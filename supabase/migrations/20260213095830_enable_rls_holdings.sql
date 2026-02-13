alter table public.holdings enable row level security;
alter table public.holdings force row level security;

revoke all on table public.holdings from anon;
revoke all on table public.holdings from authenticated;
