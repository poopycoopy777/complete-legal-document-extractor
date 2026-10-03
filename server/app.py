"""HTTP API for the case law extraction layer.

Uploaded files are written to storage/ byte-for-byte and never modified; the
viewer is served those original bytes so the left pane renders the real
document. Each upload records a SHA-256 taken before anything reads it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
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
from caselaw import verifier_client
from caselaw.group import group_citations

# This application extracts citations. Verification belongs to a separate
# read-only service that owns the corpus, the resolution ladder, and the
# evidence rules. Nothing here decides whether a citation holds up.

STORAGE = Path(__file__).resolve().parents[1] / "storage"
STORAGE.mkdir(exist_ok=True)

MAX_BYTES = 64 * 1024 * 1024
MAX_TEXT_CHARS = 2_000_000
MAX_PDF_PAGES = 500
TEXT_SUFFIXES = {".txt", ".text", ".md"}

API_VERSION = "0.1.0"


def _build_commit() -> str | None:
    """The commit this process is serving, so a caller can tell it apart from another.

    The orchestrator pins this checkout by commit and checks the running service
    against that pin. A service that will not say which build it is cannot be
    checked, so absence here is reported rather than passed off as agreement.
    BUILD_COMMIT wins when set, for an image or a copy without its .git.
    """
    configured = os.environ.get("BUILD_COMMIT", "").strip()
    if configured:
        return configured
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


BUILD_COMMIT = _build_commit()

app = FastAPI(title="Caselaw Extraction API", version=API_VERSION)
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


def _pdf_text_and_pages(path: Path) -> tuple[str, int, list[dict], list[int]]:
    """Extract text plus per-page character ranges, geometry and raw lengths.

    sort=True orders blocks by position; without it PyMuPDF can emit a filing's
    lines out of order, splitting case names across non-adjacent lines.

    The text is taken from get_text("text") verbatim. Assembling it from the
    span dictionary instead would give exact offset-to-rectangle mapping, but it
    fragments the text differently and measurably degrades citation extraction,
    so highlight rectangles are resolved by search (see _highlight_rects).

    The raw length of each page is returned alongside the ranges so a caller can
    tell which pages carry no text at all. A whole-document average hides that:
    a 50-page filing with three blank pages averages 1,400 characters per page.
    """
    chunks: list[str] = []
    pages: list[dict] = []
    lengths: list[int] = []
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
            lengths.append(len(body))
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
    return "".join(chunks), count, pages, lengths


# A page of a text-layer PDF carries well over this; a scanned page carries
# almost nothing. Measured on a 10-document sample of real filings, two had no
# text layer at all and silently produced "0 citations".
_MIN_CHARS_PER_PAGE = 100

# Below this there is no usable text layer at all, and OCR is the only source of
# text. Between the two numbers the layer is real but thin, so it is kept and
# reported rather than replaced.
_NO_TEXT_LAYER_CHARS_PER_PAGE = 20


def _text_layer_warning(text: str, page_count: int, page_lengths: list[int] | None = None) -> str | None:
    """Warn when a PDF has no usable text layer, or pages that carry none.

    Without this, a scanned brief full of citations is indistinguishable from a
    document that cites nothing: both return an empty result.

    A whole-document average hides a real filing's partial scan. One 50-page
    complaint in storage carried 70,889 characters -- an average of 1,400 per
    page, comfortably above every threshold -- with three pages that produced
    almost nothing. Citations printed on those pages are simply absent, and
    nothing in the response said so.
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
    if page_lengths:
        blank = [i + 1 for i, n in enumerate(page_lengths) if n < _MIN_CHARS_PER_PAGE]
        if blank:
            shown = ", ".join(str(n) for n in blank[:8])
            more = f" and {len(blank) - 8} more" if len(blank) > 8 else ""
            return (
                f"{len(blank)} of {page_count} page(s) carry almost no text "
                f"(page{'s' if len(blank) != 1 else ''} {shown}{more}). Those "
                "pages may be scans, photographs or images, and any citation "
                "printed on them is missing from this result."
            )
    return None


