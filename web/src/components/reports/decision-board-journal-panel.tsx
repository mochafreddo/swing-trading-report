import styles from "../reports-client.module.css";

import type { DecisionBoardJournalStatus } from "@/lib/types";

export function DecisionBoardJournalPanel({
  status,
}: {
  status: DecisionBoardJournalStatus;
}) {
  if (status.state !== "AVAILABLE" || status.records.length === 0) {
    return null;
  }

  return (
    <aside
      className={styles.journalPanel}
      aria-label="Local shadow run warning"
    >
      <h3>Local shadow run warning</h3>
      <p>
        Report status와 별개인 로컬 shadow 실행 관측입니다. 누락되거나 완료되지
        않은 실행을 수동으로 확인하세요.
      </p>
      <ul>
        {status.records.map((record) => (
          <li key={`${record.run_kind}:${record.expected_at}:${record.run_id}`}>
            <strong>{record.status}</strong>
            {" · "}
            {record.run_kind}
            {" · "}
            {record.run_id}
            {" · "}
            {record.expected_at}
          </li>
        ))}
      </ul>
    </aside>
  );
}
