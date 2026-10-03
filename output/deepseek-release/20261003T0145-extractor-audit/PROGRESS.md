# Extractor release repair - progress

Repository: `D:/complete-legal-document-extractor`, branch `master`, no commit made.
Session owner: DeepSeek. Integration, commits, pins and service restarts belong to Codex.

Started from clean HEAD `4ee5fb058dfb174fb85479bbab8eae5c3c1d82f0`.

Evidence directory: `output/deepseek-release/20261003T0145-extractor-audit/`
All scripts added are read-only probes under `scripts/`; they write only to paths
given on their command line.

## Status

| # | Defect | State | Regression |
|---|---|---|---|
| 1 | `Colo. App.` reporter parsed as an appendix record cite | REPAIRED | `tests/test_record_cites.py::TestScopeDiscipline` (5 new) |
| 2 | OCR'd documents lost the whole page table and every highlight | REPAIRED | `tests/test_document_pages.py::TestOcrUploadKeepsPageProvenance` |
| 3 | Blank pages inside a text-layer filing were never disclosed | REPAIRED | `tests/test_document_pages.py::TestPartialScanIsReported` |
| 4 | Hallucinated OCR could replace a real but thin text layer | REPAIRED | `tests/test_document_pages.py` (gate in `server/app.py`) |
| 5 | Repeated full citations lost the printed short name and were flagged `parties_unverified` | REPAIRED | `tests/test_parallel_paragraphs.py` (5 new) |
| 6 | Typographic ligatures and accents broke party extraction | REPAIRED | `tests/test_ligature_captions.py` (11 new) |
| 7 | Subsequent history was split into a separate, wrongly named group | REPAIRED | `tests/test_subsequent_history.py` (18 new) |

Full suite: **411 passed**. `ruff check .`: **All checks passed**.
Span-contract audit on 21 orderbench PDFs: **0 violations** before and after.

## Defect 5: a repeated citation lost the name printed in front of it

Real input: `04-2025CV111-2026-05-22-12b5-dismissal.pdf` (same hash as defect 1).

The brief cites Warne three times. The first prints the full caption
("Warne v. Hall, 2016 CO 50, para. 12, 373 P.3d 588, 593"); the other two print
the short name ("Warne, 2016 CO 50, para. 24, 373 P.3d at 596"). Those two
occurrences came back with no name at all and this flag:

```text
parties_unverified: eyecite reported '' v. 'Rule 12(b)(5). Warne', no 'v.' pattern
in this citation's own window
```

Root cause, two parts:

* `caselaw/extract.py` read the short name from `metadata.antecedent_guess`, but
  on the eyecite version this repository pins that attribute is **always None**,
  so the branch never fired. Every occurrence showed `antecedent=None`.
* The available substitute, `metadata.defendant`, crosses sentence boundaries:
  eyecite reported `'Rule 12(b)(5). Warne'` for one occurrence. Adopting it
  directly would have named the case after a rule citation.

So the occurrence was reported as carrying no naming evidence when the filing
prints the name on the page. Downstream that is a caption mismatch against the
case the filing names.

Repair: `_derive_short_case_name` / `_clause_tail` in `caselaw/extract.py`. The
name is taken from the last clause before the citation, with sentence breaks cut
at an abbreviation-aware boundary (so `Bell Atlantic Corp.,` keeps its period)
and the run validated as capitalized tokens with `of`/`the`/`for`/`and`
connectors. A lone introductory signal is refused, so `See, 550 U.S. 544` yields
no name rather than a case called "See". A non-adversarial clause is delegated to
the existing `_derive_case_name`.

Verified on the fixture: both occurrences now carry `case_name='Warne'`, the
flag is gone, only one `parties_unverified` flag remains in the whole document
(legitimately, on a parallel reporter with no name in its own window), and all
10 groups keep their case names.

## Defect 6: party names carrying a typographic ligature or accent were dropped

Real input: `01-2025CV36-2026-04-22-msj-denied.pdf` at offsets 7868-8349,
`Pinnacol Assurance v. Hoff, 2016 CO 53,` where the "ff" is U+FB00.

`_derive_parties` returned `(None, None)` for the full caption. Root cause:
`_PARTY_BODY` and `_PARTY_HEAD` in `caselaw/extract.py` accepted only
`[A-Za-z0-9...]`, and the head was a literal `[A-Z]`. PDF text layers carry the
typographic ligatures the typesetter used, so `Hoff` printed as `Ho\ufb00` ended
the match early and no party was captured.

