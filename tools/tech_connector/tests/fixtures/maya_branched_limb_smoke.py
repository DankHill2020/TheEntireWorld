"""Live Maya standalone smoke test for exact limb-chain duplication."""

from __future__ import annotations

import sys
from pathlib import Path

import maya.standalone


TOOLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(TOOLS_ROOT))
maya.standalone.initialize(name="python")

from maya import cmds  # noqa: E402
from maya_tools.Rigging import create_rig_core  # noqa: E402


cmds.file(new=True, force=True)
root_parent = cmds.group(empty=True, name="hipswing_ctrl")
cmds.group(empty=True, name="origin_ctrl")

cmds.select(clear=True)
thigh = cmds.joint(name="l_thigh", position=(0, 10, 0))
knee = cmds.joint(name="l_knee", position=(0, 5, 1))
ankle = cmds.joint(name="l_ankle", position=(0, 0, 0))

cmds.select(knee)
twist = cmds.joint(name="l_knee_twist", position=(0, 3.8, 0.8))
cmds.joint(name="l_knee_twist1", position=(0, 2.5, 0.5))
cmds.joint(name="l_knee_twist2", position=(0, 1.2, 0.2))

result = create_rig_core.create_ik_fk_limb([thigh, knee, ankle], root_parent)

assert result["fk_chain"] == ["l_thigh_fk", "l_knee_fk", "l_ankle_fk"], result["fk_chain"]
assert result["ik_chain"] == ["l_thigh_ik", "l_knee_ik", "l_ankle_ik"], result["ik_chain"]
assert result["driver_chain"] == ["l_thigh_driver", "l_knee_driver", "l_ankle_driver"], result["driver_chain"]
assert not (cmds.ls("l_knee_twist_fk", type="joint") or [])
assert not (cmds.ls("l_knee_twist_fk_ctrl", long=True) or [])
assert len(set(result["fk_controls"])) == 3
print("MAYA_BRANCHED_LIMB_SMOKE_OK")

maya.standalone.uninitialize()
