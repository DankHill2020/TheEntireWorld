"""Project asset browser with familiar create, import, filter, and inspect flows."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tech_connector.game_engine.assets import (
    AssetDatabase,
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


ASSET_ID_ROLE = Qt.UserRole + 1
ASSET_PATH_ROLE = Qt.UserRole + 2
ASSET_TYPE_ROLE = Qt.UserRole + 3
PROPERTY_KEY_ROLE = Qt.UserRole + 4
FOLDER_PATH_ROLE = Qt.UserRole + 5
TC_ASSET_MIME_TYPE = "application/x-tech-connector-asset"


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


class AssetBrowserWidget(QWidget):
    assetActivated = Signal(str, str, str)
    statusMessage = Signal(str)

    def __init__(
        self,
        project_root: str | Path,
        parent=None,
        *,
        database: AssetDatabase | None = None,
        registry: AssetTypeRegistry | None = None,
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
        self._build_ui()
        self.refresh()

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
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        title_row.addWidget(refresh_button)
        root.addLayout(title_row)

        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search assets by name, type, family, or path…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.apply_filter)
        filter_row.addWidget(self.search_edit, 1)
        self.family_button = QToolButton(self)
        self.family_button.setText("All Types")
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
        self.folder_combo.setToolTip("Limit the browser to a project folder and its descendants.")
        self.folder_combo.addItem("All Folders", "")
        self.folder_combo.currentIndexChanged.connect(
            lambda index: self.set_folder_filter(str(self.folder_combo.itemData(index) or ""))
        )
        self._folder_filter = ""
        filter_row.addWidget(self.folder_combo)
        root.addLayout(filter_row)

        navigation_row = QHBoxLayout()
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

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        folder_panel = QFrame(splitter)
        folder_layout = QVBoxLayout(folder_panel)
        folder_layout.setContentsMargins(0, 0, 5, 0)
        folder_layout.addWidget(QLabel("PROJECT FOLDERS"))
        self.folder_tree = QTreeWidget(folder_panel)
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setMinimumWidth(185)
        self.folder_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_tree.customContextMenuRequested.connect(self._show_folder_context_menu)
        self.folder_tree.itemSelectionChanged.connect(self._folder_tree_selection_changed)
        folder_layout.addWidget(self.folder_tree, 1)
        splitter.addWidget(folder_panel)

        self.asset_tree = _AssetTreeWidget(splitter)
        self.asset_tree.setHeaderLabels(["Name", "Type", "Status", "Path"])
        self.asset_tree.setIconSize(QSize(42, 42))
        self.asset_tree.setDragEnabled(True)
        self.asset_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.asset_tree.setAlternatingRowColors(True)
        self.asset_tree.setSortingEnabled(True)
        self.asset_tree.sortByColumn(0, Qt.AscendingOrder)
        self.asset_tree.itemSelectionChanged.connect(self._update_inspector)
        self.asset_tree.itemDoubleClicked.connect(lambda item, _column: self._activate_item(item))
        self.asset_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.asset_tree.customContextMenuRequested.connect(self._show_asset_context_menu)
        self.asset_tree.setStyleSheet(
            "QTreeWidget { background:#071018; alternate-background-color:#091722; color:#d7f7ff; border:1px solid #1a2938; }"
            "QTreeWidget::item { min-height:24px; } QTreeWidget::item:selected { background:#12324a; color:#69f0ae; }"
            "QHeaderView::section { background:#0b1118; color:#9cc7d8; border:0; padding:5px; }"
        )
        splitter.addWidget(self.asset_tree)

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
        self.property_tree.setHeaderLabels(["Property", "Value"])
        self.property_tree.setRootIsDecorated(False)
        self.property_tree.setAlternatingRowColors(True)
        self.property_tree.setMinimumHeight(130)
        self.property_tree.setToolTip("Double-click a value to edit it. JSON is accepted for lists and nested values.")
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
        self.reference_tree.setHeaderLabels(["Relationship", "Asset", "Type"])
        self.reference_tree.setMinimumHeight(150)
        inspector_layout.addWidget(self.reference_tree)
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
        self.undo_button = QPushButton("Undo Asset Operation")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self.undo_last_operation)
        footer.addWidget(self.undo_button)
        root.addLayout(footer)

    def _create_menu(self) -> QMenu:
        menu = QMenu(self)
        family_menus: dict[str, QMenu] = {}
        for descriptor in self.registry.all(creatable=True):
            family_menu = family_menus.get(descriptor.family)
            if family_menu is None:
                family_menu = menu.addMenu(descriptor.family)
                family_menus[descriptor.family] = family_menu
            action = family_menu.addAction(descriptor.display_name)
            action.setToolTip(f"Create {descriptor.display_name}")
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
            action = family_menu.addAction(descriptor.display_name)
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

    def refresh(self) -> None:
        try:
            self.database.scan_changes()
        except Exception as exc:
            self.statusMessage.emit(f"Asset scan warning: {exc}")
        records = {str(record.source_path).casefold(): record for record in self.database.list_assets()}
        discovered: dict[str, tuple[Path, str, str, str]] = {}
        if self.project_root.is_dir():
            for path in self.project_root.rglob("*"):
                if not path.is_file() or path.name.endswith(".tcmeta") or ".tech_connector" in path.parts:
                    continue
                descriptor = self.registry.infer(path)
                if descriptor is None:
                    continue
                key = str(path.resolve()).casefold()
                record = records.get(key)
                discovered[key] = (
                    path.resolve(), descriptor.type_id,
                    record.status.title() if record else "Source",
                    record.asset_id if record else "",
                )
        for key, record in records.items():
            descriptor = self.registry.descriptor(record.asset_type)
            type_id = descriptor.type_id if descriptor else record.asset_type
            discovered.setdefault(key, (record.source_path, type_id, record.status.title(), record.asset_id))

        folders: set[str] = set()
        if self.project_root.is_dir():
            for directory in self.project_root.rglob("*"):
                if not directory.is_dir() or ".tech_connector" in directory.parts:
                    continue
                try: folders.add(directory.relative_to(self.project_root).as_posix())
                except ValueError: pass
        for path, _type_id, _status, _asset_id in discovered.values():
            try:
                relative_parent = path.relative_to(self.project_root).parent
            except ValueError:
                continue
            parts = relative_parent.parts
            for depth in range(1, len(parts) + 1):
                folders.add(Path(*parts[:depth]).as_posix())
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

        self.asset_tree.setSortingEnabled(False)
        self.asset_tree.clear()
        for path, type_id, status, asset_id in discovered.values():
            descriptor = self.registry.descriptor(type_id)
            display_type = descriptor.display_name if descriptor else type_id
            try:
                relative = path.relative_to(self.project_root).as_posix()
            except ValueError:
                relative = str(path)
            item = QTreeWidgetItem([path.name, display_type, status, relative])
            item.setData(0, ASSET_ID_ROLE, asset_id)
            item.setData(0, ASSET_PATH_ROLE, str(path))
            item.setData(0, ASSET_TYPE_ROLE, type_id)
            if descriptor is not None:
                item.setIcon(0, self.thumbnails.icon(path, descriptor))
            item.setToolTip(0, f"{display_type}\n{relative}\n{asset_id or 'Not imported into the TC asset database'}")
            self.asset_tree.addTopLevelItem(item)
        self.asset_tree.setSortingEnabled(True)
        self.asset_tree.resizeColumnToContents(0)
        self.asset_tree.resizeColumnToContents(1)
        self.asset_tree.resizeColumnToContents(2)
        self.apply_filter()
        self._update_undo_button()

    def set_family_filter(self, family: str) -> None:
        self._family_filter = str(family)
        self.family_button.setText(family or "All Types")
        self.apply_filter()

    def set_folder_filter(self, folder: str) -> None:
        self._folder_filter = str(folder).replace("\\", "/").strip("/")
        selected_index = self.folder_combo.findData(self._folder_filter)
        if selected_index >= 0 and self.folder_combo.currentIndex() != selected_index:
            self.folder_combo.blockSignals(True)
            self.folder_combo.setCurrentIndex(selected_index)
            self.folder_combo.blockSignals(False)
        self.breadcrumb_label.setText("Project / " + (self._folder_filter or "All Assets"))
        self.up_folder_button.setEnabled(bool(self._folder_filter))
        self.apply_filter()

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
        query = self.search_edit.text().strip().casefold()
        visible = 0
        for index in range(self.asset_tree.topLevelItemCount()):
            item = self.asset_tree.topLevelItem(index)
            descriptor = self.registry.descriptor(str(item.data(0, ASSET_TYPE_ROLE) or ""))
            family = descriptor.family if descriptor else ""
            haystack = " ".join(item.text(column) for column in range(4)).casefold() + " " + family.casefold()
            item_folder = Path(item.text(3)).parent.as_posix()
            folder_matches = (
                not self._folder_filter
                or item_folder.casefold() == self._folder_filter.casefold()
                or item_folder.casefold().startswith(self._folder_filter.casefold() + "/")
            )
            matches = (not query or all(token in haystack for token in query.split())) and (
                not self._family_filter or family == self._family_filter
            ) and folder_matches
            item.setHidden(not matches)
            visible += int(matches)
        self.summary_label.setText(f"{visible} visible asset{'s' if visible != 1 else ''}  •  {self.asset_tree.topLevelItemCount()} discovered")

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
        self.property_tree.clear()
        self.save_properties_button.setEnabled(False)
        if item is None:
            self.inspector_title.setText("Nothing selected")
            self.inspector_type.setText("Select an asset to view its type and import state.")
            self.inspector_details.clear()
            return
        type_id = str(item.data(0, ASSET_TYPE_ROLE) or "")
        descriptor = self.registry.descriptor(type_id)
        self.inspector_title.setText(item.text(0))
        self.inspector_type.setText(
            f"{descriptor.display_name if descriptor else type_id}  •  {descriptor.family if descriptor else 'Unregistered'}"
        )
        hot_reload = descriptor.hot_reload_class.replace("_", " ").title() if descriptor else "Unknown"
        self.inspector_details.setText(
            f"Status: {item.text(2)}\nPath: {item.text(3)}\n"
            f"Asset ID: {asset_id or 'Not registered'}\nLive update: {hot_reload}"
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
                payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                payload["properties"] = properties
                record.source_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                metadata = record.metadata
            self.database.register_asset(
                record.source_path, record.asset_type, asset_id=record.asset_id,
                metadata=metadata, dependencies=self.database.dependency_edges(record.asset_id),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Property save failed", str(exc))
            return
        self.statusMessage.emit(f"Saved properties for {record.source_path.name}; hot reload is ready.")
        self.refresh()

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
            menu.addSeparator()
        create_menu = menu.addMenu("Create Asset")
        menu._tc_child_menus = [create_menu]
        self._populate_create_submenu(create_menu)
        menu.addAction("Import Assets…", self.import_assets)
        menu.addAction("New Folder…", self.create_folder)
        if selected:
            menu.addSeparator()
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
            menu.addAction("Fix Legacy Paths", self.fix_selected_legacy_paths).setEnabled(bool(asset_id))
            menu.addSeparator()
            delete = menu.addAction("Delete…", self.delete_selected); delete.setEnabled(bool(asset_id))
        menu.addSeparator()
        menu.addAction("Refresh", self.refresh)
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
        menu.addSeparator(); menu.addAction("Refresh", self.refresh)
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
        self.import_asset_paths(paths)

    def import_asset_paths(self, paths: list[str] | tuple[str, ...], *, folder: str = "") -> tuple[str, ...]:
        target_folder = folder or self.current_content_folder()
        messages = []
        errors = []
        for path in paths:
            try:
                receipt = self.operations.import_asset(path, folder=target_folder)
                messages.append(receipt.message)
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")
        self.refresh()
        self.set_folder_filter(target_folder)
        if messages:
            self.statusMessage.emit(f"Imported {len(messages)} asset(s).")
        if errors:
            QMessageBox.warning(self, "Some assets were not imported", "\n".join(errors))
        return tuple(messages)

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

    def _select_asset_id(self, asset_id: str) -> None:
        for index in range(self.asset_tree.topLevelItemCount()):
            item = self.asset_tree.topLevelItem(index)
            if str(item.data(0, ASSET_ID_ROLE) or "") == str(asset_id):
                self.asset_tree.setCurrentItem(item); self.asset_tree.scrollToItem(item); return

    def _selected_asset_id(self) -> str:
        item = self.asset_tree.currentItem()
        return str(item.data(0, ASSET_ID_ROLE) or "") if item is not None else ""

    def reimport_selected(self) -> None:
        asset_id = self._selected_asset_id()
        if not asset_id:
            return
        try:
            receipt = self.operations.reimport_asset(asset_id)
        except Exception as exc:
            QMessageBox.warning(self, "Reimport failed", str(exc))
            return
        self.statusMessage.emit(receipt.message)
        self.refresh()

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
        reports = [self.operations.validate_asset(asset_id) for asset_id in asset_ids]
        issues = [(report, issue) for report in reports for issue in report.issues]
        if not issues:
            QMessageBox.information(self, "Asset Validation", f"{len(reports)} asset(s) passed validation.")
            return
        lines = []
        for report, issue in issues:
            record = self.database.asset(report.asset_id)
            lines.append(f"[{issue.severity.upper()}] {record.source_path.name if record else report.asset_id}: {issue.message}")
        QMessageBox.warning(self, "Asset Validation", "\n".join(lines))

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
        try:
            receipt = self.production.cook_manifest(asset_ids)
        except Exception as exc:
            QMessageBox.warning(self, "Cook failed", str(exc))
            return
        self.statusMessage.emit(
            f"Cooked {len(receipt.asset_ids)} dependency-closed asset(s) for {receipt.platform}/{receipt.quality}."
        )
        QMessageBox.information(
            self, "Cook Manifest Ready",
            f"Assets: {len(receipt.asset_ids)}\nSource size: {receipt.source_bytes / (1024 * 1024):.2f} MiB\n"
            f"Hot reload: {', '.join(receipt.hot_reload_classes)}\nArtifact: {receipt.artifact.path}",
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
