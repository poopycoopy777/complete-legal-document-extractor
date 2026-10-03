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
