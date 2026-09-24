"""Quotations from the case record must bind to the record, not to case law.

The passage is from a filed objection. eyecite resolves each Id. to the last
case it saw (Browder), so three quotations from the Magistrate Judge's
Recommendation were verified against Browder and reported as missing from it.
"""

from __future__ import annotations

from caselaw.group import group_citations

PASSAGE = (
    "The Tenth Circuit has said as much. Browder v. City of Albuquerque, 787 F.3d 1076, "
    "1082 (10th Cir. 2015). The Recommendation expressly acknowledged that the SAC left "
    "the operational context of the encounter \u201cunclear at best.\u201d Doc. No. 80 at 26. "
    "It further stated that \u201cthe SAC does not describe why the officers went to "
    "Plaintiff\u2019s door.\u201d Id. But the Recommendation credited an inference that the "
    "encounter was merely a \u201cdisagreement between the officers and Plaintiff\u2019s "
    "father\u201d regarding bar security footage. Id. at 25\u201326. The SAC alleged that "
    "officers were \u201cactively getting ready to come to the location.\u201d SAC \u00b6 34; "
    "see also SAC \u00b6 41."
)


def _extract():
    return group_citations(PASSAGE).as_dict()


def test_record_quotations_leave_the_case_group():
    extraction = _extract()
    (browder,) = extraction["groups"]
    assert browder["quotes"] == []
    assert browder["children"] == []


def test_each_record_document_is_its_own_source():
    records = {r["sourceId"]: r for r in _extract()["records"]}
    assert set(records) == {"docket:80", "pleading:SAC"}
    doc80 = records["docket:80"]
    assert [c["text"] for c in (doc80["header"], *doc80["children"])] == [
        "Doc. No. 80 at 26", "Id.", "Id."]
    assert [q["text"] for q in doc80["quotes"]] == [
        "unclear at best.",
        "the SAC does not describe why the officers went to Plaintiff\u2019s door.",
        "disagreement between the officers and Plaintiff\u2019s father",
    ]
    sac = records["pleading:SAC"]
    assert [c["pin_cite"] for c in (sac["header"], *sac["children"])] == ["34", "41"]


def test_record_pins_follow_bluebook_id_rules():
    doc80 = next(r for r in _extract()["records"] if r["sourceId"] == "docket:80")
    assert [(q["pin_cite"], q["pin_basis"]) for q in doc80["quotes"]] == [
        ("26", "printed"),
        ("26", "inherited_from_id"),  # bare Id. repeats the previous page
        ("25–26", "printed"),     # "Id. at 25-26" keeps its range
    ]


def test_record_quotes_name_their_occurrence_and_slice_back():
    for record in _extract()["records"]:
        spans = {tuple(c["span"]) for c in (record["header"], *record["children"])}
        for quote in record["quotes"]:
            assert PASSAGE[quote["span"][0]:quote["span"][1]] == quote["raw_text"]
            assert tuple(quote["citation_span"]) in spans
        for occurrence in record["occurrencePropositions"]:
            if occurrence["proposition"]:
                start, end = occurrence["propositionSpan"]
                assert PASSAGE[start:end] == occurrence["proposition"]


def test_an_id_after_case_law_stays_with_the_case():
    text = ("Officers may knock. Browder v. City of Albuquerque, 787 F.3d 1076, 1082 "
            "(10th Cir. 2015). They may not linger. Id. at 1083. See Doc. No. 80 at 26.")
    extraction = group_citations(text).as_dict()
    (browder,) = extraction["groups"]
    assert [c["kind"] for c in browder["children"]] == ["IdCitation"]
    (record,) = extraction["records"]
    assert record["children"] == []


def test_a_parenthetical_id_after_a_quote_sends_it_to_the_record_not_the_named_case():
    # Cooper v. City of Pueblo, Doc. 80: the court quotes the plaintiff's brief.
    text = ("Plaintiff argues the search was unlawful. (Doc. No. 61 at 15.) Plaintiff asserts that in "
            "United States v. Reeves, 524 F.3d 1161 (10th Cir. 2008), the court found “a Fourth "
            "Amendment violation where officers entered a locked, shared breezeway.” (Id. at 25.) "
            "But Reeves involved a motel room.")
    result = group_citations(text)
    reeves = next(g for g in result.groups if "Reeves" in (g.case_name or ""))
    assert not any("breezeway" in q.text for q in reeves.quotes)
    record = next(r for r in result.records if r.label == "61")
    assert any("breezeway" in q.text for q in record.quotes)
    assert [c.pin for c in record.children] == ["25"]


def test_a_word_quoted_from_the_record_and_echoed_later_stays_with_the_record():
    text = ("Plaintiff claims the “siege” of his apartment was retaliation. (Doc. No. 42 at 32.) "
            "He has not alleged that the “siege” was motivated by speech. “Mere allegations "
            "will not suffice.” Frazer v. Dubois, 922 F.2d 560, 562 (10th Cir. 1990).")
    result = group_citations(text)
    frazer = next(g for g in result.groups if "Frazer" in (g.case_name or ""))
    assert [q.text for q in frazer.quotes] == ["Mere allegations will not suffice."]


def test_a_quote_of_what_a_party_alleges_does_not_attach_to_the_case_before_it():
    text = ("A pattern is ordinarily necessary. Connick v. Thompson, 563 U.S. 51, 61 (2011). "
            "Finally, Plaintiff’s allegation that the City “divert[s]” investigations "
            "is under-alleged.")
    result = group_citations(text)
    connick = next(g for g in result.groups if "Connick" in (g.case_name or ""))
    assert connick.quotes == []


def test_a_case_cited_only_in_short_form_gets_its_own_group_and_its_ids():
    text = ("A person may revoke the implied license. See Carloss, 818 F.3d at 994-95. "
            "The occupant may decline to open the door. Carloss, 818 F.3d at 992. "
            "Officers must leave. Id. at 998.")
    result = group_citations(text)
    carloss = next(g for g in result.groups if g.case_name == "Carloss")
    assert len((carloss.header, *carloss.children)) == 3
    assert not result.orphans
