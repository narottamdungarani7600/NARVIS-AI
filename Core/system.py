"""System composition abstractions for NARVIS Core.

This module defines lightweight system-level primitives for registering and
coordinating reusable components that can later host Voice, Vision, Memory,
and Automation services.
"""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class ComponentState(str, Enum):
    """Lifecycle state for system components."""

    NEW = "new"
    INITIALIZED = "initialized"
    RUNNING = "running"
    STOPPED = "stopped"


class SystemComponent(Protocol):
    """Protocol for reusable architectural components."""

    name: str

    def initialize(self, context: Any) -> None:
        """Initialize the component with system context."""

    def shutdown(self) -> None:
        """Release resources held by the component."""


class BaseSystemComponent(ABC):
    """Abstract base class for system components."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.state: ComponentState = ComponentState.NEW

    def initialize(self, context: Any) -> None:
        """Initialize the component and update its state."""
        self._initialize(context)
        self.state = ComponentState.INITIALIZED

    def shutdown(self) -> None:
        """Stop the component and update its state."""
        self._shutdown()
        self.state = ComponentState.STOPPED

    @abstractmethod
    def _initialize(self, context: Any) -> None:
        """Component-specific initialization logic."""

    @abstractmethod
    def _shutdown(self) -> None:
        """Component-specific shutdown logic."""


class SystemCoordinator:
    """Registers and coordinates system components."""

    def __init__(self) -> None:
        self._components: dict[str, SystemComponent] = {}

    def register(self, component: SystemComponent) -> None:
        """Register a component under its unique name."""
        self._components[component.name] = component

    def get_component(self, name: str) -> SystemComponent | None:
        """Return a registered component by name."""
        return self._components.get(name)

    def initialize_all(self, context: Any) -> None:
        """Initialize each registered component."""
        for component in self._components.values():
            component.initialize(context)

    def shutdown_all(self) -> None:
        """Shut down each registered component."""
        for component in self._components.values():
            component.shutdown()


class DependencyContainer:
    """Simple dependency injection container for service registration."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Any]] = {}
        self._instances: dict[str, Any] = {}

    def register_factory(self, name: str, factory: Callable[[], Any]) -> None:
        """Register a factory for lazy service creation."""
        self._factories[name] = factory

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance directly."""
        self._instances[name] = instance

    def resolve(self, name: str) -> Any:
        """Resolve a service by name from either instances or factories."""
        if name in self._instances:
            return self._instances[name]
        if name in self._factories:
            instance = self._factories[name]()
            self._instances[name] = instance
            return instance
        raise KeyError(f"Service '{name}' is not registered")

    def is_registered(self, name: str) -> bool:
        """Return whether a service name is registered without resolving it."""

        if not isinstance(name, str) or not name:
            return False
        return name in self._instances or name in self._factories

    def registered_services(self) -> tuple[str, ...]:
        """Return deterministic service names without invoking any factory."""

        return tuple(sorted(set(self._instances) | set(self._factories)))

    def clear(self) -> None:
        """Clear registered instances and factories."""
        self._instances.clear()
        self._factories.clear()


@dataclass(slots=True)
class SystemEvent:
    """Represents a domain event emitted through the event bus."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """A simple in-process event bus for subsystem communication."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[SystemEvent], None]]] = {}

    def subscribe(self, event_name: str, handler: Callable[[SystemEvent], None]) -> None:
        """Register a handler for a named event."""
        self._subscribers.setdefault(event_name, []).append(handler)

    def publish(self, event: SystemEvent) -> None:
        """Publish an event to all subscribers."""
        for handler in self._subscribers.get(event.name, []):
            handler(event)


class ModuleLoader:
    """Loads Python modules dynamically for runtime composition."""

    def __init__(self, container: DependencyContainer | None = None) -> None:
        self.container = container
        self._loaded_modules: dict[str, Any] = {}

    def load_module(self, module_name: str) -> Any:
        """Import a module using the standard importlib machinery."""
        if module_name in self._loaded_modules:
            return self._loaded_modules[module_name]
        module = importlib.import_module(module_name)
        self._loaded_modules[module_name] = module
        return module


@dataclass(slots=True)
class HealthReport:
    """Represents the health of a named component."""

    name: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)


class HealthChecker:
    """Collects health information for registered system components."""

    def __init__(self) -> None:
        self._checks: dict[str, Callable[[], HealthReport]] = {}

    def register(self, name: str, checker: Callable[[], HealthReport]) -> None:
        """Register a health-checking function."""
        self._checks[name] = checker

    def check_all(self) -> dict[str, HealthReport]:
        """Run all registered health checks and return the results."""
        return {name: checker() for name, checker in self._checks.items()}


class ExceptionHandler:
    """Centralizes exception handling and logging."""

    def __init__(self, logger: Any) -> None:
        self.logger = logger

    def handle(self, error: Exception, context: str | None = None) -> None:
        """Log an exception and preserve the error for downstream handling."""
        from Core.logger import LogLevel

        message = f"{context}: {error}" if context else str(error)
        self.logger.log(LogLevel.ERROR, message)


class LifecycleManager:
    """Coordinates startup, shutdown, and lifecycle reporting."""

    def __init__(
        self,
        startup_manager: Any,
        coordinator: SystemCoordinator,
        event_bus: EventBus,
        exception_handler: ExceptionHandler,
    ) -> None:
        self.startup_manager = startup_manager
        self.coordinator = coordinator
        self.event_bus = event_bus
        self.exception_handler = exception_handler

    def start(self, context: Any) -> None:
        """Run startup hooks and initialize registered components."""
        try:
            self.startup_manager.run(context)
            self.coordinator.initialize_all(context)
            self.event_bus.publish(SystemEvent(name="system.started", payload={"status": "ready"}))
        except Exception as error:  # pragma: no cover - defensive handling
            self.exception_handler.handle(error, "startup")
            raise

    def stop(self) -> None:
        """Shut down registered components gracefully."""
        try:
            self.coordinator.shutdown_all()
            self.event_bus.publish(SystemEvent(name="system.stopped", payload={"status": "shutdown"}))
        except Exception as error:  # pragma: no cover - defensive handling
            self.exception_handler.handle(error, "shutdown")
            raise


class PluginHook(Protocol):
    """Protocol for plugin hook implementations."""

    def load(self, container: DependencyContainer, event_bus: EventBus, logger: Any) -> None:
        """Load a plugin into the runtime environment."""


class PluginLoader:
    """Loads and registers runtime plugin hooks."""

    def __init__(self, hooks: list[PluginHook] | None = None) -> None:
        self._hooks: list[PluginHook] = list(hooks or [])

    def register_hook(self, hook: PluginHook) -> None:
        """Register a plugin hook."""
        self._hooks.append(hook)

    def load_all(self, container: DependencyContainer, event_bus: EventBus, logger: Any) -> None:
        """Execute all registered plugin hooks."""
        for hook in self._hooks:
            if hasattr(hook, "load"):
                hook.load(container, event_bus, logger)
            elif callable(hook):
                hook(container, event_bus, logger)
            else:
                raise TypeError(f"Unsupported plugin hook type: {type(hook)!r}")
