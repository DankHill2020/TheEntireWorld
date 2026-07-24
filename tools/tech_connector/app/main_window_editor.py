"""Extracted MainWindow methods. Generated from the uploaded monolithic file."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

_ROOT = next(candidate for candidate in Path(__file__).resolve().parents if candidate.name.lower() == "tools")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

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


class MainWindowEditorMixin:
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
            self.update_cursor_status()
            return
        try:
            compile(self.code_editor.toPlainText(), "<string>", "exec")
            self._editor_syntax_suffix = " | Python Syntax Valid"
        except SyntaxError as e:
            self._editor_syntax_suffix = (
                f" | Python Syntax Error: {e.msg} (line {e.lineno})"
            )
        except Exception as e:
            self._editor_syntax_suffix = f" | Check Error: {e}"
        self.update_cursor_status()

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
        response_label = "Implementation Plan" if is_plan else "Editor Assist"
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

        if patch:
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
            self.project_root_label.setToolTip(display)
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



LOOKUP_HINTS = (
    "what is",
    "what does",
    "where",
    "why",
    "explain",
    "describe",
    "find",
    "show",
    "definition",
    "references",
    "callers",
    "usage",
    "uses",
    "used by",
    "read",
    "inspect",
    "summarize",
)

GENERATE_HINTS = (
    "add",
    "make",
    "create",
    "write",
    "generate",
    "build",
    "implement",
    "new class",
    "new function",
    "new method",
    "popup",
    "dialog",
    "widget",
    "button",
    "upload",
    "insert",
)

EDIT_HINTS = (
    "change",
    "modify",
    "replace",
    "rename",
    "refactor",
    "fix",
    "debug",
    "improve",
    "clean up",
    "split",
    "move",
    "extract",
    "remove",
    "delete",
    "repair",
)

PROJECT_SCOPE_HINTS = (
    "project",
    "codebase",
    "whole repo",
    "entire repo",
    "entire project",
    "all files",
    "every file",
    "throughout",
    "everywhere",
    "anywhere",
    "across the project",
    "across this project",
    "find every",
    "find all",
    "every class",
    "all classes",
    "every function",
    "all functions",
    "where is",
    "where are",
    "used by",
    "callers",
    "usages",
    "references",
    "unused files",
    "dead code",
    "not imported",
    "not used",
    "safe to delete",
)


def detect_editor_intent(text):
    """Classify an Ask About File prompt.

    Returns:
        "lookup": current-file explanation/read request.
        "generate": current-file code generation request.
        "edit": current-file change/refactor/debug request.
        "project_search": whole-project/index lookup request.
        "project_edit": whole-project/index-backed edit/refactor request.
    """

    lower = (text or "").strip().lower()
    if not lower:
        return "lookup"

    edit_score = sum(1 for token in EDIT_HINTS if token in lower)
    generate_score = sum(1 for token in GENERATE_HINTS if token in lower)
    lookup_score = sum(1 for token in LOOKUP_HINTS if token in lower)
    mutation_terms = re.search(
        r"\b(add|create|write|generate|implement|insert|improve|refactor|fix|update|patch|wire|connect|troubleshoot|diagnose|repair|test)\b",
        lower,
    )
    current_file_only = bool(
        re.search(r"\b(this|current|open|active)\s+file\b", lower)
        or re.search(r"\b(in|inside)\s+this\s+file\b", lower)
        or re.search(r"\b(this|current|open|active|selected|exact selected)\s+(function|module|helper|code block|class)\b", lower)
    )
    if current_file_only and re.search(r"\b(where.*used|used by|callers|references|usages)\b", lower):
        return "project_search"
    if current_file_only:
        if edit_score or re.search(r"\b(replace|refactor|fix|update|improve|change|patch)\b", lower):
            return "edit"
        if generate_score or re.search(r"\b(add|create|write|new|fresh)\b", lower):
            return "generate"
        return "lookup"

    if re.search(r"\bwhere should\b", lower) and not re.search(r"\b(then|and then|add it|implement it|do it|make it|wire it)\b", lower):
        return "project_search"

    read_only_project_lookup = (
        re.search(
            r"\b(where is|where are|list callers|list usages|list references|find every|find all|which files|which service|what functions)\b",
            lower,
        )
        or re.search(r"\bexplain\b.*\bwhere\b.*\bused\b", lower)
    ) and not re.search(
        r"\b(then|and then|fix|patch|update|add|write|implement|insert|improve|refactor|wire|connect|make|build|repair)\b",
        lower,
    )
    if read_only_project_lookup:
        return "project_search"

    if is_project_scope_request(lower) and not (edit_score or generate_score or mutation_terms):
        return "project_search"

    if re.search(r"\b(troubleshoot|diagnose)\b", lower) and mutation_terms:
        return "project_edit"

    # Target-discovery edit: user asks the assistant to find the right file/module
    # and then add/modify code there, e.g. "find a rigging file and add IK/FK".
    target_discovery = (
        re.search(r"\b(find|locate|choose|pick|where should|best place|which file)\b", lower)
        and re.search(r"\b(file|module|place|location)\b", lower)
        and (edit_score or generate_score or mutation_terms)
    )
    if target_discovery:
        return "project_edit"

    existing_system_edit = (
        re.search(r"\b(inspect|review|audit|analyze|find)\s+(?:the\s+)?existing\b", lower)
        and re.search(r"\b(system|support|service|framework|pipeline|graph|workflow|ui|tooling|implementation|code)\b", lower)
        and (edit_score or generate_score or mutation_terms)
    )
    if existing_system_edit:
        return "project_edit"

    discovery_first_edit = (
        not current_file_only
        and (
            edit_score
            or generate_score
            or mutation_terms
            or re.search(r"\buse\s+(?:it|them|that|those)\s+for\s+(?:a|an|the)?\s*new\b", lower)
        )
        and (
            re.search(r"\b(find|locate|inspect|review|audit|analyze|where should|where.*belong|best place|choose|pick|existing|reuse|using current|using existing|before editing|first)\b", lower)
            or re.search(r"\b(system|support|service|framework|pipeline|graph|workflow|menu registration|helper|helpers|utility|utilities|code path|parser|router|index service|domain expert|startup|chat history|bridge status|maya|unreal|blueprint)\b", lower)
        )
    )
    if discovery_first_edit:
        return "project_edit"

    # Route project/codebase questions before current-file code generation.
    # This includes usage queries like "where is QFileDialog used" and broader
    # searches like "find every class in this project that opens QFileDialog".
    if is_project_scope_request(lower):
        if edit_score or generate_score or mutation_terms:
            return "project_edit"
        return "project_search"

    if edit_score:
        return "edit"
    if generate_score:
        return "generate"
    if lookup_score:
        return "lookup"

    return "lookup"

def _question_keywords(question, max_terms=10):
    """Extract useful search terms for SQLite index lookup."""
    q = question or ""
    # Preserve camel/Qt names before lowercase tokenization.
    exactish = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?\b", q)
    stop = {
        "the", "and", "for", "that", "this", "with", "from", "into", "what", "where", "which",
        "every", "class", "classes", "function", "functions", "method", "methods", "project",
        "codebase", "file", "files", "find", "show", "summarize", "explain", "does", "uses",
        "used", "opens", "open", "make", "create", "add", "change", "replace", "rename", "refactor",
        "throughout", "anywhere", "all", "each", "one", "ones", "are", "is", "in", "to", "of",
    }
    terms = []
    for item in exactish:
        if len(item) < 3:
            continue
        low = item.lower()
        if low in stop:
            continue
        if item not in terms:
            terms.append(item)
    # Add normalized lowercase words if we still need recall.
    for item in re.findall(r"[a-zA-Z0-9_]{3,}", q.lower()):
        if item in stop:
            continue
        if item not in [t.lower() for t in terms]:
            terms.append(item)
    return terms[:max_terms]


def _quote_sql_identifier(value):
    return '"' + str(value).replace('"', '""') + '"'


def gather_project_index_context(question, active_path=None, limit=40):
    """Gather project-wide evidence from the SQLite knowledge index.

    This intentionally avoids local_answer_about_file because that function is
    optimized around a single active-file symbol. Project-scope prompts need
    indexed symbols/chunks across the codebase.
    """
    import sqlite3

    try:
        from tech_connector.models.constants import project_index_db_path
    except Exception as exc:
        return f"[Project index unavailable] Could not import project_index_db_path: {exc}"

    if not project_index_db_path().exists():
        return f"[Project index unavailable] Database not found: {project_index_db_path()}"

    terms = _question_keywords(question)
    lower = (question or "").lower()

    # Bias class queries toward class symbols, but still allow functions when the
    # user asks for functions/usages.
    kind_filter = None
    if re.search(r"\b(class|classes|widget|widgets|dialog|dialogs)\b", lower):
        kind_filter = "class"
    elif re.search(r"\b(function|functions|method|methods)\b", lower):
        kind_filter = None

    try:
        from contextlib import closing
        with closing(sqlite3.connect(str(project_index_db_path()))) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Prefer symbol source/searchable_text because it keeps results at
            # class/function granularity instead of dumping whole files.
            where_parts = []
            params = []
            for term in terms:
                where_parts.append(
                    "(s.name LIKE ? OR s.qualname LIKE ? OR s.signature LIKE ? OR "
                    "s.docstring LIKE ? OR s.searchable_text LIKE ? OR s.source LIKE ? OR f.path LIKE ?)"
                )
                like = f"%{term}%"
                params.extend([like, like, like, like, like, like, like])

            query = """
                SELECT
                    s.name, s.qualname, s.kind, s.signature, s.docstring,
                    s.start_line, s.end_line, s.source, f.path
                FROM symbols s
                JOIN files f ON f.id = s.file_id
                WHERE 1=1
            """
            if where_parts:
                query += " AND (" + " OR ".join(where_parts) + ")"
            if kind_filter:
                query += " AND s.kind = ?"
                params.append(kind_filter)
            if active_path:
                query += " ORDER BY CASE WHEN f.path = ? THEN 0 ELSE 1 END, f.path, s.start_line LIMIT ?"
                params.extend([str(Path(active_path).resolve()), limit])
            else:
                query += " ORDER BY f.path, s.start_line LIMIT ?"
                params.append(limit)

            rows = cur.execute(query, params).fetchall()

            # If OR search is too broad or terms were poor, try FTS against symbols.
            if not rows and terms:
                fts_query = " OR ".join(t.replace('"', ' ') for t in terms[:6])
                try:
                    rows = cur.execute(
                        """
                        SELECT
                            s.name, s.qualname, s.kind, s.signature, s.docstring,
                            s.start_line, s.end_line, s.source, f.path
                        FROM symbols_fts sf
                        JOIN symbols s ON s.id = sf.rowid
                        JOIN files f ON f.id = s.file_id
                        WHERE symbols_fts MATCH ?
                        LIMIT ?
                        """,
                        (fts_query, limit),
                    ).fetchall()
                except Exception:
                    rows = []

            if not rows:
                return (
                    "Project index was queried, but no matching symbols were found.\n"
                    f"Search terms used: {', '.join(terms) or '(none)'}"
                )

            parts = [
                "Project index results:",
                f"Database: {project_index_db_path()}",
                f"Search terms: {', '.join(terms) or '(none)'}",
                "",
            ]
            for idx, row in enumerate(rows, start=1):
                source = row["source"] or ""
                source_lines = source.splitlines()
                if len(source_lines) > 35:
                    source = "\n".join(source_lines[:30]) + "\n... [symbol truncated] ..."
                parts.append(
                    f"[{idx}] {row['kind']} {row['qualname'] or row['name']} "
                    f"lines {row['start_line']}-{row['end_line']}\n"
                    f"File: {row['path']}\n"
                    f"Signature: {row['signature'] or row['name']}\n"
                    f"Docstring: {row['docstring'] or 'No docstring'}\n"
                    f"Source:\n```python\n{source}\n```\n"
                )

            return "\n".join(parts)

    except Exception as exc:
        return f"[Project index error] {exc}"


def build_project_request_prompt(question, active_path, project_context, intent):
    return f"""You are assisting inside a Python/Qt code editor with access to a project-wide SQLite index.

User-facing goal:
Answer the user's project-wide request directly. Do not expose routing notes,
prompt-building instructions, or hidden analyzer details.

Intent:
{intent}

Active file, if relevant:
{active_path}

User request:
{question}

Project-wide context from the knowledge index:
{project_context[:16000]}

Rules:
- Treat this as a whole-project/codebase question, not a current-file-only question.
- Use the indexed results as evidence; do not invent files, classes, functions, or usages.
- If the index results look incomplete, say what was searched and what might need reindexing.
- Group findings by file when multiple files are involved.
- For search/explanation requests, summarize what each relevant class/function/file does.
- For refactor/edit requests, identify affected files, imports, call sites, and risks.
- If edits are requested, leave the project in a functional, importable, and testable state.

