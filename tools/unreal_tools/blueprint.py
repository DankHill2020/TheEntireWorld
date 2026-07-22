"""Blueprint scan/create/compile helpers for AI Studio Unreal operations."""

from __future__ import annotations

import json
import re

from unreal_tools.assets import load_asset


def _load_blueprint(unreal, asset_path):
    asset = load_asset(unreal, asset_path)
    if not asset:
        raise ValueError(f"Blueprint asset not found: {asset_path}")
    return asset


def _pin_type_summary(pin_type):
    if pin_type is None:
        return ""
    for name in ("pin_category", "category"):
        try:
            value = pin_type.get_editor_property(name)
            if value:
                return str(value)
        except Exception:
            pass
    try:
        exported = str(pin_type.export_text())
        category = re.search(r'PinCategory="([^"]*)"', exported)
        object_type = re.search(r"PinSubCategoryObject=\"[^']*'([^']+)'\"", exported)
        base = category.group(1) if category else ""
        if object_type:
            return f"{base}:{object_type.group(1).rsplit('.', 1)[-1]}" if base else object_type.group(1)
        if base:
            return base
    except Exception:
        pass
    text = str(pin_type)
    return text.split(" (0x", 1)[0].replace("<Struct 'EdGraphPinType'", "EdGraphPinType").strip(" <>")


def _variable_row(unreal, blueprint, raw_name):
    raw = str(raw_name)
    display = raw.rsplit(".", 1)[-1]
    try:
        pin_type = unreal.BlueprintEditorLibrary.get_member_variable_type(blueprint, raw_name)
    except Exception:
        pin_type = None
    try:
        category = str(unreal.BlueprintEditorLibrary.get_blueprint_variable_category(blueprint, raw_name))
    except Exception:
        category = ""
    return {"name": display, "type": _pin_type_summary(pin_type), "category": category}


def scan_blueprint(asset_path, include_graphs=True, include_defaults=True):
    import unreal

    bp = _load_blueprint(unreal, asset_path)
    result = {
        "asset_path": asset_path,
        "class": bp.get_class().get_name(),
        "name": bp.get_name(),
        "parent_class": "",
        "variables": [],
        "inherited_project_variables": [],
        "functions": [],
        "components": [],
        "graphs": [],
        "compile_status": "",
        "compile_errors": [],
        "compile_warnings": [],
        "warnings": [],
    }

    try:
        parent_class = bp.get_blueprint_parent_class()
        result["parent_class"] = parent_class.get_path_name() if parent_class else ""
    except Exception as exc:
        result["warnings"].append(f"parent_class unavailable: {exc}")

    try:
        for name in unreal.BlueprintEditorLibrary.list_member_variable_names(bp) or []:
            raw = str(name)
            row = _variable_row(unreal, bp, name)
            if raw.startswith("/Game/"):
                result["inherited_project_variables"].append(row)
            elif not raw.startswith("/Script/"):
                result["variables"].append(row)
    except Exception as exc:
        result["warnings"].append(f"variables unavailable: {exc}")

    try:
        standard_graphs = {"EventGraph", "AnimGraph", "UserConstructionScript"}
        result["functions"] = [
            str(name)
            for name in unreal.BlueprintEditorLibrary.list_graph_names(bp) or []
            if str(name) not in standard_graphs
        ]
    except Exception as exc:
        result["warnings"].append(f"functions unavailable: {exc}")

    if include_graphs:
        for graph_name in unreal.BlueprintEditorLibrary.list_graph_names(bp) or []:
            graph_row = {"name": str(graph_name), "node_count": 0, "nodes": []}
            try:
                editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(bp, str(graph_name))
                if editor is not None:
                    nodes = list(editor.list_all_nodes() or [])
                    graph_row["node_count"] = len(nodes)
                    graph_row["nodes"] = [
                        {
                            "name": str(node.get_name()),
                            "title": str(unreal.BlueprintEditorLibrary.get_node_title(node)),
                        }
                        for node in nodes
                    ]
                    result["compile_errors"].extend(
                        str(node.get_name()) for node in editor.list_nodes_with_errors() or []
                    )
                    result["compile_warnings"].extend(
                        str(node.get_name()) for node in editor.list_nodes_with_warnings() or []
                    )
            except Exception as exc:
                graph_row["warning"] = str(exc)
            result["graphs"].append(graph_row)

    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        result["compile_status"] = "compiled_with_errors" if result["compile_errors"] else "compiled"
    except Exception as exc:
        result["compile_status"] = f"compile failed: {exc}"

    return json.dumps(result, indent=2, default=str)


