export function normalizeEnvValue(value, fallback) {
  if (typeof value !== "string") {
    return fallback;
  }
  const trimmed = value.trim();
  return trimmed || fallback;
}

export function hasOption(args, longOption, shortOption) {
  return readOption(args, longOption, shortOption).present;
}

function attachedShortOptionValue(arg, shortOption) {
  if (!shortOption || !arg.startsWith(shortOption)) {
    return null;
  }
  if (arg.startsWith(`${shortOption}=`)) {
    return arg.slice(shortOption.length + 1);
  }
  if (arg.length > shortOption.length) {
    return arg.slice(shortOption.length);
  }
  return null;
}

function readOption(args, longOption, shortOption) {
  const missing = { present: false, value: null };
  let matched = missing;

  for (let idx = 0; idx < args.length; idx += 1) {
    const arg = args[idx];
    if (arg === "--") {
      break;
    }
    if (arg.startsWith(`${longOption}=`)) {
      matched = { present: true, value: arg.slice(longOption.length + 1) };
      continue;
    }
    const shortValue = attachedShortOptionValue(arg, shortOption);
    if (shortValue !== null) {
      matched = { present: true, value: shortValue };
      continue;
    }
    if (arg === longOption || (shortOption && arg === shortOption)) {
      const nextArg = args[idx + 1];
      let value = "";
      if (typeof nextArg === "string" && !nextArg.startsWith("-")) {
        value = nextArg;
      }
      matched = { present: true, value };
    }
  }

  return matched;
}

export function resolveEffectiveBindHost(extraArgs, env = process.env) {
  const fallback = normalizeEnvValue(env.WEB_BIND_HOST, "127.0.0.1");
  const hostnameOption = readOption(extraArgs, "--hostname", "-H");
  return hostnameOption.present ? hostnameOption.value : fallback;
}
