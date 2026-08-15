import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { NextRequest } from "next/server";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/env.server", () => ({
  getSupabaseEnv: vi.fn(() => ({
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_API_KEY: "synthetic-key",
    SUPABASE_REPORTS_BUCKET: "reports",
    REPORT_RETENTION_DAYS: 30,
  })),
}));
vi.mock("@/lib/admin-auth", () => ({
  AdminAuthError: class extends Error {},
  requireAdminAuth: vi.fn(async () => undefined),
}));
vi.mock("@/lib/same-origin", () => ({
  SameOriginError: class extends Error {},
  assertSameOrigin: vi.fn(() => undefined),
}));
vi.mock("@/lib/local-request-guard", () => ({
  LocalRequestGuardError: class extends Error {},
  assertLocalRequest: vi.fn(() => undefined),
}));
vi.mock("@/lib/supabase-admin", () => ({
  SupabaseApiError: class extends Error {},
  downloadStorageBytes: vi.fn(),
  downloadStorageJson: vi.fn(),
  fetchReportIndexEntry: vi.fn(),
}));

import { GET } from "@/app/api/reports/detail/route";
import { DecisionBoardDetail } from "@/components/reports/decision-board-detail";
import type { DecisionBoardEnvelopeV0 } from "@/lib/decision-board-schema";
import {
  downloadStorageBytes,
  fetchReportIndexEntry,
} from "@/lib/supabase-admin";

const FIXTURE_PATH = resolve(
  process.cwd(),
  "../tests/fixtures/decision_board/published-entry.json",
);
const DECISION_DIGEST = "e".repeat(64);
const DECISION_KEY =
  "2026/08/2026-08-06.decision-board.entry." +
  `entry-2026-08-06T010000Z.${DECISION_DIGEST}.json`;

function sentinel(...parts: string[]): string {
  return parts.join("-");
}

const SENTINELS = {
  account_id: "acct-private-58QX-sentinel",
  account_number: "account-number-4901-7713-sentinel",
  quantity: "quantity-9137-123456-sentinel",
  entry_price: "entry-price-8123-4567-sentinel",
  pnl: "pnl-minus-7719-sentinel",
  notes: "notes-private-M7ZP-sentinel",
  tags: "tag-private-Q4KC-sentinel",
  toss_secret: sentinel("toss", "secret", "H8NW", "sentinel"),
  supabase_secret: sentinel("supabase", "secret", "R2DM", "sentinel"),
  api_secret: sentinel("api", "secret", "V6TJ", "sentinel"),
  absolute_path: "/Users/private/decision-board-S5GA-sentinel.json",
  provider_exception: "provider-exception-J9UX-sentinel",
  traceback: "Traceback-private-P3LF-sentinel",
  raw_article: "raw-article-private-C7VB-sentinel",
  private_url: "http://127.0.0.1/private-url-N4RY-sentinel",
  local_url: "http://research.local/local-url-K2WT-sentinel",
} as const;

function fixture(): DecisionBoardEnvelopeV0 & {
  metadata?: Record<string, unknown>;
} {
  return JSON.parse(
    readFileSync(FIXTURE_PATH, "utf8"),
  ) as DecisionBoardEnvelopeV0 & {
    metadata?: Record<string, unknown>;
  };
}

function mockIndex(): void {
  vi.mocked(fetchReportIndexEntry).mockResolvedValueOnce({
    bucket_id: "reports",
    report_key: DECISION_KEY,
    report_type: "decision-board",
    report_date: "2026-08-06",
    duplicate_index: 0,
    generated_at: null,
    summary: null,
    tickers: [],
    tickers_hydrated: false,
    run_kind: "ENTRY",
    run_id: "entry-2026-08-06T010000Z",
    idempotency_key: `sha256:${DECISION_DIGEST}`,
    decision_created_at: "2026-08-06T01:00:05Z",
  });
}

function request(): NextRequest {
  return new NextRequest(
    `http://localhost:55300/api/reports/detail?key=${encodeURIComponent(DECISION_KEY)}`,
  );
}

function assertNoSentinels(boundary: string, value: unknown): void {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const folded = text.toLocaleLowerCase("en-US");
  const normalized = folded.replace(/[^a-z0-9]/g, "");
  for (const [label, value] of Object.entries(SENTINELS)) {
    if (folded.includes(value.toLocaleLowerCase("en-US"))) {
      throw new Error(`privacy leak at ${boundary}: ${label}`);
    }
    const sentinelNormalized = value
      .toLocaleLowerCase("en-US")
      .replace(/[^a-z0-9]/g, "");
    if (sentinelNormalized && normalized.includes(sentinelNormalized)) {
      throw new Error(`privacy leak at ${boundary}: ${label}`);
    }
  }
}

beforeEach(() => vi.clearAllMocks());

describe("Decision Board public privacy matrix", () => {
  it("rejects injected private route bytes and keeps valid API/raw/UI public", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const injected = fixture();
    injected.metadata = Object.fromEntries(
      Object.entries(SENTINELS).map(([label, value]) => [
        `private-${label}`,
        value,
      ]),
    );
    mockIndex();
    vi.mocked(downloadStorageBytes).mockResolvedValueOnce(
      new TextEncoder().encode(JSON.stringify(injected)),
    );

    const rejected = await GET(request());
    const rejection = await rejected.json();
    expect(rejected.status).toBe(422);
    assertNoSentinels("Web API rejection", rejection);
    assertNoSentinels("Web route logs", warn.mock.calls);

    const valid = fixture();
    mockIndex();
    vi.mocked(downloadStorageBytes).mockResolvedValueOnce(
      new TextEncoder().encode(JSON.stringify(valid)),
    );
    const response = await GET(request());
    const payload = (await response.json()) as {
      report: DecisionBoardEnvelopeV0;
    };
    expect(response.status).toBe(200);
    const rawJson = JSON.stringify(payload.report, null, 2);
    const markup = renderToStaticMarkup(
      <DecisionBoardDetail
        report={payload.report}
        showRaw={true}
        rawJson={rawJson}
      />,
    );

    assertNoSentinels("Web API projection", payload.report);
    assertNoSentinels("raw JSON", rawJson);
    assertNoSentinels("UI text and link", markup);
    expect(markup).toContain("Aurora Systems");
    expect(markup).toContain("https://evidence.example/aurora-demand");
    expect(markup).toContain("Aurora demand remains strong.");
  });

  it.each(Object.entries(SENTINELS))(
    "fails safely for a normalized %s mutation",
    (label, value) => {
      const separated = [...value.toUpperCase()].join("_._");

      expect(() => assertNoSentinels("mutation boundary", separated)).toThrow(
        `privacy leak at mutation boundary: ${label}`,
      );
    },
  );
});
