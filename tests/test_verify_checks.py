"""The four identity checks.

These tests are precision-first on purpose. Where a check could plausibly be
loosened to catch more true citations, the test pins it shut instead, because
an abstention costs nothing and a false green ends up in a filing.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caselaw.verify.checks import (
    Candidate,
    check_court,
    check_name,
    check_reporter,
    check_year,
    normalize_party,
    split_caption,
)

DOWDELL = Candidate(
    cluster_id=2,
    case_name="United States v. Dowdell",
    court_id="ca1",
    date_filed="2010-02-12",
    content=(
        "United States v. Dowdell 2010 U.S. App. LEXIS 2859, 2010 WL 481416, "
        "595 F.3d 50 (ca1 2010) No. 08-1855 "
    ),
)


class TestReporter:
    def test_matches_the_reporter_citation_in_content(self):
        assert check_reporter("595", "F.3d", "50", DOWDELL)

    def test_westlaw_and_lexis_cites_are_valid_identity_evidence(self):
        """Both are in reporters-db and both are real citation forms.

        A Westlaw number is a unique identifier, so an exact match on one is
        strong evidence of identity. Refusing them would discard it.
        """
        assert check_reporter("2010", "WL", "481416", DOWDELL)
        assert check_reporter("2010", "U.S. App. LEXIS", "2859", DOWDELL)

    def test_citation_forms_do_not_cross_contaminate(self):
        """The year of a WL cite must not satisfy a reporter cite, or vice
        versa. Each form matches only its own volume/reporter/page triple."""
        assert not check_reporter("2010", "F.3d", "481416", DOWDELL)
        assert not check_reporter("2010", "WL", "50", DOWDELL)
        assert not check_reporter("595", "WL", "50", DOWDELL)

    def test_wrong_page_fails(self):
        assert not check_reporter("595", "F.3d", "42", DOWDELL)

    def test_wrong_volume_fails(self):
        assert not check_reporter("596", "F.3d", "50", DOWDELL)

    @pytest.mark.parametrize("series", ["F.2d", "F.4th", "F."])
    def test_series_never_collapse(self, series):
        """F.2d, F.3d and F.4th are different reporters, not variants."""
        assert not check_reporter("595", series, "50", DOWDELL)

    def test_letter_for_digit_misread_fails(self):
        """OCR turns 50 into 5O. That must fail, never be repaired."""
        assert not check_reporter("595", "F.3d", "5O", DOWDELL)
        assert not check_reporter("59S", "F.3d", "50", DOWDELL)

    def test_missing_component_fails(self):
        assert not check_reporter(None, "F.3d", "50", DOWDELL)
        assert not check_reporter("595", None, "50", DOWDELL)
        assert not check_reporter("595", "F.3d", None, DOWDELL)

    def test_parallel_citation_each_side_verifies(self):
        """A row carrying two reporters verifies against either."""
        candidate = Candidate(
            cluster_id=9,
            case_name="Monell v. Department of Social Services",
            court_id="scotus",
            date_filed="1978-06-06",
            content="Monell v. Dept of Social Services 436 U.S. 658, 98 S. Ct. 2018 (scotus 1978)",
        )
        assert check_reporter("436", "U.S.", "658", candidate)
        assert check_reporter("98", "S. Ct.", "2018", candidate)


class TestName:
    def test_exact_match(self):
        assert check_name("United States", "Dowdell", DOWDELL)

    def test_case_and_punctuation_insensitive(self):
        assert check_name("UNITED STATES", "dowdell", DOWDELL)

    def test_corporate_suffix_is_dropped(self):
        candidate = Candidate(
            cluster_id=3,
            case_name="Morrissette v. Teledyne Princeton, Inc.",
            court_id="ca1",
            date_filed="2010-02-12",
            content="Morrissette v. Teledyne Princeton, Inc. 364 F. App'x 655 (ca1 2010)",
        )
        assert check_name("Morrissette", "Teledyne Princeton", candidate)
        assert check_name("Morrissette", "Teledyne Princeton, Inc.", candidate)

    def test_ampersand_and_and_are_equivalent(self):
        candidate = Candidate(
            cluster_id=4,
            case_name="Smith v. Baker & Sons",
            court_id="ca1",
            date_filed="2011-01-01",
            content="Smith v. Baker & Sons 600 F.3d 1 (ca1 2011)",
        )
        assert check_name("Smith", "Baker and Sons", candidate)

    def test_ocr_damaged_name_fails(self):
        """The failure mode this whole stage exists to catch.

        'Coffinan' for 'Coffman' extracts cleanly with no flag, because eyecite
        matches on reporter, volume and page rather than the name. Check 2 is
        the only thing that catches it, so it must not be fuzzy.
        """
        candidate = Candidate(
            cluster_id=5,
            case_name="Coffman v. Williamson",
            court_id="colo",
            date_filed="2015-04-20",
            content="Coffman v. Williamson 348 P.3d 929 (colo 2015)",
        )
        assert check_name("Coffman", "Williamson", candidate)
        assert not check_name("Coffinan", "Williamson", candidate)

    def test_party_order_is_significant(self):
        """On appeal the caption reverses; the two are not the same case."""
        assert not check_name("Dowdell", "United States", DOWDELL)

    def test_one_party_alone_is_not_enough(self):
        assert not check_name("United States", "Somebody Else", DOWDELL)
        assert not check_name("Someone Else", "Dowdell", DOWDELL)

    def test_substring_does_not_match(self):
        assert not check_name("United", "Dowd", DOWDELL)

    def test_missing_party_fails(self):
        assert not check_name(None, "Dowdell", DOWDELL)
        assert not check_name("United States", None, DOWDELL)

    def test_candidate_without_a_caption_fails(self):
        candidate = Candidate(
            cluster_id=6,
            case_name="In re Grand Jury Subpoena",
            court_id="ca1",
            date_filed="2010-01-01",
            content="In re Grand Jury Subpoena 500 F.3d 1 (ca1 2010)",
        )
        assert not check_name("In re Grand Jury", "Subpoena", candidate)


class TestYear:
    def test_exact_year_matches(self):
        assert check_year(2010, DOWDELL)

    @pytest.mark.parametrize("year", [2009, 2011])
    def test_no_tolerance_window(self, year):
        """Off-by-one admits the wrong case in a series of appeals."""
        assert not check_year(year, DOWDELL)

    def test_missing_year_fails(self):
        assert not check_year(None, DOWDELL)

    def test_candidate_without_a_date_fails(self):
        candidate = Candidate(2, "United States v. Dowdell", "ca1", None, "")
        assert not check_year(2010, candidate)


class TestCourt:
    def test_identifiers_match(self):
        assert check_court("ca1", DOWDELL)

    def test_different_court_fails(self):
        assert not check_court("ca10", DOWDELL)

    def test_unresolved_court_fails(self):
        """An unresolvable court is not a matching court.

        eyecite returns None for parentheticals it cannot resolve, such as
        'Colo. App.'. That must abstain, not pass.
        """
        assert not check_court(None, DOWDELL)

    def test_candidate_without_a_court_fails(self):
        candidate = Candidate(2, "United States v. Dowdell", None, "2010-02-12", "")
        assert not check_court("ca1", candidate)


class TestHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Teledyne Princeton, Inc.", "teledyne princeton"),
            ("Baker & Sons", "baker and sons"),
            ("  Smith   Co.  ", "smith"),
            (None, ""),
        ],
    )
    def test_normalize_party(self, raw, expected):
        assert normalize_party(raw) == expected

    @pytest.mark.parametrize(
        "caption,expected",
        [
            ("United States v. Dowdell", ("United States", "Dowdell")),
            ("Roe v Wade", ("Roe", "Wade")),
            ("In re Marriage", None),
            ("", None),
        ],
    )
    def test_split_caption(self, caption, expected):
        assert split_caption(caption) == expected
