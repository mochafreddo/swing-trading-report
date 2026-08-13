import { z } from "zod";

const hashV0Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const timestampV0Schema = z.iso.datetime({ offset: true });
const runJournalTimestampV0Schema = z
  .string()
  .regex(
    /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{6})?Z$/,
  )
  .pipe(z.iso.datetime({ offset: false }));
const runJournalReportFileV0Schema = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$(?![\s\S])/);
const runJournalDecisionIssueMessages = {
  COMPILER_CONTRACT_INVALID:
    "Run reported sanitized issue code COMPILER_CONTRACT_INVALID.",
  CONFIG_UNAVAILABLE: "Run reported sanitized issue code CONFIG_UNAVAILABLE.",
  IDEMPOTENCY_CONFLICT:
    "Run reported sanitized issue code IDEMPOTENCY_CONFLICT.",
  INTERNAL_ERROR: "Run reported sanitized issue code INTERNAL_ERROR.",
  ITEM_ENRICHMENT_INVALID:
    "Run reported sanitized issue code ITEM_ENRICHMENT_INVALID.",
  LOCAL_PERSISTENCE_FAILED:
    "Run reported sanitized issue code LOCAL_PERSISTENCE_FAILED.",
  PREPARATION_INVALID: "Run reported sanitized issue code PREPARATION_INVALID.",
  SHARED_PREFLIGHT_UNAVAILABLE:
    "Run reported sanitized issue code SHARED_PREFLIGHT_UNAVAILABLE.",
  UPLOAD_FAILED: "Run reported sanitized issue code UPLOAD_FAILED.",
} as const;
const runJournalDecisionIssueCodeV0Schema = z.enum(
  Object.keys(runJournalDecisionIssueMessages) as [
    keyof typeof runJournalDecisionIssueMessages,
    ...(keyof typeof runJournalDecisionIssueMessages)[],
  ],
);
const runJournalDecisionIssueV0Schema = z
  .object({
    code: runJournalDecisionIssueCodeV0Schema,
    message: z.string(),
  })
  .strict()
  .refine(
    (issue) => runJournalDecisionIssueMessages[issue.code] === issue.message,
    { path: ["message"], message: "Must match the sanitized issue code" },
  );
const runJournalUploadIssueV0Schema = z
  .object({
    code: z.literal("UPLOAD_FAILED"),
    message: z.literal("Run reported sanitized issue code UPLOAD_FAILED."),
  })
  .strict();
const runJournalNonUploadDecisionIssueV0Schema =
  runJournalDecisionIssueV0Schema.refine(
    (issue) => issue.code !== "UPLOAD_FAILED",
    { path: ["code"], message: "UPLOAD_FAILED requires a report file" },
  );
const runJournalMissedIssueV0Schema = z
  .object({
    code: z.literal("MISSED_EXPECTED"),
    message: z.literal("Expected run did not start before its grace deadline."),
  })
  .strict();
const runJournalStaleIssueV0Schema = z
  .object({
    code: z.literal("STALE_INCOMPLETE"),
    message: z.literal(
      "Started run did not reach a terminal state before its TTL.",
    ),
  })
  .strict();
const runJournalBaseShape = {
  schema_version: z.literal("decision-board.v0"),
  run_id: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$(?![\s\S])/),
  run_kind: z.enum(["ENTRY", "HOLDING"]),
  expected_at: runJournalTimestampV0Schema,
  grace_seconds: z.number().int().min(0).max(604800),
  stale_seconds: z.number().int().min(1).max(604800),
};
const runJournalStartedV0Schema = z
  .object({
    ...runJournalBaseShape,
    status: z.literal("STARTED"),
    started_at: runJournalTimestampV0Schema,
    terminal_at: z.null(),
    issues: z.tuple([]),
    report_file: z.null(),
  })
  .strict();
