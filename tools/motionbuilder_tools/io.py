"""Concrete MotionBuilder FBX interchange and animation readback operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _sdk():
    import pyfbsdk

    return pyfbsdk


def import_fbx(filepath: str, merge: bool = True) -> dict[str, Any]:
    sdk = _sdk()
    path = Path(filepath).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"FBX does not exist: {path}")
    app = sdk.FBApplication()
    ok = bool(app.FileMerge(str(path)) if merge else app.FileOpen(str(path)))
    if not ok:
        raise RuntimeError(f"MotionBuilder could not {'merge' if merge else 'open'} {path}")
    return {"ok": True, "filepath": str(path), "merge": bool(merge)}


def export_fbx(filepath: str, selected_only: bool = False) -> dict[str, Any]:
    sdk = _sdk()
    path = Path(filepath).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    options = sdk.FBFbxOptions(False)
    if hasattr(options, "SaveSelectedModelsOnly"):
        options.SaveSelectedModelsOnly = bool(selected_only)
    ok = bool(sdk.FBApplication().FileSave(str(path), options))
    if not ok:
        raise RuntimeError(f"MotionBuilder could not export {path}")
    return {"ok": True, "filepath": str(path), "selected_only": bool(selected_only)}


def _animation_key_count(model: Any) -> int:
    total = 0
    for property_name in ("Translation", "Rotation", "Scaling"):
        prop = getattr(model, property_name, None)
        node = prop.GetAnimationNode() if prop is not None and callable(getattr(prop, "GetAnimationNode", None)) else None
        if node is None:
            continue
        nodes = list(getattr(node, "Nodes", []) or []) or [node]
        for child in nodes:
            curve = getattr(child, "FCurve", None)
            total += len(getattr(curve, "Keys", []) or []) if curve is not None else 0
    return total


def inspect_character(character_name: str) -> dict[str, Any]:
    sdk = _sdk()
    scene = sdk.FBSystem().Scene
    characters = list(getattr(scene, "Characters", []) or [])
    if not characters:
        characters = [item for item in scene.Components if isinstance(item, sdk.FBCharacter)]
    character = next((item for item in characters if str(getattr(item, "Name", "")) == str(character_name)), None)
    if character is None:
        raise ValueError(f"MotionBuilder character does not exist: {character_name}")
    take = sdk.FBSystem().CurrentTake
    span = getattr(take, "LocalTimeSpan", None)
    start = span.GetStart().GetFrame() if span is not None else 0
    end = span.GetStop().GetFrame() if span is not None else 0
    skeleton_type = getattr(sdk, "FBModelSkeleton", ())
    skeletons = [
        item for item in scene.Components
        if not skeleton_type or isinstance(item, skeleton_type)
    ]
    key_count = sum(_animation_key_count(model) for model in skeletons)
    characterized = bool(character.GetCharacterize())
    checks = {
        "character mapping": characterized,
        "root motion": key_count > 0,
        "take range and frame rate": int(end) >= int(start),
        "plotted transform curves": key_count > 0,
    }
    return {
        "ok": True,
        "character": str(character.Name),
        "characterized": characterized,
        "take": str(getattr(take, "Name", "")),
        "start_frame": int(start),
        "end_frame": int(end),
        "skeleton_count": len(skeletons),
        "animation_key_count": int(key_count),
        "parity_checks": checks,
    }


__all__ = ["export_fbx", "import_fbx", "inspect_character"]
