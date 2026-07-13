"""Typed models shared by the trusted execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class ExecutionStatus(str, Enum):
    """Lifecycle states available to execution gateway results.

    Sprint 2 emits :attr:`PENDING`, :attr:`AUTHORIZED`, :attr:`DENIED`, and
    :attr:`REJECTED`.  The remaining states define the result contract that a
    future dispatcher may use without changing callers of the gateway.
    """

    PENDING = "pending"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    REJECTED = "rejected"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PermissionLevel(str, Enum):
    """Ordered permission levels recognized by the execution boundary."""

    NONE = "none"
    READ_ONLY = "read_only"
    STANDARD = "standard"
    ELEVATED = "elevated"
    ADMINISTRATOR = "administrator"


class RiskLevel(str, Enum):
    """Ordered risk classifications for proposed execution requests."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecisionType(str, Enum):
    """Outcomes that a trust policy may return."""

    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class ApprovalDecisionType(str, Enum):
    """Outcomes produced by the approval decision service."""

    GRANTED = "granted"
    DENIED = "denied"
    REQUIRED = "required"


class VerificationStatus(str, Enum):
    """Outcomes produced by execution result verification."""

    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"


class RollbackStatus(str, Enum):
    """Lifecycle states for an inert rollback plan or result."""

    PLANNED = "planned"
    SIMULATED = "simulated"
    FAILED = "failed"


class AuditStage(str, Enum):
    """Execution lifecycle stages retained by the audit boundary."""

    REQUEST_RECEIVED = "request_received"
    VALIDATED = "validated"
    PERMISSION_EVALUATED = "permission_evaluated"
    RISK_EVALUATED = "risk_evaluated"
    POLICY_EVALUATED = "policy_evaluated"
    APPROVAL_EVALUATED = "approval_evaluated"
    STARTED = "started"
    DISPATCHED = "dispatched"
    VERIFIED = "verified"
    ROLLBACK = "rollback"
    COMPLETED = "completed"
    FAILED = "failed"


def _new_request_id() -> str:
    """Return an opaque identifier for a newly constructed request."""

    return uuid4().hex


def _new_record_id() -> str:
    """Return an opaque identifier for a lifecycle record."""

    return uuid4().hex


def _utc_now() -> datetime:
    """Return an aware UTC timestamp for lifecycle records."""

    return datetime.now(timezone.utc)


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Copy a string-keyed mapping behind a read-only facade."""

    if not isinstance(value, Mapping):
        raise TypeError("lifecycle details must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError("lifecycle detail keys must be strings")
    return MappingProxyType(dict(value))


@dataclass(slots=True, frozen=True)
class ExecutionRequest:
    """Describe one proposed action before any execution is attempted.

    Attributes:
        action: Stable action identifier understood by a future dispatcher.
        permission_level: Minimum permission declared for the action.
        parameters: Action-specific input retained as inert data in Sprint 2.
        metadata: Non-executable correlation and observability information.
        request_id: Opaque identifier used to correlate logs, events, and the
            resulting decision.
    """

    action: str
    permission_level: PermissionLevel = PermissionLevel.STANDARD
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=_new_request_id)


@dataclass(slots=True, frozen=True)
class RiskFactor:
    """Describe one rule contribution to an execution risk assessment.

    Attributes:
        source: Stable name of the rule or scorer that produced the factor.
        risk_level: Minimum risk indicated by this factor.
        reason_code: Machine-readable explanation of the finding.
        description: Human-readable explanation suitable for audit output.
    """

    source: str
    risk_level: RiskLevel
    reason_code: str
    description: str


@dataclass(slots=True, frozen=True)
class RiskAssessment:
    """Represent the complete risk classification for one request."""

    request_id: str
    risk_level: RiskLevel
    factors: tuple[RiskFactor, ...] = ()

    @property
    def level(self) -> RiskLevel:
        """Return the assessment level using a concise compatibility alias."""

        return self.risk_level

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Return all contributing reason codes in evaluation order."""

        return tuple(factor.reason_code for factor in self.factors)


@dataclass(slots=True, frozen=True)
class TrustPolicyContext:
    """Provide inert, typed facts to an independent trust policy."""

    request: ExecutionRequest
    risk_assessment: RiskAssessment
    permission_granted: bool
    required_permission_level: PermissionLevel


