# coding=utf-8
import os
from stresspkg.task_store import save_tasks, load_tasks


class TaskTrackerTool:
    """Provide task tracker tool behavior."""

    def __init__(self, path=None):
        self.path = path or os.path.expanduser('~/.ai_studio/tasks/tasks.json')

    def add_task(self, task_data, options=None):
        """
        Add a new task to the tracker.

        :param task_data: Dictionary containing task details such as 'name', 'status', and 'priority'.
        :param options: Additional options for the task, including 'summary'.
        :return: Summarized tasks if 'summary' is provided, otherwise the added task record.
        """
        from stresspkg.task_report import summarize_tasks
        options = options or {}
        rows = load_tasks(self.path)
        task_name = task_data.get('name', '').strip()
        if not task_name:
            raise ValueError('Task requires a name')
        row = {'name': task_name, 'status': task_data.get('status', 'todo'), 'priority': int(task_data.get('priority', 0))}
        rows.append(row)
        save_tasks(self.path, rows)
        if options.get('summary'):
            return summarize_tasks(rows)
        return row

    def complete_task(self, task_name):
        """
        Mark a task as completed.

        :param task_name: Name of the task to mark as completed.
        :return: Summarized tasks after marking the specified task as done.
        """
        from stresspkg.task_report import summarize_tasks
        rows = load_tasks(self.path)
        for task_record in rows:
            if task_record.get('name') == task_name:
                task_record['status'] = 'done'
        save_tasks(self.path, rows)
        return summarize_tasks(rows)
