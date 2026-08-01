import type { CompanyRec, DiscoveryRow, ProfileDraftData, ShortlistItem } from "./domain";

export interface CompanionApi {
  signIn(email: string): Promise<{ ok: true } | { ok: false; refusal: string }>;
  uploadResume(text: string): Promise<{ ok: true; draft: ProfileDraftData } | { ok: false; reason: string }>;
  answerQuestion(key: string, answer: string): Promise<ProfileDraftData>;
  confirmThesis(): Promise<{ version: number }>;
  getCompanies(): Promise<CompanyRec[]>;
  addCompany(careersUrl: string): Promise<CompanyRec>;
  approveCompanies(names: string[]): Promise<void>;
  subscribeDiscovery(onUpdate: (rows: DiscoveryRow[], done: boolean) => void): () => void;
  getShortlist(): Promise<{ items: ShortlistItem[]; emptyReason?: string }>;
  sendFeedback(postingUrl: string, value: "useful" | "not_useful"): Promise<void>;
  deleteAccount(): Promise<{ state: "done" | "delete_error" }>;
}
