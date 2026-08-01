# Hosted Companion POC — Design

**Date:** 2026-08-01  
**Status:** Approved design, pending written-spec review  
**Vision goals served:** End Goal 5 (prove the transferable product thesis
without productizing the personal runtime), while preserving End Goal 3
(profile-grounded grading) and every privacy and human-control invariant.

## Summary

Build an invite-only hosted companion at `hunter8.delapan.ai`. It turns a
user-provided résumé and a short human-in-the-loop interview into one confirmed
career-search thesis, derives a focused employer watchlist from that thesis, and
returns an evidence-ranked shortlist of live jobs.

The companion is a separate product boundary. It reuses delapan's identity and
private knowledge primitives and a new provider-neutral `hunter8-core`, but it
does not import hunter8's personal files, SQLite database, tracker, résumé
builder, local model adapters, or application automation.

The POC ends at the shortlist. It never submits an application or contacts an
employer.

## Locked decisions

| Decision | Choice |
|---|---|
| Product boundary | Separate hosted companion; local hunter8 remains personal |
| Temporary host | `hunter8.delapan.ai` |
| Audience | Invite-only testers across professions |
| Authentication | Passwordless email or LinkedIn OIDC |
| LinkedIn data | Identity prefill only; never scrape or assume résumé access |
| Profile source | Explicit PDF/DOCX résumé upload, with plain-text fallback |
| Career direction | Hybrid HITL: inferred draft plus high-impact questions |
| Active searches | One confirmed career thesis per user |
| Company universe | KB-derived, user-editable, normally 25–40 companies |
| Output | Evidence-ranked shortlist with visible uncertainty |
| Feedback | Useful / not useful; never silently rewrites the profile |
| Application behavior | None |
| POC success | Five testers; each marks at least three results useful |

## Scope

The first production POC includes:

1. Invite-gated email and LinkedIn sign-in.
2. Private résumé upload and server-side text extraction.
3. Structured `ProfileDraft` generation with source spans and confidence.
4. Adaptive questions for high-impact ambiguity.
5. Explicit confirmation of one `ConfirmedProfile`.
6. A KB-derived `CompanyThesis` and editable 25–40-company watchlist.
7. ATS discovery from approved companies.
8. Constraints-first, evidence-grounded job assessment.
9. A shortlist with why-fit, supporting evidence, trade-offs, uncertainty, and
   links to original postings.
10. Useful / not-useful feedback.
11. One-action deletion of source and derived user data.

## Non-goals

- Application submission, autofill, outreach, referrals, or employer contact.
- A general job-board index or mass-application product.
- A résumé-writing suite.
- Multiple simultaneous career tracks.
- Automatic profile or thesis mutation from click feedback.
- Scraping LinkedIn profiles.
- Sharing Anthony's profile, watchlist, grading brief, or application history.
- Supporting every ATS before the five-tester POC is validated.

## User journey

### 1. Enter

An invited user signs in through a passwordless email link or LinkedIn OIDC.
LinkedIn may prefill basic identity fields only. Access is denied before any
profile or storage resource is created if the identity is not invited.

An administrator issues a single-use invite token bound to an email address.
Email sign-in must match that address. LinkedIn sign-in must return the same
verified email or be linked through the still-valid invite token. Public signup
followed by an allowlist check is insufficient because it creates an account
before access is established.

### 2. Upload and extract

The user uploads a PDF or DOCX résumé. The server:

1. validates type and size;
2. extracts text in an isolated parser without sending the raw file to a model;
3. creates structured evidence with source spans;
4. asks the configured model for a schema-constrained `ProfileDraft`; and
5. records confidence and missing fields rather than filling gaps by guess.

If extraction fails, no partial KB is promoted. The user may retry or paste
plain text.

### 3. Resolve career direction

The question planner asks only when an answer materially affects constraints,
ranking, or company selection. Typical topics are:

