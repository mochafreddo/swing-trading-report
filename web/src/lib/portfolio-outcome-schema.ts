import { z } from "zod";

const canonicalUuidO1Schema = z
  .uuid()
  .regex(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u,
  );
const timestampO1Schema = z
  .string()
  .regex(/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/u)
  .pipe(z.iso.datetime({ offset: false, precision: 3 }));
const decimalO1Schema = z.string().regex(/^(0|[1-9][0-9]*)\.[0-9]{6}$/u);
const accountRefHashO1Schema = z
  .string()
  .regex(/^hmac-sha256:v1:[0-9a-f]{64}$/u);
const brokerIdentifierO1Schema = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u);

export const outcomeStatusO1Schema = z.enum([
  "UNLINKED",
  "MATCH_PROPOSED",
  "AMBIGUOUS",
  "MATCH_CONFIRMED",
  "EXECUTED",
  "PARTIALLY_EXECUTED",
  "DISMISSED",
  "NO_ACTION",
  "UNKNOWN",
]);
const userOutcomeStatusO1Schema = z.enum([
  "MATCH_CONFIRMED",
  "EXECUTED",
  "PARTIALLY_EXECUTED",
  "DISMISSED",
  "UNKNOWN",
]);
const feedbackReasonO1Schema = z.enum([
  "EVIDENCE_DISAGREEMENT",
  "TIMING_OR_PRICE",
  "POSITION_RISK",
  "LIQUIDITY_OR_CASH",
  "EXTERNAL_CONSTRAINT",
  "CHANGED_MIND",
  "OTHER",
]);

const capabilityO1Schema = z
  .object({
    input_mode: z.literal("SYNTHETIC_ONLY"),
    provider_history_state: z.literal("NOT_EVALUATED"),
    retention_window: z
      .object({
        starts_at: timestampO1Schema,
        ends_at: timestampO1Schema,
        pagination_state: z.literal("SYNTHETIC_COMPLETE"),
      })
      .strict(),
    partial_fill_mode: z.literal("SUM_BY_EXECUTION_LINEAGE"),
    cancel_reorder_mode: z.literal("EXPLICIT_ORDER_LINEAGE"),
    automatic_match_confirmation: z.literal(false),
    performance_attribution: z.literal("DISABLED"),
  })
  .strict();

const rangeO1Schema = z
  .object({
    minimum: decimalO1Schema,
    maximum: decimalO1Schema,
  })
  .strict()
  .superRefine((range, context) => {
    if (
      decimalToUnits(range.minimum) <= 0n ||
      decimalToUnits(range.maximum) < decimalToUnits(range.minimum)
    ) {
      context.addIssue({
        code: "custom",
        message: "range must be positive and ordered",
      });
    }
  });

const decisionO1Schema = z
  .object({
    decision_id: canonicalUuidO1Schema,
    instrument_id: canonicalUuidO1Schema,
    slice_id: canonicalUuidO1Schema.nullable(),
    candidate_id: canonicalUuidO1Schema.nullable(),
    side: z.enum(["BUY", "SELL"]),
    valid_from: timestampO1Schema,
    valid_until: timestampO1Schema,
    price_range: rangeO1Schema,
    quantity_range: rangeO1Schema,
  })
  .strict()
  .superRefine((decision, context) => {
    if ((decision.slice_id === null) === (decision.candidate_id === null)) {
      context.addIssue({
        code: "custom",
        path: ["slice_id"],
        message: "exactly one of slice_id or candidate_id is required",
      });
    }
    if (
      (decision.slice_id !== null && decision.side !== "SELL") ||
      (decision.candidate_id !== null && decision.side !== "BUY")
    ) {
      context.addIssue({
        code: "custom",
        path: ["side"],
        message: "slice decisions are SELL; candidate decisions are BUY",
      });
    }
    if (decision.valid_from >= decision.valid_until) {
      context.addIssue({
        code: "custom",
        path: ["valid_until"],
        message: "must be later than valid_from",
      });
    }
  });

const orderO1Schema = z
  .object({
    broker_order_id: brokerIdentifierO1Schema,
    supersedes_broker_order_id: brokerIdentifierO1Schema.nullable(),
    state: z.enum(["CANCELED", "PARTIALLY_FILLED", "FILLED"]),
    created_at: timestampO1Schema,
  })
  .strict();
