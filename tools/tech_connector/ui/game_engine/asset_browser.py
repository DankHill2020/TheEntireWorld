"""Project asset browser with familiar create, import, filter, and inspect flows."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Callable

from PySide6.QtCore import QMimeData, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDrag, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tech_connector.game_engine.assets import (
    AssetDatabase,
    BulkAssetOperationService,
    AssetExportService,
    AssetInUseError,
    AssetProductionService,
    AssetOperationsService,
    AssetTypeRegistry,
    asset_property_schema,
    read_asset_metadata,
    write_asset_metadata,
    builtin_asset_type_registry,
)
from tech_connector.ui.game_engine.asset_thumbnail_service import AssetThumbnailService
from tech_connector.ui.game_engine.bulk_asset_dialog import BulkAssetOperationsDialog
from tech_connector.game_engine.assets.content_browser_lifecycle_service import ContentBrowserLifecycleService


ASSET_ID_ROLE = Qt.UserRole + 1
ASSET_PATH_ROLE = Qt.UserRole + 2
ASSET_TYPE_ROLE = Qt.UserRole + 3
PROPERTY_KEY_ROLE = Qt.UserRole + 4
FOLDER_PATH_ROLE = Qt.UserRole + 5
ASSET_DOCUMENT_ROLE = Qt.UserRole + 6
COLLECTION_NAME_ROLE = Qt.UserRole + 7
TC_ASSET_MIME_TYPE = "application/x-tech-connector-asset"
PLACEABLE_ASSET_TYPES = {
    "tc.static_mesh", "tc.skeletal_mesh", "tc.prefab", "tc.effect_system",
    "tc.simulation_profile", "tc.audio_clip", "tc.behavior", "tc.gameplay_graph",
}
IMPORT_PRESETS = {
    "Balanced": {},
    "Fast iteration": {
        "tc.texture": {"generate_mips": False, "compression": "fast"},
        "tc.static_mesh": {"generate_collision": False, "tangents": "generate"},
        "tc.skeletal_mesh": {"import_morph_targets": False},
        "tc.audio_clip": {"compression": "fast"},
    },
    "High quality": {
        "tc.texture": {"generate_mips": True, "compression": "high_quality"},
        "tc.static_mesh": {"generate_collision": True, "normals": "import", "tangents": "generate"},
        "tc.skeletal_mesh": {"import_skin": True, "import_morph_targets": True},
        "tc.audio_clip": {"normalize": True, "compression": "high_quality"},
    },
}


def _maturity_label(maturity: str) -> str:
    return {
        "experimental": "Experimental",
        "authoring_preview": "Editor preview",
        "runtime_ready": "Runtime ready; shipping unqualified",
        "production_ready": "Production ready; check platform scope",
    }.get(str(maturity), "Maturity unknown")


class _AssetDropZone(QLabel):
    filesDropped = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(38)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and not event.mimeData().hasFormat(TC_ASSET_MIME_TYPE):
            event.acceptProposedAction()
            self.setProperty("dropActive", True)
            self.style().unpolish(self); self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dropActive", False)
        self.style().unpolish(self); self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.setProperty("dropActive", False)
        self.style().unpolish(self); self.style().polish(self)
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
        else:
            event.ignore()


class _AssetTreeWidget(QTreeWidget):
    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        payload = {
            "asset_id": str(item.data(0, ASSET_ID_ROLE) or ""),
            "path": str(item.data(0, ASSET_PATH_ROLE) or ""),
            "type_id": str(item.data(0, ASSET_TYPE_ROLE) or ""),
            "name": item.text(0),
        }
        mime = QMimeData()
        mime.setData(TC_ASSET_MIME_TYPE, json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        if payload["path"]:
            mime.setUrls([QUrl.fromLocalFile(payload["path"])])
        drag = QDrag(self)
        drag.setMimeData(mime)
        if not item.icon(0).isNull():
            drag.setPixmap(item.icon(0).pixmap(40, 40))
        drag.exec(Qt.CopyAction)


class _AssetThumbnailWidget(QListWidget):
    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        payload = {
            "asset_id": str(item.data(ASSET_ID_ROLE) or ""),
            "path": str(item.data(ASSET_PATH_ROLE) or ""),
            "type_id": str(item.data(ASSET_TYPE_ROLE) or ""),
            "name": item.text(),
        }
        mime = QMimeData()
        mime.setData(TC_ASSET_MIME_TYPE, json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        if payload["path"]:
            mime.setUrls([QUrl.fromLocalFile(payload["path"])])
        drag = QDrag(self)
        drag.setMimeData(mime)
        if not item.icon().isNull():
            drag.setPixmap(item.icon().pixmap(72, 72))
        drag.exec(Qt.CopyAction)


class _SourceControlSignals(QObject):
    finished = Signal(object)


class _SourceControlTask(QRunnable):
    def __init__(self, lifecycle: ContentBrowserLifecycleService, paths: list[str]) -> None:
        super().__init__()
        self.lifecycle = lifecycle
        self.paths = paths
        self.signals = _SourceControlSignals()

    def run(self) -> None:
        self.signals.finished.emit(self.lifecycle.source_control_snapshot(self.paths))


class _ImportQueueSignals(QObject):
    finished = Signal(object)


class _ImportQueueTask(QRunnable):
    def __init__(self, lifecycle: ContentBrowserLifecycleService) -> None:
        super().__init__()
        self.lifecycle = lifecycle
        self.signals = _ImportQueueSignals()

    def run(self) -> None:
        self.signals.finished.emit(self.lifecycle.import_queue.process_next())


class _PerforceTaskSignals(QObject):
    finished = Signal(object)


class _PerforceTask(QRunnable):
    def __init__(self, tag: str, operation: Callable[[], object]) -> None:
        super().__init__()
        self.tag = tag
        self.operation = operation
        self.signals = _PerforceTaskSignals()

    def run(self) -> None:
        try:
            result, error = self.operation(), ""
        except Exception as exc:
            result, error = None, str(exc)
        self.signals.finished.emit({"tag": self.tag, "result": result, "error": error})


class _AssetRefreshTask(QRunnable):
    """Collect the initial project inventory without blocking Qt's first frame."""

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _PerforceTaskSignals()

    def run(self) -> None:
        try:
            result, error = self.operation(), ""
        except Exception as exc:
            result, error = None, str(exc)
        self.signals.finished.emit({"tag": "asset_refresh", "result": result, "error": error})


class _TrackedAssetTask(QRunnable):
    def __init__(self, task_id: str, operation: Callable[[], object]) -> None:
        super().__init__(); self.task_id = str(task_id); self.operation = operation; self.signals = _PerforceTaskSignals()

    def run(self) -> None:
        try: result, error = self.operation(), ""
        except Exception as exc: result, error = None, str(exc)
        self.signals.finished.emit({"tag": self.task_id, "result": result, "error": error})


