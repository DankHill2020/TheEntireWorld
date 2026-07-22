"""Visible attribution page for reusable open-knowledge sources."""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from tech_connector.services.knowledge_credits_service import list_knowledge_credits


class KnowledgeCreditsDialog(QDialog):
    """Searchable credits page backed by the durable knowledge registry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Knowledge Credits")
        self.resize(980, 620)
        self.setMinimumSize(720, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        title = QLabel("Knowledge Credits")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        policy = QLabel(
            "Creators and organizations whose open information has been promoted into reusable system knowledge. "
            "Project asset licenses and private sources are tracked separately."
        )
        policy.setWordWrap(True)
        layout.addWidget(policy)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search creator, source, domain, or learned technique")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Source", "Creator", "License", "Knowledge Used", "Link"))
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._open_link)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("No open knowledge sources have been promoted yet.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        rows = list_knowledge_credits(query=self.search.text())
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            creator = row.get("creator") or row.get("organization") or "Not specified"
            values = (
                row.get("title") or "Untitled source",
                creator,
                row.get("license") or "Not specified",
                row.get("what_learned") or ", ".join(row.get("domains") or []),
                row.get("url") or "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 4:
                    item.setData(Qt.UserRole, str(row.get("url") or ""))
                    item.setForeground(self.palette().link())
                self.table.setItem(row_index, column, item)
            self.table.resizeRowToContents(row_index)
        self.table.setVisible(bool(rows))
        self.empty_label.setVisible(not rows)

    def _open_link(self, row: int, _column: int) -> None:
        item = self.table.item(row, 4)
        url = str(item.data(Qt.UserRole) or "") if item else ""
        if url:
            webbrowser.open(url)

