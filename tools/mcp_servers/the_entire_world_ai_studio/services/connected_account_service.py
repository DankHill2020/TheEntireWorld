"""Unified connected account metadata for VCS, messaging, and ops services."""

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
