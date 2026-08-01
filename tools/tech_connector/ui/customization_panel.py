"""Customization Panel for Swappable Models, Services, and Extensibility Settings."""

import json
import importlib
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QTabWidget,
    QWidget,
    QFormLayout,
    QGridLayout,
    QScrollArea,
    QMessageBox,
    QComboBox,
    QCheckBox,
    QGroupBox
)

from tech_connector.services.settings_service import load_settings, save_settings

DEFAULTS = {
    "semantic_intent_model": "qwen3:4b-instruct",
    "fast_general_model": "qwen3:4b-instruct",
    "visual_media_model": "qwen3:4b-instruct",
    "fast_code_model": "qwen2.5-coder:7b",
    "embedding_model": "nomic-embed-text:latest",
    "fallback_general_model": "qwen3:4b-instruct",
    "fallback_semantic_intent_model": "qwen3:4b-instruct",
    "fallback_code_model": "qwen2.5-coder:7b",
    "custom_model_mappings": {},
    "custom_provider_function_bindings": {},
    "github_ingest_provider_type": "default",
    "github_ingest_provider_module": "default",
    "mod_tech_labs_api_key": "",
    "mod_tech_labs_workflow_id": "",
    "code_intel_provider_module": "default",
    "cognitive_routing_provider_module": "default",
    "planning_provider_module": "default",
    "vcs_provider_module": "default",
    "custom_dcc_packages": [],
    "custom_dcc_adapters": {},
    "custom_dcc_bridges": {},
    "openai_api_key": "",
    "anthropic_api_key": "",
    "gemini_api_key": "",
    "xai_api_key": "",
    "cloud_provider_model": "gpt-4o",
    "asset_optimizer_provider_module": "default",
    "use_websocket_bridge": False,
    "chatbot_provider_module": "default",
}

BACKEND_PROVIDER_CONTRACTS = {
    "github_ingest_module": {
        "title": "GitHub Ingestion Provider",
        "description": "Controls how GitHub links are parsed, downloaded, extracted, and handed back to Tech Connector.",
        "path_hint": "studio.providers.github_ingest",
        "callables": {
            "parse_github_repo_reference": "parse_github_repo_reference(repo_ref: str) -> GitHubRepoRef-like object",
            "github_api_repo_url": "github_api_repo_url(repo_ref: str) -> str",
            "download_and_extract_repo": "download_and_extract_repo(repo_name: str, repo_url: str, target_parent_dir: Path, progress_cb=None) -> Path",
            "ingest_github_repo": "ingest_github_repo(repo_ref, target_dir, progress_cb=None) -> dict with ok/path or ok/error",
        },
        "notes": "This must be a module path because Tech Connector calls both functions from the same provider module.",
    },
    "asset_optimizer_module": {
        "title": "Asset Optimizer Provider",
        "description": "Runs cleanup or optimization after assets are imported, such as resizing textures, compressing files, or preparing a downloaded bundle.",
        "path_hint": "studio.providers.asset_optimizer",
        "callables": {
            "optimize_assets": "optimize_assets(local_path: str | Path) -> None or dict",
        },
        "notes": "Runs after a repository or asset bundle is extracted.",
    },
    "code_intel_module": {
        "title": "Code Intelligence Provider",
        "description": "Builds the code context Tech Connector uses before answering code questions or making project edits.",
        "path_hint": "studio.providers.code_intelligence",
        "callables": {
            "build_code_intelligence_packet": "build_code_intelligence_packet(objective: str, *, active_path=None, project_root=None, limit=20, include_repo_map=True) -> dict",
            "render_code_intelligence_packet": "render_code_intelligence_packet(packet: dict | None, *, max_context_chars=5000) -> str",
        },
        "notes": "The render function is optional at runtime, but recommended so custom packets produce readable chat context.",
    },
    "routing_module": {
        "title": "Cognitive Routing Provider",
        "description": "Decides what kind of request the user made, such as chat, code work, 3D app work, search, planning, image, or video.",
        "path_hint": "studio.providers.cognitive_router",
        "callables": {
            "upgrade_route_decision": "upgrade_route_decision(prompt: str, baseline: PromptRouteDecision, **kwargs) -> PromptRouteDecision",
        },
        "notes": "Use this to change how prompts are classified before execution planning.",
    },
    "planning_module": {
        "title": "Planning Engine Provider",
        "description": "Turns a request into a capability-aware plan, including what is missing, what can be done now, and what needs setup.",
        "path_hint": "studio.providers.planner",
        "callables": {
            "build_goal_gap_plan": "build_goal_gap_plan(prompt: str, decision: dict | None = None) -> dict",
        },
        "notes": "Use this to replace or augment capability-gap planning.",
    },
    "chatbot_module": {
        "title": "Chatbot Provider",
        "description": "Generates the conversational answer when Tech Connector is responding in chat instead of running a tool.",
        "path_hint": "studio.providers.chatbot",
        "callables": {
            "generate_chat_response": "generate_chat_response(text: str, history: list[dict], append_chunk: Callable[[str], None]) -> None or str",
        },
        "notes": "This provider streams text by calling append_chunk(...).",
    },
}


