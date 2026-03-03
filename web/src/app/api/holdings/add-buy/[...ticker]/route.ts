import { NextRequest } from "next/server";

import { POST as postSingleTickerAddBuy } from "../../[ticker]/add-buy/route";

export const runtime = "nodejs";

type CatchAllRouteContext = {
  params:
    | { ticker: string[] }
    | Promise<{
        ticker: string[];
      }>;
};

function joinTickerPath(segments: string[]): string {
  return segments.join("/");
}

export async function POST(
  request: NextRequest,
  context: CatchAllRouteContext,
) {
  const params = await context.params;
  return postSingleTickerAddBuy(request, {
    params: { ticker: joinTickerPath(params.ticker) },
  });
}
