"""A real party name is not always typed in ASCII.

PDF text layers carry the typographic characters the typesetter used: the
ligature "ff" appears as U+FB00, "fi" as U+FB01, and a name may carry a genuine
accent. The caption matcher accepted only ASCII letters in a party, so
"Pinnacol Assurance v. Hoff" -- printed with the ligature -- produced no parties
at all. The citation then reached downstream with no case name, and the identity
stage reported a caption mismatch against the very case the filing names. In
`01-2025CV36-2026-04-22-msj-denied.pdf` this produced the only unnamed group in
the whole twenty-one document order bench corpus.
"""

from __future__ import annotations

import pytest

from caselaw.extract import _derive_case_name, _derive_parties

LIGATURE_FF = "\ufb00"  # ff
LIGATURE_FI = "\ufb01"  # fi
LIGATURE_FL = "\ufb02"  # fl


class TestTypographicLigaturesInCaptions:
    def test_ligature_ff_in_a_defendant(self):
        window = f"Pinnacol\nAssurance v. Ho{LIGATURE_FF}, "
        assert _derive_parties(window) == ("Pinnacol Assurance", f"Ho{LIGATURE_FF}")

    def test_ligature_fi_in_a_defendant(self):
        window = f"Smith v. Co{LIGATURE_FI}man, "
        assert _derive_parties(window) == ("Smith", f"Co{LIGATURE_FI}man")

    def test_ligature_fl_in_a_defendant(self):
        window = f"Smith v. Su{LIGATURE_FL}olk County, "
        assert _derive_parties(window) == ("Smith", f"Su{LIGATURE_FL}olk County")

    def test_ligature_in_a_plaintiff(self):
        window = f"Ho{LIGATURE_FF}man v. Jones, "
        assert _derive_parties(window) == (f"Ho{LIGATURE_FF}man", "Jones")

    def test_accented_party_name(self):
        window = "Mu\u00f1oz v. Pe\u00f1a, "
        assert _derive_parties(window) == ("Mu\u00f1oz", "Pe\u00f1a")

    def test_a_party_may_open_on_a_non_ascii_capital(self):
        window = "\u00c5berg v. Smith, "
        assert _derive_parties(window) == ("\u00c5berg", "Smith")


class TestProseIsStillNotAParty:
    """The guard the ASCII class was protecting: a lower-case word is not a party."""

    def test_a_sentence_before_the_caption_is_cut(self):
        window = "the rule is settled. Pinnacol Assurance v. Hoff, "
        assert _derive_parties(window) == ("Pinnacol Assurance", "Hoff")

    def test_lower_case_prose_alone_is_not_a_caption(self):
        assert _derive_parties("the parties agree that this is so, ") == (None, None)

    def test_no_v_is_not_a_caption(self):
        assert _derive_parties("See generally the discussion above, ") == (None, None)

    def test_non_adversarial_caption_still_works(self):
        assert _derive_case_name("In re Marriage of Rubio, ") is not None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Ho\ufb00, ", "Ho\ufb00"),
        ("In re Marriage of Rubio, ", "In re Marriage of Rubio"),
    ],
)
def test_short_case_name_accepts_the_same_characters(text, expected):
    from caselaw.extract import _derive_short_case_name

    assert _derive_short_case_name(text) == expected


@pytest.mark.parametrize("text", ["First; Second; Warne, ", "First. Second. Warne, "])
def test_short_name_after_multiple_clause_boundaries(text):
    from caselaw.extract import _derive_short_case_name

    assert _derive_short_case_name(text) == "Warne"
