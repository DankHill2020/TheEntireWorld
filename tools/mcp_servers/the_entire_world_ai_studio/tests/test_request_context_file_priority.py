import unittest
from types import SimpleNamespace

from engine.request_context import snapshot_from_window


class _Toggle:
    def __init__(self, checked: bool):
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class RequestContextFilePriorityTests(unittest.TestCase):
    def _window(self, *, checked=False):
        return SimpleNamespace(
            current_file_path="C:/depot/tools/custom_qt/custom_widgets.py",
            open_editors={
                "C:/depot/tools/custom_qt/custom_widgets.py": object(),
                "C:/depot/tools/maya_tools/Rigging/create_rig.py": object(),
            },
            settings={
                "open_files": [
                    "C:/depot/tools/custom_qt/custom_widgets.py",
                    "C:/depot/tools/maya_tools/Rigging/create_rig.py",
                ]
            },
            prioritize_open_file_context_checkbox=_Toggle(checked),
            project_roots=lambda: ["C:/depot/tools"],
            selected_mcphost_model=lambda: "ollama:qwen2.5-coder:1.5b",
        )

    def test_open_files_are_known_without_active_file_priority(self):
        context = snapshot_from_window(self._window(checked=False), "what functions create a rig in Maya?")

        self.assertEqual("", context.current_file_path)
        self.assertIn("C:/depot/tools/custom_qt/custom_widgets.py", context.open_file_paths)
        self.assertIn("C:/depot/tools/maya_tools/Rigging/create_rig.py", context.open_file_paths)

    def test_checkbox_prioritizes_current_file(self):
        context = snapshot_from_window(self._window(checked=True), "what functions create a rig in Maya?")

        self.assertEqual("C:/depot/tools/custom_qt/custom_widgets.py", context.current_file_path)

    def test_explicit_current_file_prompt_prioritizes_even_when_unchecked(self):
        context = snapshot_from_window(self._window(checked=False), "what functions are in this file?")

        self.assertEqual("C:/depot/tools/custom_qt/custom_widgets.py", context.current_file_path)


if __name__ == "__main__":
    unittest.main()
