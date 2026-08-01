# Hosted Companion MVP UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use truenorth:subagent-driven-development (recommended) or truenorth:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the companion frontend — the dossier shell and all seven screens from the UI spec — as a separate app that runs entirely against a deterministic fake API, ready for the real API client when the hosted security spine (umbrella child plan 2) lands.

**Architecture:** A new `companion/` Vite + React 18 + TypeScript app inside this repo with a hard import boundary (no imports from the repo root — mirrors the `hunter8_core` boundary test). All data flows through a `CompanionApi` TypeScript interface; this plan implements only `FakeCompanionApi` (in-memory, injectable clock, scripted discovery fill-in). Screens are state-driven views over a zustand store; no router library.

**Vision goals served:** End Goal 5 — the invite-only companion's user-facing surface, built without touching hunter8's personal runtime.

**Tech Stack:** Vite 6, React 18, TypeScript 5, zustand 5, vitest 3 + @testing-library/react + @testing-library/user-event + jsdom. Fonts: General Sans (Fontshare CDN), Source Serif 4 (Google Fonts CDN) — declared in `index.html`, per the anthropic-design skill's font-declaration requirement.

## Global Constraints

- The UI spec (`docs/truenorth/specs/2026-08-01-hosted-companion-ui-design.md`) and its parent umbrella spec govern all copy and behavior; where this plan quotes copy, use it verbatim.
- Design tokens verbatim from the anthropic-design skill: page `#faf9f5` (dark `#141413`), surfaces `#f0eee6`/`#e8e6dc`/`#d1cfc5`, ink `#141413`, secondary text `#5e5d59`, clay `#d97757`, focus ring `#2c84db`. No pure white/black, no gradients, no shadows except overlay levels, no border-radius above 16px on components.
- Constraint-status token everywhere: pass = quiet tint chip, fail = solid ink chip, unknown/pending = dashed clay-outline chip.
- Clay budget: one accent element per dossier section (two allowed in the open shortlist row: score + original link).
- Errors are inline text in place — never toasts, never status modals. Loading is opacity fade — no shimmer, no spinners.
- Serif (`Source Serif 4`) for prose/evidence only; sans (`General Sans`) for all UI chrome; no mono anywhere in this app.
- `companion/` imports nothing from the repo root (enforced by test in Task 1).
- No apply/outreach/save/share affordances anywhere. Feedback is Useful / Not useful only.
- Run `cd companion && npx vitest run` before declaring any task complete; the full suite gates Task 8.

---

## File map

**Create (all under `companion/`)**

- `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html` — app scaffold; fonts declared in `index.html`.
- `src/styles/tokens.css` — design-token custom properties, light + dark.
- `src/styles/app.css` — component classes (dossier, ledger, chips, buttons, queries).
- `src/domain.ts` — UI-side domain types (mirrors `hunter8_core` contract names).
- `src/api.ts` — `CompanionApi` interface.
- `src/fakeApi.ts` — `FakeCompanionApi` + fixtures + scripted discovery timeline.
- `src/store.ts` — zustand store: session, dossier stage, per-stage data.
- `src/components/ConstraintChip.tsx`, `ClayButton.tsx`, `EvidenceBlock.tsx`, `FeedbackPills.tsx`, `EditorQuery.tsx`, `DossierSection.tsx`, `SectionRail.tsx`.
- `src/screens/FrontDoor.tsx`, `Upload.tsx`, `ProfileDraft.tsx`, `ThesisConfirm.tsx`, `CompanyConfirm.tsx`, `Shortlist.tsx`, `Account.tsx`.
- `src/App.tsx`, `src/main.tsx`.
- Tests: `test/boundary.test.ts`, `test/fakeApi.test.ts`, `test/primitives.test.tsx`, `test/dossier.test.tsx`, `test/entry.test.tsx`, `test/profile.test.tsx`, `test/companies.test.tsx`, `test/shortlist.test.tsx`, `test/account.test.tsx`.

**Modify**

- Repo root `README.md` — one line pointing at `companion/` (Task 8).

## Interfaces locked by this plan

```ts
// src/domain.ts — names mirror hunter8_core; UI-only fields marked.
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
  pending: boolean; removed: boolean;   // removed is UI-local until approval
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
  detail: string;   // "12 postings · 3 assessed" | "source error: board unreachable"
}

export function overallStatus(results: ConstraintResult[]): ConstraintStatus;
// fail > unknown > pass — same precedence as hunter8_core.MatchAssessment.
```

```ts
// src/api.ts
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
```

```ts
// src/store.ts (zustand)
interface AppState {
  stage: Stage;
  confirmedStages: Stage[];          // sections rendered locked
  draft: ProfileDraftData | null;
  profileVersion: number | null;
  companies: CompanyRec[];
  discovery: DiscoveryRow[];
  shortlist: ShortlistItem[];
  emptyReason: string | null;
  setStage(s: Stage): void;
  // one setter per field, same names: setDraft, setProfileVersion, setCompanies,
  // setDiscovery, setShortlist, setEmptyReason, lockStage(s: Stage)
}
export const useApp: UseBoundStore<StoreApi<AppState>>;
```

---

### Task 1: Scaffold, tokens, fonts, and the import boundary

**Files:**
- Create: `companion/package.json`, `companion/tsconfig.json`, `companion/vite.config.ts`, `companion/index.html`, `companion/src/styles/tokens.css`, `companion/src/main.tsx`, `companion/src/App.tsx` (placeholder), `companion/test/boundary.test.ts`

**Interfaces:**
- Produces: a running `npx vitest run` harness and the token stylesheet every later task's classes reference.

- [ ] **Step 1: Scaffold the app**

```bash
cd /Users/anthonysuherli/Projects/hunter8
mkdir -p companion/src/styles companion/src/components companion/src/screens companion/test
```

`companion/package.json`:

```json
{
  "name": "hunter8-companion",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^5.0.3"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.1",
    "typescript": "^5.7.3",
    "vite": "^6.1.0",
    "vitest": "^3.0.5"
  }
}
```

`companion/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022", "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext", "moduleResolution": "bundler", "jsx": "react-jsx",
    "strict": true, "noEmit": true, "skipLibCheck": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "test"]
}
```

`companion/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", globals: true, setupFiles: ["./test/setup.ts"] },
});
```

