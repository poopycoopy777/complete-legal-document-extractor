"""Every offset the extractor emits must address the original document text.

Downstream stages -- verification, closed-world analysis, the report -- cite
spans instead of copying text. A span that does not slice back to exactly what
was reported breaks the chain from finding to filing.
"""

from __future__ import annotations

import asyncio
import json
from io import BytesIO

import pymupdf
import pytest
from fastapi import UploadFile

import server.app as api
from caselaw.group import group_citations

BRIEF = (
    "Officers knocked at the front door. A warrantless search of a home is "
    "presumptively unreasonable. United States v. Carloss, 818 F.3d 988, 992 "
    "(10th Cir. 2016) (holding officers may knock). The dissent saw it differently: "
    "“a homeowner retains the power to revoke the implied license.” "
    "Id. at 1008 (Gorsuch, J., dissenting).\r\n"
    "Municipal liability requires an official policy. Monell v. Department of "
    'Social Services, 436 U.S. 658, 690 (1978). "Congress did not intend '
    'municipalities to be held liable unless action pursuant to official policy '
    'caused a constitutional tort." Id. at 691. Knocking is lawful. A v. B, 1 U.S. '
    "1, 3 (1990) (holding officers may knock at the front door). C v. D, 2 U.S. 2 (1991)."
)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "STORAGE", tmp_path)
    api._DOCUMENTS.clear()
    yield
    api._DOCUMENTS.clear()


def _slice(text: str, span) -> str:
    start, end = span
    return text[start:end]


def _assert_provenance(text: str, extraction: dict) -> None:
    for group in extraction["groups"]:
        citations = [group["header"], *group["children"]]
        spans = {tuple(c["span"]) for c in citations}
        for citation in citations:
            assert _slice(text, citation["span"]) == citation["text"]
        for quote in group["quotes"]:
            assert _slice(text, quote["span"]) == quote["raw_text"]
            # A linked quotation names the exact occurrence that carries it.
            assert tuple(quote["citation_span"]) in spans
        occurrences = group["occurrencePropositions"]
        assert [o["citationSpan"] for o in occurrences] == [list(c["span"]) for c in citations]
        for occurrence in occurrences:
            if occurrence["proposition"] is None:
                assert occurrence["propositionSpan"] is None
                continue
            assert _slice(text, occurrence["propositionSpan"]) == occurrence["proposition"]
            start, end = occurrence["propositionSpan"]
            assert end <= occurrence["citationSpan"][0]
            # Never the caption, never another authority's text.
            for other in extraction["groups"]:
                for citation in (other["header"], *other["children"]):
                    c_start, c_end = citation["span"]
                    assert c_end <= start or c_start >= end
        chosen = next((o for o in occurrences if o["proposition"] is not None), None)
        if chosen is None:
            assert group["proposition"] is None and group["propositionSpan"] is None
        else:
            assert group["proposition"] == chosen["proposition"]
            assert group["propositionSpan"] == chosen["propositionSpan"]
            assert group["propositionCitationSpan"] == chosen["citationSpan"]
            assert group["propositionSignal"] == chosen["signal"]


def test_every_span_slices_back_to_the_source_text():
    extraction = group_citations(BRIEF).as_dict()
    assert len(extraction["groups"]) == 4
    _assert_provenance(BRIEF, extraction)


def test_propositions_are_the_sentence_before_the_caption():
    groups = {g["header"]["text"]: g for g in group_citations(BRIEF).as_dict()["groups"]}
    assert groups["818 F.3d 988"]["proposition"] == (
        "A warrantless search of a home is presumptively unreasonable."
    )
    assert groups["436 U.S. 658"]["proposition"] == (
        "Municipal liability requires an official policy."
    )
    assert groups["1 U.S. 1"]["proposition"] == "Knocking is lawful."


TOA_BRIEF = (
    "TABLE OF AUTHORITIES\n"
    "Cases\n"
    "Ashcroft v. Iqbal, 556 U.S. 662 (2009) ........................ 10\n"
    "Bell Atlantic Corp. v. Twombly, 550 U.S. 544 (2007) ............ 10, 11\n"
    "ARGUMENT\n"
    "A complaint must plead facts that make a claim plausible. Ashcroft v. Iqbal, "
    "556 U.S. 662, 678 (2009) (quoting Bell Atlantic Corp. v. Twombly, 550 U.S. 544, "
    "570 (2007)). Labels and conclusions will not do. See Twombly, 550 U.S. at 555. "
    "A court accepts well-pleaded facts as true. Id. at 556.\n"
)


def test_table_of_authorities_entries_are_never_propositions():
    extraction = group_citations(TOA_BRIEF).as_dict()
    _assert_provenance(TOA_BRIEF, extraction)
    groups = {g["caseName"]: g for g in extraction["groups"]}
    iqbal = groups["Ashcroft v. Iqbal"]
    assert iqbal["occurrencePropositions"][0]["proposition"] is None
    assert iqbal["proposition"] == "A complaint must plead facts that make a claim plausible."
    assert iqbal["propositionCitationSpan"] != list(iqbal["header"]["span"])
    for group in extraction["groups"]:
        assert "...." not in (group["proposition"] or "")


