export type ConstraintStatus = "pass" | "fail" | "unknown";
export type Stage =
  | "front_door" | "upload" | "profile_draft" | "awaiting_confirmation"
  | "watchlist" | "discovering" | "ready";

export interface EvidenceItem {
  evidenceId: string; claim: string; sourceExcerpt: string; sourceLocator: string;
}
export interface ProfileQuestion {
  key: string; prompt: string; reason: string; anchorSection: string; answer?: string;
}
export interface ProfileDraftData {
  roleShapes: string[]; hardConstraints: string[]; preferredWork: string[];
  excludedWork: string[]; evidence: EvidenceItem[]; knownGaps: string[];
  employerThesis: string; questions: ProfileQuestion[];
}
export interface CompanyRec {
  name: string; tier: "core" | "adjacent" | "exploratory"; reason: string;
  pending: boolean; removed: boolean;
}
export interface ConstraintResult {
  constraint: string; status: ConstraintStatus; explanation: string;
}
export interface ShortlistItem {
  postingUrl: string; company: string; title: string; location: string;
  freshness: string; source: string; score: number;
  constraintResults: ConstraintResult[]; whyFit: string;
  evidence: EvidenceItem[]; tradeoffs: string[]; uncertainties: string[];
  feedback?: "useful" | "not_useful";
}
export interface DiscoveryRow {
  company: string;
  state: "waiting" | "fetching" | "assessed" | "source_error";
  detail: string;
}

export function overallStatus(results: ConstraintResult[]): ConstraintStatus {
  const statuses = new Set(results.map((r) => r.status));
  if (statuses.has("fail")) return "fail";
  if (statuses.has("unknown")) return "unknown";
  return "pass";
}
