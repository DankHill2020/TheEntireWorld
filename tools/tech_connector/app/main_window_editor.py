"""Extracted MainWindow methods. Generated from the uploaded monolithic file."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

from tech_connector.path_bootstrap import ensure_tools_root_on_path

ensure_tools_root_on_path(__file__)

import re
import time

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QPixmap,
    QTextCursor,
)
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
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from . import main_utils
from tech_connector.editor.diff import apply_patch
from tech_connector.editor.editor_widget import CodeEditor
from tech_connector.editor.search import (
    comment_selection_python_style,
    duplicate_line,
    find_in_editor,
    trim_trailing_whitespace,
)
from tech_connector.knowledge.search import find_in_project, local_answer_about_file
from tech_connector.services.project_search_service import (
    build_deterministic_project_search_answer,
    build_project_search_prompt,
    gather_project_search_context,
    is_project_scope_request,
)
from tech_connector.services.editor_code_quality_service import (
    EditorDiagnostic,
    fix_python_quality_issues,
    python_quality_diagnostics,
    reformat_python_source,
)
from tech_connector.services.native_project_build_service import (
    create_native_build_plan,
    reformat_native_source,
    run_native_build,
)
from tech_connector.game_engine.runtime.tc_player_build_service import (
    build_windows_player,
    launch_play_in_editor,
)

from tech_connector.models.constants import SKIP_DIRS
from tech_connector.models.files import is_supported_code_file

from tech_connector.services.project_service import (
    folder_has_children,
    populate_folder_entries,
)

from tech_connector.ui.project_tree import (
    append_folder_entries,
    filter_tree_items,
    load_lazy_roots,
    populate_folder_item,
)

from tech_connector.ui.unreal_editor_dialogs import VCSWorker



class ProjectFolderLoadWorker(QThread):
    """Stream one directory into the tree without waiting for a full scan."""

    batch_ready = Signal(str, object, int)
    completed = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self, folder_path: str, parent=None, batch_size: int = 24):
        super().__init__(parent)
        self.folder_path = str(folder_path or "")
        self.batch_size = max(8, int(batch_size or 24))

    def run(self):
        entries = []
        total = 0
        try:
            folder_path = Path(self.folder_path)
            with os.scandir(folder_path) as iterator:
                for child in iterator:
                    if self.isInterruptionRequested():
                        return
                    if child.name in SKIP_DIRS:
                        continue

                    try:
                        if child.is_dir(follow_symlinks=False):
                            entry = (child.name, child.path, "folder")
                        elif child.is_file(follow_symlinks=False):
                            child_path = Path(child.path)
                            if not is_supported_code_file(child_path):
                                continue
                            entry = (child.name, child.path, "file")
                        else:
                            continue
                    except OSError:
                        continue

                    entries.append(entry)
                    total += 1

                    if len(entries) >= self.batch_size:
                        entries.sort(
                            key=lambda row: (
                                row[2] != "folder",
                                str(row[0]).casefold(),
                            )
                        )
                        self.batch_ready.emit(
                            self.folder_path,
                            list(entries),
                            total,
                        )
                        entries.clear()

            if entries:
                entries.sort(
                    key=lambda row: (
                        row[2] != "folder",
                        str(row[0]).casefold(),
                    )
                )
                self.batch_ready.emit(
                    self.folder_path,
                    list(entries),
                    total,
                )

            self.completed.emit(self.folder_path, total)
        except Exception as exc:
            self.failed.emit(self.folder_path, str(exc))


class NativeProjectBuildWorker(QThread):
    """Run CMake configure/build phases without blocking the Qt event loop."""

    output_ready = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan

    def run(self):
        try:
            receipt = run_native_build(
                self.plan,
                emit=self.output_ready.emit,
                is_cancelled=self.isInterruptionRequested,
            )
            self.completed.emit(receipt)
        except Exception as exc:
            self.failed.emit(str(exc))


class TCPlayerActionWorker(QThread):
    """Compile or package a scene without stalling the editor heartbeat."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, action: str, scene: str, output: str = "", parent=None):
        super().__init__(parent)
        self.action = str(action)
        self.scene = str(scene)
        self.output = str(output)

    def run(self):
        try:
            if self.action == "play":
                result = launch_play_in_editor(self.scene)
            elif self.action == "build":
                result = build_windows_player(self.scene, self.output)
            else:
                raise ValueError(f"Unknown TC player action: {self.action}")
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindowEditorMixin:
    def _choose_tc_scene(self) -> str:
        previous = str(self.settings.get("last_tc_player_scene") or "")
        start = str(Path(previous).parent) if previous else str(Path.cwd())
        path, _ = QFileDialog.getOpenFileName(self, "Choose TC Scene", start, "TC Scene (*.tcscene)")
        if path:
            self.settings["last_tc_player_scene"] = str(Path(path).resolve())
        return path

    def play_tc_scene(self) -> bool:
        scene = self._choose_tc_scene()
        if not scene:
            return False
        active = getattr(self, "_tc_player_worker", None)
        if active is not None and active.isRunning():
            QMessageBox.information(self, "Player active", "A TC player action is already running.")
            return False
        self.engine_console_toggle.setChecked(True)
        self.engine_console_output.appendPlainText(f"Compiling Play In Editor scene: {scene}")
        self.engine_play_btn.setEnabled(False)
        worker = TCPlayerActionWorker("play", scene, parent=self)
        worker.completed.connect(self._tc_play_started)
        worker.failed.connect(self._tc_player_action_failed)
        worker.finished.connect(worker.deleteLater)
        self._tc_player_worker = worker
        worker.start()
        return True

    def build_tc_windows_player(self) -> bool:
        scene = self._choose_tc_scene()
        if not scene:
            return False
        default = str(Path(scene).with_name(Path(scene).stem + "_WindowsPlayer"))
        output = QFileDialog.getExistingDirectory(self, "Windows Player Output", str(Path(default).parent))
        if not output:
            return False
        output = str(Path(output) / (Path(scene).stem + "_WindowsPlayer"))
        self.engine_console_toggle.setChecked(True)
        self.engine_console_output.appendPlainText(f"Building Windows player: {output}")
        self.engine_build_player_btn.setEnabled(False)
        worker = TCPlayerActionWorker("build", scene, output, self)
        worker.completed.connect(self._tc_player_built)
        worker.failed.connect(self._tc_player_action_failed)
        worker.finished.connect(worker.deleteLater)
        self._tc_player_worker = worker
        worker.start()
        return True

    def stop_tc_play_in_editor(self) -> bool:
        session = getattr(self, "_tc_pie_session", None)
        if session is None or session.process.poll() is not None:
            self.engine_stop_btn.setEnabled(False)
            self.engine_console_output.appendPlainText("No TC Play In Editor session is running.")
            return False
        session.stop()
        timer = getattr(self, "_tc_runtime_log_timer", None)
        if timer is not None:
            timer.stop()
        self.poll_tc_runtime_log()
        self.engine_stop_btn.setEnabled(False)
        self.engine_console_output.appendPlainText("TC Play In Editor stopped.")
        return True

    def _tc_play_started(self, session) -> None:
        self.engine_play_btn.setEnabled(True)
        self._tc_player_worker = None
        self._tc_pie_session = session
        self.engine_stop_btn.setEnabled(True)
        self._tc_runtime_log_offset = 0
        timer = getattr(self, "_tc_runtime_log_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(250)
            timer.timeout.connect(self.poll_tc_runtime_log)
            self._tc_runtime_log_timer = timer
        timer.start()
        self.engine_console_output.appendPlainText(
            f"TC standalone PIE started (PID {session.process.pid}).\n"
            f"Runtime profile: {session.profile_log}"
        )

    def poll_tc_runtime_log(self) -> None:
        session = getattr(self, "_tc_pie_session", None)
        if session is None:
            return
        path = Path(session.profile_log)
        last_profile = None
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    stream.seek(int(getattr(self, "_tc_runtime_log_offset", 0)))
                    chunk = stream.read()
                    self._tc_runtime_log_offset = stream.tell()
                    for line in chunk.splitlines():
                        text = line.strip()
                        if not text:
                            continue
                        if text.startswith("{"):
                            try:
                                payload = json.loads(text)
                            except json.JSONDecodeError:
                                self.engine_console_output.appendPlainText(text)
                            else:
                                if payload.get("type") == "frame":
                                    last_profile = payload
                        else:
                            self.engine_console_output.appendPlainText(text)
            except OSError as exc:
                self.engine_console_output.appendPlainText(f"Runtime log read failed: {exc}")
        if last_profile:
            self.engine_console_target.setText(
                f"PIE: {float(last_profile.get('frame_ms') or 0.0):.2f} ms | "
                f"{int(last_profile.get('entities') or 0)} entities | "
                f"{int(last_profile.get('draw_calls') or 0)} draws"
            )
        return_code = session.process.poll()
        if return_code is not None:
            timer = getattr(self, "_tc_runtime_log_timer", None)
            if timer is not None:
                timer.stop()
            self.engine_stop_btn.setEnabled(False)
            self.engine_console_target.setText("Target: active TC scene")
            self.engine_console_output.appendPlainText(f"TC Play In Editor exited with code {return_code}.")

    def _tc_player_built(self, receipt) -> None:
        self.engine_build_player_btn.setEnabled(True)
        self._tc_player_worker = None
        self.engine_console_output.appendPlainText(
            f"Windows player ready: {receipt.player_executable}\n"
            f"{receipt.entities} entities, {len(receipt.assets)} assets, {receipt.graph_operations} graph operations."
        )
        for warning in receipt.warnings:
            self.engine_console_output.appendPlainText(f"Warning: {warning}")

    def _tc_player_action_failed(self, message: str) -> None:
        self.engine_play_btn.setEnabled(True)
        self.engine_build_player_btn.setEnabled(True)
        self._tc_player_worker = None
        self.engine_console_output.appendPlainText(f"TC player action failed: {message}")

    def update_cursor_status(self):
        if not hasattr(self, "editor_status_label"):
            return
        cursor = self.code_editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        dirty = " • modified" if self.code_editor.document().isModified() else ""

        status_text = f"Line {line}, Col {col}{dirty}{self._editor_syntax_suffix}"
        self.editor_status_label.setText(status_text)
        return
        path = getattr(self, "current_file_path", "")
        if path and path.endswith(".py"):
            try:
                compile(self.code_editor.toPlainText(), "<string>", "exec")
                status_text += " | ✓ Python Syntax Valid"
            except SyntaxError as e:
                status_text += f" | ⚠️ Python Syntax Error: {e.msg} (line {e.lineno})"
            except Exception as e:
                status_text += f" | ⚠️ Check Error: {e}"
        self.editor_status_label.setText(status_text)

    def schedule_editor_syntax_status(self):
        path = getattr(self, "current_file_path", "")
        if path and path.endswith(".py"):
            self._editor_syntax_suffix = " | Checking Python syntax..."
            self.editor_status_timer.start(450)
        else:
            self._editor_syntax_suffix = ""
        self.update_cursor_status()
        self.schedule_editor_structure_refresh()

    def update_editor_syntax_status(self):
        path = getattr(self, "current_file_path", "")
        if not path or not path.endswith(".py"):
            self._editor_syntax_suffix = ""
            self.update_editor_problems([])
            self.update_cursor_status()
            return
        try:
            diagnostics = python_quality_diagnostics(self.code_editor.toPlainText(), path)
            self.update_editor_problems(diagnostics)
            errors = [item for item in diagnostics if item.severity == "error"]
            warnings = [item for item in diagnostics if item.severity != "error"]
            if errors:
                first = errors[0]
                self._editor_syntax_suffix = f" | Error {first.code} line {first.line}: {first.message}"
            elif warnings:
                self._editor_syntax_suffix = f" | {len(warnings)} warning(s)"
            else:
                self._editor_syntax_suffix = " | Python Quality OK"
        except Exception as e:
            self._editor_syntax_suffix = f" | Check Error: {e}"
            self.update_editor_problems([])
        self.update_cursor_status()

    def update_editor_problems(self, diagnostics: list[EditorDiagnostic]) -> None:
        problems = getattr(self, "editor_problems_list", None)
        if problems is None:
            return
        problems.clear()
        self._editor_problem_count = len(diagnostics or [])
        for diagnostic in diagnostics[:120]:
            item = QListWidgetItem(diagnostic.display_text())
            item.setData(
                Qt.UserRole,
                {
                    "line": diagnostic.line,
                    "column": diagnostic.column,
                    "path": str(getattr(diagnostic, "file", "") or ""),
                },
            )
            if diagnostic.severity == "error":
                item.setForeground(QBrush(QColor("#ff6b6b")))
            elif diagnostic.fixable:
                item.setForeground(QBrush(QColor("#ffd166")))
            else:
                item.setForeground(QBrush(QColor("#9cc7d8")))
            problems.addItem(item)
        self._sync_editor_problems_visibility()

    def set_editor_problems_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.settings["editor_problems_visible"] = visible
        try:
            self.service.settings["editor_problems_visible"] = visible
            self.service.save_settings()
        except Exception:
            pass
        self._sync_editor_problems_visibility()

    def set_engine_console_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.settings["engine_console_visible"] = visible
        panel = getattr(self, "engine_console_panel", None)
        if panel is not None:
            panel.setVisible(visible)
        try:
            self.service.settings["engine_console_visible"] = visible
            self.service.save_settings()
        except Exception:
            pass
        if visible and hasattr(self, "engine_console_input"):
            self.engine_console_input.setFocus()

    def on_engine_console_mode_changed(self, mode: str) -> None:
        editor = getattr(self, "engine_console_input", None)
        if editor is None:
            return
        if str(mode) == "TC Command":
            editor.setPlaceholderText('{"command": "world_ai.find_path", "payload": {"graph_id": "town", "start": "a", "goal": "b"}}')
        else:
            editor.setPlaceholderText("print(world.world_facts)\nengine.validate_game_experience(game_profile)")

    def execute_engine_console(self) -> bool:
        editor = getattr(self, "engine_console_input", None)
        output = getattr(self, "engine_console_output", None)
        if editor is None or output is None:
            return False
        source = editor.toPlainText()
        if not source.strip():
            return False
        from tech_connector.services.engine_console_service import EngineConsoleSession

        session = getattr(self, "_engine_console_session", None)
        if session is None:
            session = EngineConsoleSession()
            self._engine_console_session = session
        mode = self.engine_console_mode.currentText()
        if mode == "TC Command":
            from tech_connector.game_engine.integration.active_viewer_command_service import execute_active_viewer_command

            receipt = session.execute_tc_command(source, execute_active_viewer_command)
        else:
            from tech_connector.game_engine.integration.active_viewer_command_service import (
                active_viewer,
                execute_active_viewer_command,
            )
            from tech_connector.game_engine.runtime.tc_engine_api import engine

            viewer = active_viewer()
            context = {
                "engine": engine,
                "run_command": execute_active_viewer_command,
                "viewer": viewer,
                "world": getattr(viewer, "character_world", None) if viewer is not None else None,
                "game_profile": getattr(viewer, "game_experience_profile", None) if viewer is not None else None,
                "runtime_state": getattr(viewer, "world_intelligence_runtime", None) if viewer is not None else None,
                "scene_document": viewer.build_federated_scene_document() if viewer is not None else None,
            }
            receipt = session.execute_python(source, context)
        state = "OK" if receipt.ok else "ERROR"
        output.appendPlainText(f"[{receipt.mode} {state} {receipt.elapsed_ms:.2f} ms]")
        if receipt.output:
            output.appendPlainText(receipt.output.rstrip())
        if receipt.result_repr:
            output.appendPlainText(receipt.result_repr)
        if receipt.error:
            output.appendPlainText(receipt.error.rstrip())
        output.appendPlainText("")
        scrollbar = output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        return receipt.ok

    def reset_engine_console(self) -> None:
        session = getattr(self, "_engine_console_session", None)
        if session is not None:
            session.reset()
            session.history.clear()
        output = getattr(self, "engine_console_output", None)
        if output is not None:
            output.clear()

    def _sync_editor_problems_visibility(self) -> None:
        problems = getattr(self, "editor_problems_list", None)
        if problems is None:
            return
        enabled = bool(self.settings.get("editor_problems_visible", False))
        count = int(getattr(self, "_editor_problem_count", 0) or 0)
        problems.setVisible(enabled and count > 0)
        toggle = getattr(self, "editor_problems_toggle", None)
        if toggle is not None:
            if toggle.isChecked() != enabled:
                toggle.blockSignals(True)
                toggle.setChecked(enabled)
                toggle.blockSignals(False)
            toggle.setText(f"Warnings {count}" if count else "Warnings")
            toggle.setToolTip(
                f"Show source diagnostics and style warnings ({count} found)"
                if count
                else "Show source diagnostics and style warnings"
            )

    def preview_editor_problem_item(self, item: QListWidgetItem) -> None:
        self._goto_editor_problem_item(item, focus_editor=False)

    def jump_to_editor_problem_item(self, item: QListWidgetItem) -> None:
        self._goto_editor_problem_item(item, focus_editor=True)

    def _goto_editor_problem_item(self, item: QListWidgetItem, *, focus_editor: bool) -> None:
        data = item.data(Qt.UserRole) or {}
        line = int(data.get("line") or 1)
        column = int(data.get("column") or 1)
        path = str(data.get("path") or "")
        if focus_editor and path and Path(path).is_file():
            self.open_code_file(path)
        editor = self.open_editors.get(getattr(self, "current_file_path", ""), self.code_editor)
        if hasattr(editor, "goto_line"):
            editor.goto_line(line)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        for _ in range(max(0, line - 1)):
            cursor.movePosition(QTextCursor.Down)
        for _ in range(max(0, column - 1)):
            cursor.movePosition(QTextCursor.Right)
        editor.setTextCursor(cursor)
        if focus_editor:
            editor.setFocus()

    def toggle_fullscreen_mode(self, checked):
        if hasattr(self, "editor_fullscreen_btn"):
            self.editor_fullscreen_btn.blockSignals(True)
            self.editor_fullscreen_btn.setChecked(checked)
            self.editor_fullscreen_btn.blockSignals(False)
        if hasattr(self, "chat_fullscreen_btn"):
            self.chat_fullscreen_btn.blockSignals(True)
            self.chat_fullscreen_btn.setChecked(checked)
            self.chat_fullscreen_btn.blockSignals(False)

        if hasattr(self, "left_panel"):
            self.left_panel.setVisible(not checked)
        if hasattr(self, "top_section_widget"):
            self.top_section_widget.setVisible(not checked)
        if hasattr(self, "bottom_controls_widget"):
            self.bottom_controls_widget.setVisible(not checked)

    def find_in_current_file(self):
        query = self.editor_find.text().strip()
        if not query:
            return
        if not find_in_editor(self.code_editor, query):
            self.append(f"\n[Find in file] No match for: {query}\n")

    def goto_line_from_box(self):
        text = self.goto_line_box.text().strip()
        if not text:
            return
        try:
            self.code_editor.goto_line(int(text))
        except Exception:
            self.append(f"\n[Go To Line] Invalid line: {text}\n")

    def duplicate_current_line(self):
        duplicate_line(self.code_editor)
        self.update_cursor_status()

    def comment_selection_python_style(self):
        comment_selection_python_style(self.code_editor)

    def format_python_basic(self):
        trim_trailing_whitespace(self.code_editor)
        self.append("\n[Editor] Trimmed trailing whitespace.\n")

    def ensure_file_writable_for_save(self, path: str, action: str = "save") -> bool:
        if not path:
            return True

        vcs = self.service.version_control_for_path(path)
        if vcs and vcs.kind == "perforce" and self.service.is_read_only_file(path):
            if self.settings.get("auto_checkout_on_change", True):
                ok, msg = vcs.checkout_file(Path(path))
                if ok:
                    self.append(f"\n[Perforce] Auto checked out for edit: {msg}\n")
                    return True
                else:
                    self.append(f"\n[Perforce Error] p4 edit failed: {msg}\n")
            else:
                reply = QMessageBox.question(
                    self,
                    "Check out from Perforce?",
                    f"This file is read-only:\n\n{path}\n\nWould you like to run 'p4 edit' to check it out?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                if reply == QMessageBox.Yes:
                    ok, msg = vcs.checkout_file(Path(path))
                    if ok:
                        self.append(f"\n[Perforce] Checked out for edit: {msg}\n")
                        return True
                    else:
                        self.append(f"\n[Perforce Error] p4 edit failed: {msg}\n")

        if not self.service.is_read_only_file(path):
            return True

        if self.settings.get("auto_checkout_on_change", True):
            ok, msg = self.service.make_file_writable(path)
            if ok:
                self.append(f"\n[File permissions] Auto made writable: {msg}\n")
                return True
            else:
                QMessageBox.critical(self, "Could not make file writable", msg)
                return False

        reply = QMessageBox.question(
            self,
            "File is read-only",
            f"This file is read-only:\n\n{path}\n\nMake it writable and {action}?",
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Ok:
            self.append(f"\n[Save cancelled] File remains read-only: {path}\n")
            return False

        ok, msg = self.service.make_file_writable(path)
        if not ok:
            QMessageBox.critical(self, "Could not make file writable", msg)
            return False

        self.append(f"\n[File permissions] Made writable: {msg}\n")
        return True

    def prepare_vcs_for_write(self, path: str, action: str = "save") -> bool:
        """Prepare existing files for writes; new files are marked after saving."""
        if not path:
            return True
        p = Path(path)
        if not p.exists():
            return True
        return self.ensure_file_writable_for_save(path, action)

    def finalize_vcs_after_write(self, path: str, *, existed_before: bool) -> None:
        if not path:
            return
        vcs = self.service.version_control_for_path(path)
        if not vcs:
            return
        p = Path(path)
        if not existed_before and vcs.kind == "perforce":
            ok, msg = vcs.mark_for_add(p)
            self.append(
                f"\n[Perforce] {'Marked for add' if ok else 'Mark for add failed'}: {msg}\n"
            )
        elif not existed_before and vcs.kind == "git":
            _ok, msg = vcs.mark_for_add(p)
            self.append(f"\n[Git] {msg}\n")
        try:
            self.update_vcs_status_card()
        except Exception:
            pass

    def write_text_with_vcs(self, path: str, content: str, action: str = "save") -> bool:
        if not path:
            return False
        existed_before = Path(path).exists()
        if not self.prepare_vcs_for_write(path, action):
            return False
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        self.finalize_vcs_after_write(path, existed_before=existed_before)
        try:
            from tech_connector.services.project_service import queue_project_index_updates

            queue_project_index_updates([path])
        except Exception:
            pass
        return True

    def apply_pending_editor_patch(self):
        patch = getattr(self, "pending_editor_patch", None)
        if not patch:
            QMessageBox.information(
                self, "No patch", "No safe pending patch is available yet."
            )
            return

        if not self.ensure_file_writable_for_save(str(patch["path"]), "apply this fix"):
            return

        ok, msg, updated = apply_patch(patch)
        if not ok:
            QMessageBox.critical(self, "Patch failed", msg)
            return

        if (
                getattr(self, "current_file_path", "") == str(patch["path"])
                and updated is not None
        ):
            self.code_editor.setPlainText(updated)
            self.code_editor.document().setModified(False)
            self.update_cursor_status()

        path = Path(patch["path"])
        backup = path.with_suffix(path.suffix + ".tew_backup")
        try:
            from tech_connector.services.chat_report_service import format_code_change_report

            report = format_code_change_report(
                [
                    {
                        "path": str(path),
                        "action": patch.get("action", "modify"),
                        "before": patch.get("old", ""),
                        "after": patch.get("new", ""),
                        "line": patch.get("start") or 1,
                        "summary": patch.get("summary", "Applied safe local patch."),
                    }
                ],
                title="Editor Patch Applied",
                validation=[f"Backup written: `{backup}`"],
            )
            self.append(f"\nASSISTANT [Code Change Report]:\n{report}\n")
        except Exception:
            self.append(
                "\\n[Applied Editor Patch]\\n"
                f"File: {path}\\n"
                f"Change: {patch.get('summary', 'Applied safe local patch.')}\\n"
                f"Backup: {backup}\\n"
            )
        self.pending_editor_patch = None

    def _start_editor_assist_progress(self, initial_stage: str) -> None:
        """Show the active editor-assist stage with a live elapsed time."""

        timer = getattr(self, "_editor_assist_progress_timer", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._editor_assist_progress_started_at = time.monotonic()
        self._editor_assist_progress_stage = str(initial_stage or "Editor assist working")
        timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(self._refresh_editor_assist_progress)
        self._editor_assist_progress_timer = timer
        timer.start()
        self._refresh_editor_assist_progress()

    def _on_editor_assist_status(self, stage: str) -> None:
        self._editor_assist_progress_stage = str(stage or "Editor assist working")
        self._refresh_editor_assist_progress()

    def _refresh_editor_assist_progress(self) -> None:
        started_at = float(getattr(self, "_editor_assist_progress_started_at", time.monotonic()))
        elapsed = max(0, int(time.monotonic() - started_at))
        stage = str(getattr(self, "_editor_assist_progress_stage", "Editor assist working"))
        if hasattr(self, "set_live_process"):
            self.set_live_process(f"{stage} ({elapsed}s)")

    def _stop_editor_assist_progress(self) -> None:
        timer = getattr(self, "_editor_assist_progress_timer", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._editor_assist_progress_timer = None

    def approve_pending_editor_plan(self):
        """Resume project-edit generation only after the user approves its plan."""

        plan_payload = getattr(self, "pending_editor_plan", None)
        if not isinstance(plan_payload, dict):
            QMessageBox.information(self, "No plan", "No implementation plan is waiting for approval.")
            return
        path = str(plan_payload.get("path") or getattr(self, "current_file_path", ""))
        question = str(plan_payload.get("question") or getattr(self, "editor_prompt_question", ""))
        if not path or not question:
            QMessageBox.critical(self, "Plan unavailable", "The pending plan is missing its target or request.")
            return

        self.pending_editor_plan = None
        if hasattr(self, "approve_editor_plan_btn"):
            self.approve_editor_plan_btn.setVisible(False)
        self.ask_file_btn.setEnabled(False)
        self.editor_prompt.setEnabled(False)
        self.ask_file_btn.setText("Generating...")
        self._editor_assist_resume_from_plan = True
        self.append("\nYOU [Plan Approval]:\nApproved implementation plan for preview generation.\n")
        self._start_editor_assist_progress("Approved plan; generating code preview")
        self.editor_assist_worker = EditorAssistWorker(
            path,
            question,
            self.code_editor.toPlainText(),
            self,
            approved_plan=plan_payload,
        )
        if hasattr(self.editor_assist_worker, "status"):
            self.editor_assist_worker.status.connect(self._on_editor_assist_status)
        self.editor_assist_worker.finished_ok.connect(self.on_editor_assist_finished)
        self.editor_assist_worker.finished.connect(self.editor_assist_worker.deleteLater)
        self.editor_assist_worker.start()

    def ask_about_current_file(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        question = self.editor_prompt.text().strip()
        if not question:
            QMessageBox.information(
                self, "No question", "Type a question about the current file first."
            )
            return

        self.ask_file_btn.setEnabled(False)
        self.editor_prompt.setEnabled(False)
        self.ask_file_btn.setText("Analyzing...")
        self.editor_prompt_question = question
        self._start_editor_assist_progress("Editor assist: gathering current file context")

        # Run the local AST/LLM analysis in a background thread to prevent GUI freezing
        self.editor_assist_worker = EditorAssistWorker(
            path, question, self.code_editor.toPlainText(), self
        )
        if hasattr(self.editor_assist_worker, "status"):
            self.editor_assist_worker.status.connect(self._on_editor_assist_status)
        self.editor_assist_worker.finished_ok.connect(self.on_editor_assist_finished)
        self.editor_assist_worker.finished.connect(self.editor_assist_worker.deleteLater)
        print("[EditorAssist] Starting worker", flush=True)
        self.editor_assist_worker.start()

    def on_editor_assist_finished(self, result, patch):
        self._stop_editor_assist_progress()
        resumed_from_plan = bool(getattr(self, "_editor_assist_resume_from_plan", False))
        self._editor_assist_resume_from_plan = False
        self.ask_file_btn.setEnabled(True)
        self.editor_prompt.setEnabled(True)
        self.ask_file_btn.setText("Ask About File")
        if hasattr(self, "set_live_process"):
            self.set_live_process("Editor assist complete")

        is_plan = isinstance(patch, dict) and patch.get("type") == "project_edit_plan"
        production_readiness = (
            dict(patch.get("production_readiness") or {})
            if isinstance(patch, dict)
            else {}
        )
        self.last_production_readiness = production_readiness
        if production_readiness and not production_readiness.get("ready"):
            readiness_summary = str(
                production_readiness.get("summary")
                or "The generated candidate is not production ready."
            )
            if hasattr(self, "set_live_process"):
                self.set_live_process(readiness_summary)
        self.pending_editor_patch = None if is_plan else (patch or None)
        self.last_user_prompt = self.editor_prompt_question
        self.service.last_user_prompt = self.editor_prompt_question
        self.last_assistant_output = result
        self.service.last_assistant_output = result
        self.last_editor_assist_payload = {
            "title": f"Ask About File: {Path(getattr(self, 'current_file_path', '')).name}",
            "source": "Ask About File",
            "content": f"Question:\n{self.editor_prompt_question}\n\nAnswer:\n{result}",
        }
        if hasattr(self, "add_editor_answer_workflow_btn"):
            self.add_editor_answer_workflow_btn.setEnabled(True)
        self.workspace_tabs.setCurrentIndex(0)
        if not resumed_from_plan:
            self.append("\nYOU [Editor Question]:\n" + self.editor_prompt_question + "\n")
        response_label = (
            "Implementation Plan"
            if is_plan
            else (
                "Production Ready"
                if production_readiness.get("ready")
                else "Not Production Ready"
            )
        )
        self.append(f"\nASSISTANT [{response_label}]:\n{result}\n")

        if is_plan:
            self.pending_editor_plan = patch
            if hasattr(self, "approve_editor_plan_btn"):
                self.approve_editor_plan_btn.setVisible(True)
                self.approve_editor_plan_btn.setEnabled(True)
            if hasattr(self, "set_live_process"):
                self.set_live_process("Implementation plan awaiting approval")
            return
        self.pending_editor_plan = None
        if hasattr(self, "approve_editor_plan_btn"):
            self.approve_editor_plan_btn.setVisible(False)

        if patch and production_readiness.get("ready", True):
            changes_list = []

            if patch.get("type") == "project_changes":
                for change in patch["changes"]:
                    path = change["path"]
                    action = change["action"]

                    if action == "create":
                        changes_list.append(
                            {
                                "path": path,
                                "action": "create",
                                "original_content": "",
                                "new_content": change["new_content"],
                            }
                        )
                    elif action == "modify":
                        ok, content = self.service.read_file(path)
                        if ok:
                            orig = change["original_content"]
                            rep = change["new_content"]
                            from tech_connector.knowledge.search import replace_content_resilient

                            matched, full_new_content = replace_content_resilient(
                                content, orig, rep
                            )
                            changes_list.append(
                                {
                                    "path": path,
                                    "action": "modify",
                                    "original_content": content,
                                    "new_content": full_new_content
                                    if matched
                                    else content,
                                }
                            )
            else:
                path = patch.get("file")
                if path:
                    ok, content = self.service.read_file(path)
                    if ok:
                        orig = patch.get("original", "")
                        rep = patch.get("new", "")
                        from tech_connector.knowledge.search import replace_content_resilient

                        matched, full_new_content = replace_content_resilient(
                            content, orig, rep
                        )
                        changes_list.append(
                            {
                                "path": path,
                                "action": "modify",
                                "original_content": content,
                                "new_content": full_new_content if matched else content,
                            }
                        )

            if changes_list:
                self.workspace_tabs.setCurrentIndex(1)
                self.normal_editor_widget.setVisible(False)
                self.editor_diff_widget.set_changes(changes_list)
                self.editor_diff_widget.set_validation_evidence(
                    {
                        "summary": production_readiness.get("summary", ""),
                        "validation": production_readiness.get("validation", []),
                        "errors": patch.get("validation_errors", []),
                    }
                )
                self.editor_diff_widget.setVisible(True)
                self.append(
                    "\n[Status] Proposed code changes loaded into the Editor Diff comparison view.\n"
                )

    def perform_project_wide_swap(self, old_name, new_name):
        if not old_name or not new_name or old_name == new_name:
            return

        from tech_connector.models.constants import SKIP_DIRS, SUPPORTED_CODE_EXTS

        project_dirs = self.project_roots()
        current_file = getattr(self, "current_file_path", "")

        extra_dirs_resolved = [
            str(Path(d).resolve()) for d in project_dirs if Path(d).exists()
        ]
        if current_file:
            extra_dirs_resolved.append(str(Path(current_file).parent.resolve()))
            p = Path(current_file).parent
            while p != p.parent:
                if (p / ".git").exists() or (
                        p / "knowledge" / "mcp_unreal_maya_knowledge_config.json"
                ).exists():
                    extra_dirs_resolved.append(str(p.resolve()))
                    break
                p = p.parent

        project_dirs_resolved = sorted(list(set(extra_dirs_resolved)))
        if not project_dirs_resolved:
            project_dirs_resolved = [os.getcwd()]

        module_name = None
        if current_file:
            module_name = main_utils.get_python_module_name(
                current_file, project_dirs_resolved
            )

        modified_count = 0
        occurrence_count = 0
        pattern = re.compile(rf"\b{re.escape(old_name)}\b")

        for pdir in project_dirs_resolved:
            for root, dirs, files in os.walk(pdir):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for file in files:
                    fpath = Path(root) / file
                    if fpath.suffix.lower() not in SUPPORTED_CODE_EXTS:
                        continue
                    if current_file and fpath.resolve() == Path(current_file).resolve():
                        continue

                    try:
                        content = fpath.read_text(encoding="utf-8", errors="replace")
                        if pattern.search(content):
                            new_content, count = pattern.subn(new_name, content)
                            if count > 0:
                                fpath.write_text(new_content, encoding="utf-8")
                                modified_count += 1
                                occurrence_count += count

                                if module_name:
                                    main_utils.insert_import_if_needed(
                                        fpath, module_name, new_name
                                    )
                    except Exception as e:
                        print(f"Failed to swap in file {fpath}: {e}")

        msg = f"Project swap complete: replaced '{old_name}' with '{new_name}' in {modified_count} files ({occurrence_count} occurrences)."
        self.append(f"\n[Refactor] {msg}\n")
        QMessageBox.information(self, "Swap Complete", msg)

    def ask_about_file_with_llm(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        question = self.editor_prompt.text().strip()
        if not question:
            QMessageBox.information(
                self, "No question", "Type a question about the current file first."
            )
            return
        local_context, _ = local_answer_about_file(
            path, question, self.code_editor.toPlainText(), query_llm=False
        )
        prompt = self.prompt_router.editor_llm_question(question, local_context)
        self.workspace_tabs.setCurrentIndex(0)
        self.send_raw(prompt, "Editor LLM Question")

    def ask_about_selection(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        question = (
                self.editor_prompt.text().strip()
                or "Explain this selected code and suggest improvements."
        )
        cursor = self.code_editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n").strip()
        if not selected:
            QMessageBox.information(
                self,
                "No selection",
                "Select code in the editor first, or use Ask About File.",
            )
            return
        if len(selected) > 8000:
            selected = selected[:8000] + "\n\n...[selection truncated]..."
        self.last_editor_assist_payload = {
            "title": f"Ask Selection: {Path(path).name}",
            "source": "Ask Selection",
            "content": f"Question:\n{question}\n\nSelected code:\n{selected}",
        }
        if hasattr(self, "add_editor_answer_workflow_btn"):
            self.add_editor_answer_workflow_btn.setEnabled(True)
        prompt = self.prompt_router.editor_selection_question(path, question, selected)
        self.workspace_tabs.setCurrentIndex(0)
        self.send_raw(prompt, "Editor Selection Question")

    def ask_for_edit_plan(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file first.")
            return
        request = self.editor_prompt.text().strip()
        if not request:
            QMessageBox.information(self, "No request", "Type the edit you want first.")
            return
        prompt = self.prompt_router.editor_edit_plan(path, request)
        self.workspace_tabs.setCurrentIndex(0)
        self.send_raw(prompt, "Editor Edit Plan")

    def load_project_tree_lazy(self):
        if not hasattr(self, "project_tree"):
            return

        workers = getattr(self, "_project_tree_folder_workers", {})
        for worker in list(workers.values()):
            try:
                worker.requestInterruption()
            except Exception:
                pass
        self._project_tree_folder_workers = {}

        load_lazy_roots(self.project_tree, self.project_roots(), self.style())
        self.status.setText("Project loaded")
        self.update_project_header(check_vcs=False)

    def update_project_header(self, *, check_vcs: bool = True):
        active = self.settings.get("active_project", "")
        display = active or "No active project"
        if hasattr(self, "project_root_label"):
            self.project_root_label.setText(display)
            self.project_root_label.setToolTip(f"Tools Project\n{display}")
        if hasattr(self, "project_directories_label"):
            try:
                directories = self.service.resolved_project_directories()
                game_name = directories.game_project.name or str(directories.game_project)
                art_name = directories.art_source.name or str(directories.art_source)
                self.project_directories_label.setText(f"Game: {game_name}  |  Art: {art_name}")
                self.project_directories_label.setToolTip(
                    f"Game Project\n{directories.game_project}\n\nArt Source\n{directories.art_source}"
                )
            except Exception:
                self.project_directories_label.setText("Game and Art paths unavailable")
        if not check_vcs or getattr(self, "_startup_defer_expensive_status", False):
            self.set_card("vcs", "unknown", "Checking later")
            return
        self.update_vcs_status_card()

    def refresh_recent_projects(self):
        if not hasattr(self, "recent_project_box"):
            return

        active = self.settings.get("active_project", "")
        self.recent_project_box.blockSignals(True)
        self.recent_project_box.clear()
        recents = self.service.recent_projects()
        if recents:
            for path in recents:
                self.recent_project_box.addItem(Path(path).name or path, path)
        else:
            self.recent_project_box.addItem("No recent projects", "")
        idx = self.recent_project_box.findData(active)
        if idx >= 0:
            self.recent_project_box.setCurrentIndex(idx)
        self.recent_project_box.blockSignals(False)

    def update_vcs_status_card(self):
        active = self.settings.get("active_project", "")
        if not active:
            account_hint = self._vcs_account_hint()
            self.set_card("vcs", "off", account_hint or "None")
            return

        import threading

        if getattr(self, "_vcs_status_thread", None) is not None and self._vcs_status_thread.is_alive():
            return
        self.set_card("vcs", "unknown", "Checking")
        settings_snapshot = dict(getattr(self, "settings", {}) or {})

        def run():
            state = "off"
            detail = "None"
            try:
                from tech_connector.services.version_control_service import detect_version_controls_for_path

                providers = detect_version_controls_for_path(Path(active))
            except Exception:
                try:
                    providers = [self.service.version_control_for_path(active)]
                    providers = [provider for provider in providers if provider]
                except Exception:
                    providers = []
            if providers:
                details = []
                for vcs in providers:
                    if vcs.kind == "git":
                        account_hint = self._vcs_account_hint("git")
                        checkout_state = {}
                        try:
                            checkout_state = vcs.checkout_state(Path(active))
                        except Exception:
                            pass
                        item = checkout_state.get("label") or "Git"
                        if account_hint:
                            item += f" / {account_hint}"
                        details.append(item)
                    elif vcs.kind == "perforce":
                        client = ""
                        checkout_state = {}
                        try:
                            import subprocess

                            creationflags = 0
                            if sys.platform == "win32":
                                creationflags = 0x08000000
                            res = subprocess.run(
                                ["p4", "info"],
                                cwd=active,
                                capture_output=True,
                                text=True,
                                creationflags=creationflags,
                                check=False,
                                timeout=2.5,
                            )
                            if res.returncode == 0:
                                for line in res.stdout.splitlines():
                                    if line.startswith("Client name:"):
                                        client = f" ({line.split(':', 1)[1].strip()})"
                                        break
                            checkout_state = vcs.checkout_state(Path(active))
                        except Exception:
                            pass
                        account_hint = self._vcs_account_hint("perforce")
                        item = f"Perforce{client}"
                        if checkout_state.get("label"):
                            item += f" / {checkout_state.get('label')}"
                        if account_hint:
                            item += f" / {account_hint}"
                        details.append(item)
                state = "ok"
                detail = " | ".join(details) if details else "Detected"
            try:
                self.vcs_status_ready.emit((state, detail, active, settings_snapshot))
            except Exception:
                pass

        self._vcs_status_thread = threading.Thread(target=run, daemon=True, name="vcs-status-card")
        self._vcs_status_thread.start()

    def _apply_vcs_status_card(self, payload):
        try:
            state, detail, active, _settings_snapshot = payload
        except Exception:
            state, detail, active = "warn", "Status unavailable", ""
        if active and active != self.settings.get("active_project", ""):
            return
        self.set_card("vcs", state, detail)

    def _active_vcs_root(self) -> Path | None:
        active = self.settings.get("active_project", "") or getattr(self, "current_file_path", "")
        if not active:
            return None
        return Path(active)

    def _detected_vcs_providers(self, root: Path):
        from tech_connector.services.version_control_service import detect_version_controls_for_path

        return detect_version_controls_for_path(root)

    def show_vcs_changelists_dialog(self):
        root = self._active_vcs_root()
        if not root:
            QMessageBox.information(self, "Current Changelists", "Load a project first.")
            return
        providers = self._detected_vcs_providers(root)
        if not providers:
            QMessageBox.information(self, "Current Changelists", "No Git or Perforce provider detected for this project.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Current Changelists")
        dialog.resize(780, 520)
        layout = QVBoxLayout(dialog)
        title = QLabel("Current Changelists")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        body = QPlainTextEdit()
        body.setReadOnly(True)
        lines = []
        for provider in providers:
            ok, msg, items = provider.current_changelists(root)
            lines.append(f"{provider.kind.upper()}: {msg}")
            if not ok:
                lines.append("  Failed to query changelists.")
            elif not items:
                lines.append("  None")
            else:
                for item in items:
                    desc = item.get("description") or ""
                    count = item.get("file_count")
                    count_label = f" ({count} files)" if count is not None else ""
                    extra = item.get("path") or item.get("owner") or ""
                    lines.append(f"  {item.get('id', '<unknown>')}{count_label}: {desc}")
                    if extra:
                        lines.append(f"    {extra}")
            lines.append("")
        body.setPlainText("\n".join(lines).strip())
        layout.addWidget(body, 1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)
        dialog.exec()

    def create_vcs_changelist_dialog(self):
        root = self._active_vcs_root()
        if not root:
            QMessageBox.information(self, "Create Changelist", "Load a project first.")
            return
        providers = self._detected_vcs_providers(root)
        if not providers:
            QMessageBox.information(self, "Create Changelist", "No Git or Perforce provider detected for this project.")
            return

        provider_files = {}
        for provider in providers:
            try:
                provider_files[provider.kind] = provider.changed_files(root)
            except Exception as exc:
                provider_files[provider.kind] = [{"path": f"Unable to query changes: {exc}", "status": "error", "source": "error"}]

        dialog = QDialog(self)
        dialog.setWindowTitle("Create Changelist from Updated Files")
        dialog.resize(820, 620)
        layout = QVBoxLayout(dialog)
        title = QLabel("Create Changelist from Updated Files")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        description_edit = QLineEdit()
        description_edit.setPlaceholderText("Description")
        layout.addWidget(description_edit)

        provider_checks = {}
        if len(providers) > 1:
            provider_row = QHBoxLayout()
            provider_row.addWidget(QLabel("Create in:"))
            for provider in providers:
                checkbox = QCheckBox(provider.kind.title())
                checkbox.setChecked(True)
                provider_checks[provider.kind] = checkbox
                provider_row.addWidget(checkbox)
            provider_row.addStretch(1)
            layout.addLayout(provider_row)
        else:
            provider_checks[providers[0].kind] = None

        tree = QTreeWidget()
        tree.setHeaderLabels(["Provider / File", "Status", "Source"])
        tree.setColumnWidth(0, 480)
        provider_nodes = {}
        for provider in providers:
            files = provider_files.get(provider.kind, [])
            parent = QTreeWidgetItem([f"{provider.kind.title()} ({len(files)} updated)", "", ""])
            parent.setFlags(parent.flags() | Qt.ItemIsUserCheckable)
            parent.setCheckState(0, Qt.Checked)
            parent.setData(0, Qt.UserRole, {"provider": provider.kind, "path": ""})
            tree.addTopLevelItem(parent)
            provider_nodes[provider.kind] = parent
            for item in files:
                child = QTreeWidgetItem([
                    item.get("path", ""),
                    item.get("status", ""),
                    item.get("source", ""),
                ])
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked if item.get("status") != "error" else Qt.Unchecked)
                child.setData(0, Qt.UserRole, {"provider": provider.kind, "path": item.get("path", "")})
                parent.addChild(child)
            parent.setExpanded(True)
        layout.addWidget(tree, 1)

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumHeight(120)
        output.setPlainText("Select providers and files, then create the changelist.")
        layout.addWidget(output)

        def sync_children(item, column):
            if column != 0 or item.parent() is not None:
                return
            state = item.checkState(0)
            for idx in range(item.childCount()):
                item.child(idx).setCheckState(0, state)

        tree.itemChanged.connect(sync_children)

        def selected_files_for(kind):
            parent = provider_nodes.get(kind)
            if not parent or parent.checkState(0) != Qt.Checked:
                return []
            selected = []
            for idx in range(parent.childCount()):
                child = parent.child(idx)
                data = child.data(0, Qt.UserRole) or {}
                path_text = data.get("path", "")
                if child.checkState(0) == Qt.Checked and path_text and not path_text.startswith("Unable to query changes:"):
                    selected.append(path_text)
            return selected

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        create_btn = QPushButton("Create")
        cancel_btn = QPushButton("Cancel")
        buttons.addWidget(create_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        def create_selected():
            description = description_edit.text().strip() or "Tech Connector changelist"
            results = []
            any_created = False
            for provider in providers:
                checkbox = provider_checks.get(provider.kind)
                if checkbox is not None and not checkbox.isChecked():
                    continue
                files = selected_files_for(provider.kind)
                if not files:
                    results.append(f"{provider.kind.upper()}: no files selected.")
                    continue
                ok, msg, payload = provider.create_changelist(root, description, files)
                any_created = any_created or ok
                results.append(f"{provider.kind.upper()}: {'OK' if ok else 'Failed'} - {msg}")
                if payload.get("path"):
                    results.append(f"  {payload['path']}")
            output.setPlainText("\n".join(results) or "No provider selected.")
            if any_created:
                self.append("\n[VCS] Created changelist(s):\n" + "\n".join(results) + "\n")
                self.update_vcs_status_card()

        create_btn.clicked.connect(create_selected)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def _vcs_account_hint(self, kind=None):
        from tech_connector.services.connected_account_service import connected_account_status

        if kind in (None, "git"):
            github = connected_account_status(self.settings, "github")
            if github.get("connected"):
                return f"GitHub: {github.get('mode')}"
        if kind in (None, "perforce"):
            perforce = connected_account_status(self.settings, "perforce")
            if perforce.get("connected"):
                return f"P4: {perforce.get('mode')}"
        return ""

    def open_google_key_page(self):
        QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey"))

    def show_vcs_accounts_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("VCS Accounts")
        dialog.resize(750, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("GitHub and Perforce Accounts")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        note = QLabel(
            "These credentials are stored in Tech Connector settings and applied to this app process for GitHub API/repo ingest and Perforce commands."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        github_title = QLabel("GitHub")
        github_title.setStyleSheet(
            "font-weight: bold; color: #64b5f6; margin-top: 8px;"
        )
        layout.addWidget(github_title)

        def make_row(label_text, widget, extra_widgets=None):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setMinimumWidth(110)
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            if extra_widgets:
                for w in extra_widgets:
                    row.addWidget(w)
            return row

        # GitHub Username
        github_user_edit = QLineEdit()
        github_user_edit.setText(self.settings.get("github_username", ""))
        github_user_edit.setPlaceholderText("GitHub username")
        layout.addLayout(make_row("Username:", github_user_edit))

        # GitHub Token
        github_token_edit = QLineEdit()
        github_token_edit.setEchoMode(QLineEdit.Password)
        github_token_edit.setText(self.settings.get("github_token", ""))
        github_token_edit.setPlaceholderText("Fine-grained or classic GitHub token")
        
        github_login_btn = QPushButton("GitHub Login")
        import_gh_token_btn = QPushButton("Import gh Token")
        open_github_token_btn = QPushButton("Create Token")
        open_github_token_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/settings/tokens"))
        )
        layout.addLayout(make_row("Token:", github_token_edit, [github_login_btn, import_gh_token_btn, open_github_token_btn]))

        p4_title = QLabel("Perforce")
        p4_title.setStyleSheet("font-weight: bold; color: #64b5f6; margin-top: 8px;")
        layout.addWidget(p4_title)

        # Perforce P4PORT
        p4_port_edit = QLineEdit()
        p4_port_edit.setText(self.settings.get("p4_port", ""))
        p4_port_edit.setPlaceholderText("ssl:perforce.example.com:1666")
        layout.addLayout(make_row("P4PORT:", p4_port_edit))

        # Perforce P4USER
        p4_user_edit = QComboBox()
        p4_user_edit.setEditable(True)
        p4_user_edit.setEditText(self.settings.get("p4_user", ""))
        load_p4_users_btn = QPushButton("Load Users")
        layout.addLayout(make_row("P4USER:", p4_user_edit, [load_p4_users_btn]))

        # Perforce P4CLIENT
        p4_client_edit = QComboBox()
        p4_client_edit.setEditable(True)
        p4_client_edit.setEditText(self.settings.get("p4_client", ""))
        load_p4_clients_btn = QPushButton("Load Workspaces")
        layout.addLayout(make_row("P4CLIENT:", p4_client_edit, [load_p4_clients_btn]))

        # Perforce Password/Ticket
        p4_pass_edit = QLineEdit()
        p4_pass_edit.setEchoMode(QLineEdit.Password)
        p4_pass_edit.setText(self.settings.get("p4_passwd", ""))
        p4_pass_edit.setPlaceholderText("Optional; p4 login tickets also work")
        layout.addLayout(make_row("Password/Ticket:", p4_pass_edit))

        status_box = QPlainTextEdit()
        status_box.setReadOnly(True)
        status_box.setMaximumHeight(120)
        status_box.setPlainText(
            "Use Test GitHub or Test Perforce to verify credentials."
        )
        layout.addWidget(status_box)

        def account_status_text(data):
            from tech_connector.services.connected_account_service import connected_account_status

            rows = [
                connected_account_status(data, "github"),
                connected_account_status(data, "perforce"),
            ]
            return "\n".join(row["summary"] for row in rows)

        status_box.setPlainText(account_status_text(self.settings))

        def pending_settings():
            data = dict(self.settings)
            data["github_username"] = github_user_edit.text().strip()
            data["github_token"] = github_token_edit.text().strip()
            data["p4_port"] = p4_port_edit.text().strip()
            data["p4_user"] = p4_user_edit.currentText().strip()
            data["p4_client"] = p4_client_edit.currentText().strip()
            data["p4_passwd"] = p4_pass_edit.text().strip()
            return data

        def replace_combo_items(combo, values, selected=""):
            selected = (selected or combo.currentText() or "").strip()
            combo.blockSignals(True)
            combo.clear()
            for value in values:
                combo.addItem(value)
            if selected:
                idx = combo.findText(selected)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    combo.setEditText(selected)
            combo.blockSignals(False)

        def github_login():
            from tech_connector.services.version_control_service import launch_github_cli_login

            ok, msg = launch_github_cli_login()
            status_box.setPlainText(("OK: " if ok else "Failed: ") + msg)

        def import_gh_token():
            from tech_connector.services.version_control_service import (
                github_token_from_cli,
                github_user_from_cli,
            )

            ok, token, msg = github_token_from_cli()
            status_lines = [("OK: " if ok else "Failed: ") + msg]
            if ok:
                github_token_edit.setText(token)
                user_ok, user, user_msg = github_user_from_cli()
                status_lines.append(("OK: " if user_ok else "Note: ") + user_msg)
                if user_ok:
                    github_user_edit.setText(user)
            status_box.setPlainText("\n".join(status_lines))

        def load_p4_users():
            from tech_connector.services.version_control_service import list_perforce_users

            active = self.settings.get("active_project", "") or "."
            ok, users, msg = list_perforce_users(pending_settings(), Path(active))
            if ok:
                replace_combo_items(p4_user_edit, users, p4_user_edit.currentText())
            status_box.setPlainText(("OK: " if ok else "Failed: ") + msg)

        def load_p4_clients():
            from tech_connector.services.version_control_service import list_perforce_clients

            active = self.settings.get("active_project", "") or "."
            ok, clients, msg = list_perforce_clients(
                pending_settings(),
                user=p4_user_edit.currentText().strip(),
                cwd=Path(active),
            )
            if ok:
                replace_combo_items(
                    p4_client_edit, clients, p4_client_edit.currentText()
                )
            status_box.setPlainText(("OK: " if ok else "Failed: ") + msg)

        def test_github():
            from tech_connector.services.version_control_service import test_github_credentials

            ok, msg = test_github_credentials(github_token_edit.text().strip())
            status_box.setPlainText(("OK: " if ok else "Failed: ") + msg)

        def test_perforce():
            from tech_connector.services.version_control_service import test_perforce_credentials

            active = self.settings.get("active_project", "") or "."
            ok, msg = test_perforce_credentials(pending_settings(), Path(active))
            status_box.setPlainText(("OK:\n" if ok else "Failed:\n") + msg)

        github_login_btn.clicked.connect(github_login)
        import_gh_token_btn.clicked.connect(import_gh_token)
        load_p4_users_btn.clicked.connect(load_p4_users)
        load_p4_clients_btn.clicked.connect(load_p4_clients)
        p4_port_edit.editingFinished.connect(load_p4_users)
        p4_user_edit.activated.connect(lambda _index: load_p4_clients())
        p4_user_edit.currentTextChanged.connect(lambda _text: p4_client_edit.clear())

        tests_row = QHBoxLayout()
        test_github_btn = QPushButton("Test GitHub")
        test_github_btn.clicked.connect(test_github)
        test_p4_btn = QPushButton("Test Perforce")
        test_p4_btn.clicked.connect(test_perforce)
        tests_row.addWidget(test_github_btn)
        tests_row.addWidget(test_p4_btn)
        tests_row.addStretch(1)
        layout.addLayout(tests_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        def save_vcs_settings():
            self.settings.update(pending_settings())
            self.service.save_settings(self.settings)
            try:
                from tech_connector.services.version_control_service import apply_vcs_settings

                apply_vcs_settings(self.settings)
            except Exception:
                pass
            self.update_vcs_status_card()
            self.append("\n[VCS] Saved GitHub/Perforce account settings.\n" + account_status_text(self.settings) + "\n")
            dialog.accept()

        save_btn.clicked.connect(save_vcs_settings)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def show_github_login_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("GitHub Login")
        dialog.resize(680, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("GitHub Login")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)
        note = QLabel(
            "Used for GitHub API access, repository search/ingest, and Git-backed workflow features. Use GitHub CLI if installed, or paste a fine-grained token."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        user_row = QHBoxLayout()
        user_row.addWidget(QLabel("Username:"))
        username_edit = QLineEdit()
        username_edit.setText(self.settings.get("github_username", ""))
        username_edit.setPlaceholderText("GitHub username")
        user_row.addWidget(username_edit, 1)
        layout.addLayout(user_row)

        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Token:"))
        token_edit = QLineEdit()
        token_edit.setEchoMode(QLineEdit.Password)
        token_edit.setText(self.settings.get("github_token", ""))
        token_edit.setPlaceholderText("Fine-grained or classic GitHub token")
        token_row.addWidget(token_edit, 1)
        layout.addLayout(token_row)

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumHeight(110)
        output.setPlainText("Use GitHub CLI login, import an existing gh token, paste a token, or test the saved token.")
        layout.addWidget(output)

        def save_settings():
            self.settings["github_username"] = username_edit.text().strip()
            self.settings["github_token"] = token_edit.text().strip()
            self.service.save_settings(self.settings)
            try:
                from tech_connector.services.version_control_service import apply_vcs_settings
                apply_vcs_settings(self.settings)
            except Exception:
                pass
            self.update_vcs_status_card()
            self.set_card("github", "ok" if self.settings.get("github_token") else "unknown", self.settings.get("github_username") or "Token saved")
            output.setPlainText("GitHub settings saved.")

        def github_cli_login():
            from tech_connector.services.version_control_service import launch_github_cli_login
            ok, msg = launch_github_cli_login()
            output.setPlainText(("OK: " if ok else "Failed: ") + msg)

        def import_gh_token():
            from tech_connector.services.version_control_service import github_token_from_cli, github_user_from_cli
            ok, token, msg = github_token_from_cli()
            lines = [("OK: " if ok else "Failed: ") + msg]
            if ok:
                token_edit.setText(token)
                user_ok, user, user_msg = github_user_from_cli()
                lines.append(("OK: " if user_ok else "Note: ") + user_msg)
                if user_ok:
                    username_edit.setText(user)
                save_settings()
            output.setPlainText("\n".join(lines))

        def test_token():
            from tech_connector.services.version_control_service import test_github_credentials
            ok, msg = test_github_credentials(token_edit.text().strip())
            output.setPlainText(("OK: " if ok else "Failed: ") + msg)
            self.set_card("github", "ok" if ok else "bad", msg.replace("GitHub ", ""))

        actions = QHBoxLayout()
        cli_btn = QPushButton("GitHub CLI Login")
        import_btn = QPushButton("Import gh Token")
        token_btn = QPushButton("Create Token")
        test_btn = QPushButton("Test GitHub")
        cli_btn.clicked.connect(github_cli_login)
        import_btn.clicked.connect(import_gh_token)
        token_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/settings/tokens")))
        test_btn.clicked.connect(test_token)
        actions.addWidget(cli_btn)
        actions.addWidget(import_btn)
        actions.addWidget(token_btn)
        actions.addWidget(test_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("Save")
        close_btn = QPushButton("Close")
        save_btn.clicked.connect(save_settings)
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def show_slack_login_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Slack Login")
        dialog.resize(720, 420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Slack Login")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)
        note = QLabel("Configure Slack output and live channel/user lookup. Webhooks send messages; bot tokens enable @channel and @user discovery.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        enabled = QCheckBox("Enable Slack output")
        enabled.setChecked(bool(self.settings.get("notify_slack_enabled", False)))
        layout.addWidget(enabled)

        webhook_row = QHBoxLayout()
        webhook_row.addWidget(QLabel("Webhook:"))
        webhook_edit = QLineEdit()
        webhook_edit.setEchoMode(QLineEdit.Password)
        webhook_edit.setText(self.settings.get("slack_webhook_url", ""))
        webhook_edit.setPlaceholderText("https://hooks.slack.com/services/...")
        webhook_row.addWidget(webhook_edit, 1)
        layout.addLayout(webhook_row)

        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Bot token:"))
        token_edit = QLineEdit()
        token_edit.setEchoMode(QLineEdit.Password)
        token_edit.setText(self.settings.get("slack_bot_token", ""))
        token_edit.setPlaceholderText("xoxb-... with conversations:read/users:read")
        token_row.addWidget(token_edit, 1)
        token_row.addWidget(QLabel("Default channel:"))
        default_edit = QLineEdit()
        default_edit.setMaximumWidth(180)
        default_edit.setText(self.settings.get("slack_default_channel", ""))
        token_row.addWidget(default_edit)
        layout.addLayout(token_row)

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumHeight(120)
        output.setPlainText("Save, load live names, or send a test Slack output.")
        layout.addWidget(output)

        def save_settings():
            self.settings["notify_slack_enabled"] = enabled.isChecked()
            self.settings["slack_webhook_url"] = webhook_edit.text().strip()
            self.settings["slack_bot_token"] = token_edit.text().strip()
            self.settings["slack_default_channel"] = default_edit.text().strip()
            self.service.save_settings(self.settings)
            self.set_card("slack", "ok" if (self.settings.get("slack_bot_token") or self.settings.get("slack_webhook_url")) else "unknown", self.settings.get("slack_default_channel") or "Configured")
            output.setPlainText("Slack settings saved.")

        def load_live_names():
            save_settings()
            from tech_connector.services.notification_service import fetch_slack_channels_and_users
            ok, data, msg = fetch_slack_channels_and_users(self.settings)
            if ok:
                self.settings["slack_channels"] = data.get("channels", [])
                self.settings["slack_users"] = data.get("users", [])
                self.service.save_settings(self.settings)
            output.setPlainText(("OK: " if ok else "Failed: ") + msg)
            self.set_card("slack", "ok" if ok else "bad", msg)

        def send_test():
            save_settings()
            from tech_connector.services.notification_service import send_slack_webhook
            ok, msg = send_slack_webhook(webhook_edit.text().strip(), "Tech Connector Slack test output")
            output.setPlainText(("OK: " if ok else "Failed: ") + msg)
            self.set_card("slack", "ok" if ok else "bad", "Webhook test")

        actions = QHBoxLayout()
        test_btn = QPushButton("Send Test")
        live_btn = QPushButton("Load Live Names")
        app_btn = QPushButton("Create Slack App")
        test_btn.clicked.connect(send_test)
        live_btn.clicked.connect(load_live_names)
        app_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://api.slack.com/apps")))
        actions.addWidget(test_btn)
        actions.addWidget(live_btn)
        actions.addWidget(app_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("Save")
        close_btn = QPushButton("Close")
        save_btn.clicked.connect(save_settings)
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def show_discord_login_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Discord Login")
        dialog.resize(720, 460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Discord Login")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)
        note = QLabel("Configure Discord output and live guild channel/user lookup. Webhooks send messages; bot tokens enable live @channel and @user discovery.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        enabled = QCheckBox("Enable Discord output")
        enabled.setChecked(bool(self.settings.get("notify_discord_enabled", False)))
        layout.addWidget(enabled)

        webhook_row = QHBoxLayout()
        webhook_row.addWidget(QLabel("Webhook:"))
        webhook_edit = QLineEdit()
        webhook_edit.setEchoMode(QLineEdit.Password)
        webhook_edit.setText(self.settings.get("discord_webhook_url", ""))
        webhook_edit.setPlaceholderText("https://discord.com/api/webhooks/...")
        webhook_row.addWidget(webhook_edit, 1)
        webhook_row.addWidget(QLabel("Name:"))
        name_edit = QLineEdit()
        name_edit.setMaximumWidth(150)
        name_edit.setText(self.settings.get("discord_username", "Tech Connector"))
        webhook_row.addWidget(name_edit)
        layout.addLayout(webhook_row)

        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Bot token:"))
        token_edit = QLineEdit()
        token_edit.setEchoMode(QLineEdit.Password)
        token_edit.setText(self.settings.get("discord_bot_token", ""))
        token_edit.setPlaceholderText("Discord bot token")
        token_row.addWidget(token_edit, 1)
        token_row.addWidget(QLabel("Guild ID:"))
        guild_edit = QLineEdit()
        guild_edit.setMaximumWidth(180)
        guild_edit.setText(self.settings.get("discord_guild_id", ""))
        token_row.addWidget(guild_edit)
        layout.addLayout(token_row)

        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("Default channel:"))
        default_edit = QLineEdit()
        default_edit.setText(self.settings.get("discord_default_channel", ""))
        default_row.addWidget(default_edit, 1)
        layout.addLayout(default_row)

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumHeight(120)
        output.setPlainText("Save, load live names, or send a test Discord output.")
        layout.addWidget(output)

        def save_settings():
            self.settings["notify_discord_enabled"] = enabled.isChecked()
            self.settings["discord_webhook_url"] = webhook_edit.text().strip()
            self.settings["discord_username"] = name_edit.text().strip() or "Tech Connector"
            self.settings["discord_bot_token"] = token_edit.text().strip()
            self.settings["discord_guild_id"] = guild_edit.text().strip()
            self.settings["discord_default_channel"] = default_edit.text().strip()
            self.service.save_settings(self.settings)
            self.set_card("discord", "ok" if (self.settings.get("discord_bot_token") or self.settings.get("discord_webhook_url")) else "unknown", self.settings.get("discord_default_channel") or "Configured")
            output.setPlainText("Discord settings saved.")

        def load_live_names():
            save_settings()
            from tech_connector.services.notification_service import fetch_discord_channels_and_users
            ok, data, msg = fetch_discord_channels_and_users(self.settings)
            if ok:
                self.settings["discord_channels"] = data.get("channels", [])
                self.settings["discord_users"] = data.get("users", [])
                self.service.save_settings(self.settings)
            output.setPlainText(("OK: " if ok else "Failed: ") + msg)
            self.set_card("discord", "ok" if ok else "bad", msg)

        def send_test():
            save_settings()
            from tech_connector.services.notification_service import send_discord_webhook
            ok, msg = send_discord_webhook(webhook_edit.text().strip(), "Tech Connector Discord test output", username=name_edit.text().strip() or "Tech Connector")
            output.setPlainText(("OK: " if ok else "Failed: ") + msg)
            self.set_card("discord", "ok" if ok else "bad", "Webhook test")

        actions = QHBoxLayout()
        test_btn = QPushButton("Send Test")
        live_btn = QPushButton("Load Live Names")
        app_btn = QPushButton("Developer Portal")
        test_btn.clicked.connect(send_test)
        live_btn.clicked.connect(load_live_names)
        app_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://discord.com/developers/applications")))
        actions.addWidget(test_btn)
        actions.addWidget(live_btn)
        actions.addWidget(app_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("Save")
        close_btn = QPushButton("Close")
        save_btn.clicked.connect(save_settings)
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        dialog.exec()

    def show_add_integration_package_dialog(self):
        from tech_connector.services.integration_package_service import (
            PACKAGE_TYPES,
            build_package_manifest,
            create_integration_package,
            format_integration_plan_card,
            load_integration_packages,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Add Integration Package")
        dialog.resize(820, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Add Integration Package")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        note = QLabel(
            "Create a controlled package for a DCC, communication portal, design board, storage system, devops service, or custom/internal app. The package starts as discovered only; live actions stay disabled until configured and validated."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        form_row = QHBoxLayout()
        form_row.addWidget(QLabel("Name:"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Miro, Microsoft Teams, Houdini, internal review API")
        form_row.addWidget(name_edit, 1)
        form_row.addWidget(QLabel("Type:"))
        type_box = QComboBox()
        type_keys = list(PACKAGE_TYPES.keys())
        for key in type_keys:
            spec = PACKAGE_TYPES[key]
            examples = ", ".join(spec.get("examples", [])[:3])
            type_box.addItem(f"{spec['label']} ({examples})", key)
        form_row.addWidget(type_box, 1)
        layout.addLayout(form_row)

        description_edit = QLineEdit()
        description_edit.setPlaceholderText("What should Tech Connector eventually do with this integration?")
        layout.addWidget(description_edit)

        source_edit = QLineEdit()
        source_edit.setPlaceholderText("Optional official docs/API URL")
        layout.addWidget(source_edit)

        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setMinimumHeight(220)
        layout.addWidget(preview, 1)

        existing = load_integration_packages()
        existing_label = QLabel(
            f"Existing packages: {len(existing)}"
            + (f" ({', '.join(pkg.get('name', pkg.get('id', '')) for pkg in existing[:5])})" if existing else "")
        )
        existing_label.setWordWrap(True)
        existing_label.setStyleSheet("color: #8fb9c9; font-size: 11px;")
        layout.addWidget(existing_label)

        def current_manifest():
            return build_package_manifest(
                name_edit.text().strip() or "New Integration",
                type_box.currentData() or "custom",
                description_edit.text().strip(),
                source_edit.text().strip(),
            )

        def refresh_preview():
            manifest = current_manifest()
            preview.setPlainText(
                format_integration_plan_card(manifest).replace("**", "").replace("`", "")
            )

        name_edit.textChanged.connect(refresh_preview)
        type_box.currentIndexChanged.connect(refresh_preview)
        description_edit.textChanged.connect(refresh_preview)
        source_edit.textChanged.connect(refresh_preview)
        refresh_preview()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        create_btn = QPushButton("Create Package")
        cancel_btn = QPushButton("Cancel")
        buttons.addWidget(create_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        def create_package():
            name = name_edit.text().strip()
            if not name:
                QMessageBox.information(dialog, "Name Required", "Enter an integration name first.")
                return

            manifest = current_manifest()
            review_card = (
                "**Operation Review: Add Integration Package**\n\n"
                f"Intent: create a scaffold for **{manifest.get('name')}**.\n\n"
                f"Type: {manifest.get('type_label')}.\n\n"
                "Plan: create package folders, write `package.json`, add knowledge/bridge/prompt/test placeholders, keep all live actions disabled until configuration and validation.\n\n"
                "Risk: low. This only writes new scaffold files under `integration_packages/`."
            )
            if hasattr(self, "append"):
                self.append("\n" + review_card + "\n")

            ok, msg, payload = create_integration_package(
                name,
                type_box.currentData() or "custom",
                description_edit.text().strip(),
                source_edit.text().strip(),
            )
            if ok:
                if hasattr(self, "append"):
                    self.append("\n" + format_integration_plan_card(payload, payload.get("path", "")) + "\n")
                if hasattr(self, "update_integrations_status_card"):
                    self.update_integrations_status_card()
                QMessageBox.information(dialog, "Integration Package Created", msg)
                dialog.accept()
            else:
                QMessageBox.warning(dialog, "Integration Package", msg)

        create_btn.clicked.connect(create_package)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def show_backend_log_dialog(self):
        from tech_connector.services.diagnostic_service import clear_backend_log, read_backend_log

        dialog = QDialog(self)
        dialog.setWindowTitle("Backend Operation Log")
        dialog.resize(900, 640)
        layout = QVBoxLayout(dialog)
        title = QLabel("Backend Operation Log")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        note = QLabel(
            "Shows backend commands, bridge setup attempts, return codes, stdout/stderr, and captured errors. This is intentionally more verbose than chat."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        log_view = QPlainTextEdit()
        log_view.setReadOnly(True)
        layout.addWidget(log_view, 1)

        def refresh():
            log_view.setPlainText(read_backend_log(limit=400))
            cursor = log_view.textCursor()
            cursor.movePosition(QTextCursor.End)
            log_view.setTextCursor(cursor)

        def clear():
            clear_backend_log()
            refresh()

        buttons = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        clear_btn = QPushButton("Clear")
        close_btn = QPushButton("Close")
        refresh_btn.clicked.connect(refresh)
        clear_btn.clicked.connect(clear)
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(refresh_btn)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        refresh()
        dialog.exec()

    def show_notification_outputs_dialog(self):
        from tech_connector.services.notification_service import send_pipeline_output

        dialog = QDialog(self)
        dialog.setWindowTitle("Notification Outputs")
        dialog.resize(780, 680)
        layout = QVBoxLayout(dialog)

        title = QLabel("Notification Outputs")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        note = QLabel(
            "Route pipeline output to Slack, Discord, or email. Webhooks send output; bot/API tokens let Tech Connector load live channel and user names for @mentions."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        slack_enabled = QCheckBox("Enable Slack output")
        slack_enabled.setChecked(bool(self.settings.get("notify_slack_enabled", False)))
        layout.addWidget(slack_enabled)

        slack_row = QHBoxLayout()
        slack_row.addWidget(QLabel("Slack webhook:"))
        slack_webhook_edit = QLineEdit()
        slack_webhook_edit.setEchoMode(QLineEdit.Password)
        slack_webhook_edit.setText(self.settings.get("slack_webhook_url", ""))
        slack_webhook_edit.setPlaceholderText("https://hooks.slack.com/services/...")
        slack_row.addWidget(slack_webhook_edit, 1)
        layout.addLayout(slack_row)

        slack_api_row = QHBoxLayout()
        slack_api_row.addWidget(QLabel("Slack bot token:"))
        slack_token_edit = QLineEdit()
        slack_token_edit.setEchoMode(QLineEdit.Password)
        slack_token_edit.setText(self.settings.get("slack_bot_token", ""))
        slack_token_edit.setPlaceholderText("xoxb-... for live channels/users")
        slack_api_row.addWidget(slack_token_edit, 1)
        slack_api_row.addWidget(QLabel("Default channel:"))
        slack_default_edit = QLineEdit()
        slack_default_edit.setMaximumWidth(160)
        slack_default_edit.setText(self.settings.get("slack_default_channel", ""))
        slack_api_row.addWidget(slack_default_edit)
        layout.addLayout(slack_api_row)

        discord_enabled = QCheckBox("Enable Discord output")
        discord_enabled.setChecked(bool(self.settings.get("notify_discord_enabled", False)))
        layout.addWidget(discord_enabled)

        discord_row = QHBoxLayout()
        discord_row.addWidget(QLabel("Discord webhook:"))
        discord_webhook_edit = QLineEdit()
        discord_webhook_edit.setEchoMode(QLineEdit.Password)
        discord_webhook_edit.setText(self.settings.get("discord_webhook_url", ""))
        discord_webhook_edit.setPlaceholderText("https://discord.com/api/webhooks/...")
        discord_row.addWidget(discord_webhook_edit, 1)
        discord_row.addWidget(QLabel("Name:"))
        discord_name_edit = QLineEdit()
        discord_name_edit.setMaximumWidth(140)
        discord_name_edit.setText(self.settings.get("discord_username", "Tech Connector"))
        discord_row.addWidget(discord_name_edit)
        layout.addLayout(discord_row)

        discord_api_row = QHBoxLayout()
        discord_api_row.addWidget(QLabel("Discord bot token:"))
        discord_token_edit = QLineEdit()
        discord_token_edit.setEchoMode(QLineEdit.Password)
        discord_token_edit.setText(self.settings.get("discord_bot_token", ""))
        discord_token_edit.setPlaceholderText("Bot token for live guild data")
        discord_api_row.addWidget(discord_token_edit, 1)
        discord_api_row.addWidget(QLabel("Guild ID:"))
        discord_guild_edit = QLineEdit()
        discord_guild_edit.setMaximumWidth(180)
        discord_guild_edit.setText(self.settings.get("discord_guild_id", ""))
        discord_api_row.addWidget(discord_guild_edit)
        discord_api_row.addWidget(QLabel("Default:"))
        discord_default_edit = QLineEdit()
        discord_default_edit.setMaximumWidth(150)
        discord_default_edit.setText(self.settings.get("discord_default_channel", ""))
        discord_api_row.addWidget(discord_default_edit)
        layout.addLayout(discord_api_row)

        email_enabled = QCheckBox("Enable email output")
        email_enabled.setChecked(bool(self.settings.get("notify_email_enabled", False)))
        layout.addWidget(email_enabled)

        smtp_row = QHBoxLayout()
        smtp_row.addWidget(QLabel("SMTP host:"))
        smtp_host_edit = QLineEdit()
        smtp_host_edit.setText(self.settings.get("email_smtp_host", "smtp.gmail.com"))
        smtp_row.addWidget(smtp_host_edit, 1)
        smtp_row.addWidget(QLabel("Port:"))
        smtp_port_edit = QLineEdit()
        smtp_port_edit.setMaximumWidth(70)
        smtp_port_edit.setText(str(self.settings.get("email_smtp_port", 587)))
        smtp_row.addWidget(smtp_port_edit)
        layout.addLayout(smtp_row)

        auth_row = QHBoxLayout()
        auth_row.addWidget(QLabel("Username:"))
        email_user_edit = QLineEdit()
        email_user_edit.setText(self.settings.get("email_username", ""))
        auth_row.addWidget(email_user_edit, 1)
        auth_row.addWidget(QLabel("Password/token:"))
        email_password_edit = QLineEdit()
        email_password_edit.setEchoMode(QLineEdit.Password)
        email_password_edit.setText(self.settings.get("email_password", ""))
        auth_row.addWidget(email_password_edit, 1)
        layout.addLayout(auth_row)

        address_row = QHBoxLayout()
        address_row.addWidget(QLabel("From:"))
        email_from_edit = QLineEdit()
        email_from_edit.setText(self.settings.get("email_from", ""))
        email_from_edit.setPlaceholderText("Defaults to username")
        address_row.addWidget(email_from_edit, 1)
        address_row.addWidget(QLabel("To:"))
        email_to_edit = QLineEdit()
        email_to_edit.setText(self.settings.get("email_to", ""))
        email_to_edit.setPlaceholderText("one@example.com, two@example.com")
        address_row.addWidget(email_to_edit, 1)
        layout.addLayout(address_row)

        tls_row = QHBoxLayout()
        email_tls_checkbox = QCheckBox("STARTTLS")
        email_tls_checkbox.setChecked(bool(self.settings.get("email_use_tls", True)))
        email_ssl_checkbox = QCheckBox("SSL")
        email_ssl_checkbox.setChecked(bool(self.settings.get("email_use_ssl", False)))
        tls_row.addWidget(email_tls_checkbox)
        tls_row.addWidget(email_ssl_checkbox)
        tls_row.addStretch(1)
        layout.addLayout(tls_row)

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumHeight(140)
        output.setPlainText("Save settings or send a test notification.")
        layout.addWidget(output)

        def pending_settings():
            data = dict(self.settings)
            data["notify_slack_enabled"] = slack_enabled.isChecked()
            data["slack_webhook_url"] = slack_webhook_edit.text().strip()
            data["slack_bot_token"] = slack_token_edit.text().strip()
            data["slack_default_channel"] = slack_default_edit.text().strip()
            data["notify_discord_enabled"] = discord_enabled.isChecked()
            data["discord_webhook_url"] = discord_webhook_edit.text().strip()
            data["discord_username"] = discord_name_edit.text().strip() or "Tech Connector"
            data["discord_bot_token"] = discord_token_edit.text().strip()
            data["discord_guild_id"] = discord_guild_edit.text().strip()
            data["discord_default_channel"] = discord_default_edit.text().strip()
            data["notify_email_enabled"] = email_enabled.isChecked()
            data["email_smtp_host"] = smtp_host_edit.text().strip()
            try:
                data["email_smtp_port"] = int(smtp_port_edit.text().strip() or 587)
            except ValueError:
                data["email_smtp_port"] = 587
            data["email_username"] = email_user_edit.text().strip()
            data["email_password"] = email_password_edit.text()
            data["email_from"] = email_from_edit.text().strip()
            data["email_to"] = email_to_edit.text().strip()
            data["email_use_tls"] = email_tls_checkbox.isChecked()
            data["email_use_ssl"] = email_ssl_checkbox.isChecked()
            return data

        def save_settings():
            self.settings.update(pending_settings())
            self.service.save_settings(self.settings)
            from tech_connector.services.connected_account_service import connected_account_status

            rows = [
                connected_account_status(self.settings, "slack"),
                connected_account_status(self.settings, "discord"),
                connected_account_status(self.settings, "email"),
            ]
            output.setPlainText("Notification output settings saved.\n" + "\n".join(row["summary"] for row in rows))

        def load_live_names():
            save_settings()
            from tech_connector.services.notification_service import (
                fetch_discord_channels_and_users,
                fetch_slack_channels_and_users,
            )

            lines = []
            slack_ok, slack_data, slack_msg = fetch_slack_channels_and_users(self.settings)
            if slack_ok:
                self.settings["slack_channels"] = slack_data.get("channels", [])
                self.settings["slack_users"] = slack_data.get("users", [])
            lines.append(("OK: " if slack_ok else "Failed: ") + slack_msg)
            discord_ok, discord_data, discord_msg = fetch_discord_channels_and_users(self.settings)
            if discord_ok:
                self.settings["discord_channels"] = discord_data.get("channels", [])
                self.settings["discord_users"] = discord_data.get("users", [])
            lines.append(("OK: " if discord_ok else "Failed: ") + discord_msg)
            self.service.save_settings(self.settings)
            output.setPlainText("\n".join(lines))

        def send_test():
            save_settings()
            results = send_pipeline_output(
                self.settings,
                "Tech Connector Test Pipeline Output",
                "This is a test notification from Tech Connector.",
                status="test",
                source="Notification Outputs",
            )
            output.setPlainText(str(results))

        buttons = QHBoxLayout()
        test_btn = QPushButton("Send Test Output")
        load_live_btn = QPushButton("Load Live Names")
        save_btn = QPushButton("Save")
        close_btn = QPushButton("Close")
        test_btn.clicked.connect(send_test)
        load_live_btn.clicked.connect(load_live_names)
        save_btn.clicked.connect(save_settings)
        close_btn.clicked.connect(dialog.accept)
        buttons.addWidget(test_btn)
        buttons.addWidget(load_live_btn)
        buttons.addStretch(1)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        dialog.exec()

    def show_connected_application_status_dialog(self):
        from tech_connector.services.connected_account_service import format_connected_application_status

        dialog = QDialog(self)
        dialog.setWindowTitle("Connected Application Capability Status")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        title = QLabel("Connected Application Capability Status")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)
        output = QPlainTextEdit()
        output.setReadOnly(True)
        layout.addWidget(output, 1)

        def refresh():
            output.setPlainText(format_connected_application_status(self.settings, self.command_router))

        buttons = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        close_btn = QPushButton("Close")
        refresh_btn.clicked.connect(refresh)
        close_btn.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(refresh_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        refresh()
        dialog.exec()

    def show_atlassian_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Atlassian Settings")
        dialog.resize(720, 380)
        layout = QVBoxLayout(dialog)

        title = QLabel("Atlassian Settings")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        note = QLabel(
            "Configure Jira and Confluence Cloud output. Use your Atlassian site URL, account email, and API token."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888888;")
        layout.addWidget(note)

        site_row = QHBoxLayout()
        site_row.addWidget(QLabel("Site URL:"))
        site_edit = QLineEdit()
        site_edit.setText(self.settings.get("atlassian_site_url", ""))
        site_edit.setPlaceholderText("https://your-domain.atlassian.net")
        site_row.addWidget(site_edit, 1)
        layout.addLayout(site_row)

        auth_row = QHBoxLayout()
        auth_row.addWidget(QLabel("Email:"))
        email_edit = QLineEdit()
        email_edit.setText(self.settings.get("atlassian_email", ""))
        auth_row.addWidget(email_edit, 1)
        auth_row.addWidget(QLabel("API token:"))
        token_edit = QLineEdit()
        token_edit.setEchoMode(QLineEdit.Password)
        token_edit.setText(self.settings.get("atlassian_api_token", ""))
        auth_row.addWidget(token_edit, 1)
        layout.addLayout(auth_row)

        defaults_row = QHBoxLayout()
        defaults_row.addWidget(QLabel("Jira project:"))
        jira_project_edit = QLineEdit()
        jira_project_edit.setMaximumWidth(110)
        jira_project_edit.setText(self.settings.get("jira_project_key", ""))
        defaults_row.addWidget(jira_project_edit)
        defaults_row.addWidget(QLabel("Issue type:"))
        issue_type_edit = QLineEdit()
        issue_type_edit.setMaximumWidth(120)
        issue_type_edit.setText(self.settings.get("jira_issue_type", "Task"))
        defaults_row.addWidget(issue_type_edit)
        defaults_row.addWidget(QLabel("Confluence space ID:"))
        space_edit = QLineEdit()
        space_edit.setText(self.settings.get("confluence_space_id", ""))
        defaults_row.addWidget(space_edit, 1)
        layout.addLayout(defaults_row)

        confluence_parent_row = QHBoxLayout()
        confluence_parent_row.addWidget(QLabel("Confluence parent page ID:"))
        parent_edit = QLineEdit()
        parent_edit.setText(self.settings.get("confluence_parent_id", ""))
        parent_edit.setPlaceholderText("Optional")
        confluence_parent_row.addWidget(parent_edit, 1)
        layout.addLayout(confluence_parent_row)

        status = QPlainTextEdit()
        status.setReadOnly(True)
        status.setMaximumHeight(90)
        status.setPlainText("Settings are saved locally in Tech Connector settings.")
        layout.addWidget(status)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save")
        load_live_btn = QPushButton("Load Live Data")
        close_btn = QPushButton("Close")
        buttons.addStretch(1)
        buttons.addWidget(load_live_btn)
        buttons.addWidget(save_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        def save():
            self.settings["atlassian_site_url"] = site_edit.text().strip()
            self.settings["atlassian_email"] = email_edit.text().strip()
            self.settings["atlassian_api_token"] = token_edit.text()
            self.settings["jira_project_key"] = jira_project_edit.text().strip()
            self.settings["jira_issue_type"] = issue_type_edit.text().strip() or "Task"
            self.settings["confluence_space_id"] = space_edit.text().strip()
            self.settings["confluence_parent_id"] = parent_edit.text().strip()
            self.service.save_settings(self.settings)
            from tech_connector.services.connected_account_service import connected_account_status

            status.setPlainText("Atlassian settings saved.\n" + connected_account_status(self.settings, "atlassian")["summary"])

        def load_live_data():
            save()
            from tech_connector.services.atlassian_service import fetch_atlassian_projects_spaces_users

            ok, data, msg = fetch_atlassian_projects_spaces_users(self.settings)
            if ok:
                self.settings["jira_projects"] = data.get("projects", [])
                self.settings["confluence_spaces"] = data.get("spaces", [])
                self.settings["atlassian_users"] = data.get("users", [])
                self.service.save_settings(self.settings)
            status.setPlainText(("OK: " if ok else "Failed: ") + msg)

        save_btn.clicked.connect(save)
        load_live_btn.clicked.connect(load_live_data)
        close_btn.clicked.connect(dialog.accept)
        dialog.exec()

    def _default_documentation_text(self) -> str:
        text = (
            getattr(self, "last_assistant_output", "")
            or getattr(self.service, "last_assistant_output", "")
            or getattr(self, "last_tool_output", "")
            or ""
        )
        path = getattr(self, "current_file_path", "")
        if not text and path and path in getattr(self, "open_editors", {}):
            try:
                text = self.open_editors[path].toPlainText()
            except Exception:
                text = ""
        return text or "Documentation generated by Tech Connector."

    def show_upload_to_confluence_dialog(self, initial_text: str = "", title_hint: str = ""):
        from tech_connector.services.atlassian_service import build_confluence_page_payload, create_confluence_page

        dialog = QDialog(self)
        dialog.setWindowTitle("Upload to Confluence")
        dialog.resize(860, 720)
        layout = QVBoxLayout(dialog)

        title = QLabel("Upload to Confluence")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        spec_row = QHBoxLayout()
        spec_row.addWidget(QLabel("Page title:"))
        page_title_edit = QLineEdit()
        page_title_edit.setText(title_hint or "Tech Connector Documentation")
        spec_row.addWidget(page_title_edit, 1)
        spec_row.addWidget(QLabel("Space ID:"))
        space_edit = QLineEdit()
        space_edit.setMaximumWidth(150)
        space_edit.setText(self.settings.get("confluence_space_id", ""))
        spec_row.addWidget(space_edit)
        layout.addLayout(spec_row)

        parent_row = QHBoxLayout()
        parent_row.addWidget(QLabel("Parent page ID:"))
        parent_edit = QLineEdit()
        parent_edit.setText(self.settings.get("confluence_parent_id", ""))
        parent_edit.setPlaceholderText("Optional")
        parent_row.addWidget(parent_edit, 1)
        layout.addLayout(parent_row)

        body_edit = QPlainTextEdit()
        body_edit.setPlainText(initial_text or self._default_documentation_text())
        layout.addWidget(body_edit, 1)

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumHeight(110)
        output.setPlainText("Review the page specs and content before uploading.")
        layout.addWidget(output)

        buttons = QHBoxLayout()
        settings_btn = QPushButton("Atlassian Settings")
        upload_btn = QPushButton("Upload")
        close_btn = QPushButton("Close")
        settings_btn.clicked.connect(self.show_atlassian_settings_dialog)
        buttons.addWidget(settings_btn)
        buttons.addStretch(1)
        buttons.addWidget(upload_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        def upload():
            self.settings["confluence_space_id"] = space_edit.text().strip()
            self.settings["confluence_parent_id"] = parent_edit.text().strip()
            self.service.save_settings(self.settings)
            payload = build_confluence_page_payload(
                space_edit.text().strip(),
                page_title_edit.text().strip(),
                body_edit.toPlainText(),
                parent_id=parent_edit.text().strip(),
            )
            ok, msg, data = create_confluence_page(self.settings, payload)
            output.setPlainText(("OK: " if ok else "Failed: ") + msg + ("\n" + str(data) if data else ""))
            if hasattr(self, "append"):
                self.append(f"\n[Confluence Upload] {'OK' if ok else 'Failed'}: {msg}\n")

        upload_btn.clicked.connect(upload)
        close_btn.clicked.connect(dialog.accept)
        dialog.exec()

    def show_create_jira_task_from_prompt_dialog(self):
        from tech_connector.services.atlassian_service import build_jira_issue_payload, create_jira_issue

        prompt_text = getattr(self, "last_user_prompt", "") or getattr(self.service, "last_user_prompt", "") or ""
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Jira Task from Prompt")
        dialog.resize(820, 640)
        layout = QVBoxLayout(dialog)

        title = QLabel("Create Jira Task from Prompt")
        title.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(title)

        top = QHBoxLayout()
        top.addWidget(QLabel("Project:"))
        project_edit = QLineEdit()
        project_edit.setMaximumWidth(100)
        project_edit.setText(self.settings.get("jira_project_key", ""))
        top.addWidget(project_edit)
        top.addWidget(QLabel("Issue type:"))
        issue_type_edit = QLineEdit()
        issue_type_edit.setMaximumWidth(120)
        issue_type_edit.setText(self.settings.get("jira_issue_type", "Task"))
        top.addWidget(issue_type_edit)
        top.addWidget(QLabel("Summary:"))
        summary_edit = QLineEdit()
        summary_edit.setText((prompt_text or "Tech Connector task").strip()[:120])
        top.addWidget(summary_edit, 1)
        layout.addLayout(top)

        desc_edit = QPlainTextEdit()
        desc_edit.setPlainText(prompt_text or self._default_documentation_text())
        layout.addWidget(desc_edit, 1)

        output = QPlainTextEdit()
        output.setReadOnly(True)
        output.setMaximumHeight(100)
        output.setPlainText("Review the task details before creating the Jira issue.")
        layout.addWidget(output)

        buttons = QHBoxLayout()
        settings_btn = QPushButton("Atlassian Settings")
        create_btn = QPushButton("Create Jira Task")
        close_btn = QPushButton("Close")
        settings_btn.clicked.connect(self.show_atlassian_settings_dialog)
        buttons.addWidget(settings_btn)
        buttons.addStretch(1)
        buttons.addWidget(create_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        def create():
            self.settings["jira_project_key"] = project_edit.text().strip()
            self.settings["jira_issue_type"] = issue_type_edit.text().strip() or "Task"
            self.service.save_settings(self.settings)
            payload = build_jira_issue_payload(
                project_edit.text().strip(),
                summary_edit.text().strip(),
                desc_edit.toPlainText(),
                issue_type=issue_type_edit.text().strip() or "Task",
                labels=["ai-studio"],
            )
            ok, msg, data = create_jira_issue(self.settings, payload)
            output.setPlainText(("OK: " if ok else "Failed: ") + msg + ("\n" + str(data) if data else ""))
            if hasattr(self, "append"):
                self.append(f"\n[Jira Task] {'OK' if ok else 'Failed'}: {msg}\n")

        create_btn.clicked.connect(create)
        close_btn.clicked.connect(dialog.accept)
        dialog.exec()

    def run_vcs_command_async(self, fn, path_obj, label):
        self.append(f"\n[{label}] Starting...\n")
        self.vcs_worker = VCSWorker(fn, path_obj)

        def on_finished(ok, msg):
            status = "Success" if ok else "Failed"
            self.append(f"\n[{label} - {status}]\n{msg}\n")
            if (
                    "revert" in label.lower()
                    or "edit" in label.lower()
                    or "pull" in label.lower()
                    or "sync" in label.lower()
            ):
                self.refresh_project_tree_fast()
                self.reload_active_tab_if_needed()
            self.update_vcs_status_card()

        self.vcs_worker.finished.connect(on_finished)
        self.vcs_worker.start()

    def run_vcs_command_dialog(self, fn, path_obj, label):
        self.setCursor(Qt.WaitCursor)
        try:
            res = fn(path_obj)
            self.unsetCursor()
            dialog = QMessageBox(self)
            dialog.setWindowTitle(label)
            dialog.setText(f"VCS Command Output for {label}:")
            dialog.setDetailedText(res)
            dialog.setStandardButtons(QMessageBox.Ok)
            dialog.exec()
        except Exception as e:
            self.unsetCursor()
            QMessageBox.critical(self, f"{label} Error", str(e))

    def reload_active_tab_if_needed(self):
        path = self.current_file_path
        if path and path in self.open_editors:
            editor = self.open_editors[path]
            ok, content = self.service.read_file(path)
            if ok:
                cursor = editor.textCursor()
                pos = cursor.position()
                editor.setPlainText(content)
                editor.document().setModified(False)
                cursor.setPosition(min(pos, len(content)))
                editor.setTextCursor(cursor)

    def show_project_tree_context_menu(self, pos):
        item = self.project_tree.itemAt(pos)
        path_str = item.text(1) if item else ""
        target_path = path_str or self.settings.get("active_project", "")
        if not target_path:
            return

        menu = QMenu(self)
        self._project_tree_context_menu = menu
        loading_act = menu.addAction("Checking VCS...")
        loading_act.setEnabled(False)

        def hydrate_vcs_actions():
            started = time.perf_counter()
            menu.clear()
            vcs = self.service.version_control_for_path(target_path)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if elapsed_ms > 80 and hasattr(self, "record_ui_diagnostic_event"):
                self.record_ui_diagnostic_event(
                    "menu_hydrate",
                    {"menu": "project_tree", "section": "vcs_detect", "duration_ms": elapsed_ms},
                )
            if not vcs:
                info_act = menu.addAction("VCS: None detected")
                info_act.setEnabled(False)
                return

            if vcs.kind == "git":
                state = vcs.checkout_state(Path(target_path))
                state_act = menu.addAction(state.get("label") or "Git status unknown")
                state_act.setEnabled(False)
                status_act = menu.addAction("Show Git Status")
                sync_act = menu.addAction("Git Pull (Sync)")
                create_cl_act = menu.addAction("Create Changelist from Updated Files...")
                view_cls_act = menu.addAction("View Current Changelists...")
                open_remote_act = menu.addAction("Open Git Remote (GitHub)")
                desktop_act = menu.addAction("Open in GitHub Desktop")
                revert_act = (
                    menu.addAction("Discard Git Changes in File")
                    if (item and item.data(0, Qt.UserRole) == "file")
                    else None
                )
                status_act.triggered.connect(lambda: self.run_vcs_command_dialog(vcs.status, Path(target_path), "Git Status"))
                sync_act.triggered.connect(lambda: self.run_vcs_command_async(vcs.sync, Path(target_path), "Git Pull"))
                create_cl_act.triggered.connect(self.create_vcs_changelist_dialog)
                view_cls_act.triggered.connect(self.show_vcs_changelists_dialog)

                def open_remote():
                    url = vcs.get_remote_url(Path(target_path))
                    if url:
                        import webbrowser
                        webbrowser.open(url)
                        self.append(f"\n[Git] Opened remote: {url}\n")
                    else:
                        QMessageBox.warning(self, "No Remote URL", "Could not retrieve git remote URL.")

                def open_desktop():
                    from tech_connector.services.version_control_service import launch_github_desktop
                    ok = launch_github_desktop(Path(target_path))
                    if ok:
                        self.append(f"\n[Git] Opened repository in GitHub Desktop client.\n")
                    else:
                        QMessageBox.warning(self, "Failed to Open", "Could not open repository in GitHub Desktop/git-gui.")

                open_remote_act.triggered.connect(open_remote)
                desktop_act.triggered.connect(open_desktop)
                if revert_act:
                    def revert_file():
                        reply = QMessageBox.question(
                            self,
                            "Revert file?",
                            f"Are you sure you want to revert changes to:\n\n{item.text(0)}?",
                            QMessageBox.Yes | QMessageBox.No,
                        )
                        if reply == QMessageBox.Yes:
                            self.run_vcs_command_async(vcs.revert_file, Path(path_str), "Git Revert")
                    revert_act.triggered.connect(revert_file)
                return

            if vcs.kind == "perforce":
                state = vcs.checkout_state(Path(target_path))
                state_act = menu.addAction(state.get("label") or "P4 status unknown")
                state_act.setEnabled(False)
                edit_act = (
                    menu.addAction("P4 Edit / Check Out File")
                    if (item and item.data(0, Qt.UserRole) == "file")
                    else None
                )
                revert_act = (
                    menu.addAction("P4 Revert Opened File")
                    if (item and item.data(0, Qt.UserRole) == "file")
                    else None
                )
                sync_act = menu.addAction("P4 Sync")
                status_act = menu.addAction("P4 Opened Files")
                create_cl_act = menu.addAction("Create Changelist from Updated Files...")
                view_cls_act = menu.addAction("View Current Changelists...")
                info_act = menu.addAction("P4 Checkout Detail")
                p4v_act = menu.addAction("Open in P4V")
                if edit_act:
                    edit_act.triggered.connect(lambda: self.run_vcs_command_async(vcs.checkout_file, Path(path_str), "P4 Edit"))
                if revert_act:
                    def revert_p4_file():
                        reply = QMessageBox.question(
                            self,
                            "Revert file?",
                            f"Are you sure you want to revert changes to:\n\n{item.text(0)}?",
                            QMessageBox.Yes | QMessageBox.No,
                        )
                        if reply == QMessageBox.Yes:
                            self.run_vcs_command_async(vcs.revert_file, Path(path_str), "P4 Revert")
                    revert_act.triggered.connect(revert_p4_file)
                sync_act.triggered.connect(lambda: self.run_vcs_command_async(vcs.sync, Path(target_path), "P4 Sync"))
                status_act.triggered.connect(lambda: self.run_vcs_command_dialog(vcs.status, Path(target_path), "P4 Opened Files"))
                create_cl_act.triggered.connect(self.create_vcs_changelist_dialog)
                view_cls_act.triggered.connect(self.show_vcs_changelists_dialog)
                info_act.triggered.connect(
                    lambda: self.run_vcs_command_dialog(
                        lambda _p: "\n".join(
                            part for part in [
                                state.get("label") or "",
                                state.get("detail") or "",
                                state.get("raw") or "",
                            ]
                            if part
                        ) or "No Perforce checkout detail available.",
                        Path(target_path),
                        "P4 Checkout Detail",
                    )
                )

                def open_p4v():
                    from tech_connector.services.version_control_service import launch_p4v
                    ok = launch_p4v(Path(target_path))
                    if ok:
                        self.append(f"\n[Perforce] Opened client in P4V.\n")
                    else:
                        QMessageBox.warning(
                            self,
                            "Failed to Open",
                            "Could not open client in P4V. Make sure P4V is installed in C:\\Program Files\\Perforce\\p4v.exe.",
                        )

                p4v_act.triggered.connect(open_p4v)

        QTimer.singleShot(0, hydrate_vcs_actions)
        menu.popup(self.project_tree.mapToGlobal(pos))
        return

    def toggle_auto_checkout(self, checked):
        self.settings["auto_checkout_on_change"] = checked
        self.service.save_settings()
        self.append(f"\n[Settings] Auto Checkout on Change set to: {checked}\n")

    def load_project(self):
        start = self.settings.get("active_project") or str(Path.cwd())
        path = QFileDialog.getExistingDirectory(self, "Load Project", start)
        if not path:
            return
        active = self.service.set_active_project(path)
        self.settings = self.service.settings
        self.update_project_header()
        self.refresh_recent_projects()
        self.load_project_tree_lazy()
        self.start_async_symbol_indexing()
        self.append(f"\n[Project] Loaded: {active}\n")

    def load_recent_project(self, *_args):
        if not hasattr(self, "recent_project_box"):
            return
        path = self.recent_project_box.currentData()
        if not path:
            return
        active = self.service.set_active_project(path)
        self.settings = self.service.settings
        self.update_project_header()
        self.refresh_recent_projects()
        self.load_project_tree_lazy()
        self.start_async_symbol_indexing()
        self.append(f"\n[Project] Loaded recent: {active}\n")

    def on_project_tree_expanded(self, item):
        """Stream folder entries progressively while keeping Qt responsive."""
        path = item.text(1)
        state = item.data(0, Qt.UserRole + 1)
        if not path or state in {"loaded", "loading"}:
            return

        item.setData(0, Qt.UserRole + 1, "loading")
        item.takeChildren()
        item.addChild(QTreeWidgetItem(["Loading...", ""]))

        workers = getattr(self, "_project_tree_folder_workers", None)
        if workers is None:
            workers = {}
            self._project_tree_folder_workers = workers

        existing = workers.get(path)
        if existing is not None and existing.isRunning():
            return

        worker = ProjectFolderLoadWorker(path, self, batch_size=20)
        workers[path] = worker
        first_batch = {"received": False}

        def release_worker():
            current = workers.get(path)
            if current is worker:
                workers.pop(path, None)
            worker.deleteLater()

        def apply_batch(loaded_path, entries, total_seen):
            if item.treeWidget() is None or item.text(1) != loaded_path:
                return

            tree = item.treeWidget()
            tree.setUpdatesEnabled(False)
            try:
                if not first_batch["received"]:
                    item.takeChildren()
                    first_batch["received"] = True
                append_folder_entries(item, entries, self.style())
                item.setData(0, Qt.UserRole + 1, "loading")
            finally:
                tree.setUpdatesEnabled(True)
                tree.viewport().update()

            try:
                self.status.setText(
                    f"Loading {Path(loaded_path).name}: {int(total_seen)} items..."
                )
            except Exception:
                pass

        def finish_loading(loaded_path, total):
            if item.treeWidget() is not None and item.text(1) == loaded_path:
                if not first_batch["received"]:
                    item.takeChildren()
                item.setData(0, Qt.UserRole + 1, "loaded")
                try:
                    self.status.setText(
                        f"Loaded {Path(loaded_path).name}: {int(total)} items"
                    )
                except Exception:
                    pass
            release_worker()

        def apply_error(failed_path, message):
            if item.treeWidget() is not None and item.text(1) == failed_path:
                item.takeChildren()
                item.addChild(
                    QTreeWidgetItem([
                        f"[error: {message or 'could not read folder'}]",
                        failed_path,
                    ])
                )
                item.setData(0, Qt.UserRole + 1, "failed")
            release_worker()

        worker.batch_ready.connect(apply_batch)
        worker.completed.connect(finish_loading)
        worker.failed.connect(apply_error)
        worker.start()

    def schedule_project_tree_filter(self):
        timer = getattr(self, "project_filter_timer", None)
        if timer is not None:
            try:
                timer.start()
                return
            except Exception:
                pass
        try:
            self.filter_project_tree(self.project_filter.text())
        except Exception:
            pass

    def filter_project_tree(self, text):
        cleaned = text.strip().strip('"').strip("'")
        if not cleaned:
            filter_tree_items(self.project_tree, "")
            return

        is_path = False
        try:
            p = Path(cleaned)
            if ("/" in cleaned or "\\" in cleaned) or p.is_absolute() or p.exists():
                is_path = True
        except Exception:
            pass

        if is_path:
            success = self.select_path_in_tree(cleaned)
            if success:
                filter_tree_items(self.project_tree, "")
                # Clear the search box to keep the layout clean after navigating
                self.project_filter.blockSignals(True)
                self.project_filter.clear()
                self.project_filter.blockSignals(False)
            else:
                filter_tree_items(self.project_tree, cleaned)
        else:
            filter_tree_items(self.project_tree, cleaned)

    def toggle_project_panel(self):
        if not hasattr(self, "left_panel") or not hasattr(self, "main_splitter"):
            return
        if self.left_panel.isVisible():
            sizes = self.main_splitter.sizes()
            if sizes and sizes[0] > 40:
                self._last_project_panel_width = sizes[0]
            self.left_panel.setVisible(False)
            self.toggle_project_btn.setText("Show")
            if hasattr(self, "project_restore_btn"):
                self.project_restore_btn.setVisible(True)
        else:
            self.left_panel.setVisible(True)
            width = getattr(self, "_last_project_panel_width", 360)
            sizes = self.main_splitter.sizes()
            total = sum(sizes) if sizes else 1500
            self.main_splitter.setSizes([width, max(700, total - width)])
            self.toggle_project_btn.setText("Hide")
            if hasattr(self, "project_restore_btn"):
                self.project_restore_btn.setVisible(False)

    def expand_project_panel(self):
        if not hasattr(self, "main_splitter"):
            return
        self.left_panel.setVisible(True)
        self.toggle_project_btn.setText("Hide")
        if hasattr(self, "project_restore_btn"):
            self.project_restore_btn.setVisible(False)
        total = sum(self.main_splitter.sizes()) or 1500
        self.main_splitter.setSizes([520, max(700, total - 520)])

    def collapse_project_panel(self):
        if not hasattr(self, "main_splitter"):
            return
        self.left_panel.setVisible(True)
        self.toggle_project_btn.setText("Hide")
        if hasattr(self, "project_restore_btn"):
            self.project_restore_btn.setVisible(False)
        total = sum(self.main_splitter.sizes()) or 1500
        self.main_splitter.setSizes([260, max(900, total - 260)])

    def refresh_project_tree_fast(self):
        self.load_project_tree_lazy()
        roots = ", ".join(self.project_roots())
        self.append(f"\n[Project Tree] Updated: {roots}\n")
        if hasattr(self, "refresh_workflows_list"):
            self.refresh_workflows_list()

    def select_path_in_tree(self, path_str):
        if not path_str or not hasattr(self, "project_tree"):
            return False

        try:
            target_path = Path(path_str).resolve()
        except Exception:
            return False

        # Find the root that is a prefix of target_path
        best_root_item = None
        best_root_len = -1

        for i in range(self.project_tree.topLevelItemCount()):
            item = self.project_tree.topLevelItem(i)
            root_path_str = item.text(1)
            if not root_path_str:
                continue
            try:
                root_path = Path(root_path_str).resolve()
                if target_path == root_path or root_path in target_path.parents:
                    root_len = len(root_path.parts)
                    if root_len > best_root_len:
                        best_root_len = root_len
                        best_root_item = item
            except Exception:
                pass

        if not best_root_item:
            return False

        current_item = best_root_item
        # Expand current item to ensure it is populated
        if current_item.data(0, Qt.UserRole + 1) != "loaded":
            self.on_project_tree_expanded(current_item)
        current_item.setExpanded(True)

        # Get components of target path relative to the root
        try:
            root_path = Path(current_item.text(1)).resolve()
            relative_parts = target_path.relative_to(root_path).parts
        except Exception:
            return False

        accumulated_path = root_path
        for part in relative_parts:
            accumulated_path = accumulated_path / part
            found_child = None
            for i in range(current_item.childCount()):
                child = current_item.child(i)
                child_path_str = child.text(1)
                if not child_path_str:
                    continue
                try:
                    if Path(child_path_str).resolve() == accumulated_path:
                        found_child = child
                        break
                except Exception:
                    pass

            if found_child:
                current_item = found_child
                if current_item.data(0, Qt.UserRole + 1) != "loaded":
                    self.on_project_tree_expanded(current_item)
                current_item.setExpanded(True)
            else:
                break

        # Select and scroll to the final item we reached
        self.project_tree.setCurrentItem(current_item)
        self.project_tree.scrollToItem(current_item)
        return True

    def on_project_tree_selection_changed(self, current, previous):
        if current and hasattr(self, "project_path_edit"):
            path = current.text(1)
            if path:
                self.project_path_edit.blockSignals(True)
                self.project_path_edit.setText(path)
                self.project_path_edit.blockSignals(False)

    def on_project_path_submitted(self):
        if not hasattr(self, "project_path_edit"):
            return
        path_str = self.project_path_edit.text().strip()
        if path_str:
            self.select_path_in_tree(path_str)

    def open_tree_file(self, item, column=0):
        path = item.text(1)
        if not path:
            return
        p = Path(path)
        if p.is_file() and is_supported_code_file(p):
            self.open_code_file(str(p))

    def open_code_file(self, path, *, restore: bool = False):
        path = str(Path(path).resolve())
        if path in self.open_editors:
            editor = self.open_editors[path]
            idx = self.editor_tabs.indexOf(editor)
            if idx != -1:
                self.editor_tabs.setCurrentIndex(idx)
                self.current_file_path = path
                self.file_path_label.setText(path)
                self.schedule_editor_syntax_status()
                if not restore:
                    self.select_path_in_tree(path)
                    self.refresh_editor_structure()
                    self.remember_recent_file(path)
                return

        ok, content = self.service.read_file(path)
        if not ok:
            QMessageBox.critical(self, "Open failed", content)
            return

        editor = CodeEditor()
        editor.setFont(QFont("Consolas", 10))
        editor.setPlainText(content)
        editor.document().setModified(False)
        editor.cursorPositionChanged.connect(self.update_cursor_status)
        editor.textChanged.connect(self.schedule_editor_syntax_status)
        editor.file_path = path

        self.open_editors[path] = editor
        title = Path(path).name
        idx = self.editor_tabs.addTab(editor, title)
        self.editor_tabs.setTabToolTip(idx, path)
        self.editor_tabs.setCurrentIndex(idx)

        self.current_file_path = path
        self.file_path_label.setText(path)
        self.schedule_editor_syntax_status()
        if not restore:
            self.append(f"\n[Opened file: {path}]\n")
            self.save_editor_state()
            self.select_path_in_tree(path)
            self.refresh_editor_structure()
            self.remember_recent_file(path)

    def save_code_file(self):
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "No file is currently open.")
            return
        # Get active editor for this path
        editor = self.open_editors.get(path, self.code_editor)
        try:
            if not self.write_text_with_vcs(path, editor.toPlainText(), "save it"):
                return
            msg = path
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        editor.document().setModified(False)
        self.schedule_editor_syntax_status()
        self.start_async_symbol_indexing()
        self.append(f"\n[Saved file: {msg}]\n")

    def analyze_current_editor_file(self) -> bool:
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a Python file before running analysis.")
            return False
        if Path(path).suffix.lower() in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}:
            return self.build_current_native_project("analyze")
        if not str(path).lower().endswith(".py"):
            QMessageBox.information(self, "Unsupported file", "Analysis supports Python and CMake-based C/C++ projects.")
            return False
        self.update_editor_syntax_status()
        problems = getattr(self, "editor_problems_list", None)
        count = problems.count() if problems is not None else 0
        if hasattr(self, "append"):
            self.append(f"\n[Editor Analysis] {Path(path).name}: {count} problem(s).\n")
        return True

    def build_current_native_project(self, action: str = "build") -> bool:
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a file inside a CMake project before building.")
            return False
        active = getattr(self, "_native_build_worker", None)
        if active is not None and active.isRunning():
            QMessageBox.information(self, "Build active", "A native project build is already running.")
            return False
        configuration = self.editor_build_configuration.currentText()
        try:
            plan = create_native_build_plan(path, configuration, action)
        except ValueError as exc:
            QMessageBox.information(self, "C++ Build", str(exc))
            return False
        self.editor_build_btn.setEnabled(False)
        self.editor_build_btn.setText("Building...")
        self.editor_problems_toggle.setChecked(True)
        self.editor_problems_list.clear()
        self.engine_console_toggle.setChecked(True)
        self.engine_console_output.clear()
        self.engine_console_output.appendPlainText(
            f"CMake {plan.action.replace('_', ' ').title()} {plan.configuration}: {plan.project_root}\n"
        )
        worker = NativeProjectBuildWorker(plan, self)
        worker.output_ready.connect(self.engine_console_output.appendPlainText)
        worker.completed.connect(self._native_build_completed)
        worker.failed.connect(self._native_build_failed)
        worker.finished.connect(worker.deleteLater)
        self._native_build_worker = worker
        self._last_native_build_root = plan.project_root
        worker.start()
        return True

    def _native_build_completed(self, receipt) -> None:
        self.editor_build_btn.setEnabled(True)
        self.editor_build_btn.setText("Build")
        self.update_editor_problems(receipt.diagnostics)
        state = "cancelled" if receipt.cancelled else ("succeeded" if receipt.ok else "failed")
        self.engine_console_output.appendPlainText(
            f"\nBuild {state} in {receipt.elapsed_seconds:.2f}s; "
            f"{len(receipt.diagnostics)} diagnostic(s)."
        )
        self._native_build_worker = None

    def _native_build_failed(self, message: str) -> None:
        self.editor_build_btn.setEnabled(True)
        self.editor_build_btn.setText("Build")
        self.engine_console_output.appendPlainText(f"\nBuild could not start: {message}")
        self._native_build_worker = None

    def open_output_source_location(self, path: str, line: int, column: int) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            worker = getattr(self, "_native_build_worker", None)
            root = getattr(getattr(worker, "plan", None), "project_root", "") or getattr(
                self, "_last_native_build_root", ""
            )
            candidate = Path(root or Path.cwd()) / candidate
        candidate = candidate.resolve()
        if not candidate.is_file():
            self.engine_console_output.appendPlainText(f"Source file was not found: {candidate}")
            return False
        self.open_code_file(str(candidate))
        editor = self.open_editors.get(str(candidate), self.code_editor)
        cursor = editor.document().findBlockByLineNumber(max(0, int(line) - 1))
        text_cursor = QTextCursor(cursor)
        text_cursor.movePosition(QTextCursor.Right, QTextCursor.MoveAnchor, max(0, int(column) - 1))
        editor.setTextCursor(text_cursor)
        editor.setFocus()
        return True

    def reformat_current_editor_file(self) -> bool:
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a Python file before reformatting.")
            return False
        editor = self.open_editors.get(path, self.code_editor)
        if Path(path).suffix.lower() in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}:
            return self._apply_editor_quality_transform(
                editor,
                lambda text: reformat_native_source(text, path),
                "Reformat File",
            )
        if not str(path).lower().endswith(".py"):
            QMessageBox.information(self, "Unsupported file", "Reformat File supports Python and C/C++ files.")
            return False
        return self._apply_editor_quality_transform(
            editor,
            lambda text: reformat_python_source(text, path),
            "Reformat File",
        )

    def fix_current_editor_quality_issues(self) -> bool:
        path = getattr(self, "current_file_path", "")
        if not path:
            QMessageBox.information(self, "No file", "Open a Python file before fixing issues.")
            return False
        if not str(path).lower().endswith(".py"):
            QMessageBox.information(self, "Unsupported file", "Fix Issues is currently enabled for Python files.")
            return False
        editor = self.open_editors.get(path, self.code_editor)
        return self._apply_editor_quality_transform(
            editor,
            lambda text: fix_python_quality_issues(text, path),
            "Fix Issues",
        )

    def _apply_editor_quality_transform(self, editor, transform, label: str) -> bool:
        if editor is None:
            return False
        before = editor.toPlainText()
        cursor = editor.textCursor()
        position = cursor.position()
        try:
            after, messages = transform(before)
        except Exception as exc:
            QMessageBox.warning(self, label, str(exc))
            return False
        if after == before:
            if hasattr(self, "append"):
                self.append(f"\n[Editor {label}] No changes needed.\n")
            self.update_editor_syntax_status()
            return True
        editor.setPlainText(after)
        cursor = editor.textCursor()
        cursor.setPosition(min(position, len(after)))
        editor.setTextCursor(cursor)
        editor.document().setModified(True)
        self.schedule_editor_syntax_status()
        if hasattr(self, "append"):
            detail = " ".join(str(message) for message in messages if message)
            self.append(f"\n[Editor {label}] Updated current buffer. {detail}\n")
        return True

    def add_docstrings_to_current_file(self, request_text: str = "") -> bool:
        path = getattr(self, "current_file_path", "")
        if not path:
            self.append("\n[Docstrings] Open a Python file first, then ask again.\n")
            return True
        if not str(path).lower().endswith(".py"):
            self.append(f"\n[Docstrings] Current file is not a Python file: {path}\n")
            return True

        editor = self.open_editors.get(path, self.code_editor)
        before = editor.toPlainText()
        cursor = editor.textCursor()
        selection_start_line = None
        selection_end_line = None
        if cursor and cursor.hasSelection():
            selection_start_line = editor.document().findBlock(cursor.selectionStart()).blockNumber() + 1
            selection_end_line = editor.document().findBlock(cursor.selectionEnd()).blockNumber() + 1

        try:
            from tech_connector.services.docstring_service import add_missing_docstrings
            from tech_connector.services.chat_report_service import format_code_change_report

            result = add_missing_docstrings(
                before,
                selection_start_line=selection_start_line,
                selection_end_line=selection_end_line,
            )
            if result.error:
                self.append(f"\n[Docstrings] Could not add docstrings: {result.error}\n")
                return True
            if not result.changed:
                scope = "selected code" if selection_start_line and selection_end_line else "current file"
                self.append(f"\n[Docstrings] No missing function docstrings or params found in the {scope}.\n")
                return True

            self.last_applied_backup = {
                str(path): {
                    "action": "modify",
                    "content": before,
                }
            }
            if not self.write_text_with_vcs(path, result.source, "add missing docstrings"):
                self.last_applied_backup = {}
                return True

            editor.blockSignals(True)
            editor.setPlainText(result.source)
            editor.blockSignals(False)
            editor.document().setModified(False)
            self.schedule_editor_syntax_status()
            self.start_async_symbol_indexing()

            added = [item.name for item in result.added if not item.updated_existing]
            repaired = [item.name for item in result.added if item.updated_existing]
            summary_bits = []
            if added:
                summary_bits.append(f"added docstrings to {len(added)} function(s)")
            if repaired:
                summary_bits.append(f"added missing params/returns to {len(repaired)} existing docstring(s)")
            summary = "; ".join(summary_bits) or "updated function docstrings"
            if request_text:
                summary += f" from chat request: {request_text[:120]}"

            report = format_code_change_report(
                [
                    {
                        "path": str(path),
                        "action": "modify",
                        "before": before,
                        "after": result.source,
                        "summary": summary,
                        "line": result.added[0].line if result.added else 1,
                    }
                ],
                title="Docstrings Added",
                validation=[
                    f"Added new docstrings: {', '.join(added) or 'none'}",
                    f"Repaired existing docstrings: {', '.join(repaired) or 'none'}",
                    "Existing docstrings were preserved unless params/return entries were missing.",
                ],
            )
            self.workspace_tabs.setCurrentIndex(0)
            self.append(f"\nASSISTANT [Docstrings]:\n{report}\n")
            return True
        except Exception as exc:
            self.append(f"\n[Docstrings Error] {exc}\n")
            return True

    def close_editor_tab_from_container(self, tabs, index):
        editor = tabs.widget(index)
        if isinstance(editor, CodeEditor):
            path = getattr(editor, "file_path", "")
            if editor.document().isModified():
                res = QMessageBox.question(
                    self,
                    "Save Changes",
                    f"File '{Path(path).name}' has unsaved changes. Save before closing?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                )
                if res == QMessageBox.Yes:
                    tabs.setCurrentIndex(index)
                    self.on_editor_tab_activated_from_container("", editor, tabs)
                    self.save_code_file()
                elif res == QMessageBox.Cancel:
                    return

            tabs.removeTab(index)
            if path in self.open_editors:
                del self.open_editors[path]
            editor.deleteLater()

        if getattr(tabs, "detached_window", None) is not None:
            tabs.detached_window.close_if_empty()

        if self.editor_tabs.count() == 0 and not self.open_editors:
            self.current_file_path = ""
            self.file_path_label.setText("No file open")
            self.update_cursor_status()
            self.refresh_editor_structure()
        self.save_editor_state()

    def close_editor_tab(self, index):
        self.close_editor_tab_from_container(self.editor_tabs, index)

    def remember_recent_file(self, path: str) -> None:
        if not path:
            return
        recent = [item for item in self.settings.get("recent_files", []) if item and item != path]
        recent.insert(0, path)
        self.settings["recent_files"] = recent[:20]
        try:
            self.service.save_settings()
        except Exception:
            pass
        self.refresh_recent_files_dropdown()

    def refresh_recent_files_dropdown(self):
        combo = getattr(self, "recent_file_box", None)
        if combo is None:
            return
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Recent files...", "")
        for path in self.settings.get("recent_files", [])[:20]:
            if not path or not Path(path).exists():
                continue
            combo.addItem(Path(path).name, path)
            index = combo.count() - 1
            combo.setItemData(index, path, Qt.ToolTipRole)
        if current:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def open_recent_file_from_dropdown(self, index: int):
        combo = getattr(self, "recent_file_box", None)
        if combo is None:
            return
        path = combo.itemData(index)
        if path:
            self.open_code_file(str(path))

    def on_editor_tab_changed(self, index):
        editor = self.editor_tabs.widget(index)
        if isinstance(editor, CodeEditor):
            self.current_file_path = getattr(editor, "file_path", "")
            self.file_path_label.setText(self.current_file_path)
        else:
            self.current_file_path = ""
            self.file_path_label.setText("No file open")
        self.schedule_editor_syntax_status()
        self.refresh_editor_structure()
        self.save_editor_state()

    def on_editor_tab_activated_from_container(self, title, editor, container):
        if isinstance(editor, CodeEditor):
            self.current_file_path = getattr(editor, "file_path", "")
            self.file_path_label.setText(self.current_file_path)
            try:
                editor.setFocus()
            except Exception:
                pass
        else:
            self.current_file_path = ""
            self.file_path_label.setText("No file open")
        self.schedule_editor_syntax_status()
        tree = getattr(container, "_detached_structure_tree", None)
        if tree is not None:
            self.refresh_editor_structure_for_container(container, tree)
        else:
            self.refresh_editor_structure()
        self.save_editor_state()

    def schedule_editor_structure_refresh(self):
        timer = getattr(self, "editor_structure_timer", None)
        if timer is not None:
            timer.start(350)

    def on_editor_structure_order_changed(self, text: str):
        self.settings["editor_structure_sort"] = "natural" if text == "Natural" else "az"
        try:
            self.service.save_settings()
        except Exception:
            pass
        self.refresh_editor_structure()

    def refresh_editor_structure(self):
        tree = getattr(self, "editor_structure_tree", None)
        if tree is None:
            return
        tree.clear()
        path = getattr(self, "current_file_path", "")
        editor = self.open_editors.get(path) if hasattr(self, "open_editors") else None
        if editor is None:
            tree.addTopLevelItem(QTreeWidgetItem(["No file open"]))
            return
        try:
            from tech_connector.services.editor_structure_service import python_structure_from_text

            sort_alpha = self.settings.get("editor_structure_sort", "az") != "natural"
            items = python_structure_from_text(editor.toPlainText(), path, sort_alpha=sort_alpha)
        except Exception:
            items = []
        if not items:
            tree.addTopLevelItem(QTreeWidgetItem(["No Python structure"]))
            return

        stack: list[QTreeWidgetItem] = []
        for entry in items:
            label = entry.label()
            node = QTreeWidgetItem([label])
            node.setToolTip(0, entry.signature or entry.kind)
            node.setData(0, Qt.UserRole, {"line": entry.line, "kind": entry.kind, "name": entry.name})
            if entry.kind == "class":
                node.setForeground(0, QBrush(QColor("#d7b46a")))
                font = node.font(0)
                font.setBold(True)
                node.setFont(0, font)
            elif entry.kind == "async function":
                node.setForeground(0, QBrush(QColor("#5bd000")))
                font = node.font(0)
                font.setItalic(True)
                node.setFont(0, font)
            else:
                node.setForeground(0, QBrush(QColor("#5bd000")))
            while len(stack) > entry.depth:
                stack.pop()
            if stack:
                stack[-1].addChild(node)
            else:
                tree.addTopLevelItem(node)
            stack.append(node)
        tree.expandAll()

    def build_detached_editor_structure_panel(self, container):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        row = QHBoxLayout()
        row.addWidget(QLabel("Structure"), 1)
        order_box = QComboBox()
        order_box.addItems(["Natural", "A-Z"])
        order_box.setCurrentText("A-Z" if self.settings.get("editor_structure_sort", "az") == "az" else "Natural")
        row.addWidget(order_box)
        layout.addLayout(row)
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setMinimumWidth(170)
        tree.setMaximumWidth(300)
        tree.setIndentation(14)
        tree.setSortingEnabled(False)
        tree.setUniformRowHeights(True)
        tree.setToolTip("Structure for the active file in this detached editor window.")
        layout.addWidget(tree, 1)
        container._detached_structure_tree = tree
        order_box.currentTextChanged.connect(lambda _text: self.refresh_editor_structure_for_container(container, tree))
        tree.itemActivated.connect(lambda item, column=0: self.jump_to_editor_structure_item_for_container(container, item))
        tree.itemClicked.connect(lambda item, column=0: self.jump_to_editor_structure_item_for_container(container, item))
        container.currentChanged.connect(lambda _idx: self.refresh_editor_structure_for_container(container, tree))
        self.refresh_editor_structure_for_container(container, tree)
        return panel

    def refresh_editor_structure_for_container(self, container, tree):
        if tree is None:
            return
        tree.clear()
        editor = container.currentWidget() if container is not None else None
        path = getattr(editor, "file_path", "") if isinstance(editor, CodeEditor) else ""
        if not path:
            tree.addTopLevelItem(QTreeWidgetItem(["No file open"]))
            return
        try:
            from tech_connector.services.editor_structure_service import python_structure_from_text

            sort_alpha = self.settings.get("editor_structure_sort", "az") != "natural"
            items = python_structure_from_text(editor.toPlainText(), path, sort_alpha=sort_alpha)
        except Exception:
            items = []
        if not items:
            tree.addTopLevelItem(QTreeWidgetItem(["No Python structure"]))
            return
        stack: list[QTreeWidgetItem] = []
        for entry in items:
            node = QTreeWidgetItem([entry.label()])
            node.setToolTip(0, entry.signature or entry.kind)
            node.setData(0, Qt.UserRole, {"line": entry.line, "kind": entry.kind, "name": entry.name})
            if entry.kind == "class":
                node.setForeground(0, QBrush(QColor("#d7b46a")))
                font = node.font(0)
                font.setBold(True)
                node.setFont(0, font)
            elif entry.kind == "async function":
                node.setForeground(0, QBrush(QColor("#5bd000")))
                font = node.font(0)
                font.setItalic(True)
                node.setFont(0, font)
            else:
                node.setForeground(0, QBrush(QColor("#5bd000")))
            while len(stack) > entry.depth:
                stack.pop()
            if stack:
                stack[-1].addChild(node)
            else:
                tree.addTopLevelItem(node)
            stack.append(node)
        tree.expandAll()

    def jump_to_editor_structure_item_for_container(self, container, item):
        data = item.data(0, Qt.UserRole) if item is not None else None
        if not data:
            return
        editor = container.currentWidget() if container is not None else None
        if not isinstance(editor, CodeEditor):
            return
        line_no = int(data.get("line") or 1)
        block = editor.document().findBlockByNumber(max(0, line_no - 1))
        cursor = QTextCursor(block)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        editor.setFocus()

    def jump_to_editor_structure_item(self, item, column=0):
        data = item.data(0, Qt.UserRole) if item is not None else None
        if not data:
            return
        line_no = int(data.get("line") or 1)
        editor = self.open_editors.get(getattr(self, "current_file_path", "")) if hasattr(self, "open_editors") else None
        if editor is None:
            return
        block = editor.document().findBlockByNumber(max(0, line_no - 1))
        cursor = QTextCursor(block)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()
        editor.setFocus()

    def save_editor_state(self):
        paths = list(self.open_editors.keys())
        self.settings["open_files"] = paths
        self.settings["active_file"] = self.current_file_path
        self.service.save_settings()
        self.refresh_recent_files_dropdown()

    def restore_editor_state(self):
        paths = self.settings.get("open_files", [])
        active = self.settings.get("active_file", "")
        # Temporarily block signals to avoid multiple writes during restoration
        self.editor_tabs.blockSignals(True)
        try:
            for path in paths:
                if Path(path).exists():
                    self.open_code_file(path, restore=True)
        finally:
            self.editor_tabs.blockSignals(False)

        if active and active in self.open_editors:
            editor = self.open_editors[active]
            idx = self.editor_tabs.indexOf(editor)
            if idx != -1:
                self.editor_tabs.setCurrentIndex(idx)
                self.current_file_path = active
                self.file_path_label.setText(active)
                self.update_cursor_status()
                self.schedule_editor_syntax_status()
                self.refresh_editor_structure()
        self.refresh_recent_files_dropdown()

    def find_in_project(self):
        query = self.project_search.text().strip()
        if not query:
            return
        self.search_results.clear()
        for line in find_in_project(self.project_roots(), query):
            self.search_results.addItem(line)

    def open_search_result(self, item):
        text = item.text()
        if "::" not in text:
            return
        path, rest = text.split("::", 1)
        self.open_code_file(path)
        try:
            line_no = int(rest.split(" ", 1)[0])
            cursor = self.code_editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            for _ in range(max(0, line_no - 1)):
                cursor.movePosition(QTextCursor.Down)
            self.code_editor.setTextCursor(cursor)
            self.code_editor.setFocus()
        except Exception:
            pass

    def run_symbol_search_from_ui(self):
        q = self.symbol_query.text().strip()
        domain = self.symbol_domain.currentText().strip() or "all"
        if not q:
            return
        self.send_raw(self.prompt_router.symbol_search(q, domain), "Symbol Search")

    def run_callers_search_from_ui(self):
        q = self.symbol_query.text().strip()
        domain = self.symbol_domain.currentText().strip() or "all"
        if not q:
            return
        self.send_raw(self.prompt_router.find_callers(q, domain), "Find Callers")

    def run_implementation_lookup_from_ui(self):
        q = self.symbol_query.text().strip()
        domain = self.symbol_domain.currentText().strip() or "all"
        if not q:
            return
        self.send_raw(
            self.prompt_router.read_implementation(q, domain), "Read Implementation"
        )

# Public compatibility exports live in a focused, independently testable service.
from .editor_assist_service import (
    EditorAssistWorker,
    answer_editor_code_request,
    answer_project_index_request,
    build_editor_code_request_prompt,
    build_project_request_prompt,
    detect_editor_intent,
    gather_project_index_context,
    query_project_index_model_text,
)
