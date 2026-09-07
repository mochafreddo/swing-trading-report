import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "toss-order-view.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  outputDir: "/private/tmp/toss-order-view-test-results",
  use: {
    browserName: "chromium",
    ...(process.platform === "darwin" ? { channel: "chrome" } : {}),
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