const fillO1Schema = z
  .object({
    broker_order_id: brokerIdentifierO1Schema,
    broker_fill_id: brokerIdentifierO1Schema,
    executed_at: timestampO1Schema,
    price: decimalO1Schema,
    quantity: decimalO1Schema,
  })
  .strict();

const executionLineageO1Schema = z
  .object({
    execution_lineage_id: canonicalUuidO1Schema,
    outcome_lineage_id: canonicalUuidO1Schema,
    account_ref_hash: accountRefHashO1Schema,
    instrument_id: canonicalUuidO1Schema,
    side: z.enum(["BUY", "SELL"]),
    slice_candidate_ids: z.array(canonicalUuidO1Schema),
    candidate_id: canonicalUuidO1Schema.nullable(),
    orders: z.array(orderO1Schema).min(1),
    fills: z.array(fillO1Schema).min(1),
  })
  .strict()
  .superRefine((execution, context) => {
    const hasSlices = execution.slice_candidate_ids.length > 0;
    if (hasSlices === (execution.candidate_id !== null)) {
      context.addIssue({
        code: "custom",
        path: ["slice_candidate_ids"],
        message:
          "holding execution needs slices; candidate execution needs only candidate_id",
      });
    }
    if (
      (hasSlices && execution.side !== "SELL") ||
      (execution.candidate_id !== null && execution.side !== "BUY")
    ) {
      context.addIssue({
        code: "custom",
        path: ["side"],
        message: "slice executions are SELL; candidate executions are BUY",
      });
    }
    if (
      new Set(execution.slice_candidate_ids).size !==
      execution.slice_candidate_ids.length
    ) {
      context.addIssue({
        code: "custom",
        path: ["slice_candidate_ids"],
        message: "slice candidates must be unique",
      });
    }
    const orderIds = new Set<string>();
    execution.orders.forEach((order, index) => {
      if (orderIds.has(order.broker_order_id)) {
        context.addIssue({
          code: "custom",
          path: ["orders", index, "broker_order_id"],
          message: "broker order IDs must be unique in a lineage",
        });
      }
      orderIds.add(order.broker_order_id);
      const prior = execution.orders[index - 1];
      if (
        (prior === undefined && order.supersedes_broker_order_id !== null) ||
        (prior !== undefined &&
          (order.supersedes_broker_order_id !== prior.broker_order_id ||
            order.created_at <= prior.created_at))
      ) {
        context.addIssue({
          code: "custom",
          path: ["orders", index, "supersedes_broker_order_id"],
          message: "orders must form an ordered direct cancel/reorder lineage",
        });
      }
    });
    execution.fills.forEach((fill, index) => {
      const order = execution.orders.find(
        (candidate) => candidate.broker_order_id === fill.broker_order_id,
      );
      if (order === undefined || fill.executed_at < order.created_at) {
        context.addIssue({
          code: "custom",
          path: ["fills", index, "broker_order_id"],
          message: "fill must reference a preceding order in this lineage",
        });
      }
      if (
        decimalToUnits(fill.price) <= 0n ||
        decimalToUnits(fill.quantity) <= 0n
      ) {
        context.addIssue({
          code: "custom",
          path: ["fills", index],
          message: "price and quantity must be positive",
        });
      }
    });
  });

const proposalO1Schema = z
  .object({
    outcome_lineage_id: canonicalUuidO1Schema,
    execution_lineage_id: canonicalUuidO1Schema,
    status: z.enum(["UNLINKED", "MATCH_PROPOSED", "AMBIGUOUS"]),
    candidate_decision_ids: z.array(canonicalUuidO1Schema),
    total_filled_quantity: decimalO1Schema,
  })
  .strict();

