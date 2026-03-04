import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  IDEMPOTENCY_KEY_MAX_LENGTH,
  IDEMPOTENCY_KEY_UUID_PATTERN,
} from "@/lib/idempotency-key";

const ADD_BUY_MIGRATION_FILENAME =
  "20260304002000_add_holdings_add_buy_idempotency.sql";

function readAddBuyMigration(): string {
  const migrationPath = path.resolve(
    process.cwd(),
    "..",
    "supabase",
    "migrations",
    ADD_BUY_MIGRATION_FILENAME,
  );
  return fs.readFileSync(migrationPath, "utf8");
}

describe("idempotency key API/DB contract", () => {
  it("keeps UUID pattern aligned with Supabase RPC validation", () => {
    const sql = readAddBuyMigration();
    const patternMatch = sql.match(/v_idempotency_key !~\* '([^']+)'/);
    expect(patternMatch?.[1]).toBe(IDEMPOTENCY_KEY_UUID_PATTERN.source);
  });

  it("keeps max-length aligned with Supabase RPC validation", () => {
    const sql = readAddBuyMigration();
    const lengthMatch = sql.match(/char_length\(v_idempotency_key\) > (\d+)/);
    expect(Number(lengthMatch?.[1])).toBe(IDEMPOTENCY_KEY_MAX_LENGTH);
  });
});
