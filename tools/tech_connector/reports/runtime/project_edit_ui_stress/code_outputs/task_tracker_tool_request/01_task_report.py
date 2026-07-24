# coding=utf-8


def summarize_tasks(records):
    """
    Summarize the tasks based on their status and priority.

    :param records: List of task records, each containing 'name', 'status', and 'priority'.
    :return: A dictionary with counts of total, done, todo tasks, and high-priority task names.
    """
    total_count = 0
    done_count = 0
    todo_count = 0
    high_priority_names = []
    for task_record in records:
        total_count += 1
        if task_record.get('status') == 'done':
            done_count += 1
        else:
            todo_count += 1
        if int(task_record.get('priority', 0)) >= 5:
            high_priority_names.append(task_record.get('name'))
    return {'total': total_count, 'done': done_count, 'todo': todo_count, 'high_priority': high_priority_names}
