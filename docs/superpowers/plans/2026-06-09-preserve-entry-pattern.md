상태: Backlog

# Preserve Entry Pattern Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Only Task 1 and Task 2 Phase A are executable in this file, and they are foundation-only work, not end-to-end completion of the goal. Sections titled `Runtime Reference ... (Non-Executable)` are requirements to copy into a separate runtime plan after the DB-only stop gate is cleared; do not run them directly from this plan. Any command block inside a runtime reference section is a commented copy-template, not an executable instruction. Do not mark the TODO complete or claim production preservation until the later runtime plan includes the scheduled/web persistence boundary, web form/edit boundary, and recent buy candidate `pattern` propagation boundary.

**Goal:** Preserve buy-report `pattern` metadata as holdings `entry_pattern` so `sma_ema_hybrid` failed-breakout sell rules work without manual `strategy` or `tags` markers.

**Architecture:** Treat `entry_pattern` as the durable holdings-side copy of a buy signal's `pattern`, not as a free-form sell marker. Keep `pattern` in buy/entry report rows, add `entry_pattern` at holdings boundaries, validate it against an append-only holdings storage pattern contract, and tighten hybrid sell so structured pattern fields use exact pattern semantics while legacy `strategy`/`tags` markers keep their existing substring behavior.

**Tech Stack:** Python dataclasses and pytest, Supabase SQL migrations/RPCs, Next.js 16 + TypeScript + Zod + Vitest, existing `just` quality gates.

**Command fallback:** For every direct `pnpm --dir web ...` checkpoint below, if `pnpm` is not available on `PATH`, rerun the same command as `mise exec -- pnpm --dir web ...` instead of inventing an ad hoc command.

---

## Problem Brief

**Context:** Hybrid buy reports already emit candidate `pattern`, and entry reports already preserve that field on `EntryReportRow`. Hybrid sell also already treats `pattern`, `entry_pattern`, and `signal_pattern` as breakout markers.

**Problem:** The durable holdings contract currently exposes only `strategy` and `tags`; scheduled Supabase export and local `holdings.yaml` loading do not preserve `entry_pattern`. A breakout buy that becomes a holding can therefore lose its origin pattern unless the operator manually encodes it in `strategy` or `tags`.

**Goal:** Add a narrow active-position `entry_pattern` contract from recent buy candidate selection/import/export through holdings DB/YAML/scheduled export into `sab sell` and the scheduled AI brief holdings bridge.

**Non-Goals:** Do not redesign holdings as lots, do not add partial exits, do not change failed-breakout thresholds, do not change buy/entry ranking policy, and do not extend the Add Buy flow/RPC to infer or accept `entry_pattern`. `entry_pattern` is active-position metadata: inactive (`quantity = 0`) holdings must store it as `null`, so every deactivation/reactivation path must prevent a closed position's marker from reaching a later position. Add Buy defensively clears `entry_pattern` when it reactivates an inactive holding because that is a new position rather than a continuation of the old entry; after the DB active-row constraint is live, target DB smoke must not depend on constructing an impossible stale inactive row with a non-null marker. Negative quantity is outside the current holdings schema contract and must not be treated as a supported reactivation state.

**Constraints:** Keep backwards compatibility with old holdings rows/YAML files; `entry_pattern` must be optional and nullable. Avoid broad web UI redesign. Update strategy/holdings docs because this changes a public holdings contract.

## Impact Note

This changes the holdings schema, web holdings DTOs/forms, YAML import/export, scheduled holdings export, Python holdings loader, hybrid sell marker interpretation, and the sell-evaluation bridge that builds the evaluator metadata dict. The likely breakages are mismatched Supabase RPC signatures, TypeScript fixture drift, YAML round-trip omissions, PostgREST `select` omissions, old replace-all callers clearing the new column, YAML import collapsing omitted `entry_pattern` into explicit null, YAML export omitting explicit nulls, overly permissive substring marker parsing, stale candidate-derived form state, stale inactive-holding `entry_pattern` markers surviving Add Buy, normal edit/PATCH, quantity-only PATCH deactivation that omits `entry_pattern`, or YAML reactivation, unsafe full-replacement RPC smoke tests, historical Add Buy replay events being rewritten when they should remain immutable, and loader fields that never reach `sab sell`. Tests/docs must cover Python loader/export including inactive-row marker rejection, `_evaluate_holdings` metadata forwarding, exact `entry_pattern` validation, web schema/YAML helpers, ticker recent-candidate metadata, executable migration/RPC validation on disposable data, shared holdings select queries, create/update persistence bodies, edit-form preservation, Add Buy rejection of `entry_pattern` inputs, active Add Buy preservation, inactive-row null enforcement, inactive-to-active null enforcement across Add Buy/replace-all/web update paths, defensive stale-marker clearing only where the invalid precondition is constructible in static/disposable verification, and legacy Add Buy replay compatibility without rewriting historical event payloads or timestamps.

## Scope Check

This is one cross-boundary metadata contract, not several independent subsystems. It should stay in one plan because each task moves the same `entry_pattern` field across one adjacent boundary.

Add Buy remains quantity-only in this plan. It should keep returning the full holding row after the schema change and must not accept or infer `entry_pattern`. For existing active holdings (`quantity > 0`), Add Buy is treated as a continuation/scale-in operation and preserves `entry_pattern` by design, even though weighted-average `entry_price` or earliest `entry_date` may change; if the operator is changing the position thesis rather than continuing the same entry, they must clear or edit `entry_pattern` through normal holdings edit/YAML import. Cover this explicit Add Buy exception with tests so it is not confused with the YAML/replace-all entry-identity rule below. For inactive-to-active reactivation (`quantity = 0` before the buy), Add Buy writes `entry_pattern = null` because the previous marker belongs to a closed position. This null write is defensive against stale pre-constraint data, but once `holdings_entry_pattern_active_quantity_check` is applied, normal target databases cannot contain `quantity = 0` with non-null `entry_pattern`; smoke tests on target data must verify null reactivation, and stale-non-null clearing must be proven by static SQL checks or isolated disposable tests that deliberately bypass the constraint. This clear is part of a broader active-position invariant: rows with `quantity = 0` must have `entry_pattern = null`. Generic edit/PATCH, form-save, server-action, YAML/import, and replace-all paths must normalize any payload that owns `quantity: 0` to also own `entry_pattern: null`; explicit non-null `entry_pattern` remains invalid when the same create/patch/import payload does not own `quantity > 0`. Do not broaden this to `quantity < 0`; the current DB schema is nonnegative and the Add Buy weighted-average price logic only has defined new-position semantics for exactly zero quantity.

YAML import/replace-all compatibility depends on preserving source key presence. A missing `entry_pattern` key in an old YAML file or canonical replace-all payload means "leave the existing DB value unchanged" only when the resulting row remains active **and** the import is not changing the entry identity or strategy/thesis. For this YAML/replace-all preserve-on-omit rule, entry identity changes are operator/import replacement changes to `entry_price` or `entry_date` on an existing active row, and thesis changes include `strategy` changes on an existing active row with a non-null `entry_pattern`; Add Buy scale-in math is the explicit exception described above because Add Buy has no marker input and is defined as continuation when the pre-buy row is active. If any of those replacement fields change while the incoming active row omits `entry_pattern`, reject the row before persistence and require the caller to send an explicit valid `entry_pattern` or an explicit clear (`entry_pattern: null` or blank). This prevents an old breakout marker from being silently preserved onto a different active position or thesis. An explicit `entry_pattern: null` or blank string means "clear the value"; a non-empty string means "set the value" for an active row. Do not normalize missing YAML `entry_pattern` to `null` before building the `replace_holdings_v1` request, because that would turn old active-row YAML imports into destructive clears for non-entry-identity/non-thesis updates. Operator-facing YAML import copy must also mention this preserve-on-omit exception and the entry-identity/strategy exception, because the import is no longer a literal full replacement for fields that old YAML files do not know about.

`replace_holdings_v1` remains a canonical holdings ticker RPC for web/YAML import paths, so those callers must normalize slash-class and exchange aliases before calling it. Direct/foreign RPC callers should send stored canonical tickers such as `BRK.B.NYS`, not `BRK/B.NYS`. Do not silently canonicalize inside the replace-all RPC in this plan, because its delete semantics make mixed raw/canonical payloads hazardous. However, canonical-ticker rejection is DB hardening, not part of the default `entry_pattern` migration: add alias-rejection SQL, static snippets, and disposable negative smoke only if the direct-caller audit explicitly keeps that hardening in this release; otherwise defer it to a separate DB-hardening migration. Because replace-all reasons over the current holdings snapshot before applying a destructive full replacement, the RPC must serialize against concurrent holdings writers. The default migration must take a holdings table lock such as `lock table public.holdings in share row exclusive mode;` before reading existing rows for preserve-on-omit validation, counting unchanged rows, updating, inserting, or deleting. Add Buy already row-locks its target row, but replace-all has whole-table delete semantics and cannot safely rely on per-row locks acquired only after validation.

The preserve-on-omit exception applies only while the resulting row remains active. If a replace-all/YAML import row sets `quantity = 0`, `replace_holdings_v1` must clear `entry_pattern` even when the incoming key is omitted, and must reject an explicit non-null `entry_pattern` on that inactive row. If an old inactive row later becomes active through replace-all while omitting `entry_pattern`, the result stays `null`; callers must explicitly set a valid current pattern for the new position if they want the hybrid sell marker. Normal web PATCH/update must apply the same invariant by clearing `entry_pattern` whenever it sends `quantity: 0`; this includes public route/action payloads that omit `entry_pattern` entirely, not only UI-generated payloads that already include `entry_pattern: null`. Because public PATCH/action schemas cannot infer the existing DB row's active state from a marker-only payload, a non-null `entry_pattern` create/patch payload must include `quantity > 0` in the same payload, while explicit `entry_pattern: null` remains allowed as a clear without quantity. Tests must prove inactive rows cannot keep stale markers through generic update paths and that marker-only non-null PATCH/action payloads are rejected before persistence.

YAML export is different from YAML import. Exported YAML is an owned current-DB snapshot, so it must emit `entry_pattern` explicitly even when the DB value is `null`; otherwise a backup of a cleared value becomes an old-style omitted key and later import would preserve an active-row DB marker instead of owning the clear. Only parser/import/replace-all inputs may omit the key to mean active-row preserve-existing; inactive rows still clear or reject the marker.

`entry_pattern` values must be exact holdings storage pattern IDs. The initial append-only storage IDs are `trend_pullback_bounce`, `swing_high_breakout`, and `rsi_oversold_reversal`; they intentionally cover the current buy `HybridPattern` values but are not derived dynamically from that enum. The only failed-breakout `entry_pattern` value is `swing_high_breakout`; an unknown value such as `not_a_breakout` must be rejected at external write/import boundaries and must not trigger hybrid sell merely because it contains the substring `breakout`. Existing free-form `strategy`/`tags` marker behavior is preserved for backwards compatibility.

Pattern ID lifecycle rule: because `entry_pattern` is durable active-position data, the holdings storage pattern allowlist is append-only for storage compatibility unless a dedicated data migration retires or rewrites all affected active holdings, YAML backups, web allowlists, Python loader allowlists, and DB constraints together. Adding a new `HybridPattern` requires either confirming the new enum value is already accepted by the storage contract or adding it through a new effective SQL constraint migration plus web/Python allowlist update. Renaming or removing a buy enum value must keep the old stored ID accepted until a reviewed migration proves no active holding, generated YAML snapshot, or backup import can still contain it. Drift guards should assert current buy enum values are covered by the append-only storage contract; they must not require equality in a way that rejects older stored IDs or lets Python accept a new enum before DB/web migrations are live.

## Deployment Ordering

No runtime may run a PostgREST `select` or mutation body containing `entry_pattern` against a database that has not applied the `holdings.entry_pattern` migration. This includes the Python scheduled export helper, the inline `.github/workflows/sell.yml` and `.github/workflows/ai-brief.yml` holdings exports, and the web/admin `HOLDINGS_SELECT` shared by list/create/update/YAML import/export. To make the task checkpoints executable and safe for this repo, Task 1 is limited to local Python YAML loading and sell-evaluation forwarding. Task 2 must be split into mandatory deployment gates: first land/apply/verify a DB-only migration release, then enable runtime select/body changes in a separate runtime release only after `public.holdings.entry_pattern`, `replace_holdings_v1`, `holdings_add_buy_v1`, and service-role PostgREST smoke checks have passed against the target database. Because the first runtime release changes public holdings contracts, that same runtime boundary must also include the YAML optional-key implementation, form/action quantity-zero normalization, route/action marker guards, and public docs for holdings/API/strategy/scheduled exports; do not ship a runtime that selects or writes `entry_pattern` while docs still say holdings only forwards `strategy`/`tags` or while YAML export/import still uses the old snapshot shape. Two commits in one branch or PR are not a deployment boundary; do not merge/deploy runtime changes with the DB migration unless reviewed deployment automation proves migrations are applied before any runtime code can execute.

DB-only Phase A must be write-closed for non-null `entry_pattern` values. It may add the nullable column, effective allowlist constraints, Add Buy response-shape compatibility, future replace-all logic, and static contract tests, but it must also add a temporary `holdings_entry_pattern_write_closed_check` constraint and an explicit `replace_holdings_v1` guard that rejects non-null incoming `entry_pattern` until export/backup/runtime paths own the field. This prevents an operator or direct RPC caller from writing production metadata that the still-old web/YAML/scheduled export paths would silently omit. The first runtime storage/export release must start with a small DB enablement migration that drops `holdings_entry_pattern_write_closed_check` and recreates `replace_holdings_v1` without the temporary non-null-write guard; only after that enablement migration and deployed-secret PostgREST smoke pass may runtime code select, export, or mutate non-null `entry_pattern`.

DB-only compatibility rule: Phase A is not automatically backwards-compatible just because it contains only SQL. Recreating `replace_holdings_v1` or `holdings_add_buy_v1` can change direct/operator RPC behavior before web runtime deploys. Before writing the Phase A migration contract test, audit all known direct callers (`web`, workflow scripts, local operator docs/scripts, and any Supabase RPC usage outside this repo) and record the audit result in the DB-only PR notes. If the migration keeps canonical-ticker rejection for `replace_holdings_v1` or adds `REVOKE ... FROM PUBLIC`, this audit is a blocking prerequisite and the release notes must call it intentional DB contract hardening. If the audit evidence is unavailable or shows possible dependency on alias input or inherited `PUBLIC` execute, split canonical-ticker rejection and `PUBLIC` execute hardening into a separate DB-hardening release and remove those expectations from this migration's static tests and smoke. Do not describe Phase A as backward-compatible unless the audit proves no existing caller depends on the old alias or inherited-execute behavior.

Autonomous implementation boundary: Task 2 Phase A and the runtime work after the Step 4 STOP are separate implementation tasks, separate PR/release candidates, and preferably separate plan files or forked threads. The Phase B checklist below is retained only to preserve the reviewed runtime requirements; a worker must not execute, stage, or deploy it in the same autonomous run as the DB-only migration unless reviewed deployment automation guarantees migration-first execution and records that proof. After Phase A smoke passes, copy the Phase B checklist into a dedicated runtime plan before editing runtime files. The checklist is non-executable while it remains in this plan.

DB-only Add Buy response note: `holdings_add_buy_v1` already returns `setof public.holdings`; recreating it after adding `holdings.entry_pattern` means Add Buy response rows may now include nullable `entry_pattern` before runtime code changes. Treat that as an explicitly accepted backward-compatible DB-first response expansion, verify it in Phase A Add Buy RPC/PostgREST smoke, and record it in the DB-only PR notes. Do not add `p_entry_pattern`, infer a marker, or change the Add Buy request body.

Hard stop: after the DB-only migration commit/release, stop implementation and record the target database smoke evidence before editing, staging, or deploying runtime files that mention `entry_pattern` in PostgREST selects or mutation bodies. If PostgREST sees the SQL migration in `information_schema` but rejects `entry_pattern`, reload/wait for the PostgREST schema cache, rerun the service-role select/write smoke, and do not proceed to runtime rollout until that smoke passes.

## Rollback Ordering

Before runtime ships, Phase A recovery is DB-only. If the DB migration or recreated RPC behavior is wrong after apply, prefer a forward-fix migration that keeps `public.holdings.entry_pattern` and corrects the constraint/RPC definition. If an urgent rollback is unavoidable before any runtime selects or writes the new column, restore the previous `replace_holdings_v1` and `holdings_add_buy_v1` definitions from the existing applied migrations in a new corrective migration; do not edit applied migration files in place. Do not drop `public.holdings.entry_pattern` once any non-null production value may have been written, because that would destroy active-position metadata and invalidate YAML backups generated after Phase A.

After any runtime that selects or mutates `entry_pattern` is deployed, rollback must be runtime-first. Disable or roll back web/admin runtime, scheduled `sell.yml`, scheduled/manual `ai-brief.yml`, and the Python scheduler helper so no live path sends `entry_pattern` in PostgREST selects or mutation bodies; then verify the runtime projection no longer mentions `entry_pattern` before considering a DB rollback or restore to a pre-column schema. Prefer a forward-fix migration once runtime has shipped, because dropping or restoring away `public.holdings.entry_pattern` while runtime still selects it will break holdings reads and scheduled exports.

## File Structure

This section is a roadmap, not a single execution scope. For this file's active execution scope, edit only the files listed under **Executable in this plan**. Files listed under **Runtime reference only** must be copied into a separate runtime plan after the Task 2 Phase A DB-only stop gate and target PostgREST smoke have passed.

### Executable in this plan

- Modify `sab/holdings_loader.py`: add optional `Holding.entry_pattern` and parse it from `holdings.yaml`.
- Create `sab/entry_pattern_contract.py`: define the append-only holdings storage pattern IDs used by Python loader tests and SQL/web drift guards.
- Modify `sab/signals/hybrid_sell.py`: make structured pattern fields use exact failed-breakout pattern semantics instead of substring matching.
- Modify `sab/sell_evaluation.py`: forward `Holding.entry_pattern` into the evaluator holding dict.
- Modify `tests/test_holdings_yaml_contract.py`: verify Python loader accepts export-style `entry_pattern`.
- Modify `tests/test_sell_evaluation_pnl.py`: verify `_evaluate_holdings` forwards `entry_pattern` into hybrid sell metadata.
- Modify `tests/test_hybrid_sell_profit_tiers.py`: add a direct evaluator regression that a holding with only `entry_pattern=swing_high_breakout` triggers failed-breakout sell.
- Modify `docs/STRATEGY.md`: document only the local YAML/evaluator support introduced by Task 1; defer operational Supabase/web/scheduled export contract wording to the runtime release.
- Create `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql`: add nullable `entry_pattern` with length and allowed-value constraints plus a temporary write-closed constraint, replace `replace_holdings_v1` so it is ready for the future preserve-on-omit field semantics but rejects non-null writes until runtime export ownership ships, serialize replace-all with a holdings table lock before reading/updating/deleting rows, and keep replace/add-buy grants explicit only after the direct-caller hardening audit proves the privilege change is safe.
- Create `scripts/smoke_holdings_entry_pattern.sql`: executable disposable-DB smoke for `replace_holdings_v1`, `holdings_add_buy_v1`, legacy Add Buy replay, entry-identity/thesis omitted-key rejection, temp-table reentrancy, and alias rejection only when the direct-caller audit keeps canonical-ticker hardening in this migration.
- Create/modify `tests/test_holdings_entry_pattern_contract.py`: verify the DB-only static contract, Add Buy request shape, privilege-preserving migration shape, and cross-language drift guard when the runtime helper later exists.
- Modify `docs/holdings-add-buy.md`: document the DB-first Add Buy response/behavior change introduced by Phase A.
- Modify `docs/adr/ADR-0010-holdings-add-buy.md`: add the Phase A Add Buy superseding note.

### Runtime reference only

- Modify `sab/scheduler/holdings.py`: include `entry_pattern` in Supabase active-holdings select and generated YAML.
- Modify `.github/workflows/sell.yml`: include `entry_pattern` in the active scheduled sell holdings export query and generated YAML keys.
- Modify `.github/workflows/ai-brief.yml`: include `entry_pattern` in the AI brief holdings export query and generated YAML keys.
- Create: `supabase/migrations/20260609010000_enable_holdings_entry_pattern_writes.sql` or equivalent runtime enablement migration that drops the Phase A write-closed constraint and recreates `replace_holdings_v1` without the temporary non-null-write guard before runtime selects/bodies deploy.
- Modify `tests/test_scheduled_holdings_export.py`: verify scheduled export selects and writes `entry_pattern`.
- Modify `tests/test_workflow_holdings_loading.py`: verify `sell.yml` scheduled inline export and `ai-brief.yml` manual inline export select and write `entry_pattern`.
- Modify `web/src/lib/types.ts`: add required nullable `entry_pattern` to holding record/current snapshot types, add optional nullable `entry_pattern` to mutation input, and add a replace/import snapshot type whose `entry_pattern` key is optional so YAML imports can preserve missing-vs-null semantics.
- Create `web/src/lib/holding-entry-pattern.ts`: centralize the web-side append-only storage pattern IDs so schemas, YAML helpers, ticker-directory extraction, and client parsing cannot drift from each other or from `sab.entry_pattern_contract`.
- Create `web/src/lib/holding-mutation.ts`: centralize `normalizeHoldingMutationForPersistence` so API routes, server actions, and YAML apply paths enforce the same active-position invariant before persistence.
- Modify `web/src/lib/schemas.ts`: accept optional nullable `entry_pattern` on create/patch and validate exact allowed pattern IDs.
- Modify `web/src/lib/supabase/holdings.ts`: select, create/update, and replace-all `entry_pattern`, omitting the key from active replace-all rows only when the incoming replace/import snapshot omitted it, and sending/deriving explicit null when the row is inactive.
- Modify `web/src/lib/holdings-yaml.ts`: parse/export/diff `entry_pattern`, validate exact allowed pattern IDs, preserve whether the YAML import row omitted the key, and emit explicit `null` in generated exports.
- Modify `web/src/components/holdings/form-state.ts`: add `entry_pattern` form state.
- Modify `web/src/components/holdings/helpers.ts`: map `entry_pattern` between records, forms, and mutation payloads.
- Modify `web/src/components/holdings/holdings-form-panel.tsx`: add a small Entry Pattern select/menu.
- Modify `web/src/components/holdings/holdings-table.tsx`: display `entry_pattern` as compact Tags-cell metadata without changing row actions.
- Modify `web/src/components/holdings/holdings-import-panel.tsx`: update import copy to explain omitted `entry_pattern` preserves the existing DB value only for active rows.
- Modify `web/src/components/holdings/use-holdings-import.ts`: update the apply confirmation copy so it no longer claims every DB field is literally replaced by file content.
- Modify `web/src/components/holdings-client.module.css` if the table uses secondary-line `entry_pattern` metadata.
- Modify `web/src/components/holdings/use-ticker-lookup.ts`: parse optional `pattern` on recent candidate payloads while preserving ticker-search behavior.
- Modify `web/src/components/holdings/use-recent-candidates.ts`: expose recent candidate `pattern`.
- Modify `web/src/components/holdings-client.tsx`: when selecting a recent buy candidate, always populate ticker, populate `entry_pattern` only when the candidate has a non-empty `pattern`, and clear stale candidate-derived `entry_pattern` on no-pattern candidate selection or non-recent ticker changes without clearing manual/edit-loaded values.
- Modify `web/src/lib/ticker-directory.ts`: carry buy report row `pattern` only in recent buy candidates; keep persisted directory cache/search entries pattern-free.
- Modify web tests:
  - `web/src/lib/__tests__/schemas.test.ts`
  - `web/src/lib/__tests__/holding-mutation.test.ts`
  - `web/src/lib/__tests__/holdings-yaml.test.ts`
  - `web/src/lib/__tests__/supabase-admin.test.ts`
  - `web/src/app/actions/__tests__/holdings.test.ts`
  - `web/src/lib/__tests__/ticker-directory.test.ts`
  - `web/src/lib/__tests__/holdings-client-hooks.test.tsx`
  - `web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts`
  - `web/src/app/api/holdings/__tests__/route.test.ts`
  - `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`
  - `web/src/app/api/holdings/[ticker]/__tests__/route.integration.test.ts`
  - `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`
  - `web/src/app/api/holdings/yaml/__tests__/route.test.ts`
  - add-buy route/precheck tests that use `HoldingRecord` fixtures
  - add-buy single-ticker route, catch-all route, and action negative tests proving `entry_pattern` payloads are rejected
