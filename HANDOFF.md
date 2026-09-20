# Development Handoff: Case-Citation Identity Verification

Date: 2026-09-20

## Repository state

- Repository: `D:\Coopers legit caselaw statute rules ect estractor`
- Public remote: `https://github.com/poopycoopy777/complete-legal-document-extractor`
- Development branch: `codex/development`
- Current development HEAD: `2b65df1` (`Measure fifty-state coverage instead of asserting it`)
- Public baseline: `b75a525` on `master`
- Do not modify or publish the frontend. `web/` belongs to a larger private project.
- Do not push, publish, merge, or release this verification work unless the user explicitly asks.
- The earlier state-coverage files are now part of commit `2b65df1`.

## Current product boundary

The existing backend is an extraction stack. It extracts case citations, short
forms, `Id.`, `supra`, statutes, regulations, rules, constitutions, and quoted
language. Extraction must remain deterministic and usable without a database or
model.

The next slice adds the first verification stage for **case citations only**.
It does not verify statutes, rules, quotations, propositions, pin cites, or
subsequent history/good-law status.

## Approved verification behavior

Add a separate backend endpoint:

`POST /api/verify/cases`

The endpoint receives the full case groups already produced by extraction. It
must not re-extract the document or independently search `Id.`, short citations,
or `supra`. Those references inherit the identity result of their extracted
full-case group.

A case citation may light green only when one candidate independently passes all
four identity checks:

1. Reporter citation resolves to the candidate.
2. Extracted case name matches the candidate.
3. Extracted year matches the candidate filing year.
4. Extracted court matches the candidate court.

The successful status is `citation_verified`. This means only that the case
citation's identity was confirmed. It must never imply that the pin cite,
quotation, legal proposition, treatment, or good-law status was checked.

This is a positive-only stage. Return only conclusively verified matches. If a
case is missing, weak, conflicting, or ambiguous, omit its per-case result
entirely. Do not emit adverse labels such as `invalid`, `fabricated`,
`not_found`, or `conflict`; later verification stages must remain free to try
those cases. The caller can determine which groups remain unresolved by
comparing submitted group IDs with returned verified group IDs.

Operational failures are different from abstention. If PostgreSQL, the model,
or the required index is unavailable, return an explicit endpoint-level error
(normally HTTP 503). Never disguise a verifier outage as an empty successful
result.

Illustrative positive-only response:

```json
{
  "verified": [
    {
      "groupId": "case-1",
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

No frontend changes are part of this slice.

## Embedding contract

The query encoder must lazy-load `BAAI/bge-m3` directly through
SentenceTransformers. Do **not** use LM Studio.

The stored vectors identify their contract as:

`st:BAAI/bge-m3:cls:norm`

The query path must match that contract:

- SentenceTransformers model: `BAAI/bge-m3`
- Pooling: CLS
- Dimensions: 1024
- L2 normalization: enabled
- Load once per backend process, guarded against concurrent duplicate loads
- Batch-encode all eligible full-case groups in a request

Vector similarity retrieves candidates; it is not itself proof. Only the four
deterministic identity checks may produce `citation_verified`.

## Verified live database target

The live corpus was inspected read-only and confirmed as:

- PostgreSQL database: `Storage_Pourage`
- Host/port: `localhost:5433`
- Data directory: `D:\PostgreSQL\dev-5433\data`
- Table: `public.vector_records`
- Namespace: `courtlistener_metadata`
- Source type: `cluster_metadata`
- Exact matching row count observed: `10,070,727`
- Vector dimensions: 1024
- Stored model tag: `st:BAAI/bge-m3:cls:norm`
- All target rows had non-null embeddings, metadata, and content at inspection
- Relation estimate: about 10.07 million rows; total `vector_records` size was
  approximately 58 GB

The relevant SQL predicate is exactly:

```sql
WHERE namespace = 'courtlistener_metadata'
  AND source_type = 'cluster_metadata'
```

Observed metadata includes `case_name`, `cluster_id`, `court_id`,
`date_filed`, and `embedding_model`. Citation and docket text are present in
the stored `content`. Inspect multiple records and formalize parsing before
depending on optional fields.

The connection currently comes from the private configuration at
`D:\THE FUTURE OF LITIGATION\app_v2\backend\.env`. Never print, commit, or copy
credentials into this repository. Add a verifier-specific environment variable
or ignored local `.env` entry when implementing the standalone backend.

## PostgreSQL runtime state

The registered Windows service is `postgresql-dev-5433`. Starting it through
Windows Service Control was denied in the prior task, so PostgreSQL was started
directly with PostgreSQL 16 `pg_ctl`. Recheck the state instead of assuming the
old PID is still current:

```powershell
& 'C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe' status `
  -D 'D:\PostgreSQL\dev-5433\data'
```

