"""Run an older commit's caselaw package side by side with HEAD on one corpus.

The old package is written to output/_scratch/<sha>/caselaw/ (untracked scratch;
no tracked file is touched) and imported under the package name "oldcaselaw" so
both versions live in one process. Emits a compact JSON per document that a
diff can compare.

Usage:
    python scripts/cmp_commits.py --commit 906a58b --inputs storage --out output/cmp_906a58b_storage.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def materialise(sha: str) -> Path:
    target = ROOT / "output" / "_scratch" / sha / "caselaw"
    target.mkdir(parents=True, exist_ok=True)
    names = subprocess.run(
        ["git", "ls-tree", "--name-only", f"{sha}:caselaw"],
        cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8",
    ).stdout.split()
    for name in names:
        if not name.endswith(".py"):
            continue
        body = subprocess.run(
            ["git", "show", f"{sha}:caselaw/{name}"],
            cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
        (target / name).write_text(body, encoding="utf-8")
    # templates/ is a directory in the tree; copy it verbatim too.
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", f"{sha}:caselaw"],
        cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8",
    ).stdout.split()
    for name in tree:
        if name.endswith(".py"):
            continue
        body = subprocess.run(
            ["git", "show", f"{sha}:caselaw/{name}"],
            cwd=ROOT, capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout
        out = target / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
    return ROOT / "output" / "_scratch" / sha


def load_old(root: Path, package: str):
    spec = importlib.util.spec_from_file_location(
        package, root / "caselaw" / "__init__.py",
        submodule_search_locations=[str(root / "caselaw")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return importlib.import_module(f"{package}.group")


def text_for(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace")
    import pymupdf

    chunks: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            chunks.append(page.get_text("text", sort=True))
    return "".join(chunks)


def summarise(data: dict) -> dict:
    def cite(c: dict) -> dict:
        return {
            "kind": c.get("kind"), "span": c.get("span"), "text": c.get("text"),
            "plaintiff": c.get("plaintiff"), "defendant": c.get("defendant"),
            "case_name": c.get("case_name"), "full_citation": c.get("full_citation"),
            "antecedent": c.get("antecedent"), "pin": c.get("pin_cite"),
            "flags": sorted(c.get("flags") or []),
        }

    return {
        "stats": data.get("stats"),
        "groups": [
            {
                "id": g["id"],
                "caseName": g.get("caseName"),
                "header": cite(g["header"]),
                "children": [cite(c) for c in g["children"]],
                "proposition": g.get("proposition"),
                "propositionSpan": g.get("propositionSpan"),
                "occurrences": [
                    {k: o.get(k) for k in ("citationSpan", "proposition", "propositionSpan", "signal")}
                    for o in (g.get("occurrencePropositions") or [])
                ],
                "quotes": [
                    {k: q.get(k) for k in ("span", "raw_text", "attribution_status",
                                           "attribution_basis", "authority_id", "pin_cite",
                                           "pin_basis", "citation_span")}
                    for q in (g.get("quotes") or [])
                ],
            }
            for g in data.get("groups", [])
        ],
        "authorities": [
            {
                "id": a["id"], "category": a.get("category"), "source": a.get("source"),
                "header": {"span": a["header"].get("span"), "text": a["header"].get("text"),
                           "name": a["header"].get("name"),
                           "short": a["header"].get("is_shortform")},
                "children": [
                    {"span": c.get("span"), "text": c.get("text"), "name": c.get("name"),
                     "short": c.get("is_shortform")}
                    for c in a.get("children", [])
                ],
                "quotes": [
                    {k: q.get(k) for k in ("span", "raw_text", "attribution_status",
                                           "attribution_basis", "authority_id", "pin_cite",
                                           "pin_basis", "citation_span")}
                    for q in (a.get("quotes") or [])
                ],
            }
            for a in data.get("authorities", [])
        ],
        "records": [
            {
                "id": r["id"], "kind": r.get("kind"), "label": r.get("label"),
                "header": {"span": r["header"].get("span"), "text": r["header"].get("text"),
                           "pin": r["header"].get("pin_cite")},
                "children": [
                    {"span": c.get("span"), "text": c.get("text")} for c in r.get("children", [])
                ],
                "proposition": r.get("proposition"),
                "propositionSpan": r.get("propositionSpan"),
                "quotes": [
                    {k: q.get(k) for k in ("span", "raw_text", "attribution_status",
                                           "attribution_basis", "authority_id", "pin_cite",
                                           "pin_basis", "citation_span")}
                    for q in (r.get("quotes") or [])
                ],
            }
            for r in data.get("records", [])
        ],
        "orphans": [cite(o) for o in data.get("orphans", [])],
        "unattributedQuotes": [
            {k: q.get(k) for k in ("span", "raw_text", "attribution_status", "attribution_basis")}
            for q in data.get("unattributedQuotes", [])
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    root = materialise(args.commit)
    old_group = load_old(root, "oldcaselaw")

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
        text = text_for(path)
        entry: dict = {"path": str(path), "name": path.name, "chars": len(text)}
        try:
            entry["old"] = summarise(old_group.group_citations(text).as_dict())
        except Exception as exc:  # noqa: BLE001
            entry["old_error"] = f"{type(exc).__name__}: {exc}"
        if index % 25 == 0:
            print(f"  [{index}/{len(files)}]", flush=True)
        reports.append(entry)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print("documents:", len(reports), "->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
