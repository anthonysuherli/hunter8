-- Private résumé bucket. Object paths are "<user_id>/<uuid>", so the first path
-- segment is the ownership check. The raw file is deleted after the profile is
-- confirmed; only structured evidence and minimal excerpts survive.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'hunter8-resumes', 'hunter8-resumes', false, 10485760,
  array['application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
)
-- do update, not do nothing: a bucket that already exists from a dashboard
-- click or a failed run could be public, and `do nothing` would silently leave
-- it that way while the migration reported success. This only ever touches the
-- row keyed 'hunter8-resumes', so no delapan bucket is reachable.
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- Storage policies: clients can upload, read, and delete their own résumés.
-- Unlike hunter8 tables (read-only), storage objects are inherently client-writable
-- because users upload their own files directly (not via service_role). The first
-- path segment is the ownership boundary — all paths must be "<user_id>/<uuid>".
-- This read policy scopes object access to the bucket and user ownership.
create policy h8_resumes_read_own on storage.objects
  for select to authenticated
  using (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- Upload is the one client-writable surface in the product, and Storage does
-- not route through companion_api — so the invite gate has to live HERE too.
-- `authenticated` is shared with delapan: without the membership check, any
-- delapan user with no hunter8 invite could write into this bucket. Read and
-- delete stay ownership-only on purpose, so a user whose membership is
-- delete_pending can still remove their own file.
-- Paths must be exactly "<user_id>/<object>"; nesting is refused so the
-- deletion sweep (which lists one level via bucket.list(user_id)) can never
-- miss a file left behind under a nested prefix.
create policy h8_resumes_insert_own on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
    and array_length(storage.foldername(name), 1) = 1
    and exists (
      select 1 from hunter8.product_memberships m
      where m.user_id = auth.uid() and m.state = 'active'
    )
  );

-- There is deliberately NO update policy. storage.objects ships with RLS on, so
-- no policy means default-deny on UPDATE: an object cannot be overwritten,
-- renamed, or moved. Paths embed a fresh uuid per upload, so nothing legitimate
-- needs it. If one is ever added, it MUST carry a `with check` on the new name —
-- a `using`-only update policy would let a user move their object into someone
-- else's folder.

-- This delete policy scopes deletion to the user's own objects.
create policy h8_resumes_delete_own on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
