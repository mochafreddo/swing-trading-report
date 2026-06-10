상태: Draft

# Preserve Entry Pattern Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve buy-report `pattern` metadata as holdings `entry_pattern` so `sma_ema_hybrid` failed-breakout sell rules work without manual `strategy` or `tags` markers.

**Architecture:** Treat `entry_pattern` as the durable holdings-side copy of a buy signal's `pattern`, not as a free-form sell marker. Keep `pattern` in buy/entry report rows, add `entry_pattern` at holdings boundaries, validate it against the current buy pattern IDs, and tighten hybrid sell so structured pattern fields use exact pattern semantics while legacy `strategy`/`tags` markers keep their existing substring behavior.

**Tech Stack:** Python dataclasses and pytest, Supabase SQL migrations/RPCs, Next.js 16 + TypeScript + Zod + Vitest, existing `just` quality gates.

---

## Problem Brief

**Context:** Hybrid buy reports already emit candidate `pattern`, and entry reports already preserve that field on `EntryReportRow`. Hybrid sell also already treats `pattern`, `entry_pattern`, and `signal_pattern` as breakout markers.

**Problem:** The durable holdings contract currently exposes only `strategy` and `tags`; scheduled Supabase export and local `holdings.yaml` loading do not preserve `entry_pattern`. A breakout buy that becomes a holding can therefore lose its origin pattern unless the operator manually encodes it in `strategy` or `tags`.

**Goal:** Add a narrow `entry_pattern` contract from recent buy candidate selection/import/export through holdings DB/YAML/scheduled export into `sab sell` and the scheduled AI brief holdings bridge.

**Non-Goals:** Do not redesign holdings as lots, do not add partial exits, do not change failed-breakout thresholds, do not change buy/entry ranking policy, and do not extend the Add Buy flow/RPC to infer, accept, clear, or overwrite `entry_pattern`.

**Constraints:** Keep backwards compatibility with old holdings rows/YAML files; `entry_pattern` must be optional and nullable. Avoid broad web UI redesign. Update strategy/holdings docs because this changes a public holdings contract.

## Impact Note

This changes the holdings schema, web holdings DTOs/forms, YAML import/export, scheduled holdings export, Python holdings loader, hybrid sell marker interpretation, and the sell-evaluation bridge that builds the evaluator metadata dict. The likely breakages are mismatched Supabase RPC signatures, TypeScript fixture drift, YAML round-trip omissions, PostgREST `select` omissions, old replace-all callers clearing the new column, YAML import collapsing omitted `entry_pattern` into explicit null, YAML export omitting explicit nulls, overly permissive substring marker parsing, stale candidate-derived form state, and loader fields that never reach `sab sell`. Tests/docs must cover Python loader/export, `_evaluate_holdings` metadata forwarding, exact `entry_pattern` validation, web schema/YAML helpers, ticker recent-candidate metadata, executable migration/RPC validation, shared holdings select queries, create/update persistence bodies, edit-form preservation, Add Buy rejection of `entry_pattern` inputs, and the Add Buy decision to preserve existing `entry_pattern` without inferring a new one.

## Scope Check

This is one cross-boundary metadata contract, not several independent subsystems. It should stay in one plan because each task moves the same `entry_pattern` field across one adjacent boundary.

Add Buy remains quantity-only in this plan. It should keep returning the full holding row after the schema change, thereby preserving any existing `entry_pattern`, but it must not accept, infer, clear, or overwrite `entry_pattern`; changing that would require a separate RPC signature and idempotency fingerprint decision.

YAML import/replace-all compatibility depends on preserving source key presence. A missing `entry_pattern` key in an old YAML file or foreign replace-all payload means "leave the existing DB value unchanged"; an explicit `entry_pattern: null` or blank string means "clear the value"; a non-empty string means "set the value". Do not normalize missing YAML `entry_pattern` to `null` before building the `replace_holdings_v1` request, because that would turn old YAML imports into destructive clears. Operator-facing YAML import copy must also mention this preserve-on-omit exception, because the import is no longer a literal full replacement for fields that old YAML files do not know about.

YAML export is different from YAML import. Exported YAML is an owned current-DB snapshot, so it must emit `entry_pattern` explicitly even when the DB value is `null`; otherwise a backup of a cleared value becomes an old-style omitted key and later import would preserve a stale DB marker instead of clearing it. Only parser/import/replace-all inputs may omit the key to mean preserve-existing.

`entry_pattern` values must be exact current buy pattern IDs: `trend_pullback_bounce`, `swing_high_breakout`, or `rsi_oversold_reversal`. The only failed-breakout `entry_pattern` value is `swing_high_breakout`; an unknown value such as `not_a_breakout` must be rejected at external write/import boundaries and must not trigger hybrid sell merely because it contains the substring `breakout`. Existing free-form `strategy`/`tags` marker behavior is preserved for backwards compatibility.

## Deployment Ordering

No runtime may run a PostgREST `select` or mutation body containing `entry_pattern` against a database that has not applied the `holdings.entry_pattern` migration. This includes the Python scheduled export helper, the inline `.github/workflows/sell.yml` and `.github/workflows/ai-brief.yml` holdings exports, and the web/admin `HOLDINGS_SELECT` shared by list/create/update/YAML import/export. To make the task checkpoints executable and safe for this repo, Task 1 is limited to local Python YAML loading and sell-evaluation forwarding. Task 2 must be split into mandatory deployment gates: first land/apply/verify a DB-only migration release, then enable runtime select/body changes in a separate runtime release only after `public.holdings.entry_pattern`, `replace_holdings_v1`, `holdings_add_buy_v1`, and service-role PostgREST smoke checks have passed against the target database. Two commits in one branch or PR are not a deployment boundary; do not merge/deploy runtime changes with the DB migration unless reviewed deployment automation proves migrations are applied before any runtime code can execute.

## File Structure

- Modify `sab/holdings_loader.py`: add optional `Holding.entry_pattern` and parse it from `holdings.yaml`.
- Modify `sab/signals/hybrid_sell.py`: make structured pattern fields use exact failed-breakout pattern semantics instead of substring matching.
- Modify `sab/sell_evaluation.py`: forward `Holding.entry_pattern` into the evaluator holding dict.
- Modify `sab/scheduler/holdings.py`: include `entry_pattern` in Supabase active-holdings select and generated YAML.
- Modify `.github/workflows/sell.yml`: include `entry_pattern` in the active scheduled sell holdings export query and generated YAML keys.
- Modify `.github/workflows/ai-brief.yml`: include `entry_pattern` in the AI brief holdings export query and generated YAML keys.
- Modify `tests/test_holdings_yaml_contract.py`: verify Python loader accepts export-style `entry_pattern`.
- Modify `tests/test_scheduled_holdings_export.py`: verify scheduled export selects and writes `entry_pattern`.
- Modify `tests/test_sell_evaluation_pnl.py`: verify `_evaluate_holdings` forwards `entry_pattern` into hybrid sell metadata.
- Modify `tests/test_hybrid_sell_profit_tiers.py`: add a direct evaluator regression that a holding with only `entry_pattern=swing_high_breakout` triggers failed-breakout sell.
- Modify `tests/test_workflow_holdings_loading.py`: verify `sell.yml` scheduled inline export and `ai-brief.yml` manual inline export select and write `entry_pattern`.
- Create `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql`: add nullable `entry_pattern` with length and allowed-value constraints, replace `replace_holdings_v1` to import/export the field while preserving existing values when old callers omit the key, and keep replace/add-buy grants explicit.
- Modify `web/src/lib/types.ts`: add required nullable `entry_pattern` to holding record/snapshot/mutation types and add a replace/import snapshot type whose `entry_pattern` key is optional so YAML imports can preserve missing-vs-null semantics.
- Create `web/src/lib/holding-entry-pattern.ts`: centralize the web-side allowed pattern IDs so schemas, YAML helpers, ticker-directory extraction, and client parsing cannot drift from each other.
- Modify `web/src/lib/schemas.ts`: accept optional nullable `entry_pattern` on create/patch and validate exact allowed pattern IDs.
- Modify `web/src/lib/supabase/holdings.ts`: select, create/update, and replace-all `entry_pattern`, omitting the key from replace-all rows only when the incoming replace/import snapshot omitted it.
- Modify `web/src/lib/holdings-yaml.ts`: parse/export/diff `entry_pattern`, validate exact allowed pattern IDs, preserve whether the YAML import row omitted the key, and emit explicit `null` in generated exports.
- Modify `web/src/components/holdings/form-state.ts`: add `entry_pattern` form state.
- Modify `web/src/components/holdings/helpers.ts`: map `entry_pattern` between records, forms, and mutation payloads.
- Modify `web/src/components/holdings/holdings-form-panel.tsx`: add a small Entry Pattern select/menu.
- Modify `web/src/components/holdings/holdings-table.tsx`: display `entry_pattern` as compact Tags-cell metadata without changing row actions.
- Modify `web/src/components/holdings/holdings-import-panel.tsx`: update import copy to explain omitted `entry_pattern` preserves the existing DB value.
- Modify `web/src/components/holdings/use-holdings-import.ts`: update the apply confirmation copy so it no longer claims every DB field is literally replaced by file content.
- Modify `web/src/components/holdings-client.module.css` if the table uses secondary-line `entry_pattern` metadata.
- Modify `web/src/components/holdings/use-ticker-lookup.ts`: parse optional `pattern` on recent candidate payloads while preserving ticker-search behavior.
- Modify `web/src/components/holdings/use-recent-candidates.ts`: expose recent candidate `pattern`.
- Modify `web/src/components/holdings-client.tsx`: when selecting a recent buy candidate, always populate ticker, populate `entry_pattern` only when the candidate has a non-empty `pattern`, and clear stale candidate-derived `entry_pattern` when the ticker changes outside recent-candidate selection.
- Modify `web/src/lib/ticker-directory.ts`: carry buy report row `pattern` in recent candidates; cache/search directory can keep pattern optional.
- Modify web tests:
  - `web/src/lib/__tests__/schemas.test.ts`
  - `web/src/lib/__tests__/holdings-yaml.test.ts`
  - `web/src/lib/__tests__/supabase-admin.test.ts`
  - `web/src/app/actions/__tests__/holdings.test.ts`
  - `web/src/lib/__tests__/ticker-directory.test.ts`
  - `web/src/lib/__tests__/holdings-client-hooks.test.tsx`
  - `web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts`
  - `web/src/app/api/holdings/__tests__/route.test.ts`
  - `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`
  - `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`
  - `web/src/app/api/holdings/yaml/__tests__/route.test.ts`
  - add-buy route/precheck tests that use `HoldingRecord` fixtures
  - add-buy single-ticker route, catch-all route, and action negative tests proving `entry_pattern` payloads are rejected
