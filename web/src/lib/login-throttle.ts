import { toErrorMessage } from "@/lib/error-utils";
import {
  consumeLoginThrottleAttempt,
  deleteRuntimeStateEntry,
  fetchRuntimeStateEntry,
} from "@/lib/supabase-admin";

type LoginThrottleConfig = {
  maxAttempts: number;
  windowMs: number;
  blockMs: number;
};

type LoginAttemptState = {
  failures: number;
  windowStartedAt: number;
  blockedUntil: number;
};

type RuntimeStateStore = "memory" | "supabase";
type LoginThrottleFailMode = "strict" | "degrade";
type LoginThrottleOperation = "assert" | "record" | "clear";

const DEFAULT_MAX_ATTEMPTS = 5;
const DEFAULT_WINDOW_SECONDS = 15 * 60;
const DEFAULT_BLOCK_SECONDS = 15 * 60;
const MAX_TRACKED_LOGIN_KEYS = 512;
const GLOBAL_LOGIN_THROTTLE_KEY = "__global__";
const USER_LOGIN_THROTTLE_PREFIX = "user:";
const LOGIN_THROTTLE_RUNTIME_STATE_PREFIX = "login_throttle:";

let globalAttemptState: LoginAttemptState | null = null;
const perUserAttempts = new Map<string, LoginAttemptState>();

function isGlobalThrottleKey(key: string): boolean {
  return key === GLOBAL_LOGIN_THROTTLE_KEY;
}

function resolveRuntimeStateStore(): RuntimeStateStore {
  const raw = process.env.SAB_RUNTIME_STATE_STORE?.trim().toLowerCase();
  if (raw === "memory") {
    return "memory";
  }
  if (raw === "supabase") {
    return "supabase";
  }
  return process.env.NODE_ENV === "test" ? "memory" : "supabase";
}

function resolveLoginThrottleFailMode(): LoginThrottleFailMode {
  const raw = process.env.SAB_LOGIN_THROTTLE_FAIL_MODE?.trim().toLowerCase();
  return raw === "degrade" ? "degrade" : "strict";
}

function buildRuntimeStateKey(key: string): string {
  return `${LOGIN_THROTTLE_RUNTIME_STATE_PREFIX}${key}`;
}

function readPositiveIntEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) {
    return fallback;
  }

  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return fallback;
  }
  return parsed;
}

function getLoginThrottleConfig(): LoginThrottleConfig {
  const maxAttempts = readPositiveIntEnv(
    "SAB_LOGIN_MAX_ATTEMPTS",
    DEFAULT_MAX_ATTEMPTS,
  );
  const windowSeconds = readPositiveIntEnv(
    "SAB_LOGIN_WINDOW_SECONDS",
    DEFAULT_WINDOW_SECONDS,
  );
  const blockSeconds = readPositiveIntEnv(
    "SAB_LOGIN_BLOCK_SECONDS",
    DEFAULT_BLOCK_SECONDS,
  );
  return {
    maxAttempts,
    windowMs: windowSeconds * 1000,
    blockMs: blockSeconds * 1000,
  };
}

function isAttemptStateExpired(
  state: LoginAttemptState,
  now: number,
  config: LoginThrottleConfig,
): boolean {
  const windowExpired = now - state.windowStartedAt > config.windowMs;
  const blockExpired = state.blockedUntil <= now;
  return windowExpired && blockExpired;
}

function shouldResetAttemptState(
  state: LoginAttemptState,
  now: number,
  config: LoginThrottleConfig,
): boolean {
  return (
    now - state.windowStartedAt > config.windowMs ||
    (state.blockedUntil > 0 && state.blockedUntil <= now)
  );
}

function parseLoginAttemptState(
  payload: Record<string, unknown>,
): LoginAttemptState | null {
  const failures = payload.failures;
  const windowStartedAt = payload.windowStartedAt;
  const blockedUntil = payload.blockedUntil;
  if (
    typeof failures !== "number" ||
    !Number.isFinite(failures) ||
    !Number.isInteger(failures) ||
    failures < 0 ||
    typeof windowStartedAt !== "number" ||
    !Number.isFinite(windowStartedAt) ||
    !Number.isInteger(windowStartedAt) ||
    windowStartedAt < 0 ||
    typeof blockedUntil !== "number" ||
    !Number.isFinite(blockedUntil) ||
    !Number.isInteger(blockedUntil) ||
    blockedUntil < 0
  ) {
    return null;
  }

  return {
    failures,
    windowStartedAt,
    blockedUntil,
  };
}

