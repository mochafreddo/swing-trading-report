# Swing Replay Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand deterministic scan replay coverage for active swing thresholds across market, regime, relative-strength, volatility, gap, stop-alignment, profit-target, and volume-confirmation axes without changing trading thresholds.

**Architecture:** Keep the existing scan replay harness as the execution path. Add a small metadata contract (`case.yaml`) beside every replay case, add a metadata coverage gate in pytest, use committed static fixture directories for the replay matrix, and keep historical performance backtesting as a later design.

**Tech Stack:** Python 3.14, pytest, PyYAML, existing `tests/helpers/replay_eod.py`, existing `sab.scan.run_scan` fixture monkeypatch path, `uv`, `just`, Markdown docs.

## Global Constraints

- Do not change default trading thresholds in this pass.
- Do not add automated order placement.
- Do not build a full historical performance backtest runner in this pass.
- Do not assert win rate, expected value, MFE/MAE, or stop/target hit-rate from synthetic replay fixtures.
- Do not rely on live market data, KIS, PyKRX, Supabase, or network access.
- Replay coverage proves deterministic rule semantics, not trading profitability.
- Commit messages must be Korean Conventional Commits.

---

## File Structure

- Modify `tests/helpers/replay_eod.py`: owns replay fixture validation, metadata parsing, metadata value validation, and the pure helper interfaces consumed by replay tests and fixture tooling.
- Modify `tests/test_replay_eod_scan.py`: owns replay artifact comparison tests plus metadata coverage gate tests.
- Create `scripts/update_scan_replay_expected.py`: deterministic local helper that refreshes `expected.buy.json` from the existing replay harness.
- Modify existing fixture dirs under `tests/fixtures/replay_eod/scan/`: add `case.yaml` to `kr_ema_cross_baseline` and `kr_hybrid_quality_order`.
- Create new fixture dirs under `tests/fixtures/replay_eod/scan/`: add the initial replay coverage matrix.
- Modify `docs/STRATEGY.md`: documents replay-vs-backtest semantics.
- Modify `TODOS.md`: marks first replay-matrix expansion complete and keeps historical backtest runner as deferred work.

---

## Task 1: Replay Case Metadata Contract

**Files:**
- Modify: `tests/helpers/replay_eod.py`
- Modify: `tests/test_replay_eod_scan.py`
- Create: `tests/fixtures/replay_eod/scan/kr_ema_cross_baseline/case.yaml`
- Create: `tests/fixtures/replay_eod/scan/kr_hybrid_quality_order/case.yaml`

**Interfaces:**
- Produces: `ReplayScanCaseMetadata`, `load_scan_replay_case_metadata(case_dir: Path) -> ReplayScanCaseMetadata`, `load_scan_replay_case_metadatas(root: Path) -> list[ReplayScanCaseMetadata]`.
- Consumes: existing `ReplayScanCaseError`, `validate_scan_replay_case_dir(case_dir)`.

- [ ] **Step 1: Write failing metadata parser tests**

Add `load_scan_replay_case_metadata` to the import list in `tests/test_replay_eod_scan.py`:

```python
from tests.helpers.replay_eod import (
    ReplayScanCaseError,
    iter_scan_replay_case_dirs,
    load_scan_replay_case_metadata,
    normalize_scan_artifact,
    run_scan_replay_case,
    validate_scan_replay_case_dir,
)
```

Append these tests to `tests/test_replay_eod_scan.py`:

