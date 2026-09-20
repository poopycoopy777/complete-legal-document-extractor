"""Second source for Colorado cases: the courts' own case-law search.

The corpus cannot verify a large share of Colorado appellate work, and the
reason is structural rather than a bug. A CourtListener row stores whatever
citations were in its content field, and for roughly a third of Colorado Court
of Appeals cases that does not include the regional reporter. Whelden is in the
corpus as "13 Brief Times Rptr. 1051, 1989 Colo. App. LEXIS 271, 1989 WL
106150" -- no P.2d anywhere -- so `782 P.2d 853`, which is how a brief actually
cites it, can never match.

The official source knows the reporter citation, so it closes that gap.

The contract is unchanged: positive-only. This stage either confirms a citation
or says nothing about it. A source that is down, slow or unreachable produces
no result rather than an adverse one, because "the court website timed out" is
not evidence about a citation.
"""

from __future__ import annotations

import asyncio
import re

from ..colorado.sources import verify_colorado_case_search
from ..colorado.types import ExtractedCitation
from .checks import _PUNCT, normalize_caption, normalize_party, split_caption
from .service import GroupQuery

# Colorado reporters and court parentheticals. A citation that looks like
# neither is not worth a request to a Colorado court.
_COLORADO_COURT = re.compile(r"\bColo\b", re.IGNORECASE)
# A brief may write "P.3d." with a trailing period. That is a typo, not a
# different reporter, and it must not decide whether the case is checked.
_PACIFIC = re.compile(r"^P\.\s?[23]d\.?$|^P\.$", re.IGNORECASE)
_APPEALS_HEADING = re.compile(
    r"(?:colorado court of appeals|court of appeals of colorado)", re.IGNORECASE
)
_SUPREME_HEADING = re.compile(
    r"(?:colorado supreme court|supreme court of colorado)", re.IGNORECASE
)

# One request per citation against someone else's server. Kept small so a
# document with many Colorado cites cannot turn into a burst of traffic.
DEFAULT_CONCURRENCY = 3


def is_colorado(query: GroupQuery, court_text: str | None = None) -> bool:
    """Is this citation plausibly a Colorado case?

    Deliberately broad: a false positive costs one wasted request, while a
    false negative silently drops the case this source exists to reach. The
    Pacific Reporter covers many states, so the court parenthetical decides
    when it is present.
    """
    haystack = " ".join(
        filter(None, [query.court, court_text, getattr(query, "court_text", None)])
    )
    if _COLORADO_COURT.search(haystack):
        return True
    if query.court and query.court.strip().casefold().startswith("colo"):
        return True
    # No court at all, but a Pacific Reporter cite: worth asking.
    return not haystack.strip() and bool(
        query.reporter and _PACIFIC.match(query.reporter.strip())
    )


def _citation_present(text: str, query: GroupQuery) -> bool:
    """Does the retrieved opinion actually carry this exact citation?

    `found` from the source is not taken on trust. The volume, reporter and
    page must appear together in the document that came back, with flexible
    spacing only.
    """
    if not (query.volume and query.reporter and query.page):
        return False
    # A brief may write "P.3d." with a trailing period. Matching the document
    # against the typo verbatim rejects the correct opinion. The series itself
    # is untouched: "P.2d" and "P.3d" stay different reporters.
    reporter = query.reporter.strip().rstrip(".")
    if not reporter:
        return False
    pattern = (
        re.escape(query.volume)
        + r"\s*"
        + re.escape(reporter).replace(r"\ ", r"\s*")
        + r"\.?\s*"
        + re.escape(query.page)
    )
    return re.search(pattern, text, re.IGNORECASE) is not None


def _parties_present(text: str, query: GroupQuery) -> bool:
    """Do both party names appear in the opinion?

    Compared against the head of the document, which is the caption. Surnames
    only: an opinion caption spells parties out in full and often in capitals,
    so requiring the brief's short form to match exactly would reject correct
    opinions. Both sides are still required.
    """
    head = " ".join(text[:3000].split()).casefold()
    # Punctuation-free view of the same caption. A juvenile caption prints
    # initials as "C.A.G."; normalized it is "cag", which does not appear in
    # the raw head at all.
    flat = _PUNCT.sub("", head)
    flat = re.sub(r"\s+", " ", flat)

    if not (query.plaintiff and query.defendant):
        # Non-adversarial caption: one name, so the distinguishing part has to
        # appear in the opinion's own caption. "In re Marriage of Rubio" is
        # confirmed by "Rubio", not by "Marriage".
        if not query.case_name:
            return False
        normalized = normalize_caption(query.case_name)
        if not normalized:
            return False
        # Initials are short: "cag" is three characters and is still the whole
        # identifying part of the caption. Long enough to be meaningful here
        # because the exact reporter citation has already pinned the case.
        words = [w for w in normalized.split() if len(w) > 3]
        anchor = words[-1] if words else normalized.split()[-1]
        return len(anchor) >= 2 and (anchor in head or anchor in flat)

    for party in (query.plaintiff, query.defendant):
        normalized = normalize_party(party)
        if not normalized:
            return False
        words = [w for w in normalized.split() if len(w) > 3]
        anchor = words[-1] if words else normalized
        if anchor not in head:
            return False
    return True


