"""Invocation-wide Decision Board research and claim-evidence bridge."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sab.research.contracts import (
    ResearchInputV0,
    ResearchQuestionV0,
    ResearchSourcePolicyV0,
    SourcePurposeV0,
    copy_research_source_policy_v0,
)
from sab.research.deadline import Deadline
from sab.research.orchestrator import (
    EvidenceResearcherV0,
    ResearchCompletedV0,
    ResearchInputFailedV0,
    ResearchItemMalformedV0,
    ResearchItemNoUsableSourceV0,
    ResearchItemProviderFailedV0,
    ResearchItemSucceededV0,
    ResearchItemTimedOutV0,
    ResearchSharedBlockedV0,
)

from .claims import (
    ClaimRequestV0,
    ClaimValidationSucceededV0,
    ClaimValidationTimedOutV0,
    ClaimVerifierV0,
    validate_claim_v0,
)
from .compiler import (
    CompilerEvidenceKindV0,
    CompilerEvidenceV0,
    ResearchStateV0,
)
from .production_adapter import DecisionItemResearchOutcomeV0
from .runner import (
    DecisionItemEnrichmentRequestV0,
    DecisionRunRequestV0,
    RunKindV0,
    create_decision_run_request_v0,
)

_QUESTIONS = (
    ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,
    ResearchQuestionV0.MATERIAL_COUNTER_EVIDENCE,
    ResearchQuestionV0.ACTION_CHANGING_EVIDENCE,
)


class BatchDecisionEvidenceError(RuntimeError):
    """The batch evidence invocation could not produce safe item outcomes."""


@dataclass(frozen=True, slots=True)
class BatchDecisionEvidenceBlockedV0:
    """The shared article-verifier preflight blocked every selected item."""


@dataclass(frozen=True, slots=True)
class _OutcomeRecordV0:
    request: DecisionItemEnrichmentRequestV0
    outcome: DecisionItemResearchOutcomeV0


@dataclass(frozen=True, slots=True)
class BatchDecisionEvidenceSourceV0:
    """Serve only invocation-owned outcomes by exact public item identity."""

    records: tuple[_OutcomeRecordV0, ...]

    def research(self, request: DecisionItemEnrichmentRequestV0) -> object:
        if type(request) is not DecisionItemEnrichmentRequestV0:
            raise TypeError("batch evidence request must be exact V0")
        matches = [record for record in self.records if record.request == request]
        if len(matches) != 1:
            raise TypeError("batch evidence request is outside the selected universe")
        record = matches[0]
        return DecisionItemResearchOutcomeV0.create(
            research_state=record.outcome.research_state,
            evidence=record.outcome.evidence,
        )


@dataclass(frozen=True, slots=True)
class BatchDecisionEvidenceBuilderV0:
    """Own one research batch plus all claim checks under one shared deadline."""

    researcher: EvidenceResearcherV0
    claim_verifier: ClaimVerifierV0
    source_policy: ResearchSourcePolicyV0 = field(
        default_factory=ResearchSourcePolicyV0
    )

    def __post_init__(self) -> None:
        if type(self.researcher) is not EvidenceResearcherV0 or not callable(
            getattr(self.claim_verifier, "verify", None)
        ):
            raise TypeError("batch evidence dependencies are unavailable")
        policy = copy_research_source_policy_v0(self.source_policy)
        if policy is None:
            raise TypeError("batch evidence source policy is invalid")
        object.__setattr__(self, "source_policy", policy)

    async def build(
        self,
        request: DecisionRunRequestV0,
        *,
        deadline: Deadline,
    ) -> BatchDecisionEvidenceSourceV0 | BatchDecisionEvidenceBlockedV0:
        if type(deadline) is not Deadline:
            raise BatchDecisionEvidenceError("batch deadline is invalid")
        try:
            trusted_request = create_decision_run_request_v0(existing=request)
        except Exception as exc:
            raise BatchDecisionEvidenceError("batch request is invalid") from exc
        selected_ids = (
            {item.item_id for item in trusted_request.items}
            if trusted_request.run_kind is RunKindV0.ENTRY
            else set(
                trusted_request.selection.selected_item_ids
                if trusted_request.selection is not None
                else ()
            )
        )
        selected_items = tuple(
            item for item in trusted_request.items if item.item_id in selected_ids
        )
        if not selected_items:
            return BatchDecisionEvidenceSourceV0(records=())
        research_input = ResearchInputV0(
            instruments=tuple(item.instrument for item in selected_items),
            questions=_QUESTIONS,
            source_policy=self.source_policy,
        )
        researched = await self.researcher.research_with_deadline(
            research_input,
            deadline=deadline,
        )
        if type(researched) is ResearchSharedBlockedV0:
            return BatchDecisionEvidenceBlockedV0()
        if type(researched) is ResearchInputFailedV0:
            raise BatchDecisionEvidenceError("batch research input failed")
        if type(researched) is not ResearchCompletedV0:
            raise BatchDecisionEvidenceError("batch research result is invalid")
        records: list[_OutcomeRecordV0] = []
        for item, research_item in zip(
            selected_items,
            researched.items,
            strict=True,
        ):
            outcome = await self._build_outcome(
                item_id=item.item_id,
                run_kind=trusted_request.run_kind,
                research_item=research_item,
                deadline=deadline,
            )
            records.append(
                _OutcomeRecordV0(
                    request=DecisionItemEnrichmentRequestV0(
                        run_kind=trusted_request.run_kind,
                        item_id=item.item_id,
                        instrument=item.instrument,
                    ),
                    outcome=outcome,
                )
            )
        return BatchDecisionEvidenceSourceV0(records=tuple(records))

    async def _build_outcome(
        self,
        *,
        item_id: str,
        run_kind: RunKindV0,
        research_item: object,
        deadline: Deadline,
    ) -> DecisionItemResearchOutcomeV0:
        del run_kind
        if type(research_item) is ResearchItemNoUsableSourceV0:
            return _outcome(ResearchStateV0.COVERAGE_GAP)
        if type(research_item) is ResearchItemTimedOutV0:
            return _outcome(ResearchStateV0.TIMEOUT)
        if type(research_item) in {
            ResearchItemMalformedV0,
            ResearchItemProviderFailedV0,
        }:
            return _outcome(ResearchStateV0.FAILED)
        if type(research_item) is not ResearchItemSucceededV0:
            raise BatchDecisionEvidenceError("batch item result is invalid")
        evidence: list[CompilerEvidenceV0] = []
        claim_failed = False
        claim_timed_out = False
        action_changing_coverage = False
        for index, article in enumerate(research_item.articles):
            source = article.source
            action_changing = source.purpose in {
                SourcePurposeV0.OPPOSING,
                SourcePurposeV0.ACTION_CHANGING,
            }
            action_changing_coverage = action_changing_coverage or action_changing
            claim = ClaimRequestV0(
                claim_id=_claim_id(item_id, source.canonical_url, index),
                instrument=research_item.instrument,
                claim_text=source.title,
                action_changing=action_changing,
            )
            validation = await validate_claim_v0(
                claim,
                article,
                expected_source=source,
                policy=self.source_policy,
                verifier=self.claim_verifier,
                deadline=deadline,
                operation_timeout_seconds=(
                    self.source_policy.operation_timeout_seconds
                ),
            )
            if type(validation) is ClaimValidationSucceededV0:
                evidence.append(
                    CompilerEvidenceV0.create(
                        kind=(
                            CompilerEvidenceKindV0.MATERIAL_ADVERSE
                            if source.purpose is SourcePurposeV0.OPPOSING
                            else CompilerEvidenceKindV0.SUPPORTIVE
                        ),
                        validation=validation.validation,
                        request=claim,
                        article=article,
                        expected_source=source,
                        policy=self.source_policy,
                    )
                )
            elif type(validation) is ClaimValidationTimedOutV0:
                claim_timed_out = True
            else:
                claim_failed = True
        state = (
            ResearchStateV0.TIMEOUT
            if claim_timed_out
            else ResearchStateV0.FAILED
            if claim_failed
            else ResearchStateV0.CLEAR
            if action_changing_coverage
            else ResearchStateV0.COVERAGE_GAP
        )
        return _outcome(state, evidence=tuple(evidence))


def _claim_id(item_id: str, source_url: str, index: int) -> str:
    digest = hashlib.sha256(f"{item_id}\0{source_url}\0{index}".encode()).hexdigest()[
        :24
    ]
    return f"claim-{digest}"


def _outcome(
    state: ResearchStateV0,
    *,
    evidence: tuple[CompilerEvidenceV0, ...] = (),
) -> DecisionItemResearchOutcomeV0:
    return DecisionItemResearchOutcomeV0.create(
        research_state=state,
        evidence=evidence,
    )


__all__ = [
    "BatchDecisionEvidenceBlockedV0",
    "BatchDecisionEvidenceBuilderV0",
    "BatchDecisionEvidenceError",
    "BatchDecisionEvidenceSourceV0",
]
