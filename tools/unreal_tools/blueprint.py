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


def _compile_and_save(unreal, blueprint, save):
    compiled = unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if compiled is False:
        raise RuntimeError("Blueprint compilation failed")
    status = ""
    try:
        status = str(blueprint.get_editor_property("status"))
    except Exception:
        pass
    if "error" in status.lower():
        raise RuntimeError("Blueprint compilation reported errors: " + status)
    saved = False
    if save:
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False))
        if not saved:
            raise RuntimeError("Blueprint save failed")
    return {"compiled": True, "compile_status": status, "saved": saved}


def _blueprint_component_rows(unreal, blueprint):
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    if subsystem is None:
        raise RuntimeError("SubobjectDataSubsystem is unavailable")
    library = unreal.SubobjectDataBlueprintFunctionLibrary
    rows = []
    seen = set()
    for handle in subsystem.k2_gather_subobject_data_for_blueprint(blueprint) or []:
        try:
            data = library.get_data(handle)
            if not library.is_component(data):
                continue
            component = library.get_object_for_blueprint(data, blueprint)
            row = {
                "handle": handle,
                "component": component,
                "variable_name": str(library.get_variable_name(data)),
                "display_name": str(library.get_display_name(data)),
                "class_path": str(component.get_class().get_path_name()) if component else "",
                "object_path": str(component.get_path_name()) if component else "",
            }
            identity = (row["variable_name"], row["object_path"])
            if identity in seen:
                continue
            seen.add(identity)
            rows.append(row)
        except Exception:
            continue
    return rows


def _resolve_component_class(unreal, component_class):
    if not isinstance(component_class, str):
        return component_class
    value = str(component_class or "").strip()
    resolved = None
    if value:
        try:
            resolved = unreal.load_class(None, value)
        except Exception:
            pass
    if resolved is None:
        resolved = getattr(unreal, value.rsplit(".", 1)[-1], None)
    if resolved is None:
        raise ValueError("Unreal component class was not found: " + value)
    return resolved


def _unreal_class_path(unreal_class):
    """
    Gets the canonical Unreal class path for a Python class proxy or UClass.

    :param unreal_class: Unreal Python class proxy or reflected UClass
    :return: canonical Unreal class path
    """
    try:
        return str(unreal_class.get_path_name())
    except TypeError:
        pass
    static_class = getattr(unreal_class, "static_class", None)
    if callable(static_class):
        reflected_class = static_class()
        if reflected_class is not None:
            return str(reflected_class.get_path_name())
    raise ValueError("Could not resolve an Unreal class path from: " + repr(unreal_class))


def _set_component_reference(component, unreal, asset_path):
    asset = load_asset(unreal, asset_path)
    if asset is None:
        raise ValueError("Component asset was not found: " + str(asset_path))
    for property_name in ("static_mesh", "skeletal_mesh", "sprite", "material"):
        try:
            if hasattr(component, "has_editor_property") and not component.has_editor_property(property_name):
                continue
            component.set_editor_property(property_name, asset)
            readback = component.get_editor_property(property_name)
            if readback is asset or str(getattr(readback, "get_path_name", lambda: "")()) == str(asset.get_path_name()):
                return property_name
        except Exception:
            continue
    raise RuntimeError("The component exposes no supported asset-reference property")


