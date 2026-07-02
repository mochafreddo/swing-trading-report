# Toss Daily Auto Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local daily Toss holdings auto-sync that applies safe `create`, `update`, and `delete` diffs without a browser session.

**Architecture:** Keep Toss sync orchestration in the web TypeScript runtime because the existing Toss client, Supabase adapter, ticker directory, reconciliation, and replace-all RPC are already there. Extract that orchestration into a shared service used by both the manual UI route and a new local scheduled route. A launchd-friendly shell runner calls the scheduled route with a local bearer token at `08:05 Asia/Seoul`.

**Tech Stack:** Next.js 16 route handlers, React 19 UI, TypeScript, Vitest, Zod, Supabase PostgREST/RPC, Toss Open API, bash, uv-managed Python for shell JSON parsing, pytest for script/plist tests.

## Global Constraints

- Approved spec: `docs/superpowers/specs/2026-06-30-toss-daily-auto-sync-design.md`.
- The user chose Toss as source of truth for automatic `create`, `update`, and `delete`.
- Run once per day at `08:05 Asia/Seoul`.
- Keep Toss account credentials on the local machine; do not make GitHub Actions the primary scheduled path.
- Do not port Toss sync to Python in the first release.
- Do not apply a partial diff when normalization has blocked rows.
- Scheduled auto sync must not automatically wipe non-empty Supabase holdings from an empty Toss snapshot.
- Scheduled route must work without a browser session and must use a dedicated local job token.
- Do not return Toss tokens, Toss account identifiers, or raw upstream Toss payloads.
- `TOSS_SYNC_AUTO_APPLY_ENABLED` defaults off unless set to `1`.
- Existing dirty web changes may already remove `APPLY TOSS HOLDINGS`; Task 1 owns those changes. Do not stage unrelated local changes outside the task files.
- Follow TDD: write the failing test, run it red, implement, run green, then commit.

---

## File Structure

- Modify `web/src/lib/schemas.ts`: remove manual Toss apply confirmation text from the apply schema and add `tossHoldingsScheduledSyncRequestSchema`.
- Modify `web/src/lib/__tests__/schemas.test.ts`: cover confirmation-free apply and scheduled auto-apply schema.
- Modify `web/src/components/holdings/use-toss-holdings-sync.ts`: send apply requests with only `mode` and `diffHash`.
- Modify `web/src/components/holdings/toss-sync-panel.tsx`: remove the confirmation input and call `onApply()` directly.
- Modify `web/src/components/holdings-client.module.css`: remove dead confirmation-input styles.
- Modify `web/src/lib/__tests__/holdings-client-hooks.test.tsx`: cover confirmation-free hook and panel behavior.
- Create `web/src/lib/toss/holdings-sync-service.ts`: shared orchestration for preview, manual apply, and scheduled auto-apply decisions.
- Create `web/src/lib/__tests__/toss-holdings-sync-service.test.ts`: service-level unit coverage for apply, blocked rows, wipe guard, disabled status, and count propagation.
- Modify `web/src/app/api/holdings/toss-sync/route.ts`: delegate to the shared service while preserving current manual API response shape.
- Modify `web/src/app/api/holdings/toss-sync/__tests__/route.test.ts`: keep manual route coverage after service extraction.
- Create `web/src/app/api/holdings/toss-sync/scheduled/route.ts`: local bearer-token scheduled endpoint.
- Create `web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts`: scheduled route auth, local guard, disabled, success, blocked, wipe guard coverage.
- Create `scripts/toss_daily_auto_sync.sh`: non-interactive runner for launchd/manual smoke.
- Create `scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist`: daily `08:05` launchd job.
- Create `tests/test_toss_daily_auto_sync.py`: runner and plist contract tests.
- Modify `docs/api.md`: manual apply payload, scheduled route contract.
- Modify `docs/configuration.md`: scheduled Toss sync env variables.
- Modify `docs/config-reference.md`: scheduled Toss sync env variables.
- Modify `docs/deployment.md`: local daily Toss sync smoke and launchd notes.
- Modify `docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md`: remove stale “confirmation text required” statement.

---

### Task 1: Finish Confirmation-Free Manual Toss Apply Contract

**Files:**
- Modify: `web/src/lib/schemas.ts`
- Modify: `web/src/lib/__tests__/schemas.test.ts`
- Modify: `web/src/components/holdings/use-toss-holdings-sync.ts`
- Modify: `web/src/components/holdings/toss-sync-panel.tsx`
- Modify: `web/src/components/holdings-client.module.css`
- Modify: `web/src/lib/__tests__/holdings-client-hooks.test.tsx`
- Modify: `web/src/app/api/holdings/toss-sync/__tests__/route.test.ts`

**Interfaces:**
- Produces: `requestTossHoldingsApply(diffHash: string, fetcher?: Fetcher): Promise<TossHoldingsDryRunResponse>`
- Produces: `TossSyncPanelProps.onApply: () => void | Promise<void>`
- Produces: `tossHoldingsSyncRequestSchema` apply branch shape `{ mode: "apply"; diffHash: string }`

- [ ] **Step 1: Write/update schema failing tests**

In `web/src/lib/__tests__/schemas.test.ts`, make the Toss schema tests read:

```ts
describe("tossHoldingsSyncRequestSchema", () => {
  it("accepts apply payload with only a reviewed diff hash", () => {
    const parsed = tossHoldingsSyncRequestSchema.parse({
      mode: "apply",
      diffHash:
        "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    });

    expect(parsed).toEqual({
      mode: "apply",
      diffHash:
        "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    });
  });

  it("rejects apply payload with an invalid reviewed diff hash", () => {
    const parsed = tossHoldingsSyncRequestSchema.safeParse({
      mode: "apply",
      diffHash: "not-a-diff-hash",
    });

    expect(parsed.success).toBe(false);
  });
});
```

- [ ] **Step 2: Write/update client failing tests**

