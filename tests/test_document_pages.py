"""The offset contract an uploaded document carries back to the caller.

Every citation the extractor reports is a character span into the text it read.
The response also carries a page table, and the orchestrator uses it to say
which printed page a span sits on. Two things must hold:

* every offset in the document resolves to exactly one page, so a span is never
  reported on two pages at once and never on none;
* the page table covers the whole text, so a citation near the end is not left
  without a page.

Both were false for OCR'd documents. A scanned PDF was recognised correctly and
the response said ``pageCount: 2`` with ``ocr.pages: 2``, but ``pages`` was
empty and ``highlights`` was empty with it: a two-page scanned filing reported
its citations with no page anywhere, and a long scanned brief would answer every
"show me that page" with nothing.
"""

from __future__ import annotations

import asyncio
from io import BytesIO

import pymupdf
import pytest
from fastapi import UploadFile

import server.app as api
from caselaw import ocr as ocr_module


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "STORAGE", tmp_path)
    api._DOCUMENTS.clear()
    yield
    api._DOCUMENTS.clear()


class TestPageRanges:
    def test_ranges_are_in_bounds_and_cover_the_whole_text(self):
        ranges = api.page_ranges([10, 20, 5])
        assert [index for index, _, _ in ranges] == [0, 1, 2]
        for _, start, end in ranges:
            assert 0 <= start < end <= 35

    def test_text_between_pages_resolves_to_exactly_one_page(self):
        text = "a" * 10 + "b" * 20 + "c" * 5
        ranges = api.page_ranges([10, 20, 5])
        for offset in range(len(text)):
            owners = [i for i, (_, s, e) in enumerate(ranges) if s <= offset < e]
            assert len(owners) == 1, f"offset {offset} is on {owners}"

    def test_the_last_page_reaches_the_end_of_the_text(self):
        ranges = api.page_ranges([10, 20, 5])
        assert ranges[-1][2] == 35

    def test_a_later_page_starting_before_the_previous_ends_is_not_ambiguous(self):
        # An empty page must not produce a range its neighbour also claims.
        ranges = api.page_ranges([4, 0, 4])
        starts = [start for _, start, _ in ranges]
        assert len(set(starts)) == len(starts)

    def test_an_empty_page_does_not_swallow_the_next_page(self):
        ranges = api.page_ranges([4, 0, 4])
        pages = [{"index": i, "start": s, "end": e} for i, s, e in ranges]
        # Offset 5 is in the third page's text, and the second page owns nothing.
        assert api._page_for_offset(pages, 5) == 2
        assert 1 not in [p["index"] for p in pages]

    def test_zero_length_document_yields_no_ranges(self):
        assert api.page_ranges([]) == []
        assert api.page_ranges([0, 0]) == []

    def test_the_last_page_ends_where_the_pages_stop(self):
        lengths = [3, 0, 4, 5]
        ranges = api.page_ranges(lengths)
        assert ranges[-1][2] == sum(lengths)
        assert [index for index, _, _ in ranges] == [0, 2, 3]

    def test_page_table_is_json_shaped(self):
        assert api.page_table([3, 4]) == [
            {"index": 0, "start": 0, "end": 3},
            {"index": 1, "start": 3, "end": 7},
        ]


class TestOcrPageProvenance:
    def test_ocr_reports_the_raw_length_of_each_page(self):
        """page_chars counts stripped text, so it cannot rebuild offsets."""
        result = ocr_module.OcrResult(
            text="ab\ncd" + "ef", engine="t", dpi=300, language="eng",
            page_chars=[4, 2], raw_page_chars=[5, 2],
        )
        assert sum(result.raw_page_chars) == len(result.text)

    def test_ocr_from_a_real_scan_reports_offsets_that_sum_to_the_text(self):
        pdf = pymupdf.open()
        for _ in range(2):
            page = pdf.new_page()
            page.insert_text((72, 72), "scanned filing")
        body = pdf.tobytes()
        pdf.close()

        # The raster path is Tesseract; use whatever the environment offers and
        # skip honestly when it is not installed.
        result = _ocr_or_skip(body)

        assert result.raw_page_chars, "OCR reported no per-page offsets"
        assert sum(result.raw_page_chars) == len(result.text)


def _ocr_or_skip(body: bytes):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "scan.pdf"
        path.write_bytes(body)
        try:
            return ocr_module.ocr_pdf(path)
        except ocr_module.OcrUnavailable as exc:  # pragma: no cover - environment
            pytest.skip(str(exc))


