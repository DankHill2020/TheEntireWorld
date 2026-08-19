"""Current-session Maya FBX animation export for bridge operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable


def export_fbx(
    export_path: str,
    start_frame: int = 1,
    end_frame: int = 120,
    selected_only: bool = True,
    nodes: Iterable[str] | None = None,
) -> dict[str, Any]:
    import maya.cmds as cmds
    import maya.mel as mel

    target = Path(export_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya")
    export_nodes = [str(value) for value in nodes or () if value]
    missing = [value for value in export_nodes if not cmds.objExists(value)]
    if missing:
        raise ValueError("Maya FBX export nodes do not exist: " + ", ".join(missing))
    if export_nodes:
        cmds.select(export_nodes, replace=True)
        selected_only = True
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    mel.eval("FBXResetExport")
    mel.eval("FBXExportBakeComplexAnimation -v true")
    mel.eval(f"FBXExportBakeComplexStart -v {start}")
    mel.eval(f"FBXExportBakeComplexEnd -v {end}")
    mel.eval("FBXExportBakeComplexStep -v 1")
    escaped = str(target).replace("\\", "/").replace('"', '\\"')
    mel.eval(f'FBXExport -f "{escaped}"' + (" -s" if selected_only else ""))
    if not target.is_file():
        raise RuntimeError(f"Maya reported FBX export success but no file exists: {target}")
    return {
        "ok": True,
        "export_path": str(target),
        "start_frame": start,
        "end_frame": end,
        "selected_only": bool(selected_only),
        "nodes": export_nodes,
    }


__all__ = ["export_fbx"]
