from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager

_PMC_DISCONTINUED_BREAK_PATTERN = (
    r".*(break_start.*break_end|break_end.*break_start).*discontinued.*"
)
_PMC_MODULE_PATTERN = r"^pandas_market_calendars(\..*)?$"


@contextmanager
def suppress_pmc_discontinued_break_warning() -> Iterator[None]:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_PMC_DISCONTINUED_BREAK_PATTERN,
            category=UserWarning,
            module=_PMC_MODULE_PATTERN,
        )
        yield


__all__ = ["suppress_pmc_discontinued_break_warning"]
