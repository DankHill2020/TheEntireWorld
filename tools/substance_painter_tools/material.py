"""Substance Painter material application operations."""

from __future__ import annotations

from typing import Any


def apply_material(material_name: str, texture_set: str = "") -> dict[str, Any]:
    import substance_painter.resource as resource

    query = str(material_name or "").strip()
    if not query:
        raise ValueError("material_name is required")
    matches = list(resource.search(query))
    if not matches:
        raise ValueError(f"Substance Painter material was not found: {query}")
    raise NotImplementedError(
        "The material resource exists, but Painter does not expose a stable "
        "cross-version Python API for inserting a smart material into the layer "
        "stack. Apply it in Painter; Tech Connector records this step as delegated."
    )


__all__ = ["apply_material"]
