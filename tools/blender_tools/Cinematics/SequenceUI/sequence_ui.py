"""Native Blender UI for Sequence Workspace export authoring."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from utilities.sequence_workspace import (
    apply_bulk_update, duplicate_entry, new_entry, sequence_preflight, validate_document,
)
from . import sequence_utils


_SYNCING = False


def _row_dict(row) -> dict:
    return {
        "id": row.entry_id,
        "name": row.name,
        "export_directory": row.export_directory,
        "start_frame": row.start_frame,
        "end_frame": row.end_frame,
        "namespace": row.namespace,
        "skeleton": row.skeleton,
        "nodes": [value.strip() for value in row.nodes.split(",") if value.strip()],
        "color": row.color,
        "shot": row.shot,
        "camera": row.camera,
        "enabled": row.enabled,
    }


def _document(scene) -> dict:
    stored = sequence_utils.read_document(scene)
    return {
        "host": "blender",
        "export_directory": scene.tc_sequence_export_directory,
        "fps": sequence_utils.frames_per_second(scene),
        "entries": [_row_dict(row) for row in scene.tc_sequence_entries],
        "engine": dict(stored.get("engine") or {}),
    }


def _store(scene) -> None:
    sequence_utils.write_document(_document(scene), scene)


def _assign(row, value: dict) -> None:
    global _SYNCING
    previous = _SYNCING
    _SYNCING = True
    try:
        row.entry_id = str(value.get("id") or "")
        row.name = str(value.get("name") or "Animation")
        row.export_directory = str(value.get("export_directory") or "")
        row.start_frame = int(value.get("start_frame") or 0)
        row.end_frame = int(value.get("end_frame") or 0)
        row.namespace = str(value.get("namespace") or "")
        row.skeleton = str(value.get("skeleton") or "")
        row.nodes = ", ".join(str(item) for item in value.get("nodes") or ())
        row.color = str(value.get("color") or "#5f8fb8")
        row.shot = str(value.get("shot") or "")
        row.camera = str(value.get("camera") or "")
        row.enabled = bool(value.get("enabled", True))
    finally:
        _SYNCING = previous


def _property_changed(_value, context) -> None:
    if _SYNCING or context is None or getattr(context, "scene", None) is None:
        return
    try:
        _store(context.scene)
    except Exception:
        # A property callback must not break Blender's undo/property system.
        pass


def _load(scene) -> None:
    global _SYNCING
    document = sequence_utils.read_document(scene)
    previous = _SYNCING
    _SYNCING = True
    try:
        scene.tc_sequence_export_directory = str(document.get("export_directory") or "")
        scene.tc_sequence_entries.clear()
        for value in document.get("entries") or ():
            _assign(scene.tc_sequence_entries.add(), value)
        scene.tc_sequence_index = min(max(0, scene.tc_sequence_index), max(0, len(scene.tc_sequence_entries) - 1))
    finally:
        _SYNCING = previous


def _replace_entries(scene, document: dict) -> None:
    global _SYNCING
    previous = _SYNCING
    _SYNCING = True
    try:
        scene.tc_sequence_entries.clear()
        for value in document.get("entries") or ():
            _assign(scene.tc_sequence_entries.add(), value)
        scene.tc_sequence_index = min(scene.tc_sequence_index, max(0, len(scene.tc_sequence_entries) - 1))
    finally:
        _SYNCING = previous
    _store(scene)


class TCSequenceEntry(PropertyGroup):
    entry_id: StringProperty(name="ID")
    name: StringProperty(name="Name", default="Animation", update=_property_changed)
    export_directory: StringProperty(name="Export Directory", subtype="DIR_PATH", update=_property_changed)
    start_frame: IntProperty(name="In", default=1, update=_property_changed)
    end_frame: IntProperty(name="Out", default=120, update=_property_changed)
    namespace: StringProperty(name="Source Rig / Namespace", update=_property_changed)
    skeleton: StringProperty(
        name="Target Engine Skeleton (optional)",
        description="May be entered manually while the engine is offline",
        update=_property_changed,
    )
    nodes: StringProperty(name="Objects", description="Comma-separated Blender object names", update=_property_changed)
    color: StringProperty(name="Color", default="#5f8fb8", update=_property_changed)
    shot: StringProperty(name="Shot", update=_property_changed)
    camera: StringProperty(name="Camera", update=_property_changed)
    enabled: BoolProperty(name="Enabled", default=True, update=_property_changed)


class TC_UL_sequence_entries(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.prop(item, "name", text="", emboss=False, icon="ACTION")
        row.label(text=f"{item.start_frame}–{item.end_frame}")
        row.label(text=item.shot or item.namespace or item.camera or "Unbound")


class TC_OT_sequence_add_selection(Operator):
    bl_idname = "tc_sequence.add_selection"
    bl_label = "Add Selected"
    bl_description = "Create export entries from selected armatures or objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        values = sequence_utils.entries_from_selection(context.scene)
        if not values:
            self.report({"WARNING"}, "Select an armature, camera, or animated object first.")
            return {"CANCELLED"}
        for value in values:
            _assign(context.scene.tc_sequence_entries.add(), value)
        context.scene.tc_sequence_index = len(context.scene.tc_sequence_entries) - 1
        _store(context.scene)
        return {"FINISHED"}


class TC_OT_sequence_add_shots(Operator):
    bl_idname = "tc_sequence.add_shots"
    bl_label = "Import Timeline Shots"
    bl_description = "Build camera and character rows from timeline markers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        values = sequence_utils.entries_from_timeline(context.scene)
        for value in values:
            _assign(context.scene.tc_sequence_entries.add(), value)
        context.scene.tc_sequence_index = max(0, len(context.scene.tc_sequence_entries) - 1)
        _store(context.scene)
        self.report({"INFO"}, f"Added {len(values)} sequence entries.")
        return {"FINISHED"}


class TC_OT_sequence_add_empty(Operator):
    bl_idname = "tc_sequence.add_empty"
    bl_label = "Add Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        value = new_entry(
            "Animation", scene.frame_start, scene.frame_end,
            export_directory=scene.tc_sequence_export_directory,
        )
        _assign(scene.tc_sequence_entries.add(), value)
        scene.tc_sequence_index = len(scene.tc_sequence_entries) - 1
        _store(scene)
        return {"FINISHED"}


class TC_OT_sequence_duplicate(Operator):
    bl_idname = "tc_sequence.duplicate"
    bl_label = "Duplicate Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if not (0 <= scene.tc_sequence_index < len(scene.tc_sequence_entries)):
            return {"CANCELLED"}
        value = duplicate_entry(_row_dict(scene.tc_sequence_entries[scene.tc_sequence_index]))
        _assign(scene.tc_sequence_entries.add(), value)
        scene.tc_sequence_index = len(scene.tc_sequence_entries) - 1
        _store(scene)
        return {"FINISHED"}


class TC_OT_sequence_remove(Operator):
    bl_idname = "tc_sequence.remove"
    bl_label = "Remove Entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if not (0 <= scene.tc_sequence_index < len(scene.tc_sequence_entries)):
            return {"CANCELLED"}
        scene.tc_sequence_entries.remove(scene.tc_sequence_index)
        scene.tc_sequence_index = min(scene.tc_sequence_index, max(0, len(scene.tc_sequence_entries) - 1))
        _store(scene)
        return {"FINISHED"}


class TC_OT_sequence_set_range(Operator):
    bl_idname = "tc_sequence.set_range"
    bl_label = "Set Scene Range"

    def execute(self, context):
        scene = context.scene
        if not (0 <= scene.tc_sequence_index < len(scene.tc_sequence_entries)):
            return {"CANCELLED"}
        row = scene.tc_sequence_entries[scene.tc_sequence_index]
        sequence_utils.set_display_range(row.start_frame, row.end_frame, scene)
        return {"FINISHED"}


class TC_OT_sequence_save(Operator):
    bl_idname = "tc_sequence.save"
    bl_label = "Save Sequence Setup"

    def execute(self, context):
        _store(context.scene)
        self.report({"INFO"}, "Sequence Workspace data saved in the Blender scene.")
        return {"FINISHED"}


class TC_OT_sequence_bulk_apply(Operator):
    bl_idname = "tc_sequence.bulk_apply"
    bl_label = "Apply Target and Directory to Enabled"
    bl_description = "Copy the selected entry's target skeleton and export directory to every enabled entry"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if not (0 <= scene.tc_sequence_index < len(scene.tc_sequence_entries)):
            return {"CANCELLED"}
        current = scene.tc_sequence_entries[scene.tc_sequence_index]
        document = _document(scene)
        identifiers = [row["id"] for row in document["entries"] if row.get("enabled", True)]
        updated = apply_bulk_update(
            document, identifiers, skeleton=current.skeleton,
            export_directory=current.export_directory or scene.tc_sequence_export_directory,
        )
        _replace_entries(scene, updated)
        self.report({"INFO"}, f"Updated {len(identifiers)} enabled entries.")
        return {"FINISHED"}


class TC_OT_sequence_preflight(Operator):
    bl_idname = "tc_sequence.preflight"
    bl_label = "Sequence Preflight"
    bl_description = "Review local export and engine publish readiness"

    def invoke(self, context, _event):
        self._preflight = sequence_preflight(_document(context.scene))
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, _context):
        layout = self.layout
        report = self._preflight
        layout.label(text=f"Engine: {report['engine_status'].replace('_', ' ').title()}", icon="LINKED")
        layout.label(text="Local FBX export ready" if report["can_export"] else "Local export needs attention",
                     icon="CHECKMARK" if report["can_export"] else "ERROR")
        layout.label(text="Engine publish ready" if report["can_publish"] else "Engine publish blocked",
                     icon="CHECKMARK" if report["can_publish"] else "LOCKED")
        for issue in report["issues"][:5]:
            layout.label(text=issue["message"], icon="ERROR" if issue["severity"] == "error" else "INFO")
        for entry in report["entries"][:8]:
            row = layout.row()
            row.label(text=entry["name"])
            row.label(text=entry["skeleton_resolution"].replace("_", " ").title())
            row.label(text=entry["message"])

    def execute(self, _context):
        return {"FINISHED"}


class TC_OT_sequence_connect_help(Operator):
    bl_idname = "tc_sequence.connect_help"
    bl_label = "Connect Engine"
    bl_description = "Engine connection is supplied by Tech Connector"

    def execute(self, _context):
        self.report({"INFO"}, "Connect an Unreal or Unity session through Tech Connector; local export remains available.")
        return {"FINISHED"}


class TC_OT_sequence_publish(Operator):
    bl_idname = "tc_sequence.publish"
    bl_label = "Publish to Engine"
    bl_description = "Publish through the connected Tech Connector engine adapter"

    @classmethod
    def poll(cls, context):
        return sequence_preflight(_document(context.scene))["can_publish"]

    def execute(self, context):
        try:
            result = sequence_utils.publish_document(_document(context.scene))
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if not result.get("ok", True):
            self.report({"ERROR"}, str(result.get("error") or "Engine publish failed."))
            return {"CANCELLED"}
        self.report({"INFO"}, str(result.get("message") or "Sequence published to engine."))
        return {"FINISHED"}


class TC_OT_sequence_export(Operator):
    bl_idname = "tc_sequence.export"
    bl_label = "Export Sequence Entries"

    selected_only: BoolProperty(default=False)

    def execute(self, context):
        scene = context.scene
        document = _document(scene)
        issues = validate_document(document)
        errors = [issue for issue in issues if issue["severity"] == "error"]
        if errors:
            self.report({"ERROR"}, errors[0]["message"])
            return {"CANCELLED"}
        indices = [scene.tc_sequence_index] if self.selected_only else list(range(len(scene.tc_sequence_entries)))
        exported = 0
        for index in indices:
            if not (0 <= index < len(scene.tc_sequence_entries)):
                continue
            value = _row_dict(scene.tc_sequence_entries[index])
            if not value["enabled"]:
                continue
            try:
                sequence_utils.export_entry(value, default_directory=scene.tc_sequence_export_directory)
                exported += 1
            except Exception as exc:
                self.report({"ERROR"}, f"{value['name']}: {exc}")
                return {"CANCELLED"}
        _store(scene)
        self.report({"INFO"}, f"Exported {exported} sequence entr{'y' if exported == 1 else 'ies'}.")
        return {"FINISHED"}


class TC_PT_sequence_workspace(Panel):
    bl_label = "Sequence Workspace"
    bl_idname = "TC_PT_sequence_workspace"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tech Connector"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        document = _document(scene)
        preflight = sequence_preflight(document)
        engine_status = preflight["engine_status"]
        header = layout.row(align=True)
        header.label(text=f"Blender • {sequence_utils.frames_per_second(scene):g} fps", icon="SEQUENCE")
        header.operator(TC_OT_sequence_save.bl_idname, text="Save", icon="FILE_TICK")
        layout.prop(scene, "tc_sequence_export_directory", text="Export Root")
        connection = layout.row(align=True)
        connection.label(
            text=f"Engine: {engine_status.replace('_', ' ').title()}",
            icon="LINKED" if engine_status == "connected" else "UNLINKED",
        )
        if engine_status != "connected":
            connection.operator(TC_OT_sequence_connect_help.bl_idname, text="How to Connect")
        layout.label(text="Offline authoring enabled • target skeletons may be entered manually", icon="INFO")

        if not scene.tc_sequence_entries:
            empty = layout.box()
            empty.label(text="Build your first sequence export", icon="SEQUENCE")
            empty.label(text="Use the current selection, import timeline markers, or start with an empty entry.")
            actions = empty.row(align=True)
            actions.operator(TC_OT_sequence_add_selection.bl_idname, text="Add Selected", icon="RESTRICT_SELECT_OFF")
            actions.operator(TC_OT_sequence_add_shots.bl_idname, text="Import Shots", icon="MARKER_HLT")
            actions.operator(TC_OT_sequence_add_empty.bl_idname, text="Empty Entry", icon="ADD")
            return

        row = layout.row()
        row.template_list(
            TC_UL_sequence_entries.__name__, "", scene, "tc_sequence_entries",
            scene, "tc_sequence_index", rows=6,
        )
        tools = row.column(align=True)
        tools.operator(TC_OT_sequence_add_empty.bl_idname, text="", icon="ADD")
        tools.operator(TC_OT_sequence_remove.bl_idname, text="", icon="REMOVE")
        tools.operator(TC_OT_sequence_duplicate.bl_idname, text="", icon="DUPLICATE")

        actions = layout.row(align=True)
        actions.operator(TC_OT_sequence_add_selection.bl_idname, icon="RESTRICT_SELECT_OFF")
        actions.operator(TC_OT_sequence_add_shots.bl_idname, icon="MARKER_HLT")
        actions.operator(TC_OT_sequence_bulk_apply.bl_idname, text="Apply Target + Directory to Enabled", icon="COPYDOWN")

        if 0 <= scene.tc_sequence_index < len(scene.tc_sequence_entries):
            item = scene.tc_sequence_entries[scene.tc_sequence_index]
            box = layout.box()
            box.label(text="Selected Entry", icon="ACTION")
            box.prop(item, "name")
            range_row = box.row(align=True)
            range_row.prop(item, "start_frame")
            range_row.prop(item, "end_frame")
            range_row.operator(TC_OT_sequence_set_range.bl_idname, text="Use Range")
            box.prop(item, "export_directory")
            box.prop(item, "nodes")
            source = box.row(align=True)
            source.prop(item, "namespace")
            source.prop(item, "skeleton")
            source = box.row(align=True)
            source.prop(item, "shot")
            source.prop(item, "camera")
            selected_preflight = next(
                (row for row in preflight["entries"] if row["id"] == item.entry_id), None,
            )
            if selected_preflight:
                box.label(
                    text=f"Skeleton: {selected_preflight['skeleton_resolution'].replace('_', ' ').title()} — {selected_preflight['message']}",
                    icon="CHECKMARK" if selected_preflight["skeleton_resolution"] in {"resolved", "not_required"} else "INFO",
                )

        issues = preflight["issues"]
        if issues:
            alert = layout.box()
            alert.alert = any(issue["severity"] == "error" for issue in issues)
            alert.label(text=f"{len(issues)} validation item(s)", icon="ERROR" if alert.alert else "INFO")
            for issue in issues[:3]:
                alert.label(text=issue["message"])

        readiness = layout.row(align=True)
        readiness.operator(TC_OT_sequence_preflight.bl_idname, text="Review Preflight", icon="CHECKMARK")
        readiness.label(text="Local export ready" if preflight["can_export"] else "Local export blocked")
        readiness.label(text="Publish ready" if preflight["can_publish"] else "Publish unavailable")

        export_row = layout.row(align=True)
        selected = export_row.operator(TC_OT_sequence_export.bl_idname, text="Export Selected FBX", icon="EXPORT")
        selected.selected_only = True
        all_rows = export_row.operator(TC_OT_sequence_export.bl_idname, text="Export Enabled FBX", icon="EXPORT")
        all_rows.selected_only = False
        publish_row = layout.row()
        publish_row.enabled = preflight["can_publish"]
        publish_row.operator(TC_OT_sequence_publish.bl_idname, text="Publish to Connected Engine", icon="LINKED")


_CLASSES = (
    TCSequenceEntry, TC_UL_sequence_entries, TC_OT_sequence_add_selection,
    TC_OT_sequence_add_shots, TC_OT_sequence_add_empty, TC_OT_sequence_duplicate,
    TC_OT_sequence_remove, TC_OT_sequence_set_range, TC_OT_sequence_save,
    TC_OT_sequence_bulk_apply, TC_OT_sequence_preflight, TC_OT_sequence_connect_help,
    TC_OT_sequence_publish, TC_OT_sequence_export, TC_PT_sequence_workspace,
)
_REGISTERED = False


def register():
    global _REGISTERED
    if _REGISTERED:
        return {"ok": True, "already_registered": True}
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.tc_sequence_entries = CollectionProperty(type=TCSequenceEntry)
    bpy.types.Scene.tc_sequence_index = IntProperty(default=0, min=0)
    bpy.types.Scene.tc_sequence_export_directory = StringProperty(
        name="Sequence Export Root", subtype="DIR_PATH", default="//Exports", update=_property_changed,
    )
    _REGISTERED = True
    for scene in bpy.data.scenes:
        try:
            _load(scene)
        except Exception:
            pass
    return {"ok": True, "registered": True}


def unregister():
    global _REGISTERED
    if not _REGISTERED:
        return
    for name in ("tc_sequence_export_directory", "tc_sequence_index", "tc_sequence_entries"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    _REGISTERED = False


def show_sequence_manager():
    result = register()
    result["message"] = "Open View3D Sidebar → Tech Connector → Sequence Workspace."
    return result


if __name__ == "__main__":
    register()
