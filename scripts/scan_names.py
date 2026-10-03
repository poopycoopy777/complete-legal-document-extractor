"""Scan HEAD dumps for case names that look like a fabricated " v. " split.

A name with two " v. " occurrences, or a one-to-three-letter token before the
first " v. ", is the signature of _normalize_glued_versus rewriting the "v." of
an abbreviation ("Serv." -> "Ser v.", "Inv." -> "In v.", "Priv." -> "Pri v.").

Usage: python scripts/scan_names.py output/cmp_head_storage.json [...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SUSPECT = re.compile(r"^.{0,3} v\. | v\. .* v\. ")


def check(name: str | None) -> bool:
    if not name:
        return False
    return bool(SUSPECT.search(name)) or name.rstrip().endswith((" Co.", " v.", " Inc.")) and len(name) < 12


def main() -> int:
    total_docs = 0
    hits: dict[str, list[str]] = {}
    for path in sys.argv[1:]:
        for entry in json.loads(Path(path).read_text(encoding="utf-8")):
            doc = entry.get("old")
            if not doc:
                continue
            total_docs += 1
            names = set()
            for g in doc["groups"]:
                names.add(g.get("caseName"))
                names.add(g["header"].get("plaintiff"))
                names.add(g["header"].get("defendant"))
                names.add(g["header"].get("case_name"))
                for c in g["children"]:
                    names.add(c.get("plaintiff"))
                    names.add(c.get("defendant"))
                    names.add(c.get("case_name"))
            flagged = sorted(n for n in names if check(n))
            if flagged:
                hits.setdefault(entry["name"], []).extend(flagged)
    print(f"documents scanned: {total_docs}, documents with a suspect name: {len(hits)}")
    for name, names in sorted(hits.items()):
        print(f"  {name}: {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
