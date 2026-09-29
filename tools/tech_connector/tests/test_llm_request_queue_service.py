"""Tests for bounded provider-aware LLM request scheduling."""

from __future__ import annotations

from contextvars import ContextVar
import threading
import time
from typing import Any, Callable

import pytest

from reasoning_runtime.models import ModelProviderRoute
from tech_connector.services import llm_router_service
from tech_connector.services.llm_request_queue_service import (
    LLMQueueError,
    LLMQueueCancelledError,
    LLMQueueDeadlineExceeded,
    LLMQueueFullError,
    LLMRequestQueue,
    global_llm_request_queue,
    llm_queue_lane_options,
    reset_global_llm_request_queue,
)


def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 2.0,
) -> None:
    """Wait for a deterministic concurrent-test condition.

    :param predicate: Condition checked repeatedly.
    :param timeout: Maximum wait in seconds.
    :return: None.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Concurrent queue condition was not reached in time.")


def _start_submission(
    queue: LLMRequestQueue,
    execute: Callable[[], Any],
    **options: Any,
) -> tuple[threading.Thread, list[Any], list[BaseException]]:
    """Submit queue work on a thread and retain its terminal evidence.

    :param queue: Queue under test.
    :param execute: Provider callback.
    :param options: Queue submission options.
    :return: Thread, result list, and error list.
    """

    results: list[Any] = []
    errors: list[BaseException] = []

    def submit() -> None:
        try:
            results.append(queue.submit(execute, **options))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=submit, daemon=True)
    thread.start()
    return thread, results, errors


def test_priority_queue_runs_interactive_work_before_background() -> None:
    """Prefer high-priority pending work while preserving the active request."""

    queue = LLMRequestQueue()
    release = threading.Event()
    first_started = threading.Event()
    order: list[str] = []

    def first() -> str:
        order.append("first")
        first_started.set()
        assert release.wait(2)
        return "first"

    first_thread, _, first_errors = _start_submission(
        queue,
        first,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="first",
    )
    assert first_started.wait(1)
    low_thread, _, low_errors = _start_submission(
        queue,
        lambda: order.append("background") or "background",
        provider="ollama",
        model="test",
        category="background",
        concurrency=1,
        max_pending=4,
        request_id="background",
    )
    _wait_until(lambda: queue.snapshot()["pending"] == 1)
    high_thread, _, high_errors = _start_submission(
        queue,
        lambda: order.append("interactive") or "interactive",
        provider="ollama",
        model="test",
        category="interactive",
        concurrency=1,
        max_pending=4,
        request_id="interactive",
    )
    _wait_until(lambda: queue.snapshot()["pending"] == 2)

    release.set()
    for thread in (first_thread, low_thread, high_thread):
        thread.join(2)
        assert not thread.is_alive()

    assert not [*first_errors, *low_errors, *high_errors]
    assert order == ["first", "interactive", "background"]
    queue.shutdown()


def test_queue_applies_backpressure_at_pending_limit() -> None:
    """Reject excess work rather than allowing an unbounded backlog."""

    queue = LLMRequestQueue()
    release = threading.Event()
    started = threading.Event()

    def active() -> None:
        started.set()
        assert release.wait(2)

    active_thread, _, active_errors = _start_submission(
        queue,
        active,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=1,
        request_id="active",
    )
    assert started.wait(1)
    pending_thread, _, pending_errors = _start_submission(
        queue,
        lambda: None,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=1,
        request_id="pending",
    )
    _wait_until(lambda: queue.snapshot()["pending"] == 1)

    with pytest.raises(LLMQueueFullError):
        queue.submit(
            lambda: None,
            provider="ollama",
            model="test",
            concurrency=1,
            max_pending=1,
            request_id="rejected",
        )

    release.set()
    active_thread.join(2)
    pending_thread.join(2)
    assert not [*active_errors, *pending_errors]
    queue.shutdown()


def test_aging_prevents_background_starvation() -> None:
    """Let sufficiently old background work overtake newly queued work."""

    queue = LLMRequestQueue()
    release = threading.Event()
    started = threading.Event()
    order: list[str] = []

    def active() -> None:
        started.set()
        assert release.wait(2)

    active_thread, _, active_errors = _start_submission(
        queue,
        active,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        aging_seconds=0.1,
        request_id="aging-active",
    )
    assert started.wait(1)
    old_thread, _, old_errors = _start_submission(
        queue,
        lambda: order.append("old-background"),
        provider="ollama",
        model="test",
        category="background",
        concurrency=1,
        max_pending=4,
        aging_seconds=0.1,
        request_id="old-background",
    )
    _wait_until(lambda: queue.snapshot()["pending"] == 1)
    time.sleep(0.11)
    fresh_thread, _, fresh_errors = _start_submission(
        queue,
        lambda: order.append("fresh-interactive"),
        provider="ollama",
        model="test",
        category="interactive",
        concurrency=1,
        max_pending=4,
        aging_seconds=0.1,
        request_id="fresh-interactive",
    )
    _wait_until(lambda: queue.snapshot()["pending"] == 2)

    release.set()
    for thread in (active_thread, old_thread, fresh_thread):
        thread.join(2)
        assert not thread.is_alive()
    assert not [*active_errors, *old_errors, *fresh_errors]
    assert order == ["old-background", "fresh-interactive"]
    queue.shutdown()


def test_supersede_key_cancels_stale_pending_request() -> None:
    """Replace stale queued work without interrupting active provider work."""

    queue = LLMRequestQueue()
    release = threading.Event()
    started = threading.Event()
    order: list[str] = []

    def active() -> None:
        started.set()
        assert release.wait(2)

    active_thread, _, _ = _start_submission(
        queue,
        active,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="active",
    )
    assert started.wait(1)
    stale_thread, _, stale_errors = _start_submission(
        queue,
        lambda: order.append("stale"),
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="stale",
        supersede_key="preview:file.py",
    )
    _wait_until(lambda: queue.snapshot()["pending"] == 1)
    fresh_thread, _, fresh_errors = _start_submission(
        queue,
        lambda: order.append("fresh"),
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="fresh",
        supersede_key="preview:file.py",
    )
    _wait_until(lambda: bool(stale_errors))

    release.set()
    for thread in (active_thread, stale_thread, fresh_thread):
        thread.join(2)
    assert isinstance(stale_errors[0], LLMQueueCancelledError)
    assert not fresh_errors
    assert order == ["fresh"]
    queue.shutdown()


def test_pending_deadline_and_cancellation_are_observable() -> None:
    """Expire or cancel pending work without executing its callback."""

    queue = LLMRequestQueue()
    release = threading.Event()
    started = threading.Event()
    executed: list[str] = []

    def active() -> None:
        started.set()
        assert release.wait(2)

    active_thread, _, _ = _start_submission(
        queue,
        active,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="active",
    )
    assert started.wait(1)
    with pytest.raises(LLMQueueDeadlineExceeded):
        queue.submit(
            lambda: executed.append("expired"),
            provider="ollama",
            model="test",
            concurrency=1,
            max_pending=4,
            deadline_seconds=0.05,
            request_id="expired",
        )

    cancel_event = threading.Event()
    cancelled_thread, _, cancelled_errors = _start_submission(
        queue,
        lambda: executed.append("cancelled"),
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="cancelled",
        cancel_event=cancel_event,
    )
    _wait_until(lambda: queue.snapshot()["pending"] == 1)
    cancel_event.set()
    cancelled_thread.join(2)
    assert isinstance(cancelled_errors[0], LLMQueueCancelledError)
    assert not executed

    telemetry = queue.snapshot()["lanes"]["ollama"]
    assert telemetry["cancelled"] == 1
    assert telemetry["failed"] == 1
    release.set()
    active_thread.join(2)
    queue.shutdown()


def test_queue_preserves_contextvars_in_provider_worker() -> None:
    """Retain prompt-scoped telemetry context across the worker boundary."""

    queue = LLMRequestQueue()
    marker: ContextVar[str] = ContextVar("queue_test_marker", default="missing")
    marker.set("prompt-scope")

    result = queue.submit(
        marker.get,
        provider="ollama",
        model="test",
        request_id="context",
    )

    assert result == "prompt-scope"
    queue.shutdown()


def test_runtime_concurrency_reduction_limits_existing_lane() -> None:
    """Honor a lower configured limit even when extra workers already exist."""

    queue = LLMRequestQueue()
    assert queue.submit(
        lambda: "warm",
        provider="openai",
        model="test",
        concurrency=2,
        request_id="warm",
    ) == "warm"
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def work() -> None:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.04)
        with lock:
            active -= 1

    submissions = [
        _start_submission(
            queue,
            work,
            provider="openai",
            model="test",
            concurrency=1,
            max_pending=4,
            request_id=f"reduced-{index}",
        )
        for index in range(3)
    ]
    for thread, _results, errors in submissions:
        thread.join(2)
        assert not thread.is_alive()
        assert not errors

    assert maximum_active == 1
    assert queue.snapshot()["lanes"]["openai"]["concurrency"] == 1
    queue.shutdown()


def test_duplicate_active_request_id_is_rejected_without_losing_owner() -> None:
    """Keep cancellation and telemetry ownership unambiguous for request ids."""

    queue = LLMRequestQueue()
    started = threading.Event()
    release = threading.Event()

    def active_work() -> str:
        started.set()
        assert release.wait(2)
        return "first"

    owner_thread, owner_results, owner_errors = _start_submission(
        queue,
        active_work,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="duplicate-id",
    )
    assert started.wait(1)

    with pytest.raises(LLMQueueError, match="already active"):
        queue.submit(
            lambda: "second",
            provider="ollama",
            model="test",
            concurrency=1,
            max_pending=4,
            request_id="duplicate-id",
        )

    assert queue.cancel("duplicate-id", "cancel the original owner") is True
    release.set()
    owner_thread.join(2)

    assert not owner_thread.is_alive()
    assert owner_results == []
    assert len(owner_errors) == 1
    assert isinstance(owner_errors[0], LLMQueueCancelledError)
    queue.shutdown()


def test_cancelling_running_request_signals_cooperative_provider() -> None:
    """Propagate API cancellation into provider/tool work that can stop safely."""

    queue = LLMRequestQueue()
    cancel_event = threading.Event()
    started = threading.Event()
    worker_stopped = threading.Event()

    def cooperative_work() -> None:
        started.set()
        assert cancel_event.wait(2)
        worker_stopped.set()

    thread, results, errors = _start_submission(
        queue,
        cooperative_work,
        provider="ollama",
        model="test",
        request_id="cooperative-running",
        cancel_event=cancel_event,
    )
    assert started.wait(1)

    assert queue.cancel("cooperative-running", "User cancelled generation.") is True
    thread.join(2)
    assert worker_stopped.wait(1)

    assert results == []
    assert len(errors) == 1
    assert isinstance(errors[0], LLMQueueCancelledError)
    _wait_until(lambda: queue.snapshot()["running"] == 0)
    recent = queue.snapshot()["lanes"]["ollama"]["recent_requests"]
    assert recent[-1]["status"] == "cancelled"
    queue.shutdown()


def test_production_router_enforces_local_model_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serialize simultaneous Ollama calls through generate_llm_response."""

    reset_global_llm_request_queue()
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: {
            "llm_local_max_concurrent": 1,
            "llm_local_queue_max_pending": 4,
        },
    )
    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def fake_query(*_args: Any, **_kwargs: Any) -> str:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return "ok"

    monkeypatch.setattr(llm_router_service, "_query_ollama", fake_query)
    route = ModelProviderRoute("ollama", "test-model")
    results: dict[int, str] = {}

    def call(index: int) -> None:
        results[index] = llm_router_service.generate_llm_response(
            "test-model",
            f"request {index}",
            timeout=2,
            provider_route=route,
            queue_request_id=f"router-{index}",
        )

    threads = [threading.Thread(target=call, args=(index,)) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()

    assert results == {0: "ok", 1: "ok", 2: "ok"}
    assert maximum_active == 1
    reset_global_llm_request_queue()


def test_router_transfers_inference_metrics_from_queue_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return Ollama token telemetry to the synchronous submitting thread."""

    reset_global_llm_request_queue()
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: {"llm_local_max_concurrent": 1},
    )
    caller_thread = threading.get_ident()
    worker_threads: list[int] = []

    def fake_query(*_args: Any, **_kwargs: Any) -> str:
        worker_thread = threading.get_ident()
        worker_threads.append(worker_thread)
        llm_router_service._INFERENCE_METRICS_BY_THREAD[worker_thread] = {
            "model": "test-model",
            "input_tokens": 321,
            "output_tokens": 45,
        }
        return "ok"

    monkeypatch.setattr(llm_router_service, "_query_ollama", fake_query)
    response = llm_router_service.generate_llm_response(
        "test-model",
        "test prompt",
        timeout=2,
        provider_route=ModelProviderRoute("ollama", "test-model"),
    )
    metrics = llm_router_service.pop_last_inference_metrics()

    assert response == "ok"
    assert worker_threads and worker_threads[0] != caller_thread
    assert metrics["input_tokens"] == 321
    assert metrics["output_tokens"] == 45
    assert llm_router_service.pop_last_inference_metrics() == {}
    reset_global_llm_request_queue()


def test_router_does_not_reuse_metrics_from_an_earlier_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clear caller telemetry when a later provider call emits no metrics."""

    reset_global_llm_request_queue()
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: {"llm_local_max_concurrent": 1},
    )
    call_count = 0

    def fake_query(*_args: Any, **_kwargs: Any) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            llm_router_service._INFERENCE_METRICS_BY_THREAD[
                threading.get_ident()
            ] = {"input_tokens": 100, "output_tokens": 10}
        return f"response-{call_count}"

    monkeypatch.setattr(llm_router_service, "_query_ollama", fake_query)
    route = ModelProviderRoute("ollama", "test-model")

    assert llm_router_service.generate_llm_response(
        "test-model",
        "first prompt",
        timeout=2,
        provider_route=route,
    ) == "response-1"
    assert llm_router_service.generate_llm_response(
        "test-model",
        "second prompt",
        timeout=2,
        provider_route=route,
    ) == "response-2"

    assert llm_router_service.pop_last_inference_metrics() == {}
    reset_global_llm_request_queue()


