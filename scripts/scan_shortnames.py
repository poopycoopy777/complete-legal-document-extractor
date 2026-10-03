"""Scan HEAD dumps for case names that are a signal word or a bare fragment.

Two signatures of the _derive_short_case_name fallback:

* the name starts with a Bluebook signal ("See Bell Atlantic Corp.");
* the name is a bare abbreviation fragment ("Co.", "R.R. Co."), i.e. no " v. ",
  no "In re"/"Ex parte", and no more than three tokens.

Usage: python scripts/scan_shortnames.py output/cmp_head_storage.json [...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SIGNAL = re.compile(
    r"^(?:see|cf\.|accord|compare|contra|but|also|e\.g\.|generally|citing|quoting|"
    r"quoted|following|applying|applied|rejecting|adopting|under|per|held|holding)\b",
    re.IGNORECASE,
)
NON_ADVERSARIAL = re.compile(r"\bIn re\b|\bEx parte\b|\bMatter of\b|\bInterest of\b", re.IGNORECASE)


def fragment(name: str) -> bool:
    if " v. " in name or NON_ADVERSARIAL.search(name):
        return False
    words = name.split()
    if len(words) > 3:
        return False
    return bool(re.fullmatch(r"(?:[A-Z][\w'./&-]*\.?\s*)+", name))


def main() -> int:
    count = {"signal": 0, "fragment": 0}
    seen: set[str] = set()
    for arg in sys.argv[1:]:
        for entry in json.loads(Path(arg).read_text(encoding="utf-8")):
            doc = entry.get("old")
            if not doc or entry["name"] in seen:
                continue
            seen.add(entry["name"])
            for g in doc["groups"]:
                name = g.get("caseName")
                if not name:
                    continue
                kind = "signal" if SIGNAL.match(name) else ("fragment" if fragment(name) else None)
                if kind:
                    count[kind] += 1
                    print(f"{kind.upper():9s} {entry['name']} {g['id']}@{g['header']['span'][0]} "
                          f"caseName={name!r} header={g['header']['text'][:40]!r}")
    print(f"documents: {len(seen)}  signals: {count['signal']}  fragments: {count['fragment']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
