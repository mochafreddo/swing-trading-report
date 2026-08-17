"""Explicit live-shadow composition that preserves the sealed runner boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sab.research.deadline import Deadline

from .batch_evidence import (
    BatchDecisionEvidenceBlockedV0,
    BatchDecisionEvidenceBuilderV0,
    BatchDecisionEvidenceError,
    BatchDecisionEvidenceSourceV0,
)
from .cli import DecisionBoardCliConfigV0
from .production_adapter import (
    DecisionBoardAdapterUnavailableError,
    PublicDecisionItemEnricherV0,
    SealedDecisionRunPreparerV0,
    SealedDecisionRunRequestLoaderV0,
    _matches_cli_identity,
)
from .results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    create_decision_run_failed_v0,
)
from .runner import (
    DecisionBoardRunnerV0,
    DecisionReportUploaderV0,
    DecisionRunPreparerV0,
    DecisionRunRequestV0,
    create_decision_run_request_v0,
    create_run_shared_blocked_v0,
)


class _SharedBlockedPreparerV0:
    def prepare(self, request: DecisionRunRequestV0) -> object:
        del request
        return create_run_shared_blocked_v0(
            DecisionRunIssueCodeV0.SHARED_PREFLIGHT_UNAVAILABLE
        )


@dataclass(frozen=True, slots=True)
class DecisionBoardLiveAdapterV0:
    """Load once, research once as a batch, then reuse the proven local runner."""

    request_loader: SealedDecisionRunRequestLoaderV0
    evidence_builder: BatchDecisionEvidenceBuilderV0
    uploader: DecisionReportUploaderV0 | None = None

    def __post_init__(self) -> None:
        if (
            type(self.request_loader) is not SealedDecisionRunRequestLoaderV0
            or type(self.evidence_builder) is not BatchDecisionEvidenceBuilderV0
            or not callable(
                getattr(self.request_loader.source, "load_sealed_request", None)
            )
        ):
            raise DecisionBoardAdapterUnavailableError(
                "live Decision Board dependencies are unavailable"
            )
        if self.uploader is not None and not callable(
            getattr(self.uploader, "upload", None)
        ):
            raise DecisionBoardAdapterUnavailableError(
                "live Decision Board uploader is unavailable"
            )

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
        try:
            evidence = asyncio.run(
                self.evidence_builder.build(
                    request,
                    deadline=Deadline.start(),
                )
            )
        except BatchDecisionEvidenceError:
            return _failed(DecisionRunIssueCodeV0.INTERNAL_ERROR)
        except Exception:
            return _failed(DecisionRunIssueCodeV0.INTERNAL_ERROR)
        if type(evidence) is BatchDecisionEvidenceBlockedV0:
            preparer: DecisionRunPreparerV0 = _SharedBlockedPreparerV0()
            source = BatchDecisionEvidenceSourceV0(records=())
        elif type(evidence) is BatchDecisionEvidenceSourceV0:
            preparer = SealedDecisionRunPreparerV0()
            source = evidence
        else:
            return _failed(DecisionRunIssueCodeV0.INTERNAL_ERROR)
        return DecisionBoardRunnerV0(
            preparer=preparer,
            enricher=PublicDecisionItemEnricherV0(source=source),
            report_dir=config.report_dir,
            uploader=self.uploader,
        ).run(request)


def _failed(issue_code: DecisionRunIssueCodeV0) -> DecisionRunResultV0:
    return create_decision_run_failed_v0(issue_code=issue_code)


__all__ = ["DecisionBoardLiveAdapterV0"]
