# coding=utf-8
"""
    Unit Test Suite for Unreal AnimGraph Wiring & On-The-Fly Animation Ingestion Engine.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.unreal_animgraph_wiring_engine import UnrealAnimGraphWiringEngine


class TestUnrealAnimGraphWiringEngine(unittest.TestCase):
    """
        Test case suite for UnrealAnimGraphWiringEngine.
    """

    def setUp(self):
        """
            Sets up engine instance.
        """
        self.abp_path = "/Game/Variant_Combat/Anims/ABP_Manny_Combat"
        self.skeleton_path = "/Game/MetaHumans/Common/Female/Medium/NormalWeight/Body/metahuman_base_skel"
        self.engine = UnrealAnimGraphWiringEngine(anim_bp_path=self.abp_path)

    def test_on_the_fly_anim_download_and_discovery(self):
        """
            Tests on-the-fly downloading of missing animation clips over HTTPS.
        """
        keys = ["idle", "climb_up", "vault"]
        clips = self.engine.discover_or_download_anim_sequences(self.skeleton_path, keys)

        self.assertEqual(len(clips), 3)
        self.assertIn("idle", clips)
        self.assertIn("climb_up", clips)
        # Verify on-the-fly downloaded asset path for missing clip
        self.assertTrue("Duck.glb" in clips["climb_up"] or "AnimSequence" in clips["climb_up"])

    def test_generate_animgraph_wiring_script(self):
        """
            Tests generation of Unreal Engine Python script for Output Pose wiring.
        """
        anim_map = {"climb_idle": "/Game/Anims/Idle", "climb_up": "/Game/Anims/Up"}
        script = self.engine.generate_unreal_animgraph_wiring_script(self.skeleton_path, anim_map)

        self.assertIn("import unreal", script)
        self.assertIn("animgraph_wired", script)
        self.assertIn("output_pose_connected", script)


if __name__ == "__main__":
    unittest.main()