In `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, change the hook and panel tests so they call apply without confirmation text:

```ts
it("applies a reviewed Toss dry-run without confirmation text and runs the applied callback", async () => {
  const onApplied = vi.fn().mockResolvedValue(undefined);
  const requestApply = vi.fn().mockResolvedValue({
    mode: "apply",
    diffHash:
      "sha256:2222222222222222222222222222222222222222222222222222222222222222",
    applyBlocked: false,
    summary: TOSS_SUMMARY,
    blockedRows: [],
    changes: { create: [], update: [], delete: [], unchanged: [] },
    targetRows: [],
  });
  const hook = renderHook(() =>
    useTossHoldingsSync({
      requestDryRun: vi.fn().mockResolvedValue({
        mode: "dry-run",
        diffHash:
          "sha256:2222222222222222222222222222222222222222222222222222222222222222",
        applyBlocked: false,
        summary: TOSS_SUMMARY,
        blockedRows: [],
        changes: { create: [], update: [], delete: [], unchanged: [] },
        targetRows: [],
      }),
      requestApply,
      onApplied,
    }),
  );

  await act(async () => {
    await hook.current.runDryRun();
  });
  expect(hook.current.status).toBe("ready");
  expect(hook.current.canApply).toBe(true);

  await act(async () => {
    await hook.current.apply();
  });

  expect(requestApply).toHaveBeenCalledWith(
    "sha256:2222222222222222222222222222222222222222222222222222222222222222",
  );
  expect(onApplied).toHaveBeenCalledTimes(1);
  expect(hook.current.status).toBe("applied");
  expect(hook.current.success).toBe("Applied Toss holdings sync");

  hook.unmount();
});
```

Also update the composition test:

```ts
expect(
  container.querySelector<HTMLInputElement>('input[name="tossConfirmation"]'),
).toBeNull();

const applyButton = findButton(container, "Apply Toss Snapshot");
expect(applyButton.disabled).toBe(false);

await act(async () => {
  applyButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
});

