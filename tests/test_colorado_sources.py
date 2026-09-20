"""The cloned Colorado source checks.

Everything here runs offline. The network functions are exercised by a
separate live check, not by the suite: a test that depends on a court website
being up is a test that fails for reasons that have nothing to do with this
code.

What is tested here is that the clone stands alone and that its pure helpers
and current Colorado search contract behave deterministically.
"""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caselaw.colorado import (
    ExtractedCitation,
    ProvisionResult,
    sources,
)
from caselaw.colorado.sources import (
    _colorado_neutral_key,
    _normalized_citation,
    _preserve_source,
    _subdivision_text,
)


class TestStandsAlone:
    def test_imports_nothing_from_the_original_project(self):
        """The clone must not reach back into the repository it came from."""
        text = Path(sources.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "from .citations",
            "from .federal_sources",
            "backend.app",
            "LEGAL CITATION VERIFICATION",
        ):
            assert forbidden not in text, f"still coupled: {forbidden}"

    def test_every_entry_point_is_present(self):
        for name in (
            "verify_colorado_case_search",
            "verify_colorado_court_of_appeals",
            "verify_colorado_supreme_court",
            "verify_crs",
            "verify_session_law",
        ):
            assert callable(getattr(sources, name))


class TestProvisionResult:
    def test_hashes_itself_when_no_bytes_were_fetched(self):
        assert ProvisionResult(found=False).response_sha256 is not None

    def test_keeps_a_supplied_digest(self):
        result = ProvisionResult(found=True, response_sha256="abc")
        assert result.response_sha256 == "abc"

    def test_same_content_hashes_the_same(self):
        a = ProvisionResult(found=True, source_url="u", text="t")
        b = ProvisionResult(found=True, source_url="u", text="t")
        assert a.response_sha256 == b.response_sha256

    def test_different_content_hashes_differently(self):
        a = ProvisionResult(found=True, text="one")
        b = ProvisionResult(found=True, text="two")
        assert a.response_sha256 != b.response_sha256

    def test_found_and_coverage_gap_are_distinct(self):
        """"Not found" and "this source does not cover it" are different
        answers and must not collapse."""
        missing = ProvisionResult(found=False)
        uncovered = ProvisionResult(found=False, coverage_gap=True)
        assert missing.coverage_gap is False
        assert uncovered.coverage_gap is True


class TestNeutralCitationKey:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2016 COA 134", "2016coa134"),
            ("2016COA134", "2016coa134"),
            ("16 COA 134", "2016coa134"),
            ("2019 CO 5", "2019co5"),
            ("2021 COA 77A", "2021coa77a"),
            ("  2016  coa  134 ", "2016coa134"),
        ],
    )
    def test_parses_colorado_neutral_citations(self, raw, expected):
        assert _colorado_neutral_key(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["782 P.2d 853", "410 U.S. 113", "", "Colo. App.", "2016 WL 1234"]
    )
    def test_rejects_anything_else(self, raw):
        assert _colorado_neutral_key(raw) is None


class TestNormalizedCitation:
    def test_strips_punctuation_and_case(self):
        assert _normalized_citation("782 P.2d 853") == "782p2d853"

    def test_two_spellings_of_one_citation_agree(self):
        assert _normalized_citation("579 P.3d 459") == _normalized_citation(
            "579 p. 3d. 459"
        )

    def test_different_citations_stay_different(self):
        """Series must not collapse: P.2d and P.3d are different reporters."""
        assert _normalized_citation("782 P.2d 853") != _normalized_citation(
            "782 P.3d 853"
        )


