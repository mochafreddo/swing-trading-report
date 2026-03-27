alter table public.report_index
drop constraint if exists report_index_report_type_check;

alter table public.report_index
add constraint report_index_report_type_check
check (report_type in ('buy', 'sell', 'entry'));

insert into public.report_index (
  report_key,
  report_type,
  report_date,
  duplicate_index,
  tickers,
  tickers_hydrated
)
select
  objects.name as report_key,
  (regexp_match(objects.name, '\.(buy|sell|entry)\.json$'))[1] as report_type,
  ((regexp_match(objects.name, '/(\d{4}-\d{2}-\d{2})(?:-\d+)?\.(buy|sell|entry)\.json$'))[1])::date as report_date,
  coalesce(
    nullif(
      (regexp_match(objects.name, '/\d{4}-\d{2}-\d{2}-(\d+)\.(buy|sell|entry)\.json$'))[1],
      ''
    )::integer,
    0
  ) as duplicate_index,
  '{}'::text[] as tickers,
  false as tickers_hydrated
from storage.objects as objects
where objects.bucket_id = 'reports'
  and objects.name ~ '^\d{4}/\d{2}/\d{4}-\d{2}-\d{2}(?:-\d+)?\.(buy|sell|entry)\.json$'
on conflict (report_key) do update
set
  report_type = excluded.report_type,
  report_date = excluded.report_date,
  duplicate_index = excluded.duplicate_index,
  summary = report_index.summary,
  tickers = report_index.tickers,
  tickers_hydrated = report_index.tickers_hydrated,
  updated_at = now();