expect(fetchMock).toHaveBeenCalledWith(
  "/api/holdings/toss-sync",
  expect.objectContaining({
    method: "POST",
    body: JSON.stringify({
      mode: "apply",
      diffHash:
        "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    }),
  }),
);
```

- [ ] **Step 3: Write/update route failing tests**

In `web/src/app/api/holdings/toss-sync/__tests__/route.test.ts`, remove `confirmationText` from all apply request bodies and rename the old rejection test:

```ts
it("applies Toss holdings without confirmation text before writing Supabase", async () => {
  vi.mocked(fetchAllHoldings).mockResolvedValue([]);
  vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValue([
    {
      symbol: "005930",
      marketCountry: "KR",
      currency: "KRW",
      quantity: "1",
      averagePurchasePrice: "70000",
    },
  ]);

  const dryRunResponse = await POST(makePostRequest({ mode: "dry-run" }));
  const dryRunPayload = (await dryRunResponse.json()) as { diffHash: string };

  const applyResponse = await POST(
    makePostRequest({ mode: "apply", diffHash: dryRunPayload.diffHash }),
  );
  const payload = (await applyResponse.json()) as { mode: string };

  expect(applyResponse.status).toBe(200);
  expect(payload.mode).toBe("apply");
  expect(vi.mocked(replaceAllHoldings)).toHaveBeenCalledWith([
    expect.objectContaining({ ticker: "005930" }),
  ]);
});
```

- [ ] **Step 4: Run tests to verify they fail on current HEAD**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/holdings/toss-sync/__tests__/route.test.ts
```

Expected before implementation: failures mentioning `confirmationText`, `tossConfirmation`, or a request body containing the confirmation text.

- [ ] **Step 5: Implement schema contract**

In `web/src/lib/schemas.ts`, make the apply branch:

```ts
export const tossHoldingsSyncRequestSchema = z.union([
  z
    .object({
      mode: z.literal("apply"),
      diffHash: z.string().regex(/^sha256:[a-f0-9]{64}$/),
    })
    .strict(),
  z
    .object({
      mode: z.literal("dry-run").default("dry-run"),
    })
    .strict(),
]);
```

- [ ] **Step 6: Implement client apply contract**

In `web/src/components/holdings/use-toss-holdings-sync.ts`, change the apply request:

```ts
export async function requestTossHoldingsApply(
  diffHash: string,
  fetcher: Fetcher = fetch,
): Promise<TossHoldingsDryRunResponse> {
  const response = await fetcher("/api/holdings/toss-sync", {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      mode: "apply",
      diffHash,
    }),
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    throw new TossHoldingsSyncRequestError(
      readApiError(payload) || "Failed to apply Toss holdings sync",
      response.status,
    );
  }
  return payload as TossHoldingsDryRunResponse;
}
```

Update the hook options and callback:

```ts
interface UseTossHoldingsSyncOptions {
  requestDryRun?: () => Promise<TossHoldingsDryRunResponse>;
  requestApply?: (diffHash: string) => Promise<TossHoldingsDryRunResponse>;
  onApplied?: () => void | Promise<void>;
}

const apply = useCallback(async () => {
  if (!dryRun?.diffHash) {
    setError("Run a Toss dry-run before applying.");
    return;
  }
  if (dryRun.applyBlocked) {
    setError("Resolve blocked Toss rows before applying.");
    return;
  }

  setStatus("applying");
  setError(null);
  setSuccess(null);
  try {
    const response = await requestApply(dryRun.diffHash);
    setDryRun(response);
    setStatus("applied");
    setSuccess("Applied Toss holdings sync");
    await onApplied?.();
  } catch (applyError) {
    setStatus("error");
    setError(
      applyError instanceof Error
        ? applyError.message
        : "Failed to apply Toss holdings sync",
    );
  }
}, [dryRun, onApplied, requestApply]);
```

- [ ] **Step 7: Implement panel UI**

In `web/src/components/holdings/toss-sync-panel.tsx`:

```ts
interface TossSyncPanelProps {
  status: TossSyncStatus;
  statusMessage: string;
  loading: boolean;
  applying: boolean;
  error: string | null;
  success: string | null;
  summary: TossHoldingsDryRunResponse["summary"] | null;
  changes: TossHoldingsDryRunResponse["changes"] | null;
  blockedRows: TossHoldingsBlockedRow[];
  canRunDryRun: boolean;
  canApply: boolean;
  onRunDryRun: () => void | Promise<void>;
  onApply: () => void | Promise<void>;
}
```

Remove `confirmationText` state and render the apply guard as:

```tsx
{canApply && (
  <div className={styles.applyGuard}>
    <button
      type="button"
      className={styles.dangerButton}
      onClick={() => void onApply()}
      disabled={applying || loading}
    >
      {applying ? "Applying..." : "Apply Toss Snapshot"}
    </button>
  </div>
)}
```

Update delete copy:

```tsx
<p className="subtle">
  Missing from the Toss snapshot. Applying the reviewed diff removes it.
</p>
```

In `web/src/components/holdings-client.module.css`, remove `.applyConfirmLabel`, `.applyConfirmLabel input`, and `.applyConfirmLabel input:focus-visible`.

- [ ] **Step 8: Run Task 1 tests green**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/holdings/toss-sync/__tests__/route.test.ts
pnpm --dir web run format:check
pnpm --dir web run lint
pnpm --dir web run typecheck
```

Expected: all commands exit 0.

- [ ] **Step 9: Commit Task 1**

```bash
git add web/src/lib/schemas.ts web/src/lib/__tests__/schemas.test.ts web/src/components/holdings/use-toss-holdings-sync.ts web/src/components/holdings/toss-sync-panel.tsx web/src/components/holdings-client.module.css web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/holdings/toss-sync/__tests__/route.test.ts
git commit -m "feat(toss): 확인 문구 없이 보유 싱크 적용" -m "토스 보유목록 apply 계약을 diffHash 기반으로 단순화한다."
```

---

### Task 2: Extract Shared Toss Holdings Sync Service

**Files:**
- Create: `web/src/lib/toss/holdings-sync-service.ts`
- Create: `web/src/lib/__tests__/toss-holdings-sync-service.test.ts`
- Modify: `web/src/app/api/holdings/toss-sync/route.ts`
- Modify: `web/src/app/api/holdings/toss-sync/__tests__/route.test.ts`

**Interfaces:**
- Consumes: `buildTossHoldingsDryRun(input)`, `buildTossHoldingsDiffHash(dryRun)`
- Consumes: `fetchAllHoldings(): Promise<HoldingRecord[]>`
- Consumes: `fetchDefaultTossHoldingsItems(): Promise<TossHoldingsItem[]>`
- Consumes: `listTickerDirectoryExactBaseCandidates(symbols): Promise<TickerDirectoryExactBaseResponse>`
- Consumes: `replaceAllHoldings(rows): Promise<ReplaceAllHoldingsResult>`
- Produces: `buildTossHoldingsSyncPreview(deps?): Promise<TossHoldingsSyncPreview>`
- Produces: `applyTossHoldingsSyncPreview(preview, deps?): Promise<TossHoldingsSyncResponsePayload>`
- Produces: `runScheduledTossAutoApply(options, deps?): Promise<ScheduledTossAutoSyncResponse>`

- [ ] **Step 1: Write service failing tests**

Create `web/src/lib/__tests__/toss-holdings-sync-service.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import {
  applyTossHoldingsSyncPreview,
  buildTossHoldingsSyncPreview,
  runScheduledTossAutoApply,
  type TossHoldingsSyncDependencies,
} from "@/lib/toss/holdings-sync-service";
import type { HoldingRecord } from "@/lib/types";

function holding(overrides: Partial<HoldingRecord> & { ticker: string }) {
  return {
    ticker: overrides.ticker,
    quantity: overrides.quantity ?? 1,
    entry_price: overrides.entry_price ?? 100,
    entry_currency: overrides.entry_currency ?? null,
    entry_date: overrides.entry_date ?? null,
    strategy: overrides.strategy ?? null,
    entry_pattern: overrides.entry_pattern ?? null,
    notes: overrides.notes ?? null,
    tags: overrides.tags ?? [],
    stop_override: overrides.stop_override ?? null,
    target_override: overrides.target_override ?? null,
    created_at: overrides.created_at ?? "2026-06-30T00:00:00Z",
    updated_at: overrides.updated_at ?? "2026-06-30T00:00:00Z",
  } satisfies HoldingRecord;
}

function deps(
  overrides: Partial<TossHoldingsSyncDependencies> = {},
): TossHoldingsSyncDependencies {
  return {
    fetchAllHoldings: vi.fn(async () => []),
    fetchTossHoldingsItems: vi.fn(async () => []),
    listTickerDirectoryExactBaseCandidates: vi.fn(async () => ({
      candidates: [],
      directory: { builtAtMs: 0, sourceReports: 0, usableForAutoMapping: false },
    })),
    replaceAllHoldings: vi.fn(async () => ({
      insertedCount: 0,
      updatedCount: 0,
      deletedCount: 0,
      unchangedCount: 0,
    })),
    ...overrides,
  };
}

describe("toss holdings sync service", () => {
  it("builds a preview and applies create update delete changes", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => [
        holding({ ticker: "AAPL.NAS", quantity: 1, entry_price: 190, entry_currency: "USD" }),
        holding({ ticker: "TSLA.NAS", quantity: 1, entry_price: 200, entry_currency: "USD" }),
      ]),
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "AAPL",
          marketCountry: "US",
          currency: "USD",
          quantity: "2",
          averagePurchasePrice: "188",
        },
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "1",
          averagePurchasePrice: "70000",
        },
      ]),
      replaceAllHoldings: vi.fn(async () => ({
        insertedCount: 1,
        updatedCount: 1,
        deletedCount: 1,
        unchangedCount: 0,
      })),
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);
    const payload = await applyTossHoldingsSyncPreview(preview, testDeps);

    expect(payload.mode).toBe("apply");
    expect(payload.summary).toEqual(
      expect.objectContaining({ createCount: 1, updateCount: 1, deleteCount: 1 }),
    );
    expect(testDeps.replaceAllHoldings).toHaveBeenCalledWith([
      expect.objectContaining({ ticker: "005930" }),
      expect.objectContaining({ ticker: "AAPL.NAS", quantity: 2 }),
    ]);
  });

  it("scheduled auto apply returns disabled without fetching when the flag is off", async () => {
    const testDeps = deps();

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: false },
      testDeps,
    );

    expect(result.status).toBe("disabled");
    expect(testDeps.fetchAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
  });

  it("scheduled auto apply skips blocked previews without writing", async () => {
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "MSFT",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ]),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("blocked");
    expect(result.applyBlocked).toBe(true);
    expect(result.blockedRows).toEqual([
      expect.objectContaining({ reason: "ticker_exchange_unresolved" }),
    ]);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
  });

  it("scheduled auto apply blocks an empty Toss snapshot from wiping active holdings", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => [
        holding({ ticker: "AAPL.NAS", quantity: 1, entry_price: 190 }),
      ]),
      fetchTossHoldingsItems: vi.fn(async () => []),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("wipe_guard_blocked");
    expect(result.summary.deleteCount).toBe(1);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
  });

  it("scheduled auto apply treats empty Toss and empty active holdings as unchanged", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => []),
      fetchTossHoldingsItems: vi.fn(async () => []),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("unchanged");
    expect(result.summary.incomingCount).toBe(0);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run service tests red**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/toss-holdings-sync-service.test.ts
```

Expected: FAIL because `@/lib/toss/holdings-sync-service` does not exist.

- [ ] **Step 3: Implement shared service**

Create `web/src/lib/toss/holdings-sync-service.ts`:

```ts
import "server-only";

