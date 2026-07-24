from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
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
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from tech_connector.editor.editor_widget import CodeEditor
import json
import difflib
from pathlib import Path
import traceback
from tech_connector.models.constants import EXTERNAL_TOOLS_DIR, TOOLS_ROOT
from tech_connector.knowledge.search import find_in_project, local_answer_about_file

class EditorAssistWorker(QThread):
    finished_ok = Signal(str, dict)

    def __init__(self, path, question, text, parent=None):
        super().__init__(parent)
        self.path = path
        self.question = question
        self.text = text

    def run(self):
        try:
            result, patch = local_answer_about_file(self.path, self.question, self.text)
            self.finished_ok.emit(result, patch or {})
        except Exception as e:
            self.finished_ok.emit(f"[Editor Assist] Error during analysis: {e}", {})


class UnrealOperationConfirmDialog(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan = plan or {}
        self.setWindowTitle("Confirm Unreal Operation")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Unreal change ready")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        risk = str(self.plan.get("risk_level") or "unknown").upper()
        summary = QLabel(
            f"Operation: {self.plan.get('operation', 'unknown')}\n"
            f"Risk: {risk}\n"
            f"Requires confirmation: {'Yes' if self.plan.get('requires_confirmation') else 'No'}"
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #d0d0d0;")
        layout.addWidget(summary)

        details = QTextBrowser()
        details.setPlainText(json.dumps(self.plan, indent=2, default=str))
        details.setStyleSheet(
            "background-color: #161616; color: #dcdcdc; border: 1px solid #333; border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(details, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.accept)
        btn_row.addWidget(apply_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)


class UnrealCapabilityValidationDialog(QDialog):
    def __init__(self, project_root="", intel_service=None, parent=None):
        super().__init__(parent)
        self.project_root = project_root
        self.intel_service = intel_service
        self.setWindowTitle("Unreal Capability Validation")
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("compile blueprint, spawn actor, duplicate asset, unreal.EditorAssetLibrary...")
        search_row.addWidget(QLabel("Search"))
        search_row.addWidget(self.search_edit, 1)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search)
        search_row.addWidget(search_btn)
        refresh_btn = QPushButton("Refresh Reflection")
        refresh_btn.clicked.connect(self.refresh_reflection)
        search_row.addWidget(refresh_btn)
        layout.addLayout(search_row)

        self.results = QTableWidget(0, 5)
        self.results.setHorizontalHeaderLabels(["Kind", "Name", "Entrypoint", "Risk", "Score"])
        self.results.itemSelectionChanged.connect(self.show_selected_metadata)
        layout.addWidget(self.results, 2)

        detail_row = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Metadata"))
        self.metadata_view = QPlainTextEdit()
        self.metadata_view.setReadOnly(True)
        self.metadata_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        left.addWidget(self.metadata_view, 1)
        detail_row.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Payload JSON"))
        self.payload_edit = QPlainTextEdit()
        self.payload_edit.setPlainText("{}")
        self.payload_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        right.addWidget(self.payload_edit, 1)
        action_row = QHBoxLayout()
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self.validate_payload)
        action_row.addWidget(validate_btn)
        dry_run_btn = QPushButton("Dry Run")
        dry_run_btn.clicked.connect(lambda: self.execute_payload(dry_run=True))
        action_row.addWidget(dry_run_btn)
        execute_btn = QPushButton("Execute")
        execute_btn.clicked.connect(lambda: self.execute_payload(dry_run=False))
        action_row.addWidget(execute_btn)
        right.addLayout(action_row)
        detail_row.addLayout(right, 1)
        layout.addLayout(detail_row, 2)

        layout.addWidget(QLabel("Diagnostics / Raw JSON"))
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.output, 2)

    def _service(self):
        if self.intel_service:
            return self.intel_service
        from tech_connector.services.project_service import ProjectIntelligenceService

        self.intel_service = ProjectIntelligenceService(project_root=self.project_root)
        return self.intel_service

    def _payload(self):
        text = self.payload_edit.toPlainText().strip() or "{}"
        return json.loads(text)

    def _selected_name(self):
        row = self.results.currentRow()
        if row < 0:
            return self.search_edit.text().strip()
        item = self.results.item(row, 1)
        return item.text() if item else self.search_edit.text().strip()

    def _set_output(self, payload):
        self.output.setPlainText(json.dumps(payload, indent=2, default=str))

    def search(self):
        query = self.search_edit.text().strip()
        if not query:
            return
        service = self._service()
        ok, message = service.ensure_running(self.project_root)
        if not ok:
            self._set_output({"success": False, "error": message})
            return
        data = service.search_unreal_capabilities(query, limit=30) or {}
        self.results.setRowCount(0)
        rows = []
        for key in ("capabilities", "functions", "python_api", "symbols"):
            for item in data.get(key) or []:
                rows.append((key, item))
        for kind, item in rows:
            row = self.results.rowCount()
            self.results.insertRow(row)
            name = item.get("name") or item.get("qualified_name") or item.get("symbol_key") or ""
            entrypoint = item.get("entrypoint") or item.get("qualified_name") or ""
            risk = item.get("risk_level") or ""
            score = item.get("score") or ""
            values = [kind, name, entrypoint, risk, str(score)]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, item)
                self.results.setItem(row, col, cell)
        self._set_output(data)

    def show_selected_metadata(self):
        row = self.results.currentRow()
        if row < 0:
            return
        item = self.results.item(row, 0)
        data = item.data(Qt.UserRole) if item else {}
        self.metadata_view.setPlainText(json.dumps(data or {}, indent=2, default=str))

    def validate_payload(self):
        name = self._selected_name()
        if not name:
            return
        service = self._service()
        data = service.validate_unreal_capability(name, self._payload()) or {}
        self._set_output(data)

    def execute_payload(self, dry_run=False):
        name = self._selected_name()
        if not name:
            return
        service = self._service()
        data = service.execute_unreal_capability(
            name,
            self._payload(),
            dry_run=dry_run,
            timeout=45.0,
        ) or {}
        self._set_output(data)

    def refresh_reflection(self):
        service = self._service()
        ok, message = service.ensure_running(self.project_root)
        if not ok:
            self._set_output({"success": False, "error": message})
            return
        self._set_output({"status": "refreshing"})
        data = service.refresh_unreal_reflection(timeout=60.0) or {}
        self._set_output(data)


