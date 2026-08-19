from __future__ import annotations

import pytest

from tech_connector.game_engine.scene.coordinate_space_service import (
    convert_camera_payload_between_providers,
    convert_point_between_providers,
    convert_vector_between_providers,
    provider_bbox_to_shared,
    provider_native_to_shared,
    provider_scale_diagnostic,
    provider_space_label,
    shared_to_provider_native,
    snapshot_scale_diagnostics,
)


@pytest.mark.parametrize(
    ("provider", "unit", "native", "shared"),
    [
        ("maya", "centimeters", (1.0, 2.0, 3.0), (1.0, 2.0, 3.0)),
        ("blender", "meters", (1.0, 2.0, 3.0), (100.0, 300.0, -200.0)),
        ("unreal", "centimeters", (1.0, 2.0, 3.0), (2.0, 3.0, 1.0)),
    ],
)
def test_provider_native_to_shared_axis_and_unit_mapping(provider, unit, native, shared):
    assert provider_native_to_shared(provider, native, unit) == pytest.approx(shared)


@pytest.mark.parametrize(
    ("provider", "unit", "native"),
    [
        ("maya", "centimeters", (12.5, -4.0, 9.25)),
        ("blender", "meters", (1.25, -4.0, 9.25)),
        ("unreal", "centimeters", (125.0, -40.0, 925.0)),
    ],
)
def test_native_shared_native_round_trip_preserves_source_position(provider, unit, native):
    shared = provider_native_to_shared(provider, native, unit)
    restored = shared_to_provider_native(provider, shared, unit)
    assert restored == pytest.approx(native)


def test_blender_to_unreal_conversion_uses_shared_basis_and_units():
    # Blender one meter right, two meters forward, three meters up.
    unreal = convert_point_between_providers(
        "blender",
        "unreal",
        (1.0, -2.0, 3.0),
        source_unit="meters",
        target_unit="centimeters",
    )
    assert unreal == pytest.approx((200.0, 100.0, 300.0))


@pytest.mark.parametrize(
    ("source", "target", "point", "source_unit", "target_unit", "expected"),
    [
        ("maya", "blender", (10.0, 20.0, 30.0), "centimeters", "meters", (0.1, -0.3, 0.2)),
        ("maya", "unreal", (10.0, 20.0, 30.0), "centimeters", "centimeters", (30.0, 10.0, 20.0)),
        ("blender", "maya", (0.1, -0.3, 0.2), "meters", "centimeters", (10.0, 20.0, 30.0)),
        ("unreal", "maya", (30.0, 10.0, 20.0), "centimeters", "centimeters", (10.0, 20.0, 30.0)),
    ],
)
def test_maya_default_shared_space_matches_blender_and_unreal_axes_and_scale(
    source,
    target,
    point,
    source_unit,
    target_unit,
    expected,
):
    assert convert_point_between_providers(
        source,
        target,
        point,
        source_unit=source_unit,
        target_unit=target_unit,
    ) == pytest.approx(expected)


def test_blender_empty_unit_uses_meter_default_for_scene_snapshots():
    assert provider_native_to_shared("blender", (1.0, 0.0, 0.0), "") == pytest.approx((100.0, 0.0, 0.0))
    assert shared_to_provider_native("blender", (100.0, 0.0, 0.0), "") == pytest.approx((1.0, 0.0, 0.0))


def test_blender_metric_unit_reported_by_live_snapshot_maps_to_meters():
    assert provider_bbox_to_shared("blender", (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0), "METRIC") == pytest.approx(
        (-100.0, -100.0, -100.0, 100.0, 100.0, 100.0)
    )


def test_live_scale_diagnostic_reports_blender_to_maya_factor_from_unit_string():
    diagnostic = provider_scale_diagnostic("blender", "METRIC", reference_provider_id="maya", reference_unit_linear="cm")
    assert diagnostic.centimeters_per_native_unit == pytest.approx(100.0)
    assert diagnostic.native_to_reference_scale == pytest.approx(100.0)
    assert diagnostic.reference_to_native_scale == pytest.approx(0.01)
    assert "blender:METRIC ->maya x100" == diagnostic.compact_label()


