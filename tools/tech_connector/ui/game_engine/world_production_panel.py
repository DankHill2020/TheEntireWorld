"""Discoverable build center for world-production assets."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import (
    AssetDatabase, WORLD_ASSET_TYPES, WorldAssetService, builtin_asset_type_registry,
    WorldBuildService,
)


_WORLD_TYPE_ORDER = (
    "tc.terrain", "tc.foliage_type", "tc.biome", "tc.navigation_mesh",
    "tc.lighting_scenario", "tc.data_layer", "tc.hlod_layer", "tc.world_partition",
)


class WorldProductionPanel(QWidget):
    """Creates, validates, and builds world assets without leaving the level workspace."""

    openRequested = Signal(str)
    statusMessage = Signal(str)

    def __init__(self, project_root: str | Path, database: AssetDatabase, parent=None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = builtin_asset_type_registry()
        self.service = WorldAssetService(self.project_root, database)
        self.build_service = WorldBuildService(self.project_root, database)
        root = QVBoxLayout(self)
        heading = QLabel("World Production", self)
        heading.setStyleSheet("font-weight: 650; font-size: 15px")
        root.addWidget(heading)
        root.addWidget(QLabel(
            "Terrain → foliage/biomes → navigation/lighting → Data Layers/HLOD → streaming cook",
            self,
        ))
        create_row = QHBoxLayout()
        self.type_combo = QComboBox(self)
        for type_id in _WORLD_TYPE_ORDER:
            descriptor = self.registry.require(type_id)
            self.type_combo.addItem(descriptor.display_name, type_id)
        create = QPushButton("+ Create", self)
        create.clicked.connect(self.create_asset)
        refresh = QPushButton("Refresh", self)
        refresh.clicked.connect(self.refresh)
        create_row.addWidget(self.type_combo, 1)
        create_row.addWidget(create)
        create_row.addWidget(refresh)
        root.addLayout(create_row)
        self.assets = QTreeWidget(self)
        self.assets.setHeaderLabels(["Asset", "Type", "Dependencies", "Build Status"])
        self.assets.setRootIsDecorated(False)
        self.assets.itemDoubleClicked.connect(lambda item, _column: self.openRequested.emit(str(item.data(0, Qt.UserRole) or "")))
        root.addWidget(self.assets, 1)
        actions = QHBoxLayout()
        for label, callback in (
            ("Open", self.open_selected), ("Validate", self.validate_selected),
            ("Build Selected", self.build_selected), ("Build All", self.build_all),
        ):
            button = QPushButton(label, self); button.clicked.connect(callback); actions.addWidget(button)
        root.addLayout(actions)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.refresh()

    def refresh(self) -> None:
        selected = self.selected_asset_id()
        self.assets.clear()
        counts: dict[str, int] = {}
        for record in self.database.list_assets():
            if record.asset_type not in WORLD_ASSET_TYPES:
                continue
            descriptor = self.registry.require(record.asset_type)
            issues = self.service.validate(record.asset_id)
            errors = sum(item.severity == "error" for item in issues)
            warnings = sum(item.severity == "warning" for item in issues)
            state = f"{errors} error(s)" if errors else (f"{warnings} warning(s)" if warnings else "Ready")
            item = QTreeWidgetItem([
                record.source_path.stem.split(".")[0], descriptor.display_name,
                str(len(self.database.dependencies(record.asset_id))), state,
            ])
            item.setData(0, Qt.UserRole, record.asset_id)
            if errors:
                item.setForeground(3, QColor("#ff6b6b"))
            self.assets.addTopLevelItem(item)
            counts[record.asset_type] = counts.get(record.asset_type, 0) + 1
            if record.asset_id == selected:
                self.assets.setCurrentItem(item)
        total = sum(counts.values())
        missing = [self.registry.require(type_id).display_name for type_id in _WORLD_TYPE_ORDER if not counts.get(type_id)]
        suffix = f" Missing: {', '.join(missing)}." if missing else " Full world-production stack present."
        self.summary.setText(f"{total} world asset(s).{suffix}")
        self.assets.resizeColumnToContents(0)
        self.assets.resizeColumnToContents(1)

    def selected_asset_id(self) -> str:
        item = self.assets.currentItem()
        return str(item.data(0, Qt.UserRole) or "") if item is not None else ""

    def create_asset(self) -> bool:
        type_id = str(self.type_combo.currentData() or "")
        descriptor = self.registry.require(type_id)
        name, accepted = QInputDialog.getText(self, f"Create {descriptor.display_name}", "Asset name", text=descriptor.display_name.replace(" ", ""))
        if not accepted or not name.strip():
            return False
        try:
            receipt = self.service.create(type_id, name.strip())
        except Exception as exc:
            self.statusMessage.emit(str(exc)); return False
        self.refresh()
        self._select(receipt.asset_id)
        self.openRequested.emit(receipt.asset_id)
        self.statusMessage.emit(receipt.message)
        return True

    def open_selected(self) -> bool:
        asset_id = self.selected_asset_id()
        if not asset_id:
            return False
        self.openRequested.emit(asset_id)
        return True

    def validate_selected(self) -> bool:
        asset_id = self.selected_asset_id()
        if not asset_id:
            return False
        issues = self.service.validate(asset_id)
        if not issues:
            message = "World asset is valid and ready to build."
        else:
            message = " • ".join(f"{item.severity.upper()}: {item.message}" for item in issues)
        self.statusMessage.emit(message)
        self.refresh()
        return not any(item.severity == "error" for item in issues)

    def build_selected(self) -> bool:
        asset_id = self.selected_asset_id()
        if not asset_id:
            return False
        try:
            artifact = self.service.compile(asset_id)
            record = self.database.asset(asset_id)
            built = self.build_service.build(asset_id) if record and record.asset_type in {"tc.terrain", "tc.navigation_mesh", "tc.lighting_scenario", "tc.hlod_layer", "tc.world_partition"} else None
        except Exception as exc:
            self.statusMessage.emit(str(exc)); return False
        detail = f"; {built.build_kind} {built.statistics}" if built is not None else ""
        self.statusMessage.emit(f"Built world runtime artifact: {artifact.path.name}{detail}")
        self.refresh()
        return True

    def build_all(self) -> bool:
        built = 0; failures: list[str] = []
        for record in self.database.list_assets():
            if record.asset_type not in WORLD_ASSET_TYPES:
                continue
            try:
                self.service.compile(record.asset_id)
                if record.asset_type in {"tc.terrain", "tc.navigation_mesh", "tc.lighting_scenario", "tc.hlod_layer", "tc.world_partition"}:
                    self.build_service.build(record.asset_id)
                built += 1
            except Exception as exc:
                failures.append(f"{record.source_path.name}: {exc}")
        self.refresh()
        if failures:
            self.statusMessage.emit(f"Built {built}; {len(failures)} failed. " + " | ".join(failures[:3]))
            return False
        self.statusMessage.emit(f"Built all {built} world-production assets.")
        return True

    def _select(self, asset_id: str) -> None:
        for index in range(self.assets.topLevelItemCount()):
            item = self.assets.topLevelItem(index)
            if str(item.data(0, Qt.UserRole) or "") == asset_id:
                self.assets.setCurrentItem(item); return


__all__ = ["WorldProductionPanel"]
