"""Typed models for the observe-only Self-Evolution proposal, planning, and execution boundary foundation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

SCHEMA_VERSION = "evolution.v1"
_WHITESPACE_PATTERN = re.compile(r"\s+")
_NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


def compact_text(value: str, *, max_chars: int = 320) -> str:
    """Normalize whitespace and bound a text value for durable storage."""

    normalized = _WHITESPACE_PATTERN.sub(" ", str(value or "").strip())
    if len(normalized) <= max_chars:
        return normalized
    trimmed = normalized[:max_chars].rsplit(" ", 1)[0].strip()
    return trimmed or normalized[:max_chars].strip()


def normalize_identity(value: str) -> str:
    """Normalize user-facing text into a stable identity key."""

    normalized = compact_text(value, max_chars=200).lower()
    return normalized


def stable_id(namespace: str, *parts: Any) -> str:
    """Build a deterministic identifier from one namespace and stable payload."""

    payload = json.dumps(
        [namespace, *[_sanitize_value(part) for part in parts]],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"{namespace}-{digest[:16]}"


def slugify(value: str) -> str:
    """Create a stable ASCII-friendly slug."""

    normalized = _NON_WORD_PATTERN.sub("-", normalize_identity(value)).strip("-")
    return normalized or "record"


def parse_timestamp(value: Any) -> datetime:
    """Parse one persisted timestamp into a timezone-aware UTC datetime."""

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return utc_now()
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return utc_now()


def _sanitize_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Return a metadata mapping without executable or oversized payloads."""

    sanitized: dict[str, Any] = {}
    for key, value in sorted(mapping.items()):
        cleaned_key = compact_text(str(key), max_chars=80)
        if not cleaned_key:
            continue
        cleaned_value = _sanitize_value(value)
        if cleaned_value is None:
            continue
        sanitized[cleaned_key] = cleaned_value
    return sanitized


def _sanitize_value(value: Any) -> Any:
    """Convert arbitrary values into safe, JSON-friendly durable payloads."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return compact_text(value, max_chars=400)
    if isinstance(value, datetime):
        return parse_timestamp(value).isoformat()
    if callable(value):
        return None
    if isinstance(value, dict):
        return _sanitize_mapping(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        sanitized_items = [_sanitize_value(item) for item in value]
        return [item for item in sanitized_items if item is not None]
    return compact_text(str(value), max_chars=400)


def sanitize_durable_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Expose the internal durable-metadata sanitizer for runtime helpers."""

    return _sanitize_mapping(mapping)


def sanitize_durable_value(value: Any) -> Any:
    """Expose the internal durable-value sanitizer for runtime helpers."""

    return _sanitize_value(value)


def _deserialize_string_list(values: Any) -> tuple[str, ...]:
    """Convert persisted sequences into one normalized string tuple."""

    if not isinstance(values, list | tuple):
        return ()
    normalized: list[str] = []
    for value in values:
        text = compact_text(str(value), max_chars=240)
        if text:
            normalized.append(text)
    return tuple(normalized)


class EvolutionAutonomyLevel(str, Enum):
    """Represent staged autonomy levels for future self-evolution work."""

    OBSERVE_ONLY = "observe_only"
    DISCOVER_AND_REPORT = "discover_and_report"
    EVALUATE_AND_RECOMMEND = "evaluate_and_recommend"
    PREPARE_SANDBOX_EXPERIMENT = "prepare_sandbox_experiment"
    RUN_APPROVED_SANDBOX_EXPERIMENTS = "run_approved_sandbox_experiments"
    INTEGRATE_APPROVED_LOW_RISK_CAPABILITIES = "integrate_approved_low_risk_capabilities"
    HIGHER_AUTONOMY = "higher_autonomy"


