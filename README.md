# Complete Legal Document Extractor

Extracts legal authorities and quotations from briefs, opinions and filings:
case law, short citations, `Id.`, `supra`, federal and state statutes,
regulations, constitutions, rules of procedure and evidence, and attributed or
unattributed quoted language.

Detection is deterministic — eyecite and CiteURL, not a language model. Nothing
is generated, nothing is guessed, and every disagreement between sources is
surfaced rather than silently resolved.

**No verification.** Nothing here has been checked against an authority. A
citation appearing in the output means it was found in the document, not that
the authority exists or says what the document claims. A linked quotation means
the document structurally attributes that language to an authority; it does not
prove the attribution is accurate.

## Install

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

The commands above use Windows paths. On Linux or macOS, use
`.venv/bin/python` instead.

## Run it

```bash
.venv/Scripts/python.exe -m caselaw sample.txt --json
.venv/Scripts/python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8010 --reload
```

On Windows, `start.bat` launches the API on localhost. Interactive API
documentation is available at `http://127.0.0.1:8010/docs`.

The HTTP adapter accepts text directly at `POST /api/extract` and `.pdf`,
`.txt`, `.text`, or `.md` files at `POST /api/documents`. It limits direct text
to 2,000,000 characters, uploads to 64 MB, and PDFs to 500 pages. These are
resource-safety bounds, not legal-document assumptions; library callers can use
`caselaw.group.group_citations()` directly.

## Measured accuracy

From `benchmark/`, over 10 real filings across 5 matters and both sides of the
caption. Five documents were injected with 17 recognized-format extraction
targets and one unknown-reporter rejection probe each, all at known offsets.

| | |
|---|---|
| Recognized-format injected recall | **85/85 = 100%** |
| Metadata errors | **0** |
| Unknown-reporter rejection probes | **5/5 passed** |
| Unexpected matches | **0** |

The rejection probe uses the invented reporter `Fake.`. It is not counted as an
extraction target because case-law detection is intentionally backed by
reporters-db. Impossible authority numbers that use recognized reporters or
code names remain extraction targets; deciding whether they exist belongs to a
downstream verifier.

What this does **not** measure: citations already in the source text that the
extractor misses. Injection cannot find unknown unknowns. Precision is reported
as a raw count for manual review, not scored.

### State coverage

`benchmark/state_fixtures.py` builds a citation for every state code from that
state's own CiteURL pattern and checks it extracts back to the same state.

| | |
|---|---|
| Generated fixtures | 74 across 30+ codes |
| Extracted to the right state | **65** |
| Extracted to the **wrong** state | **0** |
| Not extracted | 9 |

Zero cross-state misattribution is the property that matters: 86 generated
templates do not steal each other's citations. A Colorado citation reported as
Nevada law would be worse than no match, because it is wrong with confidence.

Of the 9 misses, 6 were the fixture generator building a citation the state
does not actually use — those forms extract correctly when written properly
(`735 ILCS 5/2-619`, `Mass. Gen. Laws ch. 265, § 13A`, `N.Y. Penal Law
§ 120.00`, `Fla. Admin. Code R. 62-4.070`). The rest are recorded under known
gaps.

This proves a template matches text written to its own specification. It does
not prove the specification matches what practitioners in that state write —
that needs real filings from those jurisdictions.

**The dominant risk is not the extractor.** Two of the ten documents produced
zero extractable text — image scans with no text layer, including a 36-page
Colorado Supreme Court opinion. Before OCR those returned "0 citations", which
reads identically to a document that cites nothing.

## Layout

```
caselaw/extract.py      case law detection + bounded-window metadata, flags
caselaw/authorities.py  statutes, regulations, rules, constitutions
caselaw/group.py        clustering, lossless quote extraction and attribution
caselaw/ocr.py          OCR for PDFs with no text layer
caselaw/review.py       human review findings (proposes, never rewrites)
caselaw/__main__.py     CLI: python -m caselaw <file.txt> [--json] [--flagged-only]
server/app.py           FastAPI
tests/                  regression and upstream-behaviour tests
benchmark/              corpus builder and scanner
```

The public repository contains the extraction backend only. Consumer UIs,
databases and verification services are deliberately separate.

## Upstream defects worked around

Each has a test that pins the upstream behaviour. If one starts failing after an
upgrade, the workaround can probably come out.

**eyecite ≥ 2.7.0 — backward scan crosses citation boundaries.**
`helpers._scan_for_case_boundaries` walks 28 words and breaks on `;` and quotes
but not on a period, because periods are ambiguous in legal abbreviations. It
therefore reads the *previous* citation's year parenthetical and party names.
Two citations in sequence come back with their years swapped. Detection is still
trusted; year, court and party names are re-derived from windows bounded by
adjacent citation spans.

**CiteURL — templates loaded without an encoding.** `citator.py:366` calls
`read_text()` with no encoding argument. On any machine whose default is not
UTF-8 — every stock Windows install — the section sign in the bundled patterns
decodes as `Â§`, so no pattern can match a real `§`. Silently, every
`42 U.S.C. § 1983` in every document is missed. Templates are loaded as UTF-8
explicitly.

