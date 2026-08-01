import json
import tempfile
import unittest
from pathlib import Path

from unreal_tools.unreal_project_data import (
    add_unreal_startup_script,
    install_ai_studio_bridge_plugin,
)
from tech_connector.app.main_window_chat_runtime import (
    unreal_prompt_requires_project_selection,
)


class TestUnrealProjectData(unittest.TestCase):
    def test_unreal_project_picker_gate_only_matches_project_backed_work(self):
        self.assertFalse(
            unreal_prompt_requires_project_selection("What is Unreal replication?")
        )
        self.assertFalse(
            unreal_prompt_requires_project_selection("Explain how Niagara works in Unreal")
        )
        self.assertFalse(
            unreal_prompt_requires_project_selection("Build a Maya rig", "maya")
        )
        self.assertTrue(
            unreal_prompt_requires_project_selection("Connect Unreal")
        )
        self.assertTrue(
            unreal_prompt_requires_project_selection(
                "In Maya export this animation, then import and retarget it in Unreal",
                "maya",
            )
        )
        self.assertTrue(
            unreal_prompt_requires_project_selection(
                "In Unreal implement a replicated inventory Blueprint"
            )
        )

    def test_add_startup_script_creates_config_and_enables_python_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uproject = root / "Sample.uproject"
            script = root / "http_server.py"
            uproject.write_text(json.dumps({"FileVersion": 3}), encoding="utf-8")
            script.write_text("print('server')\n", encoding="utf-8")

            add_unreal_startup_script(str(uproject), str(script))

            data = json.loads(uproject.read_text(encoding="utf-8"))
            plugins = data.get("Plugins", [])
            self.assertTrue(
                any(
                    plugin.get("Name") == "PythonScriptPlugin"
                    and plugin.get("Enabled") is True
                    for plugin in plugins
                )
            )

            default_engine = root / "Config" / "DefaultEngine.ini"
            self.assertTrue(default_engine.exists())
            contents = default_engine.read_text(encoding="utf-8")
            self.assertIn("[/Script/PythonScriptPlugin.PythonScriptPluginSettings]", contents)
            self.assertIn("StartupScripts[0]=", contents)
            self.assertIn("http_server.py", contents)

            add_unreal_startup_script(str(uproject), str(script))

            updated = default_engine.read_text(encoding="utf-8")
            self.assertEqual(1, updated.count("http_server.py"))

    def test_install_bridge_waits_for_current_binary_before_enablement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "Project"
            source = root / "Canonical" / "AIStudioBridge"
            (source / "Source" / "AIStudioBridge" / "Private").mkdir(parents=True)
            (source / "Config").mkdir()
            project.mkdir()
            uproject = project / "Sample.uproject"
            uproject.write_text(json.dumps({"FileVersion": 3}), encoding="utf-8")
            (source / "AIStudioBridge.uplugin").write_text(
                json.dumps({"FileVersion": 3, "Modules": []}),
                encoding="utf-8",
            )
            (source / "AIStudioBridgeCapabilities.json").write_text(
                json.dumps({"capabilities": []}),
                encoding="utf-8",
            )
            (source / "Source" / "AIStudioBridge" / "Private" / "Bridge.cpp").write_text(
                "void Bridge() {}\n",
                encoding="utf-8",
            )

            first = install_ai_studio_bridge_plugin(str(uproject), str(source))
            installed = project / "Plugins" / "AIStudioBridge"
            self.assertTrue(first["ok"])
            self.assertTrue(first["copied"])
            self.assertFalse(first["enabled"])
            self.assertTrue(first["build_required"])
            self.assertTrue((installed / "AIStudioBridge.uplugin").is_file())
            self.assertTrue(
                (installed / "Source" / "AIStudioBridge" / "Private" / "Bridge.cpp").is_file()
            )
            binary_dir = installed / "Binaries" / "Win64"
            binary_dir.mkdir(parents=True)
            (binary_dir / "UnrealEditor-AIStudioBridge.dll").write_bytes(b"current")

            second = install_ai_studio_bridge_plugin(str(uproject), str(source))

            self.assertFalse(second["copied"])
            self.assertTrue(second["enabled"])
            self.assertFalse(second["build_required"])
            self.assertTrue(second["binary_current"])
            data = json.loads(uproject.read_text(encoding="utf-8"))
            enabled = {
                row["Name"]: row["Enabled"]
                for row in data.get("Plugins") or []
            }
            self.assertTrue(enabled["AIStudioBridge"])
            self.assertTrue(enabled["PythonScriptPlugin"])


if __name__ == "__main__":
    unittest.main()
