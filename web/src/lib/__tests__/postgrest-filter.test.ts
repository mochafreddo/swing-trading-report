import { describe, expect, it } from "vitest";

import { quotePostgrestValue } from "@/lib/postgrest-filter";

describe("quotePostgrestValue", () => {
  it("quotes and escapes PostgREST filter values", () => {
    expect(quotePostgrestValue('AAPL.US "growth" \\ watch')).toBe(
      '"AAPL.US \\"growth\\" \\\\ watch"',
    );
  });
});
