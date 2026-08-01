"""Deterministic prompt-to-action-graph planner.

This is the rule-router/deterministic-planner layer. It emits a structured
ActionGraph for operations the app can understand without asking an LLM to
invent functions, files, or execution steps.
"""

from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

from reasoning_runtime.action.action_graph_service import ActionGraph, validate_action_graph
from tech_connector.services.workflow_service import resolve_workflow_intent


def _clean_query(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _file_hint(text: str) -> str:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+)\b", text or "")
    return match.group(1) if match else ""


def _function_mentions(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text or ""):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def _looks_like_pipeline_request(text: str) -> bool:
    lower = (text or "").lower()
    # Check for multiple DCC hosts
    hosts = []
    for host in ("maya", "unreal", "blender", "substance_painter", "unity", "motionbuilder"):
        if host in lower or host.replace("_", " ") in lower:
            hosts.append(host)
    if len(hosts) >= 2:
        return True
    return bool(
        re.search(
            r"\b("
            r"pipeline|workflow|node|graph|connected|connection|flow|bind|mapping|maping|bridge|transfer|"
            r"multi[- ]?step|step\s+\d+|chain|chained|sequence|sequential|compose|composer|wire|"
            r"node\s+view|builder|data\s+link|data\s+links|flow\s+link|flow\s+links"
            r")\b",
            lower,
        )
    )


_WORKFLOW_GRAPH_CACHE: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, Any] | None]] = {}
_WORKFLOW_GRAPH_CACHE_TTL_SECONDS = 15.0


def should_route_to_action_graph(prompt: str, project_roots: list[str] | None = None) -> bool:
    """Return True when deterministic action planning should claim a chat prompt."""
    text = _clean_query(prompt)
    if not text:
        return False
    lower = text.lower()
    if _looks_like_pipeline_request(text):
        # Keep this predicate cheap: it runs during UI-thread route classification.
        # Full symbol resolution happens later inside RequestPreparationWorker.
        return True
    file_hint = _file_hint(text)
    if re.search(r"\b(open|show|go to|jump to)\b", lower) and file_hint:
        return True
    if re.search(r"\b(find|search|locate|where is|where are)\b", lower):
        return bool(_function_mentions(text))
    if re.search(r"\b(rebuild|refresh|index)\b", lower) and re.search(r"\b(index|project|repo|repository|codebase|knowledge)\b", lower):
        return True
    if "github" in lower and re.search(r"\b(search|find|ingest|import|install)\b", lower):
        return True
    if re.search(r"\b(refresh)\b", lower) and any(host in lower for host in ("unreal", "maya", "blender")):
        return True
    return False


def _literal_actions(graph: ActionGraph, step: dict[str, Any], node_name: str, node_action_id: str) -> None:
    for param, value in (step.get("literal_values") or {}).items():
        graph.add(
            "bind_literal",
            {"node": node_name, "parameter": param, "value": value},
            depends_on=[node_action_id],
        )


def _deps(*values: str | None) -> list[str]:
    return [value for value in values if value]


