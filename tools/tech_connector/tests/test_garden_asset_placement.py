from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView, QTreeWidget, QTreeWidgetItem

from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel, MayaViewportCamera
from tech_connector.ui.dcc_viewer.mesh_painter.viewport_mixin_05 import ThreeDMeshPainterViewportMixin05
from tech_connector.ui.dcc_viewer.scene_document_lifecycle import SceneDocumentLifecycle


@pytest.fixture(scope="module", autouse=True)
def qt_application() -> QApplication:
    return QApplication.instance() or QApplication([])


class _Canvas:
    def update(self) -> None:
        pass


class _PlacementHost(ThreeDMeshPainterViewportMixin05):
    def __init__(self, recovery: Path) -> None:
        self.viewport_camera = MayaViewportCamera()
        self.mesh = FBXMeshModel("Placement Test")
        self._runtime_world_state = {"entities": [], "physics_joints": []}
        self._selected_scene_proxy = None
        self._scene_lifecycle = SceneDocumentLifecycle(recovery_directory=recovery)
        self._resolved_shaded_status = ""
        self.canvas = _Canvas()
        self.sync_calls = []

    def refresh_scene_outliner(self) -> None:
        pass

    def update_instance_details_panel(self) -> None:
        pass

    def sync_gpu_viewport(self, *, full: bool) -> None:
        self.sync_calls.append(full)

    def update_viewport_status(self) -> None:
        pass

    def auto_key_committed_transform(self, *_args) -> None:
        pass


def test_asset_drop_creates_runtime_entity_and_visible_scene_proxy(tmp_path) -> None:
    host = _PlacementHost(tmp_path)

    entity = host.place_asset_from_browser(
        {"asset_id": "tc.asset.mesh", "type_id": "tc.static_mesh", "path": str(tmp_path / "Crate.fbx")},
        QPointF(400.0, 300.0),
        800.0,
        600.0,
    )

    assert entity["name"] == "Crate"
    assert entity["render"]["mesh"].endswith("Crate.fbx")
    assert entity["transform"]["position"] == list(host.viewport_camera.target)
    assert host._runtime_world_state["entities"] == [entity]
    assert host.mesh.scene_proxy_objects[-1].get("asset_id") == "tc.asset.mesh"
    assert host.mesh.scene_proxy_objects[-1].mesh_data.topology_state == "asset_placeholder"
    assert host._scene_lifecycle.dirty
    assert host.sync_calls[-1] is True


