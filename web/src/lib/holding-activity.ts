import type { HoldingRecord } from "@/lib/types";

export interface HoldingActivityPartition {
  active: HoldingRecord[];
  inactive: HoldingRecord[];
  activeCount: number;
  inactiveCount: number;
  totalCount: number;
}

export function isActiveHoldingQuantity(quantity: number): boolean {
  return Number.isFinite(quantity) && quantity > 0;
}

export function partitionHoldingsByActivity(
  items: HoldingRecord[],
): HoldingActivityPartition {
  const active: HoldingRecord[] = [];
  const inactive: HoldingRecord[] = [];

  for (const item of items) {
    if (isActiveHoldingQuantity(item.quantity)) {
      active.push(item);
      continue;
    }
    inactive.push(item);
  }

  return {
    active,
    inactive,
    activeCount: active.length,
    inactiveCount: inactive.length,
    totalCount: items.length,
  };
}
