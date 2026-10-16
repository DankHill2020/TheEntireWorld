from __future__ import annotations

from types import SimpleNamespace

from blender_tools.animation import set_keyframe
from blender_tools.io import export_fbx, import_fbx
from blender_tools.validation import inspect_generalist_asset
from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry
from tech_connector.game_engine.integration.dcc_production_workflow_service import PRODUCTION_WORKFLOWS


def _install_bpy(monkeypatch, bpy) -> None:
    monkeypatch.setitem(__import__("sys").modules, "bpy", bpy)


def test_blender_keyframe_and_inspector_prove_authored_animation(monkeypatch) -> None:
    material = object()
    inserted = []
    obj = SimpleNamespace(
        name="TC_WorkflowMesh",
        type="MESH",
        location=[0.0, 0.0, 0.0],
        data=SimpleNamespace(polygons=[object()] * 6, uv_layers=[object()]),
        material_slots=[SimpleNamespace(material=material)],
        animation_data=SimpleNamespace(
            action=SimpleNamespace(
                fcurves=[SimpleNamespace(keyframe_points=[SimpleNamespace(co=(1.0, 0.0)), SimpleNamespace(co=(24.0, 2.0))])],
            ),
        ),
        keyframe_insert=lambda **kwargs: inserted.append(kwargs) or True,
    )
    bpy = SimpleNamespace(
        data=SimpleNamespace(
            objects=SimpleNamespace(get=lambda name: obj if name == obj.name else None),
            materials=SimpleNamespace(get=lambda name: material if name == "TC_WorkflowMaterial" else None),
        ),
    )
    _install_bpy(monkeypatch, bpy)

    key = set_keyframe(obj.name, "location", 24, 2.0, index=0)
    inspected = inspect_generalist_asset(obj.name, "TC_WorkflowMaterial", 1, 24)

    assert key["ok"] and obj.location[0] == 2.0
    assert inserted == [{"data_path": "location", "index": 0, "frame": 24}]
    assert inspected["parity_checks"] == {
        "topology": True,
        "UV and materials": True,
        "animation range": True,
    }


def test_blender_inspector_follows_skinned_mesh_armature_animation(monkeypatch) -> None:
    material = object()
    armature = SimpleNamespace(
        name="Armature",
        animation_data=SimpleNamespace(action=SimpleNamespace(fcurves=[], frame_range=(1.0, 24.0))),
    )
    mesh = SimpleNamespace(
        name="SkinnedMesh",
        type="MESH",
        parent=armature,
        modifiers=[],
        data=SimpleNamespace(polygons=[object()] * 6, uv_layers=[object()]),
        material_slots=[SimpleNamespace(material=material)],
        animation_data=None,
    )
    bpy = SimpleNamespace(
        data=SimpleNamespace(
            objects=SimpleNamespace(get=lambda name: mesh if name == mesh.name else None),
            materials=SimpleNamespace(get=lambda name: material if name == "SkinMaterial" else None),
        ),
    )
    _install_bpy(monkeypatch, bpy)

    inspected = inspect_generalist_asset(mesh.name, "SkinMaterial", 1, 24)

    assert inspected["animated_objects"] == ["Armature"]
    assert inspected["key_times"] == [1.0, 24.0]
    assert inspected["parity_checks"]["animation range"] is True


def test_blender_fbx_export_requires_file_and_reports_axis_parity(monkeypatch, tmp_path) -> None:
    target = tmp_path / "asset.fbx"

    def export(**kwargs):
        __import__("pathlib").Path(kwargs["filepath"]).write_bytes(b"fbx")

    bpy = SimpleNamespace(ops=SimpleNamespace(export_scene=SimpleNamespace(fbx=export)))
    _install_bpy(monkeypatch, bpy)

    result = export_fbx(str(target), selected_only=False, axis_forward="-Z", axis_up="Y")

    assert result["parity_checks"] == {"coordinate conversion": True}
    assert result["axis_forward"] == "-Z" and result["axis_up"] == "Y"


def test_blender_fbx_export_can_scope_an_explicit_object_set(monkeypatch, tmp_path) -> None:
    target = tmp_path / "scoped.fbx"
    selected = []
    objects = {
        name: SimpleNamespace(select_set=lambda value, item=name: selected.append((item, value)))
        for name in ("Mesh", "Armature", "Mesh_LOD1", "UCX_Mesh_00")
    }
    export_calls = []

    def export(**kwargs):
        export_calls.append(kwargs)
        target.write_bytes(b"fbx")

    bpy = SimpleNamespace(
        data=SimpleNamespace(objects=SimpleNamespace(get=objects.get)),
        ops=SimpleNamespace(
            object=SimpleNamespace(select_all=lambda **kwargs: selected.append(("*", kwargs["action"]))),
            export_scene=SimpleNamespace(fbx=export),
        ),
    )
    _install_bpy(monkeypatch, bpy)

    result = export_fbx(str(target), object_names=list(objects))

    assert result["objects"] == list(objects)
    assert result["selected_only"] is True
    assert export_calls[0]["use_selection"] is True
    assert selected[0] == ("*", "DESELECT")
    assert all(value is True for _, value in selected[1:])


def test_blender_fbx_import_preserves_source_animation_frames(monkeypatch, tmp_path) -> None:
    source = tmp_path / "animated.fbx"
    source.write_bytes(b"fbx")
    existing = type("Object", (), {"name": "Existing"})()
    imported = type("Object", (), {"name": "ImportedRig"})()
    objects = [existing]
    calls = []

    def import_scene(**kwargs):
        calls.append(kwargs)
        objects.append(imported)

    bpy = SimpleNamespace(
        data=SimpleNamespace(objects=objects),
        ops=SimpleNamespace(import_scene=SimpleNamespace(fbx=import_scene)),
    )
    _install_bpy(monkeypatch, bpy)

    result = import_fbx(str(source))

    assert calls[0]["anim_offset"] == 0.0
    assert result["animation_offset"] == 0.0
    assert result["objects"] == ["ImportedRig"]


def test_blender_workflow_authors_keys_before_baking_and_uses_specific_inspector() -> None:
    steps = PRODUCTION_WORKFLOWS["blender.generalist_asset"].steps
    operations = [step.operation for step in steps]

    assert operations.count("animation.set_key") == 2
    assert operations.index("animation.set_key") < operations.index("animation.bake")
    assert operations[-1] == "workflow.inspect_generalist_asset"
    assert dcc_operation_registry("blender")["animation.set_key"].function == "blender_tools.animation.set_keyframe"