const runJournalPublishedOrBlockedV0Schema = (
  status: "PUBLISHED" | "BLOCKED",
) =>
  z
    .object({
      ...runJournalBaseShape,
      status: z.literal(status),
      started_at: runJournalTimestampV0Schema,
      terminal_at: runJournalTimestampV0Schema,
      issues: z.array(runJournalUploadIssueV0Schema).max(1),
      report_file: runJournalReportFileV0Schema,
    })
    .strict();
const runJournalFailedV0Schema = z.union([
  z
    .object({
      ...runJournalBaseShape,
      status: z.literal("FAILED"),
      started_at: runJournalTimestampV0Schema,
      terminal_at: runJournalTimestampV0Schema,
      issues: z.tuple([runJournalUploadIssueV0Schema]),
      report_file: runJournalReportFileV0Schema,
    })
    .strict(),
  z
    .object({
      ...runJournalBaseShape,
      status: z.literal("FAILED"),
      started_at: runJournalTimestampV0Schema,
      terminal_at: runJournalTimestampV0Schema,
      issues: z.tuple([runJournalNonUploadDecisionIssueV0Schema]),
      report_file: z.null(),
    })
    .strict(),
]);
const runJournalMissedV0Schema = z
  .object({
    ...runJournalBaseShape,
    status: z.literal("MISSED_EXPECTED"),
    started_at: z.null(),
    terminal_at: runJournalTimestampV0Schema,
    issues: z.tuple([runJournalMissedIssueV0Schema]),
    report_file: z.null(),
  })
  .strict();
const runJournalStaleV0Schema = z
  .object({
    ...runJournalBaseShape,
    status: z.literal("STALE_INCOMPLETE"),
    started_at: runJournalTimestampV0Schema,
    terminal_at: runJournalTimestampV0Schema,
    issues: z.tuple([runJournalStaleIssueV0Schema]),
    report_file: z.null(),
  })
  .strict();

const runJournalStructuralV0Schema = z.union([
  runJournalStartedV0Schema,
  runJournalPublishedOrBlockedV0Schema("PUBLISHED"),
  runJournalPublishedOrBlockedV0Schema("BLOCKED"),
  runJournalFailedV0Schema,
  runJournalMissedV0Schema,
  runJournalStaleV0Schema,
]);

export const runJournalV0Schema = runJournalStructuralV0Schema.superRefine(
  (record, context) => {
    const expected = Date.parse(record.expected_at);
    const started =
      record.started_at === null ? null : Date.parse(record.started_at);
    const terminal =
      record.terminal_at === null ? null : Date.parse(record.terminal_at);
    if (started !== null && started < expected) {
      context.addIssue({
        code: "custom",
        path: ["started_at"],
        message: "started_at cannot precede expected_at",
      });
    }
    const lowerBound = started ?? expected;
    if (terminal !== null && terminal < lowerBound) {
      context.addIssue({
        code: "custom",
        path: ["terminal_at"],
        message: "terminal_at cannot precede the observed state",
      });
    }
  },
);
const sourceUrlV0Schema = z.url().refine(
  (value) => {
    if (/[\s\u0000-\u001f\u007f]/u.test(value)) {
      return false;
    }
    try {
      const parsed = new URL(value);
      return (
        (parsed.protocol === "http:" || parsed.protocol === "https:") &&
        parsed.hostname.length > 0
      );
    } catch {
      return false;
    }
  },
  { message: "Must be a valid absolute HTTP(S) URL" },
);

export const decisionBoardIssueV0Schema = z
  .object({
    code: z.string().regex(/^[A-Z][A-Z0-9_]*$/),
    message: z.string().min(1),
    path: z.array(z.string()).optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
  })
  .strict();

export const instrumentRefV0Schema = z
  .object({
    market: z.literal("US"),
    canonical_ticker: z.string().min(1),
    exchange: z.string().min(1),
    company_name: z.string().min(1),
    identity_source: z.string().min(1),
    identity_version: z.string().min(1),
  })
  .strict();