This was the only unnamed group in the entire 21-document order bench corpus
outside its index: the group count of unnamed groups went 39 -> 38, and the
remaining 38 are all in `00-INDEX.pdf`, whose table of authorities prints names
and citations in separate columns.

Repair: the party classes are Unicode-aware (`[^\W\d_]` for letters) and the
"must open on a capital" rule moved into a lookahead, so it still rejects
lower-case prose while accepting `\u00c5berg`, `Mu\u00f1oz` and `Ho\ufb00`.
Covered by `tests/test_ligature_captions.py`, which includes the guard that
prose is still not a party.

## Defect 7: subsequent history became a separate, wrongly named case

Real inputs: `storage/0385b985cbe443ba9e7e297f664764c3.pdf`,
`storage/23fb36fee64f48aa952c765bfc3be0e7.pdf`, both real filings.

A brief writes `..., aff'd, 908 F.3d 1219` or `..., report and recommendation
adopted, 2013 WL 1658203`. eyecite reads the history citation as its own full
citation. `_merge_parallel_citations` merged a parallel reporter
(`34 Colo. 372, 83 P. 361`) because the gap was only a pin and a comma, but it
had no rule for a history phrase, so the affirmance became its own group. That
group had no party and no name, and the only caption before it belonged to the
case it affirms -- a case reported under the wrong authority.

Repair: `_is_subsequent_history` in `caselaw/group.py` accepts a gap made of a
pin, the original's own court-and-year parenthetical, and a history phrase
(`aff'd`, `affirmed`, `rev'd`, `vacated`, `cert. denied`,
`report and recommendation adopted`, `overruled on other grounds`, ...). A
history merge keeps the later citation's own year, court and pin, because an
affirmance is a different decision of the same case.

Covered by `tests/test_subsequent_history.py`, including the guards: an
unrelated second case still forms its own group, and a case cited inside another
case's parenthetical does not merge into it.

## Defect 1: a reporter abbreviation became a record citation

Real input: `D:/legal-app/output/orderbench-briefs/pdf/04-2025CV111-2026-05-22-12b5-dismissal.pdf`,
sha256 `ec77b49376a82b1743a1ccceadbdac5abf9511dd66be50cac363b658eb5ff518`, 4 pages.

`extract_record_cites` reported two appendix citations on a brief that cites no
appendix at all:

```text
REC appendix 'Appendix' (4098, 4111) '306' 'App. 306, 571'
REC appendix 'Appendix' (9280, 9289) '2004' 'App. 2004'
```

Both are the reporter abbreviation `Colo. App.`:

* offset 4098 is `Sullivan v. Davis, 39 Colo. App. 306, 571 P.2d 1103, 1105 (1977).`
* offset 9280 is `E-470 Public Highway Auth. v. Revenig, 91 P.3d 1038, 1045 (Colo. App. 2004).`

Root cause: `caselaw/record_cites.py`, the `_APPENDIX` pattern matched the `App.`
inside `Colo. App.` and took the following digits as an appendix pin. The pin for
the first cite was then the parallel reporter's volume (`571`) rather than the
page, so a reader would be sent to the wrong place in a document that does not
exist. The false cites also entered `caselaw/authorities.py::_keep_supported_id_forms`
as "another citation between the authority and this Id.", which can suppress a
legitimate `Id.` attachment.

Repair: `_is_reporter_app(text, start)` in `caselaw/record_cites.py`. A match is
rejected when the abbreviation printed immediately before `App.` is a reporter
token (`Colo.`, `N.C.`, `Ill.`, `Ind.`, `Fla.`, `Ct.`, ...), unless the text
immediately before `App.` names a document (`Appellant's`, `Joint`, `Record`,
`App. to`). No name whitelist, no case-specific rule.

Verified: both `App.` occurrences are gone from the fixture and every genuine
appendix form still counts (`App. 58`, `Appellant's App. 136-38`).

## Defect 2: OCR discarded page provenance

Real input: `storage/5a29ad8948434101afcfa0446dc3ee9d.pdf`
(sha256 `8ee886bc3aa026bbd9caf6afcf4bf87d00d3ef6dad7bb5695ae23c7228b000f2`, 2 image
pages) and `storage/35996a83a8024e21ac11b477062694d5.pdf` (1 image page).

The running service on port 8010 answered a real scan with:

