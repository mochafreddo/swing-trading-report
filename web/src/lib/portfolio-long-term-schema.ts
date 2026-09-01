import { z } from "zod";

const publicTickerSchema = z
  .string()
  .regex(/^[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*$/);
const decimalSchema = z.string().regex(/^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$/);
const versionSchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/);
const periodSchema = z.string().regex(/^[A-Z0-9][A-Z0-9._-]{0,31}$/);
const unitSchema = z.string().regex(/^[A-Z][A-Z0-9_]{0,31}$/);

const instrumentSchema = z
  .object({
    instrument_id: z.string().uuid(),
    canonical_ticker: publicTickerSchema,
    company_name: z.string().trim().min(1).max(160),
  })
  .strict();

const predicateSchema = z
  .object({
    metric: z.string().regex(/^[a-z][a-z0-9_]{0,63}$/),
    operator: z.enum(["LT", "LTE", "GT", "GTE", "EQ"]),
    threshold: decimalSchema,
    unit: unitSchema,
    period: periodSchema,
  })
  .strict();

const cadenceSchema = z
  .object({
    kind: z.enum(["WEEKLY", "FILING_EVENT"]),
    due: z.boolean(),
  })
  .strict();

const activeMandateSchema = z
  .object({
    classification_state: z.literal("ACTIVE"),
    approval_state: z.literal("APPROVED"),
    horizon: z.literal("LONG_TERM"),
    thesis: z.string().trim().min(1).max(1000),
    invalidation_predicate: predicateSchema,
    review_cadence: cadenceSchema,
  })
  .strict();

const unclassifiedMandateSchema = z
  .object({
    classification_state: z.literal("UNCLASSIFIED"),
    approval_state: z.literal("DRAFT"),
    horizon: z.null(),
    thesis: z.null(),
    invalidation_predicate: z.null(),
    review_cadence: cadenceSchema,
  })
  .strict();

const predicateEvaluationSchema = z
  .object({
    authority: z.enum(["DETERMINISTIC_PARSER", "USER", "AI_RESEARCH"]),
    result: z.enum(["FULFILLED", "NOT_FULFILLED", "CANDIDATE"]),
    observed_value: decimalSchema,
    unit: unitSchema,
    period: periodSchema,
    parser_version: versionSchema.nullable(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.authority === "AI_RESEARCH" && value.result !== "CANDIDATE") {
      context.addIssue({
        code: "custom",
        path: ["result"],
        message: "AI_RESEARCH may only produce a review-only CANDIDATE",
      });
    }
    if (value.authority === "AI_RESEARCH" && value.parser_version !== null) {
      context.addIssue({
        code: "custom",
        path: ["parser_version"],
        message: "AI_RESEARCH cannot claim a deterministic parser version",
      });
    }
    if (
      value.authority === "DETERMINISTIC_PARSER" &&
      value.parser_version === null
    ) {
      context.addIssue({
        code: "custom",
        path: ["parser_version"],
        message: "DETERMINISTIC_PARSER requires parser provenance",
      });
    }
  });

const evidenceSchema = z
  .object({
    validation_status: z.enum(["VALID", "STALE", "CONFLICTED"]),
    source_tier: z.literal("PRIMARY"),
    filing_event: z
      .object({
        source_id: z.string().uuid(),
        source_url: z
          .string()
          .url()
          .refine((value) => value.startsWith("https://")),
        publisher: z.string().trim().min(1).max(160),
        published_at: z.string().datetime({ offset: true }),
        period: periodSchema,
        supporting_span: z.string().min(1).max(4096),
      })
      .strict(),
    predicate_evaluation: predicateEvaluationSchema,
  })
  .strict();

const caseSchema = z
  .object({
    case_id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/),
    instrument: instrumentSchema,
    mandate: z.discriminatedUnion("classification_state", [
      activeMandateSchema,
      unclassifiedMandateSchema,
    ]),
    evidence: evidenceSchema,
    concentration: z.object({ status: z.enum(["PASS", "BREACH"]) }).strict(),
  })
  .strict();

