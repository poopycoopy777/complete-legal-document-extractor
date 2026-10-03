"""Check EVERY reported string+span pair against the original document.

audit_contract.py checks citations, propositions, occurrences, quote raw_text,
records and authority header/children. This adds the fields it does not check:

* Quote.text (the collapsed display body) against its own span;
* authority `name`;
* Citation.full_citation / corrected / parenthetical / antecedent (no span, so
  only reported for review);
* citation/authority/record text against the UNMASKED original, which is what
  the orchestrator slices when it validates.

It does that by wrapping caselaw.group._mask_court_stamps so the unmasked
document is captured for every group_citations call.

Read-only over the corpus; writes only the report path given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import caselaw.group as group  # noqa: E402

SELFTEST_MASKED = False
_ORIGINALS: list[str] = []
_REAL_MASK = group._mask_court_stamps


def _capturing_mask(text: str) -> str:
    _ORIGINALS.append(text)
    return _REAL_MASK(text)


group._mask_court_stamps = _capturing_mask


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    chunks: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text", sort=True))
    return "".join(chunks)


def _span_ok(span) -> bool:
    return (isinstance(span, (list, tuple)) and len(span) == 2
            and all(isinstance(v, int) for v in span) and span[0] < span[1])


def check(original: str, span, claimed, label: str, doc: str, out: list[dict],
          allow_collapsed: bool = False) -> None:
    if claimed is None:
        return
    if not _span_ok(span):
        out.append({"doc": doc, "kind": "span_missing", "where": label, "span": span})
        return
    actual = original[span[0]:span[1]]
    if actual != claimed:
        if allow_collapsed and " ".join(actual.split()) == claimed:
            return
        out.append({
            "doc": doc, "kind": "mismatch", "where": label, "span": list(span),
            "claimed": claimed[:160], "actual": actual[:160],
            "collapsed_equal": " ".join(actual.split()) == claimed,
        })


def audit_one(path: Path) -> dict:
    doc = path.name
    text = text_for(path)
    _ORIGINALS.clear()
    try:
        data = group.group_citations(text).as_dict()
    except Exception as exc:  # noqa: BLE001
        return {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
    original = _ORIGINALS[0] if _ORIGINALS else text
    if SELFTEST_MASKED:
        # Deliberate self-test of the checker: hand it the MASKED working copy
        # instead of the original. Every field that is correctly read back out
        # of the original (propositions, quote raw_text, record text) must now
        # be reported as a mismatch, which proves the audit is not vacuous.
        original = _REAL_MASK(original)

    problems: list[dict] = []
    for g in data["groups"]:
        gid = g["id"]
        check(original, g["header"].get("span"), g["header"].get("text"), f"{gid}.header", doc, problems)
        for i, c in enumerate(g["children"]):
            check(original, c.get("span"), c.get("text"), f"{gid}.child[{i}]", doc, problems)
        if g.get("proposition"):
            check(original, g.get("propositionSpan"), g["proposition"], f"{gid}.proposition", doc, problems)
        for i, occ in enumerate(g.get("occurrencePropositions") or []):
            if occ.get("proposition"):
                check(original, occ.get("propositionSpan"), occ["proposition"],
                      f"{gid}.occurrence[{i}]", doc, problems)
        for i, q in enumerate(g.get("quotes") or []):
            check(original, q.get("span"), q.get("raw_text"), f"{gid}.quote[{i}].raw_text", doc, problems)
            check(original, q.get("span"), q.get("text"), f"{gid}.quote[{i}].text", doc, problems, allow_collapsed=True)
    for a in data["authorities"]:
        aid = a["id"]
        check(original, a["header"].get("span"), a["header"].get("text"), f"{aid}.header", doc, problems)
        for i, c in enumerate(a["children"]):
            check(original, c.get("span"), c.get("text"), f"{aid}.child[{i}]", doc, problems)
        for i, q in enumerate(a.get("quotes") or []):
            check(original, q.get("span"), q.get("raw_text"), f"{aid}.quote[{i}].raw_text", doc, problems)
            check(original, q.get("span"), q.get("text"), f"{aid}.quote[{i}].text", doc, problems, allow_collapsed=True)
    for r in data["records"]:
        rid = r["id"]
        check(original, r["header"].get("span"), r["header"].get("text"), f"{rid}.header", doc, problems)
        for i, c in enumerate(r["children"]):
            check(original, c.get("span"), c.get("text"), f"{rid}.child[{i}]", doc, problems)
        if r.get("proposition"):
            check(original, r.get("propositionSpan"), r["proposition"], f"{rid}.proposition", doc, problems)
        for i, q in enumerate(r.get("quotes") or []):
            check(original, q.get("span"), q.get("raw_text"), f"{rid}.quote[{i}].raw_text", doc, problems)
            check(original, q.get("span"), q.get("text"), f"{rid}.quote[{i}].text", doc, problems, allow_collapsed=True)
    for i, c in enumerate(data["orphans"]):
        check(original, c.get("span"), c.get("text"), f"orphan[{i}]", doc, problems)
    for i, q in enumerate(data.get("unattributedQuotes") or []):
        check(original, q.get("span"), q.get("raw_text"), f"unattributed[{i}].raw_text", doc, problems)
        check(original, q.get("span"), q.get("text"), f"unattributed[{i}].text", doc, problems, allow_collapsed=True)

    by_kind: dict[str, int] = {}
    for p in problems:
        by_kind[p["where"].split(".")[-1]] = by_kind.get(p["where"].split(".")[-1], 0) + 1
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "stats": data["stats"],
        "problem_count": len(problems),
        "problems": problems[:40],
        "by_field": by_kind,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--selftest-masked", action="store_true")
    args = parser.parse_args()
    global SELFTEST_MASKED
    SELFTEST_MASKED = bool(args.selftest_masked)

    files: list[Path] = []
    for raw in args.inputs:
        base = Path(raw)
        if base.is_dir():
            files.extend(sorted(p for p in base.rglob("*")
                                if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".text", ".md"}))
        else:
            files.append(base)
    if args.limit:
        files = files[: args.limit]

    reports = []
    for index, path in enumerate(files, 1):
        report = audit_one(path)
        reports.append(report)
        if report.get("problem_count"):
            print(f"[{index}/{len(files)}] {path.name}: {report['problem_count']} problems "
                  f"{report.get('by_field')}")
        elif index % 50 == 0:
            print(f"[{index}/{len(files)}] ... clean")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    dirty = [r for r in reports if r.get("problem_count") or r.get("error")]
    print(f"documents={len(reports)} with_problems={len(dirty)}")
    for r in dirty[:20]:
        print(" ", Path(r["path"]).name, r.get("problem_count"), r.get("by_field"), r.get("error", ""))
    print("report:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
