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
from functools import lru_cache
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
# "ex rel." joins the relator to the state: People ex rel. State Bd. of
# Equalization v. Hively. Cut at "rel." the caption lost "People ex rel.".
_NAME_CONNECTORS = {"of", "the", "for", "de", "van", "der", "del", "la", "&", "ex", "rel."}

# Section-heading numbering that can sit immediately before a citation:
# "III.", "A.", "2.". Matched against a token already stripped of punctuation,
# so it must be the whole token to count.
_NUMBERING = re.compile(r"[ivxlcdm]{1,7}|[a-z]|\d{1,3}", re.IGNORECASE)
# A page marker fused onto the caption by a table of authorities or a page
# stamp ("P13 County of Sacramento v. Lewis"). No party name is a letter
# followed only by digits.
_PAGE_MARK = re.compile(r"[a-z]{1,2}\d{1,4}", re.IGNORECASE)

# PDF text layers sometimes map the capital I in Ion Media's name to a
# lowercase l. Keep this correction deliberately narrow: changing arbitrary
# lowercase words at a case-name boundary would turn ordinary prose into a
# party name.
_ION_MEDIA_OCR = re.compile(r"\blon(?=\s+Media\s+Networks\b)")

# A Table of Authorities heading sits directly before its first case and is
# therefore inside the same citation-bounded window. It is layout, not a party.
_TOA_CASES_PREFIX = re.compile(
    r"^(?:.*\s)?TABLE\s+OF\s+AUTHORITIES\s+(?:Cases\s+)?", re.IGNORECASE | re.DOTALL
)

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
    name = _TOA_CASES_PREFIX.sub("", name)
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
        if head in _LEAD_IN_WORDS or _NUMBERING.fullmatch(head) or _PAGE_MARK.fullmatch(head):
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


def _normalize_court_text(text: str) -> str:
    return " ".join(text.replace(".", ". ").split()).lower()


@lru_cache(maxsize=1)
def _court_abbreviations() -> tuple[tuple[str, frozenset[str]], ...]:
    """Bluebook court abbreviations ("D. Colo.", "E.D. Ky.") and their court ids,
    longest first so "E.D. Ky." is tried before "Ky."."""
    from courts_db import courts

    table: dict[str, set[str]] = {}
    for court in courts:
        abbreviation = court.get("citation_string")
        if abbreviation:
            table.setdefault(_normalize_court_text(abbreviation), set()).add(court["id"])
    # Bluebook writes several intermediate appellate courts without "Ct.":
    # courts-db's "Colo. Ct. App." is cited "Colo. App.".
    for key, ids in list(table.items()):
        if key.endswith(" ct. app."):
            table.setdefault(key[: -len(" ct. app.")] + " app.", set(ids))
    return tuple(sorted(((k, frozenset(v)) for k, v in table.items()), key=lambda kv: -len(kv[0])))


def _court_from_hint(hint: str) -> str | None:
    """The court a parenthetical names, when it names exactly one.

    eyecite leaves the court empty for "977 P.2d 299 (Colo. App. 1999)": a
    regional reporter serves many courts. The parenthetical says which. Only an
    exact abbreviation with a single court id counts; anything looser stays None.
    """
    normalized = _normalize_court_text(hint)
    for abbreviation, ids in _court_abbreviations():
        if normalized == abbreviation:
            return next(iter(ids)) if len(ids) == 1 else None
    return None


def _court_hint_matches(hint: str, resolved: str) -> bool:
    """Loose consistency check between a parenthetical's court text and courts-db.

    Conservative by design: it only reports a mismatch when the parenthetical
    clearly names a court and shares no signal with the resolved id.
    """
    hint_l = hint.lower()
    # A bare date parenthetical ("Mar. 3," / "") names no court.
    if not any(ch.isalpha() for ch in hint_l):
        return True
    # The parenthetical's own abbreviation, when courts-db knows it, settles
    # the question: "D. Colo." is "cod", which shares no three letters with it.
    normalized = _normalize_court_text(hint)
    for abbreviation, ids in _court_abbreviations():
        if normalized == abbreviation or normalized.startswith(abbreviation + " "):
            return resolved in ids
    digits = "".join(ch for ch in hint_l if ch.isdigit())
    if digits and digits in resolved:
        return True
    letters = [w.strip(".,") for w in hint_l.split() if w.strip(".,").isalpha()]
    return any(w[:3] in resolved for w in letters if len(w) >= 3)