def _workflow_plan_to_action_graph(prompt: str, roots: list[str]) -> dict[str, Any] | None:
    cache_key = (_clean_query(prompt).lower(), tuple(sorted(str(Path(root).resolve()) for root in roots if root)))
    cached = _WORKFLOW_GRAPH_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _WORKFLOW_GRAPH_CACHE_TTL_SECONDS:
        return cached[1]

    plan = resolve_workflow_intent(prompt, roots)
    if not plan.get("success"):
        gaps = [dict(item) for item in plan.get("capability_gaps") or []]
        if not gaps:
            _WORKFLOW_GRAPH_CACHE[cache_key] = (now, None)
            return None
        missing_args = [gap for gap in gaps if gap.get("kind") == "missing_required_argument"]
        acquisition_gaps = [gap for gap in gaps if gap.get("kind") != "missing_required_argument"]
        if missing_args and not acquisition_gaps:
            graph = ActionGraph(
                goal=prompt,
                intent="pipeline_missing_required_args",
                confidence=float(plan.get("confidence") or 0.0),
                diagnostics=list(plan.get("diagnostics") or []),
            )
            for gap in missing_args:
                callable_name = gap.get("callable") or str(gap.get("capability") or "callable").split(".", 1)[0]
                argument = gap.get("argument") or str(gap.get("capability") or "").split(".")[-1]
                graph.add(
                    "request_input",
                    {
                        "callable": callable_name,
                        "argument": argument,
                        "capability": gap.get("capability") or f"{callable_name}.{argument}",
                        "question": f"What value should `{argument}` use for `{callable_name}`?",
                        "reason": gap.get("reason") or "A required argument has no default, user value, or discovered producer.",
                    },
                    requires_approval=False,
                )
            data = graph.to_dict()
            data["workflow_plan"] = plan
            data["missing_required_args"] = missing_args
            data["capability_gaps"] = gaps
            data["validation"] = validate_action_graph(data)
            _WORKFLOW_GRAPH_CACHE[cache_key] = (now, data)
            return data
        graph = ActionGraph(
            goal=prompt,
            intent="pipeline_capability_acquisition",
            confidence=float(plan.get("confidence") or 0.0),
            diagnostics=list(plan.get("diagnostics") or []),
        )
        for gap in gaps:
            internal_search = graph.add(
                "search_project",
                {
                    "query": gap.get("capability") or prompt,
                    "reason": gap.get("reason") or "Resolve a missing pipeline callable.",
                },
                requires_approval=False,
            )
            graph.add(
                "github_search",
                {
                    "query": gap.get("capability") or prompt,
                    "limit": 5,
                    "review_required": True,
                    "fallback_only": True,
                    "fallback_reason": "No internal callable or registered capability matched the requested pipeline step.",
                    "internal_search_result": {"from_action": internal_search.id, "result_path": ""},
                },
                depends_on=[internal_search.id],
                requires_approval=False,
            )
        data = graph.to_dict()
        data["workflow_plan"] = plan
        data["capability_gaps"] = gaps
        data["validation"] = validate_action_graph(data)
        _WORKFLOW_GRAPH_CACHE[cache_key] = (now, data)
        return data

    graph = ActionGraph(
        goal=prompt,
        intent="pipeline_graph",
        confidence=float(plan.get("confidence") or 0.0),
        diagnostics=plan.get("diagnostics") or [],
    )

    resolve_ids: dict[int, str] = {}
    node_ids: dict[int, str] = {}
    node_names: dict[int, str] = {}
    for index, step in enumerate(plan.get("steps") or [], start=1):
        symbol = step.get("symbol") or {}
        name = symbol.get("name") or f"step_{index}"
        node_names[index] = name
        resolve = graph.add(
            "resolve_function",
            {
                "query": name,
                "file_hint": Path(symbol.get("file_path", "")).name,
                "symbol": symbol,
            },
            requires_approval=False,
        )
        resolve_ids[index] = resolve.id
        node = graph.add(
            "create_node",
            {
                "node": name,
                "symbol": symbol,
                "params": step.get("params") or [],
                "outputs": step.get("outputs") or [],
            },
            depends_on=[resolve.id],
        )
        node_ids[index] = node.id
        _literal_actions(graph, step, name, node.id)

    for link in plan.get("data_links") or []:
        graph.add(
            "connect_data",
            {
                "from": {
                    "node": node_names.get(int(link.get("from_step") or 0), ""),
                    "port": link.get("from_output") or "result",
                },
                "to": {
                    "node": node_names.get(int(link.get("to_step") or 0), ""),
                    "port": link.get("to_input") or "",
                },
                "reason": link.get("reason") or "",
            },
            depends_on=_deps(node_ids.get(int(link.get("from_step") or 0)), node_ids.get(int(link.get("to_step") or 0))),
        )

    for link in plan.get("flow_links") or []:
        graph.add(
            "connect_flow",
            {
                "from": node_names.get(int(link.get("from_step") or 0), ""),
                "to": node_names.get(int(link.get("to_step") or 0), ""),
                "reason": link.get("reason") or "",
            },
            depends_on=_deps(node_ids.get(int(link.get("from_step") or 0)), node_ids.get(int(link.get("to_step") or 0))),
        )

    graph.add("validate_graph", {"target": "pipeline_node_view"})
    graph.add("generate_python", {"target": "pipeline_graph"})
    data = graph.to_dict()
    data["workflow_plan"] = plan
    data["validation"] = validate_action_graph(data)
    _WORKFLOW_GRAPH_CACHE[cache_key] = (now, data)
    return data