def test_asset_placement_preview_is_non_destructive_and_uses_grid_snapping(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    host.configure_asset_placement(grid_snap=True, grid_size=2.0)

    preview = host.preview_asset_placement(
        {"asset_id": "mesh", "type_id": "tc.static_mesh", "path": str(tmp_path / "Crate.fbx")},
        QPointF(513.0, 347.0), 800.0, 600.0,
    )

    assert host._runtime_world_state["entities"] == []
    assert preview["grid_snap"] is True and preview["grid_size"] == 2.0
    assert all(value % 2.0 == 0.0 for value in preview["world"])
    host.clear_asset_placement_preview()
    assert host._asset_placement_preview is None


def test_texture_drop_assigns_selected_asset_instead_of_creating_entity(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    host.place_asset_from_browser(
        {"asset_id": "tc.asset.mesh", "type_id": "tc.static_mesh", "path": str(tmp_path / "Crate.fbx")}
    )
    entity_count = len(host._runtime_world_state["entities"])

    receipt = host.place_asset_from_browser(
        {"asset_id": "tc.asset.texture", "type_id": "tc.texture", "path": str(tmp_path / "T_Crate.png")}
    )

    assert receipt["action"] == "assign_texture"
    assert len(host._runtime_world_state["entities"]) == entity_count
    assert host._selected_scene_proxy.texture_bindings["base_color"].endswith("T_Crate.png")
    assert host.sync_calls[-1] is False


def test_obj_drop_uses_real_geometry_preview_and_prefab_tracks_overrides(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    obj_path = tmp_path / "Triangle.obj"
    obj_path.write_text(
        "v 0 0 0\nv 2 0 0\nv 0 2 0\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n",
        encoding="utf-8",
    )

    mesh_entity = host.place_asset_from_browser(
        {"asset_id": "tc.asset.obj", "type_id": "tc.static_mesh", "path": str(obj_path)}
    )
    assert mesh_entity["asset_instance"]["preview_state"] == "native"
    assert host.mesh.scene_proxy_objects[-1].mesh_data.topology_state == "asset_preview"
    assert host.mesh.scene_proxy_objects[-1].mesh_data.face_count == 1

    prefab_entity = host.place_asset_from_browser(
        {"asset_id": "tc.asset.prefab", "type_id": "tc.prefab", "path": str(tmp_path / "Crate.tcprefab")}
    )
    assert prefab_entity["prefab_instance"]["source_asset_id"] == "tc.asset.prefab"
    assert prefab_entity["prefab_instance"]["overrides"] == {}
    assert prefab_entity["prefab_instance"]["override_state"] == "inherited"


def test_background_native_preview_replaces_visible_fallback_without_replacing_scene(tmp_path, monkeypatch) -> None:
    host = _PlacementHost(tmp_path)
    entity = host.place_asset_from_browser(
        {"asset_id": "tc.asset.fbx", "type_id": "tc.static_mesh", "path": str(tmp_path / "Hero.fbx")}
    )
    fallback = host.mesh.scene_proxy_objects[-1]
    preview_model = FBXMeshModel("native-preview")
    monkeypatch.setattr(FBXMeshModel, "from_native_fbx_asset", classmethod(lambda cls, _asset: preview_model))
    job = {"asset_id": "tc.asset.fbx"}
    host._asset_preview_import_jobs = [job]

    host._complete_native_asset_preview(
        job, entity, tuple(entity["transform"]["position"]), fallback,
        True, SimpleNamespace(source_path=str(tmp_path / "Hero.fbx")), "ready",
    )

    assert not fallback.visible
    assert entity["asset_instance"]["preview_state"] == "native"
    assert host.mesh.scene_proxy_objects[-1].mesh_data.topology_state == "asset_preview"
    assert len(host._runtime_world_state["entities"]) == 1


def test_level_actor_identity_create_duplicate_rename_and_delete(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    first = host.place_asset_from_browser({"asset_id": "mesh", "type_id": "tc.static_mesh", "path": str(tmp_path / "Crate.fbx")})
    second = host.place_asset_from_browser({"asset_id": "mesh", "type_id": "tc.static_mesh", "path": str(tmp_path / "Crate.fbx")})
    assert first["entity_id"] != second["entity_id"]
    assert host.mesh.scene_proxy_objects[0].source_key != host.mesh.scene_proxy_objects[1].source_key

    assert host.rename_selected_level_actor("HeroCrate")
    assert second["name"] == "HeroCrate"
    assert host.duplicate_selected_level_actor()
    duplicate = host._runtime_world_state["entities"][-1]
    assert duplicate["entity_id"] != second["entity_id"]
    assert duplicate["name"] == "HeroCrate_Copy"
    assert host.delete_selected_level_actor()
    assert duplicate not in host._runtime_world_state["entities"]

    light = host.create_level_actor("point_light")
    assert light["light"]["type"] == "point"
    assert any(component["type"] == "light" for component in light["components"])
    collider = host.add_component_to_selected_level_actor("collider")
    assert collider and collider["shape"] == "box"
    assert host.remove_component_from_selected_level_actor(collider["component_id"])
    assert collider not in light["components"]
    transform = next(component for component in light["components"] if component["type"] == "transform")
    assert not host.remove_component_from_selected_level_actor(transform["component_id"])


def test_local_level_actor_transform_commits_to_runtime_world(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    entity = host.create_level_actor("empty")
    proxy = host._selected_scene_proxy
    host.viewport_mode = "Rotate"
    proxy["_pending_rotation_absolute"] = (0.0, 45.0, 0.0)
    ok, _message = host.commit_selected_proxy_transform()
    assert ok and entity["transform"]["rotation"] == [0.0, 45.0, 0.0]


def test_actor_folders_parenting_group_transform_and_component_properties(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    parent = host.create_level_actor("empty", "Parent")
    parent_proxy = host._selected_scene_proxy
    child = host.create_level_actor("empty", "Child")
    child_proxy = host._selected_scene_proxy

    class _Item:
        def __init__(self, proxy): self.proxy = proxy
        def data(self, _column, _role): return {"proxy": self.proxy}
    class _Tree:
        def selectedItems(self): return [_Item(parent_proxy), _Item(child_proxy)]
    host.scene_outliner = _Tree()
    assert host.create_actor_folder("Gameplay/Enemies")
    assert host.move_selected_level_actors_to_folder("Gameplay/Enemies") == 2
    host.scene_outliner = type("OneTree", (), {"selectedItems": lambda self: [_Item(child_proxy)]})()
    assert host.parent_selected_level_actors(parent["entity_id"]) == 1
    assert child["parent_entity_id"] == parent["entity_id"]
    host.scene_outliner = type("ParentTree", (), {"selectedItems": lambda self: [_Item(parent_proxy)]})()
    assert host.parent_selected_level_actors(child["entity_id"]) == 0
    host.scene_outliner = type("OneTree", (), {"selectedItems": lambda self: [_Item(child_proxy)]})()
    assert host.transform_selected_level_actors(translation=(10.0, 0.0, 0.0)) == 1
    assert child["transform"]["position"][0] == 10.0
    collider = host.add_component_to_selected_level_actor("collider")
    assert host.update_component_on_selected_level_actor(collider["component_id"], {"shape": "capsule", "is_trigger": True})
    assert collider["shape"] == "capsule" and collider["is_trigger"] is True

    prefab = host.place_asset_from_browser({"asset_id": "prefab", "type_id": "tc.prefab", "path": str(tmp_path / "Actor.tcprefab")})
    assert host.set_prefab_override_on_selected_level_actor("0.transform.position", [1, 2, 3])
    assert prefab["prefab_instance"]["override_state"] == "overridden"
    assert host.remove_prefab_override_from_selected_level_actor("0.transform.position")
    assert prefab["prefab_instance"]["override_state"] == "inherited"


def test_unpack_prefab_materializes_editable_hierarchy_and_breaks_link(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    prefab = host.place_asset_from_browser({"asset_id": "prefab", "type_id": "tc.prefab", "path": str(tmp_path / "Vehicle.tcprefab")})
    prefab["transform"]["position"] = [10.0, 0.0, 2.0]
    prefab["prefab_instance"]["entities"] = [
        {"entity_id": "body", "name": "Body", "transform": {"translation": [1.0, 0.0, 0.0]}, "components": {"mesh": {"asset_id": "body-mesh"}}},
        {"entity_id": "wheel", "name": "Wheel", "parent_entity_id": "body", "transform": {"translation": [0.0, 2.0, 0.0]}, "components": {}},
    ]

    assert host.unpack_selected_prefab_instance() == 3
    assert "prefab_instance" not in prefab
    assert prefab["asset_instance"]["type_id"] == "tc.prefab_unpacked"
    body, wheel = host._runtime_world_state["entities"][-2:]
    assert body["parent_entity_id"] == prefab["entity_id"]
    assert wheel["parent_entity_id"] == body["entity_id"]
    assert body["transform"]["position"] == [11.0, 0.0, 2.0]
    assert wheel["transform"]["position"] == [10.0, 2.0, 2.0]
    assert all(entity.get("unpacked_from_prefab_asset_id") == "prefab" for entity in (body, wheel))
    assert len(host.mesh.scene_proxy_objects) == 3


def test_multi_selection_visibility_lock_components_and_camera_workflows(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    first = host.create_level_actor("empty", "First")
    first_proxy = host._selected_scene_proxy
    second = host.create_level_actor("empty", "Second")
    second_proxy = host._selected_scene_proxy
    third = host.create_level_actor("empty", "Third")

    class _Item:
        def __init__(self, proxy): self.proxy = proxy
        def data(self, _column, _role): return {"proxy": self.proxy}
    class _Tree:
        def selectedItems(self): return [_Item(first_proxy), _Item(second_proxy)]
    host.scene_outliner = _Tree()
    host._selected_scene_proxy = second_proxy

    assert host.set_selected_level_actors_locked(True) == 2
    assert first["editor_locked"] and second["editor_locked"]
    assert host.transform_selected_level_actors(translation=(5.0, 0.0, 0.0)) == 0
    assert host.set_selected_level_actors_locked(False) == 2
    assert host.transform_selected_level_actors(translation=(5.0, 0.0, 0.0)) == 2
    assert first["transform"]["position"][0] == 5.0
    assert second["transform"]["position"][0] == 5.0

    assert host.hide_selected_level_actors() == 2
    assert not first["visible"] and not second["visible"]
    assert host.show_all_level_actors() == 3
    assert all(entity["visible"] for entity in host._runtime_world_state["entities"])
    assert host.isolate_selected_level_actors() == 2
    assert first["visible"] and second["visible"] and not third["visible"]
    assert host.show_all_level_actors() == 3

    assert host.duplicate_selected_level_actors() == 2
    duplicates = host._runtime_world_state["entities"][-2:]
    assert len({entity["entity_id"] for entity in duplicates}) == 2
    assert all(entity["entity_id"] not in {first["entity_id"], second["entity_id"]} for entity in duplicates)
    assert all(
        {component["component_id"] for component in duplicate["components"]}.isdisjoint(
            {component["component_id"] for component in source["components"]}
        )
        for duplicate, source in zip(duplicates, (first, second))
    )

    camera = host.create_level_actor("camera", "ShotCamera")
    camera_proxy = host._selected_scene_proxy
    collider = host.add_component_to_selected_level_actor("collider")
    assert host.move_component_on_selected_level_actor(collider["component_id"], -1)
    assert [component["type"] for component in camera["components"]] == ["transform", "collider", "camera"]
    host.viewport_camera.eye = (1.0, 2.0, 3.0); host.viewport_camera.target = (0.0, 1.0, 0.0)
    assert host.save_camera_bookmark(1)
    host.viewport_camera.eye = (9.0, 9.0, 9.0)
    assert host.recall_camera_bookmark(1) and host.viewport_camera.eye == (1.0, 2.0, 3.0)
    host._selected_scene_proxy = camera_proxy
    assert host.pilot_selected_camera_actor()
    host.viewport_camera.eye = (4.0, 5.0, 6.0); host.viewport_camera.target = (0.0, 2.0, 0.0)
    assert host.stop_piloting_camera_actor(commit=True)
    assert camera["transform"]["position"] == [4.0, 5.0, 6.0]
    assert camera["camera"]["look_at"] == [0.0, 2.0, 0.0]


def test_viewport_selection_helper_preserves_primary_and_toggle_semantics(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    first = host.create_level_actor("empty", "First")
    first_proxy = host._selected_scene_proxy
    second = host.create_level_actor("empty", "Second")
    second_proxy = host._selected_scene_proxy
    tree = QTreeWidget(); tree.setSelectionMode(QAbstractItemView.ExtendedSelection); parent = QTreeWidgetItem(["Actors"]); tree.addTopLevelItem(parent)
    for proxy in (first_proxy, second_proxy):
        item = QTreeWidgetItem([proxy["name"]]); item.setData(0, Qt.UserRole, {"kind": "object", "proxy": proxy}); parent.addChild(item)
    host.scene_outliner = tree

    assert host.set_selected_level_actor_ids([first["entity_id"], second["entity_id"]], primary_id=second["entity_id"]) == 2
    assert len(tree.selectedItems()) == 2 and host._selected_scene_proxy is second_proxy
    assert host.select_level_actor_proxy(second_proxy, toggle=True) == 1
    assert len(tree.selectedItems()) == 1 and host._selected_scene_proxy is first_proxy
    assert host.select_level_actor_proxy(second_proxy, additive=True) == 2
    assert len(tree.selectedItems()) == 2 and host._selected_scene_proxy is second_proxy

def test_transform_pivot_modes_and_snapping_are_explicit(tmp_path) -> None:
    host = _PlacementHost(tmp_path)
    first = {"center": (1.0, 2.0, 3.0), "provider_id": "tech_connector"}
    second = {"center": (5.0, 6.0, 7.0), "provider_id": "tech_connector"}
    host._selected_scene_proxy = first
    host.mesh.scene_proxy_objects = [first, second]
    host.shared_local_to_display_local = lambda point: tuple(point)
    host.display_local_to_shared_local = lambda point: tuple(point)
    host._proxy_center_display = lambda proxy: tuple(proxy["center"])
    host.selected_level_actor_proxies = lambda: [first, second]

    assert host.configure_transform_pivot("Selection Center") == "selection"
    assert host.transform_pivot_display() == (3.0, 4.0, 5.0)
    assert host.configure_transform_pivot("World Origin") == "world"
    assert host.transform_pivot_display() == (0.0, 0.0, 0.0)

    settings = host.configure_transform_snapping(
        translation=2.0, rotation=15.0, scale=0.1,
        enabled=True, target="vertex", snap_base="median",
    )
    assert settings["target"] == "point"
    assert settings["snap_base"] == "median"
    assert settings["enabled"] is True

    host.configure_transform_pivot("Custom Pivot", (2.9, 4.1, 5.2))
    assert host.snap_transform_pivot("grid")
    assert host.transform_pivot_custom_shared == (2.0, 4.0, 6.0)
    assert host.snap_transform_pivot("point")
    assert host.transform_pivot_custom_shared == (1.0, 2.0, 3.0) or host.transform_pivot_custom_shared == (5.0, 6.0, 7.0)
