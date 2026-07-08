"""Observe-only self-evolution foundations for NARVIS."""

from .inventory import CapabilityInventoryBuilder
from .models import (
    ApprovalDecision,
    CapabilityGap,
    CapabilityInventorySnapshot,
    CapabilityRecord,
    ChangeJournalEntry,
    ChangeProposal,
    DiscoveryCandidate,
    DiscoveryQueryResult,
    EvaluationRecord,
    EvidenceRecord,
    EvolutionAutonomyLevel,
    LearnedOutcome,
)
from .runtime import EvolutionPolicy, SelfEvolutionService, build_evolution_service, register_evolution_services

__all__ = [
    "ApprovalDecision",
    "CapabilityGap",
    "CapabilityInventorySnapshot",
    "CapabilityInventoryBuilder",
    "CapabilityRecord",
    "ChangeJournalEntry",
    "ChangeProposal",
    "DiscoveryCandidate",
    "DiscoveryQueryResult",
    "EvaluationRecord",
    "EvidenceRecord",
    "EvolutionAutonomyLevel",
    "EvolutionPolicy",
    "LearnedOutcome",
    "SelfEvolutionService",
    "build_evolution_service",
    "register_evolution_services",
]
