import type { Extraction, LoadedDocument } from "./types";

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
