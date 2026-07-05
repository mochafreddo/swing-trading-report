import type { Metadata } from "next";

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
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
