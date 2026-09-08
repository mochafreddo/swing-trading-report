"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import styles from "./today-decision-board.module.css";

const commands = [
  ["compile", "합성 입력으로 검토 저장"],
  ["block", "근거 부족 검토 저장"],
  ["correct", "합성 관측 정정 후 재검토"],
  ["unlinked", "미연결 Outcome 기록"],
  ["ambiguous", "모호한 Outcome으로 정정"],
  ["no_action", "이 합성 검토에서 아무 행동도 하지 않았음 확인"],
] as const;

export function PortfolioReviewFixtureControls({ runId }: { runId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [message, setMessage] = useState("");
  function submit(command: string) {
    setMessage("");
    startTransition(async () => {
      try {
        const response = await fetch("/api/portfolio-review-fixture", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            command,
            request_id: crypto.randomUUID(),
            run_id: runId,
          }),
        });
        if (!response.ok) throw new Error("REJECTED");
        setMessage("폐기형 DB에 저장했습니다.");
        router.refresh();
      } catch {
        setMessage(
          "저장 결과를 확인하지 못했습니다. 새로고침하여 현재 검토를 확인하세요.",
        );
      }
    });
  }
  return (
    <fieldset disabled={pending} className={styles.dogfoodPanel}>
      <legend>합성 입력 → 검토 → Outcome 직접 사용</legend>
      <p>
        버튼은 새 폐기형 DB에만 기록합니다. 관측 정정은 합성 값 2와 -2를 번갈아
        추가합니다. 외부 전송은 없습니다.
      </p>
      <div className={styles.localPreviewControls}>
        {commands.map(([command, label]) => (
          <button key={command} type="button" onClick={() => submit(command)}>
            {label}
          </button>
        ))}
      </div>
      <p role="status" aria-live="polite">
        {pending ? "저장 중…" : message}
      </p>
    </fieldset>
  );
}