- target role shape and seniority;
- location, remote preference, and work authorization;
- compensation and work-style constraints;
- industries and explicit anti-goals; and
- conflicting plausible career directions.

The UI explains why each question appeared. Known facts are editable defaults,
not repeated questions.

### 4. Confirm one thesis

The user reviews a single summary containing:

- target role shapes;
- hard constraints;
- preferred and excluded work;
- evidence inventory;
- known gaps and uncertainty; and
- employer thesis.

Discovery cannot begin until the user confirms it. Confirmation produces an
immutable version of `ConfirmedProfile`; later edits create a new version.

### 5. Confirm companies

The system derives a recommended employer set from the confirmed profile:

- **Core:** strongest role-shape and evidence fit;
- **Adjacent:** credible paths with a meaningful trade-off; and
- **Exploratory:** plausible but less certain.

The normal target is 25–40 companies. Every recommendation includes a reason
linked to profile evidence. The user may remove companies or add a company
careers URL before approving the watchlist.

Recommendation is a bounded two-step process:

1. the model proposes company candidates from the confirmed profile and
   employer thesis; then
2. the system validates each candidate against an official careers page or
   recognized public ATS endpoint.

Unverified companies may appear only as explicitly pending suggestions and do
not count toward active watchlist coverage.

### 6. Review shortlist

Each result shows:

- company, role, location, freshness, and source;
- overall fit and constraint status;
- why the role fits;
- the user's supporting evidence;
- trade-offs, red flags, and unknowns; and
- the original posting link.

The only actions are open original, useful, and not useful. Feedback is product
evaluation data. After a pattern emerges, the system may propose a thesis
change, but the user must approve it before rankings change.

## Architecture

### Hosted companion frontend

A separate Vercel application owns `hunter8.delapan.ai`. It contains:

- authentication callbacks;
- résumé upload;
- the profile draft and adaptive interview;
- thesis and company confirmation;
- shortlist and feedback; and
- deletion controls.

It may reuse delapan UI primitives and Supabase session handling, but it has its
own deployment, environment configuration, navigation, and API client.

### Hosted companion API

A separate Fly service owns product orchestration:

- invite and product-membership checks;
- résumé parsing;
- profile-draft generation;
- adaptive-question planning;
- confirmed-profile versioning;
- company-thesis generation;
- ATS discovery;
- hosted assessment and ranking;
- feedback recording; and
- deletion coordination.

Long-running discovery and ranking execute as resumable jobs, not as one browser
request. Each stage records status and error reason.

### Hosted model path

The POC uses delapan's existing AI Gateway integration as its single configured
model path for profile extraction, question planning, company recommendation,
and assessment. Model names are deployment configuration, not domain logic.
Raw files never leave the parser; only extracted text is sent after the upload
screen names the configured provider. A bounded per-run budget prevents
uncontrolled fan-out. No direct Anthropic/OpenAI fallback is permitted.

### Shared Supabase, dedicated product scope

The POC reuses the delapan Supabase project's authentication and private KB
primitives. It receives dedicated:

- hunter8 product-membership and domain tables;
- private résumé bucket and object namespace;
- row-level-security policies based on `auth.uid()`;
- product-scoped API authorization;
- service-role helpers with mandatory user filters; and
- deletion records.

A separate hostname is not a security boundary. The API must validate both the
authenticated user and hunter8 product membership. Generic delapan membership
alone is insufficient.

### `hunter8-core`

Extract a small provider-neutral Python package. It owns domain types and
interfaces, not infrastructure:

```text
JobPosting
ProfileDraft
ConfirmedProfile
CompanyThesis
WatchedCompany
MatchAssessment
RankedMatch
```

