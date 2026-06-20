import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const defaultRootEnvPath = path.resolve(scriptDir, "../..", ".env");

export function loadRootEnv(options = {}) {
  const envPath = options.envPath ?? defaultRootEnvPath;
  const env = options.env ?? process.env;
  const override = options.override === true;

  let contents;
  try {
    contents = fs.readFileSync(envPath, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT") {
      return { loaded: false, path: envPath, keys: [] };
    }
    throw error;
  }

  const keys = [];
  for (const line of contents.split(/\r?\n/)) {
    const parsed = parseEnvLine(line);
    if (!parsed) {
      continue;
    }
    const [key, value] = parsed;
    keys.push(key);
    if (override || env[key] === undefined) {
      env[key] = value;
    }
  }

  return { loaded: true, path: envPath, keys };
}

export function parseEnvLine(rawLine) {
  let line = rawLine.trim();
  if (!line || line.startsWith("#")) {
    return null;
  }
  if (line.startsWith("export ")) {
    line = line.slice("export ".length).trimStart();
  }

  const separatorIndex = line.indexOf("=");
  if (separatorIndex < 1) {
    return null;
  }

  const key = line.slice(0, separatorIndex).trim();
  if (!isValidEnvKey(key)) {
    return null;
  }

  const rawValue = stripInlineComment(line.slice(separatorIndex + 1)).trim();
  return [key, unquoteValue(rawValue)];
}

function isValidEnvKey(key) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(key);
}

function stripInlineComment(value) {
  let inSingle = false;
  let inDouble = false;
  let escaped = false;

  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];

    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\") {
      escaped = true;
      continue;
    }
    if (char === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }
    if (char === '"' && !inSingle) {
      inDouble = !inDouble;
      continue;
    }
    if (
      char === "#" &&
      !inSingle &&
      !inDouble &&
      (index === 0 || /\s/.test(value[index - 1]))
    ) {
      return value.slice(0, index);
    }
  }

  return value;
}

function unquoteValue(value) {
  if (value.length >= 2) {
    const first = value[0];
    const last = value[value.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return value.slice(1, -1);
    }
  }
  return value;
}