- Modify `docs/holdings-schema.md`: document optional `entry_pattern`, allowed pattern IDs, and explicit export-null behavior.
- Modify `docs/holdings-add-buy.md`: document that Add Buy preserves existing `entry_pattern` but does not infer a new one.
- Modify `docs/STRATEGY.md`: update the hybrid sell note that currently says holdings only forwards `strategy`/`tags`.
- Modify `docs/ARCHITECTURE.md`: update the holdings CRUD and ticker-directory flow notes that now carry buy candidate `pattern` into holdings `entry_pattern`.
- Modify `docs/local-docker-scheduler-plan.md`: update the scheduled AI Brief holdings export field list to include `entry_pattern`.
- Modify `docs/holdings-ticker-lookup.md` and `docs/adr/ADR-0008-holdings-ticker-directory.md` only if they contain stale recent-candidate payload wording.
- Modify `holdings.example.yaml`: add a commented/example `entry_pattern`.
- Modify `TODOS.md`: move the completed active bullet to Completed only after implementation and full verification pass.

## Task 1: Python Holdings Contract

**Files:**
- Modify: `sab/holdings_loader.py`
- Modify: `sab/signals/hybrid_sell.py`
- Modify: `sab/sell_evaluation.py`
- Test: `tests/test_holdings_yaml_contract.py`
- Test: `tests/test_sell_evaluation_pnl.py`
- Test: `tests/test_hybrid_sell_profit_tiers.py`

- [ ] **Step 1: Write failing Python contract tests**

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

Also add optional-value regressions in `tests/test_holdings_yaml_contract.py` so the loader contract is explicit: an omitted `entry_pattern` key loads as `None`, an explicit `entry_pattern: null` loads as `None`, and a blank or whitespace-only `entry_pattern` value also loads as `None`. These lock the backwards-compatible nullable semantics that `_parse_optional_text_field` implements and prove export-style null snapshots are accepted. Add the non-string rejection as a small parameterized set, or equivalent separate tests, covering at least YAML list, mapping, boolean (`true`), and numeric (`123`) values because YAML scalar coercion can otherwise turn marker-looking inputs into non-string Python values. Add an overlong regression with 121 characters and assert the loader reports `field='entry_pattern'` and `<= 120`. Add an unknown-value regression with `entry_pattern: not_a_breakout` and assert the loader reports `field='entry_pattern'` plus `expected one of`; this keeps the action-driving field tied to exact buy pattern IDs instead of arbitrary marker strings. Add a drift guard that imports `HybridPattern` from `sab.signals.hybrid_buy` and asserts the loader allowlist equals `{pattern.value for pattern in HybridPattern}`; if you derive the allowlist directly from the enum, keep the test to catch future accidental divergence.

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

Add the same exact-vs-substring and allowed-non-breakout regressions for the other structured marker fields. `pattern="swing_high_breakout"` and `signal_pattern="swing_high_breakout"` should trigger failed-breakout sells. `pattern="not_a_breakout"`, `signal_pattern="not_a_breakout"`, `pattern="trend_pullback_bounce"`, `signal_pattern="trend_pullback_bounce"`, `pattern="rsi_oversold_reversal"`, and `signal_pattern="rsi_oversold_reversal"` must not trigger merely because the key is present, the value is a valid non-breakout pattern, or the value contains the substring `breakout`. Also add legacy regressions proving a free-form `strategy` value containing `breakout` and a free-form `tags` value containing `breakout` still trigger the failed-breakout rule, because the planned implementation must tighten only structured fields and preserve old `strategy`/`tags` marker behavior.

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
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_yaml_contract.py tests/test_sell_evaluation_pnl.py::test_evaluate_holdings_passes_entry_pattern_to_hybrid_sell tests/test_sell_evaluation_pnl.py::test_evaluate_holdings_passes_loaded_entry_pattern_to_hybrid_sell tests/test_hybrid_sell_profit_tiers.py -q
```

Expected: FAIL because `Holding` has no `entry_pattern`, `_evaluate_holdings` does not forward `entry_pattern`, the loader does not yet fail closed on non-string, unknown, or overlong `entry_pattern`, the loader allowlist is not yet tied to the current `HybridPattern` IDs, and `_is_breakout_holding` still substring-matches structured `pattern`, `entry_pattern`, and `signal_pattern` values. The direct positive hybrid sell regression may already pass because `_is_breakout_holding` already recognizes the key; the full `tests/test_hybrid_sell_profit_tiers.py` run is intentional so the structured `pattern`/`signal_pattern` and legacy `strategy`/`tags` compatibility regressions cannot be skipped.

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

Add the allowed set near the helper; keep it local to holdings loading so this public YAML contract does not depend on evaluator internals:

```python
_ALLOWED_ENTRY_PATTERNS = frozenset(
    {
        "trend_pullback_bounce",
        "swing_high_breakout",
        "rsi_oversold_reversal",
    }
)
```

Do not change existing `strategy` or `settings.default_strategy` parsing in this task; `strategy` is already a sell marker and changing blank/default fallback semantics would be an unrelated behavior change.

In `_parse_holding`, keep the current `strategy` assignment and set the new field after it:

```python
        strategy=item.get("strategy") or settings.default_strategy,
        entry_pattern=_parse_optional_text_field(
            p,
            value=item.get("entry_pattern"),
            field_name="entry_pattern",
            item_index=item_index,
            ticker=ticker,
            max_length=120,
            allowed_values=_ALLOWED_ENTRY_PATTERNS,
        ),
```

- [ ] **Step 4: Tighten hybrid sell structured pattern semantics and forward `entry_pattern`**

In `sab/signals/hybrid_sell.py`, change `_is_breakout_holding` so `pattern`, `entry_pattern`, and `signal_pattern` are treated as exact structured buy pattern fields. Only `swing_high_breakout` should satisfy the failed-breakout pattern check. Keep the existing substring behavior for legacy free-form `strategy` and `tags` markers so older holdings are not broken.

In `sab/sell_evaluation.py`, add the field to `holding_dict` immediately after `strategy`:

```python
            "entry_pattern": getattr(holding, "entry_pattern", None),
