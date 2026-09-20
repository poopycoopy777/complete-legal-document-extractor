# Case-Citation Identity Verification — Design Spec

Date: 2026-09-20
Status: proposed, awaiting user review
Scope: backend only, `codex/development`, not for public push

## 1. What this stage claims, and what it does not

This adds the first verification stage to a stack that has so far only
extracted. It answers exactly one question, for case citations only:

> Does a real case exist whose reporter citation, name, filing year and court
> all match what this document says?

A pass is reported as `citation_verified`. That string is deliberately narrow.
It does **not** mean, and must never be rendered as meaning:

- that the pin cite points at the quoted page;
- that the quotation appears in the opinion;
- that the case supports the proposition it is cited for;
- that the case is still good law, or has not been reversed, vacated,
  overruled, abrogated or superseded.

Those are separate stages and none of them exist yet. Any consumer surface that
collapses `citation_verified` into "verified" or a green check without that
qualification is misreporting the result.

Statutes, regulations, rules, constitutions and quotations are out of scope for
this stage entirely.

## 2. Positive-only by design

The endpoint returns conclusively verified cases and nothing else.

There is no `invalid`, `fabricated`, `not_found`, `conflict`, or any other
adverse label. A case that is missing from the corpus, weakly matched,
ambiguous between candidates, or conflicting on one of the four checks is
**omitted from the response**.

The reason is evidentiary. The corpus is a 10.07-million-row CourtListener
metadata snapshot, not the universe of American law. Absence from it is not
evidence of non-existence — unpublished dispositions, very recent opinions,
state trial orders and anything outside CourtListener's coverage are simply not
there. Emitting `not_found` for those would manufacture a false accusation of
fabrication against a real citation, which in a filing is worse than saying
nothing. Later stages with different evidence must remain free to reach those
cases.

The caller determines what is unresolved by set difference: submitted group IDs
minus returned group IDs. Unresolved means "this stage reached no conclusion",
never "this citation is bad".

### Abstention is not failure

An outage is categorically different from an abstention and must never be
disguised as one. If the embedding model cannot load, PostgreSQL is
unreachable, the required index is absent, or the statement timeout fires, the
endpoint returns an error at the endpoint level — normally HTTP 503 — and no
partial `verified` array. An empty `verified` array means "ran successfully,
concluded nothing"; it must never mean "the verifier was down".

## 3. API contract

### `POST /api/verify/cases`

The endpoint consumes groups that extraction already produced. It does not
re-extract, does not receive or read the document, and does not independently
resolve short forms.

Request:

```json
{
  "groups": [
    {
      "groupId": "g0",
      "volume": "576",
      "reporter": "P.3d",
      "page": "225",
      "plaintiff": "Ion Media Networks, Inc.",
      "defendant": "West",
      "year": 2025,
      "court": "Colo. App."
    }
  ]
}
```

Fields map one-to-one onto `caselaw.extract.Citation`, taken from the group
**header** only. `groupId` is the `id` of the `CitationGroup`. Requests carry no
document text, no spans and no quotations; this stage needs none of them and
sending privileged text to a verifier that does not use it is unnecessary
exposure.

Response:

```json
{
  "verified": [
    {
      "groupId": "g0",
      "status": "citation_verified",
      "clusterId": 123,
      "checks": {
        "reporterCitation": true,
        "caseName": true,
        "year": true,
        "court": true
      }
    }
  ]
}
```

`checks` is always four `true` values when present, because a result is only
emitted when all four pass. It is included so the response is self-describing
about *what was checked* rather than requiring the reader to know.

Validation and limits:

- `groups` must be a non-empty array, at most 500 entries per request.
- A group missing `volume`, `reporter` or `page` is silently skipped — it can
  never satisfy check 1. This is abstention, not an error.
- Unknown fields are ignored rather than rejected, so extraction can add fields
  without breaking the verifier.
- Malformed request bodies return 422 (FastAPI default). That is a caller
  error, not an abstention.

### Short forms, `Id.` and `supra` inherit

These are never queried. A `ShortCaseCitation`, `IdCitation`, `SupraCitation` or
`ReferenceCitation` is a child of a group; the group's header carries the
identity. If the header verifies, every child inherits that result by virtue of
being in the group. Querying them independently would ask the corpus about a
citation that has no name, no year and often no reporter, and would produce
exactly the low-evidence matches this stage exists to refuse.