- Modify `docs/holdings-schema.md`: document optional `entry_pattern`, allowed pattern IDs, and explicit export-null behavior.
- Modify `docs/holdings-add-buy.md`: document that Add Buy preserves existing active-position `entry_pattern`, clears stale inactive-position markers on reactivation, and does not infer or accept a new one.
- Modify `docs/STRATEGY.md`: update the hybrid sell note that currently says holdings only forwards `strategy`/`tags`.
- Modify `docs/ARCHITECTURE.md`: update the holdings CRUD and ticker-directory flow notes that now carry buy candidate `pattern` into holdings `entry_pattern`.
- Modify `docs/api.md`: document `entry_pattern` on holdings create/patch/record responses, explicitly state Add Buy rejects marker fields, and document that `/api/tickers/recent-candidates` now returns `pattern: string | null`.
- Modify `docs/configuration.md`: clarify the exact server-side Supabase secret required for holdings RPC/write paths and scheduled export. If the optional service-role-only hardening release is kept, document that it must be service-role-capable; otherwise document the current server-secret/write-capability requirement without implying service-role-only RPC grants.
- Modify `docs/config-reference.md`: mirror the same server-side Supabase secret requirement so the configuration reference does not drift from `docs/configuration.md`.
- Modify `docs/local-docker-scheduler-plan.md`: update the scheduled AI Brief holdings export field list to include `entry_pattern`.
- Modify `docs/holdings-ticker-lookup.md`: update stale recent-candidate payload wording while keeping ticker-directory cache/search described as ticker/name-only.
- Modify `docs/adr/ADR-0008-holdings-ticker-directory.md`: add a superseding note that cache/search remains ticker/name-only while recent buy candidate selection may carry `pattern`.
- Modify `docs/adr/ADR-0010-holdings-add-buy.md`: add a superseding note for Add Buy `entry_pattern` preservation/clearing semantics.
- Modify `holdings.example.yaml`: add a commented/example `entry_pattern`.
- Modify `TODOS.md`: move the completed active bullet to Completed only after implementation and full verification pass.

## Task 1: Python Holdings Contract

**Files:**
- Create: `sab/entry_pattern_contract.py`
- Modify: `sab/holdings_loader.py`
- Modify: `sab/signals/hybrid_sell.py`
- Modify: `sab/sell_evaluation.py`
- Modify: `docs/STRATEGY.md`
- Test: `tests/test_holdings_yaml_contract.py`
- Test: `tests/test_sell_evaluation_pnl.py`
- Test: `tests/test_hybrid_sell_profit_tiers.py`

- [ ] **Step 1: Write failing Python contract tests**

Prerequisite: before writing or running the red tests, verify the affected Python modules parse under the repository-pinned Python 3.14 toolchain. Run `UV_CACHE_DIR=.uv-cache uv run python -m py_compile sab/sell_evaluation.py sab/scheduler/holdings.py`; if this fails on the active toolchain, fix only the syntax blocker first. Do not mechanically rewrite `except TypeError, ValueError:` to the parenthesized form when `ruff-format` normalizes it back to Python 3.14's accepted style; fighting the formatter will make pre-commit fail before the `entry_pattern` contract is exercised.

In `tests/test_holdings_yaml_contract.py`, update imports first:

```python
from pathlib import Path

import pytest

from sab.holdings_loader import HoldingsLoadError, load_holdings
```

Then extend `test_loader_accepts_export_style_holdings_yaml` so the TSLA row contains `entry_pattern`, and assert the loaded value:

```python
            "    strategy: swing\n"
            "    entry_pattern: swing_high_breakout\n"
            "    notes: leader\n"
```

Add this assertion after the existing `entry_currency` assertion:

```python
    assert loaded.holdings[1].entry_pattern == "swing_high_breakout"
```

Add a fail-closed regression in the same file so the new action-driving `entry_pattern` marker cannot be smuggled through non-string YAML values:

```python
def test_loader_rejects_non_string_entry_pattern(tmp_path: Path) -> None:
    path = tmp_path / "holdings.yaml"
    path.write_text(
        "holdings:\n"
        "  - ticker: AAPL.NAS\n"
        "    quantity: 1\n"
        "    entry_price: 100\n"
        "    entry_currency: USD\n"
        "    entry_pattern:\n"
        "      - swing_high_breakout\n",
        encoding="utf-8",
    )

    with pytest.raises(HoldingsLoadError) as excinfo:
        load_holdings(path.as_posix())

    message = str(excinfo.value)
    assert "field='entry_pattern'" in message
    assert "expected a string" in message
```

Also add optional-value regressions in `tests/test_holdings_yaml_contract.py` so the loader contract is explicit: an omitted `entry_pattern` key loads as `None`, an explicit `entry_pattern: null` loads as `None`, and a blank or whitespace-only `entry_pattern` value also loads as `None`. These lock the backwards-compatible nullable semantics that `_parse_optional_text_field` implements and prove export-style null snapshots are accepted. Add the non-string rejection as a small parameterized set, or equivalent separate tests, covering at least YAML list, mapping, boolean (`true`), and numeric (`123`) values because YAML scalar coercion can otherwise turn marker-looking inputs into non-string Python values. Add an overlong regression with 121 characters and assert the loader reports `field='entry_pattern'` and `<= 120`. Add an unknown-value regression with `entry_pattern: not_a_breakout` and assert the loader reports `field='entry_pattern'` plus `expected one of`; this keeps the action-driving field tied to exact storage pattern IDs instead of arbitrary marker strings. Add an inactive-row invariant regression with `quantity: 0` and `entry_pattern: swing_high_breakout`; assert `load_holdings` raises `HoldingsLoadError` with `field='entry_pattern'` and `inactive holdings entry_pattern must be null`. Omitted, explicit `null`, blank, and whitespace-only `entry_pattern` must still be accepted for `quantity: 0` because they normalize to `None`. Add a drift guard that imports `HybridPattern` from `sab.signals.hybrid_buy` and imports `HOLDINGS_ENTRY_PATTERN_VALUES` from the new storage contract module. Assert `{pattern.value for pattern in HybridPattern}.issubset(set(HOLDINGS_ENTRY_PATTERN_VALUES))`, not equality. This proves current buy patterns remain storable while preserving the append-only ability to keep older stored IDs accepted after a future enum rename/removal.

In `tests/test_hybrid_sell_profit_tiers.py`, add this regression near `test_hybrid_sell_failed_breakout_accepts_entry_tags`:

```python
def test_hybrid_sell_failed_breakout_accepts_entry_pattern(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        stop_loss_pct_min=0.10,
        stop_loss_pct_max=0.20,
    )
    holding = {"entry_price": 100.0, "entry_pattern": "swing_high_breakout"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "SELL"
    assert any("Failed breakout" in reason for reason in result.reasons)
```

Add the negative regressions next to it so non-breakout and unknown `entry_pattern` values do not trigger failed-breakout exits merely because the key is present or contains the substring `breakout`:

```python
def test_hybrid_sell_failed_breakout_ignores_non_breakout_entry_pattern(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        stop_loss_pct_min=0.10,
        stop_loss_pct_max=0.20,
    )
    holding = {"entry_price": 100.0, "entry_pattern": "trend_pullback_bounce"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "HOLD"
    assert not any("Failed breakout" in reason for reason in result.reasons)
```

Add the substring-smuggling counterpart immediately after it:

```python
def test_hybrid_sell_failed_breakout_ignores_unknown_entry_pattern_with_breakout_substring(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        stop_loss_pct_min=0.10,
        stop_loss_pct_max=0.20,
    )
    holding = {"entry_price": 100.0, "entry_pattern": "not_a_breakout"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "HOLD"
    assert not any("Failed breakout" in reason for reason in result.reasons)
```

Add the same exact-vs-substring and allowed-non-breakout regressions for the other structured marker fields. `pattern="swing_high_breakout"` and `signal_pattern="swing_high_breakout"` should trigger failed-breakout sells. `pattern="not_a_breakout"`, `signal_pattern="not_a_breakout"`, `pattern="trend_pullback_bounce"`, `signal_pattern="trend_pullback_bounce"`, `pattern="rsi_oversold_reversal"`, and `signal_pattern="rsi_oversold_reversal"` must not trigger merely because the key is present, the value is a valid non-breakout pattern, or the value contains the substring `breakout`. Add malformed structured-field regressions for `pattern`, `entry_pattern`, and `signal_pattern` with at least list, mapping, boolean, and numeric values; structured fields must only accept string values that exactly equal `swing_high_breakout` for failed-breakout matching, rather than stringifying arbitrary objects. Also add legacy regressions proving a free-form `strategy` value containing `breakout` and a free-form `tags` value containing `breakout` still trigger the failed-breakout rule, because the planned implementation must tighten only structured fields and preserve old `strategy`/`tags` marker behavior.

In `tests/test_sell_evaluation_pnl.py`, add this regression near `test_evaluate_holdings_passes_tags_to_hybrid_sell`:

```python
def test_evaluate_holdings_passes_entry_pattern_to_hybrid_sell() -> None:
    runtime = _make_runtime(entry_price=100.0)
    runtime.cfg.sell_mode = "sma_ema_hybrid"
    runtime.holdings[0].entry_pattern = "swing_high_breakout"
    captured: dict[str, Any] = {}

    def _evaluate(
        _ticker: str,
        _candles: list[dict[str, float]],
        holding: dict[str, Any],
        _settings: Any,
    ) -> SimpleNamespace:
        captured.update(holding)
        return SimpleNamespace(
            action="HOLD",
            reasons=["ok"],
            stop_price=None,
            target_price=None,
            eval_price=100.0,
            eval_date="20250102",
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=lambda *_args, **_kwargs: pytest.fail(
            "generic sell evaluator should not be called"
        ),
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert captured["entry_pattern"] == "swing_high_breakout"
```

Add one bridge-style regression named `test_evaluate_holdings_passes_loaded_entry_pattern_to_hybrid_sell` that starts from a real loaded `Holding`, not only a manually patched runtime namespace. Keep it in `tests/test_sell_evaluation_pnl.py` with the existing fake hybrid evaluator style: set `runtime.cfg.sell_mode = "sma_ema_hybrid"`, make the generic evaluator fail if called, write a temporary `holdings.yaml` containing `entry_pattern: swing_high_breakout`, load it with `load_holdings`, assign `runtime.holdings = loaded.holdings`, capture the `holding` dict passed to `evaluate_sell_signals_hybrid_fn`, and assert `captured["entry_pattern"] == "swing_high_breakout"`. After loading, rekey `runtime.market_data` and `runtime.ticker_currency` from `loaded.holdings[0].ticker` instead of assuming the fixture ticker remains `AAPL.NASD`; `load_holdings()` canonicalizes US suffixes such as `NASD` to `NAS`, and a mismatched market-data key would skip the evaluator before the bridge is exercised. This proves the real YAML loader and `_evaluate_holdings` dict bridge work together.

Keep the direct hybrid sell tests in `tests/test_hybrid_sell_profit_tiers.py`, but do not count them as sufficient by themselves; they mostly guard the existing `_is_breakout_holding` reader. The direct tests must cover all three structured fields (`pattern`, `entry_pattern`, `signal_pattern`) plus the legacy `strategy`/`tags` compatibility markers, otherwise a partial implementation can pass while leaving old substring behavior on one structured field.

- [ ] **Step 2: Run Python tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_yaml_contract.py tests/test_sell_evaluation_pnl.py tests/test_hybrid_sell_profit_tiers.py -q
```

Expected: FAIL because `Holding` has no `entry_pattern`, `_evaluate_holdings` does not forward `entry_pattern`, the loader does not yet fail closed on non-string, unknown, overlong, or inactive-row non-null `entry_pattern`, the append-only storage allowlist module does not exist yet, and `_is_breakout_holding` still substring-matches structured `pattern`, `entry_pattern`, and `signal_pattern` values. The direct positive hybrid sell regression may already pass because `_is_breakout_holding` already recognizes the key; the full `tests/test_hybrid_sell_profit_tiers.py` run is intentional so the structured `pattern`/`signal_pattern` and legacy `strategy`/`tags` compatibility regressions cannot be skipped.

- [ ] **Step 3: Add `entry_pattern` to the Python loader**

In `sab/holdings_loader.py`, append the field to `Holding` after `target_override`, not in the middle of the dataclass. At least one test constructs `Holding(...)` positionally, and appending avoids breaking positional construction semantics for existing or external callers:

```python
    entry_pattern: str | None = None
