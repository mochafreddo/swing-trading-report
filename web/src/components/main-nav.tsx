"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

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

  return (
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
  );
}
