alter table public.report_index
  add column if not exists tickers_hydrated boolean not null default false;

update public.report_index
set tickers_hydrated = true
where tickers_hydrated = false
  and (
    coalesce(array_length(tickers, 1), 0) > 0
    or generated_at is not null
    or summary is not null
  );
