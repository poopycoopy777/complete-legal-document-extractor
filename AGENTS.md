# Agent Operating Guide

This file is the operational source of truth for agents working in this
repository. It describes the system as it exists on September 20, 2026. Read it
before starting, stopping, debugging, or changing the application.

## Repository identity and boundaries

- Repository root: `D:\Coopers legit caselaw statute rules ect estractor`
- Active development branch at the time of this snapshot: `codex/development`
- Frontend: `web/` (React, TypeScript, Vite)
- API: `server/app.py` (FastAPI)
- Extraction code: `caselaw/`
- Tests: `tests/`
- Uploaded evidence: `storage/` (ignored; never commit it)
- Official-source response packages: `data/colorado_opinions/packages/`
  through the default Colorado source configuration (the entire `data/`
  directory is ignored)
- The code in this repository is standalone. Do not import Python modules,
  frontend code, or types from `D:\legal-app` or any other repository.
- The verifier does use an existing PostgreSQL corpus outside this repository.
  That is a data service, not a source-code dependency.

Before changing anything, run:

```powershell
git status --short --branch
git log -3 --oneline
```

Preserve unrelated user changes. Never reset, clean, overwrite, or revert a
dirty worktree to make a task easier.

## Current ports and URLs

| Component | Address | Purpose |
|---|---|---|
| Vite frontend | `http://localhost:5173` | Browser application |
| FastAPI | `http://127.0.0.1:8010` | Extraction and verification API |
| FastAPI docs | `http://127.0.0.1:8010/docs` | Interactive API schema |
| PostgreSQL corpus | `localhost:5433` | CourtListener vector corpus |

Do not confuse port 8010 with a different verification service on port 8000.
`stop.bat` deliberately touches only 5173 and 8010.

## Database and corpus: exact current facts

The live corpus was re-inspected read-only on September 20, 2026:

- PostgreSQL database: `Storage_Pourage`
- Server: `localhost:5433`
- PostgreSQL data directory: `D:\PostgreSQL\dev-5433\data`
- PostgreSQL binary family: PostgreSQL 16
- Windows service name: `postgresql-dev-5433`
- Table: `public.vector_records`
- Current relation estimate: 10,076,492 rows
- Required namespace: `courtlistener_metadata`
- Required source type: `cluster_metadata`
- Embedding dimensions: 1024
- Embedding contract: `st:BAAI/bge-m3:cls:norm`
- Query model: `BAAI/bge-m3`
- Pooling: CLS
- Query-vector normalization: L2 enabled
- ANN index: `ix_vector_records_embedding_ivfflat`
- ANN definition: IVFFlat over `embedding vector_cosine_ops`, `lists=2000`
- Additional b-tree/unique indexes currently present:
  `ix_vector_records_case`, `ix_vector_records_content_hash`,
  `ix_vector_records_namespace`, `ix_vector_records_namespace_source`,
  `uq_vector_records_namespace_id`, and `vector_records_pkey`

The application reads the connection from either:

1. `VERIFIER_DATABASE_URL`, or
2. `VERIFIER_ENV_FILE`, which points to a private env file containing
   `DATABASE_URL`.

The user-level `VERIFIER_DATABASE_URL` was persisted on September 20, 2026 so
new normal launches can configure the retriever without importing another
repository. The original private configuration remains at:

`D:\THE FUTURE OF LITIGATION\app_v2\backend\.env`

That path may be used as `VERIFIER_ENV_FILE` for recovery, but it is not a code
dependency and must not be parsed for any purpose except obtaining
`DATABASE_URL`.

### Credential rules

- Never print, log, paste, commit, or expose the database URL or password.
- Never put credentials in `AGENTS.md`, README files, tests, tracked scripts,
  command output, screenshots, or issue/PR text.
- Never copy the private `.env` file into this repository.
- It is safe to report only booleans such as `configured=True` or sanitized
  facts such as host, port, database name, and data directory.
- Database diagnostics must begin with a read-only transaction.
- Never run migrations, writes, deletes, index rebuilds, vacuum operations, or
  destructive tests against `Storage_Pourage` unless the user explicitly
  authorizes that exact operation after a verified backup boundary.

### Safe database status checks

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5433
& 'C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe' status `
  -D 'D:\PostgreSQL\dev-5433\data'
```

Do not delete `postmaster.pid`. If PostgreSQL is not listening, first inspect
the PID, process command line, service state, and `pg_ctl status`. If stale
state is proven, preserve it by renaming rather than deleting it.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location web
npm install
```

After merging dependency changes, rerun the requirements installation. A
backend can pass `/api/health` in an old process yet fail after restart because
the current virtual environment lacks a newly added package. This happened
with `beautifulsoup4`, `psycopg`, and the sentence-transformers stack.

## Start, stop, and restart

Normal Windows launch:

```powershell
.\start.bat
```

Normal stop:

```powershell
.\stop.bat
```

Manual launch for an agent-managed terminal:

```powershell
# Confirm VERIFIER_DATABASE_URL exists in the process environment without
# displaying its value before starting the API.
.\.venv\Scripts\python.exe -m uvicorn server.app:app `
  --host 127.0.0.1 --port 8010

Set-Location web
npm run dev -- --host 127.0.0.1 --port 5173
```

