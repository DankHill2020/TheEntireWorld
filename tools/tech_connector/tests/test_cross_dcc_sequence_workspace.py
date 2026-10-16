from __future__ import annotations

from types import SimpleNamespace

from blender_tools.Cinematics.SequenceUI import sequence_utils as blender_sequence
from max_tools.Cinematics.SequenceUI import sequence_utils as max_sequence
from tech_connector.game_engine.integration.dcc_operation_service import registered_dcc_operation
from utilities.sequence_workspace import (
    apply_bulk_update, entry_output_path, legacy_anim_dict, new_document, new_entry,
    normalize_document, sequence_preflight, validate_document,
)


class _BlenderScene(dict):
    def __init__(self):
        super().__init__()
        self.frame_start = 1
        self.frame_end = 100
        self.frame_current = 1
        self.render = SimpleNamespace(fps=24, fps_base=1.0)
        self.camera = SimpleNamespace(name="Camera_Main")
        self.timeline_markers = [
            SimpleNamespace(name="Shot_010", frame=1, camera=SimpleNamespace(name="Camera_Main")),
            SimpleNamespace(name="Shot_020", frame=51, camera=SimpleNamespace(name="Camera_Close")),
        ]

    def frame_set(self, value):
        self.frame_current = int(value)


def _fake_blender():
    scene = _BlenderScene()
    armature = SimpleNamespace(name="Hero", type="ARMATURE", parent=None)
    mesh = SimpleNamespace(name="Hero_Mesh", type="MESH", parent=armature)
    cameras = [SimpleNamespace(name="Camera_Main", type="CAMERA", parent=None),
               SimpleNamespace(name="Camera_Close", type="CAMERA", parent=None)]
    return SimpleNamespace(
        context=SimpleNamespace(scene=scene, selected_objects=[armature]),
        data=SimpleNamespace(filepath="C:/Project/Shots/scene.blend", objects=[armature, mesh] + cameras),
        app=SimpleNamespace(driver_namespace={}),
    )


class _MaxRoot:
    pass


class _FakeMax:
    def __init__(self):
        self.frameRate = 30
        self.ticksPerFrame = 160
        self.animationRange = SimpleNamespace(start=0, end=16000)
        self.sliderTime = 0
        self.maxFilePath = "C:/Project/Shots/"
        self.maxFileName = "scene.max"
        self.rootNode = _MaxRoot()
        self._props = {}
        self.selection = []
        self.cameras = [SimpleNamespace(name="Camera_A"), SimpleNamespace(name="Camera_B")]
        self.objects = list(self.cameras)

    def getUserProp(self, _node, key):
        return self._props.get(key, "")

    def setUserProp(self, _node, key, value):
        self._props[key] = value

    def interval(self, start, end):
        return SimpleNamespace(start=int(start) * self.ticksPerFrame, end=int(end) * self.ticksPerFrame)

    def classOf(self, _item):
        return "Camera"


def test_portable_sequence_workspace_normalizes_validates_and_converts_legacy() -> None:
    document = new_document(host="blender", export_directory="C:/Exports", fps=24)
    document["entries"] = [new_entry(
        "Shot 010 Hero", 1, 48, namespace="Hero", skeleton="Hero_Rig",
        nodes=["Hero", "Hero_Mesh"], export_directory="C:/Exports",
    )]
    normalized = normalize_document(document)
    assert normalized["entries"][0]["name"] == "Shot_010_Hero"
    assert entry_output_path(normalized["entries"][0]).endswith("Shot_010_Hero.fbx")
    assert not [issue for issue in validate_document(normalized) if issue["severity"] == "error"]
    legacy = legacy_anim_dict(normalized)
    assert next(iter(legacy.values()))[:4] == [1, 48, "Hero", "Hero_Rig"]


def test_target_engine_skeleton_is_optional_offline_and_manual_values_round_trip() -> None:
    document = new_document(host="3dsmax", export_directory="C:/Exports", fps=30)
    document["entries"] = [new_entry(
        "OfflineHero", 0, 90, namespace="Hero", skeleton="/Game/Characters/SK_Hero_Skeleton",
        nodes=["Hero"], export_directory="C:/Exports",
    )]
    normalized = normalize_document(document)
    assert normalized["entries"][0]["skeleton"] == "/Game/Characters/SK_Hero_Skeleton"
    normalized["entries"][0]["skeleton"] = ""
    assert not [issue for issue in validate_document(normalized) if issue["severity"] == "error"]


def test_preflight_keeps_offline_manual_authoring_exportable_but_not_publishable() -> None:
    document = new_document(host="blender", export_directory="C:/Exports")
    document["entries"] = [new_entry(
        "Hero", 1, 48, namespace="Hero", skeleton="/Game/Hero/SK_Hero",
        export_directory="C:/Exports",
    )]
    report = sequence_preflight(document)
    assert report["can_export"] is True
    assert report["can_publish"] is False
    assert report["entries"][0]["skeleton_resolution"] == "manual"
    assert report["publish_blockers"][0]["code"] == "engine_offline"


