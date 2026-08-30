-- Existing projects may retain the legacy default DELETE grant on public tables.
revoke delete on table public.broker_snapshot_v0 from service_role;
