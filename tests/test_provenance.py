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
        if group["proposition"] is not None:
            assert _slice(text, group["propositionSpan"]) == group["proposition"]
            start, end = group["propositionSpan"]
            assert end <= group["header"]["span"][0]
            # Never the caption, never another authority's text.
            for other in extraction["groups"]:
                for citation in (other["header"], *other["children"]):
                    c_start, c_end = citation["span"]
                    assert c_end <= start or c_start >= end
        else:
            assert group["propositionSpan"] is None


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
