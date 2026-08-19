import maya.cmds as cmds

def disable_evaluation():
    """Equivalent to Evaluation > Evaluation Mode > Off"""
    try:
        cmds.evaluationManager(mode="off")
    except Exception:
        pass


def enable_evaluation():
    """Restore normal evaluation (Parallel)."""
    try:
        cmds.evaluationManager(mode="parallel")
    except Exception:
        try:
            cmds.evaluationManager(mode="serial")
        except Exception:
            pass

import maya.cmds as cmds


def rename_duplicates():
    """
    Renames duplicate DAG nodes by appending an incrementing number.
    Example:
        cube -> cube1
        cube -> cube2
        cube -> cube3
    """
    all_nodes = cmds.ls(dag=True, long=True)

    short_name_counts = {}

    # Process deepest nodes first so paths remain valid
    all_nodes.sort(key=lambda x: x.count("|"), reverse=True)

    for node in all_nodes:
        short_name = node.split("|")[-1]

        if short_name not in short_name_counts:
            short_name_counts[short_name] = 0
            continue

        short_name_counts[short_name] += 1

        new_name = f"{short_name}{short_name_counts[short_name]}"
        cmds.rename(node, new_name)

    print("Duplicate renaming complete.")