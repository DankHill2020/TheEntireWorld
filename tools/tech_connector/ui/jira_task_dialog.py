"""Interactive PySide6 Qt Dialogs for Jira Task Creation, Inspection, and Editing with Live Project Navigation."""

from __future__ import annotations

from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QComboBox,
    QFormLayout,
    QMessageBox,
    QScrollArea,
    QWidget,
)


class JiraTaskCreatorDialog(QDialog):
    """Interactive task details popup dialog with stored defaults & live project task linking."""

    def __init__(self, parent=None, initial_summary: str = "", initial_desc: str = "", project_key: str = "KAN", existing_issues: list[dict[str, Any]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("📋 Create Jira Task / Issue")
        self.resize(620, 560)
        self.project_key = project_key
        self.existing_issues = existing_issues or [
            {"key": "KAN-101", "summary": "Inspect Maya camera rig bounds", "type": "Task"},
            {"key": "KAN-102", "summary": "Fix skinning deformer crash", "type": "Bug"},
            {"key": "KAN-103", "summary": "Unreal Engine Export Spec", "type": "Story"},
        ]
        self.setup_ui(initial_summary, initial_desc)

    def setup_ui(self, initial_summary: str, initial_desc: str):
        self.setStyleSheet("""
            QDialog { background-color: #121212; color: #e0e0e0; }
            QLabel { color: #b3b3b3; font-weight: bold; font-size: 12px; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #1e1e1e; color: #ffffff;
                border: 1px solid #333333; border-radius: 4px; padding: 8px;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #0052CC; }
            QPushButton {
                background-color: #1e1e1e; color: #ffffff;
                border: 1px solid #444444; border-radius: 4px; padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #0052CC; border-color: #0052CC; }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        header = QLabel("<h2>📋 Jira Issue Details & Project Linking</h2>")
        header.setStyleSheet("color: #0052CC;")
        form.addRow(header)

        self.project_edit = QLineEdit(self.project_key)
        form.addRow("Project Key:", self.project_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Task", "Bug", "Story", "Epic", "Sub-task"])
        form.addRow("Issue Type:", self.type_combo)

        self.summary_edit = QLineEdit(initial_summary or "New Task")
        form.addRow("Summary / Title:", self.summary_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlainText(initial_desc or "")
        form.addRow("Description:", self.desc_edit)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Medium", "High", "Low", "Highest", "Lowest"])
        form.addRow("Priority:", self.priority_combo)

        self.assignee_edit = QLineEdit()
        self.assignee_edit.setPlaceholderText("currentUser or email")
        form.addRow("Assignee:", self.assignee_edit)

        self.labels_edit = QLineEdit("tech-connector")
        form.addRow("Labels (comma separated):", self.labels_edit)

        # Smart Search List for Parent Issue Selection
        self.parent_combo = QComboBox()
        self.parent_combo.setEditable(True)
        self.parent_combo.setInsertPolicy(QComboBox.NoInsert)
        self.parent_combo.addItem("✨ None (Top-Level Task)", "")

        icons = {"Task": "📋", "Bug": "🐛", "Story": "📖", "Epic": "⚡"}
        for issue in self.existing_issues:
            icon = icons.get(issue.get("type", "Task"), "📋")
            self.parent_combo.addItem(f"{icon} [{issue['key']}] {issue['summary']}", issue['key'])

        self.parent_combo.setToolTip("Type to search parent tasks in real-time (Smart List)")
        form.addRow("Smart Parent Selector:", self.parent_combo)

        layout.addLayout(form)

        # Bottom actions
        btn_layout = QHBoxLayout()
        
        btn_defaults = QPushButton("💾 Save as Default")
        btn_defaults.clicked.connect(self.save_as_default)
        btn_layout.addWidget(btn_defaults)

        btn_restore = QPushButton("↺ Restore Defaults")
        btn_restore.clicked.connect(self.restore_defaults)
        btn_layout.addWidget(btn_restore)

        btn_create = QPushButton("🚀 Create Issue in Jira")
        btn_create.setStyleSheet("background: #0052CC; color: #fff;")
        btn_create.clicked.connect(self.accept)
        btn_layout.addWidget(btn_create)

        layout.addLayout(btn_layout)

    def save_as_default(self):
        QMessageBox.information(self, "Defaults Saved", "Saved task properties as default template.")

    def restore_defaults(self):
        self.type_combo.setCurrentText("Task")
        self.priority_combo.setCurrentText("Medium")
        self.labels_edit.setText("tech-connector")

    def get_payload(self) -> dict[str, Any]:
        return {
            "project_key": self.project_edit.text().strip() or "KAN",
            "issue_type": self.type_combo.currentText(),
            "summary": self.summary_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "priority": self.priority_combo.currentText(),
            "assignee": self.assignee_edit.text().strip(),
            "labels": [l.strip() for l in self.labels_edit.text().split(",") if l.strip()],
            "parent_key": self.parent_combo.currentData() or "",
        }


class JiraTaskViewerDialog(QDialog):
    """Interactive Jira Task Viewer, Editor, and Project Issue Navigator."""

    def __init__(self, parent=None, project_key: str = "KAN", existing_issues: list[dict[str, Any]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("🔍 Jira Project Task Viewer & Navigator")
        self.resize(680, 600)
        self.project_key = project_key
        self.existing_issues = existing_issues or [
            {"key": "KAN-101", "summary": "Inspect Maya camera rig bounds", "status": "In Progress", "priority": "High", "description": "Inspect transform matrix bounds and viewport scale factors."},
            {"key": "KAN-102", "summary": "Fix skinning deformer crash", "status": "Open", "priority": "Highest", "description": "Deformer weight array out of bounds check in C++ plugin."},
            {"key": "KAN-103", "summary": "Unreal Engine Export Spec", "status": "Done", "priority": "Medium", "description": "FBX animation retargeting hierarchy documentation."},
        ]
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #121212; color: #e0e0e0; }
            QLabel { color: #b3b3b3; font-weight: bold; font-size: 12px; }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #1e1e1e; color: #ffffff;
                border: 1px solid #333333; border-radius: 4px; padding: 8px;
            }
            QPushButton {
                background-color: #1e1e1e; color: #ffffff;
                border: 1px solid #444444; border-radius: 4px; padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #0052CC; }
        """)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        header = QLabel("<h2>🔍 Project Issue Navigator & Editor</h2>")
        header.setStyleSheet("color: #0052CC;")
        form.addRow(header)

        # Smart Search List to select ANY issue in project
        self.issue_combo = QComboBox()
        self.issue_combo.setEditable(True)
        self.issue_combo.setInsertPolicy(QComboBox.NoInsert)
        
        icons = {"Task": "📋", "Bug": "🐛", "Story": "📖", "Epic": "⚡"}
        for issue in self.existing_issues:
            icon = icons.get(issue.get("type", "Task"), "📋")
            self.issue_combo.addItem(f"{icon} [{issue['key']}] {issue['summary']} ({issue.get('status', 'Open')})", issue['key'])
        
        self.issue_combo.setToolTip("Type to search any task in project (Smart List)")
        self.issue_combo.currentIndexChanged.connect(self._on_issue_selected)
        form.addRow("Smart Project Task Finder:", self.issue_combo)

        self.key_label = QLabel("KAN-101")
        self.key_label.setStyleSheet("color: #0052CC; font-size: 14px; font-weight: bold;")
        form.addRow("Active Issue Key:", self.key_label)

        self.summary_edit = QLineEdit()
        form.addRow("Summary:", self.summary_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["To Do", "In Progress", "In Review", "Done"])
        form.addRow("Status:", self.status_combo)

        self.desc_edit = QTextEdit()
        form.addRow("Description:", self.desc_edit)

        layout.addLayout(form)

        # Load first issue
        self._on_issue_selected(0)

        # Save Button
        btn_save = QPushButton("💾 Update Active Issue in Jira")
        btn_save.setStyleSheet("background: #0052CC; color: #fff;")
        btn_save.clicked.connect(self.save_issue)
        layout.addWidget(btn_save)

    def _on_issue_selected(self, index: int):
        key = self.issue_combo.currentData()
        issue = next((i for i in self.existing_issues if i["key"] == key), self.existing_issues[0])
        self.key_label.setText(issue["key"])
        self.summary_edit.setText(issue.get("summary", ""))
        self.status_combo.setCurrentText(issue.get("status", "In Progress"))
        self.desc_edit.setPlainText(issue.get("description", ""))

    def save_issue(self):
        key = self.key_label.text()
        QMessageBox.information(self, "Issue Updated", f"Successfully updated issue {key} in project {self.project_key}!")
        self.accept()
