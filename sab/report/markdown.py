from __future__ import annotations

import datetime as _dt
import os
from collections.abc import Iterable


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
) -> str:
    _ensure_dir(report_dir)
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path = _next_report_path(report_dir, today, report_type)

    cand_list = list(candidates)
    failures = list(failures or [])

    title = REPORT_TITLES.get(report_type, "Swing Report")
    lines: list[str] = []
    lines.append(f"# {title} — {today}")
    lines.append(f"- Run at: {now_str} KST")
    cache_note = f" (cache: {cache_hint})" if cache_hint else ""
    lines.append(f"- Provider: {provider}{cache_note}")
    lines.append(f"- Universe: {universe_count} tickers, Candidates: {len(cand_list)}")
    if failures:
        lines.append(f"- Notes: {len(failures)} issue(s) logged (see Appendix)")
    lines.append("")

    if cand_list:
        lines.append("## Candidates")
        lines.append("| Ticker | Name | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap | Score |")
        lines.append("|--------|------|------:|------:|------:|------:|------:|-----:|------:|")
        for c in cand_list:
            lines.append(
                f"| {c.get('ticker', '-')} | {c.get('name', '-')} | {c.get('price', '-')} | "
                f"{c.get('ema20', '-')} | {c.get('ema50', '-')} | {c.get('rsi14', '-')} | "
                f"{c.get('atr14', '-')} | {c.get('gap', '-')} | {c.get('score', '-')} |"
            )
        lines.append("")

        for c in cand_list:
            lines.append(f"## [매수 후보] {c.get('ticker', '-')} — {c.get('name', '-')}")
            lines.append(
                f"- Price: {c.get('price', '-')} (d/d {c.get('pct_change', '-')}) H: {c.get('high', '-')} L: {c.get('low', '-')}"
            )
            currency = c.get("currency")
            if currency and currency.upper() != "KRW":
                fx_note = c.get("fx_note")
                converted = c.get("price_converted")
                extra = fx_note or ""
                if converted:
                    extra = (extra + ", " if extra else "") + f"가격 ≈ ₩{converted:,.0f}"
                label = f"- Currency: {currency}"
                if extra:
                    label += f" ({extra})"
                lines.append(label)
            status = c.get("market_status")
            if status:
                lines.append(f"- Market: {status}")
            trend_line = f"- Trend: EMA20({c.get('ema20', '-')}) vs EMA50({c.get('ema50', '-')})"
            if c.get("sma200") and c.get("sma200") != "-":
                trend_line += f", SMA200({c.get('sma200', '-')})"
            if c.get("trend_pass"):
                trend_line += f" (trend pass: {c.get('trend_pass')})"
            lines.append(trend_line)
            lines.append(f"- Momentum: RSI14={c.get('rsi14', '-')}")
            lines.append(f"- Volatility: ATR14={c.get('atr14', '-')}")
            lines.append(f"- Gap: {c.get('gap', '-')} (threshold {c.get('gap_threshold', '-')})")
            lines.append(f"- Liquidity: Avg $Vol {c.get('avg_dollar_volume', '-')}")
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

    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))

    return out_path
