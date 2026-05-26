import { NextResponse } from "next/server";

const REPORTS_CACHE_CONTROL = "private, no-store, max-age=0, must-revalidate";

export function jsonWithNoStore(
  payload: unknown,
  init?: {
    status?: number;
    headers?: HeadersInit;
  },
): NextResponse {
  const headers = new Headers(init?.headers);
  headers.set("Cache-Control", REPORTS_CACHE_CONTROL);
  return NextResponse.json(payload, {
    status: init?.status,
    headers,
  });
}
