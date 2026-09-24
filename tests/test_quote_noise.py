"""Spans that are quoted but quote nothing must not reach verification.

Seen on a filed response to a motion to dismiss: the defined terms
("Plaintiff") and ("Defendants") were each "found" in the cited motion, and a
bare citation, "(Doc. 42 at p. 12).", was reported as a quotation missing from
it. Both inflate or contradict the record check without testing anything.
"""

from __future__ import annotations

from caselaw.extract import _trim_lead_in
from caselaw.group import _find_quotes, group_citations
from caselaw.record_cites import extract_record_cites


def _bodies(text: str) -> list[str]:
    return [body for _, _, body in _find_quotes(text)]


def test_defined_terms_are_not_quotations():
    text = (
        'Plaintiff Harry Cooper ("Plaintiff") responds to the Motion (Doc. 54) filed by '
        'the City of Pueblo and its officers (collectively, "Defendants"), and by the '
        'City (the “City”).'
    )
    assert _bodies(text) == []


def test_a_quoted_word_in_prose_is_still_a_quotation():
    text = 'The officer called it a "disagreement" in his report. Doc. No. 54 at 7.'
    assert _bodies(text) == ["disagreement"]


def test_a_bare_citation_is_not_a_quotation():
    assert _bodies('He was "(Doc. 42 at p. 12)." there.') == []
    assert _bodies('"Doc. No. 80 at 26; see also SAC ¶ 34"') == []


def test_a_quotation_that_mentions_a_document_survives():
    text = '"The Court should deny Doc. 54 in full." Doc. No. 61 at 3.'
    assert _bodies(text) == ["The Court should deny Doc. 54 in full."]


def test_defined_terms_do_not_attach_to_the_record():
    text = (
        'Plaintiff ("Plaintiff") opposes the Motion to Dismiss (collectively, '
        '"Defendants"). Doc. No. 54 at 1.'
    )
    (record,) = group_citations(text).as_dict()["records"]
    assert record["quotes"] == []


def test_docket_pin_written_with_a_page_abbreviation():
    (cite,) = extract_record_cites("See Doc. 42 at p. 12.")
    assert (cite.label, cite.pin) == ("42", "12")
    (cite,) = extract_record_cites("See ECF No. 42 at pp. 12-13.")
    assert (cite.label, cite.pin) == ("42", "12-13")


def test_page_marker_is_not_part_of_a_case_name():
    assert _trim_lead_in("P13 County of Sacramento") == "County of Sacramento"
    assert _trim_lead_in("County of Sacramento") == "County of Sacramento"
    assert _trim_lead_in("A12 Ashcroft") == "Ashcroft"


FOOTNOTE = (
    "The United States Supreme Court has said that the “conception defining the "
    "curtilage’ is … familiar\nenough that it is ‘easily understood from our "
    "daily experience.’” Florida v. Jardines, 569\nU.S. 1, 7 (2013) (quoting Oliver "
    "v. United States, 466 U.S. 170, 182, n. 12 (1984)."
)


def test_citation_broken_across_a_line_is_still_found():
    groups = {" ".join(g["header"]["text"].split()): g
              for g in group_citations(FOOTNOTE).as_dict()["groups"]}
    assert set(groups) == {"569 U.S. 1", "466 U.S. 170"}
    start = FOOTNOTE.index("569")
    assert tuple(groups["569 U.S. 1"]["header"]["span"]) == (start, start + 10)


def test_quote_goes_to_the_quoting_case_not_the_parenthetical():
    groups = {" ".join(g["header"]["text"].split()): g
              for g in group_citations(FOOTNOTE).as_dict()["groups"]}
    assert [q["text"][:10] for q in groups["569 U.S. 1"]["quotes"]] == ["conception"]
    assert groups["466 U.S. 170"]["quotes"] == []


# Filed in Coomer v. Lindell, No. 22-cv-01129 (D. Colo.), Doc. 283 at 3. The
# court found the Farmington quotation was invented; it must be checked against
# Farmington, not against Cerno, the next citation in the paragraph.
COOMER = (
    "the evidence must have “an undue tendency to suggest decision on an improper basis.” "
    "Fed. R. Evid. 403\nadvisory committee notes. See also Mata v. City of Farmington, 798 "
    "F.Supp.2d 1215, 1227 (D.N.M. 2011)\n\n(“The prejudice must be unfair in the sense that it "
    "would affect the jury's ability to weigh the evidence\n\nrationally.”) Rule 403 permits "
    "inclusion of evidence when the probative value is so crucial to a necessary\n\nissue that Mr. "
    "Coomer cannot show any prejudice “substantially outweighs” the probative value. See\n\n"
    "United States v. Cerno, 529 F.3d 926, 935 (10th Cir. 2008)."
)


