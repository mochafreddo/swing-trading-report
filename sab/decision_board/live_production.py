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
from .shadow_execution import (
    ShadowGateExecutionBindingV0,
    shadow_gate_binding_matches_request_v0,
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

    def execute(
        self,
        config: DecisionBoardCliConfigV0,
        *,
        binding: ShadowGateExecutionBindingV0,
    ) -> DecisionRunResultV0:
        if (
            type(config) is not DecisionBoardCliConfigV0
            or type(binding) is not ShadowGateExecutionBindingV0
        ):
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
        if not _matches_live_cli_identity(request, config):
            return _failed(DecisionRunIssueCodeV0.PREPARATION_INVALID)
        if not shadow_gate_binding_matches_request_v0(binding, request):
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
        try:
            request = _with_live_metadata(
                request,
                evidence.provider_metrics,
                gate_manifest_sha256=binding.manifest.manifest_sha256,
            )
        except Exception:
            return _failed(DecisionRunIssueCodeV0.INTERNAL_ERROR)
        return DecisionBoardRunnerV0(
            preparer=preparer,
            enricher=PublicDecisionItemEnricherV0(source=source),
            report_dir=config.report_dir,
            uploader=self.uploader,
        ).run(request)


def _failed(issue_code: DecisionRunIssueCodeV0) -> DecisionRunResultV0:
    return create_decision_run_failed_v0(issue_code=issue_code)


def _matches_live_cli_identity(
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


def _with_live_metadata(
    request: DecisionRunRequestV0,
    metrics: tuple[tuple[str, int], ...],
    *,
    gate_manifest_sha256: str,
) -> DecisionRunRequestV0:
    metadata = dict(request.metadata)
    metadata.update(dict(metrics))
    metadata["gate_manifest_sha256"] = gate_manifest_sha256
    return create_decision_run_request_v0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        items=request.items,
        selection=request.selection,
        upload_mode=request.upload_mode,
        metadata=metadata,
    )


__all__ = ["DecisionBoardLiveAdapterV0"]
