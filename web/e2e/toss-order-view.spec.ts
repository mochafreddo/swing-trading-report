import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import { expect, test } from "@playwright/test";

let server: ChildProcess;
let origin: string;
test.beforeEach(async ({ context, page }) => {
  // Only the synthetic test server uses this public test cookie.
  server = spawn(
    ".venv/bin/python",
    [
      "-u",
      "-c",
      [
        "from scripts.run_toss_order_view_once import OrderViewServer",
        "server = OrderViewServer({}, '2026-08-07', '2026-09-05', synthetic=True)",
        "server.session = 'synthetic-cookie'",
        "print(server.server_port, flush=True)",
        "server.serve_forever()",
      ].join("\n"),
    ],
    {
      cwd: "..",
      stdio: ["ignore", "pipe", "ignore"],
      env: {
        NODE_ENV: "test",
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        UV_CACHE_DIR: ".uv-cache",
      },
    },
  );
  const output = createInterface({ input: server.stdout! });
  const port = await Promise.race([
    output[Symbol.asyncIterator]()
      .next()
      .then((line) => line.value),
    new Promise<never>((_, reject) =>
      setTimeout(
        () => reject(new Error("SYNTHETIC_SERVER_START_TIMEOUT")),
        10000,
      ),
    ),
  ]);
  output.close();
  expect(port).toMatch(/^\d{1,5}$/);
  origin = `http://127.0.0.1:${port}`;
  await context.addCookies([
    {
      name: "toss_order_view_session",
      value: "synthetic-cookie",
      url: origin,
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
  await page.route("**/*", (route) => {
    expect(new URL(route.request().url()).origin).toBe(origin);
    return route.continue();
  });
});
test.afterEach(() => {
  server?.kill("SIGTERM");
});

test("authenticated one-shot display and memory clearing", async ({ page }) => {
  const errors: string[] = [];
  let queries = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("request", (request) => {
    if (request.method() === "POST") queries++;
  });
  await page.goto(origin);
  await expect(page).toHaveURL(`${origin}/`);
  await expect(page).toHaveTitle("토스 주문 이력 · 로컬 1회 조회");
  await expect(page.getByRole("heading")).toBeVisible();
  await expect(page.locator("#rows tr")).toHaveCount(0);
  expect(queries).toBe(0);
  const response = page.waitForResponse(`${origin}/query`);
  await page.getByRole("button", { name: "승인된 내역 1회 조회" }).focus();
  await page.keyboard.press("Enter");
  expect((await response).headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("#status")).toHaveAttribute(
    "data-state",
    "COMPLETE",
  );
  await expect(page.locator("#rows tr")).toHaveCount(3);
  await expect(
    page.getByRole("button", { name: "승인된 내역 1회 조회" }),
  ).toBeDisabled();
  await expect(page.locator("#rows")).toContainText("123.456789 USD");
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `/private/tmp/toss-live-view-synthetic-${width}.png`,
      fullPage: true,
    });
  }
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  expect(
    await page.evaluate(async () => (await indexedDB.databases()).length),
  ).toBe(0);
  await page.getByRole("button", { name: "결과 지우기" }).click();
  await expect(page.locator("#rows tr")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("#rows tr")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "승인된 내역 1회 조회" }),
  ).toBeDisabled();
  expect(queries).toBe(1);
  expect(errors).toEqual([]);
});

test("failure is terminal without retry or partial display", async ({
  page,
}) => {
  let queries = 0;
  await page.route("**/query", (route) => {
    queries++;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "FAILED", rows: [] }),
    });
  });
  await page.goto(origin);
  await page.getByRole("button", { name: "승인된 내역 1회 조회" }).click();
  await expect(page.locator("#status")).toHaveAttribute("data-state", "FAILED");
  await expect(page.locator("#status")).toBeFocused();
  await expect(page.locator("#rows tr")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "승인된 내역 1회 조회" }),
  ).toBeDisabled();
  expect(queries).toBe(1);
});

test("clear discards an in-flight response", async ({ page }) => {
  let release: () => void = () => {};
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/query", async (route) => {
    await delayed;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ state: "EMPTY", rows: [] }),
    });
  });
  await page.goto(origin);
  await page.getByRole("button", { name: "승인된 내역 1회 조회" }).click();
  await expect(page.locator("#status")).toHaveAttribute(
    "data-state",
    "LOADING",
  );
  await page.getByRole("button", { name: "결과 지우기" }).click();
  release();
  await expect(page.locator("#status")).toHaveAttribute(
    "data-state",
    "CLEARED",
  );
  await expect(page.locator("#rows tr")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "승인된 내역 1회 조회" }),
  ).toBeDisabled();
});
