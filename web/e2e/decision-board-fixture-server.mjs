import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";

const port = Number(process.argv[2]);
if (!Number.isSafeInteger(port) || port < 1024 || port > 65535) {
  throw new Error("fixture server port is invalid");
}

const fixture = (name) =>
  JSON.parse(
    readFileSync(
      new URL(`../../tests/fixtures/decision_board/${name}`, import.meta.url),
      "utf8",
    ),
  );

const canonicalJson = (value) => {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
    .join(",")}}`;
};

const payloadHash = (payload) =>
  `sha256:${createHash("sha256").update(canonicalJson(payload)).digest("hex")}`;

const entry = fixture("published-entry.json");
const holding = fixture("published-holding.json");
const blocked = fixture("blocked.json");
const invalid = structuredClone(entry);
invalid.run_id = "entry-invalid-fixture";
invalid.idempotency_key = `sha256:${"c".repeat(64)}`;
invalid.decision_payload.items[0].evidence[0].source_url =
  "https://127.0.0.1/private";
invalid.decision_payload_hash = payloadHash(invalid.decision_payload);

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

const row = (reportKey, report) => ({
  bucket_id: "reports",
  report_key: reportKey,
  report_type: "decision-board",
  report_date: "2026-08-06",
  duplicate_index: 0,
  generated_at: null,
  summary: null,
  tickers: [],
  tickers_hydrated: false,
  run_kind: report.run_kind,
  run_id: report.run_id,
  idempotency_key: report.idempotency_key,
  decision_created_at: report.created_at,
});

const indexedReports = [
  [entryKey, entry],
  [blockedKey, blocked],
  [invalidKey, invalid],
  [holdingKey, holding],
];
const rows = indexedReports.map(([key, report]) => row(key, report));
const objects = new Map(indexedReports);

function json(response, status, payload) {
  const bytes = Buffer.from(JSON.stringify(payload));
  response.statusCode = status;
  response.setHeader("content-type", "application/json");
  response.setHeader("content-length", String(bytes.length));
  response.end(bytes);
}

createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  if (request.method !== "GET") {
    json(response, 405, { error: "fixture method not allowed" });
    return;
  }
  if (url.pathname === "/health") {
    json(response, 200, { ok: true });
    return;
  }
  if (url.pathname === "/rest/v1/report_index") {
    const reportKeyFilter = url.searchParams.get("report_key");
    const runKindFilter = url.searchParams.get("run_kind");
    let selected = rows;
    if (reportKeyFilter?.startsWith("eq.")) {
      selected = selected.filter(
        (item) => item.report_key === reportKeyFilter.slice(3),
      );
    }
    if (runKindFilter?.startsWith("eq.")) {
      selected = selected.filter(
        (item) => item.run_kind === runKindFilter.slice(3),
      );
    }
    response.setHeader(
      "content-range",
      `0-${Math.max(selected.length - 1, 0)}/${selected.length}`,
    );
    json(response, 200, selected);
    return;
  }
  const storagePrefix = "/storage/v1/object/reports/";
  if (url.pathname.startsWith(storagePrefix)) {
    const key = decodeURIComponent(url.pathname.slice(storagePrefix.length));
    const report = objects.get(key);
    if (report !== undefined) {
      json(response, 200, report);
      return;
    }
  }
  json(response, 404, { error: "fixture route not found" });
}).listen(port, "127.0.0.1");
