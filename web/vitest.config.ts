import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: [
      "scripts/**/*.test.mjs",
      "src/lib/__tests__/**/*.test.ts",
      "src/app/api/**/__tests__/**/*.test.ts",
    ],
    coverage: {
      provider: "v8",
      include: [
        "src/app/api/run/**/*.ts",
        "src/app/api/reports/**/*.ts",
        "src/app/api/holdings/**/*.ts",
      ],
      exclude: ["src/**/*.d.ts", "src/**/__tests__/**", "src/test-stubs/**"],
      reporter: ["text", "lcov"],
      thresholds: {
        lines: 80,
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "server-only": path.resolve(__dirname, "src/test-stubs/server-only.ts"),
    },
  },
});
