"""Deterministic best-skill resolution over capability matches."""

from __future__ import annotations

from collections.abc import Iterable

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .discovery import _normalize_capabilities
from .interfaces import EventPublisher
from .matcher import CapabilityMatcher, SkillCandidate
from .models import (
    CapabilityMatchResult,
    SkillCapability,
    SkillCategory,
    SkillDefinition,
    SkillDiscoveryResult,
    SkillResolutionResult,
)


class SkillResolver:
    """Select one best matching skill without planning or executing it."""

    RESOLVED_EVENT = "skill.resolved"

    def __init__(
        self,
        matcher: CapabilityMatcher | None = None,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if matcher is not None and not isinstance(matcher, CapabilityMatcher):
            raise TypeError("resolver matcher must be a CapabilityMatcher or None")
        self._matcher = matcher or CapabilityMatcher(
            logger=logger,
            event_bus=event_bus,
        )
        self._logger = logger or NullLogger("narvis.skills.resolver")
        self._event_bus = event_bus

    @property
    def matcher(self) -> CapabilityMatcher:
        """Return the injected capability matcher."""

        return self._matcher

    def resolve(
        self,
        requested_capabilities: (
            Iterable[str | SkillCapability]
            | Iterable[CapabilityMatchResult]
            | str
            | SkillCapability
        ),
        candidates: Iterable[SkillCandidate | CapabilityMatchResult] | None = None,
        *,
        category: SkillCategory | None = None,
        preferred_skills: Iterable[str] | str = (),
        preferred_skill: str | None = None,
        allow_partial: bool = True,
        minimum_score: float = 0.0,
        available_only: bool = True,
    ) -> SkillResolutionResult:
        """Match requested capabilities and resolve the best candidate.

        For callers that already hold match results, passing those results as
        the first argument is equivalent to calling :meth:`resolve_matches`.
        """

        if category is not None and not isinstance(category, SkillCategory):
            raise TypeError("category must be a SkillCategory or None")
        materialized_request: object = requested_capabilities
        if not isinstance(requested_capabilities, (str, SkillCapability)):
            try:
                materialized_request = tuple(requested_capabilities)
            except TypeError:
                materialized_request = requested_capabilities
        direct_matches = _as_direct_matches(materialized_request)
        if direct_matches is not None:
            if candidates is not None:
                raise ValueError(
                    "candidates cannot be supplied when resolving match results"
                )
            direct_request = self._requested_capabilities(direct_matches, None)
            filtered_matches = tuple(
                match
                for match in direct_matches
                if category is None or match.metadata.category is category
            )
            return self.resolve_matches(
                filtered_matches,
                requested_capabilities=direct_request,
                preferred_skills=preferred_skills,
                preferred_skill=preferred_skill,
                available_only=available_only,
            )

        requested = _normalize_capabilities(
            materialized_request,  # type: ignore[arg-type]
            allow_empty=False,
        )
        supplied_candidates = self._filtered_candidates(candidates, category)
        if supplied_candidates is None and category is not None:
            discovery = self._matcher.discovery
            if discovery is None:
                supplied_candidates = ()
            else:
                supplied_candidates = discovery.discover(
                    category=category,
                    capabilities=requested,
                    available_only=available_only,
                    require_all_capabilities=not allow_partial,
                )

        if supplied_candidates is not None and all(
            isinstance(candidate, CapabilityMatchResult)
            for candidate in supplied_candidates
        ):
            return self.resolve_matches(
                supplied_candidates,  # type: ignore[arg-type]
                requested_capabilities=requested,
                preferred_skills=preferred_skills,
                preferred_skill=preferred_skill,
                available_only=available_only,
            )
        matches = self._matcher.match(
            requested,
            supplied_candidates,  # type: ignore[arg-type]
            allow_partial=allow_partial,
            minimum_score=minimum_score,
            available_only=available_only,
        )
        return self.resolve_matches(
            matches,
            requested_capabilities=requested,
            preferred_skills=preferred_skills,
            preferred_skill=preferred_skill,
            available_only=available_only,
        )

    def resolve_matches(
        self,
        matches: Iterable[CapabilityMatchResult],
        *,
        requested_capabilities: (
            Iterable[str | SkillCapability] | str | SkillCapability | None
        ) = None,
        preferred_skills: Iterable[str] | str = (),
        preferred_skill: str | None = None,
        available_only: bool = True,
    ) -> SkillResolutionResult:
        """Resolve precomputed matches by score, preference, priority, and name."""

        if not isinstance(available_only, bool):
            raise TypeError("available_only must be a boolean")
        try:
            supplied = tuple(matches)
        except TypeError as error:
            raise TypeError("matches must be an iterable") from error
        if not all(isinstance(match, CapabilityMatchResult) for match in supplied):
            raise TypeError("matches must contain CapabilityMatchResult values")

        requested = self._requested_capabilities(supplied, requested_capabilities)
        preferences = _normalize_preferred_skills(
            preferred_skills,
            preferred_skill,
        )
        preference_order = {
            name.casefold(): index for index, name in enumerate(preferences)
        }
        self._log(
            LogLevel.DEBUG,
            "Skill resolution started",
            requested_capabilities=requested,
            candidate_count=len(supplied),
            preferred_skills=preferences,
            available_only=available_only,
        )

        available_matches = tuple(
            match for match in supplied if match.available or not available_only
        )
        ranked = sorted(
            available_matches,
            key=lambda match: _resolution_order(match, preference_order),
        )
        unique: list[CapabilityMatchResult] = []
        seen_names: set[str] = set()
        for match in ranked:
            name_key = match.name.casefold()
            if name_key in seen_names:
                self._log(
                    LogLevel.DEBUG,
                    "Duplicate skill resolution candidate removed",
                    skill=match.name,
                    version=match.metadata.version,
                )
                continue
            seen_names.add(name_key)
            unique.append(match)

        candidates = tuple(unique)
        for rank, match in enumerate(candidates, start=1):
            self._log(
                LogLevel.DEBUG,
                "Skill resolution candidate ranked",
                skill=match.name,
                rank=rank,
                capability_score=match.capability_score,
                explicitly_preferred=match.name.casefold() in preference_order,
                preferred=match.preferred,
                priority=match.priority,
            )

        if not candidates:
            reason_code = (
                "no_available_skill"
                if supplied and available_only
                else "no_matching_skill"
            )
            result = SkillResolutionResult(
                decision="unresolved",
                reason_code=reason_code,
                reason=(
                    "No available skill matched the requested capabilities."
                    if reason_code == "no_available_skill"
                    else "No skill matched the requested capabilities."
                ),
                requested_capabilities=requested,
                candidates=(),
            )
        else:
            selected = candidates[0]
            result = SkillResolutionResult(
                decision="resolved",
                reason_code="skill_selected",
                reason="The highest-ranked matching skill was selected.",
                requested_capabilities=requested,
                selected=selected,
                candidates=candidates,
            )

        self._publish(result, preference_order)
        self._log(
            LogLevel.INFO,
            "Skill resolution completed",
            decision=result.decision,
            reason_code=result.reason_code,
            selected_skill=(
                result.selected.name if result.selected is not None else None
            ),
            candidate_count=len(result.candidates),
        )
        return result

    @staticmethod
    def _requested_capabilities(
        matches: tuple[CapabilityMatchResult, ...],
        requested_capabilities: (
            Iterable[str | SkillCapability] | str | SkillCapability | None
        ),
    ) -> tuple[str, ...]:
        """Resolve and validate the capability request represented by matches."""

        if requested_capabilities is not None:
            return _normalize_capabilities(
                requested_capabilities,
                allow_empty=not matches,
            )
        if not matches:
            return ()
        requested = matches[0].requested_capabilities
        if any(match.requested_capabilities != requested for match in matches[1:]):
            raise ValueError("all match results must represent the same request")
        return requested

    @staticmethod
    def _filtered_candidates(
        candidates: Iterable[SkillCandidate | CapabilityMatchResult] | None,
        category: SkillCategory | None,
    ) -> tuple[SkillCandidate | CapabilityMatchResult, ...] | None:
        """Materialize explicit candidates and apply an optional category filter."""

        if candidates is None:
            return None
        try:
            supplied = tuple(candidates)
        except TypeError as error:
            raise TypeError("candidates must be an iterable") from error
        filtered: list[SkillCandidate | CapabilityMatchResult] = []
        for candidate in supplied:
            if isinstance(candidate, CapabilityMatchResult):
                candidate_category = candidate.metadata.category
            elif isinstance(candidate, SkillDiscoveryResult):
                candidate_category = candidate.metadata.category
            elif isinstance(candidate, SkillDefinition):
                candidate_category = candidate.metadata.category
            else:
                raise TypeError(
                    "candidates must contain typed skill or match results"
                )
            if category is None or candidate_category is category:
                filtered.append(candidate)
        return tuple(filtered)

    def _publish(
        self,
        result: SkillResolutionResult,
        preference_order: dict[str, int],
    ) -> None:
        """Publish one resolution outcome without changing resolver behavior."""

        if self._event_bus is None:
            return
        selected = result.selected
        payload: dict[str, object] = {
            "decision": result.decision,
            "reason_code": result.reason_code,
            "requested_capabilities": result.requested_capabilities,
            "candidate_count": len(result.candidates),
            "name": selected.name if selected is not None else None,
            "capability_score": (
                selected.capability_score if selected is not None else 0.0
            ),
            "priority": selected.priority if selected is not None else None,
            "available": selected.available if selected is not None else None,
            "preferred": (
                selected is not None
                and (
                    selected.preferred
                    or selected.name.casefold() in preference_order
                )
            ),
        }
        try:
            self._event_bus.publish(SystemEvent(name=self.RESOLVED_EVENT, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish skill resolution event",
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit one Core logger entry without changing resolution behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


def _as_direct_matches(
    value: object,
) -> tuple[CapabilityMatchResult, ...] | None:
    """Recognize an explicit iterable of precomputed match results."""

    if isinstance(value, (str, SkillCapability)):
        return None
    try:
        supplied = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return None
    if supplied and all(
        isinstance(item, CapabilityMatchResult) for item in supplied
    ):
        return supplied
    return None


def _normalize_preferred_skills(
    preferred_skills: Iterable[str] | str,
    preferred_skill: str | None,
) -> tuple[str, ...]:
    """Return deterministic, unique explicit skill preferences."""

    if isinstance(preferred_skills, str):
        values = (preferred_skills,)
    else:
        try:
            values = tuple(preferred_skills)
        except TypeError as error:
            raise TypeError("preferred_skills must be an iterable") from error
    if preferred_skill is not None:
        values = (preferred_skill, *values)

    names: list[str] = []
    seen: set[str] = set()
    for name in values:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("preferred skills must contain non-empty strings")
        if name != name.strip():
            raise ValueError(
                "preferred skills must not contain surrounding whitespace"
            )
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            names.append(name)
    return tuple(names)


def _resolution_order(
    match: CapabilityMatchResult,
    preference_order: dict[str, int],
) -> tuple[float, int, int, int, int, str, str, str, str]:
    """Return the documented total order used to select one skill."""

    name_key = match.name.casefold()
    explicit_index = preference_order.get(name_key)
    return (
        -match.capability_score,
        0 if explicit_index is not None else 1,
        explicit_index if explicit_index is not None else len(preference_order),
        0 if match.preferred else 1,
        -match.priority,
        name_key,
        match.name,
        match.metadata.version.casefold(),
        match.metadata.version,
    )


__all__ = ["SkillResolver"]
