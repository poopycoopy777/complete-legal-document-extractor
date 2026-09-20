"""Regression tests for the case law extraction layer.

The eyecite_* tests document upstream behaviour in eyecite 2.7.8. If one of them
fails after an upgrade, the corresponding workaround in caselaw/extract.py may be
removable.
"""

import sys
from pathlib import Path

import pytest
from eyecite import get_citations

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from caselaw.extract import extract, extract_pairs

BRIEF = (
    "Plaintiff relies on Monell v. Department of Social Services, "
    "436 U.S. 658, 690-91 (1978). See also Bell Atlantic Corp. v. Twombly, "
    "550 U.S. 544, 570 (2007). The Tenth Circuit applied Monell in "
    "Schneider v. City of Grand Junction, 717 F.3d 760, 770 (10th Cir. 2013). "
    "Id. at 771. Graham v. Connor, 490 U.S. 386 (1989)."
)


# --- upstream behaviour being worked around -------------------------------


def test_eyecite_leaks_prior_year_across_a_sentence():
    """eyecite's backward scan reads the PRIOR citation's year parenthetical."""
    text = (
        "Monell v. Department of Social Services, 436 U.S. 658 (1978). "
        "Schneider v. City of Grand Junction, 717 F.3d 760 (10th Cir. 2013)."
    )
    years = [c.year for c in get_citations(text)]
    assert years == [2013, 1978], f"upstream behaviour changed: {years}"


def test_eyecite_is_correct_on_an_isolated_citation():
    """Detection and metadata are sound when no prior citation interferes."""
    (cite,) = get_citations(
        "Schneider v. City of Grand Junction, 717 F.3d 760, 770 (10th Cir. 2013)."
    )
    assert cite.year == 2013
    assert cite.metadata.court == "ca10"
    assert cite.metadata.pin_cite == "770"


# --- the extraction layer --------------------------------------------------


def test_years_are_taken_from_each_citation_s_own_parenthetical():
    years = [c.year for c in extract(BRIEF) if c.kind == "FullCaseCitation"]
    assert years == [1978, 2007, 2013, 1989]


def test_year_corrections_are_flagged_not_silent():
    corrected = [
        c
        for c in extract(BRIEF)
        if any(f.startswith("year_corrected") for f in c.flags)
    ]
    assert {c.text for c in corrected} == {"436 U.S. 658", "550 U.S. 544"}


def test_party_names_do_not_bleed_between_citations():
    parties = [
        (c.plaintiff, c.defendant)
        for c in extract(BRIEF)
        if c.kind == "FullCaseCitation"
    ]
    assert parties == [
        ("Monell", "Department of Social Services"),
        ("Bell Atlantic Corp.", "Twombly"),
        ("Schneider", "City of Grand Junction"),
        ("Graham", "Connor"),
    ]


def test_lead_in_prose_is_stripped_from_the_plaintiff():
    (cite,) = [c for c in extract(BRIEF) if c.text == "436 U.S. 658"]
    assert cite.plaintiff == "Monell"


def test_courts_are_resolved():
    courts = [c.court for c in extract(BRIEF) if c.kind == "FullCaseCitation"]
    assert courts == ["scotus", "scotus", "ca10", "scotus"]


def test_reporter_volume_page_are_split_out():
    (cite,) = [c for c in extract(BRIEF) if c.text == "717 F.3d 760"]
    assert (cite.volume, cite.reporter, cite.page) == ("717", "F.3d", "760")
    assert cite.pin_cite == "770"


def test_spans_are_exact_offsets_into_the_source_text():
    """Provenance: every span must slice back to its own citation text."""
    for cite in extract(BRIEF):
        start, end = cite.span
        assert BRIEF[start:end] == cite.text


def test_short_and_id_forms_are_captured():
    kinds = [c.kind for c in extract(BRIEF)]
    assert "IdCitation" in kinds


def test_supra_captures_its_antecedent():
    text = (
        "Bell Atlantic Corp. v. Twombly, 550 U.S. 544 (2007). Twombly, supra, at 556."
    )
    supra = [c for c in extract(text) if c.kind == "SupraCitation"]
    assert supra and supra[0].antecedent == "Twombly"


def test_short_case_citation_is_detected():
    text = (
        "Bell Atlantic Corp. v. Twombly, 550 U.S. 544 (2007). "
        "The Court so held. 550 U.S. at 555."
    )
    shorts = [c for c in extract(text) if c.kind == "ShortCaseCitation"]
    assert shorts and shorts[0].pin_cite == "555"


@pytest.mark.parametrize(
    "text,volume,reporter,page,year",
    [
        ("Roe v. Wade, 410 U.S. 113 (1973).", "410", "U.S.", "113", 1973),
        (
            "Smith v. Jones, 123 F. Supp. 2d 456 (D. Colo. 2000).",
            "123",
            "F. Supp. 2d",
            "456",
            2000,
        ),
        ("People v. Doe, 42 P.3d 1234 (Colo. 2002).", "42", "P.3d", "1234", 2002),
        ("In re Estate, 99 N.E.2d 1 (N.Y. 1951).", "99", "N.E.2d", "1", 1951),
    ],
)
def test_reporter_formats(text, volume, reporter, page, year):
    (cite,) = [c for c in extract(text) if c.kind == "FullCaseCitation"]
    assert (cite.volume, cite.reporter, cite.page, cite.year) == (
        volume,
        reporter,
        page,
        year,
    )


