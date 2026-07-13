"""Trusted decision and execution-boundary primitives for NARVIS Core.

The package exposes typed permission, risk, policy, and approval services plus
an inert gateway.  Sprint 2 deliberately performs no host action and invokes
no dispatcher or user interface.
"""

from .approval import ApprovalManager, ApprovalProvider

from .exceptions import (
    DispatcherUnavailableError,
    ExecutionGatewayError,
    ExecutionValidationError,
    PermissionConfigurationError,
    PermissionDeniedError,
)
from .gateway import EventPublisher, ExecutionDispatcher, TrustedExecutionGateway
from .models import (
    ApprovalDecision,
    ApprovalDecisionType,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    PermissionLevel,
    PolicyDecision,
    PolicyDecisionType,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
    TrustPolicyContext,
)
from .permissions import PermissionChecker, PermissionEngine
from .policy import AllowPolicy, ApprovalRequiredPolicy, DenyPolicy, TrustPolicy
from .risk import (
    ActionRiskRule,
    MetadataRiskRule,
    PermissionRiskRule,
    RiskAnalyzer,
    RiskEvaluator,
    RiskRule,
)

__all__ = [
    "ActionRiskRule",
    "AllowPolicy",
    "ApprovalDecision",
    "ApprovalDecisionType",
    "ApprovalManager",
    "ApprovalProvider",
    "ApprovalRequiredPolicy",
    "DenyPolicy",
    "DispatcherUnavailableError",
    "EventPublisher",
    "ExecutionDispatcher",
    "ExecutionGatewayError",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionValidationError",
    "PermissionChecker",
    "PermissionConfigurationError",
    "PermissionDeniedError",
    "PermissionEngine",
    "PermissionLevel",
    "PolicyDecision",
    "PolicyDecisionType",
    "RiskAnalyzer",
    "RiskAssessment",
    "RiskEvaluator",
    "RiskFactor",
    "RiskLevel",
    "RiskRule",
    "MetadataRiskRule",
    "PermissionRiskRule",
    "TrustedExecutionGateway",
    "TrustPolicy",
    "TrustPolicyContext",
]
