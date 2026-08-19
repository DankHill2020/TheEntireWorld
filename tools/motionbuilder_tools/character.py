"""Concrete MotionBuilder characterization and plotting operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SLOT_ALIASES = {
    "Hips": ("hips", "pelvis", "root"),
    "LeftUpLeg": ("leftupleg", "leftthigh", "l_thigh", "thigh_l"),
    "LeftLeg": ("leftleg", "leftcalf", "l_calf", "calf_l"),
    "LeftFoot": ("leftfoot", "l_foot", "foot_l"),
    "RightUpLeg": ("rightupleg", "rightthigh", "r_thigh", "thigh_r"),
    "RightLeg": ("rightleg", "rightcalf", "r_calf", "calf_r"),
    "RightFoot": ("rightfoot", "r_foot", "foot_r"),
    "Spine": ("spine", "spine1", "spine_01"),
    "Head": ("head",),
    "LeftArm": ("leftarm", "leftupperarm", "l_upperarm", "upperarm_l"),
    "LeftForeArm": ("leftforearm", "l_forearm", "lowerarm_l"),
    "LeftHand": ("lefthand", "l_hand", "hand_l"),
    "RightArm": ("rightarm", "rightupperarm", "r_upperarm", "upperarm_r"),
    "RightForeArm": ("rightforearm", "r_forearm", "lowerarm_r"),
    "RightHand": ("righthand", "r_hand", "hand_r"),
}


def _sdk():
    import pyfbsdk

    return pyfbsdk


def _normalized(name: str) -> str:
    return "".join(character for character in str(name or "").lower().split(":")[-1] if character.isalnum() or character == "_")


def _characters(sdk: Any) -> list[Any]:
    scene = sdk.FBSystem().Scene
    direct = getattr(scene, "Characters", None)
    if direct is not None:
        return list(direct)
    return [item for item in scene.Components if isinstance(item, sdk.FBCharacter)]


def _character(sdk: Any, name: str) -> Any | None:
    return next((item for item in _characters(sdk) if str(getattr(item, "Name", "")) == str(name)), None)


def _mapping_from_file(path: str) -> dict[str, str]:
    if not path:
        return {}
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Character definition does not exist: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    values = data.get("slots") or data.get("mapping") or data
    if not isinstance(values, dict):
        raise ValueError("Character definition must contain a slot-to-model mapping.")
    return {str(slot): str(model) for slot, model in values.items() if model}


def _auto_mapping(sdk: Any) -> dict[str, str]:
    models = []
    skeleton_type = getattr(sdk, "FBModelSkeleton", ())
    for component in sdk.FBSystem().Scene.Components:
        if skeleton_type and not isinstance(component, skeleton_type):
            continue
        name = str(getattr(component, "LongName", "") or getattr(component, "Name", ""))
        if name:
            models.append((name, _normalized(name)))
    mapping: dict[str, str] = {}
    for slot, aliases in _SLOT_ALIASES.items():
        match = next((name for name, normalized in models if normalized in aliases), "")
        if not match:
            match = next((name for name, normalized in models if any(normalized.endswith(alias) for alias in aliases)), "")
        if match:
            mapping[slot] = match
    return mapping


def _assign_slot(character: Any, slot: str, model: Any) -> bool:
    property_value = character.PropertyList.Find(str(slot) + "Link")
    if property_value is None:
        return False
    try:
        property_value.removeAll()
    except Exception:
        try:
            property_value.RemoveAll()
        except Exception:
            pass
    for method_name in ("append", "Add"):
        method = getattr(property_value, method_name, None)
        if callable(method):
            method(model)
            return True
    return False


def create_character(character_name: str, definition_file: str = "") -> dict[str, Any]:
    sdk = _sdk()
    name = str(character_name or "").strip()
    if not name:
        raise ValueError("character_name is required")
    character = _character(sdk, name) or sdk.FBCharacter(name)
    mapping = _mapping_from_file(definition_file) or _auto_mapping(sdk)
    assigned: dict[str, str] = {}
    missing_models: list[str] = []
    for slot, model_name in mapping.items():
        model = sdk.FBFindModelByLabelName(model_name)
        if model is None:
            missing_models.append(model_name)
            continue
        if _assign_slot(character, slot, model):
            assigned[slot] = model_name
    if not assigned and not bool(character.GetCharacterize()):
        raise RuntimeError("No character slots could be mapped; provide a definition file or standard joint names.")
    if not bool(character.GetCharacterize()):
        result = character.SetCharacterizeOn(True)
        if result is False or not bool(character.GetCharacterize()):
            raise RuntimeError("MotionBuilder rejected the character mapping.")
    return {
        "ok": True,
        "character": name,
        "characterized": bool(character.GetCharacterize()),
        "assigned_slots": assigned,
        "missing_models": missing_models,
    }


def plot_animation(character_name: str, plot_to_rig: bool = True, fps: int = 30) -> dict[str, Any]:
    sdk = _sdk()
    character = _character(sdk, str(character_name))
    if character is None:
        raise ValueError(f"MotionBuilder character does not exist: {character_name}")
    if not bool(character.GetCharacterize()):
        raise RuntimeError("Character must be characterized before plotting.")
    options = sdk.FBPlotOptions()
    options.PlotAllTakes = False
    options.PlotOnFrame = True
    options.PlotPeriod = sdk.FBTime(0, 0, 0, 1)
    options.PlotTranslationOnRootOnly = False
    options.PreciseTimeDiscontinuities = False
    options.UseConstantKeyReducer = False
    destination = (
        sdk.FBCharacterPlotWhere.kFBCharacterPlotOnControlRig
        if plot_to_rig else sdk.FBCharacterPlotWhere.kFBCharacterPlotOnSkeleton
    )
    ok = bool(character.PlotAnimation(destination, options))
    if not ok:
        raise RuntimeError("MotionBuilder did not plot animation for the character.")
    return {
        "ok": True,
        "character": str(character.Name),
        "plot_destination": "control_rig" if plot_to_rig else "skeleton",
        "fps": int(fps),
        "take": str(getattr(sdk.FBSystem().CurrentTake, "Name", "")),
    }


__all__ = ["create_character", "plot_animation"]
