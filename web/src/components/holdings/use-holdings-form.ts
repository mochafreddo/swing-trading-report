import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import type {
  HoldingsActionResult,
  SaveHoldingActionInput,
} from "@/app/actions/holdings";
import type { HoldingRecord } from "@/lib/types";

import { createEmptyHoldingForm, type HoldingFormState } from "./form-state";
import { buildCreatePayload, buildPatchPayload, recordToForm } from "./helpers";

interface UseHoldingsFormOptions {
  refresh: () => Promise<void>;
  saveHolding: (input: SaveHoldingActionInput) => Promise<HoldingsActionResult>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
}

export function useHoldingsForm({
  refresh,
  saveHolding,
  setError,
}: UseHoldingsFormOptions) {
  const [submitting, setSubmitting] = useState(false);
  const [editingTicker, setEditingTicker] = useState<string | null>(null);
  const [form, setForm] = useState<HoldingFormState>(() =>
    createEmptyHoldingForm(),
  );
  const [baselineForm, setBaselineForm] = useState<HoldingFormState>(() =>
    createEmptyHoldingForm(),
  );

  const modeLabel = useMemo(
    () => (editingTicker ? `Edit ${editingTicker}` : "Create Holding"),
    [editingTicker],
  );

  const hasUnsavedChanges = useMemo(
    () => !submitting && JSON.stringify(form) !== JSON.stringify(baselineForm),
    [baselineForm, form, submitting],
  );

  useEffect(() => {
    if (!hasUnsavedChanges) {
      return;
    }

    const message =
      "저장되지 않은 변경사항이 있습니다. 이 페이지를 떠나시겠습니까?";
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = message;
      return message;
    };
    const onDocumentClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const element =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (!(element instanceof HTMLAnchorElement)) {
        return;
      }
      if (element.target && element.target !== "_self") {
        return;
      }

      const nextUrl = new URL(element.href, window.location.href);
      const currentUrl = new URL(window.location.href);
      const changingPage =
        nextUrl.pathname !== currentUrl.pathname ||
        nextUrl.search !== currentUrl.search ||
        nextUrl.hash !== currentUrl.hash;
      if (!changingPage) {
        return;
      }

      if (!window.confirm(message)) {
        event.preventDefault();
      }
    };

    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onDocumentClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onDocumentClick, true);
    };
  }, [hasUnsavedChanges]);

  const updateField = useCallback(
    (field: keyof HoldingFormState, value: string) => {
      setForm((prev) => ({ ...prev, [field]: value }));
    },
    [],
  );

  const onSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setSubmitting(true);
      setError(null);

      try {
        const payload = editingTicker
          ? buildPatchPayload(form)
          : buildCreatePayload(form);
        const result = await saveHolding({
          editingTicker,
          payload,
        });
        if (!result.ok) {
          throw new Error(result.error || "Save failed");
        }

        setEditingTicker(null);
        const emptyForm = createEmptyHoldingForm();
        setForm(emptyForm);
        setBaselineForm(emptyForm);
        await refresh();
      } catch (submitError) {
        setError(
          submitError instanceof Error ? submitError.message : "Save failed",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [editingTicker, form, refresh, saveHolding, setError],
  );

  const beginEdit = useCallback((row: HoldingRecord) => {
    const nextForm = recordToForm(row);
    setEditingTicker(row.ticker);
    setForm(nextForm);
    setBaselineForm(nextForm);
  }, []);

  const cancelEdit = useCallback(() => {
    const emptyForm = createEmptyHoldingForm();
    setEditingTicker(null);
    setForm(emptyForm);
    setBaselineForm(emptyForm);
  }, []);

  return {
    submitting,
    editingTicker,
    form,
    modeLabel,
    hasUnsavedChanges,
    updateField,
    onSubmit,
    beginEdit,
    cancelEdit,
  };
}