class CustomizationPanel(QDialog):
    """Vibrant, premium tabbed customization panel for Tech Connector."""

    def __init__(self, parent=None, active_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("System Customization Panel")
        self.resize(780, 650)
        self.setMinimumSize(600, 520)
        self.provider_function_combos = {}
        self.provider_function_status = {}
        self.provider_function_groups = {}
        self.setup_ui(active_tab)
        self.load_values()

    def setup_ui(self, active_tab: int = 0):
        # Premium dark styling
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
                color: #e0e0e0;
            }
            QLabel {
                color: #b3b3b3;
                font-size: 12px;
            }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 12px;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                border: 1px solid #00aaff;
            }
            QComboBox QAbstractItemView {
                background-color: #1e1e1e;
                color: #ffffff;
                selection-background-color: #00aaff;
                selection-color: #ffffff;
            }
            QCheckBox {
                color: #ffffff;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #1e1e1e;
                border: 1px solid #444444;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #00aaff;
                border-color: #0088cc;
            }
            QGroupBox {
                color: #d6d6d6;
                border: 1px solid #333333;
                border-radius: 5px;
                margin-top: 12px;
                padding: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QGroupBox:checked {
                border-color: #00aaff;
            }
            QTabWidget::panel {
                border: 1px solid #292929;
                background-color: #151515;
                border-radius: 6px;
            }
            QTabBar::tab {
                background-color: #1e1e1e;
                color: #888888;
                padding: 10px 18px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid #292929;
                border-bottom: none;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #151515;
                color: #00aaff;
                font-weight: bold;
                border-bottom: 2px solid #00aaff;
            }
            QTabBar::tab:hover {
                background-color: #252525;
                color: #ffffff;
            }
            QPushButton {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2d2d2d;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #111111;
            }
            QPushButton#saveButton {
                background-color: #0088cc;
                border: 1px solid #00aaff;
            }
            QPushButton#saveButton:hover {
                background-color: #00aaff;
            }
            QPushButton#restoreButton {
                background-color: #5c1d1d;
                border: 1px solid #aa3333;
            }
            QPushButton#restoreButton:hover {
                background-color: #882222;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Header Title
        title_label = QLabel("SYSTEM CUSTOMIZATION PANEL")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title_label.setStyleSheet("color: #00aaff; letter-spacing: 1px;")
        main_layout.addWidget(title_label)

        sub_label = QLabel("Swap backend models, override processing services, and configure custom tool bridges.")
        sub_label.setStyleSheet("color: #777777; margin-bottom: 5px;")
        main_layout.addWidget(sub_label)

        # Tab Widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Tab 1: Models
        self.tab_models = QWidget()
        self.setup_models_tab()
        self.tabs.addTab(self.tab_models, "Local Models")

        # Tab 2: Cloud AI
        self.tab_cloud = QWidget()
        self.setup_cloud_tab()
        self.tabs.addTab(self.tab_cloud, "Cloud AI Options")

        # Tab 3: Connected Accounts & 1-Click Sign-Ins
        self.tab_integrations = QWidget()
        self.setup_integrations_tab()
        self.tabs.addTab(self.tab_integrations, "🔑 Connected Accounts & Logins")

        # Tab 4: Workflow Services
        self.tab_services = QWidget()
        self.setup_services_tab()
        self.tabs.addTab(self.tab_services, "Backend Services")

        # Tab 4: Extensibility & Bridges
        self.tab_ext = QWidget()
        self.setup_ext_tab()
        self.tabs.addTab(self.tab_ext, "Environment & Bridges")

        # Set index
        self.tabs.setCurrentIndex(active_tab)

        # Status & Validation Console
        self.console_label = QLabel("Status: Ready")
        self.console_label.setStyleSheet("""
            background-color: #0c0c0c;
            color: #888888;
            padding: 8px;
            border-radius: 4px;
            font-family: monospace;
            border: 1px solid #1a1a1a;
        """)
        main_layout.addWidget(self.console_label)

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        
        # View guidelines button
        btn_guide = QPushButton("View Developer Guidelines")
        btn_guide.setToolTip("Open CUSTOM_BACKEND_PROVIDERS.md reference guide")
        btn_guide.clicked.connect(self.view_guidelines)
        btn_layout.addWidget(btn_guide)

        # Validate button
        btn_validate = QPushButton("Validate Configuration")
        btn_validate.setToolTip("Check if custom modules can be successfully imported")
        btn_validate.clicked.connect(self.validate_configuration)
        btn_layout.addWidget(btn_validate)

        btn_layout.addStretch()

        # Restore defaults
        btn_restore = QPushButton("Restore Defaults")
        btn_restore.setObjectName("restoreButton")
        btn_restore.setToolTip("Reset all values back to the default Tech Connector configuration")
        btn_restore.clicked.connect(self.restore_defaults)
        btn_layout.addWidget(btn_restore)

        # Save & Cancel
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton("Save & Restart")
        btn_save.setObjectName("saveButton")
        btn_save.clicked.connect(self.save_values)
        btn_layout.addWidget(btn_save)

        main_layout.addLayout(btn_layout)

    def setup_models_tab(self):
        layout = QVBoxLayout(self.tab_models)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        # Inputs
        self.model_intent = QLineEdit()
        self.model_intent.setToolTip("Ollama model class for semantic intent understanding (e.g. qwen3:4b-instruct)")
        form.addRow("Semantic/Intent Model:", self.model_intent)

        self.model_general = QLineEdit()
        self.model_general.setToolTip("Ollama model class for general reasoning/answers (e.g. qwen3:4b-instruct)")
        form.addRow("Fast General Model:", self.model_general)

        self.model_visual = QLineEdit()
        self.model_visual.setToolTip("Ollama model class for image, video, camera, and visual media requests; prefer a non-coder or vision-capable model")
        form.addRow("Visual Media Model:", self.model_visual)

        self.model_code = QLineEdit()
        self.model_code.setToolTip("Ollama model class for code generation & edit queries (e.g. qwen2.5-coder:7b)")
        form.addRow("Fast Code Model:", self.model_code)

        self.model_embed = QLineEdit()
        self.model_embed.setToolTip("Ollama embedding model (e.g. nomic-embed-text:latest)")
        form.addRow("Embedding Model:", self.model_embed)

        self.model_fallback_gen = QLineEdit()
        self.model_fallback_gen.setToolTip("Ollama fallback model for general queries")
        form.addRow("Fallback General Model:", self.model_fallback_gen)

        self.model_fallback_sem = QLineEdit()
        self.model_fallback_sem.setToolTip("Ollama fallback model for semantic routing")
        form.addRow("Fallback Semantic Model:", self.model_fallback_sem)

        self.model_fallback_code = QLineEdit()
        self.model_fallback_code.setToolTip("Ollama fallback model for code operations")
        form.addRow("Fallback Code Model:", self.model_fallback_code)

        self.custom_mappings = QTextEdit()
        self.custom_mappings.setToolTip("JSON dictionary mapping Tech Connector role names to Ollama model names")
        self.custom_mappings.setPlaceholderText(
            '{\n'
            '  "visual_media": "llava:latest",\n'
            '  "image": "llava:latest",\n'
            '  "video": "llava:latest",\n'
            '  "general": "qwen3:4b-instruct"\n'
            '}'
        )
        self.custom_mappings.setMaximumHeight(100)
        form.addRow(
            "Custom Role Mappings (JSON):",
            self._field_with_help(self.custom_mappings, "role_mappings"),
        )

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _field_with_help(self, field, help_topic: str):
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(field, 1)
        row.addWidget(self._help_button(help_topic))
        return wrapper

    def _help_button(self, help_topic: str) -> QPushButton:
        button = QPushButton("How to")
        button.setMaximumWidth(78)
        button.setToolTip("Show setup examples for this customization field")
        button.clicked.connect(lambda _checked=False, topic=help_topic: self.show_customization_help(topic))
        return button

    def show_customization_help(self, topic: str):
        help_text = {
            "role_mappings": (
                "Custom Role Mappings let you override the model used for a named job.\n\n"
                "Use JSON where the key is the role and the value is an installed Ollama model.\n\n"
                "Common roles:\n"
                "- visual_media, image, video, camera\n"
                "- general, plan, docs\n"
                "- code, debug, unreal, maya, blender\n\n"
                "Example:\n"
                "{\n"
                '  "visual_media": "llava:latest",\n'
                '  "image": "llava:latest",\n'
                '  "code": "qwen2.5-coder:7b"\n'
                "}\n\n"
                "Tip: keep image/video/camera roles on a non-coder or vision-capable model."
            ),
            "backend_modules": (
                "Backend module fields accept Python import paths.\n\n"
                "Use 'default' for the built-in provider. To swap one, point at a module that Tech Connector can import from the project/PYTHONPATH.\n\n"
                "Important: the module is only the container. Expand Tech Connector Ports under each module, then bind every required operation to one of your module's functions. You can choose a discovered function or type a function name.\n\n"
                "Examples:\n"
                "- custom_ingest\n"
                "- studio.providers.github_ingest\n"
                "- studio.providers.planner\n\n"
                "After editing, click Detect functions, then Validate Configuration before Save & Restart. Missing or incompatible plugs fall back to the default Tech Connector provider."
            ),
            "dcc_bridges": (
                "DCC app customization has three layers:\n\n"
                "Custom DCC Package Names: comma-separated package folders inside the tools root.\n"
                "Example: maya_tools, unreal_tools, studio_blender_tools\n\n"
                "Custom DCC Adapters: JSON mapping app names to execution adapter classes.\n"
                "Adapter classes must instantiate with no arguments and expose query(request, context) and execute(request, context).\n"
                "Example:\n"
                "{\n"
                '  "unreal": "studio.adapters.UnrealAdapter",\n'
                '  "maya": "studio.adapters.MayaAdapter"\n'
                "}\n\n"
                "Custom DCC Bridges: JSON mapping app names to bridge delegate classes.\n"
                "Bridge classes must instantiate with no arguments and should expose execute_python(...) and/or health_check(...).\n"
                "Example:\n"
                "{\n"
                '  "unreal": "studio.bridges.UnrealBridge",\n'
                '  "blender": "studio.bridges.BlenderBridge"\n'
                "}\n\n"
                "Adapters usually translate operations. Bridges usually talk to a running app."
            ),
        }.get(topic, "No help is available for this field yet.")
        if topic in BACKEND_PROVIDER_CONTRACTS:
            help_text = self._backend_contract_help(topic)
        QMessageBox.information(self, "Customization Help", help_text)

    def _backend_contract_help(self, topic: str) -> str:
        contract = BACKEND_PROVIDER_CONTRACTS[topic]
        lines = [
            contract["title"],
            "",
            "Set this field to:",
            f"- default",
            f"- {contract['path_hint']}",
            "",
            "Required module functions:",
        ]
        for name, signature in contract["callables"].items():
            lines.append(f"- {signature}")
        lines.extend(
            [
                "",
            "Tech Connector Ports map each required operation to a function in your module. The selected binding is stored in custom_provider_function_bindings.\n",
            "Minimal module example:",
                f"# {contract['path_hint'].replace('.', '/')}.py",
            ]
        )
        for name in contract["callables"]:
            lines.append(f"def {name}(*args, **kwargs):")
            lines.append('    return {"ok": True}')
        lines.extend(["", str(contract.get("notes") or "")])
        return "\n".join(lines)

    def _provider_ports_widget(self, topic: str, module_field: QLineEdit) -> QGroupBox:
        contract = BACKEND_PROVIDER_CONTRACTS[topic]
        group = QGroupBox("Function hookups: Tech Connector needs -> your module provides")
        group.setCheckable(True)
        group.setChecked(False)
        group.setToolTip("Expand to choose which functions in your module handle each Tech Connector operation.")

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("Tech Connector port"), 0, 0)
        grid.addWidget(QLabel("Expected input/output"), 0, 1)
        grid.addWidget(QLabel(""), 0, 2)
        grid.addWidget(QLabel("Your function"), 0, 3)
        grid.addWidget(QLabel("Plug status"), 0, 4)

        self.provider_function_combos.setdefault(topic, {})
        self.provider_function_status.setdefault(topic, {})
        for row, (callable_name, signature) in enumerate((contract.get("callables") or {}).items(), start=1):
            port_label = QLabel(callable_name)
            port_label.setStyleSheet("color: #8ddcff; font-family: Consolas, Courier New, monospace;")
            signature_label = QLabel(signature)
            signature_label.setWordWrap(True)
            signature_label.setStyleSheet("color: #888888; font-size: 11px;")
            arrow = QLabel("->")
            arrow.setAlignment(Qt.AlignCenter)
            arrow.setStyleSheet("color: #00aaff; font-weight: bold;")
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItem(callable_name)
            combo.setToolTip("Choose a discovered function from your module, or type the exact function name to bind.")
            status = QLabel("Default")
            status.setAlignment(Qt.AlignCenter)
            self._set_provider_status(status, "default", "Default")
            self.provider_function_combos[topic][callable_name] = combo
            self.provider_function_status[topic][callable_name] = status

            grid.addWidget(port_label, row, 0)
            grid.addWidget(signature_label, row, 1)
            grid.addWidget(arrow, row, 2)
            grid.addWidget(combo, row, 3)
            grid.addWidget(status, row, 4)

        detect_btn = QPushButton("Detect functions")
        detect_btn.setToolTip("Import this module and list public callable functions as binding choices.")
        detect_btn.clicked.connect(lambda _checked=False, t=topic, f=module_field: self._refresh_provider_function_choices(t, f))
        grid.addWidget(detect_btn, len(contract.get("callables") or {}) + 1, 3, 1, 2)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(body)
        body.setVisible(False)
        group.toggled.connect(body.setVisible)
        self.provider_function_groups[topic] = group
        module_field.editingFinished.connect(lambda t=topic, f=module_field: self._refresh_provider_function_choices(t, f))
        module_field.textChanged.connect(lambda _text, t=topic, f=module_field: self._update_provider_ports_visibility(t, f))
        return group

    def _provider_description_widget(self, topic: str) -> QLabel:
        contract = BACKEND_PROVIDER_CONTRACTS[topic]
        description = QLabel(contract.get("description") or contract.get("notes") or "")
        description.setWordWrap(True)
        description.setStyleSheet("color: #8b949e; font-size: 11px; margin-top: -4px; margin-bottom: 4px;")
        return description

    def _update_provider_ports_visibility(self, topic: str, module_field: QLineEdit) -> None:
        group = self.provider_function_groups.get(topic)
        if not group:
            return
        group.setVisible(True)

    def _set_provider_status(self, label: QLabel, state: str, text: str) -> None:
        colors = {
            "valid": ("#0f3b24", "#55ff99", "#1f7a3e"),
            "warning": ("#3b2e0c", "#ffd166", "#8a6d1f"),
            "error": ("#3b0c0c", "#ff6666", "#7a1f1f"),
            "default": ("#151515", "#aaaaaa", "#333333"),
        }
        bg, fg, border = colors.get(state, colors["default"])
        label.setText(text)
        label.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            "border-radius: 4px; padding: 4px; font-size: 11px;"
        )

    def _selected_provider_bindings(self, topic: str) -> dict[str, str]:
        bindings = {}
        for port, combo in (self.provider_function_combos.get(topic) or {}).items():
            selected = combo.currentText().strip() if hasattr(combo, "currentText") else ""
            bindings[port] = selected or port
        return bindings

    def _collect_provider_function_bindings(self) -> dict[str, dict[str, str]]:
        collected = {}
        for topic in BACKEND_PROVIDER_CONTRACTS:
            topic_bindings = self._selected_provider_bindings(topic)
            if topic_bindings:
                collected[topic] = topic_bindings
        return collected

    def _refresh_provider_function_choices(self, topic: str, module_field: QLineEdit, saved_bindings: dict | None = None) -> None:
        module_path = module_field.text().strip()
        saved_topic = {}
        if isinstance(saved_bindings, dict):
            saved_topic = saved_bindings.get(topic) or {}
        try:
            from tech_connector.services.modular_provider_utils import discover_module_callables
            discovered = discover_module_callables(module_path)
            import_error = ""
        except Exception as exc:
            discovered = {}
            import_error = str(exc)

        for port, combo in (self.provider_function_combos.get(topic) or {}).items():
            current = str(saved_topic.get(port) or combo.currentText() or port).strip() or port
            combo.blockSignals(True)
            combo.clear()
            candidates = list(discovered.keys())
            if current and current not in candidates:
                candidates.insert(0, current)
            if port not in candidates:
                candidates.insert(0, port)
            combo.addItems(list(dict.fromkeys(candidates)))
            combo.setCurrentText(current)
            combo.blockSignals(False)

            status = (self.provider_function_status.get(topic) or {}).get(port)
            if not status:
                continue
            if not module_path or module_path == "default":
                self._set_provider_status(status, "default", "Default")
            elif import_error:
                self._set_provider_status(status, "error", "Import failed")
            elif current in discovered:
                self._set_provider_status(status, "valid", "Valid")
            else:
                self._set_provider_status(status, "warning", "Fallback")
        self._update_provider_ports_visibility(topic, module_field)

    def _refresh_all_provider_function_choices(self, saved_bindings: dict | None = None) -> None:
        topic_fields = {
            "github_ingest_module": self.prov_ingest,
            "asset_optimizer_module": self.asset_optimizer_module,
            "code_intel_module": self.prov_intel,
            "routing_module": self.prov_router,
            "planning_module": self.prov_planner,
            "chatbot_module": self.prov_chatbot,
        }
        for topic, field in topic_fields.items():
            self._refresh_provider_function_choices(topic, field, saved_bindings)

    def setup_cloud_tab(self):
        layout = QVBoxLayout(self.tab_cloud)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        account_note = QLabel(
            "🔑 100% Keyless Web SSO OAuth: Click any provider button below to launch official account device authentication. "
            "Click 'Authorize' in the browser window that opens. No API keys are needed, copied, or stored!"
        )
        account_note.setWordWrap(True)
        account_note.setStyleSheet("color: #00ffaa; font-weight: bold; font-size: 11px; margin-bottom: 8px;")
        form.addRow(account_note)

        account_buttons = QWidget()
        account_layout = QHBoxLayout(account_buttons)
        account_layout.setContentsMargins(0, 0, 0, 0)
        account_layout.setSpacing(8)
        
        provider_styles = {
            "openai": ("🤖 OpenAI (GPT-4 / Codex)", "background: linear-gradient(135deg, #10a37f, #0d8a6a); color: #fff; font-weight: bold; padding: 10px; border-radius: 6px;"),
            "google": ("✨ Google (Gemini / AGY)", "background: linear-gradient(135deg, #1a73e8, #1557b0); color: #fff; font-weight: bold; padding: 10px; border-radius: 6px;"),
            "anthropic": ("🧠 Anthropic (Claude)", "background: linear-gradient(135deg, #d97706, #b45309); color: #fff; font-weight: bold; padding: 10px; border-radius: 6px;"),
            "x": ("🚀 xAI (Grok)", "background: linear-gradient(135deg, #2d004d, #4c0080); color: #fff; font-weight: bold; padding: 10px; border-radius: 6px;"),
        }
        
        for provider_id, (label, style) in provider_styles.items():
            button = QPushButton(f"Connect {label}")
            button.setStyleSheet(style)
            button.clicked.connect(
                lambda _checked=False, selected=provider_id: self.open_provider_login(
                    selected
                )
            )
            account_layout.addWidget(button)
        form.addRow("Cloud AI Sign-Ins:", account_buttons)

        self.provider_executable_edits = {}
        for provider_id, label in (
            ("openai", "Codex CLI"),
            ("x", "Grok CLI"),
            ("google", "Antigravity CLI"),
            ("anthropic", "Claude Code CLI"),
        ):
            executable_edit = QLineEdit()
            executable_edit.setPlaceholderText(
                "Optional executable path; PATH and standard locations are checked first"
            )
            self.provider_executable_edits[provider_id] = executable_edit
            form.addRow(f"{label} executable:", executable_edit)

        # Cloud model selector
        self.cloud_provider_model = QLineEdit()
        self.cloud_provider_model.setToolTip(
            "Cloud model name (for example gpt-5.6-sol, gpt-5.3-codex, "
            "claude-sonnet-5, or gemini-2.5-flash)"
        )
        form.addRow("Cloud Provider Model:", self.cloud_provider_model)

        # Keys
        self.openai_api_key = QLineEdit()
        self.openai_api_key.setEchoMode(QLineEdit.Password)
        self.openai_api_key.setToolTip("OpenAI API Key for GPT-4 models")
        form.addRow("OpenAI API Key:", self.openai_api_key)

        self.anthropic_api_key = QLineEdit()
        self.anthropic_api_key.setEchoMode(QLineEdit.Password)
        self.anthropic_api_key.setToolTip("Anthropic API Key for Claude models")
        form.addRow("Anthropic API Key:", self.anthropic_api_key)

        self.gemini_api_key = QLineEdit()
        self.gemini_api_key.setEchoMode(QLineEdit.Password)
        self.gemini_api_key.setToolTip("Google Gemini API Key")
        form.addRow("Gemini API Key:", self.gemini_api_key)

        self.xai_api_key = QLineEdit()
        self.xai_api_key.setEchoMode(QLineEdit.Password)
        self.xai_api_key.setToolTip("xAI API Key")
        form.addRow("X API Key:", self.xai_api_key)

        self.advanced_api_keys = QCheckBox("Advanced: show direct API-key fallbacks")
        form.addRow(self.advanced_api_keys)
        self._advanced_key_fields = (
            self.openai_api_key,
            self.anthropic_api_key,
            self.gemini_api_key,
            self.xai_api_key,
        )
        for field in self._advanced_key_fields:
            field.setVisible(False)
            label = form.labelForField(field)
            if label:
                label.setVisible(False)

        def show_advanced_keys(visible):
            for field in self._advanced_key_fields:
                field.setVisible(bool(visible))
                label = form.labelForField(field)
                if label:
                    label.setVisible(bool(visible))

        self.advanced_api_keys.toggled.connect(show_advanced_keys)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def open_provider_login(self, provider_id):
        """Launch official provider account login in browser and terminal."""
        from tech_connector.services.authenticated_provider_service import (
            begin_provider_login,
        )
        url = begin_provider_login(provider_id)
        if hasattr(self, "console_label"):
            self.console_label.setText(f"Status: Opened official login portal for {provider_id.upper()}")

    def setup_services_tab(self):
        layout = QVBoxLayout(self.tab_services)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.services_form = QFormLayout(content)
        self.services_form.setSpacing(10)

        # Ingestion Dropdown
        self.prov_ingest_type = QComboBox()
        self.prov_ingest_type.addItem("Default (Built-In)", "default")
        self.prov_ingest_type.addItem("MOD Tech Labs Pipeline", "mod_tech_labs")
        self.prov_ingest_type.addItem("Custom Python Module...", "custom")
        self.prov_ingest_type.setToolTip("Choose the service provider type for downloading & extracting GitHub repositories")
        self.services_form.addRow(
            "GitHub Ingestion Type:",
            self._field_with_help(self.prov_ingest_type, "github_ingest_module"),
        )

        # Custom module row
        self.prov_ingest = QLineEdit()
        self.prov_ingest.setToolTip("Python module path exposing parse_github_repo_reference(...) and ingest_github_repo(...)")
        self.prov_ingest.setPlaceholderText("default or studio.providers.github_ingest")
        self.prov_ingest_row = self._field_with_help(self.prov_ingest, "github_ingest_module")
        self.services_form.addRow(
            "Custom Ingestion Module:",
            self.prov_ingest_row,
        )
        self.prov_ingest_description = self._provider_description_widget("github_ingest_module")
        self.services_form.addRow("", self.prov_ingest_description)
        self.prov_ingest_label = self.services_form.labelForField(self.prov_ingest_row)
        self.prov_ingest_ports = self._provider_ports_widget("github_ingest_module", self.prov_ingest)
        self.services_form.addRow("", self.prov_ingest_ports)
        self.prov_ingest_ports_label = self.services_form.labelForField(self.prov_ingest_ports)

        # MOD Tech Labs Rows
        self.mod_api_key = QLineEdit()
        self.mod_api_key.setEchoMode(QLineEdit.Password)
        self.mod_api_key.setToolTip("API Key to authorize calls to your MOD Tech Labs workflow")
        self.services_form.addRow("MOD API Key:", self.mod_api_key)
        self.mod_api_key_label = self.services_form.labelForField(self.mod_api_key)

        self.mod_workflow_id = QLineEdit()
        self.mod_workflow_id.setToolTip("The unique Workflow execution UUID configured in your MOD dashboard")
        self.services_form.addRow("MOD Workflow ID:", self.mod_workflow_id)
        self.mod_workflow_id_label = self.services_form.labelForField(self.mod_workflow_id)

        # Connect dropdown change
        self.prov_ingest_type.currentIndexChanged.connect(self.toggle_ingest_fields)

        # Separator line
        self.services_form.addRow(QLabel(""))

        # Asset Optimizer
        self.asset_optimizer_module = QLineEdit()
        self.asset_optimizer_module.setToolTip("Python module path exposing optimize_assets(local_path)")
        self.asset_optimizer_module.setPlaceholderText("default or studio.providers.asset_optimizer")
        self.services_form.addRow(
            "Asset Optimizer Module:",
            self._field_with_help(self.asset_optimizer_module, "asset_optimizer_module"),
        )
        self.services_form.addRow("", self._provider_description_widget("asset_optimizer_module"))
        self.services_form.addRow("", self._provider_ports_widget("asset_optimizer_module", self.asset_optimizer_module))

        self.prov_intel = QLineEdit()
        self.prov_intel.setToolTip("Python module path exposing build_code_intelligence_packet(...)")
        self.prov_intel.setPlaceholderText("default or studio.providers.code_intelligence")
        self.services_form.addRow(
            "Code Intelligence Module:",
            self._field_with_help(self.prov_intel, "code_intel_module"),
        )
        self.services_form.addRow("", self._provider_description_widget("code_intel_module"))
        self.services_form.addRow("", self._provider_ports_widget("code_intel_module", self.prov_intel))

        self.prov_router = QLineEdit()
        self.prov_router.setToolTip("Python module path exposing upgrade_route_decision(prompt, baseline, **kwargs)")
        self.prov_router.setPlaceholderText("default or studio.providers.cognitive_router")
        self.services_form.addRow(
            "Cognitive Routing Module:",
            self._field_with_help(self.prov_router, "routing_module"),
        )
        self.services_form.addRow("", self._provider_description_widget("routing_module"))
        self.services_form.addRow("", self._provider_ports_widget("routing_module", self.prov_router))

        self.prov_planner = QLineEdit()
        self.prov_planner.setToolTip("Python module path exposing build_goal_gap_plan(prompt, decision=None)")
        self.prov_planner.setPlaceholderText("default or studio.providers.planner")
        self.services_form.addRow(
            "Planning Engine Module:",
            self._field_with_help(self.prov_planner, "planning_module"),
        )
        self.services_form.addRow("", self._provider_description_widget("planning_module"))
        self.services_form.addRow("", self._provider_ports_widget("planning_module", self.prov_planner))

        self.prov_chatbot = QLineEdit()
        self.prov_chatbot.setToolTip("Python module path exposing generate_chat_response(text, history, append_chunk)")
        self.prov_chatbot.setPlaceholderText("default or studio.providers.chatbot")
        self.services_form.addRow(
            "Chatbot Provider Module:",
            self._field_with_help(self.prov_chatbot, "chatbot_module"),
        )
        self.services_form.addRow("", self._provider_description_widget("chatbot_module"))
        self.services_form.addRow("", self._provider_ports_widget("chatbot_module", self.prov_chatbot))

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def toggle_ingest_fields(self):
        current_type = self.prov_ingest_type.currentData()
        
        # Hide custom module inputs by default
        self.prov_ingest_row.setVisible(current_type == "custom")
        if self.prov_ingest_label:
            self.prov_ingest_label.setVisible(current_type == "custom")
        self.prov_ingest_description.setVisible(current_type == "custom")
        self.prov_ingest_ports.setVisible(current_type == "custom")
        self._update_provider_ports_visibility("github_ingest_module", self.prov_ingest)
        if current_type != "custom":
            self.prov_ingest_ports.setVisible(False)
        if self.prov_ingest_ports_label:
            self.prov_ingest_ports_label.setVisible(current_type == "custom")

        # Hide MOD inputs by default
        self.mod_api_key.setVisible(current_type == "mod_tech_labs")
        self.mod_workflow_id.setVisible(current_type == "mod_tech_labs")
        if self.mod_api_key_label:
            self.mod_api_key_label.setVisible(current_type == "mod_tech_labs")
        if self.mod_workflow_id_label:
            self.mod_workflow_id_label.setVisible(current_type == "mod_tech_labs")

    def setup_ext_tab(self):
        layout = QVBoxLayout(self.tab_ext)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        # WebSockets Toggler
        self.use_websocket_bridge = QCheckBox("Enable bidirectional WebSocket connection for DCC bridges")
        self.use_websocket_bridge.setToolTip("Streams console outputs in real-time. If connection fails, automatically falls back to HTTP REST.")
        form.addRow("", self.use_websocket_bridge)
        form.addRow("", self._help_button("dcc_bridges"))

        self.prov_vcs = QLineEdit()
        self.prov_vcs.setToolTip("Python class path subclassing VersionControlProvider (e.g. my_vcs.MyVcsProvider)")
        form.addRow("VCS Provider Class:", self.prov_vcs)

        self.custom_dcc_packages = QLineEdit()
        self.custom_dcc_packages.setToolTip("Comma-separated list of custom DCC tool folder names inside TOOLS_ROOT")
        self.custom_dcc_packages.setPlaceholderText("maya_tools, unreal_tools, studio_blender_tools")
        form.addRow("Custom DCC Package Names:", self.custom_dcc_packages)

        self.custom_dcc_adapters = QTextEdit()
        self.custom_dcc_adapters.setToolTip("JSON mapping of DCC names to custom execution adapter classes (e.g. {'unreal': 'my_mod.UnrealAdapter'})")
        self.custom_dcc_adapters.setPlaceholderText(
            '{\n'
            '  "unreal": "studio.adapters.UnrealAdapter",\n'
            '  "maya": "studio.adapters.MayaAdapter"\n'
            '}'
        )
        self.custom_dcc_adapters.setMaximumHeight(100)
        form.addRow(
            "Custom DCC Adapters (JSON):",
            self._field_with_help(self.custom_dcc_adapters, "dcc_bridges"),
        )

        self.custom_dcc_bridges = QTextEdit()
        self.custom_dcc_bridges.setToolTip("JSON mapping of DCC names to custom bridge delegates (e.g. {'unreal': 'my_ludus.LudusBridge'})")
        self.custom_dcc_bridges.setPlaceholderText(
            '{\n'
            '  "unreal": "studio.bridges.UnrealBridge",\n'
            '  "blender": "studio.bridges.BlenderBridge"\n'
            '}'
        )
        self.custom_dcc_bridges.setMaximumHeight(100)
        form.addRow(
            "Custom DCC Bridges (JSON):",
            self._field_with_help(self.custom_dcc_bridges, "dcc_bridges"),
        )

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def load_values(self):
        settings = load_settings()

        self.model_intent.setText(str(settings.get("semantic_intent_model", DEFAULTS["semantic_intent_model"])))
        self.model_general.setText(str(settings.get("fast_general_model", DEFAULTS["fast_general_model"])))
        self.model_visual.setText(str(settings.get("visual_media_model", DEFAULTS["visual_media_model"])))
        self.model_code.setText(str(settings.get("fast_code_model", DEFAULTS["fast_code_model"])))
        self.model_embed.setText(str(settings.get("embedding_model", DEFAULTS["embedding_model"])))
        self.model_fallback_gen.setText(str(settings.get("fallback_general_model", DEFAULTS["fallback_general_model"])))
        self.model_fallback_sem.setText(str(settings.get("fallback_semantic_intent_model", DEFAULTS["fallback_semantic_intent_model"])))
        self.model_fallback_code.setText(str(settings.get("fallback_code_model", DEFAULTS["fallback_code_model"])))

        # Custom Mappings
        custom_maps = settings.get("custom_model_mappings", DEFAULTS["custom_model_mappings"])
        self.custom_mappings.setPlainText(json.dumps(custom_maps, indent=2))

        # Cloud
        self.cloud_provider_model.setText(str(settings.get("cloud_provider_model", DEFAULTS["cloud_provider_model"])))
        self.openai_api_key.setText(str(settings.get("openai_api_key", DEFAULTS["openai_api_key"])))
        self.anthropic_api_key.setText(str(settings.get("anthropic_api_key", DEFAULTS["anthropic_api_key"])))
        self.gemini_api_key.setText(str(settings.get("gemini_api_key", DEFAULTS["gemini_api_key"])))
        self.xai_api_key.setText(str(settings.get("xai_api_key", DEFAULTS["xai_api_key"])))
        configured_executables = settings.get("provider_executables") or {}
        for provider_id, executable_edit in self.provider_executable_edits.items():
            executable_edit.setText(str(configured_executables.get(provider_id) or ""))

        # Services
        ingest_type = settings.get("github_ingest_provider_type", DEFAULTS["github_ingest_provider_type"])
        idx = self.prov_ingest_type.findData(ingest_type)
        if idx >= 0:
            self.prov_ingest_type.setCurrentIndex(idx)

        self.prov_ingest.setText(str(settings.get("github_ingest_provider_module", DEFAULTS["github_ingest_provider_module"])))
        self.mod_api_key.setText(str(settings.get("mod_tech_labs_api_key", DEFAULTS["mod_tech_labs_api_key"])))
        self.mod_workflow_id.setText(str(settings.get("mod_tech_labs_workflow_id", DEFAULTS["mod_tech_labs_workflow_id"])))

        self.asset_optimizer_module.setText(str(settings.get("asset_optimizer_provider_module", DEFAULTS["asset_optimizer_provider_module"])))
        self.prov_intel.setText(str(settings.get("code_intel_provider_module", DEFAULTS["code_intel_provider_module"])))
        self.prov_router.setText(str(settings.get("cognitive_routing_provider_module", DEFAULTS["cognitive_routing_provider_module"])))
        self.prov_planner.setText(str(settings.get("planning_provider_module", DEFAULTS["planning_provider_module"])))
        self.prov_chatbot.setText(str(settings.get("chatbot_provider_module", DEFAULTS["chatbot_provider_module"])))
        self._refresh_all_provider_function_choices(
            settings.get("custom_provider_function_bindings", DEFAULTS["custom_provider_function_bindings"])
        )

        # Ext
        self.use_websocket_bridge.setChecked(bool(settings.get("use_websocket_bridge", DEFAULTS["use_websocket_bridge"])))
        self.prov_vcs.setText(str(settings.get("vcs_provider_module", DEFAULTS["vcs_provider_module"])))
        
        # DCC packages
        dcc_pkgs = settings.get("custom_dcc_packages", DEFAULTS["custom_dcc_packages"])
        self.custom_dcc_packages.setText(", ".join(dcc_pkgs))

        # Adapters and Bridges
        dcc_adapters = settings.get("custom_dcc_adapters", DEFAULTS["custom_dcc_adapters"])
        self.custom_dcc_adapters.setPlainText(json.dumps(dcc_adapters, indent=2))

        dcc_bridges = settings.get("custom_dcc_bridges", DEFAULTS["custom_dcc_bridges"])
        self.custom_dcc_bridges.setPlainText(json.dumps(dcc_bridges, indent=2))

        # Call toggle layout
        self.toggle_ingest_fields()

    def save_values(self):
        # Validate JSON structures
        try:
            custom_maps = json.loads(self.custom_mappings.toPlainText() or "{}")
        except ValueError:
            QMessageBox.critical(self, "Invalid JSON", "Custom Role Mappings must be valid JSON.")
            return

        try:
            dcc_adapters = json.loads(self.custom_dcc_adapters.toPlainText() or "{}")
        except ValueError:
            QMessageBox.critical(self, "Invalid JSON", "Custom DCC Adapters must be valid JSON.")
            return

        try:
            dcc_bridges = json.loads(self.custom_dcc_bridges.toPlainText() or "{}")
        except ValueError:
            QMessageBox.critical(self, "Invalid JSON", "Custom DCC Bridges must be valid JSON.")
            return

        # Parse custom DCC packages
        dcc_pkgs = [p.strip() for p in self.custom_dcc_packages.text().split(",") if p.strip()]

        settings = load_settings()
        settings["semantic_intent_model"] = self.model_intent.text().strip()
        settings["fast_general_model"] = self.model_general.text().strip()
        settings["visual_media_model"] = self.model_visual.text().strip()
        settings["fast_code_model"] = self.model_code.text().strip()
        settings["embedding_model"] = self.model_embed.text().strip()
        settings["fallback_general_model"] = self.model_fallback_gen.text().strip()
        settings["fallback_semantic_intent_model"] = self.model_fallback_sem.text().strip()
        settings["fallback_code_model"] = self.model_fallback_code.text().strip()
        settings["custom_model_mappings"] = custom_maps

        # Cloud
        settings["cloud_provider_model"] = self.cloud_provider_model.text().strip()
        settings["openai_api_key"] = self.openai_api_key.text().strip()
        settings["anthropic_api_key"] = self.anthropic_api_key.text().strip()
        settings["gemini_api_key"] = self.gemini_api_key.text().strip()
        settings["xai_api_key"] = self.xai_api_key.text().strip()
        settings["provider_executables"] = {
            provider_id: executable_edit.text().strip()
            for provider_id, executable_edit in self.provider_executable_edits.items()
            if executable_edit.text().strip()
        }

        # Services
        settings["github_ingest_provider_type"] = self.prov_ingest_type.currentData()
        settings["github_ingest_provider_module"] = self.prov_ingest.text().strip()
        settings["mod_tech_labs_api_key"] = self.mod_api_key.text().strip()
        settings["mod_tech_labs_workflow_id"] = self.mod_workflow_id.text().strip()

        settings["asset_optimizer_provider_module"] = self.asset_optimizer_module.text().strip()
        settings["code_intel_provider_module"] = self.prov_intel.text().strip()
        settings["cognitive_routing_provider_module"] = self.prov_router.text().strip()
        settings["planning_provider_module"] = self.prov_planner.text().strip()
        settings["chatbot_provider_module"] = self.prov_chatbot.text().strip()
        settings["custom_provider_function_bindings"] = self._collect_provider_function_bindings()

        # Ext
        settings["use_websocket_bridge"] = self.use_websocket_bridge.isChecked()
        settings["vcs_provider_module"] = self.prov_vcs.text().strip()
        settings["custom_dcc_packages"] = dcc_pkgs
        settings["custom_dcc_adapters"] = dcc_adapters
        settings["custom_dcc_bridges"] = dcc_bridges

        save_settings(settings)
        self.console_label.setText("Status: Settings saved. Please restart Tech Connector to apply all modifications.")
        QMessageBox.information(self, "Settings Saved", "Customization settings saved successfully. Please restart Tech Connector.")
        self.accept()

    def restore_defaults(self):
        reply = QMessageBox.question(
            self, 
            "Restore Defaults?",
            "Are you sure you want to restore all options to their original default settings? This will clear all custom modules and mappings.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            settings = load_settings()
            for k, v in DEFAULTS.items():
                settings[k] = v
            save_settings(settings)
            self.load_values()
            self.console_label.setText("Status: Defaults restored successfully.")
            QMessageBox.information(self, "Defaults Restored", "All customization settings have been restored to their defaults.")

    def view_guidelines(self):
        guide_path = Path(__file__).parent.parent / "docs" / "CUSTOM_BACKEND_PROVIDERS.md"
        if guide_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide_path.resolve())))
        else:
            QMessageBox.warning(self, "Not Found", f"Developer guidelines document not found at {guide_path}")

    def validate_configuration(self):
        self.console_label.setText("Status: Validating configuration...")
        self.console_label.repaint()

        errors = []
        successes = []
        
        # Ingest validation depends on provider type
        ingest_type = self.prov_ingest_type.currentData()
        if ingest_type == "custom":
            mod_path = self.prov_ingest.text().strip()
            if mod_path and mod_path != "default":
                self._validate_provider_contract(errors, successes, "GitHub Ingest Module", mod_path, "github_ingest_module")
        elif ingest_type == "mod_tech_labs":
            api_key = self.mod_api_key.text().strip()
            wf_id = self.mod_workflow_id.text().strip()
            if not api_key:
                errors.append("MOD API Key is empty.")
            if not wf_id:
                errors.append("MOD Workflow ID is empty.")

        # Asset Optimizer validation
        opt_path = self.asset_optimizer_module.text().strip()
        if opt_path and opt_path != "default":
            self._validate_provider_contract(errors, successes, "Asset Optimizer Module", opt_path, "asset_optimizer_module")

        # Other services
        modules_to_test = {
            "Code Intel": (self.prov_intel.text().strip(), "code_intel_module"),
            "Router": (self.prov_router.text().strip(), "routing_module"),
            "Planner": (self.prov_planner.text().strip(), "planning_module"),
            "Chatbot": (self.prov_chatbot.text().strip(), "chatbot_module"),
        }

        for name, (mod_path, topic) in modules_to_test.items():
            if mod_path and mod_path != "default":
                self._validate_provider_contract(errors, successes, f"{name} Module", mod_path, topic)

        # Check VCS provider class
        vcs_class_path = self.prov_vcs.text().strip()
        if vcs_class_path and vcs_class_path != "default":
            if "." in vcs_class_path:
                try:
                    mod_name, class_name = vcs_class_path.rsplit(".", 1)
                    mod = importlib.import_module(mod_name)
                    cls_obj = getattr(mod, class_name)
                    if not callable(cls_obj):
                        errors.append(f"VCS Class ({vcs_class_path}): `{class_name}` is not callable/class-like")
                    else:
                        successes.append(f"VCS Class ({vcs_class_path}): class resolved")
                except Exception as e:
                    errors.append(f"VCS Class ({vcs_class_path}): {e}")
            else:
                errors.append(f"VCS Class ({vcs_class_path}): Class path must include module dot separation (e.g. module.ClassName)")

        # Check DCC adapters
        try:
            adapters = json.loads(self.custom_dcc_adapters.toPlainText() or "{}")
            if isinstance(adapters, dict):
                for dcc, class_path in adapters.items():
                    if class_path and class_path != "default":
                        if "." in class_path:
                            try:
                                cls_obj = self._resolve_class_path(class_path)
                                instance = cls_obj()
                                missing = [
                                    name for name in ("query", "execute")
                                    if not callable(getattr(instance, name, None))
                                ]
                                if missing:
                                    errors.append(
                                        f"DCC Adapter {dcc} ({class_path}): missing method(s) {', '.join(missing)}. "
                                        "Expected query(request, context) and execute(request, context)."
                                    )
                                else:
                                    successes.append(f"DCC Adapter {dcc} ({class_path}): class instantiated; query/execute found")
                            except Exception as e:
                                errors.append(f"DCC Adapter {dcc} ({class_path}): {e}")
                        else:
                            errors.append(f"DCC Adapter {dcc} ({class_path}): Class path must include module dot separation")
        except Exception:
            pass

        # Check DCC bridges
        try:
            bridges = json.loads(self.custom_dcc_bridges.toPlainText() or "{}")
            if isinstance(bridges, dict):
                for dcc, class_path in bridges.items():
                    if class_path and class_path != "default":
                        if "." in class_path:
                            try:
                                cls_obj = self._resolve_class_path(class_path)
                                instance = cls_obj()
                                bridge_methods = [
                                    name for name in ("execute_python", "health_check")
                                    if callable(getattr(instance, name, None))
                                ]
                                if bridge_methods:
                                    successes.append(
                                        f"DCC Bridge {dcc} ({class_path}): class instantiated; found {', '.join(bridge_methods)}"
                                    )
                                else:
                                    errors.append(
                                        f"DCC Bridge {dcc} ({class_path}): class instantiated but no common bridge method was found. "
                                        "Expected execute_python(...) and/or health_check(...)."
                                    )
                            except Exception as e:
                                errors.append(f"DCC Bridge {dcc} ({class_path}): {e}")
                        else:
                            errors.append(f"DCC Bridge {dcc} ({class_path}): Class path must include module dot separation")
        except Exception:
            pass

        if errors:
            self.console_label.setStyleSheet("background-color: #3b0c0c; color: #ff5555; padding: 8px; border-radius: 4px; border: 1px solid #7a1f1f; font-family: monospace;")
            detail = "\n".join(errors)
            if successes:
                detail += "\n\nPassed checks:\n" + "\n".join(successes)
            self.console_label.setText("Validation Failed:\n" + detail)
            QMessageBox.warning(self, "Validation Failed", "Some custom provider contracts failed:\n\n" + detail)
        else:
            self.console_label.setStyleSheet("background-color: #0c3b1e; color: #55ff55; padding: 8px; border-radius: 4px; border: 1px solid #1f7a3e; font-family: monospace;")
            detail = "\n".join(successes) if successes else "Using built-in default providers; no custom contracts to validate."
            self.console_label.setText("Status: Validation Succeeded.\n" + detail)
            QMessageBox.information(self, "Validation Succeeded", "Custom provider contracts validated:\n\n" + detail)

    @staticmethod
    def _expected_callable_for_topic(topic: str, callable_name: str):
        try:
            if topic == "github_ingest_module":
                from tech_connector.services import github_ingest_service as svc
                return getattr(svc, callable_name, None)
            if topic == "code_intel_module":
                from tech_connector.services import code_intelligence_service as svc
                return getattr(svc, callable_name, None)
            if topic == "routing_module" and callable_name == "upgrade_route_decision":
                from tech_connector.services.reasoning.cognitive_routing_service import upgrade_route_decision
                return upgrade_route_decision
            if topic == "planning_module" and callable_name == "build_goal_gap_plan":
                from tech_connector.services.reasoning.goal_gap_planning_service import build_goal_gap_plan
                return build_goal_gap_plan
        except Exception:
            return None

        if topic == "asset_optimizer_module" and callable_name == "optimize_assets":
            def optimize_assets(local_path):
                return None
            return optimize_assets
        if topic == "chatbot_module" and callable_name == "generate_chat_response":
            def generate_chat_response(text, history, append_chunk):
                return None
            return generate_chat_response
        return None

    def _validate_provider_contract(
        self,
        errors: list[str],
        successes: list[str],
        label: str,
        provider_path: str,
        topic: str,
        bindings: dict[str, str] | None = None,
    ) -> None:
        contract = BACKEND_PROVIDER_CONTRACTS.get(topic) or {}
        callable_names = list((contract.get("callables") or {}).keys())
        if not callable_names:
            return
        try:
            module = importlib.import_module(provider_path)
        except Exception as exc:
            errors.append(f"{label} ({provider_path}): import failed: {exc}")
            return

        try:
            from tech_connector.services.modular_provider_utils import discover_module_callables, signature_accepts_expected
            discovered = discover_module_callables(provider_path)
        except Exception:
            discovered = {}
            signature_accepts_expected = None

        selected_bindings = dict(bindings or {})
        if not selected_bindings and self is not None and hasattr(self, "_selected_provider_bindings"):
            selected_bindings = self._selected_provider_bindings(topic)

        for callable_name in callable_names:
            bound_name = str(selected_bindings.get(callable_name) or callable_name).strip() or callable_name
            value = getattr(module, bound_name, None)
            status = None
            if self is not None:
                status = (getattr(self, "provider_function_status", {}).get(topic) or {}).get(callable_name)
            if not callable(value):
                if status:
                    self._set_provider_status(status, "error", "Missing")
                errors.append(
                    f"{label} ({provider_path}): Tech Connector port `{callable_name}` is bound to `{bound_name}`, "
                    "but that function was not found. Falling back to the default Tech Connector provider for this operation. "
                    f"Expected {contract['callables'][callable_name]}"
                )
            else:
                expected = self._expected_callable_for_topic(topic, callable_name) if self is not None else CustomizationPanel._expected_callable_for_topic(topic, callable_name)
                compatible = True
                reason = "signature compatible"
                if expected is not None and signature_accepts_expected is not None:
                    compatible, reason = signature_accepts_expected(value, expected)
                if compatible:
                    if status:
                        self._set_provider_status(status, "valid", "Valid")
                    detail = discovered.get(bound_name, bound_name)
                    successes.append(
                        f"{label} ({provider_path}): `{callable_name}` -> `{detail}` found; {reason}. "
                        "Output contract was not executed during validation."
                    )
                else:
                    if status:
                        self._set_provider_status(status, "warning", "Check args")
                    errors.append(
                        f"{label} ({provider_path}): Tech Connector port `{callable_name}` is bound to `{bound_name}`, "
                        f"but the inputs look incompatible: {reason}. Falling back to the default Tech Connector provider for this operation. "
                        f"Expected {contract['callables'][callable_name]}"
                    )

    def _resolve_class_path(self, class_path: str):
        mod_name, class_name = class_path.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        cls_obj = getattr(mod, class_name)
        if not callable(cls_obj):
            raise TypeError(f"`{class_name}` is not callable/class-like")
        return cls_obj


    def setup_integrations_tab(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from tech_connector.services.connected_account_service import (
            get_slack_oauth_authorize_url,
            get_discord_oauth_authorize_url,
            get_atlassian_oauth_authorize_url,
            get_clickup_oauth_authorize_url,
        )

        layout = QVBoxLayout(self.tab_integrations)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(12)

        header = QLabel("<h2>🔑 Streamlined 1-Click Connected Accounts</h2>")
        header.setStyleSheet("color: #f5fff8;")
        form.addRow(header)

        # Smart Atlassian URL Input
        self.atl_url_input = QLineEdit()
        self.atl_url_input.setPlaceholderText("Paste any Jira or Confluence URL (e.g. https://theentireworldstudios.atlassian.net)")
        self.atl_url_input.textChanged.connect(self._on_atl_url_changed)
        form.addRow("Atlassian URL / Project:", self.atl_url_input)
        sub = QLabel("Sign in with 1-click to automatically connect your Slack, Discord, Jira, Confluence, and ClickUp accounts with zero manual token copying.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #8fd6a5; font-size: 11px;")
        form.addRow(sub)

        # 1-Click OAuth Buttons
        btn_slack = QPushButton("💬 Sign in with Slack")
        btn_slack.setStyleSheet("padding: 10px; background: #4A154B; color: #ffffff; font-weight: bold; border-radius: 6px;")
        btn_slack.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(get_slack_oauth_authorize_url())))
        form.addRow("Slack Workspace:", btn_slack)

        btn_discord = QPushButton("🎮 Sign in with Discord")
        btn_discord.setStyleSheet("padding: 10px; background: #5865F2; color: #ffffff; font-weight: bold; border-radius: 6px;")
        btn_discord.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(get_discord_oauth_authorize_url())))
        form.addRow("Discord Server:", btn_discord)

        btn_atl = QPushButton("📋 Sign in with Atlassian (Jira & Confluence)")
        btn_atl.setStyleSheet("padding: 10px; background: #0052CC; color: #ffffff; font-weight: bold; border-radius: 6px;")
        btn_atl.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(get_atlassian_oauth_authorize_url())))
        form.addRow("Atlassian Cloud:", btn_atl)

        btn_cu = QPushButton("🎯 Sign in with ClickUp")
        btn_cu.setStyleSheet("padding: 10px; background: #7B68EE; color: #ffffff; font-weight: bold; border-radius: 6px;")
        btn_cu.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(get_clickup_oauth_authorize_url())))
        form.addRow("ClickUp Workspace:", btn_cu)

        # User Property Defaults
        form.addRow(QLabel("<h3>⚙️ User Property Defaults</h3>"))

        self.atl_def_priority = QLineEdit()
        self.atl_def_priority.setPlaceholderText("Medium")
        form.addRow("Atlassian Default Priority:", self.atl_def_priority)

        self.atl_def_assignee = QLineEdit()
        self.atl_def_assignee.setPlaceholderText("currentUser")
        form.addRow("Atlassian Default Assignee:", self.atl_def_assignee)

        self.cu_def_list = QLineEdit()
        self.cu_def_list.setPlaceholderText("Default List ID")
        form.addRow("ClickUp Default List ID:", self.cu_def_list)

        scroll.setWidget(content)
        layout.addWidget(scroll)


    def _on_atl_url_changed(self, text: str):
        from tech_connector.services.atlassian_service import parse_atlassian_input_url
        res = parse_atlassian_input_url(text)
        if res.get("site_url"):
            if hasattr(self, "console_label"):
                self.console_label.setText(f"Status: Configured Atlassian Site: {res['site_url']} | Project: {res.get('project_key') or 'KAN'}")