If the current shell has not inherited the persisted user environment yet, a
temporary recovery launch may set only the pointer, not the secret:

```powershell
$env:VERIFIER_ENV_FILE = `
  'D:\THE FUTURE OF LITIGATION\app_v2\backend\.env'
.\.venv\Scripts\python.exe -m uvicorn server.app:app `
  --host 127.0.0.1 --port 8010
```

Do not claim the verifier is operational from `/api/health`; that endpoint only
proves FastAPI is answering. Make a real `POST /api/verify/cases` request and
inspect its returned checks.

## Zombie and stale-server problem

This machine has had multiple copies of the Vite app. The specific failure
observed on September 20, 2026 was:

- stale frontend from `D:\legal-app\web` listening on IPv6 `::1:5173`;
- current frontend from this repository listening on `127.0.0.1:5173`;
- Chrome opened `http://localhost:5173` and could resolve `localhost` to IPv6,
  silently serving the old repository even while the correct server was live.

This presents as “my changes are not showing,” and a hard refresh does not fix
it. Never infer the serving repository from the page appearance.

### Diagnose every listener and its source path

```powershell
$ports = 5173, 8010
$listeners = Get-NetTCPConnection -State Listen |
  Where-Object { $_.LocalPort -in $ports }
$listeners | Select-Object LocalAddress, LocalPort, OwningProcess

$pids = $listeners.OwningProcess
Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -in $pids } |
  Select-Object ProcessId, Name, CommandLine |
  Format-List
```

Check both `127.0.0.1` and `::1`. For Vite, the command line must contain this
repository's `web\node_modules\...\vite` path. An unexpected `D:\legal-app`
path is stale code.

### Safe zombie termination

Do not kill every `node.exe` or `python.exe`. Resolve the exact listener PID,
inspect its command line, and stop it only after the command line proves it is
the stale server. Example pattern:

```powershell
$stalePid = 12345  # obtained from Get-NetTCPConnection
$stale = Get-CimInstance Win32_Process -Filter "ProcessId = $stalePid"
if ($stale.CommandLine -notlike '*D:\legal-app\web*') {
    throw 'Refusing to stop an unverified process.'
}
Stop-Process -Id $stalePid -Force
```

After restart, prove routing from the same hostname the browser uses:

```powershell
Invoke-WebRequest http://localhost:5173 -UseBasicParsing
Invoke-RestMethod http://127.0.0.1:8010/api/health
```

`start.bat` checks ports before launch. `stop.bat` kills only listeners on 5173
and 8010, but an agent should still inspect command lines before manual process
termination.

## Exact application flow as currently implemented

### 1. Browser startup and health

1. Vite serves the React application from `web/`.
2. `web/src/api.ts` uses `VITE_API_BASE` when set; otherwise it calls
   `http://127.0.0.1:8010`.
3. `web/src/App.tsx` calls `GET /api/health` immediately and every 10 seconds.
4. The API indicator reports reachability only. It does not prove the corpus,
   embedding model, database, or Colorado website works.

### 2. Document upload

1. The user chooses a PDF/text file in the browser.
2. The frontend sends multipart form data to `POST /api/documents`.
3. The API rejects empty files, unsupported extensions, uploads over 64 MiB,
   and PDFs over 500 pages.
4. The API hashes the exact uploaded bytes with SHA-256.
5. It writes those unchanged bytes to `storage/<uuid>.<extension>`.
6. It records the document in the process-local `_DOCUMENTS` dictionary.
7. PDF text is extracted by PyMuPDF with `sort=True`; text files decode as
   UTF-8 with replacement for invalid bytes.
8. If a PDF has no usable text layer, the API attempts whole-document OCR. It
   uses OCR only when OCR recovers more text than the embedded layer, records
   the OCR engine/details, and warns that OCR output is lower confidence.
9. A backend restart clears `_DOCUMENTS`. Files remain under `storage/`, but
   old browser document IDs become invalid. Reopen the document after every
   backend restart.

### 3. Extraction and grouping

1. `group_citations(text)` calls the case-law extractor and the authority
   extractor.
2. `caselaw/extract.py` uses eyecite for citation detection only.
3. It re-derives case names, year, and court from citation-bounded windows
   because eyecite's backward scan can cross citation boundaries.
4. Current targeted text-layer repairs include:
   - visible `Ion` encoded as `lon` before `Media Networks` is normalized to
     `Ion` and flagged `party_name_ocr_corrected`;
   - `TABLE OF AUTHORITIES / Cases` is removed from the first TOA case name.
5. `caselaw/authorities.py` extracts statutes, regulations, rules, and
   constitutional provisions through CiteURL plus repository workarounds.