def test_snapshot_scale_diagnostics_are_built_from_current_scene_units():
    diagnostics = snapshot_scale_diagnostics(
        {
            "maya": {"provider_id": "maya", "unit_linear": "cm"},
            "blender": {"provider_id": "blender", "unit_linear": "METRIC"},
            "unreal": {"provider_id": "unreal", "unit_linear": "centimeters"},
        }
    )
    assert diagnostics["maya"].native_to_reference_scale == pytest.approx(1.0)
    assert diagnostics["blender"].native_to_reference_scale == pytest.approx(100.0)
    assert diagnostics["unreal"].native_to_reference_scale == pytest.approx(1.0)


def test_cross_provider_delta_vectors_use_same_axis_and_unit_math_as_points():
    # Maya +Z forward is Blender -Y and Unreal +X.
    assert convert_vector_between_providers(
        "maya",
        "blender",
        (0.0, 0.0, 25.0),
        source_unit="centimeters",
        target_unit="meters",
    ) == pytest.approx((0.0, -0.25, 0.0))
    assert convert_vector_between_providers(
        "maya",
        "unreal",
        (0.0, 0.0, 25.0),
        source_unit="centimeters",
        target_unit="centimeters",
    ) == pytest.approx((25.0, 0.0, 0.0))


def test_unreal_to_blender_conversion_round_trips_through_shared_space():
    unreal_native = (250.0, 100.0, 300.0)
    blender_native = convert_point_between_providers(
        "unreal",
        "blender",
        unreal_native,
        source_unit="centimeters",
        target_unit="meters",
    )
    restored = convert_point_between_providers(
        "blender",
        "unreal",
        blender_native,
        source_unit="meters",
        target_unit="centimeters",
    )
    assert restored == pytest.approx(unreal_native)


