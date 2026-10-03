"""Find propositions and quotes that are page furniture, not a legal proposition.

A filing repeats a running head on every page -- "Cooper v. Ingo, Case No.
2025CV111 - Argument Section". PyMuPDF emits it inside the text stream, so a
window that crosses a page break can pick it up as the sentence around a
citation. A headline is not a proposition a court said, and the release
checklist calls it out by name (B05, D03).

This script reports, per document:

* propositions that contain a repeated page-furniture line;
* propositions whose text is identical to another group's proposition, which
  means one window was reused rather than read;
* the furniture lines themselves, to show the detection is real.

Read-only apart from the report path.

Usage:
    python scripts/audit_furniture.py --inputs <dir> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402

# A caption line: "X v. Y, Case No. ..." or a bare docket line, optionally
# followed by a section label. Court stamps add "District Court, X County".
CAPTION = re.compile(
    r"[A-Z][\w'’.\-]*(?:\s+[A-Z][\w'’.\-]*)*\s+v\.?\s+"
    r"[A-Z][\w'’.\-]*(?:\s+[A-Z][\w'’.\-]*)*\s*,?\s*(?:Case\s+No\.|No\.)?"
    r"\s*[\d:A-Z\-]{2,}",
)
SECTION_LABEL = re.compile(r"\b(?:Argument|Discussion|Conclusion|Analysis)\s+Section\b")
# The doubled stamp PyMuPDF emits when a head is kerned: "CooperCooper v.v. Ingo,Ingo,".
DOUBLED = re.compile(r"\b(\w{3,})\1\b")


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    with pymupdf.open(path) as doc:
        return "".join(page.get_text("text", sort=True) for page in doc)


def furniture_lines(text: str) -> Counter:
    """Lines that repeat and look like a caption or a section label."""
    counts: Counter = Counter()
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if len(line) < 12:
            continue
        if CAPTION.search(line) or SECTION_LABEL.search(line) or DOUBLED.search(line):
            counts[line] += 1
    return Counter({line: n for line, n in counts.items() if n >= 2})


def overlaps_furniture(proposition: str, furniture: Counter) -> list[str]:
    hits = []
    flat = " ".join(proposition.split())
    for line in furniture:
        needle = line
        if needle in flat:
            hits.append(needle)
            continue
        # PyMuPDF can run the head into the following sentence with no space.
        head = needle[:40]
        if len(head) >= 20 and head in flat:
            hits.append(needle)
    return hits


def audit_one(path: Path) -> dict:
    text = text_for(path)
    data = group_citations(text).as_dict()
    furniture = furniture_lines(text)

    reused: list[dict] = []
    by_proposition: dict[str, list[str]] = {}
    contaminated: list[dict] = []

    for group in data.get("groups", []):
        proposition = group.get("proposition")
        if not proposition:
            continue
        by_proposition.setdefault(" ".join(proposition.split()), []).append(group.get("id"))
        hits = overlaps_furniture(proposition, furniture)
        if hits:
            contaminated.append({
                "group": group.get("id"),
                "case_name": group.get("caseName"),
                "proposition": proposition[:300],
                "furniture": hits[:3],
                "span": list(group.get("propositionSpan") or []),
            })

    for proposition, ids in by_proposition.items():
        if len(ids) > 1:
            reused.append({"proposition": proposition[:200], "groups": ids})

    return {
        "path": str(path),
        "text_chars": len(text),
        "furniture_lines": [{"line": line, "count": n} for line, n in furniture.most_common(10)],
        "groups": len(data.get("groups", [])),
        "contaminated_propositions": contaminated,
        "reused_propositions": reused,
        "contamination_count": len(contaminated),
        "reuse_count": len(reused),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    files: list[Path] = []
    for item in args.inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*")
                                if p.suffix.lower() in {".pdf", ".txt", ".md", ".text"}))
        else:
            files.append(item)

    results = []
    for path in files:
        try:
            results.append(audit_one(path))
        except Exception as exc:  # noqa: BLE001
            results.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")

    total = sum(r.get("contamination_count", 0) for r in results)
    reused = sum(r.get("reuse_count", 0) for r in results)
    print(f"documents={len(results)} contaminated_propositions={total} reused_propositions={reused}")
    for r in results:
        if r.get("contamination_count"):
            print(f"  {Path(r['path']).name}: {r['contamination_count']} contaminated")
            for c in r["contaminated_propositions"][:3]:
                print(f"      {c['group']} {c['case_name']!r}")
                print(f"        prop={c['proposition'][:150]!r}")
                print(f"        furniture={c['furniture']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
