-- RLS for every hunter8 table. The service role bypasses these by design;
-- companion_api/db.py is the only place that uses it, always user-filtered.
--
-- IMPORTANT: the `hunter8` schema must be added to PostgREST's exposed-schemas
-- config (Supabase dashboard: API Settings -> Exposed schemas), or every
-- client `.schema("hunter8")` call returns PGRST106.
--
-- Exposing it is NOT sufficient on its own. PostgREST keeps a separate schema
-- CACHE, and `notify pgrst, 'reload config'` does not refresh it — the API then
-- answers PGRST205 ("Could not find the table ... in the schema cache") for
-- tables it can genuinely see, with a hint naming the very table you asked for.
-- Verified on the hunter8-spine branch: 5 of 8 live tests failed this way until
-- BOTH notifies were issued. Rollout must run:
--     notify pgrst, 'reload config';
--     notify pgrst, 'reload schema';
alter table hunter8.invites enable row level security;
alter table hunter8.invites force row level security;
alter table hunter8.product_memberships enable row level security;
alter table hunter8.product_memberships force row level security;
alter table hunter8.resume_uploads enable row level security;
alter table hunter8.resume_uploads force row level security;
alter table hunter8.profile_drafts enable row level security;
alter table hunter8.profile_drafts force row level security;
alter table hunter8.profile_questions enable row level security;
alter table hunter8.profile_questions force row level security;
alter table hunter8.confirmed_profiles enable row level security;
alter table hunter8.confirmed_profiles force row level security;
alter table hunter8.company_theses enable row level security;
alter table hunter8.company_theses force row level security;
alter table hunter8.watched_companies enable row level security;
alter table hunter8.watched_companies force row level security;
alter table hunter8.job_postings enable row level security;
alter table hunter8.job_postings force row level security;
alter table hunter8.match_assessments enable row level security;
alter table hunter8.match_assessments force row level security;
alter table hunter8.shortlist_feedback enable row level security;
alter table hunter8.shortlist_feedback force row level security;
alter table hunter8.pipeline_runs enable row level security;
alter table hunter8.pipeline_runs force row level security;
alter table hunter8.deletion_requests enable row level security;
alter table hunter8.deletion_requests force row level security;

-- Invites carry no user data and are never client-readable: redemption goes
-- through the service role after the email is verified. No policy = deny all.

-- Clients are read-only by design: `authenticated` is a shared role across
-- delapan and hunter8 in this Supabase project, so a delapan user with no
-- hunter8 invite still holds `authenticated` and could reach these tables
-- through PostgREST directly. Every hunter8 write goes through the service
-- role (companion_api/db.py), which is invite-gated in FastAPI before it
-- ever touches Postgres. Because these policies grant select only (and the
-- schema-level grant below is select-only too), a user with no invite has no
-- write path even if they reach PostgREST directly.
create policy h8_membership_self on hunter8.product_memberships
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_uploads_self on hunter8.resume_uploads
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_drafts_self on hunter8.profile_drafts
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_questions_self on hunter8.profile_questions
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_profiles_self on hunter8.confirmed_profiles
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_theses_self on hunter8.company_theses
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_companies_self on hunter8.watched_companies
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_assessments_self on hunter8.match_assessments
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_feedback_self on hunter8.shortlist_feedback
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_runs_self on hunter8.pipeline_runs
  for select to authenticated using ((select auth.uid()) = user_id);

create policy h8_deletions_self on hunter8.deletion_requests
  for select to authenticated using ((select auth.uid()) = user_id);

-- Shared posting data is readable only where the caller owns an assessment of
-- it. Writes are service-role only (the discovery pipeline), so no write policy.
create policy h8_postings_via_own_assessment on hunter8.job_postings
  for select to authenticated using (
    exists (
      select 1 from hunter8.match_assessments a
      where a.posting_url = hunter8.job_postings.url
        and a.user_id = (select auth.uid())
    )
  );

grant usage on schema hunter8 to authenticated;
grant select on all tables in schema hunter8 to authenticated;

-- BYPASSRLS bypasses policies, not privileges, and Supabase's automatic
-- grants don't cover custom schemas. Without these, service_role reads and
-- writes to hunter8 fail on privilege checks even though RLS is bypassed.
grant usage on schema hunter8 to service_role;
grant all on all tables in schema hunter8 to service_role;

-- `alter default privileges` only affects objects created AFTER this point,
-- and it fires at `create table` time -- BEFORE any RLS-enable statement.
-- Every future migration that adds a hunter8 table must enable (and force)
-- RLS in the same transaction as the create, or the table is briefly
-- reachable under these default grants with RLS off.
alter default privileges in schema hunter8 grant select on tables to authenticated;
alter default privileges in schema hunter8 grant all on tables to service_role;
