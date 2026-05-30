from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import re
from collections import Counter, deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from .config import Config, load_config
from .config_loader import ConfigLoadError
from .data.kis_client import KISClient, KISClientError, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError, PykrxNotInstalledError
from .env_loader import env_flag
from .holdings_loader import (
    Holding,
    HoldingsData,
    HoldingSettings,
    HoldingsLoadError,
    load_holdings,
)
from .market_data_common import infer_env_from_base_url
from .report.entry_report import EntryReportRow, write_entry_report
from .report.run_meta import build_run_meta
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .tickers import (
    infer_market_from_ticker as infer_market_from_ticker_strict,
)
from .tickers import (
    parse_ticker,
    validate_strict_holdings_ticker,
    validate_strict_us_ticker,
)
from .utils.numeric import (
    to_finite_float as _to_finite_float,
)
from .utils.numeric import (
    to_positive_float as _to_positive_price,
)

logger = logging.getLogger(__name__)

_BUY_REPORT_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:-(?P<dup>\d+))?\.buy\.json$"
)
_SUPPORTED_MODES = {"PRE_OPEN", "INTRADAY", "AFTER_CLOSE"}
_SUPPORTED_MARKETS = {"KR", "US"}
_REPORT_LEVEL_MARKETS = {"KR", "US", "MIXED"}
_SUPPORTED_PROVIDERS = {"kis", "pykrx"}
_SUPPORTED_STRATEGY_MODES = {"ema_cross", "sma_ema_hybrid"}
_DEFAULT_US_EXCHANGE = "NAS"
_DEFAULT_ENTRY_FATAL_MISSING_PRICE_RATIO = 1.0
_PORTFOLIO_BLOCK_REASON_TOTAL = "portfolio max active holdings reached"
_PRE_OPEN_PRICE_SNAPSHOT_TIME_KEYS = (
    "stck_cntg_hour",
    "xymd",
    "stck_bsop_date",
    "bsop_date",
    "trade_date",
    "trade_time",
    "timestamp",
    "local_time",
    "quote_time",
    "as_of",
    "asof",
    "entry_snapshot_at",
)


def _has_pre_open_price_snapshot_time(detail: Mapping[str, Any]) -> bool:
    return any(
        str(detail.get(key) or "").strip() for key in _PRE_OPEN_PRICE_SNAPSHOT_TIME_KEYS
    )


def _normalize_ticker(ticker: Any) -> str:
    return str(ticker or "").strip().upper()


def _infer_market_from_ticker(ticker: str) -> str:
    return infer_market_from_ticker_strict(_normalize_ticker(ticker))


def _split_symbol_and_exchange(ticker: str) -> tuple[str, str]:
    normalized = _normalize_ticker(ticker)
    ticker_issue = validate_strict_holdings_ticker(normalized)
    if ticker_issue is not None:
        raise ValueError(f"{normalized}: {ticker_issue}")
    parsed = parse_ticker(normalized)
    if parsed.suffix is None:
        return parsed.symbol, _DEFAULT_US_EXCHANGE
    if parsed.exchange is None:
        raise ValueError(f"{normalized}: unsupported ticker suffix {parsed.suffix!r}")
    return parsed.symbol, parsed.exchange


def _validate_candidate_tickers(candidates: list[dict[str, Any]]) -> None:
    for idx, candidate in enumerate(candidates):
        ticker = _normalize_ticker(candidate.get("ticker"))
        if not ticker:
            raise ValueError(f"Buy report candidate[{idx}] missing ticker")
        ticker_issue = validate_strict_holdings_ticker(ticker)
        if ticker_issue is not None:
            raise ValueError(f"{ticker}: {ticker_issue}")


def _validate_candidates_for_market(
    *, candidates: list[dict[str, Any]], market: str
) -> None:
    for candidate in candidates:
        ticker = _normalize_ticker(candidate.get("ticker"))
        if not ticker:
            raise ValueError("Buy report candidate ticker must not be empty")
        if market == "US":
            ticker_issue = validate_strict_us_ticker(ticker)
            if ticker_issue is not None:
                raise ValueError(f"{ticker}: {ticker_issue}")
        inferred_market = _infer_market_from_ticker(ticker)
        if inferred_market != market:
            raise ValueError(
                f"{ticker}: ticker market {inferred_market} "
                f"mismatches entry market {market}"
            )


def _normalize_mode(mode: str | None) -> str:
    normalized = str(mode or "PRE_OPEN").strip().upper()
    if normalized not in _SUPPORTED_MODES:
        raise ValueError(f"mode must be one of {sorted(_SUPPORTED_MODES)}")
    return normalized


def _normalize_market(market: str | None) -> str | None:
    if market is None:
        return None
    normalized = str(market).strip().upper()
    if normalized not in _SUPPORTED_MARKETS:
        raise ValueError(f"market must be one of {sorted(_SUPPORTED_MARKETS)}")
    return normalized


def _normalize_provider(provider: str | None) -> str:
    normalized = str(provider or "kis").strip().lower()
    if normalized not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(_SUPPORTED_PROVIDERS)}")
    return normalized


def _is_entry_strict_config_mode() -> bool:
    return env_flag("GITHUB_ACTIONS") or env_flag("CI") or env_flag("SAB_CONFIG_STRICT")


