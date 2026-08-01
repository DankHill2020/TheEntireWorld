"""Background UI & AI Model Pre-loader Worker for Tech Connector Splash Screen.

Pre-warms AI Models, RequestEngine, 3D Mesh Viewport Shaders, PySide6 System Font Database,
and DCC Bridge Connection Pools in parallel while the 10-second MP4 Splash Screen is playing.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


class SplashPreloadWorker(QThread):
    """Background thread worker to pre-load models and UI components during splash screen video."""

    stage_progress = Signal(int, str)  # (percent, stage_description)
    preload_finished = Signal(dict)  # (preloaded_components)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preloaded_cache: dict[str, Any] = {}

    def run(self):
        """Execute parallel pre-loading tasks during 10-second splash video playback."""
        stages: list[tuple[str, Callable[[], Any]]] = [
            ("Enumerating 100% System Fonts & Typography Engine", self._preload_font_database),
            ("Pre-warming RequestEngine & AI Model Pipelines", self._preload_ai_model_pipelines),
            ("Pre-initializing 3D Mesh Viewport & Shader Buffers", self._preload_3d_mesh_painter),
            ("Pre-connecting DCC Bridge Protocols (UE5 / Maya / Blender)", self._preload_dcc_bridges),
            ("Pre-caching Tutorial Mode & Educational Knowledge Base", self._preload_tutorial_service),
        ]

        total_stages = len(stages)
        for idx, (stage_name, func) in enumerate(stages, 1):
            percent = int((idx / float(total_stages)) * 100)
            self.stage_progress.emit(percent, stage_name)
            try:
                res = func()
                self.preloaded_cache[stage_name] = res
            except Exception as err:
                print(f"[SplashPreloader] Warning in stage '{stage_name}': {err}")

            time.sleep(0.1)  # Smooth progress bar cadence during 10s video

        self.preload_finished.emit(self.preloaded_cache)

    def _preload_font_database(self) -> int:
        from tech_connector.services.text_warp_typography_service import get_all_system_fonts
        fonts = get_all_system_fonts()
        return len(fonts)

    def _preload_ai_model_pipelines(self) -> str:
        from tech_connector.engine.request_engine import RequestEngine
        from tech_connector.services.model_provider_service import (
            provider_for_model,
            should_use_local_runtime,
        )
        from tech_connector.services.ollama_resource_service import ollama_keep_alive
        from tech_connector.services.ollama_service import (
            normalize_ollama_model_name,
            semantic_alignment_model,
            warm_ollama_model,
        )
        from tech_connector.services.settings_service import load_settings

        RequestEngine()
        settings = load_settings()
        if not bool(settings.get("ollama_preload_on_startup", False)):
            return "RequestEngine_Warmed; Ollama lazy-start enabled"
        configured_preloads = [
            normalize_ollama_model_name(model)
            for model in list(settings.get("ollama_preload_models") or [])
            if str(model or "").strip()
        ]
        selected_model = normalize_ollama_model_name(
            settings.get("model") or semantic_alignment_model()
        )
        candidates = list(dict.fromkeys(configured_preloads + [selected_model]))
        keep_alive = ollama_keep_alive(settings)
        warmed = []
        for model in candidates[:1]:
            if (
                model
                and provider_for_model(model) == "ollama"
                and should_use_local_runtime(model, settings)
                and warm_ollama_model(model, keep_alive)
            ):
                warmed.append(model)
        if warmed:
            return "RequestEngine_Warmed; Ollama resident: " + ", ".join(warmed)
        return "RequestEngine_Warmed"

    def _preload_3d_mesh_painter(self) -> str:
        from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel
        mesh = FBXMeshModel("Preload_Sphere")
        return "3D_Mesh_Painter_Ready"

    def _preload_dcc_bridges(self) -> str:
        from tech_connector.services.dcc.dcc_bridge_setup import auto_reconnect_dcc_bridges
        auto_reconnect_dcc_bridges()
        return "DCC_Bridges_Warmed"

    def _preload_tutorial_service(self) -> str:
        from tech_connector.services.tutorial_mode_service import TutorialModeService
        svc = TutorialModeService()
        return "Tutorial_Service_Ready"
