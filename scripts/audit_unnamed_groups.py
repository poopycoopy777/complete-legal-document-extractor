"""Report every citation group that ends up with no case name, with its context.

A group with no name cannot be checked for identity downstream, so each one is
either a genuine defect (a name is printed and was missed) or an honest gap (the
filing really cites an anonymous citation). This prints enough of the surrounding
document text to tell the two apart.

Usage:
    python scripts/audit_unnamed_groups.py --inputs <dir> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import json
import sys
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--context", type=int, default=160)
    args = parser.parse_args()

    files: list[Path] = []
    for item in args.inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*")
                                if p.suffix.lower() in {".pdf", ".txt", ".md"}))
        else:
            files.append(item)

    found = []
    for path in files:
        try:
            text = text_for(path)
            data = group_citations(text).as_dict()
        except Exception as exc:  # noqa: BLE001
            found.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        for group in data.get("groups", []):
            if group.get("caseName"):
                continue
            header = group.get("header") or {}
            span = header.get("span") or [0, 0]
            # A group is named if any member carries the caption, not only the
            # header: a filing often names the case in the body and lists the
            # citation again in a table of authorities. Counting only the header
            # over-reports this badly. `CitationGroup.case_name` uses the same
            # rule, so `group["caseName"]` above already reflects it; this block
            # therefore sees only groups no member names.
            has_parties = any(
                (c or {}).get("plaintiff") and (c or {}).get("defendant")
                for c in (header, *(group.get("children") or []))
            )
            found.append({
                "path": path.name,
                "group": group.get("id"),
                "header_text": header.get("text"),
                "header_kind": header.get("kind"),
                "span": span,
                "plaintiff": header.get("plaintiff"),
                "defendant": header.get("defendant"),
                "header_case_name": header.get("case_name"),
                "any_member_has_parties": has_parties,
                "children": [{"text": (c or {}).get("text"), "kind": (c or {}).get("kind"),
                              "plaintiff": (c or {}).get("plaintiff"),
                              "defendant": (c or {}).get("defendant")}
                             for c in (group.get("children") or [])],
                "before": text[max(0, span[0] - args.context):span[0]],
                "after": text[span[1]:span[1] + 80],
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(found, indent=2, ensure_ascii=True), encoding="utf-8")

    with_parties = [f for f in found if f.get("any_member_has_parties")]
    print(f"unnamed_groups={len(found)} of_which_a_member_has_parties={len(with_parties)}")
    for item in found:
        if item.get("error"):
            print("  ERROR", item["path"], item["error"])
            continue
        marker = "PARTIES-PRESENT" if item.get("any_member_has_parties") else "no-parties"
        print(f"  [{marker}] {item['path']} {item['group']} {item['header_kind']} "
              f"{item['header_text']!r}")
        print(f"      before={item['before'][-110:]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
