"""Goal-driven capability gap planning.

This service is deterministic and intentionally lightweight. It does not execute
work or perform research. It turns a user goal into capability nodes, missing
links, gap resolution options, and learning recommendations so planning can account for
the real A-to-Z path instead of assuming a direct implementation step exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable

from tech_connector.services.reasoning.goal_gap_capability_rules import (
    CapabilityNode,
    GapResolutionOption,
    CapabilityResolutionStrategy,
    OperationActionType,
    ArtifactType,
    CapabilityPattern,
    _uniq,
    _slug,
    _function_slug,
    _goal_from_prompt,
    _build_problem_formulation,
    _capability_nodes_from_problem_formulation,
    _problem_formulation_requires_pause,
    _terms,
    _node,
    RESOLUTION_STRATEGIES,
    ACTION_TYPES,
    ARTIFACT_TYPES,
    PATTERNS,
    _matched_patterns,
    _generic_pattern,
    _is_quick_direct_action,
    _quick_direct_pattern,
    _contextual_knowledge_evidence,
    _capability_registry_evidence,
    _known_capability_evidence,
    _strategy_by_key,
    _strategy_keys_for_node,
    _is_animation_source_node,
    _is_external_asset_source_node,
    _prompt_wants_generated_asset,
    _provider_candidates_for_node,
    _resolution_strategy_plan,
    _choose_strategy_for_node,
    _adaptive_sequence,
    _action_type_by_key,
    _action_keys_for_sequence_item,
)

def _operation_action_catalog() -> list[dict[str, Any]]:
    return [action_type.to_dict() for action_type in ACTION_TYPES]


def _planned_call_for_action(item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    action_type = str(item.get("action_type") or "")
    capability = str(item.get("capability") or "")
    prompt = str(decision.get("prompt") or decision.get("original_prompt") or "")
    host = _execution_context_for_action(item).get("host", "")
    capability_text = f"{capability} {prompt}".lower()
    wants_qt_operation_runner = any(
        term in capability_text
        for term in (
            "operation runner",
            "operation catalog",
            "registered unreal/dcc operation",
            "edit its arguments as json",
        )
    )
    wants_rollback_journal = any(term in capability_text for term in ("rollback journal", "failed write", "recovery after a failed"))
    wants_prompt_router_evidence = any(term in capability_text for term in ("prompt router", "fuzz regression", "attribution paths", "route evidence"))
    if wants_qt_operation_runner:
        expected_code_dependencies = ["Qt pattern scan", "operation catalog scan", "existing execution-service dispatch path"]
        expected_code_payload = {
            "expected_files": [
                {
                    "path": "tech_connector/ui/operation_runner_panel.py",
                    "purpose": "Reusable PySide panel for browsing registered operations, editing JSON args, and non-blocking run/queue dispatch.",
                },
                {
                    "path": "tech_connector/app/main_window_ui.py or app tab composition module",
                    "purpose": "Add OperationRunnerPanel to the app/tab layout without duplicating existing workflow UI.",
                },
                {
                    "path": "tech_connector/examples/tests/test_operation_runner_panel.py",
                    "purpose": "Focused tests for catalog loading, JSON template generation, and worker payload creation.",
                },
            ],
            "expected_imports": [
                "PySide6.QtCore.QThread, Signal, Qt",
                "PySide6.QtWidgets.QWidget, QComboBox, QLineEdit, QPushButton, QPlainTextEdit, QTableWidget, QTableWidgetItem",
                "tech_connector.services.unreal.unreal_operation_service.operation_catalog",
                "tech_connector.services.unreal.unreal_operation_service.unreal_operation_payload",
                "tech_connector.game_engine.integration.dcc_operation_service.dcc_operation_registry",
                "tech_connector.router.command_router.CommandRouter",
            ],
            "expected_classes": [
                {"name": "OperationRow", "kind": "dataclass", "fields": ["host", "key", "label", "function", "required", "optional", "mutates_project"]},
                {"name": "OperationBackend", "kind": "service adapter", "methods": ["run_operation(host, operation_key, params)"]},
                {"name": "OperationRunWorker", "kind": "QThread", "signals": ["progress = Signal(str)", "finished = Signal(bool, object)"], "methods": ["__init__(host, operation_key, args_json)", "run()"]},
                {"name": "OperationRunnerPanel", "kind": "QWidget", "methods": ["__init__()", "refresh_catalog()", "populate_args_template()", "run_selected_operation()", "_on_finished()", "_set_rows()", "_selected_row()"]},
            ],
            "method_contracts": [
                {"method": "OperationRow.from_unreal", "inputs": ["operation catalog item"], "side_effects": [], "errors": ["missing key/function metadata"], "returns_or_emits": ["OperationRow"]},
                {"method": "OperationRow.from_dcc", "inputs": ["host", "DCC operation registry item"], "side_effects": [], "errors": ["missing function metadata"], "returns_or_emits": ["OperationRow"]},
                {"method": "OperationBackend.run_operation", "inputs": ["host", "operation_key", "params"], "side_effects": ["calls CommandRouter backend or injected fake"], "errors": ["unknown_host", "backend_exception"], "returns_or_emits": ["structured result with label/ok/result"]},
                {"method": "OperationRunnerPanel.refresh_catalog", "inputs": ["Unreal catalog", "DCC registries"], "side_effects": ["replaces operation table rows", "refreshes argument template for selection"], "errors": ["catalog import unavailable"], "returns_or_emits": ["row count", "error text"]},
                {"method": "OperationRunnerPanel.populate_args_template", "inputs": ["selected OperationRow"], "side_effects": ["writes formatted JSON to args editor"], "errors": ["operation_not_selected"], "returns_or_emits": ["JSON argument template"]},
                {"method": "OperationRunnerPanel.run_selected_operation", "inputs": ["selected OperationRow", "JSON editor text"], "side_effects": ["validates JSON", "starts OperationRunWorker", "disables Run button"], "errors": ["invalid_json", "operation_not_selected", "worker_already_running"], "returns_or_emits": ["progress message"]},
                {"method": "OperationRunWorker.run", "inputs": ["host", "operation_key", "args_json"], "side_effects": ["builds queued payload only", "does not touch UI widgets"], "errors": ["invalid_json", "operation_not_registered"], "returns_or_emits": ["progress", "finished"]},
            ],
            "representative_code": (
                "@dataclass(frozen=True)\n"
                "class OperationRow:\n"
                "    host: str\n"
                "    key: str\n"
                "    label: str\n"
                "    function: str\n"
                "    required: tuple[str, ...] = ()\n"
                "    optional: tuple[str, ...] = ()\n"
                "    mutates_project: bool = False\n\n"
                "    @classmethod\n"
                "    def from_unreal(cls, item: dict[str, Any]) -> 'OperationRow':\n"
                "        return cls('unreal', item['key'], item.get('label', item['key']), item.get('function', ''), tuple(item.get('required') or item.get('required_args') or ()), tuple((item.get('optional') or item.get('optional_args') or {}).keys() if isinstance(item.get('optional') or item.get('optional_args'), dict) else item.get('optional') or item.get('optional_args') or ()), bool(item.get('mutates_project')))\n\n"
                "    @classmethod\n"
                "    def from_dcc(cls, host: str, item: Any) -> 'OperationRow':\n"
                "        required = getattr(item, 'required', getattr(item, 'required_args', ()))\n"
                "        optional = getattr(item, 'optional', getattr(item, 'optional_args', ()))\n"
                "        optional_names = tuple(optional.keys()) if isinstance(optional, dict) else tuple(optional)\n"
                "        return cls(host, item.key, item.label, item.function, tuple(required), optional_names, bool(item.mutates_project))\n\n"
                "class OperationBackend:\n"
                "    def __init__(self, router: Any | None = None):\n"
                "        self.router = router or CommandRouter()\n\n"
                "    def run_operation(self, host: str, operation_key: str, params: dict[str, Any]) -> dict[str, Any]:\n"
                "        try:\n"
                "            if host == 'unreal':\n"
                "                label, ok, result = self.router.execute_unreal_operation(operation_key, params)\n"
                "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'} and hasattr(self.router, 'execute_registered_dcc_operation'):\n"
                "                label, ok, result = self.router.execute_registered_dcc_operation(host, operation_key, params)\n"
                "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'}:\n"
                "                return {'ok': False, 'error': 'backend_adapter_required', 'host': host, 'operation': operation_key, 'params': params}\n"
                "            else:\n"
                "                return {'ok': False, 'error': 'unknown_host', 'host': host, 'operation': operation_key}\n"
                "            return {'ok': bool(ok), 'label': label, 'result': result, 'host': host, 'operation': operation_key}\n"
                "        except Exception as exc:\n"
                "            return {'ok': False, 'error': 'backend_exception', 'detail': str(exc), 'host': host, 'operation': operation_key}\n\n"
                "class OperationRunWorker(QThread):\n"
                "    progress = Signal(str)\n"
                "    finished = Signal(bool, object)\n\n"
                "    def __init__(self, host: str = '', operation_key: str = '', args_json: str = '', backend: OperationBackend | None = None):\n"
                "        super().__init__()\n"
                "        self.progress = Signal(str)\n"
                "        self.finished = Signal(bool, object)\n"
                "        self.host = host\n"
                "        self.operation_key = operation_key\n"
                "        self.args_json = args_json\n\n"
                "        self.backend = backend or OperationBackend()\n\n"
                "    def run(self):\n"
                "        try:\n"
                "            params = json.loads(self.args_json or '{}')\n"
                "        except json.JSONDecodeError as exc:\n"
                "            self.finished.emit(False, {'error': 'invalid_json', 'detail': str(exc)})\n"
                "            return\n"
                "        self.progress.emit(f'Preparing {self.host}:{self.operation_key}')\n"
                "        if self.host == 'unreal':\n"
                "            payload = unreal_operation_payload(self.operation_key, params)\n"
                "            params = payload['kwargs']\n"
                "        elif self.operation_key not in dcc_operation_registry(self.host):\n"
                "            self.finished.emit(False, {'error': 'operation_not_registered'})\n"
                "            return\n"
                "        result = self.backend.run_operation(self.host, self.operation_key, params)\n"
                "        self.finished.emit(bool(result.get('ok')), result)\n\n"
                "class OperationRunnerPanel(QWidget):\n"
                "    def __init__(self, backend: OperationBackend | None = None):\n"
                "        super().__init__()\n"
                "        self.backend = backend or OperationBackend()\n"
                "        self._rows: list[OperationRow] = []\n"
                "        self.selected_index = 0\n"
                "        self.args_editor = _PlainTextBuffer()\n"
                "        self.result_editor = _PlainTextBuffer()\n"
                "        self.run_button = _ButtonState()\n"
                "        self.worker = None\n"
                "        self.refresh_catalog()\n\n"
                "    def refresh_catalog(self):\n"
                "        rows = [OperationRow.from_unreal(item) for item in operation_catalog()]\n"
                "        for host in ('blender', 'maya'):\n"
                "            rows.extend(OperationRow.from_dcc(host, item) for item in dcc_operation_registry(host).values())\n"
                "        self._set_rows(rows)\n\n"
                "    def _set_rows(self, rows: list[OperationRow]):\n"
                "        self._rows = list(rows)\n"
                "        self.selected_index = 0 if self._rows else -1\n"
                "        if self._rows:\n"
                "            self.populate_args_template()\n"
                "        return len(self._rows)\n\n"
                "    def _selected_row(self) -> OperationRow:\n"
                "        if self.selected_index < 0 or self.selected_index >= len(self._rows):\n"
                "            raise ValueError('operation_not_selected')\n"
                "        return self._rows[self.selected_index]\n\n"
                "    def populate_args_template(self):\n"
                "        row = self._selected_row()\n"
                "        template = {name: '' for name in (*row.required, *row.optional)}\n"
                "        self.args_editor.setPlainText(json.dumps(template, indent=2))\n"
                "        return template\n\n"
                "    def run_selected_operation(self):\n"
                "        row = self._selected_row()\n"
                "        self.run_button.setEnabled(False)\n"
                "        self.worker = OperationRunWorker(row.host, row.key, self.args_editor.toPlainText(), self.backend)\n"
                "        self.worker.progress.connect(self.result_editor.appendPlainText)\n"
                "        self.worker.finished.connect(self._on_finished)\n"
                "        self.worker.start()\n\n"
                "    def _on_finished(self, ok: bool, payload: object):\n"
                "        self.run_button.setEnabled(True)\n"
                "        self.result_editor.setPlainText(json.dumps({'ok': ok, 'result': payload}, indent=2, default=str))\n\n"
                "class _PlainTextBuffer:\n"
                "    def __init__(self):\n"
                "        self.text = ''\n"
                "    def setPlainText(self, text: str):\n"
                "        self.text = text\n"
                "    def appendPlainText(self, text: str):\n"
                "        self.text = f'{self.text}\\n{text}'.strip()\n"
                "    def toPlainText(self) -> str:\n"
                "        return self.text\n\n"
                "class _ButtonState:\n"
                "    def __init__(self):\n"
                "        self.enabled = True\n"
                "    def setEnabled(self, enabled: bool):\n"
                "        self.enabled = bool(enabled)"
            ),
            "integration_points": [
                "Return a standalone OperationRunnerPanel that can be embedded in any host window; only register it in an app tab/menu when the prompt explicitly asks for persistent integration.",
                "Route actual execution through existing DCC/Unreal execution services after payload preview is valid.",
                "Keep UI responsive by disabling Run button while OperationRunWorker is active and appending progress/results via signals.",
            ],
            "repo_grounding": [
                {"purpose": "Qt style source", "source": "code.search_project result matching QWidget/QThread/QPlainTextEdit"},
                {"purpose": "Unreal operation catalog source", "source": "tech_connector.services.unreal.unreal_operation_service.operation_catalog"},
                {"purpose": "DCC registry source", "source": "tech_connector.game_engine.integration.dcc_operation_service.dcc_operation_registry"},
            ],
            "pre_patch_review": [
                "All referenced imports exist or the patch adds a guarded fallback.",
                "The UI constructs real Qt widgets for search, host filtering, operation selection, argument editing, progress, and result display.",
                "No UI widget is mutated directly from OperationRunWorker.run.",
                "Run button is disabled during active worker execution and re-enabled on finished/error.",
                "Invalid JSON and missing operation selection produce visible errors.",
                "Tests assert catalog loading, JSON template generation, and queued payload creation.",
            ],
            "acceptance_tests": [
                {"name": "loads_unreal_and_dcc_catalog_rows", "asserts": ["operation_catalog called", "dcc_operation_registry called for blender and maya", "rows include host/key/function"]},
                {"name": "builds_json_template_from_selected_operation", "asserts": ["required and optional args are present", "template is valid JSON"]},
                {"name": "invalid_json_does_not_start_host_execution", "asserts": ["finished emits ok=False", "error is invalid_json"]},
                {"name": "unreal_operation_calls_backend_adapter", "asserts": ["unreal_operation_payload validates selected key and params", "CommandRouter.execute_unreal_operation is called through OperationBackend", "result status is backend_called in disposable test"]},
                {"name": "worker_does_not_block_or_touch_widgets", "asserts": ["execution path is in QThread", "UI updates happen through signals"]},
            ],
            "quality_gates": [
                {"gate": "syntax", "tool": "python -m py_compile", "pass_condition": "all changed Python files compile"},
                {"gate": "import", "tool": "focused import test", "pass_condition": "new panel imports with PySide available or cleanly skipped in headless tests"},
                {"gate": "contract", "tool": "unit tests", "pass_condition": "method contracts are covered by focused assertions"},
                {"gate": "ui_threading", "tool": "static review plus unit test", "pass_condition": "worker never mutates QWidget instances directly"},
                {"gate": "dispatch_safety", "tool": "unit tests", "pass_condition": "run operation builds/queues payload and reports host disconnection rather than blocking UI"},
            ],
            "quality_bar": {
                "target_level": "first_try_usable_integrated_tool",
                "current_level": "functional_generated_ui_smoke_validated",
                "confidence": "medium",
                "proven": [
                    "Generated artifact constructs a real QWidget layout with QComboBox host filtering, QLineEdit search, QTableWidget operation selection, QPlainTextEdit JSON arguments, QPushButton execution, and progress/result output.",
                    "Generated artifact has explicit imports for the real Unreal operation catalog, DCC registry, and CommandRouter.",
                    "UI flow is decomposed as panel -> worker -> backend -> CommandRouter.",
                    "Disposable validation can import the generated module, instantiate the panel, build JSON templates, run Unreal and DCC operations through backend adapters, and report invalid JSON.",
                    "Worker contract avoids direct widget mutation and reports results through progress/finished signals.",
                ],
                "not_yet_proven": [
                    "The disposable UI uses headless stand-ins when PySide6 is unavailable, so real rendered QTableWidget visuals are not live-validated in that runtime.",
                    "Host-window embedding is intentionally not performed unless the prompt asks to install the panel into a specific app shell.",
                    "Real host availability/error states need to be exercised against connected Unreal/Maya/Blender sessions before claiming direct execution confidence.",
                ],
                "promotion_requirements": [
                    "Run focused Qt tests in a PySide-capable runtime using qtbot or equivalent interaction helpers.",
                    "Run backend adapter tests against fake bridges and at least one live connected host smoke test.",
                    "Capture readback evidence: selected operation, payload, backend call, result/error text, and host status handling.",
                ],
                "blocks_first_try_claim": True,
            },
            "implementation_risks": [
                {"risk": "PySide may not be installed in headless test runtime", "mitigation": "guard UI tests with import skip while keeping payload/service tests deterministic"},
                {"risk": "operation_catalog return shape may differ from expected dict keys", "mitigation": "normalize through OperationRow.from_unreal with defaults and focused catalog fixture"},
                {"risk": "real execution path may require host status checks", "mitigation": "queue/preview payload first and defer direct host execution to existing execution service"},
            ],
            "readback_plan": [
                "Import OperationRunnerPanel or skip with explicit PySide unavailable reason.",
                "Instantiate panel with mocked operation catalogs.",
                "Select one Unreal operation and verify JSON template/result payload.",
                "Run worker with invalid JSON and verify structured error.",
                "Verify no direct host execution is attempted from the UI thread.",
            ],
        }
        expected_code_payload["representative_code"] = (
            "@dataclass(frozen=True)\n"
            "class OperationRow:\n"
            "    host: str\n"
            "    key: str\n"
            "    label: str\n"
            "    function: str\n"
            "    required: tuple[str, ...] = ()\n"
            "    optional: tuple[str, ...] = ()\n"
            "    mutates_project: bool = False\n\n"
            "    @classmethod\n"
            "    def from_unreal(cls, item: dict[str, Any]) -> 'OperationRow':\n"
            "        optional = item.get('optional') or item.get('optional_args') or ()\n"
            "        optional_names = tuple(optional.keys()) if isinstance(optional, dict) else tuple(optional)\n"
            "        return cls('unreal', item['key'], item.get('label', item['key']), item.get('function', ''), tuple(item.get('required') or item.get('required_args') or ()), optional_names, bool(item.get('mutates_project')))\n\n"
            "    @classmethod\n"
            "    def from_dcc(cls, host: str, item: Any) -> 'OperationRow':\n"
            "        required = getattr(item, 'required', getattr(item, 'required_args', ()))\n"
            "        optional = getattr(item, 'optional', getattr(item, 'optional_args', ()))\n"
            "        optional_names = tuple(optional.keys()) if isinstance(optional, dict) else tuple(optional)\n"
            "        return cls(host, item.key, item.label, item.function, tuple(required), optional_names, bool(item.mutates_project))\n\n"
            "class OperationBackend:\n"
            "    def __init__(self, router: Any | None = None):\n"
            "        self.router = router or CommandRouter()\n\n"
            "    def run_operation(self, host: str, operation_key: str, params: dict[str, Any]) -> dict[str, Any]:\n"
            "        try:\n"
            "            if host == 'unreal':\n"
            "                label, ok, result = self.router.execute_unreal_operation(operation_key, params)\n"
            "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'} and hasattr(self.router, 'execute_registered_dcc_operation'):\n"
            "                label, ok, result = self.router.execute_registered_dcc_operation(host, operation_key, params)\n"
            "            elif host in {'maya', 'blender', 'houdini', 'motionbuilder', 'substance_painter', 'unity'}:\n"
            "                return {'ok': False, 'error': 'backend_adapter_required', 'host': host, 'operation': operation_key, 'params': params}\n"
            "            else:\n"
            "                return {'ok': False, 'error': 'unknown_host', 'host': host, 'operation': operation_key}\n"
            "            return {'ok': bool(ok), 'label': label, 'result': result, 'host': host, 'operation': operation_key}\n"
            "        except Exception as exc:\n"
            "            return {'ok': False, 'error': 'backend_exception', 'detail': str(exc), 'host': host, 'operation': operation_key}\n\n"
            "class OperationRunWorker(QThread):\n"
            "    progress = Signal(str)\n"
            "    finished = Signal(bool, object)\n\n"
            "    def __init__(self, host: str = '', operation_key: str = '', args_json: str = '', backend: OperationBackend | None = None):\n"
            "        super().__init__()\n"
            "        self.host = host\n"
            "        self.operation_key = operation_key\n"
            "        self.args_json = args_json\n"
            "        self.backend = backend or OperationBackend()\n\n"
            "    def run(self):\n"
            "        try:\n"
            "            params = json.loads(self.args_json or '{}')\n"
            "        except json.JSONDecodeError as exc:\n"
            "            self.finished.emit(False, {'error': 'invalid_json', 'detail': str(exc)})\n"
            "            return\n"
            "        self.progress.emit(f'Preparing {self.host}:{self.operation_key}')\n"
            "        if self.host == 'unreal':\n"
            "            payload = unreal_operation_payload(self.operation_key, params)\n"
            "            params = payload['kwargs']\n"
            "        elif self.operation_key not in dcc_operation_registry(self.host):\n"
            "            self.finished.emit(False, {'error': 'operation_not_registered'})\n"
            "            return\n"
            "        result = self.backend.run_operation(self.host, self.operation_key, params)\n"
            "        self.finished.emit(bool(result.get('ok')), result)\n\n"
            "class OperationRunnerPanel(QWidget):\n"
            "    def __init__(self, backend: OperationBackend | None = None):\n"
            "        super().__init__()\n"
            "        self.backend = backend or OperationBackend()\n"
            "        self._all_rows: list[OperationRow] = []\n"
            "        self._visible_rows: list[OperationRow] = []\n"
            "        self.worker = None\n"
            "        self.host_filter = QComboBox()\n"
            "        self.host_filter.addItems(['all', 'unreal', 'blender', 'maya'])\n"
            "        self.search_edit = QLineEdit()\n"
            "        self.search_edit.setPlaceholderText('Search operations, labels, functions, args')\n"
            "        self.operation_table = QTableWidget(0, 6)\n"
            "        self.operation_table.setHorizontalHeaderLabels(['Host', 'Operation', 'Label', 'Function', 'Required', 'Mutates'])\n"
            "        self.operation_table.setSelectionBehavior(QTableWidget.SelectRows)\n"
            "        self.operation_table.setSelectionMode(QTableWidget.SingleSelection)\n"
            "        self.args_editor = QPlainTextEdit()\n"
            "        self.args_editor.setPlaceholderText('JSON arguments for the selected operation')\n"
            "        self.run_button = QPushButton('Run / Queue')\n"
            "        self.progress_label = QLabel('Ready')\n"
            "        self.result_editor = QPlainTextEdit()\n"
            "        self.result_editor.setReadOnly(True)\n"
            "        self._build_layout()\n"
            "        self.host_filter.currentTextChanged.connect(self.apply_filters)\n"
            "        self.search_edit.textChanged.connect(self.apply_filters)\n"
            "        self.operation_table.itemSelectionChanged.connect(self.populate_args_template)\n"
            "        self.run_button.clicked.connect(self.run_selected_operation)\n"
            "        self.refresh_catalog()\n\n"
            "    def _build_layout(self):\n"
            "        filters = QHBoxLayout()\n"
            "        filters.addWidget(QLabel('Host'))\n"
            "        filters.addWidget(self.host_filter)\n"
            "        filters.addWidget(QLabel('Search'))\n"
            "        filters.addWidget(self.search_edit, 1)\n"
            "        layout = QVBoxLayout(self)\n"
            "        layout.addLayout(filters)\n"
            "        layout.addWidget(self.operation_table, 2)\n"
            "        layout.addWidget(QLabel('Arguments'))\n"
            "        layout.addWidget(self.args_editor, 1)\n"
            "        layout.addWidget(self.run_button)\n"
            "        layout.addWidget(self.progress_label)\n"
            "        layout.addWidget(self.result_editor, 1)\n\n"
            "    def refresh_catalog(self):\n"
            "        rows = [OperationRow.from_unreal(item) for item in operation_catalog()]\n"
            "        for host in ('blender', 'maya'):\n"
            "            rows.extend(OperationRow.from_dcc(host, item) for item in dcc_operation_registry(host).values())\n"
            "        self._all_rows = rows\n"
            "        self.apply_filters()\n"
            "        return len(rows)\n\n"
            "    def apply_filters(self, *_):\n"
            "        host = self.host_filter.currentText() if hasattr(self.host_filter, 'currentText') else 'all'\n"
            "        query = self.search_edit.text().strip().lower() if hasattr(self.search_edit, 'text') else ''\n"
            "        visible = []\n"
            "        for row in self._all_rows:\n"
            "            haystack = ' '.join([row.host, row.key, row.label, row.function, ' '.join(row.required), ' '.join(row.optional)]).lower()\n"
            "            if host != 'all' and row.host != host:\n"
            "                continue\n"
            "            if query and query not in haystack:\n"
            "                continue\n"
            "            visible.append(row)\n"
            "        self._set_rows(visible)\n"
            "        return len(visible)\n\n"
            "    def _set_rows(self, rows: list[OperationRow]):\n"
            "        self._visible_rows = list(rows)\n"
            "        self.operation_table.setRowCount(len(self._visible_rows))\n"
            "        for index, row in enumerate(self._visible_rows):\n"
            "            values = [row.host, row.key, row.label, row.function, ', '.join(row.required), 'yes' if row.mutates_project else 'no']\n"
            "            for column, value in enumerate(values):\n"
            "                item = QTableWidgetItem(value)\n"
            "                item.setData(Qt.UserRole, row)\n"
            "                self.operation_table.setItem(index, column, item)\n"
            "        if self._visible_rows:\n"
            "            self.operation_table.selectRow(0)\n"
            "            self.populate_args_template()\n"
            "        else:\n"
            "            self.args_editor.setPlainText('{}')\n"
            "        return len(self._visible_rows)\n\n"
            "    def _selected_row(self) -> OperationRow:\n"
            "        index = self.operation_table.currentRow()\n"
            "        if index < 0 or index >= len(self._visible_rows):\n"
            "            raise ValueError('operation_not_selected')\n"
            "        return self._visible_rows[index]\n\n"
            "    def populate_args_template(self):\n"
            "        row = self._selected_row()\n"
            "        template = {name: '' for name in (*row.required, *row.optional)}\n"
            "        self.args_editor.setPlainText(json.dumps(template, indent=2))\n"
            "        return template\n\n"
            "    def run_selected_operation(self):\n"
            "        try:\n"
            "            row = self._selected_row()\n"
            "        except ValueError as exc:\n"
            "            self._on_finished(False, {'error': str(exc)})\n"
            "            return\n"
            "        self.run_button.setEnabled(False)\n"
            "        self.progress_label.setText(f'Queued {row.host}:{row.key}')\n"
            "        self.worker = OperationRunWorker(row.host, row.key, self.args_editor.toPlainText(), self.backend)\n"
            "        self.worker.progress.connect(self.progress_label.setText)\n"
            "        self.worker.finished.connect(self._on_finished)\n"
            "        self.worker.start()\n\n"
            "    def _on_finished(self, ok: bool, payload: object):\n"
            "        self.run_button.setEnabled(True)\n"
            "        self.progress_label.setText('Complete' if ok else 'Failed')\n"
            "        self.result_editor.setPlainText(json.dumps({'ok': ok, 'result': payload}, indent=2, default=str))\n"
        )
    elif wants_rollback_journal:
        expected_code_dependencies = ["project edit transaction scan", "existing write/apply boundaries", "focused rollback recovery tests"]
        expected_code_payload = {
            "expected_files": [
                {"path": "tech_connector/services/project_edit_transaction_service.py", "purpose": "Integrate journal creation, snapshots, and rollback into multi-file edit transactions."},
                {"path": "tech_connector/services/project_edit_rollback_journal_service.py", "purpose": "Typed rollback journal records and recovery helpers."},
                {"path": "tech_connector/examples/tests/test_project_edit_rollback_journal_service.py", "purpose": "Regression coverage for failed write recovery and multi-file rollback."},
            ],
            "expected_imports": ["dataclasses.dataclass", "pathlib.Path", "json", "time", "typing.Any"],
            "expected_classes": [
                {"name": "RollbackJournalEntry", "kind": "dataclass", "fields": ["path", "before_hash", "after_hash", "backup_path", "operation", "timestamp"]},
                {"name": "ProjectEditRollbackJournal", "kind": "service", "methods": ["begin()", "snapshot_file(path)", "record_change(path)", "rollback()", "finalize()"]},
            ],
            "method_contracts": [
                {"method": "ProjectEditRollbackJournal.begin", "inputs": ["transaction id", "project root"], "side_effects": ["creates journal directory", "opens manifest"], "errors": ["journal_path_unwritable"], "returns_or_emits": ["journal id"]},
                {"method": "ProjectEditRollbackJournal.snapshot_file", "inputs": ["Path"], "side_effects": ["copies before image", "records before hash"], "errors": ["path_outside_project", "file_missing"], "returns_or_emits": ["RollbackJournalEntry"]},
                {"method": "ProjectEditRollbackJournal.record_change", "inputs": ["Path"], "side_effects": ["stores after hash", "updates manifest"], "errors": ["snapshot_missing"], "returns_or_emits": ["updated entry"]},
                {"method": "ProjectEditRollbackJournal.rollback", "inputs": ["journal entries"], "side_effects": ["restores backups", "removes newly-created files when safe"], "errors": ["hash_mismatch", "restore_failed"], "returns_or_emits": ["rollback evidence"]},
                {"method": "ProjectEditRollbackJournal.finalize", "inputs": ["validation result"], "side_effects": ["marks journal committed or retained-for-debug"], "errors": [], "returns_or_emits": ["final journal status"]},
            ],
            "representative_code": (
                "@dataclass(frozen=True)\n"
                "class RollbackJournalEntry:\n"
                "    path: str\n"
                "    before_hash: str\n"
                "    after_hash: str = ''\n"
                "    backup_path: str = ''\n\n"
                "class ProjectEditRollbackJournal:\n"
                "    def __init__(self, project_root: Path, journal_root: Path):\n"
                "        self.project_root = project_root.resolve()\n"
                "        self.journal_root = journal_root\n"
                "        self.entries: dict[Path, RollbackJournalEntry] = {}\n\n"
                "    def snapshot_file(self, path: Path) -> RollbackJournalEntry:\n"
                "        target = path.resolve()\n"
                "        if self.project_root not in target.parents and target != self.project_root:\n"
                "            raise ValueError('path_outside_project')\n"
                "        before_hash = _sha256(target) if target.exists() else ''\n"
                "        backup_path = self._backup_path_for(target)\n"
                "        if target.exists():\n"
                "            backup_path.parent.mkdir(parents=True, exist_ok=True)\n"
                "            shutil.copy2(target, backup_path)\n"
                "        entry = RollbackJournalEntry(str(target), before_hash, backup_path=str(backup_path))\n"
                "        self.entries[target] = entry\n"
                "        self._write_manifest()\n"
                "        return entry\n\n"
                "    def record_change(self, path: Path) -> None:\n"
                "        target = path.resolve()\n"
                "        entry = self.entries[target]\n"
                "        self.entries[target] = replace(entry, after_hash=_sha256(target) if target.exists() else '')\n"
                "        self._write_manifest()\n\n"
                "    def rollback(self) -> dict[str, Any]:\n"
                "        restored = []\n"
                "        for target, entry in reversed(self.entries.items()):\n"
                "            if entry.backup_path and Path(entry.backup_path).exists():\n"
                "                shutil.copy2(entry.backup_path, target)\n"
                "            elif target.exists():\n"
                "                target.unlink()\n"
                "            restored.append(str(target))\n"
                "        return {'status': 'rolled_back', 'restored': restored}"
            ),
            "integration_points": [
                "Wrap multi-file project edits before first write.",
                "Record backup paths and hashes before mutation.",
                "On failed write/test validation, restore files from journal and report rollback evidence.",
            ],
            "repo_grounding": [
                {"purpose": "Edit transaction boundary", "source": "code.inspect_symbols result for apply_patch/project edit services"},
                {"purpose": "Existing result shape", "source": "neighboring service functions returning structured dict status"},
                {"purpose": "Test style", "source": "focused unittest modules under tech_connector/examples/tests"},
            ],
            "pre_patch_review": [
                "Every mutated path is resolved under the active project root before snapshot or restore.",
                "Existing files are copied before first write; newly-created files can be removed on rollback.",
                "Manifest writes are deterministic JSON and include before/after hashes.",
                "Rollback returns explicit restored paths and failures.",
                "Tests simulate a failed second write and verify the first file is restored.",
            ],
            "acceptance_tests": [
                {"name": "snapshots_existing_file_before_write", "asserts": ["backup exists", "before hash matches original"]},
                {"name": "rolls_back_after_failed_second_write", "asserts": ["first file restored", "new file removed or marked", "failure evidence returned"]},
                {"name": "rejects_paths_outside_project", "asserts": ["ValueError path_outside_project", "no backup written"]},
                {"name": "manifest_is_deterministic_json", "asserts": ["entries include path/before_hash/after_hash/backup_path", "stable ordering"]},
            ],
            "quality_gates": [
                {"gate": "syntax", "tool": "python -m py_compile", "pass_condition": "rollback journal service and transaction integration compile"},
                {"gate": "path_safety", "tool": "unit tests", "pass_condition": "outside-root paths are rejected before filesystem mutation"},
                {"gate": "rollback_integrity", "tool": "unit tests", "pass_condition": "hashes and restored file contents match pre-write state"},
                {"gate": "transaction_integration", "tool": "focused service tests", "pass_condition": "failed write invokes rollback and reports evidence"},
            ],
            "implementation_risks": [
                {"risk": "existing edit service may not have a single transaction boundary", "mitigation": "wrap the narrowest common apply/write function discovered by code.inspect_symbols"},
                {"risk": "newly-created files need different rollback semantics than modified files", "mitigation": "record missing before_hash and remove only paths created inside project root"},
            ],
            "readback_plan": [
                "Create a temporary project root fixture.",
                "Snapshot, mutate, and record one existing file.",
                "Simulate a later failed write.",
                "Run rollback and compare restored contents and hashes.",
                "Inspect journal manifest for deterministic recovery evidence.",
            ],
        }
    elif wants_prompt_router_evidence:
        expected_code_dependencies = ["prompt router scan", "evidence ranking scan", "deterministic fuzz fixture contract"]
        expected_code_payload = {
            "expected_files": [
                {"path": "tech_connector/services/prompt/prompt_route_service.py", "purpose": "Emit deterministic route evidence and ambiguity metadata."},
                {"path": "tech_connector/services/reasoning/evidence_ranking_service.py", "purpose": "Return structured attribution paths for target ranking."},
                {"path": "tech_connector/examples/tests/fixtures/prompt_route_fuzz_cases.json", "purpose": "Deterministic fuzz regression corpus."},
                {"path": "tech_connector/examples/tests/test_prompt_route_fuzz_corpus.py", "purpose": "Stable regression tests for fuzzy prompt routing."},
            ],
            "expected_imports": ["dataclasses.dataclass", "json", "typing.Any"],
            "expected_classes": [
                {"name": "RouteEvidence", "kind": "dataclass", "fields": ["route", "score", "signals", "ambiguity"]},
                {"name": "AttributionPath", "kind": "dataclass", "fields": ["type", "source", "query_fragment", "evidence", "weight"]},
                {"name": "PromptRouteFuzzCase", "kind": "fixture schema", "fields": ["seed", "mutation", "expected_route", "expected_signals"]},
            ],
            "method_contracts": [
                {"method": "load_prompt_route_fuzz_cases", "inputs": ["fixture path"], "side_effects": [], "errors": ["invalid_fixture_schema"], "returns_or_emits": ["PromptRouteFuzzCase list"]},
                {"method": "route_with_evidence", "inputs": ["prompt text"], "side_effects": [], "errors": ["empty_prompt"], "returns_or_emits": ["RouteEvidence"]},
                {"method": "rank_target_with_attributions", "inputs": ["query", "candidate targets", "active context"], "side_effects": [], "errors": [], "returns_or_emits": ["ranked targets with AttributionPath list"]},
                {"method": "test_fuzz_corpus_routes", "inputs": ["deterministic fixture corpus"], "side_effects": [], "errors": ["route mismatch", "missing required evidence signal"], "returns_or_emits": ["stable regression result"]},
            ],
            "representative_code": (
                "@dataclass(frozen=True)\n"
                "class RouteEvidence:\n"
                "    route: str\n"
                "    score: float\n"
                "    signals: dict[str, Any]\n"
                "    ambiguity: dict[str, Any]\n\n"
                "@dataclass(frozen=True)\n"
                "class AttributionPath:\n"
                "    type: str\n"
                "    source: str\n"
                "    query_fragment: str\n"
                "    evidence: str\n"
                "    weight: float\n\n"
                "@dataclass(frozen=True)\n"
                "class PromptRouteFuzzCase:\n"
                "    seed: str\n"
                "    mutation: str\n"
                "    expected_route: str\n"
                "    expected_signals: tuple[str, ...]\n\n"
                "def route_with_evidence(prompt: str) -> RouteEvidence:\n"
                "    signals = collect_route_signals(prompt)\n"
                "    evidence = rank_route_candidates(signals)\n"
                "    return RouteEvidence(route=evidence.route, score=evidence.score, signals=signals, ambiguity=evidence.ambiguity)\n\n"
                "def load_prompt_route_fuzz_cases(path: Path) -> list[PromptRouteFuzzCase]:\n"
                "    raw_cases = json.loads(path.read_text(encoding='utf-8'))\n"
                "    return [PromptRouteFuzzCase(**item) for item in raw_cases]\n\n"
                "def rank_target_with_attributions(query: str, candidates: list[Any], context: dict[str, Any]) -> list[Any]:\n"
                "    ranked = []\n"
                "    for candidate in candidates:\n"
                "        attributions = collect_attribution_paths(query, candidate, context)\n"
                "        ranked.append(with_score(candidate, sum(path.weight for path in attributions), attributions))\n"
                "    return sorted(ranked, key=lambda item: item.score, reverse=True)"
            ),
            "integration_points": [
                "Keep fuzz generation optional; promote reviewed mutations into the deterministic fixture.",
                "Expose top attribution paths in route metadata and compact planner output.",
                "Assert both selected route and defensible evidence in tests.",
            ],
            "repo_grounding": [
                {"purpose": "Router implementation", "source": "tech_connector/services/prompt/prompt_route_service.py"},
                {"purpose": "Ranking implementation", "source": "tech_connector/services/reasoning/evidence_ranking_service.py"},
                {"purpose": "Regression corpus", "source": "tech_connector/examples/tests/fixtures/prompt_route_fuzz_cases.json"},
            ],
            "pre_patch_review": [
                "Ollama/generated fuzzing is optional and never required for normal deterministic tests.",
                "Fixture cases include seed, mutation, expected route, and required evidence signals.",
                "Attribution paths are structured data, not prose-only explanations.",
                "UI/debug renderers consume the same attribution payload used by tests.",
                "Tests assert both selected route and at least one defensible attribution signal.",
            ],
            "acceptance_tests": [
                {"name": "deterministic_fuzz_corpus_routes", "asserts": ["each mutation yields expected route", "no network or Ollama dependency"]},
                {"name": "route_evidence_contains_required_signals", "asserts": ["signals include matched trigger/source", "ambiguity is explicit"]},
                {"name": "target_ranking_returns_attribution_paths", "asserts": ["top target includes semantic/open-tab/cursor paths when available"]},
                {"name": "weak_signals_are_debug_only", "asserts": ["compact UI payload limits top reasons", "full trace remains available"]},
            ],
            "quality_gates": [
                {"gate": "determinism", "tool": "unit tests", "pass_condition": "fixture tests pass repeatedly without model calls"},
                {"gate": "schema", "tool": "fixture validation test", "pass_condition": "all fuzz cases and attribution paths match schema"},
                {"gate": "explainability", "tool": "route/ranking tests", "pass_condition": "selected route/target has at least one defensible attribution"},
                {"gate": "performance", "tool": "timed focused tests", "pass_condition": "corpus route test stays under local timeout budget"},
            ],
            "implementation_risks": [
                {"risk": "attribution payload can become noisy", "mitigation": "store full trace but expose top weighted reasons by default"},
                {"risk": "fuzz generator nondeterminism can poison CI", "mitigation": "keep generator optional and promote reviewed cases into checked-in corpus"},
            ],
            "readback_plan": [
                "Load deterministic fuzz fixture corpus.",
                "Route each mutation and assert expected route plus required evidence signals.",
                "Rank sample blueprint targets and assert structured AttributionPath output.",
                "Render compact trace payload and verify top reasons are bounded.",
            ],
        }
    else:
        expected_code_dependencies = ["code.search_project output", "code.inspect_symbols output", "existing service/test conventions"]
        expected_code_payload = {
            "expected_files": [
                {"path": "resolved source module from code.inspect_symbols", "purpose": "Implement the requested behavior in the owning module."},
                {"path": "resolved focused test module from code.inspect_symbols", "purpose": "Prove the requested behavior and edge case."},
            ],
            "expected_imports": ["imports resolved from existing module patterns"],
            "expected_classes": [
                {"name": "ResolvedImplementationUnit", "kind": "function/class/service", "methods": ["inspect current contract", "apply scoped behavior", "return structured result"]},
            ],
            "method_contracts": [
                {"method": "resolved_entrypoint", "inputs": ["requested behavior", "resolved project context"], "side_effects": ["only scoped file changes from patch plan"], "errors": ["missing_target", "ambiguous_contract", "validation_failed"], "returns_or_emits": ["structured result"]},
                {"method": "focused_regression_test", "inputs": ["requested behavior", "edge case"], "side_effects": [], "errors": ["assertion mismatch"], "returns_or_emits": ["deterministic test proof"]},
            ],
            "representative_code": (
                "def requested_behavior_entrypoint(...):\n"
                "    current = inspect_existing_state(...)\n"
                "    result = apply_scoped_change(current, ...)\n"
                "    return validate_and_report(result)"
            ),
            "integration_points": ["Use existing service boundaries and focused tests discovered by code.inspect_symbols."],
            "repo_grounding": [
                {"purpose": "Source ownership", "source": "code.inspect_symbols result for target module"},
                {"purpose": "Call contract", "source": "callers and tests discovered before patching"},
            ],
            "pre_patch_review": [
                "Target file, owner symbol, and focused test file are resolved before writing.",
                "All planned imports are already present nearby or explicitly added.",
                "The representative code has no ellipsis in the final patch plan.",
                "Validation command list is specific enough to run without broad discovery.",
            ],
            "acceptance_tests": [
                {"name": "focused_behavior_regression", "asserts": ["requested behavior succeeds", "main edge case is covered"]},
                {"name": "unchanged_contracts_remain_compatible", "asserts": ["existing callers/tests still pass"]},
            ],
            "quality_gates": [
                {"gate": "syntax", "tool": "python -m py_compile", "pass_condition": "changed Python files compile"},
                {"gate": "focused_tests", "tool": "python -m unittest or project runner", "pass_condition": "focused regression tests pass"},
                {"gate": "patch_scope", "tool": "changed-file review", "pass_condition": "changed files match patch plan"},
            ],
            "quality_bar": {
                "target_level": "first_try_usable_generated_code",
                "current_level": "planned_code_with_pre_patch_validation",
                "confidence": "medium",
                "proven": [
                    "Plan includes expected files, imports, classes/method contracts, representative code, and focused acceptance tests.",
                    "Generated code must pass code.validate_expected_code before patching.",
                    "Patch must be applied and imported in a disposable workspace before it can be marked truly passing.",
                ],
                "not_yet_proven": [
                    "No live DCC/editor host smoke has run unless the host bridge is connected.",
                    "Real UI rendering is only proven after a PySide/host-capable runtime test.",
                ],
                "promotion_requirements": [
                    "Run generated patch validation in a temp workspace.",
                    "Run focused tests and host smoke/readback where applicable.",
                    "Capture exact output, errors, and rollback instructions.",
                ],
                "blocks_first_try_claim": True,
            },
            "implementation_risks": [
                {"risk": "generic code prompt may still be under-specified", "mitigation": "block patch if target file/symbol/test cannot be resolved"},
            ],
            "readback_plan": [
                "Inspect resolved source and test files.",
                "Apply patch only after imports and owner symbols are known.",
                "Run syntax and focused tests.",
                "Report remaining ambiguity or validation failures with exact paths.",
            ],
        }
    common = {
        "callable": action_type,
        "implementation_status": "registered_or_adapter_required",
        "capability": capability,
        "host": host,
        "source_prompt": prompt,
        "required_context": [
            "active project root",
            "focused target resolution",
            "operation registry entry",
            "rollback/validation policy",
        ],
        "arguments": {},
        "dependencies": [],
        "expected_outputs": [],
        "readback_validation": list(item.get("validates_with") or []),
        "fallback": "stop and report missing callable, target, permission, or validation evidence before execution",
    }
    plans: dict[str, dict[str, Any]] = {
        "code.search_project": {
            "callable": "tech_connector.services.code_operation_service.search_project",
            "implementation_status": "registered_operation",
            "arguments": {
                "root": "active project root",
                "search_terms": (
                    [
                        "QWidget",
                        "QThread",
                        "Signal",
                        "QPlainTextEdit",
                        "QTableWidget",
                        "operation_catalog",
                        "dcc_operation_registry",
                        "unreal_operation_payload",
                    ]
                    if wants_qt_operation_runner
                    else [
                        "rollback journal",
                        "prompt router",
                        "fuzz regression",
                        "attribution paths",
                        "service tests",
                    ]
                ),
                "file_globs": ["*.py", "*.json", "*.md"],
                "exclude_globs": ["**/.*/**", "**/__pycache__/**", "**/*.sqlite", "**/*.sqlite-*"],
                "prompt": prompt,
            },
            "dependencies": ["project root", "file index or rg-compatible search"],
            "expected_outputs": ["candidate source files", "candidate test files", "matched terms"],
        },
        "code.inspect_symbols": {
            "callable": "tech_connector.services.code_operation_service.inspect_symbols",
            "implementation_status": "registered_operation",
            "arguments": {
                "source_files": "candidate files from code.search_project",
                "symbol_queries": (
                    [
                        "OperationRunnerPanel",
                        "QWidget/QDialog tab panels",
                        "QThread worker patterns",
                        "operation_catalog",
                        "dcc_operation_registry",
                        "unreal_operation_payload",
                        "DccExecutionRequest",
                    ]
                    if wants_qt_operation_runner
                    else ["service classes", "route/planner functions", "test cases", "dataclasses/contracts"]
                ),
                "include_callers": True,
                "include_tests": True,
            },
            "dependencies": ["code.search_project output", "AST/symbol index or direct file reads"],
            "expected_outputs": ["symbols", "call sites", "existing behavior summary", "test target list"],
        },
        "code.plan_patch": {
            "callable": "tech_connector.services.code_operation_service.plan_patch",
            "implementation_status": "registered_operation",
            "arguments": {
                "requested_behavior": prompt,
                "target_files": (
                    [
                        "tech_connector/ui/operation_runner_panel.py",
                        "tech_connector/app/main_window_ui.py or existing tab registration module",
                        "tech_connector/examples/tests/test_operation_runner_panel.py",
                    ]
                    if wants_qt_operation_runner
                    else "resolved from code.inspect_symbols"
                ),
                "edit_policy": "scoped patch only; preserve unrelated user changes",
                "rollback_policy": "record changed files and validation command before mutation",
                "ui_contract": (
                    {
                        "widget": "OperationRunnerPanel(QWidget)",
                        "worker": "OperationRunWorker(QThread)",
                        "controls": ["host combo", "search field", "operation table", "JSON args editor", "run/queue button", "progress/result output"],
                        "non_blocking": "all execution/queue preparation goes through QThread signals",
                        "dispatch": ["unreal_operation_payload", "dcc_operation_registry", "DccExecutionRequest or existing route handler"],
                    }
                    if wants_qt_operation_runner
                    else {}
                ),
            },
            "dependencies": ["code.inspect_symbols output", "current file contents"],
            "expected_outputs": ["patch plan", "changed file list", "validation command list"],
        },
        "code.plan_expected_code": {
            "callable": "tech_connector.services.code_operation_service.plan_expected_code",
            "implementation_status": "registered_operation",
            "arguments": {
                "requested_behavior": prompt,
                **expected_code_payload,
            },
            "dependencies": expected_code_dependencies,
            "expected_outputs": ["expected code artifact", "file/class/method plan", "representative implementation skeleton"],
        },
        "code.validate_expected_code": {
            "callable": "tech_connector.services.code_operation_service.validate_expected_code",
            "implementation_status": "registered_operation",
            "arguments": {
                "representative_code": expected_code_payload.get("representative_code", ""),
                "expected_classes": expected_code_payload.get("expected_classes", []),
                "method_contracts": expected_code_payload.get("method_contracts", []),
                "quality_gates": expected_code_payload.get("quality_gates", []),
                "acceptance_tests": expected_code_payload.get("acceptance_tests", []),
                "executable_fixture_code": (
                    "class Signal:\n"
                    "    def __init__(self, *args):\n"
                    "        self.events = []\n"
                    "        self.callbacks = []\n"
                    "    def emit(self, *args):\n"
                    "        self.events.append(args)\n"
                    "        for callback in self.callbacks:\n"
                    "            callback(*args)\n"
                    "    def connect(self, callback):\n"
                    "        self.callbacks.append(callback)\n\n"
                    "class QThread:\n"
                    "    def start(self):\n"
                    "        self.run()\n\n"
                    "    def wait(self, timeout=0):\n"
                    "        return True\n\n"
                    "class Qt:\n"
                    "    UserRole = 32\n\n"
                    "class QWidget:\n"
                    "    def __init__(self, *args):\n"
                    "        self.layout = None\n\n"
                    "class QHBoxLayout:\n"
                    "    def __init__(self, *args):\n"
                    "        self.children = []\n"
                    "    def addWidget(self, widget, *args):\n"
                    "        self.children.append(widget)\n"
                    "    def addLayout(self, layout, *args):\n"
                    "        self.children.append(layout)\n\n"
                    "class QVBoxLayout(QHBoxLayout):\n"
                    "    pass\n\n"
                    "class QLabel:\n"
                    "    def __init__(self, text=''):\n"
                    "        self._text = text\n"
                    "    def setText(self, text):\n"
                    "        self._text = text\n"
                    "    def text(self):\n"
                    "        return self._text\n\n"
                    "class QComboBox:\n"
                    "    def __init__(self):\n"
                    "        self.items = []\n"
                    "        self.index = 0\n"
                    "        self.currentTextChanged = Signal(str)\n"
                    "    def addItems(self, items):\n"
                    "        self.items.extend(items)\n"
                    "    def currentText(self):\n"
                    "        return self.items[self.index] if self.items else ''\n"
                    "    def setCurrentText(self, text):\n"
                    "        if text in self.items:\n"
                    "            self.index = self.items.index(text)\n"
                    "            self.currentTextChanged.emit(text)\n\n"
                    "class QLineEdit:\n"
                    "    def __init__(self):\n"
                    "        self._text = ''\n"
                    "        self.textChanged = Signal(str)\n"
                    "    def setPlaceholderText(self, text):\n"
                    "        self.placeholder = text\n"
                    "    def setText(self, text):\n"
                    "        self._text = text\n"
                    "        self.textChanged.emit(text)\n"
                    "    def text(self):\n"
                    "        return self._text\n\n"
                    "class QPlainTextEdit:\n"
                    "    def __init__(self):\n"
                    "        self._text = ''\n"
                    "        self.read_only = False\n"
                    "    def setPlaceholderText(self, text):\n"
                    "        self.placeholder = text\n"
                    "    def setReadOnly(self, value):\n"
                    "        self.read_only = bool(value)\n"
                    "    def setPlainText(self, text):\n"
                    "        self._text = text\n"
                    "    def appendPlainText(self, text):\n"
                    "        self._text = f'{self._text}\\n{text}'.strip()\n"
                    "    def toPlainText(self):\n"
                    "        return self._text\n\n"
                    "class QPushButton:\n"
                    "    def __init__(self, text=''):\n"
                    "        self.text = text\n"
                    "        self.enabled = True\n"
                    "        self.clicked = Signal()\n"
                    "    def setEnabled(self, enabled):\n"
                    "        self.enabled = bool(enabled)\n"
                    "    def isEnabled(self):\n"
                    "        return self.enabled\n\n"
                    "class QTableWidgetItem:\n"
                    "    def __init__(self, text=''):\n"
                    "        self._text = text\n"
                    "        self.data_values = {}\n"
                    "    def text(self):\n"
                    "        return self._text\n"
                    "    def setData(self, role, value):\n"
                    "        self.data_values[role] = value\n"
                    "    def data(self, role):\n"
                    "        return self.data_values.get(role)\n\n"
                    "class QTableWidget:\n"
                    "    SelectRows = 1\n"
                    "    SingleSelection = 1\n"
                    "    def __init__(self, rows=0, columns=0):\n"
                    "        self.rows = rows\n"
                    "        self.columns = columns\n"
                    "        self.items = {}\n"
                    "        self.current_row = -1\n"
                    "        self.itemSelectionChanged = Signal()\n"
                    "    def setHorizontalHeaderLabels(self, labels):\n"
                    "        self.headers = list(labels)\n"
                    "    def setSelectionBehavior(self, mode):\n"
                    "        self.selection_behavior = mode\n"
                    "    def setSelectionMode(self, mode):\n"
                    "        self.selection_mode = mode\n"
                    "    def setRowCount(self, count):\n"
                    "        self.rows = count\n"
                    "    def setItem(self, row, column, item):\n"
                    "        self.items[(row, column)] = item\n"
                    "    def selectRow(self, row):\n"
                    "        self.current_row = row\n"
                    "        self.itemSelectionChanged.emit()\n"
                    "    def currentRow(self):\n"
                    "        return self.current_row\n\n"
                    "def operation_catalog():\n"
                    "    return [{'key': 'blueprint.scan', 'label': 'Scan Blueprint', 'function': 'unreal_tools.blueprint.scan', 'required_args': ['asset_path'], 'optional_args': [], 'mutates_project': False}]\n\n"
                    "class DccOperation:\n"
                    "    key = 'blender.scan_animation'\n"
                    "    label = 'Scan Blender Animation'\n"
                    "    function = 'tech_connector.game_engine.integration.dcc_operation_service.blender.scan_animation'\n"
                    "    required_args = ('armature_name',)\n"
                    "    optional_args = ()\n"
                    "    mutates_project = False\n\n"
                    "def dcc_operation_registry(host):\n"
                    "    return {'blender.scan_animation': DccOperation()}\n\n"
                    "def unreal_operation_payload(operation_key, params):\n"
                    "    return {'operation': operation_key, 'kwargs': params}\n\n"
                    "class CommandRouter:\n"
                    "    def __init__(self):\n"
                    "        self.calls = []\n"
                    "    def execute_unreal_operation(self, operation_key, params):\n"
                    "        self.calls.append(('unreal', operation_key, params))\n"
                    "        return 'Fake Unreal Backend', True, {'status': 'backend_called', 'operation': operation_key, 'params': params}\n"
                    "    def execute_registered_dcc_operation(self, host, operation_key, params):\n"
                    "        self.calls.append((host, operation_key, params))\n"
                    "        return f'{host.title()} Backend', True, {'status': 'dcc_backend_called', 'host': host, 'operation': operation_key, 'params': params}\n"
                    if wants_qt_operation_runner
                    else ""
                ),
                "smoke_test_code": (
                    "row = OperationRow.from_unreal(operation_catalog()[0])\n"
                    "assert row.host == 'unreal'\n"
                    "worker = OperationRunWorker()\n"
                    "worker.host = 'unreal'\n"
                    "worker.operation_key = 'blueprint.scan'\n"
                    "worker.args_json = '{\"asset_path\": \"/Game/Test/BP_Test\"}'\n"
                    "worker_results = []\n"
                    "worker.finished.connect(lambda ok, payload: worker_results.append((ok, payload)))\n"
                    "worker.run()\n"
                    "assert worker_results[-1][0] is True\n"
                    "assert worker_results[-1][1]['result']['status'] == 'backend_called'\n"
                    "bad_worker = OperationRunWorker()\n"
                    "bad_worker.host = 'unreal'\n"
                    "bad_worker.operation_key = 'blueprint.scan'\n"
                    "bad_worker.args_json = '{bad json}'\n"
                    "bad_results = []\n"
                    "bad_worker.finished.connect(lambda ok, payload: bad_results.append((ok, payload)))\n"
                    "bad_worker.run()\n"
                    "assert bad_results[-1][0] is False\n"
                    "assert bad_results[-1][1]['error'] == 'invalid_json'\n"
                    "panel = OperationRunnerPanel()\n"
                    "assert len(panel._visible_rows) >= 1\n"
                    "panel.search_edit.setText('blueprint')\n"
                    "assert panel.apply_filters() == 1\n"
                    "template = panel.populate_args_template()\n"
                    "assert 'asset_path' in template\n"
                    "panel.args_editor.setPlainText('{\"asset_path\": \"/Game/Test/BP_Test\"}')\n"
                    "panel.run_selected_operation()\n"
                    "panel.worker.wait(5000)\n"
                    "assert panel.run_button.isEnabled() is True\n"
                    "assert 'backend_called' in panel.result_editor.toPlainText()\n"
                    "panel.search_edit.setText('')\n"
                    "panel.host_filter.setCurrentText('blender')\n"
                    "assert panel.apply_filters() == 1\n"
                    "panel.operation_table.selectRow(0)\n"
                    "template = panel.populate_args_template()\n"
                    "assert 'armature_name' in template\n"
                    "panel.args_editor.setPlainText('{\"armature_name\": \"MannyRig\"}')\n"
                    "panel.run_selected_operation()\n"
                    "panel.worker.wait(5000)\n"
                    "assert 'dcc_backend_called' in panel.result_editor.toPlainText()\n"
                    if wants_qt_operation_runner
                    else ""
                ),
                "allow_exec": wants_qt_operation_runner,
            },
            "dependencies": ["code.plan_expected_code output", "safe disposable fixture for generated code"],
            "expected_outputs": ["static validation result", "mocked smoke test result when available", "quality gate evidence"],
        },
        "code.validate_patch_in_temp_workspace": {
            "callable": "tech_connector.services.code_operation_service.validate_patch_in_temp_workspace",
            "implementation_status": "registered_operation",
            "arguments": {
                "source_root": ".",
                "expected_files": expected_code_payload.get("expected_files", []),
                "patch_files": (
                    [
                        {
                            "path": "tech_connector/ui/operation_runner_panel.py",
                            "content": (
                                "from __future__ import annotations\n\n"
                                "import json\n"
                                "from dataclasses import dataclass\n"
                                "from typing import Any\n\n"
                                "try:\n"
                                "    from PySide6.QtCore import Qt, QThread, Signal\n"
                                "    from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget\n"
                                "except Exception:\n"
                                "    class Qt:\n"
                                "        UserRole = 32\n"
                                "    class Signal:\n"
                                "        def __init__(self, *args):\n"
                                "            self.events = []\n"
                                "            self.callbacks = []\n"
                                "        def emit(self, *args):\n"
                                "            self.events.append(args)\n"
                                "            for callback in self.callbacks:\n"
                                "                callback(*args)\n"
                                "        def connect(self, callback):\n"
                                "            self.callbacks.append(callback)\n"
                                "    class QThread:\n"
                                "        def start(self):\n"
                                "            self.run()\n"
                                "        def wait(self, timeout=0):\n"
                                "            return True\n"
                                "    class QWidget:\n"
                                "        def __init__(self, *args):\n"
                                "            self.layout = None\n\n"
                                "    class QComboBox:\n"
                                "        def __init__(self):\n"
                                "            self.items = []\n"
                                "            self.index = 0\n"
                                "            self.currentTextChanged = Signal(str)\n"
                                "        def addItems(self, items):\n"
                                "            self.items.extend(items)\n"
                                "        def currentText(self):\n"
                                "            return self.items[self.index] if self.items else ''\n"
                                "        def setCurrentText(self, text):\n"
                                "            if text in self.items:\n"
                                "                self.index = self.items.index(text)\n"
                                "                self.currentTextChanged.emit(text)\n"
                                "    class QHBoxLayout:\n"
                                "        def __init__(self, *args):\n"
                                "            self.children = []\n"
                                "        def addWidget(self, widget, *args):\n"
                                "            self.children.append(widget)\n"
                                "        def addLayout(self, layout, *args):\n"
                                "            self.children.append(layout)\n"
                                "    class QLabel:\n"
                                "        def __init__(self, text=''):\n"
                                "            self._text = text\n"
                                "        def setText(self, text):\n"
                                "            self._text = text\n"
                                "        def text(self):\n"
                                "            return self._text\n"
                                "    class QLineEdit:\n"
                                "        def __init__(self):\n"
                                "            self._text = ''\n"
                                "            self.textChanged = Signal(str)\n"
                                "        def setPlaceholderText(self, text):\n"
                                "            self.placeholder = text\n"
                                "        def setText(self, text):\n"
                                "            self._text = text\n"
                                "            self.textChanged.emit(text)\n"
                                "        def text(self):\n"
                                "            return self._text\n"
                                "    class QPlainTextEdit:\n"
                                "        def __init__(self):\n"
                                "            self._text = ''\n"
                                "        def setPlaceholderText(self, text):\n"
                                "            self.placeholder = text\n"
                                "        def setReadOnly(self, value):\n"
                                "            self.read_only = bool(value)\n"
                                "        def setPlainText(self, text):\n"
                                "            self._text = text\n"
                                "        def appendPlainText(self, text):\n"
                                "            self._text = f'{self._text}\\n{text}'.strip()\n"
                                "        def toPlainText(self):\n"
                                "            return self._text\n"
                                "    class QPushButton:\n"
                                "        def __init__(self, text=''):\n"
                                "            self.text = text\n"
                                "            self.enabled = True\n"
                                "            self.clicked = Signal()\n"
                                "        def setEnabled(self, enabled):\n"
                                "            self.enabled = bool(enabled)\n"
                                "        def isEnabled(self):\n"
                                "            return self.enabled\n"
                                "    class QTableWidget:\n"
                                "        SelectRows = 1\n"
                                "        SingleSelection = 1\n"
                                "        def __init__(self, rows=0, columns=0):\n"
                                "            self.rows = rows\n"
                                "            self.columns = columns\n"
                                "            self.items = {}\n"
                                "            self.current_row = -1\n"
                                "            self.itemSelectionChanged = Signal()\n"
                                "        def setHorizontalHeaderLabels(self, labels):\n"
                                "            self.headers = list(labels)\n"
                                "        def setSelectionBehavior(self, mode):\n"
                                "            self.selection_behavior = mode\n"
                                "        def setSelectionMode(self, mode):\n"
                                "            self.selection_mode = mode\n"
                                "        def setRowCount(self, count):\n"
                                "            self.rows = count\n"
                                "        def setItem(self, row, column, item):\n"
                                "            self.items[(row, column)] = item\n"
                                "        def selectRow(self, row):\n"
                                "            self.current_row = row\n"
                                "            self.itemSelectionChanged.emit()\n"
                                "        def currentRow(self):\n"
                                "            return self.current_row\n"
                                "    class QTableWidgetItem:\n"
                                "        def __init__(self, text=''):\n"
                                "            self._text = text\n"
                                "            self.data_values = {}\n"
                                "        def text(self):\n"
                                "            return self._text\n"
                                "        def setData(self, role, value):\n"
                                "            self.data_values[role] = value\n"
                                "        def data(self, role):\n"
                                "            return self.data_values.get(role)\n"
                                "    class QVBoxLayout:\n"
                                "        def __init__(self, *args):\n"
                                "            self.children = []\n"
                                "        def addWidget(self, widget, *args):\n"
                                "            self.children.append(widget)\n"
                                "        def addLayout(self, layout, *args):\n"
                                "            self.children.append(layout)\n\n"
                                "from tech_connector.services.unreal.unreal_operation_service import operation_catalog, unreal_operation_payload\n"
                                "from tech_connector.game_engine.integration.dcc_operation_service import dcc_operation_registry\n"
                                "from tech_connector.router.command_router import CommandRouter\n\n"
                                f"{expected_code_payload.get('representative_code', '')}\n"
                            ),
                        },
                        {
                            "path": "tech_connector/services/unreal/unreal_operation_service.py",
                            "content": (
                                "def operation_catalog():\n"
                                "    return [{'key': 'blueprint.scan', 'label': 'Scan Blueprint', 'function': 'unreal_tools.blueprint.scan', 'required': ['asset_path'], 'optional': {}, 'mutates_project': False}]\n\n"
                                "def unreal_operation_payload(operation_key, params):\n"
                                "    if operation_key != 'blueprint.scan':\n"
                                "        raise ValueError('unknown operation')\n"
                                "    if not params.get('asset_path'):\n"
                                "        raise ValueError('asset_path required')\n"
                                "    return {'operation': operation_key, 'kwargs': dict(params)}\n"
                            ),
                        },
                        {
                            "path": "tech_connector/services/dcc/dcc_operation_service.py",
                            "content": (
                                "from dataclasses import dataclass\n\n"
                                "@dataclass(frozen=True)\n"
                                "class DccOperation:\n"
                                "    key: str\n"
                                "    label: str\n"
                                "    function: str\n"
                                "    required: tuple[str, ...] = ()\n"
                                "    optional: dict = None\n"
                                "    mutates_project: bool = False\n\n"
                                "def dcc_operation_registry(host):\n"
                                "    if host == 'blender':\n"
                                "        return {'blender.scan_animation': DccOperation('blender.scan_animation', 'Scan Blender Animation', 'tech_connector.game_engine.integration.dcc_operation_service.blender.scan_animation', ('armature_name',), {}, False)}\n"
                                "    if host == 'maya':\n"
                                "        return {'maya.scan_facial_rig': DccOperation('maya.scan_facial_rig', 'Scan Maya Facial Rig', 'ai_studio.maya.generated.maya_scan_facial_rig', (), {}, False)}\n"
                                "    return {}\n"
                            ),
                        },
                        {
                            "path": "tech_connector/router/command_router.py",
                            "content": (
                                "class CommandRouter:\n"
                                "    def __init__(self):\n"
                                "        self.calls = []\n"
                                "    def execute_unreal_operation(self, operation_key, params):\n"
                                "        self.calls.append(('unreal', operation_key, params))\n"
                                "        return 'Fake Unreal Backend', True, {'status': 'backend_called', 'operation': operation_key, 'params': params}\n"
                                "    def execute_registered_dcc_operation(self, host, operation_key, params):\n"
                                "        self.calls.append((host, operation_key, params))\n"
                                "        return f'{host.title()} Backend', True, {'status': 'dcc_backend_called', 'host': host, 'operation': operation_key, 'params': params}\n"
                            ),
                        },
                        {
                            "path": "tech_connector/examples/tests/test_operation_runner_panel.py",
                            "content": (
                                "import os\n"
                                "import unittest\n\n"
                                "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n\n"
                                "from PySide6.QtWidgets import QApplication\n"
                                "from tech_connector.ui.operation_runner_panel import OperationRow, OperationRunWorker, OperationRunnerPanel, operation_catalog\n\n"
                                "class TestOperationRunnerPanel(unittest.TestCase):\n"
                                "    @classmethod\n"
                                "    def setUpClass(cls):\n"
                                "        cls.app = QApplication.instance() or QApplication([])\n\n"
                                "    def test_worker_builds_unreal_payload_and_reports_invalid_json(self):\n"
                                "        row = OperationRow.from_unreal(operation_catalog()[0])\n"
                                "        self.assertEqual(row.host, 'unreal')\n"
                                "        worker = OperationRunWorker()\n"
                                "        worker.host = 'unreal'\n"
                                "        worker.operation_key = 'blueprint.scan'\n"
                                "        worker.args_json = '{\"asset_path\": \"/Game/Test/BP_Test\"}'\n"
                                "        worker_results = []\n"
                                "        worker.finished.connect(lambda ok, payload: worker_results.append((ok, payload)))\n"
                                "        worker.run()\n"
                                "        self.assertTrue(worker_results[-1][0])\n"
                                "        self.assertEqual(worker_results[-1][1]['result']['status'], 'backend_called')\n"
                                "        bad_worker = OperationRunWorker()\n"
                                "        bad_worker.host = 'unreal'\n"
                                "        bad_worker.operation_key = 'blueprint.scan'\n"
                                "        bad_worker.args_json = '{bad json}'\n"
                                "        bad_results = []\n"
                                "        bad_worker.finished.connect(lambda ok, payload: bad_results.append((ok, payload)))\n"
                                "        bad_worker.run()\n"
                                "        self.assertFalse(bad_results[-1][0])\n"
                                "        self.assertEqual(bad_results[-1][1]['error'], 'invalid_json')\n"
                                "\n"
                                "    def test_panel_refresh_template_run_and_result_output(self):\n"
                                "        panel = OperationRunnerPanel()\n"
                                "        self.assertGreaterEqual(len(panel._visible_rows), 1)\n"
                                "        panel.search_edit.setText('blueprint')\n"
                                "        self.assertEqual(panel.apply_filters(), 1)\n"
                                "        template = panel.populate_args_template()\n"
                                "        self.assertIn('asset_path', template)\n"
                                "        panel.args_editor.setPlainText('{\"asset_path\": \"/Game/Test/BP_Test\"}')\n"
                                "        panel.run_selected_operation()\n"
                                "        panel.worker.wait(5000)\n"
                                "        QApplication.processEvents()\n"
                                "        self.assertTrue(panel.run_button.isEnabled())\n"
                                "        self.assertIn('backend_called', panel.result_editor.toPlainText())\n"
                                "        panel.search_edit.setText('')\n"
                                "        panel.host_filter.setCurrentText('blender')\n"
                                "        self.assertEqual(panel.apply_filters(), 1)\n"
                                "        panel.operation_table.selectRow(0)\n"
                                "        template = panel.populate_args_template()\n"
                                "        self.assertIn('armature_name', template)\n"
                                "        panel.args_editor.setPlainText('{\"armature_name\": \"MannyRig\"}')\n"
                                "        panel.run_selected_operation()\n"
                                "        panel.worker.wait(5000)\n"
                                "        QApplication.processEvents()\n"
                                "        self.assertIn('dcc_backend_called', panel.result_editor.toPlainText())\n"
                            ),
                        },
                    ]
                    if wants_qt_operation_runner
                    else []
                ),
                "representative_code": expected_code_payload.get("representative_code", ""),
                "validation_commands": (
                    [
                        ["python", "-m", "py_compile", "tech_connector/ui/operation_runner_panel.py", "tech_connector/examples/tests/test_operation_runner_panel.py"],
                        ["python", "-m", "unittest", "examples.tech_connector.tests.test_operation_runner_panel"],
                    ]
                    if wants_qt_operation_runner
                    else []
                ),
                "copy_paths": [],
                "timeout_seconds": 30,
                "keep_workspace": True,
            },
            "dependencies": ["code.validate_expected_code passed", "disposable temp directory", "focused validation command list"],
            "expected_outputs": ["temp workspace path", "written generated files", "validation command exit codes", "no live tree mutation"],
        },
        "code.apply_patch": {
            "callable": "tech_connector.services.code_operation_service.apply_patch",
            "implementation_status": "registered_operation",
            "arguments": {
                "patch_source": "code.plan_patch output",
                "mechanism": "apply_patch",
                "safety": ["no unrelated refactor", "no staged-file mutation unless requested", "no destructive git commands"],
            },
            "dependencies": ["patch plan", "current file contents"],
            "expected_outputs": ["modified source files", "patch application result"],
        },
        "code.update_tests": {
            "callable": "tech_connector.services.code_operation_service.update_tests",
            "implementation_status": "registered_operation",
            "arguments": {
                "test_targets": "focused tests from code.inspect_symbols",
                "assertions": [
                    "operation reaches concrete callable",
                    "arguments/dependencies/validation are present",
                    "ambiguous prompt behavior is deterministic",
                ],
                "fixtures": "deterministic corpus fixture when prompt fuzzing is involved",
            },
            "dependencies": ["code.apply_patch", "test framework"],
            "expected_outputs": ["focused regression tests", "fixture updates if needed"],
        },
        "code.run_tests": {
            "callable": "tech_connector.services.code_operation_service.run_tests",
            "implementation_status": "registered_operation",
            "arguments": {
                "commands": ["python -m py_compile <changed python files>", "python -m unittest <focused tests>"],
                "timeout_policy": "focused first; broaden only when blast radius requires it",
                "report": ["commands", "exit codes", "failures", "remaining gaps"],
            },
            "dependencies": ["modified source files", "modified tests", "local Python runtime"],
            "expected_outputs": ["compile/test results", "failure summary", "remaining-risk report"],
        },
        "blueprint.scan": {
            "implementation_status": "registered_operation",
            "arguments": {
                "asset_paths": (
                    ["ABP_Locomotion", "ABP_Combat"]
                    if capability in {"abp_target_scan", "abp_crawl_integration"}
                    else (
                        ["BP_Rifle", "BP_Enemy"]
                        if capability == "niagara_target_scan"
                        else ["resolved facial AnimBP", "resolved MetaHuman asset"] if capability == "facial_animbp_slot_wiring" else ["resolved target asset"]
                    )
                ),
                "include_graphs": True,
                "include_variables": True,
                "include_components": True,
                "include_compile_status": True,
            },
            "dependencies": ["Unreal editor connection", "asset registry", "Blueprint graph readback support"],
            "expected_outputs": ["graph inventory", "variable/component list", "compile status", "target insertion points"],
        },
        "anim_graph.add_state": {
            "implementation_status": "registered_operation",
            "arguments": {
                "anim_blueprint": "resolved ABP_Locomotion or ABP_Combat asset path",
                "state_machine": "resolved locomotion/combat state machine",
                "state_name": "Crouch_Crawl",
                "pose_source": "resolved crawl animation or crawl BlendSpace",
                "metadata": {"feature": "rifle crouch-crawl", "preserve_existing_states": True},
            },
            "dependencies": ["blueprint.scan", "crawl animation/BlendSpace", "AnimGraph mutation wrapper"],
            "expected_outputs": ["new state asset graph node", "state readback record"],
        },
        "anim_graph.add_transition_rule": {
            "implementation_status": "registered_operation",
            "arguments": {
                "anim_blueprint": "resolved AnimBlueprint asset path",
                "state_machine": "resolved state machine",
                "transitions": [
                    {
                        "from": "Locomotion/IdleWalkRun or CombatLocomotion",
                        "to": "Crouch_Crawl",
                        "predicates": ["bIsCrouching", "bHasRifle", "speed <= crawl_max_speed", "not bIsJumping", "not bIsSprinting"],
                    },
                    {
                        "from": "Crouch_Crawl",
                        "to": "Locomotion/IdleWalkRun or CombatLocomotion",
                        "predicates": ["not bIsCrouching or bIsJumping or bIsSprinting"],
                    },
                ],
                "preserve_rules": ["sprint", "jump", "aim offset"],
            },
            "dependencies": ["anim_graph.add_state", "variable contract", "transition rule graph synthesis"],
            "expected_outputs": ["transition edges", "rule graphs", "predicate readback"],
        },
        "anim_graph.wire_state_machine_to_output_pose": {
            "implementation_status": "registered_operation",
            "arguments": {
                "anim_blueprint": "resolved AnimBlueprint asset path",
                "state_machine": "resolved state machine",
                "output_pose": "Final Animation Pose",
                "preserve_existing_pose_chain": True,
            },
            "dependencies": ["anim_graph.add_state", "anim_graph.add_transition_rule"],
            "expected_outputs": ["connected output pose pins", "graph readback proof"],
        },
        "blueprint.compile_and_save": {
            "implementation_status": "registered_operation",
            "arguments": {
                "asset_paths": ["resolved Blueprint/AnimBlueprint assets"],
                "save": True,
                "reload_after_save": True,
                "fail_on_compile_error": True,
            },
            "dependencies": ["all intended graph/asset mutations complete"],
            "expected_outputs": ["compile result", "save result", "reload/readback result"],
        },
        "niagara.create_emitter": {
            "implementation_status": "registered_operation",
            "arguments": {
                "emitters": [
                    {
                        "name": "NS_MuzzleFlash or NE_MuzzleFlash",
                        "package_path": "/Game/FX/Weapons",
                        "template": "resolved existing muzzle flash template or empty emitter",
                        "parameters": {"duration": "short burst", "socket": "Muzzle", "visibility": "cosmetic replicated event"},
                    },
                    {
                        "name": "NS_BulletImpact or NE_BulletImpact",
                        "package_path": "/Game/FX/Impacts",
                        "template": "resolved impact template or empty emitter",
                        "parameters": {"surface_response": "material/physical surface driven", "spawn_at": "hit result"},
                    },
                ]
            },
            "dependencies": ["Niagara plugin/API availability", "target content folder", "asset save/readback"],
            "expected_outputs": ["Niagara emitter/system assets", "readback class/property proof"],
        },
        "blueprint.attach_to_socket": {
            "callable": "unreal_tools.blueprint.attach_to_socket",
            "implementation_status": "registered_operation",
            "arguments": {
                "blueprint_path": "BP_Rifle or resolved weapon Blueprint",
                "component_name": "AIStudio_MuzzleFlashFX",
                "component_class": "/Script/Niagara.NiagaraComponent",
                "asset_path": "resolved Niagara muzzle effect",
                "socket_name": "Muzzle or resolved weapon muzzle socket",
                "attach_parent": "resolved skeletal mesh/component if available",
                "save": True,
            },
            "dependencies": ["blueprint.scan", "niagara.create_emitter", "socket readback"],
            "expected_outputs": ["socket attachment/spawn graph", "resolved socket proof"],
        },
        "blueprint.add_event": {
            "callable": "unreal_tools.blueprint.add_event",
            "implementation_status": "registered_operation",
            "arguments": {
                "blueprint": "resolved target Blueprint or AnimBlueprint",
                "events_or_functions": (
                    ["Expose/confirm bIsCrouching", "Expose/confirm bHasRifle", "Expose/confirm GroundSpeed", "Expose/confirm bIsJumping/bIsSprinting"]
                    if capability == "crawl_variable_contract"
                    else ["FireWeapon", "SpawnMuzzleFlash", "OnBulletImpact", "GameplayCue/replication boundary"]
                ),
                "graph": "AnimBlueprint EventGraph / variable update graph" if capability == "crawl_variable_contract" else "EventGraph or resolved function graph",
                "pin_contract": (
                    "animation update exec, movement component reads, weapon state read, boolean/float variable writes"
                    if capability == "crawl_variable_contract"
                    else "exec, target component, hit result, instigator, cosmetic authority guard"
                ),
            },
            "dependencies": ["blueprint.scan", "domain variable/event contract"],
            "expected_outputs": ["event/function nodes", "pin wiring", "compile-safe graph"],
        },
        "unreal.create_validation_map": {
            "callable": "unreal_tools.level.create_validation_map",
            "implementation_status": "registered_operation",
            "arguments": {
                "map_path": "/Game/Developers/AI_Validation/Disposable_TestMap",
                "spawn_actors": ["resolved character/weapon/enemy test actors"],
                "test_steps": ["trigger feature", "capture readback/log/proof", "restore or keep disposable map only"],
            },
            "dependencies": ["compiled assets", "safe disposable content path"],
            "expected_outputs": ["validation map", "spawn/test report", "rollback note"],
        },
        "blender.scan_animation": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "host": "blender",
                "operation_key": "blender.scan_animation",
                "scene": "active Blender scene or supplied .blend",
                "include_actions": True,
                "include_selected": True,
            },
            "dependencies": ["Blender connection", "active scene/readback"],
            "expected_outputs": ["armature/action inventory", "selected objects", "frame range", "scene scale"],
        },
        "blender.clean_animation": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "scene": "active Blender scene or supplied .blend",
                "armature": "resolved source armature",
                "action": "resolved crawl/mocap action",
                "cleanup": ["trim frame range", "remove jitter", "normalize root motion", "set scale/axes for Unreal"],
            },
            "dependencies": ["Blender connection", "source action readback"],
            "expected_outputs": ["cleaned action", "frame/root-motion report"],
        },
        "blender.export_fbx": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "output_path": "job_workspace/exports/crawl_cleaned.fbx",
                "selection": "resolved armature/action",
                "settings": {"axis_forward": "-Y", "axis_up": "Z", "apply_unit_scale": True, "bake_animation": True},
            },
            "dependencies": ["blender.clean_animation"],
            "expected_outputs": ["FBX file", "export settings manifest"],
        },
        "import_unreal_asset": {
            "implementation_status": "registered_operation",
            "arguments": {
                "source_file": "resolved FBX/animation/DNA-derived file",
                "destination_path": "/Game/Imported/AI_Staging",
                "target_skeleton": "resolved Manny/MetaHuman skeleton",
                "import_options": {"animation": True, "skeletal_mesh": False, "import_materials": False},
            },
            "dependencies": ["source file exists", "target Unreal skeleton/project path"],
            "expected_outputs": ["imported Unreal asset path", "import log", "asset load proof"],
        },
        "unreal.retarget_animation": {
            "callable": "unreal_tools.animation.retarget_animation",
            "implementation_status": "registered_operation",
            "arguments": {
                "source_animation": "imported animation asset",
                "source_skeletal_mesh_path": "resolved source skeletal mesh",
                "target_skeletal_mesh_path": "Manny target skeletal mesh",
                "output_path": "/Game/Animations/Retargeted",
                "retargeter_path": "resolved IK Retargeter if already known",
                "destination_suffix": "_Retargeted",
                "save": True,
            },
            "dependencies": ["import_unreal_asset", "IK rig/retargeter availability"],
            "expected_outputs": ["Manny-compatible animation asset", "retarget report"],
        },
        "unreal.create_blendspace": {
            "callable": "unreal_tools.animation.create_blendspace",
            "implementation_status": "registered_operation",
            "arguments": {
                "asset_path": "/Game/Animations/Locomotion/BS_Crawl",
                "skeleton_path": "Manny skeleton",
                "samples": [{"animation": "retargeted crawl animation", "axis": {"speed": "crawl speed", "direction": 0}}],
                "axis_x": {"name": "Speed", "min": 0.0, "max": "crawl_max_speed", "grid_num": 4},
                "axis_y": {"name": "Direction", "min": -180.0, "max": 180.0, "grid_num": 4},
                "save": True,
            },
            "dependencies": ["unreal.retarget_animation"],
            "expected_outputs": ["BlendSpace asset", "sample readback"],
        },
        "maya.adjust_facial_control_rig": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "scene": "active Maya scene or supplied file",
                "control_set": "resolved MetaHuman facial controls",
                "expression": "requested facial expression",
                "animation_range": "resolved or user-provided frame range",
                "export_path": "job_workspace/exports/metahuman_expression.fbx",
            },
            "dependencies": ["Maya connection", "facial controls readback"],
            "expected_outputs": ["keyed facial animation", "exported animation file"],
        },
        "maya.scan_facial_rig": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registered_operation",
            "arguments": {
                "host": "maya",
                "operation_key": "maya.scan_facial_rig",
                "scene": "active Maya scene or supplied file",
                "control_patterns": ["*_ctrl", "*CTRL*", "*face*", "*jaw*", "*brow*", "*eye*", "*mouth*"],
                "include_selection": True,
            },
            "dependencies": ["Maya connection", "active scene/readback"],
            "expected_outputs": ["facial control candidates", "selection", "timeline range", "export readiness"],
        },
        "metahuman.propagate_dna": {
            "callable": "tech_connector.services.unreal.metahuman_dna_operation_service.propagate_dna",
            "implementation_status": "registered_operation",
            "arguments": {
                "metahuman_dna_path": "resolved DNA file",
                "animation_or_scene_delta": "Maya facial adjustment output",
                "tool_root": "available external_tools/MetaHumanDNA under the configured tools root",
                "output_path": "job_workspace/exports/metahuman_dna_update",
                "skip_if_unavailable": True,
            },
            "dependencies": ["MetaHumanDNA availability", "DNA source path", "Maya adjustment output"],
            "expected_outputs": ["DNA output/provenance or explicit unavailable reason"],
        },
        "unreal.hook_facial_animbp_slot": {
            "callable": "unreal_tools.blueprint.hook_facial_animbp_slot",
            "implementation_status": "registered_operation",
            "arguments": {
                "facial_anim_blueprint": "resolved facial AnimBP",
                "slot_name": "resolved facial slot",
                "animation_asset": "imported facial animation asset",
                "compile_after_wiring": True,
            },
            "dependencies": ["blueprint.scan", "import_unreal_asset"],
            "expected_outputs": ["slot wiring readback", "compile result"],
        },
        "sequencer.validate_playback": {
            "callable": "unreal_tools.sequencer.validate_playback",
            "implementation_status": "registered_operation",
            "arguments": {
                "sequence_path": "/Game/Developers/AI_Validation/Seq_FacialPlayback_Proof",
                "actor": "resolved MetaHuman actor or spawned validation actor",
                "animation_asset": "imported/hooked facial animation",
                "capture": ["playback status", "frame range", "warnings"],
            },
            "dependencies": ["unreal.hook_facial_animbp_slot", "validation level/actor"],
            "expected_outputs": ["Sequencer playback report", "validation proof artifact"],
        },
    }
    generic_plans = {
        "execute_internal_function": {
            "callable": "operation_catalog.resolve_and_execute",
            "implementation_status": "registry_lookup_required",
            "arguments": {
                "query": capability or str(item.get("label") or ""),
                "host": host,
                "required_capability": capability,
                "inputs": "resolved from operation contract artifacts",
            },
            "dependencies": ["authoritative operation catalog", "resolved callable metadata"],
            "expected_outputs": ["execution result", "called function id"],
        },
        "run_dcc_operation": {
            "callable": "dcc_operation_service.execute_registered_operation",
            "implementation_status": "registry_lookup_required",
            "arguments": {
                "host": host,
                "operation_key": capability or "resolved host operation",
                "target": "resolved active asset/scene/node",
                "inputs": "resolved from host context and prompt slots",
            },
            "dependencies": ["host status green or plan-only fallback", "operation registry entry", "target resolver"],
            "expected_outputs": ["host operation result", "host readback"],
        },
        "run_python_function": {
            "callable": "local_python.execute_validated_helper",
            "implementation_status": "generated_or_registry_lookup_required",
            "arguments": {
                "function": "resolved indexed helper or generated wrapper",
                "inputs": "typed artifacts from previous step",
                "timeout_seconds": 60,
            },
            "dependencies": ["py_compile", "function signature contract"],
            "expected_outputs": ["return value", "files/artifacts produced"],
        },
        "validate_result": {
            "callable": "validation_planner.run_readback_checks",
            "implementation_status": "registered_operation",
            "arguments": {
                "capability": capability,
                "checks": list(item.get("validates_with") or []),
                "artifacts": "outputs from previous operation",
            },
            "dependencies": ["previous operation output"],
            "expected_outputs": ["validation report", "warnings/errors"],
        },
    }
    payload = dict(common)
    payload.update(plans.get(action_type) or generic_plans.get(action_type) or {})
    return payload


def _mixed_operation_sequence(adaptive_sequence: list[dict[str, Any]], decision: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    decision = dict(decision or {})
    steps: list[dict[str, Any]] = []
    index = 1
    for item in adaptive_sequence:
        for action_key in _action_keys_for_sequence_item(item, decision):
            action_type = _action_type_by_key(action_key)
            row = {
                "step": index,
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "action_type": action_type.key,
                "label": action_type.label,
                "category": action_type.category,
                "host": action_type.host,
                "requires_network": action_type.requires_network,
                "requires_approval": action_type.requires_approval,
                "requires_license_check": action_type.requires_license_check,
                "report_sources": action_type.report_sources,
                "validates_with": list(action_type.validates_with),
            }
            row["planned_call"] = _planned_call_for_action(row, decision)
            steps.append(row)
            index += 1
    return steps


def _artifact_type_by_key(key: str) -> ArtifactType:
    for artifact_type in ARTIFACT_TYPES:
        if artifact_type.key == key:
            return artifact_type
    return ARTIFACT_TYPES[0]


def _artifact_catalog() -> list[dict[str, Any]]:
    return [artifact_type.to_dict() for artifact_type in ARTIFACT_TYPES]


def _artifacts_for_action(action_type: str, capability: str, *, output: bool) -> list[dict[str, Any]]:
    mapping = {
        "execute_internal_function": (("executable_function",), ("execution_result",)),
        "run_python_function": (("source_code", "file"), ("execution_result", "compatibility_report")),
        "run_dcc_operation": (("blender_object", "maya_node", "unreal_asset"), ("execution_result", "skeleton", "skeletal_mesh")),
        "web_knowledge_search": (("documentation",), ("documentation", "asset_candidate_list")),
        "github_candidate_review": (("documentation",), ("repository", "license_record", "provenance_record")),
        "plugin_candidate_review": (("documentation",), ("plugin", "license_record", "provenance_record")),
        "download_or_ingest_asset": (("asset_candidate_list", "license_record"), ("file", "animation_clip", "provenance_record")),
        "import_unreal_asset": (("file", "animation_clip", "skeleton"), ("unreal_asset", "execution_result")),
        "blueprint.scan": (("unreal_asset",), ("workflow", "execution_result")),
        "anim_graph.add_state": (("unreal_asset", "animation_clip"), ("unreal_asset", "execution_result")),
        "anim_graph.add_transition_rule": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "anim_graph.wire_state_machine_to_output_pose": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "blueprint.compile_and_save": (("unreal_asset",), ("unreal_asset", "validation_report")),
        "niagara.create_emitter": (("unreal_asset", "source_code"), ("unreal_asset", "execution_result")),
        "blueprint.add_event": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "blueprint.attach_to_socket": (("unreal_asset", "workflow"), ("unreal_asset", "execution_result")),
        "unreal.create_validation_map": (("unreal_asset", "workflow"), ("validation_report", "unreal_asset")),
        "blender.clean_animation": (("blender_object", "animation_clip"), ("animation_clip", "execution_result")),
        "blender.export_fbx": (("animation_clip", "blender_object"), ("file", "provenance_record")),
        "unreal.retarget_animation": (("unreal_asset", "skeleton"), ("unreal_asset", "compatibility_report")),
        "unreal.create_blendspace": (("unreal_asset", "animation_clip", "skeleton"), ("unreal_asset", "execution_result")),
        "maya.adjust_facial_control_rig": (("maya_node",), ("animation_clip", "file", "execution_result")),
        "metahuman.propagate_dna": (("file", "animation_clip"), ("file", "provenance_record", "compatibility_report")),
        "unreal.hook_facial_animbp_slot": (("unreal_asset", "animation_clip"), ("unreal_asset", "execution_result")),
        "sequencer.validate_playback": (("unreal_asset", "animation_clip"), ("validation_report",)),
        "generate_code_or_wrapper": (("documentation", "compatibility_report"), ("source_code", "executable_function")),
        "register_capability": (("execution_result", "validation_report"), ("workflow", "executable_function")),
        "validate_result": (("execution_result",), ("validation_report",)),
    }
    inputs, outputs = mapping.get(action_type, (("file",), ("execution_result",)))
    selected = outputs if output else inputs
    return [
        {
            "artifact_type": key,
            "label": _artifact_type_by_key(key).label,
            "capability": capability,
            "required": not output,
        }
        for key in selected
    ]


def _execution_context_for_action(item: dict[str, Any]) -> dict[str, Any]:
    action_type = str(item.get("action_type") or "")
    host = str(item.get("host") or "")
    capability = str(item.get("capability") or "").lower()
    if not host:
        if action_type == "import_unreal_asset" or "unreal" in capability:
            host = "unreal"
        elif "blender" in capability:
            host = "blender"
        elif "maya" in capability:
            host = "maya"
        elif action_type in {"run_python_function", "generate_code_or_wrapper"}:
            host = "local_python"
        elif item.get("requires_network"):
            host = "web_service"
        else:
            host = "local"
    return {
        "host": host,
        "workspace": "job_workspace",
        "project": "active_project",
        "active_asset": "",
    }


def _provider_id_for_action(item: dict[str, Any]) -> str:
    action_type = str(item.get("action_type") or "")
    host = _execution_context_for_action(item).get("host", "local")
    if action_type == "web_knowledge_search":
        return "source_policy.research"
    if action_type == "github_candidate_review":
        return "github_ingest_service"
    if action_type == "plugin_candidate_review":
        return "plugin_registry"
    if action_type == "import_unreal_asset":
        return "unreal_bridge"
    if action_type == "run_dcc_operation":
        return f"{host}_bridge"
    if action_type == "run_python_function":
        return "local_python"
    if action_type.startswith("code."):
        return "local_code_operation_catalog"
    if action_type.startswith(("blueprint.", "anim_graph.", "niagara.", "unreal.", "sequencer.")):
        return "unreal_operation_catalog"
    if action_type.startswith("blender."):
        return "blender_operation_catalog"
    if action_type.startswith("maya."):
        return "maya_operation_catalog"
    if action_type.startswith("metahuman."):
        return "external_tools.metahuman_dna"
    return "tech_connector"


def _operation_action_contracts(mixed_sequence: list[dict[str, Any]], decision: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    decision = dict(decision or {})
    contracts: list[dict[str, Any]] = []
    for item in mixed_sequence:
        action_type = str(item.get("action_type") or "")
        capability = str(item.get("capability") or "")
        requires_network = bool(item.get("requires_network", False))
        requires_approval = bool(item.get("requires_approval", False))
        requires_license = bool(item.get("requires_license_check", False))
        planned_call = dict(item.get("planned_call") or _planned_call_for_action(item, decision))
        contracts.append(
            {
                "id": f"action_{int(item.get('step') or 0):03d}_{action_type}",
                "action_type": action_type,
                "capability": capability,
                "planned_call": planned_call,
                "callable": planned_call.get("callable", action_type),
                "call_arguments": planned_call.get("arguments", {}),
                "call_dependencies": planned_call.get("dependencies", []),
                "inputs": _artifacts_for_action(action_type, capability, output=False),
                "outputs": _artifacts_for_action(action_type, capability, output=True),
                "preconditions": [
                    "required inputs are present",
                    "execution context is available",
                    "user approval is recorded" if requires_approval else "",
                    "network is available" if requires_network else "",
                    "license is acceptable" if requires_license else "",
                ],
                "postconditions": [
                    "declared outputs are produced or failure is reported",
                    "validation evidence is captured",
                    "provenance is recorded for external resources" if requires_network else "",
                ],
                "execution_context": _execution_context_for_action(item),
                "execution_host": _execution_context_for_action(item).get("host", ""),
                "provider_id": _provider_id_for_action(item),
                "permissions": [
                    "network" if requires_network else "",
                    "user_approval" if requires_approval else "",
                    "license_review" if requires_license else "",
                ],
                "approval_policy": "required_before_execution" if requires_approval else "not_required",
                "network_requirement": "required" if requires_network else "not_required",
                "estimated_cost": None,
                "estimated_duration": None,
                "confidence": 0.72 if requires_network else 0.84,
                "retry_policy": {
                    "max_attempts": 2,
                    "retry_on": ["transient_failure", "timeout"] if requires_network else ["transient_failure"],
                },
                "rollback_policy": {
                    "strategy": "remove_outputs_or_restore_previous_state",
                    "requires_snapshot": action_type in {"import_unreal_asset", "download_or_ingest_asset", "generate_code_or_wrapper", "code.apply_patch"},
                },
                "validation_steps": list(planned_call.get("readback_validation") or item.get("validates_with") or []),
                "provenance": {
                    "trust_state": "approved_external" if requires_approval else ("source_reported" if requires_network else "trusted_internal_candidate"),
                    "source_url_required": bool(item.get("report_sources", False)),
                    "license_required": requires_license,
                    "security_review_required": action_type in {"github_candidate_review", "plugin_candidate_review", "download_or_ingest_asset"},
                },
            }
        )
    for contract in contracts:
        contract["preconditions"] = [item for item in contract["preconditions"] if item]
        contract["postconditions"] = [item for item in contract["postconditions"] if item]
        contract["permissions"] = [item for item in contract["permissions"] if item]
    return contracts


def _mixed_operation_graph(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = []
    edges = []
    for index, contract in enumerate(contracts):
        nodes.append(
            {
                "id": contract["id"],
                "action_type": contract["action_type"],
                "capability": contract["capability"],
                "execution_host": contract["execution_host"],
                "provider_id": contract["provider_id"],
                "planned_call": contract.get("planned_call", {}),
                "inputs": contract["inputs"],
                "outputs": contract["outputs"],
            }
        )
        if index > 0:
            previous = contracts[index - 1]
            edges.append(
                {
                    "from": previous["id"],
                    "to": contract["id"],
                    "artifact_flow": [
                        artifact.get("artifact_type", "")
                        for artifact in previous.get("outputs", [])
                        if artifact.get("artifact_type")
                    ][:3],
                    "condition": "previous action validated or produced recoverable warning",
                }
            )
    return {
        "framework": "mixed_operation_graph_v1",
        "base_graph": "reasoning_runtime.action.action_graph_service.ActionGraph",
        "supports": [
            "typed_artifact_edges",
            "conditionals",
            "fallback_providers",
            "parallel_discovery",
            "approval_gates",
            "retries",
            "rollback",
            "human_interaction",
            "async_waits",
        ],
        "nodes": nodes,
        "edges": edges,
    }


def _action_graph_type_for_contract(contract: dict[str, Any]) -> str:
    action_type = str(contract.get("action_type") or "")
    mapping = {
        "execute_internal_function": "execute_dcc_capability",
        "run_python_function": "execute_python",
        "run_dcc_operation": "execute_dcc",
        "web_knowledge_search": "search_docs",
        "github_candidate_review": "github_search",
        "plugin_candidate_review": "resolve_dcc_capability",
        "download_or_ingest_asset": "github_ingest",
        "import_unreal_asset": "execute_unreal_python",
        "generate_code_or_wrapper": "generate_python",
        "register_capability": "index_repository",
        "validate_result": "validate",
    }
    if action_type.startswith(("blueprint.", "anim_graph.", "niagara.", "unreal.", "sequencer.")):
        return "execute_unreal_python"
    if action_type.startswith("code."):
        return "execute_python"
    if action_type.startswith("blender."):
        return "execute_dcc"
    if action_type.startswith("maya."):
        return "execute_dcc"
    if action_type.startswith("metahuman."):
        return "execute_python"
    return mapping.get(action_type, "validate")


def _canonical_action_graph(
    goal: str,
    contracts: list[dict[str, Any]],
    graph: dict[str, Any],
    materialization_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Represent mixed operations using the existing ActionGraph-compatible shape."""
    actions: list[dict[str, Any]] = []
    previous_id = ""
    for contract in contracts:
        action_id = contract.get("id", "")
        action_type = _action_graph_type_for_contract(contract)
        action = {
            "id": action_id,
            "action_id": action_id,
            "type": action_type,
            "action_type": action_type,
            "title": str(contract.get("action_type") or action_type).replace("_", " ").title(),
            "description": f"{contract.get('action_type', action_type)} for {contract.get('capability', '')}",
            "args": {
                "capability": contract.get("capability", ""),
                "provider_id": contract.get("provider_id", ""),
                "execution_context": contract.get("execution_context", {}),
                "planned_call": contract.get("planned_call", {}),
                "operation_contract": contract,
            },
            "input": {
                "capability": contract.get("capability", ""),
                "provider_id": contract.get("provider_id", ""),
                "execution_context": contract.get("execution_context", {}),
                "planned_call": contract.get("planned_call", {}),
                "operation_contract": contract,
            },
            "depends_on": [previous_id] if previous_id else [],
            "dependency_action_ids": [previous_id] if previous_id else [],
            "target_refs": contract.get("outputs", []),
            "source_refs": contract.get("inputs", []),
            "requires_approval": contract.get("approval_policy") == "required_before_execution",
            "status": "planned",
            "validation_status": "not_validated",
            "diagnostics": [
                "Generated from goal gap planner universal operation contract.",
                "Typed artifacts and execution context are carried in args.operation_contract.",
            ],
            "pipeline_materialization": (materialization_plan or {}).get("by_action_id", {}).get(action_id, {}),
        }
        actions.append(action)
        previous_id = action_id
    try:
        from reasoning_runtime.action.action_graph_service import normalize_action_graph, validate_action_graph

        data = normalize_action_graph(
            {
                "goal": goal,
                "intent": "mixed_operation",
                "planner": "goal_gap_planning_service",
                "confidence": 0.72,
                "diagnostics": [
                    "Uses canonical ActionGraph with universal operation contracts attached.",
                    "mixed_operation_graph carries typed artifact edges and future graph features.",
                ],
                "actions": actions,
                "mixed_operation_graph": graph,
                "pipeline_materialization_plan": materialization_plan or {},
            }
        )
        data["validation"] = validate_action_graph(data)
        return data
    except Exception:
        return {
            "goal": goal,
            "intent": "mixed_operation",
            "planner": "goal_gap_planning_service",
            "confidence": 0.72,
            "diagnostics": ["ActionGraph normalization unavailable."],
            "actions": actions,
            "mixed_operation_graph": graph,
            "pipeline_materialization_plan": materialization_plan or {},
            "validation": {"valid": False, "errors": ["ActionGraph normalization unavailable."], "warnings": []},
        }


