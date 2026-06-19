import { Suspense } from "react";

import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <section className="auth-shell">
      <div className="auth-copy">
        <p className="eyebrow">Swing Trading Report</p>
        <h1 className="auth-title">Local trading operations console.</h1>
        <p className="auth-lede">
          리포트 검토, 보유 종목 정리, scan·sell 실행을 한 곳에서 처리합니다.
        </p>
        <ul className="auth-list">
          <li>
            <strong>Reports review</strong>
            <span>
              Supabase Storage 리포트를 빠르게 탐색하고 원본 JSON까지
              확인합니다.
            </span>
          </li>
          <li>
            <strong>Holdings upkeep</strong>
            <span>활성 보유분과 추가 매수를 같은 흐름에서 업데이트합니다.</span>
          </li>
          <li>
            <strong>Workflow dispatch</strong>
            <span>
              scan·sell 실행을 안전한 로컬 경계 안에서 직접 트리거합니다.
            </span>
          </li>
        </ul>
      </div>

      <div className="auth-panel">
        <p className="auth-panel-label">관리자 인증</p>
        <h2 className="panelTitle">Sign in</h2>
        <p className="subtle">
          운영 콘솔 접근을 위해 관리자 자격 증명을 입력하세요.
        </p>
        <Suspense fallback={<p className="subtle">Loading sign-in form...</p>}>
          <LoginForm />
        </Suspense>
      </div>
    </section>
  );
}
