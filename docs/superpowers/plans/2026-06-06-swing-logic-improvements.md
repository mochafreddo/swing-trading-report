# Swing Logic Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `sma_ema_hybrid` swing-trading reports with entry price diagnostics, volatility/stop alignment, hybrid-only quality ordering, and explicit market-regime unavailable policy.

**Architecture:** Keep existing scan -> buy report -> entry report flow. Add deterministic annotations at the existing boundaries: config parsing owns the new policy, `sab.entry` owns row-level entry price diagnostics, `sab.signals.hybrid_buy` owns hybrid risk/quality fields, and `sab.scan_evaluation` owns market-regime policy and report ordering.

**Tech Stack:** Python dataclasses, pytest, existing `sab` config loader, existing scan/entry report JSON writers, repository `uv` and `just` task runners.

---

## File Structure

- Modify `sab/config.py`: add `strategy.market_regime_unavailable_policy`, env/YAML binding, validation, composed `Config`, and scan config snapshot.
- Modify `sab/scan_types.py`: add market-regime unavailable/block counters to `_ScanRuntime`.
- Modify `sab/scan_evaluation.py`: return structured market-regime resolution, apply `block_market`, add summary fields, pass hybrid sell stop max to hybrid buy settings, and keep `ema_cross` sort unchanged.
- Modify `sab/signals/hybrid_buy.py`: add risk alignment and quality state fields to hybrid candidates.
- Modify `sab/entry.py`: change entry price lookup from `float | None` to a structured lookup result and aggregate missing-price diagnostics.
- Modify `sab/report/entry_report.py`: add entry price diagnostic fields to `EntryReportRow`.
- Modify `config.yaml`: add the default market-regime unavailable policy.
- Modify `.env.example`: document the new env override with a non-secret example value.
- Modify `docs/STRATEGY.md`, `docs/configuration.md`, `docs/config-reference.md`: document the new contracts.
- Test `tests/test_config_validation_layers.py`: config default, YAML/env parsing, invalid value, env/YAML conflict.
- Test `tests/test_runtime_config_contract.py`: default runtime contract includes the policy.
- Test `tests/test_market_regime_filter.py`: structured resolver and `block_market`.
- Test `tests/test_scan_evaluation_issue_split.py`: hybrid-only sort and scan summary fields.
- Test `tests/test_hybrid_buy_state.py`: risk alignment and quality state.
- Test `tests/test_entry_refactor_helpers.py`, `tests/test_entry_command.py`, `tests/test_entry_report.py`: lookup result contract and report fields.

## Task 1: Config Policy Contract

**Files:**
- Modify: `sab/config.py`
- Modify: `config.yaml`
- Test: `tests/test_config_validation_layers.py`
- Test: `tests/test_runtime_config_contract.py`
- Test: `tests/test_config_conflict_binding_sync.py`

- [ ] **Step 1: Write failing config tests**

Append these tests to `tests/test_config_validation_layers.py`:

```python
def test_load_config_defaults_market_regime_unavailable_policy(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("strategy:\n  mode: sma_ema_hybrid\n", encoding="utf-8")
    monkeypatch.setenv("SAB_CONFIG", str(cfg_path))

    cfg = load_config()

    assert cfg.market_regime_unavailable_policy == "warn_continue"


def test_load_config_parses_market_regime_unavailable_policy_from_yaml(
    tmp_path, monkeypatch
):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "strategy:\n"
        "  mode: sma_ema_hybrid\n"
        "  market_regime_unavailable_policy: block_market\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SAB_CONFIG", str(cfg_path))

    cfg = load_config()

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_load_config_parses_market_regime_unavailable_policy_from_env(
    tmp_path, monkeypatch
):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("strategy:\n  mode: sma_ema_hybrid\n", encoding="utf-8")
    monkeypatch.setenv("SAB_CONFIG", str(cfg_path))
    monkeypatch.setenv("MARKET_REGIME_UNAVAILABLE_POLICY", "block_market")

    cfg = load_config()

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_load_config_rejects_invalid_market_regime_unavailable_policy(
    tmp_path, monkeypatch
):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "strategy:\n  market_regime_unavailable_policy: maybe\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SAB_CONFIG", str(cfg_path))
    monkeypatch.setenv("SAB_CONFIG_STRICT", "1")

    with pytest.raises(ConfigLoadError, match="MARKET_REGIME_UNAVAILABLE_POLICY"):
        load_config()


def test_load_config_rejects_market_regime_policy_env_yaml_conflict(
    tmp_path, monkeypatch
):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "strategy:\n  market_regime_unavailable_policy: warn_continue\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SAB_CONFIG", str(cfg_path))
    monkeypatch.setenv("MARKET_REGIME_UNAVAILABLE_POLICY", "block_market")

    with pytest.raises(ConfigLoadError, match="MARKET_REGIME_UNAVAILABLE_POLICY"):
        load_config()
```

In `tests/test_runtime_config_contract.py`, extend the default assertion:

```python
assert cfg.market_regime_unavailable_policy == "warn_continue"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_config_validation_layers.py tests/test_runtime_config_contract.py tests/test_config_conflict_binding_sync.py -q
```

Expected: FAIL because `Config` has no `market_regime_unavailable_policy` attribute and `MARKET_REGIME_UNAVAILABLE_POLICY` is not in `_ENV_YAML_CONFLICT_BINDINGS`.

