"""Behavior Tree authoring helpers backed by AIStudioBridge."""

from __future__ import annotations

import json


def author_baseline(
    behavior_tree_path,
    blackboard_path="",
    wait_seconds=1.0,
    save=True,
):
    """
        Authors a Root to Selector to Wait Behavior Tree baseline.
    :param behavior_tree_path: Unreal Behavior Tree content path
    :param blackboard_path: optional Blackboard Data content path
    :param wait_seconds: Wait task duration
    :param save: whether to save the Behavior Tree package
    :return: JSON plugin authoring receipt
    """
    import unreal

    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if bridge is None or not hasattr(bridge, "author_behavior_tree_baseline"):
        return json.dumps({
            "ok": False,
            "status": "plugin_update_required",
            "error": "AIStudioBridge must be rebuilt and Unreal restarted for Behavior Tree authoring.",
            "asset_path": behavior_tree_path,
        }, indent=2)
    return bridge.author_behavior_tree_baseline(
        str(behavior_tree_path),
        str(blackboard_path or ""),
        float(wait_seconds),
        bool(save),
    )


def author_wait_graph(
    behavior_tree_path,
    blackboard_path="",
    composite_type="selector",
    wait_seconds=(1.0,),
    save=True,
):
    """
        Authors a Selector or Sequence with one or more Wait task children.
    :param behavior_tree_path: Unreal Behavior Tree content path
    :param blackboard_path: optional Blackboard Data content path
    :param composite_type: selector or sequence
    :param wait_seconds: ordered Wait task durations
    :param save: whether to save the Behavior Tree package
    :return: JSON plugin authoring receipt
    """
    import unreal

    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if bridge is None or not hasattr(bridge, "author_behavior_tree_wait_graph"):
        return json.dumps({
            "ok": False,
            "status": "plugin_update_required",
            "error": "AIStudioBridge must be rebuilt and Unreal restarted for generalized Behavior Tree authoring.",
            "asset_path": behavior_tree_path,
        }, indent=2)
    return bridge.author_behavior_tree_wait_graph(
        str(behavior_tree_path),
        str(blackboard_path or ""),
        str(composite_type or "selector"),
        [float(value) for value in list(wait_seconds or [])],
        bool(save),
    )


def author_task_graph(
    behavior_tree_path,
    blackboard_path,
    tasks,
    composite_type="sequence",
    save=True,
):
    """
        Authors a mixed Move To and Wait Behavior Tree task graph.
    :param behavior_tree_path: Unreal Behavior Tree content path
    :param blackboard_path: Blackboard Data content path used by Move To tasks
    :param tasks: ordered task specifications
    :param composite_type: selector or sequence
    :param save: whether to save the Behavior Tree package
    :return: JSON plugin authoring receipt
    """
    import unreal

    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if bridge is None or not hasattr(bridge, "author_behavior_tree_task_graph"):
        return json.dumps({
            "ok": False,
            "status": "plugin_update_required",
            "error": "AIStudioBridge must be rebuilt and Unreal restarted for mixed Behavior Tree task authoring.",
            "asset_path": behavior_tree_path,
        }, indent=2)
    return bridge.author_behavior_tree_task_graph(
        str(behavior_tree_path),
        str(blackboard_path or ""),
        str(composite_type or "sequence"),
        json.dumps({"tasks": list(tasks or [])}),
        bool(save),
    )
