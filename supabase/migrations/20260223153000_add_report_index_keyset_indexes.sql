create index if not exists report_index_type_date_duplicate_key_idx
on public.report_index (
  report_type,
  report_date desc,
  duplicate_index desc,
  report_key desc
);

create index if not exists report_index_date_duplicate_key_idx
on public.report_index (
  report_date desc,
  duplicate_index desc,
  report_key desc
);