- [ ] **Step 3: Implement the config contract**

In `sab/config.py`, add the env/YAML binding near `USE_MARKET_REGIME_FILTER`:

```python
("MARKET_REGIME_UNAVAILABLE_POLICY", "strategy.market_regime_unavailable_policy"),
```

Add the field to `Config`:

```python
market_regime_unavailable_policy: str = "warn_continue"
```

Add the field to `_StrategySection`:

```python
market_regime_unavailable_policy: str
```

In `_parse_strategy_section`, read the value:

```python
market_regime_unavailable_policy=parser.env_str(
    "MARKET_REGIME_UNAVAILABLE_POLICY",
    "strategy.market_regime_unavailable_policy",
    "warn_continue",
) or "warn_continue",
```

In `_validate_sections`, normalize it with strict validation:

```python
validated_strategy = replace(
    strategy,
    strategy_mode=_normalize_choice(
        strategy.strategy_mode,
        allowed={"ema_cross", "sma_ema_hybrid"},
        default="ema_cross",
        strict=strict,
        source_name="STRATEGY_MODE/strategy.mode",
    ),
    market_regime_unavailable_policy=_normalize_choice(
        strategy.market_regime_unavailable_policy,
        allowed={"warn_continue", "block_market"},
        default="warn_continue",
        strict=strict,
        source_name=(
            "MARKET_REGIME_UNAVAILABLE_POLICY/"
            "strategy.market_regime_unavailable_policy"
        ),
    ),
)
```

In `_compose_config`, pass it through:

```python
market_regime_unavailable_policy=strategy.market_regime_unavailable_policy,
```

In `config.yaml`, add under `strategy:`:

```yaml
  market_regime_unavailable_policy: warn_continue
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_config_validation_layers.py tests/test_runtime_config_contract.py tests/test_config_conflict_binding_sync.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/config.py config.yaml tests/test_config_validation_layers.py tests/test_runtime_config_contract.py
git commit -m "feat(strategy): 시장 레짐 unavailable 정책 설정을 추가한다"
```

## Task 2: Entry Price Lookup Diagnostics

**Files:**
- Modify: `sab/entry.py`
- Modify: `sab/report/entry_report.py`
- Test: `tests/test_entry_refactor_helpers.py`
- Test: `tests/test_entry_command.py`
- Test: `tests/test_entry_report.py`

- [ ] **Step 1: Write failing entry helper and report tests**

Update `tests/test_entry_refactor_helpers.py` so the existing `price_lookup_fn` returns a structured result:

```python
lookup_result = entry.EntryPriceLookupResult.missing(
    "kis_live_snapshot_missing",
    source="kis_live_snapshot",
)

row, issues = helper(
    candidate={
        "ticker": "AAPL.NASD",
        "signal_price_basis": "adjusted",
        "signal_close_adjusted_value": 100.0,
        "entry_reference_close_raw_value": 100.0,
        "entry_reference_eval_date": "20260225",
        "eval_date": "20260225",
        "strategy_mode": "sma_ema_hybrid",
        "entry_state": "READY",
        "entry_trigger_price_value": "not-a-price",
        "entry_trigger_operator": "gte",
        "entry_trigger_label": "swing high",
    },
    price_lookup_fn=lambda _ticker: lookup_result,
    gap_breach_action="SKIP",
    default_strategy_mode=None,
    allow_missing_gap_guard=False,
)

assert row.entry_price is None
assert row.entry_price_status == "missing"
assert row.entry_price_source == "kis_live_snapshot"
assert row.entry_price_issue_code == "kis_live_snapshot_missing"
assert row.entry_price_issues == ["kis_live_snapshot_missing"]
```

Add summary assertions to
`test_run_entry_e2e_kr_pre_open_requires_snapshot_marker_even_with_live_price`
in `tests/test_entry_command.py`. This is the KIS live snapshot missing case;
do not add these `kis_live_snapshot_missing` assertions to the provider
credentials test.

```python
assert payload["summary"]["missing_entry_price_by_reason"] == {
    "kis_live_snapshot_missing": 1
}
assert payload["summary"]["entry_price_sources"] == {}
assert payload["entries"][0]["entry_price_status"] == "missing"
assert payload["entries"][0]["entry_price_issue_code"] == "kis_live_snapshot_missing"
```

In `test_run_entry_e2e_returns_exit_1_when_all_prices_are_missing`, assert the
credentials-specific diagnostic instead:

```python
assert payload["summary"]["missing_entry_price_by_reason"] == {
    "kis_credentials_missing": 1
}
assert payload["entries"][0]["entry_price_status"] == "missing"
assert payload["entries"][0]["entry_price_issue_code"] == "kis_credentials_missing"
```

Update every direct `evaluate_entry_candidates` test helper in
`tests/test_entry_command.py` that still returns `float | None`. Add a small
helper near `_entry_candidate`:

```python
def _entry_price_result(
    price: float | None,
    *,
    source: str = "test",
    issue_code: str = "kis_live_snapshot_missing",
) -> entry.EntryPriceLookupResult:
    if price is None:
        return entry.EntryPriceLookupResult.missing(issue_code, source=source)
    return entry.EntryPriceLookupResult.available(price, source=source)
```

Then replace direct lookup lambdas such as:

