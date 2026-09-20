import { useRef } from "react";
import type { LoadedDocument, ThemeName } from "../types";

const THEMES: { id: ThemeName; label: string; title: string }[] = [
  { id: "light", label: "Light", title: "White with defined borders" },
  { id: "dark", label: "Dark", title: "Dark" },
  { id: "crimson", label: "Crimson", title: "Dark with blood-red accents" },
];

interface Props {
  document: LoadedDocument | null;
  busy: boolean;
  online: boolean;
  theme: ThemeName;
  showQuotes: boolean;
  onOpenFile: (file: File) => void;
  onPasteText: () => void;
  onClear: () => void;
  onThemeChange: (theme: ThemeName) => void;
  onToggleQuotes: () => void;
  onPrev: () => void;
  onNext: () => void;
  canNavigate: boolean;
}

export function TopBar({
  document: doc,
  busy,
  online,
  theme,
  showQuotes,
  onOpenFile,
  onPasteText,
  onClear,
  onThemeChange,
  onToggleQuotes,
  onPrev,
  onNext,
  canNavigate,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <header className="topbar">
      <span className="brand">
        <span className="mark">§</span> Caselaw Extractor
      </span>

      <span className="sep" />

      <input
        ref={fileInput}
        type="file"
        accept=".pdf,.txt,.text,.md"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onOpenFile(file);
          event.target.value = "";
        }}
      />
      <button
        className="primary"
        onClick={() => fileInput.current?.click()}
        disabled={busy}
      >
        {busy ? "Working…" : "Open document"}
      </button>
      <button onClick={onPasteText} disabled={busy}>
        Paste text
      </button>
      <button onClick={onClear} disabled={busy || !doc}>
        Clear
      </button>

      <span className="sep" />

      <button onClick={onPrev} disabled={!canNavigate} title="Previous citation">
        ‹ Prev
      </button>
      <button onClick={onNext} disabled={!canNavigate} title="Next citation">
        Next ›
      </button>
      <button
        onClick={onToggleQuotes}
        aria-pressed={showQuotes}
        title="Highlight quoted material in the document"
      >
        {showQuotes ? "Quotes on" : "Quotes off"}
      </button>

      <span className="spacer" />

      {doc && <span className="filename" title={doc.name}>{doc.name}</span>}

      <span className="sep" />

      <span
        className="chip"
        title={online ? "Extraction API reachable" : "Extraction API unreachable"}
      >
        <span
          className="dot"
          style={{
            background: online ? "var(--accent)" : "transparent",
            borderColor: online ? "var(--accent)" : "var(--border-strong)",
          }}
        />
        {online ? "API" : "offline"}
      </span>

      <div className="theme-group" role="group" aria-label="Colour scheme">
        {THEMES.map((option) => (
          <button
            key={option.id}
            title={option.title}
            aria-pressed={theme === option.id}
            onClick={() => onThemeChange(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </header>
  );
}