```text
ResumeToProfile.extract(document_text) -> ProfileDraft
QuestionPlanner.plan(ProfileDraft) -> questions
CompanyRecommender.recommend(ConfirmedProfile) -> CompanyThesis
CompanySource.fetch(SourceConfig) -> JobPosting[]
EvidenceRanker.assess(ConfirmedProfile, JobPosting) -> MatchAssessment
ShortlistRanker.order(MatchAssessment[]) -> RankedMatch[]
```

The hosted service supplies model, persistence, queue, and source adapters.
Local hunter8 may import the types and ranking contracts while retaining
SQLite, YAML, Ollama, Claude CLI, Excel, and Playwright.

### Local-only boundary

The hosted product never imports or reads:

- `intent.md`, `rubric.md`, `brief.md`, or personal KB identifiers;
- `hunter8.db`;
- `watchlist.yaml`;
- `ML-AI-Roles-Tracker.xlsx`;
- `resumes/`;
- `sync_intent.py`;
- `triage.py`, `tracker.py`, `apply.py`, or `handlers/`; or
- local Claude CLI and Ollama adapters.

## Conceptual data model

All user-specific rows have a direct owner or an ownership path that terminates
at `auth.uid()`. Public `job_postings` are the only shared domain records; RLS
exposes them only through a user's owned assessments and approved watchlist.

- `product_memberships`: invite and access state.
- `resume_uploads`: temporary object metadata and parser state.
- `profile_drafts`: extracted structured fields, confidence, source spans.
- `profile_questions`: question, reason, answer, and resolution state.
- `confirmed_profiles`: immutable versioned search theses.
- `company_theses`: generated employer rationale for a profile version.
- `watched_companies`: approved company, careers URL, source adapter, tier.
- `job_postings`: normalized public posting data, deduplicated independently of
  users.
- `match_assessments`: user/profile-version-specific assessment of a posting.
- `shortlist_feedback`: useful / not useful plus optional reason.
- `pipeline_runs`: stage status, counters, and non-PII error details.
- `deletion_requests`: idempotent deletion status and completion timestamps.

`job_postings` and `match_assessments` are separate because one public job may
be assessed differently for many profiles.

## Knowledge representation

Each user receives a private product-linked KB. Résumé-derived profile evidence
uses a private source type rather than a fake public URL. A finding records:

- one checkable claim;
- category;
- résumé source span or explicit user-answer provenance;
- confidence;
- profile version; and
- confirmation state.

Only confirmed evidence participates in ranking. Generated career hypotheses
remain draft data until accepted.

After the raw résumé is deleted, citations retain only the minimum normalized
excerpt needed to support a claim, its page/section locator, and a document
content hash. They do not retain the complete extracted document.

## Discovery

The initial required source adapters are Greenhouse, Ashby, and Lever. For a
proposed company, discovery starts from its official careers URL, detects known
ATS links, derives a small deterministic set of slug candidates, and verifies
each candidate by probing the provider's public endpoint. A slug is stored only
after a successful response attributable to that company.

Existing Workday and Eightfold adapters may be enabled only after they pass the
same hosted contract and safety tests. Unsupported sites remain visibly
pending. Tavily may locate an official careers page, but its search results do
not become job postings and the POC does not silently replace unsupported
boards with unattributed web-search rows.

Source behavior:

- one company failure does not stop the run;
- failures persist as `source_error`;
- exact and canonical URL deduplication is applied;
- the source and fetch timestamp remain attached; and
- stale or missing descriptions are visible assessment limitations.

## Ranking contract

Ranking evaluates, in order:

1. explicit hard constraints;
2. target role-shape fit;
3. strength of supporting profile evidence;
4. company-thesis alignment;
5. posting freshness and completeness; and
6. visible uncertainty.

Unknown is not silently treated as pass or fail. A `MatchAssessment` contains
structured constraint results, score, explanation, evidence references, trade-
offs, uncertainty, provider/model provenance, and profile version.

Model output is schema-validated. Scores are bounded, enums are enforced, and
malformed output becomes `assessment_error`. The service may retry within a
fixed budget but never falls back to an unconfigured provider.

