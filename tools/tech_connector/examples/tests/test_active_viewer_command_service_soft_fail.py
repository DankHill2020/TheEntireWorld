from __future__ import annotations


def test_execute_active_viewer_command_returns_not_executed_without_viewer() -> None:
    from tech_connector.services.dcc import active_viewer_command_service as service

    service._active_viewer = None
    service._active_viewers = []
    result = service.execute_active_viewer_command("modeling.extrude_faces", faces=[3], distance=0.5)

    assert result["executed"] is False
    assert result["status"] == "unavailable"
    assert "Open The Entire Scene Viewer" in str(result.get("message", ""))


def test_execute_active_viewer_command_returns_not_executed_without_adaptive_executor() -> None:
    from tech_connector.services.dcc import active_viewer_command_service as service

    class ViewerWithoutExecutor:
        pass

    service._active_viewer = None
    service._active_viewers = []
    viewer = ViewerWithoutExecutor()
    service.register_active_viewer(viewer)
    try:
        result = service.execute_active_viewer_command("modeling.extrude_faces", faces=[3], distance=0.5)
    finally:
        service.unregister_active_viewer(viewer)

    assert result["executed"] is False
    assert result["status"] == "unsupported"
    assert "does not expose adaptive command execution" in str(result.get("message", ""))


def test_execute_active_viewer_command_returns_error_payload_on_adapter_exception() -> None:
    from tech_connector.services.dcc import active_viewer_command_service as service

    class ViewerAdapterRaises:
        def execute_adaptive_scene_command(self, command: str, payload: dict) -> dict:
            raise RuntimeError("viewer adapter failed")

    service._active_viewer = None
    service._active_viewers = []
    viewer = ViewerAdapterRaises()
    service.register_active_viewer(viewer)
    try:
        result = service.execute_active_viewer_command("modeling.extrude_faces", faces=[3], distance=0.5)
    finally:
        service.unregister_active_viewer(viewer)

    assert result["executed"] is False
    assert result["status"] == "error"
    assert "viewer adapter failed" in str(result.get("message", ""))
    assert result["command"] == "modeling.extrude_faces"
