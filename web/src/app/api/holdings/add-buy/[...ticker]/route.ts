import { NextRequest } from "next/server";

import { POST as postSingleTickerAddBuy } from "../../[ticker]/add-buy/route";
import {
  type CatchAllTickerRouteContext,
  singleTickerContextFromCatchAll,
} from "../../ticker-route-params";

export const runtime = "nodejs";

export async function POST(
  request: NextRequest,
  context: CatchAllTickerRouteContext,
) {
  return postSingleTickerAddBuy(
    request,
    await singleTickerContextFromCatchAll(context),
  );
}
