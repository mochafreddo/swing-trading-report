do $do$
begin
  if to_regnamespace('cron') is null then
    raise notice 'cron schema not found; skipping holdings_add_buy_events cleanup schedule';
    return;
  end if;

  perform cron.schedule(
    'holdings-add-buy-events-cleanup',
    '30 3 * * *',
    $sql$select public.cleanup_holdings_add_buy_events(interval '90 days', 500);$sql$
  );
end;
$do$;
