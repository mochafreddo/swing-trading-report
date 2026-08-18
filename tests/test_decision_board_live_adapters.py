from __future__ import annotations

import asyncio
import copy
import json
import ssl
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from sab.ai_brief_sources import (
    AiBriefSourceProviderError,
    AiBriefSourceProviderResult,
)
from sab.decision_board import live_adapters as openai_live_adapter_module
from sab.decision_board.batch_evidence import (
    BatchDecisionEvidenceBuilderV0,
    BatchDecisionEvidenceSourceV0,
)
from sab.decision_board.claim_responses import ResponsesClaimVerifierV0
from sab.decision_board.claims import ClaimVerifierRequestV0, ClaimVerifierTimeoutError
from sab.decision_board.cli import DecisionBoardCliConfigV0
from sab.decision_board.compiler import (
    ApprovalStateV0,
    DependencyStateV0,
    EntryCompilerItemV0,
    EntrySignalStateV0,
    ExposureStateV0,
    ResearchStateV0,
)
from sab.decision_board.contracts import canonical_json_bytes, decision_payload_hash
from sab.decision_board.instruments import InstrumentRefV0
from sab.decision_board.live_adapters import OpenAIResponsesTransportV0
from sab.decision_board.live_production import DecisionBoardLiveAdapterV0
from sab.decision_board.production_adapter import (
    DecisionBoardAdapterUnavailableError,
    DecisionItemResearchOutcomeV0,
    SealedDecisionRunRequestLoaderV0,
)
from sab.decision_board.results import DecisionRunPublishedV0
from sab.decision_board.runner import (
    DecisionItemEnrichmentRequestV0,
    DecisionRunRequestV0,
    RunKindV0,
    UploadModeV0,
    create_decision_run_request_v0,
)
from sab.decision_board.shadow_execution import (
    ShadowGateExecutionBindingV0,
    shadow_gate_binding_matches_request_v0,
)
from sab.decision_board.shadow_gate import (
    shadow_gate_approval_signature_v0,
    validate_shadow_gate_manifest_v0,
)
from sab.decision_board.shadow_ledger import validate_shadow_evaluation_ledgers_v0
from sab.decision_board.supabase_request import (
    SupabaseDecisionInputConfigV0,
    SupabaseSealedRequestSourceV0,
    SupabaseSnapshotDownloaderV0,
)
from sab.research import live_adapters as live_adapter_module
from sab.research.contracts import (
    ResearchQuestionV0,
    ResearchSourcePolicyV0,
    SearchRequestV0,
    SourceCandidateV0,
    parse_search_response_v0,
)
from sab.research.deadline import Deadline
from sab.research.live_adapters import (
    AiBriefNewsSearchProviderV0,
    AsyncPublicDnsResolverV0,
    PinnedArticleFetcherV0,
)
from sab.research.orchestrator import (
    EvidenceResearcherV0,
    SearchProviderOperationalError,
    SearchProviderTimeoutError,
)
from sab.research.source_safety import (
    ArticleFetchResponseV0,
    create_article_artifact_v0,
)
from sab.utils.bounded_process import BoundedProcessTimeoutError

ROOT = Path(__file__).resolve().parents[1]


async def _inline_bounded_runner(
    operation: object,
    args: tuple[object, ...],
    *,
    timeout: float,
    kwargs: dict[str, object] | None = None,
) -> object:
    del timeout
    assert callable(operation)
    return operation(*args, **({} if kwargs is None else kwargs))


def _shadow_binding_for(request: DecisionRunRequestV0) -> ShadowGateExecutionBindingV0:
    raw = json.loads(
        (ROOT / "config" / "decision-board-shadow-gate.proposed.json").read_text(
            encoding="utf-8"
        )
    )
    gate_version = raw["gate_version"]
    input_ledger = {
        "schema_version": "decision-board-shadow-input-ledger.v0",
        "gate_version": gate_version,
        "cases": [
            {
                "case_id": "case-entry-aapl",
                "run_kind": request.run_kind.value,
                "sealed_input_hash": request.sealed_input_hash,
                "item_id": request.items[0].item_id,
            }
        ],
    }
    expected_ledger = {
        "schema_version": "decision-board-shadow-expected-action-ledger.v0",
        "gate_version": gate_version,
        "cases": [
            {
                "case_id": "case-entry-aapl",
                "expected_action_set": ["BUY"],
            }
        ],
    }
    raw["evaluation_ledger"] = {
        "input_ledger_sha256": decision_payload_hash(input_ledger),
        "expected_action_ledger_sha256": decision_payload_hash(expected_ledger),
        "case_count": 1,
    }
    manifest = validate_shadow_gate_manifest_v0(raw)
    ledger = validate_shadow_evaluation_ledgers_v0(
        manifest,
        input_ledger=input_ledger,
        expected_action_ledger=expected_ledger,
    )
    return ShadowGateExecutionBindingV0(
        manifest=manifest,
        ledger=ledger,
        expected_item_ids=(request.items[0].item_id,),
    )


