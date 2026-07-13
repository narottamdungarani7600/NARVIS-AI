"""Typed placeholder local-plugin executor for Phase 8 Milestone 4."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from .models import MutationTarget, RollbackArtifact, compact_text, sanitize_durable_mapping, stable_id
from .mutation_surfaces import MutationSurfaceRegistry, MutationSurfaceRequest

PluginOperation = Literal["install", "uninstall", "enable", "disable"]
PluginSourceKind = Literal["local"]

_DEFAULT_APPROVED_PLUGIN_IDENTIFIERS = ("cloud.integration",)
_ALLOWED_OPERATIONS = frozenset({"install", "uninstall", "enable", "disable"})
_ALLOWED_TARGET_KINDS = frozenset({"plugin_identifier"})
_ALLOWED_ACTION_KINDS_BY_OPERATION = {
    "install": frozenset({"plugin_install"}),
    "uninstall": frozenset({"plugin_remove"}),
    "enable": frozenset({"plugin_enable"}),
    "disable": frozenset({"plugin_disable"}),
}
_ROLLBACK_OPERATION_BY_OPERATION = {
    "install": "uninstall",
    "uninstall": "install",
    "enable": "disable",
    "disable": "enable",
}
_PLUGIN_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_EXTERNAL_REPOSITORY_MARKERS = (
    "://",
    "git@",
    "git+",
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "/",
    "\\",
    ":",
    "@",
)
_NETWORK_METADATA_KEYS = frozenset({"endpoint", "network", "repository", "repository_url", "remote", "url"})
_ROLLBACK_ARTIFACT_KIND = "local_plugin_rollback_plan"


def _normalized_key(value: str) -> str:
    """Normalize one executor key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


@dataclass(slots=True, frozen=True)
class PluginExecutionRequest:
    """One typed local-plugin mutation request for placeholder-only processing."""

    mutation_target: MutationTarget
    operation: PluginOperation
    source_kind: PluginSourceKind = "local"
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class PluginExecutionResult:
    """One typed plugin execution result that never represents a real plugin mutation."""

    decision: str
    reason_code: str
    reason: str
    operation: str
    mutation_target_id: str
    plugin_identifier: str = ""
    source_kind: str = ""
    rollback_artifact: RollbackArtifact | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        """Return True when the plugin operation was accepted for simulated execution."""

        return self.decision == "simulated"


@dataclass(slots=True, frozen=True)
class _PreparedPluginExecutionRequest:
    """Normalized local-plugin request fields shared by placeholder execution helpers."""

    mutation_target: MutationTarget
    operation: str
    source_kind: str
    actor: str
    plugin_identifier: str
    metadata: dict[str, Any]