import { fetchAllHoldings, replaceAllHoldings } from "@/lib/supabase-admin";
import {
  listTickerDirectoryExactBaseCandidates,
  type TickerDirectoryExactBaseResponse,
} from "@/lib/ticker-directory";
import { fetchDefaultTossHoldingsItems } from "@/lib/toss/client";
import {
  buildTossHoldingsDiffHash,
  buildTossHoldingsDryRun,
  type TossHoldingsDryRunResult,
  type TossHoldingsItem,
  type TossTickerDirectoryCandidate,
} from "@/lib/toss/holdings-sync";
import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingsYamlImportSummary,
} from "@/lib/types";
import type { ReplaceAllHoldingsResult } from "@/lib/supabase/holdings";

export type TossHoldingsSyncMode = "dry-run" | "apply";

export type ScheduledTossAutoSyncStatus =
  | "applied"
  | "unchanged"
  | "disabled"
  | "blocked"
  | "wipe_guard_blocked"
  | "error";

export interface TossHoldingsSyncResponsePayload {
  mode: TossHoldingsSyncMode;
  diffHash: string;
  applyBlocked: boolean;
  summary: HoldingsYamlImportSummary;
  changes: TossHoldingsDryRunResult["reconciliation"]["changes"];
  blockedRows: TossHoldingsDryRunResult["blockedRows"];
  targetRows: HoldingReplaceSnapshot[];
}

export interface ScheduledTossAutoSyncResponse
  extends Omit<TossHoldingsSyncResponsePayload, "mode"> {
  mode: "auto-apply";
  status: ScheduledTossAutoSyncStatus;
}

export interface TossHoldingsSyncPreview {
  currentHoldings: HoldingRecord[];
  tossItems: TossHoldingsItem[];
  tickerDirectoryCandidates: TossTickerDirectoryCandidate[];
  dryRun: TossHoldingsDryRunResult;
  diffHash: string;
  hasChanges: boolean;
  hasActiveCurrentHoldings: boolean;
  payload: TossHoldingsSyncResponsePayload;
}

export interface TossHoldingsSyncDependencies {
  fetchAllHoldings: () => Promise<HoldingRecord[]>;
  fetchTossHoldingsItems: () => Promise<TossHoldingsItem[]>;
  listTickerDirectoryExactBaseCandidates: (
    symbols: readonly string[],
  ) => Promise<TickerDirectoryExactBaseResponse>;
  replaceAllHoldings: (
    rows: HoldingReplaceSnapshot[],
  ) => Promise<ReplaceAllHoldingsResult>;
}

export const defaultTossHoldingsSyncDependencies: TossHoldingsSyncDependencies =
  {
    fetchAllHoldings,
    fetchTossHoldingsItems: fetchDefaultTossHoldingsItems,
    listTickerDirectoryExactBaseCandidates,
    replaceAllHoldings,
  };

function hasChanges(summary: HoldingsYamlImportSummary): boolean {
  return (
    summary.createCount > 0 ||
    summary.updateCount > 0 ||
    summary.deleteCount > 0
  );
}

