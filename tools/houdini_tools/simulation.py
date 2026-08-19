"""Houdini deterministic DOP cook operations."""

from __future__ import annotations

from typing import Any


def run(dop_network_path: str, start_frame: int = 1, end_frame: int = 100, substeps: int = 1) -> dict[str, Any]:
    import hou

    network = hou.node(dop_network_path)
    if network is None:
        raise ValueError(f"DOP network does not exist: {dop_network_path}")
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    substep_parm = network.parm("substeps")
    if substep_parm is not None:
        substep_parm.set(max(1, int(substeps)))
    cooked = []
    for frame in range(start, end + 1):
        hou.setFrame(frame)
        network.cook(force=True)
        cooked.append(frame)
    return {"ok": True, "dop_network_path": network.path(), "frames": cooked, "substeps": max(1, int(substeps))}


__all__ = ["run"]
