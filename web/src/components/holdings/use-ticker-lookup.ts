import { useCallback, useEffect, useState } from "react";

import { readApiError } from "@/components/holdings/helpers";

export interface TickerLookupResult {
  ticker: string;
  name: string | null;
}

interface TickerLookupState {
  query: string;
  results: TickerLookupResult[];
  loading: boolean;
  error: string | null;
}

interface TickerSearchApiPayload {
  results?: unknown;
}

interface UseTickerLookupOptions {
  onSelectTicker: (ticker: string) => void;
  fetcher?: typeof fetch;
  debounceMs?: number;
}

const EMPTY_TICKER_LOOKUP_STATE: TickerLookupState = {
  query: "",
  results: [],
  loading: false,
  error: null,
};

export function parseTickerLookupResults(
  payload: unknown,
): TickerLookupResult[] {
  if (!Array.isArray(payload)) {
    return [];
  }
  const results: TickerLookupResult[] = [];
  for (const item of payload) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      continue;
    }
    const raw = item as { ticker?: unknown; name?: unknown };
    const ticker =
      typeof raw.ticker === "string" ? raw.ticker.trim().toUpperCase() : "";
    if (!ticker) {
      continue;
    }
    const name = typeof raw.name === "string" ? raw.name.trim() : "";
    results.push({
      ticker,
      name: name || null,
    });
  }
  return results;
}

export function useTickerLookup({
  onSelectTicker,
  fetcher = fetch,
  debounceMs = 220,
}: UseTickerLookupOptions) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<TickerLookupState>(
    () => EMPTY_TICKER_LOOKUP_STATE,
  );
  const trimmedQuery = query.trim();
  const activeState =
    state.query === trimmedQuery ? state : EMPTY_TICKER_LOOKUP_STATE;

  const reset = useCallback(() => {
    setQuery("");
    setState(EMPTY_TICKER_LOOKUP_STATE);
  }, []);

  const selectTicker = useCallback(
    (ticker: string) => {
      onSelectTicker(ticker);
      reset();
    },
    [onSelectTicker, reset],
  );

  useEffect(() => {
    const searchQuery = trimmedQuery;
    if (!searchQuery) {
      return;
    }

    const controller = new AbortController();
    const timerId = window.setTimeout(() => {
      void (async () => {
        setState({
          query: searchQuery,
          results: [],
          loading: true,
          error: null,
        });
        try {
          const params = new URLSearchParams({
            q: searchQuery,
            limit: "8",
          });
          const response = await fetcher(
            `/api/tickers/search?${params.toString()}`,
            {
              signal: controller.signal,
              cache: "no-store",
            },
          );
          const payload = (await response.json()) as TickerSearchApiPayload;
          if (!response.ok) {
            throw new Error(readApiError(payload) || "Ticker search failed");
          }
          if (!controller.signal.aborted) {
            setState({
              query: searchQuery,
              results: parseTickerLookupResults(payload.results),
              loading: false,
              error: null,
            });
          }
        } catch (searchError) {
          if (controller.signal.aborted) {
            return;
          }
          setState({
            query: searchQuery,
            results: [],
            loading: false,
            error:
              searchError instanceof Error
                ? searchError.message
                : "Ticker search failed",
          });
        }
      })();
    }, debounceMs);

    return () => {
      controller.abort();
      window.clearTimeout(timerId);
    };
  }, [debounceMs, fetcher, trimmedQuery]);

  return {
    query,
    setQuery,
    results: activeState.results,
    loading: activeState.loading,
    error: activeState.error,
    selectTicker,
    reset,
  };
}
