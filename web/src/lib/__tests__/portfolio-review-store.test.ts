import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { PortfolioStoredReview } from "@/components/portfolio-stored-review";
import { portfolioReviewStoreSchema } from "@/lib/portfolio-review-store-schema";
import { readAuthenticatedStoredReviews } from "@/lib/portfolio-review-store.server";
import fixture from "../../../fixtures/portfolio-review-store.r2.synthetic.json";

const binding = {
  ownerId: "12345678-1234-4234-8234-123456789abc",
  versionIds: fixture.rows.map((r) => r.mandate_version_id),
  origin: "https://fixture.invalid/",
  publishableKey: "sb_publishable_fixture",
  accessToken: "fixture-bearer",
  maxAgeSeconds: 600,
};
const timestamp = fixture.rows.find((r) => r.as_of !== null)!.as_of!;
const now = Date.parse(timestamp);
const user = {
  id: binding.ownerId,
  role: "authenticated",
  is_anonymous: false,
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("stored portfolio review", () => {
  it("rejects fabricated outcome confirmation and reversed correction history", () => {
    const value = structuredClone(fixture);
    const row = value.rows.find((r) => r.outcomes.length > 0)!;
    row.outcomes.reverse();
    expect(portfolioReviewStoreSchema.safeParse(value).success).toBe(false);
    row.outcomes.reverse();
    row.outcomes[0].status = "NO_ACTION";
    expect(portfolioReviewStoreSchema.safeParse(value).success).toBe(false);
  });
  it("denies admin-only contexts and remains default off", async () => {
    const request = vi.fn();
    expect(await readAuthenticatedStoredReviews({ request })).toEqual({
      state: "DISABLED",
    });
    expect(
      await readAuthenticatedStoredReviews({ enabled: true, request }),
    ).toEqual({ state: "UNAVAILABLE" });
    request.mockClear();
    expect(request).not.toHaveBeenCalled();
  });
  it.each([
    "valid",
    "owner",
    "role",
    "anonymous",
    "versions",
    "stale",
    "future",
    "private",
    "redirect",
    "error",
    "duplicate",
    "oversize",
  ])("validates HTTP, ownership and freshness: %s", async (fault) => {
    const changedUser = { ...user };
    if (fault === "owner")
      changedUser.id = "00000000-0000-4000-8000-000000000000";
    if (fault === "role") changedUser.role = "service_role";
    if (fault === "anonymous") changedUser.is_anonymous = true;
    const value = structuredClone(fixture);
    if (fault === "versions") value.rows.pop();
    if (fault === "private")
      Object.assign(value, { private_note: "PRIVATE_SENTINEL" });
    const response =
      fault === "duplicate"
        ? new Response('{"rows":[],"rows":[]}', {
            headers: { "Content-Type": "application/json" },
          })
        : fault === "oversize"
          ? new Response("x".repeat(512 * 1024 + 1), {
              headers: { "Content-Type": "application/json" },
            })
          : json(value);
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        json(changedUser, fault === "redirect" ? 302 : 200),
      )
      .mockResolvedValueOnce(response);
    if (fault === "error")
      request.mockReset().mockRejectedValue(new Error("PRIVATE_SENTINEL"));
    const result = await readAuthenticatedStoredReviews({
      enabled: true,
      binding,
      request,
      now: now + (fault === "stale" ? 601000 : fault === "future" ? -1000 : 0),
    });
    expect(result.state).toBe(
      fault === "valid"
        ? "READY"
        : ["stale", "future"].includes(fault)
          ? "STALE"
          : "UNAVAILABLE",
    );
    expect(JSON.stringify(result)).not.toContain("PRIVATE_SENTINEL");
    if (fault === "valid") {
      expect(request.mock.calls.map((c) => c[1]?.method)).toEqual([
        "GET",
        "POST",
      ]);
      expect(
        request.mock.calls.every(
          (c) => c[1]?.cache === "no-store" && c[1]?.redirect === "error",
        ),
      ).toBe(true);
    }
  });
  it("renders empty, review and aggregate correction without original values", () => {
    const value = portfolioReviewStoreSchema.parse(fixture);
    const html = renderToStaticMarkup(
      createElement(PortfolioStoredReview, {
        source: { state: "READY", value },
        synthetic: true,
      }),
    );
    for (const text of [
      "EMPTY",
      "action=null",
      "UNLINKED",
      "AMBIGUOUS",
      "이전 기록 정정",
      "SYNTHETIC_ONLY",
    ])
      expect(html).toContain(text);
    expect(html).not.toContain("holding_document");
    for (const state of ["DISABLED", "UNAVAILABLE", "STALE"] as const) {
      const output = renderToStaticMarkup(
        createElement(PortfolioStoredReview, { source: { state } }),
      );
      expect(output).toContain(state);
      expect(output).not.toContain("THESIS_INVALIDATED");
    }
  });
});
