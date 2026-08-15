import { z } from "zod";

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

export type RunJournalV0 = z.infer<typeof runJournalV0Schema>;
