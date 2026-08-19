"""Verified Unreal material asset and graph authoring operations."""

from __future__ import annotations

import json

from unreal_tools.assets import load_asset


def _asset_parts(asset_path):
    """
    Gets the package path and asset name.

    :param asset_path: Unreal content path
    :return: package path and asset name
    """
    value = str(asset_path or "").strip().rstrip("/")
    if not value.startswith("/Game/") or "/" not in value[1:]:
        raise ValueError("Material asset path must be below /Game: " + value)
    package_path, asset_name = value.rsplit("/", 1)
    if not asset_name:
        raise ValueError("Material asset name cannot be blank")
    return package_path, asset_name


def _expression_row(unreal, expression):
    """
    Gets a serializable material-expression receipt.

    :param unreal: Unreal Python module
    :param expression: material expression object
    :return: expression receipt
    """
    row = {
        "name": str(expression.get_name()),
        "class_path": str(expression.get_class().get_path_name()),
        "object_path": str(expression.get_path_name()),
    }
    for property_name in ("parameter_name", "default_value"):
        try:
            row[property_name] = expression.get_editor_property(property_name)
        except Exception:
            pass
    return row


def _resolve_expression_class(unreal, class_name):
    """
        Resolves and validates a material-expression class name.

    :param unreal: Unreal Python module
    :param class_name: short Unreal material-expression class name
    :return: validated material-expression class
    """
    name = str(class_name or "").strip().rsplit(".", 1)[-1]
    if not name.startswith("MaterialExpression"):
        raise ValueError("Expression classes must start with MaterialExpression: " + name)
    expression_class = getattr(unreal, name, None)
    if expression_class is None or not isinstance(expression_class, type):
        raise ValueError("Unknown material-expression class: " + name)
    if not issubclass(expression_class, unreal.MaterialExpression):
        raise ValueError("Class is not a MaterialExpression: " + name)
    return expression_class


def _coerce_editor_value(unreal, current_value, value):
    """
        Coerces JSON-compatible data to the reflected property's Unreal type.

    :param unreal: Unreal Python module
    :param current_value: current reflected property value
    :param value: JSON-compatible requested value
    :return: value suitable for set_editor_property
    """
    if value is None:
        return None
    value_type = type(current_value)
    type_name = value_type.__name__
    if isinstance(value, str) and value.startswith("/Game/"):
        loaded = unreal.EditorAssetLibrary.load_asset(value)
        if loaded is not None:
            return loaded
    if type_name == "Name":
        return unreal.Name(str(value))
    if type_name == "LinearColor":
        values = list(value)
        if len(values) == 3:
            values.append(1.0)
        if len(values) != 4:
            raise ValueError("LinearColor values must contain RGB or RGBA")
        return unreal.LinearColor(*(float(item) for item in values))
    if type_name == "Vector2D":
        values = list(value)
        if len(values) != 2:
            raise ValueError("Vector2D values must contain two numbers")
        return unreal.Vector2D(*(float(item) for item in values))
    if type_name in {"Vector", "Vector4", "Rotator"}:
        values = list(value)
        expected = 4 if type_name == "Vector4" else 3
        if len(values) != expected:
            raise ValueError(f"{type_name} values must contain {expected} numbers")
        return getattr(unreal, type_name)(*(float(item) for item in values))
    if isinstance(value, str):
        enum_value = getattr(value_type, value, None)
        if enum_value is not None:
            return enum_value
    if isinstance(current_value, bool):
        return bool(value)
    if isinstance(current_value, int):
        return int(value)
    if isinstance(current_value, float):
        return float(value)
    if isinstance(current_value, str):
        return str(value)
    return value


def inspect_material(asset_path):
    """
    Inspects a material graph and its material-property inputs.

    :param asset_path: Unreal material content path
    :return: JSON inspection receipt
    """
    import unreal

    material = load_asset(unreal, asset_path)
    if material is None or not isinstance(material, unreal.Material):
        return json.dumps({"ok": False, "asset_path": asset_path, "status": "material_not_found"}, indent=2)
    library = unreal.MaterialEditingLibrary
    expressions = list(library.get_material_expressions(material) or [])
    properties = {}
    for enum_name in (
        "MP_BASE_COLOR",
        "MP_METALLIC",
        "MP_ROUGHNESS",
        "MP_EMISSIVE_COLOR",
        "MP_NORMAL",
        "MP_OPACITY",
        "MP_OPACITY_MASK",
    ):
        material_property = getattr(unreal.MaterialProperty, enum_name, None)
        if material_property is None:
            continue
        node = library.get_material_property_input_node(material, material_property)
        properties[enum_name] = {
            "connected": node is not None,
            "expression": str(node.get_name()) if node else "",
            "output": str(library.get_material_property_input_node_output_name(material, material_property) or ""),
        }
    return json.dumps({
        "ok": True,
        "asset_path": asset_path,
        "class_path": str(material.get_class().get_path_name()),
        "expression_count": len(expressions),
        "expressions": [_expression_row(unreal, expression) for expression in expressions],
        "property_inputs": properties,
    }, indent=2, default=str)


