"""Typed models for the observe-only Self-Evolution foundation."""

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


__all__ = [
    "CapabilityGap",
    "CapabilityInventorySnapshot",
    "CapabilityRecord",
    "DiscoveryCandidate",
    "DiscoveryQueryResult",
    "EvaluationRecord",
    "EvidenceRecord",
    "EvolutionAutonomyLevel",
    "LearnedOutcome",
    "SCHEMA_VERSION",
    "compact_text",
    "normalize_identity",
    "parse_timestamp",
    "slugify",
    "stable_id",
    "utc_now",
]
