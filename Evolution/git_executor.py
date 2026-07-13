"""Typed placeholder local-Git executor for Phase 8 Milestone 5."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .models import MutationTarget, RollbackArtifact, compact_text, sanitize_durable_mapping, stable_id

GitOperation = Literal["stage", "unstage", "commit", "rollback_commit"]
GitTransport = Literal["local"]

_ALLOWED_OPERATIONS = frozenset({"stage", "unstage", "commit", "rollback_commit"})
_PROHIBITED_OPERATIONS = frozenset(
    {
        "push",
        "pull",
        "fetch",
        "clone",
        "merge",
        "rebase",
        "force",
        "force_push",
        "force_pull",
        "force_commit",
    }
)
_ALLOWED_TARGET_KINDS = frozenset({"local_repository"})
_ROLLBACK_OPERATION_BY_OPERATION = {
    "stage": "unstage",
    "unstage": "stage",
    "commit": "rollback_commit",
    "rollback_commit": "commit",
}
_REMOTE_REPOSITORY_MARKERS = (
    "://",
    "git@",
    "git+",
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "ssh:",
    "http:",
)
_NETWORK_METADATA_KEYS = frozenset({"endpoint", "network", "remote", "remote_url", "repository_url", "transport", "url"})
_ROLLBACK_ARTIFACT_KIND = "local_git_rollback_plan"
_LOCAL_REPOSITORY_IDENTIFIER = "local_repository"


def _normalized_key(value: str) -> str:
    """Normalize one executor key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


@dataclass(slots=True, frozen=True)
class GitExecutionRequest:
    """One typed local-Git mutation request for placeholder-only processing."""

    mutation_target: MutationTarget
    operation: GitOperation
    transport: GitTransport = "local"
    force: bool = False
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class GitExecutionResult:
    """One typed Git execution result that never represents a real Git mutation."""

    decision: str
    reason_code: str
    reason: str
    operation: str
    mutation_target_id: str
    repository_identifier: str = ""
    repository_root: str = ""
    transport: str = ""
    rollback_artifact: RollbackArtifact | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        """Return True when the Git operation was accepted for simulated execution."""

        return self.decision == "simulated"


@dataclass(slots=True, frozen=True)
class _PreparedGitExecutionRequest:
    """Normalized local-Git request fields shared by placeholder execution helpers."""

    mutation_target: MutationTarget
    operation: str
    transport: str
    actor: str
    repository_root: Path
    metadata: dict[str, Any]


