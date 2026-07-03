"use client";

import { FormEvent, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { loginAction } from "@/app/actions/auth";

import styles from "./login-form.module.css";

function sanitizeNextPath(rawNext: string | null): string {
  if (!rawNext) {
    return "/reports";
  }
  if (!rawNext.startsWith("/") || rawNext.startsWith("//")) {
    return "/reports";
  }
  if (rawNext.startsWith("/login")) {
    return "/reports";
  }
  return rawNext;
}

function getRedirectLabel(path: string): string {
  if (path.startsWith("/holdings")) {
    return "Holdings upkeep";
  }
  if (path.startsWith("/run")) {
    return "Workflow dispatch";
  }
  if (path.startsWith("/metrics")) {
    return "Metrics dashboard";
  }
  if (path.startsWith("/reports")) {
    return "Reports review";
  }
  return "Requested console page";
}

function getLoginErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "Login failed";

  if (message === "Unauthorized") {
    return "사용자 이름 또는 비밀번호가 맞지 않습니다. 로컬 웹 자격 증명을 확인한 뒤 다시 시도하세요.";
  }

  return message;
}

const REQUIRED_CREDENTIALS_MESSAGE =
  "사용자 이름과 비밀번호를 입력한 뒤 다시 시도하세요.";

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const usernameInputRef = useRef<HTMLInputElement>(null);
  const passwordInputRef = useRef<HTMLInputElement>(null);
  const redirectPath = useMemo(
    () => sanitizeNextPath(searchParams.get("next")),
    [searchParams],
  );
  const redirectLabel = useMemo(
    () => getRedirectLabel(redirectPath),
    [redirectPath],
  );

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (!username.trim() || !password) {
      setError(REQUIRED_CREDENTIALS_MESSAGE);
      if (!username.trim()) {
        usernameInputRef.current?.focus();
      } else {
        passwordInputRef.current?.focus();
      }
      return;
    }

    setSubmitting(true);

    try {
      const result = await loginAction({
        username: username.trim(),
        password,
      });
      if (!result.ok) {
        throw new Error(result.error);
      }

      router.replace(redirectPath);
      router.refresh();
    } catch (requestError) {
      setError(getLoginErrorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className={styles.wrapper}>
      <form
        className={styles.form}
        noValidate
        onSubmit={(event) => void onSubmit(event)}
      >
        <div className={styles.destination}>
          <span>After sign-in</span>
          <strong>{redirectLabel}</strong>
        </div>

        <label className={styles.field}>
          <span className={styles.label}>Username</span>
          <input
            ref={usernameInputRef}
            className={styles.input}
            autoComplete="username"
            name="username"
            type="text"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Password</span>
          <input
            ref={passwordInputRef}
            className={styles.input}
            autoComplete="current-password"
            name="password"
            type="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        <p className="visuallyHidden" role="status" aria-live="polite">
          {submitting ? "로그인 중" : ""}
        </p>

        {error ? (
          <div className={styles.error} role="alert">
            <strong>로그인 실패</strong>
            <span>{error}</span>
          </div>
        ) : null}

        <button className={styles.button} type="submit" disabled={submitting}>
          {submitting ? (
            <>
              <svg className="spinner" fill="none" viewBox="0 0 24 24">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                  opacity="0.25"
                ></circle>
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
              Signing in…
            </>
          ) : (
            "Sign in"
          )}
        </button>
      </form>
    </section>
  );
}