```

Add this helper near `_parse_entry_date`:

```python
def _parse_optional_text_field(
    p: Path,
    *,
    value: Any,
    field_name: str,
    item_index: int,
    ticker: str,
    max_length: int | None = None,
    allowed_values: frozenset[str] | None = None,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_holdings_value(
            p,
            f"expected a string, got {type(value).__name__}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    text = value.strip()
    if max_length is not None and len(text) > max_length:
        raise _invalid_holdings_value(
            p,
            f"expected a string <= {max_length} characters, got {len(text)}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    if allowed_values is not None and text and text not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise _invalid_holdings_value(
            p,
            f"expected one of {allowed}.",
            field_name=field_name,
            item_index=item_index,
            ticker=ticker,
        )
    return text or None
```

Create `sab/entry_pattern_contract.py` with the append-only storage IDs:

```python
HOLDINGS_ENTRY_PATTERN_VALUES = (
    "trend_pullback_bounce",
    "swing_high_breakout",
    "rsi_oversold_reversal",
)

HOLDINGS_ENTRY_PATTERNS = frozenset(HOLDINGS_ENTRY_PATTERN_VALUES)
```

Use this contract from `sab/holdings_loader.py` instead of deriving values from `HybridPattern`:

```python
from .entry_pattern_contract import HOLDINGS_ENTRY_PATTERNS
```

Then pass `allowed_values=HOLDINGS_ENTRY_PATTERNS` to the parser. This module is deliberately append-only storage state, not a live view of the buy enum. If a future `HybridPattern` is renamed or removed, the old stored value must remain accepted until a reviewed data migration proves it is gone from active holdings and backups. If a new buy enum is added, add it to the storage contract, SQL constraint, and web helper in a migration-aware release before Python accepts it from holdings YAML.

Do not change existing `strategy` or `settings.default_strategy` parsing in this task; `strategy` is already a sell marker and changing blank/default fallback semantics would be an unrelated behavior change.

In `_parse_holding`, parse `entry_pattern` after the entry-currency validation and before constructing `Holding`, then reject inactive rows with a non-null marker:

```python
    entry_pattern = _parse_optional_text_field(
        p,
        value=item.get("entry_pattern"),
        field_name="entry_pattern",
        item_index=item_index,
        ticker=ticker,
        max_length=120,
        allowed_values=HOLDINGS_ENTRY_PATTERNS,
    )
    if quantity == 0 and entry_pattern is not None:
        raise _invalid_holdings_value(
            p,
            "inactive holdings entry_pattern must be null.",
            field_name="entry_pattern",
            item_index=item_index,
            ticker=ticker,
        )
```

This makes local `holdings.yaml` fail closed on the same active-position invariant enforced by DB/YAML import paths. Keep the current `strategy` assignment and set the new field after it:

```python
        strategy=item.get("strategy") or settings.default_strategy,
        entry_pattern=entry_pattern,
```

- [ ] **Step 4: Tighten hybrid sell structured pattern semantics and forward `entry_pattern`**

In `sab/signals/hybrid_sell.py`, change `_is_breakout_holding` so `pattern`, `entry_pattern`, and `signal_pattern` are treated as exact structured buy pattern fields. Only `swing_high_breakout` should satisfy the failed-breakout pattern check. Keep the existing substring behavior for legacy free-form `strategy` and `tags` markers so older holdings are not broken.

In `sab/sell_evaluation.py`, add the field to `holding_dict` immediately after `strategy`:

```python
            "entry_pattern": getattr(holding, "entry_pattern", None),
```

This bridge is required because `_evaluate_holdings` builds a plain dict explicitly; adding a dataclass field alone does not reach `evaluate_sell_signals_hybrid`.

Update `docs/STRATEGY.md` in the same Task 1 commit, but keep this Task 1 wording scoped to local YAML loading and the sell evaluator. Do not use the broad Task 5 runtime wording yet, because scheduled Supabase exports and web holdings persistence still omit `entry_pattern` until the DB gate and runtime release. Replace the note that currently says holdings only forwards `strategy` and `tags` with wording that says local `holdings.yaml` may now provide `entry_pattern`, the hybrid evaluator treats structured `pattern`/`entry_pattern`/`signal_pattern` as exact pattern IDs, legacy `strategy`/`tags` substring markers still work, and scheduled/web Supabase preservation ships in the later runtime boundary.

- [ ] **Step 5: Run Python contract tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_yaml_contract.py tests/test_sell_evaluation_pnl.py tests/test_hybrid_sell_profit_tiers.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Python contract**

```bash
git add sab/entry_pattern_contract.py sab/holdings_loader.py sab/signals/hybrid_sell.py sab/sell_evaluation.py docs/STRATEGY.md tests/test_holdings_yaml_contract.py tests/test_sell_evaluation_pnl.py tests/test_hybrid_sell_profit_tiers.py
git commit -m "feat(holdings): 진입 패턴 YAML 계약 추가" -m "buy 후보의 pattern을 holdings entry_pattern으로 보존할 수 있도록 Python 로더와 sell 평가 경계를 확장한다."
```

## Task 2: Supabase DB Migration Gate (Phase A Only)

Deployment rule for this task: do not combine the DB migration and any runtime `entry_pattern` select/body changes in one deployable release unless reviewed deployment automation proves migrations run before runtime. The default path is two deployable PRs/releases and two autonomous implementation runs: a DB-only migration release with executable smoke, then a runtime storage/export/web-mutation release after the target database has the column and RPC behavior. Keeping two commits in one branch is useful for review, but it is not sufficient as a deployment boundary.

Phase A is DB-only: create the migration, add the static migration/RPC contract test, create the tracked disposable-DB smoke script, apply the migration, complete executable SQL and PostgREST smoke, and commit/release only those DB artifacts. Phase B is runtime: only after Phase A smoke evidence is recorded may the worker edit scheduled exports, workflows, web Supabase selects/bodies, mutation schemas, runtime fixtures, or runtime tests. Step 1 and Step 2 are Phase A-only; any web, scheduled export, workflow, or runtime test instructions in this task are Phase B checklists for a later runtime plan and must not be edited, run, staged, or deployed before the Step 4 STOP is explicitly cleared.

Prerequisite: Task 1 must already be committed/available before starting Phase A because `tests/test_holdings_entry_pattern_contract.py` imports `sab.entry_pattern_contract`. If Phase A must be run from a clean DB-only branch without Task 1, keep the migration allowlist test self-contained with a local literal and move the Python/web cross-language drift guard to the later runtime plan instead of silently pulling runtime files into the DB-only PR.

**Phase A executable files:**
- Create: `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql`
- Create: `scripts/smoke_holdings_entry_pattern.sql`
- Create/Modify: `tests/test_holdings_entry_pattern_contract.py`
- Modify: `docs/holdings-add-buy.md`
- Modify: `docs/adr/ADR-0010-holdings-add-buy.md`
- Required pre-existing input from Task 1, not edited in Phase A: `sab/entry_pattern_contract.py`

**Phase B checklist only - do not edit these files from Task 2 Phase A. Copy this list into a dedicated runtime plan after Phase A target smoke passes:**
- Modify: `sab/scheduler/holdings.py`
- Modify: `.github/workflows/sell.yml`
- Modify: `.github/workflows/ai-brief.yml`
- Create: `supabase/migrations/20260609010000_enable_holdings_entry_pattern_writes.sql` or equivalent runtime enablement migration
- Modify: `web/src/lib/types.ts`
- Create: `web/src/lib/holding-entry-pattern.ts`
- Create: `web/src/lib/holding-mutation.ts`
- Modify: `web/src/lib/schemas.ts`
- Modify: `web/src/lib/supabase/holdings.ts`
- Modify: `web/src/lib/holdings-yaml.ts`
- Modify: `web/src/app/actions/holdings.ts`
- Modify: `web/src/app/api/holdings/route.ts`
- Modify: `web/src/app/api/holdings/[ticker]/route.ts`
- Modify: `web/src/app/api/holdings/[...ticker]/route.ts`
- Modify: `web/src/app/api/holdings/yaml/route.ts` if needed to preserve omitted-vs-null replace-all rows
- Promote from Task 3 into this runtime boundary: full YAML parser/export/diff semantics, YAML route pass-through, and YAML-focused tests. `HoldingSnapshot` is a required-nullable DB/current snapshot type in this repo, so changing it without updating `holdings-yaml.ts` is not an executable checkpoint. Do not add a temporary missing-to-null workaround.
- Test: `tests/test_scheduled_holdings_export.py`
- Test: `tests/test_workflow_holdings_loading.py`
- Test: `web/src/lib/__tests__/schemas.test.ts`
- Test: `web/src/lib/__tests__/holding-mutation.test.ts`
- Test: `web/src/lib/__tests__/supabase-admin.test.ts`
- Test: `web/src/lib/__tests__/holdings-yaml.test.ts`
- Test: `web/src/app/api/holdings/yaml/__tests__/route.test.ts`
- Docs in the same runtime boundary: `docs/holdings-schema.md`, `docs/holdings-add-buy.md`, `docs/STRATEGY.md`, `docs/api.md`, `docs/configuration.md`, `docs/config-reference.md`, `docs/local-docker-scheduler-plan.md`, `docs/adr/ADR-0010-holdings-add-buy.md`, and any architecture/scheduler note that would otherwise contradict the new runtime behavior
- Test fixtures if surfaced by typecheck: `web/src/app/api/holdings/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`, and `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`

- [ ] **Step 0: Record direct-caller audit and DB hardening decision**

Before writing the migration static contract test, inspect all known callers of `replace_holdings_v1` and `holdings_add_buy_v1` in this repo plus any known operator/direct Supabase usage outside the repo. Record the audit result in the DB-only PR notes. At minimum, record:

- whether every replace-all caller sends canonical stored tickers, not slash-class aliases such as `BRK/B.NYS`;
- whether any caller depends on inherited `PUBLIC` execute privileges instead of the configured server-side Supabase secret;
- if the optional service-role-only hardening is kept in this release, whether the exact deployed `SUPABASE_SECRET_KEY`/`SUPABASE_SERVICE_ROLE_KEY` is service-role-capable after `REVOKE ... FROM PUBLIC`;
- the release decision: defer canonical-ticker rejection and `PUBLIC` revoke to a separate DB-hardening migration by default, or keep them in this migration only with a recorded audit artifact proving no caller depends on alias input or inherited `PUBLIC` execute.

If the audit is not complete, or if it finds a caller that may depend on alias input or inherited `PUBLIC` execute, defer canonical-ticker rejection and `PUBLIC` execute hardening. For out-of-repo callers, an agent cannot prove absence by grepping this repository; record one explicit artifact instead: either a human operator confirmation that no external callers depend on alias input or inherited `PUBLIC` execute, or `external caller evidence: unknown`, which means hardening is deferred. The default Phase A snippets below already follow that core-only path: they omit `"incoming holdings tickers must be canonical"`, `ticker <> public.canonical_holdings_ticker(ticker)`, `REVOKE ... FROM PUBLIC`, explicit anon/auth/service_role privilege changes, and service-role-only privilege expectations. Keep the `entry_pattern` column, constraints, temporary write-closed guard, preserve-on-omit logic for the later runtime unlock, entry-identity exception, replace-all table lock, and Add Buy preservation behavior in the DB-only migration. For the default path, record the pre-migration effective execute posture for `PUBLIC`, `anon`, `authenticated`, and the deployed runtime secret, then verify the post-migration posture is unchanged; do not require `anon`/`authenticated` to be false unless the pre-migration effective posture already proves that. If the precheck shows inherited `PUBLIC` execute leaves anon/auth callable, record it as an existing DB-hardening follow-up and do not describe this Phase A as permission hardening. Do not proceed by leaving pseudo-hardening SQL in place while calling it backwards-compatible. If the audit explicitly keeps hardening in this release, add those SQL blocks and matching static/smoke assertions as a separate, labeled hardening variant in the DB-only PR notes.

- [ ] **Step 1: Phase A - unblock syntax and write the failing DB-only contract test**

First verify syntax under the repository-pinned Python 3.14 toolchain: run `UV_CACHE_DIR=.uv-cache uv run python -m py_compile sab/sell_evaluation.py sab/scheduler/holdings.py`. If this fails on the active toolchain, make only the minimum syntax fix before adding or running contract tests so the red phase fails on the new `entry_pattern` contract, not on existing import-time syntax errors. Do not mechanically rewrite `except TypeError, ValueError:` when `ruff-format` normalizes it back to Python 3.14's accepted style. Keep this prerequisite narrowly scoped; do not add `entry_pattern` to runtime selects or serializer bodies before the DB-only migration gate.

Step 1 edit scope is limited to `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql`, `tests/test_holdings_entry_pattern_contract.py`, `scripts/smoke_holdings_entry_pattern.sql`, and the syntax-only fixes above. The full Phase A executable scope also includes `docs/holdings-add-buy.md` and `docs/adr/ADR-0010-holdings-add-buy.md` when Step 3 documents the DB-first Add Buy behavior. Stop Step 1 after the DB-only static contract test is written; add the smoke script in Step 4 before claiming Phase A verification. The web, scheduled export, workflow, and Supabase adapter instructions below are a Phase B checklist for a later runtime plan; do not edit, run, stage, or deploy those files before the Step 4 STOP is cleared.

Phase B checklist for Step 6, not Step 1: before runtime code can select or write `entry_pattern`, add the runtime DB enablement migration that drops `holdings_entry_pattern_write_closed_check` and recreates `replace_holdings_v1` without the temporary non-null-write guard. Then, in `web/src/lib/__tests__/supabase-admin.test.ts`, update the local holding fixture helper or individual expected `HoldingRecord` objects to include:

```ts
entry_pattern: null,
```

In the existing `replaceAllHoldings` test named `"calls replace_holdings_v1 RPC with sanitized holdings snapshot"`, add `entry_pattern` to the input row:

```ts
        strategy: "swing",
        entry_pattern: "swing_high_breakout",
        notes: "leader",
```

Update the expected request body in that same test:

```ts
            strategy: "swing",
            entry_pattern: "swing_high_breakout",
            notes: "leader",
```

Add a second `replaceAllHoldings` adapter regression for old YAML/import input that omits the key. Pass one `HoldingReplaceSnapshot` row without an owned `entry_pattern` property, inspect the posted `p_holdings[0]`, and assert:

```ts
expect(Object.prototype.hasOwnProperty.call(postedRow, "entry_pattern")).toBe(
  false,
);
```

Add the explicit-clear counterpart with `entry_pattern: null` and assert the posted row owns `entry_pattern` with `null`. Add an owned-undefined counterpart as a defensive regression: construct a row that owns `entry_pattern` with `undefined` (use a deliberate cast if needed), and assert the posted row does **not** own `entry_pattern`. This prevents TypeScript optional-property looseness from turning `undefined` into an accidental clear. These tests prove the adapter preserves the distinction that `replace_holdings_v1` relies on.

Add a small helper in `web/src/lib/__tests__/supabase-admin.test.ts` and use it in holdings read/write tests that build PostgREST `select` queries:

```ts
function expectHoldingsSelectIncludesEntryPattern(
  fetchMock: { mock: { calls: Array<[unknown, RequestInit?]> } },
  callIndex = 0,
) {
  const requestUrl = fetchMock.mock.calls[callIndex]?.[0];
  const url = new URL(String(requestUrl));
  expect(url.searchParams.get("select")?.split(",")).toContain("entry_pattern");
}
```

At minimum, call this helper in the existing `fetchAllHoldings` pagination test, one `fetchHoldingsPage`/pagination test if present, a successful `createHolding` insert test, and the update-holding request test. If a successful create test does not exist, add one. The goal is to fail if `HOLDINGS_SELECT` is not updated for list/create/update responses. Do not count this as Add Buy coverage; Add Buy uses the `holdings_add_buy_v1` RPC directly.

In the successful `createHolding` test and update test, assert the request body includes `entry_pattern` when the adapter receives it. The route/action tests mock the adapter and are not enough to prove Supabase persistence:

```ts
expect(JSON.parse(String(requestInit?.body))).toEqual(
  expect.objectContaining({
    entry_pattern: "swing_high_breakout",
  }),
);
```

Add the explicit-clear counterpart at the same Supabase adapter boundary. Call `updateHolding`/`patchHoldingByExactTicker` through the public adapter path with `{ entry_pattern: null }`, inspect the outbound PATCH body, and assert the body owns `entry_pattern` with `null`. Do not accept a test that only mocks `updateHolding`, because that does not prove the PostgREST mutation body preserves null clears:

```ts
const body =
  typeof requestInit?.body === "string"
    ? (JSON.parse(requestInit.body) as Record<string, unknown>)
    : null;

expect(Object.prototype.hasOwnProperty.call(body, "entry_pattern")).toBe(true);
expect(body?.entry_pattern).toBeNull();
```

Add a deactivation counterpart at the same adapter boundary: call the public update path with a patch that sets `{ quantity: 0, entry_pattern: null }`, inspect the outbound PATCH body, and assert it owns `entry_pattern` with `null`. This locks the active-position invariant and prevents a generic quantity edit from leaving an old failed-breakout marker on an inactive row. Route/action/UI tests should also prove the normal holdings save path sends that null clear when an edited active row is saved with `quantity = 0`; direct PostgREST PATCH callers that omit the clear should fail the DB constraint instead of silently preserving stale metadata.

In `web/src/app/api/holdings/[ticker]/__tests__/route.integration.test.ts`, add value and explicit-null `entry_pattern` PATCH pass-through regressions against the real route/Supabase request construction, and assert the route's PostgREST `select` includes `entry_pattern`. This file is the existing integration-level guard for actual PATCH request construction and must be included in the runtime fixture/staging list.

In the existing `addBuyToHolding` test named `"calls holdings_add_buy_v1 RPC and returns updated holding"`, return a row with a non-null `entry_pattern`, assert it is present on the returned row, and assert the RPC request body remains quantity-only. Add adjacent adapter/RPC contract regressions for the DB migration smoke plan: an active holding preserves a non-null `entry_pattern`, an inactive-to-active Add Buy from `quantity = 0` and `entry_pattern = null` returns `entry_pattern: null`, the migration SQL contains the defensive stale-clearing assignment for pre-constraint data, and a pre-migration-style cached replay payload that lacks `entry_pattern` is still returned with `entry_pattern: null` by the `setof public.holdings` replay path without mutating the historical event row.

```ts
const updated = await addBuyToHolding(/* existing args */);

expect(updated?.entry_pattern).toBe("swing_high_breakout");

const body =
  typeof requestInit?.body === "string"
    ? (JSON.parse(requestInit.body) as Record<string, unknown>)
    : null;
expect(body).not.toHaveProperty("p_entry_pattern");
```

In `web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.integration.test.ts`, update the real route/Supabase request construction coverage so the mocked RPC response may include `entry_pattern: "swing_high_breakout"` and the returned payload preserves it, while the outbound RPC body still contains only `p_ticker`, quantity/price/date/idempotency fields and never `p_entry_pattern`.

Add direct Add Buy API/action negative coverage so the public Add Buy surface cannot accidentally start accepting a marker field. In `web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts`, add a request with `{ buy_quantity: 1, buy_price: 10, entry_pattern: "swing_high_breakout" }`, assert status 400 with `"Invalid holding add-buy payload"`, and assert `addBuyToHolding` was not called. Add the same rejection test to the public catch-all route at `web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts`. In `web/src/app/actions/__tests__/holdings.test.ts`, call `addBuyToHoldingAction` with the same extra `entry_pattern`, assert `{ ok: false, error: "Invalid holding add-buy payload" }`, and assert `addBuyToHolding` was not called. These tests may already pass because `holdingAddBuySchema.strict()` rejects unknown keys; keep them as contract guards.

In `web/src/lib/__tests__/schemas.test.ts`, add create/patch schema regressions proving normal holdings create/update payloads accept trimmed `entry_pattern` when the same payload includes `quantity > 0`, accept explicit `null`, and reject unknown values such as `not_a_breakout`. Add inactive-row schema regressions too: `quantity: 0` with a non-null `entry_pattern` must be rejected before persistence, while `quantity: 0` with `entry_pattern: null` is accepted. Schema parsing alone cannot know the existing DB row's marker, so create `web/src/lib/holding-mutation.ts` with `normalizeHoldingMutationForPersistence` and use it from create, single PATCH, catch-all PATCH, YAML apply when it builds replace rows, and `saveHoldingAction`. Also apply the same normalization inside the exported Supabase persistence adapter functions (`createHolding`, `updateHolding`/`patchHoldingByExactTicker`, and `replaceAllHoldings`) before serializing PostgREST/RPC bodies, so future direct imports cannot bypass the active-position invariant and turn a normal deactivation into a DB constraint failure. Add direct helper coverage in `web/src/lib/__tests__/holding-mutation.test.ts` for: `quantity === 0` forces an owned `entry_pattern: null`; marker-only non-null patch is rejected; explicit `entry_pattern: null` clears without requiring quantity; non-null `entry_pattern` is allowed only when the same payload owns `quantity > 0`; owned `entry_pattern: undefined` is treated as omission for replace/import rows. The helper contract is fixed, not optional. Add route/action regressions for `PATCH { quantity: 0 }` with no `entry_pattern` and assert `updateHolding` receives `{ quantity: 0, entry_pattern: null }`. Add Supabase-adapter regressions proving direct `createHolding`, `updateHolding`, and `replaceAllHoldings` calls normalize or reject the same payloads before the outbound body is built. Add route/action regressions for marker-only non-null PATCH/action payloads such as `{ entry_pattern: "swing_high_breakout" }`; they must be rejected before persistence. Add the same server-action regressions for `saveHoldingAction` so API and action paths cannot diverge. This belongs in Task 2, not Task 3, because the first runtime release that can send `entry_pattern` to Supabase must also have public API/action schemas that accept the field after the DB migration is live and must not allow inactive rows to keep action-driving markers. Keep Add Buy schema strict and covered by the negative tests above.

In `tests/test_scheduled_holdings_export.py`, add `entry_pattern` to the active fake Supabase row:

```python
                    "strategy": "sma_ema_hybrid",
                    "entry_pattern": "swing_high_breakout",
                    "notes": None,
```

Update the URL assertion to require the selected field:

```python
    assert "entry_pattern" in str(session.get_calls[0]["url"])
```

Update the expected YAML payload:

```python
                "strategy": "sma_ema_hybrid",
                "entry_pattern": "swing_high_breakout",
                "tags": ["core"],
```

Add a second active fake Supabase row with `"entry_pattern": None` and assert the generated YAML owns the key with `None`. This protects the export-side contract that scheduled generated holdings files are current DB snapshots, not old-style import payloads; omitting `entry_pattern` on export would later preserve a stale DB marker instead of clearing it.

Add a fail-loud scheduled export regression where the fake Supabase response returns an active row that omits the `entry_pattern` key entirely. Assert `export_active_holdings_snapshot` raises `SupabaseHoldingsExportError` and the message contains `omitted entry_pattern`. This directly locks the `_normalize_rows` safety requirement from Step 5; value-present and explicit-null cases are not enough because a projection bug otherwise becomes a destructive clear snapshot.

In `tests/test_workflow_holdings_loading.py`, extend `test_sell_workflow_loads_holdings_from_supabase_before_run_sell` so it fails if the cron workflow's inline Supabase export omits `entry_pattern`:

```python
    assert "entry_pattern" in run_script
    assert (
        "select=ticker,quantity,entry_price,entry_currency,entry_date,"
        "strategy,entry_pattern,notes,tags,stop_override,target_override"
        in run_script
    )
    assert '"entry_pattern",' in run_script
    # Serializer null/missing-key behavior is verified by the executable helper below.
```

Also assert the inline serializer behavior structurally, not only by substring checks. Add a helper that extracts the embedded Python block from the workflow step and executes it against fixture `holdings.supabase.json` rows, or factor the serializer into a tiny scriptable helper before testing. Cover at least: `entry_pattern: null` is preserved, legacy optional `notes: null` is omitted, and a row missing the selected `entry_pattern` key fails loudly. Add a sibling workflow regression for `.github/workflows/ai-brief.yml` that finds its manual `Load holdings from Supabase` step and checks the same selected field string plus the same executable serializer cases. The scheduled AI Brief job uses `sab ai-brief-scheduled` and the Python scheduler export helper; keep that coverage in `tests/test_scheduled_holdings_export.py` and do not treat the manual inline workflow test as proof of scheduled-job behavior.

Create `tests/test_holdings_entry_pattern_contract.py`. Import `HOLDINGS_ENTRY_PATTERN_VALUES` from `sab.entry_pattern_contract` and `HybridPattern` from `sab.signals.hybrid_buy`. Do not make an applied timestamped migration file track future enum changes directly. The new migration should be checked for the initial contract it introduces, while a separate current-effective-contract drift guard should read the latest migration that defines `holdings_entry_pattern_value_check` and compare that effective allowlist to `set(HOLDINGS_ENTRY_PATTERN_VALUES)`. Add a second guard asserting current buy enum values are a subset of the storage contract. If a future buy pattern is added, the fix should be a new migration/current contract update, not editing the already-applied `20260609000000` migration in place. If a future buy pattern is renamed or removed, the storage contract may intentionally remain a superset until a reviewed data migration retires the old stored value.

```python
from __future__ import annotations

import re
from pathlib import Path

from sab.entry_pattern_contract import HOLDINGS_ENTRY_PATTERN_VALUES
from sab.signals.hybrid_buy import HybridPattern


_MIGRATIONS_DIR = Path("supabase/migrations")
_MIGRATION_PATH = _MIGRATIONS_DIR / "20260609000000_add_holdings_entry_pattern.sql"
_ADD_BUY_MIGRATION_PATH = _MIGRATIONS_DIR / "20260304002000_add_holdings_add_buy_idempotency.sql"
_INITIAL_ENTRY_PATTERN_IDS = {
    "trend_pullback_bounce",
    "swing_high_breakout",
    "rsi_oversold_reversal",
}


def _normalize_sql(sql: str) -> str:
    normalized = re.sub(r"\s+", " ", sql.lower()).strip()
    return normalized.replace("( ", "(").replace(" )", ")")


def _strip_sql_comments(sql: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--.*?$", "", without_block_comments, flags=re.MULTILINE)


def _extract_in_list_values_after(sql: str, marker: str) -> set[str]:
    start = sql.lower().index(marker.lower())
    segment = sql[start:]
    match = re.search(r"\bin\s*\(([^)]*)\)", segment, flags=re.IGNORECASE | re.DOTALL)
    assert match is not None, f"missing SQL IN list after {marker!r}"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def _latest_entry_pattern_constraint_sql() -> str:
    candidates = [
        path
        for path in sorted(_MIGRATIONS_DIR.glob("*.sql"))
        if path.name >= _MIGRATION_PATH.name
        and "holdings_entry_pattern_value_check" in path.read_text(encoding="utf-8")
    ]
    assert candidates, "missing effective entry_pattern constraint migration"
    return candidates[-1].read_text(encoding="utf-8")


def test_holdings_entry_pattern_migration_updates_replace_holdings_contract() -> None:
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")
    normalized_sql = _normalize_sql(sql)

    required_snippets = [
        "add column if not exists entry_pattern text null",
        "add constraint holdings_entry_pattern_length_check",
        "char_length(entry_pattern) <= 120",
        "add constraint holdings_entry_pattern_value_check",
        "entry_pattern in (",
        "add constraint holdings_entry_pattern_active_quantity_check",
        "entry_pattern is null or quantity > 0",
        "add constraint holdings_entry_pattern_write_closed_check",
        "entry_pattern is null",
        "lock table public.holdings in share row exclusive mode",
        "incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern",
        "Cannot add holdings entry_pattern constraints while invalid rows exist.",
        "Clear or fix entry_pattern on inactive, unknown, or overlong rows before rerunning.",
        "jsonb_typeof(incoming.item->'entry_pattern') <> 'string'",
        "incoming holdings entry_pattern must be a string",
        "incoming holdings entry_pattern must be <= 120 chars",
        "incoming holdings entry_pattern must be one of",
        "inactive holdings entry_pattern must be null",
        "incoming holdings entry_pattern must be explicit when entry identity or strategy changes",
        "drop table if exists pg_temp.incoming_holdings",
        "nullif(trim(incoming.item->>'entry_pattern'), '') not in (",
        "has_entry_pattern boolean not null",
        "entry_pattern text null",
        "incoming.item ? 'entry_pattern'",
        "when incoming.quantity = 0 then null",
        "when incoming.has_entry_pattern then incoming.entry_pattern",
        "else existing.entry_pattern",
        "entry_pattern text null",
        "case when incoming.quantity = 0 then null else incoming.entry_pattern end",
        "jsonb_populate_record(null::public.holdings, v_event.result_payload)",
        "create or replace function public.holdings_add_buy_v1(",
        "entry_pattern = case",
        "when coalesce(v_target.quantity, 0) = 0 then null",
        "else v_target.entry_pattern",
    ]
    for snippet in required_snippets:
        assert _normalize_sql(snippet) in normalized_sql

    assert _extract_in_list_values_after(
        sql, "holdings_entry_pattern_value_check"
    ) == _INITIAL_ENTRY_PATTERN_IDS
    assert _extract_in_list_values_after(
        sql, "nullif(trim(incoming.item->>'entry_pattern'), '') not in"
    ) == _INITIAL_ENTRY_PATTERN_IDS

    forbidden_snippets = [
        "grant execute on function public.replace_holdings_v1(jsonb) to anon",
        "grant execute on function public.replace_holdings_v1(jsonb) to authenticated",
        "grant execute on function public.replace_holdings_v1(jsonb) to public",
        "drop function public.replace_holdings_v1",
        "drop function if exists public.replace_holdings_v1",
        "drop function public.holdings_add_buy_v1",
        "drop function if exists public.holdings_add_buy_v1",
        "event.result_payload = event.result_payload || jsonb_build_object('entry_pattern', existing.entry_pattern)",
        "update public.holdings_add_buy_events event set result_payload",
        "disable row level security",
        "incoming holdings tickers must be canonical",
        "ticker <> public.canonical_holdings_ticker(ticker)",
        "revoke all on function public.replace_holdings_v1(jsonb) from public",
        "revoke all on function public.holdings_add_buy_v1(text,numeric,numeric,date,text) from public",
        "revoke all on function public.replace_holdings_v1(jsonb) from anon",
        "revoke all on function public.replace_holdings_v1(jsonb) from authenticated",
        "grant execute on function public.replace_holdings_v1(jsonb) to service_role",
        "revoke all on function public.holdings_add_buy_v1(",
        "grant execute on function public.holdings_add_buy_v1(",
    ]
    for snippet in forbidden_snippets:
        assert _normalize_sql(snippet) not in normalized_sql


def test_effective_entry_pattern_sql_allowlist_matches_storage_contract() -> None:
    effective_sql = _latest_entry_pattern_constraint_sql()

    assert _extract_in_list_values_after(
        effective_sql, "holdings_entry_pattern_value_check"
    ) == set(HOLDINGS_ENTRY_PATTERN_VALUES)


def test_current_buy_patterns_are_covered_by_storage_contract() -> None:
    storage_patterns = set(HOLDINGS_ENTRY_PATTERN_VALUES)
    buy_patterns = {pattern.value for pattern in HybridPattern}

    assert buy_patterns <= storage_patterns


def test_add_buy_rpc_remains_quantity_only_and_handles_entry_pattern_edges() -> None:
    historical_sql = _ADD_BUY_MIGRATION_PATH.read_text(encoding="utf-8")
    historical_function_sql = historical_sql[
        historical_sql.index("create or replace function public.holdings_add_buy_v1") :
    ]
    new_migration_sql = _normalize_sql(
        _strip_sql_comments(_MIGRATION_PATH.read_text(encoding="utf-8"))
    )

    assert "p_entry_pattern" not in historical_function_sql
    assert "p_entry_pattern" not in new_migration_sql
    assert "event.result_payload = to_jsonb(existing)" not in new_migration_sql
    assert "jsonb_build_object('entry_pattern', existing.entry_pattern)" not in new_migration_sql

    required_snippets = [
        "create or replace function public.holdings_add_buy_v1(",
        "returns setof public.holdings",
        "returning *",
        "jsonb_populate_record(null::public.holdings, v_event.result_payload)",
        "v_request_fingerprint := md5(",
        "entry_pattern = case",
        "when coalesce(v_target.quantity, 0) = 0 then null",
        "else v_target.entry_pattern",
    ]
    for snippet in required_snippets:
        assert _normalize_sql(snippet) in new_migration_sql

    fingerprint_start = new_migration_sql.index("v_request_fingerprint := md5(")
    fingerprint_end = new_migration_sql.index(
        "insert into public.holdings_add_buy_events", fingerprint_start
    )
    fingerprint_sql = new_migration_sql[fingerprint_start:fingerprint_end]
    assert "entry_pattern" not in fingerprint_sql
```

After `web/src/lib/holding-entry-pattern.ts` exists, add a cross-language drift guard to `tests/test_holdings_entry_pattern_contract.py` or an equivalent focused web/Python contract test. It must assert the TypeScript `HOLDING_ENTRY_PATTERN_VALUES` set equals `set(HOLDINGS_ENTRY_PATTERN_VALUES)` so the manually duplicated web allowlist cannot diverge silently from the append-only storage contract. Keep the separate subset guard for `{pattern.value for pattern in HybridPattern}`. This test should fail before the TS helper exists and pass after Step 6. Make the implementation concrete: read `web/src/lib/holding-entry-pattern.ts`, extract the quoted values inside the `HOLDING_ENTRY_PATTERN_VALUES = [...] as const` array with a small regex, and compare that set to `set(HOLDINGS_ENTRY_PATTERN_VALUES)`. Do not parse arbitrary TypeScript or rely on importing TS from Python.

- [ ] **Step 2: Run Supabase contract tests to verify failure**

Run Phase A only:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_entry_pattern_contract.py -q
```

Expected: FAIL because the new migration file does not exist yet or does not yet satisfy the DB/RPC static contract. Do not run web, scheduled export, workflow, or Supabase adapter tests in Phase A; those are Phase B runtime tests and must wait until the DB migration has been applied and the Step 4 SQL plus PostgREST smoke evidence is recorded. If the first failure is still an import `SyntaxError`, return to Step 1 and fix only that syntax blocker before treating the red phase as meaningful.

- [ ] **Step 3: Add the migration**

Create `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql`:

Compatibility decision: `replace_holdings_v1` must preserve an existing `entry_pattern` when an incoming active row omits the key entirely, so old callers and older YAML snapshots do not silently wipe the new marker. Inactive rows are different: `quantity = 0` always means `entry_pattern = null`, and an explicit non-null marker on an inactive row is rejected. A caller can still clear the field explicitly by sending `"entry_pattern": null` or a blank string. Track key presence with `has_entry_pattern`; `jsonb_to_recordset` alone cannot distinguish an absent key from an explicit null.

```sql
alter table public.holdings
  add column if not exists entry_pattern text null;

do $$
declare
  invalid_tickers text;
begin
  select string_agg(ticker, ', ' order by ticker)
  into invalid_tickers
  from public.holdings
  where entry_pattern is not null
    and (
      char_length(entry_pattern) > 120
      or entry_pattern not in (
        'trend_pullback_bounce',
        'swing_high_breakout',
        'rsi_oversold_reversal'
      )
      or quantity = 0
    );

  if invalid_tickers is not null then
    raise exception using
      errcode = 'check_violation',
      message = 'Cannot add holdings entry_pattern constraints while invalid rows exist.',
      detail = format('Invalid holdings rows: %s', invalid_tickers),
      hint = 'Clear or fix entry_pattern on inactive, unknown, or overlong rows before rerunning.';
  end if;
end
$$;

alter table public.holdings
  drop constraint if exists holdings_entry_pattern_length_check;

alter table public.holdings
  add constraint holdings_entry_pattern_length_check
  check (entry_pattern is null or char_length(entry_pattern) <= 120);

alter table public.holdings
  drop constraint if exists holdings_entry_pattern_value_check;

alter table public.holdings
  add constraint holdings_entry_pattern_value_check
  check (
    entry_pattern is null
    or entry_pattern in (
      'trend_pullback_bounce',
      'swing_high_breakout',
      'rsi_oversold_reversal'
    )
  );

alter table public.holdings
  drop constraint if exists holdings_entry_pattern_active_quantity_check;

alter table public.holdings
  add constraint holdings_entry_pattern_active_quantity_check
  check (entry_pattern is null or quantity > 0);

-- Phase A is schema/RPC preparation only. Keep non-null writes closed until
-- runtime export/backup paths select and own entry_pattern. The runtime
-- enablement migration drops this constraint after deployed-secret PostgREST
-- smoke proves exports and writes preserve the field.
alter table public.holdings
  drop constraint if exists holdings_entry_pattern_write_closed_check;

alter table public.holdings
  add constraint holdings_entry_pattern_write_closed_check
  check (entry_pattern is null);

-- Do not backfill processed Add Buy replay payloads. The existing
-- jsonb_populate_record(null::public.holdings, result_payload) replay
-- path exposes missing nullable entry_pattern values as null without
-- mutating historical event payloads or updated_at timestamps.

create or replace function public.replace_holdings_v1(
  p_holdings jsonb default '[]'::jsonb
)
returns table(
  inserted_count integer,
  updated_count integer,
  deleted_count integer,
  unchanged_count integer
)
language plpgsql
as $$
declare
  v_inserted_count integer := 0;
  v_updated_count integer := 0;
  v_deleted_count integer := 0;
  v_unchanged_count integer := 0;
  v_duplicate_tickers text;
begin
  if p_holdings is null then
    p_holdings := '[]'::jsonb;
  end if;

  if jsonb_typeof(p_holdings) <> 'array' then
    raise exception 'p_holdings must be a JSON array';
  end if;

  lock table public.holdings in share row exclusive mode;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') <> 'string'
  ) then
    raise exception 'incoming holdings entry_pattern must be a string';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') = 'string'
      and char_length(nullif(trim(incoming.item->>'entry_pattern'), '')) > 120
  ) then
    raise exception 'incoming holdings entry_pattern must be <= 120 chars';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') = 'string'
      and nullif(trim(incoming.item->>'entry_pattern'), '') is not null
      and nullif(trim(incoming.item->>'entry_pattern'), '') not in (
        'trend_pullback_bounce',
        'swing_high_breakout',
        'rsi_oversold_reversal'
      )
  ) then
    raise exception 'incoming holdings entry_pattern must be one of trend_pullback_bounce, swing_high_breakout, rsi_oversold_reversal';
  end if;

  if exists (
    select 1
    from jsonb_array_elements(p_holdings) as incoming(item)
    where incoming.item ? 'entry_pattern'
      and incoming.item->'entry_pattern' <> 'null'::jsonb
      and jsonb_typeof(incoming.item->'entry_pattern') = 'string'
      and nullif(trim(incoming.item->>'entry_pattern'), '') is not null
  ) then
    raise exception 'incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern';
  end if;

  drop table if exists pg_temp.incoming_holdings;

  create temporary table incoming_holdings (
    ticker text not null,
    quantity numeric(20, 6) not null,
    entry_price numeric(20, 4) not null,
    entry_currency text null,
    entry_date date null,
    strategy text null,
    has_entry_pattern boolean not null,
    entry_pattern text null,
    notes text null,
    tags text[] not null default '{}'::text[],
    stop_override numeric(20, 4) null,
    target_override numeric(20, 4) null
  ) on commit drop;

  insert into incoming_holdings (
    ticker,
    quantity,
    entry_price,
    entry_currency,
    entry_date,
    strategy,
    has_entry_pattern,
    entry_pattern,
    notes,
    tags,
    stop_override,
    target_override
  )
  select
    trim(coalesce(item.ticker, '')),
    round(item.quantity::numeric, 6),
    round(item.entry_price::numeric, 4),
    nullif(upper(trim(coalesce(item.entry_currency, ''))), ''),
    item.entry_date,
    nullif(trim(coalesce(item.strategy, '')), ''),
    incoming.item ? 'entry_pattern',
    nullif(trim(coalesce(item.entry_pattern, '')), ''),
    nullif(trim(coalesce(item.notes, '')), ''),
    coalesce(item.tags, '{}'::text[]),
    case
      when item.stop_override is null then null
      else round(item.stop_override::numeric, 4)
    end,
    case
      when item.target_override is null then null
      else round(item.target_override::numeric, 4)
    end
  from jsonb_array_elements(p_holdings) as incoming(item)
  cross join lateral jsonb_to_record(incoming.item) as item(
    ticker text,
    quantity numeric,
    entry_price numeric,
    entry_currency text,
    entry_date date,
    strategy text,
    entry_pattern text,
    notes text,
    tags text[],
    stop_override numeric,
    target_override numeric
  );

  if exists (
    select 1
    from incoming_holdings
    where quantity = 0
      and has_entry_pattern
      and entry_pattern is not null
  ) then
    raise exception 'inactive holdings entry_pattern must be null';
  end if;

  if exists (
    select 1
    from incoming_holdings incoming
    join public.holdings existing
      on existing.ticker = incoming.ticker
    where incoming.quantity > 0
      and existing.quantity > 0
      and existing.entry_pattern is not null
      and not incoming.has_entry_pattern
      and (
        existing.entry_price is distinct from incoming.entry_price
        or existing.entry_date is distinct from incoming.entry_date
        or existing.strategy is distinct from incoming.strategy
      )
  ) then
    raise exception 'incoming holdings entry_pattern must be explicit when entry identity or strategy changes';
  end if;

  if exists (
    select 1
    from incoming_holdings
    where ticker = ''
  ) then
    raise exception 'incoming holdings rows must include a non-empty ticker';
  end if;

  select string_agg(canonical_ticker, ', ' order by canonical_ticker)
  into v_duplicate_tickers
  from (
    select public.canonical_holdings_ticker(ticker) as canonical_ticker
    from incoming_holdings
    group by public.canonical_holdings_ticker(ticker)
    having count(*) > 1
  ) duplicates;

  if v_duplicate_tickers is not null then
    raise exception using
      errcode = '23505',
      message = 'incoming holdings contain duplicate tickers',
      detail = format('Duplicate canonical tickers: %s', v_duplicate_tickers);
  end if;

  select count(*)
  into v_unchanged_count
  from public.holdings existing
  join incoming_holdings incoming
    on incoming.ticker = existing.ticker
  where existing.quantity is not distinct from incoming.quantity
    and existing.entry_price is not distinct from incoming.entry_price
    and existing.entry_currency is not distinct from incoming.entry_currency
    and existing.entry_date is not distinct from incoming.entry_date
    and existing.strategy is not distinct from incoming.strategy
    and existing.entry_pattern is not distinct from (
      case
        when incoming.quantity = 0 then null
        when incoming.has_entry_pattern then incoming.entry_pattern
        else existing.entry_pattern
      end
    )
    and existing.notes is not distinct from incoming.notes
    and existing.tags is not distinct from incoming.tags
    and existing.stop_override is not distinct from incoming.stop_override
    and existing.target_override is not distinct from incoming.target_override;

  with updated_rows as (
    update public.holdings existing
    set
      quantity = incoming.quantity,
      entry_price = incoming.entry_price,
      entry_currency = incoming.entry_currency,
      entry_date = incoming.entry_date,
      strategy = incoming.strategy,
      entry_pattern = case
        when incoming.quantity = 0 then null
        when incoming.has_entry_pattern then incoming.entry_pattern
        else existing.entry_pattern
      end,
      notes = incoming.notes,
      tags = incoming.tags,
      stop_override = incoming.stop_override,
      target_override = incoming.target_override
    from incoming_holdings incoming
    where incoming.ticker = existing.ticker
      and (
        existing.quantity is distinct from incoming.quantity
        or existing.entry_price is distinct from incoming.entry_price
        or existing.entry_currency is distinct from incoming.entry_currency
        or existing.entry_date is distinct from incoming.entry_date
        or existing.strategy is distinct from incoming.strategy
        or existing.entry_pattern is distinct from (
          case
            when incoming.quantity = 0 then null
            when incoming.has_entry_pattern then incoming.entry_pattern
            else existing.entry_pattern
          end
        )
        or existing.notes is distinct from incoming.notes
        or existing.tags is distinct from incoming.tags
        or existing.stop_override is distinct from incoming.stop_override
        or existing.target_override is distinct from incoming.target_override
      )
    returning 1
  )
  select count(*) into v_updated_count from updated_rows;

  with inserted_rows as (
    insert into public.holdings (
      ticker,
      quantity,
      entry_price,
      entry_currency,
      entry_date,
      strategy,
      entry_pattern,
      notes,
      tags,
      stop_override,
      target_override
    )
    select
      incoming.ticker,
      incoming.quantity,
      incoming.entry_price,
      incoming.entry_currency,
      incoming.entry_date,
      incoming.strategy,
      case
        when incoming.quantity = 0 then null
        else incoming.entry_pattern
      end,
      incoming.notes,
      incoming.tags,
      incoming.stop_override,
      incoming.target_override
    from incoming_holdings incoming
    left join public.holdings existing
      on existing.ticker = incoming.ticker
    where existing.ticker is null
    returning 1
  )
  select count(*) into v_inserted_count from inserted_rows;

  with deleted_rows as (
    delete from public.holdings existing
    where not exists (
      select 1
      from incoming_holdings incoming
      where incoming.ticker = existing.ticker
    )
    returning 1
  )
  select count(*) into v_deleted_count from deleted_rows;

  inserted_count := v_inserted_count;
  updated_count := v_updated_count;
  deleted_count := v_deleted_count;
  unchanged_count := v_unchanged_count;
  return next;
end;
$$;

-- Recreate public.holdings_add_buy_v1 with the same signature,
-- idempotency fingerprint, and replay branch as the current Add Buy RPC.
-- The only behavior change is the non-replay update block: active holdings
-- preserve entry_pattern, while inactive-to-active reactivation clears it.
-- Do not add p_entry_pattern and do not include entry_pattern in the
-- idempotency request fingerprint.
create or replace function public.holdings_add_buy_v1(
  p_ticker text,
  p_buy_quantity numeric,
  p_buy_price numeric,
  p_buy_date date default null,
  p_idempotency_key text default null
)
returns setof public.holdings
language plpgsql
as $$
declare
  v_ticker_key text := trim(coalesce(p_ticker, ''));
  v_idempotency_key text := trim(coalesce(p_idempotency_key, ''));
  v_canonical_ticker text;
  v_request_fingerprint text;
  v_event public.holdings_add_buy_events%rowtype;
  v_target public.holdings%rowtype;
  v_updated public.holdings%rowtype;
  v_required_currency text;
  v_currency text;
  v_new_quantity numeric(20, 6);
  v_new_entry_price numeric(20, 4);
  v_new_entry_date date;
begin
  if v_ticker_key = '' then
    raise exception 'ticker is required';
  end if;

  if v_idempotency_key = '' then
    raise exception 'idempotency_key is required';
  end if;

  if char_length(v_idempotency_key) > 128 then
    raise exception 'idempotency_key must be <= 128 chars';
  end if;

  if v_idempotency_key !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
    raise exception 'idempotency_key must be a UUID';
  end if;

  if p_buy_quantity is null or p_buy_quantity <= 0 then
    raise exception 'buy_quantity must be > 0';
  end if;

  if p_buy_price is null or p_buy_price <= 0 then
    raise exception 'buy_price must be > 0';
  end if;

  v_canonical_ticker := public.canonical_holdings_ticker(v_ticker_key);
  v_request_fingerprint := md5(
    concat_ws(
      '|',
      v_canonical_ticker,
      round(p_buy_quantity, 6)::text,
      round(p_buy_price, 4)::text,
      coalesce(p_buy_date::text, '')
    )
  );

  insert into public.holdings_add_buy_events (
    canonical_ticker,
    idempotency_key,
    request_fingerprint
  ) values (
    v_canonical_ticker,
    v_idempotency_key,
    v_request_fingerprint
  )
  on conflict (canonical_ticker, idempotency_key) do nothing;

  select *
  into v_event
  from public.holdings_add_buy_events
  where canonical_ticker = v_canonical_ticker
    and idempotency_key = v_idempotency_key
  limit 1
  for update;

  if v_event.request_fingerprint is distinct from v_request_fingerprint then
    raise exception
      'idempotency_key payload mismatch for ticker %',
      v_canonical_ticker
    using
      errcode = '23505',
      detail = 'holdings_add_buy_idempotency_payload_mismatch';
  end if;

  if v_event.processed then
    if v_event.result_payload is null then
      return;
    end if;

    return query
    select *
    from jsonb_populate_record(null::public.holdings, v_event.result_payload);
    return;
  end if;

  select *
  into v_target
  from public.holdings
  where public.canonical_holdings_ticker(ticker) = v_canonical_ticker
  limit 1
  for update;

  if not found then
    update public.holdings_add_buy_events
    set
      processed = true,
      result_payload = null
    where canonical_ticker = v_canonical_ticker
      and idempotency_key = v_idempotency_key;
    return;
  end if;

  v_required_currency := case
    when v_target.ticker ~ '^\d{6}$' then 'KRW'
    else 'USD'
  end;

  v_currency := upper(trim(coalesce(v_target.entry_currency, '')));
  if v_currency = '' then
    v_currency := v_required_currency;
  elsif v_currency <> v_required_currency then
    raise exception
      'entry_currency mismatch for ticker %: expected %, got %',
      v_target.ticker,
      v_required_currency,
      v_currency;
  end if;

  if v_target.quantity > 0 and coalesce(v_target.entry_price, 0) <= 0 then
    raise exception
      'existing holding has non-positive entry_price for positive quantity (ticker %)',
      v_target.ticker;
  end if;

  v_new_quantity := round((coalesce(v_target.quantity, 0)::numeric + p_buy_quantity), 6);
  if v_new_quantity <= 0 then
    raise exception 'resulting quantity must be > 0';
  end if;

  if coalesce(v_target.quantity, 0) = 0 then
    v_new_entry_price := round(p_buy_price, 4);
  else
    v_new_entry_price := round(
      (
        (v_target.quantity::numeric * v_target.entry_price::numeric)
        + (p_buy_quantity * p_buy_price)
      ) / v_new_quantity,
      4
    );
  end if;

  v_new_entry_date := v_target.entry_date;
  if p_buy_date is not null and (v_new_entry_date is null or p_buy_date < v_new_entry_date) then
    v_new_entry_date := p_buy_date;
  end if;

  update public.holdings
  set
    quantity = v_new_quantity,
    entry_price = v_new_entry_price,
    entry_currency = v_currency,
    entry_date = v_new_entry_date,
    entry_pattern = case
      when coalesce(v_target.quantity, 0) = 0 then null
      else v_target.entry_pattern
    end
  where ticker = v_target.ticker
  returning *
  into v_updated;

  update public.holdings_add_buy_events
  set
    processed = true,
    result_payload = to_jsonb(v_updated)
  where canonical_ticker = v_canonical_ticker
    and idempotency_key = v_idempotency_key;

  return query
  select *
  from public.holdings
  where ticker = v_updated.ticker;
end;
$$;
```

This default SQL keeps the migration focused on `entry_pattern`, keeps non-null writes temporarily closed until export/runtime ownership ships, and does not add canonical-ticker rejection, `REVOKE ... FROM PUBLIC`, explicit anon/auth revokes, or service_role grants. `CREATE OR REPLACE FUNCTION` should preserve the existing function privilege posture; do not add partial privilege statements that look like service-role-only hardening while leaving inherited `PUBLIC` execute in place. If the direct-caller audit explicitly approves hardening changes for this release, add them in a labeled hardening block plus matching static tests, disposable smoke, and release notes. This DB-only migration changes Add Buy behavior and response shape before runtime ships, so update `docs/holdings-add-buy.md` and `docs/adr/ADR-0010-holdings-add-buy.md` in the same Phase A commit. At minimum, document that Add Buy remains quantity-only, preserves `entry_pattern` for active holdings, clears it for `quantity = 0` reactivation, rejects/does not accept `p_entry_pattern`, and may return nullable `entry_pattern` because the RPC returns `setof public.holdings`.

- [ ] **Step 4: Run executable migration smoke**

Run the static contract test first, then apply the migration to a disposable/local database before enabling runtime selects. Preferred path is the repository's local Supabase workflow if available. If no repo-local Supabase/migration recipe is available, treat target DB smoke as a manual operator gate and record the exact command class, target type, and reason local disposable apply was unavailable; do not imply the smoke was repo-local or fully automated. If using plain disposable Postgres instead of local Supabase and the optional hardening variant adds grant/revoke statements, bootstrap the Supabase-compatible roles (`anon`, `authenticated`, and `service_role`) before applying that variant. The default core-only migration should not need role bootstrap merely to exercise the column/RPC behavior. Record the command and target type used in the PR notes.

Required smoke assertions after applying the migration:

```sql
select 1
from information_schema.columns
where table_schema = 'public'
  and table_name = 'holdings'
  and column_name = 'entry_pattern';
```

Add `scripts/smoke_holdings_entry_pattern.sql` for the destructive RPC cases before relying on any manual target smoke. This tracked script provisions disposable rows, runs in a transaction or disposable database, keeps `ON_ERROR_STOP=1`, and prints only boolean assertions. Expected-failure cases must be wrapped so the script remains executable: use PL/pgSQL `DO` blocks with `BEGIN ... EXCEPTION WHEN OTHERS THEN ... END`, or `SAVEPOINT`/`ROLLBACK TO SAVEPOINT` assertions, and raise an error if the expected failure does not occur or if the error message/SQLSTATE is not the expected one. Do not disable `ON_ERROR_STOP` to make negative cases pass, because that can hide real migration failures. Run it against a disposable database after applying the migration:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/smoke_holdings_entry_pattern.sql
```

Reference that script and command in PR notes and keep manual target PostgREST checks limited to controlled smoke rows. The script must call `replace_holdings_v1` at least twice in one transaction to prove the function is reentrant after the `pg_temp.incoming_holdings` drop. Use canonical stored tickers in the default smoke. If the reviewed DB contract keeps canonical-ticker rejection, add an alias payload such as `BRK/B.NYS` and prove it fails before update/insert/delete. If canonical-ticker rejection is deferred to a separate hardening release, do not add an alias acceptance smoke; record that replace-all callers must continue to send canonical stored tickers and cover alias rejection in the later hardening release. Static SQL snippet tests are lint guards only; they cannot mark Phase A complete without this executable disposable-DB smoke or an explicitly recorded equivalent disposable-DB command.

Also exercise `replace_holdings_v1` with the executable disposable-DB smoke for these cases:

- Phase A incoming row with `"entry_pattern": "swing_high_breakout"` fails with `incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern`; this proves the DB-only release cannot create production metadata before backup/export paths own it.
- Phase A incoming row omitting `entry_pattern` leaves the existing null value unchanged when no other fields change.
- Phase A incoming row omitting `entry_pattern` leaves the existing null value unchanged while another field such as `notes` changes, proving the update branch is stable even before non-null writes are unlocked.
- Phase A static SQL must still include the future preserve-on-omit and entry-identity exception branches, but executable non-null preserve/set smoke is deferred until the runtime enablement migration drops `holdings_entry_pattern_write_closed_check` and removes the temporary `replace_holdings_v1` non-null-write guard. Runtime enablement smoke must then prove: omitted `entry_pattern` preserves an existing non-null value for no-op and notes-only updates; omitted `entry_pattern` fails when `entry_price`, `entry_date`, or `strategy` changes on an existing active row with a non-null marker; explicit `entry_pattern: null` clears; and explicit `entry_pattern: "swing_high_breakout"` allows an intentional entry-identity or thesis change.
- incoming row with `"entry_pattern": null` is accepted and leaves/stores null.
- Phase A incoming row with `quantity = 0` and omitted `entry_pattern` stores null. The branch that clears an existing non-null marker on deactivation is proved by static SQL in Phase A and by runtime enablement disposable smoke after non-null writes are unlocked.
- Phase A incoming row with `quantity = 0` and a non-null `entry_pattern` fails with the write-closed message because non-null writes are still disabled. Runtime enablement smoke, after dropping the write-closed guard, must prove the same inactive non-null payload fails with `inactive holdings entry_pattern must be null` or the DB active-quantity constraint.
- incoming row with an `entry_pattern` longer than 120 characters fails with an actionable error or the DB length constraint.
- incoming row with an unknown `entry_pattern` such as `not_a_breakout` fails with an actionable error or the DB allowed-value constraint.
- if the reviewed DB contract keeps canonical-ticker hardening in this release, incoming row with a non-canonical alias ticker such as `BRK/B.NYS` fails before mutation; if hardening is deferred, keep the default smoke canonical-only and cover alias rejection in the later DB-hardening release.
- two `replace_holdings_v1` calls in one transaction both complete or fail only on the asserted business condition, not because `incoming_holdings` already exists. Also verify the effective function definition contains `lock table public.holdings in share row exclusive mode;`, and run a disposable two-session or equivalent concurrency smoke when available: hold a replace-all transaction open after it acquires the lock, attempt a concurrent Add Buy/PATCH/replace-all against holdings, and prove the second writer waits or times out rather than passing preserve-on-omit validation against stale rows. If a two-session smoke is not available in automation, record an explicit single-writer operational constraint for replace-all imports until that smoke exists.
- Phase A `holdings_add_buy_v1` updates quantity/price/date for an already-active holding while keeping `entry_pattern` null. The non-null active-row preservation branch is proved by static SQL in Phase A and by runtime enablement disposable smoke after `holdings_entry_pattern_write_closed_check` is dropped; the smoke/PR notes must label it as the explicit active-row continuation exception rather than the YAML/replace-all entry-identity rule.
- `holdings_add_buy_v1` reactivates a normal inactive holding with `quantity = 0` and `entry_pattern = null`, and the returned row still has `entry_pattern = null`.
- Add Buy RPC/PostgREST response rows include an owned nullable `entry_pattern` after the DB migration because the RPC returns `setof public.holdings`; record this as the accepted DB-first response-shape expansion in the DB-only PR notes. In Phase A the value must remain null because non-null writes are still closed; active-row non-null preservation is proven in the runtime enablement disposable smoke after the write-closed guard is removed.
- The defensive stale-non-null clearing branch for `quantity = 0` is covered by static SQL assertion, or by an isolated disposable DB test that deliberately bypasses/drops the active-row constraint before constructing the invalid precondition. Do not require this branch as target DB smoke after `holdings_entry_pattern_active_quantity_check` is live because the stale state is no longer constructible through normal writes.
- Add Buy idempotent replay works for a post-migration event and for a pre-migration-style cached payload that lacked the key; the legacy replay should return `entry_pattern: null` through `jsonb_populate_record(null::public.holdings, result_payload)` without rewriting historical cached quantity, price, date, notes, `created_at`, `updated_at`, or the event payload itself.

Historical replay compatibility before runtime rollout: do not backfill processed `holdings_add_buy_events.result_payload` from the current `public.holdings` row. Current holdings may represent a later position, and updating processed event rows fires the `holdings_add_buy_events_set_updated_at` trigger. The migration should rely on the existing `jsonb_populate_record(null::public.holdings, v_event.result_payload)` replay branch to expose missing nullable `entry_pattern` as `null`. Record a disposable DB replay smoke proving a legacy payload without the key returns a row with `entry_pattern: null` and that the processed event row's payload and timestamps remain unchanged. Do not redefine the Add Buy RPC signature or add `p_entry_pattern`; Add Buy remains quantity-only.

Before enabling runtime code that selects or mutates `entry_pattern`, run PostgREST smoke against the target database with the exact deployed server-side secret value that the web app and scheduled jobs will use, not only SQL introspection of database roles. Use the same fallback order as the web runtime (`SUPABASE_SECRET_KEY` first, then `SUPABASE_SERVICE_ROLE_KEY`) and fail the smoke if neither value is set; do not record a smoke result from a credential different from the deployed runtime credential. At minimum, verify the exact full runtime column projection used by web and workflows succeeds, not just a reduced `ticker,entry_pattern` projection. Use `limit=0` for the target schema-cache smoke so the response validates the projection without returning real holdings rows:

```bash
SUPABASE_RUNTIME_KEY="${SUPABASE_SECRET_KEY:-${SUPABASE_SERVICE_ROLE_KEY:-}}"
test -n "$SUPABASE_RUNTIME_KEY"
curl -fsS "${SUPABASE_URL%/}/rest/v1/holdings?select=ticker,quantity,entry_price,entry_currency,entry_date,strategy,entry_pattern,notes,tags,stop_override,target_override,created_at,updated_at&limit=0" \
  -H "apikey: ${SUPABASE_RUNTIME_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_RUNTIME_KEY}" \
  -H "Accept: application/json"
```

Also run Phase A PostgREST write/RPC smoke with the exact deployed server-side secret, but keep non-null `entry_pattern` writes closed and keep full-replacement RPC tests off production/target data. On the target database, use only controlled smoke data with a reserved improbable ticker such as `SABSMOKE.NAS`: preflight that no existing row matches the ticker or any canonical alias, create the row only if absent, record the created row identity and idempotency key, and abort cleanup unless the smoke created the row. Never patch, Add Buy, or delete an existing non-smoke holding as part of target smoke. In Phase A, direct PostgREST PATCH with `entry_pattern: "swing_high_breakout"` must fail because `holdings_entry_pattern_write_closed_check` is still active; direct PATCH with explicit `entry_pattern: null` must succeed and a follow-up GET must show `entry_pattern` as `null`. Then patch the smoke row to `quantity: 0` with `entry_pattern: null` and verify the inactive row has no marker. For Add Buy on the target database, use only that reserved smoke holding and a unique smoke idempotency key, verify normal inactive reactivation from `entry_pattern = null`, and verify replay shape through `holdings_add_buy_v1` using the same deployed secret; in Phase A all returned `entry_pattern` values must be null. This catches schema-cache, representation, privilege, deployed-secret, and write-closed failures without creating production metadata that old export paths would omit.

The runtime enablement release has a separate PostgREST write/RPC smoke after its DB enablement migration drops `holdings_entry_pattern_write_closed_check` and removes the temporary `replace_holdings_v1` guard, but before any runtime selects/bodies deploy. Reuse the reserved target smoke row to create or patch `entry_pattern: "swing_high_breakout"` with `Prefer: return=representation`, verify the returned shape, patch explicit `entry_pattern: null`, verify a follow-up GET shows null, and optionally verify `quantity: 0` with non-null `entry_pattern` fails. Verify Add Buy active preservation only after this runtime unlock, using the same deployed secret. Do **not** require target smoke to prove Add Buy clears a stale non-null marker from `quantity = 0`; after the active-row constraint is live, that state cannot be created through normal target writes. Prove the defensive stale-clearing branch with static SQL assertions or an isolated disposable DB test that deliberately bypasses the constraint.

Do **not** call `replace_holdings_v1` on a production/target database with a partial `p_holdings` payload; that RPC deletes every row absent from the payload. On target data, only inspect `replace_holdings_v1` definition and, if hardening was kept, privileges; if needed, perform a reviewed no-op/full-snapshot transaction with restore guarantees. However, SQL-only psql smoke is not sufficient for this RPC because runtime invokes it through PostgREST. Phase A and runtime enablement must each execute `/rest/v1/rpc/replace_holdings_v1` against a disposable Supabase/PostgREST target, not just plain Postgres, with isolated holdings data: Phase A proves non-null values are rejected by the temporary write-closed guard and null/omitted rows work through JSON argument mapping; runtime enablement proves set, preserve-on-omit, entry-identity/strategy omitted-key rejection, clear, inactive-row null enforcement, delete behavior, and deployed-key execute through PostgREST. If a disposable Supabase/PostgREST target is unavailable, record that `replace_holdings_v1` is not fully verified and keep runtime rollout blocked until an equivalent disposable PostgREST RPC smoke is completed. If SQL introspection shows the column/function exists but PostgREST rejects `entry_pattern` or the updated RPC shape, reload or wait for the PostgREST schema cache according to the target platform, rerun the exact deployed-secret select/write/RPC smoke, and keep Phase B runtime rollout blocked until the PostgREST smoke passes.

When recording target smoke evidence, record only the command class, HTTP status, selected column list, boolean shape checks, smoke ticker, and whether cleanup was performed. Do not paste real holdings rows, response bodies from non-smoke rows, request headers, bearer tokens, API keys, curl verbose output, or environment variable values into PR notes, logs, chat, or docs.

Also verify the effective RPC definitions after applying the migration, not only the historical migration files:

```sql
select pg_get_functiondef('public.replace_holdings_v1(jsonb)'::regprocedure);
select pg_get_functiondef('public.holdings_add_buy_v1(text,numeric,numeric,date,text)'::regprocedure);
```

Always verify effective privileges after applying the default Phase A migration, because recreating RPCs must not change the observed permission posture. In the default core-only migration, run the same privilege posture checks before and after applying the migration and record the booleans in PR notes; the post-migration values must match the pre-migration values. If `anon` or `authenticated` is effectively allowed through inherited `PUBLIC` execute before the migration, record that as an existing hardening follow-up instead of treating Phase A as failed or as a hardening release. If the optional hardening variant kept service-role-only execution, replace the default preservation check with explicit negative direct-`PUBLIC` ACL plus anon/auth checks, and service-role positive checks.

```sql
-- Effective role checks. These anon/authenticated booleans include inherited PUBLIC execute.
select
  has_function_privilege('anon', 'public.replace_holdings_v1(jsonb)', 'execute') as anon_replace_execute,
  has_function_privilege('authenticated', 'public.replace_holdings_v1(jsonb)', 'execute') as authenticated_replace_execute,
  has_function_privilege('anon', 'public.holdings_add_buy_v1(text,numeric,numeric,date,text)', 'execute') as anon_add_buy_execute,
  has_function_privilege('authenticated', 'public.holdings_add_buy_v1(text,numeric,numeric,date,text)', 'execute') as authenticated_add_buy_execute;

-- Direct PUBLIC ACL checks. `grantee = 0` is PostgreSQL's PUBLIC pseudo-role.
select
  p.oid::regprocedure::text as function_signature,
  exists (
    select 1
    from aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) as acl
    where acl.grantee = 0
      and acl.privilege_type = 'EXECUTE'
  ) as public_execute_granted
from pg_proc p
where p.oid in (
  'public.replace_holdings_v1(jsonb)'::regprocedure,
  'public.holdings_add_buy_v1(text,numeric,numeric,date,text)'::regprocedure
)
order by function_signature;

-- Hardening variant only: direct PUBLIC checks above must be false, and these must pass.
select has_function_privilege('anon', 'public.replace_holdings_v1(jsonb)', 'execute') = false;
select has_function_privilege('authenticated', 'public.replace_holdings_v1(jsonb)', 'execute') = false;
select has_function_privilege('anon', 'public.holdings_add_buy_v1(text,numeric,numeric,date,text)', 'execute') = false;
select has_function_privilege('authenticated', 'public.holdings_add_buy_v1(text,numeric,numeric,date,text)', 'execute') = false;
select has_function_privilege('service_role', 'public.replace_holdings_v1(jsonb)', 'execute');
select has_function_privilege('service_role', 'public.holdings_add_buy_v1(text,numeric,numeric,date,text)', 'execute');
```

The effective `replace_holdings_v1` definition must contain `lock table public.holdings in share row exclusive mode` and, in Phase A only, the temporary non-null-write rejection message. The effective `holdings_add_buy_v1` definition must not contain `p_entry_pattern`, and the effective migration must not have used `DROP FUNCTION` for either holdings RPC because dropping before recreating can reset default execute privileges to `PUBLIC`. SQL privilege checks for literal roles do not replace the deployed-secret PostgREST smoke above. Service-role-capable PostgREST/RPC calls to `holdings_add_buy_v1` and read-only definition/privilege checks for `replace_holdings_v1` must succeed with the deployed runtime secret. In the default path, anon/authenticated PostgREST calls must match the recorded pre-migration effective posture; in a hardening variant, anon/authenticated calls must fail. Do not satisfy this by executing `replace_holdings_v1` against target holdings with a partial payload. If the audit kept `REVOKE ... FROM PUBLIC`, the migration must include it for both RPCs so future roles do not inherit execute accidentally; if the audit deferred the hardening, keep new service-role-only grant/revoke changes out of the Phase A completion checklist and cover them in the later DB-hardening release.

Run the Phase A release quality gate before the Phase A commit/release because this phase adds Python tests and docs, not only SQL:

```bash
just quality
```

If pinned tools are not available on `PATH`, rerun through mise:

```bash
mise exec -- just quality
```

If no executable DB target is available, do not mark the migration fully verified; record that only static SQL contract tests ran and keep final verification blocked until an executable migration apply is completed. If `just quality` cannot be run, record the exact blocker and at minimum run the focused pytest plus `ruff`/`mypy` fallback before release.

STOP after this step. Do not continue to Step 5 runtime files in the same autonomous implementation run, do not stage runtime tests/fixtures, and do not deploy code containing `entry_pattern` PostgREST selects/bodies until the DB-only migration has been applied to the target database and the SQL plus deployed-secret PostgREST smoke evidence is recorded. Start a separate runtime plan/PR after this evidence exists; copy the Phase B checklist there instead of treating the remaining Step 5+ instructions as immediately executable work.

**Non-executable Phase B appendix:** Steps 5-9 below are retained only as reviewed requirements for the future dedicated runtime plan. Do not execute, stage, or commit them from this Phase A task. When Phase A target smoke is complete, copy the relevant checklist into a new runtime plan and remove this appendix from the active execution path.

### Phase B Appendix Step 5: Add `entry_pattern` to scheduled holdings export paths

Before editing runtime selectors, create the runtime enablement migration (for example `supabase/migrations/20260609010000_enable_holdings_entry_pattern_writes.sql`). It must drop `holdings_entry_pattern_write_closed_check` and recreate `replace_holdings_v1` without the temporary `incoming holdings entry_pattern writes are disabled until runtime export paths own entry_pattern` guard while keeping the holdings table lock, preserve-on-omit logic, entry-identity/strategy omitted-key rejection, value/length/type validation, active-row invariant, and existing privilege posture. Apply and smoke this enablement migration before any runtime `entry_pattern` select/body can run; otherwise runtime rollout remains blocked.

In `sab/scheduler/holdings.py`, add the field to `_HOLDINGS_FIELDS` immediately after `strategy`:

```python
    "strategy",
    "entry_pattern",
    "notes",
```

The syntax prerequisite check from Step 1 should already be complete. If `UV_CACHE_DIR=.uv-cache uv run python -m py_compile sab/scheduler/holdings.py sab/sell_evaluation.py` fails on the active toolchain, fix only that parse blocker before editing the export field list; otherwise scheduled export tests can fail before exercising the `entry_pattern` contract.

Update `_normalize_rows` so it still omits `None` for legacy optional fields, but always writes an owned `entry_pattern` key when the field is present in the Supabase response, including `None` values. If the runtime projection ever omits the selected `entry_pattern` key, fail loudly instead of turning a missing projection into an explicit clearing snapshot:

```python
            if field_name == "entry_pattern":
                if field_name not in raw:
                    raise SupabaseHoldingsExportError(
                        "Supabase holdings response omitted entry_pattern"
                    )
                item[field_name] = value
            elif value is not None:
                item[field_name] = value
```

This keeps scheduled generated holdings files aligned with the export contract: current DB snapshots clear stale markers with `entry_pattern: null`, while parser/import/replace-all payloads may still omit the key to preserve existing DB values.

In `.github/workflows/sell.yml`, update the inline Supabase query:

```bash
query="select=ticker,quantity,entry_price,entry_currency,entry_date,strategy,entry_pattern,notes,tags,stop_override,target_override&quantity=gt.0&order=ticker.asc"
```

In the same workflow step, add `entry_pattern` to the Python `keys` tuple immediately after `strategy`:

```python
              "strategy",
              "entry_pattern",
              "notes",
```

Then change the inline serializer loop so it keeps explicit null only for `entry_pattern`, and fails loudly if the selected response omits that key. Keep the `value = row.get(key)` assignment in the loop before the null check:

```python
                  value = row.get(key)
                  if key == "entry_pattern" and key not in row:
                      raise SystemExit("Supabase holdings response omitted entry_pattern")
                  if value is None and key != "entry_pattern":
                      continue
                  item[key] = value
```

Apply the same query, `keys` tuple, and null-preserving loop change to `.github/workflows/ai-brief.yml` in its manual `Load holdings from Supabase` step. Both workflows currently write JSON syntax to generated holdings files; keep that shape unchanged because JSON is valid YAML. Scheduled AI Brief coverage still comes from `sab/scheduler/holdings.py` through `sab ai-brief-scheduled`, so keep the Python scheduler export tests as the scheduled-path proof.

### Phase B Appendix Step 6: Wire web Supabase types, mutation schemas, and replace-all payload

In `web/src/lib/types.ts`, add `entry_pattern` after `strategy` in `HoldingRecord` and `HoldingSnapshot`:

```ts
entry_pattern: string | null;
```

For `HoldingMutationInput`, add:

```ts
entry_pattern?: string | null;
```

Create a tiny shared TypeScript helper instead of redeclaring allowed values in every web module:

```ts
export const HOLDING_ENTRY_PATTERN_VALUES = [
  "trend_pullback_bounce",
  "swing_high_breakout",
  "rsi_oversold_reversal",
] as const;

export type HoldingEntryPattern =
  (typeof HOLDING_ENTRY_PATTERN_VALUES)[number];

export const HOLDING_ENTRY_PATTERNS = new Set<string>(
  HOLDING_ENTRY_PATTERN_VALUES,
);

export function isHoldingEntryPattern(
  value: string,
): value is HoldingEntryPattern {
  return HOLDING_ENTRY_PATTERNS.has(value);
}
```

Use this helper from `web/src/lib/schemas.ts` in the same runtime release. Add `entry_pattern` to both `holdingCreateSchema` and `holdingPatchSchema` after `strategy`, trimming strings, converting blank to `null`, accepting explicit `null`, enforcing the 120-character limit, and rejecting values outside the shared allowed set. This schema change must ship with the first web runtime that can persist `entry_pattern`; otherwise strict create/patch schemas reject the new public contract even though the Supabase adapter can store it. Keep `holdingAddBuySchema.strict()` unchanged so Add Buy continues to reject marker inputs.

Also add a replace/import snapshot type that preserves missing-vs-null semantics:

```ts
export type HoldingReplaceSnapshot = Omit<HoldingSnapshot, "entry_pattern"> & {
  entry_pattern?: string | null;
};
```

Use this type for `replaceAllHoldings` and YAML import helpers. Keep `HoldingRecord` and ordinary `HoldingSnapshot` required-nullable so fetched DB rows and exported current holdings have a stable shape.

In `web/src/lib/supabase/holdings.ts`, update `HOLDINGS_SELECT`:

```ts
const HOLDINGS_SELECT =
  "ticker,quantity,entry_price,entry_currency,entry_date,strategy,entry_pattern,notes,tags,stop_override,target_override,created_at,updated_at";
```

Change `replaceAllHoldings` to accept `HoldingReplaceSnapshot[]`. Include the field only if the incoming row owns the key:

```ts
        const payloadRow: Record<string, unknown> = {
          ticker: row.ticker,
          quantity: row.quantity,
          entry_price: row.entry_price,
          entry_currency: row.entry_currency,
          entry_date: row.entry_date,
          strategy: row.strategy,
          notes: row.notes,
          tags: row.tags,
          stop_override: row.stop_override,
          target_override: row.target_override,
        };
        if (
          Object.prototype.hasOwnProperty.call(row, "entry_pattern") &&
          row.entry_pattern !== undefined
        ) {
          payloadRow.entry_pattern = row.entry_pattern;
        }
        return payloadRow;
```

New create/update callers can send `entry_pattern` explicitly through the normal mutation schemas added in this task. Add `normalizeHoldingMutationForPersistence` in `web/src/lib/holding-mutation.ts`, cover it in `web/src/lib/__tests__/holding-mutation.test.ts`, and use it both at public callers before invoking the adapter and inside the exported Supabase adapter before serializing PostgREST/RPC bodies. `createHolding`, `updateHolding`/`patchHoldingByExactTicker`, and `replaceAllHoldings` must not trust callers to have normalized the invariant already. Replace-all callers must preserve key presence: `entry_pattern: null` intentionally clears the field, `entry_pattern: undefined` is treated like omission, and omitting the key preserves the existing DB value through the DB-level compatibility behavior only while the resulting row remains active. When the row becomes inactive (`quantity = 0`), the outbound payload must own `entry_pattern: null`; do not leave this to form-layer behavior or to a later Task 3 checkpoint.

Pull the full `web/src/lib/holdings-yaml.ts` optional-key implementation from Task 3 into this Phase B checkpoint. Do not add a temporary implementation that collapses omitted YAML `entry_pattern` into `null`. The parser, export, diff, YAML route pass-through, and YAML-focused tests are part of the first runtime release because `HoldingSnapshot.entry_pattern` is required-nullable for current DB snapshots.

### Phase B Appendix Step 7: Run Supabase contract tests

Run:

```bash
# Runtime plan example only; do not execute from Task 2 Phase A:
# UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_entry_pattern_contract.py tests/test_scheduled_holdings_export.py tests/test_workflow_holdings_loading.py -q
# pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/supabase-admin.test.ts
# pnpm --dir web run test -- web/src/lib/__tests__/holding-mutation.test.ts
# pnpm --dir web run test -- web/src/app/actions/__tests__/holdings.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[ticker]/__tests__/route.integration.test.ts" "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts" "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.integration.test.ts" "web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts"
# pnpm --dir web run test -- web/src/lib/__tests__/holdings-yaml.test.ts web/src/app/api/holdings/yaml/__tests__/route.test.ts
```

Expected: PASS. The Add Buy negative tests may already pass before implementation because the current strict Add Buy schema rejects unknown keys; their purpose is to lock the quantity-only API contract. YAML tests are required in Phase B, not conditional, because this runtime release changes the DB/current snapshot shape and replace-all import semantics.

### Phase B Appendix Step 8: Sweep web fixture fallout and typecheck

Update every `HoldingRecord` or ordinary `HoldingSnapshot` fixture surfaced by these commands to include `entry_pattern: null` or a specific test value, and include every edited fixture file in this task's commit. Fixtures intended to model old YAML import input may use `HoldingReplaceSnapshot` and omit `entry_pattern` deliberately:

```bash
# Runtime plan example only; do not execute from Task 2 Phase A:
# rg -n "HoldingRecord|HoldingSnapshot|HoldingReplaceSnapshot|strategy: null|strategy: \"swing\"" web/src web/src/lib/__tests__
# pnpm --dir web run typecheck
```

Expected: `rg` identifies only reviewed fixture locations, and `pnpm --dir web run typecheck` passes after those fixtures and the full YAML optional-key implementation are present. Do not satisfy typecheck by temporarily normalizing omitted import keys to `null`. At minimum, check these existing fixture-heavy tests: `web/src/lib/__tests__/holding-activity.test.ts`, `web/src/lib/__tests__/add-buy-precheck.test.ts`, `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, `web/src/app/actions/__tests__/holdings.test.ts`, `web/src/app/api/holdings/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/__tests__/route.integration.test.ts`, `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`, `web/src/app/api/holdings/yaml/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.integration.test.ts`, and `web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts`.

Before staging the runtime commit, also run the Task 5 static docs check for the docs promoted into this boundary. The first deployed runtime that exposes `entry_pattern` must not leave `docs/STRATEGY.md`, `docs/api.md`, `docs/holdings-schema.md`, `docs/holdings-add-buy.md`, `docs/adr/ADR-0010-holdings-add-buy.md`, or scheduler docs describing the old `strategy`/`tags`-only contract.

### Phase B Appendix Step 9: Commit Supabase contract

Use two deployable PRs/releases by default. First commit/PR only the migration and DB/static contract tests, then apply and smoke the migration against the target database. After that smoke is recorded and the DB-only release is live, commit/deploy the runtime select/body/export/schema changes. The Phase B runtime release must include the public route/action deactivation normalization described above before any runtime can expose `entry_pattern` writes: parsed payloads that own `quantity === 0` must persist `entry_pattern: null`. If the form-layer deactivation clear from Task 3 is not pulled into this runtime commit, deploy Task 2 Phase B and Task 3 as a single runtime boundary rather than shipping a UI that can still omit the null clear. If the runtime release exposes or relies on the normal holdings create/edit UI, also pull Task 4 recent-candidate propagation into the same deployable runtime boundary; otherwise clicking a recent buy candidate still drops the source buy `pattern` and the main goal remains unsatisfied. A single combined deployable change is allowed only if a reviewed deployment automation guarantees migrations apply before runtime execution. Do not treat two commits in one unreviewed deployable PR as a deployment boundary.

```bash
# Runtime plan example only; do not execute from Task 2 Phase A until the DB-only implementation plan is active:
# git add supabase/migrations/20260609000000_add_holdings_entry_pattern.sql tests/test_holdings_entry_pattern_contract.py scripts/smoke_holdings_entry_pattern.sql docs/holdings-add-buy.md docs/adr/ADR-0010-holdings-add-buy.md
# git commit -m "feat(db): 보유 종목 진입 패턴 컬럼 추가" -m "holdings.entry_pattern 컬럼과 replace_holdings_v1 보존 계약을 추가한다. 런타임 select 변경은 DB 적용 smoke 이후 별도 커밋에서 진행한다."

# STOP: apply/release the DB-only migration and record SQL + PostgREST smoke evidence.
# Do not run the runtime git add below from this plan. Copy the Phase B checklist
# into a dedicated runtime plan/PR only after the DB target smoke evidence exists.
# Include `tests/test_holdings_entry_pattern_contract.py` again in that runtime
# plan if the Phase B cross-language drift guard is added there after
# `web/src/lib/holding-entry-pattern.ts` exists.
# Runtime plan example only; do not execute from Task 2 Phase A:
# git add supabase/migrations/20260609010000_enable_holdings_entry_pattern_writes.sql sab/scheduler/holdings.py .github/workflows/sell.yml .github/workflows/ai-brief.yml tests/test_holdings_entry_pattern_contract.py tests/test_scheduled_holdings_export.py tests/test_workflow_holdings_loading.py web/src/lib/types.ts web/src/lib/holding-entry-pattern.ts web/src/lib/holding-mutation.ts web/src/lib/schemas.ts web/src/lib/supabase/holdings.ts web/src/lib/holdings-yaml.ts web/src/lib/ticker-directory.ts web/src/app/actions/holdings.ts web/src/app/api/holdings/route.ts "web/src/app/api/holdings/[ticker]/route.ts" "web/src/app/api/holdings/[...ticker]/route.ts" web/src/components/holdings/use-ticker-lookup.ts web/src/components/holdings/use-recent-candidates.ts web/src/components/holdings/holdings-form-panel.tsx web/src/components/holdings-client.tsx web/src/components/holdings-client.module.css web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/holding-mutation.test.ts web/src/lib/__tests__/supabase-admin.test.ts web/src/lib/__tests__/holdings-yaml.test.ts web/src/lib/__tests__/holding-activity.test.ts web/src/lib/__tests__/add-buy-precheck.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/lib/__tests__/ticker-directory.test.ts web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[ticker]/__tests__/route.integration.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts" web/src/app/api/holdings/yaml/route.ts web/src/app/api/holdings/yaml/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts" "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.integration.test.ts" "web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts" web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts docs/holdings-schema.md docs/holdings-add-buy.md docs/STRATEGY.md docs/api.md docs/configuration.md docs/config-reference.md docs/local-docker-scheduler-plan.md docs/ARCHITECTURE.md docs/holdings-ticker-lookup.md docs/adr/ADR-0008-holdings-ticker-directory.md docs/adr/ADR-0010-holdings-add-buy.md
# git commit -m "feat(holdings): 진입 패턴 런타임 저장 경로 연결" -m "DB 적용 이후 scheduled export와 웹 Supabase 클라이언트가 entry_pattern을 선택·보존하도록 확장한다."
```

## Runtime Reference Task 3: Web Form, Table, And Remaining UI (Non-Executable)

**Files:**
- Do not edit in Task 3; Task 2 Phase B owns parser/export/diff semantics: `web/src/lib/holdings-yaml.ts`
- Modify: `web/src/components/holdings/form-state.ts`
- Modify: `web/src/components/holdings/helpers.ts`
- Modify: `web/src/components/holdings/holdings-form-panel.tsx`
- Modify: `web/src/components/holdings/holdings-table.tsx`
- Modify: `web/src/components/holdings/holdings-import-panel.tsx`
- Modify: `web/src/components/holdings/use-holdings-import.ts`
- Modify: `web/src/components/holdings-client.module.css`
- Do not edit in Task 3; Task 2 Phase B owns YAML tests: `web/src/lib/__tests__/holdings-yaml.test.ts`
- Test: `web/src/app/actions/__tests__/holdings.test.ts`
- Test: `web/src/app/api/holdings/__tests__/route.test.ts`
- Test: `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`
- Test: `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`
- Do not edit in Task 3; Task 2 Phase B owns YAML route tests: `web/src/app/api/holdings/yaml/__tests__/route.test.ts`
- Test: `web/src/lib/__tests__/holdings-client-hooks.test.tsx`

- **Reference Step 1: Write failing web route pass-through and UI tests**

Schema create/patch validation, persistence normalization, marker-only API/action rejection, and YAML parser/export/diff behavior were added in Task 2 with the first web runtime persistence release. Do not duplicate those API/action contract tests here. Task 3 owns the remaining UI/form/table/import-copy tests and only revisits YAML helpers if Task 2 deliberately left a reviewed follow-up that does not affect deployable runtime correctness.

If Task 2 Phase B did not already carry the promoted YAML implementation for an intentionally documented reason, stop and move this YAML subsection back into Task 2 before deploying runtime. Task 3 must not write or run YAML helper/route tests as new work.

**Non-executable YAML appendix:** the following YAML notes are retained only as Task 2 Phase B acceptance criteria for the future dedicated runtime plan. Do not apply, stage, or run them from Task 3. If they are still needed when a worker reaches Task 3, the runtime plan is incomplete and must be fixed before continuing.

In `web/src/lib/__tests__/holdings-yaml.test.ts`, update `snapshot(...)` to include:

```ts
entry_pattern: overrides.entry_pattern ?? null,
```

Update the first round-trip test TSLA input:

```ts
        strategy: "sma_ema_hybrid",
        entry_pattern: "swing_high_breakout",
        tags: ["leader"],
```

Update the expected TSLA snapshot:

```ts
        strategy: "sma_ema_hybrid",
        entry_pattern: "swing_high_breakout",
        tags: ["leader"],
```

Add fail-closed YAML import regressions in the same file:

```ts
it("rejects non-string entry_pattern values", () => {
  expect(() =>
    parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
    entry_pattern:
      - swing_high_breakout
`),
  ).toThrow(/entry_pattern.*string/);
});