```python
def test_load_scan_replay_case_metadata_parses_valid_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "valid"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(
        "\n".join(
            [
                "schema: sab.replay.scan-case.v1",
                'purpose: "strong US breakout candidate with quality A"',
                "market: US",
                "strategy_mode: sma_ema_hybrid",
                "regime: rising",
                "pattern: swing_high_breakout",
                "relative_strength: strong",
                "volatility: normal",
                "expected_outcome: candidate_quality_a",
                "threshold_axes:",
                "  - consolidation",
                "  - volume_confirmation",
                "  - relative_strength",
                "",
            ]
        ),
        encoding="utf-8",
    )

    metadata = load_scan_replay_case_metadata(case_dir)

    assert metadata.case_dir == case_dir
    assert metadata.name == "valid"
    assert metadata.market == "US"
    assert metadata.strategy_mode == "sma_ema_hybrid"
    assert metadata.regime == "rising"
    assert metadata.pattern == "swing_high_breakout"
    assert metadata.relative_strength == "strong"
    assert metadata.volatility == "normal"
    assert metadata.expected_outcome == "candidate_quality_a"
    assert metadata.threshold_axes == frozenset(
        {"consolidation", "volume_confirmation", "relative_strength"}
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "wrong.schema"),
        ("market", "JP"),
        ("strategy_mode", "hybrid"),
        ("regime", "bull"),
        ("pattern", "cup_handle"),
        ("relative_strength", "medium"),
        ("volatility", "medium"),
        ("expected_outcome", "maybe_candidate"),
    ],
)
def test_load_scan_replay_case_metadata_rejects_invalid_choices(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = {
        "schema": "sab.replay.scan-case.v1",
        "purpose": "invalid field check",
        "market": "KR",
        "strategy_mode": "sma_ema_hybrid",
        "regime": "rising",
        "pattern": "trend_pullback_bounce",
        "relative_strength": "strong",
        "volatility": "normal",
        "expected_outcome": "candidate_quality_a",
        "threshold_axes": ["rsi"],
    }
    payload[field] = value
    case_dir = tmp_path / "invalid"
    case_dir.mkdir()
    yaml_text = "\n".join(
        [
            f"schema: {payload['schema']}",
            f"purpose: {payload['purpose']!r}",
            f"market: {payload['market']}",
            f"strategy_mode: {payload['strategy_mode']}",
            f"regime: {payload['regime']}",
            f"pattern: {payload['pattern']}",
            f"relative_strength: {payload['relative_strength']}",
            f"volatility: {payload['volatility']}",
            f"expected_outcome: {payload['expected_outcome']}",
            "threshold_axes:",
            *[f"  - {axis}" for axis in payload["threshold_axes"]],
            "",
        ]
    )
    (case_dir / "case.yaml").write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ReplayScanCaseError, match=field):
        load_scan_replay_case_metadata(case_dir)


def test_load_scan_replay_case_metadata_rejects_empty_threshold_axes(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "empty_axes"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(
        "\n".join(
            [
                "schema: sab.replay.scan-case.v1",
                'purpose: "empty axes check"',
                "market: KR",
                "strategy_mode: sma_ema_hybrid",
                "regime: rising",
                "pattern: trend_pullback_bounce",
                "relative_strength: strong",
                "volatility: normal",
                "expected_outcome: candidate_quality_a",
                "threshold_axes: []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReplayScanCaseError, match="threshold_axes"):
        load_scan_replay_case_metadata(case_dir)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py::test_load_scan_replay_case_metadata_parses_valid_case tests/test_replay_eod_scan.py::test_load_scan_replay_case_metadata_rejects_invalid_choices tests/test_replay_eod_scan.py::test_load_scan_replay_case_metadata_rejects_empty_threshold_axes -q
```

Expected: FAIL with import error because `load_scan_replay_case_metadata` does not exist.

- [ ] **Step 3: Implement metadata dataclass and parser**

In `tests/helpers/replay_eod.py`, add the YAML import near the existing imports:

```python
import yaml  # type: ignore[import-untyped]
```

Replace `SCAN_REPLAY_REQUIRED_FILES` with:

```python
SCAN_REPLAY_REQUIRED_FILES = (
    "case.yaml",
    "config.yaml",
    "watchlist.txt",
    "adjusted_market_data.json",
    "raw_market_data.json",
    "expected.buy.json",
)
```

Add these constants and dataclass after `ReplayScanCaseError`:

```python
_REPLAY_CASE_SCHEMA = "sab.replay.scan-case.v1"
_REPLAY_CASE_MARKETS = frozenset({"KR", "US", "MIXED"})
_REPLAY_CASE_STRATEGY_MODES = frozenset({"ema_cross", "sma_ema_hybrid"})
_REPLAY_CASE_REGIMES = frozenset(
    {"rising", "sideways", "falling", "not_applicable"}
)
_REPLAY_CASE_PATTERNS = frozenset(
    {
        "trend_pullback_bounce",
        "swing_high_breakout",
        "rsi_oversold_reversal",
        "ema_cross",
        "none",
    }
)
_REPLAY_CASE_RELATIVE_STRENGTH = frozenset(
    {"strong", "weak", "unavailable", "not_applicable"}
)
_REPLAY_CASE_VOLATILITY = frozenset(
    {"normal", "high", "unknown", "not_applicable"}
)
_REPLAY_CASE_EXPECTED_OUTCOMES = frozenset(
    {
        "candidate_quality_a",
        "candidate_quality_b",
        "candidate_quality_c",
        "candidate_present",
        "rejected_by_gap",
        "blocked_by_market_regime",
        "no_candidate",
    }
)
_REPLAY_CASE_THRESHOLD_AXES = frozenset(
    {
        "rsi",
        "consolidation",
        "gap",
        "stop_alignment",
        "profit_target",
        "volume_confirmation",
        "relative_strength",
        "market_regime",
        "entry_state",
    }
)


@dataclass(frozen=True)
class ReplayScanCaseMetadata:
    case_dir: Path
    name: str
    purpose: str
    market: str
    strategy_mode: str
    regime: str
    pattern: str
    relative_strength: str
    volatility: str
    expected_outcome: str
    threshold_axes: frozenset[str]
```

