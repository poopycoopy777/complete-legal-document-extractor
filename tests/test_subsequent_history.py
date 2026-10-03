"""Subsequent history belongs to the case it modifies, not to a new one.

A brief writes:

    People v. Hoff, 2016 CO 53, para. 16, 375 P.3d 1214, 1219, aff'd, 908 F.3d 1219

eyecite reads two full citations. The extractor merged the parallel-reporter
form ("First Nat'l Bank v. Conway, 34 Colo. 372, 83 P. 361") because the gap
between the halves was only a pin and a comma, but it did not merge history
forms, so the affirmance became a group of its own. That group carried no party
and no name, and the only caption before it in the document belonged to the case
it affirms -- so the report showed a case named after the wrong authority, which
is the failure mode the release checklist puts first: evidence attached to the
wrong authority.
"""

from __future__ import annotations

import pytest

from caselaw.group import group_citations


def _groups(text: str):
    return group_citations(text).as_dict()["groups"]


class TestSubsequentHistoryMerges:
    @pytest.mark.parametrize(
        "history",
        [
            "aff'd",
            "affirmed",
            "aff'd on other grounds",
            "rev'd",
            "cert. denied",
            "cert. granted",
            "appeal dismissed",
            "vacated",
            "overruled on other grounds",
        ],
    )
    def test_the_affirmance_joins_the_case_group(self, history):
        text = (f"People v. Hoff, 2016 CO 53, para. 16, 375 P.3d 1214, 1219, "
                f"{history}, 908 F.3d 1219, 1224 (10th Cir. 2018).")
        groups = _groups(text)
        assert len(groups) == 1, [(g["id"], g["caseName"], g["header"]["text"]) for g in groups]
        group = groups[0]
        assert group["caseName"] == "People v. Hoff"
        assert [c["text"] for c in (group["header"], *group["children"])] == [
            "2016 CO 53", "375 P.3d 1214", "908 F.3d 1219"]

    def test_the_history_citation_keeps_its_own_year_and_court(self):
        text = ("People v. Hoff, 2016 CO 53, para. 16, 375 P.3d 1214, 1219, "
                "aff'd, 908 F.3d 1219, 1224 (10th Cir. 2018).")
        (group,) = _groups(text)
        citations = [group["header"], *group["children"]]
        history = next(c for c in citations if c["text"] == "908 F.3d 1219")
        original = next(c for c in citations if c["text"] == "2016 CO 53")
        assert history["pin_cite"] == "1224"
        assert original["pin_cite"] is None

    def test_a_report_recommendation_adopted_merges(self):
        text = ("Sanchez v. City of Denver, 5 P.3d 1, 4 (Colo. App. 1999), "
                "report and recommendation adopted, 2013 WL 1658203, at *4 "
                "(D. Colo. Apr. 17, 2013).")
        groups = _groups(text)
        assert len(groups) == 1, [(g["id"], g["caseName"]) for g in groups]
        assert groups[0]["caseName"] == "Sanchez v. City of Denver"

    def test_a_star_pin_before_the_history_phrase_merges(self):
        """The real shape: the unreported pin carries its own parenthetical.

        The merge is what this asserts. Naming the group is a separate matter:
        this caption is "Case, No. CIV 16-0318 JB/SCY," rather than
        "A v. B,", so `_CASE_NAME` does not read it and the group stays unnamed.
        That limitation is recorded in the handoff rather than papered over.
        """
        text = ("A party argued the point. Rivero v. Bd. of Regents of Univ. of "
                "New Mexico, No. CIV 16-0318 JB\\SCY, 2019 WL 1085179, at *78 "
                "(D.N.M. Mar. 7, 2019), aff'd, 950 F.3d 754, 762 (10th Cir. 2020).")
        groups = _groups(text)
        assert len(groups) == 1, [(g["id"], g["caseName"], g["header"]["text"])
                                  for g in groups]
        assert [c["text"] for c in (groups[0]["header"], *groups[0]["children"])] == [
            "2019 WL 1085179", "950 F.3d 754"]

    def test_history_after_a_wrapped_line_still_merges(self):
        """PDF text layers break lines mid-citation; the gap must survive that."""
        text = ("Lot Thirty-Four Venture, L.L.C. v. Town of Telluride, 976 P.2d 303\n\n"
                "       (Colo. App. 1998), aff'd, 3 P.3d 30 (Colo. 1999).")
        groups = _groups(text)
        assert len(groups) == 1, [(g["id"], g["caseName"]) for g in groups]

    def test_a_parenthetical_comma_is_not_a_break(self):
        from caselaw.group import _is_subsequent_history

        assert _is_subsequent_history(", at *78 (D.N.M. Mar. 7, 2019), aff'd, ")

    def test_a_different_case_is_still_a_separate_group(self):
        """Guards the guard: history phrases must not merge unrelated cases."""
        text = ("People v. Hoff, 2016 CO 53, 375 P.3d 1214. "
                "Anderson v. Smith, 908 F.3d 1219 (10th Cir. 2018).")
        assert len(_groups(text)) == 2

    def test_a_parallel_reporter_still_merges(self):
        text = "First Nat'l Bank of Greeley v. Conway, 34 Colo. 372, 83 P. 361 (1905)"
        (group,) = _groups(text)
        assert [c["text"] for c in (group["header"], *group["children"])] == [
            "34 Colo. 372", "83 P. 361"]

    def test_two_cases_in_one_parenthetical_do_not_both_merge(self):
        text = ("Ashcroft v. Iqbal, 556 U.S. 662, 678 (2009) (quoting Bell Atlantic "
                "Corp. v. Twombly, 550 U.S. 544, 570 (2007)).")
        groups = _groups(text)
        names = {g["caseName"] for g in groups}
        assert "Ashcroft v. Iqbal" in names
        assert "Bell Atlantic Corp. v. Twombly" in names
        assert len(groups) == 2
