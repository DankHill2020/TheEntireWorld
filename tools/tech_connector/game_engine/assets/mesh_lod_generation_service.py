"""Character-aware static and skinned mesh LOD generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any

from tech_connector.game_engine.scene.federated_scene_service import source_file_fingerprint
from tech_connector.game_engine.scene.native_fbx_service import _stop_subprocess, find_blender_executable


LOD_SOURCE_EXTENSIONS = frozenset({".abc", ".fbx", ".glb", ".gltf", ".obj", ".stl", ".usd", ".usda", ".usdc", ".usdz"})


@dataclass(frozen=True)
class CharacterMeshLodLevel:
    name: str
    triangle_ratio: float
    screen_error_px: float = 1.0
    source_path: str = ""


@dataclass(frozen=True)
class CharacterMeshLodRequest:
    source_path: str
    output_dir: str
    levels: tuple[CharacterMeshLodLevel, ...] = (
        CharacterMeshLodLevel("LOD0", 1.0, 0.5), CharacterMeshLodLevel("LOD1", 0.5, 1.0),
        CharacterMeshLodLevel("LOD2", 0.25, 2.0), CharacterMeshLodLevel("LOD3", 0.125, 4.0),
    )
    include_animation: bool = False
    preserve_skinning: bool = True
    source_fingerprint: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_fingerprint:
            object.__setattr__(self, "source_fingerprint", source_file_fingerprint(self.source_path))

    def validate(self) -> list[str]:
        errors: list[str] = []
        source = Path(self.source_path).expanduser()
        if not source.is_file(): errors.append(f"LOD source is missing: {source}")
        if source.suffix.casefold() not in LOD_SOURCE_EXTENSIONS: errors.append(f"Unsupported LOD source format: {source.suffix or '<none>'}")
        ratios = [float(item.triangle_ratio) for item in self.levels]
        if not ratios or any(value <= 0.0 or value > 1.0 for value in ratios): errors.append("LOD triangle ratios must be greater than zero and at most one.")
        if ratios != sorted(ratios, reverse=True): errors.append("LOD levels must be ordered from strongest to weakest triangle ratio.")
        names = [item.name for item in self.levels]
        if len(names) != len(set(names)) or any(not value for value in names): errors.append("LOD names must be non-empty and unique.")
        for item in self.levels:
            if item.source_path:
                custom = Path(item.source_path).expanduser()
                if not custom.is_file(): errors.append(f"Custom LOD source is missing: {custom}")
                elif custom.suffix.casefold() not in LOD_SOURCE_EXTENSIONS: errors.append(f"Unsupported custom LOD source format: {custom.suffix}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "tech_connector.character_mesh_lod_request.v1",
                "source_path": str(Path(self.source_path).expanduser().resolve()),
                "output_dir": str(Path(self.output_dir).expanduser().resolve()),
                "levels": [asdict(item) for item in self.levels], "include_animation": self.include_animation,
                "preserve_skinning": self.preserve_skinning, "source_fingerprint": dict(self.source_fingerprint)}


def generate_character_mesh_lods(
    request: CharacterMeshLodRequest, *, timeout: float = 300.0,
    cancel_event: threading.Event | None = None, blender_executable: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    errors = request.validate()
    if errors: raise ValueError("Invalid character Mesh LOD request: " + "; ".join(errors))
    if cancel_event is not None and cancel_event.is_set(): raise RuntimeError("Mesh LOD generation canceled.")
    blender = Path(blender_executable).resolve() if blender_executable else find_blender_executable()
    worker = Path(__file__).with_name("blender_character_lod_worker.py")
    if blender is None or not blender.is_file(): raise RuntimeError("No isolated Blender Mesh LOD backend is available.")
    with tempfile.TemporaryDirectory(prefix="tc_character_lod_") as directory:
        temp = Path(directory); request_path = temp / "request.json"; result_path = temp / "result.json"
        request_path.write_text(json.dumps(request.to_dict(), separators=(",", ":")), encoding="utf-8")
        process = subprocess.Popen(
            [str(blender), "--background", "--factory-startup", "--python", str(worker), "--", "--request", str(request_path), "--result", str(result_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        started = time.perf_counter(); deadline = time.monotonic() + max(0.1, float(timeout)); stdout = stderr = ""
        while True:
            if cancel_event is not None and cancel_event.is_set(): _stop_subprocess(process); raise RuntimeError("Mesh LOD generation canceled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0.0: _stop_subprocess(process); raise TimeoutError("Mesh LOD generation timed out.")
            try: stdout, stderr = process.communicate(timeout=min(0.25, remaining)); break
            except subprocess.TimeoutExpired: continue
        if process.returncode or not result_path.is_file():
            raise RuntimeError("Mesh LOD generation failed:\n" + (stderr or stdout or "No diagnostics")[-6000:])
        result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("schema") != "tech_connector.character_mesh_lod_result.v1": raise ValueError("Unsupported Mesh LOD result schema.")
    result["elapsed_ms"] = (time.perf_counter() - started) * 1000.0
    result["source_fingerprint"] = dict(request.source_fingerprint)
    return result


__all__ = ["CharacterMeshLodLevel", "CharacterMeshLodRequest", "generate_character_mesh_lods"]
