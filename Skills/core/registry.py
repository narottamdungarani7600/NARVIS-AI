"""Thread-safe typed registry for NARVIS skill definitions."""

from __future__ import annotations

from threading import RLock

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .exceptions import DuplicateSkillError, SkillNotFoundError
from .interfaces import EventPublisher
from .models import SkillCategory, SkillDefinition


class SkillRegistry:
    """Store immutable skill definitions under unique metadata names."""

    REGISTERED_EVENT = "skill.registered"

    def __init__(
        self,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        self._logger = logger or NullLogger("narvis.skills.registry")
        self._event_bus = event_bus
        self._definitions: dict[str, SkillDefinition] = {}
        self._lock = RLock()

    def register(self, definition: SkillDefinition) -> SkillDefinition:
        """Register one typed definition without replacing an existing skill."""

        if not isinstance(definition, SkillDefinition):
            raise TypeError("registry entries must be SkillDefinition instances")

        name = definition.metadata.name
        with self._lock:
            if name in self._definitions:
                raise DuplicateSkillError(name)
            self._definitions[name] = definition

        self._log(
            LogLevel.INFO,
            "Skill registered",
            skill=name,
            version=definition.metadata.version,
        )
        self._publish(
            self.REGISTERED_EVENT,
            {
                "name": name,
                "version": definition.metadata.version,
                "category": definition.metadata.category.value,
            },
        )
        return definition

    def unregister(self, name: str) -> SkillDefinition:
        """Remove and return a registered definition."""

        normalized_name = self._validate_name(name)
        with self._lock:
            try:
                definition = self._definitions.pop(normalized_name)
            except KeyError as error:
                raise SkillNotFoundError(normalized_name) from error

        self._log(LogLevel.INFO, "Skill unregistered", skill=normalized_name)
        return definition

    def find(self, name: str) -> SkillDefinition | None:
        """Find a registered definition, returning ``None`` when absent."""

        normalized_name = self._validate_name(name)
        with self._lock:
            return self._definitions.get(normalized_name)

    def list(
        self,
        category: SkillCategory | None = None,
    ) -> tuple[SkillDefinition, ...]:
        """Return a deterministic immutable snapshot of registered skills."""

        if category is not None and not isinstance(category, SkillCategory):
            raise TypeError("category must be a SkillCategory or None")
        with self._lock:
            definitions = tuple(self._definitions.values())
        if category is not None:
            definitions = tuple(
                definition
                for definition in definitions
                if definition.metadata.category is category
            )
        return tuple(sorted(definitions, key=lambda definition: definition.name))

    def exists(self, name: str) -> bool:
        """Return whether a skill name is registered."""

        return self.find(name) is not None

    def __len__(self) -> int:
        """Return the number of registered skill definitions."""

        with self._lock:
            return len(self._definitions)

    @staticmethod
    def _validate_name(name: object) -> str:
        """Return a normalized skill name or raise a clear caller error."""

        if not isinstance(name, str) or not name.strip():
            raise ValueError("skill name must be a non-empty string")
        if name != name.strip():
            raise ValueError("skill name must not contain surrounding whitespace")
        return name

    def _publish(self, event_name: str, payload: dict[str, object]) -> None:
        """Publish an event without allowing subscriber failures to alter state."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish skill registry event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a Core logger entry without changing registry behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["SkillRegistry"]
