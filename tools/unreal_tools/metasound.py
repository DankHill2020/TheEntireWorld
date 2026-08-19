"""MetaSound graph authoring helpers backed by Unreal's Builder API."""

from __future__ import annotations

import json


def _succeeded(result):
    return "SUCCEEDED" in str(result).upper()


def _builder_node_rows(builder, nodes):
    rows = []
    for node in nodes:
        inputs, input_result = builder.find_node_inputs(node)
        outputs, output_result = builder.find_node_outputs(node)
        input_rows = []
        for handle in inputs:
            name, data_type, result = builder.get_node_input_data(handle)
            input_rows.append({"name": str(name), "data_type": str(data_type), "ok": _succeeded(result)})
        output_rows = []
        for handle in outputs:
            name, data_type, result = builder.get_node_output_data(handle)
            output_rows.append({"name": str(name), "data_type": str(data_type), "ok": _succeeded(result)})
        rows.append({
            "inputs": input_rows,
            "outputs": output_rows,
            "input_query_ok": _succeeded(input_result),
            "output_query_ok": _succeeded(output_result),
        })
    return rows


def _literal_for_value(builder_subsystem, value):
    """
        Creates a MetaSound literal for a JSON-compatible scalar or array.
    :param builder_subsystem: Unreal MetaSound Builder subsystem
    :param value: requested scalar or homogeneous scalar array
    :return: MetaSound literal and literal data type
    """
    is_array = isinstance(value, (list, tuple))
    sample = value[0] if is_array and value else value
    suffix = "_array" if is_array else ""
    if isinstance(sample, bool):
        method = getattr(builder_subsystem, f"create_bool{suffix}_meta_sound_literal")
        payload = list(map(bool, value)) if is_array else bool(value)
    elif isinstance(sample, int) and not isinstance(sample, bool):
        method = getattr(builder_subsystem, f"create_int{suffix}_meta_sound_literal")
        payload = list(map(int, value)) if is_array else int(value)
    elif isinstance(sample, (int, float)):
        method = getattr(builder_subsystem, f"create_float{suffix}_meta_sound_literal")
        payload = list(map(float, value)) if is_array else float(value)
    elif isinstance(sample, str):
        method = getattr(builder_subsystem, f"create_string{suffix}_meta_sound_literal")
        payload = list(map(str, value)) if is_array else str(value)
    else:
        raise TypeError("MetaSound defaults support bool, int, float, string, and their arrays")
    return method(payload)