const userEventO1Schema = z
  .object({
    outcome_event_id: canonicalUuidO1Schema,
    outcome_lineage_id: canonicalUuidO1Schema,
    event_kind: z.enum(["MATCH_CONFIRMATION", "CORRECTION", "FEEDBACK"]),
    actor_kind: z.literal("USER"),
    status: userOutcomeStatusO1Schema,
    decision_id: canonicalUuidO1Schema.nullable(),
    confirmed_quantity: decimalO1Schema.nullable(),
    feedback_reason: feedbackReasonO1Schema.nullable(),
    feedback_note_private: z.string().min(1).max(1000).nullable(),
    supersedes_event_id: canonicalUuidO1Schema.nullable(),
    created_at: timestampO1Schema,
  })
  .strict()
  .superRefine((event, context) => {
    if (
      event.feedback_reason === "OTHER" &&
      event.feedback_note_private === null
    ) {
      context.addIssue({
        code: "custom",
        path: ["feedback_note_private"],
        message: "OTHER requires a nonempty private note",
      });
    }
    if (
      event.feedback_reason === null &&
      event.feedback_note_private !== null
    ) {
      context.addIssue({
        code: "custom",
        path: ["feedback_note_private"],
        message: "private note requires feedback_reason",
      });
    }
    const linked = [
      "MATCH_CONFIRMED",
      "EXECUTED",
      "PARTIALLY_EXECUTED",
    ].includes(event.status);
    if (
      (linked &&
        (event.decision_id === null || event.confirmed_quantity === null)) ||
      (!linked &&
        (event.decision_id !== null || event.confirmed_quantity !== null))
    ) {
      context.addIssue({
        code: "custom",
        path: ["status"],
        message:
          "linked statuses require decision and quantity; DISMISSED/UNKNOWN require nulls",
      });
    }
  });

export const portfolioOutcomePublicProjectionO1Schema = z
  .object({
    outcome_lineage_id: canonicalUuidO1Schema,
    status: userOutcomeStatusO1Schema,
    decision_id: canonicalUuidO1Schema.nullable(),
    feedback_reason: feedbackReasonO1Schema.nullable(),
    last_event_id: canonicalUuidO1Schema,
    last_event_at: timestampO1Schema,
  })
  .strict()
  .superRefine((projection, context) => {
    const unlinked = ["DISMISSED", "UNKNOWN"].includes(projection.status);
    if (
      (unlinked && projection.decision_id !== null) ||
      (!unlinked && projection.decision_id === null)
    ) {
      context.addIssue({
        code: "custom",
        path: ["decision_id"],
        message: "public decision binding must match the projected status",
      });
    }
  });

const baseFixtureO1Schema = z
  .object({
    schema_version: z.literal("portfolio-outcome.o1"),
    capability: capabilityO1Schema,
    decisions: z.array(decisionO1Schema).min(1),
    execution_lineages: z.array(executionLineageO1Schema).min(1),
    user_events: z.array(userEventO1Schema),
    expected_proposals: z.array(proposalO1Schema),
    expected_public_projection: z.array(
      portfolioOutcomePublicProjectionO1Schema,
    ),
  })
  .strict();

type DecisionO1 = z.infer<typeof decisionO1Schema>;
type ExecutionLineageO1 = z.infer<typeof executionLineageO1Schema>;
type UserEventO1 = z.infer<typeof userEventO1Schema>;
export type OutcomeProposalO1 = z.infer<typeof proposalO1Schema>;
export type PublicOutcomeProjectionO1 = z.infer<
  typeof portfolioOutcomePublicProjectionO1Schema
>;