def _collapse(value: str) -> str:
    """Fold wrapped lines into single spaces."""
    return " ".join(value.split())


# The end of a prose sentence inside a name window: a lower-case word of three
# or more letters, a period, then a capital. Case-name abbreviations are
# capitalised ("Co.", "Inc.", "U.S.") and the lower-case ones are excluded, so
# the cut never lands inside a caption.
_PROSE_SENTENCE_END = re.compile(
    r"\b(?!(?:rel|seq|etc|viz|cit|supp|cert|den|aff|rev|mem)\.)[a-z]{3,}\.\s+(?=[A-Z])"
)


def _after_last_sentence(window: str) -> str:
    """The window from the start of the sentence the citation sits in.

    "... in United States v. Hassan, holding that social media posts are
    admissible when adequately authenticated. Hassan, 742 F.3d 104" must not
    yield a defendant that runs across the sentence end.
    """
    ends = list(_PROSE_SENTENCE_END.finditer(window))
    return window[ends[-1].end():] if ends else window


def _derive_parties(window: str) -> tuple[str | None, str | None]:
    stripped = _after_last_sentence(window).rstrip()
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


# OCR slips that stop eyecite recognising a citation at all, each replaced by a
# string of the same length so every span still indexes the original text.
# Scanned filings read the ordinal in a public-domain citation as "(Ist)" or
# "(lst)": Mata v. Avianca, ECF 21, cites "Shaboon v. Egyptair, 2013 IL App
# (Ist) 111279-U", which was then never extracted and so never checked.
_OCR_ORDINAL = re.compile(r"(\bApp\.? )\([Il]st\)")


def _ocr_for_parsing(text: str) -> str:
    return _OCR_ORDINAL.sub(r"\1(1st)", text)


_WHITESPACE_RUN = re.compile(r"\s+")


def _collapse_whitespace(text: str) -> tuple[str, list[int]]:
    """``text`` with each whitespace run as one space, and where each char came from."""
    out: list[str] = []
    origin: list[int] = []
    last = 0
    for match in _WHITESPACE_RUN.finditer(text):
        out.append(text[last : match.start()])
        origin.extend(range(last, match.start()))
        out.append(" ")
        origin.append(match.start())
        last = match.end()
    out.append(text[last:])
    origin.extend(range(last, len(text)))
    origin.append(len(text))
    return "".join(out), origin


def _map_span_back(cite: Any, origin: list[int]) -> None:
    start, end = cite.span()
    if start is None or end is None:
        return
    cite.span_start = origin[start]
    cite.span_end = origin[end - 1] + 1 if end > start else origin[end]
    for attr in ("full_span_start", "full_span_end"):
        value = getattr(cite, attr, None)
        if value is not None:
            setattr(cite, attr, origin[value - 1] + 1 if attr.endswith("end") and value else origin[value])


def extract_pairs(text: str) -> list[tuple[Any, Citation]]:
    """Extract citations, keeping each eyecite object beside its record.

    Grouping needs the eyecite objects (resolve_citations operates on them),
    so they are carried alongside rather than discarded.
    """
    if not text or not text.strip():
        return []

    # PDF text layers break lines anywhere, including inside a citation
    # ("Florida v. Jardines, 569\nU.S. 1"; "Woods v. BNSF Railway Co., 2016\n\n
    # WL 165971"), and eyecite reads neither a line break nor a run of spaces
    # between volume and reporter. The citation was then missed, and its
    # quotation attributed to the next citation found. eyecite parses a copy
    # with every whitespace run collapsed to one space; each citation's span is
    # then mapped back, so every span still indexes the original text.
    parsed, origin = _collapse_whitespace(_ocr_for_parsing(text))
    found = get_citations(parsed)
    if len(parsed) != len(text):
        for cite in found:
            _map_span_back(cite, origin)
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
            if record.court is None and court_hint:
                record.court = _court_from_hint(court_hint)
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
                corrected_before, correction_count = _ION_MEDIA_OCR.subn(
                    "Ion", before
                )
                if correction_count:
                    record.flags.append(
                        "party_name_ocr_corrected: 'lon Media Networks' -> "
                        "'Ion Media Networks'"
                    )
                plaintiff, defendant = _derive_parties(corrected_before)
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
