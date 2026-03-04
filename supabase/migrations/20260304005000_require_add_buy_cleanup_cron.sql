do $do$
declare
  v_cleanup_job_id bigint;
begin
  if to_regnamespace('cron') is null then
    raise exception
      'cron schema not found; enable pg_cron before applying holdings_add_buy_events cleanup schedule';
  end if;

  perform cron.schedule(
    'holdings-add-buy-events-cleanup',
    '30 3 * * *',
    $sql$select public.cleanup_holdings_add_buy_events(interval '90 days', 500);$sql$
  );

  select jobid
  into v_cleanup_job_id
  from cron.job
  where jobname = 'holdings-add-buy-events-cleanup'
  limit 1;

  if v_cleanup_job_id is null then
    raise exception
      'failed to register cron job holdings-add-buy-events-cleanup';
  end if;
end;
$do$;

