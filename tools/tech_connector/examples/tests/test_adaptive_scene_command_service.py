from __future__ import annotations

from tech_connector.services.dcc.adaptive_scene_command_service import (
    SceneCommandTarget,
    list_adaptive_scene_commands,
    resolve_adaptive_scene_command,
    target_from_scene_proxy,
)


def test_lists_maya_style_adaptive_scene_commands() -> None:
    commands = list_adaptive_scene_commands()
    keys = {row["key"] for row in commands}

    assert "modeling.split_edge_loop" in keys
    assert "modeling.extrude_faces" in keys
    assert "modeling.triangulate_faces" in keys
    assert "animation.create_take" in keys
    assert "animation.add_layer" in keys
    assert "simulation.create_cloth" in keys
    assert "simulation.create_fluid" in keys
    assert "simulation.add_geometry_collider" in keys
    assert "simulation.build_transfer_manifest" in keys
    assert "simulation.compile_runtime_profile" in keys
    assert "simulation.inspect_execution_plan" in keys
    assert "scene.convert_to_tc" in keys
    assert "scene.compose_usd" in keys
    assert "scene.inspect_usd_composition" in keys
    assert "scene.set_usd_variant" in keys
    assert "rigging.create_ribbon_ik" in keys
    assert "rigging.constrain_to_normal" in keys
    assert "rigging.parent_constraint" in keys
    assert "skinning.bind_skin" in keys
    assert "skinning.auto_skin" in keys
    assert "skinning.paint_weights" in keys
    assert "skinning.transfer_weights" in keys
    assert any(row["department"] == "modeling" for row in commands)
    assert any(row["department"] == "skinning" for row in commands)


def test_resolves_split_edge_loop_to_maya_bridge_script() -> None:
    target = SceneCommandTarget(
        provider="maya",
        native_id="pCube1",
        object_type="mesh",
        component_type="edge_loop",
        components=("pCube1.e[4]",),
    )

    route = resolve_adaptive_scene_command("modeling.split_edge_loop", target, {"divisions": 2}).to_dict()

    assert route["host"] == "maya"
    assert route["status"] == "routable"
    assert route["execution_mode"] == "bridge_script"
    assert "polySplitRing" in route["script"]
    assert "pCube1.e[4]" in route["script"]


def test_resolves_local_edge_loop_to_tc_native_route() -> None:
    target = SceneCommandTarget(provider="tech_connector", native_id="LocalMesh", component_type="edge_loop")

    route = resolve_adaptive_scene_command("modeling.split_edge_loop", target).to_dict()

    assert route["host"] == "tech_connector"
    assert route["execution_mode"] == "tc_native"
    assert route["status"] == "routable"
    assert "engine import/conversion path remains valid" in route["validation"]


def test_resolves_implemented_local_modeling_and_animation_commands() -> None:
    target = SceneCommandTarget(provider="tech_connector", native_id="LocalMesh")

    extrude = resolve_adaptive_scene_command("modeling.extrude_faces", target, {"faces": [2], "distance": 0.25}).to_dict()
    take = resolve_adaptive_scene_command("animation.create_take", target, {"name": "Walk"}).to_dict()

    assert extrude["status"] == "routable"
    assert extrude["required_payload"]["faces"] == [2]
    assert take["status"] == "routable"
    assert take["execution_mode"] == "tc_native"


def test_active_viewer_command_dispatch_is_chat_callable() -> None:
    from tech_connector.services.dcc.active_viewer_command_service import (
        execute_active_viewer_command,
        register_active_viewer,
        unregister_active_viewer,
    )

    class Viewer:
        def execute_adaptive_scene_command(self, command, payload):
            return {"executed": True, "command": command, "payload": payload}

    viewer = Viewer()
    register_active_viewer(viewer)
    try:
        result = execute_active_viewer_command("modeling.extrude_faces", faces=[3], distance=0.5)
    finally:
        unregister_active_viewer(viewer)

    assert result == {
        "executed": True,
        "command": "modeling.extrude_faces",
        "payload": {"faces": [3], "distance": 0.5},
    }