```

This bridge is required because `_evaluate_holdings` builds a plain dict explicitly; adding a dataclass field alone does not reach `evaluate_sell_signals_hybrid`.

- [ ] **Step 5: Run Python contract tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_yaml_contract.py tests/test_sell_evaluation_pnl.py::test_evaluate_holdings_passes_entry_pattern_to_hybrid_sell tests/test_sell_evaluation_pnl.py::test_evaluate_holdings_passes_loaded_entry_pattern_to_hybrid_sell tests/test_hybrid_sell_profit_tiers.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Python contract**

```bash
git add sab/holdings_loader.py sab/signals/hybrid_sell.py sab/sell_evaluation.py tests/test_holdings_yaml_contract.py tests/test_sell_evaluation_pnl.py tests/test_hybrid_sell_profit_tiers.py
git commit -m "feat(holdings): 진입 패턴 YAML 계약 추가" -m "buy 후보의 pattern을 holdings entry_pattern으로 보존할 수 있도록 Python 로더와 sell 평가 경계를 확장한다."
```

## Task 2: Supabase Schema, RPC, Runtime Selects, And Web Mutation Schema

Deployment rule for this task: do not combine the DB migration and any runtime `entry_pattern` select/body changes in one deployable release unless reviewed deployment automation proves migrations run before runtime. The default path is two deployable PRs/releases: a DB-only migration release with executable smoke, then a runtime storage/export/web-mutation release after the target database has the column and RPC behavior. Keeping two commits in one branch is useful for review, but it is not sufficient as a deployment boundary.

**Files:**
- Create: `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql`
- Modify: `sab/scheduler/holdings.py`
- Modify: `.github/workflows/sell.yml`
- Modify: `.github/workflows/ai-brief.yml`
- Modify: `web/src/lib/types.ts`
- Create: `web/src/lib/holding-entry-pattern.ts`
- Modify: `web/src/lib/schemas.ts`
- Modify: `web/src/lib/supabase/holdings.ts`
- Defer: `web/src/lib/holdings-yaml.ts` parser/export/diff semantics stay in Task 3; do not add temporary missing-to-null behavior in this task. If TypeScript requires touching this helper after adding `HoldingSnapshot.entry_pattern`, implement the full Task 3 optional-key semantics immediately instead of a temporary default.
- Test: `tests/test_holdings_entry_pattern_contract.py`
- Test: `tests/test_scheduled_holdings_export.py`
- Test: `tests/test_workflow_holdings_loading.py`
- Test: `web/src/lib/__tests__/schemas.test.ts`
- Test: `web/src/lib/__tests__/supabase-admin.test.ts`
- Test fixtures if surfaced by typecheck: `web/src/app/api/holdings/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`, and `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`

- [ ] **Step 1: Write failing DB, export, and Supabase adapter tests**

In `web/src/lib/__tests__/supabase-admin.test.ts`, update the local holding fixture helper or individual expected `HoldingRecord` objects to include:

```ts
entry_pattern: null,
```

In the existing `replaceAllHoldings` test named
`"calls replace_holdings_v1 RPC with sanitized holdings snapshot"`, add
`entry_pattern` to the input row:

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

In the existing `addBuyToHolding` test named `"calls holdings_add_buy_v1 RPC and returns updated holding"`, return a row with a non-null `entry_pattern`, assert it is present on the returned row, and assert the RPC request body remains quantity-only:

```ts
const updated = await addBuyToHolding(/* existing args */);

expect(updated?.entry_pattern).toBe("swing_high_breakout");

const body =
  typeof requestInit?.body === "string"
    ? (JSON.parse(requestInit.body) as Record<string, unknown>)
    : null;
expect(body).not.toHaveProperty("p_entry_pattern");
```

Add direct Add Buy API/action negative coverage so the public Add Buy surface cannot accidentally start accepting a marker field. In `web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts`, add a request with `{ buy_quantity: 1, buy_price: 10, entry_pattern: "swing_high_breakout" }`, assert status 400 with `"Invalid holding add-buy payload"`, and assert `addBuyToHolding` was not called. Add the same rejection test to the public catch-all route at `web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts`. In `web/src/app/actions/__tests__/holdings.test.ts`, call `addBuyToHoldingAction` with the same extra `entry_pattern`, assert `{ ok: false, error: "Invalid holding add-buy payload" }`, and assert `addBuyToHolding` was not called. These tests may already pass because `holdingAddBuySchema.strict()` rejects unknown keys; keep them as contract guards.

In `web/src/lib/__tests__/schemas.test.ts`, add create/patch schema regressions proving normal holdings create/update payloads accept trimmed `entry_pattern`, accept explicit `null`, and reject unknown values such as `not_a_breakout`. This belongs in Task 2, not Task 3, because the first runtime release that can send `entry_pattern` to Supabase must also have public API/action schemas that accept the field after the DB migration is live. Keep Add Buy schema strict and covered by the negative tests above.

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

In `tests/test_workflow_holdings_loading.py`, extend `test_sell_workflow_loads_holdings_from_supabase_before_run_sell` so it fails if the cron workflow's inline Supabase export omits `entry_pattern`:

```python
    assert "entry_pattern" in run_script
    assert (
        "select=ticker,quantity,entry_price,entry_currency,entry_date,"
        "strategy,entry_pattern,notes,tags,stop_override,target_override"
        in run_script
    )
    assert '"entry_pattern",' in run_script
    assert 'key != "entry_pattern"' in run_script
```

Also assert the inline serializer preserves explicit null for `entry_pattern` while continuing to omit null for legacy optional fields. Add a sibling workflow regression for `.github/workflows/ai-brief.yml` that finds its manual `Load holdings from Supabase` step and checks the same selected field string, Python `keys` tuple, and `entry_pattern` null-preservation condition. The scheduled AI Brief job uses `sab ai-brief-scheduled` and the Python scheduler export helper; keep that coverage in `tests/test_scheduled_holdings_export.py` and do not treat the manual inline workflow test as proof of scheduled-job behavior.

Create `tests/test_holdings_entry_pattern_contract.py`. Import `HybridPattern` from `sab.signals.hybrid_buy` and derive the expected pattern IDs from `{pattern.value for pattern in HybridPattern}` for migration allowlist assertions instead of hardcoding an independent Python set. The SQL still stores explicit values, but the static contract test must fail if the buy-pattern enum changes and the migration/RPC constraints are not updated.

```python
from __future__ import annotations

import re
from pathlib import Path


_MIGRATION_PATH = Path(
    "supabase/migrations/20260609000000_add_holdings_entry_pattern.sql"
)
_ADD_BUY_MIGRATION_PATH = Path(
    "supabase/migrations/20260304002000_add_holdings_add_buy_idempotency.sql"
)


def _normalize_sql(sql: str) -> str:
    normalized = re.sub(r"\s+", " ", sql.lower()).strip()
    return normalized.replace("( ", "(").replace(" )", ")")


def test_holdings_entry_pattern_migration_updates_replace_holdings_contract() -> None:
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")
    normalized_sql = _normalize_sql(sql)

    required_snippets = [
        "add column if not exists entry_pattern text null",
        "add constraint holdings_entry_pattern_length_check",
        "char_length(entry_pattern) <= 120",
        "add constraint holdings_entry_pattern_value_check",
        "entry_pattern in ('trend_pullback_bounce', 'swing_high_breakout', 'rsi_oversold_reversal')",
        "jsonb_typeof(incoming.item->'entry_pattern') <> 'string'",
        "incoming holdings entry_pattern must be a string",
        "incoming holdings entry_pattern must be <= 120 chars",
        "incoming holdings entry_pattern must be one of",
        "has_entry_pattern boolean not null",
        "entry_pattern text null",
        "incoming.item ? 'entry_pattern'",
        "case when incoming.has_entry_pattern then incoming.entry_pattern else existing.entry_pattern end",
        "incoming.has_entry_pattern and existing.entry_pattern is distinct from incoming.entry_pattern",
        "entry_pattern text null",
        "incoming.entry_pattern",
        "revoke all on function public.replace_holdings_v1(jsonb) from anon",
        "revoke all on function public.replace_holdings_v1(jsonb) from authenticated",
        "revoke all on function public.replace_holdings_v1(jsonb) from public",
        "grant execute on function public.replace_holdings_v1(jsonb) to service_role",
        "revoke all on function public.holdings_add_buy_v1(",
        "grant execute on function public.holdings_add_buy_v1(",
    ]
    for snippet in required_snippets:
        assert _normalize_sql(snippet) in normalized_sql

    forbidden_snippets = [
        "grant execute on function public.replace_holdings_v1(jsonb) to anon",
        "grant execute on function public.replace_holdings_v1(jsonb) to authenticated",
        "grant execute on function public.replace_holdings_v1(jsonb) to public",
        "disable row level security",
    ]
    for snippet in forbidden_snippets:
        assert _normalize_sql(snippet) not in normalized_sql


