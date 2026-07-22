"""Integration package registry for user-added tools and applications."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tech_connector.models.constants import APP_ROOT
from tech_connector.services.diagnostic_service import log_backend_event


INTEGRATION_PACKAGE_DIR = APP_ROOT / "integration_packages"

PACKAGE_TYPES = {
    "dcc_engine": {
        "label": "DCC / Engine",
        "examples": ["Houdini", "Nuke", "3ds Max", "Godot", "Unity"],
        "group": "DCC",
        "connector_types": ["local_process", "http_bridge", "python_bridge", "mcp_server"],
        "default_capabilities": [
            "launch_or_attach",
            "inspect_scene_or_project",
            "run_script_or_command",
            "read_selection",
            "write_safe_changes",
        ],
    },
    "communication": {
        "label": "Communication",
        "examples": ["Microsoft Teams", "Discord", "Slack"],
        "group": "Messaging",
        "connector_types": ["oauth_api", "bot_token", "webhook", "mcp_server"],
        "default_capabilities": [
            "authenticate",
            "list_channels",
            "read_messages",
            "send_message_with_approval",
            "summarize_thread",
        ],
    },
    "design_planning": {
        "label": "Design / Planning",
        "examples": ["Miro", "Figma", "FigJam", "Jira", "Linear", "Notion"],
        "group": "Ops",
        "connector_types": ["oauth_api", "rest_api", "mcp_server"],
        "default_capabilities": [
            "authenticate",
            "read_board_or_project",
            "create_item_with_approval",
            "update_item_with_approval",
            "link_source_context",
        ],
    },
    "storage_knowledge": {
        "label": "Storage / Knowledge",
        "examples": ["SharePoint", "Dropbox", "Confluence"],
        "group": "Ops",
        "connector_types": ["oauth_api", "rest_api", "mcp_server"],
        "default_capabilities": [
            "authenticate",
            "browse_resources",
            "read_documents",
            "write_with_approval",
            "index_approved_content",
        ],
    },
    "devops": {
        "label": "Build / DevOps",
        "examples": ["GitLab", "Azure DevOps", "Jenkins"],
        "group": "Ops",
        "connector_types": ["token_api", "rest_api", "cli", "mcp_server"],
        "default_capabilities": [
            "authenticate",
            "read_status",
            "trigger_job_with_approval",
            "collect_logs",
            "link_vcs_context",
        ],
    },
    "custom": {
        "label": "Custom App / Internal Tool",
        "examples": ["HTTP API", "local executable", "MCP server", "bridge plugin"],
        "group": "Ops",
        "connector_types": ["http_api", "local_process", "cli", "mcp_server"],
        "default_capabilities": [
            "describe_interface",
            "authenticate_if_needed",
            "read_state",
            "execute_with_approval",
            "validate_smoke_check",
        ],
    },
}

LIFECYCLE_STATES = [
    "discovered",
    "configured",
    "connected",
    "indexed",
    "validated",
    "trusted",
]


def slugify_package_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name or "").strip("._").lower()
    return slug[:80] or "integration"


def package_root(base_dir: Path | None = None) -> Path:
    return base_dir or INTEGRATION_PACKAGE_DIR


def build_capability_records(package_type: str) -> list[dict[str, Any]]:
    spec = PACKAGE_TYPES.get(package_type, PACKAGE_TYPES["custom"])
    return [
        {
            "id": slugify_package_name(capability),
            "name": capability.replace("_", " ").title(),
            "status": "discovered",
            "confidence": 0.2,
            "requires_user_approval": True,
            "notes": "Scaffolded by Tech Connector. Validate against official docs or a live connector before execution.",
        }
        for capability in spec["default_capabilities"]
    ]


def build_bridge_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    spec = PACKAGE_TYPES.get(manifest.get("type"), PACKAGE_TYPES["custom"])
    package_id = manifest.get("id") or slugify_package_name(manifest.get("name", "integration"))
    return {
        "schema": "ai_studio.integration_bridge.v1",
        "package_id": package_id,
        "package_name": manifest.get("name", package_id),
        "group": spec.get("group", "Ops"),
        "supports_bridge_setup": True,
        "connector_types": list(spec.get("connector_types", [])),
        "load_state": "scaffolded",
        "entrypoints": {
            "setup": "bridge/README.md",
            "adapter": "",
            "mcp_server": "",
            "health_check": "",
        },
        "capability_states": {
            "known": True,
            "connectable": False,
            "connected": False,
            "validated": False,
            "trusted": False,
        },
        "required_user_steps": [
            "Approve official docs/API research or provide local connector documentation.",
            "Configure credentials using Tech Connector settings or provider-native auth.",
            "Run a read-only health check before enabling write actions.",
            "Validate one smoke prompt before marking the package trusted.",
        ],
        "last_error": "",
    }


def build_package_manifest(
    name: str,
    package_type: str,
    description: str = "",
    source_url: str = "",
    created_by: str = "user",
) -> dict[str, Any]:
    package_type = package_type if package_type in PACKAGE_TYPES else "custom"
    slug = slugify_package_name(name)
    return {
        "schema": "ai_studio.integration_package.v1",
        "id": slug,
        "name": name.strip() or slug,
        "type": package_type,
        "type_label": PACKAGE_TYPES[package_type]["label"],
        "description": description.strip(),
        "source_url": source_url.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "created_by": created_by,
        "lifecycle": {
            "discovered": True,
            "configured": False,
            "connected": False,
            "indexed": False,
            "validated": False,
            "trusted": False,
        },
        "capabilities": build_capability_records(package_type),
        "auth": {
            "status": "unknown",
            "requirements": [],
            "secrets_storage": "Tech Connector settings or provider-native credential store",
        },
        "connection": {
            "status": "not_configured",
            "connector": "",
            "endpoint": "",
            "supports_bridge_setup": True,
            "connector_types": list(PACKAGE_TYPES[package_type].get("connector_types", [])),
            "notes": "",
        },
        "knowledge": {
            "status": "pending_user_approval",
            "official_docs": [],
            "third_party": [],
            "local_notes": [],
        },
        "safety": {
            "requires_plan": True,
            "requires_approval_before_write": True,
            "allow_live_actions": False,
            "notes": [
                "Search local knowledge first.",
                "If the workflow is unknown, ask before searching external sources.",
                "Do not claim support until validation passes.",
            ],
        },
        "validation": {
            "status": "not_run",
            "smoke_prompts": [],
            "last_result": "",
        },
    }


def create_integration_package(
    name: str,
    package_type: str,
    description: str = "",
    source_url: str = "",
    base_dir: Path | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    manifest = build_package_manifest(name, package_type, description, source_url)
    root = package_root(base_dir)
    package_dir = root / manifest["id"]
    if package_dir.exists():
        log_backend_event(
            "integration_package",
            "Integration package already exists",
            details={"name": name, "path": str(package_dir)},
        )
        return False, f"Integration package already exists: {package_dir}", {"path": str(package_dir)}

    for subdir in ("knowledge", "capabilities", "bridge", "prompts", "tests"):
        (package_dir / subdir).mkdir(parents=True, exist_ok=True)

    (package_dir / "package.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (package_dir / "knowledge" / "README.md").write_text(
        "# Knowledge\n\nStore approved official docs, third-party research pointers, and local notes here.\n",
        encoding="utf-8",
    )
    (package_dir / "prompts" / "routing_rules.md").write_text(
        "# Routing Rules\n\n- Use this package only for prompts that explicitly mention this integration or its approved aliases.\n- Ask for approval before external research or live write actions.\n",
        encoding="utf-8",
    )
    (package_dir / "prompts" / "safety_rules.md").write_text(
        "# Safety Rules\n\n- Plan before mutation.\n- Prefer read-only inspection before writes.\n- Require user approval before sending messages, changing boards, modifying assets, or triggering jobs.\n",
        encoding="utf-8",
    )
    (package_dir / "bridge" / "README.md").write_text(
        "# Bridge\n\nDescribe connector setup, local app bridge requirements, API endpoints, or MCP tools here.\n",
        encoding="utf-8",
    )
    bridge_manifest = build_bridge_manifest(manifest)
    (package_dir / "bridge" / "bridge_manifest.json").write_text(
        json.dumps(bridge_manifest, indent=2),
        encoding="utf-8",
    )
    (package_dir / "bridge" / "adapter_stub.py").write_text(
        '"""Adapter stub for this integration package.\n\n'
        'Keep live actions disabled until this package is configured, connected,\n'
        'validated by smoke prompts, and approved by the user.\n'
        '"""\n\n'
        "def health_check():\n"
        "    return {'ok': False, 'message': 'Bridge adapter is not configured yet.'}\n",
        encoding="utf-8",
    )
    (package_dir / "tests" / "smoke_prompts.json").write_text("[]\n", encoding="utf-8")

    payload = dict(manifest)
    payload["path"] = str(package_dir)
    payload["bridge_manifest"] = bridge_manifest
    log_backend_event(
        "integration_package",
        "Created integration package scaffold",
        details={
            "name": manifest.get("name"),
            "type": manifest.get("type"),
            "path": str(package_dir),
            "connector_types": bridge_manifest.get("connector_types", []),
        },
    )
    return True, f"Created integration package: {package_dir}", payload


