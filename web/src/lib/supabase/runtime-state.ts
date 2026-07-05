import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import { quotePostgrestValue } from "@/lib/postgrest-filter";
import {
  buildAuthHeaders,
  fetchSupabase,
  parseError,
  SupabaseApiError,
} from "@/lib/supabase/admin-client";

const RUNTIME_STATE_SELECT = "state_key,state_payload,expires_at";

export interface RuntimeStateEntry {
  state_key: string;
  state_payload: Record<string, unknown>;
  expires_at: string;
}

export interface ConsumeLoginThrottleAttemptInput {
  key: string;
  now: number;
  windowMs: number;
  blockMs: number;
  maxAttempts: number;
  userKeyCap: number;
}

export interface ConsumeLoginThrottleAttemptResult {
  failures: number;
  windowStartedAt: number;
  blockedUntil: number;
  isBlocked: boolean;
  retryAfterSeconds: number;
}

export interface ClaimRuntimeStateLockInput {
  key: string;
  now: number;
  ttlSeconds: number;
  payload?: Record<string, unknown>;
}

export interface ClaimRuntimeStateLockResult {
  acquired: boolean;
  expiresAt: string;
}

export interface ReleaseRuntimeStateLockInput {
  key: string;
  ownerToken: string;
}

function parseRuntimeStateEntry(payload: unknown): RuntimeStateEntry | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const raw = payload[0] as
    | {
        state_key?: unknown;
        state_payload?: unknown;
        expires_at?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }

  if (
    typeof raw.state_key !== "string" ||
    !raw.state_key.trim() ||
    typeof raw.expires_at !== "string" ||
    !raw.expires_at.trim() ||
    !raw.state_payload ||
    typeof raw.state_payload !== "object" ||
    Array.isArray(raw.state_payload)
  ) {
    return null;
  }

  return {
    state_key: raw.state_key,
    state_payload: raw.state_payload as Record<string, unknown>,
    expires_at: raw.expires_at,
  };
}

export async function fetchRuntimeStateEntry(
  key: string,
): Promise<RuntimeStateEntry | null> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: RUNTIME_STATE_SELECT,
    state_key: `eq.${quotePostgrestValue(key)}`,
    limit: "1",
  });
  const url = `${env.SUPABASE_URL}/rest/v1/runtime_state?${query.toString()}`;
  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch runtime state '${key}': ${await parseError(response)}`,
      response.status,
    );
  }

  return parseRuntimeStateEntry(await response.json());
}

export async function upsertRuntimeStateEntry(
  key: string,
  payload: Record<string, unknown>,
  expiresAtIso: string,
): Promise<void> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/runtime_state?on_conflict=state_key`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates,return=minimal",
    }),
    body: JSON.stringify([
      {
        state_key: key,
        state_payload: payload,
        expires_at: expiresAtIso,
      },
    ]),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to upsert runtime state '${key}': ${await parseError(response)}`,
      response.status,
    );
  }
}

export async function deleteRuntimeStateEntry(key: string): Promise<void> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    state_key: `eq.${quotePostgrestValue(key)}`,
  });
  const url = `${env.SUPABASE_URL}/rest/v1/runtime_state?${query.toString()}`;
  const response = await fetchSupabase(url, {
    method: "DELETE",
    headers: buildAuthHeaders({
      Accept: "application/json",
      Prefer: "return=minimal",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to delete runtime state '${key}': ${await parseError(response)}`,
      response.status,
    );
  }
}

function parseConsumeLoginThrottleAttemptResult(
  payload: unknown,
): ConsumeLoginThrottleAttemptResult | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const raw = payload[0] as
    | {
        failures?: unknown;
        window_started_at?: unknown;
        blocked_until?: unknown;
        is_blocked?: unknown;
        retry_after_seconds?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }

  if (
    typeof raw.failures !== "number" ||
    !Number.isFinite(raw.failures) ||
    !Number.isInteger(raw.failures) ||
    raw.failures < 0 ||
    typeof raw.window_started_at !== "number" ||
    !Number.isFinite(raw.window_started_at) ||
    !Number.isInteger(raw.window_started_at) ||
    raw.window_started_at < 0 ||
    typeof raw.blocked_until !== "number" ||
    !Number.isFinite(raw.blocked_until) ||
    !Number.isInteger(raw.blocked_until) ||
    raw.blocked_until < 0 ||
    typeof raw.is_blocked !== "boolean" ||
    typeof raw.retry_after_seconds !== "number" ||
    !Number.isFinite(raw.retry_after_seconds) ||
    !Number.isInteger(raw.retry_after_seconds) ||
    raw.retry_after_seconds < 0
  ) {
    return null;
  }

  return {
    failures: raw.failures,
    windowStartedAt: raw.window_started_at,
    blockedUntil: raw.blocked_until,
    isBlocked: raw.is_blocked,
    retryAfterSeconds: raw.retry_after_seconds,
  };
}

function parseClaimRuntimeStateLockResult(
  payload: unknown,
): ClaimRuntimeStateLockResult | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }
  const raw = payload[0] as
    | {
        acquired?: unknown;
        expires_at?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  if (typeof raw.acquired !== "boolean" || typeof raw.expires_at !== "string") {
    return null;
  }
  return {
    acquired: raw.acquired,
    expiresAt: raw.expires_at,
  };
}

export async function claimRuntimeStateLock(
  input: ClaimRuntimeStateLockInput,
): Promise<ClaimRuntimeStateLockResult> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/claim_runtime_state_lock`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_state_key: input.key,
      // Keep p_now for older RPC signatures; lock expiry uses DB now().
      p_now: null,
      p_ttl_seconds: Math.max(1, Math.floor(input.ttlSeconds)),
      p_state_payload: input.payload ?? {},
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to claim runtime state lock '${input.key}': ${await parseError(response)}`,
      response.status,
    );
  }

  const parsed = parseClaimRuntimeStateLockResult(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      `Failed to parse runtime state lock claim result for '${input.key}'`,
      500,
    );
  }
  return parsed;
}

export async function releaseRuntimeStateLock(
  input: ReleaseRuntimeStateLockInput,
): Promise<boolean> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/release_runtime_state_lock`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_state_key: input.key,
      p_owner_token: input.ownerToken,
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to release runtime state lock '${input.key}': ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  if (typeof payload !== "boolean") {
    throw new SupabaseApiError(
      `Failed to parse runtime state lock release result for '${input.key}'`,
      500,
    );
  }
  return payload;
}

export async function consumeLoginThrottleAttempt(
  input: ConsumeLoginThrottleAttemptInput,
): Promise<ConsumeLoginThrottleAttemptResult> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/consume_login_throttle_attempt`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_state_key: input.key,
      p_now: new Date(input.now).toISOString(),
      p_window_seconds: Math.max(1, Math.floor(input.windowMs / 1000)),
      p_block_seconds: Math.max(1, Math.floor(input.blockMs / 1000)),
      p_max_attempts: Math.max(1, Math.floor(input.maxAttempts)),
      p_user_key_cap: Math.max(1, Math.floor(input.userKeyCap)),
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to consume login throttle attempt: ${await parseError(response)}`,
      response.status,
    );
  }

  const parsed = parseConsumeLoginThrottleAttemptResult(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      "Supabase did not return a valid consume_login_throttle_attempt result",
      500,
    );
  }
  return parsed;
}
