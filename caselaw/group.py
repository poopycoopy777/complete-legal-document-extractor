"""Group extracted citations under the full citation they refer back to.

A brief cites a case once in full, then refers to it by short form, `id.` or
`supra`, and quotes it. The UI needs that shape: one header per case, with every
subsequent reference and quotation cascaded beneath it.

Grouping uses eyecite's resolve_citations. Note that eyecite resolves `supra`
and `id.` antecedents with the same backward scan that extract.py works around
for full citations, so group membership is less certain than the citation data
itself. Anything eyecite cannot attach to a full citation is returned in
`orphans` rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from eyecite import resolve_citations

from .authorities import Authority, extract_authorities
from .extract import Citation, extract_pairs
from .record_cites import RecordCite, extract_record_cites

# Quoted material: straight or curly doubles.
#
# The body may not contain another double-quote mark of either style. PDF text
# layers are routinely unbalanced -- a closing double rendered as a right SINGLE
# quote, for instance -- and without that guard a quotation runs on past its
# real end, swallowing unrelated prose and later quotations until it finds a
# closer. Explicitly paired quotes are retained even when short; the 2,000
# character ceiling bounds damage from an unmatched opener while allowing block
# quotations and PDF line wrapping.
_QUOTE = re.compile(
    r'"([^"\u201c\u201d]{1,2000})"'
    r"|\u201c([^\u201c\u201d]{1,2000})\u201d"
)

# How far a quotation may sit from the citation it is attributed to.
_QUOTE_FORWARD = 260
_QUOTE_BACKWARD = 140

# Proposition: the sentence a filing cites an authority for. A sentence ends at
# . ! ? followed by whitespace and an uppercase letter or newline, which rules
# out most abbreviations ("Corp.", "v.", "U.S.").
_SENT_END = re.compile(r"[.!?]\s+(?=[A-Z\n])")
_PROP_WINDOW = 800
# How far before the reporter a caption may begin ("United States v. Carloss, ").
_CAPTION_WINDOW = 300
# What trails an earlier citation before the next sentence can begin: pin
# pages, court/year and explanatory parentheticals, a closing period.
_CITATION_TAIL = re.compile(
    r"(?:[\s,;]*(?:at\s+)?[\d\u00b6\u00a7\-\u2013,\s]*)?(?:\s*\([^()]*\))*\s*[.;]?"
)
# Layout, not prose: table-of-contents / table-of-authorities dot leaders.
_DOT_LEADER = re.compile(r"\.{4,}|\u2026|(?:\.\s){3,}")
_WORD = re.compile(r"[a-z]{2,}")
_MIN_WORDS = 3
# Table of authorities / contents. Masked, never deleted: offsets must keep
# addressing the original document.
_TABLE_HEADING = re.compile(
    r"^[ \t]*TABLE\s+OF\s+(AUTHORITIES|CONTENTS)[ \t]*$", re.IGNORECASE | re.MULTILINE
)
# Consecutive table lines may be this far apart (entries wrap across lines).
_TABLE_LINE_GAP = 8
# CM/ECF page stamp repeated at every page break of a filed document.
_ECF_STAMP = re.compile(
    r"^.*\bCase\s+(?:No\.\s*)?\d+:\d+-[a-z]{2}-\d+\S*.*?(?:\bpg|\bPage)\s*\d+\s*of\s*\d+.*$",
    re.IGNORECASE | re.MULTILINE,
)
# A candidate that ends like this is the front of a caption, not a sentence.
_CAPTION_FRAGMENT = re.compile(r"(?:\bv\.|\bex\s+rel\.|\bIn\s+re|\bon\s+behalf\s+of)\s*$")
# A Bluebook introductory signal between the proposition and the citation. It is
# kept, separately: "See" (indirect support) is not the same claim as no signal.
_SIGNAL = re.compile(
    r"(?:\b(?:[Ss]ee,?\s+e\.g\.,|[Ss]ee\s+also|[Bb]ut\s+see|[Bb]ut\s+cf\.|[Ss]ee\s+generally"
    r"|[Cc]ompare|[Cc]f\.|[Aa]ccord|[Ss]ee|[Ee]\.g\.,|[Cc]ontra))\s*$"
)


@dataclass
class Quote:
    text: str
    span: tuple[int, int]
    raw_text: str
    attribution_status: str = "unattributed"
    attribution_basis: str | None = None
    authority_id: str | None = None
    candidate_authorities: list[str] = field(default_factory=list)
    pin_cite: str | None = None
    citation_span: tuple[int, int] | None = None
    # "printed": the pin appears at the citation. "inherited_from_id": a bare
    # Id. repeats the previous citation's page, as Bluebook reads it.
    pin_basis: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# "Id. at 25-26" / "Id. at 25–26": a record pin, kept whole.
_ID_PIN = re.compile(r"\s*,?\s*at\s+(\d{1,4}(?:\s*[-–]\s*\d{1,4})?)")


@dataclass(frozen=True)
class Proposition:
    """The sentence a citation is used for, as an exact slice of the source.

    ``text == source[span[0]:span[1]]`` always holds. Nothing is normalized or
    rewritten, so the proposition carries the same offsets the citations use.
    """

    text: str
    span: tuple[int, int]
    signal: str | None = None


@dataclass
class CitationGroup:
    """One case: the full citation, plus everything that points back to it."""

    id: str
    header: Citation
    children: list[Citation] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)
    # One entry per occurrence, aligned with (header, *children).
    occurrence_propositions: list[Proposition | None] = field(default_factory=list)
    layout_regions: list[LayoutRegion] = field(default_factory=list)

    @property
    def proposition(self) -> tuple[Citation, Proposition] | None:
        """The first occurrence, in document order, used for a real sentence.

        The header is usually a table-of-authorities entry, which is used for
        nothing; the body occurrences carry the propositions.
        """
        for citation, prop in zip((self.header, *self.children), self.occurrence_propositions):
            if prop is not None:
                return citation, prop
        return None

    @property
    def case_name(self) -> str | None:
        # The first citation may name the case only in passing ("Hassan, 742
        # F.3d 104, 133"); a later full citation to it carries the caption.
        for citation in (self.header, *self.children):
            if citation.kind == "FullCaseCitation" and citation.plaintiff and citation.defendant:
                return f"{citation.plaintiff} v. {citation.defendant}"
        # A non-adversarial caption: "In re Veal", "Ex parte Young".
        return self.header.case_name or None

    def as_dict(self) -> dict[str, Any]:
        chosen = self.proposition
        return {
            "id": self.id,
            "caseName": self.case_name,
            "header": self.header.as_dict(),
            "children": [c.as_dict() for c in self.children],
            "quotes": [q.as_dict() for q in self.quotes],
            "proposition": chosen[1].text if chosen else None,
            "propositionSpan": list(chosen[1].span) if chosen else None,
            "propositionCitationSpan": list(chosen[0].span) if chosen else None,
            "propositionSignal": chosen[1].signal if chosen else None,
            "occurrencePropositions": [
                {
                    "citationSpan": list(citation.span),
                    "layout": _layout_kind(citation, self.layout_regions),
                    "proposition": prop.text if prop else None,
                    "propositionSpan": list(prop.span) if prop else None,
                    "signal": prop.signal if prop else None,
                }
                for citation, prop in zip(
                    (self.header, *self.children), self.occurrence_propositions
                )
            ],
        }


def _layout_kind(citation: Citation, regions: list[LayoutRegion]) -> str | None:
    for region in regions:
        if region.span[0] <= citation.span[0] < region.span[1]:
            return region.kind
    return None


@dataclass
class AuthorityGroup:
    """One statute, regulation, rule or constitutional provision.

    Repeated references to the same provision cascade under the first one, the
    same shape the case law groups use.
    """

    id: str
    category: str
    source: str
    header: Authority
    children: list[Authority] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "source": self.source,
            "header": self.header.as_dict(),
            "children": [c.as_dict() for c in self.children],
            "quotes": [q.as_dict() for q in self.quotes],
        }


def _occurrence_dict(citation: Citation | RecordCite) -> dict[str, Any]:
    if isinstance(citation, RecordCite):
        return {
            "kind": "RecordCitation",
            "recordKind": citation.kind,
            "label": citation.label,
            "text": citation.text,
            "span": list(citation.span),
            "pin_cite": citation.pin,
        }
    return citation.as_dict()


@dataclass
class RecordGroup:
    """One document in the case record, and every citation that points at it.

    ``Doc. No. 80 at 26`` and each ``Id.`` that follows it refer to the same
    filing. Verifying these needs that document, not a published opinion, so
    they are kept apart from the case-law groups.
    """

    id: str
    kind: str
    label: str
    source_id: str
    header: RecordCite
    children: list[Citation | RecordCite] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)
    occurrence_propositions: list[Proposition | None] = field(default_factory=list)
    layout_regions: list[LayoutRegion] = field(default_factory=list)

    @property
    def proposition(self) -> tuple[Citation | RecordCite, Proposition] | None:
        for citation, prop in zip((self.header, *self.children), self.occurrence_propositions):
            if prop is not None:
                return citation, prop
        return None

    def as_dict(self) -> dict[str, Any]:
        chosen = self.proposition
        occurrences = (self.header, *self.children)
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "sourceId": self.source_id,
            "header": _occurrence_dict(self.header),
            "children": [_occurrence_dict(c) for c in self.children],
            "quotes": [q.as_dict() for q in self.quotes],
            "proposition": chosen[1].text if chosen else None,
            "propositionSpan": list(chosen[1].span) if chosen else None,
            "propositionCitationSpan": list(chosen[0].span) if chosen else None,
            "propositionSignal": chosen[1].signal if chosen else None,
            "occurrencePropositions": [
                {
                    "citationSpan": list(citation.span),
                    "layout": _layout_kind(citation, self.layout_regions),
                    "proposition": prop.text if prop else None,
                    "propositionSpan": list(prop.span) if prop else None,
                    "signal": prop.signal if prop else None,
                }
                for citation, prop in zip(occurrences, self.occurrence_propositions)
            ],
        }


# Display order for the authority sections beneath the case law.
CATEGORY_ORDER = ("statute", "regulation", "rule", "constitution")


@dataclass(frozen=True)
class LayoutRegion:
    """A span of the document that is layout, not argument."""

    kind: str
    span: tuple[int, int]


def find_table_regions(text: str) -> list[LayoutRegion]:
    """Tables of authorities and contents, from heading to last leader line."""
    regions: list[LayoutRegion] = []
    for heading in _TABLE_HEADING.finditer(text):
        kind = "table_of_" + heading.group(1).lower()
        end = heading.end()
        lines_since_leader = 0
        position = heading.end()
        while lines_since_leader <= _TABLE_LINE_GAP:
            newline = text.find("\n", position + 1)
            line_end = len(text) if newline < 0 else newline
            if _DOT_LEADER.search(text, position, line_end):
                end = line_end
                lines_since_leader = 0
            else:
                lines_since_leader += 1
            if newline < 0:
                break
            position = newline
        regions.append(LayoutRegion(kind=kind, span=(heading.start(), end)))
    return regions


@dataclass
class ExtractionResult:
    text: str
    groups: list[CitationGroup] = field(default_factory=list)
    orphans: list[Citation] = field(default_factory=list)
    authorities: list[AuthorityGroup] = field(default_factory=list)
    unattributed_quotes: list[Quote] = field(default_factory=list)
    layout_regions: list[LayoutRegion] = field(default_factory=list)
    records: list[RecordGroup] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        authority_cites = sum(1 + len(a.children) for a in self.authorities)
        linked_quotes = sum(len(g.quotes) for g in self.groups) + sum(
            len(a.quotes) for a in self.authorities
        )
        ambiguous_quotes = sum(
            q.attribution_status == "ambiguous" for q in self.unattributed_quotes
        )
        unlinked_quotes = len(self.unattributed_quotes) - ambiguous_quotes
        return {
            "text": self.text,
            "groups": [g.as_dict() for g in self.groups],
            "orphans": [c.as_dict() for c in self.orphans],
            "authorities": [a.as_dict() for a in self.authorities],
            "unattributedQuotes": [q.as_dict() for q in self.unattributed_quotes],
            "layoutRegions": [
                {"kind": r.kind, "span": list(r.span)} for r in self.layout_regions
            ],
            "records": [r.as_dict() for r in self.records],
            "stats": {
                "groups": len(self.groups),
                "citations": sum(1 + len(g.children) for g in self.groups)
                + len(self.orphans),
                "quotes": linked_quotes + len(self.unattributed_quotes),
                "linkedQuotes": linked_quotes,
                "ambiguousQuotes": ambiguous_quotes,
                "unattributedQuotes": unlinked_quotes,
                "flagged": sum(
                    1 for g in self.groups for c in [g.header, *g.children] if c.flags
                )
                + sum(1 for c in self.orphans if c.flags),
                "authorities": len(self.authorities),
                "authorityCitations": authority_cites,
            },
        }


# A defined term is quoted, but it quotes nothing: ("Plaintiff"),
# (collectively, "Defendants"), (the "City"). Checked against a source it can
# only ever "pass" trivially, which inflates the count of verified quotations.
_DEFINED_TERM_LEAD = re.compile(
    r"\(\s*(?:(?:collectively|together|jointly|individually|hereinafter|each)\s*,?\s*)?"
    r"(?:the\s+)?$",
    re.IGNORECASE,
)
_DEFINED_TERM_TRAIL = re.compile(r"\s*\)")

# What is left of a "quotation" once citations and pin words are removed. A span
# such as "(Doc. 42 at p. 12)." is the gap between two quotations whose marks were
# paired wrongly, not a quotation; checking it can only produce a false failure.
_CITATION_RESIDUE = re.compile(r"\b(?:at|pp?|para|paras|id|see|also|and)\b\.?", re.IGNORECASE)


def _is_defined_term(text: str, start: int, end: int, body: str) -> bool:
    if len(body.split()) > 4:
        return False
    lead = text[max(0, start - 40) : start]
    return bool(_DEFINED_TERM_LEAD.search(lead) and _DEFINED_TERM_TRAIL.match(text, end))


def _is_citation_only(body: str) -> bool:
    rest = body
    for cite in extract_record_cites(body):
        rest = rest.replace(cite.text, " ")
    rest = _CITATION_RESIDUE.sub(" ", rest)
    return not re.search(r"[A-Za-z]{2,}", rest)


def _is_shouted_label(body: str) -> bool:
    """A sign, stamp or disposition in capitals: "NO TRESPASSING", "EXONERATED".

    Opinions do not quote themselves in capitals; these are record words, and
    checking them against case law can only produce a false failure.
    """
    letters = re.sub(r"[^A-Za-z]", "", body)
    return len(body.split()) <= 4 and len(letters) >= 2 and letters.isupper()


def _find_quotes(text: str) -> list[tuple[int, int, str]]:
    spans = []
    for m in _QUOTE.finditer(text):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        body = " ".join(body.split())
        if (_is_defined_term(text, m.start(), m.end(), body) or _is_citation_only(body)
                or _is_shouted_label(body)):
            continue
        spans.append((m.start(), m.end(), body))
    return spans


# Between a citation and a quotation inside that citation's own parenthetical:
# the rest of the cite (pin, court and year), then an opening parenthesis and
# at most a short lead-in -- "(noting that ", "(quoting ", "(holding ".
#   Mata v. City of Farmington, 798 F.Supp.2d 1215, 1227 (D.N.M. 2011)
#   ("The prejudice must be unfair ...")
_PARENTHETICAL_GAP = re.compile(
    r"[\s,]*(?:at\s+)?(?:[\d*\u2013\-\s,n.]*)?(?:\([^()]{0,80}\)[\s,]*)*\([^()\"\u201c\u201d]{0,60}$"
)


def _parenthetical_owner(
    text: str, quote_start: int, records: list[Citation | Authority | RecordCite]
) -> Citation | Authority | RecordCite | None:
    """The citation whose explanatory parenthetical contains this quotation."""
    preceding = [c for c in records if c.span[1] <= quote_start and quote_start - c.span[1] <= 140]
    if not preceding:
        return None
    nearest = max(preceding, key=lambda c: c.span[1])
    gap = text[nearest.span[1] : quote_start]
    return nearest if _PARENTHETICAL_GAP.fullmatch(gap) else None


# A sentence ends at . ! or ? (after any closing quote or bracket) followed by
# whitespace and a capital. Reporter abbreviations ("F.3d", "U.S.", "v.") are
# followed by a digit or a lower-case word, so they do not end a sentence.
_SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s+(?=[A-Z\u201c\"])")
# A citation sentence opens with a signal or with the case name itself. A
# sentence opening "In Doe v. United States, ..." is prose about that case.
_TEXTUAL_OPENING = re.compile(r"\s*In\s+(?!re\b)")
_SAME_SENTENCE_REACH = 400
# A sentence of the filing's own prose: an end of sentence followed by a word
# that opens argument rather than a citation ("See", a case name, "Under").
_PROSE_SENTENCE = re.compile(
    r"[.!?][\"'\u201d\u2019)\]]*\s+(?=(?:The|This|That|These|Those|It|Its|He|She|They|We|I|"
    r"His|Her|Their|Our|Plaintiffs?|Defendants?|Officers?|Here|There|Thus|Therefore|"
    r"Accordingly|Moreover|Further|Furthermore|Indeed|However|Because|Such|No|Nor)\b)"
)


def _same_sentence_owner(
    text: str, quote_start: int, quote_end: int, records: list[Citation | Authority | RecordCite]
) -> Citation | Authority | RecordCite | None:
    """The earlier citation, when the quotation is its sentence's own language.

        In Ashcroft v. Iqbal, 556 U.S. 662 (2009), the Supreme Court held that
        ... need not accept "threadbare recitals of the elements" of a claim.
        The Court also held ... In Doe v. United States, 419 F.3d 1058 ...

    The quote is Iqbal's; Doe begins a later sentence about a different case.
    A following citation still wins when it is the citation sentence for the
    quote ("... of a claim." See Doe, ... / Doe v. United States, 419 F.3d ...).
    """
    preceding = [c for c in records
                 if c.span[1] <= quote_start and quote_start - c.span[1] <= _SAME_SENTENCE_REACH]
    if not preceding:
        return None
    nearest = max(preceding, key=lambda c: c.span[1])
    if _SENTENCE_END.search(text, nearest.span[1], quote_start):
        return None
    following = [c for c in records if c.span[0] >= quote_end]
    if not following:
        return None
    after = min(following, key=lambda c: c.span[0])
    gap = text[quote_end : after.span[0]]
    ends = list(_SENTENCE_END.finditer(gap))
    if not ends:
        return None
    if len(ends) >= 2 or _TEXTUAL_OPENING.match(gap, ends[0].end()):
        return nearest
    return None


def _attribute_quote(
    quote_start: int,
    quote_end: int,
    records: list[Citation | Authority | RecordCite],
    text: str = "",
) -> tuple[Citation | Authority | RecordCite | None, str | None]:
    """Attach a quotation to a citation.

    A quotation inside a citation's own parenthetical belongs to that citation.
    Otherwise legal writing puts the quotation before its citation, so a
    following citation wins; a preceding one is accepted only at close range.
    """
    if text:
        owner = _parenthetical_owner(text, quote_start, records)
        if owner is not None:
            return owner, "own_parenthetical"
        owner = _same_sentence_owner(text, quote_start, quote_end, records)
        if owner is not None:
            return owner, "same_sentence_preceding"

    following = [
        c
        for c in records
        if c.span[0] >= quote_end and c.span[0] - quote_end <= _QUOTE_FORWARD
    ]
    if following and text:
        # Two sentences of the filing's own argument between a quotation and
        # the next citation: that citation is for the argument, not the quote.
        nearest_start = min(c.span[0] for c in following)
        if len(_PROSE_SENTENCE.findall(text, max(quote_start, quote_end - 3), nearest_start)) >= 2:
            following = []
    if following:
        target = min(following, key=lambda c: c.span[0])
        if isinstance(target, RecordCite):
            basis = "following_record"
        elif isinstance(target, Authority):
            basis = "following_authority"
        else:
            basis = {
                "FullCaseCitation": "following_full_citation",
                "ShortCaseCitation": "following_short_citation",
                "IdCitation": "following_id",
                "SupraCitation": "following_supra",
                "ReferenceCitation": "following_reference",
            }.get(target.kind, "following_citation")
        return target, basis

    preceding = [
        c
        for c in records
        if c.span[1] <= quote_start and quote_start - c.span[1] <= _QUOTE_BACKWARD
    ]
    if preceding:
        target = max(preceding, key=lambda c: c.span[1])
        if isinstance(target, RecordCite):
            basis = "preceding_record"
        elif isinstance(target, Authority):
            basis = "preceding_authority"
        else:
            basis = "preceding_citation"
        return target, basis
    return None, None


def _group_authorities(text: str) -> list[AuthorityGroup]:
    """Cluster statutes, rules and regulations by the provision they cite.

    Grouping key is CiteURL's normalised name, so "42 U.S.C. § 1983" and a later
    bare "§ 1983" land together. Ordering is by category, then by first
    appearance, so the pane reads statutes, regulations, rules, constitutions.
    """
    found = extract_authorities(text)
    if not found:
        return []

    # CiteURL binds a short form to the nearest preceding citation of any
    # template, so "Section 1983" following a C.F.R. cite is reported as
    # "28 C.F.R. § 1983". Re-bind a short form to the earlier full citation that
    # shares its section number when exactly one such citation exists.
    full_by_section: dict[str, list[Authority]] = {}
    for item in found:
        section = str(item.tokens.get("section") or "")
        if section and not item.is_shortform:
            full_by_section.setdefault(section, []).append(item)

    def bucket_key(item: Authority) -> tuple[str, str]:
        section = str(item.tokens.get("section") or "")
        if item.is_shortform and section:
            candidates = [
                c for c in full_by_section.get(section, []) if c.span[0] < item.span[0]
            ]
            if len(candidates) == 1:
                anchor = candidates[0]
                return (anchor.category, (anchor.name or anchor.text).strip().lower())
        return (item.category, (item.name or item.text).strip().lower())

    buckets: dict[tuple[str, str], list[Authority]] = {}
    for item in found:
        buckets.setdefault(bucket_key(item), []).append(item)

    groups: list[AuthorityGroup] = []
    for (category, _), members in buckets.items():
        members.sort(key=lambda a: a.span[0])
        groups.append(
            AuthorityGroup(
                id="",
                category=category,
                source=members[0].source,
                header=members[0],
                children=members[1:],
            )
        )

    groups.sort(
        key=lambda g: (
            CATEGORY_ORDER.index(g.category)
            if g.category in CATEGORY_ORDER
            else len(CATEGORY_ORDER),
            g.header.span[0],
        )
    )
    for index, group in enumerate(groups):
        group.id = f"a{index}"
    return groups


def _caption_start(text: str, lo: int, start: int, names: list[str]) -> int:
    """Where the caption ending immediately before ``start`` begins.

    A name counts only if nothing but spaces and commas separates it from the
    citation, so a party mentioned earlier in the prose is never mistaken for
    the caption. Whitespace inside a name is matched loosely because PDF text
    layers break lines anywhere. The earliest qualifying match wins, so a full
    "Plaintiff v. Defendant" caption beats its defendant alone.
    """
    anchor = start
    for name in names:
        words = name.split()
        if not words:
            continue
        pattern = re.compile(r"\s+".join(map(re.escape, words)) + r"[\s,]*$")
        match = pattern.search(text, lo, start)
        if match and match.start() < anchor:
            anchor = match.start()
    return anchor


def _proposition(
    text: str,
    citation: Citation,
    boundaries: list[int],
    names: list[str],
    regions: list[LayoutRegion] = (),
) -> Proposition | None:
    """The sentence immediately before a citation (and its caption, if any).

    Bounded below by the end of the nearest earlier citation and whatever
    trails it, so a proposition never absorbs another authority's text.
    ``boundaries`` holds the end offset of every extracted citation. Layout --
    table-of-authorities dot leaders, heading lines -- is not a proposition.
    """
    start = citation.span[0]
    if any(r.span[0] <= start < r.span[1] for r in regions):
        return None  # a table entry is used for nothing
    floor = max((end for end in boundaries if end <= start), default=0)
    floor = max([floor, *(r.span[1] for r in regions if r.span[1] <= start)])
    after_citation = floor > 0
    floor = max(floor, start - _PROP_WINDOW)

    own = [getattr(citation, attr, None)
           for attr in ("case_name", "antecedent", "plaintiff", "defendant")]
    candidates = [n for n in (*own, *names) if n]
    anchor = _caption_start(text, max(floor, start - _CAPTION_WINDOW), start, candidates)

    if after_citation:
        tail = _CITATION_TAIL.match(text, floor, anchor)
        if tail:
            floor = tail.end()

    window = text[floor:anchor]
    # A page break inside the window: start after the last CM/ECF stamp.
    stamps = list(_ECF_STAMP.finditer(window))
    if stamps:
        floor += stamps[-1].end()
        window = text[floor:anchor]
    fragment = _CAPTION_FRAGMENT.search(window)
    while fragment:
        # "County of Sacramento v." / "Holland ex rel.": the caption started
        # earlier than the matched name. Back the anchor up to that sentence.
        cut = max((m.end() for m in _SENT_END.finditer(window, 0, fragment.start())), default=0)
        anchor = floor + cut
        window = text[floor:anchor]
        fragment = _CAPTION_FRAGMENT.search(window)
    if window.lstrip().startswith("("):
        # "(quoting X, ...)" / "(citing X)": nested in another citation's
        # parenthetical, it supports that citation's proposition, not its own.
        return None

    last_end = max((m.end() for m in _SENT_END.finditer(window)), default=None)
    lead_in = window[last_end:].strip() if last_end is not None else ""
    signal_only = (m := _SIGNAL.search(lead_in)) is not None and m.start() == 0
    if 0 < len(lead_in) < 20 and _WORD.search(lead_in) and not signal_only:
        # "Under United States v. Jones, ..." -- the citation sits inside its own
        # sentence, which continues after it. The preceding sentence is not the
        # proposition; report none rather than the wrong one.
        return None
    begin = 0
    leaders = list(_DOT_LEADER.finditer(window))
    if leaders:
        newline = window.find("\n", leaders[-1].end())
        begin = newline + 1 if newline >= 0 else len(window)
    for match in _SENT_END.finditer(window, begin):
        if len(window[match.end():].strip()) >= 20:
            begin = match.end()
    # Heading lines ("ARGUMENT", "II. STANDARD OF REVIEW") carry no lowercase.
    while True:
        newline = window.find("\n", begin)
        if newline < 0 or re.search(r"[a-z]", window[begin:newline]):
            break
        begin = newline + 1

    segment = window[begin:]
    lead = len(segment) - len(segment.lstrip())
    trail = len(segment) - len(segment.rstrip())
    s, e = floor + begin + lead, anchor - trail
    signal = None
    found_signal = _SIGNAL.search(text, s, e)
    if found_signal:
        signal = found_signal.group(0).strip()
        e = found_signal.start()
        e -= len(text[s:e]) - len(text[s:e].rstrip())
    if e - s <= 12:
        return None
    candidate = text[s:e]
    if _DOT_LEADER.search(candidate) or len(_WORD.findall(candidate)) < _MIN_WORDS:
        return None
    return Proposition(text=candidate, span=(s, e), signal=signal)


# Between the two halves of a parallel citation: an optional pin, then a comma.
#   Au v. Au, 63 Haw. 210, 214, 626 P.2d 173, 176 (1981)
_PARALLEL_GAP = re.compile(r"(?:,\s*\d+(?:\s*[-\u2013]\s*\d+)?(?:\s*n\.\s*\d+)?)?\s*,\s*")


def _merge_parallel_citations(text: str, groups: list[CitationGroup]) -> list[CitationGroup]:
    """One case cited in two reporters is one card, not two half-cards.

        First Nat'l Bank of Greeley v. Conway, 34 Colo. 372, 83 P. 361 (1905)

    eyecite reads two citations: the first carries the caption and no year, the
    second the year and no caption. The second joins the first's group as a
    child; each half lends the other what it lacks. Pins stay with their own
    reporter's citation.
    """
    owner = {id(c): g for g in groups for c in (g.header, *g.children)}
    fulls = sorted((c for g in groups for c in (g.header, *g.children)
                    if c.kind == "FullCaseCitation"), key=lambda c: c.span[0])
    for first, second in zip(fulls, fulls[1:]):
        if not _PARALLEL_GAP.fullmatch(text, first.span[1], second.span[0]):
            continue
        g_first, g_second = owner[id(first)], owner[id(second)]
        if g_first is g_second or second is not g_second.header:
            continue
        for attr in ("year", "court", "court_text"):
            if getattr(first, attr, None) is None:
                setattr(first, attr, getattr(second, attr, None))
        if not (second.plaintiff and second.defendant):
            second.plaintiff, second.defendant = first.plaintiff, first.defendant
            second.case_name = second.case_name or first.case_name
        g_first.children.extend((g_second.header, *g_second.children))
        g_first.children.sort(key=lambda c: c.span[0])
        for c in (g_second.header, *g_second.children):
            owner[id(c)] = g_first
        groups = [g for g in groups if g is not g_second]
    return groups


def _inside_parenthetical_of(outer: Citation, inner: Citation) -> bool:
    """Is ``inner`` cited inside ``outer``'s explanatory parenthetical?"""
    paren = outer.parenthetical or ""
    return bool(paren) and outer.span[1] <= inner.span[0] and " ".join(inner.text.split()) in paren


