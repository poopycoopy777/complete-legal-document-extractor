import type {
  CitationGroup,
  Selection,
  Span,
  VerificationState,
} from "../types";

/**
 * Stage one of verification: case-citation identity only.
 *
 * The four identity checks are live. Everything below them belongs to a later
 * stage and renders unrun, because showing a case as simply "verified" would
 * imply the pin cite, the quotation and its good-law status had been checked.
 * None of them have.
 *
 * Verification is positive-only. A case the stage could not confirm shows as
 * "not established", never as invalid, missing or fabricated. The corpus is a
 * CourtListener snapshot, not the universe of American law: unpublished
 * dispositions, very recent opinions and most state trial orders are not in
 * it, so absence is not evidence against a citation.
 */

const IDENTITY_CHECKS = [
  { key: "reporterCitation", label: "Reporter citation matches" },
  { key: "caseName", label: "Case name matches" },
  { key: "year", label: "Filing year matches" },
  { key: "court", label: "Court matches" },
] as const;

const LATER_STAGES = [
  "Pin cite within opinion range",
  "Quotation appears in opinion",
  "Subsequent history / still good law",
];

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
                {LATER_STAGES.map((label) => (
                  <div className="verify-check later" key={label}>
                    <span className="dot" />
                    <span className="label">{label}</span>
                    <span className="status">not run</span>
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
