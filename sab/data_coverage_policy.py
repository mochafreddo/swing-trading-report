from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MIN_DATA_COVERAGE = 0.70


@dataclass(frozen=True, slots=True)
class MissingMarketDataSummary:
    missing: tuple[str, ...]
    coverage: float
    message: str
    fatal: bool


def is_data_coverage_fatal(
    data_coverage: float,
    *,
    min_data_coverage: float = MIN_DATA_COVERAGE,
) -> bool:
    return data_coverage < min_data_coverage


def summarize_missing_market_data(
    *,
    requested: Sequence[str],
    available: Mapping[str, object],
    subject: str,
    preview_limit: int = 10,
    min_data_coverage: float = MIN_DATA_COVERAGE,
) -> MissingMarketDataSummary | None:
    if not requested:
        return None

    missing = tuple(item for item in requested if item not in available)
    if not missing:
        return None

    total = len(requested)
    missing_count = len(missing)
    covered_count = total - missing_count
    coverage = covered_count / total if total > 0 else 0.0
    preview = ", ".join(missing[:preview_limit])
    if missing_count > preview_limit:
        preview = f"{preview}, +{missing_count - preview_limit} more"

    message = (
        "Missing market data for "
        f"{missing_count}/{total} {subject} (coverage={coverage:.2f}, "
        f"required>={min_data_coverage:.2f}): {preview}"
    )
    return MissingMarketDataSummary(
        missing=missing,
        coverage=coverage,
        message=message,
        fatal=is_data_coverage_fatal(
            coverage,
            min_data_coverage=min_data_coverage,
        ),
    )


__all__ = [
    "MIN_DATA_COVERAGE",
    "MissingMarketDataSummary",
    "is_data_coverage_fatal",
    "summarize_missing_market_data",
]