```python
price_lookup_fn=lambda _ticker: 101.0
price_lookup_fn=lambda _ticker: None
price_lookup_fn=lambda ticker: prices.get(ticker)
```

with:

```python
price_lookup_fn=lambda _ticker: _entry_price_result(101.0)
price_lookup_fn=lambda _ticker: _entry_price_result(None)
price_lookup_fn=lambda ticker: _entry_price_result(prices.get(ticker))
```

Also update fake `_make_price_lookup` providers in the same file from
`Callable[[str], float | None]` to
`Callable[[str], entry.EntryPriceLookupResult]`, returning
`_entry_price_result(market_prices.get(ticker))`.

Update the existing `_make_price_lookup` tests in `tests/test_entry_command.py`
that currently assert `price_lookup("AAPL.NASD") is None`.

In `test_make_price_lookup_logs_kis_detail_failure`, replace that assertion with:

```python
lookup_result = price_lookup("AAPL.NASD")
assert lookup_result.price is None
assert lookup_result.status == "missing"
assert lookup_result.source == "kis_live_snapshot"
assert lookup_result.issue_codes == ("provider_error",)
```

In `test_make_price_lookup_logs_kis_us_snapshot_rejection_reason`, extend the
parametrize tuple with `expected_issue_code`:

```python
@pytest.mark.parametrize(
    ("detail", "expected_reason", "expected_issue_code", "expected_currency", "expected_fields"),
    [
        (
            {"last": "101.0", "curr": "EUR"},
            "currency_mismatch",
            "kis_live_snapshot_currency_mismatch",
            "EUR",
            ["last"],
        ),
        (
            {"open": "101.0", "curr": "USD"},
            "no_supported_price_field",
            "kis_live_snapshot_no_supported_price_field",
            "USD",
            [],
        ),
        (
            {"last": "0", "curr": "USD"},
            "invalid_price_value",
            "kis_live_snapshot_invalid_price_value",
            "USD",
            ["last"],
        ),
    ],
)
```

Then replace the `price_lookup("AAPL.NASD") is None` assertion with:

```python
lookup_result = price_lookup("AAPL.NASD")
assert lookup_result.price is None
assert lookup_result.status == "rejected"
assert lookup_result.source == "kis_live_snapshot"
assert lookup_result.issue_codes == (expected_issue_code,)
```

Add to `tests/test_entry_report.py`:

```python
def test_write_entry_report_includes_entry_price_diagnostics(tmp_path):
    out = write_entry_report(
        report_dir=tmp_path.as_posix(),
        artifact={"market": "US", "mode": "PRE_OPEN", "summary": {}},
        entries=[
            EntryReportRow(
                ticker="AAPL.NASD",
                action="REVIEW",
                reasons=["price snapshot unavailable"],
                signal_close=100.0,
                entry_price=None,
                gap_pct=None,
                entry_price_status="missing",
                entry_price_source="kis_live_snapshot",
                entry_price_issue_code="kis_live_snapshot_missing",
                entry_price_issues=["kis_live_snapshot_missing"],
            )
        ],
        artifact_date="2026-06-06",
    )

    payload = json.loads(Path(out).read_text(encoding="utf-8"))
    row = payload["entries"][0]
    assert row["entry_price_status"] == "missing"
    assert row["entry_price_source"] == "kis_live_snapshot"
    assert row["entry_price_issue_code"] == "kis_live_snapshot_missing"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entry_refactor_helpers.py tests/test_entry_report.py tests/test_entry_command.py -q
```

Expected: FAIL because `EntryPriceLookupResult` and `EntryReportRow` diagnostic fields do not exist.

- [ ] **Step 3: Implement lookup result and row fields**

In `sab/report/entry_report.py`, extend `EntryReportRow`:

```python
entry_price_status: str | None = None
entry_price_source: str | None = None
entry_price_issue_code: str | None = None
entry_price_issues: list[str] | None = None
```

In `sab/entry.py`, add near constants:

```python
@dataclass(frozen=True)
class EntryPriceLookupResult:
    price: float | None
    status: str
    source: str | None = None
    issue_codes: tuple[str, ...] = ()

    @classmethod
    def available(cls, price: float, *, source: str) -> "EntryPriceLookupResult":
        return cls(price=price, status="available", source=source)

    @classmethod
    def missing(
        cls, issue_code: str, *, source: str | None = None
    ) -> "EntryPriceLookupResult":
        return cls(price=None, status="missing", source=source, issue_codes=(issue_code,))

    @classmethod
    def rejected(
        cls, issue_code: str, *, source: str | None = None
    ) -> "EntryPriceLookupResult":
        return cls(price=None, status="rejected", source=source, issue_codes=(issue_code,))
```

Change `_make_price_lookup` to return
`Callable[[str], EntryPriceLookupResult]`. Also update the `price_lookup_fn`
type hints in `_evaluate_entry_candidate` and `evaluate_entry_candidates` from
`Callable[[str], float | None]` to `Callable[[str], EntryPriceLookupResult]`.
Use these source codes:

```python
"kis_after_close_daily"
"kis_live_snapshot"
"pykrx_after_close_daily"
```

Use these issue codes in the current failure branches:

```python
"kis_credentials_missing"
"provider_error"
"daily_close_unavailable"
"entry_price_invalid"
"kis_live_snapshot_missing"
"kis_live_snapshot_no_supported_price_field"
"kis_live_snapshot_currency_mismatch"
"kis_live_snapshot_invalid_price_value"
```

