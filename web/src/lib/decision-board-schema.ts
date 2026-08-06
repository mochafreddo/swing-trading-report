import { z } from "zod";

const hashV0Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const timestampV0Schema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/)
  .refine((value) => !Number.isNaN(Date.parse(value)), {
    message: "Must be a valid timezone-aware ISO-8601 timestamp",
  });

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

export const claimValidationV0Schema = z
  .object({
    claim_id: z.string().min(1),
    instrument: instrumentRefV0Schema,
    source_url: z.url(),
    publisher: z.string().min(1),
    published_at: timestampV0Schema,
    article_content_hash: hashV0Schema,
    supporting_span: z.string().min(1),
    supporting_location: z
      .object({
        kind: z.literal("TEXT_OFFSETS"),
        start: z.number().int().nonnegative(),
        end: z.number().int().positive(),
      })
      .strict(),
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

export const parseDecisionBoardReport = (
  value: unknown,
): DecisionBoardEnvelopeV0 => decisionBoardEnvelopeV0Schema.parse(value);

export const safeParseDecisionBoardReport = (value: unknown) =>
  decisionBoardEnvelopeV0Schema.safeParse(value);
