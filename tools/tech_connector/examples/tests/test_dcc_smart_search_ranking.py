from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tech_connector.services.dcc.dcc_smart_search_service import smart_search_suggestions


class DccSmartSearchRankingTest(unittest.TestCase):
    def _build_index(self, tmp: str) -> Path:
        db_path = Path(tmp) / "index.sqlite"
        connection = sqlite3.connect(str(db_path))
        try:
            connection.executescript(
                """
                CREATE TABLE files (
                    id INTEGER PRIMARY KEY,
                    rel_path TEXT,
                    module TEXT
                );
                CREATE TABLE symbols (
                    id INTEGER PRIMARY KEY,
                    file_id INTEGER,
                    name TEXT,
                    qualname TEXT,
                    kind TEXT,
                    signature TEXT,
                    docstring TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO files(id, rel_path, module) VALUES (1, 'maya_tools/Rigging/create_rig.py', 'maya_tools.Rigging.create_rig')"
            )
            connection.execute(
                "INSERT INTO files(id, rel_path, module) VALUES (2, 'maya_tools/Rigging/mocap/setup_hik.py', 'maya_tools.Rigging.mocap.setup_hik')"
            )
            connection.execute(
                "INSERT INTO symbols(file_id, name, qualname, kind, signature, docstring) VALUES (1, 'create_rig_arm_space_switches', 'create_rig_arm_space_switches', 'function', '()', 'Create arm space switches from a rig mapping')"
            )
            connection.execute(
                "INSERT INTO symbols(file_id, name, qualname, kind, signature, docstring) VALUES (2, 'create_rig_mapping', 'create_rig_mapping', 'function', '()', '')"
            )
            connection.commit()
        finally:
            connection.close()
        return db_path

    def test_package_function_search_prioritizes_exact_function_name_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._build_index(tmp)

            results = smart_search_suggestions(
                "maya_tools.create rig mapping",
                package_dirs=[Path(tmp) / "maya_tools"],
                db_path=db_path,
                limit=5,
            )

        self.assertLessEqual(len(results), 5)
        self.assertTrue(results)
        self.assertEqual("create_rig_mapping", results[0].label)

    def test_bare_function_search_returns_fully_qualified_parent_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._build_index(tmp)

            results = smart_search_suggestions(
                "create_rig_mapping",
                package_dirs=[Path(tmp) / "maya_tools"],
                db_path=db_path,
                limit=5,
            )

        self.assertLessEqual(len(results), 5)
        self.assertTrue(results)
        self.assertEqual("create_rig_mapping", results[0].label)
        self.assertEqual("maya_tools/Rigging.mocap.setup_hik.create_rig_mapping", results[0].token)


if __name__ == "__main__":
    unittest.main()