it("rejects overlong entry_pattern values", () => {
  const overlong = "x".repeat(121);

  expect(() =>
    parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
    entry_pattern: ${overlong}
`),
  ).toThrow(/entry_pattern.*120/);
});

it("rejects unknown entry_pattern values", () => {
  expect(() =>
    parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
    entry_pattern: not_a_breakout
`),
  ).toThrow(/entry_pattern.*one of/);
});
```

Add an export regression before the diff tests so generated backups keep explicit null ownership: build YAML from a `HoldingSnapshot` whose `entry_pattern` is `null`, assert the document contains `entry_pattern: null`, parse it back, and assert the parsed row owns `entry_pattern` with `null`. This prevents a generated backup from turning a cleared value into an old-style preserve-on-omit import.

Add a diff regression so YAML apply does not skip `entry_pattern`-only changes:

```ts
it("treats entry_pattern-only differences as updates", () => {
  const summary = buildHoldingsYamlImportSummary(
    [
      record({
        ticker: "AAPL.NAS",
        quantity: 1,
        entry_price: 100,
        entry_currency: "USD",
        entry_pattern: null,
      }),
    ],
    [
      snapshot({
        ticker: "AAPL.NAS",
        quantity: 1,
        entry_price: 100,
        entry_currency: "USD",
        entry_pattern: "swing_high_breakout",
      }),
    ],
  );

  expect(summary).toEqual({
    incomingCount: 1,
    createCount: 0,
    updateCount: 1,
    deleteCount: 0,
    unchangedCount: 0,
    createTickers: [],
    updateTickers: ["AAPL.NAS"],
    deleteTickers: [],
  });
});
```

Add three compatibility regressions that distinguish an omitted YAML key from explicit clears. First, old YAML that omits `entry_pattern` must not count as an update against a current DB row that already has an `entry_pattern`:

```ts
it("treats omitted entry_pattern as preserve-existing for an active row during YAML diff", () => {
  const incoming = parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
`);
  expect(Object.prototype.hasOwnProperty.call(incoming[0], "entry_pattern")).toBe(
    false,
  );

  const summary = buildHoldingsYamlImportSummary(
    [
      record({
        ticker: "AAPL.NAS",
        quantity: 1,
        entry_price: 100,
        entry_currency: "USD",
        entry_pattern: "swing_high_breakout",
      }),
    ],
    incoming,
  );

  expect(summary.updateCount).toBe(0);
  expect(summary.unchangedCount).toBe(1);
});
```

Add the entry-identity/strategy exception immediately after that preserve case. Old YAML that omits `entry_pattern` but changes `entry_price`, `entry_date`, or `strategy` on an existing active row with a non-null `entry_pattern` must not be treated as a harmless preserve. The diff/apply path should fail before `replaceAllHoldings` with an actionable error such as `entry_pattern must be explicit when entry identity or strategy changes`, or report a validation error that blocks apply. Add explicit-null and explicit-value counterparts proving the operator can intentionally clear or set the marker while changing entry identity or thesis.

Then add the explicit-null clear counterpart:

```ts
it("treats explicit null entry_pattern as a clear during YAML diff", () => {
  const incoming = parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
    entry_pattern: null
`);
  expect(Object.prototype.hasOwnProperty.call(incoming[0], "entry_pattern")).toBe(
    true,
  );

  const summary = buildHoldingsYamlImportSummary(
    [
      record({
        ticker: "AAPL.NAS",
        quantity: 1,
        entry_price: 100,
        entry_currency: "USD",
        entry_pattern: "swing_high_breakout",
      }),
    ],
    incoming,
  );

  expect(summary.updateCount).toBe(1);
});
```

Add the blank/whitespace clear counterpart. Parse YAML with `entry_pattern: ""` and, if the YAML parser preserves quoted spaces in the local library version, also `entry_pattern: "   "`; assert the incoming row owns `entry_pattern` and the parsed value is `null`, then assert the diff treats it as an update against a current non-null `entry_pattern`. This closes the plan-level contract that blank string means clear, not preserve.

Add inactive-row import regressions in the same file. A YAML row with `quantity: 0` and omitted `entry_pattern` must parse without owning the key, but `buildHoldingsYamlImportSummary` should still treat it as an update against a current active row with non-null `entry_pattern` because apply will clear the marker when the DB row becomes inactive. A YAML row with `quantity: 0` and non-null `entry_pattern` must be rejected before it can reach `replaceAllHoldings`; do not normalize this explicit invalid marker into a clear. Omitted, blank, and explicit `null` are the only inactive-row clear inputs.

In `web/src/app/api/holdings/yaml/__tests__/route.test.ts`, account for the route's current `hasChanges` guard before asserting apply-path pass-through. Add one pure preserve-on-omit apply case where old YAML omits `entry_pattern`, the mocked/import summary has no create/update/delete changes, and `replaceAllHoldings` is **not** called. Then add a separate active-row apply-path case with an independent non-entry-identity change such as `notes` or active `quantity` while still omitting `entry_pattern`; force the mocked summary to report an update, assert `replaceAllHoldings` is called, and assert the row it receives does not own `entry_pattern`. Add the entry-identity/strategy exception route regression too: YAML that omits `entry_pattern` while changing `entry_price`, `entry_date`, or `strategy` on an existing active row with a non-null marker must return 400 or another apply-blocking validation response and must not call `replaceAllHoldings`. Separately post `entry_pattern: null` and blank `entry_pattern` cases with update summaries and assert the row owns `entry_pattern` with `null`. Finally add a deactivation apply case where YAML sets `quantity: 0` while omitting `entry_pattern`; assert apply does not send a stale non-null marker and, if the route normalizes before calling `replaceAllHoldings`, the row owns `entry_pattern: null`. This catches route-level pass-through without contradicting the no-op apply behavior.

In `web/src/app/api/holdings/__tests__/route.test.ts`, update the create payload assertion in `"creates holding with slash ticker symbol"`:

```ts
        entry_pattern: "swing_high_breakout",
