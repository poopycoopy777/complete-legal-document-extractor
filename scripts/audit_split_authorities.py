"""Find documents where one reporter citation appears in more than one group.

If a filing names a case in the body and then lists it again in a table of
authorities -- "Fantasy, Inc. v. Fogerty" on one line, "984 F.2d 1524" on the
next -- the second occurrence can become its own group. The same case is then
two cards, one of them unnamed, and a report that shows both attaches evidence
to the wrong authority.

Usage:
    python scripts/audit_split_authorities.py --inputs <dir> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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


def citation_key(cite: dict) -> str | None:
    volume, reporter, page = cite.get("volume"), cite.get("reporter"), cite.get("page")
    if not (volume and reporter and page):
        return None
    reporter = " ".join(str(reporter).split()).lower().replace(".", "")
    return f"{volume} {reporter} {page}".lower()


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

    findings = []
    totals = {"documents": 0, "groups": 0, "split_citations": 0,
              "split_with_an_unnamed_member": 0}
    for path in files:
        try:
            text = text_for(path)
            data = group_citations(text).as_dict()
        except Exception as exc:  # noqa: BLE001
            findings.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
            continue
        totals["documents"] += 1
        totals["groups"] += len(data.get("groups", []))

        by_citation: dict[str, list[dict]] = defaultdict(list)
        for group in data["groups"]:
            for cite in (group["header"], *group["children"]):
                key = citation_key(cite)
                if key:
                    by_citation[key].append(group)

        for key, groups in by_citation.items():
            unique = {g["id"]: g for g in groups}
            if len(unique) < 2:
                continue
            totals["split_citations"] += 1
            unnamed = [g["id"] for g in unique.values() if not g["caseName"]]
            if unnamed:
                totals["split_with_an_unnamed_member"] += 1
            findings.append({
                "path": path.name,
                "citation": key,
                "group_ids": sorted(unique),
                "case_names": {gid: unique[gid]["caseName"] for gid in sorted(unique)},
                "unnamed_groups": unnamed,
                "contexts": {
                    gid: text[max(0, (unique[gid]["header"].get("span") or [0])[0] - 120):
                              (unique[gid]["header"].get("span") or [0, 0])[0]]
                    for gid in sorted(unique)
                },
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"totals": totals, "findings": findings},
                                   indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(totals))
    for item in findings[:20]:
        if item.get("error"):
            print("  ERROR", item["path"], item["error"])
            continue
        print(f"  {item['path']} {item['citation']} -> {item['group_ids']} "
              f"names={item['case_names']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
