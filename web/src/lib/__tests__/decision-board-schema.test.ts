import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  brokerSnapshotV0Schema,
  DecisionBoardIntegrityError,
  DecisionBoardJsonValueError,
  canonicalDecisionPayloadBytesV0,
  claimValidationV0Schema,
  decisionPayloadHashV0,
  decisionBoardEnvelopeV0Schema,
  parseDecisionBoardReportStructure,
  parseVerifiedDecisionBoardReport,
  runJournalV0Schema,
  safeParseDecisionBoardReportStructure,
  safeParseVerifiedDecisionBoardReport,
} from "@/lib/decision-board-schema";

const fixturePath = (name: string) =>
  fileURLToPath(
    new URL(
      `../../../../tests/fixtures/decision_board/${name}`,
      import.meta.url,
    ),
  );

const loadFixture = (name: string): unknown =>
  JSON.parse(readFileSync(fixturePath(name), "utf8"));

function canonicalJsonUnchecked(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJsonUnchecked).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map(
      (key) => `${JSON.stringify(key)}:${canonicalJsonUnchecked(record[key])}`,
    )
    .join(",")}}`;
}

const uncheckedPayloadHash = (payload: unknown): string =>
  `sha256:${createHash("sha256").update(canonicalJsonUnchecked(payload)).digest("hex")}`;

type MutablePublishedReport = {
  status: string;
  issues: unknown[];
  metadata?: unknown;
  decision_payload: {
    items: Array<{
      action?: string;
      evidence: Array<{ freshness: string; source_url: string }>;
    }>;
  };
  decision_payload_hash: string;
};

const loadPublishedFixture = (): MutablePublishedReport =>
  loadFixture("published-entry.json") as MutablePublishedReport;
const publicUrlCorpus = loadFixture("public-evidence-url-corpus.json") as {
  valid: string[];
  invalid: string[];
};

const validClaim = () => {
  const fixture = loadPublishedFixture();
  const instrument = (
    fixture.decision_payload.items[0] as unknown as {
      instrument: Record<string, unknown>;
    }
  ).instrument;
  return {
    claim_id: "claim-synthetic",
    instrument,
    source_url: "https://example.com/synthetic-claim",
    publisher: "Synthetic Publisher",
    published_at: "2026-08-06T00:30:00Z",
    article_content_hash: `sha256:${"d".repeat(64)}`,
    supporting_span: "Synthetic exact supporting text.",
    supporting_location: {
      kind: "TEXT_OFFSETS",
      start: 20,
      end: 21,
    },
    verifier_version: "fixture-verifier-v0",
    entailment: "SUPPORTED",
  };
};

describe("Decision Board V0 schema", () => {
  it("mirrors the strict RunJournalV0 runtime contract", () => {
    const started = {
      schema_version: "decision-board.v0",
      run_id: "entry-slot-001",
      run_kind: "ENTRY",
      status: "STARTED",
      expected_at: "2026-08-11T01:00:00Z",
      started_at: "2026-08-11T01:00:01Z",
      terminal_at: null,
      grace_seconds: 60,
      stale_seconds: 300,
      issues: [],
      report_file: null,
    };
    expect(runJournalV0Schema.safeParse(started).success).toBe(true);
    expect(
      runJournalV0Schema.safeParse({ ...started, run_id: "../private" })
        .success,
    ).toBe(false);
    expect(
      runJournalV0Schema.safeParse({ ...started, run_id: "abc\n" }).success,
    ).toBe(false);
    expect(
      runJournalV0Schema.safeParse({
        ...started,
        expected_at: "2026-08-11T10:00:00+09:00",
      }).success,
    ).toBe(false);
    expect(
      runJournalV0Schema.safeParse({
        ...started,
        expected_at: "2026-08-11T01:00:00.1Z",
      }).success,
    ).toBe(false);
    expect(
      runJournalV0Schema.safeParse({
        ...started,
        started_at: "2026-08-11T00:59:59Z",
      }).success,
    ).toBe(false);
    expect(
      runJournalV0Schema.safeParse({
        ...started,
        status: "PUBLISHED",
        terminal_at: "2026-08-11T01:00:02Z",
      }).success,
    ).toBe(false);
    expect(
      runJournalV0Schema.safeParse({
        ...started,
        issues: [
          {
            code: "MISSED_EXPECTED",
            message: "Expected run did not start before its grace deadline.",
            metadata: { private: true },
          },
        ],
      }).success,
    ).toBe(false);

    const published = {
      ...started,
      status: "PUBLISHED",
      terminal_at: "2026-08-11T01:00:02Z",
      report_file: "2026-08-11.entry.decision-board.json",
    };
    expect(runJournalV0Schema.safeParse(published).success).toBe(true);
    expect(
      runJournalV0Schema.safeParse({
        ...published,
        report_file: `${published.report_file}\n`,
      }).success,
    ).toBe(false);
    expect(
      runJournalV0Schema.safeParse({
        ...published,
        status: "FAILED",
        issues: [
          {
            code: "UPLOAD_FAILED",
            message: "Run reported sanitized issue code UPLOAD_FAILED.",
          },
        ],
        report_file: `${published.report_file}\n`,
      }).success,
    ).toBe(false);
  });

  it.each(["published-entry.json", "published-holding.json", "blocked.json"])(
    "parses shared golden fixture %s",
    (name) => {
      const fixture = loadFixture(name);

      expect(parseDecisionBoardReportStructure(fixture)).toEqual(fixture);
      expect(safeParseDecisionBoardReportStructure(fixture).success).toBe(true);
    },
  );

  it.each(["published-entry.json", "published-holding.json", "blocked.json"])(
    "verifies shared golden fixture %s through the async integrity boundary",
    async (name) => {
      const fixture = loadFixture(name);

      await expect(parseVerifiedDecisionBoardReport(fixture)).resolves.toEqual(
        fixture,
      );
      expect(
        (await safeParseVerifiedDecisionBoardReport(fixture)).success,
      ).toBe(true);
    },
  );

  it("uses recursive sorted-key compact UTF-8 canonicalization for payload hashes", async () => {
    const fixture = loadPublishedFixture();
    const parsed = parseDecisionBoardReportStructure(fixture);
    expect(parsed.status).toBe("PUBLISHED");
    if (parsed.status !== "PUBLISHED") {
      return;
    }
    const unicodePayload = structuredClone(parsed.decision_payload);
    unicodePayload.items[0].instrument.company_name = "오로라 시스템즈";
    const canonicalText = new TextDecoder().decode(
      canonicalDecisionPayloadBytesV0(unicodePayload),
    );

    expect(canonicalText).toContain("오로라 시스템즈");
    expect(canonicalText.startsWith('{"items":')).toBe(true);
    expect(canonicalText).not.toContain(": ");

    await expect(decisionPayloadHashV0(fixture.decision_payload)).resolves.toBe(
      fixture.decision_payload_hash,
    );
  });

  it.each([
    undefined,
    "",
    `sha256:${"A".repeat(64)}`,
    `sha256:${"a".repeat(63)}`,
    123,
  ])("rejects noncanonical envelope idempotency key %j", (idempotencyKey) => {
    const fixture = loadFixture("published-entry.json") as Record<
      string,
      unknown
    >;
    if (idempotencyKey === undefined) {
      delete fixture.idempotency_key;
    } else {
      fixture.idempotency_key = idempotencyKey;
    }

    expect(safeParseDecisionBoardReportStructure(fixture).success).toBe(false);
  });

  it("rejects cycles with typed path errors in canonical and verified boundaries", async () => {
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    const fixture = loadPublishedFixture();
    fixture.metadata = cycle;

    expect(() => canonicalDecisionPayloadBytesV0(cycle as never)).toThrowError(
      DecisionBoardJsonValueError,
    );
    expect(() => canonicalDecisionPayloadBytesV0(cycle as never)).toThrow(
      /\$\.self.*cycle/,
    );
    await expect(parseVerifiedDecisionBoardReport(fixture)).rejects.toThrow(
      DecisionBoardJsonValueError,
    );
    const result = await safeParseVerifiedDecisionBoardReport(fixture);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error).toBeInstanceOf(DecisionBoardJsonValueError);
    }
  });

  it.each([
    {
      name: "string value",
      invalid: { text: "\ud800" },
    },
    {
      name: "object key",
      invalid: { ["\udfff"]: "text" },
    },
  ])("rejects unpaired surrogate in $name", async ({ invalid }) => {
    const fixture = loadPublishedFixture();
    fixture.metadata = invalid;

    expect(() =>
      canonicalDecisionPayloadBytesV0(invalid as never),
    ).toThrowError(DecisionBoardJsonValueError);
    await expect(parseVerifiedDecisionBoardReport(fixture)).rejects.toThrow(
      DecisionBoardJsonValueError,
    );
  });

  it("rejects the shared conditional-invariant fixture", () => {
    const result = safeParseDecisionBoardReportStructure(
      loadFixture("invalid-review-action.json"),
    );

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            path: ["decision_payload", "items", 0, "action"],
          }),
        ]),
      );
    }
  });

  it("rejects unknown envelope and nested fields", () => {
    const fixture = loadFixture("published-entry.json") as Record<
      string,
      unknown
    >;
    expect(
      decisionBoardEnvelopeV0Schema.safeParse({ ...fixture, surprise: true })
        .success,
    ).toBe(false);

    const nested = structuredClone(fixture) as {
      decision_payload: { items: Array<Record<string, unknown>> };
    };
    nested.decision_payload.items[0].surprise = true;
    expect(decisionBoardEnvelopeV0Schema.safeParse(nested).success).toBe(false);

    const privateMetadata = structuredClone(fixture);
    privateMetadata.metadata = { account: "PRIVATE-ACCOUNT" };
    expect(
      decisionBoardEnvelopeV0Schema.safeParse(privateMetadata).success,
    ).toBe(false);

    const privateVersion = structuredClone(fixture);
    privateVersion.metadata = { compiler_version: "build-secret-v1" };
    expect(
      decisionBoardEnvelopeV0Schema.safeParse(privateVersion).success,
    ).toBe(false);

    const privateTicker = structuredClone(fixture) as {
      decision_payload: {
        items: Array<{ instrument: { canonical_ticker: string } }>;
      };
    };
    privateTicker.decision_payload.items[0].instrument.canonical_ticker =
      "private sentinel";
    expect(decisionBoardEnvelopeV0Schema.safeParse(privateTicker).success).toBe(
      false,
    );
  });

  it("rejects malformed hashes", () => {
    const fixture = loadFixture("published-entry.json") as Record<
      string,
      unknown
    >;

    const malformed = structuredClone(fixture) as {
      decision_payload_hash: string;
    };
    malformed.decision_payload_hash = `sha256:${"A".repeat(64)}`;
    expect(decisionBoardEnvelopeV0Schema.safeParse(malformed).success).toBe(
      false,
    );
  });

  it.each([
    { name: "naive", timestamp: "2026-08-06T01:00:05" },
    { name: "impossible date", timestamp: "2026-02-30T01:00:05Z" },
  ])("rejects $name timestamp mutation", ({ timestamp }) => {
    const fixture = loadPublishedFixture();

    expect(
      decisionBoardEnvelopeV0Schema.safeParse({
        ...fixture,
        created_at: timestamp,
      }).success,
    ).toBe(false);
  });

  it("rejects evidence locations whose end precedes start", () => {
    const claim = validClaim();
    claim.supporting_location.end = 19;
    const result = claimValidationV0Schema.safeParse(claim);

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ path: ["supporting_location", "end"] }),
        ]),
      );
    }
  });

  it("rejects zero-length evidence locations", () => {
    const claim = validClaim();
    claim.supporting_location.end = claim.supporting_location.start;

    expect(claimValidationV0Schema.safeParse(claim).success).toBe(false);
  });

  it("mirrors the BrokerSnapshotV0 RPC consumer shape", () => {
    const snapshot = {
      state_key: "toss-sync:success:MIXED:2026-08-06",
      session_date: "2026-08-06",
      status: "applied",
      fresh_until: "2026-08-07T15:00:00Z",
      sealed_at: "2026-08-06T02:59:00Z",
      holdings_digest: `sha256:${"0".repeat(64)}`,
      revision: 7,
      marker: {
        scope: "MIXED",
        sessionDate: "2026-08-06",
        status: "applied",
        snapshotDigest: `sha256:${"0".repeat(64)}`,
        snapshotRevision: 7,
        sealedAt: "2026-08-06T02:59:00Z",
      },
      holdings: [],
    };

    expect(brokerSnapshotV0Schema.safeParse(snapshot).success).toBe(true);
    expect(
      brokerSnapshotV0Schema.safeParse({
        snapshot_id: "legacy-shape",
        revision: "7",
        captured_at: "2026-08-06T02:59:00Z",
        fresh_until: "2026-08-07T15:00:00Z",
        digest: `sha256:${"0".repeat(64)}`,
        approved_holdings: [],
      }).success,
    ).toBe(false);
  });

  it.each([
    { name: "non-HTTP scheme", sourceUrl: "mailto:research@example.com" },
    { name: "space in host", sourceUrl: "https://bad host.example/path" },
  ])("rejects source URL mutation: $name", ({ sourceUrl }) => {
    const claim = validClaim();
    claim.source_url = sourceUrl;

    expect(claimValidationV0Schema.safeParse(claim).success).toBe(false);
  });

  it.each([
    ["userinfo", "https://user:pass@example.com/article"],
    ["localhost", "https://localhost/article"],
    ["localhost subdomain", "https://news.localhost/article"],
    ["local TLD", "https://service.local/article"],
    ["internal TLD", "https://service.internal/article"],
    ["LAN TLD", "https://service.lan/article"],
    ["home TLD", "https://service.home/article"],
    ["IPv4 loopback", "https://127.0.0.1/article"],
    ["IPv6 loopback", "https://[::1]/article"],
    ["IPv4 private", "https://192.168.1.1/article"],
    ["IPv4 link-local", "https://169.254.169.254/latest"],
    ["nondefault port", "https://example.com:8443/article"],
    ["fragment", "https://example.com/article#private"],
    ["query", "https://example.com/article?token=PRIVATE"],
    ["punycode label", "https://xn--pple-43d.com/article"],
    ["Unicode lookalike", "https://аpple.com/article"],
    ["noncanonical host case", "https://Example.com/article"],
    ["missing canonical slash", "https://example.com"],
    ["over 2048 bytes", `https://example.com/${"a".repeat(2030)}`],
    ["trailing host dot", "https://example.com./article"],
    ["truncated percent", "https://example.com/bad%"],
    ["short percent", "https://example.com/bad%2"],
    ["nonhex percent", "https://example.com/bad%GG"],
    ["raw open bracket", "https://example.com/a[b"],
    ["raw close bracket", "https://example.com/a]b"],
    ["raw pipe", "https://example.com/a|b"],
    ["raw open brace", "https://example.com/a{b"],
    ["raw close brace", "https://example.com/a}b"],
    ["raw caret", "https://example.com/a^b"],
    ["raw less-than", "https://example.com/a<b"],
    ["raw greater-than", "https://example.com/a>b"],
    ["backslash", String.raw`https://example.com/a\b`],
    ["non-ASCII path", "https://example.com/café"],
  ])("rejects public evidence URL mutation: %s", async (_name, sourceUrl) => {
    const report = loadPublishedFixture();
    report.decision_payload.items[0].evidence[0].source_url = sourceUrl;
    report.decision_payload_hash = uncheckedPayloadHash(
      report.decision_payload,
    );

    expect(safeParseDecisionBoardReportStructure(report).success).toBe(false);
    await expect(parseVerifiedDecisionBoardReport(report)).rejects.toThrow();
  });

  it.each([
    "https://example.com/",
    "https://example.com/a-z_A.Z~09",
    "https://example.com/!$&'()*+,;=:@/nested",
    "https://example.com/encoded%20space/%2F",
  ])("accepts conservative RFC3986 path %s", async (sourceUrl) => {
    const report = loadPublishedFixture();
    report.decision_payload.items[0].evidence[0].source_url = sourceUrl;
    report.decision_payload_hash = uncheckedPayloadHash(
      report.decision_payload,
    );

    expect(safeParseDecisionBoardReportStructure(report).success).toBe(true);
    await expect(
      parseVerifiedDecisionBoardReport(report),
    ).resolves.toBeDefined();
  });

  it.each(publicUrlCorpus.invalid)(
    "rejects shared public URL corpus entry %s",
    async (sourceUrl) => {
      const report = loadPublishedFixture();
      report.decision_payload.items[0].evidence[0].source_url = sourceUrl;
      report.decision_payload_hash = uncheckedPayloadHash(
        report.decision_payload,
      );
      expect(safeParseDecisionBoardReportStructure(report).success).toBe(false);
      await expect(parseVerifiedDecisionBoardReport(report)).rejects.toThrow();
    },
  );

  it.each(publicUrlCorpus.valid)(
    "accepts shared public URL corpus entry %s",
    async (sourceUrl) => {
      const report = loadPublishedFixture();
      report.decision_payload.items[0].evidence[0].source_url = sourceUrl;
      report.decision_payload_hash = uncheckedPayloadHash(
        report.decision_payload,
      );
      expect(safeParseDecisionBoardReportStructure(report).success).toBe(true);
      await expect(
        parseVerifiedDecisionBoardReport(report),
      ).resolves.toBeDefined();
    },
  );

  it("requires exact supported claim provenance on every evidence reference", () => {
    const report = loadPublishedFixture();
    const evidence = report.decision_payload.items[0].evidence[0] as Record<
      string,
      unknown
    >;

    expect(evidence).toMatchObject({
      entailment: "SUPPORTED",
      article_content_hash: expect.stringMatching(/^sha256:[0-9a-f]{64}$/u),
      supporting_span: expect.any(String),
      supporting_location: {
        kind: "TEXT_OFFSETS",
        start: expect.any(Number),
        end: expect.any(Number),
      },
    });
  });

  it.each([
    {
      name: "BLOCKED with payload",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        report.status = "BLOCKED";
        report.issues = [
          { code: "BLOCKED", message: "Synthetic block for mutation test." },
        ];
      },
    },
    {
      name: "DECIDED without action",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        delete report.decision_payload.items[0].action;
      },
    },
    {
      name: "run-kind/action crossover",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        report.decision_payload.items[0].action = "HOLD";
      },
    },
    {
      name: "unsupported evidence",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        report.decision_payload.items[0].evidence[0].freshness = "STALE";
      },
    },
    {
      name: "stale payload hash",
      structuralSuccess: true,
      mutate: (report: MutablePublishedReport) => {
        report.decision_payload.items[0].action = "AVOID";
      },
    },
  ])(
    "rejects mutation at the applicable boundary: $name",
    async ({ mutate, structuralSuccess }) => {
      const fixture = loadPublishedFixture();
      mutate(fixture);

      expect(safeParseDecisionBoardReportStructure(fixture).success).toBe(
        structuralSuccess,
      );
      await expect(parseVerifiedDecisionBoardReport(fixture)).rejects.toThrow();
      const verifiedResult =
        await safeParseVerifiedDecisionBoardReport(fixture);
      expect(verifiedResult.success).toBe(false);
      if (structuralSuccess && !verifiedResult.success) {
        expect(verifiedResult.error).toBeInstanceOf(
          DecisionBoardIntegrityError,
        );
      }
    },
  );

  it("accepts an empty published eligible universe", () => {
    const fixture = loadFixture("published-entry.json") as {
      decision_payload: { items: unknown[] };
    };
    fixture.decision_payload.items = [];

    expect(decisionBoardEnvelopeV0Schema.safeParse(fixture).success).toBe(true);
  });
});
