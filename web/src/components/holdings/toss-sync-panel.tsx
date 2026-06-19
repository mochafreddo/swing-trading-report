import { useState } from "react";

import styles from "../holdings-client.module.css";

import type {
  TossHoldingCreateChange,
  TossHoldingDeleteChange,
  TossHoldingUpdateChange,
  TossHoldingsDryRunResponse,
  TossSyncStatus,
} from "@/components/holdings/use-toss-holdings-sync";
import type { HoldingReplaceSnapshot, HoldingSnapshot } from "@/lib/types";
import type { TossHoldingsBlockedRow } from "@/lib/toss/holdings-sync";

interface TossSyncPanelProps {
  status: TossSyncStatus;
  statusMessage: string;
  loading: boolean;
  applying: boolean;
  error: string | null;
  success: string | null;
  summary: TossHoldingsDryRunResponse["summary"] | null;
  changes: TossHoldingsDryRunResponse["changes"] | null;
  blockedRows: TossHoldingsBlockedRow[];
  canRunDryRun: boolean;
  canApply: boolean;
  onRunDryRun: () => void | Promise<void>;
  onApply: () => void | Promise<void>;
}

const FIELD_LABELS: Record<string, string> = {
  quantity: "qty",
  entry_price: "entry",
  entry_currency: "currency",
  entry_date: "date",
  strategy: "strategy",
  entry_pattern: "pattern",
  notes: "notes",
  tags: "tags",
  stop_override: "stop",
  target_override: "target",
};

function displayValue(value: unknown): string {
  if (value == null || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.join(", ") : "-";
  }
  return String(value);
}

function readSnapshotValue(
  snapshot: HoldingSnapshot | HoldingReplaceSnapshot,
  field: string,
): unknown {
  return (snapshot as Record<string, unknown>)[field];
}

function nextActionForBlockedRow(row: TossHoldingsBlockedRow): string {
  switch (row.reason) {
    case "ticker_exchange_unresolved":
      return "Next: edit or create the holding with an explicit .NAS/.NYS/.AMS suffix, then run a new dry-run.";
    case "invalid_decimal":
      return "Next: keep Supabase unchanged and run a new dry-run after checking the Toss row.";
    case "unknown_currency":
    case "unknown_market_country":
      return "Next: keep Supabase unchanged and check the Toss account or API response.";
  }
}