@pytest.mark.parametrize(
    ("provider", "unit", "shared_direction", "native_direction"),
    [
        ("maya", "centimeters", (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        ("maya", "centimeters", (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
        ("maya", "centimeters", (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)),
        ("blender", "meters", (1.0, 0.0, 0.0), (0.01, 0.0, 0.0)),
        ("blender", "meters", (0.0, 1.0, 0.0), (0.0, 0.0, 0.01)),
        ("blender", "meters", (0.0, 0.0, 1.0), (0.0, -0.01, 0.0)),
        ("unreal", "centimeters", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ("unreal", "centimeters", (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        ("unreal", "centimeters", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    ],
)
def test_shared_camera_basis_maps_to_provider_native_axes(provider, unit, shared_direction, native_direction):
    assert shared_to_provider_native(provider, shared_direction, unit) == pytest.approx(native_direction)


def test_bbox_conversion_checks_all_corners_after_axis_remap():
    assert provider_bbox_to_shared("blender", (-1, -2, -3, 4, 5, 6), "meters") == pytest.approx(
        (-100.0, -300.0, -500.0, 400.0, 600.0, 200.0)
    )


def test_maya_one_meter_cube_matches_blender_one_meter_cube_in_shared_bounds():
    maya_cm_cube = provider_bbox_to_shared("maya", (0.0, 0.0, 0.0, 100.0, 100.0, 100.0), "centimeters")
    blender_m_cube = provider_bbox_to_shared("blender", (0.0, -1.0, 0.0, 1.0, 0.0, 1.0), "meters")
    assert maya_cm_cube == pytest.approx(blender_m_cube)


def test_camera_payload_conversion_preserves_maya_view_direction_in_blender_and_unreal():
    maya_payload = {
        "eye": (0.0, 200.0, -500.0),
        "target": (0.0, 100.0, 0.0),
        "up_target": (0.0, 101.0, 0.0),
        "fov_degrees": 42.0,
        "aspect_ratio": 16.0 / 9.0,
        "near_clip": 0.1,
        "far_clip": 10000.0,
    }
    blender_payload = convert_camera_payload_between_providers(
        "maya",
        "blender",
        maya_payload,
        source_unit="centimeters",
        target_unit="meters",
    )
    unreal_payload = convert_camera_payload_between_providers(
        "maya",
        "unreal",
        maya_payload,
        source_unit="centimeters",
        target_unit="centimeters",
    )
    assert blender_payload["eye"] == pytest.approx((0.0, 5.0, 2.0))
    assert blender_payload["target"] == pytest.approx((0.0, 0.0, 1.0))
    assert blender_payload["up_target"] == pytest.approx((0.0, 0.0, 1.01))
    assert unreal_payload["eye"] == pytest.approx((-500.0, 0.0, 200.0))
    assert unreal_payload["target"] == pytest.approx((0.0, 0.0, 100.0))
    assert unreal_payload["up_target"] == pytest.approx((0.0, 0.0, 101.0))
    assert blender_payload["fov_degrees"] == pytest.approx(42.0)
    assert unreal_payload["aspect_ratio"] == pytest.approx(16.0 / 9.0)


def test_camera_payload_bounds_remap_preserves_relative_framing_across_scene_scale():
    maya_payload = {
        "eye": (0.0, 0.0, -200.0),
        "target": (0.0, 0.0, 0.0),
        "up_target": (0.0, 1.0, 0.0),
    }
    converted = convert_camera_payload_between_providers(
        "maya",
        "blender",
        maya_payload,
        source_unit="centimeters",
        target_unit="meters",
        source_bounds_shared=((0.0, 0.0, 0.0), 100.0),
        target_bounds_shared=((1000.0, 0.0, 0.0), 200.0),
    )
    # Source camera is two source-extents behind its target; target scene is
    # twice as large and centered at shared X=1000cm, then expressed in meters.
    assert converted["target"] == pytest.approx((10.0, 0.0, 0.0))
    assert converted["eye"] == pytest.approx((10.0, 4.0, 0.0))
    assert converted["up_target"] == pytest.approx((10.0, 0.0, 0.02))


def test_provider_space_labels_are_explicit():
    assert "Z up" in provider_space_label("unreal", "centimeters")
    assert "X forward" in provider_space_label("unreal", "centimeters")
    assert "-Y forward" in provider_space_label("blender", "meters")


def test_viewport_scene_element_filter_excludes_cameras_and_backgrounds():
    from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel

    assert not FBXMeshModel._include_snapshot_object_as_scene_element({"type": "CameraActor", "name": "ShotCam"})
    assert not FBXMeshModel._include_snapshot_object_as_scene_element({"type": "StaticMeshActor", "name": "SM_SkySphere"})
    assert not FBXMeshModel._include_snapshot_object_as_scene_element({"type": "mesh", "name": "TechConnector_Camera"})
    assert not FBXMeshModel._include_snapshot_object_as_scene_element({"type": "WorldDataLayers", "name": "WorldDataLayers"})
    assert FBXMeshModel._include_snapshot_object_as_scene_element({"type": "StaticMeshActor", "name": "HeroProp"})


@pytest.mark.parametrize(
    "obj",
    [
        {"type": "joint", "name": "spine_01", "shape_types": []},
        {"type": "transform", "name": "hairFollicle", "shape_types": ["follicle"]},
        {"type": "transform", "name": "surfaceRig", "shape_types": ["nurbsSurface"]},
        {"type": "rigidBody", "name": "ragdollBody", "shape_types": []},
        {"type": "collision", "name": "UCX_Blocker", "shape_types": []},
        {"type": "pointLight", "name": "keyLight", "shape_types": ["pointLight"]},
        {"type": "light", "name": "Blender Light", "shape_types": ["light"]},
    ],
)
def test_viewport_scene_element_filter_keeps_template_editable_nodes(obj):
    from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel

    assert FBXMeshModel._include_snapshot_object_as_scene_element(obj)


def test_maya_viewport_camera_tumble_keeps_world_up_stable():
    from tech_connector.ui.three_d_mesh_painter_widget import MayaViewportCamera, _vec_dot

    camera = MayaViewportCamera()
    for dx, dy in [(48.0, 12.0), (36.0, -18.0), (-20.0, 8.0), (16.0, -10.0)]:
        camera.tumble(dx, dy)
    forward, right, up = camera.view_axes()
    assert _vec_dot(right, (0.0, 1.0, 0.0)) == pytest.approx(0.0, abs=1.0e-6)
    assert _vec_dot(up, (0.0, 1.0, 0.0)) > 0.65
    assert abs(_vec_dot(forward, up)) < 1.0e-6


def test_federated_scene_can_preserve_existing_maya_normal_when_adding_blender():
    from tech_connector.ui.three_d_mesh_painter_widget import FBXMeshModel

    maya_snapshot = {
        "provider_id": "maya",
        "unit_linear": "centimeters",
        "objects": [
            {
                "native_id": "pCube1",
                "name": "pCube1",
                "type": "mesh",
                "bbox": (-0.5, 1.5, -0.5, 0.5, 2.5, 0.5),
                "translation": (0.0, 2.0, 0.0),
                "rotation": (0.0, 0.0, 0.0),
                "scale": (1.0, 1.0, 1.0),
                "visible": True,
            }
        ],
        "cameras": [],
    }
    blender_snapshot = {
        "provider_id": "blender",
        "unit_linear": "centimeters",
        "objects": [
            {
                "native_id": "Cube",
                "name": "Cube",
                "type": "mesh",
                "bbox": (-1.0, -1.0, -1.0, 1.0, 1.0, 1.0),
                "translation": (0.0, 0.0, 0.0),
                "rotation": (0.0, 0.0, 0.0),
                "scale": (1.0, 1.0, 1.0),
                "visible": True,
            }
        ],
        "cameras": [],
    }
    maya_model = FBXMeshModel.from_scene_snapshots([maya_snapshot])
    maya_proxy_center = maya_model.scene_proxy_objects[0].center
    federated = FBXMeshModel.from_scene_snapshots(
        [maya_snapshot, blender_snapshot],
        scene_center=maya_model.scene_center,
        scene_scale=maya_model.scene_scale,
    )
    assert federated.scene_center == pytest.approx(maya_model.scene_center)
    assert federated.scene_scale == pytest.approx(maya_model.scene_scale)
    maya_proxy = next(proxy for proxy in federated.scene_proxy_objects if proxy.provider_id == "maya")
    blender_proxy = next(proxy for proxy in federated.scene_proxy_objects if proxy.provider_id == "blender")
    assert maya_proxy.center == pytest.approx(maya_proxy_center)
    assert maya_proxy.center[1] > blender_proxy.center[1]


def test_federated_scene_composes_embedded_fbx_and_dcc_without_mutating_source_ranges():
    from tech_connector.ui.three_d_mesh_painter_widget import (
        FBXMeshModel,
        MeshVertex3D,
        SceneProxyInstance,
        SceneProxyMeshData,
    )

    native_model = object.__new__(FBXMeshModel)
    native_model.name = "prop.fbx"
    native_model.vertices = [
        MeshVertex3D(-2.0, -2.0, 0.0),
        MeshVertex3D(2.0, -2.0, 0.0),
        MeshVertex3D(-2.0, 2.0, 0.0),
    ]
    native_model.faces = [(0, 1, 2)]
    native_model.quad_faces = []
    native_model.face_colors = []
    native_model.quad_face_colors = []
    native_model.face_proxy_indices = [0]
    native_model.quad_proxy_indices = []
    native_model.scene_proxy_objects = [SceneProxyInstance(
        index=0,
        provider_id="native_fbx",
        native_id="Prop",
        name="Prop",
        center=(0.0, 0.0, 0.0),
        mesh_data=SceneProxyMeshData(vertex_count=3, face_count=1),
    )]
    native_model.source_texture_images = {}
    native_model.provider_id = "native_fbx"
    native_model.scene_center = (50.0, 50.0, 0.0)
    native_model.scene_scale = 0.04
    native_model.native_fbx_manifest = {"schema": "tech_connector.native_fbx_asset.v1"}
    native_model.source_path = "C:/show/prop.fbx"
    native_range_before = native_model.scene_proxy_objects[0].mesh_data.vertex_start
    maya_snapshot = {
        "provider_id": "maya",
        "unit_linear": "centimeters",
        "objects": [{
            "native_id": "pPlane1",
            "name": "pPlane1",
            "type": "mesh",
            "bbox": (0.0, 0.0, 0.0, 100.0, 100.0, 0.0),
            "visible": True,
        }],
    }

    combined = FBXMeshModel.from_scene_snapshots(
        [maya_snapshot],
        retained_models=[native_model],
    )
    repeated = FBXMeshModel.from_scene_snapshots(
        [maya_snapshot],
        retained_models=[native_model],
    )

    assert native_model.scene_proxy_objects[0].mesh_data.vertex_start == native_range_before
    assert len(combined.scene_proxy_objects) == 2
    assert len(repeated.vertices) == len(combined.vertices)
    native_proxy = next(proxy for proxy in combined.scene_proxy_objects if proxy.provider_id == "native_fbx")
    maya_proxy = next(proxy for proxy in combined.scene_proxy_objects if proxy.provider_id == "maya")
    assert native_proxy.center == pytest.approx(maya_proxy.center)
    assert max(abs(vertex.x) for vertex in combined.vertices) <= 2.01
    assert max(abs(vertex.y) for vertex in combined.vertices) <= 2.01

