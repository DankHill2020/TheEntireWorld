"""High-level command layer shared by desktop UI and future remote clients."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from tech_connector.engine.progress_events import ActivityEvent, EngineResult, ProgressEvent
from tech_connector.engine.request_context import RequestContext
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
        self.desktop_window = None

    def execute(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        command = (command or "").strip()
        payload = payload or {}
        if command == "retrieve_status":
            return {"ok": True, "status": self.retrieve_status()}
        if command == "list_jobs":
            return {"ok": True, "jobs": self.job_store.list_jobs(int(payload.get("limit") or 50), state=str(payload.get("state") or "all"))}
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

    def screen_png_bytes(self, target: str = "desktop") -> bytes:
        """Capture the desktop or Tech Connector window as PNG bytes."""
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            from PySide6.QtGui import QGuiApplication
        except Exception:
            return b""

        try:
            pixmap = None
            window = self.desktop_window
            if target in {"window", "tech_connector", "desktop"} and window is not None:
                try:
                    pixmap = window.grab()
                except Exception:
                    pixmap = None
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
        for key in changes:
            value = metadata.get(key)
            if isinstance(value, list):
                changes[key].extend(value)
        return changes
