from __future__ import annotations

import uuid

import pytest
from sab.portfolio_mandate.persistence_rehearsal import (
    PersistencePrototypeDisabledError,
    PersistenceRehearsalContractError,
    PortfolioMandatePersistenceT16,
    T16ActivationCommand,
    T16DisposableTarget,
)


def _command() -> T16ActivationCommand:
    namespace = uuid.UUID("00000000-0000-4000-8000-000000000016")
    return T16ActivationCommand(
        command_id=uuid.uuid5(namespace, "command"),
        activation_event_id=uuid.uuid5(namespace, "activation-event"),
        mandate_id=uuid.uuid5(namespace, "mandate"),
        draft_mandate_version_id=uuid.uuid5(namespace, "draft-version"),
        expected_mandate_version_id=uuid.uuid5(namespace, "expected-version"),
        actor_id=uuid.uuid5(namespace, "actor"),
        broker_snapshot_version=1,
        allocation_version=1,
        correction_command_id=uuid.uuid5(namespace, "correction-command"),
        correction_event_id=uuid.uuid5(namespace, "correction-event"),
    )


def test_t16_writer_is_default_off_and_does_not_call_executor() -> None:
    calls: list[str] = []

    def executor(sql: str) -> str:
        calls.append(sql)
        return ""

    prototype = PortfolioMandatePersistenceT16(executor)

    with pytest.raises(PersistencePrototypeDisabledError, match="default-off"):
        prototype.activate(_command())

    assert calls == []


def test_t16_requires_explicit_disposable_loopback_target() -> None:
    with pytest.raises(PersistenceRehearsalContractError, match="target"):
        PortfolioMandatePersistenceT16(lambda _sql: "", writer_enabled=True)


def test_t16_enabled_writer_verifies_exact_target_identity() -> None:
    target = T16DisposableTarget(
        port=65439,
        database_name="portfolio_mandate_a1_test_unit",
        data_directory="/private/tmp/portfolio-mandate-a1-pg17.unit/data",
        session_user="tester",
    )

    with pytest.raises(PersistenceRehearsalContractError, match=r"target\.identity"):
        PortfolioMandatePersistenceT16(
            lambda _sql: (
                "127.0.0.1\t65439\tproduction\t/var/lib/postgresql/data\ttester\t170011"
            ),
            writer_enabled=True,
            target=target,
        )


def test_t16_executor_output_fails_with_typed_field_error() -> None:
    target = T16DisposableTarget(
        port=65439,
        database_name="portfolio_mandate_a1_test_unit",
        data_directory="/private/tmp/portfolio-mandate-a1-pg17.unit/data",
        session_user="tester",
    )
    responses = iter(
        [
            "127.0.0.1\t65439\tportfolio_mandate_a1_test_unit\t"
            "/private/tmp/portfolio-mandate-a1-pg17.unit/data\ttester\t170011",
            "not-a-valid-result",
        ]
    )
    prototype = PortfolioMandatePersistenceT16(
        lambda _sql: next(responses), writer_enabled=True, target=target
    )

    with pytest.raises(PersistenceRehearsalContractError, match=r"activation\.result"):
        prototype.activate(_command())


def test_t16_rechecks_disposable_identity_in_every_operation_session() -> None:
    command = _command()
    target = T16DisposableTarget(
        port=65439,
        database_name="portfolio_mandate_a1_test_unit",
        data_directory="/private/tmp/portfolio-mandate-a1-pg17.unit/data",
        session_user="tester",
    )
    calls: list[str] = []
    responses = iter(
        [
            "127.0.0.1\t65439\tportfolio_mandate_a1_test_unit\t"
            "/private/tmp/portfolio-mandate-a1-pg17.unit/data\ttester\t170011",
            f"{command.activation_event_id}|{command.draft_mandate_version_id}|ACTIVATED",
            f"{command.expected_mandate_version_id}|SUPERSEDED|f|1",
            "ENFORCED|1|1|ROLLED_BACK",
        ]
    )

    def executor(sql: str) -> str:
        calls.append(sql)
        return next(responses)

    prototype = PortfolioMandatePersistenceT16(
        executor, writer_enabled=True, target=target
    )
    prototype.activate(command)
    prototype.project(command)
    prototype.rebuild_and_rollback(command)

    assert len(calls) == 4
    for operation_sql in calls[1:]:
        assert "$t16_disposable_identity$" in operation_sql
        assert "host(inet_server_addr()) is distinct from '127.0.0.1'" in operation_sql
        assert "inet_server_port() is distinct from 65439" in operation_sql
        assert "portfolio_mandate_a1_test_unit" in operation_sql
        assert "/private/tmp/portfolio-mandate-a1-pg17.unit/data" in operation_sql


def test_t16_activation_versions_must_be_positive() -> None:
    command = _command()

    with pytest.raises(ValueError, match="positive"):
        T16ActivationCommand(
            command_id=command.command_id,
            activation_event_id=command.activation_event_id,
            mandate_id=command.mandate_id,
            draft_mandate_version_id=command.draft_mandate_version_id,
            expected_mandate_version_id=command.expected_mandate_version_id,
            actor_id=command.actor_id,
            broker_snapshot_version=0,
            allocation_version=1,
            correction_command_id=command.correction_command_id,
            correction_event_id=command.correction_event_id,
        )
