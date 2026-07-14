"""Registry-backed loader for explicitly registered NARVIS skills."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .exceptions import (
    SkillAlreadyLoadedError,
    SkillLoadError,
    SkillNotFoundError,
    SkillNotLoadedError,
    SkillUnloadError,
)
from .interfaces import EventPublisher, SkillInterface
from .models import SkillDefinition
from .registry import SkillRegistry


class SkillLoader:
    """Discover and manage skill lifecycles from an injected registry only.

    This sprint intentionally performs no module imports or filesystem scans.
    """

    LOADED_EVENT = "skill.loaded"
    UNLOADED_EVENT = "skill.unloaded"

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        logger: Logger | None = None,
        event_bus: EventPublisher | None = None,
    ) -> None:
        if not isinstance(registry, SkillRegistry):
            raise TypeError("loader registry must be a SkillRegistry")
        self._registry = registry
        self._logger = logger or NullLogger("narvis.skills.loader")
        self._event_bus = event_bus
        self._loaded: dict[str, SkillInterface[Any, Any]] = {}
        self._lock = RLock()

    @property
    def registry(self) -> SkillRegistry:
        """Return the injected discovery source."""

        return self._registry

    def discover(self) -> tuple[SkillDefinition, ...]:
        """Return all definitions currently available from the registry."""

        definitions = self._registry.list()
        self._log(
            LogLevel.DEBUG,
            "Skills discovered from registry",
            count=len(definitions),
        )
        return definitions

    def load(self, name: str) -> SkillInterface[Any, Any]:
        """Create and initialize one explicitly registered skill."""

        definition = self._registry.find(name)
        if definition is None:
            raise SkillNotFoundError(name)

        with self._lock:
            if name in self._loaded:
                raise SkillAlreadyLoadedError(name)

            try:
                implementation = definition.create()
                self._validate_implementation(name, implementation)
                implementation.initialize()
            except SkillLoadError:
                raise
            except Exception as error:
                self._log(
                    LogLevel.ERROR,
                    "Skill initialization failed",
                    skill=name,
                    error_type=type(error).__name__,
                )
                raise SkillLoadError(name, str(error) or type(error).__name__) from error

            self._loaded[name] = implementation

        self._log(LogLevel.INFO, "Skill loaded", skill=name)
        self._publish(self.LOADED_EVENT, definition)
        return implementation

    def unload(self, name: str) -> SkillInterface[Any, Any]:
        """Shut down and remove one loaded skill instance."""

        with self._lock:
            implementation = self._loaded.get(name)
            if implementation is None:
                raise SkillNotLoadedError(name)

            try:
                implementation.shutdown()
            except Exception as error:
                self._log(
                    LogLevel.ERROR,
                    "Skill shutdown failed",
                    skill=name,
                    error_type=type(error).__name__,
                )
                raise SkillUnloadError(
                    name,
                    str(error) or type(error).__name__,
                ) from error

            del self._loaded[name]

        definition = self._registry.find(name)
        self._log(LogLevel.INFO, "Skill unloaded", skill=name)
        self._publish(
            self.UNLOADED_EVENT,
            definition,
            fallback_name=name,
        )
        return implementation

    def find_loaded(self, name: str) -> SkillInterface[Any, Any] | None:
        """Return a loaded instance without changing its lifecycle."""

        with self._lock:
            return self._loaded.get(name)

    def list_loaded(self) -> tuple[SkillInterface[Any, Any], ...]:
        """Return loaded instances in deterministic skill-name order."""

        with self._lock:
            return tuple(self._loaded[name] for name in sorted(self._loaded))

    def is_loaded(self, name: str) -> bool:
        """Return whether a named skill currently has a loaded instance."""

        return self.find_loaded(name) is not None

    @staticmethod
    def _validate_implementation(name: str, implementation: object) -> None:
        """Reject providers that do not honor the complete lifecycle contract."""

        required_methods = ("initialize", "execute", "shutdown")
        if not all(
            isinstance(getattr(implementation, method, None), Callable)
            for method in required_methods
        ):
            raise SkillLoadError(
                name,
                "implementation must provide initialize(), execute(), and shutdown()",
            )

    def _publish(
        self,
        event_name: str,
        definition: SkillDefinition | None,
        *,
        fallback_name: str = "",
    ) -> None:
        """Publish a lifecycle event without changing lifecycle state on failure."""

        if self._event_bus is None:
            return
        payload: dict[str, object] = {"name": fallback_name}
        if definition is not None:
            payload = {
                "name": definition.metadata.name,
                "version": definition.metadata.version,
                "category": definition.metadata.category.value,
            }
        try:
            self._event_bus.publish(SystemEvent(name=event_name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish skill lifecycle event",
                event_name=event_name,
                error_type=type(error).__name__,
            )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Emit a Core logger entry without changing loader behavior."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return


__all__ = ["SkillLoader"]