function hasActiveQuantity(value: unknown): boolean {
  if (typeof value === "boolean" || value == null) {
    return false;
  }
  if (typeof value !== "number" && typeof value !== "string") {
    return false;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0;
}

function hasActiveHoldings(rows: readonly HoldingRecord[]): boolean {
  return rows.some((row) => hasActiveQuantity(row.quantity));
}

function buildResponsePayload(
  mode: TossHoldingsSyncMode,
  dryRun: TossHoldingsDryRunResult,
  diffHash: string,
): TossHoldingsSyncResponsePayload {
  return {
    mode,
    diffHash,
    applyBlocked: dryRun.applyBlocked,
    summary: dryRun.reconciliation.summary,
    changes: dryRun.reconciliation.changes,
    blockedRows: dryRun.blockedRows,
    targetRows: dryRun.targetRows,
  };
}

async function fetchTossTickerDirectoryCandidates(
  items: readonly TossHoldingsItem[],
  deps: Pick<TossHoldingsSyncDependencies, "listTickerDirectoryExactBaseCandidates">,
): Promise<TossTickerDirectoryCandidate[]> {
  const usSymbols = Array.from(
    new Set(
      items
        .filter((item) => item.marketCountry === "US")
        .map((item) => item.symbol.trim())
        .filter(Boolean),
    ),
  ).sort((left, right) => left.localeCompare(right));
  if (usSymbols.length <= 0) {
    return [];
  }

  try {
    const result = await deps.listTickerDirectoryExactBaseCandidates(usSymbols);
    return result.candidates.map((row) => ({ ticker: row.ticker }));
  } catch {
    return [];
  }
}

export async function buildTossHoldingsSyncPreview(
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
): Promise<TossHoldingsSyncPreview> {
  const [currentHoldings, tossItems] = await Promise.all([
    deps.fetchAllHoldings(),
    deps.fetchTossHoldingsItems(),
  ]);
  const tickerDirectoryCandidates = await fetchTossTickerDirectoryCandidates(
    tossItems,
    deps,
  );
  const dryRun = buildTossHoldingsDryRun({
    currentHoldings,
    items: tossItems,
    tickerDirectoryCandidates,
  });
  const diffHash = buildTossHoldingsDiffHash(dryRun);
  const payload = buildResponsePayload("dry-run", dryRun, diffHash);

  return {
    currentHoldings,
    tossItems,
    tickerDirectoryCandidates,
    dryRun,
    diffHash,
    hasChanges: hasChanges(dryRun.reconciliation.summary),
    hasActiveCurrentHoldings: hasActiveHoldings(currentHoldings),
    payload,
  };
}

export async function applyTossHoldingsSyncPreview(
  preview: TossHoldingsSyncPreview,
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
): Promise<TossHoldingsSyncResponsePayload> {
  const responsePayload = buildResponsePayload(
    "apply",
    preview.dryRun,
    preview.diffHash,
  );
  if (preview.hasChanges) {
    const result = await deps.replaceAllHoldings(preview.dryRun.targetRows);
    responsePayload.summary = {
      ...responsePayload.summary,
      createCount: result.insertedCount,
      updateCount: result.updatedCount,
      deleteCount: result.deletedCount,
      unchangedCount: result.unchangedCount,
    };
  }
  return responsePayload;
}

export async function runScheduledTossAutoApply(
  options: { autoApplyEnabled: boolean },
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
): Promise<ScheduledTossAutoSyncResponse> {
  if (!options.autoApplyEnabled) {
    return {
      mode: "auto-apply",
      status: "disabled",
      diffHash: "",
      applyBlocked: false,
      summary: {
        incomingCount: 0,
        createCount: 0,
        updateCount: 0,
        deleteCount: 0,
        unchangedCount: 0,
        createTickers: [],
        updateTickers: [],
        deleteTickers: [],
      },
      changes: { create: [], update: [], delete: [], unchanged: [] },
      blockedRows: [],
      targetRows: [],
    };
  }

  const preview = await buildTossHoldingsSyncPreview(deps);
  const base = {
    mode: "auto-apply" as const,
    diffHash: preview.diffHash,
    applyBlocked: preview.dryRun.applyBlocked,
    summary: preview.dryRun.reconciliation.summary,
    changes: preview.dryRun.reconciliation.changes,
    blockedRows: preview.dryRun.blockedRows,
    targetRows: preview.dryRun.targetRows,
  };

  if (preview.dryRun.applyBlocked) {
    return { ...base, status: "blocked" };
  }
  if (preview.tossItems.length === 0 && preview.hasActiveCurrentHoldings) {
    return { ...base, status: "wipe_guard_blocked" };
  }
  if (!preview.hasChanges) {
    return { ...base, status: "unchanged" };
  }

  const applied = await applyTossHoldingsSyncPreview(preview, deps);
  return {
    ...applied,
    mode: "auto-apply",
    status: "applied",
  };
}
```

- [ ] **Step 4: Refactor manual route to use the service**

In `web/src/app/api/holdings/toss-sync/route.ts`, remove route-local `hasChanges`, `buildResponsePayload`, and `fetchTossTickerDirectoryCandidates`. Import:

```ts
import {
  applyTossHoldingsSyncPreview,
  buildTossHoldingsSyncPreview,
} from "@/lib/toss/holdings-sync-service";
```

Inside `POST`, replace the fetch/build block with:

```ts
const preview = await buildTossHoldingsSyncPreview();
const dryRun = preview.dryRun;
const diffHash = preview.diffHash;
```

For apply success:

```ts
const responsePayload = await applyTossHoldingsSyncPreview(preview);
```

For dry-run success:

```ts
const responsePayload = preview.payload;
```

Keep existing conflict responses and logging fields.

- [ ] **Step 5: Run Task 2 tests green**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/toss-holdings-sync-service.test.ts web/src/app/api/holdings/toss-sync/__tests__/route.test.ts
pnpm --dir web run typecheck
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit Task 2**

```bash
git add web/src/lib/toss/holdings-sync-service.ts web/src/lib/__tests__/toss-holdings-sync-service.test.ts web/src/app/api/holdings/toss-sync/route.ts web/src/app/api/holdings/toss-sync/__tests__/route.test.ts
git commit -m "refactor(toss): 보유 싱크 서비스를 분리" -m "수동 라우트와 예약 작업이 같은 토스 보유목록 조정 로직을 재사용하도록 정리한다."
```

---

### Task 3: Add Scheduled Auto-Sync Endpoint

**Files:**
- Modify: `web/src/lib/schemas.ts`
- Modify: `web/src/lib/__tests__/schemas.test.ts`
- Create: `web/src/app/api/holdings/toss-sync/scheduled/route.ts`
- Create: `web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts`

**Interfaces:**
- Consumes: `runScheduledTossAutoApply({ autoApplyEnabled }, deps?)`
- Produces: `tossHoldingsScheduledSyncRequestSchema`
- Produces: `POST /api/holdings/toss-sync/scheduled`

- [ ] **Step 1: Write schema failing tests**

Add to `web/src/lib/__tests__/schemas.test.ts` imports:

```ts
import {
  tossHoldingsScheduledSyncRequestSchema,
} from "@/lib/schemas";
```

If the file already imports from `@/lib/schemas`, include `tossHoldingsScheduledSyncRequestSchema` in that existing import. Add tests:

```ts
describe("tossHoldingsScheduledSyncRequestSchema", () => {
  it("accepts scheduled auto-apply payload", () => {
    expect(
      tossHoldingsScheduledSyncRequestSchema.parse({ mode: "auto-apply" }),
    ).toEqual({ mode: "auto-apply" });
  });

  it("rejects unknown scheduled payload keys", () => {
    const parsed = tossHoldingsScheduledSyncRequestSchema.safeParse({
      mode: "auto-apply",
      diffHash: "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    });

    expect(parsed.success).toBe(false);
  });
});
```

- [ ] **Step 2: Write scheduled route failing tests**

Create `web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/local-request-guard", () => {
  class LocalRequestGuardError extends Error {
    status: number;

    constructor(message = "Local only", status = 403) {
      super(message);
      this.status = status;
    }
  }

  return {
    LocalRequestGuardError,
    assertLocalRequest: vi.fn(() => undefined),
  };
});

vi.mock("@/lib/toss/holdings-sync-service", () => ({
  runScheduledTossAutoApply: vi.fn(async () => ({
    mode: "auto-apply",
    status: "unchanged",
    diffHash:
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    applyBlocked: false,
    summary: {
      incomingCount: 1,
      createCount: 0,
      updateCount: 0,
      deleteCount: 0,
      unchangedCount: 1,
      createTickers: [],
      updateTickers: [],
      deleteTickers: [],
    },
    changes: { create: [], update: [], delete: [], unchanged: [] },
    blockedRows: [],
    targetRows: [],
  })),
}));

import { POST } from "@/app/api/holdings/toss-sync/scheduled/route";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { runScheduledTossAutoApply } from "@/lib/toss/holdings-sync-service";

const ORIGINAL_ENV = { ...process.env };

function makePostRequest(
  body: object,
  headers: Record<string, string> = {},
): NextRequest {
  return new NextRequest(
    "http://localhost:55300/api/holdings/toss-sync/scheduled",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://localhost:55300",
        host: "localhost:55300",
        ...headers,
      },
      body: JSON.stringify(body),
    },
  );
}

describe("/api/holdings/toss-sync/scheduled route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env = {
      ...ORIGINAL_ENV,
      TOSS_SYNC_JOB_TOKEN: "job-token",
      TOSS_SYNC_AUTO_APPLY_ENABLED: "1",
    };
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("rejects missing bearer token", async () => {
    const response = await POST(makePostRequest({ mode: "auto-apply" }));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(401);
    expect(payload.error).toBe("Unauthorized Toss sync job");
    expect(runScheduledTossAutoApply).not.toHaveBeenCalled();
  });

  it("rejects invalid bearer token", async () => {
    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer wrong-token" },
      ),
    );

    expect(response.status).toBe(401);
    expect(runScheduledTossAutoApply).not.toHaveBeenCalled();
  });

  it("rejects non-local requests before running sync", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
    expect(runScheduledTossAutoApply).not.toHaveBeenCalled();
  });

  it("passes disabled flag through when auto apply is not enabled", async () => {
    process.env.TOSS_SYNC_AUTO_APPLY_ENABLED = "0";

    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );

    expect(response.status).toBe(200);
    expect(runScheduledTossAutoApply).toHaveBeenCalledWith({
      autoApplyEnabled: false,
    });
  });

  it("returns bounded auto-sync result for valid local job requests", async () => {
    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );
    const payload = (await response.json()) as {
      status: string;
      diffHash: string;
      accessToken?: string;
      account?: string;
    };

    expect(response.status).toBe(200);
    expect(payload.status).toBe("unchanged");
    expect(payload.diffHash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(payload).not.toHaveProperty("accessToken");
    expect(payload).not.toHaveProperty("account");
    expect(runScheduledTossAutoApply).toHaveBeenCalledWith({
      autoApplyEnabled: true,
    });
  });
});
```

- [ ] **Step 3: Run scheduled route tests red**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts
```

