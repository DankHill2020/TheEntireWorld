from __future__ import annotations

"""Typed drag-detachable tab containers for Tech Connector workspaces."""

import uuid
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QMimeData, QTimer, Signal
from PySide6.QtGui import QCursor, QDrag
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QTabBar,
    QTabWidget,
    QWidget,
)

TAB_MIME = "application/x-ai-studio-detachable-tab"
_CONTAINERS: dict[str, "DetachableTabWidget"] = {}


@dataclass
class _TabRecord:
    title: str
    widget: QWidget
    original_index: int
    visible: bool = True
    detached: bool = False
    window: "_DetachedTabWindow | None" = None


class _DragTabBar(QTabBar):
    detachRequested = Signal(int, QPoint)
    LONG_PRESS_DETACH_MS = 325

    def __init__(self, owner: "DetachableTabWidget"):
        super().__init__(owner)
        self.owner = owner
        self._press_pos: QPoint | None = None
        self._press_index = -1
        self._long_press_ready = False
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._press_index = self.tabAt(event.pos())
            self._long_press_ready = False
            press_index = self._press_index
            QTimer.singleShot(self.LONG_PRESS_DETACH_MS, lambda: self._arm_long_press_detach(press_index))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        self._press_index = -1
        self._long_press_ready = False
        super().mouseReleaseEvent(event)

    def _arm_long_press_detach(self, press_index: int) -> None:
        if self._press_pos is not None and self._press_index == press_index and press_index >= 0:
            self._long_press_ready = True

    def mouseMoveEvent(self, event):
        if (
            self._press_pos is not None
            and self._press_index >= 0
            and event.buttons() & Qt.LeftButton
        ):
            current_index = self.tabAt(self._press_pos)
            if current_index < 0:
                return
            global_pos = self.mapToGlobal(event.pos())
            if self._long_press_ready and self.owner.detach_index_if_dragged_outside(current_index, global_pos):
                self._press_pos = None
                self._press_index = -1
                self._long_press_ready = False
                return
            if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
                super().mouseMoveEvent(event)
                return
            current_index = self.tabAt(self._press_pos)
            if current_index < 0:
                return
            payload = self.owner.drag_payload_for_index(current_index)
            if not payload:
                return
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(TAB_MIME, payload.encode("utf-8"))
            drag.setMimeData(mime)
            result = drag.exec(Qt.MoveAction)
            if result == Qt.IgnoreAction:
                self.owner.detach_index_if_dragged_outside(current_index, QCursor.pos())
            return
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if self.owner.can_accept_mime(event.mimeData()):
            event.acceptProposedAction()
            self.owner.setProperty("validTabDrop", True)
            self.owner.style().unpolish(self.owner)
            self.owner.style().polish(self.owner)
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if self.owner.can_accept_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.owner.setProperty("validTabDrop", False)
        self.owner.style().unpolish(self.owner)
        self.owner.style().polish(self.owner)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.owner.setProperty("validTabDrop", False)
        self.owner.style().unpolish(self.owner)
        self.owner.style().polish(self.owner)
        if not self.owner.can_accept_mime(event.mimeData()):
            event.ignore()
            return
        drop_index = self.tabAt(event.pos())
        self.owner.accept_tab_drop(bytes(event.mimeData().data(TAB_MIME)).decode("utf-8"), drop_index)
        event.acceptProposedAction()


class _DetachedTabWindow(QMainWindow):
    def __init__(self, root: "DetachableTabWidget", tab_type: str, pos: QPoint | None = None):
        super().__init__(root.window())
        self._root = root
        self._closing_empty = False
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(root.detached_window_title)
        self.resize(1100, 760)
        if pos is not None:
            self.move(pos)
        try:
            source_window = root.window()
            if source_window and source_window.styleSheet():
                self.setStyleSheet(source_window.styleSheet())
        except Exception:
            pass

        self.tabs = DetachableTabWidget(
            self,
            tab_type=tab_type,
            root_container=root,
            detached_window=self,
        )
        self.tabs.setTabsClosable(root.tabsClosable())
        panel = root.create_detached_panel(self.tabs)
        if panel is not None:
            shell = QWidget(self)
            layout = QHBoxLayout(shell)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            layout.addWidget(panel)
            layout.addWidget(self.tabs, 1)
            self.setCentralWidget(shell)
        else:
            self.setCentralWidget(self.tabs)

    def close_if_empty(self) -> None:
        if self.tabs.count() > 0:
            return
        self._closing_empty = True
        self.close()

    def closeEvent(self, event):
        if self._closing_empty:
            self._root.unregister_detached_window(self)
            event.accept()
            return
        for _ in range(self.tabs.count()):
            self._root.move_tab_from_container(self.tabs, 0)
        self._root.unregister_detached_window(self)
        event.accept()


