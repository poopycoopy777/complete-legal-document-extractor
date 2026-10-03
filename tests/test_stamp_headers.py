"""A filing-service stamp above a caption is layout, not a party.

"NOT A FILED PLEADING" is stamped across the top of proposed briefs, and it
sits on its own line directly above the first caption. Every word of it is
capitalised like a party, so the caption derivation read it in as the
plaintiff: "NOT A FILED PLEADING Monell v. Department of Social Services".
The assembled case name then carried the stamp into verification, where the
caption failed to match the real case and the monell-following-claim and
monell-bare-reference checks fired false alarms. Only a line that is nothing
but the stamp is stripped, so a party whose name contains the words is left
whole.
"""

from __future__ import annotations

from caselaw.group import group_citations


def _case_names(text: str) -> list[str]:
    return [group["caseName"] for group in group_citations(text).as_dict()["groups"]]


def _parties(text: str) -> list[tuple]:
    return [
        (group["header"].get("plaintiff"), group["header"].get("defendant"))
        for group in group_citations(text).as_dict()["groups"]
    ]


class TestStampHeaders:
    MONell = "Monell v. Department of Social Services, 436 U.S. 658 (1978)."

    def test_a_not_a_filed_pleading_stamp_is_not_a_party(self):
        (plaintiff, defendant), = _parties(f"NOT A FILED PLEADING\n\n{self.MONell}")
        assert plaintiff == "Monell"
        assert defendant == "Department of Social Services"

    def test_a_not_a_filed_pleading_stamp_stays_out_of_the_case_name(self):
        assert _case_names(f"NOT A FILED PLEADING\n\n{self.MONell}") == [
            "Monell v. Department of Social Services"
        ]

    def test_the_stamp_is_stripped_even_without_a_blank_line(self):
        assert _case_names(f"NOT A FILED PLEADING\n{self.MONell}") == [
            "Monell v. Department of Social Services"
        ]

    def test_the_stamp_is_stripped_with_its_trailing_period(self):
        assert _case_names(f"NOT A FILED PLEADING.\n\n{self.MONell}") == [
            "Monell v. Department of Social Services"
        ]

    def test_an_official_document_stamp_is_not_a_party(self):
        assert _case_names(f"NOT AN OFFICIAL COURT DOCUMENT\n\n{self.MONell}") == [
            "Monell v. Department of Social Services"
        ]

    def test_a_not_for_publication_stamp_is_not_a_party(self):
        assert _case_names(f"NOT FOR PUBLICATION\n\n{self.MONell}") == [
            "Monell v. Department of Social Services"
        ]

    def test_a_draft_stamp_is_not_a_party(self):
        assert _case_names(f"DRAFT\n\n{self.MONell}") == [
            "Monell v. Department of Social Services"
        ]

    def test_a_stamp_above_a_non_adversarial_caption_is_not_part_of_it(self):
        text = ("NOT A FILED PLEADING\n\n"
                "In re Marriage of Rubio, 313 P.3d 623 (Colo. App. 2011).")
        assert _case_names(text) == ["In re Marriage of Rubio"]

    def test_a_party_containing_the_words_is_left_whole(self):
        text = ("Not A Filed Pleading, Inc. v. Smith, 1 P.3d 1 (Colo. 2000).")
        (plaintiff, defendant), = _parties(text)
        assert plaintiff == "Not A Filed Pleading, Inc."
        assert defendant == "Smith"

    def test_the_stamp_words_inside_a_sentence_are_not_stripped(self):
        text = ("The clerk noted it was not a filed pleading. "
                "Monell v. Department of Social Services, 436 U.S. 658 (1978).")
        (plaintiff, defendant), = _parties(text)
        assert plaintiff == "Monell"
        assert defendant == "Department of Social Services"
