import { useEffect, useMemo, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { rawUrl } from "../api";
import type {
  CitationGroup,
  Highlight,
  LoadedDocument,
  Selection,
  Span,
} from "../types";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

interface Props {
  document: LoadedDocument | null;
  groups: CitationGroup[];
  selection: Selection;
  showQuotes: boolean;
  onSelect: (groupId: string, span: Span) => void;
}

type Mark = { start: number; end: number; kind: "cite" | "quote"; groupId: string };

/** Build non-overlapping marks in document order; citations win ties. */
function buildMarks(groups: CitationGroup[], showQuotes: boolean): Mark[] {
  const marks: Mark[] = [];
  for (const group of groups) {
    for (const cite of [group.header, ...group.children]) {
      marks.push({
        start: cite.span[0],
        end: cite.span[1],
        kind: "cite",
        groupId: group.id,
      });
    }
    if (showQuotes) {
      for (const quote of group.quotes) {
        marks.push({
          start: quote.span[0],
          end: quote.span[1],
          kind: "quote",
          groupId: group.id,
        });
      }
    }
  }
  marks.sort((a, b) =>
    a.start - b.start || (a.kind === "cite" ? -1 : 1),
  );

  const kept: Mark[] = [];
  let cursor = -1;
  for (const mark of marks) {
    if (mark.start >= cursor) {
      kept.push(mark);
      cursor = mark.end;
    }
  }
  return kept;
}

function TextView({
  text,
  groups,
  selection,
  showQuotes,
  onSelect,
}: {
  text: string;
  groups: CitationGroup[];
  selection: Selection;
  showQuotes: boolean;
  onSelect: (groupId: string, span: Span) => void;
}) {
  const marks = useMemo(() => buildMarks(groups, showQuotes), [groups, showQuotes]);
  const activeRef = useRef<HTMLElement>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selection]);

  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  marks.forEach((mark, index) => {
    if (mark.start > cursor) {
      nodes.push(text.slice(cursor, mark.start));
    }
    const isActive =
      selection !== null &&
      selection.span[0] === mark.start &&
      selection.span[1] === mark.end;
    nodes.push(
      <mark
        key={`${mark.kind}-${index}`}
        ref={isActive ? (activeRef as React.Ref<HTMLElement>) : undefined}
        className={`${mark.kind}${isActive ? " active" : ""}`}
        onClick={() => onSelect(mark.groupId, [mark.start, mark.end])}
        title={mark.kind === "cite" ? "Citation" : "Quoted material"}
      >
        {text.slice(mark.start, mark.end)}
      </mark>,
    );
    cursor = mark.end;
  });
  if (cursor < text.length) nodes.push(text.slice(cursor));

  return <pre className="doc-text">{nodes}</pre>;
}

function PdfView({
  url,
  pageCount,
  highlights,
  selection,
}: {
  url: string;
  pageCount: number;
  highlights: Highlight[];
  selection: Selection;
}) {
  const container = useRef<HTMLDivElement>(null);
  /** Page wrapper element and render scale, keyed by 0-based page index. */
  const pageEls = useRef(new Map<number, HTMLDivElement>());
  const scales = useRef(new Map<number, number>());
  const [error, setError] = useState<string | null>(null);
  const [rendered, setRendered] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const task = pdfjs.getDocument({ url });
    pageEls.current.clear();
    scales.current.clear();

    (async () => {
      try {
        const pdf = await task.promise;
        if (cancelled) return;
        const host = container.current;
        if (!host) return;
        host.replaceChildren();

        const available = host.clientWidth - 24;
        for (let number = 1; number <= pdf.numPages; number += 1) {
          if (cancelled) return;
          const page = await pdf.getPage(number);
          const base = page.getViewport({ scale: 1 });
          // Render at device resolution so the clone stays crisp when zoomed.
          const scale = Math.max(available / base.width, 0.2);
          const dpr = window.devicePixelRatio || 1;
          const viewport = page.getViewport({ scale: scale * dpr });

          const canvas = document.createElement("canvas");
          canvas.className = "pdf-page";
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = `${base.width * scale}px`;
          canvas.style.height = `${base.height * scale}px`;
          const context = canvas.getContext("2d");
          if (!context) continue;

          // Wrapper establishes the coordinate space highlights sit in.
          const wrap = document.createElement("div");
          wrap.className = "pdf-page-wrap";
          wrap.style.width = `${base.width * scale}px`;
          wrap.style.height = `${base.height * scale}px`;
          wrap.appendChild(canvas);
          host.appendChild(wrap);

          pageEls.current.set(number - 1, wrap);
          scales.current.set(number - 1, scale);

          await page.render({ canvasContext: context, viewport, canvas }).promise;
          if (cancelled) return;
          setRendered(number);
        }
      } catch (cause) {
        if (!cancelled) setError(String(cause));
      }
    })();

    return () => {
      cancelled = true;
      task.destroy();
    };
  }, [url]);

  // Draw the selected span over the rendered page and scroll it into view.
  useEffect(() => {
    for (const wrap of pageEls.current.values()) {
      wrap.querySelectorAll(".pdf-highlight").forEach((node) => node.remove());
    }
    if (!selection) return;

    const hit = highlights.find(
      (h) => h.span[0] === selection.span[0] && h.span[1] === selection.span[1],
    );
    if (!hit) return;

    const wrap = pageEls.current.get(hit.page);
    const scale = scales.current.get(hit.page);
    if (!wrap || scale === undefined) return;

    let first: HTMLDivElement | null = null;
    for (const [x0, y0, x1, y1] of hit.rects) {
      const box = document.createElement("div");
      box.className = "pdf-highlight";
      box.style.left = `${x0 * scale}px`;
      box.style.top = `${y0 * scale}px`;
      box.style.width = `${(x1 - x0) * scale}px`;
      box.style.height = `${(y1 - y0) * scale}px`;
      wrap.appendChild(box);
      if (!first) first = box;
    }

    // With no rectangle we can still take the reader to the right page.
    (first ?? wrap).scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selection, highlights, rendered]);

  return (
    <>
      {error && <div className="stub-note">Could not render PDF: {error}</div>}
      {!error && rendered < pageCount && (
        <div className="stub-note">
          Rendering page {rendered + 1} of {pageCount}…
        </div>
      )}
      <div className="pdf-scroll" ref={container} />
    </>
  );
}

export function DocumentPane({
  document: doc,
  groups,
  selection,
  showQuotes,
  onSelect,
}: Props) {
  const citationCount = groups.reduce(
    (total, group) => total + 1 + group.children.length,
    0,
  );

  return (
    <section className="pane">
      <div className="pane-head">
        <span>Document</span>
        {doc && (
          <span className="count">
            {doc.kind === "pdf"
              ? `${doc.pageCount} page${doc.pageCount === 1 ? "" : "s"}`
              : `${doc.extraction.text.length.toLocaleString()} chars`}
            {doc.kind === "text" && ` · ${citationCount} marked`}
          </span>
        )}
      </div>
      <div className="pane-body">
        {!doc && (
          <div className="empty">
            <div>No document loaded.</div>
            <div>Open a PDF or text file, or paste text.</div>
          </div>
        )}
        {doc?.kind === "pdf" && (
          <PdfView
            url={rawUrl(doc.rawUrl)}
            pageCount={doc.pageCount}
            highlights={doc.highlights}
            selection={selection}
          />
        )}
        {doc?.kind === "text" && (
          <TextView
            text={doc.extraction.text}
            groups={groups}
            selection={selection}
            showQuotes={showQuotes}
            onSelect={onSelect}
          />
        )}
      </div>
    </section>
  );
}
