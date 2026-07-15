"""In-process event bus for desktop and future remote frontends."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AppEvent:
    event_type: str
    message: str
    job_id: str = ""
    severity: str = "info"
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "message": self.message,
            "job_id": self.job_id,
            "severity": self.severity,
            "payload": dict(self.payload or {}),
            "created_at": self.created_at,
        }


class AppEventBus:
    """Simple event publisher shared by desktop, jobs, and remote APIs."""

    def __init__(self, max_events: int = 500):
        self._events: deque[AppEvent] = deque(maxlen=max(1, max_events))
        self._subscribers: list[Callable[[AppEvent], None]] = []

    def subscribe(self, callback: Callable[[AppEvent], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def publish(
        self,
        event_type: str,
        message: str,
        *,
        job_id: str = "",
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> AppEvent:
        event = AppEvent(
            event_type=event_type,
            message=message,
            job_id=job_id,
            severity=severity,
            payload=payload or {},
        )
        self._events.append(event)
        for subscriber in list(self._subscribers):
            try:
                subscriber(event)
            except Exception:
                pass
        return event

    def recent_events(self, limit: int = 100, *, after_event_id: str = "") -> list[dict[str, Any]]:
        events = list(self._events)
        if after_event_id:
            for index, event in enumerate(events):
                if event.event_id == after_event_id:
                    events = events[index + 1:]
                    break
        return [event.to_dict() for event in events[-max(1, limit):]]

    def events_for_job(self, job_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if not job_id:
            return []
        events = [event for event in self._events if event.job_id == job_id]
        return [event.to_dict() for event in events[-max(1, limit):]]
