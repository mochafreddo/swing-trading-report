import { z } from "zod";

const count = z.number().int().min(0).max(100000);
export const reviewFixtureVerificationSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("REPLAY"),
      run_id: z.string().uuid(),
      matched: z.literal(true),
      packet_sha256: z.string().regex(/^sha256:[a-f0-9]{64}$/),
      projection_sha256: z.string().regex(/^sha256:[a-f0-9]{64}$/),
    })
    .strict(),
  z
    .object({
      kind: z.literal("LOCAL_SINK"),
      run_id: z.string().uuid(),
      scope: z.literal("SYNTHETIC_OWNER"),
      destination: z.literal("LOCAL_REVIEW_SINK"),
      newly_received: count,
      total: count,
      received: count,
      pending: count,
      external_sends: z.literal(0),
    })
    .strict()
    .refine((v) => v.received + v.pending === v.total),
]);

export const reviewFixtureResultSchema = z
  .object({
    ok: z.literal(true),
    duplicate: z.boolean(),
    verification: reviewFixtureVerificationSchema.optional(),
  })
  .strict();
export type ReviewFixtureVerification = z.infer<
  typeof reviewFixtureVerificationSchema
>;

export function parseReviewFixtureResult(
  value: unknown,
  command: string,
  runId: string,
) {
  const result = reviewFixtureResultSchema.parse(value);
  const expectedKind =
    command === "replay"
      ? "REPLAY"
      : command === "receive"
        ? "LOCAL_SINK"
        : undefined;
  if (
    result.verification?.kind !== expectedKind ||
    (result.verification && result.verification.run_id !== runId)
  )
    throw new Error("FIXTURE_RESULT_MISMATCH");
  return result;
}
