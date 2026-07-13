"""Typed deny-by-default mutation-surface registry for future Phase 7 work."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import compact_text, sanitize_durable_mapping

_PACKAGE_SPEC_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\],<>=!~ ]*$")
_PLUGIN_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-@:]*$")
_SANDBOX_LOCATORS = frozenset(
    {
        "ephemeral_workspace",
        "sandbox_runtime",
        "sandbox_workspace",
        "temp_workspace",
        "temporary_workspace",
    }
)


def _normalized_key(value: str) -> str:
    """Normalize one registry key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


@dataclass(slots=True, frozen=True)
class MutationSurfaceDefinition:
    """One typed mutation-surface registration."""

    surface_id: str
    display_name: str
    allowed_target_kinds: tuple[str, ...]
    description: str
    requires_existing_file: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProtectedSurfaceRule:
    """One explicit protected-surface rule evaluated before any allow decision."""

    rule_id: str
    pattern: str
    match_mode: str
    description: str


@dataclass(slots=True, frozen=True)
class MutationSurfaceRequest:
    """One typed mutation-surface lookup request."""

    surface_id: str
    locator: str
    target_kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class MutationSurfaceDecision:
    """One deny-by-default mutation-surface decision."""

    decision: str
    surface_id: str
    locator: str
    target_kind: str
    reason_code: str
    reason: str
    normalized_locator: str = ""
    matched_rule_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        """Return True only when the decision is explicitly allowed."""

        return self.decision == "allowed"


