"""Deterministic model catalog and preference resolution services."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from AI.core.models import AIProvider, AIRequest, utc_now
from Core.logger import LogLevel, Logger, NullLogger

from .events import AI_PREFERENCES_RESOLVED_EVENT, OrchestrationEvents
from .exceptions import PreferenceResolutionError
from .models import (
    ContextSizeMetadata,
    CostMetadata,
    LatencyMetadata,
    ModelOption,
    ModelPreferencePolicy,
    PreferenceResolution,
)


class ProviderModelCatalog:
    """Translate provider metadata into typed model options without discovery."""

    MODEL_OPTIONS_ATTRIBUTE = "model_options"
    COST_ATTRIBUTE = "cost_metadata"
    LATENCY_ATTRIBUTE = "latency_metadata"
    CONTEXT_ATTRIBUTE = "context_size_metadata"

    def options_for(self, provider: AIProvider) -> tuple[ModelOption, ...]:
        """Return declared typed options or a deterministic metadata fallback."""

        if not isinstance(provider, AIProvider):
            raise TypeError("provider must be an AIProvider")
        declared = provider.metadata.attributes.get(self.MODEL_OPTIONS_ATTRIBUTE)
        if declared is not None:
            if isinstance(declared, (str, bytes)):
                raise TypeError("model_options must contain ModelOption values")
            try:
                options = tuple(declared)
            except TypeError as error:
                raise TypeError("model_options must be iterable") from error
            if not options or any(
                not isinstance(item, ModelOption) for item in options
            ):
                raise TypeError("model_options must contain ModelOption values")
            if any(item.provider_id != provider.provider_id for item in options):
                raise ValueError("model options must belong to their provider")
            if provider.metadata.supported_models and any(
                item.model_name is not None
                and item.model_name not in provider.metadata.supported_models
                for item in options
            ):
                raise ValueError("model options must use advertised supported models")
            option_ids = tuple(item.option_id for item in options)
            if len(set(option_ids)) != len(option_ids):
                raise ValueError("model options cannot contain duplicates")
            return options
        cost = provider.metadata.attributes.get(self.COST_ATTRIBUTE, CostMetadata())
        latency = provider.metadata.attributes.get(
            self.LATENCY_ATTRIBUTE,
            LatencyMetadata(),
        )
        context = provider.metadata.attributes.get(
            self.CONTEXT_ATTRIBUTE,
            ContextSizeMetadata(),
        )
        if not isinstance(cost, CostMetadata):
            raise TypeError("cost_metadata must be CostMetadata")
        if not isinstance(latency, LatencyMetadata):
            raise TypeError("latency_metadata must be LatencyMetadata")
        if not isinstance(context, ContextSizeMetadata):
            raise TypeError("context_size_metadata must be ContextSizeMetadata")
        models: tuple[str | None, ...] = (
            provider.metadata.supported_models
            if provider.metadata.supported_models
            else (None,)
        )
        return tuple(
            ModelOption(
                provider_id=provider.provider_id,
                model_name=model,
                capabilities=provider.capabilities,
                cost=cost,
                latency=latency,
                context_size=context,
            )
            for model in models
        )

    def options(self, providers: Iterable[AIProvider]) -> tuple[ModelOption, ...]:
        """Return typed options for a deterministic provider snapshot."""

        if isinstance(providers, (str, bytes)):
            raise TypeError("providers must contain AIProvider values")
        try:
            values = tuple(providers)
        except TypeError as error:
            raise TypeError("providers must be iterable") from error
        if any(not isinstance(item, AIProvider) for item in values):
            raise TypeError("providers must contain AIProvider values")
        identifiers = tuple(item.provider_id for item in values)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("providers cannot contain duplicate identifiers")
        return tuple(
            option for provider in values for option in self.options_for(provider)
        )


class ModelPreferenceResolver:
    """Resolve model preferences using declared metadata and stable ordering."""

    def __init__(
        self,
        catalog: ProviderModelCatalog | None = None,
        events: OrchestrationEvents | None = None,
        *,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        resolved_catalog = catalog if catalog is not None else ProviderModelCatalog()
        if not all(
            callable(getattr(resolved_catalog, method, None))
            for method in ("options", "options_for")
        ):
            raise TypeError("catalog does not implement the model catalog contract")
        resolved_events = events if events is not None else OrchestrationEvents()
        if not callable(getattr(resolved_events, "publish", None)):
            raise TypeError("events must provide a publish method")
        if logger is not None and not callable(getattr(logger, "log", None)):
            raise TypeError("logger must provide a log method")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._catalog = resolved_catalog
        self._events = resolved_events
        self._logger = (
            logger if logger is not None else NullLogger("narvis.ai.preferences")
        )
        self._clock = clock

    @property
    def catalog(self) -> ProviderModelCatalog:
        return self._catalog

    def resolve_for_providers(
        self,
        request: AIRequest,
        providers: Iterable[AIProvider],
        policy: ModelPreferencePolicy | None = None,
    ) -> PreferenceResolution:
        """Resolve preferences across a supplied immutable provider snapshot."""

        return self.resolve(request, self._catalog.options(providers), policy)

    def resolve(
        self,
        request: AIRequest,
        options: Iterable[ModelOption],
        policy: ModelPreferencePolicy | None = None,
    ) -> PreferenceResolution:
        """Select one model option without loading or invoking a model."""

        if not isinstance(request, AIRequest):
            raise TypeError("request must be an AIRequest")
        resolved_policy = policy or ModelPreferencePolicy()
        if not isinstance(resolved_policy, ModelPreferencePolicy):
            raise TypeError("policy must be a ModelPreferencePolicy or None")
        if isinstance(options, (str, bytes)):
            raise TypeError("options must contain ModelOption values")
        try:
            considered = tuple(options)
        except TypeError as error:
            raise TypeError("options must be iterable") from error
        if not considered or any(
            not isinstance(item, ModelOption) for item in considered
        ):
            raise PreferenceResolutionError(
                "preference resolution requires ModelOption values"
            )
        option_ids = tuple(item.option_id for item in considered)
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("options cannot contain duplicate provider/model pairs")
        rejected: dict[str, tuple[str, ...]] = {}
        eligible: list[ModelOption] = []
        for option in considered:
            reasons = self._rejection_reasons(request, option, resolved_policy)
            if reasons:
                rejected[option.option_id] = reasons
            else:
                eligible.append(option)
        if not eligible:
            raise PreferenceResolutionError(
                "no model option satisfies the request preference policy"
            )
        selected = min(
            enumerate(eligible),
            key=lambda item: self._rank_key(item[1], resolved_policy, item[0]),
        )[1]
        factors = self._factors(selected, resolved_policy)
        resolution = PreferenceResolution(
            request_id=request.request_id,
            selected_option=selected,
            considered_options=considered,
            policy=resolved_policy,
            rejected_reasons=rejected,
            factors=factors,
            resolved_at=self._now(),
        )
        self._log(
            LogLevel.INFO,
            "AI model preferences resolved",
            request_id=request.request_id,
            provider_id=selected.provider_id,
            model_name=selected.model_name,
            considered_count=len(considered),
            rejected_count=len(rejected),
        )
        self._events.publish(
            AI_PREFERENCES_RESOLVED_EVENT,
            request_id=request.request_id,
            provider_id=selected.provider_id,
            model_name=selected.model_name,
            considered_count=len(considered),
            rejected_count=len(rejected),
            cost_known=selected.cost.known,
            latency_known=selected.latency.known,
            context_known=selected.context_size.known,
        )
        return resolution

    @staticmethod
    def _rejection_reasons(
        request: AIRequest,
        option: ModelOption,
        policy: ModelPreferencePolicy,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        model = option.model_name
        required_model = policy.required_model
        if required_model is not None and model != required_model:
            reasons.append("model does not match required_model")
        if (
            policy.honor_request_model_hint
            and request.model_hint is not None
            and model != request.model_hint
        ):
            reasons.append("model does not match request model_hint")
        if model is None and not policy.allow_unspecified_model:
            reasons.append("unspecified models are not allowed")
        if model is not None and model in policy.excluded_models:
            reasons.append("model is excluded")
        missing = tuple(
            item
            for item in request.required_capabilities
            if item not in option.capabilities
        )
        if missing:
            reasons.append("model option lacks required capabilities")
        cost = option.cost.estimated_request_cost
        if cost is None and not policy.allow_unknown_cost:
            reasons.append("estimated cost is unknown")
        if (
            cost is not None
            and policy.maximum_estimated_cost is not None
            and cost > policy.maximum_estimated_cost
        ):
            reasons.append("estimated cost exceeds policy maximum")
        latency = option.latency.estimated_latency_ms
        if latency is None and not policy.allow_unknown_latency:
            reasons.append("estimated latency is unknown")
        if (
            latency is not None
            and policy.maximum_latency_ms is not None
            and latency > policy.maximum_latency_ms
        ):
            reasons.append("estimated latency exceeds policy maximum")
        context = option.context_size.max_context_tokens
        if context is None and not policy.allow_unknown_context:
            reasons.append("context size is unknown")
        if (
            context is not None
            and policy.minimum_context_tokens is not None
            and context < policy.minimum_context_tokens
        ):
            reasons.append("context size is below policy minimum")
        return tuple(reasons)

    @staticmethod
    def _rank_key(
        option: ModelOption,
        policy: ModelPreferencePolicy,
        stable_index: int,
    ) -> tuple[object, ...]:
        model = option.model_name
        preferred_rank = (
            policy.preferred_models.index(model)
            if model in policy.preferred_models
            else len(policy.preferred_models)
        )
        cost = option.cost.estimated_request_cost
        cost_rank: tuple[int, float] = (
            (0, cost) if cost is not None else (1, float("inf"))
        )
        latency = option.latency.estimated_latency_ms
        latency_rank: tuple[int, float] = (
            (0, latency) if latency is not None else (1, float("inf"))
        )
        context = option.context_size.max_context_tokens
        context_rank: tuple[int, int] = (0, -context) if context is not None else (1, 0)
        return (
            preferred_rank,
            *(cost_rank if policy.prefer_lower_cost else (0, 0.0)),
            *(latency_rank if policy.prefer_lower_latency else (0, 0.0)),
            *(context_rank if policy.prefer_larger_context else (0, 0)),
            stable_index,
        )

    @staticmethod
    def _factors(
        option: ModelOption,
        policy: ModelPreferencePolicy,
    ) -> tuple[str, ...]:
        return (
            f"selected model {option.model_name or 'unspecified'}",
            f"provider {option.provider_id}",
            f"cost metadata {'known' if option.cost.known else 'unknown'}",
            f"latency metadata {'known' if option.latency.known else 'unknown'}",
            f"context metadata {'known' if option.context_size.known else 'unknown'}",
            f"preferred model ranking {'enabled' if policy.preferred_models else 'neutral'}",
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise PreferenceResolutionError(
                "clock must return a timezone-aware datetime"
            )
        return value

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


PreferenceResolver = ModelPreferenceResolver


__all__ = [
    "ModelPreferenceResolver",
    "PreferenceResolver",
    "ProviderModelCatalog",
]
