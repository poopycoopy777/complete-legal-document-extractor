"""A service restart must not orphan documents the user already uploaded.

Uploads are written to storage/ as "<doc id><suffix>", but the registry was a
process-memory dict. Every restart emptied it, so the viewer's next request
for a previously uploaded document got "Unknown document" even though the
file was still on disk - which made real work look as though it had not
stuck. The registry now lives beside the files, is rebuilt from storage/ at
startup, and the files themselves are the fallback when the registry file is
absent or unreadable.
"""

from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path

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


def _upload_pdf() -> dict:
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Smith v. Jones, 1 P.3d 1 (Colo. 2000).")
    body = pdf.tobytes()
    pdf.close()
    upload = UploadFile(filename="brief.pdf", file=BytesIO(body))
    return asyncio.run(api.upload_document(upload))


def _upload_text() -> dict:
    upload = UploadFile(filename="note.txt", file=BytesIO(b"plain text upload"))
    return asyncio.run(api.upload_document(upload))


class TestRegistryPersistence:
    def test_upload_writes_a_registry_entry_beside_the_file(self):
        response = _upload_pdf()
        doc_id = response["id"]
        assert (api.STORAGE / f"{doc_id}.pdf").is_file()

        registry = json.loads((api.STORAGE / "documents.json").read_text("utf-8"))
        entry = next(e for e in registry if e["id"] == doc_id)
        assert entry["file"] == f"{doc_id}.pdf"
        assert entry["kind"] == "pdf"
        assert entry["sha256"] == response["sha256"]
        assert entry["pages"] == response["pageCount"]
        assert entry["name"] == "brief.pdf"

    def test_a_restart_recovers_an_uploaded_pdf(self):
        response = _upload_pdf()
        doc_id = response["id"]
        path = api.STORAGE / f"{doc_id}.pdf"

        api._DOCUMENTS.clear()  # the restart
        api._DOCUMENTS = api._load_documents()  # startup rebuild

        assert doc_id in api._DOCUMENTS
        assert api._DOCUMENTS[doc_id].path == path
        assert api._DOCUMENTS[doc_id].sha256 == response["sha256"]
        assert api._DOCUMENTS[doc_id].kind == "pdf"
        assert api._DOCUMENTS[doc_id].name == "brief.pdf"
        served = api.raw_document(doc_id)
        assert served.status_code == 200
        assert Path(served.path) == path

    def test_a_restart_recovers_a_text_upload(self):
        response = _upload_text()
        api._DOCUMENTS.clear()
        api._DOCUMENTS = api._load_documents()
        assert api._DOCUMENTS[response["id"]].kind == "text"
        served = api.raw_document(response["id"])
        assert served.status_code == 200

    def test_an_unknown_document_is_still_a_404_after_recovery(self):
        _upload_pdf()
        api._DOCUMENTS.clear()
        api._DOCUMENTS = api._load_documents()
        with pytest.raises(HTTPException) as caught:
            api.raw_document("f" * 32)
        assert caught.value.status_code == 404


class TestRegistryFallbackScan:
    def test_documents_survive_when_the_registry_file_is_absent(self):
        doc_id = "a" * 32
        body = b"%PDF-1.4 bytes that are not really a pdf"
        (api.STORAGE / f"{doc_id}.pdf").write_bytes(body)

        recovered = api._load_documents()

        assert doc_id in recovered
        entry = recovered[doc_id]
        assert entry.kind == "pdf"
        assert entry.sha256 == api._sha256(body)
        assert entry.name == f"{doc_id}.pdf"

    def test_a_corrupt_registry_falls_back_to_scanning(self):
        doc_id = "b" * 32
        (api.STORAGE / f"{doc_id}.pdf").write_bytes(b"stored bytes")
        (api.STORAGE / "documents.json").write_text("{not json", "utf-8")

        recovered = api._load_documents()

        assert doc_id in recovered
        assert recovered[doc_id].sha256 == api._sha256(b"stored bytes")

    def test_the_registry_file_itself_is_never_scanned_as_a_document(self):
        (api.STORAGE / "documents.json").write_text("[]", "utf-8")
        assert api._load_documents() == {}

    def test_unrelated_files_are_not_recovered_as_documents(self):
        (api.STORAGE / "notes.txt").write_bytes(b"not an upload")
        (api.STORAGE / "1234.pdf").write_bytes(b"short id")
        assert api._load_documents() == {}


class TestRegistryEntryValidation:
    def test_a_registry_entry_cannot_point_outside_storage(self):
        (api.STORAGE / "documents.json").write_text(
            json.dumps([
                {
                    "id": "c" * 32,
                    "name": "evil.pdf",
                    "kind": "pdf",
                    "file": "..\\..\\evil.pdf",
                    "sha256": "0" * 64,
                    "uploaded_at": "",
                    "pages": 1,
                }
            ]),
            "utf-8",
        )
        assert api._load_documents() == {}

    def test_a_registry_entry_with_a_missing_file_is_dropped(self):
        (api.STORAGE / "documents.json").write_text(
            json.dumps([
                {
                    "id": "d" * 32,
                    "name": "gone.pdf",
                    "kind": "pdf",
                    "file": f"{'d' * 32}.pdf",
                    "sha256": "0" * 64,
                    "uploaded_at": "",
                    "pages": 1,
                }
            ]),
            "utf-8",
        )
        assert api._load_documents() == {}

    def test_a_registry_entry_with_a_bad_id_is_dropped(self):
        doc_id = "e" * 32
        (api.STORAGE / f"{doc_id}.pdf").write_bytes(b"stored bytes")
        (api.STORAGE / "documents.json").write_text(
            json.dumps([
                {
                    "id": "not-a-document-id",
                    "name": "x.pdf",
                    "kind": "pdf",
                    "file": f"{doc_id}.pdf",
                    "sha256": api._sha256(b"stored bytes"),
                    "uploaded_at": "",
                    "pages": 1,
                }
            ]),
            "utf-8",
        )
        recovered = api._load_documents()
        assert recovered[doc_id].name == f"{doc_id}.pdf"  # scan wins, entry dropped


class TestRegistryWriteFailure:
    def test_an_upload_survives_a_registry_write_failure(self, monkeypatch):
        monkeypatch.setattr(api, "_persist_registry", lambda: False)
        response = _upload_pdf()
        assert response["id"]
        assert any("registry" in note for note in response["notes"])
