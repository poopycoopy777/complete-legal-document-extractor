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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Proposition:
    """The sentence a citation is used for, as an exact slice of the source.

    ``text == source[span[0]:span[1]]`` always holds. Nothing is normalized or
    rewritten, so the proposition carries the same offsets the citations use.
    """

    text: str
    span: tuple[int, int]


@dataclass
class CitationGroup:
    """One case: the full citation, plus everything that points back to it."""

    id: str
    header: Citation
    children: list[Citation] = field(default_factory=list)
    quotes: list[Quote] = field(default_factory=list)
    proposition: Proposition | None = None

    @property
    def case_name(self) -> str | None:
        if self.header.plaintiff and self.header.defendant:
            return f"{self.header.plaintiff} v. {self.header.defendant}"
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "caseName": self.case_name,
            "header": self.header.as_dict(),
            "children": [c.as_dict() for c in self.children],
            "quotes": [q.as_dict() for q in self.quotes],
            "proposition": self.proposition.text if self.proposition else None,
            "propositionSpan": list(self.proposition.span) if self.proposition else None,
        }


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


# Display order for the authority sections beneath the case law.
CATEGORY_ORDER = ("statute", "regulation", "rule", "constitution")


@dataclass
class ExtractionResult:
    text: str
    groups: list[CitationGroup] = field(default_factory=list)
    orphans: list[Citation] = field(default_factory=list)
    authorities: list[AuthorityGroup] = field(default_factory=list)
    unattributed_quotes: list[Quote] = field(default_factory=list)

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


def _find_quotes(text: str) -> list[tuple[int, int, str]]:
    spans = []
    for m in _QUOTE.finditer(text):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        spans.append((m.start(), m.end(), " ".join(body.split())))
    return spans


def _attribute_quote(
    quote_start: int, quote_end: int, records: list[Citation | Authority]
) -> tuple[Citation | Authority | None, str | None]:
    """Attach a quotation to a citation.

    Legal writing puts the quotation before its citation, so a following
    citation wins; a preceding one is accepted only at close range.
    """
    following = [
        c
        for c in records
        if c.span[0] >= quote_end and c.span[0] - quote_end <= _QUOTE_FORWARD
    ]
    if following:
        target = min(following, key=lambda c: c.span[0])
        if isinstance(target, Authority):
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
        basis = (
            "preceding_authority"
            if isinstance(target, Authority)
            else "preceding_citation"
        )
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


def _proposition(text: str, header: Citation, boundaries: list[int]) -> Proposition | None:
    """The sentence immediately before a full citation's caption.

    Bounded below by the end of the nearest earlier citation and whatever
    trails it, so a proposition never absorbs another authority's text.
    ``boundaries`` holds the end offset of every extracted citation.
    """
    start = header.span[0]
    floor = max((end for end in boundaries if end <= start), default=0)
    after_citation = floor > 0
    floor = max(floor, start - _PROP_WINDOW)

    anchor = start
    lo = max(floor, start - _CAPTION_WINDOW)
    for name in (header.case_name, header.plaintiff):
        if name:
            found = text.rfind(name, lo, start)
            if found >= 0:
                anchor = found
                break

    if after_citation:
        tail = _CITATION_TAIL.match(text, floor, anchor)
        if tail:
            floor = tail.end()

    window = text[floor:anchor]
    begin = 0
    for match in _SENT_END.finditer(window):
        if len(window[match.end():].strip()) >= 20:
            begin = match.end()
    segment = window[begin:]
    lead = len(segment) - len(segment.lstrip())
    trail = len(segment) - len(segment.rstrip())
    s, e = floor + begin + lead, anchor - trail
    if e - s <= 12:
        return None
    return Proposition(text=text[s:e], span=(s, e))


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

    groups.sort(key=lambda g: g.header.span[0])
    boundaries = [r.span[1] for r in records] + [
        a.span[1] for group in authorities for a in (group.header, *group.children)
    ]
    for i, g in enumerate(groups):
        g.id = f"g{i}"
        g.proposition = _proposition(text, g.header, boundaries)

    orphans = sorted(
        (r for r in records if id(r) not in grouped_ids),
        key=lambda r: r.span[0],
    )

    # Attribute quotations to whichever citation they support.
    owner_of: dict[int, CitationGroup | AuthorityGroup] = {}
    for g in groups:
        for rec in (g.header, *g.children):
            owner_of[id(rec)] = g
    authority_records: list[Authority] = []
    for authority_group in authorities:
        for authority in (authority_group.header, *authority_group.children):
            owner_of[id(authority)] = authority_group
            authority_records.append(authority)
    attribution_records: list[Citation | Authority] = [*records, *authority_records]

    unattributed_quotes: list[Quote] = []
    for q_start, q_end, body in _find_quotes(text):
        quote = Quote(
            text=body,
            span=(q_start, q_end),
            raw_text=text[q_start:q_end],
        )
        target, basis = _attribute_quote(q_start, q_end, attribution_records)
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
        pin_cite = getattr(target, "pin_cite", None)
        quote.pin_cite = (
            re.sub(r"^at\s+", "", pin_cite, flags=re.IGNORECASE) if pin_cite else None
        )
        owner.quotes.append(quote)

    for g in groups:
        g.quotes.sort(key=lambda q: q.span[0])
    for authority_group in authorities:
        authority_group.quotes.sort(key=lambda q: q.span[0])

    return ExtractionResult(
        text=text,
        groups=groups,
        orphans=orphans,
        authorities=authorities,
        unattributed_quotes=unattributed_quotes,
    )