class PluginExecutorService:
    """Validate approved local-plugin requests and return safe placeholder execution plans only."""

    def __init__(
        self,
        *,
        approved_plugin_identifiers: Iterable[str] | None = None,
        surface_registry: MutationSurfaceRegistry | None = None,
    ) -> None:
        candidates = approved_plugin_identifiers or _DEFAULT_APPROVED_PLUGIN_IDENTIFIERS
        normalized_identifiers = tuple(_normalized_key(identifier) for identifier in candidates)
        if not normalized_identifiers or any(not self._is_valid_plugin_identifier(identifier) for identifier in normalized_identifiers):
            raise ValueError("Approved plugin identifiers must be non-empty local plugin identifiers.")
        self._approved_plugin_identifiers = frozenset(normalized_identifiers)
        self.surface_registry = surface_registry or MutationSurfaceRegistry()

    def list_allowed_operations(self) -> tuple[str, ...]:
        """Return supported plugin operations in deterministic order."""

        return tuple(sorted(_ALLOWED_OPERATIONS))

    def list_approved_plugin_identifiers(self) -> tuple[str, ...]:
        """Return explicitly approved local plugin identifiers in deterministic order."""

        return tuple(sorted(self._approved_plugin_identifiers))

    def execute(self, request: PluginExecutionRequest) -> PluginExecutionResult:
        """Validate one local plugin request and simulate it without invoking plugin tooling."""

        prepared, rejected = self._prepare_request(request)
        if rejected is not None or prepared is None:
            return rejected or self._reject(
                operation="",
                mutation_target_id="",
                reason_code="plugin_request_invalid",
                reason="The plugin execution request could not be normalized safely.",
            )

        rollback_artifact = self._build_rollback_artifact(prepared)
        return PluginExecutionResult(
            decision="simulated",
            reason_code="plugin_operation_simulated",
            reason="The approved local plugin request was validated and simulated without invoking plugin, package, shell, Git, or network tooling.",
            operation=prepared.operation,
            mutation_target_id=prepared.mutation_target.mutation_target_id,
            plugin_identifier=prepared.plugin_identifier,
            source_kind=prepared.source_kind,
            rollback_artifact=rollback_artifact,
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "plugin_registry_mutated": False,
                    "network_invoked": False,
                    "shell_invoked": False,
                    "package_manager_invoked": False,
                    "git_invoked": False,
                    "executor_category": prepared.mutation_target.executor_category,
                    "target_kind": prepared.mutation_target.target_kind,
                    "risk_classification": prepared.mutation_target.risk_classification,
                }
            ),
        )

    def _prepare_request(
        self,
        request: PluginExecutionRequest,
    ) -> tuple[_PreparedPluginExecutionRequest | None, PluginExecutionResult | None]:
        """Normalize one local plugin request or return one typed rejection."""

        target = request.mutation_target
        if not isinstance(target, MutationTarget):
            return None, self._reject(
                operation=_normalized_key(request.operation),
                mutation_target_id="",
                reason_code="invalid_mutation_target",
                reason="Plugin execution requires one typed MutationTarget.",
            )

        operation = _normalized_key(request.operation)
        if operation not in _ALLOWED_OPERATIONS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                reason_code="invalid_operation",
                reason="Plugin execution supports only install, uninstall, enable, or disable operations.",
            )

        mutation_target_id = compact_text(target.mutation_target_id, max_chars=120)
        if not mutation_target_id:
            return None, self._reject(
                operation=operation,
                mutation_target_id="",
                reason_code="mutation_target_id_required",
                reason="Plugin execution requires a non-empty mutation target identifier.",
            )

        if _normalized_key(target.executor_category) != "plugin_management":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_executor_category",
                reason="Plugin execution accepts only mutation targets classified for plugin management.",
            )

        if _normalized_key(target.target_kind) not in _ALLOWED_TARGET_KINDS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_target_kind",
                reason="Plugin execution allows only approved local plugin_identifier targets.",
            )

        if _normalized_key(target.risk_classification) != "medium":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="plugin_risk_classification_required",
                reason="Plugin mutation simulation requires the medium risk classification used by the existing evolution policy.",
            )

        allowed_action_kinds = _ALLOWED_ACTION_KINDS_BY_OPERATION[operation]
        action_kind = _normalized_key(target.action_kind)
        if action_kind not in allowed_action_kinds:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="action_kind_mismatch",
                reason="The mutation target action kind does not match the requested plugin operation.",
                metadata={"allowed_action_kinds": tuple(sorted(allowed_action_kinds))},
            )

        source_kind = _normalized_key(request.source_kind)
        if source_kind != "local":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                source_kind=source_kind,
                reason_code="network_operation_not_allowed",
                reason="Plugin execution accepts only explicit local plugin targets and never performs network operations.",
            )
        if self._has_network_metadata(request.metadata):
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                source_kind=source_kind,
                reason_code="network_operation_not_allowed",
                reason="Plugin execution rejects repository, endpoint, URL, remote, and network metadata.",
            )

        raw_identifier = compact_text(target.locator, max_chars=240).strip()
        if self._looks_like_external_repository(raw_identifier):
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                source_kind=source_kind,
                reason_code="external_repository_not_allowed",
                reason="Plugin execution rejects external repositories, URLs, paths, and Git-style plugin locators.",
            )

        plugin_identifier = _normalized_key(raw_identifier)
        if not self._is_valid_plugin_identifier(plugin_identifier):
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                source_kind=source_kind,
                reason_code="invalid_plugin_identifier",
                reason="Plugin execution requires one typed local plugin identifier.",
            )
        if plugin_identifier not in self._approved_plugin_identifiers:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                source_kind=source_kind,
                reason_code="unknown_plugin_identifier",
                reason="Only explicitly approved local plugin identifiers may be simulated.",
            )

        surface_decision = self.surface_registry.evaluate(
            MutationSurfaceRequest(
                surface_id="plugin",
                locator=plugin_identifier,
                target_kind="plugin_identifier",
                metadata=request.metadata,
            )
        )
        if not surface_decision.allowed:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                source_kind=source_kind,
                reason_code=surface_decision.reason_code,
                reason=surface_decision.reason,
                metadata={"validation_layer": "mutation_surface_registry"},
            )

        return (
            _PreparedPluginExecutionRequest(
                mutation_target=target,
                operation=operation,
                source_kind=source_kind,
                actor=compact_text(request.actor or "narvis", max_chars=120) or "narvis",
                plugin_identifier=plugin_identifier,
                metadata=sanitize_durable_mapping(request.metadata),
            ),
            None,
        )

    def _is_valid_plugin_identifier(self, identifier: str) -> bool:
        """Return True only for compact local plugin identifiers without repository syntax."""

        return bool(identifier and _PLUGIN_IDENTIFIER_PATTERN.fullmatch(identifier))

    def _looks_like_external_repository(self, locator: str) -> bool:
        """Return True when a locator could describe a repository, URL, or filesystem location."""

        normalized_locator = compact_text(locator, max_chars=240).strip().lower()
        return bool(
            not normalized_locator
            or any(marker in normalized_locator for marker in _EXTERNAL_REPOSITORY_MARKERS)
            or normalized_locator.startswith(".")
            or any(character.isspace() for character in normalized_locator)
        )

    def _has_network_metadata(self, metadata: dict[str, Any]) -> bool:
        """Return True when request metadata attempts to introduce a remote operation channel."""

        return any(_normalized_key(key) in _NETWORK_METADATA_KEYS and bool(value) for key, value in metadata.items())

    def _build_rollback_artifact(self, request: _PreparedPluginExecutionRequest) -> RollbackArtifact:
        """Create rollback metadata without claiming the plugin state was observed or changed."""

        rollback_operation = _ROLLBACK_OPERATION_BY_OPERATION[request.operation]
        metadata = sanitize_durable_mapping(
            {
                "operation": request.operation,
                "plugin_identifier": request.plugin_identifier,
                "source_kind": request.source_kind,
                "target_kind": request.mutation_target.target_kind,
                "rollback_operation": rollback_operation,
                "pre_execution_state_required": True,
                "pre_execution_state_captured": False,
                "rollback_ready": False,
                "placeholder_only": True,
                "real_mutation_performed": False,
            }
        )
        fingerprint = stable_id(
            "local_plugin_rollback_plan_fingerprint",
            {
                "mutation_target_id": request.mutation_target.mutation_target_id,
                "operation": request.operation,
                "plugin_identifier": request.plugin_identifier,
                "source_kind": request.source_kind,
                "rollback_operation": rollback_operation,
            },
        )
        return RollbackArtifact(
            rollback_artifact_id=stable_id("local_plugin_rollback_plan", fingerprint),
            mutation_run_id=compact_text(str(request.metadata.get("mutation_run_id", "")), max_chars=120),
            mutation_step_run_id=compact_text(str(request.metadata.get("mutation_step_run_id", "")), max_chars=120),
            mutation_target_id=request.mutation_target.mutation_target_id,
            artifact_kind=_ROLLBACK_ARTIFACT_KIND,
            artifact_locator=request.plugin_identifier,
            artifact_fingerprint=fingerprint,
            status="planned",
            metadata=metadata,
        )

    def _reject(
        self,
        *,
        operation: str,
        mutation_target_id: str,
        reason_code: str,
        reason: str,
        source_kind: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PluginExecutionResult:
        """Build one typed fail-closed plugin execution rejection."""

        return PluginExecutionResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            operation=compact_text(operation, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            source_kind=compact_text(source_kind, max_chars=80),
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "plugin_registry_mutated": False,
                    "network_invoked": False,
                    "shell_invoked": False,
                    "package_manager_invoked": False,
                    "git_invoked": False,
                    **(metadata or {}),
                }
            ),
        )


__all__ = [
    "PluginExecutionRequest",
    "PluginExecutionResult",
    "PluginExecutorService",
    "PluginOperation",
    "PluginSourceKind",
]