Add these helpers after `iter_scan_replay_case_dirs`:

```python
def _load_case_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ReplayScanCaseError(f"failed to load replay case metadata '{path}': {exc}") from exc
    if not isinstance(loaded, dict):
        raise ReplayScanCaseError(f"replay case metadata '{path}' must be a mapping")
    return cast(dict[str, Any], loaded)


def _metadata_error(case_dir: Path, field: str, message: str) -> ReplayScanCaseError:
    return ReplayScanCaseError(f"invalid replay case metadata {field}: {message} ({case_dir})")


def _require_str(
    payload: dict[str, Any],
    *,
    case_dir: Path,
    field: str,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _metadata_error(case_dir, field, "must be a non-empty string")
    return value.strip()


def _require_choice(
    payload: dict[str, Any],
    *,
    case_dir: Path,
    field: str,
    allowed: frozenset[str],
) -> str:
    value = _require_str(payload, case_dir=case_dir, field=field)
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise _metadata_error(case_dir, field, f"must be one of: {allowed_text}")
    return value


def _require_threshold_axes(
    payload: dict[str, Any],
    *,
    case_dir: Path,
) -> frozenset[str]:
    value = payload.get("threshold_axes")
    if not isinstance(value, list) or not value:
        raise _metadata_error(case_dir, "threshold_axes", "must be a non-empty list")
    axes: set[str] = set()
    for index, raw_axis in enumerate(value):
        if not isinstance(raw_axis, str) or not raw_axis.strip():
            raise _metadata_error(
                case_dir,
                "threshold_axes",
                f"item {index} must be a non-empty string",
            )
        axis = raw_axis.strip()
        if axis not in _REPLAY_CASE_THRESHOLD_AXES:
            allowed_text = ", ".join(sorted(_REPLAY_CASE_THRESHOLD_AXES))
            raise _metadata_error(
                case_dir,
                "threshold_axes",
                f"item {index} must be one of: {allowed_text}",
            )
        axes.add(axis)
    return frozenset(sorted(axes))


def load_scan_replay_case_metadata(case_dir: Path) -> ReplayScanCaseMetadata:
    payload = _load_case_yaml(case_dir / "case.yaml")
    schema = _require_str(payload, case_dir=case_dir, field="schema")
    if schema != _REPLAY_CASE_SCHEMA:
        raise _metadata_error(case_dir, "schema", f"must be {_REPLAY_CASE_SCHEMA}")
    return ReplayScanCaseMetadata(
        case_dir=case_dir,
        name=case_dir.name,
        purpose=_require_str(payload, case_dir=case_dir, field="purpose"),
        market=_require_choice(
            payload,
            case_dir=case_dir,
            field="market",
            allowed=_REPLAY_CASE_MARKETS,
        ),
        strategy_mode=_require_choice(
            payload,
            case_dir=case_dir,
            field="strategy_mode",
            allowed=_REPLAY_CASE_STRATEGY_MODES,
        ),
        regime=_require_choice(
            payload,
            case_dir=case_dir,
            field="regime",
            allowed=_REPLAY_CASE_REGIMES,
        ),
        pattern=_require_choice(
            payload,
            case_dir=case_dir,
            field="pattern",
            allowed=_REPLAY_CASE_PATTERNS,
        ),
        relative_strength=_require_choice(
            payload,
            case_dir=case_dir,
            field="relative_strength",
            allowed=_REPLAY_CASE_RELATIVE_STRENGTH,
        ),
        volatility=_require_choice(
            payload,
            case_dir=case_dir,
            field="volatility",
            allowed=_REPLAY_CASE_VOLATILITY,
        ),
        expected_outcome=_require_choice(
            payload,
            case_dir=case_dir,
            field="expected_outcome",
            allowed=_REPLAY_CASE_EXPECTED_OUTCOMES,
        ),
        threshold_axes=_require_threshold_axes(payload, case_dir=case_dir),
    )


def load_scan_replay_case_metadatas(root: Path) -> list[ReplayScanCaseMetadata]:
    return [load_scan_replay_case_metadata(case_dir) for case_dir in iter_scan_replay_case_dirs(root)]
```

- [ ] **Step 4: Backfill existing fixture metadata**

Create `tests/fixtures/replay_eod/scan/kr_ema_cross_baseline/case.yaml`:

```yaml
schema: sab.replay.scan-case.v1
purpose: "KR ema_cross baseline preserves legacy scan artifact contract"
market: KR
strategy_mode: ema_cross
regime: not_applicable
pattern: ema_cross
relative_strength: unavailable
volatility: not_applicable
expected_outcome: candidate_present
threshold_axes:
  - relative_strength
```