def test_router_preserves_failed_provider_metrics_for_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transfer worker telemetry even when provider generation raises."""

    reset_global_llm_request_queue()
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: {"llm_local_max_concurrent": 1},
    )

    def failing_query(*_args: Any, **_kwargs: Any) -> str:
        llm_router_service._INFERENCE_METRICS_BY_THREAD[
            threading.get_ident()
        ] = {
            "input_tokens": 77,
            "output_tokens": 0,
            "timed_out": True,
        }
        raise TimeoutError("simulated provider timeout")

    monkeypatch.setattr(llm_router_service, "_query_ollama", failing_query)

    with pytest.raises(TimeoutError, match="simulated provider timeout"):
        llm_router_service.generate_llm_response(
            "test-model",
            "failing prompt",
            timeout=2,
            provider_route=ModelProviderRoute("ollama", "test-model"),
        )

    assert llm_router_service.pop_last_inference_metrics() == {
        "input_tokens": 77,
        "output_tokens": 0,
        "timed_out": True,
    }
    reset_global_llm_request_queue()


def test_public_api_reports_and_cancels_queued_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose safe queue operations through the supported headless API."""

    from tech_connector.api import (
        TechConnectorHeadlessAPI,
        cancel_llm_request,
        llm_queue_status,
    )

    reset_global_llm_request_queue()
    queue = global_llm_request_queue()
    release = threading.Event()
    started = threading.Event()

    def active() -> None:
        started.set()
        assert release.wait(2)

    active_thread, _, active_errors = _start_submission(
        queue,
        active,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="public-active",
    )
    assert started.wait(1)
    pending_thread, _, pending_errors = _start_submission(
        queue,
        lambda: None,
        provider="ollama",
        model="test",
        concurrency=1,
        max_pending=4,
        request_id="public-pending",
    )
    _wait_until(lambda: llm_queue_status()["pending"] == 1)

    monkeypatch.setenv("TECH_CONNECTOR_DEV_LICENSE_BYPASS", "1")
    api = TechConnectorHeadlessAPI(settings={}, require_entitlement=False)
    feature = api.features.get("llm.queue")
    assert feature["operations"] == ("status", "cancel")
    assert api.llm_queue_status()["pending"] == 1
    assert cancel_llm_request("public-pending", "Test cancellation.") is True

    pending_thread.join(2)
    assert isinstance(pending_errors[0], LLMQueueCancelledError)
    release.set()
    active_thread.join(2)
    assert not active_errors
    reset_global_llm_request_queue()