def test_signal_is_kept_separately_and_nested_citations_have_none():
    extraction = group_citations(TOA_BRIEF).as_dict()
    twombly = next(g for g in extraction["groups"] if g["caseName"] == "Bell Atlantic Corp. v. Twombly")
    by_text = {TOA_BRIEF[slice(*o["citationSpan"])]: o for o in twombly["occurrencePropositions"]}
    nested = next(o for text, o in by_text.items() if text == "550 U.S. 544" and o["citationSpan"][0] > 200)
    assert nested["proposition"] is None  # inside Iqbal's "(quoting ...)" parenthetical
    short = next(o for text, o in by_text.items() if text.startswith("550 U.S. at 555"))
    assert (short["proposition"], short["signal"]) == ("Labels and conclusions will not do.", "See")
    assert twombly["proposition"] == "Labels and conclusions will not do."
    assert twombly["propositionSignal"] == "See"


def test_a_string_citation_does_not_borrow_the_previous_parenthetical():
    groups = {g["header"]["text"]: g for g in group_citations(BRIEF).as_dict()["groups"]}
    assert groups["2 U.S. 2"]["proposition"] is None


def test_citation_at_document_start_has_no_proposition():
    (group,) = group_citations("United States v. Carloss, 818 F.3d 988 (10th Cir. 2016).").groups
    assert group.proposition is None


def test_quote_citation_span_names_the_short_form_that_carries_it():
    (carloss,) = [g for g in group_citations(BRIEF).groups if g.header.text == "818 F.3d 988"]
    (quote,) = carloss.quotes
    (id_cite,) = carloss.children
    assert quote.citation_span == id_cite.span


def test_extraction_is_deterministic():
    first = json.dumps(group_citations(BRIEF).as_dict(), sort_keys=True)
    for _ in range(3):
        assert json.dumps(group_citations(BRIEF).as_dict(), sort_keys=True) == first


def test_proposition_ignores_text_outside_its_window():
    lead = "Unrelated background. " * 60
    shifted = lead + BRIEF
    base = {g["header"]["text"]: g for g in group_citations(BRIEF).as_dict()["groups"]}
    moved = {g["header"]["text"]: g for g in group_citations(shifted).as_dict()["groups"]}
    for key, group in base.items():
        assert moved[key]["proposition"] == group["proposition"]
        if group["propositionSpan"]:
            assert moved[key]["propositionSpan"] == [
                o + len(lead) for o in group["propositionSpan"]
            ]


def test_text_upload_offsets_address_the_original_bytes():
    data = BRIEF.encode("utf-8")
    upload = UploadFile(filename="brief.txt", file=BytesIO(data))
    response = asyncio.run(api.upload_document(upload))
    _assert_provenance(data.decode("utf-8"), response["extraction"])
    assert response["extraction"]["groups"][0]["proposition"]


def test_pdf_upload_offsets_address_its_text_layer_and_page():
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 100), "A warrantless search of a home is presumptively unreasonable.")
    page.insert_text((72, 116), "United States v. Carloss, 818 F.3d 988, 992 (10th Cir. 2016).")
    body = pdf.tobytes()
    pdf.close()
    upload = UploadFile(filename="brief.pdf", file=BytesIO(body))
    response = asyncio.run(api.upload_document(upload))

    with pymupdf.open(stream=body, filetype="pdf") as doc:
        text_layer = "".join(p.get_text("text", sort=True) for p in doc)
    _assert_provenance(text_layer, response["extraction"])
    (group,) = response["extraction"]["groups"]
    assert group["proposition"] == "A warrantless search of a home is presumptively unreasonable."
    header = next(h for h in response["highlights"]
                  if list(h["span"]) == list(group["header"]["span"]))
    assert header["page"] == 0 and header["rects"]


def test_tables_are_masked_not_removed():
    extraction = group_citations(TOA_BRIEF).as_dict()
    (region,) = extraction["layoutRegions"]
    assert region["kind"] == "table_of_authorities"
    start, end = region["span"]
    assert TOA_BRIEF[start:].startswith("TABLE OF AUTHORITIES")
    assert TOA_BRIEF[:end].rstrip().endswith("10, 11")
    assert extraction["text"] == TOA_BRIEF  # nothing ripped out; offsets unchanged
    for group in extraction["groups"]:
        for occurrence in group["occurrencePropositions"]:
            inside = start <= occurrence["citationSpan"][0] < end
            assert (occurrence["layout"] == "table_of_authorities") is inside
            if inside:
                assert occurrence["proposition"] is None


def test_page_stamp_and_caption_fragment_never_enter_a_proposition():
    text = (
        "The officers arrived at dawn and stayed for hours.\n"
        "Case No. 1:25-cv-02263-RMR-MDB Document 61 filed 10/13/25 USDC Colorado pg 12 of 27\n"
        "Substantive due process bars conduct that shocks the conscience. "
        "County of Sacramento v. Lewis, 523 U.S. 833, 846 (1998)."
    )
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["proposition"] == "Substantive due process bars conduct that shocks the conscience."
    assert "pg 12 of 27" not in group["proposition"]


def test_citation_inside_its_own_sentence_reports_no_proposition():
    text = (
        "Officers used a tracking device for weeks. Under United States v. Jones, "
        "565 U.S. 400, 404 (2012), that installation was a search."
    )
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["proposition"] is None
