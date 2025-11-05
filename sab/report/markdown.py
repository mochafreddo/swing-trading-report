from __future__ import annotations

import datetime as _dt
import os
from typing import Iterable


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _next_report_path(report_dir: str, date: str) -> str:
    base = os.path.join(report_dir, f"{date}.md")
    if not os.path.exists(base):
        return base
    i = 1
    while True:
        p = os.path.join(report_dir, f"{date}-{i}.md")
        if not os.path.exists(p):
            return p
        i += 1


def write_report(
    *,
    report_dir: str,
    provider: str,
    universe_count: int,
    candidates: Iterable[dict],
    failures: Iterable[str] | None = None,
    cache_hint: str | None = None,
) -> str:
    _ensure_dir(report_dir)
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path = _next_report_path(report_dir, today)

    cand_list = list(candidates)
    failures = list(failures or [])

    lines: list[str] = []
    lines.append(f"# Swing Screening — {today}")
    lines.append(f"- Run at: {now_str} KST")
    cache_note = f" (cache: {cache_hint})" if cache_hint else ""
    lines.append(f"- Provider: {provider}{cache_note}")
    lines.append(f"- Universe: {universe_count} tickers, Candidates: {len(cand_list)}")
    if failures:
        lines.append(f"- Notes: {len(failures)} tickers failed (see Appendix)")
    lines.append("")

    if cand_list:
        lines.append("## Candidates")
        lines.append("| Ticker | Name | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap |")
        lines.append("|--------|------|------:|------:|------:|------:|------:|----:|")
        for c in cand_list:
            lines.append(
                f"| {c.get('ticker','-')} | {c.get('name','-')} | {c.get('price','-')} | "
                f"{c.get('ema20','-')} | {c.get('ema50','-')} | {c.get('rsi14','-')} | "
                f"{c.get('atr14','-')} | {c.get('gap','-')} |"
            )
        lines.append("")

        for c in cand_list:
            lines.append(f"## [매수 후보] {c.get('ticker','-')} — {c.get('name','-')}")
            lines.append(
                f"- Price: {c.get('price','-')} (d/d {c.get('pct_change','-')}) H: {c.get('high','-')} L: {c.get('low','-')}"
            )
            lines.append(
                f"- Trend: EMA20({c.get('ema20','-')}) vs EMA50({c.get('ema50','-')})"
            )
            lines.append(f"- Momentum: RSI14={c.get('rsi14','-')}")
            lines.append(f"- Volatility: ATR14={c.get('atr14','-')}")
            lines.append(f"- Gap: {c.get('gap','-')} vs prev close")
            rg = c.get("risk_guide")
            if rg:
                lines.append(f"- Risk guide: {rg}")
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

