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
    QScrollArea,
    QMessageBox,
    QComboBox,
    QCheckBox
)

from tech_connector.services.settings_service import load_settings, save_settings

DEFAULTS = {
    "semantic_intent_model": "qwen2.5:1.5b",
    "fast_general_model": "qwen3:14b",
    "fast_code_model": "qwen2.5-coder:14b",
    "embedding_model": "nomic-embed-text:latest",
    "fallback_general_model": "qwen2.5-coder:latest",
    "fallback_semantic_intent_model": "qwen2.5:1.5b",
    "fallback_code_model": "qwen2.5-coder:latest",
    "custom_model_mappings": {},
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
    "cloud_provider_model": "gpt-4o",
    "asset_optimizer_provider_module": "default",
    "use_websocket_bridge": False,
    "chatbot_provider_module": "default",
}


class CustomizationPanel(QDialog):
    """Vibrant, premium tabbed customization panel for Tech Connector."""

    def __init__(self, parent=None, active_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("System Customization Panel")
        self.resize(780, 650)
        self.setMinimumSize(600, 520)
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

        # Tab 3: Workflow Services
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
        self.model_intent.setToolTip("Ollama model class for semantic intent understanding (e.g. qwen2.5:1.5b)")
        form.addRow("Semantic/Intent Model:", self.model_intent)

        self.model_general = QLineEdit()
        self.model_general.setToolTip("Ollama model class for general reasoning/answers (e.g. qwen3:14b)")
        form.addRow("Fast General Model:", self.model_general)

        self.model_code = QLineEdit()
        self.model_code.setToolTip("Ollama model class for code generation & edit queries (e.g. qwen2.5-coder:14b)")
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
        self.custom_mappings.setToolTip("JSON dictionary to override specific role names to custom Ollama models")
        self.custom_mappings.setPlaceholderText('{\n  "custom_role": "model_name"\n}')
        self.custom_mappings.setMaximumHeight(100)
        form.addRow("Custom Role Mappings (JSON):", self.custom_mappings)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def setup_cloud_tab(self):
        layout = QVBoxLayout(self.tab_cloud)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setSpacing(10)

        # Cloud model selector
        self.cloud_provider_model = QLineEdit()
        self.cloud_provider_model.setToolTip("Cloud model name (e.g. gpt-4o, claude-3-5-sonnet, gemini-1.5-pro)")
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

        scroll.setWidget(content)
        layout.addWidget(scroll)

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
        self.services_form.addRow("GitHub Ingestion Type:", self.prov_ingest_type)

        # Custom module row
        self.prov_ingest = QLineEdit()
        self.prov_ingest.setToolTip("Python module path providing custom GitHub ingestion (e.g. custom_ingest)")
        self.services_form.addRow("Custom Ingestion Module:", self.prov_ingest)
        self.prov_ingest_label = self.services_form.labelForField(self.prov_ingest)

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
        self.asset_optimizer_module.setToolTip("Python module path providing custom post-extraction asset optimization (e.g. custom_optimize)")
        self.services_form.addRow("Asset Optimizer Module:", self.asset_optimizer_module)

        self.prov_intel = QLineEdit()
        self.prov_intel.setToolTip("Python module path providing custom code intelligence context (e.g. custom_intel)")
        self.services_form.addRow("Code Intelligence Module:", self.prov_intel)

        self.prov_router = QLineEdit()
        self.prov_router.setToolTip("Python module path providing custom prompt cognitive router (e.g. custom_router)")
        self.services_form.addRow("Cognitive Routing Module:", self.prov_router)

        self.prov_planner = QLineEdit()
        self.prov_planner.setToolTip("Python module path providing custom action planner (e.g. custom_planner)")
        self.services_form.addRow("Planning Engine Module:", self.prov_planner)

        self.prov_chatbot = QLineEdit()
        self.prov_chatbot.setToolTip("Python module path providing custom chatbot/reasoning provider (e.g. custom_chatbot)")
        self.services_form.addRow("Chatbot Provider Module:", self.prov_chatbot)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def toggle_ingest_fields(self):
        current_type = self.prov_ingest_type.currentData()
        
        # Hide custom module inputs by default
        self.prov_ingest.setVisible(current_type == "custom")
        if self.prov_ingest_label:
            self.prov_ingest_label.setVisible(current_type == "custom")

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

        self.prov_vcs = QLineEdit()
        self.prov_vcs.setToolTip("Python class path subclassing VersionControlProvider (e.g. my_vcs.MyVcsProvider)")
        form.addRow("VCS Provider Class:", self.prov_vcs)

        self.custom_dcc_packages = QLineEdit()
        self.custom_dcc_packages.setToolTip("Comma-separated list of custom DCC tool folder names inside TOOLS_ROOT")
        form.addRow("Custom DCC Package Names:", self.custom_dcc_packages)

        self.custom_dcc_adapters = QTextEdit()
        self.custom_dcc_adapters.setToolTip("JSON mapping of DCC names to custom execution adapter classes (e.g. {'unreal': 'my_mod.UnrealAdapter'})")
        self.custom_dcc_adapters.setPlaceholderText('{\n  "unreal": "my_module.MyAdapter"\n}')
        self.custom_dcc_adapters.setMaximumHeight(100)
        form.addRow("Custom DCC Adapters (JSON):", self.custom_dcc_adapters)

        self.custom_dcc_bridges = QTextEdit()
        self.custom_dcc_bridges.setToolTip("JSON mapping of DCC names to custom bridge delegates (e.g. {'unreal': 'my_ludus.LudusBridge'})")
        self.custom_dcc_bridges.setPlaceholderText('{\n  "unreal": "my_ludus.LudusBridge"\n}')
        self.custom_dcc_bridges.setMaximumHeight(100)
        form.addRow("Custom DCC Bridges (JSON):", self.custom_dcc_bridges)

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def load_values(self):
        settings = load_settings()

        self.model_intent.setText(str(settings.get("semantic_intent_model", DEFAULTS["semantic_intent_model"])))
        self.model_general.setText(str(settings.get("fast_general_model", DEFAULTS["fast_general_model"])))
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
        
        # Ingest validation depends on provider type
        ingest_type = self.prov_ingest_type.currentData()
        if ingest_type == "custom":
            mod_path = self.prov_ingest.text().strip()
            if mod_path and mod_path != "default":
                try:
                    importlib.import_module(mod_path)
                except ImportError as e:
                    errors.append(f"GitHub Ingest Module ({mod_path}): {e}")
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
            try:
                importlib.import_module(opt_path)
            except ImportError as e:
                errors.append(f"Asset Optimizer Module ({opt_path}): {e}")

        # Other services
        modules_to_test = {
            "Code Intel": self.prov_intel.text().strip(),
            "Router": self.prov_router.text().strip(),
            "Planner": self.prov_planner.text().strip(),
            "Chatbot": self.prov_chatbot.text().strip(),
        }

        for name, mod_path in modules_to_test.items():
            if mod_path and mod_path != "default":
                try:
                    importlib.import_module(mod_path)
                except ImportError as e:
                    errors.append(f"{name} Module ({mod_path}): {e}")

        # Check VCS provider class
        vcs_class_path = self.prov_vcs.text().strip()
        if vcs_class_path and vcs_class_path != "default":
            if "." in vcs_class_path:
                try:
                    mod_name, class_name = vcs_class_path.rsplit(".", 1)
                    mod = importlib.import_module(mod_name)
                    getattr(mod, class_name)
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
                                mod_name, class_name = class_path.rsplit(".", 1)
                                mod = importlib.import_module(mod_name)
                                getattr(mod, class_name)
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
                                mod_name, class_name = class_path.rsplit(".", 1)
                                mod = importlib.import_module(mod_name)
                                getattr(mod, class_name)
                            except Exception as e:
                                errors.append(f"DCC Bridge {dcc} ({class_path}): {e}")
                        else:
                            errors.append(f"DCC Bridge {dcc} ({class_path}): Class path must include module dot separation")
        except Exception:
            pass

        if errors:
            self.console_label.setStyleSheet("background-color: #3b0c0c; color: #ff5555; padding: 8px; border-radius: 4px; border: 1px solid #7a1f1f; font-family: monospace;")
            self.console_label.setText("Validation Failed:\n" + "\n".join(errors))
            QMessageBox.warning(self, "Validation Failed", f"Some custom module configurations failed to import:\n\n" + "\n".join(errors))
        else:
            self.console_label.setStyleSheet("background-color: #0c3b1e; color: #55ff55; padding: 8px; border-radius: 4px; border: 1px solid #1f7a3e; font-family: monospace;")
            self.console_label.setText("Status: Validation Succeeded. All modules are correctly resolvable!")
            QMessageBox.information(self, "Validation Succeeded", "All custom provider modules and class paths loaded and imported successfully!")