Expected: FAIL because scheduled schema and route do not exist.

- [ ] **Step 4: Implement scheduled schema**

In `web/src/lib/schemas.ts`:

```ts
export const tossHoldingsScheduledSyncRequestSchema = z
  .object({
    mode: z.literal("auto-apply"),
  })
  .strict();
```

- [ ] **Step 5: Implement scheduled route**

Create `web/src/app/api/holdings/toss-sync/scheduled/route.ts`:

```ts
import { NextRequest, NextResponse } from "next/server";

import {
  elapsedMs,
  getApiRequestId,
  logApiError,
  logApiInfo,
  logApiWarn,
  withApiRequestId,
} from "@/lib/api-request-log";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { parseJsonBody } from "@/lib/parse-json-body";
import { tossHoldingsScheduledSyncRequestSchema } from "@/lib/schemas";
import { runScheduledTossAutoApply } from "@/lib/toss/holdings-sync-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/holdings/toss-sync/scheduled";

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) {
    return false;
  }
  let result = 0;
  for (let index = 0; index < left.length; index += 1) {
    result |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return result === 0;
}

function readBearerToken(request: NextRequest): string | null {
  const header = request.headers.get("authorization");
  const match = header?.match(/^Bearer\s+(.+)$/i);
  const token = match?.[1]?.trim();
  return token || null;
}

function requireScheduledJobToken(request: NextRequest): NextResponse | null {
  const expected = process.env.TOSS_SYNC_JOB_TOKEN?.trim() ?? "";
  const actual = readBearerToken(request);
  if (!expected || !actual || !constantTimeEqual(actual, expected)) {
    return NextResponse.json(
      { error: "Unauthorized Toss sync job" },
      { status: 401 },
    );
  }
  return null;
}

function localGuardResponse(error: unknown): NextResponse {
  if (error instanceof LocalRequestGuardError) {
    return NextResponse.json({ error: error.message }, { status: error.status });
  }
  return NextResponse.json({ error: "Local request guard failed" }, { status: 403 });
}

export async function POST(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  try {
    assertLocalRequest(request);
  } catch (error) {
    logApiWarn({
      event: "web_api_request_rejected",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status: "failed",
      status_code: error instanceof LocalRequestGuardError ? error.status : 403,
      reason: "local_request_guard",
      duration_ms: elapsedMs(startedAtMs),
    });
    return withApiRequestId(localGuardResponse(error), requestId);
  }

  const tokenError = requireScheduledJobToken(request);
  if (tokenError) {
    logApiWarn({
      event: "web_api_request_rejected",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status: "failed",
      status_code: 401,
      reason: "job_token",
      duration_ms: elapsedMs(startedAtMs),
    });
    return withApiRequestId(tokenError, requestId);
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    return withApiRequestId(body.response, requestId);
  }

  const parsed = tossHoldingsScheduledSyncRequestSchema.safeParse(body.payload);
  if (!parsed.success) {
    return withApiRequestId(
      NextResponse.json(
        {
          error: "Invalid scheduled Toss holdings sync payload",
          details: parsed.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const result = await runScheduledTossAutoApply({
      autoApplyEnabled: process.env.TOSS_SYNC_AUTO_APPLY_ENABLED === "1",
    });
    const response = NextResponse.json(result);
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status: result.status === "applied" || result.status === "unchanged" ? "success" : "skipped",
      status_code: 200,
      dependency: "toss,supabase",
      duration_ms: elapsedMs(startedAtMs),
      mode: result.mode,
      sync_status: result.status,
      blocked_count: result.blockedRows.length,
      create_count: result.summary.createCount,
      update_count: result.summary.updateCount,
      delete_count: result.summary.deleteCount,
      unchanged_count: result.summary.unchangedCount,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status: "failed",
      status_code: 500,
      duration_ms: elapsedMs(startedAtMs),
      retryable: true,
    });
    return withApiRequestId(
      NextResponse.json({ error: "Scheduled Toss holdings sync failed" }, { status: 500 }),
      requestId,
    );
  }
}
```

- [ ] **Step 6: Run Task 3 tests green**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts
pnpm --dir web run lint
pnpm --dir web run typecheck
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit Task 3**

```bash
git add web/src/lib/schemas.ts web/src/lib/__tests__/schemas.test.ts web/src/app/api/holdings/toss-sync/scheduled/route.ts web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts
git commit -m "feat(toss): 예약 보유 싱크 엔드포인트 추가" -m "로컬 job token으로 보호되는 토스 일일 자동 적용 API를 추가한다."
```

---

### Task 4: Add Local Runner and Launchd Schedule

**Files:**
- Create: `scripts/toss_daily_auto_sync.sh`
- Create: `scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist`
- Create: `tests/test_toss_daily_auto_sync.py`

**Interfaces:**
- Consumes: `POST /api/holdings/toss-sync/scheduled`
- Consumes env: `TOSS_SYNC_JOB_TOKEN`, `WEB_HOST_PORT`, optional `TOSS_SYNC_ENV_FILE`
- Produces executable script `scripts/toss_daily_auto_sync.sh`
- Produces launchd plist scheduled for local `08:05`

- [ ] **Step 1: Write runner/plist failing tests**

Create `tests/test_toss_daily_auto_sync.py`:

