"""Paragraph pins between parallel citations keep one source-bound case."""

import pytest

from caselaw.extract import extract
from caselaw.group import group_citations


@pytest.mark.parametrize("pin", ["para. 12", "\u00b6 12", "paras. 12-14", "\u00b6\u00b6 12\u201314"])
def test_paragraph_pin_parallel_preserves_occurrences(pin):
    text = (f"Warne v. Hall, 2016 CO 50, {pin}, 373 P.3d 588, 593. "
            "Later, Warne, 373 P.3d at 594.")
    original = extract(text)
    result = group_citations(text)
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.case_name == "Warne v. Hall"
    citations = [group.header, *group.children]
    assert [(c.span, c.text, c.pin_cite) for c in citations] == [
        (c.span, c.text, c.pin_cite) for c in original
    ]
    assert [c.pin_cite for c in group.children] == ["593", "594"]
    assert group.children[0].plaintiff == "Warne"
    assert group.children[0].defendant == "Hall"
    assert all(text[c.span[0]:c.span[1]].strip() == c.text for c in citations)
    assert not result.orphans


@pytest.mark.parametrize("gap", ["; ", ", see ", ", para. 12; ", ", para. twelve, ", ". "])
def test_parallel_grouping_does_not_cross_separate_authorities(gap):
    text = "Warne v. Hall, 2016 CO 50" + gap + "418 P.3d 604, 608."
    assert len(group_citations(text).groups) == 2


# A brief cites a case in full once and then refers to it by party name with the
# full reporter citation: "Warne, 2016 CO 50, para. 24, 373 P.3d at 596." The
# name printed in front of the citation is the filing's own naming evidence, but
# the extractor reported those occurrences as nameless and flagged them
# "parties_unverified", which reads as a proof failure when the proof is printed
# on the page.
_REPEAT_BY_NAME = (
    "If, under any circumstances the plaintiff is entitled to relief, dismissal "
    "is improper. Warne v. Hall, 2016 CO 50, para. 12, 373 P.3d 588, 593. The "
    "standard is the same one the Colorado Supreme Court applied before the "
    "federal rules were revised. Id. at para. 16, 373 P.3d at 594. Colorado has "
    "deliberately declined to import the federal plausibility standard of Bell "
    "Atlantic Corp. v. Twombly, 550 U.S. 544 (2007). Warne, 2016 CO 50, "
    "para. 24, 373 P.3d at 596. The distinction is not semantic."
)


def _warne_occurrences():
    result = group_citations(_REPEAT_BY_NAME)
    warne = next(g for g in result.groups if g.case_name == "Warne v. Hall")
    return warne, [warne.header, *warne.children]


def test_a_repeated_full_citation_keeps_the_name_printed_before_it():
    _, occurrences = _warne_occurrences()
    repeats = [c for c in occurrences if c.text == "2016 CO 50" and c.pin_cite is None]
    assert len(repeats) == 2, [c.text for c in occurrences]
    # The first occurrence prints the full adversarial caption, so its parties
    # carry the name. The later one prints only "Warne", which is still naming
    # evidence and must not be dropped.
    named = [c for c in repeats if c.plaintiff or c.case_name]
    assert len(named) == len(repeats), [
        (c.span, c.plaintiff, c.defendant, c.case_name) for c in repeats]
    later = repeats[-1]
    assert later.plaintiff is None and later.defendant is None
    assert later.case_name == "Warne"


def test_naming_evidence_present_is_not_reported_as_a_missing_proof():
    _, occurrences = _warne_occurrences()
    # The occurrence that refers to Warne by name: "Warne, 2016 CO 50, para. 24".
    repeats = [c for c in occurrences if c.text == "2016 CO 50" and c.pin_cite is None]
    assert repeats, [c.text for c in occurrences]
    for occurrence in repeats:
        assert not any(f.startswith("parties_unverified") for f in occurrence.flags), (
            occurrence.text, occurrence.flags)


def test_an_occurrence_with_no_name_at_all_still_says_so():
    """Guards the guard: the flag must survive where it is true."""
    text = ("Twombly held nothing of the sort, 550 U.S. 544 (2007), and that is "
            "the whole of it.")
    result = group_citations(text)
    flags = [f for g in result.groups for c in (g.header, *g.children) for f in c.flags]
    assert not any(f.startswith("parties_unverified") for f in flags), flags


def test_an_introductory_signal_is_not_adopted_as_a_case_name():
    """A lone "See" before a citation is prose, not a party."""
    from caselaw.extract import _derive_short_case_name

    assert _derive_short_case_name("See, ") is None
    assert _derive_short_case_name("But see, ") is None
    assert _derive_short_case_name("Compare ") is None
    assert _derive_short_case_name("Warne, ") == "Warne"
    assert _derive_short_case_name("Bell Atlantic Corp., ") == "Bell Atlantic Corp."
    assert _derive_short_case_name("Board of County Commissioners, ") == (
        "Board of County Commissioners")


def test_a_name_window_holding_prose_is_refused():
    from caselaw.extract import _derive_short_case_name

    # eyecite's own answer for this shape crossed a sentence boundary.
    assert _derive_short_case_name("into Rule 12(b)(5). Warne, ") == "Warne"
    assert _derive_short_case_name("the claim was dismissed. ") is None
    assert _derive_short_case_name("42 U.S.C. 1983, ") is None


def test_the_group_still_reports_the_full_caption():
    warne, occurrences = _warne_occurrences()
    assert warne.case_name == "Warne v. Hall"
    assert any(c.plaintiff == "Warne" and c.defendant == "Hall" for c in occurrences)
