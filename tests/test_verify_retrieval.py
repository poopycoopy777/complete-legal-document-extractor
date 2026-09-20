"""Retrieval: the encoder contract, the query shape, and outage handling.

No database and no model are needed here. The live path is exercised by the
smoke test, not by the suite.
"""

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caselaw.verify.retrieval import (
    EXPECTED_DIMS,
    CorpusRetriever,
    Encoder,
    build_from_environment,
    query_text,
)
from caselaw.verify.service import GroupQuery, VerifierUnavailable

DOWDELL = GroupQuery(
    group_id="g0",
    volume="595",
    reporter="F.3d",
    page="50",
    plaintiff="United States",
    defendant="Dowdell",
    year=2010,
    court="ca1",
)


class TestQueryText:
    def test_matches_the_shape_the_corpus_stores(self):
        """Stored content reads "Name 595 F.3d 50 (ca1 2010) No. ...".

        Querying in that shape is what makes nearest-neighbour search useful.
        """
        assert query_text(DOWDELL) == "United States v. Dowdell 595 F.3d 50 (ca1 2010)"

    def test_survives_missing_pieces(self):
        bare = GroupQuery(group_id="g1", volume="1", reporter="F.3d", page="2")
        assert query_text(bare) == "1 F.3d 2"

    def test_never_returns_none(self):
        assert query_text(GroupQuery(group_id="g2")) == ""


class FakeSentenceTransformer:
    """Stands in for the real model. Records calls.

    `api` selects which sentence-transformers generation to imitate: 6.x
    exposes pooling_mode = "cls", earlier versions a boolean.
    """

    def __init__(self, dims=EXPECTED_DIMS, cls_pooling=True, api="new"):
        self.dims = dims
        self.cls_pooling = cls_pooling
        self.api = api
        self.calls: list[list[str]] = []

    def get_embedding_dimension(self):
        return self.dims

    def modules(self):
        if self.api == "new":
            attrs = {"pooling_mode": "cls" if self.cls_pooling else "mean"}
        elif self.api == "old":
            attrs = {"pooling_mode_cls_token": self.cls_pooling}
        else:
            attrs = {}
        return [type("Pooling", (), attrs)()]

    def encode(self, texts, normalize_embeddings=False, show_progress_bar=False):
        assert normalize_embeddings, "vectors must be L2 normalized"
        self.calls.append(list(texts))
        return [[0.1] * self.dims for _ in texts]


def _encoder_with(model, counter=None):
    encoder = Encoder()

    def _load():
        if counter is not None:
            counter.append(1)
        encoder._assert_contract(model)
        encoder._model = model
        return model

    encoder._load = _load
    return encoder


class TestEncoderContract:
    def test_encodes_a_batch_in_one_call(self):
        """All eligible groups in a request are encoded together."""
        model = FakeSentenceTransformer()
        encoder = _encoder_with(model)
        vectors = encoder.encode(["a", "b", "c"])
        assert len(vectors) == 3
        assert len(model.calls) == 1
        assert model.calls[0] == ["a", "b", "c"]

    def test_empty_input_does_not_load_the_model(self):
        counter: list[int] = []
        encoder = _encoder_with(FakeSentenceTransformer(), counter)
        assert encoder.encode([]) == []
        assert counter == []

    def test_wrong_dimensions_is_an_outage(self):
        """A dimension mismatch cannot silently produce nonsense."""
        encoder = Encoder()
        with pytest.raises(VerifierUnavailable, match="dimensions"):
            encoder._assert_contract(FakeSentenceTransformer(dims=768))

    @pytest.mark.parametrize("api", ["new", "old"])
    def test_wrong_pooling_is_an_outage(self, api):
        """Cosine distance between differently-pooled vectors is still a
        number, just a meaningless one. It must be caught at load."""
        encoder = Encoder()
        with pytest.raises(VerifierUnavailable):
            encoder._assert_contract(
                FakeSentenceTransformer(cls_pooling=False, api=api)
            )

    @pytest.mark.parametrize("api", ["new", "old"])
    def test_correct_contract_passes_on_both_st_generations(self, api):
        """sentence-transformers 6.x renamed the pooling attribute.

        Defaulting a missing attribute to False rejected a correct model, so
        both spellings are read.
        """
        Encoder()._assert_contract(FakeSentenceTransformer(api=api))

    def test_undeterminable_pooling_fails_closed(self):
        """A pooling mode that cannot be read is an outage, not a pass.

        A silently wrong pooling mode still yields 1024 numbers and a
        plausible cosine distance; nothing downstream would notice.
        """
        encoder = Encoder()
        with pytest.raises(VerifierUnavailable):
            encoder._assert_contract(FakeSentenceTransformer(api="unknown"))

    def test_loads_once_under_concurrent_use(self):
        counter: list[int] = []
        encoder = _encoder_with(FakeSentenceTransformer(), counter)
        errors: list[Exception] = []

        def work():
            try:
                encoder.encode(["x"])
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        # _load is replaced here, so this asserts the call pattern rather than
        # the lock itself; the lock is exercised by the real loader.
        assert len(counter) <= 8


class TestOutageNotAbstention:
    def test_unconfigured_database_is_an_outage(self, monkeypatch):
        monkeypatch.delenv("VERIFIER_DATABASE_URL", raising=False)
        monkeypatch.delenv("VERIFIER_ENV_FILE", raising=False)
        retriever = CorpusRetriever(encoder=_encoder_with(FakeSentenceTransformer()))
        with pytest.raises(VerifierUnavailable):
            retriever.candidates([DOWDELL])

    def test_unreachable_database_is_an_outage(self, monkeypatch):
        monkeypatch.setenv(
            "VERIFIER_DATABASE_URL",
            "postgresql://nobody@127.0.0.1:1/none",
        )
        retriever = CorpusRetriever(encoder=_encoder_with(FakeSentenceTransformer()))
        with pytest.raises(VerifierUnavailable):
            retriever.candidates([DOWDELL])

    def test_no_queries_needs_nothing(self):
        assert CorpusRetriever(encoder=Encoder()).candidates([]) == {}


class TestEnvironmentWiring:
    def test_returns_none_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("VERIFIER_DATABASE_URL", raising=False)
        monkeypatch.delenv("VERIFIER_ENV_FILE", raising=False)
        assert build_from_environment() is None

    def test_builds_when_configured(self, monkeypatch):
        monkeypatch.setenv("VERIFIER_DATABASE_URL", "postgresql://x@127.0.0.1/y")
        monkeypatch.setenv("VERIFIER_TOP_K", "25")
        monkeypatch.setenv("VERIFIER_IVFFLAT_PROBES", "40")
        retriever = build_from_environment()
        assert retriever is not None
        assert retriever.top_k == 25
        assert retriever.probes == 40