def test_quote_in_a_parenthetical_belongs_to_that_citation():
    groups = {" ".join(g["header"]["text"].split()): g
              for g in group_citations(COOMER).as_dict()["groups"]}
    farmington = groups["798 F.Supp.2d 1215"]
    cerno = groups["529 F.3d 926"]
    assert [q["text"][:24] for q in farmington["quotes"]] == ["The prejudice must be un"]
    assert [q["text"] for q in cerno["quotes"]] == ["substantially outweighs"]


def test_parenthetical_lead_in_words_are_allowed():
    text = ('World Wide Ass’n v. Pure, Inc., 450 F.3d 1132, 1139 (2006) (recognizing that '
            '"reputation and character are inextricably intertwined" in defamation cases). '
            'New Mexico ex rel. Balderas v. Real Estate Law Center, P.C., 409 F.Supp.3d 1122 (2019).')
    groups = {" ".join(g["header"]["text"].split()): g for g in group_citations(text).as_dict()["groups"]}
    assert [q["text"][:10] for q in groups["450 F.3d 1132"]["quotes"]] == ["reputation"]
    assert groups["409 F.Supp.3d 1122"]["quotes"] == []


# Mata v. Avianca, No. 22-cv-1461 (S.D.N.Y.), ECF 21 at 3.
MATA = (
    "In the case of Ashcroft v. Iqbal, 556 U.S. 662 (2009), the Supreme Court held that when\n"
    "evaluating a motion to dismiss, the court must accept all well-pleaded factual allegations as\n"
    "true, but need not accept legal conclusions or \"threadbare recitals of the elements\" of a claim.\n"
    "The Court also held that the plaintiff must allege enough facts to state a plausible claim for\n"
    "relief, and that the court should consider all plausible interpretations of the complaint when\n"
    "making this determination.\n\n"
    "In Doe _v. United States, 419 F.3d 1058 (9th Cir. 2005), the Ninth Circuit held that the\n"
    "court must accept all well-pleaded factual allegations in the complaint as true."
)


def _quotes_by_cite(text):
    return {" ".join(g["header"]["text"].split()): [q["text"] for q in g["quotes"]]
            for g in group_citations(text).as_dict()["groups"]}


def test_quote_in_the_sentence_of_an_earlier_citation_stays_with_it():
    quotes = _quotes_by_cite(MATA)
    assert quotes["556 U.S. 662"] == ["threadbare recitals of the elements"]
    assert quotes["419 F.3d 1058"] == []


def test_a_citation_sentence_after_the_quote_still_takes_it():
    for text in (
        'Smith v. Jones, 1 U.S. 1 (1990), is often cited. Courts reject "bare labels." '
        "See Doe v. Roe, 2 U.S. 2 (1991).",
        'In Smith v. Jones, 1 U.S. 1 (1990), the court said "bare labels do not suffice." '
        "Doe v. Roe, 2 U.S. 2 (1991).",
        'In Smith v. Jones, 1 U.S. 1 (1990), the court said "bare labels do not suffice." '
        "See Doe v. Roe, 2 U.S. 2 (1991).",
    ):
        assert _quotes_by_cite(text)["2 U.S. 2"], text


def test_ocr_ordinal_in_a_neutral_citation_is_read():
    text = "In Shaboon v. Egyptair, 2013 IL App (Ist) 111279-U (Ill. App. Ct. 2013), the court held."
    (group,) = group_citations(text).as_dict()["groups"]
    start, end = group["header"]["span"]
    assert text[start:end] == "2013 IL App (Ist) 111279-U"


def test_citation_split_by_blank_lines_is_found_at_its_original_span():
    # Wadsworth v. Walmart, No. 23-cv-118 (D. Wyo.), ECF 141 at 11.
    text = ("In Woods v. BNSF Railway Co., 2016\n\n WL 165971 (D. Wyo. 2016), the court held that "
            "allowing a defendant to present evidence could skew the jury.")
    (group,) = group_citations(text).as_dict()["groups"]
    start, end = group["header"]["span"]
    assert text[start:end] == "2016\n\n WL 165971"
    assert (group["header"]["volume"], group["header"]["reporter"], group["header"]["page"]) == (
        "2016", "WL", "165971")
