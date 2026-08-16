"""Dependency-injected production composition for Decision Board V0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .cli import DecisionBoardCliConfigV0
from .compiler import (
    CompilerEvidenceV0,
    EntryCompilerItemV0,
    HoldingCompilerItemV0,
    ResearchStateV0,
)
from .results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    create_decision_run_failed_v0,
)
from .runner import (
    DecisionBoardRunnerV0,
    DecisionItemEnricherV0,
    DecisionItemEnrichmentRequestV0,
    DecisionReportUploaderV0,
    DecisionRunPreparerV0,
    DecisionRunRequestV0,
    create_decision_run_request_v0,
    create_run_prepared_v0,
)


class DecisionBoardAdapterUnavailableError(RuntimeError):
    """The approved runtime dependencies are not connected."""


class DecisionRunRequestLoaderV0(Protocol):
    """Load one sealed request without widening the CLI authority boundary."""

    def load(self, config: DecisionBoardCliConfigV0) -> object: ...


class DecisionRunRequestSourceV0(Protocol):
    """Resolve one sealed request from sanitized CLI identity only."""

    def load_sealed_request(self, identity: dict[str, str]) -> object: ...


@dataclass(frozen=True, slots=True)
class SealedDecisionRunRequestLoaderV0:
    """Strip local path authority before crossing the request-source boundary."""

    source: DecisionRunRequestSourceV0

    def load(self, config: DecisionBoardCliConfigV0) -> object:
        if type(config) is not DecisionBoardCliConfigV0:
            raise DecisionBoardAdapterUnavailableError(
                "the Decision Board CLI configuration is unavailable"
            )
        return self.source.load_sealed_request(config.to_public_dict())


class SealedDecisionRunPreparerV0:
    """Open the runner only for one unchanged factory-issued request."""

    def prepare(self, request: DecisionRunRequestV0) -> object:
        return create_run_prepared_v0(request)


@dataclass(frozen=True, slots=True)
class DecisionItemResearchOutcomeV0:
    """Research-only fields returned across the external evidence boundary."""

    research_state: ResearchStateV0
    evidence: tuple[CompilerEvidenceV0, ...]

    @classmethod
    def create(
        cls,
        *,
        research_state: ResearchStateV0,
        evidence: tuple[CompilerEvidenceV0, ...] = (),
    ) -> DecisionItemResearchOutcomeV0:
        if type(research_state) is not ResearchStateV0:
            raise TypeError("research_state must be an exact V0 enum")
        if type(evidence) is not tuple or any(
            type(item) is not CompilerEvidenceV0 for item in evidence
        ):
            raise TypeError("evidence must contain exact V0 compiler evidence")
        return cls(research_state=research_state, evidence=evidence)


class DecisionItemEvidenceSourceV0(Protocol):
    """Resolve one recorded item outcome from its public request only.

    Live research needs a separate batch owner for shared budgets and source caps.
    """

    def research(self, request: DecisionItemEnrichmentRequestV0) -> object: ...


@dataclass(frozen=True, slots=True)
class PublicDecisionItemEnricherV0:
    """Rebuild an item while keeping external research away from sealed facts."""

    source: DecisionItemEvidenceSourceV0

    def enrich(self, item: object, *, request: object) -> object:
        if type(request) is not DecisionItemEnrichmentRequestV0:
            raise TypeError("enrichment request must be an exact public V0 request")
        outcome = self.source.research(request)
        if type(outcome) is not DecisionItemResearchOutcomeV0:
            raise TypeError("research outcome must be an exact V0 value")
        research_state = outcome.research_state
        evidence = outcome.evidence
        if type(research_state) is not ResearchStateV0:
            raise TypeError("research outcome state is invalid")
        if type(evidence) is not tuple or any(
            type(value) is not CompilerEvidenceV0 for value in evidence
        ):
            raise TypeError("research outcome evidence is invalid")
        if type(item) is EntryCompilerItemV0:
            return EntryCompilerItemV0.create(
                item_id=item.item_id,
                instrument=item.instrument,
                item_state=item.item_state,
                identity_state=item.identity_state,
                signal_state=item.signal_state,
                mandate_state=item.mandate_state,
                price_state=item.price_state,
                exposure_state=item.exposure_state,
                research_state=research_state,
                evidence=evidence,
            )
        if type(item) is HoldingCompilerItemV0:
            return HoldingCompilerItemV0.create(
                item_id=item.item_id,
                instrument=item.instrument,
                item_state=item.item_state,
                identity_state=item.identity_state,
                hard_exit_state=item.hard_exit_state,
                broker_state=item.broker_state,
                candle_state=item.candle_state,
                rule_state=item.rule_state,
                research_state=research_state,
                research_priority=item.research_priority,
                research_order=item.research_order,
                evidence=evidence,
            )
        raise TypeError("compiler item must use an exact V0 lane")


@dataclass(frozen=True, slots=True)
class DecisionBoardProductionComponentsV0:
    """Least-authority wrapper bundle for offline production composition."""

    request_loader: SealedDecisionRunRequestLoaderV0
    preparer: SealedDecisionRunPreparerV0
    enricher: PublicDecisionItemEnricherV0
    uploader: DecisionReportUploaderV0 | None = None


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
            _validate_least_authority_sources(self.request_loader, self.enricher)
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


def compose_decision_board_production_adapter_v0(
    components: DecisionBoardProductionComponentsV0,
) -> DecisionBoardProductionAdapterV0:
    """Bind exact offline wrappers without reading env or credentials."""

    if type(components) is not DecisionBoardProductionComponentsV0:
        raise DecisionBoardAdapterUnavailableError(
            "production components must use the exact V0 bundle"
        )
    if (
        type(components.request_loader) is not SealedDecisionRunRequestLoaderV0
        or type(components.preparer) is not SealedDecisionRunPreparerV0
        or type(components.enricher) is not PublicDecisionItemEnricherV0
    ):
        raise DecisionBoardAdapterUnavailableError(
            "production components must use the least-authority V0 wrappers"
        )
    _validate_least_authority_sources(
        components.request_loader,
        components.enricher,
    )
    if components.uploader is not None and not callable(
        getattr(components.uploader, "upload", None)
    ):
        raise DecisionBoardAdapterUnavailableError(
            "the configured report uploader is unavailable"
        )
    return DecisionBoardProductionAdapterV0(
        request_loader=components.request_loader,
        preparer=components.preparer,
        enricher=components.enricher,
        uploader=components.uploader,
    )


def _validate_least_authority_sources(
    request_loader: DecisionRunRequestLoaderV0,
    enricher: DecisionItemEnricherV0,
) -> None:
    if type(request_loader) is SealedDecisionRunRequestLoaderV0 and not callable(
        getattr(request_loader.source, "load_sealed_request", None)
    ):
        raise DecisionBoardAdapterUnavailableError(
            "the sealed request source is unavailable"
        )
    if type(enricher) is PublicDecisionItemEnricherV0 and not callable(
        getattr(enricher.source, "research", None)
    ):
        raise DecisionBoardAdapterUnavailableError(
            "the public evidence source is unavailable"
        )


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
    "DecisionBoardProductionComponentsV0",
    "DecisionItemEvidenceSourceV0",
    "DecisionItemResearchOutcomeV0",
    "DecisionRunRequestLoaderV0",
    "DecisionRunRequestSourceV0",
    "PublicDecisionItemEnricherV0",
    "SealedDecisionRunPreparerV0",
    "SealedDecisionRunRequestLoaderV0",
    "compose_decision_board_production_adapter_v0",
]