```

and include it in the request payload:

```ts
        entry_pattern: "swing_high_breakout",
```

In `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`, add this PATCH regression inside `describe("PATCH /api/holdings/[ticker] route", ...)`:

```ts
it("passes entry_pattern through active patch payload", async () => {
  vi.mocked(updateHolding).mockResolvedValueOnce({
    ticker: "005930",
    quantity: 3,
    entry_price: 70000,
    entry_currency: null,
    entry_date: null,
    strategy: "sma_ema_hybrid",
    entry_pattern: "swing_high_breakout",
    notes: null,
    tags: [],
    stop_override: null,
    target_override: null,
    created_at: "2026-02-20T00:00:00Z",
    updated_at: "2026-02-20T00:00:00Z",
  });

  const response = await PATCH(
    makePatchRequest({ quantity: 3, entry_pattern: " swing_high_breakout " }),
    makeContext("005930"),
  );

  expect(response.status).toBe(200);
  expect(vi.mocked(updateHolding)).toHaveBeenCalledWith("005930", {
    quantity: 3,
    entry_pattern: "swing_high_breakout",
  });
});
```

Do not add marker-only non-null API route rejection tests here if Task 2 already added them. Task 2 is authoritative for API/action schema and persistence-normalization tests; Task 3 should only keep route pass-through tests that are needed to prove UI-facing payloads still use the server contract.

In `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`, update the segmented PATCH test payload and expectation:

```ts
const response = await PATCH(
  makePatchRequest({ quantity: 3, entry_pattern: "swing_high_breakout" }),
  {
    params: { ticker: ["BRK", "B.NYS"] },
  },
);

