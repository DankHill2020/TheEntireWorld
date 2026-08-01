"""Tests for the Customization Panel settings and swappable modular providers."""

import json
import os
import sys
from pathlib import Path
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.services.ollama_service import model_for_role, semantic_intent_model, code_model_for_profile
from tech_connector.services.github_ingest_service import parse_github_repo_reference, ingest_github_repo
from tech_connector.services.code_intelligence_service import build_code_intelligence_packet
from tech_connector.services.reasoning.cognitive_routing_service import upgrade_route_decision
from tech_connector.services.prompt.prompt_route_service import PromptRouteDecision
from tech_connector.services.reasoning.goal_gap_planning_service import build_goal_gap_plan
from tech_connector.services.version_control_service import detect_version_controls_for_path, VersionControlProvider
from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
from tech_connector.bridges.maya.maya_bridge import MayaBridge
from tech_connector.models.constants import DCC_TOOL_PACKAGE_NAMES


@pytest.fixture
def temp_settings():
    """Backup settings before test, restore after."""
    backup = None
    if SETTINGS_PATH.exists():
        try:
            backup = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    yield
    if backup is not None:
        try:
            SETTINGS_PATH.write_text(json.dumps(backup, indent=2), encoding="utf-8")
        except Exception:
            pass


def test_customization_settings_defaults(temp_settings):
    """Verify that settings load defaults for the new keys."""
    settings = load_settings()
    assert settings["github_ingest_provider_module"] == "default"
    assert settings["code_intel_provider_module"] == "default"
    assert settings["cognitive_routing_provider_module"] == "default"
    assert settings["planning_provider_module"] == "default"
    assert settings["vcs_provider_module"] == "default"
    assert isinstance(settings["custom_dcc_packages"], list)
    assert isinstance(settings["custom_dcc_adapters"], dict)
    assert isinstance(settings["custom_dcc_bridges"], dict)
    assert isinstance(settings["custom_provider_function_bindings"], dict)


def test_swappable_models(temp_settings):
    """Verify that model resolution respects settings and custom model mappings."""
    # Test customMappings overrides
    settings = load_settings()
    settings["custom_model_mappings"] = {"general": "custom-gen-model:latest", "custom_role": "custom-role-model"}
    settings["semantic_intent_model"] = "custom-intent:1.5b"
    save_settings(settings)

    # Check mappings lookup
    assert model_for_role("general") == "custom-gen-model:latest"
    assert model_for_role("custom_role") == "custom-role-model"
    
    # Check fallback / specific model overrides
    assert model_for_role("intent") == "custom-intent:1.5b"
    assert semantic_intent_model() == "custom-intent:1.5b"


def test_visual_media_model_role_is_not_code_model(temp_settings):
    settings = load_settings()
    settings["visual_media_model"] = "llava:latest"
    settings["fast_code_model"] = "qwen2.5-coder:7b"
    save_settings(settings)

    assert model_for_role("visual_media") == "llava:latest"
    assert model_for_role("image") == "llava:latest"
    assert model_for_role("video") == "llava:latest"
    assert model_for_role("camera") == "llava:latest"


def test_customization_panel_explains_advanced_mapping_fields():
    package_root = Path(__file__).resolve().parents[2]
    source = (package_root / "ui" / "customization_panel.py").read_text(encoding="utf-8")

    assert "def show_customization_help" in source
    assert '"visual_media": "llava:latest"' in source
    assert "backend_modules" in source
    assert "Function hookups: Tech Connector needs -> your module provides" in source
    assert "Detect functions" in source
    assert "custom_provider_function_bindings" in source
    assert "bound to" in source
    assert "Runs cleanup or optimization after assets are imported" in source
    assert "Decides what kind of request the user made" in source
    assert "Turns a request into a capability-aware plan" in source
    assert "Generates the conversational answer" in source
    assert "studio.providers.github_ingest" in source
    assert "dcc_bridges" in source
    assert "studio.bridges.UnrealBridge" in source
    assert "How to" in source
    assert "parse_github_repo_reference(repo_ref: str)" in source
    assert "github_api_repo_url(repo_ref: str)" in source
    assert "download_and_extract_repo(repo_name: str" in source
    assert "ingest_github_repo(repo_ref, target_dir, progress_cb=None)" in source
    assert "optimize_assets(local_path: str | Path)" in source
    assert "build_code_intelligence_packet(objective: str" in source
    assert "upgrade_route_decision(prompt: str" in source
    assert "build_goal_gap_plan(prompt: str" in source
    assert "generate_chat_response(text: str, history: list[dict], append_chunk" in source
    assert "query(request, context)" in source
    assert "execute_python(...)" in source


