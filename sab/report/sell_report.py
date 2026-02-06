from __future__ import annotations

import datetime as _dt
import math
import os
from collections.abc import Iterable
from dataclasses import dataclass

from ..utils.atomic_io import advisory_path_lock, atomic_write_text


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _fmt_number(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "-"
    try:
        if digits == 0:
            return f"{value:,.0f}"
        return f"{value:,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def _fmt_quantity(value: float | None, max_digits: int = 6) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if math.isnan(numeric):
        return "-"

    try:
        digits = int(max_digits)
    except (TypeError, ValueError):
        digits = 6
    digits = max(0, min(digits, 8))
    if digits == 0:
        return f"{numeric:,.0f}"

    rounded = round(numeric, digits)
    if rounded == 0:
        rounded = 0.0
    if math.isclose(rounded, round(rounded), abs_tol=10 ** (-digits)):
        return f"{rounded:,.0f}"
    return f"{rounded:,.{digits}f}".rstrip("0").rstrip(".")


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "-"
    try:
        return f"{value * 100:+.1f}%"
    except (TypeError, ValueError):
        return "-"


def _fmt_currency(
    value: float | None, currency: str | None, fx_rate: float | None
) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if math.isnan(numeric):
        return "-"

    curr = (currency or "KRW").upper()
    if curr == "USD":
        display = f"${numeric:,.2f}"
        if fx_rate:
            converted = numeric * fx_rate
            display += f" (₩{converted:,.0f})"
        return display
    if curr == "KRW":
        return f"₩{numeric:,.0f}"
    return f"{curr} {numeric:,.2f}"


@dataclass
class SellReportRow:
    ticker: str
    name: str
    quantity: float | None
    entry_price: float | None
    entry_date: str | None
    last_price: float | None
    pnl_pct: float | None
    action: str
    reasons: list[str]
    stop_price: float | None
    target_price: float | None
    notes: str | None = None
    currency: str | None = None
    eval_date: str | None = None


def write_sell_report(
    *,
    report_dir: str,
    provider: str,
    evaluated: Iterable[SellReportRow],
    failures: Iterable[str] | None = None,
    cache_hint: str | None = None,
    atr_trail_multiplier: float | None = None,
    time_stop_days: int | None = None,
    fx_rate: float | None = None,
    fx_note: str | None = None,
    sell_mode: str | None = None,
    sell_mode_note: str | None = None,
    quantity_digits: int = 6,
) -> str:
    _ensure_dir(report_dir)

    today = _dt.datetime.now().strftime("%Y-%m-%d")
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    rows = list(evaluated)
    failures_list = list(failures or [])
    has_usd = any((row.currency or "").upper() == "USD" for row in rows)

    rules: list[str] = []
    if atr_trail_multiplier is not None:
        rules.append(f"ATR trail ×{atr_trail_multiplier:g}")
    if time_stop_days is not None and time_stop_days > 0:
        rules.append(f"Time stop {time_stop_days}d")

    lines: list[str] = []
    lines.append(f"# Holdings Sell Review — {today}")
    lines.append(f"- Run at: {now_str} KST")
    cache_note = f" (cache: {cache_hint})" if cache_hint else ""
    lines.append(f"- Provider: {provider}{cache_note}")
    lines.append(f"- Evaluated holdings: {len(rows)}")
    if has_usd:
        if fx_rate:
            fx_line = f"- FX: 1 USD ≈ ₩{fx_rate:,.0f}"
            if fx_note:
                fx_line += f" ({fx_note})"
        elif fx_note:
            fx_line = f"- FX: {fx_note}"
        else:
            fx_line = "- FX: unavailable"
        lines.append(fx_line)
    if rules:
        lines.append(f"- Rules: {', '.join(rules)}")
    if sell_mode:
        mode_label = sell_mode
        if sell_mode == "sma_ema_hybrid":
            mode_label = "sma_ema_hybrid (SMA20 + EMA10/21)"
        line = f"- Sell mode: {mode_label}"
        if sell_mode_note:
            line += f" — {sell_mode_note}"
        lines.append(line)
    if failures_list:
        lines.append(f"- Notes: {len(failures_list)} issue(s) logged (see Appendix)")
    lines.append("")

    if rows:
        lines.append("## Holdings Summary")
        lines.append("| Ticker | Qty | Entry | Last | P/L% | State | Stop | Target |")
        lines.append("|--------|----:|------:|-----:|-----:|-------|------|--------|")
        for row in rows:
            lines.append(
                f"| {row.ticker} | {_fmt_quantity(row.quantity, quantity_digits)} | {_fmt_currency(row.entry_price, row.currency, fx_rate)} | {_fmt_currency(row.last_price, row.currency, fx_rate)} | {_fmt_percent(row.pnl_pct)} | {row.action} | {_fmt_currency(row.stop_price, row.currency, fx_rate)} | {_fmt_currency(row.target_price, row.currency, fx_rate)} |"
            )
        lines.append("")

        for row in rows:
            title = f"## [{row.action}] {row.ticker}"
            if row.name and row.name != row.ticker:
                title += f" — {row.name}"
            lines.append(title)
            entry_details = []
            if row.quantity is not None:
                entry_details.append(f"Qty {row.quantity:g}")
            if row.entry_price is not None:
                entry_details.append(
                    f"Entry {_fmt_currency(row.entry_price, row.currency, fx_rate)}"
                )
            if row.entry_date:
                entry_details.append(f"since {row.entry_date}")
            if entry_details:
                lines.append(f"- Position: {' / '.join(entry_details)}")
            if row.last_price is not None:
                last_line = f"- Last close: {_fmt_currency(row.last_price, row.currency, fx_rate)}"
                if row.eval_date:
                    last_line += f" (as of {row.eval_date})"
                lines.append(last_line)
            lines.append(f"- P/L: {_fmt_percent(row.pnl_pct)}")
            if row.stop_price is not None or row.target_price is not None:
                stop_txt = _fmt_currency(row.stop_price, row.currency, fx_rate)
                target_txt = _fmt_currency(row.target_price, row.currency, fx_rate)
                lines.append(f"- Risk guide: Stop {stop_txt} / Target {target_txt}")
            if row.notes:
                lines.append(f"- Notes: {row.notes}")
            if row.reasons:
                lines.append("- Reasons:")
                for reason in row.reasons:
                    lines.append(f"  - {reason}")
            lines.append("")
    else:
        lines.append("_No holdings evaluated._")
        lines.append("")

    if failures_list:
        lines.append("### Appendix — Issues")
        for item in failures_list:
            lines.append(f"- {item}")
        lines.append("")

    suffix = ".sell.md"
    lock_path = os.path.join(report_dir, ".sell.report.lock")
    content = "\n".join(lines)
    with advisory_path_lock(lock_path):
        base = os.path.join(report_dir, f"{today}{suffix}")
        out_path = base
        if os.path.exists(out_path):
            i = 1
            while True:
                candidate = os.path.join(report_dir, f"{today}-{i}{suffix}")
                if not os.path.exists(candidate):
                    out_path = candidate
                    break
                i += 1
        atomic_write_text(out_path, content)

    return out_path


__all__ = ["SellReportRow", "write_sell_report"]
