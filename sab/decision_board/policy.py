"""Pure bounded research-selection policy for Decision Board V0 holdings."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .compiler import (
    CompilerInputError,
    HoldingCompilerItemV0,
    ResearchStateV0,
    _validated_holding_snapshot,
)

MAX_RESEARCH_ITEMS_V0 = 5


@dataclass(frozen=True, slots=True)
class HoldingResearchSelectionV0:
    selected_item_ids: tuple[str, ...]
    states: tuple[tuple[str, ResearchStateV0], ...]


def select_holding_research_v0(
    items: Iterable[HoldingCompilerItemV0], *, max_research_items: int = 5
) -> HoldingResearchSelectionV0:
    """Select at most five holdings without changing the compilation universe."""

    if (
        type(max_research_items) is not int
        or not 0 <= max_research_items <= MAX_RESEARCH_ITEMS_V0
    ):
        raise CompilerInputError("max_research_items must be in range 0..5")
    try:
        values = tuple(items)
    except TypeError as exc:
        raise CompilerInputError(
            "research selection requires a finite iterable"
        ) from exc
    item_ids: set[str] = set()
    validated: list[HoldingCompilerItemV0] = []
    for item in values:
        if _validated_holding_snapshot(item) is None:
            raise CompilerInputError(
                "research selection item is not unchanged and issued"
            )
        if item.item_id in item_ids:
            raise CompilerInputError(
                "research selection item identities must be unique"
            )
        item_ids.add(item.item_id)
        validated.append(item)
    ordered = sorted(
        validated,
        key=lambda item: (
            item.research_priority,
            item.research_order.encode("utf-8"),
            item.item_id.encode("utf-8"),
        ),
    )
    selected = tuple(item.item_id for item in ordered[:max_research_items])
    selected_set = set(selected)
    states = tuple(
        (
            item.item_id,
            ResearchStateV0.CLEAR
            if item.item_id in selected_set
            else ResearchStateV0.NOT_SELECTED_CAP,
        )
        for item in sorted(validated, key=lambda value: value.item_id.encode("utf-8"))
    )
    return HoldingResearchSelectionV0(selected_item_ids=selected, states=states)


__all__ = [
    "MAX_RESEARCH_ITEMS_V0",
    "HoldingResearchSelectionV0",
    "select_holding_research_v0",
]