Response format:
1. Direct answer.
2. Relevant files/classes/functions found.
3. What each one does or why it matters.
4. Recommended next step or verification command, if useful.
"""


def query_project_index_model_text(
    provider_route,
    *,
    model,
    system_prompt,
    user_prompt,
    response_format="",
    num_predict=4096,
    timeout=120,
    temperature=0.0,
    progress_callback=None,
    local_query=None,
    cloud_query=None,
    **kwargs,
):
    """Run a UI project-index text stage without crossing provider boundaries."""
    if local_query is None:
        from tech_connector.knowledge.search import query_ollama_text

        local_query = query_ollama_text
    if cloud_query is None:
        from tech_connector.services.llm_router_service import generate_llm_response

        cloud_query = generate_llm_response

    if provider_route.cloud_active:
        started = time.monotonic()
        result = cloud_query(
            provider_route.model,
            user_prompt,
            system=system_prompt,
            response_format=response_format or None,
            options={
                "temperature": temperature,
                "num_predict": num_predict,
            },
            timeout=timeout,
            provider_route=provider_route,
            allow_cloud_fallback=False,
        )
        if callable(progress_callback):
            progress_callback(
                {
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "characters_received": len(result),
                }
            )
        return result
    return local_query(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_format=response_format,
        num_predict=num_predict,
        timeout=timeout,
        temperature=temperature,
        progress_callback=progress_callback,
        **kwargs,
    )


def answer_project_index_request(path, question, intent, status_callback=None, approved_plan=None):
    """Answer project-wide/index-backed questions with the local coding model."""
    try:
        from tech_connector.services.settings_service import load_settings
        from tech_connector.knowledge.search import (
            query_ollama_text,
        )
        from tech_connector.services.llm_router_service import (
            LLMCloudProviderError,
            query_structured_llm_until_complete,
            resolve_llm_provider_route,
        )
        from tech_connector.services.model_provider_service import (
            cloud_provider_failure_notice,
        )
    except Exception as exc:
        return f"Could not load project-index LLM helpers:\n\n{exc}", None

    try:
        settings = load_settings()
    except Exception:
        settings = {}

    model = (
        settings.get("code_model")
        or settings.get("model")
        or settings.get("general_model")
        or "qwen3-coder:30b"
    )
    plan_model = (
        settings.get("router_local_plan")
        or settings.get("plan_model")
        or settings.get("general_model")
        or settings.get("model")
        or model
    )
    prompt_provider_route = resolve_llm_provider_route(plan_model, settings)

    def query_prompt_text(
        **kwargs,
    ):
        return query_project_index_model_text(
            prompt_provider_route,
            local_query=query_ollama_text,
            **kwargs,
        )

    if intent == "project_edit":
        try:
            from tech_connector.services.project_edit_agent_service import (
                apply_project_edit_syntax_repair,
                apply_project_edit_generated_symbol_repair,
                apply_project_edit_missing_symbol,
                build_project_edit_file_generation_stages,
                build_project_edit_requirement_coverage,
                build_project_edit_artifact_file_stages,
                build_project_edit_artifact_manifest_stage,
                build_project_edit_file_map_stage,
                build_project_edit_cross_file_failure_notes,
                build_project_edit_integration_contract_stage,
                build_project_edit_function_repair_contract,
                build_project_edit_function_repair_plan_stage,
                build_project_edit_function_repair_stage,
                build_project_edit_leaf_candidate,
                build_project_edit_leaf_stage,
                build_project_edit_multi_file_candidate,
                build_project_edit_missing_symbol_stage,
                build_project_edit_plan_from_leaf_work_units,
                build_project_edit_repair_stage,
                build_project_edit_agent_request,
                build_project_edit_model_stages,
                build_project_edit_syntax_repair_stage,
                compile_project_edit_leaf_work_units,
                complete_project_edit_integration_contract_response,
                compose_project_edit_incremental_manifest_response,
                ensure_project_edit_requested_docstrings,
                enforce_project_edit_explicit_cleanup,
                enforce_project_edit_requested_test_contracts,
                extract_project_edit_artifact_requirements,
                format_project_edit_generated_python,
                inspect_project_edit_structured_syntax,
                infer_project_edit_generated_dependencies,
                isolate_project_edit_generated_test_fixture,
                model_for_project_edit_stage,
                normalize_project_edit_async_test_lifecycle,
                parse_project_edit_generated_file,
                parse_project_edit_artifact_manifest,
                parse_project_edit_function_repair_plan,
                parse_project_edit_leaf_source,
                preview_project_edit_agent_response,
                project_edit_artifact_architecture_requires_coder,
                project_edit_file_worker_profile,
                project_edit_file_worker_model_override,
                project_edit_has_core_contract_failure,
                project_edit_preview_error_score,
                project_edit_plan_fingerprint,
                project_edit_leaf_work_units_handoff,
                project_edit_validation_failure_signature,
                repair_project_edit_duplicate_dependency_symbols,
                render_project_edit_artifact_architecture,
                render_grounded_project_edit_handoff,
                restore_project_edit_leaf_work_units,
                resolve_project_edit_cross_file_symbols,
                resolve_project_edit_failure_symbol,
                resolve_project_edit_standard_library_symbols,
                remove_project_edit_unused_imports,
                stabilize_project_edit_import_cycles,
                summarize_project_edit_generated_interface,
                validate_project_edit_generated_module_graph,
                validate_project_edit_integration_contract_response,
                validate_project_edit_plan_output,
            )

            approved_work_units = None
            if isinstance(approved_plan, dict) and approved_plan.get("leaf_work_units"):
                if callable(status_callback):
                    status_callback("Validating approved indexed work units")
                approved_work_units, handoff_errors = restore_project_edit_leaf_work_units(
                    approved_plan.get("leaf_work_units"),
                    question,
                )
                if handoff_errors:
                    return (
                        "BLOCKED: Indexed edit intelligence changed after this plan was created.\n\n"
                        + "\n".join(f"- {item}" for item in handoff_errors),
                        None,
                    )
                edit_plan = build_project_edit_plan_from_leaf_work_units(
                    question,
                    approved_work_units,
                )
            else:
                if callable(status_callback):
                    status_callback("Querying indexed target files and reusable project systems")
                edit_plan = build_project_edit_agent_request(
                    question,
                    active_path=path,
                    limit=8,
                )
            project_context = edit_plan.discovery_context
            all_stages = build_project_edit_model_stages(edit_plan)
            patch_stage = next((stage for stage in all_stages if stage.key == "patch_generation"), None)
            project_roots = list(edit_plan.discovery.get("project_roots") or [])
            project_root = project_roots[0] if project_roots else str(Path(path).parent)
            reasoning_gap_events = []
            planning_trace_events = []

            def model_heartbeat(label: str):
                if not callable(status_callback):
                    return None

                def emit(event):
                    status_callback(
                        f"{label}: model active for {event.get('elapsed_seconds', 0)}s; "
                        f"{event.get('characters_received', 0)} response characters received"
                    )

                return emit

            def json_model_heartbeat(label: str):
                if not callable(status_callback):
                    return None
                last_emitted = [0.0]

                def emit(_chunk, accumulated):
                    now = time.monotonic()
                    if now - last_emitted[0] < 5.0:
                        return
                    last_emitted[0] = now
                    status_callback(
                        f"{label}: model is still producing the architecture; "
                        f"{len(accumulated)} response characters received"
                    )

                return emit

            def synthesize_artifact_architecture(approved_text: str = ""):
                manifest_stage = build_project_edit_artifact_manifest_stage(
                    edit_plan,
                    approved_plan=approved_text,
                )
                if manifest_stage is None:
                    return [], [], []
                requirement_ledger = extract_project_edit_artifact_requirements(question)
                architecture_deadline = time.monotonic() + 20.0
                contract_stage = build_project_edit_integration_contract_stage(edit_plan)
                if approved_text:
                    contract_stage.user_prompt += (
                        "\n\nPrior approved plan or integration feedback:\n"
                        + approved_text[-6000:]
                    )
                contract_model = model_for_project_edit_stage(
                    contract_stage,
                    settings,
                    selected_model=model,
                )
                contract_provider = (
                    prompt_provider_route.provider
                    if prompt_provider_route.cloud_active
                    else "ollama"
                )
                contract_model_name = (
                    prompt_provider_route.model
                    if prompt_provider_route.cloud_active
                    else str(contract_model).replace("ollama:", "", 1)
                )
                if callable(status_callback):
                    status_callback(
                        f"{contract_stage.label}; {contract_provider}:"
                        f"{contract_model_name}; shared 20-second planning budget; "
                        "provider locked for this run"
                    )
                contract_started = time.monotonic()
                contract_response = query_structured_llm_until_complete(
                    model=contract_model,
                    system_prompt=contract_stage.system_prompt,
                    user_prompt=contract_stage.user_prompt,
                    num_ctx=contract_stage.num_ctx,
                    timeout=contract_stage.timeout,
                    prefer_coder=contract_stage.prefer_coder,
                    coder_preference=contract_stage.coder_preference,
                    response_format=contract_stage.response_format,
                    temperature=0.0,
                    progress_callback=json_model_heartbeat("Contract worker"),
                    max_wall_seconds=max(
                        0.1,
                        architecture_deadline - time.monotonic(),
                    ),
                    provider_route=prompt_provider_route,
                )
                contract_response, deterministic_contract_fixes = (
                    complete_project_edit_integration_contract_response(
                        contract_response or "",
                        requirement_ledger,
                    )
                )
                if deterministic_contract_fixes and callable(status_callback):
                    status_callback(
                        "Completed implied coordination contracts: "
                        + "; ".join(deterministic_contract_fixes)
                    )
                contract_errors = validate_project_edit_integration_contract_response(
                    contract_response or "",
                    requirement_ledger,
                )
                for contract_repair_attempt in range(1, 3):
                    if (
                        not contract_errors
                        or architecture_deadline - time.monotonic() <= 3.0
                    ):
                        break
                    planning_trace_events.append({
                        "stage": "artifact_integration_contract",
                        "attempt": contract_repair_attempt,
                        "status": "rejected",
                        "provider": contract_provider,
                        "model": contract_model_name,
                        "elapsed_seconds": round(
                            time.monotonic() - contract_started,
                            3,
                        ),
                        "response_characters": len(contract_response or ""),
                        "validator_errors": list(contract_errors),
                        "response": contract_response or "",
                    })
                    if callable(status_callback):
                        status_callback(
                            f"Repairing only the rejected shared contract "
                            f"({contract_repair_attempt}/2): "
                            + "; ".join(contract_errors[:3])
                        )
                    repair_started = time.monotonic()
                    contract_response = query_structured_llm_until_complete(
                        model=contract_model,
                        system_prompt=contract_stage.system_prompt,
                        user_prompt=(
                            contract_stage.user_prompt
                            + "\n\nThe prior contract is below. Preserve every working "
                            "contract detail and return the complete corrected contract:\n"
                            + str(contract_response or "")[-6000:]
                            + "\n\nFix exactly these remaining validator errors. Include "
                            "their required protocol words verbatim in executable signatures, "
                            "state invariants, or data layout:\n- "
                            + "\n- ".join(contract_errors[:4])
                        ),
                        num_ctx=contract_stage.num_ctx,
                        timeout=contract_stage.timeout,
                        prefer_coder=contract_stage.prefer_coder,
                        coder_preference=contract_stage.coder_preference,
                        response_format=contract_stage.response_format,
                        temperature=0.0,
                        progress_callback=json_model_heartbeat(
                            "Contract repair worker"
                        ),
                        max_wall_seconds=max(
                            0.1,
                            architecture_deadline - time.monotonic(),
                        ),
                        provider_route=prompt_provider_route,
                    )
                    contract_started = repair_started
                    contract_response, repair_contract_fixes = (
                        complete_project_edit_integration_contract_response(
                            contract_response or "",
                            requirement_ledger,
                        )
                    )
                    if repair_contract_fixes and callable(status_callback):
                        status_callback(
                            "Completed implied coordination contracts after repair: "
                            + "; ".join(repair_contract_fixes)
                        )
                    contract_errors = (
                        validate_project_edit_integration_contract_response(
                            contract_response or "",
                            requirement_ledger,
                        )
                    )
                contract_valid = not contract_errors
                if not contract_valid:
                    errors = list(contract_errors) or [
                        "Shared integration contract was incomplete or invalid within "
                        "the 20-second planning budget."
                    ]
                    planning_trace_events.append({
                        "stage": "artifact_integration_contract",
                        "status": "rejected",
                        "provider": contract_provider,
                        "model": contract_model_name,
                        "elapsed_seconds": round(
                            time.monotonic() - contract_started,
                            3,
                        ),
                        "response_characters": len(contract_response or ""),
                        "response": contract_response or "",
                    })
                    reasoning_gap_events.append({
                        "stage": "artifact_integration_contract",
                        "attempt": 1,
                        "provider": contract_provider,
                        "model": contract_model_name,
                        "elapsed_seconds": round(time.monotonic() - contract_started, 3),
                        "response_characters": len(contract_response or ""),
                        "validator_errors": errors,
                        "fallback_action": "preserve partial contract and stop before file mapping",
                    })
                    return [], errors, requirement_ledger
                planning_trace_events.append({
                    "stage": "artifact_integration_contract",
                    "status": "accepted",
                    "provider": contract_provider,
                    "model": contract_model_name,
                    "elapsed_seconds": round(time.monotonic() - contract_started, 3),
                    "response_characters": len(contract_response or ""),
                    "response": contract_response or "",
                })

                remaining_thought_seconds = architecture_deadline - time.monotonic()
                if remaining_thought_seconds <= 0:
                    errors = [
                        "Shared contract consumed the complete 20-second planning budget "
                        "before file mapping."
                    ]
                    reasoning_gap_events.append({
                        "stage": "artifact_file_map",
                        "attempt": 0,
                        "model": "",
                        "elapsed_seconds": 0.0,
                        "response_characters": 0,
                        "validator_errors": errors,
                        "fallback_action": "preserve accepted contract and defer file mapping",
                    })
                    return [], errors, requirement_ledger

                file_map_stage = build_project_edit_file_map_stage(
                    edit_plan,
                    requirement_ledger=requirement_ledger,
                    integration_contract_response=contract_response or "",
                )
                file_map_model = model_for_project_edit_stage(
                    file_map_stage,
                    settings,
                    selected_model=model,
                )
                file_map_provider = (
                    prompt_provider_route.provider
                    if prompt_provider_route.cloud_active
                    else "ollama"
                )
                file_map_model_name = (
                    prompt_provider_route.model
                    if prompt_provider_route.cloud_active
                    else str(file_map_model).replace("ollama:", "", 1)
                )
                if callable(status_callback):
                    status_callback(
                        f"{file_map_stage.label}; {file_map_provider}:"
                        f"{file_map_model_name}; "
                        f"{remaining_thought_seconds:.1f}s planning budget remains"
                    )
                file_map_started = time.monotonic()
                file_map_response = query_structured_llm_until_complete(
                    model=file_map_model,
                    system_prompt=file_map_stage.system_prompt,
                    user_prompt=file_map_stage.user_prompt,
                    num_ctx=file_map_stage.num_ctx,
                    timeout=file_map_stage.timeout,
                    prefer_coder=file_map_stage.prefer_coder,
                    coder_preference=file_map_stage.coder_preference,
                    response_format=file_map_stage.response_format,
                    temperature=0.0,
                    progress_callback=json_model_heartbeat("File-map worker"),
                    max_wall_seconds=max(
                        0.1,
                        architecture_deadline - time.monotonic(),
                    ),
                    provider_route=prompt_provider_route,
                )
                combined_response, composition_errors = (
                    compose_project_edit_incremental_manifest_response(
                        contract_response or "",
                        file_map_response or "",
                        requirement_ledger,
                    )
                )
                manifest, manifest_errors = parse_project_edit_artifact_manifest(
                    combined_response,
                    project_root=project_root,
                    requirement_ledger=requirement_ledger,
                    strict_architecture=True,
                ) if not composition_errors else ([], composition_errors)
                if (
                    manifest_errors
                    and architecture_deadline - time.monotonic() > 4.0
                ):
                    planning_trace_events.append({
                        "stage": "artifact_file_map",
                        "attempt": 1,
                        "status": "rejected",
                        "provider": file_map_provider,
                        "model": file_map_model_name,
                        "elapsed_seconds": round(
                            time.monotonic() - file_map_started,
                            3,
                        ),
                        "response_characters": len(file_map_response or ""),
                        "validator_errors": list(manifest_errors),
                        "response": file_map_response or "",
                    })
                    if callable(status_callback):
                        status_callback(
                            "Repairing only the rejected file map: "
                            + "; ".join(manifest_errors[:3])
                        )
                    repair_started = time.monotonic()
                    file_map_response = query_structured_llm_until_complete(
                        model=file_map_model,
                        system_prompt=file_map_stage.system_prompt,
                        user_prompt=(
                            file_map_stage.user_prompt
                            + "\n\nThe prior file map is below. Preserve valid file "
                            "ownership and return the complete corrected map:\n"
                            + str(file_map_response or "")[-6000:]
                            + "\n\nFix exactly these validator errors:\n- "
                            + "\n- ".join(manifest_errors[:4])
                        ),
                        num_ctx=file_map_stage.num_ctx,
                        timeout=file_map_stage.timeout,
                        prefer_coder=file_map_stage.prefer_coder,
                        coder_preference=file_map_stage.coder_preference,
                        response_format=file_map_stage.response_format,
                        temperature=0.0,
                        progress_callback=json_model_heartbeat(
                            "File-map repair worker"
                        ),
                        max_wall_seconds=max(
                            0.1,
                            architecture_deadline - time.monotonic(),
                        ),
                        provider_route=prompt_provider_route,
                    )
                    file_map_started = repair_started
                    combined_response, composition_errors = (
                        compose_project_edit_incremental_manifest_response(
                            contract_response or "",
                            file_map_response or "",
                            requirement_ledger,
                        )
                    )
                    manifest, manifest_errors = (
                        parse_project_edit_artifact_manifest(
                            combined_response,
                            project_root=project_root,
                            requirement_ledger=requirement_ledger,
                            strict_architecture=True,
                        )
                        if not composition_errors
                        else ([], composition_errors)
                    )
                planning_trace_events.append({
                    "stage": "artifact_file_map",
                    "status": "rejected" if manifest_errors else "accepted",
                    "provider": file_map_provider,
                    "model": file_map_model_name,
                    "elapsed_seconds": round(time.monotonic() - file_map_started, 3),
                    "response_characters": len(file_map_response or ""),
                    "response": file_map_response or "",
                })
                if manifest_errors:
                    reasoning_gap_events.append({
                        "stage": "artifact_file_map",
                        "attempt": 1,
                        "provider": file_map_provider,
                        "model": file_map_model_name,
                        "elapsed_seconds": round(time.monotonic() - file_map_started, 3),
                        "response_characters": len(file_map_response or ""),
                        "validator_errors": list(manifest_errors),
                        "fallback_action": (
                            "preserve accepted contract and rejected file-map evidence"
                        ),
                    })
                return manifest, manifest_errors, requirement_ledger

            approved_plan_text = ""
            if isinstance(approved_plan, dict):
                approved_plan_text = str(approved_plan.get("plan") or "").strip()
                expected_fingerprint = str(approved_plan.get("fingerprint") or "")
                if expected_fingerprint != project_edit_plan_fingerprint(edit_plan):
                    return (
                        "BLOCKED: The target changed after this implementation plan was created. "
                        "Regenerate and review the plan before code generation.",
                        None,
                    )
            elif approved_plan:
                approved_plan_text = str(approved_plan).strip()

            if approved_plan_text:
                plan_errors = validate_project_edit_plan_output(edit_plan, approved_plan_text)
                if plan_errors:
                    return (
                        "BLOCKED: The approved implementation plan no longer satisfies the grounded plan contract.\n\n"
                        + "\n".join(f"- {item}" for item in plan_errors),
                        None,
                    )
                if patch_stage is None:
                    return approved_plan_text, None
                stages = [patch_stage]
            else:
                stages = [stage for stage in all_stages if stage.key == "target_selection_plan"]
                if build_project_edit_artifact_manifest_stage(edit_plan) is not None:
                    deterministic_plan = render_grounded_project_edit_handoff(edit_plan)
                    manifest, manifest_errors, requirement_ledger = (
                        synthesize_artifact_architecture(deterministic_plan)
                    )
                    if manifest_errors:
                        return (
                            "## Implementation Plan\n\n"
                            + deterministic_plan
                            + "\n\n## Architecture Blocker\n\n"
                            + "\n".join(f"- {item}" for item in manifest_errors),
                            {
                                "type": "project_edit_plan_blocked",
                                "path": str(path or ""),
                                "question": str(question or ""),
                                "plan": deterministic_plan,
                                "fingerprint": project_edit_plan_fingerprint(edit_plan),
                                "architecture_errors": manifest_errors,
                                "reasoning_gaps": list(reasoning_gap_events),
                                "planning_trace": list(planning_trace_events),
                            },
                        )
                    architecture_text = render_project_edit_artifact_architecture(
                        manifest,
                        requirement_ledger,
                    )
                    reviewable_plan = deterministic_plan + "\n\n" + architecture_text
                    if callable(status_callback):
                        status_callback(
                            "Prepared reviewable disposable-artifact architecture with "
                            "file, API, dependency, algorithm, and test ownership"
                        )
                    return (
                        "## Implementation Plan\n\n"
                        + reviewable_plan
                        + "\n\nReview this plan, then use **Approve Plan** to generate a code preview. "
                        "No code or files have been changed.",
                        {
                            "type": "project_edit_plan",
                            "path": str(path or ""),
                            "question": str(question or ""),
                            "plan": reviewable_plan,
                            "fingerprint": project_edit_plan_fingerprint(edit_plan),
                            "artifact_manifest": manifest,
                            "requirement_ledger": requirement_ledger,
                            "reasoning_gaps": list(reasoning_gap_events),
                            "planning_trace": list(planning_trace_events),
                        },
                    )
            bounded_file_state = {
                "generated_files": [],
                "file_stages": [],
                "reasoning_gaps": list(
                    approved_plan.get("reasoning_gaps") or []
                    if isinstance(approved_plan, dict)
                    else reasoning_gap_events
                ),
            }
            bounded_symbol_repair_attempts = {}

            def build_from_bounded_file_workers():
                file_stages = build_project_edit_file_generation_stages(edit_plan)
                cached_manifest = list(
                    bounded_file_state.get("override_manifest")
                    or (
                        approved_plan.get("artifact_manifest")
                        if isinstance(approved_plan, dict)
                        else []
                    )
                    or []
                )
                if not file_stages and cached_manifest:
                    cached_ledger = list(
                        bounded_file_state.get("override_requirement_ledger")
                        or (
                            approved_plan.get("requirement_ledger")
                            if isinstance(approved_plan, dict)
                            else []
                        )
                        or []
                    )
                    cached_manifest, cached_errors = parse_project_edit_artifact_manifest(
                        json.dumps({"files": cached_manifest}),
                        project_root=project_root,
                        requirement_ledger=cached_ledger,
                        strict_architecture=True,
                    )
                    if cached_errors:
                        bounded_file_state["manifest_required"] = True
                        bounded_file_state["manifest_errors"] = cached_errors
                        return None, None
                    bounded_file_state["manifest_required"] = True
                    bounded_file_state["manifest"] = cached_manifest
                    bounded_file_state["requirement_ledger"] = cached_ledger
                    file_stages = build_project_edit_artifact_file_stages(
                        edit_plan,
                        cached_manifest,
                    )
                    if callable(status_callback):
                        status_callback(
                            f"Using approved artifact architecture: "
                            f"{len(file_stages)} dependency-ordered file workers"
                        )
                if not file_stages:
                    manifest_stage = build_project_edit_artifact_manifest_stage(
                        edit_plan,
                        approved_plan=approved_plan_text,
                    )
                    if manifest_stage is not None:
                        bounded_file_state["manifest_required"] = True
                        manifest = []
                        manifest_errors = []
                        manifest_feedback = ""
                        requirement_ledger = extract_project_edit_artifact_requirements(question)
                        requires_coder = project_edit_artifact_architecture_requires_coder(
                            requirement_ledger
                        )
                        bounded_file_state["requirement_ledger"] = requirement_ledger
                        architecture_deadline = time.monotonic() + 20.0
                        for manifest_attempt in range(1, 4):
                            remaining_thought_seconds = (
                                architecture_deadline - time.monotonic()
                            )
                            if remaining_thought_seconds <= 0:
                                manifest_errors = [
                                    "Architecture reasoning reached the 20-second interaction limit."
                                ]
                                break
                            if requires_coder:
                                manifest_stage.model_tier = "local_code"
                            else:
                                manifest_stage.model_tier = (
                                    "local_semantic"
                                    if manifest_attempt == 1
                                    else "local_semantic_verify"
                                    if manifest_attempt == 2
                                    else "local_code"
                                )
                            manifest_stage.prefer_coder = (
                                requires_coder or manifest_attempt == 3
                            )
                            manifest_stage.coder_preference = (
                                "standard"
                                if requires_coder or manifest_attempt == 3
                                else "small"
                            )
                            manifest_model = model_for_project_edit_stage(
                                manifest_stage,
                                settings,
                                selected_model=model,
                            )
                            if callable(status_callback):
                                status_callback(
                                    f"{manifest_stage.label}; {manifest_model}; "
                                    f"attempt {manifest_attempt}/3; validating paths and dependencies"
                                )
                            manifest_response = query_structured_llm_until_complete(
                                model=manifest_model,
                                system_prompt=manifest_stage.system_prompt,
                                user_prompt=manifest_stage.user_prompt + manifest_feedback,
                                num_ctx=manifest_stage.num_ctx,
                                timeout=manifest_stage.timeout,
                                prefer_coder=manifest_stage.prefer_coder,
                                coder_preference=manifest_stage.coder_preference,
                                response_format=manifest_stage.response_format,
                                temperature=0.0,
                                progress_callback=json_model_heartbeat("Architecture worker"),
                                max_wall_seconds=remaining_thought_seconds,
                                provider_route=prompt_provider_route,
                            )
                            manifest, manifest_errors = parse_project_edit_artifact_manifest(
                                manifest_response or "",
                                project_root=project_root,
                                requirement_ledger=requirement_ledger,
                                strict_architecture=True,
                            )
                            if not manifest_errors:
                                break
                            if callable(status_callback):
                                status_callback(
                                    f"Rejected artifact manifest attempt {manifest_attempt}/3: "
                                    + "; ".join(manifest_errors[:3])
                                )
                            manifest_feedback = (
                                "\n\nThe prior manifest was rejected. Return a fresh complete compact JSON "
                                "manifest that fixes these exact errors:\n- "
                                + "\n- ".join(manifest_errors[:4])
                            )
                        if manifest_errors:
                            bounded_file_state["manifest_errors"] = list(manifest_errors)
                            if callable(status_callback):
                                status_callback(
                                    "Rejected generated artifact manifest: "
                                    + "; ".join(manifest_errors[:3])
                                )
                            return None, None
                        file_stages = build_project_edit_artifact_file_stages(edit_plan, manifest)
                        bounded_file_state["manifest"] = manifest
                        if callable(status_callback):
                            status_callback(
                                f"Artifact contract accepted: {len(file_stages)} dependency-ordered files"
                            )
                if not file_stages:
                    return None, None
                generated_files = []
                dependency_sources = []
                for file_index, (target_path, original_source, file_stage) in enumerate(file_stages, start=1):
                    expected_symbols = list(
                        (file_stage.metadata or {}).get("expected_public_symbols")
                        or []
                    )
                    prior_symbol_owners: dict[str, str] = {}
                    for prior_path, _prior_original, prior_source in generated_files:
                        try:
                            prior_tree = ast.parse(prior_source, filename=prior_path)
                        except SyntaxError:
                            continue
                        for node in prior_tree.body:
                            if isinstance(
                                node,
                                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                            ) and not node.name.startswith("_"):
                                prior_symbol_owners.setdefault(node.name, prior_path)
                    transferred_symbols = {
                        str(symbol).split("(", 1)[0].rsplit(".", 1)[-1].strip(): owner
                        for symbol in expected_symbols
                        if (
                            str(symbol).split("(", 1)[0].rsplit(".", 1)[-1].strip()
                            in prior_symbol_owners
                        )
                        for owner in [
                            prior_symbol_owners[
                                str(symbol).split("(", 1)[0]
                                .rsplit(".", 1)[-1].strip()
                            ]
                        ]
                    }
                    if transferred_symbols:
                        file_stage.metadata["expected_public_symbols"] = [
                            symbol
                            for symbol in expected_symbols
                            if (
                                str(symbol).split("(", 1)[0]
                                .rsplit(".", 1)[-1].strip()
                                not in transferred_symbols
                            )
                        ]
                        transferred_dependencies = []
                        for owner_path in transferred_symbols.values():
                            try:
                                relative_owner = (
                                    Path(owner_path).resolve()
                                    .relative_to(Path(project_root).resolve())
                                    .as_posix()
                                )
                            except ValueError:
                                continue
                            transferred_dependencies.append(relative_owner)
                        file_stage.metadata["depends_on"] = list(dict.fromkeys([
                            *((file_stage.metadata or {}).get("depends_on") or []),
                            *transferred_dependencies,
                        ]))
                        file_stage.user_prompt += (
                            "\n\nValidated ownership transfer from earlier completed files: "
                            + "; ".join(
                                f"{symbol} -> {Path(owner).name}"
                                for symbol, owner in sorted(transferred_symbols.items())
                            )
                            + ". Import and reuse these canonical symbols; do not redefine them."
                        )
                        if callable(status_callback):
                            status_callback(
                                f"Transferred canonical public ownership before "
                                f"{Path(target_path).name}: "
                                + "; ".join(
                                    f"{symbol} -> {Path(owner).name}"
                                    for symbol, owner in sorted(transferred_symbols.items())
                                )
                            )
                    output_source = ""
                    errors = []
                    rejected_source = ""
                    previous_rejected_source = ""
                    for attempt in range(1, 4):
                        file_stage.coder_preference = project_edit_file_worker_profile(
                            attempt
                        )
                        stage_model = model_for_project_edit_stage(
                            file_stage,
                            settings,
                            selected_model=model,
                        )
                        stage_model = (
                            project_edit_file_worker_model_override(attempt, settings)
                            or stage_model
                        )
                        dependency_context = ""
                        if dependency_sources:
                            dependency_context = (
                                "\n\nCompleted dependency/integration files from earlier bounded stages:\n"
                                + "\n\n".join(dependency_sources)[-7000:]
                            )
                        if errors:
                            dependency_context += (
                                f"\n\nRevision attempt {attempt}/3. Deterministic parser failures "
                                "from the prior attempt:\n- "
                                + "\n- ".join(errors)
                            )
                        if rejected_source:
                            dependency_context += (
                                "\n\nRejected but parseable prior source. Preserve its working implementation and "
                                "return the complete corrected file with only the reported omissions repaired:\n"
                                "```python\n"
                                + rejected_source[-12000:]
                                + "\n```"
                            )
                        if callable(status_callback):
                            status_callback(
                                f"{file_stage.label} ({file_index}/{len(file_stages)}; "
                                f"attempt {attempt}/3; {stage_model})"
                            )
                        response = query_prompt_text(
                            model=stage_model,
                            system_prompt=file_stage.system_prompt,
                            user_prompt=file_stage.user_prompt + dependency_context,
                            num_ctx=file_stage.num_ctx,
                            num_predict=file_stage.num_predict,
                            timeout=file_stage.timeout,
                            prefer_coder=file_stage.prefer_coder,
                            coder_preference=file_stage.coder_preference,
                            think=False,
                            response_format="",
                            temperature=0.0,
                            progress_callback=model_heartbeat(
                                f"File worker {Path(target_path).name}"
                            ),
                        )
                        output_source, errors = parse_project_edit_generated_file(
                            response or "",
                            path=target_path,
                            expected_public_symbols=list(
                                (file_stage.metadata or {}).get("expected_public_symbols") or []
                            ),
                        )
                        if output_source:
                            output_source, dependency_repairs = (
                                repair_project_edit_duplicate_dependency_symbols(
                                    output_source,
                                    path=target_path,
                                    project_root=project_root,
                                    generated_files=generated_files,
                                )
                            )
                            if dependency_repairs:
                                if callable(status_callback):
                                    status_callback(
                                        "Reused canonical dependency APIs: "
                                        + "; ".join(dependency_repairs)
                                    )
                                output_source, errors = (
                                    parse_project_edit_generated_file(
                                        output_source,
                                        path=target_path,
                                        expected_public_symbols=list(
                                            (file_stage.metadata or {}).get(
                                                "expected_public_symbols"
                                            )
                                            or []
                                        ),
                                    )
                                )
                        missing_match = next(
                            (
                                re.search(
                                    r"omitted manifest-declared public symbols "
                                    r"\([^)]+\):\s*(.+)$",
                                    str(error),
                                )
                                for error in errors
                                if "omitted manifest-declared public symbols" in str(error)
                            ),
                            None,
                        )
                        if output_source and missing_match:
                            missing_symbols = [
                                value.strip()
                                for value in missing_match.group(1).split(",")
                                if value.strip()
                            ]
                            insertion_errors: list[str] = []
                            for missing_symbol in missing_symbols:
                                insertion_stage = build_project_edit_missing_symbol_stage(
                                    path=target_path,
                                    symbol=missing_symbol,
                                    source=output_source,
                                    objective=question,
                                    contracts=list(
                                        (file_stage.metadata or {}).get("contracts") or []
                                    ),
                                    algorithm_steps=list(
                                        (file_stage.metadata or {}).get(
                                            "algorithm_steps"
                                        )
                                        or []
                                    ),
                                )
                                insertion_model = model_for_project_edit_stage(
                                    insertion_stage,
                                    settings,
                                    selected_model=model,
                                )
                                if callable(status_callback):
                                    status_callback(
                                        f"Implementing only missing public symbol "
                                        f"{missing_symbol} in {Path(target_path).name}"
                                    )
                                insertion_response = query_prompt_text(
                                    model=insertion_model,
                                    system_prompt=insertion_stage.system_prompt,
                                    user_prompt=insertion_stage.user_prompt,
                                    num_ctx=insertion_stage.num_ctx,
                                    num_predict=insertion_stage.num_predict,
                                    timeout=insertion_stage.timeout,
                                    prefer_coder=True,
                                    coder_preference=insertion_stage.coder_preference,
                                    think=False,
                                    response_format="",
                                    temperature=0.0,
                                    progress_callback=model_heartbeat(
                                        f"Missing symbol {missing_symbol}"
                                    ),
                                )
                                output_source, insertion_errors = (
                                    apply_project_edit_missing_symbol(
                                        output_source,
                                        path=target_path,
                                        symbol=missing_symbol,
                                        response=insertion_response or "",
                                    )
                                )
                                bounded_file_state.setdefault(
                                    "reasoning_gaps",
                                    [],
                                ).append({
                                    "stage": "artifact_missing_symbol",
                                    "file": str(target_path),
                                    "symbol": missing_symbol,
                                    "model": insertion_model,
                                    "response_characters": len(
                                        insertion_response or ""
                                    ),
                                    "validator_errors": list(insertion_errors),
                                    "fallback_action": (
                                        "insert declaration and revalidate file"
                                        if not insertion_errors
                                        else "return exact declaration failure"
                                    ),
                                })
                                if insertion_errors:
                                    break
                            if not insertion_errors:
                                output_source, errors = (
                                    parse_project_edit_generated_file(
                                        output_source,
                                        path=target_path,
                                        expected_public_symbols=list(
                                            (file_stage.metadata or {}).get(
                                                "expected_public_symbols"
                                            )
                                            or []
                                        ),
                                    )
                                )
                            else:
                                errors = insertion_errors
                        placeholder_match = next(
                            (
                                re.search(
                                    r"placeholder callable bodies \([^)]+\):\s*(.+)$",
                                    str(error),
                                )
                                for error in errors
                                if "placeholder callable bodies" in str(error)
                            ),
                            None,
                        )
                        if output_source and placeholder_match:
                            symbols = [
                                value.strip()
                                for value in placeholder_match.group(1).split(",")
                                if value.strip()
                            ]
                            provisional_files = [
                                *generated_files,
                                (target_path, original_source, output_source),
                            ]
                            symbol_repair_errors: list[str] = []
                            for symbol in symbols:
                                repair_contract, repair_contract_errors = (
                                    build_project_edit_function_repair_contract(
                                        provisional_files,
                                        target={
                                            "path": target_path,
                                            "symbol": symbol,
                                            "source": "",
                                        },
                                        validation_errors=errors,
                                        objective=question,
                                        requirements=list(
                                            (file_stage.metadata or {}).get(
                                                "algorithm_steps"
                                            )
                                            or []
                                        ),
                                    )
                                )
                                if repair_contract_errors:
                                    symbol_repair_errors.extend(
                                        repair_contract_errors
                                    )
                                    break
                                repair_errors = []
                                repair_feedback = ""
                                for callable_attempt in range(1, 3):
                                    repair_stage = build_project_edit_function_repair_stage(
                                        repair_contract,
                                        attempt=callable_attempt,
                                        repair_plan={
                                            "root_cause": "placeholder callable body",
                                            "algorithm_steps": list(
                                                (file_stage.metadata or {}).get(
                                                    "algorithm_steps"
                                                )
                                                or []
                                            ),
                                            "preserve": [
                                                "exact signature",
                                                "validated sibling callables",
                                            ],
                                            "postconditions": list(
                                                (file_stage.metadata or {}).get(
                                                    "validation_steps"
                                                )
                                                or []
                                            ),
                                        },
                                    )
                                    repair_model = model_for_project_edit_stage(
                                        repair_stage,
                                        settings,
                                        selected_model=model,
                                    )
                                    if callable(status_callback):
                                        status_callback(
                                            f"Repairing only {symbol} in "
                                            f"{Path(target_path).name}; callable attempt "
                                            f"{callable_attempt}/2"
                                        )
                                    replacement = query_prompt_text(
                                        model=repair_model,
                                        system_prompt=repair_stage.system_prompt,
                                        user_prompt=repair_stage.user_prompt + repair_feedback,
                                        num_ctx=repair_stage.num_ctx,
                                        num_predict=repair_stage.num_predict,
                                        timeout=repair_stage.timeout,
                                        prefer_coder=repair_stage.prefer_coder,
                                        coder_preference=repair_stage.coder_preference,
                                        think=False,
                                        response_format="",
                                        temperature=0.0,
                                        progress_callback=model_heartbeat(
                                            f"Function repair {symbol}"
                                        ),
                                    )
                                    repaired_files, repair_errors = (
                                        apply_project_edit_generated_symbol_repair(
                                            provisional_files,
                                            path=target_path,
                                            symbol=symbol,
                                            replacement_response=replacement or "",
                                            forbidden_names=list(
                                                repair_contract.get(
                                                    "forbidden_names"
                                                )
                                                or []
                                            ),
                                        )
                                    )
                                    bounded_file_state.setdefault(
                                        "reasoning_gaps",
                                        [],
                                    ).append({
                                        "stage": "artifact_symbol_repair",
                                        "file": str(target_path),
                                        "symbol": symbol,
                                        "attempt": callable_attempt,
                                        "model": repair_model,
                                        "response_characters": len(
                                            replacement or ""
                                        ),
                                        "validator_errors": list(repair_errors),
                                        "fallback_action": (
                                            "splice repaired callable and revalidate file"
                                            if not repair_errors
                                            else "retry only the rejected callable"
                                        ),
                                    })
                                    if not repair_errors:
                                        provisional_files = repaired_files
                                        break
                                    repair_feedback = (
                                        "\n\nThe prior callable was rejected. Return the "
                                        "same exact signature with these failures corrected:\n- "
                                        + "\n- ".join(repair_errors[:3])
                                    )
                                if repair_errors:
                                    symbol_repair_errors.extend(repair_errors)
                                    break
                            if not symbol_repair_errors:
                                output_source = next(
                                    source
                                    for path_text, _original, source in provisional_files
                                    if Path(path_text).resolve()
                                    == Path(target_path).resolve()
                                )
                                output_source, errors = (
                                    parse_project_edit_generated_file(
                                        output_source,
                                        path=target_path,
                                        expected_public_symbols=list(
                                            (file_stage.metadata or {}).get(
                                                "expected_public_symbols"
                                            )
                                            or []
                                        ),
                                    )
                                )
                            else:
                                errors = symbol_repair_errors
                        if not errors:
                            inferred_dependencies = (
                                infer_project_edit_generated_dependencies(
                                    output_source,
                                    path=target_path,
                                    project_root=project_root,
                                    generated_files=generated_files,
                                )
                            )
                            declared_dependencies = list(
                                (file_stage.metadata or {}).get("depends_on") or []
                            )
                            newly_inferred = [
                                dependency
                                for dependency in inferred_dependencies
                                if dependency not in declared_dependencies
                            ]
                            if newly_inferred:
                                declared_dependencies.extend(newly_inferred)
                                file_stage.metadata["depends_on"] = declared_dependencies
                                if callable(status_callback):
                                    status_callback(
                                        f"Added verified generated dependency edges for "
                                        f"{Path(target_path).name}: "
                                        + ", ".join(newly_inferred)
                                    )
                            integration_errors = validate_project_edit_generated_module_graph(
                                output_source,
                                path=target_path,
                                project_root=project_root,
                                generated_files=generated_files,
                                declared_dependencies=declared_dependencies,
                            )
                            if integration_errors:
                                errors = [
                                    "Integration architect rejected the file: " + error
                                    for error in integration_errors
                                ]
                        if not errors:
                            if callable(status_callback):
                                status_callback(
                                    f"Integration architect accepted {Path(target_path).name}; "
                                    "declared imports and exports remain closed"
                                )
                            break
                        rejected_source = str(response or "").strip()
                        rejected_source = re.sub(
                            r"^```(?:python|py)?\s*|\s*```$",
                            "",
                            rejected_source,
                            flags=re.IGNORECASE,
                        )
                        repeated_source = bool(
                            previous_rejected_source
                            and rejected_source == previous_rejected_source
                        )
                        previous_rejected_source = rejected_source
                        file_stage.coder_preference = "standard"
                        file_stage.num_ctx = max(file_stage.num_ctx, 8192)
                        file_stage.num_predict = -1
                        file_stage.timeout = max(file_stage.timeout, 180)
                        if callable(status_callback):
                            status_callback(
                                f"Rejected {Path(target_path).name}; integration notes returned to its "
                                "file worker: " + "; ".join(errors[:2])
                            )
                        bounded_file_state.setdefault("reasoning_gaps", []).append({
                            "stage": "artifact_file_generation",
                            "file": str(target_path),
                            "attempt": attempt,
                            "model": stage_model,
                            "response_characters": len(response or ""),
                            "validator_errors": list(errors),
                            "fallback_action": (
                                "retry the same bounded file with deterministic integration notes"
                                if attempt < 3
                                else "return the unresolved file contract to architecture"
                            ),
                        })
                        if repeated_source:
                            if callable(status_callback):
                                status_callback(
                                    f"Stopping identical full-file retries for "
                                    f"{Path(target_path).name}; escalating the unchanged "
                                    "contract failure"
                                )
                            break
                    if errors:
                        bounded_file_state["generation_errors"] = list(errors)
                        return None, None
                    generated_files.append((target_path, original_source, output_source))
                    interface_readback = summarize_project_edit_generated_interface(
                        target_path,
                        output_source,
                    )
                    dependency_sources.append(
                        f"Validated interface readback: {interface_readback}\n"
                        f"File: {target_path}\n```python\n{output_source}\n```"
                    )
                    if callable(status_callback):
                        status_callback(
                            f"Checkpointed {Path(target_path).name}; {interface_readback}"
                        )
                generated_files, cycle_fixes = stabilize_project_edit_import_cycles(
                    generated_files,
                    project_root=project_root,
                )
                if cycle_fixes and callable(status_callback):
                    status_callback(
                        "Stabilized generated project-local import cycles: "
                        + "; ".join(cycle_fixes)
                    )
                generated_files, symbol_fixes = resolve_project_edit_cross_file_symbols(
                    generated_files,
                    project_root=project_root,
                )
                if symbol_fixes and callable(status_callback):
                    status_callback(
                        "Wired uniquely owned generated symbols: " + "; ".join(symbol_fixes)
                    )
                generated_files, docstring_fixes = ensure_project_edit_requested_docstrings(
                    generated_files,
                    request_prompt=question,
                    force=bool(bounded_file_state.get("manifest_required")),
                )
                if docstring_fixes and callable(status_callback):
                    status_callback(
                        "Completed requested public docstrings: " + "; ".join(docstring_fixes)
                    )
                generated_files, cleanup_fixes = enforce_project_edit_explicit_cleanup(
                    generated_files,
                    request_prompt=question,
                )
                if cleanup_fixes and callable(status_callback):
                    status_callback("Applied explicit scoped cleanup: " + "; ".join(cleanup_fixes))
                generated_files, lifecycle_fixes = normalize_project_edit_async_test_lifecycle(
                    generated_files
                )
                if lifecycle_fixes and callable(status_callback):
                    status_callback(
                        "Normalized generated async test lifecycle: "
                        + "; ".join(lifecycle_fixes)
                    )
                generated_files, standard_import_fixes = resolve_project_edit_standard_library_symbols(
                    generated_files
                )
                if standard_import_fixes and callable(status_callback):
                    status_callback(
                        "Resolved generated standard-library symbols: "
                        + "; ".join(standard_import_fixes)
                    )
                generated_files, unused_import_fixes = remove_project_edit_unused_imports(
                    generated_files
                )
                if unused_import_fixes and callable(status_callback):
                    status_callback(
                        "Removed generated unused imports: " + "; ".join(unused_import_fixes)
                    )
                generated_files, test_contract_fixes = enforce_project_edit_requested_test_contracts(
                    generated_files,
                    request_prompt=question,
                )
                if test_contract_fixes and callable(status_callback):
                    status_callback(
                        "Materialized explicit generated-test contracts: "
                        + "; ".join(test_contract_fixes)
                    )
                generated_files, format_fixes = format_project_edit_generated_python(
                    generated_files
                )
                if format_fixes and callable(status_callback):
                    status_callback("Normalized generated Python: " + "; ".join(format_fixes))
                bounded_file_state["generated_files"] = generated_files
                bounded_file_state["file_stages"] = file_stages
                candidate = build_project_edit_multi_file_candidate(generated_files)
                candidate_preview = preview_project_edit_agent_response(
                    candidate,
                    project_root=project_root,
                    request_prompt=question,
                )
                return candidate, candidate_preview

            def replan_bounded_architecture(validation_errors):
                if bounded_file_state.get("architecture_replanned"):
                    return None, None
                bounded_file_state["architecture_replanned"] = True
                failure_text = "\n".join(f"- {item}" for item in validation_errors)
                if callable(status_callback):
                    status_callback(
                        "Returning unchanged or structural failures to the architecture worker; "
                        "revising module ownership before further code repair"
                    )
                manifest, manifest_errors, requirement_ledger = synthesize_artifact_architecture(
                    approved_plan_text
                    + "\n\nThe prior approved architecture failed during isolated generation or "
                    "integration. Revise file boundaries, API ownership, and validation steps to "
                    "eliminate these failures:\n"
                    + failure_text
                )
                if manifest_errors:
                    bounded_file_state["manifest_errors"] = list(manifest_errors)
                    return None, None
                bounded_file_state["override_manifest"] = manifest
                bounded_file_state["override_requirement_ledger"] = requirement_ledger
                bounded_file_state["generated_files"] = []
                bounded_file_state["file_stages"] = []
                bounded_file_state["manifest"] = manifest
                bounded_file_state["requirement_ledger"] = requirement_ledger
                bounded_symbol_repair_attempts.clear()
                return build_from_bounded_file_workers()

            def repair_bounded_file_workers(validation_errors):
                generated_files = list(bounded_file_state.get("generated_files") or [])
                if not generated_files:
                    return None, None
                cross_file_notes = build_project_edit_cross_file_failure_notes(
                    generated_files,
                    validation_errors,
                )
                if cross_file_notes and not bounded_file_state.get("architecture_replanned"):
                    if callable(status_callback):
                        status_callback(
                            "Integration coordinator found a shared cross-file contract failure; "
                            "returning one ownership report to the architecture worker"
                        )
                    return replan_bounded_architecture([
                        *validation_errors,
                        *cross_file_notes,
                    ])
                exhausted_production = [
                    symbol
                    for symbol, attempts in bounded_symbol_repair_attempts.items()
                    if attempts >= 2
                    and not symbol.lower().startswith("test")
                    and ".test_" not in symbol.lower()
                ]
                if (
                    exhausted_production
                    and not bounded_file_state.get("architecture_replanned")
                ):
                    if callable(status_callback):
                        status_callback(
                            "Production repair budget was exhausted while package validation "
                            "still failed; escalating the shared contract to architecture"
                        )
                    return replan_bounded_architecture([
                        *validation_errors,
                        "Production callable repairs did not resolve the package contract: "
                        + ", ".join(exhausted_production),
                    ])
                failure_text = "\n".join(f"- {item}" for item in validation_errors)
                if (
                    "permissionerror" in failure_text.lower()
                    or "access is denied" in failure_text.lower()
                ):
                    isolated_files, isolation_fixes = isolate_project_edit_generated_test_fixture(
                        generated_files
                    )
                    if isolation_fixes:
                        isolated_files, _format_fixes = format_project_edit_generated_python(
                            isolated_files
                        )
                        bounded_file_state["generated_files"] = isolated_files
                        if callable(status_callback):
                            status_callback(
                                "Precisely isolated generated test fixture: "
                                + "; ".join(isolation_fixes)
                            )
                        candidate = build_project_edit_multi_file_candidate(isolated_files)
                        candidate_preview = preview_project_edit_agent_response(
                            candidate,
                            project_root=project_root,
                            request_prompt=question,
                        )
                        return candidate, candidate_preview
                failure_symbol = resolve_project_edit_failure_symbol(
                    generated_files,
                    validation_errors,
                    deprioritized_symbols={
                        symbol
                        for symbol, attempts in bounded_symbol_repair_attempts.items()
                        if attempts >= 2
                    },
                )
                if failure_symbol and int(
                    bounded_symbol_repair_attempts.get(failure_symbol["symbol"], 0)
                ) >= 2:
                    failure_symbol = {}
                if failure_symbol:
                    target_path = failure_symbol["path"]
                    target_symbol = failure_symbol["symbol"]
                    symbol_attempt = int(bounded_symbol_repair_attempts.get(target_symbol, 0)) + 1
                    bounded_symbol_repair_attempts[target_symbol] = symbol_attempt
                    manifest_item = next(
                        (
                            item
                            for item in bounded_file_state.get("manifest") or []
                            if Path(str(item.get("absolute_path") or "")).resolve()
                            == Path(target_path).resolve()
                        ),
                        {},
                    )
                    repair_contract, contract_errors = build_project_edit_function_repair_contract(
                        generated_files,
                        target=failure_symbol,
                        validation_errors=validation_errors,
                        objective=question,
                        requirements=list(manifest_item.get("requirements") or []),
                    )
                    if contract_errors:
                        if callable(status_callback):
                            status_callback(
                                f"Could not isolate {target_symbol}: "
                                + "; ".join(contract_errors[:2])
                            )
                        candidate = build_project_edit_multi_file_candidate(generated_files)
                        return candidate, preview_project_edit_agent_response(
                            candidate,
                            project_root=project_root,
                            request_prompt=question,
                        )
                    diagnosis_stage = build_project_edit_function_repair_plan_stage(
                        repair_contract
                    )
                    diagnosis_stage.model_tier = "local_code"
                    diagnosis_stage.prefer_coder = True
                    diagnosis_stage.coder_preference = "standard"
                    repair_plan = {}
                    repair_plan_errors = []
                    diagnosis_feedback = ""
                    for diagnosis_attempt in range(1, 3):
                        if diagnosis_attempt >= 2:
                            diagnosis_stage.model_tier = "local_code"
                            diagnosis_stage.prefer_coder = True
                            diagnosis_stage.coder_preference = "standard"
                        diagnosis_model = model_for_project_edit_stage(
                            diagnosis_stage,
                            settings,
                            selected_model=model,
                        )
                        if callable(status_callback):
                            status_callback(
                                f"Diagnosing {target_symbol}; {diagnosis_model}; "
                                f"attempt {diagnosis_attempt}/2; deriving root cause, algorithm, "
                                "and postconditions before coding"
                            )
                        diagnosis_response = query_prompt_text(
                            model=diagnosis_model,
                            system_prompt=diagnosis_stage.system_prompt,
                            user_prompt=diagnosis_stage.user_prompt + diagnosis_feedback,
                            num_ctx=diagnosis_stage.num_ctx,
                            num_predict=diagnosis_stage.num_predict,
                            timeout=diagnosis_stage.timeout,
                            prefer_coder=diagnosis_stage.prefer_coder,
                            coder_preference=diagnosis_stage.coder_preference,
                            think=False,
                            response_format=diagnosis_stage.response_format,
                            temperature=0.0,
                            progress_callback=model_heartbeat(
                                f"Repair diagnosis {target_symbol}"
                            ),
                        )
                        repair_plan, repair_plan_errors = (
                            parse_project_edit_function_repair_plan(
                                diagnosis_response or "",
                                contract=repair_contract,
                            )
                        )
                        if not repair_plan_errors:
                            break
                        if callable(status_callback):
                            status_callback(
                                f"Rejected repair diagnosis for {target_symbol}: "
                                + "; ".join(repair_plan_errors[:2])
                            )
                        diagnosis_feedback = (
                            "\n\nThe prior diagnosis was rejected. Return a corrected concise JSON "
                            "micro-plan that fixes these exact contract violations:\n- "
                            + "\n- ".join(repair_plan_errors[:3])
                        )
                    if repair_plan_errors:
                        repair_plan = dict(repair_plan or {})
                        repair_plan["root_cause"] = str(
                            repair_plan.get("root_cause")
                            or repair_contract.get("failure")
                            or ""
                        )
                        repair_plan["algorithm_steps"] = list(
                            repair_plan.get("algorithm_steps") or []
                        ) + [
                            "Mandatory rejected-plan correction: " + error
                            for error in repair_plan_errors
                        ]
                        repair_plan["preserve"] = list(
                            repair_plan.get("preserve") or []
                        ) + ["exact callable signature"]
                        repair_plan["postconditions"] = list(
                            repair_plan.get("postconditions") or []
                        ) + ["the reported disposable failure no longer occurs"]
                    repair_stage = build_project_edit_function_repair_stage(
                        repair_contract,
                        attempt=symbol_attempt,
                        repair_plan=repair_plan,
                    )
                    repair_model = model_for_project_edit_stage(
                        repair_stage,
                        settings,
                        selected_model=model,
                    )
                    if callable(status_callback):
                        status_callback(
                            f"Function contract isolated {target_symbol}; {repair_model}; "
                            f"attempt {min(symbol_attempt, 2)}/2; preserving exact signature, "
                            f"{len(repair_contract.get('sibling_symbols') or [])} sibling callables, "
                            f"and {len(generated_files) - 1} other files"
                        )
                    response = query_prompt_text(
                        model=repair_model,
                        system_prompt=repair_stage.system_prompt,
                        user_prompt=repair_stage.user_prompt,
                        num_ctx=repair_stage.num_ctx,
                        num_predict=repair_stage.num_predict,
                        timeout=repair_stage.timeout,
                        prefer_coder=True,
                        coder_preference=repair_stage.coder_preference,
                        think=False,
                        response_format="",
                        temperature=0.0,
                        progress_callback=model_heartbeat(
                            f"Callable repair {target_symbol}"
                        ),
                    )
                    repaired_files, repair_errors = apply_project_edit_generated_symbol_repair(
                        generated_files,
                        path=target_path,
                        symbol=target_symbol,
                        replacement_response=response or "",
                        forbidden_names=list(repair_contract.get("forbidden_names") or []),
                    )
                    if repair_errors:
                        if callable(status_callback):
                            status_callback(
                                f"Rejected precise repair for {target_symbol}: "
                                + "; ".join(repair_errors[:2])
                            )
                        candidate = build_project_edit_multi_file_candidate(generated_files)
                        candidate_preview = preview_project_edit_agent_response(
                            candidate,
                            project_root=project_root,
                            request_prompt=question,
                        )
                        return candidate, candidate_preview
                    repaired_files, _symbol_fixes = resolve_project_edit_cross_file_symbols(
                        repaired_files,
                        project_root=project_root,
                    )
                    repaired_files, _cleanup_fixes = enforce_project_edit_explicit_cleanup(
                        repaired_files,
                        request_prompt=question,
                    )
                    repaired_files, _standard_import_fixes = resolve_project_edit_standard_library_symbols(
                        repaired_files
                    )
                    repaired_files, _unused_import_fixes = remove_project_edit_unused_imports(
                        repaired_files
                    )
                    repaired_files, _test_contract_fixes = enforce_project_edit_requested_test_contracts(
                        repaired_files,
                        request_prompt=question,
                    )
                    repaired_files, _format_fixes = format_project_edit_generated_python(
                        repaired_files
                    )
                    bounded_file_state["generated_files"] = repaired_files
                    candidate = build_project_edit_multi_file_candidate(repaired_files)
                    candidate_preview = preview_project_edit_agent_response(
                        candidate,
                        project_root=project_root,
                        request_prompt=question,
                    )
                    return candidate, candidate_preview
                mentioned = [
                    index
                    for index, (target_path, _original, _generated) in enumerate(generated_files)
                    if Path(target_path).name.lower() in failure_text.lower()
                ]
                placeholder_methods = re.findall(
                    r"Generated test methods (?:are placeholders|need stronger behavioral proof):\s*"
                    r"([A-Za-z0-9_., ]+)",
                    failure_text,
                )
                placeholder_names = {
                    name.rsplit(".", 1)[-1].strip()
                    for group in placeholder_methods
                    for name in group.split(",")
                    if name.strip()
                }
                if placeholder_names:
                    mentioned.extend(
                        index
                        for index, (target_path, _original, generated) in enumerate(generated_files)
                        if (
                            Path(target_path).name.startswith("test_")
                            or "tests" in {part.lower() for part in Path(target_path).parts}
                        )
                        and any(f"def {name}(" in generated for name in placeholder_names)
                        and index not in mentioned
                    )
                test_indexes = [
                    index
                    for index in mentioned
                    if Path(generated_files[index][0]).name.startswith("test_")
                ]
                isolated_test_failure = (
                    "permissionerror" in failure_text.lower()
                    or "access is denied" in failure_text.lower()
                )
                structural_failure = any(
                    marker in failure_text.lower()
                    for marker in (
                        "new import could not be resolved",
                        "missing its manifest dependency edge",
                        "project-local import does not expose",
                        "generated production callables are placeholders",
                        "executes behavior at import time",
                    )
                )
                production_indexes = [
                    index
                    for index in mentioned
                    if not _is_test_path(Path(generated_files[index][0]))
                ]
                target_index = (
                    production_indexes[0]
                    if structural_failure and production_indexes
                    else test_indexes[0]
                    if test_indexes and (
                        isolated_test_failure
                        or "failed to import test module" in failure_text.lower()
                        or "disposable generated-patch validation failed" in failure_text.lower()
                    )
                    else mentioned[0]
                    if mentioned
                    else 0
                )
                target_path, original_source, current_source = generated_files[target_index]
                sibling_context = "\n\n".join(
                    f"File: {path_text}\n```python\n{generated}\n```"
                    for path_text, _original, generated in generated_files
                )
                repair_stage = list(bounded_file_state.get("file_stages") or [])[target_index][2]
                repair_stage.label = f"Repairing {Path(target_path).name} from disposable validation"
                repair_stage.coder_preference = "small"
                repair_stage.num_ctx = 6144
                repair_stage.num_predict = 1100
                repair_stage.timeout = 90
                repair_stage.user_prompt = f"""User objective:
{question}

