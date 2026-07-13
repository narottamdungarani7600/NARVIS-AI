"""Extensible risk analysis for proposed trusted execution requests.

The default analyzer is deliberately deterministic and side-effect free.  Its
rules can be replaced with future statistical or AI-based scorers without
changing approval or gateway code.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger

from .exceptions import ExecutionValidationError
from .models import (
    ExecutionRequest,
    PermissionLevel,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
)

_RISK_RANK: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}

_ACTION_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")


class RiskRule(Protocol):
    """Contract for one replaceable execution risk rule."""

    def evaluate(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel,
    ) -> Iterable[RiskFactor]:
        """Return zero or more risk factors for ``request``."""


class RiskEvaluator(Protocol):
    """Risk-analysis contract consumed by :class:`ApprovalManager`."""

    def analyze(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel | None = None,
    ) -> RiskAssessment:
        """Return a typed risk assessment for ``request``."""


class PermissionRiskRule:
    """Classify the effective permission level required by a request."""

    _LEVELS: dict[PermissionLevel, RiskLevel] = {
        PermissionLevel.NONE: RiskLevel.LOW,
        PermissionLevel.READ_ONLY: RiskLevel.LOW,
        PermissionLevel.STANDARD: RiskLevel.LOW,
        PermissionLevel.ELEVATED: RiskLevel.HIGH,
        PermissionLevel.ADMINISTRATOR: RiskLevel.CRITICAL,
    }

    def evaluate(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel,
    ) -> Iterable[RiskFactor]:
        """Return the risk floor associated with effective permission."""

        risk_level = self._LEVELS[permission_level]
        return (
            RiskFactor(
                source=type(self).__name__,
                risk_level=risk_level,
                reason_code=f"permission_{permission_level.value}",
                description=(
                    "Effective permission level is "
                    f"{permission_level.value.replace('_', ' ')}."
                ),
            ),
        )


class ActionRiskRule:
    """Classify action identifiers using conservative, replaceable rules."""

    _CRITICAL_TOKENS = frozenset(
        {
            "credential",
            "credentials",
            "factoryreset",
            "format",
            "privilegeescalation",
            "rootkit",
            "wipe",
        }
    )
    _HIGH_TOKENS = frozenset(
        {
            "configure",
            "delete",
            "disable",
            "execute",
            "install",
            "kill",
            "modify",
            "remove",
            "restart",
            "shell",
            "shutdown",
            "terminate",
            "uninstall",
            "write",
        }
    )
    _MEDIUM_TOKENS = frozenset(
        {
            "copy",
            "create",
            "download",
            "move",
            "network",
            "rename",
            "send",
            "share",
            "upload",
        }
    )

    def evaluate(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel,
    ) -> Iterable[RiskFactor]:
        """Return a factor for the most sensitive action token found."""

        del permission_level
        normalized_action = request.action.casefold()
        action_parts = tuple(
            token for token in _ACTION_TOKEN_PATTERN.split(normalized_action) if token
        )
        tokens = frozenset(action_parts)
        compact_action = "".join(action_parts)

        risk_level = RiskLevel.LOW
        reason_code = "action_read_or_observe"
        if tokens & self._CRITICAL_TOKENS or compact_action in self._CRITICAL_TOKENS:
            risk_level = RiskLevel.CRITICAL
            reason_code = "action_critical_impact"
        elif tokens & self._HIGH_TOKENS:
            risk_level = RiskLevel.HIGH
            reason_code = "action_mutates_or_controls_system"
        elif tokens & self._MEDIUM_TOKENS:
            risk_level = RiskLevel.MEDIUM
            reason_code = "action_has_external_side_effect"

        return (
            RiskFactor(
                source=type(self).__name__,
                risk_level=risk_level,
                reason_code=reason_code,
                description=f"Action {request.action!r} was classified by action rules.",
            ),
        )


class MetadataRiskRule:
    """Elevate risk from explicit, non-secret request metadata indicators."""

    _BOOLEAN_INDICATORS: tuple[tuple[str, RiskLevel], ...] = (
        ("external_side_effect", RiskLevel.MEDIUM),
        ("external_side_effects", RiskLevel.MEDIUM),
        ("requires_approval", RiskLevel.MEDIUM),
        ("destructive", RiskLevel.HIGH),
        ("sensitive_data", RiskLevel.HIGH),
        ("irreversible", RiskLevel.CRITICAL),
        ("security_critical", RiskLevel.CRITICAL),
    )

    def evaluate(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel,
    ) -> Iterable[RiskFactor]:
        """Return factors for recognized metadata risk declarations."""

        del permission_level
        factors: list[RiskFactor] = []
        declared_level = request.metadata.get("risk_level")
        if isinstance(declared_level, RiskLevel):
            level = declared_level
        elif isinstance(declared_level, str):
            try:
                level = RiskLevel(declared_level.casefold())
            except ValueError:
                level = None
        else:
            level = None

        if level is not None:
            factors.append(
                RiskFactor(
                    source=type(self).__name__,
                    risk_level=level,
                    reason_code="metadata_declared_risk",
                    description="Request metadata declares an explicit risk floor.",
                )
            )

        if request.metadata.get("trusted_source") is False:
            factors.append(
                RiskFactor(
                    source=type(self).__name__,
                    risk_level=RiskLevel.MEDIUM,
                    reason_code="metadata_untrusted_source",
                    description="Request metadata identifies an untrusted source.",
                )
            )

        for key, risk_level in self._BOOLEAN_INDICATORS:
            if request.metadata.get(key) is True:
                factors.append(
                    RiskFactor(
                        source=type(self).__name__,
                        risk_level=risk_level,
                        reason_code=f"metadata_{key}",
                        description=f"Request metadata sets the {key!r} risk indicator.",
                    )
                )
        return tuple(factors)


class RiskAnalyzer:
    """Classify execution requests using an injectable sequence of risk rules."""

    def __init__(
        self,
        rules: Iterable[RiskRule] | None = None,
        *,
        logger: Logger | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            rules: Complete rule sequence to use.  When omitted, deterministic
                permission, action, and metadata rules are installed.
            logger: Core-compatible structured logger.
        """

        self._rules = tuple(
            rules
            if rules is not None
            else (PermissionRiskRule(), ActionRiskRule(), MetadataRiskRule())
        )
        if not self._rules:
            raise ValueError("RiskAnalyzer requires at least one risk rule")
        self._logger = logger or NullLogger("narvis.execution.risk")

    @property
    def rules(self) -> tuple[RiskRule, ...]:
        """Return the immutable configured risk rule sequence."""

        return self._rules

    def analyze(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel | None = None,
    ) -> RiskAssessment:
        """Return the highest risk level contributed by configured rules.

        Args:
            request: Typed request to classify.
            permission_level: Effective level computed by a permission engine.
                The request-declared level is used when this argument is omitted.

        Raises:
            ExecutionValidationError: If request, permission, or rule output is
                malformed.
        """

        if not isinstance(request, ExecutionRequest):
            raise ExecutionValidationError(
                "risk analysis requires a typed ExecutionRequest"
            )
        effective_level = permission_level or request.permission_level
        if not isinstance(effective_level, PermissionLevel):
            raise ExecutionValidationError(
                "risk analysis requires a typed PermissionLevel"
            )

        factors: list[RiskFactor] = []
        for rule in self._rules:
            evaluated_factors = rule.evaluate(request, effective_level)
            for factor in evaluated_factors:
                if not isinstance(factor, RiskFactor):
                    raise ExecutionValidationError(
                        "risk rules must return RiskFactor instances"
                    )
                if not isinstance(factor.risk_level, RiskLevel):
                    raise ExecutionValidationError(
                        "risk factors must contain typed RiskLevel values"
                    )
                factors.append(factor)

        if not factors:
            factors.append(
                RiskFactor(
                    source=type(self).__name__,
                    risk_level=RiskLevel.LOW,
                    reason_code="no_risk_factors",
                    description="No configured rule elevated the request risk.",
                )
            )

        risk_level = max(
            (factor.risk_level for factor in factors),
            key=_RISK_RANK.__getitem__,
        )
        assessment = RiskAssessment(
            request_id=request.request_id,
            risk_level=risk_level,
            factors=tuple(factors),
        )
        self._log(
            LogLevel.INFO,
            "Execution risk evaluated",
            request_id=request.request_id,
            action=request.action,
            risk_level=risk_level.value,
            factor_count=len(factors),
        )
        return assessment

    def classify(
        self,
        request: ExecutionRequest,
        permission_level: PermissionLevel | None = None,
    ) -> RiskAssessment:
        """Return :meth:`analyze` for callers using classification terminology."""

        return self.analyze(request, permission_level)

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit an entry without allowing logging failures to change risk."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = [
    "ActionRiskRule",
    "MetadataRiskRule",
    "PermissionRiskRule",
    "RiskAnalyzer",
    "RiskAssessment",
    "RiskEvaluator",
    "RiskFactor",
    "RiskLevel",
    "RiskRule",
]
