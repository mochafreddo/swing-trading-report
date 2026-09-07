"use client";

import { useRef, useState, type FormEvent } from "react";

import fixture from "../../fixtures/toss-order-history.synthetic.json";
import {
  adaptTossOrderHistory,
  type OrderHistoryView,
} from "@/lib/toss/order-history";

import styles from "./order-history-preview.module.css";

const scenarios = {
  complete: "정상 결과",
  empty: "빈 결과",
  incomplete: "페이지 미완결",
  invalid: "응답 오류",
} as const;
type Scenario = keyof typeof scenarios;
const documents: Record<Scenario, string> = {
  complete: JSON.stringify(fixture.pages),
  empty: JSON.stringify([
    {
      requestCursor: null,
      response: { result: { orders: [], hasNext: false, nextCursor: null } },
    },
  ]),
  incomplete: JSON.stringify(fixture.pages.slice(0, 1)),
  invalid: "invalid synthetic response",
};
const states = {
  COMPLETE: "조회 완료",
  EMPTY: "조회 결과 없음",
  INCOMPLETE: "페이지 미완결 · 결과 표시 보류",
  ERROR: "검증 실패 · 결과 표시 보류",
};
const statusLabels = {
  FILLED: "체결 완료",
  PARTIAL_FILLED: "부분체결",
  CANCELED: "취소",
  REPLACED: "정정",
  REJECTED: "거부",
  CANCEL_REJECTED: "취소 거부",
  REPLACE_REJECTED: "정정 거부",
};

export function OrderHistoryPreview() {
  const [from, setFrom] = useState("2026-08-07");
  const [to, setTo] = useState("2026-09-05");
  const [scenario, setScenario] = useState<Scenario>("complete");
  const [view, setView] = useState<OrderHistoryView | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = adaptTossOrderHistory(documents[scenario], from, to);
    setView(result);
    if (result.state === "ERROR") resultRef.current?.focus();
  }

  return (
    <section
      id="order-history-preview"
      className={styles.panel}
      aria-labelledby="order-history-title"
    >
      <header className={styles.heading}>
        <div>
          <p className={styles.kicker}>주문별 체결 결과</p>
          <h2 id="order-history-title">토스 주문 이력 · 합성 미리보기</h2>
        </div>
        <span className={styles.badge}>SYNTHETIC_ONLY · NO ADVICE</span>
      </header>
      <p id="order-history-help" className={styles.help}>
        실제 계좌가 아닌 합성 데이터입니다. API 호출·저장·주문은 하지 않습니다.
        주문별 누적 체결 결과이며 개별 체결이나 정정 연결을 추정하지 않습니다.
      </p>
      <form
        onSubmit={submit}
        aria-describedby="order-history-help order-history-period-help"
        noValidate
      >
        <fieldset className={styles.period}>
          <legend>주문 생성일 · KST (최대 30일, 양 끝 포함)</legend>
          <label htmlFor="order-history-from">
            시작일
            <input
              id="order-history-from"
              name="from"
              type="date"
              required
              value={from}
              aria-invalid={view?.issue === "INVALID_DATE_RANGE"}
              aria-describedby="order-history-result"
              onChange={(event) => {
                setFrom(event.target.value);
                setView(null);
              }}
            />
          </label>
          <label htmlFor="order-history-to">
            종료일
            <input
              id="order-history-to"
              name="to"
              type="date"
              required
              value={to}
              aria-invalid={view?.issue === "INVALID_DATE_RANGE"}
              aria-describedby="order-history-result"
              onChange={(event) => {
                setTo(event.target.value);
                setView(null);
              }}
            />
          </label>
        </fieldset>
        <p id="order-history-period-help" className={styles.help}>
          종료 주문(CLOSED)만 대상으로 하며, 체결 시각이 아닌 주문 생성일로
          필터링합니다.
        </p>
        <fieldset className={styles.scenarios}>
          <legend>검증 시나리오</legend>
          {Object.entries(scenarios).map(([key, label]) => (
            <label key={key}>
              <input
                type="radio"
                name="order-history-scenario"
                value={key}
                checked={scenario === key}
                onChange={() => {
                  setScenario(key as Scenario);
                  setView(null);
                }}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <div className={styles.actions}>
          <button type="submit">합성 내역 조회</button>
          <button type="button" onClick={() => setView(null)}>
            결과 지우기
          </button>
        </div>
      </form>
      <div
        id="order-history-result"
        ref={resultRef}
        tabIndex={-1}
        className={styles.result}
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {view ? (
          <>
            <strong>{states[view.state]}</strong>
            <span>
              검사한 페이지 {view.pagesSeen}개 · 표시 주문 {view.rows.length}건
            </span>
            {view.issue ? (
              <span>
                {view.issue === "INVALID_DATE_RANGE"
                  ? "유효한 시작일·종료일과 최대 30일 범위를 확인해 주세요."
                  : "응답 형식과 페이지 연결을 확인해 주세요. 기존 결과는 제거했습니다."}
              </span>
            ) : null}
          </>
        ) : (
          <span>조회 전 · 이 화면은 실제 API에 연결되지 않았습니다.</span>
        )}
      </div>
      {view?.state === "COMPLETE" ? (
        <div
          className={styles.tableScroll}
          role="region"
          aria-label="주문별 결과 표"
          tabIndex={0}
        >
          <table>
            <caption>합성 종료 주문 · 개별 체결 명세가 아님</caption>
            <thead>
              <tr>
                <th scope="col">주문 생성 시각 (KST)</th>
                <th scope="col">종목</th>
                <th scope="col">주문 방향</th>
                <th scope="col">주문 상태</th>
                <th scope="col">누적 체결량</th>
                <th scope="col">평균 체결가</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr key={row.rowKey}>
                  <td>{row.orderedAtKst.slice(0, 19).replace("T", " ")}</td>
                  <td>{row.symbol}</td>
                  <td>{row.side === "BUY" ? "매수" : "매도"}</td>
                  <td>{statusLabels[row.status]}</td>
                  <td>{row.filledQuantity}</td>
                  <td>
                    {row.averageFilledPrice === null
                      ? "—"
                      : `${row.averageFilledPrice} ${row.currency}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
