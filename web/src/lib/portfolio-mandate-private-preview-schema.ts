import { z } from "zod";

import { parseStrictJsonText } from "@/lib/decision-board-json";
import {
  parseUnclassifiedQueuePreviewInput,
  type UnclassifiedQueuePreviewInput,
} from "@/lib/portfolio-mandate-a2-private-input-schema";

const dateSchema = z.iso.date();
const tickerSchema = z.string().regex(/^[A-Z]+\.(NAS|NYS)$/u);
const boundedTextSchema = z.string().min(1).max(2_000);
const sourceTypeSchema = z.enum([
  "SEC_FILING",
  "COMPANY_OFFICIAL",
  "REGULATOR_OFFICIAL",
]);

const conditionSchema = z
  .object({
    metric: z.string().min(1).max(200),
    operator: z.enum([
      "<",
      "<=",
      ">",
      ">=",
      "==",
      "RATING_BELOW",
      "EVENT_OCCURRED",
    ]),
    threshold: z.union([
      z.number().finite(),
      z.string().min(1).max(200),
      z.boolean(),
    ]),
    unit: z.string().min(1).max(100),
    period: z.enum(["EVENT", "QUARTER", "YEAR", "TRAILING_YEAR"]),
  })
  .strict();

const triggerSchema = z
  .object({
    id: z.string().regex(/^[A-Z0-9_]+$/u),
    description: boundedTextSchema,
    condition_match: z.enum(["ALL", "ANY"]).optional(),
    conditions: z.array(conditionSchema).min(1).max(20).optional(),
  })
  .strict()
  .superRefine((trigger, context) => {
    if (
      trigger.condition_match !== undefined &&
      trigger.conditions === undefined
    ) {
      context.addIssue({
        code: "custom",
        path: ["conditions"],
        message: "condition_match requires composite trigger conditions",
      });
    }
  });

const deteriorationRuleSchema = z
  .object({
    minimum_matches: z.number().int().min(1),
    consecutive_periods: z.number().int().min(1),
    period: z.literal("QUARTER"),
    signals: z.array(triggerSchema).min(1).max(20),
  })
  .strict()
  .superRefine((rule, context) => {
    if (rule.minimum_matches > rule.signals.length) {
      context.addIssue({
        code: "custom",
        path: ["minimum_matches"],
        message: "minimum_matches cannot exceed the signal count",
      });
    }
  });

const concentrationSchema = z
  .object({
    estimated_weight_pct: z.number().finite().min(0).max(100),
    estimate_as_of: dateSchema,
    estimate_is_execution_grade: z.literal(false),
    individual_status: z.enum(["PASS", "WARNING", "BREACH"]),
    sector: z.string().min(1).max(200).optional(),
    sector_status: z
      .enum(["PASS", "SECTOR_WARNING", "SECTOR_BREACH"])
      .optional(),
    sector_estimated_weight_pct: z.number().finite().min(0).max(100).optional(),
  })
  .strict()
  .superRefine((concentration, context) => {
    const sectorFields = [
      concentration.sector,
      concentration.sector_status,
      concentration.sector_estimated_weight_pct,
    ];
    if (
      sectorFields.some((value) => value !== undefined) &&
      sectorFields.some((value) => value === undefined)
    ) {
      context.addIssue({
        code: "custom",
        path: ["sector"],
        message: "Sector concentration fields must be provided together",
      });
    }
  });

