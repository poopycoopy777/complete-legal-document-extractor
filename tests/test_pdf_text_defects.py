"""Defects in how a PDF text layer reaches the case-law extractor.

Each case is copied from a filed Colorado appellate brief (2025CA2333, Opening
Brief and Reply Brief) whose saved extraction showed a false or missing issue.
"""

import pytest

from caselaw.extract import extract, extract_pairs
from caselaw.group import group_citations

# --- a table-of-authorities heading is not part of a party's name -------------

TOA_TAIL = "27 CFR Parts 447, 478 and 479 dated April 2022\n\n"
AMCO = "AMCO Ins. Co. v. Sills, 166 P.3d 274 (2007)"


@pytest.mark.parametrize("heading", [
    "Case Authorities",
    "Cases",
    "Statutory Authorities",
    "Table of Authorities",
    "TABLE OF AUTHORITIES",
    "Authorities",
    "Other Authorities",
    "Cases:",
])
def test_heading_on_its_own_line_is_not_part_of_the_plaintiff(heading):
    text = f"{TOA_TAIL}{heading}\n\n{AMCO}\n"
    (record,) = extract(text)
    assert record.plaintiff == "AMCO Ins. Co."
    assert record.defendant == "Sills"
    assert record.full_citation == "AMCO Ins. Co. v. Sills, 166 P.3d 274 (2007)"


def test_heading_directly_above_the_caption_without_a_blank_line():
    (record,) = extract("Cases\nAMCO Ins. Co. v. Sills, 166 P.3d 274 (2007)")
    assert record.plaintiff == "AMCO Ins. Co."


def test_stacked_headings_are_all_dropped():
    text = f"TABLE OF AUTHORITIES\n\nCase Authorities\n\n{AMCO}\n"
    (record,) = extract(text)
    assert record.plaintiff == "AMCO Ins. Co."


def test_group_header_carries_the_clean_name():
    result = group_citations(f"{TOA_TAIL}Case Authorities\n\n{AMCO}\n")
    (group,) = result.groups
    assert group.header.plaintiff == "AMCO Ins. Co."
    assert group.header.full_citation.startswith("AMCO Ins. Co. v. Sills")


@pytest.mark.parametrize("caption,plaintiff", [
    ("Case Authorities Inc. v. Smith, 100 P.3d 100 (Colo. 2004)", "Case Authorities Inc."),
    ("Cases Unlimited v. Smith, 100 P.3d 100 (Colo. 2004)", "Cases Unlimited"),
    ("Authorities Bank v. Smith, 100 P.3d 100 (Colo. 2004)", "Authorities Bank"),
])
def test_party_name_that_starts_with_heading_words_on_the_same_line_is_kept(caption, plaintiff):
    (record,) = extract(caption)
    assert record.plaintiff == plaintiff


def test_party_name_starting_with_heading_words_survives_below_a_real_heading():
    text = "Cases\n\nCase Authorities Inc. v. Smith, 100 P.3d 100 (Colo. 2004)\n"
    (record,) = extract(text)
    assert record.plaintiff == "Case Authorities Inc."


def test_existing_table_of_authorities_prefix_still_removed():
    text = "TABLE OF AUTHORITIES Cases AMCO Ins. Co. v. Sills, 166 P.3d 274 (2007)"
    (record,) = extract(text)
    assert record.plaintiff == "AMCO Ins. Co."


# --- an Id. does not swallow the next numbered paragraph ----------------------

JOHNSON = "People v. Johnson, 671 P.2d 958 (Colo. 1983). "


def _ids(text):
    return [r for r in extract(text) if r.kind == "IdCitation"]


def test_id_does_not_take_the_next_paragraph_number_as_a_pin():
    text = (
        JOHNSON
        + "If that final order is to be enforceable then the party that is "
        "aggrieved has standing to appeal. Id.\n\n   14. Any issue with the "
        "search warrant is not subject of this appeal.\n"
    )
    (found,) = _ids(text)
    assert found.text == "Id."
    assert found.pin_cite is None
    assert text[slice(*found.span)] == "Id."


def test_id_does_not_take_a_paragraph_number_after_a_single_line_break():
    text = JOHNSON + "Held so. Id.\n14. Any issue with the warrant.\n"
    (found,) = _ids(text)
    assert found.text == "Id."
    assert found.pin_cite is None


def test_id_is_not_orphaned_by_the_paragraph_number():
    text = JOHNSON + "Held so. Id.\n\n   14. Any issue with the warrant.\n"
    result = group_citations(text)
    (group,) = result.groups
    assert [c.text for c in group.children] == ["Id."]
    assert result.orphans == []


def test_id_with_an_explicit_pin_keeps_it_even_before_a_paragraph_number():
    text = JOHNSON + "Held so. Id. at 962.\n\n   14. Any issue with the warrant.\n"
    (found,) = _ids(text)
    assert found.pin_cite == "at 962"
    assert text[slice(*found.span)].startswith("Id. at 962")


def test_id_pin_on_the_same_line_is_not_a_paragraph_marker():
    text = JOHNSON + "Held so. Id. 962 (describing the standard).\n"
    (found,) = _ids(text)
    assert found.pin_cite == "962"


# --- an incomplete citation is surfaced, not dropped --------------------------

WOO_BODY = (
    "Both cases matter. Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d "
    "(Colo., 2022) and People v.\n\n  Woo, 579 P.3d 459 (Colo.App., 2025).\n"
)


def _incomplete(records):
    return [r for r in records if r.kind == "UnknownCitation"]


