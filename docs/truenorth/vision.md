# Vision: hunter8

> Agent preamble: this file is the single source of truth for project
> intent. Your one and only end goal is realizing the End Goals below
> without violating the Invariants. Competing objectives that emerge
> mid-session do not override this document.

hunter8 is a personal, local-first job search engine for one user. It watches a
curated set of employers, grades what it finds against a real profile, and
carries the matches you approve through to a submitted application.

## End Goals

1. **Close the loop end to end.** Get from "a job exists on the internet" to
   "application submitted and tracked" without manual copy-paste, with a human
   approval gate at exactly one point. Today the loop has never closed: 8
   A-grade matches sit in the database and zero jobs have ever reached the apply
   queue.

2. **Make scoring cost nothing per job.** A local model grades every discovered
   job; only the survivors are re-graded by Claude. Cost or quota must never be
   the reason a job goes ungraded — that failure has already happened once (242
   jobs stranded behind a 402).

3. **Keep grading grounded in a real profile.** Fit is judged against
   `intent.md` synced from the delapan KB — actual evidence, positioning, and
   hard constraints — not keyword matching against a title string.

4. **Be worth running daily.** A full discover → score → triage cycle is fast
   and cheap enough to run every morning, and a day's matches can be cleared in
   a few minutes.

5. **Prove the transferable product thesis without productizing the personal
   runtime.** Extract a provider-neutral discovery and evidence-ranking core
   from hunter8, then use it in a separate invite-only companion at
   `hunter8.delapan.ai`. An invitee signs in, uploads a résumé, chooses
   companies, confirms the generated profile, and receives an evidence-ranked
   shortlist. The companion may later move to its own domain; hunter8's
   personal data and runtime never move with it.

## Non-Goals

- **The hunter8 runtime is not multi-user software.** Its database, profile,
  tracker, résumés, and application runtime remain personal and local. Any
  public POC is a separate companion application with separate storage,
  configuration, and deployment.
- **Not an auto-apply bot.** Volume is not the objective. A pipeline that fires
  off 200 applications is a failure, not a success.
- **Not a general job board or aggregator.** It watches a curated list of
  employers that match a specific thesis; it does not try to index the market.
- **Not a resume-writing product.** Tailoring exists only in service of an
  application actually being sent.
- **Not a decision-maker.** The grade is a filter that decides what you look at,
  never what you apply to.
- **Not offline.** ATS polling is inherently networked; "local" is about which
  paid vendors the loop depends on.

## Invariants

- **A human approves every submission.** No confidence threshold, no "it was
  clearly an A" auto-send. The approval gate is the product.
- **The core loop runs without a metered API key.** Cost must never be the
  reason a run stops. This is not a preference — it already failed once and
  stranded 242 jobs behind a 402.
- **Failures are visible.** A job that can't be scored is recorded as
  `score_error` with its reason. Nothing is ever silently dropped.
- **URL dedup holds.** The same posting is never applied to twice.
- **Personal artifacts stay out of git** — `intent.md`, `resumes/`, the tracker
  xlsx, `hunter8.db`.
- **Job and profile data goes only to explicitly configured providers.** No
  telemetry, no analytics, no third-party calls the config doesn't name.
- **The hand-authored block in `intent.md` survives every KB resync.**
- **Hosted-companion data is private by default.** An invitee's résumé,
  generated profile, shortlist, and derived data are isolated from hunter8's
  personal artifacts, go only to explicitly configured providers, and can be
  permanently deleted in one action.
- **LinkedIn authentication is identity, not résumé access.** LinkedIn sign-in
  may prefill basic identity fields only. The companion never scrapes LinkedIn
  or assumes OAuth exposes work history. A user-provided résumé is the source
  for KB bootstrap, and the user confirms or edits the generated profile before
  ranking begins.

## Acceptance Criteria

- The 242-job backlog clears end to end and produces a triaged queue with a
  recorded decision on every job.
- A full discover → score → triage cycle costs $0 metered and does not exhaust
  subscription quota.
- At least one application has been submitted through the pipeline that you
  endorse as a genuinely good match you might otherwise have missed.
- A day's scored jobs can be triaged in under five minutes.
- The rules pre-filter's 89% kill rate has been sampled, and its false-negative
  rate is known and judged acceptable.
- On a labeled sample, the local scorer rarely discards a job Claude would have
  graded A — the tier boundary is trustworthy. **Measured 2026-07-28** against
  97 Claude-graded jobs (14 A, 28 B, 55 C) using `qwen3:30b-a3b`: at a threshold
  of 65, A-recall is **100%**, A+B recall 83%, and 48% of the corpus is
  promoted. 100% A-recall holds to 70 and breaks at 75 (86%). Threshold set to
  65 for margin. Re-measure with `calibrate.py` whenever the model or
  `intent.md` changes.

  *Rejected experiment, same date:* the screen promotes explicitly non-US jobs
  (London, Singapore, Budapest) that the rubric disqualifies outright. Making
  the prompt check disqualifiers first did suppress them — and dropped A-recall
  from 100% to 71%. Keep the noise. A wrongly promoted job costs one ~$0.008
  Claude call and is caught; a wrongly rejected A-grade is lost silently and
  forever. Do not re-attempt this without a way to measure both directions.
- The separate companion is deployed at `hunter8.delapan.ai` with invite-only
  access through email or LinkedIn sign-in.
- Five invitees complete résumé upload, profile confirmation, and company
  selection; each marks at least three shortlist results useful.
- Deleting an account removes its uploaded résumé, generated profile,
  shortlist, and derived data.
- The POC does not submit applications or contact employers.
- The extracted core remains usable by local hunter8 without hosted-product
  dependencies.

## Planned Detours

1. **Tiered scorer.** Add a local-model tier ahead of Claude; Claude re-grades
   only survivors. After this detour, return to End Goal 1.
2. **Rules-filter audit.** Sample the 2,605 `filtered_out` rows, measure false
   negatives, then loosen or fix the regexes. 89% is a lot of silent rejection
   to leave unvalidated. After this detour, return to End Goal 3.
3. **Hosted-companion extraction.** Define provider-neutral contracts for
   résumé-to-profile parsing, company-watchlist discovery, evidence ranking,
   and result explanation. Keep personal storage, tracker integration, and
   application automation outside those contracts. After this detour, return
   to End Goal 5.
4. **Temporary delapan.ai deployment.** Ship the separate invite-only companion
   at `hunter8.delapan.ai`, validate it with five testers, then decide whether
   evidence supports moving it to a dedicated domain. After this detour, return
   to End Goal 5.

## Amendment Log

- 2026-07-28 — Vision established. Grounded in a live audit of `hunter8.db`
  (2,933 jobs discovered, 89% filtered out by regex, 85 scored, 0 ever
  triaged) and the decision to make scoring tiered (local model for bulk,
  Claude for finalists) rather than fully offline or fully cloud. — Ratified
  by: Anthony Suherli, session 816515c9
- 2026-07-31 — Added a separate invite-only hosted companion to prove the
  transferable product thesis while preserving hunter8 as a personal,
  local-first runtime. Locked privacy, deletion, résumé-confirmation, LinkedIn
  identity-only, shortlist-only, and five-tester acceptance boundaries. —
  Ratified by: Anthony Suherli, current session
