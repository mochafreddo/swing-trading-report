"use client";

import { useCallback, useMemo, useState } from "react";

import { deleteHoldingAction, saveHoldingAction } from "@/app/actions/holdings";

import styles from "./holdings-client.module.css";

import { partitionHoldingsByActivity } from "@/lib/holding-activity";

import { HoldingsAddBuyPanel } from "@/components/holdings/holdings-add-buy-panel";
import { HoldingsFormPanel } from "@/components/holdings/holdings-form-panel";
import { HoldingsTable } from "@/components/holdings/holdings-table";
import { useHoldingsForm } from "@/components/holdings/use-holdings-form";
import {
  type HoldingsInitialState,
  useHoldingsQuery,
} from "@/components/holdings/use-holdings-query";
import { HoldingsImportPanel } from "@/components/holdings/holdings-import-panel";
import { useAddBuyFlow } from "@/components/holdings/use-add-buy-flow";
import { useHoldingsImport } from "@/components/holdings/use-holdings-import";
import { useRecentCandidates } from "@/components/holdings/use-recent-candidates";
import { useTickerLookup } from "@/components/holdings/use-ticker-lookup";

interface HoldingsClientProps {
  initialState?: HoldingsInitialState;
}

export function HoldingsClient({ initialState }: HoldingsClientProps) {
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
  } = useHoldingsQuery(initialState);
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
  } = useHoldingsForm({ refresh, saveHolding: saveHoldingAction, setError });
  const updateTickerField = useCallback(
    (ticker: string) => updateField("ticker", ticker),
    [updateField],
  );
  const tickerLookup = useTickerLookup({
    onSelectTicker: updateTickerField,
  });
  const { selectTicker: selectLookupTicker } = tickerLookup;
  const recentCandidates = useRecentCandidates();
  const selectTicker = useCallback(
    (ticker: string, entryPattern?: string | null) => {
      selectLookupTicker(ticker);
      if (entryPattern !== undefined) {
        updateField("entry_pattern", entryPattern ?? "");
      }
    },
    [selectLookupTicker, updateField],
  );
  const addBuy = useAddBuyFlow({
    items,
    refresh,
    setError,
  });
  const holdingsImport = useHoldingsImport({
    refresh,
    cancelEdit,
    cancelAddBuy: addBuy.cancel,
  });
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
        const result = await deleteHoldingAction(ticker);
        if (!result.ok) {
          throw new Error(result.error || "Delete failed");
        }
        if (editingTicker === ticker) {
          cancelEdit();
        }
        if (addBuy.selectedTicker === ticker) {
          addBuy.cancel();
        }
        await refresh();
      } catch (deleteError) {
        setError(
          deleteError instanceof Error ? deleteError.message : "Delete failed",
        );
      }
    },
    [addBuy, cancelEdit, editingTicker, refresh, setError],
  );

  return (
    <section className={styles.wrapper}>
      <div className={styles.sidebar}>
        <HoldingsFormPanel
          modeLabel={modeLabel}
          submitting={submitting}
          editingTicker={editingTicker}
          hasUnsavedChanges={hasUnsavedChanges}
          form={form}
          tickerLookupQuery={tickerLookup.query}
          tickerLookupResults={tickerLookup.results}
          tickerLookupLoading={tickerLookup.loading}
          tickerLookupError={tickerLookup.error}
          recentCandidates={recentCandidates.candidates}
          recentCandidatesReportKey={recentCandidates.reportKey}
          recentCandidatesReportDate={recentCandidates.reportDate}
          recentCandidatesLoading={recentCandidates.loading}
          recentCandidatesError={recentCandidates.error}
          onSubmit={onSubmit}
          onCancelEdit={cancelEdit}
          onFieldChange={updateField}
          onTickerLookupQueryChange={tickerLookup.setQuery}
          onSelectTicker={selectTicker}
        />
        <HoldingsAddBuyPanel
          target={addBuy.target}
          form={addBuy.form}
          submitting={addBuy.submitting}
          error={addBuy.error}
          precheckError={addBuy.precheckError}
          preview={addBuy.preview}
          onFieldChange={addBuy.updateField}
          onSubmit={addBuy.submit}
          onCancel={addBuy.cancel}
        />
        <HoldingsImportPanel
          fileName={holdingsImport.fileName}
          loading={holdingsImport.loading}
          applying={holdingsImport.applying}
          error={holdingsImport.error}
          success={holdingsImport.success}
          summary={holdingsImport.summary}
          canDryRun={holdingsImport.canDryRun}
          canApply={holdingsImport.canApply}
          onFileSelected={holdingsImport.handleFileSelected}
          onDryRun={holdingsImport.dryRun}
          onApply={holdingsImport.apply}
        />
      </div>
      <HoldingsTable
        items={items}
        visibleItems={visibleItems}
        activeCount={partitioned.activeCount}
        inactiveCount={partitioned.inactiveCount}
        showInactive={showInactive}
        loading={loading}
        loadingMore={loadingMore}
        exporting={holdingsImport.exporting}
        hasMore={hasMore}
        error={error}
        onRefresh={refresh}
        onExport={holdingsImport.handleExport}
        onToggleShowInactive={setShowInactive}
        onEdit={beginEdit}
        onAddBuy={addBuy.begin}
        onDelete={removeHolding}
        onLoadMore={loadMore}
      />
    </section>
  );
}
