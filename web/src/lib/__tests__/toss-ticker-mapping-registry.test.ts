import { afterEach, describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";

import { loadReviewedTossTickerMappingsFromEnv } from "@/lib/toss/ticker-mapping-registry";

const APPROVED_MAPPING_B64 =
  "eyJzY2hlbWFfdmVyc2lvbiI6InRvc3Mtc3luYy1yZXZpZXdlZC1tYXBwaW5nLnYxIiwicmV2aWV3X3N0YXRlIjoiQVBQUk9WRUQiLCJhcHByb3ZlZF9ieSI6InVzZXIiLCJhcHByb3ZlZF9hdCI6IjIwMjYtMDgtMTlUMDA6MDA6MDAuMDAwWiIsIm1hcHBpbmdzIjpbeyJzeW1ib2wiOiJNU0ZUIiwicmVwb190aWNrZXIiOiJNU0ZULk5BUyIsInNvdXJjZSI6InBvbHlnb25fcmVmZXJlbmNlIiwicHJpbWFyeV9leGNoYW5nZV9taWMiOiJYTkFTIn1dfQ==";
const APPROVED_MAPPING_SHA256 =
  "sha256:3e5d54c3ace4f5b34015d02484caca420f9e2ea51989d1c4a9448e5dbec7085f";

function configurePayload(payload: unknown): void {
  configureBytes(Buffer.from(JSON.stringify(payload)));
}

function configureBytes(bytes: Buffer): void {
  vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_B64", bytes.toString("base64"));
  vi.stubEnv(
    "TOSS_SYNC_REVIEWED_MAPPING_SHA256",
    `sha256:${createHash("sha256").update(bytes).digest("hex")}`,
  );
}

describe("reviewed Toss ticker mapping registry", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("loads an externally hash-bound approved mapping", () => {
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_B64", APPROVED_MAPPING_B64);
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_SHA256", APPROVED_MAPPING_SHA256);

    expect(loadReviewedTossTickerMappingsFromEnv(["MSFT"])).toEqual([
      { ticker: "MSFT.NAS" },
    ]);
  });

  it("stays disabled when neither registry setting is configured", () => {
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_B64", "");
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_SHA256", "");

    expect(loadReviewedTossTickerMappingsFromEnv(["MSFT"])).toEqual([]);
  });

  it.each([
    ["payload only", APPROVED_MAPPING_B64, ""],
    ["digest only", "", APPROVED_MAPPING_SHA256],
  ])("rejects a half-configured registry: %s", (_label, encoded, digest) => {
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_B64", encoded);
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_SHA256", digest);

    expect(() => loadReviewedTossTickerMappingsFromEnv(["MSFT"])).toThrow(
      "must be configured together",
    );
  });

  it.each([
    ["malformed digest", "sha256:not-a-digest", "must be a sha256 digest"],
    ["digest mismatch", `sha256:${"0".repeat(64)}`, "digest mismatch"],
  ])("rejects an invalid hash binding: %s", (_label, digest, message) => {
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_B64", APPROVED_MAPPING_B64);
    vi.stubEnv("TOSS_SYNC_REVIEWED_MAPPING_SHA256", digest);

    expect(() => loadReviewedTossTickerMappingsFromEnv(["MSFT"])).toThrow(
      message,
    );
  });

  it("rejects self-declared mapping data without approved metadata", () => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "DRAFT",
      approved_by: "automation",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [],
    });

    expect(() => loadReviewedTossTickerMappingsFromEnv([])).toThrow(
      "approval metadata is invalid",
    );
  });

  it("rejects duplicate symbols instead of allowing a later venue to win", () => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [
        {
          symbol: "ABC",
          repo_ticker: "ABC.NAS",
          source: "local_buy_reports",
        },
        {
          symbol: "ABC",
          repo_ticker: "ABC.NYS",
          source: "local_buy_reports",
        },
      ],
    });

    expect(() => loadReviewedTossTickerMappingsFromEnv(["ABC"])).toThrow(
      "duplicate symbol",
    );
  });

  it("rejects duplicate JSON keys before parsing approval metadata", () => {
    configureBytes(
      Buffer.from(
        '{"schema_version":"toss-sync-reviewed-mapping.v1","review_state":"DRAFT","review_state":"APPROVED","approved_by":"user","approved_at":"2026-08-19T00:00:00.000Z","mappings":[]}',
      ),
    );

    expect(() => loadReviewedTossTickerMappingsFromEnv([])).toThrow(
      "valid strict JSON",
    );
  });

  it("rejects mapping rows without an approved evidence source", () => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [
        {
          symbol: "MSFT",
          repo_ticker: "MSFT.NAS",
          source: "manual_guess",
        },
      ],
    });

    expect(() => loadReviewedTossTickerMappingsFromEnv(["MSFT"])).toThrow(
      "evidence source",
    );
  });

  it("rejects operation-approval fields outside the mapping schema", () => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      holdings_apply: true,
      mappings: [],
    });

    expect(() => loadReviewedTossTickerMappingsFromEnv([])).toThrow(
      "unsupported field",
    );
  });

  it("rejects venue metadata that conflicts with a local-report ticker", () => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [
        {
          symbol: "MSFT",
          repo_ticker: "MSFT.NAS",
          source: "local_buy_reports",
          primary_exchange_mic: "XNYS",
        },
      ],
    });

    expect(() => loadReviewedTossTickerMappingsFromEnv(["MSFT"])).toThrow(
      "MIC and suffix",
    );
  });

  it.each([
    [
      "symbol and ticker mismatch",
      {
        symbol: "MSFT",
        repo_ticker: "AAPL.NAS",
        source: "local_buy_reports",
      },
      "symbol and ticker do not match",
    ],
    [
      "Polygon row without MIC",
      {
        symbol: "MSFT",
        repo_ticker: "MSFT.NAS",
        source: "polygon_reference",
      },
      "MIC and suffix",
    ],
    [
      "incomplete row",
      { symbol: "MSFT", source: "local_buy_reports" },
      "row is incomplete",
    ],
  ])("rejects invalid mapping rows: %s", (_label, mapping, message) => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [mapping],
    });

    expect(() => loadReviewedTossTickerMappingsFromEnv(["MSFT"])).toThrow(
      message,
    );
  });

  it("accepts reviewed local NYSE and Polygon AMEX mappings", () => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [
        {
          symbol: "VRT",
          repo_ticker: "VRT.NYS",
          source: "local_buy_reports",
        },
        {
          symbol: "XYZ",
          repo_ticker: "XYZ.AMS",
          source: "polygon_reference",
          primary_exchange_mic: "XASE",
        },
      ],
    });

    expect(loadReviewedTossTickerMappingsFromEnv(["XYZ", "VRT"])).toEqual([
      { ticker: "VRT.NYS" },
      { ticker: "XYZ.AMS" },
    ]);
  });

  it.each([
    ["invalid symbol", "BAD$", "BAD$.NAS"],
    ["invalid ticker", "MSFT", "MSFT$.NAS"],
  ])("rejects malformed ticker syntax: %s", (_label, symbol, repoTicker) => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [
        {
          symbol,
          repo_ticker: repoTicker,
          source: "local_buy_reports",
        },
      ],
    });

    expect(() => loadReviewedTossTickerMappingsFromEnv([symbol])).toThrow(
      "symbol and ticker do not match",
    );
  });

  it("canonicalizes a valid class-share symbol", () => {
    configurePayload({
      schema_version: "toss-sync-reviewed-mapping.v1",
      review_state: "APPROVED",
      approved_by: "user",
      approved_at: "2026-08-19T00:00:00.000Z",
      mappings: [
        {
          symbol: "BRK/B",
          repo_ticker: "BRK.B.NYS",
          source: "local_buy_reports",
        },
      ],
    });

    expect(loadReviewedTossTickerMappingsFromEnv(["BRK/B"])).toEqual([
      { ticker: "BRK.B.NYS" },
    ]);
  });
});
