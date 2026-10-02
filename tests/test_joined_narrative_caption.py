from caselaw.extract import extract


def test_joined_narrative_preposition_preserves_actual_iqbal_parties_and_offsets():
    text = ('In the case ofAshcroft v. Iqbal, 556 U.S. 662 (2009), '
            'the Supreme Court held that factual allegations are required.')
    citation = next(c for c in extract(text) if c.kind == 'FullCaseCitation')
    assert citation.plaintiff == 'Ashcroft'
    assert citation.defendant == 'Iqbal'
    assert text[slice(*citation.span)] == citation.text == '556 U.S. 662'
    assert 'party_name_boundary_normalized: joined narrative preposition' in citation.flags


def test_joined_narrative_does_not_correct_a_misspelled_party():
    citation = next(c for c in extract('In the case ofAshcroft v. Igbal, 556 U.S. 662 (2009).')
                    if c.kind == 'FullCaseCitation')
    assert citation.defendant == 'Igbal'


def test_party_beginning_with_of_is_not_rewritten():
    citation = next(c for c in extract('OfAshcroft v. Igbal, 556 U.S. 662 (2009).')
                    if c.kind == 'FullCaseCitation')
    assert citation.plaintiff == 'OfAshcroft'
