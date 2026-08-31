import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));

import type { DecisionBoardEnvelopeV0 } from "@/lib/decision-board-schema";
import {
  buildTodayBoardViewModel,
  TodayDecisionBoard,
  type TodayLaneSnapshot,
} from "@/components/today-decision-board";

const DIGEST = `sha256:${"a".repeat(64)}`;

function instrument(ticker: string) {
  return {
    market: "US" as const,
    canonical_ticker: ticker,
    exchange: "NASDAQ",
    company_name: `${ticker} Corp`,
    identity_source: "fixture",
    identity_version: "v1",
  };
}

function entryReport(
  createdAt = "2026-08-31T00:00:00Z",
): DecisionBoardEnvelopeV0 {
  return {
    schema_version: "decision-board.v0",
    run_id: "entry-run",
    created_at: createdAt,
    idempotency_key: DIGEST,
    run_kind: "ENTRY",
    status: "PUBLISHED",
    issues: [],
    decision_payload: {
      run_kind: "ENTRY",
      sealed_input_hash: DIGEST,
      items: [
        {
          instrument: instrument("AVOID"),
          status: "DECIDED",
          action: "AVOID",
          issues: [],
          evidence: [],
        },
        {
          instrument: instrument("BUY"),
          status: "DECIDED",
          action: "BUY",
          issues: [],
          evidence: [
            {
              claim_id: "buy-claim",
              role: "SUPPORTING",
              source_url: "https://example.com/public-evidence",
              publisher: "Example Publisher",
              published_at: "2026-08-30T12:00:00Z",
              article_content_hash: DIGEST,
              supporting_span: "Synthetic public evidence.",
              supporting_location: {
                kind: "TEXT_OFFSETS",
                start: 0,
                end: 26,
              },
              entailment: "SUPPORTED",
              freshness: "WITHIN_POLICY",
              citation_label: "Public filing",
            },
          ],
        },
        {
          instrument: instrument("REVIEW"),
          status: "REVIEW",
          issues: [{ code: "SOURCE_GAP", message: "public" }],
          evidence: [],
        },
      ],
    },
    decision_payload_hash: DIGEST,
  };
}

function holdingReport(): DecisionBoardEnvelopeV0 {
  return {
    schema_version: "decision-board.v0",
    run_id: "holding-run",
    created_at: "2026-08-31T00:05:00Z",
    idempotency_key: DIGEST,
    run_kind: "HOLDING",
    status: "PUBLISHED",
    issues: [],
    decision_payload: {
      run_kind: "HOLDING",
      sealed_input_hash: DIGEST,
      items: [
        {
          instrument: instrument("SELL"),
          status: "DECIDED",
          action: "SELL",
          issues: [],
          evidence: [],
        },
        {
          instrument: instrument("HOLD"),
          status: "DECIDED",
          action: "HOLD",
          issues: [],
          evidence: [],
        },
      ],
    },
    decision_payload_hash: DIGEST,
  };
}

function lane(
  report: DecisionBoardEnvelopeV0,
): Extract<TodayLaneSnapshot, { report: unknown }> {
  if (report.status === "BLOCKED") {
    return {
      runKind: report.run_kind,
      state: "BLOCKED",
      report,
      reportKey: `2026/08/${report.run_kind.toLowerCase()}-report.json`,
      bucketId: "reports",
    };
  }
  return {
    runKind: report.run_kind,
    state: "PUBLISHED",
    report,
    reportKey: `2026/08/${report.run_kind.toLowerCase()}-report.json`,
    bucketId: "reports",
  };
}

