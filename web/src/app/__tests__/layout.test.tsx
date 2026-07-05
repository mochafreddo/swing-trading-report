import { describe, expect, it } from "vitest";

import RootLayout from "@/app/layout";

describe("RootLayout", () => {
  it("declares Korean as the default document language", () => {
    const element = RootLayout({ children: "content" });

    expect(element.type).toBe("html");
    expect(element.props.lang).toBe("ko");
  });
});
