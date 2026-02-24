import { NextRequest } from "next/server";

import {
  DELETE as deleteSingleTickerHolding,
  PATCH as patchSingleTickerHolding,
} from "../[ticker]/route";

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

export async function PATCH(
  request: NextRequest,
  context: CatchAllRouteContext,
) {
  const params = await context.params;
  return patchSingleTickerHolding(request, {
    params: { ticker: joinTickerPath(params.ticker) },
  });
}

export async function DELETE(
  request: NextRequest,
  context: CatchAllRouteContext,
) {
  const params = await context.params;
  return deleteSingleTickerHolding(request, {
    params: { ticker: joinTickerPath(params.ticker) },
  });
}
