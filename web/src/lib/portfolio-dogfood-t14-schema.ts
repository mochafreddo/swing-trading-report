import { z } from "zod";

const uuidSchema = z.string().uuid();
const timestampSchema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
const tickerSchema = z.string().regex(/^[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*$/);

const publicProjectionSchema = z
  .object({
    outcome_lineage_id: uuidSchema,
    status: z.enum([
      "MATCH_CONFIRMED",
      "EXECUTED",
      "PARTIALLY_EXECUTED",
      "DISMISSED",
      "UNKNOWN",
    ]),
    decision_id: uuidSchema.nullable(),
    feedback_reason: z
      .enum([
        "EVIDENCE_DISAGREEMENT",
        "TIMING_OR_PRICE",
        "POSITION_RISK",
        "LIQUIDITY_OR_CASH",
        "EXTERNAL_CONSTRAINT",
        "CHANGED_MIND",
        "OTHER",
      ])
      .nullable(),
    last_event_id: uuidSchema,
    last_event_at: timestampSchema,
  })
  .strict();

const scenarioSchema = z
  .object({
    scenario_id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/),
    label: z.string().trim().min(1).max(40),
    instrument: z
      .object({
        instrument_id: uuidSchema,
        canonical_ticker: tickerSchema,
        company_name: z.string().trim().min(1).max(160),
      })
      .strict(),
    mandate: z
      .object({
        state: z.literal("APPROVED"),
        horizon: z.literal("LONG_TERM"),
        thesis: z.string().trim().min(1).max(1000),
        predicate: z.string().trim().min(1).max(240),
      })
      .strict(),
    evidence: z
      .object({
        state: z.enum(["VALID", "STALE", "CONFLICTED"]),
        issue_code: z
          .enum(["EVIDENCE_STALE", "EVIDENCE_CONFLICTED"])
          .nullable(),
        items: z
          .array(
            z
              .object({
                role: z.enum(["SUPPORTING", "OPPOSING"]),
                source_url: z
                  .string()
                  .url()
                  .refine((value) => value.startsWith("https://")),
                publisher: z.string().trim().min(1).max(160),
                published_at: timestampSchema,
                supporting_span: z.string().trim().min(1).max(4096),
              })
              .strict(),
          )
          .min(1),
      })
      .strict(),
    outcome: z
      .object({
        state: z.enum([
          "CORRECTED",
          "EMPTY",
          "LOADING",
          "BLOCKED",
          "AMBIGUOUS",
        ]),
        issue_code: z
          .enum(["EVIDENCE_CONFLICTED", "EVIDENCE_STALE", "AMBIGUOUS_MATCH"])
          .nullable(),
        prior_event_count: z.number().int().min(0),
        public_projection: publicProjectionSchema.nullable(),
      })
      .strict(),
  })
  .strict()
  .superRefine((scenario, context) => {
    const expectedEvidenceIssue =
      scenario.evidence.state === "CONFLICTED"
        ? "EVIDENCE_CONFLICTED"
        : scenario.evidence.state === "STALE"
          ? "EVIDENCE_STALE"
          : null;
    if (scenario.evidence.issue_code !== expectedEvidenceIssue) {
      context.addIssue({
        code: "custom",
        path: ["evidence", "issue_code"],
        message: "evidence issue must match its state",
      });
    }
    const projectionRequired = scenario.outcome.state === "CORRECTED";
    if (projectionRequired !== (scenario.outcome.public_projection !== null)) {
      context.addIssue({
        code: "custom",
        path: ["outcome", "public_projection"],
        message: "only CORRECTED scenarios carry a public projection",
      });
    }
    if (
      scenario.outcome.state === "BLOCKED" &&
      (expectedEvidenceIssue === null ||
        scenario.outcome.issue_code !== expectedEvidenceIssue)
    ) {
      context.addIssue({
        code: "custom",
        path: ["outcome"],
        message: "BLOCKED requires matching stale or conflicted evidence",
      });
    }
    if (
      scenario.outcome.state === "AMBIGUOUS" &&
      (scenario.evidence.state !== "VALID" ||
        scenario.outcome.issue_code !== "AMBIGUOUS_MATCH")
    ) {
      context.addIssue({
        code: "custom",
        path: ["outcome"],
        message: "AMBIGUOUS requires valid evidence and an ambiguous match",
      });
    }
    if (
      !["BLOCKED", "AMBIGUOUS"].includes(scenario.outcome.state) &&
      scenario.outcome.issue_code !== null
    ) {
      context.addIssue({
        code: "custom",
        path: ["outcome", "issue_code"],
        message: "only blocked or ambiguous outcomes carry an issue",
      });
    }
  });

const fixtureSchema = z
  .object({
    schema_version: z.literal("portfolio-dogfood.t14"),
    mode: z.literal("SYNTHETIC_ONLY"),
    provider_history_state: z.literal("NOT_EVALUATED"),
    scenarios: z.array(scenarioSchema).min(1),
  })
  .strict()
  .superRefine((fixture, context) => {
    const seen = new Set<string>();
    fixture.scenarios.forEach((scenario, index) => {
      if (seen.has(scenario.scenario_id)) {
        context.addIssue({
          code: "custom",
          path: ["scenarios", index, "scenario_id"],
          message: "scenario_id must be unique",
        });
      }
      seen.add(scenario.scenario_id);
    });
  });

export type PortfolioDogfoodT14Fixture = z.infer<typeof fixtureSchema>;
export type TodayDogfoodSelection =
  | { state: "DEFAULT" }
  | { state: "INVALID" }
  | { state: "INVALID_FIXTURE" }
  | { state: "SELECTED"; scenarioId: string };
export type PortfolioDogfoodT14Source =
  | { state: "READY"; fixture: PortfolioDogfoodT14Fixture }
  | { state: "INVALID"; issueCode: "FIXTURE_CONTRACT_INVALID" };

export function parsePortfolioDogfoodT14Source(
  value: unknown,
): PortfolioDogfoodT14Source {
  const parsed = fixtureSchema.safeParse(value);
  return parsed.success
    ? { state: "READY", fixture: parsed.data }
    : { state: "INVALID", issueCode: "FIXTURE_CONTRACT_INVALID" };
}
