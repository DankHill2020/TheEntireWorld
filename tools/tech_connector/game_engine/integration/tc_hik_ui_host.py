"""Maya-like host facade allowing the literal HIK UI to edit a TC rig graph."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph, IDENTITY_MATRIX
from tech_connector.game_engine.authoring.rigging_workspace_service import (
    ALL_CHARACTER_SLOTS,
    CharacterDefinition,
    FACE_SLOTS,
    auto_map_character,
)
from tech_connector.game_engine.integration.tc_rigging_host_adapter import TCRiggingHostAdapter
from tech_connector.game_engine.authoring.tc_rig_template_service import (
    DEFAULT_TC_BIPED_TEMPLATE,
    instantiate_tc_rig_template,
)


_TWIST_LEAF_SLOTS = tuple(
    f"Leaf{side}{segment}{index}"
    for side in ("Left", "Right")
    for segment, count in (("ArmRoll", 3), ("ForearmRoll", 3), ("UpLegRoll", 3), ("LegRoll", 2))
    for index in range(1, count + 1)
)
_BODY_SLOTS = tuple(dict.fromkeys(ALL_CHARACTER_SLOTS + _TWIST_LEAF_SLOTS))


def _body_map() -> dict[str, dict[str, Any]]:
    return {slot: {"index": index, "joint": ""} for index, slot in enumerate(_BODY_SLOTS)}


def _face_map() -> dict[str, Any]:
    return {
        "LeftBrow": {"index": 0, "joints": []},
        "RightBrow": {"index": 1, "joints": []},
        "LeftEyelid": {"index": 10, "outer": {"joint": ""}, "upper": {"joints": []},
                        "inner": {"joint": ""}, "lower": {"joints": []}, "joints": []},
        "RightEyelid": {"index": 20, "outer": {"joint": ""}, "upper": {"joints": []},
                         "inner": {"joint": ""}, "lower": {"joints": []}, "joints": []},
        "LeftEye": {"index": 70, "joint": ""}, "RightEye": {"index": 71, "joint": ""},
        "LipChain": {"index": 30, "joints": []},
        "UpperLipCenter": {"index": 31, "joint": ""}, "LowerLipCenter": {"index": 32, "joint": ""},
        "LeftLipCorner": {"index": 33, "joint": ""}, "RightLipCorner": {"index": 34, "joint": ""},
        "Jaw": {"index": 40, "joint": ""}, "TongueChain": {"index": 50, "joints": []},
        "UpperTeeth": {"index": 60, "joint": ""}, "LowerTeeth": {"index": 61, "joint": ""},
        "NoseRoot": {"index": 80, "joint": ""}, "OtherFaceJoints": {"index": 100, "joints": []},
    }


class TCHikHostContext:
    def __init__(
        self,
        graph: EditableRigGraph,
        *,
        selection_provider: Callable[[], list[str]] | None = None,
        undo_callback: Callable[[str], None] | None = None,
        refresh_callback: Callable[[], None] | None = None,
    ):
        self.graph = graph
        self.adapter = TCRiggingHostAdapter(graph)
        self.selection_provider = selection_provider
        self.undo_callback = undo_callback
        self.refresh_callback = refresh_callback
        self.selection_ids: list[str] = []
        self.manual_selection: list[str] | None = None
        self.last_provider_selection: list[str] = []
        hik_metadata = self.graph.metadata.setdefault("hik_ui", {})
        self.metadata = hik_metadata.setdefault("modules", {})
        self.stored_connections = hik_metadata.setdefault("stored_connections", {})
        stored_definition = hik_metadata.get("character_definition")
        self.current_definition = (
            CharacterDefinition.from_dict(stored_definition)
            if isinstance(stored_definition, dict) and stored_definition.get("schema")
            else None
        )
        self.undo_chunk = ""

    def selection(self) -> list[str]:
        if self.selection_provider:
            provider_values = [str(value) for value in (self.selection_provider() or []) if value]
            if provider_values != self.last_provider_selection:
                self.last_provider_selection = provider_values
                self.manual_selection = None
            values = self.manual_selection if self.manual_selection is not None else provider_values
        else:
            values = self.manual_selection if self.manual_selection is not None else self.selection_ids
        return [str(value) for value in (values or []) if value]

    def changed(self) -> None:
        if self.refresh_callback:
            self.refresh_callback()

    def checkpoint(self, label: str) -> None:
        if not self.undo_chunk and self.undo_callback:
            self.undo_callback(str(label or "Rigging change"))


_context: TCHikHostContext | None = None


def bind_tc_hik_host(
    graph: EditableRigGraph,
    *,
    selection_provider: Callable[[], list[str]] | None = None,
    undo_callback: Callable[[str], None] | None = None,
    refresh_callback: Callable[[], None] | None = None,
) -> TCHikHostContext:
    global _context
    _context = TCHikHostContext(
        graph,
        selection_provider=selection_provider,
        undo_callback=undo_callback,
        refresh_callback=refresh_callback,
    )
    return _context


def _ctx() -> TCHikHostContext:
    if _context is None:
        raise RuntimeError("The TC HIK host must be bound to The Entire Scene Viewer before use.")
    return _context


def _node_name(value: str) -> str:
    return str(value or "").split(".", 1)[0]


class TCCmdsFacade:
    def about(self, **_kwargs):
        return "2026"

    def file(self, **_kwargs):
        return ""

    def commandPort(self, *_args, **kwargs):
        return bool(kwargs.get("q", False))

    def ls(self, *patterns, **kwargs):
        context = _ctx()
        selected = bool(kwargs.get("sl") or kwargs.get("selection"))
        node_type = str(kwargs.get("type") or "")
        values = context.selection() if selected else list(context.graph.nodes)
        if node_type == "joint":
            values = [value for value in values if value in context.graph.joints]
        elif node_type:
            values = [
                value for value in values
                if str(context.graph.nodes.get(value, {}).get("node_type") or "").lower().endswith(node_type.lower())
            ]
        if patterns:
            import fnmatch
            values = [value for value in values if any(fnmatch.fnmatch(value, str(pattern)) for pattern in patterns)]
        return values

    def objExists(self, value):
        node = _node_name(value)
        return node in _ctx().graph.nodes or node in _ctx().graph.joints

    def objectType(self, value):
        return self.nodeType(value)

    def nodeType(self, value):
        node = _node_name(value)
        if node in _ctx().graph.joints:
            return "joint"
        return str(_ctx().graph.nodes.get(node, {}).get("source_type") or
                   _ctx().graph.nodes.get(node, {}).get("node_type") or "transform")

    def listRelatives(self, value, **kwargs):
        context = _ctx()
        node = _node_name(value)
        parent_query = bool(kwargs.get("parent") or kwargs.get("p"))
        children_query = bool(kwargs.get("children") or kwargs.get("c"))
        requested_type = kwargs.get("type")
        if parent_query:
            parent = str(context.graph.joints.get(node, {}).get("parent_id") or
                         context.graph.nodes.get(node, {}).get("dag_parent_id") or "")
            return [parent] if parent else []
        values = []
        if children_query or kwargs.get("allDescendents") or kwargs.get("ad"):
            direct = [
                item_id for item_id, item in context.graph.nodes.items()
                if str(item.get("dag_parent_id") or "") == node
            ]
            values.extend(direct)
            if kwargs.get("allDescendents") or kwargs.get("ad"):
                queue = list(direct)
                while queue:
                    parent = queue.pop(0)
                    children = [item_id for item_id, item in context.graph.nodes.items()
                                if str(item.get("dag_parent_id") or "") == parent]
                    values.extend(children)
                    queue.extend(children)
        if requested_type == "joint":
            values = [value for value in values if value in context.graph.joints]
        elif requested_type == "constraint" or isinstance(requested_type, (list, tuple)):
            return [item_id for item_id, item in context.graph.constraints.items()
                    if str(item.get("target_id") or "") == node]
        return values

    def listConnections(self, value, **_kwargs):
        context = _ctx()
        node = _node_name(value)
        values = []
        for item_id, item in context.graph.connections.items():
            if node in {str(item.get("source_node") or ""), str(item.get("target_node") or "")}:
                values.append(item_id)
        for item_id, item in context.graph.constraints.items():
            if node == str(item.get("target_id") or "") or node in item.get("source_ids") or []:
                values.append(item_id)
        return values

    def connectionInfo(self, value, **_kwargs):
        node, _, attribute = str(value).partition(".")
        return any(
            str(item.get("target_node") or "") == node and str(item.get("target_attribute") or "") == attribute
            for item in _ctx().graph.connections.values()
        )

    def select(self, value=None, **kwargs):
        context = _ctx()
        values = [str(item) for item in value] if isinstance(value, (list, tuple)) else [str(value)] if value else []
        if kwargs.get("clear"):
            context.manual_selection = []
        elif kwargs.get("replace", kwargs.get("r", True)):
            context.manual_selection = values
        else:
            context.manual_selection = list(context.selection()) + values
        context.selection_ids = list(context.manual_selection or [])
        return values

    def warning(self, message):
        print("[TC HIK UI] " + str(message))

    def confirmDialog(self, **kwargs):
        print(f"[TC HIK UI] {kwargs.get('title', 'Notice')}: {kwargs.get('message', '')}")
        return str(kwargs.get("defaultButton") or (kwargs.get("button") or ["OK"])[0])

    def undoInfo(self, **kwargs):
        context = _ctx()
        if kwargs.get("openChunk"):
            context.undo_chunk = str(kwargs.get("chunkName") or "Rigging change")
            if context.undo_callback:
                context.undo_callback(context.undo_chunk)
        if kwargs.get("closeChunk"):
            context.undo_chunk = ""

    def xform(self, value, **kwargs):
        context = _ctx()
        node = _node_name(value)
        matrix = context.adapter._joint_world_matrix(node) if node in context.graph.joints else context.adapter._node_world_matrix(node)
        if kwargs.get("q") or kwargs.get("query"):
            if kwargs.get("t") or kwargs.get("translation"):
                return list(matrix[12:15])
            return matrix
        incoming = kwargs.get("matrix")
        if incoming and len(incoming) == 16:
            if node in context.graph.joints:
                context.graph.joints[node]["local_matrix"] = list(incoming)
            context.graph.nodes[node].setdefault("attributes", {})["matrix"] = list(incoming)
            context.changed()
        return None

    def setAttr(self, plug, *values, **_kwargs):
        node, _, attribute = str(plug).partition(".")
        if node in _ctx().graph.nodes:
            _ctx().graph.nodes[node].setdefault("attributes", {})[attribute] = values[0] if len(values) == 1 else list(values)

    def attributeQuery(self, attribute, **kwargs):
        node = str(kwargs.get("node") or "")
        if kwargs.get("exists"):
            return attribute in (_ctx().graph.nodes.get(node, {}).get("attributes") or {})
        if kwargs.get("listEnum"):
            return [": ".join((_ctx().graph.nodes.get(node, {}).get("attributes") or {}).get(attribute + "Names") or [])]
        return None

    def _constraint_targets(self, value):
        return list(_ctx().graph.constraints.get(_node_name(value), {}).get("source_ids") or [])

    def orientConstraint(self, value, **kwargs):
        return self._constraint_targets(value) if kwargs.get("q") else []

    parentConstraint = orientConstraint
    pointConstraint = orientConstraint


class TCSetupHikFacade:
    DEFAULT_JOINT_MAP = _body_map()
    DEFAULT_FACE_JOINT_MAP = _face_map()
    DEFAULT_FACE_MAP = DEFAULT_FACE_JOINT_MAP

    def populate_default_face_map_from_scene(self, value=None):
        return copy.deepcopy(value or self.DEFAULT_FACE_JOINT_MAP)

    def guess_joint_map_from_root(self, root_joint, base_joint_map=None):
        definition = auto_map_character(_ctx().adapter.scene_joints(), source_root=str(root_joint or ""))
        result = copy.deepcopy(base_joint_map or self.DEFAULT_JOINT_MAP)
        for slot in result:
            result[slot]["joint"] = definition.slots.get(slot, "")
        return result

    def set_t_pose(self, joint_map=None):
        definition = _definition_from_maps(joint_map or {}, {})
        _ctx().adapter._op_definition_set_reference_pose({"definition": definition})
        return True

    def setup_hik_character(self, character_name, joint_map, fbx_export_path="", namespace=""):
        definition = _definition_from_maps(joint_map, {})
        definition.name = str(character_name or "Character")
        definition.metadata.update({"export_path": str(fbx_export_path or ""), "namespace": str(namespace or "")})
        _ctx().current_definition = definition
        _ctx().graph.metadata.setdefault("hik_ui", {})["character_definition"] = definition.to_dict()
        return definition.to_dict()


def _definition_from_maps(body_map: dict[str, Any], face_map: dict[str, Any]) -> CharacterDefinition:
    slots = {}
    for slot, row in (body_map or {}).items():
        if isinstance(row, dict) and row.get("joint"):
            slots[str(slot)] = str(row["joint"])
    for slot, row in (face_map or {}).items():
        if not isinstance(row, dict):
            continue
        if row.get("joint"):
            slots[str(slot)] = str(row["joint"])
        elif row.get("joints"):
            for index, joint in enumerate(row["joints"]):
                slots[f"{slot}{index + 1}"] = str(joint)
    return CharacterDefinition("Character", slots=slots)


_MODULE_KEYS = {
    "Root / Origin": "root", "Pelvis & Hips": "pelvis", "Spine": "spine", "Neck": "neck", "Head": "head",
    "Left Arm": "left_arm", "Right Arm": "right_arm", "Left Leg": "left_leg", "Right Leg": "right_leg",
    "Left Clavicle": "left_clavicle", "Right Clavicle": "right_clavicle",
    "Brows (Left)": "brows", "Brows (Right)": "brows", "Eyes Aim": "eyes",
    "Eyelids (Left)": "eyelids", "Eyelids (Right)": "eyelids", "Mouth & Lips": "mouth",
    "Tongue": "tongue", "Teeth": "teeth", "Other Face Joints": "face",
}


class TCCreateRigFacade:
    def hik_map_to_rig_args(self, body_map, face_map):
        definition = _definition_from_maps(body_map, face_map)
        _ctx().current_definition = definition
        _ctx().graph.metadata.setdefault("hik_ui", {})["character_definition"] = definition.to_dict()
        return [definition.to_dict(), copy.deepcopy(face_map)]

    def _build(self, module, body_map, face_map=None, **options):
        definition = _definition_from_maps(body_map, face_map or {})
        result = _ctx().adapter._build_module(_MODULE_KEYS.get(module, module), definition, options)
        if not result.ok:
            raise RuntimeError(result.message)
        _ctx().metadata[module] = {"built": True, "joints": list(definition.slots.values()), **options}
        _ctx().changed()
        return result.to_dict()

    def rig_arm_module(self, side, body_map, parent_ctrl=None):
        return self._build("left_arm" if str(side).lower().startswith("l") else "right_arm", body_map, parent=parent_ctrl)

    def rig_leg_module(self, side, body_map, parent_ctrl=None):
        return self._build("left_leg" if str(side).lower().startswith("l") else "right_leg", body_map, parent=parent_ctrl)

    def rig_clavicle_module(self, side, body_map, parent_ctrl=None):
        module = "left_clavicle" if str(side).lower().startswith("l") else "right_clavicle"
        # TC clavicles use controls on the mapped shoulder joint.
        slot = "LeftShoulder" if module.startswith("left") else "RightShoulder"
        joint = str((body_map.get(slot) or {}).get("joint") or "")
        if not joint:
            return {}
        result = _ctx().adapter._op_rig_create_control({"target": joint, "module": module, "parent": parent_ctrl or ""})
        _ctx().metadata[module] = {"built": result.ok, "joints": [joint], "parent": parent_ctrl or ""}
        _ctx().changed()
        return result.to_dict()

    def rig_root_module(self, body_map, parent_ctrl=None): return self._build("root", body_map, parent=parent_ctrl)
    def rig_pelvis_module(self, body_map, parent_ctrl=None): return self._build("pelvis", body_map, parent=parent_ctrl)
    def rig_spine_module(self, body_map, parent_ctrl=None): return self._build("spine", body_map, parent=parent_ctrl)
    def rig_neck_module(self, body_map, parent_ctrl=None): return self._build("neck", body_map, parent=parent_ctrl)
    def rig_head_module(self, body_map, face_map=None, parent_ctrl=None): return self._build("head", body_map, face_map, parent=parent_ctrl)

    def _face(self, module, face_map, parent=None, side=""):
        definition = _definition_from_maps({}, face_map)
        if side:
            side_name = "Left" if str(side).lower().startswith("l") else "Right"
            definition.slots = {
                slot: joint for slot, joint in definition.slots.items()
                if slot.startswith(side_name)
            }
        module_key = f"{side}_{module}" if side else module
        created = []
        tokens = {
            "brows": ("Brow",), "eyes": ("Eye",), "eyelids": ("Lid",),
            "mouth": ("Lip", "Jaw"), "tongue": ("Tongue",), "teeth": ("Teeth",),
            "face": ("Brow", "Eye", "Lid", "Lip", "Jaw", "Tongue", "Teeth", "Nose"),
        }[module]
        for slot, joint in definition.slots.items():
            if not any(token in slot for token in tokens):
                continue
            control = f"{module_key}_{slot}_ctrl"
            if control in _ctx().graph.nodes:
                continue
            result = _ctx().adapter._op_rig_create_control({
                "target": joint, "control_id": control, "name": control,
                "shape": "circle", "size": 0.25, "module": module_key,
                "parent": parent or "",
            })
            created.extend(result.created_ids)
        _ctx().metadata[module_key] = {
            "built": bool(created), "joints": list(definition.slots.values()), "parent": parent or ""
        }
        _ctx().changed()
        return {"ok": True, "created_ids": created, "module": module_key}

    def rig_brows_module(self, side, face_map, parent_ctrl=None): return self._face("brows", face_map, parent_ctrl, side)
    def rig_eyes_module(self, face_map, parent_ctrl=None): return self._face("eyes", face_map, parent_ctrl)
    def rig_eyelids_module(self, side, face_map, parent_ctrl=None): return self._face("eyelids", face_map, parent_ctrl, side)
    def rig_mouth_module(self, face_map, parent_ctrl=None, jaw_ctrl=None): return self._face("mouth", face_map, parent_ctrl)
    def rig_tongue_module(self, face_map, parent_ctrl=None): return self._face("tongue", face_map, parent_ctrl)
    def rig_teeth_module(self, face_map, parent_ctrl=None, jaw_ctrl=None): return self._face("teeth", face_map, parent_ctrl)
    def rig_other_face_module(self, face_map, parent_ctrl=None, jaw_ctrl=None, jaw_joint=None): return self._face("face", face_map, parent_ctrl)

    def create_joint_controls(self, joint_list=None, control_shape="circle", root_parent=None, **_kwargs):
        _ctx().checkpoint("Create joint controls")
        rows = []
        for joint in joint_list or []:
            result = _ctx().adapter._op_rig_create_control({
                "target": joint, "shape": control_shape, "parent": root_parent or "", "module": "custom",
            })
            if result.ok and result.created_ids:
                rows.append({"ctrl": result.created_ids[0], "joint": joint})
        _ctx().changed()
        return rows

    def create_space_switch(self, driven, targets, attr_name="space", constraint_type="parent", **_kwargs):
        _ctx().checkpoint("Create space switch")
        result = _ctx().adapter._op_rig_create_space_switch({
            "driven": driven, "targets": targets, "names": [str(value) for value in targets], "mode": constraint_type,
        })
        _ctx().changed()
        return result.to_dict()

    def create_joints_along_curve(self, curve, joint_count=5, keep_attached=True, name_prefix=None, **_kwargs):
        _ctx().checkpoint("Create joints along curve")
        result = _ctx().adapter._op_rig_create_curve_joints({
            "curve": curve,
            "joint_count": int(joint_count),
            "keep_attached": bool(keep_attached),
            "name_prefix": name_prefix,
        })
        if not result.ok:
            raise RuntimeError(result.message)
        _ctx().changed()
        return result.data

    def setup_surface_rig_with_drivers(self, joint_list=None, joint_chain=None, **kwargs):
        chain = list(joint_list or joint_chain or [])
        _ctx().checkpoint("Create surface rig")
        payload = {
            "joint_chain": chain,
            "width": max(0.001, abs(float(kwargs.get("offset", 0.5) or 0.5))),
            "control_count": len(kwargs.get("driver_follicle_indices") or []) or len(chain),
            "region": str(kwargs.get("region") or "surface"),
            "side": str(kwargs.get("side") or ""),
            "name": str(kwargs.get("loft_name") or "surface"),
            "parent": str(kwargs.get("root_parent") or ""),
        }
        result = _ctx().adapter._op_rig_create_ribbon(payload)
        _ctx().changed()
        return result.to_dict()

    def _ensure_space_switch(self, driven, targets, mode, module):
        graph = _ctx().graph
        valid_targets = [target for target in targets if target in graph.nodes]
        if driven not in graph.nodes or not valid_targets:
            return 0
        for item in graph.constraints.values():
            settings = item.get("settings") or {}
            if item.get("target_id") == driven and settings.get("auto_space_switch") == module:
                item["source_ids"] = list(valid_targets)
                settings["space_names"] = list(valid_targets)
                settings["weights"] = [1.0] + [0.0] * (len(valid_targets) - 1)
                return 0
        result = _ctx().adapter._op_rig_create_space_switch({
            "driven": driven, "targets": valid_targets, "names": valid_targets,
            "mode": mode, "module": module,
        })
        if result.created_ids:
            graph.constraints[result.created_ids[0]].setdefault("settings", {})["auto_space_switch"] = module
        return len(result.created_ids)

    def create_arm_space_switches(self, side, body_joint_map=None):
        prefix = "left" if str(side).lower().startswith("l") else "right"
        module = f"{prefix}_arm"
        core = [f"{prefix}_clavicle_LeftShoulder_ctrl" if prefix == "left" else f"{prefix}_clavicle_RightShoulder_ctrl",
                "spine_Spine_ctrl", "pelvis_Hips_ctrl", "root_Reference_ctrl"]
        count = self._ensure_space_switch(f"{module}_pole_ctrl", [f"{module}_ik_ctrl", *core], "parent", module)
        count += self._ensure_space_switch(f"{module}_ik_ctrl", core, "parent", module)
        upper = "l_upperarm" if prefix == "left" else "r_upperarm"
        count += self._ensure_space_switch(f"{module}_{upper}_fk_ctrl", core, "orient", module)
        return count

    def create_leg_space_switches(self, side, body_joint_map=None):
        prefix = "left" if str(side).lower().startswith("l") else "right"
        module = f"{prefix}_leg"
        core = ["pelvis_Hips_ctrl", "root_Reference_ctrl"]
        count = self._ensure_space_switch(f"{module}_pole_ctrl", [f"{module}_ik_ctrl", *core], "parent", module)
        count += self._ensure_space_switch(f"{module}_ik_ctrl", core, "parent", module)
        thigh = "l_thigh" if prefix == "left" else "r_thigh"
        count += self._ensure_space_switch(f"{module}_{thigh}_fk_ctrl", core, "orient", module)
        return count
    def delete_unused_scaffold_nodes(self): return 0
    def store_all_control_cv_positions(self):
        positions = {
            node_id: copy.deepcopy((node.get("attributes") or {}).get("control_cv_positions"))
            for node_id, node in _ctx().graph.nodes.items()
            if (node.get("attributes") or {}).get("control_cv_positions") is not None
        }
        _ctx().graph.metadata.setdefault("hik_ui", {})["control_cv_positions"] = positions
        return copy.deepcopy(positions)

    def restore_all_control_cv_positions(self):
        positions = (_ctx().graph.metadata.get("hik_ui") or {}).get("control_cv_positions") or {}
        restored = 0
        for node_id, values in positions.items():
            if node_id in _ctx().graph.nodes:
                _ctx().graph.nodes[node_id].setdefault("attributes", {})["control_cv_positions"] = copy.deepcopy(values)
                restored += 1
        if restored:
            _ctx().changed()
        return restored

    def get_module_controls(self, module):
        key = _MODULE_KEYS.get(module, str(module).lower().replace(" ", "_"))
        return [node_id for node_id, node in _ctx().graph.nodes.items()
                if str((node.get("attributes") or {}).get("rig_module") or "") == key]

    def save_module_metadata(self, module, data):
        _ctx().metadata[str(module)] = copy.deepcopy(data)
        return True

    def load_module_metadata(self, module): return copy.deepcopy(_ctx().metadata.get(str(module), {}))
    def get_all_module_metadata(self): return copy.deepcopy(_ctx().metadata)
    def clear_module_metadata(self, module): _ctx().metadata.pop(str(module), None)

    def store_rig_connections(self, controls, module):
        result = _ctx().adapter._op_rig_store_connections({"module": str(module)})
        _ctx().stored_connections[str(module)] = copy.deepcopy(result.data)
        return result.data

    def restore_rig_connections(self, module):
        data = _ctx().stored_connections.get(str(module), {})
        result = _ctx().adapter._op_rig_restore_connections({"module": str(module), **data})
        return len(result.changed_ids)

    def _remove(self, module):
        result = _ctx().adapter._op_rig_remove_module({"module": _MODULE_KEYS.get(module, module)})
        _ctx().metadata.pop(str(module), None)
        _ctx().changed()
        return len(result.removed_ids)

    def remove_arm_module(self, side, _body): return self._remove("left_arm" if str(side).startswith("l") else "right_arm")
    def remove_leg_module(self, side, _body): return self._remove("left_leg" if str(side).startswith("l") else "right_leg")
    def remove_clavicle_module(self, side, _body): return self._remove("left_clavicle" if str(side).startswith("l") else "right_clavicle")
    def remove_root_module(self, _body): return self._remove("root")
    def remove_pelvis_module(self, _body): return self._remove("pelvis")
    def remove_spine_module(self, _body): return self._remove("spine")
    def remove_neck_module(self, _body): return self._remove("neck")
    def remove_head_module(self, _body): return self._remove("head")
    def remove_brows_module(self, side, _face): return self._remove(("l" if str(side).startswith("l") else "r") + "_brows")
    def remove_eyes_module(self, _face): return self._remove("eyes")
    def remove_eyelids_module(self, side, _face): return self._remove(("l" if str(side).startswith("l") else "r") + "_eyelids")
    def remove_mouth_module(self, _face): return self._remove("mouth")
    def remove_tongue_module(self, _face): return self._remove("tongue")
    def remove_teeth_module(self, _face): return self._remove("teeth")
    def remove_other_face_module(self, _face): return self._remove("face")

    def remove_full_rig(self, _body, _face=None):
        removed = 0
        modules = set(_MODULE_KEYS.values()) | {
            "l_brows", "r_brows", "eyes", "l_eyelids", "r_eyelids",
            "mouth", "tongue", "teeth", "face",
        }
        for module in sorted(modules):
            removed += self._remove(module)
        return removed


class TCRigTemplateFacade:
    DEFAULT_BIPED_RIG_TEMPLATE = DEFAULT_TC_BIPED_TEMPLATE

    def load_biped_rig_template(self, template_path=None, namespace="", reference=False, **_kwargs):
        if reference:
            raise ValueError("TC skeleton templates are instantiated locally and cannot be referenced.")
        _ctx().checkpoint("Load TC biped skeleton template")
        result = instantiate_tc_rig_template(
            _ctx().graph,
            template_path=template_path or self.DEFAULT_BIPED_RIG_TEMPLATE,
            namespace=namespace,
        )
        body_map = _body_map()
        for slot, joint in result["joint_map"].items():
            if slot in body_map:
                body_map[slot]["joint"] = joint
        face_map = _face_map()
        for slot, joint in result["face_slots"].items():
            if slot in face_map and isinstance(face_map[slot], dict):
                face_map[slot]["joint"] = joint
        for slot, joint_ids in result["face_chains"].items():
            if slot in face_map and isinstance(face_map[slot], dict):
                face_map[slot]["joints"] = list(joint_ids)
        result["joint_map"] = body_map
        result["face_map"] = face_map
        result["rfl_joint_count"] = int(result.get("roll_joint_count", 0) or 0)
        _ctx().changed()
        return result


class TCSkinningUtilsFacade:
    @staticmethod
    def _safe_name(value):
        return "".join(char if char.isalnum() or char in "-_." else "_" for char in str(value))

    def export_skin_weights(self, meshes, export_dir="C:/temp/weights"):
        directory = Path(export_dir)
        directory.mkdir(parents=True, exist_ok=True)
        requested = {str(mesh) for mesh in (meshes or [])}
        exported = []
        for skin_id, skin in _ctx().graph.skins.items():
            mesh_id = str(skin.get("mesh_id") or "")
            if requested and mesh_id not in requested and skin_id not in requested:
                continue
            path = directory / f"{self._safe_name(mesh_id or skin_id)}_weights.tcskin.json"
            payload = {"schema": "tech-connector-skin-weights/v1", "skin": copy.deepcopy(skin)}
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            exported.append(str(path))
        return exported

    def import_skin_weights(self, meshes=None, export_dir="C:/temp/weights"):
        directory = Path(export_dir)
        requested = {str(mesh) for mesh in (meshes or [])}
        imported = []
        _ctx().checkpoint("Import skin weights")
        for path in sorted(directory.glob("*_weights.tcskin.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema") != "tech-connector-skin-weights/v1":
                continue
            skin = dict(payload.get("skin") or {})
            mesh_id = str(skin.get("mesh_id") or "")
            if requested and mesh_id not in requested:
                continue
            missing = set(skin.get("joint_ids") or []) - set(_ctx().graph.joints)
            if missing:
                raise KeyError("Missing skin influences: " + ", ".join(sorted(missing)[:8]))
            skin_id = str(skin.get("id") or f"{mesh_id}_skin")
            _ctx().graph.skins[skin_id] = skin
            imported.append(skin_id)
        if imported:
            _ctx().changed()
        return imported

    def transfer_skin_weights_from_selection(self):
        selection = _ctx().selection()
        if len(selection) < 2:
            return False
        target = selection[-1]
        if any(str(skin.get("mesh_id") or "") == target for skin in _ctx().graph.skins.values()):
            return False
        source_skin = next((skin for skin in _ctx().graph.skins.values()
                            if str(skin.get("mesh_id") or "") in selection[:-1]), None)
        if source_skin is None:
            return False
        _ctx().checkpoint("Transfer skin weights")
        skin_id = _ctx().graph.add_skin(
            target, list(source_skin.get("joint_ids") or []),
            skin_id=f"{target}_skin",
            inverse_bind_blob=str(source_skin.get("inverse_bind_blob") or ""),
            weights_blob=str(source_skin.get("weights_blob") or ""),
        )
        _ctx().graph.skins[skin_id]["weight_overrides"] = copy.deepcopy(source_skin.get("weight_overrides") or {})
        _ctx().changed()
        return {"skinCluster": skin_id, "influences": list(source_skin.get("joint_ids") or [])}


class TCJointsFacade:
    def find_skinned_or_top_joints(self, namespace=""):
        return [joint_id for joint_id, joint in _ctx().graph.joints.items() if not str(joint.get("parent_id") or "")]


class TCDagFacade:
    def disable_evaluation(self): return None
    def enable_evaluation(self): return None


cmds = TCCmdsFacade()
setup_hik = TCSetupHikFacade()
create_rig = TCCreateRigFacade()
rig_template = TCRigTemplateFacade()
skinning_utils = TCSkinningUtilsFacade()
joints = TCJointsFacade()
dag = TCDagFacade()
omui = SimpleNamespace(MQtUtil=SimpleNamespace(mainWindow=lambda: 0))


__all__ = [
    "bind_tc_hik_host", "cmds", "create_rig", "dag", "joints", "omui",
    "rig_template", "setup_hik", "skinning_utils",
]

