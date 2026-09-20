# Verification-Only Pipeline Design

## Scope

Build a read-only verification service over `Storage_Pourage`. It accepts
already-structured legal authorities and assertions. It does not accept files,
perform OCR, extract citations, parse briefs, or provide a document UI.

## Input contract

Each request supplies one or more structured items with a caller-owned ID:

- Case: citation, case name, court, filing year, optional docket number,
  pin cite, quotation, proposition, and as-of date.
- Rule: rule family, rule number, subsection, effective date, and optional
  quoted text/proposition.
- Statute: normalized statute reference, jurisdiction, effective date, and
  optional quoted text/proposition.

Missing fields are reported as `not_run`; they are never inferred from an
untrusted document because extraction is outside this service.

## Evidence model

Every check returns `pass`, `fail`, `ambiguous`, `not_found`, `not_run`, or
`unavailable`, plus source table, stable record ID, query method, elapsed time,
and an evidence digest. No overall green result may erase a failed or unrun
dimension.

Case dimensions are identity, opinion text, pin cite, quotation, proposition,
precedential status, and subsequent treatment. `good_law` is never emitted
unless coverage and treatment rules can actually establish it; otherwise the
result is explicitly partial.

## Retrieval order

1. Normalize reporter citation into `citation_key`.
2. Exact B-tree lookup in `courtlistener_citation_aliases`.
3. Join `courtlistener_cluster_metadata`, `cl_bulk_clusters`,
   `cl_bulk_dockets`, and `cl_bulk_courts` for identity.
4. Use `cl_bulk_citations` and `cl_bulk_citation_groups` to corroborate and
   expose parallel citations.
5. Use trigram case-name lookup only when exact citation lookup is empty.
6. Use vectors only as a final discovery fallback; vector similarity is never
   identity proof.
7. Fetch all opinion parts for the selected cluster from
   `courtlistener_opinions`, using `cl_opinion_index` to disclose ingestion and
   full-text coverage.
8. Verify pin cites and quotations deterministically against full opinion text.
9. Run subsequent-history/treatment checks for every identity-confirmed case;
   this stage is mandatory and never a fallback.
10. Build a provenance-locked evidence package only after identity, opinion
    provenance, pin/quote checks, and history status are known.
11. Send only that verified-or-explicitly-flagged package to the LLM for
    holding/dicta, usage, qualification, and overstatement analysis.
12. Verify rules/statutes only when their versioned source tables contain the
    requested authority.

## Database roles

- `courtlistener_citation_aliases`: primary exact citation resolver.
- `courtlistener_cluster_metadata`: canonical caption/date/court/citations.
- `cl_bulk_citations`: independent cluster-to-citation rows, not graph edges.
- `cl_bulk_citation_groups`: parallel-citation sets by cluster.
- `cl_bulk_clusters`: cluster/docket lineage and precedential status.
- `cl_bulk_dockets`: docket number and court cross-check.
- `cl_bulk_courts`: court taxonomy and jurisdiction cross-check.
- `courtlistener_opinions`: authoritative stored opinion text and GIN FTS.
- `cl_opinion_index`: ingestion/full-text/graph coverage registry.
- `vector_records`: semantic discovery and proposition candidate retrieval.
- `cl_citation_edges`: available directed treatment graph.
- `legal_rule_provisions`: rule text by edition/rule/subsection.
- `rule_snippets`: curated, validated holding/rule evidence only.
- `legal_rule_editions`: version/date authority; currently empty, so historical
  rule verification must report unavailable until populated.
- `structured_statutes`: statute authority; currently empty, so statute text
  verification must report unavailable until populated.
- `negative_authorities`: explicit negative-authority registry; currently
  empty, so absence cannot support a clean-history conclusion.

## Safety and correctness

- All corpus transactions are read-only with connection and statement
  timeouts. The service never migrates or mutates `Storage_Pourage`.
- Exact citation identity requires reporter alias, caption, date/year, and
  court consistency. Duplicate rows with identical identity facts collapse to
  one identity; materially conflicting rows remain ambiguous.
- Full text is selected by cluster, never by semantic similarity alone.
- Pin cites require a verified reporter-page boundary. Page-number appearance
  somewhere in text is insufficient.
- Quotations preserve exact and whitespace-normalized comparisons and report
  the matched span.
- Proposition support requires inspectable passages; vector score alone is
  never evidence.
- Citation edges show that a later case cited an authority. They do not by
  themselves prove positive, negative, or overruling treatment.
- The LLM never sees unresolved identity, unauthenticated opinion text, or an
  unlabelled source. It cannot rescue a failed citation, quotation, or pin cite.
- LLM output is interpretive and passage-cited: holding versus dicta, accurate
  usage, omitted qualifications, overstatement, and application to the supplied
  proposition. It never establishes existence, identity, or source authenticity.
- History always runs before LLM analysis. Incomplete graph/source coverage is
  carried into the evidence package and prevents an unconditional `good_law`
  conclusion.

## Acceptance controls

- The 25-case stamped-response set is the primary positive identity benchmark.
- Include negative controls with altered page, year, court, party, pin cite,
  and quotation.
- Exact citation resolution target: warm p95 below 10 ms, measured rather than
  assumed.
- Every benchmark reports per-layer resolution count, total verified count,
  abstentions by reason, false positives, and latency distribution.
- Zero false-positive identities is the release gate. Recall improvements may
  not weaken deterministic checks.
