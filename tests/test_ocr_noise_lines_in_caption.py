"""Stray OCR marks on their own lines must not truncate a wrapped caption.

`2026-02-22_01_Judges_Orders_Show_Cause.pdf` OCRs to

    See also Freedom Colorado Information,
    <U+FFFD>
    a
    inc. v. Ef Paso County Sheriff's Department, 196 P.3d 892 (Colo. 2008),

The backward scan stopped at the lone "a", so the case was reported as "inc. v.
Ef Paso County Sheriff's Department" and the proposition swallowed the
caption's first party.
"""

from __future__ import annotations

from caselaw.extract import _derive_parties
from caselaw.group import group_citations

NOISY = (
    "mental health crisis, victim interview, or the interior of homes or "
    "treatment facilities. See also Freedom Colorado Information,\n"
    "�\n"
    "a\n"
    "inc. v. Ef Paso County Sheriff's Department, 196 P.3d 892 (Colo. 2008),\n"
    ".\n"
    "THEREFORE, considering the foregoing, the Court hereby FINDS."
)


def test_full_document_keeps_the_whole_caption_and_a_clean_proposition():
    (group,) = group_citations(NOISY).groups
    assert group.case_name == "Freedom Colorado Information, inc. v. Ef Paso County Sheriff's Department"
    proposition = group.proposition[1]
    assert proposition.text == (
        "mental health crisis, victim interview, or the interior of homes or treatment facilities.")
    assert proposition.signal == "See also"


def test_noise_lines_do_not_cut_the_first_party():
    window = "See also Freedom Colorado Information,\n�\na\ninc. v. Ef Paso County Sheriff's Department, "
    assert _derive_parties(window) == (
        "Freedom Colorado Information, inc.", "Ef Paso County Sheriff's Department")


def test_marks_and_punctuation_lines_are_dropped():
    window = "Freedom Colorado Information,\n;\n‘\nInc. v. El Paso County Sheriff's Department, "
    assert _derive_parties(window) == (
        "Freedom Colorado Information, Inc.", "El Paso County Sheriff's Department")


def test_ampersand_and_versus_lines_are_party_text_not_noise():
    assert _derive_parties("Smith\n&\nJones Co. v. Doe, ") == ("Smith & Jones Co.", "Doe")
    assert _derive_parties("See Smith\nv.\nDoe, ") == ("Smith", "Doe")


def test_a_real_lowercase_word_line_is_not_noise():
    assert _derive_parties("the court relied on\nAcme Co. v. Smith, ") == ("Acme Co.", "Smith")
