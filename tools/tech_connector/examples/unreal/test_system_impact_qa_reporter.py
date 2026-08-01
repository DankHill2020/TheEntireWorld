# coding=utf-8
"""
    Unit Test Suite for System Impact and QA Testing Reporter Engine.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.system_impact_qa_reporter import SystemImpactQAReporter


class TestSystemImpactQAReporter(unittest.TestCase):
    """
        Test case suite for SystemImpactQAReporter.
    """

    def test_report_generation(self):
        """
            Tests building a complete 4-section System Impact & QA Report.
        """
        reporter = SystemImpactQAReporter(
            system_name="Master Character Traversal & Combat",
            task_description="Consolidate Any-Wall Climbing, Parkour Vaulting, Grapple Hook, and Dodge Roll into BP_LesterPhoenix."
        )

        reporter.add_affected_asset("/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix", "Blueprint", "Modified")
        reporter.add_affected_asset("/Game/Variant_Combat/Anims/ABP_Manny_Combat", "AnimBlueprint", "Injected")

        reporter.add_modification_detail("Variables", "Added bIsClimbing, bIsVaulting, bIsGrappling, bIsDodgeRolling, ClimbSpeed.")
        reporter.add_modification_detail("Input Settings", "Configured Auto Receive Input = Player 0.")
        reporter.add_modification_detail("Movement Physics", "Configured CapsuleTrace across WorldStatic, WorldDynamic, PhysicsBody and LaunchCharacter for F Key.")

        reporter.add_test_step(1, "E Key", "Attach to any wall surface, hold W/S to climb up/down, press E to release.")
        reporter.add_test_step(2, "Space Key", "Press Space near low obstacles to vault over them.")
        reporter.add_test_step(3, "F Key", "Press F aiming at ledge/anchor to execute 2500cm/s launch zip impulse.")
        reporter.add_test_step(4, "C Key", "Press C while moving to perform directional dodge roll.")

        reporter.add_potential_impact("Character Movement Component", "Custom movement mode override may affect falling state if unreleased.", "Verify character falls normally when stepping off ledges.")
        reporter.add_potential_impact("Camera Boom Component", "Wall capsule trace could clip camera near tight corners.", "Verify camera distance during wall climbing in enclosed spaces.")

        report_dict = reporter.generate_report_dict()

        self.assertEqual(report_dict["system_name"], "Master Character Traversal & Combat")
        self.assertEqual(len(report_dict["affected_assets"]), 2)
        self.assertEqual(len(report_dict["modifications_detail"]), 3)
        self.assertEqual(len(report_dict["testing_instructions"]), 4)
        self.assertEqual(len(report_dict["potential_impacts"]), 2)

        markdown = report_dict["markdown_report"]
        self.assertIn("# System Impact & QA Testing Report", markdown)
        self.assertIn("BP_LesterPhoenix", markdown)
        self.assertIn("ABP_Manny_Combat", markdown)
        self.assertIn("Zero-Manual-Steps Policy", markdown)


if __name__ == "__main__":
    unittest.main()
