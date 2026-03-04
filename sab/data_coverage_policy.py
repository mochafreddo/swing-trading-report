from __future__ import annotations

MIN_DATA_COVERAGE = 0.70


def is_data_coverage_fatal(
    data_coverage: float,
    *,
    min_data_coverage: float = MIN_DATA_COVERAGE,
) -> bool:
    return data_coverage < min_data_coverage


__all__ = ["MIN_DATA_COVERAGE", "is_data_coverage_fatal"]