@dataclass(slots=True, frozen=True)
class PolicyDecision:
    """Represent the structured outcome returned by a trust policy."""

    decision: PolicyDecisionType
    policy_name: str
    reason_code: str
    message: str

    @property
    def allowed(self) -> bool:
        """Return whether the policy allows authorization to continue."""

        return self.decision is PolicyDecisionType.ALLOW

    @property
    def denied(self) -> bool:
        """Return whether the policy explicitly denies the request."""

        return self.decision is PolicyDecisionType.DENY

    @property
    def approval_required(self) -> bool:
        """Return whether the policy requires an external user decision."""

        return self.decision is PolicyDecisionType.APPROVAL_REQUIRED


@dataclass(slots=True, frozen=True)
class ApprovalDecision:
    """Represent the approval manager's complete, non-UI decision.

    The model retains the permission, risk, and policy facts needed by future
    dashboard, voice, or mobile approval providers without coupling the Core
    decision service to any of those interfaces.
    """

    request_id: str
    decision: ApprovalDecisionType
    permission_granted: bool
    required_permission_level: PermissionLevel
    reason_code: str
    message: str
    risk_assessment: RiskAssessment | None = None
    policy_decision: PolicyDecision | None = None
    failure_stage: str = ""

    @property
    def granted(self) -> bool:
        """Return whether trust policy granted authorization."""

        return self.decision is ApprovalDecisionType.GRANTED

    @property
    def approved(self) -> bool:
        """Return a compatibility alias for :attr:`granted`."""

        return self.granted

    @property
    def denied(self) -> bool:
        """Return whether authorization was denied."""

        return self.decision is ApprovalDecisionType.DENIED

    @property
    def approval_required(self) -> bool:
        """Return whether a future approval provider must ask the user."""

        return self.decision is ApprovalDecisionType.REQUIRED

    @property
    def requires_approval(self) -> bool:
        """Return a compatibility alias for :attr:`approval_required`."""

        return self.approval_required


@dataclass(slots=True, frozen=True)
class VerificationReport:
    """Describe deterministic verification of one dispatched result."""

    request_id: str
    action: str
    status: VerificationStatus
    completion_verified: bool
    outcome_verified: bool
    reason_code: str
    message: str
    expected_outcome: Mapping[str, Any] = field(default_factory=dict)
    actual_outcome: Mapping[str, Any] = field(default_factory=dict)
    verified_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        """Detach report mappings and require an aware verification time."""

        object.__setattr__(
            self,
            "expected_outcome",
            _immutable_mapping(self.expected_outcome),
        )
        object.__setattr__(
            self,
            "actual_outcome",
            _immutable_mapping(self.actual_outcome),
        )
        if self.verified_at.tzinfo is None:
            raise ValueError("verified_at must be timezone-aware")

    @property
    def passed(self) -> bool:
        """Return whether completion and expected outcome were verified."""

        return self.status is VerificationStatus.PASSED

    @property
    def successful(self) -> bool:
        """Return a compatibility alias for :attr:`passed`."""

        return self.passed

    @property
    def requires_rollback(self) -> bool:
        """Return whether the verification failure should trigger rollback."""

        return self.status is VerificationStatus.FAILED


