import { describe, expect, it } from "vitest";

import fixture from "../../../fixtures/toss-order-history.synthetic.json";
import decimalCases from "../../../../tests/fixtures/portfolio_mandate/toss-order-decimal-validation.synthetic.json";
import { adaptTossOrderHistory } from "@/lib/toss/order-history";

const run = (
  pages: unknown = fixture.pages,
  from = "2026-08-07",
  to = "2026-09-05",
) => adaptTossOrderHistory(JSON.stringify(pages), from, to);

describe("Toss order aggregate adapter", () => {
  it.each(decimalCases)("shared decimal validation: $name", (testCase) => {
    const pages = structuredClone(fixture.pages);
    const order = pages[0].response.result.orders[1];
    let target = order as Record<string, unknown>;
    const parts = testCase.field.split(".");
    for (const part of parts.slice(0, -1)) {
      target = target[part] as Record<string, unknown>;
    }
    target[parts.at(-1)!] = testCase.value;
    const result = run(pages);
    expect(result.state).toBe(testCase.valid ? "COMPLETE" : "ERROR");
    if (!testCase.valid) expect(result.rows).toEqual([]);
  });
  it("preserves decimal strings and order states without inventing fill identity", () => {
    const result = run();
    expect(result.state).toBe("COMPLETE");
    expect(result.pagesSeen).toBe(2);
    expect(result.rows).toHaveLength(3);
    expect(result.rows[1].averageFilledPrice).toBe("123.456789");
    expect(result.rows[1].filledQuantity).toBe("2.000000");
    expect(result.rows[2].averageFilledPrice).toBeNull();
    expect(JSON.stringify(result)).not.toMatch(
      /orderId|synthetic-order|fillId|accountSeq|commission/,
    );
  });
  it("filters by KST creation date, not browser timezone or fill time", () => {
    const result = run(fixture.pages, "2026-09-01", "2026-09-01");
    expect(result.rows.map((row) => row.symbol)).toEqual(["SYNTHA"]);
    expect(result.rows[0].orderedAtKst).toBe("2026-09-01T12:30:00.000+09:00");
    expect(run(fixture.pages, "2026-08-07", "2026-08-07").state).toBe("EMPTY");
  });
  it.each([
    ["2026-02-30", "2026-03-01"],
    ["2026-09-05", "2026-08-07"],
    ["2026-08-06", "2026-09-05"],
  ])("rejects invalid date window %s to %s", (from, to) => {
    expect(run(fixture.pages, from, to).issue).toBe("INVALID_DATE_RANGE");
  });
  it("withholds every row when pagination is incomplete or inconsistent", () => {
    expect(run(fixture.pages.slice(0, 1))).toMatchObject({
      state: "INCOMPLETE",
      rows: [],
    });
    const pages = structuredClone(fixture.pages);
    pages[1].requestCursor = "wrong";
    expect(run(pages)).toMatchObject({
      state: "ERROR",
      issue: "PAGE_CHAIN_INVALID",
      rows: [],
    });
  });
  it("rejects duplicates, unknown states and invalid decimals", () => {
    const duplicate = structuredClone(fixture.pages);
    duplicate[1].response.result.orders[0].orderId =
      duplicate[0].response.result.orders[0].orderId;
    expect(run(duplicate).issue).toBe("DUPLICATE_ORDER");
    for (const bad of ["NaN", "-1", "1e12", "11"]) {
      const pages = structuredClone(fixture.pages);
      pages[0].response.result.orders[1].execution.filledQuantity = bad;
      expect(run(pages)).toMatchObject({ state: "ERROR", rows: [] });
    }
    const pages = structuredClone(fixture.pages);
    pages[0].response.result.orders[0].status = "UNKNOWN";
    expect(run(pages).state).toBe("ERROR");
  });
  it("does not expose private unknown fields, malformed payloads or duplicate keys", () => {
    const pages = structuredClone(fixture.pages);
    Object.assign(pages[0].response.result.orders[0], {
      accountSeq: "PRIVATE_SENTINEL",
    });
    expect(JSON.stringify(run(pages))).not.toContain("PRIVATE_SENTINEL");
    expect(
      adaptTossOrderHistory('[{"x":1,"x":2}]', "2026-08-07", "2026-09-05")
        .state,
    ).toBe("ERROR");
    expect(
      adaptTossOrderHistory(" ".repeat(1_048_577), "2026-08-07", "2026-09-05")
        .issue,
    ).toBe("BUDGET_EXCEEDED");
  });
});
