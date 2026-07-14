"""Comprehensive tests for Phase 9 Skill & Agent Framework Sprint 3."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from Agents.core import (
    AgentRuntime,
    DependencyValidationError,
    EmptyPlanError,
    InvalidIntentError,
    Plan,
    PlanStep,
    PlanningContext,
    PlanningStatus,
    SkillResolutionError,
    TaskPlanner,
    WorkflowDefinition,
    WorkflowStep,
    WorkflowValidationError,
    WorkflowValidator,
    validate_plan,
    validate_workflow,
)
from Core.logger import LogLevel
from Core.system import EventBus, SystemEvent
from Skills.core import (
    SkillCapability,
    SkillDefinition,
    SkillInterface,
    SkillMetadata,
    SkillResolver,
)


class _NeverExecuteSkill(SkillInterface[object, object]):
    """Skill implementation that fails if planning attempts execution."""

    def __init__(self) -> None:
        self.execute_calls = 0

    def initialize(self) -> None:
        return None

    def execute(self, request: object) -> object:
        self.execute_calls += 1
        raise AssertionError("planning must not execute a skill")

    def shutdown(self) -> None:
        return None


class _CapturingLogger:
    """Core-compatible logger used to verify planning lifecycle logs."""

    def __init__(self) -> None:
        self.entries: list[tuple[LogLevel, str, dict[str, object]]] = []

    def log(self, level: LogLevel, message: str, **context: object) -> None:
        self.entries.append((level, message, context))


class _StaticPlanner:
    """Controllable planner dependency for runtime validation tests."""

    event_bus = None

    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def plan(
        self,
        user_intent: str,
        context: PlanningContext | None = None,
        *,
        requested_capabilities: object = None,
    ) -> object:
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _FailingEventBus:
    """Publisher used to ensure event failures do not change planning."""

    def publish(self, event: SystemEvent) -> None:
        raise RuntimeError("event bus unavailable")


def _skill(
    name: str = "communication.mail",
    *capabilities: str,
) -> tuple[SkillDefinition, _NeverExecuteSkill]:
    implementation = _NeverExecuteSkill()
    definition = SkillDefinition(
        metadata=SkillMetadata(
            name=name,
            capabilities=tuple(
                SkillCapability(capability)
                for capability in (capabilities or ("email.send",))
            ),
        ),
        implementation=implementation,
    )
    return definition, implementation


def _plan_step(
    step_id: str,
    order: int,
    *,
    dependencies: tuple[str, ...] = (),
    optional: bool = False,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        order=order,
        description=f"Plan {step_id}",
        skill_name="test.skill",
        capabilities=(f"test.{step_id}",),
        dependencies=dependencies,
        optional=optional,
    )


def _workflow_step(
    step_id: str,
    order: int,
    *,
    dependencies: tuple[str, ...] = (),
    optional: bool = False,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        order=order,
        description=f"Plan {step_id}",
        dependencies=dependencies,
        optional=optional,
    )


class PlanningContextTests(unittest.TestCase):
    """Verify planning context is typed, detached, and ephemeral."""

    def test_context_detaches_mappings_and_sorts_available_skills(self) -> None:
        first, _ = _skill("z.skill", "z.run")
        second, _ = _skill("a.skill", "a.run")
        conversation = {"last_message": "hello"}
        context = PlanningContext(
            conversation_context=conversation,
            memory_context={"preference": "concise"},
            user_context={"user_id": "user-1"},
            available_skills=(first, second),
        )
        conversation["last_message"] = "changed"

        self.assertEqual(context.conversation["last_message"], "hello")
        self.assertEqual(context.memory["preference"], "concise")
        self.assertEqual(context.user["user_id"], "user-1")
        self.assertEqual(
            [skill.name for skill in context.available_skills],
            ["a.skill", "z.skill"],
        )
        with self.assertRaises(TypeError):
            context.conversation_context["new"] = True  # type: ignore[index]

    def test_context_rejects_untyped_mappings_skills_and_duplicate_names(self) -> None:
        definition, _ = _skill()
        duplicate, _ = _skill("COMMUNICATION.MAIL")

        with self.assertRaises(TypeError):
            PlanningContext(conversation_context=[])  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            PlanningContext(available_skills=(object(),))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            PlanningContext(available_skills=(definition, duplicate))


class PlanningModelTests(unittest.TestCase):
    """Verify planning and workflow model invariants."""

    def test_plan_models_are_immutable_and_expose_ordered_steps(self) -> None:
        second = _plan_step("second", 2, dependencies=("first",))
        first = _plan_step("first", 1)
        metadata = {"source": "test"}
        plan = Plan(
            plan_id="plan-1",
            intent="test intent",
            steps=(second, first),
            metadata=metadata,
        )
        metadata["source"] = "changed"

        self.assertEqual(plan.user_intent, "test intent")
        self.assertEqual(
            [step.step_id for step in plan.ordered_steps],
            ["first", "second"],
        )
        self.assertEqual(second.sequence, 2)
        self.assertEqual(second.depends_on, ("first",))
        self.assertEqual(plan.metadata["source"], "test")
        with self.assertRaises(FrozenInstanceError):
            plan.status = PlanningStatus.COMPLETED  # type: ignore[misc]

    def test_models_reject_invalid_scalar_and_collection_values(self) -> None:
        with self.assertRaises(ValueError):
            _plan_step("first", 0)
        with self.assertRaises(TypeError):
            PlanStep(
                step_id="first",
                order=True,  # type: ignore[arg-type]
                description="Plan first",
                skill_name="test.skill",
            )
        with self.assertRaises(ValueError):
            Plan(plan_id=" plan-1 ", intent="valid", steps=())
        with self.assertRaises(TypeError):
            Plan(
                plan_id="plan-1",
                intent="valid",
                steps=(object(),),  # type: ignore[arg-type]
            )
        with self.assertRaises(ValueError):
            _workflow_step("first", 1, dependencies=("same", "same"))

    def test_workflow_identity_is_deterministic_and_preserves_optional_flag(
        self,
    ) -> None:
        steps = (
            _workflow_step("first", 1),
            _workflow_step("second", 2, dependencies=("first",), optional=True),
        )

        first = WorkflowDefinition(name="mail workflow", steps=steps)
        second = WorkflowDefinition(name="mail workflow", steps=steps)

        self.assertEqual(first.workflow_id, second.workflow_id)
        self.assertTrue(first.ordered_steps[1].optional)
        self.assertEqual(first.ordered_steps[1].sequence, 2)


class TaskPlannerTests(unittest.TestCase):
    """Verify deterministic skill-backed planning without execution."""

    def test_planner_resolves_skill_and_builds_ordered_dependent_steps(self) -> None:
        definition, implementation = _skill(
            "communication.mail",
            "email.compose",
            "email.send",
        )
        planner = TaskPlanner(SkillResolver())
        context = PlanningContext(available_skills=(definition,))

        plan = planner.plan("Compose and send email", context)

        self.assertEqual(plan.status, PlanningStatus.CREATED)
        self.assertEqual(plan.metadata["selected_skill"], "communication.mail")
        self.assertEqual(
            [step.capabilities for step in plan.steps],
            [("email.compose",), ("email.send",)],
        )
        self.assertEqual(plan.steps[0].dependencies, ())
        self.assertEqual(plan.steps[1].dependencies, (plan.steps[0].step_id,))
        self.assertTrue(all(step.skill_name == definition.name for step in plan.steps))
        self.assertEqual(implementation.execute_calls, 0)

    def test_planner_is_deterministic_across_context_skill_order(self) -> None:
        matching, _ = _skill("mail.primary", "email.send")
        other, _ = _skill("status.read", "status.read")
        first_context = PlanningContext(available_skills=(matching, other))
        second_context = PlanningContext(available_skills=(other, matching))
        planner = TaskPlanner(SkillResolver())

        first = planner.plan("send email", first_context)
        second = planner.create_plan("send   email", second_context)

        self.assertEqual(first.plan_id, second.plan_id)
        self.assertEqual(first.steps, second.steps)

    def test_planner_accepts_explicit_capabilities(self) -> None:
        definition, _ = _skill("mail.primary", "email.send")
        plan = TaskPlanner(SkillResolver()).plan(
            "Deliver the prepared message",
            PlanningContext(available_skills=(definition,)),
            requested_capabilities=("email.send",),
        )

        self.assertEqual(plan.steps[0].capabilities, ("email.send",))

    def test_planner_rejects_invalid_intent_and_unresolved_skills(self) -> None:
        definition, _ = _skill("mail.primary", "email.send")
        planner = TaskPlanner(SkillResolver())
        context = PlanningContext(available_skills=(definition,))

        with self.assertRaises(InvalidIntentError):
            planner.plan("   ", context)
        with self.assertRaises(InvalidIntentError):
            planner.plan("valid", context, requested_capabilities=())
        with self.assertRaises(SkillResolutionError):
            planner.plan("read weather", context)

    def test_planner_publishes_created_event_and_logs_creation(self) -> None:
        definition, _ = _skill()
        event_bus = EventBus()
        events: list[SystemEvent] = []
        event_bus.subscribe("plan.created", events.append)
        logger = _CapturingLogger()
        planner = TaskPlanner(
            SkillResolver(),
            logger=logger,
            event_bus=event_bus,
        )

        plan = planner.plan(
            "send email",
            PlanningContext(available_skills=(definition,)),
        )

        self.assertEqual([event.name for event in events], ["plan.created"])
        self.assertEqual(events[0].payload["plan_id"], plan.plan_id)
        self.assertFalse(events[0].payload["execution_performed"])
        self.assertTrue(
            any(message == "Plan created" for _, message, _ in logger.entries)
        )


class WorkflowValidationTests(unittest.TestCase):
    """Verify sequential, optional, and dependency validation behavior."""

    def test_valid_plan_and_workflow_support_optional_dependent_steps(self) -> None:
        plan = Plan(
            plan_id="plan-valid",
            intent="valid plan",
            steps=(
                _plan_step("first", 1),
                _plan_step("second", 2, dependencies=("first",), optional=True),
            ),
        )
        workflow = WorkflowDefinition(
            name="valid workflow",
            steps=(
                _workflow_step("first", 1),
                _workflow_step("second", 2, dependencies=("first",), optional=True),
            ),
        )
        validator = WorkflowValidator()

        self.assertIs(validate_plan(plan), plan)
        self.assertIs(validate_workflow(workflow), workflow)
        self.assertIs(validator.validate(plan), plan)
        self.assertIs(validator.validate_workflow(workflow), workflow)
        self.assertTrue(validator.is_valid(plan))

    def test_empty_plans_and_workflows_are_invalid(self) -> None:
        empty_plan = Plan(plan_id="plan-empty", intent="empty plan", steps=())
        empty_workflow = WorkflowDefinition(name="empty workflow")

        with self.assertRaises(EmptyPlanError):
            validate_plan(empty_plan)
        with self.assertRaises(WorkflowValidationError):
            validate_workflow(empty_workflow)
        self.assertFalse(WorkflowValidator().is_valid(empty_plan))

    def test_duplicate_and_noncontiguous_order_values_are_invalid(self) -> None:
        duplicate = Plan(
            plan_id="plan-duplicate",
            intent="duplicate order",
            steps=(_plan_step("first", 1), _plan_step("second", 1)),
        )
        noncontiguous = WorkflowDefinition(
            name="noncontiguous workflow",
            steps=(_workflow_step("first", 1), _workflow_step("second", 3)),
        )

        with self.assertRaises(ValueError):
            validate_plan(duplicate)
        with self.assertRaises(WorkflowValidationError):
            validate_workflow(noncontiguous)

    def test_missing_self_and_forward_dependencies_are_invalid(self) -> None:
        missing = Plan(
            plan_id="plan-missing",
            intent="missing dependency",
            steps=(_plan_step("first", 1, dependencies=("unknown",)),),
        )
        self_dependency = WorkflowDefinition(
            name="self dependency",
            steps=(_workflow_step("first", 1, dependencies=("first",)),),
        )
        forward = WorkflowDefinition(
            name="forward dependency",
            steps=(
                _workflow_step("first", 1, dependencies=("second",)),
                _workflow_step("second", 2),
            ),
        )

        with self.assertRaises(DependencyValidationError):
            validate_plan(missing)
        with self.assertRaises(DependencyValidationError):
            validate_workflow(self_dependency)
        with self.assertRaises(DependencyValidationError):
            validate_workflow(forward)

    def test_validator_rejects_untyped_values(self) -> None:
        validator = WorkflowValidator()

        with self.assertRaises(TypeError):
            validator.validate(object())  # type: ignore[arg-type]
        self.assertFalse(validator.is_valid(object()))  # type: ignore[arg-type]


class AgentRuntimeTests(unittest.TestCase):
    """Verify lifecycle results, validation, events, and logging."""

    def test_runtime_completes_planning_and_publishes_lifecycle_events(self) -> None:
        definition, implementation = _skill()
        event_bus = EventBus()
        events: list[SystemEvent] = []
        for event_name in ("plan.created", "plan.validated", "plan.completed"):
            event_bus.subscribe(event_name, events.append)
        logger = _CapturingLogger()
        planner = TaskPlanner(
            SkillResolver(),
            logger=logger,
            event_bus=event_bus,
        )
        runtime = AgentRuntime(planner, logger=logger, event_bus=event_bus)

        result = runtime.plan(
            "send email",
            PlanningContext(available_skills=(definition,)),
        )

        self.assertTrue(result.successful)
        self.assertTrue(result.completed)
        self.assertEqual(result.status, PlanningStatus.COMPLETED)
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(result.plan.status, PlanningStatus.COMPLETED)
        self.assertEqual(
            [event.name for event in events],
            ["plan.created", "plan.validated", "plan.completed"],
        )
        self.assertTrue(events[-1].payload["successful"])
        self.assertTrue(
            all(not event.payload["execution_performed"] for event in events)
        )
        messages = [message for _, message, _ in logger.entries]
        self.assertIn("Plan created", messages)
        self.assertIn("Plan validated", messages)
        self.assertIn("Planning completed", messages)
        self.assertEqual(implementation.execute_calls, 0)
        self.assertFalse(result.metadata["executor_invoked"])

    def test_runtime_publishes_created_when_only_runtime_has_event_bus(self) -> None:
        definition, _ = _skill()
        planner = TaskPlanner(SkillResolver())
        event_bus = EventBus()
        events: list[SystemEvent] = []
        for event_name in ("plan.created", "plan.validated", "plan.completed"):
            event_bus.subscribe(event_name, events.append)

        result = AgentRuntime(planner, event_bus=event_bus).create_plan(
            "send email",
            PlanningContext(available_skills=(definition,)),
        )

        self.assertTrue(result.successful)
        self.assertEqual(
            [event.name for event in events],
            ["plan.created", "plan.validated", "plan.completed"],
        )

    def test_runtime_returns_invalid_result_for_empty_plan(self) -> None:
        empty_plan = Plan(plan_id="empty-plan", intent="empty", steps=())
        event_bus = EventBus()
        events: list[SystemEvent] = []
        for event_name in ("plan.created", "plan.validated", "plan.completed"):
            event_bus.subscribe(event_name, events.append)

        result = AgentRuntime(
            _StaticPlanner(empty_plan),  # type: ignore[arg-type]
            event_bus=event_bus,
        ).plan("empty")

        self.assertEqual(result.status, PlanningStatus.INVALID)
        self.assertFalse(result.successful)
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(result.plan.status, PlanningStatus.INVALID)
        self.assertEqual(
            [event.name for event in events],
            ["plan.created", "plan.completed"],
        )

    def test_runtime_returns_invalid_result_for_bad_dependencies(self) -> None:
        plan = Plan(
            plan_id="bad-dependency-plan",
            intent="bad dependency",
            steps=(_plan_step("first", 1, dependencies=("missing",)),),
        )

        result = AgentRuntime(_StaticPlanner(plan)).plan(  # type: ignore[arg-type]
            "bad dependency"
        )

        self.assertEqual(result.status, PlanningStatus.INVALID)
        self.assertIn("missing", result.errors[0])

    def test_runtime_returns_failed_for_planner_failures_and_bad_values(
        self,
    ) -> None:
        failure = AgentRuntime(
            _StaticPlanner(  # type: ignore[arg-type]
                InvalidIntentError("intent required")
            )
        ).plan("")
        invalid_value = AgentRuntime(
            _StaticPlanner(object())  # type: ignore[arg-type]
        ).plan("valid")

        self.assertEqual(failure.status, PlanningStatus.FAILED)
        self.assertEqual(failure.errors, ("intent required",))
        self.assertIsNone(failure.plan)
        self.assertEqual(invalid_value.status, PlanningStatus.FAILED)
        self.assertFalse(invalid_value.metadata["execution_performed"])

    def test_event_and_logger_failures_do_not_change_successful_result(self) -> None:
        definition, _ = _skill()
        planner = TaskPlanner(
            SkillResolver(),
            logger=_CapturingLogger(),
            event_bus=_FailingEventBus(),
        )
        runtime = AgentRuntime(
            planner,
            logger=_CapturingLogger(),
            event_bus=_FailingEventBus(),
        )

        result = runtime.plan(
            "send email",
            PlanningContext(available_skills=(definition,)),
        )

        self.assertTrue(result.successful)


if __name__ == "__main__":
    unittest.main()
