"use client";

import styles from "./reports-client.module.css";

import { ReportDetail } from "@/components/reports/report-detail";
import { ReportsList } from "@/components/reports/reports-list";
import type { ReportsInitialState } from "@/components/reports/types";
import { useReportsState } from "@/components/reports/use-reports-state";

interface ReportsClientProps {
  initialState?: ReportsInitialState;
}

export function ReportsClient({ initialState }: ReportsClientProps) {
  const {
    reportType,
    query,
    appliedQuery,
    items,
    total,
    searched,
    truncated,
    searchWindow,
    warnings,
    selectedKey,
    detail,
    loadingList,
    loadingDetail,
    error,
    showRaw,
    summary,
    buyRows,
    sellRows,
    rawDetailJson,
    setReportType,
    setQuery,
    setSelectedKey,
    toggleShowRaw,
  } = useReportsState(initialState);

  return (
    <section className={styles.wrapper}>
      <div className={styles.left}>
        <ReportsList
          reportType={reportType}
          query={query}
          appliedQuery={appliedQuery}
          items={items}
          total={total}
          searched={searched}
          truncated={truncated}
          searchWindow={searchWindow}
          warnings={warnings}
          selectedKey={selectedKey}
          loadingList={loadingList}
          onReportTypeChange={setReportType}
          onQueryChange={setQuery}
          onSelectKey={setSelectedKey}
        />
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
          rawDetailJson={rawDetailJson}
          onToggleRaw={toggleShowRaw}
        />
      </div>
    </section>
  );
}
