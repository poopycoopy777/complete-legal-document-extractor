"""Show [PROPOSITION] diff blocks whose new value is a history fragment."""

from __future__ import annotations

import re
import sys

lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
for index, line in enumerate(lines):
    if not line.startswith("[PROPOSITION]"):
        continue
    block = lines[index: index + 3]
    if len(block) >= 3 and re.search(r"aff|rev|vacat", block[2]):
        print(block[0])
        print(block[1][:170])
        print(block[2][:170])
