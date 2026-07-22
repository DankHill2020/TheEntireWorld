"""Tests for the Customization Panel settings and swappable modular providers."""

import json
import os
from pathlib import Path
import pytest

from tech_connector.services.settings_service import load_settings, save_settings, SETTINGS_PATH
from tech_connector.services.ollama_service import model_for_role, semantic_intent_model, code_model_for_profile
from tech_connector.services.github_ingest_service import parse_github_repo_reference, ingest_github_repo
from tech_connector.services.code_intelligence_service import build_code_intelligence_packet
from tech_connector.services.cognitive_routing_service import upgrade_route_decision
from tech_connector.services.prompt_route_service import PromptRouteDecision
from tech_connector.services.goal_gap_planning_service import build_goal_gap_plan
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