The consequence is honest and worth stating: if grouping is wrong, inheritance
is wrong. Grouping still relies on eyecite's backward scan for `supra` and
`id.` (see the README's known gaps), and this stage does not fix that.

## 4. Retrieval

### Embedding contract

The query encoder loads `BAAI/bge-m3` directly through SentenceTransformers.
LM Studio is not used.

The stored vectors declare their contract as `st:BAAI/bge-m3:cls:norm`, and the
query path must reproduce it exactly:

| | |
|---|---|
| Model | `BAAI/bge-m3` |
| Pooling | CLS |
| Dimensions | 1024 |
| Normalization | L2, enabled |

A mismatch on any of these does not raise — it silently returns plausible
nonsense, because cosine distance between differently-pooled vectors is still a
number. The verifier therefore asserts the pooling and dimension configuration
at load time and refuses to start if they disagree.

The model loads once per backend process, lazily on first verification request,
behind a lock so concurrent requests cannot trigger duplicate loads. All
eligible groups in a request are batch-encoded in one call.

### Query

Retrieval is vector similarity over `public.vector_records`, filtered by the
exact predicate:

```sql
WHERE namespace = 'courtlistener_metadata'
  AND source_type = 'cluster_metadata'
```

All values are bound parameters. No SQL is assembled by string interpolation,
including the filter labels.

The transaction is read-only (`SET TRANSACTION READ ONLY`) with a statement
timeout. Candidate count, `ivfflat.probes` and any score threshold are
calibrated against the benchmark in §7, not chosen by intuition.

**Similarity is not proof.** Vector search selects candidates to examine. It
never contributes to the verdict. A candidate at cosine 0.99 that fails the
year check is rejected exactly as hard as one at 0.30.

## 5. The four identity checks

A candidate passes only if all four pass independently. If two or more
candidates pass, the group is **ambiguous and omitted** — it is not resolved by
picking the higher similarity score. Exactly one passing candidate is required.

### 1. Reporter citation

Volume, reporter and page must all match the candidate.

Reporter normalization uses reporters-db — the same source eyecite's detection
is backed by — to map variations to their canonical edition. Normalization must
not collapse series: `F.2d`, `F.3d` and `F.4th` are three different reporters
and a citation to one must never verify against another. The same holds for
`P.2d`/`P.3d`, `A.2d`/`A.3d`, `S.W.2d`/`S.W.3d` and every other series.

Volume and page compare as exact strings after stripping whitespace. No numeric
coercion, no fuzzy digits: a letter-for-digit OCR misread (`3O` for `30`) must
fail this check rather than be repaired. Repairing a garbled citation is how a
fabricated one gets laundered into a real-looking one.

Parallel citations are a known limitation inherited from extraction: the
extractor splits `436 U.S. 658, 98 S. Ct. 2018` into two groups. Each is
verified on its own here. This stage does not merge them.

### 2. Case name

Compared conservatively against the candidate's `case_name`.

Normalization permitted: case folding, whitespace collapse, punctuation
stripping, removal of trailing corporate suffixes (`Inc.`, `LLC`, `Corp.`,
`Co.`, `Ltd.`, `L.P.`), and `&`/`and` equivalence. Party order is significant —
`A v. B` does not match `B v. A`, because on appeal the caption genuinely
reverses and the difference is information.

Not permitted: fuzzy or edit-distance matching, substring containment, matching
on plaintiff alone, or matching on a single common surname. An OCR-damaged name
(`Coffinan` for `Coffman`) must fail this check. Passing it would reintroduce
precisely the OCR failure mode the README documents as invisible to extraction,
except now with a verification badge attached.

The extractor supplies `plaintiff` and `defendant` separately; the candidate
supplies one `case_name` string. Comparison parses the candidate's name on
` v. ` / ` v ` / ` vs. ` and compares sides. A candidate name that does not
parse into two sides fails the check.

### 3. Year

Exact integer equality between the extracted year and the year of the
candidate's `date_filed`.

No tolerance window. A decision issued in December and reported in January is a
real phenomenon, but a ±1 window also admits a wrong case in a series of
similarly-named appeals, and this stage is precision-first. A true citation
excluded by strict year comparison is an abstention and costs nothing; a wrong
case admitted by a loose one is a false green.

A group with no extracted year cannot pass and is omitted.

### 4. Court

Compared conservatively. The candidate supplies `court_id` (a CourtListener
identifier); the extractor supplies a court string as printed in the
parenthetical.

Mapping uses courts-db, which is already a dependency through eyecite. Both
sides normalize to a court identifier and must be equal. If either side fails
to resolve to an identifier, the check fails and the group is omitted — an
unresolvable court is not a matching court.

A group with no extracted court cannot pass and is omitted. This is a real
recall cost: many citations omit the court parenthetical when the reporter
implies it (`410 U.S. 113` needs no `(U.S.)`). Whether to infer court from an
unambiguous reporter is deliberately **deferred** and listed as an open
question in §9 rather than assumed here.

## 6. Database and safety boundary

Live target, confirmed read-only at last inspection:

| | |
|---|---|
| Database | `Storage_Pourage` |
| Host/port | `localhost:5433` |
| Data directory | `D:\PostgreSQL\dev-5433\data` |
| Service | `postgresql-dev-5433` |
| Table | `public.vector_records` |
| Matching rows | 10,070,727 |
| Vector dimensions | 1024 |
| Model tag | `st:BAAI/bge-m3:cls:norm` |

Connection details come from an environment variable or a git-ignored local
`.env`. Credentials are never printed, committed, or copied into this
repository. The existing private configuration at
`D:\THE FUTURE OF LITIGATION\app_v2\backend\.env` is read by the operator, not
by this repository.

Hard boundaries:

- Runtime verification transactions are **read-only** with a statement timeout.
- The only approved live write is the separately invoked IVFFlat index build.
- Tests never touch `Storage_Pourage`. They use fakes, or a database whose name
  ends `_test` and has been confirmed as such at connect time.
- No `drop_all()`, no destructive DDL, no migrations, no teardown fixtures
  against the live database.
- The resolved connection target is reconfirmed before every administrative
  command.
- Unrelated `Storage_Pourage` tables are not touched.

### Index

IVFFlat, selected by the user. A partial cosine index scoped only to the two
target labels.

Built by a separate, manually invoked administrative script — never at
application startup and never inside an API request. Created concurrently so
reads stay available. Existing vectors are not altered or re-embedded.

`lists` and `ivfflat.probes` are calibrated parameters. A starting point may be
documented with its arithmetic, but the values that ship come from the
benchmark.

Two preconditions before any build:

1. **Unresolved extension state.** `vector(1024)` columns and cosine operators
   were usable, but `pg_extension` did not list the `vector` extension. This is
   inconsistent and must be explained before DDL is attempted, not worked
   around. A restored-but-unregistered extension can fail DDL in ways that are
   unpleasant on a 58 GB table.
2. **Preflight.** Confirm the exact database, table, row labels, operator
   class, free disk space, and that no other index build is running.

Long builds run detached and hidden, log progress, and are monitored through
`pg_stat_progress_create_index`. No cleanup or `DROP INDEX` command is ever left
queued behind a build. A `postmaster.pid` is never deleted without first proving
the recorded process is gone and port 5433 is not listening; stale state is
renamed, not deleted.

## 7. Accuracy gate

Test-driven, after this spec is approved and the implementation plan is written.

Required unit and integration coverage:

- request/response validation, including the 500-group cap and skip-on-missing-
  reporter behavior;
- exactly one lazy model load under concurrent requests;
- CLS pooling, 1024 dimensions, L2 normalization asserted at load;
- strict namespace/source filtering;
- reporter normalization that does **not** collapse series (`F.2d` ≠ `F.3d`);
- conservative case-name compatibility, including OCR damage failing;
- exact year comparison;
- conservative court compatibility, including unresolvable court failing;
- children inheriting their group rather than being queried;
- positive-only omission, including the two-passing-candidates ambiguity case;
- explicit 503 for model, database and index outages, with no partial results;
- read-only transaction enforcement;
- bound parameters throughout.

Held-out benchmark, containing clean citations plus: wrong reporter, wrong
page, wrong case name, wrong year, wrong court, OCR damage, parallel reporters,
duplicates, and genuinely ambiguous cases. Emphasis is on preventing false
green results, because abstention is free and a false green is not.

Reported separately, never as one aggregate:

- precision of returned `citation_verified` results;
- recall among citations actually represented in the metadata corpus;
- IVFFlat candidate recall at the chosen `lists`, `probes` and top-k;
- latency for realistic document-sized batches.

Abstentions are never folded into an accuracy number. The user's 95% gate
applies to precision, and no public push happens without it — or without an
explicit request.

## 8. Out of scope

Frontend changes. `web/` belongs to a larger private project and is not touched
or published. Statute, rule, regulation and constitutional verification.
Quotation verification. Pin-cite verification. Proposition support. Subsequent
history and good-law status. Parallel-citation merging. Fixing eyecite's
backward scan for `supra`/`id.`.

## 9. Open questions for review

These are genuine forks where a wrong assumption would be expensive, listed
rather than silently decided:

1. **Court inference from reporter.** A citation with no court parenthetical
   currently cannot verify, which excludes a large and entirely legitimate
   class — every `410 U.S. 113`. Inferring the court from an unambiguous
   reporter (`U.S.` → Supreme Court) would recover them. It also weakens check 4
   from independent evidence into a restatement of check 1. Recommendation:
   ship without inference, measure how much recall it actually costs, and decide
   with that number in hand.
2. **`content` parsing.** Citation and docket text live in the stored
   `content` field, and the reporter citation check depends on parsing it.
   Multiple records must be inspected and the parsing formalized before the
   check can be relied on. If `content` proves inconsistent, check 1 has no
   source and the design needs revisiting.
3. **The unregistered `vector` extension.** Must be explained before DDL.
4. **Corpus coverage is unmeasured.** How much of a real Colorado filing's
   citations exist in `courtlistener_metadata` at all is unknown. That number
   sets the ceiling on recall and should be measured early, because if it is
   low the whole stage is less useful than it looks.
