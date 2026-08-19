"""PCG graph authoring and inspection helpers for Unreal Editor."""

from __future__ import annotations

import json


def _load_graph(unreal, graph_path):
    graph = unreal.EditorAssetLibrary.load_asset(str(graph_path or ""))
    if graph is None or not isinstance(graph, unreal.PCGGraph):
        raise ValueError("PCG Graph not found: " + str(graph_path or ""))
    return graph


def _pin_rows(node):
    rows = []
    for pin in list(node.get_editor_property("input_pins")) + list(node.get_editor_property("output_pins")):
        properties = pin.get_editor_property("properties")
        rows.append({
            "label": str(properties.label),
            "is_output": bool(pin.is_output_pin()),
            "connected": bool(pin.is_connected()),
            "edge_count": len(list(pin.get_editor_property("edges"))),
        })
    return rows


def _vector_row(value):
    return [float(value.x), float(value.y), float(value.z)]


def _resolve_settings_class(unreal, class_name):
    """
        Resolves and validates a PCG settings class.
    :param unreal: Unreal Python module
    :param class_name: Unreal Python name or reflected class path
    :return: reflected PCG settings class
    """
    value = str(class_name or "").strip()
    settings_class = (
        unreal.load_class(None, value)
        if value.startswith("/")
        else getattr(unreal, value, None)
    )
    if settings_class is None or not hasattr(settings_class, "static_class"):
        raise ValueError("PCG settings class was not found: " + value)
    reflected = settings_class.static_class()
    if not unreal.MathLibrary.class_is_child_of(
        reflected,
        unreal.PCGSettings.static_class(),
    ):
        raise TypeError("Class is not a PCGSettings subclass: " + value)
    return settings_class


def _coerce_editor_value(unreal, current, value):
    """
        Coerces JSON-compatible values to common Unreal value structs.
    :param unreal: Unreal Python module
    :param current: current reflected property value
    :param value: requested JSON-compatible value
    :return: value suitable for set_editor_property
    """
    if isinstance(current, unreal.Vector) and isinstance(value, (list, tuple)):
        return unreal.Vector(*map(float, value))
    if isinstance(current, unreal.Vector2D) and isinstance(value, (list, tuple)):
        return unreal.Vector2D(*map(float, value))
    if isinstance(current, unreal.Rotator) and isinstance(value, (list, tuple)):
        return unreal.Rotator(*map(float, value))
    if isinstance(current, unreal.LinearColor) and isinstance(value, (list, tuple)):
        return unreal.LinearColor(*map(float, value))
    if isinstance(current, unreal.Color) and isinstance(value, (list, tuple)):
        return unreal.Color(*map(int, value))
    return value


def inspect_graph(graph_path):
    """
        Inspects a PCG graph, including settings, positions, pins, and edges.
    :param graph_path: Unreal PCG graph content path
    :return: JSON graph inspection receipt
    """
    import unreal

    graph = _load_graph(unreal, graph_path)
    nodes = []
    for node in list(graph.get_editor_property("nodes")):
        settings = node.get_settings()
        nodes.append({
            "name": str(node.get_name()),
            "title": str(node.get_editor_property("node_title")),
            "settings_class": str(settings.get_class().get_path_name()) if settings else "",
            "position": list(node.get_node_position()),
            "pins": _pin_rows(node),
        })
    edges = []
    for edge in list(graph.get_all_edges()):
        endpoint_a = edge.get_editor_property("input_pin")
        endpoint_b = edge.get_editor_property("output_pin")
        output_pin, input_pin = (
            (endpoint_a, endpoint_b) if endpoint_a.is_output_pin() else (endpoint_b, endpoint_a)
        )
        edges.append({
            "from_node": str(output_pin.get_editor_property("node").get_name()),
            "from_pin": str(output_pin.get_editor_property("properties").label),
            "to_node": str(input_pin.get_editor_property("node").get_name()),
            "to_pin": str(input_pin.get_editor_property("properties").label),
        })
    return json.dumps({
        "ok": True,
        "status": "inspected",
        "graph_path": graph_path,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }, indent=2, default=str)


