"""Substance Painter project operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def create_project(mesh_path: str, template_name: str = "PBR - Metallic Roughness", directory: str = "") -> dict[str, Any]:
    import substance_painter.project as project

    mesh = Path(mesh_path).expanduser().resolve()
    if not mesh.is_file():
        raise FileNotFoundError(f"Project mesh does not exist: {mesh}")
    settings = project.ProjectSettings(str(mesh))
    project.create(settings)
    result = {"ok": True, "mesh_path": str(mesh), "template_name": str(template_name)}
    if directory:
        target = Path(directory).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        result["directory"] = str(target)
    return result


__all__ = ["create_project"]