export const brokerSnapshotV0Schema = z
  .object({
    snapshot_id: z.string().min(1),
    revision: z.string().min(1),
    captured_at: timestampV0Schema,
    fresh_until: timestampV0Schema,
    digest: hashV0Schema,
    approved_holdings: z.array(instrumentRefV0Schema),
  })
  .strict();

export const supportingLocationV0Schema = z
  .object({
    kind: z.literal("TEXT_OFFSETS"),
    start: z.number().int().nonnegative(),
    end: z.number().int().positive(),
  })
  .strict()
  .refine((location) => location.end >= location.start, {
    path: ["end"],
    message: "end must be greater than or equal to start",
  });

export const claimValidationV0Schema = z
  .object({
    claim_id: z.string().min(1),
    instrument: instrumentRefV0Schema,
    source_url: sourceUrlV0Schema,
    publisher: z.string().min(1),
    published_at: timestampV0Schema,
    article_content_hash: hashV0Schema,
    supporting_span: z.string().min(1),
    supporting_location: supportingLocationV0Schema,
    verifier_version: z.string().min(1),
    entailment: z.enum(["SUPPORTED", "CONTRADICTED", "UNCLEAR"]),
  })
  .strict();

const sourceHashV0Schema = z
  .object({
    source: z.string().min(1),
    hash: hashV0Schema,
  })
  .strict();

const deterministicFactV0Schema = z
  .object({
    fact_id: z.string().min(1),
    instrument: instrumentRefV0Schema,
    field: z.string().min(1),
    value: z.union([z.string(), z.number(), z.boolean(), z.null()]),
    observed_at: timestampV0Schema,
    source_hash: hashV0Schema,
  })
  .strict();

export const decisionInputV0Schema = z
  .object({
    sealed_at: timestampV0Schema,
    run_kind: z.enum(["ENTRY", "HOLDING"]),
    input_hash: hashV0Schema,
    source_hashes: z.array(sourceHashV0Schema),
    instruments: z.array(instrumentRefV0Schema),
    deterministic_facts: z.array(deterministicFactV0Schema),
    validated_claims: z.array(claimValidationV0Schema),
  })
  .strict();

const evidenceRefV0Schema = z
  .object({
    claim_id: z.string().min(1),
    role: z.enum(["SUPPORTING", "OPPOSING"]),
    source_url: sourceUrlV0Schema.refine(
      (value) => new URL(value).protocol === "https:",
      { message: "Public evidence links must use HTTPS" },
    ),
    publisher: z.string().min(1),
    published_at: timestampV0Schema,
    freshness: z.literal("WITHIN_POLICY"),
    citation_label: z.string().min(1),
  })
  .strict();

const reviewItemV0Schema = z
  .object({
    instrument: instrumentRefV0Schema,
    status: z.literal("REVIEW"),
    action: z.never().optional(),
    issues: z.array(decisionBoardIssueV0Schema).min(1),
    evidence: z.array(evidenceRefV0Schema),
  })
  .strict();

const decidedItemV0Schema = (actions: readonly [string, ...string[]]) =>
  z
    .object({
      instrument: instrumentRefV0Schema,
      status: z.literal("DECIDED"),
      action: z.enum(actions),
      issues: z.array(decisionBoardIssueV0Schema),
      evidence: z.array(evidenceRefV0Schema),
    })
    .strict();

const entryDecisionItemV0Schema = z.discriminatedUnion("status", [
  decidedItemV0Schema(["BUY", "AVOID"]),
  reviewItemV0Schema,
]);
const holdingDecisionItemV0Schema = z.discriminatedUnion("status", [
  decidedItemV0Schema(["HOLD", "SELL"]),
  reviewItemV0Schema,
]);

const entryDecisionPayloadV0Schema = z
  .object({
    run_kind: z.literal("ENTRY"),
    sealed_input_hash: hashV0Schema,
    items: z.array(entryDecisionItemV0Schema),
  })
  .strict();

const holdingDecisionPayloadV0Schema = z
  .object({
    run_kind: z.literal("HOLDING"),
    sealed_input_hash: hashV0Schema,
    items: z.array(holdingDecisionItemV0Schema),
  })
  .strict();

