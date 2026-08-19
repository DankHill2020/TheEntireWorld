from __future__ import annotations

"""Small, explicit pymxs operations used by the 3ds Max bridge registry."""

from pathlib import Path
from typing import Any, Iterable


def _runtime():
    import pymxs

    return pymxs.runtime


def _node(rt: Any, name: str) -> Any:
    value = rt.getNodeByName(str(name))
    if value is None:
        raise KeyError(f"Unknown 3ds Max node: {name}")
    return value


def scene_list(*, selected: bool = False, limit: int = 500) -> list[str]:
    rt = _runtime()
    rows = list(rt.selection if selected else rt.objects)
    return [str(item.name) for item in rows[: max(1, int(limit))]]


def scene_select(nodes: Iterable[str], *, replace: bool = True) -> list[str]:
    rt = _runtime()
    values = [_node(rt, name) for name in nodes]
    if replace:
        rt.clearSelection()
    if values:
        rt.select(values)
    return [str(item.name) for item in values]


def scene_move(nodes: Iterable[str], translation: Iterable[float], *, relative: bool = True) -> list[str]:
    rt = _runtime()
    xyz = tuple(float(value) for value in translation)
    if len(xyz) != 3:
        raise ValueError("translation must contain exactly three values")
    delta = rt.Point3(*xyz)
    values = [_node(rt, name) for name in nodes]
    for item in values:
        item.position = item.position + delta if relative else delta
    return [str(item.name) for item in values]


def mesh_create_box(*, name: str = "Box", size: Iterable[float] = (1.0, 1.0, 1.0)) -> str:
    rt = _runtime()
    xyz = tuple(float(value) for value in size)
    if len(xyz) != 3 or any(value <= 0.0 for value in xyz):
        raise ValueError("Box size requires three positive values.")
    node = rt.Box(name=str(name), length=xyz[2], width=xyz[0], height=xyz[1])
    return str(node.name)


def mesh_apply_modifier(node: str, modifier: str, parameters: dict[str, Any] | None = None) -> str:
    rt = _runtime()
    target = _node(rt, node)
    constructor = getattr(rt, str(modifier), None)
    if not callable(constructor):
        raise ValueError(f"Unknown 3ds Max modifier: {modifier}")
    instance = constructor()
    for key, value in dict(parameters or {}).items():
        setattr(instance, str(key), value)
    rt.addModifier(target, instance)
    return str(rt.classOf(instance))


def material_create(material_name: str, *, color: Iterable[float] | None = None) -> str:
    rt = _runtime()
    material = rt.Standardmaterial(name=str(material_name))
    if color is not None:
        rgb = tuple(float(value) for value in color)
        if len(rgb) != 3:
            raise ValueError("Material color requires RGB values.")
        scale = 255.0 if max(rgb) <= 1.0 else 1.0
        material.diffuse = rt.Color(*(value * scale for value in rgb))
    return str(material.name)


def material_assign(material_name: str, nodes: Iterable[str]) -> list[str]:
    rt = _runtime()
    material = next((item for item in list(rt.sceneMaterials) if str(item.name) == str(material_name)), None)
    if material is None:
        raise KeyError(f"Unknown 3ds Max material: {material_name}")
    values = [_node(rt, name) for name in nodes]
    for item in values:
        item.material = material
    return [str(item.name) for item in values]


def io_import(filepath: str) -> str:
    rt = _runtime()
    rt.importFile(str(filepath), rt.name("noPrompt"))
    return str(filepath)


def io_export(filepath: str, *, selected_only: bool = False) -> dict[str, Any]:
    rt = _runtime()
    target = Path(filepath).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    rt.exportFile(str(target), rt.name("noPrompt"), selectedOnly=bool(selected_only))
    if not target.is_file():
        raise RuntimeError(f"3ds Max reported export success but no file exists: {target}")
    return {"ok": True, "filepath": str(target), "selected_only": bool(selected_only)}


def animation_set_key(node: str, attribute: str, frame: int, value: Any) -> dict[str, Any]:
    import pymxs

    rt = pymxs.runtime
    target = _node(rt, node)
    with pymxs.animate(True):
        with pymxs.attime(int(frame)):
            _set_nested_attribute(rt, target, str(attribute), value)
    return {"node": str(target.name), "attribute": str(attribute), "frame": int(frame), "value": value}


def _set_nested_attribute(rt: Any, target: Any, attribute: str, value: Any) -> None:
    tokens = str(attribute).split(".")
    if len(tokens) == 2 and tokens[0] in {"position", "scale"} and tokens[1] in {"x", "y", "z"}:
        current = getattr(target, tokens[0])
        values = [float(current.x), float(current.y), float(current.z)]
        values[{"x": 0, "y": 1, "z": 2}[tokens[1]]] = float(value)
        setattr(target, tokens[0], rt.Point3(*values))
        return
    owner = target
    for token in tokens[:-1]:
        owner = getattr(owner, token)
    setattr(owner, tokens[-1], value)


def _nested_attribute(target: Any, attribute: str) -> Any:
    value = target
    for token in str(attribute).split("."):
        value = getattr(value, token)
    return value


def workflow_inspect_modifier_asset(
    node: str,
    modifier: str,
    material_name: str,
    animation_attribute: str,
    animation_frame: int,
    animation_value: Any,
    export_path: str,
    modifier_parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import pymxs

    rt = pymxs.runtime
    target = _node(rt, node)
    modifiers = list(target.modifiers)
    matching = [value for value in modifiers if str(rt.classOf(value)).lower() == str(modifier).lower()]
    editable_ok = bool(modifiers and target)
    parameters_ok = bool(matching)
    if matching:
        for name, expected in dict(modifier_parameters or {}).items():
            try:
                actual = getattr(matching[0], str(name))
                parameters_ok = parameters_ok and abs(float(actual) - float(expected)) <= 1e-4
            except Exception:
                parameters_ok = False
    assigned_material = getattr(target, "material", None)
    material_ok = bool(assigned_material and str(assigned_material.name) == str(material_name))
    with pymxs.attime(int(animation_frame)):
        observed = _nested_attribute(target, animation_attribute)
    try:
        animation_ok = abs(float(observed) - float(animation_value)) <= 1e-4
    except (TypeError, ValueError):
        animation_ok = observed == animation_value
    artifact = Path(export_path).expanduser().resolve()
    return {
        "ok": True,
        "absolute_path": str(artifact),
        "node": str(target.name),
        "modifier_count": len(modifiers),
        "material": str(assigned_material.name) if assigned_material else "",
        "animation_value": observed,
        "parity_checks": {
            "editable topology and modifier stack": editable_ok,
            "modifier parameters": parameters_ok,
            "material assignment": material_ok,
            "animation keys": animation_ok,
        },
    }


def api_call(function: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:
    target = _runtime()
    for token in str(function).split("."):
        target = getattr(target, token)
    if not callable(target):
        raise TypeError(f"3ds Max API target is not callable: {function}")
    return target(*(args or ()), **dict(kwargs or {}))


def script_run(code: str) -> Any:
    namespace: dict[str, Any] = {"pymxs": __import__("pymxs")}
    exec(str(code), namespace, namespace)
    return namespace.get("result")
