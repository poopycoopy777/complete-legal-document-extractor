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


def test_district_court_abbreviations_are_not_reported_as_mismatches():
    from caselaw.extract import _court_hint_matches

    for hint, court in (("D. Colo.", "cod"), ("E.D. Ky.", "kyed"), ("S.D.N.Y.", "nysd"),
                        ("D.N.M.", "nmd"), ("10th Cir.", "ca10"), ("Tex. App. Sept. 25,", "texapp")):
        assert _court_hint_matches(hint, court), hint
    assert not _court_hint_matches("E.D. Ky.", "cod")
    assert not _court_hint_matches("10th Cir.", "ca4")


def test_case_name_does_not_run_across_a_sentence_end():
    # Coomer v. Lindell, Doc. 283 at 7.
    text = ("The Tenth Circuit has specifically addressed authentication and admissibility of social media "
            "evidence in United States v. Hassan, holding that social media posts are admissible when "
            "adequately authenticated and relevant to material issues. Hassan, 742 F.3d 104, 133 "
            "(10th Cir. 2014).")
    (group,) = group_citations(text).as_dict()["groups"]
    name = group["header"]["full_citation"] or ""
    assert "holding" not in name and "social media" not in name, name


def test_captions_with_lower_case_abbreviations_survive():
    text = ("New Mexico ex rel. Balderas v. Real Estate Law Center, P.C., 409 F. Supp. 3d 1122 (D.N.M. 2019). "
            "Smith et al. v. Jones Co., 1 F.3d 1 (10th Cir. 1993).")
    names = [g["header"]["full_citation"] for g in group_citations(text).as_dict()["groups"]]
    # "ex rel." and "et al." are not sentence ends, and "ex rel." is part of the caption.
    assert names[0].startswith("New Mexico ex rel. Balderas v. Real Estate Law Center, P.C."), names
    assert names[1] == "1 F.3d 1 (10th Cir. 1993)", names


def _group(result, name):
    return next(g for g in result["groups"] if name in (g["caseName"] or ""))


def test_id_after_a_quoting_parenthetical_refers_to_the_cited_case():
    text = (
        'A complaint need only contain "sufficient factual matter, accepted as true, to state '
        'a claim to relief that is plausible on its face." Ashcroft v. Iqbal, 556 U.S. 662, '
        "678 (2009) (quoting Bell Atlantic Corp. v. Twombly, 550 U.S. 544, 570 (2007)). The "
        'standard asks for "more than a sheer possibility that a defendant has acted '
        'unlawfully." Id. The inquiry is a "context-specific task." Id. at 679.'
    )
    result = group_citations(text).as_dict()
    iqbal = _group(result, "Iqbal")
    assert [(q["text"][:9], q["pin_cite"]) for q in iqbal["quotes"]] == [
        ("sufficien", "678"), ("more than", "678"), ("context-s", "679")]
    assert [q["pin_basis"] for q in iqbal["quotes"]][1] == "inherited_from_id"
    assert _group(result, "Twombly")["quotes"] == []


def test_a_quote_two_argument_sentences_before_a_citation_is_not_its():
    text = (
        'Their logic is perverse: "It is lawful to besiege a home without probable cause." '
        "This makes their conduct worse, not better. The admission proves they knew. Under "
        "Holland ex rel. Overdorff v. Harrington, 268 F.3d 1179 (10th Cir. 2001), threats "
        "can be excessive force."
    )
    result = group_citations(text).as_dict()
    assert all(not g["quotes"] for g in result["groups"])
    assert [q["text"][:8] for q in result["unattributedQuotes"]] == ["It is la"]


def test_capitalised_record_words_are_not_quotations():
    text = (
        'Internal Affairs closed every allegation as "EXONERATED" or "UNFOUNDED", '
        'past a sign reading "NO TRESPASSING." Pembaur v. City of Cincinnati, 475 U.S. 469 '
        '(1986). The "very core" of the Fourth Amendment is the home.'
    )
    assert _bodies(text) == ["very core"]


def test_table_of_authorities_heading_after_a_page_stamp_is_not_a_party():
    assert _trim_lead_in("pg 2 of 27 TABLE OF AUTHORITIES Cases Ashcroft") == "Ashcroft"


def test_a_parallel_citation_is_one_case_not_two_half_cards():
    text = ("It so held. First Nat'l Bank of Greeley v. Conway, 34 Colo. 372, 375, 83 P. 361, "
            "362 (1905). Later: Conway, 83 P. at 363.")
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["caseName"] == "First Nat'l Bank of Greeley v. Conway"
    assert group["header"]["year"] == 1905
    assert [(c["text"], c["pin_cite"]) for c in group["children"]] == [
        ("83 P. 361", "362"), ("83 P. at 363", "363")]


def test_a_non_adversarial_caption_names_its_card():
    text = "It exempts no one. In re Veal, 450 B.R. 897, 917-18 (9th Cir. BAP 2011)."
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["caseName"] == "In re Veal"


def test_a_regional_reporter_takes_its_court_from_the_parenthetical():
    from caselaw.extract import extract

    (cite,) = extract("It held. Reagan v. Investors Mtg. Co., 977 P.2d 299 (Colo. App. 1999).")
    assert (cite.court, cite.flags) == ("coloctapp", [])


def test_ex_rel_stays_in_the_caption_and_the_proposition_is_found():
    text = ('A court may grant declaratory relief to "settle rights where clarity of ownership is '
            'essential." People ex rel. State Bd. of Equalization v. Hively, 336 P.2d 721 (1959).')
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["caseName"] == "People ex rel. State Bd. of Equalization v. Hively"
    assert group["proposition"].startswith("A court may grant declaratory relief")


def test_a_case_first_cited_by_short_name_takes_its_caption_from_a_later_cite():
    text = ("It addressed authentication. Hassan, 742 F.3d 104, 133 (10th Cir. 2014). Later: See "
            "United States v. Hassan, 742 F.3d 104, 133 (10th Cir. 2014) (discussing methods).")
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["caseName"] == "United States v. Hassan"


def test_an_ecf_page_stamp_is_not_part_of_the_caption():
    text = ("Filed 11/14/25   Page 6 of 33\n        PageID.1994\n\n\nMendocino Envtl. Ctr. v. "
            "Mendocino Cnty.\n     192 F.3d 1283 (9th Cir. 1999) ........ 9\n")
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["caseName"] == "Mendocino Envtl. Ctr. v. Mendocino Cnty."


def test_an_en_dash_in_a_party_name_is_kept():
    text = "It so held. Daniels–Hall v. Nat’l Educ. Ass’n, 629 F.3d 992, 998 (9th Cir. 2010)."
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["caseName"] == "Daniels–Hall v. Nat’l Educ. Ass’n"


def test_an_ocr_underscore_before_v_does_not_lose_the_caption():
    text = "It so held. In Doe _v. United States, 419 F.3d 1058 (9th Cir. 2005), the court held."
    (group,) = group_citations(text).as_dict()["groups"]
    assert group["caseName"] == "Doe v. United States"
