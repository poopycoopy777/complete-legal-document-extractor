"""An OCR-lowercased entity suffix must not erase the caption it closes.

`Cooper_v_Ingo_02-23-2026_Judges_Order_on_MTQ_Pino_BWC.pdf` prints "Freedom
Colorado Information, inc. v. Ei Paso County Sheriff's Department, 196 P.3d 892".
The capitalised-run walk stopped at "inc.", so the citation reached the report
with no case name at all.
"""

from __future__ import annotations

from caselaw.extract import _derive_parties


def test_ocr_lowercased_inc_keeps_the_caption_as_printed():
    window = ("facilities.  See  also Freedom   Colorado   Information,\n"
              "     inc.  v. Ei Paso  County  Sheriff's  Department,   ")
    assert _derive_parties(window) == (
        "Freedom Colorado Information, inc.", "Ei Paso County Sheriff's Department")


def test_lowercase_prose_before_a_caption_is_still_trimmed():
    assert _derive_parties("the court relied on Acme Co. v. Smith, ") == ("Acme Co.", "Smith")
