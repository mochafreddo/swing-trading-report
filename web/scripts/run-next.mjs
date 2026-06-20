import { spawn } from "node:child_process";
import { createRequire } from "node:module";

import {
  hasOption,
  normalizeEnvValue,
  resolveEffectiveBindHost,
} from "./next-args.mjs";
import { loadRootEnv } from "./root-env-loader.mjs";
import { enforceStartupBindGuard } from "./startup-bind-guard.mjs";

loadRootEnv();

const require = createRequire(import.meta.url);

function resolveCommand(argv) {
  const command = argv[2];
  if (command === "dev" || command === "start" || command === "build") {
    return command;
  }
  return null;
}

function buildArgs(command, extraArgs) {
  const nextBin = require.resolve("next/dist/bin/next");
  const args = [nextBin, command];
  if (command !== "build") {
    if (!hasOption(extraArgs, "--hostname", "-H")) {
      const host = normalizeEnvValue(process.env.WEB_BIND_HOST, "127.0.0.1");
      args.push("--hostname", host);
    }
    if (!hasOption(extraArgs, "--port", "-p")) {
      const port = normalizeEnvValue(process.env.PORT, "3000");
      args.push("--port", port);
    }
  }
  return [...args, ...extraArgs];
}

const command = resolveCommand(process.argv);
if (!command) {
  console.error("Usage: node scripts/run-next.mjs <dev|start|build>");
  process.exit(1);
}

const extraArgs = process.argv.slice(3);

if (command !== "build") {
  try {
    const bindHost = resolveEffectiveBindHost(extraArgs, process.env);
    enforceStartupBindGuard(process.env, console, {
      bindHost,
    });
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

const child = spawn(process.execPath, buildArgs(command, extraArgs), {
  stdio: "inherit",
  env: process.env,
});

child.on("error", (error) => {
  console.error(`Failed to launch Next.js: ${error.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