def create_sine_tone_source(
    asset_path,
    frequency=440.0,
    author="Tech Connector",
    overwrite=False,
    dry_run=False,
    cleanup_on_failure=True,
):
    """
        Authors and serializes a mono MetaSound sine tone source.
    :param asset_path: destination Unreal content path
    :param frequency: oscillator frequency in Hertz
    :param author: MetaSound document author
    :param overwrite: whether to replace the exact existing asset
    :param dry_run: whether to validate without mutation
    :param cleanup_on_failure: whether to delete a newly created failed asset
    :return: JSON builder, connection, save, and graph readback receipt
    """
    import unreal

    value = str(asset_path or "").strip().rstrip("/")
    if not value.startswith("/Game/") or "/" not in value[1:]:
        raise ValueError("MetaSound asset path must be below /Game: " + value)
    package_path, asset_name = value.rsplit("/", 1)
    frequency = float(frequency)
    if frequency <= 0.0 or frequency > 24000.0:
        raise ValueError("MetaSound frequency must be above 0 and at most 24000 Hz")
    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(value))
    if dry_run:
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_path": value,
            "frequency": frequency,
            "exists_before": exists_before,
            "would_overwrite": bool(exists_before and overwrite),
            "node_class": {"namespace": "UE", "name": "Sine", "variant": "Audio"},
        }, indent=2)
    if exists_before and not overwrite:
        raise ValueError("MetaSound asset already exists: " + value)
    if exists_before and not unreal.EditorAssetLibrary.delete_asset(value):
        raise RuntimeError("Could not delete exact existing MetaSound: " + value)

    created = False
    try:
        builder_subsystem = unreal.get_engine_subsystem(unreal.MetaSoundBuilderSubsystem)
        editor_subsystem = unreal.get_editor_subsystem(unreal.MetaSoundEditorSubsystem)
        builder, _on_play, _on_finished, audio_inputs, create_result = (
            builder_subsystem.create_source_builder(
                "TC_" + asset_name,
                unreal.MetaSoundOutputAudioFormat.MONO,
                False,
            )
        )
        if builder is None or not _succeeded(create_result) or len(audio_inputs) != 1:
            raise RuntimeError("Could not create a mono MetaSound Source builder: " + str(create_result))
        class_name = unreal.MetasoundFrontendClassName(
            namespace="UE",
            name="Sine",
            variant="Audio",
        )
        oscillator, add_result = builder.add_node_by_class_name(class_name, 1)
        if not _succeeded(add_result):
            raise RuntimeError("Could not add the registered UE/Sine/Audio node: " + str(add_result))
        frequency_input, frequency_input_result = builder.find_node_input_by_name(
            oscillator, "Frequency"
        )
        audio_output, audio_output_result = builder.find_node_output_by_name(oscillator, "Audio")
        if not _succeeded(frequency_input_result) or not _succeeded(audio_output_result):
            raise RuntimeError("Sine oscillator did not expose Frequency and Audio vertices")
        frequency_literal, literal_type = builder_subsystem.create_float_meta_sound_literal(frequency)
        default_result = builder.set_node_input_default(frequency_input, frequency_literal)
        connection_result = builder.connect_nodes(audio_output, audio_inputs[0])
        if not _succeeded(default_result) or not _succeeded(connection_result):
            raise RuntimeError(
                "MetaSound default/connection failed: "
                + str(default_result) + " / " + str(connection_result)
            )
        editor_subsystem.set_node_location(builder, oscillator, unreal.Vector2D(-250.0, 0.0))
        asset, build_result = editor_subsystem.build_to_asset(
            builder,
            str(author or "Tech Connector"),
            asset_name,
            package_path,
            None,
        )
        created = asset is not None
        if not created or not _succeeded(build_result):
            raise RuntimeError("MetaSound build_to_asset failed: " + str(build_result))
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False))
        exists_after = bool(unreal.EditorAssetLibrary.does_asset_exist(value))
        builder_readback = editor_subsystem.find_or_begin_building(asset)
        asset_builder = builder_readback[0]
        asset_builder_result = builder_readback[1]
        output_connected = bool(asset_builder.node_output_is_connected(audio_output))
        node_rows = _builder_node_rows(builder, [oscillator])
        class_path = str(asset.get_class().get_path_name())
        return json.dumps({
            "ok": bool(saved and exists_after and _succeeded(asset_builder_result)),
            "status": "authored_built_saved",
            "asset_path": value,
            "class_path": class_path,
            "frequency": frequency,
            "literal_type": str(literal_type),
            "builder_results": {
                "create": str(create_result),
                "add_node": str(add_result),
                "set_frequency": str(default_result),
                "connect_audio": str(connection_result),
                "build_to_asset": str(build_result),
                "reopen_builder": str(asset_builder_result),
            },
            "node_count": 1,
            "nodes": node_rows,
            "output_connected": output_connected,
            "saved": saved,
            "exists_after": exists_after,
        }, indent=2, default=str)
    except Exception:
        if created and cleanup_on_failure and unreal.EditorAssetLibrary.does_asset_exist(value):
            unreal.EditorAssetLibrary.delete_asset(value)
        raise