def test_add_buy_rpc_does_not_accept_or_update_entry_pattern() -> None:
    sql = _ADD_BUY_MIGRATION_PATH.read_text(encoding="utf-8")
    function_sql = sql[
        sql.index("create or replace function public.holdings_add_buy_v1") :
    ]
    new_migration_sql = _normalize_sql(_MIGRATION_PATH.read_text(encoding="utf-8"))

    assert "create or replace function public.holdings_add_buy_v1" not in new_migration_sql
    assert "p_entry_pattern" not in new_migration_sql

    required_snippets = [
        "returns setof public.holdings",
        "returning *",
        "from public.holdings",
    ]
    for snippet in required_snippets:
        assert snippet in function_sql

    forbidden_snippets = [
        "p_entry_pattern",
        "entry_pattern =",
        "entry_pattern,",
    ]
    for snippet in forbidden_snippets:
        assert snippet not in function_sql
```

- [ ] **Step 2: Run Supabase contract tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_entry_pattern_contract.py tests/test_scheduled_holdings_export.py tests/test_workflow_holdings_loading.py -q
pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/supabase-admin.test.ts
pnpm --dir web run test -- web/src/app/actions/__tests__/holdings.test.ts "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts" "web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts"
```

Expected: FAIL from TypeScript/type drift, because `replaceAllHoldings` does not include `entry_pattern`, because shared holdings select queries and create/update response selects do not include `entry_pattern`, because scheduled export paths do not select/write it yet, because `sell.yml` and `ai-brief.yml` inline exports do not select/write it yet, and because the new migration file does not exist yet. The Add Buy negative route/action tests may already pass because the current strict schema rejects unknown keys; keep them in the command as non-regression contract guards.

- [ ] **Step 3: Add the migration**

Create `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql`:

Compatibility decision: `replace_holdings_v1` must preserve an existing `entry_pattern` when an incoming row omits the key entirely, so old callers and older YAML snapshots do not silently wipe the new marker. A caller can still clear the field explicitly by sending `"entry_pattern": null` or a blank string. Track key presence with `has_entry_pattern`; `jsonb_to_recordset` alone cannot distinguish an absent key from an explicit null.

```sql
alter table public.holdings
  add column if not exists entry_pattern text null;

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
    and (
      not incoming.has_entry_pattern
      or existing.entry_pattern is not distinct from incoming.entry_pattern
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
        or (
          incoming.has_entry_pattern
          and existing.entry_pattern is distinct from incoming.entry_pattern
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
      incoming.entry_pattern,
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

revoke all on function public.replace_holdings_v1(jsonb) from anon;
revoke all on function public.replace_holdings_v1(jsonb) from authenticated;
revoke all on function public.replace_holdings_v1(jsonb) from public;
grant execute on function public.replace_holdings_v1(jsonb) to service_role;

revoke all on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date,
  text
) from anon;
revoke all on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date,
  text
) from authenticated;
revoke all on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date,
  text
) from public;
grant execute on function public.holdings_add_buy_v1(
  text,
  numeric,
  numeric,
  date,
  text
) to service_role;
```

- [ ] **Step 4: Run executable migration smoke**

Run the static contract test first, then apply the migration to a disposable/local database before enabling runtime selects. Preferred path is the repository's local Supabase workflow if available; otherwise use an equivalent disposable Postgres/Supabase target and record the command used in the PR notes.

Required smoke assertions after applying the migration:

```sql
select 1
from information_schema.columns
where table_schema = 'public'
  and table_name = 'holdings'
  and column_name = 'entry_pattern';
```

Also exercise `replace_holdings_v1` manually or with a DB integration test for these cases:

- incoming row with `"entry_pattern": "swing_high_breakout"` stores the value.
- incoming row omitting `entry_pattern` preserves an existing non-null value when no other fields change.
- incoming row omitting `entry_pattern` preserves an existing non-null value while another field such as `notes` changes, proving the update branch preserves the marker and not only the unchanged branch.
- incoming row with `"entry_pattern": null` clears it.
- incoming row with an `entry_pattern` longer than 120 characters fails with an actionable error or the DB length constraint.
- incoming row with an unknown `entry_pattern` such as `not_a_breakout` fails with an actionable error or the DB allowed-value constraint.
- `holdings_add_buy_v1` updates quantity/price/date while preserving a non-null `entry_pattern`, including idempotent replay from a post-migration idempotency event.

Record the historical replay decision explicitly: pre-migration `holdings_add_buy_events.result_payload` rows cannot contain `entry_pattern`, so either backfill/expire those events before rollout or document that only post-migration idempotency replays preserve a non-null `entry_pattern` in the replay response.

Before enabling runtime code that selects or mutates `entry_pattern`, run a service-role PostgREST smoke against the target database, not only SQL introspection. At minimum, verify the exact column projection used by runtime succeeds:

```bash
curl -fsS "${SUPABASE_URL%/}/rest/v1/holdings?select=ticker,entry_pattern&limit=1" \
  -H "apikey: ${SUPABASE_SECRET_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SECRET_KEY}" \
  -H "Accept: application/json"
```

Also run one rollback-safe PostgREST write path before runtime rollout: either a temporary insert/patch/delete through `/rest/v1/holdings` using `entry_pattern`, or a `replace_holdings_v1` RPC call through `/rest/v1/rpc/replace_holdings_v1` that sets, preserves-on-omit, and clears `entry_pattern`. This catches PostgREST schema-cache or privilege issues that `information_schema` checks can miss.

Also verify the effective RPC definitions and privileges after applying the migration, not only the historical migration files:

```sql
select pg_get_functiondef('public.holdings_add_buy_v1(text,numeric,numeric,date,text)'::regprocedure);
select has_function_privilege('service_role', 'public.replace_holdings_v1(jsonb)', 'execute');
select has_function_privilege('service_role', 'public.holdings_add_buy_v1(text,numeric,numeric,date,text)', 'execute');
```

The effective `holdings_add_buy_v1` definition must not contain `p_entry_pattern`, and service-role PostgREST/RPC calls to both functions must succeed. If practical, also assert anon/authenticated cannot execute the service-role-only RPCs.

If no executable DB target is available, do not mark the migration fully verified; record that only static SQL contract tests ran and keep final verification blocked until an executable migration apply is completed.

- [ ] **Step 5: Add `entry_pattern` to scheduled holdings export paths**

In `sab/scheduler/holdings.py`, add the field to `_HOLDINGS_FIELDS` immediately after `strategy`:

```python
    "strategy",
    "entry_pattern",
    "notes",
```

Before editing the export field list, fix the existing Python syntax blocker in this module if still present: `except TypeError, ValueError:` must be `except (TypeError, ValueError):`. Otherwise the scheduled export tests can fail before exercising the `entry_pattern` contract.

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

Then change the inline serializer loop so it keeps explicit null only for `entry_pattern`, and fails loudly if the selected response omits that key:

```python
                  if key == "entry_pattern" and key not in row:
                      raise SystemExit("Supabase holdings response omitted entry_pattern")
                  if value is None and key != "entry_pattern":
                      continue
                  item[key] = value
```

Apply the same query, `keys` tuple, and null-preserving loop change to `.github/workflows/ai-brief.yml` in its manual `Load holdings from Supabase` step. Both workflows currently write JSON syntax to generated holdings files; keep that shape unchanged because JSON is valid YAML. Scheduled AI Brief coverage still comes from `sab/scheduler/holdings.py` through `sab ai-brief-scheduled`, so keep the Python scheduler export tests as the scheduled-path proof.

- [ ] **Step 6: Wire web Supabase types, mutation schemas, and replace-all payload**

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

New create/update callers can send `entry_pattern` explicitly through the normal mutation schemas added in this task. Replace-all callers must preserve key presence: `entry_pattern: null` intentionally clears the field, `entry_pattern: undefined` is treated like omission, and omitting the key preserves the existing DB value through the DB-level compatibility behavior.