def _is_control_orchestration_action(action_type: str) -> bool:
    return action_type in {"github_candidate_review", "plugin_candidate_review"}


def _has_registered_callable(contract: dict[str, Any]) -> bool:
    action_type = str(contract.get("action_type") or "")
    provider = str(contract.get("provider_id") or "")
    if action_type == "execute_internal_function":
        return True
    if action_type == "run_dcc_operation" and provider.endswith("_bridge"):
        return True
    if action_type == "import_unreal_asset" and provider == "unreal_bridge":
        return True
    if action_type in {
        "code.search_project",
        "code.inspect_symbols",
        "code.plan_patch",
        "code.plan_expected_code",
        "code.validate_expected_code",
        "code.validate_patch_in_temp_workspace",
        "code.apply_patch",
        "code.update_tests",
        "code.run_tests",
        "blueprint.scan",
        "anim_graph.add_state",
        "anim_graph.add_transition_rule",
        "anim_graph.wire_state_machine_to_output_pose",
        "blueprint.compile_and_save",
        "blueprint.attach_to_socket",
        "blueprint.add_event",
        "niagara.create_emitter",
        "unreal.create_validation_map",
        "unreal.retarget_animation",
        "unreal.create_blendspace",
        "unreal.hook_facial_animbp_slot",
        "sequencer.validate_playback",
        "blender.scan_animation",
        "blender.clean_animation",
        "blender.export_fbx",
        "maya.scan_facial_rig",
        "maya.adjust_facial_control_rig",
        "metahuman.propagate_dna",
    }:
        return True
    if action_type in {"register_capability", "validate_result"}:
        return True
    return False


