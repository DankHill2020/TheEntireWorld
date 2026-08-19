"""Regression coverage for restored viewer camera and local-command behavior."""

from __future__ import annotations

import threading
import time
from typing import Any

from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.integration import viewer_commands
from tech_connector.game_engine.integration.active_viewer_command_service import (
    active_viewer,
)
from tech_connector.ui.dcc_viewer.mesh_painter.widget import (
    DccCameraPossessionWorker,
    ThreeDMeshPainterViewport,
)


def test_camera_authority_and_possession_helpers_are_class_methods() -> None:
    """Camera adapters should remain callable after viewport decomposition.

    :return: None.
    """

    payload = {
        "eye": [1.0, 2.0, 3.0],
        "target": [0.0, 1.0, 0.0],
        "up_target": [0.0, 2.0, 0.0],
        "fov_degrees": 52.0,
        "aspect_ratio": 2.39,
        "near_clip": 0.1,
        "far_clip": 10_000.0,
    }

    maya = ThreeDMeshPainterViewport._maya_possess_camera_code(None, payload)
    houdini = ThreeDMeshPainterViewport._houdini_possess_camera_code(None, payload)
    unity = ThreeDMeshPainterViewport._unity_possess_camera_code(None, payload)
    readback = ThreeDMeshPainterViewport._maya_read_camera_authority_code(
        None,
        "shotCamera",
    )

    assert "deviceAspectRatio" in maya
    assert "sceneViewers" in houdini
    assert "lastActiveSceneView" in unity
    assert "filmFit" in readback


def test_camera_worker_executes_independent_sessions_concurrently() -> None:
    """Independent DCC sessions should not serialize camera possession.

    :return: None.
    """

    rendezvous = threading.Barrier(2, timeout=1.0)

    class FakeBridge:
        """Minimal concurrent bridge test double."""

        def execute(self, code: str, timeout: float = 5.0) -> tuple[bool, str]:
            """Wait for both sessions and return the submitted code.

            :param code: Host code to execute.
            :param timeout: Requested execution timeout.
            :return: Successful bridge result.
            """

            del timeout
            rendezvous.wait()
            return True, code

    requests = [
        {"provider": "maya:7001", "code": "first"},
        {"provider": "maya:7002", "code": "second"},
    ]
    emitted: list[dict[str, dict[str, Any]]] = []
    worker = DccCameraPossessionWorker(
        requests,
        bridge_factory=lambda _provider: FakeBridge(),
    )
    worker.finished.connect(emitted.append)

    worker.run()

    assert set(emitted[0]) == {"maya:7001", "maya:7002"}
    assert all(result["ok"] for result in emitted[0].values())


def test_constructed_viewer_executes_character_simulation_and_world_commands() -> None:
    """A constructed embedded viewer should immediately own local commands.

    :return: None.
    """

    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        assert active_viewer() is viewer

        character = viewer_commands.execute_active(
            "characters.create",
            character_id="guide",
            display_name="Guide",
            force_local=True,
        )
        cloth = viewer_commands.execute_active(
            "simulation.create_cloth",
            material="silk",
            columns=4,
            rows=4,
            force_local=True,
        )
        experience = viewer_commands.execute_active(
            "gameplay.configure_experience",
            profile_id="learning_space",
            game_types=["educational", "sandbox"],
            learning_objectives=[
                {
                    "id": "observe",
                    "description": "Observe simulation behavior",
                    "evidence": ["prediction"],
                }
            ],
            force_local=True,
        )

        assert character["executed"]
        assert cloth["executed"]
        assert experience["executed"]
        assert viewer.simulation_world is not None
        assert len(viewer.simulation_world.particles) == 16
    finally:
        viewer.close()
        app.processEvents()


def test_effect_bake_starts_and_installs_cache() -> None:
    """Local effect baking should return immediately and install its cache.

    :return: None.
    """

    app = QApplication.instance() or QApplication([])
    viewer = ThreeDMeshPainterViewport()
    try:
        created = viewer_commands.execute_active(
            "simulation.create_effect",
            preset="sparks",
            quality="low",
            force_local=True,
        )
        started = viewer_commands.execute_active(
            "simulation.bake_effect",
            start_frame=1,
            end_frame=12,
            frame_rate=24.0,
            force_local=True,
        )
        deadline = time.perf_counter() + 5.0
        while viewer._effect_bake_thread is not None and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()

        assert created["executed"]
        assert started["executed"]
        assert started["started"]
        assert viewer.simulation_cache is not None
        assert len(viewer.simulation_cache.frames) == 12
    finally:
        viewer.close()
        app.processEvents()

