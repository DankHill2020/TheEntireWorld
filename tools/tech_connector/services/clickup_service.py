"""ClickUp API integration helpers for task and documentation management."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from tech_connector.services.diagnostic_service import log_backend_event


def create_clickup_task(
    settings: dict[str, Any],
    payload: dict[str, Any],
    *,
    opener=None,
) -> tuple[bool, str, dict[str, Any]]:
    token = (settings.get("clickup_api_token") or "").strip()
    list_id = (payload.get("list_id") or settings.get("clickup_default_list_id") or "").strip()
    
    if not token:
        return False, "ClickUp API token is not configured.", {}
    if not list_id:
        return False, "ClickUp List ID is not configured.", {}

    url = f"https://api.clickup.com/api/v2/list/{list_id}/task"
    body_data = {
        "name": str(payload.get("name") or payload.get("summary") or "Tech Connector Task").strip(),
        "description": str(payload.get("description") or payload.get("text") or "").strip(),
        "status": str(payload.get("status") or "to do").lower(),
        "priority": int(payload.get("priority") or 3),
    }
    
    body = json.dumps(body_data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": token,
        },
    )
    opener = opener or urllib.request.urlopen
    log_backend_event("clickup.task", "Creating ClickUp task", command=f"POST {url}", details={"bytes": len(body)})
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 200))
        data = json.loads(raw) if raw.strip() else {}
        ok = 200 <= int(status) < 300
        task_id = data.get("id") or "created"
        return ok, f"ClickUp task #{task_id} created." if ok else raw, data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return False, raw or f"ClickUp returned HTTP {exc.code}.", {}
    except Exception as exc:
        return False, str(exc), {}


def create_clickup_doc(
    settings: dict[str, Any],
    payload: dict[str, Any],
    *,
    opener=None,
) -> tuple[bool, str, dict[str, Any]]:
    token = (settings.get("clickup_api_token") or "").strip()
    workspace_id = (payload.get("workspace_id") or settings.get("clickup_workspace_id") or "").strip()
    
    if not token:
        return False, "ClickUp API token is not configured.", {}
    if not workspace_id:
        return False, "ClickUp Workspace ID is not configured.", {}

    url = f"https://api.clickup.com/api/v2/workspace/{workspace_id}/doc"
    body_data = {
        "name": str(payload.get("name") or payload.get("title") or "Tech Connector Documentation").strip(),
        "content": str(payload.get("content") or payload.get("text") or "").strip(),
    }
    
    body = json.dumps(body_data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": token,
        },
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 200))
        data = json.loads(raw) if raw.strip() else {}
        ok = 200 <= int(status) < 300
        doc_id = data.get("id") or "created"
        return ok, f"ClickUp Doc #{doc_id} created." if ok else raw, data
    except Exception as exc:
        return False, str(exc), {}



def search_clickup_tasks(settings: dict[str, Any], query: str = "", *, opener=None) -> tuple[bool, list[dict[str, Any]], str]:
    import urllib.parse
    token = (settings.get("clickup_api_token") or "").strip()
    team_id = (settings.get("clickup_team_id") or "").strip()
    if not token or not team_id:
        return False, [], "ClickUp API credentials or Team ID not configured."
    
    url = f"https://api.clickup.com/api/v2/team/{team_id}/task?query={urllib.parse.quote(query)}"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": token, "Accept": "application/json"},
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        tasks = [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "status": (t.get("status") or {}).get("status"),
                "priority": (t.get("priority") or {}).get("priority"),
            }
            for t in (data.get("tasks") or [])
        ]
        return True, tasks, "ClickUp tasks retrieved."
    except Exception as exc:
        return False, [], str(exc)
