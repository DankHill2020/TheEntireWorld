"""Notification outputs for pipeline and backend reports."""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any

from tech_connector.services.diagnostic_service import log_backend_event


def _mask_secret(value: str) -> str:
    value = value or ""
    if len(value) <= 8:
        return "***" if value else ""
    return value[:4] + "..." + value[-4:]


def build_pipeline_message(title: str, body: str, *, status: str = "", source: str = "") -> str:
    parts = [title.strip() or "Tech Connector Pipeline Output"]
    if status:
        parts.append(f"Status: {status}")
    if source:
        parts.append(f"Source: {source}")
    if body:
        parts.append(str(body).strip())
    return "\n\n".join(part for part in parts if part)


def send_slack_webhook(
    webhook_url: str,
    text: str,
    *,
    opener=None,
    timeout: int = 20,
) -> tuple[bool, str]:
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return False, "Slack webhook URL is not configured."
    payload = json.dumps({"text": text or "Tech Connector notification"}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = opener or urllib.request.urlopen
    log_backend_event(
        "notification.slack",
        "Sending Slack webhook notification",
        command="POST Slack incoming webhook",
        details={"webhook": _mask_secret(webhook_url), "bytes": len(payload)},
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 200))
        ok = 200 <= int(status) < 300 and raw.strip().lower() in {"", "ok"}
        log_backend_event(
            "notification.slack",
            "Slack webhook notification finished",
            returncode=int(status),
            stdout=raw,
        )
        return ok, raw.strip() or f"Slack returned HTTP {status}."
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        log_backend_event(
            "notification.slack",
            "Slack webhook notification failed",
            returncode=exc.code,
            stderr=raw,
        )
        return False, raw or f"Slack webhook failed with HTTP {exc.code}."
    except Exception as exc:
        log_backend_event("notification.slack", "Slack webhook notification failed", error=exc)
        return False, str(exc)


def send_discord_webhook(
    webhook_url: str,
    content: str,
    *,
    username: str = "Tech Connector",
    opener=None,
    timeout: int = 20,
) -> tuple[bool, str]:
    webhook_url = (webhook_url or "").strip()
    if not webhook_url:
        return False, "Discord webhook URL is not configured."
    text = (content or "Tech Connector notification").strip()
    if len(text) > 2000:
        text = text[:1997] + "..."
    payload = json.dumps({"content": text, "username": username or "Tech Connector"}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = opener or urllib.request.urlopen
    log_backend_event(
        "notification.discord",
        "Sending Discord webhook notification",
        command="POST Discord webhook",
        details={"webhook": _mask_secret(webhook_url), "bytes": len(payload)},
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 204))
        ok = 200 <= int(status) < 300
        log_backend_event(
            "notification.discord",
            "Discord webhook notification finished",
            returncode=int(status),
            stdout=raw,
        )
        return ok, raw.strip() or f"Discord returned HTTP {status}."
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        log_backend_event(
            "notification.discord",
            "Discord webhook notification failed",
            returncode=exc.code,
            stderr=raw,
        )
        return False, raw or f"Discord webhook failed with HTTP {exc.code}."
    except Exception as exc:
        log_backend_event("notification.discord", "Discord webhook notification failed", error=exc)
        return False, str(exc)


def _api_get_json(url: str, token: str, *, opener=None, timeout: int = 20, auth_prefix: str = "Bearer") -> tuple[bool, Any, str]:
    token = (token or "").strip()
    if not token:
        return False, {}, "API token is not configured."
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"{auth_prefix} {token}", "Accept": "application/json"},
        method="GET",
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 200))
        data = json.loads(raw) if raw.strip() else {}
        return 200 <= int(status) < 300, data, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return False, {}, raw or f"HTTP {exc.code}"
    except Exception as exc:
        return False, {}, str(exc)