Do not delete a `postmaster.pid` without first proving the recorded process is
absent and port 5433 is not listening. Preserve stale state by renaming rather
than deleting if recovery is ever necessary.

## Approved index strategy

The user selected **IVFFlat**. No ANN index was present on `vector_records` at
the last inspection. B-tree indexes existed for the primary key, namespace,
namespace/source/source ID, case ID, content hash, and namespace/vector ID.

Create a partial cosine IVFFlat index scoped only to the two target labels.
The index must be built by a separate, manually invoked administrative script,
not during application startup or a normal API request. Use concurrent index
creation so reads remain available. Do not alter or re-embed the existing
vectors.

Treat `lists`, `ivfflat.probes`, candidate count, and score thresholds as
calibrated parameters, not magic constants. Rough mathematical starting points
may be documented, but final values must come from the held-out benchmark.

Important live-schema finding: `vector(1024)` columns and cosine operators were
usable, but `pg_extension` did not list the `vector` extension. Investigate this
unmanaged/restored extension state before attempting DDL. Do not run a long
index build until preflight checks confirm the exact database, table, row labels,
operator class, free disk space, and absence of another index build.

Long index work must run detached and hidden, log progress, and be monitored
through `pg_stat_progress_create_index`. Never leave a cleanup or `DROP INDEX`
command queued after a build.

## Database safety boundary

- Runtime verification transactions are read-only and use a statement timeout.
- The only approved live write is the separately invoked IVFFlat index build.
- Never run tests, migrations, teardown fixtures, or exploratory write scripts
  against `Storage_Pourage`.
- Tests must use fakes or a confirmed dedicated `*_test` database.
- Never call `drop_all()` or execute destructive DDL against the live database.
- Reconfirm the resolved connection target before every administrative command.
- Do not modify unrelated `Storage_Pourage` tables.

## Accuracy and testing requirements

Use test-driven development after the implementation plan is approved.

Required coverage includes:

- Request/response validation for the separate endpoint
- One lazy model load under concurrent requests
- Exact CLS pooling, 1024 dimensions, and L2 normalization
- Strict namespace/source filtering
- Reporter normalization without collapsing reporter series (`F.2d` and
  `F.3d` must remain distinct)
- Conservative case-name compatibility
- Exact year comparison
- Conservative court compatibility
- `Id.`, short form, and `supra` inheriting their full group rather than being
  queried independently
- Positive-only omission behavior
- Explicit 503 behavior for model, database, or index outages
- Read-only transaction enforcement
- SQL-injection-resistant bound parameters

Build a held-out benchmark containing clean citations plus wrong reporter,
wrong page, wrong case name, wrong year, wrong court, OCR damage, parallel
reporters, duplicates, and ambiguous cases. Emphasize prevention of false green
results because abstention is allowed. Measure at minimum:

- Precision of returned `citation_verified` results
- Recall among citations actually represented in the metadata corpus
- IVFFlat candidate recall at the chosen `lists`, `probes`, and top-k values
- Latency for realistic document-sized batches

Do not publicly push this verification feature unless the relevant measured
accuracy exceeds the user's 95% gate. Report precision and recall separately;
do not hide abstentions inside an aggregate accuracy number.

## Required process from here

1. Read this handoff and recheck Git/database state.
2. Convert the approved design into
   `docs/superpowers/specs/2026-09-20-case-citation-identity-verification-design.md`.
3. Self-review the spec for ambiguity, placeholders, contradictions, and scope.
4. Commit only the spec and ask the user to review it.
5. After approval, use the writing-plans workflow to create the implementation
   plan.
6. Implement with test-driven development.
7. Build/calibrate IVFFlat only after the administrative preflight and explicit
   live-target verification.
8. Run focused tests, the full backend suite, linting, dependency checks, the
   held-out verification benchmark, and an end-to-end read-only smoke test.
9. Use verification-before-completion before making success claims.
10. Do not touch the frontend or push publicly without an explicit request and
    the accuracy gate passing.

