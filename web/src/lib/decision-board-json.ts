/** Strict JSON byte boundary for Decision Board artifacts. */

const WHITESPACE = /[\u0009\u000a\u000d\u0020]/;
const NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;

class StrictJsonScanner {
  private offset = 0;

  constructor(private readonly text: string) {}

  parse(): unknown {
    this.skipWhitespace();
    this.scanValue();
    this.skipWhitespace();
    if (this.offset !== this.text.length) {
      throw new SyntaxError("unexpected trailing JSON content");
    }
    return JSON.parse(this.text) as unknown;
  }

  private scanValue(): void {
    const token = this.text[this.offset];
    if (token === "{") {
      this.scanObject();
      return;
    }
    if (token === "[") {
      this.scanArray();
      return;
    }
    if (token === '"') {
      this.scanString();
      return;
    }
    for (const literal of ["true", "false", "null"] as const) {
      if (this.text.startsWith(literal, this.offset)) {
        this.offset += literal.length;
        return;
      }
    }
    NUMBER.lastIndex = this.offset;
    const match = NUMBER.exec(this.text);
    if (match) {
      this.offset = NUMBER.lastIndex;
      return;
    }
    throw new SyntaxError("invalid JSON value");
  }

  private scanObject(): void {
    this.offset += 1;
    this.skipWhitespace();
    const keys = new Set<string>();
    if (this.consume("}")) {
      return;
    }
    while (true) {
      if (this.text[this.offset] !== '"') {
        throw new SyntaxError("JSON object key must be a string");
      }
      const key = this.scanString();
      if (keys.has(key)) {
        throw new SyntaxError("duplicate JSON object key");
      }
      keys.add(key);
      this.skipWhitespace();
      this.expect(":");
      this.skipWhitespace();
      this.scanValue();
      this.skipWhitespace();
      if (this.consume("}")) {
        return;
      }
      this.expect(",");
      this.skipWhitespace();
    }
  }

  private scanArray(): void {
    this.offset += 1;
    this.skipWhitespace();
    if (this.consume("]")) {
      return;
    }
    while (true) {
      this.scanValue();
      this.skipWhitespace();
      if (this.consume("]")) {
        return;
      }
      this.expect(",");
      this.skipWhitespace();
    }
  }

  private scanString(): string {
    const start = this.offset;
    this.offset += 1;
    while (this.offset < this.text.length) {
      const code = this.text.charCodeAt(this.offset);
      if (code === 0x22) {
        this.offset += 1;
        return JSON.parse(this.text.slice(start, this.offset)) as string;
      }
      if (code < 0x20) {
        throw new SyntaxError("unescaped control character in JSON string");
      }
      if (code === 0x5c) {
        this.offset += 1;
        const escape = this.text[this.offset];
        if (escape === "u") {
          const hex = this.text.slice(this.offset + 1, this.offset + 5);
          if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
            throw new SyntaxError("invalid JSON unicode escape");
          }
          this.offset += 5;
          continue;
        }
        if (!escape || !'"\\/bfnrt'.includes(escape)) {
          throw new SyntaxError("invalid JSON escape");
        }
      }
      this.offset += 1;
    }
    throw new SyntaxError("unterminated JSON string");
  }

  private skipWhitespace(): void {
    while (WHITESPACE.test(this.text[this.offset] ?? "")) {
      this.offset += 1;
    }
  }

  private consume(token: string): boolean {
    if (this.text[this.offset] !== token) {
      return false;
    }
    this.offset += 1;
    return true;
  }

  private expect(token: string): void {
    if (!this.consume(token)) {
      throw new SyntaxError(`expected JSON token ${token}`);
    }
  }
}

export function parseDecisionBoardJsonBytes(
  bytes: Uint8Array,
): Record<string, unknown> {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  const value = new StrictJsonScanner(text).parse();
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new SyntaxError("Decision Board report must be a JSON object");
  }
  return value as Record<string, unknown>;
}
