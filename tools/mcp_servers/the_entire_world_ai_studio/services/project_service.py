"""Project file tree, file I/O, health orchestration, edit target discovery, and background intelligence daemon service."""

from __future__ import annotations

import ast
import json
import os
import re
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from models.constants import SKIP_DIRS
from models.files import is_supported_code_file


_FOLDER_ENTRY_CACHE: dict[str, tuple[float, int, list[tuple[str, str, str]]]] = {}
_FOLDER_ENTRY_CACHE_TTL_SECONDS = 3.0


def read_file(path: str) -> tuple[bool, str]:
    try:
        return True, Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, str(e)


def save_file(path: str, content: str) -> tuple[bool, str]:
    try:
        p = Path(path)
        backup = p.with_suffix(p.suffix + ".tew_backup")
        if p.exists() and not backup.exists():
            backup.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        p.write_text(content, encoding="utf-8")
        return True, str(p)
    except Exception as e:
        return False, str(e)


def is_read_only_file(path: str) -> bool:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return False
    try:
        return not bool(p.stat().st_mode & stat.S_IWRITE)
    except Exception:
        return False


def make_file_writable(path: str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"File not found: {p}"
    try:
        current_mode = p.stat().st_mode
        p.chmod(current_mode | stat.S_IWRITE)
        return True, str(p)
    except Exception as e:
        return False, str(e)


def populate_folder_entries(
    folder_path: Path,
    *,
    use_cache: bool = True,
) -> list[tuple[str, str, str]]:
    """List entries for lazy tree population using cached ``os.scandir`` data.

    Returns ``(name, path, kind)`` tuples where kind is ``folder``, ``file``,
    or ``error``. Directory metadata from ``DirEntry`` is reused so Windows
    does not need repeated filesystem probes for each row.
    """

    folder_path = Path(folder_path)
    cache_key = str(folder_path.resolve()) if folder_path.exists() else str(folder_path)
    now = time.monotonic()

    try:
        stat_result = folder_path.stat()
        directory_mtime_ns = int(getattr(stat_result, "st_mtime_ns", 0))
    except Exception as exc:
        return [("[error]", str(folder_path), "error")]

    if use_cache:
        cached = _FOLDER_ENTRY_CACHE.get(cache_key)
        if cached:
            cached_at, cached_mtime_ns, cached_entries = cached
            if (
                cached_mtime_ns == directory_mtime_ns
                and now - cached_at <= _FOLDER_ENTRY_CACHE_TTL_SECONDS
            ):
                return list(cached_entries)

    entries: list[tuple[str, str, str]] = []
    try:
        with os.scandir(folder_path) as iterator:
            children = list(iterator)
    except Exception:
        return [("[error]", str(folder_path), "error")]

    def entry_sort_key(entry: os.DirEntry) -> tuple[bool, str]:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False
        return (not is_dir, entry.name.casefold())

    children.sort(key=entry_sort_key)

    for child in children:
        if child.name in SKIP_DIRS:
            continue

        try:
            if child.is_dir(follow_symlinks=False):
                entries.append((child.name, child.path, "folder"))
                continue

            if child.is_file(follow_symlinks=False):
                child_path = Path(child.path)
                if is_supported_code_file(child_path):
                    entries.append((child.name, child.path, "file"))
        except OSError:
            continue

    _FOLDER_ENTRY_CACHE[cache_key] = (
        now,
        directory_mtime_ns,
        list(entries),
    )
    return entries


def folder_has_children(folder_path: Path) -> bool:
    """Return whether a folder has entries using a single scandir probe.

    Lazy tree population no longer calls this for every child folder, but the
    function remains efficient for legacy callers.
    """
    try:
        with os.scandir(folder_path) as iterator:
            return next(iterator, None) is not None
    except Exception:
        return False


def invalidate_folder_entry_cache(folder_path: str | Path | None = None) -> None:
    """Invalidate one cached directory listing or the complete lazy-tree cache."""
    if folder_path is None:
        _FOLDER_ENTRY_CACHE.clear()
        return

    try:
        key = str(Path(folder_path).resolve())
    except Exception:
        key = str(folder_path)
    _FOLDER_ENTRY_CACHE.pop(key, None)


def build_full_project_tree(roots: list[str], max_files_per_root: int = 6000) -> list[dict]:
    """
    Build a full project tree structure (non-lazy).
    Returns nested dict nodes: {name, path, kind, children}.
    """
    nodes = []

    for root_path in roots:
        root_p = Path(root_path)
        root_node = {
            "name": root_p.name or str(root_p),
            "path": str(root_p),
            "kind": "folder",
            "children": [],
        }
        nodes.append(root_node)

        if not root_p.exists():
            root_node["children"].append({"name": "[missing]", "path": str(root_p), "kind": "file", "children": []})
            continue

        folder_items = {root_p: root_node}
        file_count = 0

        try:
            for p in sorted(root_p.rglob("*"), key=lambda x: str(x).lower()):
                if file_count >= max_files_per_root:
                    root_node["children"].append({
                        "name": f"... truncated at {max_files_per_root} files ...",
                        "path": "",
                        "kind": "file",
                        "children": [],
                    })
                    break

                if any(part in SKIP_DIRS for part in p.parts):
                    continue

                try:
                    rel_parts = p.relative_to(root_p).parts
                except Exception:
                    rel_parts = (p.name,)

                parent_path = root_p
                parent_node = root_node

                for folder_name in rel_parts[:-1]:
                    parent_path = parent_path / folder_name
                    if parent_path not in folder_items:
                        folder_node = {
                            "name": folder_name,
                            "path": str(parent_path),
                            "kind": "folder",
                            "children": [],
                        }
                        parent_node["children"].append(folder_node)
                        folder_items[parent_path] = folder_node
                    parent_node = folder_items[parent_path]

                if p.is_dir():
                    if p not in folder_items:
                        folder_node = {
                            "name": p.name,
                            "path": str(p),
                            "kind": "folder",
                            "children": [],
                        }
                        parent_node["children"].append(folder_node)
                        folder_items[p] = folder_node
                    continue

                if not p.is_file() or not is_supported_code_file(p):
                    continue

                parent_node["children"].append({
                    "name": p.name,
                    "path": str(p),
                    "kind": "file",
                    "children": [],
                })
                file_count += 1

        except Exception as e:
            root_node["children"].append({"name": f"[error: {e}]", "path": str(root_p), "kind": "file", "children": []})

    return nodes


# --- Project Health Service (merged from project_health_service.py) ---

_HEALTH_CACHE: dict[tuple[str, str, int, tuple[str, ...]], tuple[float, str]] = {}
_CACHE_TTL_SECONDS = 30.0
_SYNC_CACHE: dict[tuple[str, tuple[str, ...], int, bool], tuple[float, dict[str, Any]]] = {}
_SYNC_CACHE_TTL_SECONDS = 20.0


@dataclass(frozen=True)
class ProjectHealthRequest:
    kind: str
    scope: str = "project"
    limit: int = 200


def is_project_health_request(question: str) -> bool:
    q = (question or "").lower()
    return bool(
        re.search(
            r"\b(dead code|dead function|dead functions|dead class|dead classes|unused symbol|unused symbols|unused function|unused functions|unused class|unused classes|unused import|unused imports|not used|not referenced|orphan|orphaned|safe to delete|index stale|out of sync|sync status)\b",
            q,
        )
    )


def detect_project_health_request(question: str) -> ProjectHealthRequest:
    q = (question or "").lower()
    scope = "all" if any(token in q for token in ("all indexed", "everything", "including engine", "including stdlib")) else "project"
    limit = 300 if any(token in q for token in ("all", "every")) else 120

    if re.search(r"\b(index stale|out of sync|sync status|changed since|not indexed)\b", q):
        return ProjectHealthRequest("index_sync", scope, limit)
    if re.search(r"\b(unused import|unused imports|dead import|dead imports)\b", q):
        return ProjectHealthRequest("unused_imports", scope, limit)
    if re.search(r"\b(dead class|dead classes|unused class|unused classes|orphan class|orphan classes)\b", q):
        return ProjectHealthRequest("unused_classes", scope, limit)
    if re.search(r"\b(dead function|dead functions|unused function|unused functions|orphan function|orphan functions)\b", q):
        return ProjectHealthRequest("unused_functions", scope, limit)
    if re.search(r"\b(dead symbol|dead symbols|unused symbol|unused symbols)\b", q):
        return ProjectHealthRequest("unused_symbols", scope, limit)
    if re.search(r"\b(unused file|unused files|dead file|dead files|not imported|never imported|safe to delete)\b", q):
        return ProjectHealthRequest("unused_files", scope, limit)
    return ProjectHealthRequest("unused_symbols", scope, limit)


def _project_roots(active_path: str | None = None) -> list[str]:
    roots: list[str] = []
    try:
        from services.settings_service import load_settings
        from models.project import project_roots

        roots.extend(project_roots(load_settings()))
    except Exception:
        pass

    if active_path:
        try:
            p = Path(active_path).expanduser().resolve()
            probe = p.parent if p.is_file() else p
            while probe != probe.parent:
                if (probe / ".git").exists() or (probe / "app").exists() or (probe / "pyproject.toml").exists():
                    val = str(probe)
                    if val not in roots:
                        roots.insert(0, val)
                    break
                probe = probe.parent
        except Exception:
            pass
    return roots


def index_sync_summary(active_path: str | None = None, *, limit: int = 40, force: bool = False, scan_new_files: bool = False) -> dict[str, Any]:
    """Fast cached stale-index summary for the UI."""
    from knowledge.search import get_index_sync_status

    roots = tuple(_project_roots(active_path))
    now = time.time()
    cache_key = (str(active_path or ""), roots, int(limit), bool(scan_new_files))
    if not force and cache_key in _SYNC_CACHE:
        ts, cached = _SYNC_CACHE[cache_key]
        if now - ts < _SYNC_CACHE_TTL_SECONDS:
            return cached

    result = get_index_sync_status(
        project_roots=list(roots),
        limit=limit,
        scan_new_files=scan_new_files,
        max_checked=2500,
    )
    _SYNC_CACHE[cache_key] = (now, result)
    return result


def format_stale_warning(sync: dict[str, Any]) -> str:
    if not sync or sync.get("error"):
        return ""
    if not sync.get("stale"):
        return ""
    total = sync.get("total_stale", 0)
    changed = sync.get("total_changed", 0)
    missing = sync.get("total_missing", 0)
    new = sync.get("total_new", 0)
    return (
        f"Note: the project index may be stale. {total} file(s) differ from the last index "
        f"({changed} changed, {missing} missing, {new} new). Results may be incomplete until quick reindex runs."
    )


def answer_project_health_request(question: str, active_path: str | None = None, *, use_cache: bool = True) -> str:
    request = detect_project_health_request(question)
    roots = tuple(_project_roots(active_path))
    cache_key = (request.kind, request.scope, request.limit, roots)
    now = time.time()
    if use_cache and cache_key in _HEALTH_CACHE:
        ts, cached = _HEALTH_CACHE[cache_key]
        if now - ts < _CACHE_TTL_SECONDS:
            return cached

    from knowledge.search import (
        analyze_unused_classes,
        analyze_unused_files,
        analyze_unused_functions,
        analyze_unused_imports,
        analyze_unused_symbols,
        format_graph_analysis_context,
        format_index_sync_context,
        format_unused_symbols_context,
        get_index_sync_status,
    )

    sync = get_index_sync_status(project_roots=list(roots), scope=request.scope, limit=40, scan_new_files=(request.kind == 'index_sync'), max_checked=5000)
    warning = format_stale_warning(sync)

    parts = []
    if warning:
        parts.append(warning)
        parts.append("")

    if request.kind == "index_sync":
        parts.append(format_index_sync_context(sync))
    elif request.kind == "unused_imports":
        parts.append(format_graph_analysis_context(analyze_unused_imports(scope=request.scope, limit=request.limit)))
    elif request.kind == "unused_files":
        parts.append(format_graph_analysis_context(analyze_unused_files(scope=request.scope, limit=request.limit)))
    elif request.kind == "unused_classes":
        parts.append(format_unused_symbols_context(analyze_unused_classes(scope=request.scope, limit=request.limit)))
    elif request.kind == "unused_functions":
        parts.append(format_unused_symbols_context(analyze_unused_functions(scope=request.scope, limit=request.limit)))
    else:
        parts.append(format_unused_symbols_context(analyze_unused_symbols(scope=request.scope, limit=request.limit)))

    parts.append("")
    parts.append("Verification: run Quick Index, then rerun this analysis before deleting anything. Static analysis can miss reflection, Qt signals, DCC callbacks, plugin discovery, and dynamic imports.")
    result = "\n".join(parts).strip()
    _HEALTH_CACHE[cache_key] = (now, result)
    return result


# --- Project Intelligence Daemon Service (merged from project_intelligence_service.py) ---

class ProjectIntelligenceService:
    def __init__(self, port: int = 12349, project_root: str | None = None, auto_start: bool = True):
        self.port = port
        self.project_root = str(Path(project_root).expanduser().resolve()) if project_root else None
        self.auto_start = bool(auto_start)
        self.base_url = f"http://127.0.0.1:{port}"
        self._process: Optional[subprocess.Popen] = None
        self._last_error: Optional[str] = None
        self._last_start_attempt = 0.0

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        self._last_error = None
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                self._last_error = parsed.get("error") or body or str(exc)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                self._last_error = str(exc)
        except Exception as exc:
            self._last_error = str(exc)
        return None

    def is_daemon_running(self) -> bool:
        data = self._request("/status", timeout=0.8)
        return bool(data and data.get("status") == "running")

    def ensure_running(self, project_root: str | None = None) -> Tuple[bool, str]:
        root = project_root or self.project_root
        if self.is_daemon_running():
            return True, "Daemon already running"
        if not self.auto_start:
            return False, self._last_error or "Daemon is not running and auto-start is disabled"
        if not root:
            return False, "No project root available for Project Intelligence daemon"
        now = time.time()
        if now - self._last_start_attempt < 5.0:
            return (self.is_daemon_running(), self._last_error or "Daemon start attempt already in progress")
        self._last_start_attempt = now
        return self.start_daemon(root)

    def ingest_unreal_if_connected(self, project_root: str | None = None, mode: str = "quick") -> Dict[str, Any]:
        root = project_root or self.project_root
        try:
            from services.ai_project_intelligence import ingest_unreal_if_connected
            return ingest_unreal_if_connected(root, mode=mode)
        except Exception as exc:
            return {"ok": False, "skipped": True, "reason": str(exc)}

    def get_status(self) -> Optional[Dict[str, Any]]:
        return self._request("/status", timeout=1.2)

    def get_health(self) -> Optional[Dict[str, Any]]:
        return self._request("/health", timeout=2.0)

    def get_docs_status(self, version: str = "5.8") -> Optional[Dict[str, Any]]:
        url = f"/docs/status?version={urllib.parse.quote(version)}"
        return self._request(url, timeout=1.5)

    def get_file_context(self, file_path: str):
        try:
            from services.file_index_service import file_index_service
            content = file_index_service.get_file_content(file_path)
            metadata = file_index_service.get_file_metadata(file_path)
            if content is not None:
                return {
                    "file_path": file_path,
                    "content": content,
                    "metadata": metadata,
                    "source": "local_index",
                }
            return None
        except Exception as exc:
            print(f"Error getting file context: {exc}")
            return None

    def search_project_files(self, query: str, limit: int = 10):
        try:
            from services.file_index_service import file_index_service
            return file_index_service.search_files(query, limit)
        except Exception as exc:
            print(f"Error searching project files: {exc}")
            return []

    def refresh_docs(
        self, version: str = "5.8", max_pages: int = 0, force: bool = False
    ) -> Optional[Dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "version": version,
                "max_pages": int(max_pages),
                "force": "true" if force else "false",
            }
        )
        timeout = 120.0 if max_pages else 30.0
        return self._request(
            f"/docs/refresh?{query}", method="POST", payload={}, timeout=timeout
        )

    def refresh_unreal_reflection(self, timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        query = urllib.parse.urlencode({"timeout": float(timeout or 60.0)})
        return self._request(
            f"/reflection/refresh?{query}",
            method="POST",
            payload={},
            timeout=max(10.0, float(timeout or 60.0) + 10.0),
        )

    def search_unreal_capabilities(self, query: str, limit: int = 20) -> Optional[Dict[str, Any]]:
        params = urllib.parse.urlencode({"q": query or "", "limit": int(limit or 20)})
        return self._request(f"/capabilities/search?{params}", timeout=5.0)

    def resolve_unreal_capability(self, request: str) -> Optional[Dict[str, Any]]:
        params = urllib.parse.urlencode({"q": request or ""})
        return self._request(f"/capabilities/resolve-intent?{params}", timeout=5.0)

    def validate_unreal_capability(
        self, name: str, payload: dict[str, Any] | None = None
    ) -> Optional[Dict[str, Any]]:
        return self._request(
            "/capabilities/validate",
            method="POST",
            payload={"name": name, "payload": payload or {}},
            timeout=5.0,
        )

    def execute_unreal_capability(
        self,
        request: str,
        payload: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        return self._request(
            "/capabilities/execute",
            method="POST",
            payload={
                "request": request,
                "payload": payload or {},
                "dry_run": bool(dry_run),
                "timeout": float(timeout or 30.0),
            },
            timeout=max(10.0, float(timeout or 30.0) + 10.0),
        )

    def start_daemon(self, project_root: str) -> Tuple[bool, str]:
        if self.is_daemon_running():
            return True, "Daemon already running"

        daemon_script = (
            Path(__file__).resolve().parent.parent
            / "bridges"
            / "unreal"
            / "project_intelligence_daemon.py"
        )
        if not daemon_script.exists():
            return False, f"Daemon script not found at {daemon_script}"

        try:
            project_root = str(Path(project_root).expanduser().resolve())
            self.project_root = project_root
            cmd = [
                sys.executable,
                str(daemon_script),
                "--root",
                project_root,
                "--port",
                str(self.port),
            ]
            startupinfo = None
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            package_root = daemon_script.parents[2]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(package_root) + os.pathsep + env.get("PYTHONPATH", "")

            self._process = subprocess.Popen(
                cmd,
                cwd=str(package_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
                close_fds=True,
                env=env,
            )

            for _ in range(14):
                time.sleep(0.25)
                if self.is_daemon_running():
                    return True, "Daemon started successfully"
                if self._process.poll() is not None:
                    break
            return (
                False,
                self._last_error
                or "Daemon process spawned but did not respond to status check",
            )
        except Exception as e:
            self._last_error = str(e)
            return False, f"Failed to start daemon process: {str(e)}"

    def stop_daemon(self) -> bool:
        data = self._request("/shutdown", method="POST", payload={}, timeout=1.5)
        if data and data.get("success"):
            self._process = None
            return True

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
                self._process = None
                return True
            except Exception:
                pass
        return False

    def trigger_scan(self, mode: str = "quick") -> Tuple[bool, int | Dict[str, Any]]:
        mode = mode if mode in {"quick", "standard", "deep", "reindex"} else "quick"
        timeout = 60.0 if mode in {"deep", "reindex"} else 10.0
        data = self._request(
            f"/scan?mode={urllib.parse.quote(mode)}",
            method="POST",
            payload={},
            timeout=timeout,
        )
        if data:
            if "scan" in data:
                return data.get("success", False), data.get("scan", {})
            return data.get("success", False), data.get("indexed", 0)
        return False, {"error": self._last_error} if self._last_error else 0

    def get_context(
        self, prompt: str = "", mode: str = "quick", max_tokens: int = 8000, project_root: str | None = None
    ) -> Optional[Dict[str, Any]]:
        mode = mode if mode in {"quick", "standard", "deep"} else "quick"
        root = project_root or self.project_root
        ok, _message = self.ensure_running(root)
        if not ok:
            try:
                self.ingest_unreal_if_connected(root, mode="quick")
            except Exception:
                pass
            return None
        payload = {
            "prompt": prompt or "unreal project context",
            "mode": mode,
            "max_tokens": int(max_tokens or 8000),
        }
        return self._request(
            f"/context?mode={urllib.parse.quote(mode)}",
            method="POST",
            payload=payload,
            timeout=12.0 if mode != "deep" else 90.0,
        )


# --- Project Edit Target Discovery (merged from project_edit_target_service.py) ---

TARGET_STOPWORDS = {
    "a", "an", "and", "add", "ask", "build", "can", "code", "create",
    "file", "files", "find", "for", "function", "functions", "give", "have",
    "i", "in", "into", "it", "me", "my", "of", "or", "please", "project",
    "should", "that", "the", "this", "to", "use", "where", "with", "you",
    "are", "during", "more", "not", "says", "still", "when", "while", "why",
}

DOMAIN_SYNONYMS = {
    "rig": ["rig", "rigging", "skeleton", "joint", "control", "ik", "fk"],
    "rigging": ["rig", "rigging", "skeleton", "joint", "control", "ik", "fk"],
    "ik": ["ik", "inverse_kinematics", "ikfk", "ik_fk", "limb"],
    "fk": ["fk", "forward_kinematics", "ikfk", "ik_fk", "limb"],
    "limb": ["limb", "arm", "leg", "joint", "chain", "ik", "fk"],
    "unreal": ["unreal", "blueprint", "asset", "editor", "ue"],
    "maya": ["maya", "cmds", "pymel", "rig", "joint", "control"],
    "dialog": ["dialog", "qdialog", "qfiledialog", "messagebox", "popup"],
    "widget": ["widget", "qwidget", "qt", "pyside", "layout"],
}

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

TARGET_SUBSYSTEM_HINTS = (
    {
        "key": "indexing_status",
        "triggers": ("index", "indexing", "knowledge", "stale", "ready", "bootstrap", "progress"),
        "terms": ("knowledge", "index", "indexing", "background", "progress", "status", "stale", "ready", "sync"),
        "paths": (
            "services/knowledge_background_service.py",
            "services/project_service.py",
            "app/main_window_core.py",
            "app/main_window.py",
        ),
    },
    {
        "key": "ui_responsiveness",
        "triggers": (
            "freeze",
            "freezes",
            "hang",
            "hung",
            "responsive",
            "responsiveness",
            "main thread",
            "main-thread",
            "long prompt",
            "watchdog",
            "streaming",
        ),
        "terms": (
            "prompt",
            "dispatch",
            "worker",
            "thread",
            "background",
            "watchdog",
            "streaming",
            "progress",
            "responsiveness",
        ),
        "paths": (
            "app/main_window_chat_runtime.py",
            "services/prompt_dispatch_service.py",
            "services/prompt_progress_service.py",
            "tests/test_long_prompt_responsiveness.py",
        ),
    },
    {
        "key": "patch_parser",
        "triggers": ("xml patch", "xml patches", "patch parser", "parser", "modify_file", "create_file", "actionable"),
        "terms": ("patch", "patches", "xml", "parser", "modify_file", "create_file", "actionable", "preview"),
        "paths": (
            "services/project_edit_agent_service.py",
            "knowledge/search.py",
        ),
    },
    {
        "key": "pipeline_graph",
        "triggers": (
            "pipeline",
            "node graph",
            "node view",
            "add and connect",
            "right click",
            "right-click",
            "compile button",
            "required inputs",
            "connections",
            "nodes",
        ),
        "terms": (
            "pipeline",
            "node",
            "graph",
            "compile",
            "filter",
            "search",
            "required",
            "inputs",
            "connections",
        ),
        "paths": (
            "ui/pipeline_node_view.py",
            "ui/node_search_dialog.py",
            "ui/pipeline_attribute_editor.py",
            "services/pipeline_graph_intelligence_service.py",
            "services/workflow_service.py",
        ),
    },
    {
        "key": "maya_rigging_code",
        "triggers": (
            "maya rigging",
            "rigging functions",
            "rigging function",
            "create rig",
            "full rig",
        ),
        "terms": (
            "maya",
            "rigging",
            "create_rig",
            "hik",
            "joint",
            "skeleton",
            "control",
            "ik",
            "fk",
            "validation",
        ),
        "paths": (
            "../../maya_tools/Rigging/create_rig.py",
            "../../maya_tools/Rigging/mocap/hik_ui.py",
        ),
    },
    {
        "key": "maya_ui_wrapper",
        "triggers": (
            "maya ui",
            "maya window",
            "maya tool",
            "maya tools",
            "tools menu",
            "typed controls",
            "duplicate window",
        ),
        "terms": (
            "maya",
            "rigging",
            "create_rig",
            "hik",
            "ui",
            "window",
            "menu",
            "pyside",
            "qt",
            "validation",
        ),
        "paths": (
            "../../maya_tools/Rigging/create_rig.py",
            "../../maya_tools/Rigging/mocap/hik_ui.py",
            "../../custom_qt/custom_widgets.py",
        ),
    },
    {
        "key": "adaptive_code_agent",
        "triggers": (
            "adaptive",
            "code-agent",
            "code agent",
            "agent planning",
            "project edit",
            "success contract",
            "ide agent",
            "repo map",
            "symbol lookup",
            "structured patching",
        ),
        "terms": ("adaptive", "code", "agent", "planning", "project", "edit", "intelligence", "validation", "repo", "symbol", "patch"),
        "paths": (
            "services/project_edit_agent_service.py",
            "services/code_intelligence_service.py",
            "services/repo_map_service.py",
            "services/validation_planner_service.py",
            "services/domain_expert_service.py",
        ),
    },
    {
        "key": "unreal_graph",
        "triggers": ("unreal graph", "blueprint graph", "graph rollback", "semantic graph", "graph mutation"),
        "terms": ("unreal", "blueprint", "graph", "semantic", "rollback", "validation", "mutation"),
        "paths": (
            "services/unreal/semantic_graph_service.py",
            "services/unreal/graph_patch_service.py",
            "services/unreal/graph_edit_intelligence_service.py",
            "services/unreal/capability_graph_service.py",
        ),
    },
    {
        "key": "chat_history",
        "triggers": ("chat history", "history files", "old thread", "thread disappears", "switch chat", "switching chats"),
        "terms": ("chat", "history", "thread", "conversation", "restore", "state", "messages"),
        "paths": (
            "app/main_window_history_assets.py",
            "app/main_window_chat_runtime.py",
            "services/chat_continuation_service.py",
            "ui/chat_renderer.py",
        ),
    },
    {
        "key": "mobile_jobs",
        "triggers": ("mobile app", "mobile", "jobs", "output logs", "job logs", "pipeline progress", "pairing"),
        "terms": ("mobile", "job", "jobs", "logs", "output", "pipeline", "progress", "pairing"),
        "paths": (
            "services/mobile_app_service.py",
            "services/remote_control_service.py",
            "services/job_log_service.py",
            "services/workflow_service.py",
            "app/main_window_workflows.py",
        ),
    },
    {
        "key": "theme_status",
        "triggers": ("status panel", "status bar", "status colors", "theme", "tech connector theme", "colors"),
        "terms": ("status", "panel", "bar", "theme", "style", "colors", "branding", "tech", "connector"),
        "paths": (
            "ui/status_panel.py",
            "ui/status_bar.py",
            "ui/branding.py",
            "models/constants.py",
        ),
    },
    {
        "key": "report_quality",
        "triggers": ("error reporting", "reporting quality", "documentation", "files changed", "rollback status", "validation warnings"),
        "terms": ("report", "reporting", "error", "documentation", "validation", "warnings", "rollback", "files", "changed"),
        "paths": (
            "services/chat_report_service.py",
            "ui/chat_renderer.py",
            "services/prompt_progress_service.py",
            "tests/test_chat_report_quality.py",
        ),
    },
)


TARGET_CONSTRAINT_PATTERNS = (
    r"\bdo not route\b.*$",
    r"\bdon't route\b.*$",
    r"\bdont route\b.*$",
    r"\bonly modify\b.*$",
    r"\bdo not modify\b.*$",
    r"\bdon't modify\b.*$",
    r"\bdont modify\b.*$",
    r"\bstop (?:immediately )?(?:after|once|when)\b.*$",
    r"\breport (?:exactly|only)\b.*$",
    r"\bdo not (?:execute|run|use|search)\b.*$",
)


def _target_discovery_text(text: str) -> str:
    """Return semantic target evidence without execution/scope instructions.

    The canonical request understanding preserves grammatical roles. For
    example, in "make a helper to find joints", ``find`` describes the helper
    behavior and is not treated as the governing search intent.
    """
    semantic_parts: list[str] = []
    try:
        from services.prompt_intent_service import understand_prompt_request

        understanding = understand_prompt_request(text, allow_model=False)
        semantic_parts.extend([
            understanding.target_file,
            understanding.target_symbol,
            understanding.requested_artifact,
            understanding.behavior_description,
        ])
    except Exception:
        pass
    lines: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if any(re.search(pattern, lower) for pattern in TARGET_CONSTRAINT_PATTERNS):
            continue
        lines.append(line)
    compact = " ".join(part for part in semantic_parts + lines if part)
    # Keep exact file and symbol phrases intact, but strip common request framing.
    compact = re.sub(
        r"\b(?:please|before creating anything|before writing any code|search that file for|search for|find an|find a)\b",
        " ",
        compact,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", compact).strip()


def _terms(text: str, limit: int = 24) -> list[str]:
    search_text = _target_discovery_text(text)
    raw = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", search_text)
    terms: list[str] = []
    for token in raw:
        low = token.lower()
        if len(low) < 3 or low in TARGET_STOPWORDS:
            continue
        if low not in terms:
            terms.append(low)
        for syn in DOMAIN_SYNONYMS.get(low, []):
            if syn not in terms:
                terms.append(syn)
    return terms[:limit]


def _target_subsystem_hints(text: str) -> list[dict[str, Any]]:
    lower = (text or "").lower()
    return [
        hint for hint in TARGET_SUBSYSTEM_HINTS
        if any(_target_trigger_matches(lower, str(trigger)) for trigger in hint["triggers"])
    ]


def _target_trigger_matches(lower: str, trigger: str) -> bool:
    trigger = (trigger or "").lower().strip()
    if not trigger:
        return False
    if " " in trigger or "-" in trigger:
        return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(trigger)}(?![A-Za-z0-9_])", lower))
    return bool(re.search(rf"\b{re.escape(trigger)}\b", lower))


def _extend_terms_for_subsystems(terms: list[str], hints: list[dict[str, Any]], limit: int = 32) -> list[str]:
    expanded = list(terms)
    for hint in hints:
        for term in hint.get("terms") or ():
            if term not in expanded:
                expanded.append(term)
    return expanded[:limit]


def _resolve_hint_path(path_text: str) -> str:
    path = Path(path_text)
    if not path.is_absolute():
        path = (_PACKAGE_ROOT / path_text).resolve()
    return str(path)


def _subsystem_hint_score(path: str, hints: list[dict[str, Any]]) -> int:
    normalized = str(path or "").replace("\\", "/").lower()
    score = 0
    for hint in hints:
        for hint_path in hint.get("paths") or ():
            resolved = _resolve_hint_path(str(hint_path)).replace("\\", "/").lower()
            if normalized == resolved:
                score += 80
            elif resolved and (resolved in normalized or normalized.endswith(resolved.split("/")[-1])):
                score += 25
    return score


def _active_path_matches_terms(active_path: str | None, terms: list[str], hints: list[dict[str, Any]]) -> bool:
    if not active_path:
        return False
    normalized = str(active_path).replace("\\", "/").lower()
    if _subsystem_hint_score(normalized, hints) > 0:
        return True
    meaningful = [term for term in terms if len(term) >= 4]
    return sum(1 for term in meaningful if term in normalized) >= 2


def is_target_discovery_edit_request(text: str) -> bool:
    """True when a prompt asks the system to locate the right file and edit/add there."""
    lower = (text or "").lower()
    wants_target = bool(
        re.search(r"\b(find|locate|choose|pick|identify|where|best place)\b", lower)
        and re.search(r"\b(file|module|place|location|where)\b", lower)
    )
    wants_change = bool(
        re.search(r"\b(add|create|write|generate|implement|insert|modify|improve|refactor|fix|update)\b", lower)
    )
    names_project_object = bool(
        re.search(r"\b(project|repo|codebase|tool|function|class|method|module|file|existing|current|ui|pipeline|workflow|editor|service|bridge)\b", lower)
    )
    mentions_existing_code = bool(
        re.search(r"\b(in|inside|to|for)\s+(?:our|the|this|my)?\s*[A-Za-z_][A-Za-z0-9_./\\-]*\.py\b", text or "")
        or re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", text or "")
    )
    return wants_change and (wants_target or names_project_object or mentions_existing_code)


def _path_score(path: str, terms: list[str], active_path: str | None = None) -> int:
    p = str(path or "").replace("\\", "/").lower()
    name = Path(p).name.lower()
    score = 0
    for term in terms:
        if term in name:
            score += 12
        if term in p:
            score += 5
    if active_path:
        try:
            active_parent = str(Path(active_path).resolve().parent).replace("\\", "/").lower()
            if active_parent and p.startswith(active_parent):
                score += 8
        except Exception:
            pass
    if any(marker in p for marker in ("test", "example", "archive", "backup", "deprecated")):
        score -= 10
    if p.endswith("__init__.py"):
        score -= 15
    return score


def _add_hint_candidates(file_scores: dict[str, dict[str, Any]], hints: list[dict[str, Any]]) -> None:
    for hint in hints:
        for hint_path in hint.get("paths") or ():
            path = _resolve_hint_path(str(hint_path))
            if not Path(path).exists():
                continue
            if not _is_project_edit_candidate_path(path):
                continue
            entry = file_scores.setdefault(path, {"path": path, "score": 0, "symbols": [], "chunks": []})
            entry["score"] += _subsystem_hint_score(path, [hint])


def _is_project_edit_candidate_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    if not normalized:
        return False
    excluded_parts = (
        "/.venv/",
        "/venv/",
        "/site-packages/",
        "/dist-packages/",
        ".dist-info/",
        "/__pycache__/",
        "/.git/",
        "/.mypy_cache/",
        "/.pytest_cache/",
    )
    return not any(part in normalized for part in excluded_parts)


def _path_allowed_for_edit_scope(path: str, scope: str | None) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    scope_text = (scope or "").lower()
    if scope_text in {"unreal_project", "project_unreal", "host_unreal"}:
        return any(
            marker in normalized
            for marker in (
                "/unreal",
                "unreal_",
                "/services/unreal/",
                "/bridges/unreal/",
                "/dcc_intelligence/unreal",
                "/project_analysis/unreal",
            )
        )
    if scope_text in {"maya_project", "project_maya", "host_maya"}:
        return any(
            marker in normalized
            for marker in (
                "/maya",
                "maya_",
                "/services/maya",
                "/bridges/maya",
                "/dcc_intelligence/maya",
            )
        )
    return True


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for row in rows:
        key = (row.get("path"), row.get("name"), row.get("qualname"), row.get("start_line"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def discover_edit_targets(
    question: str,
    active_path: str | None = None,
    limit: int = 8,
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    """Return ranked files/symbols that look like appropriate edit targets."""
    from services.project_search_service import _active_project_roots, detect_search_scope
    from knowledge.search import search_index_symbols, search_index_chunks

    hints = _target_subsystem_hints(question)
    terms = _extend_terms_for_subsystems(_terms(question), hints)
    scope = scope or detect_search_scope(question)
    roots = _active_project_roots(active_path)
    effective_active_path = active_path
    if active_path and scope in {"maya_project", "project_maya", "host_maya", "unreal_project", "project_unreal", "host_unreal"}:
        if not _path_allowed_for_edit_scope(active_path, scope):
            effective_active_path = None
    if effective_active_path and hints and not _active_path_matches_terms(effective_active_path, terms, hints):
        effective_active_path = None

    symbol_rows: list[dict[str, Any]] = []
    chunk_rows: list[dict[str, Any]] = []

    if terms:
        symbol_rows = search_index_symbols(
            terms,
            limit=max(limit * 4, 24),
            active_path=effective_active_path,
            class_bias=False,
            scope=scope,
            project_roots=roots,
        )
        chunk_rows = search_index_chunks(
            terms,
            limit=max(limit * 3, 18),
            active_path=effective_active_path,
            scope=scope,
            project_roots=roots,
        )

    symbol_rows = _dedupe_rows(symbol_rows)

    file_scores: dict[str, dict[str, Any]] = {}
    _add_hint_candidates(file_scores, hints)
    for row in symbol_rows:
        path = row.get("path") or ""
        if not path or not _is_project_edit_candidate_path(path) or not _path_allowed_for_edit_scope(path, scope):
            continue
        entry = file_scores.setdefault(path, {"path": path, "score": 0, "symbols": [], "chunks": []})
        entry["score"] += _path_score(path, terms, effective_active_path)
        entry["score"] += _subsystem_hint_score(path, hints)
        entry["score"] += 8
        src = (row.get("source") or "").lower()
        for term in terms:
            if term in src:
                entry["score"] += 2
        entry["symbols"].append(row)

    for row in chunk_rows:
        path = row.get("path") or ""
        if not path or not _is_project_edit_candidate_path(path) or not _path_allowed_for_edit_scope(path, scope):
            continue
        entry = file_scores.setdefault(path, {"path": path, "score": 0, "symbols": [], "chunks": []})
        entry["score"] += _path_score(path, terms, effective_active_path)
        entry["score"] += _subsystem_hint_score(path, hints)
        entry["score"] += 4
        text = (row.get("text") or "").lower()
        for term in terms:
            if term in text:
                entry["score"] += 1
        entry["chunks"].append(row)

    ranked = sorted(file_scores.values(), key=lambda item: item["score"], reverse=True)[:limit]
    best = ranked[0] if ranked else None
    confidence = "none"
    if best:
        if best["score"] >= 30:
            confidence = "high"
        elif best["score"] >= 14:
            confidence = "medium"
        else:
            confidence = "low"

    return {
        "question": question,
        "terms": terms,
        "scope": scope,
        "project_roots": roots,
        "active_path": active_path,
        "best_target": best,
        "candidates": ranked,
        "confidence": confidence,
    }


def format_edit_target_context(discovery: dict[str, Any], max_source_lines: int = 45) -> str:
    roots = discovery.get("project_roots") or []
    best = discovery.get("best_target") or {}
    lines = [
        "Project edit target discovery:",
        f"Scope: {discovery.get('scope')}",
        f"Project roots: {', '.join(str(root) for root in roots) or '(unknown)'}",
        f"Active file: {discovery.get('active_path') or '(none)'}",
        f"Terms: {', '.join(discovery.get('terms') or []) or '(none)'}",
        f"Confidence: {discovery.get('confidence')}",
        f"Best target: {best.get('path') or '(none)'}",
        "",
    ]
    candidates = [
        item for item in (discovery.get("candidates") or [])
        if _is_project_edit_candidate_path(str(item.get("path") or ""))
    ]
    if not candidates:
        lines.append("No strong target files were found in the index. The model should ask for confirmation before creating a new file.")
        return "\n".join(lines)

    lines.append("Ranked target files:")
    for idx, item in enumerate(candidates, start=1):
        lines.append(f"[{idx}] {item.get('path')}  score={item.get('score')}")
        symbols = item.get("symbols") or []
        if symbols:
            lines.append("Relevant symbols:")
        for sym in symbols[:5]:
            src = sym.get("source") or ""
            src_lines = src.splitlines()
            if len(src_lines) > max_source_lines:
                src = "\n".join(src_lines[:max_source_lines]) + "\n... [truncated] ..."
            lines.append(
                f"- {sym.get('kind')} {sym.get('qualname') or sym.get('name')} "
                f"lines {sym.get('start_line')}-{sym.get('end_line')}"
            )
            if src:
                lines.append(f"```python\n{src}\n```")
        chunks = item.get("chunks") or []
        if chunks and not symbols:
            preview = (chunks[0].get("text") or "")[:1400]
            lines.append(f"Relevant file text preview:\n```text\n{preview}\n```")
        lines.append("")
    return "\n".join(lines)


def build_project_understanding_contract(
    question: str,
    discovery_context: str,
    active_path: str | None = None,
) -> str:
    """Build the grounding contract for project-aware code generation."""

    confidence = "unknown"
    scope = "unknown"
    project_roots = "(unknown)"
    best_target = "(none)"
    for line in (discovery_context or "").splitlines():
        if line.startswith("Confidence:"):
            confidence = line.split(":", 1)[1].strip() or confidence
        elif line.startswith("Scope:"):
            scope = line.split(":", 1)[1].strip() or scope
        elif line.startswith("Project roots:"):
            project_roots = line.split(":", 1)[1].strip() or project_roots
        elif line.startswith("Best target:"):
            best_target = line.split(":", 1)[1].strip() or best_target

    return f"""Project understanding contract:
- Assigned project roots: {project_roots}
- Active file: {active_path or '(none)'}
- Search scope: {scope}
- Target confidence: {confidence}
- Best indexed target: {best_target}
- Treat the indexed files, symbols, signatures, docstrings, source excerpts, and line numbers as the source of truth.
- Do not invent files, classes, functions, imports, arguments, call sites, or APIs that are not present in the evidence.
- Before generating code, explain which indexed file/symbol evidence is being used and why it matches the user's request.
- If the target confidence is low or no best target exists, ask for confirmation before creating or editing files.
- Before editing an existing file, function, class, or import path, verify that the target exists in the indexed evidence.
- If the requested target does not exist, do not fabricate it directly: explain how to create it, how it would be implemented, where it belongs, what existing patterns it should reuse, and ask for approval before emitting a create-file or create-symbol patch.
- If editing an existing function/class, preserve its public API unless the user explicitly asked to change it.
- If adding code, update required imports, references, call sites, UI signal wiring, and exports that are shown by the evidence.
- Prefer project-local helpers and patterns over generic examples.
- Produce code as a patch against exact original blocks, not a detached snippet, when changing existing files.
- Include verification that fits the assigned project, such as py_compile, focused unit tests, UI smoke checks, or DCC/host validation.
- Report unresolved assumptions separately from confirmed project facts.
"""


def build_project_edit_target_prompt(question: str, discovery_context: str, active_path: str | None = None) -> str:
    understanding_contract = build_project_understanding_contract(
        question=question,
        discovery_context=discovery_context,
        active_path=active_path,
    )
    return f"""You are assisting inside The Entire World Tech Connector with a project-wide edit request.

User request:
{question}

Active file, if relevant:
{active_path or '(none)'}

Target-discovery evidence:
{discovery_context[:18000]}

{understanding_contract}

Instructions:
- First decide whether the top ranked target file is a safe place to edit.
- If confidence is high or medium, propose edits against that existing file.
- If confidence is low or the requested file/function/class does not exist, provide a creation plan and implementation plan first; ask for approval before creating a new file or new symbol.
- Preserve imports and public API unless the request requires changing them.
- If adding a new function/class, include any imports needed.
- If modifying behavior, identify affected call sites or explain that the indexed evidence did not show any.
- Keep the change functional and testable.
- Match the style and architecture of the indexed target file.
- Use existing project helpers before writing new abstractions.
- For Python edits, output XML patch tags when changing files:
  <modify_file path="absolute/or/relative/path.py">
  <<<< ORIGINAL
  exact original block
  ====
  replacement block
  >>>>
  </modify_file>
- For new files only when clearly needed:
  <create_file path="relative/path.py">
  full file content
  </create_file>
- Include a short verification command or manual test tied to the assigned project.

Response format:
1. Project facts used.
2. Target file/symbol decision with confidence.
3. Implementation plan.
4. Patch or exact code change.
5. Verification command or manual validation.
6. Assumptions, risks, or missing evidence.
"""
