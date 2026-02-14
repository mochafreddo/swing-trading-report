import { z } from "zod";

const toOptionalTrimmedString = (maxLength: number) =>
  z.preprocess((value) => {
    if (value == null) {
      return undefined;
    }
    if (typeof value !== "string") {
      return value;
    }
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }, z.string().max(maxLength).optional());

const toNullableTrimmedString = (maxLength: number) =>
  z.preprocess((value) => {
    if (value == null) {
      return null;
    }
    if (typeof value !== "string") {
      return value;
    }
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }, z.string().max(maxLength).nullable());

const toOptionalNonNegativeNumber = z.preprocess((value) => {
  if (value === "" || value == null) {
    return undefined;
  }
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    const n = Number(value.trim());
    return Number.isNaN(n) ? value : n;
  }
  return value;
}, z.number().finite().min(0).optional());

const toNullableNonNegativeNumber = z.preprocess((value) => {
  if (value === "" || value == null) {
    return null;
  }
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    const n = Number(value.trim());
    return Number.isNaN(n) ? value : n;
  }
  return value;
}, z.number().finite().min(0).nullable());

const toTags = z.preprocess((value) => {
  if (value == null || value === "") {
    return [];
  }
  if (typeof value === "string") {
    return value
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean);
  }
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry).trim()).filter(Boolean);
  }
  return value;
}, z.array(z.string().min(1).max(40)).max(20));

const KR_TICKER_PATTERN = /^\d{6}$/;
const US_TICKER_PATTERN = /^[A-Z0-9][A-Z0-9._-]{0,30}\.(US|NASDAQ|NASD|NAS|NYSE|NYS|AMEX|AMS)$/;

const tickerSchema = z
  .string()
  .trim()
  .min(1)
  .max(32)
  .transform((ticker) => ticker.toUpperCase())
  .refine(
    (ticker) =>
      KR_TICKER_PATTERN.test(ticker) || US_TICKER_PATTERN.test(ticker),
    {
      message:
        "Ticker must be KR 6-digit code or US symbol with suffix (e.g. AAPL.US, AAPL.NASD)"
    }
  );

const entryDateSchema = z.preprocess((value) => {
  if (value === "" || value == null) {
    return null;
  }
  if (typeof value === "string") {
    return value.trim();
  }
  return value;
}, z.string().regex(/^\d{4}-\d{2}-\d{2}$/).nullable());

export const reportListQuerySchema = z.object({
  type: z.enum(["all", "buy", "sell"]).default("all"),
  q: z.string().trim().default(""),
  limit: z.coerce.number().int().min(1).max(200).default(30)
});

export const reportDetailQuerySchema = z.object({
  key: z.string().trim().min(1)
});

export const holdingCreateSchema = z
  .object({
    ticker: tickerSchema,
    quantity: toOptionalNonNegativeNumber.default(0),
    entry_price: toOptionalNonNegativeNumber.default(0),
    entry_currency: toNullableTrimmedString(12).optional(),
    entry_date: entryDateSchema.optional(),
    strategy: toNullableTrimmedString(80).optional(),
    notes: toNullableTrimmedString(2000).optional(),
    tags: toTags.default([]),
    stop_override: toNullableNonNegativeNumber.optional(),
    target_override: toNullableNonNegativeNumber.optional()
  })
  .strict();

export const holdingPatchSchema = z
  .object({
    quantity: toOptionalNonNegativeNumber,
    entry_price: toOptionalNonNegativeNumber,
    entry_currency: toNullableTrimmedString(12).optional(),
    entry_date: entryDateSchema.optional(),
    strategy: toNullableTrimmedString(80).optional(),
    notes: toNullableTrimmedString(2000).optional(),
    tags: toTags.optional(),
    stop_override: toNullableNonNegativeNumber.optional(),
    target_override: toNullableNonNegativeNumber.optional()
  })
  .strict()
  .refine((payload) => Object.keys(payload).length > 0, {
    message: "At least one field must be provided"
  });

const refSchema = toOptionalTrimmedString(120);

export const runDispatchSchema = z.union([
  z
    .object({
      workflow: z.literal("scan"),
      provider: z.enum(["kis", "pykrx"]),
      universe: z.enum(["KR", "US", "both"]),
      ref: refSchema
    })
    .strict(),
  z
    .object({
      workflow: z.literal("sell"),
      provider: z.enum(["kis", "pykrx"]),
      ref: refSchema
    })
    .strict()
]);
