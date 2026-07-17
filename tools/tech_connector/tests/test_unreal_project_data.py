import json
import tempfile
import unittest
from pathlib import Path

from unreal_tools.unreal_project_data import add_unreal_startup_script


class TestUnrealProjectData(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
