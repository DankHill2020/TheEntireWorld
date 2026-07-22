"""Settings persistence and component installation."""

import json
import os
import shutil
from pathlib import Path

from tech_connector.models.constants import (
    APP_DIR,
    APP_ROOT,
    DEFAULT_CONFIGS,
    DEFAULT_MODEL,
    KNOWLEDGE_DIR,
    SETTINGS_PATH,
)


_RELOCATABLE_SETTINGS = {"config", "model_cache_dir", "db_path", "index_cache_dir"}


def _relocate_legacy_app_path(value: object) -> object:
    """Map saved paths from the former package directory onto this checkout."""
    if not isinstance(value, str) or not value.strip():
        return value
    normalized = value.replace("\\", "/")
    marker = "/the_entire_world_ai_studio"
    if marker not in normalized.lower():
        return value
    marker_index = normalized.lower().index(marker)
    suffix = normalized[marker_index + len(marker) :].lstrip("/")
    return str(APP_ROOT / Path(suffix)) if suffix else str(APP_ROOT)


def _relocate_saved_settings(data: dict) -> dict:
    relocated = dict(data)
    for key in _RELOCATABLE_SETTINGS:
        if key in relocated:
            relocated[key] = _relocate_legacy_app_path(relocated[key])
    extra_dirs = relocated.get("extra_dirs")
    if isinstance(extra_dirs, list):
        relocated["extra_dirs"] = [
            _relocate_legacy_app_path(value) for value in extra_dirs
        ]
    return relocated


def best_config() -> str:
    for p in DEFAULT_CONFIGS:
        if Path(p).exists():
            return p
    return DEFAULT_CONFIGS[0]


def load_settings() -> dict:
    defaults = {
        "extra_dirs": [],
        "first_run_complete": False,
        "model": DEFAULT_MODEL,
        "config": best_config(),
        "auto_index_on_first_run": True,
        "enable_live_sources": False,
        "research_project_snapshot": True,
        "research_unreal_capabilities": True,
        "research_official_docs": True,
        "research_best_practices": False,
        "remote_mobile_host": "0.0.0.0",
        "remote_mobile_port": 8765,
        "research_web_techniques": False,
        "research_github_examples": False,
        "research_compare_architectures": True,
        "research_generate_plan": True,
        "research_auto_implement": False,
        "allow_unreal_cpp_bridge": False,
        "ai_work_memory_enabled": True,
        "ai_work_memory_include_locked": True,
        "ai_work_memory_max_context_chars": 6000,
        "expert_memory_packet_enabled": True,
        "expert_memory_packet_max_chars": 3500,
        "expert_memory_max_experts": 4,
        "expert_memory_max_playbooks": 2,
        "expert_memory_max_work_items": 4,
        "active_project": "",
        "unreal_uproject_path": "",
        "recent_projects": [],
        "model_source_mode": "auto_with_local_fallback",
        "cloud_model_unavailable": False,
        "show_reasoning_summary": True,
        "show_activity_details": False,
        "multi_stage_reasoning_enabled": True,
        "multi_stage_reasoning_mode": "deterministic",
        "experts.default_mode": "observe",
        "experts.maya.node_editor.mode": "advise",
        "experts.maya.hypershade.mode": "observe",
        "experts.maya.rigging.mode": "advise",
        "experts.unreal.blueprint_graph.mode": "advise",
        "experts.unreal.control_rig.mode": "observe",
        "experts.pipeline.composition.mode": "advise",
        "experts.python.ui_integration.mode": "advise",
        "experts.python.testing_validation.mode": "advise",
        "experts.python.async_responsiveness.mode": "advise",
        "experts.python.index_search.mode": "advise",
        "experts.python.patch_application.mode": "advise",
        "simple_chat_responses": False,
        "prioritize_open_file_context": False,
        "dcc_bridge_setup_seen": [],
        "auto_checkout_on_change": True,
        "external_tools_dir": "",
        "search_github_tools_when_composing": False,
        "tech_connector_require_login": True,
        "tech_connector_allow_offline_community": False,
        "tech_connector_account_email": "",
        "tech_connector_license_token": "",
        "github_username": "",
        "github_token": "",
        "p4_port": "",
        "p4_user": "",
        "p4_client": "",
        "p4_passwd": "",
        "notify_slack_enabled": False,
        "slack_webhook_url": "",
        "slack_bot_token": "",
        "slack_default_channel": "",
        "slack_channels": [],
        "slack_users": [],
        "notify_discord_enabled": False,
        "discord_webhook_url": "",
        "discord_username": "Tech Connector",
        "discord_bot_token": "",
        "discord_guild_id": "",
        "discord_default_channel": "",
        "discord_channels": [],
        "discord_users": [],
        "notify_email_enabled": False,
        "email_smtp_host": "smtp.gmail.com",
        "email_smtp_port": 587,
        "email_username": "",
        "email_password": "",
        "email_from": "",
        "email_to": "",
        "email_use_tls": True,
        "email_use_ssl": False,
        "atlassian_site_url": "",
        "atlassian_email": "",
        "atlassian_api_token": "",
        "jira_project_key": "",
        "jira_issue_type": "Task",
        "jira_projects": [],
        "confluence_space_id": "",
        "confluence_space_key": "",
        "confluence_parent_id": "",
        "confluence_spaces": [],
        "atlassian_users": [],
        "embedding_model": "all-MiniLM-L6-v2",
        "model_cache_dir": str(APP_ROOT / "data" / "model_cache"),
        "db_path": str(APP_ROOT / "data" / "ai_intel.db"),
        "daemon": {
            "auto_start": False,
            "poll_interval_seconds": 5
        },
        "ui": {
            "show_health_status": True,
            "enable_unreal_context_toggle": True
        },
        "router_embed": "nomic-embed-text",
        "router_local_code": "qwen2.5-coder:14b",
        "router_local_plan": "qwen3:14b",
        "router_local_deep": "qwen3:14b",
        "router_fast_llm_model": "qwen3:14b",
        "ollama_keep_alive": "10m",
        "ollama_num_thread": max(1, min(8, (os.cpu_count() or 4) - 2)),
        "ollama_num_gpu": "",
        "ollama_temperature": 0.2,
        "llm_planning_mode": "fast_first",
        "deep_route_scope": "engine_complex_only",
        "deep_code_complexity_threshold": 7,
        "allow_30b_deep_route": False,
        "semantic_intent_model": "qwen2.5:1.5b",
        "fast_general_model": "qwen3:14b",
        "fast_code_model": "qwen2.5-coder:14b",
        "embedding_model": "nomic-embed-text:latest",
        "fallback_general_model": "qwen2.5-coder:latest",
        "fallback_semantic_intent_model": "qwen2.5:1.5b",
        "fallback_code_model": "qwen2.5-coder:latest",
        "custom_model_mappings": {},
        "github_ingest_provider_module": "default",
        "code_intel_provider_module": "default",
        "cognitive_routing_provider_module": "default",
        "planning_provider_module": "default",
        "vcs_provider_module": "default",
        "custom_dcc_packages": [],
        "custom_dcc_adapters": {},
        "custom_dcc_bridges": {},
        "github_ingest_provider_type": "default",
        "mod_tech_labs_api_key": "",
        "mod_tech_labs_workflow_id": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "gemini_api_key": "",
        "cloud_provider_model": "gpt-4o",
        "asset_optimizer_provider_module": "default",
        "use_websocket_bridge": False,
        "chatbot_provider_module": "default",
    }
    if SETTINGS_PATH.exists():
        try:
            data = _relocate_saved_settings(
                json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            )
            cfg_path = data.get("config")
            if cfg_path and not Path(cfg_path).exists():
                data["config"] = best_config()
            merged = dict(defaults)
            merged.update(data)
            if (
                not bool(merged.get("allow_30b_deep_route", False))
                and str(merged.get("router_local_deep", "")).strip() == "qwen3:30b"
            ):
                merged["router_local_deep"] = "qwen3:14b"
            return merged
        except Exception:
            pass
    return defaults