`companion/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`companion/index.html` (fonts declared here — General Sans from Fontshare, Source Serif 4 from Google Fonts):

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>hunter8 — your career dossier</title>
    <link rel="preconnect" href="https://api.fontshare.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700&display=swap" rel="stylesheet" />
    <link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,500&display=swap" rel="stylesheet" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`companion/src/main.tsx`:

```tsx
import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/tokens.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
```

`companion/src/App.tsx` (placeholder, replaced in Task 4):

```tsx
export function App() {
  return <main className="dossier" />;
}
```

- [ ] **Step 2: Write the token stylesheet**

`companion/src/styles/tokens.css` — values verbatim from the anthropic-design skill:

```css
:root {
  --background: #faf9f5; --surface1: #f0eee6; --surface2: #e8e6dc;
  --surface3: #d1cfc5; --border: #e8e6dc; --border-visible: #d1cfc5;
  --text1: #141413; --text2: #5e5d59; --text3: #87867f; --text4: #b0aea5;
  --accent: #d97757; --accent-subtle: #faf0eb;
  --error: #bf4d43; --error-bg: #faeeec;
  --focus: #2c84db;
  --font-sans: "General Sans", -apple-system, "Helvetica Neue", sans-serif;
  --font-serif: "Source Serif 4", Georgia, serif;
  --radius-control: 8px; --radius-component: 12px; --radius-pill: 999px;
  --ease: cubic-bezier(0.165, 0.84, 0.44, 1);
}
@media (prefers-color-scheme: dark) {
  :root {
    --background: #141413; --surface1: #1a1918; --surface2: #262624;
    --surface3: #3d3d3a; --border: #262624; --border-visible: #3d3d3a;
    --text1: #faf9f5; --text2: #b0aea5; --text3: #87867f; --text4: #5e5d59;
    --accent-subtle: #331709; --error-bg: #4a1d19;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--background); color: var(--text1);
  font-family: var(--font-sans); font-size: 15px; line-height: 1.4;
}
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
```

- [ ] **Step 3: Write the failing boundary test**

`companion/test/boundary.test.ts` — same rule as `hunter8_core`'s dependency test, inverted for the frontend: nothing in `companion/src` may import from the repo root or reference personal artifacts.

```ts
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe("companion boundary", () => {
  it("imports nothing from the hunter8 repo root", () => {
    const files = walk("src").filter((f) => /\.(ts|tsx)$/.test(f));
    expect(files.length).toBeGreaterThan(0);
    const forbidden = /from\s+["'](\.\.\/)*\.\.\/(db|sources|watchlist|screen|score|discover|hunter8_core)/;
    for (const f of files) {
      expect(readFileSync(f, "utf8")).not.toMatch(forbidden);
    }
  });

  it("never references personal artifact names", () => {
    const files = walk("src");
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      expect(text).not.toMatch(/intent\.md|rubric\.md|hunter8\.db|watchlist\.yaml/);
    }
  });
});
```

- [ ] **Step 4: Install and run**

```bash
cd companion && npm install && npx vitest run
```

Expected: both boundary tests PASS (App.tsx and main.tsx exist and are clean).

- [ ] **Step 5: Commit**

```bash
git add companion package.json 2>/dev/null; git add companion
git commit -m "feat(companion): scaffold the dossier app with design tokens and import boundary"
```

---

### Task 2: Domain types and the fake API

**Files:**
- Create: `companion/src/domain.ts`, `companion/src/api.ts`, `companion/src/fakeApi.ts`
- Test: `companion/test/fakeApi.test.ts`

**Interfaces:**
- Produces: everything in "Interfaces locked by this plan" above, plus `makeFakeApi(opts?: { failCompany?: string; emptyShortlist?: boolean })`.
- The fake's fixture data is the mockups' content: Hebbia / Neuberger Berman / Rogo (core), Databricks / Norm Ai (adjacent, Norm Ai pending), Notion (exploratory); shortlist led by "Senior Developer, AI Software Engineer — Neuberger Berman, score 86".

- [ ] **Step 1: Write the failing tests**

`companion/test/fakeApi.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { overallStatus } from "../src/domain";
import { makeFakeApi } from "../src/fakeApi";

describe("overallStatus precedence", () => {
  it("fail beats unknown beats pass", () => {
    expect(overallStatus([
      { constraint: "a", status: "pass", explanation: "" },
      { constraint: "b", status: "unknown", explanation: "" },
    ])).toBe("unknown");
    expect(overallStatus([
      { constraint: "a", status: "unknown", explanation: "" },
      { constraint: "b", status: "fail", explanation: "" },
    ])).toBe("fail");
    expect(overallStatus([])).toBe("pass");
  });
});

describe("FakeCompanionApi", () => {
  it("refuses uninvited emails with a plain reason", async () => {
    const api = makeFakeApi();
    const res = await api.signIn("stranger@example.com");
    expect(res).toEqual({ ok: false, refusal: expect.stringContaining("invite") });
  });

  it("extracts a draft with unanswered questions from resume text", async () => {
    const api = makeFakeApi();
    await api.signIn("tester@delapan.ai");
    const up = await api.uploadResume("some resume text");
    if (!up.ok) throw new Error("expected ok");
    expect(up.draft.questions.length).toBeGreaterThan(0);
    expect(up.draft.questions[0].anchorSection).toBeTruthy();
  });

  it("rejects an empty upload with a parse reason", async () => {
    const api = makeFakeApi();
    const up = await api.uploadResume("");
    expect(up).toEqual({ ok: false, reason: expect.stringContaining("parse") });
  });

  it("streams discovery rows to done, keeping a failed company visible", async () => {
    const api = makeFakeApi({ failCompany: "Norm Ai" });
    const frames: { rows: string; done: boolean }[] = [];
    await new Promise<void>((resolve) => {
      api.subscribeDiscovery((rows, done) => {
        frames.push({ rows: JSON.stringify(rows), done });
        if (done) resolve();
      });
    });
    const last = JSON.parse(frames.at(-1)!.rows) as { company: string; state: string; detail: string }[];
    const failed = last.find((r) => r.company === "Norm Ai");
    expect(failed?.state).toBe("source_error");
    expect(failed?.detail).toContain("source error");
    expect(last.filter((r) => r.state === "assessed").length).toBeGreaterThan(0);
  });

  it("explains an empty shortlist instead of returning bare nothing", async () => {
    const api = makeFakeApi({ emptyShortlist: true });
    const res = await api.getShortlist();
    expect(res.items).toHaveLength(0);
    expect(res.emptyReason).toBeTruthy();
  });

  it("confirmThesis returns version 1 then version 2", async () => {
    const api = makeFakeApi();
    expect((await api.confirmThesis()).version).toBe(1);
    expect((await api.confirmThesis()).version).toBe(2);
  });
});
```

- [ ] **Step 2: Run and verify failure**

```bash
cd companion && npx vitest run test/fakeApi.test.ts
```

Expected: FAIL — modules do not exist.

- [ ] **Step 3: Implement domain.ts**

Copy the `src/domain.ts` block from "Interfaces locked by this plan" verbatim, and implement:

```ts
export function overallStatus(results: ConstraintResult[]): ConstraintStatus {
  const statuses = new Set(results.map((r) => r.status));
  if (statuses.has("fail")) return "fail";
  if (statuses.has("unknown")) return "unknown";
  return "pass";
}
```

- [ ] **Step 4: Implement api.ts and fakeApi.ts**

`companion/src/api.ts`: the `CompanionApi` interface verbatim from the locked block.

`companion/src/fakeApi.ts`:

```ts
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
    evidence: [DRAFT.evidence[0]], tradeoffs: ["Applying up a level."], uncertainties: [] },
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
      return { name, tier: "exploratory", reason: `Added by you (${careersUrl}) — verifying board.`, pending: true, removed: false };
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
```

- [ ] **Step 5: Run the tests**

```bash
cd companion && npx vitest run test/fakeApi.test.ts test/boundary.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add companion/src/domain.ts companion/src/api.ts companion/src/fakeApi.ts companion/test/fakeApi.test.ts
git commit -m "feat(companion): domain types, CompanionApi contract, deterministic fake"
```

---

### Task 3: Primitives — chips, buttons, evidence, feedback

**Files:**
- Create: `companion/src/components/ConstraintChip.tsx`, `companion/src/components/ClayButton.tsx`, `companion/src/components/EvidenceBlock.tsx`, `companion/src/components/FeedbackPills.tsx`, `companion/src/styles/app.css`
- Test: `companion/test/primitives.test.tsx`

**Interfaces:**
- Produces:
  - `ConstraintChip({ status, label }: { status: ConstraintStatus; label: string })`
  - `ClayButton({ children, onClick, disabled? })`
  - `EvidenceBlock({ item }: { item: EvidenceItem })`
  - `FeedbackPills({ value, onChange }: { value?: "useful" | "not_useful"; onChange: (v) => void })`

- [ ] **Step 1: Write the failing tests**

`companion/test/primitives.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ClayButton } from "../src/components/ClayButton";
import { ConstraintChip } from "../src/components/ConstraintChip";
import { EvidenceBlock } from "../src/components/EvidenceBlock";
import { FeedbackPills } from "../src/components/FeedbackPills";