```python
from __future__ import annotations

import json
import os
import plistlib
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _run_runner(
    tmp_path: Path,
    *,
    curl_script: str,
    uv_script: str | None = None,
    env_file_text: str = "TOSS_SYNC_JOB_TOKEN=test-token\n",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env_file = tmp_path / ".env.scheduler.local"
    env_file.write_text(env_file_text, encoding="utf-8")
    _write_executable(bin_dir / "curl", curl_script)
    _write_executable(
        bin_dir / "uv",
        uv_script
        or (
            "#!/usr/bin/env bash\n"
            "shift 2\n"
            "script=''\n"
            "while IFS= read -r line; do script+=\"$line\"$'\\n'; done\n"
            "python3 - \"$@\" <<< \"$script\"\n"
        ),
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "TOSS_SYNC_ENV_FILE": str(env_file),
        "WEB_HOST_PORT": "55300",
        **(extra_env or {}),
    }
    return subprocess.run(
        [str(REPO_ROOT / "scripts/toss_daily_auto_sync.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _curl_response(payload: dict[str, object], recorder: Path) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" > {shlex.quote(recorder.as_posix())}\n"
        f"cat <<'JSON'\n{json.dumps(payload)}\nJSON\n"
    )


def test_toss_daily_auto_sync_runner_requires_job_token(tmp_path: Path) -> None:
    result = _run_runner(
        tmp_path,
        curl_script="#!/usr/bin/env bash\nexit 99\n",
        env_file_text="",
    )

    assert result.returncode != 0
    assert "TOSS_SYNC_JOB_TOKEN must be set" in result.stderr


def test_toss_daily_auto_sync_runner_posts_local_origin_and_token(
    tmp_path: Path,
) -> None:
    recorder = tmp_path / "curl.args"
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "applied",
                "summary": {
                    "incomingCount": 2,
                    "createCount": 0,
                    "updateCount": 1,
                    "deleteCount": 1,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            recorder,
        ),
    )

    assert result.returncode == 0
    args = recorder.read_text(encoding="utf-8")
    assert "http://127.0.0.1:55300/api/holdings/toss-sync/scheduled" in args
    assert "Authorization: Bearer test-token" in args
    assert "Origin: http://127.0.0.1:55300" in args
    assert '"mode":"auto-apply"' in args
    assert "status=applied" in result.stdout
    assert "test-token" not in result.stdout


def test_toss_daily_auto_sync_runner_exits_nonzero_for_blocked(
    tmp_path: Path,
) -> None:
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "wipe_guard_blocked",
                "summary": {
                    "incomingCount": 0,
                    "createCount": 0,
                    "updateCount": 0,
                    "deleteCount": 2,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            tmp_path / "curl.args",
        ),
    )

    assert result.returncode != 0
    assert "status=wipe_guard_blocked" in result.stdout


def test_toss_daily_auto_sync_launchd_plist_runs_at_0805() -> None:
    plist_path = REPO_ROOT / "scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist"
    payload = plistlib.loads(plist_path.read_bytes())

    assert payload["Label"] == "com.mochafreddo.sab.toss-daily-auto-sync"
    assert payload["ProgramArguments"][0].endswith("scripts/toss_daily_auto_sync.sh")
    interval = payload["StartCalendarInterval"]
    assert interval == {"Hour": 8, "Minute": 5}
```

- [ ] **Step 2: Run runner tests red**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_toss_daily_auto_sync.py -q
```

Expected: FAIL because the script and plist do not exist.

- [ ] **Step 3: Implement runner script**

Create `scripts/toss_daily_auto_sync.sh` and make it executable:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${TOSS_SYNC_ENV_FILE:-${repo_root}/.env.scheduler.local}"
web_host_port="${WEB_HOST_PORT:-55300}"
base_url="http://127.0.0.1:${web_host_port}"
endpoint="${base_url}/api/holdings/toss-sync/scheduled"

load_env_file() {
  local file_path="$1"
  if [[ ! -f "${file_path}" ]]; then
    return 0
  fi
  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    local line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    if [[ -z "${line}" || "${line}" == \#* ]]; then
      continue
    fi
    if [[ "${line}" == export[[:space:]]* ]]; then
      line="${line#export }"
    fi
    if [[ "${line}" != *=* ]]; then
      continue
    fi
    local key="${line%%=*}"
    local value="${line#*=}"
    key="${key//[[:space:]]/}"
    if [[ ! "${key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      continue
    fi
    value="${value%%[[:space:]]#*}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    if [[ -z "${!key+x}" ]]; then
      export "${key}=${value}"
    fi
  done < "${file_path}"
}

load_env_file "${env_file}"

if [[ -z "${TOSS_SYNC_JOB_TOKEN:-}" ]]; then
  printf '%s\n' "TOSS_SYNC_JOB_TOKEN must be set" >&2
  exit 2
fi

response_file="$(mktemp "${TMPDIR:-/tmp}/toss-auto-sync.XXXXXX.json")"
trap 'rm -f "${response_file}"' EXIT

curl -fsS \
  -X POST "${endpoint}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Origin: ${base_url}" \
  -H "Authorization: Bearer ${TOSS_SYNC_JOB_TOKEN}" \
  --data '{"mode":"auto-apply"}' \
  > "${response_file}"

set +e
status="$(
  uv run python - "${response_file}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
status = str(payload.get("status") or "error")
summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
blocked = payload.get("blockedRows") if isinstance(payload.get("blockedRows"), list) else []
print(
    "status={status} incoming={incoming} create={create} update={update} "
    "delete={delete} unchanged={unchanged} blocked={blocked}".format(
        status=status,
        incoming=summary.get("incomingCount", 0),
        create=summary.get("createCount", 0),
        update=summary.get("updateCount", 0),
        delete=summary.get("deleteCount", 0),
        unchanged=summary.get("unchangedCount", 0),
        blocked=len(blocked),
    )
)
raise SystemExit(0 if status in {"applied", "unchanged"} else 1)
PY
)"
parse_status=$?
set -e
printf '%s\n' "${status}"
exit "${parse_status}"
```

Run:

```bash
chmod +x scripts/toss_daily_auto_sync.sh
```

- [ ] **Step 4: Implement launchd plist**

Create `scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.mochafreddo.sab.toss-daily-auto-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/mochafreddo/GitHub/swing-trading-report/scripts/toss_daily_auto_sync.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>5</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/mochafreddo/GitHub/swing-trading-report/logs/launchd/toss-daily-auto-sync.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/mochafreddo/GitHub/swing-trading-report/logs/launchd/toss-daily-auto-sync.err.log</string>
</dict>
</plist>
```

