import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { parseJsonBody } from "@/lib/parse-json-body";

function makeRequest(body: string, headers: HeadersInit = {}): NextRequest {
  return new NextRequest("http://localhost:55300/api/test", {
    method: "POST",
    headers,
    body,
  });
}

describe("parseJsonBody", () => {
  it("rejects non-application/json request bodies before parsing", async () => {
    const body = await parseJsonBody(
      makeRequest('{"ok":true}', { "content-type": "text/plain" }),
    );

    expect(body.ok).toBe(false);
    if (!body.ok) {
      expect(body.response.status).toBe(415);
      await expect(body.response.json()).resolves.toEqual({
        error: "Request body must be application/json",
      });
    }
  });

  it("rejects bodies larger than the configured limit before JSON parsing", async () => {
    const body = await parseJsonBody(
      makeRequest('{"value":"123456"}', { "content-type": "application/json" }),
      { maxBytes: 12 },
    );

    expect(body.ok).toBe(false);
    if (!body.ok) {
      expect(body.response.status).toBe(413);
      await expect(body.response.json()).resolves.toEqual({
        error: "Request body is too large",
      });
    }
  });

  it("accepts application/json with charset parameters", async () => {
    const body = await parseJsonBody(
      makeRequest('{"ok":true}', {
        "content-type": "application/json; charset=utf-8",
      }),
    );

    expect(body).toEqual({ ok: true, payload: { ok: true } });
  });
});
