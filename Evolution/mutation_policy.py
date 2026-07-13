"""Pure deny-by-default mutation guard validation for future Phase 7 work."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import compact_text, sanitize_durable_mapping
from .mutation_surfaces import MutationSurfaceRegistry, MutationSurfaceRequest

_ALLOWED_RISK_CLASSIFICATIONS = frozenset({"low", "medium", "high"})


def _normalized_key(value: str) -> str:
    """Normalize one guard key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


@dataclass(slots=True, frozen=True)
class MutationGuardRequest:
    """One typed mutation guard validation request."""

    surface_id: str
    locator: str
    target_kind: str
    risk_classification: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class MutationGuardDecision:
    """One typed mutation guard validation decision."""

    decision: str
    surface_id: str
    locator: str
    target_kind: str
    risk_classification: str
    reason_code: str
    reason: str
    normalized_locator: str = ""
    matched_rule_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        """Return True only when the guard explicitly allows the request."""

        return self.decision == "allowed"


class MutationGuardService:
    """Validate mutation requests without executing, orchestrating, or registering them."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        surface_registry: MutationSurfaceRegistry | None = None,
    ) -> None:
        self.surface_registry = surface_registry or MutationSurfaceRegistry(workspace_root=workspace_root)
        self.workspace_root = self.surface_registry.workspace_root.resolve()

    def list_allowed_risk_classifications(self) -> tuple[str, ...]:
        """Return allowed risk classifications in deterministic order."""

        return tuple(sorted(_ALLOWED_RISK_CLASSIFICATIONS))

    def validate(self, request: MutationGuardRequest) -> MutationGuardDecision:
        """Validate one mutation request and return one typed guard decision."""

        normalized_surface_id = _normalized_key(request.surface_id)
        normalized_target_kind = _normalized_key(request.target_kind)
        normalized_risk = _normalized_key(request.risk_classification)
        normalized_locator = self._normalize_locator(request.locator)

        if normalized_risk not in _ALLOWED_RISK_CLASSIFICATIONS:
            return self._deny(
                surface_id=normalized_surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                risk_classification=normalized_risk,
                reason_code="invalid_risk_classification",
                reason="Mutation guard validation only allows low, medium, or high risk classifications.",
                normalized_locator=normalized_locator,
            )

        path_decision = self._validate_workspace_path(
            surface_id=normalized_surface_id,
            locator=request.locator,
            normalized_locator=normalized_locator,
            target_kind=normalized_target_kind,
            risk_classification=normalized_risk,
        )
        if path_decision is not None:
            return path_decision

        surface_decision = self.surface_registry.evaluate(
            MutationSurfaceRequest(
                surface_id=normalized_surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                metadata=request.metadata,
            )
        )
        if not surface_decision.allowed:
            return self._deny(
                surface_id=surface_decision.surface_id,
                locator=surface_decision.locator,
                target_kind=surface_decision.target_kind,
                risk_classification=normalized_risk,
                reason_code=surface_decision.reason_code,
                reason=surface_decision.reason,
                normalized_locator=surface_decision.normalized_locator,
                matched_rule_id=surface_decision.matched_rule_id,
                metadata={
                    "validation_layer": "mutation_surface_registry",
                },
            )

        return self._allow(
            surface_id=surface_decision.surface_id,
            locator=surface_decision.locator,
            target_kind=surface_decision.target_kind,
            risk_classification=normalized_risk,
            reason_code="guard_allowed",
            reason="The mutation request passed workspace, risk, and registered surface validation without executing anything.",
            normalized_locator=surface_decision.normalized_locator,
            metadata={
                "validation_layer": "mutation_guard",
            },
        )

    def _validate_workspace_path(
        self,
        *,
        surface_id: str,
        locator: str,
        normalized_locator: str,
        target_kind: str,
        risk_classification: str,
    ) -> MutationGuardDecision | None:
        """Return one path decision when the locator represents a repository path."""

        if not self._looks_like_workspace_path(locator=locator, target_kind=target_kind):
            return None
        candidate_path = self._resolve_candidate_path(locator)
        if candidate_path is None:
            return self._deny(
                surface_id=surface_id,
                locator=locator,
                target_kind=target_kind,
                risk_classification=risk_classification,
                reason_code="path_outside_workspace",
                reason="Mutation requests must stay inside the repository workspace.",
                normalized_locator=normalized_locator,
            )
        return None

    def _looks_like_workspace_path(self, *, locator: str, target_kind: str) -> bool:
        """Return True when the locator should be validated as a repository path."""

        normalized_target_kind = _normalized_key(target_kind)
        normalized_locator = compact_text(locator, max_chars=320)
        if normalized_target_kind == "source_file":
            return True
        return bool(
            normalized_locator.startswith(".")
            or "/" in normalized_locator
            or "\\" in normalized_locator
            or re.match(r"^[A-Za-z]:[\\/]", normalized_locator)
        )

    def _resolve_candidate_path(self, locator: str) -> str | None:
        """Resolve one path-like locator into a workspace-relative path when possible."""

        normalized_locator = self._normalize_locator(locator)
        try:
            raw_path = Path(normalized_locator)
            if raw_path.is_absolute():
                candidate = raw_path.resolve()
            else:
                candidate = (self.workspace_root / raw_path).resolve()
            relative = candidate.relative_to(self.workspace_root)
        except Exception:
            return None
        return relative.as_posix()

    def _normalize_locator(self, locator: str) -> str:
        """Normalize one locator for durable comparison."""

        value = compact_text(locator, max_chars=320).replace("\\", "/")
        while value.startswith("./"):
            value = value[2:]
        return value

    def _allow(
        self,
        *,
        surface_id: str,
        locator: str,
        target_kind: str,
        risk_classification: str,
        reason_code: str,
        reason: str,
        normalized_locator: str,
        metadata: dict[str, Any] | None = None,
    ) -> MutationGuardDecision:
        """Build one allowed guard decision."""

        return MutationGuardDecision(
            decision="allowed",
            surface_id=compact_text(surface_id, max_chars=120),
            locator=compact_text(locator, max_chars=320),
            target_kind=compact_text(target_kind, max_chars=120),
            risk_classification=compact_text(risk_classification, max_chars=80),
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            normalized_locator=compact_text(normalized_locator, max_chars=320),
            metadata=sanitize_durable_mapping(metadata or {}),
        )

    def _deny(
        self,
        *,
        surface_id: str,
        locator: str,
        target_kind: str,
        risk_classification: str,
        reason_code: str,
        reason: str,
        normalized_locator: str,
        matched_rule_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MutationGuardDecision:
        """Build one denied guard decision."""

        return MutationGuardDecision(
            decision="denied",
            surface_id=compact_text(surface_id, max_chars=120),
            locator=compact_text(locator, max_chars=320),
            target_kind=compact_text(target_kind, max_chars=120),
            risk_classification=compact_text(risk_classification, max_chars=80),
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            normalized_locator=compact_text(normalized_locator, max_chars=320),
            matched_rule_id=compact_text(matched_rule_id or "", max_chars=120) or None,
            metadata=sanitize_durable_mapping(metadata or {}),
        )


__all__ = [
    "MutationGuardDecision",
    "MutationGuardRequest",
    "MutationGuardService",
]
