import { describe, expect, it } from "vitest";

import {
  collectTickerAliases,
  extractBuyCandidateFromRow,
  extractBuyCandidatesFromRows,
} from "@/lib/ticker-directory-candidates";

describe("ticker directory candidate helpers", () => {
  it("normalizes a buy report candidate row", () => {
    expect(
      extractBuyCandidateFromRow({
        ticker: " brk/b.nys ",
        name: " Berkshire Hathaway ",
      }),
    ).toEqual({
      ticker: "BRK.B.NYS",
      name: "Berkshire Hathaway",
    });
  });

  it("returns null for invalid candidate rows", () => {
    expect(extractBuyCandidateFromRow(null)).toBeNull();
    expect(extractBuyCandidateFromRow([])).toBeNull();
    expect(
      extractBuyCandidateFromRow({ ticker: "  ", name: "blank" }),
    ).toBeNull();
  });

  it("deduplicates extracted rows while keeping first-seen candidate data", () => {
    expect(
      extractBuyCandidatesFromRows([
        { ticker: "ABBV.NYS", name: "애브비" },
        { ticker: "abbv.nys", name: "AbbVie" },
        { ticker: "ETN.NYS", name: "이튼" },
      ]),
    ).toEqual([
      { ticker: "ABBV.NYS", name: "애브비" },
      { ticker: "ETN.NYS", name: "이튼" },
    ]);
  });

  it("collects class-share and compact-name aliases", () => {
    expect(collectTickerAliases("BRK.B.NYS", "Berkshire Hathaway")).toEqual([
      "BRK.B.NYS",
      "BRK.B",
      "BRK/B",
      "BRK/B.NYS",
      "Berkshire Hathaway",
      "BerkshireHathaway",
    ]);
  });
});
