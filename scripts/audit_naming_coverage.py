"""How well are case groups named, by document? Read-only.

Three different things get called "unnamed", and conflating them overstates the
defect:

* **no evidence at all** - no member has parties and no member carries a
  caption, so the filing's name for this case was not found. This is the real
  gap.
* **name only on a non-header occurrence** - the group is named for a reader
  (`CitationGroup.case_name` finds it) but the header occurrence itself prints
  no name. Normal in a table of authorities, where the body names the case and
  the table repeats the citation.
* **parties only** - plaintiff and defendant were read; the group is named.

Usage:
    python scripts/audit_naming_coverage.py --inputs <dir> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    with pymupdf.open(path) as doc:
        return "".join(page.get_text("text", sort=True) for page in doc)


def classify(group: dict) -> str:
    members = [group.get("header"), *(group.get("children") or [])]
    members = [m or {} for m in members]
    has_parties = any(m.get("plaintiff") and m.get("defendant") for m in members)
    has_caption = any(m.get("case_name") for m in members)
    if has_parties:
        return "parties"
    if has_caption:
        return "caption_on_a_member"
    if (group.get("header") or {}).get("case_name"):
        return "caption_on_header"
    return "no_evidence"


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

    per_document = []
    overall: Counter = Counter()
    gaps = []
    for path in files:
        try:
            text = text_for(path)
            data = group_citations(text).as_dict()
        except Exception as exc:  # noqa: BLE001
            per_document.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        counts: Counter = Counter()
        for group in data.get("groups", []):
            kind = classify(group)
            counts[kind] += 1
            overall[kind] += 1
            if kind == "no_evidence":
                header = group.get("header") or {}
                span = header.get("span") or [0, 0]
                gaps.append({
                    "path": path.name,
                    "group": group.get("id"),
                    "citation": header.get("text"),
                    "group_case_name": group.get("caseName"),
                    "before": text[max(0, span[0] - 160):span[0]],
                })
        per_document.append({"path": path.name, "text_chars": len(text),
                             "groups": len(data.get("groups", [])), "counts": dict(counts)})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"overall": dict(overall), "per_document": per_document,
                                    "no_evidence_groups": gaps},
                                   indent=2, ensure_ascii=True), encoding="utf-8")
    total = sum(overall.values())
    print(json.dumps(dict(overall)))
    print(f"documents={len(per_document)} groups={total} "
          f"named_share={(total - overall['no_evidence']) / total if total else 0:.4f}")
    for item in per_document:
        if item.get("error"):
            print("  ERROR", item["path"], item["error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
