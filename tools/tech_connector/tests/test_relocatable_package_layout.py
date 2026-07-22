from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.models.constants import APP_PACKAGE, APP_ROOT, KNOWLEDGE_DIR, TOOLS_ROOT
from tech_connector.services.code_intelligence_service import (
    analyze_service_cleanup_candidates,
    audit_python_package_layout,
)
from tech_connector.services.settings_service import _relocate_legacy_app_path
from tech_connector.services.unreal.unreal_operation_service import UNREAL_OPERATIONS


class RelocatablePackageLayoutTests(unittest.TestCase):
    def test_roots_are_derived_from_the_current_checkout(self):
        self.assertEqual("tech_connector", APP_PACKAGE)
        self.assertEqual(Path(__file__).resolve().parents[1], APP_ROOT)
        self.assertEqual("tools", TOOLS_ROOT.name.lower())
        self.assertIn(TOOLS_ROOT, APP_ROOT.parents)
        self.assertEqual(APP_ROOT / "knowledge", KNOWLEDGE_DIR)

    def test_saved_paths_from_the_old_checkout_are_relocated(self):
        old = "D:/legacy/ai_studio_checkout/the_entire_world_ai_studio/data/ai_intel.db"
        self.assertEqual(str(APP_ROOT / "data" / "ai_intel.db"), _relocate_legacy_app_path(old))
        self.assertEqual(
            str(APP_ROOT),
            _relocate_legacy_app_path(
                "D:/legacy/ai_studio_checkout/the_entire_world_ai_studio"
            ),
        )

    def test_unreal_bootstrap_exposes_package_and_direct_import_roots(self):
        paths = [Path(value) for value in UnrealBridge()._unreal_python_bootstrap_paths()]
        self.assertIn(TOOLS_ROOT, paths)
        self.assertIn(APP_ROOT, paths)
        self.assertIn(APP_ROOT / "bridges" / "unreal", paths)

    def test_first_party_unreal_operations_use_the_new_package(self):
        first_party = [
            spec.function
            for spec in UNREAL_OPERATIONS.values()
            if "tech_connector.bridges.unreal" in spec.function
        ]
        self.assertTrue(first_party)
        self.assertTrue(all(path.startswith("tech_connector.") for path in first_party))

    def test_background_processes_do_not_create_console_windows(self):
        batch = (APP_ROOT / "Start_The_Entire_World_Tech_Connector.bat").read_text(encoding="utf-8")
        terminal_service = (APP_ROOT / "services" / "terminal_service.py").read_text(encoding="utf-8")
        self.assertIn("pyw", batch)
        self.assertIn("CREATE_NO_WINDOW", terminal_service)
        settings_source = (APP_ROOT / "services" / "settings_service.py").read_text(encoding="utf-8")
        self.assertNotIn("sys.executable", settings_source)
        self.assertIn('"command": "python"', settings_source)

    def test_package_audit_finds_no_unqualified_first_party_imports(self):
        audit = audit_python_package_layout(APP_ROOT)
        self.assertEqual([], audit["unqualified_imports"])
        self.assertEqual([], audit["stale_paths"])
        self.assertEqual([], audit["parse_errors"])
        self.assertEqual([], audit["circular_imports"])
        self.assertEqual([], audit["personal_references"])
        self.assertEqual([], audit["hardcoded_user_paths"])

    def test_package_audit_reports_top_level_circular_imports(self):
        with TemporaryDirectory() as temp_dir:
            package = Path(temp_dir) / "sample_package"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "alpha.py").write_text(
                "from sample_package import beta\n", encoding="utf-8"
            )
            (package / "beta.py").write_text(
                "from sample_package import alpha\n", encoding="utf-8"
            )
            audit = audit_python_package_layout(
                package,
                package_name="sample_package",
                first_party_packages=(),
            )

        self.assertEqual(
            [{"modules": ["sample_package.alpha", "sample_package.beta"], "paths": [str(package / "alpha.py"), str(package / "beta.py")] }],
            audit["circular_imports"],
        )

    def test_service_cleanup_analysis_finds_dead_and_related_modules(self):
        with TemporaryDirectory() as temp_dir:
            package = Path(temp_dir) / "sample_package"
            services = package / "services"
            services.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (services / "__init__.py").write_text("", encoding="utf-8")
            (services / "prompt_progress_service.py").write_text(
                "from sample_package.services.reasoning_narration_service import narrate\n"
                "def build_progress(): return narrate()\n",
                encoding="utf-8",
            )
            (services / "reasoning_narration_service.py").write_text(
                "def narrate(): return 'working'\n", encoding="utf-8"
            )
            (services / "unused_service.py").write_text(
                "def obsolete(): return None\n", encoding="utf-8"
            )
            (services / "dcc").mkdir()
            (services / "dcc" / "__init__.py").write_text("", encoding="utf-8")
            (services / "dcc_execution_service.py").write_text(
                "def execute(): return None\n", encoding="utf-8"
            )
            (services / "dcc_operation_service.py").write_text(
                "def operation(): return None\n", encoding="utf-8"
            )
            analysis = analyze_service_cleanup_candidates(
                package,
                package_name="sample_package",
            )

        dead_modules = {item["module"] for item in analysis["dead_code_candidates"]}
        candidate_pairs = {tuple(item["modules"]) for item in analysis["consolidation_candidates"]}
        self.assertIn("sample_package.services.unused_service", dead_modules)
        self.assertIn(
            (
                "sample_package.services.prompt_progress_service",
                "sample_package.services.reasoning_narration_service",
            ),
            candidate_pairs,
        )
        self.assertEqual(
            [
                "sample_package.services.dcc_execution_service",
                "sample_package.services.dcc_operation_service",
            ],
            analysis["existing_folder_moves"][0]["modules"],
        )
        self.assertEqual(
            "sample_package.services.dcc",
            analysis["existing_folder_moves"][0]["target_package"],
        )


if __name__ == "__main__":
    unittest.main()
