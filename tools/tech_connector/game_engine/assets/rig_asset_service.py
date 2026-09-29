"""First-class Control Rig, IK Rig, and IK Retargeter asset contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Iterable, Mapping


IK_SOLVERS = ("two_bone", "fabrik", "ccd", "spline", "full_body")
CONTROL_RIG_NODE_TYPES = (
    "control", "get_transform", "set_transform", "two_bone_ik", "fabrik", "aim",
    "parent_constraint", "blend_transform", "float_math", "vector_math", "sequence", "output_pose",
)


@dataclass(frozen=True)
class RigAssetIssue:
    severity: str
    code: str
    message: str
    fix: str = ""


def automatic_ik_chains(bones: Iterable[Mapping[str, Any] | str]) -> list[dict[str, Any]]:
    rows: list[dict[str, str]] = []
    for value in bones:
        if isinstance(value, Mapping):
            name = str(value.get("name") or value.get("id") or "").strip()
            parent = str(value.get("parent") or value.get("parent_id") or "").strip()
        else:
            name, parent = str(value).strip(), ""
        if name:
            rows.append({"name": name, "parent": parent})
    names = {item["name"] for item in rows}

    def find(*tokens: str) -> str:
        candidates = [name for name in names if all(token in name.casefold() for token in tokens)]
        return sorted(candidates, key=lambda value: (len(value), value.casefold()))[0] if candidates else ""

    definitions = (
        ("Left Arm", find("upperarm", "l"), find("hand", "l"), "two_bone"),
        ("Right Arm", find("upperarm", "r"), find("hand", "r"), "two_bone"),
        ("Left Leg", find("thigh", "l"), find("foot", "l"), "two_bone"),
        ("Right Leg", find("thigh", "r"), find("foot", "r"), "two_bone"),
        ("Spine", find("pelvis"), find("head"), "fabrik"),
    )
    return [
        {"name": name, "start_bone": start, "end_bone": end, "solver": solver,
         "goal": name.replace(" ", "_") + "_Goal", "pole": name.replace(" ", "_") + "_Pole",
         "settings": {"iterations": 12, "precision": 0.001, "stretch": 0.0}}
        for name, start, end, solver in definitions if start and end and start != end
    ]


def validate_control_rig_properties(properties: Mapping[str, Any]) -> tuple[RigAssetIssue, ...]:
    values = dict(properties or {})
    issues: list[RigAssetIssue] = []
    if not values.get("skeleton_id"):
        issues.append(RigAssetIssue("error", "missing_skeleton", "Assign the Skeleton evaluated by this Control Rig."))
    graph = dict(values.get("graph") or {})
    nodes = [dict(item) for item in graph.get("nodes") or () if isinstance(item, Mapping)]
    node_ids = [str(item.get("id") or "") for item in nodes]
    if not nodes:
        issues.append(RigAssetIssue("warning", "empty_graph", "Control Rig contains no graph nodes.", "Add controls and an Output Pose node."))
    if len(node_ids) != len(set(node_ids)) or any(not value for value in node_ids):
        issues.append(RigAssetIssue("error", "invalid_node_ids", "Control Rig node IDs must be non-empty and unique."))
    unknown = sorted({str(item.get("opcode") or item.get("type") or "") for item in nodes} - set(CONTROL_RIG_NODE_TYPES))
    if unknown:
        issues.append(RigAssetIssue("error", "unsupported_nodes", "Unsupported Control Rig nodes: " + ", ".join(unknown)))
    for edge in graph.get("connections") or graph.get("edges") or ():
        if str(edge.get("source") or "") not in node_ids or str(edge.get("target") or "") not in node_ids:
            issues.append(RigAssetIssue("error", "broken_edge", "Control Rig graph contains an edge with a missing node."))
            break
    if nodes and not any(str(item.get("opcode") or item.get("type") or "") == "output_pose" for item in nodes):
        issues.append(RigAssetIssue("error", "missing_output", "Control Rig requires an Output Pose node."))
    return tuple(issues)


def validate_ik_rig_properties(properties: Mapping[str, Any]) -> tuple[RigAssetIssue, ...]:
    values = dict(properties or {})
    issues: list[RigAssetIssue] = []
    if not values.get("skeleton_id"):
        issues.append(RigAssetIssue("error", "missing_skeleton", "Assign the Skeleton used by this IK Rig."))
    chains = [dict(item) for item in values.get("chains") or () if isinstance(item, Mapping)]
    names = [str(item.get("name") or "") for item in chains]
    if not chains:
        issues.append(RigAssetIssue("error", "missing_chains", "IK Rig contains no solver chains.", "Run Auto Generate Chains or add a chain."))
    if len(names) != len(set(names)) or any(not name for name in names):
        issues.append(RigAssetIssue("error", "invalid_chain_names", "IK chain names must be non-empty and unique."))
    known_bones = {str(item.get("name") or item.get("id") or "") for item in values.get("skeleton_bones") or () if isinstance(item, Mapping)}
    for chain in chains:
        name = str(chain.get("name") or "IK Chain")
        start, end = str(chain.get("start_bone") or ""), str(chain.get("end_bone") or "")
        if not start or not end or start == end:
            issues.append(RigAssetIssue("error", "invalid_chain", f"{name} requires different start and end bones."))
        if known_bones and ({start, end} - known_bones):
            issues.append(RigAssetIssue("error", "missing_chain_bone", f"{name} references a bone absent from the Skeleton."))
        solver = str(chain.get("solver") or "two_bone")
        if solver not in IK_SOLVERS:
            issues.append(RigAssetIssue("error", "unsupported_solver", f"{name} uses unsupported solver '{solver}'."))
    return tuple(issues)


def validate_ik_retargeter_properties(properties: Mapping[str, Any]) -> tuple[RigAssetIssue, ...]:
    values = dict(properties or {})
    issues: list[RigAssetIssue] = []
    if not values.get("source_ik_rig_id") or not values.get("target_ik_rig_id"):
        issues.append(RigAssetIssue("error", "missing_rig", "Assign both Source IK Rig and Target IK Rig."))
    mappings = [dict(item) for item in values.get("chain_mapping") or () if isinstance(item, Mapping)]
    sources, targets = set(), set()
    if not mappings:
        issues.append(RigAssetIssue("error", "missing_mapping", "No retarget chain mappings are authored."))
    for item in mappings:
        source, target = str(item.get("source") or ""), str(item.get("target") or "")
        if not source or not target:
            issues.append(RigAssetIssue("error", "invalid_mapping", "Every chain mapping requires source and target names."))
        if source in sources or target in targets:
            issues.append(RigAssetIssue("error", "duplicate_mapping", "A retarget chain may be mapped only once."))
        sources.add(source); targets.add(target)
    return tuple(issues)


def automatic_chain_mapping(source_chains: Iterable[Mapping[str, Any]], target_chains: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    target_by_key = {_chain_key(item.get("name")): str(item.get("name") or "") for item in target_chains}
    result = []
    for item in source_chains:
        source = str(item.get("name") or "")
        target = target_by_key.get(_chain_key(source), "")
        if source and target:
            result.append({"source": source, "target": target, "translation_mode": "scaled", "rotation_mode": "interpolated", "weight": 1.0})
    return result


def compile_rig_asset_payload(type_id: str, properties: Mapping[str, Any], *, platform: str = "desktop", quality: str = "high") -> bytes:
    values = dict(properties or {})
    validators = {
        "tc.control_rig": validate_control_rig_properties,
        "tc.ik_rig": validate_ik_rig_properties,
        "tc.ik_retargeter": validate_ik_retargeter_properties,
    }
    if type_id not in validators:
        raise KeyError(f"Unsupported rig asset type: {type_id}")
    errors = [item.message for item in validators[type_id](values) if item.severity == "error"]
    if errors:
        raise ValueError(f"{type_id} cannot be cooked: " + "; ".join(errors))
    body: dict[str, Any]
    if type_id == "tc.control_rig":
        body = {"skeleton_id": str(values["skeleton_id"]), "graph": dict(values.get("graph") or {}),
                "controls": list(values.get("controls") or ()), "variables": dict(values.get("variables") or {}),
                "lod_policy": dict(values.get("lod_policy") or {})}
    elif type_id == "tc.ik_rig":
        body = {"skeleton_id": str(values["skeleton_id"]), "retarget_root": str(values.get("retarget_root") or ""),
                "chains": list(values.get("chains") or ()), "goals": list(values.get("goals") or ()),
                "excluded_bones": list(values.get("excluded_bones") or ())}
    else:
        body = {"source_ik_rig_id": str(values["source_ik_rig_id"]), "target_ik_rig_id": str(values["target_ik_rig_id"]),
                "chain_mapping": list(values.get("chain_mapping") or ()),
                "source_retarget_pose": dict(values.get("source_retarget_pose") or {}),
                "target_retarget_pose": dict(values.get("target_retarget_pose") or {}),
                "root_settings": dict(values.get("root_settings") or {})}
    payload = {"schema": f"tech_connector.cooked_{type_id.removeprefix('tc.')}.v1", "platform": str(platform), "quality": str(quality), **body}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _chain_key(value: Any) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


__all__ = [
    "CONTROL_RIG_NODE_TYPES", "IK_SOLVERS", "RigAssetIssue", "automatic_chain_mapping",
    "automatic_ik_chains", "compile_rig_asset_payload", "validate_control_rig_properties",
    "validate_ik_retargeter_properties", "validate_ik_rig_properties",
]
