"""Concrete Houdini scene, node, material, and scripting operations."""

from __future__ import annotations

from typing import Any, Iterable


def _hou():
    import hou

    return hou


def _node(path: str):
    hou = _hou()
    value = hou.node(str(path))
    if value is None:
        raise KeyError(f"Unknown Houdini node: {path}")
    return value


def scene_select(nodes: Iterable[str], replace: bool = True) -> dict[str, Any]:
    hou = _hou()
    values = [_node(path) for path in nodes]
    if replace:
        for selected in hou.selectedNodes():
            selected.setSelected(False)
    for value in values:
        value.setSelected(True)
    if values:
        values[-1].setCurrent(True, clear_all_selected=False)
    return {"ok": True, "nodes": [value.path() for value in values]}


def scene_list(network: str = "/obj", recursive: bool = True, limit: int = 500) -> dict[str, Any]:
    parent = _node(network)
    values = list(parent.allSubChildren()) if recursive else list(parent.children())
    rows = [
        {"path": value.path(), "name": value.name(), "type": value.type().name()}
        for value in values[: max(1, int(limit))]
    ]
    return {"ok": True, "root": parent.path(), "nodes": rows, "count": len(rows)}


def node_create(node_type: str, parent: str = "/obj", name: str = "") -> dict[str, Any]:
    network = _node(parent)
    value = network.createNode(str(node_type), node_name=str(name or "") or None)
    return {"ok": True, "node_path": value.path(), "node_type": value.type().name()}


def node_set_parm(node_path: str, parm_name: str, value: Any) -> dict[str, Any]:
    node = _node(node_path)
    parm = node.parm(str(parm_name))
    if parm is None:
        raise KeyError(f"Houdini parameter does not exist: {node_path}.{parm_name}")
    parm.set(value)
    return {"ok": True, "node_path": node.path(), "parm": str(parm_name), "value": parm.eval()}


def node_connect(
    source_path: str,
    destination_path: str,
    output_index: int = 0,
    input_index: int = 0,
) -> dict[str, Any]:
    source = _node(source_path)
    destination = _node(destination_path)
    destination.setInput(int(input_index), source, int(output_index))
    connected = destination.input(int(input_index))
    if connected is not source:
        raise RuntimeError(f"Houdini did not retain connection {source.path()} -> {destination.path()}")
    return {
        "ok": True,
        "source_path": source.path(),
        "destination_path": destination.path(),
        "output_index": int(output_index),
        "input_index": int(input_index),
    }


def material_create(
    material_name: str,
    network: str = "/mat",
    shader_type: str = "principledshader::2.0",
    color: Iterable[float] | None = None,
) -> dict[str, Any]:
    parent = _node(network)
    existing = parent.node(str(material_name))
    material = existing or parent.createNode(str(shader_type), node_name=str(material_name))
    if color is not None:
        rgb = tuple(float(item) for item in color)
        if len(rgb) < 3:
            raise ValueError("Houdini material color requires three values.")
        parm = material.parmTuple("basecolor")
        if parm is not None:
            parm.set(rgb[:3])
    return {"ok": True, "material_path": material.path(), "created": existing is None}


def material_assign(
    material_path: str,
    node_path: str = "",
    nodes: Iterable[str] | None = None,
) -> dict[str, Any]:
    material = _node(material_path)
    assigned = []
    targets = list(nodes or ()) or ([node_path] if node_path else [])
    if not targets:
        raise ValueError("Houdini material assignment requires node_path or nodes.")
    for path in targets:
        node = _node(path)
        parm = node.parm("shop_materialpath")
        if parm is None:
            raise KeyError(f"Houdini node has no shop_materialpath parameter: {node.path()}")
        parm.set(material.path())
        assigned.append(node.path())
    return {"ok": True, "material_path": material.path(), "nodes": assigned}


def api_call(function: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None) -> Any:
    target: Any = _hou()
    for token in str(function).removeprefix("hou.").split("."):
        target = getattr(target, token)
    if not callable(target):
        raise TypeError(f"Houdini API target is not callable: {function}")
    return target(*(args or ()), **dict(kwargs or {}))


def script_run(code: str) -> Any:
    namespace: dict[str, Any] = {"hou": _hou()}
    exec(str(code), namespace, namespace)
    return namespace.get("result")


__all__ = [
    "api_call", "material_assign", "material_create", "node_connect", "node_create",
    "node_set_parm", "scene_list", "scene_select", "script_run",
]
