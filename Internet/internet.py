"""Core internet abstractions for the NARVIS Internet package.

This module defines reusable contracts for connectivity checks, HTTP access,
and future integrations with search engines, news feeds, weather services,
and content providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class NetworkStatus:
    """Represents the current connectivity state of the runtime environment."""

    online: bool
    latency_ms: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ConnectivityProbe(Protocol):
    """Protocol for network connectivity probes."""

    def check(self) -> NetworkStatus:
        """Check whether the environment has network connectivity."""
