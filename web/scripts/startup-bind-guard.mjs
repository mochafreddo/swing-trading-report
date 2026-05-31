const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);

function normalizeBindHost(rawHost) {
  if (typeof rawHost !== "string") {
    return "127.0.0.1";
  }

  const trimmed = rawHost.trim().toLowerCase();
  if (!trimmed) {
    return "127.0.0.1";
  }

  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    return trimmed.slice(1, -1);
  }

  return trimmed;
}

function isLoopbackBindHost(host) {
  return LOOPBACK_HOSTS.has(host);
}

function isLocalRequestGuardEnabled(env) {
  return env.SAB_ENFORCE_LOCAL_REQUEST !== "0";
}

function isNonLoopbackBindAllowed(env) {
  return env.SAB_ALLOW_NON_LOOPBACK_BIND === "1";
}

export function evaluateStartupBindGuard(env = process.env, options = {}) {
  if (
    Object.hasOwn(options, "bindHost") &&
    typeof options.bindHost === "string" &&
    !options.bindHost.trim()
  ) {
    return {
      bindHost: "",
      warning: null,
      error:
        "Next.js --hostname must not be empty. Bind to 127.0.0.1/localhost/::1, " +
        "or set SAB_ALLOW_NON_LOOPBACK_BIND=1 with an explicit trusted hostname.",
    };
  }

  const bindHost = normalizeBindHost(options.bindHost ?? env.WEB_BIND_HOST);
  const guardEnabled = isLocalRequestGuardEnabled(env);
  const nonLoopbackAllowed = isNonLoopbackBindAllowed(env);

  if (isLoopbackBindHost(bindHost)) {
    return {
      bindHost,
      warning: null,
      error: null,
    };
  }

  const scopeMessage =
    `WEB_BIND_HOST=${bindHost} binds the web server beyond loopback. ` +
    "This project only supports localhost-only exposure.";

  if (!nonLoopbackAllowed) {
    return {
      bindHost,
      warning: null,
      error:
        `${scopeMessage} Refusing to start without ` +
        "SAB_ALLOW_NON_LOOPBACK_BIND=1. Bind to 127.0.0.1/localhost/::1, " +
        "or set the override only when a trusted outer boundary restricts access.",
    };
  }

  const guardMessage = guardEnabled
    ? "The local-request guard remains enabled."
    : "SAB_ENFORCE_LOCAL_REQUEST=0 also disables the local-request guard.";
  return {
    bindHost,
    warning:
      `${scopeMessage} SAB_ALLOW_NON_LOOPBACK_BIND=1 is set. ` +
      `${guardMessage} Docker Compose localhost publishing ` +
      "(127.0.0.1:PORT:3000) remains supported even when the container " +
      "binds 0.0.0.0 internally.",
    error: null,
  };
}

export function enforceStartupBindGuard(
  env = process.env,
  log = console,
  options = {},
) {
  const result = evaluateStartupBindGuard(env, options);

  if (result.error) {
    throw new Error(result.error);
  }

  if (result.warning) {
    log.warn(result.warning);
  }

  return result;
}
