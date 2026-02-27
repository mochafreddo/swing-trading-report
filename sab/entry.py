from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import Config, load_config
from .config_loader import ConfigLoadError
from .data.kis_client import KISClient, KISClientError, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError, PykrxNotInstalledError
from .holdings_loader import HoldingsLoadError
from .market_data_common import infer_env_from_base_url
from .report.entry_report import EntryReportRow, write_entry_report
from .report.run_meta import build_run_meta
from .tickers import (
    infer_market_from_ticker as infer_market_from_ticker_strict,
)
from .tickers import (
    parse_ticker,
    validate_strict_holdings_ticker,
    validate_strict_us_ticker,
)

logger = logging.getLogger(__name__)

_BUY_REPORT_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})(?:-(?P<dup>\d+))?\.buy\.json$"
)
_SUPPORTED_MODES = {"PRE_OPEN", "INTRADAY", "AFTER_CLOSE"}
_SUPPORTED_MARKETS = {"KR", "US"}
_SUPPORTED_PROVIDERS = {"kis", "pykrx"}
_DEFAULT_US_EXCHANGE = "NAS"


def _to_finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _to_positive_price(value: Any) -> float | None:
    parsed = _to_finite_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


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


def _parse_guard_percent_text(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("±", "").replace("%", "").strip()
    parsed = _to_finite_float(text)
    if parsed is None:
        return None
    return parsed / 100.0


def _extract_signal_close(candidate: dict[str, Any]) -> float | None:
    close_value = _to_finite_float(candidate.get("close_value"))
    if close_value is not None and close_value > 0:
        return close_value
    price_value = _to_finite_float(candidate.get("price_value"))
    if price_value is not None and price_value > 0:
        return price_value
    return None


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


def _resolve_strategy_mode(candidate: dict[str, Any]) -> str:
    mode = str(candidate.get("strategy_mode") or "ema_cross").strip().lower()
    return mode or "ema_cross"


def evaluate_entry_candidates(
    *,
    candidates: list[dict[str, Any]],
    price_lookup_fn: Callable[[str], float | None],
    gap_breach_action: str = "SKIP",
) -> tuple[list[EntryReportRow], list[str]]:
    rows: list[EntryReportRow] = []
    system_issues: list[str] = []

    for candidate in candidates:
        ticker = _normalize_ticker(candidate.get("ticker"))
        if not ticker:
            continue

        reasons: list[str] = []
        signal_close = _extract_signal_close(candidate)
        gap_guard_pct, gap_guard_up_price, gap_guard_down_price = _extract_gap_guard(
            candidate
        )
        strategy_mode = _resolve_strategy_mode(candidate)
        entry_state = str(candidate.get("entry_state") or "").strip().upper() or None
        pattern = str(candidate.get("pattern") or "").strip() or None

        if signal_close is None:
            issue = f"{ticker}: signal close unavailable"
            reasons.append("signal close unavailable")
            system_issues.append(issue)

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

        if gap_guard_pct is None:
            reasons.append("gap guard unavailable")
            system_issues.append(f"{ticker}: gap guard unavailable")
            action = "REVIEW"
        elif gap_pct is None:
            action = "REVIEW"
        elif abs(gap_pct) > gap_guard_pct:
            action = gap_breach_action
            reasons.append(
                "gap guard exceeded "
                f"({gap_pct * 100:.2f}% vs {gap_guard_pct * 100:.2f}%)"
            )
        elif strategy_mode == "sma_ema_hybrid":
            if entry_state == "READY":
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


def _infer_single_market(
    *,
    report: dict[str, Any],
    candidates: list[dict[str, Any]],
    market_override: str | None,
) -> str:
    if market_override is not None:
        return market_override

    eval_context = report.get("eval_context")
    if isinstance(eval_context, dict):
        market = str(eval_context.get("market") or "").strip().upper()
        if market in _SUPPORTED_MARKETS:
            return market

    report_market = str(report.get("market") or "").strip().upper()
    if report_market in _SUPPORTED_MARKETS:
        return report_market

    markets = {
        _infer_market_from_ticker(_normalize_ticker(c.get("ticker")))
        for c in candidates
    }
    markets.discard("")
    if len(markets) == 1:
        return next(iter(markets))
    raise ValueError(
        "Unable to infer a single market from buy report. "
        "Provide --market KR or --market US."
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


def _collect_candidate_eval_dates(report: dict[str, Any]) -> list[str]:
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        return []

    normalized_dates: list[str] = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        parsed = _parse_report_date(row.get("eval_date"))
        if parsed is not None:
            normalized_dates.append(parsed)

    return normalized_dates


def _resolve_candidate_eval_date(report: dict[str, Any]) -> str | None:
    normalized_dates = _collect_candidate_eval_dates(report)
    if not normalized_dates:
        return None

    counts = Counter(normalized_dates)
    top_count = max(counts.values())
    top_dates = [date for date, count in counts.items() if count == top_count]
    return max(top_dates)


def _resolve_signal_eval_date(*, report: dict[str, Any], market: str) -> str:
    direct = _parse_report_date(report.get("signal_eval_date"))
    if direct is not None:
        return direct

    candidate_eval_date = _resolve_candidate_eval_date(report)
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
) -> Callable[[str], float | None]:
    if provider == "pykrx":
        if mode != "AFTER_CLOSE":
            raise ValueError("pykrx provider is only allowed in AFTER_CLOSE mode")
        if market != "KR":
            raise ValueError("pykrx provider only supports KR market for entry")
        try:
            pykrx_client = PykrxClient(cache_dir=cfg.data_dir)
        except (PykrxNotInstalledError, PykrxClientError):
            return lambda _ticker: None

        def _lookup_pykrx(ticker: str) -> float | None:
            try:
                rows = pykrx_client.daily_candles(ticker, count=1, adjusted=False)
            except PykrxClientError:
                return None
            if not rows:
                return None
            return _to_finite_float(rows[-1].get("close"))

        return _lookup_pykrx

    # provider == "kis"
    if not (cfg.kis_app_key and cfg.kis_app_secret and cfg.kis_base_url):
        return lambda _ticker: None

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
    kis_client = KISClient(creds, cache_dir=cfg.data_dir, min_interval=min_interval)

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
            # Use only live traded price for KR PRE_OPEN/INTRADAY.
            # Fallback fields (prev close/open/high/low) can misclassify gap guard.
            live_price = _to_positive_price(detail.get("stck_prpr"))
            if live_price is not None:
                return live_price
            return None
        except KISClientError:
            return None

    return _lookup_kis


def _build_entry_summary(
    rows: list[EntryReportRow], system_issues: list[str]
) -> dict[str, Any]:
    counts = Counter(row.action for row in rows)
    return {
        "entry_count": len(rows),
        "action_counts": dict(sorted(counts.items())),
        "system_issue_count": len(system_issues),
    }


def _build_config_snapshot(cfg: Config, *, provider: str, mode: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "mode": mode,
        "strategy_mode": cfg.strategy_mode,
        "gap_atr_multiplier": cfg.gap_atr_multiplier,
        "min_history_bars": cfg.min_history_bars,
    }


def run_entry(
    *,
    buy_report_path: str | None,
    provider: str | None,
    mode: str | None,
    market: str | None,
    upload: bool = False,
) -> int:
    if upload:
        logger.warning(
            "--upload is reserved for a later storage/index integration step; "
            "writing local entry report only."
        )

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
    except (ConfigLoadError, HoldingsLoadError) as exc:
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
        logger.error("Buy report has no valid candidate rows")
        return 1

    try:
        _validate_candidate_tickers(candidates)
    except ValueError as exc:
        logger.error("Buy report ticker validation failed: %s", exc)
        return 1

    try:
        resolved_market = _infer_single_market(
            report=source_report,
            candidates=candidates,
            market_override=normalized_market,
        )
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    try:
        _validate_candidates_for_market(candidates=candidates, market=resolved_market)
    except ValueError as exc:
        logger.error("Buy report ticker validation failed: %s", exc)
        return 1

    if normalized_provider == "pykrx" and resolved_market != "KR":
        logger.error("pykrx provider only supports KR market for entry")
        return 1

    price_lookup_fn = _make_price_lookup(
        cfg=cfg,
        provider=normalized_provider,
        mode=normalized_mode,
        market=resolved_market,
    )
    rows, system_issues = evaluate_entry_candidates(
        candidates=candidates,
        price_lookup_fn=price_lookup_fn,
        gap_breach_action="SKIP",
    )
    rows.sort(key=lambda row: (row.action, row.ticker))

    signal_eval_date = _resolve_signal_eval_date(
        report=source_report,
        market=resolved_market,
    )
    candidate_eval_dates = sorted(set(_collect_candidate_eval_dates(source_report)))
    if len(candidate_eval_dates) > 1:
        max_preview = 5
        preview = ", ".join(candidate_eval_dates[:max_preview])
        if len(candidate_eval_dates) > max_preview:
            preview = f"{preview}, +{len(candidate_eval_dates) - max_preview} more"
        mixed_issue = f"Mixed candidate eval_date values: {preview}"
        system_issues.append(mixed_issue)

    artifact = {
        "provider": normalized_provider,
        "mode": normalized_mode,
        "market": resolved_market,
        "source_buy_report": os.path.basename(resolved_report_path),
        "signal_eval_date": signal_eval_date,
        "entry_session_date": _entry_session_date(resolved_market),
        "tickers": sorted({row.ticker for row in rows}),
        "summary": _build_entry_summary(rows, system_issues),
        "system_issues": system_issues,
        "eval_index_policy": "entry_snapshot:v1",
    }
    run_meta = build_run_meta(
        market=resolved_market,
        session_state=normalized_mode,
        eval_index_policy="entry_snapshot:v1",
        config_snapshot=_build_config_snapshot(
            cfg, provider=normalized_provider, mode=normalized_mode
        ),
    )

    out_path = write_entry_report(
        report_dir=cfg.report_dir,
        artifact=artifact,
        entries=rows,
        run_meta=run_meta,
    )
    logger.info("Entry report written to: %s", out_path)
    if system_issues:
        logger.warning(
            "Entry completed with system issues (%s rows)", len(system_issues)
        )
    return 0


__all__ = ["evaluate_entry_candidates", "run_entry", "_select_latest_buy_report"]
