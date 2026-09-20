"""Positive-only verification behaviour.

The behaviour under test is mostly about what the verifier refuses to say.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caselaw.verify.checks import Candidate
from caselaw.verify.service import (
    MAX_GROUPS,
    STATUS_VERIFIED,
    GroupQuery,
    VerifierUnavailable,
    verify_groups,
)

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
    """Returns whatever it is told to. Records what it was asked."""

    def __init__(self, mapping=None, error=None):
        self.mapping = mapping or {}
        self.error = error
        self.asked: list[GroupQuery] = []

    def candidates(self, queries):
        self.asked = list(queries)
        if self.error:
            raise self.error
        return self.mapping


def test_verifies_a_clean_citation():
    retriever = FakeRetriever({"g0": [DOWDELL]})
    result = verify_groups([GOOD_GROUP], retriever)
    assert len(result) == 1
    assert result[0]["groupId"] == "g0"
    assert result[0]["status"] == STATUS_VERIFIED
    assert result[0]["clusterId"] == 2
    assert result[0]["checks"] == {
        "reporterCitation": True,
        "caseName": True,
        "year": True,
        "court": True,
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("page", "51"),
        ("volume", "596"),
        ("reporter", "F.2d"),
        ("defendant", "Dowdel"),
        ("plaintiff", "United State"),
        ("year", 2011),
        ("court", "ca10"),
    ],
)
def test_one_failing_check_omits_the_group(field, value):
    """All four are required. Any single failure yields nothing at all --
    not a partial result, not an adverse label."""
    group = {**GOOD_GROUP, field: value}
    assert verify_groups([group], FakeRetriever({"g0": [DOWDELL]})) == []


def test_missing_from_the_corpus_yields_nothing():
    """Absence is not evidence of fabrication.

    The corpus does not contain unpublished dispositions, very recent
    opinions, or most state trial orders.
    """
    assert verify_groups([GOOD_GROUP], FakeRetriever({"g0": []})) == []


def test_no_adverse_labels_are_ever_emitted():
    result = verify_groups([{**GOOD_GROUP, "page": "999"}], FakeRetriever({"g0": [DOWDELL]}))
    assert result == []
    blob = repr(result)
    for label in ("not_found", "invalid", "fabricated", "conflict", "unverified"):
        assert label not in blob


def test_two_passing_candidates_are_ambiguous_and_omitted():
    """If the corpus cannot tell them apart, neither can this stage.

    Choosing the higher similarity score would be guessing, and similarity is
    not evidence of identity.
    """
    twin = Candidate(
        cluster_id=77,
        case_name="United States v. Dowdell",
        court_id="ca1",
        date_filed="2010-02-12",
        content="United States v. Dowdell 595 F.3d 50 (ca1 2010) No. 08-9999",
    )
    assert verify_groups([GOOD_GROUP], FakeRetriever({"g0": [DOWDELL, twin]})) == []


def test_the_right_candidate_still_wins_among_wrong_ones():
    """Ambiguity means two *passing* candidates, not two candidates."""
    noise = Candidate(
        cluster_id=88,
        case_name="Someone v. Else",
        court_id="ca10",
        date_filed="1999-01-01",
        content="Someone v. Else 1 F.3d 1 (ca10 1999)",
    )
    result = verify_groups([GOOD_GROUP], FakeRetriever({"g0": [noise, DOWDELL]}))
    assert [r["clusterId"] for r in result] == [2]


class TestShortFormsAreNeverQueried:
    def test_group_without_a_reporter_citation_is_skipped(self):
        """Id., supra and short forms inherit their group's result.

        Querying them independently would ask the corpus about a citation with
        no name, no year and often no reporter -- exactly the low-evidence
        match this stage exists to refuse.
        """
        retriever = FakeRetriever({})
        groups = [{"groupId": "g1", "plaintiff": "Smith", "defendant": "Jones"}]
        assert verify_groups(groups, retriever) == []
        assert retriever.asked == []

    def test_queryable_and_unqueryable_groups_together(self):
        retriever = FakeRetriever({"g0": [DOWDELL]})
        groups = [GOOD_GROUP, {"groupId": "g1", "plaintiff": "Smith"}]
        result = verify_groups(groups, retriever)
        assert [r["groupId"] for r in result] == ["g0"]
        assert [q.group_id for q in retriever.asked] == ["g0"]


class TestCallerCanComputeUnresolved:
    def test_by_set_difference(self):
        retriever = FakeRetriever({"g0": [DOWDELL], "g1": []})
        groups = [GOOD_GROUP, {**GOOD_GROUP, "groupId": "g1", "page": "999"}]
        result = verify_groups(groups, retriever)
        submitted = {g["groupId"] for g in groups}
        returned = {r["groupId"] for r in result}
        assert submitted - returned == {"g1"}


class TestOutageIsNotAbstention:
    def test_retriever_failure_propagates(self):
        """An outage must never look like an empty successful result."""
        retriever = FakeRetriever(error=VerifierUnavailable("database down"))
        with pytest.raises(VerifierUnavailable):
            verify_groups([GOOD_GROUP], retriever)


class TestLimits:
    def test_too_many_groups_is_rejected(self):
        groups = [{**GOOD_GROUP, "groupId": f"g{i}"} for i in range(MAX_GROUPS + 1)]
        with pytest.raises(ValueError):
            verify_groups(groups, FakeRetriever({}))

    def test_empty_request_is_fine(self):
        assert verify_groups([], FakeRetriever({})) == []


class TestGroupQuery:
    def test_unknown_fields_are_ignored(self):
        """Extraction must be able to add fields without breaking this."""
        query = GroupQuery.from_dict({**GOOD_GROUP, "somethingNew": "x", "span": [1, 2]})
        assert query.group_id == "g0"
        assert query.is_queryable

    def test_non_numeric_year_becomes_none(self):
        assert GroupQuery.from_dict({**GOOD_GROUP, "year": "n.d."}).year is None

    def test_blank_strings_become_none(self):
        query = GroupQuery.from_dict({**GOOD_GROUP, "court": "   "})
        assert query.court is None
