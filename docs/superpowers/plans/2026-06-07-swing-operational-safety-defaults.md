상태: Backlog

# Swing Operational Safety Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make swing operational safety defaults explicit in YAML, fail closed for active market-regime and entry price-missing checks, and keep fatal entry diagnostics visible in automation.

**Architecture:** Keep the current scan and entry orchestration shape. `sab/config.py` owns non-secret safety policy parsing and env/YAML conflict detection, `sab.entry` consumes the parsed threshold and writes it to the entry report snapshot, and workflow/scheduler code preserves report diagnostics when entry exits non-zero. Documentation and examples are updated in the same change so operators see one active default set.

**Tech Stack:** Python dataclasses, pytest, existing `sab` config loader, existing entry report writer, GitHub Actions YAML, repository `uv` and `just` task runners.

---

## Scope Check

This plan intentionally keeps one implementation track. The code changes touch config, entry reporting, automation diagnostics, and docs, but they are one operational-safety contract and must ship together so active defaults cannot change without observable diagnostics.

## File Structure

- Modify `sab/config.py`: add `entry_fatal_missing_price_ratio`, env/YAML conflict binding, parsing, validation, and composition.
- Modify `sab/entry.py`: remove direct `ENTRY_FATAL_MISSING_PRICE_RATIO` parsing, use `cfg.entry_fatal_missing_price_ratio`, and include the threshold in entry `config_snapshot`.
- Modify `.github/workflows/ai-brief.yml`: capture entry report path before exiting non-zero and upload the fatal entry artifact.
- Modify `sab/scheduler/runner.py`: include the produced entry report path in scheduled entry failure diagnostics.
- Modify `config.yaml`: change active market-regime unavailable policy to `block_market` and add `entry_check.fatal_missing_price_ratio: 0.0`.
- Modify `config.example.yaml`: align KIS interval example to the active `200` default and show the entry threshold key.
- Modify `.env.example`: update commented override examples to avoid conflict confusion.
- Modify `docs/configuration.md`, `docs/config-reference.md`, `docs/STRATEGY.md`, and `docs/ARCHITECTURE.md`: document active defaults, YAML primary source, env override conflict behavior, and fatal entry artifact visibility.
- Test `tests/test_config_validation_layers.py`: YAML/env parsing, omitted defaults, strict/non-strict invalid values.
- Test `tests/test_config_conflict_policy.py`: `ENTRY_FATAL_MISSING_PRICE_RATIO` env/YAML duplicate fails closed.
- Test `tests/test_runtime_config_contract.py`: repository `config.yaml` loads the active safety defaults.
- Test `tests/test_entry_command.py` and `tests/test_entry_upload.py`: `run_entry()` uses the config threshold and report snapshots include it.
- Test `tests/test_ai_brief_workflow.py`: manual workflow preserves fatal entry artifact path and upload step.
- Test `tests/test_scheduled_ai_brief_runner.py`: scheduled entry failure includes the written entry report path.
- Test `tests/test_env_example_v11.py` and `tests/test_docs_state_contract.py`: docs/examples expose the new contracts and no active env example conflicts with YAML.

## Task 1: Config Entry Threshold Contract

**Files:**
- Modify: `tests/test_config_validation_layers.py`
- Modify: `tests/test_config_conflict_policy.py`
- Modify: `sab/config.py`

- [ ] **Step 1: Write failing config parsing tests**

In `tests/test_config_validation_layers.py`, add `ENTRY_FATAL_MISSING_PRICE_RATIO` to `_reset_config_env()`:

```python
"ENTRY_FATAL_MISSING_PRICE_RATIO",
```

Append these tests near the market-regime policy tests:

```python
def test_load_config_defaults_entry_fatal_missing_price_ratio(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("entry_check:\n  enabled: false\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 1.0


def test_load_config_parses_entry_fatal_missing_price_ratio_from_yaml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n"
        "  enabled: false\n"
        "  fatal_missing_price_ratio: 0.0\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 0.0


def test_load_config_parses_entry_fatal_missing_price_ratio_from_env(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("entry_check:\n  enabled: false\n", encoding="utf-8")

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", "0.25")

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 0.25


def test_load_config_strict_mode_rejects_invalid_entry_fatal_missing_price_ratio(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n"
        "  fatal_missing_price_ratio: 1.25\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("SAB_CONFIG_STRICT", "1")

    with pytest.raises(ConfigLoadError, match="entry_check.fatal_missing_price_ratio"):
        load_config()


def test_load_config_non_strict_invalid_entry_fatal_missing_price_ratio_falls_back(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n"
        "  fatal_missing_price_ratio: -0.5\n",
        encoding="utf-8",
    )

    _reset_config_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))

    cfg = load_config()

    assert cfg.entry_fatal_missing_price_ratio == 1.0
```

In `tests/test_config_conflict_policy.py`, add `ENTRY_FATAL_MISSING_PRICE_RATIO` to `_reset_conflict_env()` and append:

```python
def test_load_config_rejects_entry_fatal_missing_price_ratio_env_yaml_conflict(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "entry_check:\n"
        "  fatal_missing_price_ratio: 0.0\n",
        encoding="utf-8",
    )

    _reset_conflict_env(monkeypatch)
    _force_fallback_dotenv(monkeypatch)
    monkeypatch.setenv("SAB_CONFIG", str(config_path))
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", "1.0")

    with pytest.raises(
        ConfigLoadError,
        match=r"ENTRY_FATAL_MISSING_PRICE_RATIO \(entry_check\.fatal_missing_price_ratio\)",
    ):
        load_config()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_config_validation_layers.py tests/test_config_conflict_policy.py -q
```

Expected: FAIL with an `AttributeError` for `entry_fatal_missing_price_ratio` or missing conflict binding. The strict invalid test should also fail until range validation is added.

- [ ] **Step 3: Implement config parsing and validation**

In `sab/config.py`, add this conflict binding near the existing entry-adjacent non-secret bindings:

```python
("ENTRY_FATAL_MISSING_PRICE_RATIO", "entry_check.fatal_missing_price_ratio"),
```

Add this field to `Config`:

```python
entry_fatal_missing_price_ratio: float = 1.0
```

Add this dataclass near `_PortfolioSection`:

```python
@dataclass(frozen=True)
class _EntryCheckSection:
    fatal_missing_price_ratio: float
```

Add this parser helper:

```python
def _parse_entry_check_section(parser: _ConfigParser) -> _EntryCheckSection:
    return _EntryCheckSection(
        fatal_missing_price_ratio=parser.env_float(
            "ENTRY_FATAL_MISSING_PRICE_RATIO",
            "entry_check.fatal_missing_price_ratio",
            1.0,
        )
    )
```

Add this normalizer near `_validate_rsi_threshold()`:

```python
def _normalize_probability_threshold(
    path: str,
    value: float,
    *,
    default: float,
    strict: bool,
) -> float:
    if math.isfinite(value) and 0.0 <= value <= 1.0:
        return value
    if strict:
        _raise_range_error(path, f"must be between 0.0 and 1.0 (got {value!r})")
    return default
```

Update `_validate_sections()` to accept and return `entry_check`:

```python
def _validate_sections(
    *,
    data: _DataSection,
    strategy: _StrategySection,
    sell: _SellSection,
    fx: _FxSection,
    portfolio: _PortfolioSection,
    entry_check: _EntryCheckSection,
    strict: bool,
) -> tuple[
    _DataSection,
    _StrategySection,
    _SellSection,
    _FxSection,
    _PortfolioSection,
    _EntryCheckSection,
]:
```

Inside `_validate_sections()`, add:

```python
validated_entry_check = replace(
    entry_check,
    fatal_missing_price_ratio=_normalize_probability_threshold(
        "entry_check.fatal_missing_price_ratio",
        entry_check.fatal_missing_price_ratio,
        default=1.0,
        strict=strict,
    ),
)
```

Return it:

```python
return (
    data,
    validated_strategy,
    validated_sell,
    validated_fx,
    portfolio,
    validated_entry_check,
)
```

Update `_compose_config()` signature and return:

```python
def _compose_config(
    *,
    data: _DataSection,
    strategy: _StrategySection,
    sell: _SellSection,
    fx: _FxSection,
    portfolio: _PortfolioSection,
    entry_check: _EntryCheckSection,
) -> Config:
```

