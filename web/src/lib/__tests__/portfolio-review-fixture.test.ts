import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  liveReviewFixtureOrigin,
  readLiveReviewFixture,
} from "../portfolio-review-fixture.server";
import { POST } from "@/app/api/portfolio-review-fixture/route";
import fixture from "../../../fixtures/portfolio-review-store.r2.synthetic.json";

const auth = vi.hoisted(() => vi.fn());
vi.mock("@/lib/admin-auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/admin-auth")>()),
  requireAdminAuth: auth,
}));
import { AdminAuthError } from "@/lib/admin-auth";
const command = {
  command: "compile",
  request_id: "00000000-0000-4000-8000-000000000001",
  run_id: "00000000-0000-4000-8000-000000000002",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const request = (body: unknown = command, origin = "http://localhost:43317") =>
  new NextRequest("http://localhost:43317/api/portfolio-review-fixture", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin },
    body: JSON.stringify(body),
  });

beforeEach(() => {
  vi.stubEnv("SAB_SKIP_ROOT_ENV", "1");
  vi.stubEnv("SAB_PORTFOLIO_R2_FIXTURE", "1");
  vi.stubEnv("PORTFOLIO_REVIEW_LIVE_PORT", "43419");
  auth.mockResolvedValue(undefined);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each(["", "443", "65536", "43419/path", "evil.invalid:43419"])(
  "rejects unbounded/non-loopback configuration %s",
  async (port) => {
    vi.stubEnv("PORTFOLIO_REVIEW_LIVE_PORT", port);
    const network = vi.fn();
    vi.stubGlobal("fetch", network);
    expect(liveReviewFixtureOrigin()).toBeNull();
    expect(await readLiveReviewFixture()).toEqual({ state: "DISABLED" });
    expect((await POST(request())).status).toBe(404);
    expect(network).not.toHaveBeenCalled();
  },
);
it("requires both fixture opt-ins and an admin session before IO", async () => {
  const network = vi.fn();
  vi.stubGlobal("fetch", network);
  vi.stubEnv("SAB_SKIP_ROOT_ENV", "0");
  expect((await POST(request())).status).toBe(404);
  vi.stubEnv("SAB_SKIP_ROOT_ENV", "1");
  vi.stubEnv("SAB_PORTFOLIO_R2_FIXTURE", "0");
  expect((await POST(request())).status).toBe(404);
  vi.stubEnv("SAB_PORTFOLIO_R2_FIXTURE", "1");
  auth.mockRejectedValue(new AdminAuthError());
  expect((await POST(request())).status).toBe(401);
  expect(network).not.toHaveBeenCalled();
});
it("rejects cross-origin, oversized, and arbitrary owner/SQL commands before IO", async () => {
  const network = vi.fn();
  vi.stubGlobal("fetch", network);
  expect((await POST(request(command, "https://evil.invalid"))).status).toBe(
    403,
  );
  expect(
    (await POST(request({ ...command, owner: command.run_id }))).status,
  ).toBe(403);
  expect(
    (await POST(request({ ...command, command: "select 1" }))).status,
  ).toBe(403);
  expect((await POST(request({ padding: "x".repeat(2048) }))).status).toBe(413);
  expect(network).not.toHaveBeenCalled();
});
it.each([200, 409, 500])(
  "returns only typed results or fixed rejection: %s",
  async (status) => {
    const network = vi
      .fn()
      .mockResolvedValue(
        json(
          status === 200
            ? { ok: true, duplicate: true }
            : { private: "PRIVATE_SENTINEL" },
          status,
        ),
      );
    vi.stubGlobal("fetch", network);
    const response = await POST(request());
    expect(await response.json()).toEqual(
      status === 200
        ? { ok: true, duplicate: true }
        : { error: "FIXTURE_REQUEST_REJECTED" },
    );
    expect(network.mock.calls[0][0]).toBe("http://127.0.0.1:43419/command");
  },
);
it.each(["valid", "owner", "versions", "unavailable"])(
  "uses the real reader owner/cohort validation in the fake HTTP environment: %s",
  async (fault) => {
    const value = structuredClone(fixture);
    for (const row of value.rows)
      if (row.as_of) row.as_of = new Date(Date.now() - 1000).toISOString();
    const mapping = {
      ownerId: command.run_id,
      versionIds: value.rows.map((r) => r.mandate_version_id),
    };
    const network = vi.fn(async (url: string | URL) => {
      const path = new URL(String(url)).pathname;
      if (fault === "unavailable") return json({}, 503);
      if (path === "/binding") return json(mapping);
      if (path === "/auth/v1/user")
        return json({
          id: fault === "owner" ? command.request_id : mapping.ownerId,
          role: "authenticated",
          is_anonymous: false,
        });
      return json(fault === "versions" ? { ...value, rows: [] } : value);
    });
    vi.stubGlobal("fetch", network);
    expect((await readLiveReviewFixture()).state).toBe(
      fault === "valid" ? "READY" : "UNAVAILABLE",
    );
    for (const [url] of network.mock.calls)
      expect(new URL(String(url)).origin).toBe("http://127.0.0.1:43419");
  },
);

it.each([
  "valid",
  "wrong_run",
  "wrong_kind",
  "missing",
  "private",
  "external",
  "counts",
])(
  "binds verification proof to the requested run and command: %s",
  async (fault) => {
    const verification: Record<string, unknown> = {
      kind: "LOCAL_SINK",
      run_id: command.run_id,
      scope: "SYNTHETIC_OWNER",
      destination: "LOCAL_REVIEW_SINK",
      newly_received: 1,
      total: 1,
      received: 1,
      pending: 0,
      external_sends: 0,
    };
    if (fault === "wrong_run") verification.run_id = command.request_id;
    if (fault === "wrong_kind") verification.kind = "REPLAY";
    if (fault === "private") verification.packet = "PRIVATE_SENTINEL";
    if (fault === "external") verification.external_sends = 1;
    if (fault === "counts") verification.pending = 1;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        json({
          ok: true,
          duplicate: false,
          ...(fault === "missing" ? {} : { verification }),
        }),
      ),
    );
    const response = await POST(request({ ...command, command: "receive" }));
    expect(response.status).toBe(fault === "valid" ? 200 : 403);
    expect(JSON.stringify(await response.json())).not.toContain(
      "PRIVATE_SENTINEL",
    );
  },
);

it("returns replay hashes only and rejects a proof on an ordinary write", async () => {
  const verification = {
    kind: "REPLAY",
    run_id: command.run_id,
    matched: true,
    packet_sha256: "sha256:" + "a".repeat(64),
    projection_sha256: "sha256:" + "b".repeat(64),
  };
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementation(async () =>
        json({ ok: true, duplicate: false, verification }),
      ),
  );
  expect((await POST(request({ ...command, command: "replay" }))).status).toBe(
    200,
  );
  expect((await POST(request())).status).toBe(403);
});
