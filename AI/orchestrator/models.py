"""Immutable models for deterministic, non-executing AI orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from AI.core.models import (
    AIProvider,
    AIRequest,
    ProviderCapability,
    immutable_mapping,
    new_id,
    utc_now,
)
from AI.routing.models import RoutingDecision, RoutingPolicy


class OrchestrationSessionStatus(str, Enum):
    """Lifecycle states for an architecture-only orchestration session."""

    ACTIVE = "active"
    CREATED = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class OrchestrationPlanStatus(str, Enum):
    """States available to an inert orchestration plan."""

    READY = "ready"
    CANCELLED = "cancelled"


class OrchestrationStepType(str, Enum):
    """Planning-only stages represented in an orchestration plan."""

    VALIDATE_REQUEST = "validate_request"
    ROUTE_PROVIDER = "route_provider"
    RESOLVE_PREFERENCES = "resolve_preferences"
    NEGOTIATE_PROVIDER = "negotiate_provider"
    PREPARE_PLAN = "prepare_plan"


def _text(
    value: object,
    name: str,
    *,
    maximum: int = 256,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (
        value != value.strip()
        or len(value) > maximum
        or (not value and not allow_empty)
    ):
        raise ValueError(
            f"{name} must be normalized text of at most {maximum} characters"
        )
    return value


def _time(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric or None")
    result = float(value)
    if result != result or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _optional_count(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer or None")
    return value


def _identifiers(values: object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be an iterable of strings")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be iterable") from error
    for value in result:
        _text(value, name, maximum=256)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _capabilities(values: object, name: str) -> tuple[ProviderCapability, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must contain ProviderCapability values")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} must be iterable") from error
    if any(not isinstance(item, ProviderCapability) for item in result):
        raise TypeError(f"{name} must contain ProviderCapability values")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _factors(values: object, name: str = "factors") -> tuple[str, ...]:
    result = _identifiers(values, name)
    return result


@dataclass(slots=True, frozen=True)
class CostMetadata:
    """Declared cost facts used only for deterministic comparison and summaries."""

    currency: str = "USD"
    input_cost_per_1000_tokens: float | None = None
    output_cost_per_1000_tokens: float | None = None
    estimated_request_cost: float | None = None

    def __post_init__(self) -> None:
        currency = _text(self.currency, "currency", maximum=8)
        if not currency.isalpha() or currency.upper() != currency:
            raise ValueError("currency must be an uppercase alphabetic code")
        for name in (
            "input_cost_per_1000_tokens",
            "output_cost_per_1000_tokens",
            "estimated_request_cost",
        ):
            object.__setattr__(self, name, _optional_number(getattr(self, name), name))

    @property
    def known(self) -> bool:
        """Return whether any declared cost fact is available."""

        return any(
            value is not None
            for value in (
                self.input_cost_per_1000_tokens,
                self.output_cost_per_1000_tokens,
                self.estimated_request_cost,
            )
        )


@dataclass(slots=True, frozen=True)
class LatencyMetadata:
    """Declared latency estimates; no provider probing is performed."""

    estimated_latency_ms: float | None = None
    p95_latency_ms: float | None = None

    def __post_init__(self) -> None:
        estimate = _optional_number(self.estimated_latency_ms, "estimated_latency_ms")
        p95 = _optional_number(self.p95_latency_ms, "p95_latency_ms")
        if estimate is not None and p95 is not None and p95 < estimate:
            raise ValueError("p95_latency_ms cannot be lower than estimated latency")
        object.__setattr__(self, "estimated_latency_ms", estimate)
        object.__setattr__(self, "p95_latency_ms", p95)

    @property
    def known(self) -> bool:
        """Return whether an estimated latency is declared."""

        return self.estimated_latency_ms is not None


@dataclass(slots=True, frozen=True)
class ContextSizeMetadata:
    """Declared model context and output token limits."""

    max_context_tokens: int | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        context = _optional_count(self.max_context_tokens, "max_context_tokens")
        output = _optional_count(self.max_output_tokens, "max_output_tokens")
        if context is not None and output is not None and output > context:
            raise ValueError("max_output_tokens cannot exceed max_context_tokens")
        object.__setattr__(self, "max_context_tokens", context)
        object.__setattr__(self, "max_output_tokens", output)

    @property
    def known(self) -> bool:
        """Return whether a context limit is declared."""

        return self.max_context_tokens is not None


@dataclass(slots=True, frozen=True)
class ModelOption:
    """One provider/model option with declared operational metadata."""

    provider_id: str
    model_name: str | None = None
    capabilities: tuple[ProviderCapability, ...] = ()
    cost: CostMetadata = field(default_factory=CostMetadata)
    latency: LatencyMetadata = field(default_factory=LatencyMetadata)
    context_size: ContextSizeMetadata = field(default_factory=ContextSizeMetadata)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id", maximum=128)
        if self.model_name is not None:
            _text(self.model_name, "model_name", maximum=256)
        object.__setattr__(
            self,
            "capabilities",
            _capabilities(self.capabilities, "capabilities"),
        )
        if not isinstance(self.cost, CostMetadata):
            raise TypeError("cost must be CostMetadata")
        if not isinstance(self.latency, LatencyMetadata):
            raise TypeError("latency must be LatencyMetadata")
        if not isinstance(self.context_size, ContextSizeMetadata):
            raise TypeError("context_size must be ContextSizeMetadata")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))

    @property
    def option_id(self) -> str:
        """Return a deterministic provider/model option identifier."""

        return f"{self.provider_id}:{self.model_name or 'unspecified'}"


@dataclass(slots=True, frozen=True)
class ModelPreferencePolicy:
    """Immutable model, cost, latency, and context preference constraints."""

    preferred_models: tuple[str, ...] = ()
    excluded_models: tuple[str, ...] = ()
    required_model: str | None = None
    maximum_estimated_cost: float | None = None
    maximum_latency_ms: float | None = None
    minimum_context_tokens: int | None = None
    prefer_lower_cost: bool = False
    prefer_lower_latency: bool = False
    prefer_larger_context: bool = False
    allow_unspecified_model: bool = True
    allow_unknown_cost: bool = True
    allow_unknown_latency: bool = True
    allow_unknown_context: bool = True
    honor_request_model_hint: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        preferred = _identifiers(self.preferred_models, "preferred_models")
        excluded = _identifiers(self.excluded_models, "excluded_models")
        if set(preferred).intersection(excluded):
            raise ValueError("preferred and excluded models cannot overlap")
        if self.required_model is not None:
            _text(self.required_model, "required_model", maximum=256)
            if self.required_model in excluded:
                raise ValueError("required_model cannot be excluded")
        object.__setattr__(self, "preferred_models", preferred)
        object.__setattr__(self, "excluded_models", excluded)
        object.__setattr__(
            self,
            "maximum_estimated_cost",
            _optional_number(self.maximum_estimated_cost, "maximum_estimated_cost"),
        )
        object.__setattr__(
            self,
            "maximum_latency_ms",
            _optional_number(self.maximum_latency_ms, "maximum_latency_ms"),
        )
        object.__setattr__(
            self,
            "minimum_context_tokens",
            _optional_count(self.minimum_context_tokens, "minimum_context_tokens"),
        )
        for name in (
            "prefer_lower_cost",
            "prefer_lower_latency",
            "prefer_larger_context",
            "allow_unspecified_model",
            "allow_unknown_cost",
            "allow_unknown_latency",
            "allow_unknown_context",
            "honor_request_model_hint",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))


@dataclass(slots=True, frozen=True)
class PreferenceResolution:
    """Immutable result of deterministic model preference resolution."""

    request_id: str
    selected_option: ModelOption
    considered_options: tuple[ModelOption, ...]
    policy: ModelPreferencePolicy
    rejected_reasons: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    factors: tuple[str, ...] = ()
    resolved_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id", maximum=128)
        if not isinstance(self.selected_option, ModelOption):
            raise TypeError("selected_option must be a ModelOption")
        considered = tuple(self.considered_options)
        if not considered or any(
            not isinstance(item, ModelOption) for item in considered
        ):
            raise ValueError("considered_options must contain ModelOption values")
        option_ids = tuple(item.option_id for item in considered)
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("considered_options cannot contain duplicates")
        if self.selected_option not in considered:
            raise ValueError("selected_option must be present in considered_options")
        if not isinstance(self.policy, ModelPreferencePolicy):
            raise TypeError("policy must be a ModelPreferencePolicy")
        rejected: dict[str, tuple[str, ...]] = {}
        for option_id, reasons in self.rejected_reasons.items():
            _text(option_id, "rejected option identifier", maximum=512)
            rejected[option_id] = _factors(reasons, "rejected reasons")
        if any(option_id not in option_ids for option_id in rejected):
            raise ValueError("rejected options must be present in considered_options")
        if self.selected_option.option_id in rejected:
            raise ValueError("selected_option cannot also be rejected")
        factors = _factors(self.factors)
        if not factors:
            raise ValueError("preference resolution requires explanatory factors")
        object.__setattr__(self, "considered_options", considered)
        object.__setattr__(self, "rejected_reasons", immutable_mapping(rejected))
        object.__setattr__(self, "factors", factors)
        _time(self.resolved_at, "resolved_at")

    @property
    def provider_id(self) -> str:
        return self.selected_option.provider_id

    @property
    def model_name(self) -> str | None:
        return self.selected_option.model_name


@dataclass(slots=True, frozen=True)
class CapabilityNegotiation:
    """Capability agreement between one immutable request and provider."""

    request_id: str
    provider_id: str
    required: tuple[ProviderCapability, ...]
    matched: tuple[ProviderCapability, ...]
    missing: tuple[ProviderCapability, ...]
    successful: bool
    negotiated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id", maximum=128)
        _text(self.provider_id, "provider_id", maximum=128)
        required = _capabilities(self.required, "required")
        matched = _capabilities(self.matched, "matched")
        missing = _capabilities(self.missing, "missing")
        if set(matched).union(missing) != set(required) or set(matched).intersection(
            missing
        ):
            raise ValueError("matched and missing capabilities must partition required")
        if not isinstance(self.successful, bool) or self.successful is not (
            not missing
        ):
            raise ValueError("successful must agree with missing capabilities")
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "matched", matched)
        object.__setattr__(self, "missing", missing)
        _time(self.negotiated_at, "negotiated_at")


@dataclass(slots=True, frozen=True)
class ProviderNegotiation:
    """Provider, model, and capability negotiation with no execution behavior."""

    request: AIRequest
    provider: AIProvider
    routing_decision: RoutingDecision
    preference_resolution: PreferenceResolution
    capability_negotiation: CapabilityNegotiation
    negotiation_id: str = field(default_factory=new_id)
    negotiated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(self.provider, AIProvider):
            raise TypeError("provider must be an AIProvider")
        if not isinstance(self.routing_decision, RoutingDecision):
            raise TypeError("routing_decision must be a RoutingDecision")
        if not isinstance(self.preference_resolution, PreferenceResolution):
            raise TypeError("preference_resolution must be a PreferenceResolution")
        if not isinstance(self.capability_negotiation, CapabilityNegotiation):
            raise TypeError("capability_negotiation must be a CapabilityNegotiation")
        if self.routing_decision.request_id != self.request.request_id:
            raise ValueError("routing decision must belong to the request")
        if self.preference_resolution.request_id != self.request.request_id:
            raise ValueError("preference resolution must belong to the request")
        if self.capability_negotiation.request_id != self.request.request_id:
            raise ValueError("capability negotiation must belong to the request")
        if (
            self.provider.provider_id != self.preference_resolution.provider_id
            or self.provider.provider_id != self.capability_negotiation.provider_id
        ):
            raise ValueError("negotiation artifacts must select the same provider")
        try:
            routed_score = next(
                item
                for item in self.routing_decision.provider_scores
                if item.provider_id == self.provider.provider_id
            )
        except StopIteration as error:
            raise ValueError(
                "negotiated provider must be present in routing scores"
            ) from error
        if not routed_score.compatible:
            raise ValueError("negotiated provider must be routing-compatible")
        if not self.capability_negotiation.successful:
            raise ValueError("provider negotiation requires successful capabilities")
        _text(self.negotiation_id, "negotiation_id", maximum=128)
        _time(self.negotiated_at, "negotiated_at")

    @property
    def request_id(self) -> str:
        return self.request.request_id

    @property
    def provider_id(self) -> str:
        return self.provider.provider_id

    @property
    def model_name(self) -> str | None:
        return self.preference_resolution.model_name

    @property
    def cost(self) -> CostMetadata:
        return self.preference_resolution.selected_option.cost

    @property
    def latency(self) -> LatencyMetadata:
        return self.preference_resolution.selected_option.latency

    @property
    def context_size(self) -> ContextSizeMetadata:
        return self.preference_resolution.selected_option.context_size


@dataclass(slots=True, frozen=True)
class OrchestrationPlanStep:
    """One ordered coordination step that cannot represent execution."""

    order: int
    step_type: OrchestrationStepType
    description: str
    planned: bool = True
    executed: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.order, bool)
            or not isinstance(self.order, int)
            or self.order < 1
        ):
            raise ValueError("order must be a positive integer")
        if not isinstance(self.step_type, OrchestrationStepType):
            raise TypeError("step_type must be an OrchestrationStepType")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("description must be non-empty text")
        if self.planned is not True or self.executed is not False:
            raise ValueError("orchestration steps must remain planned and unexecuted")


@dataclass(slots=True, frozen=True)
class OrchestrationPlan:
    """Immutable architecture-only plan for one negotiated request."""

    session_id: str
    request: AIRequest
    negotiation: ProviderNegotiation
    steps: tuple[OrchestrationPlanStep, ...]
    routing_policy: RoutingPolicy
    preference_policy: ModelPreferencePolicy
    metadata: Mapping[str, Any] = field(default_factory=dict)
    plan_id: str = field(default_factory=new_id)
    status: OrchestrationPlanStatus = OrchestrationPlanStatus.READY
    created_at: datetime = field(default_factory=utc_now)
    architecture_only: bool = True
    executable: bool = False
    executed: bool = False

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id", maximum=128)
        _text(self.plan_id, "plan_id", maximum=128)
        if not isinstance(self.request, AIRequest):
            raise TypeError("request must be an AIRequest")
        if not isinstance(self.negotiation, ProviderNegotiation):
            raise TypeError("negotiation must be a ProviderNegotiation")
        if self.negotiation.request_id != self.request.request_id:
            raise ValueError("negotiation must belong to the plan request")
        steps = tuple(self.steps)
        if not steps or any(
            not isinstance(item, OrchestrationPlanStep) for item in steps
        ):
            raise ValueError("steps must contain OrchestrationPlanStep values")
        if tuple(item.order for item in steps) != tuple(range(1, len(steps) + 1)):
            raise ValueError("plan steps must be contiguous and start at 1")
        if not isinstance(self.routing_policy, RoutingPolicy):
            raise TypeError("routing_policy must be a RoutingPolicy")
        if not isinstance(self.preference_policy, ModelPreferencePolicy):
            raise TypeError("preference_policy must be a ModelPreferencePolicy")
        if not isinstance(self.status, OrchestrationPlanStatus):
            raise TypeError("status must be an OrchestrationPlanStatus")
        if (
            self.architecture_only is not True
            or self.executable is not False
            or self.executed is not False
        ):
            raise ValueError(
                "orchestration plans must remain architecture-only and unexecuted"
            )
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        _time(self.created_at, "created_at")

    @property
    def request_id(self) -> str:
        return self.request.request_id

    @property
    def provider_id(self) -> str:
        return self.negotiation.provider_id

    @property
    def model_name(self) -> str | None:
        return self.negotiation.model_name


@dataclass(slots=True, frozen=True)
class ProviderSelectionRecord:
    """Immutable provider selection history retained by a session."""

    session_id: str
    plan_id: str
    request_id: str
    provider_id: str
    model_name: str | None
    routing_decision_id: str
    score: float
    cost: CostMetadata
    latency: LatencyMetadata
    context_size: ContextSizeMetadata
    selected_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in (
            "session_id",
            "plan_id",
            "request_id",
            "provider_id",
            "routing_decision_id",
        ):
            _text(getattr(self, name), name, maximum=128)
        if self.model_name is not None:
            _text(self.model_name, "model_name", maximum=256)
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)):
            raise TypeError("score must be numeric")
        score = float(self.score)
        if score != score or score < 0 or score > 100:
            raise ValueError("score must be between 0 and 100")
        object.__setattr__(self, "score", score)
        if not isinstance(self.cost, CostMetadata):
            raise TypeError("cost must be CostMetadata")
        if not isinstance(self.latency, LatencyMetadata):
            raise TypeError("latency must be LatencyMetadata")
        if not isinstance(self.context_size, ContextSizeMetadata):
            raise TypeError("context_size must be ContextSizeMetadata")
        _time(self.selected_at, "selected_at")


@dataclass(slots=True, frozen=True)
class OrchestrationSession:
    """Immutable multi-request orchestration session snapshot."""

    session_id: str
    owner_id: str
    created_at: datetime
    expires_at: datetime
    updated_at: datetime
    status: OrchestrationSessionStatus = OrchestrationSessionStatus.ACTIVE
    metadata: Mapping[str, Any] = field(default_factory=dict)
    request_ids: tuple[str, ...] = ()
    plan_ids: tuple[str, ...] = ()
    provider_selection_history: tuple[ProviderSelectionRecord, ...] = ()
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id", maximum=128)
        _text(self.owner_id, "owner_id", maximum=128)
        _time(self.created_at, "created_at")
        _time(self.expires_at, "expires_at")
        _time(self.updated_at, "updated_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if not isinstance(self.status, OrchestrationSessionStatus):
            raise TypeError("status must be an OrchestrationSessionStatus")
        requests = _identifiers(self.request_ids, "request_ids")
        plans = _identifiers(self.plan_ids, "plan_ids")
        history = tuple(self.provider_selection_history)
        if any(not isinstance(item, ProviderSelectionRecord) for item in history):
            raise TypeError(
                "provider_selection_history must contain ProviderSelectionRecord values"
            )
        if not (len(requests) == len(plans) == len(history)):
            raise ValueError("request, plan, and selection history counts must match")
        if any(item.session_id != self.session_id for item in history):
            raise ValueError("selection history must belong to the session")
        if tuple(item.request_id for item in history) != requests:
            raise ValueError("selection history must match request_ids")
        if tuple(item.plan_id for item in history) != plans:
            raise ValueError("selection history must match plan_ids")
        if self.completed_at is not None:
            _time(self.completed_at, "completed_at")
            if self.completed_at < self.created_at:
                raise ValueError("completed_at cannot precede created_at")
        terminal = self.status in {
            OrchestrationSessionStatus.COMPLETED,
            OrchestrationSessionStatus.EXPIRED,
            OrchestrationSessionStatus.CANCELLED,
        }
        if terminal is not (self.completed_at is not None):
            raise ValueError("terminal session states require completed_at")
        object.__setattr__(self, "metadata", immutable_mapping(self.metadata))
        object.__setattr__(self, "request_ids", requests)
        object.__setattr__(self, "plan_ids", plans)
        object.__setattr__(self, "provider_selection_history", history)

    @property
    def active(self) -> bool:
        return self.status is OrchestrationSessionStatus.ACTIVE

    @property
    def selection_history(self) -> tuple[ProviderSelectionRecord, ...]:
        return self.provider_selection_history


@dataclass(slots=True, frozen=True)
class OrchestrationSummary:
    """Structured aggregate facts for one orchestration session."""

    session_id: str
    status: OrchestrationSessionStatus
    request_count: int
    plan_count: int
    selection_count: int
    provider_selection_counts: Mapping[str, int]
    total_estimated_cost: float | None
    cost_currency: str | None
    average_estimated_latency_ms: float | None
    maximum_context_tokens: int | None
    last_provider_id: str | None
    last_model_name: str | None
    generated_at: datetime = field(default_factory=utc_now)
    architecture_only: bool = True

    def __post_init__(self) -> None:
        _text(self.session_id, "session_id", maximum=128)
        if not isinstance(self.status, OrchestrationSessionStatus):
            raise TypeError("status must be an OrchestrationSessionStatus")
        for name in ("request_count", "plan_count", "selection_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not (self.request_count == self.plan_count == self.selection_count):
            raise ValueError("summary request, plan, and selection counts must match")
        counts = dict(self.provider_selection_counts)
        if any(not isinstance(key, str) or not key for key in counts):
            raise ValueError("provider selection count keys must be non-empty strings")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in counts.values()
        ):
            raise ValueError("provider selection counts must be positive integers")
        if sum(counts.values()) != self.selection_count:
            raise ValueError("provider selection counts must total selection_count")
        object.__setattr__(self, "provider_selection_counts", immutable_mapping(counts))
        object.__setattr__(
            self,
            "total_estimated_cost",
            _optional_number(self.total_estimated_cost, "total_estimated_cost"),
        )
        if self.cost_currency is not None:
            currency = _text(self.cost_currency, "cost_currency", maximum=8)
            if not currency.isalpha() or currency.upper() != currency:
                raise ValueError("cost_currency must be an uppercase alphabetic code")
        if (self.total_estimated_cost is None) is not (self.cost_currency is None):
            raise ValueError(
                "total_estimated_cost and cost_currency must be reported together"
            )
        object.__setattr__(
            self,
            "average_estimated_latency_ms",
            _optional_number(
                self.average_estimated_latency_ms,
                "average_estimated_latency_ms",
            ),
        )
        object.__setattr__(
            self,
            "maximum_context_tokens",
            _optional_count(self.maximum_context_tokens, "maximum_context_tokens"),
        )
        if self.last_provider_id is not None:
            _text(self.last_provider_id, "last_provider_id", maximum=128)
        if self.last_model_name is not None:
            _text(self.last_model_name, "last_model_name", maximum=256)
        if self.selection_count == 0 and (
            self.last_provider_id is not None or self.last_model_name is not None
        ):
            raise ValueError("empty summaries cannot report a last selection")
        if self.selection_count > 0 and self.last_provider_id is None:
            raise ValueError("non-empty summaries require last_provider_id")
        _time(self.generated_at, "generated_at")
        if self.architecture_only is not True:
            raise ValueError("orchestration summaries must remain architecture-only")


__all__ = [
    "CapabilityNegotiation",
    "ContextSizeMetadata",
    "CostMetadata",
    "LatencyMetadata",
    "ModelOption",
    "ModelPreferencePolicy",
    "OrchestrationPlan",
    "OrchestrationPlanStatus",
    "OrchestrationPlanStep",
    "OrchestrationSession",
    "OrchestrationSessionStatus",
    "OrchestrationStepType",
    "OrchestrationSummary",
    "PreferenceResolution",
    "ProviderNegotiation",
    "ProviderSelectionRecord",
]
