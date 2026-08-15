import { defineConfig } from "@playwright/test";

function portFromEnv(name: string, fallback: number): number {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isSafeInteger(value) || value < 1024 || value > 65535) {
    throw new TypeError(`${name} must be a valid unprivileged TCP port`);
  }
  return value;
}

const webPort = portFromEnv("DECISION_BOARD_E2E_WEB_PORT", 43117);
const fixturePort = portFromEnv("DECISION_BOARD_E2E_FIXTURE_PORT", 43118);
const browserChannel =
  process.env.PLAYWRIGHT_CHANNEL ??
  (process.platform === "darwin" ? "chrome" : undefined);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "decision-board-reports.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    browserName: "chromium",
    ...(browserChannel ? { channel: browserChannel } : {}),
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `node e2e/decision-board-fixture-server.mjs ${fixturePort}`,
      port: fixturePort,
      reuseExistingServer: false,
    },
    {
      command: `node scripts/run-next.mjs dev --port ${webPort}`,
      port: webPort,
      reuseExistingServer: false,
      env: {
        SAB_BASIC_AUTH_USER: "fixture-admin",
        SAB_BASIC_AUTH_PASS: "fixture-password",
        SAB_SESSION_SECRET: "fixture-session-secret-at-least-32-bytes",
        SAB_SESSION_COOKIE_SECURE: "false",
        SUPABASE_URL: `http://127.0.0.1:${fixturePort}`,
        SUPABASE_SECRET_KEY: "sb_secret_fixture_only",
        SUPABASE_REPORTS_BUCKET: "reports",
        REPORT_SEARCH_WINDOW: "100",
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
