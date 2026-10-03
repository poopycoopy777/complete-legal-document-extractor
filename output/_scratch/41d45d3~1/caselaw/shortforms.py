"""Resolve short forms that name more than one cited case.

eyecite resolves "Woo at 902" or "Woo, supra at 910" only when exactly one
earlier citation carries the name. A brief that cites People v. Woo, 579 P.3d
459, and Woo v. El Paso County Sheriff's Office, 528 P.3d 899, defeats it, so
every short form to either stayed an orphan and the quotation before it stayed
unattributed.

Resolution here is a refinement of eyecite's, never a replacement: when eyecite
resolves a short form the answer stands. Only when it declines are the
candidates narrowed by evidence the short form itself prints, and a short form
is bound only when exactly one case survives:

* the name it uses (as eyecite reads it);
* a full caption printed in front of it ("People v. Woo, supra at 465");
* its pin page, which must fall inside the opinion that starts at the case's
  first page.

If two or more cases survive, or none does, the short form stays unresolved and
is flagged on its own record so the reader sees why. It is never guessed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

# eyecite resolves a pin only if it is under this many pages past the cited
# first page (eyecite.resolve.MAX_OPINION_PAGE_COUNT, used there to reject
# "1 U.S. 1. Id. at 200"). The same conservative bound applies here: no
# reported opinion in the briefs this reads runs longer, and a page beyond it
# belongs to some other case.
MAX_OPINION_PAGES = 150

_WORDS = re.compile(r"[a-z0-9]+")
_PIN_PAGE = re.compile(r"\d+")
_CAPTION_WINDOW = 200


def _norm(value: str | None) -> str:
    return " ".join(_WORDS.findall((value or "").lower().replace("\u2019", "'").replace("'", "")))


def _contains(party: str | None, name: str) -> bool:
    """Whether ``name`` occurs in ``party`` as whole words."""
    party_norm = _norm(party)
    return bool(name) and bool(party_norm) and f" {name} " in f" {party_norm} "


def _same_party(caption: str | None, party: str | None) -> bool:
    caption_norm, party_norm = _norm(caption), _norm(party)
    return bool(caption_norm) and bool(party_norm) and (
        f" {caption_norm} " in f" {party_norm} " or f" {party_norm} " in f" {caption_norm} "
    )


def _pin_page(record: Any) -> int | None:
    match = _PIN_PAGE.search(record.pin_cite or "")
    return int(match.group()) if match else None


def _hints(cite: Any) -> list[str]:
    """The names a short form uses for its case, as eyecite read them."""
    meta = cite.metadata
    raw = [
        getattr(meta, "antecedent_guess", None),
        getattr(meta, "plaintiff", None),
        getattr(meta, "defendant", None),
    ]
    return [name for name in (_norm(value) for value in raw) if name]


def _names_of(record: Any, cite: Any) -> list[str | None]:
    meta = cite.metadata
    return [
        record.plaintiff, record.defendant, record.case_name,
        getattr(meta, "plaintiff", None), getattr(meta, "defendant", None),
    ]


def _describe(record: Any) -> str:
    return " ".join((record.full_citation or record.text).split())


def short_form_resolvers(pairs: list[tuple[Any, Any]], text: str) -> dict[str, Callable]:
    """Keyword arguments for ``eyecite.resolve_citations`` that add the refinement.

    ``pairs`` is what ``extract_pairs`` returned for ``text``.
    """
    from eyecite.models import FullCaseCitation
    from eyecite.resolve import _resolve_reference_citation, _resolve_supra_citation

    from .extract import _derive_parties

    by_cite = {id(cite): record for cite, record in pairs}

    ends = sorted(record.span[1] for _, record in pairs)

    def printed_caption(record: Any) -> tuple[str | None, str | None]:
        """The "A v. B" printed directly in front of the short form, if any.

        Bounded by the previous citation, as the extractor bounds every caption
        window: a longer one reads a parenthetical year as part of a party name.
        """
        start = record.span[0]
        floor = max((end for end in ends if end <= start), default=0)
        return _derive_parties(text[max(floor, start - _CAPTION_WINDOW):start])

    def flag(record: Any, message: str) -> None:
        if message not in record.flags:
            record.flags.append(message)

    def refine(short: Any, resolved_full: list[tuple[Any, Any]]) -> Any:
        record = by_cite.get(id(short))
        if record is None:
            return None
        hints = _hints(short)
        candidates = []
        for full, resource in resolved_full:
            full_record = by_cite.get(id(full))
            if full_record is None or not isinstance(full, FullCaseCitation):
                continue
            names = _names_of(full_record, full)
            if any(_contains(name, hint) for name in names for hint in hints):
                candidates.append((full_record, resource))
        if not candidates:
            return None

        label = " / ".join(sorted({_describe(r) for r, _ in candidates}))
        caption = printed_caption(record) if record.kind == "SupraCitation" else (None, None)
        if all(caption):
            candidates = [
                (r, res) for r, res in candidates
                if _same_party(caption[0], r.plaintiff) and _same_party(caption[1], r.defendant)
            ]
        pin = _pin_page(record)
        if pin is not None:
            candidates = [
                (r, res) for r, res in candidates
                if not (r.page or "").isdigit()
                or int(r.page) <= pin <= int(r.page) + MAX_OPINION_PAGES
            ]

        resources = {res for _, res in candidates}
        if len(resources) == 1:
            return candidates[0][1]
        if not resources:
            flag(record, (
                "short_form_unresolved: the caption and pin page it prints fit none of "
                f"the cases it could name ({label})"
            ))
        else:
            flag(record, (
                f"short_form_ambiguous: {len(resources)} cases fit this short form "
                f"and nothing it prints chooses between them ({label})"
            ))
        return None

    def resolve_supra(short: Any, resolved_full: list[tuple[Any, Any]]) -> Any:
        resource = _resolve_supra_citation(short, resolved_full)
        return resource if resource is not None else refine(short, resolved_full)

    def resolve_reference(short: Any, resolved_full: list[tuple[Any, Any]]) -> Any:
        resource = _resolve_reference_citation(short, resolved_full)
        return resource if resource is not None else refine(short, resolved_full)

    return {
        "resolve_supra_citation": resolve_supra,
        "resolve_reference_citation": resolve_reference,
    }