In `_evaluate_entry_candidate`, replace the current `entry_price = price_lookup_fn(ticker)` block with:

```python
lookup_result = price_lookup_fn(ticker)
entry_price = lookup_result.price
if entry_price is not None and entry_price <= 0:
    lookup_result = EntryPriceLookupResult.rejected(
        "entry_price_invalid",
        source=lookup_result.source,
    )
    entry_price = None
if entry_price is None:
    reasons.append("price snapshot unavailable")
    candidate_issues.append(f"{ticker}: price snapshot unavailable")
```

When building `EntryReportRow`, pass:

```python
entry_price_status=lookup_result.status,
entry_price_source=lookup_result.source,
entry_price_issue_code=lookup_result.issue_codes[0]
if lookup_result.issue_codes
else None,
entry_price_issues=list(lookup_result.issue_codes),
```

In `_build_entry_summary`, add:

```python
missing_by_reason = Counter(
    issue
    for row in rows
    if row.entry_price is None
    for issue in (row.entry_price_issues or [])
)
source_counts = Counter(
    row.entry_price_source
    for row in rows
    if row.entry_price_source and row.entry_price is not None
)
```

Return:

```python
"missing_entry_price_by_reason": dict(sorted(missing_by_reason.items())),
"entry_price_sources": dict(sorted(source_counts.items())),
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entry_refactor_helpers.py tests/test_entry_report.py tests/test_entry_command.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/entry.py sab/report/entry_report.py tests/test_entry_refactor_helpers.py tests/test_entry_report.py tests/test_entry_command.py
git commit -m "feat(entry): 진입 가격 진단 필드를 추가한다"
```

## Task 3: Hybrid Risk Alignment

**Files:**
- Modify: `sab/signals/hybrid_buy.py`
- Modify: `sab/scan_evaluation.py`
- Test: `tests/test_hybrid_buy_state.py`

- [ ] **Step 1: Write failing risk alignment tests**

Append to `tests/test_hybrid_buy_state.py`:

```python
def test_hybrid_candidate_flags_tight_stop_vs_gap_guard(monkeypatch):
    candles = _simple_candles(6, base=100.0)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [10.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Close reclaimed EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {"trigger_rsi50": True, "rsi_val": 55.0, "close_above_ema_short": True},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    settings = _settings(min_history=2)
    settings.sell_stop_loss_pct_max = 0.05

    result = evaluate_ticker_hybrid("FAKE.US", candles, settings, {"currency": "USD"})

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["risk_alignment"] == "tight_stop_vs_volatility"
    assert candidate["volatility_reference_pct"] == pytest.approx(
        candidate["gap_guard_pct_value"]
    )
    assert candidate["risk_alignment_reasons"] == ["gap_guard_exceeds_stop_max"]
    assert any(
        reason["id"] == "risk_alignment_tight_stop"
        for reason in candidate["reasons"]
    )


def test_hybrid_candidate_marks_unknown_risk_without_volatility_reference(monkeypatch):
    candles = _simple_candles(6, base=100.0)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [math.nan] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Close reclaimed EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {"trigger_rsi50": True, "rsi_val": 55.0, "close_above_ema_short": True},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid("FAKE.US", candles, _settings(min_history=2), {"currency": "USD"})

    assert result.candidate is not None
    assert result.candidate["risk_alignment"] == "unknown"
    assert result.candidate["risk_alignment_reasons"] == [
        "volatility_reference_unavailable"
    ]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_hybrid_buy_state.py::test_hybrid_candidate_flags_tight_stop_vs_gap_guard tests/test_hybrid_buy_state.py::test_hybrid_candidate_marks_unknown_risk_without_volatility_reference -q
```

Expected: FAIL because risk alignment fields do not exist.

- [ ] **Step 3: Implement risk alignment**

In `sab/signals/hybrid_buy.py`, add a setting at the end of `HybridEvaluationSettings`:

```python
sell_stop_loss_pct_max: float = 0.05
```

Add:

```python
@dataclass(frozen=True)
class _RiskAlignment:
    state: str
    reasons: list[str]
    volatility_reference_pct: float | None
```

Add helper:

```python
def _build_risk_alignment(
    *,
    gap_guard: _GapGuard,
    atr_value: float,
    last_close: float,
    settings: HybridEvaluationSettings,
) -> _RiskAlignment:
    volatility_reference_pct = gap_guard.pct
    reason_prefix = "gap_guard"
    if volatility_reference_pct is None and not math.isnan(atr_value) and last_close > 0:
        volatility_reference_pct = atr_value / last_close
        reason_prefix = "atr"
    if volatility_reference_pct is None:
        return _RiskAlignment(
            state="unknown",
            reasons=["volatility_reference_unavailable"],
            volatility_reference_pct=None,
        )
    if volatility_reference_pct > settings.sell_stop_loss_pct_max:
        return _RiskAlignment(
            state="tight_stop_vs_volatility",
            reasons=[f"{reason_prefix}_exceeds_stop_max"],
            volatility_reference_pct=volatility_reference_pct,
        )
    return _RiskAlignment(
        state="aligned",
        reasons=[],
        volatility_reference_pct=volatility_reference_pct,
    )
```

