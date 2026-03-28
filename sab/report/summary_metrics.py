from __future__ import annotations

from collections.abc import Iterable, Mapping


def compute_ratio(*, numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def count_provider_fallbacks(
    *,
    tickers: Iterable[str],
    ticker_data_source: Mapping[str, str],
    primary_provider: str,
) -> int:
    normalized_primary_provider = primary_provider.strip().lower()
    seen: set[str] = set()
    fallback_count = 0

    for raw_ticker in tickers:
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        data_source = str(ticker_data_source.get(ticker, "") or "").strip().lower()
        if data_source and data_source != normalized_primary_provider:
            fallback_count += 1

    return fallback_count


def build_market_data_summary(
    *,
    requested_count: int,
    covered_count: int,
    fallback_count: int,
) -> dict[str, int | float | None]:
    requested = max(int(requested_count), 0)
    covered = max(int(covered_count), 0)
    fallback = max(int(fallback_count), 0)
    missing = max(requested - covered, 0)

    return {
        "data_requested_count": requested,
        "data_covered_count": covered,
        "data_missing_count": missing,
        "data_coverage_ratio": compute_ratio(
            numerator=covered,
            denominator=requested,
        ),
        "provider_fallback_count": fallback,
        "provider_fallback_ratio": compute_ratio(
            numerator=fallback,
            denominator=requested,
        ),
    }


__all__ = [
    "build_market_data_summary",
    "compute_ratio",
    "count_provider_fallbacks",
]
