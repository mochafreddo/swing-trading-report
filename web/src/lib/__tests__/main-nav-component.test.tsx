import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a className={className} href={href}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/metrics",
  useRouter: () => ({
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("@/app/actions/auth", () => ({
  logoutAction: vi.fn(),
}));

import { MainNav } from "@/components/main-nav";

describe("MainNav component", () => {
  it("renders the metrics navigation item", () => {
    const html = renderToStaticMarkup(createElement(MainNav));

    expect(html).toContain('href="/metrics"');
    expect(html).toContain(">Metrics<");
  });
});
