import { useEffect, useState } from "react";

import { readApiError } from "@/components/holdings/helpers";
import {
  parseTickerLookupResults,
  type TickerLookupResult,
} from "@/components/holdings/use-ticker-lookup";

interface RecentCandidatesApiPayload {
  report?: {
    key?: unknown;
    reportDate?: unknown;
  } | null;
  candidates?: unknown;
}

interface UseRecentCandidatesOptions {
  fetcher?: typeof fetch;
}

export function useRecentCandidates({
  fetcher = fetch,
}: UseRecentCandidatesOptions = {}) {
  const [candidates, setCandidates] = useState<TickerLookupResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reportKey, setReportKey] = useState<string | null>(null);
  const [reportDate, setReportDate] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          limitReports: "10",
          limitCandidates: "20",
        });
        const response = await fetcher(
          `/api/tickers/recent-candidates?${params.toString()}`,
          {
            signal: controller.signal,
            cache: "no-store",
          },
        );
        const payload = (await response.json()) as RecentCandidatesApiPayload;
        if (!response.ok) {
          throw new Error(
            readApiError(payload) || "Failed to load recent buy candidates",
          );
        }
        setCandidates(
          parseTickerLookupResults(payload.candidates, {
            includePattern: true,
          }),
        );
        setReportKey(
          payload.report && typeof payload.report.key === "string"
            ? payload.report.key
            : null,
        );
        setReportDate(
          payload.report && typeof payload.report.reportDate === "string"
            ? payload.report.reportDate
            : null,
        );
      } catch (recentError) {
        if (controller.signal.aborted) {
          return;
        }
        setCandidates([]);
        setReportKey(null);
        setReportDate(null);
        setError(
          recentError instanceof Error
            ? recentError.message
            : "Failed to load recent buy candidates",
        );
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    })();

    return () => controller.abort();
  }, [fetcher]);

  return {
    candidates,
    loading,
    error,
    reportKey,
    reportDate,
  };
}
