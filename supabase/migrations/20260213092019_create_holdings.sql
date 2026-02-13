create table public.holdings (
  ticker text primary key,
  quantity double precision not null default 0,
  entry_price double precision not null default 0,
  entry_currency text null,
  entry_date date null,
  strategy text null,
  notes text null,
  tags text[] not null default '{}'::text[],
  stop_override double precision null,
  target_override double precision null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger holdings_set_updated_at
before update on public.holdings
for each row
execute function public.set_updated_at();

create index holdings_updated_at_idx
on public.holdings (updated_at);