def _instrument() -> InstrumentRefV0:
    return InstrumentRefV0(
        market="US",
        canonical_ticker="AAPL.NAS",
        exchange="NASDAQ",
        company_name="Apple Inc.",
        identity_source="ticker-directory",
        identity_version="fixture-2026-08-16",
    )


def test_default_blocking_operations_are_spawn_picklable() -> None:
    assert AsyncPublicDnsResolverV0().resolve_sync is live_adapter_module._resolve_sync
    assert PinnedArticleFetcherV0().fetch_sync is live_adapter_module._fetch_pinned_sync
    assert (
        OpenAIResponsesTransportV0(api_key="recorded-key").post_json
        is openai_live_adapter_module._post_json
    )


def test_live_news_search_uses_one_public_request_and_bounded_provider_chain() -> None:
    calls: list[dict[str, object]] = []
    published_at = "2026-08-16T10:00:00+00:00"

    def load_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        calls.append(kwargs)
        provider = str(kwargs["source_provider"])
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [
                    {
                        "title": f"Apple update from {provider}",
                        "url": f"https://{provider}.example/apple-update",
                        "published_at": published_at,
                    }
                ]
            }
        )

    provider = AiBriefNewsSearchProviderV0(
        source_loader=load_sources,
        now=lambda: datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        bounded_runner=_inline_bounded_runner,
    )
    request = SearchRequestV0(
        instrument=_instrument(),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        freshness_hours=72,
    )

    payload = asyncio.run(provider.search(request, deadline=Deadline.start(10)))
    sources = parse_search_response_v0(payload, expected_instrument=_instrument())

    assert [call["source_provider"] for call in calls] == [
        "finnhub",
        "polygon-news",
        "benzinga-news",
    ]
    assert all(call["eligible_tickers"] == {"AAPL.NAS"} for call in calls)
    assert all(call["source_report_path"] is None for call in calls)
    assert all(call["source_api_url"] is None for call in calls)
    assert len(sources) == 3
    assert provider.observations.snapshot() == {
        "provider_benzinga_news_attempts": 1,
        "provider_benzinga_news_failures": 0,
        "provider_benzinga_news_timeouts": 0,
        "provider_finnhub_attempts": 1,
        "provider_finnhub_failures": 0,
        "provider_finnhub_timeouts": 0,
        "provider_polygon_news_attempts": 1,
        "provider_polygon_news_failures": 0,
        "provider_polygon_news_timeouts": 0,
    }
    serialized = json.dumps(payload, sort_keys=True)
    assert "quantity" not in serialized
    assert "entry_price" not in serialized
    assert "account" not in serialized


def test_live_news_search_keeps_partial_success_provider_metrics() -> None:
    def load_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        if provider == "finnhub":
            raise AiBriefSourceProviderError("recorded provider failure")
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [
                    {
                        "title": f"Apple update from {provider}",
                        "url": f"https://{provider}.example/apple-update",
                        "published_at": "2026-08-16T10:00:00+00:00",
                    }
                ]
            }
        )

    provider = AiBriefNewsSearchProviderV0(
        source_loader=load_sources,
        now=lambda: datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        bounded_runner=_inline_bounded_runner,
    )
    request = SearchRequestV0(
        instrument=_instrument(),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        freshness_hours=72,
    )

    payload = asyncio.run(provider.search(request, deadline=Deadline.start(10)))
    sources = parse_search_response_v0(payload, expected_instrument=_instrument())

    assert len(sources) == 2
    assert provider.observations.snapshot()["provider_finnhub_attempts"] == 1
    assert provider.observations.snapshot()["provider_finnhub_failures"] == 1
    assert provider.observations.snapshot()["provider_finnhub_timeouts"] == 0


