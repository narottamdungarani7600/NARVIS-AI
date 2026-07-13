"""Typed sandbox-local mutation executor for Phase 8 Milestone 1."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import MutationTarget, RollbackArtifact, compact_text, sanitize_durable_mapping, stable_id

_ALLOWED_MODES = frozenset({"apply", "rollback"})
_ALLOWED_OPERATIONS = frozenset({"create_directory", "write_text"})
_ALLOWED_TARGET_KINDS = frozenset({"sandbox_runtime", "sandbox_workspace"})
_ALLOWED_EXECUTOR_CATEGORIES = frozenset({"sandbox", "sandbox_execution"})
_ALLOWED_TEXT_FILE_EXTENSIONS = frozenset({".csv", ".dat", ".json", ".log", ".tmp", ".txt"})
_BLOCKED_PATH_SEGMENTS = frozenset({".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules"})
_DIRECTORY_ARTIFACT_KIND = "sandbox_directory_snapshot"
_WRITE_TEXT_ARTIFACT_KIND = "sandbox_text_snapshot"


def _normalized_key(value: str) -> str:
    """Normalize one executor key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


@dataclass(slots=True, frozen=True)
class SandboxExecutionRequest:
    """One typed sandbox-local execution request."""

    mutation_target: MutationTarget
    operation: str
    mode: str = "apply"
    text_content: str | None = None
    rollback_artifact: RollbackArtifact | None = None
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SandboxExecutionResult:
    """One typed sandbox-local execution result."""

    decision: str
    reason_code: str
    reason: str
    mode: str
    operation: str
    mutation_target_id: str
    locator: str
    resolved_locator: str = ""
    rollback_artifact: RollbackArtifact | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        """Return True only when the executor explicitly completed the request."""

        return self.decision == "executed"


@dataclass(slots=True, frozen=True)
class _PreparedSandboxExecutionRequest:
    """Normalized executor inputs shared by the apply and rollback helpers."""

    mutation_target: MutationTarget
    operation: str
    mode: str
    actor: str
    resolved_path: Path
    relative_path: str
    text_content: str | None
    rollback_artifact: RollbackArtifact | None
    metadata: dict[str, Any]