- [ ] **Step 5: Run runner tests green**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_toss_daily_auto_sync.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/toss_daily_auto_sync.sh scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist tests/test_toss_daily_auto_sync.py
git commit -m "feat(toss): 일일 자동 싱크 실행기 추가" -m "로컬 launchd에서 호출할 토스 보유목록 자동 싱크 스크립트와 스케줄 계약을 추가한다."
```

---

### Task 5: Update Documentation and Stale Spec Text

**Files:**
- Modify: `docs/api.md`
- Modify: `docs/configuration.md`
- Modify: `docs/config-reference.md`
- Modify: `docs/deployment.md`
- Modify: `docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md`

**Interfaces:**
- Consumes: scheduled endpoint contract from Task 3.
- Consumes: runner/plist contract from Task 4.
- Produces: docs that no longer claim Toss apply requires `confirmationText`.

- [ ] **Step 1: Write docs drift check command and verify it fails before docs edits**

Run:

```bash
rg -n 'confirmationText: "APPLY TOSS HOLDINGS"|requires `confirmationText|requires confirmation|APPLY TOSS HOLDINGS' docs/api.md docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md
```

Expected before docs edits: at least one stale hit in `docs/api.md` or the old Toss auto-mapping spec.

- [ ] **Step 2: Update `docs/api.md`**

Change the `/api/holdings/toss-sync` row so the apply payload is:

```md
apply: `{ "mode": "apply", "diffHash": "sha256:4444444444444444444444444444444444444444444444444444444444444444" }`
```

Update the paragraph below it to state:

```md
Apply refetches Toss and Supabase, recomputes the diff/hash, rejects blocked or stale diffs with `409`, and only then calls the Supabase replace-all RPC.
```

Add the scheduled endpoint row:

```md
| `POST` | `/api/holdings/toss-sync/scheduled` | Local scheduled Toss holdings auto-apply | `{ "mode": "auto-apply" }` with `Authorization: Bearer <TOSS_SYNC_JOB_TOKEN>` from a local request | `{ mode: "auto-apply", status, diffHash, summary, changes, blockedRows, targetRows }`; `status` is `applied`, `unchanged`, `disabled`, `blocked`, `wipe_guard_blocked`, or `error` |
```

Add the scheduled safety note:

```md
The scheduled route is for local non-browser jobs. It requires a local request and `TOSS_SYNC_JOB_TOKEN`, respects `TOSS_SYNC_AUTO_APPLY_ENABLED`, applies `create/update/delete` only when no rows are blocked, and refuses to wipe non-empty active holdings from an empty Toss snapshot.
```

- [ ] **Step 3: Update configuration docs**

In `docs/configuration.md` and `docs/config-reference.md`, add:

```md
| `TOSS_SYNC_JOB_TOKEN` | required for scheduled Toss auto-sync | none | `replace-with-random-local-token` | web `/api/holdings/toss-sync/scheduled`, local runner | Bearer token for local scheduled Toss sync | Secret. Store only in ignored local env files or launchd-private environment. |
| `TOSS_SYNC_AUTO_APPLY_ENABLED` | no | disabled | `1` | web `/api/holdings/toss-sync/scheduled` | Enables scheduled Toss auto-apply | Must be `1` to write. Any other value returns `disabled` without fetching or writing. |
```

Use the existing table columns and wording style in each file.

- [ ] **Step 4: Update deployment docs**

In `docs/deployment.md`, add a local scheduled Toss sync section with:

```md
## Local Toss Holdings Auto Sync

The local daily Toss holdings sync runs at `08:05 Asia/Seoul` through `scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist`.

Manual smoke:

```bash
TOSS_SYNC_ENV_FILE=.env.scheduler.local scripts/toss_daily_auto_sync.sh
```

The first smoke should return `disabled` until `TOSS_SYNC_AUTO_APPLY_ENABLED=1` is set. After enabling, successful statuses are `applied` and `unchanged`. `blocked`, `wipe_guard_blocked`, and `error` exit non-zero and do not write holdings.
```

- [ ] **Step 5: Update old Toss auto-mapping spec**

In `docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md`, replace:

```md
Apply still requires the reviewed hash, server-side confirmation text, and still refuses blocked or stale diffs.
```

with:

```md
Apply still requires the reviewed hash and still refuses blocked or stale diffs.
```

Replace:

```md
Add route coverage that proves dry-run can create a new US holding from a
directory-backed Toss symbol without writing Supabase, and that apply requires
`confirmationText: "APPLY TOSS HOLDINGS"` before writing Supabase.
```

with:

```md
Add route coverage that proves dry-run can create a new US holding from a
directory-backed Toss symbol without writing Supabase, and that apply writes
only when the server-recomputed diff hash still matches the reviewed hash.
```

- [ ] **Step 6: Run docs drift checks**

Run:

```bash
if rg -n 'confirmationText: "APPLY TOSS HOLDINGS"|requires `confirmationText|requires confirmation|server-side confirmation text' docs/api.md docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md; then
  exit 1
fi
rg -n 'TOSS_SYNC_JOB_TOKEN|TOSS_SYNC_AUTO_APPLY_ENABLED|/api/holdings/toss-sync/scheduled|08:05 Asia/Seoul|wipe_guard_blocked' docs/api.md docs/configuration.md docs/config-reference.md docs/deployment.md
```

Expected: first command exits 0 with no output; second command prints the new docs hits.

- [ ] **Step 7: Commit Task 5**

```bash
git add docs/api.md docs/configuration.md docs/config-reference.md docs/deployment.md docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md
git commit -m "docs(toss): 일일 자동 싱크 운영 문서화" -m "예약 토스 보유목록 싱크 API와 로컬 실행 절차를 문서화한다."
```

---

### Task 6: Final Verification

**Files:**
- Verify all files touched by Tasks 1-5.

**Interfaces:**
- Consumes every previous task.
- Produces final confidence and release notes for the branch.

- [ ] **Step 1: Run focused tests**

```bash
pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/lib/__tests__/toss-holdings-sync-service.test.ts web/src/app/api/holdings/toss-sync/__tests__/route.test.ts web/src/app/api/holdings/toss-sync/scheduled/__tests__/route.test.ts
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_toss_daily_auto_sync.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run web quality checks**

```bash
pnpm --dir web run format:check
pnpm --dir web run lint
pnpm --dir web run typecheck
```

Expected: all commands exit 0.

- [ ] **Step 3: Run docs drift checks**

```bash
if rg -n 'confirmationText: "APPLY TOSS HOLDINGS"|requires `confirmationText|requires confirmation|server-side confirmation text' docs/api.md docs/superpowers/specs/2026-06-30-toss-us-ticker-auto-mapping-design.md; then
  exit 1
fi
rg -n 'TOSS_SYNC_JOB_TOKEN|TOSS_SYNC_AUTO_APPLY_ENABLED|/api/holdings/toss-sync/scheduled|08:05 Asia/Seoul|wipe_guard_blocked' docs/api.md docs/configuration.md docs/config-reference.md docs/deployment.md
```

Expected: first command exits 0 with no output; second command prints expected docs hits.

- [ ] **Step 4: Inspect git history and worktree**

```bash
git log --oneline -6
git status --short
git diff --stat HEAD~5..HEAD
```

Expected: commits are separated by task, only intended files changed, and no unrelated unstaged changes remain except user-owned work explicitly left out.

- [ ] **Step 5: Record final verification in response**

Report:

- focused Vitest result,
- pytest runner test result,
- format/lint/typecheck result,
- docs drift result,
- any commands skipped and why.
