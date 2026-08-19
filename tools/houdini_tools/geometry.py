"""Houdini geometry interchange operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def import_file(filepath: str, parent: str = "/obj", name: str = "ai_import") -> dict[str, Any]:
    import hou

    source = Path(filepath).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Geometry does not exist: {source}")
    network = hou.node(parent)
    if network is None:
        raise ValueError(f"Houdini network does not exist: {parent}")
    container = network.createNode("geo", node_name=str(name or "ai_import")) if network.childTypeCategory().name() == "Object" else network
    node = container.createNode("file", node_name=f"{name}_file")
    node.parm("file").set(str(source))
    node.cook(force=True)
    return {"ok": True, "filepath": str(source), "node_path": node.path()}


def export_file(node_path: str, filepath: str, frame: int = 1) -> dict[str, Any]:
    import hou

    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Houdini node does not exist: {node_path}")
    target = Path(filepath).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with hou.undos.disabler():
        hou.setFrame(int(frame))
        geometry = node.geometry()
        if geometry is None:
            raise RuntimeError(f"Node has no cooked geometry: {node_path}")
        geometry.saveToFile(str(target))
    return {"ok": True, "node_path": node.path(), "filepath": str(target), "frame": int(frame)}


__all__ = ["export_file", "import_file"]
