from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from tech_connector.models.constants import (
    PROJECT_KNOWLEDGE_RELATIVE,
    active_project_root,
    project_index_db_path,
)
from tech_connector.services.file_index_service import FileIndexService


class ProjectKnowledgePathTests(TestCase):
    def test_database_uses_a_stable_path_beneath_each_project_root(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_path = Path(first).resolve()
            second_path = Path(second).resolve()
            self.assertEqual(
                first_path / PROJECT_KNOWLEDGE_RELATIVE / "knowledge_index_v2.sqlite",
                project_index_db_path(first_path),
            )
            self.assertEqual(
                second_path / PROJECT_KNOWLEDGE_RELATIVE / "knowledge_index_v2.sqlite",
                project_index_db_path(second_path),
            )

    def test_environment_selects_the_active_project_for_readers(self):
        with TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"TECH_CONNECTOR_PROJECT_ROOT": root}):
                expected = Path(root).resolve()
                self.assertEqual(expected, active_project_root())
                self.assertEqual(project_index_db_path(), FileIndexService().db_path)
