import { useCallback, useEffect, useMemo, useState } from "react";
import { TopBar } from "./components/TopBar";
import { DocumentPane } from "./components/DocumentPane";
import { CitationsPane } from "./components/CitationsPane";
import { VerificationPane } from "./components/VerificationPane";
import { BottomBar } from "./components/BottomBar";
import {
  VerifierUnavailable,
  checkHealth,
  extractText,
  uploadDocument,
  verifyCases,
} from "./api";
import type {
  LoadedDocument,
  LogEntry,
  Selection,
  Span,
  ThemeName,
  VerificationState,
} from "./types";

const THEME_KEY = "caselaw.theme";

function loadTheme(): ThemeName {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark" || stored === "crimson") {
      return stored;
    }
  } catch {
    /* storage unavailable (private window); fall through to the default */
  }
  return "light";
}

const now = () => new Date().toISOString().slice(11, 19);

export default function App() {
  const [theme, setTheme] = useState<ThemeName>(loadTheme);
  const [doc, setDoc] = useState<LoadedDocument | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(false);
  const [showQuotes, setShowQuotes] = useState(true);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteValue, setPasteValue] = useState("");
  const [verification, setVerification] = useState<VerificationState>({
    kind: "idle",
  });

  const append = useCallback(
    (message: string, level: LogEntry["level"] = "info") =>
      setLog((entries) => [...entries, { time: now(), message, level }]),
    [],
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* non-fatal: the theme still applies for this session */
    }
  }, [theme]);

  useEffect(() => {
    let active = true;
    const ping = async () => {
      const ok = await checkHealth();
      if (active) setOnline(ok);
    };
    void ping();
    const timer = window.setInterval(ping, 10_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const groups = doc?.extraction.groups ?? [];
  const orphans = doc?.extraction.orphans ?? [];
  const authorities = doc?.extraction.authorities ?? [];

  /** Every citation in document order, for prev/next navigation. */
  const ordered = useMemo(() => {
    const entries = groups.flatMap((group) =>
      [group.header, ...group.children].map((cite) => ({
        groupId: group.id,
        span: cite.span,
      })),
    );
    entries.push(...orphans.map((cite) => ({ groupId: "", span: cite.span })));
    return entries.sort((a, b) => a.span[0] - b.span[0]);
  }, [groups, orphans]);

  const select = useCallback(
    (groupId: string, span: Span) => setSelection({ groupId, span }),
    [],
  );

  const step = useCallback(
    (delta: number) => {
      if (ordered.length === 0) return;
      const current = selection
        ? ordered.findIndex((entry) => entry.span[0] === selection.span[0])
        : -1;
      const next =
        current === -1
          ? delta > 0
            ? 0
            : ordered.length - 1
          : (current + delta + ordered.length) % ordered.length;
      setSelection(ordered[next]);
    },
    [ordered, selection],
  );

  // Verification runs after extraction, on its own, so a slow or unavailable
  // verifier never blocks the citations from appearing.
  useEffect(() => {
    const groupList = doc?.extraction.groups ?? [];
    let cancelled = false;
    // Setting state in a microtask keeps this out of the synchronous render
    // pass, which would otherwise cascade an extra render on every load.
    queueMicrotask(() => {
      if (!cancelled) {
        setVerification(
          groupList.length === 0 ? { kind: "idle" } : { kind: "running" },
        );
      }
    });
    if (groupList.length === 0) {
      return () => {
        cancelled = true;
      };
    }
    verifyCases(groupList)
      .then((verified) => {
        if (cancelled) return;
        setVerification({ kind: "done", verified });
        append(
          `Verified identity of ${Object.keys(verified).length} of ` +
            `${groupList.length} cases`,
        );
      })
      .catch((cause) => {
        if (cancelled) return;
        // An outage is not a result. Saying "0 verified" here would read
        // exactly like a document full of fabricated citations.
        const reason = String(cause?.message ?? cause);
        if (cause instanceof VerifierUnavailable) {
          setVerification({ kind: "unavailable", reason });
          append(`Verifier unavailable: ${reason}`, "error");
        } else {
          setVerification({ kind: "unavailable", reason });
          append(`Verification failed: ${reason}`, "error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [doc, append]);

  const openFile = useCallback(
    async (file: File) => {
      setBusy(true);
      setSelection(null);
      append(`Loading ${file.name} (${file.size.toLocaleString()} bytes)…`);
      try {
        const loaded = await uploadDocument(file);
        setDoc(loaded);

        append(
          `${loaded.name}: ${loaded.extraction.stats.groups} cases, ` +
            `${loaded.extraction.stats.citations} citations, ` +
            `${loaded.extraction.stats.flagged} flagged · sha256 ${loaded.sha256.slice(0, 16)}…`,
        );
      } catch (cause) {
        append(`Failed to load ${file.name}: ${String(cause)}`, "error");
      } finally {
        setBusy(false);
      }
    },
    [append],
  );

  const runPaste = useCallback(async () => {
    const text = pasteValue;
    setPasteOpen(false);
    setPasteValue("");
    if (!text.trim()) return;
    setBusy(true);
    setSelection(null);
    append(`Extracting from pasted text (${text.length.toLocaleString()} chars)…`);
    try {
      const extraction = await extractText(text);
      setDoc({
        id: "pasted",
        name: "Pasted text",
        kind: "text",
        sha256: "(not stored)",
        uploadedAt: new Date().toISOString(),
        pageCount: 0,
        pages: [],
        highlights: [],
        warning: null,
        textSource: "embedded",
        ocr: null,
        notes: [],
        rawUrl: "",
        extraction,
      });
      append(
        `Pasted text: ${extraction.stats.groups} cases, ` +
          `${extraction.stats.citations} citations, ${extraction.stats.flagged} flagged`,
      );
    } catch (cause) {
      append(`Extraction failed: ${String(cause)}`, "error");
    } finally {
      setBusy(false);
    }
  }, [append, pasteValue]);

  return (
    <div className="app">
      <TopBar
        document={doc}
        busy={busy}
        online={online}
        theme={theme}
        showQuotes={showQuotes}
        canNavigate={ordered.length > 0}
        onOpenFile={openFile}
        onPasteText={() => setPasteOpen(true)}
        onClear={() => {
          setDoc(null);
          setSelection(null);
          append("Cleared.");
        }}
        onThemeChange={setTheme}
        onToggleQuotes={() => setShowQuotes((value) => !value)}
        onPrev={() => step(-1)}
        onNext={() => step(1)}
      />

      <main className="panes">
        <DocumentPane
          document={doc}
          groups={groups}
          selection={selection}
          showQuotes={showQuotes}
          onSelect={select}
        />
        <CitationsPane
          groups={groups}
          orphans={orphans}
          authorities={authorities}
          hasDocument={doc !== null}
          selection={selection}
          onSelect={select}
        />
        <VerificationPane
          groups={groups}
          hasDocument={doc !== null}
          selection={selection}
          onSelect={select}
          verification={verification}
        />
      </main>

      <BottomBar document={doc} groups={groups} log={log} onSelect={select} />

      {pasteOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.55)",
            display: "grid",
            placeItems: "center",
            zIndex: 20,
          }}
          onClick={() => setPasteOpen(false)}
        >
          <div
            style={{
              width: "min(760px, 90vw)",
              background: "var(--bg-raised)",
              border: "1px solid var(--border-strong)",
              borderRadius: "var(--radius)",
              padding: 14,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <strong>Paste document text</strong>
            <textarea
              autoFocus
              value={pasteValue}
              onChange={(event) => setPasteValue(event.target.value)}
              placeholder="Paste the text of a brief or opinion…"
              style={{
                height: "42vh",
                resize: "vertical",
                font: "12.5px/1.6 var(--mono)",
                background: "var(--bg-sunken)",
                color: "var(--fg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: 10,
              }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setPasteOpen(false)}>Cancel</button>
              <button
                className="primary"
                onClick={runPaste}
                disabled={!pasteValue.trim()}
              >
                Extract
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
