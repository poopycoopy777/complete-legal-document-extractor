# Verification-Only Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only, evidence-producing legal verification API that uses every relevant corpus table in its proper role and never performs extraction.

**Architecture:** Deterministic citation resolution is primary, full opinion text supplies pin/quote evidence, and mandatory history checking runs for every identity-confirmed case. Only a provenance-locked verified/flagged evidence package reaches the LLM for usage, holding/dicta, qualification, and overstatement analysis; vectors are discovery-only fallback.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, psycopg 3, PostgreSQL 16, pgvector, PostgreSQL GIN/trigram/B-tree indexes, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-20-verification-only-pipeline-design.md`

## Global Constraints

- Verification only: no uploads, OCR, PDF reading, citation extraction, brief parsing, or frontend.
- `Storage_Pourage` is read-only; no migrations or corpus writes.
- Never expose `VERIFIER_DATABASE_URL` or database credentials.
- Deterministic evidence decides verdicts; vectors only retrieve candidates.
- Unavailable, unrun, ambiguous, and not-found are distinct states.
- Empty authority tables produce explicit coverage gaps, never negative results.
- The LLM never receives unresolved identity or unauthenticated opinion text.
- History runs for every identity-confirmed case before any LLM analysis.
- All implementation follows red-green-refactor and commits one reviewed task at a time.

---

### Task 1: Create the verification-only package and contracts

**Files:**
- Create: `verification_api/models.py`
- Create: `verification_api/status.py`
- Test: `tests/verification_api/test_models.py`

**Interfaces:**
- Produces `VerificationRequest`, `CaseAuthorityInput`, `RuleAuthorityInput`,
  `StatuteAuthorityInput`, `CheckEvidence`, and `VerificationResult`.

- [ ] Write failing tests proving raw document text/file fields are rejected,
  caller IDs are required, and every result dimension uses the six-state enum.
- [ ] Run `python -m pytest tests/verification_api/test_models.py -q` and confirm
  the failures are contract failures.
- [ ] Implement strict Pydantic models with `extra='forbid'` and enums:
  `pass`, `fail`, `ambiguous`, `not_found`, `not_run`, `unavailable`.
- [ ] Add immutable evidence fields: source table, record IDs, lookup method,
  elapsed milliseconds, evidence SHA-256, and explanatory reason code.
- [ ] Run the focused test and Ruff; commit `feat: define verification-only contracts`.

### Task 2: Add safe database access and corpus capability inventory

**Files:**
- Create: `verification_api/database.py`
- Create: `verification_api/capabilities.py`
- Test: `tests/verification_api/test_database.py`

**Interfaces:**
- Produces `readonly_connection()` and `inspect_capabilities() -> CorpusCapabilities`.

- [ ] Write failing tests for missing configuration, redacted connection errors,
  read-only transactions, 5-second connection timeout, and 30-second statement timeout.
- [ ] Implement URL loading from `VERIFIER_DATABASE_URL`/`VERIFIER_ENV_FILE`
  without ever including the URL in exceptions.
- [ ] Implement startup inventory for all 16 named tables, required columns,
  row availability, and critical indexes.
- [ ] Mark empty `legal_rule_editions`, `structured_statutes`, and
  `negative_authorities` as coverage gaps rather than startup failures.
- [ ] Verify against live PostgreSQL read-only; commit `feat: add safe corpus access`.

### Task 3: Implement citation normalization and exact alias resolution

**Files:**
- Create: `verification_api/normalize.py`
- Create: `verification_api/identity.py`
- Test: `tests/verification_api/test_exact_identity.py`

**Interfaces:**
- Produces `citation_key(str) -> str` and
  `resolve_exact_case(CaseAuthorityInput) -> IdentityResolution`.

- [ ] Write table-driven failing tests for U.S., S. Ct., L. Ed., F.2d/F.3d,
  P.2d/P.3d, WL, LEXIS, punctuation, and whitespace normalization.
- [ ] Pin the live controls `556 U.S. 662 -> cluster 145875` and
  `576 P.3d 225 -> Ion Media Networks` as opt-in integration tests.
- [ ] Query `courtlistener_citation_aliases` by `citation_key` using
  `ix_cl_citation_alias_key_cluster`; join `courtlistener_cluster_metadata` by
  cluster ID.
- [ ] Apply strict caption, filing year, and court checks after alias lookup.
- [ ] Collapse duplicate candidates only when normalized caption, date, court,
  and citation set are identical; preserve material conflicts as ambiguous.
- [ ] Record `EXPLAIN ANALYZE` timing in the benchmark, not application logs;
  commit `feat: resolve exact citation aliases`.

### Task 4: Corroborate identity across bulk metadata tables

**Files:**
- Create: `verification_api/corroboration.py`
- Test: `tests/verification_api/test_corroboration.py`

**Interfaces:**
- Consumes an exact `IdentityResolution`.
- Produces `CorroboratedIdentity` with parallel citations and docket/court lineage.

- [ ] Write failing tests for disagreements among aliases, bulk citations,
  citation groups, cluster metadata, docket, and court taxonomy.
- [ ] Join `cl_bulk_citations` and `cl_bulk_citation_groups` to assemble the
  complete parallel-citation set.
- [ ] Join `cl_bulk_clusters -> cl_bulk_dockets -> cl_bulk_courts` to verify
  docket number, court ID, jurisdiction, filing date, and precedential status.
- [ ] Return a conflict object instead of selecting whichever table is convenient.
- [ ] Test against Iqbal/Twombly parallel citations; commit
  `feat: corroborate case identity across corpus`.

### Task 5: Add exact-name fallback and vector discovery fallback

**Files:**
- Create: `verification_api/fallback.py`
- Test: `tests/verification_api/test_fallback.py`

**Interfaces:**
- Produces candidates only; all candidates return through Tasks 3-4 checks.

- [ ] Write failing tests proving fallback runs only after alias miss and that
  vector similarity can never set a passing identity status.
- [ ] Use the trigram index on `lower(case_name)` with court/year filters for
  exact-name/short-caption recovery.
- [ ] Use `vector_records` IVFFlat only when citation and name retrieval fail;
  validate 1024 dimensions and `st:BAAI/bge-m3:cls:norm`.
- [ ] Feed discovered cluster IDs back through deterministic metadata and alias checks.
- [ ] Benchmark known ANN misses (*Hall*, *Snell*) and ensure exact paths now
  resolve them without increasing vector `top_k`; commit
  `feat: add conservative identity fallbacks`.

### Task 6: Retrieve and authenticate full opinion text

**Files:**
- Create: `verification_api/opinions.py`
- Test: `tests/verification_api/test_opinions.py`

**Interfaces:**
- Produces `OpinionBundle` containing all cluster opinion parts, hashes, URLs,
  opinion IDs, precedential status, and coverage state.

- [ ] Write failing tests for majority/concurrence/dissent grouping, missing full
  text, duplicate text hashes, and cluster mismatch.
- [ ] Read `cl_opinion_index` first to disclose ingestion, `has_full_text`,
  graph-scraped, and embedding coverage.
- [ ] Fetch all `courtlistener_opinions` rows by cluster using
  `ix_cl_opinions_cluster_id`; verify stored `text_hash` against opinion text.
- [ ] Keep opinion parts separate and identify which part supports each later check.
- [ ] Commit `feat: load authenticated opinion bundles`.

### Task 7: Verify pin cites and quotations

**Files:**
- Create: `verification_api/text_checks.py`
- Test: `tests/verification_api/test_text_checks.py`

**Interfaces:**
- Produces independent pin and quotation `CheckEvidence` objects with spans.

- [ ] Write failing tests for valid pins, out-of-range pins, ambiguous pagination,
  whitespace-only quote differences, ellipses, bracket alterations, and quote absence.
- [ ] Define reporter-page boundaries from authenticated opinion text/metadata;
  do not accept a naked page-number occurrence.
- [ ] Use exact normalized text matching first and GIN `opinion_tsv` phrase search
  only to locate candidates; return inspectable surrounding passages.
- [ ] Hash the matched passage and preserve opinion ID plus character offsets.
- [ ] Commit `feat: verify pin cites and quotations`.

### Task 8: Build the pre-LLM evidence gate and analyze legal usage

**Files:**
- Create: `verification_api/evidence_gate.py`
- Create: `verification_api/usage_analysis.py`
- Test: `tests/verification_api/test_evidence_gate.py`
- Test: `tests/verification_api/test_usage_analysis.py`

**Interfaces:**
- Produces a provenance-locked `VerifiedEvidencePackage` and passage-cited
  usage/holding/overstatement findings.

- [ ] Write failing tests proving unresolved identity, missing/incorrect hashes,
  unknown opinion-part role, unrun pin/quote checks, or missing history status
  blocks package creation and prevents any LLM call.
- [ ] Build the package from the authenticated opinion bundle, deterministic
  checks, history status, caller proposition, and explicit coverage flags.
- [ ] Search only the verified cluster's text with GIN FTS and use vectors only
  to rank passages within that authenticated bundle.
- [ ] Send the complete relevant opinion parts when within model limits;
  otherwise send lossless, hashed sections with majority/concurrence/dissent
  labels and retrieval manifests.
- [ ] Require the LLM to return passage IDs/offsets for support, contrary
  language, holding/dicta classification, omitted qualifications, and
  overstatement. Reject uncited model conclusions.
- [ ] Integrate only `rule_snippets.validated=true`; expose dicta, holding type,
  doctrinal fence, procedural posture, and validation errors.
- [ ] Commit `feat: gate and analyze verified legal evidence`.

### Task 9: Add mandatory citation history and treatment evidence

**Files:**
- Create: `verification_api/treatment.py`
- Test: `tests/verification_api/test_treatment.py`

**Interfaces:**
- Produces mandatory `TreatmentEvidence` and a graph coverage statement for
  every identity-confirmed case, never an unsupported “good law” boolean.

- [ ] Write failing tests for citing/cited direction, depth, self-links,
  incomplete graph coverage, later opinion retrieval, and proof that this stage
  runs before the evidence gate for every confirmed identity.
- [ ] Traverse `cl_citation_edges` through both indexed directions and hydrate
  later clusters/opinions.
- [ ] Search later opinion passages around the cited case with GIN FTS and
  classify treatment only when explicit language is present and reviewable.
- [ ] Use `cl_opinion_index.citation_graph_scraped` to disclose coverage.
- [ ] Consult `negative_authorities` when populated; while empty, emit an
  explicit registry coverage gap.
- [ ] Emit only `adverse_treatment_found`, `history_checked_no_adverse_found`,
  `history_ambiguous`, `history_incomplete`, or `history_unavailable`; never
  convert a partial graph search into unconditional `good_law`.
- [ ] Commit `feat: report citation treatment evidence`.

### Task 10: Add rule and statute verification with honest empty-table behavior

**Files:**
- Create: `verification_api/authorities.py`
- Test: `tests/verification_api/test_authorities.py`

**Interfaces:**
- Produces versioned rule/statute verification results.

- [ ] Write failing tests for effective-date selection, subsection lookup,
  source hashing, missing edition data, and empty statute coverage.
- [ ] Resolve rules through `legal_rule_editions` then
  `legal_rule_provisions(edition_id, rule_number, subsection_path)`.
- [ ] Verify rule text SHA-256 and official-source metadata; until editions are
  populated, return unavailable rather than using unversioned provisions.
- [ ] Resolve statutes by unique `structured_statutes.statute_ref`; while the
  table is empty, return a statute-corpus coverage gap.
- [ ] Commit `feat: verify versioned rules and statutes`.

### Task 11: Orchestrate verdicts and expose the API

**Files:**
- Create: `verification_api/service.py`
- Create: `verification_api/app.py`
- Test: `tests/verification_api/test_service.py`
- Test: `tests/verification_api/test_api.py`

**Interfaces:**
- Exposes `POST /v1/verify`, `GET /v1/capabilities`, and `GET /health`.

- [ ] Write failing contract tests for mixed case/rule/statute batches,
  per-dimension statuses, 422 validation, 503 dependency failure, and no extraction endpoints.
- [ ] Orchestrate exact identity, corroboration, opinion, pin, quote,
  proposition, and treatment stages with per-stage timing.
- [ ] Ensure one unavailable optional stage does not erase completed evidence.
- [ ] Return immutable evidence records and request/result SHA-256 values.
- [ ] Confirm OpenAPI contains no upload/document/extraction routes; commit
  `feat: expose verification-only API`.

### Task 12: Build the held-out benchmark and release gate

**Files:**
- Create: `benchmarks/verification_cases.json`
- Create: `scripts/run_verification_benchmark.py`
- Test: `tests/verification_api/test_benchmark_fixture.py`
- Create: `docs/verification-release-gate.md`

**Interfaces:**
- Produces machine-readable JSON with counts, reasons, false positives, and latency.

- [ ] Encode the 25 real cases from the stamped response with expected identity
  facts and add altered-page/year/court/name negative controls.
- [ ] Add duplicate-cluster, parallel-citation, short-caption, missing-opinion,
  bad-pin, bad-quote, and unavailable-table controls.
- [ ] Report exact-alias, name, vector, opinion, quote/pin, proposition, and
  treatment counts separately with p50/p95/p99 latency.
- [ ] Gate release on zero false-positive identities, all known exact aliases
  resolved, no hidden unavailable stages, full pytest/Ruff success, and a
  read-only live smoke run.
- [ ] Run the complete suite and benchmark; commit
  `test: add verification pipeline release gate`.
