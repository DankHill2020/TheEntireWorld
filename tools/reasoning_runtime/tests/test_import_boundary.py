from __future__ import annotations

from pathlib import Path
import sys
import unittest


class ImportBoundaryTests(unittest.TestCase):
    def test_reasoning_runtime_import_does_not_import_tech_connector(self):
        sys.modules.pop("reasoning_runtime", None)
        sys.modules.pop("tech_connector", None)

        import reasoning_runtime  # noqa: F401

        self.assertNotIn("tech_connector", sys.modules)

    def test_runtime_source_has_no_domain_imports(self):
        root = Path(__file__).resolve().parents[1]
        forbidden = (
            "from tech_connector",
            "import tech_connector",
            "from maya_tools",
            "import maya_tools",
            "from unreal_tools",
            "import unreal_tools",
            "from blender_tools",
            "import blender_tools",
            "from PySide",
            "import PySide",
        )
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            if "tests" in path.relative_to(root).parts:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    offenders.append(f"{path.relative_to(root)} contains {marker!r}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
