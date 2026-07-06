alter table public.report_index
add column if not exists bucket_id text not null default 'reports';

alter table public.report_index
drop constraint if exists report_index_pkey;

alter table public.report_index
add constraint report_index_pkey
primary key (bucket_id, report_key);

create index if not exists report_index_bucket_type_date_duplicate_key_idx
on public.report_index (
  bucket_id,
  report_type,
  report_date desc,
  duplicate_index desc,
  report_key desc
);

create index if not exists report_index_bucket_date_duplicate_key_idx
on public.report_index (
  bucket_id,
  report_date desc,
  duplicate_index desc,
  report_key desc
);

create index if not exists report_index_type_date_duplicate_key_bucket_idx
on public.report_index (
  report_type,
  report_date desc,
  duplicate_index desc,
  report_key desc,
  bucket_id desc
);

create index if not exists report_index_date_duplicate_key_bucket_idx
on public.report_index (
  report_date desc,
  duplicate_index desc,
  report_key desc,
  bucket_id desc
);

create index if not exists report_index_report_key_bucket_idx
on public.report_index (
  report_key,
  bucket_id
);

insert into public.report_index (
  bucket_id,
  report_key,
  report_type,
  report_date,
  duplicate_index,
  tickers,
  tickers_hydrated
)
select
  objects.bucket_id as bucket_id,
  objects.name as report_key,
  (regexp_match(objects.name, '\.(buy|sell|entry|ai-brief|ai-brief-skip|sell-ai-brief)\.json$'))[1] as report_type,
  ((regexp_match(objects.name, '/(\d{4}-\d{2}-\d{2})(?:-\d+)?\.(buy|sell|entry|ai-brief|ai-brief-skip|sell-ai-brief)\.json$'))[1])::date as report_date,
  coalesce(
    nullif(
      (regexp_match(objects.name, '/\d{4}-\d{2}-\d{2}-(\d+)\.(buy|sell|entry|ai-brief|ai-brief-skip|sell-ai-brief)\.json$'))[1],
      ''
    )::integer,
    0
  ) as duplicate_index,
  '{}'::text[] as tickers,
  false as tickers_hydrated
from storage.objects as objects
where objects.name ~ '^\d{4}/\d{2}/\d{4}-\d{2}-\d{2}(?:-\d+)?\.(buy|sell|entry|ai-brief|ai-brief-skip|sell-ai-brief)\.json$'
on conflict (bucket_id, report_key) do update
set
  report_type = excluded.report_type,
  report_date = excluded.report_date,
  duplicate_index = excluded.duplicate_index,
  summary = report_index.summary,
  tickers = report_index.tickers,
  tickers_hydrated = report_index.tickers_hydrated,
  updated_at = now();
