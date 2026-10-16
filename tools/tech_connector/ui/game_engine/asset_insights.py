"""Dependency and audit surfaces for production asset libraries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from tech_connector.game_engine.assets import (
    AssetDatabase, AssetDependencyGraphService, AssetOperationsService, AssetTypeRegistry,
    builtin_asset_type_registry,
)


ASSET_ID_ROLE = Qt.UserRole + 1
ISSUE_KIND_ROLE = Qt.UserRole + 2


class AssetDependencyExplorer(QWidget):
    openRequested = Signal(str)
    locateRequested = Signal(str)
    assetsChanged = Signal()
    statusMessage = Signal(str)

    def __init__(self, project_root: str | Path, database: AssetDatabase, registry: AssetTypeRegistry | None = None, parent=None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve(); self.database = database; self.registry = registry or builtin_asset_type_registry(); self.asset_id = ""
        self.graphs = AssetDependencyGraphService(self.project_root, database); self.operations = AssetOperationsService(self.project_root, database, self.registry); self._graph_nodes = {}
        root = QVBoxLayout(self)
        self.heading = QLabel("Select an asset to inspect dependencies", self); self.heading.setStyleSheet("font-size:15px; font-weight:700;"); root.addWidget(self.heading)
        self.summary = QLabel(self); self.summary.setWordWrap(True); root.addWidget(self.summary)
        filters = QHBoxLayout(); filters.addWidget(QLabel("Graph:", self)); self.scope = QComboBox(self); self.scope.addItem("Dependencies + Referencers", True); self.scope.addItem("Dependencies only", False); self.scope.currentIndexChanged.connect(self.refresh); filters.addWidget(self.scope); filters.addWidget(QLabel("Depth:", self)); self.depth = QSpinBox(self); self.depth.setRange(1, 64); self.depth.setValue(16); self.depth.setAccessibleName("Dependency graph maximum depth"); self.depth.valueChanged.connect(self.refresh); filters.addWidget(self.depth); filters.addStretch(1); root.addLayout(filters)
        self.tree = QTreeWidget(self); self.tree.setAccessibleName("Asset dependency graph"); self.tree.setHeaderLabels(["Relationship", "Asset", "Type", "Source", "Derived", "Package", "Path"]); self.tree.itemDoubleClicked.connect(lambda _item, _column: self.open_selected()); root.addWidget(self.tree, 1)
        replace = QHBoxLayout(); replace.addWidget(QLabel("Replace references with:", self)); self.replacement = QComboBox(self); self.replacement.setAccessibleName("Replacement asset"); self.replacement.currentIndexChanged.connect(lambda _index: self._selection_changed()); replace.addWidget(self.replacement, 1); self.preview_replace_button = QPushButton("Preview", self); self.preview_replace_button.clicked.connect(lambda: self.preview_replacement()); replace.addWidget(self.preview_replace_button); self.replace_button = QPushButton("Replace References", self); self.replace_button.clicked.connect(lambda: self.replace_references()); replace.addWidget(self.replace_button); self.delete_button = QPushButton("Safe Delete…", self); self.delete_button.clicked.connect(lambda: self.delete_safely()); replace.addWidget(self.delete_button); root.addLayout(replace)
        actions = QHBoxLayout(); self.open_button = QPushButton("Open", self); self.open_button.clicked.connect(self.open_selected); actions.addWidget(self.open_button); self.locate_button = QPushButton("Locate in Assets", self); self.locate_button.clicked.connect(self.locate_selected); actions.addWidget(self.locate_button); actions.addStretch(1); self.undo_button = QPushButton("Undo Asset Action", self); self.undo_button.clicked.connect(self.undo_last_operation); actions.addWidget(self.undo_button); root.addLayout(actions)
        self.tree.itemSelectionChanged.connect(self._selection_changed); self._selection_changed()

    def set_asset(self, asset_id: str) -> bool:
        record = self.database.asset(str(asset_id)); self.tree.clear(); self.asset_id = str(asset_id)
        if record is None:
            self.heading.setText("Asset unavailable"); self.summary.setText("The selected asset is no longer registered."); self._selection_changed(); return False
        self.heading.setText(f"Dependencies — {record.source_path.name}")
        graph = self.graphs.analyze(record.asset_id, include_referencers=bool(self.scope.currentData()), max_depth=self.depth.value())
        self._graph_nodes = {node.asset_id: node for node in graph.nodes}
        unique_ids = {record.asset_id}; cycles: set[str] = set()
        dependencies = QTreeWidgetItem(["Uses", "Dependencies", "", "", ""]); dependencies.setFlags(dependencies.flags() & ~Qt.ItemIsSelectable); self.tree.addTopLevelItem(dependencies)
        self._append_dependency_children(dependencies, record.asset_id, unique_ids, {record.asset_id}, cycles, 0)
        referencers = QTreeWidgetItem(["Used by", "Referencers", "", "", ""]); referencers.setFlags(referencers.flags() & ~Qt.ItemIsSelectable); self.tree.addTopLevelItem(referencers)
        if bool(self.scope.currentData()):
            for owner_id, kind in self.database.referencer_edges(record.asset_id): self._append_record(referencers, owner_id, f"Used by · {kind}", unique_ids)
        dependencies.setExpanded(True); referencers.setExpanded(True)
        self.summary.setText(f"{max(0, len(graph.nodes) - 1)} dependency/referencer asset(s) • {self._format_size(graph.source_bytes)} source • {self._format_size(graph.derived_bytes)} derived • {self._format_size(graph.package_bytes)} package contribution" + (f" • {len(graph.cycles)} circular dependency group(s)" if graph.cycles else " • no cycles"))
        self._refresh_replacements(record.asset_type)
        self._selection_changed(); return True

    def refresh(self, _value=None) -> bool:
        return self.set_asset(self.asset_id) if self.asset_id else False

    def _append_dependency_children(self, parent: QTreeWidgetItem, owner_id: str, unique_ids: set[str], ancestry: set[str], cycles: set[str], depth: int) -> None:
        if depth >= self.depth.value():
            return
        for dependency_id, kind in self.database.dependency_edges(owner_id):
            child = self._append_record(parent, dependency_id, f"Depends on · {kind}", unique_ids)
            if dependency_id in ancestry:
                child.setText(0, f"Cycle · {kind}"); cycles.add(dependency_id); continue
            self._append_dependency_children(child, dependency_id, unique_ids, {*ancestry, dependency_id}, cycles, depth + 1)

    def _append_record(self, parent: QTreeWidgetItem, asset_id: str, relationship: str, unique_ids: set[str]) -> QTreeWidgetItem:
        record = self.database.asset(asset_id); unique_ids.add(asset_id)
        if record is None:
            item = QTreeWidgetItem([relationship, asset_id, "Missing", "—", "—", "—", "Unavailable"])
        else:
            descriptor = self.registry.descriptor(record.asset_type)
            try: relative = record.source_path.relative_to(self.project_root).as_posix()
            except ValueError: relative = str(record.source_path)
            node = self._graph_nodes.get(asset_id); derived = int(node.derived_bytes) if node is not None else 0
            item = QTreeWidgetItem([relationship, record.source_path.name, descriptor.display_name if descriptor else record.asset_type, self._format_size(record.size), self._format_size(derived), self._format_size(int(record.size) + derived), relative])
        item.setData(0, ASSET_ID_ROLE, asset_id); parent.addChild(item); return item

    def _refresh_replacements(self, type_id: str) -> None:
        previous = str(self.replacement.currentData() or "")
        self.replacement.blockSignals(True); self.replacement.clear(); self.replacement.addItem("Choose a compatible asset…", "")
        for record in self.database.list_assets():
            if record.asset_type == type_id and record.asset_id != self.asset_id:
                self.replacement.addItem(record.source_path.name, record.asset_id)
        index = self.replacement.findData(previous)
        if index >= 0: self.replacement.setCurrentIndex(index)
        self.replacement.blockSignals(False)

    def preview_replacement(self, *, show_dialog: bool = True) -> bool:
        replacement_id = str(self.replacement.currentData() or "")
        if not self.asset_id or not replacement_id: return False
        plan = self.operations.plan_reference_replacement(self.asset_id, replacement_id)
        message = f"{len(plan.referencers)} referencing asset(s); {plan.authored_replacements} authored value(s) will change." + (f" Blocked: {' '.join(plan.blockers)}" if plan.blockers else " Ready to replace as one undoable operation.")
        self.statusMessage.emit(message)
        if show_dialog: QMessageBox.information(self, "Reference Replacement Preview", message)
        return plan.can_execute

    def replace_references(self, *, confirm: bool = True) -> bool:
        replacement_id = str(self.replacement.currentData() or "")
        if not self.asset_id or not replacement_id: return False
        plan = self.operations.plan_reference_replacement(self.asset_id, replacement_id)
        if plan.blockers:
            self.statusMessage.emit(" ".join(plan.blockers)); return False
        if confirm and QMessageBox.question(self, "Replace Asset References", f"Replace references in {len(plan.referencers)} asset(s)? This can be undone.") != QMessageBox.Yes: return False
        receipt = self.operations.replace_asset_references(self.asset_id, replacement_id)
        self.assetsChanged.emit(); self.refresh(); self.statusMessage.emit(f"Replaced references in {len(receipt.updated_assets)} asset(s).")
        return True

    def delete_safely(self, *, confirm: bool = True) -> bool:
        if not self.asset_id: return False
        record = self.database.asset(self.asset_id)
        if record is None: return False
        referencers = self.database.referencers(self.asset_id); replacement_id = str(self.replacement.currentData() or "")
        if referencers and not replacement_id:
            self.statusMessage.emit("Choose a compatible replacement before deleting an asset that is in use."); return False
        if confirm and QMessageBox.question(self, "Safe Delete Asset", f"Move {record.source_path.name} to recoverable project trash?") != QMessageBox.Yes: return False
        receipt = self.operations.delete_asset(self.asset_id, replacement_asset_id=replacement_id)
        self.assetsChanged.emit(); self.tree.clear(); self.asset_id = ""; self.heading.setText("Asset moved to project trash"); self.summary.setText(f"{Path(receipt.original_path).name} can be restored with Undo."); self.statusMessage.emit(self.summary.text()); self._selection_changed()
        return True

    def undo_last_operation(self) -> bool:
        if not self.operations.can_undo: return False
        result = self.operations.undo_last(); restored_id = str(getattr(result, "asset_id", "") or "")
        self.assetsChanged.emit()
        if restored_id and self.database.asset(restored_id) is not None: self.set_asset(restored_id)
        elif self.asset_id: self.refresh()
        self.statusMessage.emit("Undid the last Dependency Explorer asset action."); self._selection_changed()
        return True

    @staticmethod
    def _format_size(size: int) -> str:
        value = int(size)
        return f"{value / (1024 * 1024):.2f} MiB" if value >= 1024 * 1024 else f"{value / 1024:.1f} KiB"

    def _selected_asset_id(self) -> str:
        item = self.tree.currentItem(); return str(item.data(0, ASSET_ID_ROLE) or "") if item else ""

    def open_selected(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        self.openRequested.emit(asset_id); return True

    def locate_selected(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        self.locateRequested.emit(asset_id); return True

    def _selection_changed(self) -> None:
        enabled = bool(self._selected_asset_id()); root_enabled = bool(self.asset_id); replacement_enabled = root_enabled and bool(self.replacement.currentData())
        self.open_button.setEnabled(enabled); self.locate_button.setEnabled(enabled); self.preview_replace_button.setEnabled(replacement_enabled); self.replace_button.setEnabled(replacement_enabled); self.delete_button.setEnabled(root_enabled); self.undo_button.setEnabled(self.operations.can_undo)


class _AuditSignals(QObject):
    finished = Signal(object)


class _AuditTask(QRunnable):
    def __init__(self, operation) -> None:
        super().__init__(); self.operation = operation; self.signals = _AuditSignals()
    def run(self) -> None:
        try: self.signals.finished.emit({"rows": self.operation(), "error": ""})
        except Exception as exc: self.signals.finished.emit({"rows": [], "error": str(exc)})


class AssetAuditDashboard(QWidget):
    openRequested = Signal(str)
    locateRequested = Signal(str)
    statusMessage = Signal(str)
    busyChanged = Signal(bool, str)
    completed = Signal(bool, str)
    dependencyRequested = Signal(str)
    assetsChanged = Signal()

    def __init__(self, project_root: str | Path, database: AssetDatabase, registry: AssetTypeRegistry | None = None, parent=None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve(); self.database = database; self.registry = registry or builtin_asset_type_registry(); self.operations = AssetOperationsService(self.project_root, database, self.registry); self._rows: list[dict[str, Any]] = []; self._task = None
        root = QVBoxLayout(self); heading = QHBoxLayout(); title = QLabel("Asset Audit", self); title.setStyleSheet("font-size:15px; font-weight:700;"); heading.addWidget(title); heading.addStretch(1); run = QPushButton("Run Audit", self); run.clicked.connect(self.refresh_async); heading.addWidget(run); root.addLayout(heading)
        filters = QHBoxLayout(); self.search = QLineEdit(self); self.search.setPlaceholderText("Filter issues, assets, types, or paths…"); self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.apply_filter); filters.addWidget(self.search, 1); self.severity = QComboBox(self); self.severity.addItem("All findings", ""); self.severity.addItem("Errors", "error"); self.severity.addItem("Warnings", "warning"); self.severity.addItem("Information", "info"); self.severity.currentIndexChanged.connect(self.apply_filter); filters.addWidget(self.severity); root.addLayout(filters)
        self.summary = QLabel("Audit has not run yet.", self); root.addWidget(self.summary)
        self.tree = QTreeWidget(self); self.tree.setAccessibleName("Asset audit findings"); self.tree.setHeaderLabels(["Severity", "Asset", "Finding", "Type", "Size", "Path"]); self.tree.itemDoubleClicked.connect(lambda _item, _column: self.open_selected()); root.addWidget(self.tree, 1)
        actions = QHBoxLayout(); self.open_button = QPushButton("Open", self); self.open_button.clicked.connect(self.open_selected); actions.addWidget(self.open_button); self.locate_button = QPushButton("Locate", self); self.locate_button.clicked.connect(self.locate_selected); actions.addWidget(self.locate_button); self.dependencies_button = QPushButton("Dependencies", self); self.dependencies_button.clicked.connect(self.show_dependencies); actions.addWidget(self.dependencies_button); actions.addStretch(1); self.repair_button = QPushButton("Repair Sidecar", self); self.repair_button.setToolTip("Recreate the selected asset's missing stable-identity metadata sidecar."); self.repair_button.clicked.connect(self.repair_selected_metadata); actions.addWidget(self.repair_button); self.trash_button = QPushButton("Move Unused to Trash", self); self.trash_button.setToolTip("Move an unreferenced asset into recoverable project trash."); self.trash_button.clicked.connect(lambda: self.move_selected_unused_to_trash()); actions.addWidget(self.trash_button); root.addLayout(actions); self.tree.itemSelectionChanged.connect(self._selection_changed); self._selection_changed()

    def refresh_async(self) -> bool:
        if self._task is not None: return False
        task = _AuditTask(self._collect); task.signals.finished.connect(self._finished); self._task = task; self.summary.setText("Auditing assets in the background…"); self.busyChanged.emit(True, "Auditing assets"); QThreadPool.globalInstance().start(task); return True

    def _collect(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        records = self.database.list_assets(); protected_types = {"tc.level", "tc.project_settings", "tc.build_profile", "tc.game_ruleset"}
        for record in records:
            descriptor = self.registry.descriptor(record.asset_type); display_type = descriptor.display_name if descriptor else record.asset_type
            try: relative = record.source_path.relative_to(self.project_root).as_posix()
            except ValueError: relative = str(record.source_path)
            base = {"asset_id": record.asset_id, "name": record.source_path.name, "type": display_type, "type_id": record.asset_type, "size": int(record.size), "path": relative}
            for issue in self.operations.validate_asset(record.asset_id).issues: rows.append(base | {"severity": issue.severity, "kind": issue.code, "message": issue.message})
            if record.asset_type not in protected_types and not self.database.referencers(record.asset_id): rows.append(base | {"severity": "info", "kind": "unused", "message": "No registered asset directly references this asset."})
            if int(record.size) >= 50 * 1024 * 1024: rows.append(base | {"severity": "warning", "kind": "large", "message": "Source asset exceeds 50 MiB; review streaming, compression, or LOD policy."})
        return rows

    def _finished(self, payload: object) -> None:
        self._task = None; self.busyChanged.emit(False, ""); result = dict(payload) if isinstance(payload, dict) else {}; error = str(result.get("error") or "")
        if error:
            self.summary.setText(f"Audit failed: {error}"); self.statusMessage.emit(self.summary.text()); self.completed.emit(False, self.summary.text()); return
        self._rows = list(result.get("rows") or ()); self.apply_filter(); message = f"Asset audit complete • {len(self._rows)} finding(s)."; self.statusMessage.emit(message); self.completed.emit(True, message)

    def apply_filter(self, _value=None) -> None:
        query = self.search.text().strip().casefold(); severity = str(self.severity.currentData() or ""); visible = 0; self.tree.clear()
        for row in self._rows:
            haystack = " ".join(str(row.get(key) or "") for key in ("name", "message", "kind", "type", "path")).casefold()
            if (query and query not in haystack) or (severity and row.get("severity") != severity): continue
            item = QTreeWidgetItem([str(row.get("severity") or "info").upper(), str(row.get("name") or ""), str(row.get("message") or ""), str(row.get("type") or ""), AssetDependencyExplorer._format_size(int(row.get("size") or 0)), str(row.get("path") or "")]); item.setData(0, ASSET_ID_ROLE, str(row.get("asset_id") or "")); item.setData(0, ISSUE_KIND_ROLE, str(row.get("kind") or "")); item.setToolTip(2, item.text(2)); self.tree.addTopLevelItem(item); visible += 1
        errors = sum(row.get("severity") == "error" for row in self._rows); warnings = sum(row.get("severity") == "warning" for row in self._rows); self.summary.setText(f"{visible} visible • {errors} errors • {warnings} warnings • {len(self._rows)} total findings"); self._selection_changed()

    def _selected_asset_id(self) -> str:
        item = self.tree.currentItem(); return str(item.data(0, ASSET_ID_ROLE) or "") if item else ""
    def _selected_issue_kind(self) -> str:
        item = self.tree.currentItem(); return str(item.data(0, ISSUE_KIND_ROLE) or "") if item else ""
    def open_selected(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        self.openRequested.emit(asset_id); return True
    def locate_selected(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        self.locateRequested.emit(asset_id); return True
    def show_dependencies(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id: return False
        self.dependencyRequested.emit(asset_id); return True
    def repair_selected_metadata(self) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id or self._selected_issue_kind() != "missing_metadata": return False
        record = self.database.asset(asset_id)
        if record is None or not record.source_path.is_file(): return False
        try:
            self.database.register_asset(
                record.source_path, record.asset_type, asset_id=record.asset_id,
                metadata=record.metadata, dependencies=self.database.dependency_edges(record.asset_id),
            )
        except (OSError, ValueError) as exc:
            self.statusMessage.emit(f"Could not repair asset metadata: {exc}"); return False
        self._rows = [row for row in self._rows if not (row.get("asset_id") == asset_id and row.get("kind") == "missing_metadata")]
        self.apply_filter(); self.assetsChanged.emit(); self.statusMessage.emit(f"Recreated stable identity metadata for {record.source_path.name}."); return True
    def move_selected_unused_to_trash(self, *, confirm: bool = True) -> bool:
        asset_id = self._selected_asset_id()
        if not asset_id or self._selected_issue_kind() != "unused": return False
        record = self.database.asset(asset_id)
        if record is None or self.database.referencers(asset_id):
            self.statusMessage.emit("The asset is now in use and was retained."); return False
        if confirm and QMessageBox.question(self, "Move Unused Asset to Project Trash", f"Move {record.source_path.name} to recoverable project trash?") != QMessageBox.Yes: return False
        try: receipt = self.operations.delete_asset(asset_id)
        except (KeyError, OSError, ValueError) as exc:
            self.statusMessage.emit(f"Could not move asset to trash: {exc}"); return False
        self._rows = [row for row in self._rows if row.get("asset_id") != asset_id]
        self.apply_filter(); self.assetsChanged.emit(); self.statusMessage.emit(f"Moved {Path(receipt.original_path).name} to recoverable project trash."); return True
    def _selection_changed(self) -> None:
        enabled = bool(self._selected_asset_id()); kind = self._selected_issue_kind(); self.open_button.setEnabled(enabled); self.locate_button.setEnabled(enabled); self.dependencies_button.setEnabled(enabled); self.repair_button.setEnabled(enabled and kind == "missing_metadata"); self.trash_button.setEnabled(enabled and kind == "unused")


__all__ = ["AssetAuditDashboard", "AssetDependencyExplorer"]
