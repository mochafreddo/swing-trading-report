import { z } from "zod";

const observedAtKstSchema = z.iso.datetime({ offset: true });
const tickerSchema = z.string().regex(/^[A-Z0-9.-]+\.(NAS|NYS|AMS)$/u);
const recallSchema = z.enum(["REMEMBERED", "NOT_REMEMBERED"]);
const horizonSchema = z.enum(["SWING", "LONG_TERM"]);

const holdingBaseShape = {
  ticker: tickerSchema,
  classification_state: z.enum(["UNCLASSIFIED", "ACTIVE", "EXIT_REVIEW"]),
  horizon: horizonSchema.nullable(),
  proposed_horizon: horizonSchema.nullable(),
  thesis: z.string().min(1).max(2000).nullable(),
  thesis_recall: recallSchema,
  invalidation: z.array(z.string().min(1).max(1000)),
  invalidation_recall: recallSchema,
} as const;

const unclassifiedHoldingSchema = z
  .object({
    ...holdingBaseShape,
    classification_state: z.literal("UNCLASSIFIED"),
    horizon: z.null(),
  })
  .strict()
  .superRefine((holding, context) => {
    if (
      (holding.thesis === null) !==
      (holding.thesis_recall === "NOT_REMEMBERED")
    ) {
      context.addIssue({
        code: "custom",
        path: ["thesis_recall"],
        message: "Thesis value and recall state must agree",
      });
    }
    if (
      (holding.invalidation.length === 0) !==
      (holding.invalidation_recall === "NOT_REMEMBERED")
    ) {
      context.addIssue({
        code: "custom",
        path: ["invalidation_recall"],
        message: "Invalidation values and recall state must agree",
      });
    }
  });

const activeHoldingSchema = z
  .object({
    ...holdingBaseShape,
    classification_state: z.literal("ACTIVE"),
    horizon: horizonSchema,
    proposed_horizon: z.null(),
    thesis: z.string().min(1).max(2000),
    thesis_recall: z.literal("REMEMBERED"),
    invalidation: z.array(z.string().min(1).max(1000)).min(1),
    invalidation_recall: z.literal("REMEMBERED"),
  })
  .strict();

const exitReviewHoldingSchema = z
  .object({
    ...holdingBaseShape,
    classification_state: z.literal("EXIT_REVIEW"),
    horizon: z.null(),
    proposed_horizon: z.null(),
  })
  .strict();

export const portfolioMandateA2PrivateInputSchema = z
  .object({
    schema_version: z.literal("portfolio-mandate-a2-private-input.v0"),
    state: z.enum([
      "AWAITING_USER_INPUT",
      "USER_INPUT_RECORDED_UNCLASSIFIED",
      "USER_INPUT_COMPLETE",
    ]),
    snapshot: z
      .object({
        source: z.literal("toss-open-api:/api/v1/holdings"),
        observed_at_kst: observedAtKstSchema,
        ranking_basis: z.literal("marketValue.amount"),
        currency: z.literal("USD"),
        holding_count: z.number().int().min(5),
        account_identifier_included: z.literal(false),
        amounts_included: z.literal(false),
      })
      .strict(),
    holdings: z
      .array(
        z.union([
          unclassifiedHoldingSchema,
          activeHoldingSchema,
          exitReviewHoldingSchema,
        ]),
      )
      .length(5),
  })
  .strict()
  .superRefine((input, context) => {
    if (
      input.state === "USER_INPUT_RECORDED_UNCLASSIFIED" &&
      input.holdings.some(
        (holding) => holding.classification_state !== "UNCLASSIFIED",
      )
    ) {
      context.addIssue({
        code: "custom",
        path: ["holdings"],
        message:
          "Recorded unclassified input may contain only UNCLASSIFIED rows",
      });
    }
  });

export const unclassifiedQueuePreviewInputSchema =
  portfolioMandateA2PrivateInputSchema.superRefine((input, context) => {
    if (input.state !== "USER_INPUT_RECORDED_UNCLASSIFIED") {
      context.addIssue({
        code: "custom",
        path: ["state"],
        message: "Local queue preview requires recorded unclassified input",
      });
    }
    if (
      input.holdings.some(
        (holding) => holding.classification_state !== "UNCLASSIFIED",
      )
    ) {
      context.addIssue({
        code: "custom",
        path: ["holdings"],
        message: "Local queue preview accepts only UNCLASSIFIED rows",
      });
    }
  });

type UnclassifiedHolding = z.infer<typeof unclassifiedHoldingSchema>;
type PrivateInput = z.infer<typeof portfolioMandateA2PrivateInputSchema>;

export type UnclassifiedQueuePreviewInput = Omit<
  PrivateInput,
  "state" | "holdings"
> & {
  state: "USER_INPUT_RECORDED_UNCLASSIFIED";
  holdings: UnclassifiedHolding[];
};

export function parseUnclassifiedQueuePreviewInput(
  value: unknown,
): UnclassifiedQueuePreviewInput {
  return unclassifiedQueuePreviewInputSchema.parse(
    value,
  ) as UnclassifiedQueuePreviewInput;
}