Create `tests/fixtures/replay_eod/scan/kr_hybrid_quality_order/case.yaml`:

```yaml
schema: sab.replay.scan-case.v1
purpose: "KR hybrid quality ordering keeps aligned A before tight-stop B"
market: KR
strategy_mode: sma_ema_hybrid
regime: rising
pattern: swing_high_breakout
relative_strength: strong
volatility: high
expected_outcome: candidate_quality_b
threshold_axes:
  - consolidation
  - volume_confirmation
  - relative_strength
  - stop_alignment
```

- [ ] **Step 5: Run metadata and existing replay tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
```

Expected: PASS. If `test_validate_scan_replay_case_dir_rejects_missing_required_files` reports a changed missing-file message, keep the assertion broad: `match="missing required replay case files"`.

- [ ] **Step 6: Commit metadata contract**

```bash
git add tests/helpers/replay_eod.py tests/test_replay_eod_scan.py tests/fixtures/replay_eod/scan/kr_ema_cross_baseline/case.yaml tests/fixtures/replay_eod/scan/kr_hybrid_quality_order/case.yaml
git commit -m "test(replay): 리플레이 케이스 메타데이터 계약 추가"
```

---

## Task 2: Replay Coverage Gate

**Files:**
- Modify: `tests/test_replay_eod_scan.py`

**Interfaces:**
- Consumes: `load_scan_replay_case_metadatas(root: Path) -> list[ReplayScanCaseMetadata]` from Task 1.
- Produces: coverage tests that fail until matrix fixture cases are added.

- [ ] **Step 1: Write failing coverage tests**

Add `load_scan_replay_case_metadatas` to the import list in `tests/test_replay_eod_scan.py`:

```python
from tests.helpers.replay_eod import (
    ReplayScanCaseError,
    iter_scan_replay_case_dirs,
    load_scan_replay_case_metadata,
    load_scan_replay_case_metadatas,
    normalize_scan_artifact,
    run_scan_replay_case,
    validate_scan_replay_case_dir,
)
```

Add these constants near `_SCAN_REPLAY_CASES`:

```python
_REQUIRED_REPLAY_MARKETS = {"KR", "US"}
_REQUIRED_REPLAY_REGIMES = {"rising", "sideways", "falling"}
_REQUIRED_REPLAY_PATTERNS = {
    "trend_pullback_bounce",
    "swing_high_breakout",
    "rsi_oversold_reversal",
}
_REQUIRED_REPLAY_OUTCOMES = {
    "candidate_quality_a",
    "candidate_quality_b",
    "rejected_by_gap",
    "blocked_by_market_regime",
}
_REQUIRED_REPLAY_THRESHOLD_AXES = {
    "rsi",
    "consolidation",
    "gap",
    "stop_alignment",
    "profit_target",
    "volume_confirmation",
}
```

Append this test:

```python
def test_scan_replay_metadata_covers_active_swing_threshold_matrix() -> None:
    metadata = load_scan_replay_case_metadatas(_SCAN_REPLAY_ROOT)

    markets = {case.market for case in metadata}
    regimes = {case.regime for case in metadata}
    patterns = {case.pattern for case in metadata}
    relative_strengths = {case.relative_strength for case in metadata}
    volatility_states = {case.volatility for case in metadata}
    outcomes = {case.expected_outcome for case in metadata}
    threshold_axes = set().union(*(case.threshold_axes for case in metadata))

    assert markets >= _REQUIRED_REPLAY_MARKETS
    assert regimes >= _REQUIRED_REPLAY_REGIMES
    assert patterns >= _REQUIRED_REPLAY_PATTERNS
    assert {"strong", "weak"} <= relative_strengths
    assert {"normal", "high"} <= volatility_states
    assert outcomes >= _REQUIRED_REPLAY_OUTCOMES
    assert threshold_axes >= _REQUIRED_REPLAY_THRESHOLD_AXES
```

- [ ] **Step 2: Run coverage test to verify failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py::test_scan_replay_metadata_covers_active_swing_threshold_matrix -q
```

Expected: FAIL because current metadata has no US, sideways, falling, RSI reversal, gap rejection, market-regime block, weak RS, normal volatility, `rsi`, `gap`, or `profit_target` coverage.

- [ ] **Step 3: Commit the failing coverage gate only if using subagent review checkpoints**

For normal inline execution, do not commit a failing test. Keep it staged for Task 4. For subagent-driven execution, let the reviewer see this failing gate before fixture work.

---

## Task 3: Expected Artifact Refresh Tool

**Files:**
- Create: `scripts/update_scan_replay_expected.py`

