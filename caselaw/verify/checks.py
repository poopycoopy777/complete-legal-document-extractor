"""The four deterministic identity checks.

A candidate is only `citation_verified` when all four pass. Nothing here is
fuzzy, and nothing repairs a damaged citation: correcting a garbled citation is
how a fabricated one gets laundered into a real-looking one.

Every check is a pure function over already-extracted values, so it is testable
without a database, a model or a network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..extract import extract_pairs

# Corporate suffixes carry no identifying information and appear
# inconsistently between a filing and a docket. Dropping them is safe;
# dropping anything else is not.
_SUFFIXES = re.compile(
    r"[,\s]+(inc|incorporated|llc|l\.l\.c|corp|corporation|co|company|ltd|"
    r"limited|lp|l\.p|llp|plc|pc|p\.c|n\.a|et\s+al)\.?$",
    re.IGNORECASE,
)

_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")

# A caption splits on "v." -- and on little else reliably.
_VERSUS = re.compile(r"\s+v[.s]?\.?\s+", re.IGNORECASE)

# Boilerplate openers on a non-adversarial caption. A brief and a docket
# spell these differently -- "In re Marriage of Rubio" against "In re the
# Marriage of Rubio" -- while the distinguishing part is the same, so the
# opener is stripped from both sides before they are compared.
_IN_RE_OPENER = re.compile(
    r"^(?:in\s+re:?(?:\s+the)?|in\s+the\s+matter\s+of|matter\s+of|ex\s+parte|"
    r"(?:people|state|commonwealth)\s+in\s+the\s+interest\s+of|"
    r"in\s+the\s+interest\s+of)\s*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    """One corpus row, reduced to the fields identity depends on."""

    cluster_id: int
    case_name: str
    court_id: str | None
    date_filed: str | None
    content: str

    @classmethod
    def from_row(cls, metadata: dict[str, Any], content: str) -> Candidate:
        return cls(
            cluster_id=metadata.get("cluster_id"),
            case_name=metadata.get("case_name") or "",
            court_id=metadata.get("court_id"),
            date_filed=str(metadata.get("date_filed") or "") or None,
            content=content or "",
        )


def normalize_party(value: str | None) -> str:
    """Case-fold, drop punctuation and corporate suffixes, collapse space.

    Deliberately not fuzzy. An OCR misread ("Coffinan" for "Coffman") must
    survive normalization as a difference, because check 2 failing is the only
    thing standing between a garbled name and a verified badge.
    """
    if not value:
        return ""
    text = value.strip()
    # "&" and "and" are written interchangeably in captions.
    text = re.sub(r"\s*&\s*", " and ", text)
    previous = None
    while previous != text:
        previous = text
        text = _SUFFIXES.sub("", text).strip()
    text = _PUNCT.sub("", text)
    return _SPACE.sub(" ", text).strip().casefold()


def split_caption(case_name: str) -> tuple[str, str] | None:
    """Split "A v. B" into its two sides, or None when it does not split."""
    if not case_name:
        return None
    parts = _VERSUS.split(case_name, maxsplit=1)
    if len(parts) != 2:
        return None
    left, right = parts[0].strip(), parts[1].strip()
    if not left or not right:
        return None
    return left, right


def check_reporter(
    volume: str | None,
    reporter: str | None,
    page: str | None,
    candidate: Candidate,
) -> bool:
    """Does the candidate carry this exact reporter citation?

    The candidate's citations exist only as text inside `content`, so they are
    read with the same reporters-db-backed extractor used on documents.

    Westlaw and LEXIS numbers are matched too. Both are in reporters-db as
    specialty cite types, both are real citation forms that appear in filings,
    and a Westlaw number is a unique identifier, so an exact match on one is
    strong evidence of identity. What the triple comparison prevents is the
    forms contaminating each other: a WL year can never satisfy a reporter
    volume.

    Volume and page compare as exact strings. A letter-for-digit misread ("3O"
    for "30") must fail rather than be coerced into matching.
    """
    if not (volume and reporter and page):
        return False
    wanted = (str(volume).strip(), _normalize_reporter(reporter), str(page).strip())
    for _, cite in extract_pairs(candidate.content):
        if cite.kind != "FullCaseCitation" or not cite.reporter:
            continue
        found = (
            str(cite.volume or "").strip(),
            _normalize_reporter(cite.reporter),
            str(cite.page or "").strip(),
        )
        if found == wanted:
            return True
    return False


def _normalize_reporter(reporter: str) -> str:
    """Whitespace and case only.

    Series must never collapse: F.2d, F.3d and F.4th are different reporters
    and a citation to one must not verify against another. Normalization is
    therefore kept deliberately weak.
    """
    return _SPACE.sub(" ", reporter.strip()).casefold()


def normalize_caption(value: str | None) -> str:
    """Normalize a non-adversarial caption for comparison.

    Strips the boilerplate opener and then applies the same conservative
    normalization the parties get. Still exact: only the opener and the
    punctuation are allowed to differ.
    """
    if not value:
        return ""
    return normalize_party(_IN_RE_OPENER.sub("", value.strip(), count=1))


def check_name(
    plaintiff: str | None,
    defendant: str | None,
    candidate: Candidate,
    case_name: str | None = None,
) -> bool:
    """Does the caption match the candidate's?

    Adversarial captions compare party by party, and order is significant:
    on appeal a caption genuinely reverses, and "A v. B" and "B v. A" can be
    different proceedings.

    A non-adversarial caption -- "In re Marriage of Rubio", "People in the
    Interest of C.A.G." -- has one party rather than two, so it is compared
    whole. Much precedent in domestic relations, dependency and probate is
    cited this way, and requiring two parties would refuse all of it.
    """
    if plaintiff and defendant:
        sides = split_caption(candidate.case_name)
        if sides is None:
            return False
        return (
            normalize_party(plaintiff) == normalize_party(sides[0])
            and normalize_party(defendant) == normalize_party(sides[1])
        )

    if case_name:
        # A candidate whose own caption splits on "v." is a different case,
        # not this one written differently.
        if split_caption(candidate.case_name) is not None:
            return False
        ours = normalize_caption(case_name)
        theirs = normalize_caption(candidate.case_name)
        return bool(ours) and ours == theirs

    return False


def check_year(year: int | None, candidate: Candidate) -> bool:
    """Exact equality with the filing year. No tolerance window.

    A window of plus or minus one admits the wrong case in a series of appeals
    between the same parties. A true citation excluded by strict comparison
    costs an abstention, which is free; a wrong case admitted by a loose one is
    a false green, which is not.
    """
    if not year or not candidate.date_filed:
        return False
    match = re.match(r"(\d{4})", candidate.date_filed)
    return bool(match) and int(match.group(1)) == int(year)


def check_court(court_id: str | None, candidate: Candidate) -> bool:
    """Compare courts-db identifiers.

    eyecite already resolves a citation's court parenthetical to a courts-db
    id, which is the same vocabulary the corpus stores. When either side is
    unresolved the check fails: an unresolvable court is not a matching court.
    """
    if not court_id or not candidate.court_id:
        return False
    return court_id.strip().casefold() == candidate.court_id.strip().casefold()