def ensure_integration_bridge_manifests(base_dir: Path | None = None) -> dict[str, Any]:
    root = package_root(base_dir)
    created = []
    skipped = []
    if not root.exists():
        return {"created": created, "skipped": skipped, "total": 0}
    for package_json in sorted(root.glob("*/package.json")):
        try:
            manifest = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            skipped.append(str(package_json.parent))
            continue
        bridge_dir = package_json.parent / "bridge"
        bridge_path = bridge_dir / "bridge_manifest.json"
        if bridge_path.exists():
            skipped.append(str(package_json.parent))
            continue
        bridge_dir.mkdir(parents=True, exist_ok=True)
        bridge_manifest = build_bridge_manifest(manifest)
        bridge_path.write_text(json.dumps(bridge_manifest, indent=2), encoding="utf-8")
        adapter_stub = bridge_dir / "adapter_stub.py"
        if not adapter_stub.exists():
            adapter_stub.write_text(
                '"""Adapter stub for this integration package."""\n\n'
                "def health_check():\n"
                "    return {'ok': False, 'message': 'Bridge adapter is not configured yet.'}\n",
                encoding="utf-8",
            )
        created.append(str(package_json.parent))
    if created:
        log_backend_event(
            "integration_package",
            "Backfilled integration bridge manifests",
            details={"created": created, "skipped_count": len(skipped)},
        )
    return {"created": created, "skipped": skipped, "total": len(created) + len(skipped)}


