// Memory-only browser controller. Never trace, screenshot or print page content.
import { createInterface } from "node:readline";
import { chromium } from "@playwright/test";

const input = createInterface({ input: process.stdin });
const lines = input[Symbol.asyncIterator]();
let browser;
try {
  const initial = await lines.next();
  const config = JSON.parse(initial.value);
  const origin = new URL(config.origin);
  if (origin.hostname !== "127.0.0.1" || origin.protocol !== "http:") {
    throw new Error("INVALID_LOOPBACK");
  }
  browser = await chromium.launch({
    headless: false,
    ...(process.platform === "darwin" ? { channel: "chrome" } : {}),
    args: ["--disk-cache-size=0", "--media-cache-size=0", "--disable-breakpad"],
  });
  const context = await browser.newContext({ serviceWorkers: "block" });
  await context.addCookies([
    {
      name: "toss_order_view_session",
      value: config.session,
      url: config.origin,
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
  config.session = "";
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    return url.origin === origin.origin &&
      ["/", "/query"].includes(url.pathname)
      ? route.continue()
      : route.abort();
  });
  const page = await context.newPage();
  browser.on("disconnected", () => input.close());
  page.on("close", () => {
    void browser.close();
  });
  await page.goto(origin.origin, { waitUntil: "load" });
  process.stdout.write("BROWSER_READY\n");
  let queried = false;
  for await (const line of lines) {
    if (line === "CLOSE") break;
    if (line !== "QUERY" || queried) continue;
    queried = true;
    const button = page.getByRole("button", { name: "승인된 내역 1회 조회" });
    // A user may already have clicked in the visible window; never click twice.
    if (!(await button.isDisabled())) await button.click();
    await page.waitForFunction(
      () =>
        ["COMPLETE", "EMPTY", "FAILED", "CLEARED"].includes(
          document.getElementById("status").dataset.state,
        ),
      undefined,
      { timeout: 35000 },
    );
    const state = await page.locator("#status").getAttribute("data-state");
    process.stdout.write(
      ["COMPLETE", "EMPTY"].includes(state)
        ? "DISPLAY_CONFIRMED\n"
        : "DISPLAY_NOT_COMPLETE\n",
    );
  }
  await browser.close();
} catch {
  process.stdout.write("LOCAL_BROWSER_FAILED\n");
  if (browser) await browser.close();
  process.exitCode = 1;
}
