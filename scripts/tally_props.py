"""Tally short / subsequent-history-looking new proposition values in a diff."""

from __future__ import annotations

import collections
import re
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
pat = re.compile(r"""^\s+new=(['"])(.*)\1$""")
hits: collections.Counter = collections.Counter()
for line in lines:
    m = pat.match(line)
    if not m:
        continue
    value = m.group(2)
    if value.startswith(",") or re.match(r"^(?:aff|rev|vacat|cert|modified|adopted|argued)", value) or len(value) < 25:
        hits[value] += 1
for value, count in hits.most_common(40):
    print(count, repr(value))
print("distinct:", len(hits), "total:", sum(hits.values()))
