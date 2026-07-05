import { z } from "zod";

import {
  isScanUniverseAllowed,
  PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
} from "@/lib/run-dispatch-policy";
import { REPORT_TYPES } from "@/lib/types";
import {
  HOLDING_ENTRY_PATTERN_VALUES,
  isHoldingEntryPattern,
} from "@/lib/holding-entry-pattern";
import {
  inferHoldingCurrencyForTicker,
  KR_TICKER_PATTERN,
  normalizeHoldingTickerForMutation,
  US_TICKER_PATTERN,
} from "@/lib/holding-ticker";

const REPORT_LIST_TYPES = ["all", ...REPORT_TYPES] as const;
const ISO_CALENDAR_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function isValidIsoCalendarDate(value: string): boolean {
  const match = ISO_CALENDAR_DATE_PATTERN.exec(value);
  if (!match) {
    return false;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const daysByMonth = [
    31,
    isLeapYear(year) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  return month >= 1 && month <= 12 && day >= 1 && day <= daysByMonth[month - 1];
}

const isoCalendarDateSchema = z.string().refine(isValidIsoCalendarDate, {
  message: "Date must be a valid YYYY-MM-DD date",
});

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

const toNullableEntryPattern = z.preprocess(
  (value) => {
    if (value == null) {
      return null;
    }
    if (typeof value !== "string") {
      return value;
    }
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  },
  z
    .string()
    .max(120)
    .refine(isHoldingEntryPattern, {
      message: `entry_pattern must be one of ${HOLDING_ENTRY_PATTERN_VALUES.join(", ")}`,
    })
    .nullable(),
);

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

const toPositiveNumber = z.preprocess((value) => {
  if (typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    const n = Number(value.trim());
    return Number.isNaN(n) ? value : n;
  }
  return value;
}, z.number().finite().gt(0));

const toTags = z.preprocess(
  (value) => {
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
  },
  z.array(z.string().min(1).max(40)).max(20),
);

const toBooleanRefreshFlag = z.preprocess((value) => {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "1" || normalized === "true") {
      return true;
    }
    if (normalized === "0" || normalized === "false" || normalized === "") {
      return false;
    }
  }
  if (value == null) {
    return undefined;
  }
  return value;
}, z.boolean().default(false));

const holdingTickerSchema = z
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
        "Ticker must be KR 6-digit code or US symbol with exchange suffix (e.g. AAPL.NAS, BRK.B.NYS)",
    },
  );
const holdingMutationTickerSchema = holdingTickerSchema.transform((ticker) =>
  normalizeHoldingTickerForMutation(ticker),
);

export function isHoldingEntryCurrencyValidForTicker(
  ticker: string,
  entryCurrency: string | null | undefined,
): boolean {
  if (!entryCurrency) {
    return true;
  }
  const requiredCurrency = inferHoldingCurrencyForTicker(ticker);
  if (!requiredCurrency) {
    return true;
  }
  return entryCurrency.trim().toUpperCase() === requiredCurrency;
}

function addEntryCurrencyIssue(
  ctx: z.RefinementCtx,
  ticker: string,
  entryCurrency: string | null | undefined,
): void {
  if (isHoldingEntryCurrencyValidForTicker(ticker, entryCurrency)) {
    return;
  }
  const requiredCurrency = inferHoldingCurrencyForTicker(ticker);
  ctx.addIssue({
    code: z.ZodIssueCode.custom,
    path: ["entry_currency"],
    message: `entry_currency must be ${requiredCurrency} for ${ticker}`,
  });
}

const entryDateSchema = z.preprocess((value) => {
  if (value === "" || value == null) {
    return null;
  }
  if (typeof value === "string") {
    return value.trim();
  }
  return value;
}, isoCalendarDateSchema.nullable());

export const reportListQuerySchema = z.object({
  type: z.enum(REPORT_LIST_TYPES).default("all"),
  q: z.string().trim().default(""),
  limit: z.coerce.number().int().min(1).max(200).default(30),
  refresh: toBooleanRefreshFlag,
});

export const reportDetailQuerySchema = z.object({
  key: z.string().trim().min(1),
  refresh: toBooleanRefreshFlag,
});

export const tickerSearchQuerySchema = z.object({
  q: z.string().trim().min(1).max(120),
  limit: z.coerce.number().int().min(1).max(50).default(20),
});

export const recentBuyCandidatesQuerySchema = z.object({
  limitReports: z.coerce.number().int().min(1).max(50).default(10),
  limitCandidates: z.coerce.number().int().min(1).max(100).default(30),
});

