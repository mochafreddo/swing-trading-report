import "server-only";

import { z } from "zod";
import { parseStrictJsonText } from "./decision-board-json";
import {
  portfolioReviewStoreSchema,
  type StoredReviewSource,
} from "./portfolio-review-store-schema";

const bindingSchema = z
  .object({
    ownerId: z.string().uuid(),
    versionIds: z
      .array(z.string().uuid())
      .min(1)
      .max(100)
      .refine((v) => new Set(v).size === v.length),
    origin: z.url().refine((value) => {
      const url = new URL(value);
      return (
        url.protocol === "https:" &&
        url.pathname === "/" &&
        !url.username &&
        !url.password &&
        !url.search &&
        !url.hash
      );
    }),
    publishableKey: z.string().regex(/^sb_publishable_\S+$/),
    accessToken: z.string().min(1).max(16384).regex(/^\S+$/),
    maxAgeSeconds: z.number().int().min(1).max(86400),
  })
  .strict();

export type ReviewOwnerBinding = z.infer<typeof bindingSchema>;

// This requires a separately verified Supabase user context. The admin cookie
// never supplies an owner, bearer or version mapping. No env fallback exists.
export async function readAuthenticatedStoredReviews({
  enabled = false,
  binding,
  request = fetch,
  now = Date.now(),
}: {
  enabled?: boolean;
  binding?: ReviewOwnerBinding;
  request?: typeof fetch;
  now?: number;
} = {}): Promise<StoredReviewSource> {
  if (!enabled) return { state: "DISABLED" };
  const parsed = bindingSchema.safeParse(binding);
  if (!parsed.success || !Number.isFinite(now)) return { state: "UNAVAILABLE" };
  const config = parsed.data;
  try {
    const headers = {
      apikey: config.publishableKey,
      Authorization: `Bearer ${config.accessToken}`,
      "Content-Type": "application/json",
    };
    async function read(path: string, method: string, body?: string) {
      const response = await request(new URL(path, config.origin), {
        method,
        headers,
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      });
      if (
        !response.ok ||
        response.headers.get("content-type")?.split(";")[0] !==
          "application/json"
      )
        throw new Error("UNAVAILABLE");
      const reader = response.body?.getReader();
      if (!reader) throw new Error("UNAVAILABLE");
      let size = 0;
      const chunks: Uint8Array[] = [];
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > 512 * 1024) throw new Error("UNAVAILABLE");
          chunks.push(value);
        }
      } finally {
        await reader.cancel();
      }
      return parseStrictJsonText(Buffer.concat(chunks).toString("utf8"));
    }
    const user = z
      .object({
        id: z.literal(config.ownerId),
        role: z.literal("authenticated"),
        is_anonymous: z.literal(false),
      })
      .parse(await read("/auth/v1/user", "GET"));
    if (!user.id) throw new Error("UNAVAILABLE");
    const value = portfolioReviewStoreSchema.parse(
      await read(
        "/rest/v1/rpc/read_portfolio_review_store_r2",
        "POST",
        JSON.stringify({ p_version_ids: config.versionIds }),
      ),
    );
    if (
      value.rows.length !== config.versionIds.length ||
      value.rows.some((r) => !config.versionIds.includes(r.mandate_version_id))
    )
      throw new Error("UNAVAILABLE");
    if (
      value.rows.some(
        (r) =>
          r.as_of !== null &&
          (now < Date.parse(r.as_of) ||
            now - Date.parse(r.as_of) > config.maxAgeSeconds * 1000),
      )
    )
      return { state: "STALE" };
    return { state: "READY", value };
  } catch {
    return { state: "UNAVAILABLE" };
  }
}
