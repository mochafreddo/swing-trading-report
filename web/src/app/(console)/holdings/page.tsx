import { HoldingsClient } from "@/components/holdings-client";
import { HOLDINGS_PAGE_SIZE } from "@/components/holdings/helpers";
import type { HoldingsInitialState } from "@/components/holdings/use-holdings-query";
import { hasValidAdminSession } from "@/lib/admin-prefetch";
import { fetchHoldingsPage } from "@/lib/supabase-admin";

export default async function HoldingsPage() {
  let initialState: HoldingsInitialState | undefined;

  if (await hasValidAdminSession()) {
    try {
      const page = await fetchHoldingsPage({ limit: HOLDINGS_PAGE_SIZE });
      initialState = {
        items: page.items,
        hasMore: page.hasMore,
        nextCursor: page.nextCursor,
      };
    } catch {
      initialState = undefined;
    }
  }

  return <HoldingsClient initialState={initialState} />;
}
