"""Dump the extractor's real output for one saved text file, in inspectable detail.

Usage: python scripts/dump_extraction.py <text-file> [--json <out.json>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402
from caselaw.record_cites import extract_record_cites  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    text = args.path.read_text(encoding="utf-8")
    data = group_citations(text).as_dict()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")

    print("STATS:", json.dumps(data.get("stats"), indent=2))
    print("ORPHANS:", len(data.get("orphans", [])))
    print("ORPHAN DETAIL:", json.dumps(data.get("orphans", []), ensure_ascii=True)[:1500])
    print("AUTHORITIES:", len(data.get("authorities", [])))
    for a in data.get("authorities", []):
        print("   ", json.dumps(a, ensure_ascii=True)[:600])
    print("UNATTRIBUTED QUOTES:", len(data.get("unattributedQuotes", [])))
    for g in data.get("groups", []):
        h = g["header"]
        print(
            f"[{g['id']}] caseName={g['caseName']!r} header={h['text']!r} "
            f"kind={h['kind']} pin={h['pin_cite']!r} flags={h['flags']}"
        )
        for c in g["children"]:
            print(
                f"        child kind={c['kind']} text={c['text']!r} span={c['span']} "
                f"pin={c['pin_cite']!r} flags={c['flags']}"
            )
        print(
            f"        quotes={len(g['quotes'])} "
            f"proposition={g['proposition']!r} propositionSpan={g['propositionSpan']}"
        )
        for q in g["quotes"]:
            print(f"        quote span={q.get('span')} text={q.get('text')!r} flags={q.get('flags')}")
    for rc in extract_record_cites(text):
        print("REC", rc.kind, repr(rc.label), rc.span, repr(rc.pin), repr(rc.text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