describe("ConstraintChip", () => {
  it("renders each status as its own visual class", () => {
    const { rerender } = render(<ConstraintChip status="pass" label="NYC" />);
    expect(screen.getByText("NYC")).toHaveClass("chip", "chip-pass");
    rerender(<ConstraintChip status="fail" label="onsite only" />);
    expect(screen.getByText("onsite only")).toHaveClass("chip-fail");
    rerender(<ConstraintChip status="unknown" label="sponsorship?" />);
    expect(screen.getByText("sponsorship?")).toHaveClass("chip-unknown");
  });
});

describe("ClayButton", () => {
  it("fires onClick and respects disabled", async () => {
    const onClick = vi.fn();
    render(<ClayButton onClick={onClick}>Confirm</ClayButton>);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("EvidenceBlock", () => {
  it("quotes the excerpt and shows the source locator", () => {
    render(<EvidenceBlock item={{ evidenceId: "e", claim: "c",
      sourceExcerpt: "Built 12-agent runtime", sourceLocator: "résumé p.1" }} />);
    expect(screen.getByText(/Built 12-agent runtime/)).toBeInTheDocument();
    expect(screen.getByText(/résumé p\.1/)).toBeInTheDocument();
  });
});

describe("FeedbackPills", () => {
  it("offers exactly Useful and Not useful and reports the choice", async () => {
    const onChange = vi.fn();
    render(<FeedbackPills onChange={onChange} />);
    expect(screen.getAllByRole("button")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Useful" }));
    expect(onChange).toHaveBeenCalledWith("useful");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd companion && npx vitest run test/primitives.test.tsx
```

Expected: FAIL — components missing.

- [ ] **Step 3: Implement the components and stylesheet**

`companion/src/components/ConstraintChip.tsx`:

```tsx
import type { ConstraintStatus } from "../domain";

export function ConstraintChip({ status, label }: { status: ConstraintStatus; label: string }) {
  return <span className={`chip chip-${status}`}>{label}</span>;
}
```

`companion/src/components/ClayButton.tsx`:

```tsx
import type { ReactNode } from "react";

export function ClayButton({ children, onClick, disabled }:
  { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button className="clay-button" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
```

`companion/src/components/EvidenceBlock.tsx`:

```tsx
import type { EvidenceItem } from "../domain";

export function EvidenceBlock({ item }: { item: EvidenceItem }) {
  return (
    <blockquote className="evidence">
      <p className="serif">“{item.sourceExcerpt}”</p>
      <footer className="evidence-src">— {item.sourceLocator}</footer>
    </blockquote>
  );
}
```

`companion/src/components/FeedbackPills.tsx`:

```tsx
export function FeedbackPills({ value, onChange }:
  { value?: "useful" | "not_useful"; onChange: (v: "useful" | "not_useful") => void }) {
  return (
    <span className="feedback">
      <button className={`pill ${value === "useful" ? "pill-active" : ""}`}
        onClick={() => onChange("useful")}>Useful</button>
      <button className={`pill ${value === "not_useful" ? "pill-active" : ""}`}
        onClick={() => onChange("not_useful")}>Not useful</button>
    </span>
  );
}
```

`companion/src/styles/app.css` (imported from `main.tsx` in Step 4; complete class set used across all tasks):

```css
.serif { font-family: var(--font-serif); font-size: 17px; line-height: 1.55; }
.dossier { max-width: 640px; margin: 0 auto; padding: 48px 24px 96px; }

.chip { display: inline-block; font-size: 12px; padding: 2px 10px;
  border-radius: var(--radius-pill); margin-right: 6px; }
.chip-pass { background: var(--surface2); color: var(--text2); }
.chip-fail { background: var(--text1); color: var(--background); }
.chip-unknown { background: transparent; color: var(--accent);
  border: 1px dashed var(--accent); }

.clay-button { background: var(--accent); color: #faf9f5; border: none;
  font-family: var(--font-sans); font-weight: 600; font-size: 15px;
  padding: 10px 22px; border-radius: var(--radius-pill); cursor: pointer;
  transition: background 150ms var(--ease); }
.clay-button:disabled { opacity: 0.4; cursor: default; }

.evidence { background: var(--surface1); border-radius: var(--radius-control);
  margin: 8px 0; padding: 10px 14px; }
.evidence-src { font-family: var(--font-sans); font-size: 12px; color: var(--text3); margin-top: 4px; }

.pill { background: transparent; border: 1px solid var(--border-visible);
  color: var(--text2); border-radius: var(--radius-pill); padding: 4px 14px;
  font-family: var(--font-sans); font-size: 13px; cursor: pointer; margin-right: 8px; }
.pill-active { background: var(--text1); color: var(--background); border-color: var(--text1); }

.section { margin-bottom: 48px; }
.section-locked { opacity: 0.75; }
.section-summary { color: var(--text2); font-size: 14px; }
.rail { position: fixed; left: 16px; top: 48px; font-size: 12px; color: var(--text3); }
.rail-item { margin-bottom: 8px; }
.rail-done { color: var(--text2); }
.rail-live { color: var(--text1); font-weight: 600; }
@media (max-width: 900px) { .rail { display: none; } }

.ledger-row { display: flex; justify-content: space-between; align-items: center;
  padding: 12px 8px; border-bottom: 1px solid var(--border); }
.ledger-open { background: var(--surface1); border-radius: 0 0 var(--radius-control) var(--radius-control);
  padding: 16px; }
.row-meta { font-size: 13px; color: var(--text2); }
.row-score { font-weight: 700; font-size: 22px; }
.row-score-open { color: var(--accent); }
.row-fade { opacity: 0.55; transition: opacity 250ms var(--ease); }

.tier-heading { font-weight: 700; font-size: 15px; margin: 24px 0 2px; }
.tier-sub { font-family: var(--font-serif); font-size: 14px; color: var(--text2); margin: 0 0 8px; }
.remove-x { background: none; border: none; color: var(--text3); font-size: 16px; cursor: pointer; }

.query { border-left: 3px solid var(--accent); background: var(--surface1);
  padding: 12px 16px; margin: 12px 0; }
.query-reason { font-size: 12px; color: var(--text3); margin-bottom: 6px; }

.text-input { border: 1px solid var(--border-visible); border-radius: var(--radius-control);
  background: var(--background); color: var(--text1); font-family: var(--font-sans);
  font-size: 15px; padding: 8px 12px; width: 100%; }

.display { font-family: var(--font-serif); font-weight: 500; font-size: 44px;
  line-height: 1.1; letter-spacing: -0.01em; }
.display u { text-decoration-thickness: 4px; text-underline-offset: 8px;
  text-decoration-color: var(--accent); }
.refusal { font-family: var(--font-serif); color: var(--error); }
.inline-error { font-family: var(--font-serif); color: var(--error); }
.muted { color: var(--text3); }
```

- [ ] **Step 4: Import app.css**

In `companion/src/main.tsx`, after the tokens import add:

```ts
import "./styles/app.css";
```

- [ ] **Step 5: Run tests**

```bash
cd companion && npx vitest run test/primitives.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add companion/src/components companion/src/styles/app.css companion/src/main.tsx companion/test/primitives.test.tsx
git commit -m "feat(companion): constraint chips, clay button, evidence block, feedback pills"
```

---

### Task 4: Dossier shell — store, sections, rail

**Files:**
- Create: `companion/src/store.ts`, `companion/src/components/DossierSection.tsx`, `companion/src/components/SectionRail.tsx`
- Modify: `companion/src/App.tsx`
- Test: `companion/test/dossier.test.tsx`

**Interfaces:**
- Consumes: `Stage` from domain.
- Produces:
  - `useApp` store exactly as locked above.
  - `DossierSection({ stage, title, summary, state, children })` where `state: "locked" | "live" | "hidden"` — locked renders collapsed summary; live renders children; hidden renders nothing.
  - `SectionRail()` — reads the store, renders one `.rail-item` per visible stage.
  - `App` renders `SectionRail` plus one screen component per stage (screens arrive in Tasks 5–8; until then App renders live sections' placeholders via a `SCREENS` map that later tasks fill in).

- [ ] **Step 1: Write the failing tests**

`companion/test/dossier.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DossierSection } from "../src/components/DossierSection";
import { SectionRail } from "../src/components/SectionRail";
import { useApp } from "../src/store";

describe("store", () => {
  it("locks stages in order and advances", () => {
    useApp.setState({ stage: "upload", confirmedStages: [] });
    useApp.getState().lockStage("upload");
    useApp.getState().setStage("profile_draft");
    expect(useApp.getState().confirmedStages).toContain("upload");
    expect(useApp.getState().stage).toBe("profile_draft");
  });
});

describe("DossierSection", () => {
  it("renders a collapsed summary when locked", () => {
    render(
      <DossierSection stage="upload" title="Résumé" summary="Parsed 2 pages" state="locked">
        <p>full content</p>
      </DossierSection>,
    );
    expect(screen.getByText("Parsed 2 pages")).toBeInTheDocument();
    expect(screen.queryByText("full content")).not.toBeInTheDocument();
  });

  it("renders children when live", () => {
    render(
      <DossierSection stage="upload" title="Résumé" summary="" state="live">
        <p>full content</p>
      </DossierSection>,
    );
    expect(screen.getByText("full content")).toBeInTheDocument();
  });
});

describe("SectionRail", () => {
  it("marks the live stage", () => {
    useApp.setState({ stage: "profile_draft", confirmedStages: ["upload"] });
    render(<SectionRail />);
    expect(screen.getByText("Profile")).toHaveClass("rail-live");
    expect(screen.getByText("Résumé")).toHaveClass("rail-done");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd companion && npx vitest run test/dossier.test.tsx
```

Expected: FAIL — store and components missing.

- [ ] **Step 3: Implement store.ts**

```ts
import { create } from "zustand";
import type { CompanyRec, DiscoveryRow, ProfileDraftData, ShortlistItem, Stage } from "./domain";

interface AppState {
  stage: Stage;
  confirmedStages: Stage[];
  draft: ProfileDraftData | null;
  profileVersion: number | null;
  companies: CompanyRec[];
  discovery: DiscoveryRow[];
  shortlist: ShortlistItem[];
  emptyReason: string | null;
  setStage: (s: Stage) => void;
  lockStage: (s: Stage) => void;
  setDraft: (d: ProfileDraftData) => void;
  setProfileVersion: (v: number) => void;
  setCompanies: (c: CompanyRec[]) => void;
  setDiscovery: (d: DiscoveryRow[]) => void;
  setShortlist: (s: ShortlistItem[]) => void;
  setEmptyReason: (r: string | null) => void;
}

export const useApp = create<AppState>((set) => ({
  stage: "front_door",
  confirmedStages: [],
  draft: null,
  profileVersion: null,
  companies: [],
  discovery: [],
  shortlist: [],
  emptyReason: null,
  setStage: (stage) => set({ stage }),
  lockStage: (s) => set((st) => ({
    confirmedStages: st.confirmedStages.includes(s) ? st.confirmedStages : [...st.confirmedStages, s],
  })),
  setDraft: (draft) => set({ draft }),
  setProfileVersion: (profileVersion) => set({ profileVersion }),
  setCompanies: (companies) => set({ companies }),
  setDiscovery: (discovery) => set({ discovery }),
  setShortlist: (shortlist) => set({ shortlist }),
  setEmptyReason: (emptyReason) => set({ emptyReason }),
}));
```

- [ ] **Step 4: Implement DossierSection and SectionRail**

`companion/src/components/DossierSection.tsx`:

```tsx
import type { ReactNode } from "react";
import type { Stage } from "../domain";

export function DossierSection({ title, summary, state, children }:
  { stage: Stage; title: string; summary: string;
    state: "locked" | "live" | "hidden"; children: ReactNode }) {
  if (state === "hidden") return null;
  if (state === "locked") {
    return (
      <section className="section section-locked">
        <h2>{title}</h2>
        <p className="section-summary">{summary}</p>
      </section>
    );
  }
  return (
    <section className="section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
```

`companion/src/components/SectionRail.tsx`:

```tsx
import type { Stage } from "../domain";
import { useApp } from "../store";

export const RAIL_LABELS: [Stage, string][] = [
  ["upload", "Résumé"],
  ["profile_draft", "Profile"],
  ["awaiting_confirmation", "Thesis"],
  ["watchlist", "Companies"],
  ["discovering", "Discovery"],
  ["ready", "Shortlist"],
];

export function SectionRail() {
  const { stage, confirmedStages } = useApp();
  return (
    <nav className="rail">
      {RAIL_LABELS.map(([s, label]) => (
        <div key={s}
          className={`rail-item ${s === stage ? "rail-live" : confirmedStages.includes(s) ? "rail-done" : ""}`}>
          {label}
        </div>
      ))}
    </nav>
  );
}
```

- [ ] **Step 5: Wire App.tsx**

```tsx
import { createContext, useContext } from "react";
import type { CompanionApi } from "./api";
import { SectionRail } from "./components/SectionRail";
import { makeFakeApi } from "./fakeApi";
import { useApp } from "./store";
import type { Stage } from "./domain";
import type { ComponentType } from "react";

export const ApiContext = createContext<CompanionApi>(makeFakeApi());
export const useApi = () => useContext(ApiContext);

// Screens register here as later tasks land; front_door is Task 5.
export const SCREENS: Partial<Record<Stage, ComponentType>> = {};

export function App() {
  const stage = useApp((s) => s.stage);
  const Screen = SCREENS[stage];
  return (
    <>
      {stage !== "front_door" && <SectionRail />}
      <main className="dossier">{Screen ? <Screen /> : null}</main>
    </>
  );
}
```

- [ ] **Step 6: Run tests and commit**

```bash
cd companion && npx vitest run
git add companion/src/store.ts companion/src/components/DossierSection.tsx companion/src/components/SectionRail.tsx companion/src/App.tsx companion/test/dossier.test.tsx
git commit -m "feat(companion): dossier shell — store, locked/live sections, rail"
```

Expected: all suites PASS.

---

### Task 5: Front door and upload

**Files:**
- Create: `companion/src/screens/FrontDoor.tsx`, `companion/src/screens/Upload.tsx`
- Modify: `companion/src/App.tsx` (register screens)
- Test: `companion/test/entry.test.tsx`

**Interfaces:**
- Consumes: `useApi`, `useApp`, `ClayButton`.
- Produces: `FrontDoor` (email flow + refusal line; LinkedIn button is present but disabled with the identity-only caption — real OIDC is child plan 2's), `Upload` (textarea paste path + provider disclosure + parse_error state). File drag-and-drop is deferred to the API-integration plan; the paste path is the spec's own fallback and exercises every state.

- [ ] **Step 1: Write the failing tests**

`companion/test/entry.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../src/App";
import { useApp } from "../src/store";

beforeEach(() => {
  useApp.setState({ stage: "front_door", confirmedStages: [], draft: null });
});

describe("front door", () => {
  it("shows the three-line promise and both sign-in controls", () => {
    render(<App />);
    expect(screen.getByText(/never applies on your behalf/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument();
    expect(screen.getByText(/sign-in only, we never read your profile/i)).toBeInTheDocument();
  });

  it("refuses an uninvited email inline without advancing", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/email/i), "stranger@example.com");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(await screen.findByText(/invite-only/i)).toBeInTheDocument();
    expect(useApp.getState().stage).toBe("front_door");
  });

  it("advances an invited email to upload", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/email/i), "tester@delapan.ai");
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByText(/paste your résumé/i);
    expect(useApp.getState().stage).toBe("upload");
  });
});

describe("upload", () => {
  beforeEach(() => useApp.setState({ stage: "upload" }));

  it("names the provider before anything is sent", () => {
    render(<App />);
    expect(screen.getByText(/extracted text is sent to the configured model provider/i)).toBeInTheDocument();
  });

  it("shows a parse error inline and stays on upload", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: /extract/i }));
    expect(await screen.findByText(/parse error/i)).toBeInTheDocument();
    expect(useApp.getState().stage).toBe("upload");
  });

  it("locks the section and advances on success", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/paste your résumé/i), "my resume text");
    await userEvent.click(screen.getByRole("button", { name: /extract/i }));
    await screen.findByText(/Profile/);
    expect(useApp.getState().stage).toBe("profile_draft");
    expect(useApp.getState().confirmedStages).toContain("upload");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd companion && npx vitest run test/entry.test.tsx
```

Expected: FAIL — screens missing.

- [ ] **Step 3: Implement FrontDoor.tsx**

```tsx
import { useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { useApp } from "../store";

export function FrontDoor() {
  const api = useApi();
  const setStage = useApp((s) => s.setStage);
  const [email, setEmail] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);

  async function submit() {
    const res = await api.signIn(email);
    if (res.ok) setStage("upload");
    else setRefusal(res.refusal);
  }

  return (
    <div>
      <h1 className="display">A career dossier, <u>written from your evidence</u>.</h1>
      <p className="serif">
        Upload a résumé. Confirm one career thesis. Receive an evidence-ranked
        shortlist of live roles. It never applies on your behalf.
      </p>
      <input className="text-input" placeholder="email address" value={email}
        onChange={(e) => setEmail(e.target.value)} />
      <p><ClayButton onClick={submit}>Continue</ClayButton></p>
      <p>
        <button className="pill" disabled>Continue with LinkedIn</button>
        <span className="muted"> sign-in only, we never read your profile</span>
      </p>
      {refusal && <p className="refusal">{refusal} The companion is invite-only for now.</p>}
    </div>
  );
}
```

Note: the fake's refusal string plus this suffix yields the tested "invite-only" copy; keep both.

- [ ] **Step 4: Implement Upload.tsx**

```tsx
import { useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { useApp } from "../store";

export function Upload() {
  const api = useApi();
  const { setStage, lockStage, setDraft } = useApp();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function extract() {
    setError(null);
    const res = await api.uploadResume(text);
    if (!res.ok) { setError(res.reason); return; }
    setDraft(res.draft);
    lockStage("upload");
    setStage("profile_draft");
  }

  return (
    <div>
      <h2>Résumé</h2>
      <textarea className="text-input" rows={10}
        placeholder="paste your résumé text here" value={text}
        onChange={(e) => setText(e.target.value)} />
      <p className="muted">
        Extracted text is sent to the configured model provider to draft your
        profile. The raw document never leaves the parser.
      </p>
      <ClayButton onClick={extract}>Extract profile</ClayButton>
      {error && <p className="inline-error">{error} — fix the text and retry.</p>}
    </div>
  );
}
```

- [ ] **Step 5: Register the screens**

In `companion/src/App.tsx`, replace the empty `SCREENS` map:

```tsx
import { FrontDoor } from "./screens/FrontDoor";
import { Upload } from "./screens/Upload";

export const SCREENS: Partial<Record<Stage, ComponentType>> = {
  front_door: FrontDoor,
  upload: Upload,
};
```

The `profile_draft` advance in the upload test asserts on the rail label "Profile" rendering — which the rail already provides once stage advances.

- [ ] **Step 6: Run and commit**

```bash
cd companion && npx vitest run
git add companion/src/screens/FrontDoor.tsx companion/src/screens/Upload.tsx companion/src/App.tsx companion/test/entry.test.tsx
git commit -m "feat(companion): front door with invite refusal, upload with provider disclosure"
```

Expected: all suites PASS.

---

### Task 6: Profile draft, editor's queries, thesis confirmation

**Files:**
- Create: `companion/src/components/EditorQuery.tsx`, `companion/src/screens/ProfileDraft.tsx`, `companion/src/screens/ThesisConfirm.tsx`
- Modify: `companion/src/App.tsx` (register)
- Test: `companion/test/profile.test.tsx`

**Interfaces:**
- Consumes: store, api, `EvidenceBlock`, `ClayButton`, `DossierSection`.
- Produces:
  - `EditorQuery({ question, onAnswer })` — renders `.query` with `.query-reason` = `question.reason`, an input, and an Answer button.
  - `ProfileDraft` — draft sections + one active query at a time (first unanswered); when none remain, an ink "Review thesis" button advances to `awaiting_confirmation`.
  - `ThesisConfirm` — full summary + known gaps prose + clay Confirm; on confirm locks both stages, stores the version, advances to `watchlist`.

- [ ] **Step 1: Write the failing tests**

`companion/test/profile.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../src/App";
import { makeFakeApi } from "../src/fakeApi";
import { useApp } from "../src/store";

async function seedDraft() {
  const api = makeFakeApi();
  const up = await api.uploadResume("resume");
  if (!up.ok) throw new Error("seed failed");
  useApp.setState({
    stage: "profile_draft", confirmedStages: ["upload"],
    draft: up.draft, profileVersion: null,
  });
}

describe("profile draft with editor's queries", () => {
  beforeEach(seedDraft);

  it("shows one active query with its reason as the anchor", () => {
    render(<App />);
    expect(screen.getByText(/Location constraint unclear/)).toBeInTheDocument();
    expect(screen.queryByText(/Work authorization affects/)).not.toBeInTheDocument();
  });

  it("resolves a query into the draft and surfaces the next one", async () => {
    render(<App />);
    await userEvent.type(screen.getByPlaceholderText(/your answer/i), "NYC or remote");
    await userEvent.click(screen.getByRole("button", { name: /^answer$/i }));
    expect(await screen.findByText(/Work authorization affects/)).toBeInTheDocument();
    expect(screen.getByText("NYC or remote")).toBeInTheDocument();
  });

  it("offers Review thesis only when all queries are answered", async () => {
    render(<App />);
    expect(screen.queryByRole("button", { name: /review thesis/i })).not.toBeInTheDocument();
    for (const answer of ["NYC or remote", "no sponsorship needed"]) {
      await userEvent.type(screen.getByPlaceholderText(/your answer/i), answer);
      await userEvent.click(screen.getByRole("button", { name: /^answer$/i }));
    }
    await userEvent.click(await screen.findByRole("button", { name: /review thesis/i }));
    expect(useApp.getState().stage).toBe("awaiting_confirmation");
  });
});

describe("thesis confirmation", () => {
  beforeEach(async () => {
    await seedDraft();
    useApp.setState({ stage: "awaiting_confirmation" });
  });

  it("states known gaps in prose and confirms into an immutable version", async () => {
    render(<App />);
    expect(screen.getByText(/Work authorization unstated/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /confirm thesis/i }));
    await screen.findByText(/Companies/);
    expect(useApp.getState().profileVersion).toBe(1);
    expect(useApp.getState().stage).toBe("watchlist");
    expect(useApp.getState().confirmedStages).toEqual(
      expect.arrayContaining(["profile_draft", "awaiting_confirmation"]),
    );
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd companion && npx vitest run test/profile.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement EditorQuery.tsx**

```tsx
import { useState } from "react";
import type { ProfileQuestion } from "../domain";

export function EditorQuery({ question, onAnswer }:
  { question: ProfileQuestion; onAnswer: (answer: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <aside className="query">
      <p className="query-reason">{question.reason}</p>
      <p className="serif">{question.prompt}</p>
      <input className="text-input" placeholder="your answer" value={value}
        onChange={(e) => setValue(e.target.value)} />
      <p><button className="pill" onClick={() => value.trim() && onAnswer(value)}>Answer</button></p>
    </aside>
  );
}
```

- [ ] **Step 4: Implement ProfileDraft.tsx**

```tsx
import { useApi } from "../App";
import { EditorQuery } from "../components/EditorQuery";
import { EvidenceBlock } from "../components/EvidenceBlock";
import { useApp } from "../store";

const SECTION_TITLES: Record<string, string> = {
  roleShapes: "Target role shapes",
  hardConstraints: "Hard constraints",
  preferredWork: "Preferred work",
  excludedWork: "Excluded work",
};

export function ProfileDraft() {
  const api = useApi();
  const { draft, setDraft, setStage, lockStage } = useApp();
  if (!draft) return null;
  const active = draft.questions.find((q) => q.answer === undefined);

  async function answer(value: string) {
    if (!active) return;
    setDraft(await api.answerQuestion(active.key, value));
  }

  const lists: [keyof typeof SECTION_TITLES, string[]][] = [
    ["roleShapes", draft.roleShapes],
    ["hardConstraints", draft.hardConstraints],
    ["preferredWork", draft.preferredWork],
    ["excludedWork", draft.excludedWork],
  ];

  return (
    <div>
      <h2>Profile draft</h2>
      {lists.map(([key, items]) => (
        <section key={key} className="section">
          <h3>{SECTION_TITLES[key]}</h3>
          <ul className="serif">{items.map((x) => <li key={x}>{x}</li>)}</ul>
          {active?.anchorSection === key && <EditorQuery question={active} onAnswer={answer} />}
        </section>
      ))}
      <section className="section">
        <h3>Evidence</h3>
        {draft.evidence.map((e) => <EvidenceBlock key={e.evidenceId} item={e} />)}
      </section>
      {!active && (
        <button className="pill pill-active"
          onClick={() => { lockStage("profile_draft"); setStage("awaiting_confirmation"); }}>
          Review thesis
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Implement ThesisConfirm.tsx**

```tsx
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { useApp } from "../store";

export function ThesisConfirm() {
  const api = useApi();
  const { draft, setStage, lockStage, setProfileVersion } = useApp();
  if (!draft) return null;

  async function confirm() {
    const { version } = await api.confirmThesis();
    setProfileVersion(version);
    lockStage("profile_draft");
    lockStage("awaiting_confirmation");
    setStage("watchlist");
  }

  return (
    <div>
      <h2>Your thesis</h2>
      <p className="serif">{draft.employerThesis}</p>
      <p className="serif">
        Role shapes: {draft.roleShapes.join("; ")}. Hard constraints:{" "}
        {draft.hardConstraints.join("; ")}.
      </p>
      <h3>Known gaps</h3>
      <p className="serif">{draft.knownGaps.join(". ")}.</p>
      <p className="muted">
        Confirming locks this as version 1 of your profile. Editing later starts
        a new version — nothing is rewritten behind you.
      </p>
      <ClayButton onClick={confirm}>Confirm thesis</ClayButton>
    </div>
  );
}
```

- [ ] **Step 6: Register, run, commit**

Add to `SCREENS` in `App.tsx`:

```tsx
import { ProfileDraft } from "./screens/ProfileDraft";
import { ThesisConfirm } from "./screens/ThesisConfirm";
// …
  profile_draft: ProfileDraft,
  awaiting_confirmation: ThesisConfirm,
```

```bash
cd companion && npx vitest run
git add companion/src/components/EditorQuery.tsx companion/src/screens/ProfileDraft.tsx companion/src/screens/ThesisConfirm.tsx companion/src/App.tsx companion/test/profile.test.tsx
git commit -m "feat(companion): profile draft with editor's queries and thesis confirmation"
```

Expected: all suites PASS.

---

### Task 7: Company confirmation — tier sections

**Files:**
- Create: `companion/src/screens/CompanyConfirm.tsx`
- Modify: `companion/src/App.tsx` (register)
- Test: `companion/test/companies.test.tsx`

**Interfaces:**
- Consumes: `api.getCompanies/addCompany/approveCompanies`, `ConstraintChip` (pending chip = `status="unknown"`), `ClayButton`.
- Produces: `CompanyConfirm` — three tier sections with counts, serif tier rationale, ✕ remove (toggles `removed`, freely undoable — a removed row renders faded with an "undo" pill), add-URL row, "N active · M pending" counter, clay approve advancing to `discovering`.

- [ ] **Step 1: Write the failing tests**

`companion/test/companies.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../src/App";
import { useApp } from "../src/store";

beforeEach(() => {
  useApp.setState({
    stage: "watchlist", companies: [], discovery: [],
    confirmedStages: ["upload", "profile_draft", "awaiting_confirmation"],
  });
});

describe("company confirmation", () => {
  it("renders three tier sections with counts and reasons", async () => {
    render(<App />);
    expect(await screen.findByText(/^Core/)).toBeInTheDocument();
    expect(screen.getByText(/^Adjacent/)).toBeInTheDocument();
    expect(screen.getByText(/^Exploratory/)).toBeInTheDocument();
    expect(screen.getByText(/MCP \+ RAG explicitly/)).toBeInTheDocument();
  });

  it("marks unverified companies pending and excludes them from the active count", async () => {
    render(<App />);
    const row = (await screen.findByText("Norm Ai")).closest(".ledger-row")!;
    expect(within(row as HTMLElement).getByText(/verifying/)).toHaveClass("chip-unknown");
    expect(screen.getByText(/5 active · 1 pending/)).toBeInTheDocument();
  });

  it("remove is undoable and adjusts the approve count", async () => {
    render(<App />);
    const row = (await screen.findByText("Notion")).closest(".ledger-row")!;
    await userEvent.click(within(row as HTMLElement).getByRole("button", { name: "✕" }));
    expect(screen.getByText(/approve 4 companies/i)).toBeInTheDocument();
    await userEvent.click(within(row as HTMLElement).getByRole("button", { name: /undo/i }));
    expect(screen.getByText(/approve 5 companies/i)).toBeInTheDocument();
  });

  it("adding a URL appends a pending row", async () => {
    render(<App />);
    await screen.findByText("Hebbia");
    await userEvent.type(screen.getByPlaceholderText(/careers url/i), "https://ramp.com/careers");
    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    const row = (await screen.findByText("ramp")).closest(".ledger-row")!;
    expect(within(row as HTMLElement).getByText(/verifying/)).toBeInTheDocument();
  });

  it("approval advances to discovering", async () => {
    render(<App />);
    await screen.findByText("Hebbia");
    await userEvent.click(screen.getByRole("button", { name: /approve 5 companies/i }));
    expect(useApp.getState().stage).toBe("discovering");
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd companion && npx vitest run test/companies.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement CompanyConfirm.tsx**

```tsx
import { useEffect, useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";
import { ConstraintChip } from "../components/ConstraintChip";
import { useApp } from "../store";
import type { CompanyRec } from "../domain";

const TIERS: { key: CompanyRec["tier"]; title: string; sub: string }[] = [
  { key: "core", title: "Core", sub: "Strongest fit to your role shapes and evidence." },
  { key: "adjacent", title: "Adjacent", sub: "Credible paths with one meaningful trade-off each." },
  { key: "exploratory", title: "Exploratory", sub: "Plausible, less certain — kept small on purpose." },
];

export function CompanyConfirm() {
  const api = useApi();
  const { companies, setCompanies, setStage, lockStage } = useApp();
  const [url, setUrl] = useState("");

  useEffect(() => {
    if (companies.length === 0) api.getCompanies().then(setCompanies);
  }, []);

  const active = companies.filter((c) => !c.removed && !c.pending);
  const pending = companies.filter((c) => !c.removed && c.pending);

  function toggle(name: string) {
    setCompanies(companies.map((c) => (c.name === name ? { ...c, removed: !c.removed } : c)));
  }

  async function add() {
    if (!url.trim()) return;
    setCompanies([...companies, await api.addCompany(url)]);
    setUrl("");
  }

  async function approve() {
    await api.approveCompanies(active.map((c) => c.name));
    lockStage("watchlist");
    setStage("discovering");
  }

  return (
    <div>
      <h2>Companies</h2>
      {TIERS.map(({ key, title, sub }) => {
        const rows = companies.filter((c) => c.tier === key);
        const kept = rows.filter((c) => !c.removed);
        return (
          <section key={key}>
            <h3 className="tier-heading">{title} <span className="muted">· {kept.length} of {rows.length}</span></h3>
            <p className="tier-sub">{sub}</p>
            {rows.map((c) => (
              <div key={c.name} className={`ledger-row ${c.removed ? "row-fade" : ""}`}>
                <div>
                  <strong>{c.name}</strong>{" "}
                  {c.pending && <ConstraintChip status="unknown" label="verifying…" />}
                  <div className="row-meta serif">{c.reason}</div>
                </div>
                {c.removed
                  ? <button className="pill" onClick={() => toggle(c.name)}>undo</button>
                  : <button className="remove-x" aria-label="✕" onClick={() => toggle(c.name)}>✕</button>}
              </div>
            ))}
          </section>
        );
      })}
      <div className="ledger-row">
        <input className="text-input" placeholder="Add a company careers URL…"
          value={url} onChange={(e) => setUrl(e.target.value)} />
        <button className="pill" onClick={add}>Add</button>
      </div>
      <p className="muted">{active.length} active · {pending.length} pending</p>
      <ClayButton onClick={approve}>Approve {active.length} companies →</ClayButton>
    </div>
  );
}
```

- [ ] **Step 4: Register, run, commit**

Add to `SCREENS`: `watchlist: CompanyConfirm`.

```bash
cd companion && npx vitest run
git add companion/src/screens/CompanyConfirm.tsx companion/src/App.tsx companion/test/companies.test.tsx
git commit -m "feat(companion): three-tier company confirmation with pending verification"
```

Expected: all suites PASS.

---

### Task 8: Discovery fill-in, shortlist, account — and the full gate

**Files:**
- Create: `companion/src/screens/Shortlist.tsx`, `companion/src/screens/Account.tsx`
- Modify: `companion/src/App.tsx` (register `discovering` and `ready` → `Shortlist`; account menu link)
- Modify: repo root `README.md`
- Test: `companion/test/shortlist.test.tsx`, `companion/test/account.test.tsx`

**Interfaces:**
- Consumes: `subscribeDiscovery`, `getShortlist`, `sendFeedback`, `deleteAccount`, all primitives, `overallStatus`.
- Produces: `Shortlist` renders BOTH stages — while `stage === "discovering"` it shows the fill-in ledger (subscribing on mount, unsubscribing on unmount); when discovery reports done it loads the shortlist, advances stage to `ready`, and renders the ranked ledger with one-open-row expansion. `Account` renders the deletion screen (typed confirm).

- [ ] **Step 1: Write the failing tests**

`companion/test/shortlist.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { ApiContext } from "../src/App";
import { App } from "../src/App";
import { makeFakeApi } from "../src/fakeApi";
import { useApp } from "../src/store";

function renderWith(api = makeFakeApi()) {
  return render(<ApiContext.Provider value={api}><App /></ApiContext.Provider>);
}

beforeEach(() => {
  useApp.setState({
    stage: "discovering", discovery: [], shortlist: [], emptyReason: null,
    confirmedStages: ["upload", "profile_draft", "awaiting_confirmation", "watchlist"],
  });
});

describe("discovery fill-in", () => {
  it("keeps a failed company visible with its reason, then shows ranked results", async () => {
    renderWith(makeFakeApi({ failCompany: "Norm Ai" }));
    expect(await screen.findByText(/source error: board unreachable/)).toBeInTheDocument();
    expect(await screen.findByText("Senior Developer, AI Software Engineer")).toBeInTheDocument();
    expect(useApp.getState().stage).toBe("ready");
    // the failed source stays visible above the results
    expect(screen.getByText(/source error: board unreachable/)).toBeInTheDocument();
  });

  it("explains an empty shortlist", async () => {
    renderWith(makeFakeApi({ emptyShortlist: true }));
    expect(await screen.findByText(/No postings matched/)).toBeInTheDocument();
  });
});

describe("shortlist ledger", () => {
  it("opens one row at a time with evidence, unknowns, and only three actions", async () => {
    renderWith();
    const title = await screen.findByText("Senior Developer, AI Software Engineer");
    await userEvent.click(title);
    const open = title.closest(".ledger-item")!;
    expect(within(open as HTMLElement).getByText(/Built 12-agent runtime/)).toBeInTheDocument();
    expect(within(open as HTMLElement).getByText(/Not stated in posting/)).toBeInTheDocument();
    expect(within(open as HTMLElement).getByRole("link", { name: /open original/i }))
      .toHaveAttribute("href", "https://jobs.workable.com/view/nb-1");
    // second click on another row closes the first
    await userEvent.click(screen.getByText("Principal Engineer, GenAI Team"));
    expect(screen.queryByText(/Built 12-agent runtime/)).not.toBeInTheDocument();
  });

  it("records feedback on the open row", async () => {
    const api = makeFakeApi();
    const spy = vi.spyOn(api, "sendFeedback");
    renderWith(api);
    await userEvent.click(await screen.findByText("Senior Developer, AI Software Engineer"));
    await userEvent.click(screen.getByRole("button", { name: "Useful" }));
    expect(spy).toHaveBeenCalledWith("https://jobs.workable.com/view/nb-1", "useful");
  });
});
```

Add `import { vi } from "vitest";` to the imports.

`companion/test/account.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Account } from "../src/screens/Account";

describe("deletion", () => {
  it("requires the typed word before enabling, then reports done", async () => {
    render(<Account />);
    expect(screen.getByText(/permanently removes your résumé/i)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /delete everything/i });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText(/type delete/i), "delete");
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    expect(await screen.findByText(/deleted\. nothing of yours remains/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
cd companion && npx vitest run test/shortlist.test.tsx test/account.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement Shortlist.tsx**

```tsx
import { useEffect, useState } from "react";
import { useApi } from "../App";
import { ConstraintChip } from "../components/ConstraintChip";
import { EvidenceBlock } from "../components/EvidenceBlock";
import { FeedbackPills } from "../components/FeedbackPills";
import { overallStatus } from "../domain";
import { useApp } from "../store";

export function Shortlist() {
  const api = useApi();
  const { stage, discovery, setDiscovery, shortlist, setShortlist,
    emptyReason, setEmptyReason, setStage, lockStage } = useApp();
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    if (stage !== "discovering") return;
    const unsub = api.subscribeDiscovery(async (rows, done) => {
      setDiscovery(rows);
      if (done) {
        const res = await api.getShortlist();
        setShortlist(res.items);
        setEmptyReason(res.emptyReason ?? null);
        lockStage("discovering");
        setStage("ready");
      }
    });
    return unsub;
  }, [stage]);

  const failures = discovery.filter((r) => r.state === "source_error");

  return (
    <div>
      <h2>Shortlist</h2>
      {stage === "discovering" && (
        <div>
          {discovery.map((r) => (
            <div key={r.company} className={`ledger-row ${r.state === "assessed" ? "" : "row-fade"}`}>
              <strong>{r.company}</strong>
              <span className={`row-meta ${r.state === "source_error" ? "inline-error" : ""}`}>{r.detail}</span>
            </div>
          ))}
        </div>
      )}
      {stage === "ready" && (
        <div>
          {failures.map((r) => (
            <div key={r.company} className="ledger-row row-fade">
              <strong>{r.company}</strong>
              <span className="row-meta inline-error">{r.detail}</span>
            </div>
          ))}
          {emptyReason && <p className="serif">{emptyReason}</p>}
          {shortlist.map((item) => {
            const isOpen = open === item.postingUrl;
            return (
              <div key={item.postingUrl} className="ledger-item">
                <div className="ledger-row" onClick={() => setOpen(isOpen ? null : item.postingUrl)}>
                  <div>
                    <strong>{item.title}</strong>
                    <div className="row-meta">
                      {item.company} · {item.location} · {item.freshness} · {item.source}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <span className={`row-score ${isOpen ? "row-score-open" : ""}`}>{item.score}</span>
                    <div className="row-meta">constraints: {overallStatus(item.constraintResults)}</div>
                  </div>
                </div>
                {isOpen && (
                  <div className="ledger-open">
                    <h3>Why this fits</h3>
                    <p className="serif">{item.whyFit}</p>
                    {item.evidence.map((e) => <EvidenceBlock key={e.evidenceId} item={e} />)}
                    <h3>Trade-offs &amp; unknowns</h3>
                    <p className="serif">{item.tradeoffs.join(" ")}</p>
                    <p>
                      {item.constraintResults.filter((c) => c.status !== "pass").map((c) => (
                        <ConstraintChip key={c.constraint} status={c.status}
                          label={`${c.constraint}: ${c.explanation}`} />
                      ))}
                      {item.uncertainties.map((u) => (
                        <ConstraintChip key={u} status="unknown" label={u} />
                      ))}
                    </p>
                    <p>
                      <FeedbackPills value={item.feedback}
                        onChange={async (v) => {
                          await api.sendFeedback(item.postingUrl, v);
                          setShortlist(shortlist.map((s) =>
                            s.postingUrl === item.postingUrl ? { ...s, feedback: v } : s));
                        }} />
                      <a className="row-meta" style={{ color: "var(--accent)", float: "right" }}
                        href={item.postingUrl} target="_blank" rel="noreferrer">
                        Open original ↗
                      </a>
                    </p>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Implement Account.tsx**

```tsx
import { useState } from "react";
import { useApi } from "../App";
import { ClayButton } from "../components/ClayButton";

export function Account() {
  const api = useApi();
  const [typed, setTyped] = useState("");
  const [state, setState] = useState<"idle" | "done" | "delete_error">("idle");

  async function destroy() {
    const res = await api.deleteAccount();
    setState(res.state);
  }

  if (state === "done") return <p className="serif">Deleted. Nothing of yours remains.</p>;

  return (
    <div>
      <h2>Delete account</h2>
      <p className="serif">
        This permanently removes your résumé-derived profile, evidence, watchlist,
        shortlist, feedback, and account. There is no undo.
      </p>
      <input className="text-input" placeholder="type delete to confirm"
        value={typed} onChange={(e) => setTyped(e.target.value)} />
      <p><ClayButton disabled={typed !== "delete"} onClick={destroy}>Delete everything</ClayButton></p>
      {state === "delete_error" && (
        <p className="inline-error">Deletion did not complete. It is safe to retry — nothing was reported deleted that wasn't.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Register both stages and finish App**

In `SCREENS`: `discovering: Shortlist, ready: Shortlist`. `Account` is not a stage — render it behind a header link: add to `App`'s returned JSX (when `stage !== "front_door"`) a `<button className="pill" onClick={…}>Account</button>` that toggles a local `showAccount` state rendering `<Account />` in place of the stage screen.

```tsx
export function App() {
  const stage = useApp((s) => s.stage);
  const [showAccount, setShowAccount] = useState(false);
  const Screen = SCREENS[stage];
  return (
    <>
      {stage !== "front_door" && <SectionRail />}
      <main className="dossier">
        {stage !== "front_door" && (
          <p style={{ textAlign: "right" }}>
            <button className="pill" onClick={() => setShowAccount(!showAccount)}>Account</button>
          </p>
        )}
        {showAccount ? <Account /> : Screen ? <Screen /> : null}
      </main>
    </>
  );
}
```

(Add the `useState` import and `Account` import to App.tsx.)

- [ ] **Step 6: Root README pointer**

Add to repo root `README.md`, at the end of the "Core boundary" section:

```markdown
The hosted companion's frontend lives in [companion/](companion/) — a separate
app with its own dependencies that imports nothing from this repo's root.
```

- [ ] **Step 7: Full verification gate**

```bash
cd companion && npx vitest run && npm run build
cd .. && .venv/bin/pytest tests/ -q
git diff --check
```

Expected: all companion suites PASS; `tsc`/vite build clean; the Python suite still passes 216; no whitespace errors.

- [ ] **Step 8: Commit**

```bash
git add companion README.md
git commit -m "feat(companion): discovery fill-in ledger, shortlist with in-place assessment, deletion"
```

---

## Plan self-review

- **Spec coverage:** shell/rail (T4), front door + refusal + LinkedIn caption (T5), upload + provider disclosure + parse_error (T5), draft + editor's queries + known-facts-not-reasked (T6, the fake never re-asks answered questions), thesis confirm + versioning copy (T6), three-tier companies + remove/undo + add-URL + pending + counter (T7), fill-in wait + visible source_error + empty-reason + shortlist ledger + one-open-row + three-actions-only + feedback (T8), deletion with typed confirm + retryable error (T8), constraint token (T3, exercised in T7/T8), mobile (rail hides under 900px; single column throughout). Deferred by design, stated in tasks: real OIDC, file drag-and-drop, dark-mode polish beyond tokens, real API client — all child-plan-2/4 work.
- **Placeholders:** none; every step carries complete code or exact commands.
- **Type consistency:** `CompanionApi` method names, `useApp` setter names, `ConstraintChip` props, `overallStatus`, and `SCREENS` registration are used identically across Tasks 2–8.
- **Boundary:** Task 1's test runs in every suite invocation; Task 8's gate re-runs the Python suite to prove the repo root is untouched.
