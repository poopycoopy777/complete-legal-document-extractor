import { useState } from "react";
import type {
  CitationGroup,
  LoadedDocument,
  LogEntry,
  Span,
  VerificationState,
} from "../types";

type Tab = "summary" | "flags" | "provenance" | "log";

const TABS: { id: Tab; label: string }[] = [
  { id: "summary", label: "Summary" },
  { id: "flags", label: "Flags" },
  { id: "provenance", label: "Provenance" },
  { id: "log", label: "Log" },
];

interface Props {
  document: LoadedDocument | null;
  groups: CitationGroup[];
  log: LogEntry[];
  onSelect: (groupId: string, span: Span) => void;
  verification: VerificationState;
}

export function BottomBar({
  document: doc,
  groups,
  log,
  onSelect,
  verification,
}: Props) {
  const [tab, setTab] = useState<Tab>("summary");
  const stats = doc?.extraction.stats;

  const flagged = groups.flatMap((group) =>
    [group.header, ...group.children]
      .filter((cite) => cite.flags.length > 0)
      .map((cite) => ({ group, cite })),
  );

  return (
    <footer className="bottombar">
      <div className="bottombar-tabs">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            aria-pressed={tab === entry.id}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
            {entry.id === "flags" && flagged.length > 0 && ` (${flagged.length})`}
          </button>
        ))}
      </div>

      <div className="bottombar-body">
        {tab === "summary" && (
          <div className="stat-grid">
            <span className="stat">
              <span className="k">cases</span>
              <span className="v">{stats?.groups ?? 0}</span>
            </span>
            <span className="stat">
              <span className="k">citations</span>
              <span className="v">{stats?.citations ?? 0}</span>
            </span>
            <span className="stat">
              <span className="k">quotes</span>
              <span className="v">{stats?.quotes ?? 0}</span>
            </span>
            <span className="stat">
              <span className="k">authorities</span>
              <span className="v">{stats?.authorities ?? 0}</span>
            </span>
            <span className="stat">
              <span className="k">auth cites</span>
              <span className="v">{stats?.authorityCitations ?? 0}</span>
            </span>
            <span className="stat">
              <span className="k">flagged</span>
              <span className="v">{stats?.flagged ?? 0}</span>
            </span>
            <span className="stat">
              <span className="k">unattached</span>
              <span className="v">{doc?.extraction.orphans.length ?? 0}</span>
            </span>
            <span className="stat">
              <span className="k">verified</span>
              <span className="v">
                {verification.kind === "done"
                  ? Object.keys(verification.verified).length
                  : "—"}
              </span>
            </span>
          </div>
        )}

        {tab === "flags" &&
          (flagged.length === 0 ? (
            <div style={{ color: "var(--fg-faint)" }}>
              No flags raised on this document.
            </div>
          ) : (
            flagged.map(({ group, cite }) =>
              cite.flags.map((flag) => (
                <div
                  className="flag-item"
                  key={`${cite.span[0]}-${flag}`}
                  onClick={() => onSelect(group.id, cite.span)}
                  style={{ cursor: "pointer" }}
                >
                  <span className="where">{cite.text}</span>
                  <span className="what">{flag}</span>
                </div>
              )),
            )
          ))}

        {tab === "provenance" &&
          (doc ? (
            <div className="stat-grid" style={{ flexDirection: "column" }}>
              <span className="stat">
                <span className="k">file</span>
                <span className="v">{doc.name}</span>
              </span>
              <span className="stat">
                <span className="k">sha-256</span>
                <span className="v">{doc.sha256}</span>
              </span>
              <span className="stat">
                <span className="k">loaded (utc)</span>
                <span className="v">{doc.uploadedAt}</span>
              </span>
              <span className="stat">
                <span className="k">type</span>
                <span className="v">
                  {doc.kind}
                  {doc.kind === "pdf" ? ` · ${doc.pageCount} pages` : ""}
                </span>
              </span>
            </div>
          ) : (
            <div style={{ color: "var(--fg-faint)" }}>No document loaded.</div>
          ))}

        {tab === "log" &&
          (log.length === 0 ? (
            <div style={{ color: "var(--fg-faint)" }}>Nothing logged yet.</div>
          ) : (
            [...log].reverse().map((entry, index) => (
              <div
                className={`log-line${entry.level === "error" ? " err" : ""}`}
                key={`${entry.time}-${index}`}
              >
                <span className="t">{entry.time}</span>
                <span className="m">{entry.message}</span>
              </div>
            ))
          ))}
      </div>
    </footer>
  );
}
