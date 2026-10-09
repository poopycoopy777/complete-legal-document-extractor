"""Citations to the record and to documentary evidence.

A brief quotes three kinds of thing, and only one of them is case law:

* the record in its own case -- ``Doc. No. 80 at 26``, ``SAC para 45``;
* documentary evidence -- ``Policy 1010.4.2``, exhibits, internal reports;
* published opinions.

The extractor previously saw only the third, so every quotation was bound to
the nearest *case* citation whether or not the case was its source. In the filed
Third Amended Complaint that attributed three quotations from the Pueblo Police
Department policy manual to Pembaur v. City of Cincinnati, which then reported
them as quotations absent from Pembaur. The answer was right and the question
was wrong, and that is the failure mode that teaches a reader to ignore alarms.

Recognising these citations does not verify them -- that needs the document they
point at -- but it lets a quotation attach to the source it actually names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "Doc. No. 80 at 26", "Doc. 54 at 11-12", "ECF No. 61". The pin is optional and
# is kept whole: a quotation cited "at 25-26" may sit on either page, and a
# verifier needs the range to say so.
_DOCKET = re.compile(
    r"\b(?:Doc\.?|Document|ECF)\s*(?:No\.?\s*)?(\d{1,4})(?:\s*-\s*\d{1,3})?"
    r"(?:\s*,?\s*at\s+(?:pp?\.\s*)?(\d{1,4}(?:\s*[-\u2013]\s*\d{1,4})?))?",
    re.IGNORECASE,
)

# "SAC para 45", "Compl. paras 65, 67, 69-70". The whole paragraph list is the
# pin: the quotation may sit in any paragraph it names.
_PLEADING = re.compile(
    r"\b(SAC|TAC|FAC|Compl\.?|Complaint|Am\.?\s*Compl\.?)\s*¶{1,2}\s*"
    r"(\d{1,4}(?:\s*(?:,|[-\u2013])\s*\d{1,4})*)",
    re.IGNORECASE,
)

# "App. 58", "App. 41-43", "App. at 58", "Appellant's App. 136-38".
# The appendix is a single document; the page number is a pin cite.
_APPENDIX = re.compile(
    r"\b(?:(?:Appellant|Appellee|Petitioner|Respondent)(?:['’]s)?\s+)?"
    r"App\.?\s*(?:at\s+)?(?:pp?\.\s*)?(\d{1,4}(?:\s*[-–]\s*\d{1,4})?)"
    r"(?:\s*,\s*(\d{1,4}(?:\s*[-–]\s*\d{1,4})?))*",
    re.IGNORECASE,
)

# Reporter names that end in the word "App.": Colorado, North Carolina,
# Illinois, Indiana, and the Florida District Courts of Appeal. "39 Colo. App.
# 306" is a citation to the Colorado Court of Appeals reports, not to an
# appendix, so matching it made a brief that cites no appendix look as though it
# cites one -- and took the parallel reporter's volume as the appendix page.
# A genuine appendix cite never follows a reporter token like this.
#
# "App." may itself be the tail of a longer reporter: "Fla. Dist. Ct. App.".
# The run of abbreviation tokens immediately before it names that reporter, and
# it starts with a jurisdiction or court word.
_REPORTER_TAILS = frozenset({
    "ala", "ariz", "ark", "cal", "colo", "conn", "del", "fla", "ga", "hawaii",
    "idaho", "ill", "ind", "iowa", "kan", "ky", "la", "md", "mass", "mich",
    "minn", "miss", "mo", "mont", "neb", "nev", "nh", "nj", "nm", "ny", "nc",
    "nd", "ohio", "okla", "or", "pa", "ri", "sc", "sd", "tenn", "tex", "utah",
    "vt", "va", "wash", "wva", "wis", "wyo", "dc", "pr", "guam", "nmariana",
    "virgin", "dist", "ct", "app", "misc", "supp", "so", "n", "c", "e", "w",
    "b", "p", "a", "d", "f", "g", "m", "r", "s", "t", "lois", "ed", "sci",
    "bankr", "cir", "fed", "sess", "law", "eq", "ch", "commw", "commonw",
})

# Explicitly an appendix: "Appellant's App.", "Joint App.", "App. to Pet.".
_APPENDIX_LEAD = re.compile(
    r"(?:Appellant|Appellee|Petitioner|Respondent)(?:['\u2019]s)?\s+$|"
    r"(?:Joint|Supp\.?|Separate|Record|Addendum)\s+$|"
    r"App\.\s+to\s+$",
    re.IGNORECASE,
)

# A keyed abbreviation such as "Colo.", "C.", "So.", "Ark." A parenthesised
# form, "(Colo. App. 2004)", is not a citation to the appendix either.
_ABBREV_TOKEN = re.compile(r"\(?([A-Za-z]{1,10})\.$")


def _is_reporter_app(text: str, start: int) -> bool:
    """True when this ``App.`` is the reporter word, not an appendix label.

    ``start`` is the offset of the ``App.`` token itself. The deciding evidence
    is the abbreviation printed immediately before it: "Colo." and "C." in
    "N.C." name the reporter, while "Appellant's" and "Joint" name a document.
    """
    before = text[:start]
    if _APPENDIX_LEAD.search(before):
        return False
    token = _ABBREV_TOKEN.search(before.rstrip())
    if token is None:
        return False
    return token.group(1).lower() in _REPORTER_TAILS

# "Policy 1010.4.2", "Policy 321.5.9(f)-(g)". Subsection letters are dropped:
# the policy number is what identifies the source document.
_POLICY = re.compile(r"\bPolicy\s+(\d{1,4}(?:\.\d{1,3})*)", re.IGNORECASE)

# "Order at 2", "Dismissal Order ¶ 8", "Order ¶ 5", "Dismissal Order (¶ 26–28)".
_ORDER = re.compile(
    r"\b((?:[A-Za-z-]+\s+)?Order)\s*(?:,?\s*(?:\(?\s*at\s+(?:pp?\.\s*)?|\(?\s*¶{1,2}\s*|\(?\s*pp?\.?\s*))"
    r"(\d{1,4}(?:\s*(?:,|[-\u2013])\s*\d{1,4})*)\)?",
    re.IGNORECASE,
)

# "EF 00016–00017", "EF 00041", "CF 123", "CF 45".
_EFILING = re.compile(
    r"\b(EF|CF)\s*(?:No\.?\s*)?(\d{1,6}(?:\s*[-\u2013]\s*\d{1,6})?)",
    re.IGNORECASE,
)

_KINDS = (
    ("docket", _DOCKET),
    ("pleading", _PLEADING),
    ("appendix", _APPENDIX),
    ("policy", _POLICY),
    ("order", _ORDER),
    ("efiling", _EFILING),
)

_ORDER_LEAD_STRIP = frozenset({"see", "also", "accord", "cf", "the", "this", "that", "its", "court", "court's", "courts"})


def _clean_order_label(raw: str) -> str:
    words = raw.split()
    while words and words[0].lower() in _ORDER_LEAD_STRIP:
        words.pop(0)
    return " ".join(words) if words else "Order"


# One pleading, however it is abbreviated. The paragraph is a pin, not part of
# the document's identity: "SAC para 45" and "SAC para 46" cite one document.
_PLEADING_NAMES = {"sac": "SAC", "tac": "TAC", "fac": "FAC", "compl": "Complaint",
                   "complaint": "Complaint", "amcompl": "Amended Complaint"}


def _pleading_name(token: str) -> str:
    key = "".join(ch for ch in token.lower() if ch.isalpha())
    return _PLEADING_NAMES.get(key, token.strip())

# The ECF header stamped on every page -- "Case No. 1:25-cv-02263-RMR-MDB
# Document 84-1 filed 07/02/26 USDC Colorado" -- names a document number on
# every single page. It is page furniture identifying the filing itself, not a
# citation to the record, and counting it would swamp the real ones.
_ECF_STAMP = re.compile(r"filed\s+\d{1,2}/\d{1,2}/\d{2,4}|USDC\s", re.IGNORECASE)
_STAMP_WINDOW = 40


def _is_page_stamp(text: str, span: tuple[int, int]) -> bool:
    return bool(_ECF_STAMP.search(text[span[1] : span[1] + _STAMP_WINDOW]))


@dataclass(frozen=True)
class RecordCite:
    kind: str
    label: str
    span: tuple[int, int]
    pin: str | None = None
    text: str = ""

    @property
    def source_id(self) -> str:
        """Stable identifier for the document this points at."""
        return f"{self.kind}:{self.label}"


def extract_record_cites(text: str, original: str | None = None) -> list[RecordCite]:
    """Find every record or evidence citation, in order of appearance.

    ``text`` may be a masked working copy, in which case spans are still
    offsets into the document the caller will be handed back. Court stamps are
    blanked in place, so a citation matched across a page break reports text
    that no longer matches the characters its span addresses -- and the
    orchestrator refuses an extraction whose spans do not slice back to the
    text it was sent. Pass the unmasked document as ``original`` and every
    cite's text is read back out of it, the same way propositions and
    quotations already are.
    """
    if not text:
        return []

    source = original if original is not None else text
    found: list[RecordCite] = []
    for kind, pattern in _KINDS:
        for match in pattern.finditer(text):
            if kind == "pleading":
                label, pin = _pleading_name(match.group(1)), match.group(2)
            elif kind == "docket":
                label, pin = match.group(1), match.group(2)
            elif kind == "appendix":
                label, pin = "Appendix", match.group(1)
            elif kind == "order":
                label, pin = _clean_order_label(match.group(1)), match.group(2)
            elif kind == "efiling":
                label, pin = match.group(1).upper(), match.group(2)
            else:
                label, pin = match.group(1), None
            if kind == "docket" and _is_page_stamp(text, match.span()):
                continue
            if kind == "appendix" and _is_reporter_app(text, match.start()):
                continue
            span = match.span()
            found.append(
                RecordCite(
                    kind=kind,
                    label=label,
                    span=span,
                    pin=pin,
                    text=source[span[0] : span[1]].strip(),
                )
            )

    found.sort(key=lambda c: c.span[0])
    found = _drop_overlaps(found)
    return _with_parenthetical_ids(text, found, source)


# "(Id. at 25.)", "(Id.)", "(See id. ¶ 5)". eyecite does not see an Id. inside
# parentheses at all, and that is exactly how courts and briefs cite the record
# back: "(Doc. No. 61 at 15.) ... (Id. at 25.)". Unseen, the quotation in front
# of it was handed to whatever case the sentence named -- the recommendation in
# Cooper v. City of Pueblo quoting the plaintiff's brief was reported as a quote
# missing from United States v. Reeves.
_PAREN_ID = re.compile(
    r"\(\s*(?:see\s+)?(Id\.(?:\s*,?\s*at\s+(?:pp?\.\s*)?(\d{1,4}(?:\s*[-\u2013]\s*\d{1,4})?)"
    r"|\s*¶{1,2}\s*(\d{1,4}(?:\s*(?:,|[-\u2013])\s*\d{1,4})*))?)",
    re.IGNORECASE,
)


def _with_parenthetical_ids(text: str, found: list[RecordCite], source: str | None = None) -> list[RecordCite]:
    """A parenthetical Id. points back at the most recent record citation.

    Only when one precedes it: a parenthetical Id. with no record citation
    before it is left alone rather than guessed at.
    """
    origin = source if source is not None else text
    cites = list(found)
    for match in _PAREN_ID.finditer(text):
        start, end = match.span(1)
        if any(c.span[0] < end and start < c.span[1] for c in cites):
            continue
        earlier = [c for c in cites if c.span[1] <= start]
        if not earlier:
            continue
        referent = max(earlier, key=lambda c: c.span[1])
        cites.append(RecordCite(kind=referent.kind, label=referent.label, span=(start, end),
                                pin=match.group(2) or match.group(3), text=origin[start:end].strip()))
    cites.sort(key=lambda c: c.span[0])
    return cites


def _drop_overlaps(cites: list[RecordCite]) -> list[RecordCite]:
    """Keep the first of any two citations claiming the same characters."""
    kept: list[RecordCite] = []
    for cite in cites:
        if kept and cite.span[0] < kept[-1].span[1]:
            continue
        kept.append(cite)
    return kept
