import { Suspense } from "react";

import { HoldingsClient } from "@/components/holdings-client";
import { HOLDINGS_PAGE_SIZE } from "@/components/holdings/helpers";
import type { HoldingsInitialState } from "@/components/holdings/use-holdings-query";
import { hasValidAdminSession } from "@/lib/admin-prefetch";
import { fetchHoldingsPage } from "@/lib/supabase-admin";

export async function loadHoldingsInitialState(): Promise<
  HoldingsInitialState | undefined
> {
  if (!(await hasValidAdminSession())) {
    return undefined;
  }

  const page = await fetchHoldingsPage({ limit: HOLDINGS_PAGE_SIZE });
  return {
    items: page.items,
    hasMore: page.hasMore,
    nextCursor: page.nextCursor,
  };
}

function HoldingsPageFallback() {
  return (
    <section className="panel">
      <p className="subtle">Loading holdings...</p>
    </section>
  );
}

async function HoldingsPageContent() {
  const initialState = await loadHoldingsInitialState();
  return <HoldingsClient initialState={initialState} />;
}

export default function HoldingsPage() {
  return (
    <Suspense fallback={<HoldingsPageFallback />}>
      <HoldingsPageContent />
    </Suspense>
  );
}
