"""Tests for raw WebSocket bridge execution and HTTP fallback mechanisms."""

import json
from typing import Any
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.bridges.dcc_websocket_bridge import execute_via_websocket_if_enabled, DccWebSocketClient


@pytest.fixture
def temp_settings():
    backup = None
    if SETTINGS_PATH.exists():
        try:
            backup = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    yield
    if backup is not None:
        try:
            SETTINGS_PATH.write_text(json.dumps(backup, indent=2), encoding="utf-8")
        except Exception:
            pass


class MockFailedWSClient:
    """Mock WebSocket client that always fails to connect."""
    def __init__(self, *args, **kwargs):
        pass
    def connect(self, *args, **kwargs):
        return False
    def close(self):
        pass


def test_websocket_disabled_fallback(temp_settings):
    """Verify that if WebSockets are disabled in settings, fallback executes immediately."""
    settings = load_settings()
    settings["use_websocket_bridge"] = False
    save_settings(settings)

    fallback_called = False
    def mock_fallback():
        nonlocal fallback_called
        fallback_called = True
        return {"status": "succeeded", "provider": "http"}

    res = execute_via_websocket_if_enabled(
        host="127.0.0.1",
        port=8082,
        action_dict={"action": "test"},
        fallback_fn=mock_fallback
    )

    assert res["provider"] == "http"
    assert fallback_called is True


def test_websocket_connection_failure_fallback(temp_settings, monkeypatch):
    """Verify that if WebSocket connection fails, fallback executes immediately."""
    settings = load_settings()
    settings["use_websocket_bridge"] = True
    save_settings(settings)

    # Patch DccWebSocketClient with MockFailedWSClient
    import tech_connector.bridges.dcc_websocket_bridge
    monkeypatch.setattr(tech_connector.bridges.dcc_websocket_bridge, "DccWebSocketClient", MockFailedWSClient)

    fallback_called = False
    def mock_fallback():
        nonlocal fallback_called
        fallback_called = True
        return {"status": "succeeded", "provider": "http"}

    res = execute_via_websocket_if_enabled(
        host="127.0.0.1",
        port=8082,
        action_dict={"action": "test"},
        fallback_fn=mock_fallback
    )

    assert res["provider"] == "http"
    assert fallback_called is True
