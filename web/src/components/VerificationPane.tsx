import type { CitationGroup, Selection, Span } from "../types";

/**
 * Visual shell only. No verification logic is wired up: every check renders in
 * its "not run" state so the layout is settled before any resolver exists.
 */

const CHECKS = [
  "Reporter citation resolves",
  "Case name matches reporter",
  "Year matches reporter record",
  "Court matches reporter record",
  "Pin cite within opinion range",
  "Subsequent history / still good law",
  "Quotation appears in opinion",
];

interface Props {
  groups: CitationGroup[];
  hasDocument: boolean;
  selection: Selection;
  onSelect: (groupId: string, span: Span) => void;
}

export function VerificationPane({
  groups,
  hasDocument,
  selection,
  onSelect,
}: Props) {
  return (
    <section className="pane">
      <div className="pane-head">
        <span>Verification</span>
        <span className="count">not run</span>
      </div>
      <div className="pane-body">
        <div className="stub-note">
          Verification is not implemented. Every check below is a placeholder in
          its unrun state — nothing here has been checked against any source.
        </div>

        {!hasDocument && (
          <div className="empty">
            <div>No document loaded.</div>
          </div>
        )}

        {groups.map((group) => (
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
            <div className="verify-checks">
              {CHECKS.map((check) => (
                <div className="verify-check" key={check}>
                  <span className="dot" />
                  <span className="label">{check}</span>
                  <span className="status">—</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
