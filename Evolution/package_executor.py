"""Typed placeholder package executor for Phase 8 Milestone 2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .models import MutationTarget, RollbackArtifact, compact_text, sanitize_durable_mapping, stable_id

PackageOperation = Literal["install", "uninstall", "upgrade"]

_ALLOWED_OPERATIONS = frozenset({"install", "uninstall", "upgrade"})
_ALLOWED_TARGET_KINDS = frozenset({"dependency_spec", "package_spec"})
_ALLOWED_RISK_CLASSIFICATIONS = frozenset({"low", "medium", "high"})
_ALLOWED_ACTION_KINDS_BY_OPERATION = {
    "install": frozenset({"package_install"}),
    "uninstall": frozenset({"package_remove", "package_uninstall"}),
    "upgrade": frozenset({"package_install", "package_upgrade"}),
}
_ROLLBACK_OPERATION_BY_OPERATION = {
    "install": "uninstall",
    "uninstall": "install",
    "upgrade": "install",
}
_PACKAGE_NAME_TOKEN = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_VERSION_TOKEN = r"[A-Za-z0-9][A-Za-z0-9.*+!._-]*"
_SPECIFIER_TOKEN = rf"(?:===|==|!=|<=|>=|<|>|~=)\s*{_VERSION_TOKEN}"
_PACKAGE_SPECIFICATION_PATTERN = re.compile(
    rf"^(?P<name>{_PACKAGE_NAME_TOKEN})\s*"
    rf"(?:\[(?P<extras>{_PACKAGE_NAME_TOKEN}(?:\s*,\s*{_PACKAGE_NAME_TOKEN})*)\])?\s*"
    rf"(?P<specifiers>{_SPECIFIER_TOKEN}(?:\s*,\s*{_SPECIFIER_TOKEN})*)?\s*$"
)
_BLOCKED_SPECIFICATION_CHARACTERS = frozenset({"\n", "\r", "@", "/", "\\", ";", "'", '"', "`", "$", "|", "&", "(", ")", "{", "}"})
_ROLLBACK_ARTIFACT_KIND = "package_rollback_plan"


def _normalized_key(value: str) -> str:
    """Normalize one executor key into a stable lowercase identifier."""

    return compact_text(str(value or ""), max_chars=120).strip().lower()


def _canonical_package_name(value: str) -> str:
    """Return the PEP 503-style canonical form of one package name."""

    return re.sub(r"[-_.]+", "-", value).lower()


@dataclass(slots=True, frozen=True)
class PackageExecutionRequest:
    """One typed package mutation request for placeholder-only processing."""

    mutation_target: MutationTarget
    operation: PackageOperation
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class PackageExecutionResult:
    """One typed package execution result that never represents a real package mutation."""

    decision: str
    reason_code: str
    reason: str
    operation: str
    mutation_target_id: str
    package_name: str = ""
    package_specification: str = ""
    rollback_artifact: RollbackArtifact | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        """Return True when the package operation was accepted for simulated execution."""

        return self.decision == "simulated"


@dataclass(slots=True, frozen=True)
class _PreparedPackageExecutionRequest:
    """Normalized package request fields shared by placeholder execution helpers."""

    mutation_target: MutationTarget
    operation: str
    actor: str
    package_name: str
    package_specification: str
    metadata: dict[str, Any]


class PackageExecutorService:
    """Validate typed package requests and return safe placeholder execution plans only."""

    def list_allowed_operations(self) -> tuple[str, ...]:
        """Return supported package operations in deterministic order."""

        return tuple(sorted(_ALLOWED_OPERATIONS))

    def list_allowed_target_kinds(self) -> tuple[str, ...]:
        """Return allowed package mutation target kinds in deterministic order."""

        return tuple(sorted(_ALLOWED_TARGET_KINDS))

    def execute(self, request: PackageExecutionRequest) -> PackageExecutionResult:
        """Validate one package request and simulate it without invoking a package manager."""

        prepared, rejected = self._prepare_request(request)
        if rejected is not None or prepared is None:
            return rejected or self._reject(
                operation="",
                mutation_target_id="",
                reason_code="package_request_invalid",
                reason="The package execution request could not be normalized safely.",
            )

        rollback_artifact = self._build_rollback_artifact(prepared)
        return PackageExecutionResult(
            decision="simulated",
            reason_code="package_operation_simulated",
            reason="The package request was validated and simulated without invoking a package manager.",
            operation=prepared.operation,
            mutation_target_id=prepared.mutation_target.mutation_target_id,
            package_name=prepared.package_name,
            package_specification=prepared.package_specification,
            rollback_artifact=rollback_artifact,
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "package_manager_invoked": False,
                    "executor_category": prepared.mutation_target.executor_category,
                    "target_kind": prepared.mutation_target.target_kind,
                    "risk_classification": prepared.mutation_target.risk_classification,
                    "rollback_requires_pre_execution_state": True,
                }
            ),
        )

    def _prepare_request(
        self,
        request: PackageExecutionRequest,
    ) -> tuple[_PreparedPackageExecutionRequest | None, PackageExecutionResult | None]:
        """Normalize one package request or return one typed rejection."""

        target = request.mutation_target
        if not isinstance(target, MutationTarget):
            return None, self._reject(
                operation=_normalized_key(request.operation),
                mutation_target_id="",
                reason_code="invalid_mutation_target",
                reason="Package execution requires one typed MutationTarget.",
            )

        operation = _normalized_key(request.operation)
        if operation not in _ALLOWED_OPERATIONS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=target.mutation_target_id,
                reason_code="invalid_operation",
                reason="Package execution supports only install, uninstall, or upgrade operations.",
            )

        mutation_target_id = compact_text(target.mutation_target_id, max_chars=120)
        if not mutation_target_id:
            return None, self._reject(
                operation=operation,
                mutation_target_id="",
                reason_code="mutation_target_id_required",
                reason="Package execution requires a non-empty mutation target identifier.",
            )

        if _normalized_key(target.executor_category) != "package_management":
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_executor_category",
                reason="Package execution accepts only mutation targets classified for package management.",
            )

        target_kind = _normalized_key(target.target_kind)
        if target_kind not in _ALLOWED_TARGET_KINDS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_target_kind",
                reason="Package execution allows only dependency_spec or package_spec targets.",
            )

        risk_classification = _normalized_key(target.risk_classification)
        if risk_classification not in _ALLOWED_RISK_CLASSIFICATIONS:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_risk_classification",
                reason="Package execution allows only low, medium, or high risk classifications.",
            )

        allowed_action_kinds = _ALLOWED_ACTION_KINDS_BY_OPERATION[operation]
        action_kind = _normalized_key(target.action_kind)
        if action_kind not in allowed_action_kinds:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="action_kind_mismatch",
                reason="The mutation target action kind does not match the requested package operation.",
                metadata={"allowed_action_kinds": tuple(sorted(allowed_action_kinds))},
            )

        parsed_specification = self._parse_package_specification(target.locator)
        if parsed_specification is None:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="invalid_package_specification",
                reason="Package execution requires a typed package name with optional bounded version specifiers only.",
            )
        package_name, package_specification, has_extras_or_specifiers = parsed_specification
        if operation in {"uninstall", "upgrade"} and has_extras_or_specifiers:
            return None, self._reject(
                operation=operation,
                mutation_target_id=mutation_target_id,
                reason_code="operation_requires_bare_package_name",
                reason="Uninstall and upgrade requests must name one exact package without extras or version specifiers.",
            )

        return (
            _PreparedPackageExecutionRequest(
                mutation_target=target,
                operation=operation,
                actor=compact_text(request.actor or "narvis", max_chars=120) or "narvis",
                package_name=package_name,
                package_specification=package_specification,
                metadata=sanitize_durable_mapping(request.metadata),
            ),
            None,
        )

    def _parse_package_specification(self, locator: str) -> tuple[str, str, bool] | None:
        """Return normalized package fields only for narrow, non-command package specifications."""

        specification = compact_text(locator, max_chars=240).strip()
        if not specification or any(character in specification for character in _BLOCKED_SPECIFICATION_CHARACTERS):
            return None
        match = _PACKAGE_SPECIFICATION_PATTERN.fullmatch(specification)
        if match is None:
            return None

        package_name = _canonical_package_name(match.group("name"))
        extras_text = match.group("extras") or ""
        extras = tuple(_canonical_package_name(value.strip()) for value in extras_text.split(",") if value.strip())
        specifiers = re.sub(r"\s+", "", match.group("specifiers") or "")
        normalized_specification = package_name
        if extras:
            normalized_specification = f"{normalized_specification}[{','.join(extras)}]"
        normalized_specification = f"{normalized_specification}{specifiers}"
        return package_name, normalized_specification, bool(extras or specifiers)

    def _build_rollback_artifact(self, request: _PreparedPackageExecutionRequest) -> RollbackArtifact:
        """Create rollback metadata without claiming that package state was observed or changed."""

        rollback_operation = _ROLLBACK_OPERATION_BY_OPERATION[request.operation]
        metadata = sanitize_durable_mapping(
            {
                "operation": request.operation,
                "package_name": request.package_name,
                "package_specification": request.package_specification,
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
            "package_rollback_plan_fingerprint",
            {
                "mutation_target_id": request.mutation_target.mutation_target_id,
                "operation": request.operation,
                "package_name": request.package_name,
                "package_specification": request.package_specification,
                "rollback_operation": rollback_operation,
            },
        )
        return RollbackArtifact(
            rollback_artifact_id=stable_id("package_rollback_plan", fingerprint),
            mutation_run_id=compact_text(str(request.metadata.get("mutation_run_id", "")), max_chars=120),
            mutation_step_run_id=compact_text(str(request.metadata.get("mutation_step_run_id", "")), max_chars=120),
            mutation_target_id=request.mutation_target.mutation_target_id,
            artifact_kind=_ROLLBACK_ARTIFACT_KIND,
            artifact_locator=request.package_specification,
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
        metadata: dict[str, Any] | None = None,
    ) -> PackageExecutionResult:
        """Build one typed fail-closed package execution rejection."""

        return PackageExecutionResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            operation=compact_text(operation, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "placeholder_only": True,
                    "real_mutation_performed": False,
                    "package_manager_invoked": False,
                    **(metadata or {}),
                }
            ),
        )


__all__ = [
    "PackageExecutionRequest",
    "PackageExecutionResult",
    "PackageExecutorService",
    "PackageOperation",
]