def test_scene_proxy_target_preserves_bridge_identity() -> None:
    target = target_from_scene_proxy(
        {
            "provider_id": "maya:7001",
            "native_id": "|group|meshShapeParent",
            "name": "HeroMesh",
            "object_type": "mesh",
            "source_key": "maya:7001:HeroMesh",
        },
        component_type="face",
        components=["HeroMesh.f[12]"],
    )

    assert target.provider_base == "maya"
    assert target.source_key == "maya:7001:HeroMesh"
    assert target.components == ("HeroMesh.f[12]",)


def test_public_viewer_cmds_facade_routes_commands() -> None:
    from tech_connector import viewer_cmds

    route = viewer_cmds.split_edge_loop(
        viewer_cmds.target("maya", "pSphere1", component_type="edge_loop", components=["pSphere1.e[8]"]),
        divisions=3,
    )

    assert route["host"] == "maya"
    assert route["required_payload"]["divisions"] == 3
    assert "Tech Connector" not in route["callable"]


def test_convert_to_tc_routes_to_migration_pipeline() -> None:
    from tech_connector import viewer_cmds

    route = viewer_cmds.convert_to_tc(
        viewer_cmds.target("maya", "|world|HeroRig", object_type="skeletal_mesh"),
        include_animation=True,
        include_materials=True,
    )

    assert route["execution_mode"] == "tc_migration_pipeline"
    assert route["status"] == "routable"
    assert route["required_payload"]["source_provider"] == "maya"
    assert "TC-native scene graph created" in route["validation"]


def test_resolves_skinning_bind_to_maya_skin_cluster_script() -> None:
    target = SceneCommandTarget(provider="maya", native_id="HeroMesh", object_type="skeletal_mesh")

    route = resolve_adaptive_scene_command(
        "skinning.bind_skin",
        target,
        {"influences": ["Root_JNT", "Spine_JNT"], "max_influences": 4, "bind_method": "geodesic_voxel"},
    ).to_dict()

    assert route["host"] == "maya"
    assert route["status"] == "routable"
    assert "cmds.skinCluster" in route["script"]
    assert "bindMethod=3" in route["script"]
    assert route["required_payload"]["influences"] == ["Root_JNT", "Spine_JNT"]
    assert route["required_payload"]["bind_method"] == "geodesic_voxel"


def test_public_viewer_cmds_routes_skin_weight_paint() -> None:
    from tech_connector import viewer_cmds

    route = viewer_cmds.paint_weights(
        viewer_cmds.target("maya", "HeroMesh", component_type="vertex", components=["HeroMesh.vtx[3]"]),
        influence="Spine_JNT",
        weight=0.4,
    )

    assert route["host"] == "maya"
    assert route["status"] == "routable"
    assert "cmds.skinPercent" in route["script"]
    assert route["required_payload"]["components"] == ["HeroMesh.vtx[3]"]


def test_routes_skinning_auto_transfer_and_export_import_for_maya() -> None:
    target = SceneCommandTarget(provider="maya", native_id="HeroMesh", object_type="skeletal_mesh")

    auto_route = resolve_adaptive_scene_command(
        "skinning.auto_skin",
        target,
        {"influences": ["Root_JNT"], "bind_method": "heat"},
    ).to_dict()
    transfer_route = resolve_adaptive_scene_command(
        "skinning.transfer_weights",
        target,
        {"source_mesh": "SourceMesh", "target_mesh": "HeroMesh"},
    ).to_dict()
    export_route = resolve_adaptive_scene_command(
        "skinning.export_weights",
        target,
        {"path": "C:/tmp/HeroMesh.xml"},
    ).to_dict()
    import_route = resolve_adaptive_scene_command(
        "skinning.import_weights",
        target,
        {"path": "C:/tmp/HeroMesh.xml"},
    ).to_dict()

    assert "auto_skinner" in auto_route["script"]
    assert "cmds.copySkinWeights" in transfer_route["script"]
    assert "cmds.deformerWeights" in export_route["script"]
    assert "export=True" in export_route["script"]
    assert "import=True" in import_route["script"]
