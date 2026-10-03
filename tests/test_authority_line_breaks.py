"""A section number split across printed lines is one provision, not two.

The brief that prompted this writes "C.R.S. Sec. 24-31-" at the end of a line,
a blank line, then "902(2)(a)". CiteURL read "Sec. 24-31" -- a provision that
does not exist -- and the report then told the filer the statute was invalid.
"""

from caselaw.authorities import extract_authorities


def _only(text):
    found = extract_authorities(text)
    assert len(found) == 1, [(a.span, a.name) for a in found]
    return found[0]


def test_section_number_split_across_blank_line_is_one_provision():
    text = 'Under C.R.S. \u00a7 24-31-\n\n902(2)(a), "[f]or all incidents".'
    found = _only(text)
    assert found.name == "Colo. Rev. Stat. \u00a7 24-31-902(2)(a)"
    assert text[found.span[0]:found.span[1]] == "C.R.S. \u00a7 24-31-\n\n902(2)(a)"
    assert found.tokens["section"] == "902"
    assert found.tokens["subsection"] == "(2)(a)"


def test_section_number_split_across_single_line_break_is_one_provision():
    text = "See C.R.S. \u00a7 24-72-\n305(7) for the remedy."
    found = _only(text)
    assert found.name == "Colo. Rev. Stat. \u00a7 24-72-305(7)"
    assert text[found.span[0]:found.span[1]] == "C.R.S. \u00a7 24-72-\n305(7)"


def test_split_subject_number_was_previously_read_as_a_bare_section():
    """Before the join, the trailing "24-31" survived as its own citation."""
    text = "The order rests on C.R.S. \u00a7 24-\n\n31-902 and nothing else."
    found = _only(text)
    assert found.name == "Colo. Rev. Stat. \u00a7 24-31-902"
    assert text[found.span[0]:found.span[1]].endswith("24-\n\n31-902")


def test_joined_text_does_not_shift_reported_spans():
    """Every span must index the original document, not the joined copy."""
    text = "Lead-in. Under C.R.S. \u00a7 24-31-\n\n902(2)(a) the agency acts. Tail."
    found = _only(text)
    body = text[found.span[0]:found.span[1]]
    assert body.startswith("C.R.S.")
    assert body.endswith("902(2)(a)")
    assert text[:found.span[0]].endswith("Under ")


def test_two_real_differently_numbered_citations_stay_separate():
    text = "Compare C.R.S. \u00a7 24-31-902(2)(a) with C.R.S. \u00a7 24-72-305(5)."
    found = extract_authorities(text)
    assert sorted(a.name for a in found) == [
        "Colo. Rev. Stat. \u00a7 24-31-902(2)(a)",
        "Colo. Rev. Stat. \u00a7 24-72-305(5)",
    ]


def test_a_split_word_is_still_joined_for_parsing():
    """A hyphenated line break in prose must not corrupt a later citation."""
    text = "the preponderance-\n\nof-the-evidence burden, then C.R.S. \u00a7 24-31-902."
    found = extract_authorities(text)
    assert [a.name for a in found] == ["Colo. Rev. Stat. \u00a7 24-31-902"]
    assert text[found[0].span[0]:found[0].span[1]] == "C.R.S. \u00a7 24-31-902"
