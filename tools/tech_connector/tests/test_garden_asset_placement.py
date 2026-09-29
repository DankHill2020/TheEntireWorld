from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

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
