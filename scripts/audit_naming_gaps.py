"""Classify the real-filing groups that carry no naming evidence.

Each one is checked against the shapes a repair could target, so the next piece
of work is chosen from measured counts rather than from the first example seen.

Usage:
    python scripts/audit_naming_gaps.py --inputs <file> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402

V_SPLIT = re.compile(r"\bv\.?\s*\n+\s*[A-Z]")
HISTORY = re.compile(
    r"\b(?:aff'?d|affirmed|rev'?d|vacated|cert\.|overruled|adopted|superseded)\b",
    re.IGNORECASE,
)
SEE_ALSO = re.compile(r"\bsee\s+also\b", re.IGNORECASE)


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    with pymupdf.open(path) as doc:
        return "".join(page.get_text("text", sort=True) for page in doc)


def classify(before: str) -> list[str]:
    shapes = []
    if V_SPLIT.search(before):
        shapes.append("caption_split_across_a_line")
    if SEE_ALSO.search(before):
        shapes.append("name_separated_from_citation")
    if HISTORY.search(before):
        shapes.append("subsequent_history")
    if before.count("(") > before.count(")"):
        shapes.append("inside_a_parenthetical")
    if "No." in before or "CIV" in before or "Case No" in before:
        shapes.append("docket_bearing_caption")
    if not shapes:
        shapes.append("unclassified")
    return shapes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--context", type=int, default=200)
    args = parser.parse_args()

    files: list[Path] = []
    for item in args.inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*") if p.suffix.lower() == ".pdf"))
        else:
            files.append(item)

    findings = []
    shape_counts: dict[str, int] = {}
    for path in files:
        try:
            text = text_for(path)
            data = group_citations(text).as_dict()
        except Exception:  # noqa: BLE001
            continue
        for group in data.get("groups", []):
            members = [group.get("header"), *(group.get("children") or [])]
            members = [m or {} for m in members]
            if any((m.get("plaintiff") and m.get("defendant")) or m.get("case_name")
                   for m in members):
                continue
            if group.get("caseName"):
                continue
            header = group.get("header") or {}
            span = header.get("span") or [0, 0]
            before = text[max(0, span[0] - args.context):span[0]]
            shapes = classify(before)
            for shape in shapes:
                shape_counts[shape] = shape_counts.get(shape, 0) + 1
            findings.append({
                "path": path.name,
                "group": group.get("id"),
                "citation": header.get("text"),
                "shapes": shapes,
                "before": before,
                "after": text[span[1]:span[1] + 90],
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"shape_counts": shape_counts, "findings": findings},
                                   indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"unnamed_groups={len(findings)}")
    for shape, count in sorted(shape_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>3}  {shape}")
    print()
    for item in findings:
        print(f"{item['path']} {item['group']} {item['citation']!r} {item['shapes']}")
        print(f"    before={item['before'][-150:]!r}")
        print(f"    after ={item['after'][:90]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
