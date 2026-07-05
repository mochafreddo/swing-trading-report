import "server-only";

import { FetchTimeoutError, fetchWithTimeout } from "@/lib/fetch-timeout";
import type { TossHoldingsItem } from "@/lib/toss/holdings-sync";

interface TossInvestConfig {
  baseUrl: string;
  clientId: string;
  clientSecret: string;
  account: string;
}

interface TossRequestOptions {
  accessToken?: string;
  account?: string;
  body?: URLSearchParams;
  method: "GET" | "POST";
}

export class TossInvestConfigError extends Error {
  constructor(message = "Toss Open API is not configured") {
    super(message);
    this.name = "TossInvestConfigError";
  }
}

export class TossInvestApiError extends Error {
  status: number;
  upstreamStatus?: number;

  constructor(message: string, status: number, upstreamStatus?: number) {
    super(message);
    this.name = "TossInvestApiError";
    this.status = status;
    this.upstreamStatus = upstreamStatus;
  }
}

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new TossInvestConfigError(
      "Toss Open API is not configured. Set TOSS_INVEST_CLIENT_ID, TOSS_INVEST_CLIENT_SECRET, and TOSS_INVEST_ACCOUNT.",
    );
  }
  return value;
}

function getTossInvestConfig(): TossInvestConfig {
  return {
    baseUrl:
      process.env.TOSS_INVEST_BASE_URL?.trim() ||
      "https://openapi.tossinvest.com",
    clientId: requiredEnv("TOSS_INVEST_CLIENT_ID"),
    clientSecret: requiredEnv("TOSS_INVEST_CLIENT_SECRET"),
    account: requiredEnv("TOSS_INVEST_ACCOUNT"),
  };
}

function makeUrl(config: TossInvestConfig, path: string): URL {
  return new URL(path, config.baseUrl);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new TossInvestApiError(
      "Toss Open API returned a non-JSON response",
      502,
      response.status,
    );
  }
}

function upstreamStatusCode(status: number): number {
  if (status === 429) {
    return 429;
  }
  return 502;
}

function readTossErrorMessage(payload: unknown): string | null {
  const record = asRecord(payload);
  if (!record) {
    return null;
  }

  const oauthError = record.error;
  if (typeof oauthError === "string" && oauthError.trim()) {
    return `Toss Open API request failed: ${oauthError.trim()}`;
  }

  const apiError = asRecord(record.error);
  const apiMessage = apiError?.message;
  if (typeof apiMessage === "string" && apiMessage.trim()) {
    return `Toss Open API request failed: ${apiMessage.trim()}`;
  }

  return null;
}

async function fetchTossJson(
  config: TossInvestConfig,
  path: string,
  options: TossRequestOptions,
): Promise<unknown> {
  const headers = new Headers({ Accept: "application/json" });
  if (options.body) {
    headers.set("Content-Type", "application/x-www-form-urlencoded");
  }
  if (options.accessToken) {
    headers.set("Authorization", `Bearer ${options.accessToken}`);
  }
  if (options.account) {
    headers.set("X-Tossinvest-Account", options.account);
  }

  let response: Response;
  try {
    response = await fetchWithTimeout(String(makeUrl(config, path)), {
      method: options.method,
      headers,
      body: options.body,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof FetchTimeoutError) {
      throw new TossInvestApiError("Toss Open API request timed out", 504);
    }
    throw error;
  }
  const payload = await parseJsonResponse(response);
  if (!response.ok) {
    throw new TossInvestApiError(
      readTossErrorMessage(payload) ??
        `Toss Open API request failed with HTTP ${response.status}`,
      upstreamStatusCode(response.status),
      response.status,
    );
  }
  return payload;
}

function readRequiredString(
  record: Record<string, unknown>,
  field: string,
): string {
  const value = record[field];
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  throw new TossInvestApiError(
    "Toss Open API returned an unexpected holdings response",
    502,
  );
}

function readOptionalString(
  record: Record<string, unknown>,
  field: string,
): string | null {
  const value = record[field];
  if (value == null) {
    return null;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }
  return null;
}

function readAccessToken(payload: unknown): string {
  const record = asRecord(payload);
  const accessToken = record?.access_token;
  if (typeof accessToken !== "string" || !accessToken.trim()) {
    throw new TossInvestApiError(
      "Toss Open API returned an unexpected token response",
      502,
    );
  }
  return accessToken.trim();
}

function readHoldingsArray(payload: unknown): unknown[] {
  const record = asRecord(payload);
  const result = asRecord(record?.result);
  const candidates = [
    Array.isArray(record?.result) ? record?.result : null,
    Array.isArray(result?.holdings) ? result?.holdings : null,
    Array.isArray(result?.items) ? result?.items : null,
  ];
  const holdings = candidates.find((candidate) => candidate !== null);
  if (!holdings) {
    throw new TossInvestApiError(
      "Toss Open API returned an unexpected holdings response",
      502,
    );
  }
  return holdings;
}

function parseTossHoldingItem(value: unknown): TossHoldingsItem {
  const record = asRecord(value);
  if (!record) {
    throw new TossInvestApiError(
      "Toss Open API returned an unexpected holdings response",
      502,
    );
  }

  return {
    symbol: readRequiredString(record, "symbol"),
    name: readOptionalString(record, "name"),
    marketCountry: readRequiredString(record, "marketCountry"),
    currency: readRequiredString(record, "currency"),
    quantity: readRequiredString(record, "quantity"),
    averagePurchasePrice: readRequiredString(record, "averagePurchasePrice"),
  };
}

export async function fetchDefaultTossHoldingsItems(): Promise<
  TossHoldingsItem[]
> {
  const config = getTossInvestConfig();
  const tokenPayload = await fetchTossJson(config, "/oauth2/token", {
    method: "POST",
    body: new URLSearchParams({
      grant_type: "client_credentials",
      client_id: config.clientId,
      client_secret: config.clientSecret,
    }),
  });
  const accessToken = readAccessToken(tokenPayload);
  const holdingsPayload = await fetchTossJson(config, "/api/v1/holdings", {
    method: "GET",
    accessToken,
    account: config.account,
  });
  return readHoldingsArray(holdingsPayload).map(parseTossHoldingItem);
}