def test_live_news_search_counts_hard_process_timeout_and_keeps_partial_success() -> (
    None
):
    def load_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        return AiBriefSourceProviderResult(
            sources_by_ticker={
                "AAPL.NAS": [
                    {
                        "title": f"Apple update from {provider}",
                        "url": f"https://{provider}.example/apple-update",
                        "published_at": "2026-08-16T10:00:00+00:00",
                    }
                ]
            }
        )

    async def timeout_first_provider(
        operation: object,
        args: tuple[object, ...],
        *,
        timeout: float,
        kwargs: dict[str, object] | None = None,
    ) -> object:
        del timeout
        assert kwargs is not None
        if kwargs["source_provider"] == "finnhub":
            raise BoundedProcessTimeoutError("recorded hard timeout")
        assert callable(operation)
        return operation(*args, **kwargs)

    provider = AiBriefNewsSearchProviderV0(
        source_loader=load_sources,
        now=lambda: datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        bounded_runner=timeout_first_provider,
    )
    request = SearchRequestV0(
        instrument=_instrument(),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        freshness_hours=72,
    )

    payload = asyncio.run(provider.search(request, deadline=Deadline.start(10)))
    sources = parse_search_response_v0(payload, expected_instrument=_instrument())

    assert len(sources) == 2
    assert provider.observations.snapshot()["provider_finnhub_attempts"] == 1
    assert provider.observations.snapshot()["provider_finnhub_failures"] == 1
    assert provider.observations.snapshot()["provider_finnhub_timeouts"] == 1


def test_live_news_search_counts_malformed_provider_result_as_failure() -> None:
    def load_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        del kwargs
        return cast(AiBriefSourceProviderResult, object())

    provider = AiBriefNewsSearchProviderV0(
        source_loader=load_sources,
        now=lambda: datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        bounded_runner=_inline_bounded_runner,
    )
    request = SearchRequestV0(
        instrument=_instrument(),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        freshness_hours=72,
    )

    with pytest.raises(SearchProviderOperationalError, match="provider failed"):
        asyncio.run(provider.search(request, deadline=Deadline.start(10)))

    assert provider.observations.snapshot()["provider_finnhub_attempts"] == 1
    assert provider.observations.snapshot()["provider_finnhub_failures"] == 1


@pytest.mark.parametrize("failure_kind", ["failure", "timeout"])
def test_live_news_search_aggregates_all_provider_failures_and_timeouts(
    failure_kind: str,
) -> None:
    def load_sources(**kwargs: object) -> AiBriefSourceProviderResult:
        del kwargs
        raise AiBriefSourceProviderError("recorded provider failure")

    async def timeout_runner(
        operation: object,
        args: tuple[object, ...],
        *,
        timeout: float,
        kwargs: dict[str, object] | None = None,
    ) -> object:
        del timeout
        if failure_kind == "timeout":
            raise BoundedProcessTimeoutError("recorded hard timeout")
        assert callable(operation)
        return operation(*args, **({} if kwargs is None else kwargs))

    provider = AiBriefNewsSearchProviderV0(
        source_loader=load_sources,
        now=lambda: datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        bounded_runner=(
            timeout_runner if failure_kind == "timeout" else _inline_bounded_runner
        ),
    )
    request = SearchRequestV0(
        instrument=_instrument(),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
        freshness_hours=72,
    )

    expected_error = (
        SearchProviderTimeoutError
        if failure_kind == "timeout"
        else SearchProviderOperationalError
    )
    expected_message = "timed out" if failure_kind == "timeout" else "providers failed"
    with pytest.raises(expected_error, match=expected_message):
        asyncio.run(provider.search(request, deadline=Deadline.start(10)))

    observations = provider.observations.snapshot()
    for provider_name in ("finnhub", "polygon_news", "benzinga_news"):
        assert observations[f"provider_{provider_name}_attempts"] == 1
        assert observations[f"provider_{provider_name}_failures"] == 1
        assert observations[f"provider_{provider_name}_timeouts"] == (
            1 if failure_kind == "timeout" else 0
        )


