import json
from pathlib import Path

import pytest

from services.application_service import ApplicationService


def test_read_write_file(tmp_path):
    sample = tmp_path / "sample.txt"
    service = ApplicationService(
        read_file_fn=lambda path: (True, Path(path).read_text(encoding="utf-8")),
        save_file_fn=lambda path, content: (True, Path(path).write_text(content, encoding="utf-8")) or (True, str(path)),
    )

    ok, message = service.save_file(str(sample), "hello world")
    assert ok
    assert sample.read_text(encoding="utf-8") == "hello world"

    ok, contents = service.read_file(str(sample))
    assert ok
    assert contents == "hello world"


def test_build_index_injects_custom_worker():
    created = {}

    class DummyIndexWorker:
        def __init__(self, roots):
            created["roots"] = roots

    service = ApplicationService(index_worker_cls=DummyIndexWorker)
    worker = service.build_index(ensure_components=False)

    assert isinstance(worker, DummyIndexWorker)
    assert created["roots"] == service.all_roots()


def test_start_mcphost_injects_start_function():
    called = {}

    def fake_start_mcphost(bridge, settings, model, config, use_pty):
        called["bridge"] = bridge
        called["settings"] = settings
        called["model"] = model
        called["config"] = config
        called["use_pty"] = use_pty
        return True, "cmd", ""

    service = ApplicationService(start_mcphost_fn=fake_start_mcphost)
    ok, cmd_display, error = service.start_mcphost("m", "c", True)

    assert ok
    assert cmd_display == "cmd"
    assert error == ""
    assert called["model"] == "m"
    assert called["config"] == "c"
    assert called["use_pty"] is True


def test_live_source_setting_persists_through_service():
    saved = {}
    service = ApplicationService(
        settings={"enable_live_sources": False},
        save_settings_fn=lambda data: saved.update(data),
    )

    assert service.live_sources_enabled() is False

    service.set_live_sources_enabled(True)

    assert service.live_sources_enabled() is True
    assert saved["enable_live_sources"] is True


def test_prepare_prompt_applies_source_policy():
    service = ApplicationService(settings={"enable_live_sources": False})

    prompt = service.prepare_prompt("use only what is here")

    assert prompt.startswith("Source mode: LOCAL ONLY.")
    assert "use only what is here" in prompt