def create_source_from_spec(
    asset_path,
    nodes,
    connections,
    author="Tech Connector",
    overwrite=False,
    dry_run=False,
    cleanup_on_failure=True,
):
    """
        Creates a mono MetaSound Source from registered nodes and named vertices.
    :param asset_path: destination Unreal content path
    :param nodes: registered node specifications with ids, class names, inputs, and locations
    :param connections: source-node/output to target-node/input specifications
    :param author: MetaSound document author
    :param overwrite: whether to replace the exact existing asset
    :param dry_run: whether to validate the request without mutation
    :param cleanup_on_failure: whether to delete a newly created failed asset
    :return: JSON Builder results, graph structure, save state, and readback
    """
    import unreal

    value = str(asset_path or "").strip().rstrip("/")
    if not value.startswith("/Game/") or "/" not in value[1:]:
        raise ValueError("MetaSound asset path must be below /Game: " + value)
    package_path, asset_name = value.rsplit("/", 1)
    node_specs = list(nodes or [])
    connection_specs = list(connections or [])
    if not node_specs:
        raise ValueError("MetaSound graph specification requires at least one node")
    prepared = []
    identifiers = set()
    for spec in node_specs:
        if not isinstance(spec, dict):
            raise TypeError("MetaSound node specifications must be dictionaries")
        identifier = str(spec.get("id") or "").strip()
        marker = identifier.casefold()
        if not identifier or marker in identifiers or marker == "output":
            raise ValueError("MetaSound node ids must be non-empty, unique, and not 'output'")
        identifiers.add(marker)
        class_spec = dict(spec.get("class") or {})
        namespace = str(class_spec.get("namespace") or "").strip()
        name = str(class_spec.get("name") or "").strip()
        variant = str(class_spec.get("variant") or "").strip()
        if not namespace or not name:
            raise ValueError(f"MetaSound node {identifier!r} requires class namespace and name")
        major_version = int(class_spec.get("major_version", 1))
        inputs = dict(spec.get("inputs") or {})
        location = list(spec.get("location") or [len(prepared) * -250.0, 0.0])
        if len(location) != 2:
            raise ValueError("MetaSound node location must contain x and y")
        prepared.append({
            "id": identifier,
            "class": (namespace, name, variant, major_version),
            "inputs": inputs,
            "location": location,
        })
    endpoints = identifiers | {"output"}
    for connection in connection_specs:
        if not isinstance(connection, dict):
            raise TypeError("MetaSound connection specifications must be dictionaries")
        source = str(connection.get("source") or "").casefold()
        target = str(connection.get("target") or "").casefold()
        if source not in identifiers or target not in endpoints:
            raise ValueError(f"MetaSound connection references an unknown endpoint: {source} -> {target}")
        if not str(connection.get("source_pin") or ""):
            raise ValueError("MetaSound connections require source_pin")
        if target != "output" and not str(connection.get("target_pin") or ""):
            raise ValueError("MetaSound node connections require target_pin")

    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(value))
    if dry_run:
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_path": value,
            "node_count": len(prepared),
            "connection_count": len(connection_specs),
            "exists_before": exists_before,
            "would_overwrite": bool(exists_before and overwrite),
        }, indent=2)
    if exists_before and not overwrite:
        raise ValueError("MetaSound asset already exists: " + value)
    if exists_before and not unreal.EditorAssetLibrary.delete_asset(value):
        raise RuntimeError("Could not delete exact existing MetaSound: " + value)

    created = False
    try:
        builder_subsystem = unreal.get_engine_subsystem(unreal.MetaSoundBuilderSubsystem)
        editor_subsystem = unreal.get_editor_subsystem(unreal.MetaSoundEditorSubsystem)
        builder, _on_play, _on_finished, audio_inputs, create_result = (
            builder_subsystem.create_source_builder(
                "TC_" + asset_name,
                unreal.MetaSoundOutputAudioFormat.MONO,
                False,
            )
        )
        if builder is None or not _succeeded(create_result) or len(audio_inputs) != 1:
            raise RuntimeError("Could not create a mono MetaSound Source builder: " + str(create_result))
        authored = {}
        results = {"create": str(create_result), "nodes": [], "connections": []}
        for spec in prepared:
            namespace, name, variant, major_version = spec["class"]
            class_name = unreal.MetasoundFrontendClassName(
                namespace=namespace,
                name=name,
                variant=variant,
            )
            node, add_result = builder.add_node_by_class_name(class_name, major_version)
            if not _succeeded(add_result):
                raise RuntimeError(
                    f"Could not add registered MetaSound node {namespace}/{name}/{variant}: {add_result}"
                )
            authored[spec["id"].casefold()] = node
            input_results = []
            for input_name, requested in spec["inputs"].items():
                handle, find_result = builder.find_node_input_by_name(node, str(input_name))
                if not _succeeded(find_result):
                    raise ValueError(
                        f"MetaSound node {spec['id']!r} has no input named {input_name!r}"
                    )
                literal, literal_type = _literal_for_value(builder_subsystem, requested)
                default_result = builder.set_node_input_default(handle, literal)
                if not _succeeded(default_result):
                    raise RuntimeError(
                        f"Could not set {spec['id']}.{input_name}: {default_result}"
                    )
                input_results.append({
                    "name": str(input_name),
                    "literal_type": str(literal_type),
                    "result": str(default_result),
                })
            editor_subsystem.set_node_location(
                builder,
                node,
                unreal.Vector2D(float(spec["location"][0]), float(spec["location"][1])),
            )
            results["nodes"].append({
                "id": spec["id"],
                "class": {"namespace": namespace, "name": name, "variant": variant},
                "add_result": str(add_result),
                "input_results": input_results,
            })
        connected_outputs = []
        for connection in connection_specs:
            source_node = authored[str(connection["source"]).casefold()]
            output_handle, output_result = builder.find_node_output_by_name(
                source_node,
                str(connection["source_pin"]),
            )
            if not _succeeded(output_result):
                raise ValueError(
                    f"MetaSound node {connection['source']!r} has no output "
                    f"named {connection['source_pin']!r}"
                )
            target_id = str(connection["target"]).casefold()
            if target_id == "output":
                input_handle = audio_inputs[0]
                input_result = "output interface"
            else:
                target_node = authored[target_id]
                input_handle, input_result = builder.find_node_input_by_name(
                    target_node,
                    str(connection["target_pin"]),
                )
                if not _succeeded(input_result):
                    raise ValueError(
                        f"MetaSound node {connection['target']!r} has no input "
                        f"named {connection['target_pin']!r}"
                    )
            connect_result = builder.connect_nodes(output_handle, input_handle)
            if not _succeeded(connect_result):
                raise RuntimeError("MetaSound connection failed: " + str(connect_result))
            connected_outputs.append(output_handle)
            results["connections"].append({
                "source": str(connection["source"]),
                "source_pin": str(connection["source_pin"]),
                "target": str(connection["target"]),
                "target_pin": str(connection.get("target_pin") or "Audio"),
                "result": str(connect_result),
            })
        asset, build_result = editor_subsystem.build_to_asset(
            builder,
            str(author or "Tech Connector"),
            asset_name,
            package_path,
            None,
        )
        created = asset is not None
        if not created or not _succeeded(build_result):
            raise RuntimeError("MetaSound build_to_asset failed: " + str(build_result))
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(asset, False))
        reopened_builder, reopen_result = editor_subsystem.find_or_begin_building(asset)
        output_connections = [
            bool(reopened_builder.node_output_is_connected(handle))
            for handle in connected_outputs
        ]
        return json.dumps({
            "ok": bool(saved and _succeeded(reopen_result) and all(output_connections)),
            "status": "authored_built_saved",
            "asset_path": value,
            "class_path": str(asset.get_class().get_path_name()),
            "node_count": len(prepared),
            "connection_count": len(connection_specs),
            "builder_results": results,
            "build_result": str(build_result),
            "reopen_result": str(reopen_result),
            "output_connections": output_connections,
            "saved": saved,
            "exists_after": bool(unreal.EditorAssetLibrary.does_asset_exist(value)),
        }, indent=2, default=str)
    except Exception:
        if created and cleanup_on_failure and unreal.EditorAssetLibrary.does_asset_exist(value):
            unreal.EditorAssetLibrary.delete_asset(value)
        raise