def test_live_news_search_cancellation_records_one_inflight_timeout_then_reraises() -> (
    None
):
    async def exercise() -> None:
        started = asyncio.Event()

        async def in_flight_runner(
            operation: object,
            args: tuple[object, ...],
            *,
            timeout: float,
            kwargs: dict[str, object] | None = None,
        ) -> object:
            del operation, args, timeout, kwargs
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("the cancelled provider must not return")

        provider = AiBriefNewsSearchProviderV0(
            source_loader=lambda **kwargs: cast(AiBriefSourceProviderResult, object()),
            now=lambda: datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
            bounded_runner=in_flight_runner,
        )
        request = SearchRequestV0(
            instrument=_instrument(),
            questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
            freshness_hours=72,
        )
        task = asyncio.create_task(
            provider.search(request, deadline=Deadline.start(10))
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        observations = provider.observations.snapshot()
        assert observations["provider_finnhub_attempts"] == 1
        assert observations["provider_finnhub_failures"] == 1
        assert observations["provider_finnhub_timeouts"] == 1
        for provider_name in ("polygon_news", "benzinga_news"):
            assert observations[f"provider_{provider_name}_attempts"] == 0
            assert observations[f"provider_{provider_name}_failures"] == 0
            assert observations[f"provider_{provider_name}_timeouts"] == 0

    asyncio.run(exercise())


def test_dns_and_article_fetch_adapters_preserve_resolved_address_boundary() -> None:
    dns_calls: list[tuple[str, int]] = []
    fetch_calls: list[tuple[str, tuple[str, ...], float, int]] = []

    def resolve_sync(hostname: str, port: int) -> tuple[str, ...]:
        dns_calls.append((hostname, port))
        return ("93.184.216.34",)

    def fetch_sync(
        url: str,
        addresses: tuple[str, ...],
        timeout: float,
        max_bytes: int,
    ) -> ArticleFetchResponseV0:
        fetch_calls.append((url, addresses, timeout, max_bytes))
        return ArticleFetchResponseV0(
            status_code=200,
            content_type="text/html; charset=utf-8",
            content_encoding="identity",
            body=b"<p>Public article text</p>",
            location=None,
        )

    resolver = AsyncPublicDnsResolverV0(
        resolve_sync=resolve_sync,
        bounded_runner=_inline_bounded_runner,
    )
    fetcher = PinnedArticleFetcherV0(
        fetch_sync=fetch_sync,
        bounded_runner=_inline_bounded_runner,
    )

    addresses = asyncio.run(resolver.resolve("news.example", 443, timeout=2.0))
    response = asyncio.run(
        fetcher.fetch(
            "https://news.example/article",
            tuple(addresses),
            timeout=2.0,
            max_bytes=1024,
        )
    )

    assert dns_calls == [("news.example", 443)]
    assert fetch_calls == [
        (
            "https://news.example/article",
            ("93.184.216.34",),
            2.0,
            1024,
        )
    ]
    assert response.body == b"<p>Public article text</p>"


def test_pinned_fetch_shares_one_timeout_across_resolved_addresses(monkeypatch) -> None:
    clock = [100.0]
    connection_timeouts: list[float] = []
    requested_paths: list[str] = []

    class Response:
        status = 200

        def getheader(self, name: str, default=None):
            del name
            return default

        def read(self, size: int) -> bytes:
            del size
            return b"public article"

    class Connection:
        def __init__(
            self,
            hostname: str,
            port: int,
            *,
            address: str,
            timeout: float,
        ) -> None:
            del hostname, port
            self.address = address
            connection_timeouts.append(timeout)

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            del method, headers
            requested_paths.append(path)
            if self.address == "93.184.216.34":
                clock[0] += 3.0
                raise OSError("first address timed out")

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        live_adapter_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock[0]),
        raising=False,
    )
    monkeypatch.setattr(live_adapter_module, "_PinnedHttpConnection", Connection)

    response = live_adapter_module._fetch_pinned_sync(
        "http://example.com/article?story=42",
        ("93.184.216.34", "93.184.216.35"),
        4.0,
        1024,
    )

    assert response.body == b"public article"
    assert connection_timeouts == [4.0, 1.0]
    assert requested_paths == ["/article?story=42", "/article?story=42"]


def test_pinned_https_connection_closes_raw_socket_when_tls_wrap_fails(
    monkeypatch,
) -> None:
    class RawSocket:
        closed = False

        def close(self) -> None:
            self.closed = True

    raw_socket = RawSocket()
    monkeypatch.setattr(
        live_adapter_module.socket,
        "create_connection",
        lambda *args, **kwargs: raw_socket,
    )
    connection = live_adapter_module._PinnedHttpsConnection(
        "example.com",
        443,
        address="93.184.216.34",
        timeout=2.0,
    )
    monkeypatch.setattr(
        connection._ssl_context,
        "wrap_socket",
        lambda *args, **kwargs: (_ for _ in ()).throw(ssl.SSLError("TLS failed")),
    )

    with pytest.raises(ssl.SSLError, match="TLS failed"):
        connection.connect()

    assert raw_socket.closed is True


def test_openai_responses_transport_keeps_secret_out_of_public_payload() -> None:
    calls: list[dict[str, object]] = []

    def post_json(
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout: float,
    ) -> object:
        calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout": timeout,
            }
        )
        return {"status": "completed"}

    transport = OpenAIResponsesTransportV0(
        api_key="openai-private-sentinel",
        post_json=post_json,
        bounded_runner=_inline_bounded_runner,
    )
    request: dict[str, object] = {
        "model": "gpt-5-mini",
        "input": [{"role": "user", "content": "public claim"}],
    }

    result = asyncio.run(
        transport.create_response(
            request,
            deadline=Deadline.start(10),
            timeout=3.0,
        )
    )

    assert result == {"status": "completed"}
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.openai.com/v1/responses"
    headers = calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer openai-private-sentinel"
    assert "openai-private-sentinel" not in json.dumps(calls[0]["payload"])
    assert calls[0]["timeout"] == 3.0


