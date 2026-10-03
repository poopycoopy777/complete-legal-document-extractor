"""List every gap the subsequent-history rule accepts, so a human can check it.

The rule merges two citations into one case group when the text between them is a
pin, the original's court-and-year parenthetical, and a history phrase. A false
acceptance would merge two different cases, which is the failure this whole area
is trying to prevent, so every acceptance is printed with its document for
review.

Usage:
    python scripts/audit_history_merges.py --inputs <dir> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GROUP = importlib.import_module("caselaw.group")
from caselaw.extract import extract_pairs  # noqa: E402
from caselaw.group import group_citations  # noqa: E402

PARALLEL = GROUP._PARALLEL_GAP


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    with pymupdf.open(path) as doc:
        return "".join(page.get_text("text", sort=True) for page in doc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    files: list[Path] = []
    for item in args.inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*") if p.suffix.lower() == ".pdf"))
        else:
            files.append(item)

    accepted = []
    totals = {"documents": 0, "groups": 0, "pairs": 0, "parallel": 0, "history": 0}
    for path in files:
        try:
            text = text_for(path)
            data = group_citations(text).as_dict()
            pairs = extract_pairs(text)
        except Exception as exc:  # noqa: BLE001
            accepted.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        totals["documents"] += 1
        totals["groups"] += len(data.get("groups", []))
        spans = [c.span() for c, rec in pairs
                 if c is not None and rec.kind == "FullCaseCitation"]
        for a, b in zip(spans, spans[1:]):
            totals["pairs"] += 1
            if PARALLEL.fullmatch(text, a[1], b[0]):
                totals["parallel"] += 1
                continue
            gap = text[a[1]:b[0]]
            if GROUP._is_subsequent_history(gap):
                totals["history"] += 1
                accepted.append({
                    "path": path.name,
                    "first": text[a[0]:a[1]],
                    "gap": gap,
                    "second": text[b[0]:b[1]],
                    "context": text[max(0, a[0] - 60):b[1] + 40],
                })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"totals": totals, "accepted": accepted},
                                   indent=2, ensure_ascii=True), encoding="utf-8")

    print(json.dumps(totals))
    print(f"history_merges_accepted={len(accepted)}")
    for item in accepted:
        if item.get("error"):
            print("  ERROR", item["path"], item["error"])
            continue
        print(f"  {item['path']}: {item['first']!r} <- {item['gap']!r} -> {item['second']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