def save_settings(data: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def install_components_to_tools() -> None:
    """Ensure the canonical in-package knowledge component directory exists."""
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def update_mcp_config() -> str:
    import stat

    cfg = APP_ROOT / "knowledge" / "mcp_unreal_maya_knowledge_config.json"
    if cfg.exists():
        try:
            shutil.copy2(cfg, Path(str(cfg) + ".bak"))
        except Exception:
            pass

    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            data = {"mcpServers": {}}
    else:
        data = {"mcpServers": {}}

    servers = data.setdefault("mcpServers", {})
    for managed_name in ("knowledge", "maya", "motionbuilder", "unreal", "unrealgenai"):
        servers.pop(managed_name, None)

    servers["knowledge"] = {
        "type": "stdio",
        "command": "python",
        "args": [str(APP_ROOT / "knowledge" / "knowledge_mcp_server_v2.py")],
    }
    motionbuilder_server = APP_ROOT / "bridges" / "motionbuilder" / "motionbuilder_mcp_server.py"
    if motionbuilder_server.exists():
        servers["motionbuilder"] = {
            "type": "stdio",
            "command": "python",
            "args": [str(motionbuilder_server)],
        }
    unreal_server = APP_ROOT / "bridges" / "unreal" / "unreal_mcp_server.py"
    if unreal_server.exists():
        servers["unreal"] = {
            "type": "stdio",
            "command": "python",
            "args": [str(unreal_server)],
        }
    maya_candidates = [
        APP_ROOT / "maya_mcp_server_quiet.py",
        Path(r"C:\Desktop\UnrealGenAISupport\Content\Python\maya_mcp_server_quiet.py"),
    ]
    maya_server = next((path for path in maya_candidates if path.exists()), None)
    if maya_server:
        servers["maya"] = {
            "type": "stdio",
            "command": "python",
            "args": [str(maya_server)],
        }
    servers["ludus-mcp"] = {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.ludusengine.com/mcp"],
    }

    cfg.parent.mkdir(parents=True, exist_ok=True)
    if cfg.exists():
        try:
            os.chmod(cfg, stat.S_IWRITE)
        except Exception:
            pass
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return str(cfg)