def test_responses_verifier_maps_hard_transport_timeout_to_claim_timeout() -> None:
    class TimeoutTransport:
        async def create_response(
            self,
            request: dict[str, object],
            *,
            deadline: Deadline,
            timeout: float,
        ) -> object:
            del request, deadline, timeout
            raise BoundedProcessTimeoutError("recorded hard timeout")

    verifier = ResponsesClaimVerifierV0(
        transport=TimeoutTransport(),
        model="recorded-model",
    )
    request = ClaimVerifierRequestV0(
        claim_id="claim-aapl",
        claim_text="Apple announced a public update.",
        instrument=_instrument(),
        article_content_hash="sha256:" + "d" * 64,
        article_text="Apple announced a public update.",
    )

    with pytest.raises(ClaimVerifierTimeoutError, match="timed out"):
        asyncio.run(
            verifier.verify(
                request,
                deadline=Deadline.start(10),
                timeout=3.0,
            )
        )


def test_supabase_snapshot_downloader_maps_hard_process_timeout_to_unavailable() -> (
    None
):
    def timeout_runner(
        operation: object,
        args: tuple[object, ...],
        *,
        timeout: float,
        kwargs: dict[str, object] | None = None,
    ) -> object:
        del operation, args, timeout, kwargs
        raise BoundedProcessTimeoutError("recorded hard timeout")

    downloader = SupabaseSnapshotDownloaderV0(
        config=SupabaseDecisionInputConfigV0(
            url="https://supabase.example",
            service_role_key="recorded-service-key",
            timeout_seconds=3.0,
        ),
        bounded_runner=timeout_runner,
    )

    with pytest.raises(DecisionBoardAdapterUnavailableError, match="unavailable"):
        downloader.download(
            "decision-board-inputs/v0/" + "a" * 64 + ".json",
            max_bytes=1024,
        )


def test_shadow_binding_rejects_sealed_request_item_set_mismatch() -> None:
    item = EntryCompilerItemV0.create(
        item_id="entry-AAPL.NAS",
        instrument=_instrument(),
        item_state=ApprovalStateV0.APPROVED,
        identity_state=ApprovalStateV0.APPROVED,
        signal_state=EntrySignalStateV0.READY_ENTER,
        mandate_state=DependencyStateV0.CURRENT,
        price_state=DependencyStateV0.CURRENT,
        exposure_state=ExposureStateV0.PASS,
        research_state=ResearchStateV0.COVERAGE_GAP,
    )
    second = EntryCompilerItemV0.create(
        item_id="entry-MSFT.NAS",
        instrument=InstrumentRefV0(
            market="US",
            canonical_ticker="MSFT.NAS",
            exchange="NASDAQ",
            company_name="Microsoft Corp.",
            identity_source="ticker-directory",
            identity_version="fixture-2026-08-16",
        ),
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
        run_id="entry-item-set-mismatch",
        idempotency_key="sha256:" + "a" * 64,
        created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        sealed_input_hash="sha256:" + "b" * 64,
        items=(item, second),
        selection=None,
        upload_mode=UploadModeV0.DISABLED,
        metadata={"policy_version": "decision-policy.v0"},
    )
    binding = _shadow_binding_for(request)

    assert not shadow_gate_binding_matches_request_v0(binding, request)


def test_openai_sync_transport_enforces_one_wall_clock_budget(monkeypatch) -> None:
    clock = [200.0]
    request_timeouts: list[tuple[float, float]] = []

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}

        def iter_content(self, *, chunk_size: int):
            del chunk_size
            clock[0] += 3.1
            yield b"{}"

        def close(self) -> None:
            return None

    class Session:
        trust_env = True

        def post(self, *args, **kwargs) -> Response:
            del args
            request_timeouts.append(kwargs["timeout"])
            return Response()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "sab.decision_board.live_adapters.time",
        SimpleNamespace(monotonic=lambda: clock[0]),
        raising=False,
    )
    monkeypatch.setattr(
        "sab.decision_board.live_adapters.requests.Session",
        Session,
    )

    with pytest.raises(TimeoutError, match="timed out"):
        openai_live_adapter_module._post_json(
            "https://api.openai.com/v1/responses",
            {"Authorization": "Bearer private"},
            {"model": "recorded"},
            3.0,
        )

    assert request_timeouts == [(1.0, 3.0)]