def test_preflight_resolves_connected_skeleton_and_ignores_disabled_blockers() -> None:
    document = new_document(host="3dsmax", export_directory="C:/Exports")
    document["engine"] = {
        "status": "connected", "project": "Demo",
        "known_skeletons": ["/Game/Hero/SK_Hero"], "message": "Connected",
    }
    document["entries"] = [
        new_entry("Hero", 1, 48, namespace="Hero", skeleton="/Game/Hero/SK_Hero",
                  export_directory="C:/Exports"),
        new_entry("Unused", 1, 48, namespace="Unused", skeleton="",
                  export_directory="C:/Exports", enabled=False),
    ]
    report = sequence_preflight(document)
    assert report["entries"][0]["skeleton_resolution"] == "resolved"
    assert report["entries"][1]["skeleton_resolution"] == "missing"
    assert report["can_publish"] is True


def test_bulk_update_applies_only_to_selected_entries() -> None:
    document = new_document(host="blender", export_directory="C:/Exports")
    first = new_entry("First", 1, 10, export_directory="C:/Old")
    second = new_entry("Second", 11, 20, export_directory="C:/Old")
    document["entries"] = [first, second]
    updated = apply_bulk_update(
        document, [first["id"]], skeleton="/Game/Hero/SK_Hero", export_directory="C:/New",
    )
    assert updated["entries"][0]["skeleton"] == "/Game/Hero/SK_Hero"
    assert updated["entries"][0]["export_directory"] == "C:/New"
    assert updated["entries"][1]["skeleton"] == ""
    assert updated["entries"][1]["export_directory"] == "C:/Old"


def test_blender_adapter_discovers_marker_shots_and_persists_document() -> None:
    bpy = _fake_blender()
    entries = blender_sequence.entries_from_timeline(bpy_module=bpy)
    assert {(row["shot"], row["camera"]) for row in entries if row["camera"]} >= {
        ("Shot_010", "Camera_Main"), ("Shot_020", "Camera_Close"),
    }
    assert any(row["skeleton"] == "Hero" and row["end_frame"] == 50 for row in entries)
    document = new_document(host="blender", export_directory="C:/Exports", fps=24)
    document["entries"] = entries
    blender_sequence.write_document(document, bpy.context.scene, bpy_module=bpy)
    restored = blender_sequence.read_document(bpy.context.scene, bpy_module=bpy)
    assert len(restored["entries"]) == len(entries)
    assert restored["host"] == "blender"


def test_max_adapter_discovers_cameras_persists_and_updates_range() -> None:
    rt = _FakeMax()
    assert max_sequence.display_range(runtime=rt) == (0, 100)
    entries = max_sequence.entries_from_cameras(runtime=rt)
    assert [row["camera"] for row in entries] == ["Camera_A", "Camera_B"]
    document = new_document(host="3dsmax", export_directory="C:/Exports", fps=30)
    document["entries"] = entries
    max_sequence.write_document(document, runtime=rt)
    restored = max_sequence.read_document(runtime=rt)
    assert len(restored["entries"]) == 2
    max_sequence.set_display_range(10, 42, runtime=rt)
    assert max_sequence.display_range(runtime=rt) == (10, 42)


def test_host_adapters_publish_only_through_installed_engine_callbacks() -> None:
    document = new_document(host="blender", export_directory="C:/Exports")
    document["entries"] = [new_entry("Hero", 1, 24, export_directory="C:/Exports")]
    bpy = _fake_blender()
    bpy.app.driver_namespace[blender_sequence.ENGINE_PUBLISHER_KEY] = (
        lambda payload: {"ok": True, "host": payload["host"]}
    )
    assert blender_sequence.publish_document(document, bpy_module=bpy) == {"ok": True, "host": "blender"}

    max_sequence.install_engine_publisher(lambda payload: {"ok": True, "host": payload["host"]})
    try:
        assert max_sequence.publish_document(document) == {"ok": True, "host": "blender"}
    finally:
        max_sequence.install_engine_publisher(None)


def test_tech_connector_exposes_sequence_workspace_for_blender_and_max() -> None:
    blender = registered_dcc_operation("blender", "cinematics.sequence_ui")
    max_operation = registered_dcc_operation("3dsmax", "cinematics.sequence_ui")
    assert blender.function.endswith("blender_tools.Cinematics.SequenceUI.sequence_utils.show_sequence_manager")
    assert max_operation.function.endswith("max_tools.Cinematics.SequenceUI.sequence_utils.show_sequence_manager")
