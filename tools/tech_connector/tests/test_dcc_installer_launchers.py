import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tech_connector.services.dcc import installer_launchers


class TestDccInstallerLaunchers(unittest.TestCase):
    def test_discovers_installed_dcc_apps_with_matching_launchers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools_root = root / "tools"
            app_root = tools_root / "tech_connector"
            (tools_root / "maya_tools").mkdir(parents=True)
            (tools_root / "motionbuilder_tools").mkdir(parents=True)
            (app_root / "installers").mkdir(parents=True)
            (tools_root / "maya_tools" / "run_maya_with_setup_2025.bat").write_text("", encoding="utf-8")
            (tools_root / "maya_tools" / "run_maya_with_setup_2026.bat").write_text("", encoding="utf-8")
            (tools_root / "motionbuilder_tools" / "run_motionbuilder_with_setup_2026.bat").write_text("", encoding="utf-8")
            (app_root / "installers" / "Install_Blender_AI_Studio_Bridge.bat").write_text("", encoding="utf-8")

            def fake_glob_paths(patterns):
                joined = " ".join(patterns)
                if "Maya" in joined:
                    return [
                        Path(r"C:\Program Files\Autodesk\Maya2025\bin\maya.exe"),
                        Path(r"C:\Program Files\Autodesk\Maya2026\bin\maya.exe"),
                    ]
                if "MotionBuilder" in joined:
                    return [Path(r"C:\Program Files\Autodesk\MotionBuilder 2026\bin\x64\motionbuilder.exe")]
                if "Blender" in joined:
                    return [Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe")]
                return []

            with patch.object(installer_launchers, "_glob_paths", side_effect=fake_glob_paths):
                launchers = installer_launchers.discover_first_run_dcc_installers(
                    tools_root=tools_root,
                    app_root=app_root,
                )

        self.assertEqual(
            [launcher.marker for launcher in launchers],
            ["maya_2025", "maya_2026", "motionbuilder_2026", "blender"],
        )

    def test_run_first_time_dcc_installers_skips_seen_markers(self):
        launcher = installer_launchers.DCCInstallerLauncher(
            app_id="maya",
            display_name="Maya 2025",
            marker="maya_2025",
            script_path=Path("run_maya_with_setup_2025.bat"),
            executable_path=Path("maya.exe"),
            version="2025",
        )
        settings = {"dcc_bridge_setup_seen": ["maya_2025"]}
        saved = []

        with patch.object(installer_launchers, "discover_first_run_dcc_installers", return_value=[launcher]):
            with patch.object(installer_launchers, "run_installer_launcher") as run_launcher:
                launched = installer_launchers.run_first_time_dcc_installers(
                    settings,
                    lambda: saved.append(True),
                )

        self.assertEqual(launched, [])
        self.assertEqual(saved, [])
        run_launcher.assert_not_called()

    def test_pending_first_time_dcc_installers_returns_only_unseen_markers(self):
        seen_launcher = installer_launchers.DCCInstallerLauncher(
            app_id="maya",
            display_name="Maya 2025",
            marker="maya_2025",
            script_path=Path("run_maya_with_setup_2025.bat"),
            executable_path=Path("maya.exe"),
            version="2025",
        )
        unseen_launcher = installer_launchers.DCCInstallerLauncher(
            app_id="motionbuilder",
            display_name="MotionBuilder 2026",
            marker="motionbuilder_2026",
            script_path=Path("run_motionbuilder_with_setup_2026.bat"),
            executable_path=Path("motionbuilder.exe"),
            version="2026",
        )

        with patch.object(
            installer_launchers,
            "discover_first_run_dcc_installers",
            return_value=[seen_launcher, unseen_launcher],
        ):
            pending = installer_launchers.pending_first_time_dcc_installers(
                {"dcc_bridge_setup_seen": ["maya_2025"]}
            )

        self.assertEqual([launcher.marker for launcher in pending], ["motionbuilder_2026"])


if __name__ == "__main__":
    unittest.main()
