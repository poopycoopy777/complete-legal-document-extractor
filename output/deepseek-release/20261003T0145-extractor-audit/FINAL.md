# Document Extractor release repair - final handoff

Repository: `D:/complete-legal-document-extractor`, branch `master`.
HEAD: `4ee5fb058dfb174fb85479bbab8eae5c3c1d82f0` (**not committed**; 7 modified
tracked files and 10 new untracked files).
Integration (commit, push, pin, restart) belongs to Codex.
Evidence directory: `output/deepseek-release/20261003T0145-extractor-audit/`.
Machine-readable ledger: `LEDGER.json` in the same directory.

## What this session did

Started from current code at clean HEAD, reproduced defects against real supplied
PDFs, wrote a failing regression for each, repaired the shared cause, and ran the
focused tests and the full extractor suite. Seven defects were demonstrated and
repaired. No defect was inferred from an old checklist entry.

## Gate status

| Gate | Result |
|---|---|
| Full extractor suite | **414 passed** (`.venv\Scripts\python.exe -m pytest tests -q`) |
| Lint | **All checks passed** (`ruff check .`) |
| New regressions | 39 new test cases across 3 new modules and 2 extended ones |
| Span/text contract, 21 orderbench PDFs | 0 violations (unchanged before and after) |
| Page-furniture contamination, same corpus | 0 (unchanged) |
| Silent empty extraction, 100-document storage sample | 0 |
| Live proof of the repairs | **NOT OBTAINED** - the 8010 process predates these edits |

## The seven repairs

`LEDGER.json` carries the full record for each: input path and hash, observed
before, root cause with file and symbol, the repair, the regression, verified
after, and the replay command. Summary:

1. **EXT-1** `caselaw/record_cites.py` - `Colo. App.` was parsed as an appendix
   record cite, so a brief citing no appendix appeared to cite one and the
   parallel reporter's volume became the appendix page. Guarded on the preceding
   reporter token.
2. **EXT-2** `caselaw/ocr.py`, `server/app.py` - everything OCR'd answered
   `pages: []` and `highlights: []`, so no citation in a scanned filing had a
   page. The page table is now rebuilt from the raw per-page lengths OCR already
   measured.
3. **EXT-3** `server/app.py` - a blank page inside a 50-page filing was never
   disclosed because only the document-wide average was tested. Blank pages are
   now reported by number.
4. **EXT-4** `server/app.py` - OCR could replace a thin but exact text layer with
   recognition noise, because the acceptance test was "longer". OCR is now tried
   only where the layer is unusable rather than merely thin.
5. **EXT-5** `caselaw/extract.py` - a repeated full citation that prints its
   short name (`Warne, 2016 CO 50`) came back unnamed and flagged
   `parties_unverified`. The short name is now read from the printed clause,
   with an abbreviation-aware sentence boundary and a refusal of lone
   introductory signals.
6. **EXT-6** `caselaw/extract.py` - `Pinnacol Assurance v. Hoff` produced no
   parties at all because the `ff` is the ligature U+FB00 and the party classes
   were ASCII-only. They now accept any Unicode letter.
7. **EXT-7** `caselaw/group.py` - subsequent history (`aff'd, 908 F.3d 1219`)
   became a separate group with no name, taking the caption of the case it
   affirms. A history gap is now recognised, keeping the later citation's own
   year, court and pin.

## Measured effects on real inputs

| Measurement | Before | After |
|---|---:|---:|
| Appendix record cites on the supplied dismissal | 2 | 0 |
| Groups without a case name, 21 orderbench PDFs | 39 | 38 |
| `parties_unverified` occurrences, supplied dismissal | 2 | 1 |
| Pages table entries for a 2-page scanned PDF | 0 | 2 |
| Highlights for that scan | 0 | 1 (with page) |
| Blank pages reported, 50-page filing | not reported | 3 of 50 named |
| Unnamed groups, three real storage filings | 8 | 6 |
| Subsequent-history merges accepted, those filings | 0 | 2 |

The one remaining `parties_unverified` flag on the supplied dismissal is correct:
it sits on a parallel reporter citation whose own window contains no name. The 38
remaining unnamed groups are all in `00-INDEX.pdf`; see the correction note below.

## What is honestly not done

Full detail is in `LEDGER.json` under `open_gaps`.

* **No live proof.** The 8010 process was started before these edits. EXT-2,
  EXT-3 and EXT-4 are verified by running the repaired module in-process with
  `STORAGE` pointed at a temporary directory, which exercises the same functions
  the API calls, but that is not an integrated replay. A live `/api/extract` call
  still returns the pre-repair appendix record cite for the supplied dismissal
  text. Codex should restart the extractor and then run
  `scripts/verify_ocr_pages.py storage/5a29ad8948434101afcfa0446dc3ee9d.pdf --live`
  and replay the supplied dismissal through the app.
