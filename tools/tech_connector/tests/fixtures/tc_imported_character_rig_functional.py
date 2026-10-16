"""Pose-test the TC-native graph built from the production Maya character."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np


TOOLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_ROOT))

from tech_connector.game_engine.authoring.rig_evaluation_service import evaluate_rig_graph  # noqa: E402
from tech_connector.game_engine.integration.tc_rigging_host_adapter import TCRiggingHostAdapter  # noqa: E402
from tech_connector.game_engine.scene.federated_scene_service import EditableRigGraph  # noqa: E402


if len(sys.argv) < 3:
    raise RuntimeError("Expected rig graph and source snapshot paths")
graph_path = Path(sys.argv[1]).resolve()
snapshot_path = Path(sys.argv[2]).resolve()
graph = EditableRigGraph.from_dict(json.loads(graph_path.read_text(encoding="utf-8")))
snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
slots = snapshot["slots"]
adapter = TCRiggingHostAdapter(graph)


def evaluated():
    result = evaluate_rig_graph(graph)
    assert not result.errors, result.errors
    return result


def translation(result, node_id: str) -> np.ndarray:
    return np.asarray(result.world_matrices[node_id], dtype=np.float64).reshape(4, 4)[3, :3]


left_arm = slots["LeftArm"]
left_forearm = slots["LeftForeArm"]
left_hand = slots["LeftHand"]

# IK solver motion.
switch = adapter.execute("rig.set_ik_fk_blend", {"limb": "left_arm", "blend": 1.0})
assert switch.ok, switch.to_dict()
before = evaluated()
before_hand = translation(before, left_hand)
before_forearm = np.asarray(before.world_matrices[left_forearm], dtype=np.float64)
target = graph.nodes["left_arm_ik_ctrl"]["attributes"]["matrix"]
target[14] += max(float(np.linalg.norm(translation(before, left_forearm) - translation(before, left_arm))) * 0.2, 0.5)
after = evaluated()
ik_hand_delta = float(np.linalg.norm(translation(after, left_hand) - before_hand))
ik_forearm_delta = float(np.max(np.abs(np.asarray(after.world_matrices[left_forearm]) - before_forearm)))
assert ik_hand_delta > 1.0e-3, ik_hand_delta
assert ik_forearm_delta > 1.0e-4, ik_forearm_delta

# FK constraint motion. Rotate the upper-arm FK control around local Z and
# verify that the constrained deform hierarchy changes with IK disabled.
switch = adapter.execute("rig.set_ik_fk_blend", {"limb": "left_arm", "blend": 0.0})
assert switch.ok, switch.to_dict()
before = evaluated()
before_upper = np.asarray(before.world_matrices[left_arm], dtype=np.float64)
before_hand = translation(before, left_hand)
control_id = f"left_arm_{graph.joints[left_arm]['name']}_fk_ctrl"
control_matrix = np.asarray(graph.nodes[control_id]["attributes"]["matrix"], dtype=np.float64).reshape(4, 4)
angle = math.radians(12.0)
rotation = np.asarray([
    [math.cos(angle), math.sin(angle), 0.0, 0.0],
    [-math.sin(angle), math.cos(angle), 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
])
graph.nodes[control_id]["attributes"]["matrix"] = (control_matrix @ rotation).reshape(-1).tolist()
after = evaluated()
fk_upper_delta = float(np.max(np.abs(np.asarray(after.world_matrices[left_arm]) - before_upper)))
fk_hand_delta = float(np.linalg.norm(translation(after, left_hand) - before_hand))
assert fk_upper_delta > 1.0e-4, fk_upper_delta
assert fk_hand_delta > 1.0e-3, fk_hand_delta

print("TC_IMPORTED_CHARACTER_RIG_FUNCTIONAL_OK=" + json.dumps({
    "fk_hand_position_delta": fk_hand_delta,
    "fk_upperarm_matrix_delta": fk_upper_delta,
    "ik_forearm_matrix_delta": ik_forearm_delta,
    "ik_hand_position_delta": ik_hand_delta,
}, sort_keys=True))
