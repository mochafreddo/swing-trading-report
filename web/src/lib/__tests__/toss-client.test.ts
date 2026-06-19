import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  TossInvestConfigError,
  fetchDefaultTossHoldingsItems,
} from "@/lib/toss/client";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("Toss Open API client", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.stubEnv("TOSS_INVEST_CLIENT_ID", "client-test");
    vi.stubEnv("TOSS_INVEST_CLIENT_SECRET", "secret-test");
    vi.stubEnv("TOSS_INVEST_ACCOUNT", "account-test");
  });

  it("issues a client-credentials token and fetches holdings with the account header", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          access_token: "token-test",
          token_type: "Bearer",
          expires_in: 86400,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          result: {
            items: [
              {
                symbol: "AAPL",
                name: "Apple",
                marketCountry: "US",
                currency: "USD",
                quantity: "1.5",
                averagePurchasePrice: "188.50",
              },
            ],
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const items = await fetchDefaultTossHoldingsItems();

    expect(items).toEqual([
      {
        symbol: "AAPL",
        name: "Apple",
        marketCountry: "US",
        currency: "USD",
        quantity: "1.5",
        averagePurchasePrice: "188.50",
      },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const [tokenUrl, tokenInit] = fetchMock.mock.calls[0];
    expect(String(tokenUrl)).toBe(
      "https://openapi.tossinvest.com/oauth2/token",
    );
    expect((tokenInit?.headers as Headers).get("Content-Type")).toBe(
      "application/x-www-form-urlencoded",
    );
    expect(String(tokenInit?.body)).toBe(
      "grant_type=client_credentials&client_id=client-test&client_secret=secret-test",
    );

    const [holdingsUrl, holdingsInit] = fetchMock.mock.calls[1];
    expect(String(holdingsUrl)).toBe(
      "https://openapi.tossinvest.com/api/v1/holdings",
    );
    expect((holdingsInit?.headers as Headers).get("Authorization")).toBe(
      "Bearer token-test",
    );
    expect((holdingsInit?.headers as Headers).get("X-Tossinvest-Account")).toBe(
      "account-test",
    );
  });

  it("fails before network access when required Toss env is missing", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("TOSS_INVEST_CLIENT_SECRET", "");

    await expect(fetchDefaultTossHoldingsItems()).rejects.toThrow(
      TossInvestConfigError,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
