"""Types the Colorado source checks depend on.

Cloned from the legal-citation-verification-system project so this package
stands alone. Nothing here imports from that repository, and nothing in it
needs to be installed for this one to run.

`ProvisionResult` keeps the original field names and the hashing behaviour in
__post_init__ exactly, because the Colorado functions construct it in a dozen
places and any drift would silently change what a result means.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class ProvisionResult:
    """The outcome of checking one citation against one official source.

    `found` means the source confirmed the citation. `base_found` means the
    document was retrieved but the specific provision or citation was not
    confirmed in it. `coverage_gap` means the source does not cover this
    citation at all, which is different from the source saying no.

    `response_sha256` is chain of custody: it hashes the bytes that were
    actually served, or, when no bytes were fetched, the result itself.
    """

    found: bool
    base_found: bool = False
    coverage_gap: bool = False
    source_url: str | None = None
    version: str | None = None
    version_effective_date: str | None = None
    text: str | None = None
    source_identifier: str | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    response_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.response_sha256 is not None:
            return
        payload = json.dumps(
            {
                "found": self.found,
                "base_found": self.base_found,
                "coverage_gap": self.coverage_gap,
                "source_url": self.source_url,
                "version": self.version,
                "version_effective_date": self.version_effective_date,
                "text": self.text,
                "source_identifier": self.source_identifier,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        object.__setattr__(
            self, "response_sha256", hashlib.sha256(payload).hexdigest()
        )


@dataclass
class ExtractedCitation:
    """What the Colorado checks need to know about one citation.

    The field names are the originals, so the cloned source functions read
    unchanged. `from_citation` adapts this repository's own extraction output,
    which names the same things differently: `page` rather than
    `reporter_page`, and an int year rather than a string.
    """

    text: str
    index: int = 0
    start: int = 0
    end: int = 0
    page: int = 0
    preceding_quote: str | None = None
    authority_type: str = "case"
    title: str | None = None
    section: str | None = None
    subsection: str | None = None
    citation_kind: str = "full"
    volume: str | None = None
    reporter: str | None = None
    reporter_page: str | None = None
    resolved_text: str | None = None
    resolved_index: int | None = None
    resolution_method: str | None = None
    antecedent: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    year: str | None = None
    case_name: str | None = None
    pin_cite: str | None = None
    is_toa_index: bool = False

    @classmethod
    def from_citation(cls, citation: object) -> ExtractedCitation:
        """Adapt a caselaw.extract.Citation without importing it.

        Kept duck-typed so this package has no dependency on the extraction
        module, and so a plain object with the same attributes works in tests.
        """
        get = lambda name: getattr(citation, name, None)
        plaintiff, defendant = get("plaintiff"), get("defendant")
        case_name = f"{plaintiff} v. {defendant}" if plaintiff and defendant else None
        year = get("year")
        span = get("span") or (0, 0)
        return cls(
            text=get("full_citation") or get("text") or "",
            start=span[0],
            end=span[1],
            volume=get("volume"),
            reporter=get("reporter"),
            reporter_page=get("page"),
            plaintiff=plaintiff,
            defendant=defendant,
            case_name=case_name,
            year=str(year) if year is not None else None,
            pin_cite=get("pin_cite"),
            citation_kind="full" if get("kind") == "FullCaseCitation" else "short",
        )
