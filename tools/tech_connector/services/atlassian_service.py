"""Jira and Confluence Cloud output helpers."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from typing import Any

from tech_connector.services.diagnostic_service import log_backend_event


def _base_url(settings: dict[str, Any]) -> str:
    raw = (settings.get("atlassian_site_url") or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urllib.parse.urlparse(raw)
    domain = parsed.netloc or parsed.path.split("/")[0]
    return f"https://{domain}"


def parse_atlassian_input_url(url_str: str) -> dict[str, str]:
    """Extract site URL, project key, and space key from any text containing Jira/Confluence URLs."""
    import re
    u = (url_str or "").strip()
    if not u:
        return {"site_url": "", "project_key": "", "space_key": ""}
    
    url_match = re.search(r"https?://[a-zA-Z0-9_\-\.]+\.atlassian\.net[^\s]*", u)
    if not url_match:
        url_match = re.search(r"https?://[^\s]+", u)
    
    target = url_match.group(0) if url_match else u
    if "://" not in target:
        target = f"https://{target}"
    
    parsed = urllib.parse.urlparse(target)
    domain = parsed.netloc or parsed.path.split("/")[0]
    site_url = f"https://{domain}"
    
    project_key = ""
    proj_match = re.search(r"/projects/([A-Za-z0-9_]+)", u)
    if proj_match:
        project_key = proj_match.group(1).upper()
    else:
        issue_match = re.search(r"/browse/([A-Za-z0-9_]+)-\d+", u)
        if issue_match:
            project_key = issue_match.group(1).upper()
            
    space_key = ""
    space_match = re.search(r"/spaces/([A-Za-z0-9_]+)", u)
    if space_match:
        space_key = space_match.group(1).upper()
        
    return {"site_url": site_url, "project_key": project_key, "space_key": space_key}


def _auth_header(settings: dict[str, Any]) -> str:
    email = (settings.get("atlassian_email") or "").strip()
    token = settings.get("atlassian_api_token") or ""
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _adf_doc(text: str) -> dict[str, Any]:
    lines = (text or "").splitlines() or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line or " "}],
            }
            for line in lines
        ],
    }


def build_jira_issue_payload(
    project_key: str,
    summary: str,
    description: str,
    *,
    issue_type: str = "Task",
    parent_key: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "project": {"key": (project_key or "").strip()},
        "summary": (summary or "Tech Connector task").strip(),
        "description": _adf_doc(description or ""),
        "issuetype": {"name": (issue_type or "Task").capitalize()},
    }
    if parent_key.strip():
        fields["parent"] = {"key": parent_key.strip()}
    if labels:
        fields["labels"] = labels
    return {"fields": fields}


def create_jira_issue(settings: dict[str, Any], payload: dict[str, Any], *, opener=None) -> tuple[bool, str, dict[str, Any]]:
    base = _base_url(settings)
    if not base:
        return False, "Atlassian site URL is not configured.", {}
    if not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, "Atlassian email/API token are not configured.", {}
    url = f"{base}/rest/api/3/issue"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": _auth_header(settings),
        },
    )
    opener = opener or urllib.request.urlopen
    log_backend_event("atlassian.jira", "Creating Jira issue", command=f"POST {url}", details={"bytes": len(body)})
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 201))
        data = json.loads(raw) if raw.strip() else {}
        ok = 200 <= int(status) < 300
        log_backend_event("atlassian.jira", "Jira issue create finished", command=f"POST {url}", returncode=int(status), stdout=raw)
        key = data.get("key") or data.get("id") or "created"
        return ok, f"Jira issue {key} created." if ok else raw, data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        log_backend_event("atlassian.jira", "Jira issue create failed", command=f"POST {url}", returncode=exc.code, stderr=raw)
        return False, raw or f"Jira returned HTTP {exc.code}.", {}
    except Exception as exc:
        log_backend_event("atlassian.jira", "Jira issue create failed", command=f"POST {url}", error=exc)
        return False, str(exc), {}


def build_confluence_page_payload(space_id: str, title: str, body: str, *, parent_id: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "spaceId": (space_id or "").strip(),
        "status": "current",
        "title": (title or "Tech Connector task notes").strip(),
        "body": {
            "representation": "storage",
            "value": f"<p>{escape(body or '').replace(chr(10), '<br/>')}</p>",
        },
    }
    if parent_id.strip():
        payload["parentId"] = parent_id.strip()
    return payload


def create_confluence_page(settings: dict[str, Any], payload: dict[str, Any], *, opener=None) -> tuple[bool, str, dict[str, Any]]:
    base = _base_url(settings)
    if not base:
        return False, "Atlassian site URL is not configured.", {}
    if not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, "Atlassian email/API token are not configured.", {}
    url = f"{base}/wiki/api/v2/pages"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": _auth_header(settings),
        },
    )
    opener = opener or urllib.request.urlopen
    log_backend_event("atlassian.confluence", "Creating Confluence page", command=f"POST {url}", details={"bytes": len(body)})
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 200))
        data = json.loads(raw) if raw.strip() else {}
        ok = 200 <= int(status) < 300
        log_backend_event("atlassian.confluence", "Confluence page create finished", command=f"POST {url}", returncode=int(status), stdout=raw)
        page_id = data.get("id") or "created"
        return ok, f"Confluence page {page_id} created." if ok else raw, data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        log_backend_event("atlassian.confluence", "Confluence page create failed", command=f"POST {url}", returncode=exc.code, stderr=raw)
        return False, raw or f"Confluence returned HTTP {exc.code}.", {}
    except Exception as exc:
        log_backend_event("atlassian.confluence", "Confluence page create failed", command=f"POST {url}", error=exc)
        return False, str(exc), {}


def _get_json(settings: dict[str, Any], url: str, *, opener=None) -> tuple[bool, Any, str]:
    if not _base_url(settings):
        return False, {}, "Atlassian site URL is not configured."
    if not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, {}, "Atlassian email/API token are not configured."
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "Authorization": _auth_header(settings)},
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 200))
        data = json.loads(raw) if raw.strip() else {}
        return 200 <= int(status) < 300, data, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return False, {}, raw or f"HTTP {exc.code}"
    except Exception as exc:
        return False, {}, str(exc)


def fetch_atlassian_projects_spaces_users(settings: dict[str, Any], *, opener=None) -> tuple[bool, dict[str, list[str]], str]:
    base = _base_url(settings)
    projects_ok, projects_data, projects_msg = _get_json(settings, f"{base}/rest/api/3/project/search?maxResults=100", opener=opener)
    spaces_ok, spaces_data, spaces_msg = _get_json(settings, f"{base}/wiki/api/v2/spaces?limit=100", opener=opener)
    users_ok, users_data, users_msg = _get_json(
        settings,
        f"{base}/rest/api/3/user/search?query={urllib.parse.quote('@')}&maxResults=100",
        opener=opener,
    )
    projects = [item.get("key", "") for item in (projects_data.get("values") or []) if item.get("key")]
    spaces = [item.get("id", "") or item.get("key", "") for item in (spaces_data.get("results") or []) if item.get("id") or item.get("key")]
    users = [item.get("displayName", "") for item in (users_data or []) if isinstance(item, dict) and item.get("displayName")]
    ok = projects_ok and spaces_ok and users_ok
    msg = "Loaded Atlassian projects/spaces/users." if ok else f"Atlassian discovery failed. projects={projects_msg} spaces={spaces_msg} users={users_msg}"
    return ok, {"projects": sorted(set(projects)), "spaces": sorted(set(spaces)), "users": sorted(set(users))}, msg



def search_jira_issues(settings: dict[str, Any], query: str = "", *, opener=None) -> tuple[bool, list[dict[str, Any]], str]:
    base = _base_url(settings)
    if not base or not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, [], "Atlassian API credentials not configured."
    
    jql = f'text ~ "{query}"' if query.strip() else 'ORDER BY updated DESC'
    url = f"{base}/rest/api/3/search?jql={urllib.parse.quote(jql)}&maxResults=20"
    ok, data, msg = _get_json(settings, url, opener=opener)
    
    issues = []
    if ok and isinstance(data, dict):
        for item in data.get("issues") or []:
            fields = item.get("fields") or {}
            issues.append({
                "key": item.get("key", ""),
                "summary": fields.get("summary", ""),
                "status": (fields.get("status") or {}).get("name", ""),
                "issue_type": (fields.get("issuetype") or {}).get("name", ""),
                "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
            })
    return ok, issues, msg


def search_confluence_pages(settings: dict[str, Any], query: str = "", *, opener=None) -> tuple[bool, list[dict[str, Any]], str]:
    base = _base_url(settings)
    if not base or not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, [], "Atlassian API credentials not configured."
    
    cql = f'title ~ "{query}"' if query.strip() else 'type=page ORDER BY lastmodified DESC'
    url = f"{base}/wiki/api/v2/pages?cql={urllib.parse.quote(cql)}&limit=20"
    ok, data, msg = _get_json(settings, url, opener=opener)
    
    pages = []
    if ok and isinstance(data, dict):
        for item in data.get("results") or []:
            pages.append({
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "space_id": item.get("spaceId", ""),
                "status": item.get("status", ""),
            })
    return ok, pages, msg



def get_jira_issue(settings: dict[str, Any], issue_key: str, *, opener=None) -> tuple[bool, dict[str, Any], str]:
    base = _base_url(settings)
    if not base or not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, {}, "Atlassian credentials not configured."
    
    url = f"{base}/rest/api/3/issue/{issue_key.strip()}"
    ok, data, msg = _get_json(settings, url, opener=opener)
    return ok, data if isinstance(data, dict) else {}, msg


def update_jira_issue(settings: dict[str, Any], issue_key: str, payload: dict[str, Any], *, opener=None) -> tuple[bool, str, dict[str, Any]]:
    base = _base_url(settings)
    if not base or not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, "Atlassian credentials not configured.", {}
    
    url = f"{base}/rest/api/3/issue/{issue_key.strip()}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": _auth_header(settings),
        },
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=30) as response:
            status = getattr(response, "status", getattr(response, "code", 204))
        return True, f"Jira issue {issue_key} updated.", {"status": status}
    except Exception as exc:
        return False, str(exc), {}


def get_confluence_page(settings: dict[str, Any], page_id: str, *, opener=None) -> tuple[bool, dict[str, Any], str]:
    base = _base_url(settings)
    if not base or not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, {}, "Atlassian credentials not configured."
    
    url = f"{base}/wiki/api/v2/pages/{page_id.strip()}?body-format=storage"
    ok, data, msg = _get_json(settings, url, opener=opener)
    return ok, data if isinstance(data, dict) else {}, msg


def update_confluence_page(settings: dict[str, Any], page_id: str, title: str, body: str, version_number: int = 2, *, opener=None) -> tuple[bool, str, dict[str, Any]]:
    base = _base_url(settings)
    if not base or not (settings.get("atlassian_email") and settings.get("atlassian_api_token")):
        return False, "Atlassian credentials not configured.", {}
    
    url = f"{base}/wiki/api/v2/pages/{page_id.strip()}"
    payload = {
        "id": page_id.strip(),
        "status": "current",
        "title": title.strip(),
        "body": {
            "representation": "storage",
            "value": f"<p>{escape(body or '').replace(chr(10), '<br/>')}</p>",
        },
        "version": {"number": version_number, "message": "Updated via Tech Connector"},
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body_bytes,
        method="PUT",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": _auth_header(settings),
        },
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", getattr(response, "code", 200))
        data = json.loads(raw) if raw.strip() else {}
        return True, f"Confluence page {page_id} updated.", data
    except Exception as exc:
        return False, str(exc), {}
