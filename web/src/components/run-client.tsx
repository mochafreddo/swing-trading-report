"use client";

import { useState } from "react";

import styles from "./run-client.module.css";

import type { Provider, WorkflowDispatchResult } from "@/lib/types";

function readApiError(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return undefined;
  }
  const value = (payload as { error?: unknown }).error;
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function RunClient() {
  const [provider, setProvider] = useState<Provider>("kis");
  const [universe, setUniverse] = useState<"KR" | "US" | "both">("both");
  const [loading, setLoading] = useState<"scan" | "sell" | null>(null);
  const [result, setResult] = useState<WorkflowDispatchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const trigger = async (workflow: "scan" | "sell") => {
    setLoading(workflow);
    setError(null);

    const payload =
      workflow === "scan"
        ? { workflow, provider, universe }
        : { workflow, provider };

    try {
      const response = await fetch("/api/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const body = (await response.json()) as unknown;
      if (!response.ok) {
        throw new Error(readApiError(body) || `${workflow} dispatch failed`);
      }

      setResult(body as WorkflowDispatchResult);
    } catch (dispatchError) {
      setResult(null);
      setError(
        dispatchError instanceof Error
          ? dispatchError.message
          : `${workflow} dispatch failed`
      );
    } finally {
      setLoading(null);
    }
  };

  return (
    <section className={styles.wrapper}>
      <article className={`panel ${styles.configPanel}`}>
        <h2 className="panelTitle">Run Configuration</h2>
        <p className="subtle">workflow_dispatch 입력 화이트리스트 적용</p>

        <label>
          Provider
          <select
            name="provider"
            autoComplete="off"
            value={provider}
            onChange={(event) => setProvider(event.target.value as Provider)}
          >
            <option value="kis">kis</option>
            <option value="pykrx">pykrx</option>
          </select>
        </label>

        <label>
          Universe (scan only)
          <select
            name="universe"
            autoComplete="off"
            value={universe}
            onChange={(event) =>
              setUniverse(event.target.value as "KR" | "US" | "both")
            }
          >
            <option value="KR">KR</option>
            <option value="US">US</option>
            <option value="both">both</option>
          </select>
        </label>

        <div className={styles.actions}>
          <button
            type="button"
            onClick={() => void trigger("scan")}
            disabled={loading !== null}
          >
            {loading === "scan" ? "Dispatching scan..." : "Run Scan"}
          </button>
          <button
            type="button"
            onClick={() => void trigger("sell")}
            disabled={loading !== null}
          >
            {loading === "sell" ? "Dispatching sell..." : "Run Sell"}
          </button>
        </div>
      </article>

      <article className="panel">
        <h2 className="panelTitle">Dispatch Result</h2>
        <p className="subtle">GitHub Actions 링크를 통해 실행 상태를 확인합니다.</p>
        <p className="visuallyHidden" role="status" aria-live="polite">
          {loading
            ? `${loading} 워크플로 실행 요청 중`
            : result
              ? "워크플로 실행 요청 완료"
              : "워크플로 대기 중"}
        </p>

        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        {!error && !result && (
          <p className="subtle">scan 또는 sell 실행 버튼을 눌러 시작하세요.</p>
        )}

        {result && (
          <dl className={styles.metaGrid}>
            <div>
              <dt>Status</dt>
              <dd>{result.dispatched ? "실행 요청 완료" : "실패"}</dd>
            </div>
            <div>
              <dt>Workflow</dt>
              <dd>{result.workflowFile}</dd>
            </div>
            <div>
              <dt>Ref</dt>
              <dd>{result.ref}</dd>
            </div>
          </dl>
        )}

        {result && (
          <div className={styles.links}>
            <a href={result.workflowUrl} target="_blank" rel="noreferrer">
              Workflow Page
            </a>
            <a href={result.actionsUrl} target="_blank" rel="noreferrer">
              Actions Home
            </a>
          </div>
        )}
      </article>
    </section>
  );
}