def create_material(asset_path, overwrite=False, dry_run=False):
    """
    Creates a blank Material asset with save and registry readback.

    :param asset_path: destination Unreal material content path
    :param overwrite: whether to delete the exact existing asset first
    :param dry_run: whether to validate without mutation
    :return: JSON creation receipt
    """
    import unreal

    package_path, asset_name = _asset_parts(asset_path)
    exists_before = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
    if dry_run:
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_path": asset_path,
            "exists_before": exists_before,
            "would_overwrite": bool(exists_before and overwrite),
        }, indent=2)
    if exists_before and not overwrite:
        material = load_asset(unreal, asset_path)
        if material is None or not isinstance(material, unreal.Material):
            raise ValueError("Existing asset is not a Material: " + asset_path)
        receipt = json.loads(inspect_material(asset_path))
        receipt.update({"created": False, "status": "already_exists"})
        return json.dumps(receipt, indent=2, default=str)
    if exists_before and overwrite and not unreal.EditorAssetLibrary.delete_asset(asset_path):
        raise RuntimeError("Could not delete exact existing material: " + asset_path)
    material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name,
        package_path,
        unreal.Material,
        unreal.MaterialFactoryNew(),
    )
    if material is None:
        raise RuntimeError("Unreal failed to create Material: " + asset_path)
    saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(material, False))
    exists_after = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
    if not saved or not exists_after:
        raise RuntimeError("Material failed save/readback: " + asset_path)
    return json.dumps({
        "ok": True,
        "status": "created_and_saved",
        "asset_path": asset_path,
        "created": True,
        "saved": saved,
        "exists_after": exists_after,
    }, indent=2)


def create_parameterized_pbr_material(
    asset_path,
    base_color=(0.18, 0.35, 0.8, 1.0),
    roughness=0.5,
    metallic=0.0,
    overwrite=False,
    dry_run=False,
    cleanup_on_failure=True,
):
    """
    Creates a parameterized PBR Material and verifies its graph connections.

    :param asset_path: destination Unreal material content path
    :param base_color: RGBA default for BaseColor
    :param roughness: scalar roughness default
    :param metallic: scalar metallic default
    :param overwrite: whether to replace the exact existing asset
    :param dry_run: whether to validate without mutation
    :param cleanup_on_failure: whether to delete a newly created failed asset
    :return: JSON graph-authoring receipt
    """
    import unreal

    if not 0.0 <= float(roughness) <= 1.0:
        raise ValueError("roughness must be between 0 and 1")
    if not 0.0 <= float(metallic) <= 1.0:
        raise ValueError("metallic must be between 0 and 1")
    color_values = list(base_color)
    if len(color_values) not in (3, 4):
        raise ValueError("base_color must contain RGB or RGBA values")
    if len(color_values) == 3:
        color_values.append(1.0)
    if dry_run:
        _asset_parts(asset_path)
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_path": asset_path,
            "parameters": {"base_color": color_values, "roughness": roughness, "metallic": metallic},
        }, indent=2)

    existed_before = bool(unreal.EditorAssetLibrary.does_asset_exist(asset_path))
    create_receipt = json.loads(create_material(asset_path, overwrite=overwrite))
    created = bool(create_receipt.get("created"))
    if existed_before and not overwrite:
        raise ValueError("Refusing to append a generated graph to an existing Material: " + asset_path)
    material = load_asset(unreal, asset_path)
    library = unreal.MaterialEditingLibrary
    try:
        color = library.create_material_expression(
            material, unreal.MaterialExpressionVectorParameter, -420, -80
        )
        color.set_editor_property("parameter_name", "BaseColor")
        color.set_editor_property(
            "default_value", unreal.LinearColor(*(float(value) for value in color_values))
        )
        rough = library.create_material_expression(
            material, unreal.MaterialExpressionScalarParameter, -420, 80
        )
        rough.set_editor_property("parameter_name", "Roughness")
        rough.set_editor_property("default_value", float(roughness))
        metal = library.create_material_expression(
            material, unreal.MaterialExpressionScalarParameter, -420, 220
        )
        metal.set_editor_property("parameter_name", "Metallic")
        metal.set_editor_property("default_value", float(metallic))
        connections = {
            "MP_BASE_COLOR": bool(library.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)),
            "MP_ROUGHNESS": bool(library.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)),
            "MP_METALLIC": bool(library.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)),
        }
        if not all(connections.values()):
            raise RuntimeError("Material schema rejected one or more PBR property connections")
        library.layout_material_expressions(material)
        library.recompile_material(material)
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(material, False))
        inspection = json.loads(inspect_material(asset_path))
        readback = inspection.get("property_inputs") or {}
        verified = all((readback.get(name) or {}).get("connected") for name in connections)
        if not saved or not verified or int(inspection.get("expression_count") or 0) < 3:
            raise RuntimeError("Material compile/save/graph readback failed")
        return json.dumps({
            "ok": True,
            "status": "graph_created_compiled_saved",
            "asset_path": asset_path,
            "created": created,
            "connections": connections,
            "saved": saved,
            "inspection": inspection,
            "postconditions": {
                "three_parameters_read_back": True,
                "all_properties_connected": True,
                "compiled": True,
                "saved": True,
            },
        }, indent=2, default=str)
    except Exception:
        if created and cleanup_on_failure and unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            unreal.EditorAssetLibrary.delete_asset(asset_path)
        raise


