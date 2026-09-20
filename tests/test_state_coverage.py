"""Fifty-state coverage, measured rather than asserted.

The generated-initialism work claimed coverage for 45 state codes on the
strength of 26 hand-written probes. These tests replace that claim with a
measurement: a citation is built for every state code from that state's own
CiteURL pattern and must extract back to the same state.

The claim being made is narrow. This proves a template matches text written to
its own specification, and that the 86 generated templates do not steal each
other's citations. It does not prove the specification matches what
practitioners in that state actually write; that needs real filings.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))

from state_fixtures import fixtures

from caselaw.authorities import extract_authorities

SECTION = "§"

# Built once: reading and compiling every state template is not cheap.
FIXTURES = fixtures()

# Forms the fixture generator cannot construct, because the citation puts the
# title before the code name or needs a subject volume. Each is checked below
# against the real-world form instead.
_GENERATOR_CANNOT_BUILD = {
    "Illinois Compiled Statutes",
    "Massachusetts General Laws",
    "Consolidated Laws of New York",
    "Florida Administrative Code",
    "Maryland Code",
    "Virgin Islands Code",
    "General Laws of Rhode Island",
    "South Dakota Codified Laws",
}


def test_fixtures_cover_most_states():
    names = {name for name, _, _ in FIXTURES}
    assert len(FIXTURES) >= 70, f"only {len(FIXTURES)} fixtures generated"
    assert len(names) >= 30, f"only {len(names)} distinct codes covered"


def test_no_state_citation_is_attributed_to_another_state():
    """The strongest property: 86 generated templates must not collide.

    A Colorado citation reported as Nevada law is worse than no match at all,
    because it is wrong with confidence.
    """
    wrong = []
    for name, form, text in FIXTURES:
        found = extract_authorities(text)
        if found and found[0].source != name:
            wrong.append((text, name, found[0].source))
    assert wrong == [], f"cross-state misattribution: {wrong[:5]}"


def test_generated_fixtures_mostly_extract():
    matched = [
        (name, text)
        for name, _, text in FIXTURES
        if any(f.source == name for f in extract_authorities(text))
    ]
    ratio = len(matched) / len(FIXTURES)
    assert ratio >= 0.85, f"only {ratio:.1%} of generated fixtures extracted"


@pytest.mark.parametrize(
    "want,text",
    [
        ("Illinois Compiled Statutes", "735 ILCS 5/2-619"),
        ("Massachusetts General Laws", f"Mass. Gen. Laws ch. 265, {SECTION} 13A"),
        ("Massachusetts General Laws", f"M.G.L. c. 265, {SECTION} 13A"),
        ("Consolidated Laws of New York", f"N.Y. Penal Law {SECTION} 120.00"),
        ("Florida Administrative Code", "Fla. Admin. Code R. 62-4.070"),
    ],
)
def test_real_world_forms_the_generator_cannot_build(want, text):
    """These failed as generated fixtures but are correct in practice."""
    found = extract_authorities(text)
    assert found and found[0].source == want, f"{text!r} -> {found}"


@pytest.mark.parametrize(
    "want,text",
    [
        ("General Laws of Rhode Island", f"R.I.G.L. {SECTION} 9-1-14"),
        ("General Laws of Rhode Island", f"RIGL {SECTION} 9-1-14"),
        ("South Dakota Codified Laws", f"S.D.C.L. {SECTION} 22-18-1"),
        ("South Dakota Codified Laws", f"SDCL {SECTION} 22-18-1"),
    ],
)
def test_generated_initialisms_rescue_upstream_templates(want, text):
    """CiteURL cannot match Rhode Island or South Dakota by their own names.

    Both inherit Alabama's pattern, which requires "Code" or "Stat" after the
    state name. Their actual names end in "Laws" -- "R.I. Gen. Laws",
    "S.D. Codified Laws" -- so the bundled templates can never match the
    abbreviation they themselves declare. The generated initialism forms are
    the only way these two states are matched at all.
    """
    found = extract_authorities(text)
    assert found and found[0].source == want, f"{text!r} -> {found}"


@pytest.mark.parametrize(
    "text",
    [
        f"R.I. Gen. Laws {SECTION} 9-1-14",
        f"S.D. Codified Laws {SECTION} 22-18-1",
    ],
)
def test_upstream_long_forms_remain_broken(text):
    """Pins the upstream defect. If this starts failing, CiteURL fixed it and
    the note in the README can come out."""
    assert extract_authorities(text) == [], f"upstream fixed: {text!r} now matches"


@pytest.mark.parametrize(
    "text",
    [
        f"Md. Code, Crim. Law {SECTION} 3-203",
        f"14 V.I.C. {SECTION} 2251",
        f"V.I. Code Title 14 {SECTION} 2251",
    ],
)
def test_known_uncovered_forms(text):
    """Documented gaps, pinned so a fix is noticed.

    Maryland's subject-volume form with a comma, and the Virgin Islands form
    that puts the title before the code name, are not matched.
    """
    assert extract_authorities(text) == [], f"now covered, update the README: {text!r}"
