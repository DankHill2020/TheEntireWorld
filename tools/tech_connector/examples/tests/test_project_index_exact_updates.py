from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from tech_connector.services.project_service import (
    _EXACT_INDEX_MAX_BATCH_FILES,
    _exact_index_path_batches,
    _run_exact_index_command,
)


class ProjectIndexExactUpdateTests(unittest.TestCase):
    def test_exact_index_paths_are_batched_without_loss(self):
        paths = [f"C:/depot/tools/package/module_{index:03d}.py" for index in range(75)]

        batches = _exact_index_path_batches(paths)

        self.assertEqual([path for batch in batches for path in batch], paths)
        self.assertTrue(
            all(len(batch) <= _EXACT_INDEX_MAX_BATCH_FILES for batch in batches)
        )
        self.assertGreater(len(batches), 1)

    @patch("tech_connector.services.project_service.time.sleep")
    @patch("tech_connector.services.project_service.subprocess.run")
    def test_locked_database_is_retried_and_can_recover(self, run, sleep):
        run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="sqlite3.OperationalError: database is locked",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="Done.",
                stderr="",
            ),
        ]

        ok, detail = _run_exact_index_command(
            ["python", "C:/depot/tools/knowledge/build_knowledge_index_v2.py"],
            timeout=1,
        )

        self.assertTrue(ok)
        self.assertEqual(detail, "Done.")
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once()

    @patch("tech_connector.services.project_service.subprocess.run")
    def test_process_errors_preserve_the_actual_reason(self, run):
        run.side_effect = OSError(206, "The filename or extension is too long")

        ok, detail = _run_exact_index_command(
            ["python", "C:/depot/tools/knowledge/build_knowledge_index_v2.py"],
            timeout=1,
        )

        self.assertFalse(ok)
        self.assertIn("filename or extension is too long", detail)


if __name__ == "__main__":
    unittest.main()
