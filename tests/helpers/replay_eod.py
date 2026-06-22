from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
import sab.config as sab_config
import sab.scan as scan
import yaml  # type: ignore[import-untyped]
from sab.tickers import infer_currency_from_ticker

SCAN_REPLAY_REQUIRED_FILES = (
    "case.yaml",
    "config.yaml",
    "watchlist.txt",
    "adjusted_market_data.json",
    "raw_market_data.json",
    "expected.buy.json",
)
_NORMALIZED_SCAN_ARTIFACT_KEYS = (
    "report_date",
    "eval_context",
    "config_snapshot",
    "summary",
    "tickers",
    "candidates",
    "issues",
    "system_issues",
    "screen_outs",
)
_FIXED_SESSION_STATE = "AFTER_CLOSE"
_CONFIG_ENV_KEYS = {name for name, _ in sab_config._ENV_YAML_CONFLICT_BINDINGS}
_CLEAR_ENV_KEYS = _CONFIG_ENV_KEYS | {
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "SAB_CONFIG",
    "SAB_CONFIG_STRICT",
}


class ReplayScanCaseError(ValueError):
    """Raised when a replay fixture case violates the local contract."""


_REPLAY_CASE_SCHEMA = "sab.replay.scan-case.v1"
_REPLAY_CASE_MARKETS = frozenset({"KR", "US", "MIXED"})
_REPLAY_CASE_STRATEGY_MODES = frozenset({"ema_cross", "sma_ema_hybrid"})
_REPLAY_CASE_REGIMES = frozenset({"rising", "sideways", "falling", "not_applicable"})
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
_REPLAY_CASE_VOLATILITY = frozenset({"normal", "high", "unknown", "not_applicable"})
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


@dataclass(frozen=True)
class ReplayScanResult:
    case_dir: Path
    workspace_dir: Path
    report_path: Path
    exit_code: int
    normalized_actual: dict[str, Any]
    expected: dict[str, Any]


def iter_scan_replay_case_dirs(root: Path) -> list[Path]:
    return sorted(path for path in root.iterdir() if path.is_dir())


