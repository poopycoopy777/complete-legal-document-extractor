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
    UnknownCitation,
)
from eyecite.tokenizers import Token

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
#
# The year must stand alone: a digit or letter in front of it ("(Colo., C2022)",
# "(Colo. 12022)") is a typo in the filing, and reading 2022 out of it would
# present a repair as if the filing had printed it.
_YEAR_PAREN = re.compile(r"\(([^()]{0,60}?)(?<![A-Za-z0-9])(\d{4})\s*\)")
_GLUED_YEAR_PAREN = re.compile(r"\(([^()]{0,60}?[A-Za-z]\d{4})\s*\)")

# Reporters print a party's foreign particle the way the caption has it, which
# is often lower case: "Ashcroft v. al-Kidd", "United States v. van der
# Linden", "de la Cruz v. Homan". Requiring BOTH parties to open with a capital
# dropped that class of caption entirely, and a citation extracted without a
# name is reported downstream as a caption mismatch against the very case it
# cites. The list is explicit: accepting any lower-case word would turn the
# prose that precedes a citation into a party.
_PARTY_PARTICLES = (
    "al", "bin", "bint", "da", "das", "de", "del", "della", "den", "der",
    "di", "dos", "du", "el", "ibn", "la", "le", "ten", "ter", "van", "von",
)
_PARTICLE_ALT = "|".join(_PARTY_PARTICLES)
# A run of leading particles, each followed by the separator the caption
# prints: "al-Kidd", "van der Linden", "della Robbia".
_PARTICLE_RUN = rf"(?:(?:{_PARTICLE_ALT})[-'\u2019\s])*"
# A party opens on a capital, or on a particle that the caption leaves lower
# case. The lookahead that keeps prose out is the capital itself: a lower-case
# word is only ever consumed when a capital follows it ("de Novo" is not a
# party, "de la Cruz" is). The capital may be a non-ASCII letter: a caption can
# print "\u00c5berg" or "Mu\u00f1oz".
_PARTY_HEAD = rf"(?=(?:{_PARTICLE_RUN}[^\W\d_]|\$[0-9]))"
# A party's characters are whatever the typesetter printed, not ASCII. PDF text
# layers carry the typographic ligatures ("Ho\ufb00" for "Hoff", "Co\ufb01man")
# and real accents. An ASCII-only class dropped the party entirely, and the
# citation then reached identity checking with no case name at all -- reported
# as a caption mismatch against the case the filing names.
_PARTY_BODY = (
    r"(?:[^\W\d_]|[0-9$'\u2018\u2019\.\-\u2013&,\s]"
    r"|\([A-Za-z0-9 .&\x27-]{1,40}\)){0,140}"
)

# "Plaintiff v. Defendant," immediately preceding the citation.
# Party names wrap across lines in real filings, so the character classes
# allow whitespace (including newlines); the captured value is collapsed to
# single spaces afterwards.
_CASE_NAME = re.compile(
    rf"(?P<plaintiff>{_PARTY_HEAD}{_PARTY_BODY}?)"
    r"\s+_?v\.?\s+"  # OCR of a scanned brief: "Doe _v. United States"
    rf"(?P<defendant>{_PARTY_HEAD}{_PARTY_BODY}?)"
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
    r"(?:In\s+re:?(?:\s+the)?|In\s+the\s+Matter\s+of|Matter\s+of|Ex\s+parte|"
    r"(?:People|State|Commonwealth)\s+in\s+(?:the\s+)?Interest\s+of|"
    r"In\s+the\s+Interest\s+of)",
    re.IGNORECASE,
)
# What may follow the opener. Initials with periods are common in juvenile
# captions ("C.A.G."), so periods and spaces are allowed.
_IN_RE_BODY = re.compile(r"^[A-Za-z0-9'\u2018\u2019:.\-&,\s]{0,160}$")

