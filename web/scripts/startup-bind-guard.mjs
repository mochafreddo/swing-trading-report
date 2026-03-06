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

export function evaluateStartupBindGuard(env = process.env) {
  const bindHost = normalizeBindHost(env.WEB_BIND_HOST);
  const guardEnabled = isLocalRequestGuardEnabled(env);

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

  if (!guardEnabled) {
    return {
      bindHost,
      warning: null,
      error:
        `${scopeMessage} Refusing to start because ` +
        "SAB_ENFORCE_LOCAL_REQUEST=0 disables the local-request guard. " +
        "Re-enable the guard or bind to 127.0.0.1/localhost/::1.",
    };
  }

  return {
    bindHost,
    warning:
      `${scopeMessage} Docker Compose localhost publishing ` +
      "(127.0.0.1:PORT:3000) remains supported even when the container " +
      "binds 0.0.0.0 internally.",
    error: null,
  };
}

export function enforceStartupBindGuard(env = process.env, log = console) {
  const result = evaluateStartupBindGuard(env);

  if (result.error) {
    throw new Error(result.error);
  }

  if (result.warning) {
    log.warn(result.warning);
  }

  return result;
}
