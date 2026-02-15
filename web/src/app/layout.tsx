import type { Metadata } from "next";

import { MainNav } from "@/components/main-nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "SAB Control Panel",
  description: "Reports, holdings, and workflow dispatch console.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <header className="top-bar">
            <div>
              <p className="eyebrow">Swing Trading Report</p>
              <h1 className="title">Operations Console</h1>
            </div>
            <MainNav />
          </header>
          <main className="main-content">{children}</main>
        </div>
      </body>
    </html>
  );
}