```python
entry_fatal_missing_price_ratio=entry_check.fatal_missing_price_ratio,
```

Update `load_config()`:

```python
entry_check_section = _parse_entry_check_section(parser)
```

and unpack/pass `validated_entry_check`.

- [ ] **Step 4: Run config tests to verify they pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_config_validation_layers.py tests/test_config_conflict_policy.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit config contract**

```bash
git add sab/config.py tests/test_config_validation_layers.py tests/test_config_conflict_policy.py
git commit -m "feat(config): entry 가격 누락 임계치 설정 추가" -m "ENTRY_FATAL_MISSING_PRICE_RATIO를 entry_check.fatal_missing_price_ratio YAML 키와 동일한 충돌 정책으로 승격하고 0.0~1.0 범위 검증을 추가합니다."
```

## Task 2: Entry Runtime Uses Parsed Config

**Files:**
- Modify: `tests/test_entry_command.py`
- Modify: `tests/test_entry_upload.py`
- Modify: `tests/test_entry_portfolio_existing_holding.py`
- Modify: `sab/entry.py`

- [ ] **Step 1: Add failing entry behavior tests**

In `tests/test_entry_upload.py`, add `entry_fatal_missing_price_ratio=1.0` to each `fake_cfg = SimpleNamespace(...)` block.

Append this test to `tests/test_entry_upload.py`:

```python
def test_run_entry_uses_config_threshold_instead_of_env(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [
                    _build_entry_candidate(),
                    {
                        **_build_entry_candidate(),
                        "ticker": "MSFT.NASD",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
        entry_fatal_missing_price_ratio=1.0,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setenv("ENTRY_FATAL_MISSING_PRICE_RATIO", "0.0")
    monkeypatch.setattr(
        "sab.entry._make_price_lookup",
        lambda **_kwargs: (
            lambda ticker: _entry_price_result(None)
            if ticker == "AAPL.NASD"
            else _entry_price_result(101.5),
            [],
        ),
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
        upload=False,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.entry.json")).read_text("utf-8"))
    assert payload["summary"]["missing_entry_price_ratio"] == 0.5
    assert payload["config_snapshot"]["entry_fatal_missing_price_ratio"] == 1.0


def test_run_entry_threshold_zero_fails_on_partial_missing_price(
    monkeypatch, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    buy_report_path = tmp_path / "source.buy.json"
    buy_report_path.write_text(
        json.dumps(
            {
                "run_ts_utc": "2026-02-26T01:30:00Z",
                "eval_context": {"market": "US"},
                "candidates": [
                    _build_entry_candidate(),
                    {
                        **_build_entry_candidate(),
                        "ticker": "MSFT.NASD",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    fake_cfg = SimpleNamespace(
        report_dir=report_dir.as_posix(),
        strategy_mode="ema_cross",
        gap_atr_multiplier=1.0,
        min_history_bars=50,
        data_dir=tmp_path.as_posix(),
        kis_app_key=None,
        kis_app_secret=None,
        kis_base_url=None,
        kis_min_interval_ms=None,
        entry_fatal_missing_price_ratio=0.0,
    )
    monkeypatch.setattr(
        "sab.entry.load_config", lambda provider_override=None: fake_cfg
    )
    monkeypatch.setattr(
        "sab.entry._make_price_lookup",
        lambda **_kwargs: (
            lambda ticker: _entry_price_result(None)
            if ticker == "AAPL.NASD"
            else _entry_price_result(101.5),
            [],
        ),
    )

    exit_code = run_entry(
        buy_report_path=buy_report_path.as_posix(),
        provider="kis",
        mode="PRE_OPEN",
        market="US",
        upload=True,
    )

    assert exit_code == 1
    payload = json.loads(next(report_dir.glob("*.entry.json")).read_text("utf-8"))
    assert payload["summary"]["missing_entry_price_ratio"] == 0.5
    assert payload["config_snapshot"]["entry_fatal_missing_price_ratio"] == 0.0
```