class EditorDiffWidget(QWidget):
    accepted_all = Signal(dict)  # Emitted with {path: new_content}
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pending_changes = {}  # path -> {"action": str, "original": str, "current": str}
        self.current_path = ""
        self.is_populating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top Header Bar
        header = QHBoxLayout()
        header.setContentsMargins(8, 8, 8, 8)

        self.title_label = QLabel("Comparing Changes:")
        self.title_label.setStyleSheet(
            "font-weight: bold; color: #a5d6a7; font-size: 13px;"
        )
        header.addWidget(self.title_label)

        # File selector dropdown (for multi-file changes)
        self.file_selector = QComboBox()
        self.file_selector.setMinimumWidth(300)
        self.file_selector.currentIndexChanged.connect(self.on_file_changed)
        header.addWidget(self.file_selector)

        header.addStretch(1)

        # Syntax Status Label
        self.syntax_status = QLabel("")
        self.syntax_status.setStyleSheet("font-weight: bold; margin-right: 12px;")
        header.addWidget(self.syntax_status)

        self.add_workflow_btn = QToolButton()
        self.add_workflow_btn.setText("Add to Workflow")
        self.add_workflow_btn.setPopupMode(QToolButton.InstantPopup)
        self.add_workflow_menu = QMenu(self.add_workflow_btn)
        self.add_workflow_menu.aboutToShow.connect(self.refresh_add_to_workflow_menu)
        self.add_workflow_btn.setMenu(self.add_workflow_menu)
        header.addWidget(self.add_workflow_btn)

        # Accept Button
        self.accept_btn = QPushButton("Accept Changes")
        self.accept_btn.setMinimumHeight(32)
        self.accept_btn.setStyleSheet(
            "background-color: #1b5e20; color: white; font-weight: bold; padding: 4px 16px; border-radius: 4px;"
        )
        self.accept_btn.clicked.connect(self.on_accept)
        header.addWidget(self.accept_btn)

        # Cancel Button
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(32)
        self.cancel_btn.setStyleSheet(
            "background-color: #37474f; color: white; padding: 4px 16px; border-radius: 4px;"
        )
        self.cancel_btn.clicked.connect(self.on_cancel)
        header.addWidget(self.cancel_btn)

        layout.addLayout(header)

        # Splitter for Left and Right Panels
        splitter = QSplitter(Qt.Horizontal)

        # Left Panel (Original)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 4, 0, 0)
        self.left_title = QLabel("Original Content (Read-Only):")
        left_layout.addWidget(self.left_title)
        self.left_editor = CodeEditor()
        self.left_editor.setReadOnly(True)
        left_layout.addWidget(self.left_editor)
        splitter.addWidget(left_container)

        # Right Panel (Modified / Editable)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 4, 0, 0)
        self.right_title = QLabel("Proposed Content (Editable):")
        right_layout.addWidget(self.right_title)
        self.right_editor = CodeEditor()
        self.right_editor.textChanged.connect(self.on_text_changed)
        self.right_editor.cursorPositionChanged.connect(
            self.refresh_right_editor_highlights
        )
        right_layout.addWidget(self.right_editor)
        splitter.addWidget(right_container)

        splitter.setSizes([500, 500])
        layout.addWidget(splitter)

    def first_changed_line(self, original, proposed):
        if not proposed:
            return 1
        if not original:
            return 1
        original_lines = original.splitlines()
        proposed_lines = proposed.splitlines()
        matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines)
        for tag, _i1, _i2, j1, _j2 in matcher.get_opcodes():
            if tag != "equal":
                return max(1, j1 + 1)
        return 1

    def changed_line_ranges(self, original, proposed):
        if not proposed:
            return []
        proposed_lines = proposed.splitlines()
        if not original:
            return [(1, max(1, len(proposed_lines)))]
        original_lines = original.splitlines()
        matcher = difflib.SequenceMatcher(None, original_lines, proposed_lines)
        ranges = []
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            start = max(1, j1 + 1)
            end = max(start, j2)
            ranges.append((start, end))
        return ranges

    def highlight_right_editor_changes(self, original, proposed):
        selections = []
        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor("#123f2a"))
        highlight_format.setProperty(QTextFormat.FullWidthSelection, True)

        for start, end in self.changed_line_ranges(original, proposed):
            for line_number in range(start, end + 1):
                block = self.right_editor.document().findBlockByNumber(line_number - 1)
                if not block.isValid():
                    continue
                selection = QTextEdit.ExtraSelection()
                selection.format = highlight_format
                selection.cursor = QTextCursor(block)
                selections.append(selection)

        current_line = QTextEdit.ExtraSelection()
        current_line.format.setBackground(QColor("#1a2b20"))
        current_line.format.setProperty(QTextFormat.FullWidthSelection, True)
        current_line.cursor = self.right_editor.textCursor()
        current_line.cursor.clearSelection()
        selections.append(current_line)

        self.right_editor.setExtraSelections(selections)

    def refresh_right_editor_highlights(self):
        if self.current_path not in self.pending_changes:
            return
        data = self.pending_changes[self.current_path]
        current = self.right_editor.toPlainText()
        self.highlight_right_editor_changes(data["original"], current)

    def scroll_right_editor_to_change(self, original, proposed):
        line_number = self.first_changed_line(original, proposed)

        def jump():
            self.right_editor.goto_line(line_number)
            self.highlight_right_editor_changes(original, proposed)

        QTimer.singleShot(0, jump)

    def set_changes(self, changes_list):
        self.pending_changes = {}
        self.is_populating = True
        self.file_selector.clear()

        for item in changes_list:
            path = item["path"]
            action = item["action"]
            original = item.get("original_content", "")
            proposed = item.get("new_content", "")

            self.pending_changes[path] = {
                "action": action,
                "original": original,
                "current": proposed,
            }
            from pathlib import Path

            self.file_selector.addItem(f"[{action.upper()}] {Path(path).name}", path)

        self.is_populating = False
        if changes_list:
            self.file_selector.setCurrentIndex(0)
            self.load_file_index(0)

    def load_file_index(self, index):
        if index < 0 or index >= self.file_selector.count():
            return

        path = self.file_selector.itemData(index)
        self.current_path = path
        data = self.pending_changes[path]

        self.is_populating = True

        from pathlib import Path

        if data["action"] == "create":
            self.title_label.setText(f"Comparing Changes: {Path(path).name} [NEW]")
            self.left_title.setText("Original (None - New File):")
            self.left_editor.setPlainText("")
            self.right_title.setText("New File Content (Editable):")
            self.right_editor.setPlainText(data["current"])
            self.highlight_right_editor_changes("", data["current"])
            self.scroll_right_editor_to_change("", data["current"])
        else:
            self.title_label.setText(f"Comparing Changes: {Path(path).name}")
            self.left_title.setText("Original Content (Read-Only):")
            self.left_editor.setPlainText(data["original"])
            self.right_title.setText("Proposed Content (Editable):")
            self.right_editor.setPlainText(data["current"])
            self.highlight_right_editor_changes(data["original"], data["current"])
            self.scroll_right_editor_to_change(data["original"], data["current"])

        self.is_populating = False
        self.validate_syntax()

    def on_file_changed(self, index):
        if self.is_populating:
            return
        if self.current_path in self.pending_changes:
            self.pending_changes[self.current_path]["current"] = (
                self.right_editor.toPlainText()
            )
        self.load_file_index(index)

    def on_text_changed(self):
        if self.is_populating:
            return
        if self.current_path in self.pending_changes:
            self.pending_changes[self.current_path]["current"] = (
                self.right_editor.toPlainText()
            )
            data = self.pending_changes[self.current_path]
            self.highlight_right_editor_changes(data["original"], data["current"])
        self.validate_syntax()

    def validate_syntax(self):
        if not self.current_path:
            return

        content = self.right_editor.toPlainText()
        if not self.current_path.endswith(".py"):
            self.syntax_status.setText("")
            self.accept_btn.setEnabled(True)
            return

        try:
            compile(content, self.current_path, "exec")
            self.syntax_status.setText("✓ Python Syntax Valid")
            self.syntax_status.setStyleSheet(
                "color: #00b866; font-weight: bold; margin-right: 12px;"
            )
            self.accept_btn.setEnabled(True)
        except Exception as e:
            self.syntax_status.setText(f"⚠️ Syntax Error: {str(e)}")
            self.syntax_status.setStyleSheet(
                "color: #ff5555; font-weight: bold; margin-right: 12px;"
            )
            self.accept_btn.setEnabled(False)

    def on_accept(self):
        if self.current_path in self.pending_changes:
            self.pending_changes[self.current_path]["current"] = (
                self.right_editor.toPlainText()
            )
        self.accepted_all.emit(self.pending_changes)

    def on_cancel(self):
        self.cancelled.emit()

    def refresh_add_to_workflow_menu(self):
        self.add_workflow_menu.clear()
        parent = self.parent()
        if parent and hasattr(parent, "populate_add_to_workflow_menu"):
            parent.populate_add_to_workflow_menu(
                self.add_workflow_menu, self.workflow_artifact_payload()
            )

    def workflow_artifact_payload(self):
        data = self.pending_changes.get(self.current_path, {})
        return {
            "title": f"Editor Diff: {Path(self.current_path).name if self.current_path else 'Proposed Changes'}",
            "source": "Editor diff approval",
            "content": data.get("current", self.right_editor.toPlainText()),
        }


class VCSWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args

    def run(self):
        try:
            res = self.fn(*self.args)
            if isinstance(res, tuple):
                ok, msg = res
            else:
                ok = True
                msg = str(res)
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))


class SearchWorker(QThread):
    finished = Signal(list)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        import json
        import urllib.parse
        import urllib.request

        from tech_connector.services.github_ingest_service import github_api_repo_url
        from tech_connector.services.version_control_service import github_auth_headers

        fallbacks = [
            {
                "name": "EpicGames/UnrealEngine",
                "description": "Official Unreal Engine source repository",
                "stars": 28500,
                "html_url": "https://github.com/EpicGames/UnrealEngine",
                "license": {"spdx_id": "NOASSERTION", "name": "Unreal Engine EULA"},
            },
            {
                "name": "matusnovak/maya-pymel",
                "description": "Python scripting in Autodesk Maya",
                "stars": 450,
                "html_url": "https://github.com/matusnovak/maya-pymel",
                "license": {"spdx_id": "MIT", "name": "MIT License"},
            },
            {
                "name": "Unity-Technologies/UnityCsReference",
                "description": "Unity C# reference source code",
                "stars": 12000,
                "html_url": "https://github.com/Unity-Technologies/UnityCsReference",
                "license": {"spdx_id": "NOASSERTION", "name": "Unity Companion License"},
            },
            {
                "name": "Autodesk/maya-usd",
                "description": "USD plugin for Autodesk Maya",
                "stars": 320,
                "html_url": "https://github.com/Autodesk/maya-usd",
                "license": {"spdx_id": "Apache-2.0", "name": "Apache License 2.0"},
            },
            {
                "name": "EpicGames/UnrealGenAISupport",
                "description": "Experimental generative AI hooks for Unreal Engine",
                "stars": 850,
                "html_url": "https://github.com/EpicGames/UnrealGenAISupport",
                "license": {"spdx_id": "MIT", "name": "MIT License"},
            },
            {
                "name": "DankHill2020/TheEntireWorld",
                "description": "Creative suite pipeline tools",
                "stars": 95,
                "html_url": "https://github.com/DankHill2020/TheEntireWorld",
                "license": {"spdx_id": "", "name": ""},
            },
        ]

        try:
            url = None
            exact_repo_query = False
            try:
                url = github_api_repo_url(self.query)
                exact_repo_query = True
            except ValueError:
                pass

            if not url:
                # Default search with topics
                url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(self.query)}+topic:unreal+OR+topic:maya+OR+topic:blender+OR+topic:unity&per_page=10"

            req = urllib.request.Request(url, headers=github_auth_headers())
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    res = json.loads(response.read().decode("utf-8"))
                    if exact_repo_query:
                        items = [res]
                    else:
                        items = res.get("items", [])
            except Exception:
                # Fallback to general search without topic restrictions
                fallback_url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(self.query)}&per_page=10"
                req = urllib.request.Request(
                    fallback_url, headers=github_auth_headers()
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    res = json.loads(response.read().decode("utf-8"))
                    items = res.get("items", [])

            results = []
            for item in items[:10]:
                if not isinstance(item, dict) or "full_name" not in item:
                    continue
                license_info = item.get("license") or {}
                results.append(
                    {
                        "name": item.get("full_name"),
                        "description": item.get("description")
                        or "No description provided.",
                        "stars": item.get("stargazers_count", 0),
                        "html_url": item.get("html_url"),
                        "language": item.get("language") or "",
                        "license": license_info,
                        "size": item.get("size", 0),
                        "archived": item.get("archived", False),
                        "updated_at": item.get("updated_at", ""),
                    }
                )
            if results:
                from tech_connector.services.external_tool_service import rank_github_candidate_repos

                self.finished.emit(rank_github_candidate_repos(results))
                return
        except Exception:
            pass

        q = self.query.lower()
        filtered = [
            f
            for f in fallbacks
            if q in f["name"].lower() or q in f["description"].lower()
        ]
        from tech_connector.services.external_tool_service import rank_github_candidate_repos

        self.finished.emit(rank_github_candidate_repos(filtered if filtered else fallbacks[:10]))


class GitHubCandidateSelectionDialog(QDialog):
    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.results = list(results or [])[:5]
        self.selected_repo = None
        self.setWindowTitle("Select GitHub Tool")
        self.resize(760, 460)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "No internal tool matched cleanly. Review the top GitHub candidates, select one to ingest, or cancel."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Horizontal)
        self.results_list = QListWidget()
        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)
        splitter.addWidget(self.results_list)

        self.details_box = QTextEdit()
        self.details_box.setReadOnly(True)
        splitter.addWidget(self.details_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.open_link_btn = QPushButton("Open Link")
        self.open_link_btn.setEnabled(False)
        self.open_link_btn.clicked.connect(self.open_selected_link)
        buttons.addWidget(self.open_link_btn)
        self.ingest_btn = QPushButton("Download / Ingest")
        self.ingest_btn.setEnabled(False)
        self.ingest_btn.clicked.connect(self.accept_selected)
        buttons.addWidget(self.ingest_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        for repo in self.results:
            item = QListWidgetItem(
                f"{repo.get('name', 'unknown')} (stars {repo.get('stars', 0)})"
            )
            item.setData(Qt.UserRole, repo)
            self.results_list.addItem(item)
        if self.results_list.count():
            self.results_list.setCurrentRow(0)

    def on_selection_changed(self):
        selected = self.results_list.selectedItems()
        if not selected:
            self.selected_repo = None
            self.ingest_btn.setEnabled(False)
            self.open_link_btn.setEnabled(False)
            self.details_box.clear()
            return

        repo = selected[0].data(Qt.UserRole) or {}
        self.selected_repo = repo
        self.ingest_btn.setEnabled(True)
        self.open_link_btn.setEnabled(bool(repo.get("html_url")))
        self.details_box.setPlainText(self._details(repo))

    def _details(self, repo):
        from tech_connector.services.external_tool_service import repo_preflight_summary

        preflight = repo_preflight_summary(repo)
        risks = ", ".join(preflight["risks"]) if preflight["risks"] else "none"
        return (
            f"Repository: {repo.get('name', '')}\n"
            f"Stars: {repo.get('stars', 0)}\n"
            f"URL: {repo.get('html_url', '')}\n\n"
            f"Preflight: {preflight['rating']}\n"
            f"Language: {preflight['language'] or 'unknown'}\n"
            f"License: {preflight['license'] or 'unknown'}\n"
            f"Size: {preflight['size_kb']} KB\n"
            f"Updated: {preflight['updated_at'] or 'unknown'}\n"
            f"Risks: {risks}\n\n"
            f"Description:\n{repo.get('description', '')}"
        )

    def accept_selected(self):
        if self.selected_repo:
            self.accept()

    def open_selected_link(self):
        if self.selected_repo and self.selected_repo.get("html_url"):
            QDesktopServices.openUrl(QUrl(str(self.selected_repo["html_url"])))


class IngestWorker(QThread):
    progress = Signal(str)
    progress_detail = Signal(str, int, int)
    finished = Signal(bool, str)

    def __init__(self, repo_name, repo_url, target_parent_dir):
        super().__init__()
        self.repo_name = repo_name
        self.repo_url = repo_url
        self.target_parent_dir = Path(target_parent_dir)

    def run(self):
        try:
            from tech_connector.services.github_ingest_service import download_and_extract_repo

            self._progress(f"Ingesting {self.repo_name} using structured extractor...")
            target_dir = download_and_extract_repo(
                self.repo_name,
                self.repo_url,
                self.target_parent_dir,
                progress_cb=self._progress,
            )

            # Check for Git repository at the project root to automatically ignore
            git_dir = self.target_parent_dir.parent / ".git"
            if git_dir.exists() and git_dir.is_dir():
                gitignore_path = self.target_parent_dir.parent / ".gitignore"
                rule = f"{self.target_parent_dir.name}/\n"
                if gitignore_path.exists():
                    try:
                        content = gitignore_path.read_text(encoding="utf-8")
                        if rule.strip() not in content:
                            if content and not content.endswith("\n"):
                                content += "\n"
                            content += rule
                            gitignore_path.write_text(content, encoding="utf-8")
                            self._progress(
                                f"Added {self.target_parent_dir.name}/ to .gitignore"
                            )
                    except Exception:
                        pass
                else:
                    try:
                        gitignore_path.write_text(rule, encoding="utf-8")
                        self._progress(
                            f"Created .gitignore with {self.target_parent_dir.name}/"
                        )
                    except Exception:
                        pass

            self.finished.emit(True, str(target_dir))
        except Exception as e:
            self.finished.emit(False, f"{e}\n\n{traceback.format_exc()}")

    def _progress(self, message, current=0, total=0):
        self.progress.emit(str(message))
        self.progress_detail.emit(str(message), int(current or 0), int(total or 0))


class WebImportDialog(QDialog):
    def __init__(
        self,
        parent=None,
        initial_query="",
        workflow_goal="",
        auto_search=False,
        auto_select_after_search=False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Web / GitHub Import")
        self.resize(1040, 760)
        self.setStyleSheet("""
            QDialog { background-color: #161a16; color: #cfcfcf; }
            QLineEdit { background-color: #111411; border: 1px solid #1f5f3a; color: #cfcfcf; padding: 4px; border-radius: 4px; }
            QPushButton { background-color: #1a301a; border: 1px solid #2d7a4d; color: #cfcfcf; padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background-color: #234723; }
            QListWidget { background-color: #111411; border: 1px solid #1f5f3a; color: #cfcfcf; border-radius: 4px; }
            QTextEdit { background-color: #111411; border: 1px solid #1f5f3a; color: #cfcfcf; border-radius: 4px; }
            QPlainTextEdit { background-color: #111411; border: 1px solid #1f5f3a; color: #cfcfcf; border-radius: 4px; }
        """)

        self.search_worker = None
        self.ingest_worker = None
        self.compose_worker = None
        self.results = []
        self.selected_repo = None
        self.ingested_path = None
        self.composed_code = ""
        self.saved_workflow = None
        self.auto_search = bool(auto_search)
        self.auto_select_after_search = bool(auto_select_after_search)
        default_install_dir = self.default_install_dir()

        layout = QVBoxLayout(self)

        # Search row
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search Query:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Enter keyword (e.g. unreal skeleton, maya rig)"
        )
        self.search_input.setText(initial_query)
        self.search_input.returnPressed.connect(self.perform_search)
        search_layout.addWidget(self.search_input, 1)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.perform_search)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)

        self.workflow_goal = QPlainTextEdit()
        self.workflow_goal.setPlaceholderText(
            "Describe the workflow to compose from local functions and ingested tools..."
        )
        self.workflow_goal.setPlainText(workflow_goal)
        self.workflow_goal.setMaximumHeight(90)
        layout.addWidget(self.workflow_goal)

        self.workflow_slots = QPlainTextEdit()
        self.workflow_slots.setPlaceholderText(
            "Workflow slots, one per line, e.g. bone=l_upper_cheek or parent=head1_ctrl"
        )
        self.workflow_slots.setMaximumHeight(70)
        layout.addWidget(self.workflow_slots)

        self.workflow_links = QPlainTextEdit()
        self.workflow_links.setPlaceholderText(
            "Step links / data flow, e.g. select_image.output -> image_to_mesh.image_path"
        )
        self.workflow_links.setMaximumHeight(70)
        layout.addWidget(self.workflow_links)

        install_layout = QHBoxLayout()
        install_layout.addWidget(QLabel("Install Folder:"))
        self.install_dir_input = QLineEdit()
        self.install_dir_input.setText(str(default_install_dir))
        self.install_dir_input.setToolTip(
            "GitHub repositories are extracted under this folder."
        )
        install_layout.addWidget(self.install_dir_input, 1)
        install_browse_btn = QPushButton("Browse")
        install_browse_btn.clicked.connect(self.choose_install_dir)
        install_layout.addWidget(install_browse_btn)
        layout.addLayout(install_layout)

        # Results splitter
        splitter = QSplitter(Qt.Horizontal)
        self.results_list = QListWidget()
        self.results_list.itemSelectionChanged.connect(self.on_selection_changed)
        splitter.addWidget(self.results_list)

        self.details_box = QTextEdit()
        self.details_box.setReadOnly(True)
        self.details_box.setPlaceholderText("Select an option to view details...")
        splitter.addWidget(self.details_box)

        layout.addWidget(splitter, 1)

        compose_splitter = QSplitter(Qt.Horizontal)
        self.internal_functions_list = QListWidget()
        self.internal_functions_list.setSelectionMode(QListWidget.MultiSelection)
        self.internal_functions_list.setToolTip(
            "Select one or more local project functions/classes to orchestrate."
        )
        compose_splitter.addWidget(self.internal_functions_list)

        self.ingested_tools_list = QListWidget()
        self.ingested_tools_list.setSelectionMode(QListWidget.MultiSelection)
        self.ingested_tools_list.setToolTip(
            "After ingestion, select one or more functions/classes from the downloaded repository."
        )
        compose_splitter.addWidget(self.ingested_tools_list)

        self.composed_output = QTextEdit()
        self.composed_output.setReadOnly(True)
        self.composed_output.setPlaceholderText(
            "Composed workflow code appears here..."
        )
        compose_splitter.addWidget(self.composed_output)

        layout.addWidget(compose_splitter, 1)

        # Progress and status info
        self.status_label = QLabel("Enter search term to list closest options.")
        self.status_label.setStyleSheet("color: #a0a0a0;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Action buttons
        buttons_layout = QHBoxLayout()
        self.ingest_btn = QPushButton("Select & Ingest")
        self.ingest_btn.setEnabled(False)
        self.ingest_btn.clicked.connect(self.perform_ingest)
        buttons_layout.addWidget(self.ingest_btn)

        self.open_repo_btn = QPushButton("Open Link")
        self.open_repo_btn.setEnabled(False)
        self.open_repo_btn.clicked.connect(self.open_selected_repo_link)
        buttons_layout.addWidget(self.open_repo_btn)

        self.refresh_functions_btn = QPushButton("Refresh Functions")
        self.refresh_functions_btn.clicked.connect(self.load_function_choices)
        buttons_layout.addWidget(self.refresh_functions_btn)

        self.suggest_links_btn = QPushButton("Suggest Links")
        self.suggest_links_btn.clicked.connect(self.suggest_workflow_links)
        buttons_layout.addWidget(self.suggest_links_btn)

        self.compose_btn = QPushButton("Compose Workflow")
        self.compose_btn.setEnabled(False)
        self.compose_btn.clicked.connect(self.compose_workflow)
        buttons_layout.addWidget(self.compose_btn)

        self.insert_btn = QPushButton("Insert In Chat")
        self.insert_btn.setEnabled(False)
        self.insert_btn.clicked.connect(self.insert_composed_workflow)
        buttons_layout.addWidget(self.insert_btn)

        self.save_workflow_btn = QPushButton("Save Workflow")
        self.save_workflow_btn.setEnabled(False)
        self.save_workflow_btn.clicked.connect(self.save_composed_workflow)
        buttons_layout.addWidget(self.save_workflow_btn)

        self.done_btn = QPushButton("Done")
        self.done_btn.setEnabled(False)
        self.done_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(self.done_btn)

        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_btn)

        layout.addLayout(buttons_layout)
        self.load_function_choices()
        if self.auto_search and initial_query:
            QTimer.singleShot(0, self.perform_search)

    def default_install_dir(self):
        main_win = self.parent()
        if main_win and hasattr(main_win, "settings"):
            configured = main_win.settings.get("external_tools_dir", "")
            if configured:
                return Path(configured)
        return EXTERNAL_TOOLS_DIR

    def choose_install_dir(self):
        start = self.install_dir_input.text().strip() or str(self.default_install_dir())
        selected = QFileDialog.getExistingDirectory(
            self, "Select External Tools Install Folder", start
        )
        if selected:
            self.install_dir_input.setText(selected)
            main_win = self.parent()
            if (
                main_win
                and hasattr(main_win, "settings")
                and hasattr(main_win, "service")
            ):
                main_win.settings["external_tools_dir"] = selected
                main_win.service.save_settings()
            self.load_function_choices()

    def perform_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        self.status_label.setText("Searching GitHub repositories...")
        self.results_list.clear()
        self.details_box.clear()
        self.ingest_btn.setEnabled(False)
        self.open_repo_btn.setEnabled(False)
        self.search_btn.setEnabled(False)

        self.search_worker = SearchWorker(query)
        self.search_worker.finished.connect(self.on_search_finished)
        self.search_worker.start()

    def on_search_finished(self, results):
        self.search_btn.setEnabled(True)
        self.results = list(results or [])[:5]
        if not results:
            self.status_label.setText("No options found.")
            if self.auto_select_after_search:
                self.reject()
            return

        self.status_label.setText(
            f"Showing top {len(self.results)} GitHub candidates. Select one to review or open."
        )
        for item in self.results:
            list_item = QListWidgetItem(f"{item['name']} (★ {item['stars']})")
            list_item.setData(Qt.UserRole, item)
            self.results_list.addItem(list_item)
        if self.auto_select_after_search:
            self.prompt_top_candidate_for_ingest()

    def prompt_top_candidate_for_ingest(self):
        self.auto_select_after_search = False
        dialog = GitHubCandidateSelectionDialog(self.results[:5], self)
        if dialog.exec_() != QDialog.Accepted or not dialog.selected_repo:
            self.status_label.setText("GitHub ingest canceled.")
            self.reject()
            return

        self.selected_repo = dialog.selected_repo
        for index in range(self.results_list.count()):
            item = self.results_list.item(index)
            if item.data(Qt.UserRole) == self.selected_repo:
                self.results_list.setCurrentItem(item)
                break
        self.perform_ingest()

    def on_selection_changed(self):
        selected = self.results_list.selectedItems()
        if not selected:
            self.details_box.clear()
            self.ingest_btn.setEnabled(False)
            self.open_repo_btn.setEnabled(False)
            self.selected_repo = None
            return

        item = selected[0].data(Qt.UserRole)
        self.selected_repo = item
        self.ingest_btn.setEnabled(True)
        self.open_repo_btn.setEnabled(bool(item.get("html_url")))
        from tech_connector.services.external_tool_service import repo_preflight_summary

        preflight = repo_preflight_summary(item)
        risks = ", ".join(preflight["risks"]) if preflight["risks"] else "none"

        details = (
            f"Repository: {item['name']}\n"
            f"Stars: {item['stars']}\n"
            f"URL: {item['html_url']}\n\n"
            f"Preflight: {preflight['rating']}\n"
            f"Language: {preflight['language'] or 'unknown'}\n"
            f"License: {preflight['license'] or 'unknown'}\n"
        )
        self.details_box.setPlainText(details)

    def open_selected_repo_link(self):
        if self.selected_repo and self.selected_repo.get("html_url"):
            QDesktopServices.openUrl(QUrl(str(self.selected_repo["html_url"])))

    def perform_ingest(self):
        if not self.selected_repo:
            return

        repo_name = self.selected_repo["name"]
        repo_url = self.selected_repo["html_url"]

        self.ingest_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(f"Ingesting {repo_name}...")

        target_parent = Path(
            self.install_dir_input.text().strip() or str(self.default_install_dir())
        )
        main_win = self.parent()
        if main_win and hasattr(main_win, "settings") and hasattr(main_win, "service"):
            main_win.settings["external_tools_dir"] = str(target_parent)
            main_win.service.save_settings()

        # Mirror progress to main window's system status panel
        top_win = self.window()
        if top_win and hasattr(top_win, "download_status") and hasattr(top_win, "download_progress"):
            top_win.download_status.setText(f"Ingesting {repo_name}...")
            top_win.download_status.setVisible(True)
            top_win.download_progress.setRange(0, 0)
            top_win.download_progress.setVisible(True)
            if hasattr(top_win, "system_status_body") and not top_win.system_status_body.isVisible():
                if hasattr(top_win, "toggle_system_status_panel"):
                    top_win.toggle_system_status_panel()

        self.ingest_worker = IngestWorker(repo_name, repo_url, target_parent)
        self.ingest_worker.progress.connect(self.status_label.setText)
        self.ingest_worker.progress_detail.connect(self.on_ingest_progress)
        self.ingest_worker.finished.connect(self.on_ingest_finished)
        self.ingest_worker.start()

    def on_ingest_progress(self, message, current, total):
        self.status_label.setText(message)
        self.progress_bar.setVisible(True)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(max(0, min(current, total)))
        else:
            self.progress_bar.setRange(0, 0)

        # Mirror to main window
        top_win = self.window()
        if top_win and hasattr(top_win, "download_status") and hasattr(top_win, "download_progress"):
            top_win.download_status.setText(message)
            if total > 0:
                top_win.download_progress.setRange(0, total)
                top_win.download_progress.setValue(max(0, min(current, total)))
            else:
                top_win.download_progress.setRange(0, 0)

    def on_ingest_finished(self, success, result):
        self.progress_bar.setVisible(False)
        self.cancel_btn.setEnabled(True)

        # Hide main window status panel download widgets
        top_win = self.window()
        if top_win and hasattr(top_win, "download_status") and hasattr(top_win, "download_progress"):
            top_win.download_status.setVisible(False)
            top_win.download_progress.setVisible(False)

        if success:
            self.ingested_path = result
            try:
                from tech_connector.services.external_tool_service import analyze_installed_tool

                manifest = analyze_installed_tool(
                    Path(result), self.selected_repo or {}
                )
                if manifest.get("disabled"):
                    self.status_label.setText(
                        f"Ingested but disabled for composition: {', '.join(manifest.get('risks', []))}"
                    )
                else:
                    self.status_label.setText(
                        f"Ingested into {result}. Manifest created; select functions/tools to compose."
                    )
            except Exception as e:
                self.status_label.setText(
                    f"Ingested into {result}. Manifest creation failed: {e}"
                )
            try:
                main_win = self.parent()
                settings = getattr(main_win, "settings", {}) if main_win else {}
                from tech_connector.services.ai_work_memory_service import record_approved_external_learning

                record_approved_external_learning(
                    settings,
                    source_kind="github_tool_ingest",
                    query=self.workflow_goal.toPlainText().strip() or self.search_input.text().strip(),
                    approved_item=self.selected_repo or {},
                    local_path=str(result),
                    host="workflow",
                    summary=(
                        f"User approved and ingested GitHub tool "
                        f"{(self.selected_repo or {}).get('name', '')} into {result}."
                    ),
                )
                self.status_label.setText(self.status_label.text() + " Learning saved.")
            except Exception:
                pass
            self.load_function_choices()
            self.compose_btn.setEnabled(True)
            self.done_btn.setEnabled(True)
            QMessageBox.information(
                self,
                "Ingestion Successful",
                f"Repository successfully ingested into:\n{result}\n\nSelect local and ingested functions, then compose a workflow.",
            )
        else:
            QMessageBox.critical(
                self,
                "Ingestion Failed",
                f"An error occurred during ingestion:\n{result}",
            )
            self.ingest_btn.setEnabled(True)
            self.status_label.setText("Ingestion failed. Try another option or cancel.")

    def load_function_choices(self):
        from tech_connector.services.external_tool_service import rank_symbols
        from tech_connector.services.tool_discovery_service import (
            list_ingested_tools,
            list_internal_functions,
        )

        self.internal_functions_list.clear()
        self.ingested_tools_list.clear()

        main_win = self.parent()
        roots = (
            main_win.project_roots()
            if main_win and hasattr(main_win, "project_roots")
            else []
        )
        goal = self.workflow_goal.toPlainText().strip()
        internal_functions = rank_symbols(
            list_internal_functions(roots), goal, host="maya"
        )
        for func in internal_functions[:500]:
            item = QListWidgetItem(self._function_label(func))
            item.setData(Qt.UserRole, func)
            self.internal_functions_list.addItem(item)

        external_tools_dir = (
            Path(self.ingested_path)
            if self.ingested_path
            else Path(
                self.install_dir_input.text().strip() or str(self.default_install_dir())
            )
        )
        if external_tools_dir:
            ingested_tools = rank_symbols(
                list_ingested_tools(external_tools_dir), goal, host="maya"
            )
            for tool in ingested_tools[:500]:
                item = QListWidgetItem(self._function_label(tool))
                item.setData(Qt.UserRole, tool)
                self.ingested_tools_list.addItem(item)

        self.status_label.setText(
            f"Loaded {self.internal_functions_list.count()} local symbols and "
            f"{self.ingested_tools_list.count()} ingested symbols."
        )

    def _function_label(self, item):
        from tech_connector.services.capability_service import format_contract

        name = item.get("signature") or item.get("name") or "unnamed"
        path = item.get("file_path") or ""
        score = item.get("score", 0)
        score_text = f" score:{score}" if score else ""
        contract = format_contract(item)
        contract_text = f" {contract}" if contract else ""
        return f"{name}{score_text}{contract_text}  [{Path(path).name}]"

    def _selected_symbol_data(self, widget):
        return [item.data(Qt.UserRole) for item in widget.selectedItems()]

    def _widget_symbol_data(self, widget):
        return [widget.item(index).data(Qt.UserRole) for index in range(widget.count())]

    def _select_symbols_by_name(self, widget, names):
        wanted = {name for name in names if name}
        if not wanted:
            return
        for index in range(widget.count()):
            item = widget.item(index)
            data = item.data(Qt.UserRole) or {}
            if data.get("name") in wanted:
                item.setSelected(True)

    def _live_github_enabled(self):
        main_win = self.parent()
        settings = getattr(main_win, "settings", {}) if main_win else {}
        return bool(
            settings.get("enable_live_sources", False)
            or settings.get("search_github_tools_when_composing", False)
        )

    def suggest_workflow_links(self):
        internal = self._selected_symbol_data(self.internal_functions_list)
        external = self._selected_symbol_data(self.ingested_tools_list)
        if not internal:
            QMessageBox.information(
                self,
                "Select Functions",
                "Select at least one upstream local function first.",
            )
            return
        from tech_connector.services.capability_service import recommend_workflow_connections

        recommendation = recommend_workflow_connections(
            internal,
            self._widget_symbol_data(self.internal_functions_list),
            external,
        )
        links = recommendation.get("links", [])
        if not links:
            if self._live_github_enabled():
                goal = self.workflow_goal.toPlainText().strip()
                reply = QMessageBox.question(
                    self,
                    "Search GitHub Tools?",
                    "No internal follow-up tool matched this workflow.\n\nSearch GitHub and show the top 5 candidates for review?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    if goal:
                        self.search_input.setText(goal)
                    self.auto_select_after_search = True
                    self.status_label.setText(
                        "Searching GitHub for reviewable tool candidates..."
                    )
                    self.perform_search()
                else:
                    self.status_label.setText("External tool search canceled.")
                return
            QMessageBox.information(
                self,
                "No Links Suggested",
                "No obvious output/input match was inferred. You can still type a link manually.",
            )
            return
        if recommendation.get("source") == "internal":
            recommended_names = []
            for link in links:
                source = link.split("->", 1)[0].strip() if "->" in link else ""
                target = link.split("->", 1)[1].strip() if "->" in link else ""
                if "." in source:
                    recommended_names.append(source.split(".", 1)[0])
                if "." in target:
                    recommended_names.append(target.split(".", 1)[0])
            self._select_symbols_by_name(
                self.internal_functions_list, recommended_names
            )
        existing = self.workflow_links.toPlainText().strip()
        combined = existing + ("\n" if existing else "") + "\n".join(links)
        self.workflow_links.setPlainText(combined)
        self.status_label.setText(
            f"{recommendation.get('message', 'Suggested workflow links')} Review before composing."
        )

    def compose_workflow(self):
        goal = self.workflow_goal.toPlainText().strip()
        internal = self._selected_symbol_data(self.internal_functions_list)
        external = self._selected_symbol_data(self.ingested_tools_list)

        if not goal:
            QMessageBox.information(
                self, "Workflow Goal Needed", "Describe the workflow before composing."
            )
            return
        if not internal and not external:
            QMessageBox.information(
                self,
                "Select Functions",
                "Select at least one local or ingested function.",
            )
            return

        from tech_connector.services.function_composer_service import compose_composite_function

        self.compose_btn.setEnabled(False)
        self.insert_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Composing workflow wrapper...")
        self.compose_worker = ComposeWorker(
            internal,
            external,
            goal,
            self.workflow_links.toPlainText(),
        )
        self.compose_worker.finished.connect(self.on_compose_finished)
        self.compose_worker.start()

    def on_compose_finished(self, success, result):
        self.progress_bar.setVisible(False)
        self.compose_btn.setEnabled(True)
        if success:
            self.composed_code = result
            self.composed_output.setPlainText(result)
            self.insert_btn.setEnabled(bool(result.strip()))
            self.save_workflow_btn.setEnabled(bool(result.strip()))
            self.status_label.setText(
                "Workflow composed. Review it, then save/register or insert it into chat."
            )
        else:
            self.status_label.setText("Workflow composition failed.")
            QMessageBox.critical(self, "Composition Failed", result)

    def insert_composed_workflow(self):
        if not self.composed_code.strip():
            return
        self.accept()

    def save_composed_workflow(self):
        if not self.composed_code.strip():
            return
        main_win = self.parent()
        roots = (
            main_win.project_roots()
            if main_win and hasattr(main_win, "project_roots")
            else []
        )
        if not roots:
            QMessageBox.information(
                self, "No Project", "Load a project before saving a workflow."
            )
            return
        goal = self.workflow_goal.toPlainText().strip()
        selected = self._selected_symbol_data(
            self.internal_functions_list
        ) + self._selected_symbol_data(self.ingested_tools_list)
        try:
            from tech_connector.services.workflow_service import (
                resolve_project_root,
                save_composed_workflow,
            )

            project_root = resolve_project_root(roots[0])

            saved = save_composed_workflow(
                project_root,
                self.composed_code,
                goal,
                slots_text=self.workflow_slots.toPlainText(),
                workflow_links=self.workflow_links.toPlainText(),
                selected_items=selected,
            )
            self.saved_workflow = saved
            try:
                from tech_connector.services.ai_work_memory_service import record_approved_external_learning

                main_win = self.parent()
                settings = getattr(main_win, "settings", {}) if main_win else {}
                selected_repo = self.selected_repo or {}
                record_approved_external_learning(
                    settings,
                    source_kind="github_workflow_result",
                    query=goal,
                    approved_item=selected_repo,
                    local_path=str(self.ingested_path or ""),
                    workflow_path=str(saved.module_path),
                    host="workflow",
                    summary=(
                        f"User approved saved workflow {saved.function_path}. "
                        f"Manifest: {saved.manifest_path}. Test: {saved.test_path}."
                    ),
                )
            except Exception:
                pass
            self.composed_output.setPlainText(
                self.composed_code.rstrip()
                + "\n\n# Registered workflow call payload:\n"
                + saved.call_payload
            )
            self.status_label.setText(f"Workflow saved: {saved.function_path}")
            self.insert_btn.setEnabled(True)
            QMessageBox.information(
                self,
                "Workflow Saved",
                f"Saved workflow:\n{saved.module_path}\n\nTest:\n{saved.test_path}\n\nPayload:\n{saved.call_payload}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Workflow Failed", str(e))

class ComposeWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, internal, external, goal, workflow_links):
        super().__init__()
        self.internal = internal
        self.external = external
        self.goal = goal
        self.workflow_links = workflow_links

    def run(self):
        try:
            from tech_connector.services.function_composer_service import compose_composite_function

            result = compose_composite_function(
                self.internal,
                self.external,
                self.goal,
                self.workflow_links,
            )
            self.finished.emit(True, result)
        except Exception as e:
            self.finished.emit(False, f"{e}\n\n{traceback.format_exc()}")