def add_component(
    blueprint_path,
    component_class,
    component_name,
    asset_path="",
    attach_bone="",
    socket_name="",
    save=True,
):
    """Add and verify a Blueprint-authored component through SubobjectDataSubsystem."""
    import unreal

    blueprint = _load_blueprint(unreal, blueprint_path)
    resolved_class = _resolve_component_class(unreal, component_class)
    resolved_class_path = _unreal_class_path(resolved_class)
    rows = _blueprint_component_rows(unreal, blueprint)
    row = next((item for item in rows if item["variable_name"] == str(component_name)), None)
    created = row is None
    if created:
        subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        handles = list(subsystem.k2_gather_subobject_data_for_blueprint(blueprint) or [])
        if not handles:
            raise RuntimeError("Could not gather Blueprint subobject data")
        params = unreal.AddNewSubobjectParams()
        params.set_editor_property("parent_handle", handles[0])
        params.set_editor_property("new_class", resolved_class)
        params.set_editor_property("blueprint_context", blueprint)
        handle, failure_reason = subsystem.add_new_subobject(params)
        library = unreal.SubobjectDataBlueprintFunctionLibrary
        if not library.is_handle_valid(handle):
            raise RuntimeError("Could not add Blueprint component: " + str(failure_reason))
        if not subsystem.rename_subobject(handle, str(component_name)):
            raise RuntimeError("Could not rename Blueprint component: " + str(component_name))
        rows = _blueprint_component_rows(unreal, blueprint)
        row = next((item for item in rows if item["variable_name"] == str(component_name)), None)
    if row is None or row["component"] is None:
        raise RuntimeError("Blueprint component postcondition readback failed")
    if resolved_class_path not in row["class_path"]:
        raise RuntimeError(
            f"Blueprint component class mismatch: expected {resolved_class_path}, got {row['class_path']}"
        )
    asset_property = _set_component_reference(row["component"], unreal, asset_path) if asset_path else ""
    requested_socket = str(socket_name or attach_bone or "")
    socket_property = ""
    if requested_socket:
        for property_name in ("attach_socket_name", "socket_name"):
            try:
                if hasattr(row["component"], "has_editor_property") and not row["component"].has_editor_property(property_name):
                    continue
                row["component"].set_editor_property(property_name, requested_socket)
                if str(row["component"].get_editor_property(property_name)) == requested_socket:
                    socket_property = property_name
                    break
            except Exception:
                continue
        if not socket_property:
            raise RuntimeError("The component exposes no supported attachment socket property")
    postconditions = _compile_and_save(unreal, blueprint, bool(save))
    verified = next(
        (item for item in _blueprint_component_rows(unreal, blueprint) if item["variable_name"] == str(component_name)),
        None,
    )
    if verified is None or resolved_class_path not in verified["class_path"]:
        raise RuntimeError("Blueprint component did not survive compile/save readback")
    return json.dumps({
        "ok": True,
        "blueprint_path": blueprint_path,
        "component_name": component_name,
        "component_class": resolved_class_path,
        "created": created,
        "asset_property": asset_property,
        "socket_property": socket_property,
        "component": {key: value for key, value in verified.items() if key not in {"handle", "component"}},
        "postconditions": {
            **postconditions,
            "component_readback": True,
            "component_class_match": True,
            "asset_reference_readback": not bool(asset_path) or bool(asset_property),
            "socket_readback": not bool(requested_socket) or bool(socket_property),
        },
    }, indent=2)


def _member_default_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "(" + ",".join(_member_default_text(item) for item in value) + ")"
    return str(value)


def _equivalent_default(expected, actual):
    if isinstance(expected, (list, tuple)):
        return list(expected) == list(actual or [])
    if isinstance(expected, bool):
        return bool(actual) is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    return str(actual) == str(expected)


def create_variable(
    blueprint_path,
    variable_name,
    variable_type,
    is_array=False,
    default_value=None,
    save=True,
):
    """Create a typed Blueprint member variable and verify generated-class readback."""
    import unreal

    blueprint = _load_blueprint(unreal, blueprint_path)
    graph_names = [str(value) for value in unreal.BlueprintEditorLibrary.list_graph_names(blueprint) or []]
    graph_name = "EventGraph" if "EventGraph" in graph_names else (graph_names[0] if graph_names else "")
    if not graph_name:
        raise RuntimeError("Blueprint has no editable graph for member-variable authoring")
    graph = _graph_editor(unreal, blueprint, graph_name)
    existing = {str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint) or []}
    created = str(variable_name) not in existing
    if created:
        pin_type = unreal.BlueprintEditorLibrary.get_basic_type_by_name(str(variable_type))
        if pin_type is None:
            raise ValueError("Unsupported Blueprint variable type: " + str(variable_type))
        if is_array:
            container_enum = getattr(getattr(unreal, "PinContainerType", None), "ARRAY", None)
            if container_enum is None:
                raise RuntimeError("Blueprint array pin types are unavailable in this Unreal build")
            pin_type.set_editor_property("container_type", container_enum)
        if not graph.add_member_variable(
            str(variable_name), pin_type, _member_default_text(default_value)
        ):
            raise RuntimeError("BlueprintGraphEditor rejected member variable: " + str(variable_name))
    postconditions = _compile_and_save(unreal, blueprint, bool(save))
    names = {str(value) for value in unreal.BlueprintEditorLibrary.list_member_variable_names(blueprint) or []}
    if str(variable_name) not in names:
        raise RuntimeError("Blueprint member variable did not survive compile/save readback")
    variable = _variable_row(unreal, blueprint, variable_name)
    default_readback = None
    default_verified = default_value is None
    if default_value is not None:
        try:
            generated_class = blueprint.generated_class()
            default_object = unreal.get_default_object(generated_class)
            default_readback = default_object.get_editor_property(str(variable_name))
            default_verified = _equivalent_default(default_value, default_readback)
        except Exception as exc:
            raise RuntimeError("Blueprint variable default readback failed: " + str(exc)) from exc
        if not default_verified:
            raise RuntimeError(
                f"Blueprint variable default mismatch: expected {default_value!r}, got {default_readback!r}"
            )
    return json.dumps({
        "ok": True,
        "blueprint_path": blueprint_path,
        "variable": variable,
        "is_array": bool(is_array),
        "created": created,
        "default_value": default_readback,
        "postconditions": {
            **postconditions,
            "variable_readback": True,
            "default_readback": default_verified,
        },
    }, indent=2, default=str)


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
        result["components"] = [
            {
                "variable_name": row["variable_name"],
                "display_name": row["display_name"],
                "class_path": row["class_path"],
                "object_path": row["object_path"],
            }
            for row in _blueprint_component_rows(unreal, bp)
        ]
    except Exception as exc:
        result["warnings"].append(f"components unavailable: {exc}")

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