def _resolve_entry_fatal_missing_price_ratio() -> float:
    raw = str(
        os.getenv(
            "ENTRY_FATAL_MISSING_PRICE_RATIO",
            str(_DEFAULT_ENTRY_FATAL_MISSING_PRICE_RATIO),
        )
        or ""
    ).strip()
    try:
        parsed = float(raw)
    except ValueError as exc:
        if _is_entry_strict_config_mode():
            raise ConfigLoadError(
                "Strict config parsing failed: environment variable "
                "'ENTRY_FATAL_MISSING_PRICE_RATIO' must be a number between "
                f"0.0 and 1.0, got {raw!r}."
            ) from exc
        logger.warning(
            "Invalid ENTRY_FATAL_MISSING_PRICE_RATIO=%r; fallback to %.2f",
            raw,
            _DEFAULT_ENTRY_FATAL_MISSING_PRICE_RATIO,
        )
        return _DEFAULT_ENTRY_FATAL_MISSING_PRICE_RATIO

    if not math.isfinite(parsed) or parsed < 0 or parsed > 1:
        if _is_entry_strict_config_mode():
            raise ConfigLoadError(
                "Strict config parsing failed: environment variable "
                "'ENTRY_FATAL_MISSING_PRICE_RATIO' must be between 0.0 and "
                f"1.0, got {raw!r}."
            )
        logger.warning(
            "ENTRY_FATAL_MISSING_PRICE_RATIO must be between 0.0 and 1.0; got %r. "
            "fallback to %.2f",
            raw,
            _DEFAULT_ENTRY_FATAL_MISSING_PRICE_RATIO,
        )
        return _DEFAULT_ENTRY_FATAL_MISSING_PRICE_RATIO

    return parsed


