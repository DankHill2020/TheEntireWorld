import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from services.unreal.graph_patch_service import build_patch

from ui.unreal_editor_dialogs import (
    UnrealCapabilityValidationDialog,
    UnrealOperationConfirmDialog,
)


class MainWindowDccMixin:
    def _dcc_bridge_port_for_host(self, host: str):
        host = (host or "").strip().lower()
        router = getattr(self, "command_router", None)
        bridge = getattr(router, host, None) if router else None
        if bridge is None and host == "substance":
            bridge = getattr(router, "substance_painter", None) if router else None
        if bridge is None or not hasattr(bridge, "find_port"):
            return None
        try:
            return bridge.find_port()
        except Exception:
            return None

    def _schedule_dcc_bridge_retry(self, host: str, retry_callback=None, retry_label: str = "", attempts: int = 18, interval_ms: int = 2500):
        host = (host or "").strip().lower()
        state = {"remaining": max(1, int(attempts))}

        def poll():
            port = self._dcc_bridge_port_for_host(host)
            if port:
                if hasattr(self, "set_card"):
                    self.set_card(host, "ok", f"Connected :{port}")
                if hasattr(self, "append"):
                    self.append(f"\n[DCC Launcher] {host} bridge connected on port {port}.\n")
                if callable(retry_callback):
                    if hasattr(self, "append"):
                        self.append(f"[DCC Launcher] Running queued action{': ' + retry_label if retry_label else ''}.\n")
                    retry_callback()
                return
            state["remaining"] -= 1
            if state["remaining"] <= 0:
                if hasattr(self, "set_card"):
                    self.set_card(host, "bad", "Bridge timeout")
                if hasattr(self, "append"):
                    self.append(f"\n[DCC Launcher] Timed out waiting for {host} bridge. Start the bridge, then run the action again.\n")
                return
            if hasattr(self, "set_card"):
                self.set_card(host, "busy", f"Waiting {state['remaining']}")
            QTimer.singleShot(interval_ms, poll)

        QTimer.singleShot(interval_ms, poll)

    def _prompt_launch_missing_dcc_bridge(self, host: str, detail: str = "", retry_callback=None, retry_label: str = "") -> bool:
        host = (host or "").strip().lower()
        display = {
            "maya": "Maya",
            "unreal": "Unreal Engine",
            "blender": "Blender",
            "substance_painter": "Substance Painter",
            "motionbuilder": "MotionBuilder",
            "unity": "Unity",
            "houdini": "Houdini",
        }.get(host, host.title() or "DCC")
        if hasattr(self, "set_card"):
            self.set_card(host, "bad", "Not open")
        message = detail or f"{display} is not open or its Tech Connector bridge is not connected."
        reply = QMessageBox.question(
            self,
            f"Open {display}?",
            message + f"\n\nOpen {display} now? Tech Connector will ping the bridge and run this queued action once it connects.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return False
        if hasattr(self, "set_card"):
            self.set_card(host, "busy", "Launching...")
        self.launch_dcc(host)
        self._schedule_dcc_bridge_retry(host, retry_callback=retry_callback, retry_label=retry_label)
        return True

    def direct_maya_execute(self, code, label="Maya Direct", timeout=5):
        port = self.command_router.maya.find_port()
        if not port:
            self.set_card("maya", "bad", "No commandPort")
            self.last_user_prompt = f"[{label}] {code}"
            self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
            self.append(
                "[Maya Direct] No Maya commandPort found. Start Maya and run maya_command_port_setup.py.\n"
            )
            self._prompt_launch_missing_dcc_bridge("maya", "Maya commandPort was not found.", lambda: self.direct_maya_execute(code, label, timeout), label)
            return
        self.set_card("maya", "busy", f"Executing :{port}")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        self.append(f"[Maya Direct] Executing on port {port}...\n")
        ok, result = self.command_router.maya.execute(code, timeout=timeout)
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("maya", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("maya", "bad", "Execution failed")
            self.append(f"[Maya Direct Error] {result}\n")

    def direct_maya_selection(self):
        self._execute_maya_preset("selection")

    def direct_maya_file(self):
        self._execute_maya_preset("file")

    def direct_maya_scene_objects(self):
        self._execute_maya_preset("objects")

    def direct_maya_undo(self):
        self.send_raw("import maya.cmds as cmds; cmds.undo()", "Maya Undo")

    def direct_unreal_undo(self):
        self.send_raw(
            "import unreal; unreal.SystemLibrary.execute_console_command(None, 'TRANSACTION UNDO')",
            "Unreal Undo",
        )

    def direct_blender_undo(self):
        self.send_raw("import bpy; bpy.ops.ed.undo()", "Blender Undo")

    def direct_substance_painter_undo(self):
        self.send_raw(
            "import substance_painter; substance_painter.project.undo()",
            "Substance Undo",
        )

    def direct_unity_undo(self):
        self.send_raw("UnityEditor.Undo.PerformUndo()", "Unity Undo")

    def direct_houdini_undo(self):
        self.direct_houdini_execute("import hou\nhou.undos.performUndo()", "Houdini Undo")

    def direct_motionbuilder_undo(self):
        self.direct_motionbuilder_execute(
            "import pyfbsdk; pyfbsdk.FBSystem().Undo()", "MotionBuilder Undo"
        )

    def _execute_maya_preset(self, preset: str):
        label = {
            "selection": "Maya Selection",
            "file": "Maya File",
            "objects": "Maya Scene Objects",
        }.get(preset, "Maya Preset")
        port = self.command_router.maya.find_port()
        if not port:
            self.set_card("maya", "bad", "No commandPort")
            self.append(
                "[Maya Direct] No Maya commandPort found. Start Maya and run maya_command_port_setup.py.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "maya",
                "Maya commandPort was not found.",
                lambda l=label: {
                    "Maya Selection": self.direct_maya_selection,
                    "Maya File": self.direct_maya_file,
                    "Maya Scene Objects": self.direct_maya_scene_objects,
                }.get(l, self.direct_maya_selection)(),
                label,
            )
            return
        label, ok, result = self.command_router.execute_maya_preset(preset)
        self._emit_maya_preset(label, ok, result, port=port)

    def _emit_maya_preset(self, label, ok, result, port=None):
        port = port or self.command_router.maya.find_port()
        if not port:
            self.set_card("maya", "bad", "No commandPort")
            self.append(
                "[Maya Direct] No Maya commandPort found. Start Maya and run maya_command_port_setup.py.\n"
            )
            return
        code = {
            "Maya Selection": self.command_router.maya.get_selection_code(),
            "Maya File": self.command_router.maya.get_current_file_code(),
            "Maya Scene Objects": self.command_router.maya.get_scene_objects_code(),
        }.get(label, "")
        action = {
            "Maya Selection": "Query current Maya selection.",
            "Maya File": "Query current Maya scene file.",
            "Maya Scene Objects": "Query Maya scene objects.",
        }.get(label, "Run Maya preset.")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"[Maya Direct] {action}\n")
        self.set_card("maya", "busy", f"Executing :{port}")
        self.append(f"[Maya Direct] Executing on port {port}...\n")
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("maya", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("maya", "bad", "Execution failed")
            self.append(f"[Maya Direct Error] {result}\n")

    def direct_maya_call_function(
            self, function_path, args=None, kwargs=None, label="Maya Function"
    ):
        args = args or []
        kwargs = kwargs or {}
        self.last_user_prompt = f"[{label}] {function_path}"
        call_str = f"{function_path}(*{args}, **{kwargs})"
        self.append(f"\nYOU [{label}]:\n```python\n# Call function\n{call_str}\n```\n")
        port = self.command_router.maya.find_port()
        if not port:
            self.set_card("maya", "bad", "No commandPort")
            self.append(
                "[Maya Direct] No Maya commandPort found. Start Maya and run maya_command_port_setup.py.\n"
            )
            return
        self.set_card("maya", "busy", f"Executing :{port}")
        self.append(f"[Maya Direct] Executing on port {port}...\n")
        ok, result = self.command_router.maya.call_function(
            function_path, args=args, kwargs=kwargs
        )
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("maya", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("maya", "bad", "Execution failed")
            self.append(f"[Maya Direct Error] {result}\n")

    def direct_maya_call_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append(
                "\n[Maya Direct] Enter raw Maya Python or a JSON function payload first.\n"
            )
            return
        self.input.clear()
        try:
            maya_code = self.command_router.maya_natural_language_to_python(text)
            if maya_code:
                self.direct_maya_execute(maya_code, "Maya Natural")
                return
            if text.startswith("{"):
                data = json.loads(text)
                self.direct_maya_call_function(
                    data["function"],
                    args=data.get("args", []),
                    kwargs=data.get("kwargs", {}),
                    label="Maya Function",
                )
            else:
                self.direct_maya_execute(text, "Maya Execute")
        except Exception as e:
            self.append(f"\n[Maya Direct Parse Error] {e}\n")

    def direct_unreal_call(
            self, function_path, args=None, kwargs=None, label="Unreal Direct", timeout=30
    ):
        args = args or []
        kwargs = kwargs or {}
        self.last_user_prompt = f"[{label}] {function_path} args={args} kwargs={kwargs}"
        call_str = f"{function_path}(*{args}, **{kwargs})"
        self.append(f"\nYOU [{label}]:\n```python\n# Unreal call\n{call_str}\n```\n")
        port = self.command_router.unreal.find_port()
        if not port:
            self.set_card("unreal", "bad", "HTTP bridge not found")
            self.append(
                "[Unreal Direct] Unreal HTTP bridge not found on port 12347. Start your Unreal HTTP server first.\n"
            )
            self._prompt_launch_missing_dcc_bridge("unreal", "Unreal HTTP bridge was not found.", lambda: self.direct_unreal_call(function_path, args, kwargs, label, timeout), label)
            return
        self.set_card("unreal", "busy", f"Calling :{port}")
        self.append(f"[Unreal Direct] Calling {function_path} on port {port}...\n")
        response = self.command_router.unreal.safe_call(
            function_path, args=args, kwargs=kwargs, timeout=timeout, label=label
        )
        result = json.dumps(response, indent=2, default=str)
        if response.get("ok"):
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("unreal", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("unreal", "bad", "Call failed")
            self.append(
                f"[Unreal Direct Error] {response.get('error') or 'Call failed'}\n"
            )
            self.append("Tool Result:\n" + result + "\n")

    def direct_unreal_get_skeletons(self):
        label, ok, result = self.command_router.execute_unreal_preset("skeletons")
        self._emit_unreal_preset(
            label,
            ok,
            result,
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            ["Skeleton", "/Game/"],
            {},
        )

    def direct_unreal_get_static_meshes(self):
        label, ok, result = self.command_router.execute_unreal_preset("meshes")
        self._emit_unreal_preset(
            label,
            ok,
            result,
            "unreal_tools.get_skeletons.get_all_assets_of_type",
            ["StaticMesh", "/Game/"],
            {},
        )

    def direct_unreal_project_scan(self):
        label, ok, result = self.command_router.execute_unreal_operation(
            "project.scan_assets", {"directory": "/Game/"}
        )
        self.last_user_prompt = "[Unreal Project Scan] /Game/"
        self.append(
            "\nYOU [Unreal Project Scan]:\n```python\n# Scan core project asset classes under /Game/\n```\n"
        )
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            try:
                scan = json.loads(result)
                detail = (
                    "Project scanned"
                    if scan.get("connected")
                    else ("Using cache" if scan.get("cache_used") else "Scan partial")
                )
                self.set_card(
                    "unreal", "ok" if scan.get("connected") else "warn", detail
                )
            except Exception:
                self.set_card("unreal", "ok", "Project scanned")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("unreal", "bad", "Scan failed")
            self.append(f"[Unreal Project Scan Error] {result}\n")

    def direct_unreal_project_snapshot(self):
        label, ok, result = self.command_router.execute_unreal_operation(
            "project.snapshot", {"directory": "/Game/"}
        )
        self.unreal_project_snapshot = result
        self.last_user_prompt = "[Unreal Project Snapshot] /Game/"
        self.append(
            "\nYOU [Unreal Project Snapshot]:\n```python\n# Scan loaded level and core project asset classes under /Game/\n```\n"
        )
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            try:
                scan = json.loads(result)
                stages = scan.get("stages") or []
                failed = sum(1 for stage in stages if not stage.get("ok"))
                if scan.get("connected"):
                    self.set_card(
                        "unreal",
                        "ok",
                        f"Snapshot ready ({len(stages) - failed}/{len(stages)} stages)",
                    )
                elif scan.get("cache_used"):
                    self.set_card("unreal", "warn", "Snapshot from cache")
                else:
                    self.set_card("unreal", "warn", "Snapshot partial")
            except Exception:
                self.set_card("unreal", "ok", "Snapshot ready")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("unreal", "bad", "Snapshot incomplete")
            self.append(f"[Unreal Project Snapshot Warning/Error]\n{result}\n")

    def unreal_snapshot_decision_summary(self, snapshot):
        try:
            scan = (
                json.loads(snapshot or "{}")
                if isinstance(snapshot, str)
                else (snapshot or {})
            )
        except Exception:
            scan = {}
        data = scan.get("data") if isinstance(scan.get("data"), dict) else scan
        health = data.get("health") if isinstance(data.get("health"), dict) else {}
        stages = scan.get("stages") or []
        failed = sum(1 for stage in stages if not stage.get("ok"))
        stage_summary = scan.get("stage_summary") or ""
        if not stage_summary:
            labels = {
                "bridge_connected": "Bridge connected",
                "package_import": "Package import",
                "skeleton_probe": "Skeleton probe",
                "level_scan": "Level scan",
                "cache_status": "Cache",
            }
            parts = []
            for stage in stages:
                name = stage.get("name")
                if name not in labels:
                    continue
                if name == "cache_status":
                    state = "used" if stage.get("used_cache") else "fresh"
                else:
                    state = "OK" if stage.get("ok") else "failed"
                if stage.get("count") is not None:
                    state += f" ({stage.get('count')})"
                parts.append(f"{labels[name]}: {state}")
            stage_summary = " -> ".join(parts)
        counts = data.get("asset_counts") or {}
        return {
            "connected": bool(scan.get("connected") or health.get("connected")),
            "cache_used": bool(scan.get("cache_used")),
            "mode": scan.get("mode") or data.get("mode") or "snapshot",
            "level": data.get("loaded_level")
                     or health.get("loaded_level")
                     or "unknown",
            "stage_summary": stage_summary or "No staged scan details available",
            "stage_count": len(stages),
            "failed_count": failed,
            "skeleton_count": counts.get("Skeleton")
                              or health.get("bridge_probe_count")
                              or len(data.get("skeletons") or []),
        }

    def append_unreal_reasoning_summary(
            self, text, params, snapshot, previous_context=""
    ):
        if not bool(self.settings.get("show_reasoning_summary", True)):
            return
        self.append(
            self.unreal_prototype_reasoning_summary_text(
                text, params, snapshot, previous_context
            )
        )

    def unreal_prototype_reasoning_summary_text(
            self, text, params, snapshot, previous_context=""
    ):
        summary = self.unreal_snapshot_decision_summary(snapshot)
        research = ((params or {}).get("parameters") or {}).get("research_mode") or {}
        asset_awareness = ((params or {}).get("parameters") or {}).get(
            "asset_awareness"
        ) or {}
        operation_path = "gameplay.prototype_from_template"
        target_path = params.get("target_path", "unknown")
        if params.get("asset_path"):
            operation_path = "niagara.create_emitter"
            target_path = params.get("asset_path", "unknown")
        lines = [
            "\n[Reasoning Summary - Unreal]",
            "This is a safe summary of routing/context choices, not hidden chain-of-thought.",
            "Classified as: Unreal create/prototype request",
            f"Execution path: controlled Unreal operation `{operation_path}`",
            f"Template selected: {params.get('template', 'unknown')}",
            f"Target path: {target_path}",
            f"Live context: {'yes' if summary['connected'] else 'no'}",
            f"Cache used: {'yes' if summary['cache_used'] else 'no'}",
            f"Loaded level: {summary['level']}",
            f"Skeleton probe count: {summary['skeleton_count']}",
            f"Scan stages: {summary['stage_count']} total, {summary['failed_count']} failed",
            f"Stage summary: {summary['stage_summary']}",
            f"Docs/API cache requested: {'yes' if research.get('official_docs') else 'no'}",
            f"Project snapshot requested: {'yes' if research.get('project_snapshot') else 'no'}",
            f"Previous work context: {'included' if previous_context else 'none'}",
            f"Asset inspection plan: {'enabled' if asset_awareness.get('inspect_candidate_blueprints') else 'limited'}",
            "Safety plan: prefer existing assets, validate touched references/Blueprints, do not save automatically.",
            "\n",
        ]
        return "\n".join(lines)

    def confirm_unreal_operation_plan(self, plan):
        dlg = UnrealOperationConfirmDialog(plan, self)
        return dlg.exec() == QDialog.Accepted

    def build_unreal_graph_patch_from_plan(self, plan):
        rewrite_plan = (plan or {}).get("rewrite_plan") or {}
        candidate = rewrite_plan.get("graph_patch_candidate") or {}
        target_asset = (
                candidate.get("target_asset") or rewrite_plan.get("target_asset") or ""
        )
        target_graph = (
                candidate.get("target_graph") or rewrite_plan.get("target_graph") or ""
        )
        operations = candidate.get("operations") or []
        if not target_asset or not target_graph or not operations:
            return None
        return build_patch(
            target_asset,
            target_graph,
            operations=operations,
            compile_expectations=rewrite_plan.get("compile_expectations") or None,
            metadata={
                "request_text": rewrite_plan.get("request_text")
                                or (plan or {}).get("user_request")
                                or "",
                "process_detection": rewrite_plan.get("process_detection") or {},
                "open_focus_operations": rewrite_plan.get("open_focus_operations") or [],
                "focus_targets": rewrite_plan.get("focus_targets") or [],
                "layout_contract": rewrite_plan.get("graph_layout_contract") or [],
                "post_apply_validation": rewrite_plan.get("post_apply_validation") or [],
                "progress_stages": rewrite_plan.get("graph_edit_progress_stages") or [],
                "threading_contract": rewrite_plan.get("graph_edit_threading_contract") or {},
                "edit_intelligence": rewrite_plan.get("graph_edit_intelligence") or {},
                "preflight_checks": rewrite_plan.get("preflight_checks") or [],
                "insertion_strategy": rewrite_plan.get("insertion_strategy") or [],
                "troubleshooting_path": rewrite_plan.get("troubleshooting_path") or [],
                "repair_strategies": rewrite_plan.get("repair_strategies") or [],
            },
        )

    def format_unreal_graph_patch_result(self, result):
        try:
            from services.chat_report_service import format_unreal_change_report

            return format_unreal_change_report(result)
        except Exception:
            if not result:
                return "No graph patch result available."
            return (
                "Graph patch execution:\n"
                f"Mode: {result.get('mode', 'unknown')}\n"
                f"Applied: {'yes' if result.get('applied') else 'no'}\n"
                f"Target asset: {((result.get('request') or {}).get('target_asset') or '')}\n"
                f"Target graph: {((result.get('request') or {}).get('target_graph') or '')}"
            )

    def direct_unreal_prototype_from_text(self, text):
        import threading
        import time

        from services.ai_work_memory_service import (
            record_ai_work,
            relevant_ai_work_context,
        )
        from services.unreal.unreal_operation_service import (
            build_unreal_niagara_create_params,
            build_unreal_prototype_params,
            is_unreal_niagara_create_request,
        )

        self.append(f"\nYOU [Unreal Prototype]:\n{text}\n")
        if bool(self.settings.get("show_reasoning_summary", True)):
            self.append(
                "[Reasoning Summary - Unreal]\n"
                "Classified this as an Unreal create/prototype shortcut. "
                "I will gather/refresh project context, choose a controlled template operation, "
                "then show the exact target/template before calling Unreal.\n"
            )

        progress = {
            "active": True,
            "phase": "starting",
            "started": time.time(),
            "last": "",
        }

        def post_progress(message):
            progress["last"] = message
            self.thread_log_message.emit(f"[Unreal Prototype Progress] {message}\n")

        def heartbeat():
            last_phase = ""
            while progress.get("active"):
                time.sleep(6)
                if not progress.get("active"):
                    break
                phase = progress.get("phase", "working")
                elapsed = int(time.time() - progress.get("started", time.time()))
                if elapsed > 900:
                    progress["active"] = False
                    self.thread_log_message.emit(
                        "[Unreal Prototype Progress] Stopped progress heartbeat after 15 minutes. "
                        "The Unreal operation may still be running; check Unreal output/log if the UI has not returned.\n"
                    )
                    break
                if phase != last_phase:
                    last_phase = phase
                self.thread_log_message.emit(
                    f"[Unreal Prototype Progress] Still working after {elapsed}s. Current step: {phase}.\n"
                )

        def run_prototype():
            threading.Thread(target=heartbeat, daemon=True).start()
            # Find Unreal bridge port inside thread
            progress["phase"] = "checking Unreal HTTP bridge"
            port = self.command_router.unreal.find_port()
            if not port:
                progress["active"] = False
                QTimer.singleShot(
                    0, lambda: self.set_card("unreal", "bad", "HTTP bridge not found")
                )
                self.thread_log_message.emit(
                    "[Unreal Prototype] Unreal HTTP bridge not found. Start your Unreal HTTP server first.\n"
                )
                return
            post_progress(f"Bridge found on port {port}. Preparing project context.")
            direct_niagara_create = is_unreal_niagara_create_request(text)
            snapshot = getattr(self, "unreal_project_snapshot", "")
            previous_context = ""
            if direct_niagara_create:
                progress["phase"] = "building niagara create parameters"
                params = build_unreal_niagara_create_params(text)
                post_progress(
                    "Fast-path Niagara create detected. Skipping heavyweight project snapshot refresh."
                )
                self.thread_log_message.emit(
                    "[Unreal Niagara Create] Fast-path typed Niagara creation selected. Using live bridge only and skipping full project snapshot refresh.\n"
                )
            else:
                if not snapshot:
                    progress["phase"] = "scanning project snapshot"
                    QTimer.singleShot(
                        0, lambda: self.set_card("unreal", "busy", f"Snapshot :{port}")
                    )
                    self.thread_log_message.emit(
                        "[Unreal Prototype] No cached project snapshot yet. Scanning loaded level and core assets first...\n"
                    )
                    _label, snapshot_ok, snapshot_result = (
                        self.command_router.execute_unreal_operation(
                            "project.snapshot", {"directory": "/Game/"}
                        )
                    )
                    self.unreal_project_snapshot = snapshot_result
                    snapshot = snapshot_result
                    if snapshot_ok:
                        post_progress(
                            "Project snapshot completed. Building controlled prototype parameters."
                        )
                        self.thread_log_message.emit(
                            "[Unreal Prototype] Project snapshot ready. Building prototype request from real asset context...\n"
                        )
                    else:
                        res_str = f"[Unreal Prototype] Snapshot partial; continuing with available context.\n{snapshot_result}\n"
                        post_progress(
                            "Project snapshot was partial. Continuing with available context."
                        )
                        self.thread_log_message.emit(res_str)
                else:
                    post_progress(
                        "Using cached project snapshot. Building controlled prototype parameters."
                    )
                    self.thread_log_message.emit(
                        "[Unreal Prototype] Using cached project snapshot as asset context.\n"
                    )

                progress["phase"] = "loading previous AI work context"
                previous_context = relevant_ai_work_context(
                    self.settings,
                    text,
                    host="unreal",
                    max_chars=int(
                        self.settings.get("ai_work_memory_max_context_chars", 6000)
                    ),
                )
                progress["phase"] = "building operation parameters"
                params = build_unreal_prototype_params(
                    text,
                    snapshot=snapshot,
                    settings=self.settings,
                    previous_work_context=previous_context,
                )
            roots = self.project_roots() if hasattr(self, "project_roots") else []
            plan = self.command_router.plan_unreal_request(
                text,
                project_root=roots[0] if roots else None,
                settings=self.settings,
            )
            if plan.get("high_risk_graph_rewrite"):
                self.thread_log_message.emit(
                    "[Unreal Safety] High-risk graph rewrite request detected. "
                    "Direct graph rewrites should only proceed through controlled template operations with explicit confirmation.\n"
                )
            accepted = False
            decision_made = False

            def _confirm():
                nonlocal accepted, decision_made
                accepted = self.confirm_unreal_operation_plan(plan)
                decision_made = True

            QTimer.singleShot(0, _confirm)
            wait_limit = 10 if direct_niagara_create else 30
            wait_started = time.time()
            while time.time() - wait_started < wait_limit and not decision_made:
                time.sleep(0.05)
                if progress.get("active") is False:
                    return
            if not decision_made or not accepted:
                progress["active"] = False
                self.thread_log_message.emit(
                    "[Unreal Safety] Operation cancelled before apply.\n"
                )
                return
            prepared_target = (
                    params.get("target_path") or params.get("asset_path") or "unknown"
            )
            post_progress(
                f"Prepared template={params.get('template')} target={prepared_target}. Ready to call Unreal."
            )

            operation_key = (
                "niagara.create_emitter"
                if direct_niagara_create
                else "gameplay.prototype_from_template"
            )
            self.last_user_prompt = json.dumps(
                {"operation": operation_key, "kwargs": params},
                indent=2,
            )
            if bool(self.settings.get("show_reasoning_summary", True)):
                summary = self.unreal_prototype_reasoning_summary_text(
                    text, params, snapshot, previous_context
                )
                self.thread_log_message.emit(summary)

            QTimer.singleShot(
                0, lambda: self.set_card("unreal", "busy", f"Prototyping :{port}")
            )
            if direct_niagara_create:
                self.thread_log_message.emit(
                    "[Unreal Niagara Create] Calling typed Niagara creation operation. "
                    "This should create a prototype-safe Niagara asset and return its created name/path when the Unreal-side endpoint is available.\n"
                )
            else:
                self.thread_log_message.emit(
                    "[Unreal Prototype] Calling controlled editor operation. "
                    "The Unreal side should inspect candidate assets/Blueprints, create animation slots, wire template changes, then validate. "
                    "Unsafe raw graph rewrites should be avoided unless a controlled target/template path is available.\n"
                )

            progress["phase"] = "waiting for Unreal prototype operation"
            label, ok, result = self.command_router.execute_unreal_operation(
                operation_key, params
            )
            post_progress(
                f"Unreal operation returned ok={str(ok).lower()}. Recording result."
            )

            self.last_tool_output = result
            self.last_assistant_output = result
            progress["phase"] = "recording AI work result"
            record_ai_work(
                self.settings,
                host="unreal",
                mode="prototype",
                goal=text,
                params=params,
                label=label,
                ok=ok,
                result=result,
            )

            if ok:
                QTimer.singleShot(
                    0, lambda: self.set_card("unreal", "ok", "Prototype attempted")
                )
                try:
                    from services.chat_report_service import format_unreal_operation_report

                    report = format_unreal_operation_report(
                        result,
                        operation=operation_key,
                        ok=ok,
                        request=params,
                        detail_text=str(result),
                    )
                    self.thread_log_message.emit(
                        "ASSISTANT [Unreal Change Report]:\n" + report + "\n"
                    )
                except Exception:
                    self.thread_log_message.emit("Tool Result:\n" + result + "\n")
                progress["phase"] = "validating references and Blueprint compile"
                post_progress("Running validation without saving.")
                validate_target = params.get("target_path") or params.get("asset_path")
                validate_label, validate_ok, validate_result = (
                    self.command_router.execute_unreal_operation(
                        "validate.references",
                        {
                            "paths": [validate_target] if validate_target else [],
                            "compile_blueprints": True,
                            "save": False,
                        },
                    )
                )
                val_str = f"\n[{validate_label}]\n{validate_result}\n"
                self.thread_log_message.emit(val_str)
                if not validate_ok:
                    QTimer.singleShot(
                        0,
                        lambda: self.set_card(
                            "unreal", "warn", "Prototype validation warning"
                        ),
                    )
            else:
                QTimer.singleShot(
                    0, lambda: self.set_card("unreal", "bad", "Prototype failed")
                )
                try:
                    from services.chat_report_service import format_unreal_operation_report

                    err_report = format_unreal_operation_report(
                        result,
                        operation=operation_key,
                        ok=ok,
                        request=params,
                        detail_text=str(result),
                    )
                    err_str = f"ASSISTANT [Unreal Change Report]:\n{err_report}\n"
                except Exception:
                    err_str = f"[Unreal Prototype Error]\n{result}\n"
                self.thread_log_message.emit(err_str)
            progress["active"] = False
            self.thread_log_message.emit(
                "[Unreal Prototype Progress] Finished Unreal prototype workflow.\n"
            )

        threading.Thread(target=run_prototype, daemon=True).start()

    def direct_unreal_debug_from_text(self, text):
        from services.ai_work_memory_service import record_ai_work
        from services.unreal.unreal_operation_service import build_unreal_debug_params

        port = self.command_router.unreal.find_port()
        if not port:
            self.set_card("unreal", "bad", "HTTP bridge not found")
            self.append(
                "[Unreal Debug] Unreal HTTP bridge not found. Start the Unreal HTTP server first.\n"
            )
            return

        params = build_unreal_debug_params(text)
        self.last_user_prompt = json.dumps(
            {"operation": "project.debug", "kwargs": params}, indent=2
        )
        self.append(f"\nYOU [Unreal Debug]:\n{text}\n")
        self.set_card("unreal", "busy", f"Debugging :{port}")
        scope = params.get("parameters", {}).get("scope", "full_project")
        self.append(
            f"[Unreal Debug] Running {scope} diagnostics: project snapshot, reference validation, "
            "and Blueprint compile checks where supported. Save is disabled.\n"
        )
        label, ok, result = self.command_router.execute_unreal_operation(
            "project.debug", params
        )
        self.last_tool_output = result
        self.last_assistant_output = result
        record_ai_work(
            self.settings,
            host="unreal",
            mode="debug",
            goal=text,
            params=params,
            label=label,
            ok=ok,
            result=result,
        )
        if ok:
            self.set_card("unreal", "ok", "Debug complete")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("unreal", "warn", "Debug found issues")
            self.append(f"[{label}]\n{result}\n")

    def extract_unreal_blueprint_target_name(self, text):
        import re

        text = text or ""
        path_match = re.search(r"(/Game/[A-Za-z0-9_./-]+)", text)
        if path_match:
            return path_match.group(1).rstrip(".,;:)")

        for pattern in (
                r"\b(BP_[A-Za-z0-9_]+)\b",
                r"\b(ABP_[A-Za-z0-9_]+)\b",
                r"\b([A-Za-z0-9_]+AnimBlueprint)\b",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).rstrip(".,;:)")
        return ""

    def is_unreal_named_blueprint_inspect_request(self, text):
        lower = (text or "").lower()
        if not self.extract_unreal_blueprint_target_name(text):
            return False
        inspect_terms = (
            "inspect",
            "analyze",
            "analyse",
            "look at",
            "find",
            "scan",
            "understand",
            "what could",
            "what can",
            "animgraph",
            "animation graph",
            "blueprint",
        )
        return any(term in lower for term in inspect_terms)

    def direct_unreal_blueprint_analysis_from_text(self, text):
        import threading


        from services.ai_work_memory_service import record_ai_work

        target = self.extract_unreal_blueprint_target_name(text)
        if not target:
            self.append(
                "[Unreal Blueprint Inspect] No named Blueprint target found. Try BP_Player or /Game/.../BP_Player.\n"
            )
            return

        port = self.command_router.unreal.find_port()
        if not port:
            self.set_card("unreal", "bad", "HTTP bridge not found")
            self.append(
                "[Unreal Blueprint Inspect] Unreal HTTP bridge not found. Start the Unreal HTTP server first.\n"
            )
            return

        self.last_user_prompt = json.dumps(
            {
                "operation": "blueprint.dynamic_inspect",
                "asset_name": target,
                "prompt": text,
            },
            indent=2,
        )
        self.append(f"\nYOU [Unreal Blueprint Inspect]:\n{text}\n")
        cpp_status = (
            "Unreal C++ bridge planning is enabled, so missing Python-only AnimGraph details may be escalated to reflected C++ capabilities."
            if self.unreal_cpp_bridge_enabled()
            else "Unreal C++ bridge planning is disabled, so this will stay Python/editor-API first and mark deeper AnimGraph details as unavailable."
        )
        self.append(
            "[Reasoning Summary - Unreal]\n"
            f"Targeted named Blueprint `{target}`. I will execute a read-only Python reflection probe in the editor, "
            "then report what was directly observed versus what may need a deeper AnimGraph exporter. "
            f"{cpp_status}\n"
        )
        self.append(
            f"[Unreal Blueprint Inspect] Bridge connected on port {port}. Running dynamic Python asset lookup...\n"
        )
        self.set_card("unreal", "busy", f"Inspecting :{port}")

        def run_inspect():
            self.thread_log_message.emit(
                "[Unreal Blueprint Inspect] Resolving Blueprint by path/name with normalized matching...\n"
            )
            label, ok, result = self.command_router.execute_unreal_operation(
                "blueprint.dynamic_inspect",
                {
                    "asset_name": target,
                    "timeout": 45,
                    "allow_cpp_bridge": self.unreal_cpp_bridge_enabled(),
                },
            )
            self.last_tool_output = result
            self.last_assistant_output = result
            record_ai_work(
                self.settings,
                host="unreal",
                mode="inspect",
                goal=text,
                params={
                    "asset_name": target,
                    "operation": "blueprint.dynamic_inspect",
                    "allow_cpp_bridge": self.unreal_cpp_bridge_enabled(),
                },
                label=label,
                ok=ok,
                result=result,
            )
            if ok:
                QTimer.singleShot(
                    0, lambda: self.set_card("unreal", "ok", "Blueprint inspected")
                )
                self.thread_log_message.emit(
                    "[Unreal Blueprint Inspect] Reflection probe complete. Result below is live editor data.\n"
                )
                self.thread_log_message.emit("Tool Result:\n" + result + "\n")
            else:
                QTimer.singleShot(
                    0, lambda: self.set_card("unreal", "warn", "Inspect incomplete")
                )
                self.thread_log_message.emit(f"[{label}]\n{result}\n")

        threading.Thread(target=run_inspect, daemon=True).start()

    def direct_dcc_editor_operation_from_text(self, host, mode, text):
        from services.ai_work_memory_service import (
            record_ai_work,
            relevant_ai_work_context,
        )
        from services.dcc_operation_service import (
            attach_operation_context,
            build_dcc_debug_params,
            build_dcc_prototype_params,
        )
        from services.unreal.unreal_operation_service import research_mode_from_settings

        host_label = host.replace("_", " ").title()
        mode_label = "Prototype" if mode == "prototype" else "Debug"
        text = text or f"{host_label} {mode_label.lower()} current scene"
        self.append(f"\nYOU [{host_label} {mode_label}]:\n{text}\n")
        self.set_card(host, "busy", mode_label)
        self.append(f"[{host_label} {mode_label}] Gathering host context first...\n")
        context = self.command_router.dcc_context_snapshot(host)
        if mode == "prototype":
            params = build_dcc_prototype_params(host, text, context=context)
        else:
            params = build_dcc_debug_params(host, text, context=context)
        previous_context = relevant_ai_work_context(
            self.settings,
            text,
            host=host,
            max_chars=int(self.settings.get("ai_work_memory_max_context_chars", 6000)),
        )
        params = attach_operation_context(
            params,
            previous_work_context=previous_context,
            research_mode=research_mode_from_settings(self.settings),
        )
        self.last_user_prompt = json.dumps(
            {"host": host, "mode": mode, "kwargs": params}, indent=2
        )
        self.append(
            f"[{host_label} {mode_label}] Calling controlled host operation endpoint. "
            "If the host package endpoint is missing, the result will name the function to add.\n"
        )
        label, ok, result = self.command_router.execute_dcc_editor_operation(
            host, mode, params
        )
        self.last_tool_output = result
        self.last_assistant_output = result
        record_ai_work(
            self.settings,
            host=host,
            mode=mode,
            goal=text,
            params=params,
            label=label,
            ok=ok,
            result=result,
        )
        if ok:
            self.set_card(host, "ok", f"{mode_label} complete")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card(host, "warn", f"{mode_label} needs endpoint")
            self.append(f"[{label}]\n{result}\n")

    def direct_unreal_level_scan(self):
        payload = {
            "function": "unreal_tools.level.scan_loaded_level",
            "args": [],
            "kwargs": {},
        }
        self.direct_unreal_call(
            payload["function"],
            args=payload["args"],
            kwargs=payload["kwargs"],
            label="Unreal Loaded Level Scan",
        )

    def is_simple_unreal_question(self, text):
        lower = (text or "").lower()
        simple_terms = (
            "what level",
            "current level",
            "loaded level",
            "selected assets",
            "selected actors",
            "what is selected",
            "show selected",
            "list blueprints",
            "find blueprint",
            "inspect",
            "show asset",
            "what project",
        )
        heavy_terms = (
            "rewrite",
            "create",
            "implement",
            "build",
            "modify",
            "change",
            "replace",
            "rewire",
            "connect",
            "disconnect",
            "graph",
            "animgraph",
            "control rig",
            "motion matching",
        )
        return any(term in lower for term in simple_terms) and not any(
            term in lower for term in heavy_terms
        )

    def direct_unreal_simple_question_from_text(self, text):
        import threading

        def run_simple():
            try:
                self.thread_log_message.emit(f"\nYOU [Unreal Quick]:\n{text}\n")
                lower = (text or "").lower()
                label = "Unreal Quick"
                ok = False
                result = ""
                raw_result = None
                if any(
                        term in lower
                        for term in ("what level", "current level", "loaded level")
                ):
                    response = self.command_router.unreal.safe_call(
                        "unreal_tools.level.scan_loaded_level",
                        kwargs={"include_components": False, "max_actors": 1},
                        timeout=2.0,
                        retries=0,
                        retry_safe=True,
                        label="fast_level",
                        operation="fast_level",
                    )
                    label = "Unreal Current Level"
                    ok = bool(response.get("ok"))
                    data = response.get("data") if ok else response
                    raw_result = data
                    parsed = data
                    if isinstance(parsed, str):
                        try:
                            parsed = json.loads(parsed)
                        except Exception:
                            pass
                    if isinstance(parsed, dict):
                        result = str(
                            parsed.get("level_name")
                            or parsed.get("current_level")
                            or "Unknown"
                        )
                    else:
                        result = str(parsed)
                elif "select" in lower and "asset" not in lower:
                    response = self.command_router.unreal.safe_call(
                        "unreal_tools.level.scan_loaded_level",
                        kwargs={"include_components": False, "max_actors": 1},
                        timeout=2.0,
                        retries=0,
                        retry_safe=True,
                        label="fast_selected",
                        operation="fast_selected",
                    )
                    label = "Unreal Selected Actors"
                    ok = bool(response.get("ok"))
                    data = response.get("data") if ok else response
                    raw_result = data
                    parsed = data
                    if isinstance(parsed, str):
                        try:
                            parsed = json.loads(parsed)
                        except Exception:
                            pass
                    if isinstance(parsed, dict):
                        items = parsed.get("selected_actors") or []
                        result = "Selected actors: " + (
                            ", ".join(str(x) for x in items[:12]) if items else "none"
                        )
                    else:
                        try:
                            items = (
                                self.command_router.unreal_scanner.get_selected_actors()
                            )
                        except Exception:
                            items = []
                        result = "Selected actors: " + (
                            ", ".join(str(x) for x in items[:12])
                            if items
                            else str(parsed)
                        )
                elif "select" in lower and "asset" in lower:
                    label = "Unreal Selected Assets"
                    selected_context = {}
                    try:
                        selected_context = (
                            self.command_router.unreal_scanner.build_selected_context(
                                text
                            )
                        )
                    except Exception:
                        selected_context = {}
                    ok = True
                    raw_result = selected_context
                    selected_assets = list(
                        selected_context.get("selected_assets") or []
                    )
                    primary_category = (
                            selected_context.get("primary_asset_category") or "asset"
                    )
                    focus = selected_context.get("focus") or "selection"
                    selection_context = selected_context.get("selection_context") or {}
                    if not selected_assets:
                        result = "Selected assets: none"
                    elif primary_category in {
                        "blueprint",
                        "anim_blueprint",
                        "control_rig",
                    }:
                        functions = selection_context.get("functions") or []
                        graphs = selection_context.get("graphs") or []
                        variables = selection_context.get("variables") or []
                        function_names = [
                            str(item.get("name") or item) for item in functions[:12]
                        ]
                        graph_names = [
                            str(item.get("name") or item) for item in graphs[:10]
                        ]
                        variable_names = [
                            str(item.get("name") or item) for item in variables[:10]
                        ]
                        kind_label = {
                            "blueprint": "Selected Blueprint",
                            "anim_blueprint": "Selected Animation Blueprint",
                            "control_rig": "Selected Control Rig",
                        }.get(primary_category, "Selected Asset")
                        result_parts = [
                            f"{kind_label}: {selection_context.get('asset_name') or selected_assets[0]}",
                            f"Focus: {focus}",
                            f"Functions: {', '.join(function_names) if function_names else 'none found'}",
                            f"Graphs: {', '.join(graph_names) if graph_names else 'none found'}",
                        ]
                        if variable_names:
                            result_parts.append(
                                f"Variables: {', '.join(variable_names)}"
                            )
                        result = "\n".join(result_parts)
                    elif primary_category in {"motion_matching", "retarget"}:
                        followups = selection_context.get("recommended_followups") or []
                        label_text = (
                            "Selected Motion Matching Asset"
                            if primary_category == "motion_matching"
                            else "Selected Retarget Asset"
                        )
                        result_parts = [
                            f"{label_text}: {selected_assets[0]}",
                            f"Focus: {focus}",
                        ]
                        if followups:
                            result_parts.append(
                                "Next context: "
                                + " | ".join(str(x) for x in followups[:3])
                            )
                        result = "\n".join(result_parts)
                    else:
                        result = "Selected assets: " + ", ".join(
                            str(item) for item in selected_assets[:12]
                        )
                else:
                    target = self.extract_unreal_blueprint_target_name(text)
                    if target:
                        label, ok, result = (
                            self.command_router.execute_unreal_operation(
                                "blueprint.dynamic_inspect",
                                {"asset_name": target, "timeout": 20},
                            )
                        )
                    else:
                        label, ok, result = (
                            self.command_router.execute_unreal_operation(
                                "project.snapshot",
                                {"mode": "quick", "directory": "/Game/"},
                            )
                        )
                if ok:
                    self.last_tool_output = (
                        result
                        if isinstance(result, str)
                        else json.dumps(result, indent=2, default=str)
                    )
                    self.last_assistant_output = self.last_tool_output
                    from services.interaction_quality_service import format_tool_result_aesthetic
                    formatted = format_tool_result_aesthetic(result)
                    self.thread_log_message.emit(f"Tool Result:\n{formatted}\n")
                else:
                    self.thread_log_message.emit(f"[{label}]\n{result}\n")
            except Exception as exc:
                self.thread_log_message.emit(f"[Unreal Quick Error] {exc}\n")

        self.set_live_process("Calling Unreal directly")
        threading.Thread(target=run_simple, daemon=True).start()

    def direct_unreal_inspect_asset_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append(
                "\n[Unreal Inspect Asset] Enter an asset path such as /Game/Blueprints/BP_Player in the input box first.\n"
            )
            return
        self.input.clear()
        try:
            if text.startswith("{"):
                data = json.loads(text)
                asset_path = (
                        data.get("asset_path")
                        or data.get("path")
                        or data.get("object_path")
                )
                operation = data.get("operation") or "assets.inspect"
            else:
                asset_path = text.strip("'\" ")
                operation = (
                    "blueprint.scan"
                    if "bp_" in asset_path.lower() or "blueprint" in asset_path.lower()
                    else "assets.inspect"
                )
            if not asset_path:
                self.append(
                    "\n[Unreal Inspect Asset] Could not find asset_path in the input.\n"
                )
                return
            label, ok, result = self.command_router.execute_unreal_operation(
                operation, {"asset_path": asset_path}
            )
            self.last_user_prompt = f"[{label}] {asset_path}"
            if ok:
                self.last_tool_output = result
                self.last_assistant_output = result
                self.set_card("unreal", "ok", "Asset inspected")
                self.append(
                    f"\nYOU [{label}]:\n```text\n{asset_path}\n```\nTool Result:\n{result}\n"
                )
            else:
                self.set_card("unreal", "bad", "Inspect failed")
                self.append(f"\n[Unreal Inspect Asset Error] {result}\n")
        except Exception as e:
            self.append(f"\n[Unreal Inspect Asset Parse Error] {e}\n")

    def show_unreal_operation_catalog(self):
        self.append("\n" + self.command_router.unreal_operation_catalog_text() + "\n")

    def show_unreal_capability_validation(self):
        roots = self.project_roots() if hasattr(self, "project_roots") else []
        project_root = roots[0] if roots else ""
        dialog = UnrealCapabilityValidationDialog(
            project_root=project_root,
            intel_service=getattr(self, "intel_service", None),
            parent=self,
        )
        dialog.exec()

    def direct_unreal_create_cpp_wrapper_from_text(self):
        if not self.unreal_cpp_bridge_enabled():
            self.append(
                "\n[Unreal C++ Wrapper] UE C++ is disabled. Enable the `UE C++` toggle first so Blueprint-only projects stay protected.\n"
            )
            return

        text = self.input.text().strip()
        if not text:
            text, ok = QInputDialog.getMultiLineText(
                self,
                "Create Unreal Python Wrapper",
                "Describe the missing Unreal capability to expose through reflected C++:",
                "Inspect AnimGraph nodes and pins for an Animation Blueprint",
            )
            if not ok:
                return
            text = text.strip()
        if not text:
            self.append("\n[Unreal C++ Wrapper] No capability description provided.\n")
            return

        project_root = self.settings.get("active_project", "")
        if not project_root:
            self.append("\n[Unreal C++ Wrapper] Load an Unreal project folder first.\n")
            return

        from services.unreal.unreal_cpp_wrapper_service import create_unreal_cpp_wrapper_plan

        preview = create_unreal_cpp_wrapper_plan(project_root, text, apply=False)
        self.append("\nYOU [Unreal C++ Wrapper]:\n" + text + "\n")
        self.append(
            "[Reasoning Summary - Unreal]\n"
            "This promotes a missing Python/editor API capability into a reflected C++ bridge function. "
            "The generated function is intended to be callable from Unreal Python after the project/plugin compiles.\n"
        )
        self.append(
            "Wrapper Plan:\n"
            + json.dumps(preview.to_dict(), indent=2, default=str)
            + "\n"
        )
        if preview.warnings:
            self.set_card("unreal", "warn", "Wrapper needs project")
            return

        apply = QMessageBox.question(
            self,
            "Create Unreal C++ Wrapper",
            "Create/update the AIStudioBridge plugin files in the active Unreal project?\n\n"
            "This writes source files only. It will not compile or run C++ automatically.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if apply != QMessageBox.Yes:
            self.set_card("unreal", "warn", "Wrapper previewed")
            return

        try:
            result = create_unreal_cpp_wrapper_plan(project_root, text, apply=True)
            self.last_tool_output = json.dumps(result.to_dict(), indent=2, default=str)
            self.last_assistant_output = self.last_tool_output
            self.set_card("unreal", "ok", "Wrapper files created")
            self.append("Tool Result:\n" + self.last_tool_output + "\n")
        except Exception as e:
            self.set_card("unreal", "bad", "Wrapper failed")
            self.append(f"[Unreal C++ Wrapper Error] {e}\n")

    def _emit_unreal_preset(self, label, ok, result, fn, args, kwargs):
        self.last_user_prompt = f"[{label}] {fn} args={args} kwargs={kwargs}"
        call_str = f"{fn}(*{args}, **{kwargs})"
        self.append(f"\nYOU [{label}]:\n```python\n# Unreal preset\n{call_str}\n```\n")
        port = self.command_router.unreal.find_port()
        if not port:
            self.set_card("unreal", "bad", "HTTP bridge not found")
            self.append(
                "[Unreal Direct] Unreal HTTP bridge not found on port 12347. Start your Unreal HTTP server first.\n"
            )
            return
        self.set_card("unreal", "busy", f"Calling :{port}")
        self.append(f"[Unreal Direct] Calling {fn} on port {port}...\n")
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("unreal", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("unreal", "bad", "Call failed")
            self.append(f"[Unreal Direct Error] {result}\n")

    def direct_unreal_call_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append(
                "\n[Unreal Direct] Enter a function path or JSON payload in the input box first.\n"
            )
            return
        self.input.clear()
        try:
            fn, args, kwargs = self.command_router.unreal.parse_input(text)
            self.direct_unreal_call(fn, args=args, kwargs=kwargs, label="Unreal Direct")
        except Exception as e:
            self.append(f"\n[Unreal Direct Parse Error] {e}\n")

    def direct_blender_execute(self, code, label="Blender Direct", timeout=10):
        port = self.command_router.blender.find_port()
        if not port:
            self.set_card("blender", "bad", "Bridge not found")
            self.last_user_prompt = f"[{label}] {code}"
            self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
            self.append(
                "[Blender Direct] No Blender bridge found. Run Install_Blender_AI_Studio_Bridge.bat once, then restart Blender.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "blender",
                "Blender bridge was not found.",
                lambda l=label: {
                    "Blender Selection": self.direct_blender_selection,
                    "Blender File": self.direct_blender_file,
                    "Blender Scene Objects": self.direct_blender_scene_objects,
                }.get(l, self.direct_blender_selection)(),
                label,
            )
            return
        self.set_card("blender", "busy", f"Executing :{port}")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        self.append(f"[Blender Direct] Executing on port {port}...\n")
        ok, result = self.command_router.blender.execute(code, timeout=timeout)
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("blender", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("blender", "bad", "Execution failed")
            self.append(f"[Blender Direct Error] {result}\n")

    def direct_blender_selection(self):
        label, ok, result = self.command_router.execute_blender_preset("selection")
        self._emit_blender_preset(label, ok, result)

    def direct_blender_file(self):
        label, ok, result = self.command_router.execute_blender_preset("file")
        self._emit_blender_preset(label, ok, result)

    def direct_blender_scene_objects(self):
        label, ok, result = self.command_router.execute_blender_preset("objects")
        self._emit_blender_preset(label, ok, result)

    def _emit_blender_preset(self, label, ok, result):
        port = self.command_router.blender.find_port()
        if not port:
            self.set_card("blender", "bad", "Bridge not found")
            self.append(
                "[Blender Direct] No Blender bridge found. Run Install_Blender_AI_Studio_Bridge.bat once, then restart Blender.\n"
            )
            self._prompt_launch_missing_dcc_bridge("blender", "Blender bridge was not found.", lambda: self.direct_blender_execute(code, label, timeout), label)
            return
        code = {
            "Blender Selection": self.command_router.blender.get_selection_code(),
            "Blender File": self.command_router.blender.get_current_file_code(),
            "Blender Scene Objects": self.command_router.blender.get_scene_objects_code(),
        }.get(label, "")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        self.set_card("blender", "busy", f"Executing :{port}")
        self.append(f"[Blender Direct] Executing on port {port}...\n")
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("blender", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("blender", "bad", "Execution failed")
            self.append(f"[Blender Direct Error] {result}\n")

    def direct_blender_call_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append(
                "\n[Blender Direct] Enter raw Blender Python or a JSON function payload first.\n"
            )
            return
        self.input.clear()
        try:
            port = self.command_router.blender.find_port()
            if not port:
                self.set_card("blender", "bad", "Bridge not found")
                self.append(
                    "[Blender Direct] No Blender bridge found. Run Install_Blender_AI_Studio_Bridge.bat once, then restart Blender.\n"
                )
                self._prompt_launch_missing_dcc_bridge(
                    "blender",
                    "Blender bridge was not found.",
                    lambda t=text: (self.input.setText(t), self.direct_blender_call_from_text()),
                    "Blender Execute",
                )
                return
            mode, data = self.command_router.blender.parse_input(text)
            label = "Blender Function" if mode == "function" else "Blender Execute"
            self.last_user_prompt = f"[{label}] {text}"
            if mode == "function":
                func_path = data.get("function", "")
                args = data.get("args", [])
                kwargs = data.get("kwargs", {})
                self.append(
                    f"\nYOU [{label}]:\n```python\n# Blender function call\n{func_path}(*{args}, **{kwargs})\n```\n"
                )
            else:
                self.append(f"\nYOU [{label}]:\n```python\n{text}\n```\n")
            self.set_card("blender", "busy", f"Executing :{port}")
            self.append(f"[Blender Direct] Executing on port {port}...\n")
            if mode == "function":
                ok, result = self.command_router.blender.call_function(
                    data["function"],
                    args=data.get("args", []),
                    kwargs=data.get("kwargs", {}),
                )
            else:
                ok, result = self.command_router.blender.execute(text)
            if ok:
                self.last_tool_output = result
                self.last_assistant_output = result
                self.set_card("blender", "ok", "Connected")
                self.append("Tool Result:\n" + result + "\n")
            else:
                self.set_card("blender", "bad", "Execution failed")
                self.append(f"[Blender Direct Error] {result}\n")
        except Exception as e:
            self.append(f"\n[Blender Direct Parse Error] {e}\n")

    def direct_unity_execute(self, code, label="Unity Direct", timeout=10):
        port = self.command_router.unity.find_port()
        if not port:
            self.set_card("unity", "bad", "Bridge not found")
            self.last_user_prompt = f"[{label}] {code}"
            self.append(f"\nYOU [{label}]:\n```csharp\n{code}\n```\n")
            self.append(
                "[Unity Direct] No Unity bridge found. Ensure your Unity Editor plugin is active on port 7041.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "unity",
                "Unity bridge was not found.",
                lambda l=label: {
                    "Unity Selection": self.direct_unity_selection,
                    "Unity Scene File": self.direct_unity_scene,
                    "Unity Scene Objects": self.direct_unity_scene_objects,
                }.get(l, self.direct_unity_selection)(),
                label,
            )
            return
        self.set_card("unity", "busy", f"Executing :{port}")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```csharp\n{code}\n```\n")
        self.append(f"[Unity Direct] Executing on port {port}...\n")
        ok, result = self.command_router.unity.execute(code, timeout=timeout)
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("unity", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("unity", "bad", "Execution failed")
            self.append(f"[Unity Direct Error] {result}\n")

    def direct_unity_selection(self):
        label, ok, result = self.command_router.execute_unity_preset("selection")
        self._emit_unity_preset(label, ok, result)

    def direct_unity_scene(self):
        label, ok, result = self.command_router.execute_unity_preset("file")
        self._emit_unity_preset(label, ok, result)

    def direct_unity_scene_objects(self):
        label, ok, result = self.command_router.execute_unity_preset("objects")
        self._emit_unity_preset(label, ok, result)

    def _emit_unity_preset(self, label, ok, result):
        port = self.command_router.unity.find_port()
        if not port:
            self.set_card("unity", "bad", "Bridge not found")
            self.append(
                "[Unity Direct] No Unity bridge found. Ensure your Unity Editor plugin is active on port 7041.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "unity",
                "Unity bridge was not found.",
                lambda t=text: (self.input.setText(t), self.direct_unity_call_from_text()),
                "Unity Execute",
            )
            return
        code = {
            "Unity Selection": self.command_router.unity.get_selection_code(),
            "Unity Scene File": self.command_router.unity.get_current_file_code(),
            "Unity Scene Objects": self.command_router.unity.get_scene_objects_code(),
        }.get(label, "")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```csharp\n{code}\n```\n")
        self.set_card("unity", "busy", f"Executing :{port}")
        self.append(f"[Unity Direct] Executing on port {port}...\n")
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("unity", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("unity", "bad", "Execution failed")
            self.append(f"[Unity Direct Error] {result}\n")

    def direct_unity_call_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append("\n[Unity Direct] Enter raw Unity C# code first.\n")
            return
        self.input.clear()
        port = self.command_router.unity.find_port()
        if not port:
            self.set_card("unity", "bad", "Bridge not found")
            self.append(
                "[Unity Direct] No Unity bridge found. Ensure your Unity Editor plugin is active on port 7041.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "unity",
                "Unity bridge was not found.",
                lambda t=text: (self.input.setText(t), self.direct_unity_call_from_text()),
                "Unity Execute",
            )
            return
        self.set_card("unity", "busy", f"Executing :{port}")
        self.append(f"[Unity Direct] Executing on port {port}...\n")
        label, ok, result = self.command_router.execute_unity_from_text(text)
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("unity", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("unity", "bad", "Execution failed")
            self.append(f"[Unity Direct Error] {result}\n")

    def direct_houdini_execute(self, code, label="Houdini Direct", timeout=10):
        port = self.command_router.houdini.find_port()
        if not port:
            self.set_card("houdini", "bad", "No bridge")
            self.last_user_prompt = f"[{label}] {code}"
            self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
            self.append("[Houdini Direct] No Houdini bridge found. Start Houdini with the Tech Connector bridge enabled.\n")
            self._prompt_launch_missing_dcc_bridge("houdini", "Houdini bridge was not found.", lambda: self.direct_houdini_execute(code, label, timeout), label)
            return
        self.set_card("houdini", "busy", f"Executing :{port}")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        self.append(f"[Houdini Direct] Executing on port {port}...\n")
        ok, result = self.command_router.houdini.execute(code, timeout=timeout)
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("houdini", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("houdini", "bad", "Execution failed")
            self.append(f"[Houdini Direct Error] {result}\n")

    def direct_houdini_selection(self):
        self.direct_houdini_execute(
            "import hou, json\nprint(json.dumps([{'name': n.name(), 'type': n.type().name(), 'path': n.path()} for n in hou.selectedNodes()]))",
            "Houdini Selection",
        )

    def direct_houdini_file(self):
        self.direct_houdini_execute(
            "import hou, json\nprint(json.dumps({'file': hou.hipFile.path(), 'name': hou.hipFile.name(), 'unsaved': hou.hipFile.hasUnsavedChanges()}))",
            "Houdini File",
        )

    def direct_houdini_scene_objects(self):
        self.direct_houdini_execute(
            "import hou, json\nobj = hou.node('/obj')\nprint(json.dumps([{'name': n.name(), 'type': n.type().name(), 'path': n.path()} for n in (obj.children() if obj else [])[:200]]))",
            "Houdini Scene Nodes",
        )

    def direct_houdini_context_summary(self):
        try:
            from bridges.houdini.houdini_adapter import HoudiniAdapter

            summary = HoudiniAdapter().build_context_summary()
        except Exception as exc:
            summary = str(exc)
        self.last_tool_output = summary
        self.last_assistant_output = summary
        self.append("\n[Houdini Context]\n" + summary + "\n")

    def direct_houdini_call_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append("\n[Houdini Direct] Enter raw Houdini Python first.\n")
            return
        self.input.clear()
        self.direct_houdini_execute(text, "Houdini Execute")

    def direct_motionbuilder_execute(
            self, code, label="MotionBuilder Direct", timeout=10
    ):
        port = self.command_router.motionbuilder.find_port()
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        if not port:
            self.set_card("motionbuilder", "bad", "Bridge not found")
            self.append(
                "[MotionBuilder Direct] No bridge found. Run the MotionBuilder startup bridge setup, then restart MotionBuilder.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "motionbuilder",
                "MotionBuilder bridge was not found.",
                self.direct_motionbuilder_context_summary,
                "MotionBuilder Context",
            )
            return
        self.set_card("motionbuilder", "busy", f"Executing :{port}")
        self.append(f"[MotionBuilder Direct] Executing on port {port}...\n")
        ok, result = self.command_router.motionbuilder.execute(code, timeout=timeout)
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("motionbuilder", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("motionbuilder", "bad", "Execution failed")
            self.append(f"[MotionBuilder Direct Error] {result}\n")

    def direct_motionbuilder_selection(self):
        label, ok, result = self.command_router.execute_motionbuilder_preset(
            "selection"
        )
        self._emit_motionbuilder_preset(label, ok, result)

    def direct_motionbuilder_file(self):
        label, ok, result = self.command_router.execute_motionbuilder_preset("file")
        self._emit_motionbuilder_preset(label, ok, result)

    def direct_motionbuilder_scene_objects(self):
        label, ok, result = self.command_router.execute_motionbuilder_preset("objects")
        self._emit_motionbuilder_preset(label, ok, result)

    def direct_motionbuilder_takes(self):
        label, ok, result = self.command_router.execute_motionbuilder_preset("takes")
        self._emit_motionbuilder_preset(label, ok, result)

    def direct_motionbuilder_characters(self):
        label, ok, result = self.command_router.execute_motionbuilder_preset(
            "characters"
        )
        self._emit_motionbuilder_preset(label, ok, result)

    def direct_motionbuilder_context_summary(self):
        label, ok, result = self.command_router.motionbuilder_context_summary()
        port = self.command_router.motionbuilder.find_port()
        if not port:
            self.set_card("motionbuilder", "bad", "Bridge not found")
            self.append(
                "[MotionBuilder Direct] No bridge found. Run the MotionBuilder startup bridge setup, then restart MotionBuilder.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "motionbuilder",
                "MotionBuilder bridge was not found.",
                self.direct_motionbuilder_context_summary,
                "MotionBuilder Context",
            )
            return
        self.last_user_prompt = f"[{label}]"
        self.set_card("motionbuilder", "busy", f"Scanning :{port}")
        self.append(
            f"[MotionBuilder Direct] Building context summary from port {port}...\n"
        )
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("motionbuilder", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("motionbuilder", "bad", "Scan failed")
            self.append(f"[MotionBuilder Direct Error] {result}\n")

    def _emit_motionbuilder_preset(self, label, ok, result):
        port = self.command_router.motionbuilder.find_port()
        if not port:
            self.set_card("motionbuilder", "bad", "Bridge not found")
            self.append(
                "[MotionBuilder Direct] No bridge found. Run the MotionBuilder startup bridge setup, then restart MotionBuilder.\n"
            )
            return
        code = {
            "MotionBuilder Selection": self.command_router.motionbuilder.get_selection_code(),
            "MotionBuilder File": self.command_router.motionbuilder.get_current_file_code(),
            "MotionBuilder Scene Objects": self.command_router.motionbuilder.get_scene_objects_code(),
            "MotionBuilder Takes": self.command_router.motionbuilder.get_takes_code(),
            "MotionBuilder Characters": self.command_router.motionbuilder.get_characters_code(),
        }.get(label, "")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        self.set_card("motionbuilder", "busy", f"Executing :{port}")
        self.append(f"[MotionBuilder Direct] Executing on port {port}...\n")
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("motionbuilder", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("motionbuilder", "bad", "Execution failed")
            self.append(f"[MotionBuilder Direct Error] {result}\n")

    def direct_motionbuilder_call_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append(
                "\n[MotionBuilder Direct] Enter raw MotionBuilder Python or a JSON function payload first.\n"
            )
            return
        self.input.clear()
        port = self.command_router.motionbuilder.find_port()
        if not port:
            self.set_card("motionbuilder", "bad", "Bridge not found")
            self.append(
                "[MotionBuilder Direct] No bridge found. Run the MotionBuilder startup bridge setup, then restart MotionBuilder.\n"
            )
            return
        label, ok, result = self.command_router.execute_motionbuilder_from_text(text)
        self.last_user_prompt = f"[{label}] {text}"
        self.append(f"\nYOU [{label}]:\n```python\n{text}\n```\n")
        self.set_card("motionbuilder", "busy", f"Executing :{port}")
        self.append(f"[MotionBuilder Direct] Executing on port {port}...\n")
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("motionbuilder", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("motionbuilder", "bad", "Execution failed")
            self.append(f"[MotionBuilder Direct Error] {result}\n")

    def direct_substance_painter_execute(
            self, code, label="Substance Painter Direct", timeout=10
    ):
        port = self.command_router.substance_painter.find_port()
        if not port:
            self.set_card("substance_painter", "bad", "Bridge not found")
            self.last_user_prompt = f"[{label}] {code}"
            self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
            self.append(
                "[Substance Painter Direct] No bridge found. Run Install_Substance_Painter_AI_Studio_Bridge.bat once, then restart Painter.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "substance_painter",
                "Substance Painter bridge was not found.",
                lambda l=label: {
                    "Substance Painter Project": self.direct_substance_painter_project,
                    "Substance Painter Status": self.direct_substance_painter_status,
                    "Substance Painter Texture Sets": self.direct_substance_painter_texture_sets,
                }.get(l, self.direct_substance_painter_project)(),
                label,
            )
            return
        self.set_card("substance_painter", "busy", f"Executing :{port}")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        self.append(f"[Substance Painter Direct] Executing on port {port}...\n")
        ok, result = self.command_router.substance_painter.execute(
            code, timeout=timeout
        )
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("substance_painter", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("substance_painter", "bad", "Execution failed")
            self.append(f"[Substance Painter Direct Error] {result}\n")

    def direct_substance_painter_project(self):
        label, ok, result = self.command_router.execute_substance_painter_preset(
            "project"
        )
        self._emit_substance_painter_preset(label, ok, result)

    def direct_substance_painter_status(self):
        label, ok, result = self.command_router.execute_substance_painter_preset(
            "status"
        )
        self._emit_substance_painter_preset(label, ok, result)

    def direct_substance_painter_texture_sets(self):
        label, ok, result = self.command_router.execute_substance_painter_preset(
            "texture_sets"
        )
        self._emit_substance_painter_preset(label, ok, result)

    def _emit_substance_painter_preset(self, label, ok, result):
        port = self.command_router.substance_painter.find_port()
        if not port:
            self.set_card("substance_painter", "bad", "Bridge not found")
            self.append(
                "[Substance Painter Direct] No bridge found. Run Install_Substance_Painter_AI_Studio_Bridge.bat once, then restart Painter.\n"
            )
            self._prompt_launch_missing_dcc_bridge(
                "substance_painter",
                "Substance Painter bridge was not found.",
                lambda l=label: {
                    "Substance Painter Project": self.direct_substance_painter_project,
                    "Substance Painter Status": self.direct_substance_painter_status,
                    "Substance Painter Texture Sets": self.direct_substance_painter_texture_sets,
                }.get(l, self.direct_substance_painter_project)(),
                label,
            )
            return
        code = {
            "Substance Painter Project": self.command_router.substance_painter.get_current_file_code(),
            "Substance Painter Status": self.command_router.substance_painter.get_project_status_code(),
            "Substance Painter Texture Sets": self.command_router.substance_painter.get_scene_objects_code(),
        }.get(label, "")
        self.last_user_prompt = f"[{label}] {code}"
        self.append(f"\nYOU [{label}]:\n```python\n{code}\n```\n")
        self.set_card("substance_painter", "busy", f"Executing :{port}")
        self.append(f"[Substance Painter Direct] Executing on port {port}...\n")
        if ok:
            self.last_tool_output = result
            self.last_assistant_output = result
            self.set_card("substance_painter", "ok", "Connected")
            self.append("Tool Result:\n" + result + "\n")
        else:
            self.set_card("substance_painter", "bad", "Execution failed")
            self.append(f"[Substance Painter Direct Error] {result}\n")

    def direct_substance_painter_call_from_text(self):
        text = self.input.text().strip()
        if not text:
            self.append(
                "\n[Substance Painter Direct] Enter raw Painter Python or a JSON function payload first.\n"
            )
            return
        self.input.clear()
        try:
            port = self.command_router.substance_painter.find_port()
            if not port:
                self.set_card("substance_painter", "bad", "Bridge not found")
                self.append(
                    "[Substance Painter Direct] No bridge found. Run Install_Substance_Painter_AI_Studio_Bridge.bat once, then restart Painter.\n"
                )
                return
            label, ok, result = self.command_router.execute_substance_painter_from_text(
                text
            )
            self.last_user_prompt = f"[{label}] {text}"
            self.append(f"\nYOU [{label}]:\n```python\n{text}\n```\n")
            self.set_card("substance_painter", "busy", f"Executing :{port}")
            self.append(f"[Substance Painter Direct] Executing on port {port}...\n")
            if ok:
                self.last_tool_output = result
                self.last_assistant_output = result
                self.set_card("substance_painter", "ok", "Connected")
                self.append("Tool Result:\n" + result + "\n")
            else:
                self.set_card("substance_painter", "bad", "Execution failed")
                self.append(f"[Substance Painter Direct Error] {result}\n")
        except Exception as e:
            self.append(f"\n[Substance Painter Direct Parse Error] {e}\n")

    def toggle_unreal_daemon(self):
        # Resolve active project path
        roots = self.project_roots() if hasattr(self, "project_roots") else []
        if not roots:
            QMessageBox.warning(
                self, "No Project", "Please open a project directory first."
            )
            return

        project_root = roots[0]

        if not hasattr(self, "intel_service") or not self.intel_service:
            from services.project_service import ProjectIntelligenceService

            self.intel_service = ProjectIntelligenceService()

        if self.intel_service.is_daemon_running():
            # Stop it
            self.intel_service.stop_daemon()
            self.daemon_toggle_btn.setText("Start Unreal Indexer")
            self.daemon_scan_btn.setEnabled(False)
            self.unreal_docs_btn.setEnabled(False)
            self.append("\n[Unreal Indexer] Stopped background intelligence daemon.\n")
        else:
            # Start it
            self.daemon_toggle_btn.setText("Starting...")
            self.daemon_toggle_btn.setEnabled(False)

            ok, msg = self.intel_service.start_daemon(project_root)
            self.daemon_toggle_btn.setEnabled(True)
            if ok:
                self.daemon_toggle_btn.setText("Stop Unreal Indexer")
                self.daemon_scan_btn.setEnabled(True)
                self.unreal_docs_btn.setEnabled(True)
                self.append(f"\n[Unreal Indexer] Background daemon started: {msg}.\n")
                self.ensure_unreal_docs_cache()
            else:
                self.daemon_toggle_btn.setText("Start Unreal Indexer")
                QMessageBox.critical(self, "Start Daemon Failed", msg)
        self.update_dcc_statuses()

    def trigger_daemon_scan(self):
        if not hasattr(self, "intel_service") or not self.intel_service:
            return
        mode = "quick"
        if hasattr(self, "scan_mode_combo"):
            mode = self.scan_mode_combo.currentText().lower()

        self.daemon_scan_btn.setText("Scanning...")
        self.daemon_scan_btn.setEnabled(False)

        def do_scan():
            ok, result = self.intel_service.trigger_scan(mode=mode)

            def on_done(ok=ok, result=result):
                self.daemon_scan_btn.setText("Index Project")
                self.daemon_scan_btn.setEnabled(True)
                self.update_dcc_statuses()
                if ok:
                    if isinstance(result, dict):
                        self.append(
                            f"\n[Unreal Indexer] Project scan finished. "
                            f"duration_ms={result.get('duration_ms')} total_assets={result.get('total_assets')} "
                            f"added={result.get('added')} updated={result.get('updated')}.\n"
                        )
                    else:
                        self.append(
                            f"\n[Unreal Indexer] Index complete. total_indexed={result}.\n"
                        )
                    # Automatically trigger reflection refresh to sync live API
                    self.refresh_unreal_reflection()
                else:
                    err = (
                        result.get("error")
                        if isinstance(result, dict)
                        else "No response"
                    )
                    self.append(f"\n[Unreal Indexer] Scan failed: {err}\n")

            QTimer.singleShot(0, on_done)

        import threading

        threading.Thread(target=do_scan, daemon=True).start()

    def refresh_unreal_reflection(self):
        if not hasattr(self, "intel_service") or not self.intel_service:
            return
        self.append("\n[Unreal Indexer] Refreshing live reflection API index...\n")

        def do_refresh():
            result = self.intel_service.refresh_unreal_reflection(timeout=60.0)
            QTimer.singleShot(
                0, lambda: self.on_unreal_auto_reflection_finished(result)
            )

        import threading

        threading.Thread(target=do_refresh, daemon=True).start()

    def ensure_unreal_docs_cache(self):
        if not hasattr(self, "intel_service") or not self.intel_service:
            return

        def do_ensure():
            result = self.intel_service.refresh_docs(
                version="5.8", max_pages=0, force=False
            )

            def on_done(result=result):
                self.update_dcc_statuses()
                if result and result.get("success"):
                    docs = result.get("docs") or {}
                    self.append(
                        "\n[Unreal Docs] Python API cache initialized automatically. "
                        f"api_count={docs.get('api_count')} duration_ms={docs.get('duration_ms')}.\n"
                    )
                else:
                    self.append(
                        "\n[Unreal Docs] Automatic docs cache setup skipped or failed; manual Index Docs remains available.\n"
                    )

        import threading

        threading.Thread(target=do_ensure, daemon=True).start()

    def refresh_unreal_docs_cache(self):
        if not hasattr(self, "intel_service") or not self.intel_service:
            return
        self.unreal_docs_btn.setText("Indexing...")
        self.unreal_docs_btn.setEnabled(False)

        def do_refresh():
            result = self.intel_service.refresh_docs(
                version="5.8", max_pages=0, force=False
            )

            def on_done(result=result):
                self.unreal_docs_btn.setText("Index Docs")
                self.unreal_docs_btn.setEnabled(True)
                self.update_dcc_statuses()
                if result and result.get("success"):
                    docs = result.get("docs") or {}
                    self.append(
                        "\n[Unreal Docs] Python API index ready. "
                        f"api_count={docs.get('api_count')} parsed={docs.get('parsed_count')} "
                        f"duration_ms={docs.get('duration_ms')}.\n"
                    )
                else:
                    self.append(
                        "\n[Unreal Docs] API docs indexing failed. Check network access or try again later.\n"
                    )

            QTimer.singleShot(0, on_done)

        import threading

        threading.Thread(target=do_refresh, daemon=True).start()


    def launch_maya(self):
        self.launch_dcc("maya")

    def launch_motionbuilder(self):
        self.launch_dcc("motionbuilder")

    def launch_blender(self):
        self.launch_dcc("blender")

    def launch_substance_painter(self):
        self.launch_dcc("substance_painter")

    def launch_unity(self):
        self.launch_dcc("unity")

    def launch_unreal(self):
        self.launch_dcc("unreal")

    def launch_houdini(self):
        self.launch_dcc("houdini")

    def launch_dcc(self, host: str):
        executable = find_dcc_executable(host)
        if not executable:
            from PySide6.QtWidgets import QFileDialog, QMessageBox
            import os

            QMessageBox.information(
                self,
                f"Locate {host.capitalize()}",
                f"We couldn't automatically find the installation path for {host.capitalize()}.\n\n"
                "Please select the executable file in the next dialog."
            )
            file_filter = "Executables (*.exe)" if os.name == "nt" else "All Files (*)"
            selected, _ = QFileDialog.getOpenFileName(
                self, f"Select {host.capitalize()} Executable", "C:\\", file_filter
            )
            if selected:
                executable = selected
            else:
                return

        try:
            import subprocess
            from pathlib import Path
            import os

            self.append(f"\n[DCC Launcher] Launching {host.capitalize()} from: {executable}\n")

            tools_dir = Path(__file__).resolve().parent.parent
            if host == "maya":
                setup_path = tools_dir / "maya_setup.py"
                if setup_path.exists():
                    cmd = [executable, "-command", f'python("exec(open(r\'{setup_path}\').read())")']
                else:
                    cmd = [executable]
            elif host == "motionbuilder":
                setup_path = tools_dir / "motionbuilder_setup.py"
                if setup_path.exists():
                    cmd = [executable, "-command", f'python("exec(open(r\'{setup_path}\').read())")']
                else:
                    cmd = [executable]
            else:
                cmd = [executable]

            subprocess.Popen(
                cmd,
                close_fds=True,
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            )
            self.append(f"[DCC Launcher] {host.capitalize()} launched successfully.\n")
            if hasattr(self, "set_card"):
                self.set_card(host, "busy", "Launching...")
            if hasattr(self, "update_dcc_statuses"):
                from PySide6.QtCore import QTimer
                QTimer.singleShot(2000, self.update_dcc_statuses)
                QTimer.singleShot(5000, self.update_dcc_statuses)
                QTimer.singleShot(10000, self.update_dcc_statuses)
                QTimer.singleShot(15000, self.update_dcc_statuses)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Launch Failed", f"Failed to launch {host.capitalize()}:\n{e}")


def find_dcc_executable(host: str) -> str | None:
    import glob
    import os
    # Search paths for Windows
    paths_dict = {
        "maya": [
            r"C:\Program Files\Autodesk\Maya*\bin\maya.exe",
        ],
        "unreal": [
            r"C:\Program Files\Epic Games\UE_*\Engine\Binaries\Win64\UnrealEditor.exe",
            r"C:\Program Files\Epic Games\UE_*\Engine\Binaries\Win64\UE4Editor.exe",
        ],
        "blender": [
            r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
        ],
        "substance_painter": [
            r"C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe",
            r"C:\Program Files\Allegorithmic\Substance Painter\Substance Painter.exe",
        ],
        "motionbuilder": [
            r"C:\Program Files\Autodesk\MotionBuilder*\bin\motionbuilder.exe",
        ],
        "unity": [
            r"C:\Program Files\Unity\Hub\Editor\*\Editor\Unity.exe",
        ],
    }

    candidates = paths_dict.get(host, [])
    for pattern in candidates:
        matches = glob.glob(pattern)
        if matches:
            matches.sort(reverse=True)
            return matches[0]
    return None

