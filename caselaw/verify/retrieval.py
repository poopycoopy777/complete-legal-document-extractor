"""Candidate retrieval: encode the citation, search the corpus, hand back rows.

This module chooses what to look at. It never decides anything. The four
deterministic checks in `checks.py` do that, and a candidate retrieved at
cosine 0.99 that fails the year check is rejected exactly as hard as one
retrieved at 0.30.

Two failure modes are kept strictly apart. A query that finds nothing is an
abstention and returns an empty list. A model that will not load, a database
that is unreachable, or a statement that times out is a `VerifierUnavailable`,
which the endpoint turns into 503. An outage must never look like "nothing
verified".
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

from .checks import Candidate
from .service import GroupQuery, VerifierUnavailable

NAMESPACE = "courtlistener_metadata"
SOURCE_TYPE = "cluster_metadata"
TABLE = "public.vector_records"

MODEL_NAME = "BAAI/bge-m3"
EXPECTED_DIMS = 1024

# The contract the stored vectors declare. A mismatch does not raise anywhere:
# cosine distance between differently-pooled vectors is still a number, just a
# meaningless one. So it is asserted at load time instead.
MODEL_CONTRACT = "st:BAAI/bge-m3:cls:norm"

# How many candidates to examine per citation. Retrieval only has to put the
# right case somewhere in this list; the checks do the discriminating. Wider
# costs latency, not precision.
DEFAULT_TOP_K = 50

# PROVISIONAL, measured 2026-09-20 on eight citations. Not a calibration.
#
# pgvector defaults ivfflat.probes to 1, which on a ~3162-list index scans
# about 0.03% of the corpus. Roe v. Wade at 410 U.S. 113 was not in the top
# 500 candidates at that setting; it appeared at probes=100. The corpus holds
# many rows per famous case -- cert grants, rehearing denials, orders -- and
# those crowd out the merits opinion, so the failure is recall, never
# precision: a missed row abstains, it does not verify wrongly.
#
# The value that ships must come from the held-out benchmark, measuring
# candidate recall and latency together. 100 is where one probe started
# working, not where the curve flattens.
DEFAULT_PROBES = 100

# A verification request must never hold a connection open indefinitely.
STATEMENT_TIMEOUT_MS = 30_000

# An unreachable corpus host must fail fast, not inherit the OS TCP timeout.
CONNECT_TIMEOUT_S = 5


class Encoder:
    """Lazily loads bge-m3 once per process and encodes query strings.

    The model is large and loading it is slow, so it loads on first use rather
    than at import, behind a lock so concurrent requests cannot trigger
    duplicate loads.
    """

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            # Checked again inside the lock: another thread may have loaded it
            # while this one was waiting.
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise VerifierUnavailable(
                    "sentence-transformers is not installed; case verification "
                    "cannot run."
                ) from exc
            try:
                model = SentenceTransformer(self.model_name)
            except Exception as exc:
                raise VerifierUnavailable(
                    f"Could not load {self.model_name}: {type(exc).__name__}"
                ) from exc
            self._assert_contract(model)
            self._model = model
            return self._model

    def _assert_contract(self, model: Any) -> None:
        """Fail loudly when the query path does not match the stored vectors.

        Fails closed. If the pooling mode cannot be determined at all, that is
        an outage rather than a pass: a silently wrong pooling mode still
        produces 1024 numbers and a plausible cosine distance, so there is no
        later point at which the mistake becomes visible.
        """
        dims = None
        for method in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
            getter = getattr(model, method, None)
            if callable(getter):
                dims = getter()
                break
        if dims != EXPECTED_DIMS:
            raise VerifierUnavailable(
                f"{self.model_name} produces {dims} dimensions, "
                f"the corpus stores {EXPECTED_DIMS}."
            )

        pooling = None
        for module in model.modules():
            if type(module).__name__ == "Pooling":
                pooling = module
                break
        if pooling is None:
            raise VerifierUnavailable(
                f"{self.model_name} has no pooling module; cannot confirm "
                f"{MODEL_CONTRACT}."
            )

        # sentence-transformers 6.x exposes pooling_mode = "cls"; earlier
        # versions expose a pooling_mode_cls_token boolean. Support both
        # rather than defaulting a missing attribute to False, which rejects a
        # correct model.
        mode = getattr(pooling, "pooling_mode", None)
        if mode is not None:
            is_cls = str(mode).lower() == "cls"
        elif hasattr(pooling, "pooling_mode_cls_token"):
            is_cls = bool(pooling.pooling_mode_cls_token)
        else:
            raise VerifierUnavailable(
                "Cannot determine the pooling mode of "
                f"{self.model_name}; cannot confirm {MODEL_CONTRACT}."
            )
        if not is_cls:
            raise VerifierUnavailable(
                f"{self.model_name} is using {mode!r} pooling, not CLS; the "
                f"corpus vectors declare {MODEL_CONTRACT}."
            )

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode in one batch, L2-normalized, as the stored contract requires."""
        if not texts:
            return []
        model = self._load()
        try:
            vectors = model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False
            )
        except Exception as exc:
            raise VerifierUnavailable(
                f"Encoding failed: {type(exc).__name__}"
            ) from exc
        return [list(map(float, v)) for v in vectors]