def _load_case_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ReplayScanCaseError(
            f"failed to load replay case metadata '{path}': {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ReplayScanCaseError(f"replay case metadata '{path}' must be a mapping")
    return cast(dict[str, Any], loaded)


def _metadata_error(case_dir: Path, field: str, message: str) -> ReplayScanCaseError:
    return ReplayScanCaseError(
        f"invalid replay case metadata {field}: {message} ({case_dir})"
    )


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


def validate_scan_replay_case_dir(case_dir: Path) -> None:
    entries = {entry.name for entry in case_dir.iterdir()}
    required = set(SCAN_REPLAY_REQUIRED_FILES)
    missing = sorted(required - entries)
    unexpected = sorted(entries - required)
    if missing:
        raise ReplayScanCaseError(
            f"missing required replay case files: {', '.join(missing)} ({case_dir})"
        )
    if unexpected:
        raise ReplayScanCaseError(
            f"unexpected replay case files: {', '.join(unexpected)} ({case_dir})"
        )


def prepare_scan_replay_workspace(case_dir: Path, tmp_path: Path) -> Path:
    validate_scan_replay_case_dir(case_dir)
    workspace_dir = tmp_path / case_dir.name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for name in SCAN_REPLAY_REQUIRED_FILES:
        shutil.copy2(case_dir / name, workspace_dir / name)
    return workspace_dir


def load_scan_market_data(path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayScanCaseError(
            f"failed to load market data fixture '{path}': {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ReplayScanCaseError(
            f"market data fixture '{path}' must be a mapping of ticker -> candles"
        )

    normalized: dict[str, list[dict[str, Any]]] = {}
    for raw_ticker, raw_rows in loaded.items():
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            raise ReplayScanCaseError(f"fixture '{path}' contains an empty ticker key")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise ReplayScanCaseError(
                f"fixture '{path}' ticker '{ticker}' must contain a non-empty candle list"
            )
        rows: list[dict[str, Any]] = []
        for index, raw_row in enumerate(raw_rows):
            if not isinstance(raw_row, dict):
                raise ReplayScanCaseError(
                    f"fixture '{path}' ticker '{ticker}' row {index} must be an object"
                )
            rows.append(dict(raw_row))
        normalized[ticker] = rows
    return normalized


def load_expected_scan_artifact(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayScanCaseError(
            f"failed to load expected replay artifact '{path}': {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ReplayScanCaseError(
            f"expected replay artifact '{path}' must be a JSON object"
        )
    return loaded


def normalize_scan_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: payload.get(key) for key in _NORMALIZED_SCAN_ARTIFACT_KEYS}
    return cast(
        dict[str, Any],
        json.loads(json.dumps(normalized, ensure_ascii=False)),
    )


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
    return [
        load_scan_replay_case_metadata(case_dir)
        for case_dir in iter_scan_replay_case_dirs(root)
    ]


def _normalize_date_key(value: object | None) -> str | None:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    return text


def _latest_dates_from_market_data(
    market_data: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    latest_dates: dict[str, str] = {}
    for ticker, rows in market_data.items():
        dates = [
            normalized
            for normalized in (_normalize_date_key(row.get("date")) for row in rows)
            if normalized is not None
        ]
        if not dates:
            raise ReplayScanCaseError(
                f"fixture market data for '{ticker}' must contain at least one valid date"
            )
        latest_dates[ticker] = max(dates)
    return latest_dates


def _deep_copy_json_compatible(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def run_scan_replay_case(
    case_dir: Path,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str | None = None,
) -> ReplayScanResult:
    workspace_dir = prepare_scan_replay_workspace(case_dir, tmp_path)
    if config_text is not None:
        (workspace_dir / "config.yaml").write_text(config_text, encoding="utf-8")
    adjusted_market_data = load_scan_market_data(
        workspace_dir / "adjusted_market_data.json"
    )
    raw_market_data = load_scan_market_data(workspace_dir / "raw_market_data.json")
    expected = load_expected_scan_artifact(workspace_dir / "expected.buy.json")

    for key in _CLEAR_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SAB_CONFIG", (workspace_dir / "config.yaml").as_posix())
    monkeypatch.chdir(workspace_dir)

    def _fixed_session_state_map(
        *, markets: list[str] | None, **_: Any
    ) -> dict[str, str]:
        return {
            str(market).strip().upper(): _FIXED_SESSION_STATE
            for market in (markets or [])
            if str(market).strip()
        }

    class FixtureBackedScanMarketData:
        def __init__(self, raw_by_ticker: dict[str, list[dict[str, Any]]]) -> None:
            self._raw_by_ticker = raw_by_ticker

        def collect_entry_reference_raw_market_data(
            self,
            runtime_arg: Any,
            *,
            tickers: list[str],
            target_bars: int = 10,
        ) -> None:
            del target_bars
            for ticker in dict.fromkeys(
                str(raw_ticker or "").strip().upper() for raw_ticker in tickers
            ):
                rows = self._raw_by_ticker.get(ticker)
                if rows is None:
                    continue
                runtime_arg.raw_market_data[ticker] = _deep_copy_json_compatible(rows)

    fixture_service = FixtureBackedScanMarketData(raw_market_data)

    def _collect_scan_runtime(runtime: Any, **_: Any) -> FixtureBackedScanMarketData:
        runtime.market_data = _deep_copy_json_compatible(adjusted_market_data)
        runtime.raw_market_data = {}
        runtime.ticker_data_source = dict.fromkeys(adjusted_market_data, "fixture")
        runtime.latest_dates = _latest_dates_from_market_data(adjusted_market_data)
        runtime.ticker_currency = {
            ticker: infer_currency_from_ticker(ticker) for ticker in runtime.tickers
        }
        runtime.cache_hint = "replay-fixture"
        return fixture_service

    def _skip_upload(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(scan, "ScanMarketData", FixtureBackedScanMarketData)
    monkeypatch.setattr(scan, "_collect_scan_runtime", _collect_scan_runtime)
    monkeypatch.setattr(scan, "maybe_upload_report_artifact", _skip_upload)
    monkeypatch.setattr(
        scan.scan_evaluation,
        "resolve_run_session_state_map",
        _fixed_session_state_map,
    )
    monkeypatch.setattr(
        scan.scan_evaluation,
        "resolve_run_session_state",
        lambda **_: _FIXED_SESSION_STATE,
    )

    exit_code = scan.run_scan(
        limit=None,
        watchlist_path=None,
        provider=None,
        screener_limit=None,
        universe="watchlist",
    )

    report_paths = sorted((workspace_dir / "reports").glob("*.buy.json"))
    if len(report_paths) != 1:
        raise ReplayScanCaseError(
            f"expected exactly one buy report in '{workspace_dir / 'reports'}', "
            f"found {len(report_paths)}"
        )

    try:
        payload = json.loads(report_paths[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayScanCaseError(
            f"failed to load generated replay report '{report_paths[0]}': {exc}"
        ) from exc

    return ReplayScanResult(
        case_dir=case_dir,
        workspace_dir=workspace_dir,
        report_path=report_paths[0],
        exit_code=exit_code,
        normalized_actual=normalize_scan_artifact(payload),
        expected=expected,
    )
