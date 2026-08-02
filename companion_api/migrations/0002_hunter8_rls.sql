-- RLS for every hunter8 table. The service role bypasses these by design;
-- companion_api/db.py is the only place that uses it, always user-filtered.
alter table hunter8.invites enable row level security;
alter table hunter8.product_memberships enable row level security;
alter table hunter8.resume_uploads enable row level security;
alter table hunter8.profile_drafts enable row level security;
alter table hunter8.profile_questions enable row level security;
alter table hunter8.confirmed_profiles enable row level security;
alter table hunter8.company_theses enable row level security;
alter table hunter8.watched_companies enable row level security;
alter table hunter8.job_postings enable row level security;
alter table hunter8.match_assessments enable row level security;
alter table hunter8.shortlist_feedback enable row level security;
alter table hunter8.pipeline_runs enable row level security;
alter table hunter8.deletion_requests enable row level security;

-- Invites carry no user data and are never client-readable: redemption goes
-- through the service role after the email is verified. No policy = deny all.

create policy h8_membership_self on hunter8.product_memberships
  for select using (auth.uid() = user_id);

create policy h8_uploads_self on hunter8.resume_uploads
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_drafts_self on hunter8.profile_drafts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_questions_self on hunter8.profile_questions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_profiles_self on hunter8.confirmed_profiles
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_theses_self on hunter8.company_theses
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_companies_self on hunter8.watched_companies
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_assessments_self on hunter8.match_assessments
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_feedback_self on hunter8.shortlist_feedback
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_runs_self on hunter8.pipeline_runs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_deletions_self on hunter8.deletion_requests
  for select using (auth.uid() = user_id);

-- Shared posting data is readable only where the caller owns an assessment of
-- it. Writes are service-role only (the discovery pipeline), so no write policy.
create policy h8_postings_via_own_assessment on hunter8.job_postings
  for select using (
    exists (
      select 1 from hunter8.match_assessments a
      where a.posting_url = hunter8.job_postings.url
        and a.user_id = auth.uid()
    )
  );

grant usage on schema hunter8 to authenticated;
grant select, insert, update, delete on all tables in schema hunter8 to authenticated;
