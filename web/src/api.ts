import type { CitationGroup, Extraction, LoadedDocument, VerifiedCase } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8010";

export const rawUrl = (path: string) => `${BASE}${path}`;

async function unwrap<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* response had no JSON body; keep the status line */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function uploadDocument(file: File): Promise<LoadedDocument> {
  const form = new FormData();
  form.append("file", file);
  return unwrap<LoadedDocument>(
    await fetch(`${BASE}/api/documents`, { method: "POST", body: form }),
  );
}

export async function extractText(text: string): Promise<Extraction> {
  return unwrap<Extraction>(
    await fetch(`${BASE}/api/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  );
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${BASE}/api/health`);
    return response.ok;
  } catch {
    return false;
  }
}

/** Thrown when the verifier did not run, as opposed to reaching no conclusion. */
export class VerifierUnavailable extends Error {}

export async function verifyCases(
  groups: CitationGroup[],
): Promise<Record<string, VerifiedCase>> {
  const payload = groups.map((g) => ({
    groupId: g.id,
    volume: g.header.volume,
    reporter: g.header.reporter,
    page: g.header.page,
    plaintiff: g.header.plaintiff,
    defendant: g.header.defendant,
    year: g.header.year,
    court: g.header.court,
    // The parenthetical as printed. eyecite resolves "Colo." to a court id
    // but not "Colo. App.", so this is often the only evidence of which
    // court a citation belongs to.
    courtText: g.header.court_text,
    // Non-adversarial captions ("In re Marriage of ...") have one party, not
    // two, so plaintiff and defendant are both null and this is the name.
    caseName: g.header.case_name,
  }));

  const response = await fetch(`${BASE}/api/verify/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ groups: payload }),
  });

  // 503 means the verifier is down or unconfigured. It must never be shown as
  // "nothing verified", which reads identically to a document full of
  // fabricated citations.
  if (response.status === 503) {
    let reason = "The verifier is unavailable.";
    try {
      const body = await response.json();
      if (body?.detail) reason = String(body.detail);
    } catch {
      /* no JSON body; keep the default */
    }
    throw new VerifierUnavailable(reason);
  }

  const body = await unwrap<{ verified: VerifiedCase[] }>(response);
  return Object.fromEntries(body.verified.map((v) => [v.groupId, v]));
}
