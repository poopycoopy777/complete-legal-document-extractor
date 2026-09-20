"""Turn extracted case groups into conclusively verified ones, or nothing.

Positive-only. A group that is missing from the corpus, weakly matched,
ambiguous between candidates, or conflicting on any check is omitted from the
result rather than labelled. The corpus is a CourtListener snapshot, not the
universe of American law: unpublished dispositions, very recent opinions and
state trial orders are simply not in it, so absence is not evidence of
fabrication. Emitting "not found" for those would manufacture an accusation
against a real citation, and later verification stages must stay free to reach
them.

The caller finds what is unresolved by set difference: submitted group ids
minus returned group ids. Unresolved means this stage reached no conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .checks import Candidate, check_court, check_name, check_reporter, check_year

STATUS_VERIFIED = "citation_verified"

# Guards a document-sized request. A brief with more full citations than this
# is unusual enough to be worth a deliberate second call.
MAX_GROUPS = 500


class VerifierUnavailable(RuntimeError):
    """The verifier could not run.

    Distinct from abstention on purpose. An empty result means "ran and
    concluded nothing"; this means "did not run". Disguising an outage as an
    empty success would silently under-report every citation in a document.
    """


@dataclass(frozen=True)
class GroupQuery:
    """One extracted full-case citation, as the verifier needs it."""

    group_id: str
    volume: str | None = None
    reporter: str | None = None
    page: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    year: int | None = None
    court: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> GroupQuery:
        year = payload.get("year")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None
        return cls(
            group_id=str(payload.get("groupId") or payload.get("group_id") or ""),
            volume=_clean(payload.get("volume")),
            reporter=_clean(payload.get("reporter")),
            page=_clean(payload.get("page")),
            plaintiff=_clean(payload.get("plaintiff")),
            defendant=_clean(payload.get("defendant")),
            year=year,
            court=_clean(payload.get("court")),
        )

    @property
    def is_queryable(self) -> bool:
        """Without a reporter citation, check 1 can never pass.

        Skipping these is abstention, not an error: short forms, `Id.` and
        `supra` inherit their group's result and are never asked about
        independently.
        """
        return bool(self.volume and self.reporter and self.page and self.group_id)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass
class VerifiedCase:
    group_id: str
    cluster_id: int | None
    status: str = STATUS_VERIFIED
    checks: dict[str, bool] = field(
        default_factory=lambda: {
            "reporterCitation": True,
            "caseName": True,
            "year": True,
            "court": True,
        }
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "groupId": self.group_id,
            "status": self.status,
            "clusterId": self.cluster_id,
            "checks": dict(self.checks),
        }


class Retriever(Protocol):
    """Supplies candidates to examine. Never decides anything.

    Vector similarity chooses what to look at; the four deterministic checks
    decide. A candidate retrieved at cosine 0.99 that fails the year check is
    rejected exactly as hard as one retrieved at 0.30.
    """

    def candidates(self, queries: list[GroupQuery]) -> dict[str, list[Candidate]]:
        ...


def passes_all(query: GroupQuery, candidate: Candidate) -> bool:
    return (
        check_reporter(query.volume, query.reporter, query.page, candidate)
        and check_name(query.plaintiff, query.defendant, candidate)
        and check_year(query.year, candidate)
        and check_court(query.court, candidate)
    )


def verify_groups(
    payload_groups: list[dict[str, Any]], retriever: Retriever
) -> list[dict[str, Any]]:
    """Verify what can be verified. Return only that."""
    if len(payload_groups) > MAX_GROUPS:
        raise ValueError(f"At most {MAX_GROUPS} groups per request.")

    queries = [GroupQuery.from_dict(g) for g in payload_groups]
    queryable = [q for q in queries if q.is_queryable]
    if not queryable:
        return []

    verified: list[dict[str, Any]] = []
    pending = list(queryable)

    # Escalation. Retrieval latency is linear in probe depth, and most
    # citations are found at the shallowest setting, so the deep search is
    # spent only on the ones that need it. A rung that resolves a group takes
    # it out of the next, more expensive, rung.
    #
    # Note the semantics this buys: a group resolved cheaply is not re-examined
    # deeply, so the ambiguity guard below only ever sees one rung's candidate
    # set. Two genuinely indistinguishable rows could therefore be split across
    # rungs and the shallower one accepted. Each rung uses a wide top_k so both
    # twins land in the same set when they exist.
    for rung in _rungs(retriever):
        if not pending:
            break
        found = _retrieve(retriever, pending, rung)
        still_pending: list[GroupQuery] = []
        for query in pending:
            matches = [
                c for c in found.get(query.group_id, []) if passes_all(query, c)
            ]
            # Two candidates passing every check means the corpus cannot tell
            # them apart either. Picking the higher similarity score would be
            # guessing, and similarity is not evidence of identity.
            if len(matches) == 1:
                verified.append(
                    VerifiedCase(
                        group_id=query.group_id, cluster_id=matches[0].cluster_id
                    ).as_dict()
                )
            elif not matches:
                # Nothing passed: a deeper search may simply not have reached
                # the right row yet.
                still_pending.append(query)
            # Ambiguous stays omitted and is not escalated: searching deeper
            # can only find more candidates, never fewer.
        pending = still_pending
    return verified


def _rungs(retriever: Retriever) -> list[int | None]:
    """The probe depths to try, shallowest first.

    A retriever that cannot vary probe depth -- a fake, or a future backend
    without an ANN index -- gets a single pass at whatever it does.
    """
    if not hasattr(retriever, "candidates_at"):
        return [None]
    ladder = getattr(retriever, "ladder", None)
    return list(ladder) if ladder else [getattr(retriever, "probes", None)]


def _retrieve(
    retriever: Retriever, queries: list[GroupQuery], rung: int | None
) -> dict[str, list[Candidate]]:
    if rung is not None and hasattr(retriever, "candidates_at"):
        return retriever.candidates_at(queries, rung)
    return retriever.candidates(queries)


# The retriever is injected rather than imported, so the endpoint, the tests
# and a future live implementation cannot drift apart. Until one is registered
# the endpoint answers 503: not configured is an outage, not an abstention.
_RETRIEVER: Retriever | None = None


def set_retriever(retriever: Retriever | None) -> None:
    global _RETRIEVER
    _RETRIEVER = retriever


def get_retriever() -> Retriever | None:
    return _RETRIEVER
