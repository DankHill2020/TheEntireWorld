from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from reasoning_runtime.project_analysis import audit_python_package_layout


class ProjectAnalysisPackageLayoutTests(unittest.TestCase):
    def test_audits_unqualified_imports(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "pkg"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="ascii")
            (package / "module.py").write_text("import services.foo\n", encoding="ascii")

            result = audit_python_package_layout(
                root,
                package_name="pkg",
                first_party_packages=("services",),
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["module_count"], 2)
            self.assertEqual(result["unqualified_imports"][0]["module"], "services.foo")


if __name__ == "__main__":
    unittest.main()
