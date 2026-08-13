import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DecisionBoardDetail } from "@/components/reports/decision-board-detail";
import {
  projectPublicDecisionBoardReport,
  type DecisionBoardEnvelopeV0,
} from "@/lib/decision-board-schema";

const FIXTURE_PATH = resolve(
  process.cwd(),
  "../tests/fixtures/decision_board/published-entry.json",
);

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

function assertNoSentinels(boundary: string, value: unknown): void {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const folded = text.toLocaleLowerCase("en-US");
  const normalized = folded.replace(/[^a-z0-9]/g, "");
  for (const [label, sentinel] of Object.entries(SENTINELS)) {
    if (folded.includes(sentinel.toLocaleLowerCase("en-US"))) {
      throw new Error(`privacy leak at ${boundary}: ${label}`);
    }
    const sentinelNormalized = sentinel
      .toLocaleLowerCase("en-US")
      .replace(/[^a-z0-9]/g, "");
    if (sentinelNormalized && normalized.includes(sentinelNormalized)) {
      throw new Error(`privacy leak at ${boundary}: ${label}`);
    }
  }
}

describe("Decision Board public privacy matrix", () => {
  it("keeps API projection, raw JSON, UI text, and links public-only", async () => {
    const producer = JSON.parse(
      readFileSync(FIXTURE_PATH, "utf8"),
    ) as DecisionBoardEnvelopeV0 & { metadata?: Record<string, unknown> };
    producer.metadata = Object.fromEntries(
      Object.entries(SENTINELS).map(([label, sentinel]) => [
        `private-${label}`,
        sentinel,
      ]),
    );

    const projected = await projectPublicDecisionBoardReport(producer);
    const rawJson = JSON.stringify(projected, null, 2);
    const markup = renderToStaticMarkup(
      <DecisionBoardDetail
        report={projected}
        showRaw={true}
        rawJson={rawJson}
      />,
    );

    assertNoSentinels("Web API projection", projected);
    assertNoSentinels("raw JSON", rawJson);
    assertNoSentinels("UI text and link", markup);
    expect(projected).not.toHaveProperty("metadata");
    expect(markup).toContain("Aurora Systems");
    expect(markup).toContain("https://evidence.example/aurora-demand");
    expect(markup).toContain("Aurora demand remains strong.");
  });
});
