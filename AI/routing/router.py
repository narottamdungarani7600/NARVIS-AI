"""Deterministic orchestration of validation, scoring, ranking, and fallback."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from AI.core.interfaces import EventPublisher
from AI.core.models import AIProvider, AIRequest, ProviderStatus, new_id, utc_now
from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .capabilities import CapabilityMatcher, CompatibilityValidator
from .exceptions import (
    FallbackUnavailableError,
    NoCompatibleProviderError,
    RequestValidationError,
)
from .fallback import FallbackPlanner
from .models import (
    CompatibilityReport,
    ProviderScore,
    RoutingDecision,
    RoutingExplanation,
    RoutingPolicy,
    RoutingSummary,
    SelectionPolicy,
)
from .policy import RequestPolicyValidator
from .scoring import ProviderScorer

AI_REQUEST_ROUTED_EVENT = "ai.request_routed"
AI_PROVIDER_SCORED_EVENT = "ai.provider_scored"
AI_PROVIDER_FALLBACK_EVENT = "ai.provider_fallback"
AI_VALIDATION_FAILED_EVENT = "ai.validation_failed"


class RequestRouter:
    """Route immutable requests using only registered provider descriptions."""

    _HEALTH_RANK = {
        ProviderStatus.AVAILABLE: 0,
        ProviderStatus.DEGRADED: 1,
        ProviderStatus.UNKNOWN: 2,
        ProviderStatus.UNAVAILABLE: 3,
        ProviderStatus.DISABLED: 4,
    }

    def __init__(
        self,
        matcher: CapabilityMatcher | None = None,
        validator: CompatibilityValidator | None = None,
        scorer: ProviderScorer | None = None,
        fallback_planner: FallbackPlanner | None = None,
        policy_validator: RequestPolicyValidator | None = None,
        *,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_id,
    ) -> None:
        resolved_policy_validator = (
            policy_validator
            if policy_validator is not None
            else RequestPolicyValidator()
        )
        if not callable(getattr(resolved_policy_validator, "validate", None)):
            raise TypeError("policy_validator must provide a validate method")
        resolved_matcher = (
            matcher
            if matcher is not None
            else CapabilityMatcher(resolved_policy_validator)
        )
        if not callable(getattr(resolved_matcher, "match", None)):
            raise TypeError("matcher must provide a match method")
        resolved_validator = (
            validator
            if validator is not None
            else CompatibilityValidator(
                resolved_matcher,
                clock=clock,
            )
        )
        if not callable(getattr(resolved_validator, "validate", None)):
            raise TypeError("validator must provide a validate method")
        resolved_scorer = (
            scorer
            if scorer is not None
            else ProviderScorer(
                validator=resolved_validator,
                clock=clock,
            )
        )
        if not callable(getattr(resolved_scorer, "score", None)):
            raise TypeError("scorer must provide a score method")
        resolved_fallback = (
            fallback_planner
            if fallback_planner is not None
            else FallbackPlanner(clock=clock)
        )
        if not all(
            callable(getattr(resolved_fallback, method, None))
            for method in ("plan", "next_provider_id")
        ):
            raise TypeError("fallback_planner does not implement the fallback contract")
        if event_bus is not None and not callable(getattr(event_bus, "publish", None)):
            raise TypeError("event_bus must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")
        self._policy_validator = resolved_policy_validator
        self._matcher = resolved_matcher
        self._validator = resolved_validator
        self._scorer = resolved_scorer
        self._fallback_planner = resolved_fallback
        self._event_bus = event_bus
        self._logger = logger if logger is not None else NullLogger("narvis.ai.routing")
        self._clock = clock
        self._id_factory = id_factory

    @property
    def matcher(self) -> CapabilityMatcher:
        """Return the injected capability matcher."""

        return self._matcher

    @property
    def validator(self) -> CompatibilityValidator:
        """Return the injected compatibility validator."""

        return self._validator

    @property
    def scorer(self) -> ProviderScorer:
        """Return the injected deterministic scorer."""

        return self._scorer

    @property
    def fallback_planner(self) -> FallbackPlanner:
        """Return the injected fallback planner."""

        return self._fallback_planner

    def route(
        self,
        request: AIRequest,
        providers: Iterable[AIProvider],
        policy: RoutingPolicy | None = None,
    ) -> RoutingDecision:
        """Create one routing decision without executing a provider or model."""

        resolved_policy = self._policy(policy)
        self._validate_request(request, resolved_policy)
        candidates = self._providers(providers)
        if not candidates:
            self._validation_failed(
                request.request_id, None, ("no providers registered",)
            )
            raise NoCompatibleProviderError("no providers are registered")
        reports: dict[str, CompatibilityReport] = {}
        scores: dict[str, ProviderScore] = {}
        providers_by_id = {provider.provider_id: provider for provider in candidates}
        for provider in candidates:
            report = self._validator.validate(provider, request, resolved_policy)
            reports[provider.provider_id] = report
            if not report.compatible:
                self._validation_failed(
                    request.request_id,
                    provider.provider_id,
                    report.reasons,
                )
            score = self._scorer.score(
                provider,
                request,
                resolved_policy,
                compatibility=report,
            )
            scores[provider.provider_id] = score
            self._provider_scored(provider, score)
        eligible = tuple(
            score
            for score in scores.values()
            if score.compatible and score.total >= resolved_policy.minimum_score
        )
        if not eligible:
            reason = (
                "no compatible provider met minimum score "
                f"{resolved_policy.minimum_score:.2f}"
            )
            self._validation_failed(request.request_id, None, (reason,))
            raise NoCompatibleProviderError(reason)
        ranked_eligible = tuple(
            sorted(
                eligible,
                key=lambda score: self._rank_key(
                    score,
                    providers_by_id[score.provider_id],
                    request,
                    resolved_policy,
                ),
            )
        )
        ineligible = tuple(
            sorted(
                (score for score in scores.values() if score not in ranked_eligible),
                key=lambda score: (score.provider_id.casefold(), score.provider_id),
            )
        )
        ranked_scores = (*ranked_eligible, *ineligible)
        selected_score = ranked_eligible[0]
        selected_provider = providers_by_id[selected_score.provider_id]
        fallback_plan = self._fallback_planner.plan(
            request.request_id,
            ranked_scores,
            selected_provider.provider_id,
            resolved_policy,
        )
        explanation = self._explain(
            request,
            selected_provider,
            selected_score,
            ranked_scores,
            fallback_plan.provider_ids,
            resolved_policy,
        )
        now = self._now()
        decision = RoutingDecision(
            request=request,
            selected_provider=selected_provider,
            selected_score=selected_score,
            provider_scores=ranked_scores,
            compatibility_reports=tuple(
                reports[score.provider_id] for score in ranked_scores
            ),
            fallback_plan=fallback_plan,
            policy=resolved_policy,
            explanation=explanation,
            decision_id=self._new_id(),
            routed_at=now,
        )
        self._log(
            LogLevel.INFO,
            "AI request routed",
            request_id=request.request_id,
            provider_id=selected_provider.provider_id,
            score=selected_score.total,
            policy=resolved_policy.selection.value,
            fallback_count=len(fallback_plan.provider_ids),
        )
        self._publish(
            AI_REQUEST_ROUTED_EVENT,
            request_id=request.request_id,
            provider_id=selected_provider.provider_id,
            score=selected_score.total,
            policy=resolved_policy.selection.value,
            candidate_count=len(ranked_scores),
            fallback_count=len(fallback_plan.provider_ids),
        )
        return decision

    route_request = route

    def score_provider(
        self,
        provider: AIProvider,
        request: AIRequest,
        policy: RoutingPolicy | None = None,
    ) -> ProviderScore:
        """Validate and score one provider without selecting or invoking it."""

        resolved_policy = self._policy(policy)
        self._validate_request(request, resolved_policy)
        report = self._validator.validate(provider, request, resolved_policy)
        if not report.compatible:
            self._validation_failed(
                request.request_id, provider.provider_id, report.reasons
            )
        score = self._scorer.score(
            provider,
            request,
            resolved_policy,
            compatibility=report,
        )
        self._provider_scored(provider, score)
        return score

    def validate_provider(
        self,
        provider: AIProvider,
        request: AIRequest,
        policy: RoutingPolicy | None = None,
    ) -> CompatibilityReport:
        """Return provider compatibility and publish validation failures safely."""

        resolved_policy = self._policy(policy)
        self._validate_request(request, resolved_policy)
        report = self._validator.validate(provider, request, resolved_policy)
        if not report.compatible:
            self._validation_failed(
                request.request_id, provider.provider_id, report.reasons
            )
        return report

    def fallback(
        self,
        decision: RoutingDecision,
        providers: Iterable[AIProvider],
        current_provider_id: str | None = None,
    ) -> AIProvider:
        """Return the next currently compatible provider from a prior plan."""

        if not isinstance(decision, RoutingDecision):
            raise TypeError("decision must be a RoutingDecision")
        candidates = {
            provider.provider_id: provider for provider in self._providers(providers)
        }
        try:
            remaining = decision.fallback_plan.after(current_provider_id)
        except ValueError as error:
            raise FallbackUnavailableError(str(error)) from error
        for provider_id in remaining:
            provider = candidates.get(provider_id)
            if provider is None:
                continue
            report = self._validator.validate(
                provider,
                decision.request,
                decision.policy,
            )
            if not report.compatible:
                self._validation_failed(
                    decision.request_id,
                    provider.provider_id,
                    report.reasons,
                )
                continue
            score = self._scorer.score(
                provider,
                decision.request,
                decision.policy,
                compatibility=report,
            )
            self._provider_scored(provider, score)
            if score.total < decision.policy.minimum_score:
                continue
            previous = (
                decision.selected_provider_id
                if current_provider_id is None
                else current_provider_id
            )
            self._log(
                LogLevel.INFO,
                "AI provider fallback selected",
                request_id=decision.request_id,
                previous_provider_id=previous,
                provider_id=provider.provider_id,
            )
            self._publish(
                AI_PROVIDER_FALLBACK_EVENT,
                request_id=decision.request_id,
                previous_provider_id=previous,
                provider_id=provider.provider_id,
            )
            return provider
        raise FallbackUnavailableError("no compatible fallback provider remains")

    fallback_provider = fallback

    def summary(self, decision: RoutingDecision) -> RoutingSummary:
        """Generate compact immutable routing facts from a decision."""

        if not isinstance(decision, RoutingDecision):
            raise TypeError("decision must be a RoutingDecision")
        return RoutingSummary(
            request_id=decision.request_id,
            selected_provider_id=decision.selected_provider_id,
            candidate_count=len(decision.provider_scores),
            compatible_count=sum(
                report.compatible for report in decision.compatibility_reports
            ),
            fallback_count=len(decision.fallback_chain),
            selected_score=decision.selected_score.total,
            selection_policy=decision.policy.selection,
            explanation=decision.explanation.summary,
            generated_at=self._now(),
        )

    routing_summary = summary

    def _rank_key(
        self,
        score: ProviderScore,
        provider: AIProvider,
        request: AIRequest,
        policy: RoutingPolicy,
    ) -> tuple[object, ...]:
        identifier = (provider.provider_id.casefold(), provider.provider_id)
        if policy.selection is SelectionPolicy.PRIORITY:
            return (int(provider.priority), -score.total, *identifier)
        if policy.selection is SelectionPolicy.HEALTH:
            return (
                self._HEALTH_RANK[provider.status],
                -score.total,
                int(provider.priority),
                *identifier,
            )
        if policy.selection is SelectionPolicy.CAPABILITY:
            return (
                -score.capability_score,
                -len(provider.capabilities),
                -score.total,
                int(provider.priority),
                *identifier,
            )
        if policy.selection is SelectionPolicy.PREFERRED:
            return (
                0 if provider.provider_id == request.preferred_provider_id else 1,
                -score.total,
                int(provider.priority),
                *identifier,
            )
        return (-score.total, int(provider.priority), *identifier)

    @staticmethod
    def _explain(
        request: AIRequest,
        provider: AIProvider,
        score: ProviderScore,
        ranked_scores: tuple[ProviderScore, ...],
        fallback_ids: tuple[str, ...],
        policy: RoutingPolicy,
    ) -> RoutingExplanation:
        compatible_count = sum(item.compatible for item in ranked_scores)
        summary = (
            f"Selected {provider.provider_id} using {policy.selection.value} policy "
            f"with score {score.total:.2f}."
        )
        fallback_factor = (
            f"fallback chain: {', '.join(fallback_ids)}"
            if fallback_ids
            else "no fallback provider available"
        )
        return RoutingExplanation(
            request_id=request.request_id,
            selected_provider_id=provider.provider_id,
            summary=summary,
            factors=(
                f"{compatible_count} of {len(ranked_scores)} providers compatible",
                f"priority {int(provider.priority)}",
                f"health {provider.status.value}",
                fallback_factor,
            ),
        )

    def _validate_request(self, request: AIRequest, policy: RoutingPolicy) -> None:
        try:
            self._policy_validator.validate(request, policy)
        except (TypeError, ValueError) as error:
            request_id = request.request_id if isinstance(request, AIRequest) else None
            self._validation_failed(request_id, None, (str(error),))
            if isinstance(error, RequestValidationError):
                raise
            raise RequestValidationError(str(error)) from error

    @staticmethod
    def _policy(policy: RoutingPolicy | None) -> RoutingPolicy:
        if policy is None:
            return RoutingPolicy()
        if not isinstance(policy, RoutingPolicy):
            raise TypeError("policy must be a RoutingPolicy or None")
        return policy

    @staticmethod
    def _providers(providers: Iterable[AIProvider]) -> tuple[AIProvider, ...]:
        if isinstance(providers, (str, bytes)):
            raise TypeError("providers must contain AIProvider values")
        try:
            values = tuple(providers)
        except TypeError as error:
            raise TypeError("providers must be iterable") from error
        if any(not isinstance(provider, AIProvider) for provider in values):
            raise TypeError("providers must contain AIProvider values")
        identifiers = tuple(provider.provider_id for provider in values)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("providers cannot contain duplicate identifiers")
        return values

    def _provider_scored(self, provider: AIProvider, score: ProviderScore) -> None:
        self._log(
            LogLevel.DEBUG,
            "AI provider scored",
            request_id=score.request_id,
            provider_id=provider.provider_id,
            score=score.total,
            compatible=score.compatible,
        )
        self._publish(
            AI_PROVIDER_SCORED_EVENT,
            request_id=score.request_id,
            provider_id=provider.provider_id,
            score=score.total,
            compatible=score.compatible,
        )

    def _validation_failed(
        self,
        request_id: str | None,
        provider_id: str | None,
        reasons: tuple[str, ...],
    ) -> None:
        self._log(
            LogLevel.WARNING,
            "AI routing validation failed",
            request_id=request_id,
            provider_id=provider_id,
            reasons=reasons,
        )
        self._publish(
            AI_VALIDATION_FAILED_EVENT,
            request_id=request_id,
            provider_id=provider_id,
            reasons=reasons,
        )

    def _publish(self, event_name: str, **payload: object) -> None:
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=dict(payload)))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish AI routing event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RequestValidationError("clock must return a timezone-aware datetime")
        return value

    def _new_id(self) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value or value != value.strip():
            raise RequestValidationError(
                "id_factory must return a normalized non-empty string"
            )
        return value


DeterministicRouter = RequestRouter
AIRouter = RequestRouter


__all__ = [
    "AIRouter",
    "AI_PROVIDER_FALLBACK_EVENT",
    "AI_PROVIDER_SCORED_EVENT",
    "AI_REQUEST_ROUTED_EVENT",
    "AI_VALIDATION_FAILED_EVENT",
    "DeterministicRouter",
    "RequestRouter",
]
