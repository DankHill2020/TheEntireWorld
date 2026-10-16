from __future__ import annotations

import ast
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[2]
CREATE_RIG_CORE = TOOLS_ROOT / "maya_tools" / "Rigging" / "create_rig_core.py"


def test_limb_volume_scale_stops_at_hands_ankles_and_toes() -> None:
    source = CREATE_RIG_CORE.read_text(encoding="utf-8")
    limb_body = source.split("def create_ik_fk_limb(", 1)[1].split(
        "def get_nose_joints(", 1
    )[0]

    assert "def _isolate_joint_from_parent_volume_scale(" in source
    assert "cmds.setAttr(f\"{joint}.segmentScaleCompensate\", True)" in source
    assert 'f"{parents[0]}.scale"' in source
    assert 'f"{joint}.inverseScale"' in source
    assert "for chain in (sel, fk_joints, ik_joints, driver_joints):" in limb_body
    assert "for joint in chain[ik_end_index:]:" in limb_body
    assert '"scale_isolated_joints"' in limb_body


def test_volume_scale_network_still_only_drives_two_fleshy_segments() -> None:
    source = CREATE_RIG_CORE.read_text(encoding="utf-8")
    stretch_body = source.split("def setup_ik_limb_stretch(", 1)[1].split(
        "def create_ik_fk_limb(", 1
    )[0]

    assert "for index, driven_joint in enumerate(ik_joints[:2]):" in stretch_body
    assert "ik_joints[2]" not in stretch_body.split(
        "volume_nodes = []", 1
    )[1].split("dimension_nodes =", 1)[0]