export const decisionPayloadV0Schema = z.discriminatedUnion("run_kind", [
  entryDecisionPayloadV0Schema,
  holdingDecisionPayloadV0Schema,
]);

const envelopeBaseShape = {
  schema_version: z.literal("decision-board.v0"),
  run_id: z.string().min(1),
  created_at: timestampV0Schema,
  idempotency_key: hashV0Schema,
  issues: z.array(decisionBoardIssueV0Schema),
  metadata: z.record(z.string(), z.unknown()).optional(),
};

const publishedEntryEnvelopeV0Schema = z
  .object({
    ...envelopeBaseShape,
    run_kind: z.literal("ENTRY"),
    status: z.literal("PUBLISHED"),
    decision_payload: entryDecisionPayloadV0Schema,
    decision_payload_hash: hashV0Schema,
  })
  .strict();

const publishedHoldingEnvelopeV0Schema = z
  .object({
    ...envelopeBaseShape,
    run_kind: z.literal("HOLDING"),
    status: z.literal("PUBLISHED"),
    decision_payload: holdingDecisionPayloadV0Schema,
    decision_payload_hash: hashV0Schema,
  })
  .strict();

const blockedEnvelopeV0Schema = z
  .object({
    ...envelopeBaseShape,
    run_kind: z.enum(["ENTRY", "HOLDING"]),
    status: z.literal("BLOCKED"),
    issues: z.array(decisionBoardIssueV0Schema).min(1),
  })
  .strict();

const publishedEnvelopeV0Schema = z.discriminatedUnion("run_kind", [
  publishedEntryEnvelopeV0Schema,
  publishedHoldingEnvelopeV0Schema,
]);

export const decisionBoardEnvelopeV0Schema = z.discriminatedUnion("status", [
  publishedEnvelopeV0Schema,
  blockedEnvelopeV0Schema,
]);

export type DecisionBoardIssueV0 = z.infer<typeof decisionBoardIssueV0Schema>;
export type InstrumentRefV0 = z.infer<typeof instrumentRefV0Schema>;
export type BrokerSnapshotV0 = z.infer<typeof brokerSnapshotV0Schema>;
export type ClaimValidationV0 = z.infer<typeof claimValidationV0Schema>;
export type DecisionInputV0 = z.infer<typeof decisionInputV0Schema>;
export type DecisionPayloadV0 = z.infer<typeof decisionPayloadV0Schema>;
export type DecisionBoardEnvelopeV0 = z.infer<
  typeof decisionBoardEnvelopeV0Schema
>;
export type RunJournalV0 = z.infer<typeof runJournalV0Schema>;

/** Structural validation only; this synchronous boundary does not verify the payload digest. */
export const parseDecisionBoardReportStructure = (
  value: unknown,
): DecisionBoardEnvelopeV0 => decisionBoardEnvelopeV0Schema.parse(value);

/** Structural validation only; use the async verified parser for report consumption. */
export const safeParseDecisionBoardReportStructure = (value: unknown) =>
  decisionBoardEnvelopeV0Schema.safeParse(value);

export class DecisionBoardJsonValueError extends TypeError {
  constructor(
    readonly path: string,
    message: string,
  ) {
    super(`${path}: ${message}`);
    this.name = "DecisionBoardJsonValueError";
  }
}

const assertUnicodeScalarString = (value: string, path: string): void => {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        index += 1;
        continue;
      }
      throw new DecisionBoardJsonValueError(
        path,
        "must contain only Unicode scalar values",
      );
    }
    if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new DecisionBoardJsonValueError(
        path,
        "must contain only Unicode scalar values",
      );
    }
  }
};

