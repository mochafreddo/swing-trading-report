import { createServer } from "node:http";
import { readFileSync } from "node:fs";

const port = Number(process.argv[2]);
if (!Number.isSafeInteger(port) || port < 1024 || port > 65535) {
  throw new Error("fixture server port is invalid");
}

const entry = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/decision_board/published-entry.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const blocked = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/decision_board/blocked.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
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

const row = (reportKey, runId, idempotencyKey, createdAt) => ({
  bucket_id: "reports",
  report_key: reportKey,
  report_type: "decision-board",
  report_date: "2026-08-06",
  duplicate_index: 0,
  generated_at: createdAt,
  summary: null,
  tickers: [],
  tickers_hydrated: false,
  run_kind: "ENTRY",
  run_id: runId,
  idempotency_key: idempotencyKey,
  decision_created_at: createdAt,
});

const rows = [
  row(entryKey, entry.run_id, entry.idempotency_key, entry.created_at),
  row(blockedKey, blocked.run_id, blocked.idempotency_key, blocked.created_at),
  row(
    invalidKey,
    "entry-invalid-fixture",
    `sha256:${"c".repeat(64)}`,
    "2026-08-06T00:00:00Z",
  ),
];

createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  response.setHeader("content-type", "application/json");
  if (url.pathname === "/health") {
    response.end('{"ok":true}');
    return;
  }
  if (url.pathname === "/rest/v1/report_index") {
    const reportKeyFilter = url.searchParams.get("report_key");
    const selected = reportKeyFilter?.startsWith("eq.")
      ? rows.filter((item) => item.report_key === reportKeyFilter.slice(3))
      : rows;
    response.setHeader(
      "content-range",
      `0-${Math.max(selected.length - 1, 0)}/${selected.length}`,
    );
    response.end(JSON.stringify(selected));
    return;
  }
  if (url.pathname.endsWith(`/${entryKey}`)) {
    response.end(JSON.stringify(entry));
    return;
  }
  response.statusCode = 404;
  response.end('{"error":"fixture not found"}');
}).listen(port, "127.0.0.1");