def _rebind_ids_past_parentheticals(
    timeline: list[Citation | Authority | RecordCite],
    case_owner: dict[int, CitationGroup],
) -> None:
    """Point an Id. at the cited case, not the case in its "(quoting ...)" parenthetical.

        Ashcroft v. Iqbal, 556 U.S. 662, 678 (2009) (quoting Bell Atlantic
        Corp. v. Twombly, 550 U.S. 544, 570 (2007)). ... Id. at 679.

    eyecite resolves that Id. to Twombly, the last case it read. An authority
    cited only in a parenthetical is never the antecedent of id., so the Id.
    (and every Id. chained after it) belongs to Iqbal.
    """
    rebound: dict[int, CitationGroup] = {}
    for position, citation in enumerate(timeline):
        if getattr(citation, "kind", None) != "IdCitation" or position == 0:
            continue
        previous = timeline[position - 1]
        target = rebound.get(id(previous))
        if target is None and position >= 2 and isinstance(previous, Citation):
            outer = timeline[position - 2]
            if isinstance(outer, Citation) and _inside_parenthetical_of(outer, previous):
                target = case_owner.get(id(outer))
        current = case_owner.get(id(citation))
        if target is None or current is None:
            continue
        rebound[id(citation)] = target
        if current is not target:
            current.children.remove(citation)
            target.children.append(citation)
            target.children.sort(key=lambda c: c.span[0])
            case_owner[id(citation)] = target


