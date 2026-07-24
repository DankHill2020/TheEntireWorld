"""MetaHumanDNA operation adapters for cross-DCC Unreal workflows."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _tools_root() -> Path:
    raw = os.environ.get("TOOLSROOT") or "C:/depot/tools"
    return Path(raw)


def _default_tool_root() -> Path:
    return _tools_root() / "external_tools" / "MetaHumanDNA"


def propagate_dna(
    metahuman_dna_path: str = "",
    animation_or_scene_delta: str = "",
    tool_root: str = "",
    output_path: str = "",
    skip_if_unavailable: bool = True,
) -> dict[str, Any]:
    """Prepare or execute a MetaHumanDNA propagation step with explicit proof.

    This adapter does not fake DNA mutation. If the local MetaHumanDNA tooling is
    unavailable, it returns a deterministic skip/blocker payload the planner can
    surface before Unreal import/slot wiring.
    """
    root = Path(tool_root) if tool_root else _default_tool_root()
    dna = Path(metahuman_dna_path) if metahuman_dna_path else None
    delta = Path(animation_or_scene_delta) if animation_or_scene_delta else None
    output = Path(output_path) if output_path else _tools_root() / "tool_output" / "metahuman_dna"
    candidates = [
        root / "dna_viewer",
        root / "DNAViewer",
        root / "examples",
        root / "lib",
    ]
    found = [str(path) for path in candidates if path.exists()]
    missing_inputs = []
    if dna and not dna.exists():
        missing_inputs.append(str(dna))
    if delta and not delta.exists():
        missing_inputs.append(str(delta))
    available = bool(root.exists() and found)
    if not available or missing_inputs:
        return {
            "ok": bool(skip_if_unavailable and not missing_inputs),
            "status": "metahuman_dna_tool_unavailable" if not available else "metahuman_dna_inputs_missing",
            "tool_root": str(root),
            "available_paths": found,
            "metahuman_dna_path": str(dna or ""),
            "animation_or_scene_delta": str(delta or ""),
            "missing_inputs": missing_inputs,
            "output_path": str(output),
            "skipped": bool(skip_if_unavailable),
        }
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "metahuman_dna_path": str(dna or ""),
        "animation_or_scene_delta": str(delta or ""),
        "tool_root": str(root),
        "output_path": str(output),
        "available_paths": found,
        "status": "ready_for_metahuman_dna_execution",
    }
    manifest_path = output / "metahuman_dna_propagation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"ok": True, "status": "manifest_written", "manifest_path": str(manifest_path), **manifest}


def as_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)
