"""Characterise a PDF corpus: text layer, page sparsity, OCR need. Read-only.

Reports per unique document hash:

* page count and per-page character counts, so a mixed scan (some pages with a
  text layer, some without) is visible;
* whether the embedded layer is usable, absent, or partial;
* whether the page range contract currently produced by the API covers the
  whole text (page spans must not overlap, and the last page must reach the end
  of the text);
* whether extraction returns nothing on a document whose text layer holds
  citation-shaped strings.

Usage:
    python scripts/audit_corpus_probe.py --inputs <dir> [...] --out <report.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caselaw.group import group_citations  # noqa: E402

CITATION_SHAPE = re.compile(
    r"\b\d{1,4}\s+(?:U\.?\s*S\.|F\.\s*(?:Supp\.|App'x)?|P\.\d?d?|S\.\s*Ct\.|Colo\.?|"
    r"A\.\d?d?|N\.E\.\d?d?|F\.\d?d?)\s*\d{1,5}\b|\b\d{4}\s+CO(?:A)?\s+\d+\b",
    re.IGNORECASE,
)

SPARSE_CHARS = 100


def pdf_pages(path: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [page.get_text("text", sort=True) for page in doc]


def probe(path: Path) -> dict:
    pages = pdf_pages(path)
    text = "".join(pages)
    per_page = [len(p.strip()) for p in pages]

    sparse = [i + 1 for i, n in enumerate(per_page) if n < SPARSE_CHARS]
    embedded_usable = bool(text.strip())
    mixed = embedded_usable and bool(sparse)

    # The offset contract the API builds from the embedded layer.
    ranges: list[tuple[int, int]] = []
    offset = 0
    for body in pages:
        ranges.append((offset, offset + len(body)))
        offset += len(body)
    overlapping = [
        {"page": i + 2, "start": ranges[i + 1][0], "previous_end": ranges[i][1]}
        for i in range(len(ranges) - 1)
        if ranges[i + 1][0] < ranges[i][1]
    ]
    zero_length = [i + 1 for i, (a, b) in enumerate(ranges) if b <= a]

    out: dict = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "pages": len(pages),
        "text_chars": len(text),
        "sparse_pages": sparse,
        "zero_length_pages": zero_length,
        "embedded_usable": embedded_usable,
        "mixed_scan": mixed,
        "page_range_overlaps": overlapping,
        "expanded_chars": len(text.expandtabs()),
    }

    if embedded_usable:
        data = group_citations(text).as_dict()
        stats = data.get("stats", {})
        out["stats"] = stats
        out["expected_citation_matches"] = len(CITATION_SHAPE.findall(text))
        out["silent_empty"] = out["expected_citation_matches"] > 0 and stats.get("citations", 0) == 0

    return out


def collect(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files.extend(sorted(p for p in item.rglob("*") if p.suffix.lower() == ".pdf"))
        elif item.is_file():
            files.append(item)
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-bytes", type=int, default=40 * 1024 * 1024)
    args = parser.parse_args()

    files = collect(args.inputs)

    # One probe per unique byte sequence; duplicates are recorded as aliases.
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        if path.stat().st_size > args.max_bytes:
            continue
        by_hash[hashlib.sha256(path.read_bytes()).hexdigest()].append(path)

    unique = [sorted(paths)[0] for paths in by_hash.values()]
    if args.limit:
        unique = unique[: args.limit]

    results = []
    for path in unique:
        try:
            record = probe(path)
        except Exception as exc:  # noqa: BLE001 - a crash is a finding
            record = {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
        record["aliases"] = [str(p) for p in by_hash[hashlib.sha256(path.read_bytes()).hexdigest()]]
        results.append(record)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=True), encoding="utf-8")

    usable = [r for r in results if r.get("embedded_usable")]
    absent = [r for r in results if r.get("embedded_usable") is False]
    mixed = [r for r in results if r.get("mixed_scan")]
    silent = [r for r in results if r.get("silent_empty")]
    overlaps = [r for r in results if r.get("page_range_overlaps")]
    errors = [r for r in results if r.get("error")]

    print(f"unique_documents={len(results)} total_inputs={len(files)}")
    print(f"embedded_usable={len(usable)} no_text_layer={len(absent)} "
          f"mixed_scan={len(mixed)} silent_empty={len(silent)} "
          f"page_range_overlaps={len(overlaps)} errors={len(errors)}")
    for r in errors[:10]:
        print(f"  ERROR {Path(r['path']).name}: {r['error']}")
    for r in mixed[:10]:
        print(f"  MIXED {Path(r['path']).name}: {r['pages']} pages, "
              f"sparse={r['sparse_pages'][:12]}, chars={r['text_chars']}")
    for r in silent[:10]:
        print(f"  SILENT {Path(r['path']).name}: expected>={r['expected_citation_matches']} "
              f"matches but stats={r.get('stats')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
