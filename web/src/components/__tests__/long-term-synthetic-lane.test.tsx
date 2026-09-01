import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LongTermSyntheticLane } from "@/components/long-term-synthetic-lane";
import { parsePortfolioLongTermT13Fixture } from "@/lib/portfolio-long-term-schema";

const fixturePath = fileURLToPath(
  new URL(
    "../../../fixtures/portfolio-long-term.t13.synthetic.json",
    import.meta.url,
  ),
);
const stylePath = fileURLToPath(
  new URL("../today-decision-board.module.css", import.meta.url),
);

describe("LongTermSyntheticLane", () => {
  it("renders every policy outcome as local-only audit evidence", () => {
    const fixture = parsePortfolioLongTermT13Fixture(
      JSON.parse(readFileSync(fixturePath, "utf8")),
    );
    const html = renderToStaticMarkup(
      createElement(LongTermSyntheticLane, { fixture }),
    );

    expect(html).toContain("LONG_TERM synthetic lane");
    expect(html).toContain("8 synthetic cases");
    expect(html).toContain("LOCAL_ONLY · NOT ACTIVE");
    expect(html).toContain("ACME.NAS");
    expect(html).toContain("PREDICATE_NOT_FULFILLED");
    expect(html).toContain("PREDICATE_FULFILLED");
    expect(html).toContain("EVIDENCE_STALE");
    expect(html).toContain("EVIDENCE_CONFLICTED");
    expect(html).toContain("CONCENTRATION_BREACH");
    expect(html).toContain("PREDICATE_REVIEW_ONLY");
    expect(html).toContain("UNCLASSIFIED · NO ADVICE");
    expect(html).toContain("REVIEW_NOT_DUE");
    expect(html).toContain(
      "No real holding, provider, database, or order connection",
    );
  });

  it("collapses the LONG_TERM grid to one column at the mobile breakpoint", () => {
    const css = readFileSync(stylePath, "utf8");
    const mobileRules = css.slice(css.indexOf("@media (max-width: 680px)"));

    expect(mobileRules).toMatch(
      /\.longTermGrid(?:,\s*\.[^{]+)*\s*\{[^}]*grid-template-columns:\s*1fr;/,
    );
  });
});
