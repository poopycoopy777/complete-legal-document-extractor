"""POST /api/verify/cases.

The distinction this file mostly exists to pin: an empty result means the
verifier ran and concluded nothing; a 503 means it did not run. Collapsing the
two would silently under-report every citation in a document.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caselaw.verify import service as verify_service
from caselaw.verify.checks import Candidate
from server.app import app

client = TestClient(app)

DOWDELL = Candidate(
    cluster_id=2,
    case_name="United States v. Dowdell",
    court_id="ca1",
    date_filed="2010-02-12",
    content="United States v. Dowdell 595 F.3d 50 (ca1 2010) No. 08-1855",
)

GOOD_GROUP = {
    "groupId": "g0",
    "volume": "595",
    "reporter": "F.3d",
    "page": "50",
    "plaintiff": "United States",
    "defendant": "Dowdell",
    "year": 2010,
    "court": "ca1",
}


class FakeRetriever:
    def __init__(self, mapping=None, error=None):
        self.mapping = mapping or {}
        self.error = error

    def candidates(self, queries):
        if self.error:
            raise self.error
        return self.mapping


@pytest.fixture
def retriever():
    """Register a retriever for one test, then restore the real state."""
    previous = verify_service.get_retriever()

    def _install(fake):
        verify_service.set_retriever(fake)
        return fake

    yield _install
    verify_service.set_retriever(previous)


def test_unconfigured_verifier_is_503_not_empty(retriever):
    """No corpus configured is an outage, not "nothing verified"."""
    retriever(None)
    response = client.post("/api/verify/cases", json={"groups": [GOOD_GROUP]})
    assert response.status_code == 503
    assert "verified" not in response.json()


def test_verifies_a_clean_citation(retriever):
    retriever(FakeRetriever({"g0": [DOWDELL]}))
    response = client.post("/api/verify/cases", json={"groups": [GOOD_GROUP]})
    assert response.status_code == 200
    body = response.json()
    assert len(body["verified"]) == 1
    assert body["verified"][0]["status"] == "citation_verified"
    assert body["verified"][0]["clusterId"] == 2


def test_unverifiable_citation_returns_empty_200(retriever):
    """Ran, concluded nothing. Distinct from the 503 above."""
    retriever(FakeRetriever({"g0": []}))
    response = client.post("/api/verify/cases", json={"groups": [GOOD_GROUP]})
    assert response.status_code == 200
    assert response.json() == {"verified": []}


def test_retriever_outage_is_503(retriever):
    retriever(FakeRetriever(error=verify_service.VerifierUnavailable("pg down")))
    response = client.post("/api/verify/cases", json={"groups": [GOOD_GROUP]})
    assert response.status_code == 503


def test_no_adverse_label_reaches_the_wire(retriever):
    retriever(FakeRetriever({"g0": [DOWDELL]}))
    bad = {**GOOD_GROUP, "defendant": "Dowdel"}
    response = client.post("/api/verify/cases", json={"groups": [bad]})
    body = response.text
    for label in ("not_found", "fabricated", "invalid", "conflict"):
        assert label not in body


def test_too_many_groups_is_rejected(retriever):
    retriever(FakeRetriever({}))
    groups = [
        {**GOOD_GROUP, "groupId": f"g{i}"}
        for i in range(verify_service.MAX_GROUPS + 1)
    ]
    response = client.post("/api/verify/cases", json={"groups": groups})
    assert response.status_code == 413


def test_malformed_body_is_422(retriever):
    retriever(FakeRetriever({}))
    assert client.post("/api/verify/cases", json={"nope": 1}).status_code == 422


def test_empty_groups_is_fine(retriever):
    retriever(FakeRetriever({}))
    response = client.post("/api/verify/cases", json={"groups": []})
    assert response.status_code == 200
    assert response.json() == {"verified": []}


def test_extraction_output_feeds_straight_in(retriever):
    """The request shape must match what /api/extract already produces."""
    retriever(FakeRetriever({"g0": [DOWDELL]}))
    extracted = client.post(
        "/api/extract",
        json={"text": "See United States v. Dowdell, 595 F.3d 50 (1st Cir. 2010)."},
    ).json()
    groups = [
        {
            "groupId": g["id"],
            "volume": g["header"]["volume"],
            "reporter": g["header"]["reporter"],
            "page": g["header"]["page"],
            "plaintiff": g["header"]["plaintiff"],
            "defendant": g["header"]["defendant"],
            "year": g["header"]["year"],
            "court": g["header"]["court"],
        }
        for g in extracted["groups"]
    ]
    assert groups, "extraction produced no groups to verify"
    response = client.post("/api/verify/cases", json={"groups": groups})
    assert response.status_code == 200
    assert len(response.json()["verified"]) == 1