def test_settings_define_safe_queue_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Keep bounded scheduling enabled for new and existing installations."""

    from tech_connector.services import settings_service

    monkeypatch.setattr(settings_service, "SETTINGS_PATH", tmp_path / "missing.json")
    settings = settings_service.load_settings()

    assert settings["llm_local_max_concurrent"] == 1
    assert settings["llm_cloud_max_concurrent"] == 4
    assert settings["llm_local_queue_max_pending"] == 32
    assert settings["llm_cloud_queue_max_pending"] == 64
    assert settings["llm_queue_aging_seconds"] == 15.0


def test_queue_lane_options_recover_from_invalid_user_settings() -> None:
    """Normalize hand-edited queue settings instead of breaking inference."""

    local = llm_queue_lane_options(
        {
            "llm_local_max_concurrent": "invalid",
            "llm_local_queue_max_pending": 0,
            "llm_queue_aging_seconds": None,
        },
        "ollama",
    )
    cloud = llm_queue_lane_options({}, "openai")

    assert local == {
        "concurrency": 1,
        "max_pending": 1,
        "aging_seconds": 15.0,
    }
    assert cloud == {
        "concurrency": 4,
        "max_pending": 64,
        "aging_seconds": 15.0,
    }


def test_ollama_model_warm_uses_background_queue_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serialize GPU-affecting warm operations with local inference."""

    from tech_connector.services import ollama_service

    class Response:
        """Minimal context-managed HTTP response."""

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: Any) -> bool:
            return False

        def read(self) -> bytes:
            return b"{}"

    class Opener:
        """Minimal successful URL opener."""

        def open(self, *_args: Any, **_kwargs: Any) -> Response:
            return Response()

    reset_global_llm_request_queue()
    monkeypatch.setattr(ollama_service, "ensure_ollama_server", lambda: (True, "ok"))
    monkeypatch.setattr(ollama_service.urllib.request, "build_opener", lambda *_args: Opener())
    monkeypatch.setattr(
        "tech_connector.services.settings_service.load_settings",
        lambda: {"llm_local_max_concurrent": 1},
    )

    assert ollama_service.warm_ollama_model("test-model", keep_alive="1m") is True
    recent = global_llm_request_queue().snapshot()["lanes"]["ollama"][
        "recent_requests"
    ]
    assert recent[-1]["category"] == "background"
    assert recent[-1]["model"] == "test-model"
    reset_global_llm_request_queue()
