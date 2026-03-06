"use client";

import { useEffect } from "react";

export default function ConsoleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <section className="panel">
      <h2 className="panelTitle">Console Error</h2>
      <p className="subtle">
        콘솔 데이터를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.
      </p>
      <button type="button" onClick={() => reset()}>
        Retry
      </button>
    </section>
  );
}
