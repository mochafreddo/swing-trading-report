import { defineConfig } from "@playwright/test";

// Servers belong to the identity-verified PostgreSQL rehearsal and are stopped
// before its backup/restore phase. This config cannot start or reuse production.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "portfolio-live.spec.ts",
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:43317",
    browserName: "chromium",
    ...(process.platform === "darwin" ? { channel: "chrome" } : {}),
    trace: "retain-on-failure",
  },
});
