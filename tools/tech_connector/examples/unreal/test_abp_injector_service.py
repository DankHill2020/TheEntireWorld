# coding=utf-8
"""
    Unit Test Suite for AnimBlueprint Injection and Target Selection Service.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tech_connector.services.anim_blueprint_injector_service import (
    find_existing_anim_blueprints,
    build_abp_target_selection_prompt,
    generate_unreal_abp_injection_script,
)


class TestAnimBlueprintInjectorService(unittest.TestCase):
    """
        Test case suite for AnimBlueprint Injection & Target Selection Service.
    """

    def test_find_existing_anim_blueprints(self):
        """
            Tests scanning for existing project AnimBlueprints.
        """
        abps = find_existing_anim_blueprints()
        self.assertGreaterEqual(len(abps), 1)
        abp_names = [a["name"] for a in abps]
        self.assertIn("ABP_LesterPhoenix", abp_names)

    def test_build_target_selection_prompt(self):
        """
            Tests generating interactive user options (Inject into existing vs Create new).
        """
        abps = find_existing_anim_blueprints()
        prompt_data = build_abp_target_selection_prompt(abps)
        
        self.assertIn("question", prompt_data)
        self.assertGreaterEqual(len(prompt_data["options"]), 2)
        
        actions = [opt["action"] for opt in prompt_data["options"]]
        self.assertIn("inject_existing", actions)
        self.assertIn("create_new", actions)

    def test_generate_abp_injection_script(self):
        """
            Tests generation of Unreal Engine Python injection script.
        """
        script = generate_unreal_abp_injection_script(
            anim_bp_path="/Game/MetaHumans/LesterPhoenix/ABP_LesterPhoenix",
            system_name="Climbing"
        )
        self.assertIn("import unreal", script)
        self.assertIn("bIsClimbing", script)
        self.assertIn("preserved_existing_graphs", script)


if __name__ == "__main__":
    unittest.main()
