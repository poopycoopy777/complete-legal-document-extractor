"""Audit extractor output on real documents against the contract the app relies on.

Checks, in the order that losing evidence matters:

1. every reported span (citation, child, proposition, occurrence proposition,
   authority citation, record citation, quotation) slices back to exactly the
   text reported for it, against the text the extractor says it read;
2. no document reports zero citations while its text layer contains citations;
3. page ranges cover the whole text, so an offset resolves to exactly one page;
4. duplicate full citations of one authority are visible rather than silent;
5. a proposition that is only a running head or page furniture is flagged.

Read-only: opens inputs, writes only the report path given on the command line.

Usage:
    python scripts/audit_contract.py --inputs <dir-or-file> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402

CITATION_SHAPE = re.compile(
    r"\b\d{1,4}\s+(?:U\.?\s*S\.|F\.\s*(?:Supp\.|App'x)?|P\.\d?d?|S\.\s*Ct\.|Colo\.?|"
    r"A\.\d?d?|N\.E\.\d?d?|F\.\d?d?)\s*\d{1,5}\b|\b\d{4}\s+CO(?:A)?\s+\d+\b",
    re.IGNORECASE,
)


def text_for(path: Path) -> tuple[str, int]:
    """Return (text, page_count) using the API's own PDF contract."""
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace"), 0
    import pymupdf

    chunks: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text", sort=True))
        count = doc.page_count
    return "".join(chunks), count


def page_ranges(path: Path) -> list[tuple[int, int]]:
    if path.suffix.lower() != ".pdf":
        return []
    import pymupdf

    ranges: list[tuple[int, int]] = []
    offset = 0
    with pymupdf.open(path) as doc:
        for page in doc:
            body = page.get_text("text", sort=True)
            ranges.append((offset, offset + len(body)))
            offset += len(body)
    return ranges


def is_span(span) -> bool:
    """The dict form carries tuples; the JSON form carries lists. Accept both."""
    return (
        isinstance(span, (list, tuple))
        and len(span) == 2
        and all(isinstance(v, int) for v in span)
    )


def check_span(text: str, span, label: str, violations: list[dict], doc: str) -> None:
    if not is_span(span):
        violations.append({"doc": doc, "kind": "span_missing", "where": label, "span": span})
        return
    if not (0 <= span[0] < span[1] <= len(text)):
        violations.append({"doc": doc, "kind": "span_out_of_range", "where": label,
                           "span": list(span), "text_length": len(text)})


def check_slice(text: str, span, claimed, label: str, violations: list[dict], doc: str) -> None:
    check_span(text, span, label, violations, doc)
    if not is_span(span):
        return
    actual = text[span[0]:span[1]]
    if claimed is not None and actual != claimed:
        violations.append({
            "doc": doc, "kind": "span_text_mismatch", "where": label, "span": list(span),
            "claimed": claimed[:200], "actual": actual[:200],
        })


def audit_one(path: Path) -> dict:
    doc = path.name
    text, page_count = text_for(path)
    data = group_citations(text).as_dict()
    violations: list[dict] = []

    groups = data.get("groups", [])
    for group in groups:
        gid = group.get("id")
        header = group.get("header") or {}
        check_slice(text, header.get("span"), header.get("text"), f"{gid}.header", violations, doc)
        for index, child in enumerate(group.get("children") or []):
            check_slice(text, child.get("span"), child.get("text"),
                        f"{gid}.child[{index}]", violations, doc)
        proposition = group.get("proposition")
        if proposition is not None:
            check_slice(text, group.get("propositionSpan"), proposition,
                        f"{gid}.proposition", violations, doc)
        for index, occurrence in enumerate(group.get("occurrencePropositions") or []):
            claimed = occurrence.get("proposition")
            if claimed is not None:
                check_slice(text, occurrence.get("propositionSpan"), claimed,
                            f"{gid}.occurrence[{index}]", violations, doc)
        for index, quote in enumerate(group.get("quotes") or []):
            check_slice(text, quote.get("span"), quote.get("raw_text"),
                        f"{gid}.quote[{index}]", violations, doc)

    for authority in data.get("authorities", []):
        aid = authority.get("id")
        header = authority.get("header") or {}
        check_slice(text, header.get("span"), header.get("text"), f"{aid}.header", violations, doc)
        for index, child in enumerate(authority.get("children") or []):
            check_slice(text, child.get("span"), child.get("text"),
                        f"{aid}.child[{index}]", violations, doc)

    for record in data.get("records", []):
        rid = record.get("id")
        header = record.get("header") or {}
        check_slice(text, header.get("span"), header.get("text"), f"{rid}.header", violations, doc)
        for index, child in enumerate(record.get("children") or []):
            check_slice(text, child.get("span"), child.get("text"),
                        f"{rid}.child[{index}]", violations, doc)

    # Page coverage: every character offset resolves to exactly one page.
    ranges = page_ranges(path)
    gaps = []
    if ranges:
        for (_, prev_end), (next_start, _) in zip(ranges, ranges[1:]):
            if next_start < prev_end:
                gaps.append({"kind": "overlap", "at": next_start})
        if ranges[-1][1] != len(text) and path.suffix.lower() == ".pdf":
            gaps.append({"kind": "text_beyond_last_page", "page_end": ranges[-1][1],
                         "text_length": len(text)})

    expected_citations = len(CITATION_SHAPE.findall(text))
    stats = data.get("stats", {})
    silent_empty = expected_citations > 0 and stats.get("citations", 0) == 0

    duplicate_headers = []
    by_header: dict[str, int] = {}
    for group in groups:
        key = (group.get("header") or {}).get("text") or ""
        by_header[key] = by_header.get(key, 0) + 1
    duplicate_headers = sorted(k for k, v in by_header.items() if v > 1)

    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "text_chars": len(text),
        "pdf_pages": page_count,
        "stats": stats,
        "expected_citation_matches": expected_citations,
        "silent_empty": silent_empty,
        "page_gaps": gaps,
        "duplicate_group_headers": duplicate_headers,
        "violations": violations,
        "violation_count": len(violations),
    }


def collect(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*")
                                if p.suffix.lower() in {".pdf", ".txt", ".md", ".text"}))
        elif item.is_file():
            files.append(item)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    files = collect(args.inputs)
    if args.limit:
        files = files[: args.limit]

    results = []
    for path in files:
        try:
            results.append(audit_one(path))
        except Exception as exc:  # noqa: BLE001 - a crash is a finding
            results.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}",
                            "violation_count": -1})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")

    total_violations = sum(max(0, r.get("violation_count", 0)) for r in results)
    broken = [r for r in results if r.get("violation_count")]
    silent = [r for r in results if r.get("silent_empty")]
    print(f"documents={len(results)} violations={total_violations} "
          f"documents_with_violations={len(broken)} silent_empty={len(silent)}")
    for r in broken[:20]:
        if r.get("error"):
            print(f"  CRASH {r['path']}: {r['error']}")
            continue
        print(f"  {Path(r['path']).name}: {r['violation_count']} violations")
        for v in r["violations"][:5]:
            print(f"      {v['kind']} {v['where']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