Call it after `gap_guard` is built:

```python
risk_alignment = _build_risk_alignment(
    gap_guard=gap_guard,
    atr_value=indicators.atr_value,
    last_close=last_close,
    settings=settings,
)
```

Extend `_build_hybrid_reasons` to accept `risk_alignment: _RiskAlignment`. Add:

```python
if risk_alignment.state == "tight_stop_vs_volatility":
    _add_hybrid_reason(
        reasons,
        reason_id="risk_alignment_tight_stop",
        label="손절폭 대비 변동성 큼",
        kind="risk",
        status="warn",
        points=0.0,
        value=risk_alignment.volatility_reference_pct,
        threshold=0.0,
    )
```

Add fields to `candidate`:

```python
"risk_alignment": risk_alignment.state,
"risk_alignment_reasons": risk_alignment.reasons,
"volatility_reference_pct": risk_alignment.volatility_reference_pct,
```

In `sab/scan_evaluation.py`, pass configured sell stop max to hybrid settings:

```python
sell_stop_loss_pct_max=cfg.hybrid_sell.stop_loss_pct_max,
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_hybrid_buy_state.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/signals/hybrid_buy.py sab/scan_evaluation.py tests/test_hybrid_buy_state.py
git commit -m "feat(strategy): 하이브리드 후보의 리스크 정합성을 표시한다"
```

## Task 4: Hybrid Quality State and Hybrid-Only Sorting

**Files:**
- Modify: `sab/signals/hybrid_buy.py`
- Modify: `sab/scan_evaluation.py`
- Test: `tests/test_hybrid_buy_state.py`
- Test: `tests/test_scan_evaluation_issue_split.py`

- [ ] **Step 1: Write failing quality and sort tests**

Add to `tests/test_hybrid_buy_state.py`:

```python
def test_hybrid_candidate_quality_state_demotes_negative_rs(monkeypatch):
    candles = _simple_candles(6, base=100.0)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [1.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Close reclaimed EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {"trigger_rsi50": True, "rsi_val": 55.0, "close_above_ema_short": True},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    settings = _settings(min_history=2)
    settings.rs_lookback_days = 2

    result = evaluate_ticker_hybrid(
        "FAKE.US",
        candles,
        settings,
        {"currency": "USD", "rs_benchmark_return": 0.50, "rs_benchmark_ticker": "SPY.AMS"},
    )

    assert result.candidate is not None
    assert result.candidate["quality_state"] == "B"
    assert "relative_strength_negative" in result.candidate["quality_reasons"]


def test_hybrid_candidate_quality_state_marks_watch_as_c(monkeypatch):
    candles = _simple_candles(6, base=100.0)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Reversal candle near EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {"trigger_rsi50": False, "rsi_val": 45.0, "close_above_ema_short": False},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid("FAKE.US", candles, _settings(min_history=2), {"currency": "USD"})

    assert result.candidate is not None
    assert result.candidate["entry_state"] == "WATCH"
    assert result.candidate["quality_state"] == "C"
    assert "entry_state_watch" in result.candidate["quality_reasons"]
```

Add to `tests/test_scan_evaluation_issue_split.py`:

```python
def test_decorate_candidates_uses_quality_first_only_for_hybrid() -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(runtime.cfg, strategy_mode="sma_ema_hybrid")
    runtime.candidates = [
        {
            "ticker": "HIGH_SCORE_B.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 10.0,
            "quality_state": "B",
            "rs_diff_value": -0.1,
            "avg_dollar_volume_value": 300_000.0,
            "pct_change_value": 0.03,
        },
        {
            "ticker": "LOW_SCORE_A.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 1.0,
            "quality_state": "A",
            "rs_diff_value": 0.1,
            "avg_dollar_volume_value": 100_000.0,
            "pct_change_value": 0.01,
        },
    ]

    _decorate_candidates(
        runtime,
        apply_currency_display_fn=lambda *_args, **_kwargs: None,
        lookup_holiday_fn=lambda *_args, **_kwargs: None,
        us_market_status_fn=lambda **_kwargs: "closed",
    )

    assert [candidate["ticker"] for candidate in runtime.candidates] == [
        "LOW_SCORE_A.KR",
        "HIGH_SCORE_B.KR",
    ]


def test_decorate_candidates_keeps_score_first_for_ema_cross() -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(runtime.cfg, strategy_mode="ema_cross")
    runtime.candidates = [
        {
            "ticker": "HIGH_SCORE_B.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 10.0,
            "quality_state": "B",
            "rs_diff_value": -0.1,
            "avg_dollar_volume_value": 300_000.0,
            "pct_change_value": 0.03,
        },
        {
            "ticker": "LOW_SCORE_A.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 1.0,
            "quality_state": "A",
            "rs_diff_value": 0.1,
            "avg_dollar_volume_value": 100_000.0,
            "pct_change_value": 0.01,
        },
    ]

    _decorate_candidates(
        runtime,
        apply_currency_display_fn=lambda *_args, **_kwargs: None,
        lookup_holiday_fn=lambda *_args, **_kwargs: None,
        us_market_status_fn=lambda **_kwargs: "closed",
    )

    assert [candidate["ticker"] for candidate in runtime.candidates] == [
        "HIGH_SCORE_B.KR",
        "LOW_SCORE_A.KR",
    ]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_hybrid_buy_state.py::test_hybrid_candidate_quality_state_demotes_negative_rs tests/test_hybrid_buy_state.py::test_hybrid_candidate_quality_state_marks_watch_as_c tests/test_scan_evaluation_issue_split.py::test_decorate_candidates_uses_quality_first_only_for_hybrid tests/test_scan_evaluation_issue_split.py::test_decorate_candidates_keeps_score_first_for_ema_cross -q
```

