"""Reproduce extractor behavior on a real PDF via the same PDF path the API uses.

Usage:
    python scripts/repro_pdf.py <pdf-path> [--json <out.json>]

It imports server.app helpers only for their PDF text contract, then calls
caselaw.group.group_citations exactly as POST /api/documents does. Nothing here
writes to storage/ or data/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402


def pdf_text(path: Path) -> tuple[str, int, list[dict]]:
    import pymupdf

    chunks: list[str] = []
    pages: list[dict] = []
    offset = 0
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc):
            body = page.get_text("text", sort=True)
            chunks.append(body)
            pages.append({"index": index, "start": offset, "end": offset + len(body)})
            offset += len(body)
        count = doc.page_count
    return "".join(chunks), count, pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--text-out", type=Path, default=None)
    args = parser.parse_args()

    raw_bytes = args.path.read_bytes()
    text, page_count, pages = pdf_text(args.path)
    if args.text_out:
        args.text_out.write_text(text, encoding="utf-8")

    result = group_citations(text).as_dict()
    groups = result.get("groups", [])
    authorities = result.get("authorities", [])
    data = result

    report = {
        "path": str(args.path),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "bytes": len(raw_bytes),
        "pdf_pages": page_count,
        "text_chars": len(text),
        "stats": result.get("stats"),
        "warnings": result.get("warnings"),
        "flags": result.get("flags"),
        "groups": [
            {
                "id": g.get("id"),
                "name": g.get("caseName"),
                "non_adversarial": g.get("nonAdversarial"),
                "header": g.get("header"),
                "children": [
                    {
                        "kind": (c or {}).get("kind"),
                        "text": (c or {}).get("text"),
                        "span": (c or {}).get("span"),
                        "pin_cite": (c or {}).get("pin_cite"),
                        "flags": (c or {}).get("flags"),
                    }
                    for c in g.get("children", [])
                ],
            }
            for g in groups
        ],
        "authorities": [
            {
                "id": a.get("id"),
                "category": a.get("category"),
                "source": a.get("source"),
                "header": a.get("header"),
                "children": [
                    {
                        "kind": (c or {}).get("kind"),
                        "text": (c or {}).get("text"),
                        "span": (c or {}).get("span"),
                    }
                    for c in a.get("children", [])
                ],
            }
            for a in authorities
        ],
        "quotations": data.get("unattributedQuotes") or [],
        "records": data.get("records") or [],
    }

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"pages={page_count} chars={len(text)} groups={len(groups)} "
          f"authorities={len(authorities)} records={len(report['records'])}")
    for g in report["groups"]:
        header = g["header"] or {}
        children = ", ".join(c["text"] or "" for c in g["children"])
        print(f"  [{g['id']}] caseName={g['name']!r} header={header.get('text')!r} "
              f"children=[{children}]")
    for a in report["authorities"]:
        header = a["header"] or {}
        print(f"  AUTH [{a['id']}] category={a['category']!r} name={header.get('name')!r} "
              f"section={(header.get('tokens') or {}).get('section')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