@dataclass(slots=True, frozen=True)
class RollbackAction:
    """Describe one inert action in a rollback plan.

    The action contains data only.  RollbackManager never evaluates a callable
    or invokes the named provider during Sprint 3.
    """

    action_id: str
    description: str
    provider: str = "simulation"
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate identifiers and detach action parameters."""

        if not self.action_id.strip() or self.action_id != self.action_id.strip():
            raise ValueError("action_id must be a normalized non-empty string")
        if not self.description.strip():
            raise ValueError("description must be a non-empty string")
        if not self.provider.strip() or self.provider != self.provider.strip():
            raise ValueError("provider must be a normalized non-empty string")
        object.__setattr__(
            self,
            "parameters",
            _immutable_mapping(self.parameters),
        )


@dataclass(slots=True, frozen=True)
class RollbackPlan:
    """Represent an immutable, simulation-only rollback plan."""

    request_id: str
    action: str
    actions: tuple[RollbackAction, ...] = ()
    plan_id: str = field(default_factory=_new_record_id)
    status: RollbackStatus = RollbackStatus.PLANNED
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        """Normalize the action sequence and validate the plan timestamp."""

        object.__setattr__(self, "actions", tuple(self.actions))
        if any(not isinstance(action, RollbackAction) for action in self.actions):
            raise TypeError("rollback plans require RollbackAction instances")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(slots=True, frozen=True)
class RollbackResult:
    """Describe the outcome of a simulated rollback plan."""

    request_id: str
    plan_id: str
    status: RollbackStatus
    successful: bool
    simulated: bool
    message: str
    actions_executed: tuple[str, ...] = ()
    completed_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        """Normalize retained action identifiers and timestamp."""

        object.__setattr__(self, "actions_executed", tuple(self.actions_executed))
        if self.completed_at.tzinfo is None:
            raise ValueError("completed_at must be timezone-aware")

    @property
    def succeeded(self) -> bool:
        """Return a concise compatibility alias for :attr:`successful`."""

        return self.successful


@dataclass(slots=True, frozen=True)
class AuditEntry:
    """Represent one immutable, timestamped execution audit entry."""

    request_id: str
    action: str
    stage: AuditStage
    outcome: str
    details: Mapping[str, Any] = field(default_factory=dict)
    entry_id: str = field(default_factory=_new_record_id)
    timestamp: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        """Detach entry details and require typed, aware record fields."""

        if not isinstance(self.stage, AuditStage):
            raise TypeError("audit stage must be an AuditStage")
        if self.timestamp.tzinfo is None:
            raise ValueError("audit timestamps must be timezone-aware")
        object.__setattr__(self, "details", _immutable_mapping(self.details))


@dataclass(slots=True, frozen=True)
class ExecutionResult:
    """Represent the gateway outcome for one execution request.

    ``executed`` and ``dispatcher_invoked`` are explicit safety facts.  They
    remain ``False`` for every result produced by the Sprint 2 gateway.

    Attributes:
        request_id: Identifier copied from the evaluated request when valid.
        action: Action identifier copied from the evaluated request when valid.
        status: Typed gateway outcome.
        message: Human-readable explanation of the outcome.
        permission_level: Effective permission level required by the policy.
        reason_code: Stable machine-readable reason for the outcome.
        output: Reserved result data for a future dispatcher integration.
        executed: Whether a real action was completed.
        dispatcher_invoked: Whether an execution dispatcher was called.
        risk_level: Risk assigned before the final authorization decision.
        approval_decision: Structured approval outcome assigned by Sprint 2.
        policy_decision: Trust policy outcome that informed approval.
    """

    request_id: str
    action: str
    status: ExecutionStatus
    message: str
    permission_level: PermissionLevel | None = None
    reason_code: str = ""
    output: Mapping[str, Any] = field(default_factory=dict)
    executed: bool = False
    dispatcher_invoked: bool = False
    risk_level: RiskLevel | None = None
    approval_decision: ApprovalDecisionType | None = None
    policy_decision: PolicyDecisionType | None = None
    verification_report: VerificationReport | None = None
    rollback_result: RollbackResult | None = None
    audit_entry_ids: tuple[str, ...] = ()

    @property
    def authorized(self) -> bool:
        """Return whether validation and permission checks passed."""

        return self.status is ExecutionStatus.AUTHORIZED

    @property
    def successful(self) -> bool:
        """Return whether a future dispatcher reported successful execution."""

        return self.status is ExecutionStatus.SUCCEEDED and self.executed

    @property
    def verified(self) -> bool:
        """Return whether the attached verification report passed."""

        return (
            self.verification_report is not None
            and self.verification_report.passed
        )


__all__ = [
    "AuditEntry",
    "AuditStage",
    "ApprovalDecision",
    "ApprovalDecisionType",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "PermissionLevel",
    "PolicyDecision",
    "PolicyDecisionType",
    "RiskAssessment",
    "RiskFactor",
    "RiskLevel",
    "RollbackAction",
    "RollbackPlan",
    "RollbackResult",
    "RollbackStatus",
    "TrustPolicyContext",
    "VerificationReport",
    "VerificationStatus",
]
