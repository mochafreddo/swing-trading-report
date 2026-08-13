import { describe, expect, it } from "vitest";

import { parseDecisionBoardJsonBytes } from "@/lib/decision-board-json";

describe("parseDecisionBoardJsonBytes", () => {
  const encode = (text: string) => new TextEncoder().encode(text);

  it("rejects malformed UTF-8 without replacement decoding", () => {
    expect(() =>
      parseDecisionBoardJsonBytes(new Uint8Array([0x7b, 0xff, 0x7d])),
    ).toThrow();
  });

  it("rejects duplicate object keys at any nesting depth", () => {
    expect(() =>
      parseDecisionBoardJsonBytes(encode('{"outer":{"key":1,"key":2}}')),
    ).toThrow(/duplicate/i);
  });

  it.each(["[]", "null", '"value"', "{bad}"])(
    "rejects non-object or malformed content %s",
    (text) => {
      expect(() => parseDecisionBoardJsonBytes(encode(text))).toThrow();
    },
  );
});