Do not add a temporary `web/src/lib/holdings-yaml.ts` implementation that collapses omitted YAML `entry_pattern` into `null`. The parser, export, diff, and route pass-through changes are one atomic Task 3 checkpoint. If this task's type changes force `holdings-yaml.ts` edits before Task 3, move the full Task 3 YAML optional-key implementation forward and run its tests in the same checkpoint.

- [ ] **Step 7: Run Supabase contract tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_holdings_entry_pattern_contract.py tests/test_scheduled_holdings_export.py tests/test_workflow_holdings_loading.py -q
pnpm --dir web run test -- web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/supabase-admin.test.ts
pnpm --dir web run test -- web/src/app/actions/__tests__/holdings.test.ts "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts" "web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts"
```

Expected: PASS. The Add Buy negative tests may already pass before implementation because the current strict Add Buy schema rejects unknown keys; their purpose is to lock the quantity-only API contract.

- [ ] **Step 8: Sweep web fixture fallout and typecheck**

Update every `HoldingRecord` or ordinary `HoldingSnapshot` fixture surfaced by these commands to include `entry_pattern: null` or a specific test value, and include every edited fixture file in this task's commit. Fixtures intended to model old YAML import input may use `HoldingReplaceSnapshot` and omit `entry_pattern` deliberately:

```bash
rg -n "HoldingRecord|HoldingSnapshot|HoldingReplaceSnapshot|strategy: null|strategy: \"swing\"" web/src web/src/lib/__tests__
pnpm --dir web run typecheck
```

Expected: `rg` identifies only reviewed fixture locations, and `pnpm --dir web run typecheck` passes after those fixtures and, if required by TypeScript, the full Task 3 YAML optional-key implementation is present. Do not satisfy typecheck by temporarily normalizing omitted import keys to `null`. At minimum, check these existing fixture-heavy tests: `web/src/lib/__tests__/holding-activity.test.ts`, `web/src/lib/__tests__/add-buy-precheck.test.ts`, `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, `web/src/app/actions/__tests__/holdings.test.ts`, `web/src/app/api/holdings/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`, `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`, `web/src/app/api/holdings/yaml/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts`, `web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.integration.test.ts`, and `web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts`.

- [ ] **Step 9: Commit Supabase contract**

Use two deployable PRs/releases by default. First commit/PR only the migration and DB/static contract tests, then apply and smoke the migration against the target database. After that smoke is recorded and the DB-only release is live, commit/deploy the runtime select/body/export/schema changes. A single combined deployable change is allowed only if a reviewed deployment automation guarantees migrations apply before runtime execution.

```bash
git add supabase/migrations/20260609000000_add_holdings_entry_pattern.sql tests/test_holdings_entry_pattern_contract.py
git commit -m "feat(db): 보유 종목 진입 패턴 컬럼 추가" -m "holdings.entry_pattern 컬럼과 replace_holdings_v1 보존 계약을 추가한다. 런타임 select 변경은 DB 적용 smoke 이후 별도 커밋에서 진행한다."

# After DB apply/smoke is recorded:
# If Task 3 YAML optional-key work was pulled forward to satisfy this task's typecheck, stage `web/src/lib/holdings-yaml.ts` and `web/src/lib/__tests__/holdings-yaml.test.ts` in this runtime commit too.
git add sab/scheduler/holdings.py .github/workflows/sell.yml .github/workflows/ai-brief.yml tests/test_scheduled_holdings_export.py tests/test_workflow_holdings_loading.py web/src/lib/types.ts web/src/lib/holding-entry-pattern.ts web/src/lib/schemas.ts web/src/lib/supabase/holdings.ts web/src/lib/__tests__/schemas.test.ts web/src/lib/__tests__/supabase-admin.test.ts web/src/lib/__tests__/holding-activity.test.ts web/src/lib/__tests__/add-buy-precheck.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts" web/src/app/api/holdings/yaml/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.test.ts" "web/src/app/api/holdings/[ticker]/add-buy/__tests__/route.integration.test.ts" "web/src/app/api/holdings/add-buy/[...ticker]/__tests__/route.test.ts"
git commit -m "feat(holdings): 진입 패턴 런타임 저장 경로 연결" -m "DB 적용 이후 scheduled export와 웹 Supabase 클라이언트가 entry_pattern을 선택·보존하도록 확장한다."
```

## Task 3: Web YAML, Form, And Table

**Files:**
- Modify: `web/src/lib/holdings-yaml.ts`
- Modify: `web/src/components/holdings/form-state.ts`
- Modify: `web/src/components/holdings/helpers.ts`
- Modify: `web/src/components/holdings/holdings-form-panel.tsx`
- Modify: `web/src/components/holdings/holdings-table.tsx`
- Modify: `web/src/components/holdings/holdings-import-panel.tsx`
- Modify: `web/src/components/holdings/use-holdings-import.ts`
- Modify if using secondary table metadata: `web/src/components/holdings-client.module.css`
- Test: `web/src/lib/__tests__/holdings-yaml.test.ts`
- Test: `web/src/app/actions/__tests__/holdings.test.ts`
- Test: `web/src/app/api/holdings/__tests__/route.test.ts`
- Test: `web/src/app/api/holdings/[ticker]/__tests__/route.test.ts`
- Test: `web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts`
- Test: `web/src/app/api/holdings/yaml/__tests__/route.test.ts`
- Test: `web/src/lib/__tests__/holdings-client-hooks.test.tsx`

- [ ] **Step 1: Write failing web YAML, route, and UI tests**

