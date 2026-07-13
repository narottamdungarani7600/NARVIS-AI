"""Typed placeholder source-file executor for Phase 8 Milestone 3."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .models import MutationTarget, RollbackArtifact, compact_text, sanitize_durable_mapping, stable_id
from .mutation_surfaces import MutationSurfaceRegistry, MutationSurfaceRequest

SourceOperation = Literal["modify", "delete"]

_ALLOWED_OPERATIONS = frozenset({"modify", "delete"})
_ALLOWED_TARGET_KINDS = frozenset({"source_file"})
_ALLOWED_SOURCE_EXTENSIONS = frozenset({".py", ".pyi"})
_ALLOWED_ACTION_KINDS_BY_OPERATION = {
    "modify": frozenset({"source_modify"}),
    "delete": frozenset({"source_delete"}),
}
_ROLLBACK_ARTIFACT_KIND = "source_file_rollback_plan"


def _normalized_key(value: str) -> str:
    """Normalize one executor key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


@dataclass(slots=True, frozen=True)
class SourceExecutionRequest:
    """One typed source-file mutation request for placeholder-only processing."""

    mutation_target: MutationTarget
    operation: SourceOperation
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SourceExecutionResult:
    """One typed source execution result that never represents a real file mutation."""

    decision: str
    reason_code: str
    reason: str
    operation: str
    mutation_target_id: str
    relative_path: str = ""
    source_content_sha256: str = ""
    rollback_artifact: RollbackArtifact | None = None
    matched_rule_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        """Return True when the source operation was accepted for simulated execution."""

        return self.decision == "simulated"


@dataclass(slots=True, frozen=True)
class _PreparedSourceExecutionRequest:
    """Normalized source request fields shared by placeholder execution helpers."""

    mutation_target: MutationTarget
    operation: str
    actor: str
    source_path: Path
    relative_path: str
    source_content_sha256: str
    source_size_bytes: int
    metadata: dict[str, Any]


