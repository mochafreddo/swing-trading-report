from __future__ import annotations

import uuid

import pytest
from sab.portfolio_mandate.persistence_rehearsal import (
    PersistencePrototypeDisabledError,
    PortfolioMandatePersistenceT16,
    T16ActivationCommand,
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
    with pytest.raises(ValueError, match="DISPOSABLE_LOOPBACK"):
        PortfolioMandatePersistenceT16(
            lambda _sql: "",
            writer_enabled=True,
            target_kind="LIVE",  # type: ignore[arg-type]
        )


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
