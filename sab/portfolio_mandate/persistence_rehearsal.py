"""Default-off, disposable-only Portfolio Mandate persistence rehearsal."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict

SqlExecutor = Callable[[str], str]


class PersistencePrototypeDisabledError(RuntimeError):
    """The local-only T16 writer was invoked without explicit opt-in."""


class T16ActivationResult(TypedDict):
    """Typed result returned by the existing A1 activation RPC."""

    activation_event_id: str
    mandate_version_id: str
    result_status: Literal["ACTIVATED", "ALREADY_ACTIVATED"]


class T16DecisionProjection(TypedDict):
    """Minimal decision projection inspected by the T16 rehearsal."""

    mandate_version_id: str
    projection_status: Literal["SUPERSEDED"]
    eligible: bool
    projection_version: int


class T16RollbackResult(TypedDict):
    """Evidence returned from the transaction that is always rolled back."""

    append_only_guard: Literal["ENFORCED"]
    correction_count: int
    rebuilt_projection_count: int
    transaction_outcome: Literal["ROLLED_BACK"]


@dataclass(frozen=True)
class T16ActivationCommand:
    """Synthetic activation identifiers for one disposable T16 rehearsal."""

    command_id: uuid.UUID
    activation_event_id: uuid.UUID
    mandate_id: uuid.UUID
    draft_mandate_version_id: uuid.UUID
    expected_mandate_version_id: uuid.UUID
    actor_id: uuid.UUID
    broker_snapshot_version: int
    allocation_version: int
    correction_command_id: uuid.UUID
    correction_event_id: uuid.UUID

    def __post_init__(self) -> None:
        if self.broker_snapshot_version <= 0 or self.allocation_version <= 0:
            raise ValueError("snapshot and allocation versions must be positive")


class PortfolioMandatePersistenceT16:
    """Exercise the existing A1 writer without owning a database connection.

    The caller must supply an executor only after independently proving that its
    target is the approved disposable loopback database. This prototype is not
    imported by runtime commands and stays disabled unless both opt-ins are set.
    """

    def __init__(
        self,
        executor: SqlExecutor,
        *,
        writer_enabled: bool = False,
        target_kind: Literal["DISPOSABLE_LOOPBACK"] | None = None,
    ) -> None:
        if writer_enabled and target_kind != "DISPOSABLE_LOOPBACK":
            raise ValueError("T16 requires the DISPOSABLE_LOOPBACK target")
        self._executor = executor
        self._writer_enabled = writer_enabled
        self._target_kind = target_kind

    def activate(self, command: T16ActivationCommand) -> T16ActivationResult:
        """Call the existing A1 activation RPC and parse its typed result."""

        self._require_enabled()
        raw = self._executor(_activation_sql(command))
        parts = raw.split("|")
        if len(parts) != 3 or parts[2] not in {"ACTIVATED", "ALREADY_ACTIVATED"}:
            raise ValueError("unexpected A1 activation result")
        return T16ActivationResult(
            activation_event_id=parts[0],
            mandate_version_id=parts[1],
            result_status=parts[2],  # type: ignore[typeddict-item]
        )

    def project(self, command: T16ActivationCommand) -> T16DecisionProjection:
        """Read the public decision semantics through the service role."""

        self._require_enabled()
        raw = self._executor(_projection_sql(command))
        parts = raw.split("|")
        if len(parts) != 4 or parts[1] != "SUPERSEDED" or parts[2] not in {"t", "f"}:
            raise ValueError("unexpected A1 decision projection")
        return T16DecisionProjection(
            mandate_version_id=parts[0],
            projection_status="SUPERSEDED",
            eligible=parts[2] == "t",
            projection_version=int(parts[3]),
        )

    def rebuild_and_rollback(self, command: T16ActivationCommand) -> T16RollbackResult:
        """Rebuild a corrected projection inside a transaction, then roll it back."""

        self._require_enabled()
        raw = self._executor(_rebuild_rollback_sql(command))
        parts = raw.split("|")
        if len(parts) != 4 or parts[0] != "ENFORCED" or parts[3] != "ROLLED_BACK":
            raise ValueError("unexpected T16 rollback rehearsal result")
        return T16RollbackResult(
            append_only_guard="ENFORCED",
            correction_count=int(parts[1]),
            rebuilt_projection_count=int(parts[2]),
            transaction_outcome="ROLLED_BACK",
        )

    def _require_enabled(self) -> None:
        if not self._writer_enabled or self._target_kind != "DISPOSABLE_LOOPBACK":
            raise PersistencePrototypeDisabledError(
                "T16 persistence prototype is default-off"
            )


def _activation_sql(command: T16ActivationCommand) -> str:
    return f"""
    set role authenticated;
    set request.jwt.claim.role = 'authenticated';
    set request.jwt.claim.sub = '{command.actor_id}';
    select * from public.activate_mandate_version_a1(
      '{command.command_id}',
      '{command.activation_event_id}',
      '{command.mandate_id}',
      '{command.draft_mandate_version_id}',
      '{command.expected_mandate_version_id}',
      {command.broker_snapshot_version},
      {command.allocation_version}
    );
    """


def _projection_sql(command: T16ActivationCommand) -> str:
    return f"""
    set role service_role;
    select concat_ws('|',
      mandate_version_id,
      projection_status,
      eligible,
      projection_version
    )
    from public.portfolio_mandate_decision_projection_a1
    where mandate_version_id = '{command.expected_mandate_version_id}';
    """


def _rebuild_rollback_sql(command: T16ActivationCommand) -> str:
    return f"""
    begin;
    create temporary table t16_rehearsal_guard (
      append_only_guard text not null
    ) on commit drop;
    do $t16_append_only$
    begin
      begin
        update public.portfolio_mandate_journal_event_a1
        set event_type = 'MUTATION_MUST_FAIL'
        where journal_event_id = '{command.activation_event_id}';
        raise exception 'append-only trigger did not reject mutation';
      exception
        when sqlstate '55000' then
          insert into t16_rehearsal_guard values ('ENFORCED');
      end;
    end;
    $t16_append_only$;

    insert into public.portfolio_mandate_journal_event_a1 (
      journal_event_id,
      command_id,
      aggregate_id,
      aggregate_version_id,
      event_type,
      actor_kind,
      event_payload,
      supersedes_event_id,
      published_at
    )
    select
      '{command.correction_event_id}',
      '{command.correction_command_id}',
      source.aggregate_id,
      source.aggregate_version_id,
      'DECISION_CORRECTED',
      'USER',
      jsonb_build_object(
        'decision_id', source.event_payload ->> 'decision_id',
        'projection_status', 'SUPERSEDED',
        'eligible', false
      ),
      source.journal_event_id,
      source.published_at + interval '1 second'
    from public.portfolio_mandate_journal_event_a1 as source
    where source.aggregate_id = '{command.mandate_id}'
      and source.aggregate_version_id = '{command.expected_mandate_version_id}'
      and source.event_type = 'DECISION_SUPERSEDED';

    delete from public.portfolio_mandate_decision_projection_a1
    where mandate_version_id = '{command.expected_mandate_version_id}';

    with correction as (
      select *
      from public.portfolio_mandate_journal_event_a1
      where journal_event_id = '{command.correction_event_id}'
    ), unique_slice as (
      select
        (array_agg(slice_id order by slice_id))[1] as slice_id,
        count(*) as slice_count
      from public.portfolio_mandate_position_slice_a1
      where mandate_version_id = '{command.expected_mandate_version_id}'
    )
    insert into public.portfolio_mandate_decision_projection_a1 (
      decision_id,
      mandate_version_id,
      slice_id,
      source_journal_event_id,
      projection_status,
      eligible,
      projection_version,
      superseded_at
    )
    select
      (correction.event_payload ->> 'decision_id')::uuid,
      correction.aggregate_version_id,
      unique_slice.slice_id,
      correction.journal_event_id,
      'SUPERSEDED',
      false,
      2,
      correction.published_at
    from correction
    cross join unique_slice
    where unique_slice.slice_count = 1;

    select concat_ws('|',
      (select append_only_guard from t16_rehearsal_guard),
      (select count(*) from public.portfolio_mandate_journal_event_a1
       where journal_event_id = '{command.correction_event_id}'),
      (select count(*) from public.portfolio_mandate_decision_projection_a1
       where mandate_version_id = '{command.expected_mandate_version_id}'
         and projection_status = 'SUPERSEDED'
         and not eligible
         and projection_version = 2),
      'ROLLED_BACK'
    );
    rollback;
    """


__all__ = [
    "PersistencePrototypeDisabledError",
    "PortfolioMandatePersistenceT16",
    "T16ActivationCommand",
    "T16ActivationResult",
    "T16DecisionProjection",
    "T16RollbackResult",
]