class SourceExecutorService:
    """Validate approved source-file requests and return safe placeholder execution plans only."""

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        surface_registry: MutationSurfaceRegistry | None = None,
    ) -> None:
        if surface_registry is not None and workspace_root is not None:
            supplied_root = Path(workspace_root).resolve()
            if supplied_root != surface_registry.workspace_root.resolve():
                raise ValueError("workspace_root must match the supplied mutation surface registry workspace root.")
        self.surface_registry = surface_registry or MutationSurfaceRegistry(workspace_root=workspace_root)
        self.workspace_root = self.surface_registry.workspace_root.resolve()

    def list_allowed_operations(self) -> tuple[str, ...]:
        """Return supported source operations in deterministic order."""

        return tuple(sorted(_ALLOWED_OPERATIONS))

    def list_allowed_target_kinds(self) -> tuple[str, ...]:
        """Return allowed source mutation target kinds in deterministic order."""

        return tuple(sorted(_ALLOWED_TARGET_KINDS))

    def execute(self, request: SourceExecutionRequest) -> SourceExecutionResult:
        """Validate one source request and simulate it without changing any files."""

        prepared, rejected = self._prepare_request(request)
        if rejected is not None or prepared is None:
            return rejected or self._reject(
                operation="",
                mutation_target_id="",
                reason_code="source_request_invalid",
                reason="The source execution request could not be normalized safely.",
            )

        rollback_artifact = self._build_rollback_artifact(prepared)
        return SourceExecutionResult(
            decision="simulated",
            reason_code="source_operation_simulated",
            reason="The source request was validated and simulated without reading or writing through a shell or file-mutation executor.",
            operation=prepared.operation,
            mutation_target_id=prepared.mutation_target.mutation_target_id,
            relative_path=prepared.relative_path,
            source_content_sha256=prepared.source_content_sha256,
            rollback_artifact=rollback_artifact,
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "source_file_written": False,
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
        request: SourceExecutionRequest,
    ) -> tuple[_PreparedSourceExecutionRequest | None, SourceExecutionResult | None]:
        """Normalize one source request or return one typed rejection."""

        target = request.mutation_target
        if not isinstance(target, MutationTarget):
            return None, self._reject(
                operation=_normalized_key(request.operation),
                mutation_target_id="",
                reason_code="invalid_mutation_target",
                reason="Source execution requires one typed MutationTarget.",
            )

        operation = _normalized_key(request.operation)
        if operation not in _ALLOWED_OPERATIONS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                reason_code="invalid_operation",
                reason="Source execution supports only modify or delete operations for existing approved source files.",
            )

        mutation_target_id = compact_text(target.mutation_target_id, max_chars=120)
        if not mutation_target_id:
            return None, self._reject(
                operation=operation,
                mutation_target_id="",
                reason_code="mutation_target_id_required",
                reason="Source execution requires a non-empty mutation target identifier.",
            )

        if _normalized_key(target.executor_category) != "code_development":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_executor_category",
                reason="Source execution accepts only mutation targets classified for code development.",
            )

        if _normalized_key(target.target_kind) not in _ALLOWED_TARGET_KINDS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_target_kind",
                reason="Source execution allows only approved source_file targets.",
            )

        if _normalized_key(target.risk_classification) != "high":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="source_risk_classification_required",
                reason="Source mutation simulation requires the high risk classification used by the existing evolution policy.",
            )

        allowed_action_kinds = _ALLOWED_ACTION_KINDS_BY_OPERATION[operation]
        action_kind = _normalized_key(target.action_kind)
        if action_kind not in allowed_action_kinds:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="action_kind_mismatch",
                reason="The mutation target action kind does not match the requested source operation.",
                metadata={"allowed_action_kinds": tuple(sorted(allowed_action_kinds))},
            )

        if self._contains_directory_traversal(target.locator):
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="directory_traversal",
                reason="Source execution rejects every directory-traversal path before workspace resolution.",
            )

        source_path, relative_path = self._resolve_workspace_path(target.locator)
        if source_path is None or not relative_path:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="path_outside_workspace",
                reason="Source execution requires a path strictly inside the configured workspace.",
            )

        surface_decision = self.surface_registry.evaluate(
            MutationSurfaceRequest(
                surface_id="approved_source_file",
                locator=relative_path,
                target_kind="source_file",
                metadata=request.metadata,
            )
        )
        if not surface_decision.allowed:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                relative_path=relative_path,
                reason_code=surface_decision.reason_code,
                reason=surface_decision.reason,
                matched_rule_id=surface_decision.matched_rule_id,
                metadata={"validation_layer": "mutation_surface_registry"},
            )

        if source_path.suffix.lower() not in _ALLOWED_SOURCE_EXTENSIONS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                relative_path=relative_path,
                reason_code="source_file_type_not_allowed",
                reason="Source execution permits only approved Python source files with .py or .pyi extensions.",
            )

        try:
            source_content = source_path.read_bytes()
        except OSError as error:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                relative_path=relative_path,
                reason_code="source_file_unreadable",
                reason="The approved source file could not be read safely for placeholder rollback metadata.",
                metadata={"error_type": type(error).__name__},
            )

        return (
            _PreparedSourceExecutionRequest(
                mutation_target=target,
                operation=operation,
                actor=compact_text(request.actor or "narvis", max_chars=120) or "narvis",
                source_path=source_path,
                relative_path=relative_path,
                source_content_sha256=hashlib.sha256(source_content).hexdigest(),
                source_size_bytes=len(source_content),
                metadata=sanitize_durable_mapping(request.metadata),
            ),
            None,
        )

    def _contains_directory_traversal(self, locator: str) -> bool:
        """Return True when the raw locator contains any parent-directory traversal segment."""

        normalized_locator = compact_text(locator, max_chars=320).replace("\\", "/")
        return any(segment.strip() == ".." for segment in normalized_locator.split("/"))

    def _resolve_workspace_path(self, locator: str) -> tuple[Path | None, str]:
        """Resolve one source locator and require it to remain inside the configured workspace."""

        normalized_locator = compact_text(locator, max_chars=320).strip()
        if not normalized_locator:
            return None, ""
        try:
            candidate = Path(normalized_locator)
            if not candidate.is_absolute():
                candidate = self.workspace_root / candidate
            resolved_path = candidate.resolve()
            relative_path = resolved_path.relative_to(self.workspace_root).as_posix()
        except (OSError, ValueError):
            return None, ""
        return resolved_path, relative_path

    def _build_rollback_artifact(self, request: _PreparedSourceExecutionRequest) -> RollbackArtifact:
        """Create rollback metadata without retaining source content or changing the file."""

        metadata = sanitize_durable_mapping(
            {
                "operation": request.operation,
                "relative_path": request.relative_path,
                "target_kind": request.mutation_target.target_kind,
                "rollback_operation": "restore_verified_snapshot",
                "pre_execution_fingerprint": request.source_content_sha256,
                "pre_execution_size_bytes": request.source_size_bytes,
                "pre_execution_content_captured": False,
                "rollback_ready": False,
                "placeholder_only": True,
                "real_mutation_performed": False,
            }
        )
        fingerprint = stable_id(
            "source_file_rollback_plan_fingerprint",
            {
                "mutation_target_id": request.mutation_target.mutation_target_id,
                "operation": request.operation,
                "relative_path": request.relative_path,
                "source_content_sha256": request.source_content_sha256,
                "source_size_bytes": request.source_size_bytes,
            },
        )
        return RollbackArtifact(
            rollback_artifact_id=stable_id("source_file_rollback_plan", fingerprint),
            mutation_run_id=compact_text(str(request.metadata.get("mutation_run_id", "")), max_chars=120),
            mutation_step_run_id=compact_text(str(request.metadata.get("mutation_step_run_id", "")), max_chars=120),
            mutation_target_id=request.mutation_target.mutation_target_id,
            artifact_kind=_ROLLBACK_ARTIFACT_KIND,
            artifact_locator=request.relative_path,
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
        relative_path: str = "",
        matched_rule_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceExecutionResult:
        """Build one typed fail-closed source execution rejection."""

        return SourceExecutionResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            operation=compact_text(operation, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            relative_path=compact_text(relative_path, max_chars=320),
            matched_rule_id=compact_text(matched_rule_id or "", max_chars=120) or None,
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "source_file_written": False,
                    "shell_invoked": False,
                    "package_manager_invoked": False,
                    "git_invoked": False,
                    **(metadata or {}),
                }
            ),
        )


__all__ = [
    "SourceExecutionRequest",
    "SourceExecutionResult",
    "SourceExecutorService",
    "SourceOperation",
]
