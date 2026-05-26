import { NextRequest, NextResponse } from "next/server";

type ParsedJsonBody =
  | { ok: true; payload: unknown }
  | { ok: false; response: NextResponse };

export async function parseJsonBody(
  request: NextRequest,
): Promise<ParsedJsonBody> {
  try {
    const payload = await request.json();
    return { ok: true, payload };
  } catch {
    return {
      ok: false,
      response: NextResponse.json(
        { error: "Request body must be valid JSON" },
        { status: 400 },
      ),
    };
  }
}
