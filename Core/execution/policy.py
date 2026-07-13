"""Reusable trust policies independent from gateway execution logic."""

from __future__ import annotations

from typing import Protocol

from .models import (
    PolicyDecision,
    PolicyDecisionType,
    TrustPolicyContext,
)


class TrustPolicy(Protocol):
    """Contract implemented by built-in and future custom trust policies."""

    @property
    def name(self) -> str:
        """Return a stable policy name for logs and audit records."""

    def evaluate(self, context: TrustPolicyContext) -> PolicyDecision:
        """Evaluate typed trust facts without performing any action."""


class _StaticTrustPolicy:
    """Base implementation for policies returning one configured outcome."""

    decision_type: PolicyDecisionType
    default_name: str
    default_reason_code: str
    default_message: str

    def __init__(
        self,
        *,
        name: str | None = None,
        reason_code: str | None = None,
        message: str | None = None,
    ) -> None:
        self._name = name or self.default_name
        self._reason_code = reason_code or self.default_reason_code
        self._message = message or self.default_message
        if not self._name.strip() or not self._reason_code.strip():
            raise ValueError("policy name and reason_code must be non-empty")

    @property
    def name(self) -> str:
        """Return the configured policy name."""

        return self._name

    def evaluate(self, context: TrustPolicyContext) -> PolicyDecision:
        """Return the configured decision for a typed policy context."""

        if not isinstance(context, TrustPolicyContext):
            raise TypeError("trust policies require a TrustPolicyContext")
        return PolicyDecision(
            decision=self.decision_type,
            policy_name=self._name,
            reason_code=self._reason_code,
            message=self._message,
        )


class AllowPolicy(_StaticTrustPolicy):
    """Grant authorization when selected by the approval manager."""

    decision_type = PolicyDecisionType.ALLOW
    default_name = "allow"
    default_reason_code = "policy_allowed"
    default_message = "Trust policy allows the request."


class DenyPolicy(_StaticTrustPolicy):
    """Deny authorization when selected by the approval manager."""

    decision_type = PolicyDecisionType.DENY
    default_name = "deny"
    default_reason_code = "policy_denied"
    default_message = "Trust policy denies the request."


class ApprovalRequiredPolicy(_StaticTrustPolicy):
    """Pause authorization until a future provider obtains user approval."""

    decision_type = PolicyDecisionType.APPROVAL_REQUIRED
    default_name = "approval_required"
    default_reason_code = "approval_required"
    default_message = "User approval is required before authorization."


__all__ = [
    "AllowPolicy",
    "ApprovalRequiredPolicy",
    "DenyPolicy",
    "PolicyDecision",
    "PolicyDecisionType",
    "TrustPolicy",
    "TrustPolicyContext",
]
