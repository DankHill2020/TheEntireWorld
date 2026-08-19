"""Bounded provider-aware scheduling for synchronous LLM requests."""

from __future__ import annotations

from collections import deque
from contextvars import Context, copy_context
from dataclasses import asdict, dataclass, field
import threading
import time
import uuid
from typing import Any, Callable


LLM_QUEUE_PRIORITIES = {
    "background": 20,
    "validation": 70,
    "repair": 80,
    "interactive": 100,
}


def _positive_int(value: Any, default: int) -> int:
    """Return a positive integer setting or its safe default.

    :param value: Untrusted settings value.
    :param default: Fallback value.
    :return: Positive integer.
    """

    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, int(default))


def _positive_float(value: Any, default: float) -> float:
    """Return a positive floating-point setting or its safe default.

    :param value: Untrusted settings value.
    :param default: Fallback value.
    :return: Positive floating-point value.
    """

    try:
        return max(0.1, float(value))
    except (TypeError, ValueError):
        return max(0.1, float(default))


def llm_queue_lane_options(
    settings: dict[str, Any] | None,
    provider: str,
) -> dict[str, int | float]:
    """Resolve validated queue capacity for a provider lane.

    :param settings: Tech Connector settings.
    :param provider: Resolved provider name.
    :return: Queue submission capacity options.
    """

    values = dict(settings or {})
    cloud_active = str(provider or "ollama").strip().casefold() != "ollama"
    concurrency_default = 4 if cloud_active else 1
    pending_default = 64 if cloud_active else 32
    pending_fallback = _positive_int(
        values.get("llm_queue_max_pending"),
        pending_default,
    )
    return {
        "concurrency": _positive_int(
            values.get(
                "llm_cloud_max_concurrent"
                if cloud_active
                else "llm_local_max_concurrent"
            ),
            concurrency_default,
        ),
        "max_pending": _positive_int(
            values.get(
                "llm_cloud_queue_max_pending"
                if cloud_active
                else "llm_local_queue_max_pending"
            ),
            pending_fallback,
        ),
        "aging_seconds": _positive_float(
            values.get("llm_queue_aging_seconds"),
            15.0,
        ),
    }


class LLMQueueError(RuntimeError):
    """Base class for LLM queue failures."""


class LLMQueueFullError(LLMQueueError):
    """Raised when a bounded provider lane cannot accept more work."""


class LLMQueueCancelledError(LLMQueueError):
    """Raised when queued or running work is cancelled or superseded."""


class LLMQueueDeadlineExceeded(LLMQueueError):
    """Raised when work cannot start before its queue deadline."""


