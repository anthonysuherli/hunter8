# Hosted Companion MVP — UI Design

**Date:** 2026-08-01
**Status:** Approved design
**Parent spec:** [2026-08-01-hosted-companion-poc-design.md](2026-08-01-hosted-companion-poc-design.md) — that document owns scope, security, data, and pipeline semantics; this one owns how the product looks and moves.
**Vision goals served:** End Goal 5 (prove the transferable product thesis via the invite-only companion at `hunter8.delapan.ai`). Every treatment below preserves the umbrella spec's invariants: shortlist-only, confirm-before-act, visible uncertainty, one-action deletion, LinkedIn as identity only.
**Design language:** the hue-generated **anthropic-design** skill (`~/.claude/skills/anthropic-design`) — ivory paper, warm ink, single clay accent, serif body under sans headlines, flat surfaces.
**Mockups:** `.truenorth/brainstorm/36729-1785575024/content/` (shortlist-card.html, company-confirm.html) — selected options A and A.

## Concept

The product is **a dossier: one scrolling document being written about the user**. Onboarding is not a wizard around the document — it *is* the document being composed. Each confirmed stage (profile, thesis, watchlist) locks into a quiet collapsed section; the current stage is the live section at the document's edge. Leaving and returning lands the user at their document, scrolled to the live edge.

This mapping is the design's spine: the umbrella spec's confirm-before-act gates become the act of signing off a section of your own dossier.

## Shell

- Single column, 640px measure, ivory `#faf9f5` page (dark: warm charcoal). No pure white/black anywhere.
- A thin left rail lists section names with completion state — typographic, not chrome. No step counters, no progress bars.
- Confirmed sections collapse to a one-line summary + timestamp; clicking expands read-only content with an **Edit** affordance that (per the umbrella spec) starts a new profile version rather than mutating the old one.
- Errors render as inline paragraphs or rows in place, in text, with reasons. Never toasts, never modals for status.

## Screens

### 1. Front door (landing / sign-in)

