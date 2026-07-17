from __future__ import annotations

"""Main-window navigation UX helpers.

Adds:
- one main-window fullscreen controller
- draggable detachable tabs
- detached-window fullscreen behavior
- Ctrl+F find-in-current-file navigation
- Win+B project-use search popup

This module is designed to be wired from MainWindow without disturbing the
existing tab implementations.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import QPoint, Qt, QEvent, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabBar,
    QTabWidget,
    QTextEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class DetachedTabWindow(QDialog):
    """Host for a detached tab.

    Its Full Screen button affects only this detached window, not the main app.
    """

    reattachRequested = Signal(QWidget, str)

    def __init__(self, widget: QWidget, title: str, parent=None):
        super().__init__(parent)
        self._content_widget = widget
        self._title = title
        self.setWindowTitle(title)
        self.resize(1000, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        toolbar.addWidget(title_label, 1)

        self.fullscreen_btn = QPushButton("Full Screen")
        self.fullscreen_btn.clicked.connect(self.toggle_detached_fullscreen)
        toolbar.addWidget(self.fullscreen_btn)

        self.reattach_btn = QPushButton("Reattach")
        self.reattach_btn.clicked.connect(self.request_reattach)
        toolbar.addWidget(self.reattach_btn)

        layout.addLayout(toolbar)
        layout.addWidget(widget, 1)

    def toggle_detached_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_btn.setText("Full Screen")
        else:
            self.showFullScreen()
            self.fullscreen_btn.setText("Exit Full Screen")

    def request_reattach(self):
        self.reattachRequested.emit(self._content_widget, self._title)
        self.close()

    def closeEvent(self, event):
        # Do not destroy the content. Reattach on close.
        if self._content_widget.parent() is self:
            self.reattachRequested.emit(self._content_widget, self._title)
        super().closeEvent(event)


class DraggableDetachTabBar(QTabBar):
    detachRequested = Signal(int, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self._press_index = -1
        self.setMovable(True)
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._press_index = self.tabAt(event.pos())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is not None and self._press_index >= 0:
            distance = (event.pos() - self._press_pos).manhattanLength()
            outside = not self.rect().adjusted(-20, -20, 20, 20).contains(event.pos())
            if distance > 28 and outside:
                index = self._press_index
                self._press_pos = None
                self._press_index = -1
                self.detachRequested.emit(index, event.globalPosition().toPoint())
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        self._press_index = -1
        super().mouseReleaseEvent(event)


class DetachableTabWidget(QTabWidget):
    """QTabWidget with drag-to-detach and reattach support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        bar = DraggableDetachTabBar(self)
        self.setTabBar(bar)
        bar.detachRequested.connect(self.detach_tab)
        self._detached_windows: list[DetachedTabWindow] = []

    def detach_tab(self, index: int, global_pos: QPoint | None = None):
        if index < 0 or index >= self.count():
            return
        widget = self.widget(index)
        title = self.tabText(index)
        icon = self.tabIcon(index)
        self.removeTab(index)

        window = DetachedTabWindow(widget, title, self.window())
        window.reattachRequested.connect(lambda w, t, ic=icon: self.reattach_tab(w, t, ic))
        self._detached_windows.append(window)
        if global_pos:
            window.move(global_pos)
        window.show()

    def reattach_tab(self, widget: QWidget, title: str, icon=None):
        if widget is None:
            return
        if widget.parent() is not self:
            widget.setParent(self)
        index = self.addTab(widget, title)
        if icon is not None:
            try:
                self.setTabIcon(index, icon)
            except Exception:
                pass
        self.setCurrentIndex(index)


@dataclass
class FindMatch:
    start: int
    end: int