def _parse_guard_percent_text(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("±", "").replace("%", "").strip()
    parsed = _to_finite_float(text)
    if parsed is None:
        return None
    return parsed / 100.0


def _normalize_signal_basis(candidate: dict[str, Any]) -> str:
    return str(candidate.get("signal_price_basis") or "").strip().lower()


def _normalize_trigger_basis(candidate: dict[str, Any]) -> str:
    primary = str(candidate.get("entry_trigger_price_basis") or "").strip().lower()
    if primary:
        return primary
    return _normalize_signal_basis(candidate)


def _resolve_signal_close(
    candidate: dict[str, Any],
) -> tuple[float | None, str | None]:
    signal_basis = _normalize_signal_basis(candidate)
    candidate_eval_date = _parse_report_date(candidate.get("eval_date"))
    reference_eval_date = _parse_report_date(candidate.get("entry_reference_eval_date"))
    raw_reference_close = _to_positive_price(
        candidate.get("entry_reference_close_raw_value")
    )

    if raw_reference_close is not None:
        if candidate_eval_date is not None:
            if reference_eval_date is None:
                return None, "entry reference eval_date unavailable"
            if reference_eval_date != candidate_eval_date:
                return None, (
                    "entry reference eval_date mismatch "
                    f"({reference_eval_date} vs {candidate_eval_date})"
                )
        return raw_reference_close, None

    if signal_basis == "raw":
        close_value = _to_positive_price(candidate.get("close_value"))
        if close_value is not None:
            return close_value, None
        price_value = _to_positive_price(candidate.get("price_value"))
        if price_value is not None:
            return price_value, None
        return None, "signal close unavailable"

    if signal_basis:
        return None, "raw entry reference unavailable"
    return None, "signal price basis unavailable"


def _extract_signal_close(candidate: dict[str, Any]) -> float | None:
    close_value, _ = _resolve_signal_close(candidate)
    return close_value


def _signal_close_issue(candidate: dict[str, Any]) -> str:
    _, issue = _resolve_signal_close(candidate)
    return issue or ""


def _extract_gap_guard(
    candidate: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
    pct = _to_finite_float(candidate.get("gap_guard_pct_value"))
    up = _to_finite_float(candidate.get("gap_guard_up_price_value"))
    down = _to_finite_float(candidate.get("gap_guard_down_price_value"))
    if pct is None:
        pct = _parse_guard_percent_text(candidate.get("gap_guard_pct"))
    if up is None:
        up = _to_finite_float(candidate.get("gap_guard_up_price"))
    if down is None:
        down = _to_finite_float(candidate.get("gap_guard_down_price"))
    return pct, up, down


def _extract_adjusted_signal_close(candidate: dict[str, Any]) -> float | None:
    close_value = _to_positive_price(candidate.get("signal_close_adjusted_value"))
    if close_value is not None:
        return close_value

    signal_basis = _normalize_signal_basis(candidate)
    if signal_basis != "adjusted":
        return None

    close_value = _to_positive_price(candidate.get("close_value"))
    if close_value is not None:
        return close_value
    return _to_positive_price(candidate.get("price_value"))


def _extract_entry_trigger_guard(
    candidate: dict[str, Any],
    *,
    signal_close: float | None = None,
) -> tuple[float | None, str | None, str | None, str | None]:
    raw_trigger_price = candidate.get("entry_trigger_price_value")
    if raw_trigger_price is None or raw_trigger_price == "":
        raw_trigger_price = candidate.get("entry_trigger_price")
    if raw_trigger_price is None or raw_trigger_price == "":
        return None, None, None, None

    trigger_price = _to_positive_price(raw_trigger_price)
    if trigger_price is None:
        return None, None, None, "hybrid trigger guard invalid"

    operator = str(candidate.get("entry_trigger_operator") or "gte").strip().lower()
    label = str(candidate.get("entry_trigger_label") or "trigger").strip()
    resolved_label = label or "trigger"
    trigger_basis = _normalize_trigger_basis(candidate)

    if trigger_basis in {"", "raw"}:
        return trigger_price, operator, resolved_label, None
    if trigger_basis != "adjusted":
        return None, operator, resolved_label, "hybrid trigger guard basis invalid"

    adjusted_signal_close = _extract_adjusted_signal_close(candidate)
    if adjusted_signal_close is None or signal_close is None:
        return (
            None,
            operator,
            resolved_label,
            "hybrid trigger guard raw basis unavailable",
        )
    return (
        trigger_price * signal_close / adjusted_signal_close,
        operator,
        resolved_label,
        None,
    )


def _normalize_strategy_mode(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in _SUPPORTED_STRATEGY_MODES:
        return normalized
    return None


def _resolve_strategy_mode(
    candidate: dict[str, Any], *, default_strategy_mode: str | None = None
) -> str:
    candidate_mode = _normalize_strategy_mode(candidate.get("strategy_mode"))
    if candidate_mode is not None:
        return candidate_mode
    if default_strategy_mode is not None:
        return default_strategy_mode
    return "ema_cross"


def _resolve_report_strategy_mode(report: dict[str, Any]) -> str | None:
    direct = _normalize_strategy_mode(report.get("strategy_mode"))
    if direct is not None:
        return direct

    config_snapshot = report.get("config_snapshot")
    if isinstance(config_snapshot, dict):
        return _normalize_strategy_mode(config_snapshot.get("strategy_mode"))
    return None


def _resolve_report_gap_atr_multiplier(report: dict[str, Any]) -> float | None:
    config_snapshot = report.get("config_snapshot")
    if not isinstance(config_snapshot, dict):
        return None
    return _to_finite_float(config_snapshot.get("gap_atr_multiplier"))


def evaluate_entry_candidates(
    *,
    candidates: list[dict[str, Any]],
    price_lookup_fn: Callable[[str], float | None],
    gap_breach_action: str = "SKIP",
    default_strategy_mode: str | None = None,
    allow_missing_gap_guard: bool = False,
) -> tuple[list[EntryReportRow], list[str]]:
    rows: list[EntryReportRow] = []
    system_issues: list[str] = []
    resolved_default_strategy_mode = _normalize_strategy_mode(default_strategy_mode)

    for candidate in candidates:
        ticker = _normalize_ticker(candidate.get("ticker"))
        if not ticker:
            continue

        reasons: list[str] = []
        signal_close = _extract_signal_close(candidate)
        gap_guard_pct, gap_guard_up_price, gap_guard_down_price = _extract_gap_guard(
            candidate
        )
        strategy_mode = _resolve_strategy_mode(
            candidate,
            default_strategy_mode=resolved_default_strategy_mode,
        )
        entry_state = str(candidate.get("entry_state") or "").strip().upper() or None
        pattern = str(candidate.get("pattern") or "").strip() or None
        trigger_price, trigger_operator, trigger_label, trigger_issue = (
            _extract_entry_trigger_guard(candidate, signal_close=signal_close)
        )

        if signal_close is None:
            signal_issue = _signal_close_issue(candidate)
            issue = f"{ticker}: {signal_issue}"
            reasons.append(signal_issue)
            system_issues.append(issue)
        if trigger_issue is not None:
            reasons.append(trigger_issue)
            system_issues.append(f"{ticker}: {trigger_issue}")

        entry_price = price_lookup_fn(ticker)
        if entry_price is not None and entry_price <= 0:
            entry_price = None
        if entry_price is None:
            issue = f"{ticker}: price snapshot unavailable"
            reasons.append("price snapshot unavailable")
            system_issues.append(issue)

        gap_pct: float | None = None
        if signal_close is not None and signal_close > 0 and entry_price is not None:
            gap_pct = (entry_price - signal_close) / signal_close
        if signal_close is not None and signal_close > 0 and gap_guard_pct is not None:
            gap_guard_up_price = round(signal_close * (1.0 + gap_guard_pct), 10)
            gap_guard_down_price = round(signal_close * (1.0 - gap_guard_pct), 10)

        if gap_guard_pct is None and not allow_missing_gap_guard:
            reasons.append("gap guard unavailable")
            system_issues.append(f"{ticker}: gap guard unavailable")
            action = "REVIEW"
        elif gap_pct is None:
            action = "REVIEW"
        elif gap_guard_pct is not None and abs(gap_pct) > gap_guard_pct:
            action = gap_breach_action
            reasons.append(
                "gap guard exceeded "
                f"({gap_pct * 100:.2f}% vs {gap_guard_pct * 100:.2f}%)"
            )
        elif trigger_issue is not None:
            action = "REVIEW"
        elif strategy_mode == "sma_ema_hybrid":
            if entry_state == "READY":
                if trigger_price is None:
                    action = "ENTER"
                elif trigger_operator != "gte":
                    action = "REVIEW"
                    reasons.append(
                        "hybrid trigger guard unsupported "
                        f"({trigger_label} operator {trigger_operator})"
                    )
                elif entry_price is not None and entry_price < trigger_price:
                    action = "SKIP"
                    reasons.append(
                        "hybrid trigger guard failed "
                        f"({entry_price:.2f} < {trigger_label} {trigger_price:.2f})"
                    )
                else:
                    action = "ENTER"
            else:
                action = "REVIEW"
                reasons.append("hybrid entry_state requires manual review")
        else:
            action = "ENTER"

        if not reasons:
            reasons.append("entry conditions satisfied")

        rows.append(
            EntryReportRow(
                ticker=ticker,
                action=action,
                reasons=reasons,
                signal_close=signal_close,
                entry_price=entry_price,
                gap_pct=gap_pct,
                gap_guard_pct=gap_guard_pct,
                gap_guard_up_price=gap_guard_up_price,
                gap_guard_down_price=gap_guard_down_price,
                strategy_mode=strategy_mode,
                pattern=pattern,
                entry_state=entry_state,
            )
        )

    return rows, system_issues


def _select_latest_buy_report(report_dir: str) -> str:
    base = Path(report_dir)
    best: tuple[str, int, Path] | None = None
    for path in base.glob("*.buy.json"):
        match = _BUY_REPORT_PATTERN.match(path.name)
        if not match:
            continue
        date_key = match.group("date")
        duplicate = int(match.group("dup") or "0")
        key = (date_key, duplicate, path)
        if best is None or key > best:
            best = key
    if best is None:
        raise FileNotFoundError(f"No buy report files found in {report_dir}")
    return best[2].as_posix()


def _resolve_buy_report_path(*, report_dir: str, buy_report_path: str | None) -> str:
    if buy_report_path:
        return buy_report_path
    return _select_latest_buy_report(report_dir)


def _resolve_report_market_hint(report: dict[str, Any]) -> str | None:
    eval_context = report.get("eval_context")
    if isinstance(eval_context, dict):
        market = str(eval_context.get("market") or "").strip().upper()
        if market in _REPORT_LEVEL_MARKETS:
            return market

    report_market = str(report.get("market") or "").strip().upper()
    if report_market in _REPORT_LEVEL_MARKETS:
        return report_market
    return None


def _group_candidates_by_market(
    *,
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    market_override: str | None,
) -> dict[str, list[dict[str, Any]]]:
    grouped_candidates: dict[str, list[dict[str, Any]]] = {}

    for candidate in candidates:
        ticker = _normalize_ticker(candidate.get("ticker"))
        inferred_market = _infer_market_from_ticker(ticker)
        if market_override is not None and inferred_market != market_override:
            continue
        grouped_candidates.setdefault(inferred_market, []).append(candidate)

    if market_override is not None:
        selected = grouped_candidates.get(market_override, [])
        if not selected:
            raise ValueError(
                f"Buy report has no {market_override} candidates for entry evaluation"
            )
        _validate_candidates_for_market(candidates=selected, market=market_override)
        return {market_override: selected}

    for market, market_candidates in grouped_candidates.items():
        _validate_candidates_for_market(candidates=market_candidates, market=market)

    if grouped_candidates:
        return grouped_candidates

    report_market = _resolve_report_market_hint(report)
    if report_market in _SUPPORTED_MARKETS:
        raise ValueError(
            f"Buy report has no {report_market} candidates for entry evaluation"
        )
    raise ValueError(
        "Unable to infer candidate markets from buy report. "
        "Provide --market KR or --market US."
    )


def _empty_candidates_by_market(
    *,
    report: dict[str, Any],
    market_override: str | None,
) -> dict[str, list[dict[str, Any]]]:
    if market_override is not None:
        return {market_override: []}

    report_market = _resolve_report_market_hint(report)
    if report_market in _SUPPORTED_MARKETS:
        return {report_market: []}

    raise ValueError(
        "Buy report has no candidate rows. Provide --market KR or --market US."
    )


def _entry_session_date(market: str) -> str:
    zone = ZoneInfo("Asia/Seoul") if market == "KR" else ZoneInfo("America/New_York")
    return dt.datetime.now(zone).date().isoformat()


def _parse_iso_datetime(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed


def _parse_report_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        return None
    try:
        parsed = dt.datetime.strptime(normalized, "%Y%m%d").date()
    except ValueError:
        return None
    return parsed.isoformat()


def _collect_candidate_eval_dates(
    report: dict[str, Any],
    *,
    candidates: list[dict[str, Any]] | None = None,
) -> list[str]:
    candidate_rows = candidates
    if candidate_rows is None:
        raw_candidates = report.get("candidates")
        if not isinstance(raw_candidates, list):
            return []
        candidate_rows = [row for row in raw_candidates if isinstance(row, dict)]

    if not candidate_rows:
        return []

    normalized_dates: list[str] = []
    for row in candidate_rows:
        parsed = _parse_report_date(row.get("eval_date"))
        if parsed is not None:
            normalized_dates.append(parsed)

    return normalized_dates


def _resolve_candidate_eval_date(
    report: dict[str, Any],
    *,
    candidates: list[dict[str, Any]] | None = None,
) -> str | None:
    normalized_dates = _collect_candidate_eval_dates(report, candidates=candidates)
    if not normalized_dates:
        return None

    counts = Counter(normalized_dates)
    top_count = max(counts.values())
    top_dates = [date for date, count in counts.items() if count == top_count]
    return max(top_dates)


def _resolve_signal_eval_date(
    *,
    report: dict[str, Any],
    market: str,
    candidates: list[dict[str, Any]] | None = None,
) -> str:
    direct = _parse_report_date(report.get("signal_eval_date"))
    report_market = _resolve_report_market_hint(report)
    if direct is not None and (candidates is None or report_market == market):
        return direct

    candidate_eval_date = _resolve_candidate_eval_date(report, candidates=candidates)
    if candidate_eval_date is not None:
        return candidate_eval_date

    run_ts_utc = _parse_iso_datetime(report.get("run_ts_utc"))
    if run_ts_utc is not None:
        zone = (
            ZoneInfo("Asia/Seoul") if market == "KR" else ZoneInfo("America/New_York")
        )
        return run_ts_utc.astimezone(zone).date().isoformat()

    for key in ("report_date", "date"):
        fallback = _parse_report_date(report.get(key))
        if fallback is not None:
            return fallback

    return _entry_session_date(market)


def _make_price_lookup(
    *,
    cfg: Config,
    provider: str,
    mode: str,
    market: str,
) -> tuple[Callable[[str], float | None], list[str]]:
    provider_issues: list[str] = []

    if provider == "pykrx":
        if mode != "AFTER_CLOSE":
            raise ValueError("pykrx provider is only allowed in AFTER_CLOSE mode")
        if market != "KR":
            raise ValueError("pykrx provider only supports KR market for entry")
        try:
            pykrx_client = PykrxClient(cache_dir=cfg.data_dir)
        except PykrxNotInstalledError:
            provider_issues.append(
                "provider init failed (pykrx): pykrx package is not installed"
            )
            return (lambda _ticker: None), provider_issues
        except PykrxClientError as exc:
            provider_issues.append(f"provider init failed (pykrx): {exc}")
            return (lambda _ticker: None), provider_issues

        def _lookup_pykrx(ticker: str) -> float | None:
            try:
                rows = pykrx_client.daily_candles(ticker, count=1, adjusted=False)
            except PykrxClientError:
                return None
            if not rows:
                return None
            return _to_finite_float(rows[-1].get("close"))

        return _lookup_pykrx, provider_issues

    # provider == "kis"
    if not (cfg.kis_app_key and cfg.kis_app_secret and cfg.kis_base_url):
        provider_issues.append(
            "provider not configured (kis): missing KIS_APP_KEY/KIS_APP_SECRET/"
            "KIS_BASE_URL"
        )
        return (lambda _ticker: None), provider_issues

    creds = KISCredentials(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        base_url=cfg.kis_base_url,
        env=infer_env_from_base_url(cfg.kis_base_url),
    )
    min_interval = (
        max(0.0, cfg.kis_min_interval_ms / 1000.0)
        if cfg.kis_min_interval_ms is not None
        else None
    )
    try:
        kis_client = KISClient(creds, cache_dir=cfg.data_dir, min_interval=min_interval)
    except KISClientError as exc:
        provider_issues.append(f"provider init failed (kis): {exc}")
        return (lambda _ticker: None), provider_issues

    def _lookup_kis(ticker: str) -> float | None:
        try:
            if mode == "AFTER_CLOSE":
                if market == "US":
                    symbol, exchange = _split_symbol_and_exchange(ticker)
                    rows = kis_client.overseas_daily_candles(
                        symbol=symbol, exchange=exchange, count=1, adjusted=False
                    )
                else:
                    symbol, _ = _split_symbol_and_exchange(ticker)
                    rows = kis_client.daily_candles(symbol, count=1, adjusted=False)
                if not rows:
                    return None
                return _to_positive_price(rows[-1].get("close"))

            if market == "US":
                symbol, exchange = _split_symbol_and_exchange(ticker)
                detail = kis_client.overseas_price_detail(
                    symbol=symbol, exchange=exchange
                )
                if mode == "PRE_OPEN" and not _has_pre_open_price_snapshot_time(detail):
                    return None
                for key in (
                    "last",
                    "last_price",
                    "stck_prpr",
                    "ovrs_nmix_prpr",
                    "ovrs_prpr",
                ):
                    parsed = _to_positive_price(detail.get(key))
                    if parsed is not None:
                        return parsed
                return None

            symbol, _ = _split_symbol_and_exchange(ticker)
            detail = kis_client.domestic_price_detail(ticker=symbol)
            if mode == "PRE_OPEN" and not _has_pre_open_price_snapshot_time(detail):
                return None
            # Use only live traded price for KR PRE_OPEN/INTRADAY.
            # Fallback fields (prev close/open/high/low) can misclassify gap guard.
            live_price = _to_positive_price(detail.get("stck_prpr"))
            if live_price is not None:
                return live_price
            return None
        except KISClientError:
            return None

    return _lookup_kis, provider_issues


def _build_entry_summary(
    rows: list[EntryReportRow],
    system_issues: list[str],
    *,
    portfolio_blocked_by_market: dict[str, int] | None = None,
) -> dict[str, Any]:
    counts = Counter(row.action for row in rows)
    missing_entry_price_count = sum(1 for row in rows if row.entry_price is None)
    missing_entry_price_ratio = missing_entry_price_count / len(rows) if rows else 0.0
    portfolio_counts = {
        market: count
        for market, count in sorted((portfolio_blocked_by_market or {}).items())
        if count > 0
    }
    return {
        "entry_count": len(rows),
        "action_counts": dict(sorted(counts.items())),
        "system_issue_count": len(system_issues),
        "missing_entry_price_count": missing_entry_price_count,
        "missing_entry_price_ratio": missing_entry_price_ratio,
        "portfolio_blocked_count": sum(portfolio_counts.values()),
        "portfolio_blocked_by_market": portfolio_counts,
    }


def _is_missing_price_ratio_fatal(
    *,
    missing_price_ratio: float,
    fatal_missing_price_ratio: float,
) -> bool:
    if fatal_missing_price_ratio <= 0:
        return missing_price_ratio > 0
    return missing_price_ratio >= fatal_missing_price_ratio


def _build_config_snapshot(
    cfg: Config,
    *,
    provider: str,
    mode: str,
    effective_gap_atr_multiplier: float | None = None,
    source_report_gap_atr_multiplier: float | None = None,
) -> dict[str, Any]:
    portfolio = getattr(cfg, "portfolio", None)
    return {
        "provider": provider,
        "mode": mode,
        "strategy_mode": cfg.strategy_mode,
        "gap_atr_multiplier": cfg.gap_atr_multiplier,
        "effective_gap_atr_multiplier": effective_gap_atr_multiplier,
        "source_report_gap_atr_multiplier": source_report_gap_atr_multiplier,
        "min_history_bars": cfg.min_history_bars,
        "portfolio": {
            "max_active_holdings": getattr(portfolio, "max_active_holdings", None),
            "max_new_entries_per_market": {
                "KR": getattr(portfolio, "max_new_entries_kr", None),
                "US": getattr(portfolio, "max_new_entries_us", None),
            },
        },
    }


def _is_default_empty_holdings_data(value: Any) -> bool:
    return (
        isinstance(value, HoldingsData)
        and value.path is None
        and value.settings == HoldingSettings()
        and value.holdings == []
    )


def _resolve_entry_holdings(cfg: Config) -> HoldingsData:
    configured_holdings = getattr(cfg, "holdings", None)
    holdings_path = getattr(cfg, "holdings_path", None)

    if holdings_path and _is_default_empty_holdings_data(configured_holdings):
        return load_holdings(holdings_path)

    if isinstance(configured_holdings, HoldingsData):
        return configured_holdings
    if configured_holdings is not None and hasattr(configured_holdings, "holdings"):
        return cast(HoldingsData, configured_holdings)

    if holdings_path:
        return load_holdings(holdings_path)
    return HoldingsData(path=None, settings=HoldingSettings(), holdings=[])


def _is_active_holding(holding: Holding | Any) -> bool:
    quantity = _to_finite_float(getattr(holding, "quantity", None))
    return quantity is not None and quantity > 0


def _canonical_ticker(ticker: Any) -> str:
    normalized = _normalize_ticker(ticker)
    if not normalized:
        return ""
    return parse_ticker(normalized).ticker


def _build_active_holding_state(
    holdings_data: HoldingsData | Any,
) -> tuple[int, set[str]]:
    active_total = 0
    active_tickers: set[str] = set()
    for holding in getattr(holdings_data, "holdings", []):
        if not _is_active_holding(holding):
            continue
        active_total += 1
        active_tickers.add(_canonical_ticker(getattr(holding, "ticker", None)))
    return active_total, active_tickers


def _apply_portfolio_guards(
    rows: list[EntryReportRow],
    *,
    active_total: int,
    active_tickers: set[str],
    max_active_holdings: int | None,
    max_new_entries_per_market: dict[str, int | None],
) -> dict[str, int]:
    accepted_new_entries_by_market = {"KR": 0, "US": 0}
    blocked_by_market = {"KR": 0, "US": 0}
    current_active_total = active_total

    for row in rows:
        if row.action != "ENTER":
            continue

        if _canonical_ticker(row.ticker) in active_tickers:
            continue

        market = _infer_market_from_ticker(row.ticker)
        if (
            max_active_holdings is not None
            and current_active_total >= max_active_holdings
        ):
            row.action = "SKIP"
            row.reasons.append(_PORTFOLIO_BLOCK_REASON_TOTAL)
            blocked_by_market[market] = blocked_by_market.get(market, 0) + 1
            continue

        market_cap = max_new_entries_per_market.get(market)
        accepted_market_entries = accepted_new_entries_by_market.get(market, 0)
        if market_cap is not None and accepted_market_entries >= market_cap:
            row.action = "SKIP"
            row.reasons.append(f"portfolio market cap reached ({market})")
            blocked_by_market[market] = blocked_by_market.get(market, 0) + 1
            continue

        accepted_new_entries_by_market[market] = (
            accepted_new_entries_by_market.get(market, 0) + 1
        )
        current_active_total += 1

    return blocked_by_market


def _ordered_entry_rows(
    *,
    source_candidates: list[dict[str, Any]],
    market_rows_by_market: dict[str, list[EntryReportRow]],
    market_override: str | None,
) -> list[EntryReportRow]:
    queued_rows_by_market = {
        market: deque(rows) for market, rows in market_rows_by_market.items()
    }
    ordered_rows: list[EntryReportRow] = []

    for candidate in source_candidates:
        market = _infer_market_from_ticker(_normalize_ticker(candidate.get("ticker")))
        if market_override is not None and market != market_override:
            continue
        market_queue = queued_rows_by_market.get(market)
        if not market_queue:
            continue
        ordered_rows.append(market_queue.popleft())

    for market_queue in queued_rows_by_market.values():
        ordered_rows.extend(list(market_queue))

    return ordered_rows


def run_entry(
    *,
    buy_report_path: str | None,
    provider: str | None,
    mode: str | None,
    market: str | None,
    upload: bool = False,
    report_path_callback: Callable[[str], None] | None = None,
) -> int:
    try:
        normalized_provider = _normalize_provider(provider)
        normalized_mode = _normalize_mode(mode)
        normalized_market = _normalize_market(market)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    if normalized_provider == "pykrx" and normalized_mode != "AFTER_CLOSE":
        logger.error("pykrx provider is only allowed in AFTER_CLOSE mode")
        return 1

    try:
        cfg = load_config(provider_override=normalized_provider)
    except ConfigLoadError as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1
    try:
        holdings_data = _resolve_entry_holdings(cfg)
    except HoldingsLoadError as exc:
        logger.error("Holdings loading failed: %s", exc)
        return 1
    try:
        fatal_missing_price_ratio = _resolve_entry_fatal_missing_price_ratio()
    except ConfigLoadError as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    try:
        resolved_report_path = _resolve_buy_report_path(
            report_dir=cfg.report_dir,
            buy_report_path=buy_report_path,
        )
        with open(resolved_report_path, encoding="utf-8") as fp:
            source_report = json.load(fp)
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to load buy report: %s", exc)
        return 1

    candidates_raw = source_report.get("candidates")
    if not isinstance(candidates_raw, list):
        logger.error("Buy report is missing candidates[]")
        return 1

    candidates = [item for item in candidates_raw if isinstance(item, dict)]
    if not candidates:
        if candidates_raw:
            logger.error("Buy report has no valid candidate rows")
            return 1
        logger.info("Buy report has no candidate rows; writing empty entry report")

    if candidates:
        try:
            _validate_candidate_tickers(candidates)
        except ValueError as exc:
            logger.error("Buy report ticker validation failed: %s", exc)
            return 1

    try:
        if candidates:
            candidates_by_market = _group_candidates_by_market(
                report=source_report,
                candidates=candidates,
                market_override=normalized_market,
            )
        else:
            candidates_by_market = _empty_candidates_by_market(
                report=source_report,
                market_override=normalized_market,
            )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    resolved_markets = sorted(candidates_by_market)
    if normalized_provider == "pykrx" and resolved_markets != ["KR"]:
        logger.error("pykrx provider only supports KR market for entry")
        return 1

    rows: list[EntryReportRow] = []
    system_issues: list[str] = []
    market_rows_by_market: dict[str, list[EntryReportRow]] = {}
    report_strategy_mode = _resolve_report_strategy_mode(source_report)
    source_gap_atr_multiplier = _resolve_report_gap_atr_multiplier(source_report)
    effective_gap_atr_multiplier = source_gap_atr_multiplier
    if effective_gap_atr_multiplier is None:
        effective_gap_atr_multiplier = _to_finite_float(
            getattr(cfg, "gap_atr_multiplier", None)
        )
    allow_missing_gap_guard = (
        effective_gap_atr_multiplier is not None and effective_gap_atr_multiplier <= 0
    )
    for candidate_market in resolved_markets:
        market_candidates = candidates_by_market[candidate_market]
        if not market_candidates:
            market_rows_by_market[candidate_market] = []
            continue
        price_lookup_fn, provider_issues = _make_price_lookup(
            cfg=cfg,
            provider=normalized_provider,
            mode=normalized_mode,
            market=candidate_market,
        )
        market_rows, candidate_system_issues = evaluate_entry_candidates(
            candidates=market_candidates,
            price_lookup_fn=price_lookup_fn,
            gap_breach_action="SKIP",
            default_strategy_mode=report_strategy_mode,
            allow_missing_gap_guard=allow_missing_gap_guard,
        )
        market_rows_by_market[candidate_market] = market_rows
        system_issues.extend(provider_issues)
        system_issues.extend(candidate_system_issues)
    rows = _ordered_entry_rows(
        source_candidates=candidates,
        market_rows_by_market=market_rows_by_market,
        market_override=normalized_market,
    )
    system_issues = list(dict.fromkeys(system_issues))

    active_total, active_tickers = _build_active_holding_state(holdings_data)
    portfolio_settings = getattr(cfg, "portfolio", None)
    portfolio_blocked_by_market = _apply_portfolio_guards(
        rows,
        active_total=active_total,
        active_tickers=active_tickers,
        max_active_holdings=getattr(portfolio_settings, "max_active_holdings", None),
        max_new_entries_per_market={
            "KR": getattr(portfolio_settings, "max_new_entries_kr", None),
            "US": getattr(portfolio_settings, "max_new_entries_us", None),
        },
    )

    if len(resolved_markets) == 1:
        artifact_market = resolved_markets[0]
        artifact_markets = None
        signal_eval_date = _resolve_signal_eval_date(
            report=source_report,
            market=artifact_market,
            candidates=candidates_by_market[artifact_market],
        )
        entry_session_date = _entry_session_date(artifact_market)
        signal_eval_date_by_market = None
        entry_session_date_by_market = None
    else:
        artifact_market = "MIXED"
        artifact_markets = resolved_markets
        signal_eval_date = None
        entry_session_date = None
        signal_eval_date_by_market = {
            market: _resolve_signal_eval_date(
                report=source_report,
                market=market,
                candidates=candidates_by_market[market],
            )
            for market in resolved_markets
        }
        entry_session_date_by_market = {
            market: _entry_session_date(market) for market in resolved_markets
        }

    for candidate_market in resolved_markets:
        candidate_eval_dates = sorted(
            set(
                _collect_candidate_eval_dates(
                    source_report,
                    candidates=candidates_by_market[candidate_market],
                )
            )
        )
        if len(candidate_eval_dates) <= 1:
            continue
        max_preview = 5
        preview = ", ".join(candidate_eval_dates[:max_preview])
        if len(candidate_eval_dates) > max_preview:
            preview = f"{preview}, +{len(candidate_eval_dates) - max_preview} more"
        if len(resolved_markets) == 1:
            mixed_issue = f"Mixed candidate eval_date values: {preview}"
        else:
            mixed_issue = (
                f"Mixed candidate eval_date values for {candidate_market}: {preview}"
            )
        system_issues.append(mixed_issue)
    system_issues = list(dict.fromkeys(system_issues))

    entry_summary = _build_entry_summary(
        rows,
        system_issues,
        portfolio_blocked_by_market=portfolio_blocked_by_market,
    )
    artifact = {
        "provider": normalized_provider,
        "mode": normalized_mode,
        "market": artifact_market,
        "source_buy_report": os.path.basename(resolved_report_path),
        "signal_eval_date": signal_eval_date,
        "entry_session_date": entry_session_date,
        "tickers": sorted({row.ticker for row in rows}),
        "summary": entry_summary,
        "system_issues": system_issues,
        "eval_index_policy": "entry_snapshot:v1",
    }
    if artifact_markets is not None:
        artifact["markets"] = artifact_markets
    if signal_eval_date_by_market is not None:
        artifact["signal_eval_date_by_market"] = signal_eval_date_by_market
    if entry_session_date_by_market is not None:
        artifact["entry_session_date_by_market"] = entry_session_date_by_market
    run_meta = build_run_meta(
        market=artifact_market,
        markets=artifact_markets,
        session_state=normalized_mode,
        eval_index_policy="entry_snapshot:v1",
        config_snapshot=_build_config_snapshot(
            cfg,
            provider=normalized_provider,
            mode=normalized_mode,
            effective_gap_atr_multiplier=effective_gap_atr_multiplier,
            source_report_gap_atr_multiplier=source_gap_atr_multiplier,
        ),
    )
    artifact_dates = [
        value
        for value in [
            entry_session_date,
            *(entry_session_date_by_market or {}).values(),
        ]
        if value
    ]

    out_path = write_entry_report(
        report_dir=cfg.report_dir,
        artifact=artifact,
        entries=rows,
        run_meta=run_meta,
        artifact_date=max(artifact_dates) if artifact_dates else None,
    )
    missing_price_ratio = float(entry_summary["missing_entry_price_ratio"])
    logger.info(
        "Entry evaluation summary: candidates=%s, missing_price_ratio=%.4f, "
        "fatal_threshold=%.4f, system_issue_count=%s",
        len(rows),
        missing_price_ratio,
        fatal_missing_price_ratio,
        len(system_issues),
    )
    logger.info("Entry report written to: %s", out_path)
    if report_path_callback is not None:
        report_path_callback(out_path)
    if system_issues:
        logger.warning(
            "Entry completed with system issues (%s rows)", len(system_issues)
        )
    if _is_missing_price_ratio_fatal(
        missing_price_ratio=missing_price_ratio,
        fatal_missing_price_ratio=fatal_missing_price_ratio,
    ):
        logger.error(
            "Entry failed: missing_price_ratio %.4f exceeded threshold %.4f",
            missing_price_ratio,
            fatal_missing_price_ratio,
        )
        return 1
    try:
        uploaded_key = maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="entry",
            logger=logger,
            force=upload,
        )
    except SupabaseStorageError as exc:
        logger.error("Supabase report upload failed: %s", exc)
        return 1
    else:
        if uploaded_key:
            logger.info("Entry report uploaded to Supabase: %s", uploaded_key)
    return 0


__all__ = ["_select_latest_buy_report", "evaluate_entry_candidates", "run_entry"]
