"""Maya-hosted extraction of an ordered rig DAG and plug-level dependency graph."""

from __future__ import annotations

from typing import Any


PORTABLE_NODE_TYPES = {
    "transform": "dag.transform",
    "joint": "dag.joint",
    "mesh": "geometry.mesh",
    "nurbsCurve": "control.curve",
    "nurbsSurface": "geometry.nurbs_surface",
    "dagPose": "binding.pose",
    "groupId": "deformation.component_group_id",
    "groupParts": "deformation.component_group",
    "parentConstraint": "constraint.parent",
    "pointConstraint": "constraint.point",
    "orientConstraint": "constraint.orient",
    "scaleConstraint": "constraint.scale",
    "aimConstraint": "constraint.aim",
    "poleVectorConstraint": "constraint.pole_vector",
    "geometryConstraint": "constraint.geometry",
    "normalConstraint": "constraint.normal",
    "tangentConstraint": "constraint.tangent",
    "ikHandle": "solver.ik_handle",
    "ikEffector": "solver.ik_effector",
    "ikRPsolver": "solver.ik_rotate_plane",
    "ikSCsolver": "solver.ik_single_chain",
    "ikSplineSolver": "solver.ik_spline",
    "motionPath": "path.motion",
    "follicle": "surface.follicle",
    "pointOnSurfaceInfo": "surface.sample",
    "closestPointOnSurface": "surface.closest_point",
    "curveInfo": "curve.info",
    "pointOnCurveInfo": "curve.sample",
    "nearestPointOnCurve": "curve.closest_point",
    "multiplyDivide": "math.multiply_divide_power",
    "plusMinusAverage": "math.sum_subtract_average",
    "unitConversion": "math.unit_conversion",
    "reverse": "math.one_minus",
    "clamp": "math.clamp",
    "condition": "math.condition",
    "blendWeighted": "math.weighted_blend",
    "pairBlend": "transform.pair_blend",
    "remapValue": "math.remap",
    "choice": "logic.choice",
    "blendColors": "math.blend",
    "multMatrix": "matrix.multiply",
    "inverseMatrix": "matrix.inverse",
    "composeMatrix": "matrix.compose",
    "decomposeMatrix": "matrix.decompose",
    "pickMatrix": "matrix.pick",
    "fourByFourMatrix": "matrix.literal",
    "wtAddMatrix": "matrix.weighted_add",
    "addMatrix": "matrix.add",
    "quatToEuler": "rotation.quaternion_to_euler",
    "eulerToQuat": "rotation.euler_to_quaternion",
    "skinCluster": "deformer.skin",
    "blendShape": "deformer.blend_shape",
    "cluster": "deformer.cluster",
    "wire": "deformer.wire",
    "ffd": "deformer.lattice",
    "wrap": "deformer.wrap",
    "deltaMush": "deformer.delta_mush",
    "tension": "deformer.tension",
    "sculpt": "deformer.sculpt",
    "softMod": "deformer.soft_mod",
    "nonLinear": "deformer.nonlinear",
    "time": "animation.time",
}

LOCALLY_PORTABLE_SOURCE_TYPES = {
    "transform", "joint", "parentConstraint", "pointConstraint", "orientConstraint",
    "scaleConstraint", "aimConstraint", "poleVectorConstraint", "multiplyDivide",
    "plusMinusAverage", "unitConversion", "reverse", "clamp", "condition",
    "blendWeighted", "pairBlend", "remapValue", "choice", "blendColors", "multMatrix",
    "inverseMatrix", "composeMatrix", "decomposeMatrix", "pickMatrix", "fourByFourMatrix",
    "wtAddMatrix", "addMatrix", "quatToEuler", "eulerToQuat", "motionPath",
}

EXCLUDED_SOURCE_TYPES = {
    "shadingEngine", "materialInfo", "file", "place2dTexture", "place3dTexture",
    "lambert", "blinn", "phong", "phongE", "standardSurface", "aiStandardSurface",
    "displayLayer", "displayLayerManager", "renderLayer", "renderLayerManager",
    "lightLinker", "defaultLightList", "colorManagementGlobals", "camera",
}