def load_integration_packages(base_dir: Path | None = None) -> list[dict[str, Any]]:
    root = package_root(base_dir)
    packages = []
    if not root.exists():
        return packages
    for package_json in sorted(root.glob("*/package.json")):
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        data["path"] = str(package_json.parent)
        bridge_manifest = package_json.parent / "bridge" / "bridge_manifest.json"
        if bridge_manifest.exists():
            try:
                data["bridge_manifest"] = json.loads(bridge_manifest.read_text(encoding="utf-8"))
            except Exception:
                data["bridge_manifest"] = {"last_error": "Could not read bridge manifest."}
        packages.append(data)
    return packages


def summarize_integration_packages(base_dir: Path | None = None) -> dict[str, Any]:
    packages = load_integration_packages(base_dir)
    connected = sum(1 for pkg in packages if pkg.get("lifecycle", {}).get("connected"))
    validated = sum(1 for pkg in packages if pkg.get("lifecycle", {}).get("validated"))
    trusted = sum(1 for pkg in packages if pkg.get("lifecycle", {}).get("trusted"))
    return {
        "total": len(packages),
        "connected": connected,
        "validated": validated,
        "trusted": trusted,
        "packages": packages,
    }


def bridge_setup_summary(base_dir: Path | None = None) -> dict[str, Any]:
    packages = load_integration_packages(base_dir)
    supported = []
    missing = []
    for package in packages:
        bridge = package.get("bridge_manifest") or {}
        if bridge.get("supports_bridge_setup"):
            supported.append(package)
        else:
            missing.append(package)
    return {
        "total": len(packages),
        "supported": len(supported),
        "missing": len(missing),
        "packages": packages,
    }


def format_integration_plan_card(manifest: dict[str, Any], path: str = "") -> str:
    capabilities = manifest.get("capabilities") or []
    cap_lines = "\n".join(f"- {cap.get('name', cap.get('id', 'Capability'))}: {cap.get('status', 'discovered')}" for cap in capabilities[:6])
    return (
        "**Integration Package Plan**\n\n"
        f"Package: **{manifest.get('name', '')}**\n\n"
        f"Type: {manifest.get('type_label', manifest.get('type', 'Custom'))}\n\n"
        "Lifecycle after creation: discovered only. Configure, connect, index, validate, and trust remain pending until approved workflows prove them.\n\n"
        "**Scaffolded Capabilities**\n"
        f"{cap_lines or '- None'}\n\n"
        "**Created Files**\n"
        f"- `{path or manifest.get('path', '')}`\n\n"
        "Next step: approve official docs/API research or configure a connector before live actions are enabled."
    )