class DetachableTabWidget(QTabWidget):
    tabVisibilityChanged = Signal(str, bool)
    tabDetachedChanged = Signal(str, bool)
    tabActivated = Signal(str, object, object)
    containerEmptied = Signal(object)

    def __init__(
        self,
        parent=None,
        *,
        tab_type: str = "feature",
        root_container: "DetachableTabWidget | None" = None,
        detached_window: _DetachedTabWindow | None = None,
    ):
        super().__init__(parent)
        self.tab_type = tab_type
        self.container_id = str(uuid.uuid4())
        self.root_container = root_container or self
        self.detached_window = detached_window
        self.detached_window_title = {
            "feature": "Tech Connector Feature Tabs",
            "editor_file": "Tech Connector Editor",
            "pipeline": "Tech Connector Pipeline Tabs",
        }.get(tab_type, "Tech Connector Tabs")
        self._records: dict[str, _TabRecord] = {} if self.is_root_container else self.root_container._records
        self._order: list[str] = [] if self.is_root_container else self.root_container._order
        self._detached_windows: list[_DetachedTabWindow] = [] if self.is_root_container else self.root_container._detached_windows
        self._detached_panel_factory: Callable[["DetachableTabWidget"], QWidget | None] | None = None
        self._tab_close_handler: Callable[["DetachableTabWidget", int], None] | None = None

        self.setTabsClosable(False)
        self.setMovable(True)
        self.setAcceptDrops(True)
        self.setDocumentMode(True)
        bar = _DragTabBar(self)
        bar.detachRequested.connect(self.detach_tab_at_global_pos)
        self.setTabBar(bar)
        self.currentChanged.connect(self._emit_current_activated)
        self.tabCloseRequested.connect(self._handle_tab_close_requested)
        if not self.is_root_container:
            self.tabActivated.connect(self.root_container.tabActivated)
        _CONTAINERS[self.container_id] = self

    @property
    def is_root_container(self) -> bool:
        return self.root_container is self

    def set_detached_panel_factory(self, factory: Callable[["DetachableTabWidget"], QWidget | None] | None) -> None:
        self._detached_panel_factory = factory

    def set_tab_close_handler(self, handler: Callable[["DetachableTabWidget", int], None] | None) -> None:
        self.root_container._tab_close_handler = handler

    def create_detached_panel(self, container: "DetachableTabWidget") -> QWidget | None:
        factory = self._detached_panel_factory
        if callable(factory):
            return factory(container)
        return None

    def addTab(self, widget: QWidget, title: str):
        index = super().addTab(widget, title)
        tab_id = self._tab_id_for_widget(widget, title)
        self.setTabToolTip(index, self.tabToolTip(index) or title)
        if self.is_root_container and title not in self._records:
            self._records[title] = _TabRecord(title, widget, index, True, False)
        if self.is_root_container and title not in self._order:
            self._order.append(title)
        self.tabBar().setTabData(index, tab_id)
        return index

    def insertTab(self, index: int, widget: QWidget, title: str):
        result = super().insertTab(index, widget, title)
        self.tabBar().setTabData(result, self._tab_id_for_widget(widget, title))
        return result

    def _tab_id_for_widget(self, widget: QWidget, title: str) -> str:
        explicit = widget.property("ai_studio_tab_id")
        if explicit:
            return str(explicit)
        tab_id = f"{self.tab_type}:{title}:{id(widget)}"
        widget.setProperty("ai_studio_tab_id", tab_id)
        widget.setProperty("ai_studio_tab_type", self.tab_type)
        return tab_id

    def _container_for_id(self, container_id: str) -> "DetachableTabWidget | None":
        return _CONTAINERS.get(container_id)

    def drag_payload_for_index(self, index: int) -> str:
        if index < 0 or index >= self.count():
            return ""
        tab_id = self.tabBar().tabData(index) or self._tab_id_for_widget(self.widget(index), self.tabText(index))
        return "|".join([self.container_id, self.tab_type, str(tab_id)])

    def can_accept_mime(self, mime: QMimeData) -> bool:
        if not mime.hasFormat(TAB_MIME):
            return False
        try:
            _source, tab_type, _tab_id = bytes(mime.data(TAB_MIME)).decode("utf-8").split("|", 2)
        except Exception:
            return False
        return tab_type == self.tab_type

    def accept_tab_drop(self, payload: str, drop_index: int = -1) -> bool:
        try:
            source_id, tab_type, tab_id = payload.split("|", 2)
        except ValueError:
            return False
        if tab_type != self.tab_type:
            return False
        source = self._container_for_id(source_id)
        if source is None:
            return False
        source_index = source.index_for_tab_id(tab_id)
        if source_index < 0:
            return False
        if source is self:
            if drop_index >= 0 and drop_index != source_index:
                self.tabBar().moveTab(source_index, drop_index)
            return True
        self.move_tab_from_container(source, source_index, drop_index)
        return True

    def index_for_tab_id(self, tab_id: str) -> int:
        for index in range(self.count()):
            if str(self.tabBar().tabData(index)) == tab_id:
                return index
        return -1

    def move_tab_from_container(
        self,
        source: "DetachableTabWidget",
        source_index: int,
        drop_index: int = -1,
    ) -> None:
        title = source.tabText(source_index)
        widget = source.widget(source_index)
        tooltip = source.tabToolTip(source_index)
        tab_id = source.tabBar().tabData(source_index)
        source.removeTab(source_index)
        if source.count() == 0:
            source.containerEmptied.emit(source)
        insert_at = self.count() if drop_index < 0 else max(0, min(drop_index, self.count()))
        new_index = super().insertTab(insert_at, widget, title)
        self.setTabToolTip(new_index, tooltip)
        self.tabBar().setTabData(new_index, tab_id or self._tab_id_for_widget(widget, title))
        self.setCurrentIndex(new_index)
        self._mark_record_location(title, self.detached_window)
        if source.detached_window is not None:
            source.detached_window.close_if_empty()
        self._emit_current_activated(new_index)

    def _mark_record_location(self, title: str, window: _DetachedTabWindow | None) -> None:
        record = self.root_container._records.get(title)
        if record is None:
            return
        record.detached = window is not None
        record.window = window
        record.visible = True
        self.root_container.tabDetachedChanged.emit(title, record.detached)
        self.root_container.tabVisibilityChanged.emit(title, True)

    def detach_tab_at_global_pos(self, index: int, global_pos: QPoint | None = None) -> None:
        self.detach_tab_by_index(index, global_pos)

    def detach_index_if_dragged_outside(self, index: int, global_pos: QPoint) -> bool:
        if index < 0 or index >= self.count():
            return False
        source_rect = self.rect()
        source_rect.moveTopLeft(self.mapToGlobal(source_rect.topLeft()))
        if source_rect.adjusted(-24, -24, 24, 24).contains(global_pos):
            return False
        self.detach_tab_by_index(index, global_pos)
        return True

    def detach_current_tab(self):
        idx = self.currentIndex()
        if idx >= 0:
            self.detach_tab_by_index(idx)

    def detach_tab(self, title: str):
        idx = self._visible_index_for_title(title)
        if idx >= 0:
            self.detach_tab_by_index(idx)

    def detach_tab_by_index(self, index: int, global_pos: QPoint | None = None):
        if index < 0 or index >= self.count():
            return
        root = self.root_container
        window = _DetachedTabWindow(root, self.tab_type, global_pos)
        root._detached_windows.append(window)
        window.show()
        window.raise_()
        window.tabs.move_tab_from_container(self, index)

    def workspace_tab_titles(self) -> list[str]:
        return list(self._order) if self._order else [self.tabText(i) for i in range(self.count())]

    def _visible_index_for_title(self, title: str) -> int:
        for i in range(self.count()):
            if self.tabText(i) == title:
                return i
        return -1

    def is_tab_visible(self, title: str) -> bool:
        record = self._records.get(title)
        return bool(record and record.visible and (not record.detached or record.window and record.window.isVisible()))

    def set_tab_visible(self, title: str, visible: bool):
        record = self._records.get(title)
        if not record:
            return
        if record.detached:
            record.visible = bool(visible)
            if record.window:
                record.window.setVisible(bool(visible))
            self.tabVisibilityChanged.emit(title, bool(visible))
            return
        idx = self._visible_index_for_title(title)
        if visible and idx < 0:
            self.insertTab(min(record.original_index, self.count()), record.widget, title)
            record.visible = True
            self.tabVisibilityChanged.emit(title, True)
        elif not visible and idx >= 0:
            super().removeTab(idx)
            record.visible = False
            self.tabVisibilityChanged.emit(title, False)

    def show_all_tabs(self):
        for title in self.workspace_tab_titles():
            self.set_tab_visible(title, True)

    def reattach_tab(self, title: str):
        record = self._records.get(title)
        if not record or not record.detached or record.window is None:
            return
        source = record.window.tabs
        idx = source._visible_index_for_title(title)
        if idx >= 0:
            self.move_tab_from_container(source, idx, min(record.original_index, self.count()))

    def reattach_all_tabs(self):
        for title in list(self.workspace_tab_titles()):
            self.reattach_tab(title)

    def unregister_detached_window(self, window: _DetachedTabWindow) -> None:
        if window in self._detached_windows:
            self._detached_windows.remove(window)

    def close_detached_windows(self) -> None:
        for window in list(self._detached_windows):
            window._closing_empty = True
            window.close()
        self._detached_windows.clear()

    def _emit_current_activated(self, index: int) -> None:
        if index < 0 or index >= self.count():
            return
        self.tabActivated.emit(self.tabText(index), self.widget(index), self)

    def _handle_tab_close_requested(self, index: int) -> None:
        handler = self.root_container._tab_close_handler
        if callable(handler):
            handler(self, index)

    def closeEvent(self, event):
        if self.is_root_container:
            self.close_detached_windows()
        _CONTAINERS.pop(self.container_id, None)
        super().closeEvent(event)
