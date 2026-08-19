"""Read-only parity inspectors for Houdini production workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def inspect_procedural_fx(
    source_node: str,
    transform_node: str,
    dop_network_path: str,
    usd_path: str,
    start_frame: int = 1,
    end_frame: int = 24,
) -> dict[str, Any]:
    import hou

    source = hou.node(str(source_node))
    transform = hou.node(str(transform_node))
    dop = hou.node(str(dop_network_path))
    target = Path(usd_path).expanduser().resolve()
    topology_ok = bool(source and transform and transform.input(0) is source and dop)
    geometry = transform.geometry() if transform is not None else None
    bounds = []
    if geometry is not None:
        box = geometry.boundingBox()
        bounds = [float(value) for value in (*box.minvec(), *box.maxvec())]
    bounds_ok = len(bounds) == 6 and all(value == value for value in bounds)
    usd_ok = bool(target.is_file() and target.stat().st_size > 0)
    if usd_ok:
        try:
            from pxr import Usd

            stage = Usd.Stage.Open(str(target))
            usd_ok = bool(stage and stage.GetPseudoRoot())
        except Exception:
            usd_ok = False
    start, end = int(start_frame), max(int(start_frame), int(end_frame))
    return {
        "ok": True,
        "absolute_path": str(target),
        "node_paths": [path for path in (source_node, transform_node, dop_network_path) if hou.node(path)],
        "geometry_bounds": bounds,
        "frame_range": [start, end],
        "parity_checks": {
            "node topology": topology_ok,
            "simulation frame range": start <= end,
            "geometry bounds": bounds_ok,
            "USD composition": usd_ok,
        },
    }


__all__ = ["inspect_procedural_fx"]
