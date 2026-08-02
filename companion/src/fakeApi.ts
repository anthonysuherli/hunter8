import type { CompanionApi } from "./api";
import type { CompanyRec, DiscoveryRow, ProfileDraftData, ShortlistItem } from "./domain";

const INVITED = new Set(["tester@delapan.ai"]);

const DRAFT: ProfileDraftData = {
  roleShapes: ["Agentic systems engineer", "Applied AI engineer"],
  hardConstraints: ["New York or remote (US)"],
  preferredWork: ["Production agent runtimes", "Evaluation harnesses"],
  excludedWork: ["Pure dashboarding"],
  evidence: [
    { evidenceId: "ev-1", claim: "Built a production multi-agent runtime.",
      sourceExcerpt: "Built 12-agent runtime with JSON-Schema contracts and human-in-the-loop checkpoints",
      sourceLocator: "résumé p.1 · Vanguard AI Garage" },
    { evidenceId: "ev-2", claim: "Owns evaluation infrastructure.",
      sourceExcerpt: "Evaluation harnesses: RAGAS, hallucination scoring, regression gating",
      sourceLocator: "résumé p.2" },
  ],
  knownGaps: ["Work authorization unstated"],
  employerThesis: "AI systems roles near investment decisions.",
  questions: [
    { key: "location", prompt: "Which locations are acceptable?",
      reason: "Location constraint unclear — affects company selection",
      anchorSection: "hardConstraints" },
    { key: "authorization", prompt: "Do you require visa sponsorship?",
      reason: "Work authorization affects hard-constraint evaluation",
      anchorSection: "hardConstraints" },
  ],
};

const COMPANIES: CompanyRec[] = [
  { name: "Hebbia", tier: "core", reason: "Agentic doc-intelligence for finance — your Hybrid Knowledge System work is their product surface.", pending: false, removed: false },
  { name: "Neuberger Berman", tier: "core", reason: "Req names MCP + RAG explicitly; regulated-enterprise depth applies.", pending: false, removed: false },
  { name: "Rogo", tier: "core", reason: "AI analyst for IB workflows; evidence: multi-agent runtime, eval harness.", pending: false, removed: false },
  { name: "Databricks", tier: "adjacent", reason: "Agent platform scale; trade-off: further from finance domain.", pending: false, removed: false },
  { name: "Norm Ai", tier: "adjacent", reason: "Regulatory agents — your audit-trail work as the product.", pending: true, removed: false },
  { name: "Notion", tier: "exploratory", reason: "Enterprise-knowledge surface; unproven finance angle.", pending: false, removed: false },
];

const SHORTLIST: ShortlistItem[] = [
  { postingUrl: "https://jobs.workable.com/view/nb-1", company: "Neuberger Berman",
    title: "Senior Developer, AI Software Engineer", location: "New York",
    freshness: "posted 3d ago", source: "ats:workable", score: 86,
    constraintResults: [
      { constraint: "New York or remote (US)", status: "pass", explanation: "NYC office." },
      { constraint: "Visa sponsorship", status: "unknown", explanation: "Not stated in posting." },
    ],
    whyFit: "The requirements name MCP, agentic workflows, and RAG explicitly — the same systems you shipped. Level (7+ yrs SWE / 2+ AI) sits on your band.",
    evidence: DRAFT.evidence, tradeoffs: ["Comp band sits below buy-side alternatives."],
    uncertainties: ["Hybrid days per week unknown"] },
  { postingUrl: "https://careers.bankofamerica.com/26009617", company: "Bank of America",
    title: "Principal Engineer, GenAI Team", location: "New York",
    freshness: "posted 6d ago", source: "ats:workday", score: 74,
    constraintResults: [
      { constraint: "Seniority band", status: "unknown", explanation: "Asks 10+ years." },
    ],
    whyFit: "Agent architecture at scale in a regulated bank; audit-trail experience is the differentiator.",
    evidence: [DRAFT.evidence[1]], tradeoffs: ["Applying up a level."], uncertainties: [] },
];

const DISCOVERY_SCRIPT: DiscoveryRow["state"][] = ["waiting", "fetching", "assessed"];

export function makeFakeApi(opts: { failCompany?: string; emptyShortlist?: boolean } = {}): CompanionApi {
  let version = 0;
  let draft: ProfileDraftData = structuredClone(DRAFT);
  return {
    async signIn(email) {
      return INVITED.has(email)
        ? { ok: true }
        : { ok: false, refusal: "This address has no invite. The companion is invite-only for now." };
    },
    async uploadResume(text) {
      if (!text.trim()) return { ok: false, reason: "parse error: the document contained no readable text" };
      draft = structuredClone(DRAFT);
      return { ok: true, draft };
    },
    async answerQuestion(key, answer) {
      draft = {
        ...draft,
        hardConstraints: [...draft.hardConstraints, answer],
        questions: draft.questions.map((q) => (q.key === key ? { ...q, answer } : q)),
      };
      return draft;
    },
    async confirmThesis() { version += 1; return { version }; },
    async getCompanies() { return structuredClone(COMPANIES); },
    async addCompany(careersUrl) {
      const name = new URL(careersUrl).hostname.replace(/^www\./, "").split(".")[0];
      return { name, tier: "exploratory", reason: `Added by you (${careersUrl}) — board being checked.`, pending: true, removed: false };
    },
    async approveCompanies() {},
    subscribeDiscovery(onUpdate) {
      const names = COMPANIES.filter((c) => !c.pending).map((c) => c.name);
      let step = 0;
      const tick = () => {
        step += 1;
        const rows: DiscoveryRow[] = names.map((company, i) => {
          if (company === opts.failCompany && step > i)
            return { company, state: "source_error", detail: "source error: board unreachable" };
          const state = DISCOVERY_SCRIPT[Math.min(Math.max(step - i, 0), 2)];
          const detail = state === "assessed" ? "12 postings · 3 assessed"
            : state === "fetching" ? "reading board…" : "queued";
          return { company, state, detail };
        });
        const done = rows.every((r) => r.state === "assessed" || r.state === "source_error");
        onUpdate(rows, done);
        if (!done) timer = setTimeout(tick, 10);
      };
      let timer = setTimeout(tick, 0);
      return () => clearTimeout(timer);
    },
    async getShortlist() {
      if (opts.emptyShortlist)
        return { items: [], emptyReason: "No postings matched your confirmed constraints. Sources were all reachable; ranking is complete." };
      return { items: structuredClone(SHORTLIST) };
    },
    async sendFeedback() {},
    async deleteAccount() { return { state: "done" }; },
  };
}
