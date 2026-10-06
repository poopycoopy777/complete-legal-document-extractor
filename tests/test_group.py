"""Tests for citation grouping and quote attribution."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from caselaw.group import group_citations

BRIEF = (
    'The Court held otherwise. "Congress did not intend municipalities to be '
    "held liable unless action pursuant to official municipal policy caused a "
    'constitutional tort." Monell v. Department of Social Services, 436 U.S. '
    "658, 691 (1978). The Tenth Circuit applied it in Schneider v. City of "
    "Grand Junction, 717 F.3d 760, 770 (10th Cir. 2013). Id. at 771. "
    "Schneider, 717 F.3d at 772."
)

JARDINES_MULTILINE = (
    "Florida v. Jardines, 569 U.S. 1 (2013). The implied license permits officers "
    "to \u201capproach the home and knock, precisely because that is no more than any "
    "private\n\ncitizen might do.\u201d Jardines, 569 U.S. at 8."
)


def test_full_citations_become_group_headers():
    result = group_citations(BRIEF)
    assert [g.case_name for g in result.groups] == [
        "Monell v. Department of Social Services",
        "Schneider v. City of Grand Junction",
    ]


def test_id_and_short_forms_cascade_under_their_full_citation():
    result = group_citations(BRIEF)
    schneider = result.groups[1]
    kinds = [c.kind for c in schneider.children]
    assert "IdCitation" in kinds
    assert "ShortCaseCitation" in kinds


def test_a_quotation_is_attributed_to_the_citation_that_follows_it():
    result = group_citations(BRIEF)
    monell = result.groups[0]
    assert len(monell.quotes) == 1
    assert monell.quotes[0].text.startswith("Congress did not intend")
    assert monell.quotes[0].pin_cite == "691"


def test_pdf_line_wrapping_does_not_discard_a_multiline_quotation():
    result = group_citations(JARDINES_MULTILINE)
    jardines = next(g for g in result.groups if g.case_name == "Florida v. Jardines")

    assert [quote.text for quote in jardines.quotes] == [
        (
            "approach the home and knock, precisely because that is no more than "
            "any private citizen might do."
        )
    ]
    assert jardines.quotes[0].pin_cite == "8"


def test_unattributed_quotation_is_retained_instead_of_discarded():
    text = "The private door displayed the warning “No Trespassing.”"

    result = group_citations(text).as_dict()

    assert [quote["text"] for quote in result["unattributedQuotes"]] == [
        "No Trespassing."
    ]
    assert result["unattributedQuotes"][0]["attribution_status"] == "unattributed"
    assert result["stats"]["quotes"] == 1
    assert result["stats"]["linkedQuotes"] == 0
    assert result["stats"]["unattributedQuotes"] == 1


def test_quotation_followed_by_id_is_linked_without_treating_every_id_as_a_quote():
    text = (
        "Monell v. Department of Social Services, 436 U.S. 658, 690 (1978). "
        "The Court called the rule \u201ca deliberate choice to follow a course of "
        "action.\u201d Id. at 690. Id. at 691 explains a different proposition."
    )

    result = group_citations(text)
    monell = next(
        g
        for g in result.groups
        if g.case_name == "Monell v. Department of Social Services"
    )

    assert len(monell.quotes) == 1
    assert monell.quotes[0].attribution_basis == "following_id"
    assert monell.quotes[0].pin_cite == "690"


def test_long_block_quotation_is_not_cut_off_at_four_hundred_characters():
    quoted = "constitutional text " * 30
    text = (
        "Monell v. Department of Social Services, 436 U.S. 658 (1978). Later, "
        f"\u201c{quoted}\u201d Monell, 436 U.S. at 690."
    )

    result = group_citations(text)
    monell = next(
        g
        for g in result.groups
        if g.case_name == "Monell v. Department of Social Services"
    )

    assert [quote.text for quote in monell.quotes] == [quoted.strip()]


def test_quotation_can_be_attributed_to_a_statute_instead_of_a_case():
    text = "The statute reaches every person acting “under color of law.” 42 U.S.C. § 1983."

    result = group_citations(text)
    section_1983 = next(
        group for group in result.authorities if "1983" in group.header.text
    )

    assert [quote.text for quote in section_1983.quotes] == ["under color of law."]
    assert section_1983.quotes[0].attribution_basis == "following_authority"


def test_quote_spans_round_trip_into_the_source():
    result = group_citations(BRIEF)
    for g in result.groups:
        for q in g.quotes:
            start, end = q.span
            assert q.text in BRIEF[start:end]
            assert q.raw_text == BRIEF[start:end]


def test_groups_are_in_document_order():
    result = group_citations(BRIEF)
    starts = [g.header.span[0] for g in result.groups]
    assert starts == sorted(starts)


def test_every_citation_appears_exactly_once():
    result = group_citations(BRIEF)
    seen = [c.span for g in result.groups for c in (g.header, *g.children)] + [
        c.span for c in result.orphans
    ]
    assert len(seen) == len(set(seen))


def test_stats_are_consistent():
    result = group_citations(BRIEF).as_dict()
    counted = sum(1 + len(g["children"]) for g in result["groups"])
    assert result["stats"]["citations"] == counted + len(result["orphans"])


def test_empty_text_yields_nothing():
    result = group_citations("")
    assert result.groups == [] and result.orphans == []


POLLARD = (
    "Bell Atl. Corp. v. Twombly, 550 U.S. 544, 570 (2007). "
    "Ashcroft v. Iqbal, 556 U.S. 662, 678 (2009). "
    "Courts will not supply additional facts. Hall v. Bellmon, 935 F.2d 1106, 1110 "
    "(10th Cir. 1991). A pro se complaint must still allege facts stating "
    "\u201ca plausible on its face\u201d claim in compliance with Iqbal and Twombly. "
    "See id."
)


def test_a_quotation_named_to_another_case_in_its_sentence_is_not_given_to_the_following_id():
    result = group_citations(POLLARD)
    by_name = {g.case_name: g for g in result.groups}
    iqbal = by_name["Ashcroft v. Iqbal"]
    hall = by_name["Hall v. Bellmon"]

    assert [q.text for q in iqbal.quotes] == ["a plausible on its face"]
    quote = iqbal.quotes[0]
    assert quote.attribution_basis == "named_in_sentence"
    assert quote.candidate_authorities == [iqbal.id, by_name["Bell Atl. Corp. v. Twombly"].id]
    assert quote.citation_span == iqbal.header.span
    assert quote.pin_cite is None
    assert hall.quotes == []


def test_a_case_name_used_as_a_caption_does_not_take_a_quotation_from_its_id():
    text = (
        "Monell v. Department of Social Services, 436 U.S. 658, 690 (1978). "
        "The Court called the rule \u201ca deliberate choice,\u201d id. at 690; see also "
        "Pembaur v. City of Cincinnati, 475 U.S. 469, 483 (1986)."
    )
    result = group_citations(text)
    monell = next(g for g in result.groups if g.case_name.startswith("Monell"))
    assert [q.text for q in monell.quotes] == ["a deliberate choice,"]
    assert monell.quotes[0].attribution_basis == "following_id"


def test_a_short_citation_that_names_its_own_case_keeps_its_quotation():
    text = (
        "Monell v. Department of Social Services, 436 U.S. 658, 694 (1978). "
        "Frey v. Town of Jackson, 41 F.4th 1223, 1238 (10th Cir. 2022). "
        "To state a Monell claim, \u201ca plaintiff must allege a municipal policy\u201d "
        "under Monell. Frey, 41 F.4th at 1238."
    )
    result = group_citations(text)
    frey = next(g for g in result.groups if g.case_name.startswith("Frey"))
    assert [q.text for q in frey.quotes] == ["a plaintiff must allege a municipal policy"]


def test_a_quotation_before_a_sentence_with_its_own_signal_citation_is_not_given_to_it():
    text = (
        "Such conduct cannot be \u201cextreme and outrageous\u201d as a matter of law. "
        "The Colorado Supreme Court has held that asserting one's legal rights is not "
        "outrageous conduct. See Rugg v. McCarty, 476 P.2d 753, 755 (Colo. 1970)."
    )
    result = group_citations(text)
    rugg = next(g for g in result.groups if g.case_name.startswith("Rugg"))
    assert rugg.quotes == []
    assert [q.text for q in result.unattributed_quotes] == ["extreme and outrageous"]


def test_a_quotation_in_the_sentence_before_a_signal_citation_keeps_it():
    text = (
        "Conduct must be \u201cextreme and outrageous.\u201d "
        "See Rugg v. McCarty, 476 P.2d 753, 755 (Colo. 1970)."
    )
    result = group_citations(text)
    rugg = next(g for g in result.groups if g.case_name.startswith("Rugg"))
    assert [q.text for q in rugg.quotes] == ["extreme and outrageous."]


def test_an_exhibit_number_is_not_read_as_a_reporter_volume():
    text = (
        "Ex. 8         Call 2400006154 Redacted\n\n"
        "Ex. 9        Call 25-114565 Redacted\n\n"
        "Exhibit 3 shows it. See Rugg v. McCarty, 476 P.2d 753, 755 (Colo. 1970)."
    )
    result = group_citations(text)
    assert [g.case_name for g in result.groups] == ["Rugg v. McCarty"]
    assert result.orphans == []


def test_a_page_number_inside_a_quotation_across_a_page_break_is_not_part_of_it():
    text = (
        "Such conduct cannot be \u201cextreme and\n\n\n\n"
        "                                      5       outrageous\u201d as a matter of law."
    )
    result = group_citations(text)
    assert [q.text for q in result.unattributed_quotes] == ["extreme and outrageous"]


def test_a_quotation_under_a_new_heading_is_not_given_to_the_citation_above_it():
    text = (
        "These allegations are insufficient. See Rugg v. McCarty, 476 P.2d 753, 756 (Colo. 1970).\n\n\n\n"
        "C. Counterclaim III (Abuse of Process) Fails to Allege an Improper \u201cAct\u201d\n\n"
    )
    result = group_citations(text)
    rugg = next(g for g in result.groups if g.case_name.startswith("Rugg"))
    assert rugg.quotes == []


def test_a_quotation_that_opens_a_sentence_after_a_citation_goes_to_the_one_after_it():
    text = (
        "\u201cA search occurs when an expectation of privacy is infringed.\u201d Maryland v. Macon, "
        "472 U.S. 463, 468 (1985) (quoting United States v. Jacobsen, 466 U.S. 109, 113 (1984)). "
        "\u201cIt is well-established that a warrantless search is presumptively unreasonable.\u201d "
        "Roska ex rel. Roska v. Peterson, 328 F.3d 1230, 1240 (10th Cir. 2003)."
    )
    result = group_citations(text)
    owner = {q.text[:5]: g.case_name for g in result.groups for q in g.quotes}
    assert owner["It is"] == "Roska ex rel. Roska v. Peterson"


def test_a_quotation_marked_citations_omitted_carries_the_mark():
    text = (
        "See Artes-Roy v. City of Aspen, 31 F.3d 958, 962 (10th Cir. 1994) (\u201cEven if we treat "
        "the entry as a violation, it was a de minimis violation.\u201d (citations omitted)). "
        "The officers were there to investigate. See Lyman v. James, 400 U.S. 309, 318 (1971) "
        "(\u201cnot a search\u201d (internal quotation marks omitted))."
    )
    marks = {q.text[:5]: q.citations_omitted for g in group_citations(text).groups for q in g.quotes}
    assert marks == {"Even ": True, "not a": False}
