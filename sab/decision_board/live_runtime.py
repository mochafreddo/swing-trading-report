"""Environment-owned composition root for the explicit live shadow command."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from sab.report.supabase_storage import (
    SupabaseStorageConfig,
    upload_decision_board_report,
)
from sab.research.contracts import ResearchSourcePolicyV0
from sab.research.live_adapters import (
    AiBriefNewsSearchProviderV0,
    AsyncPublicDnsResolverV0,
    PinnedArticleFetcherV0,
)
from sab.research.orchestrator import EvidenceResearcherV0
from sab.research.source_safety import SafeArticleVerifierV0

from .batch_evidence import BatchDecisionEvidenceBuilderV0
from .claim_responses import ResponsesClaimVerifierV0
from .live_adapters import OpenAIResponsesTransportV0
from .live_production import DecisionBoardLiveAdapterV0
from .production_adapter import (
    DecisionBoardAdapterUnavailableError,
    SealedDecisionRunRequestLoaderV0,
)
from .supabase_request import (
    SupabaseDecisionInputConfigV0,
    SupabaseSealedRequestSourceV0,
    SupabaseSnapshotDownloaderV0,
)

_REQUIRED_PROVIDER_KEYS = (
    "FINNHUB_API_KEY",
    "POLYGON_API_KEY",
    "BENZINGA_API_TOKEN",
)


@dataclass(frozen=True, slots=True)
class SupabaseDecisionBoardUploaderV0:
    config: SupabaseStorageConfig = field(repr=False)

    def upload(self, *, local_path: Path, storage_key: str) -> str:
        return upload_decision_board_report(
            local_path=local_path,
            storage_key=storage_key,
            config=self.config,
        )


def build_decision_board_live_adapter_from_env_v0() -> DecisionBoardLiveAdapterV0:
    """Build dependencies only for the explicit live command or fail closed."""

    supabase = SupabaseDecisionInputConfigV0.from_env()
    if any(not _env_value(name) for name in _REQUIRED_PROVIDER_KEYS):
        raise DecisionBoardAdapterUnavailableError(
            "Decision Board news provider config is unavailable"
        )
    openai_key = _env_value("OPENAI_API_KEY")
    model = _env_value("DECISION_BOARD_OPENAI_MODEL") or _env_value(
        "OPENAI_AI_BRIEF_MODEL"
    )
    if not openai_key or not model:
        raise DecisionBoardAdapterUnavailableError(
            "Decision Board claim verifier config is unavailable"
        )
    policy = ResearchSourcePolicyV0()
    researcher = EvidenceResearcherV0(
        AiBriefNewsSearchProviderV0(),
        SafeArticleVerifierV0(
            resolver=AsyncPublicDnsResolverV0(),
            fetcher=PinnedArticleFetcherV0(),
            policy=policy,
        ),
    )
    builder = BatchDecisionEvidenceBuilderV0(
        researcher=researcher,
        claim_verifier=ResponsesClaimVerifierV0(
            transport=OpenAIResponsesTransportV0(api_key=openai_key),
            model=model,
        ),
        source_policy=policy,
    )
    storage_config = SupabaseStorageConfig(
        url=supabase.url,
        service_role_key=supabase.service_role_key,
        bucket=supabase.bucket,
        timeout_seconds=supabase.timeout_seconds,
    )
    return DecisionBoardLiveAdapterV0(
        request_loader=SealedDecisionRunRequestLoaderV0(
            SupabaseSealedRequestSourceV0(
                downloader=SupabaseSnapshotDownloaderV0(supabase)
            )
        ),
        evidence_builder=builder,
        uploader=SupabaseDecisionBoardUploaderV0(storage_config),
    )


def _env_value(name: str) -> str | None:
    value = str(os.getenv(name) or "").strip()
    return value or None


__all__ = [
    "SupabaseDecisionBoardUploaderV0",
    "build_decision_board_live_adapter_from_env_v0",
]