def test_openai_sync_transport_allows_slow_first_byte_within_wall_clock_budget(
    monkeypatch,
) -> None:
    request_timeouts: list[tuple[float, float]] = []

    class Response:
        status_code = 200
        headers = {"content-type": "application/json"}

        def iter_content(self, *, chunk_size: int):
            assert chunk_size == 64 * 1024
            yield b"{}"

        def close(self) -> None:
            return None

    class Session:
        trust_env = True

        def post(self, *args, **kwargs) -> Response:
            del args
            timeout = kwargs["timeout"]
            request_timeouts.append(timeout)
            if timeout[1] < 7.5:
                raise openai_live_adapter_module.requests.ReadTimeout(
                    "recorded slow first byte"
                )
            return Response()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "sab.decision_board.live_adapters.requests.Session",
        Session,
    )

    assert (
        openai_live_adapter_module._post_json(
            "https://api.openai.com/v1/responses",
            {"Authorization": "Bearer private"},
            {"model": "recorded"},
            15.0,
        )
        == {}
    )
    assert request_timeouts == [(5.0, 15.0)]


def test_batch_evidence_builder_researches_selected_items_once_under_shared_deadline(
    tmp_path,
) -> None:
    provider_calls: list[str] = []
    claim_calls: list[str] = []

    class Provider:
        async def search(
            self, request: SearchRequestV0, *, deadline: Deadline
        ) -> object:
            deadline.remaining()
            provider_calls.append(request.instrument.canonical_ticker)
            return {
                "schema": "sab.research.search.v0",
                "instrument": request.instrument.to_public_dict(),
                "sources": [
                    {
                        "canonical_ticker": request.instrument.canonical_ticker,
                        "title": "Apple announced a public product update.",
                        "url": "https://news.example/apple-update",
                        "publisher": "news.example",
                        "published_at": "2026-08-16T10:00:00Z",
                        "purpose": "PRIMARY",
                    }
                ],
            }

    class ArticleVerifier:
        def preflight(self, policy: object) -> None:
            del policy

        async def verify(
            self,
            source: SourceCandidateV0,
            *,
            deadline: Deadline,
            policy: ResearchSourcePolicyV0,
        ):
            deadline.remaining()
            return create_article_artifact_v0(
                source=source,
                final_url=source.canonical_url,
                normalized_text=(
                    "Apple announced a public product update. Details are public."
                ),
                policy=policy,
            )

    class ClaimVerifier:
        async def verify(
            self,
            request: ClaimVerifierRequestV0,
            *,
            deadline: Deadline,
            timeout: float,
        ):
            deadline.remaining()
            claim_calls.append(request.claim_id)
            start = request.article_text.index(request.claim_text)
            return {
                "entailment": "SUPPORTED",
                "supporting_span": request.claim_text,
                "supporting_location": {
                    "kind": "TEXT_OFFSETS",
                    "start": start,
                    "end": start + len(request.claim_text),
                },
                "verifier_version": "recorded-claim-v0",
            }

    class ProviderMetrics:
        def snapshot(self) -> dict[str, int]:
            return {
                "provider_finnhub_attempts": 1,
                "provider_finnhub_failures": 1,
                "provider_finnhub_timeouts": 0,
                "provider_polygon_news_attempts": 1,
                "provider_polygon_news_failures": 0,
                "provider_polygon_news_timeouts": 0,
                "provider_benzinga_news_attempts": 1,
                "provider_benzinga_news_failures": 0,
                "provider_benzinga_news_timeouts": 0,
            }

    item = EntryCompilerItemV0.create(
        item_id="entry-AAPL.NAS",
        instrument=_instrument(),
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
        run_id="entry-batch-recorded",
        idempotency_key="sha256:" + "a" * 64,
        created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        sealed_input_hash="sha256:" + "b" * 64,
        items=(item,),
        selection=None,
        upload_mode=UploadModeV0.DISABLED,
        metadata={
            "policy_version": "decision-policy.v0",
            "researcher_version": "recorded-research-v0",
            "verifier_version": "recorded-claim-v0",
        },
    )
    builder = BatchDecisionEvidenceBuilderV0(
        researcher=EvidenceResearcherV0(Provider(), ArticleVerifier()),
        claim_verifier=ClaimVerifier(),
        provider_metrics_source=ProviderMetrics(),
    )

    source = asyncio.run(builder.build(request, deadline=Deadline.start(10)))
    assert type(source) is BatchDecisionEvidenceSourceV0
    outcome = cast(
        DecisionItemResearchOutcomeV0,
        source.research(
            DecisionItemEnrichmentRequestV0(
                run_kind=RunKindV0.ENTRY,
                item_id=item.item_id,
                instrument=_instrument(),
            )
        ),
    )

    assert provider_calls == ["AAPL.NAS"]
    assert len(claim_calls) == 1
    assert outcome.research_state is ResearchStateV0.COVERAGE_GAP
    assert len(outcome.evidence) == 1

    class RequestSource:
        identities: list[dict[str, str]] = []

        def load_sealed_request(self, identity: dict[str, str]) -> object:
            self.identities.append(identity)
            return request

    request_source = RequestSource()
    adapter = DecisionBoardLiveAdapterV0(
        request_loader=SealedDecisionRunRequestLoaderV0(request_source),
        evidence_builder=builder,
    )
    config = DecisionBoardCliConfigV0.from_strings(
        run_kind="ENTRY",
        run_id=request.run_id,
        idempotency_key=request.idempotency_key,
        created_at="2026-08-16T12:00:00Z",
        sealed_input_hash=request.sealed_input_hash,
        upload_mode="DISABLED",
        report_dir=str(tmp_path),
    )

    binding = _shadow_binding_for(request)
    result = adapter.execute(config, binding=binding)

    assert type(result) is DecisionRunPublishedV0
    assert result.local_path.is_file()
    report = json.loads(result.local_path.read_text(encoding="utf-8"))
    assert report["metadata"]["provider_finnhub_attempts"] == 1
    assert report["metadata"]["provider_finnhub_failures"] == 1
    assert report["metadata"]["provider_polygon_news_failures"] == 0
    assert report["metadata"]["provider_benzinga_news_failures"] == 0
    assert report["metadata"]["gate_manifest_sha256"] == (
        binding.manifest.manifest_sha256
    )
    assert request_source.identities == [config.to_public_dict()]
    assert "report_dir" not in request_source.identities[0]


