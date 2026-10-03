"""Short forms that share a name across two cases are resolved by evidence.

The Opening Brief (2025CA2333) cites People v. Woo, 579 P.3d 459, and Woo v. El
Paso County Sheriff's Office, 528 P.3d 899. eyecite will not resolve "Woo at 902"
or "Woo, supra at 910" when two cases carry the name, so each stayed an orphan
and the quotation in front of it stayed unattributed. A short form is now bound
when exactly one case fits its name, the caption it prints, and its pin page,
and is otherwise left unresolved and flagged, never guessed.

These tests drive eyecite's resolver with the functions from
caselaw.shortforms, which is how caselaw.group wires them in.
"""

from eyecite import resolve_citations

from caselaw.extract import extract_pairs
from caselaw.shortforms import MAX_OPINION_PAGES, short_form_resolvers

PEOPLE_V_WOO = "People v. Woo, 579 P.3d 459 (Colo. App. 2025)"
WOO_V_EL_PASO = "Woo v. El Paso County Sheriff\u2019s Office, 528 P.3d 899 (Colo. 2022)"
FULLS = f"Two cases matter: {PEOPLE_V_WOO}, and {WOO_V_EL_PASO}.\n\n"


def _resolve(text):
    """{short-form text: full citation it resolved to or None}, and the records."""
    pairs = extract_pairs(text)
    resolved = resolve_citations(
        [cite for cite, _ in pairs], **short_form_resolvers(pairs, text)
    )
    by_cite = {id(cite): record for cite, record in pairs}
    outcome = {}
    for members in resolved.values():
        header = next(by_cite[id(m)] for m in members if by_cite[id(m)].kind == "FullCaseCitation")
        for member in members:
            record = by_cite[id(member)]
            if record.kind != "FullCaseCitation":
                outcome[" ".join(record.text.split())] = header.full_citation
    records = [record for _, record in pairs if record.kind != "FullCaseCitation"]
    return outcome, records


def _record(records, text):
    return next(r for r in records if " ".join(r.text.split()) == text)


def test_pin_page_selects_the_case_whose_opinion_contains_it():
    text = FULLS + "The court said so. Woo at 902.\n\nAnd later, Woo at 910.\n"
    outcome, _ = _resolve(text)
    assert outcome["Woo at 902"] == WOO_V_EL_PASO
    assert outcome["Woo at 910"] == WOO_V_EL_PASO


def test_pin_page_selects_the_other_case_when_only_it_fits():
    outcome, _ = _resolve(FULLS + "Here, Woo at 470.\n")
    assert outcome["Woo at 470"] == PEOPLE_V_WOO


def test_supra_with_a_pin_page_is_resolved_by_the_page():
    outcome, _ = _resolve(FULLS + "As explained in Woo, supra at 910, it follows.\n")
    assert outcome["supra at 910"] == WOO_V_EL_PASO


def test_supra_that_prints_its_own_caption_is_resolved_by_the_caption():
    """"People v. Woo, supra at 465" names People explicitly."""
    outcome, _ = _resolve(FULLS + "The standard is clear. See People v. Woo, supra at 465.\n")
    assert outcome["supra at 465"] == PEOPLE_V_WOO


def test_printed_caption_wins_over_a_pin_that_fits_neither_by_page_alone():
    outcome, _ = _resolve(FULLS + "See Woo v. El Paso County Sheriff\u2019s Office, supra at 905.\n")
    assert outcome["supra at 905"] == WOO_V_EL_PASO


def test_caption_and_pin_that_disagree_resolve_to_nothing():
    """People names the first case, but page 902 is not in that opinion."""
    outcome, records = _resolve(FULLS + "See People v. Woo, supra at 902.\n")
    assert "supra at 902" not in outcome
    assert any(f.startswith("short_form_unresolved") for f in _record(records, "supra at 902").flags)


def test_short_form_with_no_pin_and_no_caption_stays_ambiguous_and_is_flagged():
    outcome, records = _resolve(FULLS + "As Woo, supra, explains, the rule is old.\n")
    assert not [k for k in outcome if k.startswith("supra")]
    flags = _record(records, "supra,").flags
    (flag,) = [f for f in flags if f.startswith("short_form_ambiguous")]
    assert "579 P.3d 459" in flag and "528 P.3d 899" in flag


def test_pin_beyond_every_candidate_is_unresolved_not_nearest():
    outcome, records = _resolve(FULLS + "And Woo at 5000.\n")
    assert "Woo at 5000" not in outcome
    assert any(f.startswith("short_form_unresolved") for f in _record(records, "Woo at 5000").flags)


def test_pin_below_every_candidate_is_unresolved():
    outcome, _ = _resolve(FULLS + "And Woo at 12.\n")
    assert "Woo at 12" not in outcome


def test_pin_bound_is_the_documented_opinion_length():
    assert MAX_OPINION_PAGES == 150
    inside = 459 + MAX_OPINION_PAGES
    outside = inside + 1
    outcome, _ = _resolve(FULLS + f"First, Woo at {inside}. Second, Woo at {outside}.\n")
    assert outcome[f"Woo at {inside}"] == PEOPLE_V_WOO
    assert f"Woo at {outside}" not in outcome


def test_two_cases_that_both_fit_the_pin_stay_ambiguous():
    text = (
        "See Smith v. Alpha Corp., 100 P.3d 100 (Colo. 2001); Smith v. Beta Corp., "
        "100 P.3d 120 (Colo. 2002).\n\nHere, Smith at 130.\n"
    )
    outcome, records = _resolve(text)
    assert "Smith at 130" not in outcome
    assert any(f.startswith("short_form_ambiguous") for f in _record(records, "Smith at 130").flags)


def test_pin_separates_two_cases_that_share_a_name_and_a_reporter():
    text = (
        "See Smith v. Alpha Corp., 100 P.3d 100 (Colo. 2001); Smith v. Beta Corp., "
        "100 P.3d 400 (Colo. 2002).\n\nHere, Smith at 410.\n"
    )
    outcome, _ = _resolve(text)
    assert outcome["Smith at 410"] == "Smith v. Beta Corp., 100 P.3d 400 (Colo. 2002)"


def test_a_name_that_only_one_case_carries_still_resolves_without_a_pin():
    """eyecite's own behaviour for an unambiguous name is unchanged."""
    text = (
        "See People v. Angerstein, 572 P.2d 479 (Colo. 1977); Whelden v. Board, "
        "782 P.2d 853 (Colo. App. 1989).\n\nAngerstein, supra, is dispositive.\n"
    )
    outcome, _ = _resolve(text)
    assert outcome["supra,"] == "People v. Angerstein, 572 P.2d 479 (Colo. 1977)"


def test_a_unique_name_is_not_second_guessed_by_the_pin():
    """Bounding by pin is evidence for choosing between cases, not a veto."""
    text = "See People v. Angerstein, 572 P.2d 479 (Colo. 1977).\n\nAngerstein, supra at 9000, says so.\n"
    outcome, _ = _resolve(text)
    assert outcome["supra at 9000"] == "People v. Angerstein, 572 P.2d 479 (Colo. 1977)"


def test_a_short_form_never_resolves_to_a_case_cited_after_it():
    text = "Early on, Woo at 902.\n\n" + FULLS
    outcome, _ = _resolve(text)
    assert "Woo at 902" not in outcome
