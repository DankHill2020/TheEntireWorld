"""Reusable searchable asset-reference picker for engine properties."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout,
)

from tech_connector.game_engine.assets import AssetDatabase, AssetTypeRegistry, builtin_asset_type_registry
from tech_connector.game_engine.assets.content_browser_lifecycle_service import ContentBrowserLifecycleService
from tech_connector.ui.game_engine.asset_thumbnail_service import AssetThumbnailService


class AssetPickerDialog(QDialog):
    """Search project assets by name, path, type, favorites, or recency."""

    ASSET_ID_ROLE = Qt.UserRole + 1
    locateRequested = Signal(str)
    inspectRequested = Signal(str)

    def __init__(
        self, project_root: str | Path, database: AssetDatabase, *,
        registry: AssetTypeRegistry | None = None, allowed_types: tuple[str, ...] = (),
        current_asset_id: str = "", recent_asset_ids: tuple[str, ...] = (),
        context_asset_id: str = "",
        title: str = "Choose Asset", parent=None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = registry or builtin_asset_type_registry()
        self.allowed_types = tuple(str(value) for value in allowed_types if str(value))
        self.recent_asset_ids = tuple(str(value) for value in recent_asset_ids if str(value))
        self.current_asset_id = str(current_asset_id)
        self.context_asset_id = str(context_asset_id)
        self.selected_asset_id = ""
        self.lifecycle = ContentBrowserLifecycleService(self.project_root, self.database, self.registry)
        self.thumbnails = AssetThumbnailService()
        self.setWindowTitle(title)
        self.resize(680, 520)
        root = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setAccessibleName("Search compatible assets")
        self.search.setPlaceholderText("Search by name, path, or asset type…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.accept_selected)
        filters.addWidget(self.search, 1)
        self.scope = QComboBox(self)
        self.scope.setAccessibleName("Asset picker scope")
        self.scope.addItem("All compatible", "all")
        self.scope.addItem("Recent", "recent")
        self.scope.addItem("Favorites", "favorites")
        self.scope.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.scope)
        root.addLayout(filters)
        self.compatibility = QLabel(self)
        self.compatibility.setWordWrap(True)
        root.addWidget(self.compatibility)
        self.assets = QListWidget(self)
        self.assets.setAccessibleName("Compatible project assets")
        self.assets.setIconSize(QSize(56, 56)); self.assets.setSpacing(3)
        self.assets.itemDoubleClicked.connect(lambda _item: self.accept_selected())
        self.assets.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.assets, 1)
        self.details = QLabel("Select an asset to inspect its reference.", self)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.details)
        buttons = QHBoxLayout()
        clear = QPushButton("Clear Reference", self)
        clear.clicked.connect(self.clear_reference)
        buttons.addWidget(clear)
        self.favorite_button = QPushButton("Add to Favorites", self); self.favorite_button.clicked.connect(self.toggle_selected_favorite); buttons.addWidget(self.favorite_button)
        self.locate_button = QPushButton("Locate", self); self.locate_button.clicked.connect(self.locate_selected); buttons.addWidget(self.locate_button)
        self.inspect_button = QPushButton("Open", self); self.inspect_button.clicked.connect(self.inspect_selected); buttons.addWidget(self.inspect_button)
        self.context_button = QPushButton("Use Content Browser Selection", self); self.context_button.clicked.connect(self.use_context_asset); buttons.addWidget(self.context_button)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel", self); cancel.clicked.connect(self.reject); buttons.addWidget(cancel)
        self.choose_button = QPushButton("Use Selected Asset", self)
        self.choose_button.setDefault(True)
        self.choose_button.clicked.connect(self.accept_selected)
        buttons.addWidget(self.choose_button)
        root.addLayout(buttons)
        self.refresh()
        self.select_asset(current_asset_id)

    def refresh(self, _value=None) -> None:
        current = str((self.assets.currentItem().data(self.ASSET_ID_ROLE) if self.assets.currentItem() else "") or "")
        query = self.search.text().strip().casefold()
        favorites = self.lifecycle.collection("Favorites")
        favorite_ids = set(favorites.asset_ids) if favorites else set()
        favorite_only = self.scope.currentData() == "favorites"
        recent_only = self.scope.currentData() == "recent"
        self.assets.clear()
        records = list(self.database.list_assets())
        recent_order = {asset_id: index for index, asset_id in enumerate(self.recent_asset_ids)}
        records.sort(key=lambda record: (recent_order.get(record.asset_id, len(recent_order)), record.source_path.name.casefold()))
        for record in records:
            if self.allowed_types and record.asset_type not in self.allowed_types:
                continue
            if favorite_only and record.asset_id not in favorite_ids:
                continue
            if recent_only and record.asset_id not in recent_order:
                continue
            descriptor = self.registry.descriptor(record.asset_type)
            type_name = descriptor.display_name if descriptor else record.asset_type
            try: relative = record.source_path.relative_to(self.project_root).as_posix()
            except ValueError: relative = str(record.source_path)
            raw_tags = record.metadata.get("tags") or ()
            tags = [value.strip() for value in raw_tags.split(",")] if isinstance(raw_tags, str) else [str(value) for value in raw_tags]
            haystack = f"{record.source_path.stem} {relative} {record.asset_type} {type_name} {' '.join(tags)}".casefold()
            if query and query not in haystack:
                continue
            star = "★ " if record.asset_id in favorite_ids else ""
            item = QListWidgetItem(f"{star}{record.source_path.stem}\n{type_name}  •  {relative}")
            if descriptor is not None: item.setIcon(self.thumbnails.icon(record.source_path, descriptor, size=56))
            item.setData(self.ASSET_ID_ROLE, record.asset_id)
            item.setData(Qt.AccessibleDescriptionRole, f"{type_name}. {relative}")
            self.assets.addItem(item)
            if record.asset_id == current:
                self.assets.setCurrentItem(item)
        allowed = ", ".join(self.allowed_types) if self.allowed_types else "all registered asset types"
        self.compatibility.setText(f"Showing {self.assets.count()} compatible assets • {allowed}")
        self.choose_button.setEnabled(self.assets.currentItem() is not None)
        context = self.database.asset(self.context_asset_id) if self.context_asset_id else None
        context_compatible = bool(context and (not self.allowed_types or context.asset_type in self.allowed_types))
        self.context_button.setEnabled(context_compatible)
        self.context_button.setToolTip(f"Use {context.source_path.name}" if context_compatible else "Select a compatible asset in the Content Browser first")
        self._selection_changed()

    def select_asset(self, asset_id: str) -> bool:
        for index in range(self.assets.count()):
            item = self.assets.item(index)
            if str(item.data(self.ASSET_ID_ROLE) or "") == str(asset_id):
                self.assets.setCurrentItem(item)
                self.assets.scrollToItem(item)
                return True
        return False

    def accept_selected(self) -> bool:
        item = self.assets.currentItem()
        if item is None:
            return False
        self.selected_asset_id = str(item.data(self.ASSET_ID_ROLE) or "")
        self.accept()
        return True

    def clear_reference(self) -> None:
        self.selected_asset_id = ""
        self.accept()

    def use_context_asset(self) -> bool:
        record = self.database.asset(self.context_asset_id) if self.context_asset_id else None
        if record is None or (self.allowed_types and record.asset_type not in self.allowed_types): return False
        self.selected_asset_id = record.asset_id; self.accept(); return True

    def locate_selected(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        self.locateRequested.emit(asset_id); return True

    def inspect_selected(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        self.inspectRequested.emit(asset_id); return True

    def toggle_selected_favorite(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        favorites = self.lifecycle.collection("Favorites")
        if favorites is not None and asset_id in favorites.asset_ids: self.lifecycle.remove_from_collection("Favorites", (asset_id,))
        elif favorites is None: self.lifecycle.save_collection("Favorites", asset_ids=(asset_id,))
        else: self.lifecycle.add_to_collection("Favorites", (asset_id,))
        self.refresh(); self.select_asset(asset_id); return True

    def _selected_asset_id(self) -> str:
        item = self.assets.currentItem(); return str(item.data(self.ASSET_ID_ROLE) or "") if item else ""

    def _selection_changed(self) -> None:
        item = self.assets.currentItem()
        asset_id = str(item.data(self.ASSET_ID_ROLE) or "") if item else ""
        record = self.database.asset(asset_id) if asset_id else None
        self.choose_button.setEnabled(record is not None)
        favorites = self.lifecycle.collection("Favorites"); is_favorite = bool(record and favorites and record.asset_id in favorites.asset_ids)
        self.favorite_button.setEnabled(record is not None); self.favorite_button.setText("Remove from Favorites" if is_favorite else "Add to Favorites")
        self.locate_button.setEnabled(record is not None); self.inspect_button.setEnabled(record is not None)
        raw_tags = record.metadata.get("tags") or () if record else ()
        tags = ", ".join(raw_tags) if isinstance(raw_tags, (list, tuple)) else str(raw_tags)
        self.details.setText(
            f"Asset ID: {record.asset_id}\nType: {record.asset_type}\nSource: {record.source_path}\nRevision: {record.revision}  •  Size: {record.size / 1024:.1f} KiB"
            + (f"\nTags: {tags}" if tags else "")
            if record else "Select an asset to inspect its reference."
        )


__all__ = ["AssetPickerDialog"]