def test_supabase_sealed_request_source_reissues_only_hashed_public_snapshot() -> None:
    snapshot = {
        "schema": "sab.decision_board.sealed_request.v0",
        "run_kind": "ENTRY",
        "metadata": {
            "policy_version": "decision-policy.v0",
            "registry_version": "ticker-directory.v0",
            "researcher_version": "live-research.v0",
            "verifier_version": "openai-claim.v0",
        },
        "items": [
            {
                "item_id": "entry-AAPL.NAS",
                "instrument": _instrument().to_public_dict(),
                "item_state": "APPROVED",
                "identity_state": "APPROVED",
                "signal_state": "READY_ENTER",
                "mandate_state": "CURRENT",
                "price_state": "CURRENT",
                "exposure_state": "PASS",
            }
        ],
    }
    sealed_hash = decision_payload_hash(snapshot)
    calls: list[tuple[str, int]] = []

    class Downloader:
        def download(self, storage_key: str, *, max_bytes: int) -> bytes:
            calls.append((storage_key, max_bytes))
            return canonical_json_bytes(snapshot)

    source = SupabaseSealedRequestSourceV0(downloader=Downloader())
    identity = {
        "run_kind": "ENTRY",
        "run_id": "entry-live-snapshot",
        "idempotency_key": "sha256:" + "c" * 64,
        "created_at": "2026-08-16T12:00:00Z",
        "sealed_input_hash": sealed_hash,
        "upload_mode": "DISABLED",
    }

    request = cast(DecisionRunRequestV0, source.load_sealed_request(identity))

    assert calls == [
        (
            f"decision-board-inputs/v0/{sealed_hash.removeprefix('sha256:')}.json",
            1_048_576,
        )
    ]
    assert request.run_kind is RunKindV0.ENTRY
    assert request.sealed_input_hash == sealed_hash
    assert request.items[0].instrument == _instrument()
    assert set(request.metadata) == {
        "eligible_count",
        "policy_version",
        "registry_version",
        "researcher_version",
        "selected_count",
        "verifier_version",
    }


