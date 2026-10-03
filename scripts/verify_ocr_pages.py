"""Repaired contract, checked against the live build and against a real scan.

Two modes:

``--live`` posts a file to the running extractor on 8010, so the answer comes
from the code the process is actually serving. This is what proves integration;
it stays broken until the service is restarted.

``--in-process`` runs the same upload through the checkout's own module with
``STORAGE`` pointed at a temporary directory, so the repaired path can be checked
before any restart. It never writes to the repository's storage/.

Usage:
    python scripts/verify_ocr_pages.py <pdf> --in-process
    python scripts/verify_ocr_pages.py <pdf> --live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def report(payload: dict, text: str | None) -> dict:
    pages = payload.get("pages") or []
    highlights = payload.get("highlights") or []
    extraction = payload.get("extraction") or {}
    source_text = text if text is not None else extraction.get("text") or ""
    spans = [g["header"]["span"] for g in extraction.get("groups", [])]
    spans += [c["span"] for g in extraction.get("groups", [])
              for c in g.get("children", [])]

    def owner(offset: int):
        hits = [p["index"] for p in pages if p["start"] <= offset < p["end"]]
        return hits

    ambiguous = [s for s in spans if len(owner(s[0])) > 1]
    unowned = [s for s in spans if not owner(s[0])]
    return {
        "textSource": payload.get("textSource"),
        "pageCount": payload.get("pageCount"),
        "pages_table": len(pages),
        "highlights": len(highlights),
        "highlights_with_page": sum(1 for h in highlights if h.get("page") is not None),
        "ocr": payload.get("ocr"),
        "stats": extraction.get("stats"),
        "page_table_last_end": pages[-1]["end"] if pages else None,
        "text_length": len(source_text),
        "spans": len(spans),
        "spans_ambiguous": len(ambiguous),
        "spans_without_page": len(unowned),
    }


def run_in_process(path: Path) -> dict:
    import server.app as api
    from fastapi import UploadFile

    original = api.STORAGE
    with tempfile.TemporaryDirectory() as directory:
        api.STORAGE = Path(directory)
        api._DOCUMENTS.clear()
        try:
            upload = UploadFile(filename=path.name, file=BytesIO(path.read_bytes()))
            payload = asyncio.run(api.upload_document(upload))
        finally:
            api.STORAGE = original
            api._DOCUMENTS.clear()
    return payload


def run_live(path: Path) -> dict:
    boundary = "----bench" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        "http://127.0.0.1:8010/api/documents",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=1800) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.live:
        payload = run_live(args.path)
    else:
        payload = run_in_process(args.path)

    summary = report(payload, None)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"summary": summary, "response": payload}, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    ok = (
        summary["page_table_last_end"] == summary["text_length"]
        and summary["spans_ambiguous"] == 0
        and summary["spans_without_page"] == 0
        and summary["pageCount"] == summary["pages_table"]
        and summary["highlights_with_page"] == summary["highlights"]
    )
    print("CONTRACT_OK" if ok else "CONTRACT_BROKEN")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
