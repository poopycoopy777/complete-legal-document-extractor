"""CLI: python -m caselaw <file.txt> [--json] [--flagged-only]"""

import argparse
import json
import sys
from pathlib import Path

from .extract import extract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caselaw")
    parser.add_argument("path", type=Path, help="UTF-8 text file to extract from")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--flagged-only",
        action="store_true",
        help="only show citations carrying a flag",
    )
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"not a file: {args.path}", file=sys.stderr)
        return 2

    cites = extract(args.path.read_text(encoding="utf-8", errors="replace"))
    if args.flagged_only:
        cites = [c for c in cites if c.flags]

    if args.json:
        print(json.dumps([c.as_dict() for c in cites], indent=2))
        return 0

    for c in cites:
        head = f"{c.span[0]:>7}-{c.span[1]:<7} {c.kind:<18} {c.text}"
        print(head)
        if c.plaintiff:
            print(f"{'':<16}{c.plaintiff} v. {c.defendant}")
        bits = [
            b
            for b in (
                f"year={c.year}" if c.year else "",
                f"court={c.court}" if c.court else "",
                f"pin={c.pin_cite}" if c.pin_cite else "",
            )
            if b
        ]
        if bits:
            print(f"{'':<16}{'  '.join(bits)}")
        for f in c.flags:
            print(f"{'':<16}FLAG: {f}")
    total = len(cites)
    flagged = sum(1 for c in cites if c.flags)
    print(f"\n{total} citations, {flagged} flagged", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
