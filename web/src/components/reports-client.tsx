"use client";

import styles from "./reports-client.module.css";

import { ReportDetail } from "@/components/reports/report-detail";
import { ReportsList } from "@/components/reports/reports-list";
import { DecisionBoardJournalPanel } from "@/components/reports/decision-board-journal-panel";
import type { ReportsInitialState } from "@/components/reports/types";
import { useReportsState } from "@/components/reports/use-reports-state";

interface ReportsClientProps {
  initialState?: ReportsInitialState;
}

export function ReportsClient({ initialState }: ReportsClientProps) {
  const {
    reportType,
    runKind,
    query,
    appliedQuery,
    items,
    total,
    searched,
    truncated,
    searchWindow,
    warnings,
    selectedKey,
    selectedBucketId,
    detail,
    loadingList,
    loadingDetail,
    error,
    showRaw,
    summary,
    buyRows,
    sellRows,
    entryRows,
    aiBriefRows,
    rawDetailJson,
    journalStatus,
    setReportType,
    setRunKind,
    setQuery,
    setSelectedKey,
    refreshReports,
    toggleShowRaw,
  } = useReportsState(initialState);

  return (
    <section className={styles.wrapper}>
      <div className={styles.left}>
        <ReportsList
          reportType={reportType}
          runKind={runKind}
          query={query}
          appliedQuery={appliedQuery}
          items={items}
          total={total}
          searched={searched}
          truncated={truncated}
          searchWindow={searchWindow}
          warnings={warnings}
          selectedKey={selectedKey}
          selectedBucketId={selectedBucketId}
          loadingList={loadingList}
          refreshing={loadingList || loadingDetail}
          onReportTypeChange={setReportType}
          onRunKindChange={setRunKind}
          onQueryChange={setQuery}
          onSelectKey={setSelectedKey}
          onRefresh={refreshReports}
        />
        {reportType === "decision-board" && (
          <DecisionBoardJournalPanel status={journalStatus} />
        )}
      </div>

      <div className={styles.right}>
        <ReportDetail
          detail={detail}
          loadingDetail={loadingDetail}
          error={error}
          showRaw={showRaw}
          summary={summary}
          buyRows={buyRows}
          sellRows={sellRows}
          entryRows={entryRows}
          aiBriefRows={aiBriefRows}
          rawDetailJson={rawDetailJson}
          onToggleRaw={toggleShowRaw}
        />
      </div>
    </section>
  );
}
