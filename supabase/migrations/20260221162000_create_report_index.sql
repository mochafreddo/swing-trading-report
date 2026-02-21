create table if not exists public.report_index (
  report_key text primary key,
  report_type text not null
    check (report_type in ('buy', 'sell')),
  report_date date not null,
  duplicate_index integer not null default 0
    check (duplicate_index >= 0),
  generated_at text null,
  summary jsonb null,
  tickers text[] not null default '{}'::text[],
  tickers_hydrated boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists report_index_type_date_duplicate_idx
on public.report_index (report_type, report_date desc, duplicate_index desc);

create index if not exists report_index_date_duplicate_idx
on public.report_index (report_date desc, duplicate_index desc);

create or replace function public.set_report_index_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists report_index_set_updated_at on public.report_index;

create trigger report_index_set_updated_at
before update on public.report_index
for each row
execute function public.set_report_index_updated_at();

alter table public.report_index enable row level security;
alter table public.report_index force row level security;

revoke all on table public.report_index from anon;
revoke all on table public.report_index from authenticated;

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
  (regexp_match(objects.name, '\.(buy|sell)\.json$'))[1] as report_type,
  ((regexp_match(objects.name, '/(\d{4}-\d{2}-\d{2})(?:-\d+)?\.(buy|sell)\.json$'))[1])::date as report_date,
  coalesce(
    nullif(
      (regexp_match(objects.name, '/\d{4}-\d{2}-\d{2}-(\d+)\.(buy|sell)\.json$'))[1],
      ''
    )::integer,
    0
  ) as duplicate_index,
  '{}'::text[] as tickers,
  false as tickers_hydrated
from storage.objects as objects
where objects.bucket_id = 'reports'
  and objects.name ~ '^\d{4}/\d{2}/\d{4}-\d{2}-\d{2}(?:-\d+)?\.(buy|sell)\.json$'
on conflict (report_key) do update
set
  report_type = excluded.report_type,
  report_date = excluded.report_date,
  duplicate_index = excluded.duplicate_index,
  tickers_hydrated = report_index.tickers_hydrated,
  updated_at = now();
