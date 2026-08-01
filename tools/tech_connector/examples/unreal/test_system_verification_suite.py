# coding=utf-8
"""
    Unit Test Suite for Comprehensive System & Action Verification Suite.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.skeleton_compatibility_service import SkeletonCompatibilityService
from tech_connector.services.unreal.unreal_editor_status_service import UnrealEditorStatusService
from tech_connector.services.system_verification_suite import SystemVerificationSuite


class TestSystemVerificationSuite(unittest.TestCase):
    """
        Test case suite for SystemVerificationSuite.
    """

    def setUp(self):
        """
            Sets up test suite instances.
        """
        self.skel_service = SkeletonCompatibilityService()
        self.status_service = UnrealEditorStatusService()
        self.verification_suite = SystemVerificationSuite(system_name="TraversalAndCombat")

    def test_manny_skeleton_compatibility(self):
        """
            Tests verifying animation sequence plugs against Manny Skeleton (ABP_Manny_Combat).
        """
        anim_map = {
            "climb_idle": "/Game/AIStudio/GeneratedAnims/Combat/AI_DodgeRoll",
            "climb_up": "/Game/AIStudio/GeneratedAnimations/OpenMocap/CMU/A_CMU_01_03_ClimbHang_Manny",
            "vault": "/Game/AIStudio/GeneratedAnimations/Retargeted/A_CMU_01_03_playground___climb_hang_swing_SKM_Manny_NoGeo"
        }
        audit = self.skel_service.audit_system_animation_plugs(anim_map, "/Game/Variant_Combat/Anims/ABP_Manny_Combat")

        if not audit["all_plugs_valid"] and any(
            row.get("missing_evidence") for row in audit.get("plug_audits", [])
        ):
            self.skipTest("Live Unreal skeleton metadata is unavailable for this integration check.")
        self.assertTrue(audit["all_plugs_valid"])
        self.assertEqual(audit["total_plugs_checked"], 3)

    def test_editor_status_inspection(self):
        """
            Tests inspecting Unreal Engine editor process status.
        """
        status = self.status_service.check_unreal_editor_status()
        self.assertIn("editor_open", status)
        self.assertIn("execution_mode", status)

    def test_full_system_verification_suite(self):
        """
            Tests running 5-point verification audit.
        """
        anim_map = {
            "idle": "/Game/AIStudio/GeneratedAnims/Combat/AI_DodgeRoll",
            "walk": "/Game/AIStudio/GeneratedAnimations/OpenMocap/CMU/A_CMU_01_03_ClimbHang_Manny"
        }
        res = self.verification_suite.execute_full_system_validation(anim_map, input_key="N")

        if not res["ok"] and any(
            row.get("missing_evidence")
            for row in res.get("manny_skeleton_audit", {}).get("plug_audits", [])
        ):
            self.skipTest("Live Unreal skeleton metadata is unavailable for this integration check.")
        self.assertTrue(res["ok"])
        self.assertEqual(res["verification_status"], "PASSED_5_POINT_AUDIT")
        self.assertIn("qa_report", res)
        self.assertIn("markdown_report", res["qa_report"])


if __name__ == "__main__":
    unittest.main()
