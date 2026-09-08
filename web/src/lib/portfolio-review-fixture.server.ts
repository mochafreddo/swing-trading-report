import "server-only";

import { z } from "zod";
import { readAuthenticatedStoredReviews } from "./portfolio-review-store.server";
import type { StoredReviewSource } from "./portfolio-review-store-schema";

// Only the explicit synthetic server can inject this HTTP test double. The real
// authenticated transport continues to require HTTPS and independent user mapping.
export function liveReviewFixtureOrigin(): string | null {
  if (
    process.env.SAB_SKIP_ROOT_ENV !== "1" ||
    process.env.SAB_PORTFOLIO_R2_FIXTURE !== "1"
  )
    return null;
  const port = process.env.PORTFOLIO_REVIEW_LIVE_PORT ?? "";
  if (!/^\d{4,5}$/.test(port) || Number(port) < 1024 || Number(port) > 65535)
    return null;
  return `http://127.0.0.1:${port}`;
}

export async function fixtureRequest(
  path: "/binding" | "/command",
  body?: string,
) {
  const origin = liveReviewFixtureOrigin();
  if (!origin) throw new Error("FIXTURE_DISABLED");
  return fetch(origin + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: "Bearer synthetic-review-only",
      "Content-Type": "application/json",
    },
    body,
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(10000),
  });
}

export async function readLiveReviewFixture(): Promise<StoredReviewSource> {
  const origin = liveReviewFixtureOrigin();
  if (!origin) return { state: "DISABLED" };
  try {
    const response = await fixtureRequest("/binding");
    if (!response.ok) throw new Error("UNAVAILABLE");
    const mapping = z
      .object({
        ownerId: z.string().uuid(),
        versionIds: z.array(z.string().uuid()).min(1).max(2),
      })
      .strict()
      .parse(await response.json());
    const request: typeof fetch = (input, init) => {
      const url = new URL(String(input));
      if (
        url.origin !== "https://synthetic.invalid" ||
        ![
          "/auth/v1/user",
          "/rest/v1/rpc/read_portfolio_review_store_r2",
        ].includes(url.pathname) ||
        url.search ||
        url.hash
      )
        throw new Error("FIXTURE_PATH_REJECTED");
      return fetch(origin + url.pathname, init);
    };
    return readAuthenticatedStoredReviews({
      enabled: true,
      binding: {
        ...mapping,
        origin: "https://synthetic.invalid",
        publishableKey: "sb_publishable_synthetic",
        accessToken: "synthetic-review-only",
        maxAgeSeconds: 3600,
      },
      request,
    });
  } catch {
    return { state: "UNAVAILABLE" };
  }
}
