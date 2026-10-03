"""Show every citation pair whose gap contains a history phrase, and the verdict.

`audit_history_merges.py` only lists gaps the rule accepts. When it accepts none
on a real corpus, the useful question is why not, so this prints every gap that
mentions a history word at all together with the reason it was refused.

Usage:
    python scripts/audit_history_rejects.py --inputs <file> [...] --limit 40
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GROUP = importlib.import_module("caselaw.group")
from caselaw.extract import extract_pairs  # noqa: E402

HISTORY_WORD = re.compile(
    r"\b(?:aff'?d|affirmed|rev'?d|reversed|vacated|cert\.|adopted|overruled|"
    r"abrogated|superseded|depublished|remanded|withdrawn)\b",
    re.IGNORECASE,
)


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    with pymupdf.open(path) as doc:
        return "".join(page.get_text("text", sort=True) for page in doc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()

    files: list[Path] = []
    for item in args.inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*") if p.suffix.lower() == ".pdf"))
        else:
            files.append(item)

    refused = 0
    accepted = 0
    long_gap = 0
    shown = 0
    for path in files:
        try:
            text = text_for(path)
            pairs = extract_pairs(text)
        except Exception:  # noqa: BLE001
            continue
        spans = [c.span() for c, rec in pairs
                 if c is not None and rec.kind == "FullCaseCitation"]
        for a, b in zip(spans, spans[1:]):
            gap = text[a[1]:b[0]]
            if not HISTORY_WORD.search(gap):
                continue
            if GROUP._PARALLEL_GAP.fullmatch(text, a[1], b[0]):
                continue
            ok = GROUP._is_subsequent_history(gap)
            if ok:
                accepted += 1
                continue
            refused += 1
            if len(gap) > GROUP._HISTORY_GAP_MAX:
                long_gap += 1
            pieces = [p.strip() for p in gap.split(",")]
            pieces = [p for p in pieces if p]
            bad = [p for p in pieces
                   if not GROUP._HISTORY_PHRASE.match(p)
                   and not GROUP._PIN_OR_PARENTHETICAL.match(p)]
            if shown < args.limit:
                shown += 1
                print(f"REFUSED {path.name}")
                print(f"   first={text[a[0]:a[1]]!r} second={text[b[0]:b[1]]!r} len={len(gap)}")
                print(f"   gap={gap!r}")
                print(f"   pieces={pieces}")
                print(f"   offending={bad[:3]}")
    print()
    print(f"accepted={accepted} refused={refused} refused_because_too_long={long_gap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
