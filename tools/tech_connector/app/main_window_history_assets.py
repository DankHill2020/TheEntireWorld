"""Main application window — thin orchestration layer."""

import os
import sys
from pathlib import Path

_ROOT = next(candidate for candidate in Path(__file__).resolve().parents if candidate.name.lower() == "tools")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import re
import time

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
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
    QVBoxLayout,
    QWidget,
)


from tech_connector.models.constants import (

    DCC_TOOL_PACKAGE_DIRS,
    DEFAULT_CONFIGS,
    EXTERNAL_TOOLS_DIR,

    HISTORY_DIR,
    IMAGE_DIR,

    TOOLS_ROOT,
    project_index_db_path,
)

from tech_connector.services.model_provider_service import (
    PROVIDERS,
    credential_requirement_for_model,

    provider_setup_notes,
    provider_setup_url,
)
from tech_connector.services.ollama_service import (

    as_mcphost_model,

)

from tech_connector.services.settings_service import best_config
from tech_connector.ui.first_run_dialog import FirstRunDialog
from tech_connector.ui.chat_worker_dialogs import CredentialsPromptDialog
from tech_connector.ui.unreal_editor_dialogs import WebImportDialog

from tech_connector.services.knowledge_background_service import KnowledgeBuildWorker, KnowledgeBuildPhase



# Compatibility imports that the original monolithic file referenced indirectly.
try:
    from tech_connector.services.model_provider_service import should_use_local_runtime
except Exception:
    def should_use_local_runtime(model, settings):
        return True



