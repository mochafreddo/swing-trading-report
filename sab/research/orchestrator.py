"""Bounded deterministic research orchestration for public instruments."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

from sab.decision_board.instruments import InstrumentRefV0, InstrumentRegistryError

from .contracts import (
    MAX_ARTICLE_ATTEMPTS,
    ResearchInputV0,
    SearchRequestV0,
    SourceCandidateV0,
    build_search_request_v0,
    parse_search_response_v0,
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
    ArticlePreflightError,
    ArticleSafetyError,
)

MAX_PROVIDER_CONCURRENCY = 2


class SearchProviderV0(Protocol):
    async def search(
        self,
        request: SearchRequestV0,
        *,
        deadline: Deadline,
    ) -> object: ...


class ArticleVerifierV0(Protocol):
    def preflight(self) -> None: ...

    async def verify(
        self,
        source: SourceCandidateV0,
        *,
        deadline: Deadline,
    ) -> ArticleArtifactV0: ...


@dataclass(frozen=True, slots=True)
class ResearchIssueV0:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ResearchItemSucceededV0:
    instrument: InstrumentRefV0
    articles: tuple[ArticleArtifactV0, ...]
    issues: tuple[ResearchIssueV0, ...] = ()
    status: Literal["SUCCEEDED"] = field(default="SUCCEEDED", init=False)

    def __post_init__(self) -> None:
        _require_exact_instrument(self.instrument)
        if not self.articles:
            raise ValueError("successful research requires at least one article")
        if not all(type(article) is ArticleArtifactV0 for article in self.articles):
            raise TypeError("successful research requires exact article artifacts")
        _require_exact_issues(self.issues)


@dataclass(frozen=True, slots=True)
class ResearchItemNoUsableSourceV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["NO_USABLE_SOURCE"] = field(default="NO_USABLE_SOURCE", init=False)

    def __post_init__(self) -> None:
        _require_exact_instrument(self.instrument)
        _require_nonempty_issues(self.issues)


@dataclass(frozen=True, slots=True)
class ResearchItemTimedOutV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["TIMED_OUT"] = field(default="TIMED_OUT", init=False)

    def __post_init__(self) -> None:
        _require_exact_instrument(self.instrument)
        _require_nonempty_issues(self.issues)


@dataclass(frozen=True, slots=True)
class ResearchItemMalformedV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["MALFORMED_PROVIDER_RESULT"] = field(
        default="MALFORMED_PROVIDER_RESULT", init=False
    )

    def __post_init__(self) -> None:
        _require_exact_instrument(self.instrument)
        _require_nonempty_issues(self.issues)


@dataclass(frozen=True, slots=True)
class ResearchItemProviderFailedV0:
    instrument: InstrumentRefV0
    issues: tuple[ResearchIssueV0, ...]
    status: Literal["PROVIDER_FAILED"] = field(default="PROVIDER_FAILED", init=False)

    def __post_init__(self) -> None:
        _require_exact_instrument(self.instrument)
        _require_nonempty_issues(self.issues)


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


@dataclass(frozen=True, slots=True)
class ResearchCompletedV0:
    items: tuple[ResearchItemResultV0, ...]
    status: Literal["COMPLETED"] = field(default="COMPLETED", init=False)

    def __post_init__(self) -> None:
        if not self.items or not all(
            type(item) in _ITEM_RESULT_TYPES for item in self.items
        ):
            raise ValueError("completed research requires exact typed item results")


@dataclass(frozen=True, slots=True)
class ResearchSharedBlockedV0:
    issue: ResearchIssueV0
    status: Literal["BLOCKED"] = field(default="BLOCKED", init=False)

    def __post_init__(self) -> None:
        if type(self.issue) is not ResearchIssueV0:
            raise TypeError("blocked research requires one typed issue")


@dataclass(frozen=True, slots=True)
class ResearchInputFailedV0:
    issue: ResearchIssueV0
    status: Literal["FAILED"] = field(default="FAILED", init=False)

    def __post_init__(self) -> None:
        if type(self.issue) is not ResearchIssueV0:
            raise TypeError("failed research requires one typed issue")


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
        if type(research_input) is not ResearchInputV0:
            return ResearchInputFailedV0(
                issue=_issue(
                    "RESEARCH_INPUT_INVALID",
                    "Research input did not satisfy the exact public V0 contract.",
                )
            )
        try:
            deadline = Deadline.start(
                self._budget_seconds,
                monotonic=self._monotonic,
            )
        except DeadlineInvariantError:
            return _deadline_invariant_failure()

        try:
            self._verifier.preflight()
        except ArticlePreflightError as exc:
            return ResearchSharedBlockedV0(
                issue=_issue(exc.code, "The shared article verifier is unavailable.")
            )
        except Exception:
            return ResearchSharedBlockedV0(
                issue=_issue(
                    "VERIFIER_UNAVAILABLE",
                    "The shared article verifier is unavailable.",
                )
            )

        try:
            search_outcomes = await self._search_all(research_input, deadline)
            return await self._verify_all(search_outcomes, deadline)
        except DeadlineInvariantError:
            return _deadline_invariant_failure()
        except Exception:
            return ResearchInputFailedV0(
                issue=_issue(
                    "RESEARCH_INVARIANT",
                    "Research stopped because an internal invariant failed.",
                )
            )

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
        except DeadlineExpiredError, TimeoutError:
            return _timed_out(instrument)
        except DeadlineInvariantError:
            raise
        except Exception:
            return ResearchItemProviderFailedV0(
                instrument=instrument,
                issues=(
                    _issue(
                        "PROVIDER_FAILED",
                        "The search provider failed for this public instrument.",
                    ),
                ),
            )
        try:
            sources = parse_search_response_v0(
                payload,
                expected_instrument=instrument,
            )
        except TypeError, ValueError:
            return ResearchItemMalformedV0(
                instrument=instrument,
                issues=(
                    _issue(
                        "PROVIDER_RESULT_MALFORMED",
                        "The search provider returned an invalid public result.",
                    ),
                ),
            )
        if not sources:
            return ResearchItemNoUsableSourceV0(
                instrument=instrument,
                issues=(
                    _issue(
                        "NO_SOURCE_CANDIDATES",
                        "The search provider returned no usable source candidates.",
                    ),
                ),
            )
        return _SearchSucceeded(instrument=instrument, sources=sources)

    async def _verify_all(
        self,
        search_outcomes: tuple[_SearchOutcome, ...],
        deadline: Deadline,
    ) -> ResearchCompletedV0:
        articles: list[list[ArticleArtifactV0]] = [[] for _outcome in search_outcomes]
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
                    issues[item_index].append(
                        _issue(
                            "ARTICLE_ATTEMPT_LIMIT",
                            "The global article verification limit was reached.",
                        )
                    )
                    continue
                scheduled[source.canonical_url] = [(item_index, source)]

        deadline_exhausted = False
        for attributions in scheduled.values():
            primary_source = attributions[0][1]
            try:
                artifact = await self._verify_one(primary_source, deadline=deadline)
            except DeadlineExpiredError:
                deadline_exhausted = True
                for item_index, _source in attributions:
                    issues[item_index].append(
                        _issue(
                            "ARTICLE_TIMEOUT",
                            "Article verification exceeded the shared deadline.",
                        )
                    )
                break
            except ArticleSafetyError as exc:
                for item_index, _source in attributions:
                    issues[item_index].append(
                        _issue(
                            exc.code,
                            "The public article could not be retrieved safely.",
                        )
                    )
                continue
            except DeadlineInvariantError:
                raise
            except Exception:
                for item_index, _source in attributions:
                    issues[item_index].append(
                        _issue(
                            "ARTICLE_VERIFICATION_FAILED",
                            "Article verification failed without a usable artifact.",
                        )
                    )
                continue
            for item_index, attributed_source in attributions:
                articles[item_index].append(replace(artifact, source=attributed_source))

        if deadline_exhausted:
            for item_index, _outcome in successful:
                if not articles[item_index] and not any(
                    issue.code == "ARTICLE_TIMEOUT" for issue in issues[item_index]
                ):
                    issues[item_index].append(
                        _issue(
                            "ARTICLE_TIMEOUT",
                            "Article verification was not started before the deadline.",
                        )
                    )

        results: list[ResearchItemResultV0] = []
        for index, search_outcome in enumerate(search_outcomes):
            if not isinstance(search_outcome, _SearchSucceeded):
                results.append(search_outcome)
                continue
            if articles[index]:
                results.append(
                    ResearchItemSucceededV0(
                        instrument=search_outcome.instrument,
                        articles=tuple(articles[index]),
                        issues=tuple(issues[index]),
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
                item_issues = tuple(issues[index]) or (
                    _issue(
                        "NO_VERIFIED_ARTICLE",
                        "No source produced a safely retrieved article.",
                    ),
                )
                results.append(
                    ResearchItemNoUsableSourceV0(
                        instrument=search_outcome.instrument,
                        issues=item_issues,
                    )
                )
        return ResearchCompletedV0(items=tuple(results))

    async def _verify_one(
        self,
        source: SourceCandidateV0,
        *,
        deadline: Deadline,
    ) -> ArticleArtifactV0:
        task = asyncio.create_task(self._verifier.verify(source, deadline=deadline))
        try:
            timeout = deadline.child_timeout()
            _done, pending = await asyncio.wait({task}, timeout=timeout)
            if pending:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise DeadlineExpiredError("article verification timed out")
            artifact = task.result()
            deadline.remaining()
            if type(artifact) is not ArticleArtifactV0:
                raise ArticleSafetyError(
                    "ARTICLE_ARTIFACT_INVALID",
                    "article verifier returned an invalid artifact",
                )
            return artifact
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


def _timed_out(instrument: InstrumentRefV0) -> ResearchItemTimedOutV0:
    return ResearchItemTimedOutV0(
        instrument=instrument,
        issues=(
            _issue(
                "PROVIDER_TIMEOUT",
                "Search did not complete before the shared deadline.",
            ),
        ),
    )


def _deadline_invariant_failure() -> ResearchInputFailedV0:
    return ResearchInputFailedV0(
        issue=_issue(
            "DEADLINE_INVARIANT",
            "Research stopped because the monotonic clock invariant failed.",
        )
    )


def _issue(code: str, message: str) -> ResearchIssueV0:
    return ResearchIssueV0(code=code, message=message)


def _require_exact_instrument(value: object) -> None:
    if type(value) is not InstrumentRefV0:
        raise TypeError("research result requires exact InstrumentRefV0")
    try:
        InstrumentRefV0(
            market=value.market,
            canonical_ticker=value.canonical_ticker,
            exchange=value.exchange,
            company_name=value.company_name,
            identity_source=value.identity_source,
            identity_version=value.identity_version,
        )
    except (AttributeError, InstrumentRegistryError, TypeError) as exc:
        raise TypeError("research result requires valid InstrumentRefV0") from exc


def _require_exact_issues(value: object) -> None:
    if type(value) is not tuple or not all(
        type(issue) is ResearchIssueV0 for issue in value
    ):
        raise TypeError("research result requires exact typed issues")


def _require_nonempty_issues(value: tuple[ResearchIssueV0, ...]) -> None:
    _require_exact_issues(value)
    if not value:
        raise ValueError("research failure variants require at least one issue")


__all__ = [
    "MAX_PROVIDER_CONCURRENCY",
    "ArticleVerifierV0",
    "EvidenceResearcherV0",
    "ResearchCompletedV0",
    "ResearchInputFailedV0",
    "ResearchIssueV0",
    "ResearchItemMalformedV0",
    "ResearchItemNoUsableSourceV0",
    "ResearchItemProviderFailedV0",
    "ResearchItemResultV0",
    "ResearchItemSucceededV0",
    "ResearchItemTimedOutV0",
    "ResearchRunResultV0",
    "ResearchSharedBlockedV0",
    "SearchProviderV0",
]
