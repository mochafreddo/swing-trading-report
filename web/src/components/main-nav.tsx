"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import styles from "./main-nav.module.css";

const NAV_ITEMS = [
  { href: "/reports", label: "Reports" },
  { href: "/holdings", label: "Holdings" },
  { href: "/run", label: "Run" }
] as const;

export function MainNav() {
  const pathname = usePathname();

  return (
    <nav className={styles.nav} aria-label="Main navigation">
      {NAV_ITEMS.map((item) => {
        const active = pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`${styles.link} ${active ? styles.active : ""}`.trim()}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