class InFileFindController:
    """Ctrl+F find for current editor, with up/down cycling."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.matches: list[FindMatch] = []
        self.index = -1
        self.query = ""

    def current_text_editor(self):
        mw = self.main_window
        # Prefer known editor widgets, then search focused/current widgets.
        candidates = [
            getattr(mw, "editor_text", None),
            getattr(mw, "code_editor", None),
            getattr(mw, "current_editor", None),
            getattr(mw, "file_editor", None),
        ]
        focus = mw.focusWidget() if hasattr(mw, "focusWidget") else None
        if focus:
            candidates.insert(0, focus)
        for widget in candidates:
            if isinstance(widget, (QPlainTextEdit, QTextEdit)):
                return widget
        for widget in mw.findChildren((QPlainTextEdit, QTextEdit)):
            if widget.isVisible():
                return widget
        return None

    def show_find_bar(self):
        mw = self.main_window
        if not hasattr(mw, "global_find_bar"):
            mw.global_find_bar = QWidget(mw)
            layout = QHBoxLayout(mw.global_find_bar)
            layout.setContentsMargins(4, 2, 4, 2)
            layout.addWidget(QLabel("Find in file:"))
            mw.global_find_input = QLineEdit()
            mw.global_find_input.setPlaceholderText("Search current file...")
            layout.addWidget(mw.global_find_input, 1)
            prev_btn = QPushButton("↑")
            next_btn = QPushButton("↓")
            close_btn = QPushButton("×")
            layout.addWidget(prev_btn)
            layout.addWidget(next_btn)
            layout.addWidget(close_btn)

            mw.global_find_input.textChanged.connect(self.update_query)
            mw.global_find_input.returnPressed.connect(self.next_match)
            prev_btn.clicked.connect(self.prev_match)
            next_btn.clicked.connect(self.next_match)
            close_btn.clicked.connect(lambda: mw.global_find_bar.hide())

            # Add to the top of the central layout if possible.
            central = mw.centralWidget()
            if central and central.layout():
                central.layout().insertWidget(0, mw.global_find_bar)
        mw.global_find_bar.show()
        mw.global_find_input.setFocus()
        mw.global_find_input.selectAll()
        self.update_query(mw.global_find_input.text())

    def update_query(self, query: str):
        self.query = query or ""
        self.matches.clear()
        self.index = -1
        editor = self.current_text_editor()
        if not editor or not self.query:
            return
        text = editor.toPlainText()
        flags = re.IGNORECASE
        for m in re.finditer(re.escape(self.query), text, flags):
            self.matches.append(FindMatch(m.start(), m.end()))
        if self.matches:
            self.index = 0
            self._select_current()

    def _select_current(self):
        editor = self.current_text_editor()
        if not editor or not self.matches or self.index < 0:
            return
        match = self.matches[self.index % len(self.matches)]
        cursor = editor.textCursor()
        cursor.setPosition(match.start)
        cursor.setPosition(match.end, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()

    def next_match(self):
        if not self.matches:
            self.update_query(self.query)
        if not self.matches:
            return
        self.index = (self.index + 1) % len(self.matches)
        self._select_current()

    def prev_match(self):
        if not self.matches:
            self.update_query(self.query)
        if not self.matches:
            return
        self.index = (self.index - 1) % len(self.matches)
        self._select_current()


class ProjectUsesPopup(QDialog):
    """Win+B project-use finder popup."""

    def __init__(self, main_window, query: str = ""):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Find uses in project")
        self.resize(760, 420)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Find uses:"))
        self.input = QLineEdit()
        self.input.setText(query)
        self.input.setPlaceholderText("symbol / function / class / call name")
        row.addWidget(self.input, 1)
        self.search_btn = QPushButton("Search")
        row.addWidget(self.search_btn)
        layout.addLayout(row)

        self.results = QListWidget()
        layout.addWidget(self.results, 1)

        self.search_btn.clicked.connect(self.search)
        self.input.returnPressed.connect(self.search)
        self.results.itemActivated.connect(self.open_result)

        if query:
            self.search()

    def _project_roots(self):
        mw = self.main_window
        for name in ("project_roots", "get_project_roots"):
            fn = getattr(mw, name, None)
            if callable(fn):
                try:
                    roots = fn()
                    if roots:
                        return [Path(r) for r in roots]
                except Exception:
                    pass
        root = getattr(mw, "project_root", None) or getattr(mw, "current_project_root", None)
        if root:
            return [Path(root)]
        return [Path.cwd()]

    def search(self):
        query = self.input.text().strip()
        self.results.clear()
        if not query:
            return

        allowed = {".py", ".cpp", ".h", ".hpp", ".cs", ".uasset", ".json", ".yaml", ".yml", ".txt", ".md"}
        max_results = 250
        found = 0

        for root in self._project_roots():
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if found >= max_results:
                    break
                if not path.is_file() or path.suffix.lower() not in allowed:
                    continue
                if any(part in {".git", "__pycache__", "Intermediate", "Saved", "DerivedDataCache"} for part in path.parts):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                for line_no, line in enumerate(text.splitlines(), start=1):
                    if query.lower() in line.lower():
                        item = QListWidgetItem(f"{path}:{line_no}: {line.strip()[:160]}")
                        item.setData(Qt.UserRole, {"path": str(path), "line": line_no, "query": query})
                        self.results.addItem(item)
                        found += 1
                        if found >= max_results:
                            break

    def open_result(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole) or {}
        path = data.get("path")
        line = int(data.get("line") or 1)
        mw = self.main_window

        opened = False
        for name in ("open_file_at_line", "open_file_in_editor", "open_file"):
            fn = getattr(mw, name, None)
            if callable(fn):
                try:
                    try:
                        fn(path, line)
                    except TypeError:
                        fn(path)
                    opened = True
                    break
                except Exception:
                    pass

        if not opened:
            try:
                mw.append(f"\n[Project Uses]\n{path}:{line}\n")
            except Exception:
                pass
        self.accept()


def install_main_window_navigation_tools(main_window):
    """Install all navigation helpers on a MainWindow instance."""
    # One global fullscreen shortcut/action. Keep per-tab fullscreen buttons hidden when possible.
    if not hasattr(main_window, "toggle_main_window_fullscreen"):
        def toggle_main_window_fullscreen():
            if main_window.isFullScreen():
                main_window.showNormal()
            else:
                main_window.showFullScreen()
        main_window.toggle_main_window_fullscreen = toggle_main_window_fullscreen

    main_window._in_file_find_controller = InFileFindController(main_window)

    QShortcut(QKeySequence("Ctrl+F"), main_window, activated=main_window._in_file_find_controller.show_find_bar)
    QShortcut(QKeySequence("F3"), main_window, activated=main_window._in_file_find_controller.next_match)
    QShortcut(QKeySequence("Shift+F3"), main_window, activated=main_window._in_file_find_controller.prev_match)

    # Qt usually exposes Meta as the Windows key.
    try:
        QShortcut(QKeySequence("Meta+B"), main_window, activated=lambda: ProjectUsesPopup(main_window).exec())
    except Exception:
        pass

    # Convert main tabs to detachable where possible.
    for tab_widget in main_window.findChildren(QTabWidget):
        if isinstance(tab_widget, DetachableTabWidget):
            continue
        try:
            old_bar = tab_widget.tabBar()
            new_bar = DraggableDetachTabBar(tab_widget)
            tab_widget.setTabBar(new_bar)

            def _detach(index, pos, tabs=tab_widget):
                if index < 0 or index >= tabs.count():
                    return
                widget = tabs.widget(index)
                title = tabs.tabText(index)
                icon = tabs.tabIcon(index)
                tabs.removeTab(index)
                window = DetachedTabWindow(widget, title, main_window)
                window.reattachRequested.connect(lambda w, t, ic=icon, tw=tabs: _reattach(tw, w, t, ic))
                window.move(pos)
                window.show()

            def _reattach(tabs, widget, title, icon):
                widget.setParent(tabs)
                idx = tabs.addTab(widget, title)
                try:
                    tabs.setTabIcon(idx, icon)
                except Exception:
                    pass
                tabs.setCurrentIndex(idx)

            new_bar.detachRequested.connect(_detach)
        except Exception:
            pass

    # Per request: individual tab fullscreen buttons should not exist in normal tabs.
    for btn in main_window.findChildren(QPushButton):
        try:
            if btn.text().strip().lower().replace("⛶", "").strip() == "full screen":
                btn.setVisible(False)
        except Exception:
            pass