File owned by this repair:
{target_path}

Current generated source:
```python
{current_source}
```

Complete generated multi-file candidate:
{sibling_context[-6000:]}

Disposable validation failures:
{failure_text}

Return the complete corrected source for the owned file only. Fix the reported failure at its cause while preserving
the passing behavior in all sibling files. For circular imports, move project-local imports inside the function that
uses them. Tests must use disposable temporary paths and may never write to a user's real home directory.
Return raw Python only, without Markdown, JSON, or commentary.
"""
                repair_model = model_for_project_edit_stage(
                    repair_stage,
                    settings,
                    selected_model=model,
                )
                if callable(status_callback):
                    status_callback(
                        f"{repair_stage.label}; {repair_model}; preserving "
                        f"{len(generated_files) - 1} passing file(s)"
                    )
                response = query_prompt_text(
                    model=repair_model,
                    system_prompt=repair_stage.system_prompt,
                    user_prompt=repair_stage.user_prompt,
                    num_ctx=repair_stage.num_ctx,
                    num_predict=repair_stage.num_predict,
                    timeout=repair_stage.timeout,
                    prefer_coder=True,
                    coder_preference=repair_stage.coder_preference,
                    think=False,
                    response_format="",
                    temperature=0.0,
                    progress_callback=model_heartbeat(
                        f"Integration file repair {Path(target_path).name}"
                    ),
                )
                corrected, parse_errors = parse_project_edit_generated_file(
                    response or "",
                    path=target_path,
                    expected_public_symbols=list(
                        (repair_stage.metadata or {}).get("expected_public_symbols") or []
                    ),
                )
                if not parse_errors:
                    parse_errors = validate_project_edit_generated_module_graph(
                        corrected,
                        path=target_path,
                        project_root=project_root,
                        generated_files=[
                            item for item in generated_files
                            if Path(item[0]).resolve() != Path(target_path).resolve()
                        ],
                        declared_dependencies=list(
                            (repair_stage.metadata or {}).get("depends_on") or []
                        ),
                    )
                if parse_errors:
                    if callable(status_callback):
                        status_callback(
                            f"Rejected bounded repair for {Path(target_path).name}: "
                            + "; ".join(parse_errors[:2])
                        )
                    return None, None
                generated_files[target_index] = (target_path, original_source, corrected)
                generated_files, cycle_fixes = stabilize_project_edit_import_cycles(
                    generated_files,
                    project_root=project_root,
                )
                if cycle_fixes and callable(status_callback):
                    status_callback(
                        "Stabilized repaired project-local import cycles: "
                        + "; ".join(cycle_fixes)
                    )
                generated_files, symbol_fixes = resolve_project_edit_cross_file_symbols(
                    generated_files,
                    project_root=project_root,
                )
                if symbol_fixes and callable(status_callback):
                    status_callback(
                        "Wired repaired generated symbols: " + "; ".join(symbol_fixes)
                    )
                generated_files, docstring_fixes = ensure_project_edit_requested_docstrings(
                    generated_files,
                    request_prompt=question,
                    force=bool(bounded_file_state.get("manifest_required")),
                )
                bounded_file_state["generated_files"] = generated_files
                candidate = build_project_edit_multi_file_candidate(generated_files)
                candidate_preview = preview_project_edit_agent_response(
                    candidate,
                    project_root=project_root,
                    request_prompt=question,
                )
                return candidate, candidate_preview

            def build_from_bounded_leaf_workers(work_units=None):
                work_units = work_units or compile_project_edit_leaf_work_units(
                    edit_plan,
                    approved_plan_text,
                )
                if work_units is None:
                    return None, None
                generated = {}

                # 1. Run 'define' stage sequentially (integrate and test depend on it)
                define_errors = []
                expected_symbol_define = work_units.helper_name
                for attempt in range(1, 3):
                    leaf_stage = build_project_edit_leaf_stage(
                        work_units,
                        kind="define",
                        attempt=attempt,
                        objective=question,
                        approved_plan=approved_plan_text,
                        dependency_source="",
                    )
                    leaf_model = model_for_project_edit_stage(
                        leaf_stage,
                        settings,
                        selected_model=model,
                    )
                    if callable(status_callback):
                        status_callback(
                            f"{leaf_stage.label}; unit 1/3; {leaf_model}; "
                            "source-only subagent"
                        )
                    leaf_response = query_prompt_text(
                        model=leaf_model,
                        system_prompt=leaf_stage.system_prompt,
                        user_prompt=leaf_stage.user_prompt,
                        num_ctx=leaf_stage.num_ctx,
                        num_predict=leaf_stage.num_predict,
                        timeout=leaf_stage.timeout,
                        prefer_coder=leaf_stage.prefer_coder,
                        coder_preference=leaf_stage.coder_preference,
                        think=False,
                        response_format=leaf_stage.response_format,
                        temperature=0.0,
                    )
                    if not leaf_response:
                        define_errors = ["The define subagent returned no source."]
                        continue
                    leaf_source, define_errors = parse_project_edit_leaf_source(
                        leaf_response,
                        kind="define",
                        expected_symbol=expected_symbol_define,
                        required_reference="",
                        objective=question,
                    )
                    if not define_errors:
                        generated["define"] = leaf_source
                        break
                    if callable(status_callback):
                        status_callback(
                            f"Rejected bounded define unit: "
                            + "; ".join(define_errors[:2])
                        )
                if define_errors or "define" not in generated:
                    return None, None

                # 2. Run 'integrate' and 'test' stages concurrently
                import concurrent.futures

                def run_stage(kind, leaf_index):
                    expected_symbol = (
                        work_units.integration_symbol
                        if kind == "integrate"
                        else "test_generated_behavior"
                    )
                    required_reference = work_units.helper_name
                    dependency_source = generated["define"]
                    errors = []

                    for attempt in range(1, 3):
                        leaf_stage = build_project_edit_leaf_stage(
                            work_units,
                            kind=kind,
                            attempt=attempt,
                            objective=question,
                            approved_plan=approved_plan_text,
                            dependency_source=dependency_source,
                        )
                        leaf_model = model_for_project_edit_stage(
                            leaf_stage,
                            settings,
                            selected_model=model,
                        )
                        if callable(status_callback):
                            status_callback(
                                f"{leaf_stage.label}; unit {leaf_index}/3; {leaf_model}; "
                                "source-only subagent"
                            )
                        leaf_response = query_prompt_text(
                            model=leaf_model,
                            system_prompt=leaf_stage.system_prompt,
                            user_prompt=leaf_stage.user_prompt,
                            num_ctx=leaf_stage.num_ctx,
                            num_predict=leaf_stage.num_predict,
                            timeout=leaf_stage.timeout,
                            prefer_coder=leaf_stage.prefer_coder,
                            coder_preference=leaf_stage.coder_preference,
                            think=False,
                            response_format=leaf_stage.response_format,
                            temperature=0.0,
                        )
                        if not leaf_response:
                            errors = [f"The {kind} subagent returned no source."]
                            continue
                        leaf_source, errors = parse_project_edit_leaf_source(
                            leaf_response,
                            kind=kind,
                            expected_symbol=expected_symbol,
                            required_reference=required_reference,
                            objective=question,
                        )
                        if not errors:
                            return leaf_source, None
                        if callable(status_callback):
                            status_callback(
                                f"Rejected bounded {kind} unit: "
                                + "; ".join(errors[:2])
                            )
                    return None, errors

                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    future_integrate = executor.submit(run_stage, "integrate", 2)
                    future_test = executor.submit(run_stage, "test", 3)

                    integrate_source, integrate_errors = future_integrate.result()
                    test_source, test_errors = future_test.result()

                if integrate_errors or test_errors or integrate_source is None or test_source is None:
                    return None, None

                generated["integrate"] = integrate_source
                generated["test"] = test_source

                candidate = build_project_edit_leaf_candidate(
                    work_units,
                    helper_source=generated["define"],
                    integration_source=generated["integrate"],
                    test_source=generated["test"],
                )
                candidate_preview = preview_project_edit_agent_response(
                    candidate,
                    project_root=project_root,
                    request_prompt=question,
                )
                return candidate, candidate_preview

            stage_outputs = []
            approved_preview = None
            for index, stage in enumerate(stages, start=1):
                stage_model = model_for_project_edit_stage(stage, settings, selected_model=model)
                stage_user_prompt = stage.user_prompt
                if approved_plan_text and stage.key == "patch_generation":
                    stage_user_prompt += (
                        "\n\nUser-approved grounded implementation plan:\n"
                        + approved_plan_text[:10000]
                    )
                if stage_outputs:
                    prior_handoff = "\n\n".join(output for _prior_stage, output in stage_outputs[-2:])
                    stage_user_prompt += (
                        "\n\nGrounded outputs from completed earlier stages:\n"
                        + prior_handoff[:10000]
                    )
                output = None
                bounded_attempted = bool(approved_work_units and stage.key == "patch_generation")
                bounded_files_attempted = False
                if stage.key == "patch_generation":
                    bounded_files_attempted = bool(
                        build_project_edit_file_generation_stages(edit_plan)
                        or build_project_edit_artifact_manifest_stage(
                            edit_plan,
                            approved_plan=approved_plan_text,
                        )
                    )
                    if bounded_files_attempted:
                        if callable(status_callback):
                            status_callback(
                                "Using bounded multi-file workers; generating dependency files, "
                                "consumers, then focused tests"
                            )
                        output, _bounded_preview = build_from_bounded_file_workers()
                        if output is None and bounded_file_state.get("generation_errors"):
                            output, _bounded_preview = replan_bounded_architecture(
                                list(bounded_file_state.get("generation_errors") or [])
                            )
                        if output is None and bounded_file_state.get("manifest_required"):
                            errors = list(
                                bounded_file_state.get("manifest_errors")
                                or bounded_file_state.get("generation_errors")
                                or []
                            )
                            output = json.dumps({
                                "changes": [],
                                "report": {
                                    "changed": [],
                                    "reused": [],
                                    "verification": [],
                                    "remaining_gaps": errors or ["Bounded artifact generation was incomplete."],
                                    "requirement_coverage": [],
                                },
                                "blocked_reason": (
                                    "The validated artifact manifest or one of its bounded file workers failed."
                                ),
                            })
                            if callable(status_callback):
                                status_callback(
                                    "Bounded artifact generation stopped safely; whole-patch fallback is disabled"
                                )
                        elif output is None and callable(status_callback):
                            status_callback(
                                "Bounded multi-file generation was incomplete; falling back to the whole-patch coder"
                            )
                if bounded_attempted:
                    if callable(status_callback):
                        status_callback("Using approved indexed boundaries; skipping speculative whole-patch generation")
                    output, _bounded_preview = build_from_bounded_leaf_workers(approved_work_units)
                    if output is None and callable(status_callback):
                        status_callback("Bounded generation was incomplete; falling back to the whole-patch coder")
                if output is None:
                    if callable(status_callback):
                        status_callback(
                            f"{stage.label} ({index}/{len(stages)}; {stage.resource_lane}; "
                            f"{stage.model_tier}; {len(stage_user_prompt)} chars)"
                        )
                        status_callback(
                            f"Waiting on {stage_model} for {stage.label}; UI should remain responsive"
                        )
                    output = query_prompt_text(
                        model=stage_model,
                        system_prompt=stage.system_prompt,
                        user_prompt=stage_user_prompt,
                        num_ctx=stage.num_ctx,
                        num_predict=stage.num_predict,
                        timeout=stage.timeout,
                        prefer_coder=stage.prefer_coder,
                        coder_preference=stage.coder_preference,
                        think=False,
                        response_format=stage.response_format or None,
                        progress_callback=model_heartbeat(stage.label),
                    )
                if output:
                    output = output.strip()
                    if stage.key == "target_selection_plan":
                        plan_errors = validate_project_edit_plan_output(edit_plan, output)
                        if plan_errors:
                            if callable(status_callback):
                                status_callback(
                                    "Planning handoff was not grounded in project evidence; "
                                    "using the deterministic target plan"
                                )
                            output = render_grounded_project_edit_handoff(
                                edit_plan,
                                rejected_plan_errors=plan_errors,
                            )
                    if stage.key == "patch_generation":
                        project_roots = list(edit_plan.discovery.get("project_roots") or [])
                        project_root = project_roots[0] if project_roots else str(Path(path).parent)

                        def repair_structured_syntax(candidate: str) -> str:
                            for syntax_attempt in range(1, 3):
                                issues = inspect_project_edit_structured_syntax(candidate)
                                if not issues:
                                    break
                                issue = issues[0]
                                syntax_stage = build_project_edit_syntax_repair_stage(
                                    issue,
                                    attempt=syntax_attempt,
                                )
                                syntax_model = model_for_project_edit_stage(
                                    syntax_stage,
                                    settings,
                                    selected_model=model,
                                )
                                if callable(status_callback):
                                    status_callback(
                                        f"{syntax_stage.label}; {syntax_model}; "
                                        f"{issue.get('target_symbol') or Path(str(issue.get('path') or '')).name}"
                                    )
                                syntax_response = query_prompt_text(
                                    model=syntax_model,
                                    system_prompt=syntax_stage.system_prompt,
                                    user_prompt=syntax_stage.user_prompt,
                                    num_ctx=syntax_stage.num_ctx,
                                    num_predict=syntax_stage.num_predict,
                                    timeout=syntax_stage.timeout,
                                    prefer_coder=syntax_stage.prefer_coder,
                                    coder_preference=syntax_stage.coder_preference,
                                    think=False,
                                    response_format=syntax_stage.response_format,
                                    progress_callback=model_heartbeat(
                                        f"Syntax repair {issue.get('target_symbol') or 'file'}"
                                    ),
                                )
                                if not syntax_response:
                                    break
                                candidate = apply_project_edit_syntax_repair(
                                    candidate,
                                    change_index=int(issue.get("change_index") or 0),
                                    repair_response=syntax_response,
                                )
                            return candidate

                        preview = preview_project_edit_agent_response(
                            output,
                            project_root=project_root,
                            request_prompt=question,
                        )
                        best_output = output
                        best_preview = preview
                        best_preview_score = project_edit_preview_error_score(list(preview.errors))
                        core_contract_failure = project_edit_has_core_contract_failure(
                            list(preview.errors),
                            question,
                        )
                        if not preview.ok and core_contract_failure and not bounded_attempted:
                            if callable(status_callback):
                                status_callback(
                                    "Initial coder missed the core implementation contract; "
                                    "compiling bounded helper, integration, and test units"
                                )
                            leaf_output, leaf_preview = build_from_bounded_leaf_workers()
                            if leaf_output is not None and leaf_preview is not None:
                                output = leaf_output
                                preview = leaf_preview
                                preview_score = project_edit_preview_error_score(list(preview.errors))
                                if preview_score < best_preview_score:
                                    best_output = output
                                    best_preview = preview
                                    best_preview_score = preview_score
                                core_contract_failure = project_edit_has_core_contract_failure(
                                    list(preview.errors),
                                    question,
                                )
                        if not preview.ok and not core_contract_failure:
                            output = repair_structured_syntax(output)
                            preview = preview_project_edit_agent_response(
                                output,
                                project_root=project_root,
                                request_prompt=question,
                            )
                            preview_score = project_edit_preview_error_score(list(preview.errors))
                            if preview_score < best_preview_score:
                                best_output = output
                                best_preview = preview
                                best_preview_score = preview_score
                        if bounded_files_attempted:
                            prior_bounded_error_signature = ()
                            for bounded_repair_attempt in range(1, 9):
                                if preview.ok:
                                    break
                                current_error_signature = (
                                    project_edit_validation_failure_signature(
                                        list(preview.errors)
                                    )
                                )
                                if current_error_signature == prior_bounded_error_signature:
                                    replanned_output, replanned_preview = replan_bounded_architecture(
                                        list(preview.errors)
                                    )
                                    if replanned_output is not None and replanned_preview is not None:
                                        output = replanned_output
                                        preview = replanned_preview
                                        prior_bounded_error_signature = ()
                                        if callable(status_callback):
                                            status_callback(
                                                "Architecture replan completed; resumed validation "
                                                "from the revised generated package"
                                            )
                                        continue
                                    if callable(status_callback):
                                        status_callback(
                                            "Stopping precise repair because validation failures did not "
                                            "change and the architecture replan was exhausted"
                                        )
                                    break
                                prior_bounded_error_signature = current_error_signature
                                repaired_output, repaired_preview = repair_bounded_file_workers(
                                    list(preview.errors)
                                )
                                if repaired_output is None or repaired_preview is None:
                                    break
                                output = repaired_output
                                preview = repaired_preview
                                if callable(status_callback):
                                    status_callback(
                                        "Precise repair validation "
                                        f"({bounded_repair_attempt}/8): "
                                        + (
                                            "passed"
                                            if preview.ok
                                            else "; ".join(str(item) for item in preview.errors[:3])
                                        )
                                    )
                                preview_score = project_edit_preview_error_score(list(preview.errors))
                                if preview_score < best_preview_score:
                                    best_output = output
                                    best_preview = preview
                                    best_preview_score = preview_score
                        for repair_attempt in range(1, 6):
                            if preview.ok:
                                break
                            if bounded_files_attempted:
                                break
                            if callable(status_callback):
                                status_callback(
                                    f"Implementation quality gate found {len(preview.errors)} issue(s); "
                                    f"repairing ({repair_attempt}/5): "
                                    + "; ".join(str(error) for error in preview.errors[:3])
                                )
                            repair_stage = build_project_edit_repair_stage(
                                edit_plan,
                                output,
                                list(preview.errors),
                                attempt=repair_attempt,
                                approved_plan=approved_plan_text,
                            )
                            repair_model = model_for_project_edit_stage(
                                repair_stage,
                                settings,
                                selected_model=model,
                            )
                            repaired = query_prompt_text(
                                model=repair_model,
                                system_prompt=repair_stage.system_prompt,
                                user_prompt=repair_stage.user_prompt,
                                num_ctx=repair_stage.num_ctx,
                                num_predict=repair_stage.num_predict,
                                timeout=repair_stage.timeout,
                                prefer_coder=repair_stage.prefer_coder,
                                coder_preference=repair_stage.coder_preference,
                                think=False,
                                response_format=repair_stage.response_format or None,
                                progress_callback=model_heartbeat(
                                    f"Whole-patch repair {repair_attempt}/5"
                                ),
                            )
                            if not repaired:
                                break
                            output = repaired.strip()
                            preview = preview_project_edit_agent_response(
                                output,
                                project_root=project_root,
                                request_prompt=question,
                            )
                            core_contract_failure = project_edit_has_core_contract_failure(
                                list(preview.errors),
                                question,
                            )
                            if not preview.ok and not core_contract_failure:
                                output = repair_structured_syntax(output)
                                preview = preview_project_edit_agent_response(
                                    output,
                                    project_root=project_root,
                                    request_prompt=question,
                                )
                            preview_score = project_edit_preview_error_score(list(preview.errors))
                            if preview_score < best_preview_score:
                                best_output = output
                                best_preview = preview
                                best_preview_score = preview_score
                        if not preview.ok:
                            output = best_output
                            preview = best_preview
                            requirement_coverage = (
                                build_project_edit_requirement_coverage(
                                    list(bounded_file_state.get("manifest") or []),
                                    list(bounded_file_state.get("requirement_ledger") or []),
                                    validation_errors=list(preview.errors),
                                )
                                if bounded_file_state.get("manifest")
                                else []
                            )
                            bounded_file_state["requirement_coverage"] = requirement_coverage
                            output = (
                                "BLOCKED: The generated patch did not pass the implementation quality gate.\n\n"
                                + "\n".join(f"- {item}" for item in preview.errors)
                            )
                            if requirement_coverage:
                                output += "\n\nRequirement coverage:\n" + "\n".join(
                                    f"- {item['id']} [{item['status']}]: "
                                    f"{item['requirement']} | "
                                    + (
                                        "workflow="
                                        f"{', '.join(item.get('system_owners') or []) or 'missing'}"
                                        if item.get("scope") == "workflow"
                                        else (
                                            "production="
                                            f"{', '.join(item['production_owners']) or 'missing'} | tests="
                                            f"{', '.join(item['test_owners']) or 'missing'}"
                                        )
                                    )
                                    for item in requirement_coverage
                                )
                        else:
                            if bounded_file_state.get("manifest"):
                                requirement_coverage = build_project_edit_requirement_coverage(
                                    list(bounded_file_state.get("manifest") or []),
                                    list(bounded_file_state.get("requirement_ledger") or []),
                                )
                                bounded_file_state["requirement_coverage"] = requirement_coverage
                                try:
                                    structured_output = json.loads(output)
                                    structured_output.setdefault("report", {})[
                                        "requirement_coverage"
                                    ] = requirement_coverage
                                    output = json.dumps(structured_output, ensure_ascii=True)
                                except (TypeError, ValueError):
                                    pass
                            approved_preview = preview
                    stage_outputs.append((stage, output))
                    if callable(status_callback):
                        status_callback(f"{stage.label} completed")
                    continue
                if callable(status_callback):
                    status_callback(f"{stage.label} did not return before the current model timeout")
                if stage.key == "target_selection_plan":
                    output = render_grounded_project_edit_handoff(edit_plan)
                    stage_outputs.append((stage, output))
                break
            if stage_outputs:
                if not approved_plan_text and patch_stage is not None:
                    plan_output = stage_outputs[-1][1]
                    work_units = compile_project_edit_leaf_work_units(edit_plan, plan_output)
                    plan_payload = {
                        "type": "project_edit_plan",
                        "path": str(path or ""),
                        "question": str(question or ""),
                        "plan": plan_output,
                        "fingerprint": project_edit_plan_fingerprint(edit_plan),
                    }
                    if work_units is not None:
                        plan_payload["leaf_work_units"] = project_edit_leaf_work_units_handoff(
                            work_units
                        )
                    return (
                        "## Implementation Plan\n\n"
                        + plan_output
                        + "\n\nReview this plan, then use **Approve Plan** to generate a code preview. "
                        "No code or files have been changed.",
                        plan_payload,
                    )
                sections = []
                for stage, output in stage_outputs:
                    sections.append(f"## {stage.label}\n\n{output}")
                patch_payload = None
                if approved_preview is not None and approved_preview.ok:
                    patch_payload = {
                        "type": "project_changes",
                        "changes": [
                            {
                                "action": item.get("action"),
                                "path": item.get("path"),
                                "original_content": item.get("before", ""),
                                "new_content": item.get("after", ""),
                            }
                            for item in approved_preview.changes
                        ],
                        "requirement_coverage": list(
                            bounded_file_state.get("requirement_coverage") or []
                        ),
                        "reasoning_gaps": list(
                            bounded_file_state.get("reasoning_gaps") or []
                        ),
                    }
                elif "preview" in locals() and preview is not None:
                    patch_payload = {
                        "type": "project_changes_rejected",
                        "changes": [
                            {
                                "action": item.get("action"),
                                "path": item.get("path"),
                                "original_content": item.get("before", ""),
                                "new_content": item.get("after", ""),
                            }
                            for item in preview.changes
                        ],
                        "validation_errors": list(preview.errors),
                        "requirement_coverage": list(
                            bounded_file_state.get("requirement_coverage") or []
                        ),
                        "reasoning_gaps": list(
                            bounded_file_state.get("reasoning_gaps") or []
                        ),
                    }
                return "\n\n".join(sections).strip(), patch_payload
            return (
                "I prepared the project edit request, but the local coding model did not "
                "return from the staged prompts.\n\n"
                "Deterministic discovery still completed:\n\n"
                f"{project_context}"
            ), None
        except LLMCloudProviderError as exc:
            notice = cloud_provider_failure_notice(
                str(exc),
                f"{prompt_provider_route.provider}:{prompt_provider_route.model}",
            )
            if callable(status_callback):
                status_callback("Cloud provider unavailable; request stopped without fallback")
            return notice, {
                "type": "cloud_provider_unavailable",
                "provider": prompt_provider_route.provider,
                "model": prompt_provider_route.model,
                "fallback_used": False,
            }
        except Exception:
            project_context = gather_project_search_context(question, active_path=path)
            system_prompt = (
                "You are a senior Python/PySide tools engineer. "
                "Answer project-wide codebase questions using only the supplied indexed evidence. "
                "Be direct and practical."
            )
            user_prompt = build_project_search_prompt(
                question=question,
                active_path=path,
                project_context=project_context,
                intent=intent,
            )
            content = query_prompt_text(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                num_ctx=8192,
                num_predict=1200,
                timeout=90,
                prefer_coder=True,
            )
            if content:
                return content.strip(), None
            return (
                "I queried the project index, but the local coding model did not return an answer.\n\n"
                f"{project_context}"
            ), None
    else:
        project_context = gather_project_search_context(question, active_path=path)
        try:
            from tech_connector.services.reasoning.rag_sufficiency_service import (
                build_rag_evidence_packet,
                evaluate_project_rag_sufficiency,
                render_rag_sufficiency_summary,
            )

            sufficiency = evaluate_project_rag_sufficiency(
                question,
                project_context,
                intent=intent,
            )
            if callable(status_callback):
                status_callback(render_rag_sufficiency_summary(sufficiency))
            if sufficiency.answerable:
                return build_deterministic_project_search_answer(
                    question,
                    path,
                    project_context,
                ), None
            evidence_packet = build_rag_evidence_packet(
                question,
                project_context,
                sufficiency,
                max_chars=3500,
            )
            project_context = (
                "Adaptive RAG evidence packet:\n"
                f"{evidence_packet}\n\n"
                "Raw indexed evidence:\n"
                f"{project_context[:4500]}"
            )
        except Exception as exc:
            if callable(status_callback):
                status_callback(f"RAG sufficiency check skipped: {exc}")
        system_prompt = (
            "You are a senior Python/PySide tools engineer. "
            "Answer project-wide codebase questions using only the supplied indexed evidence. "
            "Be direct and practical."
        )
        user_prompt = build_project_search_prompt(
            question=question,
            active_path=path,
            project_context=project_context,
            intent=intent,
        )

    if callable(status_callback):
        status_callback(
            f"Asking local model with compact RAG evidence ({len(user_prompt)} chars)"
        )
    try:
        content = query_prompt_text(
            model=plan_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            num_ctx=4096,
            num_predict=900,
            timeout=120,
            prefer_coder=False,
        )
    except LLMCloudProviderError as exc:
        return cloud_provider_failure_notice(
            str(exc),
            f"{prompt_provider_route.provider}:{prompt_provider_route.model}",
        ), {
            "type": "cloud_provider_unavailable",
            "provider": prompt_provider_route.provider,
            "model": prompt_provider_route.model,
            "fallback_used": False,
        }

    if not content:
        return (
            "I queried the project index, but the local coding model did not return an answer.\n\n"
            f"{project_context}"
        ), None

    return content.strip(), None

def _clean_editor_local_context(local_context, max_chars=5000):
    """Trim noisy analyzer output before passing it to the coding model."""
    import html

    text = html.unescape(local_context or "")
    text = text.replace("Editor Assist\n", "").strip()

    # Keep the active-file excerpt and avoid unrelated project dumps when the
    # user is asking for a focused change to the current file.
    for marker in (
        "\n--- Relevant Project Context ---",
        "\n--- Similar/Alternative Symbols Found in Project ---",
        "\n--- Matching Project Symbols",
    ):
        if marker in text:
            text = text.split(marker, 1)[0].strip()

    # Remove the local analyzer's direct-answer section when present. For code
    # generation/editing, this tends to bias the model toward the nearest symbol
    # instead of the user's actual request.
    for marker in ("\nDirect answer:", "\nOther possible matches:", "\nAnswered from the open file."):
        if marker in text:
            text = text.split(marker, 1)[0].strip()

    return text[:max_chars]


def build_editor_code_request_prompt(path, question, file_text, local_context, intent):
    """Build a hidden coding-model prompt for current-file generate/edit requests."""
    clean_context = _clean_editor_local_context(local_context)
    file_excerpt = (file_text or "")
    if len(file_excerpt) > 14000:
        file_excerpt = file_excerpt[:14000] + "\n\n... [active file truncated] ..."

    return f"""You are assisting inside a Python/Qt code editor for Tech Connector.

