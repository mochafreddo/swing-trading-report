from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sab.decision_board.claims import (
    ClaimRequestV0,
    ClaimValidationSucceededV0,
    ClaimVerifierRequestV0,
    validate_claim_v0,
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
from sab.decision_board.inputs import (
    SwingApprovedV0,
    approve_swing_snapshot_v0,
    project_research_instruments_v0,
)
from sab.decision_board.instruments import (
    InstrumentRefV0,
    VersionedInstrumentRegistryV0,
)
from sab.decision_board.results import (
    DecisionRunPublishedV0,
    serialize_decision_run_result_v0,
)
from sab.decision_board.run_journal import (
    RunJournalStatusV0,
    RunJournalStoreV0,
    serialize_run_journal_v0,
)
from sab.decision_board.runner import (
    CompilerItemV0,
    DecisionBoardRunnerV0,
    DecisionRunRequestV0,
    RunKindV0,
    UploadModeV0,
    create_decision_run_request_v0,
    create_run_prepared_v0,
)
from sab.report.decision_board import build_decision_board_storage_key
from sab.report.supabase_storage import (
    SupabaseStorageConfig,
    upload_decision_board_report,
)
from sab.research.contracts import (
    ResearchInputV0,
    ResearchQuestionV0,
    ResearchSourcePolicyV0,
    SourcePurposeV0,
    create_source_candidate_v0,
)
from sab.research.deadline import Deadline
from sab.research.orchestrator import EvidenceResearcherV0, ResearchCompletedV0
from sab.research.source_safety import (
    ArticleArtifactV0,
    ArticleFetchResponseV0,
    SafeArticleVerifierV0,
    create_article_artifact_v0,
)
from sab.scheduler.holdings import (
    broker_holdings_digest_v0,
    validate_broker_snapshot_v0,
)

NOW = datetime(2026, 8, 13, 3, 0, tzinfo=UTC)
PUBLIC_ARTICLE = "Aurora beat guidance. Aurora public demand remains stable."
PUBLIC_SPAN = "Aurora beat guidance."


def _sentinel(*parts: str) -> str:
    return "-".join(parts)


SENTINELS = {
    "account_id": "acct-private-58QX-sentinel",
    "account_number": "account-number-4901-7713-sentinel",
    "quantity": "9137.123456",
    "entry_price": "8123.4567",
    "pnl": "pnl-minus-7719-sentinel",
    "notes": "notes-private-M7ZP-sentinel",
    "tags": "tag-private-Q4KC-sentinel",
    "toss_secret": _sentinel("toss", "secret", "H8NW", "sentinel"),
    "supabase_secret": _sentinel("supabase", "secret", "R2DM", "sentinel"),
    "api_secret": _sentinel("api", "secret", "V6TJ", "sentinel"),
    "absolute_path": "/Users/private/decision-board-S5GA-sentinel.json",
    "provider_exception": "provider-exception-J9UX-sentinel",
    "traceback": "Traceback-private-P3LF-sentinel",
    "raw_article": "raw-article-private-C7VB-sentinel",
    "private_url": "http://127.0.0.1/private-url-N4RY-sentinel",
    "local_url": "http://research.local/local-url-K2WT-sentinel",
}


def _scan(boundary: str, value: object) -> None:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    folded = text.casefold()
    normalized = re.sub(r"[^a-z0-9]", "", folded)
    for label, sentinel in SENTINELS.items():
        if sentinel.casefold() in folded:
            raise AssertionError(f"privacy leak at {boundary}: {label}")
        sentinel_normalized = re.sub(r"[^a-z0-9]", "", sentinel.casefold())
        if sentinel_normalized and sentinel_normalized in normalized:
            raise AssertionError(f"privacy leak at {boundary}: {label}")


def _instrument() -> InstrumentRefV0:
    return InstrumentRefV0(
        market="US",
        canonical_ticker="AUR.NAS",
        exchange="NASDAQ",
        company_name="Aurora Synthetic Systems",
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-13",
    )


def _registry() -> VersionedInstrumentRegistryV0:
    return VersionedInstrumentRegistryV0(
        identity_source="synthetic-directory",
        identity_version="fixture-2026-08-13",
        records=(
            {
                "market": "US",
                "canonical_ticker": "AUR.NAS",
                "exchange": "NASDAQ",
                "company_name": "Aurora Synthetic Systems",
                "aliases": ["AURORA.O"],
            },
        ),
    )


def _private_snapshot():
    holdings = [
        {
            "ticker": "AUR.NAS",
            "quantity": SENTINELS["quantity"],
            "entry_price": SENTINELS["entry_price"],
            "entry_currency": "USD",
            "entry_date": "2026-08-12",
            "strategy": "SWING",
            "entry_pattern": None,
            "notes": SENTINELS["notes"],
            "tags": [SENTINELS["tags"]],
            "stop_override": None,
            "target_override": None,
            "broker_state": "confirmed",
            "broker_missing_first_seen_date": None,
            "broker_missing_last_seen_date": None,
            "broker_missing_count": 0,
            "broker_missing_diff_hash": None,
        }
    ]
    digest = broker_holdings_digest_v0(holdings)
    return validate_broker_snapshot_v0(
        [
            {
                "state_key": "toss-sync:success:MIXED:2026-08-13",
                "session_date": "2026-08-13",
                "status": "applied",
                "fresh_until": (NOW + timedelta(minutes=5)).isoformat(),
                "sealed_at": (NOW - timedelta(minutes=1)).isoformat(),
                "holdings_digest": digest,
                "revision": 13,
                "marker": {
                    "scope": "MIXED",
                    "sessionDate": "2026-08-13",
                    "status": "applied",
                    "snapshotDigest": digest,
                    "snapshotRevision": 13,
                    "sealedAt": (NOW - timedelta(minutes=1)).isoformat(),
                },
                "holdings": holdings,
            }
        ],
        now=NOW,
        expected_session_date="2026-08-13",
    )


class _PublicSearchProvider:
    def __init__(self) -> None:
        self.toss_secret = SENTINELS["toss_secret"]
        self.api_secret = SENTINELS["api_secret"]
        self.requests: list[dict[str, object]] = []

    async def search(self, request: object, *, deadline: Deadline) -> object:
        del deadline
        public = request.to_public_dict()  # type: ignore[attr-defined]
        self.requests.append(public)
        instrument = public["instrument"]
        return {
            "schema": "sab.research.search.v0",
            "instrument": instrument,
            "sources": [
                {
                    "canonical_ticker": "AUR.NAS",
                    "title": "Synthetic public filing",
                    "url": "https://evidence.example/aurora/filing",
                    "publisher": "Synthetic Exchange",
                    "published_at": "2026-08-13T01:00:00Z",
                    "purpose": "ACTION_CHANGING",
                }
            ],
        }


class _PublicArticleVerifier:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def preflight(self, policy: ResearchSourcePolicyV0) -> None:
        del policy

    async def verify(
        self,
        source: object,
        *,
        deadline: Deadline,
        policy: ResearchSourcePolicyV0,
    ) -> ArticleArtifactV0:
        del deadline
        self.requests.append(
            {
                "instrument": source.instrument.to_public_dict(),  # type: ignore[attr-defined]
                "canonical_url": source.canonical_url,  # type: ignore[attr-defined]
            }
        )
        return create_article_artifact_v0(
            source=source,  # type: ignore[arg-type]
            final_url=source.canonical_url,  # type: ignore[attr-defined]
            normalized_text=PUBLIC_ARTICLE,
            policy=policy,
        )


class _PublicClaimVerifier:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def verify(
        self,
        request: ClaimVerifierRequestV0,
        *,
        deadline: Deadline,
        timeout: float,
    ) -> object:
        self.requests.append(
            {
                **request.to_public_dict(),
                "deadline": {
                    "expires_at_monotonic": deadline.expires_at,
                    "timeout_seconds": timeout,
                },
            }
        )
        return {
            "entailment": "SUPPORTED",
            "supporting_span": PUBLIC_SPAN,
            "supporting_location": {
                "kind": "TEXT_OFFSETS",
                "start": 0,
                "end": len(PUBLIC_SPAN),
            },
            "verifier_version": "synthetic-verifier-2026-08-13",
        }


class _Prepared:
    def prepare(self, request: DecisionRunRequestV0):
        return create_run_prepared_v0(request)


class _EvidenceEnricher:
    def __init__(self, evidence: CompilerEvidenceV0) -> None:
        self.evidence = evidence
        self.requests: list[object] = []

    def enrich(self, item: CompilerItemV0, *, request: object):
        self.requests.append(request)
        assert type(item) is EntryCompilerItemV0
        return EntryCompilerItemV0.create(
            item_id=item.item_id,
            instrument=item.instrument,
            item_state=item.item_state,
            identity_state=item.identity_state,
            signal_state=item.signal_state,
            mandate_state=item.mandate_state,
            price_state=item.price_state,
            exposure_state=item.exposure_state,
            research_state=item.research_state,
            evidence=(self.evidence,),
        )


class _CapturingUploader:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def upload(self, *, local_path: Path, storage_key: str) -> str:
        self.requests.append(
            {
                "storage_key": storage_key,
                "body": local_path.read_bytes(),
            }
        )
        return storage_key


class _Response:
    def __init__(self, status_code: int, *, text: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


class _StorageSession:
    def __init__(self, authoritative_row: dict[str, object]) -> None:
        self.authoritative_row = authoritative_row
        self.posts: list[dict[str, object]] = []
        self.gets: list[dict[str, object]] = []

    def post(self, url: str, *, headers: dict[str, str], data: bytes, timeout: float):
        del headers, timeout
        self.posts.append({"url": url, "data": data})
        return _Response(201)

    def get(self, url: str, *, headers: dict[str, str], timeout: float):
        del headers, timeout
        self.gets.append({"url": url})
        return _Response(200, text=json.dumps([self.authoritative_row]))

    def delete(self, *args: object, **kwargs: object):
        raise AssertionError("unexpected storage delete")


def _index_row(report: dict[str, object], key: str) -> dict[str, object]:
    payload = report["decision_payload"]
    assert isinstance(payload, dict)
    items = payload["items"]
    assert isinstance(items, list)
    tickers = sorted(
        {
            instrument["canonical_ticker"]
            for item in items
            if isinstance(item, dict)
            and isinstance((instrument := item.get("instrument")), dict)
            and isinstance(instrument.get("canonical_ticker"), str)
        },
        key=str.encode,
    )
    return {
        "bucket_id": "reports",
        "report_key": key,
        "report_type": "decision-board",
        "report_date": "2026-08-13",
        "duplicate_index": 0,
        "generated_at": None,
        "summary": None,
        "tickers": tickers,
        "tickers_hydrated": True,
        "run_kind": report["run_kind"],
        "run_id": report["run_id"],
        "idempotency_key": report["idempotency_key"],
        "decision_created_at": report["created_at"],
    }


def test_privacy_sentinels_do_not_cross_integrated_public_boundaries(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    snapshot = _private_snapshot()
    assert snapshot.holdings[0].quantity == SENTINELS["quantity"]
    assert snapshot.holdings[0].entry_price == SENTINELS["entry_price"]
    assert snapshot.holdings[0].notes == SENTINELS["notes"]
    assert SENTINELS["tags"] in snapshot.holdings[0].tags
    approval = approve_swing_snapshot_v0(snapshot, _registry(), now=NOW)
    assert type(approval[0]) is SwingApprovedV0
    research_projection = project_research_instruments_v0(approval)
    _scan("research projection", research_projection)

    instrument = approval[0].approved_ref.instrument
    research_input = ResearchInputV0(
        instruments=(instrument,),
        questions=(ResearchQuestionV0.RECENT_MATERIAL_DEVELOPMENTS,),
    )
    search_provider = _PublicSearchProvider()
    assert search_provider.toss_secret == SENTINELS["toss_secret"]
    assert search_provider.api_secret == SENTINELS["api_secret"]
    article_verifier = _PublicArticleVerifier()
    research = asyncio.run(
        EvidenceResearcherV0(search_provider, article_verifier).research(research_input)
    )
    assert type(research) is ResearchCompletedV0
    article = research.items[0].articles[0]  # type: ignore[union-attr]
    source = article.source
    _scan("research request", search_provider.requests)
    _scan("article request", article_verifier.requests)
    _scan("research result", repr(research))

    claim_request = ClaimRequestV0(
        claim_id="claim-aurora-guidance",
        instrument=instrument,
        claim_text="Aurora raised its synthetic guidance.",
        action_changing=True,
    )
    claim_verifier = _PublicClaimVerifier()
    claim_result = asyncio.run(
        validate_claim_v0(
            claim_request,
            article,
            expected_source=source,
            policy=research_input.source_policy,
            verifier=claim_verifier,
            deadline=Deadline.start(monotonic=lambda: 100.0),
        )
    )
    assert type(claim_result) is ClaimValidationSucceededV0
    validation = claim_result.validation
    _scan("verifier request", claim_verifier.requests)
    _scan("recorded verifier trace", claim_verifier.requests)
    _scan("claim validation", validation.to_public_dict())

    evidence = CompilerEvidenceV0.create(
        kind=CompilerEvidenceKindV0.SUPPORTIVE,
        validation=validation,
        request=claim_request,
        article=article,
        expected_source=source,
        policy=research_input.source_policy,
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
        research_state=ResearchStateV0.CLEAR,
    )
    run_request = create_decision_run_request_v0(
        run_kind=RunKindV0.ENTRY,
        run_id="entry-privacy-20260813T030000Z",
        idempotency_key="sha256:" + "a" * 64,
        created_at=NOW,
        sealed_input_hash="sha256:" + "b" * 64,
        items=(item,),
        selection=None,
        upload_mode=UploadModeV0.OPTIONAL,
        metadata={
            "policy_version": "decision-policy.v0",
            "researcher_version": "synthetic-researcher-v0",
            "verifier_version": "synthetic-verifier-v0",
        },
    )
    enricher = _EvidenceEnricher(evidence)
    uploader = _CapturingUploader()
    runner = DecisionBoardRunnerV0(
        preparer=_Prepared(),
        enricher=enricher,
        report_dir=tmp_path / "reports",
        uploader=uploader,
    )
    terminal = runner.run(run_request)
    assert type(terminal) is DecisionRunPublishedV0
    _scan("compiler payload", terminal.envelope["decision_payload"])
    _scan("runner terminal", serialize_decision_run_result_v0(terminal))
    _scan("canonical local artifact", terminal.local_path.read_bytes())
    _scan("runner upload", uploader.requests)
    _scan("enrichment request", [repr(value) for value in enricher.requests])

    storage_key = build_decision_board_storage_key(terminal.envelope)
    storage_session = _StorageSession(_index_row(terminal.envelope, storage_key))
    storage_config = SupabaseStorageConfig(
        url="https://project.supabase.co",
        service_role_key=SENTINELS["supabase_secret"],
        bucket="reports",
    )
    assert storage_config.service_role_key == SENTINELS["supabase_secret"]
    assert (
        upload_decision_board_report(
            local_path=terminal.local_path,
            storage_key=storage_key,
            config=storage_config,
            session=storage_session,  # type: ignore[arg-type]
        )
        == storage_key
    )
    _scan("Storage upload body", storage_session.posts[0]["data"])
    _scan("Storage object key", storage_session.posts[0]["url"])
    _scan("report index metadata", storage_session.posts[1]["data"])

    journal_store = RunJournalStoreV0(tmp_path / "journal")
    started = journal_store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=NOW,
        run_id=run_request.run_id,
        started_at=NOW + timedelta(seconds=1),
        grace_seconds=60,
        stale_seconds=300,
    )
    finished = journal_store.finish(
        started,
        status=RunJournalStatusV0.PUBLISHED,
        terminal_at=NOW + timedelta(seconds=2),
        report_file=terminal.local_path.name,
    )
    _scan("RunJournal public output", serialize_run_journal_v0(finished))
    for journal_path in (tmp_path / "journal").glob("*.json"):
        _scan("RunJournal artifact", journal_path.read_bytes())

    journal_path = next((tmp_path / "journal").glob("*.json"))
    orphan_backup = journal_path.parent / f".{journal_path.name}.{'a' * 24}.backup"
    os.link(journal_path, orphan_backup)
    assert journal_store.status(limit=1)[0].run_id == run_request.run_id
    assert not orphan_backup.exists()

    class _ExplodingPreparer:
        def prepare(self, _request: object):
            raise RuntimeError(
                " ".join(
                    (
                        SENTINELS["provider_exception"],
                        SENTINELS["traceback"],
                        SENTINELS["absolute_path"],
                        SENTINELS["private_url"],
                    )
                )
            )

    logging.getLogger("privacy-mutation-control").error(SENTINELS["provider_exception"])
    with pytest.raises(AssertionError, match="privacy leak at mutation log"):
        _scan("mutation log", [record.getMessage() for record in caplog.records])
    caplog.clear()
    sanitized = DecisionBoardRunnerV0(
        preparer=_ExplodingPreparer(),
        enricher=enricher,
        report_dir=tmp_path / "failed",
    ).run(run_request)
    _scan("sanitized exception", serialize_decision_run_result_v0(sanitized))
    failure_logs = [record.getMessage() for record in caplog.records]
    assert failure_logs == []
    _scan("failure logs", failure_logs)


@pytest.mark.parametrize(
    ("label", "container", "field"),
    [
        ("account_id", "snapshot", "account_id"),
        ("account_number", "snapshot", "account_number"),
        ("pnl", "holding", "pnl"),
    ],
)
def test_private_snapshot_schema_rejects_unsupported_private_fields(
    label: str, container: str, field: str
) -> None:
    holdings = [dict(_private_snapshot().holdings[0])]
    digest = broker_holdings_digest_v0(holdings)
    raw = {
        "state_key": "toss-sync:success:MIXED:2026-08-13",
        "session_date": "2026-08-13",
        "status": "applied",
        "fresh_until": (NOW + timedelta(minutes=5)).isoformat(),
        "sealed_at": (NOW - timedelta(minutes=1)).isoformat(),
        "holdings_digest": digest,
        "revision": 13,
        "marker": {
            "scope": "MIXED",
            "sessionDate": "2026-08-13",
            "status": "applied",
            "snapshotDigest": digest,
            "snapshotRevision": 13,
            "sealedAt": (NOW - timedelta(minutes=1)).isoformat(),
        },
        "holdings": holdings,
    }
    if container == "snapshot":
        raw[field] = SENTINELS[label]
    else:
        holdings[0][field] = SENTINELS[label]

    with pytest.raises(Exception) as caught:
        validate_broker_snapshot_v0([raw], now=NOW, expected_session_date="2026-08-13")
    assert SENTINELS[label] not in str(caught.value)


@pytest.mark.parametrize(
    ("label", "field", "value"),
    [
        ("raw_article", "normalized_text", SENTINELS["raw_article"]),
        ("local_url", "canonical_url", SENTINELS["local_url"]),
        ("private_url", "canonical_url", SENTINELS["private_url"]),
    ],
)
def test_research_boundary_mutations_are_detected_or_rejected(
    label: str, field: str, value: str
) -> None:
    if field == "normalized_text":
        with pytest.raises(AssertionError) as caught:
            _scan("article public boundary", value)
        assert str(caught.value) == f"privacy leak at article public boundary: {label}"
        return
    with pytest.raises(ValueError) as rejected:
        create_source_candidate_v0(
            instrument=_instrument(),
            title="Rejected private source",
            canonical_url=value,
            publisher="Synthetic Wire",
            published_at=NOW,
            purpose=SourcePurposeV0.ACTION_CHANGING,
        )
    assert value not in str(rejected.value)


def test_raw_article_sentinel_is_removed_by_real_html_fetch_normalization() -> None:
    source = create_source_candidate_v0(
        instrument=_instrument(),
        title="Raw article rejection",
        canonical_url="https://evidence.example/raw-article",
        publisher="Synthetic Wire",
        published_at=NOW,
        purpose=SourcePurposeV0.ACTION_CHANGING,
    )

    class _Resolver:
        async def resolve(self, _hostname: str, _port: int, *, timeout: float):
            del timeout
            return ("93.184.216.34",)

    class _Fetcher:
        async def fetch(
            self,
            _url: str,
            _addresses: tuple[str, ...],
            *,
            timeout: float,
            max_bytes: int,
        ):
            del timeout, max_bytes
            return ArticleFetchResponseV0(
                status_code=200,
                content_type="text/html; charset=utf-8",
                content_encoding=None,
                body=(
                    f"<html><script>{SENTINELS['raw_article']}</script>"
                    f"<style>{SENTINELS['raw_article']}</style>"
                    f"<body>{PUBLIC_ARTICLE}</body></html>"
                ).encode(),
                location=None,
            )

    verifier = SafeArticleVerifierV0(_Resolver(), _Fetcher())  # type: ignore[arg-type]
    article = asyncio.run(
        verifier.verify(
            source,
            deadline=Deadline.start(monotonic=lambda: 100.0),
            policy=ResearchSourcePolicyV0(),
        )
    )
    assert article.normalized_text == PUBLIC_ARTICLE
    _scan("normalized fetched article", repr(article))

    claim_request = ClaimRequestV0(
        claim_id="claim-raw-normalization",
        instrument=_instrument(),
        claim_text="Aurora raised its synthetic guidance.",
        action_changing=True,
    )
    claim_verifier = _PublicClaimVerifier()
    validation = asyncio.run(
        validate_claim_v0(
            claim_request,
            article,
            expected_source=source,
            policy=ResearchSourcePolicyV0(),
            verifier=claim_verifier,
            deadline=Deadline.start(monotonic=lambda: 100.0),
        )
    )
    assert type(validation) is ClaimValidationSucceededV0
    _scan("normalized article verifier trace", claim_verifier.requests)
    assert PUBLIC_ARTICLE in json.dumps(claim_verifier.requests, ensure_ascii=False)


@pytest.mark.parametrize(("label", "sentinel"), SENTINELS.items())
def test_privacy_scanner_rejects_case_and_separator_mutations(
    label: str, sentinel: str
) -> None:
    mutated = "_._".join(sentinel.swapcase())

    with pytest.raises(AssertionError) as caught:
        _scan("mutation boundary", mutated)

    assert str(caught.value) == f"privacy leak at mutation boundary: {label}"
    assert sentinel not in str(caught.value)
