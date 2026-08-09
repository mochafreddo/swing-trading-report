alter table public.report_index
add column if not exists run_kind text null,
add column if not exists run_id text null,
add column if not exists idempotency_key text null,
add column if not exists decision_created_at timestamptz null;

alter table public.report_index
drop constraint if exists report_index_report_type_check;

alter table public.report_index
add constraint report_index_report_type_check
check (
  report_type in (
    'buy',
    'sell',
    'entry',
    'ai-brief',
    'ai-brief-skip',
    'sell-ai-brief',
    'decision-board'
  )
);

alter table public.report_index
add constraint report_index_decision_board_fields_check
check (
  (
    report_type = 'decision-board'
    and run_kind in ('ENTRY', 'HOLDING')
    and run_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'
    and idempotency_key ~ '^sha256:[0-9a-f]{64}$'
    and decision_created_at is not null
  )
  or
  (
    report_type <> 'decision-board'
    and run_kind is null
    and run_id is null
    and idempotency_key is null
    and decision_created_at is null
  )
);

create unique index if not exists report_index_decision_board_identity_uidx
on public.report_index (
  bucket_id,
  report_type,
  run_kind,
  idempotency_key
);

create unique index if not exists report_index_decision_board_run_id_uidx
on public.report_index (
  bucket_id,
  report_type,
  run_kind,
  run_id
);

create index if not exists report_index_decision_board_latest_idx
on public.report_index (
  bucket_id,
  report_type,
  run_kind,
  decision_created_at desc,
  run_id desc,
  report_key desc
)
where report_type = 'decision-board';

alter table public.report_index enable row level security;
alter table public.report_index force row level security;

revoke all on table public.report_index from public;
revoke all on table public.report_index from anon;
revoke all on table public.report_index from authenticated;
grant select, insert, update, delete on table public.report_index to service_role;