expect(vi.mocked(updateHolding)).toHaveBeenCalledWith("BRK.B.NYS", {
  quantity: 3,
  entry_pattern: "swing_high_breakout",
});
```

In `web/src/app/actions/__tests__/holdings.test.ts`, add server-action pass-through coverage because the Holdings UI saves through `saveHoldingAction`, not through the API routes. Update the create test or add a new one so a trimmed `entry_pattern` reaches `createHolding`:

```ts
await saveHoldingAction({
  editingTicker: null,
  payload: {
    ticker: "005930",
    quantity: 1,
    entry_price: 70000,
    entry_pattern: " swing_high_breakout ",
    tags: [],
  },
});

expect(createHolding).toHaveBeenCalledWith(
  expect.objectContaining({
    entry_pattern: "swing_high_breakout",
  }),
);
```

Add a patch clear regression in the same file:

```ts
await saveHoldingAction({
  editingTicker: "AAPL.NAS",
  payload: {
    entry_pattern: null,
  },
});

expect(updateHolding).toHaveBeenCalledWith("AAPL.NAS", {
  entry_pattern: null,
});
```

Do not duplicate marker-only non-null action negative tests or Add Buy marker rejection tests here if Task 2 already added them. Keep Task 2 as the single source of truth for server action/API rejection behavior, and use Task 3 action tests only when they prove a UI form path submits or clears the field correctly.

In the `HoldingsClient composition` describe block in `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, add a UI save-path regression. This catches a missing `entry_pattern` in `buildHoldingMutationPayload`, which TypeScript will not catch because mutation input fields are optional:

```ts
it("submits entry pattern from the holdings form", async () => {
  await act(async () => {
    root.render(
      React.createElement(HoldingsClient, {
        initialState: { items: [], hasMore: false, nextCursor: null },
      }),
    );
    await Promise.resolve();
  });

  const ticker = container.querySelector<HTMLInputElement>(
    'input[name="ticker"]',
  );
  const quantity = container.querySelector<HTMLInputElement>(
    'input[name="quantity"]',
  );
  const entryPrice = container.querySelector<HTMLInputElement>(
    'input[name="entryPrice"]',
  );
  const entryPattern = container.querySelector<HTMLSelectElement>(
    'select[name="entryPattern"]',
  );
  expect(ticker).not.toBeNull();
  expect(quantity).not.toBeNull();
  expect(entryPrice).not.toBeNull();
  expect(entryPattern).not.toBeNull();

  act(() => {
    ticker!.value = "AAPL.NAS";
    ticker!.dispatchEvent(new Event("input", { bubbles: true }));
    quantity!.value = "1";
    quantity!.dispatchEvent(new Event("input", { bubbles: true }));
    entryPrice!.value = "100";
    entryPrice!.dispatchEvent(new Event("input", { bubbles: true }));
    entryPattern!.value = "swing_high_breakout";
    entryPattern!.dispatchEvent(new Event("change", { bubbles: true }));
  });

  await act(async () => {
    container.querySelector("form")?.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await Promise.resolve();
  });

  expect(saveHoldingAction).toHaveBeenCalledWith({
    editingTicker: null,
    payload: expect.objectContaining({
      ticker: "AAPL.NAS",
      entry_pattern: "swing_high_breakout",
    }),
  });
});
```

Add an active-row edit-preservation regression in the same block. Render an active row with `quantity > 0` and `entry_pattern: "swing_high_breakout"`, click `Edit`, assert the `entryPattern` select is prefilled, change an unrelated field such as `notes`, submit, and assert the saved payload still includes the original `entry_pattern`. This catches `recordToForm` mapping mistakes that would clear the marker during ordinary active-position edits:

```ts
it("preserves entry pattern when editing another field", async () => {
  await act(async () => {
    root.render(
      React.createElement(HoldingsClient, {
        initialState: {
          items: [{ ...HOLDING, entry_pattern: "swing_high_breakout" }],
          hasMore: false,
          nextCursor: null,
        },
      }),
    );
    await Promise.resolve();
  });

  act(() => {
    findButton(container, "Edit").dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
  });

  const entryPattern = container.querySelector<HTMLSelectElement>(
    'select[name="entryPattern"]',
  );
  expect(entryPattern?.value).toBe("swing_high_breakout");

  const notes = container.querySelector<HTMLTextAreaElement>(
    'textarea[name="notes"]',
  );
  act(() => {
    notes!.value = "updated note";
    notes!.dispatchEvent(new Event("input", { bubbles: true }));
  });

  await act(async () => {
    container.querySelector("form")?.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    await Promise.resolve();
  });

  expect(saveHoldingAction).toHaveBeenCalledWith({
    editingTicker: HOLDING.ticker,
    payload: expect.objectContaining({
      notes: "updated note",
      entry_pattern: "swing_high_breakout",
    }),
  });
});
```

Add the deactivation counterpart in the same block. Render an active row with `entry_pattern: "swing_high_breakout"`, click `Edit`, change `quantity` to `0`, submit, and assert the saved payload owns `entry_pattern: null`. This proves the normal UI edit path enforces the active-position invariant instead of preserving a stale failed-breakout marker on an inactive row. If the implementation rejects deactivation through the generic edit path instead, assert the rejected UI/action behavior explicitly and keep Add Buy as the only reactivation path.

Add a small table rendering regression in the same describe block so the manual visual smoke is not the only coverage for the new metadata:

```ts
it("renders entry pattern metadata in the holdings table", async () => {
  await act(async () => {
    root.render(
      React.createElement(HoldingsClient, {
        initialState: {
          items: [{ ...HOLDING, entry_pattern: "swing_high_breakout" }],
          hasMore: false,
          nextCursor: null,
        },
      }),
    );
    await Promise.resolve();
  });

  expect(container.textContent).toContain(
    "Entry Pattern: swing_high_breakout",
  );
});
```

- **Reference Step 2: Run targeted web tests to verify failure**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# pnpm --dir web run test -- web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts"
```

Expected: FAIL because the import panel and apply-confirmation copy still need the reviewed YAML-contract warning, and the form/table do not expose or submit the field yet. YAML parser/export/diff behavior and strict create/patch schema acceptance were already covered in Task 2 Phase B.

- **Reference Step 3: Verify YAML helpers were completed in Task 2**

Task 3 must not introduce YAML parser/export/diff behavior. Verify the Task 2 Phase B runtime commit already used the shared `web/src/lib/holding-entry-pattern.ts` helper for all web-side `entry_pattern` validation and did not redeclare the allowed set in this module. If any item below is still incomplete, stop and move the missing YAML work back to Task 2 Phase B before deploying runtime. The snippets below are verification targets for the earlier runtime plan, not permission to edit YAML files during Task 3.

In `web/src/lib/holdings-yaml.ts`, import `HoldingReplaceSnapshot` from `web/src/lib/types.ts`, then add this stricter parser near `parseOptionalText`. Keep `parseOptionalText` unchanged for legacy fields because changing `strategy`/`notes` coercion would be a broader behavior change:

```ts
function parseOptionalStringField(
  value: unknown,
  fieldName: string,
  context: string,
  maxLength: number,
): string | null {
  if (value == null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new HoldingsYamlError(`${context}: '${fieldName}' must be a string.`);
  }
  const text = value.trim();
  if (!text) {
    return null;
  }
  if (text.length > maxLength) {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be <= ${maxLength} characters.`,
    );
  }
  if (!isHoldingEntryPattern(text)) {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be one of ${HOLDING_ENTRY_PATTERN_VALUES.join(", ")}.`,
    );
  }
  return text;
}
```

Import `isHoldingEntryPattern` and `HOLDING_ENTRY_PATTERN_VALUES` from `web/src/lib/holding-entry-pattern.ts` for validation and error text. Do not introduce a second local allowed set.

Update `toHoldingSnapshot`:

```ts
    entry_pattern: record.entry_pattern ?? null,
```

Task 2 should not have added a temporary parser/diff workaround. If Task 2 had to touch this file for typecheck, it should already contain the full optional-key implementation described here; keep that implementation and continue with the remaining schema/form/table changes below.

Change the YAML import-facing function signatures to make the optional-key contract explicit:

```ts
export function parseHoldingsYamlDocument(document: string): HoldingReplaceSnapshot[]

export function buildHoldingsYamlImportSummary(
  currentHoldings: readonly HoldingRecord[],
  incomingHoldings: readonly HoldingReplaceSnapshot[],
): HoldingsYamlImportSummary
```

Add a key-presence helper:

```ts
function hasOwnEntryPattern(
  snapshot: HoldingReplaceSnapshot,
): snapshot is HoldingReplaceSnapshot & { entry_pattern: string | null } {
  return Object.prototype.hasOwnProperty.call(snapshot, "entry_pattern");
}
```

Update `buildYamlRow` after strategy. This function is used for generated exports, so it must always write the owned DB snapshot value, including explicit `null`:

```ts
  row.entry_pattern = snapshot.entry_pattern ?? null;
```

Update `areSnapshotsEqual`:

```ts
    (!hasOwnEntryPattern(right) ||
      left.entry_pattern === right.entry_pattern) &&
```

Do not convert incoming YAML rows with `toHoldingSnapshot` before diffing; that would collapse an omitted `entry_pattern` into `null`. `buildHoldingsYamlImportSummary` should normalize current DB rows with `toHoldingSnapshot`, keep incoming rows as `HoldingReplaceSnapshot`, and compare with the key-presence helper above.

Before returning the summary, validate the omitted-key entry-identity/strategy exception for active existing rows. If `right` omits `entry_pattern`, `left.entry_pattern` is non-null, both rows are active, and `entry_price`, `entry_date`, or `strategy` changed, throw `HoldingsYamlError` with wording that includes `entry_pattern` and `entry identity` or `strategy` (or equivalent Korean copy in UI-facing text). Do this before calling `replaceAllHoldings`, so dry-run/apply feedback is actionable and the web path does not rely on the DB RPC as the first validator:

```ts
function assertEntryPatternExplicitForEntryIdentityChange(
  current: HoldingSnapshot,
  incoming: HoldingReplaceSnapshot,
): void {
  if (
    hasOwnEntryPattern(incoming) ||
    current.entry_pattern == null ||
    current.quantity <= 0 ||
    incoming.quantity <= 0
  ) {
    return;
  }
  if (
    current.entry_price === incoming.entry_price &&
    current.entry_date === incoming.entry_date &&
    current.strategy === incoming.strategy
  ) {
    return;
  }
  throw new HoldingsYamlError(
    `${incoming.ticker}: entry_pattern must be explicit when entry identity or strategy changes.`,
  );
}
```

Update `parseHoldingsYamlDocument` snapshot construction after strategy so it only owns `entry_pattern` when the YAML row owns the key:

```ts
      const snapshot: HoldingReplaceSnapshot = {
        // existing fields...
      };
      if (Object.prototype.hasOwnProperty.call(row, "entry_pattern")) {
        snapshot.entry_pattern = parseOptionalStringField(
          row.entry_pattern,
          "entry_pattern",
          context,
          120,
        );
      }
      return snapshot;
```

- **Reference Step 4: Update form state, payload helpers, import copy, and UI**

In `web/src/components/holdings/form-state.ts`, add:

```ts
  entry_pattern: string;
```

and default it to empty:

```ts
    entry_pattern: "",
```

In `web/src/components/holdings/helpers.ts`, update `recordToForm`:

```ts
    entry_pattern: record.entry_pattern ?? "",
```

Update `buildHoldingMutationPayload` after `strategy`:

```ts
    entry_pattern:
      Number(form.quantity) === 0 ? null : stringOrNull(form.entry_pattern),
```

Use the same quantity-zero guard in any route/action mutation helper that bypasses `buildHoldingMutationPayload`. A disabled or hidden select is not enough; the outbound payload must carry `entry_pattern: null` when a normal holdings edit deactivates a row, so the DB constraint and scheduled export contract remain aligned.

In `web/src/components/holdings/holdings-form-panel.tsx`, import `HOLDING_ENTRY_PATTERN_VALUES` from `web/src/lib/holding-entry-pattern.ts` and add this label after the Strategy input. Use a select/menu instead of free-form text because `entry_pattern` is an enum-like field, but render the options from the shared allowlist instead of hardcoding them:

```tsx
        <label>
          Entry Pattern
          <select
            name="entryPattern"
            value={form.entry_pattern}
            onChange={(event) =>
              onFieldChange("entry_pattern", event.target.value)
            }
          >
            <option value="">None</option>
            {HOLDING_ENTRY_PATTERN_VALUES.map((pattern) => (
              <option key={pattern} value={pattern}>
                {pattern}
              </option>
            ))}
          </select>
        </label>