function DisclosureGroup({
  title,
  count,
  defaultExpanded,
  danger = false,
  children,
}: {
  title: string;
  count: number;
  defaultExpanded: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  if (count <= 0) {
    return null;
  }
  const id = `toss-sync-${title.toLowerCase().replaceAll(" ", "-")}`;

  return (
    <section
      className={`${styles.diffGroup} ${danger ? styles.diffGroupDanger : ""}`}
    >
      <button
        type="button"
        className={styles.diffGroupToggle}
        aria-expanded={expanded}
        aria-controls={id}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>{title}</span>
        <span>{count}</span>
      </button>
      {expanded && (
        <div id={id} className={styles.diffGroupBody}>
          {children}
        </div>
      )}
    </section>
  );
}

function renderBlockedRows(rows: TossHoldingsBlockedRow[]) {
  return (
    <ul className={styles.diffRows}>
      {rows.map((row) => (
        <li key={`${row.symbol}-${row.reason}`} className={styles.diffRow}>
          <p className={styles.diffTicker}>{row.symbol || "Unresolved"}</p>
          <p className={styles.diffMeta}>
            {row.reason} · {row.marketCountry || "-"} · {row.currency || "-"}
          </p>
          <p className="subtle">{row.message}</p>
          <p className="subtle">{nextActionForBlockedRow(row)}</p>
        </li>
      ))}
    </ul>
  );
}

function renderDeleteRows(rows: TossHoldingDeleteChange[]) {
  return (
    <ul className={styles.diffRows}>
      {rows.map((row) => (
        <li key={row.ticker} className={styles.diffRow}>
          <p className={styles.diffTicker}>{row.ticker}</p>
          <p className={styles.diffMeta}>
            qty {row.before.quantity} · entry {row.before.entry_price}
          </p>
          <p className="subtle">
            Missing from the Toss snapshot. Dry-run reviews it; apply removes it
            after confirmation.
          </p>
        </li>
      ))}
    </ul>
  );
}

function renderUpdateRows(rows: TossHoldingUpdateChange[]) {
  return (
    <ul className={styles.diffRows}>
      {rows.map((row) => (
        <li key={row.ticker} className={styles.diffRow}>
          <p className={styles.diffTicker}>{row.ticker}</p>
          <ul className={styles.fieldList}>
            {row.changedFields.map((field) => (
              <li key={field}>
                <span>{FIELD_LABELS[field] ?? field}</span>
                <span>
                  {displayValue(readSnapshotValue(row.before, field))} -&gt;{" "}
                  {displayValue(readSnapshotValue(row.after, field))}
                </span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

function renderCreateRows(rows: TossHoldingCreateChange[]) {
  return (
    <ul className={styles.diffRows}>
      {rows.map((row) => (
        <li key={row.ticker} className={styles.diffRow}>
          <p className={styles.diffTicker}>{row.ticker}</p>
          <p className={styles.diffMeta}>
            qty {row.after.quantity} · entry {row.after.entry_price} ·{" "}
            {row.after.entry_currency ?? "KRW"}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function TossSyncPanel({
  status,
  statusMessage,
  loading,
  applying,
  error,
  success,
  summary,
  changes,
  blockedRows,
  canRunDryRun,
  canApply,
  onRunDryRun,
  onApply,
}: TossSyncPanelProps) {
  const actionLabel =
    status === "idle" || status === "error" || status === "rate-limited"
      ? "Fetch Toss Snapshot"
      : "Run New Dry-run";
  const hasBlockingError =
    status === "error" || status === "rate-limited" || status === "blocked";

  return (
    <aside className="panel" aria-busy={loading || applying}>
      <div className={styles.lookupPanelHeader}>
        <h2 className="panelTitle">Toss Sync</h2>
      </div>
      <p className="subtle">
        Broker-backed holdings sync. Dry-run fetches without writing Supabase.
      </p>
      <p
        className={hasBlockingError ? styles.error : "subtle"}
        role={
          status === "error" || status === "rate-limited" ? "alert" : "status"
        }
        aria-live="polite"
      >
        {statusMessage}
      </p>

      <div className={styles.formActions}>
        <button
          type="button"
          onClick={() => void onRunDryRun()}
          disabled={!canRunDryRun}
        >
          {loading ? "Fetching..." : actionLabel}
        </button>
      </div>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {success && (
        <p className={styles.success} role="status" aria-live="polite">
          {success}
        </p>
      )}

      {summary && (
        <section className={styles.summaryPanel}>
          <div className={styles.summaryGrid}>
            <div>
              <p className={styles.summaryLabel}>Incoming</p>
              <p className={styles.summaryValue}>{summary.incomingCount}</p>
            </div>
            <div>
              <p className={styles.summaryLabel}>Create</p>
              <p className={styles.summaryValue}>{summary.createCount}</p>
            </div>
            <div>
              <p className={styles.summaryLabel}>Update</p>
              <p className={styles.summaryValue}>{summary.updateCount}</p>
            </div>
            <div>
              <p className={styles.summaryLabel}>Delete</p>
              <p className={styles.summaryValue}>{summary.deleteCount}</p>
            </div>
            <div>
              <p className={styles.summaryLabel}>Unchanged</p>
              <p className={styles.summaryValue}>{summary.unchangedCount}</p>
            </div>
          </div>

          <DisclosureGroup
            title="Blocked"
            count={blockedRows.length}
            defaultExpanded
            danger
          >
            {renderBlockedRows(blockedRows)}
          </DisclosureGroup>
          <DisclosureGroup
            title="Delete"
            count={changes?.delete.length ?? 0}
            defaultExpanded
            danger
          >
            {renderDeleteRows(changes?.delete ?? [])}
          </DisclosureGroup>
          <DisclosureGroup
            title="Update"
            count={changes?.update.length ?? 0}
            defaultExpanded={Boolean(blockedRows.length === 0)}
          >
            {renderUpdateRows(changes?.update ?? [])}
          </DisclosureGroup>
          <DisclosureGroup
            title="Create"
            count={changes?.create.length ?? 0}
            defaultExpanded={Boolean(blockedRows.length === 0)}
          >
            {renderCreateRows(changes?.create ?? [])}
          </DisclosureGroup>

          {canApply && (
            <div className={styles.applyGuard}>
              <button
                type="button"
                className={styles.dangerButton}
                onClick={() => void onApply()}
                disabled={applying || loading}
              >
                {applying ? "Applying..." : "Apply Toss Snapshot"}
              </button>
            </div>
          )}
        </section>
      )}
    </aside>
  );
}
