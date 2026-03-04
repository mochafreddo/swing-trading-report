export const ADD_BUY_IDEMPOTENCY_MISMATCH_CODE =
  "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH";
export const ADD_BUY_IDEMPOTENCY_MISMATCH_DETAIL =
  "holdings_add_buy_idempotency_payload_mismatch";

const IDEMPOTENCY_MISMATCH_TOKEN = "idempotency_key payload mismatch";

export function isAddBuyIdempotencyPayloadMismatchMessage(
  message: string,
): boolean {
  return message.toLowerCase().includes(IDEMPOTENCY_MISMATCH_TOKEN);
}