@dataclass(frozen=True)
class LLMQueueRequestSnapshot:
    """Describe one request without exposing its executable callback.

    :param request_id: Stable request correlation identifier.
    :param lane: Provider scheduling lane.
    :param provider: Resolved provider name.
    :param model: Resolved model name.
    :param category: Scheduling category.
    :param priority: Base scheduling priority.
    :param status: Current request state.
    :param submitted_at: Monotonic submission timestamp.
    :param started_at: Monotonic start timestamp, or zero while queued.
    :param finished_at: Monotonic finish timestamp, or zero while active.
    :param wait_seconds: Queue wait duration observed so far.
    :param run_seconds: Provider execution duration observed so far.
    :param supersede_key: Optional key used to replace stale queued work.
    :param error: Concise terminal error.
    """

    request_id: str
    lane: str
    provider: str
    model: str
    category: str
    priority: int
    status: str
    submitted_at: float
    started_at: float
    finished_at: float
    wait_seconds: float
    run_seconds: float
    supersede_key: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible request snapshot.

        :return: Snapshot fields as a dictionary.
        """

        return asdict(self)


@dataclass
class _QueueJob:
    request_id: str
    lane: str
    provider: str
    model: str
    category: str
    priority: int
    sequence: int
    submitted_at: float
    deadline_at: float
    supersede_key: str
    execute: Callable[[], Any]
    context: Context
    cancel_event: threading.Event | None = None
    status: str = "queued"
    started_at: float = 0.0
    finished_at: float = 0.0
    result: Any = None
    error: BaseException | None = None
    completion: threading.Event = field(default_factory=threading.Event)


class _ProviderLane:
    """Schedule one provider lane with bounded pending work."""

    def __init__(
        self,
        lane: str,
        *,
        concurrency: int,
        max_pending: int,
        aging_seconds: float,
        history_limit: int,
    ) -> None:
        self.lane = lane
        self.concurrency = max(1, int(concurrency))
        self.max_pending = max(1, int(max_pending))
        self.aging_seconds = max(0.1, float(aging_seconds))
        self._condition = threading.Condition(threading.RLock())
        self._pending: list[_QueueJob] = []
        self._running: dict[str, _QueueJob] = {}
        self._requests: dict[str, _QueueJob] = {}
        self._history: deque[LLMQueueRequestSnapshot] = deque(
            maxlen=max(1, int(history_limit))
        )
        self._workers: list[threading.Thread] = []
        self._closed = False
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._ensure_workers()

    def configure(
        self,
        *,
        concurrency: int,
        max_pending: int,
        aging_seconds: float,
    ) -> None:
        """Increase lane capacity without interrupting active work.

        :param concurrency: Desired worker count.
        :param max_pending: Desired pending queue bound.
        :param aging_seconds: Wait interval used to increase effective priority.
        :return: None.
        """

        with self._condition:
            self.concurrency = max(1, int(concurrency))
            self.max_pending = max(1, int(max_pending))
            self.aging_seconds = max(0.1, float(aging_seconds))
            self._ensure_workers()
            self._condition.notify_all()

    def submit(self, job: _QueueJob) -> Any:
        """Queue a job and synchronously return its provider result.

        :param job: Fully configured queue job.
        :return: Provider callback result.
        """

        with self._condition:
            if self._closed:
                raise LLMQueueError(f"LLM queue lane {self.lane!r} is closed.")
            existing_request = self._requests.get(job.request_id)
            if existing_request is not None and existing_request.status in {
                "queued",
                "running",
            }:
                raise LLMQueueError(
                    f"LLM request id {job.request_id!r} is already active "
                    f"in lane {self.lane!r}."
                )
            if job.supersede_key:
                for existing in list(self._pending):
                    if existing.supersede_key == job.supersede_key:
                        self._cancel_locked(
                            existing,
                            "Superseded by a newer queued request.",
                        )
            if len(self._pending) >= self.max_pending:
                raise LLMQueueFullError(
                    f"LLM queue lane {self.lane!r} is full "
                    f"({self.max_pending} pending request(s))."
                )
            self._requests[job.request_id] = job
            self._pending.append(job)
            self._condition.notify_all()

        while not job.completion.wait(0.05):
            if job.cancel_event is not None and job.cancel_event.is_set():
                self.cancel(job.request_id, "Cancelled by the caller.")
            if job.deadline_at and time.monotonic() >= job.deadline_at:
                with self._condition:
                    if job.status == "queued":
                        self._expire_locked(job)
        if job.error is not None:
            raise job.error
        return job.result

    def cancel(self, request_id: str, reason: str) -> bool:
        """Cancel queued work or detach a caller from running work.

        :param request_id: Request correlation identifier.
        :param reason: User-facing cancellation reason.
        :return: True when the request was active.
        """

        with self._condition:
            job = self._requests.get(request_id)
            if job is None or job.status in {
                "cancelled",
                "completed",
                "deadline_exceeded",
                "failed",
            }:
                return False
            self._cancel_locked(job, reason)
            self._condition.notify_all()
            return True

    def snapshot(self) -> dict[str, Any]:
        """Return lane depth, activity, counters, and recent requests.

        :return: JSON-compatible lane telemetry.
        """

        with self._condition:
            now = time.monotonic()
            active = [
                self._snapshot_job(job, now)
                for job in [*self._running.values(), *self._pending]
            ]
            recent = list(self._history)
            waits = [item.wait_seconds for item in recent if item.started_at]
            runs = [item.run_seconds for item in recent if item.finished_at]
            return {
                "lane": self.lane,
                "concurrency": self.concurrency,
                "max_pending": self.max_pending,
                "pending": len(self._pending),
                "running": len(self._running),
                "completed": self._completed,
                "failed": self._failed,
                "cancelled": self._cancelled,
                "mean_wait_seconds": round(sum(waits) / len(waits), 6) if waits else 0.0,
                "mean_run_seconds": round(sum(runs) / len(runs), 6) if runs else 0.0,
                "active_requests": [item.to_dict() for item in active],
                "recent_requests": [item.to_dict() for item in recent],
            }

    def shutdown(self, *, wait: bool, cancel_pending: bool) -> None:
        """Stop accepting work and optionally cancel pending requests.

        :param wait: Whether to join worker threads briefly.
        :param cancel_pending: Whether pending requests should fail immediately.
        :return: None.
        """

        with self._condition:
            self._closed = True
            if cancel_pending:
                for job in list(self._pending):
                    self._cancel_locked(job, "LLM queue is shutting down.")
            self._condition.notify_all()
        if wait:
            for worker in list(self._workers):
                worker.join(timeout=2.0)

    def _ensure_workers(self) -> None:
        while len(self._workers) < self.concurrency:
            index = len(self._workers) + 1
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"llm-queue-{self.lane}-{index}",
                daemon=True,
            )
            self._workers.append(worker)
            worker.start()

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                job = self._next_job_locked()
                while job is None:
                    if self._closed:
                        return
                    self._condition.wait(timeout=0.1)
                    job = self._next_job_locked()
                job.status = "running"
                job.started_at = time.monotonic()
                self._running[job.request_id] = job
            try:
                result = job.context.run(job.execute)
            except BaseException as exc:
                with self._condition:
                    if job.status != "cancelled":
                        job.status = "failed"
                        job.error = exc
                        self._failed += 1
            else:
                with self._condition:
                    if job.status != "cancelled":
                        job.status = "completed"
                        job.result = result
                        self._completed += 1
            finally:
                with self._condition:
                    job.finished_at = time.monotonic()
                    self._running.pop(job.request_id, None)
                    self._requests.pop(job.request_id, None)
                    self._history.append(self._snapshot_job(job, job.finished_at))
                    job.completion.set()
                    self._condition.notify_all()

    def _next_job_locked(self) -> _QueueJob | None:
        if len(self._running) >= self.concurrency:
            return None
        now = time.monotonic()
        for job in list(self._pending):
            if job.cancel_event is not None and job.cancel_event.is_set():
                self._cancel_locked(job, "Cancelled before execution.")
            elif job.deadline_at and now >= job.deadline_at:
                self._expire_locked(job)
        if not self._pending:
            return None

        def scheduling_key(job: _QueueJob) -> tuple[float, int]:
            wait = max(0.0, now - job.submitted_at)
            aging_boost = (wait / self.aging_seconds) * 100.0
            return float(job.priority) + aging_boost, -job.sequence

        selected = max(self._pending, key=scheduling_key)
        self._pending.remove(selected)
        return selected

    def _cancel_locked(self, job: _QueueJob, reason: str) -> None:
        if job in self._pending:
            self._pending.remove(job)
        job.status = "cancelled"
        job.error = LLMQueueCancelledError(reason)
        job.finished_at = time.monotonic()
        self._cancelled += 1
        if job.request_id not in self._running:
            self._requests.pop(job.request_id, None)
            self._history.append(self._snapshot_job(job, job.finished_at))
        job.completion.set()

    def _expire_locked(self, job: _QueueJob) -> None:
        if job in self._pending:
            self._pending.remove(job)
        job.status = "deadline_exceeded"
        job.error = LLMQueueDeadlineExceeded(
            f"LLM request {job.request_id} exceeded its queue deadline before starting."
        )
        job.finished_at = time.monotonic()
        self._failed += 1
        self._requests.pop(job.request_id, None)
        self._history.append(self._snapshot_job(job, job.finished_at))
        job.completion.set()

    def _snapshot_job(
        self,
        job: _QueueJob,
        observed_at: float,
    ) -> LLMQueueRequestSnapshot:
        started = job.started_at
        finished = job.finished_at
        wait_end = started or finished or observed_at
        run_end = finished or observed_at
        return LLMQueueRequestSnapshot(
            request_id=job.request_id,
            lane=job.lane,
            provider=job.provider,
            model=job.model,
            category=job.category,
            priority=job.priority,
            status=job.status,
            submitted_at=round(job.submitted_at, 6),
            started_at=round(started, 6),
            finished_at=round(finished, 6),
            wait_seconds=round(max(0.0, wait_end - job.submitted_at), 6),
            run_seconds=round(max(0.0, run_end - started), 6) if started else 0.0,
            supersede_key=job.supersede_key,
            error=str(job.error or ""),
        )


class LLMRequestQueue:
    """Coordinate bounded queues across local and cloud provider lanes."""

    def __init__(self, *, history_limit: int = 100) -> None:
        self.history_limit = max(1, int(history_limit))
        self._lock = threading.RLock()
        self._lanes: dict[str, _ProviderLane] = {}
        self._sequence = 0

    def submit(
        self,
        execute: Callable[[], Any],
        *,
        provider: str,
        model: str,
        category: str = "interactive",
        priority: int | None = None,
        concurrency: int = 1,
        max_pending: int = 32,
        aging_seconds: float = 15.0,
        deadline_seconds: float | None = None,
        request_id: str = "",
        supersede_key: str = "",
        cancel_event: threading.Event | None = None,
    ) -> Any:
        """Execute a synchronous provider call through its bounded queue lane.

        :param execute: Zero-argument provider callback.
        :param provider: Resolved provider name.
        :param model: Resolved model name.
        :param category: Scheduling category.
        :param priority: Optional explicit scheduling priority.
        :param concurrency: Maximum active work for the provider lane.
        :param max_pending: Maximum queued work excluding active requests.
        :param aging_seconds: Wait interval used to increase effective priority.
        :param deadline_seconds: Maximum queue wait before the request expires.
        :param request_id: Optional caller correlation identifier.
        :param supersede_key: Optional key for replacing stale queued requests.
        :param cancel_event: Optional caller cancellation event.
        :return: Provider callback result.
        """

        provider_name = str(provider or "ollama").strip().casefold() or "ollama"
        lane_name = "ollama" if provider_name == "ollama" else provider_name
        category_name = str(category or "interactive").strip().casefold()
        base_priority = int(
            priority
            if priority is not None
            else LLM_QUEUE_PRIORITIES.get(category_name, 50)
        )
        submitted_at = time.monotonic()
        deadline_at = (
            submitted_at + max(0.001, float(deadline_seconds))
            if deadline_seconds is not None
            else 0.0
        )
        with self._lock:
            self._sequence += 1
            lane = self._lanes.get(lane_name)
            if lane is None:
                lane = _ProviderLane(
                    lane_name,
                    concurrency=concurrency,
                    max_pending=max_pending,
                    aging_seconds=aging_seconds,
                    history_limit=self.history_limit,
                )
                self._lanes[lane_name] = lane
            else:
                lane.configure(
                    concurrency=concurrency,
                    max_pending=max_pending,
                    aging_seconds=aging_seconds,
                )
            job = _QueueJob(
                request_id=str(request_id or uuid.uuid4()),
                lane=lane_name,
                provider=provider_name,
                model=str(model or ""),
                category=category_name,
                priority=base_priority,
                sequence=self._sequence,
                submitted_at=submitted_at,
                deadline_at=deadline_at,
                supersede_key=str(supersede_key or ""),
                execute=execute,
                context=copy_context(),
                cancel_event=cancel_event,
            )
        return lane.submit(job)

    def cancel(self, request_id: str, reason: str = "Cancelled by request.") -> bool:
        """Cancel an active request by correlation identifier.

        :param request_id: Request correlation identifier.
        :param reason: User-facing cancellation reason.
        :return: True when an active request was found.
        """

        with self._lock:
            lanes = list(self._lanes.values())
        cancelled = False
        for lane in lanes:
            cancelled = lane.cancel(request_id, reason) or cancelled
        return cancelled

    def snapshot(self) -> dict[str, Any]:
        """Return telemetry for every initialized provider lane.

        :return: Queue telemetry keyed by provider lane.
        """

        with self._lock:
            lanes = dict(self._lanes)
        rows = {name: lane.snapshot() for name, lane in lanes.items()}
        return {
            "lanes": rows,
            "pending": sum(int(row["pending"]) for row in rows.values()),
            "running": sum(int(row["running"]) for row in rows.values()),
        }

    def shutdown(self, *, wait: bool = True, cancel_pending: bool = True) -> None:
        """Shut down all initialized provider lanes.

        :param wait: Whether to join worker threads briefly.
        :param cancel_pending: Whether pending requests should fail immediately.
        :return: None.
        """

        with self._lock:
            lanes = list(self._lanes.values())
            self._lanes.clear()
        for lane in lanes:
            lane.shutdown(wait=wait, cancel_pending=cancel_pending)


_GLOBAL_QUEUE_LOCK = threading.Lock()
_GLOBAL_QUEUE: LLMRequestQueue | None = None


def global_llm_request_queue() -> LLMRequestQueue:
    """Return the process-wide LLM request queue.

    :return: Shared queue instance.
    """

    global _GLOBAL_QUEUE
    with _GLOBAL_QUEUE_LOCK:
        if _GLOBAL_QUEUE is None:
            _GLOBAL_QUEUE = LLMRequestQueue()
        return _GLOBAL_QUEUE


def reset_global_llm_request_queue() -> None:
    """Replace the process queue after cancelling pending work.

    :return: None.
    """

    global _GLOBAL_QUEUE
    with _GLOBAL_QUEUE_LOCK:
        queue = _GLOBAL_QUEUE
        _GLOBAL_QUEUE = None
    if queue is not None:
        queue.shutdown(wait=True, cancel_pending=True)


def llm_request_queue_snapshot() -> dict[str, Any]:
    """Return process-wide queue telemetry for UI and diagnostics.

    :return: JSON-compatible queue telemetry.
    """

    return global_llm_request_queue().snapshot()


def cancel_llm_request(request_id: str, reason: str = "Cancelled by request.") -> bool:
    """Cancel one process-wide queued or running request.

    :param request_id: Request correlation identifier.
    :param reason: User-facing cancellation reason.
    :return: True when an active request was found.
    """

    return global_llm_request_queue().cancel(request_id, reason)