def create_grid_transform_graph(
    graph_path,
    grid_extents=(1000.0, 1000.0, 100.0),
    cell_size=(200.0, 200.0, 200.0),
    offset=(0.0, 0.0, 100.0),
    save=True,
):
    """
        Authors a Grid to Transform to Output PCG graph.
    :param graph_path: Unreal PCG graph content path
    :param grid_extents: grid half extents
    :param cell_size: grid cell size
    :param offset: transform offset
    :param save: whether to save the graph package
    :return: JSON authoring receipt with graph readback
    """
    import unreal

    graph = _load_graph(unreal, graph_path)
    graph.modify()
    removable = list(graph.get_editor_property("nodes"))
    for node in removable:
        graph.remove_node(node)
    grid_node, grid_settings = graph.add_node_of_type(unreal.PCGCreatePointsGridSettings)
    transform_node, transform_settings = graph.add_node_of_type(unreal.PCGTransformPointsSettings)
    grid_settings.set_editor_property("grid_extents", unreal.Vector(*map(float, grid_extents)))
    grid_settings.set_editor_property("cell_size", unreal.Vector(*map(float, cell_size)))
    transform_settings.set_editor_property("offset_min", unreal.Vector(*map(float, offset)))
    transform_settings.set_editor_property("offset_max", unreal.Vector(*map(float, offset)))
    grid_node.set_node_position(0, 0)
    transform_node.set_node_position(320, 0)
    output_node = graph.get_output_node()
    output_node.set_node_position(640, 0)
    graph.add_edge(grid_node, "Out", transform_node, "In")
    graph.add_edge(transform_node, "Out", output_node, "Out")
    if hasattr(graph, "force_notification_for_editor"):
        graph.force_notification_for_editor()
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(graph, False)) if save else False
    inspection = json.loads(inspect_graph(graph_path))
    settings_readback = {
        "grid_extents": _vector_row(grid_settings.get_editor_property("grid_extents")),
        "cell_size": _vector_row(grid_settings.get_editor_property("cell_size")),
        "offset_min": _vector_row(transform_settings.get_editor_property("offset_min")),
        "offset_max": _vector_row(transform_settings.get_editor_property("offset_max")),
    }
    ok = bool(inspection.get("node_count") == 2 and inspection.get("edge_count") == 2)
    return json.dumps({
        "ok": bool(ok and (saved or not save)),
        "status": "authored_and_saved" if saved else "authored",
        "graph_path": graph_path,
        "saved": saved,
        "settings_readback": settings_readback,
        "inspection": inspection,
    }, indent=2, default=str)


def apply_graph_spec(
    graph_path,
    nodes,
    edges,
    clear_existing=True,
    save=True,
):
    """
        Applies a typed PCG node and connection specification.
    :param graph_path: Unreal PCG graph content path
    :param nodes: node specifications with id, settings_class, position, and properties
    :param edges: connection specifications with source, target, and pin labels
    :param clear_existing: whether to remove existing user nodes first
    :param save: whether to save the graph package
    :return: JSON authoring and structural readback receipt
    """
    import unreal

    node_specs = list(nodes or [])
    edge_specs = list(edges or [])
    if not node_specs:
        raise ValueError("PCG graph specification requires at least one node")
    prepared = []
    identifiers = set()
    for spec in node_specs:
        if not isinstance(spec, dict):
            raise TypeError("PCG node specifications must be dictionaries")
        identifier = str(spec.get("id") or "").strip()
        if not identifier or identifier.casefold() in identifiers:
            raise ValueError("PCG node ids must be non-empty and unique: " + identifier)
        identifiers.add(identifier.casefold())
        settings_class = _resolve_settings_class(unreal, spec.get("settings_class"))
        properties = dict(spec.get("properties") or {})
        defaults = unreal.get_default_object(settings_class)
        coerced = {}
        for property_name, requested in properties.items():
            try:
                current = defaults.get_editor_property(str(property_name))
            except Exception as exc:
                raise ValueError(
                    f"PCG property {property_name!r} is unavailable on {settings_class.__name__}"
                ) from exc
            coerced[str(property_name)] = _coerce_editor_value(unreal, current, requested)
        position = list(spec.get("position") or [0, len(prepared) * 180])
        if len(position) != 2:
            raise ValueError("PCG node position must contain x and y")
        prepared.append((identifier, settings_class, coerced, position))
    endpoints = identifiers | {"input", "output"}
    for edge in edge_specs:
        if not isinstance(edge, dict):
            raise TypeError("PCG edge specifications must be dictionaries")
        source = str(edge.get("source") or "").casefold()
        target = str(edge.get("target") or "").casefold()
        if source not in endpoints or target not in endpoints:
            raise ValueError(f"PCG edge references an unknown node: {source} -> {target}")
        if not str(edge.get("source_pin") or "") or not str(edge.get("target_pin") or ""):
            raise ValueError("PCG edges require source_pin and target_pin")

    graph = _load_graph(unreal, graph_path)
    with unreal.ScopedEditorTransaction("Tech Connector: Apply PCG Graph Spec"):
        graph.modify()
        if clear_existing:
            for node in list(graph.get_editor_property("nodes")):
                graph.remove_node(node)
        authored = {}
        for identifier, settings_class, properties, position in prepared:
            node, settings = graph.add_node_of_type(settings_class)
            for property_name, value in properties.items():
                settings.set_editor_property(property_name, value)
            node.set_node_position(int(position[0]), int(position[1]))
            authored[identifier.casefold()] = node
        authored["input"] = graph.get_input_node()
        authored["output"] = graph.get_output_node()
        for edge in edge_specs:
            graph.add_edge(
                authored[str(edge["source"]).casefold()],
                str(edge["source_pin"]),
                authored[str(edge["target"]).casefold()],
                str(edge["target_pin"]),
            )
        if hasattr(graph, "force_notification_for_editor"):
            graph.force_notification_for_editor()
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(graph, False)) if save else False
    inspection = json.loads(inspect_graph(graph_path))
    expected_nodes = len(node_specs)
    expected_edges = len(edge_specs)
    structural_match = bool(
        inspection.get("node_count") == expected_nodes
        and inspection.get("edge_count") == expected_edges
    )
    return json.dumps({
        "ok": bool(structural_match and (saved or not save)),
        "status": "authored_and_saved" if saved else "authored",
        "graph_path": graph_path,
        "authored_node_ids": [row[0] for row in prepared],
        "expected_node_count": expected_nodes,
        "expected_edge_count": expected_edges,
        "structural_match": structural_match,
        "saved": saved,
        "inspection": inspection,
    }, indent=2, default=str)