@dataclass(slots=True, frozen=True)
class CapabilityRecord:
    """One deterministic fact about the current NARVIS capability surface."""

    capability_id: str
    name: str
    category: str
    status: str
    implementation: str = ""
    source_of_truth: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "capability_id": self.capability_id,
            "name": compact_text(self.name, max_chars=120),
            "category": compact_text(self.category, max_chars=80),
            "status": compact_text(self.status, max_chars=80),
            "implementation": compact_text(self.implementation, max_chars=120),
            "source_of_truth": compact_text(self.source_of_truth, max_chars=120),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CapabilityRecord":
        """Restore a capability record from durable storage."""

        return cls(
            capability_id=str(value.get("capability_id", "")),
            name=str(value.get("name", "")),
            category=str(value.get("category", "")),
            status=str(value.get("status", "")),
            implementation=str(value.get("implementation", "")),
            source_of_truth=str(value.get("source_of_truth", "")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class CapabilityInventorySnapshot:
    """A durable inventory snapshot of the current NARVIS capabilities."""

    snapshot_id: str
    capabilities: tuple[CapabilityRecord, ...]
    autonomy_level: EvolutionAutonomyLevel = EvolutionAutonomyLevel.OBSERVE_ONLY
    schema_version: str = SCHEMA_VERSION
    captured_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "snapshot_id": self.snapshot_id,
            "capabilities": [record.to_dict() for record in self.capabilities],
            "autonomy_level": self.autonomy_level.value,
            "schema_version": self.schema_version,
            "captured_at": parse_timestamp(self.captured_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CapabilityInventorySnapshot":
        """Restore an inventory snapshot from durable storage."""

        capabilities = tuple(
            CapabilityRecord.from_dict(item)
            for item in value.get("capabilities", [])
            if isinstance(item, dict)
        )
        autonomy_level = EvolutionAutonomyLevel(str(value.get("autonomy_level", EvolutionAutonomyLevel.OBSERVE_ONLY.value)))
        return cls(
            snapshot_id=str(value.get("snapshot_id", "")),
            capabilities=capabilities,
            autonomy_level=autonomy_level,
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            captured_at=parse_timestamp(value.get("captured_at")),
        )


@dataclass(slots=True, frozen=True)
class EvidenceRecord:
    """A bounded untrusted evidence fragment retained for later evaluation."""

    evidence_id: str
    source_identity: str
    source_url: str
    title: str
    summary: str
    bounded_text: str
    provenance_label: str
    trust_label: str
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    retrieved_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "evidence_id": self.evidence_id,
            "source_identity": compact_text(self.source_identity, max_chars=120),
            "source_url": compact_text(self.source_url, max_chars=400),
            "title": compact_text(self.title, max_chars=240),
            "summary": compact_text(self.summary, max_chars=320),
            "bounded_text": compact_text(self.bounded_text, max_chars=400),
            "provenance_label": compact_text(self.provenance_label, max_chars=80),
            "trust_label": compact_text(self.trust_label, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "retrieved_at": parse_timestamp(self.retrieved_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvidenceRecord":
        """Restore an evidence record from durable storage."""

        return cls(
            evidence_id=str(value.get("evidence_id", "")),
            source_identity=str(value.get("source_identity", "")),
            source_url=str(value.get("source_url", "")),
            title=str(value.get("title", "")),
            summary=str(value.get("summary", "")),
            bounded_text=str(value.get("bounded_text", "")),
            provenance_label=str(value.get("provenance_label", "grounded_public_web")),
            trust_label=str(value.get("trust_label", "unverified_public_web")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            retrieved_at=parse_timestamp(value.get("retrieved_at")),
        )


@dataclass(slots=True, frozen=True)
class DiscoveryCandidate:
    """A discovered technology candidate backed by untrusted evidence data."""

    candidate_id: str
    name: str
    normalized_name: str
    technology_category: str
    short_description: str
    status: str
    evidence_records: tuple[EvidenceRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    discovered_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "candidate_id": self.candidate_id,
            "name": compact_text(self.name, max_chars=160),
            "normalized_name": compact_text(self.normalized_name, max_chars=160),
            "technology_category": compact_text(self.technology_category, max_chars=80),
            "short_description": compact_text(self.short_description, max_chars=400),
            "status": compact_text(self.status, max_chars=80),
            "evidence_records": [record.to_dict() for record in self.evidence_records],
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "discovered_at": parse_timestamp(self.discovered_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscoveryCandidate":
        """Restore a discovery candidate from durable storage."""

        evidence_records = tuple(
            EvidenceRecord.from_dict(item)
            for item in value.get("evidence_records", [])
            if isinstance(item, dict)
        )
        return cls(
            candidate_id=str(value.get("candidate_id", "")),
            name=str(value.get("name", "")),
            normalized_name=str(value.get("normalized_name", "")),
            technology_category=str(value.get("technology_category", "technology")),
            short_description=str(value.get("short_description", "")),
            status=str(value.get("status", "discovered")),
            evidence_records=evidence_records,
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            discovered_at=parse_timestamp(value.get("discovered_at")),
        )


@dataclass(slots=True, frozen=True)
class DiscoveryQueryResult:
    """A structured outcome for one observe-only discovery query."""

    query: str
    status: str
    candidates: tuple[DiscoveryCandidate, ...] = ()
    error: str | None = None
    search_provider_name: str = ""
    source_count: int = 0
    autonomy_level: EvolutionAutonomyLevel = EvolutionAutonomyLevel.OBSERVE_ONLY
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "query": compact_text(self.query, max_chars=200),
            "status": compact_text(self.status, max_chars=80),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "error": compact_text(self.error or "", max_chars=240) or None,
            "search_provider_name": compact_text(self.search_provider_name, max_chars=120),
            "source_count": int(self.source_count),
            "autonomy_level": self.autonomy_level.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscoveryQueryResult":
        """Restore a discovery query result from durable storage."""

        candidates = tuple(
            DiscoveryCandidate.from_dict(item)
            for item in value.get("candidates", [])
            if isinstance(item, dict)
        )
        autonomy_level = EvolutionAutonomyLevel(str(value.get("autonomy_level", EvolutionAutonomyLevel.OBSERVE_ONLY.value)))
        return cls(
            query=str(value.get("query", "")),
            status=str(value.get("status", "")),
            candidates=candidates,
            error=value.get("error"),
            search_provider_name=str(value.get("search_provider_name", "")),
            source_count=int(value.get("source_count", 0) or 0),
            autonomy_level=autonomy_level,
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class EvaluationRecord:
    """A conservative evidence-backed evaluation draft for one candidate."""

    evaluation_id: str
    candidate_id: str
    candidate_name: str
    candidate_category: str
    inventory_snapshot_id: str
    facts: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    potential_benefits: tuple[str, ...] = ()
    overlapping_capability_ids: tuple[str, ...] = ()
    capability_gap_ids: tuple[str, ...] = ()
    compatibility_notes: tuple[str, ...] = ()
    cost_notes: tuple[str, ...] = ()
    privacy_security_notes: tuple[str, ...] = ()
    reliability_notes: tuple[str, ...] = ()
    status: str = "draft"
    confidence: float = 0.0
    autonomy_level: EvolutionAutonomyLevel = EvolutionAutonomyLevel.OBSERVE_ONLY
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    evaluated_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "evaluation_id": self.evaluation_id,
            "candidate_id": self.candidate_id,
            "candidate_name": compact_text(self.candidate_name, max_chars=160),
            "candidate_category": compact_text(self.candidate_category, max_chars=80),
            "inventory_snapshot_id": compact_text(self.inventory_snapshot_id, max_chars=120),
            "facts": list(self.facts),
            "evidence_ids": list(self.evidence_ids),
            "inferences": list(self.inferences),
            "unknowns": list(self.unknowns),
            "potential_benefits": list(self.potential_benefits),
            "overlapping_capability_ids": list(self.overlapping_capability_ids),
            "capability_gap_ids": list(self.capability_gap_ids),
            "compatibility_notes": list(self.compatibility_notes),
            "cost_notes": list(self.cost_notes),
            "privacy_security_notes": list(self.privacy_security_notes),
            "reliability_notes": list(self.reliability_notes),
            "status": compact_text(self.status, max_chars=80),
            "confidence": round(float(self.confidence), 4),
            "autonomy_level": self.autonomy_level.value,
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "evaluated_at": parse_timestamp(self.evaluated_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvaluationRecord":
        """Restore an evaluation record from durable storage."""

        autonomy_level = EvolutionAutonomyLevel(str(value.get("autonomy_level", EvolutionAutonomyLevel.OBSERVE_ONLY.value)))
        return cls(
            evaluation_id=str(value.get("evaluation_id", "")),
            candidate_id=str(value.get("candidate_id", "")),
            candidate_name=str(value.get("candidate_name", "")),
            candidate_category=str(value.get("candidate_category", "technology")),
            inventory_snapshot_id=str(value.get("inventory_snapshot_id", "")),
            facts=_deserialize_string_list(value.get("facts", [])),
            evidence_ids=_deserialize_string_list(value.get("evidence_ids", [])),
            inferences=_deserialize_string_list(value.get("inferences", [])),
            unknowns=_deserialize_string_list(value.get("unknowns", [])),
            potential_benefits=_deserialize_string_list(value.get("potential_benefits", [])),
            overlapping_capability_ids=_deserialize_string_list(value.get("overlapping_capability_ids", [])),
            capability_gap_ids=_deserialize_string_list(value.get("capability_gap_ids", [])),
            compatibility_notes=_deserialize_string_list(value.get("compatibility_notes", [])),
            cost_notes=_deserialize_string_list(value.get("cost_notes", [])),
            privacy_security_notes=_deserialize_string_list(value.get("privacy_security_notes", [])),
            reliability_notes=_deserialize_string_list(value.get("reliability_notes", [])),
            status=str(value.get("status", "draft")),
            confidence=float(value.get("confidence", 0.0) or 0.0),
            autonomy_level=autonomy_level,
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            evaluated_at=parse_timestamp(value.get("evaluated_at")),
        )


@dataclass(slots=True, frozen=True)
class CapabilityGap:
    """A possible capability gap inferred conservatively from current evidence."""

    gap_id: str
    candidate_id: str
    inventory_snapshot_id: str
    capability_category: str
    summary: str
    current_capability_evidence: tuple[str, ...] = ()
    candidate_evidence_ids: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    status: str = "identified"
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    identified_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "gap_id": self.gap_id,
            "candidate_id": self.candidate_id,
            "inventory_snapshot_id": compact_text(self.inventory_snapshot_id, max_chars=120),
            "capability_category": compact_text(self.capability_category, max_chars=80),
            "summary": compact_text(self.summary, max_chars=320),
            "current_capability_evidence": list(self.current_capability_evidence),
            "candidate_evidence_ids": list(self.candidate_evidence_ids),
            "unknowns": list(self.unknowns),
            "status": compact_text(self.status, max_chars=80),
            "confidence": round(float(self.confidence), 4),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "identified_at": parse_timestamp(self.identified_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CapabilityGap":
        """Restore a capability gap from durable storage."""

        return cls(
            gap_id=str(value.get("gap_id", "")),
            candidate_id=str(value.get("candidate_id", "")),
            inventory_snapshot_id=str(value.get("inventory_snapshot_id", "")),
            capability_category=str(value.get("capability_category", "technology")),
            summary=str(value.get("summary", "")),
            current_capability_evidence=_deserialize_string_list(value.get("current_capability_evidence", [])),
            candidate_evidence_ids=_deserialize_string_list(value.get("candidate_evidence_ids", [])),
            unknowns=_deserialize_string_list(value.get("unknowns", [])),
            status=str(value.get("status", "identified")),
            confidence=float(value.get("confidence", 0.0) or 0.0),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            identified_at=parse_timestamp(value.get("identified_at")),
        )


@dataclass(slots=True, frozen=True)
class LearnedOutcome:
    """A durable remembered outcome linked to one self-evolution subject."""

    outcome_id: str
    subject_id: str
    outcome_type: str
    summary: str
    confidence: float = 0.0
    evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    recorded_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "outcome_id": self.outcome_id,
            "subject_id": compact_text(self.subject_id, max_chars=120),
            "outcome_type": compact_text(self.outcome_type, max_chars=80),
            "summary": compact_text(self.summary, max_chars=320),
            "confidence": round(float(self.confidence), 4),
            "evidence_ids": list(self.evidence_ids),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "recorded_at": parse_timestamp(self.recorded_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LearnedOutcome":
        """Restore one learned outcome from durable storage."""

        return cls(
            outcome_id=str(value.get("outcome_id", "")),
            subject_id=str(value.get("subject_id", "")),
            outcome_type=str(value.get("outcome_type", "")),
            summary=str(value.get("summary", "")),
            confidence=float(value.get("confidence", 0.0) or 0.0),
            evidence_ids=_deserialize_string_list(value.get("evidence_ids", [])),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            recorded_at=parse_timestamp(value.get("recorded_at")),
        )


@dataclass(slots=True, frozen=True)
class ChangeProposal:
    """An immutable proposed future change derived from one evaluation record."""

    proposal_id: str
    candidate_id: str
    title: str
    summary: str
    rationale: str
    requested_actions: tuple[str, ...] = ()
    affected_surfaces: tuple[str, ...] = ()
    expected_benefits: tuple[str, ...] = ()
    known_risks: tuple[str, ...] = ()
    verification_plan: tuple[str, ...] = ()
    rollback_plan: tuple[str, ...] = ()
    proposal_version: int = 1
    proposal_fingerprint: str = ""
    status: str = "proposed"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "proposal_id": self.proposal_id,
            "candidate_id": compact_text(self.candidate_id, max_chars=120),
            "title": compact_text(self.title, max_chars=160),
            "summary": compact_text(self.summary, max_chars=320),
            "rationale": compact_text(self.rationale, max_chars=400),
            "requested_actions": list(self.requested_actions),
            "affected_surfaces": list(self.affected_surfaces),
            "expected_benefits": list(self.expected_benefits),
            "known_risks": list(self.known_risks),
            "verification_plan": list(self.verification_plan),
            "rollback_plan": list(self.rollback_plan),
            "proposal_version": int(self.proposal_version),
            "proposal_fingerprint": compact_text(self.proposal_fingerprint, max_chars=120),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChangeProposal":
        """Restore one change proposal from durable storage."""

        return cls(
            proposal_id=str(value.get("proposal_id", "")),
            candidate_id=str(value.get("candidate_id", "")),
            title=str(value.get("title", "")),
            summary=str(value.get("summary", "")),
            rationale=str(value.get("rationale", "")),
            requested_actions=_deserialize_string_list(value.get("requested_actions", [])),
            affected_surfaces=_deserialize_string_list(value.get("affected_surfaces", [])),
            expected_benefits=_deserialize_string_list(value.get("expected_benefits", [])),
            known_risks=_deserialize_string_list(value.get("known_risks", [])),
            verification_plan=_deserialize_string_list(value.get("verification_plan", [])),
            rollback_plan=_deserialize_string_list(value.get("rollback_plan", [])),
            proposal_version=int(value.get("proposal_version", 1) or 1),
            proposal_fingerprint=str(value.get("proposal_fingerprint", "")),
            status=str(value.get("status", "proposed")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class ApprovalDecision:
    """One durable approval, rejection, pending, or expiry decision."""

    decision_id: str
    proposal_id: str
    proposal_fingerprint: str
    decision: str
    actor: str
    note: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "decision_id": self.decision_id,
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "proposal_fingerprint": compact_text(self.proposal_fingerprint, max_chars=120),
            "decision": compact_text(self.decision, max_chars=80),
            "actor": compact_text(self.actor, max_chars=120),
            "note": compact_text(self.note or "", max_chars=320) or None,
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ApprovalDecision":
        """Restore one approval decision from durable storage."""

        return cls(
            decision_id=str(value.get("decision_id", "")),
            proposal_id=str(value.get("proposal_id", "")),
            proposal_fingerprint=str(value.get("proposal_fingerprint", "")),
            decision=str(value.get("decision", "pending")),
            actor=str(value.get("actor", "")),
            note=value.get("note"),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class ChangeJournalEntry:
    """One append-only lifecycle event for proposal and approval transitions."""

    journal_entry_id: str
    proposal_id: str
    event_type: str
    previous_state: str
    new_state: str
    actor: str
    details: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    timestamp: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "journal_entry_id": self.journal_entry_id,
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "event_type": compact_text(self.event_type, max_chars=80),
            "previous_state": compact_text(self.previous_state, max_chars=120),
            "new_state": compact_text(self.new_state, max_chars=120),
            "actor": compact_text(self.actor, max_chars=120),
            "details": _sanitize_mapping(self.details),
            "schema_version": self.schema_version,
            "timestamp": parse_timestamp(self.timestamp).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChangeJournalEntry":
        """Restore one journal entry from durable storage."""

        return cls(
            journal_entry_id=str(value.get("journal_entry_id", "")),
            proposal_id=str(value.get("proposal_id", "")),
            event_type=str(value.get("event_type", "")),
            previous_state=str(value.get("previous_state", "")),
            new_state=str(value.get("new_state", "")),
            actor=str(value.get("actor", "")),
            details=_sanitize_mapping(dict(value.get("details", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            timestamp=parse_timestamp(value.get("timestamp")),
        )


@dataclass(slots=True, frozen=True)
class VerificationRequirement:
    """One durable non-executing verification requirement for a future plan step."""

    requirement_id: str
    plan_id: str
    proposal_id: str
    step_id: str
    description: str
    expected_signal: str
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "requirement_id": self.requirement_id,
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "step_id": compact_text(self.step_id, max_chars=120),
            "description": compact_text(self.description, max_chars=320),
            "expected_signal": compact_text(self.expected_signal, max_chars=320),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerificationRequirement":
        """Restore one verification requirement from durable storage."""

        return cls(
            requirement_id=str(value.get("requirement_id", "")),
            plan_id=str(value.get("plan_id", "")),
            proposal_id=str(value.get("proposal_id", "")),
            step_id=str(value.get("step_id", "")),
            description=str(value.get("description", "")),
            expected_signal=str(value.get("expected_signal", "")),
            status=str(value.get("status", "planned")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class RecoveryRequirement:
    """One durable non-executing recovery requirement for a future plan step."""

    recovery_id: str
    plan_id: str
    proposal_id: str
    step_id: str
    description: str
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "recovery_id": self.recovery_id,
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "step_id": compact_text(self.step_id, max_chars=120),
            "description": compact_text(self.description, max_chars=320),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RecoveryRequirement":
        """Restore one recovery requirement from durable storage."""

        return cls(
            recovery_id=str(value.get("recovery_id", "")),
            plan_id=str(value.get("plan_id", "")),
            proposal_id=str(value.get("proposal_id", "")),
            step_id=str(value.get("step_id", "")),
            description=str(value.get("description", "")),
            status=str(value.get("status", "planned")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class PlanStep:
    """One deterministic, typed, future execution step within a change plan."""

    step_id: str
    plan_id: str
    proposal_id: str
    sequence: int
    action_kind: str
    target: str
    description: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    verification_requirement_ids: tuple[str, ...] = ()
    recovery_requirement_id: str | None = None
    risk_classification: str = "medium"
    status: str = "planned"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "step_id": self.step_id,
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "sequence": int(self.sequence),
            "action_kind": compact_text(self.action_kind, max_chars=80),
            "target": compact_text(self.target, max_chars=240),
            "description": compact_text(self.description, max_chars=400),
            "inputs": _sanitize_mapping(self.inputs),
            "expected_outcome": compact_text(self.expected_outcome, max_chars=320),
            "verification_requirement_ids": list(self.verification_requirement_ids),
            "recovery_requirement_id": compact_text(self.recovery_requirement_id or "", max_chars=120) or None,
            "risk_classification": compact_text(self.risk_classification, max_chars=80),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PlanStep":
        """Restore one plan step from durable storage."""

        return cls(
            step_id=str(value.get("step_id", "")),
            plan_id=str(value.get("plan_id", "")),
            proposal_id=str(value.get("proposal_id", "")),
            sequence=int(value.get("sequence", 0) or 0),
            action_kind=str(value.get("action_kind", "")),
            target=str(value.get("target", "")),
            description=str(value.get("description", "")),
            inputs=_sanitize_mapping(dict(value.get("inputs", {}))),
            expected_outcome=str(value.get("expected_outcome", "")),
            verification_requirement_ids=_deserialize_string_list(value.get("verification_requirement_ids", [])),
            recovery_requirement_id=value.get("recovery_requirement_id"),
            risk_classification=str(value.get("risk_classification", "medium")),
            status=str(value.get("status", "planned")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class ChangePlan:
    """One durable, deterministic, approved change plan."""

    plan_id: str
    proposal_id: str
    proposal_fingerprint: str
    proposal_version: int
    approval_decision_id: str
    approval_state: str
    status: str = "planned"
    plan_fingerprint: str = ""
    step_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "plan_id": self.plan_id,
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "proposal_fingerprint": compact_text(self.proposal_fingerprint, max_chars=120),
            "proposal_version": int(self.proposal_version),
            "approval_decision_id": compact_text(self.approval_decision_id, max_chars=120),
            "approval_state": compact_text(self.approval_state, max_chars=80),
            "status": compact_text(self.status, max_chars=80),
            "plan_fingerprint": compact_text(self.plan_fingerprint, max_chars=120),
            "step_ids": list(self.step_ids),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChangePlan":
        """Restore one change plan from durable storage."""

        return cls(
            plan_id=str(value.get("plan_id", "")),
            proposal_id=str(value.get("proposal_id", "")),
            proposal_fingerprint=str(value.get("proposal_fingerprint", "")),
            proposal_version=int(value.get("proposal_version", 0) or 0),
            approval_decision_id=str(value.get("approval_decision_id", "")),
            approval_state=str(value.get("approval_state", "pending")),
            status=str(value.get("status", "planned")),
            plan_fingerprint=str(value.get("plan_fingerprint", "")),
            step_ids=_deserialize_string_list(value.get("step_ids", [])),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class ExecutionStepRequest:
    """One immutable typed execution-boundary projection of one exact plan step."""

    step_request_id: str
    request_id: str
    plan_id: str
    proposal_id: str
    plan_step_id: str
    sequence: int
    executor_category: str
    action_kind: str
    target: str
    inputs: dict[str, Any] = field(default_factory=dict)
    risk_classification: str = "medium"
    status: str = "projected"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "step_request_id": self.step_request_id,
            "request_id": compact_text(self.request_id, max_chars=120),
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "plan_step_id": compact_text(self.plan_step_id, max_chars=120),
            "sequence": int(self.sequence),
            "executor_category": compact_text(self.executor_category, max_chars=80),
            "action_kind": compact_text(self.action_kind, max_chars=80),
            "target": compact_text(self.target, max_chars=240),
            "inputs": _sanitize_mapping(self.inputs),
            "risk_classification": compact_text(self.risk_classification, max_chars=80),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionStepRequest":
        """Restore one execution-step request from durable storage."""

        return cls(
            step_request_id=str(value.get("step_request_id", "")),
            request_id=str(value.get("request_id", "")),
            plan_id=str(value.get("plan_id", "")),
            proposal_id=str(value.get("proposal_id", "")),
            plan_step_id=str(value.get("plan_step_id", "")),
            sequence=int(value.get("sequence", 0) or 0),
            executor_category=str(value.get("executor_category", "")),
            action_kind=str(value.get("action_kind", "")),
            target=str(value.get("target", "")),
            inputs=_sanitize_mapping(dict(value.get("inputs", {}))),
            risk_classification=str(value.get("risk_classification", "medium")),
            status=str(value.get("status", "projected")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class ExecutionRequest:
    """One durable immutable request bound to an exact approved plan snapshot."""

    request_id: str
    request_fingerprint: str
    plan_id: str
    plan_fingerprint: str
    proposal_id: str
    proposal_fingerprint: str
    proposal_version: int
    approval_decision_id: str
    step_request_ids: tuple[str, ...] = ()
    mode: str = "authorize_only"
    status: str = "pending_authorization"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "request_id": self.request_id,
            "request_fingerprint": compact_text(self.request_fingerprint, max_chars=120),
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "plan_fingerprint": compact_text(self.plan_fingerprint, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "proposal_fingerprint": compact_text(self.proposal_fingerprint, max_chars=120),
            "proposal_version": int(self.proposal_version),
            "approval_decision_id": compact_text(self.approval_decision_id, max_chars=120),
            "step_request_ids": list(self.step_request_ids),
            "mode": compact_text(self.mode, max_chars=80),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionRequest":
        """Restore one execution request from durable storage."""

        return cls(
            request_id=str(value.get("request_id", "")),
            request_fingerprint=str(value.get("request_fingerprint", "")),
            plan_id=str(value.get("plan_id", "")),
            plan_fingerprint=str(value.get("plan_fingerprint", "")),
            proposal_id=str(value.get("proposal_id", "")),
            proposal_fingerprint=str(value.get("proposal_fingerprint", "")),
            proposal_version=int(value.get("proposal_version", 0) or 0),
            approval_decision_id=str(value.get("approval_decision_id", "")),
            step_request_ids=_deserialize_string_list(value.get("step_request_ids", [])),
            mode=str(value.get("mode", "authorize_only")),
            status=str(value.get("status", "pending_authorization")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class ExecutionAuthorization:
    """One durable immutable authorization result after immediate revalidation."""

    authorization_id: str
    authorization_fingerprint: str
    request_id: str
    request_fingerprint: str
    plan_id: str
    plan_fingerprint: str
    proposal_id: str
    proposal_fingerprint: str
    proposal_version: int
    approval_decision_id: str
    decision: str
    reason_code: str
    reason: str
    host_action_proof: str = "no_host_action_performed"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "authorization_id": self.authorization_id,
            "authorization_fingerprint": compact_text(self.authorization_fingerprint, max_chars=120),
            "request_id": compact_text(self.request_id, max_chars=120),
            "request_fingerprint": compact_text(self.request_fingerprint, max_chars=120),
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "plan_fingerprint": compact_text(self.plan_fingerprint, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "proposal_fingerprint": compact_text(self.proposal_fingerprint, max_chars=120),
            "proposal_version": int(self.proposal_version),
            "approval_decision_id": compact_text(self.approval_decision_id, max_chars=120),
            "decision": compact_text(self.decision, max_chars=80),
            "reason_code": compact_text(self.reason_code, max_chars=120),
            "reason": compact_text(self.reason, max_chars=320),
            "host_action_proof": compact_text(self.host_action_proof, max_chars=160),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
            "created_at": parse_timestamp(self.created_at).isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionAuthorization":
        """Restore one execution authorization from durable storage."""

        return cls(
            authorization_id=str(value.get("authorization_id", "")),
            authorization_fingerprint=str(value.get("authorization_fingerprint", "")),
            request_id=str(value.get("request_id", "")),
            request_fingerprint=str(value.get("request_fingerprint", "")),
            plan_id=str(value.get("plan_id", "")),
            plan_fingerprint=str(value.get("plan_fingerprint", "")),
            proposal_id=str(value.get("proposal_id", "")),
            proposal_fingerprint=str(value.get("proposal_fingerprint", "")),
            proposal_version=int(value.get("proposal_version", 0) or 0),
            approval_decision_id=str(value.get("approval_decision_id", "")),
            decision=str(value.get("decision", "denied")),
            reason_code=str(value.get("reason_code", "")),
            reason=str(value.get("reason", "")),
            host_action_proof=str(value.get("host_action_proof", "no_host_action_performed")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
            created_at=parse_timestamp(value.get("created_at")),
        )


@dataclass(slots=True, frozen=True)
class VerificationRun:
    """One durable verification session bound to one exact granted authorization."""

    verification_run_id: str
    run_fingerprint: str
    authorization_id: str
    authorization_fingerprint: str
    execution_request_id: str
    request_fingerprint: str
    plan_id: str
    plan_fingerprint: str
    proposal_id: str
    proposal_fingerprint: str
    proposal_version: int
    approval_decision_id: str
    execution_step_request_ids: tuple[str, ...] = ()
    verification_step_run_ids: tuple[str, ...] = ()
    status: str = "pending_start"
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "verification_run_id": self.verification_run_id,
            "run_fingerprint": compact_text(self.run_fingerprint, max_chars=120),
            "authorization_id": compact_text(self.authorization_id, max_chars=120),
            "authorization_fingerprint": compact_text(self.authorization_fingerprint, max_chars=120),
            "execution_request_id": compact_text(self.execution_request_id, max_chars=120),
            "request_fingerprint": compact_text(self.request_fingerprint, max_chars=120),
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "plan_fingerprint": compact_text(self.plan_fingerprint, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "proposal_fingerprint": compact_text(self.proposal_fingerprint, max_chars=120),
            "proposal_version": int(self.proposal_version),
            "approval_decision_id": compact_text(self.approval_decision_id, max_chars=120),
            "execution_step_request_ids": list(self.execution_step_request_ids),
            "verification_step_run_ids": list(self.verification_step_run_ids),
            "status": compact_text(self.status, max_chars=80),
            "actor": compact_text(self.actor, max_chars=120),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerificationRun":
        """Restore one verification run from durable storage."""

        return cls(
            verification_run_id=str(value.get("verification_run_id", "")),
            run_fingerprint=str(value.get("run_fingerprint", "")),
            authorization_id=str(value.get("authorization_id", "")),
            authorization_fingerprint=str(value.get("authorization_fingerprint", "")),
            execution_request_id=str(value.get("execution_request_id", "")),
            request_fingerprint=str(value.get("request_fingerprint", "")),
            plan_id=str(value.get("plan_id", "")),
            plan_fingerprint=str(value.get("plan_fingerprint", "")),
            proposal_id=str(value.get("proposal_id", "")),
            proposal_fingerprint=str(value.get("proposal_fingerprint", "")),
            proposal_version=int(value.get("proposal_version", 0) or 0),
            approval_decision_id=str(value.get("approval_decision_id", "")),
            execution_step_request_ids=_deserialize_string_list(value.get("execution_step_request_ids", [])),
            verification_step_run_ids=_deserialize_string_list(value.get("verification_step_run_ids", [])),
            status=str(value.get("status", "pending_start")),
            actor=str(value.get("actor", "narvis")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class VerificationStepRun:
    """One ordered runtime verification instance for one exact execution step request."""

    verification_step_run_id: str
    verification_run_id: str
    execution_step_request_id: str
    plan_step_id: str
    sequence: int
    executor_category: str
    action_kind: str
    target: str
    inputs: dict[str, Any] = field(default_factory=dict)
    risk_classification: str = "medium"
    step_run_fingerprint: str = ""
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "verification_step_run_id": self.verification_step_run_id,
            "verification_run_id": compact_text(self.verification_run_id, max_chars=120),
            "execution_step_request_id": compact_text(self.execution_step_request_id, max_chars=120),
            "plan_step_id": compact_text(self.plan_step_id, max_chars=120),
            "sequence": int(self.sequence),
            "executor_category": compact_text(self.executor_category, max_chars=80),
            "action_kind": compact_text(self.action_kind, max_chars=80),
            "target": compact_text(self.target, max_chars=240),
            "inputs": _sanitize_mapping(self.inputs),
            "risk_classification": compact_text(self.risk_classification, max_chars=80),
            "step_run_fingerprint": compact_text(self.step_run_fingerprint, max_chars=120),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerificationStepRun":
        """Restore one verification step run from durable storage."""

        return cls(
            verification_step_run_id=str(value.get("verification_step_run_id", "")),
            verification_run_id=str(value.get("verification_run_id", "")),
            execution_step_request_id=str(value.get("execution_step_request_id", "")),
            plan_step_id=str(value.get("plan_step_id", "")),
            sequence=int(value.get("sequence", 0) or 0),
            executor_category=str(value.get("executor_category", "")),
            action_kind=str(value.get("action_kind", "")),
            target=str(value.get("target", "")),
            inputs=_sanitize_mapping(dict(value.get("inputs", {}))),
            risk_classification=str(value.get("risk_classification", "medium")),
            step_run_fingerprint=str(value.get("step_run_fingerprint", "")),
            status=str(value.get("status", "pending")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class VerificationObservation:
    """One durable evidence record bound to one exact verification step run."""

    observation_id: str
    verification_run_id: str
    verification_step_run_id: str
    observation_kind: str
    evidence: Any
    status: str
    observation_fingerprint: str
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "observation_id": self.observation_id,
            "verification_run_id": compact_text(self.verification_run_id, max_chars=120),
            "verification_step_run_id": compact_text(self.verification_step_run_id, max_chars=120),
            "observation_kind": compact_text(self.observation_kind, max_chars=120),
            "evidence": _sanitize_value(self.evidence),
            "status": compact_text(self.status, max_chars=80),
            "observation_fingerprint": compact_text(self.observation_fingerprint, max_chars=120),
            "actor": compact_text(self.actor, max_chars=120),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerificationObservation":
        """Restore one verification observation from durable storage."""

        return cls(
            observation_id=str(value.get("observation_id", "")),
            verification_run_id=str(value.get("verification_run_id", "")),
            verification_step_run_id=str(value.get("verification_step_run_id", "")),
            observation_kind=str(value.get("observation_kind", "")),
            evidence=_sanitize_value(value.get("evidence")),
            status=str(value.get("status", "recorded")),
            observation_fingerprint=str(value.get("observation_fingerprint", "")),
            actor=str(value.get("actor", "narvis")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class VerificationOutcome:
    """One durable terminal outcome for one exact verification run."""

    verification_outcome_id: str
    verification_run_id: str
    run_fingerprint: str
    step_results: tuple[dict[str, Any], ...]
    status: str
    reason_code: str
    outcome_fingerprint: str
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "verification_outcome_id": self.verification_outcome_id,
            "verification_run_id": compact_text(self.verification_run_id, max_chars=120),
            "run_fingerprint": compact_text(self.run_fingerprint, max_chars=120),
            "step_results": [_sanitize_mapping(dict(result)) for result in self.step_results],
            "status": compact_text(self.status, max_chars=80),
            "reason_code": compact_text(self.reason_code, max_chars=120),
            "outcome_fingerprint": compact_text(self.outcome_fingerprint, max_chars=120),
            "actor": compact_text(self.actor, max_chars=120),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VerificationOutcome":
        """Restore one verification outcome from durable storage."""

        step_results: list[dict[str, Any]] = []
        raw_results = value.get("step_results", [])
        if isinstance(raw_results, list | tuple):
            for result in raw_results:
                if isinstance(result, dict):
                    step_results.append(_sanitize_mapping(dict(result)))

        return cls(
            verification_outcome_id=str(value.get("verification_outcome_id", "")),
            verification_run_id=str(value.get("verification_run_id", "")),
            run_fingerprint=str(value.get("run_fingerprint", "")),
            step_results=tuple(step_results),
            status=str(value.get("status", "blocked")),
            reason_code=str(value.get("reason_code", "")),
            outcome_fingerprint=str(value.get("outcome_fingerprint", "")),
            actor=str(value.get("actor", "narvis")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class RecoveryRun:
    """One durable recovery-readiness session bound to one exact verification outcome."""

    recovery_run_id: str
    run_fingerprint: str
    verification_outcome_id: str
    verification_outcome_fingerprint: str
    verification_run_id: str
    verification_run_fingerprint: str
    authorization_id: str
    authorization_fingerprint: str
    execution_request_id: str
    request_fingerprint: str
    plan_id: str
    plan_fingerprint: str
    proposal_id: str
    proposal_fingerprint: str
    proposal_version: int
    approval_decision_id: str
    execution_step_request_ids: tuple[str, ...] = ()
    recovery_step_run_ids: tuple[str, ...] = ()
    status: str = "pending_start"
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "recovery_run_id": self.recovery_run_id,
            "run_fingerprint": compact_text(self.run_fingerprint, max_chars=120),
            "verification_outcome_id": compact_text(self.verification_outcome_id, max_chars=120),
            "verification_outcome_fingerprint": compact_text(self.verification_outcome_fingerprint, max_chars=120),
            "verification_run_id": compact_text(self.verification_run_id, max_chars=120),
            "verification_run_fingerprint": compact_text(self.verification_run_fingerprint, max_chars=120),
            "authorization_id": compact_text(self.authorization_id, max_chars=120),
            "authorization_fingerprint": compact_text(self.authorization_fingerprint, max_chars=120),
            "execution_request_id": compact_text(self.execution_request_id, max_chars=120),
            "request_fingerprint": compact_text(self.request_fingerprint, max_chars=120),
            "plan_id": compact_text(self.plan_id, max_chars=120),
            "plan_fingerprint": compact_text(self.plan_fingerprint, max_chars=120),
            "proposal_id": compact_text(self.proposal_id, max_chars=120),
            "proposal_fingerprint": compact_text(self.proposal_fingerprint, max_chars=120),
            "proposal_version": int(self.proposal_version),
            "approval_decision_id": compact_text(self.approval_decision_id, max_chars=120),
            "execution_step_request_ids": list(self.execution_step_request_ids),
            "recovery_step_run_ids": list(self.recovery_step_run_ids),
            "status": compact_text(self.status, max_chars=80),
            "actor": compact_text(self.actor, max_chars=120),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RecoveryRun":
        """Restore one recovery run from durable storage."""

        return cls(
            recovery_run_id=str(value.get("recovery_run_id", "")),
            run_fingerprint=str(value.get("run_fingerprint", "")),
            verification_outcome_id=str(value.get("verification_outcome_id", "")),
            verification_outcome_fingerprint=str(value.get("verification_outcome_fingerprint", "")),
            verification_run_id=str(value.get("verification_run_id", "")),
            verification_run_fingerprint=str(value.get("verification_run_fingerprint", "")),
            authorization_id=str(value.get("authorization_id", "")),
            authorization_fingerprint=str(value.get("authorization_fingerprint", "")),
            execution_request_id=str(value.get("execution_request_id", "")),
            request_fingerprint=str(value.get("request_fingerprint", "")),
            plan_id=str(value.get("plan_id", "")),
            plan_fingerprint=str(value.get("plan_fingerprint", "")),
            proposal_id=str(value.get("proposal_id", "")),
            proposal_fingerprint=str(value.get("proposal_fingerprint", "")),
            proposal_version=int(value.get("proposal_version", 0) or 0),
            approval_decision_id=str(value.get("approval_decision_id", "")),
            execution_step_request_ids=_deserialize_string_list(value.get("execution_step_request_ids", [])),
            recovery_step_run_ids=_deserialize_string_list(value.get("recovery_step_run_ids", [])),
            status=str(value.get("status", "pending_start")),
            actor=str(value.get("actor", "narvis")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class RecoveryStepRun:
    """One ordered runtime recovery-readiness instance for one exact execution step request."""

    recovery_step_run_id: str
    recovery_run_id: str
    execution_step_request_id: str
    plan_step_id: str
    sequence: int
    executor_category: str
    action_kind: str
    target: str
    inputs: dict[str, Any] = field(default_factory=dict)
    risk_classification: str = "medium"
    step_run_fingerprint: str = ""
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "recovery_step_run_id": self.recovery_step_run_id,
            "recovery_run_id": compact_text(self.recovery_run_id, max_chars=120),
            "execution_step_request_id": compact_text(self.execution_step_request_id, max_chars=120),
            "plan_step_id": compact_text(self.plan_step_id, max_chars=120),
            "sequence": int(self.sequence),
            "executor_category": compact_text(self.executor_category, max_chars=80),
            "action_kind": compact_text(self.action_kind, max_chars=80),
            "target": compact_text(self.target, max_chars=240),
            "inputs": _sanitize_mapping(self.inputs),
            "risk_classification": compact_text(self.risk_classification, max_chars=80),
            "step_run_fingerprint": compact_text(self.step_run_fingerprint, max_chars=120),
            "status": compact_text(self.status, max_chars=80),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RecoveryStepRun":
        """Restore one recovery step run from durable storage."""

        return cls(
            recovery_step_run_id=str(value.get("recovery_step_run_id", "")),
            recovery_run_id=str(value.get("recovery_run_id", "")),
            execution_step_request_id=str(value.get("execution_step_request_id", "")),
            plan_step_id=str(value.get("plan_step_id", "")),
            sequence=int(value.get("sequence", 0) or 0),
            executor_category=str(value.get("executor_category", "")),
            action_kind=str(value.get("action_kind", "")),
            target=str(value.get("target", "")),
            inputs=_sanitize_mapping(dict(value.get("inputs", {}))),
            risk_classification=str(value.get("risk_classification", "medium")),
            step_run_fingerprint=str(value.get("step_run_fingerprint", "")),
            status=str(value.get("status", "pending")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class RecoveryObservation:
    """One durable readiness-evidence record bound to one exact recovery step run."""

    observation_id: str
    recovery_run_id: str
    recovery_step_run_id: str
    observation_kind: str
    evidence: Any
    status: str
    observation_fingerprint: str
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "observation_id": self.observation_id,
            "recovery_run_id": compact_text(self.recovery_run_id, max_chars=120),
            "recovery_step_run_id": compact_text(self.recovery_step_run_id, max_chars=120),
            "observation_kind": compact_text(self.observation_kind, max_chars=120),
            "evidence": _sanitize_value(self.evidence),
            "status": compact_text(self.status, max_chars=80),
            "observation_fingerprint": compact_text(self.observation_fingerprint, max_chars=120),
            "actor": compact_text(self.actor, max_chars=120),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RecoveryObservation":
        """Restore one recovery observation from durable storage."""

        return cls(
            observation_id=str(value.get("observation_id", "")),
            recovery_run_id=str(value.get("recovery_run_id", "")),
            recovery_step_run_id=str(value.get("recovery_step_run_id", "")),
            observation_kind=str(value.get("observation_kind", "")),
            evidence=_sanitize_value(value.get("evidence")),
            status=str(value.get("status", "recorded")),
            observation_fingerprint=str(value.get("observation_fingerprint", "")),
            actor=str(value.get("actor", "narvis")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True, frozen=True)
class RecoveryOutcome:
    """One durable terminal recovery-readiness outcome for one exact recovery run."""

    recovery_outcome_id: str
    recovery_run_id: str
    run_fingerprint: str
    step_results: tuple[dict[str, Any], ...]
    status: str
    reason_code: str
    outcome_fingerprint: str
    actor: str = "narvis"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""

        return {
            "recovery_outcome_id": self.recovery_outcome_id,
            "recovery_run_id": compact_text(self.recovery_run_id, max_chars=120),
            "run_fingerprint": compact_text(self.run_fingerprint, max_chars=120),
            "step_results": [_sanitize_mapping(dict(result)) for result in self.step_results],
            "status": compact_text(self.status, max_chars=80),
            "reason_code": compact_text(self.reason_code, max_chars=120),
            "outcome_fingerprint": compact_text(self.outcome_fingerprint, max_chars=120),
            "actor": compact_text(self.actor, max_chars=120),
            "metadata": _sanitize_mapping(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RecoveryOutcome":
        """Restore one recovery outcome from durable storage."""

        step_results: list[dict[str, Any]] = []
        raw_results = value.get("step_results", [])
        if isinstance(raw_results, list | tuple):
            for result in raw_results:
                if isinstance(result, dict):
                    step_results.append(_sanitize_mapping(dict(result)))

        return cls(
            recovery_outcome_id=str(value.get("recovery_outcome_id", "")),
            recovery_run_id=str(value.get("recovery_run_id", "")),
            run_fingerprint=str(value.get("run_fingerprint", "")),
            step_results=tuple(step_results),
            status=str(value.get("status", "blocked")),
            reason_code=str(value.get("reason_code", "")),
            outcome_fingerprint=str(value.get("outcome_fingerprint", "")),
            actor=str(value.get("actor", "narvis")),
            metadata=_sanitize_mapping(dict(value.get("metadata", {}))),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )


__all__ = [
    "ApprovalDecision",
    "CapabilityGap",
    "CapabilityInventorySnapshot",
    "CapabilityRecord",
    "ChangePlan",
    "ChangeJournalEntry",
    "ChangeProposal",
    "DiscoveryCandidate",
    "DiscoveryQueryResult",
    "ExecutionAuthorization",
    "ExecutionRequest",
    "ExecutionStepRequest",
    "EvaluationRecord",
    "EvidenceRecord",
    "EvolutionAutonomyLevel",
    "LearnedOutcome",
    "PlanStep",
    "RecoveryObservation",
    "RecoveryOutcome",
    "RecoveryRequirement",
    "RecoveryRun",
    "RecoveryStepRun",
    "SCHEMA_VERSION",
    "VerificationObservation",
    "VerificationOutcome",
    "VerificationRequirement",
    "VerificationRun",
    "VerificationStepRun",
    "compact_text",
    "normalize_identity",
    "parse_timestamp",
    "sanitize_durable_mapping",
    "sanitize_durable_value",
    "slugify",
    "stable_id",
    "utc_now",
]
