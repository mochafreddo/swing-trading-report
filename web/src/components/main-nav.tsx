"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { requestLogout } from "@/lib/logout-client";

import styles from "./main-nav.module.css";

const NAV_ITEMS = [
  { href: "/reports", label: "Reports" },
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
      await requestLogout();
      router.replace("/login");
      router.refresh();
    } catch (error) {
      setLogoutError(
        error instanceof Error ? error.message : "Sign out failed",
      );
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className={styles.container}>
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
        <button
          type="button"
          className={styles.link}
          onClick={() => void onLogout()}
          disabled={loggingOut}
        >
          {loggingOut ? "Signing out..." : "Sign Out"}
        </button>
      </nav>
      {logoutError ? (
        <p className={styles.error} role="alert">
          {logoutError}
        </p>
      ) : null}
    </div>
  );
}
