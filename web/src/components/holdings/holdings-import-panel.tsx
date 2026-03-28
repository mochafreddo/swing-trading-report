import styles from "../holdings-client.module.css";

import type { HoldingsYamlImportSummary } from "@/lib/types";

interface HoldingsImportPanelProps {
  fileName: string | null;
  loading: boolean;
  applying: boolean;
  error: string | null;
  success: string | null;
  summary: HoldingsYamlImportSummary | null;
  canDryRun: boolean;
  canApply: boolean;
  onFileSelected: (file: File | null) => void | Promise<void>;
  onDryRun: () => void | Promise<void>;
  onApply: () => void | Promise<void>;
}

function renderTickerList(title: string, items: string[]) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div>
      <p className={styles.summaryListTitle}>{title}</p>
      <p className="subtle">{items.join(", ")}</p>
    </div>
  );
}

export function HoldingsImportPanel({
  fileName,
  loading,
  applying,
  error,
  success,
  summary,
  canDryRun,
  canApply,
  onFileSelected,
  onDryRun,
  onApply,
}: HoldingsImportPanelProps) {
  return (
    <aside className="panel">
      <div className={styles.lookupPanelHeader}>
        <h2 className="panelTitle">Holdings YAML</h2>
      </div>
      <p className="subtle">
        전체 holdings 스냅샷 백업/복구용. apply 시 현재 DB를 파일 내용으로
        교체합니다.
      </p>

      <label className={styles.fileInputLabel}>
        <span>YAML File</span>
        <input
          type="file"
          accept=".yaml,.yml,application/yaml,text/yaml,text/plain"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0] ?? null;
            void onFileSelected(file);
            event.currentTarget.value = "";
          }}
        />
      </label>

      <p className="subtle">
        {fileName ? `선택됨: ${fileName}` : "파일을 선택하세요."}
      </p>

      <div className={styles.formActions}>
        <button
          type="button"
          onClick={() => void onDryRun()}
          disabled={!canDryRun || loading || applying}
        >
          {loading ? "Dry-run…" : "Dry-run"}
        </button>
        <button
          type="button"
          onClick={() => void onApply()}
          disabled={!canApply || loading || applying}
          className={styles.dangerButton}
        >
          {applying ? "Applying…" : "Apply Import"}
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
          {renderTickerList("Create", summary.createTickers)}
          {renderTickerList("Update", summary.updateTickers)}
          {renderTickerList("Delete", summary.deleteTickers)}
        </section>
      )}
    </aside>
  );
}
