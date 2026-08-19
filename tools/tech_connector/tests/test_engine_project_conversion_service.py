from tech_connector.services.dcc.engine_project_conversion_service import (
    EngineProjectManifest,
    EngineSemanticNode,
    engine_project_adapters,
    plan_engine_project_conversion,
)


def test_unreal_character_conversion_includes_executable_dependencies():
    manifest = EngineProjectManifest(
        provider="unreal",
        project_id="locomotion",
        engine_version="5.x",
        nodes=(
            EngineSemanticNode("mesh", "geometry", "SkeletalMesh"),
            EngineSemanticNode("ik", "ik_rig", "IKRigDefinition", ("mesh",)),
            EngineSemanticNode("poses", "motion_matching", "PoseSearchDatabase", ("mesh",)),
            EngineSemanticNode(
                "anim_bp",
                "animation_state_machine",
                "AnimBlueprint",
                ("ik", "poses"),
            ),
            EngineSemanticNode(
                "player",
                "gameplay_graph",
                "BlueprintGeneratedClass",
                ("anim_bp",),
            ),
        ),
    )

    plan = plan_engine_project_conversion(manifest, ["player"])

    assert plan["dependency_closed"] is True
    assert plan["executable_after_conversion"] is True
    assert [item["source_id"] for item in plan["operations"]] == [
        "mesh",
        "ik",
        "poses",
        "anim_bp",
        "player",
    ]
    assert all(item["strategy"] == "translate" for item in plan["operations"])


def test_conversion_plan_reports_missing_dependencies():
    manifest = EngineProjectManifest(
        provider="unity",
        project_id="sample",
        engine_version="6.x",
        nodes=(
            EngineSemanticNode(
                "controller",
                "animation_state_machine",
                "AnimatorController",
                ("missing_clip",),
            ),
        ),
    )

    plan = plan_engine_project_conversion(manifest, ["controller"])

    assert plan["dependency_closed"] is False
    assert plan["executable_after_conversion"] is False
    assert plan["missing_dependencies"] == [["controller", "missing_clip"]]


def test_code_and_vfx_are_preserved_when_not_directly_translated():
    manifest = EngineProjectManifest(
        provider="unity",
        project_id="sample",
        engine_version="6.x",
        nodes=(
            EngineSemanticNode("script", "code", "MonoBehaviour"),
            EngineSemanticNode("effect", "vfx", "VisualEffectAsset"),
        ),
    )

    plan = plan_engine_project_conversion(manifest)
    operations = {item["source_id"]: item for item in plan["operations"]}

    assert operations["script"]["strategy"] == "source_proxy"
    assert operations["script"]["preserve_source_payload"] is True
    assert operations["effect"]["strategy"] == "bake"
    assert operations["effect"]["preserve_source_payload"] is True
    assert plan["standalone_runtime_ready"] is False
    assert plan["runtime_dependencies"] == [
        "Source proxy requires a translator: script (MonoBehaviour)"
    ]


def test_registered_engine_adapters_require_the_native_editor():
    adapters = engine_project_adapters()

    assert adapters["unreal"]["extraction_mode"] == "compatible_engine_editor_plugin"
    assert adapters["unity"]["extraction_mode"] == "compatible_engine_editor_package"


def test_dependency_cycles_continue_traversal_for_other_dependencies() -> None:
    manifest = EngineProjectManifest(
        provider="unreal",
        project_id="looped",
        engine_version="5.x",
        nodes=(
            EngineSemanticNode("root", "geometry", "SM_Root", ("bridge",)),
            EngineSemanticNode("bridge", "geometry", "SM_Bridge", ("root", "surface")),
            EngineSemanticNode("surface", "material", "M_Cycle", ()),
        ),
    )

    plan = plan_engine_project_conversion(manifest, ["root"])

    assert [item["source_id"] for item in plan["operations"]] == ["surface", "bridge", "root"]
    assert plan["dependency_closed"] is True
    assert plan["standalone_runtime_ready"] is False
    assert plan["executable_after_conversion"] is False
    assert any(cycle == ["root", "bridge", "root"] for cycle in plan["cycles"])
