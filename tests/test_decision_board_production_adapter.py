from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
    HardExitStateV0,
    HoldingCompilerItemV0,
    ResearchStateV0,
)
from sab.decision_board.instruments import InstrumentRefV0
from sab.decision_board.policy import select_holding_research_v0
from sab.decision_board.production_adapter import (
    DecisionBoardAdapterUnavailableError,
    DecisionBoardProductionAdapterV0,
    DecisionBoardProductionComponentsV0,
    DecisionItemResearchOutcomeV0,
    PublicDecisionItemEnricherV0,
    SealedDecisionRunPreparerV0,
    SealedDecisionRunRequestLoaderV0,
)
from sab.decision_board.results import (
    DecisionRunFailedV0,
    DecisionRunIssueCodeV0,
    DecisionRunPublishedV0,
    serialize_decision_run_result_v0,
)
from sab.decision_board.runner import (
    DecisionItemEnrichmentRequestV0,
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


class _RecordedRequestSource:
    def __init__(
        self,
        request: DecisionRunRequestV0,
        expected_identity: dict[str, str],
    ) -> None:
        self.request = request
        self.expected_identity = expected_identity
        self.identities: list[dict[str, str]] = []

    def load_sealed_request(self, identity: dict[str, str]) -> object:
        assert identity == self.expected_identity
        assert "report_dir" not in identity
        self.identities.append(identity)
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


class _ExplodingCapability:
    @property
    def upload(self) -> object:
        raise RuntimeError("PRIVATE-COMPOSITION-SENTINEL")


class _NonCallableUploader:
    upload = None


class _ExplodingRequestCapability:
    @property
    def load_sealed_request(self) -> object:
        raise RuntimeError("PRIVATE-NESTED-SENTINEL")


class _ExplodingEvidenceCapability:
    @property
    def research(self) -> object:
        raise RuntimeError("PRIVATE-NESTED-SENTINEL")


class _UnavailableRequestSource:
    def load_sealed_request(self, identity: dict[str, str]) -> object:
        del identity
        raise DecisionBoardAdapterUnavailableError("PRIVATE-SOURCE-SENTINEL")


class _UnexpectedRequestSource:
    def load_sealed_request(self, identity: dict[str, str]) -> object:
        del identity
        raise RuntimeError("PRIVATE-SOURCE-SENTINEL")


class _RawEnricher:
    def enrich(self, item: object, *, request: object) -> object:
        del request
        return item


class _LegacyEntryEnricher:
    def enrich(self, item: object, *, request: object) -> object:
        assert type(item) is EntryCompilerItemV0
        assert type(request) is DecisionItemEnrichmentRequestV0
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
        )


class _SuccessfulUploader:
    def upload(self, *, local_path: Path, storage_key: str) -> str:
        assert local_path.is_file()
        return storage_key


@dataclass(frozen=True)
class _StaticEvidenceSource:
    outcome: object

    def research(self, request: DecisionItemEnrichmentRequestV0) -> object:
        assert request.to_public_dict() == {
            "run_kind": "HOLDING",
            "item_id": "holding-AUR.NAS",
            "instrument": {
                "market": "US",
                "canonical_ticker": "AUR.NAS",
                "exchange": "NASDAQ",
                "company_name": "Aurora Synthetic Systems",
                "identity_source": "synthetic-directory",
                "identity_version": "fixture-2026-08-13",
            },
        }
        return self.outcome


class _UntypedEvidenceSource:
    def research(self, request: DecisionItemEnrichmentRequestV0) -> object:
        assert request.run_kind is RunKindV0.ENTRY
        return {"research_state": "CLEAR"}


@dataclass(frozen=True)
class _ReturningEvidenceSource:
    outcome: object

    def research(self, request: DecisionItemEnrichmentRequestV0) -> object:
        assert type(request) is DecisionItemEnrichmentRequestV0
        return self.outcome


class _ExplodingEvidenceSource:
    def research(self, request: DecisionItemEnrichmentRequestV0) -> object:
        del request
        raise RuntimeError("PRIVATE-EVIDENCE-SENTINEL")


