"""Blueprint replication configuration and authority-flow inspection."""

from __future__ import annotations

import json


def _json_object(value):
    if isinstance(value, dict):
        return dict(value)
    parsed = json.loads(str(value or "{}"))
    if not isinstance(parsed, dict):
        raise RuntimeError("Expected a JSON object result")
    return parsed


def configure_blueprint_replication(
    blueprint_path,
    replicated_variables=None,
    rep_notify_variables=None,
    server_rpc_functions=None,
    reliable=True,
    save=True,
):
    """Configure replication metadata through the reflected first-party bridge."""
    import unreal

    blueprint = unreal.EditorAssetLibrary.load_asset(str(blueprint_path))
    if not blueprint:
        raise ValueError(f"Blueprint asset not found: {blueprint_path}")
    library = getattr(unreal, "AIStudioBridgeLibrary", None)
    method = getattr(library, "configure_blueprint_replication", None) if library else None
    if not callable(method):
        raise RuntimeError(
            "AIStudioBridge.configure_blueprint_replication is unavailable. "
            "Build and load the current AIStudioBridge plugin before executing this operation."
        )
    result = _json_object(
        method(
            blueprint,
            [str(value) for value in replicated_variables or []],
            [str(value) for value in rep_notify_variables or []],
            [str(value) for value in server_rpc_functions or []],
            bool(reliable),
            bool(save),
        )
    )
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "Blueprint replication configuration failed"))
    return json.dumps(result, indent=2)


def inspect_authority_flow(
    blueprint_path,
    required_variables=None,
    required_server_rpcs=None,
    required_onrep_functions=None,
):
    """Read back graph and generated-class evidence for an authoritative Blueprint flow."""
    import unreal

    from unreal_tools.blueprint import scan_blueprint

    blueprint = unreal.EditorAssetLibrary.load_asset(str(blueprint_path))
    if not blueprint:
        raise ValueError(f"Blueprint asset not found: {blueprint_path}")
    scan = _json_object(scan_blueprint(str(blueprint_path), True, False))
    generated_class = blueprint.generated_class()
    properties = {}
    for name in required_variables or []:
        prop = generated_class.find_property_by_name(str(name)) if generated_class else None
        flags = str(prop.get_property_flags()) if prop and hasattr(prop, "get_property_flags") else ""
        properties[str(name)] = {
            "exists": bool(prop),
            "flags": flags,
            "replicated": "Net" in flags or "Rep" in flags,
        }
    functions = {}
    for name in [*(required_server_rpcs or []), *(required_onrep_functions or [])]:
        function = generated_class.find_function_by_name(str(name)) if generated_class else None
        flags = str(function.get_function_flags()) if function and hasattr(function, "get_function_flags") else ""
        functions[str(name)] = {
            "exists": bool(function),
            "flags": flags,
            "networked": "Net" in flags or str(name).lower().startswith(("server", "multicast", "client")),
        }
    graph_text = json.dumps(scan.get("graphs") or []).lower()
    authority_nodes = [
        value
        for value in ("switch has authority", "has authority", "authority")
        if value in graph_text
    ]
    assertions = {
        "required_variables_exist": all(row["exists"] for row in properties.values()),
        "required_variables_replicated": all(row["replicated"] for row in properties.values()),
        "required_functions_exist": all(row["exists"] for row in functions.values()),
        "authority_check_present": bool(authority_nodes),
        "blueprint_compiles": scan.get("compile_status") == "compiled",
    }
    return json.dumps(
        {
            "ok": bool(assertions) and all(assertions.values()),
            "blueprint_path": str(blueprint_path),
            "assertions": assertions,
            "variables": properties,
            "functions": functions,
            "authority_nodes": authority_nodes,
            "compile_errors": scan.get("compile_errors") or [],
            "errors": [name for name, passed in assertions.items() if not passed],
        },
        indent=2,
    )
