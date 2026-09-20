import { useState } from "react";
import type {
  AuthorityGroup,
  Citation,
  CitationGroup,
  Selection,
  Span,
} from "../types";
import { CATEGORY_LABEL, CATEGORY_ORDER, KIND_LABEL } from "../types";

interface Props {
  groups: CitationGroup[];
  orphans: Citation[];
  authorities: AuthorityGroup[];
  hasDocument: boolean;
  selection: Selection;
  onSelect: (groupId: string, span: Span) => void;
}

/** A statute, regulation, rule or constitutional provision, same shape as a
 *  case group: one header, everything that points back to it cascaded below. */
function Authority({
  group,
  expanded,
  onToggle,
  selection,
  onSelect,
}: {
  group: AuthorityGroup;
  expanded: boolean;
  onToggle: () => void;
  selection: Selection;
  onSelect: (groupId: string, span: Span) => void;
}) {
  const refCount = group.children.length;
  const hasContent = refCount > 0;
  const selected = selection?.groupId === group.id;

  return (
    <article className={`group${selected ? " selected" : ""}`}>
      <div
        className={`group-head${hasContent ? " expandable" : ""}`}
        onClick={() => {
          onSelect(group.id, group.header.span);
          if (hasContent) onToggle();
        }}
        aria-expanded={hasContent ? expanded : undefined}
        title={group.source}
      >
        <span className={`twisty${hasContent ? "" : " inert"}`} aria-hidden="true">
          {hasContent ? (expanded ? "▾" : "▸") : "·"}
        </span>
        <span className="full-citation">
          {group.header.name ?? group.header.text}
        </span>
        {hasContent && !expanded && (
          <span className="group-summary">
            {refCount} ref{refCount === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {expanded && hasContent && (
        <div className="children">
          {group.children.map((child) => (
            <div
              key={`${child.span[0]}-${child.span[1]}`}
              className={`child${isActive(selection, child.span) ? " active" : ""}`}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(group.id, child.span);
              }}
            >
              <span className="chip kind">
                {child.is_shortform ? "short" : "cite"}
              </span>
              <span className="child-text">{child.text}</span>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

function isActive(selection: Selection, span: Span) {
  return (
    selection !== null &&
    selection.span[0] === span[0] &&
    selection.span[1] === span[1]
  );
}

function Group({
  group,
  expanded,
  onToggle,
  selection,
  onSelect,
}: {
  group: CitationGroup;
  expanded: boolean;
  onToggle: () => void;
  selection: Selection;
  onSelect: (groupId: string, span: Span) => void;
}) {
  const refCount = group.children.length;
  const quoteCount = group.quotes.length;
  const hasContent = refCount + quoteCount > 0;
  const selected = selection?.groupId === group.id;

  const summary = [
    refCount > 0 ? `${refCount} ref${refCount === 1 ? "" : "s"}` : null,
    quoteCount > 0 ? `${quoteCount} quote${quoteCount === 1 ? "" : "s"}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <article className={`group${selected ? " selected" : ""}`}>
      <div
        className={`group-head${hasContent ? " expandable" : ""}`}
        onClick={() => {
          onSelect(group.id, group.header.span);
          if (hasContent) onToggle();
        }}
        role={hasContent ? "button" : undefined}
        aria-expanded={hasContent ? expanded : undefined}
        title={
          hasContent
            ? expanded
              ? "Collapse"
              : "Expand references and quotations"
            : "No further references or quotations"
        }
      >
        <span className={`twisty${hasContent ? "" : " inert"}`} aria-hidden="true">
          {hasContent ? (expanded ? "▾" : "▸") : "·"}
        </span>
        <span className="full-citation">
          {group.header.full_citation ?? group.header.text}
        </span>
        {hasContent && !expanded && <span className="group-summary">{summary}</span>}
      </div>

      {expanded && refCount > 0 && (
        <div className="children">
          {group.children.map((child) => (
            <div
              key={`${child.span[0]}-${child.span[1]}`}
              className={`child${isActive(selection, child.span) ? " active" : ""}`}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(group.id, child.span);
              }}
            >
              <span className="chip kind">{KIND_LABEL[child.kind]}</span>
              <span className="child-text">{child.text}</span>
              {child.pin_cite && <span className="chip">{child.pin_cite}</span>}
            </div>
          ))}
        </div>
      )}

      {expanded && quoteCount > 0 && (
        <div className="quotes">
          {group.quotes.map((quote) => (
            <blockquote
              key={`${quote.span[0]}-${quote.span[1]}`}
              className="quote"
              onClick={(event) => {
                event.stopPropagation();
                onSelect(group.id, quote.span);
              }}
            >
              “{quote.text}”
              <span className="attrib">
                {group.caseName ?? group.header.text}
                {quote.pin_cite ? `, at ${quote.pin_cite}` : ""}
              </span>
            </blockquote>
          ))}
        </div>
      )}
    </article>
  );
}

export function CitationsPane({
  groups,
  orphans,
  authorities,
  hasDocument,
  selection,
  onSelect,
}: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const expandable = [
    ...groups.filter((g) => g.children.length + g.quotes.length > 0),
    ...authorities.filter((a) => a.children.length > 0),
  ];
  const allOpen =
    expandable.length > 0 && expandable.every((g) => expanded.has(g.id));

  const total =
    groups.reduce((sum, group) => sum + 1 + group.children.length, orphans.length) +
    authorities.reduce((sum, a) => sum + 1 + a.children.length, 0);

  return (
    <section className="pane">
      <div className="pane-head">
        <span>Extracted citations</span>
        {expandable.length > 0 && (
          <button
            className="head-action"
            onClick={() =>
              setExpanded(allOpen ? new Set() : new Set(expandable.map((g) => g.id)))
            }
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
        )}
        <span className="count">
          {groups.length} case{groups.length === 1 ? "" : "s"}
          {authorities.length > 0 && ` · ${authorities.length} auth`} · {total}{" "}
          cite{total === 1 ? "" : "s"}
        </span>
      </div>
      <div className="pane-body">
        {!hasDocument && (
          <div className="empty">
            <div>Nothing extracted yet.</div>
            <div>Citations appear here grouped by case.</div>
          </div>
        )}
        {hasDocument && groups.length === 0 && orphans.length === 0 && (
          <div className="empty">No case law citations found in this document.</div>
        )}

        {groups.map((group) => (
          <Group
            key={group.id}
            group={group}
            expanded={expanded.has(group.id)}
            onToggle={() => toggle(group.id)}
            selection={selection}
            onSelect={onSelect}
          />
        ))}

        {/* Statutes, regulations and rules come after all of the case law,
            each category under its own heading. */}
        {CATEGORY_ORDER.map((category) => {
          const inCategory = authorities.filter((a) => a.category === category);
          if (inCategory.length === 0) return null;
          return (
            <div key={category}>
              <div className="section-label">
                {CATEGORY_LABEL[category]} ({inCategory.length})
              </div>
              {inCategory.map((group) => (
                <Authority
                  key={group.id}
                  group={group}
                  expanded={expanded.has(group.id)}
                  onToggle={() => toggle(group.id)}
                  selection={selection}
                  onSelect={onSelect}
                />
              ))}
            </div>
          );
        })}

        {orphans.length > 0 && (
          <>
            <div className="section-label">
              Unattached references ({orphans.length})
            </div>
            {orphans.map((cite) => (
              <div
                key={`${cite.span[0]}-${cite.span[1]}`}
                className={`child${isActive(selection, cite.span) ? " active" : ""}`}
                onClick={() => onSelect("", cite.span)}
                title="No full citation could be matched to this reference"
              >
                <span className="chip kind">{KIND_LABEL[cite.kind]}</span>
                <span className="child-text">{cite.text}</span>
              </div>
            ))}
          </>
        )}
      </div>
    </section>
  );
}
