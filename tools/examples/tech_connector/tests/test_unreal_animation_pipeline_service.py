from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from unreal_tools.animation import retarget_imported_animations_if_needed


class TestUnrealAnimationPipelineService(unittest.TestCase):
    def test_retarget_uses_meshes_resolved_by_inspection(self) -> None:
        report = {
            "ok": True,
            "source_skeletal_mesh_path": "/Game/Source/SK_Source",
            "target_skeletal_mesh_path": "/Game/Target/SK_Target",
            "compatible_animation_paths": [],
            "assets": [
                {
                    "asset_path": "/Game/Imported/A_Run",
                    "class": "AnimSequence",
                    "retarget_required": True,
                }
            ],
        }
        with patch(
            "unreal_tools.animation.retarget_animation",
            return_value=json.dumps(
                {
                    "ok": True,
                    "output_asset": "/Game/Retargeted/A_Run_Retargeted",
                }
            ),
        ) as retarget:
            result = json.loads(
                retarget_imported_animations_if_needed(report)
            )

        self.assertTrue(result["ok"])
        retarget.assert_called_once_with(
            "/Game/Imported/A_Run",
            "/Game/Source/SK_Source",
            "/Game/Target/SK_Target",
            "/Game/Animations/Retargeted",
            retargeter_path="",
            save=True,
        )

    def test_retarget_blocks_truthfully_when_required_mesh_is_unresolved(self) -> None:
        report = {
            "ok": True,
            "source_skeletal_mesh_path": "",
            "target_skeletal_mesh_path": "/Game/Target/SK_Target",
            "source_skeletal_mesh_candidates": [],
            "target_skeletal_mesh_candidates": ["/Game/Target/SK_Target"],
            "compatible_animation_paths": [],
            "assets": [
                {
                    "asset_path": "/Game/Imported/A_Run",
                    "class": "AnimSequence",
                    "retarget_required": True,
                }
            ],
        }

        result = json.loads(retarget_imported_animations_if_needed(report))

        self.assertFalse(result["ok"])
        self.assertEqual(
            "retarget_target_resolution_required",
            result["status"],
        )
        self.assertEqual(["source_skeletal_mesh_path"], result["missing"])


if __name__ == "__main__":
    unittest.main()
