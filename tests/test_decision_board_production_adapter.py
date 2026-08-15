from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from sab.decision_board.claim_responses import ResponsesClaimVerifierV0
from sab.decision_board.claims import (
    ClaimRequestV0,
    ClaimValidationSucceededV0,
    validate_claim_v0,
)
from sab.decision_board.cli import (
    DecisionBoardCliConfigV0,
    execute_decision_board_cli_v0,
)
from sab.decision_board.compiler import (
    ApprovalStateV0,
    CompilerEvidenceKindV0,
    CompilerEvidenceV0,
    DependencyStateV0,
    EntryCompilerItemV0,
    EntrySignalStateV0,
    ExposureStateV0,
    ResearchStateV0,
)
from sab.decision_board.instruments import InstrumentRefV0
from sab.decision_board.production_adapter import (
    DecisionBoardAdapterUnavailableError,
    DecisionBoardProductionAdapterV0,
)
from sab.decision_board.results import (
    DecisionRunFailedV0,
    DecisionRunIssueCodeV0,
    DecisionRunPublishedV0,
    serialize_decision_run_result_v0,
)
from sab.decision_board.runner import (
    DecisionRunRequestV0,
    RunKindV0,
    UploadModeV0,
    create_decision_run_request_v0,
    create_run_prepared_v0,
)
from sab.research.contracts import (
    ResearchSourcePolicyV0,
    SourcePurposeV0,
    create_source_candidate_v0,
)
from sab.research.deadline import Deadline
from sab.research.source_safety import create_article_artifact_v0

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "decision_board"
    / "claim-verifier-responses-recorded.json"
)
CREATED_AT = datetime(2026, 8, 13, 1, 2, 3, tzinfo=UTC)
ARTICLE_TEXT = "Aurora beat guidance. Aurora beat guidance. Café demand is stable."


class _RequestLoader:
    def __init__(self, request: DecisionRunRequestV0) -> None:
        self.request = request
        self.configs: list[dict[str, str]] = []

    def load(self, config: DecisionBoardCliConfigV0) -> object:
        self.configs.append(config.to_public_dict())
        return self.request


class _Prepared:
    def prepare(self, request: DecisionRunRequestV0):
        return create_run_prepared_v0(request)


class _UnavailableLoader:
    def load(self, config: DecisionBoardCliConfigV0) -> object:
        del config
        raise DecisionBoardAdapterUnavailableError("PRIVATE-SENTINEL")


class _UnexpectedLoader:
    def load(self, config: DecisionBoardCliConfigV0) -> object:
        del config
        raise RuntimeError("PRIVATE-SENTINEL")


