"""Case law citation extraction.

eyecite is trusted for DETECTION (reporter/volume/page/span) — that is the hard
part and it is backed by reporters-db. Its metadata is NOT trusted: the backward
case-name scan in eyecite >=2.7.0 (helpers._scan_for_case_boundaries) walks up to
BACKWARD_SEEK=28 words and does not stop at a sentence-ending period, so it reads
the PRIOR citation's year parenthetical and party names. See tests/test_extract.py
for the reproductions.

Metadata is therefore re-derived from windows bounded by adjacent citation spans,
which cannot cross a citation boundary by construction. Every disagreement with
eyecite is recorded in Citation.flags rather than silently resolved.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from eyecite import get_citations
from eyecite.models import (
    FullCaseCitation,
    IdCitation,
    ReferenceCitation,
    ShortCaseCitation,
    SupraCitation,
)

# The citation types this module is scoped to. Statute (FullLawCitation),
# journal (FullJournalCitation) and placeholder/unknown citations are dropped.
_CASE_LAW_TYPES = (
    FullCaseCitation,
    ShortCaseCitation,
    SupraCitation,
    IdCitation,
    ReferenceCitation,
)

_MIN_YEAR = 1600
_MAX_YEAR = datetime.now(timezone.utc).year + 1

# A parenthetical whose final token is a 4-digit year: "(1978)", "(10th Cir. 2013)",
# "(D. Colo. Mar. 3, 2011)". Requires the year at the close paren so that
# "(rejecting Conley)" or "(en banc)" do not match.
_YEAR_PAREN = re.compile(r"\(([^()]{0,60}?)(\d{4})\s*\)")

# "Plaintiff v. Defendant," immediately preceding the citation.
# Party names wrap across lines in real filings, so the character classes
# allow whitespace (including newlines); the captured value is collapsed to
# single spaces afterwards.
_CASE_NAME = re.compile(
    r"(?P<plaintiff>[A-Z][A-Za-z0-9'‘’\.\-&,\s]{0,140}?)"
    r"\s+v\.?\s+"
    r"(?P<defendant>[A-Z][A-Za-z0-9'‘’\.\-&,\s]{0,140}?)"
    r"\s*,?\s*$"
)

# Non-adversarial captions have no "v." at all: one party, not two. Domestic
# relations, dependency and neglect, probate and juvenile cases are all cited
# this way, so a case-name pattern built only around "v." silently drops a
# large share of family-law precedent.
#
#   In re Marriage of Rubio, 313 P.3d 623 (Colo. App. 2011)
#   People in the Interest of C.A.G., 903 P.2d 1229 (Colo. App. 1995)
_IN_RE_OPENER = re.compile(
    r"(?:In\s+re(?:\s+the)?|In\s+the\s+Matter\s+of|Matter\s+of|Ex\s+parte|"
    r"(?:People|State|Commonwealth)\s+in\s+the\s+Interest\s+of|"
    r"In\s+the\s+Interest\s+of|In\s+re:)",
    re.IGNORECASE,
)
# What may follow the opener. Initials with periods are common in juvenile
# captions ("C.A.G."), so periods and spaces are allowed.
_IN_RE_BODY = re.compile(r"^[A-Za-z0-9'‘’\.\-&,\s]{0,160}$")

# Bluebook introductory signals and common lead-in verbs. These are capitalised
# at the start of a sentence, so capitalisation alone cannot separate them from
# a party name.
_LEAD_IN_WORDS = {
    "see",
    "accord",
    "cf",
    "compare",
    "contra",
    "but",
    "eg",
    "e.g",
    "also",
    "generally",
    "under",
    "in",
    "citing",
    "quoting",
    "quoted",
    "following",
    "applying",
    "applied",
    "overruling",
    "overruled",
    "rejecting",
    "adopting",
    "per",
    "id",
    "supra",
    "infra",
    "to",
    "with",
    "from",
    "held",
    "holding",
    "relies",
    "relied",
    "reaffirmed",
    "affirmed",
    "reversed",
    "noted",
    "stated",
    "however",
    "here",
    "thus",
    "therefore",
    "because",
    "although",
    "since",
    "plaintiff",
    "defendant",
    "appellant",
    "appellee",
    "petitioner",
    "respondent",
    "court",
    "courts",
    "circuit",
    "reaffirm",
    "again",
    "and",
    # Honorifics end the preceding sentence with a period, which cannot be used
    # as a sentence boundary in legal text, so they leak into the window.
    "mr",
    "ms",
    "mrs",
    "dr",
    "prof",
    "hon",
    "atty",
    "esq",
}

# True Bluebook introductory signals. Narrower than _LEAD_IN_WORDS on purpose:
# these are safe to treat as "everything before this is prose", whereas nouns
# like "court" appear inside real party names ("Court of Appeals v. ...").
_SIGNAL_WORDS = {
    "see",
    "accord",
    "cf",
    "compare",
    "contra",
    "eg",
    "e.g",
    "also",
    "generally",
    "citing",
    "quoting",
    "quoted",
    "following",
    "applying",
    "overruling",
    "rejecting",
    "adopting",
    "supra",
    "infra",
    "but",
}

# Connector words that may appear lowercase inside a party name ("Board of
# Education", "Bank of the West"). "and" is deliberately NOT here: Bluebook
# abbreviates it to "&" inside case names, so an "and" running up to a citation
# is nearly always the prose that precedes the case name.
_NAME_CONNECTORS = {"of", "the", "for", "de", "van", "der", "del", "la", "&"}

# Section-heading numbering that can sit immediately before a citation:
# "III.", "A.", "2.". Matched against a token already stripped of punctuation,
# so it must be the whole token to count.
_NUMBERING = re.compile(r"[ivxlcdm]{1,7}|[a-z]|\d{1,3}", re.IGNORECASE)

# A year parenthetical must appear close to the citation; pin cites and
# court/year parentheticals are short.
_TRAILING_LOOKAHEAD = 100


@dataclass
class Citation:
    """One extracted citation with provenance."""

    kind: str
    text: str
    span: tuple[int, int]
    volume: str | None = None
    reporter: str | None = None
    page: str | None = None
    pin_cite: str | None = None
    year: int | None = None
    court: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    parenthetical: str | None = None
    antecedent: str | None = None
    corrected: str | None = None
    court_text: str | None = None
    # A non-adversarial caption ("In re Marriage of Rubio"), which has one
    # party rather than two and so cannot be held in plaintiff/defendant.
    case_name: str | None = None
    full_citation: str | None = None
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _valid_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if _MIN_YEAR <= year <= _MAX_YEAR else None


def _trailing_window(text: str, start: int, end: int) -> str:
    """Text after a citation, bounded by the next citation and a distance cap.

    No sentence splitting: legal abbreviations ("v.", "Cir.", "Colo. Mar.") make
    period-based splitting unsafe, which is the same defect this module works
    around in eyecite.
    """
    return text[start : min(end, start + _TRAILING_LOOKAHEAD)]


def _leading_window(text: str, start: int, end: int) -> str:
    """Text before a citation, bounded by the previous citation."""
    return text[start:end]


def _trim_lead_in(name: str) -> str:
    """Strip introductory prose, keeping the trailing run of name-like words.

    "Plaintiff relies on Monell" -> "Monell"
    "See also Bell Atlantic Corp." -> "Bell Atlantic Corp."
    """
    words = name.split()
    keep = len(words)
    for i in range(len(words) - 1, -1, -1):
        word = words[i]
        if word[:1].isupper() or word.lower().strip(",") in _NAME_CONNECTORS:
            keep = i
        else:
            break
    kept = words[keep:]
    # A Bluebook signal marks where the citation sentence starts, so anything
    # before it is prose. This matters because the preceding sentence often ends
    # in a capitalised abbreviation ("Att'y Gen.", "Pueblo County.", "Colo.")
    # that cannot be split on, and which otherwise survives as part of the name.
    last_signal = max(
        (
            index
            for index, word in enumerate(kept)
            if word.lower().strip(".,'‘’") in _SIGNAL_WORDS
        ),
        default=None,
    )
    if last_signal is not None and last_signal + 1 < len(kept):
        kept = kept[last_signal + 1 :]

    # Strip Bluebook signals, lead-in verbs, and section-heading numbering.
    # Briefs label sections "III.", "A.", "2." immediately before the sentence
    # that cites a case, and those tokens are capitalised like a party name, so
    # they survive the trailing-capitalised-run walk above.
    # Never strip the final word: "In re Estate" and a one-word party must survive.
    while len(kept) > 1:
        head = kept[0].lower().strip(".,'‘’")
        if head in _LEAD_IN_WORDS or _NUMBERING.fullmatch(head):
            kept = kept[1:]
            continue
        break
    while len(kept) > 1 and kept[0].lower().strip(".,") in _NAME_CONNECTORS:
        kept = kept[1:]
    return " ".join(kept).strip().strip(",")


def _derive_year_and_court(window: str) -> tuple[int | None, str | None]:
    match = _YEAR_PAREN.search(window)
    if not match:
        return None, None
    year = _valid_year(match.group(2))
    if year is None:
        return None, None
    court = match.group(1).strip().rstrip(",").strip() or None
    return year, court


def _court_hint_matches(hint: str, resolved: str) -> bool:
    """Loose consistency check between a parenthetical's court text and courts-db.

    Conservative by design: it only reports a mismatch when the parenthetical
    clearly names a court and shares no signal with the resolved id.
    """
    hint_l = hint.lower()
    # A bare date parenthetical ("Mar. 3," / "") names no court.
    if not any(ch.isalpha() for ch in hint_l):
        return True
    digits = "".join(ch for ch in hint_l if ch.isdigit())
    if digits and digits in resolved:
        return True
    letters = [w.strip(".,") for w in hint_l.split() if w.strip(".,").isalpha()]
    return any(w[:3] in resolved for w in letters if len(w) >= 3)


def _collapse(value: str) -> str:
    """Fold wrapped lines into single spaces."""
    return " ".join(value.split())


def _derive_parties(window: str) -> tuple[str | None, str | None]:
    stripped = window.rstrip()
    match = _CASE_NAME.search(stripped)
    if not match:
        return None, None
    plaintiff = _trim_lead_in(_collapse(match.group("plaintiff")))
    defendant = _collapse(match.group("defendant")).strip(",")
    if not plaintiff or not defendant:
        return None, None
    return plaintiff, defendant


def _derive_case_name(window: str) -> str | None:
    """A non-adversarial caption sitting immediately before the citation.

    Anchored on the last opener in the window, so a preceding sentence that
    happens to contain "in the matter of" cannot drag prose into the name.
    Returns the caption as written; there are no parties to split.
    """
    stripped = window.rstrip().rstrip(",").rstrip()
    openers = list(_IN_RE_OPENER.finditer(stripped))
    if not openers:
        return None
    candidate = _collapse(stripped[openers[-1].start():]).strip().strip(",").strip()
    if not candidate or not _IN_RE_BODY.match(candidate):
        return None
    # An opener alone is not a case name; something must follow it.
    remainder = _IN_RE_OPENER.sub("", candidate, count=1).strip(" :,.")
    return candidate if remainder else None


def _assemble_full_citation(record: Citation) -> str:
    """Render the complete citation the way a brief writes it.

    eyecite's own corrected_citation_full() is not used: it is built from the
    unbounded backward scan and drags in preceding prose.
    """
    reporter = " ".join(
        part for part in (record.volume, record.reporter, record.page) if part
    )
    body = reporter
    if record.pin_cite:
        body = f"{body}, {record.pin_cite}" if body else record.pin_cite

    inside = " ".join(
        part
        for part in (record.court_text, str(record.year) if record.year else None)
        if part
    )
    if inside:
        body = f"{body} ({inside})" if body else f"({inside})"

    if record.plaintiff and record.defendant:
        name = f"{record.plaintiff} v. {record.defendant}"
        return f"{name}, {body}" if body else name
    if record.case_name:
        return f"{record.case_name}, {body}" if body else record.case_name
    return body


def extract_pairs(text: str) -> list[tuple[Any, Citation]]:
    """Extract citations, keeping each eyecite object beside its record.

    Grouping needs the eyecite objects (resolve_citations operates on them),
    so they are carried alongside rather than discarded.
    """
    if not text or not text.strip():
        return []

    found = get_citations(text)
    # Case law only. eyecite also returns statute, journal and placeholder
    # citations; those are out of scope here and would otherwise arrive as
    # unattached noise (bare section symbols, C.F.R. cites, and so on).
    anchored = sorted(
        (
            c
            for c in found
            if c.span()[0] is not None and isinstance(c, _CASE_LAW_TYPES)
        ),
        key=lambda c: c.span()[0],
    )

    results: list[tuple[Any, Citation]] = []
    for i, cite in enumerate(anchored):
        start, end = cite.span()
        prev_end = anchored[i - 1].span()[1] if i else 0
        next_start = anchored[i + 1].span()[0] if i + 1 < len(anchored) else len(text)

        record = Citation(
            kind=type(cite).__name__,
            # The source slice, not matched_text(): on IdCitation eyecite's
            # span() covers the pin cite but matched_text() does not, and span
            # is what provenance depends on.
            text=text[start:end],
            span=(start, end),
            corrected=cite.corrected_citation(),
        )

        groups = getattr(cite, "groups", {}) or {}
        record.volume = groups.get("volume")
        record.reporter = groups.get("reporter")
        record.page = groups.get("page")

        meta = cite.metadata
        record.pin_cite = getattr(meta, "pin_cite", None)
        record.parenthetical = getattr(meta, "parenthetical", None)
        record.antecedent = getattr(meta, "antecedent_guess", None)

        if isinstance(cite, (FullCaseCitation, ShortCaseCitation)):
            after = _trailing_window(text, end, next_start)
            before = _leading_window(text, prev_end, start)

            year, court_hint = _derive_year_and_court(after)
            record.year = year
            eyecite_year = _valid_year(getattr(cite, "year", None))
            if year is None:
                if eyecite_year is not None:
                    record.flags.append(
                        f"year_unverified: eyecite reports {eyecite_year}, "
                        "no year parenthetical in this citation's own window"
                    )
            elif eyecite_year is not None and eyecite_year != year:
                record.flags.append(
                    f"year_corrected: eyecite reported {eyecite_year}, "
                    f"citation's own parenthetical says {year}"
                )

            record.court = getattr(meta, "court", None)
            record.court_text = court_hint
            if (
                record.court
                and court_hint
                and not _court_hint_matches(court_hint, record.court)
            ):
                # The citation's own parenthetical names a court. Confirm it is
                # consistent with what eyecite resolved.
                record.flags.append(
                    f"court_mismatch: eyecite resolved {record.court!r}, "
                    f"citation's parenthetical says {court_hint!r}"
                )

            if isinstance(cite, FullCaseCitation):
                plaintiff, defendant = _derive_parties(before)
                record.plaintiff = plaintiff
                record.defendant = defendant
                if plaintiff is None:
                    # No "v." in the window. That is the normal shape of a
                    # domestic relations, dependency or probate caption, not a
                    # failure, so look for a non-adversarial one before
                    # reporting the citation as nameless.
                    record.case_name = _derive_case_name(before)
                ec_p = (getattr(meta, "plaintiff", None) or "").strip()
                ec_d = (getattr(meta, "defendant", None) or "").strip()
                if plaintiff is None and record.case_name is None and (ec_p or ec_d):
                    record.flags.append(
                        f"parties_unverified: eyecite reported "
                        f"{ec_p!r} v. {ec_d!r}, no 'v.' pattern in this "
                        "citation's own window"
                    )
                elif plaintiff is not None and (ec_p != plaintiff or ec_d != defendant):
                    record.flags.append(
                        f"parties_corrected: eyecite reported {ec_p!r} v. {ec_d!r}"
                    )
        elif isinstance(cite, (SupraCitation, IdCitation)):
            record.year = None

        if isinstance(cite, FullCaseCitation):
            record.full_citation = _assemble_full_citation(record)
        results.append((cite, record))

    return results


def extract(text: str) -> list[Citation]:
    """Extract case law citations from text, in document order."""
    return [record for _, record in extract_pairs(text)]
