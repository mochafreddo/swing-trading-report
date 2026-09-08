import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

test("live disposable review writes survive refresh and preserve correction lineage", async ({
  page,
  context,
  request,
}) => {
  test.setTimeout(120000);
  const external: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (
      url.origin !== "http://127.0.0.1:43317" ||
      /toss|notification|telegram|slack|supabase/iu.test(url.href)
    ) {
      external.push(url.href);
      await route.abort();
    } else await route.continue();
  });
  const anonymous = await request.post("/api/portfolio-review-fixture", {
    data: {
      command: "compile",
      request_id: randomUUID(),
      run_id: randomUUID(),
    },
    headers: { Origin: "http://127.0.0.1:43317" },
  });
  expect(anonymous.status()).toBe(401);
  await page.goto("/login?next=%2Ftoday");
  await page.getByLabel("Username", { exact: true }).fill("fixture-admin");
  await page.getByLabel("Password", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: /sign in/i }).click();
  const panel = page.locator("#stored-review");
  await expect(panel).toContainText("EMPTY");
  await expect(panel).toContainText("PRIMARY 관측");
  async function runId() {
    return (await panel.locator("code").last().textContent())!;
  }
  const firstRun = await runId();
  const command = {
    command: "compile",
    request_id: randomUUID(),
    run_id: firstRun,
  };
  const headers = { Origin: "http://127.0.0.1:43317" };
  const beforeAuth = await context.request.post(
    "/api/portfolio-review-fixture",
    { data: command, headers: { Origin: "https://untrusted.invalid" } },
  );
  expect([401, 403]).toContain(beforeAuth.status());
  const first = await context.request.post("/api/portfolio-review-fixture", {
    data: command,
    headers,
  });
  expect(await first.json()).toEqual({ ok: true, duplicate: false });
  const retry = await context.request.post("/api/portfolio-review-fixture", {
    data: command,
    headers,
  });
  expect(await retry.json()).toEqual({ ok: true, duplicate: true });
  const stale = await context.request.post("/api/portfolio-review-fixture", {
    data: { ...command, request_id: randomUUID() },
    headers,
  });
  expect(stale.status()).toBe(409);
  await page.reload();
  await expect(panel).toContainText(command.request_id);
  const blockButton = page.getByRole("button", {
    name: "근거 부족 검토 저장",
    exact: true,
  });
  await blockButton.focus();
  await blockButton.press("Enter");
  await expect(panel).toContainText("검토 차단");
  await page
    .getByRole("button", { name: "합성 입력으로 검토 저장", exact: true })
    .click();
  await expect(panel).not.toContainText("검토 차단");
  const previousRun = await runId();
  await page
    .getByRole("button", { name: "합성 관측 정정 후 재검토", exact: true })
    .click();
  await expect.poll(runId).not.toBe(previousRun);
  await expect(panel).toContainText("정정 전 관측 2개");
  await page
    .getByRole("button", { name: "미연결 Outcome 기록", exact: true })
    .click();
  await expect(panel).toContainText("UNLINKED");
  await page
    .getByRole("button", { name: "모호한 Outcome으로 정정", exact: true })
    .click();
  await expect(panel).toContainText("AMBIGUOUS");
  await page
    .getByRole("button", {
      name: "이 합성 검토에서 아무 행동도 하지 않았음 확인",
      exact: true,
    })
    .click();
  await expect(panel).toContainText("NO_ACTION");
  await page
    .getByRole("button", { name: "저장된 검토 재검증", exact: true })
    .click();
  const verification = page.getByRole("region", { name: "검토 검증 결과" });
  await expect(verification).toContainText("REPLAY_MATCH");
  await expect(verification).toContainText(await runId());
  await expect(verification).toContainText("sha256:");
  await page
    .getByRole("button", { name: "합성 로컬 수신 확인", exact: true })
    .click();
  await expect(verification).toContainText("총 1건 · 수신 1건 · 대기 0건");
  await expect(verification).toContainText("외부 전송 0건");
  await page
    .getByRole("button", { name: "합성 로컬 수신 확인", exact: true })
    .click();
  await expect(verification).toContainText("이번 요청으로 0건");
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.reload();
    await expect(panel).toContainText("NO_ACTION");
    await expect(verification).toHaveCount(0);
    await page
      .getByRole("button", { name: "합성 로컬 수신 확인", exact: true })
      .click();
    await expect(verification).toContainText("총 1건 · 수신 1건 · 대기 0건");
    const summary = panel.locator("summary");
    await expect(summary).toBeVisible();
    await summary.focus();
    await summary.press("Enter");
    await expect(panel.locator("details")).toHaveAttribute("open", "");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await panel.screenshot({
      path: `test-results/portfolio-live-${width}.png`,
    });
    await page
      .getByRole("group", { name: "합성 입력 → 검토 → Outcome 직접 사용" })
      .screenshot({
        path: `test-results/portfolio-live-controls-${width}.png`,
      });
    const html = await page.content();
    for (const sentinel of [
      "Synthetic PRIMARY source",
      "observed_value",
      "holding_document",
      "source_document",
      "synthetic-review-only",
    ])
      expect(html).not.toContain(sentinel);
  }
  await page.route("**/api/portfolio-review-fixture", (route) => route.abort());
  await page
    .getByRole("button", { name: "미연결 Outcome 기록", exact: true })
    .click();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "처리 결과를 확인하지 못했습니다" }),
  ).toBeVisible();
  await expect(panel).toContainText("NO_ACTION");
  await page.unroute("**/api/portfolio-review-fixture");
  await page.goto("/today?stored=stale#stored-review");
  await expect(panel).toContainText("STALE");
  await expect(
    page.getByRole("button", { name: "합성 입력으로 검토 저장", exact: true }),
  ).toHaveCount(0);
  await page.goto("/today?stored=error#stored-review");
  await expect(panel).toContainText("UNAVAILABLE");
  expect(external).toEqual([]);
  expect(errors).toEqual([]);
});
