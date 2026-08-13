import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

const secret = "fixture-session-secret-at-least-32-bytes";
const username = "fixture-admin";
const password = "fixture-password";
const entryKey =
  "2026/08/2026-08-06.decision-board.entry.entry-2026-08-06T010000Z." +
  "e".repeat(64) +
  ".json";
const blockedKey =
  "2026/08/2026-08-06.decision-board.entry.entry-2026-08-06T030000Z." +
  "0".repeat(64) +
  ".json";
const invalidKey =
  "2026/08/2026-08-06.decision-board.entry.entry-invalid-fixture." +
  "c".repeat(64) +
  ".json";
const holdingKey =
  "2026/08/2026-08-06.decision-board.holding.holding-2026-08-06T020000Z." +
  "f".repeat(64) +
  ".json";

const fixture = (name: string) =>
  JSON.parse(
    readFileSync(
      resolve(process.cwd(), `../tests/fixtures/decision_board/${name}`),
      "utf8",
    ),
  ) as Record<string, unknown>;

const entry = fixture("published-entry.json");
const holding = fixture("published-holding.json");
const blocked = fixture("blocked.json");

function base64url(value: string | Buffer): string {
  return Buffer.from(value).toString("base64url");
}

function sessionToken(): string {
  const credentialVersion = createHmac("sha256", secret)
    .update(`${username}\0${password}`)
    .digest("base64url");
  const payload = base64url(
    JSON.stringify({
      v: "v1",
      exp: Math.floor(Date.now() / 1000) + 3600,
      nonce: "fixture-nonce",
      cv: credentialVersion,
    }),
  );
  return `${payload}.${createHmac("sha256", secret).update(payload).digest("base64url")}`;
}

const listItem = (
  key: string,
  runKind: "ENTRY" | "HOLDING",
  runId: string,
) => ({
  key,
  bucketId: "reports",
  type: "decision-board",
  reportDate: "2026-08-06",
  duplicateIndex: 0,
  runKind,
  runId,
});

test("fixture-only /reports Decision Board journey", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: "sab_admin_session",
      value: sessionToken(),
      url: "http://127.0.0.1:43117",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);

  const unexpectedRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      url.origin !== "http://127.0.0.1:43117" ||
      /toss|order|notification|telegram|slack|supabase/iu.test(url.href)
    ) {
      unexpectedRequests.push(url.href);
    }
  });

  await page.route("**/api/reports/decision-board-journal", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        state: "AVAILABLE",
        records: [
          {
            schema_version: "decision-board.v0",
            run_id: "holding-slot-stale",
            run_kind: "HOLDING",
            status: "STALE_INCOMPLETE",
            expected_at: "2026-08-11T01:00:00Z",
            started_at: "2026-08-11T01:00:01Z",
            terminal_at: "2026-08-11T02:00:00Z",
            grace_seconds: 60,
            stale_seconds: 300,
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
      }),
    }),
  );
  await page.route("**/api/reports?**", (route) => {
    const url = new URL(route.request().url());
    const isHolding = url.searchParams.get("runKind") === "HOLDING";
    const items = isHolding
      ? [listItem(holdingKey, "HOLDING", String(holding.run_id))]
      : [
          listItem(entryKey, "ENTRY", String(entry.run_id)),
          listItem(blockedKey, "ENTRY", String(blocked.run_id)),
          listItem(invalidKey, "ENTRY", "entry-invalid-fixture"),
        ];
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items,
        total: items.length,
        searched: 0,
        searchWindow: 100,
        truncated: false,
        warnings: [],
      }),
    });
  });
  await page.route("**/api/reports/detail?**", (route) => {
    const key = new URL(route.request().url()).searchParams.get("key");
    if (key === invalidKey) {
      return route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({
          error: "Decision Board report failed validation",
          code: "invalid_decision_board_report",
        }),
      });
    }
    const report =
      key === holdingKey ? holding : key === blockedKey ? blocked : entry;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ key, bucketId: "reports", report }),
    });
  });

  await page.goto("/reports?type=decision-board&runKind=ENTRY");
  await page.getByRole("button", { name: "새로고침" }).click();
  await page.getByRole("button", { name: /entry-2026-08-06T010000Z/ }).click();
  await expect(page.getByText("AUR.NAS")).toBeVisible();
  const evidence = page.getByRole("link", { name: "Aurora demand update" });
  await expect(evidence).toHaveAttribute(
    "href",
    "https://evidence.example/aurora-demand",
  );
  await expect(evidence).toHaveAttribute("rel", "noopener noreferrer");
  await expect(evidence.locator("..")).toContainText("Synthetic Wire");
  await expect(evidence.locator("..")).toContainText("WITHIN_POLICY");

  await page.getByRole("button", { name: /entry-2026-08-06T030000Z/ }).click();
  await expect(page.getByText("Shared issues")).toBeVisible();
  await expect(page.getByText("IDENTITY_UNRESOLVED")).toBeVisible();

  await page.getByRole("button", { name: /entry-invalid-fixture/ }).click();
  await expect(
    page.getByText("Decision Board report failed validation"),
  ).toBeVisible();

  await page.locator('select[name="runKind"]').selectOption("HOLDING");
  await page
    .getByRole("button", { name: /holding-2026-08-06T020000Z/ })
    .click();
  await expect(page.getByText("ELM.NYS")).toBeVisible();
  await expect(page.getByText("SELL", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Local shadow run warning")).toContainText(
    "STALE_INCOMPLETE",
  );
  await expect(page.locator('[data-order-action="true"]')).toHaveCount(0);
  await expect(page.getByRole("button", { name: /order|notify/i })).toHaveCount(
    0,
  );
  expect(unexpectedRequests).toEqual([]);
});
