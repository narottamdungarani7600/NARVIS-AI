"""Observe-only self-evolution runtime with durable proposal, planning, and execution-boundary records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from Internet.research import ResearchQuery
from Memory.memory import MemoryEntry

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
    PlanStep,
    RecoveryRequirement,
    VerificationRequirement,
    compact_text,
    normalize_identity,
    stable_id,
)

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


class SelfEvolutionService:
    """Observe-only self-evolution service with approval-bound planning and authorization support."""

    def __init__(
        self,
        *,
        storage: Any,
        internet_service: Any,
        inventory_builder: CapabilityInventoryBuilder,
        policy: EvolutionPolicy | None = None,
        logger: Any | None = None,
    ) -> None:
        self.storage = storage
        self.internet_service = internet_service
        self.inventory_builder = inventory_builder
        self.policy = policy or EvolutionPolicy()
        self.logger = logger
        if self.policy.autonomy_level is not EvolutionAutonomyLevel.OBSERVE_ONLY:
            raise ValueError("Self-Evolution currently supports observe_only autonomy only.")

    @property
    def autonomy_level(self) -> EvolutionAutonomyLevel:
        """Return the active autonomy level."""

        return self.policy.autonomy_level

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
    service = SelfEvolutionService(
        storage=storage,
        internet_service=internet_service,
        inventory_builder=inventory_builder,
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
    _emit_log(logger, "info", "Registered evolution services in container", autonomy_level=service.autonomy_level.value)
    return service


__all__ = [
    "EvolutionPolicy",
    "SelfEvolutionService",
    "build_evolution_service",
    "register_evolution_services",
]