Schema create/patch validation was added in Task 2 with the first web runtime persistence release. Do not duplicate that work here; Task 3 starts from YAML parser/export/diff and UI behavior.

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
it("treats omitted entry_pattern as preserve-existing during YAML diff", () => {
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

In `web/src/app/api/holdings/yaml/__tests__/route.test.ts`, add apply-path coverage that posts an old YAML document without `entry_pattern`, asserts `replaceAllHoldings` receives a row without an owned `entry_pattern` property, separately posts `entry_pattern: null` and asserts the row owns `entry_pattern` with `null`, and separately posts blank `entry_pattern` and asserts the row owns `entry_pattern` with `null`. This catches the route-level pass-through because the route calls `parseHoldingsYamlDocument(...)` and then `replaceAllHoldings(...)`.

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
it("passes entry_pattern through patch payload", async () => {
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
    makePatchRequest({ entry_pattern: " swing_high_breakout " }),
    makeContext("005930"),
  );

  expect(response.status).toBe(200);
  expect(vi.mocked(updateHolding)).toHaveBeenCalledWith("005930", {
    entry_pattern: "swing_high_breakout",
  });
});
```

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

Add a patch regression in the same file:

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

Also add the Add Buy action negative regression from Task 2 if it was not already added there: a payload with `buy_quantity`, `buy_price`, and `entry_pattern` must return `"Invalid holding add-buy payload"` and must not call `addBuyToHolding`.

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

Add an edit-preservation regression in the same block. Render a row with `entry_pattern: "swing_high_breakout"`, click `Edit`, assert the `entryPattern` select is prefilled, change an unrelated field such as `notes`, submit, and assert the saved payload still includes the original `entry_pattern`. This catches `recordToForm` mapping mistakes that would clear the marker during ordinary edits:

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

- [ ] **Step 2: Run targeted web tests to verify failure**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/holdings-yaml.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts" web/src/app/api/holdings/yaml/__tests__/route.test.ts
```

Expected: FAIL because `entry_pattern` is not round-tripped/diffed by YAML helpers, generated YAML export omits explicit `entry_pattern: null`, non-string, unknown, and overlong YAML values are not rejected yet, omitted YAML `entry_pattern` is not preserved as an omitted replace-all key yet, blank YAML `entry_pattern` is not treated as an explicit clear yet, the import panel and apply-confirmation copy still describe a literal full replacement, and the form/table do not expose or submit the field yet. Strict create/patch schema acceptance was already covered in Task 2.

- [ ] **Step 3: Update YAML helpers**

Use the shared `web/src/lib/holding-entry-pattern.ts` helper introduced in Task 2 for all web-side `entry_pattern` validation. Do not redeclare the allowed set in this module.

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

- [ ] **Step 4: Update form state, payload helpers, import copy, and UI**

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
    entry_pattern: stringOrNull(form.entry_pattern),
```

In `web/src/components/holdings/holdings-form-panel.tsx`, add this label after the Strategy input. Use a select/menu instead of free-form text because `entry_pattern` is an enum-like field with three allowed IDs:

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
            <option value="trend_pullback_bounce">trend_pullback_bounce</option>
            <option value="swing_high_breakout">swing_high_breakout</option>
            <option value="rsi_oversold_reversal">rsi_oversold_reversal</option>
          </select>
        </label>
```

In `web/src/components/holdings/holdings-import-panel.tsx`, update the explanatory copy so it still says apply replaces the holdings snapshot, but explicitly notes that omitted `entry_pattern` in older YAML preserves the existing DB value and `entry_pattern: null` or blank clears it. Keep this concise; it is an operational warning, not a tutorial.

In `web/src/components/holdings/use-holdings-import.ts`, update the apply confirmation string for the same contract. The confirmation must not say the DB is literally replaced by the uploaded file without qualification. In `web/src/lib/__tests__/holdings-client-hooks.test.tsx`, extend the existing `useHoldingsImport` apply test to assert `confirm.mock.calls[0]?.[0]` contains `entry_pattern`, `preserve`/`보존`, and `null` or `blank`/`빈 값`.

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

- [ ] **Step 5: Run targeted web tests**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/holdings-yaml.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts" web/src/app/api/holdings/yaml/__tests__/route.test.ts
```

Expected: PASS.

- [ ] **Step 6: Run holdings UI smoke check**

Run:

```bash
pnpm --dir web run typecheck
```

If a local web target is available, open `/holdings` at desktop and mobile widths and verify the Entry Pattern display is visible without overlapping Tags, Updated, or Action controls. Use the running `sab-web` container at `http://127.0.0.1:${WEB_HOST_PORT:-55300}` when available; otherwise record that visual smoke is deferred to Final Verification.

Expected: typecheck passes, and the holdings table/form remains readable at both widths. The Entry Pattern control is a select/menu with the empty value plus the three allowed pattern IDs, so users cannot create schema-invalid values from the normal UI.

- [ ] **Step 7: Commit web holdings surface**

```bash
git add web/src/lib/holdings-yaml.ts web/src/components/holdings/form-state.ts web/src/components/holdings/helpers.ts web/src/components/holdings/holdings-form-panel.tsx web/src/components/holdings/holdings-table.tsx web/src/components/holdings/holdings-import-panel.tsx web/src/components/holdings/use-holdings-import.ts web/src/components/holdings-client.module.css web/src/lib/__tests__/holdings-yaml.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/actions/__tests__/holdings.test.ts web/src/app/api/holdings/__tests__/route.test.ts "web/src/app/api/holdings/[ticker]/__tests__/route.test.ts" "web/src/app/api/holdings/[...ticker]/__tests__/route.test.ts" web/src/app/api/holdings/yaml/__tests__/route.test.ts
git commit -m "feat(web): 보유 종목 진입 패턴 입력 추가" -m "웹 holdings 입력 화면과 YAML import/export 경로에서 entry_pattern을 보존한다."
```

## Task 4: Recent Buy Candidate Pattern Propagation

**Files:**
- Modify: `web/src/lib/ticker-directory.ts`
- Modify: `web/src/components/holdings/use-ticker-lookup.ts`
- Modify: `web/src/components/holdings/use-recent-candidates.ts`
- Modify: `web/src/components/holdings/holdings-form-panel.tsx`
- Modify: `web/src/components/holdings-client.tsx`
- Modify if adding a new pattern metadata style: `web/src/components/holdings-client.module.css`
- Test: `web/src/lib/__tests__/ticker-directory.test.ts`
- Test: `web/src/lib/__tests__/holdings-client-hooks.test.tsx`
- Test: `web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts`

- [ ] **Step 1: Write failing recent-candidate tests**

In `web/src/lib/__tests__/ticker-directory.test.ts`, update `"extracts ticker/name pairs and canonicalizes slash class ticker"` so the first candidate has a pattern:

```ts
          pattern: "swing_high_breakout",
```

and expect:

```ts
        pattern: "swing_high_breakout",
```

Update `"deduplicates ticker while keeping the first seen order"` expected rows to include `pattern: null` unless the input has a pattern.

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

Add a client-boundary regression in `web/src/lib/__tests__/holdings-client-hooks.test.tsx` for `parseTickerLookupResults` or `useRecentCandidates`: when the API payload contains `{ ticker: "AAPL.NAS", name: "Apple", pattern: "not_a_breakout" }`, the parsed candidate must keep `ticker`/`name` but expose `pattern: null`. This catches invalid values from stale API payloads or mocked route responses after server extraction has been bypassed.

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

Add the negative regression in the same block:

```ts
it("does not clear an existing entry pattern when a recent candidate has no pattern", async () => {
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

- Select a recent candidate with `pattern`, then manually type a different ticker in the main `ticker` input; assert the candidate-derived `entryPattern` is cleared.
- Select a recent candidate with `pattern`, then use ticker search to select another ticker; assert the candidate-derived `entryPattern` is cleared.
- Select a recent candidate with `pattern`, then click `Edit` on an existing holding with its own `entry_pattern`; assert the edit-loaded value is shown and later no-pattern candidate selection does not treat the edit-loaded value as candidate-derived.
- Select a recent candidate with `pattern`, submit or cancel the form, then assert the next create form starts with empty `entryPattern` and no stale candidate source state.

These tests distinguish manual/edit-loaded values from candidate-derived values and catch stale breakout markers moving to a different ticker.

- [ ] **Step 2: Run recent-candidate tests to verify failure**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/ticker-directory.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts
```

Expected: FAIL because recent candidate parsing drops `pattern`, the client parser does not yet null out unknown pattern IDs, the UI does not expose pattern metadata, candidate-derived entry patterns are not yet cleared when a later no-pattern candidate is selected, and stale candidate-derived markers are not yet cleared on manual ticker changes, ticker-search selection, or form lifecycle transitions.

- [ ] **Step 3: Preserve `pattern` in ticker-directory recent candidates**

In `web/src/lib/ticker-directory.ts`, import `isHoldingEntryPattern` from `web/src/lib/holding-entry-pattern.ts`, then change `TickerDirectoryCandidate`:

```ts
export interface TickerDirectoryCandidate {
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

In `extractBuyCandidatesFromReport`, read `pattern`:

```ts
    const raw = row as { ticker?: unknown; name?: unknown; pattern?: unknown };
```

and return it:

```ts
      pattern: normalizeCandidatePattern(raw.pattern),
```

In `mergeCandidatesFromReport`, no directory search behavior needs to use `pattern`; keep aliasing based on ticker/name only.

- [ ] **Step 4: Parse pattern in client hooks**

In `web/src/components/holdings/use-ticker-lookup.ts`, import `isHoldingEntryPattern` from `web/src/lib/holding-entry-pattern.ts` and extend the type:

```ts
export interface TickerLookupResult {
  ticker: string;
  name: string | null;
  pattern?: string | null;
}
```

In `parseTickerLookupResults`, first widen the local raw type:

```ts
    const raw = item as { ticker?: unknown; name?: unknown; pattern?: unknown };
```

Then read and validate `pattern` against the allowed IDs. Unknown strings become `null`, not a free-form marker:

```ts
    const rawPattern = typeof raw.pattern === "string" ? raw.pattern.trim() : "";
    const pattern =
      rawPattern && isHoldingEntryPattern(rawPattern) ? rawPattern : null;
```

Because ticker search responses do not include `pattern`, conditionally omit `pattern` unless the raw payload included that key:

```ts
    const result: TickerLookupResult = {
      ticker,
      name: name || null,
    };
    if ("pattern" in raw) {
      result.pattern = pattern;
    }
    results.push(result);
```

Use the conditional form so existing ticker-search UI tests stay focused on ticker/name.

`web/src/components/holdings/use-recent-candidates.ts` can keep using `parseTickerLookupResults`; its `candidates` now carry `pattern` when the API sends it.

- [ ] **Step 5: Populate `entry_pattern` when selecting a recent candidate**

In `web/src/components/holdings/holdings-form-panel.tsx`, import the shared candidate type if needed and add a small `.lookupPattern` style if no suitable secondary metadata class already exists:

```tsx
import type { TickerLookupResult } from "./use-ticker-lookup";
```

Change `recentCandidates` prop from `TickerLookupItem[]` to:

```ts
  recentCandidates: TickerLookupResult[];
```

Add a callback prop:

```ts
  onSelectRecentCandidate: (candidate: TickerLookupResult) => void;
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
import type { TickerLookupResult } from "@/components/holdings/use-ticker-lookup";
```

Track whether the current `entry_pattern` came from a recent candidate, including the ticker it belongs to, so a later no-pattern candidate can clear stale candidate-derived metadata without clearing manual/edit-loaded values:

```tsx
  const [recentCandidateEntryPatternSource, setRecentCandidateEntryPatternSource] =
    useState<{ ticker: string; pattern: string } | null>(null);

  const clearCandidateDerivedEntryPattern = useCallback(() => {
    if (
      recentCandidateEntryPatternSource !== null &&
      form.entry_pattern === recentCandidateEntryPatternSource.pattern
    ) {
      updateField("entry_pattern", "");
    }
    setRecentCandidateEntryPatternSource(null);
  }, [form.entry_pattern, recentCandidateEntryPatternSource, updateField]);

  const handleFieldChange = useCallback(
    (field: keyof HoldingFormState, value: string) => {
      if (field === "entry_pattern") {
        setRecentCandidateEntryPatternSource(null);
        updateField(field, value);
        return;
      }
      if (field === "ticker") {
        clearCandidateDerivedEntryPattern();
      }
      updateField(field, value);
    },
    [clearCandidateDerivedEntryPattern, updateField],
  );
```

Use the same clearing helper for ticker-search selection, and reset source state when entering edit mode, canceling edit, or after a successful submit/reset. A simple way is to wrap `beginEdit`, `cancelEdit`, and ticker lookup selection in `HoldingsClient`; if implementing a form hook callback is cleaner, keep the source-reset behavior covered by the tests above.

Add the callback before `return`:

```tsx
  const selectRecentCandidate = useCallback(
    (candidate: TickerLookupResult) => {
      updateField("ticker", candidate.ticker);
      if (candidate.pattern) {
        updateField("entry_pattern", candidate.pattern);
        setRecentCandidateEntryPatternSource({
          ticker: candidate.ticker,
          pattern: candidate.pattern,
        });
        return;
      }
      clearCandidateDerivedEntryPattern();
    },
    [clearCandidateDerivedEntryPattern, updateField],
  );
```

Only preserve `entry_pattern` for a no-pattern candidate when the current value is manual/edit-loaded. If the current value was populated by a prior recent candidate, clear it to avoid carrying a stale breakout sell marker to a different ticker. Any non-recent ticker change must also clear candidate-derived values; otherwise a user can select one breakout candidate and accidentally save that marker on a different ticker.

Pass both the wrapped field handler and the recent-candidate callback:

```tsx
          onFieldChange={handleFieldChange}
          onSelectRecentCandidate={selectRecentCandidate}
```

- [ ] **Step 6: Run recent-candidate tests**

Run:

```bash
pnpm --dir web run test -- web/src/lib/__tests__/ticker-directory.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit recent-candidate propagation**

```bash
git add web/src/lib/ticker-directory.ts web/src/components/holdings/use-ticker-lookup.ts web/src/components/holdings/use-recent-candidates.ts web/src/components/holdings/holdings-form-panel.tsx web/src/components/holdings-client.tsx web/src/components/holdings-client.module.css web/src/lib/__tests__/ticker-directory.test.ts web/src/lib/__tests__/holdings-client-hooks.test.tsx web/src/app/api/tickers/recent-candidates/__tests__/route.test.ts
git commit -m "feat(web): 최근 매수 후보 패턴 보존" -m "최근 buy 후보 API와 holdings 입력 플로우가 후보 pattern을 entry_pattern으로 전달하도록 연결한다."
```

## Task 5: Documentation

**Files:**
- Modify: `docs/holdings-schema.md`
- Modify: `docs/holdings-add-buy.md`
- Modify: `docs/STRATEGY.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/local-docker-scheduler-plan.md`
- Modify if stale wording exists: `docs/holdings-ticker-lookup.md`
- Modify if stale wording exists: `docs/adr/ADR-0008-holdings-ticker-directory.md`
- Modify: `holdings.example.yaml`

- [ ] **Step 1: Update holdings schema docs**

In `docs/holdings-schema.md`, add `entry_pattern` to the example row after `strategy` and document that the value is trimmed, nullable, explicitly exported as `null` when absent, limited to 120 characters, and restricted to the current buy pattern IDs across DB/RPC/YAML/web mutation paths. Also document the import/export semantic exception: generated exports always include `entry_pattern` with either a value or `null`; YAML/import/replace-all inputs that omit the key preserve the existing DB value for that field, while explicit `entry_pattern: null` or blank clears it.

```yaml
    strategy: sma_ema_hybrid
    entry_pattern: swing_high_breakout
```

Add this row to the field table after `strategy`:

```markdown
| `entry_pattern` | string (선택, 최대 120자) | buy/entry report의 `pattern`을 보유 상태에 보존한 값. 허용값: `trend_pullback_bounce`, `swing_high_breakout`, `rsi_oversold_reversal`; `swing_high_breakout`만 hybrid sell의 failed-breakout 판정에 사용 |
```

Add this note near the sell command section:

```markdown
- `sma_ema_hybrid` breakout 후보를 보유로 전환할 때는 `entry_pattern`에 buy/entry report의 `pattern` 값을 보존하세요. `sab sell`은 `entry_pattern: swing_high_breakout`을 exact pattern marker로 인식해 `strategy`/`tags` 수동 마커 없이 failed-breakout 규칙을 적용합니다.
```

- [ ] **Step 2: Update Add Buy docs**

In `docs/holdings-add-buy.md`, add this contract note near the API/RPC contract section:

```markdown
- Add Buy는 수량, 평단, 진입일, 통화만 갱신하며 기존 holdings row의 `entry_pattern`은 보존합니다. buy/entry report의 `pattern`을 새로 기록해야 하는 경우 holdings 생성/수정 또는 YAML import 경로에서 `entry_pattern`을 설정하세요. 이 RPC는 `entry_pattern`을 추론하거나 덮어쓰지 않습니다.
```

- [ ] **Step 3: Update strategy docs**

In `docs/STRATEGY.md`, replace the note that says holdings only forwards `strategy` and `tags` with:

```markdown
  - 하위 hybrid sell evaluator는 `strategy`, `tags`, `pattern`, `entry_pattern`, `signal_pattern` marker를 인식합니다. 운영 holdings 계약은 buy/entry report의 `pattern`을 `entry_pattern`으로 보존해 breakout 매수의 failed-breakout sell 규칙이 수동 태그 없이도 적용되도록 합니다.
```

- [ ] **Step 4: Update architecture docs**

In `docs/ARCHITECTURE.md`, update the web holdings CRUD flow note that currently says ticker directory candidates are derived from `candidates[].{ticker,name}`. Replace it with:

```markdown
   - 검색/후보 데이터는 buy 리포트(`candidates[].{ticker,name,pattern}`)에서 파생한 “티커 디렉토리(캐시)”를 사용합니다. 최근 buy 후보 선택은 후보 `pattern`을 holdings 입력의 `entry_pattern`으로 전달해, breakout 매수의 sell marker를 보존합니다.
```

Also add short notes under the workflow holdings bridge sections:

```markdown
- scheduled `sell.yml`은 Supabase `holdings`에서 `entry_pattern`까지 export한 `holdings.generated.yaml`을 `sab sell --holdings`에 전달합니다.
- scheduled AI Brief는 Python scheduler export helper가 Supabase `holdings`에서 `entry_pattern`까지 export한 holdings snapshot을 사용합니다.
- `.github/workflows/ai-brief.yml`의 manual `ai_brief` job inline holdings bridge도 `entry_pattern`까지 export해 manual downstream entry/brief context가 동일한 holdings contract를 사용합니다.
```

Review `docs/holdings-ticker-lookup.md` and `docs/adr/ADR-0008-holdings-ticker-directory.md` for stale `candidates[].{ticker,name}`-only wording. Update them if they describe recent buy candidate payload shape or holdings candidate selection behavior; leave them unchanged only if they discuss search-directory cache behavior that intentionally remains ticker/name-only.

- [ ] **Step 5: Update local Docker scheduler docs**

In `docs/local-docker-scheduler-plan.md`, update the scheduled AI Brief holdings export field list that currently says the active export uses `ticker`, `quantity`, `entry_price`, `entry_currency`, `entry_date`, `strategy`, `notes`, `tags`, `stop_override`, and `target_override`. Insert `entry_pattern` immediately after `strategy`, matching the Python scheduler helper and the manual GitHub workflow bridge:

```markdown
   - 필드는 current GitHub workflow와 같은 `ticker`, `quantity`, `entry_price`, `entry_currency`, `entry_date`, `strategy`, `entry_pattern`, `notes`, `tags`, `stop_override`, `target_override`를 사용합니다.
```

- [ ] **Step 6: Update example YAML**

In `holdings.example.yaml`, add `entry_pattern` to the first swing example:

```yaml
    strategy: sma_ema_hybrid
    entry_pattern: swing_high_breakout
```

If the example currently uses `strategy: swing`, change only that example row to `sma_ema_hybrid`; leave unrelated examples unchanged.

- [ ] **Step 7: Run static docs check**

Run:

```bash
rg -n 'entry_pattern|failed-breakout|failed breakout|candidates\[\].*pattern' docs/holdings-schema.md docs/holdings-add-buy.md docs/STRATEGY.md docs/ARCHITECTURE.md docs/local-docker-scheduler-plan.md holdings.example.yaml
if rg -n 'holdings.*only.*strategy.*tags|strategy.*tags.*만|`strategy`, `notes`' docs/STRATEGY.md docs/ARCHITECTURE.md docs/local-docker-scheduler-plan.md; then
  exit 1
fi
rg -n 'candidates\[\].*\{ticker,name\}' docs/holdings-ticker-lookup.md docs/adr/ADR-0008-holdings-ticker-directory.md || true
```

Expected: output shows `entry_pattern` documented in holdings schema, Add Buy docs, strategy docs, architecture flow docs, local Docker scheduler docs, and example YAML; the negative check produces no stale contradictory wording. Any remaining `candidates[].{ticker,name}` hits in `docs/holdings-ticker-lookup.md` or ADR-0008 must be manually classified: update them if they describe recent buy candidate payload or holdings candidate-selection behavior, but leave them only if they intentionally describe the ticker/name-only search-directory cache.

- [ ] **Step 8: Commit docs**

```bash
git add docs/holdings-schema.md docs/holdings-add-buy.md docs/STRATEGY.md docs/ARCHITECTURE.md docs/local-docker-scheduler-plan.md docs/holdings-ticker-lookup.md docs/adr/ADR-0008-holdings-ticker-directory.md holdings.example.yaml
git commit -m "docs: 진입 패턴 보유 계약 문서화" -m "entry_pattern을 holdings 공개 계약으로 설명한다."
```

## Task 6: Final Verification

**Files:**
- No source changes unless verification exposes a bug.

- [ ] **Step 1: Confirm migration/runtime deployment ordering**

Before merge/deploy, confirm the DB migration that adds `public.holdings.entry_pattern` was applied and the executable migration smoke from Task 2 passed before any runtime containing `entry_pattern` in a PostgREST select or mutation body can run. This includes `.github/workflows/sell.yml`, `.github/workflows/ai-brief.yml`, `sab/scheduler/holdings.py`, and web `HOLDINGS_SELECT` in `web/src/lib/supabase/holdings.ts`. Runtime select changes must stay separate until the migration is applied and verified unless reviewed deployment automation guarantees migration-first ordering.

Expected: the release notes or PR checklist explicitly records the migration apply command, SQL smoke result, service-role PostgREST select/write smoke result, the historical Add Buy idempotency replay decision, and that `supabase/migrations/20260609000000_add_holdings_entry_pattern.sql` is applied before scheduled workflow, AI brief workflow, Python helper, or web/admin runtime rollout.

- [ ] **Step 2: Run Python quality gate**

Run:

```bash
just quality
```

Expected: PASS. If `just` cannot find pinned tools, rerun:

```bash
mise exec -- just quality
```

- [ ] **Step 3: Run web CI gate**

Run:

```bash
just ci-web
```

Expected: PASS. If `pnpm` is not on `PATH`, rerun:

```bash
mise exec -- just ci-web
```

- [ ] **Step 4: Run workflow audit**

Run:

```bash
just workflow-audit
```

Expected: PASS. This gate is required because Task 2 edits inline shell/Python in `.github/workflows/sell.yml` and `.github/workflows/ai-brief.yml`; `just quality` and `just ci-web` are not sufficient to catch workflow YAML, heredoc, or shell-lint regressions.

- [ ] **Step 5: Run holdings page visual smoke**

If the `sab-web` container is running, open:

```bash
http://127.0.0.1:${WEB_HOST_PORT:-55300}/holdings
```

Otherwise start the repo's web app with:

```bash
docker compose up -d --build web
```

Then open the same route. Check desktop and mobile widths. Expected: the form Entry Pattern select, recent candidate selection, and holdings table Entry Pattern display are visible; no table text overlaps Tags, Updated, or Action controls.

- [ ] **Step 6: Review focused diff**

Run:

```bash
BASE_REF="${BASE_REF:-origin/main}"
MERGE_BASE="$(git merge-base HEAD "${BASE_REF}")"
git diff --stat "${MERGE_BASE}"..HEAD
git diff --name-only "${MERGE_BASE}"..HEAD
```

Expected: diff is limited to the `entry_pattern` contract and its tests/docs, including all planned Python tests, Supabase migration/tests, scheduled export tests, `sell.yml`, `ai-brief.yml`, web schemas/helpers/routes/components/tests, docs, example YAML, and `TODOS.md` only after quality gates pass. If `origin/main` is unavailable, use the actual PR base branch and record it.

## Task 7: TODO Closure

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1: Move active TODO to completed**

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

- [ ] **Step 2: Run TODO closure check**

Run:

```bash
rg -n "Preserved buy|Preserve buy|entry_pattern" TODOS.md
```

Expected: completed entry is present, old active bullet is absent, and no unrelated TODO text changed.

- [ ] **Step 3: Commit TODO closure**

```bash
git add TODOS.md
git commit -m "docs: 진입 패턴 TODO 완료 처리" -m "품질 게이트 통과 후 entry_pattern 보존 작업을 완료 항목으로 이동한다."
```

- [ ] **Step 4: Confirm no uncommitted changes**

Run:

```bash
git status --short
```

Expected: no output.

## Self-Review

**Spec coverage:** The plan covers the active TODO: buy `pattern` is preserved into holdings via `entry_pattern`; entry reports already preserve `pattern`; hybrid sell reads structured pattern fields with exact failed-breakout semantics; scheduled sell receives the field through both the Python export helper and the active `.github/workflows/sell.yml` inline export, then through the Python loader and `_evaluate_holdings` metadata bridge. Scheduled AI Brief preserves the field through the Python scheduler export helper, the manual `.github/workflows/ai-brief.yml` inline bridge is tested separately, and `docs/local-docker-scheduler-plan.md` is updated to match. It also covers web recent-candidate selection, web/admin `HOLDINGS_SELECT`, YAML import/export/diff behavior including omitted-vs-null replace-all semantics and explicit export-null ownership, and deployment ordering so the operator does not need manual `strategy`/`tags`. Add Buy is explicitly scoped to preserve existing `entry_pattern` only, reject marker inputs, and not infer a new one.

**Completeness scan:** Instructions are concrete, with no filler placeholders, conditional mock instructions, or unspecified edge handling. `TODOS.md` references are repository file names, not placeholders.

**Type consistency:** The field name is consistently `entry_pattern` in SQL, Python dataclass/YAML, TypeScript record/snapshot/mutation types, form state, and docs. TypeScript uses required nullable `entry_pattern` for DB/current holdings and an optional key only for replace/import snapshots that must preserve YAML key presence. Buy/entry report source field remains `pattern`, and allowed values are the exact current buy pattern IDs: `trend_pullback_bounce`, `swing_high_breakout`, and `rsi_oversold_reversal`.

**Review hardening:** The plan now explicitly guards migration-before-any-runtime deployment ordering, active `sell.yml` scheduled export coverage, manual `ai-brief.yml` inline export coverage, local Docker scheduler docs, fail-closed Python/web/RPC `entry_pattern` parsing with allowed-value checks, exact hybrid sell semantics for structured pattern fields, shared PostgREST holdings select coverage, YAML omitted-vs-null and blank-clear diff/apply behavior, explicit `entry_pattern: null` YAML exports, Add Buy preservation and marker-input rejection without request-surface expansion, server-action and client form save pass-through, fixture commit completeness, stale recent-candidate marker clearing, import confirmation copy, architecture docs, and table metadata wrapping.