6. `caselaw/group.py` uses eyecite resolution to attach short forms, `Id.`,
   `supra`, and references to full case groups. Unresolved citations remain
   orphans; the code does not guess.
7. Explicitly paired quotations are extracted and structurally attributed to
   nearby case or authority citations. Unattributed/ambiguous quotes remain
   visible.
8. The API returns groups, citations, authorities, quotations, flags, source
   spans, PDF highlights, hash/provenance, warnings, and counts in the upload
   response.

### 4. Verification request

1. After a document with case groups enters React state, a separate effect
   immediately calls `POST /api/verify/cases` with every full case group.
2. The payload includes group ID, volume, reporter, page, parties, year,
   resolved court ID, printed court text, and non-adversarial case name.
3. Extraction remains visible while verification runs.
4. There is no automatic retry button. A failed/unavailable result remains in
   the page state until another document load changes `doc`. Reopen the PDF to
   rerun verification after repairing/restarting the backend.
5. HTTP 503 becomes “Verifier unavailable,” never “0 verified.”

### 5. Corpus verification

1. At `server.app` import time, `build_from_environment()` registers a
   `CorpusRetriever` only if `VERIFIER_DATABASE_URL` or `VERIFIER_ENV_FILE` is
   visible to that process.
2. If neither is visible, `POST /api/verify/cases` currently returns 503 before
   attempting any source, including the Colorado fallback.
3. The first configured request lazily loads `BAAI/bge-m3`. First-request
   latency is therefore much higher than warm-request latency.
4. The query encoder must produce 1024-dimensional, CLS-pooled, L2-normalized
   vectors. Contract mismatch fails closed.
5. The retriever searches `public.vector_records` using exactly:
   `namespace='courtlistener_metadata'` and
   `source_type='cluster_metadata'`.
6. Transactions are read-only, connection timeout is 5 seconds, and statement
   timeout is 30 seconds.
7. Retrieval uses an escalation ladder of IVFFlat probes 10 then 100, with up
   to 50 candidates per citation.
8. Vector similarity selects candidates only. It does not verify identity.
9. A case is emitted as `citation_verified` only when exactly one candidate
   passes all four deterministic checks: reporter citation, case name, filing
   year, and court.
10. Zero passing candidates means abstention; multiple passing candidates mean
    ambiguity. Both are omitted, not labeled false or fabricated.

### 6. Official Colorado fallback

1. Only groups unresolved by the corpus are considered.
2. `caselaw/verify/colorado_check.py` selects Colorado-looking citations using
   the court fields or an otherwise courtless Pacific Reporter citation.
3. Requests run with concurrency 3 and a 30-second HTTP client timeout.
4. `caselaw/colorado/sources.py` queries the Colorado Judicial case-law
   `search.json` endpoint with the required headers and exact reporter
   citation.
5. Search results are not trusted merely because they rank highly. The code
   fetches the returned opinion content.
6. The opinion itself must contain the exact reporter citation, both party
   anchors (or the non-adversarial caption anchor), the filing year, and the
   expected Colorado appellate/supreme court heading.
7. Only all-four-check matches are returned as `citation_verified`, with
   `source='colorado_judicial'`, source URL, and response SHA-256.
8. Official responses are preserved under the configured Colorado opinions
   package directory.
9. Colorado network/search failure abstains. It is never evidence that the
   citation is false.

The September 20, 2026 live control case is:

`Ion Media Networks, Inc. v. West, 576 P.3d 225 (Colo. App. 2025)`

It returned all four checks true from the official Colorado source at:

`https://research.coloradojudicial.gov/en/vid/1105742207`

Use it as a live smoke test, not as proof that every citation or every source
path works.

## Verification semantics: do not overclaim

`citation_verified` proves identity only:

- reporter citation matches;
- case name matches;
- filing year matches;
- court matches.

It does not prove a pin cite, quotation, legal proposition, subsequent history,
current validity, or “good law.” Those UI rows currently remain `not run`.
Unresolved means no conclusion, not false. A source outage means unavailable,
not zero verified.

## Tests and completion gates

Focused extractor regression:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_extract.py -q
```

Full backend suite and lint:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check .
```

Frontend checks:

```powershell
Set-Location web
npm run lint
npm run build
```

Current known baseline after commit `aae4687`:

- 293 backend tests passed;
- Ruff passed;
- the live upload endpoint returned the corrected Ion and Ashcroft names;
- Ion passed all four official Colorado identity checks;
- frontend lint previously reported two existing `useMemo` dependency
  warnings and no errors.

Before claiming a fix, test the original real artifact or live request. A
health response, a successful upload, a synthetic unit test, or a browser page
that merely renders is not proof of successful citation verification.

## Git and commit discipline

- Check the worktree before edits and before committing.
- Stage only files belonging to the requested change.
- Do not push unless the user explicitly asks.
- Never commit `storage/`, `data/`, corpus data, downloaded opinions, logs,
  credentials, virtual environments, or `node_modules`.
- Report the exact commit SHA, tests/counts, live control result, and remaining
  verification boundary.
