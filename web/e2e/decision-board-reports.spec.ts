import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

const secret = "fixture-session-secret-at-least-32-bytes";
const username = "fixture-admin";
const password = "fixture-password";
const webPort = Number(process.env.DECISION_BOARD_E2E_WEB_PORT ?? "43117");
const webOrigin = `http://127.0.0.1:${webPort}`;
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

test("fixture-only /reports Decision Board journey", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: "sab_admin_session",
      value: sessionToken(),
      url: webOrigin,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);

  const unexpectedRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      url.origin !== webOrigin ||
      /toss|order|notification|telegram|slack|supabase/iu.test(url.href)
    ) {
      unexpectedRequests.push(url.href);
    }
  });

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (
      url.origin !== webOrigin ||
      /toss|order|notification|telegram|slack|supabase/iu.test(url.href)
    ) {
      unexpectedRequests.push(url.href);
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
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
  await page.goto("/reports?type=decision-board&runKind=ENTRY");
  const entryListResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/reports?") &&
      response.url().includes("runKind=ENTRY"),
  );
  await page.getByRole("button", { name: "새로고침" }).click();
  await expect((await entryListResponse).status()).toBe(200);
  const entryDetailResponse = page.waitForResponse((response) =>
    response
      .url()
      .includes(`/api/reports/detail?key=${encodeURIComponent(entryKey)}`),
  );
  await page.getByRole("button", { name: /entry-2026-08-06T010000Z/ }).click();
  await expect((await entryDetailResponse).status()).toBe(200);
  await expect(page.getByText("AUR.NAS")).toBeVisible();
  const evidence = page.getByRole("link", { name: "Aurora demand update" });
  await expect(evidence).toHaveAttribute(
    "href",
    "https://evidence.example/aurora-demand",
  );
  await expect(evidence).toHaveAttribute("rel", "noopener noreferrer");
  await expect(evidence.locator("..")).toContainText("Synthetic Wire");
  await expect(evidence.locator("..")).toContainText("WITHIN_POLICY");
  await expect(evidence.locator("..")).toContainText("SUPPORTED");
  await expect(evidence.locator("..")).toContainText(
    "Aurora demand remains strong.",
  );

  const blockedDetailResponse = page.waitForResponse((response) =>
    response
      .url()
      .includes(`/api/reports/detail?key=${encodeURIComponent(blockedKey)}`),
  );
  await page.getByRole("button", { name: /entry-2026-08-06T030000Z/ }).click();
  await expect((await blockedDetailResponse).status()).toBe(200);
  await expect(page.getByText("Shared issues")).toBeVisible();
  await expect(page.getByText("IDENTITY_UNRESOLVED")).toBeVisible();

  const invalidDetailResponse = page.waitForResponse((response) =>
    response
      .url()
      .includes(`/api/reports/detail?key=${encodeURIComponent(invalidKey)}`),
  );
  await page.getByRole("button", { name: /entry-invalid-fixture/ }).click();
  await expect((await invalidDetailResponse).status()).toBe(422);
  await expect(
    page.getByText("Decision Board report failed validation"),
  ).toBeVisible();
  await expect(page).toHaveURL(
    (url) => url.searchParams.get("key") === invalidKey,
  );
  await expect(page.locator("#report-raw-json")).toHaveCount(0);
  await expect(page.getByText("https://127.0.0.1/private")).toHaveCount(0);

  await page.goto("/reports?type=decision-board&runKind=HOLDING");
  await expect(page.locator('select[name="runKind"]')).toHaveValue("HOLDING");
  const holdingListResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/reports?") &&
      response.url().includes("runKind=HOLDING"),
  );
  await page.getByRole("button", { name: "새로고침" }).click();
  await expect((await holdingListResponse).status()).toBe(200);
  const holdingDetailResponse = page.waitForResponse((response) =>
    response
      .url()
      .includes(`/api/reports/detail?key=${encodeURIComponent(holdingKey)}`),
  );
  await page
    .getByRole("button", { name: /holding-2026-08-06T020000Z/ })
    .click();
  await expect((await holdingDetailResponse).status()).toBe(200);
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
