"""Default-off compiler persistence seam. No connection, credentials or outbound sink."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from .review_import import canonical, replay_review_packet


def _uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError
    return value


class ReviewStore:
    def __init__(
        self, rpc: Callable[[str, dict[str, Any]], Any], *, enabled: bool = False
    ):
        self._rpc = rpc
        self._enabled = enabled

    def _call(self, name: str, params: dict[str, Any]) -> Any:
        if self._enabled is not True:
            raise ValueError("REVIEW_WRITER_DISABLED")
        try:
            return self._rpc(name, params)
        except Exception:
            raise ValueError("REVIEW_STORE_UNAVAILABLE") from None

    def commit(
        self,
        bundle: dict[str, Any],
        *,
        run_id: str,
        owner_id: str,
        trigger_id: str,
        revision: int = 1,
        supersedes: str | None = None,
    ) -> dict[str, Any]:
        if self._enabled is not True:
            raise ValueError("REVIEW_WRITER_DISABLED")
        try:
            replay_review_packet(bundle)
            params = {
                "p_run_id": _uuid(run_id),
                "p_owner_id": _uuid(owner_id),
                "p_trigger_id": _uuid(trigger_id),
                "p_revision": revision,
                "p_supersedes": _uuid(supersedes) if supersedes is not None else None,
                "p_bundle": bundle,
            }
            if type(revision) is not int or revision < 1:
                raise ValueError
            result = self._call("commit_review_r2", params)
            if (
                type(result) is not dict
                or set(result) != {"run_id", "status", "duplicate"}
                or result["run_id"] != run_id
                or result["status"] not in {"COMPILED", "BLOCKED"}
                or type(result["duplicate"]) is not bool
            ):
                raise ValueError
            return result
        except Exception:
            raise ValueError("REVIEW_STORE_UNAVAILABLE") from None

    def record_outcome(
        self,
        *,
        owner_id: str,
        run_id: str,
        outcome_id: str,
        status: str,
        supersedes: str | None = None,
        confirmed_actor_id: str | None = None,
    ) -> None:
        """Review-only outcomes never manufacture order/fill/decision attribution."""
        if self._enabled is not True:
            raise ValueError("REVIEW_WRITER_DISABLED")
        try:
            if status not in {"UNLINKED", "AMBIGUOUS", "NO_ACTION"}:
                raise ValueError
            if status == "NO_ACTION" and confirmed_actor_id != owner_id:
                raise ValueError
            self._call(
                "record_outcome_r2",
                {
                    "p_owner_id": _uuid(owner_id),
                    "p_run_id": _uuid(run_id),
                    "p_outcome_id": _uuid(outcome_id),
                    "p_status": status,
                    "p_basis": "USER_CONFIRMED_NO_ACTION"
                    if status == "NO_ACTION"
                    else "ORDER_AGGREGATE_ONLY",
                    "p_supersedes": _uuid(supersedes)
                    if supersedes is not None
                    else None,
                },
            )
        except Exception:
            raise ValueError("REVIEW_OUTCOME_REJECTED") from None


def compiler_sql(name: str, params: dict[str, Any]) -> str:
    """Fixed compiler RPC renderer for isolated psql harnesses; no arbitrary SQL names.

    JSON is quoted as a SQL literal with apostrophes escaped. Parameters never enter
    a shell argument; callers send this statement over stdin with ON_ERROR_STOP.
    """
    signatures = {
        "commit_review_r2": (
            "p_run_id",
            "p_owner_id",
            "p_trigger_id",
            "p_revision",
            "p_supersedes",
            "p_bundle",
        ),
        "record_outcome_r2": (
            "p_owner_id",
            "p_run_id",
            "p_outcome_id",
            "p_status",
            "p_basis",
            "p_supersedes",
        ),
    }
    if name not in signatures or set(params) != set(signatures[name]):
        raise ValueError("REVIEW_RPC_INVALID")
    values = []
    for key in signatures[name]:
        value = params[key]
        if value is None:
            values.append("NULL")
        elif key == "p_revision":
            if type(value) is not int:
                raise ValueError("REVIEW_RPC_INVALID")
            values.append(str(value))
        else:
            raw = canonical(value) if key == "p_bundle" else str(value)
            values.append("'" + raw.replace("'", "''") + "'")
    return (
        "set standard_conforming_strings=on; set role portfolio_mandate_review_compiler_r2; select portfolio_mandate_private."
        + name
        + "("
        + ",".join(values)
        + ");"
    )