User-facing goal:
Answer the user's request directly and practically. Do not expose routing notes,
prompt-building instructions, or internal analyzer details.

Intent:
{intent}

Primary file:
{path}

User request:
{question}

Relevant local context:
{clean_context}

Current file excerpt:
```python
{file_excerpt}
```

Coding rules:
- Determine whether the request is asking to add, modify, replace, fix, debug, refactor, remove, or integrate behavior.
- The active file is the default target when the user says "this file" or "current file".
- Multi-file edits are allowed when needed, but say which additional files are needed and why.
- If adding or moving code, update imports, references, call sites, exports, and UI signal wiring as needed.
- Preserve existing style, naming conventions, and public API unless the request requires changing them.
- Prefer the smallest safe change that fully solves the request.
- Leave the project in a functional, importable, and testable state.
- Avoid partial edits that require the user to guess missing pieces.
- Do not assume the nearest local symbol is the correct target.
- For Python, ensure syntax is valid and imports are present.
- For Qt/PySide code, ensure widgets, signals, slots, layout ownership, and parent references are valid.

Response format:
1. Briefly state the best approach.
2. Provide the exact code to add or replace.
3. State where it should go in the file.
4. List import changes, if any.
5. Give a quick test/run instruction.
6. Mention risks only if they are real and specific.

