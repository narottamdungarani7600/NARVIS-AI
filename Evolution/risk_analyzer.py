"""Standalone typed risk analysis for Phase 9 execution plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import MutationTarget, compact_text, sanitize_durable_mapping, stable_id
from .task_planner import ExecutionPlan, PlannedTask, TaskDependency


class RiskLevel(str, Enum):
    """The ordered risk levels emitted by the standalone analyzer."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}
_DECLARED_RISK_LEVELS = {
    "low": RiskLevel.LOW,
    "medium": RiskLevel.MEDIUM,
    "high": RiskLevel.HIGH,
}
_MEDIUM_TASK_PREFIXES = ("sandbox_task_planning", "package_task_planning", "plugin_task_planning")
_HIGH_TASK_PREFIXES = ("source_task_planning", "git_task_planning")
_CRITICAL_TASK_PREFIXES = ("remote_task_planning",)
_PROTECTED_PATHS = (
    "narvis.py",
    "core/",
    "ai/",
    "memory/",
    "dashboard/",
    "evolution/runtime.py",
    "evolution/models.py",
    "evolution/inventory.py",
    "docs/",
    "data/",
    ".git/",
)
_EXTERNAL_TARGET_MARKERS = ("://", "git@", "git+", "github.com", "gitlab.com", "bitbucket.org")


def _normalized_text(value: Any, *, max_chars: int) -> str:
    """Normalize one bounded text field without treating arbitrary values as instructions."""

    return compact_text(value if isinstance(value, str) else "", max_chars=max_chars).strip()


