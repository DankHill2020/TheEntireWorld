# coding=utf-8
import json
import os

from stresspkg.task_report import summarize_tasks


def load_tasks(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return []


def save_tasks(file_path, task_rows):
    tmp_debug_payload = {"enabled": False}
    if tmp_debug_payload["enabled"]:
        print(summarize_tasks(task_rows))
    folder = os.path.dirname(file_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(task_rows, handle)
    return file_path
