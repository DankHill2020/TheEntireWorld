"""Workflow authoring, graph synchronization, and persistence methods."""

from __future__ import annotations

import sys
from pathlib import Path

from tech_connector.path_bootstrap import ensure_tools_root_on_path

ensure_tools_root_on_path(__file__)

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


class MainWindowWorkflowAuthoringMixin:
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
            warning_key = tuple(
                sorted(
                    (
                        str(issue.get("step_id") or ""),
                        str(issue.get("input") or ""),
                        str(issue.get("message") or ""),
                    )
                    for issue in issues
                )
            )
            if warning_key != getattr(self, "_last_pipeline_data_flow_warning_key", None):
                self._last_pipeline_data_flow_warning_key = warning_key
                self._report_workflow_builder_event(
                    f"Pipeline data flow needs attention: {len(issues)} input(s) need a value or connection."
                )
        elif hasattr(self, "wf_test_status"):
            self._last_pipeline_data_flow_warning_key = None
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
        self._refresh_pipeline_attribute_connection_state()
        self._refresh_pipeline_auto_metadata()
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
        self._refresh_pipeline_auto_metadata()
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
            view.nodeSelected.connect(self._handle_pipeline_node_selected)
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
        try:
            editor.disconnectInputRequested.connect(
                self._handle_pipeline_attribute_disconnect_input
            )
        except Exception:
            pass

    def _handle_pipeline_node_selected(self, step_data: dict):
        editor = getattr(self, "wf_attribute_editor", None)
        view = getattr(self, "wf_node_view", None)
        if editor is None:
            return
        if not isinstance(step_data, dict):
            editor.set_node(None)
            return
        connected_inputs = {}
        if view is not None and hasattr(view, "connected_input_sources"):
            try:
                connected_inputs = view.connected_input_sources(step_data)
            except Exception:
                connected_inputs = {}
        step_data["_connected_inputs"] = connected_inputs
        editor.set_node(step_data)

    def _refresh_pipeline_attribute_connection_state(self):
        editor = getattr(self, "wf_attribute_editor", None)
        step_data = getattr(editor, "step_data", None) if editor is not None else None
        if isinstance(step_data, dict):
            self._handle_pipeline_node_selected(step_data)

    def _handle_pipeline_attribute_disconnect_input(self, payload: dict):
        step_data = (payload or {}).get("step_data") or {}
        step_id = str(step_data.get("graph_step_id") or "")
        input_name = str((payload or {}).get("input") or "")
        view = getattr(self, "wf_node_view", None)
        if not step_id or not input_name or view is None:
            return
        if hasattr(view, "disconnect_input") and view.disconnect_input(step_id, input_name):
            self._handle_pipeline_node_selected(step_data)

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

    def _activate_editor_workspace(self):
        """Bring the real Editor workspace and normal code view to the front."""
        workspace_tabs = getattr(self, "workspace_tabs", None)
        if workspace_tabs is not None:
            editor_index = -1
            try:
                for index in range(workspace_tabs.count()):
                    if workspace_tabs.tabText(index).strip().casefold() == "editor":
                        editor_index = index
                        break
                if editor_index >= 0:
                    workspace_tabs.setCurrentIndex(editor_index)
            except Exception:
                pass
        normal_editor = getattr(self, "normal_editor_widget", None)
        if normal_editor is not None:
            try:
                normal_editor.setVisible(True)
            except Exception:
                pass
        diff_editor = getattr(self, "editor_diff_widget", None)
        if diff_editor is not None:
            try:
                diff_editor.setVisible(False)
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

        if not preview:
            self._activate_editor_workspace()

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

            self.shortcut_reformat_file = QShortcut(QKeySequence("Ctrl+Alt+L"), self)
            self.shortcut_reformat_file.setContext(Qt.ApplicationShortcut)
            self.shortcut_reformat_file.activated.connect(self.reformat_current_editor_file)

            self.shortcut_fix_issues = QShortcut(QKeySequence("Alt+Enter"), self)
            self.shortcut_fix_issues.setContext(Qt.ApplicationShortcut)
            self.shortcut_fix_issues.activated.connect(self.fix_current_editor_quality_issues)

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
                if event.key() == Qt.Key_L and event.modifiers() & Qt.AltModifier:
                    self.reformat_current_editor_file()
                    event.accept()
                    return
                if event.key() == Qt.Key_F:
                    self.find_in_current_file_from_shortcut()
                    event.accept()
                    return
            if event.modifiers() & Qt.AltModifier and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.fix_current_editor_quality_issues()
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
