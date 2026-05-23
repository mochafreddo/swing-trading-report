import { useCallback, useMemo, useState } from "react";
import type { Dispatch, FormEvent, SetStateAction } from "react";

import { addBuyToHoldingAction } from "@/app/actions/holdings";
import {
  getAddBuyPrecheckError,
  inferRequiredCurrency,
} from "@/components/holdings/add-buy-precheck";
import {
  createAddBuyIdempotencyKey,
  resolveAddBuySubmitError,
} from "@/components/holdings/add-buy-idempotency";
import type {
  AddBuyFormState,
  AddBuyPreview,
} from "@/components/holdings/holdings-add-buy-panel";
import type { HoldingRecord } from "@/lib/types";

type AddBuyAction = typeof addBuyToHoldingAction;

interface UseAddBuyFlowOptions {
  items: HoldingRecord[];
  refresh: () => Promise<void>;
  setError: Dispatch<SetStateAction<string | null>>;
  addBuyToHolding?: AddBuyAction;
}

function formatTodayLocalDate(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function createEmptyAddBuyForm(): AddBuyFormState {
  return {
    buy_quantity: "",
    buy_price: "",
    buy_date: formatTodayLocalDate(),
  };
}

function parsePositiveNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function roundTo(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function resolveNextEntryDate(
  currentEntryDate: string | null,
  buyDateInput: string,
): string | null {
  const buyDate = buyDateInput.trim();
  if (!buyDate) {
    return currentEntryDate;
  }
  if (!currentEntryDate) {
    return buyDate;
  }
  return buyDate < currentEntryDate ? buyDate : currentEntryDate;
}

function buildAddBuyPreview(
  target: HoldingRecord | null,
  form: AddBuyFormState,
): AddBuyPreview | null {
  if (!target) {
    return null;
  }
  const buyQuantity = parsePositiveNumber(form.buy_quantity);
  const buyPrice = parsePositiveNumber(form.buy_price);
  if (buyQuantity == null || buyPrice == null) {
    return null;
  }

  const nextQuantity = target.quantity + buyQuantity;
  if (!Number.isFinite(nextQuantity) || nextQuantity <= 0) {
    return null;
  }

  const nextEntryPrice =
    target.quantity === 0
      ? buyPrice
      : (target.quantity * target.entry_price + buyQuantity * buyPrice) /
        nextQuantity;

  return {
    next_quantity: roundTo(nextQuantity, 6),
    next_entry_price: roundTo(nextEntryPrice, 4),
    next_entry_date: resolveNextEntryDate(target.entry_date, form.buy_date),
    next_entry_currency:
      target.entry_currency?.trim().toUpperCase() ||
      inferRequiredCurrency(target.ticker),
  };
}

export function useAddBuyFlow({
  items,
  refresh,
  setError,
  addBuyToHolding = addBuyToHoldingAction,
}: UseAddBuyFlowOptions) {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [form, setForm] = useState<AddBuyFormState>(() =>
    createEmptyAddBuyForm(),
  );
  const [idempotencyKey, setIdempotencyKey] = useState<string>(() =>
    createAddBuyIdempotencyKey(),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setAddBuyError] = useState<string | null>(null);
  const target = useMemo(
    () => items.find((item) => item.ticker === selectedTicker) ?? null,
    [items, selectedTicker],
  );
  const precheckError = useMemo(() => getAddBuyPrecheckError(target), [target]);
  const preview = useMemo(
    () => (precheckError ? null : buildAddBuyPreview(target, form)),
    [form, precheckError, target],
  );

  const cancel = useCallback(() => {
    setSelectedTicker(null);
    setForm(createEmptyAddBuyForm());
    setIdempotencyKey(createAddBuyIdempotencyKey());
    setAddBuyError(null);
  }, []);

  const begin = useCallback(
    (row: HoldingRecord) => {
      setSelectedTicker(row.ticker);
      setForm(createEmptyAddBuyForm());
      setIdempotencyKey(createAddBuyIdempotencyKey());
      setAddBuyError(null);
      setError(null);
    },
    [setError],
  );

  const updateField = useCallback(
    (field: keyof AddBuyFormState, value: string) => {
      setForm((prev) => ({ ...prev, [field]: value }));
      setIdempotencyKey(createAddBuyIdempotencyKey());
    },
    [],
  );

  const submit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!selectedTicker) {
        setAddBuyError("Add Buy 대상 티커를 선택하세요.");
        return;
      }
      if (precheckError) {
        return;
      }

      const buyQuantity = parsePositiveNumber(form.buy_quantity);
      const buyPrice = parsePositiveNumber(form.buy_price);
      if (buyQuantity == null || buyPrice == null) {
        setAddBuyError("Buy Quantity/Price는 0보다 큰 숫자여야 합니다.");
        return;
      }
      const trimmedIdempotencyKey = idempotencyKey.trim();
      if (!trimmedIdempotencyKey) {
        setAddBuyError("Idempotency key 생성에 실패했습니다. 다시 시도하세요.");
        return;
      }

      setSubmitting(true);
      setAddBuyError(null);
      setError(null);
      try {
        const payload: {
          buy_quantity: number;
          buy_price: number;
          buy_date?: string;
        } = {
          buy_quantity: buyQuantity,
          buy_price: buyPrice,
        };
        const buyDate = form.buy_date.trim();
        if (buyDate) {
          payload.buy_date = buyDate;
        }

        const result = await addBuyToHolding({
          ticker: selectedTicker,
          idempotencyKey: trimmedIdempotencyKey,
          payload,
        });
        if (!result.ok) {
          const message = result.error || "Add buy failed";
          const code = result.code;
          throw Object.assign(new Error(message), {
            code,
          });
        }

        setSelectedTicker(null);
        setForm(createEmptyAddBuyForm());
        setIdempotencyKey(createAddBuyIdempotencyKey());
        await refresh();
      } catch (addBuySubmitError) {
        const resolvedError = resolveAddBuySubmitError(addBuySubmitError);
        if (resolvedError.shouldRotateIdempotencyKey) {
          setIdempotencyKey(createAddBuyIdempotencyKey());
        }
        setAddBuyError(resolvedError.message);
      } finally {
        setSubmitting(false);
      }
    },
    [
      addBuyToHolding,
      form,
      idempotencyKey,
      precheckError,
      refresh,
      selectedTicker,
      setError,
    ],
  );

  return {
    selectedTicker,
    target,
    form,
    submitting,
    error,
    precheckError,
    preview,
    begin,
    updateField,
    cancel,
    submit,
  };
}
