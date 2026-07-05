import { NextRequest, type NextResponse } from "next/server";

import { jsonWithNoStore } from "@/lib/reports-response";

type ParsedJsonBody =
  { ok: true; payload: unknown } | { ok: false; response: NextResponse };

type ParseJsonBodyOptions = {
  maxBytes?: number;
};

const DEFAULT_MAX_JSON_BODY_BYTES = 64 * 1024;

function jsonError(error: string, status: number): ParsedJsonBody {
  return {
    ok: false,
    response: jsonWithNoStore({ error }, { status }),
  };
}

function hasJsonContentType(request: NextRequest): boolean {
  const contentType = request.headers.get("content-type");
  if (!contentType) {
    return false;
  }
  const mediaType = contentType.split(";", 1)[0]?.trim().toLowerCase();
  return mediaType === "application/json";
}

async function readTextBodyWithLimit(
  request: NextRequest,
  maxBytes: number,
): Promise<{ ok: true; text: string } | { ok: false }> {
  const contentLength = request.headers.get("content-length");
  if (contentLength) {
    const byteLength = Number(contentLength);
    if (Number.isFinite(byteLength) && byteLength > maxBytes) {
      return { ok: false };
    }
  }

  if (!request.body) {
    return { ok: true, text: "" };
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let byteLength = 0;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    if (!value) {
      continue;
    }
    byteLength += value.byteLength;
    if (byteLength > maxBytes) {
      await reader.cancel();
      return { ok: false };
    }
    chunks.push(value);
  }

  return {
    ok: true,
    text: new TextDecoder().decode(
      chunks.length === 1 ? chunks[0] : Buffer.concat(chunks),
    ),
  };
}

export async function parseJsonBody(
  request: NextRequest,
  options: ParseJsonBodyOptions = {},
): Promise<ParsedJsonBody> {
  if (!hasJsonContentType(request)) {
    return jsonError("Request body must be application/json", 415);
  }

  const maxBytes = options.maxBytes ?? DEFAULT_MAX_JSON_BODY_BYTES;
  const body = await readTextBodyWithLimit(request, maxBytes);
  if (!body.ok) {
    return jsonError("Request body is too large", 413);
  }

  try {
    const payload = JSON.parse(body.text) as unknown;
    return { ok: true, payload };
  } catch {
    return jsonError("Request body must be valid JSON", 400);
  }
}
