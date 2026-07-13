"""Typed models shared by the trusted execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
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


def _new_request_id() -> str:
    """Return an opaque identifier for a newly constructed request."""

    return uuid4().hex


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

    @property
    def authorized(self) -> bool:
        """Return whether validation and permission checks passed."""

        return self.status is ExecutionStatus.AUTHORIZED

    @property
    def successful(self) -> bool:
        """Return whether a future dispatcher reported successful execution."""

        return self.status is ExecutionStatus.SUCCEEDED and self.executed


__all__ = [
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
    "TrustPolicyContext",
]
