import { NextRequest } from "next/server";

import {
  DELETE as deleteSingleTickerHolding,
  PATCH as patchSingleTickerHolding,
} from "../[ticker]/route";
import {
  type CatchAllTickerRouteContext,
  joinTickerPath,
} from "../ticker-route-params";

export const runtime = "nodejs";

export async function PATCH(
  request: NextRequest,
  context: CatchAllTickerRouteContext,
) {
  const params = await context.params;
  return patchSingleTickerHolding(request, {
    params: { ticker: joinTickerPath(params.ticker) },
  });
}

export async function DELETE(
  request: NextRequest,
  context: CatchAllTickerRouteContext,
) {
  const params = await context.params;
  return deleteSingleTickerHolding(request, {
    params: { ticker: joinTickerPath(params.ticker) },
  });
}
