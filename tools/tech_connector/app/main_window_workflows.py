"""Extracted MainWindow methods. Generated from the uploaded monolithic file."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = next(candidate for candidate in Path(__file__).resolve().parents if candidate.name.lower() == "tools")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import re
import time

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal, QEvent, QPoint
from PySide6.QtGui import QTextCursor, QKeySequence, QShortcut

from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
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
    QHeaderView
)

from tech_connector.ui.chat_worker_dialogs import WorkflowOutputSelectorDialog
from tech_connector.ui.pipeline_node_view import pipeline_tool_query_rank


class MainWindowWorkflowsMixin:
    # ------------------------------------------------------------------
    # Pipeline composer enabled/locked state
    # ------------------------------------------------------------------
    def set_pipeline_composer_enabled(self, enabled: bool, reason: str = ""):
        """Enable/disable the node graph and Python composer area.

        The left rail and composer stay active so the user can create a new
        pipeline, select an existing one, or edit Python without first escaping
        a locked state.
        """
        enabled = bool(enabled)
        self.wf_pipeline_composer_locked = not enabled

        # The composer should never become a dead surface. Keep graph tabs,
        # filters, Add Node, and the Python editor interactive so the user can
        # start or inspect a pipeline from whichever surface currently has focus.
        try:
            if hasattr(self, "wf_builder_tabs"):
                for idx in range(self.wf_builder_tabs.count()):
                    self.wf_builder_tabs.setTabEnabled(idx, True)
        except Exception:
            pass

        # Saved-pipeline-only actions should still require an actual selected item.
        has_saved_selection = False
        try:
            has_saved_selection = bool(self.workflows_list.selectedItems())
        except Exception:
            pass
        for attr in (
            "wf_graph_run_btn",
            "wf_graph_export_btn",
            "wf_graph_append_btn",
            "wf_graph_delete_btn",
            "wf_graph_test_btn",
            "wf_graph_log_btn",
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                try:
                    widget.setEnabled(enabled and has_saved_selection)
                except Exception:
                    pass

        try:
            if hasattr(self, "wf_test_status"):
                self.wf_test_status.setText("" if enabled else (reason or "Create or select a pipeline to edit."))
                self.wf_test_status.setStyleSheet("color: #8fb9c9;" if not enabled else "font-weight: bold;")
        except Exception:
            pass

    def _ensure_pipeline_composer_unlocked(self, reason: str = "") -> bool:
        if not getattr(self, "wf_pipeline_composer_locked", False):
            return True
        self.set_pipeline_composer_enabled(False, reason or "Create or select a pipeline before editing the node graph / Python.")
        return False

    def refresh_workflows_list(self):
        self.workflows_list.clear()
        self.loaded_workflows = {}

        roots = self.project_roots() if hasattr(self, "project_roots") else []
        if not roots:
            return

        project_root = Path(roots[0])
        workflows_dir = project_root / "workflows"
        if not workflows_dir.exists() or not workflows_dir.is_dir():
            return

        for path in workflows_dir.rglob("*.workflow.json"):
            if not path.is_file():
                continue
            try:
                import json

                data = json.loads(path.read_text(encoding="utf-8"))
                host = data.get("host", "unknown")
                func = data.get("function", "unnamed")
                display_name = f"[{host}] {func}"

                item = QListWidgetItem(display_name)
                item.setData(Qt.UserRole, str(path))
                self.workflows_list.addItem(item)

                self.loaded_workflows[str(path)] = data
            except Exception:
                pass

    def _report_workflow_error(self, label: str, exc: BaseException):
        from tech_connector.services.chat_report_service import format_error_report
        graph_report = {}
        try:
            view = getattr(self, "wf_node_view", None)
            if view is not None and hasattr(view, "graph_intelligence_report"):
                graph_report = view.graph_intelligence_report()
        except Exception:
            graph_report = {}

        msg = "\n" + format_error_report(
            title="Workflow Builder Error",
            summary=label,
            operation="Pipeline / node graph workflow builder",
            exception=exc,
            context={
                "active_file": getattr(self, "current_file_path", ""),
                "selected_node": getattr(getattr(self, "wf_node_view", None), "selected_node_id", lambda: "")(),
                "graph_status": graph_report.get("status", ""),
                "graph_summary": graph_report.get("summary", ""),
            },
            recovery=[
                "Check the highlighted node or the Python tab for missing inputs, syntax errors, or broken data-flow connections.",
                *list((graph_report.get("next_actions") or [])[:3]),
                "Use Undo Graph Change if the failure happened immediately after a graph edit.",
                "Retry after saving/compiling only when the validation state is green or the report explains why it is safe.",
            ],
            validation=[
                "The workflow builder did not complete the requested operation.",
                *list((graph_report.get("validation_gates") or [])[:3]),
                "Inspect the node graph border/status colors before running or exporting the pipeline.",
            ],
        ) + "\n"

        if hasattr(self, "append"):
            self.append(msg)
        else:
            print(msg, flush=True)

    def filter_workflows(self, text):
        text = text.lower()
        for i in range(self.workflows_list.count()):
            item = self.workflows_list.item(i)
            item.setHidden(text not in item.text().lower())

    def on_workflow_selection_changed(self):
        selected = self.workflows_list.selectedItems()
        has_sel = bool(selected)
        try:
            self.set_pipeline_composer_enabled(has_sel, "Create or select a pipeline to edit the node graph / Python.")
        except Exception:
            pass
        for btn in (
                self.wf_save_btn,
                self.wf_run_btn,
                self.wf_test_btn,
                self.wf_test_log_btn,
                self.wf_delete_btn,
                self.wf_edit_btn,
                self.wf_export_btn,
                self.wf_append_btn,
        ):
            btn.setEnabled(has_sel)

        if not selected:
            self.wf_header.setText("Select a pipeline to view details.")
            self.wf_path_lbl.setText("")
            self.wf_goal_display.clear()
            self.wf_slots_table.setRowCount(0)
            self.wf_code_preview.clear()
            self.wf_test_status.setText("")
            return

        manifest_path_str = selected[0].data(Qt.UserRole)
        data = self.loaded_workflows.get(manifest_path_str)
        if not data:
            return

        host = data.get("host", "unknown")
        func = data.get("function", "unnamed")
        goal = data.get("goal", "")

        self.wf_header.setText(f"[{host.upper()}] {func}")
        self.wf_path_lbl.setText(f"Manifest: {manifest_path_str}")
        self.wf_goal_display.setPlainText(goal)

        # Populate slots table
        slots = data.get("slots", {})
        self.wf_slots_table.setRowCount(0)
        self.wf_slots_table.setRowCount(len(slots))
        for idx, (key, value) in enumerate(slots.items()):
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)  # readonly key
            val_item = QTableWidgetItem(str(value) if value is not None else "")
            self.wf_slots_table.setItem(idx, 0, key_item)
            self.wf_slots_table.setItem(idx, 1, val_item)

        # Display source code
        manifest_path = Path(manifest_path_str)
        code_path = manifest_path.with_suffix(".py")
        if code_path.exists():
            try:
                self.wf_code_preview.setPlainText(code_path.read_text(encoding="utf-8"))
            except Exception as e:
                self.wf_code_preview.setPlainText(f"Error reading source: {e}")
        else:
            self.wf_code_preview.setPlainText("Source file not found.")

        self.wf_save_btn.setEnabled(True)
        self.wf_run_btn.setEnabled(True)
        self.wf_test_btn.setEnabled(True)
        self.wf_delete_btn.setEnabled(True)
        self.wf_edit_btn.setEnabled(True)
        self.wf_test_log_btn.setEnabled(False)
        self.wf_test_status.setText("")

    def save_workflow_parameter_changes(self):
        selected = self.workflows_list.selectedItems()
        if not selected:
            return
        manifest_path_str = selected[0].data(Qt.UserRole)
        data = self.loaded_workflows.get(manifest_path_str)
        if not data:
            return

        # Read table rows
        slots = {}
        for r in range(self.wf_slots_table.rowCount()):
            key_item = self.wf_slots_table.item(r, 0)
            val_item = self.wf_slots_table.item(r, 1)
            if key_item and val_item:
                p_val = val_item.text().strip()
                # Parse python literal if possible
                try:
                    import ast

                    parsed_val = ast.literal_eval(p_val) if p_val else None
                except Exception:
                    parsed_val = p_val if p_val else None
                slots[key_item.text()] = parsed_val

        data["slots"] = slots
        try:
            import json

            Path(manifest_path_str).write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
            self.wf_test_status.setText("Parameters saved successfully.")
            self.wf_test_status.setStyleSheet("color: #5bd000;")

            # Reload display code preview just in case (parameters in file itself won't change,
            # but this keeps manifest json and state consistent)
            self.on_workflow_selection_changed()
        except Exception as e:
            QMessageBox.critical(
                self, "Error Saving", f"Failed to save parameters:\n{e}"
            )

    def _workflow_python_launcher(self) -> list[str]:
        """Return a portable Python launcher command for user-visible terminal runs."""
        import os
        import sys

        if os.name == "nt":
            return ["py", "-3.11"]
        return [sys.executable or "python3"]

    def _quote_workflow_command(self, parts: list[str]) -> str:
        """Format a command so it is copyable in the embedded terminal."""
        import os
        import shlex
        import subprocess

        cleaned = [str(part) for part in parts if str(part) != ""]
        if os.name == "nt":
            return subprocess.list2cmdline(cleaned)
        return " ".join(shlex.quote(part) for part in cleaned)

    def _show_embedded_terminal_for_workflow(self) -> None:
        """Best-effort focus/open of whatever terminal panel exists in this build."""
        terminal_names = {"terminal", "console", "output"}
        for tab_attr in ("bottom_tabs", "workspace_tabs", "tabs", "main_tabs"):
            tabs = getattr(self, tab_attr, None)
            if not tabs or not hasattr(tabs, "count") or not hasattr(tabs, "setCurrentIndex"):
                continue
            try:
                for idx in range(tabs.count()):
                    label = str(tabs.tabText(idx)).lower() if hasattr(tabs, "tabText") else ""
                    if any(name in label for name in terminal_names):
                        tabs.setCurrentIndex(idx)
                        tab_widget = tabs.widget(idx) if hasattr(tabs, "widget") else None
                        if tab_widget and hasattr(tab_widget, "setVisible"):
                            tab_widget.setVisible(True)
                        return
            except Exception:
                pass

        for attr in ("terminal_dock", "terminal_panel", "terminal_widget", "terminal_output"):
            widget = getattr(self, attr, None)
            if not widget:
                continue
            try:
                widget.setVisible(True)
                widget.raise_()
                widget.setFocus()
                return
            except Exception:
                pass

    def _send_workflow_command_to_terminal(self, command: str, cwd: str, label: str = "Workflow") -> bool:
        """Open the terminal and send the exact command the user can re-run manually."""
        command = (command or "").strip()
        if not command:
            return False

        self._show_embedded_terminal_for_workflow()

        # Prefer an already-created embedded terminal/session if the app has one.
        for attr in ("terminal_session", "embedded_terminal_session", "workflow_terminal_session"):
            session = getattr(self, attr, None)
            if session and hasattr(session, "send"):
                try:
                    if hasattr(session, "cd"):
                        session.cd(cwd)
                    session.send(command)
                    return True
                except Exception:
                    pass

        # Fall back to creating a persistent TerminalSession. Its output is routed to chat/log
        # if no dedicated terminal widget has been attached yet.
        try:
            from tech_connector.services.terminal_service import TerminalSession, TerminalSessionConfig

            session = TerminalSession(TerminalSessionConfig(cwd=cwd), parent=self)
            session.output.connect(lambda text: self.append(text) if hasattr(self, "append") else print(text, end="", flush=True))
            session.start()
            session.send(command)
            self.workflow_terminal_session = session
            return True
        except Exception as exc:
            try:
                self.append(f"\n[{label} command] {command}\n[terminal unavailable] {exc}\n")
            except Exception:
                pass
            return False

    def _write_workflow_runner_script(self, project_root: str, dotted_module: str, func_name: str, slots: dict) -> Path:
        """Create a readable runner file instead of stuffing multiline Python into -c."""
        import json

        root = Path(project_root or ".").expanduser().resolve()
        runtime_dir = root / ".ai_studio_runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        runner_path = runtime_dir / "run_workflow.py"
        slots_json = json.dumps(slots or {}, indent=2, sort_keys=True)
        runner_path.write_text(
            "import importlib\n"
            "import json\n"
            "import sys\n"
            "import traceback\n"
            "from pathlib import Path\n\n"
            f"project_root = Path({str(root)!r})\n"
            "project_root_text = str(project_root)\n"
            "if project_root_text not in sys.path:\n"
            "    sys.path.insert(0, project_root_text)\n\n"
            f"module_name = {dotted_module!r}\n"
            f"function_name = {func_name!r}\n"
            f"kwargs = json.loads({slots_json!r})\n\n"
            "try:\n"
            "    module = importlib.import_module(module_name)\n"
            "    module = importlib.reload(module)\n"
            "    func = getattr(module, function_name)\n"
            "    result = func(**kwargs)\n"
            "    print('PIPELINE_EXECUTION_SUCCESS')\n"
            "    print('Result:', result)\n"
            "except Exception as exc:\n"
            "    traceback.print_exc()\n"
            "    print('PIPELINE_EXECUTION_FAILED:', exc)\n"
            "    raise\n",
            encoding="utf-8",
        )
        return runner_path

    # ------------------------------------------------------------------
    # Pipeline run path: DCC bridge first, terminal only as fallback
    # ------------------------------------------------------------------
    def _pipeline_project_root(self, manifest_path_str: str = "") -> Path:
        roots = self.project_roots() if hasattr(self, "project_roots") else []
        if roots:
            return Path(roots[0]).expanduser().resolve()
        if manifest_path_str:
            try:
                return Path(manifest_path_str).expanduser().resolve().parent.parent.parent
            except Exception:
                pass
        return Path(".").resolve()

    def _pipeline_safe_slug(self, name: str, fallback: str = "pipeline") -> str:
        import re
        slug = re.sub(r"[^A-Za-z0-9_]+", "_", str(name or fallback)).strip("_").lower()
        slug = re.sub(r"_+", "_", slug) or fallback
        if slug[0].isdigit():
            slug = f"pipeline_{slug}"
        return slug

    def _pipeline_function_name_from_code(self, code: str, fallback: str = "unnamed_workflow") -> str:
        import ast
        try:
            from tech_connector.services.workflow_service import extract_python_code

            code = extract_python_code(code)
        except Exception:
            pass
        try:
            tree = ast.parse(code or "")
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return node.name
        except Exception:
            pass
        return fallback

    def _current_pipeline_code_and_meta(self):
        self.update_builder_code_preview()
        code = ""
        if hasattr(self, "wf_builder_code_edit"):
            try:
                code = self.wf_builder_code_edit.toPlainText()
            except Exception:
                pass
        code = code or getattr(self, "_last_workflow_generated_code", "") or ""
        try:
            from tech_connector.services.workflow_service import extract_python_code

            code = extract_python_code(code)
        except Exception:
            pass
        name_text = "unnamed_workflow"
        try:
            name_text = self.wf_build_name.text().strip() or name_text
        except Exception:
            pass
        fn = self._pipeline_function_name_from_code(code, self._pipeline_safe_slug(name_text, "unnamed_workflow"))
        slots = self._pipeline_slots_from_builder()
        host = self._infer_pipeline_host_from_builder()
        root = self._pipeline_project_root("")
        return code, fn, slots, host, root, "current graph"

    def _selected_pipeline_code_and_meta(self):
        selected = self.workflows_list.selectedItems() if hasattr(self, "workflows_list") else []
        if not selected:
            return None
        manifest_path_str = selected[0].data(Qt.UserRole)
        data = self.loaded_workflows.get(manifest_path_str) if hasattr(self, "loaded_workflows") else None
        if not data:
            return None
        manifest_path = Path(manifest_path_str)
        py_path = manifest_path.with_suffix(".py")
        if not py_path.exists():
            maybe = data.get("code_path") or data.get("source_path")
            if maybe:
                py_path = Path(maybe)
        code = py_path.read_text(encoding="utf-8", errors="replace") if py_path.exists() else ""
        fn = data.get("function") or self._pipeline_function_name_from_code(code)
        slots = data.get("slots", {}) or {}
        host = self._infer_pipeline_host(data)
        root = self._pipeline_project_root(manifest_path_str)
        return code, fn, slots, host, root, manifest_path.name

    def _pipeline_slots_from_builder(self) -> dict:
        slots = {}
        for idx, step in enumerate(getattr(self, "wf_builder_steps", []) or [], start=1):
            params_table = step.get("table")
            if not params_table:
                continue
            for r in range(params_table.rowCount()):
                param_name_item = params_table.item(r, 0)
                cell_widget = params_table.cellWidget(r, 1)
                if not param_name_item or not cell_widget:
                    continue
                p_name = param_name_item.text()
                val_edit = cell_widget.findChild(QLineEdit)
                conn_check = cell_widget.findChild(QCheckBox)
                if conn_check and conn_check.isChecked():
                    continue
                p_val = val_edit.text().strip() if val_edit else ""
                wrapper_arg_name = f"step{idx}_{p_name}"
                try:
                    import ast
                    slots[wrapper_arg_name] = ast.literal_eval(p_val) if p_val else None
                except Exception:
                    slots[wrapper_arg_name] = p_val if p_val else None
        return slots

    def _infer_pipeline_host_from_builder(self) -> str:
        candidates = []
        for step in getattr(self, "wf_builder_steps", []) or []:
            sym = step.get("symbol") or {}
            text = " ".join(str(sym.get(k) or "") for k in ("host", "package", "module", "file_path", "source_package", "function_path")).lower()
            if "maya" in text:
                candidates.append("maya")
            elif "unreal" in text:
                candidates.append("unreal")
            elif "blender" in text or "bpy" in text:
                candidates.append("blender")
            elif "substance" in text:
                candidates.append("substance_painter")
            elif "unity" in text:
                candidates.append("unity")
            elif "motionbuilder" in text:
                candidates.append("motionbuilder")
        non_utility = [c for c in candidates if c]
        return non_utility[0] if non_utility else "local"

    def _infer_pipeline_host(self, manifest: dict | None = None) -> str:
        manifest = manifest or {}
        host = str(manifest.get("host") or "").lower().strip()
        if host and host not in {"cross_dcc", "unknown", "local"}:
            return host
        selected = manifest.get("selected_capabilities") or manifest.get("selected_items") or []
        for sym in selected:
            if not isinstance(sym, dict):
                continue
            text = " ".join(str(sym.get(k) or "") for k in ("host", "package", "module", "file_path", "source_package", "function_path")).lower()
            if "maya" in text:
                return "maya"
            if "unreal" in text:
                return "unreal"
            if "blender" in text or "bpy" in text:
                return "blender"
            if "substance" in text:
                return "substance_painter"
            if "unity" in text:
                return "unity"
            if "motionbuilder" in text:
                return "motionbuilder"
        return self._infer_pipeline_host_from_builder()

    def _pipeline_runtime_source(self, code: str, function_name: str, slots: dict, project_root: Path) -> str:
        import base64
        import json
        encoded_code = base64.b64encode((code or "").encode("utf-8")).decode("ascii")
        slots_json = json.dumps(slots or {}, default=str)
        template = r'''
# Tech Connector DCC pipeline runner. This entire block executes inside the host app.
import base64, importlib, importlib.util, io, json, os, sys, traceback
from pathlib import Path
_PROJECT_ROOT = Path(__PROJECT_ROOT__)
for _p in [str(_PROJECT_ROOT), str(_PROJECT_ROOT / "tools"), str(_PROJECT_ROOT / "src")]:
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)
_REAL_IMPORT_MODULE = importlib.import_module

def _ai_import_module(name, package=None):
    if isinstance(name, str) and (":" in name or "\" in name or "/" in name):
        raw = name.replace("\", "/")
        guesses = []
        if ":." in raw:
            guesses.append(raw.replace(":.", ":/"))
        guesses.append(raw)
        for guess in list(guesses):
            if ":" in guess and "/" not in guess.split(":", 1)[1]:
                drive, rest = guess.split(":", 1)
                guesses.append(drive + ":/" + rest.lstrip(".").replace(".", "/"))
        for guess in guesses:
            path = Path(guess)
            py_path = path if path.suffix == ".py" else Path(str(path) + ".py")
            if py_path.exists():
                module_name = py_path.stem
                spec = importlib.util.spec_from_file_location(module_name, str(py_path))
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                return module
    return _REAL_IMPORT_MODULE(name, package=package)
importlib.import_module = _ai_import_module
_CODE = base64.b64decode(__ENCODED_CODE__.encode("ascii")).decode("utf-8")
_FUNCTION_NAME = __FUNCTION_NAME__
_KWARGS = json.loads(__SLOTS_JSON__)
_GLOBALS = {"__name__": "__ai_studio_pipeline__", "__file__": "<ai_studio_pipeline>"}
_STDOUT, _STDERR = sys.stdout, sys.stderr
_OUT, _ERR = io.StringIO(), io.StringIO()
_envelope = {"ok": False, "result": None, "stdout": "", "stderr": "", "error": None, "traceback": None}
try:
    sys.stdout = _OUT
    sys.stderr = _ERR
    exec(compile(_CODE, "<ai_studio_pipeline>", "exec"), _GLOBALS, _GLOBALS)
    _func = _GLOBALS.get(_FUNCTION_NAME)
    if _func is None:
        raise RuntimeError("Pipeline function not found: " + str(_FUNCTION_NAME))
    _result = _func(**_KWARGS)
    _envelope.update({"ok": True, "result": _result})
except Exception as _exc:
    _envelope.update({"ok": False, "error": str(_exc), "traceback": traceback.format_exc()})
finally:
    _envelope["stdout"] = _OUT.getvalue()
    _envelope["stderr"] = _ERR.getvalue()
    sys.stdout = _STDOUT
    sys.stderr = _STDERR
print("__AI_STUDIO_PIPELINE_JSON_START__")
print(json.dumps(_envelope, default=str))
print("__AI_STUDIO_PIPELINE_JSON_END__")
'''
        return (template
            .replace("__PROJECT_ROOT__", repr(str(project_root)))
            .replace("__ENCODED_CODE__", repr(encoded_code))
            .replace("__FUNCTION_NAME__", repr(function_name))
            .replace("__SLOTS_JSON__", repr(slots_json)))

    def _parse_pipeline_bridge_output(self, raw):
        import json
        if isinstance(raw, dict):
            data = raw.get("python_result") or raw.get("result") or raw.get("data") or raw
            if isinstance(data, dict) and "ok" in data:
                return data
            raw = raw.get("python_stdout") or raw.get("raw") or str(raw)
        text = str(raw or "")
        start = "__AI_STUDIO_PIPELINE_JSON_START__"
        end = "__AI_STUDIO_PIPELINE_JSON_END__"
        if start in text and end in text:
            payload = text.split(start, 1)[1].split(end, 1)[0].strip()
            try:
                return json.loads(payload)
            except Exception:
                return {"ok": False, "result": None, "stdout": text, "stderr": "", "error": "Could not parse pipeline JSON envelope."}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"ok": True, "result": text, "stdout": text, "stderr": "", "error": None}

    def _execute_pipeline_via_bridge(self, host: str, source: str, timeout: float = 120.0):
        host = (host or "").lower()
        if host == "maya":
            from tech_connector.bridges.maya.maya_bridge import MayaBridge
            return MayaBridge().execute(source, timeout=timeout)
        if host == "blender":
            from tech_connector.bridges.blender.blender_bridge import BlenderBridge
            return BlenderBridge().execute(source, timeout=timeout)
        if host == "unreal":
            from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
            response = UnrealBridge().execute_python(source, timeout=timeout, reset_globals=True)
            return bool(response.get("ok", True)), response
        if host == "substance_painter":
            from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
            return SubstancePainterBridge().execute(source, timeout=timeout)
        if host == "unity":
            from tech_connector.bridges.unity.unity_bridge import UnityBridge
            return UnityBridge().execute(source, timeout=timeout)
        if host == "houdini":
            from tech_connector.bridges.houdini.houdini_bridge import HoudiniBridge
            return HoudiniBridge().execute(source, timeout=timeout)
        return False, f"No direct pipeline bridge configured for host: {host}"

    def _pipeline_bridge_port(self, host: str):
        host = (host or "").lower()
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

    def _cross_dcc_pipeline_hosts(self) -> list[str]:
        supported = {
            "maya",
            "blender",
            "unreal",
            "motionbuilder",
            "houdini",
            "substance_painter",
            "unity",
        }
        hosts: list[str] = []
        for step in getattr(self, "wf_builder_steps", []) or []:
            symbol = dict(step.get("symbol") or {})
            host = str(symbol.get("provider_id") or symbol.get("host") or "").strip().lower()
            if host in supported and host not in hosts:
                hosts.append(host)
        if hosts:
            return hosts

        flow = dict(getattr(self, "_last_pipeline_prompt_flow", {}) or {})
        plan = dict(flow.get("workflow_plan") or {})
        for step in plan.get("steps") or []:
            symbol = dict(step.get("symbol") or {})
            host = str(symbol.get("provider_id") or symbol.get("host") or "").strip().lower()
            if host in supported and host not in hosts:
                hosts.append(host)
        return hosts

    def _notify_pipeline_output(self, title: str, body: str, *, status: str = "", source: str = ""):
        try:
            if not (
                self.settings.get("notify_slack_enabled")
                or self.settings.get("notify_email_enabled")
            ):
                return
            from tech_connector.services.notification_service import send_pipeline_output

            results = send_pipeline_output(self.settings, title, body, status=status, source=source)
            if hasattr(self, "append"):
                self.append(f"\n[Notification Outputs]\n{results}\n")
        except Exception as exc:
            if hasattr(self, "append"):
                self.append(f"\n[Notification Outputs Failed] {exc}\n")

    def run_selected_workflow(self):
        if getattr(self, "_workflow_run_in_flight", False):
            self.wf_test_status.setText("Pipeline run is already active.")
            self.wf_test_status.setStyleSheet("color: #f1d38a;")
            return
        try:
            from tech_connector.services.interaction_lifecycle_service import InteractionLifecycleManager

            lifecycle = getattr(self, "_interaction_lifecycle", None)
            if lifecycle is None:
                lifecycle = InteractionLifecycleManager()
                self._interaction_lifecycle = lifecycle
            operation = lifecycle.start_operation(origin_message_id="workflow_run")
            if not lifecycle.claim_action(
                operation_id=operation.operation_id,
                action_id="run_workflow",
                idempotency_key="workflow:run:selected",
            ):
                self.wf_test_status.setText("Pipeline run is already active.")
                self.wf_test_status.setStyleSheet("color: #f1d38a;")
                return
            self._workflow_run_in_flight = True
        except Exception:
            pass
        selected_meta = self._selected_pipeline_code_and_meta()
        if selected_meta is None:
            selected_meta = self._current_pipeline_code_and_meta()
        code, func_name, slots, host, project_root, label = selected_meta
        if not code.strip():
            self.wf_test_status.setText("No pipeline code to run. Save/compile or add nodes first.")
            self.wf_test_status.setStyleSheet("color: #e05252;")
            self._workflow_run_in_flight = False
            return
        if not func_name:
            self.wf_test_status.setText("Could not determine pipeline function name.")
            self.wf_test_status.setStyleSheet("color: #e05252;")
            self._workflow_run_in_flight = False
            return
        runtime_source = self._pipeline_runtime_source(code, func_name, slots, project_root)
        self._last_test_output = f"Host: {host}\nFunction: {func_name}\nSource: {label}\nProject: {project_root}\n"
        self.wf_test_log_btn.setEnabled(True)
        if host == "cross_dcc":
            for required_host in self._cross_dcc_pipeline_hosts():
                if self._pipeline_bridge_port(required_host):
                    continue
                self.wf_test_status.setText(
                    f"{required_host} is required by this cross-DCC pipeline. Waiting for its bridge."
                )
                self.wf_test_status.setStyleSheet("color: #e05252;")
                try:
                    if hasattr(self, "set_card"):
                        self.set_card(required_host, "bad", "Not open")
                    if hasattr(self, "_prompt_launch_missing_dcc_bridge"):
                        self._prompt_launch_missing_dcc_bridge(
                            required_host,
                            f"This cross-DCC pipeline requires {required_host}, but its Tech Connector bridge is not connected.",
                            self.run_selected_workflow,
                            f"Resume cross-DCC pipeline: {func_name}",
                        )
                finally:
                    self._workflow_run_in_flight = False
                return
        if host and host not in {"local", "cross_dcc", "unknown"}:
            port = self._pipeline_bridge_port(host)
            if not port:
                self.wf_test_status.setText(f"{host} is not connected. Open it, then run the pipeline again.")
                self.wf_test_status.setStyleSheet("color: #e05252;")
                try:
                    if hasattr(self, "set_card"):
                        self.set_card(host, "bad", "Not open")
                    if hasattr(self, "_prompt_launch_missing_dcc_bridge"):
                        self._prompt_launch_missing_dcc_bridge(
                            host,
                            f"{host} is not open or its Tech Connector bridge is not connected.",
                            self.run_selected_workflow,
                            f"Run pipeline: {func_name}",
                        )
                finally:
                    self._workflow_run_in_flight = False
                return
            self.wf_test_status.setText(f"Running pipeline in {host} bridge...")
            self.wf_test_status.setStyleSheet("color: #4aa3ff;")
            try:
                ok, raw = self._execute_pipeline_via_bridge(host, runtime_source, timeout=120.0)
                envelope = self._parse_pipeline_bridge_output(raw)
                self._last_workflow_result = envelope.get("result")
                self._last_workflow_envelope = envelope
                self._last_test_output += "\nRaw bridge output:\n" + str(raw) + "\n\nEnvelope:\n" + str(envelope)
                if ok and envelope.get("ok"):
                    self.wf_test_status.setText(f"Pipeline completed in {host} bridge.")
                    self.wf_test_status.setStyleSheet("color: #5bd000;")
                else:
                    self.wf_test_status.setText(f"Pipeline failed in {host} bridge. See Test Log.")
                    self.wf_test_status.setStyleSheet("color: #e05252;")
                if hasattr(self, "append"):
                    self.append(f"\n[Pipeline Bridge Run: {host}] ok={ok} result={self._last_workflow_result!r}\n")
                self._notify_pipeline_output(
                    f"Tech Connector Pipeline: {func_name}",
                    self._last_test_output,
                    status="ok" if ok and envelope.get("ok") else "failed",
                    source=f"{host} bridge",
                )
                try:
                    getattr(self, "_interaction_lifecycle", None).cancel_current(reason="workflow_run_completed")
                except Exception:
                    pass
                self._workflow_run_in_flight = False
                return
            except Exception as exc:
                self._last_test_output += "\nBridge execution exception:\n" + str(exc)
                self.wf_test_status.setText(f"Bridge run failed: {exc}")
                self.wf_test_status.setStyleSheet("color: #e05252;")
                self._notify_pipeline_output(
                    f"Tech Connector Pipeline Failed: {func_name}",
                    self._last_test_output,
                    status="exception",
                    source=f"{host} bridge",
                )
                try:
                    getattr(self, "_interaction_lifecycle", None).cancel_current(reason="workflow_run_failed")
                except Exception:
                    pass
                self._workflow_run_in_flight = False
                return
        runner_path = self._write_workflow_runner_script(str(project_root), "", func_name, slots)
        runner_path.write_text(runtime_source, encoding="utf-8")
        command = self._quote_workflow_command([*self._workflow_python_launcher(), "-u", str(runner_path)])
        sent = self._send_workflow_command_to_terminal(command, str(project_root), label="Pipeline")
        self._last_test_output += f"\nLocal fallback command:\n{command}\n"
        self.wf_test_status.setText("Sent local pipeline command to terminal." if sent else "Pipeline command prepared, but terminal could not be opened.")
        self.wf_test_status.setStyleSheet("color: #4aa3ff;" if sent else "color: #e05252;")
        self._notify_pipeline_output(
            f"Tech Connector Pipeline Command: {func_name}",
            self._last_test_output,
            status="sent_to_terminal" if sent else "terminal_unavailable",
            source="local fallback",
        )
        try:
            lifecycle = getattr(self, "_interaction_lifecycle", None)
            if lifecycle is not None:
                current = lifecycle.current_operation()
                if current:
                    current.status = "running_external"
        except Exception:
            pass

    def run_selected_workflow_test(self):
        selected = self.workflows_list.selectedItems()
        if not selected:
            return
        manifest_path_str = selected[0].data(Qt.UserRole)

        manifest_path = Path(manifest_path_str)
        project_root = manifest_path.parent.parent.parent
        slug = manifest_path.stem
        host = manifest_path.parent.name
        test_file = project_root / "tests" / f"test_workflow_{host}_{slug}.py"

        if not test_file.exists():
            self.wf_test_status.setText("Test file not found.")
            self.wf_test_status.setStyleSheet("color: #e05252;")
            return

        command = self._quote_workflow_command([*self._workflow_python_launcher(), "-u", "-m", "pytest", str(test_file)])

        self.wf_test_status.setText("Sent pytest command to terminal.")
        self.wf_test_status.setStyleSheet("color: #4aa3ff;")
        self._last_test_output = f"Command:\n{command}\n\nTest file:\n{test_file}"
        self.wf_test_log_btn.setEnabled(True)

        sent = self._send_workflow_command_to_terminal(command, str(project_root), label="Pytest")
        if hasattr(self, "append"):
            self.append(f"\n[Pipeline Test Command]\n{command}\n[cwd] {project_root}\n")
        if not sent:
            self.wf_test_status.setText("Test command prepared, but terminal could not be opened.")
            self.wf_test_status.setStyleSheet("color: #e05252;")

    def view_test_log(self):
        log = getattr(self, "_last_test_output", "No test run log available.")
        QMessageBox.information(self, "Pytest Output Log", log)

    def load_selected_workflow_to_builder(self):
        selected = self.workflows_list.selectedItems()
        if not selected:
            return

        manifest_path_str = selected[0].data(Qt.UserRole)
        data = self.loaded_workflows.get(manifest_path_str)
        if not data:
            return

        self.set_pipeline_composer_enabled(True)
        self.wf_pipeline_current_key = manifest_path_str

        selected_capabilities = data.get("selected_capabilities", [])
        slots = data.get("slots", {})
        links = data.get("links", [])
        host = data.get("host", "maya")
        goal = data.get("goal", "")
        function_name = data.get("naming", {}).get("original_function") or data.get(
            "function", ""
        )

        self.wf_build_name.setText(function_name)
        self.wf_build_goal.setText(goal)

        idx = self.wf_build_host.findText(host.lower())
        if idx >= 0:
            self.wf_build_host.setCurrentIndex(idx)

        for i in reversed(range(self.wf_steps_layout.count())):
            item = self.wf_steps_layout.itemAt(i)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        self.wf_steps_layout.addStretch(1)
        self.wf_builder_steps = []
        self._rebuild_pipeline_graph_from_steps()

        self._ensure_pipeline_symbols_available_nonblocking()

        for cap in selected_capabilities:
            self.add_builder_step(custom_sym=cap)

        for idx, step in enumerate(self.wf_builder_steps, start=1):
            params_table = step["table"]

            for r in range(params_table.rowCount()):
                param_name_item = params_table.item(r, 0)
                cell_widget = params_table.cellWidget(r, 1)

                if param_name_item and cell_widget:
                    p_name = param_name_item.text()
                    val_edit = cell_widget.findChild(QLineEdit)
                    conn_combo = cell_widget.findChild(QComboBox)
                    conn_check = cell_widget.findChild(QCheckBox)

                    matching_link = None
                    target_str = f"step{idx}.{p_name}"
                    for link in links:
                        if link.get("to") == target_str:
                            matching_link = link
                            break

                    if matching_link:
                        conn_check.setChecked(True)
                        from_str = matching_link.get("from", "")
                        # New format: "step1.varname" or legacy "step1.output"
                        if from_str.startswith("step"):
                            parts = from_str.split(".", 1)
                            prev_step_num = parts[0].replace("step", "").strip()
                            out_var = parts[1] if len(parts) > 1 else "result"
                            # Build the $step combo key - new format uses dot, legacy used no dot
                            if out_var == "output":
                                combo_val = f"$step{prev_step_num}"
                            else:
                                combo_val = f"$step{prev_step_num}.{out_var}"
                            combo_idx = -1
                            for c_i in range(conn_combo.count()):
                                cd = conn_combo.itemData(c_i) or ""
                                if cd == combo_val:
                                    combo_idx = c_i
                                    break
                            if combo_idx < 0 and out_var == "output":
                                legacy_val = f"$step{prev_step_num}.result"
                                for c_i in range(conn_combo.count()):
                                    if (conn_combo.itemData(c_i) or "") == legacy_val:
                                        combo_idx = c_i
                                        break
                            if combo_idx >= 0:
                                conn_combo.setCurrentIndex(combo_idx)
                            else:
                                conn_combo.setEditText(combo_val)
                    else:
                        conn_check.setChecked(False)
                        slot_key = f"step{idx}_{p_name}"
                        if slot_key in slots:
                            val = slots[slot_key]
                            if isinstance(val, str):
                                val_edit.setText(val)
                            else:
                                val_edit.setText(repr(val) if val is not None else "")

        self.update_builder_code_preview()
        for step_idx in range(1, len(self.wf_builder_steps) + 1):
            self._refresh_builder_output_consumers(step_idx)
        self.wf_stack.setCurrentIndex(1)

    def delete_selected_workflow(self):
        selected = self.workflows_list.selectedItems()
        if not selected:
            return

        manifest_path_str = selected[0].data(Qt.UserRole)
        manifest_path = Path(manifest_path_str)
        py_path = manifest_path.with_suffix(".py")

        slug = manifest_path.stem
        host = manifest_path.parent.name
        project_root = manifest_path.parent.parent.parent
        test_path = project_root / "tests" / f"test_workflow_{host}_{slug}.py"

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete this pipeline?\n\nThis will delete:\n"
            f"- {manifest_path.name}\n- {py_path.name}\n- {test_path.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                if manifest_path.exists():
                    manifest_path.unlink()
                if py_path.exists():
                    py_path.unlink()
                if test_path.exists():
                    test_path.unlink()
                self.refresh_workflows_list()
                QMessageBox.information(
                    self, "Success", "Pipeline deleted successfully."
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "Error Deleting", f"Failed to delete pipeline files:\n{e}"
                )

    def export_selected_workflow(self):
        """Copy the pipeline .py to a user-chosen destination."""
        selected = self.workflows_list.selectedItems()
        if not selected:
            return

        manifest_path = Path(selected[0].data(Qt.UserRole))
        py_path = manifest_path.with_suffix(".py")
        if not py_path.exists():
            QMessageBox.warning(
                self, "Not Found", f"Workflow .py not found:\n{py_path}"
            )
            return

        start_dir = self.settings.get("active_project") or str(Path.home())
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export Pipeline",
            str(Path(start_dir) / py_path.name),
            "Python Files (*.py);;All Files (*)",
        )
        if not dest:
            return

        try:
            import shutil

            shutil.copy2(str(py_path), dest)
            self.append(f"\n[Pipeline exported to: {dest}]\n")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def append_selected_workflow_to_file(self):
        """Append this pipeline's function code to an existing .py file."""
        selected = self.workflows_list.selectedItems()
        if not selected:
            return

        manifest_path = Path(selected[0].data(Qt.UserRole))
        py_path = manifest_path.with_suffix(".py")
        if not py_path.exists():
            QMessageBox.warning(
                self, "Not Found", f"Workflow .py not found:\n{py_path}"
            )
            return

        wf_code = py_path.read_text(encoding="utf-8", errors="replace")

        start_dir = self.settings.get("active_project") or str(Path.home())
        dest, _ = QFileDialog.getOpenFileName(
            self,
            "Append to Existing Python File",
            start_dir,
            "Python Files (*.py);;All Files (*)",
        )
        if not dest:
            return

        try:
            dest_path = Path(dest)
            existing = dest_path.read_text(encoding="utf-8", errors="replace")

            # Separate the function definition from any __main__ block / imports
            # Append after the last non-empty line
            separator = f"\n\n# --- Appended pipeline: {manifest_path.stem} ---\n"
            dest_path.write_text(
                existing.rstrip() + separator + wf_code, encoding="utf-8"
            )

            self.append(f"\n[Pipeline appended to: {dest}]\n")

            # Offer to open it
            reply = QMessageBox.question(
                self,
                "Open File?",
                f"Appended to {dest_path.name}.\nOpen it in the editor?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self.open_code_file(dest)
        except Exception as e:
            QMessageBox.critical(self, "Append Failed", str(e))

    def start_new_workflow_builder(self):
        try:
            if hasattr(self, "workflows_list"):
                self.workflows_list.clearSelection()
        except Exception:
            pass
        self.set_pipeline_composer_enabled(True)
        self.wf_pipeline_current_key = "new"
        self._workflow_python_manually_edited = False
        try:
            self.wf_stack.setCurrentIndex(1)
            self.wf_builder_tabs.setCurrentIndex(0)
            self.wf_node_view.setFocus()
        except Exception:
            pass
        self.wf_build_name.clear()
        self.wf_build_goal.clear()

        # Clear steps layout
        for i in reversed(range(self.wf_steps_layout.count())):
            item = self.wf_steps_layout.itemAt(i)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        # Re-add stretch at bottom
        self.wf_steps_layout.addStretch(1)
        self.wf_builder_steps = []
        self._rebuild_pipeline_graph_from_steps()

        self._ensure_pipeline_symbols_available_nonblocking()

        # Clearing the filter textbox automatically triggers filter_discovered_symbols("")
        self.wf_build_func_filter.clear()
        self.filter_discovered_symbols("")

        self.wf_stack.setCurrentIndex(1)

    def _ensure_pipeline_symbols_available_nonblocking(self) -> bool:
        symbols = getattr(self, "_cached_discovered_symbols", []) or getattr(self, "all_discovered_symbols", []) or []
        if symbols:
            self.all_discovered_symbols = symbols
            self._refresh_pipeline_node_view_tool_symbols()
            return True
        self.all_discovered_symbols = []
        self._refresh_pipeline_node_view_tool_symbols()
        try:
            self.start_async_symbol_indexing()
            self._report_workflow_builder_event("Function list is preparing in the background.")
            self._poll_pipeline_symbol_cache_for_graph()
        except Exception as exc:
            self._report_workflow_builder_event(f"Could not start function discovery: {exc}")
        return False

    def ensure_pipeline_graph_interaction_ready(self):
        """Make the node graph immediately usable when the user clicks into it.

        This path is intentionally lighter than the New Graph button: it must not
        wait on indexing or run a project-wide symbol scan from a mouse event.
        """
        if getattr(self, "_pipeline_graph_interaction_bootstrap_active", False):
            return
        self._pipeline_graph_interaction_bootstrap_active = True
        try:
            view = getattr(self, "wf_node_view", None)
            if view is None:
                return

            active_key = str(getattr(self, "wf_pipeline_current_key", "") or "")
            if not active_key:
                try:
                    if hasattr(self, "workflows_list"):
                        self.workflows_list.clearSelection()
                except Exception:
                    pass
                try:
                    self.set_pipeline_composer_enabled(True)
                except Exception:
                    pass
                self.wf_pipeline_current_key = "new"
                self._workflow_python_manually_edited = False
                if not isinstance(getattr(self, "wf_builder_steps", None), list):
                    self.wf_builder_steps = []
                try:
                    self._rebuild_pipeline_graph_from_steps()
                except Exception:
                    pass

            self._ensure_pipeline_symbols_available_nonblocking()
        finally:
            self._pipeline_graph_interaction_bootstrap_active = False

    def _poll_pipeline_symbol_cache_for_graph(self, attempts: int = 0):
        symbols = getattr(self, "_cached_discovered_symbols", []) or []
        if symbols:
            self.all_discovered_symbols = symbols
            self._refresh_pipeline_node_view_tool_symbols()
            try:
                self._report_workflow_builder_event(f"Function list ready: {len(symbols)} symbols available.")
            except Exception:
                pass
            return
        thread = getattr(self, "_indexing_thread", None)
        if thread is not None and getattr(thread, "is_alive", lambda: False)() and attempts < 240:
            QTimer.singleShot(500, lambda: self._poll_pipeline_symbol_cache_for_graph(attempts + 1))

    def _workflow_intent_roots(self) -> list[str]:
        roots = []
        try:
            roots.extend(self.all_roots() if hasattr(self, "all_roots") else [])
        except Exception:
            pass
        try:
            from tech_connector.models.project import dcc_tool_roots
            roots.extend(dcc_tool_roots(getattr(self, "settings", {}) or {}))
        except Exception:
            pass
        normalized = []
        for root in roots:
            try:
                resolved = str(Path(root).resolve())
            except Exception:
                resolved = str(root)
            if resolved and resolved not in normalized:
                normalized.append(resolved)
        return normalized

    def build_pipeline_graph_from_prompt(self):
        prompt = ""
        try:
            prompt = self.wf_build_goal.text().strip()
        except Exception:
            pass
        if not prompt:
            QMessageBox.information(
                self,
                "Pipeline Prompt Needed",
                "Describe the pipeline in the Pipeline Goal / Description field first.",
            )
            return

        name = ""
        try:
            name = self.wf_build_name.text().strip()
        except Exception:
            pass

        try:
            from tech_connector.services.prompt.pipeline_prompt_flow_service import (
                resolve_pipeline_prompt_flow,
            )
            roots = self._workflow_intent_roots()
            flow_result = resolve_pipeline_prompt_flow(
                prompt,
                roots,
                host_hint="cross_dcc",
                decision_facts={
                    "settings": dict(getattr(self, "settings", {}) or {}),
                    "planning_preferences": {
                        "use_default_settings": bool(
                            self.wf_use_default_settings_checkbox.isChecked()
                        ),
                        "semantic_verification": True,
                        "semantic_understanding": True,
                        "custom_settings": {
                            "unreal_destination_path": self.wf_unreal_destination_edit.text().strip(),
                        },
                    },
                },
                progress_callback=self._report_pipeline_prompt_progress,
            )
            route_data = dict(flow_result.get("route_decision") or {})
            self._last_prompt_route_decision = route_data
            self._last_pipeline_prompt_flow = flow_result
            if route_data.get("route") not in {"pipeline_graph", "action_graph"}:
                QMessageBox.information(
                    self,
                    "Prompt Needs Different Route",
                    "This prompt does not look like a pipeline graph request yet.\n\n"
                    f"Route: {route_data.get('route')}\n"
                    f"Mode: {route_data.get('operation_mode')}\n"
                    f"Missing: {', '.join(route_data.get('missing_info') or []) or 'none'}",
                )
                return
            validation = dict(flow_result.get("understanding_validation") or {})
            if not validation.get("valid"):
                QMessageBox.information(
                    self,
                    "Pipeline Prompt Needs Clarification",
                    "\n".join(validation.get("reasons") or ["The requested pipeline is ambiguous."]),
                )
                return
            action_graph = dict(flow_result.get("action_graph") or {})
            plan = flow_result.get("workflow_plan")
            if (
                plan
                and not plan.get("success")
                and not self.wf_use_default_settings_checkbox.isChecked()
                and plan.get("unresolved_inputs")
            ):
                custom_settings = {
                    "unreal_destination_path": self.wf_unreal_destination_edit.text().strip(),
                }
                stage_lookup = {
                    str(row.get("id") or ""): row
                    for row in action_graph.get("stages") or []
                }
                for unresolved in plan.get("unresolved_inputs") or []:
                    parameter = str(unresolved.get("required_output") or "").strip()
                    question = str(
                        unresolved.get("question")
                        or f"What should `{parameter}` use?"
                    )
                    value, accepted = QInputDialog.getText(
                        self,
                        "Pipeline Setting Required",
                        question,
                    )
                    if not accepted:
                        return
                    value = value.strip()
                    if not value:
                        QMessageBox.information(
                            self,
                            "Pipeline Setting Required",
                            f"`{parameter}` cannot be empty while Default Settings is off.",
                        )
                        return
                    stage = stage_lookup.get(str(unresolved.get("step") or ""), {})
                    operation = str(stage.get("operation") or "")
                    host = str(stage.get("host") or unresolved.get("host") or "")
                    key = (
                        f"{host}.{operation}.{parameter}"
                        if host and operation
                        else parameter
                    )
                    custom_settings[key] = value
                flow_result = resolve_pipeline_prompt_flow(
                    prompt,
                    roots,
                    host_hint="cross_dcc",
                    decision_facts={
                        "settings": dict(getattr(self, "settings", {}) or {}),
                        "planning_preferences": {
                            "use_default_settings": False,
                            "semantic_verification": True,
                            "semantic_understanding": True,
                            "custom_settings": custom_settings,
                        },
                    },
                    progress_callback=self._report_pipeline_prompt_progress,
                )
                action_graph = dict(flow_result.get("action_graph") or {})
                plan = flow_result.get("workflow_plan")
                self._last_pipeline_prompt_flow = flow_result
            if not plan:
                validation = action_graph.get("validation") or {}
                diagnostics = action_graph.get("diagnostics") or []
                QMessageBox.information(
                    self,
                    "Action Plan Created",
                    "The prompt produced an action graph, but not a pipeline graph yet.\n\n"
                    + "\n".join(diagnostics or [f"Intent: {action_graph.get('intent')}"])
                    + f"\n\nValidation: {'valid' if validation.get('valid') else 'needs attention'}",
                )
                return
        except Exception as exc:
            self._report_workflow_error("Prompt-to-graph resolution failed", exc)
            return

        diagnostics = plan.get("diagnostics") or []
        if not plan.get("success"):
            unresolved = list(plan.get("unresolved_inputs") or [])
            questions = [
                str(item.get("question") or "").strip()
                for item in unresolved
                if str(item.get("question") or "").strip()
            ]
            QMessageBox.warning(
                self,
                "Could Not Build Graph",
                "\n".join(
                    questions
                    or diagnostics[-4:]
                    or ["The prompt did not map cleanly to indexed functions."]
                ),
            )
            return

        try:
            self.start_new_workflow_builder()
            if name and hasattr(self, "wf_build_name"):
                self.wf_build_name.setText(name)
            elif hasattr(self, "wf_build_name"):
                self.wf_build_name.setText("prompt_pipeline")
            if hasattr(self, "wf_build_goal"):
                self.wf_build_goal.setText(prompt)

            added_steps = []
            for planned_step in plan.get("steps") or []:
                step_data = self.add_builder_step(custom_sym=planned_step.get("symbol") or {})
                if not step_data:
                    continue
                step_data["params"] = planned_step.get("params") or step_data.get("params") or []
                step_data["outputs"] = planned_step.get("outputs") or step_data.get("outputs") or []
                step_data["literal_values"] = planned_step.get("literal_values") or {}
                added_steps.append(step_data)

            self._apply_workflow_intent_links(added_steps, plan)
            view = getattr(self, "wf_node_view", None)
            if view and hasattr(view, "focus_all"):
                view.focus_all()
            self.update_builder_code_preview()
            
            unconnected_details = []
            if view:
                for idx, step in enumerate(added_steps, start=1):
                    step_id = step.get("graph_step_id")
                    symbol = step.get("symbol") or {}
                    params = step.get("params") or []
                    literals = step.get("literal_values") or {}
                    for p in params:
                        p_name = p.get("name")
                        if not p_name or p_name.startswith("*"):
                            continue
                        has_link = any(l.to_step == step_id and l.to_input == p_name and l.kind == "data" for l in view.links)
                        has_literal = p_name in literals and str(literals[p_name]).strip() != ""
                        if not has_link and not has_literal:
                            unconnected_details.append(f"- Step {idx} ({symbol.get('name')}): Param '{p_name}' is unconnected")
            
            if unconnected_details:
                QMessageBox.warning(
                    self,
                    "Pipeline Connections Incomplete",
                    "The generated pipeline contains unconnected inputs:\n\n"
                    + "\n".join(unconnected_details)
                    + "\n\nSwitching to the Pipelines builder tab so you can connect them manually."
                )
                if hasattr(self, "workspace_tabs"):
                    self.workspace_tabs.setCurrentIndex(3)

            self._report_workflow_builder_event(
                f"Built pipeline graph from action graph: {len(added_steps)} node(s), "
                f"{len(plan.get('data_links') or [])} data link(s), {len(plan.get('flow_links') or [])} flow link(s)."
            )
            try:
                self._last_action_graph = action_graph
                self._last_pipeline_prompt_flow = flow_result
            except Exception:
                pass
        except Exception as exc:
            self._report_workflow_error("Build graph from prompt failed", exc)

    def _apply_workflow_intent_links(self, steps: list[dict], plan: dict):
        view = getattr(self, "wf_node_view", None)
        if not view:
            return
        try:
            from tech_connector.ui.pipeline_node_types import FLOW_PORT
            from tech_connector.ui.pipeline_node_view import PipelineGraphLink
        except Exception:
            return

        view.links.clear()
        for step in steps:
            if hasattr(view, "refresh_node_literals"):
                view.refresh_node_literals(step)

        def step_id(step_index):
            idx = int(step_index or 0) - 1
            if idx < 0 or idx >= len(steps):
                return ""
            return steps[idx].get("graph_step_id") or ""

        for link in plan.get("data_links") or []:
            source = step_id(link.get("from_step"))
            target = step_id(link.get("to_step"))
            if source and target:
                view.links.append(
                    PipelineGraphLink(
                        source,
                        link.get("from_output") or "result",
                        target,
                        link.get("to_input") or "",
                        "data",
                    )
                )
        for link in plan.get("flow_links") or []:
            source = step_id(link.get("from_step"))
            target = step_id(link.get("to_step"))
            if source and target:
                view.links.append(PipelineGraphLink(source, FLOW_PORT, target, FLOW_PORT, "flow"))
        view.refresh_links(rebuild=True)
        view.graphChanged.emit()
        view.orderChanged.emit(view.execution_order())

    def start_async_symbol_indexing(self):
        import threading

        if hasattr(self, "_indexing_thread") and self._indexing_thread.is_alive():
            return

        def run_indexing():
            try:
                symbols = self.get_all_available_symbols()
                self._cached_discovered_symbols = symbols
            except Exception as e:
                print(f"Error during async symbol indexing: {e}")

        self._indexing_thread = threading.Thread(target=run_indexing, daemon=True)
        self._indexing_thread.start()

    def _pipeline_symbol_dcc_keys(self, sym: dict) -> set[str]:
        text = " ".join(
            str((sym or {}).get(k) or "")
            for k in ("host", "package", "module", "file_path", "source_package", "function_path", "kind", "utility_kind")
        ).lower().replace("\\", "/")
        keys = set()
        if "maya" in text:
            keys.add("maya")
        if "unreal" in text:
            keys.add("unreal")
        if "blender" in text or "bpy" in text:
            keys.add("blender")
        if "motionbuilder" in text or "mobu" in text:
            keys.add("motionbuilder")
        if "substance" in text or "painter" in text:
            keys.add("substance_painter")
        if "unity" in text:
            keys.add("unity")
        if "utility" in text or (sym or {}).get("utility_kind"):
            keys.add("utility")
        if not keys:
            keys.add("project")
        return keys

    def _refresh_pipeline_node_view_tool_symbols(self):
        view = getattr(self, "wf_node_view", None)
        if view is not None and hasattr(view, "set_tool_symbols"):
            try:
                view.set_tool_symbols(getattr(self, "all_discovered_symbols", []) or [])
            except Exception:
                pass

    def _current_pipeline_dcc_filter(self) -> str:
        box = getattr(self, "wf_build_dcc_filter", None)
        if not box:
            return "all"
        try:
            return str(box.currentData() or box.currentText() or "all").lower().strip().replace(" ", "_")
        except Exception:
            return "all"

    def schedule_pipeline_symbol_filter(self):
        timer = getattr(self, "wf_symbol_filter_timer", None)
        if timer is not None:
            try:
                timer.start()
                return
            except Exception:
                pass
        try:
            self.filter_discovered_symbols(self.wf_build_func_filter.text())
        except Exception:
            pass

    def _pipeline_symbol_filter_meta(self, idx: int, sym: dict) -> dict:
        cache = getattr(self, "_pipeline_symbol_filter_cache", None)
        if cache is None:
            cache = {}
            self._pipeline_symbol_filter_cache = cache
        key = (
            idx,
            str(sym.get("name") or ""),
            str(sym.get("kind") or ""),
            str(sym.get("host") or ""),
            str(sym.get("package") or sym.get("source_package") or ""),
            str(sym.get("module") or sym.get("function_path") or ""),
            str(sym.get("file_path") or ""),
            str(sym.get("utility_kind") or ""),
        )
        cached = cache.get(key)
        if cached:
            return cached

        name = str(sym.get("name") or "unnamed")
        kind = str(sym.get("kind") or "function")
        host = str(sym.get("host") or "").lower()
        package = str(sym.get("package") or sym.get("source_package") or "").lower()
        module = str(sym.get("module") or sym.get("function_path") or "").lower()
        file_path = str(sym.get("file_path") or "")
        file_name = Path(file_path).name
        dcc_keys = self._pipeline_symbol_dcc_keys(sym)
        dcc_label = "/".join(sorted(dcc_keys))
        search_text = " ".join(
            (
                name.lower(),
                kind.lower(),
                host,
                package,
                module,
                file_name.lower(),
                file_path.lower(),
                str(sym.get("description") or sym.get("docstring") or "").lower(),
                str(sym.get("signature") or "").lower(),
            )
        )
        cached = {
            "name_lower": name.lower(),
            "dcc_keys": dcc_keys,
            "display": f"{kind}: {name} [{file_name}] - {dcc_label}",
            "search_text": search_text,
            "label_lower": f"{kind}: {name} [{file_name}] - {dcc_label}".lower(),
            "path_lower": file_path.lower(),
            "priority": 0,
        }
        cache[key] = cached
        return cached

    def filter_discovered_symbols(self, text):
        query = (text or "").strip().lower()
        selected_dcc = self._current_pipeline_dcc_filter()
        terms = query.split()

        matched_items = []
        for idx, sym in enumerate(getattr(self, "all_discovered_symbols", []) or []):
            if str(sym.get("name") or "").strip() == "__init__":
                continue
            meta = self._pipeline_symbol_filter_meta(idx, sym)
            if selected_dcc not in {"", "all"} and selected_dcc not in meta["dcc_keys"]:
                continue
            if not terms or all(term in meta["search_text"] for term in terms):
                rank = pipeline_tool_query_rank(
                    {
                        "name": meta["name_lower"],
                        "label_lower": meta["label_lower"],
                        "path_lower": meta["path_lower"],
                        "priority": meta["priority"],
                    },
                    terms,
                )
                matched_items.append((rank, meta["display"], idx))

        if not matched_items and query:
            import difflib

            scored_items = []
            for idx, sym in enumerate(getattr(self, "all_discovered_symbols", []) or []):
                if str(sym.get("name") or "").strip() == "__init__":
                    continue
                meta = self._pipeline_symbol_filter_meta(idx, sym)
                if selected_dcc not in {"", "all"} and selected_dcc not in meta["dcc_keys"]:
                    continue
                ratio = difflib.SequenceMatcher(None, query, meta["name_lower"]).ratio()
                if ratio > 0.4:
                    scored_items.append((ratio, f"{meta['display']} (Fuzzy Match)", idx))
            scored_items.sort(key=lambda item: item[0], reverse=True)
            matched_items.extend((0, display, idx) for _ratio, display, idx in scored_items[:10])

        matched_items.sort(key=lambda item: (item[0], item[1].lower()))
        max_items = 80 if not query else 5
        box = getattr(self, "wf_build_func_box", None)
        if box is None:
            return
        box.blockSignals(True)
        try:
            box.clear()
            for _score, display, idx in matched_items[:max_items]:
                try:
                    box.addItem(display, self.all_discovered_symbols[idx])
                except Exception:
                    box.addItem(display, idx)
            if not query and len(matched_items) > max_items:
                box.addItem(f"Type more to narrow {len(matched_items) - max_items} more matches...", None)
        finally:
            box.blockSignals(False)

        if matched_items:
            try:
                box.setCurrentIndex(0)
            except Exception:
                pass

    def get_all_available_symbols(self):
        from tech_connector.models.constants import EXTERNAL_TOOLS_DIR
        from tech_connector.services.tool_discovery_service import (
            list_ingested_tools,
            list_internal_functions,
        )

        roots = self.all_roots() if hasattr(self, "all_roots") else []
        symbols = list_internal_functions(roots)

        ext_tools = self.settings.get("external_tools_dir", "") or str(EXTERNAL_TOOLS_DIR)
        if Path(ext_tools).exists():
            symbols.extend(list_ingested_tools(Path(ext_tools)))

        return symbols

    def _extract_init_params(self, class_source):
        import ast

        params = []
        try:
            tree = ast.parse(class_source)
            for node in ast.walk(tree):
                if (
                        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "__init__"
                ):
                    args = (
                            list(getattr(node.args, "posonlyargs", []))
                            + list(node.args.args)
                            + list(node.args.kwonlyargs)
                    )
                    for arg in args:
                        if arg.arg in {"self", "cls"}:
                            continue
                        annotation = ""
                        if arg.annotation:
                            try:
                                annotation = ast.unparse(arg.annotation).strip()
                            except Exception:
                                pass
                        params.append({"name": arg.arg, "annotation": annotation})
                    break
        except Exception:
            pass
        return params

    def are_types_compatible(self, input_type: str, output_type: str) -> bool:
        input_type = (input_type or "").strip().lower()
        output_type = (output_type or "").strip().lower()

        # If either is unspecified (Any or empty), allow it to be user-proof and flexible
        if (
                not input_type
                or not output_type
                or "any" in input_type
                or "any" in output_type
        ):
            return True

        # Direct match
        if input_type == output_type:
            return True

        # Numbers compatibility (e.g. float accepts int)
        if input_type in {"float", "number"} and output_type in {
            "int",
            "float",
            "number",
        }:
            return True

        # Union types (e.g. Union[str, int])
        if "union" in input_type:
            if output_type in input_type:
                return True

        return False

    def _normalized_builder_outputs(self, sym):
        outputs = sym.get("outputs") or []
        if not outputs:
            if sym.get("kind") == "class":
                outputs = [{"name": "instance", "annotation": sym.get("name", "")}]
            else:
                outputs = [
                    {
                        "name": "result",
                        "annotation": sym.get("return_annotation", "") or "",
                    }
                ]
        normalized = []
        for idx, out in enumerate(outputs):
            fallback_name = "result" if idx == 0 else f"output_{idx + 1}"
            normalized.append(
                {
                    "name": (out.get("name") or fallback_name).strip(),
                    "annotation": (out.get("annotation") or "").strip(),
                }
            )
        sym["outputs"] = normalized
        return normalized

    def _builder_output_supports_indexing(self, annotation):
        anno = (annotation or "").lower()
        return any(
            token in anno
            for token in ("tuple", "list", "sequence", "iterable", "set", "[]")
        )

    def _builder_output_supports_keying(self, annotation):
        anno = (annotation or "").lower()
        return "dict" in anno or "mapping" in anno

    def _builder_selector_tail_is_safe(self, selector_tail):
        if selector_tail is None:
            return False
        if selector_tail == "":
            return True
        return bool(re.fullmatch(r"(?:\[(?:\d+|'[^']*'|\"[^\"]*\")\])+", selector_tail))

    def _builder_output_ref_parts(self, output_ref):
        match = re.match(
            r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<selectors>(?:\[(?:\d+|'[^']*'|\"[^\"]*\")\])*)$",
            output_ref or "",
        )
        if not match:
            return output_ref or "result", ""
        return match.group("name"), match.group("selectors") or ""

    def _builder_step_output_expr(self, prev_step_num, output_ref):
        output_name, selector_tail = self._builder_output_ref_parts(output_ref)
        base_expr = f"step{prev_step_num}_outputs.get('{output_name}', step{prev_step_num}_result)"
        if self._builder_selector_tail_is_safe(selector_tail):
            return f"{base_expr}{selector_tail}"
        return base_expr

    def _builder_step_ref_expr(self, step_ref):
        ref = (step_ref or "").strip()
        match = re.match(
            r"^(?P<num>\d+)(?P<selectors>(?:\[(?:\d+|'[^']*'|\"[^\"]*\")\])*)$", ref
        )
        if match and self._builder_selector_tail_is_safe(
                match.group("selectors") or ""
        ):
            return f"step{match.group('num')}_result{match.group('selectors') or ''}"
        if "." in ref:
            prev_step_num, out_var = ref.split(".", 1)
            return self._builder_step_output_expr(prev_step_num, out_var)
        return f"step{ref}_result"

    def _builder_combo_connection_value(self, combo):
        if not combo:
            return ""
        current_text = (combo.currentText() or "").strip()
        if current_text.startswith("$step"):
            return current_text
        data = combo.itemData(combo.currentIndex()) if combo.currentIndex() > 0 else ""
        return (data or current_text or "").strip()

    def _populate_builder_connection_combo(
            self, combo, param_annotation, max_prev_steps, selected_data=None
    ):
        combo.blockSignals(True)
        combo.setEditable(True)
        combo.clear()
        combo.addItem(f"Select step output ({param_annotation or 'Any'})...")
        combo.setToolTip(f"Expected type: {param_annotation or 'Any'}")
        selected_index = 0

        for prev_idx, prev_step in enumerate(
                self.wf_builder_steps[:max_prev_steps], start=1
        ):
            prev_sym = prev_step["symbol"]
            prev_outputs = self._normalized_builder_outputs(prev_sym)
            for out in prev_outputs:
                out_name = out.get("name", "result")
                out_anno = out.get("annotation", "")
                if (
                        self.are_types_compatible(param_annotation, out_anno)
                        or not param_annotation
                ):
                    label = f"Step {prev_idx} > {prev_sym.get('name')} -> {out_name}"
                    if out_anno:
                        label += f" ({out_anno})"
                    data = f"$step{prev_idx}.{out_name}"
                    combo.addItem(label, data)
                    if data == selected_data:
                        selected_index = combo.count() - 1
                if self._builder_output_supports_indexing(out_anno):
                    for index in range(6):
                        indexed_ref = f"{out_name}[{index}]"
                        label = (
                            f"Step {prev_idx} > {prev_sym.get('name')} -> {indexed_ref}"
                        )
                        if out_anno:
                            label += f" ({out_anno})"
                        data = f"$step{prev_idx}.{indexed_ref}"
                        combo.addItem(label, data)
                        if data == selected_data:
                            selected_index = combo.count() - 1
                if self._builder_output_supports_keying(out_anno):
                    label = (
                        f"Step {prev_idx} > {prev_sym.get('name')} -> {out_name}['key']"
                    )
                    if out_anno:
                        label += f" ({out_anno})"
                    data = f"$step{prev_idx}.{out_name}['key']"
                    combo.addItem(label, data)
                    if data == selected_data:
                        selected_index = combo.count() - 1

        combo.setCurrentIndex(selected_index)
        if (
                selected_data
                and selected_index == 0
                and str(selected_data).startswith("$step")
        ):
            combo.setEditText(str(selected_data))
        combo.blockSignals(False)

    def open_builder_output_picker(self, combo, conn_check, current_step_num):
        output_refs = []
        for prev_idx, prev_step in enumerate(
                self.wf_builder_steps[: max(0, current_step_num - 1)], start=1
        ):
            prev_sym = prev_step["symbol"]
            for out in self._normalized_builder_outputs(prev_sym):
                out_name = out.get("name", "result")
                out_anno = out.get("annotation", "")
                label = f"Step {prev_idx} > {prev_sym.get('name')} -> {out_name}"
                if out_anno:
                    label += f" ({out_anno})"
                output_refs.append(
                    {
                        "label": label,
                        "ref": f"$step{prev_idx}.{out_name}",
                        "annotation": out_anno,
                    }
                )

        if not output_refs:
            QMessageBox.information(
                self,
                "No Outputs",
                "Add an earlier pipeline step before linking this input.",
            )
            return

        dialog = WorkflowOutputSelectorDialog(
            output_refs,
            current_ref=self._builder_combo_connection_value(combo),
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        selected_ref = dialog.selected_ref()
        if not selected_ref:
            return
        if not selected_ref.startswith("$step"):
            QMessageBox.warning(
                self,
                "Invalid Reference",
                "Pipeline output references must start with $step.",
            )
            return

        conn_check.setChecked(True)
        combo.setEditText(selected_ref)
        self.update_builder_code_preview()

    def _refresh_builder_connection_options(self, start_step=1):
        for step_idx, step in enumerate(self.wf_builder_steps, start=1):
            if step_idx < start_step:
                continue
            params_table = step["table"]
            for row in range(params_table.rowCount()):
                param_item = params_table.item(row, 0)
                cell_widget = params_table.cellWidget(row, 1)
                if not param_item or not cell_widget:
                    continue
                combo = cell_widget.findChild(QComboBox)
                if not combo:
                    continue
                selected_data = self._builder_combo_connection_value(combo)
                param_annotation = param_item.data(Qt.UserRole) or ""
                self._populate_builder_connection_combo(
                    combo, param_annotation, step_idx - 1, selected_data
                )

    def _builder_step_index_for_output_table(self, out_table):
        for idx, step in enumerate(self.wf_builder_steps, start=1):
            if step.get("outputs_table") is out_table:
                return idx
        return -1

    def _builder_step_index_for_widget(self, step_widget):
        for idx, step in enumerate(self.wf_builder_steps, start=1):
            if step.get("widget") is step_widget:
                return idx
        return -1

    def _builder_connection_records(self):
        records = []
        for target_idx, target_step in enumerate(self.wf_builder_steps, start=1):
            params_table = target_step["table"]
            for row in range(params_table.rowCount()):
                param_item = params_table.item(row, 0)
                cell_widget = params_table.cellWidget(row, 1)
                if not param_item or not cell_widget:
                    continue
                combo = cell_widget.findChild(QComboBox)
                check = cell_widget.findChild(QCheckBox)
                if not combo or not check or not check.isChecked():
                    continue
                data = self._builder_combo_connection_value(combo)
                if not data.startswith("$step"):
                    continue
                ref = data[len("$step"):].strip()
                if "." in ref:
                    source_num, output_name = ref.split(".", 1)
                else:
                    source_num, output_name = ref, "result"
                try:
                    source_idx = int(source_num)
                except ValueError:
                    continue
                if not 1 <= source_idx <= len(self.wf_builder_steps):
                    continue
                records.append(
                    {
                        "source_step": self.wf_builder_steps[source_idx - 1],
                        "output_name": output_name,
                        "target_step": target_step,
                        "target_row": row,
                    }
                )
        return records

    def _restore_builder_connection_records(self, records):
        for target_step in self.wf_builder_steps:
            params_table = target_step["table"]
            for row in range(params_table.rowCount()):
                cell_widget = params_table.cellWidget(row, 1)
                if not cell_widget:
                    continue
                check = cell_widget.findChild(QCheckBox)
                combo = cell_widget.findChild(QComboBox)
                if check and combo and check.isChecked():
                    check.setChecked(False)

        for record in records:
            if (
                    record["source_step"] not in self.wf_builder_steps
                    or record["target_step"] not in self.wf_builder_steps
            ):
                continue
            source_idx = self.wf_builder_steps.index(record["source_step"]) + 1
            target_step = record["target_step"]
            target_idx = self.wf_builder_steps.index(target_step) + 1
            if source_idx >= target_idx:
                continue
            params_table = target_step["table"]
            if record["target_row"] >= params_table.rowCount():
                continue
            cell_widget = params_table.cellWidget(record["target_row"], 1)
            if not cell_widget:
                continue
            check = cell_widget.findChild(QCheckBox)
            combo = cell_widget.findChild(QComboBox)
            if not check or not combo:
                continue
            wanted = f"$step{source_idx}.{record['output_name']}"
            for idx in range(combo.count()):
                if combo.itemData(idx) == wanted:
                    check.setChecked(True)
                    combo.setCurrentIndex(idx)
                    break
            else:
                check.setChecked(True)
                combo.setEditText(wanted)

    def _renumber_builder_steps(self):
        for idx, step in enumerate(self.wf_builder_steps, start=1):
            sym = step["symbol"]
            step["header_lbl"].setText(
                f"Step {idx}: {sym.get('kind')} {sym.get('name')} {step.get('dcc_tag', '')}"
            )
        self._refresh_builder_connection_options()
        for idx in range(1, len(self.wf_builder_steps) + 1):
            self._refresh_builder_output_consumers(idx)

    def _rename_builder_output_references(self, step_num, old_name, new_name):
        if not old_name or old_name == new_name:
            return
        old_ref = f"$step{step_num}.{old_name}"
        new_ref = f"$step{step_num}.{new_name}"
        for later_idx, later_step in enumerate(self.wf_builder_steps, start=1):
            if later_idx <= step_num:
                continue
            params_table = later_step["table"]
            for row in range(params_table.rowCount()):
                cell_widget = params_table.cellWidget(row, 1)
                if not cell_widget:
                    continue
                combo = cell_widget.findChild(QComboBox)
                if combo:
                    current_ref = self._builder_combo_connection_value(combo)
                    if current_ref == old_ref:
                        if combo.currentIndex() > 0:
                            combo.setItemData(combo.currentIndex(), new_ref)
                        combo.setEditText(new_ref)
                    elif current_ref.startswith(old_ref + "["):
                        renamed_ref = new_ref + current_ref[len(old_ref):]
                        if combo.currentIndex() > 0:
                            combo.setItemData(combo.currentIndex(), renamed_ref)
                        combo.setEditText(renamed_ref)

    def _refresh_builder_output_consumers(self, step_num):
        if step_num < 1 or step_num - 1 >= len(self.wf_builder_steps):
            return
        step = self.wf_builder_steps[step_num - 1]
        out_table = step.get("outputs_table")
        if not out_table:
            return
        outputs = self._normalized_builder_outputs(step["symbol"])
        out_table.blockSignals(True)
        for out_idx, out in enumerate(outputs):
            out_name = out.get("name", "result")
            key_item = out_table.item(out_idx, 2)
            if key_item:
                key_item.setText(f"$step{step_num}.{out_name}")

            consumers = []
            for later_idx, later_step in enumerate(self.wf_builder_steps, start=1):
                if later_idx <= step_num:
                    continue
                later_table = later_step["table"]
                for row in range(later_table.rowCount()):
                    p_item = later_table.item(row, 0)
                    cell_widget = later_table.cellWidget(row, 1)
                    if not p_item or not cell_widget:
                        continue
                    chk = cell_widget.findChild(QCheckBox)
                    combo = cell_widget.findChild(QComboBox)
                    if chk and chk.isChecked() and combo:
                        data = self._builder_combo_connection_value(combo)
                        if (
                                data == f"$step{step_num}.{out_name}"
                                or data.startswith(f"$step{step_num}.{out_name}[")
                                or data == f"$step{step_num}"
                        ):
                            consumers.append(f"Step {later_idx} > {p_item.text()}")
            used_item = out_table.item(out_idx, 3)
            if used_item:
                used_item.setText(", ".join(consumers) if consumers else "-")
                used_item.setForeground(Qt.cyan if consumers else Qt.gray)
        out_table.blockSignals(False)

    def _handle_builder_output_changed(self, item, out_table):
        step_num = self._builder_step_index_for_output_table(out_table)
        if item.column() not in (0, 1) or step_num - 1 >= len(self.wf_builder_steps):
            return
        step = self.wf_builder_steps[step_num - 1]
        outputs = self._normalized_builder_outputs(step["symbol"])
        row = item.row()
        if row >= len(outputs):
            return

        old_name = outputs[row].get("name", "result")
        new_text = item.text().strip()
        if item.column() == 0:
            import keyword

            if (
                    not new_text
                    or not new_text.isidentifier()
                    or keyword.iskeyword(new_text)
            ):
                item.setText(old_name)
                return
            duplicate = any(
                idx != row and out.get("name") == new_text
                for idx, out in enumerate(outputs)
            )
            if duplicate:
                item.setText(old_name)
                return
            outputs[row]["name"] = new_text
            item.setData(Qt.UserRole, new_text)
            self._rename_builder_output_references(step_num, old_name, new_text)
            self._refresh_builder_connection_options(start_step=step_num + 1)
        else:
            outputs[row]["annotation"] = new_text
            self._refresh_builder_connection_options(start_step=step_num + 1)

        self._refresh_builder_output_consumers(step_num)
        self.update_builder_code_preview()

    def _builder_output_validation_errors(self):
        import keyword

        errors = []
        for step_idx, step in enumerate(self.wf_builder_steps, start=1):
            seen = set()
            for out in self._normalized_builder_outputs(step["symbol"]):
                name = out.get("name", "")
                if not name or not name.isidentifier() or keyword.iskeyword(name):
                    errors.append(
                        f"Step {step_idx}: output '{name or '(blank)'}' must be a valid Python identifier."
                    )
                elif name in seen:
                    errors.append(f"Step {step_idx}: output '{name}' is duplicated.")
                seen.add(name)
        return errors

    def add_builder_step(self, custom_sym=None):
        try:
            return self._add_builder_step_impl(custom_sym)
        except Exception as exc:
            self._report_workflow_error("Add Node failed", exc)
            return None

    def _add_builder_step_impl(self, custom_sym=None):
        """Add a function/capability as a node in the pipeline graph.

        This intentionally bypasses the old Visual Steps / table-card builder.
        The graph is the composer now; wf_builder_steps is kept only as the
        lightweight backing list used by codegen/save paths.
        """
        import copy

        if isinstance(custom_sym, bool):
            custom_sym = None

        if custom_sym is not None:
            sym = copy.deepcopy(custom_sym)
        else:
            selected = self.wf_build_func_box.currentData()
            if isinstance(selected, dict):
                sym = copy.deepcopy(selected)
            elif selected is None:
                self._report_workflow_builder_event("No function selected for Add Node.")
                return None
            else:
                try:
                    idx = int(selected)
                except Exception:
                    self._report_workflow_builder_event("Selected function is not a valid node candidate.")
                    return None
                if idx < 0 or idx >= len(getattr(self, "all_discovered_symbols", []) or []):
                    self._report_workflow_builder_event("Selected function index is stale. Refreshing function filter.")
                    self.filter_discovered_symbols(
                        self.wf_build_func_filter.text() if hasattr(self, "wf_build_func_filter") else "")
                    return None
                sym = copy.deepcopy(self.all_discovered_symbols[idx])

        if sym.get("kind") == "class":
            params = self._extract_init_params(sym.get("source", ""))
        else:
            params = sym.get("params", []) or []

        outputs = self._normalized_builder_outputs(sym)

        file_path_lower = (sym.get("file_path", "") or "").lower()
        if "maya" in file_path_lower:
            dcc_tag = "[MAYA]"
        elif "unreal" in file_path_lower:
            dcc_tag = "[UNREAL]"
        elif "blender" in file_path_lower:
            dcc_tag = "[BLENDER]"
        elif "substance" in file_path_lower:
            dcc_tag = "[SUBSTANCE]"
        elif "unity" in file_path_lower:
            dcc_tag = "[UNITY]"
        elif "motionbuilder" in file_path_lower or "mobu" in file_path_lower:
            dcc_tag = "[MOTIONBUILDER]"
        else:
            dcc_tag = "[GENERAL]"

        step_data = {
            "widget": None,
            "symbol": sym,
            "params": params,
            "outputs": outputs,
            "table": None,
            "outputs_table": None,
            "header_lbl": None,
            "dcc_tag": dcc_tag,
            "literal_values": {},
        }

        self.wf_builder_steps.append(step_data)
        self._sync_builder_step_to_graph(step_data)
        self.update_builder_code_preview()

        try:
            self._report_workflow_builder_event(f"Added node: {sym.get('name', 'unnamed')}")
        except Exception:
            pass
        return step_data

    def update_step_connections_list(self, step_num, conn_list):
        conn_list.clear()

        if step_num < 1 or step_num - 1 >= len(self.wf_builder_steps):
            return
        step = self.wf_builder_steps[step_num - 1]
        params_table = step["table"]

        incoming = []
        for r in range(params_table.rowCount()):
            param_name_item = params_table.item(r, 0)
            cell_widget = params_table.cellWidget(r, 1)
            if param_name_item and cell_widget:
                p_name = param_name_item.text()
                conn_combo = cell_widget.findChild(QComboBox)
                conn_check = cell_widget.findChild(QCheckBox)

                if conn_check and conn_check.isChecked():
                    p_val = self._builder_combo_connection_value(conn_combo)
                    if p_val.startswith("$step"):
                        ref = p_val[len("$step"):].strip()
                        if "." in ref:
                            prev_step_num, out_var = ref.split(".", 1)
                            incoming.append(
                                f"[Incoming] Parameter '{p_name}' <- Step {prev_step_num} -> {out_var}"
                            )
                        else:
                            prev_step_num = ref
                            incoming.append(
                                f"[Incoming] Parameter '{p_name}' <- Step {prev_step_num} -> {out_var}"
                            )

        if incoming:
            for item in incoming:
                conn_list.addItem(item)
        else:
            conn_list.addItem(
                "No incoming connections (all parameters use literal values)."
            )

        outgoing = []
        for idx, other_step in enumerate(self.wf_builder_steps, start=1):
            if idx <= step_num:
                continue
            other_table = other_step["table"]
            other_sym = other_step["symbol"]

            for r in range(other_table.rowCount()):
                param_name_item = other_table.item(r, 0)
                cell_widget = other_table.cellWidget(r, 1)
                if param_name_item and cell_widget:
                    p_name = param_name_item.text()
                    conn_combo = cell_widget.findChild(QComboBox)
                    conn_check = cell_widget.findChild(QCheckBox)

                    if conn_check and conn_check.isChecked():
                        p_val = self._builder_combo_connection_value(conn_combo)
                        if p_val == f"$step{step_num}" or p_val.startswith(
                                f"$step{step_num}."
                        ):
                            ref = p_val[len("$step"):].strip()
                            out_var = ref.split(".", 1)[1] if "." in ref else "result"
                            outgoing.append(
                                f"[Outgoing] Output '{out_var}' -> Step {idx} ({other_sym.get('name')}) Parameter '{p_name}'"
                            )

        if outgoing:
            conn_list.addItem("")
            for item in outgoing:
                conn_list.addItem(item)
        else:
            conn_list.addItem("")
            conn_list.addItem(
                "No outgoing connections (no subsequent steps link to this output)."
            )

    def remove_builder_step(self, step_widget):
        target_idx = -1
        for idx, step in enumerate(self.wf_builder_steps):
            if step["widget"] == step_widget:
                target_idx = idx
                break

        if target_idx >= 0:
            connection_records = self._builder_connection_records()
            step = self.wf_builder_steps.pop(target_idx)
            step["widget"].setParent(None)
            step["widget"].deleteLater()
            self._renumber_builder_steps()
            self._restore_builder_connection_records(connection_records)
            for idx in range(1, len(self.wf_builder_steps) + 1):
                self._refresh_builder_output_consumers(idx)

            self._rebuild_pipeline_graph_from_steps()
            # Update code preview
            self.update_builder_code_preview()

    def move_builder_step(self, step_widget, direction):
        current_idx = self._builder_step_index_for_widget(step_widget) - 1
        if current_idx < 0:
            return
        new_idx = current_idx + direction
        if new_idx < 0 or new_idx >= len(self.wf_builder_steps):
            return

        connection_records = self._builder_connection_records()
        step = self.wf_builder_steps.pop(current_idx)
        self.wf_builder_steps.insert(new_idx, step)

        self.wf_steps_layout.removeWidget(step["widget"])
        self.wf_steps_layout.insertWidget(new_idx, step["widget"])

        self._renumber_builder_steps()
        self._restore_builder_connection_records(connection_records)
        for idx in range(1, len(self.wf_builder_steps) + 1):
            self._refresh_builder_output_consumers(idx)
        self._rebuild_pipeline_graph_from_steps()
        self.update_builder_code_preview()

    def update_builder_code_preview(self, force: bool = False):
        wf_name = getattr(self, "wf_build_name", None)
        if not wf_name:
            return
        if getattr(self, "_workflow_python_manually_edited", False) and not force:
            return
        name_str = wf_name.text().strip() or "unnamed_workflow"
        goal_str = self.wf_build_goal.text().strip()
        host_str = "cross_dcc"

        # Prefer the node graph as the source of truth when it exists.
        # This reconnects live graph edits, graph order, links, and attribute literals
        # directly to the Python Code tab. The older table-based generator remains
        # below as a fallback for builds without the graph widgets.
        view = getattr(self, "wf_node_view", None)
        if view is not None:
            try:
                from tech_connector.services.workflow_codegen_service import generate_pipeline_code_from_graph
                composed_code = generate_pipeline_code_from_graph(
                    name_str,
                    goal_str,
                    getattr(self, "wf_builder_steps", []) or [],
                    view=view,
                )
                self._last_workflow_generated_code = composed_code
                if hasattr(self, "wf_builder_code_edit"):
                    cursor = self.wf_builder_code_edit.textCursor()
                    self._updating_workflow_python_from_graph = True
                    self.wf_builder_code_edit.blockSignals(True)
                    self.wf_builder_code_edit.setPlainText(composed_code)
                    self.wf_builder_code_edit.setTextCursor(cursor)
                    self.wf_builder_code_edit.blockSignals(False)
                    self._updating_workflow_python_from_graph = False
                    self._workflow_python_manually_edited = False
                    self._set_pipeline_python_warning("")
                return
            except Exception as exc:
                try:
                    self._report_workflow_builder_event(f"Graph code generation fell back to table builder: {exc}")
                except Exception:
                    pass

        roots = self.project_roots() if hasattr(self, "project_roots") else []
        project_root = Path(roots[0]) if roots else Path(".")

        lines = []
        lines.append(f'"""Generated pipeline: {name_str}')
        if goal_str:
            lines.append(f"Goal: {goal_str}")
        lines.append('"""\n')
        lines.append("import sys")
        lines.append("import traceback\n")

        func_args = []
        step_calls = []

        for idx, step in enumerate(self.wf_builder_steps, start=1):
            sym = step["symbol"]
            params_table = step["table"]

            file_path = Path(sym.get("file_path", ""))
            try:
                rel_path = None
                for root in self.all_roots():
                    try:
                        rel_path = file_path.relative_to(Path(root))
                        break
                    except ValueError:
                        pass
                if not rel_path:
                    rel_path = file_path.relative_to(project_root)
                module_dotted = ".".join(rel_path.with_suffix("").parts)
            except Exception:
                module_dotted = file_path.stem

            func_name = sym.get("name", "unnamed")
            kind = sym.get("kind", "function")

            arg_mappings = []

            for r in range(params_table.rowCount()):
                param_name_item = params_table.item(r, 0)
                cell_widget = params_table.cellWidget(r, 1)

                if param_name_item and cell_widget:
                    p_name = param_name_item.text()

                    val_edit = cell_widget.findChild(QLineEdit)
                    conn_combo = cell_widget.findChild(QComboBox)
                    conn_check = cell_widget.findChild(QCheckBox)

                    if conn_check and conn_check.isChecked():
                        p_val = self._builder_combo_connection_value(conn_combo)
                    else:
                        p_val = val_edit.text().strip() if val_edit else ""

                    if p_val.startswith("$step"):
                        # Format: $step{n} or $step{n}.{var_name}
                        ref = p_val[
                              len("$step"):
                              ].strip()  # e.g. "1" or "1.body_joint_map"
                        arg_mappings.append(
                            f"{p_name}={self._builder_step_ref_expr(ref)}"
                        )
                    else:
                        wrapper_arg_name = f"step{idx}_{p_name}"
                        try:
                            import ast

                            parsed_val = ast.literal_eval(p_val) if p_val else None
                        except Exception:
                            parsed_val = p_val if p_val else None

                        default_repr = (
                            repr(parsed_val) if parsed_val is not None else "None"
                        )
                        func_args.append(f"{wrapper_arg_name}={default_repr}")
                        arg_mappings.append(f"{p_name}={wrapper_arg_name}")

            step_calls.append((idx, module_dotted, func_name, kind, arg_mappings))

        from tech_connector.services.workflow_service import GITHUB_INGEST_FUNCTION_SUFFIX, slugify

        composed_func_name = f"{slugify(name_str)}{GITHUB_INGEST_FUNCTION_SUFFIX}"

        args_str = ", ".join(func_args)
        lines.append(f"def {composed_func_name}({args_str}):")
        lines.append("    results = {}")

        for idx, mod_path, name, kind, arg_mappings in step_calls:
            lines.append(f"    # Step {idx}: {mod_path}.{name} ({kind})")
            lines.append(f"    try:")
            lines.append(f"        import {mod_path}")
            lines.append(f"        import importlib")
            lines.append(f"        importlib.reload({mod_path})")

            lines.append(f"        target = getattr({mod_path}, '{name}')")

            args_mapping_str = ", ".join(arg_mappings)
            if kind == "class":
                lines.append(f"        # Instantiate class")
                lines.append(f"        step{idx}_result = target({args_mapping_str})")
            else:
                lines.append(f"        step{idx}_result = target({args_mapping_str})")

            # Unpack tuple results into named output dict for downstream steps
            step_sym = self.wf_builder_steps[idx - 1]["symbol"]
            step_outputs = self._normalized_builder_outputs(step_sym)
            if len(step_outputs) > 1:
                out_names = [o["name"] for o in step_outputs]
                unpack_str = ", ".join(out_names)
                lines.append(f"        # Unpack outputs: {unpack_str}")
                lines.append(f"        try:")
                lines.append(
                    f"            ({unpack_str},) = (step{idx}_result if isinstance(step{idx}_result, (list, tuple)) else [step{idx}_result])"
                )
                lines.append(
                    f"            step{idx}_outputs = {{{', '.join(repr(n) + ': ' + n for n in out_names)}}}"
                )
                lines.append(f"        except (TypeError, ValueError):")
                lines.append(
                    f"            step{idx}_outputs = {{'result': step{idx}_result}}"
                )
            else:
                out_name = step_outputs[0]["name"] if step_outputs else "result"
                lines.append(
                    f"        step{idx}_outputs = {{'{out_name}': step{idx}_result}}"
                )

            lines.append(f"        results['step{idx}'] = step{idx}_result")
            lines.append(f"    except Exception as e:")
            lines.append(f"        print(f'Step {idx} failed: {{e}}')")
            lines.append(f"        traceback.print_exc()")
            lines.append(f"        raise e\n")

        if step_calls:
            lines.append(f"    return results['step{len(step_calls)}']")
        else:
            lines.append("    return None")

        composed_code = "\n".join(lines)
        self._last_workflow_generated_code = composed_code
        if hasattr(self, "wf_builder_code_edit"):
            self._updating_workflow_python_from_graph = True
            self.wf_builder_code_edit.blockSignals(True)
            self.wf_builder_code_edit.setPlainText(composed_code)
            self.wf_builder_code_edit.blockSignals(False)
            self._updating_workflow_python_from_graph = False
            self._workflow_python_manually_edited = False

    def _save_pipeline_direct_fallback(self, project_root, composed_code, goal, slots, workflow_links, selected_symbols, host):
        """Last-resort save path so the builder always writes a visible pipeline."""
        import ast
        import json
        from pathlib import Path

        root = Path(project_root).expanduser().resolve()
        name_text = self.wf_build_name.text().strip() if hasattr(self, "wf_build_name") else "pipeline"
        slug = self._pipeline_safe_slug(name_text, "pipeline")
        function_name = self._pipeline_function_name_from_code(composed_code, slug)
        save_host = (host or self._infer_pipeline_host_from_builder() or "cross_dcc").lower()
        workflows_dir = root / "workflows" / save_host
        workflows_dir.mkdir(parents=True, exist_ok=True)
        py_path = workflows_dir / f"{slug}.py"
        manifest_path = workflows_dir / f"{slug}.workflow.json"
        py_path.write_text(composed_code or "", encoding="utf-8")
        manifest = {
            "host": save_host,
            "function": function_name,
            "module": "",
            "code_path": str(py_path),
            "goal": goal or "",
            "slots": slots or {},
            "workflow_links": workflow_links or [],
            "selected_capabilities": selected_symbols or [],
            "selected_items": selected_symbols or [],
            "naming": {"original_function": function_name, "slug": slug},
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        class SavedFallback:
            pass
        saved = SavedFallback()
        saved.manifest_path = manifest_path
        saved.module_path = py_path
        saved.test_path = root / "tests" / f"test_workflow_{save_host}_{slug}.py"
        saved.function_path = function_name
        return saved

    def save_new_workflow(self):
        if not self._ensure_pipeline_composer_unlocked("Create or select a pipeline before saving."):
            return
        wf_name = self.wf_build_name.text().strip()
        wf_goal = self.wf_build_goal.text().strip()
        wf_host = self._infer_pipeline_host_from_builder() if hasattr(self, "_infer_pipeline_host_from_builder") else "cross_dcc"

        if not wf_name:
            QMessageBox.information(
                self, "Required Fields", "Please enter a pipeline name."
            )
            return
        if not self.wf_builder_steps:
            QMessageBox.information(
                self, "Required Fields", "Please add at least one step."
            )
            return

        output_errors = self._builder_output_validation_errors()
        if output_errors:
            QMessageBox.warning(
                self,
                "Invalid Outputs",
                "Fix these output definitions before saving:\n\n"
                + "\n".join(f"- {err}" for err in output_errors),
            )
            return

        data_flow_issues = self._refresh_pipeline_data_flow_warnings()
        if data_flow_issues:
            msg = (
                "Some node inputs do not have a literal value or incoming data connection.\n\n"
                + self._format_pipeline_data_flow_issues(data_flow_issues)
                + "\n\nNodes with these issues are highlighted in the graph. "
                "Save anyway only if these should remain exposed/defaulted pipeline inputs."
            )
            reply = QMessageBox.question(
                self,
                "Pipeline Data Flow Warning",
                msg,
                QMessageBox.Save | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Save:
                return

        # Validation checks
        empty_params = []
        for idx, step in enumerate(self.wf_builder_steps, start=1):
            sym = step["symbol"]
            params_table = step["table"]
            for r in range(params_table.rowCount()):
                param_name_item = params_table.item(r, 0)
                cell_widget = params_table.cellWidget(r, 1)
                if param_name_item and cell_widget:
                    val_edit = cell_widget.findChild(QLineEdit)
                    conn_combo = cell_widget.findChild(QComboBox)
                    conn_check = cell_widget.findChild(QCheckBox)

                    is_empty = False
                    if conn_check and conn_check.isChecked():
                        if not self._builder_combo_connection_value(conn_combo):
                            is_empty = True
                    else:
                        if val_edit and not val_edit.text().strip():
                            is_empty = True

                    if is_empty:
                        empty_params.append(
                            f"Step {idx} ({sym.get('name')}): {param_name_item.text()}"
                        )

        if empty_params and not data_flow_issues:
            msg = (
                    "The following parameters are unconfigured/empty:\n"
                    + "\n".join(f"- {p}" for p in empty_params)
                    + "\n\nDo you want to proceed with a default value of None for these parameters?"
            )
            reply = QMessageBox.question(
                self,
                "Undefined Parameters",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        roots = self.project_roots() if hasattr(self, "project_roots") else []
        if not roots:
            QMessageBox.information(
                self, "No Project", "Please load a project before saving pipelines."
            )
            return
        project_root = roots[0]

        # Preserve manual Python edits. If the user has not edited the script,
        # refresh it from the graph before saving.
        if not getattr(self, "_workflow_python_manually_edited", False):
            self.update_builder_code_preview(force=True)
        composed_code = self.wf_builder_code_edit.toPlainText() if hasattr(self, "wf_builder_code_edit") else getattr(self, "_last_workflow_generated_code", "")
        try:
            from tech_connector.services.workflow_service import extract_python_code

            cleaned_code = extract_python_code(composed_code)
            if cleaned_code != composed_code:
                composed_code = cleaned_code
                if hasattr(self, "wf_builder_code_edit"):
                    cursor = self.wf_builder_code_edit.textCursor()
                    self.wf_builder_code_edit.blockSignals(True)
                    self.wf_builder_code_edit.setPlainText(composed_code)
                    self.wf_builder_code_edit.setTextCursor(cursor)
                    self.wf_builder_code_edit.blockSignals(False)
                    self._workflow_python_manually_edited = True
        except Exception:
            pass
        try:
            compile(composed_code or "", "<ai_studio_pipeline>", "exec")
        except SyntaxError as exc:
            self._set_pipeline_python_warning(f"Python syntax error on line {exc.lineno}: {exc.msg}")
            QMessageBox.warning(
                self,
                "Python Syntax Error",
                f"The pipeline Python has a syntax error on line {exc.lineno}:\n\n{exc.msg}\n\nFix the Python tab before saving.",
            )
            self._report_workflow_builder_event(f"Python syntax error on line {exc.lineno}: {exc.msg}")
            return
        self._set_pipeline_python_warning("")

        # Re-compile slots and workflow links for the manifest
        slots = {}
        workflow_links = []
        selected_symbols = []

        for idx, step in enumerate(self.wf_builder_steps, start=1):
            sym = step["symbol"]
            params_table = step["table"]
            selected_symbols.append(sym)

            for r in range(params_table.rowCount()):
                param_name_item = params_table.item(r, 0)
                cell_widget = params_table.cellWidget(r, 1)

                if param_name_item and cell_widget:
                    p_name = param_name_item.text()
                    val_edit = cell_widget.findChild(QLineEdit)
                    conn_combo = cell_widget.findChild(QComboBox)
                    conn_check = cell_widget.findChild(QCheckBox)

                    if conn_check and conn_check.isChecked():
                        p_val = self._builder_combo_connection_value(conn_combo)
                    else:
                        p_val = val_edit.text().strip() if val_edit else ""

                    if p_val.startswith("$step"):
                        # Format: $step{n} or $step{n}.{var_name}
                        ref = p_val[len("$step"):].strip()
                        if "." in ref:
                            prev_step_num, out_var = ref.split(".", 1)
                            workflow_links.append(
                                f"step{prev_step_num}.{out_var} -> step{idx}.{p_name}"
                            )
                        else:
                            prev_step_num = ref
                            workflow_links.append(
                                f"step{prev_step_num}.result -> step{idx}.{p_name}"
                            )
                    else:
                        wrapper_arg_name = f"step{idx}_{p_name}"
                        try:
                            import ast

                            parsed_val = ast.literal_eval(p_val) if p_val else None
                        except Exception:
                            parsed_val = p_val if p_val else None
                        slots[wrapper_arg_name] = parsed_val

        try:
            from tech_connector.services.workflow_service import save_composed_workflow

            saved = save_composed_workflow(
                project_root=project_root,
                composed_code=composed_code,
                goal=wf_goal,
                slots_text="\n".join(f"{k}={v}" for k, v in slots.items()),
                workflow_links="\n".join(workflow_links),
                host=wf_host,
                selected_items=selected_symbols,
            )

            self.refresh_workflows_list()

            # Select the newly created workflow
            for i in range(self.workflows_list.count()):
                item = self.workflows_list.item(i)
                if item.data(Qt.UserRole) == str(saved.manifest_path):
                    self.workflows_list.setCurrentItem(item)
                    break

            self.wf_stack.setCurrentIndex(1)
            QMessageBox.information(
                self,
                "Pipeline Saved",
                f"Pipeline successfully saved and compiled!\n\nModule: {saved.module_path.name}\nManifest: {saved.manifest_path.name}",
            )
        except Exception as e:
            # Do not let the composer silently lose work if workflow_service rejects the generated code.
            # Save a direct manifest + .py file that refresh_workflows_list can see and run by path.
            try:
                saved = self._save_pipeline_direct_fallback(
                    project_root=project_root,
                    composed_code=composed_code,
                    goal=wf_goal,
                    slots=slots,
                    workflow_links=workflow_links,
                    selected_symbols=selected_symbols,
                    host=wf_host,
                )
                self.refresh_workflows_list()
                for i in range(self.workflows_list.count()):
                    item = self.workflows_list.item(i)
                    if item.data(Qt.UserRole) == str(saved.manifest_path):
                        self.workflows_list.setCurrentItem(item)
                        break
                self.wf_stack.setCurrentIndex(1)
                QMessageBox.warning(
                    self,
                    "Pipeline Saved With Fallback",
                    "The normal compiler failed, but the pipeline was still saved as a direct .py + manifest.\n\n"
                    f"Compiler error:\n{e}\n\n"
                    f"Module: {saved.module_path.name}\nManifest: {saved.manifest_path.name}",
                )
            except Exception as fallback_exc:
                QMessageBox.critical(
                    self,
                    "Compilation Error",
                    f"Failed to compile or save pipeline:\n{e}\n\nFallback save also failed:\n{fallback_exc}",
                )

    # ------------------------------------------------------------------
    # Pipeline attribute editor / export / primary-view workflow UX
    # ------------------------------------------------------------------
    def _pipeline_params_for_symbol(self, symbol: dict):
        if (symbol or {}).get("kind") == "class":
            try:
                return self._extract_init_params((symbol or {}).get("source", ""))
            except Exception:
                return []
        return (symbol or {}).get("params", []) or []

    def _pipeline_outputs_for_symbol(self, symbol: dict):
        try:
            return self._normalized_builder_outputs(symbol or {})
        except Exception:
            return (symbol or {}).get("outputs", []) or [
                {"name": "result", "annotation": (symbol or {}).get("return_annotation", "") or ""}]

    def _report_workflow_builder_event(self, message: str):
        text = str(message or "")
        try:
            if hasattr(self, "wf_test_status"):
                self.wf_test_status.setText(text)
        except Exception:
            pass
        try:
            if hasattr(self, "append") and text:
                self.append(f"\n[Workflow Builder] {text}\n")
        except Exception:
            pass

    def _report_pipeline_prompt_progress(self, event: dict):
        data = dict(event or {})
        status = str(data.get("status") or "running").upper()
        label = str(data.get("label") or data.get("state") or "Pipeline planning")
        details = dict(data.get("details") or {})
        facts = []
        for key in (
            "route",
            "host",
            "intent",
            "action_count",
            "node_count",
            "data_link_count",
            "flow_link_count",
            "total_ms",
        ):
            value = details.get(key)
            if value is not None and value != "":
                facts.append(f"{key.replace('_', ' ')}={value}")
        suffix = f" ({', '.join(facts)})" if facts else ""
        self._report_workflow_builder_event(f"[{status}] {label}{suffix}")
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()
        except Exception:
            pass

    def _format_pipeline_data_flow_issues(self, issues, limit: int = 10) -> str:
        shown = []
        for issue in (issues or [])[:limit]:
            shown.append(f"- {issue.get('message') or 'Data-flow issue'}")
        if issues and len(issues) > limit:
            shown.append(f"- {len(issues) - limit} more issue(s)")
        return "\n".join(shown)

    def _refresh_pipeline_data_flow_warnings(self):
        view = getattr(self, "wf_node_view", None)
        if view is None or not hasattr(view, "refresh_data_flow_warnings"):
            return []
        try:
            issues = view.refresh_data_flow_warnings()
        except Exception as exc:
            self._report_workflow_builder_event(f"Could not validate pipeline data flow: {exc}")
            return []
        if issues:
            self._report_workflow_builder_event(
                f"Pipeline data flow needs attention: {len(issues)} input(s) need a value or connection."
            )
        elif hasattr(self, "wf_test_status"):
            try:
                current = self.wf_test_status.text()
                if "data flow" in current.lower() or "needs attention" in current.lower():
                    self.wf_test_status.setText("Pipeline data flow looks connected.")
            except Exception:
                pass
        return issues

    def _set_pipeline_python_warning(self, message: str = ""):
        editor = getattr(self, "wf_builder_code_edit", None)
        if editor is None:
            return
        warning = bool(str(message or "").strip())
        border = "#ff4d6d" if warning else "#5bd000"
        editor.setStyleSheet(f"""
            QPlainTextEdit, QTextEdit {{
                background-color: #0b0f14;
                color: #d7dde5;
                border: 1px solid {border};
                border-radius: 4px;
            }}
        """)
        if warning:
            editor.setToolTip(message)
        else:
            editor.setToolTip("")

    def _handle_pipeline_graph_changed(self, *args, **kwargs):
        if getattr(self, "_syncing_workflow_python_to_graph", False):
            return
        self.update_builder_code_preview()
        self._refresh_pipeline_data_flow_warnings()

    def _handle_pipeline_node_deleted(self, node_ids):
        node_ids = set(node_ids or [])
        if not node_ids:
            return
        kept = []
        for step in getattr(self, "wf_builder_steps", []) or []:
            if step.get("graph_step_id") in node_ids:
                widget = step.get("widget")
                try:
                    if widget:
                        widget.setParent(None)
                        widget.deleteLater()
                except Exception:
                    pass
            else:
                kept.append(step)
        self.wf_builder_steps = kept
        self.update_builder_code_preview()
        self._refresh_pipeline_data_flow_warnings()

    def _schedule_workflow_python_to_graph_sync(self):
        if getattr(self, "_updating_workflow_python_from_graph", False):
            return
        self._workflow_python_manually_edited = True
        timer = getattr(self, "_workflow_python_parse_timer", None)
        if timer:
            timer.start(650)

    def sync_workflow_graph_from_python(self):
        """Best-effort Python -> graph sync.

        Generated Pipeline Python can round-trip back into graph nodes, plugs,
        literals, and links. Other Python falls back to the lightweight callable
        scanner so hand-written helpers can still add known functions.
        """
        if getattr(self, "_updating_workflow_python_from_graph", False):
            return
        editor = getattr(self, "wf_builder_code_edit", None)
        if editor is None:
            return
        code = editor.toPlainText()
        try:
            from tech_connector.services.workflow_service import extract_python_code

            cleaned_code = extract_python_code(code)
            if cleaned_code != code:
                cursor = editor.textCursor()
                editor.blockSignals(True)
                editor.setPlainText(cleaned_code)
                editor.setTextCursor(cursor)
                editor.blockSignals(False)
                code = cleaned_code
        except Exception:
            pass

        try:
            import ast
            tree = ast.parse(code or "")
        except Exception as exc:
            self._report_workflow_builder_event(f"Python parse waiting for valid code: {exc}")
            self._set_pipeline_python_warning(f"Python is not valid yet: {exc}")
            return
        self._set_pipeline_python_warning("")

        self._syncing_workflow_python_to_graph = True
        try:
            try:
                from tech_connector.services.workflow_python_graph_sync_service import parse_pipeline_python_to_graph

                parsed = parse_pipeline_python_to_graph(code)
            except Exception:
                parsed = None
            if parsed is not None and parsed.ok and parsed.steps:
                self._replace_pipeline_graph_from_parsed_python(parsed)
                return

            if not getattr(self, "all_discovered_symbols", None):
                self.all_discovered_symbols = getattr(self, "_cached_discovered_symbols", []) or []
                if not self.all_discovered_symbols:
                    self._ensure_pipeline_symbols_available_nonblocking()
                    self._report_workflow_builder_event("Python-to-graph sync is waiting for the background function list.")
                    return

            import_aliases = {}
            callable_aliases = {}
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        import_aliases[alias.asname or alias.name.split(".")[-1]] = alias.name
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        callable_aliases[
                            alias.asname or alias.name] = f"{module}.{alias.name}" if module else alias.name

            calls = []
            search_body = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    search_body.extend(node.body)
                    break
            if not search_body:
                search_body = tree.body

            for node in ast.walk(ast.Module(body=search_body, type_ignores=[])):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                call_name = ""
                function_path = ""
                if isinstance(func, ast.Name):
                    call_name = func.id
                    function_path = callable_aliases.get(call_name, call_name)
                elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    module = import_aliases.get(func.value.id, func.value.id)
                    call_name = func.attr
                    function_path = f"{module}.{func.attr}"
                if call_name and call_name not in {"getattr", "print", "len", "range", "isinstance", "Exception",
                                                   "RuntimeError"}:
                    calls.append((call_name, function_path))

            existing_keys = set()
            for step in getattr(self, "wf_builder_steps", []) or []:
                sym = step.get("symbol") or {}
                existing_keys.add((sym.get("name") or "", sym.get("function_path") or sym.get("module") or ""))

            def symbol_key(sym):
                return (sym.get("name") or "", sym.get("function_path") or sym.get("module") or "")

            added = 0
            for call_name, function_path in calls:
                match = None
                for sym in self.all_discovered_symbols:
                    sym_name = sym.get("name") or ""
                    sym_path = sym.get("function_path") or sym.get("module") or ""
                    if symbol_key(sym) in existing_keys:
                        continue
                    if sym_name == call_name or sym_path == function_path or sym_path.endswith(f".{call_name}"):
                        match = sym
                        break
                if match:
                    self.add_builder_step(custom_sym=match)
                    existing_keys.add(symbol_key(match))
                    added += 1
            if added:
                self._report_workflow_builder_event(f"Synced {added} Python callable(s) into the node graph.")
        finally:
            self._syncing_workflow_python_to_graph = False

    def _replace_pipeline_graph_from_parsed_python(self, parsed):
        import copy

        parsed_steps = list(getattr(parsed, "steps", []) or [])
        if not parsed_steps:
            return

        self.all_discovered_symbols = getattr(self, "all_discovered_symbols", None) or getattr(
            self, "_cached_discovered_symbols", []
        ) or []

        def _norm_path(value):
            return str(value or "").replace("\\", "/").lower()

        def _match_symbol(parsed_symbol: dict):
            parsed_name = parsed_symbol.get("name") or ""
            parsed_file = _norm_path(parsed_symbol.get("file_path"))
            parsed_path = parsed_symbol.get("function_path") or parsed_symbol.get("module") or ""
            for sym in self.all_discovered_symbols:
                sym_name = sym.get("name") or ""
                sym_file = _norm_path(sym.get("file_path"))
                sym_path = sym.get("function_path") or sym.get("module") or ""
                if parsed_file and sym_file and parsed_file == sym_file and sym_name == parsed_name:
                    return sym
                if parsed_path and sym_path and sym_path == parsed_path:
                    return sym
                if sym_name == parsed_name and (not parsed_file or not sym_file or parsed_file.endswith(sym_file) or sym_file.endswith(parsed_file)):
                    return sym
            return None

        self.wf_builder_steps = []
        self._rebuild_pipeline_graph_from_steps()

        previous_manual_state = getattr(self, "_workflow_python_manually_edited", False)
        self._workflow_python_manually_edited = True
        added_steps = []
        try:
            for parsed_step in parsed_steps:
                parsed_symbol = copy.deepcopy(parsed_step.get("symbol") or {})
                match = _match_symbol(parsed_symbol)
                symbol = copy.deepcopy(match) if isinstance(match, dict) else parsed_symbol
                if parsed_symbol.get("params"):
                    symbol["params"] = parsed_symbol.get("params")
                if parsed_symbol.get("outputs"):
                    symbol["outputs"] = parsed_symbol.get("outputs")
                if parsed_symbol.get("file_path"):
                    symbol["file_path"] = parsed_symbol.get("file_path")
                step_data = self.add_builder_step(custom_sym=symbol)
                if not step_data:
                    continue
                step_data["literal_values"] = copy.deepcopy(parsed_step.get("literal_values") or {})
                added_steps.append(step_data)
            self._apply_workflow_intent_links(
                added_steps,
                {
                    "data_links": getattr(parsed, "data_links", []) or [],
                    "flow_links": getattr(parsed, "flow_links", []) or [],
                },
            )
            view = getattr(self, "wf_node_view", None)
            if view is not None:
                for step in added_steps:
                    if hasattr(view, "refresh_node_literals"):
                        view.refresh_node_literals(step)
            self._workflow_python_manually_edited = previous_manual_state
            self._report_workflow_builder_event(
                f"Synced Pipeline Python into graph: {len(added_steps)} node(s), "
                f"{len(getattr(parsed, 'data_links', []) or [])} data link(s), "
                f"{len(getattr(parsed, 'flow_links', []) or [])} flow link(s)."
            )
        except Exception:
            self._workflow_python_manually_edited = previous_manual_state
            raise

    def _sync_builder_step_to_graph(self, step_data: dict):
        view = getattr(self, "wf_node_view", None)
        if not view or not step_data or step_data.get("graph_step_id"):
            return
        try:
            symbol = step_data.get("symbol") or {}
            params = step_data.get("params") or self._pipeline_params_for_symbol(symbol)
            outputs = step_data.get("outputs") or self._pipeline_outputs_for_symbol(symbol)
            view.add_pipeline_step(step_data, params, outputs)
        except Exception as exc:
            try:
                self._report_workflow_builder_event(f"Could not add step to node graph: {exc}")
            except Exception:
                pass

    def _rebuild_pipeline_graph_from_steps(self):
        view = getattr(self, "wf_node_view", None)
        if not view:
            return
        try:
            scene = getattr(view, "scene_obj", None)
            if scene is not None:
                scene.clear()
            view.nodes.clear()
            view.node_items.clear()
            view.links.clear()
            view.link_items.clear()
            view.pending_port = None
            view.temp_link = None
            from PySide6.QtGui import QColor
            from PySide6.QtWidgets import QGraphicsSimpleTextItem
            view.empty = QGraphicsSimpleTextItem(
                "Add pipeline steps. Select a node to edit attributes. Select connections and press Delete to remove links."
            )
            view.empty.setBrush(QColor("#8fb9c9"))
            view.empty.setPos(80, 80)
            view.scene_obj.addItem(view.empty)
            for step in getattr(self, "wf_builder_steps", []) or []:
                step.pop("graph_step_id", None)
                self._sync_builder_step_to_graph(step)
            view.graphChanged.emit()
            view.orderChanged.emit(view.execution_order())
        except Exception as exc:
            try:
                self._report_workflow_builder_event(f"Could not rebuild node graph: {exc}")
            except Exception:
                pass

    def _wire_pipeline_attribute_editor_once(self):
        if getattr(self, "_pipeline_attribute_editor_wired", False):
            return
        view = getattr(self, "wf_node_view", None)
        editor = getattr(self, "wf_attribute_editor", None)
        if not view or not editor:
            return
        self._pipeline_attribute_editor_wired = True
        try:
            view.nodeSelected.connect(editor.set_node)
        except Exception:
            pass
        try:
            editor.literalChanged.connect(self._handle_pipeline_attribute_literal_changed)
        except Exception:
            pass
        try:
            editor.openFileRequested.connect(self._handle_pipeline_attribute_open_file)
        except Exception:
            pass

    def _handle_pipeline_attribute_literal_changed(self, payload: dict):
        step_data = payload.get("step_data") or {}
        view = getattr(self, "wf_node_view", None)
        if view and hasattr(view, "refresh_node_literals"):
            view.refresh_node_literals(step_data)
        try:
            self._report_workflow_builder_event(
                f"Set node attribute: {payload.get('input')} = {payload.get('value')!r}"
            )
        except Exception:
            pass
        self.update_builder_code_preview()

    def _handle_pipeline_attribute_open_file(self, payload):
        if isinstance(payload, dict):
            raw_path = str(payload.get("path") or "").strip()
            try:
                line_number = max(1, int(payload.get("line") or 1))
            except Exception:
                line_number = 1
        else:
            raw_path = str(payload or "").strip()
            line_number = 1
        if not raw_path:
            return
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            roots = [
                getattr(self, "project_root", ""),
                getattr(self, "current_project_root", ""),
                getattr(self, "current_project_path", ""),
                getattr(self, "project_path", ""),
            ]
            for root in roots:
                if not root:
                    continue
                resolved = Path(str(root)) / raw_path
                if resolved.exists():
                    candidate = resolved
                    break
        if not candidate.exists():
            try:
                self._report_workflow_builder_event(f"Node source file not found: {raw_path}")
            except Exception:
                pass
            return
        try:
            self._open_or_focus_file_at_line(str(candidate), line_number)
            return
        except Exception as exc:
            if hasattr(self, "open_code_file"):
                self.open_code_file(str(candidate))
                return
            try:
                self._report_workflow_builder_event(f"Could not open node source file: {exc}")
            except Exception:
                pass

    def open_pipeline_for_edit(self, pipeline_name: str):
        """Switch between created pipelines without opening a separate details page.

        This keeps the user in the primary composer: Node Graph or Python.
        Existing loading behavior can still populate fields before this method.
        """
        try:
            self.start_new_workflow_builder()
        except Exception:
            pass
        try:
            if hasattr(self, "wf_build_name"):
                self.wf_build_name.setText(pipeline_name)
        except Exception:
            pass
        try:
            self.tabs.setCurrentWidget(self.pipelines_tab)
        except Exception:
            pass
        self.update_builder_code_preview()

    def _pipeline_default_export_path(self) -> str:
        import re

        name = self._pipeline_widget_text(getattr(self, "wf_build_name", None), "workflow")
        fn = re.sub(r"[^A-Za-z0-9_]+", "_", str(name or "workflow")).strip("_").lower()
        fn = re.sub(r"_+", "_", fn) or "workflow"
        if fn[0].isdigit():
            fn = f"workflow_{fn}"
        try:
            root = self.active_project_root_path()
        except Exception:
            root = ""
        if root:
            from pathlib import Path
            return str(Path(root) / "generated_pipelines" / f"{fn}.py")
        return f"{fn}.py"

    def export_pipeline_python_file(self):
        """Export generated pipeline Python to a user-selected location."""
        self.update_builder_code_preview()
        code = getattr(self, "_last_workflow_generated_code", "") or ""
        if not code:
            try:
                self._report_workflow_builder_event("No generated Python code to export yet.")
            except Exception:
                pass
            return None

        try:
            from PySide6.QtWidgets import QFileDialog, QMessageBox
            default_path = self._pipeline_default_export_path()
            path, _filter = QFileDialog.getSaveFileName(
                self,
                "Export Pipeline Python",
                default_path,
                "Python Files (*.py);;All Files (*)",
            )
            if not path:
                return None
            from pathlib import Path
            out_path = Path(path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(code, encoding="utf-8")
            self._report_workflow_builder_event(f"Exported pipeline Python:\n{out_path}")
            return str(out_path)
        except Exception as exc:
            try:
                QMessageBox.warning(self, "Export failed", str(exc))
            except Exception:
                pass
            self._report_workflow_builder_event(f"Export failed: {exc}")
            return None

    def show_workflow_details(self, *args, **kwargs):
        """Deprecated details page: keep users in the primary pipeline editor."""
        self._report_workflow_builder_event("Details view is deprecated. Use Node Graph or Python.")
        try:
            if hasattr(self, "wf_builder_tabs"):
                self.wf_builder_tabs.setCurrentIndex(0)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Hard fix: fullscreen button placement + editor find/use hotkeys
    # ------------------------------------------------------------------


    def _find_matches_in_editor(self, query=None):
        editor = self._current_editor_widget()
        query = query if query is not None else self.editor_find.text()
        query = (query or "").strip()
        self._editor_find_matches = []
        self._editor_find_index = -1
        self._editor_find_query = query
        if editor is None or not query:
            return []

        text = editor.toPlainText()
        flags = re.IGNORECASE
        for m in re.finditer(re.escape(query), text, flags):
            self._editor_find_matches.append((m.start(), m.end()))

        return self._editor_find_matches

    def _select_editor_match(self, index):
        editor = self._current_editor_widget()
        matches = getattr(self, "_editor_find_matches", []) or []
        if editor is None or not matches:
            return
        index = index % len(matches)
        self._editor_find_index = index
        start, end = matches[index]
        cursor = editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        try:
            self.editor_status_label.setText(f"Find {index + 1}/{len(matches)}")
        except Exception:
            pass

    def find_in_current_file(self):
        """Find from current cursor position using the existing Find in File field."""
        editor = self._current_editor_widget()
        if editor is None:
            return
        query = self.editor_find.text().strip()
        if not query:
            query = self._selected_symbol_or_word()
            if query:
                self.editor_find.setText(query)
        if not query:
            return

        matches = self._find_matches_in_editor(query)
        if not matches:
            try:
                self.editor_status_label.setText("No matches")
            except Exception:
                pass
            return

        current_pos = editor.textCursor().position()
        target_index = 0
        for i, (start, _end) in enumerate(matches):
            if start >= current_pos:
                target_index = i
                break
        self._select_editor_match(target_index)

    def find_next_in_current_file(self):
        query = self.editor_find.text().strip()
        if not query:
            return self.find_in_current_file()
        if query != getattr(self, "_editor_find_query", None) or not getattr(self, "_editor_find_matches", None):
            self._find_matches_in_editor(query)
            self._editor_find_index = -1
        matches = getattr(self, "_editor_find_matches", []) or []
        if not matches:
            return
        self._select_editor_match(getattr(self, "_editor_find_index", -1) + 1)

    def find_previous_in_current_file(self):
        query = self.editor_find.text().strip()
        if not query:
            return self.find_in_current_file()
        if query != getattr(self, "_editor_find_query", None) or not getattr(self, "_editor_find_matches", None):
            self._find_matches_in_editor(query)
            self._editor_find_index = 0
        matches = getattr(self, "_editor_find_matches", []) or []
        if not matches:
            return
        self._select_editor_match(getattr(self, "_editor_find_index", 0) - 1)

    def find_in_current_file_from_shortcut(self):
        """Ctrl+F: populate Find field from selection/current word and jump from current line."""
        query = self._selected_symbol_or_word()
        if query:
            self.editor_find.setText(query)
        self.editor_find.setFocus()
        self.editor_find.selectAll()
        return self.find_in_current_file()

    def _uses_search_pattern(self, query):
        """Return an exact Python-identifier matcher for symbol-use search.

        Ctrl+B/Ctrl+N should find exact function/class/variable uses, not
        similarly named symbols. For example, `_get_joint` must not match
        `_get_joint_hierarchy`.
        """
        query = (query or "").strip()
        if not query:
            return None

        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", query):
            return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(query)}(?![A-Za-z0-9_])")

        return re.compile(re.escape(query), re.IGNORECASE)

    def _line_has_symbol_use(self, line, query):
        pattern = self._uses_search_pattern(query)
        if pattern is None:
            return False
        return bool(pattern.search(line))

    def _uses_popup(self, query, project_wide=False):
        dialog = QDialog(self)
        dialog.setWindowTitle("Find uses in project" if project_wide else "Find uses in file")
        dialog.resize(850, 450)
        layout = QVBoxLayout(dialog)
        row = QHBoxLayout()
        row.addWidget(QLabel("Find uses:"))
        search = QLineEdit()
        search.setText(query or "")
        row.addWidget(search, 1)
        run_btn = QPushButton("Search")
        row.addWidget(run_btn)
        layout.addLayout(row)
        results = QListWidget()
        results.setSelectionMode(QAbstractItemView.SingleSelection)
        results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(results, 1)

        def project_roots_for_search():
            try:
                roots = self.project_roots() if hasattr(self, "project_roots") else []
                return [Path(r) for r in roots if r]
            except Exception:
                return []

        def add_result(path, line_no, line):
            label_path = str(path) if path else "current file"
            item = QListWidgetItem(f"{label_path}:{line_no}: {line.strip()[:180]}")
            item.setData(Qt.UserRole, {"path": str(path) if path else "", "line": line_no})
            results.addItem(item)
            if results.count() > 0:
                results.setCurrentRow(0)
                results.setFocus()

        def run_search():
            results.clear()
            q = search.text().strip()
            if not q:
                search.setFocus()
                return
            max_results = 400
            count = 0

            if not project_wide:
                editor = self._current_editor_widget()
                if editor is None:
                    return
                for line_no, line in enumerate(editor.toPlainText().splitlines(), start=1):
                    if self._line_has_symbol_use(line, q):
                        add_result("", line_no, line)
                        count += 1
                        if count >= max_results:
                            QTimer.singleShot(0, results.setFocus)
                            return
                if results.count() > 0:
                    QTimer.singleShot(0, results.setFocus)
                return

            allowed = {".py", ".cpp", ".h", ".hpp", ".cs", ".json", ".yaml", ".yml", ".txt", ".md"}
            skip_names = {".git", "__pycache__", "Intermediate", "Saved", "DerivedDataCache", ".ai_studio"}
            started = time.monotonic()
            scanned_files = 0
            max_files = 2500
            time_budget_seconds = 4.0
            for root in project_roots_for_search():
                if not root.exists():
                    continue
                for file_path in root.rglob("*"):
                    if count >= max_results:
                        return
                    if scanned_files >= max_files or time.monotonic() - started >= time_budget_seconds:
                        QTimer.singleShot(0, results.setFocus if results.count() > 0 else search.setFocus)
                        return
                    if not file_path.is_file() or file_path.suffix.lower() not in allowed:
                        continue
                    if any(part in skip_names for part in file_path.parts):
                        continue
                    scanned_files += 1
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    for line_no, line in enumerate(content.splitlines(), start=1):
                        if self._line_has_symbol_use(line, q):
                            add_result(file_path, line_no, line)
                            count += 1
                            if count >= max_results:
                                QTimer.singleShot(0, results.setFocus)
                                return
            if results.count() > 0:
                QTimer.singleShot(0, results.setFocus)
            else:
                QTimer.singleShot(0, search.setFocus)

        def open_result(item):
            data = item.data(Qt.UserRole) or {}
            path = data.get("path") or ""
            line_no = int(data.get("line") or 1)
            if path:
                self._open_or_focus_file_at_line(path, line_no)
            else:
                editor = self._current_editor_widget()
                if editor is not None:
                    block = editor.document().findBlockByNumber(line_no - 1)
                    cursor = QTextCursor(block)
                    editor.setTextCursor(cursor)
                    editor.ensureCursorVisible()
            dialog.accept()

        run_btn.clicked.connect(run_search)
        search.returnPressed.connect(run_search)
        results.itemActivated.connect(open_result)
        run_search()
        QTimer.singleShot(0, results.setFocus if results.count() else search.setFocus)
        dialog.exec()

    def _should_hide_for_tab_focus(self, widget):
        workspace = getattr(self, "workspace_tabs", None)
        if widget is None or widget is workspace:
            return False
        try:
            if widget is getattr(self, "main_fullscreen_btn", None):
                return False
            if workspace is not None and workspace.isAncestorOf(widget):
                return False
            if widget.window() is not self:
                return False
        except Exception:
            return False

        name = (widget.objectName() or "").lower()
        cls = widget.__class__.__name__.lower()

        # Explicitly include top/header/menu/source/model/running sections.
        if any(token in name for token in (
                "header", "top", "menu", "source", "model", "status", "sidebar",
                "left", "project", "prompt", "input", "brand", "logo"
        )):
            return True
        if cls in {"qmenubar", "qtoolbar", "qstatusbar"}:
            return True
        return widget.parent() is self.centralWidget()

    def toggle_main_window_fullscreen(self):
        """Docked fullscreen means focus the active tab by hiding every surrounding panel/header."""
        workspace = getattr(self, "workspace_tabs", None)
        if workspace is None:
            return

        if not getattr(self, "_tab_focus_mode_active", False):
            self._tab_focus_mode_active = True
            self._tab_focus_hidden_widgets = []
            self._tab_focus_project_panel_was_visible = False
            try:
                left_panel = getattr(self, "left_panel", None)
                if left_panel is not None and left_panel.isVisible():
                    self._tab_focus_project_panel_was_visible = True
                    sizes = self.main_splitter.sizes() if hasattr(self, "main_splitter") else []
                    if sizes and sizes[0] > 40:
                        self._last_project_panel_width = sizes[0]
                    left_panel.setVisible(False)
                    if hasattr(self, "main_splitter"):
                        total = sum(sizes) if sizes else 1500
                        self.main_splitter.setSizes([0, max(700, total)])
                restore_btn = getattr(self, "project_restore_btn", None)
                if restore_btn is not None:
                    restore_btn.setVisible(not self._tab_focus_project_panel_was_visible)
            except Exception:
                pass
            for widget in self._main_layout_widgets_for_focus_mode():
                try:
                    if widget.isVisible():
                        self._tab_focus_hidden_widgets.append(widget)
                        widget.setVisible(False)
                except Exception:
                    pass
            try:
                workspace.show()
                workspace.raise_()
                workspace.setFocus()
            except Exception:
                pass
            try:
                self.main_fullscreen_btn.setChecked(True)
                self.main_fullscreen_btn.setText("Exit Focus")
            except Exception:
                pass
        else:
            self._tab_focus_mode_active = False
            for widget in getattr(self, "_tab_focus_hidden_widgets", []):
                try:
                    widget.setVisible(True)
                except Exception:
                    pass
            self._tab_focus_hidden_widgets = []
            try:
                left_panel = getattr(self, "left_panel", None)
                if left_panel is not None and getattr(self, "_tab_focus_project_panel_was_visible", False):
                    left_panel.setVisible(True)
                    width = getattr(self, "_last_project_panel_width", 360)
                    sizes = self.main_splitter.sizes() if hasattr(self, "main_splitter") else []
                    total = sum(sizes) if sizes else 1500
                    self.main_splitter.setSizes([width, max(700, total - width)])
                restore_btn = getattr(self, "project_restore_btn", None)
                if restore_btn is not None:
                    restore_btn.setVisible(left_panel is not None and not left_panel.isVisible())
            except Exception:
                pass
            self._tab_focus_project_panel_was_visible = False
            try:
                self.main_fullscreen_btn.setChecked(False)
                self.main_fullscreen_btn.setText("Full Screen")
            except Exception:
                pass


    def _jump_to_uses_result(self, result):
        path = result.get("path") or ""
        line_no = int(result.get("line") or 1)
        if path:
            self._open_or_focus_file_at_line(path, line_no)
            return
        editor = self._current_editor_widget()
        if editor is not None:
            block = editor.document().findBlockByNumber(max(0, line_no - 1))
            cursor = QTextCursor(block)
            editor.setTextCursor(cursor)
            editor.ensureCursorVisible()


    # ------------------------------------------------------------------
    # Geometry-based header hiding for tab focus mode
    # ------------------------------------------------------------------
    def _main_layout_widgets_for_focus_mode(self):
        """Hide all widgets outside/above the workspace tabs when focusing a tab.

        The prior object-name approach missed the top brand/source/model/running
        block because it is built as anonymous layout widgets. This version uses
        geometry relative to the workspace tab bar, so anything above the real
        workspace tabs is hidden even if it has no objectName.
        """
        workspace = getattr(self, "workspace_tabs", None)
        if workspace is None:
            return []

        widgets = []
        try:
            workspace_top = workspace.mapTo(self, workspace.rect().topLeft()).y()
        except Exception:
            workspace_top = 999999

        def should_hide(widget):
            if widget is None or widget is workspace:
                return False
            try:
                if widget is getattr(self, "main_fullscreen_btn", None):
                    return False
                if workspace.isAncestorOf(widget):
                    return False
                if widget.window() is not self:
                    return False
                if not widget.isVisible():
                    return False

                geo_top = widget.mapTo(self, widget.rect().topLeft()).y()
                geo_bottom = widget.mapTo(self, widget.rect().bottomLeft()).y()
                name = (widget.objectName() or "").lower()
                cls = widget.__class__.__name__.lower()

                # Hide anything vertically above the workspace tabs.
                if geo_bottom <= workspace_top:
                    return True

                # Hide direct left/sidebar/bottom/status siblings too, so tab gets the whole app body.
                if any(token in name for token in (
                        "header", "top", "brand", "logo", "source", "model", "running",
                        "status", "sidebar", "left", "project", "prompt", "input"
                )):
                    return True
                if cls in {"qmenubar", "qtoolbar", "qstatusbar"}:
                    return True

                central = self.centralWidget()
                if central and widget.parent() is central and widget is not workspace:
                    return True
            except Exception:
                return False
            return False

        for widget in self.findChildren(QWidget):
            if should_hide(widget) and widget not in widgets:
                widgets.append(widget)

        # Explicitly include menu/status/header-like top-level widgets.
        for getter in ("menuBar", "statusBar"):
            try:
                widget = getattr(self, getter)()
                if widget and widget.isVisible() and widget not in widgets:
                    widgets.append(widget)
            except Exception:
                pass

        # Hide direct siblings of workspace from the central layout.
        try:
            central = self.centralWidget()
            layout = central.layout() if central else None
            if layout is not None:
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    widget = item.widget() if item else None
                    if widget and widget is not workspace and widget.isVisible() and widget not in widgets:
                        widgets.append(widget)
        except Exception:
            pass

        return widgets

    # ------------------------------------------------------------------
    # Quick uses navigator: preview vs commit + already-open reuse
    # ------------------------------------------------------------------
    def _editor_syntax_for_path(self, path):
        suffix = Path(path).suffix.lower()
        if suffix == ".py":
            return "python"
        if suffix in {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"}:
            return "cpp"
        if suffix in {".cs"}:
            return "csharp"
        if suffix in {".json"}:
            return "json"
        if suffix in {".yaml", ".yml"}:
            return "yaml"
        if suffix in {".md"}:
            return "markdown"
        return "text"

    def _mark_editor_path_and_syntax(self, editor, path):
        if editor is None or not path:
            return
        try:
            editor.file_path = str(path)
            editor._file_path = str(path)
            editor.syntax_mode = self._editor_syntax_for_path(path)
        except Exception:
            pass
        # Try common syntax hooks if your editor exposes one.
        for method_name in ("set_syntax_mode", "setSyntaxMode", "apply_syntax_highlighting", "set_language"):
            fn = getattr(editor, method_name, None)
            if callable(fn):
                try:
                    fn(self._editor_syntax_for_path(path))
                    return
                except Exception:
                    pass


    def _focus_quick_uses_list(self, popup, list_widget, index=0):
        """Force the list to be keyboard-active with a highlighted current row."""
        try:
            if list_widget.count() <= 0:
                return
            index = max(0, min(index, list_widget.count() - 1))
            list_widget.setCurrentRow(index)
            item = list_widget.item(index)
            if item is not None:
                item.setSelected(True)
                list_widget.scrollToItem(item)
            list_widget.setFocus(Qt.OtherFocusReason)
            list_widget.activateWindow()
            popup.activateWindow()
            popup.raise_()
        except Exception:
            pass


    # ------------------------------------------------------------------
    # Editor toolbar space + hotkey-only actions + real quicknav open
    # ------------------------------------------------------------------
    def duplicate_current_line(self):
        """Ctrl+D duplicate current editor line."""
        editor = self._current_editor_widget()
        if editor is None:
            return
        cursor = editor.textCursor()
        block = cursor.block()
        text = block.text()
        cursor.movePosition(QTextCursor.EndOfBlock)
        cursor.insertText("\n" + text)

    def trim_trailing_spaces(self):
        """Ctrl+T trim trailing whitespace in current editor."""
        editor = self._current_editor_widget()
        if editor is None:
            return
        cursor = editor.textCursor()
        pos = cursor.position()
        text = editor.toPlainText()
        lines = [line.rstrip() for line in text.splitlines()]
        # Preserve final newline if present.
        new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        editor.setPlainText(new_text)
        cursor = editor.textCursor()
        cursor.setPosition(min(pos, len(new_text)))
        editor.setTextCursor(cursor)

    def _current_file_path_from_editor(self, editor=None):
        editor = editor or self._current_editor_widget()
        if editor is None:
            return ""
        for attr in ("file_path", "_file_path", "path"):
            value = getattr(editor, attr, None)
            if value:
                return str(value)
        for attr in ("current_file_path", "active_file_path", "editor_file_path"):
            value = getattr(self, attr, None)
            if value:
                return str(value)
        return ""

    def _find_open_editor_tab_for_path(self, path):
        path = str(Path(path).resolve()) if path else ""
        tabs = getattr(self, "editor_tabs", None)
        if tabs is None:
            return None, None
        for i in range(tabs.count()):
            widget = tabs.widget(i)
            candidates = [widget]
            try:
                candidates.extend(widget.findChildren(QPlainTextEdit))
                candidates.extend(widget.findChildren(QTextEdit))
            except Exception:
                pass
            for candidate in candidates:
                existing = (
                        getattr(candidate, "file_path", None)
                        or getattr(candidate, "_file_path", None)
                        or getattr(candidate, "path", None)
                )
                if existing:
                    try:
                        if str(Path(existing).resolve()) == path:
                            editor = candidate if isinstance(candidate,
                                                             (QPlainTextEdit, QTextEdit)) else candidate.findChild(
                                QPlainTextEdit) or candidate.findChild(QTextEdit)
                            return i, editor
                    except Exception:
                        pass
            try:
                tip = tabs.tabToolTip(i)
                if tip and str(Path(tip).resolve()) == path:
                    editor = widget if isinstance(widget, (QPlainTextEdit, QTextEdit)) else widget.findChild(
                        QPlainTextEdit) or widget.findChild(QTextEdit)
                    return i, editor
            except Exception:
                pass
        return None, None

    def _goto_line_in_editor(self, editor, line_number):
        if editor is None:
            return
        line_number = max(1, int(line_number or 1))
        block = editor.document().findBlockByNumber(line_number - 1)
        cursor = QTextCursor(block)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()

    def _apply_editor_syntax_for_path(self, editor, path):
        """Use the app's syntax setup if available; otherwise tag mode for existing highlighter hooks."""
        if editor is None or not path:
            return
        suffix = Path(path).suffix.lower()
        mode = {
            ".py": "python",
            ".pyw": "python",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".c": "cpp",
            ".h": "cpp",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".md": "markdown",
        }.get(suffix, "text")
        try:
            editor.file_path = str(path)
            editor._file_path = str(path)
            editor.syntax_mode = mode
        except Exception:
            pass
        for method_name in ("set_syntax_mode", "setSyntaxMode", "set_language", "apply_syntax_highlighting"):
            fn = getattr(editor, method_name, None)
            if callable(fn):
                try:
                    fn(mode)
                    return
                except Exception:
                    pass
        # App-level syntax hook if present.
        for method_name in ("apply_editor_syntax", "setup_editor_syntax", "apply_syntax_to_editor"):
            fn = getattr(self, method_name, None)
            if callable(fn):
                try:
                    fn(editor, str(path))
                    return
                except Exception:
                    pass

    def _open_file_in_real_editor(self, path, line_number=1, preview=False):
        """Open through the real app editor, reuse existing tab, and apply syntax.

        This avoids the blank/plain preview editor issue by preferring the app's
        existing file-opening methods, then tagging syntax/path metadata.
        """
        path = str(Path(path).resolve()) if path else ""
        if not path:
            editor = self._current_editor_widget()
            self._goto_line_in_editor(editor, line_number)
            return editor

        tabs = getattr(self, "editor_tabs", None)
        existing_index, existing_editor = self._find_open_editor_tab_for_path(path)
        if existing_editor is not None:
            if tabs is not None:
                tabs.setCurrentIndex(existing_index)
            self._apply_editor_syntax_for_path(existing_editor, path)
            self._goto_line_in_editor(existing_editor, line_number)
            return existing_editor

        # For committed opens, use app openers first.
        if not preview:
            for name in ("open_file_at_line", "open_file_in_editor", "open_file", "open_file_from_path"):
                fn = getattr(self, name, None)
                if callable(fn) and fn is not self._open_file_in_real_editor:
                    try:
                        try:
                            result = fn(path, line_number)
                        except TypeError:
                            result = fn(path)
                        editor = self._current_editor_widget()
                        if editor is not None:
                            self._apply_editor_syntax_for_path(editor, path)
                            self._goto_line_in_editor(editor, line_number)
                            return editor
                        if result is not None and isinstance(result, (QPlainTextEdit, QTextEdit)):
                            self._apply_editor_syntax_for_path(result, path)
                            self._goto_line_in_editor(result, line_number)
                            return result
                    except Exception:
                        pass

        # Replace old quick preview tab when previewing a new path.
        if preview and tabs is not None:
            old_index = getattr(self, "_quick_uses_preview_tab_index", None)
            old_path = getattr(self, "_quick_uses_preview_path", None)
            if old_index is not None and 0 <= old_index < tabs.count():
                try:
                    old_widget = tabs.widget(old_index)
                    if not getattr(old_widget, "_quick_uses_committed", False) and old_path and str(
                            Path(old_path).resolve()) != path:
                        tabs.removeTab(old_index)
                        old_widget.deleteLater()
                        self._quick_uses_preview_tab_index = None
                        self._quick_uses_preview_path = None
                except  Exception:
                    pass

        # Fallback editor creation, but still with real path metadata/syntax hooks.
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            editor = QPlainTextEdit()
            editor.setPlainText(text)
            editor.setLineWrapMode(QPlainTextEdit.NoWrap)
            self._apply_editor_syntax_for_path(editor, path)
            if tabs is not None:
                index = tabs.addTab(editor, Path(path).name)
                tabs.setTabToolTip(index, path)
                tabs.setCurrentIndex(index)
                if preview:
                    editor._quick_uses_preview = True
                    editor._quick_uses_committed = False
                    self._quick_uses_preview_tab_index = index
                    self._quick_uses_preview_path = path
                else:
                    editor._quick_uses_committed = True
            self.current_file_path = path
            try:
                self.file_path_label.setText(path)
            except Exception:
                pass
            self._goto_line_in_editor(editor, line_number)
            return editor
        except Exception as exc:
            QMessageBox.warning(self, "Open file failed", str(exc))
            return None

    def _open_or_focus_file_at_line(self, path, line_number, preview=False):
        return self._open_file_in_real_editor(path, line_number, preview=preview)

    def _commit_quick_uses_selection(self, popup, list_widget):
        item = list_widget.currentItem()
        if item is None:
            return
        result = item.data(Qt.UserRole) or {}
        path = result.get("path") or ""
        line_no = int(result.get("line") or 1)
        if path:
            try:
                if getattr(self, "_quick_uses_preview_path", None) and str(Path(path).resolve()) == str(
                        Path(self._quick_uses_preview_path).resolve()):
                    tabs = getattr(self, "editor_tabs", None)
                    idx = getattr(self, "_quick_uses_preview_tab_index", None)
                    if tabs is not None and idx is not None and 0 <= idx < tabs.count():
                        widget = tabs.widget(idx)
                        widget._quick_uses_committed = True
                        self._apply_editor_syntax_for_path(widget, path)
                        self._quick_uses_preview_tab_index = None
                        self._quick_uses_preview_path = None
            except Exception:
                pass
        self._open_file_in_real_editor(path, line_no, preview=False)
        popup.accept()


    # ------------------------------------------------------------------
    # Hard fix: editor toolbar layout + reliable Ctrl+B / Ctrl+N
    # ------------------------------------------------------------------
    def _take_widget_from_layout(self, layout, widget):
        if layout is None or widget is None:
            return
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item and item.widget() is widget:
                taken = layout.takeAt(i)
                return taken.widget()

    def _find_button_by_text(self, text):
        text = text.strip().lower()
        for btn in self.findChildren(QPushButton):
            try:
                if btn.text().strip().lower() == text:
                    return btn
            except Exception:
                pass
        return None


    # ------------------------------------------------------------------
    # Final hard fix: editor toolbar + reliable uses shortcuts
    # ------------------------------------------------------------------

    def _app_has_active_focus(self):
        try:
            app = QApplication.instance()
            active = app.activeWindow() if app is not None else None
            return active is self or (active is not None and active.window() is self)
        except Exception:
            return self.isActiveWindow()


    def _current_editor_widget(self):
        try:
            tabs = getattr(self, "editor_tabs", None)
            if tabs is not None:
                current = tabs.currentWidget()
                if isinstance(current, (QPlainTextEdit, QTextEdit)):
                    return current
                if current is not None:
                    child = current.findChild(QPlainTextEdit) or current.findChild(QTextEdit)
                    if child is not None:
                        return child
        except Exception:
            pass
        for attr in ("code_editor", "editor_text", "current_editor", "file_editor"):
            widget = getattr(self, attr, None)
            if isinstance(widget, (QPlainTextEdit, QTextEdit)):
                return widget
        focus = QApplication.focusWidget()
        if isinstance(focus, (QPlainTextEdit, QTextEdit)):
            return focus
        try:
            for widget in list(self.findChildren(QPlainTextEdit)) + list(self.findChildren(QTextEdit)):
                if widget.isVisible():
                    return widget
        except Exception:
            pass
        return None

    def _selected_symbol_or_word(self):
        editor = self._current_editor_widget()
        if editor is None:
            return ""
        cursor = editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n").strip()
        if selected:
            return selected
        cursor.select(QTextCursor.WordUnderCursor)
        word = cursor.selectedText().strip()
        if word:
            return word
        try:
            return self.editor_find.text().strip()
        except Exception:
            return ""

    def _collect_uses_results(self, query, project_wide=False, max_results=500):
        results = []
        query = (query or "").strip()
        if not query:
            return results
        if not project_wide:
            editor = self._current_editor_widget()
            if editor is None:
                return results
            for line_no, line in enumerate(editor.toPlainText().splitlines(), start=1):
                if self._line_has_symbol_use(line, query):
                    results.append({"path": "", "line": line_no, "text": line.strip()})
                    if len(results) >= max_results:
                        return results
            return results
        try:
            roots = self.project_roots() if hasattr(self, "project_roots") else []
        except Exception:
            roots = []
        if not roots:
            root = getattr(self, "current_project_root", None) or getattr(self, "project_root", None)
            roots = [root] if root else [Path.cwd()]
        allowed = {".py", ".pyw", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".cs", ".json", ".yaml", ".yml", ".txt",
                   ".md"}
        skip = {".git", "__pycache__", "Intermediate", "Saved", "DerivedDataCache", ".ai_studio"}
        started = time.monotonic()
        scanned_files = 0
        max_files = 2500
        time_budget_seconds = 4.0
        for root in [Path(r) for r in roots if r]:
            if not root.exists():
                continue
            for file_path in root.rglob("*"):
                if len(results) >= max_results:
                    return results
                if scanned_files >= max_files or time.monotonic() - started >= time_budget_seconds:
                    return results
                if not file_path.is_file() or file_path.suffix.lower() not in allowed:
                    continue
                if any(part in skip for part in file_path.parts):
                    continue
                scanned_files += 1
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for line_no, line in enumerate(content.splitlines(), start=1):
                    if self._line_has_symbol_use(line, query):
                        results.append({"path": str(file_path), "line": line_no, "text": line.strip()})
                        if len(results) >= max_results:
                            return results
        return results

    def _quick_uses_popup(self, query, project_wide=False):
        results = self._collect_uses_results(query, project_wide=project_wide)
        if not results:
            try:
                self.editor_status_label.setText(f"No uses found for {query}")
            except Exception:
                pass
            return
        popup = QDialog(self)
        popup.setWindowTitle("Project uses" if project_wide else "File uses")
        popup.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        popup.setFocusPolicy(Qt.StrongFocus)
        popup.resize(900, min(430, 92 + len(results) * 24))
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel(
            f"{'Project' if project_wide else 'File'} uses for: {query}    Up/Down preview - Enter keep/open - Esc close"))
        list_widget = QListWidget()
        list_widget.setFocusPolicy(Qt.StrongFocus)
        list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(list_widget, 1)
        for result in results:
            prefix = result.get("path") or "current file"
            item = QListWidgetItem(f"{prefix}:{result.get('line')}: {result.get('text', '')[:180]}")
            item.setData(Qt.UserRole, result)
            list_widget.addItem(item)
        state = {"index": 0}
        timer = QTimer(popup)
        timer.setInterval(3000)
        timer.setSingleShot(True)
        navigation_shortcuts = []

        def reset_timer():
            timer.start()

        def popup_has_focus():
            focus = QApplication.focusWidget()
            return focus is popup or (focus is not None and popup.isAncestorOf(focus))

        def close_if_inactive():
            if popup_has_focus():
                reset_timer()
                return
            popup.accept()

        timer.timeout.connect(close_if_inactive)

        def jump_result(index, preview=True):
            index %= len(results)
            state["index"] = index
            list_widget.setCurrentRow(index)
            item = list_widget.item(index)
            if item is not None:
                item.setSelected(True)
                list_widget.scrollToItem(item)
            result = results[index]
            self._open_or_focus_file_at_line(result.get("path") or "", int(result.get("line") or 1), preview=preview)
            list_widget.setFocus(Qt.OtherFocusReason)
            popup.raise_()
            reset_timer()

        def commit():
            item = list_widget.currentItem()
            if item is None:
                return
            result = item.data(Qt.UserRole) or {}
            self._open_or_focus_file_at_line(result.get("path") or "", int(result.get("line") or 1), preview=False)
            popup.accept()

        def cleanup_preview():
            idx = getattr(self, "_quick_uses_preview_tab_index", None)
            tabs = getattr(self, "editor_tabs", None)
            if tabs is not None and idx is not None and 0 <= idx < tabs.count():
                try:
                    widget = tabs.widget(idx)
                    if not getattr(widget, "_quick_uses_committed", False):
                        tabs.removeTab(idx)
                        widget.deleteLater()
                except Exception:
                    pass
            self._quick_uses_preview_tab_index = None
            self._quick_uses_preview_path = None

        def release_popup_focus():
            for shortcut in navigation_shortcuts:
                shortcut.setEnabled(False)
            cleanup_preview()

        popup.finished.connect(lambda _code: release_popup_focus())
        for target in (popup, list_widget):
            QShortcut(QKeySequence("Return"), target, activated=commit).setContext(Qt.WidgetWithChildrenShortcut)
            QShortcut(QKeySequence("Enter"), target, activated=commit).setContext(Qt.WidgetWithChildrenShortcut)
            QShortcut(QKeySequence("Esc"), target, activated=popup.reject).setContext(Qt.WidgetWithChildrenShortcut)

        def navigate_from_active_popup(direction):
            if not popup.isVisible():
                return
            jump_result(state["index"] + direction)

        for key, direction in ((Qt.Key_Down, 1), (Qt.Key_Up, -1)):
            shortcut = QShortcut(QKeySequence(key), popup)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(lambda step=direction: navigate_from_active_popup(step))
            navigation_shortcuts.append(shortcut)

        list_widget.itemActivated.connect(lambda _item: commit())
        list_widget.currentRowChanged.connect(lambda _row: reset_timer())
        try:
            popup.move(self.mapToGlobal(QPoint(120, 120)))
        except Exception:
            pass
        def focus_results_list():
            try:
                if list_widget.count() > 0:
                    list_widget.setCurrentRow(max(0, min(state["index"], list_widget.count() - 1)))
                    item = list_widget.currentItem()
                    if item is not None:
                        item.setSelected(True)
                        list_widget.scrollToItem(item)
                popup.raise_()
                popup.activateWindow()
                list_widget.setFocus(Qt.OtherFocusReason)
                list_widget.activateWindow()
            except Exception:
                pass

        popup.show()
        jump_result(0, preview=True)
        QTimer.singleShot(0, focus_results_list)
        QTimer.singleShot(50, focus_results_list)
        QTimer.singleShot(150, focus_results_list)
        reset_timer()
        popup._quick_uses_inactivity_timer = timer
        popup._quick_uses_navigation_shortcuts = tuple(navigation_shortcuts)
        self._quick_uses_popup_widget = popup
        return popup

    def find_uses_in_current_file_from_shortcut(self):
        query = self._selected_symbol_or_word()
        if not query:
            return
        self._quick_uses_popup(query, project_wide=False)

    def find_uses_in_project_from_shortcut(self):
        query = self._selected_symbol_or_word()
        if not query:
            return
        self._quick_uses_popup(query, project_wide=True)


    # ------------------------------------------------------------------
    # Editor toolbar final row alignment + Ctrl+S save
    # ------------------------------------------------------------------
    def finalize_editor_toolbar_layout(self):
        """Single-row editor toolbar.

        Row order:
        file path label | Find field | Find | Up | Down | Line | Go | stretch | Go to File Location

        Hidden but hotkey-active:
        Save File      -> Ctrl+S
        Duplicate Line -> Ctrl+D
        Trim Spaces    -> Ctrl+T
        """
        try:
            find_widget = getattr(self, "editor_find", None)
            if find_widget is None:
                return

            parent = find_widget.parentWidget()
            layout = parent.layout() if parent else None
            if layout is None:
                return

            file_label = getattr(self, "file_path_label", None)
            line_widget = getattr(self, "editor_line", None) or getattr(self, "line_edit", None)

            find_btn = self._find_button_by_text("find") if hasattr(self, "_find_button_by_text") else None
            go_btn = self._find_button_by_text("go") if hasattr(self, "_find_button_by_text") else None
            go_location_btn = self._find_button_by_text("go to file location") if hasattr(self,
                                                                                          "_find_button_by_text") else None
            save_btn = self._find_button_by_text("save file") if hasattr(self, "_find_button_by_text") else None
            dup_btn = self._find_button_by_text("duplicate line") if hasattr(self, "_find_button_by_text") else None
            trim_btn = self._find_button_by_text("trim spaces") if hasattr(self, "_find_button_by_text") else None
            comment_btn = self._find_button_by_text("comment") if hasattr(self, "_find_button_by_text") else None

            if not hasattr(self, "editor_find_prev_btn"):
                self.editor_find_prev_btn = QPushButton("Up")
                self.editor_find_prev_btn.setToolTip("Previous match in file")
                self.editor_find_prev_btn.clicked.connect(self.find_previous_in_current_file)

            if not hasattr(self, "editor_find_next_btn"):
                self.editor_find_next_btn = QPushButton("Down")
                self.editor_find_next_btn.setToolTip("Next match in file")
                self.editor_find_next_btn.clicked.connect(self.find_next_in_current_file)

            # Remove known widgets from current layout so we can rebuild order.
            for widget in (
                    file_label,
                    find_widget,
                    find_btn,
                    self.editor_find_prev_btn,
                    self.editor_find_next_btn,
                    line_widget,
                    go_btn,
                    go_location_btn,
                    save_btn,
                    dup_btn,
                    trim_btn,
                    comment_btn,
                    getattr(self, "editor_fullscreen_btn", None),
            ):
                try:
                    self._take_widget_from_layout(layout, widget)
                except Exception:
                    pass

            # Hotkey-only / hidden.
            for widget in (save_btn, dup_btn, trim_btn, getattr(self, "editor_fullscreen_btn", None)):
                try:
                    if widget:
                        widget.setVisible(False)
                except Exception:
                    pass

            if file_label:
                try:
                    file_label.setMinimumWidth(260)
                    file_label.setMaximumWidth(620)
                    file_label.setStyleSheet("padding-left: 2px;")
                except Exception:
                    pass
                layout.addWidget(file_label, 2)

            try:
                find_widget.setMinimumWidth(360)
                find_widget.setMaximumWidth(760)
            except Exception:
                pass
            layout.addWidget(find_widget, 3)

            if find_btn:
                layout.addWidget(find_btn)
            layout.addWidget(self.editor_find_prev_btn)
            layout.addWidget(self.editor_find_next_btn)

            if line_widget:
                try:
                    line_widget.setMaximumWidth(80)
                except Exception:
                    pass
                layout.addWidget(line_widget)

            if go_btn:
                layout.addWidget(go_btn)

            layout.addStretch(1)

            if go_location_btn:
                layout.addWidget(go_location_btn)

            # Comment can stay visible only if there is horizontal room, but place after file location.
            # If you want this hidden too, remove these two lines.
            if comment_btn:
                layout.addWidget(comment_btn)

        except Exception as exc:
            try:
                self.append(f"\n[Editor Toolbar] single-row layout failed: {exc}\n")
            except Exception:
                pass

    def install_editor_navigation_hotkeys(self):
        """Install reliable app-level shortcuts for editor actions."""
        try:
            if getattr(self, "_editor_navigation_hotkeys_installed_final", False):
                return
            self._editor_navigation_hotkeys_installed_final = True

            self.shortcut_save_file = QShortcut(QKeySequence("Ctrl+S"), self)
            self.shortcut_save_file.setContext(Qt.ApplicationShortcut)
            self.shortcut_save_file.activated.connect(self.save_current_file)

            self.shortcut_duplicate_line = QShortcut(QKeySequence("Ctrl+D"), self)
            self.shortcut_duplicate_line.setContext(Qt.ApplicationShortcut)
            self.shortcut_duplicate_line.activated.connect(self.duplicate_current_line)

            self.shortcut_trim_spaces = QShortcut(QKeySequence("Ctrl+T"), self)
            self.shortcut_trim_spaces.setContext(Qt.ApplicationShortcut)
            self.shortcut_trim_spaces.activated.connect(self.trim_trailing_spaces)

            self.shortcut_file_uses = QShortcut(QKeySequence("Ctrl+B"), self)
            self.shortcut_file_uses.setContext(Qt.ApplicationShortcut)
            self.shortcut_file_uses.activated.connect(self.find_uses_in_current_file_from_shortcut)

            self.shortcut_project_uses = QShortcut(QKeySequence("Ctrl+N"), self)
            self.shortcut_project_uses.setContext(Qt.ApplicationShortcut)
            self.shortcut_project_uses.activated.connect(self.find_uses_in_project_from_shortcut)

            self.shortcut_find_file = QShortcut(QKeySequence("Ctrl+F"), self)
            self.shortcut_find_file.setContext(Qt.ApplicationShortcut)
            self.shortcut_find_file.activated.connect(self.find_in_current_file_from_shortcut)

            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
        except Exception as exc:
            try:
                self.append(f"\n[Editor Hotkeys] install failed: {exc}\n")
            except Exception:
                pass

    def keyPressEvent(self, event):
        try:
            if event.modifiers() & Qt.ControlModifier:
                if event.key() == Qt.Key_Z:
                    if self._handle_global_undo_shortcut():
                        event.accept()
                        return
                if event.key() == Qt.Key_S:
                    self.save_current_file()
                    event.accept()
                    return
                if event.key() == Qt.Key_B:
                    self.find_uses_in_current_file_from_shortcut()
                    event.accept()
                    return
                if event.key() == Qt.Key_N:
                    self.find_uses_in_project_from_shortcut()
                    event.accept()
                    return
                if event.key() == Qt.Key_D:
                    self.duplicate_current_line()
                    event.accept()
                    return
                if event.key() == Qt.Key_T:
                    self.trim_trailing_spaces()
                    event.accept()
                    return
                if event.key() == Qt.Key_F:
                    self.find_in_current_file_from_shortcut()
                    event.accept()
                    return
        except Exception:
            pass
        try:
            super().keyPressEvent(event)
        except Exception:
            event.ignore()

    def _focus_is_inside_widget(self, focus, root) -> bool:
        if focus is None or root is None:
            return False
        if focus is root:
            return True
        try:
            return root.isAncestorOf(focus)
        except Exception:
            return False

    def _handle_global_undo_shortcut(self) -> bool:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return False

        node_view = getattr(self, "wf_node_view", None)
        if node_view is not None and self._focus_is_inside_widget(focus, node_view):
            if hasattr(node_view, "can_undo") and node_view.can_undo():
                node_view.undo_last_change()
            else:
                try:
                    node_view.statusMessage.emit("Nothing to undo in the node graph.")
                except Exception:
                    pass
            return True

        tabs = getattr(self, "wf_builder_tabs", None)
        graph_tab = getattr(self, "wf_graph_mode_tab", None)
        if (
            node_view is not None
            and tabs is not None
            and graph_tab is not None
            and getattr(tabs, "currentWidget", lambda: None)() is graph_tab
            and not isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit))
        ):
            if hasattr(node_view, "can_undo") and node_view.can_undo():
                node_view.undo_last_change()
            else:
                try:
                    node_view.statusMessage.emit("Nothing to undo in the node graph.")
                except Exception:
                    pass
            return True
        return False

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.KeyPress and self.isActiveWindow():
                if event.modifiers() & Qt.ControlModifier:
                    if event.key() == Qt.Key_Z:
                        return self._handle_global_undo_shortcut()
                    if event.key() == Qt.Key_S:
                        self.save_current_file()
                        return True
                    if event.key() == Qt.Key_B:
                        self.find_uses_in_current_file_from_shortcut()
                        return True
                    if event.key() == Qt.Key_N:
                        self.find_uses_in_project_from_shortcut()
                        return True
                    if event.key() == Qt.Key_D:
                        self.duplicate_current_line()
                        return True
                    if event.key() == Qt.Key_T:
                        self.trim_trailing_spaces()
                        return True
                    if event.key() == Qt.Key_F:
                        self.find_in_current_file_from_shortcut()
                        return True
        except Exception:
            pass
        try:
            return super().eventFilter(obj, event)
        except Exception:
            return False
