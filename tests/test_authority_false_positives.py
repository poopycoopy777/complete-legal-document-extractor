"""Authorities the extractor invented from text that cites no statute.

Both defects were found in two filed Colorado appellate briefs (Reply Brief and
Opening Brief, 2025CA2333) and each put a false "issue" in front of the user:

* CiteURL's id-form patterns read "Id." after any earlier statute cite as a
  short form and build a section number from whatever number came last -- a
  paragraph number, a page pin, a year -- so a case's "Id. at 962" became
  "C.R.S. 24-25-962".
* The California Code of Regulations template accepts a bare "CA" as its name,
  so the appellate case number "25 CA 2333" became "Cal. Code Regs. tit. 25,
  2333".
"""

import pytest

from caselaw.authorities import extract_authorities
from caselaw.group import group_citations

S = "\u00a7"

STATUTE = f"The weapon is governed by C.R.S. {S} 24-72-703 and nothing else. "
CASE = "People v. Johnson, 671 P.2d 958 (Colo. 1983). "


def _ids(text):
    return [a for a in extract_authorities(text) if a.text.lower().startswith("id")]


# --- Id. after a case, not a statute ---------------------------------------


def test_id_after_case_citation_is_not_a_statute():
    text = STATUTE + CASE + "The court held that findings are required. Id. at 962."
    assert _ids(text) == []


def test_id_followed_by_paragraph_number_is_not_a_statute():
    """Reply Brief: "...has standing to appeal. Id.\\n\\n   14. Any issue..."."""
    text = (
        f"The address is governed by C.R.S. {S} 18-12-103. "
        "People v. Angerstein, 572 P.2d 479 (Colo., 1977). "
        "If that final order is to be enforceable then the party that is "
        "aggrieved has standing to appeal. Id.\n\n   14. Any issue with the "
        "search warrant is not the subject of this appeal."
    )
    assert _ids(text) == []


def test_bare_id_after_case_is_not_a_statute():
    """Reply Brief: "flashlight and ski mask among others. Id. The case is distinct..."."""
    text = (
        f"The address is governed by C.R.S. {S} 18-12-103. "
        "The Angerstein case is dispositive. People v. Angerstein, 572 P.2d\n\n"
        "   479 (Colo., 1977). Burglary tools are often legal to possess, and "
        "the items included a flashlight and ski mask among others. Id. The "
        "case is distinct from this one."
    )
    assert _ids(text) == []


def test_id_with_page_pin_never_mints_a_section_even_after_a_statute():
    """A statute has no pages: "Id. at 962" is not "24-72-962"."""
    text = STATUTE + "Id. at 962 says otherwise."
    assert _ids(text) == []


def test_every_id_after_a_case_chain_is_rejected():
    text = STATUTE + CASE + "Held so. Id. at 962. And again. Id. Still so. Id. at 963."
    assert _ids(text) == []


def test_id_after_case_does_not_reach_back_past_the_case_to_the_statute():
    text = STATUTE + "Then " + CASE + "Id."
    assert _ids(text) == []


def test_group_citations_reports_no_id_statute_for_case_ids():
    text = STATUTE + CASE + "Held so. Id. at 962.\n\n14. Next paragraph. Id.\n\n15. More."
    result = group_citations(text)
    members = [a for g in result.authorities for a in (g.header, *g.children)]
    assert [a.text for a in members if a.text.lower().startswith("id")] == []
    assert [g.header.name for g in result.authorities] == ["Colo. Rev. Stat. " + S + " 24-72-703"]


# --- Id. after a statute keeps working -------------------------------------


def test_bare_id_directly_after_a_statute_attaches_to_that_statute():
    text = f"Governed by C.R.S. {S} 24-31-902(2). Id."
    found = extract_authorities(text)
    assert [a.text for a in found] == [f"C.R.S. {S} 24-31-902(2)", "Id."]
    assert found[1].is_shortform
    assert found[1].name == found[0].name == "Colo. Rev. Stat. " + S + " 24-31-902(2)"
    assert found[1].tokens == found[0].tokens
    assert text[slice(*found[1].span)] == "Id."


def test_id_with_explicit_section_after_a_statute_is_kept():
    text = f"Governed by C.R.S. {S} 24-31-902(2). Id. {S} 24-31-903."
    found = extract_authorities(text)
    assert found[-1].text == f"Id. {S} 24-31-903"
    assert found[-1].name == "Colo. Rev. Stat. " + S + " 24-31-903"


def test_id_after_a_federal_statute_and_a_rule_follows_the_nearest_one():
    text = f"Claims arise under 42 U.S.C. {S} 1983. See Fed. R. Civ. P. 56. Id."
    found = extract_authorities(text)
    last = found[-1]
    assert last.text == "Id."
    assert last.name == "Fed. R. Civ. P. 56"
    assert last.category == "rule"


def test_id_chains_through_an_accepted_id():
    text = f"Governed by 42 U.S.C. {S} 1983. Id. Again. Id."
    found = extract_authorities(text)
    assert [a.text for a in found] == [f"42 U.S.C. {S} 1983", "Id.", "Id."]
    assert {a.name for a in found} == {f"42 U.S.C. {S} 1983"}


def test_statute_cited_after_a_case_owns_the_next_id():
    text = CASE + f"Held so. See C.R.S. {S} 24-72-703. Id."
    found = extract_authorities(text)
    assert [a.text for a in found] == [f"C.R.S. {S} 24-72-703", "Id."]
    assert found[1].name == found[0].name


def test_short_case_citation_between_statute_and_id_blocks_the_id():
    text = STATUTE + "Johnson, 671 P.2d at 960. Id."
    text = CASE + text
    assert _ids(text) == []


# --- appellate case numbers are not regulations ----------------------------


@pytest.mark.parametrize("text", [
    "Court of Appeals Case\nAttorneys for Appellant        Number: 25 CA 2333\nElizabeth",
    "Colorado Court of Appeals No. 25 CA 2333",
    "Colorado Court of Appeals Case No. 25CA2333",
    "CASE NUMBER: 2025CA2333",
    "Court of Appeals Case Number 2025CA002333",
    "In re 25 CA 2333 the court of appeals",
    "Number: 25 CA 2333.",
])
def test_appellate_case_number_is_not_a_regulation(text):
    assert extract_authorities(text) == []


def test_real_california_regulation_still_extracts():
    text = f"See Cal. Code Regs. tit. 25, {S} 2333 for the standard."
    found = extract_authorities(text)
    assert [a.name for a in found] == ["Cal. Code Regs. Tit. 25, " + S + " 2333"]
    assert found[0].category == "regulation"


@pytest.mark.parametrize("text", [
    "See 25 CCR 2333 for the standard.",
    f"See Cal. Code Regs., tit. 25, {S} 2333 for the standard.",
])
def test_other_real_california_spellings_still_extract(text):
    found = extract_authorities(text)
    assert [a.category for a in found] == ["regulation"]


def test_case_number_beside_a_real_citation_leaves_the_citation_alone():
    text = f"Number: 25 CA 2333. The weapon is governed by C.R.S. {S} 24-72-703."
    found = extract_authorities(text)
    assert [a.name for a in found] == ["Colo. Rev. Stat. " + S + " 24-72-703"]