* **Naming coverage is 88.75 percent, measured.** Over 26 documents and 400
  groups (`scripts/audit_naming_coverage.py`): 330 groups named from parties, 25
  named from a caption on a non-header occurrence, and **45 with no naming
  evidence on any member**. Every one of the 20 order bench briefs is 100 percent
  named; the 45 are 38 in `00-INDEX.pdf` plus 7 in five real filings. A group
  with no name gives the identity stage nothing to compare.
* **The seven real-filing naming gaps have five distinct causes**, each with a
  named input in the ledger: a markdown index prints the name and the citation in
  separate cells; a real table of authorities prints the name on the line above
  the citation, across a dot leader; a citation inside a nested parenthetical
  takes the inner caption; a caption shaped `Case, No. CIV 16-0318 JB/SCY,` is
  not read; and a name wrapping onto the line before its citation is missed.
* **Unadjudicated dimensions are untouched.** Natural-filing semantic gold,
  treatment and rules coverage remain unadjudicated. Extracting a rule citation
  is not proof its authoritative text is verified, and nothing here changes that.

## Corrections to earlier counts in this session

Two measurements in the first draft of `PROGRESS.md` were wrong and are corrected
here, because leaving them would overstate the defect:

* "39 groups without a case name" counted only the header occurrence. A group is
  named when any member carries the caption, which is what
  `CitationGroup.case_name` already does. The correct figure over the same corpus
  is 38, all in `00-INDEX.pdf`.
* A first pass suggested real tables of authorities were losing names. Running
  `scripts/audit_split_authorities.py` over two filings that each carry a table
  of authorities found 0 citations appearing in more than one group, so the body
  occurrence names the group and the table does not create a second card.

The remaining seven real-filing gaps are confirmed individually with their
context printed in `naming-coverage-sample.json`.


## State for integration

```text
 M caselaw/extract.py            (EXT-5, EXT-6, docket-slash normalisation)
 M caselaw/group.py              (EXT-7)
 M caselaw/ocr.py                (EXT-2)
 M caselaw/record_cites.py       (EXT-1)
 M server/app.py                 (EXT-2, EXT-3, EXT-4)
 M tests/test_parallel_paragraphs.py   (EXT-5)
 M tests/test_record_cites.py          (EXT-1)
?? tests/test_document_pages.py        (EXT-2, EXT-3, EXT-4)
?? tests/test_ligature_captions.py     (EXT-6)
?? tests/test_subsequent_history.py    (EXT-7)
?? scripts/audit_contract.py
?? scripts/audit_corpus_probe.py
?? scripts/audit_furniture.py
?? scripts/audit_history_merges.py
?? scripts/audit_history_rejects.py
?? scripts/audit_unnamed_groups.py
?? scripts/dump_extraction.py
?? scripts/probe_upload.py
?? scripts/repro_pdf.py
?? scripts/verify_ocr_pages.py
?? output/                      (generated evidence; not for commit)
```

The `scripts/` additions are read-only probes and reproducers. They write only to
the path given on their command line, and the ones that exercise upload redirect
`STORAGE` to a temporary directory. They are useful for the integrated replay and
for regression hunting later; they are not required by the product.

## Suggested integration order

1. Review the diff, especially `caselaw/extract.py` `_derive_short_case_name` and
   `caselaw/group.py` `_is_subsequent_history`, which are the two places a wrong
   answer could attach one case's name to another.
2. Run `.venv\Scripts\python.exe -m pytest tests -q` and `ruff check .`.
3. Replay `04-2025CV111-2026-05-22-12b5-dismissal.pdf` through the API and check
   that record cites are empty, that all 10 groups carry a case name, and that
   `parties_unverified` appears once.
4. Restart the extractor on 8010, then replay `storage/5a29ad8948434101afcfa0446dc3ee9d.pdf`
   and confirm `pages` is non-empty with `highlights` carrying a page.
5. Replay `storage/263afae0799f45b2b45306907ce00975.pdf` and confirm the blank-page
   warning names pages 1, 31 and 40.
6. Bump `services.lock.json` and re-check `GET http://127.0.0.1:8030/api/services`
   reports `commit_verified: true` for the extractor.

## Preserved

`storage/` was not written except by the API's own upload path; `data/` and the
Colorado opinion packages were untouched; no environment file was read, printed or
modified; no database was contacted; `D:/legal-app` `runs/` and
`fullbench/results/` were read only; no commit, branch, worktree, reset, clean or
stash was performed; no service was restarted and no port changed; and neither
`D:/legal-app` nor `D:/The Verifyer` was edited.
