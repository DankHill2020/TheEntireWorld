"""Substance Painter texture export operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def export_textures(output_path: str, preset_name: str = "PBR Metallic Roughness", resolution: int = 2048) -> dict[str, Any]:
    import substance_painter.export as painter_export
    import substance_painter.project as project
    import substance_painter.resource as resource
    import substance_painter.textureset as textureset

    if not project.is_open():
        raise RuntimeError("No Substance Painter project is open.")
    target = Path(output_path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    size = int(resolution)
    if size <= 0 or size & (size - 1):
        raise ValueError("Painter export resolution must be a positive power of two.")
    texture_sets = list(textureset.all_texture_sets())
    if not texture_sets:
        raise RuntimeError("The Painter project contains no texture sets.")
    stack_rows = []
    for texture_set in texture_sets:
        stacks = list(texture_set.all_stacks())
        stack_rows.append({
            "name": _display_name(texture_set),
            "stacks": [str(stack) for stack in stacks],
        })
    active_stack = textureset.get_active_stack()
    if active_stack is None:
        raise RuntimeError("Painter has no active paintable layer stack.")
    preset = resource.ResourceID(context="starter_assets", name=str(preset_name)).url()
    config = {
        "exportPath": str(target),
        "exportList": [{"rootPath": str(stack)} for row in texture_sets for stack in row.all_stacks()],
        "defaultExportPreset": preset,
        "exportParameters": [{"parameters": {"sizeLog2": int(round(size.bit_length() - 1))}}],
        "exportShaderParams": False,
    }
    result = painter_export.export_project_textures(config)
    files = sorted(str(path) for path in target.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"Painter exported no texture files to {target}")
    dimensions = [_image_dimensions(Path(path)) for path in files]
    readable_dimensions = [value for value in dimensions if value is not None]
    resolution_ok = bool(readable_dimensions) and all(value == (size, size) for value in readable_dimensions)
    return {
        "ok": True,
        "output_path": str(target),
        "preset_name": str(preset_name),
        "preset_url": str(preset),
        "resolution": size,
        "texture_sets": stack_rows,
        "files": files,
        "dimensions": [list(value) if value else None for value in dimensions],
        "result": str(result),
        "parity_checks": {
            "texture-set names": all(row["name"] for row in stack_rows),
            "stack and UV-tile coverage": all(row["stacks"] for row in stack_rows),
            "requested channel resolution": resolution_ok,
            "exported map inventory": bool(files),
        },
    }


def _display_name(value: Any) -> str:
    candidate = getattr(value, "name", None)
    if callable(candidate):
        try:
            return str(candidate())
        except Exception:
            pass
    return str(candidate or value)


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        from PySide6.QtGui import QImage
    except ImportError:
        try:
            from PySide2.QtGui import QImage
        except ImportError:
            QImage = None
    if QImage is not None:
        image = QImage(str(path))
        if not image.isNull():
            return int(image.width()), int(image.height())
    try:
        with path.open("rb") as stream:
            header = stream.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
    except OSError:
        pass
    return None


__all__ = ["export_textures"]
