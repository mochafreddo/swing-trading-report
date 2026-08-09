import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  fetchLatestDecisionBoardReport,
  fetchReportIndexPage,
} from "@/lib/supabase-admin";
import { isReportType } from "@/lib/types";

const DIGEST_A = "a".repeat(64);
const DIGEST_B = "b".repeat(64);
const ENTRY_KEY = `2026/08/2026-08-06.decision-board.entry.entry-run.${DIGEST_A}.json`;

function response(rows: unknown[]): Response {
  return new Response(JSON.stringify(rows), {
    status: 200,
    headers: {
      "content-type": "application/json",
      "content-range": `0-${Math.max(rows.length - 1, 0)}/${rows.length}`,
    },
  });
}

function decisionRow(overrides: Record<string, unknown> = {}) {
  return {
    bucket_id: "reports",
    report_key: ENTRY_KEY,
    report_type: "decision-board",
    report_date: "2026-08-06",
    duplicate_index: 0,
    generated_at: null,
    summary: null,
    tickers: [],
    tickers_hydrated: false,
    run_kind: "ENTRY",
    run_id: "entry-run",
    idempotency_key: `sha256:${DIGEST_A}`,
    decision_created_at: "2026-08-06T01:00:05Z",
    ...overrides,
  };
}

beforeAll(() => {
  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_SECRET_KEY = "sb_secret_test_key";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Decision Board report index", () => {
  it("adds decision-board to the server report type contract", () => {
    expect(isReportType("decision-board")).toBe(true);
  });

  it("parses an exact ENTRY row and uses Decision Board latest ordering", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(response([decisionRow()]));

    const result = await fetchReportIndexPage({
      type: "decision-board",
      runKind: "ENTRY",
      limit: 1,
    });

    expect(result.items).toEqual([decisionRow()]);
    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.searchParams.get("report_type")).toBe("eq.decision-board");
    expect(url.searchParams.get("run_kind")).toBe("eq.ENTRY");
    expect(url.searchParams.get("order")).toBe(
      "decision_created_at.desc,run_id.desc,report_key.desc,bucket_id.desc",
    );
    expect(url.searchParams.get("select")).toContain("idempotency_key");
    expect(url.searchParams.get("select")).toContain("decision_created_at");
  });

  it.each([
    { run_kind: null },
    { run_kind: "entry" },
    { run_id: "../escape" },
    { idempotency_key: `sha256:${DIGEST_B}` },
    { decision_created_at: "2026-08-06T01:00:05" },
    { decision_created_at: "2026-08-07T01:00:05Z" },
    { tickers: ["PRIVATE.NAS"] },
    { report_key: ` ${ENTRY_KEY}` },
    { report_date: " 2026-08-06" },
    { bucket_id: " reports" },
  ])("skips malformed Decision Board row %#", async (override) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response([decisionRow(override)]),
    );

    const result = await fetchReportIndexPage({ type: "decision-board" });

    expect(result.items).toEqual([]);
    expect(result.fetchedCount).toBe(1);
  });

  it("normalizes absent Decision Board fields to null for legacy rows", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response([
        {
          bucket_id: "reports",
          report_key: "2026/08/2026-08-06.buy.json",
          report_type: "buy",
          report_date: "2026-08-06",
          duplicate_index: 0,
          generated_at: null,
          summary: null,
          tickers: [],
          tickers_hydrated: false,
        },
      ]),
    );

    const result = await fetchReportIndexPage({ type: "buy" });

    expect(result.items[0]).toMatchObject({
      run_kind: null,
      run_id: null,
      idempotency_key: null,
      decision_created_at: null,
    });
  });

  it.each(["buy", "all"] as const)(
    "rejects runKind with type=%s before a request",
    async (type) => {
      const fetchMock = vi.spyOn(globalThis, "fetch");

      await expect(
        fetchReportIndexPage({ type, runKind: "ENTRY" }),
      ).rejects.toThrow("runKind requires type=decision-board");
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("latest ENTRY lookup cannot return a HOLDING row", async () => {
    const holdingKey = `2026/08/2026-08-06.decision-board.holding.holding-run.${DIGEST_B}.json`;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response([
        decisionRow({
          report_key: holdingKey,
          run_kind: "HOLDING",
          run_id: "holding-run",
          idempotency_key: `sha256:${DIGEST_B}`,
        }),
      ]),
    );

    await expect(fetchLatestDecisionBoardReport("ENTRY")).resolves.toBeNull();
    const url = new URL(String(fetchMock.mock.calls[0]?.[0]));
    expect(url.searchParams.get("report_type")).toBe("eq.decision-board");
    expect(url.searchParams.get("run_kind")).toBe("eq.ENTRY");
    expect(url.searchParams.get("limit")).toBe("1");
  });
});
