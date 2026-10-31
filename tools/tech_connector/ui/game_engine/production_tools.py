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

from tech_connector.game_engine.assets import AssetDatabase, AssetOperationsService
from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.build_profile_service import plan_build_profile
from tech_connector.game_engine.runtime.engine_console_service import EngineConsoleSession
from tech_connector.game_engine.runtime.tc_player_build_service import (
    PlayerBuildReceipt, build_windows_player, compile_tcscene_for_runtime, launch_play_in_editor,
    runtime_platform_capabilities, summarize_player_profile,
)


class PlayerBuildWorker(QThread):
    progress = Signal(str); stageCompleted = Signal(str, object); completed = Signal(object); failed = Signal(str)

    def __init__(self, action: str, scene: str, output: str = "", parent=None, *, checkpoint: dict[str, Any] | None = None) -> None:
        super().__init__(parent); self.action = str(action); self.scene = str(scene); self.output = str(output); self.checkpoint = dict(checkpoint or {})

    @staticmethod
    def _restore_receipt(data: dict[str, Any]) -> PlayerBuildReceipt | None:
        manifest = Path(str(data.get("runtime_manifest") or ""))
        if not manifest.is_file(): return None
        return PlayerBuildReceipt(
            scene=Path(str(data.get("scene") or "")), runtime_manifest=manifest,
            player_executable=Path(str(data["player_executable"])) if data.get("player_executable") else None,
            output_directory=Path(str(data["output_directory"])) if data.get("output_directory") else None,
            assets=tuple(str(value) for value in data.get("assets") or ()), entities=int(data.get("entities") or 0),
            graph_operations=int(data.get("graph_operations") or 0), warnings=tuple(str(value) for value in data.get("warnings") or ()),
            validation=dict(data.get("validation") or {}),
        )

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                raise RuntimeError("Canceled before the build stage started.")
            self.progress.emit(f"{self.action.title()}: {Path(self.scene).name}")
            if self.action in {"cook", "package"}:
                saved = dict(dict(self.checkpoint.get("stage_receipts") or {}).get("runtime_compile") or {})
                compiled = self._restore_receipt(saved) if "runtime_compile" in set(self.checkpoint.get("completed_stages") or ()) else None
                if compiled is None:
                    compiled = compile_tcscene_for_runtime(self.scene, Path(self.output) / "Content" / "main.tcruntime")
                    self.stageCompleted.emit("runtime_compile", compiled.to_dict())
                else:
                    self.progress.emit("Reusing completed runtime compile from the build checkpoint.")
                if self.isInterruptionRequested(): raise RuntimeError("Stopped after runtime compilation at a safe stage boundary.")
                if self.action == "cook": result = compiled
                else:
                    result = build_windows_player(self.scene, self.output, compiled_receipt=compiled)
                    self.stageCompleted.emit("package", result.to_dict())
            elif self.action == "play": result = launch_play_in_editor(self.scene, working_directory=self.output or None)
            else: raise ValueError(f"Unknown player action: {self.action}")
            self.completed.emit(result)
        except Exception as exc: self.failed.emit(str(exc))