describe("TodayDecisionBoard", () => {
  it("keeps every V0 source item historical and all active surfaces empty", () => {
    const model = buildTodayBoardViewModel([
      lane(holdingReport()),
      lane(entryReport()),
    ]);

    expect(model.alerts.map((item) => item.label)).toEqual([
      "FRESHNESS_UNPROVEN · NOT ACTIVE",
      "FRESHNESS_UNPROVEN · NOT ACTIVE",
    ]);
    expect(model.queue).toEqual([]);
    expect(model.holds).toEqual([]);
    expect(model.historical.map((item) => item.label)).toEqual([
      "AVOID",
      "BUY",
      "REVIEW",
      "HOLD",
      "SELL",
    ]);
    expect(
      model.historical.every(
        (item) => item.projectionStatus === "FRESHNESS_UNPROVEN · NOT ACTIVE",
      ),
    ).toBe(true);
    expect(model.actionCount).toBe(0);
    expect(model.hasLaneWarning).toBe(true);
  });

  it("keeps BLOCKED and run issues in alerts without activating advice", () => {
    const blocked: DecisionBoardEnvelopeV0 = {
      schema_version: "decision-board.v0",
      run_id: "holding-blocked",
      created_at: "2026-08-31T00:00:00Z",
      idempotency_key: DIGEST,
      run_kind: "HOLDING",
      status: "BLOCKED",
      issues: [{ code: "INPUT_GAP", message: "public" }],
    };
    const entry = entryReport();
    entry.issues.push({ code: "SOURCE_GAP", message: "public" });

    const model = buildTodayBoardViewModel([lane(entry), lane(blocked)]);

    expect(model.alerts.map((item) => item.label)).toEqual([
      "BLOCKED",
      "FRESHNESS_UNPROVEN · NOT ACTIVE",
      "Run issue",
    ]);
    expect(model.queue).toEqual([]);
    expect(model.holds).toEqual([]);
    expect(model.alerts[0]?.issueCodes).toEqual(["INPUT_GAP"]);
  });

  it("renders an exact lane deep link and does not invent unavailable fields", () => {
    const html = renderToStaticMarkup(
      createElement(TodayDecisionBoard, {
        lanes: [lane(entryReport()), lane(holdingReport())],
        journalStatus: { state: "AVAILABLE", records: [] },
      }),
    );

    expect(html).toContain("Today&#x27;s Investment Actions");
    expect(html).toContain(
      "type=decision-board&amp;runKind=HOLDING&amp;key=2026%2F08%2Fholding-report.json&amp;bucket=reports",
    );
    expect(html).toContain("FRESHNESS_UNPROVEN · NOT ACTIVE");
    expect(html).toContain("Source status: DECIDED");
    expect(html).toContain("Source action: BUY");
    expect(html).toContain("Public filing");
    expect(html).toContain("Example Publisher");
    expect(html).toContain("WITHIN_POLICY");
    expect(html).toContain("2026-08-30T12:00:00Z");
    expect(html).toContain("never infers an absolute");
    expect(html).not.toMatch(/confidence|exposure|mandate|key driver/i);
  });

  it("renders missing and BLOCKED lanes as explicit fail-closed states", () => {
    const blocked: DecisionBoardEnvelopeV0 = {
      schema_version: "decision-board.v0",
      run_id: "holding-blocked",
      created_at: "2026-08-31T00:00:00Z",
      idempotency_key: DIGEST,
      run_kind: "HOLDING",
      status: "BLOCKED",
      issues: [{ code: "INPUT_GAP", message: "public" }],
    };
    const html = renderToStaticMarkup(
      createElement(TodayDecisionBoard, {
        lanes: [{ runKind: "ENTRY", state: "MISSING" }, lane(blocked)],
        journalStatus: { state: "AVAILABLE", records: [] },
      }),
    );

    expect(html).toContain("No verified report");
    expect(html).toContain("BLOCKED");
    expect(html).toContain("INPUT_GAP");
    expect(html).toContain(
      "No verified public advice is available for this lane.",
    );
  });

  it.each([
    "2001-01-01T00:00:00Z",
    "2026-08-31T00:00:00Z",
    "2099-12-31T23:59:59Z",
  ])("does not activate decisions from created_at=%s", (createdAt) => {
    const model = buildTodayBoardViewModel([lane(entryReport(createdAt))], {
      state: "AVAILABLE",
      records: [],
    });

    expect(model.actionCount).toBe(0);
    expect(model.queue).toEqual([]);
    expect(model.holds).toEqual([]);
    expect(model.alerts.map((item) => item.label)).toEqual([
      "FRESHNESS_UNPROVEN · NOT ACTIVE",
    ]);
    expect(model.historical).toHaveLength(3);
  });

  it("puts stale journal records first without changing lane validity", () => {
    const model = buildTodayBoardViewModel([lane(entryReport())], {
      state: "AVAILABLE",
      records: [
        {
          schema_version: "decision-board.v0",
          run_id: "stale-run",
          run_kind: "ENTRY",
          expected_at: "2026-08-31T00:00:00Z",
          grace_seconds: 60,
          stale_seconds: 300,
          status: "STALE_INCOMPLETE",
          started_at: "2026-08-31T00:00:01Z",
          terminal_at: "2026-08-31T00:05:01Z",
          issues: [
            {
              code: "STALE_INCOMPLETE",
              message:
                "Started run did not reach a terminal state before its TTL.",
            },
          ],
          report_file: null,
        },
      ],
    });

    expect(model.alerts[0]).toMatchObject({
      kind: "JOURNAL_ALERT",
      label: "STALE_INCOMPLETE",
      priority: -2,
      runId: "stale-run",
      expectedAt: "2026-08-31T00:00:00Z",
    });
    expect(model.alerts[1]).toMatchObject({
      label: "FRESHNESS_UNPROVEN · NOT ACTIVE",
    });
    expect(model.hasLaneWarning).toBe(true);
    expect(model.hasJournalWarning).toBe(true);

    const html = renderToStaticMarkup(
      createElement(TodayDecisionBoard, {
        lanes: [lane(entryReport())],
        journalStatus: {
          state: "AVAILABLE",
          records: [
            {
              schema_version: "decision-board.v0",
              run_id: "stale-run",
              run_kind: "ENTRY",
              expected_at: "2026-08-31T00:00:00Z",
              grace_seconds: 60,
              stale_seconds: 300,
              status: "STALE_INCOMPLETE",
              started_at: "2026-08-31T00:00:01Z",
              terminal_at: "2026-08-31T00:05:01Z",
              issues: [
                {
                  code: "STALE_INCOMPLETE",
                  message:
                    "Started run did not reach a terminal state before its TTL.",
                },
              ],
              report_file: null,
            },
          ],
        },
      }),
    );
    expect(html).toContain("Expected slot");
    expect(html).toContain("stale-run");
    expect(html).toContain('dateTime="2026-08-31T00:00:00Z"');
  });

  it("puts unavailable journal attention ahead of freshness alerts", () => {
    const model = buildTodayBoardViewModel([lane(entryReport())], {
      state: "UNAVAILABLE",
      reason: "NOT_CONFIGURED",
      records: [],
    });

    expect(model.journalUnavailable).toBe(true);
    expect(model.hasJournalWarning).toBe(true);
    expect(model.hasLaneWarning).toBe(true);
    expect(model.alerts.map((item) => item.label)).toEqual([
      "JOURNAL UNAVAILABLE",
      "FRESHNESS_UNPROVEN · NOT ACTIVE",
    ]);

    const html = renderToStaticMarkup(
      createElement(TodayDecisionBoard, {
        lanes: [lane(entryReport())],
        journalStatus: {
          state: "UNAVAILABLE",
          reason: "NOT_CONFIGURED",
          records: [],
        },
      }),
    );
    expect(html).toContain("Attention required");
    expect(html.indexOf("JOURNAL UNAVAILABLE")).toBeLessThan(
      html.indexOf("FRESHNESS_UNPROVEN · NOT ACTIVE"),
    );
  });
});
