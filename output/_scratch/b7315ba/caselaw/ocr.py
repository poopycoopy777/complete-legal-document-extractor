"""OCR for PDFs with no usable text layer.

Roughly a fifth of the real filings sampled for the benchmark were image scans
with zero extractable text. Without OCR those documents return "0 citations",
which is indistinguishable from a document that genuinely cites nothing.

Three rules govern everything here, because OCR output is evidence-adjacent:

1. The original file is never modified. Pages are rasterised in memory and the
   recognised text is returned; nothing is written back into the PDF.

2. OCR text is never silently blended with an embedded text layer. A document
   is either "embedded" or "ocr", and which one is recorded.

3. OCR text is lower confidence and is marked as such, so that downstream
   citations carry the caveat. Observed on one 36-page opinion: "Coffman" read
   as "Coffinan", "Chavez" as "Cliavez", and section signs lost entirely --
   errors which then propagate into party names and statute numbers.

Nothing here attempts to "correct" OCR output. Guessing at what a garbled
citation was meant to say is how fabricated citations get created.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# Where Tesseract usually lands on Windows when it is not on PATH.
_WINDOWS_CANDIDATES = (
    Path(r"C:\Program Files\Tesseract-OCR"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR"),
    Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR",
)

DEFAULT_DPI = 300


@dataclass
class OcrResult:
    """Recognised text plus the provenance needed for a chain of custody."""

    text: str
    engine: str
    dpi: int
    language: str
    page_chars: list[int] = field(default_factory=list)

    @property
    def pages(self) -> int:
        return len(self.page_chars)

    @property
    def empty_pages(self) -> int:
        return sum(1 for n in self.page_chars if n < 20)

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "dpi": self.dpi,
            "language": self.language,
            "pages": self.pages,
            "emptyPages": self.empty_pages,
            "chars": len(self.text),
        }


class OcrUnavailable(RuntimeError):
    """Tesseract is not installed or its language data cannot be found."""


def _tesseract_binary() -> Path | None:
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    for base in _WINDOWS_CANDIDATES:
        candidate = base / "tesseract.exe"
        if candidate.is_file():
            return candidate
    return None


def find_tessdata() -> Path | None:
    """Locate a tessdata directory containing at least one language."""
    env = os.environ.get("TESSDATA_PREFIX")
    if env:
        for candidate in (Path(env), Path(env) / "tessdata"):
            if candidate.is_dir() and any(candidate.glob("*.traineddata")):
                return candidate

    binary = _tesseract_binary()
    bases = list(_WINDOWS_CANDIDATES)
    if binary:
        bases.insert(0, binary.parent)
    for base in bases:
        candidate = base / "tessdata"
        if candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return candidate
    return None


def engine_version() -> str:
    """Tesseract's version string, for the provenance record."""
    binary = _tesseract_binary()
    if binary is None:
        return "tesseract (version unknown)"
    try:
        out = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        first = (out.stdout or out.stderr).splitlines()[0].strip()
        return first or "tesseract"
    except Exception:  # noqa: BLE001 - provenance only, never fatal
        return "tesseract"


def available() -> bool:
    return find_tessdata() is not None


def ocr_pdf(
    path: Path,
    dpi: int = DEFAULT_DPI,
    language: str = "eng",
) -> OcrResult:
    """Recognise text for every page of a PDF. The file is only read.

    Raises OcrUnavailable when Tesseract or its language data is missing, so a
    caller can report that honestly instead of returning an empty document.
    """
    tessdata = find_tessdata()
    if tessdata is None:
        raise OcrUnavailable(
            "Tesseract language data not found. Install Tesseract OCR, or set "
            "TESSDATA_PREFIX to a directory containing eng.traineddata."
        )

    # PyMuPDF reads this at call time.
    os.environ["TESSDATA_PREFIX"] = str(tessdata)

    chunks: list[str] = []
    page_chars: list[int] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            textpage = page.get_textpage_ocr(language=language, dpi=dpi, full=True)
            body = page.get_text(textpage=textpage)
            chunks.append(body)
            page_chars.append(len(body.strip()))

    return OcrResult(
        text="".join(chunks),
        engine=engine_version(),
        dpi=dpi,
        language=language,
        page_chars=page_chars,
    )


# Characters Tesseract emits when it cannot resolve a glyph. Their presence is
# reported, never repaired: substituting a guess would fabricate a citation.
_REPLACEMENT = re.compile(r"[\ufffd\u25a1]")


def quality_notes(result: OcrResult) -> list[str]:
    """Observations a reviewer should see before trusting OCR output."""
    notes: list[str] = []
    if result.pages and result.empty_pages:
        notes.append(
            f"{result.empty_pages} of {result.pages} page(s) produced almost no "
            "text; those pages may be photographs, signatures or poor scans."
        )
    unresolved = len(_REPLACEMENT.findall(result.text))
    if unresolved:
        notes.append(
            f"{unresolved} character(s) could not be resolved and appear as "
            "placeholders. Section signs are a common casualty, so statute "
            "citations on those lines may be wrong or missing."
        )
    return notes
