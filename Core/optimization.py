"""Runtime optimization and lightweight telemetry services for NARVIS Core.

This module provides a small cache and timing/counter registry that higher-
level packages can use to avoid repeated work while preserving dependency
injection and testability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable, Protocol, TypeVar

T = TypeVar("T")


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
    """Protocol for dependency-injection containers used by Core services."""

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a concrete instance in the container."""


@dataclass(slots=True, frozen=True)
class RuntimeMetric:
    """Represents one aggregated runtime metric."""

    name: str
    count: int = 0
    total_duration_ms: float = 0.0
    average_duration_ms: float = 0.0
    last_duration_ms: float | None = None


@dataclass(slots=True, frozen=True)
class OptimizationSnapshot:
    """Represents the optimization service state at a point in time."""

    cache_entries: int
    cache_hits: int
    cache_misses: int
    counters: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, RuntimeMetric] = field(default_factory=dict)


@dataclass(slots=True)
class _CacheEntry:
    """Internal mutable cache entry representation."""

    value: Any
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    def is_expired(self, reference_time: datetime | None = None) -> bool:
        """Return whether the cache entry has expired."""

        if self.expires_at is None:
            return False
        return self.expires_at <= (reference_time or utc_now())


class RuntimeOptimizationService:
    """Provide small runtime caches, counters, and timing metrics."""

    def __init__(self, logger: Any | None = None) -> None:
        self.logger = logger
        self._lock = RLock()
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._counters: dict[str, int] = {}
        self._metric_counts: dict[str, int] = {}
        self._metric_totals_ms: dict[str, float] = {}
        self._metric_last_ms: dict[str, float] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    def get(self, namespace: str, key: str) -> Any | None:
        """Return a cached value if it exists and has not expired."""

        composite_key = (namespace, key)
        with self._lock:
            self._purge_expired_locked()
            entry = self._cache.get(composite_key)
            if entry is None:
                self._cache_misses += 1
                return None
            self._cache_hits += 1
            return entry.value

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: float | None = None) -> Any:
        """Store a value in the cache and return it."""

        expires_at = None
        if ttl_seconds is not None and ttl_seconds > 0:
            expires_at = utc_now() + timedelta(seconds=ttl_seconds)

        with self._lock:
            self._cache[(namespace, key)] = _CacheEntry(value=value, expires_at=expires_at)
        _emit_log(self.logger, "debug", "Cached runtime value", namespace=namespace, key=key, ttl_seconds=ttl_seconds)
        return value

    def get_or_set(
        self,
        namespace: str,
        key: str,
        factory: Callable[[], T],
        ttl_seconds: float | None = None,
    ) -> T:
        """Return a cached value or create and cache one using ``factory``."""

        cached = self.get(namespace, key)
        if cached is not None:
            return cached
        value = factory()
        self.set(namespace, key, value, ttl_seconds=ttl_seconds)
        return value

    def invalidate(self, namespace: str, key: str | None = None) -> None:
        """Invalidate one cache entry or an entire namespace."""

        with self._lock:
            if key is not None:
                self._cache.pop((namespace, key), None)
                return

            targets = [composite_key for composite_key in self._cache if composite_key[0] == namespace]
            for composite_key in targets:
                self._cache.pop(composite_key, None)

    def increment_counter(self, name: str, amount: int = 1) -> int:
        """Increment a named counter and return its updated value."""

        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount
            return self._counters[name]

    def record_timing(self, name: str, duration_seconds: float) -> RuntimeMetric:
        """Record a duration measurement for a named operation."""

        duration_ms = round(max(duration_seconds, 0.0) * 1000.0, 3)
        with self._lock:
            count = self._metric_counts.get(name, 0) + 1
            total_ms = self._metric_totals_ms.get(name, 0.0) + duration_ms
            self._metric_counts[name] = count
            self._metric_totals_ms[name] = total_ms
            self._metric_last_ms[name] = duration_ms
            metric = RuntimeMetric(
                name=name,
                count=count,
                total_duration_ms=round(total_ms, 3),
                average_duration_ms=round(total_ms / count, 3),
                last_duration_ms=duration_ms,
            )
        return metric

    def snapshot(self) -> OptimizationSnapshot:
        """Return a read-only snapshot of optimization metrics and cache state."""

        with self._lock:
            self._purge_expired_locked()
            metrics = {
                name: RuntimeMetric(
                    name=name,
                    count=self._metric_counts.get(name, 0),
                    total_duration_ms=round(self._metric_totals_ms.get(name, 0.0), 3),
                    average_duration_ms=round(
                        self._metric_totals_ms.get(name, 0.0) / max(self._metric_counts.get(name, 1), 1),
                        3,
                    ),
                    last_duration_ms=self._metric_last_ms.get(name),
                )
                for name in sorted(self._metric_counts)
            }
            return OptimizationSnapshot(
                cache_entries=len(self._cache),
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                counters=dict(sorted(self._counters.items())),
                metrics=metrics,
            )

    def _purge_expired_locked(self) -> None:
        """Remove expired cache entries while the internal lock is held."""

        reference_time = utc_now()
        expired_keys = [
            composite_key
            for composite_key, entry in self._cache.items()
            if entry.is_expired(reference_time)
        ]
        for composite_key in expired_keys:
            self._cache.pop(composite_key, None)


def register_runtime_optimization_services(
    container: DependencyRegistrar,
    *,
    service: RuntimeOptimizationService | None = None,
    logger: Any | None = None,
) -> RuntimeOptimizationService:
    """Register runtime optimization services in the dependency container."""

    resolved_service = service or RuntimeOptimizationService(logger=logger)
    container.register_instance("runtime_optimizer", resolved_service)
    container.register_instance("runtime_cache", resolved_service)
    container.register_instance("runtime_telemetry", resolved_service)
    _emit_log(logger, "info", "Registered runtime optimization services")
    return resolved_service


__all__ = [
    "DependencyRegistrar",
    "OptimizationSnapshot",
    "RuntimeMetric",
    "RuntimeOptimizationService",
    "register_runtime_optimization_services",
    "utc_now",
]
