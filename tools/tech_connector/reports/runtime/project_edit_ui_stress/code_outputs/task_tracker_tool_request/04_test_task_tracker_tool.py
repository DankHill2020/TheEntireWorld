# coding=utf-8
import os
import unittest
from stresspkg.task_tracker_tool import TaskTrackerTool


class TestTaskTrackerTool(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._generated_workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self._generated_workspace.cleanup)
        self.tool = TaskTrackerTool(os.path.join(self._generated_workspace.name, 'generated_test_data.json'))

    def test_add_task_with_summary(self):
        task_data = {'name': 'Test Task', 'status': 'todo', 'priority': 5}
        result = self.tool.add_task(task_data, options={'summary': True})
        expected_summary = {'total': 1, 'done': 0, 'todo': 1, 'high_priority': ['Test Task']}
        self.assertEqual(result, expected_summary)

    def test_complete_task(self):
        task_data = {'name': 'Test Task', 'status': 'todo', 'priority': 5}
        self.tool.add_task(task_data)
        result = self.tool.complete_task('Test Task')
        self.assertEqual(result['done'], 1)

    def test_add_task_with_invalid_missing_name(self):
        with self.assertRaises(ValueError):
            task_data = {'name': '', 'status': 'todo', 'priority': 5}
            self.tool.add_task(task_data)

    def test_load_tasks_with_invalid_json(self):
        from stresspkg.task_store import load_tasks
        with open(self.tool.path, 'w', encoding='utf-8') as handle:
            handle.write('invalid json')
        self.assertEqual(load_tasks(self.tool.path), [])

    def test_add_task_with_dynamic_default_path(self):
        tool = TaskTrackerTool()
        expected_path = os.path.expanduser('~/.ai_studio/tasks/tasks.json')
        self.assertEqual(tool.path, expected_path)


if __name__ == '__main__':
    unittest.main()