Expected: FAIL because `quality_state` fields and hybrid-only sort are not implemented.

- [ ] **Step 3: Implement quality state and sort key**

In `sab/signals/hybrid_buy.py`, add:

```python
@dataclass(frozen=True)
class _QualityState:
    state: str
    reasons: list[str]
```

Do not add a candidate-level `data_warning` reason in the first pass. Current
hybrid system/data failures return `HybridEvaluationResult(candidate=None, ...)`
and are recorded outside the candidate list, so `_build_quality_state` should
only classify emitted-candidate inputs: `entry_state`, `rs_diff`, and
`risk_alignment`.

Add:

```python
def _build_quality_state(
    *,
    entry_state: _EntryStateResult,
    rs_diff: float | None,
    risk_alignment: _RiskAlignment,
) -> _QualityState:
    reasons: list[str] = []
    if entry_state.state == "WATCH":
        reasons.append("entry_state_watch")
        return _QualityState("C", reasons)
    reasons.append("entry_state_ready")
    if rs_diff is None:
        reasons.append("relative_strength_unavailable")
        return _QualityState("C", reasons)
    if rs_diff < 0:
        reasons.append("relative_strength_negative")
    else:
        reasons.append("relative_strength_positive")
    if risk_alignment.state == "unknown":
        reasons.extend(risk_alignment.reasons)
        return _QualityState("C", reasons)
    if risk_alignment.state == "tight_stop_vs_volatility":
        reasons.append("risk_alignment_tight_stop")
    if "relative_strength_negative" in reasons or "risk_alignment_tight_stop" in reasons:
        return _QualityState("B", reasons)
    return _QualityState("A", reasons)
```

Call it after `risk_alignment`:

```python
quality_state = _build_quality_state(
    entry_state=entry_state,
    rs_diff=rs_diff,
    risk_alignment=risk_alignment,
)
```

Add fields to `candidate`:

```python
"quality_state": quality_state.state,
"quality_reasons": quality_state.reasons,
```

In `sab/scan_evaluation.py`, update `_decorate_candidates`:

```python
def _quality_rank(candidate: dict[str, Any]) -> int:
    return {"A": 0, "B": 1, "C": 2}.get(str(candidate.get("quality_state") or "C"), 2)


def _base_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float, float, str]:
    return (
        -_metric(candidate, "score_value", fallback_key="score", default=0.0),
        -_metric(candidate, "rs_diff_value", default=float("-inf")),
        -_liquidity_metric(candidate),
        -_metric(candidate, "pct_change_value"),
        str(candidate.get("ticker", "")),
    )


if runtime.cfg.strategy_mode == "sma_ema_hybrid":
    runtime.candidates.sort(
        key=lambda candidate: (_quality_rank(candidate), *_base_sort_key(candidate))
    )
else:
    runtime.candidates.sort(key=_base_sort_key)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_hybrid_buy_state.py tests/test_scan_evaluation_issue_split.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/signals/hybrid_buy.py sab/scan_evaluation.py tests/test_hybrid_buy_state.py tests/test_scan_evaluation_issue_split.py
git commit -m "feat(strategy): 하이브리드 후보 품질 정렬을 추가한다"
```

## Task 5: Structured Market-Regime Unavailable Policy

**Files:**
- Modify: `sab/scan_types.py`
- Modify: `sab/scan_evaluation.py`
- Test: `tests/test_market_regime_filter.py`
- Test: `tests/test_scan_metrics_summary.py`

- [ ] **Step 1: Write failing market-regime tests**

Append to `tests/test_market_regime_filter.py`:

```python
def test_resolve_market_regime_context_returns_unavailable_markets() -> None:
    runtime = _build_runtime(tickers=["AAPL.NAS"])
    runtime.kis_client = None

    resolution = _resolve_market_regime_context(runtime)

    assert resolution.regime_by_market == {}
    unavailable = resolution.unavailable_markets["US"]
    assert unavailable.issue_code == "market_regime_benchmark_unavailable"
    assert unavailable.message.startswith("SPY.AMS: Market regime unavailable")
    assert resolution.issues == [unavailable.message]


def test_evaluate_candidates_blocks_market_when_regime_unavailable_policy_blocks(
    monkeypatch,
) -> None:
    runtime = _build_runtime(tickers=["AAPL.NAS"])
    runtime.cfg = replace(
        runtime.cfg,
        use_market_regime_filter=True,
        market_regime_unavailable_policy="block_market",
    )
    evaluated: list[str] = []

    monkeypatch.setattr(
        "sab.scan_evaluation._compute_market_regime_context",
        lambda *_args, **_kwargs: (
            None,
            "SPY.AMS: Market regime unavailable (insufficient completed history for SMA200)",
        ),
    )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda ticker, *_args, **_kwargs: evaluated.append(ticker),
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
        enrich_entry_reference_prices=False,
    )

    assert evaluated == []
    assert runtime.market_regime_blocked_by_market == {"US": 1}
    assert runtime.screen_outs == [
        "AAPL.NAS: Market regime unavailable policy blocked US "
        "(SPY.AMS: Market regime unavailable (insufficient completed history for SMA200))"
    ]
```

