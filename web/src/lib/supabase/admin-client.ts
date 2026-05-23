import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import { FetchTimeoutError, fetchWithTimeout } from "@/lib/fetch-timeout";

export class SupabaseApiError extends Error {
  public readonly code: string | null;
  public readonly upstreamCode: string | null;
  public readonly details: string | null;
  public readonly hint: string | null;

  constructor(
    message: string,
    public readonly status: number,
    options?: {
      code?: string | null;
      upstreamCode?: string | null;
      details?: string | null;
      hint?: string | null;
    },
  ) {
    super(message);
    this.code = options?.code ?? null;
    this.upstreamCode = options?.upstreamCode ?? null;
    this.details = options?.details ?? null;
    this.hint = options?.hint ?? null;
  }
}

export async function fetchSupabase(
  url: string,
  init: Omit<RequestInit, "signal">,
): Promise<Response> {
  try {
    return await fetchWithTimeout(url, init);
  } catch (error) {
    if (error instanceof FetchTimeoutError) {
      throw new SupabaseApiError(
        `Supabase request timed out after ${error.timeoutMs}ms`,
        504,
      );
    }
    throw error;
  }
}

export function buildAuthHeaders(extra?: Record<string, string>): HeadersInit {
  const env = getSupabaseEnv();
  return {
    apikey: env.SUPABASE_API_KEY,
    Authorization: `Bearer ${env.SUPABASE_API_KEY}`,
    ...extra,
  };
}

interface ParsedSupabaseErrorPayload {
  message: string;
  code: string | null;
  details: string | null;
  hint: string | null;
}

function trimTextOrNull(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export async function parseErrorPayload(
  response: Response,
): Promise<ParsedSupabaseErrorPayload> {
  const text = await response.text();
  if (!text) {
    return {
      message: `HTTP ${response.status}`,
      code: null,
      details: null,
      hint: null,
    };
  }

  try {
    const parsed = JSON.parse(text) as {
      message?: unknown;
      error?: unknown;
      code?: unknown;
      details?: unknown;
      hint?: unknown;
    };
    const message =
      trimTextOrNull(parsed.message) || trimTextOrNull(parsed.error) || text;
    return {
      message,
      code: trimTextOrNull(parsed.code),
      details: trimTextOrNull(parsed.details),
      hint: trimTextOrNull(parsed.hint),
    };
  } catch {
    return {
      message: text,
      code: null,
      details: null,
      hint: null,
    };
  }
}

export async function parseError(response: Response): Promise<string> {
  const parsed = await parseErrorPayload(response);
  return parsed.message;
}
