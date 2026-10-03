"""Markdown emphasis wrapping a pasted caption must not hide the parties.

Pasting an italicised citation ("*Warne v. Hall*, 373 P.3d 588") left the
asterisks in the caption window, so eyecite read "Hall*" and the case name was
lost. The delimiters sit at the caption boundary, so only those two positions
are stripped; a real asterisk inside a party name is preserved.
"""

from caselaw.extract import extract


def test_markdown_emphasis_wrapping_a_caption_is_stripped():
    text = "See *Warne v. Hall*, 373 P.3d 588 (Colo. 2016)."
    citation = next(c for c in extract(text) if c.kind == "FullCaseCitation")
    assert citation.plaintiff == "Warne"
    assert citation.defendant == "Hall"
    assert not any(f.startswith("parties_unverified:") for f in citation.flags)


def test_underscore_emphasis_wrapping_a_caption_is_stripped():
    text = "See _Warne v. Hall_, 373 P.3d 588 (Colo. 2016)."
    citation = next(c for c in extract(text) if c.kind == "FullCaseCitation")
    assert citation.plaintiff == "Warne"
    assert citation.defendant == "Hall"


def test_non_adversarial_caption_emphasis_is_stripped():
    text = "See *In re Marriage of Rubio*, 313 P.3d 623 (Colo. 2013)."
    citation = next(c for c in extract(text) if c.kind == "FullCaseCitation")
    assert citation.case_name == "In re Marriage of Rubio"