def test_customization_panel_provider_validation_checks_required_callables(tmp_path, monkeypatch):
    module_path = tmp_path / "custom_provider_missing_contract.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("custom_provider_missing_contract", None)

    from tech_connector.ui.customization_panel import CustomizationPanel

    errors = []
    successes = []
    CustomizationPanel._validate_provider_contract(
        None,
        errors,
        successes,
        "Planner Module",
        "custom_provider_missing_contract",
        "planning_module",
        {"build_goal_gap_plan": "make_plan"},
    )

    assert any("port `build_goal_gap_plan` is bound to `make_plan`" in error for error in errors)
    assert any("Falling back to the default Tech Connector provider" in error for error in errors)
    assert successes == []


def test_customization_panel_provider_validation_reports_passed_callables(tmp_path, monkeypatch):
    module_path = tmp_path / "custom_planner_provider.py"
    module_path.write_text(
        "def make_plan(prompt, decision=None):\n"
        "    return {'ok': True, 'prompt': prompt}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("custom_planner_provider", None)

    from tech_connector.ui.customization_panel import CustomizationPanel

    errors = []
    successes = []
    CustomizationPanel._validate_provider_contract(
        None,
        errors,
        successes,
        "Planner Module",
        "custom_planner_provider",
        "planning_module",
        {"build_goal_gap_plan": "make_plan"},
    )

    assert errors == []
    assert any("`build_goal_gap_plan` -> `make_plan" in item for item in successes)


def test_custom_provider_function_binding_resolution():
    from tech_connector.services.modular_provider_utils import resolve_custom_provider_binding

    settings = {
        "custom_provider_function_bindings": {
            "planning_module": {"build_goal_gap_plan": "make_plan"}
        }
    }

    assert (
        resolve_custom_provider_binding(
            "planning_module",
            "custom_planner_provider",
            "build_goal_gap_plan",
            settings,
        )
        == "custom_planner_provider.make_plan"
    )


def test_fallback_on_invalid_custom_provider(temp_settings):
    """Verify that if custom provider is missing, it falls back to defaults."""
    settings = load_settings()
    settings["github_ingest_provider_module"] = "nonexistent_module_path"
    settings["code_intel_provider_module"] = "nonexistent_module_path"
    settings["cognitive_routing_provider_module"] = "nonexistent_module_path"
    settings["planning_provider_module"] = "nonexistent_module_path"
    save_settings(settings)

    # Ingestion fallback
    # Should not crash, should resolve via default implementation
    ref = parse_github_repo_reference("https://github.com/owner/repo")
    assert ref.owner == "owner"
    assert ref.repo == "repo"

    # Code Intel fallback
    packet = build_code_intelligence_packet("find my functions", limit=2)
    assert isinstance(packet, dict)

    # Cognitive router fallback
    baseline = PromptRouteDecision(route="chat", confidence=0.5, provider="ollama", host="standalone")
    decision = upgrade_route_decision("help me write a script", baseline)
    assert isinstance(decision, PromptRouteDecision)

    # Planning fallback
    plan = build_goal_gap_plan("build a character selector")
    assert isinstance(plan, dict)


def test_custom_dcc_bridge_delegate(temp_settings, tmp_path):
    """Verify that custom bridge delegate intercepts bridge method calls."""
    # Write a mock bridge delegate module to a temp folder
    mock_module_content = """
class MockUnrealBridge:
    def execute_python(self, source, timeout=30.0, reset_globals=False):
        return {"ok": True, "output": "intercepted_by_mock", "result": None}

    def health_check(self, timeout=5.0):
        return {"status": "healthy", "provider": "mock"}
"""
    # Create the python file in current directory to import it
    mock_mod_path = Path("mock_unreal_bridge_delegate.py")
    mock_mod_path.write_text(mock_module_content, encoding="utf-8")

    try:
        settings = load_settings()
        settings["custom_dcc_bridges"] = {"unreal": "mock_unreal_bridge_delegate.MockUnrealBridge"}
        save_settings(settings)

        # Instantiate bridge
        bridge = UnrealBridge()
        # Verify it uses the delegate
        assert bridge._custom_delegate is not None
        res = bridge.execute_python("print('hello')")
        assert res["output"] == "intercepted_by_mock"
    finally:
        if mock_mod_path.exists():
            mock_mod_path.unlink()
