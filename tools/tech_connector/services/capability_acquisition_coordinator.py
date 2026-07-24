"""Resumable orchestration for acquiring a missing callable mid-request."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import uuid
from typing import Any, Callable


TERMINAL_STATES = {"completed", "cancelled", "failed"}
ACTIVE_STATES = {"running", "pausing", "resuming"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AcquisitionCheckpoint:
    step_id: str
    status: str
    started_at: str
    completed_at: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    context_revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": dict(self.result),
            "context_revision": self.context_revision,
        }


@dataclass
class AcquisitionJob:
    plan: dict[str, Any]
    original_request: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"
    current_step_id: str = ""
    current_step_label: str = "Queued"
    progress: int = 0
    context_addenda: list[str] = field(default_factory=list)
    checkpoints: list[AcquisitionCheckpoint] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "current_step_id": self.current_step_id,
            "current_step_label": self.current_step_label,
            "progress": self.progress,
            "original_request": self.original_request,
            "context_addenda": list(self.context_addenda),
            "context_revision": len(self.context_addenda),
            "checkpoints": [item.to_dict() for item in self.checkpoints],
            "errors": list(self.errors),
            "plan": dict(self.plan),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


StageRunner = Callable[[dict[str, Any], AcquisitionJob], dict[str, Any]]
PlanReviser = Callable[[dict[str, Any], list[dict[str, Any]], list[str]], list[dict[str, Any]]]
EventCallback = Callable[[str, dict[str, Any]], None]


class CapabilityAcquisitionCoordinator:
    """Runs an acquisition plan with durable in-memory safe-step checkpoints.

    A running atomic step is allowed to finish. Pause and context requests take
    effect at the next boundary, so completed edits and validation evidence are
    never silently repeated.
    """

    def __init__(
        self,
        plan: dict[str, Any],
        *,
        original_request: str = "",
        stage_runner: StageRunner | None = None,
        plan_reviser: PlanReviser | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        self.job = AcquisitionJob(
            plan=dict(plan or {}),
            original_request=str(original_request or plan.get("original_request") or ""),
        )
        self._stage_runner = stage_runner or self._default_stage_runner
        self._plan_reviser = plan_reviser or self._default_plan_reviser
        self._event_callback = event_callback
        self._pause_requested = threading.Event()
        self._cancel_requested = threading.Event()
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._steps = [dict(step) for step in list(plan.get("steps") or []) if isinstance(step, dict)]
        self._next_index = 0
        self._applied_context_revision = 0

    def start(self) -> dict[str, Any]:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return self.snapshot()
            if self.job.status in TERMINAL_STATES:
                return self.snapshot()
            self.job.status = "running"
            self.job.current_step_label = "Starting capability acquisition"
            self._touch()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        self._emit("started")
        return self.snapshot()

    def request_pause(self) -> dict[str, Any]:
        with self._condition:
            if self.job.status in TERMINAL_STATES or self.job.status == "paused":
                return self.snapshot()
            self._pause_requested.set()
            if self.job.status in ACTIVE_STATES:
                self.job.status = "pausing"
                self.job.current_step_label = (
                    f"Pausing after {self.job.current_step_label}"
                    if self.job.current_step_id
                    else "Pausing at the next safe checkpoint"
                )
                self._touch()
        self._emit("pause_requested")
        return self.snapshot()

    def add_context(self, text: str) -> dict[str, Any]:
        addendum = str(text or "").strip()
        if not addendum:
            return self.snapshot()
        with self._condition:
            if self.job.status in TERMINAL_STATES:
                return self.snapshot()
            self.job.context_addenda.append(addendum)
            self._pause_requested.set()
            if self.job.status in ACTIVE_STATES:
                self.job.status = "pausing"
                self.job.current_step_label = "Context received; pausing after the current safe step"
            self._touch()
        self._emit("context_added", {"context": addendum})
        return self.snapshot()

    def resume(self) -> dict[str, Any]:
        with self._condition:
            if self.job.status != "paused":
                return self.snapshot()
            self._revise_remaining_steps_locked()
            self._pause_requested.clear()
            self.job.status = "resuming"
            self.job.current_step_label = "Resuming from the last completed checkpoint"
            self._touch()
            self._condition.notify_all()
        self._emit("resumed")
        return self.snapshot()

    def cancel(self) -> dict[str, Any]:
        self._cancel_requested.set()
        with self._condition:
            self._condition.notify_all()
        self._emit("cancel_requested")
        return self.snapshot()

    def wait(self, timeout: float | None = None) -> dict[str, Any]:
        thread = self._thread
        if thread:
            thread.join(timeout)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return self.job.to_dict()

    def _run(self) -> None:
        while self._next_index < len(self._steps):
            if not self._checkpoint_control():
                return
            step = self._steps[self._next_index]
            step_id = str(step.get("step_id") or f"step_{self._next_index + 1}")
            checkpoint = AcquisitionCheckpoint(
                step_id=step_id,
                status="running",
                started_at=_utc_now(),
                context_revision=len(self.job.context_addenda),
            )
            with self._condition:
                self.job.status = "running"
                self.job.current_step_id = step_id
                self.job.current_step_label = str(step.get("objective") or step_id)
                self.job.checkpoints.append(checkpoint)
                self._touch()
            self._emit("step_started", {"step": step})
            try:
                result = dict(self._stage_runner(step, self.job) or {})
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            checkpoint.completed_at = _utc_now()
            checkpoint.result = result
            if result.get("pause_required"):
                checkpoint.status = "waiting"
                with self._condition:
                    self.job.status = "paused"
                    self.job.current_step_id = step_id
                    self.job.current_step_label = str(
                        result.get("message")
                        or result.get("error")
                        or "External action is required before this step can continue"
                    )
                    self._touch()
                self._emit("input_required", {"step": step, "result": result})
                with self._condition:
                    while self.job.status == "paused" and not self._cancel_requested.is_set():
                        self._condition.wait()
                    if self._cancel_requested.is_set():
                        self.job.status = "cancelled"
                        self.job.current_step_label = "Cancelled while waiting for external action"
                        self._touch()
                        self._emit("cancelled")
                        return
                continue
            checkpoint.status = "completed" if result.get("ok") else "failed"
            with self._condition:
                if not result.get("ok"):
                    error = str(result.get("error") or result.get("message") or f"{step_id} failed")
                    self.job.errors.append(error)
                    self.job.status = "failed"
                    self.job.current_step_label = error
                    self._touch()
                    self._emit("failed", {"step": step, "result": result})
                    return
                self._next_index += 1
                self.job.progress = int(round((self._next_index / max(1, len(self._steps))) * 100))
                self._touch()
            self._emit("step_completed", {"step": step, "result": result})

        with self._condition:
            self.job.status = "completed"
            self.job.current_step_id = ""
            self.job.current_step_label = "Capability acquired and original request is ready to resume"
            self.job.progress = 100
            self._touch()
        self._emit("completed")

    def _checkpoint_control(self) -> bool:
        with self._condition:
            if self._cancel_requested.is_set():
                self.job.status = "cancelled"
                self.job.current_step_label = "Cancelled at a safe checkpoint"
                self._touch()
                self._emit("cancelled")
                return False
            if self._pause_requested.is_set():
                self.job.status = "paused"
                self.job.current_step_id = ""
                self.job.current_step_label = "Paused at a safe checkpoint"
                self._touch()
                self._emit("paused")
                while self.job.status == "paused" and not self._cancel_requested.is_set():
                    self._condition.wait()
                if self._cancel_requested.is_set():
                    self.job.status = "cancelled"
                    self.job.current_step_label = "Cancelled while paused"
                    self._touch()
                    self._emit("cancelled")
                    return False
            return True

    def _revise_remaining_steps_locked(self) -> None:
        revision = len(self.job.context_addenda)
        if revision <= self._applied_context_revision:
            return
        completed = [item.to_dict() for item in self.job.checkpoints if item.status == "completed"]
        remaining = [dict(step) for step in self._steps[self._next_index :]]
        revised = self._plan_reviser(self.job.plan, remaining, list(self.job.context_addenda))
        self._steps = self._steps[: self._next_index] + [dict(step) for step in revised]
        self.job.plan["steps"] = [dict(step) for step in self._steps]
        self.job.plan["completed_checkpoints"] = completed
        self.job.plan["context_addenda"] = list(self.job.context_addenda)
        self._applied_context_revision = revision

    def _touch(self) -> None:
        self.job.updated_at = _utc_now()

    def _emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        if not self._event_callback:
            return
        data = {"event": event, "job": self.job.to_dict(), **dict(payload or {})}
        try:
            self._event_callback(event, data)
        except Exception:
            pass

    @staticmethod
    def _default_plan_reviser(
        plan: dict[str, Any],
        remaining_steps: list[dict[str, Any]],
        context_addenda: list[str],
    ) -> list[dict[str, Any]]:
        del plan
        revision = len(context_addenda)
        return [
            {**step, "context_revision": revision, "added_context": list(context_addenda)}
            for step in remaining_steps
        ]

    @staticmethod
    def _default_stage_runner(step: dict[str, Any], job: AcquisitionJob) -> dict[str, Any]:
        del job
        if str(step.get("action") or "") == "modify":
            return {
                "ok": False,
                "error": "No concrete capability implementation provider is registered for this modification step.",
            }
        return {"ok": True, "evidence": [str(step.get("success_condition") or "stage completed")]}