class _RecordedTransport:
    def __init__(self, response: object) -> None:
        self.response = copy.deepcopy(response)

    async def create_response(
        self,
        request: dict[str, object],
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        del request, deadline, timeout
        return copy.deepcopy(self.response)


class _RecordedEvidenceSource:
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

    def research(self, request: DecisionItemEnrichmentRequestV0) -> object:
        assert type(request) is DecisionItemEnrichmentRequestV0
        assert request.to_public_dict() == {
            "run_kind": "ENTRY",
            "item_id": "entry-AUR.NAS",
            "instrument": {
                "market": "US",
                "canonical_ticker": "AUR.NAS",
                "exchange": "NASDAQ",
                "company_name": "Aurora Synthetic Systems",
                "identity_source": "synthetic-directory",
                "identity_version": "fixture-2026-08-13",
            },
        }
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
        return DecisionItemResearchOutcomeV0.create(
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
    enricher = PublicDecisionItemEnricherV0(
        source=_RecordedEvidenceSource(
            transport=transport,
            model=recording["model"],
            claim=claim,
            article=article,
            source=source,
            policy=policy,
        )
    )
    return request, transport, enricher


def test_production_adapter_runs_recorded_entry_without_live_provider(
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
    loader = _RequestLoader(request)
    adapter = DecisionBoardProductionAdapterV0(
        request_loader=loader,
        preparer=_Prepared(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, adapter=adapter)

    assert type(result) is DecisionRunPublishedV0
    item = result.envelope["decision_payload"]["items"][0]
    assert item["action"] == "BUY"
    assert item["evidence"][0]["claim_id"] == "claim-aurora-guidance"
    assert item["evidence"][0]["source_url"] == (
        "https://evidence.example/aurora/final-update"
    )
    assert item["evidence"][0]["supporting_span"] == "Aurora beat guidance."
    assert result.local_path.parent == tmp_path
    assert loader.configs == [config.to_public_dict()]


def test_direct_adapter_preserves_protocol_only_legacy_enricher(tmp_path: Path) -> None:
    request, _transport, _enricher = _recorded_dependencies()
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )
    adapter = DecisionBoardProductionAdapterV0(
        request_loader=_RequestLoader(request),
        preparer=_Prepared(),
        enricher=_LegacyEntryEnricher(),
    )

    result = execute_decision_board_cli_v0(config, adapter=adapter)

    assert type(result) is DecisionRunPublishedV0
    assert result.envelope["decision_payload"]["items"][0]["action"] == "BUY"


def test_production_composition_publishes_recorded_entry_through_cli(
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
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            _RecordedRequestSource(request, config.to_public_dict())
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert type(result) is DecisionRunPublishedV0
    assert result.envelope["decision_payload"]["items"][0]["action"] == "BUY"
    assert (
        result.local_path.read_bytes()
        == json.dumps(
            result.envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


def test_production_composition_fails_closed_when_capability_is_missing(
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
    components = DecisionBoardProductionComponentsV0(
        request_loader=object(),  # type: ignore[arg-type]
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_non_exact_component_bundle_as_config_unavailable(
    tmp_path: Path,
) -> None:
    request, _transport, _enricher = _recorded_dependencies()
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )

    result = execute_decision_board_cli_v0(
        config,
        components=object(),  # type: ignore[arg-type]
    )

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert list(tmp_path.iterdir()) == []


def test_composition_rejects_non_callable_uploader_before_loading(
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
    source = _RecordedRequestSource(request, config.to_public_dict())
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(source),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
        uploader=_NonCallableUploader(),  # type: ignore[arg-type]
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert source.identities == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("unsafe_capability", ["loader", "preparer", "enricher"])
def test_production_composition_rejects_raw_authority_capability_before_loading(
    tmp_path: Path,
    unsafe_capability: str,
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
    source = _RecordedRequestSource(request, config.to_public_dict())
    raw_loader = _RequestLoader(request)
    loader: object = SealedDecisionRunRequestLoaderV0(source)
    preparer: object = SealedDecisionRunPreparerV0()
    selected_enricher: object = enricher
    if unsafe_capability == "loader":
        loader = raw_loader
    elif unsafe_capability == "preparer":
        preparer = _Prepared()
    else:
        selected_enricher = _RawEnricher()
    components = DecisionBoardProductionComponentsV0(
        request_loader=loader,  # type: ignore[arg-type]
        preparer=preparer,  # type: ignore[arg-type]
        enricher=selected_enricher,  # type: ignore[arg-type]
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert source.identities == []
    assert raw_loader.configs == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("missing_source", ["request", "evidence"])
def test_production_composition_rejects_missing_nested_source_before_loading(
    tmp_path: Path,
    missing_source: str,
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
    source = _RecordedRequestSource(request, config.to_public_dict())
    loader = SealedDecisionRunRequestLoaderV0(source)
    if missing_source == "request":
        loader = SealedDecisionRunRequestLoaderV0(object())  # type: ignore[arg-type]
    if missing_source == "evidence":
        enricher = PublicDecisionItemEnricherV0(object())  # type: ignore[arg-type]
    components = DecisionBoardProductionComponentsV0(
        request_loader=loader,
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert source.identities == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("exploding_source", ["request", "evidence"])
def test_composition_sanitizes_exploding_nested_capability_getters(
    tmp_path: Path,
    exploding_source: str,
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
    source = _RecordedRequestSource(request, config.to_public_dict())
    loader = SealedDecisionRunRequestLoaderV0(source)
    if exploding_source == "request":
        loader = SealedDecisionRunRequestLoaderV0(
            _ExplodingRequestCapability()  # type: ignore[arg-type]
        )
    if exploding_source == "evidence":
        enricher = PublicDecisionItemEnricherV0(
            _ExplodingEvidenceCapability()  # type: ignore[arg-type]
        )
    components = DecisionBoardProductionComponentsV0(
        request_loader=loader,
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "INTERNAL_ERROR",
    }
    assert "PRIVATE-NESTED-SENTINEL" not in repr(result)
    assert source.identities == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("missing_source", ["request", "evidence"])
def test_direct_adapter_rejects_missing_nested_source_before_loading(
    tmp_path: Path,
    missing_source: str,
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
    source = _RecordedRequestSource(request, config.to_public_dict())
    loader = SealedDecisionRunRequestLoaderV0(source)
    if missing_source == "request":
        loader = SealedDecisionRunRequestLoaderV0(object())  # type: ignore[arg-type]
    if missing_source == "evidence":
        enricher = PublicDecisionItemEnricherV0(object())  # type: ignore[arg-type]
    adapter = DecisionBoardProductionAdapterV0(
        request_loader=loader,
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, adapter=adapter)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    assert source.identities == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("source", "expected_issue"),
    [
        (_UnavailableRequestSource(), "CONFIG_UNAVAILABLE"),
        (_UnexpectedRequestSource(), "INTERNAL_ERROR"),
    ],
)
def test_sealed_request_source_errors_are_sanitized(
    tmp_path: Path,
    source: object,
    expected_issue: str,
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
    adapter = DecisionBoardProductionAdapterV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            source  # type: ignore[arg-type]
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(config, adapter=adapter)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": expected_issue,
    }
    assert "PRIVATE-SOURCE-SENTINEL" not in repr(result)
    assert list(tmp_path.iterdir()) == []


def test_production_composition_sanitizes_unexpected_capability_error(
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
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            _RecordedRequestSource(request, config.to_public_dict())
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
        uploader=_ExplodingCapability(),  # type: ignore[arg-type]
    )

    try:
        result = execute_decision_board_cli_v0(config, components=components)
    except RuntimeError as exc:
        assert "PRIVATE-COMPOSITION-SENTINEL" not in str(exc)
        raise AssertionError("composition errors must not escape the CLI") from exc

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "INTERNAL_ERROR",
    }
    assert "PRIVATE-COMPOSITION-SENTINEL" not in repr(result)
    assert list(tmp_path.iterdir()) == []


def test_production_composition_rejects_ambiguous_adapter_authority(
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
    loader = _RequestLoader(request)
    adapter = DecisionBoardProductionAdapterV0(
        request_loader=loader,
        preparer=_Prepared(),
        enricher=enricher,
    )
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            _RecordedRequestSource(request, config.to_public_dict())
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
    )

    result = execute_decision_board_cli_v0(
        config,
        adapter=adapter,
        components=components,
    )

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "PREPARATION_INVALID",
    }
    assert list(tmp_path.iterdir()) == []


def test_production_composition_preserves_optional_upload_identity(
    tmp_path: Path,
) -> None:
    baseline, _transport, enricher = _recorded_dependencies()
    request = create_decision_run_request_v0(
        run_kind=baseline.run_kind,
        run_id=baseline.run_id,
        idempotency_key=baseline.idempotency_key,
        created_at=baseline.created_at,
        sealed_input_hash=baseline.sealed_input_hash,
        items=baseline.items,
        selection=baseline.selection,
        upload_mode=UploadModeV0.OPTIONAL,
        metadata=baseline.metadata,
    )
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            _RecordedRequestSource(request, config.to_public_dict())
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=enricher,
        uploader=_SuccessfulUploader(),
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert type(result) is DecisionRunPublishedV0
    assert result.storage_key == (
        "2026/08/2026-08-13.decision-board.entry."
        "entry-recorded-20260813T010203Z."
        f"{'1' * 64}.json"
    )


def test_research_outcome_factory_rejects_non_exact_state() -> None:
    with pytest.raises(TypeError, match="exact V0 enum"):
        DecisionItemResearchOutcomeV0.create(
            research_state="CLEAR",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("invalid_evidence", [[], (object(),)])
def test_research_outcome_factory_rejects_invalid_evidence(
    invalid_evidence: object,
) -> None:
    with pytest.raises(TypeError, match="exact V0 compiler evidence"):
        DecisionItemResearchOutcomeV0.create(
            research_state=ResearchStateV0.CLEAR,
            evidence=invalid_evidence,  # type: ignore[arg-type]
        )


def test_public_enricher_rejects_non_exact_request_and_unsupported_item() -> None:
    baseline, _transport, _enricher = _recorded_dependencies()
    item = baseline.items[0]
    public_request = DecisionItemEnrichmentRequestV0(
        run_kind=baseline.run_kind,
        item_id=item.item_id,
        instrument=item.instrument,
    )
    enricher = PublicDecisionItemEnricherV0(
        _ReturningEvidenceSource(
            DecisionItemResearchOutcomeV0.create(research_state=ResearchStateV0.CLEAR)
        )
    )

    with pytest.raises(TypeError, match="exact public V0 request"):
        enricher.enrich(item, request=object())
    with pytest.raises(TypeError, match="exact V0 lane"):
        enricher.enrich(object(), request=public_request)


@pytest.mark.parametrize("mutated_field", ["research_state", "evidence"])
def test_public_enricher_rejects_mutated_exact_outcome(mutated_field: str) -> None:
    baseline, _transport, _enricher = _recorded_dependencies()
    item = baseline.items[0]
    public_request = DecisionItemEnrichmentRequestV0(
        run_kind=baseline.run_kind,
        item_id=item.item_id,
        instrument=item.instrument,
    )
    outcome = DecisionItemResearchOutcomeV0.create(research_state=ResearchStateV0.CLEAR)
    if mutated_field == "research_state":
        object.__setattr__(outcome, mutated_field, "CLEAR")
    else:
        object.__setattr__(outcome, mutated_field, [])
    enricher = PublicDecisionItemEnricherV0(_ReturningEvidenceSource(outcome))

    with pytest.raises(TypeError, match="research outcome"):
        enricher.enrich(item, request=public_request)


@pytest.mark.parametrize(
    ("hard_exit_state", "expected_action"),
    [
        (HardExitStateV0.NONE, "HOLD"),
        (HardExitStateV0.HARD_STOP, "SELL"),
    ],
)
def test_public_enricher_preserves_holding_facts_through_cli(
    tmp_path: Path,
    hard_exit_state: HardExitStateV0,
    expected_action: str,
) -> None:
    baseline, _transport, _enricher = _recorded_dependencies()
    instrument = baseline.items[0].instrument
    holding = HoldingCompilerItemV0.create(
        item_id="holding-AUR.NAS",
        instrument=instrument,
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        hard_exit_state=hard_exit_state,
        broker_state=DependencyStateV0.CURRENT,
        candle_state=DependencyStateV0.CURRENT,
        rule_state=DependencyStateV0.CURRENT,
        research_state=ResearchStateV0.COVERAGE_GAP,
        research_priority=1,
        research_order="aurora",
    )
    request = create_decision_run_request_v0(
        run_kind=RunKindV0.HOLDING,
        run_id="holding-recorded-20260813T010203Z",
        idempotency_key="sha256:" + "3" * 64,
        created_at=CREATED_AT,
        sealed_input_hash="sha256:" + "4" * 64,
        items=(holding,),
        selection=select_holding_research_v0((holding,)),
        upload_mode=UploadModeV0.DISABLED,
        metadata={
            "policy_version": "decision-policy.v0",
            "researcher_version": "recorded-research-v0",
            "verifier_version": "decision-board-claim-verifier-v0",
        },
    )
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            _RecordedRequestSource(request, config.to_public_dict())
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=PublicDecisionItemEnricherV0(
            source=_StaticEvidenceSource(
                DecisionItemResearchOutcomeV0.create(
                    research_state=ResearchStateV0.CLEAR
                )
            )
        ),
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert type(result) is DecisionRunPublishedV0
    assert result.envelope["decision_payload"]["items"][0]["action"] == expected_action


def test_public_enricher_rejects_untyped_research_outcome(tmp_path: Path) -> None:
    request, _transport, _enricher = _recorded_dependencies()
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            _RecordedRequestSource(request, config.to_public_dict())
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=PublicDecisionItemEnricherV0(source=_UntypedEvidenceSource()),
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "ITEM_ENRICHMENT_INVALID",
    }
    assert list(tmp_path.iterdir()) == []


def test_public_enricher_contains_evidence_source_errors_without_write(
    tmp_path: Path,
) -> None:
    request, _transport, _enricher = _recorded_dependencies()
    config = DecisionBoardCliConfigV0(
        run_kind=request.run_kind,
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at=request.created_at,
        sealed_input_hash=request.sealed_input_hash,
        upload_mode=request.upload_mode,
        report_dir=tmp_path,
    )
    components = DecisionBoardProductionComponentsV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            _RecordedRequestSource(request, config.to_public_dict())
        ),
        preparer=SealedDecisionRunPreparerV0(),
        enricher=PublicDecisionItemEnricherV0(_ExplodingEvidenceSource()),
    )

    result = execute_decision_board_cli_v0(config, components=components)

    assert serialize_decision_run_result_v0(result) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "ITEM_ENRICHMENT_INVALID",
    }
    assert "PRIVATE-EVIDENCE-SENTINEL" not in repr(result)
    assert list(tmp_path.iterdir()) == []


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
