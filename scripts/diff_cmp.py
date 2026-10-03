"""Diff two cmp_commits.py dumps and report evidence/attribution changes.

Quotations are compared by the OWNER's header span, not by group id, because a
group id shifts whenever any earlier group appears or disappears; only a change
of owner is a real attribution change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: str) -> dict[str, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in data}


def key_of(item: dict) -> tuple:
    return (item.get("kind"), tuple(item.get("span") or ()))


def quotes_of(doc: dict) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for g in doc["groups"]:
        owner = tuple(g["header"]["span"])
        for q in g["quotes"]:
            out[tuple(q["span"])] = dict(q, owner=owner, owner_kind="case")
    for a in doc["authorities"]:
        owner = tuple(a["header"]["span"])
        for q in a.get("quotes") or []:
            out[tuple(q["span"])] = dict(q, owner=owner, owner_kind="authority")
    for r in doc.get("records", []):
        owner = tuple(r["header"]["span"])
        for q in r.get("quotes") or []:
            out[tuple(q["span"])] = dict(q, owner=owner, owner_kind="record")
    for q in doc.get("unattributedQuotes", []):
        out[tuple(q["span"])] = dict(q, owner=None, owner_kind="unattributed")
    return out


def main() -> int:
    old = load(sys.argv[1])
    new = load(sys.argv[2])
    print(f"old={len(old)} new={len(new)}")

    total = {"lost_citations": 0, "gained_citations": 0, "lost_groups": 0,
             "gained_groups": 0, "lost_quotes": 0, "gained_quotes": 0,
             "lost_records": 0, "gained_records": 0, "lost_authorities": 0,
             "gained_authorities": 0, "attr_changed": 0, "text_changed": 0,
             "proposition_changed": 0, "caseName_changed": 0}

    for name in sorted(set(old) & set(new)):
        o, n = old[name].get("old"), new[name].get("old")
        if o is None or n is None:
            print(f"[error] {name}: old={old[name].get('old_error')} new={new[name].get('old_error')}")
            continue
        o_cites, n_cites = {}, {}
        for c in [g["header"] for g in o["groups"]] + [c for g in o["groups"] for c in g["children"]] + o["orphans"]:
            o_cites[key_of(c)] = c
        for c in [g["header"] for g in n["groups"]] + [c for g in n["groups"] for c in g["children"]] + n["orphans"]:
            n_cites[key_of(c)] = c
        for k in sorted(set(o_cites) - set(n_cites)):
            total["lost_citations"] += 1
            print(f"[LOST CITE] {name} {k[0]} {k[1]} text={o_cites[k]['text'][:80]!r}")
        for k in sorted(set(n_cites) - set(o_cites)):
            total["gained_citations"] += 1
            print(f"[GAIN CITE] {name} {k[0]} {k[1]} text={n_cites[k]['text'][:80]!r}")
        for k in sorted(set(o_cites) & set(n_cites)):
            if o_cites[k]["text"] != n_cites[k]["text"]:
                total["text_changed"] += 1
                print(f"[TEXT CHANGED] {name} {k[0]} {k[1]} old={o_cites[k]['text'][:60]!r} new={n_cites[k]['text'][:60]!r}")

        o_groups = {g["header"]["span"][0]: g for g in o["groups"]}
        n_groups = {g["header"]["span"][0]: g for g in n["groups"]}
        for start in sorted(set(o_groups) - set(n_groups)):
            total["lost_groups"] += 1
            g = o_groups[start]
            print(f"[LOST GROUP] {name} g@{start} header={g['header']['text'][:70]!r} children={len(g['children'])}")
        for start in sorted(set(n_groups) - set(o_groups)):
            total["gained_groups"] += 1
            g = n_groups[start]
            print(f"[GAIN GROUP] {name} g@{start} header={g['header']['text'][:70]!r} children={len(g['children'])}")
        for start in sorted(set(o_groups) & set(n_groups)):
            og, ng = o_groups[start], n_groups[start]
            if og["caseName"] != ng["caseName"]:
                total["caseName_changed"] += 1
                print(f"[CASENAME] {name} g@{start} old={og['caseName']!r} new={ng['caseName']!r}")
            if [c["span"] for c in og["children"]] != [c["span"] for c in ng["children"]]:
                total["attr_changed"] += 1
                print(f"[CHILDREN] {name} g@{start} old={[c['span'] for c in og['children']]} "
                      f"new={[c['span'] for c in ng['children']]}")
            if og["proposition"] != ng["proposition"]:
                total["proposition_changed"] += 1
                print(f"[PROPOSITION] {name} g@{start}\n    old={og['proposition']!r}\n    new={ng['proposition']!r}")

        o_q, n_q = quotes_of(o), quotes_of(n)
        for span in sorted(set(o_q) - set(n_q)):
            total["lost_quotes"] += 1
            print(f"[LOST QUOTE] {name} {span} {o_q[span]['raw_text'][:80]!r} owner={o_q[span]['owner']}")
        for span in sorted(set(n_q) - set(o_q)):
            total["gained_quotes"] += 1
            print(f"[GAIN QUOTE] {name} {span} {n_q[span]['raw_text'][:80]!r} owner={n_q[span]['owner']}")
        for span in sorted(set(o_q) & set(n_q)):
            a, b = o_q[span], n_q[span]
            if (a["owner"], a.get("attribution_basis")) != (b["owner"], b.get("attribution_basis")):
                total["attr_changed"] += 1
                print(f"[QUOTE ATTR] {name} {span} {a['raw_text'][:50]!r} "
                      f"old={a['owner_kind']}{a['owner']}/{a.get('attribution_basis')} "
                      f"new={b['owner_kind']}{b['owner']}/{b.get('attribution_basis')}")

        o_rec = {tuple(r["header"]["span"]): r for r in o["records"]}
        n_rec = {tuple(r["header"]["span"]): r for r in n["records"]}
        for span in sorted(set(o_rec) - set(n_rec)):
            total["lost_records"] += 1
            print(f"[LOST RECORD] {name} {span} {o_rec[span]['header']['text'][:80]!r}")
        for span in sorted(set(n_rec) - set(o_rec)):
            total["gained_records"] += 1
            print(f"[GAIN RECORD] {name} {span} {n_rec[span]['header']['text'][:80]!r}")
        for span in sorted(set(o_rec) & set(n_rec)):
            if [c["span"] for c in o_rec[span]["children"]] != [c["span"] for c in n_rec[span]["children"]]:
                total["attr_changed"] += 1
                print(f"[RECORD CHILDREN] {name} {span} old={[c['span'] for c in o_rec[span]['children']]} "
                      f"new={[c['span'] for c in n_rec[span]['children']]}")

        o_a = {tuple(a["header"]["span"]): a for a in o["authorities"]}
        n_a = {tuple(a["header"]["span"]): a for a in n["authorities"]}
        for span in sorted(set(o_a) - set(n_a)):
            total["lost_authorities"] += 1
            print(f"[LOST AUTH] {name} {span} {o_a[span]['source']} {o_a[span]['header']['text'][:60]!r}")
        for span in sorted(set(n_a) - set(o_a)):
            total["gained_authorities"] += 1
            print(f"[GAIN AUTH] {name} {span} {n_a[span]['source']} {n_a[span]['header']['text'][:60]!r}")

    print()
    print("TOTALS", json.dumps(total, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
