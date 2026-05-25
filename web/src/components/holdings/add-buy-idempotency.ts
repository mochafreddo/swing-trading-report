import {
  ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
  isAddBuyIdempotencyPayloadMismatchMessage,
} from "@/lib/add-buy-idempotency";
import { toErrorMessage } from "@/lib/error-utils";

const IDEMPOTENCY_MISMATCH_HINT =
  "요청 충돌이 감지되어 새 Idempotency-Key를 자동 발급했습니다. 다시 시도하세요.";

export interface AddBuySubmitErrorResolution {
  message: string;
  shouldRotateIdempotencyKey: boolean;
}

function createUuidFromRandomValues(
  getRandomValues: (values: Uint8Array) => Uint8Array,
): string {
  const values = getRandomValues(new Uint8Array(16));
  values[6] = (values[6] & 0x0f) | 0x40;
  values[8] = (values[8] & 0x3f) | 0x80;
  const hex = Array.from(values, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}

export function createAddBuyIdempotencyKey(): string {
  if (typeof crypto === "undefined" || !crypto) {
    return "";
  }
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  if (typeof crypto.getRandomValues === "function") {
    return createUuidFromRandomValues(
      crypto.getRandomValues.bind(crypto) as (values: Uint8Array) => Uint8Array,
    );
  }
  return "";
}

function readErrorCode(error: unknown): string | null {
  if (!error || typeof error !== "object" || Array.isArray(error)) {
    return null;
  }
  const code = (error as { code?: unknown }).code;
  if (typeof code !== "string") {
    return null;
  }
  const trimmed = code.trim();
  return trimmed ? trimmed : null;
}

export function resolveAddBuySubmitError(
  error: unknown,
): AddBuySubmitErrorResolution {
  const baseMessage = toErrorMessage(error, "Add buy failed");
  const errorCode = readErrorCode(error);
  const shouldRotateIdempotencyKey =
    errorCode === ADD_BUY_IDEMPOTENCY_MISMATCH_CODE ||
    isAddBuyIdempotencyPayloadMismatchMessage(baseMessage);
  if (!shouldRotateIdempotencyKey) {
    return {
      message: baseMessage,
      shouldRotateIdempotencyKey: false,
    };
  }
  return {
    message: `${baseMessage} ${IDEMPOTENCY_MISMATCH_HINT}`,
    shouldRotateIdempotencyKey: true,
  };
}
