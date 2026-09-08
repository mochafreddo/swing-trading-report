import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { parseJsonBody } from "@/lib/parse-json-body";
import {
  fixtureRequest,
  liveReviewFixtureOrigin,
} from "@/lib/portfolio-review-fixture.server";

const commandSchema = z
  .object({
    command: z.enum([
      "compile",
      "block",
      "correct",
      "unlinked",
      "ambiguous",
      "no_action",
    ]),
    request_id: z.string().uuid(),
    run_id: z.string().uuid(),
  })
  .strict();

export async function POST(request: NextRequest) {
  const fail = (status: number) =>
    NextResponse.json(
      { error: "FIXTURE_REQUEST_REJECTED" },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  if (!liveReviewFixtureOrigin()) return fail(404);
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) return fail(guardError.status);
  try {
    const parsed = await parseJsonBody(request, { maxBytes: 1024 });
    if (!parsed.ok) return fail(parsed.response.status);
    const command = commandSchema.parse(parsed.payload);
    const response = await fixtureRequest("/command", JSON.stringify(command));
    if (!response.ok) return fail(409);
    const result = z
      .object({ ok: z.literal(true), duplicate: z.boolean() })
      .strict()
      .parse(await response.json());
    return NextResponse.json(result, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return fail(403);
  }
}
