# coding=utf-8
import json
import os


def load_tasks(file_path):
    """
    Load tasks from a JSON file.

    :param file_path: Path to the JSON file containing task records.
    :return: List of task records, or an empty list if the file is missing or invalid JSON.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return []


def save_tasks(file_path, task_rows):
    """
    Save tasks to a JSON file atomically.

    :param file_path: Path to the JSON file where tasks will be saved.
    :param task_rows: List of task records to be saved.
    :return: The path to the saved file.
    """
    folder = os.path.dirname(file_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp_file_path = f'{file_path}.tmp'
    with open(temp_file_path, 'w', encoding='utf-8') as handle:
        json.dump(task_rows, handle)
    os.replace(temp_file_path, file_path)
    return file_path
