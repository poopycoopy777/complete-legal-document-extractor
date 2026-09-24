import type {
  CheckStatus,
  CitationGroup,
  Extraction,
  LoadedDocument,
  StageResult,
  Span,
  VerifiedCase,
} from "./types";

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
  const response = await fetch(`${BASE}/api/verify/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ groups }),
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

  const body = await unwrap<{
    verified: VerifiedCase[];
    results?: ServiceResult[];
  }>(response);

  // Start from the positive-only array so a service that predates `results`
  // still renders, then fold in every dimension the service now reports --
  // including the cases it flagged, which the positive-only array omits.
  const byId: Record<string, VerifiedCase> = Object.fromEntries(
    body.verified.map((v) => [v.groupId, v]),
  );

  for (const r of body.results ?? []) {
    const id = r.caller_id;
    const passed = r.identity?.status === "pass";
    const base: VerifiedCase = byId[id] ?? {
      groupId: id,
      status: "citation_verified",
      clusterId: r.identity?.cluster_id ?? null,
      checks: {
        reporterCitation: passed,
        caseName: passed,
        year: passed,
        court: passed,
      },
    };
    byId[id] = {
      ...base,
      identity: {
        status: r.identity.status,
        reason: r.identity.reason_code,
        message: r.identity.message,
      },
      pinCite: stage(r.pin_cite),
      quotation: stage(r.quotation),
      history: r.treatment
        ? {
            status: historyStatus(r.treatment.status),
            reason: r.treatment.reason_code,
            detail: r.treatment.message ?? null,
            role: null,
            page: null,
          }
        : undefined,
      quotations: (r.quotations ?? []).map((q) => ({
        sourceSpan: q.source_span,
        text: q.text,
        pinCite: q.pin_cite ?? null,
        pinPage: q.pin_page ?? null,
        status: q.finding?.status ?? "not_run",
        reason: q.finding?.reason_code ?? "",
      })),
      occurrences: (r.occurrences ?? []).map((o) => ({
        occurrenceId: o.occurrence_id, sourceSpan: o.source_span, text: o.text,
        pinCite: stage(o.pin_cite), opinionPart: stage(o.opinion_part),
      })),
    };
  }

  return byId;
}

interface ServiceFinding {
  status: CheckStatus;
  reason_code: string;
  detail: string | null;
  role: string | null;
  page: number | null;
}

interface ServiceResult {
  caller_id: string;
  identity: {
    status: CheckStatus;
    reason_code: string;
    message: string;
    cluster_id: number | null;
  };
  pin_cite: ServiceFinding | null;
  quotation: ServiceFinding | null;
  treatment: { status: string; reason_code: string; message: string } | null;
  quotations?: {
    source_span?: Span | null;
    text: string;
    pin_cite: string | null;
    pin_page: number | null;
    finding: ServiceFinding | null;
  }[];
  occurrences?: {
    occurrence_id: string;
    source_span: Span;
    text: string;
    pin_cite: ServiceFinding | null;
    opinion_part: ServiceFinding | null;
  }[];
}

function stage(f: ServiceFinding | null | undefined): StageResult | undefined {
  if (!f) return undefined;
  return {
    status: f.status,
    reason: f.reason_code,
    detail: f.detail ?? null,
    role: f.role ?? null,
    page: f.page ?? null,
  };
}

/**
 * History has its own vocabulary because "good law" is not a claim this corpus
 * can make. Only an affirmative adverse finding is a failure; everything else
 * is incomplete coverage, which is not a finding against the citation.
 */
function historyStatus(raw: string): CheckStatus {
  if (raw === "adverse_treatment_found") return "fail";
  if (raw === "history_checked_no_adverse_found") return "pass";
  if (raw === "history_unavailable") return "unavailable";
  return "not_run";
}
