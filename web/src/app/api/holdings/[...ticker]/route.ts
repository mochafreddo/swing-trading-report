import { NextRequest } from "next/server";

import {
  DELETE as deleteSingleTickerHolding,
  PATCH as patchSingleTickerHolding,
} from "../[ticker]/route";
import {
  type CatchAllTickerRouteContext,
  singleTickerContextFromCatchAll,
} from "../ticker-route-params";

export const runtime = "nodejs";

export async function PATCH(
  request: NextRequest,
  context: CatchAllTickerRouteContext,
) {
  return patchSingleTickerHolding(
    request,
    await singleTickerContextFromCatchAll(context),
  );
}

export async function DELETE(
  request: NextRequest,
  context: CatchAllTickerRouteContext,
) {
  return deleteSingleTickerHolding(
    request,
    await singleTickerContextFromCatchAll(context),
  );
}
