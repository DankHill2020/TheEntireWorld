"""Widget Blueprint authoring helpers backed by AIStudioBridge."""

from __future__ import annotations

import json


def author_canvas_text(
    widget_blueprint_path,
    root_name="RootCanvas",
    text_name="TitleText",
    text="Tech Connector",
    save=True,
):
    """
        Authors a CanvasPanel and TextBlock in a Widget Blueprint.
    :param widget_blueprint_path: Unreal Widget Blueprint content path
    :param root_name: root CanvasPanel name
    :param text_name: child TextBlock name
    :param text: text content
    :param save: whether to save the Widget Blueprint package
    :return: JSON plugin authoring receipt
    """
    import unreal

    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if bridge is None or not hasattr(bridge, "author_widget_blueprint"):
        return json.dumps({
            "ok": False,
            "status": "plugin_update_required",
            "error": "AIStudioBridge must be rebuilt and Unreal restarted for Widget Blueprint authoring.",
            "asset_path": widget_blueprint_path,
        }, indent=2)
    return bridge.author_widget_blueprint(
        str(widget_blueprint_path),
        unreal.Name(str(root_name)),
        unreal.Name(str(text_name)),
        str(text),
        bool(save),
    )


def author_from_spec(widget_blueprint_path, widgets, save=True):
    """
        Authors a validated Widget Blueprint hierarchy from a specification.
    :param widget_blueprint_path: Unreal Widget Blueprint content path
    :param widgets: widget hierarchy specification or widget list
    :param save: whether to save the Widget Blueprint package
    :return: JSON plugin authoring receipt
    """
    import unreal

    bridge = getattr(unreal, "AIStudioBridgeLibrary", None)
    if bridge is None or not hasattr(bridge, "author_widget_blueprint_from_json"):
        return json.dumps({
            "ok": False,
            "status": "plugin_update_required",
            "error": (
                "AIStudioBridge must be rebuilt and Unreal restarted for "
                "spec-driven Widget Blueprint authoring."
            ),
            "asset_path": widget_blueprint_path,
        }, indent=2)
    specification = widgets if isinstance(widgets, dict) else {"widgets": list(widgets or [])}
    return bridge.author_widget_blueprint_from_json(
        str(widget_blueprint_path),
        json.dumps(specification),
        bool(save),
    )