def _year_present(text: str, query: GroupQuery) -> bool:
    """Require the extracted filing year in the opinion's own header."""
    if query.year is None:
        return False
    head = " ".join(text[:3000].split())
    return re.search(rf"(?<!\d){int(query.year)}(?!\d)", head) is not None


def _query_court_kind(query: GroupQuery) -> str | None:
    kinds: set[str] = set()
    for value in (query.court, query.court_text):
        if not value:
            continue
        normalized = re.sub(r"[^a-z]", "", value.casefold())
        if (
            "courtofappeals" in normalized
            or "ctapp" in normalized
            or "coloapp" in normalized
        ):
            kinds.add("appeals")
        elif normalized in {"colo", "colorado"} or "supremecourt" in normalized:
            kinds.add("supreme")
    return next(iter(kinds)) if len(kinds) == 1 else None


def _court_present(text: str, query: GroupQuery) -> bool:
    """Match the extracted court to the earliest court heading in the source."""
    expected = _query_court_kind(query)
    if expected is None:
        return False
    head = " ".join(text[:3000].split())
    positions = {
        "appeals": (
            match.start() if (match := _APPEALS_HEADING.search(head)) else None
        ),
        "supreme": (
            match.start() if (match := _SUPREME_HEADING.search(head)) else None
        ),
    }
    present = {
        kind: position
        for kind, position in positions.items()
        if position is not None
    }
    if not present:
        return False
    actual = min(present, key=present.__getitem__)
    return actual == expected


def confirms(result: object, query: GroupQuery) -> bool:
    """Does this source result establish the citation's identity?

    The source must say found, and the returned opinion itself must confirm
    the exact citation, caption, filing year, and court. These are checked
    here rather than trusted from the search, because a search that matches on
    a snippet can return a case that merely discusses the one being cited.
    """
    if not getattr(result, "found", False):
        return False
    text = getattr(result, "text", None) or ""
    if not text:
        return False
    return (
        _citation_present(text, query)
        and _parties_present(text, query)
        and _year_present(text, query)
        and _court_present(text, query)
    )


async def _check_one(query: GroupQuery, client, semaphore) -> tuple[str, object | None]:
    citation = ExtractedCitation(
        text=f"{query.volume} {query.reporter} {query.page}",
        volume=query.volume,
        reporter=query.reporter,
        reporter_page=query.page,
        plaintiff=query.plaintiff,
        defendant=query.defendant,
        case_name=(
            f"{query.plaintiff} v. {query.defendant}"
            if query.plaintiff and query.defendant
            else None
        ),
        year=str(query.year) if query.year else None,
    )
    if query.case_name and not citation.case_name:
        citation.case_name = query.case_name
    async with semaphore:
        try:
            result = await verify_colorado_case_search(citation, client=client)
        except Exception:  # noqa: BLE001
            # An unreachable court website is not evidence about a citation.
            return query.group_id, None
    return query.group_id, result


async def _check_all(
    queries: list[GroupQuery], concurrency: int
) -> dict[str, object | None]:
    import httpx

    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        pairs = await asyncio.gather(
            *(_check_one(q, client, semaphore) for q in queries)
        )
    return dict(pairs)


def verify_colorado(
    queries: list[GroupQuery], concurrency: int = DEFAULT_CONCURRENCY
) -> dict[str, dict]:
    """Confirm what the official Colorado source can confirm.

    Returns one entry per confirmed citation and nothing for the rest. Never
    raises: this is a supplementary source, so its failure must not turn a
    working verification request into an error.
    """
    colorado = [q for q in queries if is_colorado(q) and q.is_queryable]
    if not colorado:
        return {}
    try:
        results = asyncio.run(_check_all(colorado, concurrency))
    except Exception:  # noqa: BLE001
        return {}

    confirmed: dict[str, dict] = {}
    for query in colorado:
        result = results.get(query.group_id)
        if result is None or not confirms(result, query):
            continue
        confirmed[query.group_id] = {
            "groupId": query.group_id,
            "status": "citation_verified",
            "clusterId": None,
            "source": "colorado_judicial",
            "sourceUrl": getattr(result, "source_url", None),
            "responseSha256": getattr(result, "response_sha256", None),
            "checks": {
                "reporterCitation": True,
                "caseName": True,
                "year": True,
                "court": True,
            },
        }
    return confirmed


def case_name_of(query: GroupQuery) -> str | None:
    """Convenience for callers that log what was checked."""
    sides = split_caption(f"{query.plaintiff} v. {query.defendant}")
    return f"{sides[0]} v. {sides[1]}" if sides else None