Add to `tests/test_scan_metrics_summary.py`:

```python
def test_write_scan_report_includes_market_regime_policy_summary() -> None:
    runtime = _build_runtime(tickers=["AAPL.NAS"])
    runtime.market_regime_unavailable_count = 2
    runtime.market_regime_blocked_by_market = {"US": 2}
    captured: dict[str, Any] = {}

    _write_scan_report(runtime, write_report_fn=lambda **kwargs: captured.update(kwargs) or "x.json")

    summary = captured["summary_fields"]
    assert summary["market_regime_unavailable_count"] == 2
    assert summary["market_regime_blocked_count"] == 2
    assert summary["market_regime_blocked_by_market"] == {"US": 2}
```

Update the existing tests in `tests/test_market_regime_filter.py` that still
expect `_resolve_market_regime_context` to return a plain dict.

Add `MarketRegimeResolution` to the import from `sab.scan_evaluation`.

In `test_resolve_market_regime_context_marks_bullish_market`, change:

```python
contexts = _resolve_market_regime_context(runtime)

assert contexts["US"].benchmark_ticker == "SPY.AMS"
assert contexts["US"].is_bullish is True
assert contexts["US"].benchmark_close > contexts["US"].benchmark_sma200
```

to:

```python
resolution = _resolve_market_regime_context(runtime)

contexts = resolution.regime_by_market
assert contexts["US"].benchmark_ticker == "SPY.AMS"
assert contexts["US"].is_bullish is True
assert contexts["US"].benchmark_close > contexts["US"].benchmark_sma200
assert resolution.unavailable_markets == {}
assert resolution.issues == []
```

In `test_evaluate_candidates_skips_ticker_when_market_regime_blocked` and
`test_evaluate_candidates_keeps_other_market_when_one_market_blocked`, replace
the monkeypatched plain dict return value with:

```python
MarketRegimeResolution(
    regime_by_market={...},
    unavailable_markets={},
    issues=[],
)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_market_regime_filter.py tests/test_scan_metrics_summary.py -q
```

Expected: FAIL because `_resolve_market_regime_context` returns a dict and runtime market-regime counters do not exist.

- [ ] **Step 3: Implement structured resolver and block policy**

In `sab/scan_types.py`, add fields:

```python
market_regime_unavailable_count: int = 0
market_regime_blocked_by_market: dict[str, int] = field(default_factory=dict)
```

In `sab/scan_evaluation.py`, add:

```python
@dataclass(frozen=True)
class MarketRegimeUnavailable:
    market: str
    issue_code: str
    message: str


@dataclass(frozen=True)
class MarketRegimeResolution:
    regime_by_market: dict[str, MarketRegimeContext]
    unavailable_markets: dict[str, MarketRegimeUnavailable]
    issues: list[str]
```

Change `_resolve_market_regime_context` to return `MarketRegimeResolution`. On missing benchmark ticker, set:

When the filter is disabled or there are no active markets, return an empty
resolution instead of `{}`:

```python
return MarketRegimeResolution(
    regime_by_market={},
    unavailable_markets={},
    issues=[],
)
```

```python
unavailable_markets[market] = MarketRegimeUnavailable(
    market=market,
    issue_code="market_regime_benchmark_not_configured",
    message=f"{market}: market regime benchmark ticker not configured",
)
```

On compute failure, set:

```python
unavailable_markets[market] = MarketRegimeUnavailable(
    market=market,
    issue_code="market_regime_benchmark_unavailable",
    message=issue or f"{market}: market regime unavailable",
)
```

At return:

```python
runtime.market_regime_unavailable_count = len(unavailable_markets)
return MarketRegimeResolution(
    regime_by_market=regime_by_market,
    unavailable_markets=unavailable_markets,
    issues=issues,
)
```

In `_evaluate_candidates`, change:

```python
market_regime_resolution = _resolve_market_regime_context(runtime)
market_regimes_by_market = market_regime_resolution.regime_by_market
```

Before checking `regime_context`, add:

```python
unavailable = market_regime_resolution.unavailable_markets.get(ticker_market)
if (
    unavailable is not None
    and cfg.market_regime_unavailable_policy == "block_market"
):
    detail = (
        f"{ticker}: Market regime unavailable policy blocked {ticker_market} "
        f"({unavailable.message})"
    )
    runtime.screen_outs.append(detail)
    runtime.market_regime_blocked_by_market[ticker_market] = (
        runtime.market_regime_blocked_by_market.get(ticker_market, 0) + 1
    )
    runtime.logger.info("%s", detail)
    continue
```

In `_write_scan_report`, include config and summary:

```python
config_snapshot["market_regime_unavailable_policy"] = (
    runtime.cfg.market_regime_unavailable_policy
)
```

```python
blocked_by_market = dict(sorted(runtime.market_regime_blocked_by_market.items()))
summary_fields.update(
    {
        "market_regime_unavailable_count": runtime.market_regime_unavailable_count,
        "market_regime_blocked_count": sum(blocked_by_market.values()),
        "market_regime_blocked_by_market": blocked_by_market,
    }
)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_market_regime_filter.py tests/test_scan_metrics_summary.py tests/test_scan_evaluation_issue_split.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sab/scan_types.py sab/scan_evaluation.py tests/test_market_regime_filter.py tests/test_scan_metrics_summary.py
git commit -m "feat(strategy): 시장 레짐 unavailable 차단 정책을 구현한다"
```

