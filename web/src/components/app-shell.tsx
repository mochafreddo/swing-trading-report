"use client";

import { usePathname } from "next/navigation";

import { MainNav } from "@/components/main-nav";

type AppShellProps = {
  children: React.ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const isLoginPage = pathname === "/login";

  return (
    <div className="app-shell">
      <header className="top-bar">
        <div>
          <p className="eyebrow">Swing Trading Report</p>
          <h1 className="title">Operations Console</h1>
        </div>
        {!isLoginPage ? <MainNav /> : null}
      </header>
      <main className="main-content">{children}</main>
    </div>
  );
}