export const holdingListQuerySchema = z.object({
  limit: z.coerce.number().int().min(1).max(200).default(100),
  cursor: z.string().trim().min(1).optional(),
});

export const holdingCreateSchema = z
  .object({
    ticker: holdingMutationTickerSchema,
    quantity: toOptionalNonNegativeNumber.default(0),
    entry_price: toOptionalNonNegativeNumber.default(0),
    entry_currency: toNullableTrimmedString(12).optional(),
    entry_date: entryDateSchema.optional(),
    strategy: toNullableTrimmedString(80).optional(),
    entry_pattern: toNullableEntryPattern.optional(),
    notes: toNullableTrimmedString(2000).optional(),
    tags: toTags.default([]),
    stop_override: toNullableNonNegativeNumber.optional(),
    target_override: toNullableNonNegativeNumber.optional(),
  })
  .strict()
  .refine((payload) => payload.quantity === 0 || payload.entry_price > 0, {
    message: "entry_price must be > 0 when quantity > 0",
    path: ["entry_price"],
  })
  .superRefine((payload, ctx) => {
    if (payload.entry_pattern != null && payload.quantity <= 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["entry_pattern"],
        message: "entry_pattern requires quantity > 0",
      });
    }
    addEntryCurrencyIssue(ctx, payload.ticker, payload.entry_currency);
  });

export const holdingPatchSchema = z
  .object({
    ticker: holdingMutationTickerSchema.optional(),
    quantity: toOptionalNonNegativeNumber,
    entry_price: toOptionalNonNegativeNumber,
    entry_currency: toNullableTrimmedString(12).optional(),
    entry_date: entryDateSchema.optional(),
    strategy: toNullableTrimmedString(80).optional(),
    entry_pattern: toNullableEntryPattern.optional(),
    notes: toNullableTrimmedString(2000).optional(),
    tags: toTags.optional(),
    stop_override: toNullableNonNegativeNumber.optional(),
    target_override: toNullableNonNegativeNumber.optional(),
  })
  .strict()
  .refine(
    (payload) => {
      if (payload.quantity == null || payload.entry_price == null) {
        return true;
      }
      return payload.quantity === 0 || payload.entry_price > 0;
    },
    {
      message: "entry_price must be > 0 when quantity > 0",
      path: ["entry_price"],
    },
  )
  .superRefine((payload, ctx) => {
    if (
      payload.entry_pattern != null &&
      (payload.quantity == null || payload.quantity <= 0)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["entry_pattern"],
        message: "entry_pattern requires quantity > 0",
      });
    }
    if (payload.ticker) {
      if (payload.entry_currency == null) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["entry_currency"],
          message: "entry_currency is required when ticker changes",
        });
        return;
      }
      addEntryCurrencyIssue(ctx, payload.ticker, payload.entry_currency);
    }
  })
  .refine((payload) => Object.keys(payload).length > 0, {
    message: "At least one field must be provided",
  });

const addBuyDateSchema = z.preprocess((value) => {
  if (value == null) {
    return undefined;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? trimmed : undefined;
  }
  return value;
}, isoCalendarDateSchema.optional());

export const holdingAddBuySchema = z
  .object({
    buy_quantity: toPositiveNumber,
    buy_price: toPositiveNumber,
    buy_date: addBuyDateSchema,
  })
  .strict();

export const holdingYamlImportRequestSchema = z
  .object({
    document: z.string().min(1),
    apply: z.boolean().default(false),
  })
  .strict();

export const tossHoldingsSyncRequestSchema = z.union([
  z
    .object({
      mode: z.literal("apply"),
      diffHash: z.string().regex(/^sha256:[a-f0-9]{64}$/),
    })
    .strict(),
  z
    .object({
      mode: z.literal("dry-run").default("dry-run"),
    })
    .strict(),
]);

export const tossHoldingsScheduledSyncRequestSchema = z
  .object({
    mode: z.literal("auto-apply"),
  })
  .strict();

export const runDispatchSchema = z.union([
  z
    .object({
      workflow: z.literal("scan"),
      provider: z.enum(["kis", "pykrx"]),
      universe: z.enum(["KR", "US", "both"]),
    })
    .strict()
    .superRefine((payload, ctx) => {
      if (!isScanUniverseAllowed(payload.provider, payload.universe)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["universe"],
          message: PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
        });
      }
    }),
  z
    .object({
      workflow: z.literal("sell"),
      provider: z.enum(["kis", "pykrx"]),
    })
    .strict(),
]);