class AssetBrowserWidget(QWidget):
    assetActivated = Signal(str, str, str)
    assetPlacementRequested = Signal(str, str, str)
    statusMessage = Signal(str)
    busyChanged = Signal(bool, str)
    dependencyExplorerRequested = Signal(str)
    auditDashboardRequested = Signal()
    taskEvent = Signal(object)

    def __init__(
        self,
        project_root: str | Path,
        parent=None,
        *,
        database: AssetDatabase | None = None,
        registry: AssetTypeRegistry | None = None,
        defer_initial_refresh: bool = False,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.registry = registry or builtin_asset_type_registry()
        self.thumbnails = AssetThumbnailService()
        self.database = database or AssetDatabase(
            self.project_root / ".tech_connector" / "assets.sqlite3",
            self.project_root / ".tech_connector" / "derived_data",
        )
        self.operations = AssetOperationsService(self.project_root, self.database, self.registry)
        self.production = AssetProductionService(self.project_root, self.database, self.registry)
        self.exports = AssetExportService(self.project_root, self.database)
        self.bulk_operations = BulkAssetOperationService(
            self.project_root, self.database, operations=self.operations,
            production=self.production, exports=self.exports,
        )
        self.lifecycle = ContentBrowserLifecycleService(
            self.project_root, self.database, self.registry, self.operations,
        )
        self._collection_filter = ""
        self._folder_history = [""]
        self._folder_history_index = 0
        self._navigating_folder_history = False
        self._source_control_cache: dict[str, dict] = {}
        self._source_control_task = None
        self._import_queue_running = False
        self._import_queue_task = None
        self._active_import_queue_id = ""
        self._tracked_asset_tasks: dict[str, _TrackedAssetTask] = {}
        self._tracked_asset_retries: dict[str, tuple[str, Callable[[], object], dict, Callable[[object], tuple[str, str, dict]]]] = {}
        self._perforce_task = None
        self._asset_refresh_task = None
        self._asset_scan_in_progress = bool(defer_initial_refresh)
        self._latest_import_asset_id = ""
        self._syncing_asset_selection = False
        self._stale_source_asset_ids: set[str] = set()
        self._build_ui()
        self._install_keyboard_shortcuts()
        if defer_initial_refresh:
            self.asset_tree.addTopLevelItem(QTreeWidgetItem(["Loading project assets…", "", "Scanning in background"] ))
            QTimer.singleShot(0, self.refresh_async)
        else:
            self.refresh()
        self._source_watch_timer = QTimer(self)
        self._source_watch_timer.setInterval(2000)
        self._source_watch_timer.timeout.connect(self.check_external_source_updates)
        self._source_watch_timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)

        title_row = QHBoxLayout()
        title = QLabel("Assets")
        title.setStyleSheet("font-size:15px; font-weight:700; color:#eaf6ff;")
        title_row.addWidget(title)
        location = QLabel(str(self.project_root))
        location.setToolTip(str(self.project_root))
        location.setStyleSheet("color:#8299aa; font-size:10px;")
        title_row.addWidget(location)
        title_row.addStretch(1)

        starter_button = QPushButton("Starter Game…")
        starter_button.setToolTip("Create a playable default Level and editable gameplay assets from a template.")
        starter_button.clicked.connect(self.create_starter_game)
        title_row.addWidget(starter_button)

        self.create_button = QToolButton(self)
        self.create_button.setText("+ Create")
        self.create_button.setPopupMode(QToolButton.InstantPopup)
        self.create_button.setToolTip("Create an engine-authored asset in the current project.")
        self.create_button.setMenu(self._create_menu())
        title_row.addWidget(self.create_button)
        import_button = QPushButton("Import…")
        import_button.setToolTip("Copy a source file into the project and preserve its import settings in a .tcmeta sidecar.")
        import_button.clicked.connect(self.import_assets)
        title_row.addWidget(import_button)
        self.queue_button = QPushButton("Import Queue")
        self.queue_button.setToolTip("Show cancellable, recoverable asset imports and failures.")
        self.queue_button.clicked.connect(self.toggle_import_queue)
        title_row.addWidget(self.queue_button)
        refresh_button = QPushButton("Refresh")
        refresh_button.setToolTip("Rescan project assets in the background")
        refresh_button.clicked.connect(self.refresh_async)
        title_row.addWidget(refresh_button)
        self.vcs_button = QPushButton("VCS Refresh")
        self.vcs_button.setToolTip("Query Perforce for synced, checked-out, opened-elsewhere, and out-of-date states.")
        self.vcs_button.clicked.connect(self.refresh_source_control)
        title_row.addWidget(self.vcs_button)
        root.addLayout(title_row)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search…  type:tc.texture  state:authored  cook:uncooked  rev>=2  -status:missing")
        self.search_edit.setAccessibleName("Search assets")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setToolTip(
            "Structured fields: name, type, family, path, status, state, cook, vcs, tag, collection, rev, size. "
            "Use -term to exclude and quotes for phrases."
        )
        self.search_edit.textChanged.connect(self.apply_filter)
        filter_row.addWidget(self.search_edit, 1)
        self.family_button = QToolButton(self)
        self.family_button.setText("All Types")
        self.family_button.setAccessibleName("Filter asset types")
        self.family_button.setPopupMode(QToolButton.InstantPopup)
        family_menu = QMenu(self.family_button)
        all_action = family_menu.addAction("All Types")
        all_action.triggered.connect(lambda: self.set_family_filter(""))
        for family in self.registry.families():
            action = family_menu.addAction(family)
            action.triggered.connect(lambda _checked=False, value=family: self.set_family_filter(value))
        self.family_button.setMenu(family_menu)
        self._family_filter = ""
        filter_row.addWidget(self.family_button)
        self.folder_combo = QComboBox(self)
        self.folder_combo.setMinimumWidth(150)
        self.folder_combo.setAccessibleName("Filter asset folder")
        self.folder_combo.setToolTip("Limit the browser to a project folder and its descendants.")
        self.folder_combo.addItem("All Folders", "")
        self.folder_combo.currentIndexChanged.connect(
            lambda index: self.set_folder_filter(str(self.folder_combo.itemData(index) or ""))
        )
        self._folder_filter = ""
        filter_row.addWidget(self.folder_combo)
        self.collection_combo = QComboBox(self)
        self.collection_combo.setMinimumWidth(140)
        self.collection_combo.setAccessibleName("Filter asset collection")
        self.collection_combo.setToolTip("Show a saved static or dynamic collection.")
        self.collection_combo.addItem("All Collections", "")
        self.collection_combo.currentIndexChanged.connect(
            lambda index: self.set_collection_filter(str(self.collection_combo.itemData(index) or ""))
        )
        filter_row.addWidget(self.collection_combo)
        self.favorites_button = QPushButton("★ Favorites", self)
        self.favorites_button.setCheckable(True)
        self.favorites_button.setAccessibleName("Show favorite assets")
        self.favorites_button.setToolTip("Show only assets marked as favorites")
        self.favorites_button.clicked.connect(self.show_favorites)
        filter_row.addWidget(self.favorites_button)
        self.view_combo = QComboBox(self)
        self.view_combo.setAccessibleName("Asset browser view")
        self.view_combo.addItem("Thumbnails", "thumbnails")
        self.view_combo.addItem("Details", "details")
        self.view_combo.setToolTip("Switch between a visual thumbnail grid and detailed asset rows.")
        self.view_combo.currentIndexChanged.connect(self._set_asset_view_mode)
        filter_row.addWidget(self.view_combo)
        root.addLayout(filter_row)

        navigation_row = QHBoxLayout()
        self.back_folder_button = QPushButton("←")
        self.back_folder_button.setFixedWidth(30)
        self.back_folder_button.setAccessibleName("Back in asset folder history")
        self.back_folder_button.setToolTip("Back to the previous Content Browser folder")
        self.back_folder_button.setEnabled(False)
        self.back_folder_button.clicked.connect(lambda: self.navigate_folder_history(-1))
        navigation_row.addWidget(self.back_folder_button)
        self.forward_folder_button = QPushButton("→")
        self.forward_folder_button.setFixedWidth(30)
        self.forward_folder_button.setAccessibleName("Forward in asset folder history")
        self.forward_folder_button.setToolTip("Forward to the next Content Browser folder")
        self.forward_folder_button.setEnabled(False)
        self.forward_folder_button.clicked.connect(lambda: self.navigate_folder_history(1))
        navigation_row.addWidget(self.forward_folder_button)
        self.up_folder_button = QPushButton("↑")
        self.up_folder_button.setFixedWidth(30)
        self.up_folder_button.setToolTip("Go to the parent folder")
        self.up_folder_button.clicked.connect(self.go_to_parent_folder)
        navigation_row.addWidget(self.up_folder_button)
        self.breadcrumb_label = QLabel("Project / All Assets")
        self.breadcrumb_label.setStyleSheet("background:#0b141d; color:#b9d6e8; border:1px solid #1d3242; border-radius:4px; padding:5px 9px;")
        navigation_row.addWidget(self.breadcrumb_label, 1)
        self.new_folder_button = QPushButton("New Folder")
        self.new_folder_button.clicked.connect(self.create_folder)
        navigation_row.addWidget(self.new_folder_button)
        root.addLayout(navigation_row)

        self.import_drop_zone = _AssetDropZone(self)
        self.import_drop_zone.setAccessibleName("Asset import drop area")
        self.import_drop_zone.setAccessibleDescription(
            "Drop external files or folders here, or use the Import button for a keyboard-accessible file picker."
        )
        self.import_drop_zone.setStyleSheet(
            'QLabel { background:#091722; color:#8fb6c8; border:1px dashed #315066; '
            'border-radius:5px; padding:6px; } '
            'QLabel[dropActive="true"] { background:#12324a; color:#69f0ae; border:2px solid #46c996; }'
        )
        self.import_drop_zone.filesDropped.connect(self.queue_dropped_imports)
        root.addWidget(self.import_drop_zone)
        self._update_import_drop_zone()

        import_options = QHBoxLayout()
        import_options.addWidget(QLabel("Import preset:"))
        self.import_preset_combo = QComboBox(self)
        self.import_preset_combo.setAccessibleName("Import quality preset")
        for preset in IMPORT_PRESETS:
            self.import_preset_combo.addItem(preset, preset)
        self.import_preset_combo.setToolTip("Balanced preserves importer defaults; other presets optimize iteration speed or final quality.")
        import_options.addWidget(self.import_preset_combo)
        import_options.addWidget(QLabel("Name conflict:"))
        self.import_conflict_combo = QComboBox(self)
        self.import_conflict_combo.setAccessibleName("Import filename conflict policy")
        self.import_conflict_combo.addItem("Keep both", "rename")
        self.import_conflict_combo.addItem("Replace existing", "replace")
        self.import_conflict_combo.addItem("Skip existing", "skip")
        self.import_conflict_combo.setToolTip("Choose what happens when an imported filename already exists in the destination folder.")
        import_options.addWidget(self.import_conflict_combo)
        self.auto_reimport_checkbox = QCheckBox("Auto-reimport changed sources", self)
        self.auto_reimport_checkbox.setToolTip("Watch original external source files and reimport them when they change.")
        import_options.addWidget(self.auto_reimport_checkbox)
        import_options.addStretch(1)
        root.addLayout(import_options)

        self.empty_state = QFrame(self)
        empty_layout = QHBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(10, 7, 10, 7)
        self.empty_state_label = QLabel("Scanning project assets…", self.empty_state)
        self.empty_state_label.setWordWrap(True)
        empty_layout.addWidget(self.empty_state_label, 1)
        self.empty_create_button = QPushButton("Create Asset", self.empty_state)
        self.empty_create_button.setMenu(self._create_menu())
        empty_layout.addWidget(self.empty_create_button)
        self.empty_import_button = QPushButton("Import…", self.empty_state)
        self.empty_import_button.clicked.connect(self.import_assets)
        empty_layout.addWidget(self.empty_import_button)
        self.empty_state.setStyleSheet(
            "QFrame { background:#10202c; border:1px solid #28475b; border-radius:5px; }"
            "QLabel { color:#b9d6e8; border:0; }"
        )
        root.addWidget(self.empty_state)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        folder_panel = QFrame(splitter)
        folder_layout = QVBoxLayout(folder_panel)
        folder_layout.setContentsMargins(0, 0, 5, 0)
        folder_layout.addWidget(QLabel("PROJECT FOLDERS"))
        self.folder_tree = QTreeWidget(folder_panel)
        self.folder_tree.setAccessibleName("Project asset folders")
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setMinimumWidth(185)
        self.folder_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self._show_folder_context_menu)
        self.folder_tree.itemSelectionChanged.connect(self._folder_tree_selection_changed)
        folder_layout.addWidget(self.folder_tree, 1)
        collection_header = QHBoxLayout()
        collection_header.addWidget(QLabel("COLLECTIONS"), 1)
        add_collection = QPushButton("+")
        add_collection.setFixedWidth(28)
        add_collection.setToolTip("Create a static collection from the selection or a dynamic collection from the search.")
        add_collection.clicked.connect(self.create_collection)
        collection_header.addWidget(add_collection)
        remove_collection = QPushButton("−")
        remove_collection.setFixedWidth(28)
        remove_collection.setToolTip("Delete the selected collection; assets are not deleted.")
        remove_collection.clicked.connect(self.delete_selected_collection)
        collection_header.addWidget(remove_collection)
        folder_layout.addLayout(collection_header)
        self.collection_tree = QTreeWidget(folder_panel)
        self.collection_tree.setAccessibleName("Asset collections")
        self.collection_tree.setHeaderHidden(True)
        self.collection_tree.setMaximumHeight(170)
        self.collection_tree.itemSelectionChanged.connect(self._collection_tree_selection_changed)
        folder_layout.addWidget(self.collection_tree)
        splitter.addWidget(folder_panel)

        self.asset_stack = QStackedWidget(splitter)
        self.asset_tree = _AssetTreeWidget(self.asset_stack)
        self.asset_tree.setAccessibleName("Assets detail list")
        self.asset_tree.setHeaderLabels(["Name", "Type", "Content", "Cook", "Source Control", "Rev", "Path"])
        self.asset_tree.setIconSize(QSize(42, 42))
        self.asset_tree.setDragEnabled(True)
        self.asset_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.asset_tree.setAlternatingRowColors(True)
        self.asset_tree.setSortingEnabled(True)
        self.asset_tree.sortByColumn(0, Qt.AscendingOrder)
        self.asset_tree.itemSelectionChanged.connect(self._tree_selection_changed)
        self.asset_tree.itemDoubleClicked.connect(lambda item, _column: self._activate_item(item))
        self.asset_tree.itemActivated.connect(lambda item, _column: self._activate_item(item))
        self.asset_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.asset_tree.customContextMenuRequested.connect(self._show_asset_context_menu)
        self.asset_tree.setStyleSheet(
            "QTreeWidget { background:#071018; alternate-background-color:#091722; color:#d7f7ff; border:1px solid #1a2938; }"
            "QTreeWidget::item { min-height:24px; } QTreeWidget::item:selected { background:#12324a; color:#69f0ae; }"
            "QHeaderView::section { background:#0b1118; color:#9cc7d8; border:0; padding:5px; }"
        )
        self.asset_stack.addWidget(self.asset_tree)
        self.asset_grid = _AssetThumbnailWidget(self.asset_stack)
        self.asset_grid.setAccessibleName("Asset thumbnail grid")
        self.asset_grid.setViewMode(QListView.IconMode)
        self.asset_grid.setResizeMode(QListView.Adjust)
        self.asset_grid.setMovement(QListView.Static)
        self.asset_grid.setWrapping(True)
        self.asset_grid.setIconSize(QSize(96, 96))
        self.asset_grid.setGridSize(QSize(132, 138))
        self.asset_grid.setWordWrap(True)
        self.asset_grid.setDragEnabled(True)
        self.asset_grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.asset_grid.itemSelectionChanged.connect(self._grid_selection_changed)
        self.asset_grid.itemDoubleClicked.connect(lambda item: self._activate_grid_item(item))
        self.asset_grid.itemActivated.connect(self._activate_grid_item)
        self.asset_grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.asset_grid.customContextMenuRequested.connect(self._show_grid_context_menu)
        self.asset_grid.setStyleSheet(
            "QListWidget { background:#071018; color:#d7f7ff; border:1px solid #1a2938; }"
            "QListWidget::item { padding:6px; border-radius:5px; }"
            "QListWidget::item:selected { background:#12324a; color:#69f0ae; }"
        )
        self.asset_stack.addWidget(self.asset_grid)
        self.asset_stack.setCurrentWidget(self.asset_grid)
        splitter.addWidget(self.asset_stack)

        inspector = QFrame(splitter)
        inspector.setMinimumWidth(260)
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(10, 9, 10, 9)
        inspector_layout.addWidget(QLabel("ASSET INSPECTOR"))
        self.inspector_title = QLabel("Nothing selected")
        self.inspector_title.setWordWrap(True)
        self.inspector_title.setStyleSheet("font-size:14px; font-weight:700; color:#eaf6ff;")
        inspector_layout.addWidget(self.inspector_title)
        self.inspector_type = QLabel("Select an asset to view its type and import state.")
        self.inspector_type.setWordWrap(True)
        self.inspector_type.setStyleSheet("color:#75d8ff;")
        inspector_layout.addWidget(self.inspector_type)
        self.inspector_details = QLabel("")
        self.inspector_details.setWordWrap(True)
        self.inspector_details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.inspector_details.setStyleSheet("color:#9badba;")
        inspector_layout.addWidget(self.inspector_details)
        self.property_tree = QTreeWidget(inspector)
        self.property_tree.setAccessibleName("Selected asset properties")
        self.property_tree.setHeaderLabels(["Property", "Value"])
        self.property_tree.setRootIsDecorated(False)
        self.property_tree.setAlternatingRowColors(True)
        self.property_tree.setMinimumHeight(130)
        self.property_tree.setToolTip("Double-click a value to edit it. JSON is accepted for lists and nested values.")
        self.property_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.property_tree.customContextMenuRequested.connect(self._show_property_context_menu)
        self._property_mode = ""
        inspector_layout.addWidget(self.property_tree)
        self.save_properties_button = QPushButton("Save Properties")
        self.save_properties_button.setEnabled(False)
        self.save_properties_button.clicked.connect(self.save_selected_properties)
        inspector_layout.addWidget(self.save_properties_button)
        self.open_button = QPushButton("Open")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_selected)
        inspector_layout.addWidget(self.open_button)
        action_row = QHBoxLayout()
        self.reimport_button = QPushButton("Reimport")
        self.reimport_button.setEnabled(False)
        self.reimport_button.clicked.connect(self.reimport_selected)
        action_row.addWidget(self.reimport_button)
        self.rename_button = QPushButton("Rename")
        self.rename_button.setEnabled(False)
        self.rename_button.clicked.connect(self.rename_selected)
        action_row.addWidget(self.rename_button)
        self.move_button = QPushButton("Move…")
        self.move_button.setEnabled(False)
        self.move_button.clicked.connect(self.move_selected)
        action_row.addWidget(self.move_button)
        inspector_layout.addLayout(action_row)
        safety_row = QHBoxLayout()
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.setEnabled(False)
        self.duplicate_button.clicked.connect(self.duplicate_selected)
        safety_row.addWidget(self.duplicate_button)
        self.validate_button = QPushButton("Validate")
        self.validate_button.setEnabled(False)
        self.validate_button.clicked.connect(self.validate_selected)
        safety_row.addWidget(self.validate_button)
        self.delete_button = QPushButton("Delete…")
        self.delete_button.setEnabled(False)
        self.delete_button.setStyleSheet("color:#ff9d9d;")
        self.delete_button.clicked.connect(self.delete_selected)
        safety_row.addWidget(self.delete_button)
        inspector_layout.addLayout(safety_row)
        reference_row = QHBoxLayout()
        references_button = QPushButton("References")
        references_button.clicked.connect(self.show_selected_references)
        reference_row.addWidget(references_button)
        self.fix_paths_button = QPushButton("Fix Legacy Paths")
        self.fix_paths_button.setEnabled(False)
        self.fix_paths_button.clicked.connect(self.fix_selected_legacy_paths)
        reference_row.addWidget(self.fix_paths_button)
        inspector_layout.addLayout(reference_row)
        self.reference_tree = QTreeWidget(inspector)
        self.reference_tree.setAccessibleName("Selected asset dependencies and references")
        self.reference_tree.setHeaderLabels(["Relationship", "Asset", "Type"])
        self.reference_tree.setMinimumHeight(150)
        inspector_layout.addWidget(self.reference_tree)
        inspector_layout.addWidget(QLabel("REVISION HISTORY"))
        self.revision_tree = QTreeWidget(inspector)
        self.revision_tree.setAccessibleName("Selected asset revision history")
        self.revision_tree.setHeaderLabels(["Revision", "Event", "Details"])
        self.revision_tree.setMinimumHeight(105)
        inspector_layout.addWidget(self.revision_tree)
        inspector_layout.addWidget(QLabel("PERFORCE"))
        self.vcs_history_tree = QTreeWidget(inspector)
        self.vcs_history_tree.setAccessibleName("Selected asset source control history")
        self.vcs_history_tree.setHeaderLabels(["Rev", "Change", "Action", "User", "Description"])
        self.vcs_history_tree.setMinimumHeight(105)
        inspector_layout.addWidget(self.vcs_history_tree)
        vcs_actions = QHBoxLayout()
        history_button = QPushButton("History")
        history_button.clicked.connect(self.load_selected_vcs_history)
        vcs_actions.addWidget(history_button)
        changelists_button = QPushButton("Changelists")
        changelists_button.clicked.connect(self.show_perforce_changelists)
        vcs_actions.addWidget(changelists_button)
        checkout_button = QPushButton("Check Out")
        checkout_button.clicked.connect(lambda: self.run_selected_perforce_action("edit"))
        vcs_actions.addWidget(checkout_button)
        add_button = QPushButton("Add")
        add_button.clicked.connect(lambda: self.run_selected_perforce_action("add"))
        vcs_actions.addWidget(add_button)
        revert_button = QPushButton("Revert")
        revert_button.clicked.connect(lambda: self.run_selected_perforce_action("revert"))
        vcs_actions.addWidget(revert_button)
        inspector_layout.addLayout(vcs_actions)
        inspector_layout.addStretch(1)
        tip = QLabel("Double-click to open. Drag mesh, prefab, FX, audio, or gameplay assets into Garden to place an instance.")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#6f8392; font-size:10px;")
        inspector_layout.addWidget(tip)
        splitter.addWidget(inspector)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([210, 800, 300])
        root.addWidget(splitter, 1)

        self.import_queue_panel = QFrame(self)
        queue_layout = QVBoxLayout(self.import_queue_panel)
        queue_layout.setContentsMargins(6, 6, 6, 6)
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("IMPORT QUEUE"), 1)
        process_queue = QPushButton("Process")
        process_queue.clicked.connect(self.process_import_queue)
        queue_header.addWidget(process_queue)
        cancel_queue = QPushButton("Cancel Selected")
        cancel_queue.clicked.connect(self.cancel_selected_import)
        queue_header.addWidget(cancel_queue)
        retry_queue = QPushButton("Retry Selected")
        retry_queue.clicked.connect(self.retry_selected_import)
        queue_header.addWidget(retry_queue)
        clear_queue = QPushButton("Clear Finished")
        clear_queue.clicked.connect(self.clear_finished_imports)
        queue_header.addWidget(clear_queue)
        queue_layout.addLayout(queue_header)
        self.import_queue_tree = QTreeWidget(self.import_queue_panel)
        self.import_queue_tree.setAccessibleName("Asset import queue")
        self.import_queue_tree.setHeaderLabels(["Source", "Destination", "Status", "Progress", "Message"])
        self.import_queue_tree.setMaximumHeight(150)
        queue_layout.addWidget(self.import_queue_tree)
        self.import_queue_panel.setVisible(False)
        root.addWidget(self.import_queue_panel)

        self.import_result_panel = QFrame(self)
        result_layout = QHBoxLayout(self.import_result_panel)
        result_layout.setContentsMargins(8, 5, 8, 5)
        self.import_result_label = QLabel("Import complete")
        result_layout.addWidget(self.import_result_label, 1)
        open_import = QPushButton("Open")
        open_import.clicked.connect(self.open_latest_import)
        result_layout.addWidget(open_import)
        self.place_import_button = QPushButton("Place in Garden")
        self.place_import_button.clicked.connect(self.place_latest_import)
        result_layout.addWidget(self.place_import_button)
        dismiss_import = QPushButton("Dismiss")
        dismiss_import.clicked.connect(lambda: self.import_result_panel.setVisible(False))
        result_layout.addWidget(dismiss_import)
        self.import_result_panel.setStyleSheet(
            "QFrame { background:#10261f; border:1px solid #2b7658; border-radius:5px; }"
            "QLabel { color:#8ff0bd; border:0; }"
        )
        self.import_result_panel.setVisible(False)
        root.addWidget(self.import_result_panel)

        footer = QHBoxLayout()
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color:#8299aa; font-size:10px;")
        footer.addWidget(self.summary_label, 1)
        audit_button = QPushButton("Audit Project")
        audit_button.setToolTip("Validate all registered assets and summarize source memory and production warnings.")
        audit_button.clicked.connect(self.audit_project)
        footer.addWidget(audit_button)
        self.cook_button = QPushButton("Cook Selection")
        self.cook_button.setToolTip("Build a deterministic dependency-closed cook manifest for the selected assets.")
        self.cook_button.clicked.connect(self.cook_selected)
        footer.addWidget(self.cook_button)
        export_button = QPushButton("Export Selection…")
        export_button.setToolTip("Create a dependency-closed package for Unreal, Unity, Blender, Maya, Houdini, or generic interchange.")
        export_button.clicked.connect(self.export_selected)
        footer.addWidget(export_button)
        bulk_button = QPushButton("Bulk Operations…")
        bulk_button.setToolTip("Preview and run rename, move, tag, reimport, validate, cook, or export across the selection.")
        bulk_button.clicked.connect(self.open_bulk_operations)
        footer.addWidget(bulk_button)
        self.undo_button = QPushButton("Undo Asset Operation")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_last_operation)
        footer.addWidget(self.undo_button)
        root.addLayout(footer)

    def _install_keyboard_shortcuts(self) -> None:
        self._asset_shortcuts = []

        def bind(sequence: str | QKeySequence, callback: Callable[[], None]) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._asset_shortcuts.append(shortcut)

        bind("Ctrl+I", self.import_assets)
        bind("Ctrl+L", lambda: (self.search_edit.setFocus(Qt.ShortcutFocusReason), self.search_edit.selectAll()))
        bind("F5", self.refresh)
        bind("F2", self.rename_selected)
        bind(QKeySequence.Delete, self.delete_selected)
        bind("Ctrl+Shift+V", self.validate_selected)

    def _create_menu(self) -> QMenu:
        menu = QMenu(self)
        family_menus: dict[str, QMenu] = {}
        for descriptor in self.registry.all(creatable=True):
            family_menu = family_menus.get(descriptor.family)
            if family_menu is None:
                family_menu = menu.addMenu(descriptor.family)
                family_menus[descriptor.family] = family_menu
            action = family_menu.addAction(f"{descriptor.display_name} · {_maturity_label(descriptor.maturity)}")
            action.setToolTip(f"Create {descriptor.display_name}. {_maturity_label(descriptor.maturity)}")
            action.triggered.connect(
                lambda _checked=False, type_id=descriptor.type_id: self.create_asset(type_id)
            )
        return menu

    def _populate_create_submenu(self, menu: QMenu) -> None:
        family_menus: dict[str, QMenu] = {}
        for descriptor in self.registry.all(creatable=True):
            family_menu = family_menus.get(descriptor.family)
            if family_menu is None:
                family_menu = menu.addMenu(descriptor.family)
                family_menus[descriptor.family] = family_menu
            action = family_menu.addAction(f"{descriptor.display_name} · {_maturity_label(descriptor.maturity)}")
            action.setToolTip(_maturity_label(descriptor.maturity))
            action.triggered.connect(lambda _checked=False, type_id=descriptor.type_id: self.create_asset(type_id))
        menu._tc_child_menus = list(family_menus.values())

    def create_starter_game(self) -> None:
        from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
        from tech_connector.ui.game_engine.game_template_dialog import GameTemplateDialog

        api = TCEditorAPI(self.project_root, database=self.database, registry=self.registry)
        dialog = GameTemplateDialog(self.project_root, self, api=api)
        if dialog.exec() != QDialog.Accepted or not dialog.receipt:
            return
        self.refresh()
        receipt = dialog.receipt
        self.statusMessage.emit(
            f"Created {receipt['template_id']}/{receipt['variant_id']}; the default Level passed Play-readiness checks."
        )

    def _collect_refresh_inventory(self) -> dict[str, object]:
        """Read database and filesystem state; safe to run outside the UI thread."""
        warning = ""
        try:
            self.database.scan_changes()
        except Exception as exc:
            warning = f"Asset scan warning: {exc}"
        records = {str(record.source_path).casefold(): record for record in self.database.list_assets()}
        discovered: dict[str, tuple[Path, str, str, str]] = {}
        folders: set[str] = set()
        if self.project_root.is_dir():
            for root, directory_names, file_names in os.walk(self.project_root):
                directory_names[:] = [name for name in directory_names if name != ".tech_connector"]
                root_path = Path(root)
                for directory_name in directory_names:
                    directory = root_path / directory_name
                    try: folders.add(directory.relative_to(self.project_root).as_posix())
                    except ValueError: pass
                for file_name in file_names:
                    if file_name.endswith(".tcmeta"):
                        continue
                    path = root_path / file_name
                    descriptor = self.registry.infer(path)
                    if descriptor is None:
                        continue
                    resolved_path = path.resolve()
                    key = str(resolved_path).casefold()
                    record = records.get(key)
                    discovered[key] = (
                        resolved_path, descriptor.type_id,
                        record.status.title() if record else "Source",
                        record.asset_id if record else "",
                    )
        for key, record in records.items():
            descriptor = self.registry.descriptor(record.asset_type)
            type_id = descriptor.type_id if descriptor else record.asset_type
            discovered.setdefault(key, (record.source_path, type_id, record.status.title(), record.asset_id))

        for path, _type_id, _status, _asset_id in discovered.values():
            try:
                relative_parent = path.relative_to(self.project_root).parent
            except ValueError:
                continue
            parts = relative_parent.parts
            for depth in range(1, len(parts) + 1):
                folders.add(Path(*parts[:depth]).as_posix())
        return {"discovered": discovered, "folders": folders, "warning": warning}

    def refresh_async(self) -> bool:
        if self._asset_refresh_task is not None:
            return False
        self._asset_scan_in_progress = True
        self.apply_filter()
        task = _AssetRefreshTask(self._collect_refresh_inventory)
        task.signals.finished.connect(self._asset_refresh_finished)
        self._asset_refresh_task = task
        self.statusMessage.emit("Scanning project assets in the background…")
        self.busyChanged.emit(True, "Scanning assets")
        QThreadPool.globalInstance().start(task)
        return True

    def _asset_refresh_finished(self, payload: object) -> None:
        self._asset_refresh_task = None
        self._asset_scan_in_progress = False
        self.busyChanged.emit(False, "")
        result = dict(payload) if isinstance(payload, dict) else {}
        error = str(result.get("error") or "")
        if error:
            self.statusMessage.emit(f"Asset scan warning: {error}")
            self.apply_filter()
            return
        inventory = result.get("result")
        if isinstance(inventory, dict):
            self.refresh(inventory=inventory)
            self.statusMessage.emit(
                f"Asset scan complete • {self.asset_tree.topLevelItemCount()} assets discovered."
            )

    def refresh(self, *, inventory: dict[str, object] | None = None) -> None:
        payload = inventory if isinstance(inventory, dict) else self._collect_refresh_inventory()
        warning = str(payload.get("warning") or "")
        if warning:
            self.statusMessage.emit(warning)
        discovered = dict(payload.get("discovered") or {})
        folders = set(payload.get("folders") or set())
        current_folder = self._folder_filter
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        self.folder_combo.addItem("All Folders", "")
        for folder in sorted(folders, key=str.casefold):
            self.folder_combo.addItem(folder, folder)
        selected_index = self.folder_combo.findData(current_folder)
        self.folder_combo.setCurrentIndex(max(0, selected_index))
        self.folder_combo.blockSignals(False)
        self._rebuild_folder_tree(folders)
        self._rebuild_collections()

        self.asset_tree.setSortingEnabled(False)
        self.asset_tree.clear()
        self.asset_grid.clear()
        collections = self.lifecycle.collections()
        cooked_asset_ids = set(self.database.assets_with_valid_derived_data())
        for path, type_id, status, asset_id in discovered.values():
            descriptor = self.registry.descriptor(type_id)
            display_type = descriptor.display_name if descriptor else type_id
            try:
                relative = path.relative_to(self.project_root).as_posix()
            except ValueError:
                relative = str(path)
            membership = tuple(
                collection.name for collection in collections
                if collection.kind == "static" and asset_id in collection.asset_ids
            )
            vcs = self._source_control_cache.get(str(path.resolve()), {}).get("status", "not_queried")
            document = self.lifecycle.asset_document(
                path, type_id, asset_id, source_control=vcs, collections=membership,
                cooked=asset_id in cooked_asset_ids,
            )
            source_changed = asset_id in self._stale_source_asset_ids
            content_label = document["state_label"] + (" • Source changed" if source_changed else "")
            item = QTreeWidgetItem([
                path.name, display_type, content_label, document["cook_label"],
                str(document["vcs"]).replace("_", " ").title(),
                str(document["revision"] or "—"), relative,
            ])
            item.setData(0, ASSET_ID_ROLE, asset_id)
            item.setData(0, ASSET_PATH_ROLE, str(path))
            item.setData(0, ASSET_TYPE_ROLE, type_id)
            item.setData(0, ASSET_DOCUMENT_ROLE, document)
            maturity_label = _maturity_label(descriptor.maturity) if descriptor else "Maturity unknown"
            item.setData(0, Qt.AccessibleTextRole, f"{path.stem}, {display_type}, {maturity_label}, {content_label}")
            item.setData(
                0, Qt.AccessibleDescriptionRole,
                f"{relative}. {maturity_label}. {document['cook_label']}. Source control {str(document['vcs']).replace('_', ' ')}.",
            )
            if descriptor is not None:
                detail_icon = self.thumbnails.icon(
                    path, descriptor, badges=(document["state"], document["cook"]),
                )
                item.setIcon(0, detail_icon)
            item.setToolTip(
                0, f"{display_type} • {maturity_label}\n{relative}\n{content_label} • {document['cook_label']}\n"
                f"{asset_id or 'Source file—not registered as an authored asset'}"
            )
            self.asset_tree.addTopLevelItem(item)
            grid_item = QListWidgetItem(
                self.thumbnails.icon(
                    path, descriptor, size=96, badges=(document["state"], document["cook"]),
                ) if descriptor is not None else item.icon(0),
                f"{path.stem}\n{display_type} · {maturity_label}",
            )
            grid_item.setData(ASSET_ID_ROLE, asset_id)
            grid_item.setData(ASSET_PATH_ROLE, str(path))
            grid_item.setData(ASSET_TYPE_ROLE, type_id)
            grid_item.setData(ASSET_DOCUMENT_ROLE, document)
            grid_item.setData(Qt.AccessibleTextRole, f"{path.stem}, {display_type}, {maturity_label}, {content_label}")
            grid_item.setData(
                Qt.AccessibleDescriptionRole,
                f"{relative}. {maturity_label}. {document['cook_label']}. Press Enter to open; use the context menu for more actions.",
            )
            grid_item.setToolTip(item.toolTip(0))
            grid_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.asset_grid.addItem(grid_item)
        self.asset_tree.setSortingEnabled(True)
        for column in range(6):
            self.asset_tree.resizeColumnToContents(column)
        self.apply_filter()
        self._refresh_import_queue_view()
        self._update_undo_button()

    def set_family_filter(self, family: str) -> None:
        self._family_filter = str(family)
        self.family_button.setText(family or "All Types")
        self.apply_filter()

    def set_folder_filter(self, folder: str) -> None:
        previous = self._folder_filter
        self._folder_filter = str(folder).replace("\\", "/").strip("/")
        if self._folder_filter != previous and not self._navigating_folder_history:
            del self._folder_history[self._folder_history_index + 1:]
            self._folder_history.append(self._folder_filter)
            self._folder_history = self._folder_history[-50:]
            self._folder_history_index = len(self._folder_history) - 1
        selected_index = self.folder_combo.findData(self._folder_filter)
        if selected_index >= 0 and self.folder_combo.currentIndex() != selected_index:
            self.folder_combo.blockSignals(True)
            self.folder_combo.setCurrentIndex(selected_index)
            self.folder_combo.blockSignals(False)
        self.breadcrumb_label.setText("Project / " + (self._folder_filter or "All Assets"))
        self.up_folder_button.setEnabled(bool(self._folder_filter))
        self._update_import_drop_zone()
        self._update_folder_history_buttons()
        self.apply_filter()

    def navigate_folder_history(self, offset: int) -> bool:
        target = self._folder_history_index + int(offset)
        if target < 0 or target >= len(self._folder_history):
            return False
        self._folder_history_index = target
        self._navigating_folder_history = True
        try:
            self.set_folder_filter(self._folder_history[target])
            self._select_folder_tree_path(self._folder_filter)
        finally:
            self._navigating_folder_history = False
        self._update_folder_history_buttons()
        return True

    def _update_folder_history_buttons(self) -> None:
        if hasattr(self, "back_folder_button"):
            self.back_folder_button.setEnabled(self._folder_history_index > 0)
            self.forward_folder_button.setEnabled(self._folder_history_index < len(self._folder_history) - 1)

    def _update_import_drop_zone(self) -> None:
        zone = getattr(self, "import_drop_zone", None)
        if zone is not None:
            zone.setText(
                f"Drop files or folders here to import into {self.current_content_folder()}  ·  "
                "supported files are detected automatically"
            )

    def set_collection_filter(self, collection: str) -> None:
        self._collection_filter = str(collection or "")
        index = self.collection_combo.findData(self._collection_filter)
        if index >= 0 and index != self.collection_combo.currentIndex():
            self.collection_combo.blockSignals(True)
            self.collection_combo.setCurrentIndex(index)
            self.collection_combo.blockSignals(False)
        self.favorites_button.blockSignals(True)
        self.favorites_button.setChecked(self._collection_filter.casefold() == "favorites")
        self.favorites_button.blockSignals(False)
        self.apply_filter()

    def show_favorites(self, enabled: bool = True) -> None:
        if enabled and self.lifecycle.collection("Favorites") is None:
            self.lifecycle.save_collection("Favorites")
            self._rebuild_collections()
        self.set_collection_filter("Favorites" if enabled else "")

    def _rebuild_collections(self) -> None:
        current = self._collection_filter
        collections = self.lifecycle.collections()
        self.collection_combo.blockSignals(True)
        self.collection_combo.clear()
        self.collection_combo.addItem("All Collections", "")
        self.collection_tree.blockSignals(True)
        self.collection_tree.clear()
        for collection in collections:
            suffix = "Dynamic" if collection.kind == "dynamic" else f"{len(collection.asset_ids)} assets"
            self.collection_combo.addItem(collection.name, collection.name)
            item = QTreeWidgetItem([f"{collection.name}  ·  {suffix}"])
            item.setData(0, COLLECTION_NAME_ROLE, collection.name)
            item.setToolTip(0, collection.query if collection.kind == "dynamic" else "Static collection")
            self.collection_tree.addTopLevelItem(item)
            if collection.name == current:
                self.collection_tree.setCurrentItem(item)
        index = self.collection_combo.findData(current)
        if index < 0:
            current = ""; self._collection_filter = ""; index = 0
        self.collection_combo.setCurrentIndex(index)
        self.collection_combo.blockSignals(False)
        self.collection_tree.blockSignals(False)

    def _collection_tree_selection_changed(self) -> None:
        item = self.collection_tree.currentItem()
        if item is not None:
            self.set_collection_filter(str(item.data(0, COLLECTION_NAME_ROLE) or ""))

    def _rebuild_folder_tree(self, folders: set[str]) -> None:
        current = self._folder_filter
        self.folder_tree.blockSignals(True)
        self.folder_tree.clear()
        root_item = QTreeWidgetItem(["All Assets"])
        root_item.setData(0, FOLDER_PATH_ROLE, "")
        self.folder_tree.addTopLevelItem(root_item)
        by_path: dict[str, QTreeWidgetItem] = {"": root_item}
        for folder in sorted(folders, key=lambda value: (value.count("/"), value.casefold())):
            parent_path = Path(folder).parent.as_posix()
            if parent_path == ".": parent_path = ""
            parent = by_path.get(parent_path, root_item)
            item = QTreeWidgetItem([Path(folder).name])
            item.setData(0, FOLDER_PATH_ROLE, folder)
            item.setToolTip(0, folder)
            parent.addChild(item); by_path[folder] = item
        root_item.setExpanded(True)
        selected = by_path.get(current, root_item)
        self.folder_tree.setCurrentItem(selected)
        ancestor = selected.parent()
        while ancestor is not None:
            ancestor.setExpanded(True); ancestor = ancestor.parent()
        self.folder_tree.blockSignals(False)
        self.breadcrumb_label.setText("Project / " + (current or "All Assets"))
        self.up_folder_button.setEnabled(bool(current))

    def _folder_tree_selection_changed(self) -> None:
        item = self.folder_tree.currentItem()
        if item is not None:
            self.set_folder_filter(str(item.data(0, FOLDER_PATH_ROLE) or ""))

    def go_to_parent_folder(self) -> None:
        if not self._folder_filter:
            return
        parent = Path(self._folder_filter).parent.as_posix()
        self.set_folder_filter("" if parent == "." else parent)
        self._select_folder_tree_path(self._folder_filter)

    def _select_folder_tree_path(self, folder: str) -> None:
        iterator = [self.folder_tree.topLevelItem(index) for index in range(self.folder_tree.topLevelItemCount())]
        while iterator:
            item = iterator.pop(0)
            if str(item.data(0, FOLDER_PATH_ROLE) or "") == folder:
                self.folder_tree.setCurrentItem(item); return
            iterator.extend(item.child(index) for index in range(item.childCount()))

    def current_content_folder(self) -> str:
        return self._folder_filter or "Assets"

    def apply_filter(self) -> None:
        query = self.search_edit.text().strip()
        query_terms = self.lifecycle.compile_query(query)
        selected_collection = self.lifecycle.collection(self._collection_filter) if self._collection_filter else None
        static_collection_ids = set(selected_collection.asset_ids) if selected_collection and selected_collection.kind == "static" else set()
        dynamic_collection_terms = self.lifecycle.compile_query(selected_collection.query) if selected_collection and selected_collection.kind == "dynamic" else ()
        visible = 0
        for index in range(self.asset_tree.topLevelItemCount()):
            item = self.asset_tree.topLevelItem(index)
            document = item.data(0, ASSET_DOCUMENT_ROLE) or {}
            descriptor = self.registry.descriptor(str(item.data(0, ASSET_TYPE_ROLE) or ""))
            family = descriptor.family if descriptor else ""
            item_folder = Path(str(document.get("path") or "")).parent.as_posix()
            folder_matches = (
                not self._folder_filter
                or item_folder.casefold() == self._folder_filter.casefold()
                or item_folder.casefold().startswith(self._folder_filter.casefold() + "/")
            )
            collection_matches = (
                not self._collection_filter
                or bool(selected_collection and (
                    self.lifecycle.matches_compiled(document, dynamic_collection_terms)
                    if selected_collection.kind == "dynamic"
                    else str(document.get("asset_id") or "") in static_collection_ids
                ))
            )
            matches = self.lifecycle.matches_compiled(document, query_terms) and (
                not self._family_filter or family == self._family_filter
            ) and folder_matches and collection_matches
            item.setHidden(not matches)
            if index < self.asset_grid.count():
                self.asset_grid.item(index).setHidden(not matches)
            visible += int(matches)
        filter_text = f"  •  Collection: {self._collection_filter}" if self._collection_filter else ""
        self.summary_label.setText(
            f"{visible} visible asset{'s' if visible != 1 else ''}  •  "
            f"{self.asset_tree.topLevelItemCount()} discovered{filter_text}"
        )
        has_filters = bool(query or self._family_filter or self._folder_filter or self._collection_filter)
        self.empty_state.setVisible(bool(self._asset_scan_in_progress or visible == 0))
        if self._asset_scan_in_progress:
            self.empty_state_label.setText("Scanning project assets in the background… You can keep working while results load.")
        elif has_filters:
            self.empty_state_label.setText("No assets match these filters. Clear search, folder, type, or collection filters to see more.")
        else:
            self.empty_state_label.setText("This project has no assets yet. Create an engine asset or import source files to begin.")
        self.empty_create_button.setEnabled(not self._asset_scan_in_progress)
        self.empty_import_button.setEnabled(not self._asset_scan_in_progress)

    def _set_asset_view_mode(self, _index: int = -1) -> None:
        mode = str(self.view_combo.currentData() or "thumbnails")
        self.asset_stack.setCurrentWidget(self.asset_grid if mode == "thumbnails" else self.asset_tree)

    def _tree_selection_changed(self) -> None:
        if not self._syncing_asset_selection:
            self._syncing_asset_selection = True
            try:
                selected = {
                    (str(item.data(0, ASSET_ID_ROLE) or ""), str(item.data(0, ASSET_PATH_ROLE) or ""))
                    for item in self.asset_tree.selectedItems()
                }
                self.asset_grid.clearSelection()
                current = None
                for index in range(self.asset_grid.count()):
                    item = self.asset_grid.item(index)
                    match = (str(item.data(ASSET_ID_ROLE) or ""), str(item.data(ASSET_PATH_ROLE) or "")) in selected
                    item.setSelected(match)
                    if match and current is None:
                        current = item
                if current is not None:
                    self.asset_grid.setCurrentItem(current)
            finally:
                self._syncing_asset_selection = False
        self._update_inspector()

    def _grid_selection_changed(self) -> None:
        if self._syncing_asset_selection:
            return
        self._syncing_asset_selection = True
        try:
            selected = {
                (str(item.data(ASSET_ID_ROLE) or ""), str(item.data(ASSET_PATH_ROLE) or ""))
                for item in self.asset_grid.selectedItems()
            }
            self.asset_tree.clearSelection()
            current = None
            for index in range(self.asset_tree.topLevelItemCount()):
                row = self.asset_tree.topLevelItem(index)
                matches = (
                    str(row.data(0, ASSET_ID_ROLE) or ""),
                    str(row.data(0, ASSET_PATH_ROLE) or ""),
                ) in selected
                row.setSelected(matches)
                if matches and current is None:
                    current = row
            if current is not None:
                self.asset_tree.setCurrentItem(current)
        finally:
            self._syncing_asset_selection = False
        self._update_inspector()

    def _activate_grid_item(self, item: QListWidgetItem) -> None:
        self._grid_selection_changed()
        self.assetActivated.emit(
            str(item.data(ASSET_PATH_ROLE) or ""),
            str(item.data(ASSET_TYPE_ROLE) or ""),
            str(item.data(ASSET_ID_ROLE) or ""),
        )

    def _show_grid_context_menu(self, position) -> None:
        item = self.asset_grid.itemAt(position)
        if item is not None and item not in self.asset_grid.selectedItems():
            self.asset_grid.setCurrentItem(item)
        self._grid_selection_changed()
        menu = self._asset_context_menu(has_item=item is not None)
        menu.exec(self.asset_grid.viewport().mapToGlobal(position))

    def _update_inspector(self) -> None:
        item = self.asset_tree.currentItem()
        self.open_button.setEnabled(item is not None)
        asset_id = str(item.data(0, ASSET_ID_ROLE) or "") if item is not None else ""
        selected_record = self.database.asset(asset_id) if asset_id else None
        import_source = str(selected_record.metadata.get("import_source") or "") if selected_record else ""
        self.reimport_button.setEnabled(bool(import_source and Path(import_source).is_file()))
        self.rename_button.setEnabled(bool(asset_id))
        self.move_button.setEnabled(bool(asset_id))
        self.duplicate_button.setEnabled(bool(asset_id))
        self.validate_button.setEnabled(bool(asset_id))
        self.delete_button.setEnabled(bool(asset_id))
        self.fix_paths_button.setEnabled(bool(asset_id))
        self._update_undo_button()
        self.reference_tree.clear()
        self.revision_tree.clear()
        self.vcs_history_tree.clear()
        self.property_tree.clear()
        self.save_properties_button.setEnabled(False)
        if item is None:
            self.inspector_title.setText("Nothing selected")
            self.inspector_type.setText("Select an asset to view its type and import state.")
            self.inspector_details.clear()
            return
        type_id = str(item.data(0, ASSET_TYPE_ROLE) or "")
        descriptor = self.registry.descriptor(type_id)
        document = item.data(0, ASSET_DOCUMENT_ROLE) or {}
        self.inspector_title.setText(item.text(0))
        self.inspector_type.setText(
            f"{descriptor.display_name if descriptor else type_id}  •  {descriptor.family if descriptor else 'Unregistered'}"
        )
        hot_reload = descriptor.hot_reload_class.replace("_", " ").title() if descriptor else "Unknown"
        self.inspector_details.setText(
            f"Maturity: {_maturity_label(descriptor.maturity) if descriptor else 'Maturity unknown'}\n"
            f"Content: {document.get('state_label', item.text(2))}\n"
            f"Cook: {document.get('cook_label', '—')}\n"
            f"Source control: {str(document.get('vcs') or 'not_queried').replace('_', ' ').title()}\n"
            f"Revision: {document.get('revision') or '—'}\nPath: {document.get('path') or item.text(6)}\n"
            f"Asset ID: {asset_id or 'Not registered'}\nLive update: {hot_reload}\n"
            f"{document.get('instance_note') or ''}"
        )
        self._load_selected_properties(selected_record, descriptor)
        if asset_id:
            report = self.operations.reference_report(asset_id)
            for relationship, key in (("Uses", "dependencies"), ("Used by", "referencers")):
                for record in report[key]:
                    descriptor = self.registry.descriptor(record["type_id"])
                    child = QTreeWidgetItem([
                        relationship,
                        Path(record["path"]).name,
                        descriptor.display_name if descriptor else record["type_id"],
                    ])
                    child.setToolTip(1, record["path"])
                    self.reference_tree.addTopLevelItem(child)
            if self.reference_tree.topLevelItemCount() == 0:
                self.reference_tree.addTopLevelItem(QTreeWidgetItem(["References", "None", "—"]))
            for event in self.lifecycle.revision_history(asset_id, limit=20):
                payload = dict(event.get("payload") or {})
                detail = ", ".join(f"{key}={value}" for key, value in list(payload.items())[:2]) or "—"
                revision = str(payload.get("revision") or "—")
                child = QTreeWidgetItem([revision, str(event.get("kind") or "change").replace("_", " ").title(), detail])
                child.setToolTip(2, json.dumps(payload, indent=2, sort_keys=True))
                self.revision_tree.addTopLevelItem(child)

    def _load_selected_properties(self, record, descriptor) -> None:
        if record is None or not record.source_path.is_file():
            return
        self._property_mode = ""
        try:
            payload = json.loads(record.source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        properties = payload.get("properties") if isinstance(payload, dict) else None
        if isinstance(properties, dict):
            self._property_mode = "authored"
            self.save_properties_button.setText("Save Properties")
        else:
            try:
                sidecar = read_asset_metadata(record.source_path)
            except ValueError:
                sidecar = {}
            properties = sidecar.get("importer_settings") if isinstance(sidecar, dict) else None
            if isinstance(properties, dict) and properties:
                self._property_mode = "import"
                self.save_properties_button.setText("Save Import Settings")
        if not isinstance(properties, dict):
            return
        schema = {item.key: item for item in asset_property_schema(record.asset_type)}
        for key, value in properties.items():
            property_descriptor = schema.get(str(key))
            display_name = property_descriptor.display_name if property_descriptor else str(key).replace("_", " ").title()
            text = json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list, bool)) or value is None else str(value)
            item = QTreeWidgetItem([display_name, text])
            item.setData(0, PROPERTY_KEY_ROLE, str(key))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            if property_descriptor:
                item.setToolTip(0, property_descriptor.tooltip)
                item.setToolTip(1, property_descriptor.tooltip)
            self.property_tree.addTopLevelItem(item)
        self.property_tree.resizeColumnToContents(0)
        self.save_properties_button.setEnabled(True)

    def save_selected_properties(self) -> None:
        asset_id = self._selected_asset_id()
        record = self.database.asset(asset_id) if asset_id else None
        if record is None:
            return
        try:
            properties = {}
            for index in range(self.property_tree.topLevelItemCount()):
                item = self.property_tree.topLevelItem(index)
                key = str(item.data(0, PROPERTY_KEY_ROLE) or "")
                raw = item.text(1).strip()
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    value = raw
                properties[key] = value
            if self._property_mode == "import":
                sidecar = read_asset_metadata(record.source_path)
                write_asset_metadata(
                    record.source_path, asset_id=record.asset_id, type_id=record.asset_type,
                    importer=str(sidecar.get("importer") or ""), importer_settings=properties,
                    previous_paths=list(sidecar.get("previous_paths") or ()),
                )
                metadata = {**record.metadata, "importer_settings": properties}
            else:
                if record.asset_type == "tc.ui_document":
                    from tech_connector.game_engine.assets.ui_document_asset_service import UIDocumentAssetService

                    UIDocumentAssetService(self.project_root, self.database).update(
                        record.asset_id, properties, replace=True,
                    )
                else:
                    payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    payload["properties"] = properties
                    record.source_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                metadata = record.metadata
            if record.asset_type != "tc.ui_document":
                self.database.register_asset(
                    record.source_path, record.asset_type, asset_id=record.asset_id,
                    metadata=metadata, dependencies=self.database.dependency_edges(record.asset_id),
                )
        except Exception as exc:
            QMessageBox.warning(self, "Property save failed", str(exc))
            return
        hot_reload = self.registry.require(record.asset_type).hot_reload_class.replace("_", " ")
        self.statusMessage.emit(f"Saved properties for {record.source_path.name}; live update: {hot_reload}.")
        self.refresh()

    def _show_property_context_menu(self, position) -> None:
        item = self.property_tree.itemAt(position)
        if item is None: return
        self.property_tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Copy Value", lambda: QApplication.clipboard().setText(item.text(1)))
        menu.addAction("Paste Value", lambda: item.setText(1, QApplication.clipboard().text()))
        menu.addAction("Reset to Default", lambda: self.reset_property_to_default(item))
        menu.exec(self.property_tree.viewport().mapToGlobal(position))

    def reset_property_to_default(self, item: QTreeWidgetItem | None = None) -> bool:
        row = item or self.property_tree.currentItem()
        asset_id = self._selected_asset_id(); record = self.database.asset(asset_id) if asset_id else None
        if row is None or record is None: return False
        key = str(row.data(0, PROPERTY_KEY_ROLE) or "")
        descriptor = next((value for value in asset_property_schema(record.asset_type) if value.key == key), None)
        if descriptor is None: return False
        default = descriptor.default
        row.setText(1, json.dumps(default, separators=(",", ":")) if isinstance(default, (dict, list, bool)) or default is None else str(default))
        return True

    def _activate_item(self, item: QTreeWidgetItem) -> None:
        self.assetActivated.emit(
            str(item.data(0, ASSET_PATH_ROLE) or ""),
            str(item.data(0, ASSET_TYPE_ROLE) or ""),
            str(item.data(0, ASSET_ID_ROLE) or ""),
        )

    def open_selected(self) -> None:
        item = self.asset_tree.currentItem()
        if item is not None:
            self._activate_item(item)

    def _show_asset_context_menu(self, position) -> None:
        item = self.asset_tree.itemAt(position)
        if item is not None and item not in self.asset_tree.selectedItems():
            self.asset_tree.setCurrentItem(item)
        menu = self._asset_context_menu(has_item=item is not None)
        menu.exec(self.asset_tree.viewport().mapToGlobal(position))

    def _asset_context_menu(self, *, has_item: bool | None = None) -> QMenu:
        selected = self.asset_tree.currentItem() is not None if has_item is None else bool(has_item)
        asset_id = self._selected_asset_id() if selected else ""
        record = self.database.asset(asset_id) if asset_id else None
        menu = QMenu(self)
        if selected:
            menu.addAction("Open", self.open_selected)
            favorites = self.lifecycle.collection("Favorites")
            selected_ids = set(self._selected_asset_ids())
            all_favorites = bool(selected_ids and favorites and selected_ids.issubset(set(favorites.asset_ids)))
            menu.addAction(
                "Remove from Favorites" if all_favorites else "Add to Favorites",
                self.toggle_selected_favorites,
            )
            menu.addSeparator()
        create_menu = menu.addMenu("Create Asset")
        menu._tc_child_menus = [create_menu]
        self._populate_create_submenu(create_menu)
        menu.addAction("Import Assets…", self.import_assets)
        menu.addAction("New Folder…", self.create_folder)
        if selected:
            menu.addSeparator()
            copy_menu = menu.addMenu("Copy Reference")
            menu._tc_child_menus.append(copy_menu)
            copy_menu.addAction("Asset ID", self.copy_selected_asset_id)
            copy_menu.addAction("Project Path", self.copy_selected_asset_path)
            menu.addAction("Add Tags…", self.prompt_add_tags)
            menu.addAction("Bulk Operations…", self.open_bulk_operations)
            menu.addAction("Rename", self.rename_selected).setEnabled(bool(asset_id))
            menu.addAction("Duplicate", self.duplicate_selected).setEnabled(bool(asset_id))
            menu.addAction("Move To…", self.move_selected).setEnabled(bool(asset_id))
            reimport = menu.addAction("Reimport", self.reimport_selected)
            reimport.setEnabled(bool(record and record.metadata.get("import_source")))
            menu.addSeparator()
            menu.addAction("Validate", self.validate_selected).setEnabled(bool(asset_id))
            menu.addAction("Cook Selection", self.cook_selected).setEnabled(bool(asset_id))
            menu.addAction("Export Selection…", self.export_selected).setEnabled(bool(asset_id))
            menu.addAction("Find References", self.show_selected_references).setEnabled(bool(asset_id))
            menu.addAction("Dependency Explorer", lambda: self.dependencyExplorerRequested.emit(asset_id)).setEnabled(bool(asset_id))
            menu.addAction("Fix Legacy Paths", self.fix_selected_legacy_paths).setEnabled(bool(asset_id))
            collection_menu = menu.addMenu("Add to Collection")
            menu._tc_child_menus.append(collection_menu)
            for collection in self.lifecycle.collections():
                if collection.kind == "static":
                    collection_menu.addAction(
                        collection.name,
                        lambda _checked=False, name=collection.name: self.add_selected_to_collection(name),
                    )
            menu.addSeparator()
            delete = menu.addAction("Delete…", self.delete_selected); delete.setEnabled(bool(asset_id))
        menu.addSeparator()
        menu.addAction("Repair Project References", self.repair_project_references)
        menu.addAction("Open Asset Audit", self.auditDashboardRequested.emit)
        menu.addAction("Refresh Source Control", self.refresh_source_control)
        menu.addAction("Refresh", self.refresh_async)
        return menu

    def _show_folder_context_menu(self, position) -> None:
        item = self.folder_tree.itemAt(position)
        if item is not None:
            self.folder_tree.setCurrentItem(item)
        menu = QMenu(self)
        create_menu = menu.addMenu("Create Asset")
        menu._tc_child_menus = [create_menu]
        self._populate_create_submenu(create_menu)
        menu.addAction("Import Assets…", self.import_assets)
        menu.addAction("New Folder…", self.create_folder)
        if self._folder_filter:
            menu.addAction("Show Parent Folder", self.go_to_parent_folder)
        menu.addSeparator(); menu.addAction("Refresh", self.refresh_async)
        menu.exec(self.folder_tree.viewport().mapToGlobal(position))

    def create_asset(self, type_id: str, *, name: str = "", folder: str = "") -> None:
        descriptor = self.registry.require(type_id)
        if not name:
            name, accepted = QInputDialog.getText(self, f"Create {descriptor.display_name}", "Asset name:")
            if not accepted or not name.strip():
                return
        target_folder = folder or self.current_content_folder()
        try:
            receipt = self.operations.create_asset(type_id, name, folder=target_folder)
        except Exception as exc:
            QMessageBox.warning(self, "Asset creation failed", str(exc))
            return
        self.statusMessage.emit(receipt.message)
        self.refresh()
        self.set_folder_filter(target_folder)
        self._select_asset_id(receipt.asset_id)

    def import_assets(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "Import Assets", str(self.project_root))
        if not paths:
            return
        self.import_asset_paths(paths, process_immediately=False)
        self.import_queue_panel.setVisible(True)
        self.process_import_queue()

    def import_asset_paths(
        self, paths: list[str] | tuple[str, ...], *, folder: str = "", process_immediately: bool = True,
        conflict_policy: str = "",
    ) -> tuple[str, ...]:
        target_folder = folder or self.current_content_folder()
        policy = conflict_policy or str(self.import_conflict_combo.currentData() or "rename")
        queued = []
        for path in paths:
            descriptor = self.registry.infer(path)
            type_id = descriptor.type_id if descriptor is not None else ""
            preset_name = str(self.import_preset_combo.currentData() or "Balanced")
            importer_settings = dict(IMPORT_PRESETS.get(preset_name, {}).get(type_id, {}))
            queued.extend(self.lifecycle.import_queue.enqueue(
                [path], folder=target_folder, type_id=type_id,
                importer_settings=importer_settings, conflict_policy=policy,
            ))
        self._refresh_import_queue_view()
        if not process_immediately:
            self.statusMessage.emit(f"Queued {len(queued)} asset import(s).")
            return tuple(item.message for item in queued)
        processed = self.lifecycle.import_queue.process_all()
        messages = [item.message for item in processed if item.status == "complete"]
        errors = [f"{Path(item.source_path).name}: {item.message}" for item in processed if item.status == "failed"]
        self.refresh()
        self.set_folder_filter(target_folder)
        if messages:
            self.statusMessage.emit(f"Imported {len(messages)} asset(s).")
        if errors:
            QMessageBox.warning(self, "Some assets were not imported", "\n".join(errors))
        return tuple(messages)

    def classify_import_paths(
        self, paths: list[str] | tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Expand dropped folders and separate importable files from unsupported inputs."""
        candidates: list[Path] = []
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if path.is_dir():
                candidates.extend(item for item in path.rglob("*") if item.is_file())
            elif path.is_file():
                candidates.append(path)
        supported: list[str] = []
        unsupported: list[str] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path).casefold()
            if key in seen:
                continue
            seen.add(key)
            descriptor = self.registry.infer(path)
            try:
                path.relative_to(self.project_root)
                inside_project = True
            except ValueError:
                inside_project = False
            if descriptor is not None and descriptor.importable and not inside_project:
                supported.append(str(path))
            else:
                unsupported.append(str(path))
        return tuple(supported), tuple(unsupported)

    def queue_dropped_imports(self, paths: object) -> dict[str, object]:
        raw_paths = [str(path) for path in (paths or ())]
        supported, unsupported = self.classify_import_paths(raw_paths)
        if supported:
            self.import_asset_paths(supported, process_immediately=False)
            self.import_queue_panel.setVisible(True)
            self.process_import_queue()
        summary = f"Queued {len(supported)} asset(s) for {self.current_content_folder()}."
        if unsupported:
            summary += f" Skipped {len(unsupported)} unsupported or already-project file(s)."
        if not supported:
            summary = "No importable external assets were found in the drop."
        self.statusMessage.emit(summary)
        return {"queued": supported, "skipped": unsupported, "folder": self.current_content_folder()}

    def check_external_source_updates(self) -> tuple[str, ...]:
        """Detect changed original source files and optionally reimport them in place."""
        stale: list[str] = []
        for record in self.database.list_assets():
            source = Path(str(record.metadata.get("import_source") or "")).expanduser()
            if not source.is_file():
                continue
            recorded_ns = int(record.metadata.get("import_source_modified_ns") or record.modified_ns or 0)
            if source.stat().st_mtime_ns > recorded_ns:
                stale.append(record.asset_id)
        new_stale = set(stale)
        if new_stale != self._stale_source_asset_ids:
            self._stale_source_asset_ids = new_stale
            if stale and not self.auto_reimport_checkbox.isChecked():
                self.statusMessage.emit(
                    f"{len(stale)} imported source file(s) changed externally; select and Reimport, or enable Auto-reimport."
                )
            self.refresh()
        if stale and self.auto_reimport_checkbox.isChecked():
            completed = 0
            for asset_id in stale:
                try:
                    self.operations.reimport_asset(asset_id)
                    completed += 1
                except Exception as exc:
                    self.statusMessage.emit(f"Auto-reimport failed: {exc}")
            self._stale_source_asset_ids.clear()
            self.thumbnails.invalidate()
            self.refresh()
            self.statusMessage.emit(f"Auto-reimported {completed} changed source asset(s).")
        return tuple(stale)

    def toggle_import_queue(self) -> None:
        self.import_queue_panel.setVisible(not self.import_queue_panel.isVisible())
        self._refresh_import_queue_view()

    def process_import_queue(self) -> None:
        if self._import_queue_running:
            return
        self._import_queue_running = True
        self.import_queue_panel.setVisible(True)
        self._process_import_queue_step()

    def _process_import_queue_step(self) -> None:
        if self._import_queue_task is not None:
            return
        if not any(item.status == "queued" for item in self.lifecycle.import_queue.items()):
            self._import_queue_running = False
            self._active_import_queue_id = ""
            self.refresh()
            if self._latest_import_asset_id:
                self._select_asset_id(self._latest_import_asset_id)
            return
        queued_item = next(item for item in self.lifecycle.import_queue.items() if item.status == "queued")
        self._active_import_queue_id = queued_item.queue_id
        self.taskEvent.emit({
            "operation": "begin", "task_id": f"import:{queued_item.queue_id}",
            "label": f"Import {Path(queued_item.source_path).name}", "category": "import",
            "can_cancel": True, "can_retry": True,
            "metadata": {"path": queued_item.source_path},
        })
        task = _ImportQueueTask(self.lifecycle)
        task.signals.finished.connect(self._import_queue_item_finished)
        self._import_queue_task = task
        QThreadPool.globalInstance().start(task)
        QTimer.singleShot(100, self._poll_import_queue_progress)

    def _poll_import_queue_progress(self) -> None:
        self._refresh_import_queue_view()
        if self._import_queue_task is not None:
            current = next((item for item in self.lifecycle.import_queue.items() if item.queue_id == self._active_import_queue_id), None)
            if current is not None:
                self.taskEvent.emit({
                    "operation": "update", "task_id": f"import:{current.queue_id}",
                    "progress": current.progress, "message": current.message,
                })
            QTimer.singleShot(100, self._poll_import_queue_progress)

    def _import_queue_item_finished(self, item: object) -> None:
        self._import_queue_task = None
        self._refresh_import_queue_view()
        if item is not None:
            status = str(getattr(item, "status", "failed"))
            state = "complete" if status == "complete" else "canceled" if status == "cancelled" else "failed"
            self.taskEvent.emit({
                "operation": "finish", "task_id": f"import:{getattr(item, 'queue_id', self._active_import_queue_id)}",
                "state": state, "message": str(getattr(item, "message", "Import finished.")),
                "metadata": {"asset_id": str(getattr(item, "asset_id", "")), "path": str(getattr(item, "source_path", ""))},
            })
            self.statusMessage.emit(str(getattr(item, "message", "Import completed.")))
            if str(getattr(item, "status", "")) == "complete":
                self._show_import_result(str(getattr(item, "asset_id", "")))
        self._active_import_queue_id = ""
        QTimer.singleShot(0, self._process_import_queue_step)

    def cancel_background_task(self, task_id: str) -> bool:
        if not str(task_id).startswith("import:"): return False
        changed = self.lifecycle.import_queue.cancel(str(task_id).split(":", 1)[1])
        if changed: self._refresh_import_queue_view()
        return changed

    def retry_background_task(self, task_id: str) -> bool:
        identifier = str(task_id)
        if identifier.startswith("import:"):
            changed = self.lifecycle.import_queue.retry(identifier.split(":", 1)[1])
            if changed: self._refresh_import_queue_view(); self.process_import_queue()
            return changed
        spec = self._tracked_asset_retries.get(identifier)
        if spec is None: return False
        label, operation, metadata, completed = spec
        return self._start_tracked_asset_task(identifier, label, operation, metadata, completed)

    def _show_import_result(self, asset_id: str) -> None:
        record = self.database.asset(asset_id) if asset_id else None
        if record is None:
            return
        self._latest_import_asset_id = record.asset_id
        descriptor = self.registry.descriptor(record.asset_type)
        display_type = descriptor.display_name if descriptor is not None else record.asset_type
        validation = self.operations.validate_asset(record.asset_id)
        errors = sum(1 for issue in validation.issues if issue.severity == "error")
        warnings = sum(1 for issue in validation.issues if issue.severity == "warning")
        validation_text = "Validation passed" if not validation.issues else f"{errors} error(s), {warnings} warning(s)"
        self.import_result_label.setText(
            f"Imported {record.source_path.name} as {display_type}  ·  {validation_text}"
        )
        self.place_import_button.setEnabled(record.asset_type in PLACEABLE_ASSET_TYPES and errors == 0)
        self.place_import_button.setToolTip(
            "Place an instance in the current Garden level."
            if self.place_import_button.isEnabled()
            else (
                "Resolve validation errors before placing this asset."
                if errors else "This asset type opens in an editor instead of being placed in a level."
            )
        )
        self.import_result_panel.setVisible(True)

    def open_latest_import(self) -> None:
        record = self.database.asset(self._latest_import_asset_id) if self._latest_import_asset_id else None
        if record is not None:
            self.assetActivated.emit(str(record.source_path), record.asset_type, record.asset_id)

    def place_latest_import(self) -> None:
        record = self.database.asset(self._latest_import_asset_id) if self._latest_import_asset_id else None
        if record is not None and record.asset_type in PLACEABLE_ASSET_TYPES:
            self.assetPlacementRequested.emit(str(record.source_path), record.asset_type, record.asset_id)

    def _refresh_import_queue_view(self) -> None:
        if not hasattr(self, "import_queue_tree"):
            return
        self.import_queue_tree.clear()
        pending = 0
        for item in self.lifecycle.import_queue.items():
            row = QTreeWidgetItem([
                Path(item.source_path).name, item.folder, item.status.replace("_", " ").title(),
                f"{item.progress}%", item.message,
            ])
            row.setData(0, Qt.UserRole, item.queue_id)
            row.setToolTip(0, item.source_path)
            self.import_queue_tree.addTopLevelItem(row)
            pending += int(item.status in {"queued", "processing"})
        self.queue_button.setText(f"Import Queue ({pending})" if pending else "Import Queue")

    def cancel_selected_import(self) -> None:
        item = self.import_queue_tree.currentItem()
        if item is not None:
            self.lifecycle.import_queue.cancel(str(item.data(0, Qt.UserRole) or ""))
            self._refresh_import_queue_view()

    def retry_selected_import(self) -> None:
        item = self.import_queue_tree.currentItem()
        if item is not None and self.lifecycle.import_queue.retry(str(item.data(0, Qt.UserRole) or "")):
            self._refresh_import_queue_view()
            self.process_import_queue()

    def clear_finished_imports(self) -> None:
        removed = self.lifecycle.import_queue.clear_finished()
        self._refresh_import_queue_view()
        self.statusMessage.emit(f"Cleared {removed} finished import queue item(s).")

    def create_folder(self) -> None:
        name, accepted = QInputDialog.getText(self, "Create Project Folder", "Folder name:")
        if accepted and name.strip():
            try:
                folder = self.create_folder_named(name)
            except Exception as exc:
                QMessageBox.warning(self, "Folder creation failed", str(exc)); return
            self.statusMessage.emit(f"Created project folder {folder}.")

    def create_folder_named(self, name: str, *, parent_folder: str = "") -> str:
        safe = str(name).strip().replace("\\", "/").strip("/")
        if not safe or any(part in {"", ".", ".."} for part in safe.split("/")):
            raise ValueError("Folder name must be a relative project folder name.")
        if any(character in '<>:"|?*' for character in safe):
            raise ValueError("Folder name contains characters that are not portable.")
        parent = (parent_folder or self.current_content_folder()).replace("\\", "/").strip("/")
        relative = (Path(parent) / Path(safe)).as_posix()
        destination = (self.project_root / relative).resolve()
        try: destination.relative_to(self.project_root)
        except ValueError as exc: raise ValueError("Folder must remain inside the project.") from exc
        destination.mkdir(parents=True, exist_ok=False)
        self.set_folder_filter(relative); self.refresh(); self._select_folder_tree_path(relative)
        return relative

    def create_collection(self) -> None:
        kind_label, accepted = QInputDialog.getItem(
            self, "Create Collection", "Collection type:",
            ["Static — selected assets", "Dynamic — current search"], 0, False,
        )
        if not accepted:
            return
        name, accepted = QInputDialog.getText(self, "Create Collection", "Collection name:")
        if not accepted or not name.strip():
            return
        try:
            if kind_label.startswith("Dynamic"):
                collection = self.lifecycle.save_collection(
                    name, kind="dynamic", query=self.search_edit.text().strip(),
                )
            else:
                collection = self.lifecycle.save_collection(name, asset_ids=self._selected_asset_ids())
        except Exception as exc:
            QMessageBox.warning(self, "Collection creation failed", str(exc))
            return
        self._collection_filter = collection.name
        self._rebuild_collections()
        self.set_collection_filter(collection.name)
        self.statusMessage.emit(f"Created {collection.kind} collection '{collection.name}'.")

    def delete_selected_collection(self) -> None:
        item = self.collection_tree.currentItem()
        name = str(item.data(0, COLLECTION_NAME_ROLE) or "") if item is not None else self._collection_filter
        if not name:
            return
        if self.lifecycle.delete_collection(name):
            self._collection_filter = ""
            self._rebuild_collections()
            self.apply_filter()
            self.statusMessage.emit(f"Deleted collection '{name}'; no assets were changed.")

    def add_selected_to_collection(self, name: str) -> None:
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            return
        try:
            collection = self.lifecycle.add_to_collection(name, asset_ids)
        except Exception as exc:
            QMessageBox.warning(self, "Collection update failed", str(exc))
            return
        self._rebuild_collections()
        self.apply_filter()
        self.statusMessage.emit(f"Added {len(asset_ids)} asset(s) to '{collection.name}'.")

    def toggle_selected_favorites(self) -> bool:
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            return False
        favorites = self.lifecycle.collection("Favorites")
        current = set(favorites.asset_ids) if favorites else set()
        remove = set(asset_ids).issubset(current)
        if favorites is None:
            updated = self.lifecycle.save_collection("Favorites", asset_ids=asset_ids)
        elif remove:
            updated = self.lifecycle.remove_from_collection("Favorites", asset_ids)
        else:
            updated = self.lifecycle.add_to_collection("Favorites", asset_ids)
        self._rebuild_collections()
        self.apply_filter()
        verb = "Removed" if remove else "Added"
        relation = "from" if remove else "to"
        self.statusMessage.emit(f"{verb} {len(asset_ids)} asset(s) {relation} Favorites.")
        return bool(updated)

    def _select_asset_id(self, asset_id: str) -> None:
        for index in range(self.asset_tree.topLevelItemCount()):
            item = self.asset_tree.topLevelItem(index)
            if str(item.data(0, ASSET_ID_ROLE) or "") == str(asset_id):
                self.asset_tree.setCurrentItem(item); self.asset_tree.scrollToItem(item); return

    def _selected_asset_id(self) -> str:
        item = self.asset_tree.currentItem()
        return str(item.data(0, ASSET_ID_ROLE) or "") if item is not None else ""

    def open_bulk_operations(self) -> bool:
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            QMessageBox.information(self, "Bulk Asset Operations", "Select one or more assets first.")
            return False
        dialog = BulkAssetOperationsDialog(self.bulk_operations, asset_ids, self)
        if dialog.exec() != QDialog.Accepted or dialog.receipt is None:
            return False
        receipt = dialog.receipt
        self.statusMessage.emit(
            f"Bulk {receipt.operation} completed for {len(receipt.asset_ids)} asset(s)."
            + (f" Undo: {receipt.undo_label}." if receipt.undoable else "")
        )
        self.refresh()
        return True

    def reimport_selected(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            return
        record = self.database.asset(asset_id)
        metadata = {"asset_id": asset_id, "path": str(record.source_path) if record else ""}

        def completed(result: object) -> tuple[str, str, dict]:
            self.refresh_async(); message = str(getattr(result, "message", "Reimport complete.")); self.statusMessage.emit(message)
            return "complete", message, {}

        self._start_tracked_asset_task(
            f"reimport:{asset_id}", f"Reimport {record.source_path.name if record else asset_id}",
            lambda: self.operations.reimport_asset(asset_id), metadata, completed,
        )

    def _start_tracked_asset_task(
        self, task_id: str, label: str, operation: Callable[[], object], metadata: dict,
        completed: Callable[[object], tuple[str, str, dict]],
    ) -> bool:
        identifier = str(task_id)
        if identifier in self._tracked_asset_tasks: return False
        self._tracked_asset_retries[identifier] = (str(label), operation, dict(metadata), completed)
        while len(self._tracked_asset_retries) > 100:
            self._tracked_asset_retries.pop(next(iter(self._tracked_asset_retries)))
        task = _TrackedAssetTask(identifier, operation)
        task.signals.finished.connect(lambda payload, done=completed: self._tracked_asset_task_finished(payload, done))
        self._tracked_asset_tasks[identifier] = task
        self.taskEvent.emit({
            "operation": "begin", "task_id": identifier, "label": str(label),
            "category": "assets", "can_retry": True, "metadata": dict(metadata),
        })
        QThreadPool.globalInstance().start(task)
        return True

    def _tracked_asset_task_finished(
        self, payload: object, completed: Callable[[object], tuple[str, str, dict]],
    ) -> None:
        result = dict(payload) if isinstance(payload, dict) else {}
        task_id = str(result.get("tag") or ""); self._tracked_asset_tasks.pop(task_id, None)
        error = str(result.get("error") or "")
        if error:
            self.statusMessage.emit(f"Asset task failed: {error}")
            self.taskEvent.emit({"operation": "finish", "task_id": task_id, "state": "failed", "message": error})
            return
        try: state, message, metadata = completed(result.get("result"))
        except Exception as exc:
            state, message, metadata = "failed", str(exc), {}
        self.taskEvent.emit({
            "operation": "finish", "task_id": task_id, "state": state,
            "message": message, "metadata": metadata,
        })

    def rename_selected(self) -> None:
        asset_id = self._selected_asset_id()
        item = self.asset_tree.currentItem()
        if not asset_id or item is None:
            return
        current = Path(item.text(0)).stem
        name, accepted = QInputDialog.getText(self, "Rename Asset", "New name:", text=current)
        if not accepted or not name.strip():
            return
        try:
            receipt = self.operations.rename_asset(asset_id, name)
        except Exception as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))
            return
        self.statusMessage.emit(receipt.message)
        self.refresh()

    def move_selected(self) -> None:
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            return
        folder = QFileDialog.getExistingDirectory(self, "Move Asset Inside Project", str(self.project_root / "Assets"))
        if not folder:
            return
        try:
            receipts = self.operations.move_assets(asset_ids, folder)
        except Exception as exc:
            QMessageBox.warning(self, "Move failed", str(exc))
            return
        self.statusMessage.emit(f"Moved {len(receipts)} asset(s); UUID references remain valid.")
        self.refresh()

    def _selected_asset_ids(self) -> list[str]:
        return [
            str(item.data(0, ASSET_ID_ROLE) or "")
            for item in self.asset_tree.selectedItems()
            if str(item.data(0, ASSET_ID_ROLE) or "")
        ]

    def copy_selected_asset_id(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        QApplication.clipboard().setText(asset_id)
        self.statusMessage.emit("Copied stable asset ID.")
        return True

    def copy_selected_asset_path(self) -> bool:
        asset_id = self._selected_asset_id(); record = self.database.asset(asset_id) if asset_id else None
        if record is None: return False
        try: value = record.source_path.relative_to(self.project_root).as_posix()
        except ValueError: value = str(record.source_path)
        QApplication.clipboard().setText(value)
        self.statusMessage.emit("Copied project-relative asset path.")
        return True

    def prompt_add_tags(self) -> None:
        raw, accepted = QInputDialog.getText(self, "Add Asset Tags", "Tags to add to every selected asset (comma separated):")
        if accepted: self.add_tags_to_selected(raw)

    def add_tags_to_selected(self, tags: str | list[str] | tuple[str, ...]) -> int:
        values = [value.strip() for value in (tags.split(",") if isinstance(tags, str) else tags) if str(value).strip()]
        asset_ids = self._selected_asset_ids()
        if not values or not asset_ids: return 0
        try:
            plan = self.bulk_operations.plan("tag", asset_ids, options={"add_tags": values})
            receipt = self.bulk_operations.execute(plan)
        except Exception as exc:
            QMessageBox.warning(self, "Tag assets failed", str(exc)); return 0
        changed = len(receipt.asset_ids)
        self.statusMessage.emit(f"Added {len(values)} tag(s) to {changed} asset(s).")
        self.refresh()
        return changed

    def export_selected(self) -> None:
        asset_ids = self._selected_asset_ids()
        if not asset_ids: return
        target, accepted = QInputDialog.getItem(self, "Export Assets", "Target package:", ["Generic", "Unreal", "Unity", "Blender", "Maya", "Houdini"], 0, False)
        if not accepted: return
        destination = QFileDialog.getExistingDirectory(self, f"Export for {target}", str(self.project_root / "Exports"))
        if not destination: return
        try: receipt = self.exports.export_assets(asset_ids, Path(destination) / f"TechConnector_{target}", target=target.casefold())
        except Exception as exc: QMessageBox.warning(self, "Export failed", str(exc)); return
        message = f"Exported {len(receipt.asset_ids)} dependency-closed asset(s) for {target} to {receipt.destination}."
        if receipt.warnings: message += f" {len(receipt.warnings)} warning(s)."
        self.statusMessage.emit(message)

    def duplicate_selected(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            return
        try:
            receipt = self.operations.duplicate_asset(asset_id)
        except Exception as exc:
            QMessageBox.warning(self, "Duplicate failed", str(exc))
            return
        self.statusMessage.emit(receipt.message)
        self.refresh()

    def validate_selected(self) -> None:
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            return
        ids = tuple(asset_ids); first = self.database.asset(ids[0]); metadata = {"asset_ids": list(ids), "asset_id": ids[0] if len(ids) == 1 else "", "path": str(first.source_path) if len(ids) == 1 and first else ""}

        def completed(result: object) -> tuple[str, str, dict]:
            reports = list(result or ()); issues = [issue for report in reports for issue in report.issues]
            errors = sum(issue.severity == "error" for issue in issues); warnings = sum(issue.severity == "warning" for issue in issues)
            message = f"Validated {len(reports)} asset(s): {errors} error(s), {warnings} warning(s)." if issues else f"{len(reports)} asset(s) passed validation."
            self.statusMessage.emit(message)
            return ("failed" if errors else "complete"), message, {"validation_errors": errors, "validation_warnings": warnings}

        self._start_tracked_asset_task(
            f"validate:{time.time_ns()}", f"Validate {len(ids)} asset(s)",
            lambda: tuple(self.operations.validate_asset(asset_id) for asset_id in ids), metadata, completed,
        )

    def delete_selected(self) -> None:
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            return
        if len(asset_ids) > 1:
            answer = QMessageBox.question(
                self, "Move Assets to Project Trash",
                f"Move {len(asset_ids)} selected assets to recoverable project trash? Referenced assets will be skipped.",
            )
            if answer != QMessageBox.Yes:
                return
            deleted = 0
            errors = []
            for asset_id in asset_ids:
                try:
                    self.operations.delete_asset(asset_id)
                    deleted += 1
                except Exception as exc:
                    errors.append(str(exc))
            self.statusMessage.emit(f"Moved {deleted} asset(s) to project trash.")
            self.refresh()
            if errors:
                QMessageBox.warning(self, "Some assets were retained", "\n".join(errors))
            return

        asset_id = asset_ids[0]
        record = self.database.asset(asset_id)
        if record is None:
            return
        replacement_id = ""
        referencers = self.database.referencers(asset_id)
        if referencers:
            compatible = [
                item for item in self.database.list_assets(status="ready")
                if item.asset_type == record.asset_type and item.asset_id != asset_id
            ]
            if not compatible:
                QMessageBox.warning(
                    self, "Asset Is In Use",
                    f"{record.source_path.name} is referenced by {len(referencers)} asset(s). No compatible replacement exists.",
                )
                return
            labels = [f"{item.source_path.name}  —  {item.source_path}" for item in compatible]
            choice, accepted = QInputDialog.getItem(
                self, "Replace References Before Delete",
                f"Used by {len(referencers)} asset(s). Replace every reference with:", labels, 0, False,
            )
            if not accepted:
                return
            replacement_id = compatible[labels.index(choice)].asset_id
        answer = QMessageBox.question(
            self, "Move Asset to Project Trash",
            f"Move {record.source_path.name} to recoverable project trash?"
            + ("\nAll tracked references will be replaced first." if replacement_id else ""),
        )
        if answer != QMessageBox.Yes:
            return
        try:
            receipt = self.operations.delete_asset(asset_id, replacement_asset_id=replacement_id)
        except AssetInUseError as exc:
            QMessageBox.warning(self, "Asset Is In Use", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
            return
        self.statusMessage.emit(f"Moved {Path(receipt.original_path).name} to recoverable project trash.")
        self.refresh()

    def undo_last_operation(self) -> None:
        try:
            receipt = self.operations.undo_last()
        except Exception as exc:
            QMessageBox.warning(self, "Undo failed", str(exc))
            return
        self.statusMessage.emit(str(getattr(receipt, "message", "Asset operation undone.")))
        self.refresh()

    def _update_undo_button(self) -> None:
        self.undo_button.setEnabled(self.operations.can_undo)
        self.undo_button.setText(
            f"Undo {self.operations.undo_label}" if self.operations.can_undo else "Undo Asset Operation"
        )

    def audit_project(self) -> None:
        report = self.production.audit()
        severity_counts = {
            severity: sum(1 for issue in report.issues if issue.severity == severity)
            for severity in ("error", "warning", "info")
        }
        largest = "\n".join(
            f"  • {Path(path).name}: {size / (1024 * 1024):.2f} MiB"
            for path, size in report.largest_assets[:5]
        ) or "  None"
        QMessageBox.information(
            self, "Project Asset Audit",
            f"Status: {'READY' if report.ready else 'NEEDS ATTENTION'}\n"
            f"Assets: {report.asset_count}\nSource size: {report.source_bytes / (1024 * 1024):.2f} MiB\n"
            f"Errors: {severity_counts['error']}  Warnings: {severity_counts['warning']}  Info: {severity_counts['info']}\n\n"
            f"Largest assets:\n{largest}",
        )

    def cook_selected(self) -> None:
        asset_ids = self._selected_asset_ids()
        if not asset_ids:
            QMessageBox.information(self, "Cook Selection", "Select one or more registered assets first.")
            return
        ids = tuple(asset_ids); first = self.database.asset(ids[0]); metadata = {"asset_ids": list(ids), "asset_id": ids[0] if len(ids) == 1 else "", "path": str(first.source_path) if len(ids) == 1 and first else ""}

        def completed(result: object) -> tuple[str, str, dict]:
            receipt = result
            message = f"Cooked {len(receipt.asset_ids)} dependency-closed asset(s) for {receipt.platform}/{receipt.quality}."
            self.statusMessage.emit(message); self.refresh_async()
            return "complete", message, {"output": str(receipt.artifact.path), "source_bytes": int(receipt.source_bytes)}

        self._start_tracked_asset_task(
            f"cook:{time.time_ns()}", f"Cook {len(ids)} selected asset(s)",
            lambda: self.production.cook_manifest(ids), metadata, completed,
        )

    def show_selected_references(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset References", "Import this source into the asset database to track references.")
            return
        report = self.operations.reference_report(asset_id)
        dependencies = report["dependencies"]
        referencers = report["referencers"]
        lines = [f"Dependencies ({len(dependencies)}):"]
        lines.extend(f"  • {Path(item['path']).name}" for item in dependencies)
        lines.append(f"\nDirect referencers ({len(referencers)}):")
        lines.extend(f"  • {Path(item['path']).name}" for item in referencers)
        if not dependencies and not referencers:
            lines.append("  None")
        QMessageBox.information(self, "Asset References", "\n".join(lines))

    def fix_selected_legacy_paths(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            return
        try:
            receipt = self.operations.fix_legacy_path_references(asset_id)
        except Exception as exc:
            QMessageBox.warning(self, "Reference fix-up failed", str(exc))
            return
        self.statusMessage.emit(
            f"Fixed {receipt.replacements} legacy path reference(s) in {len(receipt.updated_assets)} asset(s)."
        )
        self.refresh()

    def repair_project_references(self) -> None:
        health = self.lifecycle.reference_health()
        answer = QMessageBox.question(
            self, "Repair Project References",
            f"Scan authored assets for legacy paths and prune {health['stale_redirectors']} stale redirector(s)?\n"
            "Stable UUID references are preserved.",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            receipt = self.operations.repair_project_references()
        except Exception as exc:
            QMessageBox.warning(self, "Reference repair failed", str(exc))
            return
        self.statusMessage.emit(
            f"Repaired {receipt['replacements']} reference(s) in {len(receipt['updated_assets'])} asset(s); "
            f"pruned {receipt['pruned_redirectors']} stale redirector(s)."
        )
        self.refresh()

    def refresh_source_control(self) -> None:
        if self._source_control_task is not None:
            return
        paths = [
            str(self.asset_tree.topLevelItem(index).data(0, ASSET_PATH_ROLE) or "")
            for index in range(self.asset_tree.topLevelItemCount())
        ]
        self.statusMessage.emit("Refreshing Perforce status for Content Browser assets…")
        self.vcs_button.setEnabled(False)
        task = _SourceControlTask(self.lifecycle, paths)
        task.signals.finished.connect(self._source_control_ready)
        self._source_control_task = task
        QThreadPool.globalInstance().start(task)

    def _source_control_ready(self, snapshot: object) -> None:
        self._source_control_cache = dict(snapshot) if isinstance(snapshot, dict) else {}
        self._source_control_task = None
        self.vcs_button.setEnabled(True)
        self.refresh()
        unavailable = bool(self._source_control_cache) and all(
            row.get("status") == "unavailable" for row in self._source_control_cache.values()
        )
        self.statusMessage.emit(
            "Perforce CLI is unavailable; source-control state is shown as Unavailable."
            if unavailable else f"Refreshed source-control state for {len(self._source_control_cache)} asset(s)."
        )

    def load_selected_vcs_history(self) -> None:
        item = self.asset_tree.currentItem()
        path = str(item.data(0, ASSET_PATH_ROLE) or "") if item is not None else ""
        if not path or self._perforce_task is not None:
            return
        self.statusMessage.emit(f"Loading Perforce history for {Path(path).name}…")
        self._start_perforce_task(
            "history", lambda: self.lifecycle.perforce_history(path, limit=50),
        )

    def show_perforce_changelists(self) -> None:
        if self._perforce_task is not None:
            return
        self.statusMessage.emit("Loading pending Perforce changelists…")
        self._start_perforce_task(
            "changelists", lambda: self.lifecycle.perforce_changelists(status="pending", limit=50),
        )

    def run_selected_perforce_action(self, action: str) -> None:
        paths = [
            str(item.data(0, ASSET_PATH_ROLE) or "")
            for item in self.asset_tree.selectedItems()
            if str(item.data(0, ASSET_PATH_ROLE) or "")
        ]
        if not paths or self._perforce_task is not None:
            return
        changelist = ""
        if action in {"edit", "add"}:
            changelist, accepted = QInputDialog.getText(
                self, "Perforce Changelist", "Pending changelist number (blank for default):",
            )
            if not accepted:
                return
        verb = {"edit": "check out", "add": "add", "revert": "revert"}.get(action, action)
        answer = QMessageBox.question(
            self, f"Perforce {verb.title()}",
            f"{verb.title()} {len(paths)} selected file(s)"
            + (f" in changelist {changelist}" if changelist else "") + "?",
        )
        if answer != QMessageBox.Yes:
            return
        self.statusMessage.emit(f"Running Perforce {verb}…")
        self._start_perforce_task(
            "action", lambda: self.lifecycle.perforce_action(
                paths, action, changelist=changelist, confirmed=True,
            ),
        )

    def _start_perforce_task(self, tag: str, operation: Callable[[], object]) -> None:
        task = _PerforceTask(tag, operation)
        task.signals.finished.connect(self._perforce_task_finished)
        self._perforce_task = task
        QThreadPool.globalInstance().start(task)

    def _perforce_task_finished(self, payload: object) -> None:
        self._perforce_task = None
        values = dict(payload) if isinstance(payload, dict) else {}
        error = str(values.get("error") or "")
        if error:
            QMessageBox.warning(self, "Perforce operation failed", error)
            self.statusMessage.emit(f"Perforce operation failed: {error}")
            return
        tag, result = str(values.get("tag") or ""), values.get("result")
        if tag == "history":
            self.vcs_history_tree.clear()
            for row in result or ():
                item = QTreeWidgetItem([
                    str(row.get("rev") or "—"), str(row.get("change") or "—"),
                    str(row.get("action") or "—"), str(row.get("user") or "—"),
                    str(row.get("desc") or "—"),
                ])
                self.vcs_history_tree.addTopLevelItem(item)
            self.statusMessage.emit(f"Loaded {self.vcs_history_tree.topLevelItemCount()} Perforce revision(s).")
        elif tag == "changelists":
            rows = list(result or ())
            lines = [
                f"{row.get('change', 'default')} — {row.get('user', '')} — {row.get('desc', '')}"
                for row in rows
            ]
            QMessageBox.information(
                self, "Pending Perforce Changelists", "\n".join(lines) if lines else "No pending changelists.",
            )
        elif tag == "action":
            receipt = dict(result or {})
            if int(receipt.get("returncode") or 0) != 0:
                QMessageBox.warning(self, "Perforce action failed", str(receipt.get("stderr") or receipt.get("stdout") or "Unknown error"))
            else:
                self.statusMessage.emit(f"Perforce {receipt.get('action')} completed for {len(receipt.get('paths') or ())} file(s).")
            self.refresh_source_control()