function cleanupGlobalAttempt(now: number, config: LoginThrottleConfig): void {
  if (!globalAttemptState) {
    return;
  }
  if (isAttemptStateExpired(globalAttemptState, now, config)) {
    globalAttemptState = null;
  }
}

function cleanupPerUserAttempts(
  now: number,
  config: LoginThrottleConfig,
): void {
  for (const [key, state] of perUserAttempts) {
    const windowExpired = now - state.windowStartedAt > config.windowMs;
    const blockExpired = state.blockedUntil <= now;
    if (windowExpired && blockExpired) {
      perUserAttempts.delete(key);
    }
  }
}

function evictOldestKeysIfNeeded(): void {
  while (perUserAttempts.size >= MAX_TRACKED_LOGIN_KEYS) {
    const oldestKey = perUserAttempts.keys().next().value;
    if (oldestKey == null) {
      break;
    }
    perUserAttempts.delete(oldestKey);
  }
}

function assertLoginAttemptAllowedInMemory(key: string, now: number): void {
  const config = getLoginThrottleConfig();
  cleanupGlobalAttempt(now, config);
  cleanupPerUserAttempts(now, config);

  const state = isGlobalThrottleKey(key)
    ? globalAttemptState
    : perUserAttempts.get(key);
  if (!state) {
    return;
  }

  if (state.blockedUntil > now) {
    const retryAfterSeconds = Math.max(
      1,
      Math.ceil((state.blockedUntil - now) / 1000),
    );
    throw new LoginThrottleError(retryAfterSeconds);
  }

  if (shouldResetAttemptState(state, now, config)) {
    if (isGlobalThrottleKey(key)) {
      globalAttemptState = null;
    } else {
      perUserAttempts.delete(key);
    }
  }
}

function recordLoginAttemptFailureInMemory(key: string, now: number): void {
  const config = getLoginThrottleConfig();
  cleanupGlobalAttempt(now, config);
  cleanupPerUserAttempts(now, config);

  const current = isGlobalThrottleKey(key)
    ? globalAttemptState
    : perUserAttempts.get(key);
  if (current && current.blockedUntil > now) {
    const retryAfterSeconds = Math.max(
      1,
      Math.ceil((current.blockedUntil - now) / 1000),
    );
    throw new LoginThrottleError(retryAfterSeconds);
  }
  const windowExpired =
    !current || shouldResetAttemptState(current, now, config);

  const state: LoginAttemptState = windowExpired
    ? { failures: 0, windowStartedAt: now, blockedUntil: 0 }
    : current;

  state.failures += 1;
  if (state.failures >= config.maxAttempts) {
    state.blockedUntil = now + config.blockMs;
  }

  if (isGlobalThrottleKey(key)) {
    globalAttemptState = state;
    return;
  }

  if (!current) {
    evictOldestKeysIfNeeded();
  }
  perUserAttempts.set(key, state);
}

function clearLoginAttemptFailuresInMemory(key: string): void {
  if (isGlobalThrottleKey(key)) {
    globalAttemptState = null;
  } else {
    perUserAttempts.delete(key);
  }
}

async function deleteRuntimeStateEntryBestEffort(key: string): Promise<void> {
  try {
    await deleteRuntimeStateEntry(key);
  } catch {
    // Cleanup failure must not block login request handling.
  }
}

async function loadLoginAttemptStateFromSupabase(
  key: string,
  now: number,
  config: LoginThrottleConfig,
): Promise<LoginAttemptState | null> {
  const runtimeKey = buildRuntimeStateKey(key);
  const cached = await fetchRuntimeStateEntry(runtimeKey);
  if (!cached) {
    return null;
  }

  const expiresAt = Date.parse(cached.expires_at);
  if (!Number.isFinite(expiresAt) || expiresAt <= now) {
    await deleteRuntimeStateEntryBestEffort(runtimeKey);
    return null;
  }

  const parsed = parseLoginAttemptState(cached.state_payload);
  if (!parsed || shouldResetAttemptState(parsed, now, config)) {
    await deleteRuntimeStateEntryBestEffort(runtimeKey);
    return null;
  }

  return parsed;
}

