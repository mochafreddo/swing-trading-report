"""Dependency-injected production composition for Decision Board V0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .cli import DecisionBoardCliConfigV0
from .results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    create_decision_run_failed_v0,
)
from .runner import (
    DecisionBoardRunnerV0,
    DecisionItemEnricherV0,
    DecisionReportUploaderV0,
    DecisionRunPreparerV0,
    DecisionRunRequestV0,
    create_decision_run_request_v0,
)


class DecisionBoardAdapterUnavailableError(RuntimeError):
    """The approved runtime dependencies are not connected."""


class DecisionRunRequestLoaderV0(Protocol):
    """Load one sealed request without widening the CLI authority boundary."""

    def load(self, config: DecisionBoardCliConfigV0) -> object: ...


@dataclass(frozen=True, slots=True)
class DecisionBoardProductionAdapterV0:
    """Bind approved request, preparation, enrichment, and persistence adapters."""

    request_loader: DecisionRunRequestLoaderV0
    preparer: DecisionRunPreparerV0
    enricher: DecisionItemEnricherV0
    uploader: DecisionReportUploaderV0 | None = None

    def execute(self, config: DecisionBoardCliConfigV0) -> DecisionRunResultV0:
        if type(config) is not DecisionBoardCliConfigV0:
            return _failed(DecisionRunIssueCodeV0.PREPARATION_INVALID)
        try:
            loaded = self.request_loader.load(config)
        except DecisionBoardAdapterUnavailableError:
            return _failed(DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE)
        except Exception:
            return _failed(DecisionRunIssueCodeV0.INTERNAL_ERROR)
        try:
            request = create_decision_run_request_v0(existing=loaded)
        except Exception:
            return _failed(DecisionRunIssueCodeV0.PREPARATION_INVALID)
        if not _matches_cli_identity(request, config):
            return _failed(DecisionRunIssueCodeV0.PREPARATION_INVALID)
        return DecisionBoardRunnerV0(
            preparer=self.preparer,
            enricher=self.enricher,
            report_dir=config.report_dir,
            uploader=self.uploader,
        ).run(request)


def _matches_cli_identity(
    request: DecisionRunRequestV0,
    config: DecisionBoardCliConfigV0,
) -> bool:
    return (
        request.run_kind is config.run_kind
        and request.run_id == config.run_id
        and request.idempotency_key == config.idempotency_key
        and request.created_at == config.created_at
        and request.sealed_input_hash == config.sealed_input_hash
        and request.upload_mode is config.upload_mode
    )


def _failed(issue_code: DecisionRunIssueCodeV0) -> DecisionRunResultV0:
    return create_decision_run_failed_v0(issue_code=issue_code)


__all__ = [
    "DecisionBoardAdapterUnavailableError",
    "DecisionBoardProductionAdapterV0",
    "DecisionRunRequestLoaderV0",
]