In `tests/test_entry_command.py` and `tests/test_entry_portfolio_existing_holding.py`, add `entry_fatal_missing_price_ratio=1.0` to every `fake_cfg = SimpleNamespace(...)` that is returned from a monkeypatched `sab.entry.load_config`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entry_upload.py tests/test_entry_command.py tests/test_entry_portfolio_existing_holding.py -q
```

Expected: FAIL because `run_entry()` still reads `ENTRY_FATAL_MISSING_PRICE_RATIO` directly and `config_snapshot` does not include `entry_fatal_missing_price_ratio`.

- [ ] **Step 3: Implement entry config consumption**

In `sab/entry.py`, delete `_DEFAULT_ENTRY_FATAL_MISSING_PRICE_RATIO`, `_is_entry_strict_config_mode()`, and `_resolve_entry_fatal_missing_price_ratio()`.

Remove the now-unused `math` import. Keep `os` because `_build_entry_report_payloads()` uses `os.path.basename(...)`.

In `_build_config_snapshot()`, add:

```python
"entry_fatal_missing_price_ratio": cfg.entry_fatal_missing_price_ratio,
```

In `run_entry()`, replace the try/except block that calls `_resolve_entry_fatal_missing_price_ratio()` with:

```python
fatal_missing_price_ratio = cfg.entry_fatal_missing_price_ratio
```

- [ ] **Step 4: Run entry tests to verify they pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_entry_upload.py tests/test_entry_command.py tests/test_entry_portfolio_existing_holding.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit entry runtime changes**

```bash
git add sab/entry.py tests/test_entry_upload.py tests/test_entry_command.py tests/test_entry_portfolio_existing_holding.py
git commit -m "feat(entry): 설정 기반 가격 누락 실패 기준 적용" -m "sab entry가 env를 직접 읽지 않고 load_config 결과의 entry_fatal_missing_price_ratio를 사용하며 리포트 스냅샷에 기준값을 기록합니다."
```

## Task 3: Active Repository Defaults

**Files:**
- Modify: `tests/test_runtime_config_contract.py`
- Modify: `config.yaml`

- [ ] **Step 1: Update failing runtime contract tests**

In `tests/test_runtime_config_contract.py`, change the market-regime assertion and add the entry threshold assertion:

```python
def test_repository_config_defaults_market_regime_unavailable_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_repository_config(monkeypatch)

    assert cfg.market_regime_unavailable_policy == "block_market"


def test_repository_config_defaults_entry_fatal_missing_price_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _load_repository_config(monkeypatch)

    assert cfg.entry_fatal_missing_price_ratio == 0.0
```

- [ ] **Step 2: Run runtime contract tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_runtime_config_contract.py -q
```

Expected: FAIL because active `config.yaml` still uses `warn_continue` and has no `entry_check.fatal_missing_price_ratio`.

- [ ] **Step 3: Update active config**

In `config.yaml`, change:

```yaml
  market_regime_unavailable_policy: warn_continue
```

to:

```yaml
  market_regime_unavailable_policy: block_market
```

Under `entry_check:`, change:

```yaml
entry_check:
  enabled: false
```

to:

```yaml
entry_check:
  enabled: false
  fatal_missing_price_ratio: 0.0
```

