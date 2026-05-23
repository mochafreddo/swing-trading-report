import "server-only";

export { SupabaseApiError } from "@/lib/supabase/admin-client";
export {
  claimRuntimeStateLock,
  consumeLoginThrottleAttempt,
  deleteRuntimeStateEntry,
  fetchRuntimeStateEntry,
  releaseRuntimeStateLock,
  upsertRuntimeStateEntry,
} from "@/lib/supabase/runtime-state";
export type {
  ClaimRuntimeStateLockInput,
  ClaimRuntimeStateLockResult,
  ConsumeLoginThrottleAttemptInput,
  ConsumeLoginThrottleAttemptResult,
  ReleaseRuntimeStateLockInput,
  RuntimeStateEntry,
} from "@/lib/supabase/runtime-state";
export {
  downloadStorageJson,
  fetchReportIndexPage,
  upsertReportIndexEntry,
} from "@/lib/supabase/reports";
export type {
  FetchReportIndexPageOptions,
  FetchReportIndexPageResult,
  ReportIndexCursor,
  ReportIndexRow,
  ReportIndexUpsertInput,
} from "@/lib/supabase/reports";
export {
  addBuyToHolding,
  createHolding,
  deleteHolding,
  fetchAllHoldings,
  fetchHoldingsPage,
  replaceAllHoldings,
  updateHolding,
} from "@/lib/supabase/holdings";
export type {
  FetchHoldingsPageOptions,
  FetchHoldingsPageResult,
  HoldingAddBuyInput,
  ReplaceAllHoldingsResult,
} from "@/lib/supabase/holdings";