def fetch_slack_channels_and_users(settings: dict[str, Any], *, opener=None) -> tuple[bool, dict[str, list[str]], str]:
    token = settings.get("slack_bot_token") or ""
    channels_ok, channels_data, channels_msg = _api_get_json(
        "https://slack.com/api/conversations.list?exclude_archived=true&limit=200&types=public_channel,private_channel",
        token,
        opener=opener,
    )
    users_ok, users_data, users_msg = _api_get_json(
        "https://slack.com/api/users.list?limit=200",
        token,
        opener=opener,
    )
    channels = [item.get("name", "") for item in (channels_data.get("channels") or []) if item.get("name")]
    users = [
        (item.get("profile") or {}).get("display_name") or item.get("name", "")
        for item in (users_data.get("members") or [])
        if not item.get("deleted") and not item.get("is_bot")
    ]
    ok = channels_ok and users_ok and bool(channels_data.get("ok", True)) and bool(users_data.get("ok", True))
    msg = "Loaded Slack channels/users." if ok else f"Slack discovery failed. channels={channels_msg} users={users_msg}"
    return ok, {"channels": sorted(set(channels)), "users": sorted(set(filter(None, users)))}, msg


def fetch_discord_channels_and_users(settings: dict[str, Any], *, opener=None) -> tuple[bool, dict[str, list[str]], str]:
    token = settings.get("discord_bot_token") or ""
    guild_id = (settings.get("discord_guild_id") or "").strip()
    if not guild_id:
        return False, {"channels": [], "users": []}, "Discord guild/server ID is not configured."
    channels_ok, channels_data, channels_msg = _api_get_json(
        f"https://discord.com/api/v10/guilds/{guild_id}/channels",
        token,
        opener=opener,
        auth_prefix="Bot",
    )
    users_ok, users_data, users_msg = _api_get_json(
        f"https://discord.com/api/v10/guilds/{guild_id}/members?limit=200",
        token,
        opener=opener,
        auth_prefix="Bot",
    )
    channels = [item.get("name", "") for item in (channels_data or []) if isinstance(item, dict) and item.get("name")]
    users = []
    for item in users_data or []:
        if not isinstance(item, dict):
            continue
        user = item.get("user") or {}
        users.append(item.get("nick") or user.get("global_name") or user.get("username") or "")
    ok = channels_ok and users_ok
    msg = "Loaded Discord channels/users." if ok else f"Discord discovery failed. channels={channels_msg} users={users_msg}"
    return ok, {"channels": sorted(set(channels)), "users": sorted(set(filter(None, users)))}, msg


def send_email_smtp(settings: dict[str, Any], subject: str, body: str, *, smtp_factory=None) -> tuple[bool, str]:
    host = (settings.get("email_smtp_host") or "").strip()
    port = int(settings.get("email_smtp_port") or 587)
    username = (settings.get("email_username") or "").strip()
    password = settings.get("email_password") or ""
    sender = (settings.get("email_from") or username).strip()
    recipients = _split_recipients(settings.get("email_to") or "")
    use_tls = bool(settings.get("email_use_tls", True))
    use_ssl = bool(settings.get("email_use_ssl", False))

    if not host:
        return False, "SMTP host is not configured."
    if not sender:
        return False, "Email sender is not configured."
    if not recipients:
        return False, "Email recipient is not configured."

    msg = EmailMessage()
    msg["Subject"] = subject or "Tech Connector Pipeline Output"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body or "")

    log_backend_event(
        "notification.email",
        "Sending email notification",
        command=f"SMTP {host}:{port}",
        details={"from": sender, "to_count": len(recipients), "tls": use_tls, "ssl": use_ssl},
    )
    try:
        if smtp_factory:
            smtp = smtp_factory(host, port)
        elif use_ssl:
            smtp = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(host, port, timeout=30)
        with smtp:
            if use_tls and not use_ssl:
                smtp.starttls(context=ssl.create_default_context())
            if username or password:
                smtp.login(username, password)
            smtp.send_message(msg)
        log_backend_event("notification.email", "Email notification sent", command=f"SMTP {host}:{port}", returncode=0)
        return True, "Email sent."
    except Exception as exc:
        log_backend_event("notification.email", "Email notification failed", command=f"SMTP {host}:{port}", error=exc)
        return False, str(exc)


def _split_recipients(value: str) -> list[str]:
    return [part.strip() for part in (value or "").replace(";", ",").split(",") if part.strip()]


