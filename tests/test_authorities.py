"""Tests for statute, regulation, rule and constitution extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from caselaw.authorities import (
    _initialism_regex,
    _initialisms,
    _is_balanced,
    build_citator,
    extract_authorities,
)
from caselaw.group import group_citations

SECTION = "§"


def one(text: str):
    found = extract_authorities(text)
    assert found, f"nothing extracted from {text!r}"
    return found[0]


# --- the upstream encoding defect being worked around ----------------------


def test_section_sign_citations_are_matched():
    """CiteURL loads its templates without an encoding argument, so on a
    non-UTF-8 default (any stock Windows) every section sign in the bundled
    patterns becomes mojibake and no real section cite can ever match."""
    cite = one(f"42 U.S.C. {SECTION} 1983")
    assert cite.source == "U.S. Code"
    assert cite.category == "statute"


def test_templates_load_without_mojibake():
    citator = build_citator()
    pattern = "".join(citator.templates["U.S. Code"].patterns)
    assert "§" in pattern
    assert "Â§" not in pattern, "templates decoded with the wrong codec"


# --- categories ------------------------------------------------------------


@pytest.mark.parametrize(
    "text,category,source",
    [
        (f"42 U.S.C. {SECTION} 1983", "statute", "U.S. Code"),
        (f"28 C.F.R. {SECTION} 20.21", "regulation", "Code of Federal Regulations"),
        ("Fed. R. Civ. P. 12(b)(6)", "rule", "Federal Rules of Civil Procedure"),
        ("Fed. R. Evid. 702", "rule", "Federal Rules of Evidence"),
        ("Fed. R. App. P. 4", "rule", "Federal Rules of Appellate Procedure"),
        ("Fed. R. Crim. P. 11", "rule", "Federal Rules of Criminal Procedure"),
        ("U.S. Const. amend. XIV", "constitution", "U.S. Constitution Amendments"),
    ],
)
def test_categories(text, category, source):
    cite = one(text)
    assert (cite.category, cite.source) == (category, source)


# --- state coverage is generated, not hand-written -------------------------


@pytest.mark.parametrize(
    "text,source",
    [
        (f"C.R.S. {SECTION} 24-72-303", "Colorado Revised Statutes"),
        (f"N.R.S. {SECTION} 200.471", "Nevada Revised Statutes"),
        ("R.C.W. 9A.36.041", "Revised Code of Washington"),
        (f"O.C.G.A. {SECTION} 16-5-23", "Georgia Code"),
        (f"O.R.C. {SECTION} 2903.13", "Ohio Revised Code"),
        (f"N.D.C.C. {SECTION} 12.1-17-01", "North Dakota Century Code"),
        (f"A.R.S. {SECTION} 13-1203", "Arizona Revised Statutes"),
        (f"M.C.L. {SECTION} 750.81", "Michigan Compiled Laws"),
        (f"O.R.S. {SECTION} 163.160", "Oregon Revised Statutes"),
        (f"K.R.S. {SECTION} 508.030", "Kentucky Revised Statutes"),
        (f"S.D.C.L. {SECTION} 22-18-1", "South Dakota Codified Laws"),
        (f"H.R.S. {SECTION} 707-712", "Hawaii Revised Statutes"),
    ],
)
def test_state_initialisms(text, source):
    """Initialism forms are generated for every state from its own template."""
    cite = one(text)
    assert cite.source == source
    assert cite.category == "statute"


def test_postfix_state_form():
    """Several states write the code after the section."""
    cite = one(f"{SECTION} 24-72-303, C.R.S.")
    assert cite.source == "Colorado Revised Statutes"


def test_long_form_still_matches():
    cite = one(f"Colo. Rev. Stat. {SECTION} 24-72-303")
    assert cite.source == "Colorado Revised Statutes"


def test_generated_coverage_spans_many_states():
    citator = build_citator()
    generated = [name for name in citator.templates if "[" in name]
    assert len(generated) >= 60, f"only {len(generated)} generated templates"


# --- helpers ---------------------------------------------------------------


def test_two_letter_initialisms_are_rejected():
    """ "IC" is both Idaho Code and Iowa Code, and matches ordinary prose."""
    assert _initialisms("Idaho Code") == []
    assert _initialisms("Iowa Code") == ["IOWA CODE"]  # via the override table


def test_initialism_regex_accepts_spacing_and_periods():
    import re

    pattern = re.compile(_initialism_regex("CRS"))
    for form in ["C.R.S.", "CRS", "C. R. S.", "C.R.S.A."]:
        assert pattern.match(form), form


def test_balance_checker_rejects_split_groups():
    assert _is_balanced(["(abc)", "[)]", r"\("])
    assert not _is_balanced(["(abc"])
    assert not _is_balanced([")abc"])


# --- grouping --------------------------------------------------------------


def test_repeat_references_cascade_under_one_provision():
    text = (
        f"Claims arise under 42 U.S.C. {SECTION} 1983. "
        f"Later, 42 U.S.C. {SECTION} 1983 is discussed again."
    )
    result = group_citations(text)
    statutes = [a for a in result.authorities if a.category == "statute"]
    assert len(statutes) == 1
    assert len(statutes[0].children) == 1


def test_shortform_binds_to_the_matching_section_not_the_nearest_cite():
    """CiteURL attaches a short form to the nearest preceding citation of any
    template, which turns a trailing "Section 1983" into "28 C.F.R. § 1983"."""
    text = (
        f"Claims arise under 42 U.S.C. {SECTION} 1983. "
        f"See also 28 C.F.R. {SECTION} 20.21. Section 1983 again."
    )
    result = group_citations(text)
    sources = {a.source for a in result.authorities}
    assert sources == {"U.S. Code", "Code of Federal Regulations"}
    usc = next(a for a in result.authorities if a.source == "U.S. Code")
    assert len(usc.children) == 1
    assert "1983" in usc.children[0].text


def test_authorities_are_ordered_by_category():
    text = (
        f"U.S. Const. amend. XIV. Fed. R. Evid. 702. 28 C.F.R. {SECTION} 20.21. "
        f"42 U.S.C. {SECTION} 1983."
    )
    categories = [a.category for a in group_citations(text).authorities]
    assert categories == ["statute", "regulation", "rule", "constitution"]


def test_case_law_is_not_duplicated_into_authorities():
    """eyecite owns case law; the caselaw templates are deliberately not loaded."""
    text = "Monell v. Department of Social Services, 436 U.S. 658 (1978)."
    result = group_citations(text)
    assert len(result.groups) == 1
    assert result.authorities == []


def test_spans_round_trip_into_the_source():
    text = f"Moves under Fed. R. Civ. P. 56 and 42 U.S.C. {SECTION} 1983."
    for cite in extract_authorities(text):
        start, end = cite.span
        assert text[start:end] == cite.text


def test_empty_text():
    assert extract_authorities("") == []
    assert extract_authorities("   ") == []


def test_bare_numbers_are_not_treated_as_shortform_statutes():
    """CiteURL's idform patterns accept a bare section token once a full cite
    has been seen, so in a brief every page and paragraph number after the first
    statute cite matched as a short form. One real answer brief produced 816
    "citations" that way, of which 710 were bare numbers."""
    text = (
        f"Disclosure is governed by C.R.S. {SECTION} 24-31-902(2). "
        "The record at 13 and at 27 shows the 2023 incident; see pages 14, 21, "
        "29, 32, 36, 41 and 43 of the transcript."
    )
    found = extract_authorities(text)
    assert len(found) == 1, [f.text for f in found]
    assert found[0].text.startswith(SECTION) or "24-31-902" in found[0].text


def test_real_shortforms_survive_the_bare_number_filter():
    text = (
        f"Disclosure is governed by C.R.S. {SECTION} 24-31-902(2). "
        f"See also {SECTION} 24-72-305. Section 24-31-902 again."
    )
    found = extract_authorities(text)
    assert len(found) >= 3, [f.text for f in found]


@pytest.mark.parametrize("text,sections", [
    ("C.R.C.P.12(f)", ["12(f)"]),
    ("C.R.C.P. 121 Section 1-15 subsection (3)", ["121 Section 1-15(3)"]),
    ("C.R.C.P. 8", ["8"]),
    ("C.R.C.P. 12 or 56", ["12", "56"]),
])
def test_colorado_civil_rules_have_source_bound_occurrences(text, sections):
    found = extract_authorities(text)
    assert [a.tokens.get("section") for a in found] == sections
    for a in found:
        assert (a.category, a.source) == ("rule", "Colorado Rules of Civil Procedure")
        assert text[slice(*a.span)] == a.text
        assert a.name


def test_colorado_civil_rules_group_repeated_spellings():
    result = group_citations("C.R.C.P.12(f) and C. R. C. P. 12 (f).")
    assert len(result.authorities) == 1
    assert len(result.authorities[0].children) == 1


@pytest.mark.parametrize("text", ["Rules 12 or 56", "C.R.C.P. 12foo", "C.R.C.P. 8, 2026"])
def test_colorado_civil_rules_do_not_infer_unmarked_numbers(text):
    found = extract_authorities(text)
    assert [a.tokens["rule"] for a in found if a.source == "Colorado Rules of Civil Procedure"] == (["8"] if "8," in text else [])