def _blender_to_unreal_prop_action_graph(prompt: str) -> dict[str, Any] | None:
    lower = prompt.lower()
    if not ("blender" in lower and "unreal" in lower):
        return None
    if not re.search(r"\b(prop|mesh|static mesh|lod0|lod1|collision|material slots?|apply transforms?)\b", lower):
        return None

    fbx_match = re.search(r"\b([A-Za-z]:[\\/][^\s,;]+?\.fbx)\b", prompt, re.IGNORECASE)
    dest_match = re.search(r"\b(/Game/[A-Za-z0-9_./-]+)", prompt)
    fbx_path = fbx_match.group(1).replace("\\", "/") if fbx_match else "C:/tmp/tc_prop.fbx"
    destination_path = dest_match.group(1).rstrip(".,;") if dest_match else "/Game/Props/Test"
    blender_code = """import json
import os
import re
import bpy

selected = list(bpy.context.selected_objects)
if not selected:
    selected = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
if not selected:
    raise RuntimeError('No selected mesh objects, and no mesh fallback exists in the Blender scene.')

cleaned = []
for index, obj in enumerate(selected, start=1):
    if obj.type != 'MESH':
        continue
    clean_name = re.sub(r'[^A-Za-z0-9_]+', '_', obj.name).strip('_') or ('Prop_%02d' % index)
    if not clean_name.startswith('SM_'):
        clean_name = 'SM_' + clean_name
    obj.name = clean_name
    obj.data.name = clean_name + '_Mesh'
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if not obj.data.materials:
        material = bpy.data.materials.new(clean_name + '_MAT')
        material.diffuse_color = (0.25, 0.55, 1.0, 1.0)
        obj.data.materials.append(material)
    if not any(mod.name == 'LOD1_Decimate' for mod in obj.modifiers):
        decimate = obj.modifiers.new('LOD1_Decimate', 'DECIMATE')
        decimate.ratio = 0.5
    cleaned.append(obj)

if not cleaned:
    raise RuntimeError('Selection did not contain mesh objects.')

bpy.ops.object.select_all(action='DESELECT')
for obj in cleaned:
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
os.makedirs(os.path.dirname(fbx_path), exist_ok=True)
bpy.ops.export_scene.fbx(filepath=fbx_path, use_selection=True, apply_unit_scale=True, bake_space_transform=False, object_types={'MESH'})
print(json.dumps({'ok': True, 'fbx_path': fbx_path, 'objects': [obj.name for obj in cleaned], 'materials': [slot.material.name for obj in cleaned for slot in obj.material_slots if slot.material]}))"""
    unreal_import_code = """import json
import os
import unreal

if not os.path.exists(fbx_path):
    raise RuntimeError('FBX does not exist on disk: ' + str(fbx_path))
unreal.EditorAssetLibrary.make_directory(destination_path)
task = unreal.AssetImportTask()
task.filename = fbx_path
task.destination_path = destination_path
task.automated = True
task.save = True
task.replace_existing = True
options = unreal.FbxImportUI()
options.import_mesh = True
options.import_as_skeletal = False
options.import_materials = True
options.import_textures = False
try:
    options.static_mesh_import_data.combine_meshes = False
    options.static_mesh_import_data.auto_generate_collision = True
except Exception:
    pass
task.options = options
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
imported_paths = [str(path) for path in task.imported_object_paths]
source_stem = os.path.splitext(os.path.basename(blender_fbx_path))[0]
registry = unreal.AssetRegistryHelpers.get_asset_registry()
registry.scan_paths_synchronous([destination_path], force_rescan=True)
for data in registry.get_assets_by_path(destination_path, recursive=False):
    asset_name = str(data.asset_name)
    class_name = str(data.asset_class_path.asset_name)
    if (
        asset_name == source_stem
        or asset_name.startswith(source_stem + '_')
    ) and class_name in {'SkeletalMesh', 'Skeleton', 'AnimSequence', 'PhysicsAsset'}:
        loaded = data.get_asset()
        candidate = str(loaded.get_path_name()) if loaded else str(data.package_name)
        if candidate not in imported_paths:
            imported_paths.append(candidate)
if not imported_paths:
    raise RuntimeError('Unreal import completed without task or registry object paths.')
for path in imported_paths:
    unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False)
print(json.dumps({'ok': True, 'fbx_path': fbx_path, 'destination_path': destination_path, 'asset_path': imported_paths[0], 'imported_paths': imported_paths}))"""
    unreal_validate_code = """import json
import unreal

registry = unreal.AssetRegistryHelpers.get_asset_registry()
assets = []
for data in registry.get_assets_by_path(destination_path, recursive=True):
    package_name = str(data.package_name)
    if any(str(path).split('.')[0] == package_name for path in imported_paths):
        assets.append({'package_name': package_name, 'asset_name': str(data.asset_name), 'class_path': str(data.asset_class_path.asset_name)})
if not assets:
    raise RuntimeError('Imported assets were not visible in the Unreal asset registry.')
print(json.dumps({'ok': True, 'destination_path': destination_path, 'assets': assets, 'asset_count': len(assets)}))"""

    try:
        from tech_connector.services.dcc.transfer_template_service import plan_transfer_permutation

        transfer_permutation = plan_transfer_permutation(prompt)
    except Exception:
        transfer_permutation = {}

    graph = ActionGraph(
        goal=prompt,
        intent="blender_to_unreal_prop_pipeline",
        confidence=0.92,
        diagnostics=[
            "Matched explicit Blender to Unreal prop/mesh pipeline.",
            "Plan includes Blender cleanup/export, Unreal import/save, and Unreal registry readback.",
        ],
    )
    export = graph.add(
        "execute_dcc",
        {
            "host": "blender",
            "operation": "script.run",
            "callable": "tech_connector.bridges.blender.blender_bridge.BlenderBridge.execute",
            "params": {"code": blender_code, "fbx_path": fbx_path},
            "produces": ["fbx_path", "objects", "materials"],
            "requires": [],
        },
        id="blender_clean_export_fbx",
        title="Blender clean selected meshes and export FBX",
    )
    import_step = graph.add(
        "execute_dcc",
        {
            "host": "unreal",
            "operation": "script.run",
            "callable": "tech_connector.bridges.unreal.unreal_bridge.UnrealBridge.execute_python",
            "params": {"code": unreal_import_code, "fbx_path": "$fbx_path", "destination_path": destination_path},
            "produces": ["asset_path", "imported_paths"],
            "requires": ["fbx_path"],
        },
        depends_on=[export.id],
        id="unreal_import_static_mesh_fbx",
        title="Unreal import static mesh FBX and save assets",
    )
    graph.add(
        "validate_dcc_call",
        {
            "host": "unreal",
            "operation": "script.run",
            "callable": "tech_connector.bridges.unreal.unreal_bridge.UnrealBridge.execute_python",
            "params": {"code": unreal_validate_code, "destination_path": destination_path, "imported_paths": "$imported_paths"},
            "produces": ["assets", "asset_count"],
            "requires": ["imported_paths"],
        },
        depends_on=[import_step.id],
        id="unreal_validate_imported_prop_assets",
        title="Unreal validate imported prop assets",
        requires_approval=False,
    )
    data = graph.to_dict()
    data["transfer_permutation"] = transfer_permutation
    data["validation"] = validate_action_graph(data)
    return data


