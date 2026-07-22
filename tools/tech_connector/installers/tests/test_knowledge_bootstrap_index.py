from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tech_connector.knowledge.build_knowledge_index_v2 import index_file, init_db, stale_file_plan
from tech_connector.services.knowledge_background_service import KnowledgeBuildPhase, KnowledgeBuildWorker


class TestKnowledgeBootstrapIndex(unittest.TestCase):
    def test_symbols_only_bootstrap_is_completed_by_rich_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tool.py"
            source.write_text(
                "import os\n\n"
                "class RigTool:\n"
                "    def build(self):\n"
                "        return os.getcwd()\n",
                encoding="utf-8",
            )
            conn = sqlite3.connect(":memory:")
            init_db(conn)

            self.assertTrue(index_file(conn, root, source, symbols_only=True))
            cur = conn.cursor()
            cur.execute("SELECT id, sha1 FROM files WHERE path = ?", (str(source),))
            file_id, sha1 = cur.fetchone()
            self.assertTrue(str(sha1).startswith("bootstrap:"))
            cur.execute("SELECT COUNT(*) FROM symbols WHERE file_id = ?", (file_id,))
            self.assertGreater(cur.fetchone()[0], 0)
            cur.execute("SELECT COUNT(*) FROM chunks WHERE file_id = ?", (file_id,))
            self.assertEqual(cur.fetchone()[0], 0)

            changed, missing, counts = stale_file_plan(conn, [root])
            self.assertEqual(missing, [])
            self.assertEqual(counts["changed"], 1)
            self.assertEqual(changed[0][1], source)

            self.assertTrue(index_file(conn, root, source, symbols_only=False))
            cur.execute("SELECT id, sha1 FROM files WHERE path = ?", (str(source),))
            file_id, sha1 = cur.fetchone()
            self.assertFalse(str(sha1).startswith("bootstrap:"))
            cur.execute("SELECT COUNT(*) FROM chunks WHERE file_id = ?", (file_id,))
            self.assertGreater(cur.fetchone()[0], 0)

    def test_bootstrap_worker_runs_symbols_first_without_graph(self) -> None:
        worker = KnowledgeBuildWorker(
            project_root="C:/example/project",
            phase=KnowledgeBuildPhase.BOOTSTRAP_SYMBOLS,
            python_exe="python",
        )
        label, cmd = worker._phase_cmds()[0]
        self.assertEqual(label, "Bootstrap files / symbols")
        self.assertIn("--symbols-only", cmd)
        self.assertIn("--no-graph", cmd)
        self.assertNotIn("--graph-only", cmd)

    def test_bootstrap_worker_can_import_package_from_child_process(self) -> None:
        worker = KnowledgeBuildWorker(
            project_root="C:/example/project",
            phase=KnowledgeBuildPhase.BOOTSTRAP_SYMBOLS,
            python_exe="python",
        )
        cwd, env = worker._subprocess_context()
        package_root = Path(__file__).resolve().parents[1]
        self.assertEqual(package_root.parent, cwd)
        self.assertEqual("C:/example/project", env["TECH_CONNECTOR_PROJECT_ROOT"])
        self.assertEqual(str(cwd), env["PYTHONPATH"].split(os.pathsep)[0])


if __name__ == "__main__":
    unittest.main()