def _materialization_kind(contract: dict[str, Any]) -> str:
    action_type = str(contract.get("action_type") or "")
    if action_type in {"download_or_ingest_asset", "github_candidate_review", "plugin_candidate_review"}:
        return "third_party_wrapper"
    if action_type == "web_knowledge_search":
        return "provider_operation"
    if action_type in {"run_python_function", "generate_code_or_wrapper"}:
        return "generated_function"
    return "generated_adapter"


def _generated_capability_path(contract: dict[str, Any]) -> str:
    host = _function_slug(str(contract.get("execution_host") or "local"), fallback="local")
    capability = _function_slug(str(contract.get("capability") or contract.get("action_type") or "operation"))
    action_type = str(contract.get("action_type") or "")
    if action_type in {"download_or_ingest_asset", "github_candidate_review", "plugin_candidate_review"}:
        return f"third_party/wrappers/{capability}/adapter.py"
    if action_type == "web_knowledge_search":
        return f"tool_output/generated_adapters/{host}/{capability}_provider.py"
    return f"tool_output/generated_functions/{host}/{capability}.py"


def _manifest_path_for_implementation(implementation_path: str) -> str:
    base = implementation_path.rsplit(".", 1)[0]
    return f"{base}.manifest.yaml"


def _pipeline_materialization_plan(
    contracts: list[dict[str, Any]],
    graph: dict[str, Any],
    canonical_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan how a solved mixed operation can become a reusable pipeline.

    Planning may mention generated files, but it must not write them. Actual
    function generation belongs to an approved materialization/save step.
    """
    candidates: list[dict[str, Any]] = []
    by_action_id: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        action_id = str(contract.get("id") or "")
        action_type = str(contract.get("action_type") or "")
        capability = str(contract.get("capability") or action_type)
        control_node = _is_control_orchestration_action(action_type)
        registered = _has_registered_callable(contract)
        materializable = not control_node
        implementation_path = ""
        manifest_path = ""
        entry_point = ""
        status = "registered_callable" if registered else "planned_not_written"
        if materializable and not registered:
            implementation_path = _generated_capability_path(contract)
            manifest_path = _manifest_path_for_implementation(implementation_path)
            entry_point = "execute"
        node_plan = {
            "action_id": action_id,
            "capability": capability,
            "action_type": action_type,
            "node_kind": "control_flow" if control_node else "executable_operation",
            "pipeline_node_type": "approval_or_selection" if control_node else "operation",
            "registered_callable": registered,
            "materializable": materializable,
            "materialization_kind": "control_node" if control_node else (_materialization_kind(contract) if not registered else "existing_callable"),
            "status": "control_node_no_function_required" if control_node else status,
            "promotion_scope_default": "pipeline_local" if not registered else "internal",
            "trust_state": (
                "orchestration_only"
                if control_node
                else ("trusted_internal" if registered else "untrusted_until_validated")
            ),
            "implementation": {
                "path": implementation_path,
                "entry_point": entry_point,
                "contract": "OperationContext + inputs -> OperationResult",
            },
            "manifest": {
                "path": manifest_path,
                "schema": "tech_connector.operation_manifest.v1" if manifest_path else "",
                "must_declare": [
                    "id",
                    "entry_point",
                    "inputs",
                    "outputs",
                    "host_environment",
                    "dependencies",
                    "provenance",
                    "trust_level",
                    "validation_state",
                    "pipeline_node_metadata",
                ] if manifest_path else [],
            },
            "inputs": list(contract.get("inputs") or []),
            "outputs": list(contract.get("outputs") or []),
            "validation": {
                "required": bool(materializable),
                "steps": list(contract.get("validation_steps") or []),
                "minimum_checks": [
                    "generated implementation imports or host adapter resolves",
                    "declared inputs and outputs match operation contract",
                    "manifest validates",
                    "operation can be called by pipeline runtime",
                ] if materializable and not registered else [],
            },
            "registration": {
                "required_before_pipeline_run": bool(materializable and not registered),
                "registry_target": "capability_registry",
                "replace_temporary_action_with": f"capability:{_function_slug(capability)}" if materializable and not registered else "",
            },
        }
        by_action_id[action_id] = node_plan
        if contract.get("approval_policy") == "required_before_execution":
            candidates.append(
                {
                    "action_id": f"{action_id}_approval",
                    "capability": capability,
                    "action_type": "approval_gate",
                    "node_kind": "control_flow",
                    "pipeline_node_type": "approval_or_selection",
                    "registered_callable": False,
                    "materializable": False,
                    "materialization_kind": "control_node",
                    "status": "control_node_no_function_required",
                    "promotion_scope_default": "pipeline_local",
                    "trust_state": "orchestration_only",
                    "implementation": {
                        "path": "",
                        "entry_point": "",
                        "contract": "approval decision -> continuation state",
                    },
                    "manifest": {
                        "path": "",
                        "schema": "",
                        "must_declare": [],
                    },
                    "inputs": [
                        {
                            "artifact_type": "provenance_record",
                            "label": "ProvenanceRecord",
                            "capability": capability,
                            "required": True,
                        }
                    ],
                    "outputs": [
                        {
                            "artifact_type": "execution_result",
                            "label": "ExecutionResult",
                            "capability": capability,
                            "required": False,
                        }
                    ],
                    "validation": {
                        "required": True,
                        "steps": ["approval is recorded", "selected candidate or operation parameters are explicit"],
                        "minimum_checks": [],
                    },
                    "registration": {
                        "required_before_pipeline_run": False,
                        "registry_target": "pipeline_control_nodes",
                        "replace_temporary_action_with": "",
                    },
                }
            )
        candidates.append(node_plan)

    generated = [item for item in candidates if item["materializable"] and not item["registered_callable"]]
    return {
        "framework": "mixed_operation_materializer_v1",
        "base_graph": graph.get("base_graph", "reasoning_runtime.action.action_graph_service.ActionGraph"),
        "convertible": True,
        "status": "planned_not_written",
        "generated_function_root": "tool_output/generated_functions",
        "generated_adapter_root": "tool_output/generated_adapters",
        "third_party_wrapper_root": "third_party/wrappers",
        "pipeline_package_root": "pipelines/<pipeline_id>",
        "default_promotion_scope": "pipeline_local",
        "promotion_scopes": [
            "temporary_job",
            "pipeline_local",
            "project",
            "user_library",
            "trusted_global",
        ],
        "promotion_policy": [
            "Do not promote generated or third-party code to global trust automatically.",
            "Pipeline-local is the safest default for newly generated functions.",
            "Externally sourced code must be wrapped and must keep license/provenance records.",
            "Credentials must be stored as references, not embedded in generated functions or manifests.",
        ],
        "materialization_steps": [
            "Inspect completed mixed-operation graph.",
            "Reuse registered callables where contracts already match.",
            "Generate functions, adapters, or wrappers only for materializable executable steps without callables.",
            "Write manifests and tests beside generated implementations.",
            "Validate each callable independently.",
            "Register validated capabilities.",
            "Replace temporary action IDs with stable operation IDs.",
            "Emit a pipeline-ready ActionGraph/workflow package.",
        ],
        "pipeline_node_candidates": candidates,
        "generated_callable_candidates": generated,
        "by_action_id": by_action_id,
        "reproducibility_checks": [
            "Every executable step has a callable implementation or generated wrapper plan.",
            "All dependencies, host versions, credentials, approvals, and provenance are explicit.",
            "User choices are represented as pipeline inputs or approval nodes.",
            "External assets are dynamically resolved or safely referenced with license records.",
            "Rollback and validation steps survive conversion from mixed operation to pipeline.",
        ],
        "canonical_action_graph": {
            "framework": "reasoning_runtime.action.action_graph_service.ActionGraph",
            "action_count": len((canonical_graph or {}).get("actions") or []),
            "validation": (canonical_graph or {}).get("validation", {}),
        },
    }


def _approval_gates(strategy_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    for item in strategy_plan:
        for strategy in list(item.get("strategies") or []):
            if not isinstance(strategy, dict):
                continue
            if not strategy.get("pause_before_execution"):
                continue
            gates.append(
                {
                    "capability": item.get("capability", ""),
                    "label": item.get("label", ""),
                    "strategy": strategy.get("key", ""),
                    "requires_link": True,
                    "requires_fit_explanation": True,
                    "requires_license_check": bool(strategy.get("requires_license_check", False)),
                    "requires_user_approval": True,
                    "approval_prompt": strategy.get("approval_prompt", ""),
                }
            )
    return gates


def _source_report_requirements(strategy_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    for item in strategy_plan:
        for strategy in list(item.get("strategies") or []):
            if not isinstance(strategy, dict):
                continue
            if not strategy.get("requires_internet") or strategy.get("pause_before_execution"):
                continue
            requirements.append(
                {
                    "capability": item.get("capability", ""),
                    "label": item.get("label", ""),
                    "strategy": strategy.get("key", ""),
                    "report_links": True,
                    "report_relevance": True,
                    "report_knowledge_added": True,
                    "approval_required": False,
                    "report_prompt": strategy.get("approval_prompt", ""),
                }
            )
    return requirements


def _planned_actions_from_path(path: list[dict[str, Any]], options: list[GapResolutionOption]) -> list[str]:
    actions: list[str] = []
    if path:
        actions.append("Inspect and confirm the current goal, target context, and existing capabilities before editing.")
    for item in path[1:7]:
        label = str(item.get("label") or item.get("capability") or "").strip()
        status = str(item.get("status") or "").strip()
        if not label:
            continue
        if status == "known":
            actions.append(f"Reuse or extend: {label}.")
        elif status == "missing_or_unverified":
            actions.append(f"Resolve missing prerequisite: {label}.")
        else:
            actions.append(f"Discover and verify: {label}.")
    if options:
        actions.append(f"Prefer the highest-confidence resolution option: {options[0].label}.")
    actions.append("Stop for approval before risky, destructive, ambiguous, or broad mutation.")
    actions.append("Report progress at each long-running stage and hand off compact findings to the next stage.")
    return list(_uniq(actions))


def _needs_detailed_progress(
    decision: dict[str, Any],
    missing_links: list[dict[str, Any]],
    path: list[dict[str, Any]],
    patterns: list[CapabilityPattern],
) -> bool:
    if len(patterns) == 1 and patterns[0].key.startswith("quick."):
        return False
    if missing_links:
        return True
    if len(path) > 4:
        return True
    if decision.get("requires_plan") or decision.get("requires_confirmation") or decision.get("requires_dcc_connection"):
        return True
    if str(decision.get("risk_level") or "").lower() in {"medium", "high"}:
        return True
    if str(decision.get("compound_kind") or "atomic") != "atomic":
        return True
    mutation = str(decision.get("mutation_scope") or "")
    return bool(mutation and mutation != "read_only")


def _test_plan_from_path(path: list[dict[str, Any]], options: list[GapResolutionOption]) -> list[str]:
    tests: list[str] = []
    for item in path:
        for check in list(item.get("verify") or [])[:2]:
            tests.append(str(check))
    if options:
        tests.append(f"Validate that the selected resolution option worked: {options[0].label}.")
    tests.extend(
        [
            "Confirm the original user-facing goal works in the target app or project.",
            "Confirm existing related behavior still works and was not duplicated or broken.",
            "Report anything that could not be verified and the next safest validation step.",
        ]
    )
    return list(_uniq(tests))[:12]


def _report_outline(needs_detailed_progress: bool) -> list[str]:
    if not needs_detailed_progress:
        return [
            "Completed action",
            "Result or blocker",
        ]
    return [
        "Goal and context used",
        "Path selected and why",
        "Planned actions before mutation",
        "Targets/files/assets/graphs affected",
        "Edits made or operations performed",
        "What was reused versus created",
        "Validation and user test steps",
        "Warnings, unresolved assumptions, rollback or recovery notes",
        "Learning recommendations for future capability gaps",
        "Final outcome: completed, partially completed, blocked, failed, or rolled back",
    ]


def build_goal_gap_plan(prompt: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        from tech_connector.services.settings_service import load_settings
        settings = load_settings()
        custom_module = settings.get("planning_provider_module")
        if custom_module and custom_module != "default":
            from tech_connector.services.modular_provider_utils import invoke_custom_provider, resolve_custom_provider_binding
            return invoke_custom_provider(
                resolve_custom_provider_binding("planning_module", custom_module, "build_goal_gap_plan", settings),
                _build_goal_gap_plan_impl,
                prompt,
                decision
            )
    except Exception as e:
        print(f"Error calling custom build_goal_gap_plan: {e}", flush=True)
    return _build_goal_gap_plan_impl(prompt, decision)

def _build_goal_gap_plan_impl(prompt: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an A-to-Z plan only after the problem is adequately formulated."""
    decision = dict(decision or {})
    decision.setdefault("prompt", prompt)
    decision.setdefault("original_prompt", prompt)
    problem_formulation = _build_problem_formulation(prompt, decision)
    decision["problem_formulation"] = problem_formulation

    # Capability matching may use the original wording, but the formulated
    # problem is authoritative for goal, prerequisites, success, and whether
    # execution is allowed to continue.
    quick_allowed = (
        bool(problem_formulation.get("adequate"))
        and not _problem_formulation_requires_pause(problem_formulation)
        and _is_quick_direct_action(decision)
    )
    patterns = [_quick_direct_pattern(prompt, decision)] if quick_allowed else _matched_patterns(prompt, decision)
    if not patterns:
        # A request is only "quick direct" after formulation confirms that it
        # is actually an execution/direct-action problem rather than a source
        # question containing executable words.
        patterns = [_generic_pattern(prompt, decision)]

    goal = str(
        problem_formulation.get("interpreted_problem")
        or problem_formulation.get("desired_outcome")
        or _goal_from_prompt(prompt)
    )
    known_evidence = _known_capability_evidence(decision, prompt)
    nodes: list[CapabilityNode] = [
        CapabilityNode(
            key="user_goal",
            label=goal,
            status="target",
            evidence=("current prompt", "problem formulation"),
            produces=tuple(problem_formulation.get("deliverables") or ["desired outcome"]),
            verification=tuple(problem_formulation.get("success_conditions") or ["user-visible outcome is testable"]),
        )
    ]
    formulation_nodes = _capability_nodes_from_problem_formulation(problem_formulation)
    pattern_nodes: list[CapabilityNode] = []
    options: list[GapResolutionOption] = []
    questions: list[str] = []
    learning: list[str] = []
    labels: list[str] = []

    for pattern in patterns:
        labels.extend(pattern.labels)
        pattern_nodes.extend(pattern.required_chain)
        options.extend(pattern.resolution_options)
        questions.extend(pattern.questions)
        learning.extend(pattern.learning_recommendations)
    has_specific_pattern = any(
        not pattern.key.startswith(("generic.", "quick."))
        for pattern in patterns
    )
    if has_specific_pattern:
        nodes.extend(pattern_nodes)
    else:
        nodes.extend(formulation_nodes)
        nodes.extend(pattern_nodes)

    deduped_nodes: list[CapabilityNode] = []
    seen_nodes: set[str] = set()
    for node in nodes:
        if node.key in seen_nodes:
            continue
        seen_nodes.add(node.key)
        status = node.status
        evidence = list(node.evidence)
        if node.key != "user_goal":
            label_terms = _terms(node.label)
            if known_evidence and any(term in " ".join(known_evidence).lower() for term in label_terms if len(term) > 4):
                status = "known"
                evidence.extend(known_evidence[:3])
            elif node.requires:
                status = "missing_or_unverified"
            else:
                status = "discoverable"
        deduped_nodes.append(
            CapabilityNode(
                key=node.key,
                label=node.label,
                status=status,
                evidence=_uniq(evidence),
                requires=node.requires,
                produces=node.produces,
                verification=node.verification,
            )
        )

    ranked_options = sorted(options, key=lambda item: item.confidence, reverse=True)
    missing_links = [
        {
            "from": deduped_nodes[index - 1].key if index > 0 else "start",
            "to": node.key,
            "label": node.label,
            "status": node.status,
            "requires": list(node.requires),
            "verification": list(node.verification),
        }
        for index, node in enumerate(deduped_nodes)
        if node.status in {"missing_or_unverified", "unknown", "discoverable"}
    ]
    recommended_path = [
        {
            "step": index,
            "capability": node.key,
            "label": node.label,
            "status": node.status,
            "verify": list(node.verification[:2]),
        }
        for index, node in enumerate(deduped_nodes, start=1)
    ]
    capability_resolution_plan = _resolution_strategy_plan(deduped_nodes, decision)
    adaptive_sequence = _adaptive_sequence(capability_resolution_plan)
    mixed_operation_sequence = _mixed_operation_sequence(adaptive_sequence, decision)
    operation_contracts = _operation_action_contracts(mixed_operation_sequence, decision)
    mixed_operation_graph = _mixed_operation_graph(operation_contracts)
    pipeline_materialization_plan = _pipeline_materialization_plan(operation_contracts, mixed_operation_graph)
    canonical_action_graph = _canonical_action_graph(
        goal,
        operation_contracts,
        mixed_operation_graph,
        pipeline_materialization_plan,
    )
    pipeline_materialization_plan["canonical_action_graph"] = {
        "framework": "reasoning_runtime.action.action_graph_service.ActionGraph",
        "intent": canonical_action_graph.get("intent", ""),
        "planner": canonical_action_graph.get("planner", ""),
        "action_count": len(canonical_action_graph.get("actions") or []),
        "validation": canonical_action_graph.get("validation", {}),
    }
    canonical_action_graph["pipeline_materialization_plan"] = pipeline_materialization_plan
    approval_gates = _approval_gates(capability_resolution_plan)
    source_report_requirements = _source_report_requirements(capability_resolution_plan)
    needs_detailed_progress = _needs_detailed_progress(decision, missing_links, recommended_path, patterns)
    planned_actions = _planned_actions_from_path(recommended_path, ranked_options) if needs_detailed_progress else []
    test_plan = _test_plan_from_path(recommended_path, ranked_options) if needs_detailed_progress else []

    return {
        "framework": "goal_gap_planning_v2",
        "goal": goal,
        "problem_formulation": problem_formulation,
        "meaning_graph": dict(problem_formulation.get("meaning_graph") or {}),
        "problem_adequate": bool(problem_formulation.get("adequate")),
        "problem_can_plan": bool(problem_formulation.get("can_plan")),
        "problem_requires_clarification": bool(problem_formulation.get("requires_clarification")),
        "matched_patterns": _uniq(pattern.key for pattern in patterns),
        "capability_labels": _uniq(labels),
        "known_evidence": list(known_evidence),
        "capability_nodes": [node.to_dict() for node in deduped_nodes],
        "missing_links": missing_links,
        "resolution_options": [option.to_dict() for option in ranked_options[:6]],
        "recommended_gap_path": recommended_path,
        "capability_resolution_plan": capability_resolution_plan,
        "adaptive_sequence": adaptive_sequence,
        "operation_action_catalog": _operation_action_catalog(),
        "artifact_type_catalog": _artifact_catalog(),
        "mixed_operation_sequence": mixed_operation_sequence,
        "operation_contracts": operation_contracts,
        "mixed_operation_graph": mixed_operation_graph,
        "canonical_action_graph": canonical_action_graph,
        "pipeline_materialization_plan": pipeline_materialization_plan,
        "approval_gates": approval_gates,
        "source_report_requirements": source_report_requirements,
        "progress_mode": "detailed" if needs_detailed_progress else "terse",
        "planned_actions": planned_actions,
        "test_plan": test_plan,
        "report_outline": _report_outline(needs_detailed_progress),
        "questions": _uniq(questions),
        "learning_recommendations": _uniq(learning),
        "planning_rules": [
            "Do not route, retrieve, mutate, or execute until the problem formulation is adequate.",
            "Generate the capability/task graph from the meaning graph and desired deliverables, not from raw token overlap.",
            "A handler result is not completion unless it satisfies the problem formulation success conditions.",
            "Treat every missing prerequisite as a planning node, not a failure.",
            "Ask what produces each missing capability before asking the user.",
            "Rank multiple resolution options before choosing one.",
            "For quick direct actions, keep the user report terse and completion-focused.",
            "For longer, risky, or uncertain work, use a documentation-level breakdown of goal, path, targets, edits, validation, risks, and outcome.",
            "Each capability node may resolve through internal functions, workflows, composition, local/project search, official docs, GitHub/plugin acquisition, generated code, or user approval.",
            "Mixed operation sequences may combine internal functions, Python helpers, DCC operations, asset acquisition, imports, validation, and capability registration.",
            "Use the existing ActionGraph as the canonical graph shape; attach universal operation contracts for typed artifacts, state transitions, context, retry, rollback, and provenance.",
            "Every successful mixed operation should be convertible into a pipeline; every executable step must have a registered callable or a generated/wrapped callable plan before pipeline save/run.",
            "Generated functions belong under tool_output/generated_functions or tool_output/generated_adapters by default; third-party code belongs behind wrappers under third_party/wrappers with license and provenance manifests.",
            "Ask for approval before materializing untrusted generated or external code, then validate and register it before making it a reusable pipeline node.",
            "New action types should be added to the action catalog instead of hardcoding new planner branches.",
            "If a capability is acquired or generated, validate it and register it before continuing the original plan.",
            "Web/official knowledge research may proceed without pausing, but the report must include links found, relevance, and what knowledge was used or added.",
            "Before GitHub/plugin/marketplace ingestion, pause and show links, relevance, license/approval needs, and the intended ingest/use plan.",
            "Use local/project knowledge first and request research only when local confidence is weak.",
            "Keep reporting visible progress during long context, model, tool, daemon, or validation work.",
            "After execution, recommend reusable capability relationships that should be persisted.",
        ],
        "next_action": (
            "clarify_problem"
            if _problem_formulation_requires_pause(problem_formulation)
            else ("resolve_missing_links" if missing_links else "execute_validated_path")
        ),
    }


def goal_gap_planning_context(prompt: str, decision: dict[str, Any] | None = None, *, max_chars: int = 3000) -> str:
    plan = build_goal_gap_plan(prompt, decision)
    formulation = dict(plan.get("problem_formulation") or {})
    lines = [
        "GOAL GAP PLANNING:",
        "Use this to connect the user's A-to-Z goal through required intermediate capabilities before execution.",
        f"Goal: {plan['goal']}",
        f"Problem adequate: {str(bool(plan.get('problem_adequate'))).lower()}",
        f"Can plan: {str(bool(plan.get('problem_can_plan'))).lower()}",
        f"Progress mode: {plan.get('progress_mode', 'detailed')}",
    ]
    if formulation:
        lines.extend([
            "Problem formulation:",
            f"- Literal request: {formulation.get('literal_request', '')}",
            f"- Interpreted problem: {formulation.get('interpreted_problem', '')}",
            f"- Desired outcome: {formulation.get('desired_outcome', '')}",
            f"- Deliverables: {', '.join(formulation.get('deliverables') or [])}",
            f"- Action mode: {formulation.get('action_mode', '')}",
        ])
        if formulation.get("unknowns"):
            lines.append("- Unknowns: " + " | ".join(list(formulation.get("unknowns") or [])[:5]))
        if formulation.get("exclusions"):
            lines.append("- Exclusions: " + " | ".join(list(formulation.get("exclusions") or [])[:4]))
    lines.append("Planning rules:")
    lines.extend(f"- {rule}" for rule in plan.get("planning_rules") or [])
    if plan.get("known_evidence"):
        lines.append("Known evidence:")
        lines.extend(f"- {item}" for item in plan["known_evidence"][:6])
    if plan.get("missing_links"):
        lines.append("Missing or unverified links:")
        for link in plan["missing_links"][:8]:
            req = "; ".join(link.get("requires") or [])
            suffix = f" requires {req}" if req else ""
            lines.append(f"- {link.get('label')} ({link.get('status')}){suffix}")
    if plan.get("resolution_options"):
        lines.append("Resolution options:")
        for option in plan["resolution_options"][:4]:
            lines.append(f"- {option['label']} confidence={option['confidence']:.2f}")
            for step in option.get("steps", [])[:4]:
                lines.append(f"  - {step}")
    if plan.get("capability_resolution_plan"):
        lines.append("Capability resolution strategy per step:")
        for item in plan["capability_resolution_plan"][:8]:
            strategies = item.get("strategies") or []
            chosen = item.get("chosen_strategy") or ""
            detail = ""
            if strategies:
                first = strategies[0]
                detail = (
                    f" confidence={float(first.get('confidence') or 0):.2f}"
                    f" internet={str(bool(first.get('requires_internet'))).lower()}"
                    f" approval={str(bool(first.get('requires_approval'))).lower()}"
                )
            lines.append(f"- {item.get('label')} -> {chosen}{detail}")
    if plan.get("adaptive_sequence"):
        lines.append("Adaptive execution sequence:")
        for item in plan["adaptive_sequence"][:8]:
            lines.append(f"- {item.get('action')}: {item.get('label')} via {item.get('strategy')}")
    if plan.get("mixed_operation_sequence"):
        lines.append("Mixed operation sequence:")
        for item in plan["mixed_operation_sequence"][:10]:
            flags = []
            if item.get("requires_network"):
                flags.append("network")
            if item.get("requires_approval"):
                flags.append("approval")
            if item.get("requires_license_check"):
                flags.append("license")
            flag_text = f" ({', '.join(flags)})" if flags else ""
            planned_call = dict(item.get("planned_call") or {})
            call_arguments = dict(planned_call.get("arguments") or {})
            arg_keys = ", ".join(list(call_arguments.keys())[:6])
            callable_name = planned_call.get("callable", "")
            call_text = f" call={callable_name}" if callable_name else ""
            args_text = f" args=[{arg_keys}]" if arg_keys else ""
            lines.append(f"- {item.get('action_type')}: {item.get('capability')} via {item.get('strategy')}{flag_text}{call_text}{args_text}")
    if plan.get("operation_contracts"):
        lines.append("Universal action contracts:")
        for contract in plan["operation_contracts"][:6]:
            inputs = ", ".join(item.get("artifact_type", "") for item in contract.get("inputs", [])[:3])
            outputs = ", ".join(item.get("artifact_type", "") for item in contract.get("outputs", [])[:3])
            call_arguments = dict(contract.get("call_arguments") or {})
            arg_keys = ", ".join(list(call_arguments.keys())[:6])
            call_text = f" call={contract.get('callable', '')}" if contract.get("callable") else ""
            args_text = f" args=[{arg_keys}]" if arg_keys else ""
            lines.append(
                f"- {contract.get('id')}: {contract.get('action_type')} on {contract.get('execution_host')} "
                f"inputs=[{inputs}] outputs=[{outputs}]{call_text}{args_text}"
            )
    if plan.get("mixed_operation_graph"):
        graph = plan["mixed_operation_graph"]
        lines.append(
            f"Canonical graph basis: {graph.get('base_graph', 'ActionGraph')} "
            f"nodes={len(graph.get('nodes') or [])} edges={len(graph.get('edges') or [])}"
        )
    if plan.get("pipeline_materialization_plan"):
        materializer = plan["pipeline_materialization_plan"]
        lines.append("Pipeline materialization:")
        lines.append(
            f"- Convertible={str(bool(materializer.get('convertible'))).lower()} "
            f"default_scope={materializer.get('default_promotion_scope', '')} "
            f"generated_candidates={len(materializer.get('generated_callable_candidates') or [])}"
        )
        for item in list(materializer.get("generated_callable_candidates") or [])[:5]:
            implementation = item.get("implementation") or {}
            lines.append(
                f"- {item.get('capability')}: {item.get('materialization_kind')} -> "
                f"{implementation.get('path', '')}"
            )
    if plan.get("approval_gates"):
        lines.append("Source review / approval gates:")
        for gate in plan["approval_gates"][:6]:
            lines.append(
                f"- Pause before {gate.get('strategy')} for {gate.get('label')}: "
                "show links, relevance, license/approval needs, and intended use."
            )
    if plan.get("source_report_requirements"):
        lines.append("Knowledge source reporting after research:")
        for item in plan["source_report_requirements"][:6]:
            lines.append(f"- {item.get('strategy')} for {item.get('label')}: report links found, relevance, and knowledge used/added.")
    if plan.get("planned_actions"):
        lines.append("Planned actions to explain before mutation:")
        lines.extend(f"- {item}" for item in plan["planned_actions"][:8])
    if plan.get("test_plan"):
        lines.append("How the user can test or verify this:")
        lines.extend(f"- {item}" for item in plan["test_plan"][:8])
    if plan.get("report_outline"):
        lines.append("Required response/report outline:")
        lines.extend(f"- {item}" for item in plan["report_outline"][:10])
    if plan.get("learning_recommendations"):
        lines.append("Learning recommendations after this workflow:")
        lines.extend(f"- {item}" for item in plan["learning_recommendations"][:5])
    text = "\n".join(lines)
    return text[:max_chars].rstrip()


def compact_goal_gap_plan(
    plan: dict[str, Any] | None,
    *,
    max_links: int = 5,
    max_options: int = 3,
    max_learning: int = 3,
    max_actions: int = 3,
    max_tests: int = 3,
) -> dict[str, Any]:
    """Return a route-metadata friendly gap plan."""
    plan = dict(plan or {})
    formulation = dict(plan.get("problem_formulation") or {})
    return {
        "framework": plan.get("framework", "goal_gap_planning_v2"),
        "goal": plan.get("goal", ""),
        "problem_formulation": {
            "interpreted_problem": formulation.get("interpreted_problem", ""),
            "desired_outcome": formulation.get("desired_outcome", ""),
            "deliverables": list(formulation.get("deliverables") or []),
            "action_mode": formulation.get("action_mode", ""),
            "unknowns": list(formulation.get("unknowns") or [])[:max_links],
            "blocking_unknowns": list(formulation.get("blocking_unknowns") or [])[:max_links],
            "exclusions": list(formulation.get("exclusions") or [])[:max_links],
            "success_conditions": list(formulation.get("success_conditions") or [])[:max_links],
            "candidate_plan": list(formulation.get("candidate_plan") or [])[:max_links * 2],
            "adequate": bool(formulation.get("adequate")),
            "can_plan": bool(formulation.get("can_plan")),
            "requires_clarification": bool(formulation.get("requires_clarification")),
            "confidence": float(formulation.get("confidence") or 0.0),
        },
        "matched_patterns": list(plan.get("matched_patterns") or [])[:6],
        "next_action": plan.get("next_action", ""),
        "progress_mode": plan.get("progress_mode", ""),
        "missing_links": [
            {
                "label": link.get("label", ""),
                "status": link.get("status", ""),
                "requires": list(link.get("requires") or [])[:3],
            }
            for link in list(plan.get("missing_links") or [])[:max_links]
            if isinstance(link, dict)
        ],
        "resolution_options": [
            {
                "key": option.get("key", ""),
                "label": option.get("label", ""),
                "confidence": option.get("confidence", 0),
                "requires_approval": bool(option.get("requires_approval", False)),
            }
            for option in list(plan.get("resolution_options") or [])[:max_options]
            if isinstance(option, dict)
        ],
        "capability_resolution_plan": [
            {
                "capability": item.get("capability", ""),
                "label": item.get("label", ""),
                "status": item.get("status", ""),
                "chosen_strategy": item.get("chosen_strategy", ""),
                "strategies": [
                    {
                        "key": strategy.get("key", ""),
                        "confidence": strategy.get("confidence", 0),
                        "requires_internet": bool(strategy.get("requires_internet", False)),
                        "requires_approval": bool(strategy.get("requires_approval", False)),
                        "requires_license_check": bool(strategy.get("requires_license_check", False)),
                    }
                    for strategy in list(item.get("strategies") or [])[:2]
                    if isinstance(strategy, dict)
                ],
            }
            for item in list(plan.get("capability_resolution_plan") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "adaptive_sequence": [
            {
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "action": item.get("action", ""),
            }
            for item in list(plan.get("adaptive_sequence") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "mixed_operation_sequence": [
            {
                "step": item.get("step", 0),
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "action_type": item.get("action_type", ""),
                "planned_call": {
                    "callable": (item.get("planned_call") or {}).get("callable", ""),
                    "implementation_status": (item.get("planned_call") or {}).get("implementation_status", ""),
                    "capability": (item.get("planned_call") or {}).get("capability", ""),
                    "host": (item.get("planned_call") or {}).get("host", ""),
                    "arguments": dict((item.get("planned_call") or {}).get("arguments") or {}),
                    "dependencies": list((item.get("planned_call") or {}).get("dependencies") or [])[:8],
                    "expected_outputs": list((item.get("planned_call") or {}).get("expected_outputs") or [])[:8],
                    "readback_validation": list((item.get("planned_call") or {}).get("readback_validation") or [])[:8],
                },
                "requires_network": bool(item.get("requires_network", False)),
                "requires_approval": bool(item.get("requires_approval", False)),
                "requires_license_check": bool(item.get("requires_license_check", False)),
                "report_sources": bool(item.get("report_sources", False)),
            }
            for item in list(plan.get("mixed_operation_sequence") or [])[:max_links * 3]
            if isinstance(item, dict)
        ],
        "operation_contracts": [
            {
                "id": item.get("id", ""),
                "action_type": item.get("action_type", ""),
                "capability": item.get("capability", ""),
                "execution_host": item.get("execution_host", ""),
                "provider_id": item.get("provider_id", ""),
                "callable": item.get("callable", ""),
                "call_arguments": dict(item.get("call_arguments") or {}),
                "call_dependencies": list(item.get("call_dependencies") or [])[:8],
                "validation_steps": list(item.get("validation_steps") or [])[:8],
                "planned_call": {
                    "callable": (item.get("planned_call") or {}).get("callable", item.get("callable", "")),
                    "implementation_status": (item.get("planned_call") or {}).get("implementation_status", ""),
                    "arguments": dict((item.get("planned_call") or {}).get("arguments") or item.get("call_arguments") or {}),
                    "dependencies": list((item.get("planned_call") or {}).get("dependencies") or item.get("call_dependencies") or [])[:8],
                    "readback_validation": list((item.get("planned_call") or {}).get("readback_validation") or item.get("validation_steps") or [])[:8],
                },
                "approval_policy": item.get("approval_policy", ""),
                "network_requirement": item.get("network_requirement", ""),
            }
            for item in list(plan.get("operation_contracts") or [])[:max_links * 2]
            if isinstance(item, dict)
        ],
        "mixed_operation_graph": {
            "framework": (plan.get("mixed_operation_graph") or {}).get("framework", ""),
            "base_graph": (plan.get("mixed_operation_graph") or {}).get("base_graph", ""),
            "node_count": len((plan.get("mixed_operation_graph") or {}).get("nodes") or []),
            "edge_count": len((plan.get("mixed_operation_graph") or {}).get("edges") or []),
            "supports": list((plan.get("mixed_operation_graph") or {}).get("supports") or [])[:8],
        },
        "canonical_action_graph": {
            "framework": "reasoning_runtime.action.action_graph_service.ActionGraph",
            "intent": (plan.get("canonical_action_graph") or {}).get("intent", ""),
            "planner": (plan.get("canonical_action_graph") or {}).get("planner", ""),
            "action_count": len((plan.get("canonical_action_graph") or {}).get("actions") or []),
            "validation": (plan.get("canonical_action_graph") or {}).get("validation", {}),
        },
        "pipeline_materialization_plan": {
            "framework": (plan.get("pipeline_materialization_plan") or {}).get("framework", ""),
            "convertible": bool((plan.get("pipeline_materialization_plan") or {}).get("convertible", False)),
            "status": (plan.get("pipeline_materialization_plan") or {}).get("status", ""),
            "default_promotion_scope": (plan.get("pipeline_materialization_plan") or {}).get("default_promotion_scope", ""),
            "generated_function_root": (plan.get("pipeline_materialization_plan") or {}).get("generated_function_root", ""),
            "third_party_wrapper_root": (plan.get("pipeline_materialization_plan") or {}).get("third_party_wrapper_root", ""),
            "generated_callable_candidates": [
                {
                    "action_id": item.get("action_id", ""),
                    "capability": item.get("capability", ""),
                    "materialization_kind": item.get("materialization_kind", ""),
                    "status": item.get("status", ""),
                    "implementation_path": (item.get("implementation") or {}).get("path", ""),
                    "manifest_path": (item.get("manifest") or {}).get("path", ""),
                    "promotion_scope_default": item.get("promotion_scope_default", ""),
                    "trust_state": item.get("trust_state", ""),
                }
                for item in list((plan.get("pipeline_materialization_plan") or {}).get("generated_callable_candidates") or [])[:max_links]
                if isinstance(item, dict)
            ],
            "pipeline_node_candidates": [
                {
                    "action_id": item.get("action_id", ""),
                    "node_kind": item.get("node_kind", ""),
                    "pipeline_node_type": item.get("pipeline_node_type", ""),
                    "registered_callable": bool(item.get("registered_callable", False)),
                    "materializable": bool(item.get("materializable", False)),
                }
                for item in list((plan.get("pipeline_materialization_plan") or {}).get("pipeline_node_candidates") or [])[:max_links]
                if isinstance(item, dict)
            ],
        },
        "approval_gates": [
            {
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "requires_link": bool(item.get("requires_link", False)),
                "requires_fit_explanation": bool(item.get("requires_fit_explanation", False)),
                "requires_license_check": bool(item.get("requires_license_check", False)),
                "requires_user_approval": bool(item.get("requires_user_approval", False)),
            }
            for item in list(plan.get("approval_gates") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "source_report_requirements": [
            {
                "capability": item.get("capability", ""),
                "strategy": item.get("strategy", ""),
                "report_links": bool(item.get("report_links", False)),
                "report_relevance": bool(item.get("report_relevance", False)),
                "report_knowledge_added": bool(item.get("report_knowledge_added", False)),
            }
            for item in list(plan.get("source_report_requirements") or [])[:max_links]
            if isinstance(item, dict)
        ],
        "planned_actions": list(plan.get("planned_actions") or [])[:max_actions],
        "test_plan": list(plan.get("test_plan") or [])[:max_tests],
        "learning_recommendations": list(plan.get("learning_recommendations") or [])[:max_learning],
    }


def render_goal_gap_plan(plan: dict[str, Any] | None, *, max_links: int = 5) -> str:
    if not plan:
        return ""
    formulation = dict(plan.get("problem_formulation") or {})
    lines = [
        "Goal gap plan:",
        f"Goal: {plan.get('goal', '')}",
        f"Next action: {plan.get('next_action', '')}",
    ]
    if formulation:
        lines.extend([
            "Problem formulation:",
            f"- {formulation.get('interpreted_problem', '')}",
            f"- deliverables={', '.join(formulation.get('deliverables') or [])}",
            f"- adequate={str(bool(formulation.get('adequate'))).lower()} confidence={float(formulation.get('confidence') or 0):.2f}",
        ])
    links = list(plan.get("missing_links") or [])
    if links:
        lines.append("Missing or unverified links:")
        for link in links[:max_links]:
            lines.append(f"- {link.get('label', '')}: {link.get('status', '')}")
    options = list(plan.get("resolution_options") or [])
    if options:
        lines.append("Top resolution options:")
        for option in options[:3]:
            lines.append(f"- {option.get('label', '')} ({option.get('confidence', 0):.2f})")
    sequence = list(plan.get("adaptive_sequence") or [])
    if sequence:
        lines.append("Adaptive sequence:")
        for item in sequence[:4]:
            lines.append(f"- {item.get('action', '')}: {item.get('capability', '')} via {item.get('strategy', '')}")
    gates = list(plan.get("approval_gates") or [])
    if gates:
        lines.append("Source review gates:")
        for gate in gates[:3]:
            lines.append(f"- {gate.get('strategy', '')}: show links/relevance before use")
    source_reports = list(plan.get("source_report_requirements") or [])
    if source_reports:
        lines.append("Knowledge source report:")
        for item in source_reports[:3]:
            lines.append(f"- {item.get('strategy', '')}: report links and relevance after research")
    mixed = list(plan.get("mixed_operation_sequence") or [])
    if mixed:
        lines.append("Mixed operations:")
        for item in mixed[:5]:
            planned_call = dict(item.get("planned_call") or {})
            call_arguments = dict(planned_call.get("arguments") or {})
            arg_keys = ", ".join(list(call_arguments.keys())[:6])
            callable_name = planned_call.get("callable", "")
            call_text = f" call={callable_name}" if callable_name else ""
            args_text = f" args=[{arg_keys}]" if arg_keys else ""
            lines.append(f"- {item.get('action_type', '')}: {item.get('capability', '')}{call_text}{args_text}")
    graph = dict(plan.get("mixed_operation_graph") or {})
    if graph:
        lines.append(
            f"Operation graph: {graph.get('base_graph', 'ActionGraph')} "
            f"nodes={len(graph.get('nodes') or [])} edges={len(graph.get('edges') or [])}"
        )
    materializer = dict(plan.get("pipeline_materialization_plan") or {})
    if materializer:
        lines.append("Pipeline materialization:")
        lines.append(
            f"- convertible={str(bool(materializer.get('convertible'))).lower()} "
            f"generated={len(materializer.get('generated_callable_candidates') or [])} "
            f"default_scope={materializer.get('default_promotion_scope', '')}"
        )
        for item in list(materializer.get("generated_callable_candidates") or [])[:max_links]:
            implementation = item.get("implementation") or {}
            lines.append(f"- {item.get('capability', '')}: {implementation.get('path', '')}")
    actions = list(plan.get("planned_actions") or [])
    if actions:
        lines.append("Planned actions:")
        lines.extend(f"- {item}" for item in actions[:4])
    tests = list(plan.get("test_plan") or [])
    if tests:
        lines.append("How to test:")
        lines.extend(f"- {item}" for item in tests[:4])
    outline = list(plan.get("report_outline") or [])
    if outline:
        lines.append("Report outline:")
        lines.extend(f"- {item}" for item in outline[:5])
    learning = list(plan.get("learning_recommendations") or [])
    if learning:
        lines.append("Learning loop:")
        lines.extend(f"- {item}" for item in learning[:3])
    return "\n".join(lines)

