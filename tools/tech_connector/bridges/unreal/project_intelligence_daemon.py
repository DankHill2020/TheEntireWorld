# project_intelligence_daemon.py
"""Background daemon for Unreal Project Intelligence.

Watches the active project directory for file modifications to trigger
incremental indexing, polls Unreal for live state, and exposes a micro-HTTP API
for the main UI.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote_plus, urlparse

_ROOT = next(
    candidate
    for candidate in pathlib.Path(__file__).resolve().parents
    if candidate.name.lower() == "tools"
)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tech_connector.bridges.unreal.index_worker import _connect, index_asset, reindex_all
from tech_connector.bridges.unreal.unreal_api_docs import UnrealApiDocsCache
from tech_connector.bridges.unreal.unreal_scanner import UnrealScanner

try:
    from tech_connector.bridges.unreal.unreal_intelligence import build_context as build_local_context
    from tech_connector.bridges.unreal.unreal_intelligence import ingest_scan as ingest_unreal_scan
    from tech_connector.bridges.unreal.unreal_intelligence import (
        lookup_symbols as lookup_unreal_symbols,
    )
    from tech_connector.bridges.unreal.unreal_intelligence import status as local_intelligence_status
except Exception:
    build_local_context = None
    ingest_unreal_scan = None
    lookup_unreal_symbols = None
    local_intelligence_status = None

try:
    from tech_connector.services.unreal.capability_graph_service import (
        execute_unreal_capability,
        resolve_unreal_graph_item,
        resolve_unreal_capability,
        search_unreal_capability_graph,
        sync_unreal_capability_graph,
        validate_unreal_graph_call,
    )
except Exception:
    execute_unreal_capability = None
    resolve_unreal_graph_item = None
    resolve_unreal_capability = None
    search_unreal_capability_graph = None
    sync_unreal_capability_graph = None
    validate_unreal_graph_call = None

try:
    from tech_connector.services.unreal.reflection_indexer import refresh_unreal_reflection_index
except Exception:
    refresh_unreal_reflection_index = None

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


class AssetChangeHandler:
    def __init__(self, callback):
        self.callback = callback

    def on_modified(self, path: str):
        if path.endswith(".uasset") or path.endswith(".umap"):
            self.callback(path)


if HAS_WATCHDOG:

    class WatchdogEventHandler(FileSystemEventHandler):
        def __init__(self, handler: AssetChangeHandler):
            self.handler = handler

        def on_modified(self, event):
            if not event.is_directory:
                self.handler.on_modified(event.src_path)

        def on_created(self, event):
            if not event.is_directory:
                self.handler.on_modified(event.src_path)


class FallbackDirectoryWatcher:
    def __init__(self, root_dir: str, callback, interval: float = 5.0):
        self.root_dir = root_dir
        self.callback = callback
        self.interval = interval
        self.last_mtimes: Dict[str, float] = {}
        self.running = False
        self._thread = None

    def start(self):
        self.running = True
        self.last_mtimes = self._scan_mtimes()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _scan_mtimes(self) -> Dict[str, float]:
        mtimes = {}
        skip_dirs = {
            ".git",
            "Intermediate",
            "Saved",
            "DerivedDataCache",
            "Binaries",
            ".ai_studio",
        }
        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                if f.endswith(".uasset") or f.endswith(".umap"):
                    path = os.path.join(root, f)
                    try:
                        mtimes[path] = os.path.getmtime(path)
                    except Exception:
                        pass
        return mtimes

    def _run(self):
        while self.running:
            time.sleep(self.interval)
            try:
                current = self._scan_mtimes()
                for path, mtime in current.items():
                    if path not in self.last_mtimes or self.last_mtimes[path] != mtime:
                        self.callback(path)
                self.last_mtimes = current
            except Exception:
                pass


class DaemonState:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.indexed_count = 0
        self.last_scan_time = 0.0
        self.unreal_connected = False
        self.watcher_type = "watchdog" if HAS_WATCHDOG else "polling"
        self.db_path = ""
        self.last_health_check: Dict[str, Any] = {}
        self.last_context_packet: Dict[str, Any] = {}
        self.current_operation = "idle"
        self.last_cache_update = None
        self.update_indexed_count()

    def update_indexed_count(self):
        try:
            conn = _connect()
            cur = conn.execute("SELECT COUNT(*) FROM assets")
            self.indexed_count = cur.fetchone()[0]
            conn.close()
            from tech_connector.bridges.unreal.index_worker import _get_db_path

            self.db_path = str(_get_db_path())
            self.last_cache_update = time.time()
        except Exception:
            self.indexed_count = 0


class DaemonHTTPHandler(BaseHTTPRequestHandler):
    state: DaemonState = None
    scanner: UnrealScanner = None
    server_instance: HTTPServer = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/status":
            health = self.scanner.health_summary(timeout=1.0)
            self.state.unreal_connected = bool(health.get("ok"))
            self.state.last_health_check = health
            self.state.update_indexed_count()

            intelligence = {}
            if local_intelligence_status:
                try:
                    intelligence = local_intelligence_status(self.state.project_root)
                except Exception as e:
                    intelligence = {"error": str(e)}

            payload = {
                "status": "running",
                "watcher_type": self.state.watcher_type,
                "project_root": self.state.project_root,
                "db_path": self.state.db_path,
                "indexed_assets": self.state.indexed_count,
                "unreal_connected": self.state.unreal_connected,
                "unreal_health": health,
                "last_health_check": self.state.last_health_check,
                "last_scan_time": self.state.last_scan_time,
                "last_cache_update": self.state.last_cache_update,
                "current_operation": self.state.current_operation,
                "last_context_packet": self.state.last_context_packet,
                "local_intelligence": intelligence,
            }
            self._send_json(payload)
        elif path == "/health":
            health = self.scanner.health_summary(timeout=1.5)
            self.state.last_health_check = health
            self._send_json(
                {
                    "success": True,
                    "health": health,
                    "last_request": self.scanner.bridge.get_last_request_status(),
                }
            )
        elif path == "/context":
            prompt = unquote_plus(
                (query.get("prompt") or ["unreal project context"])[0]
            )
            mode = (query.get("mode") or ["quick"])[0]
            self._send_context(prompt, mode, max_tokens=8000)
        elif path == "/symbols":
            q = unquote_plus((query.get("q") or query.get("prefix") or [""])[0])
            exact = str((query.get("exact") or ["false"])[0]).lower() in {
                "1",
                "true",
                "yes",
            }
            limit_raw = (query.get("limit") or ["20"])[0]
            try:
                limit = max(1, min(100, int(limit_raw)))
            except Exception:
                limit = 20
            if not lookup_unreal_symbols:
                self._send_json(
                    {"success": False, "error": "local symbol lookup unavailable"},
                    status=503,
                )
                return
            self._send_json(
                {
                    "success": True,
                    "query": q,
                    "prefix": not exact,
                    "symbols": lookup_unreal_symbols(
                        q, self.state.project_root, prefix=not exact, limit=limit
                    ),
                }
            )
        elif path in {"/capabilities/search", "/functions/search"}:
            q = unquote_plus((query.get("q") or query.get("query") or [""])[0])
            limit_raw = (query.get("limit") or ["20"])[0]
            try:
                limit = max(1, min(100, int(limit_raw)))
            except Exception:
                limit = 20
            if not search_unreal_capability_graph:
                self._send_json(
                    {"success": False, "error": "capability graph lookup unavailable"},
                    status=503,
                )
                return
            result = search_unreal_capability_graph(
                q, self.state.project_root, limit=limit
            )
            if path == "/functions/search":
                result = {
                    "success": result.get("success", False),
                    "query": result.get("query", q),
                    "project_id": result.get("project_id"),
                    "functions": result.get("functions", []),
                    "python_api": result.get("python_api", []),
                    "symbols": [
                        item for item in result.get("symbols", [])
                        if item.get("symbol_kind") in {"function", "operation", "python_api", "capability"}
                    ],
                }
            self._send_json(result)
        elif path in {"/capabilities/resolve", "/functions/resolve"}:
            name = unquote_plus((query.get("name") or query.get("q") or [""])[0])
            if not name:
                self._send_json(
                    {"success": False, "error": "Missing name query parameter"},
                    status=400,
                )
                return
            if not resolve_unreal_graph_item:
                self._send_json(
                    {"success": False, "error": "capability graph resolver unavailable"},
                    status=503,
                )
                return
            self._send_json(resolve_unreal_graph_item(name, self.state.project_root))
        elif path == "/capabilities/resolve-intent":
            request_text = unquote_plus(
                (query.get("q") or query.get("request") or [""])[0]
            )
            if not request_text:
                self._send_json(
                    {"success": False, "error": "Missing q or request query parameter"},
                    status=400,
                )
                return
            if not resolve_unreal_capability:
                self._send_json(
                    {"success": False, "error": "capability resolver unavailable"},
                    status=503,
                )
                return
            self._send_json(
                resolve_unreal_capability(request_text, self.state.project_root)
            )
        elif path == "/docs/status":
            version = (query.get("version") or ["5.8"])[0]
            self._send_json(
                {
                    "success": True,
                    "docs": UnrealApiDocsCache(
                        self.state.project_root, version=version
                    ).status(),
                }
            )
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/scan":
            mode = (query.get("mode") or ["quick"])[0]
            if mode not in {"quick", "standard", "deep", "reindex"}:
                mode = "quick"
            self.state.current_operation = f"scan:{mode}"
            if mode == "reindex":
                t0 = time.time()
                count = reindex_all(self.state.project_root)
                self.state.last_scan_time = time.time() - t0
                self.state.update_indexed_count()
                self.state.current_operation = "idle"
                self._send_json(
                    {
                        "success": True,
                        "mode": mode,
                        "indexed": count,
                        "duration_ms": round(self.state.last_scan_time * 1000, 2),
                    }
                )
                return
            scan = self.scanner.scan_all(mode=mode, force=mode == "deep")
            if ingest_unreal_scan:
                try:
                    ingest_unreal_scan(
                        scan.get("data") or scan, self.state.project_root
                    )
                except Exception:
                    pass
            self.state.last_scan_time = scan.get("duration_ms", 0) / 1000.0
            self.state.update_indexed_count()
            self.state.current_operation = "idle"
            self._send_json({"success": True, "scan": scan})
        elif path == "/snapshot":
            self.state.current_operation = "snapshot"
            try:
                index = self.scanner.scan_all(mode="standard")
                if ingest_unreal_scan:
                    ingest_unreal_scan(
                        index.get("data") or index, self.state.project_root
                    )
                self.state.update_indexed_count()
                self.state.current_operation = "idle"
                self._send_json({"success": True, "scan": index})
            except Exception as e:
                self.state.current_operation = "idle"
                self._send_json({"success": False, "error": str(e)}, status=500)
        elif path == "/context":
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                data = json.loads(body or "{}")
                request_text = (
                    data.get("request")
                    or data.get("prompt")
                    or "unreal project context"
                )
                mode = data.get("mode") or (query.get("mode") or ["quick"])[0]
                max_tokens = int(data.get("max_tokens") or 8000)
                self._send_context(request_text, mode, max_tokens=max_tokens)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=500)
        elif path == "/capabilities/sync":
            if not sync_unreal_capability_graph:
                self._send_json(
                    {"success": False, "error": "capability graph sync unavailable"},
                    status=503,
                )
                return
            try:
                self._send_json(sync_unreal_capability_graph(self.state.project_root))
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=500)
        elif path == "/reflection/refresh":
            if not refresh_unreal_reflection_index:
                self._send_json(
                    {"success": False, "error": "Unreal reflection indexer unavailable"},
                    status=503,
                )
                return
            try:
                timeout = float((query.get("timeout") or ["60"])[0])
            except Exception:
                timeout = 60.0
            self.state.current_operation = "reflection:refresh"
            try:
                result = refresh_unreal_reflection_index(
                    self.state.project_root, timeout=timeout
                )
                self.state.current_operation = "idle"
                self._send_json(result, status=200 if result.get("success") else 500)
            except Exception as e:
                self.state.current_operation = "idle"
                self._send_json({"success": False, "error": str(e)}, status=500)
        elif path in {"/capabilities/validate", "/functions/validate"}:
            if not validate_unreal_graph_call:
                self._send_json(
                    {"success": False, "error": "capability graph validation unavailable"},
                    status=503,
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                data = json.loads(body or "{}")
                name = data.get("name") or data.get("capability") or data.get("function") or ""
                if not name:
                    self._send_json(
                        {"success": False, "error": "Request body must include name, capability, or function"},
                        status=400,
                    )
                    return
                payload = data.get("payload") or data.get("params") or data.get("kwargs") or {}
                self._send_json(
                    validate_unreal_graph_call(
                        name,
                        payload if isinstance(payload, dict) else {},
                        self.state.project_root,
                    )
                )
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=500)
        elif path in {"/capabilities/execute", "/functions/execute"}:
            if not execute_unreal_capability:
                self._send_json(
                    {"success": False, "error": "capability execution unavailable"},
                    status=503,
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                data = json.loads(body or "{}")
                request_text = (
                    data.get("request")
                    or data.get("name")
                    or data.get("capability")
                    or data.get("function")
                    or ""
                )
                if not request_text:
                    self._send_json(
                        {"success": False, "error": "Request body must include request, name, capability, or function"},
                        status=400,
                    )
                    return
                payload = data.get("payload") or data.get("params") or data.get("kwargs") or {}
                dry_run = bool(data.get("dry_run", False))
                timeout = float(data.get("timeout") or 30.0)
                result = execute_unreal_capability(
                    request_text,
                    payload if isinstance(payload, dict) else {},
                    self.state.project_root,
                    timeout=timeout,
                    dry_run=dry_run,
                )
                self._send_json(result, status=200 if result.get("success") or dry_run else 400)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=500)
        elif path == "/docs/refresh":
            version = (query.get("version") or ["5.8"])[0]
            max_pages_raw = (query.get("max_pages") or ["0"])[0]
            force = str((query.get("force") or ["false"])[0]).lower() in {
                "1",
                "true",
                "yes",
            }
            try:
                max_pages = max(0, min(500, int(max_pages_raw)))
            except Exception:
                max_pages = 0
            try:
                result = UnrealApiDocsCache(
                    self.state.project_root, version=version
                ).refresh(max_pages=max_pages, force=force)
                self._send_json(
                    {"success": bool(result.get("success")), "docs": result}
                )
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, status=500)
        elif path == "/shutdown":
            self._send_json({"success": True, "message": "shutting down"})

            def shutdown_server():
                time.sleep(0.5)
                self.server_instance.shutdown()

            threading.Thread(target=shutdown_server, daemon=True).start()
        else:
            self.send_error(404)

    def _send_json(self, payload: Dict[str, Any], status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload, default=str).encode("utf-8"))

    def _send_context(
        self, request_text: str, mode: str = "quick", max_tokens: int = 8000
    ):
        mode = mode if mode in {"quick", "standard", "deep"} else "quick"
        self.state.current_operation = f"context:{mode}"
        scan = self.scanner.scan_all(mode=mode, force=mode == "deep")
        compact_context = self.scanner.build_unreal_context(
            request_text, max_tokens=max_tokens
        )
        context = self.scanner.build_context_summary()
        if build_local_context is not None:
            try:
                local_context = build_local_context(
                    request_text, self.state.project_root
                )
                if local_context:
                    context = context + "\n\n" + local_context
            except Exception:
                pass
        status = self.scanner.context_status(request_text, mode=mode)
        self.state.last_context_packet = compact_context
        self.state.current_operation = "idle"
        print(
            f"[UnrealContext] prompt_type=context project_intelligence_used=true "
            f"live_unreal={str(status['unreal_live_context']).lower()} "
            f"selected_assets={status['selected_assets']} selected_actors={status['selected_actors']}"
        )
        self._send_json(
            {
                "success": True,
                "context": context,
                "structured_context": compact_context,
                "status": status,
                "scan": scan,
            }
        )


def run_daemon(project_root: str, port: int):
    state = DaemonState(project_root)
    scanner = UnrealScanner(project_root)

    def on_file_changed(path: str):
        try:
            print(f"[Daemon] Change detected: {path}. Reindexing...")
            index_asset(path)
            state.update_indexed_count()
        except Exception as e:
            print(f"[Daemon Error] Failed to index {path}: {e}")

    change_handler = AssetChangeHandler(on_file_changed)

    watcher = None
    if HAS_WATCHDOG:
        print("[Daemon] Starting watchdog file watcher...")
        event_handler = WatchdogEventHandler(change_handler)
        observer = Observer()
        observer.schedule(event_handler, path=project_root, recursive=True)
        observer.start()
    else:
        print(
            "[Daemon] Watchdog missing. Starting fallback polling directory watcher..."
        )
        watcher = FallbackDirectoryWatcher(project_root, change_handler.on_modified)
        watcher.start()

    DaemonHTTPHandler.state = state
    DaemonHTTPHandler.scanner = scanner

    server = HTTPServer(("127.0.0.1", port), DaemonHTTPHandler)
    DaemonHTTPHandler.server_instance = server

    print(f"[Daemon] HTTP API Listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("[Daemon] Shutting down...")
        if HAS_WATCHDOG:
            observer.stop()
            observer.join()
        elif watcher:
            watcher.stop()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Unreal project intelligence daemon"
    )
    parser.add_argument("--root", required=True, help="Project root")
    parser.add_argument("--port", type=int, default=12349, help="HTTP port")
    args = parser.parse_args()
    run_daemon(args.root, args.port)
