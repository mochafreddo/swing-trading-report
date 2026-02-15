import { NextRequest, NextResponse } from "next/server";

import { dispatchWorkflow, GitHubDispatchError } from "@/lib/github-actions";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { runDispatchSchema } from "@/lib/schemas";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  try {
    assertLocalRequest(request);
  } catch (error) {
    if (error instanceof LocalRequestGuardError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Request body must be valid JSON" },
      { status: 400 },
    );
  }

  const parsed = runDispatchSchema.safeParse(payload);
  if (!parsed.success) {
    return NextResponse.json(
      {
        error: "Invalid run payload",
        details: parsed.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const dispatched = await dispatchWorkflow(parsed.data);
    return NextResponse.json(dispatched, { status: 202 });
  } catch (error) {
    if (error instanceof GitHubDispatchError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }

    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
