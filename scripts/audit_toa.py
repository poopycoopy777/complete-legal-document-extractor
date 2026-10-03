"""Inspect a real table of authorities: does each citation keep its printed name?

A table of authorities prints "Case Name ......... 12" on one line, and a later
table may print the citation instead of a page. If the extractor drops the name
there, every citation in the table loses its identity -- so this prints, per
document, the table lines and how the resulting groups are named.

Usage:
    python scripts/audit_toa.py <pdf> [--max-lines 40]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402

DOT_LEADER = re.compile(r"\.\s?\.\s?\.\s?\.")


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    with pymupdf.open(path) as doc:
        return "".join(page.get_text("text", sort=True) for page in doc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-lines", type=int, default=30)
    args = parser.parse_args()

    text = text_for(args.path)
    data = group_citations(text).as_dict()

    print(f"document: {args.path.name}")
    print(f"text_chars={len(text)} groups={len(data['groups'])} "
          f"orphans={len(data['orphans'])}")
    unnamed = [g for g in data["groups"] if not g["caseName"]]
    print(f"groups_without_caseName={len(unnamed)}")
    for g in unnamed:
        header = g["header"]
        span = header.get("span") or [0, 0]
        print(f"  UNNAMED {g['id']} {header['text']!r} at {span}")
        print(f"      before={text[max(0, span[0] - 120):span[0]]!r}")

    print()
    print("table lines (dot leaders):")
    shown = 0
    for raw in text.splitlines():
        if DOT_LEADER.search(raw):
            print(f"  {raw.strip()[:150]!r}")
            shown += 1
            if shown >= args.max_lines:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
