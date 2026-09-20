export type Span = [number, number];

export type CitationKind =
  | "FullCaseCitation"
  | "ShortCaseCitation"
  | "SupraCitation"
  | "IdCitation"
  | "ReferenceCitation"
  | "UnknownCitation";

export interface Citation {
  kind: CitationKind;
  text: string;
  span: Span;
  volume: string | null;
  reporter: string | null;
  page: string | null;
  pin_cite: string | null;
  year: number | null;
  court: string | null;
  plaintiff: string | null;
  defendant: string | null;
  parenthetical: string | null;
  antecedent: string | null;
  corrected: string | null;
  /** Court text exactly as the citation's own parenthetical gives it. */
  court_text: string | null;
  /** A non-adversarial caption ("In re Marriage of X"): one party, not two. */
  case_name: string | null;
  /** The complete citation, assembled from verified parts. Full cites only. */
  full_citation: string | null;
  flags: string[];
}

export interface Quote {
  text: string;
  span: Span;
  pin_cite: string | null;
}

export interface CitationGroup {
  id: string;
  caseName: string | null;
  header: Citation;
  children: Citation[];
  quotes: Quote[];
}

export type AuthorityCategory =
  | "statute"
  | "regulation"
  | "rule"
  | "constitution";

export interface Authority {
  category: AuthorityCategory;
  source: string;
  text: string;
  span: Span;
  name: string | null;
  url: string | null;
  tokens: Record<string, string>;
  is_shortform: boolean;
}

export interface AuthorityGroup {
  id: string;
  category: AuthorityCategory;
  source: string;
  header: Authority;
  children: Authority[];
}

/** Section headings for the authority blocks beneath the case law. */
export const CATEGORY_LABEL: Record<AuthorityCategory, string> = {
  statute: "Statutes",
  regulation: "Regulations",
  rule: "Rules of procedure & evidence",
  constitution: "Constitutional provisions",
};

export const CATEGORY_ORDER: AuthorityCategory[] = [
  "statute",
  "regulation",
  "rule",
  "constitution",
];

export interface ExtractionStats {
  groups: number;
  citations: number;
  quotes: number;
  flagged: number;
  authorities: number;
  authorityCitations: number;
}

export interface Extraction {
  text: string;
  groups: CitationGroup[];
  orphans: Citation[];
  authorities: AuthorityGroup[];
  stats: ExtractionStats;
}

export interface PdfPageInfo {
  index: number;
  start: number;
  end: number;
  width: number;
  height: number;
}

/** A resolved location for one extracted span inside a rendered PDF. */
export interface Highlight {
  span: Span;
  page: number;
  /** PDF user-space rectangles [x0, y0, x1, y1]; empty when not located. */
  rects: [number, number, number, number][];
}

/** Provenance for text recovered by OCR. */
export interface OcrInfo {
  engine: string;
  dpi: number;
  language: string;
  pages: number;
  emptyPages: number;
  chars: number;
}

export interface LoadedDocument {
  id: string;
  name: string;
  kind: "pdf" | "text";
  sha256: string;
  uploadedAt: string;
  pageCount: number;
  pages: PdfPageInfo[];
  highlights: Highlight[];
  /** Set when the PDF has no usable text layer, or when OCR was used. */
  warning: string | null;
  /** Where the text came from: the PDF's own layer, or OCR. */
  textSource: "embedded" | "ocr";
  ocr: OcrInfo | null;
  notes: string[];
  rawUrl: string;
  extraction: Extraction;
}

export type ThemeName = "light" | "dark" | "crimson";

export interface LogEntry {
  time: string;
  message: string;
  level: "info" | "error";
}

/** A citation the user has focused, identified by its span. */
export type Selection = { groupId: string; span: Span } | null;

export const KIND_LABEL: Record<CitationKind, string> = {
  FullCaseCitation: "full",
  ShortCaseCitation: "short",
  SupraCitation: "supra",
  IdCitation: "id.",
  ReferenceCitation: "ref",
  UnknownCitation: "unknown",
};

/** One case whose identity the verifier confirmed. */
export interface VerifiedCase {
  groupId: string;
  status: "citation_verified";
  clusterId: number | null;
  checks: {
    reporterCitation: boolean;
    caseName: boolean;
    year: boolean;
    court: boolean;
  };
}

/**
 * Verification is positive-only, so this models three distinct states that
 * must never be collapsed in the UI:
 *
 * - "verified": the stage ran and confirmed this case's identity.
 * - "unresolved": the stage ran and reached no conclusion. NOT a finding
 *   against the citation. The corpus is a CourtListener snapshot, not the
 *   universe of American law, so a real citation can be absent from it.
 * - "unavailable": the stage did not run. Rendering this as "nothing
 *   verified" would make an outage look like a document full of bad cites.
 */
export type VerificationState =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "done"; verified: Record<string, VerifiedCase> }
  | { kind: "unavailable"; reason: string };
