"""Observe-only self-evolution runtime with durable proposal, planning, and execution-boundary records."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from Internet.research import ResearchQuery
from Memory.memory import MemoryEntry

from .action_registry import ActionRecord, ActionRegistryService
from .application_executor import (
    ApplicationExecutionRequest,
    ApplicationExecutionResult,
    ApplicationExecutorService,
)
from .browser_executor import BrowserExecutionRequest, BrowserExecutionResult, BrowserExecutorService
from .desktop_executor import DesktopExecutionRequest, DesktopExecutionResult, DesktopExecutorService
from .execution_context import (
    ExecutionContextBuildRequest,
    ExecutionContextBuildResult,
    ExecutionContextService,
)
from .execution_validator import (
    ExecutionValidationRequest,
    ExecutionValidationResult,
    ExecutionValidatorService,
)
from .inventory import CapabilityInventoryBuilder
from .models import (
    ApprovalDecision,
    CapabilityGap,
    CapabilityInventorySnapshot,
    ChangePlan,
    ChangeJournalEntry,
    ChangeProposal,
    DiscoveryCandidate,
    DiscoveryQueryResult,
    ExecutionAuthorization,
    ExecutionRequest,
    ExecutionStepRequest,
    EvaluationRecord,
    EvidenceRecord,
    EvolutionAutonomyLevel,
    LearnedOutcome,
    MutationApproval,
    MutationObservation,
    MutationOutcome,
    MutationRun,
    MutationStepRun,
    MutationTarget,
    PlanStep,
    RecoveryObservation,
    RecoveryOutcome,
    RecoveryRequirement,
    RecoveryRun,
    RollbackArtifact,
    RecoveryStepRun,
    VerificationObservation,
    VerificationOutcome,
    VerificationRequirement,
    VerificationRun,
    VerificationStepRun,
    compact_text,
    normalize_identity,
    parse_timestamp,
    sanitize_durable_mapping,
    sanitize_durable_value,
    stable_id,
    utc_now,
)
from .mutation_approval import MutationApprovalRequest, MutationApprovalService
from .decision_engine import DecisionEngineService, DecisionRequest, DecisionResult
from .execution_scheduler import ExecutionSchedule, ExecutionSchedulerService, SchedulerRequest, SchedulerResult
from .git_executor import GitExecutionRequest, GitExecutionResult, GitExecutorService
from .mutation_policy import MutationGuardDecision, MutationGuardRequest, MutationGuardService
from .mutation_runner import MutationRunRequest, MutationRunResult, MutationRunService
from .mutation_surfaces import MutationSurfaceDefinition, MutationSurfaceRegistry
from .package_executor import PackageExecutionRequest, PackageExecutionResult, PackageExecutorService
from .plugin_executor import PluginExecutionRequest, PluginExecutionResult, PluginExecutorService
from .risk_analyzer import RiskAnalysisRequest, RiskAnalysisResult, RiskAnalyzerService
from .sandbox_executor import SandboxExecutionRequest, SandboxExecutionResult, SandboxExecutorService
from .source_executor import SourceExecutionRequest, SourceExecutionResult, SourceExecutorService
from .task_planner import TaskPlannerService, TaskPlanningRequest, TaskPlanningResult
from .workflow_engine import WorkflowEngineService, WorkflowRequest, WorkflowResult
from .workflow_executor import WorkflowExecutionRequest, WorkflowExecutionResult, WorkflowExecutorService

_PHRASE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "sandbox_execution",
        (
            "sandboxed python",
            "sandboxed runtime",
            "sandboxed code",
            "sandboxed execution",
            "sandbox",
            "isolated execution",
            "isolated runtime",
            "isolated environment",
            "experiment runner",
            "experiment execution",
            "code runner",
            "code execution",
            "python runtime",
            "python runner",
            "secure code execution",
            "execute code without host access",
        ),
    ),
    (
        "rollback_recovery",
        (
            "rollback",
            "recovery",
            "restore point",
            "restore previous",
            "restore version",
            "revert changes",
            "checkpoint restore",
            "checkpoint recovery",
            "backup restore",
            "disaster recovery",
        ),
    ),
    (
        "package_management",
        (
            "pip install",
            "package install",
            "dependency management",
            "dependency upgrade",
            "dependency resolver",
            "dependency compatibility",
            "package compatibility",
            "package manager",
            "requirements.txt",
            "version pinning",
            "installer",
            "install package",
            "upgrade package",
        ),
    ),
    (
        "code_development",
        (
            "source code",
            "codebase",
            "self-modification",
            "self modification",
            "modify source",
            "modify code",
            "source modification",
            "edit source",
            "patch generation",
            "patch engine",
            "code refactor",
            "rewrite code",
            "apply patch",
        ),
    ),
    ("voice", ("voice", "speech", "stt", "tts", "microphone", "wake word", "wakeword", "audio")),
    ("vision", ("vision", "ocr", "image", "camera", "screenshot", "face detection", "object detection", "barcode", "qr")),
    ("automation", ("automation", "workflow", "scheduler", "task queue", "task runner", "job runner", "background task")),
    ("integration", ("plugin", "extension", "integration", "adapter", "connector")),
    ("computer_control", ("desktop control", "computer control", "window control", "clipboard", "keyboard", "mouse")),
    ("memory", ("memory", "profile", "session memory", "vector database")),
    (
        "internet",
        (
            "web research",
            "internet research",
            "web search",
            "internet search",
            "browse the web",
            "search provider",
            "research service",
            "grounded research",
            "news provider",
            "weather provider",
            "wikipedia provider",
            "youtube provider",
        ),
    ),
    ("ai", ("llm", "language model", "model provider", "ai provider", "model routing", "inference engine")),
)
_TECHNICAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "compatibility_notes": ("python", "windows", "linux", "api", "sdk", "local", "offline", "on-device", "on device"),
    "cost_notes": ("free", "open source", "open-source", "paid", "pricing", "subscription", "enterprise"),
    "privacy_security_notes": ("local", "offline", "on-device", "on device", "cloud", "hosted", "remote", "privacy", "security"),
    "reliability_notes": ("beta", "preview", "experimental", "stable", "release"),
}
_EVIDENCE_FALLBACK_CATEGORIES = frozenset(
    {
        "sandbox_execution",
        "rollback_recovery",
        "package_management",
        "code_development",
        "voice",
        "vision",
        "automation",
        "integration",
        "computer_control",
        "memory",
    }
)
_DESCRIPTION_FALLBACK_CATEGORIES = frozenset(set(_EVIDENCE_FALLBACK_CATEGORIES) | {"ai"})
_CATEGORY_RELATIONSHIPS: dict[str, frozenset[str]] = {
    "ai": frozenset({"ai"}),
    "automation": frozenset({"automation"}),
    "computer_control": frozenset({"computer_control"}),
    "integration": frozenset({"plugin", "skill"}),
    "internet": frozenset({"internet", "plugin", "skill"}),
    "memory": frozenset({"memory"}),
    "voice": frozenset({"voice"}),
    "vision": frozenset({"vision"}),
}
_INTERNET_ALIGNMENT_MARKERS: dict[str, tuple[str, ...]] = {
    "internet:http_client": ("http", "api client", "http client", "fetch", "request client"),
    "internet:search_provider": ("search", "search provider", "web search", "internet search", "search results"),
    "internet:research_service": ("research", "research service", "grounded research", "web research", "public web"),
    "internet:news_provider": ("news", "headline", "top stories"),
    "internet:weather_provider": ("weather", "forecast", "temperature"),
    "internet:wikipedia_provider": ("wikipedia", "encyclopedia"),
    "internet:youtube_provider": ("youtube", "video", "channel"),
}
_INTERNET_GENERIC_CAPABILITY_IDS = frozenset({"internet:runtime", "plugin:internet.runtime", "skill:internet.query"})
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_MUTATING_ACTION_KINDS = frozenset(
    {
        "package_install",
        "package_remove",
        "software_install",
        "software_uninstall",
        "code_execute",
        "source_create",
        "source_modify",
        "source_delete",
        "plugin_install",
        "plugin_remove",
        "git_operation",
        "application_open",
        "application_close",
        "computer_control",
        "automation_action",
        "os_configuration",
        "service_integration",
    }
)
_CATEGORY_SURFACE_MAP: dict[str, tuple[str, ...]] = {
    "ai": ("ai provider routing",),
    "automation": ("automation runtime",),
    "code_development": ("source code workspace",),
    "computer_control": ("desktop control surfaces",),
    "integration": ("plugin and skill integration surfaces",),
    "internet": ("internet services",),
    "memory": ("memory services",),
    "package_management": ("python packages and dependencies",),
    "rollback_recovery": ("runtime rollback and recovery workflow",),
    "sandbox_execution": ("sandboxed local execution runtime",),
    "vision": ("vision services",),
    "voice": ("voice services",),
}
_EXECUTOR_CATEGORY_KEYS = frozenset(
    {
        "verification_observation",
        "recovery_preparation",
        "sandbox_execution",
        "package_management",
        "code_development",
        "git_operation",
        "plugin_management",
        "os_configuration",
        "computer_control",
        "automation_action",
        "unsupported",
    }
)
_VERIFICATION_RUN_TERMINAL_STATUSES = frozenset(
    {
        "passed",
        "failed",
        "partial",
        "blocked",
        "invalidated",
        "superseded",
        "aborted",
    }
)
_VERIFICATION_STEP_TERMINAL_STATUSES = frozenset(
    {
        "satisfied",
        "unsatisfied",
        "error",
        "skipped",
        "invalidated",
    }
)
_VERIFICATION_STEP_OUTCOMES = frozenset(_VERIFICATION_STEP_TERMINAL_STATUSES)
_RECOVERY_RUN_TERMINAL_STATUSES = frozenset({"ready", "blocked", "invalidated"})
_RECOVERY_STEP_TERMINAL_STATUSES = frozenset({"ready", "blocked", "invalidated"})
_RECOVERY_STEP_OUTCOMES = frozenset({"ready", "blocked"})
_PHASE8_EXECUTOR_BINDINGS = {
    "sandbox_execution": ("sandbox", "sandbox_executor_service"),
    "package_management": ("package", "package_executor_service"),
    "code_development": ("source", "source_executor_service"),
    "plugin_management": ("plugin", "plugin_executor_service"),
    "git_operation": ("git", "git_executor_service"),
}


def _normalize_decision_text(value: str) -> str:
    """Normalize one free-form approval text into a conservative comparison key."""

    return " ".join(_WORD_PATTERN.findall(compact_text(value, max_chars=240).lower()))


_APPROVAL_TEXTS = frozenset(
    {
        _normalize_decision_text("yes"),
        _normalize_decision_text("approve"),
        _normalize_decision_text("approved"),
        _normalize_decision_text("yes approve"),
        _normalize_decision_text("yes approve this proposal"),
        _normalize_decision_text("yes do it"),
        _normalize_decision_text("proceed with this proposal"),
        _normalize_decision_text("go ahead"),
        _normalize_decision_text("go ahead with this proposal"),
        _normalize_decision_text("approve this proposal"),
        _normalize_decision_text("ha"),
        _normalize_decision_text("ha kar do"),
        _normalize_decision_text("haan"),
        _normalize_decision_text("haan karo"),
        _normalize_decision_text("haan is proposal ko approve karo"),
        _normalize_decision_text("isko approve kar do"),
        _normalize_decision_text("yes karo"),
        _normalize_decision_text("karo"),
    }
)
_REJECTION_TEXTS = frozenset(
    {
        _normalize_decision_text("no"),
        _normalize_decision_text("reject"),
        _normalize_decision_text("rejected"),
        _normalize_decision_text("reject this proposal"),
        _normalize_decision_text("do not approve"),
        _normalize_decision_text("do not do it"),
        _normalize_decision_text("don't do it"),
        _normalize_decision_text("nahi"),
        _normalize_decision_text("nahi karo"),
        _normalize_decision_text("nahin"),
        _normalize_decision_text("isko reject karo"),
        _normalize_decision_text("mat karo"),
    }
)


def _emit_log(logger: Any | None, level: str, message: str, **context: Any) -> None:
    """Write a log message using either stdlib-style or Core logger contracts."""

    if logger is None:
        return

    if hasattr(logger, level.lower()):
        details = " | ".join(f"{key}={value}" for key, value in sorted(context.items()))
        payload = f"{message} | {details}" if details else message
        getattr(logger, level.lower())(payload)
        return

    try:
        from Core.logger import LogLevel

        log_level = getattr(LogLevel, level.upper(), LogLevel.INFO)
        logger.log(log_level, message, **context)
    except Exception:
        return


class DependencyRegistrar(Protocol):
    """Protocol for dependency-injection containers used by Evolution."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


@dataclass(slots=True, frozen=True)
class EvolutionPolicy:
    """Represent the currently active self-evolution policy gate."""

    autonomy_level: EvolutionAutonomyLevel = EvolutionAutonomyLevel.OBSERVE_ONLY


@dataclass(slots=True, frozen=True)
class MutationExecutorSelection:
    """One typed Phase 8 executor-selection decision for one mutation target."""

    decision: str
    mutation_target_id: str
    executor_category: str
    executor_kind: str
    reason_code: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def selected(self) -> bool:
        """Return True only when one Phase 8 executor was explicitly selected."""

        return self.decision == "selected"


@dataclass(slots=True, frozen=True)
class Phase8MutationExecutionRequest:
    """One explicit approval-bound request to simulate a selected Phase 8 executor."""

    mutation_approval: MutationApproval | str
    mutation_target_id: str
    operation: str
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class Phase8MutationExecutionResult:
    """One typed runtime result for an explicit, simulated Phase 8 executor request."""

    decision: str
    reason_code: str
    reason: str
    mutation_approval_id: str
    mutation_run_id: str
    recovery_outcome_id: str
    recovery_run_id: str
    mutation_target_id: str
    executor_kind: str
    executor_result: (
        SandboxExecutionResult
        | PackageExecutionResult
        | SourceExecutionResult
        | PluginExecutionResult
        | GitExecutionResult
        | None
    ) = None
    rollback_artifact: RollbackArtifact | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def successful(self) -> bool:
        """Return True only when one executor completed its placeholder simulation."""

        return self.decision == "simulated"


@dataclass(slots=True, frozen=True)
class Phase9PlanningPipelineRequest:
    """One typed request to compose the review-only Phase 9 planning intelligence pipeline."""

    task_planning_request: TaskPlanningRequest
    mutation_approval: MutationApproval | str | None = None
    request_id: str = ""
    actor: str = "narvis"
    evaluated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class Phase9PlanningPipelineResult:
    """One typed runtime result for a planning pipeline that never executes tasks or mutations."""

    decision: str
    reason_code: str
    reason: str
    request_id: str = ""
    mutation_approval_id: str = ""
    task_planning_result: TaskPlanningResult | None = None
    risk_analysis_result: RiskAnalysisResult | None = None
    scheduler_result: SchedulerResult | None = None
    workflow_result: WorkflowResult | None = None
    decision_result: DecisionResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def completed(self) -> bool:
        """Return True only when every review-only planning stage produced a typed result."""

        return self.decision == "completed" and self.decision_result is not None


@dataclass(slots=True, frozen=True)
class _PlanStepBlueprint:
    """Internal deterministic blueprint used to materialize durable plan records."""

    sequence: int
    action_kind: str
    target: str
    description: str
    inputs: dict[str, Any]
    expected_outcome: str
    verification_requirements: tuple[tuple[str, str], ...] = ()
    recovery_requirement: str | None = None
    risk_classification: str = "medium"
    metadata: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class _ExecutionStepBlueprint:
    """Internal deterministic execution-boundary projection of one plan step."""

    plan_step_id: str
    sequence: int
    executor_category: str
    action_kind: str
    target: str
    inputs: dict[str, Any]
    risk_classification: str = "medium"
    metadata: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class _ExecutionValidationResult:
    """Internal revalidation result used before authorization is recorded."""

    decision: str
    reason_code: str
    reason: str
    proposal: ChangeProposal | None = None
    plan: ChangePlan | None = None
    approval: ApprovalDecision | None = None
    step_requests: tuple[ExecutionStepRequest, ...] = ()


@dataclass(slots=True, frozen=True)
class _VerificationEligibilityResult:
    """Internal Phase 5 eligibility result for verification-run lifecycle work."""

    decision: str
    reason_code: str
    reason: str
    authorization: ExecutionAuthorization | None = None
    request: ExecutionRequest | None = None
    proposal: ChangeProposal | None = None
    plan: ChangePlan | None = None
    approval: ApprovalDecision | None = None
    verification_step_requests: tuple[ExecutionStepRequest, ...] = ()


@dataclass(slots=True, frozen=True)
class _RecoveryEligibilityResult:
    """Internal Phase 6 eligibility result for recovery-run lifecycle work."""

    decision: str
    reason_code: str
    reason: str
    verification_outcome: VerificationOutcome | None = None
    verification_run: VerificationRun | None = None
    authorization: ExecutionAuthorization | None = None
    request: ExecutionRequest | None = None
    proposal: ChangeProposal | None = None
    plan: ChangePlan | None = None
    approval: ApprovalDecision | None = None
    recovery_step_requests: tuple[ExecutionStepRequest, ...] = ()


