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
from pathlib import Path

class ProjectChangesDialog(QDialog):
    def __init__(self, changes, explanation, parent=None):
        super().__init__(parent)
        self.changes = changes
        self.setWindowTitle("Review Project-Wide Changes")
        self.resize(1140, 820)
        self.setStyleSheet("""
            QDialog { background-color: #161a16; color: #cfcfcf; }
            QListWidget { background-color: #111411; border: 1px solid #1f5f3a; color: #cfcfcf; border-radius: 4px; }
            QListWidget::item:selected { background-color: #1f5f3a; color: white; }
            QLabel { color: #cfcfcf; }
            QPushButton { background-color: #1a301a; border: 1px solid #2d7a4d; color: #cfcfcf; padding: 6px 16px; border-radius: 4px; }
            QPushButton:hover { background-color: #234723; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.expl_browser = QTextBrowser()
        self.expl_browser.setMarkdown(explanation)
        self.expl_browser.setMaximumHeight(140)
        self.expl_browser.setStyleSheet(
            "background-color: #111411; color: #e0e0e0; border: 1px solid #1f5f3a; border-radius: 4px; padding: 6px;"
        )
        layout.addWidget(self.expl_browser)

        self.main_splitter = QSplitter(Qt.Horizontal, self)

        self.files_list = QListWidget()
        self.files_list.itemSelectionChanged.connect(self.on_file_selection_changed)
        self.main_splitter.addWidget(self.files_list)

        self.compare_container = QWidget()
        self.compare_layout = QVBoxLayout(self.compare_container)
        self.compare_layout.setContentsMargins(0, 0, 0, 0)

        code_compare_widget = QWidget()
        code_compare_layout = QHBoxLayout(code_compare_widget)
        code_compare_layout.setContentsMargins(0, 0, 0, 0)
        code_compare_layout.setSpacing(10)

        orig_widget = QWidget()
        orig_layout = QVBoxLayout(orig_widget)
        orig_layout.setContentsMargins(0, 0, 0, 0)
        self.orig_title = QLabel("Original Code:")
        self.orig_title.setStyleSheet(
            "font-weight: bold; color: #ff8a80; font-size: 11px;"
        )
        self.orig_edit = QPlainTextEdit()
        self.orig_edit.setReadOnly(True)
        self.orig_edit.setFont(QFont("Consolas", 10))
        self.orig_edit.setStyleSheet(
            "background-color: #2d1a1a; color: #ffbcbc; border: 1px solid #7a2222; border-radius: 4px; padding: 6px;"
        )
        orig_layout.addWidget(self.orig_title)
        orig_layout.addWidget(self.orig_edit)
        orig_widget.setLayout(orig_layout)
        self.orig_container = orig_widget
        code_compare_layout.addWidget(orig_widget, 1)

        new_widget = QWidget()
        new_layout = QVBoxLayout(new_widget)
        new_layout.setContentsMargins(0, 0, 0, 0)
        self.new_title = QLabel("Proposed Code (Editable):")
        self.new_title.setStyleSheet(
            "font-weight: bold; color: #a5d6a7; font-size: 11px;"
        )
        self.new_edit = QPlainTextEdit()
        self.new_edit.setFont(QFont("Consolas", 10))
        self.new_edit.setStyleSheet(
            "background-color: #1a2d1a; color: #c8e6c9; border: 1px solid #2e7d32; border-radius: 4px; padding: 6px;"
        )
        self.new_edit.textChanged.connect(self.on_code_edited)

        self.syntax_label = QLabel("")
        self.syntax_label.setStyleSheet(
            "font-weight: bold; font-size: 11px; margin-top: 4px;"
        )

        new_layout.addWidget(self.new_title)
        new_layout.addWidget(self.new_edit)
        new_layout.addWidget(self.syntax_label)
        new_widget.setLayout(new_layout)
        code_compare_layout.addWidget(new_widget, 1)

        self.compare_layout.addWidget(code_compare_widget, 1)
        self.main_splitter.addWidget(self.compare_container)

        self.main_splitter.setSizes([260, 840])
        layout.addWidget(self.main_splitter, 1)

        btn_row = QHBoxLayout()
        self.status_lbl = QLabel(f"{len(changes)} files scheduled for modification.")
        self.status_lbl.setStyleSheet("color: #a0a0a0;")
        btn_row.addWidget(self.status_lbl)
        btn_row.addStretch(1)

        self.apply_btn = QPushButton("Apply All Changes")
        self.apply_btn.setMinimumHeight(32)
        self.apply_btn.setStyleSheet(
            "padding: 0px 24px; font-weight: bold; background-color: #1b5e20; color: white;"
        )
        self.apply_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.apply_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

        self.populate_files()

    def populate_files(self):
        for idx, change in enumerate(self.changes):
            path = change["path"]
            action = change["action"].upper()
            display_name = f"[{action}] {Path(path).name} ({path})"
            list_item = QListWidgetItem(display_name)
            list_item.setData(Qt.UserRole, idx)
            self.files_list.addItem(list_item)

        if self.changes:
            self.files_list.setCurrentRow(0)

    def on_file_selection_changed(self):
        selected = self.files_list.selectedItems()
        if not selected:
            return

        idx = selected[0].data(Qt.UserRole)
        change = self.changes[idx]

        self.orig_edit.blockSignals(True)
        self.new_edit.blockSignals(True)

        if change["action"] == "create":
            self.orig_container.setVisible(False)
            self.orig_edit.clear()
            self.new_title.setText("New File Content (Editable):")
            self.new_edit.setPlainText(change["new_content"])
        else:
            self.orig_container.setVisible(True)
            self.orig_title.setText("Original Code Block:")
            self.orig_edit.setPlainText(change.get("original_content", ""))
            self.new_title.setText("Proposed Replacement (Editable):")
            self.new_edit.setPlainText(change["new_content"])

        self.orig_edit.blockSignals(False)
        self.new_edit.blockSignals(False)
        self.verify_active_syntax()

    def on_code_edited(self):
        selected = self.files_list.selectedItems()
        if not selected:
            return
        idx = selected[0].data(Qt.UserRole)
        self.changes[idx]["new_content"] = self.new_edit.toPlainText()
        self.verify_active_syntax()

    def verify_active_syntax(self):
        selected = self.files_list.selectedItems()
        if not selected:
            self.syntax_label.clear()
            return
        idx = selected[0].data(Qt.UserRole)
        change = self.changes[idx]
        path = change["path"]

        if path.endswith(".py"):
            content_to_check = change["new_content"]
            try:
                compile(content_to_check, "<string>", "exec")
                self.syntax_label.setText("✓ Python Syntax Valid")
                self.syntax_label.setStyleSheet("color: #a5d6a7; font-weight: bold;")
            except SyntaxError as e:
                self.syntax_label.setText(
                    f"⚠️ Python Syntax Error: {e.msg} (line {e.lineno})"
                )
                self.syntax_label.setStyleSheet("color: #ff8a80; font-weight: bold;")
            except Exception as e:
                self.syntax_label.setText(f"⚠️ Check Error: {e}")
                self.syntax_label.setStyleSheet("color: #ff8a80; font-weight: bold;")
        else:
            self.syntax_label.setText("— Non-Python File")
            self.syntax_label.setStyleSheet("color: #888888;")


class ChatLogBrowser(QTextBrowser):
    """A custom QTextBrowser that allows inline editing only within Consolas/Monospace code blocks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(False)
        self.setUndoRedoEnabled(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        cursor = self.textCursor()

        copy_selection = menu.addAction("Copy Selection")
        copy_selection.setEnabled(cursor.hasSelection())
        copy_selection.triggered.connect(self.copy)

        parent = self.window()
        copy_response = menu.addAction("Copy Response")
        if hasattr(parent, "copy_current_chat_response"):
            copy_response.triggered.connect(parent.copy_current_chat_response)
        else:
            copy_response.setEnabled(False)

        copy_thread = menu.addAction("Copy Thread")
        if hasattr(parent, "copy_full_log"):
            copy_thread.triggered.connect(parent.copy_full_log)
        else:
            copy_thread.setEnabled(False)

        menu.addSeparator()
        prev_response = menu.addAction("Previous Response")
        next_response = menu.addAction("Next Response")
        if hasattr(parent, "navigate_chat_response"):
            prev_response.triggered.connect(lambda: parent.navigate_chat_response(-1))
            next_response.triggered.connect(lambda: parent.navigate_chat_response(1))
        else:
            prev_response.setEnabled(False)
            next_response.setEnabled(False)

        menu.addSeparator()
        select_all = menu.addAction("Select All")
        select_all.triggered.connect(self.selectAll)

        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        cursor = self.textCursor()
        if event.key() in (
            Qt.Key_Left,
            Qt.Key_Right,
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
            Qt.Key_Home,
            Qt.Key_End,
            Qt.Key_Escape,
            Qt.Key_Tab,
            Qt.Key_Backtab,
        ):
            super().keyPressEvent(event)
            return
        if event.modifiers() & Qt.ControlModifier:
            super().keyPressEvent(event)
            return

        block = cursor.block()
        block_fmt = block.blockFormat()
        block_bg = block_fmt.background().color().name().lower()

        block_font = block.charFormat().font()
        block_family = block_font.family().lower()

        fmt = cursor.charFormat()
        font = fmt.font()
        family = font.family().lower()

        # Robustly determine if we are in a monospace code snippet block
        is_monospace = (
            any(f in family for f in ("consolas", "monaco", "courier", "monospace"))
            or any(
                f in block_family
                for f in ("consolas", "monaco", "courier", "monospace")
            )
            or font.fixedPitch()
            or block_font.fixedPitch()
            or block_bg in ("#161b22", "#0d1117", "#0f141c")
            or fmt.background().color().name().lower()
            in ("#161b22", "#0d1117", "#0f141c")
        )

        if is_monospace:
            super().keyPressEvent(event)
        else:
            event.ignore()


class CredentialsPromptDialog(QDialog):
    def __init__(self, parent, model_name, provider_id):
        super().__init__(parent)
        self.setWindowTitle("Authentication Required")
        self.resize(450, 220)
        self.model_name = model_name
        self.provider_id = provider_id
        self.success = False
        self.api_key = ""
        self.user_email = ""

        self.setStyleSheet("""
            QDialog {
                background-color: #0b0f14;
                color: #d7dde5;
            }
            QLabel {
                color: #d7dde5;
            }
            QLineEdit {
                background-color: #0f141c;
                border: 1px solid #1f6f45;
                border-radius: 4px;
                color: #d7dde5;
                padding: 6px;
            }
            QPushButton {
                background-color: #1f6f45;
                border: 1px solid #2e7d32;
                border-radius: 4px;
                color: #ffffff;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #2e7d32;
            }
            QPushButton#cancel {
                background-color: #3e2723;
                border: 1px solid #5d4037;
            }
            QPushButton#cancel:hover {
                background-color: #4e342e;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(f"Authenticate for {model_name}")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #a5d6a7;")
        layout.addWidget(title)

        desc = QLabel(
            f"This model runs via {provider_id.upper()}. Please enter your API Key below."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("API Key:"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)

        stored_key = parent.settings.get(f"{provider_id}_api_key", "")
        if not stored_key and provider_id == "gemini":
            stored_key = parent.settings.get("google_api_key", "")
        self.key_edit.setText(stored_key)
        key_layout.addWidget(self.key_edit, 1)
        layout.addLayout(key_layout)

        self.google_btn = None
        if provider_id in {"gemini", "google"}:
            self.google_btn = QPushButton("Open Google AI Studio Keys")
            self.google_btn.clicked.connect(self.open_google_key_page)
            self.google_btn.setStyleSheet(
                "background-color: #0f141c; border: 1px solid #1f6f45; color: #a5d6a7;"
            )
            layout.addWidget(self.google_btn)

            self.status_lbl = QLabel(
                "Gemini uses API keys in Tech Connector. Create/copy a key, then paste it above."
            )
            self.status_lbl.setStyleSheet("color: #a5d6a7; font-size: 11px;")
            layout.addWidget(self.status_lbl)

        layout.addStretch(1)

        actions = QHBoxLayout()
        actions.addStretch(1)

        save_btn = QPushButton("Save & Connect")
        save_btn.clicked.connect(self.on_save)
        actions.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)

        layout.addLayout(actions)

    def open_google_key_page(self):
        QDesktopServices.openUrl(QUrl("https://aistudio.google.com/app/apikey"))

    def on_save(self):
        self.api_key = self.key_edit.text().strip()
        if not self.api_key:
            QMessageBox.information(
                self,
                "Key Required",
                "Please enter an API key. Use the Google AI Studio button to create one.",
            )
            return
        self.success = True
        self.accept()


class WorkflowOutputSelectorDialog(QDialog):
    """Pick a workflow output reference, including safe nested dict/list selectors."""

    def __init__(self, output_refs, current_ref="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick Output Data")
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Select output data")
        title.setStyleSheet("font-weight: bold; color: #a5d6a7;")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Output", "Reference"])
        self.tree.setStyleSheet(
            "QTreeWidget { background-color: #0b0f14; color: #d7dde5; border: 1px solid #1f6f45; }"
            "QHeaderView::section { background-color: #0f141c; color: #a5d6a7; border: 1px solid #1f6f45; }"
        )
        self.tree.itemSelectionChanged.connect(self._use_current_tree_item)
        layout.addWidget(self.tree, 1)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Reference:"))
        self.ref_edit = QLineEdit()
        self.ref_edit.setPlaceholderText("$step1.result['key'][0]['nested']")
        self.ref_edit.setText(current_ref or "")
        self.ref_edit.setStyleSheet(
            "QLineEdit { background: #0b0f14; border: 1px solid #1f6f45; color: #d7dde5; }"
        )
        edit_row.addWidget(self.ref_edit, 1)
        layout.addLayout(edit_row)

        hint = QLabel(
            "Use bracket selectors for nested dict/list/tuple data, for example ['body'][0]['joint']."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        use_btn = QPushButton("Use Selection")
        use_btn.setStyleSheet(
            "QPushButton { background-color: #1a231a; border: 1px solid #1f6f45; color: #a5d6a7; font-weight: bold; }"
        )
        use_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(use_btn)
        layout.addLayout(buttons)

        self._populate(output_refs)

    def _populate(self, output_refs):
        for output in output_refs:
            ref = output.get("ref", "")
            label = output.get("label") or ref
            annotation = output.get("annotation", "")
            root = QTreeWidgetItem([label, ref])
            root.setData(0, Qt.UserRole, ref)
            self.tree.addTopLevelItem(root)

            anno = (annotation or "").lower()
            if any(token in anno for token in ("dict", "mapping")):
                self._add_selector_item(root, "dict key", f"{ref}['key']")
                self._add_selector_item(
                    root, "nested dict key", f"{ref}['key']['nested']"
                )
            if any(
                token in anno
                for token in ("tuple", "list", "sequence", "iterable", "set", "[]")
            ):
                for idx in range(6):
                    self._add_selector_item(root, f"index {idx}", f"{ref}[{idx}]")

            if not root.childCount():
                self._add_selector_item(root, "index 0", f"{ref}[0]")
                self._add_selector_item(root, "dict key", f"{ref}['key']")
            root.setExpanded(True)

        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(1)

    def _add_selector_item(self, parent, label, ref):
        item = QTreeWidgetItem([label, ref])
        item.setData(0, Qt.UserRole, ref)
        parent.addChild(item)
        return item

    def _use_current_tree_item(self):
        item = self.tree.currentItem()
        if not item:
            return
        ref = item.data(0, Qt.UserRole) or ""
        if ref:
            self.ref_edit.setText(ref)

    def selected_ref(self):
        return self.ref_edit.text().strip()