export const portfolioOutcomeO1FixtureSchema = baseFixtureO1Schema.superRefine(
  (fixture, context) => {
    const { starts_at: retentionStart, ends_at: retentionEnd } =
      fixture.capability.retention_window;
    if (retentionStart >= retentionEnd) {
      context.addIssue({
        code: "custom",
        path: ["capability", "retention_window", "ends_at"],
        message: "must be later than starts_at",
      });
    }
    addDuplicateIssues(
      fixture.decisions.map((decision) => decision.decision_id),
      ["decisions"],
      "decision IDs",
      context,
    );
    addDuplicateIssues(
      fixture.execution_lineages.map(
        (execution) => execution.execution_lineage_id,
      ),
      ["execution_lineages"],
      "execution lineage IDs",
      context,
    );
    addDuplicateIssues(
      fixture.execution_lineages.map(
        (execution) => execution.outcome_lineage_id,
      ),
      ["execution_lineages"],
      "outcome lineage IDs",
      context,
    );

    const fillIdentities = new Set<string>();
    fixture.execution_lineages.forEach((execution, executionIndex) => {
      execution.fills.forEach((fill, fillIndex) => {
        if (
          fill.executed_at < retentionStart ||
          fill.executed_at > retentionEnd
        ) {
          context.addIssue({
            code: "custom",
            path: [
              "execution_lineages",
              executionIndex,
              "fills",
              fillIndex,
              "executed_at",
            ],
            message: "must be inside synthetic retention window",
          });
        }
        const identity = [
          fill.broker_order_id,
          fill.broker_fill_id,
          execution.account_ref_hash,
        ].join("\u0000");
        if (fillIdentities.has(identity)) {
          context.addIssue({
            code: "custom",
            path: ["execution_lineages", executionIndex, "fills", fillIndex],
            message: "broker order, fill, and account hash must be unique",
          });
        }
        fillIdentities.add(identity);
      });
    });

    const proposals = proposeOutcomeMatchesO1(
      fixture.decisions,
      fixture.execution_lineages,
    );
    if (
      JSON.stringify(proposals) !== JSON.stringify(fixture.expected_proposals)
    ) {
      context.addIssue({
        code: "custom",
        path: ["expected_proposals"],
        message: "must equal deterministic synthetic matcher output",
      });
    }
    validateEventHistory(fixture, proposals, context);
    const projection = projectPublicOutcomeEventsO1(fixture.user_events);
    if (
      JSON.stringify(projection) !==
      JSON.stringify(fixture.expected_public_projection)
    ) {
      context.addIssue({
        code: "custom",
        path: ["expected_public_projection"],
        message: "must equal latest append-only user event projection",
      });
    }
  },
);

export function proposeOutcomeMatchesO1(
  decisions: readonly DecisionO1[],
  executionLineages: readonly ExecutionLineageO1[],
): OutcomeProposalO1[] {
  return executionLineages.map((execution) => {
    const totalUnits = execution.fills.reduce(
      (total, fill) => total + decimalToUnits(fill.quantity),
      0n,
    );
    const candidates = decisions
      .filter((decision) => matchesDecision(decision, execution, totalUnits))
      .map((decision) => decision.decision_id)
      .sort();
    return {
      outcome_lineage_id: execution.outcome_lineage_id,
      execution_lineage_id: execution.execution_lineage_id,
      status:
        candidates.length === 0
          ? "UNLINKED"
          : candidates.length === 1
            ? "MATCH_PROPOSED"
            : "AMBIGUOUS",
      candidate_decision_ids: candidates,
      total_filled_quantity: unitsToDecimal(totalUnits),
    };
  });
}

export function projectPublicOutcomeEventsO1(
  events: readonly UserEventO1[],
): PublicOutcomeProjectionO1[] {
  const latest = new Map<string, UserEventO1>();
  events.forEach((event) => latest.set(event.outcome_lineage_id, event));
  return [...latest.entries()].map(([lineageId, event]) => ({
    outcome_lineage_id: lineageId,
    status: event.status,
    decision_id: event.decision_id,
    feedback_reason: event.feedback_reason,
    last_event_id: event.outcome_event_id,
    last_event_at: event.created_at,
  }));
}

export function parsePortfolioOutcomeO1Fixture(value: unknown) {
  return portfolioOutcomeO1FixtureSchema.parse(value);
}

export function parsePortfolioOutcomePublicProjectionO1(value: unknown) {
  return portfolioOutcomePublicProjectionO1Schema.parse(value);
}

function matchesDecision(
  decision: DecisionO1,
  execution: ExecutionLineageO1,
  totalUnits: bigint,
): boolean {
  if (
    decision.instrument_id !== execution.instrument_id ||
    decision.side !== execution.side
  ) {
    return false;
  }
  const targetMatches =
    (decision.slice_id !== null &&
      execution.candidate_id === null &&
      execution.slice_candidate_ids.includes(decision.slice_id)) ||
    (decision.candidate_id !== null &&
      execution.slice_candidate_ids.length === 0 &&
      decision.candidate_id === execution.candidate_id);
  return (
    targetMatches &&
    decimalToUnits(decision.quantity_range.minimum) <= totalUnits &&
    totalUnits <= decimalToUnits(decision.quantity_range.maximum) &&
    execution.fills.every(
      (fill) =>
        decision.valid_from <= fill.executed_at &&
        fill.executed_at <= decision.valid_until &&
        decimalToUnits(decision.price_range.minimum) <=
          decimalToUnits(fill.price) &&
        decimalToUnits(fill.price) <=
          decimalToUnits(decision.price_range.maximum),
    )
  );
}

