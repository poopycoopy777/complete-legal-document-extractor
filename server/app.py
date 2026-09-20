"""HTTP API for the case law extraction layer.

Uploaded files are written to storage/ byte-for-byte and never modified; the
viewer is served those original bytes so the left pane renders the real
document. Each upload records a SHA-256 taken before anything reads it.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from caselaw import ocr as ocr_module
from caselaw.group import group_citations
from caselaw.verify import service as verify_service

STORAGE = Path(__file__).resolve().parents[1] / "storage"
STORAGE.mkdir(exist_ok=True)

MAX_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_PDF_PAGES = 500
TEXT_SUFFIXES = {".txt", ".text", ".md"}

app = FastAPI(title="Caselaw Extraction API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class StoredDocument:
    id: str
    name: str
    kind: str
    path: Path
    sha256: str
    uploaded_at: str
    pages: int = 0


_DOCUMENTS: dict[str, StoredDocument] = {}


class ExtractRequest(BaseModel):
    text: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _read_upload_limited(file: UploadFile, limit: int = MAX_BYTES) -> bytes:
    """Read no more than one byte beyond the accepted upload size."""
    data = await file.read(limit + 1)
    if len(data) > limit:
        size_mb = limit // (1024 * 1024)
        detail = (
            f"File exceeds {size_mb} MB." if size_mb else f"File exceeds {limit} bytes."
        )
        raise HTTPException(status_code=413, detail=detail)
    return data


def _pdf_text_and_pages(path: Path) -> tuple[str, int, list[dict]]:
    """Extract text plus per-page character ranges and geometry.

    sort=True orders blocks by position; without it PyMuPDF can emit a filing's
    lines out of order, splitting case names across non-adjacent lines.

    The text is taken from get_text("text") verbatim. Assembling it from the
    span dictionary instead would give exact offset-to-rectangle mapping, but it
    fragments the text differently and measurably degrades citation extraction,
    so highlight rectangles are resolved by search (see _highlight_rects).
    """
    chunks: list[str] = []
    pages: list[dict] = []
    offset = 0
    with pymupdf.open(path) as doc:
        if doc.page_count > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF exceeds {MAX_PDF_PAGES} page{'s' if MAX_PDF_PAGES != 1 else ''}.",
            )
        for index, page in enumerate(doc):
            body = page.get_text("text", sort=True)
            chunks.append(body)
            pages.append(
                {
                    "index": index,
                    "start": offset,
                    "end": offset + len(body),
                    "width": page.rect.width,
                    "height": page.rect.height,
                }
            )
            offset += len(body)
        count = doc.page_count
    return "".join(chunks), count, pages


# A page of a text-layer PDF carries well over this; a scanned page carries
# almost nothing. Measured on a 10-document sample of real filings, two had no
# text layer at all and silently produced "0 citations".
_MIN_CHARS_PER_PAGE = 100


def _text_layer_warning(text: str, page_count: int) -> str | None:
    """Warn when a PDF has no usable text layer.

    Without this, a scanned brief full of citations is indistinguishable from a
    document that cites nothing: both return an empty result.
    """
    if page_count <= 0:
        return None
    per_page = len(text.strip()) / page_count
    if per_page < 1:
        return (
            f"No text layer: {page_count} page(s) produced no extractable text. "
            "This document is an image scan and needs OCR before any citation "
            "can be found. An empty result here does NOT mean the document has "
            "no citations."
        )
    if per_page < _MIN_CHARS_PER_PAGE:
        return (
            f"Sparse text layer: about {per_page:.0f} characters per page across "
            f"{page_count} page(s). The document may be a partial scan, so "
            "citations may be missing."
        )
    return None


def _page_for_offset(pages: list[dict], offset: int) -> int | None:
    for page in pages:
        if page["start"] <= offset < page["end"]:
            return page["index"]
    return None


def _search_snippet(body: str) -> str:
    """A short, single-line needle that PyMuPDF's search can actually match."""
    line = " ".join(body.split())
    return line[:60]


def _highlight_rects(
    path: Path, text: str, pages: list[dict], extraction: dict
) -> list[dict]:
    """Resolve each extracted span to page rectangles for the viewer.

    Best effort: a span that cannot be located on its page is returned with its
    page but no rectangles, so the viewer can still scroll to the right page.
    """
    targets: list[tuple[int, int]] = []
    for group in extraction["groups"]:
        for cite in (group["header"], *group["children"]):
            targets.append(tuple(cite["span"]))
        for quote in group["quotes"]:
            targets.append(tuple(quote["span"]))
    for group in extraction["authorities"]:
        for cite in (group["header"], *group["children"]):
            targets.append(tuple(cite["span"]))
        for quote in group["quotes"]:
            targets.append(tuple(quote["span"]))
    for cite in extraction["orphans"]:
        targets.append(tuple(cite["span"]))
    for quote in extraction["unattributedQuotes"]:
        targets.append(tuple(quote["span"]))

    targets.sort()

    resolved: list[dict] = []
    with pymupdf.open(path) as doc:
        cache: dict[int, object] = {}
        # Short forms repeat ("Id." three times on one page), so search_for
        # returns every occurrence. Targets are processed in document order, so
        # the Nth request for a given needle on a page takes the Nth hit.
        seen: dict[tuple[int, str], int] = {}

        for start, end in targets:
            index = _page_for_offset(pages, start)
            if index is None:
                continue
            needle = _search_snippet(text[start:end])
            rects: list[list[float]] = []
            if needle:
                page = cache.get(index)
                if page is None:
                    page = doc[index]
                    cache[index] = page
                try:
                    hits = page.search_for(needle)
                except Exception:  # noqa: BLE001 - highlighting is best effort
                    hits = []

                key = (index, needle)
                nth = seen.get(key, 0)
                seen[key] = nth + 1
                if len(hits) > 1 and nth < len(hits):
                    hits = [hits[nth]]

                rects = [
                    [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]
                    for r in hits
                ]
            resolved.append({"span": [start, end], "page": index, "rects": rects})
    return resolved


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract")
def extract_text(payload: ExtractRequest) -> dict:
    if len(payload.text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Text exceeds {MAX_TEXT_CHARS} characters.",
        )
    return group_citations(payload.text).as_dict()