def _maya_blender_unreal_validation_action_graph(prompt: str) -> dict[str, Any] | None:
    lower = prompt.lower()
    if not all(host in lower for host in ("maya", "blender", "unreal")):
        return None
    if not ("fbx" in lower and re.search(r"\b(pipeline|workflow|then|after|import|export|validation)\b", lower)):
        return None

    fbx_paths = [match.group(1).replace("\\", "/") for match in re.finditer(r"\b([A-Za-z]:[\\/][^\s,;]+?\.fbx)\b", prompt, re.IGNORECASE)]
    maya_fbx_path = fbx_paths[0] if fbx_paths else "C:/tmp/tc_chain_maya.fbx"
    blender_fbx_path = fbx_paths[1] if len(fbx_paths) > 1 else "C:/tmp/tc_chain_blender.fbx"
    dest_match = re.search(r"\b(/Game/[A-Za-z0-9_./-]+)", prompt)
    destination_path = dest_match.group(1).rstrip(".,;") if dest_match else "/Game/AIStudio/Validation/Chain"
    maya_code = """import datetime
import json
import os
import maya.cmds as cmds
import maya.mel as mel

tag = 'TC_PROMPT_CHAIN_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
original_selection = cmds.ls(selection=True, long=True) or []
try:
    cmds.select(clear=True)
    root = cmds.joint(name=tag + '_root_JNT', position=(0, 0, 0))
    spine = cmds.joint(name=tag + '_spine_JNT', position=(0, 4, 0))
    head = cmds.joint(name=tag + '_head_JNT', position=(0, 7, 0))
    mesh = cmds.polyCube(name=tag + '_proxy_GEO', width=1.5, height=5.5, depth=0.75, subdivisionsHeight=6)[0]
    cmds.move(0, 2.75, 0, mesh)
    skin_cluster = cmds.skinCluster([root, spine, head], mesh, name=tag + '_skinCluster', toSelectedBones=True)[0]
    cmds.currentTime(1)
    cmds.setKeyframe(root, attribute='translateX', value=0)
    cmds.currentTime(24)
    cmds.setKeyframe(root, attribute='translateX', value=2)
    cmds.playbackOptions(minTime=1, maxTime=24, animationStartTime=1, animationEndTime=24)
    cmds.select([root, mesh], replace=True)
    selection = cmds.ls(selection=True, long=True) or []

    os.makedirs(os.path.dirname(maya_fbx_path), exist_ok=True)
    if not cmds.pluginInfo('fbxmaya', query=True, loaded=True):
        cmds.loadPlugin('fbxmaya')
    mel.eval('FBXResetExport;')
    mel.eval('FBXExportSkins -v true;')
    mel.eval('FBXExportBakeComplexAnimation -v true;')
    mel.eval('FBXExport -f "{}" -s;'.format(maya_fbx_path.replace('\\\\', '/')))
    key_times = cmds.keyframe(root, attribute='translateX', query=True, timeChange=True) or []
    proof = {
        'generated_tag': tag,
        'joints': cmds.ls([root, spine, head], long=True) or [],
        'mesh': (cmds.ls(mesh, long=True) or [mesh])[0],
        'skin_cluster': skin_cluster,
        'frame_range': [1.0, 24.0],
        'root_translate_x_keys': [float(value) for value in key_times],
        'fbx_exists': os.path.isfile(maya_fbx_path),
        'fbx_bytes': os.path.getsize(maya_fbx_path) if os.path.isfile(maya_fbx_path) else 0,
    }
    if len(proof['joints']) != 3 or len(proof['root_translate_x_keys']) < 2 or proof['fbx_bytes'] <= 0:
        raise RuntimeError('Maya rig/export proof failed: ' + repr(proof))
finally:
    if original_selection:
        cmds.select(original_selection, replace=True)
    else:
        cmds.select(clear=True)
print(json.dumps({'ok': True, 'maya_fbx_path': maya_fbx_path, 'selection': selection, 'generated_tag': tag, 'proof': proof}))"""
    blender_code = """import json
import os
import re
import bpy

before = set(bpy.data.objects.keys())
bpy.ops.import_scene.fbx(filepath=maya_fbx_path, automatic_bone_orientation=True)
imported = [bpy.data.objects[name] for name in sorted(set(bpy.data.objects.keys()) - before)]
meshes = [obj for obj in imported if obj.type == 'MESH']
armatures = [obj for obj in imported if obj.type == 'ARMATURE']
if not meshes:
    raise RuntimeError('Blender import did not produce a mesh from ' + str(maya_fbx_path))
if not armatures:
    raise RuntimeError('Blender import did not preserve an armature from ' + str(maya_fbx_path))
material = bpy.data.materials.new('TC_PROMPT_CHAIN_validation_MAT')
material.diffuse_color = (0.2, 0.6, 1.0, 1.0)
for obj in meshes:
    obj.name = 'SM_' + re.sub(r'[^A-Za-z0-9_]+', '_', obj.name).strip('_')
    obj.data.name = obj.name + '_Mesh'
    obj.data.materials.clear()
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if not any(mod.name == 'LOD1_Decimate' for mod in obj.modifiers):
        decimate = obj.modifiers.new('LOD1_Decimate', 'DECIMATE')
        decimate.ratio = 0.55
    obj.select_set(False)

bpy.ops.object.select_all(action='DESELECT')
for obj in meshes + armatures:
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
os.makedirs(os.path.dirname(blender_fbx_path), exist_ok=True)
bpy.ops.export_scene.fbx(filepath=blender_fbx_path, use_selection=True, add_leaf_bones=False, bake_anim=True, object_types={'ARMATURE', 'MESH'})
mesh_proof = []
for obj in meshes:
    lod = next((mod for mod in obj.modifiers if mod.name == 'LOD1_Decimate' and mod.type == 'DECIMATE'), None)
    mesh_proof.append({
        'name': obj.name,
        'materials': [slot.material.name for slot in obj.material_slots if slot.material],
        'rotation': [round(float(value), 6) for value in obj.rotation_euler],
        'scale': [round(float(value), 6) for value in obj.scale],
        'lod_modifier': lod.name if lod else None,
        'lod_ratio': float(lod.ratio) if lod else None,
    })
armature_proof = []
for obj in armatures:
    action = obj.animation_data.action if obj.animation_data else None
    armature_proof.append({
        'name': obj.name,
        'action': action.name if action else None,
        'action_frame_range': [float(value) for value in action.frame_range] if action else None,
    })
proof = {
    'meshes': mesh_proof,
    'armatures': armature_proof,
    'fbx_exists': os.path.isfile(blender_fbx_path),
    'fbx_bytes': os.path.getsize(blender_fbx_path) if os.path.isfile(blender_fbx_path) else 0,
}
if any(not row['materials'] or not row['lod_modifier'] or row['scale'] != [1.0, 1.0, 1.0] for row in mesh_proof):
    raise RuntimeError('Blender mesh proof failed: ' + repr(proof))
if not any(row['action'] for row in armature_proof) or proof['fbx_bytes'] <= 0:
    raise RuntimeError('Blender animation/export proof failed: ' + repr(proof))
print(json.dumps({'ok': True, 'maya_fbx_path': maya_fbx_path, 'blender_fbx_path': blender_fbx_path, 'meshes': [obj.name for obj in meshes], 'armatures': [obj.name for obj in armatures], 'proof': proof}))"""
    unreal_import_code = """import datetime
import json
import os
import unreal

if not os.path.exists(blender_fbx_path):
    raise RuntimeError('Blender FBX does not exist on disk: ' + str(blender_fbx_path))
run_id = datetime.datetime.now().strftime('Run_%Y%m%d_%H%M%S_%f')
actual_destination_path = destination_path.rstrip('/') + '/' + run_id
unreal.EditorAssetLibrary.make_directory(actual_destination_path)
imported_paths = []
imported_assets = []
rollback = {'available': True, 'strategy': 'delete_unique_run_directory', 'target': actual_destination_path, 'performed': False}
try:
    task = unreal.AssetImportTask()
    task.filename = blender_fbx_path
    task.destination_path = actual_destination_path
    task.automated = True
    task.save = True
    task.replace_existing = False
    options = unreal.FbxImportUI()
    options.import_mesh = True
    options.import_as_skeletal = True
    options.import_animations = True
    options.import_materials = True
    options.import_textures = False
    task.options = options
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported_paths = [str(path) for path in task.imported_object_paths]
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous([actual_destination_path], force_rescan=True)
    for data in registry.get_assets_by_path(actual_destination_path, recursive=True):
        loaded = data.get_asset()
        candidate = str(loaded.get_path_name()) if loaded else str(data.package_name)
        imported_assets.append({
            'object_path': candidate,
            'class_path': str(data.asset_class_path.asset_name),
        })
        if candidate not in imported_paths:
            imported_paths.append(candidate)
    if not imported_paths:
        raise RuntimeError('Unreal import completed without task or registry object paths.')
    for path in imported_paths:
        if not unreal.EditorAssetLibrary.save_asset(path, only_if_is_dirty=False):
            raise RuntimeError('Unreal failed to save imported asset: ' + path)
    primary_asset_path = next(
        (row['object_path'] for row in imported_assets if row['class_path'] == 'SkeletalMesh'),
        imported_paths[0],
    )
except Exception as exc:
    rollback['performed'] = bool(unreal.EditorAssetLibrary.delete_directory(actual_destination_path))
    raise RuntimeError(str(exc) + ' | rollback=' + json.dumps(rollback)) from exc
print(json.dumps({'ok': True, 'blender_fbx_path': blender_fbx_path, 'destination_path': destination_path, 'actual_destination_path': actual_destination_path, 'asset_path': primary_asset_path, 'imported_paths': imported_paths, 'imported_assets': imported_assets, 'saved_paths': list(imported_paths), 'rollback': rollback}))"""
    unreal_validate_code = """import json
import unreal

registry = unreal.AssetRegistryHelpers.get_asset_registry()
package_names = {str(path).split('.')[0] for path in imported_paths}
assets = []
loaded_assets = []
for data in registry.get_assets_by_path(destination_path, recursive=True):
    if str(data.package_name) in package_names:
        loaded = data.get_asset()
        path = str(loaded.get_path_name()) if loaded else str(data.package_name)
        row = {
            'package_name': str(data.package_name),
            'asset_name': str(data.asset_name),
            'class_path': str(data.asset_class_path.asset_name),
            'object_path': path,
        }
        if loaded:
            loaded_assets.append(loaded)
            skeleton = None
            try:
                skeleton = loaded.get_editor_property('skeleton')
            except Exception:
                pass
            if skeleton:
                row['skeleton_path'] = str(skeleton.get_path_name())
            try:
                row['play_length'] = float(loaded.get_play_length())
            except Exception:
                pass
        assets.append(row)
if not assets:
    raise RuntimeError('Imported assets were not visible in the Unreal asset registry.')

classes = {row['class_path'] for row in assets}
required_classes = {'Skeleton', 'SkeletalMesh', 'AnimSequence'}
missing_classes = sorted(required_classes - classes)
if missing_classes:
    raise RuntimeError('Cross-DCC import is missing required asset classes: ' + ', '.join(missing_classes))

mesh_skeletons = {row.get('skeleton_path') for row in assets if row['class_path'] == 'SkeletalMesh' and row.get('skeleton_path')}
anim_skeletons = {row.get('skeleton_path') for row in assets if row['class_path'] == 'AnimSequence' and row.get('skeleton_path')}
if not mesh_skeletons or not anim_skeletons or mesh_skeletons.isdisjoint(anim_skeletons):
    raise RuntimeError('Imported SkeletalMesh and AnimSequence do not prove a shared skeleton.')

animation_lengths = [row.get('play_length', 0.0) for row in assets if row['class_path'] == 'AnimSequence']
if not animation_lengths or max(animation_lengths) <= 0.0:
    raise RuntimeError('Imported animation has no positive play length.')

print(json.dumps({
    'ok': True,
    'destination_path': destination_path,
    'assets': assets,
    'asset_count': len(assets),
    'required_classes': sorted(required_classes),
    'shared_skeleton_paths': sorted(mesh_skeletons & anim_skeletons),
    'animation_lengths': animation_lengths,
    'compatibility_proven': True,
}))"""

    try:
        from tech_connector.services.dcc.transfer_template_service import plan_transfer_permutation

        transfer_permutation = plan_transfer_permutation(prompt)
    except Exception:
        transfer_permutation = {}

    graph = ActionGraph(
        goal=prompt,
        intent="maya_blender_unreal_validation_pipeline",
        confidence=0.94,
        diagnostics=[
            "Matched explicit Maya -> Blender -> Unreal pipeline.",
            "Plan preserves all host stages and data handoffs.",
        ],
    )
    maya_export = graph.add(
        "execute_dcc",
        {
            "host": "maya",
            "operation": "script.run",
            "callable": "tech_connector.bridges.maya.maya_bridge.MayaBridge.execute",
            "params": {"code": maya_code, "maya_fbx_path": maya_fbx_path},
            "produces": ["maya_fbx_path", "selection", "generated_tag", "proof"],
            "requires": [],
        },
        id="maya_build_or_export_rig_fbx",
        title="Maya build/export rigged animated FBX",
    )
    blender_process = graph.add(
        "execute_dcc",
        {
            "host": "blender",
            "operation": "script.run",
            "callable": "tech_connector.bridges.blender.blender_bridge.BlenderBridge.execute",
            "params": {"code": blender_code, "maya_fbx_path": "$maya_fbx_path", "blender_fbx_path": blender_fbx_path},
            "produces": ["blender_fbx_path", "meshes", "armatures", "proof"],
            "requires": ["maya_fbx_path"],
        },
        depends_on=[maya_export.id],
        id="blender_import_clean_export_fbx",
        title="Blender import Maya FBX, clean, and export handoff FBX",
    )
    unreal_import = graph.add(
        "execute_dcc",
        {
            "host": "unreal",
            "operation": "script.run",
            "callable": "tech_connector.bridges.unreal.unreal_bridge.UnrealBridge.execute_python",
            "params": {"code": unreal_import_code, "blender_fbx_path": "$blender_fbx_path", "destination_path": destination_path},
            "produces": ["asset_path", "imported_paths", "imported_assets", "saved_paths", "actual_destination_path", "rollback"],
            "requires": ["blender_fbx_path"],
        },
        depends_on=[blender_process.id],
        id="unreal_import_processed_fbx",
        title="Unreal import processed FBX and save assets",
    )
    graph.add(
        "validate_dcc_call",
        {
            "host": "unreal",
            "operation": "script.run",
            "callable": "tech_connector.bridges.unreal.unreal_bridge.UnrealBridge.execute_python",
            "params": {"code": unreal_validate_code, "destination_path": destination_path, "imported_paths": "$imported_paths"},
            "produces": ["assets", "asset_count"],
            "requires": ["imported_paths"],
        },
        depends_on=[unreal_import.id],
        id="unreal_registry_readback_validation",
        title="Unreal registry readback validation",
        requires_approval=False,
    )
    data = graph.to_dict()
    data["transfer_permutation"] = transfer_permutation
    data["validation"] = validate_action_graph(data)
    return data