def query_text(query: GroupQuery) -> str:
    """Render a citation the way the corpus stores one.

    The stored content reads "Case Name 595 F.3d 50 (ca1 2010) No. 08-1855",
    so the query is built in that shape rather than as a sentence. Matching the
    stored form is what makes nearest-neighbour search useful here.
    """
    parts: list[str] = []
    if query.plaintiff and query.defendant:
        parts.append(f"{query.plaintiff} v. {query.defendant}")
    if query.volume and query.reporter and query.page:
        parts.append(f"{query.volume} {query.reporter} {query.page}")
    court_year = " ".join(p for p in (query.court, str(query.year or "")) if p).strip()
    if court_year:
        parts.append(f"({court_year})")
    return " ".join(parts).strip()


def _connection_url() -> str:
    """Never printed. Callers see failures by exception type only."""
    url = os.environ.get("VERIFIER_DATABASE_URL")
    if not url:
        env_path = os.environ.get("VERIFIER_ENV_FILE")
        if env_path and Path(env_path).is_file():
            for line in Path(env_path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.strip().startswith("DATABASE_URL"):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not url:
        raise VerifierUnavailable("No corpus database configured.")
    # SQLAlchemy-style driver suffixes are not valid libpq URLs.
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


class CorpusRetriever:
    """Cosine nearest-neighbour search over the CourtListener metadata vectors.

    Every statement runs in a read-only transaction with a timeout, and every
    value is a bound parameter.
    """

    def __init__(
        self,
        encoder: Encoder | None = None,
        top_k: int = DEFAULT_TOP_K,
        probes: int | None = DEFAULT_PROBES,
    ) -> None:
        self.encoder = encoder or Encoder()
        self.top_k = top_k
        # None leaves the server default of 1, which measurably loses the
        # right row on this corpus. See DEFAULT_PROBES.
        self.probes = probes

    def candidates(
        self, queries: list[GroupQuery]
    ) -> dict[str, list[Candidate]]:
        if not queries:
            return {}

        try:
            import psycopg
        except ImportError as exc:
            raise VerifierUnavailable("psycopg is not installed.") from exc

        vectors = self.encoder.encode([query_text(q) for q in queries])

        results: dict[str, list[Candidate]] = {q.group_id: [] for q in queries}
        try:
            # Without this a verification request inherits the OS TCP timeout
            # and hangs for over a minute when the corpus host is down.
            conn = psycopg.connect(_connection_url(), connect_timeout=CONNECT_TIMEOUT_S)
        except VerifierUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - never echo the URL
            raise VerifierUnavailable(
                f"Corpus database unreachable: {type(exc).__name__}"
            ) from None

        try:
            with conn, conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                if self.probes is not None:
                    cur.execute(f"SET LOCAL ivfflat.probes = {int(self.probes)}")
                for query, vector in zip(queries, vectors, strict=True):
                    results[query.group_id] = self._search(cur, vector)
        except Exception as exc:
            raise VerifierUnavailable(
                f"Corpus query failed: {type(exc).__name__}"
            ) from exc
        finally:
            conn.close()
        return results

    def _search(self, cur: Any, vector: list[float]) -> list[Candidate]:
        literal = "[" + ",".join(f"{x:.7f}" for x in vector) + "]"
        cur.execute(
            f"SELECT metadata, content FROM {TABLE} "
            "WHERE namespace = %s AND source_type = %s "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (NAMESPACE, SOURCE_TYPE, literal, self.top_k),
        )
        found = []
        for metadata, content in cur.fetchall():
            if isinstance(metadata, str):
                import json

                metadata = json.loads(metadata)
            found.append(Candidate.from_row(metadata or {}, content or ""))
        return found


def build_from_environment() -> CorpusRetriever | None:
    """Return a retriever when the corpus is configured, otherwise None.

    None means the endpoint answers 503. Not configured is an outage, not an
    abstention: an unconfigured verifier reporting "nothing verified" would be
    indistinguishable from a document full of fabricated citations.
    """
    if not (
        os.environ.get("VERIFIER_DATABASE_URL")
        or os.environ.get("VERIFIER_ENV_FILE")
    ):
        return None
    probes = os.environ.get("VERIFIER_IVFFLAT_PROBES")
    top_k = os.environ.get("VERIFIER_TOP_K")
    return CorpusRetriever(
        top_k=int(top_k) if top_k else DEFAULT_TOP_K,
        probes=int(probes) if probes else DEFAULT_PROBES,
    )