async function assertLoginAttemptAllowedInSupabase(
  key: string,
  now: number,
): Promise<void> {
  const config = getLoginThrottleConfig();
  const state = await loadLoginAttemptStateFromSupabase(key, now, config);
  if (!state) {
    return;
  }

  if (state.blockedUntil > now) {
    const retryAfterSeconds = Math.max(
      1,
      Math.ceil((state.blockedUntil - now) / 1000),
    );
    throw new LoginThrottleError(retryAfterSeconds);
  }
}

async function recordLoginAttemptFailureInSupabase(
  key: string,
  now: number,
): Promise<void> {
  const config = getLoginThrottleConfig();
  const result = await consumeLoginThrottleAttempt({
    key: buildRuntimeStateKey(key),
    now,
    windowMs: config.windowMs,
    blockMs: config.blockMs,
    maxAttempts: config.maxAttempts,
    userKeyCap: MAX_TRACKED_LOGIN_KEYS,
  });
  if (result.isBlocked) {
    throw new LoginThrottleError(result.retryAfterSeconds);
  }
}

async function clearLoginAttemptFailuresInSupabase(key: string): Promise<void> {
  await deleteRuntimeStateEntry(buildRuntimeStateKey(key));
}

function logLoginThrottleDegraded(
  op: LoginThrottleOperation,
  key: string,
  error: unknown,
): void {
  const errorType =
    error instanceof Error && error.name
      ? error.name
      : typeof error === "object"
        ? "UnknownError"
        : typeof error;
  const errorMessage = toErrorMessage(error, String(error));
  console.warn(
    JSON.stringify({
      event: "login_throttle_degraded",
      mode: "degrade",
      op,
      throttle_key_type: isGlobalThrottleKey(key) ? "global" : "user",
      error_type: errorType,
      error_message: errorMessage,
    }),
  );
}

export class LoginThrottleError extends Error {
  readonly status = 429;
  readonly retryAfterSeconds: number;

  constructor(retryAfterSeconds: number) {
    super("Too many login attempts. Try again later.");
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function buildGlobalLoginThrottleKey(): string {
  return GLOBAL_LOGIN_THROTTLE_KEY;
}

export function buildLoginThrottleKey(username: string): string {
  const normalizedUsername = username.trim().toLowerCase();
  return `${USER_LOGIN_THROTTLE_PREFIX}${normalizedUsername || "unknown"}`;
}

export async function assertLoginAttemptAllowed(
  key: string,
  now = Date.now(),
): Promise<void> {
  if (resolveRuntimeStateStore() === "memory") {
    assertLoginAttemptAllowedInMemory(key, now);
    return;
  }
  try {
    await assertLoginAttemptAllowedInSupabase(key, now);
  } catch (error) {
    if (error instanceof LoginThrottleError) {
      throw error;
    }
    if (resolveLoginThrottleFailMode() === "strict") {
      throw error;
    }
    logLoginThrottleDegraded("assert", key, error);
    assertLoginAttemptAllowedInMemory(key, now);
  }
}

export async function recordLoginAttemptFailure(
  key: string,
  now = Date.now(),
): Promise<void> {
  if (resolveRuntimeStateStore() === "memory") {
    recordLoginAttemptFailureInMemory(key, now);
    return;
  }
  try {
    await recordLoginAttemptFailureInSupabase(key, now);
  } catch (error) {
    if (error instanceof LoginThrottleError) {
      throw error;
    }
    if (resolveLoginThrottleFailMode() === "strict") {
      throw error;
    }
    logLoginThrottleDegraded("record", key, error);
    recordLoginAttemptFailureInMemory(key, now);
  }
}

export async function clearLoginAttemptFailures(key: string): Promise<void> {
  if (resolveRuntimeStateStore() === "memory") {
    clearLoginAttemptFailuresInMemory(key);
    return;
  }
  try {
    await clearLoginAttemptFailuresInSupabase(key);
  } catch (error) {
    if (resolveLoginThrottleFailMode() === "strict") {
      throw error;
    }
    logLoginThrottleDegraded("clear", key, error);
    clearLoginAttemptFailuresInMemory(key);
  }
}

export function __resetLoginThrottleForTests(): void {
  globalAttemptState = null;
  perUserAttempts.clear();
}

export function __getTrackedLoginThrottleKeyCountForTests(): number {
  return perUserAttempts.size;
}
