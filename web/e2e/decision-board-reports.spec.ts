import { createHmac } from "node:crypto";

import { expect, test, type BrowserContext, type Page } from "@playwright/test";

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
const unclassifiedFixturePath =
  "../tests/fixtures/portfolio_mandate/portfolio-mandate-a2-unclassified-preview.synthetic.json";
const privateMandateFixturePath =
  "../tests/fixtures/portfolio_mandate/portfolio-mandate-private-v1-preview.synthetic.json";

test("fixture-only stored review from disposable database", async ({
  context,
  page,
}) => {
  const requests = await configureFixtureBoundary(context, page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/today#stored-review");
    const panel = page.locator("#stored-review");
    await expect(panel).toContainText("EMPTY");
    await expect(panel).toContainText("THESIS_INVALIDATED_REVIEW_REQUIRED");
    await expect(panel).toContainText("AMBIGUOUS");
    const detail = panel.locator("summary");
    await expect(detail).toBeVisible();
    await detail.focus();
    await expect(detail).toBeFocused();
    await detail.press("Enter");
    await expect(panel.locator("details")).toHaveAttribute("open", "");
    await expect(panel).toContainText("PRIMARY 관측 2개");
    await expectNoHorizontalOverflow(page);
    if (width !== 768)
      await panel.screenshot({
        path: `test-results/portfolio-r2-${width}.png`,
      });
    await page.reload();
    await expect(panel).toContainText("AMBIGUOUS");
  }
  await page.goto("/today?stored=stale#stored-review");
  await expect(page.locator("#stored-review")).toContainText("STALE");
  await expect(page.locator("#stored-review")).not.toContainText(
    "THESIS_INVALIDATED",
  );
  await page.goto("/today?stored=error#stored-review");
  await expect(page.locator("#stored-review")).toContainText("UNAVAILABLE");
  expect(errors).toEqual([]);
  expect(requests).toEqual([]);
});

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const layout = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));

  expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth);
}

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

async function configureFixtureBoundary(
  context: BrowserContext,
  page: Page,
): Promise<string[]> {
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

  return unexpectedRequests;
}