def page_ranges(page_lengths: list[int]) -> list[tuple[int, int, int]]:
    """``(page_index, start, end)`` for every page that carries text.

    ``_page_for_offset`` resolves an offset by scanning for the first range that
    contains it, so ranges must not overlap and no two may share a start. Only
    pages with text get a range: an empty page has no offsets to own, and giving
    it one adjacent to its neighbour's start would make every offset on that
    boundary ambiguous. A page that recognised nothing is therefore absent from
    the table, which is the honest answer for a page with no text.

    Text a page contributed but did not report a length for is still covered,
    because the ranges are built from the text the caller actually holds.
    """
    ranges: list[tuple[int, int, int]] = []
    offset = 0
    for index, length in enumerate(page_lengths):
        length = max(0, int(length))
        if length:
            ranges.append((index, offset, offset + length))
        offset += length
    if not ranges and offset:
        # Lengths were reported but no single page accounted for the text.
        ranges.append((0, 0, offset))
    return ranges


def page_table(page_lengths: list[int]) -> list[dict]:
    """The response's page table: one entry per page that carries text."""
    return [
        {"index": index, "start": start, "end": end}
        for index, start, end in page_ranges(page_lengths)
    ]


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
def health() -> dict[str, str | None]:
    """Liveness, and which build is answering. Says nothing about extraction quality."""
    return {"status": "ok", "version": API_VERSION, "commit_sha": BUILD_COMMIT}


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
    page_lengths: list[int] = []
    text_source = "embedded"
    ocr_info: dict | None = None
    notes: list[str] = []

    if kind == "pdf":
        try:
            text, page_count, pages, page_lengths = _pdf_text_and_pages(path)
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
        if page_count and len(text.strip()) / page_count < _NO_TEXT_LAYER_CHARS_PER_PAGE:
            try:
                result = ocr_module.ocr_pdf(path)
            except ocr_module.OcrUnavailable as exc:
                notes.append(str(exc))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"OCR failed: {exc}")
            else:
                if len(result.text.strip()) > len(text.strip()):
                    # A page table built from the embedded layer describes the
                    # text that layer produced, so it has to be rebuilt for OCR
                    # text. Dropping it instead left a scanned filing with
                    # "pageCount: 2" and no page for any citation.
                    text = result.text
                    text_source = "ocr"
                    ocr_info = result.as_dict()
                    notes.extend(ocr_module.quality_notes(result))
                    pages = page_table(result.raw_page_chars)
                    page_lengths = list(result.raw_page_chars)
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
        warning = _text_layer_warning(text, page_count, page_lengths) if kind == "pdf" else None
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
    analyze: bool = False


@app.post("/api/verify/cases")
def verify_cases(payload: VerifyRequest) -> dict:
    """Send extracted citation groups to the verification service.

    This endpoint is a proxy. It does no verification of its own: the service
    owns the corpus, the resolution ladder (local corpus, then CourtListener,
    then the official Colorado source), and every rule about what evidence
    means. That is why absence from one source is no longer a conclusion here.

    The response carries three things at once:

    * `verified` -- the positive-only shape the existing UI already renders, so
      nothing breaks. Only a confirmed identity appears in it.
    * `results` -- the full per-citation record: identity verdict and reason
      code, pin cite, quotation with its opinion role, citation history with
      coverage numbers, and any model analysis of legal usage.
    * `counts` -- card counts against log counts. `verified` plus `flagged`
      does not sum to the total, because an unresolved citation is neither.

    Two distinctions the service makes that this app must not flatten: a
    fabricated citation (`phantom_citation`) is not the same finding as a real
    case cited wrongly (`citation_does_not_match_named_case`), and a source
    outage is not a finding at all.

    An outage is an error, never an empty success.
    """
    try:
        response = verifier_client.verify_groups(payload.groups, analyze=payload.analyze)
    except verifier_client.VerifierUnavailable as exc:
        # Never disguise an outage as "nothing verified": a document full of
        # real citations and one the verifier could not reach look identical.
        raise HTTPException(status_code=503, detail=str(exc)) from None

    results = response.get("results") or []
    verified = [
        entry
        for entry in (verifier_client.to_legacy_verified(result) for result in results)
        if entry
    ]

    return {
        "verified": verified,
        "results": results,
        "counts": response.get("counts") or {},
        "authorities": response.get("authorities") or [],
    }


@app.get("/api/verify/capabilities")
def verify_capabilities() -> dict:
    """Report what the verification service can currently answer.

    Coverage gaps are disclosed rather than discovered mid-request, so the UI
    can say which checks are unavailable before a user reads a result as a
    finding.
    """
    try:
        return verifier_client.capabilities()
    except verifier_client.VerifierUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