# Bluebook introductory signals and common lead-in verbs. These are capitalised
# at the start of a sentence, so capitalisation alone cannot separate them from
# a party name.
_LEAD_IN_WORDS = {
    "as",
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

# The connectors that may be left over from the prose a caption follows. The
# particles are deliberately excluded: a leading particle belongs to the
# caption itself, so "de la Cruz v. Davis" must not be cut down to
# "Cruz v. Davis".
_STRIPPABLE_CONNECTORS = _NAME_CONNECTORS - set(_PARTY_PARTICLES)

# An entity suffix closes a party even when OCR or the typist lowercased it:
# "Freedom Colorado Information, inc. v. El Paso County" lost its whole caption
# because the capitalised-run walk stopped at "inc.". Matched as printed, never
# re-cased, so the name stays the source text.
_ENTITY_SUFFIXES = {"inc.", "inc", "corp.", "co.", "ltd.", "llc", "l.l.c.", "llp", "l.l.p.", "l.p."}

# A word that may close a party name: a capitalised word, a connector, or a
# particle-led word such as "al-Kidd". The lookahead keeps ordinary lower-case
# prose out -- neither "also" nor "derivative" opens on a whole particle -- and
# excluding a trailing period keeps the abbreviation "et al." out, which is
# prose, not a party.
_PARTICLE_WORD = re.compile(rf"(?:{_PARTICLE_ALT})(?=[-'\u2019\s]|$)")

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

# An ECF page stamp's last line sits directly above a table-of-authorities
# entry: "PageID.1994 Mendocino Envtl. Ctr. v. Mendocino Cnty.".
_PAGE_STAMP_PREFIX = re.compile(r"^(?:.*\s)?PageID\s*[.#:]?\s*\d+\s+", re.DOTALL)

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


def _is_party_word(word: str) -> bool:
    """A word that may sit at the closing edge of a party name.

    Capitalised words, the lower-case connectors reporters print inside a
    caption ("of", "the"), and particle-led words ("al-Kidd") all qualify;
    ordinary lower-case prose does not.
    """
    stripped = word.lstrip("(").strip(",")
    if not stripped:
        return False
    if stripped[:1].isupper():
        return True
    lowered = stripped.lower()
    return lowered in _NAME_CONNECTORS or lowered in _ENTITY_SUFFIXES or bool(_PARTICLE_WORD.match(stripped))


def _trim_lead_in(name: str) -> str:
    """Strip introductory prose, keeping the trailing run of name-like words.

    "Plaintiff relies on Monell" -> "Monell"
    "See also Bell Atlantic Corp." -> "Bell Atlantic Corp."
    """
    name = _TOA_CASES_PREFIX.sub("", name)
    name = _PAGE_STAMP_PREFIX.sub("", name)
    # A narrative citation can follow a sentence ending in a capitalized
    # legal term: "Fourth Amendment. In Cortez v. McCauley". The ordinary
    # lowercase sentence-end rule deliberately preserves party abbreviations.
    # This explicit prose opener supplies the boundary without cutting those.
    narrative = list(re.finditer(r"\.\s+In\s+(?=[A-Z])", name))
    if narrative:
        name = name[narrative[-1].end():]
    words = name.split()
    keep = len(words)
    for i in range(len(words) - 1, -1, -1):
        word = words[i]
        if _is_party_word(word):
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
    while len(kept) > 1 and kept[0].lower().strip(".,") in _STRIPPABLE_CONNECTORS:
        kept = kept[1:]
    return " ".join(kept).strip().strip(",")


def _derive_year_and_court(window: str) -> tuple[int | None, str | None]:
    match = _YEAR_PAREN.search(window)
    if not match:
        return None, None
    year = _valid_year(match.group(2))
    if year is None:
        return None, None
    court = _collapse(match.group(1)).rstrip(",").strip() or None
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


# A section heading of a table of authorities or an index of cases. It is layout,
# not a party, but sits on the line above the first caption of its section and
# is capitalised like one: "Case Authorities\n\nAMCO Ins. Co. v. Sills" gave the
# plaintiff "Case Authorities AMCO Ins. Co.". Only a line that is nothing but
# the heading counts, so "Case Authorities Inc. v. Smith" on one line is a
# party name and is left whole.
_SECTION_HEADING_LINE = re.compile(
    r"^[ \t]*(?:table[ \t]+of[ \t]+(?:authorities|cases)|index[ \t]+of[ \t]+authorities"
    r"|(?:(?:case|statutory|constitutional|other|cited)[ \t]+)?authorities"
    r"|cases(?:[ \t]+cited)?|case[ \t]+law|statutes)[ \t]*[:.]?[ \t]*\r?\n",
    re.IGNORECASE | re.MULTILINE,
)


def _after_section_heading(window: str) -> str:
    """The window from the line after the last section heading that stands alone."""
    headings = list(_SECTION_HEADING_LINE.finditer(window))
    return window[headings[-1].end():] if headings else window


# A filing-service stamp that stands alone on its own line above a caption:
# "NOT A FILED PLEADING" across the top of a proposed brief, or "NOT AN
# OFFICIAL COURT DOCUMENT" on a slip copy. It is layout, not a party, but every
# word is capitalised like one, so the caption read the stamp in as the
# plaintiff and the assembled case name carried it into verification, where the
# caption then failed to match the case it actually cites. Only a line that is
# nothing but the stamp counts, so "Not a Filed Pleading, Inc. v. Smith" on one
# line is a party name and is left whole.
_STAMP_HEADING_LINE = re.compile(
    r"^[ \t]*(?:"
    r"not[ \t]+(?:a|an)[ \t]+(?:filed[ \t]+pleading|official[ \t]+(?:court[ \t]+)?document|original[ \t]+(?:document|pleading))"
    r"|not[ \t]+for[ \t]+(?:publication|filing|citation)"
    r"|draft(?:[ \t]+version)?"
    r"|(?:unfiled|unofficial)[ \t]+(?:copy|draft|document)"
    r"|placeholder(?:[ \t]+(?:pleading|document))?"
    r")[ \t]*[:.]?[ \t]*\r?\n",
    re.IGNORECASE | re.MULTILINE,
)


def _after_stamp_heading(window: str) -> str:
    """The window from the line after the last standalone filing stamp."""
    stamps = list(_STAMP_HEADING_LINE.finditer(window))
    return window[stamps[-1].end():] if stamps else window


def _strip_emphasis_markers(window: str) -> str:
    """Remove Markdown emphasis delimiters that wrap a caption.

    Pasted text may italicise a case name ("*Warne v. Hall*"). The markers sit
    at the caption boundary -- a leading run and a run immediately before the
    terminal comma or end -- never inside a real party name, so only those two
    positions are stripped.
    """
    window = re.sub(r"^[*_]+", "", window)
    return re.sub(r"[*_]+(?=\s*,?\s*$)", "", window)


def _normalize_docket_slashes(window: str) -> str:
    """A federal docket number separates its magistrate with either slash.

    "No. CIV 16-0318 JB\\SCY" is printed with a backslash on the docket. A
    backslash is not a party-name character, so the caption match stopped inside
    the docket number and the case was reported with no name at all. The window
    is a working copy for parsing only; the reported text and its spans are read
    from the original elsewhere, so this cannot move an offset.
    """
    return window.replace("\\", "/")


def _normalize_glued_versus(window: str) -> str:
    """A text layer that drops the space before "v." glues the parties together.

        "... in favor of the plaintiff.  Rectorv.  City and County of
         Denver, 122 P.3d 1010 (Colo. App. 2005), certiorari denied ..."

    One character is missing from the caption, and it costs the case its name
    twice over: "_after_last_sentence" reads "Rectorv." as the end of a sentence,
    and the party pattern needs whitespace before the "v." anyway. The caption
    was rejected, so the citation reached verification with whatever word sat
    before the comma as its name ("Denver"), and the card said the case was
    unnamed even though the filing prints its name in full. Parsing-only: the
    reported text and its spans come from the original.
    """
    return re.sub(r"(?<=[^\W\d_])v\.(?=\s+[^\W\d_])", " v.", window)


# A scanned page's text layer leaves stray marks on lines of their own inside a
# caption that wraps across lines: "Freedom Colorado Information,", a line holding
# one replacement character, a line holding "a", then "inc. v. El Paso County
# Sheriff's Department". Such a line is a mark that is not text (a replacement
# character, a stray quote or semicolon) or a single lower-case letter, which no
# party name is. The backward scan stopped at it, so the caption lost its first
# party and the card read "inc. v. El Paso County Sheriff's Department". "&" is a
# real party connector and "v" a glued versus, so neither counts. Parsing-only:
# reported text and spans come from the original.
_NOISE_LINE_BODY = r"[ \t]*(?:[^\w&\s]+|[a-uw-z])[ \t]*"
_NOISE_LINE = re.compile(rf"^{_NOISE_LINE_BODY}(?:\r?\n|$)", re.MULTILINE)
# Between two words of a caption: whitespace, which may run across noise lines.
NOISE_TOLERANT_SPACE = rf"(?:\s+|\s*\n(?:{_NOISE_LINE_BODY}\r?\n)+\s*)"


def _drop_noise_lines(window: str) -> str:
    return _NOISE_LINE.sub("", window)


def _derive_parties(window: str) -> tuple[str | None, str | None]:
    stripped = _strip_emphasis_markers(
        _normalize_docket_slashes(
            _after_last_sentence(_after_section_heading(_after_stamp_heading(
                _normalize_glued_versus(_drop_noise_lines(window))
            )))
        ).rstrip()
    )
    match = _CASE_NAME.search(stripped)
    if not match:
        return None, None
    # Parentheses inside corporate captions are literal source text. Require
    # balanced pairs so an incomplete caption cannot become a partial party.
    for party in (match.group("plaintiff"), match.group("defendant")):
        depth = 0
        for char in party:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            if depth < 0:
                return None, None
        if depth:
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
    stripped = _strip_emphasis_markers(
        _after_stamp_heading(_drop_noise_lines(window)).rstrip().rstrip(",").rstrip()
    )
    openers = list(_IN_RE_OPENER.finditer(stripped))
    if not openers:
        return None
    candidate = _collapse(stripped[openers[-1].start():]).strip().strip(",").strip()
    if not candidate or not _IN_RE_BODY.match(candidate):
        return None
    # An opener alone is not a case name; something must follow it.
    remainder = _IN_RE_OPENER.sub("", candidate, count=1).strip(" :,.")
    return candidate if remainder else None


# The short name a brief prints in front of a repeat citation: "Warne, 2016 CO
# 50, para. 24", "Bell Atlantic Corp., 550 U.S. 544". eyecite's own answer for
# this shape is unsound -- on the supplied dismissal it read
# "Rule 12(b)(5). Warne" as the defendant, dragging the previous sentence in --
# and its antecedent_guess is always None on this version, so the name was
# dropped and the occurrence was then reported as though nothing named it.
#
# The clause is what bounds a short name: it sits after the last sentence or
# clause break, before the citation. A period only ends a sentence when a new one
# follows it, so the abbreviation period in "Bell Atlantic Corp., 550 U.S. 544"
# does not cut the name in half.
_CASE_NAME_CLAUSE_BREAK = re.compile(r"[;:!?\n\u2014\u2013]")
_CASE_NAME_SENTENCE_END = re.compile(r"(?<!\bv)\.(?=\s+[A-Z\"\u201c(])")
_CASE_NAME_RUN = re.compile(
    r"([A-Z][\w&.'\u2019-]*"
    r"(?:\s+(?:(?:of|the|and|for|on|in|d(?:ba)?)\s+)?[A-Z][\w&.'\u2019-]*)*"
    r")\s*$"
)


def _clause_tail(window: str) -> str:
    """The last clause of ``window``, with abbreviation periods left intact."""
    tail = window
    for pattern in (_CASE_NAME_CLAUSE_BREAK, _CASE_NAME_SENTENCE_END):
        matches = list(pattern.finditer(tail))
        if matches:
            tail = tail[matches[-1].end():]
    return tail.strip()


def _derive_short_case_name(window: str) -> str | None:
    """The case name printed immediately before a repeat citation, if any.

    Returns None rather than a guess when the clause holds anything a name cannot
    contain: digits, section signs, parentheses, or a lower-case word that is not
    a listed connector. A missed name costs a label; a wrong one labels a case
    with another case's party.
    """
    tail = _clause_tail(window.rstrip()).rstrip(",\u2019'").strip()
    if not tail or len(tail) > 120:
        return None
    if _IN_RE_OPENER.match(tail):
        # A non-adversarial caption ("In re Marriage of Rubio, 313 P.3d 623")
        # is parsed by its own rule, which knows how far a name runs.
        return _derive_case_name(tail + ", ")
    if re.search(r"[\d\u00a7()\[\]]", tail):
        return None
    match = _CASE_NAME_RUN.fullmatch(tail)
    if match is None:
        return None
    # The pattern stops at the final token's own characters, so an abbreviation
    # keeps its period ("Bell Atlantic Corp.") while a trailing comma does not.
    name = _collapse(match.group(1))
    if not name or _norm_word(name) in _SIGNAL_WORDS:
        # A lone introductory signal is prose, not a party. "See, 550 U.S. 544"
        # names nothing, and labelling the case "See" is worse than no label.
        return None
    return name


def _norm_word(value: str) -> str:
    return value.strip().strip(".,").lower()


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
        return _collapse(f"{name}, {body}" if body else name)
    if record.case_name:
        return _collapse(f"{record.case_name}, {body}" if body else record.case_name)
    return _collapse(body)


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


def _case_law_cites(text: str) -> list[Any]:
    """eyecite's case-law citations in ``text``, in order, spans indexing ``text``."""
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
    anchored = [cite for cite in anchored if not _is_exhibit_number(cite, text)]
    for cite in anchored:
        if isinstance(cite, IdCitation):
            _release_paragraph_marker(cite, text)
    return sorted(
        [*anchored, *_incomplete_cites(text, anchored)], key=lambda c: c.span()[0]
    )


# An exhibit label in front of the "volume": an exhibit list row such as
# "Ex. 9    Call 25-114565 Redacted" reads as 9 Call 25, volume 9 of Call's
# Virginia Reports. A reporter volume never follows "Ex." or "Exhibit".
_EXHIBIT_LABEL = re.compile(r"(?<![A-Za-z])(?:Ex|Exh|Exs|Exhs|Exhibits?)\.?\s*$", re.IGNORECASE)


def _is_exhibit_number(cite: Any, text: str) -> bool:
    start = cite.span()[0]
    return bool(start) and bool(_EXHIBIT_LABEL.search(text, max(0, start - 20), start))


# A pin cite eyecite read off the numbered paragraph that follows an Id.:
#
#   ...has standing to appeal. Id.\n\n   14. Any issue with the search warrant
#
# eyecite parses a copy with whitespace collapsed, so "Id. 14" looks like a pin.
# A real pin follows "at" or sits on the Id.'s own line; a number that starts
# its own line and is followed by a period and a new sentence is the next
# paragraph's marker.
_ID_THEN_PARAGRAPH_NUMBER = re.compile(r"(?P<id>Id\.?)(?P<gap>\s*\n\s*)\d{1,4}", re.IGNORECASE)
_PARAGRAPH_MARKER_TAIL = re.compile(r"\.[ \t]+[A-Z(\u201c\"]")


def _release_paragraph_marker(cite: Any, text: str) -> None:
    start, end = cite.span()
    match = _ID_THEN_PARAGRAPH_NUMBER.fullmatch(text, start, end)
    if not match or not _PARAGRAPH_MARKER_TAIL.match(text, end):
        return
    cite.span_end = match.end("id")
    if getattr(cite, "full_span_end", None) is not None:
        cite.full_span_end = match.end("id")
    cite.metadata.pin_cite = None


@lru_cache(maxsize=1)
def _reporter_names() -> frozenset[str]:
    """Every reporter abbreviation and variant eyecite knows, spacing removed."""
    from reporters_db import REPORTERS

    names: set[str] = set()
    for key, entries in REPORTERS.items():
        names.add(key)
        for entry in entries:
            names.update(entry["editions"])
            names.update(entry.get("variations", {}))
    return frozenset(re.sub(r"\s+", "", name).lower() for name in names)


# A volume and a reporter with no first page, straight into the court/year
# parenthetical: "Woo v. El Paso County Sheriff's Office, 528 P.3d (Colo., 2022)".
# eyecite needs a page and reports nothing, so the citation vanished from the
# result and the reader counted one case fewer than the brief cites. The
# parenthetical must carry a year, and the reporter must be a known one that is
# printed with a period ("P.3d", "Colo."), which keeps "Exhibit 12 (attached)",
# "42 U.S.C. (2018)" and bare state codes out.
_NO_PAGE_CITATION = re.compile(
    r"(?<![\w.])(?P<volume>\d{1,4})[ \t]+(?P<reporter>[A-Z][A-Za-z.\d' ]{0,18}?)[ \t]*"
    r"(?=\([^()]{0,60}(?<![A-Za-z0-9])\d{4}\s*\))"
)


def _incomplete_cites(text: str, found: list[Any]) -> list[Any]:
    """Stand-in eyecite objects for each volume-and-reporter cite with no page.

    UnknownCitation is a kind the result schema and the interface already carry;
    eyecite's resolver ignores it and breaks any Id. chain through it, which is
    right: an Id. after a citation nobody could read has no referent.
    """
    taken = [cite.span() for cite in found]
    cites: list[Any] = []
    for match in _NO_PAGE_CITATION.finditer(text):
        reporter = match.group("reporter").rstrip()
        if "." not in reporter or re.sub(r"\s+", "", reporter).lower() not in _reporter_names():
            continue
        start = match.start("volume")
        end = match.start("reporter") + len(reporter)
        if any(start < b and a < end for a, b in taken):
            continue
        cites.append(
            UnknownCitation(Token(text[start:end], start, end), 0, span_start=start, span_end=end)
        )
    return cites


def case_citation_spans(text: str) -> list[tuple[int, int]]:
    """Spans of every case citation except Id., which has no referent of its own.

    A statute's "Id." is only meaningful when no case was cited after the
    statute, so the statute extractor asks where the cases are.
    """
    if not text or not text.strip():
        return []
    return [
        (start, end)
        for cite in _case_law_cites(text)
        if not isinstance(cite, IdCitation)
        for start, end in [cite.span()]
    ]


def _incomplete_record(text: str, cite: Any, prev_end: int, next_start: int) -> Citation:
    """A citation that names a volume and reporter but no page, flagged as such.

    It keeps what the filing printed -- caption, court, year -- and nothing it
    did not: no page, and no assembled full citation, so it can never be
    mistaken for one that could be checked against a reporter.
    """
    start, end = cite.span()
    record = Citation(
        kind="UnknownCitation",
        text=text[start:end],
        span=(start, end),
    )
    record.volume, record.reporter = text[start:end].split(None, 1)
    record.flags.append(
        f"incomplete: no first page after {record.volume} {record.reporter}; "
        "the citation cannot be located or verified as printed"
    )
    record.year, hint = _derive_year_and_court(_trailing_window(text, end, next_start))
    record.court_text = hint
    if record.court_text:
        record.court = _court_from_hint(record.court_text)
    before = _leading_window(text, prev_end, start)
    record.plaintiff, record.defendant = _derive_parties(before)
    if record.plaintiff is None:
        record.case_name = _derive_case_name(before)
    return record


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
    anchored = _case_law_cites(text)

    results: list[tuple[Any, Citation]] = []
    for i, cite in enumerate(anchored):
        start, end = cite.span()
        prev_end = anchored[i - 1].span()[1] if i else 0
        next_start = anchored[i + 1].span()[0] if i + 1 < len(anchored) else len(text)

        if isinstance(cite, UnknownCitation):
            results.append((cite, _incomplete_record(text, cite, prev_end, next_start)))
            continue

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
                glued = _GLUED_YEAR_PAREN.search(after)
                if glued:
                    record.flags.append(
                        f"year_unverified: parenthetical reads ({_collapse(glued.group(1))}), "
                        "which has no standalone four-digit year"
                    )
                elif eyecite_year is not None:
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
                # A missing PDF word boundary in the narrative opener is not a
                # spelling correction to the party. Parse a copy and preserve
                # the original text/spans; never rewrite Igbal into Iqbal.
                corrected_before, joined = re.subn(
                    r"\b(In the case of)(?=[A-Z])", r"\1 ", corrected_before
                )
                if joined:
                    record.flags.append("party_name_boundary_normalized: joined narrative preposition")
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
                if plaintiff is None and record.case_name is None:
                    # A brief names a case in full once and then refers to it by
                    # party name with the reporter citation: "Warne, 2016 CO 50,
                    # para. 24, 373 P.3d at 596." The name is printed in front of
                    # the citation, so this occurrence does carry naming
                    # evidence; leaving it unnamed reported the later occurrence
                    # of a named case as though nothing identified it.
                    record.case_name = _derive_short_case_name(before)
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