def create_material_from_spec(
    asset_path,
    nodes,
    connections=None,
    outputs=None,
    material_domain="MD_SURFACE",
    material_properties=None,
    overwrite=False,
    dry_run=False,
    cleanup_on_failure=True,
):
    """
        Creates, connects, compiles, saves, and verifies a Material graph specification.

    :param asset_path: destination Unreal material content path
    :param nodes: expression nodes with id, expression_class, position, and properties
    :param connections: expression-to-expression connections
    :param outputs: expression-to-MaterialProperty connections
    :param material_domain: Unreal MaterialDomain enum name
    :param material_properties: additional reflected Material properties
    :param overwrite: whether to replace the exact existing asset
    :param dry_run: whether to validate the graph specification without mutation
    :param cleanup_on_failure: whether to delete a newly created failed asset
    :return: JSON graph-authoring and readback receipt
    """
    import unreal

    node_specs = list(nodes or [])
    connection_specs = list(connections or [])
    output_specs = list(outputs or [])
    if not node_specs:
        raise ValueError("At least one material expression node is required")
    normalized_nodes = []
    node_classes = {}
    for index, raw_node in enumerate(node_specs):
        if not isinstance(raw_node, dict):
            raise ValueError("Material nodes must be objects")
        node_id = str(raw_node.get("id") or f"node_{index + 1}").strip()
        if not node_id or node_id in node_classes:
            raise ValueError("Material node ids must be non-empty and unique: " + node_id)
        expression_class = _resolve_expression_class(
            unreal, raw_node.get("expression_class") or raw_node.get("class")
        )
        node_classes[node_id] = expression_class
        position = list(raw_node.get("position") or (index * 240 - 480, 0))
        if len(position) != 2:
            raise ValueError("Material node positions must contain X and Y")
        properties = raw_node.get("properties") or {}
        if not isinstance(properties, dict):
            raise ValueError("Material node properties must be an object: " + node_id)
        normalized_nodes.append({
            "id": node_id,
            "class": expression_class,
            "class_name": expression_class.__name__,
            "position": [int(position[0]), int(position[1])],
            "properties": dict(properties),
        })

    normalized_connections = []
    for raw_connection in connection_specs:
        if not isinstance(raw_connection, dict):
            raise ValueError("Material connections must be objects")
        source = str(raw_connection.get("source") or "").strip()
        target = str(raw_connection.get("target") or "").strip()
        if source not in node_classes or target not in node_classes:
            raise ValueError(f"Material connection references unknown nodes: {source} -> {target}")
        normalized_connections.append({
            "source": source,
            "source_output": str(raw_connection.get("source_output") or ""),
            "target": target,
            "target_input": str(raw_connection.get("target_input") or ""),
        })

    normalized_outputs = []
    for raw_output in output_specs:
        if not isinstance(raw_output, dict):
            raise ValueError("Material outputs must be objects")
        source = str(raw_output.get("source") or "").strip()
        property_name = str(
            raw_output.get("material_property") or raw_output.get("property") or ""
        ).strip().upper()
        if source not in node_classes:
            raise ValueError("Material output references unknown node: " + source)
        if not property_name.startswith("MP_"):
            property_name = "MP_" + property_name
        if getattr(unreal.MaterialProperty, property_name, None) is None:
            raise ValueError("Unknown Unreal MaterialProperty: " + property_name)
        normalized_outputs.append({
            "source": source,
            "source_output": str(raw_output.get("source_output") or ""),
            "material_property": property_name,
        })
    if not normalized_outputs:
        raise ValueError("At least one material-property output connection is required")

    domain_name = str(material_domain or "MD_SURFACE").strip().upper()
    domain_value = getattr(unreal.MaterialDomain, domain_name, None)
    if domain_value is None:
        raise ValueError("Unknown Unreal MaterialDomain: " + domain_name)
    reflected_material_properties = dict(material_properties or {})
    if dry_run:
        _asset_parts(asset_path)
        return json.dumps({
            "ok": True,
            "status": "dry_run",
            "asset_path": asset_path,
            "material_domain": domain_name,
            "node_count": len(normalized_nodes),
            "connection_count": len(normalized_connections),
            "output_count": len(normalized_outputs),
        }, indent=2)

    create_receipt = json.loads(create_material(asset_path, overwrite=overwrite))
    created = bool(create_receipt.get("created"))
    if not created:
        raise ValueError("Refusing to modify an existing Material without overwrite=True: " + asset_path)
    material = load_asset(unreal, asset_path)
    library = unreal.MaterialEditingLibrary
    expression_by_id = {}
    try:
        material.set_editor_property("material_domain", domain_value)
        for property_name, requested_value in reflected_material_properties.items():
            current_value = material.get_editor_property(str(property_name))
            material.set_editor_property(
                str(property_name),
                _coerce_editor_value(unreal, current_value, requested_value),
            )
        for node in normalized_nodes:
            expression = library.create_material_expression(
                material,
                node["class"],
                node["position"][0],
                node["position"][1],
            )
            if expression is None:
                raise RuntimeError("Unreal failed to create material node: " + node["id"])
            for property_name, requested_value in node["properties"].items():
                current_value = expression.get_editor_property(str(property_name))
                expression.set_editor_property(
                    str(property_name),
                    _coerce_editor_value(unreal, current_value, requested_value),
                )
            expression_by_id[node["id"]] = expression

        connection_receipts = []
        for connection in normalized_connections:
            connected = bool(library.connect_material_expressions(
                expression_by_id[connection["source"]],
                connection["source_output"],
                expression_by_id[connection["target"]],
                connection["target_input"],
            ))
            if not connected:
                raise RuntimeError(
                    "Material schema rejected connection "
                    f"{connection['source']} -> {connection['target']}:{connection['target_input']}"
                )
            connection_receipts.append(dict(connection, connected=True))

        output_receipts = []
        for output in normalized_outputs:
            connected = bool(library.connect_material_property(
                expression_by_id[output["source"]],
                output["source_output"],
                getattr(unreal.MaterialProperty, output["material_property"]),
            ))
            if not connected:
                raise RuntimeError(
                    "Material schema rejected output connection: "
                    + output["material_property"]
                )
            output_receipts.append(dict(output, connected=True))

        library.layout_material_expressions(material)
        library.recompile_material(material)
        saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(material, False))
        inspection = json.loads(inspect_material(asset_path))
        property_inputs = inspection.get("property_inputs") or {}
        outputs_verified = all(
            (property_inputs.get(output["material_property"]) or {}).get("connected")
            for output in normalized_outputs
        )
        verified = (
            saved
            and int(inspection.get("expression_count") or 0) == len(normalized_nodes)
            and outputs_verified
        )
        if not verified:
            raise RuntimeError("Material compile/save/graph readback failed")
        return json.dumps({
            "ok": True,
            "status": "graph_created_compiled_saved",
            "asset_path": asset_path,
            "material_domain": domain_name,
            "nodes": [
                {
                    "id": node["id"],
                    "class_name": node["class_name"],
                    "object_name": str(expression_by_id[node["id"]].get_name()),
                }
                for node in normalized_nodes
            ],
            "connections": connection_receipts,
            "outputs": output_receipts,
            "saved": saved,
            "inspection": inspection,
            "postconditions": {
                "expression_count_matches": True,
                "all_outputs_connected": True,
                "compiled": True,
                "saved": True,
            },
        }, indent=2, default=str)
    except Exception:
        if created and cleanup_on_failure and unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            unreal.EditorAssetLibrary.delete_asset(asset_path)
        raise