@app.post("/api/documents")
async def upload_document(file: Annotated[UploadFile, File()]) -> dict:
    data = await _read_upload_limited(file)
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    name = Path(file.filename or "document").name
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        kind = "pdf"
    elif suffix in TEXT_SUFFIXES:
        kind = "text"
    else:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type {suffix or '(none)'}. Accepts .pdf or .txt.",
        )

    doc_id = uuid.uuid4().hex
    digest = _sha256(data)
    path = STORAGE / f"{doc_id}{suffix}"
    path.write_bytes(data)

    pages: list[dict] = []
    text_source = "embedded"
    ocr_info: dict | None = None
    notes: list[str] = []

    if kind == "pdf":
        try:
            text, page_count, pages = _pdf_text_and_pages(path)
        except HTTPException:
            path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422, detail=f"Could not read PDF: {exc}"
            ) from exc

        # No usable text layer: recognise the pages rather than reporting an
        # empty document, which reads identically to "cites nothing".
        if _text_layer_warning(text, page_count):
            try:
                result = ocr_module.ocr_pdf(path)
            except ocr_module.OcrUnavailable as exc:
                notes.append(str(exc))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"OCR failed: {exc}")
            else:
                if len(result.text.strip()) > len(text.strip()):
                    text = result.text
                    text_source = "ocr"
                    ocr_info = result.as_dict()
                    notes.extend(ocr_module.quality_notes(result))
                    # Page offsets came from the embedded layer and no longer
                    # describe this text.
                    pages = []
    else:
        text = data.decode("utf-8", errors="replace")
        page_count = 0

    stored = StoredDocument(
        id=doc_id,
        name=name,
        kind=kind,
        path=path,
        sha256=digest,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        pages=page_count,
    )
    _DOCUMENTS[doc_id] = stored

    extraction = group_citations(text).as_dict()
    if text_source == "ocr":
        warning = (
            "Text recovered by OCR, not read from the document. This document "
            "had no text layer. OCR misreads characters -- observed examples "
            'include "Coffman" read as "Coffinan" and lost section signs -- '
            "so every citation below is lower confidence and must be checked "
            "against the page image before it is relied on."
        )
    else:
        warning = _text_layer_warning(text, page_count) if kind == "pdf" else None
    highlights = (
        _highlight_rects(path, text, pages, extraction) if kind == "pdf" else []
    )

    return {
        "id": doc_id,
        "name": name,
        "kind": kind,
        "sha256": digest,
        "uploadedAt": stored.uploaded_at,
        "pageCount": page_count,
        "pages": pages,
        "highlights": highlights,
        "warning": warning,
        "textSource": text_source,
        "ocr": ocr_info,
        "notes": notes,
        "rawUrl": f"/api/documents/{doc_id}/raw",
        "extraction": extraction,
    }


@app.get("/api/documents/{doc_id}/raw")
def raw_document(doc_id: str) -> FileResponse:
    stored = _DOCUMENTS.get(doc_id)
    if stored is None or not stored.path.is_file():
        raise HTTPException(status_code=404, detail="Unknown document.")
    media = "application/pdf" if stored.kind == "pdf" else "text/plain; charset=utf-8"
    return FileResponse(stored.path, media_type=media, filename=stored.name)


class VerifyRequest(BaseModel):
    groups: list[dict]


@app.post("/api/verify/cases")
def verify_cases(payload: VerifyRequest) -> dict:
    """Verify the identity of extracted case citations. Positive-only.

    Returns conclusively verified cases and nothing else. A case that is
    missing from the corpus, weakly matched, ambiguous or conflicting is
    omitted rather than labelled: the corpus is a CourtListener snapshot, not
    the universe of American law, so absence is not evidence of fabrication.
    The caller finds what is unresolved by comparing submitted group ids with
    returned ones.

    `citation_verified` means the reporter citation, case name, filing year and
    court all matched one candidate. It says nothing about pin cites,
    quotations, propositions or whether the case is still good law.

    A verifier outage is an error, never an empty success.
    """
    retriever = verify_service.get_retriever()
    if retriever is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Case verification is not configured. It requires the "
                "CourtListener metadata corpus and its vector index."
            ),
        )
    try:
        verified = verify_service.verify_groups(payload.groups, retriever)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except verify_service.VerifierUnavailable as exc:
        # Never disguise an outage as "nothing verified".
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"verified": verified}