class MutationSurfaceRegistry:
    """Register and evaluate narrow mutation surfaces with protected-path denial."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        surfaces: Iterable[MutationSurfaceDefinition] | None = None,
        protected_rules: Iterable[ProtectedSurfaceRule] | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self._workspace_root_text = self.workspace_root.as_posix().lower().rstrip("/")
        self._surfaces: dict[str, MutationSurfaceDefinition] = {}
        self._protected_rules: tuple[ProtectedSurfaceRule, ...] = tuple(
            protected_rules or self._default_protected_rules()
        )
        for surface in surfaces or self._default_surfaces():
            self.register_surface(surface)

    def register_surface(self, surface: MutationSurfaceDefinition) -> MutationSurfaceDefinition:
        """Register one typed surface definition."""

        normalized_surface_id = _normalized_key(surface.surface_id)
        if not normalized_surface_id:
            raise ValueError("Surface registration requires a non-empty surface id.")
        if normalized_surface_id in self._surfaces:
            raise ValueError(f"Surface '{normalized_surface_id}' is already registered.")
        if not surface.allowed_target_kinds:
            raise ValueError("Surface registration requires at least one allowed target kind.")
        normalized_target_kinds = tuple(
            dict.fromkeys(
                _normalized_key(target_kind)
                for target_kind in surface.allowed_target_kinds
                if _normalized_key(target_kind)
            )
        )
        if not normalized_target_kinds:
            raise ValueError("Surface registration requires non-empty normalized target kinds.")
        registered = MutationSurfaceDefinition(
            surface_id=normalized_surface_id,
            display_name=compact_text(surface.display_name, max_chars=120),
            allowed_target_kinds=normalized_target_kinds,
            description=compact_text(surface.description, max_chars=320),
            requires_existing_file=bool(surface.requires_existing_file),
            metadata=sanitize_durable_mapping(surface.metadata),
        )
        self._surfaces[normalized_surface_id] = registered
        return registered

    def get_surface(self, surface_id: str) -> MutationSurfaceDefinition | None:
        """Return one registered surface by normalized id."""

        return self._surfaces.get(_normalized_key(surface_id))

    def list_surfaces(self) -> tuple[MutationSurfaceDefinition, ...]:
        """Return registered surfaces in deterministic order."""

        return tuple(self._surfaces[key] for key in sorted(self._surfaces))

    def list_protected_rules(self) -> tuple[ProtectedSurfaceRule, ...]:
        """Return protected-surface rules in deterministic order."""

        return self._protected_rules

    def evaluate(self, request: MutationSurfaceRequest) -> MutationSurfaceDecision:
        """Evaluate one mutation target against registered and protected surfaces."""

        normalized_surface_id = _normalized_key(request.surface_id)
        normalized_target_kind = _normalized_key(request.target_kind)
        normalized_locator = self._normalize_locator(request.locator)
        surface = self._surfaces.get(normalized_surface_id)
        if surface is None:
            return self._deny(
                surface_id=normalized_surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="surface_unregistered",
                reason="Unknown mutation surfaces are denied by default.",
                normalized_locator=normalized_locator,
            )
        if normalized_target_kind not in surface.allowed_target_kinds:
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="target_kind_not_allowed",
                reason="The requested target kind is not allowed for the registered mutation surface.",
                normalized_locator=normalized_locator,
            )

        if surface.surface_id == "approved_source_file":
            return self._evaluate_source_file(surface, request, normalized_locator, normalized_target_kind)
        if surface.surface_id == "sandbox":
            return self._evaluate_sandbox(surface, request, normalized_locator, normalized_target_kind)
        if surface.surface_id == "package":
            return self._evaluate_package(surface, request, normalized_locator, normalized_target_kind)
        if surface.surface_id == "plugin":
            return self._evaluate_plugin(surface, request, normalized_locator, normalized_target_kind)
        return self._deny(
            surface_id=surface.surface_id,
            locator=request.locator,
            target_kind=normalized_target_kind,
            reason_code="surface_handler_missing",
            reason="The registered surface has no active evaluator and remains denied by default.",
            normalized_locator=normalized_locator,
        )

    def _evaluate_source_file(
        self,
        surface: MutationSurfaceDefinition,
        request: MutationSurfaceRequest,
        normalized_locator: str,
        normalized_target_kind: str,
    ) -> MutationSurfaceDecision:
        """Evaluate one source-file mutation request."""

        candidate_path = self._normalize_workspace_path(request.locator)
        if not candidate_path:
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="unknown_target",
                reason="Source-file mutation requires one known workspace-relative file target.",
                normalized_locator=normalized_locator,
            )
        matched_rule = self._match_protected_rule(candidate_path)
        if matched_rule is not None:
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="protected_surface",
                reason="Protected files and directories cannot be registered as mutation targets.",
                normalized_locator=candidate_path,
                matched_rule_id=matched_rule.rule_id,
            )
        candidate_file = self.workspace_root / Path(candidate_path)
        if surface.requires_existing_file and not candidate_file.is_file():
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="unknown_target",
                reason="Approved source-file mutation requires an existing workspace file target.",
                normalized_locator=candidate_path,
            )
        return self._allow(
            surface_id=surface.surface_id,
            locator=request.locator,
            target_kind=normalized_target_kind,
            reason_code="surface_allowed",
            reason="The workspace file target is inside the approved source-file mutation surface.",
            normalized_locator=candidate_path,
        )

    def _evaluate_sandbox(
        self,
        surface: MutationSurfaceDefinition,
        request: MutationSurfaceRequest,
        normalized_locator: str,
        normalized_target_kind: str,
    ) -> MutationSurfaceDecision:
        """Evaluate one sandbox mutation request."""

        sandbox_locator = _normalized_key(request.locator)
        if sandbox_locator not in _SANDBOX_LOCATORS:
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="unknown_target",
                reason="Only the registered sandbox identifiers are allowed.",
                normalized_locator=normalized_locator,
            )
        return self._allow(
            surface_id=surface.surface_id,
            locator=request.locator,
            target_kind=normalized_target_kind,
            reason_code="surface_allowed",
            reason="The sandbox target matches one registered sandbox mutation surface.",
            normalized_locator=sandbox_locator,
        )

    def _evaluate_package(
        self,
        surface: MutationSurfaceDefinition,
        request: MutationSurfaceRequest,
        normalized_locator: str,
        normalized_target_kind: str,
    ) -> MutationSurfaceDecision:
        """Evaluate one package mutation request."""

        locator = compact_text(request.locator, max_chars=240)
        if not locator or not _PACKAGE_SPEC_PATTERN.fullmatch(locator):
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="unknown_target",
                reason="Only typed package or dependency specifiers are allowed in the package mutation surface.",
                normalized_locator=normalized_locator,
            )
        return self._allow(
            surface_id=surface.surface_id,
            locator=request.locator,
            target_kind=normalized_target_kind,
            reason_code="surface_allowed",
            reason="The package target matches the typed package mutation surface.",
            normalized_locator=locator,
        )

    def _evaluate_plugin(
        self,
        surface: MutationSurfaceDefinition,
        request: MutationSurfaceRequest,
        normalized_locator: str,
        normalized_target_kind: str,
    ) -> MutationSurfaceDecision:
        """Evaluate one plugin mutation request."""

        locator = compact_text(request.locator, max_chars=240)
        if not locator or not _PLUGIN_IDENTIFIER_PATTERN.fullmatch(locator):
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="unknown_target",
                reason="Only typed plugin identifiers are allowed in the plugin mutation surface.",
                normalized_locator=normalized_locator,
            )
        candidate_path = self._normalize_workspace_path(locator)
        matched_rule = self._match_protected_rule(candidate_path) if candidate_path else None
        if matched_rule is not None:
            return self._deny(
                surface_id=surface.surface_id,
                locator=request.locator,
                target_kind=normalized_target_kind,
                reason_code="protected_surface",
                reason="Protected files and directories cannot be targeted through the plugin mutation surface.",
                normalized_locator=candidate_path,
                matched_rule_id=matched_rule.rule_id,
            )
        return self._allow(
            surface_id=surface.surface_id,
            locator=request.locator,
            target_kind=normalized_target_kind,
            reason_code="surface_allowed",
            reason="The plugin target matches the typed plugin mutation surface.",
            normalized_locator=locator,
        )

    def _allow(
        self,
        *,
        surface_id: str,
        locator: str,
        target_kind: str,
        reason_code: str,
        reason: str,
        normalized_locator: str,
    ) -> MutationSurfaceDecision:
        """Build one allowed surface decision."""

        return MutationSurfaceDecision(
            decision="allowed",
            surface_id=surface_id,
            locator=compact_text(locator, max_chars=320),
            target_kind=target_kind,
            reason_code=reason_code,
            reason=compact_text(reason, max_chars=320),
            normalized_locator=compact_text(normalized_locator, max_chars=320),
        )

    def _deny(
        self,
        *,
        surface_id: str,
        locator: str,
        target_kind: str,
        reason_code: str,
        reason: str,
        normalized_locator: str,
        matched_rule_id: str | None = None,
    ) -> MutationSurfaceDecision:
        """Build one denied surface decision."""

        return MutationSurfaceDecision(
            decision="denied",
            surface_id=surface_id,
            locator=compact_text(locator, max_chars=320),
            target_kind=target_kind,
            reason_code=reason_code,
            reason=compact_text(reason, max_chars=320),
            normalized_locator=compact_text(normalized_locator, max_chars=320),
            matched_rule_id=matched_rule_id,
        )

    def _normalize_locator(self, locator: str) -> str:
        """Normalize one caller-supplied locator for durable comparison."""

        value = compact_text(locator, max_chars=320).replace("\\", "/")
        while value.startswith("./"):
            value = value[2:]
        return value

    def _normalize_workspace_path(self, locator: str) -> str:
        """Normalize one workspace path candidate into a relative POSIX path."""

        value = self._normalize_locator(locator)
        if not value:
            return ""
        lowered = value.lower()
        if lowered == self._workspace_root_text:
            return ""
        workspace_prefix = f"{self._workspace_root_text}/"
        if lowered.startswith(workspace_prefix):
            value = value[len(workspace_prefix) :]
        elif re.match(r"^[A-Za-z]:/", value):
            return ""
        parts: list[str] = []
        for part in value.split("/"):
            cleaned = part.strip()
            if cleaned in {"", "."}:
                continue
            if cleaned == "..":
                if not parts:
                    return ""
                parts.pop()
                continue
            parts.append(cleaned)
        return "/".join(parts)

    def _match_protected_rule(self, normalized_path: str) -> ProtectedSurfaceRule | None:
        """Return the first matching protected-surface rule for one normalized path."""

        candidate = compact_text(normalized_path, max_chars=320).strip("/")
        if not candidate:
            return None
        candidate_lower = candidate.lower()
        for rule in self._protected_rules:
            pattern = rule.pattern.lower()
            if rule.match_mode == "exact" and candidate_lower == pattern:
                return rule
            if rule.match_mode == "prefix" and (
                candidate_lower == pattern or candidate_lower.startswith(f"{pattern}/")
            ):
                return rule
        return None

    def _default_surfaces(self) -> tuple[MutationSurfaceDefinition, ...]:
        """Return the built-in mutation surfaces for Phase 7 Milestone 2."""

        return (
            MutationSurfaceDefinition(
                surface_id="sandbox",
                display_name="Sandbox",
                allowed_target_kinds=("sandbox_runtime", "sandbox_workspace"),
                description="Ephemeral sandbox runtime and workspace targets for narrow approved mutation.",
                metadata={"executor_categories": ("sandbox_execution",)},
            ),
            MutationSurfaceDefinition(
                surface_id="package",
                display_name="Package",
                allowed_target_kinds=("dependency_spec", "package_spec"),
                description="Typed package and dependency targets for future narrow approved mutation.",
                metadata={"executor_categories": ("package_management",)},
            ),
            MutationSurfaceDefinition(
                surface_id="plugin",
                display_name="Plugin",
                allowed_target_kinds=("plugin_identifier", "plugin_package"),
                description="Typed plugin and capability identifiers for future narrow approved mutation.",
                metadata={"executor_categories": ("plugin_management",)},
            ),
            MutationSurfaceDefinition(
                surface_id="approved_source_file",
                display_name="Approved Source Files",
                allowed_target_kinds=("source_file",),
                description="Existing workspace source files outside protected surfaces.",
                requires_existing_file=True,
                metadata={"executor_categories": ("code_development",)},
            ),
        )

    def _default_protected_rules(self) -> tuple[ProtectedSurfaceRule, ...]:
        """Return the built-in protected surfaces for Phase 7 Milestone 2."""

        return (
            ProtectedSurfaceRule(
                rule_id="protected.narvis",
                pattern="narvis.py",
                match_mode="exact",
                description="The composition root must remain protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.core",
                pattern="core",
                match_mode="prefix",
                description="Core runtime internals are protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.ai",
                pattern="ai",
                match_mode="prefix",
                description="AI runtime internals are protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.memory",
                pattern="memory",
                match_mode="prefix",
                description="Memory internals are protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.dashboard",
                pattern="dashboard",
                match_mode="prefix",
                description="Dashboard internals are protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.evolution_runtime",
                pattern="evolution/runtime.py",
                match_mode="exact",
                description="The evolution runtime control plane is protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.evolution_models",
                pattern="evolution/models.py",
                match_mode="exact",
                description="The evolution durable model layer is protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.evolution_inventory",
                pattern="evolution/inventory.py",
                match_mode="exact",
                description="The evolution inventory builder is protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.docs",
                pattern="docs",
                match_mode="prefix",
                description="Documentation files are protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.data",
                pattern="data",
                match_mode="prefix",
                description="Runtime data files are protected.",
            ),
            ProtectedSurfaceRule(
                rule_id="protected.git",
                pattern=".git",
                match_mode="prefix",
                description="Git internals are protected.",
            ),
        )


__all__ = [
    "MutationSurfaceDecision",
    "MutationSurfaceDefinition",
    "MutationSurfaceRegistry",
    "MutationSurfaceRequest",
    "ProtectedSurfaceRule",
]