test("fixture-only order aggregate preview", async ({ context, page }) => {
  const unexpectedRequests = await configureFixtureBoundary(context, page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto("/today");
  await expect(page).toHaveURL(`${webOrigin}/today`);
  await expect(page).toHaveTitle("SAB Control Panel");
  const panel = page.locator("#order-history-preview");
  await expect(
    panel.getByRole("heading", { name: "토스 주문 이력 · 합성 미리보기" }),
  ).toBeVisible();
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await panel.getByRole("radio", { name: "정상 결과" }).check();
    await panel.getByRole("button", { name: "합성 내역 조회" }).click();
    await expect(panel.locator("tbody tr")).toHaveCount(3);
    await expect(panel).toContainText("123.456789 USD");
    await expectNoHorizontalOverflow(page);
    await panel.scrollIntoViewIfNeeded();
    await panel.screenshot({
      path: `/private/tmp/toss-order-preview-${width}.png`,
    });
    await panel.getByLabel("시작일").fill("2026-09-01");
    await panel.getByLabel("종료일").fill("2026-09-01");
    await expect(panel.locator("table")).toHaveCount(0);
    await panel.getByRole("button", { name: "합성 내역 조회" }).focus();
    await page.keyboard.press("Enter");
    await expect(panel.locator("tbody tr")).toHaveCount(1);
    await expect(panel).toContainText("2026-09-01 12:30:00");
    await panel.getByLabel("시작일").fill("2026-08-07");
    await panel.getByLabel("종료일").fill("2026-09-05");
  }
  await panel.getByLabel("시작일").fill("2026-09-06");
  await panel.getByRole("button", { name: "합성 내역 조회" }).click();
  await expect(panel.getByRole("status")).toContainText("최대 30일 범위");
  await expect(panel.getByRole("status")).toBeFocused();
  await expect(panel.getByLabel("시작일")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await panel.getByLabel("시작일").fill("2026-08-07");
  for (const [name, state] of [
    ["빈 결과", "조회 결과 없음"],
    ["페이지 미완결", "페이지 미완결 · 결과 표시 보류"],
    ["응답 오류", "검증 실패 · 결과 표시 보류"],
  ]) {
    await panel.getByRole("radio", { name, exact: true }).check();
    await panel.getByRole("button", { name: "합성 내역 조회" }).click();
    await expect(panel.getByRole("status")).toContainText(state);
    await expect(panel.locator("table")).toHaveCount(0);
  }
  await page.reload();
  await expect(panel.getByRole("status")).toContainText("조회 전");
  expect(errors).toEqual([]);
  expect(unexpectedRequests).toEqual([]);
});

test("fixture-only /reports Decision Board journey", async ({
  context,
  page,
}) => {
  const unexpectedRequests = await configureFixtureBoundary(context, page);

  await page.goto("/reports?type=decision-board&runKind=ENTRY");
  const entryListResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/reports?") &&
      response.url().includes("runKind=ENTRY"),
  );
  const entryDetailResponse = page.waitForResponse((response) =>
    response
      .url()
      .includes(`/api/reports/detail?key=${encodeURIComponent(entryKey)}`),
  );
  await page.getByRole("button", { name: "새로고침" }).click();
  await expect((await entryListResponse).status()).toBe(200);
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
  const holdingDetailResponse = page.waitForResponse((response) =>
    response
      .url()
      .includes(`/api/reports/detail?key=${encodeURIComponent(holdingKey)}`),
  );
  await page.getByRole("button", { name: "새로고침" }).click();
  await expect((await holdingListResponse).status()).toBe(200);
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

test("fixture-only /today Unclassified Queue journey", async ({
  context,
  page,
}) => {
  const unexpectedRequests = await configureFixtureBoundary(context, page);
  await page.setViewportSize({ width: 375, height: 812 });

  await page.goto("/today");
  const boardSummary = page.getByRole("region", {
    name: "Today's Investment Actions",
  });
  const queue = page.getByRole("region", { name: "Unclassified Queue" });
  const input = queue.locator("#unclassified-preview-file");

  await expect(queue).toBeVisible();
  await expect(boardSummary.locator("strong")).toHaveText("0");
  await expectNoHorizontalOverflow(page);

  await input.setInputFiles(unclassifiedFixturePath);

  await expect(queue.getByRole("status")).toContainText(
    "Local preview ready: 5 validated rows",
  );
  await expect(
    queue.locator('[aria-label="Unclassified local preview rows"] article'),
  ).toHaveCount(5);
  await expect(queue.getByText("UNCLASSIFIED · NO ADVICE")).toHaveCount(5);
  await expect(queue.getByText(/UNAPPROVED DRAFT/u)).toHaveCount(5);
  await expect(queue).toContainText("not a current, freshness-proven");
  await expect(boardSummary.locator("strong")).toHaveText("0");
  await expectNoHorizontalOverflow(page);
  await expect(
    queue.getByRole("button", {
      name: /approve|order|notify|buy|hold|sell|avoid/iu,
    }),
  ).toHaveCount(0);

  await input.setInputFiles({
    name: "invalid.synthetic.json",
    mimeType: "application/json",
    buffer: Buffer.from('{"schema_version":'),
  });
  await expect(queue.getByRole("alert")).toContainText(
    "not valid local preview JSON",
  );
  await expect(
    queue.locator('[aria-label="Unclassified local preview rows"] article'),
  ).toHaveCount(0);
  await expect(boardSummary.locator("strong")).toHaveText("0");

  await input.setInputFiles(unclassifiedFixturePath);
  await expect(
    queue.locator('[aria-label="Unclassified local preview rows"] article'),
  ).toHaveCount(5);
  await queue.getByRole("button", { name: "Clear local preview" }).click();
  await expect(queue.getByRole("status")).toContainText(
    "Local preview cleared from browser memory",
  );
  await expect(
    queue.locator('[aria-label="Unclassified local preview rows"] article'),
  ).toHaveCount(0);
  await expect(input).toHaveValue("");
  expect(unexpectedRequests).toEqual([]);
});

test("fixture-only /today private mandate memory-only journey", async ({
  context,
  page,
}) => {
  const unexpectedRequests = await configureFixtureBoundary(context, page);

  for (const viewport of [
    { width: 375, height: 812 },
    { width: 768, height: 1024 },
    { width: 1280, height: 720 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/today");
    const boardSummary = page.getByRole("region", {
      name: "Today's Investment Actions",
    });
    const queue = page.getByRole("region", { name: "Unclassified Queue" });
    const input = queue.locator("#unclassified-preview-file");

    await input.focus();
    await expect(input).toBeFocused();
    await input.setInputFiles(privateMandateFixturePath);
    await expect(queue.getByRole("status")).toContainText(
      "Local preview ready: 8 validated rows",
    );
    await expect(
      queue.locator(
        '[aria-label="Private portfolio mandate preview rows"] article',
      ),
    ).toHaveCount(8);
    await expect(queue.getByText("APPROVED · ACTIVE · LONG_TERM")).toHaveCount(
      8,
    );
    await expect(queue).toContainText("5 CORE · 3 SATELLITE");
    await expect(boardSummary.locator("strong")).toHaveText("0");
    await expect(
      queue.locator('[aria-label="Private portfolio mandate preview rows"] a'),
    ).toHaveCount(8);
    await expectNoHorizontalOverflow(page);
    await expect(
      queue.getByRole("button", {
        name: /approve|order|notify|buy|hold|sell|avoid/iu,
      }),
    ).toHaveCount(0);

    await input.setInputFiles(privateMandateFixturePath);
    await expect(
      queue.locator(
        '[aria-label="Private portfolio mandate preview rows"] article',
      ),
    ).toHaveCount(8);
    await queue.getByRole("button", { name: "Clear local preview" }).click();
    await expect(
      queue.locator(
        '[aria-label="Private portfolio mandate preview rows"] article',
      ),
    ).toHaveCount(0);
    await expect(boardSummary.locator("strong")).toHaveText("0");

    await input.setInputFiles(privateMandateFixturePath);
    await page.reload();
    await expect(
      page.locator(
        '[aria-label="Private portfolio mandate preview rows"] article',
      ),
    ).toHaveCount(0);
    await page.goto("/reports");
    await page.goto("/today");
    await expect(
      page.locator(
        '[aria-label="Private portfolio mandate preview rows"] article',
      ),
    ).toHaveCount(0);
  }

  expect(unexpectedRequests).toEqual([]);
});

test("fixture-only /today Mandate Evidence Outcome journey", async ({
  context,
  page,
}) => {
  const unexpectedRequests = await configureFixtureBoundary(context, page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  for (const viewport of [
    { width: 375, height: 812 },
    { width: 768, height: 1024 },
    { width: 1280, height: 720 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(
      "/today?dogfood=corrected-lineage#mandate-evidence-outcome",
    );
    const drilldown = page.getByRole("region", {
      name: "Mandate → Evidence → Outcome",
    });
    await expect(drilldown).toContainText("CORRECTED");
    await expect(drilldown).toContainText("PARTIALLY_EXECUTED");
    const summary = drilldown
      .locator("summary")
      .filter({ hasText: "A1 version" });
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(
      drilldown.locator('[aria-label="A1 connected review rows"] article'),
    ).toHaveCount(2);
    await expect(
      drilldown.locator('[aria-label="A1 connected review rows"]'),
    ).toContainText("ALLOCATION_REBASE_REQUIRED");
    const compositeSummary = drilldown
      .locator("summary")
      .filter({ hasText: "Long-term composite review" });
    await compositeSummary.focus();
    await page.keyboard.press("Enter");
    await expect(
      drilldown.locator(
        '[aria-label="Long-term composite review rows"] article',
      ),
    ).toHaveCount(8);
    await expect(
      drilldown.locator('[aria-label="Long-term composite review rows"]'),
    ).toContainText("THESIS INVALIDATED REVIEW REQUIRED");
    await expectNoHorizontalOverflow(page);
    await drilldown.screenshot({
      path: `/private/tmp/portfolio-a1-review-${viewport.width}.png`,
    });
  }

  const drilldown = page.getByRole("region", {
    name: "Mandate → Evidence → Outcome",
  });
  const emptyLink = drilldown.getByRole("link", { name: "Empty" });
  await emptyLink.focus();
  await expect(emptyLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(
    (url) => url.searchParams.get("dogfood") === "empty-outcome",
  );
  await expect(drilldown).toContainText("EMPTY · NO INFERENCE");
  await page.reload();
  await expect(drilldown).toContainText("No public outcome events yet");
  await expect(drilldown.getByRole("link", { name: "Empty" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await drilldown.getByRole("link", { name: "Blocked" }).click();
  await expect(drilldown).toContainText("BLOCKED · EVIDENCE_CONFLICTED");
  await expect(drilldown).toContainText("Outcome projection withheld");

  await drilldown.getByRole("link", { name: "Loading" }).click();
  await expect(drilldown.getByRole("status")).toHaveAttribute(
    "aria-busy",
    "true",
  );
  await expect(drilldown).toContainText("LOADING · FIXTURE REPLAY");

  await drilldown.getByRole("link", { name: "Stale" }).click();
  await expect(drilldown).toContainText("STALE · EVIDENCE_STALE");

  await drilldown.getByRole("link", { name: "Ambiguous" }).click();
  await expect(drilldown).toContainText("AMBIGUOUS MATCH · REVIEW ONLY");

  await drilldown.getByRole("link", { name: "Invalid contract" }).click();
  await expect(drilldown).toContainText("FIXTURE CONTRACT INVALID");

  await page.goto("/today?dogfood=unknown-case#mandate-evidence-outcome");
  await expect(drilldown).toContainText("INVALID SELECTION");
  await expect(drilldown).toContainText("No scenario was inferred");
  await expect(drilldown).not.toContainText(
    "Synthetic private correction note",
  );
  expect(unexpectedRequests).toEqual([]);
  expect(errors).toEqual([]);
});
