import { NextRequest } from "next/server";

import { POST as postSingleTickerAddBuy } from "../../[ticker]/add-buy/route";
import {
  type CatchAllTickerRouteContext,
  joinTickerPath,
} from "../../ticker-route-params";

export const runtime = "nodejs";

export async function POST(
  request: NextRequest,
  context: CatchAllTickerRouteContext,
) {
  const params = await context.params;
  return postSingleTickerAddBuy(request, {
    params: { ticker: joinTickerPath(params.ticker) },
  });
}