class MainWindowHistoryAssetsMixin:
    def show_first_run(self):
        dlg = FirstRunDialog(self.settings, self)
        if dlg.exec():
            self.service.reload_settings()
            self.settings = self.service.settings
            self.append("\n[Project directories updated.]\n")
            try:
                if hasattr(self, "confirm_and_run_first_time_dcc_installers"):
                    self.confirm_and_run_first_time_dcc_installers()
            except Exception as exc:
                self.append(f"\n[DCC Setup] First-time installer launch failed: {exc}\n")
            self.refresh_project_tree_fast()
            if self.settings.get("auto_index_on_first_run") and not project_index_db_path().exists():
                self.build_index()

    def install_components(self):
        try:
            cfg = self.service.install_components()
            self.append(
                f"\n[Installed Knowledge v2 and quiet Maya MCP. Updated config: {cfg}]\n"
            )
            self.config_box.setEditText(cfg)
        except Exception as e:
            QMessageBox.critical(self, "Install failed", str(e))

    def trigger_web_import(
        self,
        initial_query="",
        workflow_goal="",
        auto_search=False,
        auto_select_after_search=False,
    ):
        dialog = WebImportDialog(
            self,
            initial_query=initial_query,
            workflow_goal=workflow_goal,
            auto_search=auto_search,
            auto_select_after_search=auto_select_after_search,
        )
        if dialog.exec_() == QDialog.Accepted:
            if dialog.ingested_path:
                self.append(
                    f"\n[Import] Repository successfully ingested into: {dialog.ingested_path}\n"
                )
                self.refresh_project_tree_fast()
                self.append(
                    "[Import] Re-indexing workspace database to include imported files...\n"
                )
                self.build_index()
            if dialog.composed_code.strip():
                composed_prompt = (
                    "Review and apply this composed workflow function to the appropriate project file(s). "
                    "Preserve the selected workflow intent and use normal project-change review before writing files.\n\n"
                    f"{dialog.composed_code.strip()}"
                )
                self.input.setText(composed_prompt)
                self.append(
                    "[Composer] Inserted composed workflow into the chat input for review/application.\n"
                )
        else:
            self.append(
                "\n[Source Mode] Web import canceled. Performing deeper local analysis...\n"
            )
            self.settings["last_search_cancelled"] = True
            self.service.save_settings()

    def populate_add_to_workflow_menu(self, menu, payload):
        menu.clear()
        new_action = menu.addAction("New Workflow")
        new_action.triggered.connect(
            lambda _checked=False, p=dict(payload): self.add_artifact_to_workflow(p)
        )
        menu.addSeparator()

        if not hasattr(self, "loaded_workflows"):
            loading = menu.addAction("Loading saved pipelines...")
            loading.setEnabled(False)

            def hydrate():
                started = time.perf_counter()
                self.refresh_workflows_list()
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                if elapsed_ms > 80 and hasattr(self, "record_ui_diagnostic_event"):
                    self.record_ui_diagnostic_event(
                        "menu_hydrate",
                        {"menu": "add_to_workflow", "section": "refresh_workflows", "duration_ms": elapsed_ms},
                    )
                self.populate_add_to_workflow_menu(menu, payload)

            QTimer.singleShot(0, hydrate)
            return
        if not getattr(self, "loaded_workflows", {}):
            menu.addAction("No saved workflows found").setEnabled(False)
            return

        for manifest_path, data in sorted(
                self.loaded_workflows.items(), key=lambda item: item[1].get("function", "")
        ):
            label = (
                    data.get("naming", {}).get("original_function")
                    or data.get("function")
                    or Path(manifest_path).stem
            )
            host = data.get("host", "")
            action = menu.addAction(f"{label} [{host}]")
            action.triggered.connect(
                lambda _checked=False, p=dict(payload), manifest=manifest_path: (
                    self.add_artifact_to_workflow(p, manifest)
                )
            )

    def add_artifact_to_workflow(self, payload, manifest_path=None):
        title = (payload or {}).get("title", "Workflow Reference")
        source = (payload or {}).get("source", "Tech Connector")
        content = (payload or {}).get("content", "").strip()
        if not content:
            QMessageBox.information(
                self, "No Content", "There is no content to add to a workflow."
            )
            return

        self.workspace_tabs.setCurrentIndex(3)
        if manifest_path:
            self.refresh_workflows_list()
            for idx in range(self.workflows_list.count()):
                item = self.workflows_list.item(idx)
                if item.data(Qt.UserRole) == manifest_path:
                    self.workflows_list.setCurrentItem(item)
                    self.load_selected_workflow_to_builder()
                    break
            else:
                QMessageBox.warning(
                    self,
                    "Workflow Not Found",
                    "The selected workflow could not be loaded.",
                )
                return
        else:
            self.start_new_workflow_builder()
            safe_name = (
                    re.sub(r"[^A-Za-z0-9_]+", "_", title).strip("_").lower()
                    or "workflow_reference"
            )
            self.wf_build_name.setText(safe_name[:64])

        existing_goal = self.wf_build_goal.toPlainText().strip()
        note = f"[{source}] {title}"
        if note not in existing_goal:
            self.wf_build_goal.setPlainText(
                (existing_goal + "\n\n" if existing_goal else "") + note
            )

        comment_lines = [f"1 Workflow reference from {source}: {title}"]
        comment_lines.extend(
            f"1 {line}" if line.strip() else "1" for line in content.splitlines()
        )
        current_code = self.wf_builder_code_edit.toPlainText().rstrip()
        self.wf_builder_code_edit.setPlainText(
            (current_code + "\n\n" if current_code else "") + "\n".join(comment_lines)
        )
        self.wf_builder_tabs.setCurrentIndex(1)
        self.append(f"\n[Workflow] Added '{title}' as workflow reference context.\n")

    def refresh_editor_answer_workflow_menu(self):
        if not hasattr(self, "add_editor_answer_workflow_menu"):
            return
        payload = getattr(self, "last_editor_assist_payload", None)
        self.populate_add_to_workflow_menu(
            self.add_editor_answer_workflow_menu, payload or {}
        )

    def should_open_github_import_for_prompt(self, text):
        if not bool(self.settings.get("search_github_tools_when_composing", False)):
            return False
        lower = (text or "").lower()
        import re

        if "github.com/" in lower or (
                re.search(r"\b[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+\b", lower) and "github" in lower
        ):
            return True
        wants_tool_source = any(
            phrase in lower
            for phrase in [
                "ingest a tool",
                "ingest tool",
                "import a tool",
                "find a tool",
                "github tool",
                "third party tool",
                "third-party tool",
                "external tool",
            ]
        )
        wants_composition = any(
            word in lower
            for word in [
                "compose",
                "combine",
                "chain",
                "workflow",
                "hook it",
                "connect",
                "orchestrate",
            ]
        )
        return wants_tool_source or ("github" in lower and wants_composition)

    def has_internal_workflow_matches_for_prompt(self, text):
        try:
            from tech_connector.services.external_tool_service import rank_symbols
            from tech_connector.services.tool_discovery_service import list_internal_functions

            roots = self.project_roots() if hasattr(self, "project_roots") else []
            ranked = rank_symbols(list_internal_functions(roots), text or "", limit=5)
            return any(int(item.get("score") or 0) > 0 for item in ranked)
        except Exception:
            return False

    def should_offer_research_for_unknown_dcc_request(self, text, prompt_route_decision=None):
        lower = (text or "").lower()
        host_terms = (
            "unreal", "ue5", "ue4", "maya", "blender", "houdini",
            "motionbuilder", "motion builder", "substance painter", "unity",
        )
        if not any(term in lower for term in host_terms):
            return False
        if not any(
            term in lower
            for term in (
                "create", "make", "build", "implement", "add", "setup", "set up",
                "develop", "script", "tool", "plugin", "api", "node", "blueprint",
                "material", "shader", "rig", "animation", "workflow", "pipeline",
            )
        ):
            return False

        decision = (
            prompt_route_decision.to_dict()
            if hasattr(prompt_route_decision, "to_dict")
            else (prompt_route_decision or {})
        )
        route = str(decision.get("route") or "")
        execution_route = str(decision.get("execution_route") or "")
        target = str(decision.get("target_identifier") or decision.get("callable_name") or "")
        unknown_target = not target or target in {"llm_fallback", "unknown"}
        routed_to_dcc = (
            route in {"dcc_execute", "dcc_prototype", "unreal_operation", "action_graph"}
            or execution_route in {"dcc.execution_pipeline", "dcc.prototype_pipeline", "unreal.capability_pipeline"}
        )
        return bool(routed_to_dcc and unknown_target and not self.has_internal_workflow_matches_for_prompt(text))

    def build_index(self, full: bool = False):
        """Refresh stale searchable index files first, then rebuild graph only if needed."""
        worker = getattr(self, "index_worker", None)
        if worker and worker.isRunning():
            QMessageBox.information(
                self, "Index running", "Knowledge indexing is already running in the background."
            )
            return

        try:
            self.service.install_components()
        except Exception as exc:
            self.append(f"\n[Knowledge] Component install/update warning: {exc}\n")

        root = ""
        try:
            roots = self.project_roots()
            root = roots[0] if roots else ""
        except Exception:
            root = ""

        if hasattr(self, "index_progress"):
            self.index_progress.setRange(0, 0)
        if hasattr(self, "index_status"):
            self.index_status.setText("Knowledge: full index rebuild..." if full else "Knowledge: bootstrapping files/symbols...")
        self.set_card("knowledge", "busy", "Full index rebuild" if full else "Bootstrapping symbols")

        self._knowledge_worker_phase = KnowledgeBuildPhase.FULL_REBUILD if full else KnowledgeBuildPhase.BOOTSTRAP_SYMBOLS
        self.index_worker = KnowledgeBuildWorker(
            project_root=root,
            phase=self._knowledge_worker_phase,
            parent=self,
        )
        self.index_worker.status.connect(self.on_knowledge_build_status)
        self.index_worker.progress.connect(self.on_index_progress)
        self.index_worker.finished_ok.connect(self.on_index_finished)
        self.index_worker.start()

    def build_full_index(self):
        """Explicit nuclear option for repairing a badly stale or corrupted index."""
        return self.build_index(full=True)

    def on_knowledge_build_status(self, status):
        label = f"Knowledge: {status}"
        if hasattr(self, "index_status"):
            self.index_status.setText(label)
        if status.lower() == "dependency graph":
            self.set_card("knowledge", "busy", "Graph building")
        elif status.lower() == "ready":
            self.set_card("knowledge", "ok", "Index + graph ready")
        else:
            self.set_card("knowledge", "busy", status)

    def on_index_progress(self, current=0, total=0, label="Indexing"):
        if not hasattr(self, "index_status"):
            return
        if total:
            self.index_status.setText(f"Knowledge: {label} {current}/{total}")
        elif current:
            self.index_status.setText(f"Knowledge: {label} updated {current}")
        else:
            self.index_status.setText(f"Knowledge: {label}...")

    def on_index_finished(self, ok, msg):
        phase = getattr(self, "_knowledge_worker_phase", "")

        if hasattr(self, "index_progress"):
            self.index_progress.setRange(0, 1)
            self.index_progress.setValue(1 if ok else 0)

        self.append(f"\n[Knowledge] {msg}\n")

        if phase == KnowledgeBuildPhase.BOOTSTRAP_SYMBOLS:
            if ok:
                if hasattr(self, "index_status"):
                    self.index_status.setText("Knowledge: symbols ready; rich search queued")
                self.set_card("knowledge", "busy", "Symbols ready / search queued")
                QTimer.singleShot(250, self.build_rich_index_only)
            else:
                if hasattr(self, "index_status"):
                    self.index_status.setText("Knowledge: bootstrap failed")
                self.set_card("knowledge", "bad", "Bootstrap failed")
            return

        if phase == KnowledgeBuildPhase.QUICK_INDEX:
            if ok:
                updated = 0
                try:
                    updated = int(getattr(self.index_worker, "summary_metrics", {}).get("Updated files", 0))
                except Exception:
                    updated = 0
                if updated <= 0:
                    if hasattr(self, "index_status"):
                        self.index_status.setText("Knowledge: index already current")
                    self.set_card("knowledge", "ok", "Index current")
                    return
                if hasattr(self, "index_status"):
                    self.index_status.setText("Knowledge: index ready; graph queued")
                self.set_card("knowledge", "busy", "Index ready / graph queued")
                # Start the heavier graph after the UI has a moment to repaint.
                QTimer.singleShot(700, self.build_dependency_graph_only)
            else:
                if hasattr(self, "index_status"):
                    self.index_status.setText("Knowledge: quick index failed")
                self.set_card("knowledge", "bad", "Index failed")
            return

        if phase == KnowledgeBuildPhase.DEPENDENCY_GRAPH:
            if ok:
                if hasattr(self, "index_status"):
                    self.index_status.setText("Knowledge: index + graph ready")
                self.set_card("knowledge", "ok", "Index + graph ready")
            else:
                # The search index is still usable even if graph analysis failed.
                if hasattr(self, "index_status"):
                    self.index_status.setText("Knowledge: index ready; graph failed")
                self.set_card("knowledge", "warn", "Index ready / graph failed")
            return

        if hasattr(self, "index_status"):
            self.index_status.setText("Knowledge: ready" if ok else "Knowledge: failed")
        self.set_card(
            "knowledge", "ok" if ok else "bad", "Index + graph ready" if ok else "Index failed"
        )

    def build_rich_index_only(self):
        """Complete chunks/search tables after the first-pass symbol bootstrap."""
        worker = getattr(self, "index_worker", None)
        if worker and worker.isRunning():
            QMessageBox.information(self, "Index running", "Knowledge work is already running.")
            return
        root = ""
        try:
            roots = self.project_roots()
            root = roots[0] if roots else ""
        except Exception:
            root = ""
        self.set_card("knowledge", "busy", "Rich search building")
        if hasattr(self, "index_progress"):
            self.index_progress.setRange(0, 0)
        if hasattr(self, "index_status"):
            self.index_status.setText("Knowledge: building rich search tables...")
        self._knowledge_worker_phase = KnowledgeBuildPhase.QUICK_INDEX
        self.index_worker = KnowledgeBuildWorker(
            project_root=root,
            phase=KnowledgeBuildPhase.QUICK_INDEX,
            parent=self,
        )
        self.index_worker.status.connect(self.on_knowledge_build_status)
        self.index_worker.progress.connect(self.on_index_progress)
        self.index_worker.finished_ok.connect(self.on_index_finished)
        self.index_worker.start()

    def build_dependency_graph_only(self):
        """Rebuild only the graph from the existing index. Useful after a quick index."""
        worker = getattr(self, "index_worker", None)
        if worker and worker.isRunning():
            QMessageBox.information(self, "Index running", "Knowledge work is already running.")
            return
        root = ""
        try:
            roots = self.project_roots()
            root = roots[0] if roots else ""
        except Exception:
            root = ""
        self.set_card("knowledge", "busy", "Graph building")
        if hasattr(self, "index_progress"):
            self.index_progress.setRange(0, 0)
        if hasattr(self, "index_status"):
            self.index_status.setText("Knowledge: rebuilding dependency graph...")
        self._knowledge_worker_phase = KnowledgeBuildPhase.DEPENDENCY_GRAPH
        self.index_worker = KnowledgeBuildWorker(
            project_root=root,
            phase=KnowledgeBuildPhase.DEPENDENCY_GRAPH,
            parent=self,
        )
        self.index_worker.status.connect(self.on_knowledge_build_status)
        self.index_worker.progress.connect(self.on_index_progress)
        self.index_worker.finished_ok.connect(self.on_index_finished)
        self.index_worker.start()

    def attach_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Attach images", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        self.attached_images.extend(files)
        self.update_image_label()

    def paste_image_from_clipboard(self):
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()
        saved = []
        if mime.hasImage():
            image = cb.image()
            if not image.isNull():
                path = IMAGE_DIR / f"clipboard_{time.strftime('%Y%m%d_%H%M%S')}.png"
                image.save(str(path), "PNG")
                saved.append(str(path))
        if saved:
            self.attached_images.extend(saved)
            self.update_image_label()
            self.append(f"\n[Attached pasted image: {Path(saved[0]).name}]\n")

    def update_image_label(self):
        self.image_label.setText(
            "Attached images: "
            + (
                "; ".join(Path(p).name for p in self.attached_images)
                if self.attached_images
                else "none"
            )
        )

    def refresh_history(self):
        self.history.clear()
        for idx, p in enumerate(sorted(HISTORY_DIR.glob("*.json"), reverse=True)):
            if idx >= 200:
                self.history.addItem("... older history omitted at startup ...")
                break
            self.history.addItem(p.name)

    def save_history(self):
        p = HISTORY_DIR / f"chat_{time.strftime('%Y%m%d_%H%M%S')}.json"
        p.write_text(json.dumps(self.current_session, indent=2), encoding="utf-8")
        self.refresh_history()
        self.append(f"\n[Saved chat: {p}]\n")

    def _history_content_to_text(self, content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or item))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part)
        if content is None:
            return ""
        return str(content)

    def _history_role_label(self, role):
        role_text = str(role or "").strip().lower()
        labels = {
            "assistant": "ASSISTANT",
            "assistant_or_tool_output": "ASSISTANT",
            "tool": "TOOL",
            "system": "SYSTEM",
            "user": "YOU",
        }
        return labels.get(role_text, role_text.upper() or "MESSAGE")

    def _history_session_to_transcript(self, session):
        full_text = []
        for message in session or []:
            if not isinstance(message, dict):
                continue
            role = self._history_role_label(message.get("role", ""))
            content = self._history_content_to_text(message.get("content", ""))
            if not content.strip():
                continue
            full_text.append(f"\n{role}:\n{content}\n")
        return "".join(full_text)

    def new_chat(self):
        if self.current_session:
            self.save_history()
        self.current_session = []
        self.service.current_session = self.current_session
        self.code_snippets = []
        self.service.code_snippets = self.code_snippets
        self.code_list.clear()
        self.output_cleaner.reset()
        if hasattr(self, "clear_visible_chat_state"):
            self.clear_visible_chat_state()
        else:
            self.chat_history_raw = ""
            self.log.clear()
        self.last_user_prompt = ""
        self.last_assistant_output = ""
        self.last_tool_output = ""
        self.service.last_user_prompt = ""
        self.service.last_assistant_output = ""
        self.service.last_tool_output = ""
        self.attached_images = []
        self.service.attached_images = self.attached_images
        if hasattr(self, "attached_files"):
            self.attached_files = []
        if hasattr(self, "update_attachment_strip"):
            self.update_attachment_strip()
        elif hasattr(self, "update_image_label"):
            self.update_image_label()
        if hasattr(self, "input"):
            self.input.clear()
            self.input.setFocus()
        if hasattr(self, "set_live_process"):
            self.set_live_process("New chat ready")

    def load_history_item(self, item):
        p = HISTORY_DIR / item.text()
        try:
            self.current_session = json.loads(p.read_text(encoding="utf-8"))
            self.service.current_session = self.current_session
        except Exception as e:
            self.append(f"\n[History] Error reading history file: {e}\n")
            return

        if hasattr(self, "clear_visible_chat_state"):
            self.clear_visible_chat_state()
        else:
            self.log.clear()
            self.chat_history_raw = ""
        self.code_snippets = []
        self.service.code_snippets = self.code_snippets
        self.code_list.clear()

        self.chat_history_raw = self._history_session_to_transcript(self.current_session)
        if hasattr(self, "extract_code_blocks"):
            self.extract_code_blocks(self.chat_history_raw)
        if hasattr(self, "render_chat_history"):
            self._chat_render_pending_bottom = True
            self.render_chat_history()
        elif hasattr(self, "log"):
            self.log.setPlainText(self.chat_history_raw)
        self.refresh_snippets_list()

    def show_history_context_menu(self, pos):
        item = self.history.itemAt(pos)
        menu = QMenu(self)
        load_act = menu.addAction("Load Chat")
        delete_act = menu.addAction("Delete Chat")
        clear_all_act = menu.addAction("Clear All History")

        if not item:
            load_act.setEnabled(False)
            delete_act.setEnabled(False)

        action = menu.exec(self.history.mapToGlobal(pos))
        if action == load_act and item:
            self.load_history_item(item)
        elif action == delete_act and item:
            filename = item.text()
            p = HISTORY_DIR / filename
            try:
                if p.exists():
                    p.unlink()
                self.history.takeItem(self.history.row(item))
                self.append(f"\n[History] Deleted chat log: {filename}\n")
            except Exception as e:
                QMessageBox.critical(
                    self, "Delete Failed", f"Could not delete history file:\n{e}"
                )
        elif action == clear_all_act:
            if (
                    QMessageBox.question(
                        self,
                        "Clear All History",
                        "Are you sure you want to delete all chat history files?",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    == QMessageBox.Yes
            ):
                for p in HISTORY_DIR.glob("*.json"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                self.refresh_history()
                if hasattr(self, "clear_visible_chat_state"):
                    self.clear_visible_chat_state()
                else:
                    self.log.clear()
                    self.chat_history_raw = ""
                self.append("[History] All chat history cleared.\n")

    def refresh_snippets_list(self):
        self.code_snippets = []
        self.code_list.clear()
        from tech_connector.models.constants import CODE_SNIPPETS_DIR

        for idx, p in enumerate(sorted(CODE_SNIPPETS_DIR.glob("*.*"))):
            if idx >= 200:
                self.code_list.addItem("... more snippets omitted at startup ...")
                break
            if p.is_file():
                self.code_snippets.append(str(p.resolve()))
                self.code_list.addItem(p.name)

    def open_selected_snippet_in_editor(self):
        item = self.code_list.currentItem()
        if not item:
            return
        idx = self.code_list.row(item)
        if 0 <= idx < len(self.code_snippets):
            filepath = self.code_snippets[idx]
            self.open_code_file(filepath)

    def show_snippets_context_menu(self, pos):
        item = self.code_list.itemAt(pos)
        menu = QMenu(self)
        open_act = menu.addAction("Open in Editor")
        copy_act = menu.addAction("Copy to Clipboard")
        delete_act = menu.addAction("Delete Snippet")
        clear_all_act = menu.addAction("Clear All Snippets")

        if not item:
            open_act.setEnabled(False)
            copy_act.setEnabled(False)
            delete_act.setEnabled(False)

        action = menu.exec(self.code_list.mapToGlobal(pos))
        if action == open_act and item:
            self.open_selected_snippet_in_editor()
        elif action == copy_act and item:
            idx = self.code_list.row(item)
            if 0 <= idx < len(self.code_snippets):
                try:
                    code = Path(self.code_snippets[idx]).read_text(encoding="utf-8")
                    QGuiApplication.clipboard().setText(code)
                    self.append(f"\n[Snippets] Copied code snippet to clipboard.\n")
                except Exception:
                    pass
        elif action == delete_act and item:
            idx = self.code_list.row(item)
            if 0 <= idx < len(self.code_snippets):
                p = Path(self.code_snippets[idx])
                try:
                    if p.exists():
                        p.unlink()
                    self.refresh_snippets_list()
                    self.append(f"\n[Snippets] Deleted snippet: {p.name}\n")
                except Exception as e:
                    QMessageBox.critical(
                        self, "Delete Failed", f"Could not delete snippet:\n{e}"
                    )
        elif action == clear_all_act:
            if (
                    QMessageBox.question(
                        self,
                        "Clear All Snippets",
                        "Are you sure you want to delete all code snippets?",
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    == QMessageBox.Yes
            ):
                from tech_connector.models.constants import CODE_SNIPPETS_DIR

                for p in CODE_SNIPPETS_DIR.glob("*.*"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                self.refresh_snippets_list()
                self.append("[Snippets] All code snippets cleared.\n")

    def load_project_tree(self):
        """Refresh the visible project tree without recursively walking roots."""
        if not hasattr(self, "project_tree"):
            return
        self.load_project_tree_lazy()
        if hasattr(self, "refresh_workflows_list"):
            self.refresh_workflows_list()

    def add_model_option(self, label, model, seen_models):
        model = (model or "").strip()
        if not model or model in seen_models:
            return
        seen_models.add(model)
        self.model_box.addItem(f"{label} - {model}", model)

    def selected_mcphost_model(self):
        model = self.model_box.currentData()
        if isinstance(model, str) and model.strip():
            return model.strip()

        text = self.model_box.currentText().strip()
        if " - ollama:" in text:
            return text.rsplit(" - ", 1)[-1].strip()
        if " - " in text:
            return text.rsplit(" - ", 1)[-1].strip()
        return text

    def on_model_changed(self):
        model = self.selected_mcphost_model()
        if not model:
            return

        from tech_connector.services.model_provider_service import (
            credential_requirement_for_model,
            provider_for_model,
            should_use_local_runtime,
        )

        info = credential_requirement_for_model(model, self.settings)
        if info["required"]:
            provider_id = provider_for_model(model)
            dialog = CredentialsPromptDialog(self, model, provider_id)
            if dialog.exec():
                key = dialog.api_key
                self.settings[f"{provider_id}_api_key"] = key
                if provider_id in {"google", "gemini"}:
                    self.settings["gemini_api_key"] = key
                    self.settings["google_api_key"] = key
                    os.environ["GOOGLE_API_KEY"] = key
                    os.environ["GEMINI_API_KEY"] = key
                elif provider_id == "openai":
                    os.environ["OPENAI_API_KEY"] = key
                elif provider_id == "anthropic":
                    os.environ["ANTHROPIC_API_KEY"] = key

                self.service.save_settings(self.settings)
                self.append(
                    f"\n[Settings] Saved API Key for {provider_id.upper()} and activated model {model}.\n"
                )
            else:
                self.model_box.blockSignals(True)
                idx = self.model_box.findData(self.last_selected_model)
                if idx >= 0:
                    self.model_box.setCurrentIndex(idx)
                else:
                    self.model_box.setEditText(self.last_selected_model)
                self.model_box.blockSignals(False)
                return

        # Save to settings
        self.settings["model"] = model
        if provider_for_model(model) != "ollama":
            self.settings["cloud_provider_model"] = model
            self.settings["cloud_model_unavailable"] = False
        self.last_selected_model = model
        self.service.save_settings(self.settings)

        # Warm the newly selected model in the background immediately
        import threading

        from tech_connector.services.ollama_service import warm_ollama_model

        if provider_for_model(model) == "ollama" and should_use_local_runtime(
                model, self.settings
        ):
            t = threading.Thread(
                target=warm_ollama_model, args=(model, "24h"), daemon=True
            )
            t.start()
        self.update_model_requirement_label()
        self.update_active_response_model_label(model)

    def on_fallback_models_changed(self, state):
        enabled = bool(state)
        self.settings["use_fallback_models"] = enabled
        self.service.save_settings()
        self.mcphost_manager.set_use_fallback_models(enabled)
        self.mcphost_manager.stop_all()
        mode = "fallback" if enabled else "primary"
        self.append(
            f"\n[Router] Using {mode} routed models. Routed MCPHost sessions will restart on next prompt.\n"
        )

    def on_live_sources_changed(self, state):
        enabled = bool(state)
        self.service.set_live_sources_enabled(enabled)
        self.settings = self.service.settings
        self.append(
            "\n[Source Mode] "
            + (
                "Live web/GitHub sourcing enabled for normal chat prompts. Review sources before ingesting code.\n"
                if enabled
                else "Local-only mode enabled. Normal chat prompts will avoid live web/GitHub sourcing.\n"
            )
        )

    def lock_ai_knowledge_snapshot(self):
        from tech_connector.services.ai_work_memory_service import lock_current_knowledge

        name, ok = QInputDialog.getText(self, "Lock Knowledge", "Snapshot name:")
        if not ok:
            return
        note, note_ok = QInputDialog.getMultiLineText(
            self,
            "Lock Knowledge",
            "Optional note about why this state is good:",
            "",
        )
        if not note_ok:
            note = ""
        try:
            path = lock_current_knowledge(
                self.settings, name.strip() or "Knowledge Lock", note
            )
            self.append(f"\n[AI Knowledge] Locked current work knowledge:\n{path}\n")
        except Exception as e:
            QMessageBox.critical(self, "Lock Knowledge Failed", str(e))

    def show_ai_knowledge_summary(self):
        from tech_connector.services.ai_work_memory_service import knowledge_status_summary

        QMessageBox.information(
            self, "AI Knowledge", knowledge_status_summary(self.settings)
        )

    def on_model_source_mode_changed(self, index):
        mode = self.model_source_mode_box.currentData() or "auto_with_local_fallback"
        self.service.set_model_source_mode(mode)
        self.settings = self.service.settings
        self.mcphost_manager.settings = self.settings
        label = self.model_source_mode_box.currentText()
        self.update_model_requirement_label()
        self.update_active_response_model_label()
        self.append(
            f"\n[Model Provider] Source mode set to {label}. Routed sessions will restart on next prompt.\n"
        )

    def on_show_reasoning_summary_changed(self, state):
        enabled = bool(state)
        self.settings["show_reasoning_summary"] = enabled
        self.service.save_settings(self.settings)
        self.append(
            f"\n[Settings] Reasoning summary display {'enabled' if enabled else 'disabled'}.\n"
        )

    def on_simple_chat_responses_changed(self, state):
        enabled = bool(state)
        self.settings["simple_chat_responses"] = enabled
        self.service.save_settings(self.settings)
        self.append(
            "\n[Settings] "
            + (
                "Simple chat responses enabled. Tech Connector will keep deterministic reports short.\n"
                if enabled
                else "Rich chat responses enabled. Tech Connector will include clearer plans, status, and next steps.\n"
            )
        )

    def on_unreal_cpp_bridge_changed(self, state):
        enabled = bool(state)
        self.settings["allow_unreal_cpp_bridge"] = enabled
        self.service.save_settings(self.settings)
        if hasattr(self, "unreal_cpp_bridge_checkbox"):
            self.unreal_cpp_bridge_checkbox.blockSignals(True)
            self.unreal_cpp_bridge_checkbox.setChecked(enabled)
            self.unreal_cpp_bridge_checkbox.blockSignals(False)
        self.append(
            "\n[Unreal Capability] "
            + (
                "C++ bridge planning enabled. Tech Connector may recommend reflected C++ plugin functions when Python is incomplete.\n"
                if enabled
                else "C++ bridge planning disabled. Unreal operations will stay Python/editor-API first and report C++ needs as unavailable.\n"
            )
        )

    def unreal_cpp_bridge_enabled(self):
        return bool(self.settings.get("allow_unreal_cpp_bridge", False))

    def update_model_requirement_label(self):
        if not hasattr(self, "model_requirement_label") or not hasattr(
                self, "model_box"
        ):
            return
        info = credential_requirement_for_model(
            self.selected_mcphost_model(), self.settings
        )
        if info["required"]:
            text = f"Action required: {info['status']} {info['action']}"
            style = "color: #ffe0a3; background-color: #33280d; border: 1px solid #80621d; padding: 5px;"
        else:
            text = info["status"]
            style = "color: #b9dcff; background-color: #000711; border: 1px solid #1e9bff; padding: 5px;"
        self.model_requirement_label.setText(text)
        self.model_requirement_label.setStyleSheet(style)

    def show_model_provider_setup(self, provider_id="openai"):
        provider = PROVIDERS.get(provider_id)
        if not provider:
            QMessageBox.warning(
                self, "Model Provider", f"Unknown provider: {provider_id}"
            )
            return

        QMessageBox.information(
            self,
            f"{provider.display_name} Setup",
            provider_setup_notes(provider_id),
        )

    def open_model_provider_setup(self, provider_id):
        url = provider_setup_url(provider_id)
        if not url:
            self.show_model_provider_setup(provider_id)
            return
        QDesktopServices.openUrl(QUrl(url))
        self.append(
            f"\n[Model Provider] Opened official setup page for {PROVIDERS[provider_id].display_name}: {url}\n"
        )

    def show_customization_panel_dialog(self, active_tab: int = 0):
        from tech_connector.ui.customization_panel import CustomizationPanel
        dialog = CustomizationPanel(self, active_tab=active_tab)
        dialog.exec()

    def show_customization_panel_models(self):
        self.show_customization_panel_dialog(active_tab=0)

    def show_customization_panel_cloud(self):
        self.show_customization_panel_dialog(active_tab=1)

    def show_customization_panel_services(self):
        self.show_customization_panel_dialog(active_tab=2)

    def show_customization_panel_ext(self):
        self.show_customization_panel_dialog(active_tab=3)

    def show_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Settings")
        dialog.resize(860, 760)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Model Providers")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        help_text = QLabel(
            "Choose local Ollama or a cloud provider. A cloud provider/model is locked "
            "for the complete prompt run and failures are reported without silently "
            "switching models."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #cfcfcf;")
        layout.addWidget(help_text)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Model source:"))
        source_box = QComboBox()
        source_box.addItem(
            "Cloud locked / local if unset", "auto_with_local_fallback"
        )
        source_box.addItem("Always local", "local_only")
        idx = source_box.findData(
            self.settings.get("model_source_mode", "auto_with_local_fallback")
        )
        if idx >= 0:
            source_box.setCurrentIndex(idx)
        source_row.addWidget(source_box, 1)
        layout.addLayout(source_row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        model_box = QComboBox()
        model_box.setEditable(True)
        for i in range(self.model_box.count()):
            model_box.addItem(self.model_box.itemText(i), self.model_box.itemData(i))
        selected = self.selected_mcphost_model()
        idx = model_box.findData(selected)
        if idx >= 0:
            model_box.setCurrentIndex(idx)
        else:
            model_box.setEditText(selected)
        model_row.addWidget(model_box, 1)
        layout.addLayout(model_row)

        selected_requirement = QLabel("")
        selected_requirement.setWordWrap(True)
        layout.addWidget(selected_requirement)

        def update_dialog_requirement():
            model = model_box.currentData()
            if not isinstance(model, str) or not model.strip():
                model = model_box.currentText().strip()
            temp_settings = dict(self.settings)
            temp_settings["model_source_mode"] = (
                    source_box.currentData() or "auto_with_local_fallback"
            )
            info = credential_requirement_for_model(model, temp_settings)
            if info["required"]:
                selected_requirement.setText(
                    f"Action required: {info['status']} {info['action']}"
                )
                selected_requirement.setStyleSheet(
                    "color: #ffe0a3; background-color: #33280d; border: 1px solid #80621d; padding: 6px;"
                )
            else:
                selected_requirement.setText(info["status"])
                selected_requirement.setStyleSheet(
                    "color: #b9dcff; background-color: #000711; border: 1px solid #1e9bff; padding: 6px;"
                )

        model_box.currentIndexChanged.connect(lambda _idx: update_dialog_requirement())
        model_box.currentTextChanged.connect(lambda _text: update_dialog_requirement())
        source_box.currentIndexChanged.connect(lambda _idx: update_dialog_requirement())
        update_dialog_requirement()

        runtime_title = QLabel("Source & Runtime")
        runtime_title.setStyleSheet(
            "font-weight: bold; color: #64b5f6; margin-top: 10px;"
        )
        layout.addWidget(runtime_title)

        config_row = QHBoxLayout()
        config_row.addWidget(QLabel("MCPHost config:"))
        settings_config_box = QComboBox()
        settings_config_box.setEditable(True)
        current_config = (
            self.config_box.currentText().strip()
            if hasattr(self, "config_box")
            else self.settings.get("config", "")
        )
        current_config = current_config or self.settings.get("config") or best_config()
        for cfg in [current_config] + DEFAULT_CONFIGS:
            if settings_config_box.findText(cfg) < 0:
                settings_config_box.addItem(cfg)
        settings_config_box.setEditText(current_config)
        settings_config_box.setToolTip("Config file passed to MCPHost with --config.")
        config_row.addWidget(settings_config_box, 1)
        browse_config_btn = QPushButton("Browse")
        config_row.addWidget(browse_config_btn)
        layout.addLayout(config_row)

        def browse_config_file():
            start = str(
                Path(settings_config_box.currentText().strip() or current_config).parent
            )
            selected, _ = QFileDialog.getOpenFileName(
                dialog,
                "Select MCPHost Config",
                start,
                "JSON Files (*.json);;All Files (*)",
            )
            if selected:
                settings_config_box.setEditText(selected)

        browse_config_btn.clicked.connect(browse_config_file)

        source_settings_row = QHBoxLayout()
        live_sources_settings_checkbox = QCheckBox("Allow live Web/GitHub sources")
        live_sources_settings_checkbox.setChecked(
            bool(self.settings.get("enable_live_sources", False))
        )
        live_sources_settings_checkbox.setToolTip(
            "Allows normal chat prompts to use live web/GitHub sources when useful."
        )
        source_settings_row.addWidget(live_sources_settings_checkbox)

        github_tools_settings_checkbox = QCheckBox(
            "Allow GitHub tools in workflow composition"
        )
        github_tools_settings_checkbox.setChecked(
            bool(self.settings.get("search_github_tools_when_composing", False))
        )
        github_tools_settings_checkbox.setToolTip(
            "Allows the workflow composer to search GitHub and use the configured external tools folder."
        )
        source_settings_row.addWidget(github_tools_settings_checkbox)

        reasoning_summary_settings_checkbox = QCheckBox("Show reasoning summary")
        reasoning_summary_settings_checkbox.setChecked(
            bool(self.settings.get("show_reasoning_summary", True))
        )
        reasoning_summary_settings_checkbox.setToolTip(
            "Shows safe routing/context summaries before answers without exposing hidden chain-of-thought."
        )
        source_settings_row.addWidget(reasoning_summary_settings_checkbox)

        simple_chat_settings_checkbox = QCheckBox("Simple chat responses")
        simple_chat_settings_checkbox.setChecked(
            bool(self.settings.get("simple_chat_responses", False))
        )
        simple_chat_settings_checkbox.setToolTip(
            "Keeps deterministic reports short. Disable for richer Codex-style feedback."
        )
        source_settings_row.addWidget(simple_chat_settings_checkbox)

        unreal_cpp_settings_checkbox = QCheckBox("Allow Unreal C++ bridge")
        unreal_cpp_settings_checkbox.setChecked(self.unreal_cpp_bridge_enabled())
        unreal_cpp_settings_checkbox.setToolTip(
            "Allows Tech Connector to recommend reflected C++ plugin bridge functions when Unreal Python is incomplete. "
            "Keep disabled for Blueprint-only projects."
        )
        source_settings_row.addWidget(unreal_cpp_settings_checkbox)
        source_settings_row.addStretch(1)
        layout.addLayout(source_settings_row)

        routing_title = QLabel("Model Routing")
        routing_title.setStyleSheet(
            "font-weight: bold; color: #64b5f6; margin-top: 8px;"
        )
        layout.addWidget(routing_title)

        routing_row = QHBoxLayout()
        routing_row.addWidget(QLabel("LLM planning:"))
        llm_planning_mode_box = QComboBox()
        llm_planning_mode_box.addItem("Fast first", "fast_first")
        llm_planning_mode_box.addItem("Manual/deep when requested", "manual_deep")
        idx = llm_planning_mode_box.findData(
            self.settings.get("llm_planning_mode", "fast_first")
        )
        if idx >= 0:
            llm_planning_mode_box.setCurrentIndex(idx)
        llm_planning_mode_box.setToolTip(
            "Use deterministic planning first, then a fast planner model unless a deep route is justified."
        )
        routing_row.addWidget(llm_planning_mode_box)

        routing_row.addWidget(QLabel("Deep route:"))
        deep_route_scope_box = QComboBox()
        deep_route_scope_box.addItem("Engine/complex only", "engine_complex_only")
        deep_route_scope_box.addItem("Engine + complex code", "engine_and_complex_code")
        deep_route_scope_box.addItem("All complex prompts", "all_complex")
        idx = deep_route_scope_box.findData(
            self.settings.get("deep_route_scope", "engine_complex_only")
        )
        if idx >= 0:
            deep_route_scope_box.setCurrentIndex(idx)
        deep_route_scope_box.setToolTip(
            "Controls when the router may use the deep model. Keep narrow for snappier indexed chat."
        )
        routing_row.addWidget(deep_route_scope_box)

        routing_row.addWidget(QLabel("Code deep threshold:"))
        deep_code_threshold_edit = QLineEdit()
        deep_code_threshold_edit.setText(
            str(self.settings.get("deep_code_complexity_threshold", 7))
        )
        deep_code_threshold_edit.setMaximumWidth(48)
        deep_code_threshold_edit.setToolTip("0-10 complexity threshold for complex code deep routing.")
        routing_row.addWidget(deep_code_threshold_edit)

        allow_30b_deep_checkbox = QCheckBox("Allow 30B deep route")
        allow_30b_deep_checkbox.setChecked(
            bool(self.settings.get("allow_30b_deep_route", False))
        )
        allow_30b_deep_checkbox.setToolTip(
            "Keep disabled unless you explicitly want the router to use a configured 30B deep model."
        )
        routing_row.addWidget(allow_30b_deep_checkbox)
        routing_row.addStretch(1)
        layout.addLayout(routing_row)

        research_title = QLabel("Research Mode")
        research_title.setStyleSheet(
            "font-weight: bold; color: #64b5f6; margin-top: 8px;"
        )
        layout.addWidget(research_title)

        research_row_1 = QHBoxLayout()
        research_project_snapshot_checkbox = QCheckBox("Project snapshot")
        research_project_snapshot_checkbox.setChecked(
            bool(self.settings.get("research_project_snapshot", True))
        )
        research_project_snapshot_checkbox.setToolTip(
            "Always prefer local project and loaded-level facts before external research."
        )
        research_row_1.addWidget(research_project_snapshot_checkbox)

        research_unreal_capabilities_checkbox = QCheckBox("Unreal capabilities")
        research_unreal_capabilities_checkbox.setChecked(
            bool(self.settings.get("research_unreal_capabilities", True))
        )
        research_unreal_capabilities_checkbox.setToolTip(
            "Inspect enabled Unreal plugins/modules/features before inventing custom systems."
        )
        research_row_1.addWidget(research_unreal_capabilities_checkbox)

        research_official_docs_checkbox = QCheckBox("Official docs")
        research_official_docs_checkbox.setChecked(
            bool(self.settings.get("research_official_docs", True))
        )
        research_official_docs_checkbox.setToolTip(
            "Prefer official engine/tool docs before general web sources."
        )
        research_row_1.addWidget(research_official_docs_checkbox)

        research_best_practices_checkbox = QCheckBox("Best-practice lookup")
        research_best_practices_checkbox.setChecked(
            bool(self.settings.get("research_best_practices", False))
        )
        research_best_practices_checkbox.setToolTip(
            "When local guidance is missing, stale, version-specific, or risky, offer authoritative best-practice research before planning."
        )
        research_row_1.addWidget(research_best_practices_checkbox)
        research_row_1.addStretch(1)
        layout.addLayout(research_row_1)

        research_row_2 = QHBoxLayout()
        research_web_techniques_checkbox = QCheckBox("Web techniques")
        research_web_techniques_checkbox.setChecked(
            bool(self.settings.get("research_web_techniques", False))
        )
        research_web_techniques_checkbox.setToolTip(
            "Allow curated web research for production techniques and patterns."
        )
        research_row_2.addWidget(research_web_techniques_checkbox)

        research_github_examples_checkbox = QCheckBox("GitHub examples")
        research_github_examples_checkbox.setChecked(
            bool(self.settings.get("research_github_examples", False))
        )
        research_github_examples_checkbox.setToolTip(
            "Allow GitHub example search with license/source review before ingesting code."
        )
        research_row_2.addWidget(research_github_examples_checkbox)

        research_compare_architectures_checkbox = QCheckBox("Compare architectures")
        research_compare_architectures_checkbox.setChecked(
            bool(self.settings.get("research_compare_architectures", True))
        )
        research_compare_architectures_checkbox.setToolTip(
            "Ask the model to compare viable approaches before committing to a plan."
        )
        research_row_2.addWidget(research_compare_architectures_checkbox)
        research_row_2.addStretch(1)
        layout.addLayout(research_row_2)

        research_row_3 = QHBoxLayout()
        research_generate_plan_checkbox = QCheckBox("Plan before edit")
        research_generate_plan_checkbox.setChecked(
            bool(self.settings.get("research_generate_plan", True))
        )
        research_generate_plan_checkbox.setToolTip(
            "Require an implementation plan before project mutation unless auto implement is enabled."
        )
        research_row_3.addWidget(research_generate_plan_checkbox)

        research_auto_implement_checkbox = QCheckBox("Auto implement")
        research_auto_implement_checkbox.setChecked(
            bool(self.settings.get("research_auto_implement", False))
        )
        research_auto_implement_checkbox.setToolTip(
            "Allow controlled endpoints to attempt implementation after planning."
        )
        research_row_3.addWidget(research_auto_implement_checkbox)

        ai_work_memory_checkbox = QCheckBox("Use previous AI work")
        ai_work_memory_checkbox.setChecked(
            bool(self.settings.get("ai_work_memory_enabled", True))
        )
        ai_work_memory_checkbox.setToolTip(
            "Include compact relevant records from previous Tech Connector operations."
        )
        research_row_3.addWidget(ai_work_memory_checkbox)

        ai_work_locked_checkbox = QCheckBox("Use locked knowledge")
        ai_work_locked_checkbox.setChecked(
            bool(self.settings.get("ai_work_memory_include_locked", True))
        )
        ai_work_locked_checkbox.setToolTip(
            "Include user-locked knowledge snapshots when planning."
        )
        research_row_3.addWidget(ai_work_locked_checkbox)
        research_row_3.addStretch(1)
        layout.addLayout(research_row_3)

        external_tools_row = QHBoxLayout()
        external_tools_row.addWidget(QLabel("External tools folder:"))
        external_tools_edit = QLineEdit()
        external_tools_edit.setText(self.settings.get("external_tools_dir", ""))
        external_tools_edit.setPlaceholderText(str(EXTERNAL_TOOLS_DIR))
        external_tools_edit.setToolTip(
            "Folder used for ingested GitHub/external Python tools."
        )
        external_tools_edit.setStyleSheet(
            "QLineEdit { background: #0b0f14; border: 1px solid #1e9bff; color: #d7dde5; padding: 4px; }"
        )
        external_tools_row.addWidget(external_tools_edit, 1)
        browse_tools_btn = QPushButton("Browse")
        external_tools_row.addWidget(browse_tools_btn)
        layout.addLayout(external_tools_row)

        dcc_packages = [str(path) for path in DCC_TOOL_PACKAGE_DIRS]
        dcc_package_label = QLabel(
            "Built-in DCC packages: "
            + (
                ", ".join(Path(path).name for path in dcc_packages)
                if dcc_packages
                else "none found under tools root"
            )
        )
        dcc_package_label.setWordWrap(True)
        dcc_package_label.setToolTip("\n".join(dcc_packages))
        dcc_package_label.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(dcc_package_label)

        def browse_external_tools_dir():
            start = external_tools_edit.text().strip() or str(EXTERNAL_TOOLS_DIR)
            selected = QFileDialog.getExistingDirectory(
                dialog, "Select External Tools Folder", start
            )
            if selected:
                external_tools_edit.setText(selected)

        browse_tools_btn.clicked.connect(browse_external_tools_dir)

        provider_title = QLabel("Enterprise Connections & API Keys")
        provider_title.setStyleSheet(
            "font-weight: bold; color: #64b5f6; margin-top: 10px;"
        )
        layout.addWidget(provider_title)

        vcs_row = QHBoxLayout()
        vcs_row.addWidget(QLabel("VCS Accounts:"))
        vcs_summary = QLabel(
            self._vcs_account_hint() or "No GitHub/Perforce account saved"
        )
        vcs_summary.setStyleSheet("color: #888888;")
        vcs_row.addWidget(vcs_summary, 1)
        vcs_login_btn = QPushButton("GitHub / Perforce Login")
        vcs_login_btn.clicked.connect(self.show_vcs_accounts_dialog)
        vcs_row.addWidget(vcs_login_btn)
        layout.addLayout(vcs_row)

        # Gemini Row
        gemini_row = QHBoxLayout()
        gemini_lbl = QLabel("Gemini API Key:")
        gemini_lbl.setMinimumWidth(100)
        gemini_row.addWidget(gemini_lbl)

        gemini_key_edit = QLineEdit()
        gemini_key_edit.setEchoMode(QLineEdit.Password)
        gemini_key_edit.setStyleSheet(
            "QLineEdit { background: #0b0f14; border: 1px solid #1e9bff; color: #d7dde5; padding: 4px; }"
        )
        gemini_key_edit.setText(
            self.settings.get("gemini_api_key", self.settings.get("google_api_key", ""))
        )
        gemini_row.addWidget(gemini_key_edit, 1)

        google_signin_btn = QPushButton("Open Google AI Studio Keys")
        google_signin_btn.setStyleSheet(
            "QPushButton { background-color: #0f141c; border: 1px solid #1e9bff; color: #b9dcff; padding: 4px 10px; } QPushButton:hover { background-color: #062b40; color: #ffffff; }"
        )
        gemini_row.addWidget(google_signin_btn)
        layout.addLayout(gemini_row)

        google_status = QLabel("")
        google_status.setStyleSheet(
            "color: #5bd000; font-size: 11px; margin-left: 104px;"
        )
        if self.settings.get("gemini_api_key") or self.settings.get("google_api_key"):
            google_status.setText("Connected")
        layout.addWidget(google_status)

        # Google Gemini currently uses API keys here. Open the official key page instead of a fake OAuth flow.
        def run_settings_google_auth():
            self.open_google_key_page()
            google_status.setText("Create/copy a Gemini API key, then paste it here.")

        google_signin_btn.clicked.connect(run_settings_google_auth)

        # OpenAI Row
        openai_row = QHBoxLayout()
        openai_lbl = QLabel("OpenAI API Key:")
        openai_lbl.setMinimumWidth(100)
        openai_row.addWidget(openai_lbl)

        openai_key_edit = QLineEdit()
        openai_key_edit.setEchoMode(QLineEdit.Password)
        openai_key_edit.setStyleSheet(
            "QLineEdit { background: #0b0f14; border: 1px solid #1e9bff; color: #d7dde5; padding: 4px; }"
        )
        openai_key_edit.setText(self.settings.get("openai_api_key", ""))
        openai_row.addWidget(openai_key_edit, 1)
        layout.addLayout(openai_row)

        # Anthropic Row
        anthropic_row = QHBoxLayout()
        anthropic_lbl = QLabel("Anthropic Key:")
        anthropic_lbl.setMinimumWidth(100)
        anthropic_row.addWidget(anthropic_lbl)

        anthropic_key_edit = QLineEdit()
        anthropic_key_edit.setEchoMode(QLineEdit.Password)
        anthropic_key_edit.setStyleSheet(
            "QLineEdit { background: #0b0f14; border: 1px solid #1e9bff; color: #d7dde5; padding: 4px; }"
        )
        anthropic_key_edit.setText(self.settings.get("anthropic_api_key", ""))
        anthropic_row.addWidget(anthropic_key_edit, 1)
        layout.addLayout(anthropic_row)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        def save_settings_from_dialog():
            mode = source_box.currentData() or "auto_with_local_fallback"
            model = model_box.currentData()
            if not isinstance(model, str) or not model.strip():
                model = model_box.currentText().strip()

            # Save keys from UI
            gemini_key = gemini_key_edit.text().strip()
            openai_key = openai_key_edit.text().strip()
            anthropic_key = anthropic_key_edit.text().strip()

            self.settings["gemini_api_key"] = gemini_key
            self.settings["google_api_key"] = gemini_key
            self.settings["openai_api_key"] = openai_key
            self.settings["anthropic_api_key"] = anthropic_key

            if gemini_key:
                os.environ["GEMINI_API_KEY"] = gemini_key
                os.environ["GOOGLE_API_KEY"] = gemini_key
            if openai_key:
                os.environ["OPENAI_API_KEY"] = openai_key
            if anthropic_key:
                os.environ["ANTHROPIC_API_KEY"] = anthropic_key

            self.service.set_model_source_mode(mode)
            self.settings = self.service.settings
            self.settings["model"] = model
            self.settings["config"] = (
                    settings_config_box.currentText().strip() or best_config()
            )
            self.settings["enable_live_sources"] = (
                live_sources_settings_checkbox.isChecked()
            )
            self.settings["show_reasoning_summary"] = (
                reasoning_summary_settings_checkbox.isChecked()
            )
            self.settings["simple_chat_responses"] = (
                simple_chat_settings_checkbox.isChecked()
            )
            self.settings["allow_unreal_cpp_bridge"] = (
                unreal_cpp_settings_checkbox.isChecked()
            )
            self.settings["search_github_tools_when_composing"] = (
                github_tools_settings_checkbox.isChecked()
            )
            self.settings["research_project_snapshot"] = (
                research_project_snapshot_checkbox.isChecked()
            )
            self.settings["research_unreal_capabilities"] = (
                research_unreal_capabilities_checkbox.isChecked()
            )
            self.settings["research_official_docs"] = (
                research_official_docs_checkbox.isChecked()
            )
            self.settings["research_best_practices"] = (
                research_best_practices_checkbox.isChecked()
            )
            self.settings["research_web_techniques"] = (
                research_web_techniques_checkbox.isChecked()
            )
            self.settings["research_github_examples"] = (
                research_github_examples_checkbox.isChecked()
            )
            self.settings["research_compare_architectures"] = (
                research_compare_architectures_checkbox.isChecked()
            )
            self.settings["research_generate_plan"] = (
                research_generate_plan_checkbox.isChecked()
            )
            self.settings["research_auto_implement"] = (
                research_auto_implement_checkbox.isChecked()
            )
            self.settings["llm_planning_mode"] = (
                llm_planning_mode_box.currentData() or "fast_first"
            )
            self.settings["deep_route_scope"] = (
                deep_route_scope_box.currentData() or "engine_complex_only"
            )
            try:
                threshold = int(deep_code_threshold_edit.text().strip())
            except Exception:
                threshold = 7
            self.settings["deep_code_complexity_threshold"] = max(0, min(10, threshold))
            self.settings["allow_30b_deep_route"] = (
                allow_30b_deep_checkbox.isChecked()
            )
            if (
                not self.settings["allow_30b_deep_route"]
                and str(self.settings.get("router_local_deep", "")).strip() == "qwen3:30b"
            ):
                self.settings["router_local_deep"] = "qwen3:14b"
            self.settings["ai_work_memory_enabled"] = (
                ai_work_memory_checkbox.isChecked()
            )
            self.settings["ai_work_memory_include_locked"] = (
                ai_work_locked_checkbox.isChecked()
            )
            self.settings["external_tools_dir"] = external_tools_edit.text().strip()
            self.service.save_settings(self.settings)
            self.mcphost_manager.settings = self.settings
            try:
                self.mcphost_manager.stop_all()
            except Exception:
                pass

            self.model_source_mode_box.blockSignals(True)
            idx = self.model_source_mode_box.findData(mode)
            if idx >= 0:
                self.model_source_mode_box.setCurrentIndex(idx)
            self.model_source_mode_box.blockSignals(False)

            self.add_model_option(
                "Saved Manual",
                model,
                {self.model_box.itemData(i) for i in range(self.model_box.count())},
            )
            idx = self.model_box.findData(model)
            if idx >= 0:
                self.model_box.setCurrentIndex(idx)
            else:
                self.model_box.setEditText(model)

            self.config_box.setEditText(self.settings["config"])
            self.live_sources_checkbox.blockSignals(True)
            self.live_sources_checkbox.setChecked(self.settings["enable_live_sources"])
            self.live_sources_checkbox.blockSignals(False)
            if hasattr(self, "show_reasoning_summary_checkbox"):
                self.show_reasoning_summary_checkbox.blockSignals(True)
                self.show_reasoning_summary_checkbox.setChecked(
                    bool(self.settings.get("show_reasoning_summary", True))
                )
                self.show_reasoning_summary_checkbox.blockSignals(False)
            if hasattr(self, "simple_response_checkbox"):
                self.simple_response_checkbox.blockSignals(True)
                self.simple_response_checkbox.setChecked(
                    bool(self.settings.get("simple_chat_responses", False))
                )
                self.simple_response_checkbox.blockSignals(False)
            if hasattr(self, "unreal_cpp_bridge_checkbox"):
                self.unreal_cpp_bridge_checkbox.blockSignals(True)
                self.unreal_cpp_bridge_checkbox.setChecked(
                    self.unreal_cpp_bridge_enabled()
                )
                self.unreal_cpp_bridge_checkbox.blockSignals(False)

            self.set_card("ollama", "unknown", "Not checked")
            self.update_active_response_model_label(model)
            self.append(
                f"\n[Settings] Saved provider/source/runtime settings: {mode}, {model}\n"
            )
            dialog.accept()

        save_btn.clicked.connect(save_settings_from_dialog)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def _on_dynamic_models_loaded(self, models):
        from tech_connector.models.constants import DEFAULT_MODEL

        selected_model = self.settings.get("model", DEFAULT_MODEL)
        for m in models:
            self.add_model_option("Installed", as_mcphost_model(m), self._seen_models)
        for i in range(self.model_box.count()):
            if self.model_box.itemData(i) == selected_model:
                self.model_box.setCurrentIndex(i)
                break
