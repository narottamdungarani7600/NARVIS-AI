"""FIFO approval queue for the planning-only safe execution layer."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from threading import RLock
from typing import Protocol

from Core.logger import LogLevel, Logger, NullLogger
from Core.system import SystemEvent

from .exceptions import (
    DuplicateQueueItemError,
    QueueEmptyError,
    QueueItemNotFoundError,
)
from .models import ApprovalRequest, ApprovalStatus, QueueStatus, utc_now


class EventPublisher(Protocol):
    """Structural event publisher accepted through dependency injection."""

    def publish(self, event: SystemEvent) -> None:
        """Publish one system event."""


class ExecutionQueue:
    """Thread-safe FIFO queue of immutable approval requests.

    The queue stores data only.  Dequeuing never dispatches, invokes, or
    otherwise interprets the action described by an approval request.
    """

    QUEUE_UPDATED_EVENT = "queue.updated"
    EXECUTION_CANCELLED_EVENT = "execution.cancelled"

    def __init__(
        self,
        *,
        event_bus: EventPublisher | None = None,
        logger: Logger | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Initialize observable queue dependencies and empty storage."""

        self._event_bus = event_bus
        self._logger = logger or NullLogger("narvis.execution.session.queue")
        self._clock = clock
        self._items: OrderedDict[str, ApprovalRequest] = OrderedDict()
        self._lock = RLock()

    def enqueue(self, request: ApprovalRequest) -> ApprovalRequest:
        """Append one pending approval request to the queue."""

        if not isinstance(request, ApprovalRequest):
            raise TypeError("execution queues accept ApprovalRequest instances")
        if request.status is not ApprovalStatus.PENDING:
            raise ValueError("only pending approval requests may be enqueued")
        with self._lock:
            if request.request_id in self._items:
                raise DuplicateQueueItemError(
                    f"approval request '{request.request_id}' is already queued"
                )
            self._items[request.request_id] = request
            self._publish_update("enqueue", request_id=request.request_id)
        return request

    def dequeue(self) -> ApprovalRequest:
        """Remove and return the oldest queued request without executing it."""

        with self._lock:
            if not self._items:
                raise QueueEmptyError("execution approval queue is empty")
            _, request = self._items.popitem(last=False)
            self._publish_update("dequeue", request_id=request.request_id)
            return request

    def peek(self) -> ApprovalRequest:
        """Return the oldest request without changing queue state."""

        with self._lock:
            if not self._items:
                raise QueueEmptyError("execution approval queue is empty")
            return next(iter(self._items.values()))

    def cancel(
        self,
        request_id: str,
        *,
        reason: str = "queue_cancelled",
    ) -> ApprovalRequest:
        """Cancel and remove one queued approval request."""

        if not isinstance(reason, str) or not reason:
            raise ValueError("cancellation reason must be a non-empty string")
        with self._lock:
            request = self._pop(request_id)
            cancelled = replace(request, status=ApprovalStatus.CANCELLED)
            self._log_approval_event(cancelled, "cancelled")
            self._publish(
                self.EXECUTION_CANCELLED_EVENT,
                {
                    "request_id": cancelled.request_id,
                    "execution_request_id": cancelled.execution_request_id,
                    "session_id": cancelled.session_id,
                    "action": cancelled.action,
                    "status": cancelled.status.value,
                    "reason": reason,
                    "executed": False,
                    "dispatcher_invoked": False,
                },
            )
            self._publish_update("cancel", request_id=cancelled.request_id)
            return cancelled

    def clear(self) -> tuple[ApprovalRequest, ...]:
        """Cancel all queued requests and return immutable cancellation records."""

        with self._lock:
            cancelled = tuple(
                replace(request, status=ApprovalStatus.CANCELLED)
                for request in self._items.values()
            )
            self._items.clear()
            for request in cancelled:
                self._log_approval_event(request, "cancelled")
                self._publish(
                    self.EXECUTION_CANCELLED_EVENT,
                    {
                        "request_id": request.request_id,
                        "execution_request_id": request.execution_request_id,
                        "session_id": request.session_id,
                        "action": request.action,
                        "status": request.status.value,
                        "reason": "queue_cleared",
                        "executed": False,
                        "dispatcher_invoked": False,
                    },
                )
            self._publish_update("clear")
            return cancelled

    def remove(self, request_id: str) -> ApprovalRequest:
        """Remove a resolved request without reporting it as cancelled."""

        with self._lock:
            request = self._pop(request_id)
            self._publish_update("resolve", request_id=request.request_id)
            return request

    def status(self) -> QueueStatus:
        """Return an immutable snapshot of queue state."""

        with self._lock:
            return QueueStatus(
                size=len(self._items),
                request_ids=tuple(self._items),
                updated_at=self._now(),
            )

    @property
    def queue_status(self) -> QueueStatus:
        """Return :meth:`status` for property-oriented callers."""

        return self.status()

    def contains(self, request_id: str) -> bool:
        """Return whether an approval request is currently queued."""

        if not isinstance(request_id, str):
            return False
        with self._lock:
            return request_id in self._items

    def __len__(self) -> int:
        """Return the current queue length."""

        with self._lock:
            return len(self._items)

    def _pop(self, request_id: str) -> ApprovalRequest:
        """Remove one item or raise a typed lookup error."""

        if not isinstance(request_id, str) or not request_id:
            raise QueueItemNotFoundError("a non-empty request_id is required")
        try:
            return self._items.pop(request_id)
        except KeyError as error:
            raise QueueItemNotFoundError(
                f"approval request '{request_id}' is not queued"
            ) from error

    def _publish_update(self, operation: str, *, request_id: str = "") -> None:
        """Publish a non-sensitive queue snapshot after a mutation."""

        self._publish(
            self.QUEUE_UPDATED_EVENT,
            {
                "operation": operation,
                "request_id": request_id,
                "size": len(self._items),
                "request_ids": tuple(self._items),
            },
        )

    def _publish(self, name: str, payload: dict[str, object]) -> None:
        """Publish observability without changing queue control flow."""

        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(SystemEvent(name=name, payload=payload))
        except Exception as error:
            self._log(
                LogLevel.WARNING,
                "Unable to publish safe execution queue event",
                event_name=name,
                error_type=type(error).__name__,
            )

    def _log_approval_event(self, request: ApprovalRequest, outcome: str) -> None:
        """Log a queue-originated approval lifecycle event."""

        self._log(
            LogLevel.INFO,
            "Execution approval cancelled",
            request_id=request.request_id,
            execution_request_id=request.execution_request_id,
            session_id=request.session_id,
            action=request.action,
            approval_status=outcome,
            executed=False,
        )

    def _log(self, level: LogLevel, message: str, **context: object) -> None:
        """Log without allowing observer failure to alter queue state."""

        try:
            self._logger.log(level, message, **context)
        except Exception:
            return

    def _now(self) -> datetime:
        """Read and validate the injected clock."""

        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value


__all__ = ["EventPublisher", "ExecutionQueue", "QueueStatus"]
