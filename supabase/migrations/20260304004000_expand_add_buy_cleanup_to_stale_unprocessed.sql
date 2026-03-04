create index if not exists holdings_add_buy_events_processed_updated_at_created_at_idx
on public.holdings_add_buy_events (processed, updated_at, created_at);

create or replace function public.cleanup_holdings_add_buy_events(
  p_retention interval default interval '90 days',
  p_batch_size integer default 500
)
returns integer
language plpgsql
as $$
declare
  v_deleted integer := 0;
begin
  if p_batch_size is null or p_batch_size <= 0 then
    raise exception 'batch_size must be > 0';
  end if;

  with deleted_rows as (
    delete from public.holdings_add_buy_events
    where ctid in (
      select ctid
      from public.holdings_add_buy_events
      where (
          processed = true
          and created_at < now() - p_retention
        )
        or (
          processed = false
          and updated_at < now() - p_retention
        )
      order by created_at asc
      limit p_batch_size
    )
    returning 1
  )
  select count(*) into v_deleted from deleted_rows;

  return v_deleted;
end;
$$;

revoke all on function public.cleanup_holdings_add_buy_events(
  interval,
  integer
) from anon;

revoke all on function public.cleanup_holdings_add_buy_events(
  interval,
  integer
) from authenticated;
