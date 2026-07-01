"""Core package for NARVIS."""

from .optimization import (
    OptimizationSnapshot,
    RuntimeMetric,
    RuntimeOptimizationService,
    register_runtime_optimization_services,
)
from .plugins import (
    ManagedPluginHook,
    PluginDescriptor,
    PluginRegistry,
    RegisteredPlugin,
    register_plugin_services,
)

__all__ = [
    "ManagedPluginHook",
    "OptimizationSnapshot",
    "PluginDescriptor",
    "PluginRegistry",
    "RegisteredPlugin",
    "RuntimeMetric",
    "RuntimeOptimizationService",
    "register_plugin_services",
    "register_runtime_optimization_services",
]