@dataclass(slots=True, frozen=True)
class RiskAnalysisRequest:
    """One standalone request to assess one typed execution plan and optional mutation targets."""

    execution_plan: ExecutionPlan
    mutation_targets: tuple[MutationTarget, ...] = ()
    request_id: str = ""
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RiskFactor:
    """One typed factor contributing to an execution-plan risk assessment."""

    factor_id: str
    factor_type: str
    risk_level: RiskLevel
    description: str
    task_ids: tuple[str, ...] = ()
    mutation_target_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RiskRecommendation:
    """One typed human-review recommendation derived from a risk assessment."""

    recommendation_id: str
    code: str
    risk_level: RiskLevel
    description: str
    requires_human_approval: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RiskAnalysisResult:
    """One typed, non-executing result for an execution-plan risk assessment."""

    decision: str
    reason_code: str
    reason: str
    risk_level: RiskLevel | None = None
    execution_plan_id: str = ""
    request_id: str = ""
    factors: tuple[RiskFactor, ...] = ()
    recommendations: tuple[RiskRecommendation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def analyzed(self) -> bool:
        """Return True only when one typed plan was assessed without execution."""

        return self.decision == "analyzed" and self.risk_level is not None


class RiskAnalyzerService:
    """Evaluate execution plans conservatively without mutation, approval, or runtime integration."""

    def list_risk_levels(self) -> tuple[RiskLevel, ...]:
        """Return supported risk levels in ascending deterministic order."""

        return tuple(_RISK_ORDER)

    def analyze(self, request: RiskAnalysisRequest) -> RiskAnalysisResult:
        """Assess one typed execution plan and return only typed risk analysis records."""

        if not isinstance(request, RiskAnalysisRequest):
            return self._reject(
                reason_code="invalid_risk_analysis_request",
                reason="Risk analysis requires one typed RiskAnalysisRequest.",
            )
        if not isinstance(request.execution_plan, ExecutionPlan):
            return self._reject(
                reason_code="invalid_execution_plan",
                reason="Risk analysis requires one typed ExecutionPlan.",
                request_id=_normalized_text(request.request_id, max_chars=120),
            )

        plan = request.execution_plan
        request_id = _normalized_text(request.request_id, max_chars=120) or stable_id(
            "risk_analysis_request",
            plan.execution_plan_id,
            plan.plan_fingerprint,
        )
        factors = [*self._plan_integrity_factors(plan), *self._task_factors(plan)]
        factors.extend(self._dependency_count_factors(plan, factors))
        factors.extend(self._mutation_target_factors(plan, request.mutation_targets))
        risk_level = self._highest_risk_level(factors)
        recommendations = self._recommendations(plan, risk_level, factors)
        return RiskAnalysisResult(
            decision="analyzed",
            reason_code="risk_analysis_completed",
            reason="The execution plan was assessed without executing tasks, mutations, or runtime services.",
            risk_level=risk_level,
            execution_plan_id=compact_text(plan.execution_plan_id, max_chars=120),
            request_id=request_id,
            factors=tuple(factors),
            recommendations=recommendations,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.risk_analysis",
                    "task_count": len(plan.tasks) if isinstance(plan.tasks, tuple) else 0,
                    "dependency_count": len(plan.dependencies) if isinstance(plan.dependencies, tuple) else 0,
                    "mutation_target_count": len(request.mutation_targets)
                    if isinstance(request.mutation_targets, tuple)
                    else 0,
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                    "request_metadata": request.metadata if isinstance(request.metadata, dict) else {},
                }
            ),
        )

    def _plan_integrity_factors(self, plan: ExecutionPlan) -> tuple[RiskFactor, ...]:
        """Return critical factors when the plan graph is malformed or internally inconsistent."""

        if not isinstance(plan.tasks, tuple) or not plan.tasks or not all(
            isinstance(task, PlannedTask) for task in plan.tasks
        ):
            return (
                self._factor(
                    plan,
                    factor_type="execution_plan_tasks_invalid",
                    risk_level=RiskLevel.CRITICAL,
                    description="The execution plan must contain a non-empty typed task tuple before any later review.",
                ),
            )
        if not isinstance(plan.dependencies, tuple) or not all(
            isinstance(dependency, TaskDependency) for dependency in plan.dependencies
        ):
            return (
                self._factor(
                    plan,
                    factor_type="execution_plan_dependencies_invalid",
                    risk_level=RiskLevel.CRITICAL,
                    description="The execution plan dependencies must be a typed tuple before any later review.",
                ),
            )

        task_ids = tuple(task.task_id for task in plan.tasks)
        factors: list[RiskFactor] = []
        if not all(_normalized_text(task_id, max_chars=120) for task_id in task_ids) or len(set(task_ids)) != len(task_ids):
            factors.append(
                self._factor(
                    plan,
                    factor_type="execution_plan_task_ids_invalid",
                    risk_level=RiskLevel.CRITICAL,
                    description="Task identifiers must be non-empty and unique for a reviewable execution plan.",
                    task_ids=task_ids,
                )
            )
        expected_order = tuple(range(1, len(plan.tasks) + 1))
        if tuple(task.estimated_execution_order for task in plan.tasks) != expected_order:
            factors.append(
                self._factor(
                    plan,
                    factor_type="execution_order_invalid",
                    risk_level=RiskLevel.CRITICAL,
                    description="Task execution-order estimates must be an ordered contiguous sequence.",
                    task_ids=task_ids,
                )
            )
        if plan.estimated_execution_order != task_ids:
            factors.append(
                self._factor(
                    plan,
                    factor_type="execution_order_mismatch",
                    risk_level=RiskLevel.CRITICAL,
                    description="The plan execution order must exactly match the typed task sequence.",
                    task_ids=task_ids,
                )
            )

        expected_edges = {
            (task.task_id, prerequisite_task_id)
            for task in plan.tasks
            for prerequisite_task_id in task.dependency_task_ids
        }
        declared_edges = {
            (dependency.dependent_task_id, dependency.prerequisite_task_id)
            for dependency in plan.dependencies
        }
        known_task_ids = set(task_ids)
        if (
            any(
                dependent_task_id not in known_task_ids
                or prerequisite_task_id not in known_task_ids
                or dependent_task_id == prerequisite_task_id
                for dependent_task_id, prerequisite_task_id in declared_edges
            )
            or expected_edges != declared_edges
        ):
            factors.append(
                self._factor(
                    plan,
                    factor_type="task_dependency_binding_invalid",
                    risk_level=RiskLevel.CRITICAL,
                    description="Task dependencies must reference known distinct tasks and match each task binding exactly.",
                    task_ids=task_ids,
                )
            )
        elif self._has_dependency_cycle(task_ids, declared_edges):
            factors.append(
                self._factor(
                    plan,
                    factor_type="task_dependency_cycle",
                    risk_level=RiskLevel.CRITICAL,
                    description="Cyclic task dependencies are not reviewable and remain blocked by the risk analyzer.",
                    task_ids=task_ids,
                )
            )
        return tuple(factors)

    def _task_factors(self, plan: ExecutionPlan) -> tuple[RiskFactor, ...]:
        """Return risk factors for typed task categories and declared task risk levels."""

        if not isinstance(plan.tasks, tuple) or not all(isinstance(task, PlannedTask) for task in plan.tasks):
            return ()

        factors: list[RiskFactor] = []
        for task in plan.tasks:
            task_kind = _normalized_text(task.task_kind, max_chars=120).lower()
            if task_kind.startswith(_CRITICAL_TASK_PREFIXES):
                factors.append(
                    self._factor(
                        plan,
                        factor_type="remote_task_type",
                        risk_level=RiskLevel.CRITICAL,
                        description="Remote or multi-device task planning requires a critical risk classification and separate approval-bound handling.",
                        task_ids=(task.task_id,),
                    )
                )
            elif task_kind.startswith(_HIGH_TASK_PREFIXES):
                factors.append(
                    self._factor(
                        plan,
                        factor_type="high_impact_task_type",
                        risk_level=RiskLevel.HIGH,
                        description="Source-code or local Git task planning is high impact and requires explicit human review.",
                        task_ids=(task.task_id,),
                    )
                )
            elif task_kind.startswith(_MEDIUM_TASK_PREFIXES):
                factors.append(
                    self._factor(
                        plan,
                        factor_type="controlled_mutation_task_type",
                        risk_level=RiskLevel.MEDIUM,
                        description="Sandbox, package, or plugin task planning requires controlled review before any later action.",
                        task_ids=(task.task_id,),
                    )
                )

            declared_risk = _DECLARED_RISK_LEVELS.get(_normalized_text(task.risk_level, max_chars=40).lower())
            if declared_risk is None:
                factors.append(
                    self._factor(
                        plan,
                        factor_type="task_risk_level_invalid",
                        risk_level=RiskLevel.CRITICAL,
                        description="Every planned task must declare only low, medium, or high risk before later review.",
                        task_ids=(task.task_id,),
                    )
                )
            elif declared_risk is not RiskLevel.LOW:
                factors.append(
                    self._factor(
                        plan,
                        factor_type="declared_task_risk",
                        risk_level=declared_risk,
                        description="The task carries an elevated declared risk level that must remain visible to human review.",
                        task_ids=(task.task_id,),
                    )
                )
        return tuple(factors)

    def _dependency_count_factors(
        self,
        plan: ExecutionPlan,
        existing_factors: list[RiskFactor],
    ) -> tuple[RiskFactor, ...]:
        """Return complexity factors for large valid dependency graphs only."""

        if any(factor.risk_level is RiskLevel.CRITICAL for factor in existing_factors):
            return ()
        if not isinstance(plan.dependencies, tuple):
            return ()
        dependency_count = len(plan.dependencies)
        if dependency_count >= 10:
            return (
                self._factor(
                    plan,
                    factor_type="dependency_count_high",
                    risk_level=RiskLevel.HIGH,
                    description="A large dependency graph increases coordination and recovery risk.",
                    metadata={"dependency_count": dependency_count},
                ),
            )
        if dependency_count >= 6:
            return (
                self._factor(
                    plan,
                    factor_type="dependency_count_medium",
                    risk_level=RiskLevel.MEDIUM,
                    description="A multi-branch dependency graph requires focused ordering review.",
                    metadata={"dependency_count": dependency_count},
                ),
            )
        return ()

    def _mutation_target_factors(
        self,
        plan: ExecutionPlan,
        mutation_targets: tuple[MutationTarget, ...],
    ) -> tuple[RiskFactor, ...]:
        """Return risk factors for optional typed mutation targets without validating or executing them."""

        if not isinstance(mutation_targets, tuple):
            return (
                self._factor(
                    plan,
                    factor_type="mutation_target_list_invalid",
                    risk_level=RiskLevel.CRITICAL,
                    description="Mutation targets must be provided as one typed tuple for risk analysis.",
                ),
            )
        if not mutation_targets:
            return (
                self._factor(
                    plan,
                    factor_type="mutation_targets_unresolved",
                    risk_level=RiskLevel.LOW,
                    description="No exact mutation targets were supplied; this standalone plan remains non-executing.",
                ),
            )

        factors: list[RiskFactor] = []
        target_ids: list[str] = []
        for target in mutation_targets:
            if not isinstance(target, MutationTarget):
                factors.append(
                    self._factor(
                        plan,
                        factor_type="mutation_target_invalid",
                        risk_level=RiskLevel.CRITICAL,
                        description="Every mutation target must be a typed MutationTarget before risk can be assessed.",
                    )
                )
                continue

            target_id = _normalized_text(target.mutation_target_id, max_chars=120)
            target_ids.append(target_id)
            locator = _normalized_text(target.locator, max_chars=320).replace("\\", "/").lower().lstrip("./")
            if not target_id or not locator:
                factors.append(
                    self._factor(
                        plan,
                        factor_type="mutation_target_identity_missing",
                        risk_level=RiskLevel.CRITICAL,
                        description="Mutation targets require non-empty identifiers and locators for risk assessment.",
                        mutation_target_ids=(target_id,),
                    )
                )
                continue
            if any(marker in locator for marker in _EXTERNAL_TARGET_MARKERS):
                factors.append(
                    self._factor(
                        plan,
                        factor_type="external_mutation_target",
                        risk_level=RiskLevel.CRITICAL,
                        description="External repositories, URLs, and network targets remain outside this standalone risk boundary.",
                        mutation_target_ids=(target_id,),
                    )
                )
                continue
            if any(locator == protected_path or locator.startswith(protected_path) for protected_path in _PROTECTED_PATHS):
                factors.append(
                    self._factor(
                        plan,
                        factor_type="protected_mutation_target",
                        risk_level=RiskLevel.CRITICAL,
                        description="Protected core, documentation, data, and Git targets require a critical risk classification.",
                        mutation_target_ids=(target_id,),
                    )
                )
                continue

            target_risk = _DECLARED_RISK_LEVELS.get(
                _normalized_text(target.risk_classification, max_chars=40).lower()
            )
            if target_risk is None:
                factors.append(
                    self._factor(
                        plan,
                        factor_type="mutation_target_risk_invalid",
                        risk_level=RiskLevel.CRITICAL,
                        description="Mutation targets must declare only low, medium, or high risk before later review.",
                        mutation_target_ids=(target_id,),
                    )
                )
                continue
            if target_risk is not RiskLevel.LOW:
                factors.append(
                    self._factor(
                        plan,
                        factor_type="declared_mutation_target_risk",
                        risk_level=target_risk,
                        description="The mutation target carries an elevated declared risk level.",
                        mutation_target_ids=(target_id,),
                    )
                )

        if len(set(target_ids)) != len(target_ids):
            factors.append(
                self._factor(
                    plan,
                    factor_type="mutation_target_ids_duplicate",
                    risk_level=RiskLevel.CRITICAL,
                    description="Mutation-target identifiers must be unique for a reviewable risk assessment.",
                    mutation_target_ids=tuple(target_ids),
                )
            )
        return tuple(factors)

    def _has_dependency_cycle(
        self,
        task_ids: tuple[str, ...],
        edges: set[tuple[str, str]],
    ) -> bool:
        """Return True when the typed dependency graph contains a cycle."""

        prerequisites_by_task = {task_id: set() for task_id in task_ids}
        for dependent_task_id, prerequisite_task_id in edges:
            prerequisites_by_task[dependent_task_id].add(prerequisite_task_id)

        active: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> bool:
            if task_id in active:
                return True
            if task_id in visited:
                return False
            active.add(task_id)
            if any(visit(prerequisite_task_id) for prerequisite_task_id in prerequisites_by_task[task_id]):
                return True
            active.remove(task_id)
            visited.add(task_id)
            return False

        return any(visit(task_id) for task_id in task_ids)

    def _highest_risk_level(self, factors: list[RiskFactor]) -> RiskLevel:
        """Return the highest factor level, defaulting to LOW for typed plans without elevated factors."""

        return max((factor.risk_level for factor in factors), key=lambda risk_level: _RISK_ORDER[risk_level], default=RiskLevel.LOW)

    def _recommendations(
        self,
        plan: ExecutionPlan,
        risk_level: RiskLevel,
        factors: list[RiskFactor],
    ) -> tuple[RiskRecommendation, ...]:
        """Build review-only recommendations; no recommendation enables execution."""

        messages = {
            RiskLevel.LOW: ("maintain_standard_review", "Maintain the existing human review and verification gates."),
            RiskLevel.MEDIUM: ("require_focused_verification", "Require focused verification and human review before any later approval-bound handling."),
            RiskLevel.HIGH: ("require_explicit_human_review", "Require explicit human review, exact target binding, verification, and recovery readiness."),
            RiskLevel.CRITICAL: ("block_pending_design_review", "Keep the plan blocked from later handling until a separate human design review resolves the critical factors."),
        }
        code, description = messages[risk_level]
        recommendations = [
            RiskRecommendation(
                recommendation_id=stable_id("risk_recommendation", plan.execution_plan_id, code),
                code=code,
                risk_level=risk_level,
                description=description,
                metadata=sanitize_durable_mapping(
                    {
                        "execution_performed": False,
                        "executor_invoked": False,
                    }
                ),
            )
        ]
        if any(factor.factor_type == "mutation_targets_unresolved" for factor in factors):
            recommendations.append(
                RiskRecommendation(
                    recommendation_id=stable_id("risk_recommendation", plan.execution_plan_id, "resolve_exact_targets"),
                    code="resolve_exact_targets",
                    risk_level=RiskLevel.LOW,
                    description="Bind exact mutation targets only in a future approval-bound stage; this analyzer does not resolve them.",
                    metadata=sanitize_durable_mapping(
                        {
                            "execution_performed": False,
                            "executor_invoked": False,
                        }
                    ),
                )
            )
        return tuple(recommendations)

    def _factor(
        self,
        plan: ExecutionPlan,
        *,
        factor_type: str,
        risk_level: RiskLevel,
        description: str,
        task_ids: tuple[str, ...] = (),
        mutation_target_ids: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> RiskFactor:
        """Build one deterministic typed risk factor without invoking any service."""

        normalized_task_ids = tuple(_normalized_text(task_id, max_chars=120) for task_id in task_ids)
        normalized_target_ids = tuple(_normalized_text(target_id, max_chars=120) for target_id in mutation_target_ids)
        normalized_factor_type = _normalized_text(factor_type, max_chars=120)
        return RiskFactor(
            factor_id=stable_id(
                "risk_factor",
                plan.execution_plan_id,
                normalized_factor_type,
                risk_level.value,
                normalized_task_ids,
                normalized_target_ids,
            ),
            factor_type=normalized_factor_type,
            risk_level=risk_level,
            description=compact_text(description, max_chars=320),
            task_ids=normalized_task_ids,
            mutation_target_ids=normalized_target_ids,
            metadata=sanitize_durable_mapping(
                {
                    "execution_performed": False,
                    "executor_invoked": False,
                    **(metadata or {}),
                }
            ),
        )

    def _reject(
        self,
        *,
        reason_code: str,
        reason: str,
        request_id: str = "",
    ) -> RiskAnalysisResult:
        """Build one typed non-executing rejection result."""

        return RiskAnalysisResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            request_id=compact_text(request_id, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.risk_analysis",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "approval_validation_performed": False,
                }
            ),
        )


__all__ = [
    "RiskAnalysisRequest",
    "RiskAnalysisResult",
    "RiskAnalyzerService",
    "RiskFactor",
    "RiskLevel",
    "RiskRecommendation",
]
