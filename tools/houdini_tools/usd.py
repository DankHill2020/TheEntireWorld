"""Houdini USD export operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def export(filepath: str, node_path: str = "/obj", frame_range: list[int] | tuple[int, int] | None = None) -> dict[str, Any]:
    import hou

    source = hou.node(node_path)
    if source is None:
        raise ValueError(f"Houdini node does not exist: {node_path}")
    target = Path(filepath).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
    import_node = stage.createNode("sopimport", "tc_sop_import")
    import_node.parm("soppath").set(source.path())
    rop = stage.createNode("usd_rop", "tc_usd_export")
    rop.setInput(0, import_node)
    rop.parm("lopoutput").set(str(target))
    if frame_range:
        rop.parm("trange").set(1)
        rop.parm("f1").set(int(frame_range[0]))
        rop.parm("f2").set(int(frame_range[-1]))
    rop.render()
    return {"ok": True, "filepath": str(target), "node_path": source.path()}


__all__ = ["export"]
