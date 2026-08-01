from tech_connector.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.services.tutorial_mode_service import (
    classify_3d_task,
    detect_target_dcc,
    get_educational_resources_for_task,
    has_tutorial_directive,
    strip_tutorial_directive,
    tutorial_service,
)


def test_tutorial_directive_is_explicit_and_stripped_from_task_name():
    assert has_tutorial_directive("/tutorial how do I fix UV stretching in Substance Painter?")
    assert not has_tutorial_directive("how do I fix UV stretching in Substance Painter?")
    assert strip_tutorial_directive("/tutorial how do I fix UV stretching?") == "how do I fix UV stretching?"


def test_tutorial_classifies_broad_3d_topics_and_detects_dcc():
    assert classify_3d_task("how do I fix UV stretching in Substance Painter?") == "uv_texturing"
    assert classify_3d_task("teach me to build a procedural scatter tool in Houdini") == "procedural"
    assert classify_3d_task("teach me camera lens FOV aperture and matchmove settings") == "camera_settings"
    assert detect_target_dcc("create a geometry nodes setup in Blender") == "Blender"


def test_resources_include_app_and_topic_links():
    resources = get_educational_resources_for_task("/tutorial fix UV stretching in Substance Painter")
    titles = {resource.title for resource in resources}

    assert "Substance 3D Painter Documentation" in titles
    assert "Substance 3D Painter Baking" in titles


def test_camera_tutorial_has_camera_steps_and_resources():
    plan = tutorial_service.build_educational_walkthrough(
        "/tutorial teach me camera lens FOV aperture focus distance and matchmove settings in Unreal"
    )
    resources = get_educational_resources_for_task(
        "/tutorial teach me camera lens FOV aperture focus distance and matchmove settings in Unreal"
    )
    titles = {resource.title for resource in resources}

    assert plan.target_dcc == "Unreal Engine 5"
    assert plan.steps[0].title == "Lock Output and Framing"
    assert any("focal length" in step.educational_concept.lower() for step in plan.steps)
    assert "Unreal Engine Cameras Documentation" in titles
    assert "Confluence Camera and Matchmove Checklist" in titles


def test_engine_only_uses_tutorial_mode_when_selected():
    tutorial_service.set_mode("automation")
    engine = RequestEngine()

    default_result = engine._fast_tutorial_mode_request_v2(
        RequestContext(text="how do I set up a 3-point light rig in Maya?")
    )
    tutorial_result = engine._fast_tutorial_mode_request_v2(
        RequestContext(text="/tutorial how do I set up a 3-point light rig in Maya?")
    )

    assert default_result is None
    assert tutorial_result is not None
    assert tutorial_result.metadata["result_type"] == "tutorial_walkthrough"
    assert "Optional Learning Resources" in tutorial_result.text
    assert tutorial_result.metadata["walkthrough_plan"]["target_dcc"] == "Autodesk Maya"
