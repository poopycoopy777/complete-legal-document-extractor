"""Statute, regulation, court rule and constitution extraction.

Case law is eyecite's job (see extract.py). Everything else — the U.S. Code,
the C.F.R., all fifty states' codes, the Federal Rules of Civil/Appellate/
Criminal Procedure and Evidence, named federal acts, and state and federal
constitutions — comes from CiteURL's template set.

Two defects in that template set are corrected here:

1. CiteURL loads its bundled YAML with ``Path.read_text()`` and no encoding
   argument (citator.py:366). On any machine whose preferred encoding is not
   UTF-8 — every stock Windows install — the section sign in those templates is
   decoded as "Â§", so no pattern can ever match a real "§". Silently, every
   "42 U.S.C. § 1983" in every document is missed. The templates are loaded
   here as UTF-8 explicitly.

2. The state templates recognise a state's long form ("Colo. Rev. Stat.") but
   not the initialism practitioners actually write ("C.R.S."), and not the
   postfix form several states use ("§ 24-72-303, C.R.S."). Without those, a
   bare section cite is captured by the U.S. Code short-form pattern and
   mislabelled as federal law. Prefix and postfix patterns are generated for
   every state code from that state's own token structure.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import citeurl
import yaml
from citeurl import Citator

# Bundled template sets to load. "caselaw" is deliberately excluded: eyecite
# owns case law and running both produces duplicate, conflicting citations.
# "secondary sources" (law reviews, treatises) is out of scope.
_TEMPLATE_SETS = (
    "general federal law",
    "specific federal laws",
    "state law",
)

_OVERRIDES = Path(__file__).parent / "templates" / "overrides.yaml"

# Words skipped when building a code's initialism from its name.
_INITIALISM_STOPWORDS = {"of", "the", "and", "for", "in"}

# Initialisms that do not fall out of the template name. The general rule
# derives "ICS" from "Illinois Compiled Statutes"; practitioners write "ILCS".
_INITIALISM_OVERRIDES = {
    "Illinois Compiled Statutes": ["ILCS"],
    "Consolidated Laws of New York": ["NYCLS"],
    "General Statutes of Connecticut": ["CGS", "CGSA"],
    "Georgia Code": ["OCGA"],
    "Louisiana Statutes": ["LSA"],
    "Maine Statutes": ["MRSA"],
    "Revised Statutes of Nebraska": ["NEB REV STAT"],
    "Code of Alabama, 1975": ["ALA CODE"],
    "Florida Statutes": ["FLA STAT"],
    "Indiana Code": ["IND CODE"],
    "Iowa Code": ["IOWA CODE"],
    "Alaska Statutes": ["ALASKA STAT"],
    "Texas Codes": ["TEX CODE"],
    "Kansas Statutes": ["KSA"],
    "Kentucky Revised Statutes": ["KRS"],
    "Mississippi Code": ["MISS CODE"],
    "Montana Code": ["MCA"],
    "Oklahoma Statutes": ["OKLA STAT"],
    "Pennsylvania Consolidated Statutes": ["PACS"],
    "General Laws of Rhode Island": ["RIGL"],
    "South Carolina Code": ["SC CODE"],
    "South Dakota Codified Laws": ["SDCL"],
    "Tennessee Code": ["TCA"],
    "Utah Code": ["UTAH CODE"],
    "Vermont Statutes": ["VSA"],
    "Virginia Code": ["VA CODE"],
    "West Virginia Code": ["WV CODE"],
    "Wisconsin Statutes": ["WIS STAT"],
    "Wyoming Statutes": ["WYO STAT"],
}

_SECTION_SIGN = r"(([Ss]ec(tions?|t?s?\.?)|(&sect;|&#167|§){1,2}) ?)?"

# A short form must carry something that marks it as a citation. CiteURL's
# idform patterns accept a bare {section} token once a full citation has been
# seen, so in a brief every page number, paragraph number and year after the
# first statute cite is matched as a short-form reference to it. On one
# 82,000-character answer brief that turned 106 real citations into 816.
# A reference with no section sign, no "section"/"sec.", no "id." and no code
# name is not a citation in legal writing.
_SHORTFORM_EVIDENCE = re.compile(
    r"§|&sect;|&#167|\bsec(tion)?s?\b\.?|\bid\b\.?|[A-Z]\.\s?[A-Z]\.",
    re.IGNORECASE,
)

# An initialism must be at least this long. Two-letter forms ("IC" for both
# Idaho Code and Iowa Code, "MS" for Minnesota Statutes) collide with ordinary
# abbreviations and produce false positives.
_MIN_INITIALISM = 3


@dataclass
class Authority:
    """One extracted non-case citation."""

    category: str
    source: str
    text: str
    span: tuple[int, int]
    name: str | None = None
    url: str | None = None
    tokens: dict[str, Any] = field(default_factory=dict)
    is_shortform: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _categorise(template_name: str) -> str:
    lowered = template_name.lower()
    if "constitution" in lowered:
        return "constitution"
    if "rules of" in lowered or lowered.startswith("federal rules"):
        return "rule"
    if any(
        token in lowered
        for token in (
            "regulation",
            "code of federal regulations",
            "administrative code",
            "federal register",
            "codes, rules",
        )
    ):
        return "regulation"
    return "statute"


def _initialisms(template_name: str) -> list[str]:
    if template_name in _INITIALISM_OVERRIDES:
        return _INITIALISM_OVERRIDES[template_name]
    letters = [
        word[0]
        for word in re.findall(r"[A-Za-z]+", template_name)
        if word.lower() not in _INITIALISM_STOPWORDS
    ]
    candidate = "".join(letters).upper()
    return [candidate] if len(candidate) >= _MIN_INITIALISM else []


def _initialism_regex(initialism: str) -> str:
    """Match C.R.S., CRS, C. R. S., and the Annotated variants."""
    letters = [ch for ch in initialism if ch.isalnum()]
    core = r"\.?\s?".join(re.escape(ch) for ch in letters)
    return rf"{core}\.?(\s?A(nn(otated)?)?\.?)?"


def _body_index(pattern: list[str]) -> int | None:
    """Index where the citation body starts, after the source designator.

    Returns None when the designator and body cannot be separated — California
    and Delaware interleave them, and both already carry their own initialism.
    """
    for index, part in enumerate(pattern):
        if "{" in part and "{name regex}" not in part:
            return index if index >= 1 else None
    return None


def _is_balanced(parts: list[str]) -> bool:
    """Whether a pattern slice stands on its own as a regex fragment.

    Some templates split a single group across list elements, so a slice taken
    from the middle can open or close parentheses it does not own. Escaped
    parentheses and those inside character classes do not count.
    """
    depth = 0
    in_class = False
    for text in parts:
        index = 0
        while index < len(text):
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if in_class:
                if char == "]":
                    in_class = False
            elif char == "[":
                in_class = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    return False
            index += 1
    return depth == 0


def _resolve_pattern(name: str, raw: dict[str, dict]) -> list[str] | None:
    """Follow the inherit chain until a template that defines a pattern.

    Most states do not carry their own pattern: Nevada inherits Florida's,
    Washington inherits Alaska's, and so on, overriding only the name regex and
    URL builder. Generating from the declared patterns alone would cover 23 of
    the 50-odd codes.
    """
    seen: set[str] = set()
    current = name
    while current and current not in seen:
        seen.add(current)
        data = raw.get(current)
        if not isinstance(data, dict):
            return None
        pattern = data.get("pattern")
        if pattern:
            return pattern if isinstance(pattern, list) else [pattern]
        current = data.get("inherit")
    return None


def _generated_templates(raw_sets: dict[str, dict]) -> dict[str, dict]:
    """Prefix and postfix initialism templates for every state code."""
    generated: dict[str, dict] = {}
    for name, data in raw_sets.items():
        if not isinstance(data, dict):
            continue
        if "constitution" in name.lower():
            continue
        pattern = _resolve_pattern(name, raw_sets)
        if not pattern:
            continue
        start = _body_index(pattern)
        if start is None:
            continue
        body = pattern[start:]
        # The body already opens with the template's own optional section-sign
        # group; a slice that is not self-balancing cannot be reused.
        if not _is_balanced(body):
            continue

        for initialism in _initialisms(name):
            stem = _initialism_regex(initialism)
            generated[f"{name} [{initialism} prefix]"] = {
                "inherit": name,
                "pattern": [rf"\b{stem},?\s*", *body],
            }
            generated[f"{name} [{initialism} postfix]"] = {
                "inherit": name,
                "pattern": [*body, rf",?\s*{stem}\b"],
            }
    return generated


def build_citator() -> Citator:
    """A citator with UTF-8 templates plus generated state initialism forms."""
    templates_dir = Path(citeurl.__file__).parent / "templates"

    citator = Citator(defaults=None)
    raw: dict[str, dict] = {}
    for name in _TEMPLATE_SETS:
        body = (templates_dir / f"{name}.yaml").read_text(encoding="utf-8")
        citator.load_yaml(body)
        parsed = yaml.safe_load(body)
        if name == "state law":
            raw.update(parsed)

    generated = _generated_templates(raw)
    if generated:
        citator.load_yaml(yaml.safe_dump(generated, allow_unicode=True))

    if _OVERRIDES.is_file():
        citator.load_yaml(_OVERRIDES.read_text(encoding="utf-8"))

    return citator


_CITATOR: Citator | None = None


def _citator() -> Citator:
    global _CITATOR
    if _CITATOR is None:
        _CITATOR = build_citator()
    return _CITATOR


def _base_source(template_name: str) -> str:
    """Strip the generated "[CRS prefix]" marker back to the real code name."""
    return re.sub(r"\s*\[[^\]]+\]\s*$", "", template_name)


def extract_authorities(text: str) -> list[Authority]:
    """Extract statutes, regulations, rules and constitutions, in order."""
    if not text or not text.strip():
        return []

    results: list[Authority] = []
    for cite in _citator().list_cites(text):
        source = _base_source(cite.template.name)
        start, end = cite.span
        body = text[start:end]
        is_shortform = getattr(cite, "parent", None) is not None
        if is_shortform and not _SHORTFORM_EVIDENCE.search(body):
            continue
        results.append(
            Authority(
                category=_categorise(source),
                source=source,
                text=body,
                span=(start, end),
                name=getattr(cite, "name", None),
                url=getattr(cite, "URL", None),
                tokens={k: v for k, v in (cite.tokens or {}).items() if v},
                is_shortform=is_shortform,
            )
        )
    results.sort(key=lambda a: a.span[0])
    return results