**Interfaces:**
- Consumes: `run_scan_replay_case(case_dir, tmp_path, monkeypatch)` from `tests.helpers.replay_eod`.
- Produces: CLI command `UV_CACHE_DIR=.uv-cache uv run python scripts/update_scan_replay_expected.py <case-dir> [...]` that rewrites `expected.buy.json` with `normalized_actual`.

- [ ] **Step 1: Create the script**

Create `scripts/update_scan_replay_expected.py`:

```python
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pytest

from tests.helpers.replay_eod import (
    ReplayScanCaseError,
    iter_scan_replay_case_dirs,
    run_scan_replay_case,
)

_DEFAULT_REPLAY_ROOT = Path("tests/fixtures/replay_eod/scan")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh scan replay expected.buy.json artifacts.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Replay case directory paths. Defaults to every scan replay case.",
    )
    return parser.parse_args()


def _resolve_case_dirs(paths: list[Path]) -> list[Path]:
    if paths:
        return [path for path in paths if path.is_dir()]
    return iter_scan_replay_case_dirs(_DEFAULT_REPLAY_ROOT)


def _ensure_expected_placeholder(case_dir: Path) -> None:
    expected_path = case_dir / "expected.buy.json"
    if not expected_path.exists():
        expected_path.write_text("{}\n", encoding="utf-8")


def _refresh_case(case_dir: Path) -> None:
    _ensure_expected_placeholder(case_dir)
    monkeypatch = pytest.MonkeyPatch()
    try:
        with tempfile.TemporaryDirectory(prefix=f"{case_dir.name}-replay-") as tmp_dir:
            result = run_scan_replay_case(
                case_dir,
                tmp_path=Path(tmp_dir),
                monkeypatch=monkeypatch,
            )
    finally:
        monkeypatch.undo()
    expected_path = case_dir / "expected.buy.json"
    expected_path.write_text(
        json.dumps(result.normalized_actual, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"updated {expected_path}")


def main() -> int:
    case_dirs = _resolve_case_dirs(_parse_args().paths)
    if not case_dirs:
        raise ReplayScanCaseError("no replay case directories found")
    for case_dir in case_dirs:
        _refresh_case(case_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the script on existing cases**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/update_scan_replay_expected.py tests/fixtures/replay_eod/scan/kr_ema_cross_baseline tests/fixtures/replay_eod/scan/kr_hybrid_quality_order
```

Expected: command exits 0 and rewrites the two expected files. If the only diff is formatting from compact JSON to indented JSON with equal content, keep the rewritten files because they become easier to review. If the semantic content changes unexpectedly, stop and inspect the generated diff before continuing.