def compile_and_save_blueprint(asset_path):
    """Compile a Blueprint and save it to disk if compilation succeeds."""
    import unreal

    bp = _load_blueprint(unreal, asset_path)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    errors = unreal.BlueprintEditorLibrary.get_compiler_results(bp) if hasattr(
        unreal.BlueprintEditorLibrary, 'get_compiler_results'
    ) else []
    if errors:
        return __import__('json').dumps(
            {
                'ok': False,
                'asset_path': asset_path,
                'compiled': False,
                'errors': list(errors),
                'parity_checks': {'Blueprint compile': False},
            },
            indent=2,
        )
    saved = bool(unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False))
    return __import__('json').dumps(
        {
            'ok': saved,
            'asset_path': asset_path,
            'compiled': True,
            'saved': saved,
            'parity_checks': {'Blueprint compile': bool(saved)},
        },
        indent=2,
    )

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
    for direction, parameters in (("input", inputs or []), ("output", outputs or [])):
        for parameter in parameters:
            if isinstance(parameter, str):
                parameter_name = parameter
                parameter_type = "wildcard"
            elif isinstance(parameter, dict):
                parameter_name = str(parameter.get("name") or "").strip()
                parameter_type = parameter.get("type") or parameter.get("pin_type") or "wildcard"
            else:
                raise ValueError(f"Invalid {direction} parameter specification: {parameter!r}")
            if not parameter_name:
                raise ValueError(f"{direction.title()} parameter name cannot be blank")
            editor_method = getattr(editor, f"add_{direction}_pin", None)
            library_method = getattr(
                unreal.BlueprintEditorLibrary,
                f"add_function_{direction}",
                None,
            )
            if callable(editor_method):
                editor_method(parameter_name, parameter_type)
            elif callable(library_method):
                library_method(blueprint, str(function_name), parameter_name, parameter_type)
            else:
                raise RuntimeError(
                    f"The installed Unreal bridge cannot author typed function {direction}s"
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
        "inputs": list(inputs or []),
        "outputs": list(outputs or []),
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
    """
    Creates or loads a Blueprint and reports only operations actually performed.

    :param template: parent selection hint such as actor or character
    :param asset_path: destination Unreal content path
    :param parent_class: optional explicit Unreal parent class path
    :param parameters: reserved template parameters
    :return: JSON creation and postcondition receipt
    """
    import unreal

    parameters = parameters or {}
    if "/" not in asset_path:
        raise ValueError(f"Invalid asset path: {asset_path}")
    package_path, asset_name = asset_path.rsplit("/", 1)

    parent_obj = unreal.Character
    if parent_class:
        try:
            parent_obj = unreal.load_class(None, parent_class)
        except Exception:
            parent_obj = None
        if parent_obj is None:
            try:
                parent_obj = unreal.load_object(None, parent_class)
            except Exception:
                parent_obj = None
        if parent_obj is None:
            raise ValueError("Unreal parent class was not found: " + str(parent_class))
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

    postconditions = _compile_and_save(unreal, asset, True)
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        raise RuntimeError("Blueprint asset did not survive save readback: " + asset_path)

    parent_class_name = parent_obj.__name__ if isinstance(parent_obj, type) else parent_obj.get_name()

    operations = []
    if created:
        operations.append(f"Created Blueprint subclass of '{parent_class_name}'")
    else:
        operations.append("Loaded existing Blueprint without replacing it")
    operations.extend(("Compiled Blueprint", "Saved Blueprint", "Verified asset path readback"))

    return json.dumps({
        "created": created,
        "template": template,
        "asset_path": asset_path,
        "asset_name": asset_name,
        "parent_class": parent_class_name,
        "operations_performed": operations,
        "steps_executed": operations,
        "parameters_applied": [],
        "parameters_ignored": sorted(str(key) for key in parameters),
        "postconditions": {
            **postconditions,
            "asset_exists": True,
        },
        "message": "Successfully created Blueprint asset." if created else "Blueprint asset already exists.",
    }, indent=2, default=str)
