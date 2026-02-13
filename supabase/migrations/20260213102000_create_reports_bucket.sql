insert into storage.buckets (id, name, public, allowed_mime_types)
values ('reports', 'reports', false, array['application/json'])
on conflict (id) do update
set
  public = excluded.public,
  allowed_mime_types = excluded.allowed_mime_types;
