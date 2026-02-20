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

const DEFAULT_MAX_ATTEMPTS = 5;
const DEFAULT_WINDOW_SECONDS = 15 * 60;
const DEFAULT_BLOCK_SECONDS = 15 * 60;
const MAX_TRACKED_LOGIN_KEYS = 512;
const GLOBAL_LOGIN_THROTTLE_KEY = "__global__";
const USER_LOGIN_THROTTLE_PREFIX = "user:";

let globalAttemptState: LoginAttemptState | null = null;
const perUserAttempts = new Map<string, LoginAttemptState>();

function isGlobalThrottleKey(key: string): boolean {
  return key === GLOBAL_LOGIN_THROTTLE_KEY;
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

export function assertLoginAttemptAllowed(key: string, now = Date.now()): void {
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

  if (
    now - state.windowStartedAt > config.windowMs ||
    (state.blockedUntil > 0 && state.blockedUntil <= now)
  ) {
    if (isGlobalThrottleKey(key)) {
      globalAttemptState = null;
    } else {
      perUserAttempts.delete(key);
    }
  }
}

export function recordLoginAttemptFailure(key: string, now = Date.now()): void {
  const config = getLoginThrottleConfig();
  cleanupGlobalAttempt(now, config);
  cleanupPerUserAttempts(now, config);

  const current = isGlobalThrottleKey(key)
    ? globalAttemptState
    : perUserAttempts.get(key);
  const windowExpired =
    !current || now - current.windowStartedAt > config.windowMs;

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

export function clearLoginAttemptFailures(key: string): void {
  if (isGlobalThrottleKey(key)) {
    globalAttemptState = null;
  } else {
    perUserAttempts.delete(key);
  }
}

export function __resetLoginThrottleForTests(): void {
  globalAttemptState = null;
  perUserAttempts.clear();
}

export function __getTrackedLoginThrottleKeyCountForTests(): number {
  return perUserAttempts.size;
}