const evidenceSchema = z
  .object({
    published_on: dateSchema,
    source_type: sourceTypeSchema,
    title: boundedTextSchema,
    url: z
      .string()
      .url()
      .regex(/^https:\/\//u),
    baseline: z
      .record(
        z.string().min(1).max(200),
        z.union([z.number().finite(), z.string().max(500), z.boolean()]),
      )
      .refine(
        (baseline) => Object.keys(baseline).length > 0,
        "Evidence baseline cannot be empty",
      ),
  })
  .strict();

const holdingSchema = z
  .object({
    ticker: tickerSchema,
    role: z.enum(["CORE", "SATELLITE"]),
    classification_state: z.literal("ACTIVE"),
    approval_state: z.literal("APPROVED"),
    horizon: z.literal("LONG_TERM"),
    thesis: z.string().min(1).max(1_000),
    review_cadence: z
      .object({
        quarterly: z.literal("NEXT_OFFICIAL_FILING"),
        annual_review_by: dateSchema,
        event_driven: z.array(z.string().min(1).max(200)).min(1).max(20),
      })
      .strict(),
    invalidation_policy: z
      .object({
        outcome: z.literal("THESIS_INVALIDATED_REVIEW_REQUIRED"),
        hard_triggers: z.array(triggerSchema).min(1).max(20),
        deterioration_rule: deteriorationRuleSchema,
        special_review_rules: z.array(boundedTextSchema).max(20),
      })
      .strict(),
    concentration: concentrationSchema,
    addition_policy: z
      .object({
        status: z.enum([
          "FROZEN_CONCENTRATION",
          "FROZEN_PENDING_VALUATION",
          "FROZEN_VALUATION_NOT_PASSED",
        ]),
        automatic_orders: z.literal(false),
        automatic_reinvestment: z.literal(false),
        reasons: z.array(boundedTextSchema).min(1).max(20),
      })
      .strict(),
    evidence: z.array(evidenceSchema).min(1).max(20),
  })
  .strict();

const targetRangeSchema = z
  .object({
    minimum_pct: z.number().finite().min(0).max(100),
    maximum_pct: z.number().finite().min(0).max(100),
  })
  .strict()
  .superRefine((range, context) => {
    if (range.minimum_pct > range.maximum_pct) {
      context.addIssue({
        code: "custom",
        path: ["minimum_pct"],
        message: "Target range minimum cannot exceed its maximum",
      });
    }
  });

export const portfolioMandatePrivatePreviewSchema = z
  .object({
    schema_version: z.literal("portfolio-mandate-private.v1"),
    data_mode: z.literal("PRIVATE_ZERO_WRITE"),
    decision_date: dateSchema,
    review_state: z
      .object({
        review_due: z.boolean(),
        next_quarterly_review: z.literal("NEXT_OFFICIAL_FILING"),
        next_annual_review_by: dateSchema,
        active_event_triggers: z.array(z.never()).max(0),
        automation_created: z.literal(false),
      })
      .strict(),
    portfolio_policy: z
      .object({
        target_ranges: z
          .object({ CORE: targetRangeSchema, SATELLITE: targetRangeSchema })
          .strict(),
        concentration_thresholds_pct: z
          .object({
            individual_warning: z.number().finite().min(0).max(100),
            individual_breach: z.number().finite().min(0).max(100),
            sector_warning: z.number().finite().min(0).max(100),
            sector_breach: z.number().finite().min(0).max(100),
          })
          .strict(),
        normalization: z
          .object({
            target_months: z.literal(12),
            primary_method: z.literal("NEW_CAPITAL_AND_DIVIDEND_REALLOCATION"),
            review_frequency: z.literal("QUARTERLY"),
          })
          .strict(),
        capital_deployment: z
          .object({
            automatic_reinvestment: z.literal(false),
            no_candidate_action: z.literal("HOLD_CASH"),
            valuation_method: z.literal(
              "NORMALIZED_EARNINGS_AND_FCF_YIELD_WITH_GROWTH_BALANCE_SHEET_HISTORY_AND_PEERS",
            ),
          })
          .strict(),
        valuation_queue: z.array(tickerSchema).min(1).max(8),
        evidence_priority: z.tuple([
          z.literal("SEC_FILING"),
          z.literal("COMPANY_OFFICIAL"),
          z.literal("REGULATOR_OFFICIAL"),
        ]),
        prohibited_operations: z
          .array(z.string().min(1).max(100))
          .min(1)
          .max(20)
          .refine(
            (operations) => new Set(operations).size === operations.length,
            "Prohibited operations must be unique",
          ),
      })
      .strict(),
    holdings: z.array(holdingSchema).length(8),
  })
  .strict()
  .superRefine((input, context) => {
    const tickers = input.holdings.map((holding) => holding.ticker);
    if (new Set(tickers).size !== tickers.length) {
      context.addIssue({
        code: "custom",
        path: ["holdings"],
        message: "Holding tickers must be unique",
      });
    }

    const coreCount = input.holdings.filter(
      (holding) => holding.role === "CORE",
    ).length;
    if (coreCount !== 5) {
      context.addIssue({
        code: "custom",
        path: ["holdings"],
        message: "The v1 overlay requires five CORE holdings",
      });
    }

    const queue = input.portfolio_policy.valuation_queue;
    if (
      new Set(queue).size !== queue.length ||
      queue.some((ticker) => !tickers.includes(ticker))
    ) {
      context.addIssue({
        code: "custom",
        path: ["portfolio_policy", "valuation_queue"],
        message: "Valuation queue must contain unique holding tickers",
      });
    }

    const thresholds = input.portfolio_policy.concentration_thresholds_pct;
    if (thresholds.individual_warning >= thresholds.individual_breach) {
      context.addIssue({
        code: "custom",
        path: [
          "portfolio_policy",
          "concentration_thresholds_pct",
          "individual_warning",
        ],
        message: "Individual warning must be below breach",
      });
    }
    if (thresholds.sector_warning >= thresholds.sector_breach) {
      context.addIssue({
        code: "custom",
        path: [
          "portfolio_policy",
          "concentration_thresholds_pct",
          "sector_warning",
        ],
        message: "Sector warning must be below breach",
      });
    }

    const weight = input.holdings.reduce(
      (total, holding) => total + holding.concentration.estimated_weight_pct,
      0,
    );
    if (weight < 99 || weight > 101) {
      context.addIssue({
        code: "custom",
        path: ["holdings"],
        message: "Estimated holding weights must describe the whole portfolio",
      });
    }
  });

export type PortfolioMandatePrivatePreview = z.infer<
  typeof portfolioMandatePrivatePreviewSchema
>;

export function parsePortfolioMandatePrivatePreviewText(
  text: string,
): PortfolioMandatePrivatePreview {
  const value = parseStrictJsonText(text);
  return portfolioMandatePrivatePreviewSchema.parse(value);
}

export type LocalPortfolioPreview =
  | {
      kind: "UNCLASSIFIED_A2";
      document: UnclassifiedQueuePreviewInput;
    }
  | {
      kind: "PRIVATE_MANDATE_V1";
      document: PortfolioMandatePrivatePreview;
    };

export function parseLocalPortfolioPreviewText(
  text: string,
): LocalPortfolioPreview {
  const value = parseStrictJsonText(text);
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new SyntaxError("Local portfolio preview must be a JSON object");
  }

  const schemaVersion = (value as { schema_version?: unknown }).schema_version;
  if (schemaVersion === "portfolio-mandate-a2-private-input.v0") {
    return {
      kind: "UNCLASSIFIED_A2",
      document: parseUnclassifiedQueuePreviewInput(value),
    };
  }
  if (schemaVersion === "portfolio-mandate-private.v1") {
    return {
      kind: "PRIVATE_MANDATE_V1",
      document: portfolioMandatePrivatePreviewSchema.parse(value),
    };
  }
  throw new SyntaxError("Unsupported local portfolio preview schema");
}