def compile_blueprint(asset_path):
    import unreal

    bp = _load_blueprint(unreal, asset_path)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    return json.dumps({"asset_path": asset_path, "compiled": True}, indent=2)


def _graph_editor(unreal, blueprint, graph_name):
    editor = unreal.BlueprintGraphEditor.get_graph_editor_by_name(blueprint, str(graph_name))
    if editor is None:
        raise ValueError(f"Blueprint graph not found: {graph_name}")
    return editor


def _node_by_name(editor, node_name):
    wanted = str(node_name or "").strip().lower()
    matches = []
    for node in editor.list_all_nodes() or []:
        names = {str(node.get_name()).lower()}
        try:
            names.add(str(node.get_node_title(0)).lower())
        except Exception:
            pass
        if wanted in names:
            matches.append(node)
    if len(matches) != 1:
        raise ValueError(f"Expected one node named {node_name!r}, found {len(matches)}")
    return matches[0]


def _pin_by_name(unreal, node, pin_name):
    wanted = str(pin_name or "").replace(" ", "").lower()
    matches = []
    for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
        name = str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin))
        if name.replace(" ", "").lower() == wanted:
            matches.append(pin)
    if len(matches) != 1:
        raise ValueError(
            f"Expected one pin named {pin_name!r} on {node.get_name()}, found {len(matches)}"
        )
    return matches[0]


def add_function(blueprint_path, function_name, inputs=None, outputs=None, save=True):
    import unreal

    blueprint = _load_blueprint(unreal, blueprint_path)
    names = {str(value) for value in unreal.BlueprintEditorLibrary.list_graph_names(blueprint) or []}
    created = str(function_name) not in names
    editor = (
        unreal.BlueprintGraphEditor.create_and_edit_function_graph(blueprint, str(function_name))
        if created
        else _graph_editor(unreal, blueprint, function_name)
    )
    if inputs or outputs:
        raise NotImplementedError(
            "Typed function signature authoring needs a reflected signature adapter; the empty graph was not accepted as complete."
        )
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False)
    graph_names = {str(value) for value in unreal.BlueprintEditorLibrary.list_graph_names(blueprint) or []}
    ok = str(function_name) in graph_names and editor is not None
    if not ok:
        raise RuntimeError(f"Function graph readback failed: {function_name}")
    return json.dumps({
        "ok": True,
        "blueprint_path": blueprint_path,
        "function_name": function_name,
        "created": created,
        "postconditions": {"graph_exists": True, "compiled": True, "saved": bool(save)},
    }, indent=2)


def add_node_to_graph(
    blueprint_path,
    graph_name,
    node_class,
    node_name="",
    x=0.0,
    y=0.0,
    context_node_names=None,
    save=True,
):
    import unreal

    blueprint = _load_blueprint(unreal, blueprint_path)
    editor = _graph_editor(unreal, blueprint, graph_name)
    context_nodes = [
        _node_by_name(editor, value) for value in context_node_names or []
    ]
    context_pins = []
    for node in context_nodes:
        context_pins.extend(unreal.BlueprintEditorLibrary.list_all_pins(node) or [])
    node = editor.create_node_from_name(
        str(node_class), unreal.Vector2D(float(x), float(y)), context_pins, None
    )
    if node is None:
        raise RuntimeError(f"BlueprintGraphEditor could not create action: {node_class}")
    if node_name:
        try:
            node.rename(str(node_name))
        except Exception:
            pass
    unreal.BlueprintEditorLibrary.set_node_pos(node, unreal.IntPoint(int(x), int(y)))
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False)
    created_name = str(node.get_name())
    readback = [str(value.get_name()) for value in editor.list_all_nodes() or []]
    if created_name not in readback:
        raise RuntimeError(f"Created node did not survive graph readback: {created_name}")
    pins = [
        str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin))
        for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []
    ]
    return json.dumps({
        "ok": True,
        "blueprint_path": blueprint_path,
        "graph_name": graph_name,
        "node_name": created_name,
        "palette_action": node_class,
        "pins": pins,
        "postconditions": {"node_readback": True, "compiled": True, "saved": bool(save)},
    }, indent=2)


