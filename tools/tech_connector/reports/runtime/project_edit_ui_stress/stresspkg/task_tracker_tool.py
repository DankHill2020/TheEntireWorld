# coding=utf-8
from stresspkg.task_store import save_tasks, load_tasks
from stresspkg.task_report import summarize_tasks


class TaskTrackerTool:
    def __init__(self, path=None):
        self.path = path or "D:/example_user/.ai_studio/tasks/tasks.json"
        self.debug_cache_unused = []

    def add_task(self, t, p=None):
        p = p or {}
        rows = load_tasks(self.path)
        task_name = t.get("name", "").strip()
        if not task_name:
            raise ValueError("Task requires name")
        row = {
            "name": task_name,
            "status": t.get("status", "todo"),
            "priority": int(t.get("priority", 0)),
        }
        rows.append(row)
        save_tasks(self.path, rows)
        if p.get("summary"):
            return summarize_tasks(rows)
        return row

    def complete_task(self, nm):
        rows = load_tasks(self.path)
        for r in rows:
            if r.get("name") == nm:
                r["status"] = "done"
        save_tasks(self.path, rows)
        return summarize_tasks(rows)