## Privacy and data lifecycle

### Résumé retention

The raw résumé exists only while the profile is being extracted and confirmed.
After confirmation, the system deletes the original object and retains only
structured evidence and minimal source excerpts needed for explanations.
Reprocessing requires re-upload.

Editing a confirmed thesis creates a new immutable profile version. Watchlists,
assessments, and feedback remain linked to the version that produced them. A
new version requires a new company confirmation and ranking run; historical
results are never silently reinterpreted.

### Provider disclosure

Before upload, the UI names every configured provider that may receive
extracted résumé text. Raw files are not sent when extracted text is sufficient.
No telemetry receives résumé text, profile content, prompts, or model outputs.

### Deletion

One action:

1. marks the account `delete_pending`;
2. deletes private Storage objects and parser artifacts;
3. deletes findings, embeddings, graph data, profiles, theses, assessments,
   shortlist feedback, and run data;
4. deletes product membership;
5. deletes the Auth user last; and
6. retains only a PII-free deletion outcome.

Deletion is idempotent. Partial failure remains visible and retryable; it is
never reported complete early. Supabase requires owned Storage objects to be
removed before deleting an Auth user, and public-table cascades must be defined
explicitly ([Supabase user-data management](https://github.com/supabase/supabase/blob/master/apps/docs/content/guides/auth/managing-user-data.mdx)).

## Authentication

- Email authentication is passwordless.
- LinkedIn uses Supabase's LinkedIn OIDC provider.
- OAuth state and redirect validation are mandatory.
- Allowed redirect URLs include only approved preview and production origins.
- LinkedIn OIDC supplies identity claims, not a résumé.
- Elevated LinkedIn profile APIs are not required for the POC.

LinkedIn's self-service OIDC scopes expose basic identity fields; full work
history is not a standard sign-in claim
([LinkedIn OIDC](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2)).

## Failure model

Visible pipeline states:

```text
uploaded
profile_draft
awaiting_answers
awaiting_confirmation
watchlist_ready
discovering
ranking
ready
```

Errors are explicit states with reasons:

- `parse_error`;
- `source_error`;
- `assessment_error`;
- `delete_pending`;
- `delete_error`; and
- `system_error`.

Systemic provider or queue failures stop affected work without marking every
item bad. Per-item failures do not stop unrelated work. An empty shortlist says
whether no jobs matched, sources failed, or ranking is incomplete.

## Security

- Enforce invite status before creating product resources.
- Enforce product membership and direct user ownership on every API operation.
- Test live RLS with two real users; fake-database tests are insufficient.
- Keep service-role usage in narrow, user-filtered helpers.
- Use private Storage, size/type limits, malware-safe parsing, and unguessable
  object names.
- Protect user-supplied careers URLs from SSRF and redirect abuse.
- Do not log résumé text, profile data, authorization headers, prompts, or model
  responses.
- Rate-limit by verified JWT subject, not only IP.
- Isolate preview and production secrets and callback origins.

## Observability

Collect only operational metadata:

- stage duration and completion;
- source success/failure counts;
- postings discovered and assessed;
- model/provider latency, tokens, and cost;
- shortlist usefulness counts; and
- deletion completion.

User-visible status and internal operations use the same persisted run state.
Operational events contain identifiers and counters, not profile content.

## Testing

### Unit

- résumé extraction schemas and source spans;
- confidence thresholds and question selection;
- profile version transitions;
- company-tier generation;
- constraints-first assessment;
- score and enum validation;
- evidence-reference integrity; and
- idempotent deletion planning.

### Adapter contracts

Greenhouse, Ashby, and Lever fixtures must normalize to the same `JobPosting`.
Malformed rows, missing dates, pagination, canonical deduplication, and
per-company failure isolation are covered.

### Integration

- email and LinkedIn callback flows;
- invite enforcement;
- private upload/read/delete;
- product-scoped API authorization;
- cross-user RLS denial using live Supabase;
- KB bootstrap and profile versioning;
- resumable discovery/ranking jobs; and
- complete source-and-derived-data deletion.

### End-to-end

An invited user can:

1. sign in;
2. upload a résumé;
3. answer only the generated high-impact questions;
4. edit and confirm one thesis;
5. approve a 25–40-company watchlist;
6. receive an evidence-ranked shortlist;
7. mark results useful; and
8. delete the account and all product data.

Local hunter8's existing test suite must continue to pass against the extracted
core.

## Deployment and rollout

1. Deploy separate preview frontend and API environments.
2. Configure dedicated product resources and live isolation tests.
3. Attach `hunter8.delapan.ai` to the production frontend.
4. Add the production origin to API CORS and Supabase Auth redirect allowlists.
5. Invite one tester and verify the full flow plus deletion.
6. Expand one tester at a time until five complete the POC.
7. Review usefulness, coverage, failure, cost, and deletion evidence.
8. Decide whether evidence supports a dedicated domain.

## Delivery decomposition

This umbrella design is too broad for one implementation plan. Deliver it as
five bounded child plans, each with its own verification gate:

1. **Core extraction.** Introduce provider-neutral domain types and adapter
   contracts while keeping local hunter8 behavior and all existing tests green.
2. **Hosted security spine.** Create the separate frontend/API deployments,
   invite binding, product authorization, dedicated tables/bucket/RLS, and
   deletion path. This may proceed in parallel with core extraction.
3. **Profile pipeline.** Add résumé parsing, model-backed `ProfileDraft`,
   adaptive questions, confirmed versioning, and private KB bootstrap.
4. **Company discovery and ranking.** Add company recommendation, official
   careers/ATS verification, source adapters, assessment, shortlist, and
   feedback.
5. **Production rollout.** Complete end-to-end, security, deletion, and live
   isolation tests; attach the subdomain; invite five testers; measure the
   acceptance criteria.

After this umbrella spec is approved, implementation planning begins with child
plan 1, **Core extraction**. Each later child receives a focused plan after its
dependencies pass.

## Acceptance criteria

- The companion is live at `hunter8.delapan.ai`.
- Five invited users complete onboarding and company confirmation.
- Every tester marks at least three shortlist results useful.
- Cross-user access tests fail closed.
- Every deletion test removes raw and derived user data.
- Source and assessment failures are visible.
- The hosted product has no application-submission or employer-contact path.
- Local hunter8 remains independently operable.

## Research context

The market's dominant patterns are résumé/job matching, tracking, autofill, and
volume auto-apply. Jobright presents broad-feed résumé matching and Teal focuses
on résumé management and tracking
([Jobright](https://jobright.ai/),
[Teal extension](https://chromewebstore.google.com/detail/teal-job-search-companion/opafjjlpbiaicbbgifbejoochmmeikep)).
The companion differentiates by using a short HITL process to establish one
confirmed career direction before deriving a focused company universe.

LinkedIn sign-in cannot be treated as résumé import. Standard OIDC returns
identity claims; additional current-job/education access is restricted and is
not a complete résumé
([LinkedIn Profile Details API](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/verified-on-linkedin/api-reference/identity-me)).

Supabase supports LinkedIn OIDC configuration and private Storage policies, but
secure deletion requires explicit Storage cleanup and database cascades
([Supabase LinkedIn auth](https://github.com/supabase/supabase/blob/master/apps/docs/content/guides/auth/social-login/auth-linkedin.mdx),
[Supabase Storage access control](https://github.com/supabase/supabase/blob/master/apps/docs/content/guides/storage/security/access-control.mdx)).

The requested delapan `/explore` persistence step could not run during design
because the delapan MCP server was not registered in the active Cursor session.
The web and repository research above informed this spec; persisting it to the
KB remains an operational follow-up, not an implementation dependency.