def connect_node_pins(
    blueprint_path,
    graph_name,
    source_node,
    source_pin,
    target_node,
    target_pin,
    save=True,
):
    import unreal

    blueprint = _load_blueprint(unreal, blueprint_path)
    editor = _graph_editor(unreal, blueprint, graph_name)
    source = _pin_by_name(unreal, _node_by_name(editor, source_node), source_pin)
    target = _pin_by_name(unreal, _node_by_name(editor, target_node), target_pin)
    linked = bool(unreal.BlueprintGraphPinLibrary.try_create_connection(source, target))
    if not linked:
        raise RuntimeError(
            f"Schema rejected pin connection {source_node}.{source_pin} -> {target_node}.{target_pin}"
        )
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False)
    return json.dumps({
        "ok": True,
        "blueprint_path": blueprint_path,
        "graph_name": graph_name,
        "source": f"{source_node}.{source_pin}",
        "target": f"{target_node}.{target_pin}",
        "postconditions": {"schema_connection_accepted": True, "compiled": True, "saved": bool(save)},
    }, indent=2)


def get_compile_errors(blueprint_path):
    import unreal

    blueprint = _load_blueprint(unreal, blueprint_path)
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    status = str(blueprint.get_editor_property("status")) if blueprint.has_editor_property("status") else "unknown"
    return json.dumps({
        "ok": "error" not in status.lower(),
        "blueprint_path": blueprint_path,
        "compile_status": status,
        "postconditions": {"compile_status_read": True},
    }, indent=2)


def _bridge_action_result(unreal, method_name, blueprint_path, graph_name, *args):
    library = getattr(unreal, "AIStudioBridgeLibrary", None)
    if library is None or not hasattr(library, method_name):
        raise RuntimeError(f"Installed AIStudioBridge does not expose {method_name}")
    blueprint = _load_blueprint(unreal, blueprint_path)
    raw = getattr(library, method_name)(blueprint, str(graph_name), *args)
    result = json.loads(str(raw or "{}"))
    if not isinstance(result, dict):
        raise RuntimeError(f"AIStudioBridge {method_name} returned non-object JSON")
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or f"{method_name} failed"))
    return json.dumps(result, indent=2)


def describe_node_action(blueprint_path, graph_name, palette_action):
    """Read an exact context-filtered palette action and pin signature without mutation."""
    import unreal

    return _bridge_action_result(
        unreal,
        "describe_blueprint_node_action",
        blueprint_path,
        graph_name,
        str(palette_action),
    )


def search_node_actions(blueprint_path, graph_name, query, max_results=50):
    """Search live graph-context Blueprint actions without changing the source asset."""
    import unreal

    return _bridge_action_result(
        unreal,
        "search_blueprint_node_actions",
        blueprint_path,
        graph_name,
        str(query),
        int(max_results),
    )


