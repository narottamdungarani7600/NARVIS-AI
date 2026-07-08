"""Read-only runtime service for observe-only self-evolution work."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from Internet.research import ResearchQuery
from Memory.memory import MemoryEntry

from .inventory import CapabilityInventoryBuilder
from .models import (
    CapabilityGap,
    CapabilityInventorySnapshot,
    DiscoveryCandidate,
    DiscoveryQueryResult,
    EvaluationRecord,
    EvidenceRecord,
    EvolutionAutonomyLevel,
    LearnedOutcome,
    compact_text,
    normalize_identity,
    slugify,
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


class SelfEvolutionService:
    """Observe-only read-only self-evolution service."""

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
            raise ValueError("Self-Evolution Phase 1 only supports observe_only autonomy.")

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
