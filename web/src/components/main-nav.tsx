"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { logoutAction } from "@/app/actions/auth";
import { toErrorMessage } from "@/lib/error-utils";

import styles from "./main-nav.module.css";

const NAV_ITEMS = [
  { href: "/reports", label: "Reports" },
  { href: "/metrics", label: "Metrics" },
  { href: "/holdings", label: "Holdings" },
  { href: "/run", label: "Run" },
] as const;

function isActivePath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function MainNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const onLogout = async () => {
    setLoggingOut(true);
    setLogoutError(null);
    try {
      const result = await logoutAction();
      if (!result.ok) {
        throw new Error(result.error);
      }
      router.replace("/login");
      router.refresh();
    } catch (error) {
      setLogoutError(toErrorMessage(error, "Sign out failed"));
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.row}>
        <nav className={styles.nav} aria-label="Main navigation">
          {NAV_ITEMS.map((item) => {
            const active = isActivePath(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`${styles.link} ${active ? styles.active : ""}`.trim()}
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <button
          type="button"
          className={styles.action}
          onClick={() => void onLogout()}
          disabled={loggingOut}
        >
          {loggingOut ? (
            <>
              <svg
                className="spinner"
                style={{ marginRight: "8px" }}
                fill="none"
                viewBox="0 0 24 24"
              >
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
              Signing out…
            </>
          ) : (
            "Sign Out"
          )}
        </button>
      </div>
      {logoutError ? (
        <p className={styles.error} role="alert">
          {logoutError}
        </p>
      ) : null}
    </div>
  );
}
