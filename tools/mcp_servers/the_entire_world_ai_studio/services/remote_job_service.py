"""Persistent-ish remote job records for command frontends.

This first layer is in-memory and serializable. The shape is intentionally
stable so a disk-backed store can replace it without changing the remote API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


JOB_STATES = {
    "queued",
    "planning",
    "awaiting_confirmation",
    "launching_application",
    "connecting",
    "executing",
    "validating",
    "completed",
    "cancelled",
    "failed",
    "rollback_available",
}

FINISHED_JOB_STATES = {"completed", "cancelled", "failed", "rollback_available"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