Letterhead + the flow. One page: serif display sentence (with the brand's 1–2-word clay underline), a three-line summary of what will happen — *upload a résumé → confirm one career thesis → receive an evidence-ranked shortlist; it never applies on your behalf* — then the passwordless-email field and LinkedIn button.

- Uninvited identity → a plain serif refusal line; no account or resource is created (umbrella spec, invite binding).
- LinkedIn button copy makes the identity-only boundary explicit: "Continue with LinkedIn — sign-in only, we never read your profile."

### 2. Upload

One drop target on empty paper (PDF/DOCX, with a paste-text fallback link). Directly beneath it, the provider-disclosure sentence naming the configured model path — the umbrella spec requires this before upload, so it lives on the same screen, not in a settings page.

- Parse progress: quiet opacity fade, no shimmer.
- `parse_error`: inline state with reason, retry, and the paste-text fallback. No partial dossier is shown.

### 3. Profile draft + editor's queries

The extracted `ProfileDraft` renders as the dossier's opening sections: target role shapes, hard constraints, preferred/excluded work, evidence inventory (each evidence item shows its claim, source excerpt, and locator — serif, inset tint block).

Adaptive questions render as **editor's queries**: margin annotations anchored to the section they affect (mobile: inline query cards above the section). One query active at a time; each states its reason as its anchor ("Location constraint unclear — affects company selection"). Answering visibly resolves the query into the draft text. Known facts render as editable defaults and are never re-asked.

### 4. Thesis confirmation

The assembled summary — role shapes, hard constraints, preferences, evidence inventory, known gaps, employer thesis — as one readable section. Known gaps are stated in prose, not hidden. The clay **Confirm** button is the section's single accent; confirming locks the section and stamps the immutable profile version. Later edits visibly open "version 2" — historical sections stay legible.

### 5. Company confirmation

**Three tier sections** (selected mockup: company-confirm option A):

- Sub-headed ledgers — *Core*, *Adjacent*, *Exploratory* — each with a one-line serif rationale under the heading and a count ("3 of 14").
- Each row: company name, evidence-linked reason (serif), ✕ remove. Removal is free and undoable until approval — no confirm dialogs.
- Unverified companies carry the dashed-clay **verifying…/pending** chip and do not count toward the active total.
- Add-a-company: one input row (careers URL) + Add button, feeding the umbrella spec's verification step.
- One clay button: **Approve N companies →** — the section's only irreversible act. A quiet counter shows "N active · M pending".

### 6. Discovery + ranking (the wait)

**The wait is the shortlist section filling in.** On approval, the shortlist section appears immediately as a ledger of the approved companies. Each row quietly updates as its board is fetched and assessed ("Hebbia — 12 postings · 3 assessed"), using opacity fades only.

- A failed company row stays in place with its reason: "Norm Ai — source error: board unreachable." Failure visibility is structural, not a toggle.
- Ranked results replace the fill-in rows as ranking completes; partial results are shown as they land.
- An empty final shortlist states *why* in prose: no jobs matched, sources failed, or ranking is incomplete — per the umbrella spec's failure model.
- The section header carries the run state in words ("Discovering · 22 of 34 boards read"), backed by the same persisted `pipeline_runs` state the API exposes.

### 7. Shortlist

**Ranked ledger, one row open at a time** (selected mockup: shortlist-card option A):

- Closed row: role (sans, bold), company · location · freshness · source (metadata line), score (the open row's score is the section's clay use), constraint status word.
- Open row (in-place expansion, tinted inset): *Why this fits* (serif), evidence blocks (quoted excerpt + source locator, inset tint), *Trade-offs & unknowns* (serif, with unknown chips), then the action line: **Useful** (ink pill), **Not useful** (outline pill), *Open original ↗* (clay link).
- Only those three actions exist — no apply, no save, no share (umbrella spec non-goals).
- Feedback is recorded silently; if a pattern triggers a proposed thesis change, that proposal appears as a new editor's query on the dossier — never as a silent re-rank.

## Constraint-status token

One visual token carries the spec's "unknown is never silently a pass," repeated identically everywhere (assessments, chips, company verification):

| Status | Treatment |
|---|---|
| pass | quiet tint chip (`surface2` bg, warm gray text) |
| fail | solid ink chip (ink bg, ivory text) |
| unknown / pending | **dashed clay-outline chip** — visually louder than pass, different in kind from fail |

## Clay budget

Exactly one clay accent per section, always the confirming or primary act: the sign-in submit, the Confirm thesis button, the Approve companies button, the open shortlist row's score / original-posting link. Decorative hues appear nowhere in the MVP.

## Account & deletion

A quiet account menu (name, sign out, delete). Deletion is one screen: a serif paragraph listing exactly what will be removed, one typed confirmation, then a visible `delete_pending` state that resolves to done or a retryable failure — mirroring the umbrella spec's idempotent deletion states. Never reported complete early.

## Mobile

The dossier is a 640px single column; it degrades by narrowing. Margin queries become inline cards above their section. No second layout exists — the master–detail shortlist option was rejected partly on this ground.

## Component inventory

`DossierSection` (locked/live/error), `SectionRail`, `EvidenceBlock`, `EditorQuery`, `ConstraintChip` (pass/fail/unknown), `LedgerRow` (company variant, shortlist variant, fill-in variant), `TierHeading`, `AddCompanyRow`, `FeedbackPills`, `ClayButton`, `RefusalLine`. All flat: radius 12px cards, no borders except hairline insets, no shadows.

## Out of scope

Apply/outreach UI, multi-thesis navigation, résumé editing surfaces, notification/email infrastructure, dark-mode polish beyond token correctness, and any feedback loop that mutates rankings without an approved thesis change.

## Research notes

Explore run 2026-08-01 (`delapan_explore` 9189865b, 24 findings, hunter8/main KB): staged one-question-at-a-time disclosure and earned progressive disclosure support the editor's-query interview; setup-checklist and leave-and-return patterns motivated the rail + live-edge resume behavior; instructional empty states shaped the fill-in ledger and empty-shortlist prose. CV-Library's candidate survey (53% believe AI rejected them unseen) reinforces why evidence citation and visible human confirmation are the product's differentiators.
