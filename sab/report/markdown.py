from __future__ import annotations

import os
from collections.abc import Iterable

from ..utils.atomic_io import advisory_path_lock, atomic_write_text
from .time_label import resolve_report_timestamp


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _next_report_path(report_dir: str, date: str, report_type: str) -> str:
    suffix = f".{report_type}.md" if report_type else ".md"
    base = os.path.join(report_dir, f"{date}{suffix}")
    if not os.path.exists(base):
        return base
    i = 1
    while True:
        p = os.path.join(report_dir, f"{date}-{i}{suffix}")
        if not os.path.exists(p):
            return p
        i += 1


REPORT_TITLES: dict[str, str] = {
    "buy": "Swing Screening",
    "sell": "Holdings Sell Review",
    "entry": "Entry Check",
}


def write_report(
    *,
    report_dir: str,
    provider: str,
    universe_count: int,
    candidates: Iterable[dict],
    failures: Iterable[str] | None = None,
    cache_hint: str | None = None,
    report_type: str = "buy",
    strategy_mode: str | None = None,
) -> str:
    _ensure_dir(report_dir)
    today, now_str, tz_label = resolve_report_timestamp()

    cand_list = list(candidates)
    failures = list(failures or [])

    title = REPORT_TITLES.get(report_type, "Swing Report")
    lines: list[str] = []
    lines.append(f"# {title} — {today}")
    lines.append(f"- Run at: {now_str} {tz_label}")
    cache_note = f" (cache: {cache_hint})" if cache_hint else ""
    lines.append(f"- Provider: {provider}{cache_note}")
    if strategy_mode and report_type == "buy":
        mode_label = strategy_mode
        if strategy_mode == "sma_ema_hybrid":
            mode_label = "sma_ema_hybrid (SMA20 + EMA10/21)"
        lines.append(f"- Strategy: {mode_label}")
    lines.append(f"- Universe: {universe_count} tickers, Candidates: {len(cand_list)}")
    if failures:
        lines.append(f"- Notes: {len(failures)} issue(s) logged (see Appendix)")
    lines.append("")

    if cand_list:
        lines.append("## Candidates")
        if strategy_mode == "sma_ema_hybrid" and report_type == "buy":
            lines.append(
                "| Ticker | Name | Price | SMA20 | EMA10 | EMA21 | RSI14 | Vol(5d) | Pattern | State |"
            )
            lines.append(
                "|--------|------|------:|------:|------:|------:|------:|--------:|---------|------:|"
            )
            for c in cand_list:
                lines.append(
                    f"| {c.get('ticker', '-')} | {c.get('name', '-')} | {c.get('price', '-')} | "
                    f"{c.get('sma20', '-')} | {c.get('ema10', '-')} | {c.get('ema21', '-')} | "
                    f"{c.get('rsi14', '-')} | {c.get('avg_dollar_volume', '-')} | "
                    f"{c.get('pattern', '-')} | {c.get('entry_state', '-')} |"
                )
        else:
            lines.append(
                "| Ticker | Name | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap | Score |"
            )
            lines.append(
                "|--------|------|------:|------:|------:|------:|------:|-----:|------:|"
            )
            for c in cand_list:
                lines.append(
                    f"| {c.get('ticker', '-')} | {c.get('name', '-')} | {c.get('price', '-')} | "
                    f"{c.get('ema20', '-')} | {c.get('ema50', '-')} | {c.get('rsi14', '-')} | "
                    f"{c.get('atr14', '-')} | {c.get('gap', '-')} | {c.get('score', '-')} |"
                )
        lines.append("")

        for c in cand_list:
            lines.append(
                f"## [매수 후보] {c.get('ticker', '-')} — {c.get('name', '-')}"
            )
            lines.append(
                f"- Price: {c.get('price', '-')} (d/d {c.get('pct_change', '-')}) H: {c.get('high', '-')} L: {c.get('low', '-')}"
            )
            currency = c.get("currency")
            if currency and currency.upper() != "KRW":
                fx_note = c.get("fx_note")
                converted = c.get("price_converted")
                extra = fx_note or ""
                if converted:
                    extra = (
                        extra + ", " if extra else ""
                    ) + f"가격 ≈ ₩{converted:,.0f}"
                label = f"- Currency: {currency}"
                if extra:
                    label += f" ({extra})"
                lines.append(label)
            status = c.get("market_status")
            if status:
                lines.append(f"- Market: {status}")
            if strategy_mode == "sma_ema_hybrid" and report_type == "buy":
                trend_line = (
                    f"- Trend: SMA20({c.get('sma20', '-')}) / "
                    f"EMA10({c.get('ema10', '-')}) / EMA21({c.get('ema21', '-')})"
                )
            else:
                trend_line = f"- Trend: EMA20({c.get('ema20', '-')}) vs EMA50({c.get('ema50', '-')})"
                if c.get("sma200") and c.get("sma200") != "-":
                    trend_line += f", SMA200({c.get('sma200', '-')})"
                if c.get("trend_pass"):
                    trend_line += f" (trend pass: {c.get('trend_pass')})"
            lines.append(trend_line)
            lines.append(f"- Momentum: RSI14={c.get('rsi14', '-')}")
            if strategy_mode != "sma_ema_hybrid" or report_type != "buy":
                lines.append(f"- Volatility: ATR14={c.get('atr14', '-')}")
                lines.append(
                    f"- Gap: {c.get('gap', '-')} (threshold {c.get('gap_threshold', '-')})"
                )
            lines.append(f"- Liquidity: Avg $Vol {c.get('avg_dollar_volume', '-')}")

            if strategy_mode == "sma_ema_hybrid" and report_type == "buy":
                pattern = c.get("pattern")
                if pattern:
                    entry_state = c.get("entry_state")
                    state_label = f" ({entry_state})" if entry_state else ""
                    lines.append(f"- Pattern: {pattern}{state_label}")
                reasons = c.get("pattern_reasons")
                if reasons:
                    lines.append(f"- Pattern notes: {reasons}")
                entry_state_reason = c.get("entry_state_reason")
                if entry_state_reason:
                    lines.append(f"- Entry guidance: {entry_state_reason}")
                checklist: list[str] = []
                if c.get("sma20") not in (None, "-"):
                    checklist.append("Close>SMA20?")
                if c.get("ema10") not in (None, "-") and c.get("ema21") not in (
                    None,
                    "-",
                ):
                    checklist.append("EMA10≥EMA21?")
                lines.append(f"- Checklist: {', '.join(checklist)}")
                if c.get("atr14"):
                    lines.append(f"- ATR14: {c.get('atr14')}")
                gap_guard_pct = c.get("gap_guard_pct")
                if gap_guard_pct and gap_guard_pct != "-":
                    lines.append(
                        f"- Gap guard: avoid if open > {c.get('gap_guard_up_price', '-')} "
                        f"({gap_guard_pct}) or < {c.get('gap_guard_down_price', '-')} ({gap_guard_pct})"
                    )
            rg = c.get("risk_guide")
            if rg:
                lines.append(f"- Risk guide: {rg}")
            score_line = c.get("score")
            if score_line:
                detail = f"- Score: {score_line}"
                notes = c.get("score_notes")
                if notes:
                    detail += f" ({notes})"
                lines.append(detail)
            lines.append("")
    else:
        lines.append("_No candidates for today._")
        lines.append("")

    if failures:
        lines.append("### Appendix — Failures")
        for f in failures:
            lines.append(f"- {f}")
        lines.append("")

    lock_name = f".{report_type}.report.lock" if report_type else ".report.lock"
    lock_path = os.path.join(report_dir, lock_name)
    content = "\n".join(lines)
    with advisory_path_lock(lock_path):
        out_path = _next_report_path(report_dir, today, report_type)
        atomic_write_text(out_path, content)

    return out_path
