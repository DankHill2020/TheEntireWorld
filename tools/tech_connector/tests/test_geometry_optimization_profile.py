from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QApplication

from tech_connector.game_engine.assets import (
    GEOMETRY_OPTIMIZATION_PRESETS,
    GEOMETRY_PROCESSORS,
    GEOMETRY_EXECUTION_MODES,
    builtin_asset_type_registry,
    compile_geometry_optimization_payload,
    geometry_optimization_preset,
    plan_geometry_optimization,
    validate_geometry_optimization_profile,
)
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.ui.game_engine.asset_editor_workspace import DedicatedAssetEditor
from tech_connector.ui.game_engine.asset_specialized_editors import GeometryOptimizationEditorWidget


def test_processor_vocabulary_covers_simplygon_style_outputs() -> None:
    assert {"reduction", "quad_reduction", "remeshing", "aggregation", "impostor", "occlusion_mesh"} <= set(GEOMETRY_PROCESSORS)
    assert {"character_balanced", "character_mobile", "prop_hlod", "distant_impostor", "occluder"} <= set(GEOMETRY_OPTIMIZATION_PRESETS)
    assert GEOMETRY_PROCESSORS["reduction"]["output"] != GEOMETRY_PROCESSORS["remeshing"]["output"]
    assert {"in_process", "isolated_process", "distributed_grid", "distributed_fastbuild", "distributed_incredibuild"} <= set(GEOMETRY_EXECUTION_MODES)


@pytest.mark.parametrize("preset", sorted(GEOMETRY_OPTIMIZATION_PRESETS))
def test_presets_are_valid_and_truthfully_report_local_backend_coverage(preset: str) -> None:
    properties = geometry_optimization_preset(preset)
    issues = validate_geometry_optimization_profile(properties)
    assert not [issue for issue in issues if issue.severity == "error"]
    plan = plan_geometry_optimization(properties)
    assert plan["executable"] is True
    if preset.startswith("character_"):
        assert plan["fully_local"] is True
        assert all(stage["execution_backend"] == "blender_decimate" for stage in plan["stages"])
    else:
        assert plan["fully_local"] is False
        assert any(issue["code"] == "backend_unavailable" for issue in plan["issues"])


def test_incompatible_component_and_bad_target_are_rejected() -> None:
    properties = {
        "stages": [{"stage_id": "bad", "processor": "aggregation", "enabled": True,
                    "components": ["skinning"], "settings": {}}],
        "components": {"skinning": {"preserve_weights": True}},
    }
    assert {issue.code for issue in validate_geometry_optimization_profile(properties)} >= {"incompatible_component"}
    with pytest.raises(ValueError, match="Invalid Geometry Optimization Profile"):
        compile_geometry_optimization_payload(properties)


def test_python_api_creates_assigns_plans_and_cooks_profile(tmp_path) -> None:
    api = TCEditorAPI(tmp_path)
    skeleton = api.create_asset("tc.skeleton", "HeroSkeleton", folder="Assets/Characters")
    mesh = api.create_skeletal_mesh_asset("Hero", skeleton_id=skeleton.asset_id)
    profile = api.create_geometry_optimization_profile(
        "Hero LOD Pipeline", preset="character_mobile", source_asset_ids=[mesh.asset_id],
    )
    values = api.assign_geometry_optimization_profile(mesh.asset_id, profile.asset_id)
    assert values["optimization_profile_id"] == profile.asset_id
    assert api.plan_geometry_optimization(profile.asset_id)["fully_local"] is True
    assert not [issue for issue in api.validate_geometry_optimization(profile.asset_id) if issue["severity"] == "error"]
    artifact = api.cook_geometry_optimization(profile.asset_id, platform="windows", quality="high")
    payload = json.loads(artifact.path.read_bytes())
    assert payload["schema"] == "tech_connector.geometry_optimization_plan.v1"
    assert payload["platform"] == "windows"
    assert payload["components"]["skinning"]["preserve_weights"] is True
    manifest = api.cook([profile.asset_id], platform="windows", quality="high")
    assert manifest.asset_ids == (profile.asset_id,)
    assert api.database.derived(profile.asset_id, "geometry_optimization_plan:windows:high") is not None
    assert "geometry_optimization" in api.capability_contract()["geometry_optimization_operations"][0]


def test_profile_is_first_class_asset_type() -> None:
    descriptor = builtin_asset_type_registry().require("tc.geometry_optimization_profile")
    assert descriptor.creatable is True
    assert descriptor.standard_editor_name == "Geometry Optimization Editor"
    assert descriptor.python_api_namespace == "editor.geometry_optimization"


def test_dedicated_editor_exposes_pipeline_and_backend_readiness(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    api = TCEditorAPI(tmp_path)
    profile = api.create_geometry_optimization_profile("HLOD", preset="prop_hlod")
    editor = DedicatedAssetEditor(tmp_path, api.database)
    assert editor.open_asset(profile.asset_id)
    assert "Pipeline" in [editor.pages.tabText(index) for index in range(editor.pages.count())]
    widgets = [widget for _key, widget in editor._specialized_widgets if isinstance(widget, GeometryOptimizationEditorWidget)]
    assert len(widgets) == 1
    assert "awaiting a local backend" in widgets[0].summary.text()
