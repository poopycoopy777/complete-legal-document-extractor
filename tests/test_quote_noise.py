"""Spans that are quoted but quote nothing must not reach verification.

Seen on a filed response to a motion to dismiss: the defined terms
("Plaintiff") and ("Defendants") were each "found" in the cited motion, and a
bare citation, "(Doc. 42 at p. 12).", was reported as a quotation missing from
it. Both inflate or contradict the record check without testing anything.
"""

from __future__ import annotations

from caselaw.extract import _trim_lead_in
from caselaw.group import _find_quotes, group_citations
from caselaw.record_cites import extract_record_cites


def _bodies(text: str) -> list[str]:
    return [body for _, _, body in _find_quotes(text)]


def test_defined_terms_are_not_quotations():
    text = (
        'Plaintiff Harry Cooper ("Plaintiff") responds to the Motion (Doc. 54) filed by '
        'the City of Pueblo and its officers (collectively, "Defendants"), and by the '
        'City (the “City”).'
    )
    assert _bodies(text) == []


def test_a_quoted_word_in_prose_is_still_a_quotation():
    text = 'The officer called it a "disagreement" in his report. Doc. No. 54 at 7.'
    assert _bodies(text) == ["disagreement"]


def test_a_bare_citation_is_not_a_quotation():
    assert _bodies('He was "(Doc. 42 at p. 12)." there.') == []
    assert _bodies('"Doc. No. 80 at 26; see also SAC ¶ 34"') == []


def test_a_quotation_that_mentions_a_document_survives():
    text = '"The Court should deny Doc. 54 in full." Doc. No. 61 at 3.'
    assert _bodies(text) == ["The Court should deny Doc. 54 in full."]


def test_defined_terms_do_not_attach_to_the_record():
    text = (
        'Plaintiff ("Plaintiff") opposes the Motion to Dismiss (collectively, '
        '"Defendants"). Doc. No. 54 at 1.'
    )
    (record,) = group_citations(text).as_dict()["records"]
    assert record["quotes"] == []


def test_docket_pin_written_with_a_page_abbreviation():
    (cite,) = extract_record_cites("See Doc. 42 at p. 12.")
    assert (cite.label, cite.pin) == ("42", "12")
    (cite,) = extract_record_cites("See ECF No. 42 at pp. 12-13.")
    assert (cite.label, cite.pin) == ("42", "12-13")


def test_page_marker_is_not_part_of_a_case_name():
    assert _trim_lead_in("P13 County of Sacramento") == "County of Sacramento"
    assert _trim_lead_in("County of Sacramento") == "County of Sacramento"
    assert _trim_lead_in("A12 Ashcroft") == "Ashcroft"


FOOTNOTE = (
    "The United States Supreme Court has said that the “conception defining the "
    "curtilage’ is … familiar\nenough that it is ‘easily understood from our "
    "daily experience.’” Florida v. Jardines, 569\nU.S. 1, 7 (2013) (quoting Oliver "
    "v. United States, 466 U.S. 170, 182, n. 12 (1984)."
)


def test_citation_broken_across_a_line_is_still_found():
    groups = {" ".join(g["header"]["text"].split()): g
              for g in group_citations(FOOTNOTE).as_dict()["groups"]}
    assert set(groups) == {"569 U.S. 1", "466 U.S. 170"}
    start = FOOTNOTE.index("569")
    assert tuple(groups["569 U.S. 1"]["header"]["span"]) == (start, start + 10)


def test_quote_goes_to_the_quoting_case_not_the_parenthetical():
    groups = {" ".join(g["header"]["text"].split()): g
              for g in group_citations(FOOTNOTE).as_dict()["groups"]}
    assert [q["text"][:10] for q in groups["569 U.S. 1"]["quotes"]] == ["conception"]
    assert groups["466 U.S. 170"]["quotes"] == []