```

In `web/src/components/holdings-client.module.css`, include `.form select` in the same sizing, border, font, and focus-visible rules as `.form input` and `.form textarea`. The Entry Pattern control should not rely on unstyled native select defaults, and the visual smoke should check focus/readability as well as overlap.

In `web/src/components/holdings/holdings-import-panel.tsx`, update the explanatory copy so it still says apply replaces the holdings snapshot, but explicitly notes that omitted `entry_pattern` in older YAML preserves the existing DB value only while that row remains active, and `entry_pattern: null`, blank, or `quantity: 0` clears it. Keep this concise; it is an operational warning, not a tutorial.

In `web/src/components/holdings/use-holdings-import.ts`, update the apply confirmation string for the same contract. The confirmation must not say the DB is literally replaced by the uploaded file without qualification. In `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, extend the existing `useHoldingsImport` apply test to assert `confirm.mock.calls[0]?.[0]` contains `entry_pattern`, `preserve`/`보존`, active-row wording, and `null`, `blank`/`빈 값`, or `quantity = 0` clear wording.

In `web/src/components/holdings/holdings-table.tsx`, keep the holdings row dense and scannable. The current table has a Tags column but no Strategy column, so do not add a new Strategy or Entry Pattern column in this task. Show `entry_pattern` as a secondary line inside the Tags cell:

```tsx
                    <td data-label="Tags">
                      {row.tags.join(", ") || "-"}
                      {row.entry_pattern && (
                        <span className={styles.entryPatternMeta}>
                          Entry Pattern: {row.entry_pattern}
                        </span>
                      )}
                    </td>
```

If using the secondary-line fallback, add a block-level CSS class so the metadata does not cram into the nowrap table line:

```css
.entryPatternMeta {
  display: block;
  margin-top: var(--space-1);
  color: var(--ink-muted);
  font-size: 0.8rem;
  line-height: 1.35;
  white-space: normal;
  overflow-wrap: anywhere;
}
```

- **Reference Step 5: Run targeted web tests**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# pnpm --dir web run test -- web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts"
```

Expected: PASS.

- **Reference Step 6: Run holdings UI smoke check**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# pnpm --dir web run typecheck
```

If a local web target is available, open `/holdings` at desktop and mobile widths and verify the Entry Pattern display is visible without overlapping Tags, Updated, or Action controls. Use the running `sab-web` container at `http://127.0.0.1:${WEB_HOST_PORT:-55300}` when available; otherwise record that visual smoke is deferred to Final Verification.

Expected: typecheck passes, and the holdings table/form remains readable at both widths. The Entry Pattern control is a select/menu with the empty value plus the three allowed pattern IDs, so users cannot create schema-invalid values from the normal UI.

- **Reference Step 7: Commit web holdings surface**

```bash
# Runtime plan example only; do not execute from this plan:
# git add web/src/components/holdings/form-state.ts web/src/components/holdings/helpers.ts web/src/components/holdings/holdings-form-panel.tsx web/src/components/holdings/holdings-table.tsx web/src/components/holdings/holdings-import-panel.tsx web/src/components/holdings/use-holdings-import.ts web/src/components/holdings-client.module.css web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts"
# git commit -m "feat(web): 보유 종목 진입 패턴 입력 추가" -m "웹 holdings 입력 화면과 YAML import/export 경로에서 entry_pattern을 보존한다."
```

## Runtime Reference Task 4: Recent Buy Candidate Pattern Propagation (Non-Executable)

Task 4 is non-executable from this DB-only plan, but it is not optional for the first user-facing runtime that claims automatic buy `pattern` preservation. When the Phase A stop gate is cleared, copy Task 2 Phase B, Task 3, and Task 4 into the same dedicated runtime plan unless the runtime release is intentionally limited to non-UI infrastructure and explicitly states that normal recent-candidate create/edit flows still require a follow-up. Do not close `TODOS.md` or claim that manual `strategy`/`tags` markers are no longer needed until this Task 4 boundary is deployed and verified.

**Files:**
- Modify: `web/src/lib/ticker-directory.ts`
- Modify: `web/src/components/holdings/use-ticker-lookup.ts`
- Modify: `web/src/components/holdings/use-recent-candidates.ts`
- Modify: `web/src/components/holdings/holdings-form-panel.tsx`
- Modify: `web/src/components/holdings-client.tsx`
- Modify if adding a new pattern metadata style: `web/src/components/holdings-client.module.css`
- Modify: `docs/holdings-ticker-lookup.md`
- Modify: `docs/adr/ADR-0008-holdings-ticker-directory.md`
- Test: `web/src/lib/__tests__/ticker-directory.test.ts`
- Test: `web/src/lib/__tests__/holdings-client-hooks.test.tsx`
- Test: `web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts`

- **Reference Step 1: Write failing recent-candidate tests**

In `web/src/lib/__tests__/ticker-directory.test.ts`, keep `"extracts ticker/name pairs and canonicalizes slash class ticker"` focused on ticker/name-only directory extraction. If the fixture row includes `pattern`, assert the directory candidate result still omits it:

```ts
expect(result[0]).toEqual({
  ticker: "BRK.B.NYS",
  name: "Berkshire Hathaway",
});
expect(result[0]).not.toHaveProperty("pattern");
```

Keep `"deduplicates ticker while keeping the first seen order"` pattern-free for directory extraction. Add separate recent-candidate tests under `listRecentBuyCandidates` for `pattern: null`, valid `pattern`, invalid-pattern normalization, and duplicate promotion.

Update the existing `listRecentBuyCandidates` test named `"returns first non-empty recent report candidates"` so candidates without report pattern explicitly expect `pattern: null`:

```ts
expect(result.candidates).toEqual([
  { ticker: "ABBV.NYS", name: "애브비", pattern: null },
  { ticker: "ETN.NYS", name: "이튼", pattern: null },
]);
```

Add this test in the `listRecentBuyCandidates` describe block:

```ts
it("returns pattern metadata for recent buy candidates", async () => {
  vi.mocked(fetchReportIndexPage).mockResolvedValueOnce(
    reportIndexPage([
      buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
    ]),
  );
  vi.mocked(downloadStorageJson).mockResolvedValueOnce({
    candidates: [
      {
        ticker: "AAPL.NAS",
        name: "Apple",
        pattern: "swing_high_breakout",
      },
    ],
  });

  const result = await listRecentBuyCandidates({
    limitReports: 1,
    limitCandidates: 5,
  });

  expect(result.candidates).toEqual([
    {
      ticker: "AAPL.NAS",
      name: "Apple",
      pattern: "swing_high_breakout",
    },
  ]);
});
```

In `web/src/components/holdings/use-ticker-lookup.ts` tests inside `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, update `"loads recent candidates on mount"` response:

```ts
        candidates: [
          {
            ticker: "aapl.nas",
            name: "Apple",
            pattern: "swing_high_breakout",
          },
        ],
```

and expected hook candidates:

```ts
      { ticker: "AAPL.NAS", name: "Apple", pattern: "swing_high_breakout" },
```

In `web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts`, update the mocked candidate and expected payload typing to include `pattern`, then assert:

```ts
    expect(payload.candidates[0]?.pattern).toBe("swing_high_breakout");
```

Add a negative extraction regression in `web/src/lib/__tests__/ticker-directory.test.ts` where a recent buy report row has `pattern: "not_a_breakout"`; assert the returned candidate has `pattern: null`. Recent-candidate UI should not forward unknown action-driving strings even though the report payload is internal.

Add duplicate-candidate merge regressions in the same file. Keep first-seen display order and first-seen ticker/name behavior, but if a later duplicate row for the same canonical ticker has the first valid `pattern`, promote that valid pattern onto the already-returned candidate. Cover both first row omitted/null then second row `pattern: "swing_high_breakout"`, and first row `pattern: "not_a_breakout"` then second row `pattern: "swing_high_breakout"`. This prevents the current first-seen dedupe behavior from discarding valid action-driving metadata when report rows contain duplicates.

Add client-boundary regressions in `web/src/lib/__tests__/holdings-client-hooks.test.tsx` for the recent-candidate parser or `useRecentCandidates`: when the API payload contains `{ ticker: "AAPL.NAS", name: "Apple", pattern: "not_a_breakout" }`, the parsed candidate must keep `ticker`/`name` but expose an owned `pattern: null`; when the API payload omits `pattern` entirely, the parsed recent candidate must still own `pattern: null`. This catches invalid or stale API payloads after server extraction has been bypassed while keeping the client recent-candidate shape stable.

This route test is pass-through coverage only because the route mocks `listRecentBuyCandidates`; do not count it as proof that report `pattern` survives extraction. The real extraction coverage must stay in `web/src/lib/__tests__/ticker-directory.test.ts`, and the client propagation coverage must stay in `web/src/lib/__tests__/holdings-client-hooks.test.tsx`.

In the `HoldingsClient composition` describe block in `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, add click-through regressions for recent candidate selection:

```ts
it("populates entry pattern when a recent candidate has pattern metadata", async () => {
  vi.mocked(globalThis.fetch as typeof fetch).mockResolvedValueOnce(
    jsonResponse({
      report: { key: "2026/03/report.buy.json", reportDate: "2026-03-02" },
      candidates: [
        {
          ticker: "msft.nas",
          name: "Microsoft",
          pattern: "swing_high_breakout",
        },
      ],
    }),
  );

  await act(async () => {
    root.render(
      React.createElement(HoldingsClient, {
        initialState: { items: [], hasMore: false, nextCursor: null },
      }),
    );
    await Promise.resolve();
    await Promise.resolve();
  });

  act(() => {
    findButton(container, "MSFT.NAS").dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
  });

  expect(
    container.querySelector<HTMLInputElement>('input[name="ticker"]')?.value,
  ).toBe("MSFT.NAS");
  expect(
    container.querySelector<HTMLSelectElement>('select[name="entryPattern"]')?.value,
  ).toBe("swing_high_breakout");
});
```

Add a render assertion to the populated-pattern test so the side effect is visible before click:

```ts
expect(container.textContent).toContain("Pattern: swing_high_breakout");
```

Add a manual-value stale-marker regression in the same block. A manual `entry_pattern` may be preserved only when the ticker identity stays the same; a no-pattern candidate that changes ticker must clear it so a marker chosen for one ticker is not saved on another:

```ts
it("clears a manual entry pattern when a no-pattern recent candidate changes ticker", async () => {
  vi.mocked(globalThis.fetch as typeof fetch).mockResolvedValueOnce(
    jsonResponse({
      report: { key: "2026/03/report.buy.json", reportDate: "2026-03-02" },
      candidates: [{ ticker: "msft.nas", name: "Microsoft", pattern: null }],
    }),
  );

  await act(async () => {
    root.render(
      React.createElement(HoldingsClient, {
        initialState: { items: [], hasMore: false, nextCursor: null },
      }),
    );
    await Promise.resolve();
    await Promise.resolve();
  });

  const entryPatternInput = container.querySelector<HTMLSelectElement>(
    'select[name="entryPattern"]',
  );
  expect(entryPatternInput).not.toBeNull();
  act(() => {
    entryPatternInput!.value = "trend_pullback_bounce";
    entryPatternInput!.dispatchEvent(new Event("change", { bubbles: true }));
  });

  act(() => {
    findButton(container, "MSFT.NAS").dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
  });

  expect(
    container.querySelector<HTMLInputElement>('input[name="ticker"]')?.value,
  ).toBe("MSFT.NAS");
  expect(
    container.querySelector<HTMLSelectElement>('select[name="entryPattern"]')?.value,
  ).toBe("");
});

it("preserves entry pattern when the user edits it after no-pattern candidate selection", async () => {
  vi.mocked(globalThis.fetch as typeof fetch).mockResolvedValueOnce(
    jsonResponse({
      report: { key: "2026/03/report.buy.json", reportDate: "2026-03-02" },
      candidates: [{ ticker: "msft.nas", name: "Microsoft", pattern: null }],
    }),
  );

  await act(async () => {
    root.render(
      React.createElement(HoldingsClient, {
        initialState: { items: [], hasMore: false, nextCursor: null },
      }),
    );
    await Promise.resolve();
    await Promise.resolve();
  });

  act(() => {
    findButton(container, "MSFT.NAS").dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
  });

  const entryPatternInput = container.querySelector<HTMLSelectElement>(
    'select[name="entryPattern"]',
  );
  act(() => {
    entryPatternInput!.value = "trend_pullback_bounce";
    entryPatternInput!.dispatchEvent(new Event("change", { bubbles: true }));
  });

  expect(
    container.querySelector<HTMLInputElement>('input[name="ticker"]')?.value,
  ).toBe("MSFT.NAS");
  expect(
    container.querySelector<HTMLSelectElement>('select[name="entryPattern"]')?.value,
  ).toBe("trend_pullback_bounce");
});

it("clears candidate-derived entry pattern when the next recent candidate has no pattern", async () => {
  vi.mocked(globalThis.fetch as typeof fetch).mockResolvedValueOnce(
    jsonResponse({
      report: { key: "2026/03/report.buy.json", reportDate: "2026-03-02" },
      candidates: [
        { ticker: "msft.nas", name: "Microsoft", pattern: "swing_high_breakout" },
        { ticker: "etn.nys", name: "Eaton", pattern: null },
      ],
    }),
  );

  await act(async () => {
    root.render(
      React.createElement(HoldingsClient, {
        initialState: { items: [], hasMore: false, nextCursor: null },
      }),
    );
    await Promise.resolve();
    await Promise.resolve();
  });

  act(() => {
    findButton(container, "MSFT.NAS").dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
  });
  expect(
    container.querySelector<HTMLSelectElement>('select[name="entryPattern"]')?.value,
  ).toBe("swing_high_breakout");

  act(() => {
    findButton(container, "ETN.NYS").dispatchEvent(
      new MouseEvent("click", { bubbles: true }),
    );
  });

  expect(
    container.querySelector<HTMLInputElement>('input[name="ticker"]')?.value,
  ).toBe("ETN.NYS");
  expect(
    container.querySelector<HTMLSelectElement>('select[name="entryPattern"]')?.value,
  ).toBe("");
});
```

Add stale-state regressions in the same block:

- Select a recent candidate with `pattern`, then select a no-pattern recent candidate for the same ticker; assert the candidate-derived `entryPattern` is cleared. Then repeat with a manually edited `entryPattern` after the first selection and assert the manual value is preserved only when selecting the same-ticker no-pattern candidate.
- Select a recent candidate with `pattern`, then manually type a different ticker in the main `ticker` input; assert the candidate-derived `entryPattern` is cleared. Repeat with a manual `entryPattern` value and assert ticker identity change clears it unless the manual value was chosen after the new ticker was set.
- Select a recent candidate with `pattern`, then use ticker search to select another ticker; assert the candidate-derived `entryPattern` is cleared. Repeat with a manual `entryPattern` value and assert ticker-search identity change clears it unless the manual value was chosen after the new ticker was set.
- Select a recent candidate with `pattern`, then click `Edit` on an existing holding with its own `entry_pattern`; assert the edit-loaded value is shown and later no-pattern candidate selection does not treat the edit-loaded value as candidate-derived.
- Select a recent candidate with `pattern`, submit or cancel the form, then assert the next create form starts with empty `entryPattern` and no stale candidate source state.

These tests distinguish manual/edit-loaded values from candidate-derived values and catch stale breakout markers moving to a different ticker.

- **Reference Step 2: Run recent-candidate tests to verify failure**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# pnpm --dir web run test -- web/src/lib/__tests__/ticker-directory.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts
```

Expected: FAIL because recent candidate parsing drops `pattern`, the client parser does not yet null out unknown pattern IDs, the UI does not expose pattern metadata, candidate-derived entry patterns are not yet cleared when a later no-pattern candidate is selected, and stale candidate-derived markers are not yet cleared on manual ticker changes, ticker-search selection, or form lifecycle transitions.

- **Reference Step 3: Preserve `pattern` in ticker-directory recent candidates**

In `web/src/lib/ticker-directory.ts`, import `isHoldingEntryPattern` from `web/src/lib/holding-entry-pattern.ts`, but keep `TickerDirectoryCandidate` and `TickerDirectorySearchResult` ticker/name-only. Add a separate recent-candidate type so action-driving `pattern` metadata never becomes part of the persisted ticker-directory cache or `/api/tickers/search` response:

```ts
export interface RecentBuyCandidate {
  ticker: string;
  name: string | null;
  pattern: string | null;
}
```

Add helper near `normalizeCandidateName` using the shared validator:

```ts
function normalizeCandidatePattern(value: unknown): string | null {
  const text = toCleanString(value);
  if (!text || !isHoldingEntryPattern(text)) {
    return null;
  }
  return text;
}
```

Add a new recent-candidate extraction helper instead of changing the directory-cache extraction contract. `extractBuyCandidatesFromReport` should keep returning `TickerDirectoryCandidate[]` for cache/search merge behavior. The new helper reads `pattern`:

```ts
    const raw = row as { ticker?: unknown; name?: unknown; pattern?: unknown };
```

and returns it on `RecentBuyCandidate` rows:

```ts
      pattern: normalizeCandidatePattern(raw.pattern),
```

For duplicate rows inside a single report, do not keep pure first-seen skip behavior in the recent-candidate helper if it discards pattern metadata. Keep the first candidate's position, ticker, and name, but if the first candidate's `pattern` is `null` and a later duplicate has a valid normalized pattern, update the first candidate's `pattern` to that value. One straightforward implementation is to keep a `Map<string, number>` from ticker to result index instead of a `Set<string>` and promote `results[index].pattern` only when it is currently `null`.

In `tryLoadBuyReportCandidates`/`mergeCandidatesFromReport`, keep directory search behavior pattern-free and aliasing based on ticker/name only. In `listRecentBuyCandidates`, call the new recent-candidate helper so `/api/tickers/recent-candidates` returns `pattern: string | null` without persisting that field into the directory cache. Add a negative test that `refreshTickerDirectory`/cache payload entries and `/api/tickers/search` results do not include `pattern`.

In the same Task 4 runtime boundary, update `docs/holdings-ticker-lookup.md` and `docs/adr/ADR-0008-holdings-ticker-directory.md` so public documentation ships with the API shape change. The docs must distinguish ticker-directory cache/search results, which remain ticker/name-only, from `/api/tickers/recent-candidates`, which now returns `pattern: string | null`. Do not defer these docs to Task 5 if Task 4 is deployable.

- **Reference Step 4: Parse pattern in client hooks**

In `web/src/components/holdings/use-ticker-lookup.ts`, import `isHoldingEntryPattern` from `web/src/lib/holding-entry-pattern.ts`. Keep normal ticker-search results focused on ticker/name, and add a recent-candidate-specific type plus parser so recent candidates always own `pattern: string | null`:

```ts
export interface TickerLookupResult {
  ticker: string;
  name: string | null;
}

export interface RecentCandidateLookupResult extends TickerLookupResult {
  pattern: string | null;
}
```

Keep `parseTickerLookupResults` for `/api/tickers/search` unchanged except for any shared helper extraction. Add a helper that validates pattern values against the allowed IDs:

```ts
function parseCandidatePattern(value: unknown): string | null {
  const text = typeof value === "string" ? value.trim() : "";
  return text && isHoldingEntryPattern(text) ? text : null;
}
```

Add a separate parser for `/api/tickers/recent-candidates` payloads. It should preserve valid ticker/name rows, normalize unknown or omitted pattern values to `null`, and always return objects that own the `pattern` key:

```ts
export function parseRecentCandidateLookupResults(
  payload: unknown,
): RecentCandidateLookupResult[] {
  if (!Array.isArray(payload)) {
    return [];
  }
  const results: RecentCandidateLookupResult[] = [];
  for (const item of payload) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      continue;
    }
    const raw = item as { ticker?: unknown; name?: unknown; pattern?: unknown };
    const ticker =
      typeof raw.ticker === "string" ? raw.ticker.trim().toUpperCase() : "";
    if (!ticker) {
      continue;
    }
    const name = typeof raw.name === "string" ? raw.name.trim() : "";
    results.push({
      ticker,
      name: name || null,
      pattern: parseCandidatePattern(raw.pattern),
    });
  }
  return results;
}
```

Update `web/src/components/holdings/use-recent-candidates.ts` to call `parseRecentCandidateLookupResults`, not `parseTickerLookupResults`, so a server/fixture payload that omits `pattern` still becomes a stable client shape with an owned `pattern: null`. Search UI tests should remain focused on ticker/name and should not have to assert a pattern key.

- **Reference Step 5: Populate `entry_pattern` when selecting a recent candidate**

In `web/src/components/holdings/holdings-form-panel.tsx`, import the shared candidate type if needed and add a small `.lookupPattern` style if no suitable secondary metadata class already exists:

```tsx
import type { RecentCandidateLookupResult } from "./use-ticker-lookup";
```

Change `recentCandidates` prop from `TickerLookupItem[]` to:

```ts
  recentCandidates: RecentCandidateLookupResult[];
```

Add a callback prop:

```ts
  onSelectRecentCandidate: (candidate: RecentCandidateLookupResult) => void;
```

Change the recent candidate button handler:

```tsx
                    onClick={() => onSelectRecentCandidate(item)}
```

Show the pattern whenever present so the action-driving metadata is visible before click. Keep the company name as the primary secondary text and add a compact pattern line or badge:

```tsx
                      {item.name ?? "이름 없음"}
                      {item.pattern && (
                        <span className={styles.lookupPattern}>
                          Pattern: {item.pattern}
                        </span>
                      )}
```

In `web/src/components/holdings-client.tsx`, import the types:

```tsx
import type { HoldingFormState } from "@/components/holdings/form-state";
import type { RecentCandidateLookupResult } from "@/components/holdings/use-ticker-lookup";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
```

Track whether the current `entry_pattern` value came from a recent candidate and which ticker it belongs to. Clear on ticker identity changes, not on every ticker-field edit, so edit-loaded or manual values are not dropped when the user touches the ticker field but keeps the same canonical identity:

```tsx
  const normalizeTickerIdentity = useCallback(
    (ticker: string) => normalizeHoldingTickerForMutation(ticker),
    [],
  );
  const [
    recentCandidateEntryPatternSource,
    setRecentCandidateEntryPatternSource,
  ] = useState<{ ticker: string; pattern: string } | null>(null);

  const clearEntryPatternForTickerIdentityChange = useCallback(
    (nextTicker: string) => {
      const currentIdentity = normalizeTickerIdentity(form.ticker);
      const nextIdentity = normalizeTickerIdentity(nextTicker);
      if (currentIdentity === nextIdentity) {
        return;
      }
      if (form.entry_pattern) {
        updateField("entry_pattern", "");
      }
      setRecentCandidateEntryPatternSource(null);
    },
    [form.entry_pattern, form.ticker, normalizeTickerIdentity, updateField],
  );

  const clearCandidateDerivedPatternForSameTicker = useCallback(() => {
    if (
      recentCandidateEntryPatternSource !== null &&
      form.entry_pattern === recentCandidateEntryPatternSource.pattern
    ) {
      updateField("entry_pattern", "");
      setRecentCandidateEntryPatternSource(null);
    }
  }, [form.entry_pattern, recentCandidateEntryPatternSource, updateField]);

  const handleFieldChange = useCallback(
    (field: keyof HoldingFormState, value: string) => {
      if (field === "entry_pattern") {
        setRecentCandidateEntryPatternSource(null);
        updateField(field, value);
        return;
      }
      if (field === "ticker") {
        clearEntryPatternForTickerIdentityChange(value);
      }
      updateField(field, value);
    },
    [clearEntryPatternForTickerIdentityChange, updateField],
  );
