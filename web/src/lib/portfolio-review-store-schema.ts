import { z } from "zod";

import { portfolioReviewR1Schema } from "./portfolio-dogfood-t14-schema";

export const portfolioReviewStoreSchema = z
  .object({
    schema_version: z.literal("portfolio-review-store.r2"),
    mode: z.literal("LOCAL_ONLY"),
    advice_enabled: z.literal(false),
    rows: z
      .array(
        z
          .object({
            mandate_version_id: z.string().uuid(),
            run_id: z.string().uuid().nullable(),
            run_status: z.enum(["COMPILED", "BLOCKED"]).nullable(),
            review: portfolioReviewR1Schema.shape.rows.element.nullable(),
            as_of: z.string().datetime({ offset: true }).nullable(),
            outcomes: z
              .array(
                z
                  .object({
                    outcome_id: z.string().uuid(),
                    status: z.enum(["UNLINKED", "AMBIGUOUS", "NO_ACTION"]),
                    basis: z.enum([
                      "ORDER_AGGREGATE_ONLY",
                      "USER_CONFIRMED_NO_ACTION",
                    ]),
                    supersedes_outcome_id: z.string().uuid().nullable(),
                  })
                  .strict(),
              )
              .max(1000),
          })
          .strict()
          .superRefine((row, ctx) => {
            const seen = new Set<string>();
            const superseded = new Set<string>();
            for (const outcome of row.outcomes) {
              const previous = outcome.supersedes_outcome_id;
              if (
                seen.has(outcome.outcome_id) ||
                (outcome.status === "NO_ACTION") !==
                  (outcome.basis === "USER_CONFIRMED_NO_ACTION") ||
                (previous !== null &&
                  (!seen.has(previous) || superseded.has(previous)))
              ) {
                ctx.addIssue({
                  code: "custom",
                  message: "Invalid outcome history",
                });
              }
              seen.add(outcome.outcome_id);
              if (previous !== null) superseded.add(previous);
            }
            if (
              row.run_id === null
                ? row.review !== null ||
                  row.run_status !== null ||
                  row.as_of !== null ||
                  row.outcomes.length > 0
                : row.review?.mandate_version_id !== row.mandate_version_id ||
                  row.run_status === null ||
                  row.as_of === null
            ) {
              ctx.addIssue({
                code: "custom",
                message: "Inconsistent stored review",
              });
            }
            if (
              row.run_status === "COMPILED" &&
              row.review?.status === "BLOCKED"
            ) {
              ctx.addIssue({
                code: "custom",
                message: "Blocked review cannot be compiled",
              });
            }
          }),
      )
      .min(1)
      .max(100),
  })
  .strict()
  .refine(
    (value) =>
      new Set(value.rows.map((r) => r.mandate_version_id)).size ===
      value.rows.length,
  );

export type PortfolioReviewStore = z.infer<typeof portfolioReviewStoreSchema>;
export type StoredReviewSource =
  | { state: "DISABLED" | "UNAVAILABLE" | "STALE" }
  | { state: "READY"; value: PortfolioReviewStore };