class TestColoradoCaseSearchRequest:
    def test_uses_the_public_webapp_search_mode_that_returns_ion_media(
        self, tmp_path
    ):
        """A cold JSON request searches only a small incomplete result set.

        The public website selects its complete search mode with the
        X-webapp-seed header.  Without it this exact query omits Ion Media,
        even though the rendered court search ranks the opinion first.
        """

        async def check() -> ProvisionResult:
            def respond(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/search.json":
                    results = []
                    if request.headers.get("X-webapp-seed"):
                        results = [
                            {
                                "id": 1105742207,
                                "title": "Ion Media Networks, Inc. v. W.",
                                "parent": {"title": "Colorado Court of Appeals"},
                                "snippet": (
                                    "<hi>576</hi> <hi>P</hi>.<hi>3d</hi> "
                                    "<hi>225</hi> 2025 COA 66"
                                ),
                                "properties": [
                                    {
                                        "property": {
                                            "id": "pCitations",
                                            "label": "Citations",
                                        },
                                        "values": [
                                            {"value": "576 P.3d 225"},
                                            {"value": "2025 COA 66"},
                                        ],
                                    }
                                ],
                            }
                        ]
                    return httpx.Response(
                        200, json={"count": len(results), "results": results}
                    )
                if request.url.path == "/vid/1105742207/content":
                    return httpx.Response(
                        200,
                        text=(
                            "<html><body>576 P.3d 225 2025 COA 66 "
                            "ION MEDIA NETWORKS, INC. v. WEST</body></html>"
                        ),
                    )
                raise AssertionError(f"unexpected request: {request.url}")

            citation = ExtractedCitation(
                text="576 P.3d 225",
                volume="576",
                reporter="P.3d",
                reporter_page="225",
                case_name="Ion Media Networks, Inc. v. West",
                year="2025",
            )
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond),
                base_url="https://research.coloradojudicial.gov",
            ) as client:
                return await sources.verify_colorado_case_search(
                    citation, client=client, opinions_dir=str(tmp_path)
                )

        result = asyncio.run(check())

        assert result.found is True
        assert result.source_identifier is not None
        assert "vid-1105742207" in result.source_identifier


class TestPreserveSource:
    def test_writes_the_bytes_under_their_own_hash(self, tmp_path):
        digest = _preserve_source(b"opinion text", tmp_path, "html")
        assert (tmp_path / f"{digest}.html").read_bytes() == b"opinion text"

    def test_is_idempotent(self, tmp_path):
        first = _preserve_source(b"same", tmp_path, "html")
        second = _preserve_source(b"same", tmp_path, "html")
        assert first == second
        assert len(list(tmp_path.iterdir())) == 1

    def test_refuses_a_corrupted_preserved_copy(self, tmp_path):
        """Chain of custody: if the stored bytes no longer hash to their own
        name, the copy is not evidence of anything."""
        digest = _preserve_source(b"original", tmp_path, "html")
        (tmp_path / f"{digest}.html").write_bytes(b"tampered")
        with pytest.raises(OSError):
            _preserve_source(b"original", tmp_path, "html")


class TestSubdivisionText:
    def test_narrows_to_the_cited_subsection(self):
        section = "18-1-704. (1) A person is justified. (2) Deadly force. (3) Other."
        assert "Deadly force" in _subdivision_text(section, "(2)")

    def test_missing_subsection_returns_none(self):
        assert _subdivision_text("18-1-704. (1) Only one.", "(4)") is None


class TestCitationAdapter:
    def test_adapts_this_repositorys_extraction_output(self):
        class Fake:
            kind = "FullCaseCitation"
            text = "782 P.2d 853"
            full_citation = "Whelden v. Board, 782 P.2d 853 (Colo. App. 1989)"
            span = (10, 22)
            volume = "782"
            reporter = "P.2d"
            page = "853"
            plaintiff = "Whelden"
            defendant = "Board of County Commissioners"
            year = 1989
            pin_cite = None

        adapted = ExtractedCitation.from_citation(Fake())
        assert adapted.volume == "782"
        assert adapted.reporter_page == "853", "page maps to reporter_page"
        assert adapted.year == "1989", "year becomes a string"
        assert adapted.case_name == "Whelden v. Board of County Commissioners"
        assert adapted.citation_kind == "full"

    def test_missing_fields_do_not_raise(self):
        class Bare:
            text = "something"

        adapted = ExtractedCitation.from_citation(Bare())
        assert adapted.text == "something"
        assert adapted.case_name is None
        assert adapted.year is None