def test_approved_gate_and_sealed_snapshot_hash_form_a_unidirectional_binding() -> None:
    snapshot = {
        "schema": "sab.decision_board.sealed_request.v0",
        "run_kind": "ENTRY",
        "metadata": {
            "policy_version": "decision-policy.v0",
            "registry_version": "ticker-directory.v0",
            "researcher_version": "live-research.v0",
            "verifier_version": "openai-claim.v0",
        },
        "items": [
            {
                "item_id": "entry-AAPL.NAS",
                "instrument": _instrument().to_public_dict(),
                "item_state": "APPROVED",
                "identity_state": "APPROVED",
                "signal_state": "READY_ENTER",
                "mandate_state": "CURRENT",
                "price_state": "CURRENT",
                "exposure_state": "PASS",
            }
        ],
    }
    sealed_hash = decision_payload_hash(snapshot)
    raw = json.loads(
        (ROOT / "config" / "decision-board-shadow-gate.proposed.json").read_text(
            encoding="utf-8"
        )
    )
    raw["approval"].update(
        {
            "state": "APPROVED",
            "approved_by": "user",
            "approved_at": "2026-08-17T09:00:00Z",
            "approval_signature_sha256": "sha256:" + "0" * 64,
        }
    )
    raw["runtime_contract"]["code_revision"] = "git:" + "1" * 40
    for name in raw["runtime_contract"]["artifact_digests"]:
        raw["runtime_contract"]["artifact_digests"][name] = "sha256:" + "2" * 64
    input_ledger = {
        "schema_version": "decision-board-shadow-input-ledger.v0",
        "gate_version": raw["gate_version"],
        "cases": [
            {
                "case_id": "case-entry-aapl",
                "run_kind": "ENTRY",
                "sealed_input_hash": sealed_hash,
                "item_id": "entry-AAPL.NAS",
            }
        ],
    }
    expected_ledger = {
        "schema_version": "decision-board-shadow-expected-action-ledger.v0",
        "gate_version": raw["gate_version"],
        "cases": [{"case_id": "case-entry-aapl", "expected_action_set": ["BUY"]}],
    }
    raw["evaluation_ledger"] = {
        "input_ledger_sha256": decision_payload_hash(input_ledger),
        "expected_action_ledger_sha256": decision_payload_hash(expected_ledger),
        "case_count": 1,
    }
    raw["approval"]["approval_signature_sha256"] = shadow_gate_approval_signature_v0(
        raw
    )
    manifest = validate_shadow_gate_manifest_v0(
        raw,
        require_approved=True,
        input_ledger=input_ledger,
        expected_action_ledger=expected_ledger,
    )
    ledger = validate_shadow_evaluation_ledgers_v0(
        manifest,
        input_ledger=input_ledger,
        expected_action_ledger=expected_ledger,
    )

    class Downloader:
        def download(self, storage_key: str, *, max_bytes: int) -> bytes:
            del storage_key, max_bytes
            return canonical_json_bytes(snapshot)

    request = cast(
        DecisionRunRequestV0,
        SupabaseSealedRequestSourceV0(downloader=Downloader()).load_sealed_request(
            {
                "run_kind": "ENTRY",
                "run_id": "entry-gate-bundle",
                "idempotency_key": "sha256:" + "c" * 64,
                "created_at": "2026-08-17T12:30:00Z",
                "sealed_input_hash": sealed_hash,
                "upload_mode": "DISABLED",
            }
        ),
    )
    binding = ShadowGateExecutionBindingV0(
        manifest=manifest,
        ledger=ledger,
        expected_item_ids=("entry-AAPL.NAS",),
    )

    assert "gate_manifest_sha256" not in request.metadata
    assert decision_payload_hash(snapshot) == sealed_hash
    assert shadow_gate_binding_matches_request_v0(binding, request)


def test_supabase_sealed_request_source_rejects_private_snapshot_fields() -> None:
    snapshot = {
        "schema": "sab.decision_board.sealed_request.v0",
        "run_kind": "ENTRY",
        "metadata": {"policy_version": "decision-policy.v0"},
        "items": [
            {
                "item_id": "entry-AAPL.NAS",
                "instrument": _instrument().to_public_dict(),
                "item_state": "APPROVED",
                "identity_state": "APPROVED",
                "signal_state": "READY_ENTER",
                "mandate_state": "CURRENT",
                "price_state": "CURRENT",
                "exposure_state": "PASS",
                "quantity": "PRIVATE-ACCOUNT-SENTINEL",
            }
        ],
    }
    sealed_hash = decision_payload_hash(snapshot)

    class Downloader:
        def download(self, storage_key: str, *, max_bytes: int) -> bytes:
            del storage_key, max_bytes
            return canonical_json_bytes(copy.deepcopy(snapshot))

    source = SupabaseSealedRequestSourceV0(downloader=Downloader())

    try:
        source.load_sealed_request(
            {
                "run_kind": "ENTRY",
                "run_id": "entry-private-rejected",
                "idempotency_key": "sha256:" + "d" * 64,
                "created_at": "2026-08-16T12:00:00Z",
                "sealed_input_hash": sealed_hash,
                "upload_mode": "DISABLED",
            }
        )
    except ValueError as exc:
        assert "PRIVATE-ACCOUNT-SENTINEL" not in str(exc)
    else:  # pragma: no cover - the source must reject private-bearing snapshots
        raise AssertionError(
            "private snapshot field crossed the sealed request boundary"
        )
