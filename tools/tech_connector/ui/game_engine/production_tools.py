"""Production build, console, and profiling surfaces for the engine workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QProcess, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from tech_connector.game_engine.assets import AssetDatabase
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.build_profile_service import plan_build_profile
from tech_connector.game_engine.runtime.engine_console_service import EngineConsoleSession
from tech_connector.game_engine.runtime.tc_player_build_service import (
    build_windows_player, compile_tcscene_for_runtime, launch_play_in_editor,
    runtime_platform_capabilities, summarize_player_profile,
)


class PlayerBuildWorker(QThread):
    progress = Signal(str); completed = Signal(object); failed = Signal(str)

    def __init__(self, action: str, scene: str, output: str = "", parent=None) -> None:
        super().__init__(parent); self.action = str(action); self.scene = str(scene); self.output = str(output)

    def run(self) -> None:
        try:
            self.progress.emit(f"{self.action.title()}: {Path(self.scene).name}")
            if self.action == "cook": result = compile_tcscene_for_runtime(self.scene, Path(self.output) / "Content" / "main.tcruntime")
            elif self.action == "package": result = build_windows_player(self.scene, self.output)
            elif self.action == "play": result = launch_play_in_editor(self.scene, working_directory=self.output or None)
            else: raise ValueError(f"Unknown player action: {self.action}")
            self.completed.emit(result)
        except Exception as exc: self.failed.emit(str(exc))


class BuildDeployPanel(QWidget):
    statusMessage = Signal(str); profileReady = Signal(str)

    def __init__(self, project_root: str | Path, database: AssetDatabase, parent=None) -> None:
        super().__init__(parent); self.project_root = Path(project_root).resolve(); self.database = database
        self._worker = None; self._last_output = ""
        root = QVBoxLayout(self); form = QFormLayout()
        self.entry_level = QComboBox(self); self.platform = QComboBox(self); self.platform.addItems(["windows", "linux", "macos", "android", "ios", "web"])
        self.configuration = QComboBox(self); self.configuration.addItems(["development", "test", "shipping"])
        self.quality = QComboBox(self); self.quality.addItems(["low", "medium", "high", "cinematic"]); self.quality.setCurrentText("high")
        self.output_path = QLineEdit(str(self.project_root / "Build" / "Windows"), self); browse = QPushButton("Browse…", self); browse.clicked.connect(self.choose_output); output_row = QHBoxLayout(); output_row.addWidget(self.output_path, 1); output_row.addWidget(browse)
        form.addRow("Entry Level", self.entry_level); form.addRow("Platform", self.platform); form.addRow("Configuration", self.configuration); form.addRow("Quality", self.quality); form.addRow("Output", output_row); root.addLayout(form)
        actions = QHBoxLayout(); self.action_buttons: list[QPushButton] = []
        for label, handler in (("Validate", self.validate), ("Cook", self.cook), ("Package", self.package), ("Build & Run", self.build_and_run)): button = QPushButton(label, self); button.clicked.connect(handler); actions.addWidget(button); self.action_buttons.append(button)
        root.addLayout(actions); self.capabilities = QLabel(self); self.capabilities.setWordWrap(True); root.addWidget(self.capabilities)
        self.log = QPlainTextEdit(self); self.log.setReadOnly(True); root.addWidget(self.log, 1); self.refresh()

    def refresh(self) -> None:
        current = str(self.entry_level.currentData() or ""); self.entry_level.clear()
        for record in self.database.list_assets():
            if record.asset_type == "tc.level": self.entry_level.addItem(record.source_path.stem, record.asset_id)
        index = self.entry_level.findData(current)
        if index >= 0: self.entry_level.setCurrentIndex(index)
        caps = runtime_platform_capabilities(); windows = caps["targets"]["windows"]
        self.capabilities.setText(f"Native package: Windows / {windows['renderer']} • Other targets currently compile headless runtime data only.")

    def properties(self) -> dict[str, Any]:
        asset_id = str(self.entry_level.currentData() or "")
        return {"platform": self.platform.currentText(), "configuration": self.configuration.currentText(), "quality_profile": self.quality.currentText(), "entry_level": asset_id, "included_levels": [asset_id] if asset_id else [], "incremental": True, "output_directory": self.output_path.text()}

    def validate(self) -> bool:
        plan = plan_build_profile(self.database, self.properties()); self.log.clear(); self.log.appendPlainText(f"Target: {plan.platform} / {plan.configuration} / {plan.quality_profile}\nAssets: {len(plan.asset_ids)}")
        for item in plan.diagnostics: self.log.appendPlainText(f"[{item.severity.upper()}] {item.message}")
        state = "ready" if plan.ready else "blocked"; self.statusMessage.emit(f"Build profile {state}."); return plan.ready

    def choose_output(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Build Output", self.output_path.text() or str(self.project_root))
        if value: self.output_path.setText(value)

    def _scene(self) -> Path | None:
        record = self.database.asset(str(self.entry_level.currentData() or "")); return record.source_path if record else None

    def cook(self) -> bool:
        if not self.validate(): return False
        scene = self._scene()
        if scene is None: return False
        return self._start("cook", scene, Path(self.output_path.text()).resolve())

    def package(self) -> bool:
        if not self.validate(): return False
        if self.platform.currentText() != "windows": self.log.appendPlainText("[ERROR] Graphical packaging currently supports Windows only."); return False
        scene = self._scene()
        return self._start("package", scene, Path(self.output_path.text()).resolve()) if scene else False

    def build_and_run(self) -> bool:
        self._last_output = str(Path(self.output_path.text()).resolve())
        started = self.package()
        if not started: self._last_output = ""
        return started

    def _start(self, action: str, scene: Path, output: Path) -> bool:
        if self._worker is not None and self._worker.isRunning(): return False
        output.mkdir(parents=True, exist_ok=True)
        for button in self.action_buttons: button.setEnabled(False)
        worker = PlayerBuildWorker(action, str(scene), str(output), self); worker.progress.connect(self._append); worker.failed.connect(self._failed); worker.completed.connect(self._completed); worker.finished.connect(self._worker_finished); worker.finished.connect(worker.deleteLater); self._worker = worker; worker.start(); return True

    def _append(self, message: str) -> None: self.log.appendPlainText(str(message)); self.statusMessage.emit(str(message))
    def _failed(self, message: str) -> None: self._last_output = ""; self._append("[ERROR] " + str(message))
    def _worker_finished(self) -> None:
        self._worker = None
        for button in self.action_buttons: button.setEnabled(True)
    def _completed(self, receipt: object) -> None:
        data = receipt.to_dict() if hasattr(receipt, "to_dict") else {}; self._append(json.dumps(data, indent=2, default=str))
        output_text = str(data.get("output_directory") or "")
        if not output_text: return
        output = Path(output_text); profile = output / "Content" / "build-validation-profile.jsonl"
        if profile.is_file(): self.profileReady.emit(str(profile))
        if self._last_output and output == Path(self._last_output) and (output / "Play.cmd").is_file():
            QProcess.startDetached("cmd.exe", ["/c", str(output / "Play.cmd")], str(output)); self._last_output = ""


class EngineConsolePanel(QWidget):
    def __init__(self, workspace: Any, parent=None) -> None:
        super().__init__(parent); self.workspace = workspace; self.session = EngineConsoleSession(); root = QVBoxLayout(self)
        top = QHBoxLayout(); self.mode = QComboBox(self); self.mode.addItems(["Python", "TC Command"]); top.addWidget(self.mode); run = QPushButton("Run", self); run.clicked.connect(self.execute); top.addWidget(run); reset = QPushButton("Reset", self); reset.clicked.connect(self.reset); top.addWidget(reset); root.addLayout(top)
        self.input = QPlainTextEdit(self); self.input.setPlaceholderText("editor.database.list_assets()\nviewer.current_level_path"); self.input.setMaximumHeight(110); root.addWidget(self.input)
        self.output = QPlainTextEdit(self); self.output.setReadOnly(True); root.addWidget(self.output, 1)

    def execute(self) -> bool:
        source = self.input.toPlainText()
        if not source.strip(): return False
        if self.mode.currentText() == "TC Command":
            from tech_connector.game_engine.integration.active_viewer_command_service import execute_active_viewer_command
            receipt = self.session.execute_tc_command(source, execute_active_viewer_command)
        else:
            from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
            receipt = self.session.execute_python(source, {"editor": TCEditorAPI(self.workspace.project_root, database=self.workspace.database), "workspace": self.workspace, "viewer": self.workspace.viewport})
        self.output.appendPlainText(f"[{receipt.mode} {'OK' if receipt.ok else 'ERROR'} {receipt.elapsed_ms:.2f} ms]")
        for value in (receipt.output, receipt.result_repr, receipt.error):
            if value: self.output.appendPlainText(value.rstrip())
        return receipt.ok

    def reset(self) -> None: self.session.reset(); self.session.history.clear(); self.output.clear()


class RuntimeProfilerPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent); self.profile_path = Path(); root = QVBoxLayout(self); controls = QHBoxLayout(); self.path_label = QLabel("No capture loaded", self); controls.addWidget(self.path_label, 1); load = QPushButton("Load Capture…", self); load.clicked.connect(self.choose_capture); controls.addWidget(load); root.addLayout(controls)
        self.metrics = QTableWidget(4, 4, self); self.metrics.setHorizontalHeaderLabels(["Metric", "Average ms", "P95 ms", "Maximum ms"])
        for row, name in enumerate(("Frame", "Graph", "Physics", "GPU")): self.metrics.setItem(row, 0, QTableWidgetItem(name))
        root.addWidget(self.metrics); self.details = QPlainTextEdit(self); self.details.setReadOnly(True); root.addWidget(self.details, 1)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh)

    def choose_capture(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Runtime Profile", "", "Runtime Profile (*.jsonl *.log);;All Files (*)")
        if path: self.watch(path)

    def watch(self, path: str | Path) -> None: self.profile_path = Path(path); self.path_label.setText(str(self.profile_path)); self.refresh(); self.timer.start(500)
    def refresh(self) -> None:
        if not self.profile_path.is_file(): return
        summary = summarize_player_profile(self.profile_path)
        for row, key in enumerate(("frame", "graph", "physics", "gpu")):
            values = summary[key]
            for column, field in enumerate(("average_ms", "p95_ms", "maximum_ms"), 1): self.metrics.setItem(row, column, QTableWidgetItem(f"{values[field]:.3f}"))
        lines = [*summary.get("diagnostics", ()), *summary.get("graph_trace", ())]; self.details.setPlainText("\n".join(lines[-500:]))


class LaunchReadinessPanel(QWidget):
    """Evidence-first launch dashboard shared by artists, engineers, and producers."""

    statusMessage = Signal(str)

    def __init__(self, project_root: str | Path, database: AssetDatabase, parent=None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).expanduser().resolve()
        self.api = TCEditorAPI(self.project_root, database=database)
        self.last_audit: dict[str, Any] = {}
        root = QVBoxLayout(self)
        heading = QLabel("Launch Readiness", self)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(heading)
        explanation = QLabel(
            "Fail-closed qualification across packaging, Python API parity, asset UX, "
            "runtime capability maturity, and live DCC evidence.", self,
        )
        explanation.setWordWrap(True); root.addWidget(explanation)
        controls = QHBoxLayout()
        self.production = QCheckBox("Include production, legal, and source-access controls", self)
        self.production.setToolTip("Adds release-signing, legal approval, protected-source, and production-runtime gates.")
        controls.addWidget(self.production, 1)
        refresh = QPushButton("Run Audit", self); refresh.setObjectName("LaunchReadinessRunAudit")
        refresh.clicked.connect(self.refresh); controls.addWidget(refresh); root.addLayout(controls)
        self.summary = QLabel(self); self.summary.setWordWrap(True); root.addWidget(self.summary)
        self.gates = QTableWidget(0, 5, self)
        self.gates.setObjectName("LaunchReadinessGates")
        self.gates.setHorizontalHeaderLabels(["Gate", "Status", "Blockers", "Next action", "Evidence"])
        self.gates.setSelectionBehavior(QTableWidget.SelectRows); self.gates.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.gates.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.ResizeToContents); header.setSectionResizeMode(1, QHeaderView.ResizeToContents); header.setSectionResizeMode(2, QHeaderView.Stretch); header.setSectionResizeMode(3, QHeaderView.Stretch); header.setSectionResizeMode(4, QHeaderView.Stretch)
        root.addWidget(self.gates, 1)
        self.details = QPlainTextEdit(self); self.details.setReadOnly(True); self.details.setMaximumHeight(180)
        self.details.setPlaceholderText("Select a gate to inspect its complete evidence and blockers.")
        self.gates.itemSelectionChanged.connect(self._show_selected_gate); root.addWidget(self.details)
        self.refresh()

    def refresh(self) -> dict[str, Any]:
        self.last_audit = self.api.audit_launch_readiness(production=self.production.isChecked())
        rows = list(self.last_audit.get("gates") or ())
        self.gates.setRowCount(len(rows))
        for row_index, gate in enumerate(rows):
            blockers = list(gate.get("blockers") or ())
            remediation = list(gate.get("remediation") or ())
            evidence = gate.get("evidence") or {}
            values = (
                str(gate.get("gate") or "").replace("_", " ").title(),
                str(gate.get("status") or "unknown").upper(),
                "None" if not blockers else f"{len(blockers)} — {blockers[0]}",
                "Complete" if not remediation else remediation[0],
                json.dumps(evidence, sort_keys=True, default=str),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.UserRole, gate); item.setToolTip(value)
                if column == 1:
                    item.setForeground(Qt.darkGreen if value == "PASSED" else Qt.darkRed)
                self.gates.setItem(row_index, column, item)
        blocked = list(self.last_audit.get("blocking_gates") or ())
        ready = self.last_audit.get("status") == "launch_ready"
        if ready:
            self.summary.setText("LAUNCH READY — every selected gate passed with evidence.")
            self.summary.setStyleSheet("font-weight: 600; color: #5fbf72;")
        else:
            self.summary.setText(f"BLOCKED — {len(blocked)} gate(s) require work: {', '.join(blocked)}")
            self.summary.setStyleSheet("font-weight: 600; color: #e6a23c;")
        self.statusMessage.emit(self.summary.text())
        return self.last_audit

    def _show_selected_gate(self) -> None:
        items = self.gates.selectedItems()
        if not items: return
        gate = items[0].data(Qt.UserRole) or {}
        self.details.setPlainText(json.dumps(gate, indent=2, sort_keys=True, default=str))


__all__ = ["BuildDeployPanel", "EngineConsolePanel", "LaunchReadinessPanel", "PlayerBuildWorker", "RuntimeProfilerPanel"]
