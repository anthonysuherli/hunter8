-- Companion product schema. Isolated from delapan's `public` schema; every
-- user-owned row terminates at auth.users. Additive only.
create schema if not exists hunter8;

create table if not exists hunter8.invites (
  token         text primary key,
  email         text not null,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null,
  redeemed_at   timestamptz,
  redeemed_by   uuid references auth.users on delete set null
);

create table if not exists hunter8.product_memberships (
  user_id       uuid primary key references auth.users on delete cascade,
  email         text not null,
  invite_token  text references hunter8.invites(token),
  state         text not null default 'active'
                check (state in ('active', 'delete_pending')),
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.resume_uploads (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  object_path   text not null,
  parse_state   text not null default 'uploaded'
                check (parse_state in ('uploaded', 'parsed', 'parse_error')),
  parse_error   text,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.profile_drafts (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  payload       jsonb not null,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.profile_questions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  draft_id      uuid not null references hunter8.profile_drafts on delete cascade,
  key           text not null,
  prompt        text not null,
  reason        text not null,
  anchor_section text not null,
  answer        text,
  answered_at   timestamptz
);

create table if not exists hunter8.confirmed_profiles (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  version       integer not null check (version >= 1),
  payload       jsonb not null,
  created_at    timestamptz not null default now(),
  unique (user_id, version)
);

create table if not exists hunter8.company_theses (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  profile_id    uuid not null references hunter8.confirmed_profiles on delete cascade,
  payload       jsonb not null,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.watched_companies (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  profile_id    uuid not null references hunter8.confirmed_profiles on delete cascade,
  name          text not null,
  tier          text not null check (tier in ('core', 'adjacent', 'exploratory')),
  careers_url   text,
  ats           text,
  board         text,
  verification  text not null default 'pending'
                check (verification in ('verified', 'pending', 'rejected')),
  evidence_ids  text[] not null default '{}'
);

-- Public posting data, deduplicated independently of users. No user_id: it is
-- shared, and is exposed only through a user's own assessments (see RLS).
create table if not exists hunter8.job_postings (
  url           text primary key,
  canonical_url text,
  company       text not null,
  title         text not null,
  location      text,
  source        text not null,
  ats           text,
  posted_at     text,
  description   text,
  fetched_at    timestamptz not null default now()
);

create table if not exists hunter8.match_assessments (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  profile_id    uuid not null references hunter8.confirmed_profiles on delete cascade,
  posting_url   text not null references hunter8.job_postings on delete cascade,
  score         integer not null check (score between 0 and 100),
  constraint_results jsonb not null default '[]',
  explanation   text,
  evidence_ids  text[] not null default '{}',
  tradeoffs     text[] not null default '{}',
  uncertainties text[] not null default '{}',
  provider      text not null,
  model         text not null,
  created_at    timestamptz not null default now(),
  unique (user_id, profile_id, posting_url)
);

create table if not exists hunter8.shortlist_feedback (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  assessment_id uuid not null references hunter8.match_assessments on delete cascade,
  value         text not null check (value in ('useful', 'not_useful')),
  reason        text,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.pipeline_runs (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  stage         text not null,
  state         text not null,
  detail        text,
  counters      jsonb not null default '{}',
  updated_at    timestamptz not null default now()
);

create table if not exists hunter8.deletion_requests (
  user_id       uuid primary key,
  state         text not null default 'delete_pending'
                check (state in ('delete_pending', 'done', 'delete_error')),
  detail        text,
  requested_at  timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_h8_uploads_user on hunter8.resume_uploads(user_id);
create index if not exists idx_h8_drafts_user on hunter8.profile_drafts(user_id);
create index if not exists idx_h8_questions_user on hunter8.profile_questions(user_id);
create index if not exists idx_h8_profiles_user on hunter8.confirmed_profiles(user_id);
create index if not exists idx_h8_companies_user on hunter8.watched_companies(user_id);
create index if not exists idx_h8_assessments_user on hunter8.match_assessments(user_id);
create index if not exists idx_h8_feedback_user on hunter8.shortlist_feedback(user_id);
create index if not exists idx_h8_runs_user on hunter8.pipeline_runs(user_id);
create index if not exists idx_h8_invites_email on hunter8.invites(email);
