"""DCC-neutral character definition and rigging workspace contracts.

The UI and saved scene data use these operation keys and payloads. Host
adapters are responsible for translating them to TC graph edits, maya.cmds,
or pyfbsdk calls without leaking host APIs into the shared UI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Iterable, Protocol


RIGGING_WORKSPACE_SCHEMA = "tech_connector.rigging_workspace.v1"
CHARACTER_DEFINITION_SCHEMA = "tech_connector.character_definition.v1"


@dataclass(frozen=True)
class RiggingCapability:
    key: str
    label: str
    category: str
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    engine_transfer: str = "bake"


_CAPABILITY_ROWS = (
    ("definition.auto_map", "Auto Map Skeleton", "definition", (), ("root_joint", "profile"), "metadata"),
    ("definition.assign_slot", "Assign Joint To Slot", "definition", ("slot", "joint"), (), "metadata"),
    ("definition.clear_slot", "Clear Slot", "definition", ("slot",), (), "metadata"),
    ("definition.mirror_slots", "Mirror Slot Assignments", "definition", (), ("source_side",), "metadata"),
    ("definition.validate", "Validate Character Definition", "definition", ("mapping",), (), "metadata"),
    ("definition.set_reference_pose", "Set Reference Pose", "definition", (), ("pose",), "skeleton"),
    ("definition.import", "Import Character Definition", "definition", ("definition",), (), "metadata"),
    ("definition.export", "Export Character Definition", "definition", (), ("path",), "metadata"),
    ("rig.build_full", "Build Full Control Rig", "build", ("definition",), ("modules", "options"), "bake"),
    ("rig.build_module", "Build Rig Module", "build", ("module", "definition"), ("options",), "bake"),
    ("rig.remove_module", "Remove Rig Module", "build", ("module",), (), "bake"),
    ("rig.rebuild_module", "Rebuild Rig Module", "build", ("module", "definition"), ("options",), "bake"),
    ("rig.create_control", "Create Control", "controls", ("target",), ("shape", "size", "parent"), "bake"),
    ("rig.edit_control_shape", "Edit Control Shape", "controls", ("control",), ("shape", "cv_positions"), "bake"),
    ("rig.create_ik_fk_limb", "Create IK/FK Limb", "solvers", ("start", "mid", "end"), ("pole", "spaces"), "bake"),
    ("rig.set_ik_fk_blend", "Set IK/FK Blend", "solvers", ("limb", "blend"), (), "bake"),
    ("rig.create_reverse_foot", "Create Reverse Foot", "solvers", ("ankle", "ball", "toe"), ("heel", "bank"), "bake"),
    ("rig.create_ribbon", "Create Ribbon Rig", "solvers", ("joint_chain",), ("control_count",), "bake"),
    ("rig.create_twist", "Create Twist Distribution", "solvers", ("start", "end"), ("twist_joints",), "bake"),
    ("rig.create_motion_path", "Create Motion Path Rig", "solvers", ("target", "curve"), ("follow",), "bake"),
    ("rig.create_curve_joints", "Create Joints Along Curve", "solvers", ("curve",), ("joint_count", "keep_attached", "name_prefix"), "bake"),
    ("rig.create_space_switch", "Create Space Switch", "constraints", ("driven", "targets"), ("mode",), "bake"),
    ("rig.set_space", "Set Active Space", "constraints", ("space_switch", "space"), (), "bake"),
    ("rig.create_constraint", "Create Constraint", "constraints", ("type", "drivers", "driven"), ("axes", "offset"), "bake"),
    ("rig.create_mesh_attachment", "Constrain To Mesh", "constraints", ("driven", "mesh"), ("uv", "normal"), "bake"),
    ("rig.create_pose_reader", "Create Pose Reader", "deformation", ("driver",), ("axis", "range"), "bake"),
    ("skin.surface_spatial_smooth_brush", "Surface Spatial Smooth Brush", "deformation", (),
     ("radius", "strength", "iterations", "max_influences", "normal_angle", "max_neighbors"), "metadata"),
    ("rig.create_face_module", "Create Facial Rig Module", "facial", ("module", "definition"), ("options",), "bake"),
    ("rig.store_connections", "Store Module Connections", "build", ("module",), (), "metadata"),
    ("rig.restore_connections", "Restore Module Connections", "build", ("module",), (), "metadata"),
    ("retarget.create_definition", "Create Retarget Definition", "retarget", ("mapping",), ("name",), "metadata"),
    ("retarget.validate_definition", "Validate Retarget Definition", "retarget", ("definition",), (), "metadata"),
    ("retarget.solve_pose", "Solve Retarget Pose", "retarget", ("source", "target"), ("root_motion", "scale"), "bake"),
    ("retarget.preview", "Preview Retarget", "retarget", ("source", "target"), ("take",), "bake"),
    ("retarget.bake", "Bake Retargeted Animation", "retarget", ("source", "target", "range"), ("sample_rate",), "bake"),
    ("retarget.transfer_take", "Transfer Animation Take", "retarget", ("take", "target"), ("timecode",), "animation"),
)


RIGGING_CAPABILITIES: dict[str, RiggingCapability] = {
    row[0]: RiggingCapability(*row) for row in _CAPABILITY_ROWS
}


REQUIRED_BODY_SLOTS = (
    "Reference", "Hips", "Spine", "Neck", "Head",
    "LeftArm", "LeftForeArm", "LeftHand",
    "RightArm", "RightForeArm", "RightHand",
    "LeftUpLeg", "LeftLeg", "LeftFoot",
    "RightUpLeg", "RightLeg", "RightFoot",
)

OPTIONAL_BODY_SLOTS = (
    "Spine1", "Spine2", "Spine3", "Neck1",
    "LeftShoulder", "RightShoulder", "LeftToeBase", "RightToeBase",
    "LeftArmRoll", "RightArmRoll", "LeftForeArmRoll", "RightForeArmRoll",
    "LeftUpLegRoll", "RightUpLegRoll", "LeftLegRoll", "RightLegRoll",
)

FINGER_NAMES = ("Thumb", "Index", "Middle", "Ring", "Pinky")
FINGER_SLOTS = tuple(
    f"{side}Hand{finger}{index}"
    for side in ("Left", "Right")
    for finger in FINGER_NAMES
    for index in range(1, 5)
) + tuple(
    f"{side}InHand{finger}"
    for side in ("Left", "Right")
    for finger in FINGER_NAMES[1:]
)

FACE_SLOTS = (
    "Jaw", "LeftEye", "RightEye", "LeftBrow", "RightBrow",
    "LeftEyeLidOuter", "LeftEyeLidUpper", "LeftEyeLidInner", "LeftEyeLidLower",
    "RightEyeLidOuter", "RightEyeLidUpper", "RightEyeLidInner", "RightEyeLidLower",
    "UpperLipCenter", "LowerLipCenter", "LeftLipCorner", "RightLipCorner",
    "UpperTeeth", "LowerTeeth", "NoseRoot",
)

ALL_CHARACTER_SLOTS = REQUIRED_BODY_SLOTS + OPTIONAL_BODY_SLOTS + FINGER_SLOTS + FACE_SLOTS


@dataclass
class CharacterDefinition:
    name: str
    slots: dict[str, str] = field(default_factory=dict)
    reference_pose: dict[str, list[float]] = field(default_factory=dict)
    source_provider: str = "tech_connector"
    source_root: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CHARACTER_DEFINITION_SCHEMA,
            **asdict(self),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CharacterDefinition":
        if str(value.get("schema") or CHARACTER_DEFINITION_SCHEMA) != CHARACTER_DEFINITION_SCHEMA:
            raise ValueError("Unsupported character definition schema.")
        return cls(
            name=str(value.get("name") or "Character"),
            slots={str(key): str(node) for key, node in dict(value.get("slots") or {}).items() if node},
            reference_pose={
                str(key): [float(item) for item in matrix]
                for key, matrix in dict(value.get("reference_pose") or {}).items()
                if isinstance(matrix, (list, tuple)) and len(matrix) == 16
            },
            source_provider=str(value.get("source_provider") or "tech_connector"),
            source_root=str(value.get("source_root") or ""),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass
class CharacterDefinitionValidation:
    ok: bool
    missing_required: list[str] = field(default_factory=list)
    unknown_slots: list[str] = field(default_factory=list)
    missing_nodes: list[str] = field(default_factory=list)
    duplicate_nodes: dict[str, list[str]] = field(default_factory=dict)
    hierarchy_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiggingOperationResult:
    ok: bool
    capability: str
    host: str
    message: str = ""
    created_ids: list[str] = field(default_factory=list)
    changed_ids: list[str] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RiggingHostAdapter(Protocol):
    """The only host surface the shared rigging UI is allowed to call."""

    @property
    def host_id(self) -> str: ...

    def capabilities(self) -> dict[str, str]: ...

    def scene_joints(self) -> list[dict[str, Any]]: ...

    def selection(self) -> list[str]: ...

    def execute(self, capability: str, payload: dict[str, Any]) -> RiggingOperationResult: ...


def list_rigging_capabilities(category: str = "") -> list[dict[str, Any]]:
    requested = str(category or "").strip().lower()
    return [
        asdict(item)
        for item in RIGGING_CAPABILITIES.values()
        if not requested or item.category == requested
    ]


def validate_operation_payload(capability: str, payload: dict[str, Any]) -> list[str]:
    operation = RIGGING_CAPABILITIES.get(str(capability))
    if operation is None:
        return [f"Unknown rigging capability: {capability}"]
    missing = [name for name in operation.required_inputs if payload.get(name) in (None, "", [], {})]
    return [f"{capability} requires {name}" for name in missing]


def validate_character_definition(
    definition: CharacterDefinition | dict[str, Any],
    joints: Iterable[dict[str, Any]] = (),
) -> CharacterDefinitionValidation:
    item = definition if isinstance(definition, CharacterDefinition) else CharacterDefinition.from_dict(definition)
    known_slots = set(ALL_CHARACTER_SLOTS)
    unknown_slots = sorted(set(item.slots) - known_slots)
    missing_required = [slot for slot in REQUIRED_BODY_SLOTS if not item.slots.get(slot)]
    joint_rows = [dict(row) for row in joints if isinstance(row, dict)]
    known_nodes = {
        str(row.get("id") or row.get("native_id") or row.get("name") or "")
        for row in joint_rows
    }
    missing_nodes = sorted({node for node in item.slots.values() if known_nodes and node not in known_nodes})
    slots_by_node: dict[str, list[str]] = {}
    for slot, node in item.slots.items():
        slots_by_node.setdefault(str(node), []).append(str(slot))
    duplicate_nodes = {
        node: sorted(slots) for node, slots in slots_by_node.items() if node and len(slots) > 1
    }
    hierarchy_errors = _validate_required_hierarchy(item.slots, joint_rows)
    warnings = []
    if not item.reference_pose:
        warnings.append("No reference pose has been captured; retarget offsets will use the current rest pose.")
    return CharacterDefinitionValidation(
        ok=not (missing_required or unknown_slots or missing_nodes or duplicate_nodes or hierarchy_errors),
        missing_required=missing_required,
        unknown_slots=unknown_slots,
        missing_nodes=missing_nodes,
        duplicate_nodes=duplicate_nodes,
        hierarchy_errors=hierarchy_errors,
        warnings=warnings,
    )


def auto_map_character(
    joints: Iterable[dict[str, Any]],
    *,
    name: str = "Character",
    source_provider: str = "tech_connector",
    source_root: str = "",
) -> CharacterDefinition:
    """Infer semantic slots from names, sides, and hierarchy without a DCC API."""
    rows = [dict(row) for row in joints if isinstance(row, dict)]
    candidates: dict[str, list[tuple[int, str]]] = {slot: [] for slot in ALL_CHARACTER_SLOTS}
    for row in rows:
        node_id = str(row.get("id") or row.get("native_id") or row.get("name") or "")
        if not node_id:
            continue
        normalized = _normalized_joint_name(str(row.get("name") or node_id))
        depth = int(row.get("depth", 0) or 0)
        for slot in ALL_CHARACTER_SLOTS:
            score = _slot_name_score(slot, normalized, depth)
            if score > 0:
                candidates[slot].append((score, node_id))
    slots: dict[str, str] = {}
    used: set[str] = set()
    for slot in ALL_CHARACTER_SLOTS:
        for _score, node_id in sorted(candidates[slot], key=lambda value: (-value[0], value[1].lower())):
            if node_id not in used:
                slots[slot] = node_id
                used.add(node_id)
                break
    reference_pose = {}
    for row in rows:
        node_id = str(row.get("id") or row.get("native_id") or row.get("name") or "")
        matrix = row.get("world_matrix") or row.get("local_matrix")
        if node_id in used and isinstance(matrix, (list, tuple)) and len(matrix) == 16:
            reference_pose[node_id] = [float(value) for value in matrix]
    return CharacterDefinition(
        name=str(name or "Character"),
        slots=slots,
        reference_pose=reference_pose,
        source_provider=str(source_provider or "tech_connector"),
        source_root=str(source_root or ""),
        metadata={"mapping_method": "name_and_topology", "joint_count": len(rows)},
    )


def mirror_character_slots(definition: CharacterDefinition, source_side: str = "left") -> CharacterDefinition:
    source = str(source_side or "left").strip().lower()
    if source not in {"left", "right"}:
        raise ValueError("source_side must be left or right")
    from_prefix, to_prefix = ("Left", "Right") if source == "left" else ("Right", "Left")
    mirrored = CharacterDefinition.from_dict(definition.to_dict())
    for slot, node in list(definition.slots.items()):
        if slot.startswith(from_prefix):
            mirrored.slots[slot.replace(from_prefix, to_prefix, 1)] = _mirror_node_name(node)
    mirrored.metadata["last_mirror_source"] = source
    return mirrored


class RiggingWorkspaceController:
    """Shared controller used by embedded and standalone rigging windows."""

    def __init__(self, adapter: RiggingHostAdapter):
        self.adapter = adapter

    @property
    def host_id(self) -> str:
        return self.adapter.host_id

    def capability_status(self) -> dict[str, str]:
        reported = dict(self.adapter.capabilities())
        return {key: str(reported.get(key) or "unsupported") for key in RIGGING_CAPABILITIES}

    def run(self, capability: str, **payload: Any) -> RiggingOperationResult:
        errors = validate_operation_payload(capability, payload)
        if errors:
            return RiggingOperationResult(False, capability, self.host_id, "; ".join(errors))
        status = self.capability_status().get(capability, "unsupported")
        if status not in {"native", "translated", "bridge", "bake"}:
            return RiggingOperationResult(
                False,
                capability,
                self.host_id,
                f"{capability} is {status} on {self.host_id}.",
            )
        return self.adapter.execute(capability, payload)


def _validate_required_hierarchy(slots: dict[str, str], joints: list[dict[str, Any]]) -> list[str]:
    parent_by_id = {
        str(row.get("id") or row.get("native_id") or row.get("name") or ""):
        str(row.get("parent_id") or row.get("parent_native_id") or row.get("parent") or "")
        for row in joints
    }
    if not parent_by_id:
        return []
    relationships = (
        ("Hips", "Spine"), ("Spine", "Neck"), ("Neck", "Head"),
        ("LeftArm", "LeftForeArm"), ("LeftForeArm", "LeftHand"),
        ("RightArm", "RightForeArm"), ("RightForeArm", "RightHand"),
        ("LeftUpLeg", "LeftLeg"), ("LeftLeg", "LeftFoot"),
        ("RightUpLeg", "RightLeg"), ("RightLeg", "RightFoot"),
    )
    errors = []
    for ancestor_slot, descendant_slot in relationships:
        ancestor = slots.get(ancestor_slot, "")
        descendant = slots.get(descendant_slot, "")
        if ancestor and descendant and not _is_ancestor(ancestor, descendant, parent_by_id):
            errors.append(f"{descendant_slot} is not below {ancestor_slot}")
    return errors


def _is_ancestor(ancestor: str, descendant: str, parent_by_id: dict[str, str]) -> bool:
    cursor = parent_by_id.get(descendant, "")
    visited = {descendant}
    while cursor and cursor not in visited:
        if cursor == ancestor:
            return True
        visited.add(cursor)
        cursor = parent_by_id.get(cursor, "")
    return False


def _normalized_joint_name(value: str) -> str:
    leaf = str(value).split("|")[-1].split(":")[-1]
    return re.sub(r"[^a-z0-9]+", " ", leaf.lower()).strip()


def _slot_name_score(slot: str, name: str, depth: int) -> int:
    side = "left" if slot.startswith("Left") else "right" if slot.startswith("Right") else ""
    body = slot[len(side):] if side else slot
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", body)
    tokens = set(name.split())
    score = 0
    side_tokens = {"left": {"l", "lf", "left"}, "right": {"r", "rt", "right"}}
    if side:
        if tokens & side_tokens[side]:
            score += 25
        elif tokens & side_tokens["right" if side == "left" else "left"]:
            return 0
    aliases = {
        "Reference": ("root", "origin", "reference"),
        "Hips": ("hips", "hip", "pelvis"),
        "Spine": ("spine", "spn"),
        "Neck": ("neck",),
        "Head": ("head",),
        "Shoulder": ("shoulder", "clavicle"),
        "Arm": ("upperarm", "upper arm", "arm"),
        "ForeArm": ("forearm", "lowerarm", "lower arm", "elbow"),
        "Hand": ("hand", "wrist"),
        "UpLeg": ("upleg", "upperleg", "upper leg", "thigh"),
        "Leg": ("lowerleg", "lower leg", "calf", "knee", "shin"),
        "Foot": ("foot", "ankle"),
        "ToeBase": ("toe", "ball"),
        "Eye": ("eye",), "Brow": ("brow",), "Jaw": ("jaw",),
    }
    compact = name.replace(" ", "")
    if body.startswith("Arm") and any(token in compact for token in ("forearm", "lowerarm", "elbow")):
        return 0
    if body.startswith("ForeArm") and any(token in compact for token in ("upperarm", "shoulder")):
        return 0
    if body.startswith("UpLeg") and any(token in compact for token in ("lowerleg", "knee", "calf", "shin")):
        return 0
    if body == "Leg" and any(token in compact for token in ("upperleg", "thigh", "upleg")):
        return 0
    matched = False
    for key, values in aliases.items():
        if key == "Leg" and "UpLeg" in body:
            continue
        if key == "Arm" and "ForeArm" in body:
            continue
        if key.lower() in body.lower() and any(value.replace(" ", "") in compact for value in values):
            score += 50
            matched = True
    for word in words:
        if word.lower() in tokens or word.lower() in compact:
            score += 8
            matched = True
    digits = re.findall(r"\d+", slot)
    if digits and digits[-1] in tokens:
        score += 12
    if "roll" in slot.lower() and not ({"roll", "twist"} & tokens):
        return 0
    if "roll" not in slot.lower() and ({"roll", "twist"} & tokens):
        score -= 30
    if slot == "Reference":
        score += max(0, 10 - depth)
    return score if matched else 0


def _mirror_node_name(value: str) -> str:
    replacements = (
        (r"(^|[|:_])left(?=$|[|:_])", r"\1right"),
        (r"(^|[|:_])Left(?=$|[|:_])", r"\1Right"),
        (r"(^|[|:_])l(?=$|[|:_])", r"\1r"),
        (r"(^|[|:_])L(?=$|[|:_])", r"\1R"),
    )
    output = str(value)
    for pattern, replacement in replacements:
        changed = re.sub(pattern, replacement, output)
        if changed != output:
            return changed
    return output


__all__ = [
    "ALL_CHARACTER_SLOTS", "CHARACTER_DEFINITION_SCHEMA", "CharacterDefinition",
    "CharacterDefinitionValidation", "FACE_SLOTS", "FINGER_SLOTS", "OPTIONAL_BODY_SLOTS",
    "REQUIRED_BODY_SLOTS", "RIGGING_CAPABILITIES", "RIGGING_WORKSPACE_SCHEMA",
    "RiggingCapability", "RiggingHostAdapter", "RiggingOperationResult",
    "RiggingWorkspaceController", "auto_map_character", "list_rigging_capabilities",
    "mirror_character_slots", "validate_character_definition", "validate_operation_payload",
]
