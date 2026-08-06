import { z } from "zod";

const hashV0Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const timestampV0Schema = z.iso.datetime({ offset: true });

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
    source_url: z.url(),
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
    entailment: z.literal("SUPPORTED"),
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

/** Structural validation only; this synchronous boundary does not verify the payload digest. */
export const parseDecisionBoardReportStructure = (
  value: unknown,
): DecisionBoardEnvelopeV0 => decisionBoardEnvelopeV0Schema.parse(value);

/** Structural validation only; use the async verified parser for report consumption. */
export const safeParseDecisionBoardReportStructure = (value: unknown) =>
  decisionBoardEnvelopeV0Schema.safeParse(value);

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
): Uint8Array<ArrayBuffer> => new TextEncoder().encode(canonicalJson(payload));

export const decisionPayloadHashV0 = async (
  payload: unknown,
): Promise<string> => {
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
  | { success: false; error: z.ZodError | DecisionBoardIntegrityError };

/** Non-throwing integrity-verifying report boundary for UI consumers. */
export const safeParseVerifiedDecisionBoardReport = async (
  value: unknown,
): Promise<VerifiedDecisionBoardParseResult> => {
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