def send_pipeline_output(settings: dict[str, Any], title: str, body: str, *, status: str = "", source: str = "") -> dict[str, Any]:
    message = build_pipeline_message(title, body, status=status, source=source)
    results: dict[str, Any] = {}
    if settings.get("notify_slack_enabled"):
        ok, msg = send_slack_webhook(settings.get("slack_webhook_url", ""), message)
        results["slack"] = {"ok": ok, "message": msg}
    if settings.get("notify_discord_enabled"):
        ok, msg = send_discord_webhook(
            settings.get("discord_webhook_url", ""),
            message,
            username=settings.get("discord_username", "Tech Connector"),
        )
        results["discord"] = {"ok": ok, "message": msg}
    if settings.get("notify_email_enabled"):
        ok, msg = send_email_smtp(settings, title or "Tech Connector Pipeline Output", message)
        results["email"] = {"ok": ok, "message": msg}
    if not results:
        results["enabled"] = False
    return results



def parse_and_dispatch_inline_messaging(
    text: str,
    settings: dict[str, Any] | None = None,
    *,
    default_title: str = "Tech Connector Output",
) -> list[dict[str, Any]]:
    import re
    settings = settings or {}
    pattern = r"@(?P<platform>slack|discord|jira|confluence|clickup|docs)(?:\.(?P<target>[a-zA-Z0-9_\-\.]+))?(?:\s+(?P<content>.*?))(?=(?:@(?:slack|discord|jira|confluence|clickup|docs)|$))"
    matches = list(re.finditer(pattern, text, re.DOTALL | re.IGNORECASE))
    
    if not matches:
        return []
    
    results = []
    for match in matches:
        platform = match.group("platform").lower()
        target = (match.group("target") or ("KAN" if platform == "jira" else "DOCS")).strip()
        raw_content = (match.group("content") or "").strip() or text
        
        parts = target.split(".")
        main_target = parts[0]
        sub_type = parts[1].lower() if len(parts) > 1 else ""
        
        formatted_msg = f"[{default_title}] Target: #{target}\n\n{raw_content}"
        
        if platform == "slack":
            url = settings.get(f"slack_webhook_{main_target}") or settings.get("slack_webhook_url", "")
            ok, msg = send_slack_webhook(url, formatted_msg)
            results.append({"platform": "slack", "target": target, "ok": ok, "message": msg, "content": raw_content})
        elif platform == "discord":
            url = settings.get(f"discord_webhook_{main_target}") or settings.get("discord_webhook_url", "")
            username = settings.get("discord_username", "Tech Connector")
            ok, msg = send_discord_webhook(url, formatted_msg, username=username)
            results.append({"platform": "discord", "target": target, "ok": ok, "message": msg, "content": raw_content})
        elif platform == "jira":
            from tech_connector.services.atlassian_service import create_jira_issue, build_jira_issue_payload
            issue_type = "Bug" if sub_type in {"bug", "issue"} else ("Story" if sub_type == "story" else ("Epic" if sub_type == "epic" else ("Sub-task" if sub_type == "subtask" else "Task")))
            parent_key = main_target if sub_type == "subtask" and "-" in main_target else ""
            proj_key = main_target.split("-")[0] if "-" in main_target else main_target
            
            payload = build_jira_issue_payload(proj_key, f"{default_title}: {target}", raw_content, issue_type=issue_type, parent_key=parent_key)
            ok, msg, data = create_jira_issue(settings, payload)
            results.append({"platform": "jira", "target": target, "issue_type": issue_type, "ok": ok, "message": msg, "content": raw_content, "data": data})
        elif platform in {"confluence", "docs"}:
            from tech_connector.services.atlassian_service import create_confluence_page, build_confluence_page_payload
            parent_id = parts[1] if len(parts) > 1 and parts[1].isdigit() else ""
            space_id = main_target
            payload = build_confluence_page_payload(space_id, f"{default_title}: {target}", raw_content, parent_id=parent_id)
            ok, msg, data = create_confluence_page(settings, payload)
            results.append({"platform": "confluence", "target": target, "parent_id": parent_id, "ok": ok, "message": msg, "content": raw_content, "data": data})
        elif platform == "clickup":
            from tech_connector.services.clickup_service import create_clickup_task
            payload = {"list_id": main_target, "name": f"{default_title}: {target}", "description": raw_content, "status": "bug" if sub_type == "bug" else "to do"}
            ok, msg, data = create_clickup_task(settings, payload)
            results.append({"platform": "clickup", "target": target, "sub_type": sub_type, "ok": ok, "message": msg, "content": raw_content, "data": data})
            
    return results