- [ ] **Step 4: Run runtime and replay tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_runtime_config_contract.py tests/test_replay_eod_scan.py -q
```

Expected: PASS. Replay fixtures use their own fixture `config.yaml`; if a replay expected JSON changes only because a fixture config was intentionally changed in this task, update the matching `tests/fixtures/replay_eod/scan/*/expected.buy.json` key and rerun this command.

- [ ] **Step 5: Commit active defaults**

```bash
git add config.yaml tests/test_runtime_config_contract.py tests/fixtures/replay_eod/scan
git commit -m "feat(config): 스윙 운영 안전 기본값 강화" -m "활성 config.yaml에서 market regime 미확보 시장을 차단하고 entry 가격 누락 1건도 실패하도록 기본 임계치를 0.0으로 고정합니다."
```

## Task 4: Manual AI Brief Fatal Entry Artifact

**Files:**
- Modify: `tests/test_ai_brief_workflow.py`
- Modify: `.github/workflows/ai-brief.yml`

- [ ] **Step 1: Add failing workflow structure test**

Append this test to `tests/test_ai_brief_workflow.py`:

```python
def test_ai_brief_workflow_uploads_entry_artifact_after_fatal_entry() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    run_entry_step = _find_step_by_name(steps, "Run entry")
    run_entry_script = str(run_entry_step.get("run") or "")

    assert "set +e" in run_entry_script
    assert "entry_status=${PIPESTATUS[0]}" in run_entry_script
    assert 'echo "entry_report_path=${entry_report_path}"' in run_entry_script
    assert 'echo "entry_status=${entry_status}"' in run_entry_script
    assert 'exit "${entry_status}"' in run_entry_script

    upload_step = _find_step_by_name(steps, "Upload fatal entry artifact")
    assert "failure()" in str(upload_step.get("if") or "")
    assert "steps.run_entry.outputs.entry_report_path != ''" in str(
        upload_step.get("if") or ""
    )
    assert "actions/upload-artifact" in str(upload_step.get("uses") or "")
    upload_with = upload_step.get("with") or {}
    assert upload_with.get("name") == "ai-brief-entry-report-${{ github.run_id }}"
    assert upload_with.get("path") == "${{ steps.run_entry.outputs.entry_report_path }}"
```

- [ ] **Step 2: Run workflow test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_workflow.py -q
```

Expected: FAIL because the `Run entry` step still exits before capturing status and there is no fatal-entry upload step.

- [ ] **Step 3: Update workflow entry step**

In `.github/workflows/ai-brief.yml`, replace the entry command portion of `Run entry` with:

```yaml
          set +e
          uv run -m sab entry \
            --provider "${{ steps.params.outputs.provider }}" \
            --mode "${{ steps.params.outputs.entry_mode }}" \
            --market "${{ steps.params.outputs.market }}" \
            --buy-report "${{ steps.run_scan.outputs.buy_report_path }}" \
            --upload 2>&1 | tee entry.log
          entry_status=${PIPESTATUS[0]}
          set -e
```

Keep the existing `entry_report_path` extraction block. After:

```bash
          echo "entry_report_path=${entry_report_path}" >> "${GITHUB_OUTPUT}"
```

add:

```bash
          echo "entry_status=${entry_status}" >> "${GITHUB_OUTPUT}"
          if [[ "${entry_status}" -ne 0 ]]; then
            exit "${entry_status}"
          fi
```

Add this step immediately after `Run entry` and before `Run AI brief`:

```yaml
      - name: Upload fatal entry artifact
        if: failure() && steps.run_entry.outputs.entry_report_path != ''
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7
        with:
          name: ai-brief-entry-report-${{ github.run_id }}
          path: ${{ steps.run_entry.outputs.entry_report_path }}
```

- [ ] **Step 4: Run workflow tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_workflow.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit workflow artifact change**

```bash
git add .github/workflows/ai-brief.yml tests/test_ai_brief_workflow.py
git commit -m "fix(workflow): fatal entry 리포트 artifact 보존" -m "AI Brief 수동 워크플로우에서 sab entry가 실패해도 작성된 entry report 경로를 output으로 남기고 별도 artifact로 업로드합니다."
```

## Task 5: Scheduled Entry Failure Diagnostics

**Files:**
- Modify: `tests/test_scheduled_ai_brief_runner.py`
- Modify: `sab/scheduler/runner.py`

- [ ] **Step 1: Add failing scheduler diagnostic test**

Append this test near `test_default_pipeline_entry_step_helper_returns_single_entry_report()` in `tests/test_scheduled_ai_brief_runner.py`:

```python
def test_default_pipeline_entry_step_failure_mentions_written_entry_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 1

    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)

    with pytest.raises(
        RuntimeError,
        match=r"scheduled entry failed.*reports/current\.entry\.json",
    ):
        DefaultScheduledPipeline()._run_entry_step(
            market="US",
            report_date="2026-05-28",
            buy_report_path="reports/current.buy.json",
            holdings_path="data/scheduler/holdings.US.2026-05-28.yaml",
        )
```

- [ ] **Step 2: Run scheduler test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_entry_step_failure_mentions_written_entry_report -q
```

Expected: FAIL because `_run_entry_step()` raises `scheduled entry failed` without the report path.

- [ ] **Step 3: Implement scheduled diagnostic message**

In `sab/scheduler/runner.py`, replace:

```python
        if entry_status != 0:
            raise RuntimeError("scheduled entry failed")
```

with:

```python
        if entry_status != 0:
            report_hint = entry_report_paths[-1] if entry_report_paths else "not produced"
            raise RuntimeError(
                f"scheduled entry failed (entry_report_path={report_hint})"
            )
```

- [ ] **Step 4: Run scheduler tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_scheduled_ai_brief_runner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit scheduled diagnostics**

```bash
git add sab/scheduler/runner.py tests/test_scheduled_ai_brief_runner.py
git commit -m "fix(scheduler): entry 실패 진단에 리포트 경로 포함" -m "scheduled AI Brief entry 단계가 non-zero로 끝나도 report_path_callback으로 받은 entry report 경로를 RuntimeError에 포함합니다."
```

## Task 6: Docs and Examples

**Files:**
- Modify: `tests/test_env_example_v11.py`
- Modify: `tests/test_docs_state_contract.py`
- Modify: `.env.example`
- Modify: `config.example.yaml`
- Modify: `docs/configuration.md`
- Modify: `docs/config-reference.md`
- Modify: `docs/STRATEGY.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Add failing docs/example tests**

In `tests/test_env_example_v11.py`, append:

```python
def test_env_example_documents_entry_fatal_override_without_active_override() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example_path.read_text(encoding="utf-8")
    active_keys = set(_extract_env_keys(env_example_path))

    assert "ENTRY_FATAL_MISSING_PRICE_RATIO" in text
    assert "entry_check.fatal_missing_price_ratio" in text
    assert "ENTRY_FATAL_MISSING_PRICE_RATIO" not in active_keys


def test_env_example_uses_active_kis_interval_in_commented_override() -> None:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    text = env_example_path.read_text(encoding="utf-8")

    assert "# KIS_MIN_INTERVAL_MS=200" in text
    assert "# KIS_MIN_INTERVAL_MS=500" not in text
```

In `tests/test_docs_state_contract.py`, extend `test_strategy_docs_include_swing_logic_improvement_contracts()`:

```python
    configuration_text = _read(Path("docs/configuration.md"))

    assert "entry_check.fatal_missing_price_ratio" in strategy_text
    assert "ENTRY_FATAL_MISSING_PRICE_RATIO" in config_reference_text
    assert "entry_check.fatal_missing_price_ratio" in config_reference_text
    assert "| `KIS_MIN_INTERVAL_MS` | no | `config.yaml` `kis.min_interval_ms` | `200`" in configuration_text
```

- [ ] **Step 2: Run docs tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_env_example_v11.py tests/test_docs_state_contract.py -q
```

Expected: FAIL because docs/examples still present entry fatal as env-only and KIS interval examples still show `500`.

- [ ] **Step 3: Update `.env.example`**

Change:

```env
# KIS_MIN_INTERVAL_MS=500
```

to:

```env
# KIS_MIN_INTERVAL_MS=200
```

Replace the entry fatal comment block with:

```env
# Optional: entry_price 누락 비율 임계치 override.
# 기본 운영값은 config.yaml `entry_check.fatal_missing_price_ratio`입니다.
# 같은 키를 YAML과 env에 동시에 두면 충돌로 실패합니다.
# 0.0은 누락이 1건이라도 있으면 `sab entry` exit 1로 처리합니다.
# ENTRY_FATAL_MISSING_PRICE_RATIO=0.0
```

Replace the market regime comment block with:

```env
# Optional: market regime benchmark unavailable 처리 정책 override.
# 기본 운영값은 config.yaml `strategy.market_regime_unavailable_policy`입니다.
# YAML에 같은 키가 있으면 env override는 충돌로 실패합니다.
# MARKET_REGIME_UNAVAILABLE_POLICY=block_market
```

- [ ] **Step 4: Update `config.example.yaml`**

Change:

```yaml
  min_interval_ms: 500
```

to:

```yaml
  min_interval_ms: 200
```

Under `strategy.use_market_regime_filter`, add:

```yaml
  market_regime_unavailable_policy: block_market  # warn_continue | block_market
```

Under `entry_check:`, add:

```yaml
  fatal_missing_price_ratio: 0.0  # 0.0이면 entry price 누락 1건도 실패
```

- [ ] **Step 5: Update config docs**

In `docs/configuration.md`, update the `KIS_MIN_INTERVAL_MS` row so the example is `200`.

Update the `MARKET_REGIME_UNAVAILABLE_POLICY` row so the default column references `config.yaml` and the notes mention env/YAML conflict:

```markdown
| `MARKET_REGIME_UNAVAILABLE_POLICY` | no | `config.yaml` `strategy.market_regime_unavailable_policy` | `block_market` | `sab scan` | Market regime unavailable policy | Env/YAML conflict binding. |
```

Update the `ENTRY_FATAL_MISSING_PRICE_RATIO` row:

```markdown
| `ENTRY_FATAL_MISSING_PRICE_RATIO` | no | `config.yaml` `entry_check.fatal_missing_price_ratio`; code fallback `1.0` | `0.0` | `sab entry` | Missing entry price fatal threshold | Env/YAML conflict binding. 0.0 means any missing price fails. |
```

In `docs/config-reference.md`, replace:

```markdown
| `ENTRY_FATAL_MISSING_PRICE_RATIO` | `sab entry` | 0.0-1.0, 기본 1.0 |
```

with:

```markdown
| `ENTRY_FATAL_MISSING_PRICE_RATIO` | `sab entry` | `entry_check.fatal_missing_price_ratio` env override, 0.0-1.0, 코드 fallback 1.0 |
```

Add this row to the CLI Config Override Bindings table:

```markdown
| `ENTRY_FATAL_MISSING_PRICE_RATIO` | `entry_check.fatal_missing_price_ratio` | entry price 누락 fatal 임계치 |
```

- [ ] **Step 6: Update strategy and architecture docs**

In `docs/STRATEGY.md`, add this bullet under the `sab entry` report behavior section:

```markdown
- `entry_check.fatal_missing_price_ratio`는 entry price 누락 비율이 어느 수준부터 fatal인지 정합니다. 활성 운영 기본값은 `0.0`이므로 누락이 1건이라도 있으면 entry report를 쓴 뒤 `sab entry`가 non-zero로 종료합니다. 코드 fallback은 기존 호환성을 위해 `1.0`입니다.
```

In `docs/ARCHITECTURE.md`, extend the manual AI Brief flow note with:

```markdown
`sab entry`가 fatal missing-price 정책으로 non-zero 종료해도 이미 작성된 entry report는 workflow output과 별도 artifact upload step으로 노출해 진단 가능성을 유지합니다.
```

- [ ] **Step 7: Run docs tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_env_example_v11.py tests/test_docs_state_contract.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit docs/examples**

```bash
git add .env.example config.example.yaml docs/configuration.md docs/config-reference.md docs/STRATEGY.md docs/ARCHITECTURE.md tests/test_env_example_v11.py tests/test_docs_state_contract.py
git commit -m "docs(config): 스윙 운영 안전 기본값 문서화" -m "entry fatal threshold의 YAML 기준, env 충돌 정책, market regime 기본 차단, KIS 200ms 기본값을 docs와 예시에 반영합니다."
```

## Task 7: Final Verification

**Files:**
- Verify only; do not modify files in this task.

- [ ] **Step 1: Run targeted regression suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_config_validation_layers.py tests/test_config_conflict_policy.py tests/test_runtime_config_contract.py tests/test_entry_upload.py tests/test_entry_command.py tests/test_entry_portfolio_existing_holding.py tests/test_ai_brief_workflow.py tests/test_scheduled_ai_brief_runner.py tests/test_env_example_v11.py tests/test_docs_state_contract.py tests/test_replay_eod_scan.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Python quality gate**

Run:

```bash
just quality
```

Expected: PASS. If `just` fails because `pnpm` is missing from `PATH`, rerun:

```bash
mise exec -- just quality
```

Expected: PASS.

- [ ] **Step 3: Review final diff**

Run:

```bash
git status --short
git log --oneline -7
```

Expected: working tree clean, with the six implementation commits from Tasks 1-6 on top of the design commits.

