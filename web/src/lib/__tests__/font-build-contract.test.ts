import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

describe("font build contract", () => {
  it("does not depend on Google Fonts at build time", () => {
    const layoutSource = fs.readFileSync(
      path.resolve(process.cwd(), "src/app/layout.tsx"),
      "utf8",
    );
    const globalCss = fs.readFileSync(
      path.resolve(process.cwd(), "src/app/globals.css"),
      "utf8",
    );

    expect(layoutSource).not.toContain("next/font/google");
    expect(layoutSource).not.toContain("fonts.googleapis");
    expect(globalCss).toContain("--font-inter:");
    expect(globalCss).toContain("--font-space-grotesk:");
  });
});
