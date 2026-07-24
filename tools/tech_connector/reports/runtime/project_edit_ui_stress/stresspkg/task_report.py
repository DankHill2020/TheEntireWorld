# coding=utf-8
from stresspkg.task_store import load_tasks


def summarize_tasks(records):
    total_count = 0
    done_count = 0
    todo_count = 0
    high_priority_names = []
    for r in records:
        total_count += 1
        if r.get("status") == "done":
            done_count += 1
        else:
            todo_count += 1
        if int(r.get("priority", 0)) >= 5:
            high_priority_names.append(r.get("name"))
    return {
        "total": total_count,
        "done": done_count,
        "todo": todo_count,
        "high_priority": high_priority_names,
    }
