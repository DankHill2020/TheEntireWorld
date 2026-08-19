"""Project panel helpers for Tech Connector."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from tech_connector.ui.icons import configure_button


def add_project_action_buttons(window, layout) -> None:
    """Add project-specific actions to the left project panel.

    Intended placement: directly under the existing Load Project / Update Project row.
    """

    row = QHBoxLayout()

    dirs_btn = QPushButton("Project Dirs")
    configure_button(dirs_btn, "folder", text="Directories", role="secondary")
    dirs_btn.setToolTip("Add/remove project and tool folders used by the knowledge index.")
    dirs_btn.clicked.connect(window.show_first_run)
    row.addWidget(dirs_btn)

    quick_index_btn = QPushButton("Quick Index")
    configure_button(quick_index_btn, "database", text="Quick index", role="secondary")
    quick_index_btn.setToolTip("Build the fast searchable files/symbols index.")
    quick_index_btn.clicked.connect(window.build_index)
    row.addWidget(quick_index_btn)

    graph_btn = QPushButton("Graph")
    configure_button(graph_btn, "graph", text="Graph", role="secondary")
    graph_btn.setToolTip("Rebuild dependency/dead-code graph from the current index.")
    graph_btn.clicked.connect(window.build_dependency_graph_only)
    row.addWidget(graph_btn)

    open_btn = QPushButton("Open Folder")
    configure_button(open_btn, "folder", text="Open folder", role="secondary")
    open_btn.setToolTip("Open the active project folder in the OS file browser.")
    open_btn.clicked.connect(lambda: open_active_project_folder(window))
    row.addWidget(open_btn)

    layout.addLayout(row)


def open_active_project_folder(window) -> None:
    active = ""
    try:
        roots = window.project_roots()
        active = roots[0] if roots else ""
    except Exception:
        active = ""

    if not active:
        active = getattr(window, "current_file_path", "")
        if active:
            active = str(Path(active).parent)

    if active:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(active).resolve())))
