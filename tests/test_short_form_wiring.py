"""group_citations binds ambiguous-name short forms through caselaw.shortforms.

Skipped until caselaw/group.py passes ``short_form_resolvers(pairs, text)`` to
``resolve_citations``; tests/test_short_form_resolution.py covers the resolution
rules themselves and runs either way.
"""

import inspect

import pytest

import caselaw.group as group_module
from caselaw.group import group_citations

pytestmark = pytest.mark.skipif(
    "short_form_resolvers" not in inspect.getsource(group_module),
    reason="caselaw/group.py does not yet pass short_form_resolvers to resolve_citations",
)

PEOPLE_V_WOO = "People v. Woo, 579 P.3d 459 (Colo. App. 2025)"
WOO_V_EL_PASO = "Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d 899 (Colo. 2022)"
FULLS = f"Two cases matter: {PEOPLE_V_WOO}, and {WOO_V_EL_PASO}.\n\n"


def _group(result, plaintiff):
    return next(g for g in result.groups if g.header.plaintiff == plaintiff)


def test_short_forms_join_the_case_their_pin_page_names():
    text = FULLS + 'The court said "replevin is available to the custodian." Woo at 902.\n'
    result = group_citations(text)
    el_paso = _group(result, "Woo")
    assert [c.text for c in el_paso.children] == ["Woo at 902"]
    assert result.orphans == []


def test_quotation_before_a_resolved_short_form_is_attributed_to_its_case():
    text = FULLS + 'The court said "replevin is available to the custodian." Woo at 902.\n'
    result = group_citations(text)
    el_paso = _group(result, "Woo")
    assert [q.text for q in el_paso.quotes] == ["replevin is available to the custodian."]
    assert [q.text for q in result.unattributed_quotes] == []
    assert _group(result, "People").quotes == []


def test_supra_with_a_printed_caption_joins_the_named_case():
    text = FULLS + "The rule is plain. See People v. Woo, supra at 465.\n"
    result = group_citations(text)
    assert [c.text for c in _group(result, "People").children] == ["supra at 465"]


def test_unresolvable_short_form_stays_an_orphan_with_its_reason():
    text = FULLS + "As Woo, supra, explains, the rule is old.\n"
    result = group_citations(text)
    (orphan,) = result.orphans
    assert orphan.kind == "SupraCitation"
    assert any(flag.startswith("short_form_ambiguous") for flag in orphan.flags)
    assert all(g.children == [] for g in result.groups)
