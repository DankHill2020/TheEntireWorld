"""Cancellable isolated generation of portable mesh LOD assets."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any, Sequence

from tech_connector.game_engine.scene.federated_scene_service import source_file_fingerprint
from tech_connector.game_engine.scene.native_fbx_service import _stop_subprocess, find_blender_executable


MESH_LOD_SCHEMA = "tech_connector.mesh_lod_request.v1"
LOD_SOURCE_EXTENSIONS = frozenset({".abc", ".fbx", ".glb", ".gltf", ".obj", ".stl", ".usd", ".usda", ".usdc", ".usdz"})


@dataclass(frozen=True)
class MeshLodLevel:
    name: str
    triangle_ratio: float
    screen_error_px: float = 1.0


@dataclass(frozen=True)
class MeshLodRequest:
    source_path: str
    output_dir: str
    levels: tuple[MeshLodLevel, ...] = (
        MeshLodLevel("LOD0", 1.0, 0.5),
        MeshLodLevel("LOD1", 0.5, 1.0),
        MeshLodLevel("LOD2", 0.2, 2.0),
        MeshLodLevel("LOD3", 0.05, 4.0),
    )
    include_animation: bool = False
    source_fingerprint: dict[str, Any] = field(default_factory=dict)
    schema: str = MESH_LOD_SCHEMA

    def __post_init__(self) -> None:
        if not self.source_fingerprint:
            object.__setattr__(self, "source_fingerprint", source_file_fingerprint(self.source_path))

    def validate(self) -> list[str]:
        errors = []
        source = Path(self.source_path).expanduser()
        if not source.is_file():
            errors.append(f"LOD source is missing: {source}")
        if source.suffix.lower() not in LOD_SOURCE_EXTENSIONS:
            errors.append(f"Unsupported LOD source format: {source.suffix or '<none>'}")
        if not self.levels:
            errors.append("At least one LOD level is required.")
        names = [level.name for level in self.levels]
        if len(names) != len(set(names)) or any(not name for name in names):
            errors.append("LOD level names must be non-empty and unique.")
        ratios = [float(level.triangle_ratio) for level in self.levels]
        if any(ratio <= 0.0 or ratio > 1.0 for ratio in ratios):
            errors.append("LOD triangle ratios must be greater than zero and at most one.")
        if ratios != sorted(ratios, reverse=True):
            errors.append("LOD levels must be ordered from strongest to weakest triangle ratio.")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_path": str(Path(self.source_path).expanduser().resolve()),
            "output_dir": str(Path(self.output_dir).expanduser().resolve()),
            "levels": [asdict(level) for level in self.levels],
            "include_animation": bool(self.include_animation),
            "source_fingerprint": dict(self.source_fingerprint),
        }


def generate_mesh_lods(
    request: MeshLodRequest,
    *,
    timeout: float = 300.0,
    cancel_event: threading.Event | None = None,
    blender_executable: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    errors = request.validate()
    if errors:
        raise ValueError("Invalid mesh LOD request: " + "; ".join(errors))
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("Mesh LOD generation canceled.")
    blender = Path(blender_executable).resolve() if blender_executable else find_blender_executable()
    worker = Path(__file__).resolve().parents[1] / "integration" / "blender_mesh_lod_generate.py"
    if blender is None or not blender.is_file() or not worker.is_file():
        raise RuntimeError("No isolated Blender mesh LOD backend is available.")
    with tempfile.TemporaryDirectory(prefix="tech_connector_lod_") as directory:
        temporary = Path(directory)
        request_path = temporary / "request.json"
        result_path = temporary / "result.json"
        request_path.write_text(json.dumps(request.to_dict(), separators=(",", ":")), encoding="utf-8")
        command = [str(blender), "--background", "--factory-startup", "--python", str(worker), "--", "--request", str(request_path), "--result", str(result_path)]
        started = time.perf_counter()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + max(0.1, float(timeout))
        stdout = stderr = ""
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _stop_subprocess(process)
                raise RuntimeError("Mesh LOD generation canceled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                _stop_subprocess(process)
                raise TimeoutError(f"Mesh LOD generation exceeded {float(timeout):g} seconds.")
            try:
                stdout, stderr = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0 or not result_path.is_file():
            raise RuntimeError("Mesh LOD generation failed:\n" + (stderr or stdout or "No Blender diagnostics.")[-6000:])
        result = json.loads(result_path.read_text(encoding="utf-8"))
    if str(result.get("schema") or "") != "tech_connector.mesh_lod_result.v1":
        raise ValueError("The mesh LOD backend returned an unsupported result schema.")
    result["elapsed_ms"] = (time.perf_counter() - started) * 1000.0
    result["source_fingerprint"] = dict(request.source_fingerprint)
    return result


__all__ = ["MESH_LOD_SCHEMA", "MeshLodLevel", "MeshLodRequest", "generate_mesh_lods"]
