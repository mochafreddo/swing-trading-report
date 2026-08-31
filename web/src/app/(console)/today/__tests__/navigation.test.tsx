import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const redirect = vi.hoisted(() => vi.fn());

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    "aria-current"?: "page";
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({
  redirect,
  usePathname: () => "/today",
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/app/actions/auth", () => ({ logoutAction: vi.fn() }));

import IndexPage from "@/app/page";
import { MainNav } from "@/components/main-nav";

describe("Today navigation", () => {
  it("redirects the root route to Today", () => {
    IndexPage();
    expect(redirect).toHaveBeenCalledWith("/today");
  });

  it("renders Today as the first main navigation item", () => {
    const html = renderToStaticMarkup(createElement(MainNav));
    expect(html.indexOf('href="/today"')).toBeLessThan(
      html.indexOf('href="/reports"'),
    );
    expect(html).toMatch(/href="\/today"[^>]+aria-current="page"/);
  });
});