**CiteURL — bare numbers as short-form statutes.** The idform patterns accept a
bare section token once any full citation has been seen, so every page number,
paragraph number and year afterwards matches. One 82,000-character answer brief
reported 816 statute citations, of which 710 were bare numbers. A short form now
requires a section sign, "section"/"sec.", "id." or a code name.

**CiteURL — state codes known only by their long form.** The templates recognise
"Colo. Rev. Stat." but not "C.R.S.", and not the postfix form several states use
("§ 24-72-303, C.R.S."). Prefix and postfix patterns are generated for every
state from that state's own token structure, resolving the `inherit` chain first
because most states borrow their pattern from another. 86 generated templates.

**CiteURL — two states cannot match their own declared abbreviation.** Rhode
Island and South Dakota both inherit Alabama's pattern, which requires
`(C(odes?|\.)|Stat(utes|s?\.?))` after the state name. Their actual names end in
"Laws" — `R.I. Gen. Laws`, `S.D. Codified Laws` — which matches neither branch,
so the bundled templates can never match the abbreviation they themselves
declare. The generated initialism forms (`RIGL`, `SDCL`) are the only way these
two states are matched at all. Pinned by
`tests/test_state_coverage.py::test_upstream_long_forms_remain_broken`.

## Quotations and attribution

Every explicitly paired straight or curly double quotation is retained with its
exact document span, raw source text and whitespace-normalized display text.
PDF line wrapping does not break a quotation. Quotations up to 2,000 characters
are accepted so ordinary block quotations survive while damage from an
unmatched opening mark remains bounded.

Attribution is structural and conservative:

- A nearby following full citation, short citation, `Id.`, `supra`, statute,
  regulation, rule or constitutional citation links the quotation to that
  authority group.
- The output records why it linked (`following_id`,
  `following_short_citation`, `following_authority`, and similar values).
- Quotations without a structural attribution are returned under
  `unattributedQuotes`; they are never discarded or guessed away.
- `raw_text` plus `span` preserves provenance. `text` is normalized only for
  display and searching.

The statistics distinguish total, linked, ambiguous and unattributed
quotations. A linked quotation records what the filing claims, not what the
cited authority actually says.

## OCR

PDFs with no usable text layer are recognised with Tesseract. The original file
is never modified; pages are rasterised in memory. A document is either
`embedded` or `ocr` — never a blend — and which one is recorded in the API
response along with the engine version, DPI and page count.

Raising DPI does not help on fixed-resolution page images: measured across
200/300/400/600 dpi on one opinion, character counts were identical (~48,120)
and the error rate did not improve. It only costs time.

OCR creates two failure modes the extractor cannot see on its own:

- **A misread party name passes through with full confidence.** `Coffinan v.
  Williamson, 348 P.3d 929` extracts cleanly with no flag, because eyecite
  matches on reporter, volume and page — not the name.
- **A misread reporter deletes the citation.** `30 R3d 197` and `3O P.3d 197`
  are not extracted at all. Silent recall loss, no error.

## Review layer

`caselaw/review.py` finds what extraction cannot see. It proposes; it never
rewrites. Automatic correction of a garbled citation is how fabricated citations
get made.

- **Missed citations** — citation-shaped text that was not extracted, with
  suggestions drawn from reporters-db at edit distance 1.
- **Suspect names** — party names holding a classic OCR confusion (`in`↔`m`,
  `li`↔`h`). A candidate is only offered when that spelling appears **elsewhere
  in the same document**, so the suggestion is evidence rather than a guess.
  Without that rule the detector fires on "Williamson" and "People".
- **Inconsistent names** — one reporter citation carrying two case names. No
  majority is assumed: on a real opinion the misread spelling outnumbered the
  correct one 11 to 1.

On the 36-page OCR'd opinion this produces **one finding**, and it is correct.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

Current validation: 104 tests, clean Ruff checks, Python bytecode compilation,
`pip check`, and a dependency audit with no known vulnerabilities reported.

## Known gaps

- `supra`/`id.` grouping still uses eyecite's backward scan — the likeliest
  source of wrong grouping.
- Parallel citations (`436 U.S. 658, 98 S. Ct. 2018`) split into two cases.
- California-style pre-citation years flag rather than resolve.
- 22 of 67 state code templates get no initialism (mostly administrative codes);
  they still match by long form.
- A letter-for-digit misread in a volume (`3O` for `30`) is not detected.
- Layout-only block quotations without quotation marks are not detected; doing
  so reliably requires retaining PDF layout semantics rather than guessing from
  indentation in flattened text.
- Maryland's subject-volume form with a comma (`Md. Code, Crim. Law § 3-203`)
  and the Virgin Islands form that puts the title before the code name
  (`14 V.I.C. § 2251`) are not matched. Both are pinned by tests so a fix is
  noticed.
- Verification does not exist. It is the structural fix for both OCR failure
  modes and for fabricated citations generally.

## Privacy

`storage/` holds uploaded documents and is git-ignored, as is
`benchmark/corpus/`. Both contain real client filings. Do not commit them.

## License

Licensed under the Apache License 2.0. See `LICENSE` and `NOTICE`.
