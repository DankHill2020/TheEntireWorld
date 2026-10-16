"""Structured local-generation reliability tests."""

from __future__ import annotations

import json

from tech_connector.services import llm_router_service


class _StreamResponse:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._lines = iter(
            [json.dumps(event).encode("utf-8") + b"\n" for event in events]
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def readline(self) -> bytes:
        return next(self._lines, b"")


def test_structured_ollama_generation_disables_separate_thinking_by_default(
    monkeypatch,
) -> None:
    """Reserve the generation budget for the JSON response body."""

    captured: dict[str, object] = {}

    class _Opener:
        def open(self, request, **_kwargs):
            captured.update(json.loads(request.data.decode("utf-8")))
            return _StreamResponse(
                [
                    {
                        "response": '{"assignments":[]}',
                        "done": True,
                        "prompt_eval_count": 10,
                        "eval_count": 5,
                    }
                ]
            )

    monkeypatch.setattr(
        "tech_connector.services.ollama_service.ensure_ollama_server",
        lambda: (True, "ready"),
    )
    monkeypatch.setattr(
        "tech_connector.services.ollama_service.resolve_ollama_model_name",
        lambda model: model,
    )
    monkeypatch.setattr(
        llm_router_service.urllib.request,
        "build_opener",
        lambda *_args: _Opener(),
    )

    result = llm_router_service._query_ollama(
        "qwen3.5:4b",
        "Return assignments.",
        response_format="json",
        options={"num_predict": 64},
        timeout=30,
    )

    assert result == '{"assignments":[]}'
    assert captured["think"] is False
    assert captured["format"] == "json"


def test_unstructured_ollama_generation_does_not_force_thinking_policy(
    monkeypatch,
) -> None:
    """Leave ordinary chat/reasoning behavior under the model's own default."""

    captured: dict[str, object] = {}

    class _Opener:
        def open(self, request, **_kwargs):
            captured.update(json.loads(request.data.decode("utf-8")))
            return _StreamResponse([{"response": "done", "done": True}])

    monkeypatch.setattr(
        "tech_connector.services.ollama_service.ensure_ollama_server",
        lambda: (True, "ready"),
    )
    monkeypatch.setattr(
        "tech_connector.services.ollama_service.resolve_ollama_model_name",
        lambda model: model,
    )
    monkeypatch.setattr(
        llm_router_service.urllib.request,
        "build_opener",
        lambda *_args: _Opener(),
    )

    assert llm_router_service._query_ollama(
        "qwen3.5:4b", "Explain this code.", timeout=30
    ) == "done"
    assert "think" not in captured
