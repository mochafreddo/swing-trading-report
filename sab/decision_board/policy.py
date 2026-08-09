"""Pure bounded research-selection policy for Decision Board V0 holdings."""

from __future__ import annotations

import weakref
from collections.abc import Iterable
from dataclasses import dataclass

from .compiler import (
    CompilerInputError,
    HoldingCompilerItemV0,
    ResearchStateV0,
    _holding_selection_snapshot,
    _is_canonical_enum_member,
    _validated_holding_snapshot,
)

MAX_RESEARCH_ITEMS_V0 = 5


type _SelectionSnapshotV0 = tuple[
    tuple[str, ...],
    tuple[tuple[str, ResearchStateV0], ...],
]
type _UniverseSnapshotV0 = tuple[tuple[object, ...], ...]


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class HoldingResearchSelectionV0:
    selected_item_ids: tuple[str, ...]
    states: tuple[tuple[str, ResearchStateV0], ...]


@dataclass(frozen=True, slots=True)
class _SelectionRecordV0:
    reference: weakref.ReferenceType[HoldingResearchSelectionV0]
    selection_snapshot: _SelectionSnapshotV0
    universe_snapshot: _UniverseSnapshotV0


_SELECTIONS: dict[int, _SelectionRecordV0] = {}


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
    return _allocate_selection_v0(
        selected_item_ids=selected,
        states=states,
        universe_snapshot=_universe_snapshot(validated),
    )


def _validate_holding_research_selection_v0(
    value: object,
    *,
    items: Iterable[HoldingCompilerItemV0],
) -> dict[str, ResearchStateV0]:
    """Bind compilation to the exact complete universe used for selection."""

    if type(value) is not HoldingResearchSelectionV0:
        raise CompilerInputError("holding research selection is not an exact V0 result")
    record = _SELECTIONS.get(id(value))
    current = _selection_snapshot(value)
    if (
        record is None
        or record.reference() is not value
        or current is None
        or current != record.selection_snapshot
    ):
        raise CompilerInputError(
            "holding research selection is not unchanged and issued"
        )
    try:
        supplied_items = tuple(items)
    except TypeError as exc:
        raise CompilerInputError("holding compiler universe must be finite") from exc
    if _universe_snapshot(supplied_items) != record.universe_snapshot:
        raise CompilerInputError("holding compiler universe does not match selection")
    selected = set(record.selection_snapshot[0])
    return {
        item.item_id: (
            item.research_state
            if item.item_id in selected
            else ResearchStateV0.NOT_SELECTED_CAP
        )
        for item in supplied_items
    }


def _allocate_selection_v0(
    *,
    selected_item_ids: tuple[str, ...],
    states: tuple[tuple[str, ResearchStateV0], ...],
    universe_snapshot: _UniverseSnapshotV0,
) -> HoldingResearchSelectionV0:
    value = object.__new__(HoldingResearchSelectionV0)
    object.__setattr__(value, "selected_item_ids", selected_item_ids)
    object.__setattr__(value, "states", states)
    snapshot = _selection_snapshot(value)
    if snapshot is None:
        raise CompilerInputError("holding research selection allocation failed")
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[HoldingResearchSelectionV0]) -> None:
        current = _SELECTIONS.get(value_id)
        if current is not None and current.reference is reference:
            _SELECTIONS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _SELECTIONS[value_id] = _SelectionRecordV0(
        reference=reference,
        selection_snapshot=snapshot,
        universe_snapshot=universe_snapshot,
    )
    return value


def _selection_snapshot(value: object) -> _SelectionSnapshotV0 | None:
    if type(value) is not HoldingResearchSelectionV0:
        return None
    try:
        selected = value.selected_item_ids
        states = value.states
    except AttributeError:
        return None
    if type(selected) is not tuple or not all(
        type(item_id) is str for item_id in selected
    ):
        return None
    if type(states) is not tuple:
        return None
    for state in states:
        if (
            type(state) is not tuple
            or len(state) != 2
            or type(state[0]) is not str
            or not _is_canonical_enum_member(state[1], ResearchStateV0)
        ):
            return None
    return selected, states


def _universe_snapshot(items: Iterable[HoldingCompilerItemV0]) -> _UniverseSnapshotV0:
    snapshots: list[tuple[object, ...]] = []
    for item in items:
        snapshot = _holding_selection_snapshot(item)
        if snapshot is None:
            raise CompilerInputError(
                "holding research universe item is not unchanged and issued"
            )
        snapshots.append(snapshot)
    return tuple(
        sorted(snapshots, key=lambda snapshot: str(snapshot[0]).encode("utf-8"))
    )


__all__ = [
    "MAX_RESEARCH_ITEMS_V0",
    "HoldingResearchSelectionV0",
    "select_holding_research_v0",
]