class GitExecutorService:
    """Validate one explicit local repository target and return safe placeholder plans only."""

    def __init__(self, *, repository_root: str | Path | None = None) -> None:
        # The configured root is the explicit local approval boundary; this executor never calls Git to discover it.
        self.repository_root = Path(repository_root or Path.cwd()).resolve()

    def list_allowed_operations(self) -> tuple[str, ...]:
        """Return supported Git operations in deterministic order."""

        return tuple(sorted(_ALLOWED_OPERATIONS))

    def list_allowed_target_kinds(self) -> tuple[str, ...]:
        """Return allowed Git mutation target kinds in deterministic order."""

        return tuple(sorted(_ALLOWED_TARGET_KINDS))

    def execute(self, request: GitExecutionRequest) -> GitExecutionResult:
        """Validate one Git request and simulate it without invoking Git or changing repository state."""

        prepared, rejected = self._prepare_request(request)
        if rejected is not None or prepared is None:
            return rejected or self._reject(
                operation="",
                mutation_target_id="",
                reason_code="git_request_invalid",
                reason="The Git execution request could not be normalized safely.",
            )

        rollback_artifact = self._build_rollback_artifact(prepared)
        return GitExecutionResult(
            decision="simulated",
            reason_code="git_operation_simulated",
            reason="The approved local Git request was validated and simulated without invoking Git, network, shell, package, or filesystem mutation tooling.",
            operation=prepared.operation,
            mutation_target_id=prepared.mutation_target.mutation_target_id,
            repository_identifier=_LOCAL_REPOSITORY_IDENTIFIER,
            repository_root=str(prepared.repository_root),
            transport=prepared.transport,
            rollback_artifact=rollback_artifact,
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "git_executed": False,
                    "index_mutated": False,
                    "commit_created": False,
                    "network_invoked": False,
                    "shell_invoked": False,
                    "package_manager_invoked": False,
                    "executor_category": prepared.mutation_target.executor_category,
                    "target_kind": prepared.mutation_target.target_kind,
                    "risk_classification": prepared.mutation_target.risk_classification,
                }
            ),
        )

    def _prepare_request(
        self,
        request: GitExecutionRequest,
    ) -> tuple[_PreparedGitExecutionRequest | None, GitExecutionResult | None]:
        """Normalize one local-Git request or return one typed rejection."""

        target = request.mutation_target
        if not isinstance(target, MutationTarget):
            return None, self._reject(
                operation=_normalized_key(request.operation),
                mutation_target_id="",
                reason_code="invalid_mutation_target",
                reason="Git execution requires one typed MutationTarget.",
            )

        operation = _normalized_key(request.operation)
        if operation in _PROHIBITED_OPERATIONS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                reason_code="git_operation_not_allowed",
                reason="Remote, history-rewriting, and force Git operations are not allowed by this local-only executor.",
            )
        if operation not in _ALLOWED_OPERATIONS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                reason_code="invalid_operation",
                reason="Git execution supports only stage, unstage, commit, or rollback_commit simulations.",
            )

        mutation_target_id = compact_text(target.mutation_target_id, max_chars=120)
        if not mutation_target_id:
            return None, self._reject(
                operation=operation,
                mutation_target_id="",
                reason_code="mutation_target_id_required",
                reason="Git execution requires a non-empty mutation target identifier.",
            )

        if _normalized_key(target.executor_category) != "git_operation":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_executor_category",
                reason="Git execution accepts only mutation targets classified for Git operations.",
            )

        if _normalized_key(target.target_kind) not in _ALLOWED_TARGET_KINDS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_target_kind",
                reason="Git execution allows only the approved local_repository target kind.",
            )

        if _normalized_key(target.risk_classification) != "high":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="git_risk_classification_required",
                reason="Git mutation simulation requires the high risk classification used by the existing evolution policy.",
            )

        if _normalized_key(target.action_kind) != "git_operation":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="action_kind_mismatch",
                reason="Git execution requires the typed git_operation action kind.",
            )

        transport = _normalized_key(request.transport)
        if transport != "local":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                transport=transport,
                reason_code="network_operation_not_allowed",
                reason="Git execution accepts only an explicit local transport and never performs network operations.",
            )
        if bool(request.force) or self._has_force_metadata(request.metadata):
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                transport=transport,
                reason_code="force_operation_not_allowed",
                reason="Git execution rejects all force operations, including force flags in request metadata.",
            )
        if self._has_network_metadata(request.metadata):
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                transport=transport,
                reason_code="network_operation_not_allowed",
                reason="Git execution rejects remote, endpoint, URL, transport, and network metadata.",
            )

        repository_decision = self._validate_repository_locator(target.locator)
        if repository_decision is not None:
            reason_code, reason = repository_decision
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                transport=transport,
                reason_code=reason_code,
                reason=reason,
            )

        return (
            _PreparedGitExecutionRequest(
                mutation_target=target,
                operation=operation,
                transport=transport,
                actor=compact_text(request.actor or "narvis", max_chars=120) or "narvis",
                repository_root=self.repository_root,
                metadata=sanitize_durable_mapping(request.metadata),
            ),
            None,
        )

    def _validate_repository_locator(self, locator: str) -> tuple[str, str] | None:
        """Return one typed rejection when a locator is not the approved local repository root."""

        raw_locator = compact_text(locator, max_chars=320).strip()
        normalized_locator = raw_locator.replace("\\", "/").lower()
        if self._looks_like_remote_repository(normalized_locator):
            return (
                "remote_repository_not_allowed",
                "Git execution rejects remote repository URLs and Git-style remote locators.",
            )
        if any(segment.strip() == ".." for segment in normalized_locator.split("/")):
            return (
                "directory_traversal",
                "Git execution rejects every directory-traversal path before local repository resolution.",
            )
        if normalized_locator == _LOCAL_REPOSITORY_IDENTIFIER:
            return None
        if normalized_locator == ".git" or normalized_locator.startswith(".git/"):
            return (
                "git_metadata_target_not_allowed",
                "Git execution may target only the approved repository root, never .git metadata paths.",
            )
        if not raw_locator:
            return (
                "repository_target_not_approved",
                "Git execution requires the explicit local_repository identifier or configured repository root path.",
            )

        try:
            candidate = Path(raw_locator)
            if not candidate.is_absolute():
                candidate = self.repository_root / candidate
            resolved_path = candidate.resolve()
        except (OSError, ValueError):
            return (
                "repository_target_not_approved",
                "Git execution could not resolve the requested local repository target safely.",
            )
        if resolved_path != self.repository_root:
            return (
                "repository_target_not_approved",
                "Git execution accepts only the exact configured local repository root.",
            )
        return None

    def _looks_like_remote_repository(self, normalized_locator: str) -> bool:
        """Return True when a locator could identify an external Git repository or remote."""

        return any(marker in normalized_locator for marker in _REMOTE_REPOSITORY_MARKERS)

    def _has_network_metadata(self, metadata: dict[str, Any]) -> bool:
        """Return True when request metadata attempts to introduce a network operation channel."""

        return any(_normalized_key(key) in _NETWORK_METADATA_KEYS and bool(value) for key, value in metadata.items())

    def _has_force_metadata(self, metadata: dict[str, Any]) -> bool:
        """Return True when request metadata attempts to introduce a force operation flag."""

        return any(_normalized_key(key) in {"force", "force_with_lease"} and bool(value) for key, value in metadata.items())

    def _build_rollback_artifact(self, request: _PreparedGitExecutionRequest) -> RollbackArtifact:
        """Create rollback metadata without claiming that Git state was observed or changed."""

        rollback_operation = _ROLLBACK_OPERATION_BY_OPERATION[request.operation]
        metadata = sanitize_durable_mapping(
            {
                "operation": request.operation,
                "repository_identifier": _LOCAL_REPOSITORY_IDENTIFIER,
                "repository_root": str(request.repository_root),
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
            "local_git_rollback_plan_fingerprint",
            {
                "mutation_target_id": request.mutation_target.mutation_target_id,
                "operation": request.operation,
                "repository_root": str(request.repository_root),
                "rollback_operation": rollback_operation,
            },
        )
        return RollbackArtifact(
            rollback_artifact_id=stable_id("local_git_rollback_plan", fingerprint),
            mutation_run_id=compact_text(str(request.metadata.get("mutation_run_id", "")), max_chars=120),
            mutation_step_run_id=compact_text(str(request.metadata.get("mutation_step_run_id", "")), max_chars=120),
            mutation_target_id=request.mutation_target.mutation_target_id,
            artifact_kind=_ROLLBACK_ARTIFACT_KIND,
            artifact_locator=_LOCAL_REPOSITORY_IDENTIFIER,
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
        transport: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GitExecutionResult:
        """Build one typed fail-closed Git execution rejection."""

        return GitExecutionResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            operation=compact_text(operation, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            transport=compact_text(transport, max_chars=80),
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "git_executed": False,
                    "index_mutated": False,
                    "commit_created": False,
                    "network_invoked": False,
                    "shell_invoked": False,
                    "package_manager_invoked": False,
                    **(metadata or {}),
                }
            ),
        )


__all__ = [
    "GitExecutionRequest",
    "GitExecutionResult",
    "GitExecutorService",
    "GitOperation",
    "GitTransport",
]
