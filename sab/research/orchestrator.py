"""Bounded deterministic research orchestration for public instruments."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from sab.decision_board.instruments import (
    InstrumentRefV0,
    copy_trusted_instrument_ref_v0,
)

from .contracts import (
    MAX_ARTICLE_ATTEMPTS,
    ResearchInputV0,
    ResearchSourcePolicyV0,
    SearchRequestV0,
    SourceCandidateV0,
    build_search_request_v0,
    copy_research_source_policy_v0,
    parse_search_response_v0,
    validate_and_copy_source_candidate_v0,
)
from .deadline import (
    DEFAULT_RESEARCH_BUDGET_SECONDS,
    Deadline,
    DeadlineExpiredError,
    DeadlineInvariantError,
    MonotonicClock,
)
from .source_safety import (
    ArticleArtifactV0,
    ArticleArtifactValidationError,
    ArticlePreflightError,
    ArticleSafetyError,
    create_article_artifact_v0,
    validate_and_copy_article_artifact_v0,
)

MAX_PROVIDER_CONCURRENCY = 2


class SearchProviderOperationalError(RuntimeError):
    """An expected per-instrument provider failure."""


class SearchProviderTimeoutError(SearchProviderOperationalError):
    """An expected per-instrument provider timeout."""


class SearchProviderV0(Protocol):
    async def search(
        self,
        request: SearchRequestV0,
        *,
        deadline: Deadline,
    ) -> object: ...


class ArticleVerifierV0(Protocol):
    def preflight(self, policy: ResearchSourcePolicyV0) -> None: ...

    async def verify(
        self,
        source: SourceCandidateV0,
        *,
        deadline: Deadline,
        policy: ResearchSourcePolicyV0,
    ) -> ArticleArtifactV0: ...


class ResearchIssueCodeV0(StrEnum):
    ARTICLE_ATTEMPT_LIMIT = "ARTICLE_ATTEMPT_LIMIT"
    ARTICLE_EMPTY = "ARTICLE_EMPTY"
    ARTICLE_ENCODING_INVALID = "ARTICLE_ENCODING_INVALID"
    ARTICLE_TEXT_TOO_LARGE = "ARTICLE_TEXT_TOO_LARGE"
    ARTICLE_TIMEOUT = "ARTICLE_TIMEOUT"
    CONTENT_ENCODING_UNSAFE = "CONTENT_ENCODING_UNSAFE"
    CONTENT_TYPE_UNSAFE = "CONTENT_TYPE_UNSAFE"
    DEADLINE_INVARIANT = "DEADLINE_INVARIANT"
    DNS_INVALID = "DNS_INVALID"
    DNS_NOT_PUBLIC = "DNS_NOT_PUBLIC"
    DNS_TIMEOUT = "DNS_TIMEOUT"
    FETCH_RESPONSE_INVALID = "FETCH_RESPONSE_INVALID"
    FETCH_TIMEOUT = "FETCH_TIMEOUT"
    HTTP_STATUS_UNUSABLE = "HTTP_STATUS_UNUSABLE"
    NO_SOURCE_CANDIDATES = "NO_SOURCE_CANDIDATES"
    NO_VERIFIED_ARTICLE = "NO_VERIFIED_ARTICLE"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    PROVIDER_RESULT_MALFORMED = "PROVIDER_RESULT_MALFORMED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    REDIRECT_INVALID = "REDIRECT_INVALID"
    REDIRECT_LIMIT = "REDIRECT_LIMIT"
    REDIRECT_UNSAFE = "REDIRECT_UNSAFE"
    RESEARCH_INPUT_INVALID = "RESEARCH_INPUT_INVALID"
    RESEARCH_INVARIANT = "RESEARCH_INVARIANT"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    SOURCE_INVALID = "SOURCE_INVALID"
    SOURCE_URL_UNSAFE = "SOURCE_URL_UNSAFE"
    VERIFIER_CONFIG_UNSAFE = "VERIFIER_CONFIG_UNSAFE"
    VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"


_ISSUE_MESSAGES = {
    code: {
        ResearchIssueCodeV0.RESEARCH_INPUT_INVALID: "Research input is invalid.",
        ResearchIssueCodeV0.RESEARCH_INVARIANT: "Research internal invariant failed.",
        ResearchIssueCodeV0.DEADLINE_INVARIANT: "Research deadline invariant failed.",
        ResearchIssueCodeV0.VERIFIER_CONFIG_UNSAFE: "Article verifier configuration is unsafe.",
        ResearchIssueCodeV0.VERIFIER_UNAVAILABLE: "Article verifier is unavailable.",
        ResearchIssueCodeV0.PROVIDER_TIMEOUT: "Search provider timed out.",
        ResearchIssueCodeV0.PROVIDER_FAILED: "Search provider failed.",
        ResearchIssueCodeV0.PROVIDER_RESULT_MALFORMED: "Search provider result is malformed.",
        ResearchIssueCodeV0.NO_SOURCE_CANDIDATES: "No source candidates were returned.",
        ResearchIssueCodeV0.ARTICLE_ATTEMPT_LIMIT: "Article attempt limit was reached.",
        ResearchIssueCodeV0.ARTICLE_TIMEOUT: "Article verification timed out.",
        ResearchIssueCodeV0.NO_VERIFIED_ARTICLE: "No safely retrieved article is available.",
    }.get(code, "Public article retrieval failed safely.")
    for code in ResearchIssueCodeV0
}

_ARTICLE_SAFETY_ISSUE_CODES = frozenset(
    {
        ResearchIssueCodeV0.ARTICLE_EMPTY,
        ResearchIssueCodeV0.ARTICLE_ENCODING_INVALID,
        ResearchIssueCodeV0.ARTICLE_TEXT_TOO_LARGE,
        ResearchIssueCodeV0.CONTENT_ENCODING_UNSAFE,
        ResearchIssueCodeV0.CONTENT_TYPE_UNSAFE,
        ResearchIssueCodeV0.DNS_INVALID,
        ResearchIssueCodeV0.DNS_NOT_PUBLIC,
        ResearchIssueCodeV0.DNS_TIMEOUT,
        ResearchIssueCodeV0.FETCH_RESPONSE_INVALID,
        ResearchIssueCodeV0.FETCH_TIMEOUT,
        ResearchIssueCodeV0.HTTP_STATUS_UNUSABLE,
        ResearchIssueCodeV0.REDIRECT_INVALID,
        ResearchIssueCodeV0.REDIRECT_LIMIT,
        ResearchIssueCodeV0.REDIRECT_UNSAFE,
        ResearchIssueCodeV0.RESPONSE_TOO_LARGE,
        ResearchIssueCodeV0.SOURCE_INVALID,
        ResearchIssueCodeV0.SOURCE_URL_UNSAFE,
    }
)
_PREFLIGHT_ISSUE_CODES = frozenset(
    {
        ResearchIssueCodeV0.VERIFIER_CONFIG_UNSAFE,
        ResearchIssueCodeV0.VERIFIER_UNAVAILABLE,
    }
)
_SUCCESS_ISSUE_CODES = _ARTICLE_SAFETY_ISSUE_CODES | {
    ResearchIssueCodeV0.ARTICLE_ATTEMPT_LIMIT,
    ResearchIssueCodeV0.ARTICLE_TIMEOUT,
}
_NO_USABLE_SOURCE_ISSUE_CODES = _SUCCESS_ISSUE_CODES | {
    ResearchIssueCodeV0.NO_SOURCE_CANDIDATES,
    ResearchIssueCodeV0.NO_VERIFIED_ARTICLE,
}
_TIMED_OUT_ISSUE_CODES = _SUCCESS_ISSUE_CODES | {
    ResearchIssueCodeV0.ARTICLE_TIMEOUT,
    ResearchIssueCodeV0.PROVIDER_TIMEOUT,
}
_FAILED_ISSUE_CODES = frozenset(
    {
        ResearchIssueCodeV0.DEADLINE_INVARIANT,
        ResearchIssueCodeV0.RESEARCH_INPUT_INVALID,
        ResearchIssueCodeV0.RESEARCH_INVARIANT,
    }
)


@dataclass(frozen=True, slots=True, init=False)
class ResearchIssueV0:
    code: ResearchIssueCodeV0
    message: str


@dataclass(frozen=True, slots=True, init=False)
class ResearchItemSucceededV0:
    instrument: InstrumentRefV0
    articles: tuple[ArticleArtifactV0, ...]
    issues: tuple[ResearchIssueV0, ...] = ()
    status: Literal["SUCCEEDED"] = field(default="SUCCEEDED", init=False)

    def __new__(cls) -> ResearchItemSucceededV0:
        del cls
        raise TypeError("successful research results require the trusted factory")


def _create_research_item_succeeded_v0(
    *,
    instrument: InstrumentRefV0,
    articles: tuple[ArticleArtifactV0, ...],
    expected_sources: tuple[SourceCandidateV0, ...],
    policy: ResearchSourcePolicyV0,
    issues: tuple[ResearchIssueV0, ...] = (),
) -> ResearchItemSucceededV0:
    """Create one success result from policy-bound trusted artifact copies."""

    trusted_instrument = _require_exact_instrument(instrument)
    trusted_policy = _copy_required_policy(policy)
    if type(articles) is not tuple or not articles:
        raise TypeError("successful research artifacts must be a non-empty exact tuple")
    if type(expected_sources) is not tuple or len(expected_sources) != len(articles):
        raise TypeError("successful research artifact baselines are invalid")
    trusted_articles: list[ArticleArtifactV0] = []
    for article, expected_source in zip(articles, expected_sources, strict=True):
        if type(article) is not ArticleArtifactV0:
            raise TypeError("successful research artifact is invalid")
        try:
            trusted_source = validate_and_copy_source_candidate_v0(
                expected_source,
                expected_instrument=trusted_instrument,
            )
            trusted_articles.append(
                validate_and_copy_article_artifact_v0(
                    article,
                    expected_source=trusted_source,
                    policy=trusted_policy,
                )
            )
        except (
            ArticleArtifactValidationError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            raise TypeError("successful research artifact is invalid") from None
    try:
        _require_issues(issues, allowed=_SUCCESS_ISSUE_CODES)
    except AttributeError, TypeError, ValueError:
        raise TypeError("successful research issues are invalid") from None
    trusted_issues = tuple(_issue(issue.code) for issue in issues)
    result = object.__new__(ResearchItemSucceededV0)
    object.__setattr__(result, "instrument", trusted_instrument)
    object.__setattr__(result, "articles", tuple(trusted_articles))
    object.__setattr__(result, "issues", trusted_issues)
    object.__setattr__(result, "status", "SUCCEEDED")
    return result


@dataclass(frozen=True, slots=True)
class ResearchItemNoUsableSourceV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["NO_USABLE_SOURCE"] = field(default="NO_USABLE_SOURCE", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument", _require_exact_instrument(self.instrument)
        )
        _require_issues(
            self.issues,
            allowed=_NO_USABLE_SOURCE_ISSUE_CODES,
            nonempty=True,
        )


@dataclass(frozen=True, slots=True)
class ResearchItemTimedOutV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["TIMED_OUT"] = field(default="TIMED_OUT", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument", _require_exact_instrument(self.instrument)
        )
        _require_issues(
            self.issues,
            allowed=_TIMED_OUT_ISSUE_CODES,
            nonempty=True,
        )
        if not any(
            issue.code
            in {
                ResearchIssueCodeV0.ARTICLE_TIMEOUT,
                ResearchIssueCodeV0.PROVIDER_TIMEOUT,
            }
            for issue in self.issues
        ):
            raise ValueError("timed out research requires at least one timeout issue")


@dataclass(frozen=True, slots=True)
class ResearchItemMalformedV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["MALFORMED_PROVIDER_RESULT"] = field(
        default="MALFORMED_PROVIDER_RESULT", init=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument", _require_exact_instrument(self.instrument)
        )
        _require_issues(
            self.issues,
            allowed=frozenset({ResearchIssueCodeV0.PROVIDER_RESULT_MALFORMED}),
            nonempty=True,
        )


@dataclass(frozen=True, slots=True)
class ResearchItemProviderFailedV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["PROVIDER_FAILED"] = field(default="PROVIDER_FAILED", init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "instrument", _require_exact_instrument(self.instrument)
        )
        _require_issues(
            self.issues,
            allowed=frozenset({ResearchIssueCodeV0.PROVIDER_FAILED}),
            nonempty=True,
        )


type ResearchItemResultV0 = (
    ResearchItemSucceededV0
    | ResearchItemNoUsableSourceV0
    | ResearchItemTimedOutV0
    | ResearchItemMalformedV0
    | ResearchItemProviderFailedV0
)

_ITEM_RESULT_TYPES = {
    ResearchItemSucceededV0,
    ResearchItemNoUsableSourceV0,
    ResearchItemTimedOutV0,
    ResearchItemMalformedV0,
    ResearchItemProviderFailedV0,
}


@dataclass(frozen=True, slots=True, init=False)
class ResearchCompletedV0:
    items: tuple[ResearchItemResultV0, ...]
    status: Literal["COMPLETED"] = field(default="COMPLETED", init=False)

    def __new__(cls) -> ResearchCompletedV0:
        del cls
        raise TypeError("completed research results require the trusted factory")


def _create_research_completed_v0(
    *,
    items: tuple[ResearchItemResultV0, ...],
    instruments: tuple[InstrumentRefV0, ...],
    expected_source_baselines: tuple[tuple[SourceCandidateV0, ...], ...],
    policy: ResearchSourcePolicyV0,
) -> ResearchCompletedV0:
    """Deep-validate and copy one invocation-owned completed result."""

    trusted_policy = _copy_required_policy(policy)
    if type(instruments) is not tuple or not instruments:
        raise TypeError("completed research instrument order is invalid")
    try:
        trusted_instruments = tuple(
            _require_exact_instrument(instrument) for instrument in instruments
        )
    except AttributeError, TypeError, ValueError:
        raise TypeError("completed research instrument order is invalid") from None
    if len(set(trusted_instruments)) != len(trusted_instruments):
        raise ValueError("completed research instrument order is invalid")
    if (
        type(items) is not tuple
        or type(expected_source_baselines) is not tuple
        or len(items) != len(trusted_instruments)
        or len(expected_source_baselines) != len(trusted_instruments)
    ):
        raise TypeError("completed research item shape is invalid")

    trusted_items: list[ResearchItemResultV0] = []
    for item, instrument, source_baselines in zip(
        items,
        trusted_instruments,
        expected_source_baselines,
        strict=True,
    ):
        if type(source_baselines) is not tuple or type(item) not in _ITEM_RESULT_TYPES:
            raise TypeError("completed research item is invalid")
        try:
            item_instrument = _require_exact_instrument(item.instrument)
            status = item.status
        except AttributeError, TypeError, ValueError:
            raise TypeError("completed research item is invalid") from None
        if item_instrument != instrument:
            raise ValueError("completed research item instrument is invalid")
        try:
            if type(item) is ResearchItemSucceededV0:
                if status != "SUCCEEDED":
                    raise TypeError("completed research item status is invalid")
                trusted_items.append(
                    _create_research_item_succeeded_v0(
                        instrument=instrument,
                        articles=item.articles,
                        expected_sources=source_baselines,
                        issues=item.issues,
                        policy=trusted_policy,
                    )
                )
            elif type(item) is ResearchItemNoUsableSourceV0:
                _require_empty_source_baselines(source_baselines)
                if status != "NO_USABLE_SOURCE":
                    raise TypeError("completed research item status is invalid")
                trusted_items.append(
                    ResearchItemNoUsableSourceV0(
                        instrument=instrument,
                        issues=_copy_issues(
                            item.issues,
                            allowed=_NO_USABLE_SOURCE_ISSUE_CODES,
                            nonempty=True,
                        ),
                    )
                )
            elif type(item) is ResearchItemTimedOutV0:
                _require_empty_source_baselines(source_baselines)
                if status != "TIMED_OUT":
                    raise TypeError("completed research item status is invalid")
                trusted_items.append(
                    ResearchItemTimedOutV0(
                        instrument=instrument,
                        issues=_copy_issues(
                            item.issues,
                            allowed=_TIMED_OUT_ISSUE_CODES,
                            nonempty=True,
                        ),
                    )
                )
            elif type(item) is ResearchItemMalformedV0:
                _require_empty_source_baselines(source_baselines)
                if status != "MALFORMED_PROVIDER_RESULT":
                    raise TypeError("completed research item status is invalid")
                trusted_items.append(
                    ResearchItemMalformedV0(
                        instrument=instrument,
                        issues=_copy_issues(
                            item.issues,
                            allowed=frozenset(
                                {ResearchIssueCodeV0.PROVIDER_RESULT_MALFORMED}
                            ),
                            nonempty=True,
                        ),
                    )
                )
            else:
                _require_empty_source_baselines(source_baselines)
                if status != "PROVIDER_FAILED":
                    raise TypeError("completed research item status is invalid")
                trusted_items.append(
                    ResearchItemProviderFailedV0(
                        instrument=instrument,
                        issues=_copy_issues(
                            item.issues,
                            allowed=frozenset({ResearchIssueCodeV0.PROVIDER_FAILED}),
                            nonempty=True,
                        ),
                    )
                )
        except ArticleArtifactValidationError, AttributeError, TypeError, ValueError:
            raise TypeError("completed research item is invalid") from None

    result = object.__new__(ResearchCompletedV0)
    object.__setattr__(result, "items", tuple(trusted_items))
    object.__setattr__(result, "status", "COMPLETED")
    return result


@dataclass(frozen=True, slots=True)
class ResearchSharedBlockedV0:
    issue: ResearchIssueV0
    status: Literal["BLOCKED"] = field(default="BLOCKED", init=False)

    def __post_init__(self) -> None:
        _require_issues((self.issue,), allowed=_PREFLIGHT_ISSUE_CODES)


@dataclass(frozen=True, slots=True)
class ResearchInputFailedV0:
    issue: ResearchIssueV0
    status: Literal["FAILED"] = field(default="FAILED", init=False)

    def __post_init__(self) -> None:
        _require_issues((self.issue,), allowed=_FAILED_ISSUE_CODES)


type ResearchRunResultV0 = (
    ResearchCompletedV0 | ResearchSharedBlockedV0 | ResearchInputFailedV0
)


@dataclass(frozen=True, slots=True)
class _SearchSucceeded:
    instrument: InstrumentRefV0
    sources: tuple[SourceCandidateV0, ...]


type _SearchOutcome = _SearchSucceeded | ResearchItemResultV0


class EvidenceResearcherV0:
    """Run one bounded public research invocation without workflow side effects."""

    def __init__(
        self,
        provider: SearchProviderV0,
        verifier: ArticleVerifierV0,
        *,
        budget_seconds: float = DEFAULT_RESEARCH_BUDGET_SECONDS,
        monotonic: MonotonicClock = time.monotonic,
    ) -> None:
        self._provider = provider
        self._verifier = verifier
        self._budget_seconds = budget_seconds
        self._monotonic = monotonic

    async def research(self, research_input: ResearchInputV0) -> ResearchRunResultV0:
        try:
            deadline = Deadline.start(
                self._budget_seconds,
                monotonic=self._monotonic,
            )
        except DeadlineInvariantError:
            return _deadline_invariant_failure()
        except Exception:
            return _research_invariant_failure()
        return await self.research_with_deadline(research_input, deadline=deadline)

    async def research_with_deadline(
        self,
        research_input: ResearchInputV0,
        *,
        deadline: Deadline,
    ) -> ResearchRunResultV0:
        """Run with an invocation-owned deadline shared by downstream claim checks."""

        if type(research_input) is not ResearchInputV0:
            return ResearchInputFailedV0(issue=_issue("RESEARCH_INPUT_INVALID"))
        if type(deadline) is not Deadline:
            return _deadline_invariant_failure()
        trusted_input = _copy_research_input(research_input)
        if trusted_input is None:
            return ResearchInputFailedV0(issue=_issue("RESEARCH_INPUT_INVALID"))
        try:
            try:
                self._verifier.preflight(
                    _copy_required_policy(trusted_input.source_policy)
                )
            except ArticlePreflightError as exc:
                deadline.remaining()
                issue_code = ResearchIssueCodeV0(exc.code)
                if issue_code not in _PREFLIGHT_ISSUE_CODES:
                    return _research_invariant_failure()
                return ResearchSharedBlockedV0(issue=_issue(issue_code))
            search_outcomes = await self._search_all(trusted_input, deadline)
            return await self._verify_all(
                search_outcomes,
                deadline,
                instruments=trusted_input.instruments,
                policy=trusted_input.source_policy,
            )
        except DeadlineExpiredError:
            return _create_research_completed_v0(
                items=tuple(
                    _timed_out(instrument) for instrument in trusted_input.instruments
                ),
                instruments=trusted_input.instruments,
                expected_source_baselines=tuple(
                    () for _instrument in trusted_input.instruments
                ),
                policy=trusted_input.source_policy,
            )
        except DeadlineInvariantError:
            return _deadline_invariant_failure()
        except Exception:
            return _research_invariant_failure()

    async def _search_all(
        self,
        research_input: ResearchInputV0,
        deadline: Deadline,
    ) -> tuple[_SearchOutcome, ...]:
        semaphore = asyncio.Semaphore(MAX_PROVIDER_CONCURRENCY)
        tasks = [
            asyncio.create_task(
                self._search_one(
                    research_input,
                    instrument,
                    semaphore=semaphore,
                    deadline=deadline,
                )
            )
            for instrument in research_input.instruments
        ]
        try:
            timeout = deadline.child_timeout()
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            if pending:
                for pending_task in pending:
                    pending_task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            outcomes: list[_SearchOutcome] = []
            for index, completed_task in enumerate(tasks):
                if completed_task not in done or completed_task.cancelled():
                    outcomes.append(_timed_out(research_input.instruments[index]))
                    continue
                try:
                    outcomes.append(completed_task.result())
                except DeadlineInvariantError:
                    for candidate_task in tasks:
                        if not candidate_task.done():
                            candidate_task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
            return tuple(outcomes)
        finally:
            pending_tasks = [task for task in tasks if not task.done()]
            for pending_task in pending_tasks:
                pending_task.cancel()
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

    async def _search_one(
        self,
        research_input: ResearchInputV0,
        instrument: InstrumentRefV0,
        *,
        semaphore: asyncio.Semaphore,
        deadline: Deadline,
    ) -> _SearchOutcome:
        try:
            deadline.remaining()
            async with semaphore:
                deadline.remaining()
                request = build_search_request_v0(research_input, instrument)
                payload = await self._provider.search(request, deadline=deadline)
                deadline.remaining()
        except DeadlineExpiredError:
            return _timed_out(instrument)
        except SearchProviderTimeoutError:
            deadline.remaining()
            return _timed_out(instrument)
        except DeadlineInvariantError:
            raise
        except SearchProviderOperationalError:
            deadline.remaining()
            return ResearchItemProviderFailedV0(
                instrument=instrument,
                issues=(_issue("PROVIDER_FAILED"),),
            )
        try:
            parsed_sources = parse_search_response_v0(
                payload,
                expected_instrument=instrument,
            )
            sources = tuple(
                validate_and_copy_source_candidate_v0(
                    source,
                    expected_instrument=instrument,
                )
                for source in parsed_sources
            )
        except TypeError, ValueError:
            return ResearchItemMalformedV0(
                instrument=instrument,
                issues=(_issue("PROVIDER_RESULT_MALFORMED"),),
            )
        if not sources:
            return ResearchItemNoUsableSourceV0(
                instrument=instrument,
                issues=(_issue("NO_SOURCE_CANDIDATES"),),
            )
        return _SearchSucceeded(instrument=instrument, sources=sources)

    async def _verify_all(
        self,
        search_outcomes: tuple[_SearchOutcome, ...],
        deadline: Deadline,
        *,
        instruments: tuple[InstrumentRefV0, ...],
        policy: ResearchSourcePolicyV0,
    ) -> ResearchCompletedV0:
        articles: list[list[ArticleArtifactV0]] = [[] for _outcome in search_outcomes]
        article_source_baselines: list[list[SourceCandidateV0]] = [
            [] for _outcome in search_outcomes
        ]
        issues: list[list[ResearchIssueV0]] = [[] for _outcome in search_outcomes]
        scheduled: dict[str, list[tuple[int, SourceCandidateV0]]] = {}
        successful = [
            (index, outcome)
            for index, outcome in enumerate(search_outcomes)
            if type(outcome) is _SearchSucceeded
        ]
        max_sources = max(
            (len(outcome.sources) for _, outcome in successful),
            default=0,
        )
        for source_index in range(max_sources):
            for item_index, outcome in successful:
                if source_index >= len(outcome.sources):
                    continue
                source = outcome.sources[source_index]
                attributions = scheduled.get(source.canonical_url)
                if attributions is not None:
                    attributions.append((item_index, source))
                    continue
                if len(scheduled) >= MAX_ARTICLE_ATTEMPTS:
                    issues[item_index].append(_issue("ARTICLE_ATTEMPT_LIMIT"))
                    continue
                scheduled[source.canonical_url] = [(item_index, source)]

        scheduled_batches = tuple(scheduled.values())

        def mark_remaining_article_timeouts(start_index: int) -> None:
            affected_items = {
                item_index
                for remaining_attributions in scheduled_batches[start_index:]
                for item_index, _source in remaining_attributions
            }
            for item_index in sorted(affected_items):
                if not any(
                    issue.code == ResearchIssueCodeV0.ARTICLE_TIMEOUT
                    for issue in issues[item_index]
                ):
                    issues[item_index].append(_issue("ARTICLE_TIMEOUT"))

        for batch_index, attributions in enumerate(scheduled_batches):
            primary_source = attributions[0][1]
            try:
                artifact = await self._verify_one(
                    primary_source,
                    deadline=deadline,
                    policy=policy,
                )
            except DeadlineExpiredError:
                mark_remaining_article_timeouts(batch_index)
                break
            except ArticleSafetyError as exc:
                try:
                    deadline.remaining()
                except DeadlineExpiredError:
                    mark_remaining_article_timeouts(batch_index)
                    break
                try:
                    issue_code = ResearchIssueCodeV0(exc.code)
                except ValueError as error:
                    raise ValueError("article safety issue code is invalid") from error
                if issue_code not in _ARTICLE_SAFETY_ISSUE_CODES:
                    raise ValueError("article safety issue code is invalid") from exc
                for item_index, _source in attributions:
                    issues[item_index].append(_issue(issue_code))
                continue
            except DeadlineInvariantError:
                raise
            for item_index, attributed_source in attributions:
                trusted_attributed_source = validate_and_copy_source_candidate_v0(
                    attributed_source,
                    expected_instrument=instruments[item_index],
                )
                articles[item_index].append(
                    create_article_artifact_v0(
                        source=trusted_attributed_source,
                        final_url=artifact.final_url,
                        normalized_text=artifact.normalized_text,
                        policy=policy,
                    )
                )
                article_source_baselines[item_index].append(trusted_attributed_source)

        results: list[ResearchItemResultV0] = []
        for index, search_outcome in enumerate(search_outcomes):
            if not isinstance(search_outcome, _SearchSucceeded):
                results.append(search_outcome)
                continue
            if articles[index]:
                results.append(
                    _create_research_item_succeeded_v0(
                        instrument=search_outcome.instrument,
                        articles=tuple(articles[index]),
                        expected_sources=tuple(article_source_baselines[index]),
                        issues=tuple(issues[index]),
                        policy=policy,
                    )
                )
            elif any(issue.code == "ARTICLE_TIMEOUT" for issue in issues[index]):
                results.append(
                    ResearchItemTimedOutV0(
                        instrument=search_outcome.instrument,
                        issues=tuple(issues[index]),
                    )
                )
            else:
                item_issues = tuple(issues[index]) or (_issue("NO_VERIFIED_ARTICLE"),)
                results.append(
                    ResearchItemNoUsableSourceV0(
                        instrument=search_outcome.instrument,
                        issues=item_issues,
                    )
                )
        return _create_research_completed_v0(
            items=tuple(results),
            instruments=instruments,
            expected_source_baselines=tuple(
                tuple(source_baselines) for source_baselines in article_source_baselines
            ),
            policy=policy,
        )

    async def _verify_one(
        self,
        source: SourceCandidateV0,
        *,
        deadline: Deadline,
        policy: ResearchSourcePolicyV0,
    ) -> ArticleArtifactV0:
        trusted_policy = _copy_required_policy(policy)
        trusted_source = validate_and_copy_source_candidate_v0(
            source,
            expected_instrument=source.instrument,
        )
        verifier_source = validate_and_copy_source_candidate_v0(
            trusted_source,
            expected_instrument=trusted_source.instrument,
        )
        task = asyncio.create_task(
            self._verifier.verify(
                verifier_source,
                deadline=deadline,
                policy=_copy_required_policy(trusted_policy),
            )
        )
        try:
            timeout = deadline.child_timeout()
            _done, pending = await asyncio.wait({task}, timeout=timeout)
            if pending:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise DeadlineExpiredError("article verification timed out")
            artifact = task.result()
            deadline.remaining()
            return validate_and_copy_article_artifact_v0(
                artifact,
                expected_source=trusted_source,
                policy=trusted_policy,
            )
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def _timed_out(instrument: InstrumentRefV0) -> ResearchItemTimedOutV0:
    return ResearchItemTimedOutV0(
        instrument=instrument,
        issues=(_issue("PROVIDER_TIMEOUT"),),
    )


def _deadline_invariant_failure() -> ResearchInputFailedV0:
    return ResearchInputFailedV0(issue=_issue("DEADLINE_INVARIANT"))


def _research_invariant_failure() -> ResearchInputFailedV0:
    return ResearchInputFailedV0(issue=_issue("RESEARCH_INVARIANT"))


def _issue(code: str | ResearchIssueCodeV0) -> ResearchIssueV0:
    try:
        issue_code = ResearchIssueCodeV0(code)
    except ValueError as exc:
        raise ValueError("research issue code is not allowlisted") from exc
    issue = object.__new__(ResearchIssueV0)
    object.__setattr__(issue, "code", issue_code)
    object.__setattr__(issue, "message", _ISSUE_MESSAGES[issue_code])
    return issue


def _copy_research_input(value: ResearchInputV0) -> ResearchInputV0 | None:
    try:
        return ResearchInputV0(
            instruments=value.instruments,
            questions=value.questions,
            source_policy=value.source_policy,
        )
    except AttributeError, TypeError, ValueError:
        return None


def _copy_required_policy(value: object) -> ResearchSourcePolicyV0:
    copied = copy_research_source_policy_v0(value)
    if copied is None:
        raise TypeError("research source policy is not an exact valid V0 value")
    return copied


def _require_exact_instrument(value: object) -> InstrumentRefV0:
    copied = copy_trusted_instrument_ref_v0(value)
    if copied is None:
        raise TypeError("research result requires exact valid InstrumentRefV0")
    return copied


def _require_issues(
    value: object,
    *,
    allowed: frozenset[ResearchIssueCodeV0],
    nonempty: bool = False,
) -> None:
    if type(value) is not tuple or not all(
        type(issue) is ResearchIssueV0
        and type(issue.code) is ResearchIssueCodeV0
        and issue.code in allowed
        and issue.message == _ISSUE_MESSAGES[issue.code]
        for issue in value
    ):
        raise TypeError("research result requires exact allowed typed issues")
    if nonempty and not value:
        raise ValueError("research failure variants require at least one issue")


def _copy_issues(
    value: tuple[ResearchIssueV0, ...],
    *,
    allowed: frozenset[ResearchIssueCodeV0],
    nonempty: bool = False,
) -> tuple[ResearchIssueV0, ...]:
    try:
        _require_issues(value, allowed=allowed, nonempty=nonempty)
        return tuple(_issue(issue.code) for issue in value)
    except AttributeError, TypeError, ValueError:
        raise TypeError("research result issues are invalid") from None


def _require_empty_source_baselines(value: object) -> None:
    if type(value) is not tuple or value:
        raise TypeError("non-success research item cannot carry source baselines")


__all__ = [
    "MAX_PROVIDER_CONCURRENCY",
    "ArticleVerifierV0",
    "EvidenceResearcherV0",
    "ResearchCompletedV0",
    "ResearchInputFailedV0",
    "ResearchIssueCodeV0",
    "ResearchIssueV0",
    "ResearchItemMalformedV0",
    "ResearchItemNoUsableSourceV0",
    "ResearchItemProviderFailedV0",
    "ResearchItemResultV0",
    "ResearchItemSucceededV0",
    "ResearchItemTimedOutV0",
    "ResearchRunResultV0",
    "ResearchSharedBlockedV0",
    "SearchProviderOperationalError",
    "SearchProviderTimeoutError",
    "SearchProviderV0",
]