def _inherited_case_pins(
    timeline: list[Citation | Authority | RecordCite],
    case_owner: dict[int, CitationGroup],
) -> dict[int, tuple[str, str]]:
    """A bare Id. repeats the page of the citation it refers to.

        Iqbal, 556 U.S. at 678. ... "more than a sheer possibility." Id.

    That quotation is on page 678. The referent skips any citation inside the
    earlier citation's parenthetical, as in _rebind_ids_past_parentheticals.
    """
    pins: dict[int, tuple[str, str]] = {}
    for position, citation in enumerate(timeline):
        if getattr(citation, "kind", None) != "IdCitation" or position == 0:
            continue
        if citation.pin_cite:
            continue
        previous = timeline[position - 1]
        if (position >= 2 and isinstance(previous, Citation)
                and isinstance(timeline[position - 2], Citation)
                and _inside_parenthetical_of(timeline[position - 2], previous)):
            previous = timeline[position - 2]
        group = case_owner.get(id(citation))
        if group is None or case_owner.get(id(previous)) is not group:
            continue
        if id(previous) in pins:
            pins[id(citation)] = (pins[id(previous)][0], "inherited_from_id")
        elif getattr(previous, "pin_cite", None):
            page = re.sub(r"^at\s+", "", previous.pin_cite, flags=re.IGNORECASE)
            pins[id(citation)] = (page, "inherited_from_id")
    return pins