```

Use the same ticker-identity clearing helper for ticker-search selection before setting the new ticker, and reset source state when entering edit mode, canceling edit, or after a successful submit/reset. A simple way is to wrap `beginEdit`, `cancelEdit`, and ticker lookup selection in `HoldingsClient`; if implementing a form hook callback is cleaner, keep the source-reset behavior covered by the tests above.

Add the callback before `return`:

```tsx
  const selectRecentCandidate = useCallback(
    (candidate: RecentCandidateLookupResult) => {
      const sameTickerIdentity =
        normalizeTickerIdentity(form.ticker) ===
        normalizeTickerIdentity(candidate.ticker);
      updateField("ticker", candidate.ticker);
      if (candidate.pattern) {
        updateField("entry_pattern", candidate.pattern);
        setRecentCandidateEntryPatternSource({
          ticker: candidate.ticker,
          pattern: candidate.pattern,
        });
        return;
      }
      if (!sameTickerIdentity && form.entry_pattern) {
        updateField("entry_pattern", "");
      } else {
        clearCandidateDerivedPatternForSameTicker();
      }
      setRecentCandidateEntryPatternSource(null);
    },
    [
      clearCandidateDerivedPatternForSameTicker,
      form.entry_pattern,
      form.ticker,
      normalizeTickerIdentity,
      updateField,
    ],
  );
```

Clear candidate-derived `entry_pattern` whenever a no-pattern recent candidate is selected, even when the ticker stays the same. A user can still intentionally set `entry_pattern` after that selection; the `entry_pattern` field handler above marks that value as manual/edit-loaded for the current ticker. If the canonical ticker identity changes through recent-candidate selection, ticker-search selection, or manual ticker typing, clear the current `entry_pattern` unless it was selected after the new ticker was already set. Otherwise a marker chosen for one ticker can be saved on a different ticker and later trigger an unrelated failed-breakout sell. Cover canonical-equivalent aliases such as `BRK/B.NYS` versus `BRK.B.NYS`, and suffix aliases such as `AAPL.NASD` versus `AAPL.NAS`, so the stale-marker guard matches the same identity rules as holdings mutations.

Pass both the wrapped field handler and the recent-candidate callback:

```tsx
          onFieldChange={handleFieldChange}
          onSelectRecentCandidate={selectRecentCandidate}
```

- **Reference Step 6: Run recent-candidate tests**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# pnpm --dir web run test -- web/src/lib/__tests__/ticker-directory.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts
```

Expected: PASS.

- **Reference Step 7: Commit recent-candidate propagation**

```bash
# Runtime plan example only; do not execute from this plan:
# git add web/src/lib/ticker-directory.ts web/src/components/holdings/use-ticker-lookup.ts web/src/components/holdings/use-recent-candidates.ts web/src/components/holdings/holdings-form-panel.tsx web/src/components/holdings-client.tsx web/src/components/holdings-client.module.css web/src/lib/__tests__/ticker-directory.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts docs/holdings-ticker-lookup.md docs/adr/ADR-0008-holdings-ticker-directory.md
# git commit -m "feat(web): 최근 매수 후보 패턴 보존" -m "최근 buy 후보 API와 holdings 입력 플로우가 후보 pattern을 entry_pattern으로 전달하도록 연결한다."
```

## Runtime Reference Task 5: Documentation (Non-Executable)

Task 5 is a documentation checklist, not permission to defer public-contract docs until after runtime deployment. The docs that describe runtime-visible behavior (`docs/holdings-schema.md`, `docs/holdings-add-buy.md`, `docs/STRATEGY.md`, `docs/api.md`, `docs/local-docker-scheduler-plan.md`, `docs/adr/ADR-0010-holdings-add-buy.md`, and any architecture/scheduler note that would otherwise contradict the runtime) must be included in the same deployable boundary as the DB/runtime behavior they describe. If those files were already staged and committed with the DB or runtime boundary, use this task to verify them and finish remaining ADR/example updates, not to introduce the first public documentation after deploy.

**Files:**
- Modify: `docs/holdings-schema.md`
- Modify: `docs/holdings-add-buy.md`
- Modify: `docs/STRATEGY.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/api.md`
- Modify: `docs/configuration.md`
- Modify: `docs/config-reference.md`
- Modify: `docs/local-docker-scheduler-plan.md`
- Modify: `docs/holdings-ticker-lookup.md`
- Modify: `docs/adr/ADR-0008-holdings-ticker-directory.md`
- Modify: `docs/adr/ADR-0010-holdings-add-buy.md`
- Modify: `holdings.example.yaml`

- **Reference Step 1: Update holdings schema docs**

In `docs/holdings-schema.md`, add `entry_pattern` to the example row after `strategy` and document that the value is trimmed, nullable, explicitly exported as `null` when absent, limited to 120 characters, restricted to the append-only holdings storage pattern IDs across DB/RPC/YAML/web mutation paths, and valid only for active rows (`quantity > 0`). Also document the import/export semantic exception: generated exports always include `entry_pattern` with either a value or `null`; YAML/import/replace-all inputs that omit the key preserve the existing DB value for that field only while the resulting row remains active and entry identity plus strategy are unchanged, while explicit `entry_pattern: null`, blank, or `quantity: 0` clears it.

```yaml
    strategy: sma_ema_hybrid
    entry_pattern: swing_high_breakout
```

Add this row to the field table after `strategy`:

```markdown
| `entry_pattern` | string (선택, 최대 120자) | buy/entry report의 `pattern`을 active 보유 상태에 보존한 값. `quantity = 0` 행에서는 `null`이어야 함. 허용값: `trend_pullback_bounce`, `swing_high_breakout`, `rsi_oversold_reversal`; `swing_high_breakout`만 hybrid sell의 failed-breakout 판정에 사용 |
```

Add this note near the sell command section:

```markdown
- `sma_ema_hybrid` breakout 후보를 보유로 전환할 때는 `entry_pattern`에 buy/entry report의 `pattern` 값을 보존하세요. `sab sell`은 `entry_pattern: swing_high_breakout`을 exact pattern marker로 인식해 `strategy`/`tags` 수동 마커 없이 failed-breakout 규칙을 적용합니다.
```

- **Reference Step 2: Update Add Buy docs**

In `docs/holdings-add-buy.md`, add this contract note near the API/RPC contract section:

```markdown
- Add Buy는 수량, 평단, 진입일, 통화만 갱신하며 active holdings row의 기존 `entry_pattern`은 보존합니다. 단, `quantity = 0` 비활성 row를 Add Buy로 재활성화할 때는 닫힌 포지션의 stale marker가 새 포지션에 붙지 않도록 기존 `entry_pattern`을 clear합니다. `entry_pattern`은 active-position metadata이므로 일반 holdings 수정이나 YAML import가 행을 `quantity = 0`으로 만들 때도 clear되어야 합니다. buy/entry report의 `pattern`을 새로 기록해야 하는 경우 holdings 생성/수정 또는 YAML import 경로에서 active row의 `entry_pattern`을 설정하세요. 이 RPC는 `entry_pattern`을 추론하거나 입력으로 받지 않습니다.
```

Also update `docs/adr/ADR-0010-holdings-add-buy.md` with a short superseding note under the decision or consequences section. The note must state that Add Buy remains quantity-only, preserves `entry_pattern` for active holdings, clears it for `quantity = 0` reactivation, and rejects/does not accept `p_entry_pattern`; it should also point to the broader holdings invariant that inactive rows store `entry_pattern` as `null`. This keeps the accepted ADR aligned with `docs/holdings-add-buy.md`.

- **Reference Step 3: Update strategy docs**

In `docs/STRATEGY.md`, replace the note that says holdings only forwards `strategy` and `tags` with:

```markdown
  - 하위 hybrid sell evaluator는 `strategy`, `tags`, `pattern`, `entry_pattern`, `signal_pattern` marker를 인식합니다. 운영 holdings 계약은 buy/entry report의 `pattern`을 `entry_pattern`으로 보존해 breakout 매수의 failed-breakout sell 규칙이 수동 태그 없이도 적용되도록 합니다.
```

- **Reference Step 4: Update architecture docs**

In `docs/ARCHITECTURE.md`, update the web holdings CRUD flow note that currently says ticker directory candidates are derived from `candidates[].{ticker,name}`. Replace it with:

```markdown
   - 티커 검색 데이터는 buy 리포트(`candidates[].{ticker,name}`)에서 파생한 “티커 디렉토리(캐시)”를 사용하며, 캐시/검색 entry shape는 ticker/name 중심으로 유지합니다. 최근 buy 후보 API와 후보 선택 경로는 최신 buy 리포트의 `candidates[].{ticker,name,pattern}`을 읽고, 후보 `pattern`을 holdings 입력의 `entry_pattern`으로 전달해 breakout 매수의 sell marker를 보존합니다.
```

Also add short notes under the workflow holdings bridge sections:

```markdown
- scheduled `sell.yml`은 Supabase `holdings`에서 `entry_pattern`까지 export한 `holdings.generated.yaml`을 `sab sell --holdings`에 전달합니다.
- scheduled AI Brief는 Python scheduler export helper가 Supabase `holdings`에서 `entry_pattern`까지 export한 holdings snapshot을 사용합니다.
- `.github/workflows/ai-brief.yml`의 manual `ai_brief` job inline holdings bridge도 `entry_pattern`까지 export해 manual downstream entry/brief context가 동일한 holdings contract를 사용합니다.
```

Update `docs/holdings-ticker-lookup.md` where it currently describes `/api/tickers/recent-candidates` as returning only `{ticker, name}`. The revised docs must distinguish the two shapes: ticker-directory cache/search remains ticker/name-only, while recent buy candidate payloads include `pattern: string | null`. Update `docs/adr/ADR-0008-holdings-ticker-directory.md` with a short superseding note under consequences or status: the directory cache still derives/stores ticker/name aliases only, and the newer recent-candidate selection flow reads buy report `pattern` separately without adding it to the cache/search contract.

In `docs/api.md`, update the holdings contract so returned holdings rows and current snapshots document `entry_pattern: string | null` as an owned nullable field, while normal holdings create/patch payloads document `entry_pattern?: string | null` with the invariant that non-null `entry_pattern` must be accompanied by `quantity > 0` in the same create/patch payload, and explicit `entry_pattern: null` clears without requiring quantity. Reserve omitted-key preserve semantics for YAML/replace-all import inputs only. Also explicitly state that Add Buy remains quantity-only and rejects marker fields such as `entry_pattern`. Update the `/api/tickers/recent-candidates` response contract so each candidate documents `pattern: string | null`. Make the distinction explicit: ticker search results remain ticker/name-only, while recent buy candidates may carry validated buy-report pattern metadata.

In `docs/configuration.md` and `docs/config-reference.md`, update the `SUPABASE_SECRET_KEY` and `SUPABASE_SERVICE_ROLE_KEY` rows so they state holdings replace/add-buy RPCs and scheduled holdings export require the configured server-side Supabase secret to have the write/RPC capability used by deployed web and scheduled jobs. If the optional service-role-only hardening release is kept, state that this secret must be service-role-capable; otherwise do not imply the core `entry_pattern` migration added service-role-only RPC grants. In every case, deployment smoke must prove the exact configured secret can run the holdings projection and Add Buy RPC.

- **Reference Step 5: Update local Docker scheduler docs**

In `docs/local-docker-scheduler-plan.md`, update the scheduled AI Brief holdings export field list that currently says the active export uses `ticker`, `quantity`, `entry_price`, `entry_currency`, `entry_date`, `strategy`, `notes`, `tags`, `stop_override`, and `target_override`. Insert `entry_pattern` immediately after `strategy`, matching the Python scheduler helper and the manual GitHub workflow bridge:

```markdown
   - 필드는 current GitHub workflow와 같은 `ticker`, `quantity`, `entry_price`, `entry_currency`, `entry_date`, `strategy`, `entry_pattern`, `notes`, `tags`, `stop_override`, `target_override`를 사용합니다.
```

- **Reference Step 6: Update example YAML**

In `holdings.example.yaml`, add `entry_pattern` to the first swing example:

```yaml
    strategy: sma_ema_hybrid
    entry_pattern: swing_high_breakout
```

If the example currently uses `strategy: swing`, change only that example row to `sma_ema_hybrid`; leave unrelated examples unchanged.

- **Reference Step 7: Run static docs check**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# rg -n 'entry_pattern|failed-breakout|failed breakout|candidates\[\].*pattern|recent-candidates.*pattern|Add Buy.*marker|Add Buy.*entry_pattern|server-side Supabase secret|service-role-capable|service_role' docs/holdings-schema.md docs/holdings-add-buy.md docs/STRATEGY.md docs/ARCHITECTURE.md docs/api.md docs/configuration.md docs/config-reference.md docs/local-docker-scheduler-plan.md docs/adr/ADR-0010-holdings-add-buy.md holdings.example.yaml
# rg -n 'recent-candidates.*pattern|pattern: string \| null|`pattern`' docs/holdings-ticker-lookup.md docs/adr/ADR-0008-holdings-ticker-directory.md
# if rg -n 'holdings.*only.*strategy.*tags|strategy.*tags.*만|`strategy`, `notes`' docs/STRATEGY.md docs/ARCHITECTURE.md docs/local-docker-scheduler-plan.md; then
#   exit 1
# fi
# rg -n 'candidates\[\].*\{ticker,name\}' docs/holdings-ticker-lookup.md docs/adr/ADR-0008-holdings-ticker-directory.md || true
```

Expected: output shows `entry_pattern` documented in holdings schema, Add Buy docs, Add Buy ADR, strategy docs, architecture flow docs, API docs, local Docker scheduler docs, and example YAML; `docs/configuration.md` and `docs/config-reference.md` document the configured server-side Supabase secret requirement for holdings RPC/write paths, and only claim service-role-capable execution if the optional hardening release kept service-role-only grants; `docs/api.md` covers holdings create/patch/record responses plus Add Buy marker rejection; `docs/holdings-ticker-lookup.md` and ADR-0008 positively document that recent candidates carry `pattern: string | null`; the negative check produces no stale contradictory wording. Any remaining `candidates[].{ticker,name}` hits in `docs/holdings-ticker-lookup.md` or ADR-0008 must explicitly refer to the ticker/name-only search-directory cache, not recent-candidate API payloads or holdings candidate-selection behavior.

- **Reference Step 8: Commit docs**

```bash
# Runtime plan example only; do not execute from this plan:
# git add docs/holdings-schema.md docs/holdings-add-buy.md docs/STRATEGY.md docs/ARCHITECTURE.md docs/api.md docs/configuration.md docs/config-reference.md docs/local-docker-scheduler-plan.md docs/holdings-ticker-lookup.md docs/adr/ADR-0008-holdings-ticker-directory.md docs/adr/ADR-0010-holdings-add-buy.md holdings.example.yaml
# git commit -m "docs: 진입 패턴 보유 계약 문서화" -m "entry_pattern을 holdings 공개 계약으로 설명한다."
```

## Runtime Reference Task 6: Final Verification (Non-Executable)

**Files:**
- No source changes unless verification exposes a bug.

Targeted task tests are checkpoints only. Do not mark the plan complete, move `TODOS.md`, or deploy runtime changes until the full Python, web, workflow, DB-ordering, and visual checks in this task are either passed or explicitly recorded as blocked with a concrete reason.

- **Reference Step 1: Confirm migration/runtime deployment ordering**

Before merge/deploy, confirm the DB migration that adds `public.holdings.entry_pattern` was applied and the executable migration smoke from Task 2 passed before any runtime containing `entry_pattern` in a PostgREST select or mutation body can run. This includes `.github/workflows/sell.yml`, `.github/workflows/ai-brief.yml`, `sab/scheduler/holdings.py`, and web `HOLDINGS_SELECT` in `web/src/lib/supabase/holdings.ts`. Runtime select changes must stay separate until the migration is applied and verified unless reviewed deployment automation guarantees migration-first ordering.

Expected: the release notes or PR checklist explicitly records the Phase A migration apply command, SQL smoke result, deployed-secret PostgREST select/write smoke result, the reserved target-DB smoke ticker and preflight absence evidence, any PostgREST schema-cache remediation if needed, that Phase A kept non-null `entry_pattern` writes closed, that `replace_holdings_v1` was executed through disposable Supabase/PostgREST rather than only psql, legacy Add Buy replay null-field compatibility without historical event rewrites, normal inactive Add Buy reactivation from `entry_pattern = null`, static/disposable evidence for the defensive stale-clearing branch if claimed, generic inactive-row `entry_pattern = null` enforcement evidence, replace-all locking/concurrency evidence or an explicit single-writer operational constraint, and that `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql` plus the later runtime enablement migration are applied in order before scheduled workflow, AI brief workflow, Python helper, or web/admin runtime rollout.

- **Reference Step 2: Run Python quality gate**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# just quality
```

Expected: PASS. If `just` cannot find pinned tools, rerun:

```bash
# Runtime plan example only; do not execute from this plan:
# mise exec -- just quality
```

- **Reference Step 3: Run web CI gate**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# just ci-web
```

Expected: PASS. If `pnpm` is not on `PATH`, rerun:

```bash
# Runtime plan example only; do not execute from this plan:
# mise exec -- just ci-web
```

- **Reference Step 4: Run workflow audit**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# just workflow-audit
```

Expected: PASS. This gate is required because Task 2 edits inline shell/Python in `.github/workflows/sell.yml` and `.github/workflows/ai-brief.yml`; `just quality` and `just ci-web` are not sufficient to catch workflow YAML, heredoc, or shell-lint regressions.

- **Reference Step 5: Run holdings page visual smoke**

Before opening the page, verify the web target points at a database whose PostgREST schema cache already exposes `entry_pattern`. Reuse the Task 2 full-projection `limit=0` smoke with the same environment values the web target uses, or record the migrated target URL/evidence from the runtime release notes. Do not treat a `/holdings` failure against an unmigrated local/target DB as a frontend regression; fix the DB ordering or point the smoke at the migrated target first.

If the `sab-web` container is running, open:

```bash
# Runtime plan example only; do not execute from this plan:
# http://127.0.0.1:${WEB_HOST_PORT:-55300}/holdings
```

Otherwise start the repo's web app with:

```bash
# Runtime plan example only; do not execute from this plan:
# docker compose up -d --build web
```

Then open the same route. Check desktop and mobile widths. Expected: the form Entry Pattern select, recent candidate selection, and holdings table Entry Pattern display are visible; no table text overlaps Tags, Updated, or Action controls.

- **Reference Step 6: Review focused diff**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# BASE_REF="${BASE_REF:-origin/main}"
# MERGE_BASE="$(git merge-base HEAD "${BASE_REF}")"
# git diff --stat "${MERGE_BASE}"..HEAD
# git diff --name-only "${MERGE_BASE}"..HEAD
```

Expected: diff is limited to the `entry_pattern` contract and its tests/docs, including all planned Python tests, Supabase migration/tests, scheduled export tests, `sell.yml`, `ai-brief.yml`, web schemas/helpers/routes/components/tests, docs, example YAML, and `TODOS.md` only after quality gates pass. If `origin/main` is unavailable, use the actual PR base branch and record it.

## Runtime Reference Task 7: TODO Closure (Non-Executable)

**Files:**
- Modify: `TODOS.md`

- **Reference Step 1: Move active TODO to completed**

In `TODOS.md`, remove this active bullet:

```markdown
  - Preserve buy `pattern` into holdings/entry state so breakout-specific sell
    rules reliably identify failed breakout positions, not only holdings with
    manual `strategy`/`tags` markers.
```

Add this completed entry at the top of `## Completed`:

```markdown
- 2026-06-09: Preserved buy `pattern` as holdings `entry_pattern` across
  Python YAML loading, Supabase holdings storage, scheduled export, web
  holdings create/edit/import/export, and recent buy candidate selection, so
  `sma_ema_hybrid` failed-breakout sell rules no longer depend on manual
  `strategy`/`tags` markers.
```

- **Reference Step 2: Run TODO closure check**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# rg -n "2026-06-09: Preserved buy .*entry_pattern" TODOS.md
# if rg -n 'Preserve buy .*failed breakout|Preserve buy `pattern`' TODOS.md; then
#   exit 1
# fi
```

Expected: completed entry is present, old active bullet is absent, and no unrelated TODO text changed. The check must fail if the active bullet remains.

- **Reference Step 3: Commit TODO closure**

```bash
# Runtime plan example only; do not execute from this plan:
# git add TODOS.md
# git commit -m "docs: 진입 패턴 TODO 완료 처리" -m "품질 게이트 통과 후 entry_pattern 보존 작업을 완료 항목으로 이동한다."
```

- **Reference Step 4: Confirm no uncommitted changes**

Run:

```bash
# Runtime plan example only; do not execute from this plan:
# git status --short
```

Expected: no output.

## Self-Review

**Spec coverage:** The plan covers the active TODO: buy `pattern` is preserved into holdings via `entry_pattern`; entry reports already preserve `pattern`; hybrid sell reads structured pattern fields with exact failed-breakout semantics; scheduled sell receives the field through both the Python export helper and the active `.github/workflows/sell.yml` inline export, then through the Python loader and `_evaluate_holdings` metadata bridge. Scheduled AI Brief preserves the field through the Python scheduler export helper, the manual `.github/workflows/ai-brief.yml` inline bridge is tested separately, and `docs/local-docker-scheduler-plan.md` is updated to match. It also covers web recent-candidate selection, web/admin `HOLDINGS_SELECT`, YAML import/export/diff behavior including omitted-vs-null replace-all semantics and explicit export-null ownership, inactive-row `entry_pattern = null` enforcement, and deployment ordering so the operator does not need manual `strategy`/`tags`. Task 1 and Task 2 Phase A are foundation-only; production goal completion requires the later runtime plan to include Task 4 recent-candidate propagation with the first user-facing create/edit boundary. Add Buy is explicitly scoped to preserve active-position `entry_pattern`, keep zero-quantity reactivation at `entry_pattern = null`, defensively clear stale pre-constraint markers without requiring impossible target-DB smoke, reject marker inputs, and not infer a new one; generic edit/PATCH and YAML/replace-all paths must also clear or reject inactive-row markers.

**Completeness scan:** Instructions are concrete, with no filler placeholders, conditional mock instructions, or unspecified edge handling. `TODOS.md` references are repository file names, not placeholders.

**Type consistency:** The field name is consistently `entry_pattern` in SQL, Python dataclass/YAML, TypeScript record/snapshot/mutation types, form state, and docs. TypeScript uses required nullable `entry_pattern` for DB/current holdings and an optional key only for replace/import snapshots that must preserve YAML key presence on active rows. Buy/entry report source field remains `pattern`, allowed values come from the append-only holdings storage pattern IDs initially set to `trend_pullback_bounce`, `swing_high_breakout`, and `rsi_oversold_reversal`, and inactive rows must store `entry_pattern` as `null`.

**Review hardening:** The plan now explicitly guards migration-before-any-runtime deployment ordering with a DB-only stop point, temporary Phase A write-closed protection for non-null `entry_pattern`, a separate runtime enablement migration before exports/writes, default RPC privilege-posture preservation rather than contradictory pseudo-hardening, replace-all table locking plus concurrency evidence or a documented single-writer constraint, disposable Supabase/PostgREST execution smoke for `replace_holdings_v1`, active `sell.yml` scheduled export coverage, manual `ai-brief.yml` inline export coverage, local Docker scheduler docs, fail-closed Python/web/RPC `entry_pattern` parsing with allowed-value checks, exact hybrid sell semantics for structured pattern fields, shared PostgREST holdings select coverage plus schema-cache remediation, YAML omitted-vs-null and blank-clear diff/apply behavior, explicit `entry_pattern: null` YAML exports, DB/RPC/web enforcement that inactive rows cannot retain `entry_pattern`, legacy Add Buy idempotency replay compatibility without event rewrites, Add Buy active preservation/normal inactive zero-quantity reactivation with null marker/static stale-branch proof and marker-input rejection without request-surface expansion, server-action and client form save pass-through plus deactivation clear coverage, fixture commit completeness, cross-language allowlist drift guards, stale recent-candidate marker clearing, ticker-aware manual/edit-loaded value preservation that does not cross ticker identity changes, first user-facing runtime inclusion of recent-candidate `pattern` propagation, import confirmation copy, API/architecture docs, and table metadata wrapping.
