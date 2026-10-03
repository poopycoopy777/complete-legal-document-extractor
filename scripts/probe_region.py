"""Show the source around an offset and what HEAD reports there.

Usage:
  python scripts/probe_region.py --file <pdf-or-txt> --at 2035 [--at 2683 ...] [--window 260]
  python scripts/probe_region.py --text "..."           # synthetic input from the CLI
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

    chunks: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text", sort=True))
    return "".join(chunks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path)
    parser.add_argument("--text", default=None)
    parser.add_argument("--at", type=int, action="append", default=[])
    parser.add_argument("--span", type=int, nargs=2, action="append", default=[])
    parser.add_argument("--window", type=int, default=260)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    text = args.text if args.text is not None else text_for(args.file)
    data = group_citations(text).as_dict()

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")

    for offset in args.at:
        print(f"--- around {offset} ---")
        print(repr(text[max(0, offset - args.window): offset + args.window]))

    interesting = [(g["header"]["span"][0], g["header"]["span"][1]) for g in data["groups"]]
    interesting += [(c["span"][0], c["span"][1]) for g in data["groups"] for c in g["children"]]
    interesting += [(o["span"][0], o["span"][1]) for o in data["orphans"]]
    interesting += [(a["header"]["span"][0], a["header"]["span"][1]) for a in data["authorities"]]
    interesting += [(c["span"][0], c["span"][1]) for a in data["authorities"] for c in a["children"]]
    interesting += [(r["header"]["span"][0], r["header"]["span"][1]) for r in data["records"]]
    interesting += [(q["span"][0], q["span"][1]) for g in data["groups"] for q in g["quotes"]]
    interesting += [(q["span"][0], q["span"][1]) for q in data["unattributedQuotes"]]

    for target in args.span:
        lo, hi = target
        print(f"--- overlapped by span {lo}-{hi} ---")
        print(repr(text[max(0, lo - 60): hi + 60]))
        for start, end in sorted(interesting):
            if start < hi and lo < end:
                print("   overlap:", start, end, repr(text[start:end][:90]))

    print("=== HEAD groups ===")
    for g in data["groups"]:
        h = g["header"]
        print(f"{g['id']} @{h['span'][0]}-{h['span'][1]} caseName={g['caseName']!r} "
              f"text={h['text'][:70]!r} P={h['plaintiff']!r} D={h['defendant']!r} "
              f"case_name={h['case_name']!r} pins={h.get('pin_cite')!r}")
        print(f"    full={h['full_citation']!r} flags={h['flags']}")
        for c in g["children"]:
            print(f"      child @{c['span'][0]}-{c['span'][1]} {c['kind']} {c['text'][:50]!r} "
                  f"P={c['plaintiff']!r} D={c['defendant']!r} cn={c['case_name']!r} flags={c['flags']}")
        print(f"    prop@{(g.get('propositionSpan') or [None])[0]}: {g['proposition']!r}")
    print("=== HEAD authorities ===")
    for a in data["authorities"]:
        print(f"{a['id']} @{a['header']['span'][0]}-{a['header']['span'][1]} "
              f"{a['header']['text'][:60]!r} name={a['header']['name']!r} short={a['header']['is_shortform']}")
        for c in a["children"]:
            print(f"    child @{c['span'][0]}-{c['span'][1]} {c['text'][:60]!r} "
                  f"short={c['is_shortform']}")
    print("=== HEAD records ===")
    for r in data["records"]:
        print(f"{r['id']} {r['kind']}:{r['label']} @{r['header']['span']} {r['header']['text']!r} "
              f"children={[c['span'] for c in r['children']]}")
    print("=== orphans ===")
    for o in data["orphans"]:
        print(f"  @{o['span']} {o['kind']} {o['text'][:60]!r} antecedent={o['antecedent']!r}")
    print("=== quotes ===")
    for g in data["groups"]:
        for q in g["quotes"]:
            print(f"  {g['id']} @{q['span']} {q['raw_text'][:60]!r} {q['attribution_basis']}")
    for r in data["records"]:
        for q in r["quotes"]:
            print(f"  {r['id']} @{q['span']} {q['raw_text'][:60]!r} {q['attribution_basis']}")
    for q in data["unattributedQuotes"]:
        print(f"  UNATTR @{q['span']} {q['raw_text'][:60]!r} {q['attribution_basis']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
