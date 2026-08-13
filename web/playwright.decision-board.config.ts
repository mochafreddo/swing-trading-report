import { defineConfig } from "@playwright/test";

const webPort = 43117;
const fixturePort = 43118;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "decision-board-reports.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    browserName: "chromium",
    channel: "chrome",
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
      },
    },
  ],
});