class BuildDeployPanel(QWidget):
    statusMessage = Signal(str); profileReady = Signal(str); taskEvent = Signal(object); openAssetRequested = Signal(str)

    def __init__(self, project_root: str | Path, database: AssetDatabase, parent=None) -> None:
        super().__init__(parent); self.project_root = Path(project_root).resolve(); self.database = database; self.operations = AssetOperationsService(self.project_root, database)
        self._worker = None; self._last_output = ""; self._active_task_id = ""; self._cancel_requested = False; self._pause_requested = False
        self.checkpoint_path = self.project_root / ".tech_connector" / "build_checkpoint.json"
        root = QVBoxLayout(self); form = QFormLayout()
        self.entry_level = QComboBox(self); self.platform = QComboBox(self); self.platform.addItems(["windows", "linux", "macos", "android", "ios", "web"])
        self.configuration = QComboBox(self); self.configuration.addItems(["development", "test", "shipping"])
        self.quality = QComboBox(self); self.quality.addItems(["low", "medium", "high", "cinematic"]); self.quality.setCurrentText("high")
        self.incremental = QCheckBox("Reuse current derived data", self); self.incremental.setChecked(True); self.incremental.setToolTip("Keep valid cooked artifacts and rebuild only stale dependencies")
        self.output_path = QLineEdit(str(self.project_root / "Build" / "Windows"), self); browse = QPushButton("Browse…", self); browse.clicked.connect(self.choose_output); output_row = QHBoxLayout(); output_row.addWidget(self.output_path, 1); output_row.addWidget(browse)
        form.addRow("Entry Level", self.entry_level); form.addRow("Platform", self.platform); form.addRow("Configuration", self.configuration); form.addRow("Quality", self.quality); form.addRow("Cook Mode", self.incremental); form.addRow("Output", output_row); root.addLayout(form)
        actions = QHBoxLayout(); self.action_buttons: list[QPushButton] = []
        for label, handler in (("Validate", self.validate), ("Cook", self.cook), ("Package", self.package), ("Build & Run", self.build_and_run)): button = QPushButton(label, self); button.clicked.connect(handler); actions.addWidget(button); self.action_buttons.append(button)
        self.cancel_button = QPushButton("Cancel Safely", self); self.cancel_button.setEnabled(False); self.cancel_button.setToolTip("Request cancellation at the next safe build-stage boundary"); self.cancel_button.clicked.connect(self.cancel); actions.addWidget(self.cancel_button)
        self.pause_button = QPushButton("Pause Safely", self); self.pause_button.setEnabled(False); self.pause_button.setToolTip("Pause after the current native build stage and retain completed output"); self.pause_button.clicked.connect(self.pause); actions.addWidget(self.pause_button)
        self.resume_button = QPushButton("Resume Last", self); self.resume_button.clicked.connect(self.resume_last); actions.addWidget(self.resume_button)
        root.addLayout(actions); self.capabilities = QLabel(self); self.capabilities.setWordWrap(True); root.addWidget(self.capabilities)
        self.size_summary = QLabel("Validate to preview dependency and package sizes.", self); self.size_summary.setWordWrap(True); root.addWidget(self.size_summary)
        self.assets = QTableWidget(0, 6, self); self.assets.setHorizontalHeaderLabels(["Asset", "Type", "Source Size", "Cook", "State", "Details"]); self.assets.setSelectionBehavior(QTableWidget.SelectRows); self.assets.setEditTriggers(QTableWidget.NoEditTriggers); self.assets.cellDoubleClicked.connect(self._open_asset_row); header = self.assets.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.Stretch); header.setSectionResizeMode(1, QHeaderView.ResizeToContents); header.setSectionResizeMode(2, QHeaderView.ResizeToContents); header.setSectionResizeMode(3, QHeaderView.ResizeToContents); header.setSectionResizeMode(4, QHeaderView.ResizeToContents); header.setSectionResizeMode(5, QHeaderView.Stretch); root.addWidget(self.assets, 1)
        self.log = QPlainTextEdit(self); self.log.setReadOnly(True); root.addWidget(self.log, 1); self.refresh(); self._restore_checkpoint_state()

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
        return {"platform": self.platform.currentText(), "configuration": self.configuration.currentText(), "quality_profile": self.quality.currentText(), "entry_level": asset_id, "included_levels": [asset_id] if asset_id else [], "incremental": self.incremental.isChecked(), "output_directory": self.output_path.text()}

    def validate(self) -> bool:
        plan = plan_build_profile(self.database, self.properties()); self.log.clear(); self.log.appendPlainText(f"Target: {plan.platform} / {plan.configuration} / {plan.quality_profile}\nAssets: {len(plan.asset_ids)}"); self._populate_asset_plan(plan)
        for item in plan.diagnostics: self.log.appendPlainText(f"[{item.severity.upper()}] {item.message}")
        ready = bool(plan.ready and not getattr(self, "_asset_plan_errors", 0)); state = "ready" if ready else "blocked"; self.statusMessage.emit(f"Build profile {state}."); return ready

    def _populate_asset_plan(self, plan: Any) -> None:
        self.assets.setRowCount(0); source_bytes = 0; cached_bytes = 0; cached_count = 0; errors = 0
        for asset_id in plan.asset_ids:
            record = self.database.asset(asset_id); row = self.assets.rowCount(); self.assets.insertRow(row)
            if record is None:
                values = (asset_id, "Missing", "0 B", "Blocked", "ERROR", "Asset record is unavailable."); errors += 1
            else:
                source_bytes += int(record.size); artifacts = self.database.derived_artifacts(asset_id) if plan.incremental else ()
                issues = self.operations.validate_asset(asset_id).issues
                messages = [issue.message for issue in issues if issue.severity == "error"]
                if record.status != "ready": messages.insert(0, f"Asset state is {record.status}.")
                if messages:
                    cook, state, details = "Blocked", "ERROR", "; ".join(messages); errors += 1
                elif artifacts:
                    artifact_bytes = sum(item.path.stat().st_size for item in artifacts if item.path.is_file()); cached_bytes += artifact_bytes; cached_count += 1
                    cook, state, details = f"Reuse {len(artifacts)}", "CACHED", self._format_bytes(artifact_bytes)
                else:
                    cook, state, details = "Build", "READY", "No current derived output"
                values = (record.source_path.name, record.asset_type.removeprefix("tc."), self._format_bytes(record.size), cook, state, details)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setToolTip(str(value)); item.setData(Qt.UserRole, str(asset_id)); self.assets.setItem(row, column, item)
        mode = "incremental" if plan.incremental else "clean"
        self._asset_plan_errors = errors
        self.size_summary.setText(f"{len(plan.asset_ids)} assets • {self._format_bytes(source_bytes)} source • {cached_count} cached ({self._format_bytes(cached_bytes)}) • {errors} blocked • {mode} cook")

    def _open_asset_row(self, row: int, _column: int) -> None:
        item = self.assets.item(row, 0); asset_id = str(item.data(Qt.UserRole) or "") if item else ""
        if asset_id and self.database.asset(asset_id) is not None: self.openAssetRequested.emit(asset_id)

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = float(max(0, int(value)))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0 or unit == "GB": return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} GB"

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

    def _start(self, action: str, scene: Path, output: Path, *, resume: bool = False) -> bool:
        if self._worker is not None and self._worker.isRunning(): return False
        output.mkdir(parents=True, exist_ok=True)
        self._cancel_requested = False
        self._pause_requested = False
        self._active_task_id = f"build:{action}"
        scene_record = self.database.asset_for_path(scene)
        if resume: self._set_checkpoint_state("running")
        else: self._write_checkpoint(action, scene, output, "running")
        checkpoint = self._read_checkpoint()
        self.taskEvent.emit({
            "operation": "begin", "task_id": self._active_task_id,
            "label": f"{action.title()} player", "category": "build",
            "can_cancel": True, "can_pause": True, "can_retry": True,
            "metadata": {"action": action, "scene": str(scene), "scene_asset_id": scene_record.asset_id if scene_record else "", "output": str(output), "resumed": bool(resume)},
        })
        for button in self.action_buttons: button.setEnabled(False)
        self.cancel_button.setEnabled(True); self.pause_button.setEnabled(True); self.resume_button.setEnabled(False)
        worker = PlayerBuildWorker(action, str(scene), str(output), self, checkpoint=checkpoint); worker.progress.connect(self._append); worker.stageCompleted.connect(self._stage_completed); worker.failed.connect(self._failed); worker.completed.connect(self._completed); worker.finished.connect(self._worker_finished); worker.finished.connect(worker.deleteLater); self._worker = worker; worker.start(); return True

    def _append(self, message: str) -> None:
        self.log.appendPlainText(str(message)); self.statusMessage.emit(str(message))
        if self._active_task_id: self.taskEvent.emit({"operation": "update", "task_id": self._active_task_id, "message": str(message)})
    def _stage_completed(self, stage: str, receipt: object) -> None:
        checkpoint = self._read_checkpoint(); completed = list(checkpoint.get("completed_stages") or ())
        if str(stage) not in completed: completed.append(str(stage))
        checkpoint["completed_stages"] = completed; receipts = dict(checkpoint.get("stage_receipts") or {}); receipts[str(stage)] = dict(receipt or {}) if isinstance(receipt, dict) else {}; checkpoint["stage_receipts"] = receipts; self._save_checkpoint(checkpoint)
        self._append(f"Checkpoint saved after {str(stage).replace('_', ' ')}.")
    def _failed(self, message: str) -> None:
        self._last_output = ""; self._append("[ERROR] " + str(message))
        state = "canceled" if self._cancel_requested else "paused" if self._pause_requested else "failed"
        self._set_checkpoint_state(state); self._set_asset_result_state(state, str(message)); self._write_build_report(state, error=str(message))
        if self._active_task_id: self.taskEvent.emit({"operation": "finish", "task_id": self._active_task_id, "state": state, "message": "Paused at a safe stage boundary." if state == "paused" else str(message)})
    def _worker_finished(self) -> None:
        self._worker = None
        for button in self.action_buttons: button.setEnabled(True)
        self.cancel_button.setEnabled(False); self.pause_button.setEnabled(False); self.resume_button.setEnabled(self._checkpoint_can_resume())
        self._active_task_id = ""; self._cancel_requested = False; self._pause_requested = False
    def _completed(self, receipt: object) -> None:
        data = receipt.to_dict() if hasattr(receipt, "to_dict") else {}; self._append(json.dumps(data, indent=2, default=str))
        if self._cancel_requested:
            self._last_output = ""
            self._set_checkpoint_state("canceled"); self._set_asset_result_state("canceled", "Canceled at a safe stage boundary."); self._write_build_report("canceled", receipt=data)
            if self._active_task_id: self.taskEvent.emit({"operation": "finish", "task_id": self._active_task_id, "state": "canceled", "message": "Stopped at a safe stage boundary; completed outputs were retained."})
            return
        if self._pause_requested:
            self._last_output = ""
            self._set_checkpoint_state("paused"); self._set_asset_result_state("paused", "Paused at a safe stage boundary."); self._write_build_report("paused", receipt=data)
            if self._active_task_id: self.taskEvent.emit({"operation": "finish", "task_id": self._active_task_id, "state": "paused", "message": "Paused at a safe stage boundary; completed outputs were retained."})
            return
        self._set_checkpoint_state("complete"); self._set_asset_result_state("complete"); report_path = self._write_build_report("complete", receipt=data)
        if report_path: self._append(f"Build report: {report_path}")
        if self._active_task_id: self.taskEvent.emit({"operation": "finish", "task_id": self._active_task_id, "state": "complete", "message": "Build stage completed successfully."})
        output_text = str(data.get("output_directory") or "")
        if not output_text: return
        output = Path(output_text); profile = output / "Content" / "build-validation-profile.jsonl"
        if profile.is_file(): self.profileReady.emit(str(profile))
        if self._last_output and output == Path(self._last_output) and (output / "Play.cmd").is_file():
            QProcess.startDetached("cmd.exe", ["/c", str(output / "Play.cmd")], str(output)); self._last_output = ""

    def cancel(self) -> bool:
        if self._worker is None or not self._worker.isRunning():
            return False
        self._cancel_requested = True
        self._pause_requested = False
        self._worker.requestInterruption()
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self._append("Cancellation requested; the active native stage will finish before the task stops.")
        return True

    def pause(self) -> bool:
        if self._worker is None or not self._worker.isRunning():
            return False
        self._pause_requested = True
        self._cancel_requested = False
        self._worker.requestInterruption()
        self.cancel_button.setEnabled(False); self.pause_button.setEnabled(False)
        self._append("Pause requested; the active native stage will finish before the checkpoint pauses.")
        return True

    def resume_last(self) -> bool:
        checkpoint = self._read_checkpoint()
        if not checkpoint or str(checkpoint.get("state") or "") not in {"failed", "interrupted", "canceled", "paused"}:
            self.statusMessage.emit("There is no interrupted build to resume.")
            return False
        scene = Path(str(checkpoint.get("scene") or ""))
        output = Path(str(checkpoint.get("output") or ""))
        action = str(checkpoint.get("action") or "")
        if action not in {"cook", "package", "play"} or not scene.is_file():
            self.statusMessage.emit("The saved build checkpoint no longer has a valid entry level.")
            return False
        stages = list(checkpoint.get("completed_stages") or ()); suffix = f" after {', '.join(value.replace('_', ' ') for value in stages)}" if stages else ""
        self.log.appendPlainText(f"Resuming {action} from the last safe stage{suffix}…")
        return self._start(action, scene, output, resume=True)

    def _write_checkpoint(self, action: str, scene: Path, output: Path, state: str) -> None:
        plan = plan_build_profile(self.database, self.properties())
        self._save_checkpoint({
            "schema": "tech_connector.build_checkpoint.v2", "action": str(action),
            "scene": str(scene), "output": str(output), "state": str(state),
            "profile": self.properties(), "asset_ids": list(plan.asset_ids),
            "completed_stages": [], "stage_receipts": {},
        })

    def _save_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    def _read_checkpoint(self) -> dict[str, Any]:
        if not self.checkpoint_path.is_file(): return {}
        try: return dict(json.loads(self.checkpoint_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError): return {}

    def _set_checkpoint_state(self, state: str) -> None:
        checkpoint = self._read_checkpoint()
        if checkpoint:
            checkpoint["state"] = str(state)
            self._save_checkpoint(checkpoint)

    def _set_asset_result_state(self, state: str, error: str = "") -> None:
        final = {"complete": "BUILT", "paused": "PAUSED", "canceled": "CANCELED", "failed": "FAILED"}.get(str(state), str(state).upper())
        for row in range(self.assets.rowCount()):
            current = self.assets.item(row, 4)
            if current is None or current.text() == "ERROR" or (current.text() == "CACHED" and state == "complete"): continue
            current.setText(final)
            if error:
                details = self.assets.item(row, 5)
                if details is not None: details.setText(error); details.setToolTip(error)

    def _write_build_report(self, state: str, *, receipt: dict[str, Any] | None = None, error: str = "") -> str:
        checkpoint = self._read_checkpoint(); output_text = str(checkpoint.get("output") or "")
        if not output_text: return ""
        output = Path(output_text)
        if not output.exists(): return ""
        report_path = output / "build-report.json"; files: list[dict[str, Any]] = []; groups: dict[str, int] = {}
        try:
            for path in output.rglob("*"):
                if not path.is_file() or path == report_path: continue
                relative = path.relative_to(output).as_posix(); size = path.stat().st_size; group = relative.split("/", 1)[0]
                groups[group] = groups.get(group, 0) + size; files.append({"path": relative, "bytes": size})
        except OSError:
            pass
        assets = []
        for row in range(self.assets.rowCount()):
            first = self.assets.item(row, 0)
            assets.append({
                "asset_id": str(first.data(Qt.UserRole) or "") if first else "", "name": first.text() if first else "",
                "type": self.assets.item(row, 1).text() if self.assets.item(row, 1) else "",
                "cook": self.assets.item(row, 3).text() if self.assets.item(row, 3) else "",
                "state": self.assets.item(row, 4).text() if self.assets.item(row, 4) else "",
                "details": self.assets.item(row, 5).text() if self.assets.item(row, 5) else "",
            })
        payload = {
            "schema": "tech_connector.build_report.v1", "state": str(state), "error": str(error),
            "action": checkpoint.get("action"), "profile": checkpoint.get("profile") or {},
            "completed_stages": checkpoint.get("completed_stages") or [], "assets": assets,
            "output_bytes": sum(groups.values()), "size_by_group": dict(sorted(groups.items())),
            "files": sorted(files, key=lambda value: (-int(value["bytes"]), str(value["path"]))), "receipt": dict(receipt or {}),
        }
        try: report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        except OSError: return ""
        breakdown = ", ".join(f"{name}: {self._format_bytes(size)}" for name, size in sorted(groups.items())) or "no output files"
        self.size_summary.setText(f"Output {self._format_bytes(payload['output_bytes'])} • {breakdown}")
        return str(report_path)

    def _checkpoint_can_resume(self) -> bool:
        return str(self._read_checkpoint().get("state") or "") in {"failed", "interrupted", "canceled", "paused"}

    def _restore_checkpoint_state(self) -> None:
        checkpoint = self._read_checkpoint()
        if checkpoint.get("state") == "running":
            self._set_checkpoint_state("interrupted")
            checkpoint["state"] = "interrupted"
        self.resume_button.setEnabled(str(checkpoint.get("state") or "") in {"failed", "interrupted", "canceled", "paused"})
        if self.resume_button.isEnabled():
            self.log.appendPlainText("An interrupted build checkpoint is available to resume.")


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

    def __init__(
        self, project_root: str | Path, database: AssetDatabase, parent=None, *, auto_refresh: bool = True,
    ) -> None:
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
        self.summary.setText("Audit not run yet — open this panel or choose Run Audit when you need release evidence.")
        self.summary.setStyleSheet("color: #8da3b2;")
        if auto_refresh:
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
