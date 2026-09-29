from __future__ import annotations

import threading

import pytest

from tech_connector.game_engine.integration import pipeline_operation_runtime_service as runtime


def test_pipeline_operation_emits_correlated_lifecycle_without_changing_result(monkeypatch) -> None:
    events = []
    calls = []
    monkeypatch.setattr(
        runtime,
        "_execute_pipeline_operation_once",
        lambda host, operation, callable_name, params, **options: (
            calls.append((host, operation, callable_name, params, options))
            or {"created": ["asset"]}
        ),
    )

    result = runtime.execute_pipeline_operation(
        "Maya", "mesh.create", "studio.create_mesh", {"name": "Hero"},
        session_port=7002, timeout_seconds=42, execution_id="demo-operation",
        progress_callback=events.append,
    )

    assert result == {"created": ["asset"]}
    assert [event["event"] for event in events] == ["queued", "dispatching", "completed"]
    assert {event["execution_id"] for event in events} == {"demo-operation"}
    assert all(event["schema"] == runtime.PIPELINE_OPERATION_EVENT_SCHEMA for event in events)
    assert calls == [
        ("maya", "mesh.create", "studio.create_mesh", {"name": "Hero"},
         {"session_port": 7002, "timeout_seconds": 42.0})
    ]


def test_pipeline_operation_cancellation_prevents_host_mutation(monkeypatch) -> None:
    cancel = threading.Event()
    cancel.set()
    called = []
    events = []
    monkeypatch.setattr(
        runtime, "_execute_pipeline_operation_once", lambda *_args, **_kwargs: called.append(True),
    )

    with pytest.raises(runtime.PipelineOperationCancelled, match="before host dispatch"):
        runtime.execute_pipeline_operation(
            "maya", "mesh.delete", "studio.delete_mesh", cancel_token=cancel,
            progress_callback=events.append,
        )

    assert called == []
    assert [event["event"] for event in events] == ["queued", "cancelled"]


def test_pipeline_operation_retries_only_explicitly_safe_transient_failures(monkeypatch) -> None:
    attempts = []
    events = []

    def flaky(*_args, **_kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("connection reset by host")
        return {"ok": True}

    monkeypatch.setattr(runtime, "_execute_pipeline_operation_once", flaky)

    result = runtime.execute_pipeline_operation(
        "blender", "scene.list", "studio.list_scene",
        retry_attempts=2, retry_safe=True, retry_backoff_seconds=0,
        progress_callback=events.append,
    )

    assert result == {"ok": True}
    assert len(attempts) == 2
    assert [event["event"] for event in events] == [
        "queued", "dispatching", "retrying", "dispatching", "completed",
    ]


def test_pipeline_operation_never_retries_mutation_without_safe_opt_in(monkeypatch) -> None:
    attempts = []

    def unavailable(*_args, **_kwargs):
        attempts.append(True)
        raise RuntimeError("connection refused")

    monkeypatch.setattr(runtime, "_execute_pipeline_operation_once", unavailable)

    with pytest.raises(RuntimeError, match="connection refused"):
        runtime.execute_pipeline_operation(
            "maya", "mesh.delete", "studio.delete_mesh", retry_attempts=3,
        )

    assert len(attempts) == 1