class _RecordedTransport:
    def __init__(self, response: object) -> None:
        self.response = copy.deepcopy(response)
        self.call_count = 0

    async def create_response(
        self,
        request: dict[str, object],
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        del request, deadline, timeout
        self.call_count += 1
        return copy.deepcopy(self.response)


class _RecordedEnricher:
    def __init__(
        self,
        *,
        transport: _RecordedTransport,
        model: str,
        claim: ClaimRequestV0,
        article: object,
        source: object,
        policy: ResearchSourcePolicyV0,
    ) -> None:
        self.transport = transport
        self.model = model
        self.claim = claim
        self.article = article
        self.source = source
        self.policy = policy

    def enrich(self, item: object, *, request: object) -> object:
        del request
        assert type(item) is EntryCompilerItemV0
        result = asyncio.run(
            validate_claim_v0(
                self.claim,
                self.article,  # type: ignore[arg-type]
                expected_source=self.source,  # type: ignore[arg-type]
                policy=self.policy,
                verifier=ResponsesClaimVerifierV0(
                    transport=self.transport,
                    model=self.model,
                ),
                deadline=Deadline.start(monotonic=lambda: 100.0),
            )
        )
        assert type(result) is ClaimValidationSucceededV0
        evidence = CompilerEvidenceV0.create(
            kind=CompilerEvidenceKindV0.SUPPORTIVE,
            validation=result.validation,
            request=self.claim,
            article=self.article,
            expected_source=self.source,
            policy=self.policy,
        )
        return EntryCompilerItemV0.create(
            item_id=item.item_id,
            instrument=item.instrument,
            item_state=item.item_state,
            identity_state=item.identity_state,
            signal_state=item.signal_state,
            mandate_state=item.mandate_state,
            price_state=item.price_state,
            exposure_state=item.exposure_state,
            research_state=ResearchStateV0.CLEAR,
            evidence=(evidence,),
        )


def _recorded_dependencies():
    recording = json.loads(FIXTURE.read_text(encoding="utf-8"))
    instrument = InstrumentRefV0(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-13",
    )
    policy = ResearchSourcePolicyV0()
    source = create_source_candidate_v0(
        instrument=instrument,
        title="Synthetic quarterly update",
        canonical_url="https://evidence.example/aurora/update",
        publisher="Synthetic Wire",
        published_at=CREATED_AT,
        purpose=SourcePurposeV0.ACTION_CHANGING,
    )
    article = create_article_artifact_v0(
        source=source,
        final_url="https://evidence.example/aurora/final-update",
        normalized_text=ARTICLE_TEXT,
        policy=policy,
    )
    claim = ClaimRequestV0(
        claim_id="claim-aurora-guidance",
        instrument=instrument,
        claim_text="Aurora raised its synthetic guidance.",
        action_changing=True,
    )
    item = EntryCompilerItemV0.create(
        item_id="entry-AUR.NAS",
        instrument=instrument,
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        signal_state=EntrySignalStateV0.READY_ENTER,
        mandate_state=DependencyStateV0.CURRENT,
        price_state=DependencyStateV0.CURRENT,
        exposure_state=ExposureStateV0.PASS,
        research_state=ResearchStateV0.COVERAGE_GAP,
    )
    request = create_decision_run_request_v0(
        run_kind=RunKindV0.ENTRY,
        run_id="entry-recorded-20260813T010203Z",
        idempotency_key="sha256:" + "1" * 64,
        created_at=CREATED_AT,
        sealed_input_hash="sha256:" + "2" * 64,
        items=(item,),
        selection=None,
        upload_mode=UploadModeV0.DISABLED,
        metadata={
            "policy_version": "decision-policy.v0",
            "researcher_version": "recorded-research-v0",
            "verifier_version": "decision-board-claim-verifier-v0",
        },
    )
    transport = _RecordedTransport(recording["cases"]["SUPPORTED"]["response"])
    enricher = _RecordedEnricher(
        transport=transport,
        model=recording["model"],
        claim=claim,
        article=article,
        source=source,
        policy=policy,
    )
    return request, transport, enricher


def test_production_adapter_runs_recorded_entry_without_live_provider(
    tmp_path: Path,
) -> None:
    request, transport, enricher = _recorded_dependencies()
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )
    loader = _RequestLoader(request)
    adapter = DecisionBoardProductionAdapterV0(
        request_loader=loader,
        preparer=_Prepared(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, adapter=adapter)

    assert type(result) is DecisionRunPublishedV0
    assert result.envelope["decision_payload"]["items"][0]["action"] == "BUY"
    assert result.local_path.parent == tmp_path
    assert transport.call_count == 1
    assert loader.configs == [config.to_public_dict()]


def test_production_adapter_rejects_cli_and_request_identity_mismatch(
    tmp_path: Path,
) -> None:
    request, _transport, enricher = _recorded_dependencies()
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id="entry-foreign-trigger",
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )
    adapter = DecisionBoardProductionAdapterV0(
        request_loader=_RequestLoader(request),
        preparer=_Prepared(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, adapter=adapter)

    assert type(result) is DecisionRunFailedV0
    assert result.issue_code is DecisionRunIssueCodeV0.PREPARATION_INVALID
    assert list(tmp_path.iterdir()) == []


def test_production_adapter_sanitizes_unavailable_and_unexpected_loader_errors(
    tmp_path: Path,
) -> None:
    request, _transport, enricher = _recorded_dependencies()
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )

    unavailable = execute_decision_board_cli_v0(
        config,
        adapter=DecisionBoardProductionAdapterV0(
            request_loader=_UnavailableLoader(),
            preparer=_Prepared(),
            enricher=enricher,
        ),
    )
    unexpected = execute_decision_board_cli_v0(
        config,
        adapter=DecisionBoardProductionAdapterV0(
            request_loader=_UnexpectedLoader(),
            preparer=_Prepared(),
            enricher=enricher,
        ),
    )

    assert serialize_decision_run_result_v0(unavailable) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert serialize_decision_run_result_v0(unexpected) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "INTERNAL_ERROR",
    }
    assert "PRIVATE-SENTINEL" not in repr((unavailable, unexpected))
