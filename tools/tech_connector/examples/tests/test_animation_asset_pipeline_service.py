from tech_connector.services.unreal.animation_asset_pipeline_service import (
    resolve_retarget_target_selection,
    selected_target_mesh,
)


def test_resolves_target_only_for_retarget_selection_followup():
    prior = {"result_type": "unreal_animation_retarget_target_selection"}
    value = resolve_retarget_target_selection(
        "ignored",
        prior,
        {"values": {"target_skeleton": "/Game/Characters/SK_Target"}},
    )
    assert value == "/Game/Characters/SK_Target"
    assert not resolve_retarget_target_selection("x", {"result_type": "other"}, {})


def test_selected_target_mesh_prefers_simple_or_nogeo():
    options = {
        "options": [
            {
                "skeleton": "/Game/Characters/SK_Target",
                "skeletal_meshes": [
                    "/Game/Characters/SKM_Target_Full",
                    "/Game/Characters/SKM_Target_NoGeo",
                ],
            }
        ]
    }
    assert selected_target_mesh(options, "/Game/Characters/SK_Target").endswith("NoGeo")
