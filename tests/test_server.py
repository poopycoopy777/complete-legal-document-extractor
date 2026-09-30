"""Resource-safety contracts for the optional local HTTP adapter."""

from __future__ import annotations

import asyncio
from io import BytesIO

import pymupdf
import pytest
from fastapi import HTTPException, UploadFile

import server.app as api


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "STORAGE", tmp_path)
    api._DOCUMENTS.clear()
    yield
    api._DOCUMENTS.clear()


def test_extract_endpoint_rejects_oversized_text(monkeypatch):
    monkeypatch.setattr(api, "MAX_TEXT_CHARS", 4, raising=False)

    with pytest.raises(HTTPException) as caught:
        api.extract_text(api.ExtractRequest(text="12345"))

    assert caught.value.status_code == 413
    assert caught.value.detail == "Text exceeds 4 characters."


def test_upload_reader_never_reads_past_limit_plus_one():
    class RecordingUpload:
        def __init__(self):
            self.read_sizes: list[int] = []

        async def read(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            return b"12345"

    upload = RecordingUpload()

    with pytest.raises(HTTPException) as caught:
        asyncio.run(api._read_upload_limited(upload, limit=4))

    assert caught.value.status_code == 413
    assert upload.read_sizes == [5]


def test_upload_rejects_pdf_over_page_limit_and_removes_file(monkeypatch):
    monkeypatch.setattr(api, "MAX_PDF_PAGES", 1, raising=False)
    pdf = pymupdf.open()
    for _ in range(2):
        page = pdf.new_page()
        page.insert_text((72, 72), "Legal filing text " * 20)
    body = pdf.tobytes()
    pdf.close()

    upload = UploadFile(filename="two-pages.pdf", file=BytesIO(body))

    with pytest.raises(HTTPException) as caught:
        asyncio.run(api.upload_document(upload))

    assert caught.value.status_code == 413
    assert caught.value.detail == "PDF exceeds 1 page."
    assert list(api.STORAGE.iterdir()) == []


def test_health_reports_the_build_answering():
    """The orchestrator checks the running service against its pinned commit.

    A build that cannot be named cannot be checked, so this must report one --
    from BUILD_COMMIT when set, otherwise from the checkout's own HEAD.
    """
    body = api.health()

    assert body["status"] == "ok"
    assert body["version"] == api.API_VERSION
    assert body["commit_sha"] == api.BUILD_COMMIT


def test_build_commit_prefers_the_configured_value(monkeypatch):
    monkeypatch.setenv("BUILD_COMMIT", "abc1234")

    assert api._build_commit() == "abc1234"


def test_pdf_highlights_include_unattributed_quotations():
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text(
        (72, 72),
        'The private entrance displayed "No Trespassing." ' + "ordinary text " * 12,
    )
    body = pdf.tobytes()
    pdf.close()
    upload = UploadFile(filename="quote.pdf", file=BytesIO(body))

    response = asyncio.run(api.upload_document(upload))

    (quote,) = response["extraction"]["unattributedQuotes"]
    assert any(
        highlight["span"] == list(quote["span"]) for highlight in response["highlights"]
    )