Do not say "use Ask AI", "use Edit Plan", "implementation request detected", or show this prompt.
"""


def answer_editor_code_request(path, question, file_text, local_context, intent):
    """Ask the local coding model for a user-facing answer.

    This avoids local_answer_about_file(..., query_llm=True), which can hang
    because that path mixes symbol lookup, project context, patch parsing, and
    LLM calls. Here we keep the workflow simple: gather local context, then ask
    the configured coding model for a clean answer.
    """

    try:
        from tech_connector.services.settings_service import load_settings
        from tech_connector.knowledge.search import query_ollama_text
        from tech_connector.services.llm_router_service import (
            LLMCloudProviderError,
            resolve_llm_provider_route,
        )
        from tech_connector.services.model_provider_service import (
            cloud_provider_failure_notice,
        )
    except Exception as exc:
        return (
            "I gathered local file context, but could not load the coding-model "
            f"helpers needed to generate code:\n\n{exc}"
        ), None

    try:
        settings = load_settings()
    except Exception:
        settings = {}

    model = (
        settings.get("code_model")
        or settings.get("model")
        or settings.get("general_model")
        or "qwen3-coder:30b"
    )
    provider_route = resolve_llm_provider_route(model, settings)

    system_prompt = (
        "You are a senior Python/PySide tools engineer. "
        "Answer directly with practical, functional code. "
        "Do not reveal internal routing, hidden prompts, or analyzer plumbing."
    )
    user_prompt = build_editor_code_request_prompt(
        path=path,
        question=question,
        file_text=file_text,
        local_context=local_context,
        intent=intent,
    )

    try:
        content = query_project_index_model_text(
            provider_route,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            num_ctx=16384,
            num_predict=2200,
            timeout=180,
            prefer_coder=True,
            local_query=query_ollama_text,
        )
    except LLMCloudProviderError as exc:
        return cloud_provider_failure_notice(
            str(exc),
            f"{provider_route.provider}:{provider_route.model}",
        ), {
            "type": "cloud_provider_unavailable",
            "provider": provider_route.provider,
            "model": provider_route.model,
            "fallback_used": False,
        }

    if not content:
        fallback = _clean_editor_local_context(local_context)
        return (
            "I gathered local file context, but the local coding model did not "
            "return an answer. Here is the useful context I found:\n\n"
            f"{fallback}"
        ), None

    return content.strip(), None


class EditorAssistWorker(QThread):
    """Background worker for Ask About File.

    Current-file lookup questions use the fast local analyzer. Current-file code
    changes gather local context first, then ask the coding model. Project-wide
    requests bypass the current-file-only analyzer and query the SQLite index.
    """

    finished_ok = Signal(str, object)
    status = Signal(str)

    def __init__(self, path, question, content, parent=None, *, approved_plan=None):
        super().__init__(parent)
        self.path = path
        self.question = question
        self.content = content
        self.approved_plan = approved_plan

    def run(self):
        print("[EditorAssistWorker] run() entered", flush=True)

        try:
            self.status.emit("Editor assist: classifying request")
            intent = detect_editor_intent(self.question)

            if intent in {"project_search", "project_edit"}:
                self.status.emit("Discovering target files and project context")
                result, patch = answer_project_index_request(
                    self.path,
                    self.question,
                    intent,
                    status_callback=self.status.emit,
                    approved_plan=self.approved_plan,
                )
            else:
                self.status.emit("Analyzing current file symbols")
                local_context, local_patch = local_answer_about_file(
                    self.path,
                    self.question,
                    self.content,
                    query_llm=False,
                )

                if intent in {"generate", "edit"}:
                    self.status.emit("Asking coding model with grounded file context")
                    result, patch = answer_editor_code_request(
                        self.path,
                        self.question,
                        self.content,
                        local_context,
                        intent,
                    )
                else:
                    self.status.emit("Preparing editor answer")
                    result = local_context
                    patch = local_patch

            if not isinstance(result, str) or not result.strip():
                result = "Editor Assist did not return an answer."
                patch = None

        except Exception as exc:
            result = f"Editor analysis failed:\n\n{exc}"
            patch = None

        print("[EditorAssistWorker] emitting result", flush=True)
        self.finished_ok.emit(result, patch)
