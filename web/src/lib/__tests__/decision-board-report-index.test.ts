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
    expect(url.searchParams.get("limit")).toBe("2");
  });

  it("continues latest lookup past a malformed newest raw row", async () => {
    const malformedNewest = decisionRow({ tickers: ["PRIVATE.NAS"] });
    const older = decisionRow({
      report_key: `2026/08/2026-08-05.decision-board.entry.older-run.${DIGEST_B}.json`,
      report_date: "2026-08-05",
      run_id: "older-run",
      idempotency_key: `sha256:${DIGEST_B}`,
      decision_created_at: "2026-08-05T01:00:05Z",
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response([malformedNewest, older]))
      .mockResolvedValueOnce(response([older]));

    await expect(fetchLatestDecisionBoardReport("ENTRY")).resolves.toEqual(
      older,
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondUrl = new URL(String(fetchMock.mock.calls[1]?.[0]));
    expect(secondUrl.searchParams.get("or")).toContain(
      'decision_created_at.lt."2026-08-06T01:00:05Z"',
    );
    expect(secondUrl.searchParams.get("or")).toContain('run_id.lt."entry-run"');
  });

  it("uses a strict raw Decision cursor across invalid pages until valid data", async () => {
    const invalidFirst = decisionRow({ tickers: ["PRIVATE.NAS"] });
    const invalidSecond = decisionRow({
      report_key: `2026/08/2026-08-05.decision-board.entry.middle-run.${DIGEST_B}.json`,
      report_date: "2026-08-05",
      run_id: "middle-run",
      idempotency_key: `sha256:${DIGEST_B}`,
      decision_created_at: "2026-08-05T01:00:05Z",
      tickers: ["PRIVATE.NAS"],
    });
    const validThird = decisionRow({
      report_key: `2026/08/2026-08-04.decision-board.entry.older-run.${DIGEST_A}.json`,
      report_date: "2026-08-04",
      run_id: "older-run",
      decision_created_at: "2026-08-04T01:00:05Z",
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response([invalidFirst, invalidSecond]))
      .mockResolvedValueOnce(response([invalidSecond, validThird]))
      .mockResolvedValueOnce(response([validThird]));

    await expect(fetchLatestDecisionBoardReport("ENTRY")).resolves.toEqual(
      validThird,
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const secondUrl = new URL(String(fetchMock.mock.calls[1]?.[0]));
    const thirdUrl = new URL(String(fetchMock.mock.calls[2]?.[0]));
    expect(secondUrl.searchParams.get("or")).toContain('run_id.lt."entry-run"');
    expect(thirdUrl.searchParams.get("or")).toContain('run_id.lt."middle-run"');
  });

  it("derives a Decision cursor from an all-malformed emitted page", async () => {
    const invalidFirst = decisionRow({ tickers: ["PRIVATE.NAS"] });
    const invalidLookahead = decisionRow({
      report_key: `2026/08/2026-08-05.decision-board.entry.lookahead-run.${DIGEST_B}.json`,
      report_date: "2026-08-05",
      run_id: "lookahead-run",
      idempotency_key: `sha256:${DIGEST_B}`,
      decision_created_at: "2026-08-05T01:00:05Z",
      tickers: ["PRIVATE.NAS"],
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response([invalidFirst, invalidLookahead]),
    );

    const page = await fetchReportIndexPage({
      type: "decision-board",
      runKind: "ENTRY",
      limit: 1,
      lookahead: true,
    });

    expect(page.items).toEqual([]);
    expect(page.fetchedCount).toBe(1);
    expect(page.hasMore).toBe(true);
    expect(page.nextCursor).toMatchObject({
      decision_created_at: invalidFirst.decision_created_at,
      run_id: invalidFirst.run_id,
      report_key: invalidFirst.report_key,
      bucket_id: invalidFirst.bucket_id,
    });
  });

  it("exhausts bounded latest pages when every Decision row is invalid", async () => {
    const invalidFirst = decisionRow({ tickers: ["PRIVATE.NAS"] });
    const invalidLast = decisionRow({
      report_key: `2026/08/2026-08-05.decision-board.entry.last-run.${DIGEST_B}.json`,
      report_date: "2026-08-05",
      run_id: "last-run",
      idempotency_key: `sha256:${DIGEST_B}`,
      decision_created_at: "2026-08-05T01:00:05Z",
      tickers: ["PRIVATE.NAS"],
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response([invalidFirst, invalidLast]))
      .mockResolvedValueOnce(response([invalidLast]));

    await expect(fetchLatestDecisionBoardReport("ENTRY")).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
