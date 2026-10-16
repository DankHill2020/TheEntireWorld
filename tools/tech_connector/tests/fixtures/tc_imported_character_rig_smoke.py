"""Build a portable TC rig from a real Maya mesh snapshot and hierarchy."""

from __future__ import annotations

import json
import sys
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_ROOT))

from tech_connector.game_engine.authoring.rigging_workspace_service import (  # noqa: E402
    ALL_CHARACTER_SLOTS,
    CharacterDefinition,
)
from tech_connector.game_engine.integration.tc_rigging_host_adapter import (  # noqa: E402
    TCRiggingHostAdapter,
)
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph  # noqa: E402


if len(sys.argv) < 2:
    raise RuntimeError("Expected a Maya character snapshot path")
snapshot_path = Path(sys.argv[1]).resolve()
output_path = (
    Path(sys.argv[2]).resolve()
    if len(sys.argv) > 2
    else snapshot_path.with_name(snapshot_path.stem + "_rig_graph.json")
)
snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

graph = EditableRigGraph()
for row in snapshot["joints"]:
    parent = str(row.get("parent") or "")
    graph.add_joint(
        str(row["id"]),
        parent_id=parent if parent in graph.joints else "",
        local_matrix=row["local_matrix"],
        joint_id=str(row["id"]),
    )

mesh_data = snapshot["mesh"]
mesh_id = graph.add_node(
    mesh_data["name"],
    "geometry.mesh",
    node_id=mesh_data["name"],
    attributes={
        "bounds": mesh_data["bounds"],
        "vertex_count": int(mesh_data["vertex_count"]),
    },
)
slots = {
    slot: joint_id
    for slot, joint_id in snapshot["slots"].items()
    if slot in ALL_CHARACTER_SLOTS and joint_id in graph.joints
}
definition = CharacterDefinition(
    "IndianWomanCrossDcc",
    slots=slots,
    source_provider="maya",
    source_root="origin",
).to_dict()
adapter = TCRiggingHostAdapter(graph, selected_ids=[mesh_id])

validation = adapter.execute("definition.validate", {"mapping": definition})
assert validation.ok, validation.to_dict()
preview = adapter.execute("rig.place_joints", {
    "mesh": mesh_id,
    "definition": definition,
    "preview": True,
})
assert preview.ok and not preview.data["applied"], preview.to_dict()
placement = adapter.execute("rig.place_joints", {
    "definition": definition,
    "positions": preview.data["positions"],
})
assert placement.ok and placement.data["applied"], placement.to_dict()
assert len(placement.changed_ids) == len(preview.data["positions"])

first_pose = adapter.execute("rig.set_t_pose", {"definition": definition})
assert first_pose.ok, first_pose.to_dict()
core_ids = [
    slots[key]
    for key in (
        "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand",
        "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot",
    )
]
first_world = {joint_id: adapter._joint_world_matrix(joint_id) for joint_id in core_ids}
second_pose = adapter.execute("rig.set_t_pose", {"definition": definition})
assert second_pose.ok, second_pose.to_dict()
repeat_delta = max(
    abs(adapter._joint_world_matrix(joint_id)[index] - first_world[joint_id][index])
    for joint_id in core_ids
    for index in range(16)
)
assert repeat_delta < 1.0e-8, repeat_delta

modules = [
    "root", "pelvis", "spine", "neck", "head",
    "left_arm", "right_arm", "left_leg", "right_leg", "fingers",
]
build = adapter.execute("rig.build_full", {
    "definition": definition,
    "modules": modules,
})
assert build.ok, build.to_dict()
assert build.data["t_pose"]["ok"], build.to_dict()
assert build.data["modules"] == modules
for module in ("left_arm", "right_arm", "left_leg", "right_leg"):
    ik_control = graph.nodes.get(module + "_ik_ctrl")
    assert ik_control is not None
    attributes = ik_control["attributes"]
    assert attributes["world_oriented"] is True
    matrix = attributes["matrix"]
    assert matrix[0:12] == [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]

output_path.write_text(json.dumps(graph.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
print("TC_IMPORTED_CHARACTER_RIG_OK=" + json.dumps({
    "changed_joint_count": len(placement.changed_ids),
    "constraint_count": len(graph.constraints),
    "control_count": sum(
        str(node.get("node_type") or "") == "dag.control"
        for node in graph.nodes.values()
    ),
    "joint_count": len(graph.joints),
    "mesh": mesh_id,
    "output": str(output_path),
    "repeat_t_pose_delta": repeat_delta,
    "vertex_count": graph.nodes[mesh_id]["attributes"]["vertex_count"],
}, sort_keys=True))