def plan_prompt_to_action_graph(
    prompt: str,
    project_roots: list[str] | None = None,
    *,
    planning_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _clean_query(prompt)
    roots = project_roots or []
    lower = text.lower()

    if _looks_like_pipeline_request(text):
        if (
            "unreal" in lower
            and not any(
                host in lower
                for host in (
                    "maya",
                    "blender",
                    "motionbuilder",
                    "houdini",
                    "unity",
                    "substance painter",
                )
            )
            and re.search(r"\b(pipeline|workflow)\b", lower)
        ):
            from tech_connector.services.unreal.unreal_pipeline_compiler_service import (
                compile_unreal_operation_pipeline,
            )

            return compile_unreal_operation_pipeline(
                text,
                requirement_manifest=dict(
                    (planning_preferences or {}).get("requirement_manifest") or {}
                ),
            )
        from tech_connector.services.dcc.dynamic_pipeline_compiler_service import (
            compile_dynamic_pipeline,
            is_dynamic_transfer_request,
        )

        if is_dynamic_transfer_request(text):
            dynamic = compile_dynamic_pipeline(
                text,
                project_root=roots[0] if roots else None,
                use_default_settings=bool(
                    (planning_preferences or {}).get("use_default_settings", True)
                ),
                custom_settings=dict(
                    (planning_preferences or {}).get("custom_settings") or {}
                ),
                requirement_manifest=dict(
                    (planning_preferences or {}).get("requirement_manifest") or {}
                ),
            )
            if dynamic.get("selected_contracts") or dynamic.get("gaps"):
                return dynamic
        concrete = _maya_blender_unreal_validation_action_graph(text)
        if concrete:
            return concrete
        concrete = _blender_to_unreal_prop_action_graph(text)
        if concrete:
            return concrete
        graph = _workflow_plan_to_action_graph(text, roots)
        if graph:
            return graph

    action_graph = ActionGraph(goal=text, intent="general", confidence=0.65)

    file_hint = _file_hint(text)
    if re.search(r"\b(open|show|go to|jump to)\b", lower) and file_hint:
        resolve = action_graph.add("resolve_file", {"query": file_hint, "path": file_hint}, requires_approval=False)
        action_graph.add("open_file", {"query": file_hint, "path": file_hint}, depends_on=[resolve.id], requires_approval=False)
    elif re.search(r"\b(find|search|locate|where is|where are)\b", lower) and "github" not in lower:
        function_names = _function_mentions(text)
        if function_names or re.search(r"\b(function|method|symbol)\b", lower):
            query = function_names[0] if function_names else re.sub(r"\b(find|search|locate|where is|where are|function|method|symbol)\b", "", text, flags=re.IGNORECASE).strip()
            action_graph.intent = "symbol_search"
            action_graph.add("resolve_function", {"query": query, "file_hint": file_hint}, requires_approval=False)
            action_graph.add("open_symbol", {"query": query, "file_hint": file_hint}, requires_approval=False)
        else:
            action_graph.intent = "project_search"
            action_graph.add("search_project", {"query": text}, requires_approval=False)
    elif re.search(r"\b(rebuild|refresh)\b", lower) and re.search(r"\b(index|project index|knowledge)\b", lower):
        action_graph.intent = "rebuild_index"
        action_graph.add("rebuild_index", {"scope": "project"})
    elif re.search(r"\b(index)\b", lower) and re.search(r"\b(project|repo|repository|codebase)\b", lower):
        action_graph.intent = "index_project"
        action_graph.add("index_project", {"scope": "project"})
    elif "github" in lower and re.search(r"\b(ingest|import|install)\b", lower):
        auto_select = bool(re.search(r"\b(auto(?:matically)?\s+select|auto[- ]?select|use\s+best\s+match|pick\s+the\s+best)\b", lower))
        action_graph.intent = "github_candidate_review"
        action_graph.add(
            "github_search",
            {
                "query": text,
                "limit": 5,
                "auto_select": auto_select,
                "review_required": not auto_select,
            },
            requires_approval=False,
        )
    elif "github" in lower and re.search(r"\b(search|find)\b", lower):
        action_graph.intent = "github_search"
        action_graph.add("github_search", {"query": text, "limit": 5}, requires_approval=False)
    elif re.search(r"\b(refresh)\b", lower) and "unreal" in lower:
        action_graph.intent = "refresh_unreal"
        action_graph.add("refresh_unreal", {})
    elif re.search(r"\b(refresh)\b", lower) and "maya" in lower:
        action_graph.intent = "refresh_maya"
        action_graph.add("refresh_maya", {})
    elif re.search(r"\b(refresh)\b", lower) and "blender" in lower:
        action_graph.intent = "refresh_blender"
        action_graph.add("refresh_blender", {})
    else:
        action_graph.intent = "needs_llm_planner"
        action_graph.planner = "deterministic_router"
        action_graph.confidence = 0.2
        action_graph.add("search_project", {"query": text}, requires_approval=False)
        action_graph.diagnostics.append("Deterministic router found no complete plan; LLM planner may be needed.")

    data = action_graph.to_dict()
    data["validation"] = validate_action_graph(data)
    return data


def workflow_plan_from_action_graph(graph: dict[str, Any]) -> dict[str, Any] | None:
    if graph.get("workflow_plan"):
        return graph["workflow_plan"]

    actions = [
        dict(action)
        for action in graph.get("actions") or []
        if action.get("type") in {"execute_dcc", "validate_dcc_call"}
    ]
    if not actions:
        return None

    action_indexes = {
        str(action.get("id") or f"step_{index}"): index
        for index, action in enumerate(actions, start=1)
    }
    produced_by: dict[str, tuple[int, str]] = {}
    steps: list[dict[str, Any]] = []
    data_links: list[dict[str, Any]] = []
    flow_links: list[dict[str, Any]] = []

    for index, action in enumerate(actions, start=1):
        args = dict(action.get("args") or {})
        host = str(args.get("host") or "").lower()
        operation = str(args.get("operation") or "")
        params = dict(args.get("params") or {})
        produces = [str(name) for name in args.get("produces") or [] if str(name)]
        list_string_contract_names = {
            "armatures",
            "imported_paths",
            "joints",
            "materials",
            "meshes",
            "objects",
            "saved_paths",
            "selection",
        }
        list_mapping_contract_names = {"assets", "imported_assets"}
        param_contracts = [
            {
                "name": str(name),
                "annotation": (
                    "list[str]"
                    if str(name) in list_string_contract_names
                    else "list[dict[str, Any]]"
                    if str(name) in list_mapping_contract_names
                    else "str"
                    if name == "code" or isinstance(value, str)
                    else "Any"
                ),
                "required": True,
            }
            for name, value in params.items()
        ]
        output_contracts = [
            {
                "name": name,
                "annotation": (
                    "list[str]"
                    if name in list_string_contract_names
                    else "list[dict[str, Any]]"
                    if name in list_mapping_contract_names
                    else "Any"
                ),
            }
            for name in produces
        ]
        literal_values: dict[str, Any] = {}

        for param_name, value in params.items():
            if isinstance(value, str) and value.startswith("$"):
                output_name = value[1:]
                producer = produced_by.get(output_name)
                if producer:
                    source_index, source_output = producer
                    data_links.append(
                        {
                            "from_step": source_index,
                            "from_output": source_output,
                            "to_step": index,
                            "to_input": str(param_name),
                            "reason": f"Bind `{source_output}` from the prior DCC stage.",
                        }
                    )
                continue
            literal_values[str(param_name)] = value

        action_id = str(action.get("id") or f"step_{index}")
        steps.append(
            {
                "id": action_id,
                "symbol": {
                    "name": action_id,
                    "kind": "function",
                    "host": host,
                    "provider_id": host,
                    "pipeline_operation": "dcc_operation",
                    "operation": operation,
                    "function_path": str(args.get("callable") or ""),
                    "params": param_contracts,
                    "outputs": output_contracts,
                    "return_annotation": "dict[str, Any]",
                },
                "params": param_contracts,
                "outputs": output_contracts,
                "literal_values": literal_values,
            }
        )
        for output_name in produces:
            produced_by[output_name] = (index, output_name)

        for dependency in action.get("depends_on") or []:
            source_index = action_indexes.get(str(dependency))
            if source_index:
                flow_links.append(
                    {
                        "from_step": source_index,
                        "to_step": index,
                        "reason": "Preserve the planned cross-DCC execution order.",
                    }
                )

    unresolved = [
        {
            "step": item.get("stage"),
            "required_output": item.get("argument"),
            "question": item.get("question"),
            "host": item.get("host"),
        }
        for item in graph.get("required_inputs") or []
    ]
    for index, action in enumerate(actions, start=1):
        args = dict(action.get("args") or {})
        for required in args.get("requires") or []:
            if str(required) not in produced_by:
                unresolved.append({"step": index, "required_output": str(required)})

    return {
        "success": bool(steps) and not unresolved and not bool(graph.get("capability_gaps")),
        "confidence": float(graph.get("confidence") or 0.0),
        "steps": steps,
        "data_links": data_links,
        "flow_links": flow_links,
        "diagnostics": list(graph.get("diagnostics") or []),
        "capability_gaps": list(graph.get("capability_gaps") or []),
        "unresolved_inputs": unresolved,
        "source_action_graph_intent": graph.get("intent") or "",
    }
