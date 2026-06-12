import { parseHoldingTickerForMutation } from "@/lib/holding-ticker";

export type SingleTickerRouteContext = {
  params: { ticker: string } | Promise<{ ticker: string }>;
};

export type CatchAllTickerRouteContext = {
  params:
    | { ticker: string[] }
    | Promise<{
        ticker: string[];
      }>;
};

export function joinTickerPath(segments: string[]): string {
  return segments.join("/");
}

export async function singleTickerContextFromCatchAll(
  context: CatchAllTickerRouteContext,
): Promise<SingleTickerRouteContext> {
  const params = await context.params;
  return { params: { ticker: joinTickerPath(params.ticker) } };
}

export function parseHoldingTickerRouteParam(rawTicker: string): string | null {
  const candidate = (() => {
    try {
      return decodeURIComponent(rawTicker);
    } catch {
      return rawTicker;
    }
  })();
  return parseHoldingTickerForMutation(candidate);
}
