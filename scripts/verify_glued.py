"""Prove a reported case name was fabricated by _normalize_glued_versus.

The normalization inserts a space into "Xv." ("Serv." -> "Ser v."). A name the
extractor reports is therefore, for that boundary, present in the document ONLY
without the inserted space: the reported form is absent and the glued form is
present. That is a mechanical proof, not a heuristic.

Usage: python scripts/verify_glued.py output/cmp_head_storage.json [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    chunks: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text", sort=True))
    return "".join(chunks)


def main() -> int:
    seen: set[str] = set()
    findings: list[tuple[str, str]] = []
    for arg in sys.argv[1:]:
        for entry in json.loads(Path(arg).read_text(encoding="utf-8")):
            doc = entry.get("old")
            if not doc or entry["name"] in seen:
                continue
            seen.add(entry["name"])
            text = text_for(Path(entry["path"]))
            # Reported names are whitespace-collapsed, so the document must be
            # compared in the same form: a caption wrapped across lines would
            # otherwise never match either hypothesis.
            text = " ".join(text.split())
            names = set()
            for g in doc["groups"]:
                names.add(g.get("caseName"))
                for c in (g["header"], *g["children"]):
                    names.add(c.get("plaintiff"))
                    names.add(c.get("defendant"))
                    names.add(c.get("case_name"))
            for name in sorted(n for n in names if n and " v. " in n):
                i = name.find(" v. ")
                # " v. " -> "v. " : the space was inserted by the normalization.
                glued = name[:i] + "v. " + name[i + 4:]
                if glued in text and name not in text:
                    findings.append((entry["name"], name))
                    print(f"FABRICATED {entry['name']}: {name!r}  (source has {glued!r})",
                          flush=True)
    print(f"documents scanned: {len(seen)}, fabricated names: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
