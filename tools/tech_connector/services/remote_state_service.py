"""Remote command events and job state shared by desktop and mobile clients."""

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


JOB_STATES = {
    "queued",
    "planning",
    "awaiting_confirmation",
    "launching_application",
    "connecting",
    "executing",
    "validating",
    "pausing",
    "paused",
    "resuming",
    "completed",
    "cancelled",
    "failed",
    "rollback_available",
}

FINISHED_JOB_STATES = {"completed", "cancelled", "failed", "rollback_available"}


@dataclass
class RemoteJob:
    command: str
    payload: dict[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"
    current_step: str = "Queued"
    progress: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    rollback: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    context_addenda: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def update(self, *, status: str | None = None, current_step: str | None = None, progress: int | None = None) -> None:
        if status:
            self.status = status if status in JOB_STATES else "failed"
        if current_step is not None:
            self.current_step = current_step
        if progress is not None:
            self.progress = max(0, min(100, int(progress)))
        self.updated_at = utc_now_iso()

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        self.updated_at = utc_now_iso()

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.status = "failed"
        self.current_step = "Failed"
        self.updated_at = utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "command": self.command,
            "payload": dict(self.payload or {}),
            "status": self.status,
            "current_step": self.current_step,
            "progress": self.progress,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "artifacts": list(self.artifacts),
            "reports": list(self.reports),
            "rollback": dict(self.rollback or {}),
            "result": dict(self.result or {}),
            "context_addenda": list(self.context_addenda),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RemoteJobStore:
    def __init__(self):
        self._jobs: dict[str, RemoteJob] = {}

    def create(self, command: str, payload: dict[str, Any] | None = None) -> RemoteJob:
        job = RemoteJob(command=command, payload=payload or {})
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> RemoteJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 50, *, state: str = "all") -> list[dict[str, Any]]:
        jobs = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
        if state == "finished":
            jobs = [job for job in jobs if job.status in FINISHED_JOB_STATES]
        elif state == "active":
            jobs = [job for job in jobs if job.status not in FINISHED_JOB_STATES]
        return [job.to_dict() for job in jobs[:max(1, limit)]]

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in {"completed", "failed", "cancelled"}:
            return False
        job.update(status="cancelled", current_step="Cancelled", progress=job.progress)
        return True

    def pause(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in FINISHED_JOB_STATES or job.status == "paused":
            return False
        job.update(status="pausing", current_step="Pausing after the current safe step")
        return True

    def mark_paused(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in FINISHED_JOB_STATES:
            return False
        job.update(status="paused", current_step="Paused at a safe checkpoint")
        return True

    def add_context(self, job_id: str, text: str) -> bool:
        job = self.get(job_id)
        addendum = str(text or "").strip()
        if not job or not addendum or job.status in FINISHED_JOB_STATES:
            return False
        job.context_addenda.append(addendum)
        job.updated_at = utc_now_iso()
        return True

    def resume(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status != "paused":
            return False
        job.update(status="resuming", current_step="Resuming from the last safe checkpoint")
        return True
