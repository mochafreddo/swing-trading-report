import { z } from "zod";

import { parseStrictJsonText } from "@/lib/decision-board-json";

const decimal = z
  .string()
  .max(30)
  .regex(/^[0-9]+(?:\.[0-9]+)?$/);
const timestamp = z.string().datetime({ offset: true });
const orderSchema = z.object({
  orderId: z.string().min(1).max(512),
  symbol: z.string().min(1).max(80),
  side: z.enum(["BUY", "SELL"]),
  status: z.enum([
    "FILLED",
    "PARTIAL_FILLED",
    "CANCELED",
    "REPLACED",
    "REJECTED",
    "CANCEL_REJECTED",
    "REPLACE_REJECTED",
  ]),
  quantity: decimal,
  orderAmount: decimal.nullable().optional(),
  currency: z.enum(["KRW", "USD"]),
  orderedAt: timestamp,
  execution: z.object({
    filledQuantity: decimal,
    averageFilledPrice: decimal.nullable(),
    filledAt: timestamp.nullable(),
  }),
});
const pageSchema = z
  .object({
    requestCursor: z.string().min(1).max(8192).nullable(),
    response: z.object({
      result: z.object({
        orders: z.array(orderSchema).max(20),
        hasNext: z.boolean(),
        nextCursor: z.string().min(1).max(8192).nullable(),
      }),
    }),
  })
  .strict();

export type OrderAggregateRow = {
  rowKey: string;
  symbol: string;
  side: "BUY" | "SELL";
  status: z.infer<typeof orderSchema>["status"];
  currency: "KRW" | "USD";
  orderedAtKst: string;
  filledQuantity: string;
  averageFilledPrice: string | null;
};
export type OrderHistoryView = {
  state: "COMPLETE" | "EMPTY" | "INCOMPLETE" | "ERROR";
  issue:
    | "INVALID_DATE_RANGE"
    | "INVALID_RESPONSE"
    | "PAGE_CHAIN_INVALID"
    | "DUPLICATE_ORDER"
    | "BUDGET_EXCEEDED"
    | null;
  pagesSeen: number;
  rows: OrderAggregateRow[];
};

function dateMs(value: string): number {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return NaN;
  const ms = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(ms) &&
    new Date(ms).toISOString().slice(0, 10) === value
    ? ms
    : NaN;
}

function greaterThan(left: string, right: string): boolean {
  const [li, lf = ""] = left.split(".");
  const [ri, rf = ""] = right.split(".");
  const scale = Math.max(lf.length, rf.length);
  return (
    BigInt(li + lf.padEnd(scale, "0")) > BigInt(ri + rf.padEnd(scale, "0"))
  );
}

/** Pure bounded memory adapter. No transport, persistence, logging or fill synthesis. */
export function adaptTossOrderHistory(
  text: string,
  fromDate: string,
  toDate: string,
): OrderHistoryView {
  const fail = (
    issue: OrderHistoryView["issue"],
    pagesSeen = 0,
  ): OrderHistoryView => ({ state: "ERROR", issue, pagesSeen, rows: [] });
  const from = dateMs(fromDate),
    to = dateMs(toDate);
  if (
    !Number.isFinite(from) ||
    !Number.isFinite(to) ||
    from > to ||
    to - from >= 30 * 86400000
  )
    return fail("INVALID_DATE_RANGE");
  if (new TextEncoder().encode(text).byteLength > 1_048_576)
    return fail("BUDGET_EXCEEDED");
  try {
    const parsed = z
      .array(pageSchema)
      .min(1)
      .max(4)
      .safeParse(parseStrictJsonText(text));
    if (!parsed.success) return fail("INVALID_RESPONSE");
    const rows: OrderAggregateRow[] = [];
    const identities = new Set<string>();
    const cursors = new Set<string>();
    let expectedCursor: string | null = null;
    for (const [index, envelope] of parsed.data.entries()) {
      if (index > 0 && expectedCursor === null)
        return fail("PAGE_CHAIN_INVALID", index);
      if (envelope.requestCursor !== expectedCursor)
        return fail("PAGE_CHAIN_INVALID", index);
      const page = envelope.response.result;
      if (page.hasNext !== (page.nextCursor !== null))
        return fail("PAGE_CHAIN_INVALID", index + 1);
      if (page.nextCursor !== null) {
        if (cursors.has(page.nextCursor))
          return fail("PAGE_CHAIN_INVALID", index + 1);
        cursors.add(page.nextCursor);
      }
      expectedCursor = page.nextCursor;
      for (const order of page.orders) {
        if (identities.has(order.orderId))
          return fail("DUPLICATE_ORDER", index + 1);
        identities.add(order.orderId);
        const execution = order.execution;
        if (
          (order.orderAmount == null &&
            greaterThan(execution.filledQuantity, order.quantity)) ||
          (greaterThan(execution.filledQuantity, "0") &&
            (execution.averageFilledPrice === null ||
              execution.filledAt === null))
        )
          return fail("INVALID_RESPONSE", index + 1);
        const orderedAtKst = new Date(Date.parse(order.orderedAt) + 9 * 3600000)
          .toISOString()
          .replace("Z", "+09:00");
        if (
          orderedAtKst.slice(0, 10) < fromDate ||
          orderedAtKst.slice(0, 10) > toDate
        )
          continue;
        rows.push({
          rowKey: `row-${identities.size}`,
          symbol: order.symbol,
          side: order.side,
          status: order.status,
          currency: order.currency,
          orderedAtKst,
          filledQuantity: execution.filledQuantity,
          averageFilledPrice: execution.averageFilledPrice,
        });
      }
    }
    if (expectedCursor !== null)
      return {
        state: "INCOMPLETE",
        issue: null,
        rows: [],
        pagesSeen: parsed.data.length,
      };
    return {
      state: rows.length ? "COMPLETE" : "EMPTY",
      issue: null,
      rows,
      pagesSeen: parsed.data.length,
    };
  } catch {
    return fail("INVALID_RESPONSE");
  }
}
