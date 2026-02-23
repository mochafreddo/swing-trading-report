import { useCallback, useEffect, useRef, useState } from "react";

import type { HoldingRecord, HoldingsListResponse } from "@/lib/types";

import {
  HOLDINGS_PAGE_SIZE,
  mergeHoldingsByTicker,
  readApiError,
} from "./helpers";

export interface HoldingsInitialState {
  items: HoldingRecord[];
  hasMore: boolean;
  nextCursor: string | null;
}

export function useHoldingsQuery(initialState?: HoldingsInitialState) {
  const [items, setItems] = useState<HoldingRecord[]>(
    () => initialState?.items ?? [],
  );
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(() => initialState?.hasMore ?? false);
  const [nextCursor, setNextCursor] = useState<string | null>(
    () => initialState?.nextCursor ?? null,
  );
  const [error, setError] = useState<string | null>(null);
  const skipInitialRefresh = useRef(Boolean(initialState));

  const fetchPage = useCallback(
    async (cursor?: string | null): Promise<HoldingsListResponse> => {
      const params = new URLSearchParams({
        limit: String(HOLDINGS_PAGE_SIZE),
      });
      if (cursor) {
        params.set("cursor", cursor);
      }

      const response = await fetch(`/api/holdings?${params.toString()}`, {
        cache: "no-store",
      });
      const payload = (await response.json()) as unknown;
      if (!response.ok) {
        throw new Error(readApiError(payload) || "Failed to load holdings");
      }

      return payload as HoldingsListResponse;
    },
    [],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadingMore(false);
    setError(null);

    try {
      const page = await fetchPage();
      setItems(page.items);
      setHasMore(page.hasMore);
      setNextCursor(page.nextCursor);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Failed to load holdings",
      );
    } finally {
      setLoading(false);
    }
  }, [fetchPage]);

  const loadMore = useCallback(async () => {
    if (!hasMore || !nextCursor || loadingMore) {
      return;
    }

    setLoadingMore(true);
    setError(null);
    try {
      const page = await fetchPage(nextCursor);
      setItems((prev) => mergeHoldingsByTicker(prev, page.items));
      setHasMore(page.hasMore);
      setNextCursor(page.nextCursor);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Failed to load holdings",
      );
    } finally {
      setLoadingMore(false);
    }
  }, [fetchPage, hasMore, loadingMore, nextCursor]);

  useEffect(() => {
    if (skipInitialRefresh.current) {
      skipInitialRefresh.current = false;
      return;
    }
    void refresh();
  }, [refresh]);

  return {
    items,
    loading,
    loadingMore,
    hasMore,
    error,
    setError,
    refresh,
    loadMore,
  };
}
