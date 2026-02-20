import { describe, expect, it } from "vitest";

import { requestLogout } from "@/lib/logout-client";

describe("logout-client", () => {
  it("resolves when logout API succeeds", async () => {
    const fetcher = async () => new Response(JSON.stringify({ ok: true }));
    await expect(requestLogout(fetcher)).resolves.toBeUndefined();
  });

  it("throws API error message on failed logout", async () => {
    const fetcher = async () =>
      new Response(JSON.stringify({ error: "Session revoke failed" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      });

    await expect(requestLogout(fetcher)).rejects.toThrow(
      "Session revoke failed",
    );
  });

  it("throws fallback message on failed non-json response", async () => {
    const fetcher = async () =>
      new Response("bad gateway", {
        status: 502,
        headers: { "content-type": "text/plain" },
      });

    await expect(requestLogout(fetcher)).rejects.toThrow("Sign out failed");
  });
});