const decisionSchema = z
  .object({
    case_id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/),
    instrument_id: z.string().uuid(),
    canonical_ticker: publicTickerSchema,
    status: z.enum(["DECIDED", "REVIEW", "NO_ADVICE", "NOT_DUE"]),
    action: z.enum(["HOLD", "SELL", "REVIEW"]).nullable(),
    reason_code: z.enum([
      "PREDICATE_NOT_FULFILLED",
      "PREDICATE_FULFILLED",
      "EVIDENCE_STALE",
      "EVIDENCE_CONFLICTED",
      "CONCENTRATION_BREACH",
      "PREDICATE_REVIEW_ONLY",
      "MANDATE_UNCLASSIFIED",
      "REVIEW_NOT_DUE",
    ]),
    mode: z.literal("LOCAL_ONLY"),
  })
  .strict();

const baseFixtureSchema = z
  .object({
    schema_version: z.literal("portfolio-long-term.t13"),
    mode: z.literal("LOCAL_ONLY"),
    as_of: z.string().datetime({ offset: true }),
    cases: z.array(caseSchema).min(1),
    expected_decisions: z.array(decisionSchema).min(1),
  })
  .strict();

export type PortfolioLongTermT13Fixture = z.infer<typeof baseFixtureSchema>;
export type LongTermDecisionT13 = z.infer<typeof decisionSchema>;

function policyOutcome(
  item: PortfolioLongTermT13Fixture["cases"][number],
): Pick<LongTermDecisionT13, "status" | "action" | "reason_code"> {
  if (item.mandate.classification_state !== "ACTIVE") {
    return {
      status: "NO_ADVICE",
      action: null,
      reason_code: "MANDATE_UNCLASSIFIED",
    };
  }
  if (!item.mandate.review_cadence.due) {
    return {
      status: "NOT_DUE",
      action: null,
      reason_code: "REVIEW_NOT_DUE",
    };
  }
  if (item.evidence.validation_status === "STALE") {
    return {
      status: "REVIEW",
      action: "REVIEW",
      reason_code: "EVIDENCE_STALE",
    };
  }
  if (item.evidence.validation_status === "CONFLICTED") {
    return {
      status: "REVIEW",
      action: "REVIEW",
      reason_code: "EVIDENCE_CONFLICTED",
    };
  }
  if (item.concentration.status === "BREACH") {
    return {
      status: "REVIEW",
      action: "REVIEW",
      reason_code: "CONCENTRATION_BREACH",
    };
  }
  const evaluation = item.evidence.predicate_evaluation;
  if (evaluation.authority === "AI_RESEARCH") {
    return {
      status: "REVIEW",
      action: "REVIEW",
      reason_code: "PREDICATE_REVIEW_ONLY",
    };
  }
  if (evaluation.result === "FULFILLED") {
    return {
      status: "DECIDED",
      action: "SELL",
      reason_code: "PREDICATE_FULFILLED",
    };
  }
  return {
    status: "DECIDED",
    action: "HOLD",
    reason_code: "PREDICATE_NOT_FULFILLED",
  };
}

export function compilePortfolioLongTermT13(
  value: PortfolioLongTermT13Fixture,
): LongTermDecisionT13[] {
  return value.cases.map((item) => ({
    case_id: item.case_id,
    instrument_id: item.instrument.instrument_id,
    canonical_ticker: item.instrument.canonical_ticker,
    ...policyOutcome(item),
    mode: "LOCAL_ONLY" as const,
  }));
}

export const portfolioLongTermT13FixtureSchema = baseFixtureSchema.superRefine(
  (value, context) => {
    const caseIds = new Set<string>();
    value.cases.forEach((item, index) => {
      if (caseIds.has(item.case_id)) {
        context.addIssue({
          code: "custom",
          path: ["cases", index, "case_id"],
          message: "case_id must be unique",
        });
      }
      caseIds.add(item.case_id);
    });

    const compiled = compilePortfolioLongTermT13(value);
    if (JSON.stringify(compiled) !== JSON.stringify(value.expected_decisions)) {
      context.addIssue({
        code: "custom",
        path: ["expected_decisions"],
        message: "must match the deterministic policy projection",
      });
    }
  },
);

export function parsePortfolioLongTermT13Fixture(value: unknown) {
  return portfolioLongTermT13FixtureSchema.parse(value);
}
