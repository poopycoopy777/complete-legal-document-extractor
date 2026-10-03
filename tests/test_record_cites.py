"""Record and document citations as attribution targets.

A brief quotes three kinds of thing: case law, the record in its own case, and
documentary evidence. Only the first is checkable against a corpus of opinions,
but all three get quoted, and the extractor previously bound every quotation to
the nearest *case* citation because that was the only kind it could see.

That produced confident nonsense. In the filed Third Amended Complaint, three
quotations from the Pueblo Police Department policy manual --

    Policy 1010.4.2 classifies allegations of "corruption, untruthfulness,
    brutality, misuse of force, breach of civil rights" as "Class I
    Allegations" that "will be investigated by the Internal Affairs Section"

-- were attributed to Pembaur v. City of Cincinnati and then reported as
quotations that do not appear in Pembaur. Correct answer, wrong question, and
the kind of false alarm that teaches a user to ignore the red flags.
"""

import pytest

from caselaw.record_cites import RecordCite, extract_record_cites


class TestDocketCitations:
    @pytest.mark.parametrize(
        "text,kind,label",
        [
            ("Doc. No. 80 at 26", "docket", "80"),
            ("Doc. 54 at 11-12", "docket", "54"),
            ("(Doc. No. 42 at 4-5)", "docket", "42"),
            ("ECF No. 61", "docket", "61"),
        ],
    )
    def test_docket_forms(self, text, kind, label):
        found = extract_record_cites(text)
        assert found, f"nothing found in {text!r}"
        assert found[0].kind == kind
        assert found[0].label == label

    def test_pin_page_is_captured(self):
        assert extract_record_cites("Doc. No. 80 at 26")[0].pin == "26"

    def test_page_range_is_kept_whole(self):
        # The quotation may sit on either page of the range.
        assert extract_record_cites("Doc. No. 80 at 17-18")[0].pin == "17-18"


class TestPleadingParagraphs:
    @pytest.mark.parametrize(
        "text,label,pin",
        [
            ("SAC ¶ 45", "SAC", "45"),
            ("SAC ¶¶ 65, 67, 69-70", "SAC", "65, 67, 69-70"),
            ("Compl. ¶ 12", "Complaint", "12"),
            ("TAC ¶ 101", "TAC", "101"),
        ],
    )
    def test_paragraph_forms(self, text, label, pin):
        # The pleading identifies the document; the paragraph is the pin.
        found = extract_record_cites(text)
        assert found and found[0].kind == "pleading"
        assert (found[0].label, found[0].pin) == (label, pin)

    def test_paragraphs_of_one_pleading_share_a_source(self):
        found = extract_record_cites("SAC ¶ 45; SAC ¶ 46")
        assert {c.source_id for c in found} == {"pleading:SAC"}


class TestPolicyCitations:
    @pytest.mark.parametrize(
        "text,label",
        [
            ("Policy 1010.4.2 classifies", "1010.4.2"),
            ("Policy 321.5.9(f)-(g) prohibits", "321.5.9"),
            ("PPD Policy 300.3", "300.3"),
        ],
    )
    def test_policy_forms(self, text, label):
        found = extract_record_cites(text)
        assert found and found[0].kind == "policy"
        assert found[0].label == label

    def test_the_tac_sentence_yields_the_policy_not_nothing(self):
        """The sentence that produced three false Pembaur attributions."""
        text = (
            'Policy 1010.4.2 classifies allegations of "corruption, untruthfulness, '
            'brutality, misuse of force, breach of civil rights" as "Class I Allegations" '
            'that "will be investigated by the Internal Affairs Section"'
        )
        found = extract_record_cites(text)
        assert [c.kind for c in found] == ["policy"]
        assert found[0].label == "1010.4.2"


