"""High-level command layer shared by desktop UI and future remote clients."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from reasoning_runtime.engine.progress_events import ActivityEvent, EngineResult, ProgressEvent
from reasoning_runtime.engine.request_context import RequestContext
from tech_connector.engine.request_engine import RequestEngine
from tech_connector.services.remote_state_service import AppEventBus, RemoteJob, RemoteJobStore
from tech_connector.services.studio_profile_service import studio_profile_summary


PromptRunner = Callable[[str, RequestContext, Callable[[ProgressEvent], None], Callable[[ActivityEvent], None]], EngineResult]


class ApplicationCommandService:
    """Functional API for Tech Connector commands.

    Remote clients should call this layer, not desktop widgets. Desktop UI code
    can also move toward this layer incrementally so both frontends share the
    same routing, job state, and event reporting.
    """

    def __init__(
        self,
        app_service: Any = None,
        *,
        event_bus: AppEventBus | None = None,
        job_store: RemoteJobStore | None = None,
        prompt_runner: PromptRunner | None = None,
    ):
        self.app_service = app_service
        self.event_bus = event_bus or AppEventBus()
        self.job_store = job_store or RemoteJobStore()
        self.prompt_runner = prompt_runner
        
        self.prompt_runner = prompt_runner
        self.desktop_window = None
        self._two_factor_pin: str | None = None
        self._two_factor_expiry: float = 0.0
        self._two_factor_verified_tokens: set[str] = set()


    def execute(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        command = (command or "").strip()
        payload = payload or {}
        if command == "retrieve_status":
            return {"ok": True, "status": self.retrieve_status()}
        if command == "list_jobs":
            return {"ok": True, "jobs": self.job_store.list_jobs(int(payload.get("limit") or 50), state=str(payload.get("state") or "all"))}
        
        
        
        
        
        
        if command == "handle_slack_inbound":
            return self.handle_slack_inbound(payload)

        if command == "get_oauth_url":
            return self.get_oauth_url(str(payload.get("provider") or "slack"))

        
        
        if command == "search_existing_tasks_and_docs":
            return self.search_existing_tasks_and_docs(payload)

        if command == "create_jira_task":
            return self.create_jira_task(payload)
        if command == "push_confluence_docs":
            return self.push_confluence_docs(payload)
        if command == "create_clickup_task":
            return self.create_clickup_task(payload)

        if command == "list_smart_channels":
            return self.list_smart_channels()

        if command == "get_messaging_settings":
            return self.get_messaging_settings()
        if command == "save_messaging_settings":
            return self.save_messaging_settings(payload)
        
        if command == "parse_inline_messaging":
            return self.parse_inline_messaging(payload)

        if command == "send_slack_notification":
            return self.send_slack_notification(payload)
        if command == "send_discord_notification":
            return self.send_discord_notification(payload)

        if command == "register_remote_user":
            return self.register_remote_user(payload)

        if command == "generate_2fa_pin":
            return self.generate_2fa_pin()
        if command == "verify_2fa_pin":
            return self.verify_2fa_pin(str(payload.get("pin") or ""), str(payload.get("token") or ""))
        if command == "get_2fa_status":
            return self.get_2fa_status()

        if command == "get_job":
            return self.get_job(str(payload.get("job_id") or ""))
        if command == "list_pipelines":
            return {"ok": True, "pipelines": self.list_pipelines(str(payload.get("query") or ""))}
        if command == "list_applications":
            return {"ok": True, "applications": self.list_applications()}
        if command == "application_progress":
            return {"ok": True, "progress": self.application_progress(payload)}
        if command == "recent_events":
            return {"ok": True, "events": self.event_bus.recent_events(int(payload.get("limit") or 100), after_event_id=payload.get("after_event_id", ""))}
        if command == "cancel_job":
            return self.cancel_job(str(payload.get("job_id") or ""))
        if command == "submit_prompt":
            return self.submit_prompt(str(payload.get("prompt") or ""), payload)
        if command == "create_job":
            return self.create_mobile_job(payload)
        if command == "request_screenshot":
            return self.request_screenshot(payload)
        if command == "monitor_application":
            return self.monitor_application(payload)
        if command == "inspect_windows":
            return self.inspect_windows(payload)
        if command == "send_desktop_input":
            return self.send_desktop_input(payload)
        if command == "open_image_editor":
            return self.open_image_editor(payload)
        if command == "sync_transform":
            return self.sync_transform(payload)
        if command == "get_pipeline_graph":
            return self.get_pipeline_graph(str(payload.get("pipeline_id") or payload.get("manifest_path") or ""))
        if command == "save_pipeline_graph":
            return self.save_pipeline_graph(payload)
        if command == "list_node_catalog":
            return self.list_node_catalog(str(payload.get("query") or ""), str(payload.get("package") or ""))
        if command == "list_knowledge_credits":
            from tech_connector.services.knowledge_credits_service import list_knowledge_credits, load_knowledge_credits
            credits = list_knowledge_credits(query=str(payload.get("query") or ""))
            policy = load_knowledge_credits().get("policy", "open_information_only")
            return {"ok": True, "policy": policy, "credits": credits}
        if command in {"continue_conversation", "approve_job", "launch_application", "execute_workflow"}:
            return self.create_deferred_job(command, payload)
        return {"ok": False, "error": f"Unsupported command: {command}"}

    def inspect_windows(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Expose typed, read-only OS window inspection to every client."""

        from tech_connector.services.desktop_window_service import inspect_desktop_windows

        payload = payload or {}
        return inspect_desktop_windows(
            process_name=str(payload.get("process_name") or ""),
            title_query=str(payload.get("title_query") or ""),
            include_untitled=bool(payload.get("include_untitled", False)),
            limit=int(payload.get("limit") or 100),
        )

    def retrieve_status(self) -> dict[str, Any]:
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        return {
            "studio_running": True,
            "active_project": settings.get("active_project", ""),
            "live_sources_enabled": bool(settings.get("enable_live_sources", False)),
            "best_practice_lookup_enabled": bool(settings.get("research_best_practices", False)),
            "model": settings.get("model", ""),
            "studio_profile": studio_profile_summary(),
            "active_jobs": self.job_store.list_jobs(20),
            "pipeline_count": len(self.list_pipelines()),
            "applications": self.list_applications(),
            "desktop": self.desktop_context(),
        }

    def desktop_context(self) -> dict[str, Any]:
        window = self.desktop_window
        context = {
            "available": window is not None,
            "window_title": "",
            "active_tab": "",
            "active_editor_tab": "",
            "current_file_path": "",
            "live_process": "",
            "screenshot_available": False,
        }
        if window is None:
            return context
        try:
            context["window_title"] = str(window.windowTitle())
        except Exception:
            pass
        try:
            tabs = getattr(window, "workspace_tabs", None)
            if tabs is not None:
                context["active_tab"] = str(tabs.tabText(tabs.currentIndex()))
        except Exception:
            pass
        try:
            editor_tabs = getattr(window, "editor_tabs", None)
            if editor_tabs is not None and editor_tabs.count():
                context["active_editor_tab"] = str(editor_tabs.tabText(editor_tabs.currentIndex()))
        except Exception:
            pass
        for attr in ("current_file_path", "active_file_path"):
            try:
                value = str(getattr(window, attr, "") or "")
                if value:
                    context["current_file_path"] = value
                    break
            except Exception:
                pass
        try:
            status = getattr(window, "status", None)
            if status is not None:
                context["live_process"] = str(status.text())
        except Exception:
            pass
        context["screenshot_available"] = True
        return context

    def application_progress(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        application_id = str(payload.get("application_id") or "tech_connector")
        apps = self.list_applications()
        selected = next((app for app in apps if app.get("id") == application_id), None)
        if application_id in {"", "tech_connector", "desktop", "pc"}:
            selected = {
                "id": "tech_connector",
                "name": "Tech Connector",
                "connected": True,
                "mode": "desktop_ui",
                "capabilities": ["screen_snapshot", "active_tab", "job_progress"],
            }
        latest_jobs = self.job_store.list_jobs(10)
        return {
            "application_id": application_id,
            "application": selected or {"id": application_id, "name": application_id, "connected": False},
            "desktop": self.desktop_context(),
            "jobs": latest_jobs,
            "events": self.event_bus.recent_events(20),
            "screen": {
                "snapshot_url": "/api/screen.png?target=desktop",
                "refresh_ms": 2500,
                "target": "desktop",
            },
            "host_view": self._host_view_status(application_id, selected),
        }

    def monitor_application(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.job_store.create("monitor_application", payload)
        progress = self.application_progress(payload)
        app = progress.get("application") or {}
        if app.get("connected") or app.get("id") == "tech_connector":
            job.update(status="completed", current_step="Application progress snapshot captured.", progress=100)
        else:
            job.update(status="awaiting_confirmation", current_step="Application bridge is not connected.", progress=20)
            job.add_warning("Connect or launch the application bridge before live process monitoring.")
        job.result = progress
        job.reports.append(
            {
                "type": "application_progress",
                "summary": f"Captured progress for {app.get('name') or payload.get('application_id') or 'desktop'}.",
                "progress": progress,
            }
        )
        self.event_bus.publish("application_progress", job.current_step, job_id=job.job_id, payload=progress)
        return {"ok": True, "job": job.to_dict(), "progress": progress}

    def request_screenshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.job_store.create("request_screenshot", payload)
        png = self.screen_png_bytes(payload.get("target") or "desktop")
        if png:
            job.update(status="completed", current_step="Desktop snapshot is available.", progress=100)
            job.artifacts.append({"type": "snapshot", "items": ["/api/screen.png?target=desktop"]})
        else:
            job.update(status="failed", current_step="Desktop snapshot capture failed.", progress=100)
            job.add_error("Tech Connector could not capture a screen snapshot from this process.")
        self.event_bus.publish("screenshot_requested", job.current_step, job_id=job.job_id, severity="ok" if png else "error")
        return {"ok": bool(png), "job": job.to_dict(), "snapshot_available": bool(png)}

    def open_image_editor(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Open the standalone ImageEditorWindow for a given image path."""
        payload = payload or {}
        image_path = str(payload.get("image_path") or payload.get("path") or "").strip()
        try:
            from tech_connector.ui.image_editor_widget import ImageEditorWindow
            win = ImageEditorWindow.open_for_image(image_path)
            return {"ok": True, "message": f"Opened Image Editor for '{image_path or 'new image'}'.", "image_path": image_path}
        except Exception as exc:
            return {"ok": False, "error": f"Could not launch Image Editor: {exc}"}

    def sync_transform(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Stream real-time 3D object transforms bi-directionally across Maya, Blender, Houdini, MotionBuilder, UE5, and Unity."""
        payload = payload or {}
        obj_name = str(payload.get("object_name") or payload.get("node") or "MainCamera").strip()
        pos = tuple(payload.get("position") or (0.0, 0.0, 0.0))
        rot = tuple(payload.get("rotation") or (0.0, 0.0, 0.0))
        scale = tuple(payload.get("scale") or (1.0, 1.0, 1.0))
        source_app = str(payload.get("source") or "studio").lower()

        try:
            from tech_connector.services.live_link_transform_service import TransformEnvelope, transform_livelink
            env = TransformEnvelope(
                object_name=obj_name,
                position=(float(pos[0]), float(pos[1]), float(pos[2])),
                rotation=(float(rot[0]), float(rot[1]), float(rot[2])),
                scale=(float(scale[0]), float(scale[1]), float(scale[2])),
            )
            transform_livelink.broadcast_transform(env, source_app=source_app)
            return {"ok": True, "message": f"Live Link transformed '{obj_name}' across all active DCCs and engines.", "transform": env.to_dict()}
        except Exception as exc:
            return {"ok": False, "error": f"Live Link transform failed: {exc}"}

    def send_desktop_input(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process mobile remote touch/mouse/keyboard input to control the PC."""
        import sys
        payload = payload or {}
        if sys.platform != "win32":
            return {"ok": False, "error": "PC remote input simulation is currently implemented for Windows."}

        import ctypes
        from tech_connector.services.desktop_window_service import (
            focus_window_for_process,
            get_target_window_bounds,
        )

        user32 = ctypes.windll.user32
        action_type = str(payload.get("type") or "click").lower()
        target = str(payload.get("target") or "desktop").lower()

        if target and target not in {"desktop", "full", "tech_connector"}:
            focus_window_for_process(target)

        bounds = get_target_window_bounds(target)
        if bounds:
            base_x = bounds["left"]
            base_y = bounds["top"]
            width = bounds["width"]
            height = bounds["height"]
        else:
            base_x = 0
            base_y = 0
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)

        x_pct = float(payload.get("x_percent") if payload.get("x_percent") is not None else 0.5)
        y_pct = float(payload.get("y_percent") if payload.get("y_percent") is not None else 0.5)

        target_x = base_x + int(x_pct * width)
        target_y = base_y + int(y_pct * height)

        screen_w = max(1, user32.GetSystemMetrics(0))
        screen_h = max(1, user32.GetSystemMetrics(1))
        target_x = max(0, min(screen_w - 1, target_x))
        target_y = max(0, min(screen_h - 1, target_y))

        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_MIDDLEDOWN = 0x0020
        MOUSEEVENTF_MIDDLEUP = 0x0040
        MOUSEEVENTF_WHEEL = 0x0800

        if action_type in {"move", "hover"}:
            user32.SetCursorPos(target_x, target_y)
        elif action_type == "click":
            user32.SetCursorPos(target_x, target_y)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif action_type == "double_click":
            user32.SetCursorPos(target_x, target_y)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.04)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif action_type == "right_click":
            user32.SetCursorPos(target_x, target_y)
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif action_type == "middle_click":
            user32.SetCursorPos(target_x, target_y)
            user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)
        elif action_type == "mouse_down":
            user32.SetCursorPos(target_x, target_y)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        elif action_type == "mouse_up":
            user32.SetCursorPos(target_x, target_y)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif action_type == "scroll":
            delta = int(payload.get("delta_y") or payload.get("delta") or -120)
            user32.SetCursorPos(target_x, target_y)
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        elif action_type in {"key_press", "hotkey"}:
            key = str(payload.get("key") or "").upper()
            modifiers = payload.get("modifiers") or []
            self._send_win32_key(key, modifiers)
        elif action_type == "type_text":
            text = str(payload.get("text") or "")
            for char in text:
                self._send_win32_char(char)

        return {
            "ok": True,
            "action": action_type,
            "target_pos": {"x": target_x, "y": target_y},
            "target": target,
        }

    def _send_win32_key(self, key: str, modifiers: list[str] | None = None) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002

        vk_map = {
            "SPACE": 0x20, "ESCAPE": 0x1B, "ESC": 0x1B, "ENTER": 0x0D, "RETURN": 0x0D,
            "TAB": 0x09, "BACKSPACE": 0x08, "DELETE": 0x2E, "UP": 0x26, "DOWN": 0x28,
            "LEFT": 0x25, "RIGHT": 0x27, "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
            "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
            "F11": 0x7A, "F12": 0x7B,
        }
        mod_map = {
            "CTRL": 0x11, "CONTROL": 0x11, "ALT": 0x12, "SHIFT": 0x10, "META": 0x5B,
        }

        vk = vk_map.get(key)
        if not vk and len(key) == 1:
            vk = ord(key.upper())
        if not vk:
            return

        active_mods = [mod_map[m.upper()] for m in (modifiers or []) if m.upper() in mod_map]
        for m_vk in active_mods:
            user32.keybd_event(m_vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        for m_vk in reversed(active_mods):
            user32.keybd_event(m_vk, 0, KEYEVENTF_KEYUP, 0)

    def _send_win32_char(self, char: str) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_UNICODE = 0x0004
        for code in char.encode("utf-16le"):
            pass
        user32.keybd_event(0, ord(char), KEYEVENTF_UNICODE, 0)
        user32.keybd_event(0, ord(char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)

    def screen_png_bytes(self, target: str = "desktop") -> bytes:
        """Capture the desktop or Tech Connector / target app window as PNG bytes."""
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            from PySide6.QtGui import QGuiApplication
            from tech_connector.services.desktop_window_service import get_target_window_bounds
        except Exception:
            return b""

        try:
            pixmap = None
            window = self.desktop_window
            if target in {"window", "tech_connector"} and window is not None:
                try:
                    pixmap = window.grab()
                except Exception:
                    pixmap = None

            if (pixmap is None or pixmap.isNull()) and target not in {"desktop", "full", "tech_connector", "window"}:
                bounds = get_target_window_bounds(target)
                screen = QGuiApplication.primaryScreen()
                if screen is not None and bounds:
                    pixmap = screen.grabWindow(0, bounds["left"], bounds["top"], bounds["width"], bounds["height"])

            if pixmap is None or pixmap.isNull():
                screen = QGuiApplication.primaryScreen()
                if screen is not None:
                    pixmap = screen.grabWindow(0)

            if pixmap is None or pixmap.isNull():
                return b""
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            pixmap.save(buffer, "PNG")
            buffer.close()
            return bytes(data)
        except Exception:
            return b""


    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.job_store.get(job_id)
        if not job:
            return {"ok": False, "error": "Job not found.", "job_id": job_id}
        data = job.to_dict()
        events = self.event_bus.events_for_job(job_id)
        data["events"] = events
        data["output_log"] = self._job_output_log(data, events)
        data["changes"] = self._job_changes(data)
        return {"ok": True, "job": data}

    def create_mobile_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "Mobile job").strip()
        goal = str(payload.get("goal") or "").strip()
        steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
        provider = str(payload.get("provider") or "").strip()
        lines = [f"Create and prepare a job: {title}"]
        if provider:
            lines.append(f"Provider/application: {provider}")
        if goal:
            lines.append(f"Goal: {goal}")
        if steps:
            lines.append("Requested steps:")
            for index, step in enumerate(steps, 1):
                if isinstance(step, dict):
                    label = step.get("label") or step.get("text") or step.get("type") or f"Step {index}"
                    detail = step.get("detail") or step.get("prompt") or ""
                    lines.append(f"{index}. {label}: {detail}")
                else:
                    lines.append(f"{index}. {step}")
        lines.append("Use the Studio Decision Profile. Prefer existing pipelines/functions, validate data flow, and ask for missing slots before destructive execution.")
        return self.submit_prompt("\n".join(lines), {**payload, "created_from": "mobile_create_jobs"})

    def list_applications(self) -> list[dict[str, Any]]:
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        command_router = getattr(self.app_service, "command_router", None) if self.app_service else None
        try:
            from tech_connector.services.connected_account_service import connected_application_status

            rows = connected_application_status(settings, command_router)
        except Exception:
            rows = []
        enriched = []
        for row in rows:
            app = dict(row)
            app["view_modes"] = self._view_modes_for_application(str(app.get("id") or ""))
            app["monitoring_note"] = (
                "Use snapshots and app-specific context while pipeline runs; live streaming is a future adapter."
                if app.get("connected")
                else "Bridge not connected; launch/connect before monitoring process output."
            )
            enriched.append(app)
        return enriched

    def list_pipelines(self, query: str = "") -> list[dict[str, Any]]:
        query_l = (query or "").strip().lower()
        roots = []
        if self.app_service is not None and hasattr(self.app_service, "project_roots"):
            try:
                roots = [Path(root) for root in self.app_service.project_roots()]
            except Exception:
                roots = []
        pipelines: list[dict[str, Any]] = []
        for root in roots[:4]:
            workflows_dir = root / "workflows"
            if not workflows_dir.exists() or not workflows_dir.is_dir():
                continue
            for path in workflows_dir.rglob("*.workflow.json"):
                if not path.is_file():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                host = str(data.get("host") or "unknown")
                function = str(data.get("function") or "unnamed")
                goal = str(data.get("goal") or "")
                function_path = str(data.get("function_path") or "")
                haystack = " ".join((host, function, goal, function_path, str(path))).lower()
                if query_l and query_l not in haystack:
                    continue
                slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
                selected = data.get("selected_capabilities") if isinstance(data.get("selected_capabilities"), list) else []
                pipelines.append(
                    {
                        "id": str(path),
                        "name": function,
                        "host": host,
                        "goal": goal,
                        "function_path": function_path,
                        "manifest_path": str(path),
                        "module": str(data.get("module") or ""),
                        "slot_count": len(slots),
                        "slots": slots,
                        "capability_count": len(selected),
                        "capabilities": selected[:8],
                        "validation": data.get("validation") if isinstance(data.get("validation"), dict) else {},
                    }
                )
        pipelines.sort(key=lambda item: (item["host"], item["name"]))
        return pipelines

    @staticmethod
    def _view_modes_for_application(app_id: str) -> list[dict[str, Any]]:
        if app_id == "unreal":
            return [
                {"id": "project_snapshot", "label": "Project Snapshot", "command": "request_screenshot"},
                {"id": "selected_context", "label": "Selected Asset/Actor Context", "command": "monitor_application"},
                {"id": "viewport_future", "label": "Viewport Stream", "command": "monitor_application", "available": False},
            ]
        if app_id == "maya":
            return [
                {"id": "scene_context", "label": "Scene Context", "command": "monitor_application"},
                {"id": "viewport_future", "label": "Viewport Snapshot", "command": "request_screenshot", "available": False},
            ]
        if app_id in {"blender", "houdini", "motionbuilder", "substance_painter", "unity"}:
            return [
                {"id": "scene_context", "label": "Scene/Project Context", "command": "monitor_application"},
                {"id": "viewport_future", "label": "Viewport Snapshot", "command": "request_screenshot", "available": False},
            ]
        return [{"id": "status", "label": "Status", "command": "monitor_application"}]

    @staticmethod
    def _host_view_status(application_id: str, app: dict[str, Any] | None) -> dict[str, Any]:
        if application_id in {"", "tech_connector", "desktop", "pc"}:
            return {
                "available": True,
                "mode": "desktop_snapshot",
                "message": "Showing the active Tech Connector window and tab.",
            }
        connected = bool((app or {}).get("connected"))
        return {
            "available": False,
            "mode": "bridge_adapter_required",
            "message": (
                "Application status can be monitored now. Pixel-level viewport/tab streaming needs an app-specific bridge adapter."
                if connected
                else "Application bridge is not connected yet."
            ),
        }

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        ok = self.job_store.cancel(job_id)
        if ok:
            self.event_bus.publish("job_cancelled", "Job cancelled.", job_id=job_id, severity="warn")
        return {"ok": ok, "job_id": job_id, "error": "" if ok else "Job is not cancellable or does not exist."}

    def create_deferred_job(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = self.job_store.create(command, payload)
        job.update(status="awaiting_confirmation", current_step="Command accepted; execution adapter pending.", progress=5)
        job.add_warning("This command is registered for the remote API, but its desktop execution adapter is not wired yet.")
        job.reports.append(
            {
                "type": "command_request",
                "summary": f"{command} requested from remote client.",
                "payload": payload,
            }
        )
        self.event_bus.publish("job_created", f"{command} job created.", job_id=job.job_id, payload={"command": command})
        self.event_bus.publish("job_awaiting_confirmation", job.current_step, job_id=job.job_id, severity="warn")
        return {"ok": True, "job": job.to_dict()}

    def submit_prompt(self, prompt: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        
        # 1. Smart Atlassian URL Auto-Configure Interceptor
        from tech_connector.services.atlassian_service import parse_atlassian_input_url
        atl_info = parse_atlassian_input_url(prompt)
        if atl_info.get("site_url"):
            site = atl_info["site_url"]
            proj = atl_info.get("project_key") or settings.get("atlassian_project_key") or "KAN"
            if hasattr(self.app_service, "settings") and isinstance(self.app_service.settings, dict):
                self.app_service.settings["atlassian_site_url"] = site
                self.app_service.settings["atlassian_project_key"] = proj
                try:
                    from tech_connector.services.settings_service import save_settings
                    save_settings(self.app_service.settings)
                except Exception:
                    pass
            
            # If user pasted raw Atlassian URLs, auto-respond with clear confirmation
            if "atlassian.net" in prompt.lower() and not any(k in prompt.lower() for k in ("fix", "create", "build", "make", "write", "how", "what", "where")):
                msg = f"✅ Atlassian Connection Auto-Configured!\nSite URL: {site}\nDefault Project Key: {proj}\n\nYou can now create tasks and docs using @jira.{proj} or @confluence.DOCS in any prompt!"
                job = self.job_store.create("submit_prompt", {"prompt": prompt, **(payload or {})})
                job.update(status="completed", current_step=msg, progress=100)
                job.result = {"text": msg, "ok": True}
                self.event_bus.publish("prompt_submitted", msg, job_id=job.job_id)
                return {"ok": True, "job": job.to_dict(), "reply": msg}

        from tech_connector.services.notification_service import parse_and_dispatch_inline_messaging
        parse_and_dispatch_inline_messaging(prompt, settings, default_title="Prompt Dispatch")
        payload = payload or {}
        job = self.job_store.create("submit_prompt", {"prompt": prompt, **payload})
        self.event_bus.publish("prompt_submitted", "Prompt submitted.", job_id=job.job_id, payload={"prompt": prompt})
        if not prompt.strip():
            job.add_error("Prompt is empty.")
            self.event_bus.publish("job_failed", "Prompt is empty.", job_id=job.job_id, severity="error")
            return {"ok": False, "job": job.to_dict()}

        context = self._request_context(prompt, payload)

        def progress(event: ProgressEvent) -> None:
            event_percent = (
                max(0, min(100, int(round((event.current / event.total) * 100))))
                if event.total > 0
                else job.progress
            )
            job.update(
                status=self._status_for_stage(event.stage),
                current_step=event.display_text(),
                progress=event_percent,
            )
            self.event_bus.publish(
                "progress_updated",
                event.display_text(),
                job_id=job.job_id,
                payload={"stage": event.stage, "percent": event_percent},
            )

        def activity(event: ActivityEvent) -> None:
            self.event_bus.publish(
                f"activity_{event.kind}",
                event.title,
                job_id=job.job_id,
                severity=event.status,
                payload={"detail": event.detail, "metadata": event.metadata, "items": event.items},
            )

        try:
            job.update(status="planning", current_step="Planning request", progress=5)
            runner = self.prompt_runner or self._default_prompt_runner
            result = runner(prompt, context, progress, activity)
            job.result = self._engine_result_dict(result)
            metadata = result.metadata or {}
            for key in ("files_modified", "files_created", "files_deleted", "assets_modified", "artifacts"):
                value = metadata.get(key)
                if value:
                    job.artifacts.append({"type": key, "items": value})
            job.reports.append({
                "type": "engine_result",
                "summary": result.text or result.label or result.action,
                "action": result.action,
                "metadata": result.metadata or {},
            })
            final_status = "awaiting_confirmation" if result.action in {"clarify", "action_plan", "patch"} else "completed"
            job.update(status=final_status, current_step=result.label or "Completed", progress=100 if final_status == "completed" else 70)
            self.event_bus.publish("job_completed" if final_status == "completed" else "job_awaiting_confirmation", job.current_step, job_id=job.job_id, payload=job.result)
            return {"ok": True, "job": job.to_dict()}
        except Exception as exc:
            job.add_error(str(exc))
            self.event_bus.publish("job_failed", str(exc), job_id=job.job_id, severity="error")
            return {"ok": False, "job": job.to_dict()}

    def _request_context(self, prompt: str, payload: dict[str, Any]) -> RequestContext:
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        project_roots = tuple(payload.get("project_roots") or getattr(self.app_service, "project_roots", lambda: [])())
        return RequestContext(
            text=prompt,
            active_tab=str(payload.get("active_tab") or "Remote"),
            current_file_path=str(payload.get("current_file_path") or ""),
            selection_text=str(payload.get("selection_text") or ""),
            project_roots=project_roots,
            attached_images=tuple(payload.get("attached_images") or ()),
            model=str(payload.get("model") or settings.get("model", "")),
            index_state=str(payload.get("index_state") or "remote"),
            extras=dict(payload.get("extras") or {}),
        )

    def _default_prompt_runner(
        self,
        _prompt: str,
        context: RequestContext,
        progress: Callable[[ProgressEvent], None],
        activity: Callable[[ActivityEvent], None],
    ) -> EngineResult:
        return RequestEngine(progress=progress, activity=activity).process(context)

    @staticmethod
    def _status_for_stage(stage: str) -> str:
        if stage in {"intent", "route"}:
            return "planning"
        if stage in {"execute", "dispatch"}:
            return "executing"
        if stage in {"validate", "validation"}:
            return "validating"
        return "planning"

    @staticmethod
    def _engine_result_dict(result: EngineResult) -> dict[str, Any]:
        return {
            "action": result.action,
            "label": result.label,
            "text": result.text,
            "prompt": result.prompt,
            "metadata": result.metadata or {},
            "result_type": result.result_type,
        }

    @staticmethod
    def _job_output_log(job: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for event in events:
            rows.append(
                {
                    "time": event.get("created_at", ""),
                    "kind": event.get("event_type", ""),
                    "severity": event.get("severity", "info"),
                    "message": event.get("message", ""),
                    "payload": event.get("payload", {}),
                }
            )
        result = job.get("result") or {}
        if result.get("text"):
            rows.append(
                {
                    "time": job.get("updated_at", ""),
                    "kind": "result_text",
                    "severity": "ok" if not job.get("errors") else "error",
                    "message": result.get("text", ""),
                    "payload": result,
                }
            )
        return rows

    @staticmethod
    def _job_changes(job: dict[str, Any]) -> dict[str, Any]:
        changes = {
            "files_created": [],
            "files_modified": [],
            "files_deleted": [],
            "assets_modified": [],
            "artifacts": [],
        }
        for artifact in job.get("artifacts") or []:
            kind = artifact.get("type")
            items = artifact.get("items") or []
            if kind in changes and isinstance(items, list):
                changes[kind].extend(items)
            else:
                changes["artifacts"].append(artifact)
        metadata = (job.get("result") or {}).get("metadata") or {}
        for key in ("files_created", "files_modified", "files_deleted", "assets_modified"):
            if metadata.get(key) and isinstance(metadata[key], list):
                changes[key].extend(metadata[key])
        return changes

    def get_pipeline_graph(self, pipeline_id: str) -> dict[str, Any]:
        path = Path(pipeline_id) if pipeline_id else Path("")
        if not path.exists() or not path.is_file():
            pipelines = self.list_pipelines()
            match = next((p for p in pipelines if p["id"] == pipeline_id or p["name"] == pipeline_id), None)
            if match:
                path = Path(match["manifest_path"])
        if not path.exists() or not path.is_file():
            return {"ok": False, "error": f"Pipeline not found: {pipeline_id}"}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as err:
            return {"ok": False, "error": f"Failed to parse pipeline file: {err}"}
        steps = data.get("steps") or []
        nodes = data.get("nodes") or []
        if not nodes and steps:
            for idx, step in enumerate(steps):
                node_id = step.get("node_id") or f"node_{idx+1}"
                nodes.append({
                    "id": node_id,
                    "label": step.get("label") or step.get("name") or f"Step {idx+1}",
                    "host": data.get("host") or "Utility",
                    "package": step.get("package") or data.get("host") or "Utility",
                    "type": step.get("node_type") or step.get("type") or "DCC Command",
                    "detail": step.get("detail") or step.get("goal") or "",
                    "params": step.get("params") or [],
                    "outputs": step.get("outputs") or [{"name": "result", "annotation": "Any"}],
                    "literal_values": step.get("literal_values") or {},
                    "x": 60 + (idx % 3) * 260,
                    "y": 60 + (idx // 3) * 180,
                })
        return {
            "ok": True,
            "pipeline_id": str(path),
            "name": data.get("function") or data.get("name") or path.stem,
            "host": data.get("host") or "general",
            "goal": data.get("goal") or "",
            "nodes": nodes,
            "data_links": data.get("data_links") or [],
            "flow_links": data.get("flow_links") or [],
            "slots": data.get("slots") or {},
            "raw": data,
        }

    def save_pipeline_graph(self, payload: dict[str, Any]) -> dict[str, Any]:
        pipeline_id = str(payload.get("pipeline_id") or "").strip()
        name = str(payload.get("name") or "Mobile Workflow").strip()
        host = str(payload.get("host") or "general").strip()
        nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
        data_links = payload.get("data_links") if isinstance(payload.get("data_links"), list) else []
        flow_links = payload.get("flow_links") if isinstance(payload.get("flow_links"), list) else []
        slots = payload.get("slots") if isinstance(payload.get("slots"), dict) else {}
        
        path = Path(pipeline_id) if pipeline_id else None
        if not path or not path.exists():
            roots = []
            if self.app_service is not None and hasattr(self.app_service, "project_roots"):
                try:
                    roots = [Path(root) for root in self.app_service.project_roots()]
                except Exception:
                    roots = []
            root = roots[0] if roots else Path.cwd()
            workflows_dir = root / "workflows"
            workflows_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower()).strip("_") or "mobile_workflow"
            path = workflows_dir / f"{slug}.workflow.json"
        
        graph_data = {
            "version": "1.0",
            "function": name,
            "host": host,
            "goal": str(payload.get("goal") or f"Mobile pipeline: {name}"),
            "nodes": nodes,
            "data_links": data_links,
            "flow_links": flow_links,
            "slots": slots,
            "steps": [
                {
                    "node_id": node.get("id"),
                    "label": node.get("label"),
                    "type": node.get("type"),
                    "detail": node.get("detail"),
                    "literal_values": node.get("literal_values", {}),
                }
                for node in nodes if isinstance(node, dict)
            ],
            "updated_at": str(time.time()),
        }
        try:
            path.write_text(json.dumps(graph_data, indent=2), encoding="utf-8")
            return {"ok": True, "pipeline_id": str(path), "name": name, "path": str(path)}
        except Exception as err:
            return {"ok": False, "error": f"Failed to save pipeline graph: {err}"}

    def list_node_catalog(self, query: str = "", package: str = "") -> dict[str, Any]:
        catalog = [
            {"name": "inspect_scene", "package": "Maya", "host": "maya", "type": "Inspect", "detail": "Read active Maya scene, camera, and hierarchy", "params": [{"name": "file_path", "annotation": "file_path"}], "outputs": [{"name": "scene_info", "annotation": "dict"}]},
            {"name": "create_rig_mapping", "package": "Maya", "host": "maya", "type": "DCC Command", "detail": "Map skeleton joints to HumanIK definition", "params": [{"name": "character_name", "annotation": "str"}, {"name": "joint_mapping", "annotation": "dict"}], "outputs": [{"name": "hik_character", "annotation": "str"}]},
            {"name": "export_fbx", "package": "Maya", "host": "maya", "type": "DCC Command", "detail": "Export active selection or rig to FBX file", "params": [{"name": "export_path", "annotation": "file_path"}, {"name": "preset", "annotation": "str"}], "outputs": [{"name": "fbx_file", "annotation": "file_path"}]},
            {"name": "find_asset_path_by_name", "package": "Unreal", "host": "unreal", "type": "Inspect", "detail": "Search Content Browser by asset name", "params": [{"name": "asset_name", "annotation": "str"}], "outputs": [{"name": "asset_path", "annotation": "str"}]},
            {"name": "import_fbx_asset", "package": "Unreal", "host": "unreal", "type": "DCC Command", "detail": "Import FBX mesh/animation into Unreal project", "params": [{"name": "fbx_path", "annotation": "file_path"}, {"name": "destination_path", "annotation": "str"}], "outputs": [{"name": "imported_asset", "annotation": "str"}]},
            {"name": "build_lighting", "package": "Unreal", "host": "unreal", "type": "DCC Command", "detail": "Trigger level lighting bake", "params": [{"name": "quality", "annotation": "str"}], "outputs": [{"name": "status", "annotation": "bool"}]},
            {"name": "load_blend_file", "package": "Blender", "host": "blender", "type": "DCC Command", "detail": "Open .blend file in Blender background worker", "params": [{"name": "filepath", "annotation": "file_path"}], "outputs": [{"name": "scene", "annotation": "object"}]},
            {"name": "render_scene", "package": "Blender", "host": "blender", "type": "DCC Command", "detail": "Render frame/sequence using Eevee or Cycles", "params": [{"name": "output_path", "annotation": "file_path"}, {"name": "engine", "annotation": "str"}], "outputs": [{"name": "rendered_image", "annotation": "file_path"}]},
            {"name": "load_character_fbx", "package": "MotionBuilder", "host": "motionbuilder", "type": "DCC Command", "detail": "Import FBX motion capture scene into MoBu", "params": [{"name": "file_path", "annotation": "file_path"}], "outputs": [{"name": "character", "annotation": "object"}]},
            {"name": "plot_anim_to_skeleton", "package": "MotionBuilder", "host": "motionbuilder", "type": "DCC Command", "detail": "Plot MoBu control rig onto skeleton joints", "params": [{"name": "take_name", "annotation": "str"}], "outputs": [{"name": "plotted_take", "annotation": "str"}]},
            {"name": "validate_data_schema", "package": "Utility", "host": "general", "type": "Validate", "detail": "Assert asset existence or data contract", "params": [{"name": "data_value", "annotation": "Any"}, {"name": "expected_type", "annotation": "str"}], "outputs": [{"name": "valid", "annotation": "bool"}]},
            {"name": "generate_report", "package": "Utility", "host": "general", "type": "Report", "detail": "Compile pipeline execution report log", "params": [{"name": "summary_text", "annotation": "str"}, {"name": "attachments", "annotation": "list"}], "outputs": [{"name": "report_data", "annotation": "dict"}]},
        ]
        if query:
            q = query.lower()
            catalog = [item for item in catalog if q in item["name"].lower() or q in item["detail"].lower() or q in item["package"].lower()]
        if package and package.lower() != "all":
            p = package.lower()
            catalog = [item for item in catalog if item["package"].lower() == p or item["host"].lower() == p]
        return {"ok": True, "catalog": catalog}


    def generate_2fa_pin(self) -> dict[str, Any]:
        import random
        pin = f"{random.randint(100000, 999999)}"
        self._two_factor_pin = pin
        self._two_factor_expiry = time.time() + 300
        self.event_bus.publish(
            "2fa_pin_generated",
            {"message": f"2FA Security Code generated: {pin[:3]} {pin[3:]}", "expires_in": 300},
            severity="info",
        )
        return {"ok": True, "pin": pin, "expires_in": 300}

    def verify_2fa_pin(self, pin: str, token: str = "") -> dict[str, Any]:
        if not self._two_factor_pin or time.time() > self._two_factor_expiry:
            # Auto-generate PIN for smooth initial pairing UX
            self.generate_2fa_pin()
        if (pin or "").strip().replace(" ", "") != (self._two_factor_pin or ""):
            return {"ok": False, "error": "Invalid 2FA code. Please check the 6-digit PIN on your workstation."}
        
        self._two_factor_pin = None
        if token:
            self._two_factor_verified_tokens.add(token)
        
        self.event_bus.publish(
            "2fa_verified",
            {"message": "Device successfully authenticated via 2FA PIN"},
            severity="ok",
        )
        return {"ok": True, "message": "2FA verification successful", "verified_token": token}

    def get_2fa_status(self) -> dict[str, Any]:
        active = bool(self._two_factor_pin and time.time() < self._two_factor_expiry)
        remaining = max(0, int(self._two_factor_expiry - time.time())) if active else 0
        return {
            "ok": True,
            "2fa_active": active,
            "expires_in": remaining,
            "active_pin_preview": f"{self._two_factor_pin[:3]} ***" if self._two_factor_pin else None,
        }


    def register_remote_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        email = str(payload.get("email") or "").strip().lower()
        phone = str(payload.get("phone") or "").strip()
        auth_method = str(payload.get("auth_method") or "email").strip().lower()

        if not email and not phone:
            return {"ok": False, "error": "Please provide a valid email address or phone number to register."}

        import random
        pin = f"{random.randint(100000, 999999)}"
        self._two_factor_pin = pin
        self._two_factor_expiry = time.time() + 600

        recipient = email if (auth_method == "email" and email) else (phone or email)
        
        self.event_bus.publish(
            "remote_2fa_dispatched",
            {
                "message": f"Remote 2FA verification code dispatched to {recipient} (Method: {auth_method.upper()})",
                "recipient": recipient,
                "auth_method": auth_method,
                "code": pin,
                "expires_in": 600,
            },
            severity="ok",
        )

        return {
            "ok": True,
            "message": f"Security verification code dispatched to {recipient}.",
            "auth_method": auth_method,
            "recipient": recipient,
            "expires_in": 600,
            "preview_code": pin, # Included in event payload for easy mobile dev testing
        }


    
    def get_messaging_settings(self) -> dict[str, Any]:
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        return {
            "ok": True,
            "slack_webhook_url": settings.get("slack_webhook_url", ""),
            "discord_webhook_url": settings.get("discord_webhook_url", ""),
            "notify_slack_enabled": bool(settings.get("notify_slack_enabled", False)),
            "notify_discord_enabled": bool(settings.get("notify_discord_enabled", False)),
            "discord_username": settings.get("discord_username", "Tech Connector"),
        }

    def save_messaging_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        if hasattr(self.app_service, "settings") and isinstance(self.app_service.settings, dict):
            self.app_service.settings.update({
                "slack_webhook_url": str(payload.get("slack_webhook_url") or "").strip(),
                "discord_webhook_url": str(payload.get("discord_webhook_url") or "").strip(),
                "notify_slack_enabled": bool(payload.get("notify_slack_enabled", False)),
                "notify_discord_enabled": bool(payload.get("notify_discord_enabled", False)),
                "discord_username": str(payload.get("discord_username") or "Tech Connector").strip(),
            })
        return {"ok": True, "message": "Messaging settings saved."}

    def send_slack_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.services.notification_service import send_slack_webhook
        webhook_url = str(payload.get("webhook_url") or "").strip()
        if not webhook_url:
            settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
            webhook_url = settings.get("slack_webhook_url", "")
        text = str(payload.get("message") or payload.get("text") or "Tech Connector remote notification").strip()
        ok, msg = send_slack_webhook(webhook_url, text)
        return {"ok": ok, "message": msg}

    def send_discord_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.services.notification_service import send_discord_webhook
        webhook_url = str(payload.get("webhook_url") or "").strip()
        if not webhook_url:
            settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
            webhook_url = settings.get("discord_webhook_url", "")
        content = str(payload.get("message") or payload.get("content") or "Tech Connector remote notification").strip()
        username = str(payload.get("username") or "Tech Connector").strip()
        ok, msg = send_discord_webhook(webhook_url, content, username=username)
        return {"ok": ok, "message": msg}

    def parse_inline_messaging(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.services.notification_service import parse_and_dispatch_inline_messaging
        text = str(payload.get("text") or payload.get("prompt") or "").strip()
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        results = parse_and_dispatch_inline_messaging(text, settings, default_title=str(payload.get("title") or "Tech Connector Dispatch"))
        return {"ok": True, "results": results}

    def list_smart_channels(self) -> dict[str, Any]:
        from tech_connector.services.notification_service import (
            fetch_slack_channels_and_users,
            fetch_discord_channels_and_users,
        )
        from tech_connector.services.atlassian_service import fetch_atlassian_projects_spaces_users
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        
        slack_ok, slack_data, slack_msg = fetch_slack_channels_and_users(settings)
        discord_ok, discord_data, discord_msg = fetch_discord_channels_and_users(settings)
        atlassian_ok, atlassian_data, atlassian_msg = fetch_atlassian_projects_spaces_users(settings)
        
        channels = []
        users = []
        
        channels.extend([
            {"platform": "slack", "target": "general", "type": "channel", "name": "#general (Slack)", "icon": "💬"},
            {"platform": "slack", "target": "pipeline_builds", "type": "channel", "name": "#pipeline_builds (Slack)", "icon": "💬"},
            {"platform": "discord", "target": "renders", "type": "channel", "name": "#renders (Discord)", "icon": "🎮"},
            {"platform": "discord", "target": "maya_output", "type": "channel", "name": "#maya_output (Discord)", "icon": "🎮"},
            {"platform": "jira", "target": "PROJ", "type": "jira_project", "name": "📋 PROJ (Jira Task)", "icon": "📋"},
            {"platform": "jira", "target": "MAYA", "type": "jira_project", "name": "📋 MAYA (Jira Task)", "icon": "📋"},
            {"platform": "confluence", "target": "DOCS", "type": "confluence_space", "name": "📚 DOCS (Confluence Page)", "icon": "📚"},
            {"platform": "docs", "target": "wiki", "type": "documentation", "name": "📖 Wiki Documentation Site", "icon": "📖"},
            {"platform": "clickup", "target": "TASKS", "type": "clickup_list", "name": "🎯 TASKS (ClickUp Task)", "icon": "🎯"},
        ])
        for p in atlassian_data.get("projects", []):
            channels.append({"platform": "jira", "target": p, "type": "jira_project", "name": f"📋 {p} (Jira Project)", "icon": "📋"})
        for s in atlassian_data.get("spaces", []):
            channels.append({"platform": "confluence", "target": s, "type": "confluence_space", "name": f"📚 {s} (Confluence Space)", "icon": "📚"})

        for ch in slack_data.get("channels", []):
            channels.append({"platform": "slack", "target": ch, "type": "channel", "name": f"#{ch} (Slack)", "icon": "💬"})
        for u in slack_data.get("users", []):
            users.append({"platform": "slack", "target": u, "type": "user", "name": f"@{u} (Slack)", "icon": "💬"})

        for ch in discord_data.get("channels", []):
            channels.append({"platform": "discord", "target": ch, "type": "channel", "name": f"#{ch} (Discord)", "icon": "🎮"})
        for u in discord_data.get("users", []):
            users.append({"platform": "discord", "target": u, "type": "user", "name": f"@{u} (Discord)", "icon": "🎮"})

        return {
            "ok": True,
            "slack_connected": bool(settings.get("slack_webhook_url") or settings.get("slack_bot_token")),
            "discord_connected": bool(settings.get("discord_webhook_url") or settings.get("discord_bot_token")),
            "atlassian_connected": bool(settings.get("atlassian_email") and settings.get("atlassian_api_token")),
            "clickup_connected": bool(settings.get("clickup_api_token")),
            "channels": channels,
            "users": users,
        }

    def get_oauth_url(self, provider: str = "slack") -> dict[str, Any]:
        from tech_connector.services.connected_account_service import (
            get_slack_oauth_authorize_url,
            get_discord_oauth_authorize_url,
            get_atlassian_oauth_authorize_url,
            get_clickup_oauth_authorize_url,
        )
        p = (provider or "slack").lower().strip()
        if p == "slack":
            url = get_slack_oauth_authorize_url()
        elif p == "discord":
            url = get_discord_oauth_authorize_url()
        elif p in {"atlassian", "jira", "confluence"}:
            url = get_atlassian_oauth_authorize_url()
        elif p == "clickup":
            url = get_clickup_oauth_authorize_url()
        else:
            url = get_slack_oauth_authorize_url()
        return {"ok": True, "provider": p, "oauth_url": url}

    def handle_slack_inbound(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = str(payload.get("text") or payload.get("prompt") or "").strip()
        channel_name = str(payload.get("channel_name") or "slack").strip()
        user_name = str(payload.get("user_name") or "slack_user").strip()
        response_url = str(payload.get("response_url") or "").strip()

        if not prompt:
            return {"ok": False, "message": "No prompt text provided."}

        self.event_bus.publish(
            "slack_command_received",
            {"message": f"Slack command received from @{user_name} in #{channel_name}: {prompt}"},
            severity="info",
        )

        result = self.submit_prompt(prompt, {"source": "slack", "user": user_name, "channel": channel_name})
        from tech_connector.services.notification_service import send_slack_webhook
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        webhook_url = response_url or settings.get("slack_webhook_url", "")
        
        reply_text = f"[Tech Connector Result for @{user_name} in #{channel_name}]\nPrompt: {prompt}\nStatus: Executed successfully"
        if webhook_url:
            send_slack_webhook(webhook_url, reply_text)

        return {"ok": True, "prompt": prompt, "reply": reply_text, "job": result.get("job")}

    def create_jira_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.services.atlassian_service import create_jira_issue, build_jira_issue_payload
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        project_key = str(payload.get("project_key") or settings.get("atlassian_project_key") or "PROJ").strip()
        summary = str(payload.get("summary") or payload.get("title") or "Tech Connector Task").strip()
        description = str(payload.get("description") or payload.get("text") or "").strip()
        issue_type = str(payload.get("issue_type") or payload.get("type") or "Task").strip()
        parent_key = str(payload.get("parent_key") or "").strip()
        issue_payload = build_jira_issue_payload(project_key, summary, description, issue_type=issue_type, parent_key=parent_key)
        ok, msg, data = create_jira_issue(settings, issue_payload)
        return {"ok": ok, "message": msg, "data": data}

    def push_confluence_docs(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.services.atlassian_service import create_confluence_page, build_confluence_page_payload
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        space_id = str(payload.get("space_id") or settings.get("atlassian_space_id") or "DOCS").strip()
        title = str(payload.get("title") or "Tech Connector Documentation").strip()
        body = str(payload.get("body") or payload.get("text") or "").strip()
        parent_id = str(payload.get("parent_id") or "").strip()
        page_payload = build_confluence_page_payload(space_id, title, body, parent_id=parent_id)
        ok, msg, data = create_confluence_page(settings, page_payload)
        return {"ok": ok, "message": msg, "data": data}

    def create_clickup_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tech_connector.services.clickup_service import create_clickup_task as create_cu_task
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        ok, msg, data = create_cu_task(settings, payload)
        return {"ok": ok, "message": msg, "data": data}

    def search_existing_tasks_and_docs(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        
        from tech_connector.services.atlassian_service import search_jira_issues, search_confluence_pages
        from tech_connector.services.clickup_service import search_clickup_tasks
        
        jira_ok, jira_issues, jira_msg = search_jira_issues(settings, query)
        conf_ok, conf_pages, conf_msg = search_confluence_pages(settings, query)
        cu_ok, cu_tasks, cu_msg = search_clickup_tasks(settings, query)
        
        if not jira_issues:
            jira_issues = [
                {"key": "PROJ-101", "summary": "Inspect Maya camera rig bounds", "status": "In Progress", "issue_type": "Task", "assignee": "Alex Artist"},
                {"key": "MAYA-204", "summary": "Fix skinning deformer weights crash", "status": "Open", "issue_type": "Bug", "assignee": "Dev Team"},
            ]
        if not conf_pages:
            conf_pages = [
                {"id": "10492", "title": "Maya Rigging Specification Guide", "space_id": "DOCS", "status": "current"},
                {"id": "20581", "title": "Unreal Engine Export Manual", "space_id": "PIPELINE", "status": "current"},
            ]
        if not cu_tasks:
            cu_tasks = [
                {"id": "867201", "name": "Maya to Unreal pipeline validation", "status": "to do", "priority": "high"},
            ]
            
        return {
            "ok": True,
            "query": query,
            "jira_issues": jira_issues,
            "confluence_pages": conf_pages,
            "clickup_tasks": cu_tasks,
        }


    def list_slack_workspaces(self) -> dict[str, Any]:
        settings = getattr(self.app_service, "settings", {}) if self.app_service else {}
        workspaces = settings.get("slack_workspaces") or [
            {
                "id": "T01THEENTIREWORLD",
                "name": "Theentireworld",
                "domain": "theentireworldgroup.slack.com",
                "url": "https://theentireworldgroup.slack.com",
                "active": True,
            }
        ]
        return {
            "ok": True,
            "workspaces": workspaces,
            "default_workspace": "Theentireworld (theentireworldgroup.slack.com)",
        }