def extract_rig_topology(
    target_native_ids: list[str] | tuple[str, ...],
    *,
    max_nodes: int = 6000,
    max_connections: int = 30000,
    include_attribute_values: bool = False,
    cmds_module: Any = None,
) -> dict[str, Any]:
    """Extract relevant upstream rig data once; no part of this runs per frame."""
    import time

    extraction_started = time.perf_counter()
    phase_started = extraction_started
    timings_ms: dict[str, float] = {}

    def mark_phase(name: str) -> None:
        nonlocal phase_started
        now = time.perf_counter()
        timings_ms[name] = round((now - phase_started) * 1000.0, 3)
        phase_started = now

    if cmds_module is None:
        import maya.cmds as cmds_module  # type: ignore

    cmds = cmds_module
    max_nodes = max(1, int(max_nodes))
    max_connections = max(1, int(max_connections))
    nodes: set[str] = set()
    truncated = False
    canonical_cache: dict[str, str] = {}
    node_type_cache: dict[str, str] = {}
    inherited_type_cache: dict[str, set[str]] = {}
    try:
        scene_dag_nodes = [str(item) for item in (cmds.ls(dag=True, long=True) or [])]
    except Exception:
        scene_dag_nodes = []
    dag_aliases: dict[str, Any] = {}
    for full_path in scene_dag_nodes:
        for alias in {full_path, full_path.rsplit("|", 1)[-1]}:
            previous = dag_aliases.get(alias)
            dag_aliases[alias] = full_path if previous in (None, full_path) and alias not in dag_aliases else (
                full_path if previous == full_path else None
            )
    canonical_cache.update({alias: path for alias, path in dag_aliases.items() if path})
    canonical_cache.update({path: path for path in scene_dag_nodes})
    mark_phase("dag_index")

    def canonical(node: str) -> str:
        if not node:
            return ""
        text = str(node)
        cached = canonical_cache.get(text)
        if cached is not None:
            return cached
        if text.startswith("|"):
            canonical_cache[text] = text
            return text
        if "|" not in text and text not in dag_aliases:
            # Dependency nodes have globally unique names in Maya. Unique DAG leaf aliases
            # were pre-indexed above, so this avoids one cmds.ls call per DG plug.
            canonical_cache[text] = text
            return text
        try:
            matches = cmds.ls(text, long=True) or cmds.ls(text) or []
            result = str(matches[0]) if matches else text
        except Exception:
            result = text
        canonical_cache[text] = result
        canonical_cache[result] = result
        return result

    def source_type(node: str) -> str:
        native_id = canonical(node)
        cached = node_type_cache.get(native_id)
        if cached is not None:
            return cached
        try:
            cached = str(cmds.nodeType(native_id) or "unknown")
        except Exception:
            cached = "unknown"
        node_type_cache[native_id] = cached
        return cached

    def populate_source_types(node_ids: list[str]) -> None:
        for start in range(0, len(node_ids), 512):
            chunk = node_ids[start:start + 512]
            try:
                values = list(cmds.ls(chunk, showType=True, long=True) or [])
            except Exception:
                values = []
            for index in range(0, len(values) - 1, 2):
                native_id = canonical(str(values[index]))
                node_type_cache[native_id] = str(values[index + 1] or "unknown")

    def inherited_types(node: str) -> set[str]:
        native_id = canonical(node)
        cached = inherited_type_cache.get(native_id)
        if cached is not None:
            return cached
        try:
            cached = set(cmds.nodeType(native_id, inherited=True) or [])
        except Exception:
            cached = set()
        inherited_type_cache[native_id] = cached
        return cached

    def plug_parts(plug: str) -> tuple[str, str]:
        text = str(plug or "")
        if "." not in text:
            return canonical(text), ""
        node, attribute = text.split(".", 1)
        return canonical(node), attribute

    def add_node(node: str) -> bool:
        nonlocal truncated
        native_id = canonical(node)
        if not native_id or native_id in nodes:
            return False
        if len(nodes) >= max_nodes:
            truncated = True
            return False
        nodes.add(native_id)
        return True

    def add_ancestors(node: str) -> list[str]:
        added: list[str] = []
        current = canonical(node)
        while current:
            if current.startswith("|"):
                current = current.rsplit("|", 1)[0]
                if not current:
                    break
            else:
                parents = cmds.listRelatives(current, parent=True, fullPath=True) or []
                if not parents:
                    break
                current = canonical(parents[0])
            if add_node(current):
                added.append(current)
        return added

    def incoming_pairs(batch: list[str]) -> list[str]:
        if not batch:
            return []
        try:
            return list(cmds.listConnections(
                batch,
                connections=True,
                plugs=True,
                source=True,
                destination=False,
                skipConversionNodes=False,
            ) or [])
        except Exception:
            result: list[str] = []
            for node in batch:
                try:
                    result.extend(cmds.listConnections(
                        node,
                        connections=True,
                        plugs=True,
                        source=True,
                        destination=False,
                        skipConversionNodes=False,
                    ) or [])
                except Exception:
                    pass
            return result

    for target in target_native_ids:
        if not target or not cmds.objExists(target):
            continue
        target = canonical(target)
        add_node(target)
        add_ancestors(target)
        for shape in cmds.listRelatives(target, shapes=True, fullPath=True) or []:
            add_node(shape)
        for history_node in cmds.listHistory(target, pruneDagObjects=False) or []:
            add_node(history_node)
            try:
                if source_type(history_node) == "skinCluster":
                    for joint in cmds.skinCluster(history_node, q=True, influence=True) or []:
                        add_node(joint)
                        add_ancestors(joint)
            except Exception:
                pass
    mark_phase("seed")

    frontier = list(nodes)
    visited: set[str] = set()
    for _depth in range(64):
        batch = [node for node in frontier if node not in visited]
        if not batch or truncated:
            break
        frontier = []
        visited.update(batch)
        for start in range(0, len(batch), 256):
            chunk = batch[start:start + 256]
            pairs = incoming_pairs(chunk)
            for index in range(0, len(pairs) - 1, 2):
                source_node, _source_attribute = plug_parts(pairs[index + 1])
                if add_node(source_node):
                    frontier.append(source_node)
                    frontier.extend(add_ancestors(source_node))
    mark_phase("upstream_walk")

    # Control shapes carry selectable rig presentation but do not expand the DG walk.
    try:
        curve_shapes = cmds.ls(type="nurbsCurve", long=True, noIntermediate=True) or []
    except Exception:
        curve_shapes = []
    for shape in curve_shapes:
        full_shape = canonical(shape)
        parent = full_shape.rsplit("|", 1)[0] if full_shape.startswith("|") else ""
        if parent in nodes:
            add_node(full_shape)
    mark_phase("control_shapes")

    node_list = sorted(nodes)
    populate_source_types(node_list)
    excluded_nodes = {node for node in node_list if source_type(node) in EXCLUDED_SOURCE_TYPES}
    if excluded_nodes:
        nodes.difference_update(excluded_nodes)
        node_list = [node for node in node_list if node not in excluded_nodes]
    mark_phase("node_types")
    connections: list[dict[str, Any]] = []
    connection_keys: set[tuple[str, str, str, str]] = set()
    for start in range(0, len(node_list), 256):
        chunk = node_list[start:start + 256]
        pairs = incoming_pairs(chunk)
        for index in range(0, len(pairs) - 1, 2):
            target_node, target_attribute = plug_parts(pairs[index])
            source_node, source_attribute = plug_parts(pairs[index + 1])
            if source_node not in nodes or target_node not in nodes:
                continue
            key = (source_node, source_attribute, target_node, target_attribute)
            if key in connection_keys:
                continue
            if len(connections) >= max_connections:
                truncated = True
                break
            connection_keys.add(key)
            source_node_type = source_type(source_node)
            target_node_type = source_type(target_node)
            connection_type = "attribute"
            if source_node_type.endswith("Constraint") or target_node_type.endswith("Constraint"):
                connection_type = "constraint"
            elif source_node_type.startswith("animCurve") or target_node_type.startswith("animCurve"):
                connection_type = "animation"
            elif (
                PORTABLE_NODE_TYPES.get(source_node_type, "").startswith("deformer.")
                or PORTABLE_NODE_TYPES.get(target_node_type, "").startswith("deformer.")
            ):
                connection_type = "deformation"
            connections.append({
                "source_node": source_node,
                "source_attribute": source_attribute,
                "target_node": target_node,
                "target_attribute": target_attribute,
                "connection_type": connection_type,
            })
    mark_phase("connections")

    connected_inputs: dict[str, set[str]] = {}
    for connection in connections:
        connected_inputs.setdefault(connection["target_node"], set()).add(connection["target_attribute"])

    source_order_by_node: dict[str, int] = {}
    try:
        dag_traversal = [canonical(item) for item in scene_dag_nodes]
    except Exception:
        dag_traversal = []
    dag_order = {node: index for index, node in enumerate(dag_traversal)}
    fallback_order = len(dag_order)
    for index, node in enumerate(node_list):
        if node.startswith("|"):
            source_order_by_node[node] = dag_order.get(node, fallback_order + index)

    node_payloads = [
        _node_payload(
            cmds,
            node,
            nodes,
            connected_inputs.get(node, set()),
            source_type(node),
            inherited_types(node) if source_type(node) not in PORTABLE_NODE_TYPES and not source_type(node).startswith("animCurve") else set(),
            source_order_by_node.get(node, 0),
            include_attribute_values=include_attribute_values,
        )
        for node in node_list
    ]
    mark_phase("node_payloads")
    constraints = _constraint_payloads(
        cmds,
        node_list,
        connections,
        canonical,
        node_type_cache,
        include_attribute_values=include_attribute_values,
    )
    mark_phase("constraints")
    timings_ms["total"] = round((time.perf_counter() - extraction_started) * 1000.0, 3)
    return {
        "schema": "tech_connector.maya.rig_topology.v1",
        "provider_id": "maya",
        "scene": str(cmds.file(q=True, sceneName=True) or ""),
        "nodes": node_payloads,
        "connections": connections,
        "constraints": constraints,
        "truncated": bool(truncated),
        "attribute_hydration": "full" if include_attribute_values else "structural",
        "limits": {"max_nodes": max_nodes, "max_connections": max_connections},
        "timings_ms": timings_ms,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        if len(value) == 1 and isinstance(value[0], (list, tuple)):
            return _json_value(value[0])
        return [_json_value(item) for item in value]
    return str(value)


def _attribute_value(cmds: Any, node: str, attribute: str) -> Any:
    if not attribute:
        return None
    try:
        return _json_value(cmds.getAttr(node + "." + attribute))
    except Exception:
        return None


def _node_payload(
    cmds: Any,
    node: str,
    included_nodes: set[str],
    connected_inputs: set[str],
    source_type: str,
    inherited: set[str],
    source_order: int,
    *,
    include_attribute_values: bool,
) -> dict[str, Any]:
    parent = node.rsplit("|", 1)[0] if node.startswith("|") else ""
    if parent not in included_nodes:
        parent = ""

    neutral_type = PORTABLE_NODE_TYPES.get(source_type)
    if not neutral_type and source_type.startswith("animCurve"):
        neutral_type = "animation.curve"
    if not neutral_type:
        neutral_type = "deformer.opaque" if "geometryFilter" in inherited else "source.opaque"

    attributes: dict[str, Any] = {}
    common_attributes: list[str] = []
    if include_attribute_values:
        if source_type in ("transform", "joint"):
            common_attributes.extend((
                "translate", "rotate", "scale", "rotateOrder", "visibility", "inheritsTransform",
                "matrix", "worldMatrix[0]",
            ))
        if source_type == "joint":
            common_attributes.extend(("jointOrient", "rotateAxis", "segmentScaleCompensate", "preferredAngle"))
        common_attributes.extend(sorted(connected_inputs))
        for attribute in dict.fromkeys(common_attributes):
            attributes[attribute] = _attribute_value(cmds, node, attribute)
        if source_type.startswith("animCurve"):
            attributes.update(_animation_curve_attributes(cmds, node))

    attribute_specs: dict[str, Any] = {}
    try:
        user_attributes = cmds.listAttr(node, userDefined=True) or [] if include_attribute_values else []
    except Exception:
        user_attributes = []
    for attribute in user_attributes:
        plug = node + "." + attribute
        try:
            attribute_specs[attribute] = {
                "data_type": str(cmds.getAttr(plug, type=True) or ""),
                "value": _attribute_value(cmds, node, attribute),
                "keyable": bool(cmds.getAttr(plug, keyable=True)),
                "channel_box": bool(cmds.getAttr(plug, channelBox=True)),
                "locked": bool(cmds.getAttr(plug, lock=True)),
            }
        except Exception:
            pass
    return {
        "native_id": node,
        "name": node.split("|")[-1],
        "node_type": neutral_type,
        "source_type": source_type,
        "dag_parent_native_id": parent,
        "source_order": int(source_order),
        "attributes": attributes,
        "attribute_specs": attribute_specs,
        "portable": bool(source_type in LOCALLY_PORTABLE_SOURCE_TYPES or source_type.startswith("animCurve")),
        "evaluation_mode": "source_proxy",
    }


def _animation_curve_attributes(cmds: Any, node: str) -> dict[str, Any]:
    """Capture editable Maya keys and tangent data without depending on OpenMaya."""
    def query(command: str, **kwargs: Any) -> list[Any]:
        try:
            return list(getattr(cmds, command)(node, q=True, **kwargs) or [])
        except Exception:
            return []

    times = query("keyframe", timeChange=True)
    input_domain = "time"
    if not times:
        times = query("keyframe", floatChange=True)
        input_domain = "unitless"
    values = query("keyframe", valueChange=True)
    in_types = query("keyTangent", inTangentType=True)
    out_types = query("keyTangent", outTangentType=True)
    in_angles = query("keyTangent", inAngle=True)
    out_angles = query("keyTangent", outAngle=True)
    in_weights = query("keyTangent", inWeight=True)
    out_weights = query("keyTangent", outWeight=True)
    keys: list[dict[str, Any]] = []
    for index, (frame, value) in enumerate(zip(times, values)):
        in_type = str(in_types[index]) if index < len(in_types) else "auto"
        out_type = str(out_types[index]) if index < len(out_types) else "auto"
        key = {
            "frame": float(frame),
            "value": float(value),
            "interpolation": "constant" if out_type in {"step", "stepnext"} else out_type,
            "in_tangent": in_type,
            "out_tangent": out_type,
        }
        if index < len(in_angles):
            key["in_angle"] = float(in_angles[index])
        if index < len(out_angles):
            key["out_angle"] = float(out_angles[index])
        if index < len(in_weights):
            key["in_weight"] = float(in_weights[index])
        if index < len(out_weights):
            key["out_weight"] = float(out_weights[index])
        keys.append(key)
    weighted = query("keyTangent", weightedTangents=True)
    return {
        "keys": keys,
        "input_domain": input_domain,
        "weighted_tangents": bool(weighted[0]) if weighted else False,
        "pre_infinity": _attribute_value(cmds, node, "preInfinity"),
        "post_infinity": _attribute_value(cmds, node, "postInfinity"),
    }


def _constraint_payloads(
    cmds: Any,
    nodes: list[str],
    connections: list[dict[str, Any]],
    canonical: Any,
    node_types: dict[str, str],
    *,
    include_attribute_values: bool,
) -> list[dict[str, Any]]:
    command_names = {
        "parentConstraint": "parentConstraint",
        "pointConstraint": "pointConstraint",
        "orientConstraint": "orientConstraint",
        "scaleConstraint": "scaleConstraint",
        "aimConstraint": "aimConstraint",
        "poleVectorConstraint": "poleVectorConstraint",
        "geometryConstraint": "geometryConstraint",
        "normalConstraint": "normalConstraint",
        "tangentConstraint": "tangentConstraint",
    }
    result: list[dict[str, Any]] = []
    incoming_by_target: dict[str, list[dict[str, Any]]] = {}
    outgoing_by_source: dict[str, list[dict[str, Any]]] = {}
    for connection in connections:
        incoming_by_target.setdefault(str(connection.get("target_node") or ""), []).append(connection)
        outgoing_by_source.setdefault(str(connection.get("source_node") or ""), []).append(connection)
    for node in nodes:
        source_type = str(node_types.get(node) or "unknown")
        command_name = command_names.get(source_type)
        if not command_name:
            continue
        command = getattr(cmds, command_name)
        if include_attribute_values:
            try:
                targets = command(node, q=True, targetList=True) or []
            except Exception:
                targets = []
            try:
                aliases = command(node, q=True, weightAliasList=True) or []
            except Exception:
                aliases = []
        else:
            targets = []
            aliases = []
            seen_targets: set[str] = set()
            for connection in incoming_by_target.get(node, []):
                if not str(connection.get("target_attribute") or "").startswith("target["):
                    continue
                candidate = str(connection["source_node"] or "")
                if candidate in seen_targets:
                    continue
                try:
                    if node_types.get(candidate) not in ("transform", "joint"):
                        continue
                except Exception:
                    continue
                seen_targets.add(candidate)
                targets.append(candidate)
        target_payloads: list[dict[str, Any]] = []
        for index, target in enumerate(targets):
            alias = str(aliases[index]) if index < len(aliases) else ""
            target_payloads.append({
                "native_id": canonical(target),
                "weight_attribute": alias,
                "weight": _attribute_value(cmds, node, alias) if alias else None,
            })
        driven = ""
        for connection in outgoing_by_source.get(node, []):
            candidate = connection["target_node"]
            try:
                if node_types.get(candidate) in ("transform", "joint"):
                    driven = candidate
                    break
            except Exception:
                pass
        result.append({
            "native_id": node,
            "type": PORTABLE_NODE_TYPES.get(source_type, "constraint.opaque").split(".", 1)[-1],
            "source_type": source_type,
            "targets": target_payloads,
            "driven_native_id": driven,
            "enabled": bool(_attribute_value(cmds, node, "nodeState") != 1) if include_attribute_values else True,
            "evaluation_mode": "source_proxy",
        })
    return result
