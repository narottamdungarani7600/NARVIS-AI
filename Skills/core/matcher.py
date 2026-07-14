"""Deterministic capability matching and skill ranking."""

from __future__ import annotations

from collections.abc import Iterable

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .discovery import SkillDiscovery, _normalize_capabilities
from .interfaces import EventPublisher
from .models import (
    CapabilityMatchResult,
    SkillCapability,
    SkillDefinition,
    SkillDiscoveryResult,
)


SkillCandidate = SkillDefinition | SkillDiscoveryResult


class CapabilityMatcher:
    """Score registered skills against explicitly requested capabilities.

    Scores are the fraction of unique requested capability identifiers that a
    skill advertises. The matcher does not infer capabilities or create plans.
    """

    MATCHED_EVENT = "skill.matched"

    def __init__(
        self,
        discovery: SkillDiscovery | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if discovery is not None and not isinstance(discovery, SkillDiscovery):
            raise TypeError("matcher discovery must be a SkillDiscovery or None")
        self._discovery = discovery
        self._logger = logger or NullLogger("narvis.skills.matcher")
        self._event_bus = event_bus

    @property
    def discovery(self) -> SkillDiscovery | None:
        """Return the optional injected discovery service."""

        return self._discovery

    def match(
        self,
        requested_capabilities: (
            Iterable[str | SkillCapability] | str | SkillCapability
        ),
        candidates: Iterable[SkillCandidate] | None = None,
        *,
        allow_partial: bool = True,
        minimum_score: float = 0.0,
        available_only: bool = True,
    ) -> tuple[CapabilityMatchResult, ...]:
        """Score and rank candidates by capability coverage.

        Ranking uses descending capability score followed by stable skill name
        and version ordering. Preference and priority remain resolver concerns.
        """

        if not isinstance(allow_partial, bool):
            raise TypeError("allow_partial must be a boolean")
        if not isinstance(available_only, bool):
            raise TypeError("available_only must be a boolean")
        if not isinstance(minimum_score, (int, float)) or isinstance(
            minimum_score,
            bool,
        ):
            raise TypeError("minimum_score must be a number")
        threshold = float(minimum_score)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("minimum_score must be between 0.0 and 1.0")
        requested = _normalize_capabilities(
            requested_capabilities,
            allow_empty=False,
        )
        resolved_candidates = self._candidates(
            requested,
            candidates,
            allow_partial=allow_partial,
            available_only=available_only,
        )

        self._log(
            LogLevel.DEBUG,
            "Capability matching started",
            requested_capabilities=requested,
            candidate_count=len(resolved_candidates),
            allow_partial=allow_partial,
            minimum_score=threshold,
            available_only=available_only,
        )
        matches: list[CapabilityMatchResult] = []
        for definition in resolved_candidates:
            if available_only and not definition.available:
                self._log(
                    LogLevel.DEBUG,
                    "Capability match candidate skipped",
                    skill=definition.name,
                    reason="unavailable",
                )
                continue

            advertised = {
                capability.name.casefold()
                for capability in definition.metadata.capabilities
            }
            matched = tuple(
                name for name in requested if name.casefold() in advertised
            )
            unmatched = tuple(
                name for name in requested if name.casefold() not in advertised
            )
            score = len(matched) / len(requested)
            selected = bool(matched) and score >= threshold
            if not allow_partial:
                selected = selected and not unmatched
            self._log(
                LogLevel.DEBUG,
                "Capability match candidate scored",
                skill=definition.name,
                capability_score=score,
                matched_capabilities=matched,
                unmatched_capabilities=unmatched,
                selected=selected,
            )
            if not selected:
                continue
            matches.append(
                CapabilityMatchResult(
                    definition=definition,
                    requested_capabilities=requested,
                    matched_capabilities=matched,
                    unmatched_capabilities=unmatched,
                    capability_score=score,
                )
            )

        ranked = self.rank(matches)
        for rank, match in enumerate(ranked, start=1):
            self._publish(match, rank)
        self._log(
            LogLevel.INFO,
            "Capability matching completed",
            requested_capabilities=requested,
            match_count=len(ranked),
        )
        return ranked

    def rank(
        self,
        matches: Iterable[CapabilityMatchResult],
    ) -> tuple[CapabilityMatchResult, ...]:
        """Return unique matches in deterministic score-first order."""

        try:
            supplied = tuple(matches)
        except TypeError as error:
            raise TypeError("matches must be an iterable") from error
        if not all(isinstance(match, CapabilityMatchResult) for match in supplied):
            raise TypeError("matches must contain CapabilityMatchResult values")

        ranked = sorted(supplied, key=_match_order)
        unique: list[CapabilityMatchResult] = []
        seen: set[tuple[object, ...]] = set()
        for match in ranked:
            identity = (
                match.name.casefold(),
                match.metadata.version.casefold(),
                match.priority,
                match.available,
                match.preferred,
                match.requested_capabilities,
                match.matched_capabilities,
                match.unmatched_capabilities,
                match.capability_score,
            )
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(match)
        return tuple(unique)

    def _candidates(
        self,
        requested: tuple[str, ...],
        candidates: Iterable[SkillCandidate] | None,
        *,
        allow_partial: bool,
        available_only: bool,
    ) -> tuple[SkillDefinition, ...]:
        """Resolve explicit or discovery-backed candidates to typed definitions."""

        if candidates is None:
            if self._discovery is None:
                return ()
            discovered = self._discovery.discover(
                capabilities=requested,
                available_only=available_only,
                require_all_capabilities=not allow_partial,
            )
            return tuple(result.definition for result in discovered)

        try:
            supplied = tuple(candidates)
        except TypeError as error:
            raise TypeError("candidates must be an iterable") from error
        definitions: list[SkillDefinition] = []
        for candidate in supplied:
            if isinstance(candidate, SkillDiscoveryResult):
                definitions.append(candidate.definition)
            elif isinstance(candidate, SkillDefinition):
                definitions.append(candidate)
            else:
                raise TypeError(
                    "candidates must contain SkillDefinition or "
                    "SkillDiscoveryResult values"
                )
        return tuple(definitions)

    def _publish(self, match: CapabilityMatchResult, rank: int) -> None:
        """Publish one match event without allowing subscribers to alter ranking."""

        if self._event_bus is None:
            return
        payload: dict[str, object] = {
            "name": match.name,
            "capability_score": match.capability_score,
            "matched_capabilities": match.matched_capabilities,
            "unmatched_capabilities": match.unmatched_capabilities,
            "exact_match": match.exact_match,
            "rank": rank,
            "priority": match.priority,
            "available": match.available,
            "preferred": match.preferred,
        }
        try:
            self._event_bus.publish(SystemEvent(name=self.MATCHED_EVENT, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish skill match event",
                skill=match.name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit one Core logger entry without changing matching behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


def _match_order(
    match: CapabilityMatchResult,
) -> tuple[float, str, str, str, str, int, int, int]:
    """Return a total, deterministic capability ranking key."""

    return (
        -match.capability_score,
        match.name.casefold(),
        match.name,
        match.metadata.version.casefold(),
        match.metadata.version,
        -match.priority,
        0 if match.preferred else 1,
        0 if match.available else 1,
    )


__all__ = ["CapabilityMatcher", "SkillCandidate"]
