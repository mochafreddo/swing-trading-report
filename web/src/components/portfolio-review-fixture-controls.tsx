"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  parseReviewFixtureResult,
  type ReviewFixtureVerification,
} from "@/lib/portfolio-review-fixture-schema";
import styles from "./today-decision-board.module.css";

const commands = [
  ["compile", "합성 입력으로 검토 저장"],
  ["block", "근거 부족 검토 저장"],
  ["correct", "합성 관측 정정 후 재검토"],
  ["unlinked", "미연결 Outcome 기록"],
  ["ambiguous", "모호한 Outcome으로 정정"],
  ["no_action", "이 합성 검토에서 아무 행동도 하지 않았음 확인"],
  ["replay", "저장된 검토 재검증"],
  ["receive", "합성 로컬 수신 확인"],
] as const;

export function PortfolioReviewFixtureControls({ runId }: { runId: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [message, setMessage] = useState("");
  const [verification, setVerification] =
    useState<ReviewFixtureVerification | null>(null);
  function submit(command: string) {
    setMessage("");
    setVerification(null);
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
        const result = parseReviewFixtureResult(
          await response.json(),
          command,
          runId,
        );
        setVerification(result.verification ?? null);
        setMessage(
          result.verification
            ? "확인을 마쳤습니다."
            : "폐기형 DB에 저장했습니다.",
        );
        router.refresh();
      } catch {
        setMessage(
          "처리 결과를 확인하지 못했습니다. 새로고침하여 현재 검토를 확인하세요.",
        );
      }
    });
  }
  return (
    <fieldset disabled={pending} className={styles.dogfoodPanel}>
      <legend>합성 입력 → 검토 → Outcome 직접 사용</legend>
      <p>
        이 화면은 새 폐기형 DB만 사용합니다. 관측 정정은 합성 값 2와 -2를 번갈아
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
        {pending ? "처리 중…" : message}
      </p>
      {verification && (
        <section aria-label="검토 검증 결과">
          {verification.kind === "REPLAY" ? (
            <>
              <p>
                REPLAY_MATCH · 저장 당시 입력·시각·기준으로 다시 계산한 결과가
                일치합니다.
              </p>
              <p>현재 시점의 유효성이나 실제 gate 통과를 뜻하지 않습니다.</p>
              <details>
                <summary>검증한 저장 기록</summary>
                <p>
                  Run <code>{verification.run_id}</code>
                </p>
                <p>
                  Packet <code>{verification.packet_sha256}</code>
                </p>
                <p>
                  Projection <code>{verification.projection_sha256}</code>
                </p>
              </details>
            </>
          ) : (
            <>
              <p>LOCAL_REVIEW_SINK · 외부 전송 0건</p>
              <p>
                합성 owner 전체에서 이번 요청으로 {verification.newly_received}
                건의 수신을 확인했습니다.
              </p>
              <p>
                현재 검토: 총 {verification.total}건 · 수신{" "}
                {verification.received}건 · 대기 {verification.pending}건
              </p>
              <p>폐기형 DB 내부 확인이며 실제 알림 전달이 아닙니다.</p>
            </>
          )}
        </section>
      )}
    </fieldset>
  );
}
