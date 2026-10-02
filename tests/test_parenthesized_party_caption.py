import pytest

from caselaw.extract import extract


@pytest.mark.parametrize('caption,plaintiff,defendant', [
    ("Friends of the Earth, Inc. v. Laidlaw Env't Servs. (TOC), Inc.",
     'Friends of the Earth, Inc.', "Laidlaw Env't Servs. (TOC), Inc."),
    ('Acme (USA), Inc. v. Smith', 'Acme (USA), Inc.', 'Smith'),
])
def test_balanced_parenthetical_is_part_of_the_party(caption, plaintiff, defendant):
    text = f'See also {caption}, 528 U.S. 167, 189 (2000).'
    citation = next(c for c in extract(text) if c.kind == 'FullCaseCitation')
    assert citation.plaintiff == plaintiff
    assert citation.defendant == defendant
    assert text[slice(*citation.span)] == citation.text == '528 U.S. 167'
    assert not any(f.startswith('parties_unverified:') for f in citation.flags)


def test_wrapped_caption_after_another_citation_does_not_import_prior_parties():
    text = ("Prior v. Other, 550 U.S. 544 (2007); see also Friends of the Earth, Inc. "
            "v. Laidlaw Env't Servs.\n\n(TOC), Inc., 528 U.S. 167, 189 (2000).")
    citation = next(c for c in extract(text) if c.volume == '528')
    assert citation.plaintiff == 'Friends of the Earth, Inc.'
    assert citation.defendant == "Laidlaw Env't Servs. (TOC), Inc."


def test_unclosed_parenthetical_does_not_confirm_a_partial_caption():
    citation = next(c for c in extract('Friends v. Laidlaw (TOC, Inc., 528 U.S. 167 (2000).')
                    if c.kind == 'FullCaseCitation')
    assert citation.plaintiff is None
    assert citation.defendant is None