class TestOcrUploadKeepsPageProvenance:
    """A scanned upload must still answer "which page is this citation on?"."""

    def _upload(self, monkeypatch) -> dict:
        pdf = pymupdf.open()
        for _ in range(2):
            page = pdf.new_page()
            page.insert_text((72, 72), "  ")
        body = pdf.tobytes()
        pdf.close()

        # Deterministic stand-in for Tesseract: same shape, same contract.
        class FakeOcr:
            text = "Smith v. Jones, 1 P.3d 1 (Colo. 2000).\n" + "more text here"
            engine = "test"
            dpi = 300
            language = "eng"
            page_chars = [38, 14]
            raw_page_chars = [39, 14]

            @property
            def pages(self):
                return len(self.page_chars)

            @property
            def empty_pages(self):
                return 0

            def as_dict(self):
                return {"engine": self.engine, "dpi": self.dpi, "language": self.language,
                        "pages": self.pages, "emptyPages": 0, "chars": len(self.text)}

        monkeypatch.setattr(ocr_module, "ocr_pdf", lambda path, **kw: FakeOcr())
        upload = UploadFile(filename="scan.pdf", file=BytesIO(body))
        return asyncio.run(api.upload_document(upload))

    def test_a_scanned_upload_reports_a_page_table(self, monkeypatch):
        response = self._upload(monkeypatch)
        assert response["textSource"] == "ocr"
        assert response["pageCount"] == 2
        assert len(response["pages"]) == 2
        assert response["pages"][-1]["end"] == len(response["extraction"]["text"])

    def test_every_span_resolves_to_a_page_after_ocr(self, monkeypatch):
        response = self._upload(monkeypatch)
        pages = response["pages"]
        text = response["extraction"]["text"]
        spans = [g["header"]["span"] for g in response["extraction"]["groups"]]
        assert spans, "the OCR text states one case citation"
        for span in spans:
            owner = api._page_for_offset(pages, span[0])
            assert owner is not None, f"span {span} has no page"
            assert 0 <= owner < len(pages)
            assert pages[owner]["start"] <= span[0] < pages[owner]["end"]
        assert len(text) == pages[-1]["end"]

    def test_highlights_carry_a_page_for_a_scanned_upload(self, monkeypatch):
        response = self._upload(monkeypatch)
        assert response["highlights"], "a scan with a citation must be highlightable"
        assert any(h["page"] is not None for h in response["highlights"])


class TestEmbeddedUploadKeepsPageProvenance:
    def _upload(self) -> dict:
        pdf = pymupdf.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "Smith v. Jones, 1 P.3d 1 (Colo. 2000).")
        page = pdf.new_page()
        page.insert_text((72, 72), "Second page with no citation.")
        body = pdf.tobytes()
        pdf.close()
        upload = UploadFile(filename="brief.pdf", file=BytesIO(body))
        return asyncio.run(api.upload_document(upload))

    def test_pages_resolve_uniquely_for_a_text_layer_pdf(self):
        response = self._upload()
        pages = response["pages"]
        text = response["extraction"]["text"]
        assert len(pages) == 2
        for offset in range(len(text)):
            owners = [p for p in pages if p["start"] <= offset < p["end"]]
            assert len(owners) <= 1, f"offset {offset} is claimed by {len(owners)} pages"
        assert pages[-1]["end"] == len(text)


class TestPartialScanIsReported:
    """A blank page inside a text-layer filing must not pass without comment.

    One 50-page complaint in storage produced 70,889 characters -- 1,400 per
    page, far above every threshold -- with three pages that produced almost
    nothing. The document-level average said the filing was fine, so those
    pages' citations disappeared with no warning at all.
    """

    ARGUMENT = "Substantive argument text. " * 12  # one dense page, ~340 chars

    def _upload_with_page_lengths(self, monkeypatch, lengths: list[int], text: str) -> dict:
        """An upload whose embedded layer reports exactly these page lengths.

        The PDF on disk is a two-page stub; the contract under test is built
        from the page lengths the PDF reader reports, which is what the real
        filing supplied.
        """
        pdf = pymupdf.open()
        for _ in range(2):
            page = pdf.new_page()
            page.insert_text((72, 72), "placeholder")
        body = pdf.tobytes()
        pdf.close()

        monkeypatch.setattr(
            api, "_pdf_text_and_pages",
            lambda path: (text, len(lengths), api.page_table(lengths), list(lengths)))
        upload = UploadFile(filename="partial-scan.pdf", file=BytesIO(body))
        return asyncio.run(api.upload_document(upload))

    def test_a_blank_page_inside_a_text_layer_pdf_is_reported(self, monkeypatch):
        lengths = [len(self.ARGUMENT), 0, len(self.ARGUMENT)]
        response = self._upload_with_page_lengths(monkeypatch, lengths, self.ARGUMENT * 3)

        assert response["textSource"] == "embedded"
        assert response["warning"], "a page carrying no text must be disclosed"

    def test_the_blank_page_warning_names_the_page_number(self, monkeypatch):
        lengths = [len(self.ARGUMENT), 0, len(self.ARGUMENT)]
        response = self._upload_with_page_lengths(monkeypatch, lengths, self.ARGUMENT * 3)

        warning = response["warning"]
        assert "1 of 3 page" in warning, warning
        assert "page 2" in warning, warning
        assert "carry almost no text" in warning, warning

    def test_the_average_alone_would_not_have_reported_it(self):
        """The exact gap: this is what the old check returned for the filing."""
        text = self.ARGUMENT * 3
        assert len(text) / 3 > api._MIN_CHARS_PER_PAGE
        assert "carry almost no text" not in (
            api._text_layer_warning(text, 3) or "")

    def test_a_document_with_no_blank_pages_is_not_warned_about(self, monkeypatch):
        lengths = [len(self.ARGUMENT), len(self.ARGUMENT)]
        response = self._upload_with_page_lengths(monkeypatch, lengths, self.ARGUMENT * 2)

        assert response["warning"] is None

    def test_many_blank_pages_are_summarised_not_listed_forever(self):
        warning = api._text_layer_warning("x" * 4000, 20, [200] * 12 + [0] * 8)
        assert warning is not None
        assert "8 of 20 page" in warning
        assert "and 0 more" not in warning
        assert "and more" not in warning
