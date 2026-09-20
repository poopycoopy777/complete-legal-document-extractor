"""Generate and check one citation per state code, from that state's own spec.

The generated-initialism work claimed coverage for 45 state codes on the
strength of 26 hand-written probes. This closes that gap without inventing
citation formats: each fixture is built by reading the state's own CiteURL
pattern, substituting concrete values for its tokens and its literal
separators, and then asserting the result extracts back to that same state.

It is a self-consistency check, not an authority on Bluebook form. It proves a
template matches text written to its own specification; it does not prove the
specification matches what practitioners in that state actually write. Those
are different claims and only the first one is made here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import citeurl
import yaml

from caselaw.authorities import _initialisms, _resolve_pattern, extract_authorities

SECTION = "§"

# Concrete values substituted for each token name. Chosen to satisfy the token
# regexes across templates (they are all digit-ish with optional letters).
_TOKEN_VALUES = {
    "title": "24",
    "chapter": "72",
    "article": "72",
    "division": "24",
    "section": "303",
    "part": "3",
    "code": "Penal",
    "paragraph": "3",
}

_TOKEN = re.compile(r"\{(?P<name>[\w ]+)\}")


def _literal(fragment: str) -> str | None:
    """Turn a separator fragment of a pattern into one concrete character."""
    fragment = fragment.strip()
    if not fragment:
        return ""
    # "[-‑–]" -> "-"
    klass = re.fullmatch(r"\[([^\]]+)\]", fragment)
    if klass:
        first = klass.group(1)[0]
        return "-" if first in "-‑–" else first
    # "\." -> "."
    if re.fullmatch(r"\\(.)", fragment):
        return fragment[1]
    if re.fullmatch(r"[.:,\-]", fragment):
        return fragment
    return None


def body_for(name: str, raw: dict) -> str | None:
    """The "24-72-303" part of a citation, built from the template's tokens."""
    pattern = _resolve_pattern(name, raw)
    if not pattern:
        return None
    joined = "".join(pattern)

    # The token run is the longest stretch of {token}separator{token}...
    best: str | None = None
    for match in re.finditer(
        r"(\{[\w ]+\}(?:(?:\[[^\]]+\]|\\.|[.:,-])\{[\w ]+\})+)", joined
    ):
        run = match.group(1)
        if "name regex" in run:
            continue
        if best is None or len(run) > len(best):
            best = run
    if best is None:
        # Single-token bodies, e.g. "{section}".
        singles = [m for m in _TOKEN.finditer(joined) if m.group("name") != "name regex"]
        if not singles:
            return None
        value = _TOKEN_VALUES.get(singles[0].group("name"))
        return value

    out: list[str] = []
    cursor = 0
    for match in _TOKEN.finditer(best):
        separator = _literal(best[cursor : match.start()])
        if separator is None:
            return None
        out.append(separator)
        value = _TOKEN_VALUES.get(match.group("name"))
        if value is None:
            return None
        out.append(value)
        cursor = match.end()
    return "".join(out)


def fixtures() -> list[tuple[str, str, str]]:
    """(state template name, form, citation text) for every state code."""
    root = Path(citeurl.__file__).parent / "templates"
    raw = yaml.safe_load((root / "state law.yaml").read_text(encoding="utf-8"))

    rows: list[tuple[str, str, str]] = []
    for name, data in raw.items():
        if not isinstance(data, dict) or "constitution" in name.lower():
            continue
        body = body_for(name, raw)
        if not body:
            continue
        abbreviation = (data.get("meta") or {}).get("abbreviation")
        if abbreviation:
            rows.append((name, "long", f"{abbreviation} {SECTION} {body}"))
        for initialism in _initialisms(name):
            if " " in initialism:
                continue  # multi-word overrides are long forms already
            dotted = ".".join(initialism) + "."
            rows.append((name, "initialism", f"{dotted} {SECTION} {body}"))
    return rows


def main() -> int:
    rows = fixtures()
    passed, wrong, missed = [], [], []
    for name, form, text in rows:
        found = extract_authorities(text)
        if not found:
            missed.append((name, form, text))
        elif found[0].source != name:
            wrong.append((name, form, text, found[0].source))
        else:
            passed.append((name, form, text))

    total = len(rows)
    print(f"fixtures: {total}")
    print(f"  extracted to the right state : {len(passed)}")
    print(f"  extracted to the WRONG state : {len(wrong)}")
    print(f"  not extracted at all         : {len(missed)}")
    if total:
        print(f"  accuracy                     : {len(passed) / total:.1%}")

    if wrong:
        print("\nWRONG STATE:")
        for name, form, text, got in wrong[:20]:
            print(f"  {text!r:38} {form:10} want {name!r}, got {got!r}")
    if missed:
        print("\nNOT EXTRACTED:")
        for name, form, text in missed[:25]:
            print(f"  {text!r:38} {form:10} {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
