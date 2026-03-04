"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import styles from "./login-form.module.css";

function readApiError(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return undefined;
  }
  const value = (payload as { error?: unknown }).error;
  return typeof value === "string" && value.trim() ? value : undefined;
}

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

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectPath = useMemo(
    () => sanitizeNextPath(searchParams.get("next")),
    [searchParams],
  );

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      let payload: unknown = null;
      try {
        payload = (await response.json()) as unknown;
      } catch {
        payload = null;
      }

      if (!response.ok) {
        throw new Error(readApiError(payload) || "Login failed");
      }

      router.replace(redirectPath);
      router.refresh();
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "Login failed",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className={styles.wrapper}>
      <form className={styles.form} onSubmit={(event) => void onSubmit(event)}>
        <label className={styles.field}>
          <span className={styles.label}>Username</span>
          <input
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
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        <button className={styles.button} type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign In"}
        </button>
      </form>
    </section>
  );
}
