import type {
  CitationGroup,
  Selection,
  Span,
  VerificationState,
} from "../types";

/**
 * Verification results, as reported by the verification service.
 *
 * Every dimension carries one of six states, and they are not interchangeable.
 * "unavailable" means a source could not be reached and "not run" means a
 * prerequisite was missing; neither is a finding against a citation, and
 * rendering either like a failure would make an outage look like a document
 * full of fabricated authority.
 *
 * History never claims good law. The corpus reaches a fraction of the opinions
 * that cite any given case, so the honest answer is usually that coverage is
 * incomplete, and that is what it says.
 */

const IDENTITY_CHECKS = [
  { key: "reporterCitation", label: "Reporter citation matches" },
  { key: "caseName", label: "Case name matches" },
  { key: "year", label: "Filing year matches" },
  { key: "court", label: "Court matches" },
] as const;

const STAGES = [
  { key: "pinCite", label: "Pin cite within opinion range" },
  { key: "quotation", label: "Quotation appears in opinion" },
  { key: "history", label: "Subsequent history" },
] as const;

/** What a state is called, and whether it reads as a finding. */
const STATUS_TEXT: Record<string, string> = {
  pass: "yes",
  fail: "NO",
  ambiguous: "ambiguous",
  not_found: "not found",
  not_run: "not run",
  unavailable: "unavailable",
};

function statusClass(status: string | undefined): string {
  if (status === "pass") return "dot ok";
  if (status === "fail") return "dot bad";
  return "dot";
}

interface Props {
  groups: CitationGroup[];
  hasDocument: boolean;
  selection: Selection;
  onSelect: (groupId: string, span: Span) => void;
  verification: VerificationState;
}

function headline(state: VerificationState, total: number): string {
  switch (state.kind) {
    case "idle":
      return "not run";
    case "running":
      return "checking…";
    case "unavailable":
      return "unavailable";
    case "done":
      return `${Object.keys(state.verified).length}/${total} identified`;
  }
}

export function VerificationPane({
  groups,
  hasDocument,
  selection,
  onSelect,
  verification,
}: Props) {
  const verified = verification.kind === "done" ? verification.verified : {};

  return (
    <section className="pane">
      <div className="pane-head">
        <span>Verification</span>
        <span className="count">{headline(verification, groups.length)}</span>
      </div>
      <div className="pane-body">
        {verification.kind === "unavailable" && (
          <div className="stub-note">
            Verifier did not run: {verification.reason}
          </div>
        )}

        {!hasDocument && (
          <div className="empty">
            <div>No document loaded.</div>
          </div>
        )}

        {groups.map((group) => {
          const result = verified[group.id];
          const isVerified = Boolean(result);
          return (
            <div
              key={group.id}
              className="verify-row"
              style={
                selection?.groupId === group.id
                  ? { background: "var(--accent-soft)" }
                  : undefined
              }
              onClick={() => onSelect(group.id, group.header.span)}
            >
              <div className="case">
                {group.header.full_citation ?? group.header.text}
              </div>

              {isVerified && (
                <div className="verify-verdict ok">
                  Identity confirmed
                  {result?.clusterId != null && (
                    <span className="cluster">
                      {" "}
                      · cluster {result.clusterId}
                    </span>
                  )}
                </div>
              )}

              <div className="verify-checks">
                {IDENTITY_CHECKS.map(({ key, label }) => {
                  const passed = result?.checks?.[key];
                  return (
                    <div className="verify-check" key={key}>
                      <span className={passed ? "dot ok" : "dot"} />
                      <span className="label">{label}</span>
                      <span className="status">{passed ? "yes" : "—"}</span>
                    </div>
                  );
                })}
                {STAGES.map(({ key, label }) => {
                  const stage = result?.[key];
                  const status = stage?.status ?? "not_run";
                  return (
                    <div
                      className={
                        status === "fail" ? "verify-check bad" : "verify-check later"
                      }
                      key={key}
                      title={stage?.detail ?? stage?.reason ?? undefined}
                    >
                      <span className={statusClass(status)} />
                      <span className="label">
                        {label}
                        {stage?.role ? ` (${stage.role})` : ""}
                        {stage?.page != null ? ` — p. ${stage.page}` : ""}
                      </span>
                      <span className="status">
                        {STATUS_TEXT[status] ?? status}
                      </span>
                    </div>
                  );
                })}
                {(result?.quotations ?? [])
                  .filter((q) => q.status === "fail")
                  .map((q, i) => (
                    <div className="verify-check bad" key={`q${i}`} title={q.text}>
                      <span className="dot bad" />
                      <span className="label">
                        Quote not found
                        {q.pinCite ? ` (${q.pinCite})` : ""}: "{q.text.slice(0, 60)}
                        {q.text.length > 60 ? "…" : ""}"
                      </span>
                      <span className="status">NO</span>
                    </div>
                  ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
