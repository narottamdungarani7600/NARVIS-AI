"""Plugin metadata and registration helpers for the NARVIS runtime.

This module complements the low-level plugin loader by tracking plugin
descriptors, load state, and runtime-visible metadata without changing the
existing plugin hook contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable, Protocol


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


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
    """Protocol for dependency-injection containers used by plugin services."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


class EventPublisher(Protocol):
    """Protocol for event buses used by managed plugin hooks."""

    def publish(self, event: Any) -> None:
        """Publish an event."""


class PluginHookContract(Protocol):
    """Protocol implemented by runtime plugin hooks."""

    def load(self, container: Any, event_bus: Any, logger: Any) -> None:
        """Load the plugin into the runtime."""


@dataclass(slots=True, frozen=True)
class PluginDescriptor:
    """Describes a plugin known to the NARVIS runtime."""

    name: str
    version: str = "1.0"
    description: str = ""
    kind: str = "runtime"
    services: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RegisteredPlugin:
    """Represents the current runtime state of a registered plugin."""

    descriptor: PluginDescriptor
    loaded: bool = False
    load_count: int = 0
    last_loaded_at: datetime | None = None


class PluginRegistry:
    """Track plugin descriptors and load state for dashboard and runtime use."""

    def __init__(self, logger: Any | None = None) -> None:
        self.logger = logger
        self._lock = RLock()
        self._plugins: dict[str, RegisteredPlugin] = {}

    def register(self, descriptor: PluginDescriptor) -> RegisteredPlugin:
        """Register or update a plugin descriptor."""

        with self._lock:
            existing = self._plugins.get(descriptor.name)
            if existing is None:
                registered = RegisteredPlugin(descriptor=descriptor)
            else:
                registered = RegisteredPlugin(
                    descriptor=descriptor,
                    loaded=existing.loaded,
                    load_count=existing.load_count,
                    last_loaded_at=existing.last_loaded_at,
                )
            self._plugins[descriptor.name] = registered
        _emit_log(self.logger, "debug", "Registered plugin descriptor", plugin=descriptor.name, kind=descriptor.kind)
        return registered

    def mark_loaded(self, name: str) -> RegisteredPlugin:
        """Mark a registered plugin as loaded."""

        with self._lock:
            registered = self._plugins[name]
            loaded = RegisteredPlugin(
                descriptor=registered.descriptor,
                loaded=True,
                load_count=registered.load_count + 1,
                last_loaded_at=utc_now(),
            )
            self._plugins[name] = loaded
        _emit_log(self.logger, "info", "Plugin loaded", plugin=name, load_count=loaded.load_count)
        return loaded

    def get(self, name: str) -> RegisteredPlugin | None:
        """Return a registered plugin by name."""

        with self._lock:
            return self._plugins.get(name)

    def list_plugins(self) -> tuple[RegisteredPlugin, ...]:
        """Return every registered plugin sorted by name."""

        with self._lock:
            return tuple(self._plugins[name] for name in sorted(self._plugins))

    def total_count(self) -> int:
        """Return the total number of registered plugins."""

        with self._lock:
            return len(self._plugins)

    def loaded_count(self) -> int:
        """Return the number of plugins loaded at least once."""

        with self._lock:
            return sum(1 for plugin in self._plugins.values() if plugin.loaded)


class ManagedPluginHook:
    """Wrap a plugin hook with descriptor registration and load tracking."""

    def __init__(
        self,
        descriptor: PluginDescriptor,
        hook: PluginHookContract | Callable[[Any, Any, Any], None],
        registry: PluginRegistry,
        logger: Any | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.hook = hook
        self.registry = registry
        self.logger = logger

    def load(self, container: Any, event_bus: EventPublisher | None = None, logger: Any | None = None) -> None:
        """Register the descriptor, invoke the hook, and mark it as loaded."""

        resolved_logger = logger or self.logger
        self.registry.register(self.descriptor)
        if hasattr(self.hook, "load"):
            self.hook.load(container, event_bus, resolved_logger)
        else:
            self.hook(container, event_bus, resolved_logger)
        self.registry.mark_loaded(self.descriptor.name)

        if event_bus is not None:
            try:
                from Core.system import SystemEvent

                event_bus.publish(
                    SystemEvent(
                        name="plugin.loaded",
                        payload={"name": self.descriptor.name, "kind": self.descriptor.kind},
                    )
                )
            except Exception:
                _emit_log(resolved_logger, "warning", "Unable to publish plugin loaded event", plugin=self.descriptor.name)


def register_plugin_services(
    container: DependencyRegistrar,
    *,
    registry: PluginRegistry | None = None,
    loader: Any | None = None,
    logger: Any | None = None,
) -> PluginRegistry:
    """Register plugin metadata services in the dependency container."""

    resolved_registry = registry or PluginRegistry(logger=logger)
    container.register_instance("plugin_registry", resolved_registry)
    if loader is not None:
        container.register_instance("plugin_loader", loader)
    _emit_log(logger, "info", "Registered plugin services in container")
    return resolved_registry


__all__ = [
    "DependencyRegistrar",
    "EventPublisher",
    "ManagedPluginHook",
    "PluginDescriptor",
    "PluginHookContract",
    "PluginRegistry",
    "RegisteredPlugin",
    "register_plugin_services",
    "utc_now",
]