class SelfEvolutionService:
    """Observe-only self-evolution service with approval-bound planning and authorization support."""

    def __init__(
        self,
        *,
        storage: Any,
        internet_service: Any,
        inventory_builder: CapabilityInventoryBuilder,
        mutation_surface_registry: MutationSurfaceRegistry | None = None,
        mutation_guard_service: MutationGuardService | None = None,
        mutation_approval_service: MutationApprovalService | None = None,
        mutation_run_service: MutationRunService | None = None,
        sandbox_executor_service: SandboxExecutorService | None = None,
        package_executor_service: PackageExecutorService | None = None,
        source_executor_service: SourceExecutorService | None = None,
        plugin_executor_service: PluginExecutorService | None = None,
        git_executor_service: GitExecutorService | None = None,
        task_planner_service: TaskPlannerService | None = None,
        risk_analyzer_service: RiskAnalyzerService | None = None,
        execution_scheduler_service: ExecutionSchedulerService | None = None,
        workflow_engine_service: WorkflowEngineService | None = None,
        decision_engine_service: DecisionEngineService | None = None,
        action_registry_service: ActionRegistryService | None = None,
        execution_context_service: ExecutionContextService | None = None,
        execution_validator_service: ExecutionValidatorService | None = None,
        desktop_executor_service: DesktopExecutorService | None = None,
        application_executor_service: ApplicationExecutorService | None = None,
        browser_executor_service: BrowserExecutorService | None = None,
        workflow_executor_service: WorkflowExecutorService | None = None,
        policy: EvolutionPolicy | None = None,
        logger: Any | None = None,
    ) -> None:
        self.storage = storage
        self.internet_service = internet_service
        self.inventory_builder = inventory_builder
        self.mutation_surface_registry = mutation_surface_registry or MutationSurfaceRegistry()
        self.mutation_guard_service = mutation_guard_service or MutationGuardService(
            surface_registry=self.mutation_surface_registry
        )
        self.mutation_approval_service = mutation_approval_service or MutationApprovalService()
        self.mutation_run_service = mutation_run_service or MutationRunService()
        workspace_root = self.mutation_surface_registry.workspace_root.resolve()
        self.sandbox_executor_service = sandbox_executor_service or SandboxExecutorService(
            sandbox_root=workspace_root / "data" / "evolution_sandbox"
        )
        self.package_executor_service = package_executor_service or PackageExecutorService()
        self.source_executor_service = source_executor_service or SourceExecutorService(
            workspace_root=workspace_root,
            surface_registry=self.mutation_surface_registry,
        )
        self.plugin_executor_service = plugin_executor_service or PluginExecutorService(
            surface_registry=self.mutation_surface_registry
        )
        self.git_executor_service = git_executor_service or GitExecutorService(repository_root=workspace_root)
        self.task_planner_service = task_planner_service or TaskPlannerService()
        self.risk_analyzer_service = risk_analyzer_service or RiskAnalyzerService()
        self.execution_scheduler_service = execution_scheduler_service or ExecutionSchedulerService()
        self.workflow_engine_service = workflow_engine_service or WorkflowEngineService()
        self.decision_engine_service = decision_engine_service or DecisionEngineService()
        self.action_registry_service = action_registry_service or ActionRegistryService()
        self.execution_context_service = execution_context_service or ExecutionContextService()
        self.execution_validator_service = execution_validator_service or ExecutionValidatorService(
            action_registry=self.action_registry_service,
            context_service=self.execution_context_service,
            mutation_guard=self.mutation_guard_service,
        )
        self.desktop_executor_service = desktop_executor_service or DesktopExecutorService()
        self.application_executor_service = application_executor_service or ApplicationExecutorService()
        self.browser_executor_service = browser_executor_service or BrowserExecutorService()
        self.workflow_executor_service = workflow_executor_service or WorkflowExecutorService()
        self.policy = policy or EvolutionPolicy()
        self.logger = logger
        self._mutation_approvals: dict[str, MutationApproval] = {}
        self._mutation_targets_by_approval: dict[str, tuple[MutationTarget, ...]] = {}
        self._mutation_runs: dict[str, MutationRun] = {}
        self._mutation_step_runs: dict[str, MutationStepRun] = {}
        self._mutation_observations: dict[str, MutationObservation] = {}
        self._mutation_outcomes: dict[str, MutationOutcome] = {}
        self._mutation_outcomes_by_run_id: dict[str, MutationOutcome] = {}
        self._rollback_artifacts: dict[str, RollbackArtifact] = {}
        if self.policy.autonomy_level is not EvolutionAutonomyLevel.OBSERVE_ONLY:
            raise ValueError("Self-Evolution currently supports observe_only autonomy only.")

    @property
    def autonomy_level(self) -> EvolutionAutonomyLevel:
        """Return the active autonomy level."""

        return self.policy.autonomy_level

    def list_registered_actions(self) -> tuple[ActionRecord, ...]:
        """Return the inert Phase 10 action catalog without selecting or executing an action."""

        return self.action_registry_service.list_actions()

    def create_execution_context(
        self,
        request: ExecutionContextBuildRequest,
    ) -> ExecutionContextBuildResult:
        """Build one caller-supplied immutable execution context without observing the host."""

        return self.execution_context_service.build_snapshot(request)

    def validate_execution(
        self,
        request: ExecutionValidationRequest,
    ) -> ExecutionValidationResult:
        """Validate one future action request without authorizing or invoking host execution."""

        return self.execution_validator_service.validate(request)

    def simulate_desktop_execution(
        self,
        request: DesktopExecutionRequest,
    ) -> DesktopExecutionResult:
        """Return one Phase 10 desktop placeholder result without desktop or OS interaction."""

        return self.desktop_executor_service.execute(request)

    def simulate_application_execution(
        self,
        request: ApplicationExecutionRequest,
    ) -> ApplicationExecutionResult:
        """Return one Phase 10 application placeholder result without process or OS interaction."""

        return self.application_executor_service.execute(request)

    def simulate_browser_execution(
        self,
        request: BrowserExecutionRequest,
    ) -> BrowserExecutionResult:
        """Return one Phase 10 browser placeholder result without browser launch or network access."""

        return self.browser_executor_service.execute(request)

    def compose_execution_workflow(
        self,
        request: WorkflowExecutionRequest,
    ) -> WorkflowExecutionResult:
        """Compose one validated Phase 10 workflow plan without invoking any executor."""

        return self.workflow_executor_service.compose(request)

    def run_phase9_planning_pipeline(
        self,
        request: Phase9PlanningPipelineRequest,
    ) -> Phase9PlanningPipelineResult:
        """Compose planning, risk, scheduling, workflow, and decision records without execution."""

        if not isinstance(request, Phase9PlanningPipelineRequest):
            return self._reject_phase9_planning_pipeline(
                reason_code="invalid_phase9_planning_request",
                reason="Phase 9 planning requires one typed Phase9PlanningPipelineRequest.",
            )
        if not isinstance(request.task_planning_request, TaskPlanningRequest):
            return self._reject_phase9_planning_pipeline(
                reason_code="invalid_task_planning_request",
                reason="Phase 9 planning requires one typed TaskPlanningRequest.",
                request_id=compact_text(request.request_id, max_chars=120),
            )
        if request.mutation_approval is not None and not isinstance(request.mutation_approval, MutationApproval | str):
            return self._reject_phase9_planning_pipeline(
                reason_code="invalid_mutation_approval_reference",
                reason="Phase 9 planning accepts only a recorded MutationApproval or approval identifier when supplied.",
                request_id=compact_text(request.request_id, max_chars=120),
            )

        resolved_approval: MutationApproval | None = None
        if request.mutation_approval is not None:
            resolved_approval = self._resolve_known_mutation_approval(request.mutation_approval)
            if resolved_approval is None:
                return self._reject_phase9_planning_pipeline(
                    reason_code="unknown_mutation_approval",
                    reason="Phase 9 readiness evaluation accepts only a mutation approval recorded by this evolution service.",
                    request_id=compact_text(request.request_id, max_chars=120),
                )
            if request.task_planning_request.approval_reference != resolved_approval.mutation_approval_id:
                return self._reject_phase9_planning_pipeline(
                    reason_code="planning_approval_reference_mismatch",
                    reason="The TaskPlanningRequest approval reference must exactly match the supplied MutationApproval identifier.",
                    request_id=compact_text(request.request_id, max_chars=120),
                    mutation_approval_id=resolved_approval.mutation_approval_id,
                )
            resolved_approval, approval_error = self._revalidate_mutation_approval_for_phase9_planning(
                resolved_approval,
                actor=compact_text(request.actor, max_chars=120) or "narvis",
            )
            if approval_error is not None:
                reason_code, reason = approval_error
                return self._reject_phase9_planning_pipeline(
                    reason_code=reason_code,
                    reason=reason,
                    request_id=compact_text(request.request_id, max_chars=120),
                    mutation_approval_id=resolved_approval.mutation_approval_id if resolved_approval is not None else "",
                )

        planning_result = self.task_planner_service.plan(request.task_planning_request)
        if not planning_result.planned or planning_result.execution_plan is None:
            return self._reject_phase9_planning_pipeline(
                reason_code=planning_result.reason_code,
                reason=planning_result.reason,
                request_id=planning_result.request_id,
                mutation_approval_id=resolved_approval.mutation_approval_id if resolved_approval is not None else "",
                task_planning_result=planning_result,
            )

        risk_analysis_result = self.risk_analyzer_service.analyze(
            RiskAnalysisRequest(execution_plan=planning_result.execution_plan)
        )
        if not risk_analysis_result.analyzed:
            return self._reject_phase9_planning_pipeline(
                reason_code=risk_analysis_result.reason_code,
                reason=risk_analysis_result.reason,
                request_id=planning_result.request_id,
                mutation_approval_id=resolved_approval.mutation_approval_id if resolved_approval is not None else "",
                task_planning_result=planning_result,
                risk_analysis_result=risk_analysis_result,
            )

        scheduler_result = self.execution_scheduler_service.schedule(
            SchedulerRequest(execution_plan=planning_result.execution_plan)
        )
        if not scheduler_result.scheduled or scheduler_result.execution_schedule is None:
            return self._reject_phase9_planning_pipeline(
                reason_code=scheduler_result.reason_code,
                reason=scheduler_result.reason,
                request_id=planning_result.request_id,
                mutation_approval_id=resolved_approval.mutation_approval_id if resolved_approval is not None else "",
                task_planning_result=planning_result,
                risk_analysis_result=risk_analysis_result,
                scheduler_result=scheduler_result,
            )

        workflow_result = self.workflow_engine_service.orchestrate(
            WorkflowRequest(
                execution_plan=planning_result.execution_plan,
                risk_analysis=risk_analysis_result,
                execution_schedule=scheduler_result.execution_schedule,
            )
        )
        if not workflow_result.orchestrated:
            return self._reject_phase9_planning_pipeline(
                reason_code=workflow_result.reason_code,
                reason=workflow_result.reason,
                request_id=planning_result.request_id,
                mutation_approval_id=resolved_approval.mutation_approval_id if resolved_approval is not None else "",
                task_planning_result=planning_result,
                risk_analysis_result=risk_analysis_result,
                scheduler_result=scheduler_result,
                workflow_result=workflow_result,
            )

        decision_result = self.decision_engine_service.decide(
            DecisionRequest(
                workflow_result=workflow_result,
                risk_analysis=risk_analysis_result,
                mutation_approval=resolved_approval,
                evaluated_at=request.evaluated_at,
            )
        )
        if not decision_result.decided:
            return self._reject_phase9_planning_pipeline(
                reason_code=decision_result.reason_code,
                reason=decision_result.reason,
                request_id=planning_result.request_id,
                mutation_approval_id=resolved_approval.mutation_approval_id if resolved_approval is not None else "",
                task_planning_result=planning_result,
                risk_analysis_result=risk_analysis_result,
                scheduler_result=scheduler_result,
                workflow_result=workflow_result,
                decision_result=decision_result,
            )

        return Phase9PlanningPipelineResult(
            decision="completed",
            reason_code="phase9_planning_pipeline_completed",
            reason="The typed planning intelligence pipeline completed without task, mutation, or executor execution.",
            request_id=compact_text(request.request_id, max_chars=120) or planning_result.request_id,
            mutation_approval_id=resolved_approval.mutation_approval_id if resolved_approval is not None else "",
            task_planning_result=planning_result,
            risk_analysis_result=risk_analysis_result,
            scheduler_result=scheduler_result,
            workflow_result=workflow_result,
            decision_result=decision_result,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.runtime_pipeline",
                    "decision_state": decision_result.state.value,
                    "execution_performed": False,
                    "executor_invoked": False,
                    "real_mutation_performed": False,
                }
            ),
        )

    def snapshot_inventory(self) -> CapabilityInventorySnapshot:
        """Capture and persist the current deterministic capability inventory."""

        snapshot = self.inventory_builder.build()
        self._persist_record(
            category="capability_inventory",
            key=f"evolution:capability_inventory:{snapshot.snapshot_id}",
            value=snapshot.to_dict(),
            metadata={
                "autonomy_level": self.autonomy_level.value,
                "snapshot_id": snapshot.snapshot_id,
            },
        )
        return snapshot

    def discover_candidates(self, query: str) -> DiscoveryQueryResult:
        """Use the existing Internet research path to build source-backed candidates."""

        normalized_query = compact_text(query, max_chars=200)
        if not normalized_query:
            return DiscoveryQueryResult(
                query="",
                status="no_results",
                candidates=(),
                error="A discovery query is required.",
                autonomy_level=self.autonomy_level,
            )

        research_query = ResearchQuery(
            original_text=normalized_query,
            topic=normalized_query,
            search_text=normalized_query,
            confidence=1.0,
            reason="observe-only evolution discovery",
            intent_kind="explicit",
            routing_signals=("evolution", "discovery"),
        )
        response = self.internet_service.research(research_query, limit=5)
        evidence_records = self._build_evidence_records(response)

        if response.search_status == "all_failed" and not evidence_records:
            return DiscoveryQueryResult(
                query=normalized_query,
                status="provider_unavailable",
                candidates=(),
                error=response.error or "Internet research providers were unavailable.",
                search_provider_name=response.search_provider_name,
                source_count=0,
                autonomy_level=self.autonomy_level,
            )

        if not evidence_records:
            return DiscoveryQueryResult(
                query=normalized_query,
                status="no_results",
                candidates=(),
                error=response.error if response.search_status == "zero_results" else None,
                search_provider_name=response.search_provider_name,
                source_count=0,
                autonomy_level=self.autonomy_level,
            )

        candidate = self._build_candidate(normalized_query, response, evidence_records)
        for evidence in candidate.evidence_records:
            self._persist_record(
                category="evidence_record",
                key=f"evolution:evidence_record:{evidence.evidence_id}",
                value=evidence.to_dict(),
                metadata={
                    "autonomy_level": self.autonomy_level.value,
                    "evidence_id": evidence.evidence_id,
                    "candidate_id": candidate.candidate_id,
                },
            )
        self._persist_record(
            category="discovery_candidate",
            key=f"evolution:discovery_candidate:{candidate.candidate_id}",
            value=candidate.to_dict(),
            metadata={
                "autonomy_level": self.autonomy_level.value,
                "candidate_id": candidate.candidate_id,
                "technology_category": candidate.technology_category,
            },
        )
        result = DiscoveryQueryResult(
            query=normalized_query,
            status="discovered",
            candidates=(candidate,),
            search_provider_name=response.search_provider_name,
            source_count=len(candidate.evidence_records),
            autonomy_level=self.autonomy_level,
        )
        _emit_log(self.logger, "info", "Discovered evolution candidate", candidate_id=candidate.candidate_id, query=normalized_query)
        return result

    def evaluate_candidate(self, candidate: DiscoveryCandidate) -> EvaluationRecord:
        """Create and persist one conservative evidence-backed evaluation draft."""

        if self.autonomy_level is not EvolutionAutonomyLevel.OBSERVE_ONLY:
            raise ValueError("Evaluation is only available in observe_only mode.")

        snapshot = self.snapshot_inventory()
        self._persist_candidate(candidate)

        related_records = self._select_related_records(candidate, snapshot.capabilities)
        degraded_records = [record for record in related_records if record.status in {"degraded", "unavailable", "stopped"}]
        evidence_ids = tuple(record.evidence_id for record in candidate.evidence_records)
        facts = (
            f"Candidate '{candidate.name}' is tracked under category '{candidate.technology_category}'.",
            f"Discovery includes {len(candidate.evidence_records)} source-backed evidence record(s).",
            f"The current inventory contains {len(related_records)} related capability record(s).",
        ) + tuple(
            f"Current related capability '{record.name}' reports status '{record.status}'."
            for record in related_records
        )

        inferences = list(self._build_inferences(candidate, related_records, degraded_records))
        potential_benefits = list(self._build_potential_benefits(candidate, degraded_records, related_records))
        compatibility_notes = self._extract_signal_notes(candidate, "compatibility_notes")
        cost_notes = self._extract_signal_notes(candidate, "cost_notes")
        privacy_security_notes = self._extract_signal_notes(candidate, "privacy_security_notes")
        reliability_notes = self._extract_signal_notes(candidate, "reliability_notes")

        unknowns = [
            "Compatibility with the current NARVIS runtime is unverified.",
            "No installation or integration decision is allowed in observe_only mode.",
        ]
        if not compatibility_notes:
            unknowns.append("Direct compatibility evidence was not found in the current source set.")
        if not cost_notes:
            unknowns.append("Cost evidence was not found in the current source set.")
        if not privacy_security_notes:
            unknowns.append("Privacy and security implications remain unverified.")
        if not reliability_notes:
            unknowns.append("Reliability evidence remains limited.")

        gaps = self._build_capability_gaps(
            candidate=candidate,
            inventory_snapshot=snapshot,
            related_records=related_records,
            degraded_records=degraded_records,
        )
        for gap in gaps:
            self._persist_record(
                category="capability_gap",
                key=f"evolution:capability_gap:{gap.gap_id}",
                value=gap.to_dict(),
                metadata={
                    "autonomy_level": self.autonomy_level.value,
                    "candidate_id": gap.candidate_id,
                    "gap_id": gap.gap_id,
                },
            )

        confidence = min(
            0.85,
            round(
                0.35
                + (0.1 * min(len(candidate.evidence_records), 3))
                + (0.1 if candidate.technology_category != "technology" else 0.0)
                + (0.1 if gaps else 0.0),
                4,
            ),
        )
        evaluation = EvaluationRecord(
            evaluation_id=stable_id("evaluation_record", candidate.candidate_id, snapshot.snapshot_id),
            candidate_id=candidate.candidate_id,
            candidate_name=candidate.name,
            candidate_category=candidate.technology_category,
            inventory_snapshot_id=snapshot.snapshot_id,
            facts=tuple(facts),
            evidence_ids=evidence_ids,
            inferences=tuple(inferences),
            unknowns=tuple(dict.fromkeys(unknowns)),
            potential_benefits=tuple(dict.fromkeys(potential_benefits)),
            overlapping_capability_ids=tuple(record.capability_id for record in related_records),
            capability_gap_ids=tuple(gap.gap_id for gap in gaps),
            compatibility_notes=tuple(compatibility_notes),
            cost_notes=tuple(cost_notes),
            privacy_security_notes=tuple(privacy_security_notes),
            reliability_notes=tuple(reliability_notes),
            confidence=confidence,
            metadata={"autonomy_level": self.autonomy_level.value},
        )
        self._persist_record(
            category="evaluation_record",
            key=f"evolution:evaluation_record:{evaluation.evaluation_id}",
            value=evaluation.to_dict(),
            metadata={
                "autonomy_level": self.autonomy_level.value,
                "candidate_id": evaluation.candidate_id,
                "evaluation_id": evaluation.evaluation_id,
            },
        )
        _emit_log(self.logger, "info", "Evaluated evolution candidate", candidate_id=candidate.candidate_id, evaluation_id=evaluation.evaluation_id)
        return evaluation

    def list_capability_gaps(self) -> tuple[CapabilityGap, ...]:
        """Return every persisted capability gap in deterministic order."""

        gaps = self._load_records("capability_gap", CapabilityGap.from_dict)
        return tuple(sorted(gaps, key=lambda gap: (gap.capability_category, gap.summary, gap.gap_id)))

    def record_outcome(self, record: LearnedOutcome) -> LearnedOutcome:
        """Persist one durable learned outcome record."""

        self._persist_record(
            category="learned_outcome",
            key=f"evolution:learned_outcome:{record.outcome_id}",
            value=record.to_dict(),
            metadata={
                "autonomy_level": self.autonomy_level.value,
                "subject_id": record.subject_id,
                "outcome_id": record.outcome_id,
            },
        )
        _emit_log(self.logger, "info", "Recorded evolution outcome", outcome_id=record.outcome_id, subject_id=record.subject_id)
        return record

    def create_change_proposal(
        self,
        evaluation: EvaluationRecord,
        *,
        actor: str = "narvis",
        title: str | None = None,
        summary: str | None = None,
        rationale: str | None = None,
        requested_actions: tuple[str, ...] | None = None,
        affected_surfaces: tuple[str, ...] | None = None,
        expected_benefits: tuple[str, ...] | None = None,
        known_risks: tuple[str, ...] | None = None,
        verification_plan: tuple[str, ...] | None = None,
        rollback_plan: tuple[str, ...] | None = None,
    ) -> ChangeProposal:
        """Create and persist one immutable change proposal from an evaluation record."""

        proposal_id = stable_id("change_proposal", evaluation.candidate_id)
        existing_versions = self.list_change_proposals(candidate_id=evaluation.candidate_id)
        title_value = compact_text(title or self._build_proposal_title(evaluation), max_chars=160)
        summary_value = compact_text(summary or self._build_proposal_summary(evaluation), max_chars=320)
        rationale_value = compact_text(rationale or self._build_proposal_rationale(evaluation), max_chars=400)
        requested_actions_value = tuple(requested_actions or self._build_requested_actions(evaluation))
        affected_surfaces_value = tuple(affected_surfaces or self._build_affected_surfaces(evaluation))
        expected_benefits_value = tuple(expected_benefits or self._build_expected_benefits(evaluation))
        known_risks_value = tuple(known_risks or self._build_known_risks(evaluation))
        verification_plan_value = tuple(verification_plan or self._build_verification_plan(evaluation))
        rollback_plan_value = tuple(rollback_plan or self._build_rollback_plan(evaluation))
        proposal_fingerprint = stable_id(
            "change_proposal_fingerprint",
            evaluation.candidate_id,
            title_value,
            summary_value,
            rationale_value,
            requested_actions_value,
            affected_surfaces_value,
            expected_benefits_value,
            known_risks_value,
            verification_plan_value,
            rollback_plan_value,
        )

        for existing in existing_versions:
            if existing.proposal_id == proposal_id and existing.proposal_fingerprint == proposal_fingerprint:
                return existing

        latest_version = max((proposal.proposal_version for proposal in existing_versions if proposal.proposal_id == proposal_id), default=0)
        previous_proposal = self.get_change_proposal(proposal_id)
        proposal = ChangeProposal(
            proposal_id=proposal_id,
            candidate_id=evaluation.candidate_id,
            title=title_value,
            summary=summary_value,
            rationale=rationale_value,
            requested_actions=requested_actions_value,
            affected_surfaces=affected_surfaces_value,
            expected_benefits=expected_benefits_value,
            known_risks=known_risks_value,
            verification_plan=verification_plan_value,
            rollback_plan=rollback_plan_value,
            proposal_version=latest_version + 1,
            proposal_fingerprint=proposal_fingerprint,
            status="proposed",
            metadata={
                "actor": compact_text(actor, max_chars=120),
                "candidate_category": evaluation.candidate_category,
                "evaluation_id": evaluation.evaluation_id,
                "inventory_snapshot_id": evaluation.inventory_snapshot_id,
                "overlapping_capability_ids": evaluation.overlapping_capability_ids,
                "capability_gap_ids": evaluation.capability_gap_ids,
                "autonomy_level": self.autonomy_level.value,
            },
        )
        self._persist_record(
            category="change_proposal",
            key=f"evolution:change_proposal:{proposal.proposal_id}:{proposal.proposal_fingerprint}",
            value=proposal.to_dict(),
            metadata={
                "proposal_id": proposal.proposal_id,
                "candidate_id": proposal.candidate_id,
                "proposal_version": proposal.proposal_version,
                "proposal_fingerprint": proposal.proposal_fingerprint,
                "status": proposal.status,
                "autonomy_level": self.autonomy_level.value,
            },
        )
        self._persist_journal_entry(
            proposal_id=proposal.proposal_id,
            event_type="proposal_created" if previous_proposal is None else "proposal_revised",
            previous_state="none"
            if previous_proposal is None
            else f"version:{previous_proposal.proposal_version}:{previous_proposal.proposal_fingerprint}",
            new_state=f"version:{proposal.proposal_version}:{proposal.proposal_fingerprint}",
            actor=actor,
            details={
                "candidate_id": proposal.candidate_id,
                "evaluation_id": evaluation.evaluation_id,
                "proposal_version": proposal.proposal_version,
                "proposal_fingerprint": proposal.proposal_fingerprint,
            },
        )
        self.invalidate_approval_if_proposal_changed(proposal, actor=actor)
        self._record_decision(
            proposal,
            decision="pending",
            actor=actor,
            note="Awaiting explicit approval for this exact proposal fingerprint.",
            metadata={"auto_created": True},
        )
        _emit_log(
            self.logger,
            "info",
            "Created change proposal",
            proposal_id=proposal.proposal_id,
            proposal_version=proposal.proposal_version,
            proposal_fingerprint=proposal.proposal_fingerprint,
        )
        return proposal

    def get_change_proposal(
        self,
        proposal_id: str,
        *,
        proposal_fingerprint: str | None = None,
    ) -> ChangeProposal | None:
        """Return one persisted proposal by logical id and optional exact fingerprint."""

        proposals = [proposal for proposal in self._load_records("change_proposal", ChangeProposal.from_dict) if proposal.proposal_id == proposal_id]
        if proposal_fingerprint is not None:
            for proposal in proposals:
                if proposal.proposal_fingerprint == proposal_fingerprint:
                    return proposal
            return None
        if not proposals:
            return None
        proposals.sort(key=lambda proposal: (proposal.proposal_version, proposal.created_at, proposal.proposal_fingerprint))
        return proposals[-1]

    def list_change_proposals(
        self,
        *,
        candidate_id: str | None = None,
        latest_only: bool = False,
    ) -> tuple[ChangeProposal, ...]:
        """Return persisted change proposals in deterministic order."""

        proposals = self._load_records("change_proposal", ChangeProposal.from_dict)
        if candidate_id is not None:
            proposals = [proposal for proposal in proposals if proposal.candidate_id == candidate_id]
        proposals.sort(key=lambda proposal: (proposal.proposal_id, proposal.proposal_version, proposal.created_at, proposal.proposal_fingerprint))
        if not latest_only:
            return tuple(proposals)

        latest_by_id: dict[str, ChangeProposal] = {}
        for proposal in proposals:
            latest_by_id[proposal.proposal_id] = proposal
        return tuple(latest_by_id[key] for key in sorted(latest_by_id))

    def record_approval_decision(
        self,
        proposal: ChangeProposal | str,
        *,
        actor: str,
        decision_text: str | None = None,
        decision: str | None = None,
        note: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> ApprovalDecision:
        """Persist one approval decision bound to an exact proposal fingerprint."""

        resolved_proposal = self._resolve_proposal(proposal)
        if resolved_proposal is None:
            raise ValueError("A known change proposal is required before recording a decision.")
        current_effective = self.get_effective_approval(resolved_proposal)
        normalized_decision = self._normalize_decision(decision=decision, decision_text=decision_text)
        if decision is None and normalized_decision == "pending" and current_effective is not None and current_effective.decision != "pending":
            return current_effective
        decision_note = compact_text(note or decision_text or "", max_chars=320) or None
        return self._record_decision(
            resolved_proposal,
            decision=normalized_decision,
            actor=actor,
            note=decision_note,
            metadata={
                "session_id": compact_text(session_id or "", max_chars=120) or None,
                "conversation_id": compact_text(conversation_id or "", max_chars=120) or None,
                "decision_text": compact_text(decision_text or "", max_chars=240) or None,
            },
        )

    def get_effective_approval(self, proposal: ChangeProposal | str) -> ApprovalDecision | None:
        """Return the latest effective decision for an exact proposal fingerprint."""

        resolved_proposal = self._resolve_proposal(proposal)
        if resolved_proposal is None:
            return None
        self.invalidate_approval_if_proposal_changed(resolved_proposal, actor="narvis")
        decisions = self._decisions_for_proposal(resolved_proposal)
        if not decisions:
            return None
        decisions.sort(key=lambda item: (item.created_at, item.decision_id))
        return decisions[-1]

    def invalidate_approval_if_proposal_changed(
        self,
        proposal: ChangeProposal | str,
        *,
        actor: str = "narvis",
    ) -> tuple[ApprovalDecision, ...]:
        """Expire prior proposal-version approvals or pending states when a new version supersedes them."""

        resolved_proposal = self._resolve_proposal(proposal)
        if resolved_proposal is None:
            return ()
        current_proposal = self.get_change_proposal(resolved_proposal.proposal_id)
        if current_proposal is None:
            return ()

        latest_by_fingerprint: dict[str, ApprovalDecision] = {}
        all_decisions = self._proposal_decisions_by_id(current_proposal.proposal_id)
        for decision in sorted(all_decisions, key=lambda item: (item.created_at, item.decision_id)):
            latest_by_fingerprint[decision.proposal_fingerprint] = decision

        expired: list[ApprovalDecision] = []
        for fingerprint, latest_decision in latest_by_fingerprint.items():
            if fingerprint == current_proposal.proposal_fingerprint:
                continue
            if latest_decision.decision not in {"approved", "pending"}:
                continue
            expired.append(
                self._record_decision(
                    current_proposal.proposal_id,
                    decision="expired",
                    actor=actor,
                    note=f"Proposal version changed after {latest_decision.decision}; prior decision no longer authorizes the current proposal.",
                    proposal_fingerprint=fingerprint,
                    metadata={
                        "superseded_by_fingerprint": current_proposal.proposal_fingerprint,
                        "superseded_by_version": current_proposal.proposal_version,
                    },
                )
            )
        return tuple(expired)

    def list_change_journal(self, *, proposal_id: str | None = None) -> tuple[ChangeJournalEntry, ...]:
        """Return append-only change journal entries in deterministic order."""

        entries = self._load_records("change_journal", ChangeJournalEntry.from_dict)
        if proposal_id is not None:
            entries = [entry for entry in entries if entry.proposal_id == proposal_id]
        entries.sort(key=lambda entry: (entry.timestamp, entry.journal_entry_id))
        return tuple(entries)

    def create_change_plan(
        self,
        proposal: ChangeProposal | str,
        *,
        actor: str = "narvis",
    ) -> ChangePlan:
        """Create and persist one deterministic non-executing plan for an approved proposal."""

        resolved_proposal = self._resolve_proposal(proposal)
        if resolved_proposal is None:
            raise ValueError("A known change proposal is required before plan creation.")

        approval = self.get_effective_approval(resolved_proposal)
        self._ensure_plan_authorized(resolved_proposal, approval)
        assert approval is not None

        existing_plan = self.get_change_plan_for_proposal(
            resolved_proposal,
            approval_decision_id=approval.decision_id,
        )
        if existing_plan is not None:
            return existing_plan

        evaluation = self._load_evaluation_for_proposal(resolved_proposal)
        plan_id = stable_id(
            "change_plan",
            resolved_proposal.proposal_id,
            resolved_proposal.proposal_fingerprint,
            approval.decision_id,
        )
        blueprints = self._build_plan_blueprints(
            proposal=resolved_proposal,
            approval=approval,
            evaluation=evaluation,
        )
        verification_requirements, recovery_requirements, steps = self._materialize_plan_records(
            plan_id=plan_id,
            proposal=resolved_proposal,
            approval=approval,
            blueprints=blueprints,
        )
        plan_fingerprint = self._build_change_plan_fingerprint(
            proposal=resolved_proposal,
            approval=approval,
            verification_requirements=verification_requirements,
            recovery_requirements=recovery_requirements,
            steps=steps,
        )
        plan = ChangePlan(
            plan_id=plan_id,
            proposal_id=resolved_proposal.proposal_id,
            proposal_fingerprint=resolved_proposal.proposal_fingerprint,
            proposal_version=resolved_proposal.proposal_version,
            approval_decision_id=approval.decision_id,
            approval_state=approval.decision,
            status="planned",
            plan_fingerprint=plan_fingerprint,
            step_ids=tuple(step.step_id for step in steps),
            metadata={
                "actor": compact_text(actor, max_chars=120),
                "autonomy_level": self.autonomy_level.value,
                "candidate_id": resolved_proposal.candidate_id,
                "candidate_category": self._proposal_candidate_category(resolved_proposal, evaluation),
                "evaluation_id": self._proposal_evaluation_id(resolved_proposal),
                "affected_surfaces": resolved_proposal.affected_surfaces,
            },
        )
        for requirement in verification_requirements:
            self._persist_record(
                category="verification_requirement",
                key=f"evolution:verification_requirement:{requirement.requirement_id}",
                value=requirement.to_dict(),
                metadata={
                    "plan_id": requirement.plan_id,
                    "proposal_id": requirement.proposal_id,
                    "step_id": requirement.step_id,
                    "status": requirement.status,
                    "autonomy_level": self.autonomy_level.value,
                },
            )
        for requirement in recovery_requirements:
            self._persist_record(
                category="recovery_requirement",
                key=f"evolution:recovery_requirement:{requirement.recovery_id}",
                value=requirement.to_dict(),
                metadata={
                    "plan_id": requirement.plan_id,
                    "proposal_id": requirement.proposal_id,
                    "step_id": requirement.step_id,
                    "status": requirement.status,
                    "autonomy_level": self.autonomy_level.value,
                },
            )
        for step in steps:
            self._persist_record(
                category="plan_step",
                key=f"evolution:plan_step:{step.step_id}",
                value=step.to_dict(),
                metadata={
                    "plan_id": step.plan_id,
                    "proposal_id": step.proposal_id,
                    "sequence": step.sequence,
                    "action_kind": step.action_kind,
                    "status": step.status,
                    "autonomy_level": self.autonomy_level.value,
                },
            )
        self._persist_record(
            category="change_plan",
            key=f"evolution:change_plan:{plan.plan_id}",
            value=plan.to_dict(),
            metadata={
                "plan_id": plan.plan_id,
                "proposal_id": plan.proposal_id,
                "proposal_fingerprint": plan.proposal_fingerprint,
                "proposal_version": plan.proposal_version,
                "approval_decision_id": plan.approval_decision_id,
                "status": plan.status,
                "autonomy_level": self.autonomy_level.value,
            },
        )
        self._persist_journal_entry(
            proposal_id=resolved_proposal.proposal_id,
            event_type="plan_created",
            previous_state="approved",
            new_state=f"planned:{plan.plan_id}",
            actor=actor,
            details={
                "plan_id": plan.plan_id,
                "plan_fingerprint": plan.plan_fingerprint,
                "approval_decision_id": approval.decision_id,
                "proposal_fingerprint": resolved_proposal.proposal_fingerprint,
                "proposal_version": resolved_proposal.proposal_version,
            },
        )
        _emit_log(
            self.logger,
            "info",
            "Created change plan",
            plan_id=plan.plan_id,
            proposal_id=plan.proposal_id,
            proposal_version=plan.proposal_version,
        )
        return plan

    def get_change_plan(self, plan_id: str) -> ChangePlan | None:
        """Return one persisted change plan by exact plan id."""

        for plan in self._load_records("change_plan", ChangePlan.from_dict):
            if plan.plan_id == plan_id:
                return plan
        return None

    def get_change_plan_for_proposal(
        self,
        proposal: ChangeProposal | str,
        *,
        approval_decision_id: str | None = None,
    ) -> ChangePlan | None:
        """Return the latest plan for one exact proposal fingerprint."""

        resolved_proposal = self._resolve_proposal(proposal)
        if resolved_proposal is None:
            return None
        plans = list(
            self.list_change_plans(
                proposal_id=resolved_proposal.proposal_id,
                proposal_fingerprint=resolved_proposal.proposal_fingerprint,
                approval_decision_id=approval_decision_id,
            )
        )
        if not plans:
            return None
        plans.sort(key=lambda item: (item.created_at, item.plan_id))
        return plans[-1]

    def list_change_plans(
        self,
        *,
        proposal_id: str | None = None,
        proposal_fingerprint: str | None = None,
        approval_decision_id: str | None = None,
    ) -> tuple[ChangePlan, ...]:
        """Return persisted change plans in deterministic order."""

        plans = self._load_records("change_plan", ChangePlan.from_dict)
        if proposal_id is not None:
            plans = [plan for plan in plans if plan.proposal_id == proposal_id]
        if proposal_fingerprint is not None:
            plans = [plan for plan in plans if plan.proposal_fingerprint == proposal_fingerprint]
        if approval_decision_id is not None:
            plans = [plan for plan in plans if plan.approval_decision_id == approval_decision_id]
        plans.sort(
            key=lambda plan: (
                plan.proposal_id,
                plan.proposal_version,
                plan.created_at,
                plan.plan_id,
            )
        )
        return tuple(plans)

    def list_plan_steps(
        self,
        *,
        plan_id: str | None = None,
        proposal_id: str | None = None,
    ) -> tuple[PlanStep, ...]:
        """Return persisted plan steps in deterministic order."""

        steps = self._load_records("plan_step", PlanStep.from_dict)
        if plan_id is not None:
            steps = [step for step in steps if step.plan_id == plan_id]
        if proposal_id is not None:
            steps = [step for step in steps if step.proposal_id == proposal_id]
        steps.sort(key=lambda step: (step.plan_id, step.sequence, step.step_id))
        return tuple(steps)

    def list_verification_requirements(
        self,
        *,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> tuple[VerificationRequirement, ...]:
        """Return persisted verification requirements in deterministic order."""

        requirements = self._load_records("verification_requirement", VerificationRequirement.from_dict)
        if plan_id is not None:
            requirements = [item for item in requirements if item.plan_id == plan_id]
        if step_id is not None:
            requirements = [item for item in requirements if item.step_id == step_id]
        requirements.sort(key=lambda item: (item.plan_id, item.step_id, item.requirement_id))
        return tuple(requirements)

    def list_recovery_requirements(
        self,
        *,
        plan_id: str | None = None,
        step_id: str | None = None,
    ) -> tuple[RecoveryRequirement, ...]:
        """Return persisted recovery requirements in deterministic order."""

        requirements = self._load_records("recovery_requirement", RecoveryRequirement.from_dict)
        if plan_id is not None:
            requirements = [item for item in requirements if item.plan_id == plan_id]
        if step_id is not None:
            requirements = [item for item in requirements if item.step_id == step_id]
        requirements.sort(key=lambda item: (item.plan_id, item.step_id, item.recovery_id))
        return tuple(requirements)

    def create_execution_request(
        self,
        plan: ChangePlan | str,
        *,
        actor: str = "narvis",
    ) -> ExecutionRequest:
        """Create and persist one immutable typed execution request for an exact approved plan."""

        resolved_plan = self._resolve_plan(plan)
        if resolved_plan is None:
            raise ValueError("A known change plan is required before creating an execution request.")
        proposal = self.get_change_proposal(
            resolved_plan.proposal_id,
            proposal_fingerprint=resolved_plan.proposal_fingerprint,
        )
        if proposal is None:
            raise ValueError("The execution request requires the exact proposal revision bound to the plan.")
        approval = self._load_approval_decision(resolved_plan.approval_decision_id)
        self._ensure_execution_request_eligible(
            proposal=proposal,
            plan=resolved_plan,
            approval=approval,
        )
        assert approval is not None

        projected_steps = self._project_execution_steps(plan=resolved_plan, proposal=proposal)
        if any(step.executor_category == "unsupported" for step in projected_steps):
            unsupported_steps = tuple(
                step.plan_step_id
                for step in projected_steps
                if step.executor_category == "unsupported"
            )
            raise ValueError(
                "The current plan contains unsupported or ambiguous execution-step projections and cannot create an execution request."
                f" Unsupported steps: {', '.join(unsupported_steps)}."
            )
        request_fingerprint = self._build_execution_request_fingerprint(
            proposal=proposal,
            plan=resolved_plan,
            approval=approval,
            projected_steps=projected_steps,
            mode="authorize_only",
        )
        request_id = stable_id("execution_request", request_fingerprint)
        existing = self.get_execution_request(request_id)
        if existing is not None:
            self._persist_journal_entry(
                proposal_id=proposal.proposal_id,
                event_type="execution_request_reused",
                previous_state=existing.status,
                new_state=f"request:{existing.request_id}",
                actor=actor,
                details={
                    "request_id": existing.request_id,
                    "request_fingerprint": existing.request_fingerprint,
                    "plan_id": existing.plan_id,
                    "plan_fingerprint": existing.plan_fingerprint,
                    "approval_decision_id": existing.approval_decision_id,
                },
            )
            return existing

        step_requests = self._materialize_execution_step_requests(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            proposal=proposal,
            plan=resolved_plan,
            approval=approval,
            projected_steps=projected_steps,
        )
        request_record = ExecutionRequest(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            plan_id=resolved_plan.plan_id,
            plan_fingerprint=resolved_plan.plan_fingerprint,
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.proposal_fingerprint,
            proposal_version=proposal.proposal_version,
            approval_decision_id=approval.decision_id,
            step_request_ids=tuple(step.step_request_id for step in step_requests),
            mode="authorize_only",
            status="pending_authorization",
            metadata={
                "actor": compact_text(actor, max_chars=120),
                "autonomy_level": self.autonomy_level.value,
                "step_count": len(step_requests),
            },
        )
        for step_request in step_requests:
            self._persist_record(
                category="execution_step_request",
                key=f"evolution:execution_step_request:{step_request.step_request_id}",
                value=step_request.to_dict(),
                metadata={
                    "request_id": step_request.request_id,
                    "plan_id": step_request.plan_id,
                    "proposal_id": step_request.proposal_id,
                    "plan_step_id": step_request.plan_step_id,
                    "sequence": step_request.sequence,
                    "executor_category": step_request.executor_category,
                    "action_kind": step_request.action_kind,
                    "autonomy_level": self.autonomy_level.value,
                },
            )
        self._persist_record(
            category="execution_request",
            key=f"evolution:execution_request:{request_record.request_id}",
            value=request_record.to_dict(),
            metadata={
                "request_id": request_record.request_id,
                "request_fingerprint": request_record.request_fingerprint,
                "plan_id": request_record.plan_id,
                "proposal_id": request_record.proposal_id,
                "proposal_version": request_record.proposal_version,
                "approval_decision_id": request_record.approval_decision_id,
                "mode": request_record.mode,
                "status": request_record.status,
                "autonomy_level": self.autonomy_level.value,
            },
        )
        self._persist_journal_entry(
            proposal_id=proposal.proposal_id,
            event_type="execution_request_created",
            previous_state=resolved_plan.status,
            new_state=f"request:{request_record.request_id}",
            actor=actor,
            details={
                "request_id": request_record.request_id,
                "request_fingerprint": request_record.request_fingerprint,
                "plan_id": request_record.plan_id,
                "plan_fingerprint": request_record.plan_fingerprint,
                "approval_decision_id": request_record.approval_decision_id,
                "mode": request_record.mode,
                "step_count": len(step_requests),
            },
        )
        _emit_log(
            self.logger,
            "info",
            "Created execution request",
            request_id=request_record.request_id,
            plan_id=request_record.plan_id,
            proposal_id=request_record.proposal_id,
        )
        return request_record

    def get_execution_request(self, request_id: str) -> ExecutionRequest | None:
        """Return one persisted execution request by exact request id."""

        for request in self._load_records("execution_request", ExecutionRequest.from_dict):
            if request.request_id == request_id:
                return request
        return None

    def list_execution_requests(
        self,
        *,
        proposal_id: str | None = None,
        plan_id: str | None = None,
    ) -> tuple[ExecutionRequest, ...]:
        """Return persisted execution requests in deterministic order."""

        requests = self._load_records("execution_request", ExecutionRequest.from_dict)
        if proposal_id is not None:
            requests = [item for item in requests if item.proposal_id == proposal_id]
        if plan_id is not None:
            requests = [item for item in requests if item.plan_id == plan_id]
        requests.sort(
            key=lambda item: (
                item.proposal_id,
                item.proposal_version,
                item.plan_id,
                item.created_at,
                item.request_id,
            )
        )
        return tuple(requests)

    def authorize_execution_request(
        self,
        request: ExecutionRequest | str,
        *,
        actor: str = "narvis",
    ) -> ExecutionAuthorization:
        """Immediately revalidate one execution request and persist a non-executing authorization result."""

        resolved_request = self._resolve_execution_request(request)
        if resolved_request is None:
            raise ValueError("A known execution request is required before authorization.")

        validation = self._revalidate_execution_request(resolved_request)
        authorization_fingerprint = self._build_execution_authorization_fingerprint(
            request=resolved_request,
            validation=validation,
        )
        authorization_id = stable_id("execution_authorization", authorization_fingerprint)
        existing = self.get_execution_authorization(authorization_id)
        if existing is not None:
            return existing

        authorization = ExecutionAuthorization(
            authorization_id=authorization_id,
            authorization_fingerprint=authorization_fingerprint,
            request_id=resolved_request.request_id,
            request_fingerprint=resolved_request.request_fingerprint,
            plan_id=resolved_request.plan_id,
            plan_fingerprint=resolved_request.plan_fingerprint,
            proposal_id=resolved_request.proposal_id,
            proposal_fingerprint=resolved_request.proposal_fingerprint,
            proposal_version=resolved_request.proposal_version,
            approval_decision_id=resolved_request.approval_decision_id,
            decision=validation.decision,
            reason_code=validation.reason_code,
            reason=validation.reason,
            host_action_proof="authorization_recorded_without_host_action",
            metadata={
                "actor": compact_text(actor, max_chars=120),
                "autonomy_level": self.autonomy_level.value,
            },
        )
        self._persist_record(
            category="execution_authorization",
            key=f"evolution:execution_authorization:{authorization.authorization_id}",
            value=authorization.to_dict(),
            metadata={
                "authorization_id": authorization.authorization_id,
                "request_id": authorization.request_id,
                "plan_id": authorization.plan_id,
                "proposal_id": authorization.proposal_id,
                "decision": authorization.decision,
                "reason_code": authorization.reason_code,
                "autonomy_level": self.autonomy_level.value,
            },
        )
        self._persist_journal_entry(
            proposal_id=resolved_request.proposal_id,
            event_type="execution_approval_revalidated",
            previous_state=resolved_request.status,
            new_state=validation.decision,
            actor=actor,
            details={
                "authorization_id": authorization.authorization_id,
                "request_id": authorization.request_id,
                "decision": authorization.decision,
                "reason_code": authorization.reason_code,
                "host_action_proof": authorization.host_action_proof,
            },
        )
        self._persist_journal_entry(
            proposal_id=resolved_request.proposal_id,
            event_type=self._authorization_event_type(validation.decision),
            previous_state=resolved_request.status,
            new_state=validation.decision,
            actor=actor,
            details={
                "authorization_id": authorization.authorization_id,
                "authorization_fingerprint": authorization.authorization_fingerprint,
                "request_id": authorization.request_id,
                "decision": authorization.decision,
                "reason_code": authorization.reason_code,
                "reason": authorization.reason,
                "host_action_proof": authorization.host_action_proof,
            },
        )
        _emit_log(
            self.logger,
            "info",
            "Authorized execution request",
            request_id=authorization.request_id,
            decision=authorization.decision,
            reason_code=authorization.reason_code,
        )
        return authorization

    def get_execution_authorization(self, authorization_id: str) -> ExecutionAuthorization | None:
        """Return one persisted execution authorization by exact id."""

        for authorization in self._load_records("execution_authorization", ExecutionAuthorization.from_dict):
            if authorization.authorization_id == authorization_id:
                return authorization
        return None

    def list_execution_authorizations(
        self,
        *,
        request_id: str | None = None,
        proposal_id: str | None = None,
    ) -> tuple[ExecutionAuthorization, ...]:
        """Return persisted execution authorizations in deterministic order."""

        authorizations = self._load_records("execution_authorization", ExecutionAuthorization.from_dict)
        if request_id is not None:
            authorizations = [item for item in authorizations if item.request_id == request_id]
        if proposal_id is not None:
            authorizations = [item for item in authorizations if item.proposal_id == proposal_id]
        authorizations.sort(
            key=lambda item: (
                item.proposal_id,
                item.proposal_version,
                item.request_id,
                item.created_at,
                item.authorization_id,
            )
        )
        return tuple(authorizations)

    def create_verification_run(
        self,
        authorization: ExecutionAuthorization | str,
        *,
        actor: str = "narvis",
    ) -> VerificationRun:
        """Create one durable Phase 5 verification run for the exact current granted authorization."""

        resolved_authorization = self._resolve_execution_authorization(authorization)
        if resolved_authorization is None:
            raise ValueError("A known granted execution authorization is required before creating a verification run.")

        eligibility = self._revalidate_verification_authorization(resolved_authorization)
        if eligibility.decision != "granted":
            raise ValueError(
                "Verification runs require one exact current granted execution authorization. "
                f"Reason: {eligibility.reason_code}."
            )

        assert eligibility.request is not None
        assert eligibility.proposal is not None
        assert eligibility.plan is not None
        assert eligibility.approval is not None

        run_fingerprint = self._build_verification_run_fingerprint(
            authorization=resolved_authorization,
            verification_step_requests=eligibility.verification_step_requests,
        )
        verification_run_id = stable_id("verification_run", run_fingerprint)
        existing = self.get_verification_run(verification_run_id)
        if existing is not None:
            existing_eligibility = self._revalidate_verification_run(existing)
            if existing_eligibility.decision != "granted":
                self._invalidate_verification_run(
                    existing,
                    reason_code=existing_eligibility.reason_code,
                    reason=existing_eligibility.reason,
                    actor=actor,
                )
                raise ValueError(
                    "The existing verification run became stale and was invalidated before it could be reused. "
                    f"Reason: {existing_eligibility.reason_code}."
                )
            self._persist_journal_entry(
                proposal_id=existing.proposal_id,
                event_type="verification_run_reused",
                previous_state=existing.status,
                new_state=f"verification_run:{existing.verification_run_id}",
                actor=actor,
                details={
                    "verification_run_id": existing.verification_run_id,
                    "run_fingerprint": existing.run_fingerprint,
                    "authorization_id": existing.authorization_id,
                    "execution_request_id": existing.execution_request_id,
                    "step_count": len(existing.verification_step_run_ids),
                },
            )
            return existing

        step_runs = self._materialize_verification_step_runs(
            verification_run_id=verification_run_id,
            run_fingerprint=run_fingerprint,
            authorization=resolved_authorization,
            request=eligibility.request,
            proposal=eligibility.proposal,
            plan=eligibility.plan,
            approval=eligibility.approval,
            verification_step_requests=eligibility.verification_step_requests,
            actor=actor,
        )
        created_at = self._now_iso()
        run_record = VerificationRun(
            verification_run_id=verification_run_id,
            run_fingerprint=run_fingerprint,
            authorization_id=resolved_authorization.authorization_id,
            authorization_fingerprint=resolved_authorization.authorization_fingerprint,
            execution_request_id=eligibility.request.request_id,
            request_fingerprint=eligibility.request.request_fingerprint,
            plan_id=eligibility.plan.plan_id,
            plan_fingerprint=eligibility.plan.plan_fingerprint,
            proposal_id=eligibility.proposal.proposal_id,
            proposal_fingerprint=eligibility.proposal.proposal_fingerprint,
            proposal_version=eligibility.proposal.proposal_version,
            approval_decision_id=eligibility.approval.decision_id,
            execution_step_request_ids=tuple(step.execution_step_request_id for step in step_runs),
            verification_step_run_ids=tuple(step.verification_step_run_id for step in step_runs),
            status="pending_start",
            actor=compact_text(actor, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "created_at": created_at,
                    "phase_scope": "evolution.phase5.verification_run",
                    "autonomy_level": self.autonomy_level.value,
                    "step_count": len(step_runs),
                }
            ),
        )
        for step_run in step_runs:
            self._persist_verification_step_run(step_run)
        self._persist_verification_run(run_record)
        self._persist_journal_entry(
            proposal_id=run_record.proposal_id,
            event_type="verification_run_created",
            previous_state=resolved_authorization.decision,
            new_state=run_record.status,
            actor=actor,
            details={
                "verification_run_id": run_record.verification_run_id,
                "run_fingerprint": run_record.run_fingerprint,
                "authorization_id": run_record.authorization_id,
                "execution_request_id": run_record.execution_request_id,
                "step_count": len(step_runs),
            },
        )
        return run_record

    def get_verification_run(self, run_id: str) -> VerificationRun | None:
        """Return one verification run by exact durable id."""

        for run in self._load_records("verification_run", VerificationRun.from_dict):
            if run.verification_run_id == run_id:
                return run
        return None

    def list_verification_runs(
        self,
        *,
        proposal_id: str | None = None,
        execution_request_id: str | None = None,
        authorization_id: str | None = None,
    ) -> tuple[VerificationRun, ...]:
        """Return persisted verification runs in deterministic order."""

        runs = self._load_records("verification_run", VerificationRun.from_dict)
        if proposal_id is not None:
            runs = [item for item in runs if item.proposal_id == proposal_id]
        if execution_request_id is not None:
            runs = [item for item in runs if item.execution_request_id == execution_request_id]
        if authorization_id is not None:
            runs = [item for item in runs if item.authorization_id == authorization_id]
        runs.sort(
            key=lambda item: (
                item.proposal_id,
                item.proposal_version,
                self._metadata_timestamp(item.metadata, "created_at"),
                item.verification_run_id,
            )
        )
        return tuple(runs)

    def get_verification_step_run(self, step_run_id: str) -> VerificationStepRun | None:
        """Return one verification step run by exact durable id."""

        for step_run in self._load_records("verification_step_run", VerificationStepRun.from_dict):
            if step_run.verification_step_run_id == step_run_id:
                return step_run
        return None

    def list_verification_step_runs(
        self,
        *,
        verification_run_id: str | None = None,
        execution_step_request_id: str | None = None,
    ) -> tuple[VerificationStepRun, ...]:
        """Return verification step runs in deterministic order."""

        step_runs = self._load_records("verification_step_run", VerificationStepRun.from_dict)
        if verification_run_id is not None:
            step_runs = [item for item in step_runs if item.verification_run_id == verification_run_id]
        if execution_step_request_id is not None:
            step_runs = [item for item in step_runs if item.execution_step_request_id == execution_step_request_id]
        step_runs.sort(
            key=lambda item: (
                item.verification_run_id,
                item.sequence,
                item.verification_step_run_id,
            )
        )
        return tuple(step_runs)

    def get_verification_observation(self, observation_id: str) -> VerificationObservation | None:
        """Return one verification observation by exact durable id."""

        for observation in self._load_records("verification_observation", VerificationObservation.from_dict):
            if observation.observation_id == observation_id:
                return observation
        return None

    def list_verification_observations(
        self,
        *,
        verification_run_id: str | None = None,
        verification_step_run_id: str | None = None,
    ) -> tuple[VerificationObservation, ...]:
        """Return verification observations in deterministic order."""

        observations = self._load_records("verification_observation", VerificationObservation.from_dict)
        if verification_run_id is not None:
            observations = [item for item in observations if item.verification_run_id == verification_run_id]
        if verification_step_run_id is not None:
            observations = [item for item in observations if item.verification_step_run_id == verification_step_run_id]
        observations.sort(
            key=lambda item: (
                item.verification_run_id,
                item.verification_step_run_id,
                self._metadata_timestamp(item.metadata, "created_at"),
                item.observation_id,
            )
        )
        return tuple(observations)

    def get_verification_outcome(self, outcome_id: str) -> VerificationOutcome | None:
        """Return one verification outcome by exact durable id."""

        for outcome in self._load_records("verification_outcome", VerificationOutcome.from_dict):
            if outcome.verification_outcome_id == outcome_id:
                return outcome
        return None

    def list_verification_outcomes(
        self,
        *,
        verification_run_id: str | None = None,
    ) -> tuple[VerificationOutcome, ...]:
        """Return verification outcomes in deterministic order."""

        outcomes = self._load_records("verification_outcome", VerificationOutcome.from_dict)
        if verification_run_id is not None:
            outcomes = [item for item in outcomes if item.verification_run_id == verification_run_id]
        outcomes.sort(
            key=lambda item: (
                item.verification_run_id,
                self._metadata_timestamp(item.metadata, "created_at"),
                item.verification_outcome_id,
            )
        )
        return tuple(outcomes)

    def start_verification_step(
        self,
        run: VerificationRun | str,
        step_request_id: str,
        *,
        actor: str = "narvis",
    ) -> VerificationStepRun:
        """Start the next legal verification-only step without invoking any host-action surface."""

        resolved_run = self._resolve_verification_run(run)
        if resolved_run is None:
            raise ValueError("A known verification run is required before starting a verification step.")
        if resolved_run.status in _VERIFICATION_RUN_TERMINAL_STATUSES:
            raise ValueError(f"Verification run '{resolved_run.verification_run_id}' is already terminal.")

        eligibility = self._revalidate_verification_run(resolved_run)
        if eligibility.decision != "granted":
            self._invalidate_verification_run(
                resolved_run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            raise ValueError(
                "Verification steps can start only while the exact authorization remains current. "
                f"Reason: {eligibility.reason_code}."
            )

        current_run = self.get_verification_run(resolved_run.verification_run_id) or resolved_run
        step_runs = self.list_verification_step_runs(verification_run_id=current_run.verification_run_id)
        target_step_run = next(
            (item for item in step_runs if item.execution_step_request_id == compact_text(step_request_id, max_chars=120)),
            None,
        )
        if target_step_run is None:
            raise ValueError("The supplied execution step request is not bound to this verification run.")
        if target_step_run.executor_category != "verification_observation":
            raise ValueError("Phase 5 can only start verification_observation step runs.")
        if target_step_run.status != "pending":
            raise ValueError(f"Verification step '{target_step_run.verification_step_run_id}' cannot transition from '{target_step_run.status}' to 'observing'.")

        next_pending = next((item for item in step_runs if item.status not in _VERIFICATION_STEP_TERMINAL_STATUSES), None)
        if next_pending is None or next_pending.verification_step_run_id != target_step_run.verification_step_run_id:
            raise ValueError("Verification step runs must start in their recorded deterministic order.")
        if any(item.status == "observing" for item in step_runs):
            raise ValueError("Only one verification step may observe evidence at a time.")

        now = self._now_iso()
        if current_run.status == "pending_start":
            current_run = replace(
                current_run,
                status="in_progress",
                metadata=self._updated_metadata(
                    current_run.metadata,
                    started_at=current_run.metadata.get("started_at") or now,
                    started_by=current_run.metadata.get("started_by") or compact_text(actor, max_chars=120),
                ),
            )
            self._persist_verification_run(current_run)

        updated_step_run = replace(
            target_step_run,
            status="observing",
            metadata=self._updated_metadata(
                target_step_run.metadata,
                started_at=now,
                started_by=compact_text(actor, max_chars=120),
            ),
        )
        self._persist_verification_step_run(updated_step_run)
        self._persist_journal_entry(
            proposal_id=current_run.proposal_id,
            event_type="verification_step_started",
            previous_state=target_step_run.status,
            new_state=updated_step_run.status,
            actor=actor,
            details={
                "verification_run_id": current_run.verification_run_id,
                "verification_step_run_id": updated_step_run.verification_step_run_id,
                "execution_step_request_id": updated_step_run.execution_step_request_id,
                "sequence": updated_step_run.sequence,
            },
        )
        return updated_step_run

    def record_verification_observation(
        self,
        step_run: VerificationStepRun | str,
        observed_signal: Any,
        status: str,
        metadata: dict[str, Any] | None = None,
        *,
        actor: str = "narvis",
    ) -> VerificationObservation:
        """Persist one safe, non-executing verification observation for an observing step."""

        resolved_step_run = self._resolve_verification_step_run(step_run)
        if resolved_step_run is None:
            raise ValueError("A known verification step run is required before recording an observation.")
        if resolved_step_run.status != "observing":
            raise ValueError(f"Verification observations may only be recorded while a step is observing, not '{resolved_step_run.status}'.")

        run = self.get_verification_run(resolved_step_run.verification_run_id)
        if run is None:
            raise ValueError("The verification run bound to this step no longer exists.")
        eligibility = self._revalidate_verification_run(run)
        if eligibility.decision != "granted":
            self._invalidate_verification_run(
                run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            raise ValueError(
                "Verification observations require a current eligible verification run. "
                f"Reason: {eligibility.reason_code}."
            )

        observation_kind, evidence_payload = self._normalize_verification_observation(observed_signal)
        normalized_status = compact_text(str(status or ""), max_chars=80).lower()
        if not normalized_status:
            raise ValueError("Verification observations require a non-empty observation status.")

        created_at = self._now_iso()
        observation_fingerprint = self._build_verification_observation_fingerprint(
            run=run,
            step_run=resolved_step_run,
            observation_kind=observation_kind,
            evidence=evidence_payload,
            status=normalized_status,
        )
        observation_id = stable_id("verification_observation", observation_fingerprint)
        existing = self.get_verification_observation(observation_id)
        if existing is not None:
            return existing

        observation = VerificationObservation(
            observation_id=observation_id,
            verification_run_id=run.verification_run_id,
            verification_step_run_id=resolved_step_run.verification_step_run_id,
            observation_kind=observation_kind,
            evidence=evidence_payload,
            status=normalized_status,
            observation_fingerprint=observation_fingerprint,
            actor=compact_text(actor, max_chars=120),
            metadata=self._updated_metadata(
                metadata or {},
                created_at=created_at,
                execution_step_request_id=resolved_step_run.execution_step_request_id,
                plan_step_id=resolved_step_run.plan_step_id,
                phase_scope="evolution.phase5.verification_observation",
            ),
        )
        self._persist_verification_observation(observation)
        self._persist_journal_entry(
            proposal_id=run.proposal_id,
            event_type="verification_observation_recorded",
            previous_state=resolved_step_run.status,
            new_state=resolved_step_run.status,
            actor=actor,
            details={
                "verification_run_id": run.verification_run_id,
                "verification_step_run_id": resolved_step_run.verification_step_run_id,
                "observation_id": observation.observation_id,
                "observation_kind": observation.observation_kind,
                "observation_status": observation.status,
            },
        )
        return observation

    def complete_verification_step(
        self,
        step_run: VerificationStepRun | str,
        outcome: str,
        *,
        actor: str = "narvis",
    ) -> VerificationStepRun:
        """Complete one observing verification step without widening into execution."""

        resolved_step_run = self._resolve_verification_step_run(step_run)
        if resolved_step_run is None:
            raise ValueError("A known verification step run is required before completion.")
        if resolved_step_run.status != "observing":
            raise ValueError(f"Verification step '{resolved_step_run.verification_step_run_id}' cannot complete from '{resolved_step_run.status}'.")

        run = self.get_verification_run(resolved_step_run.verification_run_id)
        if run is None:
            raise ValueError("The verification run bound to this step no longer exists.")
        eligibility = self._revalidate_verification_run(run)
        if eligibility.decision != "granted":
            self._invalidate_verification_run(
                run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            raise ValueError(
                "Verification steps may complete only while the run remains current. "
                f"Reason: {eligibility.reason_code}."
            )

        normalized_outcome = compact_text(str(outcome or ""), max_chars=80).lower()
        if normalized_outcome not in _VERIFICATION_STEP_OUTCOMES:
            raise ValueError(f"Unsupported verification step outcome '{outcome}'.")

        observations = self.list_verification_observations(
            verification_step_run_id=resolved_step_run.verification_step_run_id,
        )
        if normalized_outcome == "satisfied" and not self._step_run_has_required_evidence(resolved_step_run, observations):
            raise ValueError("A verification step cannot be marked satisfied without the required recorded evidence.")

        updated_step_run = replace(
            resolved_step_run,
            status=normalized_outcome,
            metadata=self._updated_metadata(
                resolved_step_run.metadata,
                completed_at=self._now_iso(),
                completed_by=compact_text(actor, max_chars=120),
            ),
        )
        self._persist_verification_step_run(updated_step_run)
        self._persist_journal_entry(
            proposal_id=run.proposal_id,
            event_type="verification_step_completed",
            previous_state=resolved_step_run.status,
            new_state=updated_step_run.status,
            actor=actor,
            details={
                "verification_run_id": run.verification_run_id,
                "verification_step_run_id": updated_step_run.verification_step_run_id,
                "execution_step_request_id": updated_step_run.execution_step_request_id,
                "observation_count": len(observations),
            },
        )
        return updated_step_run

    def finalize_verification_run(
        self,
        run: VerificationRun | str,
        *,
        actor: str = "narvis",
    ) -> VerificationOutcome:
        """Finalize one verification run into a durable truthful terminal outcome."""

        resolved_run = self._resolve_verification_run(run)
        if resolved_run is None:
            raise ValueError("A known verification run is required before finalization.")

        eligibility = self._revalidate_verification_run(resolved_run)
        current_run = self.get_verification_run(resolved_run.verification_run_id) or resolved_run
        if eligibility.decision != "granted":
            current_run = self._invalidate_verification_run(
                current_run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            step_runs = self.list_verification_step_runs(verification_run_id=current_run.verification_run_id)
            status = "invalidated"
            reason_code = eligibility.reason_code
        else:
            step_runs = self.list_verification_step_runs(verification_run_id=current_run.verification_run_id)
            if any(
                step.status == "satisfied"
                and not self._step_run_has_required_evidence(
                    step,
                    self.list_verification_observations(verification_step_run_id=step.verification_step_run_id),
                )
                for step in step_runs
            ):
                status = "failed"
                reason_code = "missing_required_evidence"
            else:
                status, reason_code = self._derive_verification_run_outcome(step_runs)

        step_results = self._build_verification_step_results(step_runs)
        outcome_fingerprint = self._build_verification_outcome_fingerprint(
            run=current_run,
            step_results=step_results,
            status=status,
            reason_code=reason_code,
        )
        verification_outcome_id = stable_id("verification_outcome", outcome_fingerprint)
        existing = self.get_verification_outcome(verification_outcome_id)
        if existing is not None:
            if current_run.status not in _VERIFICATION_RUN_TERMINAL_STATUSES or current_run.status != existing.status:
                finalized_run = replace(
                    current_run,
                    status=existing.status,
                    metadata=self._updated_metadata(
                        current_run.metadata,
                        finalized_at=current_run.metadata.get("finalized_at") or self._now_iso(),
                        finalized_by=current_run.metadata.get("finalized_by") or compact_text(actor, max_chars=120),
                        outcome_id=existing.verification_outcome_id,
                        reason_code=existing.reason_code,
                    ),
                )
                self._persist_verification_run(finalized_run)
            return existing

        if current_run.status in _VERIFICATION_RUN_TERMINAL_STATUSES and current_run.status != status:
            raise ValueError(
                "The verification run is already terminal with a different outcome and cannot be finalized again."
            )

        finalized_run = replace(
            current_run,
            status=status,
            metadata=self._updated_metadata(
                current_run.metadata,
                finalized_at=self._now_iso(),
                finalized_by=compact_text(actor, max_chars=120),
                reason_code=reason_code,
            ),
        )
        outcome = VerificationOutcome(
            verification_outcome_id=verification_outcome_id,
            verification_run_id=finalized_run.verification_run_id,
            run_fingerprint=finalized_run.run_fingerprint,
            step_results=step_results,
            status=status,
            reason_code=reason_code,
            outcome_fingerprint=outcome_fingerprint,
            actor=compact_text(actor, max_chars=120),
            metadata=self._updated_metadata(
                {},
                created_at=self._now_iso(),
                phase_scope="evolution.phase5.verification_outcome",
                step_count=len(step_results),
            ),
        )
        finalized_run = replace(
            finalized_run,
            metadata=self._updated_metadata(
                finalized_run.metadata,
                outcome_id=outcome.verification_outcome_id,
            ),
        )
        self._persist_verification_run(finalized_run)
        self._persist_verification_outcome(outcome)
        self._persist_journal_entry(
            proposal_id=finalized_run.proposal_id,
            event_type="verification_run_finalized",
            previous_state=current_run.status,
            new_state=outcome.status,
            actor=actor,
            details={
                "verification_run_id": finalized_run.verification_run_id,
                "verification_outcome_id": outcome.verification_outcome_id,
                "reason_code": outcome.reason_code,
                "step_count": len(step_results),
            },
        )
        return outcome

    def create_recovery_run(
        self,
        verification_outcome: VerificationOutcome | str,
        *,
        actor: str = "narvis",
    ) -> RecoveryRun:
        """Create one durable Phase 6 recovery-readiness run for the exact current verification outcome."""

        resolved_outcome = self._resolve_verification_outcome(verification_outcome)
        if resolved_outcome is None:
            raise ValueError("A known terminal verification outcome is required before creating a recovery run.")

        eligibility = self._revalidate_recovery_outcome(resolved_outcome)
        if eligibility.decision != "granted":
            raise ValueError(
                "Recovery runs require one exact current terminal verification outcome with eligible recovery-preparation steps. "
                f"Reason: {eligibility.reason_code}."
            )

        assert eligibility.verification_outcome is not None
        assert eligibility.verification_run is not None
        assert eligibility.authorization is not None
        assert eligibility.request is not None
        assert eligibility.proposal is not None
        assert eligibility.plan is not None
        assert eligibility.approval is not None

        run_fingerprint = self._build_recovery_run_fingerprint(
            verification_outcome=eligibility.verification_outcome,
            verification_run=eligibility.verification_run,
            authorization=eligibility.authorization,
            request=eligibility.request,
            plan=eligibility.plan,
            proposal=eligibility.proposal,
            approval=eligibility.approval,
            recovery_step_requests=eligibility.recovery_step_requests,
        )
        recovery_run_id = stable_id("recovery_run", run_fingerprint)
        existing = self.get_recovery_run(recovery_run_id)
        if existing is not None:
            existing_eligibility = self._revalidate_recovery_run(existing)
            if existing_eligibility.decision != "granted":
                self._invalidate_recovery_run(
                    existing,
                    reason_code=existing_eligibility.reason_code,
                    reason=existing_eligibility.reason,
                    actor=actor,
                )
                raise ValueError(
                    "The existing recovery run became stale and was invalidated before it could be reused. "
                    f"Reason: {existing_eligibility.reason_code}."
                )
            self._persist_journal_entry(
                proposal_id=existing.proposal_id,
                event_type="recovery_run_reused",
                previous_state=existing.status,
                new_state=f"recovery_run:{existing.recovery_run_id}",
                actor=actor,
                details={
                    "recovery_run_id": existing.recovery_run_id,
                    "run_fingerprint": existing.run_fingerprint,
                    "verification_outcome_id": existing.verification_outcome_id,
                    "verification_run_id": existing.verification_run_id,
                    "step_count": len(existing.recovery_step_run_ids),
                },
            )
            return existing

        step_runs = self._materialize_recovery_step_runs(
            recovery_run_id=recovery_run_id,
            run_fingerprint=run_fingerprint,
            verification_outcome=eligibility.verification_outcome,
            verification_run=eligibility.verification_run,
            authorization=eligibility.authorization,
            request=eligibility.request,
            proposal=eligibility.proposal,
            plan=eligibility.plan,
            approval=eligibility.approval,
            recovery_step_requests=eligibility.recovery_step_requests,
            actor=actor,
        )
        created_at = self._now_iso()
        run_record = RecoveryRun(
            recovery_run_id=recovery_run_id,
            run_fingerprint=run_fingerprint,
            verification_outcome_id=eligibility.verification_outcome.verification_outcome_id,
            verification_outcome_fingerprint=eligibility.verification_outcome.outcome_fingerprint,
            verification_run_id=eligibility.verification_run.verification_run_id,
            verification_run_fingerprint=eligibility.verification_run.run_fingerprint,
            authorization_id=eligibility.authorization.authorization_id,
            authorization_fingerprint=eligibility.authorization.authorization_fingerprint,
            execution_request_id=eligibility.request.request_id,
            request_fingerprint=eligibility.request.request_fingerprint,
            plan_id=eligibility.plan.plan_id,
            plan_fingerprint=eligibility.plan.plan_fingerprint,
            proposal_id=eligibility.proposal.proposal_id,
            proposal_fingerprint=eligibility.proposal.proposal_fingerprint,
            proposal_version=eligibility.proposal.proposal_version,
            approval_decision_id=eligibility.approval.decision_id,
            execution_step_request_ids=tuple(step.execution_step_request_id for step in step_runs),
            recovery_step_run_ids=tuple(step.recovery_step_run_id for step in step_runs),
            status="pending_start",
            actor=compact_text(actor, max_chars=120),
            metadata=sanitize_durable_mapping(
                {
                    "created_at": created_at,
                    "phase_scope": "evolution.phase6.recovery_run",
                    "autonomy_level": self.autonomy_level.value,
                    "step_count": len(step_runs),
                    "verification_outcome_status": eligibility.verification_outcome.status,
                }
            ),
        )
        for step_run in step_runs:
            self._persist_recovery_step_run(step_run)
        self._persist_recovery_run(run_record)
        self._persist_journal_entry(
            proposal_id=run_record.proposal_id,
            event_type="recovery_run_created",
            previous_state=eligibility.verification_outcome.status,
            new_state=run_record.status,
            actor=actor,
            details={
                "recovery_run_id": run_record.recovery_run_id,
                "run_fingerprint": run_record.run_fingerprint,
                "verification_outcome_id": run_record.verification_outcome_id,
                "verification_run_id": run_record.verification_run_id,
                "step_count": len(step_runs),
            },
        )
        return run_record

    def get_recovery_run(self, run_id: str) -> RecoveryRun | None:
        """Return one recovery run by exact durable id."""

        for run in self._load_records("recovery_run", RecoveryRun.from_dict):
            if run.recovery_run_id == run_id:
                return run
        return None

    def list_recovery_runs(
        self,
        *,
        proposal_id: str | None = None,
        verification_outcome_id: str | None = None,
        verification_run_id: str | None = None,
    ) -> tuple[RecoveryRun, ...]:
        """Return persisted recovery runs in deterministic order."""

        runs = self._load_records("recovery_run", RecoveryRun.from_dict)
        if proposal_id is not None:
            runs = [item for item in runs if item.proposal_id == proposal_id]
        if verification_outcome_id is not None:
            runs = [item for item in runs if item.verification_outcome_id == verification_outcome_id]
        if verification_run_id is not None:
            runs = [item for item in runs if item.verification_run_id == verification_run_id]
        runs.sort(
            key=lambda item: (
                item.proposal_id,
                item.proposal_version,
                self._metadata_timestamp(item.metadata, "created_at"),
                item.recovery_run_id,
            )
        )
        return tuple(runs)

    def get_recovery_step_run(self, step_run_id: str) -> RecoveryStepRun | None:
        """Return one recovery step run by exact durable id."""

        for step_run in self._load_records("recovery_step_run", RecoveryStepRun.from_dict):
            if step_run.recovery_step_run_id == step_run_id:
                return step_run
        return None

    def list_recovery_step_runs(
        self,
        *,
        recovery_run_id: str | None = None,
        execution_step_request_id: str | None = None,
    ) -> tuple[RecoveryStepRun, ...]:
        """Return recovery step runs in deterministic order."""

        step_runs = self._load_records("recovery_step_run", RecoveryStepRun.from_dict)
        if recovery_run_id is not None:
            step_runs = [item for item in step_runs if item.recovery_run_id == recovery_run_id]
        if execution_step_request_id is not None:
            step_runs = [item for item in step_runs if item.execution_step_request_id == execution_step_request_id]
        step_runs.sort(
            key=lambda item: (
                item.recovery_run_id,
                item.sequence,
                item.recovery_step_run_id,
            )
        )
        return tuple(step_runs)

    def get_recovery_observation(self, observation_id: str) -> RecoveryObservation | None:
        """Return one recovery observation by exact durable id."""

        for observation in self._load_records("recovery_observation", RecoveryObservation.from_dict):
            if observation.observation_id == observation_id:
                return observation
        return None

    def list_recovery_observations(
        self,
        *,
        recovery_run_id: str | None = None,
        recovery_step_run_id: str | None = None,
    ) -> tuple[RecoveryObservation, ...]:
        """Return recovery observations in deterministic order."""

        observations = self._load_records("recovery_observation", RecoveryObservation.from_dict)
        if recovery_run_id is not None:
            observations = [item for item in observations if item.recovery_run_id == recovery_run_id]
        if recovery_step_run_id is not None:
            observations = [item for item in observations if item.recovery_step_run_id == recovery_step_run_id]
        observations.sort(
            key=lambda item: (
                item.recovery_run_id,
                item.recovery_step_run_id,
                self._metadata_timestamp(item.metadata, "created_at"),
                item.observation_id,
            )
        )
        return tuple(observations)

    def get_recovery_outcome(self, outcome_id: str) -> RecoveryOutcome | None:
        """Return one recovery outcome by exact durable id."""

        for outcome in self._load_records("recovery_outcome", RecoveryOutcome.from_dict):
            if outcome.recovery_outcome_id == outcome_id:
                return outcome
        return None

    def list_recovery_outcomes(
        self,
        *,
        recovery_run_id: str | None = None,
    ) -> tuple[RecoveryOutcome, ...]:
        """Return recovery outcomes in deterministic order."""

        outcomes = self._load_records("recovery_outcome", RecoveryOutcome.from_dict)
        if recovery_run_id is not None:
            outcomes = [item for item in outcomes if item.recovery_run_id == recovery_run_id]
        outcomes.sort(
            key=lambda item: (
                item.recovery_run_id,
                self._metadata_timestamp(item.metadata, "created_at"),
                item.recovery_outcome_id,
            )
        )
        return tuple(outcomes)

    def start_recovery_step(
        self,
        run: RecoveryRun | str,
        step_request_id: str,
        *,
        actor: str = "narvis",
    ) -> RecoveryStepRun:
        """Start the next legal recovery-preparation step without invoking any host-action surface."""

        resolved_run = self._resolve_recovery_run(run)
        if resolved_run is None:
            raise ValueError("A known recovery run is required before starting a recovery step.")
        if resolved_run.status in _RECOVERY_RUN_TERMINAL_STATUSES:
            raise ValueError(f"Recovery run '{resolved_run.recovery_run_id}' is already terminal.")

        eligibility = self._revalidate_recovery_run(resolved_run)
        if eligibility.decision != "granted":
            self._invalidate_recovery_run(
                resolved_run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            raise ValueError(
                "Recovery steps can start only while the exact verification outcome and recovery-step bindings remain current. "
                f"Reason: {eligibility.reason_code}."
            )

        current_run = self.get_recovery_run(resolved_run.recovery_run_id) or resolved_run
        step_runs = self.list_recovery_step_runs(recovery_run_id=current_run.recovery_run_id)
        target_step_run = next(
            (item for item in step_runs if item.execution_step_request_id == compact_text(step_request_id, max_chars=120)),
            None,
        )
        if target_step_run is None:
            raise ValueError("The supplied execution step request is not bound to this recovery run.")
        if target_step_run.executor_category != "recovery_preparation":
            raise ValueError("Phase 6 can only start recovery_preparation step runs.")
        if target_step_run.status != "pending":
            raise ValueError(f"Recovery step '{target_step_run.recovery_step_run_id}' cannot transition from '{target_step_run.status}' to 'preparing'.")

        next_pending = next((item for item in step_runs if item.status not in _RECOVERY_STEP_TERMINAL_STATUSES), None)
        if next_pending is None or next_pending.recovery_step_run_id != target_step_run.recovery_step_run_id:
            raise ValueError("Recovery step runs must start in their recorded deterministic order.")
        if any(item.status == "preparing" for item in step_runs):
            raise ValueError("Only one recovery step may prepare readiness evidence at a time.")

        now = self._now_iso()
        if current_run.status == "pending_start":
            current_run = replace(
                current_run,
                status="in_progress",
                metadata=self._updated_metadata(
                    current_run.metadata,
                    started_at=current_run.metadata.get("started_at") or now,
                    started_by=current_run.metadata.get("started_by") or compact_text(actor, max_chars=120),
                ),
            )
            self._persist_recovery_run(current_run)

        updated_step_run = replace(
            target_step_run,
            status="preparing",
            metadata=self._updated_metadata(
                target_step_run.metadata,
                started_at=now,
                started_by=compact_text(actor, max_chars=120),
            ),
        )
        self._persist_recovery_step_run(updated_step_run)
        self._persist_journal_entry(
            proposal_id=current_run.proposal_id,
            event_type="recovery_step_started",
            previous_state=target_step_run.status,
            new_state=updated_step_run.status,
            actor=actor,
            details={
                "recovery_run_id": current_run.recovery_run_id,
                "recovery_step_run_id": updated_step_run.recovery_step_run_id,
                "execution_step_request_id": updated_step_run.execution_step_request_id,
            },
        )
        return updated_step_run

    def record_recovery_observation(
        self,
        step_run: RecoveryStepRun | str,
        observed_signal: Any,
        status: str,
        metadata: dict[str, Any] | None = None,
        *,
        actor: str = "narvis",
    ) -> RecoveryObservation:
        """Persist one safe, non-executing recovery-readiness observation for a preparing step."""

        resolved_step_run = self._resolve_recovery_step_run(step_run)
        if resolved_step_run is None:
            raise ValueError("A known recovery step run is required before recording an observation.")
        if resolved_step_run.status != "preparing":
            raise ValueError(f"Recovery observations may only be recorded while a step is preparing, not '{resolved_step_run.status}'.")

        run = self.get_recovery_run(resolved_step_run.recovery_run_id)
        if run is None:
            raise ValueError("The recovery run bound to this step no longer exists.")
        eligibility = self._revalidate_recovery_run(run)
        if eligibility.decision != "granted":
            self._invalidate_recovery_run(
                run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            raise ValueError(
                "Recovery observations require a current eligible recovery run. "
                f"Reason: {eligibility.reason_code}."
            )

        observation_kind, evidence_payload = self._normalize_verification_observation(observed_signal)
        normalized_status = compact_text(str(status or ""), max_chars=80).lower()
        if not normalized_status:
            raise ValueError("Recovery observations require a non-empty observation status.")

        created_at = self._now_iso()
        observation_fingerprint = self._build_recovery_observation_fingerprint(
            run=run,
            step_run=resolved_step_run,
            observation_kind=observation_kind,
            evidence=evidence_payload,
            status=normalized_status,
        )
        observation_id = stable_id("recovery_observation", observation_fingerprint)
        existing = self.get_recovery_observation(observation_id)
        if existing is not None:
            return existing

        observation = RecoveryObservation(
            observation_id=observation_id,
            recovery_run_id=run.recovery_run_id,
            recovery_step_run_id=resolved_step_run.recovery_step_run_id,
            observation_kind=observation_kind,
            evidence=evidence_payload,
            status=normalized_status,
            observation_fingerprint=observation_fingerprint,
            actor=compact_text(actor, max_chars=120),
            metadata=self._updated_metadata(
                metadata or {},
                created_at=created_at,
                execution_step_request_id=resolved_step_run.execution_step_request_id,
                plan_step_id=resolved_step_run.plan_step_id,
                phase_scope="evolution.phase6.recovery_observation",
            ),
        )
        self._persist_recovery_observation(observation)
        self._persist_journal_entry(
            proposal_id=run.proposal_id,
            event_type="recovery_observation_recorded",
            previous_state=resolved_step_run.status,
            new_state=resolved_step_run.status,
            actor=actor,
            details={
                "recovery_run_id": run.recovery_run_id,
                "recovery_step_run_id": resolved_step_run.recovery_step_run_id,
                "observation_id": observation.observation_id,
                "observation_kind": observation.observation_kind,
                "observation_status": observation.status,
            },
        )
        return observation

    def complete_recovery_step(
        self,
        step_run: RecoveryStepRun | str,
        outcome: str,
        *,
        actor: str = "narvis",
    ) -> RecoveryStepRun:
        """Complete one preparing recovery step without widening into execution."""

        resolved_step_run = self._resolve_recovery_step_run(step_run)
        if resolved_step_run is None:
            raise ValueError("A known recovery step run is required before completion.")
        if resolved_step_run.status != "preparing":
            raise ValueError(f"Recovery step '{resolved_step_run.recovery_step_run_id}' cannot complete from '{resolved_step_run.status}'.")

        run = self.get_recovery_run(resolved_step_run.recovery_run_id)
        if run is None:
            raise ValueError("The recovery run bound to this step no longer exists.")
        eligibility = self._revalidate_recovery_run(run)
        if eligibility.decision != "granted":
            self._invalidate_recovery_run(
                run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            raise ValueError(
                "Recovery steps may complete only while the run remains current. "
                f"Reason: {eligibility.reason_code}."
            )

        normalized_outcome = compact_text(str(outcome or ""), max_chars=80).lower()
        if normalized_outcome not in _RECOVERY_STEP_OUTCOMES:
            raise ValueError(f"Unsupported recovery step outcome '{outcome}'.")

        observations = self.list_recovery_observations(
            recovery_step_run_id=resolved_step_run.recovery_step_run_id,
        )
        if normalized_outcome == "ready" and not self._recovery_step_run_has_required_evidence(resolved_step_run, observations):
            raise ValueError("A recovery step cannot be marked ready without explicit positive readiness evidence.")
        if normalized_outcome == "blocked" and not observations:
            raise ValueError("A recovery step cannot be marked blocked without at least one recorded precondition or readiness observation.")

        updated_step_run = replace(
            resolved_step_run,
            status=normalized_outcome,
            metadata=self._updated_metadata(
                resolved_step_run.metadata,
                completed_at=self._now_iso(),
                completed_by=compact_text(actor, max_chars=120),
            ),
        )
        self._persist_recovery_step_run(updated_step_run)
        self._persist_journal_entry(
            proposal_id=run.proposal_id,
            event_type="recovery_step_completed",
            previous_state=resolved_step_run.status,
            new_state=updated_step_run.status,
            actor=actor,
            details={
                "recovery_run_id": run.recovery_run_id,
                "recovery_step_run_id": updated_step_run.recovery_step_run_id,
                "execution_step_request_id": updated_step_run.execution_step_request_id,
                "observation_count": len(observations),
            },
        )
        return updated_step_run

    def finalize_recovery_run(
        self,
        run: RecoveryRun | str,
        *,
        actor: str = "narvis",
    ) -> RecoveryOutcome:
        """Finalize one recovery run into a durable truthful terminal readiness outcome."""

        resolved_run = self._resolve_recovery_run(run)
        if resolved_run is None:
            raise ValueError("A known recovery run is required before finalization.")

        eligibility = self._revalidate_recovery_run(resolved_run)
        current_run = self.get_recovery_run(resolved_run.recovery_run_id) or resolved_run
        if eligibility.decision != "granted":
            current_run = self._invalidate_recovery_run(
                current_run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            step_runs = self.list_recovery_step_runs(recovery_run_id=current_run.recovery_run_id)
            status = "invalidated"
            reason_code = eligibility.reason_code
        else:
            step_runs = self.list_recovery_step_runs(recovery_run_id=current_run.recovery_run_id)
            if any(
                step.status == "ready"
                and not self._recovery_step_run_has_required_evidence(
                    step,
                    self.list_recovery_observations(recovery_step_run_id=step.recovery_step_run_id),
                )
                for step in step_runs
            ):
                status = "blocked"
                reason_code = "missing_required_readiness_evidence"
            else:
                status, reason_code = self._derive_recovery_run_outcome(step_runs)

        step_results = self._build_recovery_step_results(step_runs)
        outcome_fingerprint = self._build_recovery_outcome_fingerprint(
            run=current_run,
            step_results=step_results,
            status=status,
            reason_code=reason_code,
        )
        recovery_outcome_id = stable_id("recovery_outcome", outcome_fingerprint)
        existing = self.get_recovery_outcome(recovery_outcome_id)
        if existing is not None:
            if current_run.status not in _RECOVERY_RUN_TERMINAL_STATUSES or current_run.status != existing.status:
                finalized_run = replace(
                    current_run,
                    status=existing.status,
                    metadata=self._updated_metadata(
                        current_run.metadata,
                        finalized_at=current_run.metadata.get("finalized_at") or self._now_iso(),
                        finalized_by=current_run.metadata.get("finalized_by") or compact_text(actor, max_chars=120),
                        outcome_id=existing.recovery_outcome_id,
                        reason_code=existing.reason_code,
                    ),
                )
                self._persist_recovery_run(finalized_run)
            return existing

        if current_run.status in _RECOVERY_RUN_TERMINAL_STATUSES and current_run.status != status:
            raise ValueError(
                "The recovery run is already terminal with a different outcome and cannot be finalized again."
            )

        finalized_run = replace(
            current_run,
            status=status,
            metadata=self._updated_metadata(
                current_run.metadata,
                finalized_at=self._now_iso(),
                finalized_by=compact_text(actor, max_chars=120),
                reason_code=reason_code,
            ),
        )
        outcome = RecoveryOutcome(
            recovery_outcome_id=recovery_outcome_id,
            recovery_run_id=finalized_run.recovery_run_id,
            run_fingerprint=finalized_run.run_fingerprint,
            step_results=step_results,
            status=status,
            reason_code=reason_code,
            outcome_fingerprint=outcome_fingerprint,
            actor=compact_text(actor, max_chars=120),
            metadata=self._updated_metadata(
                {},
                created_at=self._now_iso(),
                phase_scope="evolution.phase6.recovery_outcome",
                step_count=len(step_results),
            ),
        )
        finalized_run = replace(
            finalized_run,
            metadata=self._updated_metadata(
                finalized_run.metadata,
                outcome_id=outcome.recovery_outcome_id,
            ),
        )
        self._persist_recovery_run(finalized_run)
        self._persist_recovery_outcome(outcome)
        self._persist_journal_entry(
            proposal_id=finalized_run.proposal_id,
            event_type="recovery_run_finalized",
            previous_state=current_run.status,
            new_state=outcome.status,
            actor=actor,
            details={
                "recovery_run_id": finalized_run.recovery_run_id,
                "recovery_outcome_id": outcome.recovery_outcome_id,
                "reason_code": outcome.reason_code,
                "step_count": len(step_results),
            },
        )
        return outcome

    def list_mutation_surfaces(self) -> tuple[MutationSurfaceDefinition, ...]:
        """Return the registered Phase 7 mutation surfaces in deterministic order."""

        return self.mutation_surface_registry.list_surfaces()

    def validate_mutation_target(self, target: MutationTarget) -> MutationGuardDecision:
        """Validate one explicit mutation target against the narrow approved mutation surfaces."""

        return self.mutation_guard_service.validate(
            MutationGuardRequest(
                surface_id=self._mutation_surface_id_for_target(target),
                locator=target.locator,
                target_kind=target.target_kind,
                risk_classification=target.risk_classification,
                metadata=target.metadata,
            )
        )

    def select_mutation_executor(self, target: MutationTarget) -> MutationExecutorSelection:
        """Select one Phase 8 executor by typed target category without executing anything."""

        if not isinstance(target, MutationTarget):
            return self._mutation_executor_selection(
                decision="denied",
                mutation_target_id="",
                executor_category="",
                executor_kind="",
                reason_code="invalid_mutation_target",
                reason="Phase 8 executor selection requires one typed MutationTarget.",
            )

        executor_category = compact_text(target.executor_category, max_chars=80).strip().lower()
        binding = _PHASE8_EXECUTOR_BINDINGS.get(executor_category)
        if binding is None:
            return self._mutation_executor_selection(
                decision="denied",
                mutation_target_id=target.mutation_target_id,
                executor_category=executor_category,
                executor_kind="",
                reason_code="executor_category_not_supported",
                reason="No approved Phase 8 executor is registered for this mutation target category.",
            )

        executor_kind, _service_attribute = binding
        return self._mutation_executor_selection(
            decision="selected",
            mutation_target_id=target.mutation_target_id,
            executor_category=executor_category,
            executor_kind=executor_kind,
            reason_code="executor_selected",
            reason="The mutation target maps to one registered Phase 8 executor; selection does not execute it.",
            metadata={"phase_scope": "evolution.phase8.executor_selection"},
        )

    def select_approved_mutation_executor(
        self,
        approval: MutationApproval | str,
        mutation_target_id: str,
    ) -> MutationExecutorSelection:
        """Select one executor only for a target retained by one recorded mutation approval."""

        normalized_target_id = compact_text(mutation_target_id, max_chars=120)
        resolved_approval = self._resolve_known_mutation_approval(approval)
        if resolved_approval is None:
            return self._mutation_executor_selection(
                decision="denied",
                mutation_target_id=normalized_target_id,
                executor_category="",
                executor_kind="",
                reason_code="unknown_mutation_approval",
                reason="Approved executor selection requires one mutation approval recorded by this evolution service.",
            )

        target = next(
            (
                item
                for item in self._targets_for_mutation_approval(resolved_approval)
                if item.mutation_target_id == normalized_target_id
            ),
            None,
        )
        if target is None:
            return self._mutation_executor_selection(
                decision="denied",
                mutation_target_id=normalized_target_id,
                executor_category="",
                executor_kind="",
                reason_code="mutation_target_not_approved",
                reason="The requested mutation target is not part of the exact recorded mutation approval.",
            )

        selection = self.select_mutation_executor(target)
        return replace(
            selection,
            metadata=sanitize_durable_mapping(
                {
                    **selection.metadata,
                    "phase_scope": "evolution.phase8.approved_executor_selection",
                    "mutation_approval_id": resolved_approval.mutation_approval_id,
                }
            ),
        )

    def simulate_approved_phase8_mutation(
        self,
        request: Phase8MutationExecutionRequest,
    ) -> Phase8MutationExecutionResult:
        """Explicitly simulate one approval-bound Phase 8 executor without changing host state."""

        if not isinstance(request, Phase8MutationExecutionRequest):
            return self._reject_phase8_mutation_execution(
                reason_code="invalid_phase8_request",
                reason="Phase 8 simulation requires one typed Phase8MutationExecutionRequest.",
            )

        resolved_approval = self._resolve_known_mutation_approval(request.mutation_approval)
        if resolved_approval is None:
            return self._reject_phase8_mutation_execution(
                reason_code="unknown_mutation_approval",
                reason="Phase 8 simulation requires one mutation approval recorded by this evolution service.",
            )

        mutation_run_id = compact_text(str(resolved_approval.metadata.get("mutation_run_id", "")), max_chars=120)
        mutation_target_id = compact_text(request.mutation_target_id, max_chars=120)
        approval_mode = compact_text(resolved_approval.mode, max_chars=80).strip().lower()
        if approval_mode != "apply":
            return self._reject_phase8_mutation_execution(
                approval=resolved_approval,
                mutation_run_id=mutation_run_id,
                mutation_target_id=mutation_target_id,
                reason_code="mutation_approval_mode_not_supported",
                reason="Phase 8 executor simulation accepts only an exact apply-mode approval until rollback orchestration is explicitly integrated.",
                metadata={"mutation_approval_mode": approval_mode},
            )

        targets = self._targets_for_mutation_approval(resolved_approval)
        target = next((item for item in targets if item.mutation_target_id == mutation_target_id), None)
        if target is None:
            return self._reject_phase8_mutation_execution(
                approval=resolved_approval,
                mutation_run_id=mutation_run_id,
                mutation_target_id=mutation_target_id,
                reason_code="mutation_target_not_approved",
                reason="The requested mutation target is not part of the exact recorded mutation approval.",
            )

        selection = self.select_approved_mutation_executor(resolved_approval, mutation_target_id)
        if not selection.selected:
            return self._reject_phase8_mutation_execution(
                approval=resolved_approval,
                mutation_run_id=mutation_run_id,
                mutation_target_id=mutation_target_id,
                executor_kind=selection.executor_kind,
                reason_code=selection.reason_code,
                reason=selection.reason,
            )

        normalized_actor = compact_text(request.actor, max_chars=120) or "narvis"
        try:
            ready_outcome, ready_run, step_request_by_id = self._ensure_ready_recovery_for_mutation(
                resolved_approval.recovery_outcome_id,
                actor=normalized_actor,
            )
            step_request = step_request_by_id.get(target.execution_step_request_id)
            if step_request is None:
                raise ValueError("The approved mutation target no longer matches an execution-step request.")
            self._ensure_mutation_target_matches_step_request(target=target, step_request=step_request)
            guard_decision = self.validate_mutation_target(target)
            if not guard_decision.allowed:
                return self._reject_phase8_mutation_execution(
                    approval=resolved_approval,
                    mutation_run_id=mutation_run_id,
                    mutation_target_id=mutation_target_id,
                    executor_kind=selection.executor_kind,
                    reason_code=guard_decision.reason_code,
                    reason=guard_decision.reason,
                    metadata={"validation_layer": "mutation_guard"},
                )

            approval_request = self._build_mutation_approval_request(
                approval=resolved_approval,
                recovery_outcome=ready_outcome,
                recovery_run=ready_run,
                mutation_targets=targets,
            )
            approval_decision = self.mutation_approval_service.validate_approval(
                resolved_approval,
                approval_request,
                now=utc_now(),
            )
            if not approval_decision.approved:
                return self._reject_phase8_mutation_execution(
                    approval=resolved_approval,
                    mutation_run_id=mutation_run_id,
                    mutation_target_id=mutation_target_id,
                    executor_kind=selection.executor_kind,
                    reason_code=approval_decision.reason_code,
                    reason=approval_decision.reason,
                    metadata={"validation_layer": "mutation_approval_service"},
                )
        except ValueError as error:
            return self._reject_phase8_mutation_execution(
                approval=resolved_approval,
                mutation_run_id=mutation_run_id,
                mutation_target_id=mutation_target_id,
                executor_kind=selection.executor_kind,
                reason_code="approved_mutation_revalidation_failed",
                reason=str(error),
            )

        # SandboxExecutorService can mutate its isolated filesystem, so runtime integration never invokes it.
        if selection.executor_kind == "sandbox":
            return self._reject_phase8_mutation_execution(
                approval=resolved_approval,
                mutation_run_id=mutation_run_id,
                mutation_target_id=mutation_target_id,
                executor_kind=selection.executor_kind,
                reason_code="sandbox_runtime_execution_disabled",
                reason="The runtime selects the sandbox executor but blocks invocation until a later explicitly approved real-execution phase.",
            )

        executor_result = self._simulate_phase8_executor(
            executor_kind=selection.executor_kind,
            target=target,
            operation=request.operation,
            actor=normalized_actor,
            metadata={
                **sanitize_durable_mapping(request.metadata),
                "mutation_run_id": mutation_run_id,
                "phase_scope": "evolution.phase8.executor_simulation",
                "real_mutation_performed": False,
            },
        )
        return Phase8MutationExecutionResult(
            decision=executor_result.decision,
            reason_code=executor_result.reason_code,
            reason=executor_result.reason,
            mutation_approval_id=resolved_approval.mutation_approval_id,
            mutation_run_id=mutation_run_id,
            recovery_outcome_id=resolved_approval.recovery_outcome_id,
            recovery_run_id=resolved_approval.recovery_run_id,
            mutation_target_id=mutation_target_id,
            executor_kind=selection.executor_kind,
            executor_result=executor_result,
            rollback_artifact=executor_result.rollback_artifact,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase8.executor_simulation",
                    "real_mutation_performed": False,
                    "mutation_run_exists": mutation_run_id in self._mutation_runs,
                    "executor_metadata": executor_result.metadata,
                }
            ),
        )

    def record_mutation_approval(
        self,
        recovery_outcome: RecoveryOutcome | str,
        mutation_targets: tuple[MutationTarget, ...] | list[MutationTarget],
        *,
        actor: str = "user",
        mode: str = "apply",
        expires_at: datetime | None = None,
        note: str | None = None,
    ) -> MutationApproval:
        """Record one exact human mutation approval after a ready recovery outcome."""

        normalized_actor = compact_text(actor, max_chars=120)
        if not normalized_actor:
            raise ValueError("A human actor is required before recording mutation approval.")

        current_time = utc_now()
        ready_outcome, ready_run, step_request_by_id = self._ensure_ready_recovery_for_mutation(
            recovery_outcome,
            actor=normalized_actor,
        )
        targets = self._normalize_mutation_targets(mutation_targets)
        if not targets:
            raise ValueError("Mutation approval requires at least one explicit typed mutation target.")

        target_ids = tuple(target.mutation_target_id for target in targets)
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("Mutation approval target ids must be unique within one exact approval scope.")

        execution_step_request_ids: list[str] = []
        for target in targets:
            step_request = step_request_by_id.get(target.execution_step_request_id)
            if step_request is None:
                raise ValueError("Mutation targets must bind to one exact execution-step request from the ready recovery scope.")
            self._ensure_mutation_target_matches_step_request(target=target, step_request=step_request)
            guard_decision = self.validate_mutation_target(target)
            if not guard_decision.allowed:
                raise ValueError(guard_decision.reason)
            execution_step_request_ids.append(step_request.step_request_id)

        normalized_mode = compact_text(mode, max_chars=80).strip().lower()
        approval_expires_at = (
            parse_timestamp(expires_at) if expires_at is not None else current_time + timedelta(hours=1)
        )
        mutation_run_id = self._build_mutation_run_id(
            recovery_outcome=ready_outcome,
            recovery_run=ready_run,
            mutation_targets=targets,
            mode=normalized_mode,
        )
        approval_request = MutationApprovalRequest(
            proposal_id=ready_run.proposal_id,
            mutation_run_id=mutation_run_id,
            approval_decision_id=ready_run.approval_decision_id,
            mutation_target_ids=target_ids,
            expires_at=approval_expires_at,
            actor=normalized_actor,
            recovery_outcome_id=ready_outcome.recovery_outcome_id,
            recovery_outcome_fingerprint=ready_outcome.outcome_fingerprint,
            recovery_run_id=ready_run.recovery_run_id,
            recovery_run_fingerprint=ready_run.run_fingerprint,
            execution_request_id=ready_run.execution_request_id,
            request_fingerprint=ready_run.request_fingerprint,
            plan_id=ready_run.plan_id,
            plan_fingerprint=ready_run.plan_fingerprint,
            proposal_fingerprint=ready_run.proposal_fingerprint,
            proposal_version=ready_run.proposal_version,
            execution_step_request_ids=tuple(execution_step_request_ids),
            mode=normalized_mode,
            note=note,
            metadata={
                "created_at": self._now_iso(),
                "phase_scope": "evolution.phase7.mutation_approval",
                "mutation_target_records": [target.to_dict() for target in targets],
                "real_mutation_performed": False,
            },
        )
        decision = self.mutation_approval_service.record_approval(approval_request, now=current_time)
        if not decision.approved or decision.mutation_approval is None:
            raise ValueError(decision.reason)

        existing = self._mutation_approvals.get(decision.mutation_approval.mutation_approval_id)
        if existing is not None:
            return existing

        self._mutation_approvals[decision.mutation_approval.mutation_approval_id] = decision.mutation_approval
        self._mutation_targets_by_approval[decision.mutation_approval.mutation_approval_id] = targets
        _emit_log(
            self.logger,
            "info",
            "Recorded mutation approval",
            mutation_approval_id=decision.mutation_approval.mutation_approval_id,
            recovery_outcome_id=ready_outcome.recovery_outcome_id,
            target_count=len(targets),
            mode=decision.mutation_approval.mode,
        )
        return decision.mutation_approval

    def get_mutation_approval(self, approval_id: str) -> MutationApproval | None:
        """Return one recorded mutation approval by exact id."""

        return self._mutation_approvals.get(compact_text(approval_id, max_chars=120))

    def list_mutation_approvals(
        self,
        *,
        proposal_id: str | None = None,
        recovery_outcome_id: str | None = None,
    ) -> tuple[MutationApproval, ...]:
        """Return mutation approvals in deterministic order for the current runtime session."""

        approvals = list(self._mutation_approvals.values())
        if proposal_id is not None:
            normalized = compact_text(proposal_id, max_chars=120)
            approvals = [item for item in approvals if item.proposal_id == normalized]
        if recovery_outcome_id is not None:
            normalized = compact_text(recovery_outcome_id, max_chars=120)
            approvals = [item for item in approvals if item.recovery_outcome_id == normalized]
        approvals.sort(key=lambda item: (item.proposal_id, item.created_at, item.mutation_approval_id))
        return tuple(approvals)

    def execute_mutation_run(
        self,
        approval: MutationApproval | str,
        *,
        actor: str = "narvis",
    ) -> MutationOutcome:
        """Execute one approved placeholder mutation run after revalidation."""

        normalized_actor = compact_text(actor, max_chars=120) or "narvis"
        resolved_approval = self._resolve_mutation_approval(approval)
        if resolved_approval is None:
            raise ValueError("A known mutation approval is required before executing a mutation run.")

        ready_outcome, ready_run, step_request_by_id = self._ensure_ready_recovery_for_mutation(
            resolved_approval.recovery_outcome_id,
            actor=normalized_actor,
        )
        targets = self._targets_for_mutation_approval(resolved_approval)
        if not targets:
            raise ValueError("The mutation approval does not retain any executable mutation targets.")

        for target in targets:
            step_request = step_request_by_id.get(target.execution_step_request_id)
            if step_request is None:
                raise ValueError("The mutation approval no longer matches the exact execution-step request bindings.")
            self._ensure_mutation_target_matches_step_request(target=target, step_request=step_request)
            guard_decision = self.validate_mutation_target(target)
            if not guard_decision.allowed:
                raise ValueError(guard_decision.reason)

        approval_request = self._build_mutation_approval_request(
            approval=resolved_approval,
            recovery_outcome=ready_outcome,
            recovery_run=ready_run,
            mutation_targets=targets,
        )
        approval_decision = self.mutation_approval_service.validate_approval(
            resolved_approval,
            approval_request,
            now=utc_now(),
        )
        if not approval_decision.approved or approval_decision.mutation_approval is None:
            raise ValueError(approval_decision.reason)

        existing_outcome = self._mutation_outcomes_by_run_id.get(approval_decision.mutation_run_id)
        if existing_outcome is not None:
            return existing_outcome

        result = self.mutation_run_service.execute(
            MutationRunRequest(
                approval_decision=approval_decision,
                mutation_targets=targets,
                actor=normalized_actor,
                metadata={
                    "phase_scope": "evolution.phase7.mutation_run",
                    "real_mutation_performed": False,
                },
            ),
            now=utc_now(),
        )
        if result.decision != "executed" or result.mutation_run is None or result.outcome is None:
            raise ValueError(result.reason)

        self._store_mutation_run_result(result)
        _emit_log(
            self.logger,
            "info",
            "Executed placeholder mutation run",
            mutation_run_id=result.mutation_run.mutation_run_id,
            mutation_approval_id=result.mutation_run.mutation_approval_id,
            status=result.outcome.status,
            reason_code=result.outcome.reason_code,
        )
        return result.outcome

    def get_mutation_run(self, run_id: str) -> MutationRun | None:
        """Return one executed placeholder mutation run by exact id."""

        return self._mutation_runs.get(compact_text(run_id, max_chars=120))

    def list_mutation_runs(
        self,
        *,
        proposal_id: str | None = None,
        mutation_approval_id: str | None = None,
    ) -> tuple[MutationRun, ...]:
        """Return mutation runs in deterministic order for the current runtime session."""

        runs = list(self._mutation_runs.values())
        if proposal_id is not None:
            normalized = compact_text(proposal_id, max_chars=120)
            runs = [item for item in runs if item.proposal_id == normalized]
        if mutation_approval_id is not None:
            normalized = compact_text(mutation_approval_id, max_chars=120)
            runs = [item for item in runs if item.mutation_approval_id == normalized]
        runs.sort(key=lambda item: (item.proposal_id, item.mutation_run_id))
        return tuple(runs)

    def get_mutation_step_run(self, step_run_id: str) -> MutationStepRun | None:
        """Return one mutation-step run by exact id."""

        return self._mutation_step_runs.get(compact_text(step_run_id, max_chars=120))

    def list_mutation_step_runs(
        self,
        *,
        mutation_run_id: str | None = None,
        execution_step_request_id: str | None = None,
    ) -> tuple[MutationStepRun, ...]:
        """Return mutation-step runs in deterministic order for the current runtime session."""

        step_runs = list(self._mutation_step_runs.values())
        if mutation_run_id is not None:
            normalized = compact_text(mutation_run_id, max_chars=120)
            step_runs = [item for item in step_runs if item.mutation_run_id == normalized]
        if execution_step_request_id is not None:
            normalized = compact_text(execution_step_request_id, max_chars=120)
            step_runs = [item for item in step_runs if item.execution_step_request_id == normalized]
        step_runs.sort(key=lambda item: (item.mutation_run_id, item.sequence, item.mutation_step_run_id))
        return tuple(step_runs)

    def get_mutation_observation(self, observation_id: str) -> MutationObservation | None:
        """Return one mutation observation by exact id."""

        return self._mutation_observations.get(compact_text(observation_id, max_chars=120))

    def list_mutation_observations(
        self,
        *,
        mutation_run_id: str | None = None,
        mutation_step_run_id: str | None = None,
    ) -> tuple[MutationObservation, ...]:
        """Return mutation observations in deterministic order for the current runtime session."""

        observations = list(self._mutation_observations.values())
        if mutation_run_id is not None:
            normalized = compact_text(mutation_run_id, max_chars=120)
            observations = [item for item in observations if item.mutation_run_id == normalized]
        if mutation_step_run_id is not None:
            normalized = compact_text(mutation_step_run_id, max_chars=120)
            observations = [item for item in observations if item.mutation_step_run_id == normalized]
        observations.sort(key=lambda item: (item.mutation_run_id, item.mutation_step_run_id, item.observation_id))
        return tuple(observations)

    def get_mutation_outcome(self, outcome_id: str) -> MutationOutcome | None:
        """Return one mutation outcome by exact id."""

        return self._mutation_outcomes.get(compact_text(outcome_id, max_chars=120))

    def list_mutation_outcomes(self, *, mutation_run_id: str | None = None) -> tuple[MutationOutcome, ...]:
        """Return mutation outcomes in deterministic order for the current runtime session."""

        outcomes = list(self._mutation_outcomes.values())
        if mutation_run_id is not None:
            normalized = compact_text(mutation_run_id, max_chars=120)
            outcomes = [item for item in outcomes if item.mutation_run_id == normalized]
        outcomes.sort(key=lambda item: (item.mutation_run_id, item.mutation_outcome_id))
        return tuple(outcomes)

    def get_rollback_artifact(self, artifact_id: str) -> RollbackArtifact | None:
        """Return one rollback artifact by exact id."""

        return self._rollback_artifacts.get(compact_text(artifact_id, max_chars=120))

    def list_rollback_artifacts(self, *, mutation_run_id: str | None = None) -> tuple[RollbackArtifact, ...]:
        """Return rollback artifacts in deterministic order for the current runtime session."""

        artifacts = list(self._rollback_artifacts.values())
        if mutation_run_id is not None:
            normalized = compact_text(mutation_run_id, max_chars=120)
            artifacts = [item for item in artifacts if item.mutation_run_id == normalized]
        artifacts.sort(key=lambda item: (item.mutation_run_id, item.mutation_step_run_id, item.rollback_artifact_id))
        return tuple(artifacts)

    def _resolve_recovery_outcome(self, outcome: RecoveryOutcome | str) -> RecoveryOutcome | None:
        """Resolve one recovery outcome reference into the stored durable record when possible."""

        if isinstance(outcome, RecoveryOutcome):
            return self.get_recovery_outcome(outcome.recovery_outcome_id) or outcome
        return self.get_recovery_outcome(str(outcome))

    def _resolve_mutation_approval(self, approval: MutationApproval | str) -> MutationApproval | None:
        """Resolve one mutation approval reference from the current runtime session."""

        if isinstance(approval, MutationApproval):
            return self.get_mutation_approval(approval.mutation_approval_id) or approval
        return self.get_mutation_approval(str(approval))

    def _resolve_known_mutation_approval(self, approval: MutationApproval | str) -> MutationApproval | None:
        """Resolve one approval only when it is durably known to this runtime session."""

        approval_id = approval.mutation_approval_id if isinstance(approval, MutationApproval) else str(approval)
        return self.get_mutation_approval(approval_id)

    def _mutation_executor_selection(
        self,
        *,
        decision: str,
        mutation_target_id: str,
        executor_category: str,
        executor_kind: str,
        reason_code: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> MutationExecutorSelection:
        """Build one typed Phase 8 executor-selection decision."""

        return MutationExecutorSelection(
            decision=compact_text(decision, max_chars=80),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            executor_category=compact_text(executor_category, max_chars=80),
            executor_kind=compact_text(executor_kind, max_chars=80),
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            metadata=sanitize_durable_mapping(metadata or {}),
        )

    def _simulate_phase8_executor(
        self,
        *,
        executor_kind: str,
        target: MutationTarget,
        operation: str,
        actor: str,
        metadata: dict[str, Any],
    ) -> PackageExecutionResult | SourceExecutionResult | PluginExecutionResult | GitExecutionResult:
        """Invoke one placeholder-only Phase 8 executor after all runtime bindings are revalidated."""

        if executor_kind == "package":
            return self.package_executor_service.execute(
                PackageExecutionRequest(
                    mutation_target=target,
                    operation=operation,  # type: ignore[arg-type]
                    actor=actor,
                    metadata=metadata,
                )
            )
        if executor_kind == "source":
            return self.source_executor_service.execute(
                SourceExecutionRequest(
                    mutation_target=target,
                    operation=operation,  # type: ignore[arg-type]
                    actor=actor,
                    metadata=metadata,
                )
            )
        if executor_kind == "plugin":
            return self.plugin_executor_service.execute(
                PluginExecutionRequest(
                    mutation_target=target,
                    operation=operation,  # type: ignore[arg-type]
                    actor=actor,
                    metadata=metadata,
                )
            )
        if executor_kind == "git":
            return self.git_executor_service.execute(
                GitExecutionRequest(
                    mutation_target=target,
                    operation=operation,  # type: ignore[arg-type]
                    actor=actor,
                    metadata=metadata,
                )
            )
        raise ValueError("No placeholder-only Phase 8 executor is registered for the requested target.")

    def _reject_phase8_mutation_execution(
        self,
        *,
        reason_code: str,
        reason: str,
        approval: MutationApproval | None = None,
        mutation_run_id: str = "",
        mutation_target_id: str = "",
        executor_kind: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Phase8MutationExecutionResult:
        """Build one typed fail-closed result for the explicit Phase 8 simulation path."""

        return Phase8MutationExecutionResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            mutation_approval_id=compact_text(approval.mutation_approval_id if approval else "", max_chars=120),
            mutation_run_id=compact_text(mutation_run_id, max_chars=120),
            recovery_outcome_id=compact_text(approval.recovery_outcome_id if approval else "", max_chars=120),
            recovery_run_id=compact_text(approval.recovery_run_id if approval else "", max_chars=120),
            mutation_target_id=compact_text(mutation_target_id, max_chars=120),
            executor_kind=compact_text(executor_kind, max_chars=80),
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase8.executor_simulation",
                    "real_mutation_performed": False,
                    **(metadata or {}),
                }
            ),
        )

    def _ensure_ready_recovery_for_mutation(
        self,
        recovery_outcome: RecoveryOutcome | str,
        *,
        actor: str,
    ) -> tuple[RecoveryOutcome, RecoveryRun, dict[str, ExecutionStepRequest]]:
        """Return the current ready recovery scope required before any mutation-phase work."""

        resolved_outcome = self._resolve_recovery_outcome(recovery_outcome)
        if resolved_outcome is None:
            raise ValueError("A known recovery outcome is required before any mutation-phase work.")
        if resolved_outcome.status != "ready":
            raise ValueError("Phase 7 mutation work requires one recovery outcome with status 'ready'.")

        current_run = self.get_recovery_run(resolved_outcome.recovery_run_id)
        if current_run is None:
            raise ValueError("The recovery run bound to this ready recovery outcome no longer exists.")

        eligibility = self._revalidate_recovery_run(current_run)
        if eligibility.decision != "granted":
            self._invalidate_recovery_run(
                current_run,
                reason_code=eligibility.reason_code,
                reason=eligibility.reason,
                actor=actor,
            )
            raise ValueError(
                "Phase 7 mutation work requires a current exact ready recovery scope. "
                + eligibility.reason
            )

        refreshed_run = self.get_recovery_run(current_run.recovery_run_id) or current_run
        refreshed_outcome = self.get_recovery_outcome(resolved_outcome.recovery_outcome_id) or resolved_outcome
        if refreshed_run.status != "ready" or refreshed_outcome.status != "ready":
            raise ValueError("Phase 7 mutation work begins only after the recovery run is durably ready.")
        if refreshed_run.metadata.get("outcome_id") and refreshed_run.metadata.get("outcome_id") != refreshed_outcome.recovery_outcome_id:
            raise ValueError("The ready recovery run no longer matches the exact recovery outcome binding.")

        step_requests = self._list_execution_step_requests(request_id=refreshed_run.execution_request_id)
        step_request_by_id = {item.step_request_id: item for item in step_requests}
        return refreshed_outcome, refreshed_run, step_request_by_id

    def _revalidate_mutation_approval_for_phase9_planning(
        self,
        approval: MutationApproval,
        *,
        actor: str,
    ) -> tuple[MutationApproval | None, tuple[str, str] | None]:
        """Revalidate a recorded approval and its ready recovery scope without executing a mutation."""

        try:
            ready_outcome, ready_run, step_request_by_id = self._ensure_ready_recovery_for_mutation(
                approval.recovery_outcome_id,
                actor=actor,
            )
            targets = self._targets_for_mutation_approval(approval)
            if not targets:
                raise ValueError("The mutation approval does not retain any exact mutation targets.")
            for target in targets:
                step_request = step_request_by_id.get(target.execution_step_request_id)
                if step_request is None:
                    raise ValueError("The mutation approval no longer matches the exact execution-step request bindings.")
                self._ensure_mutation_target_matches_step_request(target=target, step_request=step_request)
                guard_decision = self.validate_mutation_target(target)
                if not guard_decision.allowed:
                    raise ValueError(guard_decision.reason)
            approval_request = self._build_mutation_approval_request(
                approval=approval,
                recovery_outcome=ready_outcome,
                recovery_run=ready_run,
                mutation_targets=targets,
            )
            approval_decision = self.mutation_approval_service.validate_approval(
                approval,
                approval_request,
                now=utc_now(),
            )
        except ValueError as error:
            return None, ("recovery_outcome_gating_failed", str(error))

        if not approval_decision.approved or approval_decision.mutation_approval is None:
            return None, (approval_decision.reason_code, approval_decision.reason)
        return approval_decision.mutation_approval, None

    def _reject_phase9_planning_pipeline(
        self,
        *,
        reason_code: str,
        reason: str,
        request_id: str = "",
        mutation_approval_id: str = "",
        task_planning_result: TaskPlanningResult | None = None,
        risk_analysis_result: RiskAnalysisResult | None = None,
        scheduler_result: SchedulerResult | None = None,
        workflow_result: WorkflowResult | None = None,
        decision_result: DecisionResult | None = None,
    ) -> Phase9PlanningPipelineResult:
        """Build one fail-closed Phase 9 pipeline result without task or mutation execution."""

        return Phase9PlanningPipelineResult(
            decision="rejected",
            reason_code=compact_text(reason_code, max_chars=120),
            reason=compact_text(reason, max_chars=320),
            request_id=compact_text(request_id, max_chars=120),
            mutation_approval_id=compact_text(mutation_approval_id, max_chars=120),
            task_planning_result=task_planning_result,
            risk_analysis_result=risk_analysis_result,
            scheduler_result=scheduler_result,
            workflow_result=workflow_result,
            decision_result=decision_result,
            metadata=sanitize_durable_mapping(
                {
                    "phase_scope": "evolution.phase9.runtime_pipeline",
                    "execution_performed": False,
                    "executor_invoked": False,
                    "real_mutation_performed": False,
                }
            ),
        )

    def _normalize_mutation_targets(
        self,
        values: tuple[MutationTarget, ...] | list[MutationTarget],
    ) -> tuple[MutationTarget, ...]:
        """Normalize one explicit mutation-target list into a deterministic tuple."""

        if not isinstance(values, list | tuple):
            return ()
        normalized: list[MutationTarget] = []
        for value in values:
            if not isinstance(value, MutationTarget):
                return ()
            normalized.append(value)
        return tuple(normalized)

    def _ensure_mutation_target_matches_step_request(
        self,
        *,
        target: MutationTarget,
        step_request: ExecutionStepRequest,
    ) -> None:
        """Ensure one explicit mutation target still matches its exact execution-step binding."""

        if target.plan_step_id != step_request.plan_step_id:
            raise ValueError("The mutation target no longer matches the exact plan-step binding.")
        if target.execution_step_request_id != step_request.step_request_id:
            raise ValueError("The mutation target no longer matches the exact execution-step request binding.")
        if target.executor_category != step_request.executor_category:
            raise ValueError("The mutation target executor category no longer matches the exact execution-step binding.")
        if target.action_kind != step_request.action_kind:
            raise ValueError("The mutation target action kind no longer matches the exact execution-step binding.")
        if target.risk_classification != step_request.risk_classification:
            raise ValueError("The mutation target risk classification no longer matches the exact execution-step binding.")
        if self._mutation_surface_id_for_target(target) == "unsupported":
            raise ValueError("Only narrow approved mutation surfaces are allowed in Phase 7.")

    def _mutation_surface_id_for_target(self, target: MutationTarget) -> str:
        """Map one mutation target onto the narrow approved mutation surface identifiers."""

        mapping = {
            "sandbox_execution": "sandbox",
            "package_management": "package",
            "plugin_management": "plugin",
            "code_development": "approved_source_file",
        }
        return mapping.get(compact_text(target.executor_category, max_chars=80), "unsupported")

    def _build_mutation_run_id(
        self,
        *,
        recovery_outcome: RecoveryOutcome,
        recovery_run: RecoveryRun,
        mutation_targets: tuple[MutationTarget, ...],
        mode: str,
    ) -> str:
        """Build one deterministic mutation-run id for an exact approved target subset."""

        payload = {
            "recovery_outcome_id": recovery_outcome.recovery_outcome_id,
            "recovery_run_id": recovery_run.recovery_run_id,
            "execution_request_id": recovery_run.execution_request_id,
            "proposal_id": recovery_run.proposal_id,
            "approval_decision_id": recovery_run.approval_decision_id,
            "mode": compact_text(mode, max_chars=80).strip().lower(),
            "mutation_targets": [self._canonical_mutation_target_payload(target) for target in mutation_targets],
        }
        return stable_id("mutation_run", payload)

    def _canonical_mutation_target_payload(self, target: MutationTarget) -> dict[str, Any]:
        """Return one canonical semantic payload for an exact mutation target."""

        return {
            "mutation_target_id": target.mutation_target_id,
            "plan_step_id": target.plan_step_id,
            "execution_step_request_id": target.execution_step_request_id,
            "executor_category": target.executor_category,
            "action_kind": target.action_kind,
            "target_kind": target.target_kind,
            "locator": target.locator,
            "target_fingerprint": target.target_fingerprint,
            "expected_after_fingerprint": target.expected_after_fingerprint,
            "risk_classification": target.risk_classification,
        }

    def _targets_for_mutation_approval(self, approval: MutationApproval) -> tuple[MutationTarget, ...]:
        """Return the exact target list retained for one mutation approval."""

        cached = self._mutation_targets_by_approval.get(approval.mutation_approval_id)
        if cached:
            return cached

        raw_records = approval.metadata.get("mutation_target_records", [])
        if not isinstance(raw_records, list | tuple):
            return ()

        targets: list[MutationTarget] = []
        for item in raw_records:
            if not isinstance(item, dict):
                return ()
            targets.append(MutationTarget.from_dict(dict(item)))
        resolved = tuple(targets)
        if tuple(target.mutation_target_id for target in resolved) != tuple(approval.mutation_target_ids):
            return ()
        if resolved:
            self._mutation_targets_by_approval[approval.mutation_approval_id] = resolved
        return resolved

    def _build_mutation_approval_request(
        self,
        *,
        approval: MutationApproval,
        recovery_outcome: RecoveryOutcome,
        recovery_run: RecoveryRun,
        mutation_targets: tuple[MutationTarget, ...],
    ) -> MutationApprovalRequest:
        """Rebuild one exact mutation approval request from a stored approval record."""

        return MutationApprovalRequest(
            proposal_id=approval.proposal_id,
            mutation_run_id=compact_text(approval.metadata.get("mutation_run_id", ""), max_chars=120),
            approval_decision_id=approval.approval_decision_id,
            mutation_target_ids=tuple(approval.mutation_target_ids),
            expires_at=parse_timestamp(approval.expires_at),
            actor=approval.actor,
            recovery_outcome_id=recovery_outcome.recovery_outcome_id,
            recovery_outcome_fingerprint=approval.recovery_outcome_fingerprint or recovery_outcome.outcome_fingerprint,
            recovery_run_id=recovery_run.recovery_run_id,
            recovery_run_fingerprint=approval.recovery_run_fingerprint or recovery_run.run_fingerprint,
            execution_request_id=recovery_run.execution_request_id,
            request_fingerprint=recovery_run.request_fingerprint,
            plan_id=recovery_run.plan_id,
            plan_fingerprint=recovery_run.plan_fingerprint,
            proposal_fingerprint=recovery_run.proposal_fingerprint,
            proposal_version=recovery_run.proposal_version,
            execution_step_request_ids=tuple(target.execution_step_request_id for target in mutation_targets),
            mode=approval.mode,
            note=approval.note,
            metadata=approval.metadata,
        )

    def _store_mutation_run_result(self, result: MutationRunResult) -> None:
        """Store one placeholder mutation-run result in the current runtime session ledger."""

        if result.mutation_run is None or result.outcome is None:
            return
        self._mutation_runs[result.mutation_run.mutation_run_id] = result.mutation_run
        for step_run in result.step_runs:
            self._mutation_step_runs[step_run.mutation_step_run_id] = step_run
        for observation in result.observations:
            self._mutation_observations[observation.observation_id] = observation
        for artifact in result.rollback_artifacts:
            self._rollback_artifacts[artifact.rollback_artifact_id] = artifact
        self._mutation_outcomes[result.outcome.mutation_outcome_id] = result.outcome
        self._mutation_outcomes_by_run_id[result.outcome.mutation_run_id] = result.outcome

    def _resolve_plan(self, plan: ChangePlan | str) -> ChangePlan | None:
        """Resolve a plan reference into one persisted change plan."""

        if isinstance(plan, ChangePlan):
            return plan
        return self.get_change_plan(str(plan))

    def _resolve_execution_request(self, request: ExecutionRequest | str) -> ExecutionRequest | None:
        """Resolve an execution request reference into one persisted request."""

        if isinstance(request, ExecutionRequest):
            return request
        return self.get_execution_request(str(request))

    def _resolve_execution_authorization(self, authorization: ExecutionAuthorization | str) -> ExecutionAuthorization | None:
        """Resolve one execution authorization reference into the stored durable record when possible."""

        if isinstance(authorization, ExecutionAuthorization):
            return self.get_execution_authorization(authorization.authorization_id) or authorization
        return self.get_execution_authorization(str(authorization))

    def _resolve_verification_run(self, run: VerificationRun | str) -> VerificationRun | None:
        """Resolve one verification run reference into the stored durable record when possible."""

        if isinstance(run, VerificationRun):
            return self.get_verification_run(run.verification_run_id) or run
        return self.get_verification_run(str(run))

    def _resolve_verification_step_run(self, step_run: VerificationStepRun | str) -> VerificationStepRun | None:
        """Resolve one verification step-run reference into the stored durable record when possible."""

        if isinstance(step_run, VerificationStepRun):
            return self.get_verification_step_run(step_run.verification_step_run_id) or step_run
        return self.get_verification_step_run(str(step_run))

    def _resolve_verification_outcome(self, outcome: VerificationOutcome | str) -> VerificationOutcome | None:
        """Resolve one verification outcome reference into the stored durable record when possible."""

        if isinstance(outcome, VerificationOutcome):
            return self.get_verification_outcome(outcome.verification_outcome_id) or outcome
        return self.get_verification_outcome(str(outcome))

    def _resolve_recovery_run(self, run: RecoveryRun | str) -> RecoveryRun | None:
        """Resolve one recovery run reference into the stored durable record when possible."""

        if isinstance(run, RecoveryRun):
            return self.get_recovery_run(run.recovery_run_id) or run
        return self.get_recovery_run(str(run))

    def _resolve_recovery_step_run(self, step_run: RecoveryStepRun | str) -> RecoveryStepRun | None:
        """Resolve one recovery step-run reference into the stored durable record when possible."""

        if isinstance(step_run, RecoveryStepRun):
            return self.get_recovery_step_run(step_run.recovery_step_run_id) or step_run
        return self.get_recovery_step_run(str(step_run))

    def _load_approval_decision(self, decision_id: str) -> ApprovalDecision | None:
        """Return one approval decision by exact durable decision id."""

        for decision in self._load_records("approval_decision", ApprovalDecision.from_dict):
            if decision.decision_id == decision_id:
                return decision
        return None

    def _list_execution_step_requests(
        self,
        *,
        request_id: str | None = None,
        plan_id: str | None = None,
    ) -> tuple[ExecutionStepRequest, ...]:
        """Return execution-step requests in deterministic order."""

        step_requests = self._load_records("execution_step_request", ExecutionStepRequest.from_dict)
        if request_id is not None:
            step_requests = [item for item in step_requests if item.request_id == request_id]
        if plan_id is not None:
            step_requests = [item for item in step_requests if item.plan_id == plan_id]
        step_requests.sort(key=lambda item: (item.request_id, item.sequence, item.step_request_id))
        return tuple(step_requests)

    def _ensure_execution_request_eligible(
        self,
        *,
        proposal: ChangeProposal,
        plan: ChangePlan,
        approval: ApprovalDecision | None,
    ) -> None:
        """Raise when one approved plan cannot safely create an execution request."""

        current_proposal = self.get_change_proposal(proposal.proposal_id)
        if current_proposal is None or current_proposal.proposal_fingerprint != proposal.proposal_fingerprint:
            raise ValueError("Only the current proposal revision may create an execution request.")
        if current_proposal.proposal_version != proposal.proposal_version:
            raise ValueError("Execution requests require the current proposal version.")
        current_plan = self.get_change_plan(plan.plan_id)
        if current_plan is None:
            raise ValueError("Execution requests require an existing persisted change plan.")
        if current_plan.proposal_id != proposal.proposal_id or current_plan.proposal_fingerprint != proposal.proposal_fingerprint:
            raise ValueError("The execution request plan does not belong to the exact approved proposal revision.")
        if current_plan.proposal_version != proposal.proposal_version:
            raise ValueError("The execution request plan is not bound to the current proposal version.")
        if approval is None:
            raise ValueError("Execution requests require an exact approved decision bound to the plan.")
        self._ensure_plan_authorized(proposal, approval)
        if approval.decision_id != plan.approval_decision_id:
            raise ValueError("The bound approval decision does not match the supplied plan.")
        effective_approval = self.get_effective_approval(proposal)
        if effective_approval is None:
            raise ValueError("Execution requests require a current effective approval.")
        if effective_approval.decision != "approved":
            raise ValueError(f"Execution requests require a current approved decision, not '{effective_approval.decision}'.")
        if effective_approval.decision_id != approval.decision_id:
            raise ValueError("Execution requests require the current effective approval decision bound to the plan.")
        verification_requirements = self.list_verification_requirements(plan_id=plan.plan_id)
        recovery_requirements = self.list_recovery_requirements(plan_id=plan.plan_id)
        steps = self.list_plan_steps(plan_id=plan.plan_id)
        recomputed_fingerprint = self._build_change_plan_fingerprint(
            proposal=proposal,
            approval=approval,
            verification_requirements=verification_requirements,
            recovery_requirements=recovery_requirements,
            steps=steps,
        )
        if current_plan.plan_fingerprint != recomputed_fingerprint or plan.plan_fingerprint != recomputed_fingerprint:
            raise ValueError("Execution requests require a current plan whose fingerprint still matches its persisted steps and requirements.")
        if tuple(step.step_id for step in steps) != plan.step_ids:
            raise ValueError("Execution requests require the exact ordered plan-step bindings recorded on the plan.")

    def _project_execution_steps(
        self,
        *,
        plan: ChangePlan,
        proposal: ChangeProposal,
    ) -> tuple[_ExecutionStepBlueprint, ...]:
        """Project exact plan steps onto one typed, non-executing execution boundary."""

        projected_steps: list[_ExecutionStepBlueprint] = []
        for step in self.list_plan_steps(plan_id=plan.plan_id):
            executor_category = self._project_executor_category(step=step, proposal=proposal)
            projected_steps.append(
                _ExecutionStepBlueprint(
                    plan_step_id=step.step_id,
                    sequence=int(step.sequence),
                    executor_category=executor_category,
                    action_kind=step.action_kind,
                    target=step.target,
                    inputs=dict(step.inputs),
                    risk_classification=step.risk_classification,
                    metadata={
                        key: value
                        for key, value in {
                            "phase": step.metadata.get("phase"),
                            "plan_step_status": step.status,
                        }.items()
                        if value is not None
                    },
                )
            )
        return tuple(projected_steps)

    def _project_executor_category(
        self,
        *,
        step: PlanStep,
        proposal: ChangeProposal,
    ) -> str:
        """Project one plan step onto an explicit executor category without executing it."""

        action_kind = compact_text(step.action_kind, max_chars=80)
        if action_kind == "verification":
            return "verification_observation"
        if action_kind == "recovery":
            return "recovery_preparation"
        if action_kind in {"package_install", "package_remove", "software_install", "software_uninstall"}:
            return "package_management"
        if action_kind in {"source_create", "source_modify", "source_delete"}:
            return "code_development"
        if action_kind == "git_operation":
            return "git_operation"
        if action_kind in {"plugin_install", "plugin_remove"}:
            return "plugin_management"
        if action_kind == "os_configuration":
            return "os_configuration"
        if action_kind in {"application_open", "application_close", "computer_control"}:
            return "computer_control"
        if action_kind == "automation_action":
            return "automation_action"
        if action_kind == "code_execute":
            return "sandbox_execution"
        if action_kind == "service_integration":
            return self._project_service_integration_category(step=step, proposal=proposal)
        return "unsupported"

    def _project_service_integration_category(
        self,
        *,
        step: PlanStep,
        proposal: ChangeProposal,
    ) -> str:
        """Resolve broad service-integration actions onto a narrower executor category or fail closed."""

        candidate_category = compact_text(
            str(step.inputs.get("candidate_category") or proposal.metadata.get("candidate_category", "")),
            max_chars=80,
        ).lower()
        mapping = {
            "sandbox_execution": "sandbox_execution",
            "package_management": "package_management",
            "code_development": "code_development",
            "integration": "plugin_management",
            "computer_control": "computer_control",
            "automation": "automation_action",
        }
        return mapping.get(candidate_category, "unsupported")

    def _materialize_execution_step_requests(
        self,
        *,
        request_id: str,
        request_fingerprint: str,
        proposal: ChangeProposal,
        plan: ChangePlan,
        approval: ApprovalDecision,
        projected_steps: tuple[_ExecutionStepBlueprint, ...],
    ) -> tuple[ExecutionStepRequest, ...]:
        """Materialize one immutable execution-step request sequence from projected plan steps."""

        step_requests: list[ExecutionStepRequest] = []
        for blueprint in projected_steps:
            step_request_id = stable_id(
                "execution_step_request",
                request_fingerprint,
                self._canonical_execution_projection_payload(blueprint),
            )
            step_requests.append(
                ExecutionStepRequest(
                    step_request_id=step_request_id,
                    request_id=request_id,
                    plan_id=plan.plan_id,
                    proposal_id=proposal.proposal_id,
                    plan_step_id=blueprint.plan_step_id,
                    sequence=blueprint.sequence,
                    executor_category=blueprint.executor_category,
                    action_kind=blueprint.action_kind,
                    target=blueprint.target,
                    inputs=dict(blueprint.inputs),
                    risk_classification=blueprint.risk_classification,
                    status="projected",
                    metadata={
                        "proposal_fingerprint": proposal.proposal_fingerprint,
                        "proposal_version": proposal.proposal_version,
                        "plan_fingerprint": plan.plan_fingerprint,
                        "approval_decision_id": approval.decision_id,
                        **{
                            key: value
                            for key, value in dict(blueprint.metadata or {}).items()
                            if value is not None
                        },
                    },
                )
            )
        return tuple(step_requests)

    def _build_execution_request_fingerprint(
        self,
        *,
        proposal: ChangeProposal,
        plan: ChangePlan,
        approval: ApprovalDecision,
        projected_steps: tuple[_ExecutionStepBlueprint | ExecutionStepRequest, ...],
        mode: str,
    ) -> str:
        """Build one deterministic fingerprint from canonical execution-request semantics."""

        payload = self._build_execution_request_fingerprint_payload(
            proposal=proposal,
            plan=plan,
            approval=approval,
            projected_steps=projected_steps,
            mode=mode,
        )
        return stable_id("execution_request_fingerprint", payload)

    def _build_execution_request_fingerprint_payload(
        self,
        *,
        proposal: ChangeProposal,
        plan: ChangePlan,
        approval: ApprovalDecision,
        projected_steps: tuple[_ExecutionStepBlueprint | ExecutionStepRequest, ...],
        mode: str,
    ) -> dict[str, Any]:
        """Return the canonical semantic payload used to fingerprint one execution request."""

        ordered_steps = tuple(
            sorted(
                projected_steps,
                key=lambda item: (
                    int(item.sequence),
                    item.executor_category,
                    item.action_kind,
                    item.target,
                    item.plan_step_id,
                ),
            )
        )
        return {
            "proposal_binding": {
                "proposal_fingerprint": proposal.proposal_fingerprint,
                "proposal_version": int(proposal.proposal_version),
            },
            "plan_binding": {
                "plan_fingerprint": plan.plan_fingerprint,
                "approval_state": plan.approval_state,
            },
            "approval_binding": {
                "proposal_fingerprint": approval.proposal_fingerprint,
                "proposal_version": int(approval.metadata.get("proposal_version", proposal.proposal_version) or proposal.proposal_version),
                "decision": approval.decision,
            },
            "mode": compact_text(mode, max_chars=80),
            "steps": tuple(self._canonical_execution_projection_payload(step) for step in ordered_steps),
        }

    def _build_execution_authorization_fingerprint(
        self,
        *,
        request: ExecutionRequest,
        validation: _ExecutionValidationResult,
    ) -> str:
        """Build one deterministic fingerprint from canonical authorization semantics."""

        payload = self._build_execution_authorization_fingerprint_payload(
            request=request,
            validation=validation,
        )
        return stable_id("execution_authorization_fingerprint", payload)

    def _build_execution_authorization_fingerprint_payload(
        self,
        *,
        request: ExecutionRequest,
        validation: _ExecutionValidationResult,
    ) -> dict[str, Any]:
        """Return the canonical semantic payload used to fingerprint one authorization result."""

        return {
            "request_fingerprint": request.request_fingerprint,
            "plan_binding": {
                "plan_fingerprint": request.plan_fingerprint,
            },
            "proposal_binding": {
                "proposal_fingerprint": request.proposal_fingerprint,
                "proposal_version": int(request.proposal_version),
            },
            "decision": validation.decision,
            "reason_code": validation.reason_code,
            "reason": validation.reason,
            "host_action_proof": "authorization_recorded_without_host_action",
        }

    def _canonical_execution_projection_payload(
        self,
        step: _ExecutionStepBlueprint | ExecutionStepRequest,
    ) -> dict[str, Any]:
        """Return one canonical semantic payload for a projected execution step."""

        return {
            "plan_step_id": getattr(step, "plan_step_id"),
            "sequence": int(getattr(step, "sequence")),
            "executor_category": compact_text(str(getattr(step, "executor_category")), max_chars=80),
            "action_kind": compact_text(str(getattr(step, "action_kind")), max_chars=80),
            "target": compact_text(str(getattr(step, "target")), max_chars=240),
            "inputs": dict(getattr(step, "inputs")),
            "risk_classification": compact_text(str(getattr(step, "risk_classification")), max_chars=80),
        }

    def _revalidate_execution_request(self, request: ExecutionRequest) -> _ExecutionValidationResult:
        """Immediately revalidate one execution request without performing any host action."""

        proposal = self.get_change_proposal(
            request.proposal_id,
            proposal_fingerprint=request.proposal_fingerprint,
        )
        if proposal is None:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="proposal_missing",
                reason="The exact proposal revision bound to this request no longer exists.",
            )
        current_proposal = self.get_change_proposal(request.proposal_id)
        if current_proposal is None:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="proposal_missing",
                reason="The logical proposal referenced by this request no longer exists.",
            )
        if current_proposal.proposal_fingerprint != request.proposal_fingerprint:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="proposal_revision_changed",
                reason="The proposal fingerprint changed after this execution request was created.",
                proposal=current_proposal,
            )
        if current_proposal.proposal_version != request.proposal_version:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="proposal_version_changed",
                reason="The proposal version changed after this execution request was created.",
                proposal=current_proposal,
            )

        plan = self.get_change_plan(request.plan_id)
        if plan is None:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="plan_missing",
                reason="The exact plan bound to this execution request no longer exists.",
                proposal=proposal,
            )
        if plan.proposal_id != request.proposal_id or plan.proposal_fingerprint != request.proposal_fingerprint:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="plan_proposal_binding_mismatch",
                reason="The stored plan no longer belongs to the proposal revision bound to this request.",
                proposal=proposal,
                plan=plan,
            )
        if plan.proposal_version != request.proposal_version:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="plan_proposal_version_mismatch",
                reason="The stored plan no longer belongs to the proposal version bound to this request.",
                proposal=proposal,
                plan=plan,
            )
        if plan.approval_decision_id != request.approval_decision_id:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="plan_approval_binding_mismatch",
                reason="The stored plan no longer references the approval decision bound to this request.",
                proposal=proposal,
                plan=plan,
            )

        approval = self._load_approval_decision(request.approval_decision_id)
        if approval is None:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="approval_record_missing",
                reason="The exact approval decision bound to this request no longer exists.",
                proposal=proposal,
                plan=plan,
            )
        if approval.proposal_id != request.proposal_id or approval.proposal_fingerprint != request.proposal_fingerprint:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="approval_binding_mismatch",
                reason="The approval decision no longer matches the proposal revision bound to this request.",
                proposal=proposal,
                plan=plan,
                approval=approval,
            )
        approval_version = int(approval.metadata.get("proposal_version", request.proposal_version) or request.proposal_version)
        if approval_version != request.proposal_version:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="approval_version_mismatch",
                reason="The approval decision belongs to a different proposal version than this request.",
                proposal=proposal,
                plan=plan,
                approval=approval,
            )

        verification_requirements = self.list_verification_requirements(plan_id=plan.plan_id)
        recovery_requirements = self.list_recovery_requirements(plan_id=plan.plan_id)
        plan_steps = self.list_plan_steps(plan_id=plan.plan_id)
        if tuple(step.step_id for step in plan_steps) != plan.step_ids:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="plan_step_bindings_changed",
                reason="The ordered plan-step bindings changed after this request was created.",
                proposal=proposal,
                plan=plan,
                approval=approval,
            )
        recomputed_plan_fingerprint = self._build_change_plan_fingerprint(
            proposal=proposal,
            approval=approval,
            verification_requirements=verification_requirements,
            recovery_requirements=recovery_requirements,
            steps=plan_steps,
        )
        if plan.plan_fingerprint != recomputed_plan_fingerprint or request.plan_fingerprint != recomputed_plan_fingerprint:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="plan_fingerprint_changed",
                reason="The plan fingerprint changed after this execution request was created.",
                proposal=proposal,
                plan=plan,
                approval=approval,
            )

        projected_steps = self._project_execution_steps(plan=plan, proposal=proposal)
        if any(step.executor_category not in _EXECUTOR_CATEGORY_KEYS or step.executor_category == "unsupported" for step in projected_steps):
            return _ExecutionValidationResult(
                decision="denied",
                reason_code="unsupported_executor_category",
                reason="At least one projected execution step is unsupported or ambiguous, so authorization fails closed.",
                proposal=proposal,
                plan=plan,
                approval=approval,
            )

        stored_step_requests = self._list_execution_step_requests(request_id=request.request_id)
        if tuple(step.step_request_id for step in stored_step_requests) != request.step_request_ids:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="step_request_bindings_changed",
                reason="The stored execution-step request bindings no longer match the request snapshot.",
                proposal=proposal,
                plan=plan,
                approval=approval,
                step_requests=stored_step_requests,
            )
        if len(stored_step_requests) != len(projected_steps):
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="step_request_count_changed",
                reason="The stored execution-step request count no longer matches the current plan projection.",
                proposal=proposal,
                plan=plan,
                approval=approval,
                step_requests=stored_step_requests,
            )
        projected_payloads = tuple(self._canonical_execution_projection_payload(step) for step in projected_steps)
        stored_payloads = tuple(self._canonical_execution_projection_payload(step) for step in stored_step_requests)
        if stored_payloads != projected_payloads:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="step_projection_changed",
                reason="The typed execution-step projection changed after this request was created.",
                proposal=proposal,
                plan=plan,
                approval=approval,
                step_requests=stored_step_requests,
            )

        recomputed_request_fingerprint = self._build_execution_request_fingerprint(
            proposal=proposal,
            plan=plan,
            approval=approval,
            projected_steps=projected_steps,
            mode=request.mode,
        )
        if request.request_fingerprint != recomputed_request_fingerprint:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="request_fingerprint_changed",
                reason="The execution-request fingerprint no longer matches the current exact plan snapshot.",
                proposal=proposal,
                plan=plan,
                approval=approval,
                step_requests=stored_step_requests,
            )

        effective_approval = self.get_effective_approval(proposal)
        if effective_approval is None:
            return _ExecutionValidationResult(
                decision="denied",
                reason_code="approval_missing",
                reason="No effective approval currently authorizes this request.",
                proposal=proposal,
                plan=plan,
                approval=approval,
                step_requests=stored_step_requests,
            )
        if effective_approval.decision == "pending":
            return _ExecutionValidationResult(
                decision="denied",
                reason_code="approval_pending",
                reason="Pending approval cannot authorize execution.",
                proposal=proposal,
                plan=plan,
                approval=effective_approval,
                step_requests=stored_step_requests,
            )
        if effective_approval.decision == "rejected":
            return _ExecutionValidationResult(
                decision="denied",
                reason_code="approval_rejected",
                reason="Rejected approval cannot authorize execution.",
                proposal=proposal,
                plan=plan,
                approval=effective_approval,
                step_requests=stored_step_requests,
            )
        if effective_approval.decision == "expired":
            return _ExecutionValidationResult(
                decision="denied",
                reason_code="approval_expired",
                reason="Expired approval cannot authorize execution.",
                proposal=proposal,
                plan=plan,
                approval=effective_approval,
                step_requests=stored_step_requests,
            )
        if effective_approval.decision != "approved":
            return _ExecutionValidationResult(
                decision="denied",
                reason_code="approval_not_granted",
                reason=f"Approval state '{effective_approval.decision}' does not authorize execution.",
                proposal=proposal,
                plan=plan,
                approval=effective_approval,
                step_requests=stored_step_requests,
            )
        if effective_approval.decision_id != request.approval_decision_id:
            return _ExecutionValidationResult(
                decision="invalidated",
                reason_code="approval_superseded",
                reason="A different effective approval decision is now current for this proposal revision.",
                proposal=proposal,
                plan=plan,
                approval=effective_approval,
                step_requests=stored_step_requests,
            )

        return _ExecutionValidationResult(
            decision="granted",
            reason_code="approved_current_exact_match",
            reason="The execution request still matches the current exact approved plan snapshot and no host action was performed.",
            proposal=proposal,
            plan=plan,
            approval=effective_approval,
            step_requests=stored_step_requests,
        )

    def _revalidate_verification_authorization(
        self,
        authorization: ExecutionAuthorization,
    ) -> _VerificationEligibilityResult:
        """Revalidate one granted authorization before any Phase 5 verification work."""

        if authorization.decision != "granted":
            reason_code = f"authorization_{compact_text(authorization.decision, max_chars=80).lower() or 'not_granted'}"
            return _VerificationEligibilityResult(
                decision="denied",
                reason_code=reason_code,
                reason="Only a granted execution authorization may create or start a Phase 5 verification run.",
                authorization=authorization,
            )

        request = self.get_execution_request(authorization.request_id)
        if request is None:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="request_missing",
                reason="The execution request bound to this authorization no longer exists.",
                authorization=authorization,
            )

        validation = self._revalidate_execution_request(request)
        if validation.decision != "granted":
            return _VerificationEligibilityResult(
                decision=validation.decision,
                reason_code=validation.reason_code,
                reason=validation.reason,
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
                verification_step_requests=tuple(
                    step
                    for step in validation.step_requests
                    if step.executor_category == "verification_observation"
                ),
            )

        assert validation.proposal is not None
        assert validation.plan is not None
        assert validation.approval is not None

        if authorization.request_fingerprint != request.request_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="authorization_request_binding_mismatch",
                reason="The stored authorization no longer matches the exact execution request fingerprint.",
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
            )
        if authorization.plan_id != request.plan_id or authorization.plan_fingerprint != request.plan_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="authorization_plan_binding_mismatch",
                reason="The stored authorization no longer matches the exact plan bound to the execution request.",
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
            )
        if authorization.proposal_id != request.proposal_id or authorization.proposal_fingerprint != request.proposal_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="authorization_proposal_binding_mismatch",
                reason="The stored authorization no longer matches the exact proposal revision bound to the request.",
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
            )
        if authorization.proposal_version != request.proposal_version:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="authorization_proposal_version_mismatch",
                reason="The stored authorization belongs to a different proposal version than the current execution request.",
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
            )
        if authorization.approval_decision_id != request.approval_decision_id:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="authorization_approval_binding_mismatch",
                reason="The stored authorization no longer matches the exact approval decision bound to the request.",
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
            )

        recomputed_authorization_fingerprint = self._build_execution_authorization_fingerprint(
            request=request,
            validation=validation,
        )
        if authorization.authorization_fingerprint != recomputed_authorization_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="stale_authorization",
                reason="The authorization fingerprint no longer matches the current exact revalidation result.",
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
            )

        verification_step_requests = tuple(
            step
            for step in validation.step_requests
            if step.executor_category == "verification_observation"
        )
        if not verification_step_requests:
            return _VerificationEligibilityResult(
                decision="denied",
                reason_code="no_verification_steps",
                reason="Phase 5 can only materialize execution steps whose executor category is exactly verification_observation.",
                authorization=authorization,
                request=request,
                proposal=validation.proposal,
                plan=validation.plan,
                approval=validation.approval,
            )

        return _VerificationEligibilityResult(
            decision="granted",
            reason_code="granted_current_exact_verification_subset",
            reason="The granted authorization still matches the current exact request, and the verification-only step subset remains eligible.",
            authorization=authorization,
            request=request,
            proposal=validation.proposal,
            plan=validation.plan,
            approval=validation.approval,
            verification_step_requests=verification_step_requests,
        )

    def _revalidate_verification_run(self, run: VerificationRun) -> _VerificationEligibilityResult:
        """Revalidate one persisted verification run before it can continue."""

        authorization = self.get_execution_authorization(run.authorization_id)
        if authorization is None:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="authorization_missing",
                reason="The execution authorization bound to this verification run no longer exists.",
            )
        eligibility = self._revalidate_verification_authorization(authorization)
        if eligibility.decision != "granted":
            return eligibility

        assert eligibility.authorization is not None
        assert eligibility.request is not None
        assert eligibility.proposal is not None
        assert eligibility.plan is not None
        assert eligibility.approval is not None

        if run.authorization_fingerprint != eligibility.authorization.authorization_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="authorization_fingerprint_changed",
                reason="The verification run no longer matches the exact authorization fingerprint.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )
        if run.execution_request_id != eligibility.request.request_id or run.request_fingerprint != eligibility.request.request_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_request_binding_changed",
                reason="The verification run no longer matches the exact execution request binding.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )
        if run.plan_id != eligibility.plan.plan_id or run.plan_fingerprint != eligibility.plan.plan_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_plan_binding_changed",
                reason="The verification run no longer matches the exact plan binding.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )
        if (
            run.proposal_id != eligibility.proposal.proposal_id
            or run.proposal_fingerprint != eligibility.proposal.proposal_fingerprint
            or run.proposal_version != eligibility.proposal.proposal_version
        ):
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_proposal_binding_changed",
                reason="The verification run no longer matches the current exact proposal revision.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )
        if run.approval_decision_id != eligibility.approval.decision_id:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_approval_binding_changed",
                reason="The verification run no longer matches the current exact approval decision binding.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )

        step_runs = self.list_verification_step_runs(verification_run_id=run.verification_run_id)
        if tuple(step.execution_step_request_id for step in step_runs) != run.execution_step_request_ids:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_step_bindings_changed",
                reason="The verification run no longer references the exact ordered execution-step bindings it was created with.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )
        if tuple(step.verification_step_run_id for step in step_runs) != run.verification_step_run_ids:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_step_run_bindings_changed",
                reason="The stored verification-step-run bindings no longer match the run snapshot.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )
        if len(step_runs) != len(eligibility.verification_step_requests):
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_step_count_changed",
                reason="The verification-step-run count no longer matches the current verification-only step projection.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )

        recomputed_run_fingerprint = self._build_verification_run_fingerprint(
            authorization=eligibility.authorization,
            verification_step_requests=eligibility.verification_step_requests,
        )
        if run.run_fingerprint != recomputed_run_fingerprint:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_run_fingerprint_changed",
                reason="The verification run fingerprint no longer matches the current exact authorization and verification-step semantics.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )

        allowed_statuses = {"pending", "observing"} | _VERIFICATION_STEP_TERMINAL_STATUSES
        for step_run, step_request in zip(step_runs, eligibility.verification_step_requests):
            if step_run.executor_category != "verification_observation" or step_request.executor_category != "verification_observation":
                return _VerificationEligibilityResult(
                    decision="denied",
                    reason_code="unsupported_executor_category",
                    reason="Phase 5 can continue only verification_observation step runs.",
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    verification_step_requests=eligibility.verification_step_requests,
                )
            if step_run.execution_step_request_id != step_request.step_request_id:
                return _VerificationEligibilityResult(
                    decision="invalidated",
                    reason_code="verification_step_request_binding_changed",
                    reason="A verification step run no longer points at the exact execution-step request it was created from.",
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    verification_step_requests=eligibility.verification_step_requests,
                )
            if step_run.status not in allowed_statuses:
                return _VerificationEligibilityResult(
                    decision="invalidated",
                    reason_code="verification_step_status_invalid",
                    reason="A verification step run entered an unsupported lifecycle state.",
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    verification_step_requests=eligibility.verification_step_requests,
                )
            recomputed_step_run_fingerprint = self._build_verification_step_run_fingerprint(
                run=run,
                step_request=step_request,
            )
            if step_run.step_run_fingerprint != recomputed_step_run_fingerprint:
                return _VerificationEligibilityResult(
                    decision="invalidated",
                    reason_code="verification_step_run_fingerprint_changed",
                    reason="A verification step run fingerprint no longer matches the exact underlying step semantics.",
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    verification_step_requests=eligibility.verification_step_requests,
                )
            if self._canonical_verification_step_run_payload(step_run) != self._canonical_execution_projection_payload(step_request):
                return _VerificationEligibilityResult(
                    decision="invalidated",
                    reason_code="verification_step_payload_changed",
                    reason="A verification step run no longer matches the exact typed execution-step payload it was created from.",
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    verification_step_requests=eligibility.verification_step_requests,
                )

        if run.status not in {"pending_start", "in_progress"} | _VERIFICATION_RUN_TERMINAL_STATUSES:
            return _VerificationEligibilityResult(
                decision="invalidated",
                reason_code="verification_run_status_invalid",
                reason="The verification run entered an unsupported lifecycle state.",
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                verification_step_requests=eligibility.verification_step_requests,
            )

        return eligibility

    def _materialize_verification_step_runs(
        self,
        *,
        verification_run_id: str,
        run_fingerprint: str,
        authorization: ExecutionAuthorization,
        request: ExecutionRequest,
        proposal: ChangeProposal,
        plan: ChangePlan,
        approval: ApprovalDecision,
        verification_step_requests: tuple[ExecutionStepRequest, ...],
        actor: str,
    ) -> tuple[VerificationStepRun, ...]:
        """Materialize one immutable verification-step-run sequence from verification-only step requests."""

        step_runs: list[VerificationStepRun] = []
        created_at = self._now_iso()
        for step_request in verification_step_requests:
            step_run_fingerprint = self._build_verification_step_run_fingerprint(
                run=VerificationRun(
                    verification_run_id=verification_run_id,
                    run_fingerprint=run_fingerprint,
                    authorization_id=authorization.authorization_id,
                    authorization_fingerprint=authorization.authorization_fingerprint,
                    execution_request_id=request.request_id,
                    request_fingerprint=request.request_fingerprint,
                    plan_id=plan.plan_id,
                    plan_fingerprint=plan.plan_fingerprint,
                    proposal_id=proposal.proposal_id,
                    proposal_fingerprint=proposal.proposal_fingerprint,
                    proposal_version=proposal.proposal_version,
                    approval_decision_id=approval.decision_id,
                ),
                step_request=step_request,
            )
            step_runs.append(
                VerificationStepRun(
                    verification_step_run_id=stable_id("verification_step_run", step_run_fingerprint),
                    verification_run_id=verification_run_id,
                    execution_step_request_id=step_request.step_request_id,
                    plan_step_id=step_request.plan_step_id,
                    sequence=step_request.sequence,
                    executor_category=step_request.executor_category,
                    action_kind=step_request.action_kind,
                    target=step_request.target,
                    inputs=dict(step_request.inputs),
                    risk_classification=step_request.risk_classification,
                    step_run_fingerprint=step_run_fingerprint,
                    status="pending",
                    metadata=sanitize_durable_mapping(
                        {
                            "created_at": created_at,
                            "created_by": compact_text(actor, max_chars=120),
                            "phase_scope": "evolution.phase5.verification_step_run",
                            "proposal_fingerprint": proposal.proposal_fingerprint,
                            "proposal_version": proposal.proposal_version,
                            "plan_fingerprint": plan.plan_fingerprint,
                            "request_fingerprint": request.request_fingerprint,
                            "authorization_id": authorization.authorization_id,
                            "authorization_fingerprint": authorization.authorization_fingerprint,
                        }
                    ),
                )
            )
        return tuple(step_runs)

    def _revalidate_recovery_outcome(
        self,
        outcome: VerificationOutcome,
    ) -> _RecoveryEligibilityResult:
        """Revalidate one terminal verification outcome before any Phase 6 recovery-readiness work."""

        if outcome.status not in _VERIFICATION_RUN_TERMINAL_STATUSES:
            return _RecoveryEligibilityResult(
                decision="denied",
                reason_code="verification_outcome_not_terminal",
                reason="Phase 6 recovery runs require one terminal verification outcome.",
            )

        stored_outcome = self.get_verification_outcome(outcome.verification_outcome_id)
        if stored_outcome is None:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="verification_outcome_missing",
                reason="The verification outcome bound to this recovery scope no longer exists.",
            )
        if stored_outcome.outcome_fingerprint != outcome.outcome_fingerprint:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="verification_outcome_binding_changed",
                reason="The supplied verification outcome no longer matches the stored outcome fingerprint.",
            )

        verification_run = self.get_verification_run(stored_outcome.verification_run_id)
        if verification_run is None:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="verification_run_missing",
                reason="The verification run bound to this outcome no longer exists.",
                verification_outcome=stored_outcome,
            )
        if verification_run.run_fingerprint != stored_outcome.run_fingerprint:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="verification_outcome_run_binding_changed",
                reason="The verification outcome no longer matches the exact verification run fingerprint.",
                verification_outcome=stored_outcome,
                verification_run=verification_run,
            )
        if verification_run.status not in _VERIFICATION_RUN_TERMINAL_STATUSES:
            return _RecoveryEligibilityResult(
                decision="denied",
                reason_code="verification_run_not_terminal",
                reason="Recovery readiness requires a terminal verification run snapshot.",
                verification_outcome=stored_outcome,
                verification_run=verification_run,
            )

        verification_eligibility = self._revalidate_verification_run(verification_run)
        if verification_eligibility.decision != "granted":
            return _RecoveryEligibilityResult(
                decision=verification_eligibility.decision,
                reason_code=verification_eligibility.reason_code,
                reason=verification_eligibility.reason,
                verification_outcome=stored_outcome,
                verification_run=verification_run,
                authorization=verification_eligibility.authorization,
                request=verification_eligibility.request,
                proposal=verification_eligibility.proposal,
                plan=verification_eligibility.plan,
                approval=verification_eligibility.approval,
            )

        step_runs = self.list_verification_step_runs(verification_run_id=verification_run.verification_run_id)
        if any(
            step.status == "satisfied"
            and not self._step_run_has_required_evidence(
                step,
                self.list_verification_observations(verification_step_run_id=step.verification_step_run_id),
            )
            for step in step_runs
        ):
            derived_status = "failed"
            derived_reason_code = "missing_required_evidence"
        else:
            derived_status, derived_reason_code = self._derive_verification_run_outcome(step_runs)
        step_results = self._build_verification_step_results(step_runs)
        recomputed_outcome_fingerprint = self._build_verification_outcome_fingerprint(
            run=verification_run,
            step_results=step_results,
            status=derived_status,
            reason_code=derived_reason_code,
        )
        if stored_outcome.outcome_fingerprint != recomputed_outcome_fingerprint:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="verification_outcome_fingerprint_changed",
                reason="The verification outcome no longer matches the current exact verification evidence snapshot.",
                verification_outcome=stored_outcome,
                verification_run=verification_run,
                authorization=verification_eligibility.authorization,
                request=verification_eligibility.request,
                proposal=verification_eligibility.proposal,
                plan=verification_eligibility.plan,
                approval=verification_eligibility.approval,
            )
        if stored_outcome.status != derived_status or stored_outcome.reason_code != derived_reason_code:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="verification_outcome_state_changed",
                reason="The verification outcome no longer matches the current exact terminal verification state.",
                verification_outcome=stored_outcome,
                verification_run=verification_run,
                authorization=verification_eligibility.authorization,
                request=verification_eligibility.request,
                proposal=verification_eligibility.proposal,
                plan=verification_eligibility.plan,
                approval=verification_eligibility.approval,
            )

        assert verification_eligibility.request is not None
        recovery_step_requests = tuple(
            step
            for step in self._list_execution_step_requests(request_id=verification_eligibility.request.request_id)
            if step.executor_category == "recovery_preparation"
        )
        if not recovery_step_requests:
            return _RecoveryEligibilityResult(
                decision="denied",
                reason_code="no_recovery_steps",
                reason="Phase 6 can only materialize recovery_preparation execution steps.",
                verification_outcome=stored_outcome,
                verification_run=verification_run,
                authorization=verification_eligibility.authorization,
                request=verification_eligibility.request,
                proposal=verification_eligibility.proposal,
                plan=verification_eligibility.plan,
                approval=verification_eligibility.approval,
            )

        return _RecoveryEligibilityResult(
            decision="granted",
            reason_code="granted_current_exact_recovery_subset",
            reason="The terminal verification outcome still matches the current exact approved plan snapshot, and the recovery-only step subset remains eligible.",
            verification_outcome=stored_outcome,
            verification_run=verification_run,
            authorization=verification_eligibility.authorization,
            request=verification_eligibility.request,
            proposal=verification_eligibility.proposal,
            plan=verification_eligibility.plan,
            approval=verification_eligibility.approval,
            recovery_step_requests=recovery_step_requests,
        )

    def _revalidate_recovery_run(self, run: RecoveryRun) -> _RecoveryEligibilityResult:
        """Revalidate one persisted recovery run before it can continue."""

        verification_outcome = self.get_verification_outcome(run.verification_outcome_id)
        if verification_outcome is None:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="verification_outcome_missing",
                reason="The verification outcome bound to this recovery run no longer exists.",
            )

        eligibility = self._revalidate_recovery_outcome(verification_outcome)
        if eligibility.decision != "granted":
            return eligibility

        assert eligibility.verification_outcome is not None
        assert eligibility.verification_run is not None
        assert eligibility.authorization is not None
        assert eligibility.request is not None
        assert eligibility.proposal is not None
        assert eligibility.plan is not None
        assert eligibility.approval is not None

        if (
            run.verification_outcome_id != eligibility.verification_outcome.verification_outcome_id
            or run.verification_outcome_fingerprint != eligibility.verification_outcome.outcome_fingerprint
        ):
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_verification_outcome_binding_changed",
                reason="The recovery run no longer matches the exact verification outcome binding.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if (
            run.verification_run_id != eligibility.verification_run.verification_run_id
            or run.verification_run_fingerprint != eligibility.verification_run.run_fingerprint
        ):
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_verification_run_binding_changed",
                reason="The recovery run no longer matches the exact verification run binding.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if (
            run.authorization_id != eligibility.authorization.authorization_id
            or run.authorization_fingerprint != eligibility.authorization.authorization_fingerprint
        ):
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_authorization_binding_changed",
                reason="The recovery run no longer matches the exact execution authorization binding.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if run.execution_request_id != eligibility.request.request_id or run.request_fingerprint != eligibility.request.request_fingerprint:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_request_binding_changed",
                reason="The recovery run no longer matches the exact execution request binding.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if run.plan_id != eligibility.plan.plan_id or run.plan_fingerprint != eligibility.plan.plan_fingerprint:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_plan_binding_changed",
                reason="The recovery run no longer matches the exact plan binding.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if (
            run.proposal_id != eligibility.proposal.proposal_id
            or run.proposal_fingerprint != eligibility.proposal.proposal_fingerprint
            or run.proposal_version != eligibility.proposal.proposal_version
        ):
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_proposal_binding_changed",
                reason="The recovery run no longer matches the current exact proposal revision.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if run.approval_decision_id != eligibility.approval.decision_id:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_approval_binding_changed",
                reason="The recovery run no longer matches the current exact approval decision binding.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )

        step_runs = self.list_recovery_step_runs(recovery_run_id=run.recovery_run_id)
        if tuple(step.execution_step_request_id for step in step_runs) != run.execution_step_request_ids:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_step_bindings_changed",
                reason="The recovery run no longer references the exact ordered execution-step bindings it was created with.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if tuple(step.recovery_step_run_id for step in step_runs) != run.recovery_step_run_ids:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_step_run_bindings_changed",
                reason="The stored recovery-step-run bindings no longer match the run snapshot.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )
        if len(step_runs) != len(eligibility.recovery_step_requests):
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_step_count_changed",
                reason="The recovery-step-run count no longer matches the current recovery-only step projection.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )

        recomputed_run_fingerprint = self._build_recovery_run_fingerprint(
            verification_outcome=eligibility.verification_outcome,
            verification_run=eligibility.verification_run,
            authorization=eligibility.authorization,
            request=eligibility.request,
            plan=eligibility.plan,
            proposal=eligibility.proposal,
            approval=eligibility.approval,
            recovery_step_requests=eligibility.recovery_step_requests,
        )
        if run.run_fingerprint != recomputed_run_fingerprint:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_run_fingerprint_changed",
                reason="The recovery run fingerprint no longer matches the current exact verification and recovery-step semantics.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )

        allowed_statuses = {"pending", "preparing"} | _RECOVERY_STEP_TERMINAL_STATUSES
        for step_run, step_request in zip(step_runs, eligibility.recovery_step_requests):
            if step_run.executor_category != "recovery_preparation" or step_request.executor_category != "recovery_preparation":
                return _RecoveryEligibilityResult(
                    decision="denied",
                    reason_code="unsupported_executor_category",
                    reason="Phase 6 can continue only recovery_preparation step runs.",
                    verification_outcome=eligibility.verification_outcome,
                    verification_run=eligibility.verification_run,
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    recovery_step_requests=eligibility.recovery_step_requests,
                )
            if step_run.execution_step_request_id != step_request.step_request_id:
                return _RecoveryEligibilityResult(
                    decision="invalidated",
                    reason_code="recovery_step_request_binding_changed",
                    reason="A recovery step run no longer points at the exact execution-step request it was created from.",
                    verification_outcome=eligibility.verification_outcome,
                    verification_run=eligibility.verification_run,
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    recovery_step_requests=eligibility.recovery_step_requests,
                )
            if step_run.status not in allowed_statuses:
                return _RecoveryEligibilityResult(
                    decision="invalidated",
                    reason_code="recovery_step_status_invalid",
                    reason="A recovery step run entered an unsupported lifecycle state.",
                    verification_outcome=eligibility.verification_outcome,
                    verification_run=eligibility.verification_run,
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    recovery_step_requests=eligibility.recovery_step_requests,
                )
            recomputed_step_run_fingerprint = self._build_recovery_step_run_fingerprint(
                run=run,
                step_request=step_request,
            )
            if step_run.step_run_fingerprint != recomputed_step_run_fingerprint:
                return _RecoveryEligibilityResult(
                    decision="invalidated",
                    reason_code="recovery_step_run_fingerprint_changed",
                    reason="A recovery step run fingerprint no longer matches the exact underlying step semantics.",
                    verification_outcome=eligibility.verification_outcome,
                    verification_run=eligibility.verification_run,
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    recovery_step_requests=eligibility.recovery_step_requests,
                )
            if self._canonical_recovery_step_run_payload(step_run) != self._canonical_execution_projection_payload(step_request):
                return _RecoveryEligibilityResult(
                    decision="invalidated",
                    reason_code="recovery_step_payload_changed",
                    reason="A recovery step run no longer matches the exact typed execution-step payload it was created from.",
                    verification_outcome=eligibility.verification_outcome,
                    verification_run=eligibility.verification_run,
                    authorization=eligibility.authorization,
                    request=eligibility.request,
                    proposal=eligibility.proposal,
                    plan=eligibility.plan,
                    approval=eligibility.approval,
                    recovery_step_requests=eligibility.recovery_step_requests,
                )

        if run.status not in {"pending_start", "in_progress"} | _RECOVERY_RUN_TERMINAL_STATUSES:
            return _RecoveryEligibilityResult(
                decision="invalidated",
                reason_code="recovery_run_status_invalid",
                reason="The recovery run entered an unsupported lifecycle state.",
                verification_outcome=eligibility.verification_outcome,
                verification_run=eligibility.verification_run,
                authorization=eligibility.authorization,
                request=eligibility.request,
                proposal=eligibility.proposal,
                plan=eligibility.plan,
                approval=eligibility.approval,
                recovery_step_requests=eligibility.recovery_step_requests,
            )

        return eligibility

    def _materialize_recovery_step_runs(
        self,
        *,
        recovery_run_id: str,
        run_fingerprint: str,
        verification_outcome: VerificationOutcome,
        verification_run: VerificationRun,
        authorization: ExecutionAuthorization,
        request: ExecutionRequest,
        proposal: ChangeProposal,
        plan: ChangePlan,
        approval: ApprovalDecision,
        recovery_step_requests: tuple[ExecutionStepRequest, ...],
        actor: str,
    ) -> tuple[RecoveryStepRun, ...]:
        """Materialize one immutable recovery-step-run sequence from recovery-only step requests."""

        step_runs: list[RecoveryStepRun] = []
        created_at = self._now_iso()
        for step_request in recovery_step_requests:
            step_run_fingerprint = self._build_recovery_step_run_fingerprint(
                run=RecoveryRun(
                    recovery_run_id=recovery_run_id,
                    run_fingerprint=run_fingerprint,
                    verification_outcome_id=verification_outcome.verification_outcome_id,
                    verification_outcome_fingerprint=verification_outcome.outcome_fingerprint,
                    verification_run_id=verification_run.verification_run_id,
                    verification_run_fingerprint=verification_run.run_fingerprint,
                    authorization_id=authorization.authorization_id,
                    authorization_fingerprint=authorization.authorization_fingerprint,
                    execution_request_id=request.request_id,
                    request_fingerprint=request.request_fingerprint,
                    plan_id=plan.plan_id,
                    plan_fingerprint=plan.plan_fingerprint,
                    proposal_id=proposal.proposal_id,
                    proposal_fingerprint=proposal.proposal_fingerprint,
                    proposal_version=proposal.proposal_version,
                    approval_decision_id=approval.decision_id,
                ),
                step_request=step_request,
            )
            step_runs.append(
                RecoveryStepRun(
                    recovery_step_run_id=stable_id("recovery_step_run", step_run_fingerprint),
                    recovery_run_id=recovery_run_id,
                    execution_step_request_id=step_request.step_request_id,
                    plan_step_id=step_request.plan_step_id,
                    sequence=step_request.sequence,
                    executor_category=step_request.executor_category,
                    action_kind=step_request.action_kind,
                    target=step_request.target,
                    inputs=dict(step_request.inputs),
                    risk_classification=step_request.risk_classification,
                    step_run_fingerprint=step_run_fingerprint,
                    status="pending",
                    metadata=sanitize_durable_mapping(
                        {
                            "created_at": created_at,
                            "created_by": compact_text(actor, max_chars=120),
                            "phase_scope": "evolution.phase6.recovery_step_run",
                            "verification_outcome_id": verification_outcome.verification_outcome_id,
                            "verification_outcome_fingerprint": verification_outcome.outcome_fingerprint,
                            "verification_run_id": verification_run.verification_run_id,
                            "verification_run_fingerprint": verification_run.run_fingerprint,
                            "proposal_fingerprint": proposal.proposal_fingerprint,
                            "proposal_version": proposal.proposal_version,
                            "plan_fingerprint": plan.plan_fingerprint,
                            "request_fingerprint": request.request_fingerprint,
                            "authorization_id": authorization.authorization_id,
                            "authorization_fingerprint": authorization.authorization_fingerprint,
                        }
                    ),
                )
            )
        return tuple(step_runs)

    def _build_verification_run_fingerprint(
        self,
        *,
        authorization: ExecutionAuthorization,
        verification_step_requests: tuple[ExecutionStepRequest, ...],
    ) -> str:
        """Build one deterministic fingerprint for the exact Phase 5 verification run scope."""

        ordered_steps = tuple(
            sorted(
                verification_step_requests,
                key=lambda item: (
                    item.sequence,
                    item.step_request_id,
                ),
            )
        )
        payload = {
            "phase_scope": "evolution.phase5.verification_run.v1",
            "authorization_binding": {
                "authorization_fingerprint": authorization.authorization_fingerprint,
            },
            "request_binding": {
                "request_fingerprint": authorization.request_fingerprint,
            },
            "plan_binding": {
                "plan_fingerprint": authorization.plan_fingerprint,
            },
            "proposal_binding": {
                "proposal_fingerprint": authorization.proposal_fingerprint,
                "proposal_version": int(authorization.proposal_version),
            },
            "approval_binding": {
                "approval_decision_id": authorization.approval_decision_id,
            },
            "verification_steps": tuple(self._canonical_execution_projection_payload(step) for step in ordered_steps),
        }
        return stable_id("verification_run_fingerprint", payload)

    def _build_verification_step_run_fingerprint(
        self,
        *,
        run: VerificationRun,
        step_request: ExecutionStepRequest,
    ) -> str:
        """Build one deterministic fingerprint for an exact verification step run."""

        payload = {
            "phase_scope": "evolution.phase5.verification_step_run.v1",
            "run_fingerprint": run.run_fingerprint,
            "step_request": self._canonical_execution_projection_payload(step_request),
        }
        return stable_id("verification_step_run_fingerprint", payload)

    def _build_verification_observation_fingerprint(
        self,
        *,
        run: VerificationRun,
        step_run: VerificationStepRun,
        observation_kind: str,
        evidence: Any,
        status: str,
    ) -> str:
        """Build one deterministic fingerprint for exact verification evidence semantics."""

        payload = {
            "phase_scope": "evolution.phase5.verification_observation.v1",
            "run_fingerprint": run.run_fingerprint,
            "step_run_fingerprint": step_run.step_run_fingerprint,
            "observation_kind": compact_text(observation_kind, max_chars=120),
            "status": compact_text(status, max_chars=80),
            "evidence": sanitize_durable_value(evidence),
        }
        return stable_id("verification_observation_fingerprint", payload)

    def _build_verification_outcome_fingerprint(
        self,
        *,
        run: VerificationRun,
        step_results: tuple[dict[str, Any], ...],
        status: str,
        reason_code: str,
    ) -> str:
        """Build one deterministic fingerprint for a terminal verification outcome."""

        payload = {
            "phase_scope": "evolution.phase5.verification_outcome.v1",
            "run_fingerprint": run.run_fingerprint,
            "status": compact_text(status, max_chars=80),
            "reason_code": compact_text(reason_code, max_chars=120),
            "step_results": tuple(self._canonical_verification_step_result_payload(result) for result in step_results),
        }
        return stable_id("verification_outcome_fingerprint", payload)

    def _canonical_verification_step_run_payload(self, step_run: VerificationStepRun) -> dict[str, Any]:
        """Return one canonical semantic payload for a persisted verification step run."""

        return {
            "plan_step_id": step_run.plan_step_id,
            "sequence": int(step_run.sequence),
            "executor_category": compact_text(step_run.executor_category, max_chars=80),
            "action_kind": compact_text(step_run.action_kind, max_chars=80),
            "target": compact_text(step_run.target, max_chars=240),
            "inputs": sanitize_durable_mapping(dict(step_run.inputs)),
            "risk_classification": compact_text(step_run.risk_classification, max_chars=80),
        }

    def _canonical_verification_step_result_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        """Return one canonical semantic payload for one step result."""

        return {
            "step_run_fingerprint": compact_text(str(result.get("step_run_fingerprint", "")), max_chars=120),
            "sequence": int(result.get("sequence", 0) or 0),
            "status": compact_text(str(result.get("status", "")), max_chars=80),
            "observation_count": int(result.get("observation_count", 0) or 0),
            "required_evidence_satisfied": bool(result.get("required_evidence_satisfied", False)),
        }

    def _normalize_verification_observation(self, observed_signal: Any) -> tuple[str, Any]:
        """Normalize one observation input into safe kind and evidence payload values."""

        if isinstance(observed_signal, dict):
            observation_kind = compact_text(
                str(
                    observed_signal.get("kind")
                    or observed_signal.get("signal")
                    or observed_signal.get("observation_kind")
                    or observed_signal.get("type")
                    or "observation"
                ),
                max_chars=120,
            )
            evidence_source = observed_signal.get("evidence", observed_signal.get("payload", observed_signal))
        elif isinstance(observed_signal, str):
            observation_kind = compact_text(observed_signal, max_chars=120) or "observation"
            evidence_source = observed_signal
        else:
            observation_kind = compact_text(type(observed_signal).__name__, max_chars=120) or "observation"
            evidence_source = observed_signal

        if not observation_kind:
            raise ValueError("Verification observations require a non-empty observation kind.")

        sanitized_evidence = sanitize_durable_value(evidence_source)
        if sanitized_evidence is None:
            raise ValueError("Verification evidence could not be represented safely for durable storage.")
        if isinstance(evidence_source, dict) and evidence_source and (not isinstance(sanitized_evidence, dict) or not sanitized_evidence):
            raise ValueError("Verification evidence dictionary could not be represented safely for durable storage.")
        if isinstance(evidence_source, (list, tuple, set, frozenset)) and evidence_source and (
            not isinstance(sanitized_evidence, list) or not sanitized_evidence
        ):
            raise ValueError("Verification evidence sequence could not be represented safely for durable storage.")
        return observation_kind, sanitized_evidence

    def _verification_evidence_polarity(self, evidence: Any) -> bool | None:
        """Return explicit positive, explicit negative, or inconclusive verification evidence."""

        if isinstance(evidence, bool):
            return evidence

        nested_polarities: list[bool | None]
        if isinstance(evidence, dict):
            nested_polarities = [self._verification_evidence_polarity(value) for value in evidence.values()]
        elif isinstance(evidence, (list, tuple, set, frozenset)):
            nested_polarities = [self._verification_evidence_polarity(value) for value in evidence]
        else:
            return None

        if any(item is False for item in nested_polarities):
            return False
        if any(item is True for item in nested_polarities):
            return True
        return None

    def _observation_supports_satisfaction(self, observation: VerificationObservation) -> bool:
        """Return whether one observation provides explicit positive verification evidence."""

        normalized_status = compact_text(observation.status, max_chars=80).lower()
        if normalized_status in {"error", "unsafe", "invalidated", "failed", "unsatisfied", "negative"}:
            return False
        return self._verification_evidence_polarity(observation.evidence) is True

    def _step_run_has_required_evidence(
        self,
        step_run: VerificationStepRun,
        observations: tuple[VerificationObservation, ...],
    ) -> bool:
        """Return whether one verification step run has the required durable evidence to satisfy success."""

        if not observations:
            return False

        step_request = next(
            (
                item
                for item in self._list_execution_step_requests()
                if item.step_request_id == step_run.execution_step_request_id
            ),
            None,
        )
        if step_request is None:
            return False
        plan_step = next(
            (
                item
                for item in self.list_plan_steps(plan_id=step_request.plan_id)
                if item.step_id == step_run.plan_step_id
            ),
            None,
        )
        if plan_step is None:
            return False
        required_ids = tuple(plan_step.verification_requirement_ids)
        requirements = {
            item.requirement_id: item
            for item in self.list_verification_requirements(plan_id=plan_step.plan_id)
        }
        observed_kinds: set[str] = set()
        for observation in observations:
            if not self._observation_supports_satisfaction(observation):
                return False
            observed_kinds.add(normalize_identity(observation.observation_kind))

        if not observed_kinds:
            return False

        if not required_ids:
            return True

        for requirement_id in required_ids:
            requirement = requirements.get(requirement_id)
            if requirement is None:
                return False
            if normalize_identity(requirement.expected_signal) not in observed_kinds:
                return False
        return True

    def _build_verification_step_results(
        self,
        step_runs: tuple[VerificationStepRun, ...],
    ) -> tuple[dict[str, Any], ...]:
        """Return ordered step-result semantics for one verification run."""

        ordered_results: list[dict[str, Any]] = []
        for step_run in step_runs:
            observations = self.list_verification_observations(
                verification_step_run_id=step_run.verification_step_run_id,
            )
            ordered_results.append(
                {
                    "execution_step_request_id": step_run.execution_step_request_id,
                    "step_run_fingerprint": step_run.step_run_fingerprint,
                    "sequence": step_run.sequence,
                    "status": step_run.status,
                    "observation_count": len(observations),
                    "required_evidence_satisfied": self._step_run_has_required_evidence(step_run, observations),
                }
            )
        return tuple(ordered_results)

    def _derive_verification_run_outcome(
        self,
        step_runs: tuple[VerificationStepRun, ...],
    ) -> tuple[str, str]:
        """Derive one truthful terminal verification-run outcome from ordered step states."""

        if not step_runs:
            return "blocked", "no_verification_steps"

        statuses = [step.status for step in step_runs]
        if any(status == "invalidated" for status in statuses):
            return "invalidated", "verification_step_invalidated"
        if all(status == "skipped" for status in statuses):
            return "aborted", "all_steps_skipped"
        if all(status == "satisfied" for status in statuses):
            return "passed", "all_steps_satisfied"

        has_satisfied = any(status == "satisfied" for status in statuses)
        if any(status in {"unsatisfied", "error"} for status in statuses):
            return ("partial", "partial_evidence") if has_satisfied else ("failed", "verification_failed")
        if any(status in {"pending", "observing"} for status in statuses):
            return ("partial", "steps_incomplete") if has_satisfied else ("blocked", "steps_incomplete")
        if any(status == "skipped" for status in statuses):
            return ("partial", "steps_skipped") if has_satisfied else ("aborted", "steps_skipped")
        return "blocked", "verification_state_incomplete"

    def _build_recovery_run_fingerprint(
        self,
        *,
        verification_outcome: VerificationOutcome,
        verification_run: VerificationRun,
        authorization: ExecutionAuthorization,
        request: ExecutionRequest,
        plan: ChangePlan,
        proposal: ChangeProposal,
        approval: ApprovalDecision,
        recovery_step_requests: tuple[ExecutionStepRequest, ...],
    ) -> str:
        """Build one deterministic fingerprint for the exact Phase 6 recovery run scope."""

        ordered_steps = tuple(
            sorted(
                recovery_step_requests,
                key=lambda item: (
                    item.sequence,
                    item.step_request_id,
                ),
            )
        )
        payload = {
            "phase_scope": "evolution.phase6.recovery_run.v1",
            "verification_outcome_binding": {
                "outcome_fingerprint": verification_outcome.outcome_fingerprint,
            },
            "verification_run_binding": {
                "run_fingerprint": verification_run.run_fingerprint,
            },
            "authorization_binding": {
                "authorization_fingerprint": authorization.authorization_fingerprint,
            },
            "request_binding": {
                "request_fingerprint": request.request_fingerprint,
            },
            "plan_binding": {
                "plan_fingerprint": plan.plan_fingerprint,
            },
            "proposal_binding": {
                "proposal_fingerprint": proposal.proposal_fingerprint,
                "proposal_version": int(proposal.proposal_version),
            },
            "approval_binding": {
                "approval_decision_id": approval.decision_id,
            },
            "recovery_steps": tuple(self._canonical_execution_projection_payload(step) for step in ordered_steps),
        }
        return stable_id("recovery_run_fingerprint", payload)

    def _build_recovery_step_run_fingerprint(
        self,
        *,
        run: RecoveryRun,
        step_request: ExecutionStepRequest,
    ) -> str:
        """Build one deterministic fingerprint for an exact recovery step run."""

        payload = {
            "phase_scope": "evolution.phase6.recovery_step_run.v1",
            "run_fingerprint": run.run_fingerprint,
            "step_request": self._canonical_execution_projection_payload(step_request),
        }
        return stable_id("recovery_step_run_fingerprint", payload)

    def _build_recovery_observation_fingerprint(
        self,
        *,
        run: RecoveryRun,
        step_run: RecoveryStepRun,
        observation_kind: str,
        evidence: Any,
        status: str,
    ) -> str:
        """Build one deterministic fingerprint for exact recovery-readiness evidence semantics."""

        payload = {
            "phase_scope": "evolution.phase6.recovery_observation.v1",
            "run_fingerprint": run.run_fingerprint,
            "step_run_fingerprint": step_run.step_run_fingerprint,
            "observation_kind": compact_text(observation_kind, max_chars=120),
            "status": compact_text(status, max_chars=80),
            "evidence": sanitize_durable_value(evidence),
        }
        return stable_id("recovery_observation_fingerprint", payload)

    def _build_recovery_outcome_fingerprint(
        self,
        *,
        run: RecoveryRun,
        step_results: tuple[dict[str, Any], ...],
        status: str,
        reason_code: str,
    ) -> str:
        """Build one deterministic fingerprint for a terminal recovery-readiness outcome."""

        payload = {
            "phase_scope": "evolution.phase6.recovery_outcome.v1",
            "run_fingerprint": run.run_fingerprint,
            "status": compact_text(status, max_chars=80),
            "reason_code": compact_text(reason_code, max_chars=120),
            "step_results": tuple(self._canonical_recovery_step_result_payload(result) for result in step_results),
        }
        return stable_id("recovery_outcome_fingerprint", payload)

    def _canonical_recovery_step_run_payload(self, step_run: RecoveryStepRun) -> dict[str, Any]:
        """Return one canonical semantic payload for a persisted recovery step run."""

        return {
            "plan_step_id": step_run.plan_step_id,
            "sequence": int(step_run.sequence),
            "executor_category": compact_text(step_run.executor_category, max_chars=80),
            "action_kind": compact_text(step_run.action_kind, max_chars=80),
            "target": compact_text(step_run.target, max_chars=240),
            "inputs": sanitize_durable_mapping(dict(step_run.inputs)),
            "risk_classification": compact_text(step_run.risk_classification, max_chars=80),
        }

    def _canonical_recovery_step_result_payload(self, result: dict[str, Any]) -> dict[str, Any]:
        """Return one canonical semantic payload for one recovery step result."""

        return {
            "step_run_fingerprint": compact_text(str(result.get("step_run_fingerprint", "")), max_chars=120),
            "sequence": int(result.get("sequence", 0) or 0),
            "status": compact_text(str(result.get("status", "")), max_chars=80),
            "observation_count": int(result.get("observation_count", 0) or 0),
            "required_evidence_satisfied": bool(result.get("required_evidence_satisfied", False)),
        }

    def _recovery_observation_supports_readiness(self, observation: RecoveryObservation) -> bool:
        """Return whether one observation provides explicit positive recovery-readiness evidence."""

        normalized_status = compact_text(observation.status, max_chars=80).lower()
        if normalized_status in {"error", "unsafe", "invalidated", "failed", "blocked", "negative"}:
            return False
        return self._verification_evidence_polarity(observation.evidence) is True

    def _recovery_step_run_has_required_evidence(
        self,
        step_run: RecoveryStepRun,
        observations: tuple[RecoveryObservation, ...],
    ) -> bool:
        """Return whether one recovery step run has the required durable readiness evidence."""

        if not observations:
            return False

        step_request = next(
            (
                item
                for item in self._list_execution_step_requests()
                if item.step_request_id == step_run.execution_step_request_id
            ),
            None,
        )
        if step_request is None:
            return False
        plan_step = next(
            (
                item
                for item in self.list_plan_steps(plan_id=step_request.plan_id)
                if item.step_id == step_run.plan_step_id
            ),
            None,
        )
        if plan_step is None:
            return False

        return all(self._recovery_observation_supports_readiness(observation) for observation in observations)

    def _build_recovery_step_results(
        self,
        step_runs: tuple[RecoveryStepRun, ...],
    ) -> tuple[dict[str, Any], ...]:
        """Return ordered step-result semantics for one recovery run."""

        ordered_results: list[dict[str, Any]] = []
        for step_run in step_runs:
            observations = self.list_recovery_observations(
                recovery_step_run_id=step_run.recovery_step_run_id,
            )
            ordered_results.append(
                {
                    "execution_step_request_id": step_run.execution_step_request_id,
                    "step_run_fingerprint": step_run.step_run_fingerprint,
                    "sequence": step_run.sequence,
                    "status": step_run.status,
                    "observation_count": len(observations),
                    "required_evidence_satisfied": self._recovery_step_run_has_required_evidence(step_run, observations),
                }
            )
        return tuple(ordered_results)

    def _derive_recovery_run_outcome(
        self,
        step_runs: tuple[RecoveryStepRun, ...],
    ) -> tuple[str, str]:
        """Derive one truthful terminal recovery-run outcome from ordered step states."""

        if not step_runs:
            return "blocked", "no_recovery_steps"

        statuses = [step.status for step in step_runs]
        if any(status == "invalidated" for status in statuses):
            return "invalidated", "recovery_step_invalidated"
        if all(status == "ready" for status in statuses):
            return "ready", "all_steps_ready"
        if any(status == "blocked" for status in statuses):
            return "blocked", "recovery_preconditions_unresolved"
        if any(status in {"pending", "preparing"} for status in statuses):
            return "blocked", "steps_incomplete"
        return "blocked", "recovery_state_incomplete"

    def _invalidate_recovery_run(
        self,
        run: RecoveryRun,
        *,
        reason_code: str,
        reason: str,
        actor: str,
    ) -> RecoveryRun:
        """Persist one invalidated recovery run and mark any active step runs invalidated."""

        current_run = self.get_recovery_run(run.recovery_run_id) or run
        if current_run.status in _RECOVERY_RUN_TERMINAL_STATUSES:
            return current_run

        now = self._now_iso()
        invalidated_run = replace(
            current_run,
            status="invalidated",
            metadata=self._updated_metadata(
                current_run.metadata,
                invalidated_at=current_run.metadata.get("invalidated_at") or now,
                invalidated_by=current_run.metadata.get("invalidated_by") or compact_text(actor, max_chars=120),
                invalidation_reason_code=compact_text(reason_code, max_chars=120),
                invalidation_reason=compact_text(reason, max_chars=320),
            ),
        )
        self._persist_recovery_run(invalidated_run)

        for step_run in self.list_recovery_step_runs(recovery_run_id=invalidated_run.recovery_run_id):
            if step_run.status in _RECOVERY_STEP_TERMINAL_STATUSES:
                continue
            self._persist_recovery_step_run(
                replace(
                    step_run,
                    status="invalidated",
                    metadata=self._updated_metadata(
                        step_run.metadata,
                        invalidated_at=step_run.metadata.get("invalidated_at") or now,
                        invalidated_by=step_run.metadata.get("invalidated_by") or compact_text(actor, max_chars=120),
                        invalidation_reason_code=compact_text(reason_code, max_chars=120),
                    ),
                )
            )

        self._persist_journal_entry(
            proposal_id=invalidated_run.proposal_id,
            event_type="recovery_run_invalidated",
            previous_state=current_run.status,
            new_state="invalidated",
            actor=actor,
            details={
                "recovery_run_id": invalidated_run.recovery_run_id,
                "reason_code": compact_text(reason_code, max_chars=120),
                "reason": compact_text(reason, max_chars=320),
            },
        )
        return invalidated_run

    def _invalidate_verification_run(
        self,
        run: VerificationRun,
        *,
        reason_code: str,
        reason: str,
        actor: str,
    ) -> VerificationRun:
        """Persist one invalidated verification run and mark any active step runs invalidated."""

        current_run = self.get_verification_run(run.verification_run_id) or run
        if current_run.status in _VERIFICATION_RUN_TERMINAL_STATUSES:
            return current_run

        now = self._now_iso()
        invalidated_run = replace(
            current_run,
            status="invalidated",
            metadata=self._updated_metadata(
                current_run.metadata,
                invalidated_at=current_run.metadata.get("invalidated_at") or now,
                invalidated_by=current_run.metadata.get("invalidated_by") or compact_text(actor, max_chars=120),
                invalidation_reason_code=compact_text(reason_code, max_chars=120),
                invalidation_reason=compact_text(reason, max_chars=320),
            ),
        )
        self._persist_verification_run(invalidated_run)

        for step_run in self.list_verification_step_runs(verification_run_id=invalidated_run.verification_run_id):
            if step_run.status in _VERIFICATION_STEP_TERMINAL_STATUSES:
                continue
            self._persist_verification_step_run(
                replace(
                    step_run,
                    status="invalidated",
                    metadata=self._updated_metadata(
                        step_run.metadata,
                        invalidated_at=step_run.metadata.get("invalidated_at") or now,
                        invalidated_by=step_run.metadata.get("invalidated_by") or compact_text(actor, max_chars=120),
                        invalidation_reason_code=compact_text(reason_code, max_chars=120),
                    ),
                )
            )

        self._persist_journal_entry(
            proposal_id=invalidated_run.proposal_id,
            event_type="verification_run_invalidated",
            previous_state=current_run.status,
            new_state="invalidated",
            actor=actor,
            details={
                "verification_run_id": invalidated_run.verification_run_id,
                "reason_code": compact_text(reason_code, max_chars=120),
                "reason": compact_text(reason, max_chars=320),
            },
        )
        return invalidated_run

    def _persist_verification_run(self, run: VerificationRun) -> None:
        """Persist one verification run through the existing memory storage."""

        self._persist_record(
            category="verification_run",
            key=f"evolution:verification_run:{run.verification_run_id}",
            value=run.to_dict(),
            metadata={
                "verification_run_id": run.verification_run_id,
                "run_fingerprint": run.run_fingerprint,
                "proposal_id": run.proposal_id,
                "authorization_id": run.authorization_id,
                "status": run.status,
                "actor": run.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _persist_verification_step_run(self, step_run: VerificationStepRun) -> None:
        """Persist one verification step run through the existing memory storage."""

        self._persist_record(
            category="verification_step_run",
            key=f"evolution:verification_step_run:{step_run.verification_step_run_id}",
            value=step_run.to_dict(),
            metadata={
                "verification_run_id": step_run.verification_run_id,
                "verification_step_run_id": step_run.verification_step_run_id,
                "execution_step_request_id": step_run.execution_step_request_id,
                "sequence": step_run.sequence,
                "status": step_run.status,
                "executor_category": step_run.executor_category,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _persist_verification_observation(self, observation: VerificationObservation) -> None:
        """Persist one verification observation through the existing memory storage."""

        self._persist_record(
            category="verification_observation",
            key=f"evolution:verification_observation:{observation.observation_id}",
            value=observation.to_dict(),
            metadata={
                "verification_run_id": observation.verification_run_id,
                "verification_step_run_id": observation.verification_step_run_id,
                "observation_id": observation.observation_id,
                "observation_kind": observation.observation_kind,
                "status": observation.status,
                "actor": observation.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _persist_verification_outcome(self, outcome: VerificationOutcome) -> None:
        """Persist one verification outcome through the existing memory storage."""

        self._persist_record(
            category="verification_outcome",
            key=f"evolution:verification_outcome:{outcome.verification_outcome_id}",
            value=outcome.to_dict(),
            metadata={
                "verification_run_id": outcome.verification_run_id,
                "verification_outcome_id": outcome.verification_outcome_id,
                "status": outcome.status,
                "reason_code": outcome.reason_code,
                "actor": outcome.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _persist_recovery_run(self, run: RecoveryRun) -> None:
        """Persist one recovery run through the existing memory storage."""

        self._persist_record(
            category="recovery_run",
            key=f"evolution:recovery_run:{run.recovery_run_id}",
            value=run.to_dict(),
            metadata={
                "recovery_run_id": run.recovery_run_id,
                "run_fingerprint": run.run_fingerprint,
                "proposal_id": run.proposal_id,
                "verification_outcome_id": run.verification_outcome_id,
                "status": run.status,
                "actor": run.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _persist_recovery_step_run(self, step_run: RecoveryStepRun) -> None:
        """Persist one recovery step run through the existing memory storage."""

        self._persist_record(
            category="recovery_step_run",
            key=f"evolution:recovery_step_run:{step_run.recovery_step_run_id}",
            value=step_run.to_dict(),
            metadata={
                "recovery_run_id": step_run.recovery_run_id,
                "recovery_step_run_id": step_run.recovery_step_run_id,
                "execution_step_request_id": step_run.execution_step_request_id,
                "sequence": step_run.sequence,
                "status": step_run.status,
                "executor_category": step_run.executor_category,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _persist_recovery_observation(self, observation: RecoveryObservation) -> None:
        """Persist one recovery observation through the existing memory storage."""

        self._persist_record(
            category="recovery_observation",
            key=f"evolution:recovery_observation:{observation.observation_id}",
            value=observation.to_dict(),
            metadata={
                "recovery_run_id": observation.recovery_run_id,
                "recovery_step_run_id": observation.recovery_step_run_id,
                "observation_id": observation.observation_id,
                "observation_kind": observation.observation_kind,
                "status": observation.status,
                "actor": observation.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _persist_recovery_outcome(self, outcome: RecoveryOutcome) -> None:
        """Persist one recovery outcome through the existing memory storage."""

        self._persist_record(
            category="recovery_outcome",
            key=f"evolution:recovery_outcome:{outcome.recovery_outcome_id}",
            value=outcome.to_dict(),
            metadata={
                "recovery_run_id": outcome.recovery_run_id,
                "recovery_outcome_id": outcome.recovery_outcome_id,
                "status": outcome.status,
                "reason_code": outcome.reason_code,
                "actor": outcome.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )

    def _updated_metadata(self, metadata: dict[str, Any], **updates: Any) -> dict[str, Any]:
        """Return one sanitized metadata mapping updated with supplied values."""

        merged = dict(metadata)
        merged.update({key: value for key, value in updates.items() if value is not None})
        return sanitize_durable_mapping(merged)

    def _metadata_timestamp(self, metadata: dict[str, Any], key: str) -> Any:
        """Return one sortable timestamp value from record metadata."""

        value = metadata.get(key)
        if not value:
            return ""
        return parse_timestamp(value).isoformat()

    def _now_iso(self) -> str:
        """Return the current UTC timestamp in ISO format."""

        return utc_now().isoformat()

    def _authorization_event_type(self, decision: str) -> str:
        """Return the journal event name for one authorization decision."""

        if decision == "granted":
            return "execution_authorization_granted"
        if decision == "invalidated":
            return "execution_request_invalidated"
        return "execution_authorization_denied"

    def _build_candidate(self, query: str, response: Any, evidence_records: tuple[EvidenceRecord, ...]) -> DiscoveryCandidate:
        """Create one conservative candidate record from source-backed evidence."""

        technology_category = self._infer_category(
            query,
            response.answer,
            evidence_records,
        )
        normalized_name = normalize_identity(query)
        candidate = DiscoveryCandidate(
            candidate_id=stable_id("discovery_candidate", technology_category, normalized_name),
            name=query,
            normalized_name=normalized_name,
            technology_category=technology_category,
            short_description=compact_text(response.answer, max_chars=320),
            status="discovered",
            evidence_records=evidence_records,
            metadata={
                "evidence_count": len(evidence_records),
                "search_provider_name": response.search_provider_name,
                "search_status": response.search_status,
                "source_domains": tuple(record.source_identity for record in evidence_records),
            },
        )
        return candidate

    def _build_evidence_records(self, response: Any) -> tuple[EvidenceRecord, ...]:
        """Normalize grounded research sources into durable evidence records."""

        evidence_lines = list(getattr(response, "evidence_summary", ()) or ())
        records: list[EvidenceRecord] = []
        for index, source in enumerate(getattr(response, "sources", ()) or ()):
            summary = evidence_lines[index] if index < len(evidence_lines) else getattr(source, "title", "")
            bounded_text = compact_text(summary or response.answer or getattr(source, "title", ""), max_chars=400)
            record = EvidenceRecord(
                evidence_id=stable_id(
                    "evidence_record",
                    getattr(source, "url", ""),
                    getattr(source, "title", ""),
                    bounded_text,
                ),
                source_identity=compact_text(getattr(source, "domain", "") or getattr(source, "title", ""), max_chars=120),
                source_url=compact_text(getattr(source, "url", ""), max_chars=400),
                title=compact_text(getattr(source, "title", ""), max_chars=240),
                summary=compact_text(summary, max_chars=320),
                bounded_text=bounded_text,
                provenance_label="grounded_public_web",
                trust_label="unverified_public_web",
                metadata={
                    "search_provider_name": getattr(response, "search_provider_name", ""),
                    "source_rank": index + 1,
                },
            )
            records.append(record)
        return tuple(records)

    def _build_inferences(
        self,
        candidate: DiscoveryCandidate,
        related_records: list[Any],
        degraded_records: list[Any],
    ) -> tuple[str, ...]:
        """Build conservative evidence-linked inferences."""

        if not related_records and candidate.technology_category != "technology":
            return (f"NARVIS may have a capability gap in '{candidate.technology_category}' because no related capability records were found.",)
        if degraded_records:
            return (
                f"NARVIS may have limited '{candidate.technology_category}' coverage because some related capabilities are degraded or unavailable.",
            )
        if related_records:
            return (
                f"The candidate appears to overlap existing '{candidate.technology_category}' capabilities, but its improvement value is still unverified.",
            )
        return ("The candidate could represent a new technology area, but the current inventory mapping is uncertain.",)

    def _build_potential_benefits(
        self,
        candidate: DiscoveryCandidate,
        degraded_records: list[Any],
        related_records: list[Any],
    ) -> tuple[str, ...]:
        """Build conservative potential-benefit statements."""

        if degraded_records:
            return (f"The candidate could help improve degraded '{candidate.technology_category}' coverage if later compatibility checks succeed.",)
        if related_records:
            return (f"The candidate could extend existing '{candidate.technology_category}' capability coverage if later evaluation supports it.",)
        if candidate.technology_category != "technology":
            return (f"The candidate could add missing '{candidate.technology_category}' coverage if later evidence supports integration.",)
        return ("The candidate may be relevant to future capability expansion, but the exact benefit remains uncertain.",)

    def _build_capability_gaps(
        self,
        *,
        candidate: DiscoveryCandidate,
        inventory_snapshot: CapabilityInventorySnapshot,
        related_records: list[Any],
        degraded_records: list[Any],
    ) -> tuple[CapabilityGap, ...]:
        """Return conservative capability gaps backed by current inventory facts."""

        current_evidence = tuple(
            f"{record.name} ({record.status}, {record.implementation})"
            for record in related_records
        )
        candidate_evidence_ids = tuple(record.evidence_id for record in candidate.evidence_records)
        if candidate.technology_category == "technology":
            return ()
        if not related_records:
            summary = f"No direct '{candidate.technology_category}' capability record exists in the current inventory."
            return (
                CapabilityGap(
                    gap_id=stable_id("capability_gap", inventory_snapshot.snapshot_id, candidate.candidate_id, "missing"),
                    candidate_id=candidate.candidate_id,
                    inventory_snapshot_id=inventory_snapshot.snapshot_id,
                    capability_category=candidate.technology_category,
                    summary=summary,
                    current_capability_evidence=current_evidence,
                    candidate_evidence_ids=candidate_evidence_ids,
                    unknowns=("Whether the candidate is compatible with the current runtime is still unknown.",),
                    confidence=0.6,
                ),
            )
        if degraded_records:
            summary = f"The current '{candidate.technology_category}' capability surface exists but is degraded or limited."
            return (
                CapabilityGap(
                    gap_id=stable_id("capability_gap", inventory_snapshot.snapshot_id, candidate.candidate_id, "degraded"),
                    candidate_id=candidate.candidate_id,
                    inventory_snapshot_id=inventory_snapshot.snapshot_id,
                    capability_category=candidate.technology_category,
                    summary=summary,
                    current_capability_evidence=current_evidence,
                    candidate_evidence_ids=candidate_evidence_ids,
                    unknowns=("Whether the candidate would actually improve the degraded capability remains unknown.",),
                    confidence=0.65,
                ),
            )
        return ()

    def _extract_signal_notes(self, candidate: DiscoveryCandidate, note_type: str) -> tuple[str, ...]:
        """Extract conservative evidence-supported notes from candidate evidence text."""

        keywords = _TECHNICAL_KEYWORDS[note_type]
        search_text = " ".join(
            [candidate.name, candidate.short_description, *(record.title for record in candidate.evidence_records), *(record.bounded_text for record in candidate.evidence_records)]
        ).lower()
        notes: list[str] = []
        if note_type == "compatibility_notes":
            if any(keyword in search_text for keyword in ("python", "sdk", "api")):
                notes.append("Evidence mentions a developer-facing integration surface such as Python, an SDK, or an API.")
            if any(keyword in search_text for keyword in ("windows", "linux")):
                notes.append("Evidence mentions operating-system support.")
        elif note_type == "cost_notes":
            if "open source" in search_text or "open-source" in search_text or "free" in search_text:
                notes.append("Evidence suggests the candidate may be free or open source.")
            if any(keyword in search_text for keyword in ("paid", "pricing", "subscription", "enterprise")):
                notes.append("Evidence mentions paid, subscription, or enterprise pricing.")
        elif note_type == "privacy_security_notes":
            if any(keyword in search_text for keyword in ("local", "offline", "on-device", "on device")):
                notes.append("Evidence suggests local or offline execution, which may reduce external data exposure.")
            if any(keyword in search_text for keyword in ("cloud", "hosted", "remote")):
                notes.append("Evidence suggests hosted or remote execution, which may increase data-sharing considerations.")
            if "security" in search_text or "privacy" in search_text:
                notes.append("Evidence directly references privacy or security considerations.")
        elif note_type == "reliability_notes":
            if any(keyword in search_text for keyword in ("beta", "preview", "experimental")):
                notes.append("Evidence suggests the candidate may still be in preview, beta, or experimental status.")
            if "stable" in search_text or "release" in search_text:
                notes.append("Evidence mentions a stable or release-oriented state.")

        return tuple(dict.fromkeys(note for note in notes if note and any(keyword in search_text for keyword in keywords)))

    def _infer_category(
        self,
        query_text: str,
        description_text: str,
        evidence_records: tuple[EvidenceRecord, ...],
    ) -> str:
        """Infer one conservative technology category from the proposed capability itself."""

        category = self._match_category(query_text)
        if category is not None:
            return category

        category = self._match_category(
            description_text,
            allowed_categories=_DESCRIPTION_FALLBACK_CATEGORIES,
        )
        if category is not None:
            return category

        evidence_text = " ".join(
            filter(
                None,
                (
                    *(record.title for record in evidence_records),
                    *(record.summary for record in evidence_records),
                    *(record.bounded_text for record in evidence_records),
                ),
            )
        )
        category = self._match_category(
            evidence_text,
            allowed_categories=_EVIDENCE_FALLBACK_CATEGORIES,
        )
        if category is not None:
            return category
        return "technology"

    def _match_category(
        self,
        value: str,
        *,
        allowed_categories: frozenset[str] | None = None,
    ) -> str | None:
        """Return the first matching semantic category for one normalized text block."""

        normalized = compact_text(value, max_chars=1600).lower()
        if not normalized:
            return None
        for category, markers in _PHRASE_CATEGORY_RULES:
            if allowed_categories is not None and category not in allowed_categories:
                continue
            if any(marker in normalized for marker in markers):
                return category
        tokens = set(_WORD_PATTERN.findall(normalized))
        ai_allowed = allowed_categories is None or "ai" in allowed_categories
        if ai_allowed and {"llm", "inference"} & tokens:
            return "ai"
        if ai_allowed and "model" in tokens and ("provider" in tokens or "routing" in tokens):
            return "ai"
        return None

    def _select_related_records(
        self,
        candidate: DiscoveryCandidate,
        capabilities: tuple[Any, ...],
    ) -> list[Any]:
        """Return only the runtime capability records meaningfully comparable to one candidate."""

        related_categories = _CATEGORY_RELATIONSHIPS.get(candidate.technology_category, frozenset())
        if not related_categories:
            return []

        direct_records = [record for record in capabilities if record.category in related_categories]
        if not direct_records:
            return []

        if candidate.technology_category == "internet":
            return self._select_internet_related_records(candidate, direct_records)
        if candidate.technology_category == "integration":
            return self._select_integration_related_records(candidate, direct_records)
        return direct_records

    def _select_internet_related_records(self, candidate: DiscoveryCandidate, direct_records: list[Any]) -> list[Any]:
        """Return internet runtime records that actually align with the candidate semantics."""

        candidate_text = self._candidate_text(candidate)
        aligned_records = [
            record
            for record in direct_records
            if any(marker in candidate_text for marker in _INTERNET_ALIGNMENT_MARKERS.get(record.capability_id, ()))
        ]
        generic_records = [
            record
            for record in direct_records
            if record.capability_id in _INTERNET_GENERIC_CAPABILITY_IDS
        ]
        if aligned_records:
            return self._dedupe_records([*aligned_records, *generic_records])
        return generic_records

    def _select_integration_related_records(self, candidate: DiscoveryCandidate, direct_records: list[Any]) -> list[Any]:
        """Return plugin/skill records only when the candidate explicitly names them."""

        candidate_text = self._candidate_text(candidate)
        if not any(marker in candidate_text for marker in ("plugin", "extension", "integration", "adapter", "connector")):
            return []
        return [
            record
            for record in direct_records
            if record.category == "plugin" or record.capability_id.startswith("skill:")
        ]

    def _candidate_text(self, candidate: DiscoveryCandidate) -> str:
        """Build one normalized semantic text block for candidate-to-runtime alignment."""

        return compact_text(
            " ".join(
                filter(
                    None,
                    (
                        candidate.name,
                        candidate.short_description,
                        *(record.title for record in candidate.evidence_records),
                        *(record.summary for record in candidate.evidence_records),
                        *(record.bounded_text for record in candidate.evidence_records),
                    ),
                )
            ),
            max_chars=2000,
        ).lower()

    def _dedupe_records(self, records: list[Any]) -> list[Any]:
        """Return records without duplicates while preserving stable order."""

        ordered: list[Any] = []
        seen_ids: set[str] = set()
        for record in records:
            record_id = getattr(record, "capability_id", "")
            if record_id in seen_ids:
                continue
            ordered.append(record)
            seen_ids.add(record_id)
        return ordered

    def _build_proposal_title(self, evaluation: EvaluationRecord) -> str:
        """Return a conservative human-readable title for one proposal."""

        return f"Prepare approved improvement for {evaluation.candidate_name}"

    def _build_proposal_summary(self, evaluation: EvaluationRecord) -> str:
        """Return a concise proposal summary."""

        if evaluation.potential_benefits:
            return evaluation.potential_benefits[0]
        if evaluation.inferences:
            return evaluation.inferences[0]
        return f"Prepare a future user-approved improvement path for '{evaluation.candidate_name}'."

    def _build_proposal_rationale(self, evaluation: EvaluationRecord) -> str:
        """Build one bounded rationale from the evaluation facts and inferences."""

        rationale_parts = [
            *evaluation.inferences[:2],
            *evaluation.potential_benefits[:1],
            *evaluation.unknowns[:1],
        ]
        if not rationale_parts:
            rationale_parts.append(f"'{evaluation.candidate_name}' requires a documented approval path before any future integration work.")
        return compact_text(" ".join(rationale_parts), max_chars=400)

    def _build_requested_actions(self, evaluation: EvaluationRecord) -> tuple[str, ...]:
        """Build conservative requested actions without execution authority."""

        actions = [
            f"Prepare a compatibility review for '{evaluation.candidate_name}' in the '{evaluation.candidate_category}' capability area.",
            "Document the exact future change scope before any package, code, git, OS, automation, or computer mutation is allowed.",
            "Require explicit user approval bound to this exact proposal fingerprint before any later execution phase.",
        ]
        if evaluation.overlapping_capability_ids:
            actions.append(
                "Inspect related runtime surfaces: "
                + ", ".join(evaluation.overlapping_capability_ids[:4])
                + "."
            )
        return tuple(dict.fromkeys(compact_text(action, max_chars=240) for action in actions if action))

    def _build_affected_surfaces(self, evaluation: EvaluationRecord) -> tuple[str, ...]:
        """Build one conservative list of potentially affected surfaces."""

        surfaces = list(_CATEGORY_SURFACE_MAP.get(evaluation.candidate_category, ("future capability surface",)))
        surfaces.extend(evaluation.overlapping_capability_ids)
        if evaluation.capability_gap_ids:
            surfaces.append("evolution capability-gap records")
        return tuple(dict.fromkeys(compact_text(surface, max_chars=160) for surface in surfaces if surface))

    def _build_expected_benefits(self, evaluation: EvaluationRecord) -> tuple[str, ...]:
        """Return bounded expected benefits."""

        if evaluation.potential_benefits:
            return tuple(dict.fromkeys(compact_text(item, max_chars=240) for item in evaluation.potential_benefits if item))
        return (f"The proposal could improve '{evaluation.candidate_category}' coverage after later approval and verification.",)

    def _build_known_risks(self, evaluation: EvaluationRecord) -> tuple[str, ...]:
        """Return bounded known risks."""

        risks = list(evaluation.unknowns[:4])
        if not risks:
            risks.append("Compatibility and rollout risk remain unverified until a later execution phase.")
        return tuple(dict.fromkeys(compact_text(item, max_chars=240) for item in risks if item))

    def _build_verification_plan(self, evaluation: EvaluationRecord) -> tuple[str, ...]:
        """Return a conservative verification plan."""

        steps = [
            "Validate the proposal details against the current inventory and retained evidence records.",
            "Re-run focused regression tests before any later approved execution phase.",
            "Confirm that the proposal fingerprint shown to the user matches the fingerprint used for approval.",
        ]
        if evaluation.overlapping_capability_ids:
            steps.append(
                "Check related capability records for regressions: "
                + ", ".join(evaluation.overlapping_capability_ids[:4])
                + "."
            )
        return tuple(dict.fromkeys(compact_text(step, max_chars=240) for step in steps if step))

    def _build_rollback_plan(self, evaluation: EvaluationRecord) -> tuple[str, ...]:
        """Return a conservative rollback plan."""

        steps = [
            "Do not execute any host mutation until a later explicitly approved execution phase exists.",
            "If a future execution phase changes files, packages, or system surfaces, restore the last verified pre-change state.",
            f"If the proposal for '{evaluation.candidate_name}' changes, expire prior approvals and require a fresh approval decision.",
        ]
        return tuple(dict.fromkeys(compact_text(step, max_chars=240) for step in steps if step))

    def _ensure_plan_authorized(
        self,
        proposal: ChangeProposal,
        approval: ApprovalDecision | None,
    ) -> None:
        """Raise when one proposal is not currently authorized for planning."""

        current_proposal = self.get_change_proposal(proposal.proposal_id)
        if current_proposal is None or current_proposal.proposal_fingerprint != proposal.proposal_fingerprint:
            raise ValueError("Only the current proposal revision may be converted into a change plan.")
        if approval is None or approval.decision == "pending":
            raise ValueError("An explicitly approved proposal is required before a change plan can be created.")
        if approval.decision == "rejected":
            raise ValueError("Rejected proposals cannot be converted into change plans.")
        if approval.decision == "expired":
            raise ValueError("Expired approvals cannot authorize change-plan creation.")
        if approval.decision != "approved":
            raise ValueError(f"Proposal approval state '{approval.decision}' does not authorize planning.")
        if approval.proposal_id != proposal.proposal_id or approval.proposal_fingerprint != proposal.proposal_fingerprint:
            raise ValueError("The effective approval does not authorize this exact proposal fingerprint.")
        approval_version = int(approval.metadata.get("proposal_version", proposal.proposal_version) or proposal.proposal_version)
        if approval_version != proposal.proposal_version:
            raise ValueError("The effective approval belongs to an older proposal version and cannot authorize this plan.")

    def _proposal_evaluation_id(self, proposal: ChangeProposal) -> str:
        """Return the durable evaluation identifier recorded on one proposal."""

        return compact_text(str(proposal.metadata.get("evaluation_id", "")), max_chars=120)

    def _load_evaluation_for_proposal(self, proposal: ChangeProposal) -> EvaluationRecord | None:
        """Load the evaluation record linked to one proposal when available."""

        evaluation_id = self._proposal_evaluation_id(proposal)
        if not evaluation_id:
            return None
        for evaluation in self._load_records("evaluation_record", EvaluationRecord.from_dict):
            if evaluation.evaluation_id == evaluation_id:
                return evaluation
        return None

    def _proposal_candidate_name(
        self,
        proposal: ChangeProposal,
        evaluation: EvaluationRecord | None,
    ) -> str:
        """Return the best available candidate name for one proposal."""

        if evaluation is not None and evaluation.candidate_name:
            return compact_text(evaluation.candidate_name, max_chars=160)
        return compact_text(proposal.title.replace("Prepare approved improvement for", "").strip() or proposal.title, max_chars=160)

    def _proposal_candidate_category(
        self,
        proposal: ChangeProposal,
        evaluation: EvaluationRecord | None,
    ) -> str:
        """Return the best available candidate category for one proposal."""

        if evaluation is not None and evaluation.candidate_category:
            return compact_text(evaluation.candidate_category, max_chars=80)
        return compact_text(str(proposal.metadata.get("candidate_category", "technology")), max_chars=80) or "technology"

    def _build_plan_blueprints(
        self,
        *,
        proposal: ChangeProposal,
        approval: ApprovalDecision,
        evaluation: EvaluationRecord | None,
    ) -> tuple[_PlanStepBlueprint, ...]:
        """Build deterministic future plan blueprints from one approved proposal."""

        candidate_name = self._proposal_candidate_name(proposal, evaluation)
        candidate_category = self._proposal_candidate_category(proposal, evaluation)
        action_kind, target, category_missing_details = self._primary_plan_action(
            candidate_name=candidate_name,
            candidate_category=candidate_category,
        )
        evidence_unknowns = tuple(evaluation.unknowns[:3]) if evaluation is not None else ()
        missing_details = tuple(dict.fromkeys((*category_missing_details, *evidence_unknowns)))
        verification_steps = tuple(proposal.verification_plan[:3]) or (
            "Confirm the exact approved proposal fingerprint before any later execution phase.",
        )
        rollback_steps = tuple(proposal.rollback_plan[:3]) or (
            "Restore the last verified pre-change state if the future execution phase fails or widens scope.",
        )
        mutation_description = (
            f"Prepare the future '{action_kind}' change for '{candidate_name}' within the approved '{candidate_category}' scope. "
            "This plan records intent only and does not authorize or execute the change in Phase 3."
        )
        if missing_details:
            mutation_description = compact_text(
                mutation_description
                + " Missing execution details remain explicit: "
                + " ".join(missing_details),
                max_chars=400,
            )
        mutation_inputs = {
            "candidate_name": candidate_name,
            "candidate_category": candidate_category,
            "affected_surfaces": proposal.affected_surfaces,
            "requested_actions": proposal.requested_actions,
            "missing_details": missing_details,
            "approval_boundary": "Phase 2 approval authorizes plan creation only; execution remains disallowed in Phase 3.",
        }
        verification_requirements = (
            (
                f"Verify the future '{action_kind}' change for '{candidate_name}' stays inside the approved proposal scope.",
                "The approved proposal fingerprint, affected surfaces, and recorded verification checks all still match the planned change.",
            ),
            (
                f"Run the required verification checks for '{candidate_name}' before and after any later execution phase.",
                "Focused regression checks and manual runtime validation pass without introducing new failures.",
            ),
        )
        recovery_requirement = compact_text(
            " ".join(rollback_steps),
            max_chars=320,
        )
        plan_blueprints = (
            _PlanStepBlueprint(
                sequence=1,
                action_kind="verification",
                target=proposal.proposal_id,
                description=compact_text(
                    f"Verify that the approved proposal for '{candidate_name}' still matches the retained evidence, current inventory, and exact approval fingerprint.",
                    max_chars=400,
                ),
                inputs={
                    "proposal_fingerprint": proposal.proposal_fingerprint,
                    "approval_decision_id": approval.decision_id,
                    "evaluation_id": self._proposal_evaluation_id(proposal),
                    "evidence_ids": evaluation.evidence_ids if evaluation is not None else (),
                },
                expected_outcome="The proposal remains evidence-backed, current, and correctly bound to one exact approval decision.",
                risk_classification="low",
                metadata={"phase": "pre_change"},
            ),
            _PlanStepBlueprint(
                sequence=2,
                action_kind=action_kind,
                target=target,
                description=mutation_description,
                inputs=mutation_inputs,
                expected_outcome=compact_text(
                    f"A later execution phase could apply the approved '{candidate_category}' change for '{candidate_name}' without widening scope beyond the recorded plan.",
                    max_chars=320,
                ),
                verification_requirements=verification_requirements,
                recovery_requirement=recovery_requirement,
                risk_classification=self._risk_for_action(action_kind),
                metadata={"phase": "future_mutation"},
            ),
            _PlanStepBlueprint(
                sequence=3,
                action_kind="verification",
                target=target,
                description=compact_text(
                    f"Verify the future applied change for '{candidate_name}' using the approved verification checklist and affected-surface regressions.",
                    max_chars=400,
                ),
                inputs={"verification_plan": verification_steps, "affected_surfaces": proposal.affected_surfaces},
                expected_outcome="The future applied change is verified with focused regressions and no scope drift.",
                risk_classification="low",
                metadata={"phase": "post_change"},
            ),
            _PlanStepBlueprint(
                sequence=4,
                action_kind="recovery",
                target=target,
                description=compact_text(
                    f"If the future change for '{candidate_name}' fails or regresses the runtime, execute the documented recovery path and require renewed review.",
                    max_chars=400,
                ),
                inputs={"rollback_plan": rollback_steps},
                expected_outcome="The last verified pre-change state can be restored deterministically if later execution fails.",
                risk_classification="medium",
                metadata={"phase": "recovery_readiness"},
            ),
        )
        return plan_blueprints

    def _primary_plan_action(
        self,
        *,
        candidate_name: str,
        candidate_category: str,
    ) -> tuple[str, str, tuple[str, ...]]:
        """Return a conservative future mutation kind, target, and explicit missing details."""

        category = compact_text(candidate_category, max_chars=80) or "technology"
        if category == "package_management":
            return (
                "package_install",
                "unresolved package or dependency target",
                ("Exact package name and version were not confirmed by the retained evidence.",),
            )
        if category == "code_development":
            return (
                "source_modify",
                "unresolved source files and patch scope",
                ("Exact source files and patch contents remain unresolved before any future source mutation.",),
            )
        if category == "integration":
            return (
                "plugin_install",
                "unresolved plugin or integration artifact",
                ("Exact plugin or adapter identifier remains unresolved and must be confirmed before any later installation.",),
            )
        if category == "rollback_recovery":
            return (
                "service_integration",
                "rollback and recovery workflow",
                ("Exact rollback mechanism details remain unresolved and must be documented before execution.",),
            )
        if category == "sandbox_execution":
            return (
                "service_integration",
                f"{candidate_name} sandbox runtime surface",
                ("Exact sandbox runtime package and execution boundary details remain unresolved before integration.",),
            )
        if category == "computer_control":
            return (
                "service_integration",
                "computer control integration surface",
                ("Exact desktop-control integration points must be confirmed before any future host interaction.",),
            )
        return ("service_integration", candidate_name, ())

    def _risk_for_action(self, action_kind: str) -> str:
        """Return one conservative risk classification for a future action kind."""

        if action_kind in {"source_create", "source_modify", "source_delete", "os_configuration", "computer_control", "git_operation"}:
            return "high"
        if action_kind in _MUTATING_ACTION_KINDS:
            return "medium"
        return "low"

    def _materialize_plan_records(
        self,
        *,
        plan_id: str,
        proposal: ChangeProposal,
        approval: ApprovalDecision,
        blueprints: tuple[_PlanStepBlueprint, ...],
    ) -> tuple[tuple[VerificationRequirement, ...], tuple[RecoveryRequirement, ...], tuple[PlanStep, ...]]:
        """Convert deterministic blueprints into durable requirement and step records."""

        verification_requirements: list[VerificationRequirement] = []
        recovery_requirements: list[RecoveryRequirement] = []
        steps: list[PlanStep] = []
        for blueprint in blueprints:
            step_id = stable_id(
                "plan_step",
                plan_id,
                blueprint.sequence,
                blueprint.action_kind,
                blueprint.target,
                blueprint.description,
            )
            step_verification_ids: list[str] = []
            for index, (description, expected_signal) in enumerate(blueprint.verification_requirements, start=1):
                requirement = VerificationRequirement(
                    requirement_id=stable_id(
                        "verification_requirement",
                        plan_id,
                        step_id,
                        index,
                        description,
                        expected_signal,
                    ),
                    plan_id=plan_id,
                    proposal_id=proposal.proposal_id,
                    step_id=step_id,
                    description=compact_text(description, max_chars=320),
                    expected_signal=compact_text(expected_signal, max_chars=320),
                    metadata={
                        "proposal_fingerprint": proposal.proposal_fingerprint,
                        "approval_decision_id": approval.decision_id,
                    },
                )
                verification_requirements.append(requirement)
                step_verification_ids.append(requirement.requirement_id)
            recovery_requirement_id: str | None = None
            if blueprint.recovery_requirement:
                recovery = RecoveryRequirement(
                    recovery_id=stable_id(
                        "recovery_requirement",
                        plan_id,
                        step_id,
                        blueprint.recovery_requirement,
                    ),
                    plan_id=plan_id,
                    proposal_id=proposal.proposal_id,
                    step_id=step_id,
                    description=compact_text(blueprint.recovery_requirement, max_chars=320),
                    metadata={
                        "proposal_fingerprint": proposal.proposal_fingerprint,
                        "approval_decision_id": approval.decision_id,
                    },
                )
                recovery_requirements.append(recovery)
                recovery_requirement_id = recovery.recovery_id
            steps.append(
                PlanStep(
                    step_id=step_id,
                    plan_id=plan_id,
                    proposal_id=proposal.proposal_id,
                    sequence=blueprint.sequence,
                    action_kind=compact_text(blueprint.action_kind, max_chars=80),
                    target=compact_text(blueprint.target, max_chars=240),
                    description=compact_text(blueprint.description, max_chars=400),
                    inputs=dict(blueprint.inputs),
                    expected_outcome=compact_text(blueprint.expected_outcome, max_chars=320),
                    verification_requirement_ids=tuple(step_verification_ids),
                    recovery_requirement_id=recovery_requirement_id,
                    risk_classification=compact_text(blueprint.risk_classification, max_chars=80),
                    status="planned",
                    metadata={
                        "proposal_fingerprint": proposal.proposal_fingerprint,
                        "approval_decision_id": approval.decision_id,
                        **{key: value for key, value in dict(blueprint.metadata or {}).items() if value is not None},
                    },
                )
            )
        return tuple(verification_requirements), tuple(recovery_requirements), tuple(steps)

    def _build_change_plan_fingerprint(
        self,
        *,
        proposal: ChangeProposal,
        approval: ApprovalDecision,
        verification_requirements: tuple[VerificationRequirement, ...],
        recovery_requirements: tuple[RecoveryRequirement, ...],
        steps: tuple[PlanStep, ...],
    ) -> str:
        """Build one deterministic fingerprint from canonical semantic plan content."""

        payload = self._build_change_plan_fingerprint_payload(
            proposal=proposal,
            approval=approval,
            verification_requirements=verification_requirements,
            recovery_requirements=recovery_requirements,
            steps=steps,
        )
        return stable_id("change_plan_fingerprint", payload)

    def _build_change_plan_fingerprint_payload(
        self,
        *,
        proposal: ChangeProposal,
        approval: ApprovalDecision,
        verification_requirements: tuple[VerificationRequirement, ...],
        recovery_requirements: tuple[RecoveryRequirement, ...],
        steps: tuple[PlanStep, ...],
    ) -> dict[str, Any]:
        """Return the canonical semantic payload used to fingerprint one plan."""

        ordered_steps = tuple(
            sorted(
                steps,
                key=lambda item: (
                    int(item.sequence),
                    item.action_kind,
                    item.target,
                    item.description,
                    item.expected_outcome,
                ),
            )
        )
        step_sequence_by_id = {step.step_id: int(step.sequence) for step in ordered_steps}
        verification_by_step: dict[str, list[dict[str, Any]]] = {}
        for requirement in verification_requirements:
            verification_by_step.setdefault(requirement.step_id, []).append(
                {
                    "description": requirement.description,
                    "expected_signal": requirement.expected_signal,
                }
            )
        recovery_by_step: dict[str, dict[str, Any]] = {}
        for requirement in recovery_requirements:
            recovery_by_step[requirement.step_id] = {
                "description": requirement.description,
            }

        canonical_steps: list[dict[str, Any]] = []
        for step in ordered_steps:
            ordered_verifications = tuple(
                sorted(
                    verification_by_step.get(step.step_id, ()),
                    key=lambda item: (
                        item["description"],
                        item["expected_signal"],
                    ),
                )
            )
            canonical_steps.append(
                {
                    "sequence": int(step.sequence),
                    "action_kind": step.action_kind,
                    "target": step.target,
                    "description": step.description,
                    "inputs": dict(step.inputs),
                    "expected_outcome": step.expected_outcome,
                    "risk_classification": step.risk_classification,
                    "verification_requirements": ordered_verifications,
                    "recovery_requirement": recovery_by_step.get(step.step_id),
                }
            )

        ordered_verifications = tuple(
            sorted(
                (
                    {
                        "step_sequence": step_sequence_by_id.get(requirement.step_id, 0),
                        "description": requirement.description,
                        "expected_signal": requirement.expected_signal,
                    }
                    for requirement in verification_requirements
                ),
                key=lambda item: (
                    item["step_sequence"],
                    item["description"],
                    item["expected_signal"],
                ),
            )
        )
        ordered_recovery = tuple(
            sorted(
                (
                    {
                        "step_sequence": step_sequence_by_id.get(requirement.step_id, 0),
                        "description": requirement.description,
                    }
                    for requirement in recovery_requirements
                ),
                key=lambda item: (
                    item["step_sequence"],
                    item["description"],
                ),
            )
        )
        approval_version = int(approval.metadata.get("proposal_version", proposal.proposal_version) or proposal.proposal_version)
        return {
            "proposal_id": proposal.proposal_id,
            "proposal_fingerprint": proposal.proposal_fingerprint,
            "proposal_version": int(proposal.proposal_version),
            "approval_binding": {
                "proposal_id": approval.proposal_id,
                "proposal_fingerprint": approval.proposal_fingerprint,
                "proposal_version": approval_version,
                "decision": approval.decision,
            },
            "steps": tuple(canonical_steps),
            "verification_requirements": ordered_verifications,
            "recovery_requirements": ordered_recovery,
        }

    def _resolve_proposal(self, proposal: ChangeProposal | str) -> ChangeProposal | None:
        """Resolve a proposal reference into one persisted proposal."""

        if isinstance(proposal, ChangeProposal):
            return proposal
        return self.get_change_proposal(str(proposal))

    def _normalize_decision(self, *, decision: str | None, decision_text: str | None) -> str:
        """Normalize one explicit or free-form decision into a durable state."""

        explicit = compact_text(decision or "", max_chars=80).lower()
        if explicit in {"approved", "rejected", "pending", "expired"}:
            return explicit

        normalized_text = _normalize_decision_text(decision_text or "")
        if normalized_text in _APPROVAL_TEXTS:
            return "approved"
        if normalized_text in _REJECTION_TEXTS:
            return "rejected"
        return "pending"

    def _proposal_decisions_by_id(self, proposal_id: str) -> list[ApprovalDecision]:
        """Return every decision for one logical proposal id."""

        return [
            decision
            for decision in self._load_records("approval_decision", ApprovalDecision.from_dict)
            if decision.proposal_id == proposal_id
        ]

    def _decisions_for_proposal(self, proposal: ChangeProposal) -> list[ApprovalDecision]:
        """Return every decision for one exact proposal fingerprint."""

        return [
            decision
            for decision in self._proposal_decisions_by_id(proposal.proposal_id)
            if decision.proposal_fingerprint == proposal.proposal_fingerprint
        ]

    def _record_decision(
        self,
        proposal: ChangeProposal | str,
        *,
        decision: str,
        actor: str,
        note: str | None = None,
        proposal_fingerprint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalDecision:
        """Persist one durable approval decision and journal transition."""

        if isinstance(proposal, ChangeProposal):
            proposal_id = proposal.proposal_id
            fingerprint = proposal.proposal_fingerprint
            proposal_version = proposal.proposal_version
        else:
            proposal_id = str(proposal)
            if proposal_fingerprint is None:
                resolved = self.get_change_proposal(proposal_id)
                if resolved is None:
                    raise ValueError("A known proposal fingerprint is required for this decision.")
                fingerprint = resolved.proposal_fingerprint
                proposal_version = resolved.proposal_version
            else:
                fingerprint = proposal_fingerprint
                resolved = self.get_change_proposal(proposal_id, proposal_fingerprint=fingerprint)
                proposal_version = resolved.proposal_version if resolved is not None else 0

        previous_decisions = [
            item
            for item in self._proposal_decisions_by_id(proposal_id)
            if item.proposal_fingerprint == fingerprint
        ]
        previous_decisions.sort(key=lambda item: (item.created_at, item.decision_id))
        previous_state = previous_decisions[-1].decision if previous_decisions else "none"
        if previous_state == decision and compact_text(note or "", max_chars=320) == compact_text(previous_decisions[-1].note or "", max_chars=320):
            return previous_decisions[-1]

        approval_decision = ApprovalDecision(
            decision_id=stable_id("approval_decision", proposal_id, fingerprint, decision, actor, note or "", len(previous_decisions)),
            proposal_id=proposal_id,
            proposal_fingerprint=fingerprint,
            decision=decision,
            actor=compact_text(actor, max_chars=120),
            note=compact_text(note or "", max_chars=320) or None,
            metadata={
                "proposal_version": proposal_version,
                **{key: value for key, value in dict(metadata or {}).items() if value is not None},
            },
        )
        self._persist_record(
            category="approval_decision",
            key=f"evolution:approval_decision:{approval_decision.decision_id}",
            value=approval_decision.to_dict(),
            metadata={
                "proposal_id": approval_decision.proposal_id,
                "proposal_fingerprint": approval_decision.proposal_fingerprint,
                "decision": approval_decision.decision,
                "actor": approval_decision.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )
        self._persist_journal_entry(
            proposal_id=proposal_id,
            event_type="approval_expired" if decision == "expired" else "approval_decision_recorded",
            previous_state=previous_state,
            new_state=decision,
            actor=actor,
            details={
                "decision_id": approval_decision.decision_id,
                "proposal_fingerprint": fingerprint,
                "proposal_version": proposal_version,
                "note": approval_decision.note or "",
                **approval_decision.metadata,
            },
        )
        return approval_decision

    def _persist_journal_entry(
        self,
        *,
        proposal_id: str,
        event_type: str,
        previous_state: str,
        new_state: str,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> ChangeJournalEntry:
        """Persist one append-only change journal entry."""

        journal_entry = ChangeJournalEntry(
            journal_entry_id=stable_id(
                "change_journal",
                proposal_id,
                event_type,
                previous_state,
                new_state,
                actor,
                details or {},
                len(self.storage.list_entries(category="change_journal")),
            ),
            proposal_id=proposal_id,
            event_type=event_type,
            previous_state=compact_text(previous_state, max_chars=120),
            new_state=compact_text(new_state, max_chars=120),
            actor=compact_text(actor, max_chars=120),
            details=dict(details or {}),
        )
        self._persist_record(
            category="change_journal",
            key=f"evolution:change_journal:{journal_entry.journal_entry_id}",
            value=journal_entry.to_dict(),
            metadata={
                "proposal_id": journal_entry.proposal_id,
                "event_type": journal_entry.event_type,
                "actor": journal_entry.actor,
                "autonomy_level": self.autonomy_level.value,
            },
        )
        return journal_entry

    def _persist_candidate(self, candidate: DiscoveryCandidate) -> None:
        """Persist a candidate and each nested evidence record."""

        for evidence in candidate.evidence_records:
            self._persist_record(
                category="evidence_record",
                key=f"evolution:evidence_record:{evidence.evidence_id}",
                value=evidence.to_dict(),
                metadata={
                    "autonomy_level": self.autonomy_level.value,
                    "candidate_id": candidate.candidate_id,
                    "evidence_id": evidence.evidence_id,
                },
            )
        self._persist_record(
            category="discovery_candidate",
            key=f"evolution:discovery_candidate:{candidate.candidate_id}",
            value=candidate.to_dict(),
            metadata={
                "autonomy_level": self.autonomy_level.value,
                "candidate_id": candidate.candidate_id,
                "technology_category": candidate.technology_category,
            },
        )

    def _persist_record(self, *, category: str, key: str, value: dict[str, Any], metadata: dict[str, Any]) -> None:
        """Persist one evolution record through the existing memory storage."""

        entry = MemoryEntry(
            key=key,
            value=value,
            category=category,
            metadata=metadata,
        )
        self.storage.save(entry)

    def _load_records(self, category: str, factory: Any) -> list[Any]:
        """Load and reconstruct stored evolution records for one category."""

        loaded: list[Any] = []
        for entry in self.storage.list_entries(category=category):
            if not isinstance(entry.value, dict):
                continue
            loaded.append(factory(dict(entry.value)))
        return loaded


def build_evolution_service(
    *,
    config: Any,
    storage: Any,
    short_term_memory: Any,
    long_term_memory: Any,
    session_memory: Any,
    profile_memory: Any,
    internet_service: Any,
    skill_registry: Any,
    plugin_registry: Any,
    ai_provider: Any,
    voice_runtime_service: Any | None = None,
    vision_service: Any | None = None,
    policy: EvolutionPolicy | None = None,
    logger: Any | None = None,
) -> SelfEvolutionService:
    """Build the observe-only evolution runtime service."""

    inventory_builder = CapabilityInventoryBuilder(
        config=config,
        ai_provider=ai_provider,
        memory_storage=storage,
        short_term_memory=short_term_memory,
        long_term_memory=long_term_memory,
        session_memory=session_memory,
        profile_memory=profile_memory,
        internet_service=internet_service,
        skill_registry=skill_registry,
        plugin_registry=plugin_registry,
        voice_runtime_service=voice_runtime_service,
        vision_service=vision_service,
        logger=logger,
    )
    workspace_root = Path.cwd().resolve()
    mutation_surface_registry = MutationSurfaceRegistry(workspace_root=workspace_root)
    mutation_guard_service = MutationGuardService(surface_registry=mutation_surface_registry)
    mutation_approval_service = MutationApprovalService()
    mutation_run_service = MutationRunService()
    sandbox_executor_service = SandboxExecutorService(sandbox_root=workspace_root / "data" / "evolution_sandbox")
    package_executor_service = PackageExecutorService()
    source_executor_service = SourceExecutorService(
        workspace_root=workspace_root,
        surface_registry=mutation_surface_registry,
    )
    plugin_executor_service = PluginExecutorService(surface_registry=mutation_surface_registry)
    git_executor_service = GitExecutorService(repository_root=workspace_root)
    task_planner_service = TaskPlannerService()
    risk_analyzer_service = RiskAnalyzerService()
    execution_scheduler_service = ExecutionSchedulerService()
    workflow_engine_service = WorkflowEngineService()
    decision_engine_service = DecisionEngineService()
    action_registry_service = ActionRegistryService()
    execution_context_service = ExecutionContextService()
    execution_validator_service = ExecutionValidatorService(
        action_registry=action_registry_service,
        context_service=execution_context_service,
        mutation_guard=mutation_guard_service,
    )
    desktop_executor_service = DesktopExecutorService()
    application_executor_service = ApplicationExecutorService()
    browser_executor_service = BrowserExecutorService()
    workflow_executor_service = WorkflowExecutorService()
    service = SelfEvolutionService(
        storage=storage,
        internet_service=internet_service,
        inventory_builder=inventory_builder,
        mutation_surface_registry=mutation_surface_registry,
        mutation_guard_service=mutation_guard_service,
        mutation_approval_service=mutation_approval_service,
        mutation_run_service=mutation_run_service,
        sandbox_executor_service=sandbox_executor_service,
        package_executor_service=package_executor_service,
        source_executor_service=source_executor_service,
        plugin_executor_service=plugin_executor_service,
        git_executor_service=git_executor_service,
        task_planner_service=task_planner_service,
        risk_analyzer_service=risk_analyzer_service,
        execution_scheduler_service=execution_scheduler_service,
        workflow_engine_service=workflow_engine_service,
        decision_engine_service=decision_engine_service,
        action_registry_service=action_registry_service,
        execution_context_service=execution_context_service,
        execution_validator_service=execution_validator_service,
        desktop_executor_service=desktop_executor_service,
        application_executor_service=application_executor_service,
        browser_executor_service=browser_executor_service,
        workflow_executor_service=workflow_executor_service,
        policy=policy,
        logger=logger,
    )
    _emit_log(logger, "info", "Built evolution service", autonomy_level=service.autonomy_level.value)
    return service


def register_evolution_services(
    container: DependencyRegistrar,
    service: SelfEvolutionService,
    *,
    logger: Any | None = None,
) -> SelfEvolutionService:
    """Register the evolution runtime service in the dependency container."""

    container.register_instance("evolution_service", service)
    container.register_instance("self_evolution_service", service)
    container.register_instance("evolution_policy", service.policy)
    container.register_instance("mutation_surface_registry", service.mutation_surface_registry)
    container.register_instance("mutation_guard_service", service.mutation_guard_service)
    container.register_instance("mutation_approval_service", service.mutation_approval_service)
    container.register_instance("mutation_run_service", service.mutation_run_service)
    container.register_instance("sandbox_executor_service", service.sandbox_executor_service)
    container.register_instance("package_executor_service", service.package_executor_service)
    container.register_instance("source_executor_service", service.source_executor_service)
    container.register_instance("plugin_executor_service", service.plugin_executor_service)
    container.register_instance("git_executor_service", service.git_executor_service)
    container.register_instance("task_planner_service", service.task_planner_service)
    container.register_instance("risk_analyzer_service", service.risk_analyzer_service)
    container.register_instance("execution_scheduler_service", service.execution_scheduler_service)
    container.register_instance("workflow_engine_service", service.workflow_engine_service)
    container.register_instance("decision_engine_service", service.decision_engine_service)
    container.register_instance("action_registry_service", service.action_registry_service)
    container.register_instance("execution_context_service", service.execution_context_service)
    container.register_instance("execution_validator_service", service.execution_validator_service)
    container.register_instance("desktop_executor_service", service.desktop_executor_service)
    container.register_instance("application_executor_service", service.application_executor_service)
    container.register_instance("browser_executor_service", service.browser_executor_service)
    container.register_instance("workflow_executor_service", service.workflow_executor_service)
    _emit_log(logger, "info", "Registered evolution services in container", autonomy_level=service.autonomy_level.value)
    return service


__all__ = [
    "EvolutionPolicy",
    "MutationExecutorSelection",
    "Phase8MutationExecutionRequest",
    "Phase8MutationExecutionResult",
    "Phase9PlanningPipelineRequest",
    "Phase9PlanningPipelineResult",
    "SelfEvolutionService",
    "build_evolution_service",
    "register_evolution_services",
]
