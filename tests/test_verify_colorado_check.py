"""The Colorado fallback stage.

Offline. The network path is exercised by hand against the live source; a test
that needs a court website to be up fails for reasons unrelated to this code.

What matters here is that the fallback is not a rubber stamp. It does not
trust the source's own "found" flag: the exact citation must appear in the
document that came back, and both parties must appear in its caption.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caselaw.verify.colorado_check import confirms, is_colorado
from caselaw.verify.service import GroupQuery

WHELDEN = GroupQuery(
    group_id="g0",
    volume="782",
    reporter="P.2d",
    page="853",
    plaintiff="Whelden",
    defendant="Board of County Commissioners",
    year=1989,
)

# Trimmed from the real response for 782 P.2d 853.
OPINION = (
    "Page 853 782 P.2d 853 Leroy WHELDEN and Pam Whelden ; Gerald Schreiber "
    "and Kay Schreiber , Plaintiffs-Appellants , v. BOARD OF COUNTY "
    "COMMISSIONERS OF the COUNTY OF ADAMS , Defendant-Appellee . "
    "Colorado Court of Appeals September 14, 1989 "
)


class Result:
    def __init__(self, found=True, text=OPINION, url="https://example", sha="abc"):
        self.found = found
        self.text = text
        self.source_url = url
        self.response_sha256 = sha


class TestIsColorado:
    @pytest.mark.parametrize(
        "court", ["colo", "coloctapp", "Colo.", "Colo. App.", "Colo.App."]
    )
    def test_colorado_courts_qualify(self, court):
        assert is_colorado(GroupQuery(group_id="g", court=court))

    def test_pacific_reporter_with_no_court_qualifies(self):
        """Worth one request: the court parenthetical is often missing, and a
        false positive costs a request while a false negative silently drops
        the case this source exists to reach."""
        assert is_colorado(
            GroupQuery(group_id="g", volume="782", reporter="P.2d", page="853")
        )

    @pytest.mark.parametrize("court", ["ca1", "scotus", "ca10", "nev"])
    def test_other_courts_do_not(self, court):
        assert not is_colorado(GroupQuery(group_id="g", court=court))

    def test_federal_reporter_does_not(self):
        assert not is_colorado(
            GroupQuery(group_id="g", volume="595", reporter="F.3d", page="50",
                       court="ca1")
        )


class TestConfirmsIsNotARubberStamp:
    def test_confirms_a_real_match(self):
        assert confirms(Result(), WHELDEN)

    def test_found_false_is_never_confirmed(self):
        assert not confirms(Result(found=False), WHELDEN)

    def test_found_true_without_the_citation_is_refused(self):
        """A search can match on a snippet and return a case that merely
        discusses the one being cited. The citation must be in the document."""
        text = OPINION.replace("782 P.2d 853", "999 P.2d 111")
        assert not confirms(Result(text=text), WHELDEN)

    def test_found_true_with_the_wrong_parties_is_refused(self):
        text = "Page 853 782 P.2d 853 Somebody Else v. Another Party ."
        assert not confirms(Result(text=text), WHELDEN)

    def test_empty_document_is_refused(self):
        assert not confirms(Result(text=""), WHELDEN)

    def test_missing_party_names_cannot_confirm(self):
        """Two cases in the sample brief extract with no party names. Without
        them the caption cannot be checked, so the case abstains."""
        bare = GroupQuery(
            group_id="g", volume="782", reporter="P.2d", page="853", year=1989
        )
        assert not confirms(Result(), bare)

    def test_wrong_reporter_series_is_refused(self):
        query = GroupQuery(
            group_id="g",
            volume="782",
            reporter="P.3d",
            page="853",
            plaintiff="Whelden",
            defendant="Board of County Commissioners",
            year=1989,
        )
        assert not confirms(Result(), query)

    def test_spacing_variation_still_matches(self):
        """Opinions render citations with inconsistent spacing."""
        assert confirms(Result(text=OPINION.replace("782 P.2d 853", "782 P.2d  853")), WHELDEN)

    def test_capitalised_caption_still_matches(self):
        """Opinion captions are frequently in capitals; the brief's short form
        is not. Surname anchors are compared case-insensitively."""
        assert confirms(Result(text=OPINION.upper()), WHELDEN)


class TestOutageIsSilent:
    def test_a_result_of_none_confirms_nothing(self):
        assert not confirms(None, WHELDEN)

    def test_no_colorado_citations_makes_no_requests(self, monkeypatch):
        from caselaw.verify import colorado_check

        def explode(*args, **kwargs):
            raise AssertionError("should not have called the network")

        monkeypatch.setattr(colorado_check, "_check_all", explode)
        federal = GroupQuery(
            group_id="g", volume="595", reporter="F.3d", page="50", court="ca1"
        )
        assert colorado_check.verify_colorado([federal]) == {}


class TestEligibilityRegressions:
    """Two ways a Colorado case was silently skipped."""

    def test_reporter_with_a_trailing_period_still_qualifies(self):
        """A brief wrote "313 P.3d. 623". The extra period is a typo, not a
        different reporter, and it must not decide whether the case is
        checked at all."""
        assert is_colorado(
            GroupQuery(group_id="g", volume="313", reporter="P.3d.", page="623")
        )

    @pytest.mark.parametrize(
        "court_text", ["Colo.App.", "Colo. App.", "Colo.", "Colo. Ct. App."]
    )
    def test_court_text_alone_qualifies(self, court_text):
        """eyecite resolves "Colo." to a court id but not "Colo. App.", so
        court_text is often the only evidence of the court. It has to reach
        this check, which means the caller has to send it."""
        assert is_colorado(
            GroupQuery(
                group_id="g",
                volume="1",
                reporter="P.3d",
                page="2",
                court_text=court_text,
            )
        )

    def test_court_text_survives_from_dict(self):
        query = GroupQuery.from_dict(
            {"groupId": "g", "volume": "1", "reporter": "P.3d", "page": "2",
             "courtText": "Colo.App."}
        )
        assert query.court_text == "Colo.App."
        assert is_colorado(query)

    def test_a_non_colorado_pacific_case_is_still_skipped(self):
        """The Pacific Reporter covers many states. A Nevada case must not be
        sent to a Colorado court."""
        assert not is_colorado(
            GroupQuery(
                group_id="g",
                volume="1",
                reporter="P.3d",
                page="2",
                court_text="Nev.",
            )
        )