```text
textSource=ocr pageCount=2 pages_table=0 highlights=0
ocr={"engine": "tesseract v5.5.0.20241111", "dpi": 300, "pages": 2, "chars": 1386}
```

Root cause: `server/app.py::upload_document` set `pages = []` when OCR text
replaced the embedded text, with the comment that the embedded offsets no longer
describe the text. True, but the page table was then simply dropped. A scanned
filing reported `pageCount: 2` with no page for any citation and no highlight at
all, and the orchestrator maps every span to a page through that table.

The information needed was already computed and discarded: `OcrResult.page_chars`
counts *stripped* text, so it cannot rebuild offsets, but the raw per-page length
can.

Repair:

* `caselaw/ocr.py`: `OcrResult` records `raw_page_chars`, the verbatim length of
  each recognised page, and exposes `page_ranges()`.
* `server/app.py`: `page_ranges(page_lengths)` and `page_table(page_lengths)`
  build the offset table, and the OCR branch rebuilds it from `raw_page_chars`.
  Only pages that carry text get a range, so no two ranges share a start and no
  offset resolves to two pages.

Verified against the repaired checkout, in process, with `STORAGE` redirected to
a temporary directory (the repository's `storage/` is untouched):

```text
pageCount: 2, pages_table: 2, highlights: 1, highlights_with_page: 1
page_table_last_end: 1386, text_length: 1386
spans_ambiguous: 0, spans_without_page: 0
CONTRACT_OK
```

The same probe against the still-running pre-repair service returns
`pages_table: 0, highlights: 0, CONTRACT_BROKEN`. **This repair is not live until
Codex restarts the extractor on 8010.**

## Defect 3: blank pages inside a normal filing were never disclosed

Real input: `storage/263afae0799f45b2b45306907ce00975.pdf`, 50 pages, 70,889
characters, pages 1, 31 and 40 producing almost no text.

Before the repair the response carried `warning: null`. The document-level average
is 1,400 characters per page, far above `_MIN_CHARS_PER_PAGE`, so neither branch
of `_text_layer_warning` fired. Citations printed on the three blank pages were
absent with nothing in the response saying so.

Repair: `_text_layer_warning` also takes the per-page lengths and reports pages
that carry almost no text. `_pdf_text_and_pages` now returns those lengths.

Verified on the real document:

```text
WARNING: 3 of 50 page(s) carry almost no text (pages 1, 31, 40). Those pages may
be scans, photographs or images, and any citation printed on them is missing from
this result.
```

## Defect 4: OCR could overwrite a real text layer with hallucinated text

Found while building the tests for defect 2. A two-page PDF whose embedded layer
held one short case citation was run through the real upload path; Tesseract
returned more characters than the embedded layer, so `len(ocr) > len(embedded)`
let garbled OCR text replace exact text already in the document. The unstated
assumption was that longer means better, which is false when the embedded layer is
short but exact.

Repair: the decision to OCR is now made only below
`_NO_TEXT_LAYER_CHARS_PER_PAGE = 20`, a level at which the layer is unusable
rather than merely thin. Between 20 and 100 characters per page the layer is kept
and reported through defect 3's warning instead.

## Inputs and hashes

| Input | sha256 | Use |
|---|---|---|
| `D:/legal-app/output/orderbench-briefs/pdf/04-2025CV111-2026-05-22-12b5-dismissal.pdf` | `ec77b49376a82b1743a1ccceadbdac5abf9511dd66be50cac363b658eb5ff518` | defect 1 |
| `storage/5a29ad8948434101afcfa0446dc3ee9d.pdf` | `8ee886bc3aa026bbd9caf6afcf4bf87d00d3ef6dad7bb5695ae23c7228b000f2` | defect 2 |
| `storage/35996a83a8024e21ac11b477062694d5.pdf` | 1 page, no text layer | defect 2 |
| `storage/263afae0799f45b2b45306907ce00975.pdf` | `a4ace67a6666200c41f9c049ae52440ff8c10cd9d387dc3802d2cbb53cb6e355` | defect 3 |

## Corpus survey already done (evidence for the next step)

`scripts/audit_corpus_probe.py` over `storage/`: 351 PDFs, 100 unique hashes,
98 with a usable embedded layer, 2 with none, 3 partially scanned, 0 silent
empty results, 0 page-range overlaps, 0 read errors.
Report: `corpus-probe-storage.json`.

`scripts/audit_contract.py` over the 21 orderbench PDFs: 755 spans, **0**
span/text mismatches, 0 out-of-range spans, 0 silent empty results.
Report: `contract-audit-orderbench.json` and the later re-runs.

`scripts/audit_furniture.py` over the same 21: 0 propositions contaminated by a
running head or page furniture, 0 reused proposition windows.
Report: `furniture-audit-orderbench.json`.

`scripts/audit_naming_coverage.py` over the 21 orderbench PDFs plus five real
storage filings: 26 documents, 400 groups, 330 named from parties, 25 named from
a caption on a non-header member, **45 with no naming evidence on any member**.
All 20 orderbench briefs are 100 percent named; the 45 are 38 in `00-INDEX.pdf`
and 7 in five real filings.
Report: `naming-coverage-sample.json`.

`scripts/audit_split_authorities.py` over two filings that each carry a table of
authorities: 71 groups, 0 citations appearing in more than one group.
Report: `split-authorities-sample.json`.

`scripts/audit_history_merges.py` over `storage/`: 356 documents, 4896 groups,
6700 adjacent full-citation pairs, 123 parallel merges, 0 history merges.
Report: `history-merges-storage.json`. The rule was verified separately on the
three filings where it applies: 2 accepted, 0 wrongly refused.
Report: `history-merges-storage-sample.json`.

## Corrections to counts stated earlier in this file

* "39 groups without a case name" counted only the header occurrence. A group is
  named when any member carries the caption, so the figure over the same corpus
  is 38, all in `00-INDEX.pdf`. See `naming-coverage-sample.json`.
* A first pass suggested real tables of authorities lost names. Two filings with
  tables of authorities showed 0 split citations, so the body occurrence names
  the group. The seven real-filing naming gaps that do exist are listed in
  `LEDGER.json` under GAP-1 with their distinct causes and inputs.

## Replay commands

```powershell
cd D:\complete-legal-document-extractor
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -m pytest tests -q
& "$HOME\AppData\Local\Programs\Python\Python312\Scripts\ruff.exe" check .

# Defect 1, on the real supplied PDF
.\.venv\Scripts\python.exe scripts\repro_pdf.py `
  'D:\legal-app\output\orderbench-briefs\pdf\04-2025CV111-2026-05-22-12b5-dismissal.pdf'

# Defect 2, before a restart
.\.venv\Scripts\python.exe scripts\verify_ocr_pages.py `
  storage\5a29ad8948434101afcfa0446dc3ee9d.pdf --in-process

# Defect 3
.\.venv\Scripts\python.exe scripts\verify_ocr_pages.py `
  storage\263afae0799f45b2b45306907ce00975.pdf --in-process
```

## Open items

* The extractor process on 8010 is still serving the pre-repair build. Codex owns
  the restart. Until then, EXT-2, EXT-3 and EXT-4 are repaired in the checkout
  only. A live `POST /api/extract` still returns the pre-repair appendix record
  cite for the supplied dismissal text.
* Seven real-filing citation groups carry no naming evidence, classified by
  `scripts/audit_naming_gaps.py` into five shapes. Details, inputs and counts are
  in `LEDGER.json` under GAP-1 and in `naming-gaps-sample.json`.
* Not audited: parallel-reporter pin ownership on the long orderbench PDFs,
  rule subsection ownership, and proposition occurrence ownership on
  multi-occurrence groups. The span contract is clean on those documents, but
  that only proves offsets, not semantics.

## Final state

| Gate | Result |
|---|---|
| Full suite | 414 passed |
| Lint | All checks passed |
| Span contract, 21 orderbench PDFs | 0 violations |
| Furniture contamination, same corpus | 0 |
| Supplied dismissal | 10 groups, all named, 0 false record cites, 13 authorities including C.R.C.P. 26(b)(1) and 121 |
| Naming coverage, 26 documents / 400 groups | 88.75 percent; every orderbench brief 100 percent |
| Committed | No - Codex integrates |

Handoff documents: `FINAL.md` (report), `LEDGER.json` (machine-readable).

## Changed files

```text
 M caselaw/ocr.py
 M caselaw/record_cites.py
 M server/app.py
 M tests/test_record_cites.py
?? tests/test_document_pages.py
?? scripts/audit_contract.py
?? scripts/audit_corpus_probe.py
?? scripts/audit_furniture.py
?? scripts/dump_extraction.py
?? scripts/probe_upload.py
?? scripts/repro_pdf.py
?? scripts/verify_ocr_pages.py
?? output/            (generated evidence, not for commit)
```
