-- Private résumé bucket. Object paths are "<user_id>/<uuid>", so the first path
-- segment is the ownership check. The raw file is deleted after the profile is
-- confirmed; only structured evidence and minimal excerpts survive.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'hunter8-resumes', 'hunter8-resumes', false, 10485760,
  array['application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
)
on conflict (id) do nothing;

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

-- This insert policy prevents clients from uploading to other users' folders.
create policy h8_resumes_insert_own on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

-- This delete policy scopes deletion to the user's own objects.
create policy h8_resumes_delete_own on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
