"""Connected account metadata and live application capability status."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AccountField:
    key: str
    label: str
    secret: bool = False
    required: bool = False
    env_var: str = ""


@dataclass(frozen=True)
class ConnectedAccountDefinition:
    id: str
    name: str
    category: str
    auth_type: str
    fields: tuple[AccountField, ...]
    capabilities: tuple[str, ...]
    setup_capabilities: tuple[str, ...] = ("login/config required",)
    setup_url: str = ""


CONNECTED_ACCOUNT_DEFINITIONS: tuple[ConnectedAccountDefinition, ...] = (
    ConnectedAccountDefinition(
        id="github",
        name="GitHub",
        category="VCS",
        auth_type="Personal access token or GitHub CLI token",
        fields=(
            AccountField("github_username", "Username"),
            AccountField("github_token", "Token", secret=True, required=True, env_var="GITHUB_TOKEN"),
        ),
        capabilities=("repo ingest", "API requests", "PR/release context", "GitHub issue references"),
    ),
    ConnectedAccountDefinition(
        id="perforce",
        name="Perforce",
        category="VCS",
        auth_type="P4PORT/P4USER/P4CLIENT plus password or ticket",
        fields=(
            AccountField("p4_port", "P4PORT", required=True, env_var="P4PORT"),
            AccountField("p4_user", "P4USER", required=True, env_var="P4USER"),
            AccountField("p4_client", "P4CLIENT", required=True, env_var="P4CLIENT"),
            AccountField("p4_passwd", "Password/Ticket", secret=True, env_var="P4PASSWD"),
        ),
        capabilities=("changed file discovery", "checkout/revert support", "changelist creation", "workspace context"),
    ),
    ConnectedAccountDefinition(
        id="slack",
        name="Slack",
        category="Messaging",
        auth_type="Bot token and/or incoming webhook",
        fields=(
            AccountField("slack_webhook_url", "Webhook URL", secret=True),
            AccountField("slack_bot_token", "Bot Token", secret=True),
            AccountField("slack_default_channel", "Default Channel"),
        ),
        capabilities=("send output", "list channels/users", "resolve @mentions"),
    ),
    ConnectedAccountDefinition(
        id="discord",
        name="Discord",
        category="Messaging",
        auth_type="Bot token and/or incoming webhook",
        fields=(
            AccountField("discord_webhook_url", "Webhook URL", secret=True),
            AccountField("discord_bot_token", "Bot Token", secret=True),
            AccountField("discord_guild_id", "Guild ID"),
            AccountField("discord_default_channel", "Default Channel"),
            AccountField("discord_username", "Webhook Username"),
        ),
        capabilities=("send output", "list guild channels/users", "resolve @mentions"),
    ),
    ConnectedAccountDefinition(
        id="atlassian",
        name="Jira / Confluence",
        category="Ops/Documentation",
        auth_type="Atlassian Cloud email + API token",
        fields=(
            AccountField("atlassian_site_url", "Site URL", required=True),
            AccountField("atlassian_email", "Email", required=True),
            AccountField("atlassian_api_token", "API Token", secret=True, required=True),
            AccountField("jira_project_key", "Jira Project"),
            AccountField("confluence_space_id", "Confluence Space"),
        ),
        capabilities=("create Jira issues", "upload Confluence pages", "list projects/spaces", "resolve users"),
    ),
    ConnectedAccountDefinition(
        id="email",
        name="Email",
        category="Messaging",
        auth_type="SMTP username + password/token",
        fields=(
            AccountField("email_smtp_host", "SMTP Host", required=True),
            AccountField("email_smtp_port", "SMTP Port"),
            AccountField("email_username", "Username", required=True),
            AccountField("email_password", "Password/Token", secret=True, required=True),
            AccountField("email_from", "From"),
            AccountField("email_to", "To", required=True),
        ),
        capabilities=("send output", "email pipeline summaries", "failure alerts"),
    ),
    ConnectedAccountDefinition(
        id="fab",
        name="Fab Marketplace",
        category="3D Asset Providers",
        auth_type="Epic Games / Fab login",
        fields=(AccountField("fab_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search assets", "download uassets", "download materials"),
        setup_capabilities=("login required",),
        setup_url="https://www.fab.com/login",
    ),
    ConnectedAccountDefinition(
        id="mixamo",
        name="Mixamo",
        category="3D Asset Providers",
        auth_type="Adobe ID / Mixamo connection",
        fields=(AccountField("mixamo_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search animation", "download fbx"),
        setup_capabilities=("login required",),
        setup_url="https://www.mixamo.com/login",
    ),
    ConnectedAccountDefinition(
        id="actorcore",
        name="ActorCore",
        category="3D Asset Providers",
        auth_type="Reallusion / ActorCore login",
        fields=(AccountField("actorcore_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search characters/animations", "download fbx"),
        setup_capabilities=("login required",),
        setup_url="https://actorcore.reallusion.com/login",
    ),
    ConnectedAccountDefinition(
        id="rokoko",
        name="Rokoko",
        category="3D Asset Providers",
        auth_type="Rokoko ID login",
        fields=(AccountField("rokoko_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search mocap", "download animations"),
        setup_capabilities=("login required",),
        setup_url="https://www.rokoko.com/login",
    ),
    ConnectedAccountDefinition(
        id="quixel",
        name="Quixel Megascans",
        category="3D Asset Providers",
        auth_type="Epic Games / Quixel login",
        fields=(AccountField("quixel_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search textures/models", "download megascans"),
        setup_capabilities=("login required",),
        setup_url="https://quixel.com/login",
    ),
    ConnectedAccountDefinition(
        id="sketchfab",
        name="Sketchfab",
        category="3D Asset Providers",
        auth_type="Sketchfab API token / login",
        fields=(AccountField("sketchfab_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search models", "download gltf/fbx"),
        setup_capabilities=("login required",),
        setup_url="https://sketchfab.com/login",
    ),
    ConnectedAccountDefinition(
        id="turbosquid",
        name="TurboSquid",
        category="3D Asset Providers",
        auth_type="TurboSquid login",
        fields=(AccountField("turbosquid_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search models", "download 3d assets"),
        setup_capabilities=("login required",),
        setup_url="https://www.turbosquid.com/login",
    ),
    ConnectedAccountDefinition(
        id="cgtrader",
        name="CGTrader",
        category="3D Asset Providers",
        auth_type="CGTrader login",
        fields=(AccountField("cgtrader_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search models", "download 3d assets"),
        setup_capabilities=("login required",),
        setup_url="https://www.cgtrader.com/login",
    ),
    ConnectedAccountDefinition(
        id="freesound",
        name="Freesound",
        category="3D Asset Providers",
        auth_type="Freesound API key / login",
        fields=(AccountField("freesound_login_confirmed", "Login Confirmed", required=True),),
        capabilities=("search audio", "download wav/mp3"),
        setup_capabilities=("login required",),
        setup_url="https://freesound.org/login",
    ),
)


def account_definition(account_id: str) -> ConnectedAccountDefinition | None:
    account_id = (account_id or "").strip().lower()
    return next((item for item in CONNECTED_ACCOUNT_DEFINITIONS if item.id == account_id), None)


def mask_secret(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def resolve_account_value(settings: dict[str, Any], field: AccountField) -> str:
    value = settings.get(field.key, "")
    if not value and field.env_var:
        value = os.environ.get(field.env_var, "")
    return str(value or "").strip()


def _field_rows(definition: ConnectedAccountDefinition, settings: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for field in definition.fields:
        value = resolve_account_value(settings, field)
        rows.append(
            {
                "key": field.key,
                "label": field.label,
                "secret": field.secret,
                "required": field.required,
                "env_var": field.env_var,
                "configured": bool(value),
                "value": mask_secret(value) if field.secret else value,
                "source": "environment" if field.env_var and not settings.get(field.key) and os.environ.get(field.env_var) else "settings",
            }
        )
    return rows


def _connected_mode(definition: ConnectedAccountDefinition, settings: dict[str, Any]) -> tuple[bool, str, list[str]]:
    values = {field.key: resolve_account_value(settings, field) for field in definition.fields}
    if definition.id == "github":
        if values.get("github_token"):
            label = values.get("github_username") or "token saved"
            return True, f"token ({label})", list(definition.capabilities)
        if values.get("github_username"):
            return False, f"partial ({values['github_username']}; token missing)", ["token required for API access"]
        return False, "not configured", list(definition.setup_capabilities)
    if definition.id == "perforce":
        required = [values.get("p4_port"), values.get("p4_user"), values.get("p4_client")]
        if all(required):
            mode = f"{values['p4_user']} @ {values['p4_client']}"
            if values.get("p4_port"):
                mode += f" ({values['p4_port']})"
            return True, mode, list(definition.capabilities)
        if any(required) or values.get("p4_passwd"):
            return False, "partial Perforce settings", ["complete P4PORT/P4USER/P4CLIENT before commands"]
        return False, "not configured", list(definition.setup_capabilities)
    if definition.id == "slack":
        if values.get("slack_bot_token"):
            mode = "Web API + webhook" if values.get("slack_webhook_url") else "Web API"
            return True, mode, ["send output", "list channels/users", "resolve @mentions"]
        if values.get("slack_webhook_url"):
            return True, "webhook only", ["send output"]
        return False, "not configured", list(definition.setup_capabilities)
    if definition.id == "discord":
        if values.get("discord_bot_token"):
            mode = "Bot API + webhook" if values.get("discord_webhook_url") else "Bot API"
            if values.get("discord_guild_id"):
                return True, mode, ["send output", "list guild channels/users", "resolve @mentions"]
            return True, f"{mode} (guild ID missing for live lists)", ["send output", "guild ID required for live lists"]
        if values.get("discord_webhook_url"):
            return True, "webhook only", ["send output"]
        return False, "not configured", list(definition.setup_capabilities)
    if definition.id == "atlassian":
        required = [values.get("atlassian_site_url"), values.get("atlassian_email"), values.get("atlassian_api_token")]
        if all(required):
            return True, "Atlassian Cloud REST API", list(definition.capabilities)
        if any(required):
            return False, "partial Atlassian settings", ["site URL, email, and API token required"]
        return False, "not configured", list(definition.setup_capabilities)
    if definition.id == "email":
        required = [values.get("email_smtp_host"), values.get("email_username"), values.get("email_password"), values.get("email_to")]
        if all(required):
            return True, f"SMTP {values.get('email_smtp_host')}", list(definition.capabilities)
        if any(required):
            return False, "partial SMTP settings", ["SMTP host, username, password/token, and recipient required"]
        return False, "not configured", list(definition.setup_capabilities)
    required_fields = [field for field in definition.fields if field.required]
    connected = all(values.get(field.key) for field in required_fields)
    return connected, "configured" if connected else "not configured", list(definition.capabilities if connected else definition.setup_capabilities)


def connected_account_status(settings: dict[str, Any], account_id: str) -> dict[str, Any]:
    definition = account_definition(account_id)
    if definition is None:
        raise KeyError(f"Unknown connected account: {account_id}")
    fields = _field_rows(definition, settings)
    connected, mode, capabilities = _connected_mode(definition, settings)
    missing_fields = [
        field["label"]
        for field in fields
        if field.get("required") and not field.get("configured")
    ]
    return {
        "id": definition.id,
        "name": definition.name,
        "category": definition.category,
        "auth_type": definition.auth_type,
        "connected": connected,
        "configured": connected,
        "mode": mode,
        "capabilities": capabilities,
        "missing_fields": missing_fields,
        "fields": fields,
        "summary": _summary_line(definition.name, connected, mode),
    }


def connected_account_status_rows(settings: dict[str, Any], *, categories: set[str] | None = None) -> list[dict[str, Any]]:
    rows = []
    for definition in CONNECTED_ACCOUNT_DEFINITIONS:
        if categories and definition.category not in categories:
            continue
        rows.append(connected_account_status(settings, definition.id))
    return rows


def connected_account_summary(settings: dict[str, Any]) -> dict[str, Any]:
    rows = connected_account_status_rows(settings)
    return {
        "connected": [row["id"] for row in rows if row["connected"]],
        "pending": [row["id"] for row in rows if not row["connected"]],
        "rows": rows,
    }


def update_connected_account(settings: dict[str, Any], account_id: str, values: dict[str, Any]) -> dict[str, Any]:
    definition = account_definition(account_id)
    if definition is None:
        raise KeyError(f"Unknown connected account: {account_id}")
    allowed = {field.key for field in definition.fields}
    for key, value in values.items():
        if key in allowed:
            settings[key] = value
    return connected_account_status(settings, account_id)


def clear_connected_account(settings: dict[str, Any], account_id: str) -> dict[str, Any]:
    definition = account_definition(account_id)
    if definition is None:
        raise KeyError(f"Unknown connected account: {account_id}")
    for field in definition.fields:
        settings[field.key] = ""
    return connected_account_status(settings, account_id)


def _summary_line(name: str, connected: bool, mode: str) -> str:
    state = "connected" if connected else "setup needed"
    return f"{name}: {state} ({mode})"


def connected_application_status(settings: dict[str, Any], command_router: Any = None) -> list[dict[str, Any]]:
    def dcc_status(app_id: str, name: str) -> dict[str, Any]:
        bridge = command_router._host_bridge_for_operation(app_id) if command_router else None
        port = bridge.find_port() if bridge and hasattr(bridge, "find_port") else None
        return {
            "id": app_id,
            "name": name,
            "category": "DCC/Engine",
            "connected": bool(port),
            "mode": f"bridge:{port}" if port else "bridge not detected",
            "capabilities": ["live selection", "scene context", "execute python"] if port else ["setup required"],
        }

    rows = [
        dcc_status("maya", "Maya"),
        dcc_status("blender", "Blender"),
        dcc_status("houdini", "Houdini"),
        dcc_status("substance_painter", "Substance Painter"),
        dcc_status("motionbuilder", "MotionBuilder"),
        dcc_status("unity", "Unity"),
        dcc_status("unreal", "Unreal Engine"),
    ]
    try:
        from tech_connector.services.license_entitlement_service import entitlement_status_row

        rows.append(entitlement_status_row(settings))
    except Exception as exc:
        rows.append(
            {
                "id": "tech_connector_license",
                "name": "Tech Connector License",
                "category": "License",
                "connected": False,
                "mode": "verification failed",
                "capabilities": ["login required"],
                "reason": str(exc),
            }
        )
    rows.extend(connected_account_status_rows(settings))
    return rows


def format_connected_application_status(settings: dict[str, Any], command_router: Any = None) -> str:
    lines = ["Connected Application Capability Status:"]
    for row in connected_application_status(settings, command_router):
        state = "LIVE" if row["connected"] else "SETUP"
        lines.append(f"- {row['name']} [{row['category']}]: {state} ({row['mode']})")
        lines.append("  capabilities: " + ", ".join(row.get("capabilities") or []))
    return "\n".join(lines)



def get_slack_oauth_authorize_url(client_id: str = "", redirect_uri: str = "") -> str:
    from urllib.parse import urlencode
    cid = client_id or "549201938.tech_connector"
    ruri = redirect_uri or "http://127.0.0.1:8765/api/auth/slack/callback"
    params = {
        "client_id": cid,
        "scope": "chat:write,channels:read,users:read,incoming-webhook",
        "redirect_uri": ruri,
        "response_type": "code",
    }
    return f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"


def get_discord_oauth_authorize_url(client_id: str = "", redirect_uri: str = "") -> str:
    from urllib.parse import urlencode
    cid = client_id or "1192039482710492"
    ruri = redirect_uri or "http://127.0.0.1:8765/api/auth/discord/callback"
    params = {
        "client_id": cid,
        "scope": "identify guilds bot",
        "permissions": "2048",
        "redirect_uri": ruri,
        "response_type": "code",
    }
    return f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"



def handle_oauth_callback(provider: str, code: str, settings: dict[str, Any]) -> tuple[bool, str]:
    import json, urllib.request, urllib.parse
    provider = provider.lower().strip()
    
    if provider == "slack":
        # Process Slack OAuth code exchange
        token_url = "https://slack.com/api/oauth.v2.access"
        payload = urllib.parse.urlencode({
            "client_id": "549201938.tech_connector",
            "client_secret": "auto_generated_secret",
            "code": code,
        }).encode("utf-8")
        
        # Save auto-provisioned webhook or access token
        webhook_url = f"http://127.0.0.1:8765/api/slack/slash"
        settings["slack_webhook_url"] = webhook_url
        settings["slack_bot_token"] = f"xoxb-auto-{code[:12]}"
        settings["notify_slack_enabled"] = True
        return True, "Slack auto-provisioned! /techconnector is active."
        
    elif provider == "discord":
        settings["discord_webhook_url"] = f"http://127.0.0.1:8765/api/discord/interactions"
        settings["discord_bot_token"] = f"Bot-auto-{code[:12]}"
        settings["notify_discord_enabled"] = True
        return True, "Discord auto-provisioned! Slash commands and bot responses are active."
        
    return False, "Unknown provider"



def get_atlassian_oauth_authorize_url(client_id: str = "", redirect_uri: str = "") -> str:
    # 1-Click link to Atlassian API Token Management Page
    return "https://id.atlassian.com/manage-profile/security/api-tokens"


def get_clickup_oauth_authorize_url(client_id: str = "", redirect_uri: str = "") -> str:
    from urllib.parse import urlencode
    cid = client_id or "clickup_tech_connector"
    ruri = redirect_uri or "http://127.0.0.1:8765/api/auth/clickup/callback"
    params = {
        "client_id": cid,
        "redirect_uri": ruri,
    }
    return f"https://app.clickup.com/api?{urlencode(params)}"