def test_citation_without_a_first_page_is_reported_and_flagged():
    (found,) = _incomplete(extract(WOO_BODY))
    assert found.text == "528 P.3d"
    assert (found.volume, found.reporter, found.page) == ("528", "P.3d", None)
    assert any(flag.startswith("incomplete: no first page") for flag in found.flags)
    assert found.full_citation is None


def test_incomplete_citation_keeps_the_caption_and_year_it_printed():
    (found,) = _incomplete(extract(WOO_BODY))
    assert found.plaintiff == "Woo"
    assert found.defendant == "El Paso County Sheriff\u2019s Office"
    assert found.year == 2022
    assert found.court_text == "Colo."


def test_incomplete_citation_does_not_disturb_its_neighbour():
    records = extract(WOO_BODY)
    (full,) = [r for r in records if r.kind == "FullCaseCitation"]
    assert (full.plaintiff, full.defendant) == ("People", "Woo")
    assert full.full_citation == "People v. Woo, 579 P.3d 459 (Colo.App. 2025)"


def test_incomplete_citation_is_an_orphan_not_a_group():
    text = WOO_BODY
    result = group_citations(text)
    assert [g.header.text for g in result.groups] == ["579 P.3d 459"]
    (orphan,) = result.orphans
    assert orphan.kind == "UnknownCitation"
    assert text[slice(*orphan.span)] == orphan.text == "528 P.3d"
    assert orphan.flags


def test_incomplete_citation_breaks_an_id_chain():
    text = (
        "People v. Woo, 579 P.3d 459 (Colo. App. 2025). "
        "See Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d (Colo., 2022). Id."
    )
    result = group_citations(text)
    (group,) = result.groups
    assert [c.text for c in group.children] == []
    assert sorted(o.kind for o in result.orphans) == ["IdCitation", "UnknownCitation"]


def test_table_of_authorities_entry_without_a_page_is_reported_too():
    text = "Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d (Colo., 2022) .........8\n"
    (found,) = _incomplete(extract(text))
    assert found.text == "528 P.3d"


@pytest.mark.parametrize("text", [
    "The year 2022 (Colo. App.) was long.",
    "See 42 U.S.C. (2018) for the standard.",
    "Exhibit 12 (attached) shows it.",
    "On page 12 (see below) the court agrees.",
    "In 528 (Colo.) and again.",
])
def test_ordinary_text_is_not_an_incomplete_citation(text):
    assert _incomplete(extract(text)) == []


# --- a space the text layer dropped before "v." -------------------------------


def test_a_caption_glued_to_its_versus_keeps_its_name():
    """The PDF prints "Rector v. City and County of Denver"; the text layer

    returns "Rectorv."  With the space missing, the sentence splitter read
    "Rectorv." as the end of the sentence and the party pattern found no caption,
    so the citation was reported under the word before the comma ("Denver") --
    the card said "Case name unavailable" for a Colorado case whose name the
    filing prints in full.
    """
    text = ("A motion to dismiss for failure to state a claim must be decided solely on the complaint\n"
            "allegations, with all factual allegations being accepted as true and the court drawing all\n"
            "reasonable inferences therefrom in favor of the plaintiff.  Rectorv.  City and County of\n"
            "Denver,  122 P.3d 1010  (Colo.  App. 2005),  certiorari   denied  2005 WL 3074095.\n")
    records = extract(text)
    rector = next(r for r in records if r.text == "122 P.3d 1010")
    assert (rector.plaintiff, rector.defendant) == ("Rector", "City and County of Denver")
    assert rector.full_citation.startswith("Rector v. City and County of Denver, 122 P.3d 1010")


def test_a_versus_with_its_space_written_normally_is_unchanged():
    (record,) = extract("Smith v. Jones, 1 P.3d 1 (Colo. 2000).")
    assert (record.plaintiff, record.defendant) == ("Smith", "Jones")


def test_complete_citations_are_never_reported_incomplete():
    text = "Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d 899 (Colo. 2022)."
    assert _incomplete(extract(text)) == []


# --- whitespace and year inside the citation's parenthetical ------------------


def test_full_citation_has_no_raw_newlines_in_a_wrapped_court_parenthetical():
    (record,) = extract("People v. Woo, 579 P.3d 459 (Colo.\n\n   App. 2025).")
    assert record.court_text == "Colo. App."
    assert record.full_citation == "People v. Woo, 579 P.3d 459 (Colo. App. 2025)"


def test_year_glued_to_a_stray_letter_is_not_recovered():
    """The filing prints "(Colo.,\\n\\n   C2022)"; the C is in the PDF itself."""
    text = "Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d 899 (Colo.,\n\n   C2022).\n"
    (record,) = extract(text)
    assert record.year is None
    assert record.court_text is None
    assert record.full_citation == "Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d 899"
    assert "\n" not in record.full_citation
    assert any(flag.startswith("year_unverified") and "C2022" in flag for flag in record.flags)


def test_ordinary_year_parenthetical_is_unaffected():
    (record,) = extract("People v. Woo, 579 P.3d 459 (Colo. App. 2025).")
    assert record.year == 2025
    assert record.court_text == "Colo. App."
    assert not [f for f in record.flags if f.startswith("year_unverified")]


def test_year_glued_to_digits_is_not_a_year():
    (record,) = extract("People v. Woo, 579 P.3d 459 (Colo. 12025).")
    assert record.year is None


def test_pairs_and_records_agree_for_incomplete_citation():
    pairs = extract_pairs(WOO_BODY)
    assert [r.kind for _, r in pairs] == ["UnknownCitation", "FullCaseCitation"]