def group_citations(text: str) -> ExtractionResult:
    """Extract citations and cluster them under their full citation."""
    pairs = extract_pairs(text)
    authorities = _group_authorities(text)

    by_cite: dict[int, Citation] = {id(cite): rec for cite, rec in pairs}
    records = [rec for _, rec in pairs]

    resolved = resolve_citations([cite for cite, _ in pairs]) if pairs else {}

    groups: list[CitationGroup] = []
    grouped_ids: set[int] = set()

    for members in resolved.values():
        member_records = [by_cite[id(m)] for m in members if id(m) in by_cite]
        if not member_records:
            continue
        headers = [r for r in member_records if r.kind == "FullCaseCitation"]
        if not headers:
            continue
        header = min(headers, key=lambda r: r.span[0])
        children = sorted(
            (r for r in member_records if r is not header),
            key=lambda r: r.span[0],
        )
        groups.append(
            CitationGroup(id=f"g{len(groups)}", header=header, children=children)
        )
        grouped_ids.update(id(r) for r in member_records)

    groups = _merge_parallel_citations(text, groups)
    groups.sort(key=lambda g: g.header.span[0])
    for i, g in enumerate(groups):
        g.id = f"g{i}"
    regions = find_table_regions(text)

    orphans = sorted(
        (r for r in records if id(r) not in grouped_ids),
        key=lambda r: r.span[0],
    )

    # The case record: "Doc. No. 80 at 26", "SAC para 45", "Policy 1010.4.2".
    record_cites = extract_record_cites(text)
    record_groups: dict[str, RecordGroup] = {}
    owner_of_record: dict[int, RecordGroup] = {}
    record_pins: dict[int, tuple[str, str]] = {
        id(cite): (cite.pin, "printed") for cite in record_cites if cite.pin
    }
    for cite in record_cites:
        group = record_groups.get(cite.source_id)
        if group is None:
            group = RecordGroup(id=f"r{len(record_groups)}", kind=cite.kind, label=cite.label,
                                source_id=cite.source_id, header=cite)
            record_groups[cite.source_id] = group
        else:
            group.children.append(cite)
        owner_of_record[id(cite)] = group

    # eyecite resolves Id. to the last *case* it saw and knows nothing of the
    # record, so "Doc. No. 80 at 26 ... Id." lands on whatever case came
    # before. An Id. refers to the citation immediately preceding it, of any
    # kind; when that is the record, the Id. belongs to the record.
    authority_records: list[Authority] = [
        a for group in authorities for a in (group.header, *group.children)
    ]
    # CiteURL also reports each "Id." as a statute short form with the same
    # span; keep one entry per span, preferring the record, then case law.
    def rank(citation) -> int:
        return 0 if isinstance(citation, RecordCite) else 1 if isinstance(citation, Citation) else 2

    by_span: dict[tuple[int, int], Citation | Authority | RecordCite] = {}
    for citation in (*records, *authority_records, *record_cites):
        key = tuple(citation.span)
        if key not in by_span or rank(citation) < rank(by_span[key]):
            by_span[key] = citation
    timeline = sorted(by_span.values(), key=lambda c: c.span[0])
    case_owner = {id(r): g for g in groups for r in (g.header, *g.children)}
    for position, citation in enumerate(timeline):
        if getattr(citation, "kind", None) != "IdCitation":
            continue
        previous = timeline[position - 1] if position else None
        owner = owner_of_record.get(id(previous)) if previous is not None else None
        if owner is None:
            continue
        case_group = case_owner.pop(id(citation), None)
        if case_group is not None:
            case_group.children.remove(citation)
        elif citation in orphans:
            orphans.remove(citation)
        owner.children.append(citation)
        owner_of_record[id(citation)] = owner
        printed = _ID_PIN.match(text, citation.span[1])
        if printed:
            record_pins[id(citation)] = (printed.group(1), "printed")
        elif id(previous) in record_pins:
            record_pins[id(citation)] = (record_pins[id(previous)][0], "inherited_from_id")

    _rebind_ids_past_parentheticals(timeline, case_owner)
    record_pins.update(_inherited_case_pins(timeline, case_owner))

    ordered_records = list(record_groups.values())
    for group in ordered_records:
        group.children.sort(key=lambda c: c.span[0])

    boundaries = [c.span[1] for c in timeline]
    for g in groups:
        names = [n for n in (g.case_name, g.header.case_name, g.header.plaintiff,
                             g.header.defendant) if n]
        g.layout_regions = regions
        g.occurrence_propositions = [
            _proposition(text, citation, boundaries, names, regions)
            for citation in (g.header, *g.children)
        ]
    for group in ordered_records:
        group.layout_regions = regions
        group.occurrence_propositions = [
            _proposition(text, citation, boundaries, [], regions)
            for citation in (group.header, *group.children)
        ]

    # Attribute quotations to whichever citation they support.
    owner_of: dict[int, CitationGroup | AuthorityGroup | RecordGroup] = {}
    for g in groups:
        for rec in (g.header, *g.children):
            owner_of[id(rec)] = g
    for authority_group in authorities:
        for authority in (authority_group.header, *authority_group.children):
            owner_of[id(authority)] = authority_group
    owner_of.update(owner_of_record)
    attribution_records = [*records, *authority_records, *record_cites]

    unattributed_quotes: list[Quote] = []
    for q_start, q_end, body in _find_quotes(text):
        quote = Quote(
            text=body,
            span=(q_start, q_end),
            raw_text=text[q_start:q_end],
        )
        target, basis = _attribute_quote(q_start, q_end, attribution_records, text)
        if target is None:
            unattributed_quotes.append(quote)
            continue
        owner = owner_of.get(id(target))
        if owner is None:
            unattributed_quotes.append(quote)
            continue
        quote.attribution_status = "linked"
        quote.attribution_basis = basis
        quote.authority_id = owner.id
        quote.citation_span = target.span
        if id(target) in record_pins:
            quote.pin_cite, quote.pin_basis = record_pins[id(target)]
        else:
            pin_cite = getattr(target, "pin_cite", None) or getattr(target, "pin", None)
            quote.pin_cite = (
                re.sub(r"^at\s+", "", pin_cite, flags=re.IGNORECASE) if pin_cite else None
            )
            quote.pin_basis = "printed" if quote.pin_cite else None
        owner.quotes.append(quote)

    for g in groups:
        g.quotes.sort(key=lambda q: q.span[0])
    for authority_group in authorities:
        authority_group.quotes.sort(key=lambda q: q.span[0])
    for group in ordered_records:
        group.quotes.sort(key=lambda q: q.span[0])

    return ExtractionResult(
        text=text,
        layout_regions=regions,
        records=ordered_records,
        groups=groups,
        orphans=orphans,
        authorities=authorities,
        unattributed_quotes=unattributed_quotes,
    )
