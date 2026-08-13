import styles from "../reports-client.module.css";

import type { DecisionBoardEnvelopeV0 } from "@/lib/decision-board-schema";

function issueCodes(issues: DecisionBoardEnvelopeV0["issues"]): string {
  return issues.length > 0
    ? issues.map((issue) => issue.code).join(" · ")
    : "-";
}

export function DecisionBoardDetail({
  report,
  showRaw,
  rawJson,
}: {
  report: DecisionBoardEnvelopeV0;
  showRaw: boolean;
  rawJson: string;
}) {
  return (
    <>
      <dl className={styles.metaGrid}>
        <div>
          <dt>schema</dt>
          <dd>{report.schema_version}</dd>
        </div>
        <div>
          <dt>run kind</dt>
          <dd>{report.run_kind}</dd>
        </div>
        <div>
          <dt>status</dt>
          <dd>{report.status}</dd>
        </div>
        <div>
          <dt>run ID</dt>
          <dd>{report.run_id}</dd>
        </div>
        <div>
          <dt>created</dt>
          <dd>{report.created_at}</dd>
        </div>
      </dl>

      <p className={styles.infoNote}>
        Decision Board는 공개 근거만 담는 advice-only shadow 결과입니다.
      </p>

      {report.status === "BLOCKED" ? (
        <section className={styles.decisionBlocked}>
          <h3 className={styles.sectionTitle}>Shared issues</h3>
          <ul>
            {report.issues.map((issue) => (
              <li key={issue.code}>
                <strong>{issue.code}</strong> — {issue.message}
              </li>
            ))}
          </ul>
        </section>
      ) : report.decision_payload.items.length === 0 ? (
        <p className={styles.infoNote}>No eligible Decision Board items.</p>
      ) : (
        <div className={styles.tableWrap}>
          <h3 className={styles.sectionTitle}>
            Decision items ({report.decision_payload.items.length})
          </h3>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Exchange</th>
                <th>Status</th>
                <th>Action</th>
                <th>Reason codes</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {report.decision_payload.items.map((item) => (
                <tr key={item.instrument.canonical_ticker}>
                  <td data-label="Ticker">
                    <strong>{item.instrument.canonical_ticker}</strong>
                    <br />
                    <span className="subtle">
                      {item.instrument.company_name}
                    </span>
                  </td>
                  <td data-label="Exchange">{item.instrument.exchange}</td>
                  <td data-label="Status">{item.status}</td>
                  <td
                    data-label="Action"
                    className={
                      item.status === "DECIDED" && item.action === "SELL"
                        ? styles.decisionSell
                        : undefined
                    }
                  >
                    {item.status === "DECIDED" ? item.action : "-"}
                  </td>
                  <td data-label="Reason codes">{issueCodes(item.issues)}</td>
                  <td data-label="Evidence">
                    {item.evidence.length > 0
                      ? item.evidence.map((evidence) => (
                          <span key={evidence.claim_id}>
                            <a
                              href={evidence.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {evidence.citation_label}
                            </a>{" "}
                            ({evidence.role} · {evidence.publisher} ·{" "}
                            <time dateTime={evidence.published_at}>
                              {evidence.published_at}
                            </time>{" "}
                            · {evidence.freshness})
                          </span>
                        ))
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {report.issues.length > 0 && report.status !== "BLOCKED" && (
        <p className={styles.infoNote}>
          Run issues: {issueCodes(report.issues)}
        </p>
      )}
      {showRaw && (
        <pre id="report-raw-json" className={styles.raw}>
          {rawJson}
        </pre>
      )}
    </>
  );
}
