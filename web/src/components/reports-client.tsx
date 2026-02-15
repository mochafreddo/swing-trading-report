"use client";

import { useEffect, useMemo, useState } from "react";

import styles from "./reports-client.module.css";

import type { ReportListItem, ReportsListResponse } from "@/lib/types";

const PAGE_LIMIT = 30;

type ReportJson = Record<string, unknown>;

function asRecord(value: unknown): ReportJson | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as ReportJson;
}

function asRecordArray(value: unknown): ReportJson[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => asRecord(entry))
    .filter((entry): entry is ReportJson => Boolean(entry));
}

function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

function readApiError(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return undefined;
  }
  const value = (payload as { error?: unknown }).error;
  return typeof value === "string" && value.trim() ? value : undefined;
}

function formatDateLabel(item: ReportListItem): string {
  return item.duplicateIndex > 0
    ? `${item.reportDate} #${item.duplicateIndex}`
    : item.reportDate;
}

export function ReportsClient() {
  const [reportType, setReportType] = useState<"all" | "buy" | "sell">("all");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ReportListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [searched, setSearched] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [searchWindow, setSearchWindow] = useState(100);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReportJson | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    const load = async () => {
      setLoadingList(true);
      setError(null);

      try {
        const params = new URLSearchParams({
          type: reportType,
          limit: String(PAGE_LIMIT)
        });
        if (query.trim()) {
          params.set("q", query.trim());
        }

        const response = await fetch(`/api/reports?${params.toString()}`, {
          signal: controller.signal,
          cache: "no-store"
        });

        const payload = (await response.json()) as unknown;

        if (!response.ok) {
          throw new Error(readApiError(payload) || "Failed to load reports");
        }

        const typed = payload as ReportsListResponse;
        setItems(typed.items);
        setTotal(typed.total);
        setSearched(typed.searched);
        setTruncated(typed.truncated);
        setSearchWindow(typed.searchWindow);

        const firstKey = typed.items[0]?.key ?? null;
        setSelectedKey((prev) => {
          if (prev && typed.items.some((item) => item.key === prev)) {
            return prev;
          }
          return firstKey;
        });
      } catch (loadError) {
        if (controller.signal.aborted) {
          return;
        }
        const message =
          loadError instanceof Error ? loadError.message : "Failed to load reports";
        setError(message);
      } finally {
        if (!controller.signal.aborted) {
          setLoadingList(false);
        }
      }
    };

    void load();

    return () => controller.abort();
  }, [reportType, query]);

  useEffect(() => {
    if (!selectedKey) {
      setDetail(null);
      return;
    }

    const controller = new AbortController();
    const loadDetail = async () => {
      setLoadingDetail(true);
      setError(null);

      try {
        const params = new URLSearchParams({ key: selectedKey });
        const response = await fetch(`/api/reports/detail?${params.toString()}`, {
          signal: controller.signal,
          cache: "no-store"
        });
        const payload = (await response.json()) as unknown;

        if (!response.ok) {
          throw new Error(readApiError(payload) || "Failed to load report detail");
        }

        setDetail((payload as { report: ReportJson }).report);
      } catch (detailError) {
        if (controller.signal.aborted) {
          return;
        }
        const message =
          detailError instanceof Error
            ? detailError.message
            : "Failed to load report detail";
        setError(message);
        setDetail(null);
      } finally {
        if (!controller.signal.aborted) {
          setLoadingDetail(false);
        }
      }
    };

    void loadDetail();

    return () => controller.abort();
  }, [selectedKey]);

  const summary = useMemo(() => asRecord(detail?.summary), [detail]);
  const buyRows = useMemo(() => asRecordArray(detail?.candidates), [detail]);
  const sellRows = useMemo(() => asRecordArray(detail?.evaluated), [detail]);

  return (
    <section className={styles.wrapper}>
      <div className={styles.left}>
        <header className="panel">
          <h2 className="panelTitle">Reports</h2>
          <p className="subtle">Supabase Storage 리포트 탐색</p>

          <div className={styles.controls}>
            <label>
              Type
              <select
                name="reportType"
                autoComplete="off"
                value={reportType}
                onChange={(event) => {
                  setReportType(event.target.value as "all" | "buy" | "sell");
                }}
              >
                <option value="all">All</option>
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
            </label>

            <label>
              Ticker 검색
              <input
                name="reportQuery"
                autoComplete="off"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="예: AAPL"
                spellCheck={false}
              />
            </label>
          </div>

          <p className="subtle">
            total={total}
            {query.trim() && (
              <>
                {" · "}searched={searched}
                {truncated ? `/${searchWindow} window` : ""}
              </>
            )}
          </p>
          {query.trim() && truncated && (
            <p className="subtle">
              검색 범위 제한: 최신 {searchWindow}개 리포트만 검색됨
            </p>
          )}
        </header>

        <ul className={styles.list} aria-busy={loadingList}>
          {loadingList && (
            <li className="panel subtle" role="status" aria-live="polite">
              목록 로딩 중...
            </li>
          )}
          {!loadingList && items.length === 0 && (
            <li className="panel subtle" role="status" aria-live="polite">
              조건에 맞는 리포트가 없습니다.
            </li>
          )}
          {!loadingList &&
            items.map((item) => (
              <li key={item.key}>
                <button
                  type="button"
                  className={`${styles.itemButton} ${
                    selectedKey === item.key ? styles.active : ""
                  }`.trim()}
                  onClick={() => setSelectedKey(item.key)}
                  aria-pressed={selectedKey === item.key}
                >
                  <span className={styles.itemPrimary}>{formatDateLabel(item)}</span>
                  <span className={styles.badge}>{item.type.toUpperCase()}</span>
                  <span className={styles.itemKey}>{item.key}</span>
                </button>
              </li>
            ))}
        </ul>
      </div>

      <div className={styles.right}>
        <section className="panel" aria-busy={loadingDetail}>
          <div className={styles.detailHeaderRow}>
            <div>
              <h2 className="panelTitle">Report Detail</h2>
              <p className="subtle">구조화 보기 + Raw JSON</p>
            </div>
            <button
              type="button"
              className={styles.toggleButton}
              onClick={() => setShowRaw((prev) => !prev)}
              disabled={!detail}
              aria-pressed={showRaw}
              aria-controls="report-raw-json"
            >
              {showRaw ? "Raw 숨기기" : "Raw 보기"}
            </button>
          </div>

          <p className="visuallyHidden" role="status" aria-live="polite">
            {loadingDetail
              ? "리포트 상세 로딩 중"
              : detail
                ? "리포트 상세 로딩 완료"
                : "리포트를 선택하세요"}
          </p>
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
          {loadingDetail && (
            <p className="subtle" role="status" aria-live="polite">
              상세 로딩 중...
            </p>
          )}
          {!loadingDetail && !detail && <p className="subtle">리포트를 선택하세요.</p>}

          {detail && (
            <>
              <dl className={styles.metaGrid}>
                <div>
                  <dt>schema</dt>
                  <dd>{String(detail.schema ?? "-")}</dd>
                </div>
                <div>
                  <dt>type</dt>
                  <dd>{String(detail.type ?? "-")}</dd>
                </div>
                <div>
                  <dt>generated_at</dt>
                  <dd>{String(detail.generated_at ?? "-")}</dd>
                </div>
                <div>
                  <dt>provider</dt>
                  <dd>{String(detail.provider ?? "-")}</dd>
                </div>
              </dl>

              {summary && (
                <div className={styles.summaryBoxes}>
                  {Object.entries(summary).map(([key, value]) => (
                    <article key={key} className={styles.summaryBox}>
                      <h3>{key}</h3>
                      <p>{typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
                    </article>
                  ))}
                </div>
              )}

              {buyRows.length > 0 && (
                <div className={styles.tableWrap}>
                  <h3 className={styles.sectionTitle}>Candidates ({buyRows.length})</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Name</th>
                        <th>Price</th>
                        <th>Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {buyRows.slice(0, 20).map((row, idx) => (
                        <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                          <td>{String(row.ticker ?? "-")}</td>
                          <td>{String(row.name ?? "-")}</td>
                          <td>{String(row.price ?? "-")}</td>
                          <td>{readNumber(row.score) ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {sellRows.length > 0 && (
                <div className={styles.tableWrap}>
                  <h3 className={styles.sectionTitle}>Evaluated ({sellRows.length})</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th>Action</th>
                        <th>Last</th>
                        <th>PnL%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sellRows.slice(0, 20).map((row, idx) => (
                        <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                          <td>{String(row.ticker ?? "-")}</td>
                          <td>{String(row.action ?? "-")}</td>
                          <td>{readNumber(row.last_price) ?? "-"}</td>
                          <td>{readNumber(row.pnl_pct) ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {showRaw && (
                <pre id="report-raw-json" className={styles.raw}>
                  {JSON.stringify(detail, null, 2)}
                </pre>
              )}
            </>
          )}
        </section>
      </div>
    </section>
  );
}
