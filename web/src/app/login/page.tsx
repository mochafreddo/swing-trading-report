import { Suspense } from "react";

import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <section className="panel">
      <h1 className="panelTitle">Admin Sign In</h1>
      <p className="subtle">
        운영 콘솔 접근을 위해 관리자 자격 증명을 입력하세요.
      </p>
      <Suspense fallback={<p className="subtle">Loading sign-in form...</p>}>
        <LoginForm />
      </Suspense>
    </section>
  );
}
