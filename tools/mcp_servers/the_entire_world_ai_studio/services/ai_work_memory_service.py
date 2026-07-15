"""Local memory for Tech Connector work history and locked knowledge snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any, Iterable

from models.constants import APP_DIR, APP_ROOT


MEMORY_DIR = APP_DIR / "ai_work_memory"
LOCKS_DIR = MEMORY_DIR / "locks"
JOURNAL_PATH = MEMORY_DIR / "current.jsonl"
THIRD_PARTY_KNOWLEDGE_DIR = APP_ROOT / "knowledge" / "third_party"
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_CONTEXT_CHARS = 6000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_").lower()
    return clean[:64] or "knowledge_lock"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_]+", (text or "").lower())
        if len(token) >= 3
    }


def _ensure_dirs() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    THIRD_PARTY_KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def _read_jsonl(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    records = []
    for line in lines[-limit:]:
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                records.append(data)
        except Exception:
            pass
    return records


def _trim_text(value: Any, limit: int = 4000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = text.strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _compact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
    return {
        "timestamp": entry.get("timestamp") or _utc_now(),
        "host": entry.get("host") or "",
        "mode": entry.get("mode") or "",
        "label": entry.get("label") or "",
        "ok": bool(entry.get("ok")),
        "goal": _trim_text(entry.get("goal") or "", 800),
        "template": params.get("template") or "",
        "target_path": params.get("target_path") or "",
        "source_url": params.get("source_url") or params.get("repo_url") or "",
        "local_path": params.get("local_path") or "",
        "workflow_path": params.get("workflow_path") or "",
        "knowledge_path": params.get("knowledge_path") or "",
        "created_or_modified_assets": entry.get("created_or_modified_assets", []),
        "summary": _trim_text(entry.get("summary") or entry.get("result") or "", 1800),
    }


def _write_third_party_knowledge_record(payload: dict[str, Any]) -> Path:
    _ensure_dirs()
    source = payload.get("repo_name") or payload.get("source_kind") or payload.get("query") or "third_party"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = THIRD_PARTY_KNOWLEDGE_DIR / f"{stamp}_{_slug(str(source))}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _maybe_rotate_journal() -> None:
    if not JOURNAL_PATH.exists() or JOURNAL_PATH.stat().st_size <= MAX_JOURNAL_BYTES:
        return
    records = _read_jsonl(JOURNAL_PATH, limit=2000)
    keep = records[-300:]
    archive = MEMORY_DIR / f"archive_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    JOURNAL_PATH.replace(archive)
    JOURNAL_PATH.write_text(
        "".join(json.dumps(_compact_entry(item), default=str) + "\n" for item in keep),
        encoding="utf-8",
    )


def record_ai_work(
    settings: dict | None,
    *,
    host: str,
    mode: str,
    goal: str,
    params: dict[str, Any] | None,
    label: str,
    ok: bool,
    result: Any,
) -> None:
    """Append one AI operation record to the local work journal."""
    if settings is not None and not settings.get("ai_work_memory_enabled", True):
        return
    _ensure_dirs()
    entry = {
        "timestamp": _utc_now(),
        "host": host,
        "mode": mode,
        "goal": goal,
        "params": params or {},
        "label": label,
        "ok": bool(ok),
        "result": _trim_text(result, 12000),
    }
    with JOURNAL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_compact_entry(entry), default=str) + "\n")
    _maybe_rotate_journal()


def record_approved_external_learning(
    settings: dict | None,
    *,
    source_kind: str,
    query: str,
    approved_item: dict[str, Any] | None = None,
    local_path: str = "",
    workflow_path: str = "",
    summary: str = "",
    host: str = "",
) -> Path | None:
    """Remember user-approved external research/tool/workflow results."""
    if settings is not None and not settings.get("ai_work_memory_enabled", True):
        return None
    approved_item = approved_item or {}
    repo_name = approved_item.get("name") or approved_item.get("full_name") or ""
    repo_url = approved_item.get("html_url") or approved_item.get("url") or ""
    knowledge_payload = {
        "schema": "ai_studio.third_party_knowledge.v1",
        "approved_at": _utc_now(),
        "source_kind": source_kind,
        "query": query,
        "host": host or "external",
        "repo_name": repo_name,
        "repo_url": repo_url,
        "approved_item": approved_item,
        "local_path": local_path,
        "workflow_path": workflow_path,
        "summary": summary.strip(),
    }
    knowledge_path = _write_third_party_knowledge_record(knowledge_payload)
    details = {
        "source_kind": source_kind,
        "query": query,
        "repo_name": repo_name,
        "repo_url": repo_url,
        "source_url": repo_url,
        "local_path": local_path,
        "workflow_path": workflow_path,
        "knowledge_path": str(knowledge_path),
        "language": approved_item.get("language") or "",
        "license": approved_item.get("license") or {},
        "stars": approved_item.get("stars", 0),
        "description": approved_item.get("description") or "",
    }
    text = summary.strip() or (
        f"Approved {source_kind}: {repo_name or repo_url or 'external result'}"
        f" for query: {query}"
    )
    record_ai_work(
        settings,
        host=host or "external",
        mode=source_kind,
        goal=query,
        params=details,
        label=f"Approved external learning: {repo_name or source_kind}",
        ok=True,
        result=text,
    )
    return knowledge_path


def list_locked_knowledge() -> list[dict[str, Any]]:
    _ensure_dirs()
    locks = []
    for path in sorted(LOCKS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data["_path"] = str(path)
                locks.append(data)
        except Exception:
            pass
    return locks


def lock_current_knowledge(settings: dict | None, name: str, note: str = "") -> Path:
    """Freeze the current AI work journal into a named locked snapshot."""
    _ensure_dirs()
    entries = _read_jsonl(JOURNAL_PATH, limit=1000)
    lock = {
        "locked_at": _utc_now(),
        "name": name.strip() or "Knowledge Lock",
        "note": note.strip(),
        "entry_count": len(entries),
        "entries": [_compact_entry(item) for item in entries],
    }
    path = LOCKS_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_slug(name)}.json"
    path.write_text(json.dumps(lock, indent=2, default=str), encoding="utf-8")
    return path


def _score(entry: dict[str, Any], query_tokens: set[str], host: str = "") -> int:
    text = " ".join(
        str(entry.get(key, ""))
        for key in (
            "host", "mode", "label", "goal", "template", "target_path",
            "source_url", "local_path", "workflow_path", "knowledge_path", "summary",
        )
    ).lower()
    score = sum(1 for token in query_tokens if token in text)
    if host and entry.get("host") == host:
        score += 4
    if entry.get("ok"):
        score += 1
    return score


def _best_entries(entries: Iterable[dict[str, Any]], query: str, host: str = "", limit: int = 8) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    ranked = []
    for index, entry in enumerate(entries):
        score = _score(entry, query_tokens, host)
        if score or not query_tokens:
            ranked.append((score, index, entry))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for _score, _index, entry in ranked[:limit]]


def relevant_ai_work_context(
    settings: dict | None,
    query: str,
    *,
    host: str = "",
    limit: int = 8,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> str:
    """Return a bounded context block from locked snapshots and recent work."""
    matches = relevant_ai_work_entries(settings, query, host=host, limit=limit)
    recent = matches.get("recent", [])
    locked = matches.get("locked", [])
    if not recent and not locked:
        return ""

    lines = ["Tech Connector Previous Work Context:"]
    if locked:
        lines.append("- Locked knowledge matches:")
        for item in locked:
            lines.append(
                f"  - [{item.get('host')} {item.get('mode')}] {item.get('goal')} "
                f"(lock: {item.get('locked_snapshot')}, target: {item.get('target_path') or item.get('local_path') or item.get('workflow_path') or item.get('knowledge_path') or 'n/a'})"
            )
    if recent:
        lines.append("- Recent work matches:")
        for item in recent:
            lines.append(
                f"  - [{item.get('host')} {item.get('mode')}] {item.get('goal')} "
                f"(ok: {item.get('ok')}, target: {item.get('target_path') or item.get('local_path') or item.get('workflow_path') or item.get('knowledge_path') or 'n/a'})"
            )
    text = "\n".join(lines)
    return text[:max_chars]


def relevant_ai_work_entries(
    settings: dict | None,
    query: str,
    *,
    host: str = "",
    limit: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Return structured recent/locked matches for compact expert context."""
    settings = settings or {}
    if not settings.get("ai_work_memory_enabled", True):
        return {"recent": [], "locked": []}

    _ensure_dirs()
    recent = _best_entries(_read_jsonl(JOURNAL_PATH, limit=500), query, host=host, limit=limit)
    locked = []
    if settings.get("ai_work_memory_include_locked", True):
        for lock in list_locked_knowledge()[:5]:
            for item in lock.get("entries", [])[-300:]:
                item = dict(item)
                item["locked_snapshot"] = lock.get("name") or "Knowledge Lock"
                locked.append(item)
    locked = _best_entries(locked, query, host=host, limit=max(2, limit // 2))
    return {"recent": recent, "locked": locked}


def knowledge_status_summary(settings: dict | None = None) -> str:
    _ensure_dirs()
    current = _read_jsonl(JOURNAL_PATH, limit=10000)
    locks = list_locked_knowledge()
    size = JOURNAL_PATH.stat().st_size if JOURNAL_PATH.exists() else 0
    lines = [
        f"AI work memory: {'enabled' if (settings or {}).get('ai_work_memory_enabled', True) else 'disabled'}",
        f"Journal: {JOURNAL_PATH}",
        f"Journal entries loaded: {len(current)}",
        f"Journal size: {size / 1024:.1f} KB",
        f"Locked snapshots: {len(locks)}",
    ]
    for lock in locks[:8]:
        lines.append(f"- {lock.get('name')} ({lock.get('locked_at')}): {lock.get('entry_count', 0)} entries")
    return "\n".join(lines)