- [ ] **Step 3: Run script lint and replay tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check scripts/update_scan_replay_expected.py
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
```

Expected: replay tests still fail only on `test_scan_replay_metadata_covers_active_swing_threshold_matrix` until Task 4 lands. Parser and artifact comparison tests pass.

- [ ] **Step 4: Commit the tool**

If expected artifact files changed only by formatting, include them in this commit. If Task 2 is still failing, do not commit this task separately during inline execution. In subagent-driven execution, use:

```bash
git add scripts/update_scan_replay_expected.py tests/fixtures/replay_eod/scan/kr_ema_cross_baseline/expected.buy.json tests/fixtures/replay_eod/scan/kr_hybrid_quality_order/expected.buy.json
git commit -m "test(replay): 리플레이 기대값 갱신 도구 추가"
```

---

## Task 4: Initial Replay Matrix Fixtures

**Files:**
- Create: `tests/fixtures/replay_eod/scan/us_hybrid_strong_rs_breakout/*`
- Create: `tests/fixtures/replay_eod/scan/kr_hybrid_weak_rs_pullback/*`
- Create: `tests/fixtures/replay_eod/scan/us_hybrid_high_vol_tight_stop/*`
- Create: `tests/fixtures/replay_eod/scan/kr_hybrid_gap_rejected/*`
- Create: `tests/fixtures/replay_eod/scan/us_hybrid_sideways_consolidation/*`
- Create: `tests/fixtures/replay_eod/scan/kr_hybrid_falling_regime_blocked/*`
- Create: `tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation/*`
- Create: `tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal/*`

**Interfaces:**
- Consumes: metadata contract from Task 1, coverage gate from Task 2, expected updater from Task 3.
- Produces: committed static fixture directories whose generated artifacts pass `tests/test_replay_eod_scan.py`.

- [ ] **Step 1: Create the fixture directories and metadata**

Create the eight directories listed above. Each directory must contain `case.yaml`, `config.yaml`, `watchlist.txt`, `adjusted_market_data.json`, `raw_market_data.json`, and `expected.buy.json`.

Use these `case.yaml` files:

`tests/fixtures/replay_eod/scan/us_hybrid_strong_rs_breakout/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "US strong relative-strength breakout produces quality A"
market: US
strategy_mode: sma_ema_hybrid
regime: rising
pattern: swing_high_breakout
relative_strength: strong
volatility: normal
expected_outcome: candidate_quality_a
threshold_axes:
  - consolidation
  - volume_confirmation
  - relative_strength
  - profit_target
```

`tests/fixtures/replay_eod/scan/kr_hybrid_weak_rs_pullback/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "KR ready pullback with weak relative strength is quality B"
market: KR
strategy_mode: sma_ema_hybrid
regime: rising
pattern: trend_pullback_bounce
relative_strength: weak
volatility: normal
expected_outcome: candidate_quality_b
threshold_axes:
  - rsi
  - relative_strength
  - volume_confirmation
```

`tests/fixtures/replay_eod/scan/us_hybrid_high_vol_tight_stop/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "US high-volatility breakout warns on stop alignment"
market: US
strategy_mode: sma_ema_hybrid
regime: rising
pattern: swing_high_breakout
relative_strength: strong
volatility: high
expected_outcome: candidate_quality_b
threshold_axes:
  - consolidation
  - gap
  - stop_alignment
  - volume_confirmation
```

`tests/fixtures/replay_eod/scan/kr_hybrid_gap_rejected/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "KR oversized signal-day gap is rejected"
market: KR
strategy_mode: sma_ema_hybrid
regime: rising
pattern: none
relative_strength: strong
volatility: high
expected_outcome: rejected_by_gap
threshold_axes:
  - gap
```

`tests/fixtures/replay_eod/scan/us_hybrid_sideways_consolidation/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "US sideways consolidation breakout remains quality A"
market: US
strategy_mode: sma_ema_hybrid
regime: sideways
pattern: swing_high_breakout
relative_strength: strong
volatility: normal
expected_outcome: candidate_quality_a
threshold_axes:
  - consolidation
  - volume_confirmation
```

`tests/fixtures/replay_eod/scan/kr_hybrid_falling_regime_blocked/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "KR falling benchmark blocks candidate through market regime filter"
market: KR
strategy_mode: sma_ema_hybrid
regime: falling
pattern: none
relative_strength: not_applicable
volatility: normal
expected_outcome: blocked_by_market_regime
threshold_axes:
  - market_regime
```

`tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "KR pullback bounce uses volume confirmation"
market: KR
strategy_mode: sma_ema_hybrid
regime: rising
pattern: trend_pullback_bounce
relative_strength: strong
volatility: normal
expected_outcome: candidate_quality_a
threshold_axes:
  - rsi
  - volume_confirmation
  - profit_target
```

`tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal/case.yaml`

```yaml
schema: sab.replay.scan-case.v1
purpose: "US RSI oversold reversal produces quality A"
market: US
strategy_mode: sma_ema_hybrid
regime: sideways
pattern: rsi_oversold_reversal
relative_strength: strong
volatility: normal
expected_outcome: candidate_quality_a
threshold_axes:
  - rsi
  - volume_confirmation
  - profit_target
```

- [ ] **Step 2: Use a shared compact hybrid config template**

For candidate-producing hybrid cases, use this `config.yaml` baseline and change only the values noted below each case:

```yaml
data:
  provider: pykrx
  report_dir: reports
  data_dir: data
files:
  watchlist: watchlist.txt
universe:
  markets:
    - KR
strategy:
  mode: sma_ema_hybrid
  min_history_bars: 30
  gap_atr_multiplier: 1.0
  use_sma200_filter: false
  use_market_regime_filter: false
  require_slope_up: false
  rs_lookback_days: 5
  rs_benchmark_return: 0.02
  hybrid:
    sma_trend_period: 20
    ema_short_period: 10
    ema_mid_period: 21
    rsi_period: 14
    rsi_zone_low: 40
    rsi_zone_high: 70
    rsi_oversold_low: 25
    rsi_oversold_high: 40
    pullback_max_bars: 7
    breakout_consolidation_min_bars: 4
    breakout_consolidation_max_bars: 12
    breakout_consolidation_max_range_pct: 0.10
    volume_lookback_days: 3
    max_gap_pct: 0.08
    use_sma60_filter: false
    sma60_period: 55
    kr_breakout_requires_confirmation: false
screener:
  enabled: false
  min_price: 0
  min_dollar_volume: 0
sell:
  hybrid:
    stop_loss_pct_max: 0.05
```

For US cases, set:

```yaml
universe:
  markets:
    - US
screener:
  enabled: false
  min_price: 0
  min_dollar_volume: 0
  us:
    min_price: 0
    min_dollar_volume: 0
```

For weak RS, set `strategy.rs_benchmark_return: 0.20`.

For high-volatility tight-stop, set `strategy.gap_atr_multiplier: 2.0` and keep `sell.hybrid.stop_loss_pct_max: 0.05`.

For gap rejection, set `strategy.hybrid.max_gap_pct: 0.03`.

For falling regime block, set:

```yaml
strategy:
  mode: sma_ema_hybrid
  min_history_bars: 30
  gap_atr_multiplier: 1.0
  use_sma200_filter: false
  use_market_regime_filter: true
  market_regime_unavailable_policy: block_market
  require_slope_up: false
  rs_lookback_days: 5
  rs_benchmark_ticker_kr: 069500
  hybrid:
    sma_trend_period: 20
    ema_short_period: 10
    ema_mid_period: 21
    rsi_period: 14
    rsi_zone_low: 40
    rsi_zone_high: 70
    rsi_oversold_low: 25
    rsi_oversold_high: 40
    pullback_max_bars: 7
    breakout_consolidation_min_bars: 4
    breakout_consolidation_max_bars: 12
    breakout_consolidation_max_range_pct: 0.10
    volume_lookback_days: 3
    max_gap_pct: 0.08
    use_sma60_filter: false
    sma60_period: 55
    kr_breakout_requires_confirmation: false
```

- [ ] **Step 3: Create market-data JSON inputs**

For each new case, create `watchlist.txt` with one candidate ticker. Use KR six-digit tickers for KR cases and explicit exchange suffixes for US cases:

```text
005930
```

or:

```text
AAPL.NAS
```

Create `adjusted_market_data.json` and `raw_market_data.json` with the same candle payload unless the case explicitly needs different raw reference prices. Each candidate ticker needs at least 30 completed rows because the config uses `min_history_bars: 30`. Falling-regime cases also need benchmark ticker `069500` in both JSON files with at least 201 completed rows so SMA200 can be computed.

Use these data-shape rules when building the candles:

- Strong breakout: last close above the previous consolidation high, last volume greater than the average of previous `volume_lookback_days`, EMA10 > EMA21 > SMA20, RSI < 60.
- Weak RS pullback: ready pullback candidate with `rs_return_value < rs_benchmark_return`, so the generated artifact has `quality_state: "B"` and `quality_reasons` contains `relative_strength_negative`.
- High-volatility tight stop: ATR-derived `gap_guard_pct_value > 0.05`, so `risk_alignment: "tight_stop_vs_volatility"` and `quality_state: "B"`.
- Gap rejection: latest open gaps more than `strategy.hybrid.max_gap_pct` from previous close and produces no candidate.
- Sideways consolidation: pre-breakout highs/lows stay within `breakout_consolidation_max_range_pct`, then latest close breaks above swing high with volume confirmation.
- Falling regime block: benchmark `069500` latest close is below SMA200 and candidate ticker appears in `screen_outs` as market-regime blocked.
- Pullback volume confirmation: previous pullback bars close at or below EMA short, latest close reclaims EMA short with rising volume and quality A.
- RSI oversold reversal: previous RSI in oversold band, latest RSI rebounds above 40, latest candle is bullish with lower shadow near EMA support.

The quickest safe implementation path is to start from `kr_hybrid_quality_order` candle shapes, copy a case, rename tickers, then adjust only the final 8-12 rows until the generated expected artifact shows the metadata outcome. Do not commit a case whose metadata says one outcome while `expected.buy.json` shows another outcome.

- [ ] **Step 4: Seed placeholder expected artifacts**

For each new fixture directory, create `expected.buy.json` as:

```json
{}
```

- [ ] **Step 5: Generate expected artifacts**

Run the updater on the new cases:

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/update_scan_replay_expected.py \
  tests/fixtures/replay_eod/scan/us_hybrid_strong_rs_breakout \
  tests/fixtures/replay_eod/scan/kr_hybrid_weak_rs_pullback \
  tests/fixtures/replay_eod/scan/us_hybrid_high_vol_tight_stop \
  tests/fixtures/replay_eod/scan/kr_hybrid_gap_rejected \
  tests/fixtures/replay_eod/scan/us_hybrid_sideways_consolidation \
  tests/fixtures/replay_eod/scan/kr_hybrid_falling_regime_blocked \
  tests/fixtures/replay_eod/scan/kr_hybrid_pullback_volume_confirmation \
  tests/fixtures/replay_eod/scan/us_hybrid_rsi_oversold_reversal
```

Expected: command exits 0 and writes each `expected.buy.json`.

- [ ] **Step 6: Review each generated expected artifact**

Run these focused checks with `rg`:

```bash
rg -n '"quality_state": "A"|"quality_state": "B"|"risk_alignment": "tight_stop_vs_volatility"|"Gap .*exceeds|Market regime filter blocked|rsi_oversold_reversal|trend_pullback_bounce|swing_high_breakout' tests/fixtures/replay_eod/scan
```

Expected:

- `us_hybrid_strong_rs_breakout` has a candidate with `quality_state: "A"`.
- `kr_hybrid_weak_rs_pullback` has a candidate with `quality_state: "B"` and `relative_strength_negative`.
- `us_hybrid_high_vol_tight_stop` has `risk_alignment: "tight_stop_vs_volatility"`.
- `kr_hybrid_gap_rejected` has no candidate and has a gap screen-out.
- `us_hybrid_sideways_consolidation` has `pattern: "swing_high_breakout"`.
- `kr_hybrid_falling_regime_blocked` has no candidate and has market-regime screen-out or summary block count.
- `kr_hybrid_pullback_volume_confirmation` has `pattern: "trend_pullback_bounce"`.
- `us_hybrid_rsi_oversold_reversal` has `pattern: "rsi_oversold_reversal"`.

- [ ] **Step 7: Run full replay tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
```

Expected: PASS, including `test_scan_replay_metadata_covers_active_swing_threshold_matrix`.

- [ ] **Step 8: Commit matrix fixtures**

```bash
git add tests/fixtures/replay_eod/scan tests/test_replay_eod_scan.py scripts/update_scan_replay_expected.py
git commit -m "test(replay): 스윙 임계값 리플레이 매트릭스 확장"
```

---

## Task 5: Strategy Documentation and Backlog Update

**Files:**
- Modify: `docs/STRATEGY.md`
- Modify: `TODOS.md`

**Interfaces:**
- Consumes: replay matrix implemented in Tasks 1-4.
- Produces: documented semantics separating replay regression coverage from historical performance backtesting.

- [ ] **Step 1: Update strategy documentation**

In `docs/STRATEGY.md`, add a subsection near the existing experiment/backlog or parameter-tuning discussion:

```markdown
### Replay coverage vs historical backtesting

`tests/fixtures/replay_eod/scan/*` contains deterministic scan replay fixtures
for active threshold behavior. These fixtures protect implementation semantics:
market/regime gating, RSI zones, consolidation windows, gap rejection,
volume confirmation, relative-strength quality, volatility-vs-stop alignment,
and report artifact shape.

Replay fixtures are not profitability evidence. They do not estimate win rate,
expected value, MFE/MAE, stop/target hit-rate, slippage, transaction cost, or
survivorship effects. Those claims require a separate historical backtest runner
with explicit data-source, universe, entry-timing, benchmark, and execution
assumptions.
```

- [ ] **Step 2: Update backlog file**

In `TODOS.md`, move the active replay coverage item into `Completed` with this text:

```markdown
- 2026-06-22: Expanded deterministic scan replay coverage with case metadata and a KR/US swing-threshold matrix covering rising/sideways/falling regimes, high-volatility tight-stop warnings, strong/weak relative strength, gap rejection, market-regime blocking, and major hybrid patterns. This validates rule semantics and report regression behavior, not parameter profitability.
```

Add a deferred follow-up:

```markdown
- 2026-06-22: Design and implement a historical swing backtest runner for profitability and parameter-sensitivity research, covering data source, sample period, universe, benchmark/regime alignment, survivorship assumptions, EOD entry timing, stop/target approximation, transaction costs, slippage, and output metrics. The 2026-06-22 replay matrix intentionally covers deterministic rule semantics only.
```

- [ ] **Step 3: Run documentation and replay verification**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
```

Expected: PASS.

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check tests/helpers/replay_eod.py tests/test_replay_eod_scan.py scripts/update_scan_replay_expected.py
```

Expected: PASS.

- [ ] **Step 4: Commit docs and backlog**

```bash
git add docs/STRATEGY.md TODOS.md
git commit -m "docs(strategy): 리플레이와 백테스트 범위 구분"
```

---

## Task 6: Final Verification

**Files:**
- No new edits unless verification exposes a defect.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified working tree ready for review.

- [ ] **Step 1: Run targeted replay suite**

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Python quality gate**

```bash
just quality
```

Expected: PASS.

If `just quality` fails because of missing local tools, run the fallback commands and record the reason:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_replay_eod_scan.py -q
UV_CACHE_DIR=.uv-cache uv run ruff check tests/helpers/replay_eod.py tests/test_replay_eod_scan.py scripts/update_scan_replay_expected.py
UV_CACHE_DIR=.uv-cache uv run ruff format --check tests/helpers/replay_eod.py tests/test_replay_eod_scan.py scripts/update_scan_replay_expected.py
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml
```

- [ ] **Step 3: Inspect final diff**

```bash
git status --short
git diff --stat
```

Expected: no unstaged changes after commits, or only intentional final edits ready to commit.

- [ ] **Step 4: Report outcome**

Summarize:

- fixture metadata contract added;
- coverage gate added;
- replay matrix cases added;
- docs/backlog updated;
- verification commands and results.