const assertStrictJsonValue = (
  value: unknown,
  path = "$",
  activeContainers = new Set<object>(),
): void => {
  if (value === null || typeof value === "boolean") {
    return;
  }
  if (typeof value === "string") {
    assertUnicodeScalarString(value, path);
    return;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new DecisionBoardJsonValueError(
        path,
        "non-finite numbers are not strict JSON values",
      );
    }
    return;
  }
  if (typeof value !== "object") {
    throw new DecisionBoardJsonValueError(
      path,
      `${typeof value} is not a strict JSON value`,
    );
  }
  if (activeContainers.has(value)) {
    throw new DecisionBoardJsonValueError(
      path,
      "cycle detected in JSON container",
    );
  }
  activeContainers.add(value);
  try {
    if (Array.isArray(value)) {
      value.forEach((item, index) =>
        assertStrictJsonValue(item, `${path}[${index}]`, activeContainers),
      );
      return;
    }
    if (Object.getOwnPropertySymbols(value).length > 0) {
      throw new DecisionBoardJsonValueError(
        path,
        "symbol keys are not strict JSON object keys",
      );
    }
    Object.entries(value).forEach(([key, item]) => {
      assertUnicodeScalarString(key, path);
      assertStrictJsonValue(item, `${path}.${key}`, activeContainers);
    });
  } finally {
    activeContainers.delete(value);
  }
};

const canonicalJson = (value: unknown): string => {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new TypeError("Canonical JSON does not support non-finite numbers");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (typeof value === "object") {
    const objectValue = value as Record<string, unknown>;
    return `{${Object.keys(objectValue)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(objectValue[key])}`)
      .join(",")}}`;
  }
  throw new TypeError(`Canonical JSON does not support ${typeof value}`);
};

export const canonicalDecisionPayloadBytesV0 = (
  payload: DecisionPayloadV0,
): Uint8Array<ArrayBuffer> => {
  assertStrictJsonValue(payload);
  return new TextEncoder().encode(canonicalJson(payload));
};

export const decisionPayloadHashV0 = async (
  payload: unknown,
): Promise<string> => {
  assertStrictJsonValue(payload);
  const parsedPayload = decisionPayloadV0Schema.parse(payload);
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    canonicalDecisionPayloadBytesV0(parsedPayload),
  );
  const hex = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `sha256:${hex}`;
};

export class DecisionBoardIntegrityError extends Error {
  constructor(
    readonly expectedHash: string,
    readonly actualHash: string,
  ) {
    super("Decision Board payload hash does not match its canonical payload");
    this.name = "DecisionBoardIntegrityError";
  }
}

/** Integrity-verifying report boundary for UI and other report consumers. */
export const parseVerifiedDecisionBoardReport = async (
  value: unknown,
): Promise<DecisionBoardEnvelopeV0> => {
  assertStrictJsonValue(value);
  const report = parseDecisionBoardReportStructure(value);
  if (report.status === "PUBLISHED") {
    const actualHash = await decisionPayloadHashV0(report.decision_payload);
    if (actualHash !== report.decision_payload_hash) {
      throw new DecisionBoardIntegrityError(
        report.decision_payload_hash,
        actualHash,
      );
    }
  }
  return report;
};

export type VerifiedDecisionBoardParseResult =
  | { success: true; data: DecisionBoardEnvelopeV0 }
  | {
      success: false;
      error:
        z.ZodError | DecisionBoardIntegrityError | DecisionBoardJsonValueError;
    };

/** Non-throwing integrity-verifying report boundary for UI consumers. */
export const safeParseVerifiedDecisionBoardReport = async (
  value: unknown,
): Promise<VerifiedDecisionBoardParseResult> => {
  try {
    assertStrictJsonValue(value);
  } catch (error) {
    if (error instanceof DecisionBoardJsonValueError) {
      return { success: false, error };
    }
    throw error;
  }
  const structuralResult = safeParseDecisionBoardReportStructure(value);
  if (!structuralResult.success) {
    return structuralResult;
  }
  try {
    return {
      success: true,
      data: await parseVerifiedDecisionBoardReport(structuralResult.data),
    };
  } catch (error) {
    if (error instanceof DecisionBoardIntegrityError) {
      return { success: false, error };
    }
    throw error;
  }
};