## Task 6: Documentation and Env Reference

**Files:**
- Modify: `.env.example`
- Modify: `docs/STRATEGY.md`
- Modify: `docs/configuration.md`
- Modify: `docs/config-reference.md`
- Modify: `docs/ARCHITECTURE.md`
- Test: `tests/test_env_example_v11.py`
- Test: `tests/test_docs_state_contract.py`

- [ ] **Step 1: Write failing docs/env reference tests**

In `tests/test_env_example_v11.py`, add the new key to the existing `required`
set in `test_env_example_contains_v11_required_keys`:

```python
"MARKET_REGIME_UNAVAILABLE_POLICY",
```

In `tests/test_docs_state_contract.py`, add this test:

```python
def test_strategy_docs_include_swing_logic_improvement_contracts() -> None:
    strategy_text = _read(Path("docs/STRATEGY.md"))
    config_reference_text = _read(Path("docs/config-reference.md"))

    assert "market_regime_unavailable_policy" in strategy_text
    assert "quality_state" in strategy_text
    assert "risk_alignment" in strategy_text
    assert "MARKET_REGIME_UNAVAILABLE_POLICY" in config_reference_text
```

- [ ] **Step 2: Run docs tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_env_example_v11.py tests/test_docs_state_contract.py -q
```

Expected: FAIL because docs and `.env.example` do not mention the new fields.

- [ ] **Step 3: Update docs and env template**

In `.env.example`, add:

```env
# Optional. warn_continue keeps current permissive behavior; block_market skips a market when regime benchmark is unavailable.
MARKET_REGIME_UNAVAILABLE_POLICY=warn_continue
```

In `docs/configuration.md`, add a row:

```markdown
| `MARKET_REGIME_UNAVAILABLE_POLICY` | no | `warn_continue` | `block_market` | `sab scan` | Market regime unavailable policy | Must be `warn_continue` or `block_market`. |
```

In `docs/config-reference.md`, add to the conflict binding table:

```markdown
| `MARKET_REGIME_UNAVAILABLE_POLICY` | `strategy.market_regime_unavailable_policy` | benchmark unavailable 시 market regime 처리 정책 |
```

In `docs/STRATEGY.md`, update the market regime section with:

```markdown
- `strategy.market_regime_unavailable_policy=warn_continue`이면 benchmark를 구하지 못할 때 현재처럼 경고를 남기고 scan을 계속합니다.
- `strategy.market_regime_unavailable_policy=block_market`이면 benchmark를 구하지 못한 시장의 후보를 제외하고 summary에 `market_regime_blocked_by_market`을 기록합니다.
```

Also add hybrid candidate field definitions:

```markdown
- `risk_alignment`: `aligned | tight_stop_vs_volatility | unknown`
- `quality_state`: `A | B | C`; 1차 구현에서는 `sma_ema_hybrid` 후보 정렬에만 사용합니다.
```

In `docs/ARCHITECTURE.md`, update the entry summary section:

```markdown
- `entry.summary`는 `missing_entry_price_by_reason`과 `entry_price_sources`로 가격 조회 실패 원인과 사용된 가격 소스를 집계합니다.
```

- [ ] **Step 4: Run docs tests to verify pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_env_example_v11.py tests/test_docs_state_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .env.example docs/STRATEGY.md docs/configuration.md docs/config-reference.md docs/ARCHITECTURE.md tests/test_env_example_v11.py tests/test_docs_state_contract.py
git commit -m "docs(strategy): 스윙 개선 설정과 리포트 계약을 문서화한다"
```

## Task 7: Final Verification

**Files:**
- No source edits in this task.

- [ ] **Step 1: Run targeted Python tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_config_validation_layers.py tests/test_runtime_config_contract.py tests/test_config_conflict_binding_sync.py tests/test_market_regime_filter.py tests/test_scan_metrics_summary.py tests/test_scan_evaluation_issue_split.py tests/test_hybrid_buy_state.py tests/test_entry_refactor_helpers.py tests/test_entry_report.py tests/test_entry_command.py tests/test_env_example_v11.py tests/test_docs_state_contract.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Python quality gate**

Run:

```bash
just quality
```

Expected: PASS. When `just` cannot find pinned tools, run this fallback command:

```bash
mise exec -- just quality
```

Expected: PASS.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git status --short
git diff --stat HEAD
```

Expected: working tree is clean after the previous task commits, or only intentional uncommitted verification notes are present. No generated reports, cache files, secrets, or local env files are staged.

## Self-Review

- Spec coverage: config policy is covered by Task 1; entry diagnostics by Task 2; risk alignment by Task 3; hybrid quality and hybrid-only sort by Task 4; structured market-regime unavailable policy by Task 5; docs/env updates by Task 6; verification by Task 7.
- Red-flag scan: no forbidden marker or open design question remains in this plan.
- Type consistency: `EntryPriceLookupResult`, `MarketRegimeResolution`, `_RiskAlignment`, and `_QualityState` are introduced before later tasks reference their fields.