class TestScopeDiscipline:
    def test_case_citations_are_not_record_cites(self):
        assert extract_record_cites("Pembaur v. City of Cincinnati, 475 U.S. 469 (1986)") == []

    def test_statutes_are_not_record_cites(self):
        assert extract_record_cites("42 U.S.C. § 1983") == []

    def test_rules_are_not_record_cites(self):
        assert extract_record_cites("Fed. R. Civ. P. 12(b)(6)") == []

    @pytest.mark.parametrize(
        "text",
        [
            # "Colo. App." is a reporter abbreviation, not a record appendix. The
            # extractor reported "App. 306" and "App. 2004" as record cites, so a
            # brief citing Sullivan v. Davis appeared to cite an appendix, and the
            # parallel reporter's volume became the appendix page.
            "Sullivan v. Davis, 39 Colo. App. 306, 571 P.2d 1103, 1105 (1977).",
            "E-470 Public Highway Auth. v. Revenig, 91 P.3d 1038, 1045 (Colo. App. 2004).",
            "See Colo. App. 306 for the parallel citation.",
        ],
    )
    def test_reporter_app_is_not_an_appendix_cite(self, text):
        assert [c.kind for c in extract_record_cites(text)] == []

    def test_a_real_appendix_cite_still_counts(self):
        found = extract_record_cites("As shown in App. 58, the record is thin.")
        assert [(c.kind, c.label, c.pin) for c in found] == [("appendix", "Appendix", "58")]

    def test_appellant_appendix_cite_still_counts(self):
        found = extract_record_cites("Appellant's App. 136-38 shows the objection.")
        assert [(c.kind, c.label, c.pin) for c in found] == [
            ("appendix", "Appendix", "136-38")]

    def test_other_state_appellate_reporters_are_not_appendices(self):
        for text in (
            "Smith v. Jones, 5 N.C. App. 12, 20 (1968).",
            "Doe v. Roe, 12 Ill. App. 3d 45, 50 (1973).",
            "Poe v. Coe, 300 So. 2d 1, 4 (Fla. Dist. Ct. App. 1974).",
        ):
            assert [c.kind for c in extract_record_cites(text)] == [], text

    def test_spans_are_reported(self):
        cite = extract_record_cites("As stated in Doc. No. 80 at 26, the court found")[0]
        assert cite.span[0] < cite.span[1]

    def test_multiple_cites_in_order(self):
        found = extract_record_cites("Doc. No. 80 at 17-18; see also SAC ¶ 45")
        assert [c.kind for c in found] == ["docket", "pleading"]

    def test_empty_text(self):
        assert extract_record_cites("") == []


def test_record_cite_is_immutable():
    cite = extract_record_cites("Doc. No. 80 at 26")[0]
    with pytest.raises(Exception):
        cite.label = "99"
    assert isinstance(cite, RecordCite)


class TestPageFurniture:
    """The ECF stamp names a document number on every page of a filing."""

    STAMP = "Case No. 1:25-cv-02263-RMR-MDB Document 84-1 filed 07/02/26 USDC Colorado pg 3 of 58"

    def test_ecf_stamp_is_not_a_record_cite(self):
        assert extract_record_cites(self.STAMP) == []

    def test_a_real_cite_beside_a_stamp_still_counts(self):
        text = self.STAMP + " As the Court found in Doc. No. 80 at 26, the record is thin."
        found = extract_record_cites(text)
        assert [c.source_id for c in found] == ["docket:80"]

    def test_stamp_repeated_across_pages_yields_nothing(self):
        assert extract_record_cites(" ".join([self.STAMP] * 12)) == []


def test_a_parenthetical_id_points_back_at_the_preceding_record_cite():
    text = "It is alleged. (Doc. No. 61 at 15.) More. (Id. at 25.) Again. (Id.)"
    cites = extract_record_cites(text)
    assert [(c.label, c.pin, c.text) for c in cites] == [
        ("61", "15", "Doc. No. 61 at 15"), ("61", "25", "Id. at 25"), ("61", None, "Id.")]


def test_a_parenthetical_id_with_no_record_cite_before_it_is_left_alone():
    assert extract_record_cites("Smith v. Jones, 1 F.3d 2 (1st Cir. 1990). (Id. at 3.)") == []

class TestStampsInsideARecordCiteSpan:
    """A pin read across a page break must still slice back to the document.

    The report the caller gets is the unmasked document, but record cites are
    matched against a working copy whose court stamps are blanked in place.
    "Doc. 54 ... at 4" with the stamp between the number and the pin therefore
    reported text its own span did not address, and the orchestrator refused the
    whole extraction: "record r0 citation span does not match text".
    """

    STAMP = "Case No. 1:25-cv-02263-RMR-MDB  Document 61    filed 10/13/25  USDC Colorado\npg 17 of 27"

    def _filing(self) -> str:
        return (
            'Counsel wrote "Officer Albaugh entered without a warrant." (Doc. 54\n'
            "\n\n                    16" + self.STAMP + "\n\n\n\nat 4). Yet on page 13, "
            "Doc. 42 at 7 says otherwise."
        )

    def test_every_record_cite_slices_back_out_of_the_unmasked_document(self):
        from caselaw.group import group_citations

        text = self._filing()
        extraction = group_citations(text)

        cites = [g.header for g in extraction.records] + [
            child for g in extraction.records for child in g.children
        ]
        assert cites, "the filing states two record citations"
        for cite in cites:
            assert text[cite.span[0]:cite.span[1]] == cite.text, (
                f"{cite.source_id} text does not match its own span"
            )

    def test_the_masked_copy_would_have_broken_it(self):
        """Guards the guard: if masking stopped mattering, this test is inert."""
        from caselaw.group import _mask_court_stamps

        text = self._filing()
        masked = _mask_court_stamps(text)
        assert masked != text, "the stamp must actually be blanked"
        assert len(masked) == len(text), "masking must preserve every offset"
        assert "USDC" not in masked and "USDC" in text

    def test_the_pin_across_the_break_still_reports_its_page(self):
        from caselaw.group import group_citations

        extraction = group_citations(self._filing())
        pins = [c.pin for g in extraction.records for c in (*([g.header] if g.header else []), *g.children)]
        assert "4" in pins