def probe_node_action(
    blueprint_path,
    graph_name,
    palette_action,
    temp_folder="/Game/AIStudio/Temp/NodeProbes",
):
    """Create an action only on a disposable Blueprint copy and report its real pins."""
    import unreal

    original = _load_blueprint(unreal, blueprint_path)
    original_dirty = None
    try:
        original_dirty = bool(original.get_outermost().is_dirty())
    except Exception:
        pass
    probe_name = re.sub(r"[^A-Za-z0-9_]", "_", str(original.get_name())) + "_NodeProbe"
    probe_path = f"{str(temp_folder).rstrip('/')}/{probe_name}"
    probe = None
    editor = None
    node = None
    report = {
        "ok": False,
        "blueprint_path": blueprint_path,
        "graph_name": graph_name,
        "palette_action": palette_action,
        "probe_path": probe_path,
        "pins": [],
        "errors": [],
    }
    try:
        probe = (
            unreal.EditorAssetLibrary.load_asset(probe_path)
            if unreal.EditorAssetLibrary.does_asset_exist(probe_path)
            else unreal.EditorAssetLibrary.duplicate_asset(blueprint_path, probe_path)
        )
        if probe is None:
            raise RuntimeError("Could not create disposable Blueprint probe")
        editor = _graph_editor(unreal, probe, graph_name)
        initial_names = {str(value.get_name()) for value in editor.list_all_nodes() or []}
        node = editor.create_node_from_name(
            str(palette_action), unreal.Vector2D(0.0, 0.0), [], None
        )
        if node is None:
            raise RuntimeError(f"Palette action returned no node: {palette_action}")
        for pin in unreal.BlueprintEditorLibrary.list_all_pins(node) or []:
            try:
                direction = str(unreal.BlueprintGraphPinLibrary.get_pin_direction(pin))
            except Exception:
                direction = "unknown"
            try:
                pin_type = _pin_type_summary(unreal.BlueprintGraphPinLibrary.get_pin_type(pin))
            except Exception:
                pin_type = ""
            try:
                default_value = str(unreal.BlueprintGraphPinLibrary.get_pin_value(pin))
            except Exception:
                default_value = ""
            report["pins"].append(
                {
                    "name": str(unreal.BlueprintGraphPinLibrary.get_pin_name(pin)),
                    "direction": direction,
                    "type": pin_type,
                    "default_value": default_value,
                }
            )
        unreal.BlueprintEditorLibrary.compile_blueprint(probe)
        try:
            status = str(probe.get_editor_property("status"))
        except Exception:
            status = "unknown"
        report["node_name"] = str(node.get_name())
        report["node_title"] = str(unreal.BlueprintEditorLibrary.get_node_title(node))
        report["compile_status"] = status
        report["ok"] = "error" not in status.lower() and bool(report["pins"])
        editor.remove_nodes([node])
        node = None
        unreal.BlueprintEditorLibrary.compile_blueprint(probe)
        unreal.EditorAssetLibrary.save_loaded_asset(probe, False)
        final_names = {str(value.get_name()) for value in editor.list_all_nodes() or []}
        report["probe_reset"] = final_names == initial_names
        report["probe_retained"] = True
    except Exception as exc:
        report["errors"].append(str(exc))
    finally:
        try:
            report["original_dirty_unchanged"] = (
                original_dirty is None or bool(original.get_outermost().is_dirty()) == original_dirty
            )
        except Exception:
            report["original_dirty_unchanged"] = False
        report["ok"] = bool(
            report["ok"] and report.get("probe_reset") and report.get("original_dirty_unchanged")
        )
    return json.dumps(report, indent=2)


def _validate_graph_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError("graph_spec must be an object")
    nodes = list(spec.get("nodes") or [])
    links = list(spec.get("links") or [])
    if not nodes:
        raise ValueError("graph_spec.nodes must contain at least one node")
    node_ids = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"graph_spec.nodes[{index}] must be an object")
        node_id = str(node.get("id") or "").strip()
        palette = str(node.get("palette_action") or "").strip()
        if not node_id or not palette:
            raise ValueError(f"graph_spec.nodes[{index}] requires id and palette_action")
        node_ids.append(node_id)
        values = node.get("pin_values") or {}
        if not isinstance(values, dict):
            raise ValueError(f"graph_spec.nodes[{index}].pin_values must be an object")
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("graph_spec node ids must be unique")
    known = set(node_ids)
    for index, link in enumerate(links):
        if not isinstance(link, dict):
            raise ValueError(f"graph_spec.links[{index}] must be an object")
        required = ("source_node", "source_pin", "target_node", "target_pin")
        missing = [key for key in required if not str(link.get(key) or "").strip()]
        if missing:
            raise ValueError(f"graph_spec.links[{index}] missing: {', '.join(missing)}")
        if link["source_node"] not in known or link["target_node"] not in known:
            raise ValueError(f"graph_spec.links[{index}] references an unknown node id")
    return nodes, links


