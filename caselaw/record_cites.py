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
    r"(?:\s*,?\s*at\s+(\d{1,4}(?:\s*[-\u2013]\s*\d{1,4})?))?",
    re.IGNORECASE,
)

# "SAC para 45", "Compl. paras 65, 67, 69-70". The whole paragraph list is the
# pin: the quotation may sit in any paragraph it names.
_PLEADING = re.compile(
    r"\b(SAC|TAC|FAC|Compl\.?|Complaint|Am\.?\s*Compl\.?)\s*¶{1,2}\s*"
    r"(\d{1,4}(?:\s*(?:,|[-\u2013])\s*\d{1,4})*)",
    re.IGNORECASE,
)

# "Policy 1010.4.2", "Policy 321.5.9(f)-(g)". Subsection letters are dropped:
# the policy number is what identifies the source document.
_POLICY = re.compile(r"\bPolicy\s+(\d{1,4}(?:\.\d{1,3})*)", re.IGNORECASE)

_KINDS = (("docket", _DOCKET), ("pleading", _PLEADING), ("policy", _POLICY))

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


def extract_record_cites(text: str) -> list[RecordCite]:
    """Find every record or evidence citation, in order of appearance."""
    if not text:
        return []

    found: list[RecordCite] = []
    for kind, pattern in _KINDS:
        for match in pattern.finditer(text):
            if kind == "pleading":
                label, pin = _pleading_name(match.group(1)), match.group(2)
            elif kind == "docket":
                label, pin = match.group(1), match.group(2)
            else:
                label, pin = match.group(1), None
            if kind == "docket" and _is_page_stamp(text, match.span()):
                continue
            found.append(
                RecordCite(
                    kind=kind,
                    label=label,
                    span=match.span(),
                    pin=pin,
                    text=match.group(0).strip(),
                )
            )

    found.sort(key=lambda c: c.span[0])
    return _drop_overlaps(found)


def _drop_overlaps(cites: list[RecordCite]) -> list[RecordCite]:
    """Keep the first of any two citations claiming the same characters."""
    kept: list[RecordCite] = []
    for cite in cites:
        if kept and cite.span[0] < kept[-1].span[1]:
            continue
        kept.append(cite)
    return kept