class SandboxExecutorService:
    """Execute narrow sandbox-local file mutations without shell, git, or package actions."""

    def __init__(
        self,
        *,
        sandbox_root: str | Path | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        configured_root = sandbox_root or workspace_root
        if configured_root is None:
            raise ValueError("SandboxExecutorService requires an explicit sandbox_root or workspace_root.")
        if sandbox_root is not None and workspace_root is not None:
            sandbox_path = Path(sandbox_root).resolve()
            workspace_path = Path(workspace_root).resolve()
            if sandbox_path != workspace_path:
                raise ValueError("sandbox_root and workspace_root must resolve to the same sandbox directory when both are supplied.")
        self.sandbox_root = Path(configured_root).resolve()

    def list_allowed_modes(self) -> tuple[str, ...]:
        """Return supported execution modes in deterministic order."""

        return tuple(sorted(_ALLOWED_MODES))

    def list_allowed_operations(self) -> tuple[str, ...]:
        """Return supported sandbox operations in deterministic order."""

        return tuple(sorted(_ALLOWED_OPERATIONS))

    def list_allowed_target_kinds(self) -> tuple[str, ...]:
        """Return allowed sandbox target kinds in deterministic order."""

        return tuple(sorted(_ALLOWED_TARGET_KINDS))

    def execute(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        """Execute one typed sandbox-local request or reject it fail closed."""

        prepared, rejected = self._prepare_request(request)
        if rejected is not None or prepared is None:
            return rejected or self._reject(
                mode="",
                operation="",
                mutation_target_id="",
                locator="",
                reason_code="sandbox_request_invalid",
                reason="The sandbox execution request could not be normalized safely.",
            )

        try:
            if prepared.mode == "apply":
                return self._execute_apply(prepared)
            return self._execute_rollback(prepared)
        except UnicodeError:
            return self._fail(
                mode=prepared.mode,
                operation=prepared.operation,
                mutation_target_id=prepared.mutation_target.mutation_target_id,
                locator=prepared.mutation_target.locator,
                resolved_locator=prepared.relative_path,
                reason_code="sandbox_text_encoding_error",
                reason="Sandbox text execution requires UTF-8 readable and writable text artifacts only.",
            )
        except OSError as error:
            return self._fail(
                mode=prepared.mode,
                operation=prepared.operation,
                mutation_target_id=prepared.mutation_target.mutation_target_id,
                locator=prepared.mutation_target.locator,
                resolved_locator=prepared.relative_path,
                reason_code="sandbox_io_error",
                reason="The sandbox-local file operation failed due to an operating-system error.",
                metadata={
                    "error_type": type(error).__name__,
                },
            )

    def _prepare_request(
        self,
        request: SandboxExecutionRequest,
    ) -> tuple[_PreparedSandboxExecutionRequest | None, SandboxExecutionResult | None]:
        """Normalize one sandbox request or return one typed rejection."""

        target = request.mutation_target
        if not isinstance(target, MutationTarget):
            return None, self._reject(
                mode=_normalized_key(request.mode),
                operation=_normalized_key(request.operation),
                mutation_target_id="",
                locator="",
                reason_code="invalid_mutation_target",
                reason="Sandbox execution requires one typed MutationTarget.",
            )

        mode = _normalized_key(request.mode)
        if mode not in _ALLOWED_MODES:
            return None, self._reject(
                mode=mode,
                operation=_normalized_key(request.operation),
                mutation_target_id=target.mutation_target_id,
                locator=target.locator,
                reason_code="invalid_mode",
                reason="Sandbox execution supports only apply or rollback modes.",
            )

        operation = _normalized_key(request.operation)
        if operation not in _ALLOWED_OPERATIONS:
            return None, self._reject(
                mode=mode,
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                locator=target.locator,
                reason_code="invalid_operation",
                reason="Sandbox execution allows only create_directory or write_text operations.",
            )

        executor_category = _normalized_key(target.executor_category)
        if executor_category not in _ALLOWED_EXECUTOR_CATEGORIES:
            return None, self._reject(
                mode=mode,
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                locator=target.locator,
                reason_code="invalid_executor_category",
                reason="Sandbox execution accepts only mutation targets already classified for sandbox execution.",
            )

        target_kind = _normalized_key(target.target_kind)
        if target_kind not in _ALLOWED_TARGET_KINDS:
            return None, self._reject(
                mode=mode,
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                locator=target.locator,
                reason_code="invalid_target_kind",
                reason="Sandbox execution allows only sandbox_runtime or sandbox_workspace targets.",
            )

        resolved_path, relative_path = self._resolve_path(target.locator)
        if resolved_path is None or not relative_path:
            return None, self._reject(
                mode=mode,
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                locator=target.locator,
                reason_code="path_outside_sandbox",
                reason="Sandbox execution must stay strictly inside the configured sandbox directory.",
            )

        blocked_segment = self._blocked_path_segment(relative_path)
        if blocked_segment is not None:
            return None, self._reject(
                mode=mode,
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                locator=target.locator,
                resolved_locator=relative_path,
                reason_code="protected_sandbox_path",
                reason="Sandbox execution cannot target git, package-cache, or virtual-environment paths.",
                metadata={"blocked_segment": blocked_segment},
            )

        text_content = request.text_content
        if operation == "write_text":
            if mode == "apply" and not isinstance(text_content, str):
                return None, self._reject(
                    mode=mode,
                    operation=operation,
                    mutation_target_id=target.mutation_target_id,
                    locator=target.locator,
                    resolved_locator=relative_path,
                    reason_code="text_content_required",
                    reason="The write_text sandbox operation requires explicit text content in apply mode.",
                )
            if not self._is_allowed_text_artifact(relative_path):
                return None, self._reject(
                    mode=mode,
                    operation=operation,
                    mutation_target_id=target.mutation_target_id,
                    locator=target.locator,
                    resolved_locator=relative_path,
                    reason_code="file_type_not_allowed",
                    reason="Sandbox execution can write only narrow text or data artifacts, not source or executable files.",
                )

        rollback_artifact = request.rollback_artifact
        if mode == "rollback":
            rollback_rejection = self._validate_rollback_artifact(
                rollback_artifact=rollback_artifact,
                mutation_target=target,
                operation=operation,
                relative_path=relative_path,
            )
            if rollback_rejection is not None:
                return None, rollback_rejection

        return (
            _PreparedSandboxExecutionRequest(
                mutation_target=target,
                operation=operation,
                mode=mode,
                actor=compact_text(request.actor or "narvis", max_chars=120) or "narvis",
                resolved_path=resolved_path,
                relative_path=relative_path,
                text_content=text_content if isinstance(text_content, str) else None,
                rollback_artifact=rollback_artifact,
                metadata=sanitize_durable_mapping(request.metadata),
            ),
            None,
        )

    def _execute_apply(self, request: _PreparedSandboxExecutionRequest) -> SandboxExecutionResult:
        """Execute one apply-mode sandbox request."""

        if request.operation == "create_directory":
            return self._apply_create_directory(request)
        return self._apply_write_text(request)

    def _execute_rollback(self, request: _PreparedSandboxExecutionRequest) -> SandboxExecutionResult:
        """Execute one rollback-mode sandbox request."""

        if request.operation == "create_directory":
            return self._rollback_create_directory(request)
        return self._rollback_write_text(request)

    def _apply_create_directory(self, request: _PreparedSandboxExecutionRequest) -> SandboxExecutionResult:
        """Create one sandbox-local directory and capture a rollback snapshot."""

        existed_before = request.resolved_path.exists()
        if existed_before and not request.resolved_path.is_dir():
            return self._reject(
                mode=request.mode,
                operation=request.operation,
                mutation_target_id=request.mutation_target.mutation_target_id,
                locator=request.mutation_target.locator,
                resolved_locator=request.relative_path,
                reason_code="target_type_not_allowed",
                reason="Sandbox directory creation cannot replace an existing non-directory target.",
            )

        request.resolved_path.mkdir(parents=True, exist_ok=True)
        rollback_artifact = self._build_directory_artifact(
            request=request,
            existed_before=existed_before,
        )
        return self._executed(
            mode=request.mode,
            operation=request.operation,
            mutation_target_id=request.mutation_target.mutation_target_id,
            locator=request.mutation_target.locator,
            resolved_locator=request.relative_path,
            rollback_artifact=rollback_artifact,
            reason_code="sandbox_directory_ready",
            reason="The sandbox executor created or confirmed the requested directory inside the configured sandbox root.",
            metadata={
                "changed": not existed_before,
                "target_kind": request.mutation_target.target_kind,
            },
        )

    def _apply_write_text(self, request: _PreparedSandboxExecutionRequest) -> SandboxExecutionResult:
        """Write one sandbox-local text artifact and capture a rollback snapshot."""

        if request.resolved_path.exists() and not request.resolved_path.is_file():
            return self._reject(
                mode=request.mode,
                operation=request.operation,
                mutation_target_id=request.mutation_target.mutation_target_id,
                locator=request.mutation_target.locator,
                resolved_locator=request.relative_path,
                reason_code="target_type_not_allowed",
                reason="Sandbox text writes can target only regular files inside the configured sandbox root.",
            )

        existed_before = request.resolved_path.is_file()
        previous_content = request.resolved_path.read_text(encoding="utf-8") if existed_before else ""
        request.resolved_path.parent.mkdir(parents=True, exist_ok=True)
        request.resolved_path.write_text(request.text_content or "", encoding="utf-8")
        rollback_artifact = self._build_write_text_artifact(
            request=request,
            existed_before=existed_before,
            previous_content=previous_content,
        )
        return self._executed(
            mode=request.mode,
            operation=request.operation,
            mutation_target_id=request.mutation_target.mutation_target_id,
            locator=request.mutation_target.locator,
            resolved_locator=request.relative_path,
            rollback_artifact=rollback_artifact,
            reason_code="sandbox_text_written",
            reason="The sandbox executor wrote one text artifact inside the configured sandbox root.",
            metadata={
                "changed": (not existed_before) or previous_content != (request.text_content or ""),
                "target_kind": request.mutation_target.target_kind,
            },
        )

    def _rollback_create_directory(self, request: _PreparedSandboxExecutionRequest) -> SandboxExecutionResult:
        """Roll back one directory creation using the exact returned rollback artifact."""

        artifact = request.rollback_artifact
        if artifact is None:
            return self._reject(
                mode=request.mode,
                operation=request.operation,
                mutation_target_id=request.mutation_target.mutation_target_id,
                locator=request.mutation_target.locator,
                resolved_locator=request.relative_path,
                reason_code="rollback_artifact_required",
                reason="Sandbox rollback requires the exact rollback artifact returned by the apply operation.",
            )

        existed_before = bool(artifact.metadata.get("existed_before", False))
        if not existed_before and request.resolved_path.exists():
            if not request.resolved_path.is_dir():
                return self._reject(
                    mode=request.mode,
                    operation=request.operation,
                    mutation_target_id=request.mutation_target.mutation_target_id,
                    locator=request.mutation_target.locator,
                    resolved_locator=request.relative_path,
                    reason_code="target_type_not_allowed",
                    reason="Sandbox directory rollback cannot remove a non-directory target.",
                )
            if any(request.resolved_path.iterdir()):
                return self._reject(
                    mode=request.mode,
                    operation=request.operation,
                    mutation_target_id=request.mutation_target.mutation_target_id,
                    locator=request.mutation_target.locator,
                    resolved_locator=request.relative_path,
                    reason_code="directory_not_empty",
                    reason="Sandbox directory rollback stops fail closed when the created directory is no longer empty.",
                )
            request.resolved_path.rmdir()

        return self._executed(
            mode=request.mode,
            operation=request.operation,
            mutation_target_id=request.mutation_target.mutation_target_id,
            locator=request.mutation_target.locator,
            resolved_locator=request.relative_path,
            rollback_artifact=artifact,
            reason_code="sandbox_directory_rolled_back",
            reason="The sandbox executor rolled back the directory mutation using the exact recorded rollback artifact.",
            metadata={
                "changed": not existed_before,
                "target_kind": request.mutation_target.target_kind,
            },
        )

    def _rollback_write_text(self, request: _PreparedSandboxExecutionRequest) -> SandboxExecutionResult:
        """Roll back one text write using the exact returned rollback artifact."""

        artifact = request.rollback_artifact
        if artifact is None:
            return self._reject(
                mode=request.mode,
                operation=request.operation,
                mutation_target_id=request.mutation_target.mutation_target_id,
                locator=request.mutation_target.locator,
                resolved_locator=request.relative_path,
                reason_code="rollback_artifact_required",
                reason="Sandbox rollback requires the exact rollback artifact returned by the apply operation.",
            )

        if request.resolved_path.exists() and not request.resolved_path.is_file():
            return self._reject(
                mode=request.mode,
                operation=request.operation,
                mutation_target_id=request.mutation_target.mutation_target_id,
                locator=request.mutation_target.locator,
                resolved_locator=request.relative_path,
                reason_code="target_type_not_allowed",
                reason="Sandbox text rollback can restore only regular files inside the configured sandbox root.",
            )

        existed_before = bool(artifact.metadata.get("existed_before", False))
        if existed_before:
            previous_content = str(artifact.metadata.get("previous_content", ""))
            request.resolved_path.parent.mkdir(parents=True, exist_ok=True)
            request.resolved_path.write_text(previous_content, encoding="utf-8")
        elif request.resolved_path.exists():
            request.resolved_path.unlink()

        return self._executed(
            mode=request.mode,
            operation=request.operation,
            mutation_target_id=request.mutation_target.mutation_target_id,
            locator=request.mutation_target.locator,
            resolved_locator=request.relative_path,
            rollback_artifact=artifact,
            reason_code="sandbox_text_rolled_back",
            reason="The sandbox executor rolled back the text artifact mutation using the exact recorded rollback artifact.",
            metadata={
                "changed": True,
                "target_kind": request.mutation_target.target_kind,
            },
        )

    def _build_directory_artifact(
        self,
        *,
        request: _PreparedSandboxExecutionRequest,
        existed_before: bool,
    ) -> RollbackArtifact:
        """Build one rollback artifact for a directory mutation."""

        metadata = {
            "operation": request.operation,
            "mode": request.mode,
            "relative_path": request.relative_path,
            "target_kind": request.mutation_target.target_kind,
            "existed_before": existed_before,
        }
        fingerprint = stable_id(
            "sandbox_directory_artifact_fingerprint",
            {
                "mutation_target_id": request.mutation_target.mutation_target_id,
                "relative_path": request.relative_path,
                "operation": request.operation,
                "mode": request.mode,
                "existed_before": existed_before,
            },
        )
        return RollbackArtifact(
            rollback_artifact_id=stable_id("sandbox_directory_artifact", fingerprint),
            mutation_run_id=compact_text(str(request.metadata.get("mutation_run_id", "")), max_chars=120),
            mutation_step_run_id=compact_text(str(request.metadata.get("mutation_step_run_id", "")), max_chars=120),
            mutation_target_id=request.mutation_target.mutation_target_id,
            artifact_kind=_DIRECTORY_ARTIFACT_KIND,
            artifact_locator=request.relative_path,
            artifact_fingerprint=fingerprint,
            metadata=metadata,
        )

    def _build_write_text_artifact(
        self,
        *,
        request: _PreparedSandboxExecutionRequest,
        existed_before: bool,
        previous_content: str,
    ) -> RollbackArtifact:
        """Build one rollback artifact for a text-artifact mutation."""

        previous_content_sha1 = hashlib.sha1(previous_content.encode("utf-8")).hexdigest() if existed_before else ""
        # Keep the raw prior content in the rollback artifact so rollback can restore exact text later.
        metadata = {
            "operation": request.operation,
            "mode": request.mode,
            "relative_path": request.relative_path,
            "target_kind": request.mutation_target.target_kind,
            "existed_before": existed_before,
            "previous_content": previous_content,
            "previous_content_sha1": previous_content_sha1,
        }
        fingerprint = stable_id(
            "sandbox_text_artifact_fingerprint",
            {
                "mutation_target_id": request.mutation_target.mutation_target_id,
                "relative_path": request.relative_path,
                "operation": request.operation,
                "mode": request.mode,
                "existed_before": existed_before,
                "previous_content_sha1": previous_content_sha1,
            },
        )
        return RollbackArtifact(
            rollback_artifact_id=stable_id("sandbox_text_artifact", fingerprint),
            mutation_run_id=compact_text(str(request.metadata.get("mutation_run_id", "")), max_chars=120),
            mutation_step_run_id=compact_text(str(request.metadata.get("mutation_step_run_id", "")), max_chars=120),
            mutation_target_id=request.mutation_target.mutation_target_id,
            artifact_kind=_WRITE_TEXT_ARTIFACT_KIND,
            artifact_locator=request.relative_path,
            artifact_fingerprint=fingerprint,
            metadata=metadata,
        )

    def _validate_rollback_artifact(
        self,
        *,
        rollback_artifact: RollbackArtifact | None,
        mutation_target: MutationTarget,
        operation: str,
        relative_path: str,
    ) -> SandboxExecutionResult | None:
        """Return one typed rejection when the rollback artifact does not match exactly."""

        if rollback_artifact is None:
            return self._reject(
                mode="rollback",
                operation=operation,
                mutation_target_id=mutation_target.mutation_target_id,
                locator=mutation_target.locator,
                resolved_locator=relative_path,
                reason_code="rollback_artifact_required",
                reason="Sandbox rollback requires the exact rollback artifact returned by the apply operation.",
            )
        if not isinstance(rollback_artifact, RollbackArtifact):
            return self._reject(
                mode="rollback",
                operation=operation,
                mutation_target_id=mutation_target.mutation_target_id,
                locator=mutation_target.locator,
                resolved_locator=relative_path,
                reason_code="rollback_artifact_invalid",
                reason="Sandbox rollback requires one typed RollbackArtifact.",
            )

        expected_artifact_kind = _DIRECTORY_ARTIFACT_KIND if operation == "create_directory" else _WRITE_TEXT_ARTIFACT_KIND
        if _normalized_key(rollback_artifact.artifact_kind) != expected_artifact_kind:
            return self._reject(
                mode="rollback",
                operation=operation,
                mutation_target_id=mutation_target.mutation_target_id,
                locator=mutation_target.locator,
                resolved_locator=relative_path,
                reason_code="rollback_artifact_mismatch",
                reason="The rollback artifact kind does not match the requested sandbox operation.",
            )
        if compact_text(rollback_artifact.mutation_target_id, max_chars=120) != compact_text(
            mutation_target.mutation_target_id,
            max_chars=120,
        ):
            return self._reject(
                mode="rollback",
                operation=operation,
                mutation_target_id=mutation_target.mutation_target_id,
                locator=mutation_target.locator,
                resolved_locator=relative_path,
                reason_code="rollback_artifact_mismatch",
                reason="The rollback artifact is not bound to the exact sandbox mutation target.",
            )
        if compact_text(rollback_artifact.artifact_locator, max_chars=320) != compact_text(relative_path, max_chars=320):
            return self._reject(
                mode="rollback",
                operation=operation,
                mutation_target_id=mutation_target.mutation_target_id,
                locator=mutation_target.locator,
                resolved_locator=relative_path,
                reason_code="rollback_artifact_mismatch",
                reason="The rollback artifact is not bound to the exact sandbox path.",
            )
        if _normalized_key(str(rollback_artifact.metadata.get("operation", ""))) != operation:
            return self._reject(
                mode="rollback",
                operation=operation,
                mutation_target_id=mutation_target.mutation_target_id,
                locator=mutation_target.locator,
                resolved_locator=relative_path,
                reason_code="rollback_artifact_mismatch",
                reason="The rollback artifact operation binding no longer matches the requested sandbox rollback.",
            )
        return None

    def _resolve_path(self, locator: str) -> tuple[Path | None, str]:
        """Resolve one caller-supplied locator under the configured sandbox root only."""

        normalized_locator = compact_text(locator, max_chars=320).replace("\\", "/")
        while normalized_locator.startswith("./"):
            normalized_locator = normalized_locator[2:]
        if not normalized_locator:
            return None, ""

        try:
            raw_path = Path(normalized_locator)
            candidate = raw_path if raw_path.is_absolute() else self.sandbox_root / raw_path
            resolved = candidate.resolve()
            relative = resolved.relative_to(self.sandbox_root)
        except Exception:
            return None, ""
        relative_path = relative.as_posix()
        if not relative_path or relative_path == ".":
            return None, ""
        return resolved, relative_path

    def _blocked_path_segment(self, relative_path: str) -> str | None:
        """Return the first blocked path segment inside one normalized sandbox path."""

        for part in Path(relative_path).parts:
            lowered = compact_text(part, max_chars=120).lower()
            if lowered in _BLOCKED_PATH_SEGMENTS:
                return lowered
        return None

    def _is_allowed_text_artifact(self, relative_path: str) -> bool:
        """Return True only for narrow non-source text artifacts."""

        artifact_path = Path(relative_path)
        if artifact_path.name.startswith("."):
            return False
        return artifact_path.suffix.lower() in _ALLOWED_TEXT_FILE_EXTENSIONS

    def _executed(
        self,
        *,
        mode: str,
        operation: str,
        mutation_target_id: str,
        locator: str,
        resolved_locator: str,
        reason_code: str,
        reason: str,
        rollback_artifact: RollbackArtifact | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SandboxExecutionResult:
        """Build one successful execution result."""

        return SandboxExecutionResult(
            decision="executed",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            mode=compact_text(mode, max_chars=80),
            operation=compact_text(operation, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            locator=compact_text(locator, max_chars=320),
            resolved_locator=compact_text(resolved_locator, max_chars=320),
            rollback_artifact=rollback_artifact,
            metadata=sanitize_durable_mapping(
                {
                    **(metadata or {}),
                    "sandbox_root": self.sandbox_root.as_posix(),
                }
            ),
        )

    def _reject(
        self,
        *,
        mode: str,
        operation: str,
        mutation_target_id: str,
        locator: str,
        reason_code: str,
        reason: str,
        resolved_locator: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SandboxExecutionResult:
        """Build one typed rejection result."""

        return SandboxExecutionResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            mode=compact_text(mode, max_chars=80),
            operation=compact_text(operation, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            locator=compact_text(locator, max_chars=320),
            resolved_locator=compact_text(resolved_locator, max_chars=320),
            metadata=sanitize_durable_mapping(metadata or {}),
        )

    def _fail(
        self,
        *,
        mode: str,
        operation: str,
        mutation_target_id: str,
        locator: str,
        reason_code: str,
        reason: str,
        resolved_locator: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SandboxExecutionResult:
        """Build one typed execution failure result."""

        return SandboxExecutionResult(
            decision="failed",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            mode=compact_text(mode, max_chars=80),
            operation=compact_text(operation, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            locator=compact_text(locator, max_chars=320),
            resolved_locator=compact_text(resolved_locator, max_chars=320),
            metadata=sanitize_durable_mapping(metadata or {}),
        )


__all__ = [
    "SandboxExecutionRequest",
    "SandboxExecutionResult",
    "SandboxExecutorService",
]