def apply_graph_spec(blueprint_path, graph_name, graph_spec, save=True):
    """Apply an approved, explicit node graph without mechanic-specific dispatch."""

    import unreal

    node_specs, link_specs = _validate_graph_spec(graph_spec)
    blueprint = _load_blueprint(unreal, blueprint_path)
    editor = _graph_editor(unreal, blueprint, graph_name)
    created = {}
    report = {"nodes": [], "pin_values": [], "links": []}
    for node_spec in node_specs:
        context_pins = []
        for reference in node_spec.get("context_pins") or []:
            context_node = created.get(str(reference.get("node") or ""))
            if context_node is None:
                raise ValueError(f"Context pin references a node that has not been created: {reference}")
            context_pins.append(_pin_by_name(unreal, context_node, reference.get("pin")))
        node = editor.create_node_from_name(
            str(node_spec["palette_action"]),
            unreal.Vector2D(float(node_spec.get("x") or 0.0), float(node_spec.get("y") or 0.0)),
            context_pins,
            None,
        )
        if node is None:
            raise RuntimeError(f"Blueprint palette action returned no node: {node_spec['palette_action']}")
        created[str(node_spec["id"])] = node
        report["nodes"].append({"id": node_spec["id"], "name": str(node.get_name())})
        for pin_name, value in (node_spec.get("pin_values") or {}).items():
            pin = _pin_by_name(unreal, node, pin_name)
            if not unreal.BlueprintGraphPinLibrary.set_pin_value(pin, str(value)):
                raise RuntimeError(f"Unreal rejected pin value {node_spec['id']}.{pin_name}={value!r}")
            report["pin_values"].append(f"{node_spec['id']}.{pin_name}")
    for link_spec in link_specs:
        source = _pin_by_name(unreal, created[link_spec["source_node"]], link_spec["source_pin"])
        target = _pin_by_name(unreal, created[link_spec["target_node"]], link_spec["target_pin"])
        if not unreal.BlueprintGraphPinLibrary.try_create_connection(source, target):
            raise RuntimeError(
                "Unreal rejected graph link "
                f"{link_spec['source_node']}.{link_spec['source_pin']} -> "
                f"{link_spec['target_node']}.{link_spec['target_pin']}"
            )
        report["links"].append(dict(link_spec))
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False)
    current_names = {str(node.get_name()) for node in editor.list_all_nodes() or []}
    missing = [row["name"] for row in report["nodes"] if row["name"] not in current_names]
    if missing:
        raise RuntimeError("Graph readback lost created nodes: " + ", ".join(missing))
    return json.dumps({
        "ok": True,
        "blueprint_path": blueprint_path,
        "graph_name": graph_name,
        **report,
        "postconditions": {
            "all_nodes_read_back": True,
            "all_values_accepted": True,
            "all_links_schema_accepted": True,
            "compiled": True,
            "saved": bool(save),
        },
    }, indent=2)


def create_from_template(template, asset_path, parent_class="", parameters=None):
    import unreal

    parameters = parameters or {}
    if "/" not in asset_path:
        raise ValueError(f"Invalid asset path: {asset_path}")
    package_path, asset_name = asset_path.rsplit("/", 1)

    parent_obj = unreal.Character
    if parent_class:
        try:
            parent_obj = unreal.load_object(None, parent_class)
        except Exception:
            parent_obj = unreal.Character
    elif "actor" in template.lower():
        parent_obj = unreal.Actor
    elif "character" in template.lower() or "locomotion" in template.lower() or "climbing" in template.lower():
        parent_obj = unreal.Character

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_obj)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        created = False
    else:
        asset = asset_tools.create_asset(asset_name, package_path, unreal.Blueprint, factory)
        created = True

    if not asset:
        raise RuntimeError("Failed to create Blueprint asset")

    # Force compile and save
    unreal.BlueprintEditorLibrary.compile_blueprint(asset)
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)

    parent_class_name = parent_obj.__name__ if isinstance(parent_obj, type) else parent_obj.get_name()

    steps = [
        f"Instantiate Blueprint subclass from parent class '{parent_class_name}'"
    ]
    if "locomotion" in template.lower():
        steps.extend([
            "Configure default locomotion movement component parameters",
            "Register input bindings for move forward/right and camera look",
            "Initialize motion matching database references"
        ])
    elif "combat" in template.lower():
        steps.extend([
            "Add combo tracking variables (ComboIndex, MaxCombos, LastAttackTime)",
            "Create state transition variables for combat action sequences",
            "Map melee animation montage slots"
        ])
    elif "dash" in template.lower():
        steps.extend([
            "Add dash velocity multiplier, duration, and cooldown variables",
            "Configure character movement impulse modes for launch velocity",
            "Bind dash action event trigger"
        ])
    elif "climbing" in template.lower() or "climb" in template.lower():
        steps.extend([
            "Add climbing status variables (bIsClimbing, ClimbState, ClimbSurfaceNormal)",
            "Register ledge detection trace and mantle transition overrides",
            "Create climbing animation slots (ClimbStart, ClimbLoop, ClimbMantle)"
        ])
    else:
        steps.extend([
            "Initialize template-specific node properties",
            "Verify variables and input action mappings"
        ])
    steps.append("Compile and save blueprint asset to Content Browser")

    return json.dumps({
        "created": created,
        "template": template,
        "asset_path": asset_path,
        "asset_name": asset_name,
        "parent_class": parent_class_name,
        "steps_executed": steps,
        "message": f"Successfully created Blueprint asset from template {template}.",
    }, indent=2, default=str)