def test_empty_and_citationless_text():
    assert extract("") == []
    assert extract("There are no citations in this sentence.") == []


def test_no_citation_is_dropped_or_duplicated():
    cites = extract(BRIEF)
    starts = [c.span[0] for c in cites]
    assert starts == sorted(starts)
    assert len(starts) == len(set(starts))


@pytest.mark.parametrize(
    "lead_in",
    [
        "Under",
        "See",
        "See also",
        "Accord",
        "Citing",
        "But see",
        "Compare",
        "The court applied",
        "Plaintiff relies on",
        "Quoting",
    ],
)
def test_bluebook_signals_are_not_absorbed_into_the_plaintiff(lead_in):
    text = f"{lead_in} Monell v. Department of Social Services, 436 U.S. 658 (1978)."
    (cite,) = [c for c in extract(text) if c.kind == "FullCaseCitation"]
    assert cite.plaintiff == "Monell"


def test_apostrophes_and_abbreviations_survive_in_party_names():
    text = "Accord Bd. of Cnty. Comm'rs v. Brown, 520 U.S. 397, 403 (1997)."
    (cite,) = [c for c in extract(text) if c.kind == "FullCaseCitation"]
    assert cite.plaintiff == "Bd. of Cnty. Comm'rs"
    assert cite.defendant == "Brown"


def test_ampersand_party_names():
    text = "Waller v. City & County of Denver, 932 F.3d 1277 (10th Cir. 2019)."
    (cite,) = [c for c in extract(text) if c.kind == "FullCaseCitation"]
    assert cite.defendant == "City & County of Denver"


def test_single_word_party_is_not_stripped_away():
    text = "In re Grand Jury, 111 F.3d 1 (1st Cir. 1997)."
    cites = [c for c in extract(text) if c.kind == "FullCaseCitation"]
    assert cites and cites[0].year == 1997


def test_curly_apostrophes_in_party_names():
    """Real filings use typographic apostrophes, not ASCII ones."""
    text = "Accord Bd. of Cnty. Comm’rs v. Brown, 520 U.S. 397, 404 (1997)."
    (cite,) = [c for c in extract(text) if c.kind == "FullCaseCitation"]
    assert cite.plaintiff == "Bd. of Cnty. Comm’rs"
    assert cite.defendant == "Brown"


class TestNonAdversarialCaptions:
    """Captions with no "v." at all: one party, not two.

    Domestic relations, dependency and neglect, probate and juvenile cases are
    all cited this way. A case-name pattern built only around "v." drops the
    whole class, which in family law is most of the precedent.
    """

    @pytest.mark.parametrize(
        "text,expected",
        [
            (
                "In re Marriage of Rubio, 313 P.3d 623 (Colo. App. 2011).",
                "In re Marriage of Rubio",
            ),
            (
                "People in the Interest of C.A.G., 903 P.2d 1229 (Colo. App. 1995).",
                "People in the Interest of C.A.G.",
            ),
            (
                "In the Matter of the Estate of Smith, 100 P.3d 1 (Colo. 2004).",
                "In the Matter of the Estate of Smith",
            ),
            ("Ex parte Young, 209 U.S. 123 (1908).", "Ex parte Young"),
            (
                "In re the Marriage of Jones, 55 P.3d 2 (Colo. App. 2002).",
                "In re the Marriage of Jones",
            ),
        ],
    )
    def test_captures_the_caption(self, text, expected):
        full = [c for _, c in extract_pairs(text) if c.kind == "FullCaseCitation"]
        assert full, f"no full citation extracted from {text!r}"
        assert full[0].case_name == expected
        assert full[0].plaintiff is None
        assert full[0].defendant is None

    def test_adversarial_captions_are_unaffected(self):
        full = [
            c
            for _, c in extract_pairs(
                "See United States v. Dowdell, 595 F.3d 50 (1st Cir. 2010)."
            )
            if c.kind == "FullCaseCitation"
        ]
        assert full[0].plaintiff == "United States"
        assert full[0].defendant == "Dowdell"
        assert full[0].case_name is None

    def test_the_caption_reaches_the_assembled_citation(self):
        full = [
            c
            for _, c in extract_pairs(
                "In re Marriage of Rubio, 313 P.3d 623 (Colo. App. 2011)."
            )
            if c.kind == "FullCaseCitation"
        ]
        assert full[0].full_citation.startswith("In re Marriage of Rubio, 313 P.3d 623")

    def test_an_opener_with_nothing_after_it_is_not_a_name(self):
        """"In re" alone is boilerplate, not a case."""
        full = [
            c
            for _, c in extract_pairs("See In re, 313 P.3d 623 (Colo. App. 2011).")
            if c.kind == "FullCaseCitation"
        ]
        assert full[0].case_name is None

    def test_prose_before_the_opener_is_not_dragged_in(self):
        """Anchored on the last opener, so a preceding sentence cannot bleed
        into the caption."""
        text = (
            "The court discussed the matter of custody at length. "
            "In re Marriage of Rubio, 313 P.3d 623 (Colo. App. 2011)."
        )
        full = [c for _, c in extract_pairs(text) if c.kind == "FullCaseCitation"]
        assert full[0].case_name == "In re Marriage of Rubio"