function validateEventHistory(
  fixture: z.infer<typeof baseFixtureO1Schema>,
  proposals: readonly OutcomeProposalO1[],
  context: z.RefinementCtx,
) {
  const proposalByLineage = new Map(
    proposals.map((proposal) => [proposal.outcome_lineage_id, proposal]),
  );
  const knownDecisions = new Set(
    fixture.decisions.map((decision) => decision.decision_id),
  );
  const eventIds = new Set<string>();
  const heads = new Map<string, UserEventO1>();
  fixture.user_events.forEach((event, index) => {
    const path = ["user_events", index] as const;
    if (eventIds.has(event.outcome_event_id)) {
      context.addIssue({
        code: "custom",
        path: [...path, "outcome_event_id"],
        message: "event ID must be unique and immutable",
      });
    }
    eventIds.add(event.outcome_event_id);
    const proposal = proposalByLineage.get(event.outcome_lineage_id);
    if (proposal === undefined) {
      context.addIssue({
        code: "custom",
        path: [...path, "outcome_lineage_id"],
        message: "must reference a known outcome lineage",
      });
    }
    if (event.decision_id !== null && !knownDecisions.has(event.decision_id)) {
      context.addIssue({
        code: "custom",
        path: [...path, "decision_id"],
        message: "must reference a known synthetic decision",
      });
    }
    if (
      proposal !== undefined &&
      event.decision_id !== null &&
      !proposal.candidate_decision_ids.includes(event.decision_id)
    ) {
      context.addIssue({
        code: "custom",
        path: [...path, "decision_id"],
        message: "must belong to this outcome lineage deterministic proposal",
      });
    }
    if (
      event.confirmed_quantity !== null &&
      decimalToUnits(event.confirmed_quantity) <= 0n
    ) {
      context.addIssue({
        code: "custom",
        path: [...path, "confirmed_quantity"],
        message: "must be positive when present",
      });
    }
    const prior = heads.get(event.outcome_lineage_id);
    if (prior === undefined) {
      if (
        event.event_kind !== "MATCH_CONFIRMATION" ||
        event.status !== "MATCH_CONFIRMED" ||
        event.supersedes_event_id !== null ||
        event.decision_id === null ||
        event.confirmed_quantity === null ||
        event.confirmed_quantity !== proposal?.total_filled_quantity ||
        event.feedback_reason !== null ||
        event.feedback_note_private !== null
      ) {
        context.addIssue({
          code: "custom",
          path: [...path],
          message: "first lineage event must be a user confirmation snapshot",
        });
      }
    } else {
      if (event.supersedes_event_id !== prior.outcome_event_id) {
        context.addIssue({
          code: "custom",
          path: [...path, "supersedes_event_id"],
          message: "must supersede the current head in the same lineage",
        });
      }
      if (event.created_at <= prior.created_at) {
        context.addIssue({
          code: "custom",
          path: [...path, "created_at"],
          message: "must be later than the superseded event",
        });
      }
      if (
        event.event_kind === "MATCH_CONFIRMATION" ||
        (event.event_kind === "FEEDBACK" &&
          (event.feedback_reason === null ||
            event.status !== prior.status ||
            event.decision_id !== prior.decision_id ||
            event.confirmed_quantity !== prior.confirmed_quantity))
      ) {
        context.addIssue({
          code: "custom",
          path: [...path, "event_kind"],
          message:
            "feedback preserves matching state; confirmation occurs once",
        });
      }
    }
    heads.set(event.outcome_lineage_id, event);
  });
}

function addDuplicateIssues(
  values: readonly string[],
  path: PropertyKey[],
  label: string,
  context: z.RefinementCtx,
) {
  if (new Set(values).size !== values.length) {
    context.addIssue({
      code: "custom",
      path,
      message: `${label} must be unique`,
    });
  }
}

function decimalToUnits(value: string): bigint {
  const [whole, fraction] = value.split(".");
  return BigInt(whole) * 1_000_000n + BigInt(fraction);
}

function unitsToDecimal(value: bigint): string {
  const whole = value / 1_000_000n;
  const fraction = (value % 1_000_000n).toString().padStart(6, "0");
  return `${whole}.${fraction}`;
}
