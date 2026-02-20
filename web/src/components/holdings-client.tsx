"use client";

import { useCallback, useMemo, useState } from "react";

import styles from "./holdings-client.module.css";

import { partitionHoldingsByActivity } from "@/lib/holding-activity";

import { HoldingsFormPanel } from "@/components/holdings/holdings-form-panel";
import { HoldingsTable } from "@/components/holdings/holdings-table";
import { readApiError } from "@/components/holdings/helpers";
import { useHoldingsForm } from "@/components/holdings/use-holdings-form";
import { useHoldingsQuery } from "@/components/holdings/use-holdings-query";

export function HoldingsClient() {
  const [showInactive, setShowInactive] = useState(false);
  const {
    items,
    loading,
    loadingMore,
    hasMore,
    error,
    setError,
    refresh,
    loadMore,
  } = useHoldingsQuery();
  const {
    submitting,
    editingTicker,
    form,
    modeLabel,
    hasUnsavedChanges,
    updateField,
    onSubmit,
    beginEdit,
    cancelEdit,
  } = useHoldingsForm({ refresh, setError });
  const partitioned = useMemo(
    () => partitionHoldingsByActivity(items),
    [items],
  );
  const visibleItems = showInactive ? items : partitioned.active;

  const removeHolding = useCallback(
    async (ticker: string) => {
      const confirmDelete = window.confirm(
        `${ticker} 을(를) 삭제하시겠습니까?`,
      );
      if (!confirmDelete) {
        return;
      }

      setError(null);
      try {
        const response = await fetch(
          `/api/holdings/${encodeURIComponent(ticker)}`,
          {
            method: "DELETE",
          },
        );
        const payload = (await response.json()) as unknown;
        if (!response.ok) {
          throw new Error(readApiError(payload) || "Delete failed");
        }
        if (editingTicker === ticker) {
          cancelEdit();
        }
        await refresh();
      } catch (deleteError) {
        setError(
          deleteError instanceof Error ? deleteError.message : "Delete failed",
        );
      }
    },
    [cancelEdit, editingTicker, refresh, setError],
  );

  return (
    <section className={styles.wrapper}>
      <HoldingsFormPanel
        modeLabel={modeLabel}
        submitting={submitting}
        editingTicker={editingTicker}
        hasUnsavedChanges={hasUnsavedChanges}
        form={form}
        onSubmit={onSubmit}
        onCancelEdit={cancelEdit}
        onFieldChange={updateField}
      />
      <HoldingsTable
        items={items}
        visibleItems={visibleItems}
        activeCount={partitioned.activeCount}
        inactiveCount={partitioned.inactiveCount}
        showInactive={showInactive}
        loading={loading}
        loadingMore={loadingMore}
        hasMore={hasMore}
        error={error}
        onRefresh={refresh}
        onToggleShowInactive={setShowInactive}
        onEdit={beginEdit}
        onDelete={removeHolding}
        onLoadMore={loadMore}
      />
    </section>
  );
}
