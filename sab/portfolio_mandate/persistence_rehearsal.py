"""Default-off, disposable-only Portfolio Mandate persistence rehearsal."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

SqlExecutor = Callable[[str], str]


class PersistencePrototypeDisabledError(RuntimeError):
    """The local-only T16 writer was invoked without explicit opt-in."""


class PersistenceRehearsalContractError(ValueError):
    """A T16 target or executor result failed closed."""

    def __init__(self, operation: str, field: str, message: str) -> None:
        self.operation = operation
        self.field = field
        self.message = message
        super().__init__(f"{operation}.{field}: {message}")


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
class T16DisposableTarget:
    """Expected identity of the independently created disposable database."""

    port: int
    database_name: str
    data_directory: str
    session_user: str
    server_version_num: Literal["170011"] = "170011"

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise PersistenceRehearsalContractError(
                "target", "port", "must be an explicit TCP port"
            )
        if not self.database_name.startswith("portfolio_mandate_a1_test_"):
            raise PersistenceRehearsalContractError(
                "target", "database_name", "must use the disposable database prefix"
            )
        data_parts = self.data_directory.split("/")
        if (
            len(data_parts) != 5
            or data_parts[:3] != ["", "private", "tmp"]
            or not data_parts[3].startswith("portfolio-mandate-a1-pg17.")
            or data_parts[4] != "data"
        ):
            raise PersistenceRehearsalContractError(
                "target", "data_directory", "must use the dedicated disposable path"
            )
        if not self.session_user:
            raise PersistenceRehearsalContractError(
                "target", "session_user", "must be explicit"
            )
        if self.server_version_num != "170011":
            raise PersistenceRehearsalContractError(
                "target", "server_version_num", "must be PostgreSQL 17.11"
            )


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
        target: T16DisposableTarget | None = None,
    ) -> None:
        self._executor = executor
        self._writer_enabled = writer_enabled
        self._target = target
        if writer_enabled:
            if target is None:
                raise PersistenceRehearsalContractError(
                    "target", "identity", "verified disposable target is required"
                )
            self._verify_target_identity(target)

    def activate(self, command: T16ActivationCommand) -> T16ActivationResult:
        """Call the existing A1 activation RPC and parse its typed result."""

        target = self._require_enabled()
        raw = self._executor(_activation_sql(command, target))
        parts = _split_result(raw, operation="activation", expected_fields=3)
        activation_event_id = _parse_uuid(parts[0], "activation", "activation_event_id")
        mandate_version_id = _parse_uuid(parts[1], "activation", "mandate_version_id")
        if activation_event_id != command.activation_event_id:
            raise PersistenceRehearsalContractError(
                "activation", "activation_event_id", "does not match the command"
            )
        if mandate_version_id != command.draft_mandate_version_id:
            raise PersistenceRehearsalContractError(
                "activation", "mandate_version_id", "does not match the command"
            )
        if parts[2] not in {"ACTIVATED", "ALREADY_ACTIVATED"}:
            raise PersistenceRehearsalContractError(
                "activation", "result_status", "is not an allowed A1 status"
            )
        return T16ActivationResult(
            activation_event_id=str(activation_event_id),
            mandate_version_id=str(mandate_version_id),
            result_status=cast(Literal["ACTIVATED", "ALREADY_ACTIVATED"], parts[2]),
        )

    def project(self, command: T16ActivationCommand) -> T16DecisionProjection:
        """Read the public decision semantics through the service role."""

        target = self._require_enabled()
        raw = self._executor(_projection_sql(command, target))
        parts = _split_result(raw, operation="projection", expected_fields=4)
        mandate_version_id = _parse_uuid(parts[0], "projection", "mandate_version_id")
        if mandate_version_id != command.expected_mandate_version_id:
            raise PersistenceRehearsalContractError(
                "projection", "mandate_version_id", "does not match the source version"
            )
        if parts[1] != "SUPERSEDED":
            raise PersistenceRehearsalContractError(
                "projection", "projection_status", "must be SUPERSEDED"
            )
        if parts[2] != "f":
            raise PersistenceRehearsalContractError(
                "projection", "eligible", "superseded decision must be ineligible"
            )
        projection_version = _parse_positive_int(
            parts[3], "projection", "projection_version"
        )
        return T16DecisionProjection(
            mandate_version_id=str(mandate_version_id),
            projection_status="SUPERSEDED",
            eligible=False,
            projection_version=projection_version,
        )

    def rebuild_and_rollback(self, command: T16ActivationCommand) -> T16RollbackResult:
        """Rebuild a corrected projection inside a transaction, then roll it back."""

        target = self._require_enabled()
        raw = self._executor(_rebuild_rollback_sql(command, target))
        parts = _split_result(raw, operation="rollback", expected_fields=4)
        correction_count = _parse_positive_int(parts[1], "rollback", "correction_count")
        rebuilt_projection_count = _parse_positive_int(
            parts[2], "rollback", "rebuilt_projection_count"
        )
        if parts[0] != "ENFORCED":
            raise PersistenceRehearsalContractError(
                "rollback", "append_only_guard", "must be ENFORCED"
            )
        if correction_count != 1 or rebuilt_projection_count != 1:
            raise PersistenceRehearsalContractError(
                "rollback", "result_count", "must contain one correction and projection"
            )
        if parts[3] != "ROLLED_BACK":
            raise PersistenceRehearsalContractError(
                "rollback", "transaction_outcome", "must be ROLLED_BACK"
            )
        return T16RollbackResult(
            append_only_guard="ENFORCED",
            correction_count=correction_count,
            rebuilt_projection_count=rebuilt_projection_count,
            transaction_outcome="ROLLED_BACK",
        )

    def _require_enabled(self) -> T16DisposableTarget:
        if not self._writer_enabled or self._target is None:
            raise PersistencePrototypeDisabledError(
                "T16 persistence prototype is default-off"
            )
        return self._target

    def _verify_target_identity(self, target: T16DisposableTarget) -> None:
        raw = self._executor(_target_identity_sql())
        parts = raw.split("\t")
        expected = [
            "127.0.0.1",
            str(target.port),
            target.database_name,
            target.data_directory,
            target.session_user,
            target.server_version_num,
        ]
        if parts != expected:
            raise PersistenceRehearsalContractError(
                "target", "identity", "does not match the disposable proof"
            )


def _split_result(raw: str, *, operation: str, expected_fields: int) -> list[str]:
    parts = raw.split("|")
    if len(parts) != expected_fields:
        raise PersistenceRehearsalContractError(
            operation, "result", f"must contain {expected_fields} fields"
        )
    return parts


def _parse_uuid(raw: str, operation: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (AttributeError, ValueError) as error:
        raise PersistenceRehearsalContractError(
            operation, field, "must be a UUID"
        ) from error


def _parse_positive_int(raw: str, operation: str, field: str) -> int:
    try:
        value = int(raw)
    except ValueError as error:
        raise PersistenceRehearsalContractError(
            operation, field, "must be an integer"
        ) from error
    if value <= 0:
        raise PersistenceRehearsalContractError(operation, field, "must be positive")
    return value


def _target_identity_sql() -> str:
    return """
    select concat_ws(E'\\t',
      host(inet_server_addr()),
      inet_server_port()::text,
      current_database(),
      current_setting('data_directory'),
      session_user,
      current_setting('server_version_num')
    );
    """


def _target_identity_guard_sql(target: T16DisposableTarget) -> str:
    expected_database = _sql_text_literal(target.database_name)
    expected_data_directory = _sql_text_literal(target.data_directory)
    expected_session_user = _sql_text_literal(target.session_user)
    expected_version = _sql_text_literal(target.server_version_num)
    return f"""
    do $t16_disposable_identity$
    begin
      if host(inet_server_addr()) is distinct from '127.0.0.1'
         or inet_server_port() is distinct from {target.port}
         or current_database() is distinct from {expected_database}
         or current_setting('data_directory') is distinct from {expected_data_directory}
         or session_user is distinct from {expected_session_user}
         or current_setting('server_version_num') is distinct from {expected_version}
      then
        raise exception using
          errcode = '55000',
          message = 'T16 disposable target identity mismatch';
      end if;
    end;
    $t16_disposable_identity$;
    """


def _sql_text_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _activation_sql(command: T16ActivationCommand, target: T16DisposableTarget) -> str:
    return f"""
    {_target_identity_guard_sql(target)}
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


def _projection_sql(command: T16ActivationCommand, target: T16DisposableTarget) -> str:
    return f"""
    {_target_identity_guard_sql(target)}
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


def _rebuild_rollback_sql(
    command: T16ActivationCommand, target: T16DisposableTarget
) -> str:
    return f"""
    {_target_identity_guard_sql(target)}
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
    "PersistenceRehearsalContractError",
    "PortfolioMandatePersistenceT16",
    "T16ActivationCommand",
    "T16ActivationResult",
    "T16DecisionProjection",
    "T16DisposableTarget",
    "T16RollbackResult",
]
