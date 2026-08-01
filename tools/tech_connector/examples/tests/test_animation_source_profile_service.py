from tech_connector.services.unreal.animation_source_profile_service import (
    match_animation_source_profile,
)


def _profile():
    return {
        "id": "test_profile",
        "required_bones": ["hip", "spine", "head"],
        "parent_constraints": [["hip", "spine"], ["spine", "head"]],
        "hik_mapping": {"Hips": {"slot": 1, "bone": "hip"}},
    }


def test_profile_requires_names_and_parent_topology():
    hierarchy = {
        "joints": [
            {"name": "hip", "parent": ""},
            {"name": "spine", "parent": "|source:hip"},
            {"name": "head", "parent": "|source:hip|source:spine"},
        ]
    }
    result = match_animation_source_profile(hierarchy, [_profile()])
    assert result["ok"]
    assert result["profile_id"] == "test_profile"
    assert result["source_mapping"]["Hips"]["bone"] == "hip"


def test_profile_rejects_same_names_with_wrong_topology():
    hierarchy = {
        "joints": [
            {"name": "hip", "parent": ""},
            {"name": "spine", "parent": ""},
            {"name": "head", "parent": "|source:spine"},
        ]
    }
    result = match_animation_source_profile(hierarchy, [_profile()])
    assert not result["ok"]
    assert result["requires_knowledge"]
    assert ["hip", "spine"] in result["attempts"][0]["failed_parent_constraints"]
