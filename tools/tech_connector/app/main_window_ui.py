"""Extracted MainWindow methods. Generated from the uploaded monolithic file."""


import sys
from pathlib import Path

from tech_connector.path_bootstrap import ensure_tools_root_on_path

ensure_tools_root_on_path(__file__)

from PySide6.QtCore import QRect, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QPixmap,
    QTextCursor,
    QKeySequence,
    QShortcut,
)
from tech_connector.ui.pipeline_attribute_editor import PipelineAttributeEditor
from tech_connector.ui.pipeline_node_view import PipelineNodeView
from tech_connector.ui.growing_prompt_edit import GrowingPromptEdit
from tech_connector.ui.status_bar import format_status_card
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tech_connector.models.constants import (
    APP_DISPLAY_NAME,
    APP_SHORT_NAME,
    DEFAULT_CONFIGS,
    DEFAULT_MODEL,
    LOGO_PATH,
    PRIME_PROMPT,
    project_index_db_path,
)

from tech_connector.services.model_provider_service import (
    PROVIDER_ORDER,
    PROVIDERS,
    provider_for_model,
)
from tech_connector.services.ollama_service import (
    AI_MODELS,
    FALLBACK_CODE_MODEL,
    FALLBACK_GENERAL_MODEL,
    as_mcphost_model,
)

from tech_connector.services.settings_service import best_config
from tech_connector.services.native_project_build_service import source_location_from_output_line

from tech_connector.ui.chat_worker_dialogs import ChatLogBrowser
from tech_connector.ui.unreal_editor_dialogs import EditorDiffWidget
from tech_connector.ui.detachable_tabs import DetachableTabWidget
from tech_connector.ui.design_system import set_ui_role
from tech_connector.ui.icons import configure_button, icon
try:
    from tech_connector.editor.editor_widget import CodeEditor
except Exception:
    CodeEditor = None


class NavigableOutputEdit(QPlainTextEdit):
    """Output log that opens source locations embedded in diagnostic lines."""

    sourceLocationActivated = Signal(str, int, int)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        cursor = self.cursorForPosition(event.position().toPoint())
        location = source_location_from_output_line(cursor.block().text())
        if location is not None:
            self.sourceLocationActivated.emit(*location)




class MainWindowUiMixin:
    def toggle_project_setup_section(self):
        setup = getattr(self, "project_setup_widget", None)
        button = getattr(self, "project_setup_toggle_btn", None)
        if setup is None:
            return
        visible = setup.isHidden()
        setup.setVisible(visible)
        if button is not None:
            button.setText("Setup -" if visible else "Setup +")

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.top_section_widget = QWidget()
        self.top_section_widget.setObjectName("appHeader")
        top_layout = QVBoxLayout(self.top_section_widget)
        top_layout.setContentsMargins(6, 4, 6, 5)

        header = QHBoxLayout()
        if LOGO_PATH.exists():
            logo = QLabel()
            logo.setPixmap(
                QPixmap(str(LOGO_PATH)).scaled(
                    44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
            logo.setStyleSheet("margin-right: 6px; padding: 0;")
            header.addWidget(logo)

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel(APP_DISPLAY_NAME)
        set_ui_role(title, "title")
        title_col.addWidget(title)
        subtitle = QLabel(
            "Build, connect, and automate across DCCs and game engines"
        )
        set_ui_role(subtitle, "muted")
        title_col.addWidget(subtitle)
        header.addLayout(title_col)

        self.status = QLabel("Stopped")
        set_ui_role(self.status, "status")
        self.status.setProperty("statusState", "idle")
        self.status.setMinimumWidth(82)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setToolTip(f"Current {APP_SHORT_NAME} application state. Detailed routing, model, knowledge, DCC, and VCS status is shown in the bottom status panel.")

        self.menu_bar_controls_widget = QWidget()
        self.menu_bar_controls_widget.setObjectName("MenuBarControls")
        self.menu_bar_controls_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.menu_bar_controls_widget.setMaximumHeight(32)

        controls = QHBoxLayout(self.menu_bar_controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        source_label = QLabel("Source:")
        set_ui_role(source_label, "muted")
        source_label.setFixedWidth(56)
        source_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        controls.addWidget(source_label)
        self.model_source_mode_box = QComboBox()
        self.model_source_mode_box.addItem(
            "Cloud locked / local if unset", "auto_with_local_fallback"
        )
        self.model_source_mode_box.addItem("Always local", "local_only")
        source_mode = self.settings.get("model_source_mode", "auto_with_local_fallback")
        idx = self.model_source_mode_box.findData(source_mode)
        if idx >= 0:
            self.model_source_mode_box.setCurrentIndex(idx)
        self.model_source_mode_box.setToolTip(
            "Uses one configured cloud provider and model for the complete prompt run. "
            "If no cloud credential is configured when the run starts, it uses local Ollama."
        )
        self.model_source_mode_box.currentIndexChanged.connect(
            self.on_model_source_mode_changed
        )
        self.model_source_mode_box.setFixedWidth(180)
        controls.addWidget(self.model_source_mode_box)

        selected_model = self.settings.get("model", DEFAULT_MODEL)

        provider_label = QLabel("Provider:")
        set_ui_role(provider_label, "muted")
        provider_label.setFixedWidth(58)
        provider_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        controls.addWidget(provider_label)
        self.model_provider_box = QComboBox()
        for provider_id in PROVIDER_ORDER:
            self.model_provider_box.addItem(PROVIDERS[provider_id].display_name, provider_id)
        provider_index = self.model_provider_box.findData(
            provider_for_model(selected_model)
        )
        if provider_index >= 0:
            self.model_provider_box.setCurrentIndex(provider_index)
        self.model_provider_box.setToolTip(
            "Choose Local, OpenAI, X, Google, or Anthropic. "
            "The model list only shows models from this provider."
        )
        self.model_provider_box.setFixedWidth(112)
        controls.addWidget(self.model_provider_box)

        model_label = QLabel("Model:")
        set_ui_role(model_label, "muted")
        model_label.setFixedWidth(52)
        model_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        controls.addWidget(model_label)
        self.model_box = QComboBox()
        self.model_box.setEditable(False)

        self._seen_models = set()
        self._installed_ollama_models = []
        self._local_model_options = [
            ("Planning", as_mcphost_model(AI_MODELS["plan"])),
            ("Code 7B", as_mcphost_model(AI_MODELS["code"])),
            ("DCC", as_mcphost_model(AI_MODELS["dcc"])),
            ("Mechanical 3B", "ollama:qwen2.5-coder:3b"),
            ("Fallback Gen", as_mcphost_model(FALLBACK_GENERAL_MODEL)),
            ("Fallback Code", as_mcphost_model(FALLBACK_CODE_MODEL)),
            ("Default", DEFAULT_MODEL),
        ]
        self.refresh_model_options_for_provider(
            self.model_provider_box.currentData(),
            selected_model=selected_model,
        )

        # Dynamic Ollama Installed Models - Non-blocking
        self.dynamic_models_loaded.connect(self._on_dynamic_models_loaded)
        self.provider_models_loaded.connect(self._on_provider_models_loaded)
        import threading

        def load_models():
            try:
                from tech_connector.services.ollama_service import installed_ollama_models

                self.dynamic_models_loaded.emit(installed_ollama_models())
            except Exception:
                pass

        def start_model_discovery():
            threading.Thread(target=load_models, daemon=True).start()

        QTimer.singleShot(5500, start_model_discovery)

        for i in range(self.model_box.count()):
            if self.model_box.itemData(i) == selected_model:
                self.model_box.setCurrentIndex(i)
                break
        self.model_box.currentIndexChanged.connect(self.on_model_changed)
        self.model_provider_box.currentIndexChanged.connect(
            self.on_model_provider_changed
        )
        self.model_box.setMinimumWidth(260)
        self.model_box.setMaximumWidth(480)
        controls.addWidget(self.model_box, 1)
        controls.addStretch(1)
        controls.addWidget(self.status)

        settings_btn = QPushButton()
        configure_button(
            settings_btn,
            "settings",
            tooltip="Settings — models, safety, knowledge, integrations, and pipelines",
            role="quiet",
            icon_only=True,
        )
        settings_btn.clicked.connect(self.show_settings_dialog)
        controls.addWidget(settings_btn)
        header.addWidget(self.menu_bar_controls_widget, 1)
        top_layout.addLayout(header)

        self.show_reasoning_summary_checkbox = QCheckBox("Show reasoning summary")
        self.show_reasoning_summary_checkbox.setChecked(
            bool(self.settings.get("show_reasoning_summary", True))
        )
        self.show_reasoning_summary_checkbox.setToolTip(
            "Shows safe route/context summaries before answers. This does not expose hidden chain-of-thought."
        )
        self.show_reasoning_summary_checkbox.stateChanged.connect(
            self.on_show_reasoning_summary_changed
        )
        self.show_reasoning_summary_checkbox.setVisible(False)
        # Settings-only: kept alive for state/signal compatibility, hidden from the main toolbar.
        controls.addWidget(self.show_reasoning_summary_checkbox)


        self.active_model_label = QLabel("")
        self.active_model_label.setWordWrap(True)
        self.active_model_label.setStyleSheet(
            "color: #b9dcff; background-color: #000711; border: 1px solid #1e9bff; padding: 5px;"
        )
        # Moved to the bottom status panel so the header stays focused on branding, source, model, state, and settings.
        self.update_active_response_model_label()

        self.model_requirement_label = QLabel("")
        self.model_requirement_label.setWordWrap(True)
        self.update_model_requirement_label()

        self.use_fallback_models_checkbox = QCheckBox("Use fallback models")
        self.use_fallback_models_checkbox.setChecked(
            bool(self.settings.get("use_fallback_models", False))
        )
        self.use_fallback_models_checkbox.setToolTip(
            "Routes plan/docs and code/DCC to configured fallback models. "
            "Changing this restarts routed MCPHost sessions."
        )
        self.use_fallback_models_checkbox.stateChanged.connect(
            self.on_fallback_models_changed
        )
        self.mcphost_manager.set_use_fallback_models(
            self.use_fallback_models_checkbox.isChecked()
        )
        self.use_fallback_models_checkbox.setVisible(False)
        # Settings-only: routed model fallback is configured from Settings/AI menus.
        controls.addWidget(self.use_fallback_models_checkbox)

        self.live_sources_checkbox = QCheckBox("Web/GitHub")
        self.live_sources_checkbox.setChecked(
            bool(self.settings.get("enable_live_sources", False))
        )
        self.live_sources_checkbox.setToolTip(
            "When enabled, normal chat prompts may use live web/GitHub sources. "
            "When disabled, prompts stay local-only."
        )
        self.live_sources_checkbox.stateChanged.connect(self.on_live_sources_changed)
        self.live_sources_checkbox.setVisible(False)
        # Settings-only: live source policy is configured from Settings/AI menus.
        controls.addWidget(self.live_sources_checkbox)

        self.unreal_cpp_bridge_checkbox = QCheckBox("UE C++")
        self.unreal_cpp_bridge_checkbox.setChecked(self.unreal_cpp_bridge_enabled())
        self.unreal_cpp_bridge_checkbox.setToolTip(
            "Allow Unreal planning to recommend reflected C++ plugin bridge functions when Python/editor APIs are incomplete. "
            "Leave off for Blueprint-only projects."
        )
        self.unreal_cpp_bridge_checkbox.stateChanged.connect(
            self.on_unreal_cpp_bridge_changed
        )
        self.unreal_cpp_bridge_checkbox.setVisible(False)
        # Settings-only: Unreal C++ bridge is configured from Settings → Source & Runtime / DCC.
        controls.addWidget(self.unreal_cpp_bridge_checkbox)

        self.config_label = QLabel("Config:")
        self.config_label.setVisible(False)
        controls.addWidget(self.config_label)
        self.config_box = QComboBox()
        self.config_box.setEditable(True)
        self.config_box.setVisible(False)
        self.config_box.setToolTip("MCPHost config. Change this from Settings → Source & Runtime.")
        default_config = self.settings.get("config") or best_config()
        for c in [default_config] + DEFAULT_CONFIGS:
            if self.config_box.findText(c) < 0:
                self.config_box.addItem(c)
        # Settings-only: keep the widget for compatibility with settings/startup code, but do not show it in the main toolbar.
        controls.addWidget(self.config_box, 2)

        setup_btn = QPushButton("Project Dirs")
        setup_btn.setToolTip("Project directories. Also available in the left Project Tools panel and Project menu.")
        setup_btn.clicked.connect(self.show_first_run)
        setup_btn.setVisible(False)
        controls.addWidget(setup_btn)

        self.use_pty_checkbox = QCheckBox("Use PTY")
        self.use_pty_checkbox.setChecked(False)
        self.use_pty_checkbox.setToolTip(
            "Recommended ON for MCPHost. Pipe mode can run but may hide MCPHost's terminal UI output."
        )
        self.use_pty_checkbox.setVisible(False)
        # Advanced runtime setting. Configure through Tools/Settings.
        controls.addWidget(self.use_pty_checkbox)

        install_btn = QPushButton("Install Components")
        install_btn.setToolTip("Install/update local components. Also available in Tools → Tech Connector.")
        install_btn.clicked.connect(self.install_components)
        install_btn.setVisible(False)
        controls.addWidget(install_btn)

        index_btn = QPushButton("Quick Index")
        index_btn.setToolTip("Refresh only stale/new project files. Use a full rebuild only as a last-resort repair.")
        index_btn.setToolTip("Build the knowledge index. Also available in the left Project Tools panel and Knowledge menu.")
        index_btn.clicked.connect(self.build_index)
        index_btn.setVisible(False)
        controls.addWidget(index_btn)

        daemon_row = QHBoxLayout()
        self.daemon_toggle_btn = QPushButton("Start Unreal Indexer")
        self.daemon_toggle_btn.setToolTip("Start or stop Unreal Indexer. Use Tools → Connected Applications → Unreal Engine.")
        self.daemon_toggle_btn.clicked.connect(self.toggle_unreal_daemon)
        self.daemon_toggle_btn.setVisible(False)
        daemon_row.addWidget(self.daemon_toggle_btn, 1)

        self.daemon_scan_btn = QPushButton("Scan Project")
        self.daemon_scan_btn.setToolTip("Scan the Unreal project. Use Tools → Connected Applications → Unreal Engine.")
        self.daemon_scan_btn.clicked.connect(self.trigger_daemon_scan)
        self.daemon_scan_btn.setEnabled(False)
        self.daemon_scan_btn.setVisible(False)
        daemon_row.addWidget(self.daemon_scan_btn)

        self.unreal_docs_btn = QPushButton("Index Docs")
        self.unreal_docs_btn.clicked.connect(self.refresh_unreal_docs_cache)
        self.unreal_docs_btn.setEnabled(False)
        self.unreal_docs_btn.setVisible(False)
        self.unreal_docs_btn.setToolTip(
            "Cache Unreal Python API docs and build fast API symbol lookup. Use Tools → Connected Applications → Unreal Engine."
        )
        daemon_row.addWidget(self.unreal_docs_btn)
        controls.addLayout(daemon_row)

        status_cards = QHBoxLayout()
        status_cards.setContentsMargins(0, 0, 0, 0)
        status_cards.setSpacing(4)
        self.status_cards = {}
        for key, label in [
            ("ollama", "Ollama"),
            ("mcphost", "MCPHost"),
            ("knowledge", "Knowledge"),
            ("vcs", "VCS"),
            ("maya", "Maya"),
            ("unreal", "Unreal"),
            ("blender", "Blender"),
            ("houdini", "Houdini"),
            ("substance_painter", "Substance"),
            ("motionbuilder", "MotionBuilder"),
            ("unity", "Unity"),
            ("slack", "Slack"),
            ("discord", "Discord"),
            ("github", "GitHub"),
            ("git", "Git"),
            ("perforce", "Perforce"),
            ("gmail", "Gmail"),
            ("integrations", "Integrations"),
        ]:
            card_text, card_style = format_status_card(key, "unknown", "Not checked")
            card = QLabel(card_text)
            card.setTextFormat(Qt.RichText)
            card.setMinimumWidth(54)
            card.setMaximumWidth(118)
            card.setStyleSheet(card_style)
            card.setToolTip(label)
            status_cards.addWidget(card)
            self.status_cards[key] = card
        status_cards.addStretch(1)
        self.status_cards_scroll = QScrollArea()
        self.status_cards_scroll.setWidgetResizable(True)
        self.status_cards_scroll.setMaximumHeight(28)
        self.status_cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.status_cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.status_cards_scroll.setFrameShape(QFrame.NoFrame)
        self.status_cards_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:horizontal { background: #00040a; height: 8px; }"
            "QScrollBar::handle:horizontal { background: #1e9bff; border-radius: 4px; min-width: 24px; }"
        )
        self.status_cards_container = QWidget()
        self.status_cards_container.setLayout(status_cards)
        self.status_cards_scroll.setWidget(self.status_cards_container)
        # Moved to the bottom status panel.

        index_row = QHBoxLayout()
        index_row.setContentsMargins(0, 0, 0, 0)
        index_row.setSpacing(6)
        self.index_status = QLabel(
            "Index: " + ("ready" if project_index_db_path().exists() else "missing")
        )
        index_row.addWidget(self.index_status)
        self.index_progress = QProgressBar()
        self.index_progress.setRange(0, 1)
        self.index_progress.setValue(0)
        self.index_progress.setMaximumHeight(18)
        self.index_progress.setTextVisible(True)
        self.index_progress.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        index_row.addWidget(self.index_progress, 1)
        # Moved to the bottom status panel.

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        top_layout.addWidget(line)

        root.addWidget(self.top_section_widget)

        self.project_restore_btn = QPushButton("Project")
        self.project_restore_btn.setToolTip("Restore the hidden Project panel")
        self.project_restore_btn.setMaximumWidth(64)
        self.project_restore_btn.setMinimumWidth(54)
        configure_button(self.project_restore_btn, "panel_left", text="Project", role="quiet")
        self.project_restore_btn.clicked.connect(self.toggle_project_panel)
        self.project_restore_btn.setVisible(False)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(10)

        left = QWidget()
        left.setObjectName("projectSidebar")
        left.setMinimumWidth(220)
        left.setMaximumWidth(900)
        left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left)

        project_header = QHBoxLayout()
        project_title = QLabel("Project")
        set_ui_role(project_title, "sectionTitle")
        project_header.addWidget(project_title, 1)
        self.toggle_project_btn = QPushButton("Hide")
        configure_button(
            self.toggle_project_btn,
            "panel_left",
            text="Hide",
            tooltip="Hide the project sidebar",
            role="quiet",
        )
        self.toggle_project_btn.clicked.connect(self.toggle_project_panel)
        project_header.addWidget(self.toggle_project_btn)
        left_layout.addLayout(project_header)

        if LOGO_PATH.exists():
            sidebar_logo = QLabel()
            sidebar_logo.setObjectName("projectSidebarLogo")
            sidebar_logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            source_logo = QPixmap(str(LOGO_PATH))
            logo_crop = source_logo.copy(
                QRect(
                    70,
                    220,
                    max(1, source_logo.width() - 140),
                    min(590, max(1, source_logo.height() - 220)),
                )
            )
            sidebar_logo.setPixmap(
                logo_crop.scaled(
                    220,
                    72,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            sidebar_logo.setMinimumHeight(64)
            sidebar_logo.setMaximumHeight(78)
            sidebar_logo.setStyleSheet(
                "QLabel1projectSidebarLogo { "
                "background-color: #000102; "
                "border: 0px; "
                "padding: 6px 0px 4px 0px; "
                "}"
            )
            left_layout.addWidget(sidebar_logo)

        self.project_setup_widget = QWidget()
        project_setup_layout = QVBoxLayout(self.project_setup_widget)
        project_setup_layout.setContentsMargins(0, 0, 0, 0)
        project_setup_layout.setSpacing(6)

        self.project_root_label = QLabel("No active project")
        self.project_root_label.setStyleSheet("color: #bdbdbd;")
        self.project_root_label.setWordWrap(True)
        project_setup_layout.addWidget(self.project_root_label)

        self.project_directories_label = QLabel("Game: TCGame  |  Art: ArtSource")
        self.project_directories_label.setStyleSheet("color: #7f9bb3; font-size: 10px;")
        self.project_directories_label.setWordWrap(True)
        project_setup_layout.addWidget(self.project_directories_label)

        project_actions = QHBoxLayout()
        load_project_btn = QPushButton("Load Project")
        load_project_btn.clicked.connect(self.load_project)
        project_actions.addWidget(load_project_btn)
        update_project_btn = QPushButton("Update Project")
        update_project_btn.clicked.connect(self.refresh_project_tree_fast)
        project_actions.addWidget(update_project_btn)
        project_setup_layout.addLayout(project_actions)

        self.recent_project_box = QComboBox()
        self.recent_project_box.setToolTip("Recent projects")
        self.recent_project_box.activated.connect(self.load_recent_project)
        project_setup_layout.addWidget(self.recent_project_box)
        self.update_project_header()
        self.refresh_recent_projects()

        left_layout.addWidget(self.project_setup_widget)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("projectSidebarScroll")
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setStyleSheet(
            "QScrollArea1projectSidebarScroll { background: transparent; border: 0px; }"
        )
        sidebar_body = QWidget()
        sidebar_body_layout = QVBoxLayout(sidebar_body)
        sidebar_body_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_body_layout.setSpacing(6)
        sidebar_scroll.setWidget(sidebar_body)
        left_layout.addWidget(sidebar_scroll, 1)

        self.project_filter = QLineEdit()
        self.project_filter.setPlaceholderText("Filter project tree...")
        self.project_filter_timer = QTimer(self)
        self.project_filter_timer.setSingleShot(True)
        self.project_filter_timer.setInterval(120)
        self.project_filter_timer.timeout.connect(
            lambda: self.filter_project_tree(self.project_filter.text())
        )
        self.project_filter.textChanged.connect(lambda *_args: self.schedule_project_tree_filter())
        sidebar_body_layout.addWidget(self.project_filter)

        self.recent_file_box = QComboBox()
        self.recent_file_box.setToolTip("Recent files")
        self.recent_file_box.activated.connect(self.open_recent_file_from_dropdown)
        sidebar_body_layout.addWidget(self.recent_file_box)

        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderLabels(["File", "Path"])
        self.project_tree.setHeaderHidden(True)
        self.project_tree.setColumnHidden(1, True)
        self.project_tree.itemDoubleClicked.connect(self.open_tree_file)
        self.project_tree.itemExpanded.connect(self.on_project_tree_expanded)
        self.project_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_tree.customContextMenuRequested.connect(
            self.show_project_tree_context_menu
        )
        self.project_tree.currentItemChanged.connect(
            self.on_project_tree_selection_changed
        )

        self.project_path_edit = QLineEdit()
        self.project_path_edit.setPlaceholderText("Selected file path...")
        self.project_path_edit.setStyleSheet(
            "QLineEdit { background: #0b0f14; border: 1px solid #1e9bff; color: #d7dde5; }"
        )
        self.project_path_edit.returnPressed.connect(self.on_project_path_submitted)
        sidebar_body_layout.addWidget(self.project_path_edit)
        self.project_tree.setMinimumHeight(300)
        self.project_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sidebar_body_layout.addWidget(self.project_tree)

        sidebar_body_layout.addWidget(QLabel("Chat History"))
        self.history = QListWidget()
        self.history.itemClicked.connect(self.load_history_item)
        self.history.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history.customContextMenuRequested.connect(self.show_history_context_menu)
        self.history.setMinimumHeight(150)
        self.history.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sidebar_body_layout.addWidget(self.history)

        hrow = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_history)
        hrow.addWidget(save_btn)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.new_chat)
        hrow.addWidget(new_btn)
        sidebar_body_layout.addLayout(hrow)

        sidebar_body_layout.addWidget(QLabel("Code Snippets"))
        self.code_list = QListWidget()
        self.code_list.itemDoubleClicked.connect(self.open_selected_snippet_in_editor)
        self.code_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.code_list.customContextMenuRequested.connect(
            self.show_snippets_context_menu
        )
        self.code_list.setMinimumHeight(240)
        self.code_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sidebar_body_layout.addWidget(self.code_list)
        open_snippet_btn = QPushButton("Open in Editor")
        open_snippet_btn.clicked.connect(self.open_selected_snippet_in_editor)
        sidebar_body_layout.addWidget(open_snippet_btn)

        self.left_panel = left
        self.main_splitter.addWidget(left)

        main = QWidget()
        main.setMinimumWidth(600)
        main.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout = QVBoxLayout(main)

        self.workspace_tabs = DetachableTabWidget(self, tab_type="feature")
        self.workspace_tabs.set_tab_close_handler(self.close_workspace_tab)
        self.workspace_tabs.setTabsClosable(True)
        self.main_fullscreen_btn = QPushButton("Full Screen")
        configure_button(self.main_fullscreen_btn, "maximize", text="Focus", role="quiet")
        self.main_fullscreen_btn.setCheckable(True)
        self.main_fullscreen_btn.setToolTip("Focus the current tab by hiding surrounding panels. Detached tabs use real fullscreen.")
        self.main_fullscreen_btn.clicked.connect(self.toggle_main_window_fullscreen)
        self.workspace_tabs.setCornerWidget(self.project_restore_btn, Qt.TopLeftCorner)
        self.workspace_tabs.setCornerWidget(self.main_fullscreen_btn, Qt.TopRightCorner)
        self.workspace_tabs.currentChanged.connect(self.on_workspace_tab_changed)
        self.workspace_tabs.tabActivated.connect(self.on_workspace_tab_activated)
        self.workspace_tabs.tabVisibilityChanged.connect(lambda *_args: self.schedule_unified_prompt_context_label_update())
        self.workspace_tabs.tabDetachedChanged.connect(lambda *_args: self.schedule_unified_prompt_context_label_update())
        self.workspace_tabs.currentChanged.connect(lambda *_args: self.schedule_window_state_save())
        self.workspace_tabs.tabVisibilityChanged.connect(lambda *_args: self.schedule_window_state_save())
        self.workspace_tabs.tabDetachedChanged.connect(lambda *_args: self.schedule_window_state_save())
        self.workspace_tabs.containerEmptied.connect(lambda _container: self._update_workspace_anchor_visibility())

        self.workspace_anchor_tabs = DetachableTabWidget(
            self,
            tab_type="feature",
            root_container=self.workspace_tabs,
        )
        self.workspace_anchor_tabs.set_tab_close_handler(self.close_workspace_tab)
        self.workspace_anchor_tabs.setTabsClosable(True)
        self.workspace_anchor_tabs.setToolTip("Anchored feature tabs. Drag compatible feature tabs here or use Window > Anchor Current Tab Right.")
        self.workspace_anchor_tabs.tabActivated.connect(self.on_workspace_tab_activated)
        self.workspace_anchor_tabs.tabActivated.connect(lambda *_args: self.schedule_window_state_save())
        self.workspace_anchor_tabs.tabVisibilityChanged.connect(lambda *_args: self.schedule_window_state_save())
        self.workspace_anchor_tabs.tabDetachedChanged.connect(lambda *_args: self.schedule_window_state_save())
        self.workspace_anchor_tabs.containerEmptied.connect(lambda _container: self._update_workspace_anchor_visibility())
        self.workspace_anchor_close_btn = QPushButton("Close")
        self.workspace_anchor_close_btn.setToolTip("Move anchored tabs back to the main feature tab container")
        self.workspace_anchor_close_btn.setMaximumWidth(58)
        configure_button(self.workspace_anchor_close_btn, "close", text="Close", role="quiet")
        self.workspace_anchor_close_btn.clicked.connect(self.close_workspace_anchor)
        self.workspace_anchor_tabs.setCornerWidget(self.workspace_anchor_close_btn, Qt.TopRightCorner)
        self.workspace_anchor_tabs.setVisible(False)

        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)

        chat_top = QHBoxLayout()
        chat_title = QLabel("Conversation Log")
        set_ui_role(chat_title, "sectionTitle")
        chat_top.addWidget(chat_title, 1)

        self.chat_prev_response_btn = QPushButton("Up")
        self.chat_prev_response_btn.setToolTip("Jump to the previous assistant response")
        configure_button(self.chat_prev_response_btn, "chevron_up", text="Previous", role="quiet")
        self.chat_prev_response_btn.clicked.connect(lambda: self.navigate_chat_response(-1))
        chat_top.addWidget(self.chat_prev_response_btn)

        self.chat_next_response_btn = QPushButton("Down")
        self.chat_next_response_btn.setToolTip("Jump to the next assistant response")
        configure_button(self.chat_next_response_btn, "chevron_down", text="Next", role="quiet")
        self.chat_next_response_btn.clicked.connect(lambda: self.navigate_chat_response(1))
        chat_top.addWidget(self.chat_next_response_btn)

        self.copy_response_header_btn = QPushButton("Copy Response")
        self.copy_response_header_btn.setToolTip("Copy the currently selected assistant response")
        configure_button(self.copy_response_header_btn, "copy", text="Copy response", role="quiet")
        self.copy_response_header_btn.clicked.connect(self.copy_current_chat_response)
        chat_top.addWidget(self.copy_response_header_btn)

        self.copy_thread_header_btn = QPushButton("Copy Thread")
        configure_button(self.copy_thread_header_btn, "copy", text="Copy thread", role="quiet")
        self.copy_thread_header_btn.clicked.connect(self.copy_full_log)
        chat_top.addWidget(self.copy_thread_header_btn)

        self.full_thread_header_btn = QPushButton("Full Thread")
        self.full_thread_header_btn.setToolTip(
            "View the complete canonical conversation, including messages outside the recent render window"
        )
        configure_button(self.full_thread_header_btn, "maximize", text="Full thread", role="quiet")
        self.full_thread_header_btn.clicked.connect(self.show_full_thread)
        chat_top.addWidget(self.full_thread_header_btn)

        self.undo_header_btn = QPushButton("Undo Last Change")
        configure_button(self.undo_header_btn, "undo", text="Undo change", role="danger")
        self.undo_header_btn.clicked.connect(self.undo_last_applied_changes)
        chat_top.addWidget(self.undo_header_btn)

        self.export_pdf_btn = QPushButton("Export PDF")
        configure_button(self.export_pdf_btn, "export", text="Export PDF", role="quiet")
        self.export_pdf_btn.clicked.connect(self.export_log_to_pdf)
        chat_top.addWidget(self.export_pdf_btn)

        # Keep the conversation toolbar task-focused. Less common thread
        # operations remain available from a single, labeled overflow menu.
        for secondary_action in (
            self.copy_thread_header_btn,
            self.full_thread_header_btn,
            self.undo_header_btn,
            self.export_pdf_btn,
        ):
            secondary_action.setVisible(False)
        self.chat_more_btn = QToolButton()
        configure_button(
            self.chat_more_btn,
            "more_horizontal",
            text="More",
            tooltip="More conversation actions",
            role="quiet",
        )
        self.chat_more_btn.setPopupMode(QToolButton.InstantPopup)
        chat_more_menu = QMenu(self.chat_more_btn)
        for label, icon_name, callback in (
            ("Copy thread", "copy", self.copy_full_log),
            ("View full thread", "maximize", self.show_full_thread),
            ("Undo last change", "undo", self.undo_last_applied_changes),
            ("Export PDF", "export", self.export_log_to_pdf),
        ):
            action = chat_more_menu.addAction(icon(icon_name), label)
            action.triggered.connect(
                lambda _checked=False, fn=callback: fn()
            )
        self.chat_more_btn.setMenu(chat_more_menu)
        chat_top.addWidget(self.chat_more_btn)

        self.simple_response_checkbox = QCheckBox("Simple")
        self.simple_response_checkbox.setChecked(
            bool(self.settings.get("simple_chat_responses", False))
        )
        self.simple_response_checkbox.setToolTip(
            "Use shorter chat reports. Leave off for richer Codex-style feedback."
        )
        self.simple_response_checkbox.stateChanged.connect(
            self.on_simple_chat_responses_changed
        )
        chat_top.addWidget(self.simple_response_checkbox)

        self.chat_fullscreen_btn = QPushButton("Full Screen")
        self.chat_fullscreen_btn.setCheckable(True)
        self.chat_fullscreen_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.chat_fullscreen_btn.clicked.connect(self.toggle_fullscreen_mode)
        self.chat_fullscreen_btn.setVisible(False)
        self.copy_thread_header_btn.setText("Copy Thread")
        self.undo_header_btn.setText("Undo Last Change")
        self.export_pdf_btn.setText("Export PDF")
        self.chat_fullscreen_btn.setText("Full Screen")
        chat_layout.addLayout(chat_top)

        self.log = ChatLogBrowser()
        self.log.setOpenLinks(False)
        self.log.anchorClicked.connect(self.handle_log_anchor_clicked)
        self.log.setFont(QFont("Segoe UI", 10))
        self.log.setStyleSheet(
            "QTextBrowser { background: #00040a; border: 1px solid #12324a; "
            "border-radius: 8px; padding: 0px; color: #d7dde5; }"
            "QScrollBar:vertical { background: #00040a; width: 12px; }"
            "QScrollBar::handle:vertical { background: #243041; border-radius: 5px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )
        chat_layout.addWidget(self.log, 1)
        self.workspace_tabs.addTab(chat_tab, "Chat")

        code_tab = QWidget()
        code_layout = QVBoxLayout(code_tab)
        code_layout.setContentsMargins(0, 0, 0, 0)

        self.normal_editor_widget = QWidget()
        normal_layout = QVBoxLayout(self.normal_editor_widget)
        normal_layout.setContentsMargins(0, 0, 0, 0)



        editor_tools = QHBoxLayout()
        editor_tools.setSpacing(6)
        file_top = QHBoxLayout()
        self.file_path_label = QLabel("No file open")
        file_top.addWidget(self.file_path_label, 1)
        editor_tools.addLayout(file_top)
        self.editor_find = QLineEdit()
        self.editor_find.setPlaceholderText("Find in file...")
        self.editor_find.setMinimumWidth(260)
        self.editor_find.returnPressed.connect(self.find_in_current_file)
        editor_tools.addWidget(self.editor_find, 1)

        self.find_file_btn = QPushButton("Find")
        configure_button(self.find_file_btn, "search", text="Find", role="secondary")
        self.find_file_btn.clicked.connect(self.find_in_current_file)
        editor_tools.addWidget(self.find_file_btn)

        self.editor_find_prev_btn = QPushButton("↑")
        self.editor_find_prev_btn.setToolTip("Previous match in file")
        configure_button(
            self.editor_find_prev_btn,
            "chevron_up",
            tooltip="Previous match in file",
            role="quiet",
            icon_only=True,
        )
        self.editor_find_prev_btn.clicked.connect(self.find_previous_in_current_file)
        editor_tools.addWidget(self.editor_find_prev_btn)

        self.editor_find_next_btn = QPushButton("↓")
        self.editor_find_next_btn.setToolTip("Next match in file")
        configure_button(
            self.editor_find_next_btn,
            "chevron_down",
            tooltip="Next match in file",
            role="quiet",
            icon_only=True,
        )
        self.editor_find_next_btn.clicked.connect(self.find_next_in_current_file)
        editor_tools.addWidget(self.editor_find_next_btn)

        self.goto_line_box = QLineEdit()
        self.goto_line_box.setPlaceholderText("Line")
        self.goto_line_box.setMaximumWidth(70)
        self.goto_line_box.returnPressed.connect(self.goto_line_from_box)
        editor_tools.addWidget(self.goto_line_box)

        self.goto_line_btn = QPushButton("Go")
        configure_button(self.goto_line_btn, "arrow_right", text="Go", role="secondary")
        self.goto_line_btn.clicked.connect(self.goto_line_from_box)
        editor_tools.addWidget(self.goto_line_btn)

        editor_tools.addStretch(1)

        self.go_to_file_button = QPushButton("File location")
        configure_button(self.go_to_file_button, "folder", text="File location", role="quiet")
        self.go_to_file_button.clicked.connect(
            lambda checked=False: self.open_file_location(
                getattr(self, "current_file_path", "")
            )
        )
        editor_tools.addWidget(self.go_to_file_button)

        self.save_file_btn = QPushButton("Save File")
        configure_button(self.save_file_btn, "save", text="Save", role="primary")
        self.save_file_btn.clicked.connect(self.save_code_file)
        editor_tools.addWidget(self.save_file_btn)

        self.editor_analyze_btn = QPushButton("Analyze")
        configure_button(self.editor_analyze_btn, "search", text="Analyze", role="secondary")
        self.editor_analyze_btn.setToolTip("Inspect Python source or build the current CMake project for compiler diagnostics")
        self.editor_analyze_btn.clicked.connect(self.analyze_current_editor_file)
        editor_tools.addWidget(self.editor_analyze_btn)

        self.editor_reformat_btn = QPushButton("Reformat")
        configure_button(self.editor_reformat_btn, "format", text="Format", role="secondary")
        self.editor_reformat_btn.setToolTip("Reformat Python with Black or C/C++ with clang-format")
        self.editor_reformat_btn.clicked.connect(self.reformat_current_editor_file)
        editor_tools.addWidget(self.editor_reformat_btn)

        self.editor_fix_btn = QPushButton("Fix Issues")
        configure_button(self.editor_fix_btn, "wrench", text="Fix issues", role="secondary")
        self.editor_fix_btn.setToolTip("Apply safe automated code-quality fixes. Uses Ruff when available, then formatting cleanup.")
        self.editor_fix_btn.clicked.connect(self.fix_current_editor_quality_issues)
        editor_tools.addWidget(self.editor_fix_btn)

        self.editor_build_configuration = QComboBox()
        self.editor_build_configuration.addItems(["Debug", "Release", "RelWithDebInfo"])
        self.editor_build_configuration.setToolTip("CMake build configuration")
        editor_tools.addWidget(self.editor_build_configuration)

        self.editor_build_btn = QToolButton()
        configure_button(self.editor_build_btn, "package", text="Build", role="secondary")
        self.editor_build_btn.setPopupMode(QToolButton.MenuButtonPopup)
        self.editor_build_btn.setToolTip("Build the native project containing the current file")
        self.editor_build_btn.clicked.connect(self.build_current_native_project)
        self.editor_build_menu = QMenu(self.editor_build_btn)
        build_action = self.editor_build_menu.addAction("Build")
        build_action.triggered.connect(lambda checked=False: self.build_current_native_project("build"))
        test_action = self.editor_build_menu.addAction("Build and Test")
        test_action.triggered.connect(lambda checked=False: self.build_current_native_project("build_test"))
        analyze_action = self.editor_build_menu.addAction("Analyze Current File")
        analyze_action.triggered.connect(lambda checked=False: self.build_current_native_project("analyze"))
        rebuild_action = self.editor_build_menu.addAction("Rebuild")
        rebuild_action.triggered.connect(lambda checked=False: self.build_current_native_project("rebuild"))
        clean_action = self.editor_build_menu.addAction("Clean")
        clean_action.triggered.connect(lambda checked=False: self.build_current_native_project("clean"))
        self.editor_build_btn.setMenu(self.editor_build_menu)
        editor_tools.addWidget(self.editor_build_btn)

        self.editor_fullscreen_btn = QPushButton("Full Screen")
        self.editor_fullscreen_btn.setVisible(False)

        self.dup_line_btn = QPushButton("Duplicate Line")
        self.dup_line_btn.clicked.connect(self.duplicate_current_line)
        self.dup_line_btn.setVisible(False)

        self.comment_btn = QPushButton("Comment")
        self.comment_btn.clicked.connect(self.comment_selection_python_style)
        editor_tools.addWidget(self.comment_btn)

        self.trim_spaces_btn = QPushButton("Trim Spaces")
        self.trim_spaces_btn.clicked.connect(self.trim_trailing_spaces)
        self.trim_spaces_btn.setVisible(False)

        normal_layout.addLayout(editor_tools)

        editor_splitter = QSplitter(Qt.Horizontal)
        structure_panel = QWidget()
        structure_layout = QVBoxLayout(structure_panel)
        structure_layout.setContentsMargins(0, 0, 0, 0)
        structure_layout.setSpacing(3)
        structure_row = QHBoxLayout()
        structure_row.addWidget(QLabel("Structure"), 1)
        self.editor_structure_order_box = QComboBox()
        self.editor_structure_order_box.addItems(["Natural", "A-Z"])
        self.editor_structure_order_box.setCurrentText("A-Z" if self.settings.get("editor_structure_sort", "az") == "az" else "Natural")
        self.editor_structure_order_box.setToolTip("Structure order")
        self.editor_structure_order_box.currentTextChanged.connect(self.on_editor_structure_order_changed)
        structure_row.addWidget(self.editor_structure_order_box)
        structure_layout.addLayout(structure_row)
        self.editor_structure_tree = QTreeWidget()
        self.editor_structure_tree.setHeaderHidden(True)
        self.editor_structure_tree.setMinimumWidth(150)
        self.editor_structure_tree.setMaximumWidth(280)
        self.editor_structure_tree.setIndentation(14)
        self.editor_structure_tree.setSortingEnabled(False)
        self.editor_structure_tree.setUniformRowHeights(True)
        self.editor_structure_tree.setToolTip("Current file structure. Click a symbol to jump to it.")
        self.editor_structure_tree.itemActivated.connect(self.jump_to_editor_structure_item)
        self.editor_structure_tree.itemClicked.connect(self.jump_to_editor_structure_item)
        structure_layout.addWidget(self.editor_structure_tree, 1)
        editor_splitter.addWidget(structure_panel)

        self.editor_tabs = DetachableTabWidget(self, tab_type="editor_file")
        self.editor_tabs.setTabsClosable(True)
        self.editor_tabs.set_detached_panel_factory(self.build_detached_editor_structure_panel)
        self.editor_tabs.set_tab_close_handler(self.close_editor_tab_from_container)
        self.editor_tabs.currentChanged.connect(self.on_editor_tab_changed)
        self.editor_tabs.tabActivated.connect(self.on_editor_tab_activated_from_container)
        editor_splitter.addWidget(self.editor_tabs)
        editor_splitter.setStretchFactor(0, 0)
        editor_splitter.setStretchFactor(1, 1)
        editor_splitter.setSizes([190, 900])
        normal_layout.addWidget(editor_splitter, 1)

        self.editor_structure_timer = QTimer(self)
        self.editor_structure_timer.setSingleShot(True)
        self.editor_structure_timer.timeout.connect(self.refresh_editor_structure)

        editor_status_row = QHBoxLayout()
        editor_status_row.setContentsMargins(0, 0, 0, 0)
        self.editor_status_label = QLabel("Line 1, Col 1")
        editor_status_row.addWidget(self.editor_status_label, 1)
        self.editor_problems_toggle = QPushButton("Warnings")
        self.editor_problems_toggle.setCheckable(True)
        self.editor_problems_toggle.setChecked(bool(self.settings.get("editor_problems_visible", False)))
        self.editor_problems_toggle.setToolTip("Show source diagnostics and style warnings")
        self.editor_problems_toggle.setMaximumWidth(88)
        self.editor_problems_toggle.toggled.connect(self.set_editor_problems_visible)
        editor_status_row.addWidget(self.editor_problems_toggle)
        self.engine_console_toggle = QPushButton("Engine Console")
        self.engine_console_toggle.setCheckable(True)
        self.engine_console_toggle.setChecked(bool(self.settings.get("engine_console_visible", False)))
        self.engine_console_toggle.setToolTip("Show the explicit Python and TC command console")
        self.engine_console_toggle.toggled.connect(self.set_engine_console_visible)
        editor_status_row.addWidget(self.engine_console_toggle)
        normal_layout.addLayout(editor_status_row)

        self.editor_problems_list = QListWidget()
        self.editor_problems_list.setMaximumHeight(96)
        self.editor_problems_list.setAlternatingRowColors(True)
        self.editor_problems_list.setMouseTracking(True)
        self.editor_problems_list.viewport().setMouseTracking(True)
        self.editor_problems_list.setToolTip("Source and build diagnostics. Hover a row to preview its line; double-click to focus it.")
        self.editor_problems_list.itemEntered.connect(self.preview_editor_problem_item)
        self.editor_problems_list.itemDoubleClicked.connect(self.jump_to_editor_problem_item)
        self.editor_problems_list.setVisible(False)
        normal_layout.addWidget(self.editor_problems_list)

        self.engine_console_panel = QWidget()
        engine_console_layout = QVBoxLayout(self.engine_console_panel)
        engine_console_layout.setContentsMargins(0, 2, 0, 0)
        engine_console_layout.setSpacing(3)
        engine_console_tools = QHBoxLayout()
        self.engine_console_mode = QComboBox()
        self.engine_console_mode.addItems(["Python", "TC Command"])
        self.engine_console_mode.setToolTip("Python runs in a persistent engine namespace; TC Command executes adaptive command JSON")
        self.engine_console_mode.currentTextChanged.connect(self.on_engine_console_mode_changed)
        engine_console_tools.addWidget(self.engine_console_mode)
        self.engine_console_target = QLabel("Target: active TC scene")
        engine_console_tools.addWidget(self.engine_console_target, 1)
        self.engine_play_btn = QPushButton("Play")
        self.engine_play_btn.setToolTip("Run a .tcscene in the standalone TC runtime")
        self.engine_play_btn.clicked.connect(self.play_tc_scene)
        engine_console_tools.addWidget(self.engine_play_btn)
        self.engine_stop_btn = QPushButton("Stop")
        self.engine_stop_btn.setToolTip("Stop the active TC Play In Editor runtime")
        self.engine_stop_btn.setEnabled(False)
        self.engine_stop_btn.clicked.connect(self.stop_tc_play_in_editor)
        engine_console_tools.addWidget(self.engine_stop_btn)
        self.engine_build_player_btn = QPushButton("Build Player")
        self.engine_build_player_btn.setToolTip("Create a self-contained Windows player from a .tcscene")
        self.engine_build_player_btn.clicked.connect(self.build_tc_windows_player)
        engine_console_tools.addWidget(self.engine_build_player_btn)
        self.engine_console_run_btn = QPushButton("Run")
        self.engine_console_run_btn.setToolTip("Execute console input (Ctrl+Enter)")
        self.engine_console_run_btn.clicked.connect(self.execute_engine_console)
        engine_console_tools.addWidget(self.engine_console_run_btn)
        self.engine_console_reset_btn = QPushButton("Reset")
        self.engine_console_reset_btn.setToolTip("Reset the persistent Python namespace and clear output")
        self.engine_console_reset_btn.clicked.connect(self.reset_engine_console)
        engine_console_tools.addWidget(self.engine_console_reset_btn)
        engine_console_layout.addLayout(engine_console_tools)
        engine_console_splitter = QSplitter(Qt.Vertical)
        self.engine_console_input = CodeEditor()
        self.engine_console_input.setPlaceholderText("engine.create_game_experience('orbit_lab', ['realistic_simulation', 'educational'])")
        self.engine_console_input.setMinimumHeight(72)
        self.engine_console_output = NavigableOutputEdit()
        self.engine_console_output.setReadOnly(True)
        self.engine_console_output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.engine_console_output.setPlaceholderText("Execution output")
        self.engine_console_output.setMinimumHeight(54)
        self.engine_console_output.setToolTip("Build and runtime output. Click a diagnostic line to open its source location.")
        self.engine_console_output.sourceLocationActivated.connect(self.open_output_source_location)
        engine_console_splitter.addWidget(self.engine_console_input)
        engine_console_splitter.addWidget(self.engine_console_output)
        engine_console_splitter.setSizes([100, 80])
        engine_console_layout.addWidget(engine_console_splitter)
        self.engine_console_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.engine_console_input)
        self.engine_console_shortcut.activated.connect(self.execute_engine_console)
        self.engine_console_panel.setVisible(self.engine_console_toggle.isChecked())
        normal_layout.addWidget(self.engine_console_panel)

        # The old editor-specific prompt row has been collapsed into the single
        # global Ask line at the bottom of the window. These widgets remain as
        # hidden/backward-compatible action targets so existing editor pipeline
        # methods can still read self.editor_prompt and temporarily disable
        # self.ask_file_btn while a request is running.
        self.editor_prompt = QLineEdit()
        self.editor_prompt.setVisible(False)
        self.editor_prompt.returnPressed.connect(self.ask_about_current_file)

        self.ask_file_btn = QPushButton("Ask About File")
        self.ask_file_btn.setVisible(False)
        self.ask_file_btn.clicked.connect(self.ask_about_current_file)

        self.add_editor_answer_workflow_btn = QToolButton()
        self.add_editor_answer_workflow_btn.setText("Save Answer as Pipeline")
        self.add_editor_answer_workflow_btn.setPopupMode(QToolButton.InstantPopup)
        self.add_editor_answer_workflow_btn.setEnabled(False)
        self.add_editor_answer_workflow_btn.setVisible(False)
        self.add_editor_answer_workflow_menu = QMenu(self.add_editor_answer_workflow_btn)
        self.add_editor_answer_workflow_menu.aboutToShow.connect(
            self.refresh_editor_answer_workflow_menu
        )
        self.add_editor_answer_workflow_btn.setMenu(self.add_editor_answer_workflow_menu)

        code_layout.addWidget(self.normal_editor_widget, 1)

        # Inline side-by-side diff comparison widget
        self.editor_diff_widget = EditorDiffWidget(self)
        self.editor_diff_widget.setVisible(False)
        self.editor_diff_widget.accepted_all.connect(self.handle_diff_accepted)
        self.editor_diff_widget.cancelled.connect(self.handle_diff_cancelled)
        self.editor_diff_widget.repair_requested.connect(
            self.handle_editor_diff_repair_requested
        )
        code_layout.addWidget(self.editor_diff_widget, 1)

        self.workspace_tabs.addTab(code_tab, "Editor")

        search_tab = QWidget()
        search_layout = QVBoxLayout(search_tab)
        search_row = QHBoxLayout()
        self.project_search = QLineEdit()
        self.project_search.setPlaceholderText("Find in project...")
        self.project_search.returnPressed.connect(self.find_in_project)
        search_row.addWidget(self.project_search, 1)
        search_btn = QPushButton("Find")
        configure_button(search_btn, "search", text="Find project", role="primary")
        search_btn.clicked.connect(self.find_in_project)
        search_row.addWidget(search_btn)

        self.search_fullscreen_btn = QPushButton("Full Screen")
        self.search_fullscreen_btn.setCheckable(True)
        self.search_fullscreen_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.search_fullscreen_btn.clicked.connect(self.toggle_fullscreen_mode)
        self.search_fullscreen_btn.setVisible(False)
        search_layout.addLayout(search_row)

        self.search_results = QListWidget()
        self.search_results.itemDoubleClicked.connect(self.open_search_result)
        search_layout.addWidget(self.search_results, 1)

        symbol_row = QHBoxLayout()
        self.symbol_query = QLineEdit()
        self.symbol_query.setPlaceholderText("Symbol / function / call name...")
        symbol_row.addWidget(self.symbol_query, 1)
        self.symbol_domain = QComboBox()
        self.symbol_domain.addItems(
            [
                "all",
                "maya_tools",
                "maya",
                "unreal_tools",
                "unreal",
                "blender_tools",
                "blender",
                "mobu_tools",
                "motionbuilder",
                "project",
                "depot",
            ]
        )
        symbol_row.addWidget(self.symbol_domain)
        sym_btn = QPushButton("Symbols")
        sym_btn.clicked.connect(self.run_symbol_search_from_ui)
        symbol_row.addWidget(sym_btn)
        callers_btn = QPushButton("Callers")
        callers_btn.clicked.connect(self.run_callers_search_from_ui)
        symbol_row.addWidget(callers_btn)
        impl_btn = QPushButton("Implementation")
        impl_btn.clicked.connect(self.run_implementation_lookup_from_ui)
        symbol_row.addWidget(impl_btn)
        search_layout.addLayout(symbol_row)
        self.workspace_tabs.addTab(search_tab, "Search / Symbols")

        # Pipelines Tab
        workflows_tab = QWidget()
        workflows_layout = QVBoxLayout(workflows_tab)
        workflows_layout.setContentsMargins(4, 4, 4, 4)
        workflows_layout.setSpacing(4)

        pipelines_top = QHBoxLayout()
        pipelines_title = QLabel("Pipelines")
        pipelines_title.setStyleSheet("font-weight: bold; color: #b9dcff;")
        pipelines_top.addWidget(pipelines_title, 1)
        self.pipelines_fullscreen_btn = QPushButton("Full Screen")
        self.pipelines_fullscreen_btn.setCheckable(True)
        self.pipelines_fullscreen_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.pipelines_fullscreen_btn.clicked.connect(self.toggle_fullscreen_mode)
        self.pipelines_fullscreen_btn.setVisible(False)
        workflows_layout.addLayout(pipelines_top)

        workflows_splitter = QSplitter(Qt.Horizontal)

        # Left Panel (Saved Pipelines List)
        left_wf = QWidget()
        left_wf_layout = QVBoxLayout(left_wf)
        left_wf_layout.setContentsMargins(0, 0, 0, 0)

        create_panel_title = QLabel("Create New Pipeline")
        create_panel_title.setStyleSheet("font-weight: bold; color: #b9dcff;")
        left_wf_layout.addWidget(create_panel_title)

        left_wf_layout.addWidget(QLabel("Name:"))
        self.wf_build_name = QLineEdit()
        self.wf_build_name.setPlaceholderText("e.g. character_exporter")
        self.wf_build_name.textEdited.connect(
            lambda text: self._mark_pipeline_metadata_user_edited("name", text)
        )
        self.wf_build_name.textChanged.connect(self.update_builder_code_preview)
        left_wf_layout.addWidget(self.wf_build_name)

        left_wf_layout.addWidget(QLabel("Pipeline Goal / Description:"))
        self.wf_build_goal = QLineEdit()
        self.wf_build_goal.setPlaceholderText("Describe the goal of this pipeline...")
        self.wf_build_goal.textEdited.connect(
            lambda text: self._mark_pipeline_metadata_user_edited("goal", text)
        )
        self.wf_build_goal.textChanged.connect(self.update_builder_code_preview)
        left_wf_layout.addWidget(self.wf_build_goal)

        # Pipelines are cross-DCC by design. Keep a hidden compatibility field for
        # older save/load code, but do not ask the user to choose one global host.
        self.wf_build_host = QComboBox()
        self.wf_build_host.addItems(["cross_dcc"])
        self.wf_build_host.setCurrentText("cross_dcc")
        self.wf_build_host.setVisible(False)
        left_wf_layout.addWidget(self.wf_build_host)

        self.create_wf_btn = QPushButton("Create New Pipeline")
        configure_button(self.create_wf_btn, "edit", text="New pipeline", role="secondary")
        self.create_wf_btn.setToolTip("Clear the composer and start a new pipeline definition")
        self.create_wf_btn.clicked.connect(self.start_new_workflow_builder)
        left_wf_layout.addWidget(self.create_wf_btn)

        self.wf_build_save_btn = QPushButton("Save Pipeline")
        configure_button(self.wf_build_save_btn, "save", text="Save pipeline", role="primary")
        self.wf_build_save_btn.setToolTip("Save and compile the current pipeline")
        self.wf_build_save_btn.clicked.connect(self.save_new_workflow)
        left_wf_layout.addWidget(self.wf_build_save_btn)

        left_wf_layout.addSpacing(8)
        saved_label = QLabel("Saved Pipelines:")
        set_ui_role(saved_label, "sectionTitle")
        left_wf_layout.addWidget(saved_label)
        self.wf_filter_input = QLineEdit()
        self.wf_filter_input.setPlaceholderText("Filter pipelines...")
        self.wf_filter_input.textChanged.connect(self.filter_workflows)
        left_wf_layout.addWidget(self.wf_filter_input)

        self.workflows_list = QListWidget()
        self.workflows_list.itemSelectionChanged.connect(
            self.on_workflow_selection_changed
        )
        # Double-clicking a saved pipeline opens it directly in the composer
        # instead of showing the legacy details/parameter screen.
        self.workflows_list.itemDoubleClicked.connect(
            lambda *_args: self.load_selected_workflow_to_builder()
        )
        left_wf_layout.addWidget(self.workflows_list, 1)

        refresh_list_btn = QPushButton("Refresh List")
        configure_button(refresh_list_btn, "database", text="Refresh list", role="quiet")
        refresh_list_btn.clicked.connect(self.refresh_workflows_list)
        left_wf_layout.addWidget(refresh_list_btn)

        workflows_splitter.addWidget(left_wf)

        # Right Stacked Panel (Manager or Builder)
        self.wf_stack = QStackedWidget()

        # --- Stack Widget 1: Manager View ---
        self.wf_manager_widget = QWidget()
        manager_layout = QVBoxLayout(self.wf_manager_widget)
        manager_layout.setContentsMargins(0, 0, 0, 0)

        self.wf_header = QLabel("Select a pipeline to view details.")
        set_ui_role(self.wf_header, "sectionTitle")
        manager_layout.addWidget(self.wf_header)

        self.wf_path_lbl = QLabel("")
        self.wf_path_lbl.setStyleSheet(
            "color: #888888; font-family: Consolas; font-size: 11px;"
        )
        self.wf_path_lbl.setWordWrap(True)
        manager_layout.addWidget(self.wf_path_lbl)

        manager_layout.addWidget(QLabel("Goal / Description:"))
        self.wf_goal_display = QTextEdit()
        self.wf_goal_display.setReadOnly(True)
        self.wf_goal_display.setMaximumHeight(50)
        manager_layout.addWidget(self.wf_goal_display)

        manager_layout.addWidget(
            QLabel("Parameters (Slots) - Double-click value to edit:")
        )
        self.wf_slots_table = QTableWidget(0, 2)
        self.wf_slots_table.setHorizontalHeaderLabels(["Parameter Name", "Value"])
        self.wf_slots_table.horizontalHeader().setStretchLastSection(True)
        self.wf_slots_table.setMaximumHeight(150)
        self.wf_slots_table.setStyleSheet("""
            QTableWidget {
                background-color: #00040a;
                color: #d7dde5;
                gridline-color: #12324a;
                border: 1px solid #12324a;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #0f141c;
                color: #b9dcff;
                padding: 4px;
                border: 1px solid #12324a;
            }
            QTableWidget QTableCornerButton::section {
                background-color: #0f141c;
                border: 1px solid #12324a;
            }
        """)
        manager_layout.addWidget(self.wf_slots_table)

        # Actions Row
        actions_row = QHBoxLayout()
        self.wf_save_btn = QPushButton("Save Parameters")
        configure_button(self.wf_save_btn, "save", text="Save parameters", role="secondary")
        self.wf_save_btn.clicked.connect(self.save_workflow_parameter_changes)
        self.wf_save_btn.setEnabled(False)
        actions_row.addWidget(self.wf_save_btn)

        self.wf_run_btn = QPushButton("Run in DCC")
        configure_button(self.wf_run_btn, "play", text="Run in DCC", role="primary")
        self.wf_run_btn.clicked.connect(self.run_selected_workflow)
        self.wf_run_btn.setEnabled(False)
        actions_row.addWidget(self.wf_run_btn)

        self.wf_test_btn = QPushButton("Run Test")
        configure_button(self.wf_test_btn, "test", text="Run test", role="secondary")
        self.wf_test_btn.clicked.connect(self.run_selected_workflow_test)
        self.wf_test_btn.setEnabled(False)
        actions_row.addWidget(self.wf_test_btn)

        self.wf_test_log_btn = QPushButton("View Test Log")
        configure_button(self.wf_test_log_btn, "document", text="Test log", role="quiet")
        self.wf_test_log_btn.clicked.connect(self.view_test_log)
        self.wf_test_log_btn.setEnabled(False)
        actions_row.addWidget(self.wf_test_log_btn)

        self.wf_delete_btn = QPushButton("Delete")
        configure_button(self.wf_delete_btn, "trash", text="Delete", role="danger")
        self.wf_delete_btn.clicked.connect(self.delete_selected_workflow)
        self.wf_delete_btn.setEnabled(False)
        actions_row.addWidget(self.wf_delete_btn)

        self.wf_edit_btn = QPushButton("Edit Visually")
        configure_button(self.wf_edit_btn, "edit", text="Edit visually", role="secondary")
        self.wf_edit_btn.clicked.connect(self.load_selected_workflow_to_builder)
        self.wf_edit_btn.setEnabled(False)
        actions_row.addWidget(self.wf_edit_btn)

        self.wf_export_btn = QPushButton("Export .py")
        configure_button(self.wf_export_btn, "export", text="Export .py", role="quiet")
        self.wf_export_btn.clicked.connect(self.export_selected_workflow)
        self.wf_export_btn.setEnabled(False)
        self.wf_export_btn.setToolTip(
            "Export the pipeline .py file to a chosen location"
        )
        actions_row.addWidget(self.wf_export_btn)

        self.wf_append_btn = QPushButton("Append to File")
        configure_button(self.wf_append_btn, "document", text="Append to file", role="quiet")
        self.wf_append_btn.clicked.connect(self.append_selected_workflow_to_file)
        self.wf_append_btn.setEnabled(False)
        self.wf_append_btn.setToolTip(
            "Append this pipeline function to an existing .py file"
        )
        actions_row.addWidget(self.wf_append_btn)

        for overflow_button in (
            self.wf_test_log_btn,
            self.wf_delete_btn,
            self.wf_export_btn,
            self.wf_append_btn,
        ):
            overflow_button.setVisible(False)
        self.wf_more_btn = QToolButton()
        configure_button(
            self.wf_more_btn,
            "more_horizontal",
            text="More",
            tooltip="More pipeline actions",
            role="quiet",
        )
        self.wf_more_btn.setPopupMode(QToolButton.InstantPopup)
        workflow_more_menu = QMenu(self.wf_more_btn)
        workflow_more_actions = []
        for label, icon_name, source_button, callback in (
            ("View test log", "document", self.wf_test_log_btn, self.view_test_log),
            ("Export .py", "export", self.wf_export_btn, self.export_selected_workflow),
            ("Append to file", "document", self.wf_append_btn, self.append_selected_workflow_to_file),
            ("Delete pipeline", "trash", self.wf_delete_btn, self.delete_selected_workflow),
        ):
            action = workflow_more_menu.addAction(icon(icon_name), label)
            action.triggered.connect(lambda _checked=False, fn=callback: fn())
            workflow_more_actions.append((action, source_button))

        def sync_workflow_more_actions():
            for action, source_button in workflow_more_actions:
                action.setEnabled(source_button.isEnabled())

        workflow_more_menu.aboutToShow.connect(sync_workflow_more_actions)
        self.wf_more_btn.setMenu(workflow_more_menu)
        actions_row.addWidget(self.wf_more_btn)

        manager_layout.addLayout(actions_row)

        self.wf_test_status = QLabel("")
        self.wf_test_status.setStyleSheet("font-weight: bold;")
        manager_layout.addWidget(self.wf_test_status)

        manager_layout.addWidget(QLabel("Source Code:"))
        self.wf_code_preview = QPlainTextEdit()
        self.wf_code_preview.setReadOnly(True)
        self.wf_code_preview.setFont(QFont("Consolas", 9))
        manager_layout.addWidget(self.wf_code_preview)

        self.wf_stack.addWidget(self.wf_manager_widget)

        # --- Stack Widget 2: Builder View ---
        self.wf_builder_widget = QWidget()
        builder_layout = QVBoxLayout(self.wf_builder_widget)
        builder_layout.setContentsMargins(0, 0, 0, 0)

        # Name/description controls live in the left pipeline rail so the
        # composer area can stay focused on graph editing and execution.

        # Dual-mode Builder Tabs
        self.wf_builder_tabs = DetachableTabWidget(self, tab_type="pipeline")
        self.wf_builder_tabs.tabActivated.connect(
            lambda title, _widget, _container: setattr(self, "_active_pipeline_tab_title", title)
        )

        # --- Tab 1: Node Graph Mode ---
        graph_mode_tab = QWidget()
        graph_mode_layout = QVBoxLayout(graph_mode_tab)
        graph_mode_layout.setContentsMargins(0, 4, 0, 0)

        # Composer actions live with the node graph now. The legacy manager
        # screen remains only as a compatibility fallback for old methods.
        graph_actions_row = QHBoxLayout()
        graph_actions_row.setSpacing(6)

        self.wf_graph_new_btn = QPushButton("New Graph")
        self.wf_graph_new_btn.setToolTip("Clear the current composer and start a new graph")
        self.wf_graph_new_btn.clicked.connect(self.start_new_workflow_builder)
        graph_actions_row.addWidget(self.wf_graph_new_btn)

        self.wf_graph_save_btn = QPushButton("Save / Compile")
        self.wf_graph_save_btn.setToolTip("Save and compile the current node graph / Python pipeline")
        self.wf_graph_save_btn.clicked.connect(self.save_new_workflow)
        graph_actions_row.addWidget(self.wf_graph_save_btn)

        self.wf_graph_undo_btn = QPushButton("Undo Graph")
        self.wf_graph_undo_btn.setToolTip("Undo the last node graph change")
        self.wf_graph_undo_btn.clicked.connect(lambda: self.wf_node_view.undo_last_change() if hasattr(self, "wf_node_view") else None)
        graph_actions_row.addWidget(self.wf_graph_undo_btn)

        self.wf_graph_from_prompt_btn = QPushButton("Build From Prompt")
        self.wf_graph_from_prompt_btn.setToolTip("Resolve the pipeline description into indexed functions, arguments, and graph links")
        self.wf_graph_from_prompt_btn.clicked.connect(self.build_pipeline_graph_from_prompt)
        graph_actions_row.addWidget(self.wf_graph_from_prompt_btn)

        self.wf_use_default_settings_checkbox = QCheckBox("Use Default Settings")
        self.wf_use_default_settings_checkbox.setChecked(True)
        self.wf_use_default_settings_checkbox.setToolTip(
            "Resolve omitted values from host context. Unreal imports use the current Content Browser folder."
        )
        graph_actions_row.addWidget(self.wf_use_default_settings_checkbox)

        self.wf_unreal_destination_edit = QLineEdit()
        self.wf_unreal_destination_edit.setPlaceholderText("/Game/Custom/ImportFolder")
        self.wf_unreal_destination_edit.setToolTip(
            "Custom Unreal import folder used when Default Settings is off"
        )
        self.wf_unreal_destination_edit.setEnabled(False)
        self.wf_unreal_destination_edit.setMaximumWidth(220)
        self.wf_use_default_settings_checkbox.toggled.connect(
            lambda checked: self.wf_unreal_destination_edit.setEnabled(not checked)
        )
        graph_actions_row.addWidget(self.wf_unreal_destination_edit)

        self.wf_graph_run_btn = QPushButton("Run")
        self.wf_graph_run_btn.setToolTip("Run the selected saved pipeline")
        self.wf_graph_run_btn.clicked.connect(self.run_selected_workflow)
        graph_actions_row.addWidget(self.wf_graph_run_btn)

        self.wf_graph_test_btn = QPushButton("Test")
        self.wf_graph_test_btn.setToolTip("Run the selected pipeline test")
        self.wf_graph_test_btn.clicked.connect(self.run_selected_workflow_test)
        graph_actions_row.addWidget(self.wf_graph_test_btn)

        self.wf_graph_log_btn = QPushButton("Test Log")
        self.wf_graph_log_btn.clicked.connect(self.view_test_log)
        graph_actions_row.addWidget(self.wf_graph_log_btn)

        self.wf_graph_export_btn = QPushButton("Export .py")
        self.wf_graph_export_btn.clicked.connect(self.export_selected_workflow)
        graph_actions_row.addWidget(self.wf_graph_export_btn)

        self.wf_graph_append_btn = QPushButton("Append to File")
        self.wf_graph_append_btn.clicked.connect(self.append_selected_workflow_to_file)
        graph_actions_row.addWidget(self.wf_graph_append_btn)

        self.wf_graph_delete_btn = QPushButton("Delete")
        self.wf_graph_delete_btn.clicked.connect(self.delete_selected_workflow)
        graph_actions_row.addWidget(self.wf_graph_delete_btn)

        graph_actions_row.addStretch(1)
        graph_mode_layout.addLayout(graph_actions_row)

        # Legacy step widgets still exist as an invisible backing structure while
        # the workflow code is migrated. They are not part of the visible UI.
        self.wf_steps_container = QWidget()
        self.wf_steps_container.setVisible(False)
        self.wf_steps_layout = QVBoxLayout(self.wf_steps_container)
        self.wf_steps_layout.setContentsMargins(0, 0, 0, 0)
        self.wf_steps_layout.addStretch(1)
        self.wf_steps_scroll = QScrollArea()
        self.wf_steps_scroll.setWidget(self.wf_steps_container)
        self.wf_steps_scroll.setVisible(False)

        add_node_row = QHBoxLayout()
        add_node_row.addWidget(QLabel("DCC:"))
        self.wf_build_dcc_filter = QComboBox()
        self.wf_build_dcc_filter.setToolTip("Filter node candidates by host/DCC package")
        for _label, _value in [
            ("All", "all"),
            ("Maya", "maya"),
            ("Unreal", "unreal"),
            ("Blender", "blender"),
            ("MotionBuilder", "motionbuilder"),
            ("Substance Painter", "substance_painter"),
            ("Unity", "unity"),
            ("Utility", "utility"),
            ("Project", "project"),
        ]:
            self.wf_build_dcc_filter.addItem(_label, _value)
        self.wf_symbol_filter_timer = QTimer(self)
        self.wf_symbol_filter_timer.setSingleShot(True)
        self.wf_symbol_filter_timer.setInterval(120)
        self.wf_symbol_filter_timer.timeout.connect(
            lambda: self.filter_discovered_symbols(self.wf_build_func_filter.text())
        )
        self.wf_build_dcc_filter.currentIndexChanged.connect(
            lambda *_args: self.schedule_pipeline_symbol_filter()
        )
        self.wf_build_dcc_filter.setStyleSheet(
            "QComboBox { background: #000711; border: 1px solid #12324a; color: #b9dcff; }"
        )
        add_node_row.addWidget(self.wf_build_dcc_filter)

        add_node_row.addWidget(QLabel("Search / Filter:"))
        self.wf_build_func_filter = QLineEdit()
        self.wf_build_func_filter.setPlaceholderText(
            "Type to find a function/class to add as a node..."
        )
        self.wf_build_func_filter.setStyleSheet(
            "QLineEdit { background: #0b0f14; border: 1px solid #1e9bff; color: #d7dde5; }"
        )
        self.wf_build_func_filter.textChanged.connect(
            lambda *_args: self.schedule_pipeline_symbol_filter()
        )
        add_node_row.addWidget(self.wf_build_func_filter, 2)

        self.wf_build_func_box = QComboBox()
        self.wf_build_func_box.setStyleSheet(
            "QComboBox { background: #000711; border: 1px solid #12324a; color: #b9dcff; }"
        )
        add_node_row.addWidget(self.wf_build_func_box, 2)

        self.wf_add_node_btn = QPushButton("Add Node")
        self.wf_add_node_btn.clicked.connect(self.add_builder_step)
        add_node_row.addWidget(self.wf_add_node_btn)
        graph_mode_layout.addLayout(add_node_row)

        self.wf_graph_splitter = QSplitter(Qt.Horizontal)
        graph_splitter = self.wf_graph_splitter
        self.wf_node_view = PipelineNodeView()
        self.wf_attribute_editor = PipelineAttributeEditor()
        graph_splitter.addWidget(self.wf_node_view)
        graph_splitter.addWidget(self.wf_attribute_editor)
        graph_splitter.setSizes([820, 260])
        graph_splitter.splitterMoved.connect(lambda *_args: self.schedule_window_state_save())
        graph_mode_layout.addWidget(graph_splitter, 1)

        try:
            self.wf_node_view.graphChanged.connect(self._handle_pipeline_graph_changed)
            self.wf_node_view.linkCreated.connect(self._handle_pipeline_graph_changed)
            self.wf_node_view.linkDeleted.connect(self._handle_pipeline_graph_changed)
            self.wf_node_view.orderChanged.connect(lambda *_: self._handle_pipeline_graph_changed())
            self.wf_node_view.literalChanged.connect(self._handle_pipeline_attribute_literal_changed)
            self.wf_node_view.nodeDeleted.connect(self._handle_pipeline_node_deleted)
            self.wf_node_view.toolNodeRequested.connect(lambda symbol: self.add_builder_step(custom_sym=symbol))
            self.wf_node_view.statusMessage.connect(self._report_workflow_builder_event)
        except Exception:
            pass
        try:
            self.wf_node_view.graphInteractionRequested.connect(
                self.ensure_pipeline_graph_interaction_ready
            )
            self._refresh_pipeline_node_view_tool_symbols()
        except Exception as exc:
            self._report_workflow_builder_event(
                f"Could not connect graph tool inventory: {exc}"
            )
        try:
            self._wire_pipeline_attribute_editor_once()
        except Exception:
            pass

        try:
            self.wf_node_undo_shortcut = QShortcut(QKeySequence.Undo, self.wf_node_view)
            self.wf_node_undo_shortcut.activated.connect(self.wf_node_view.undo_last_change)
        except Exception:
            pass

        self.wf_builder_tabs.addTab(graph_mode_tab, "Node Graph")

        # --- Tab 2: Script Mode (Python Code Editor) ---
        script_mode_tab = QWidget()
        script_mode_layout = QVBoxLayout(script_mode_tab)
        script_mode_layout.setContentsMargins(0, 4, 0, 0)

        # Use the same Python editor class as the rest of the app so undo,
        # syntax/highlighting, shortcuts, and editor behavior stay consistent.
        self.wf_builder_code_edit = CodeEditor() if CodeEditor is not None else QPlainTextEdit()
        try:
            self.wf_builder_code_edit.setFont(QFont("Consolas", 10))
        except Exception:
            pass
        self.wf_builder_code_edit.setStyleSheet("""
            QPlainTextEdit, QTextEdit {
                background-color: #00040a;
                color: #d7dde5;
                border: 1px solid #12324a;
                border-radius: 4px;
            }
        """)
        script_mode_layout.addWidget(self.wf_builder_code_edit, 1)
        self._workflow_python_parse_timer = QTimer(self)
        self._workflow_python_parse_timer.setSingleShot(True)
        self._workflow_python_parse_timer.timeout.connect(self.sync_workflow_graph_from_python)
        self.wf_builder_code_edit.textChanged.connect(self._schedule_workflow_python_to_graph_sync)
        try:
            self.wf_python_undo_shortcut = QShortcut(QKeySequence.Undo, self.wf_builder_code_edit)
            self.wf_python_undo_shortcut.activated.connect(self.wf_builder_code_edit.undo)
        except Exception:
            pass
        self.wf_builder_tabs.addTab(script_mode_tab, "Python")

        self.wf_graph_mode_tab = graph_mode_tab
        self.wf_script_mode_tab = script_mode_tab
        self.wf_pipeline_composer_locked = True
        self.wf_pipeline_current_key = None

        builder_layout.addWidget(self.wf_builder_tabs, 1)

        # Legacy bottom builder actions are hidden now because composer actions
        # live directly in the Node Graph toolbar. Keep the save button object
        # for compatibility with older code paths.
        builder_actions = QHBoxLayout()
        builder_actions_layout = builder_layout.addLayout(builder_actions)

        self.wf_stack.addWidget(self.wf_builder_widget)
        # Pipelines open directly to the composer; the legacy detail screen is
        # not the primary workflow anymore.
        self.wf_stack.setCurrentIndex(1)
        QTimer.singleShot(0, lambda: self.set_pipeline_composer_enabled(False, "Create or select a pipeline to edit the node graph / Python."))

        workflows_splitter.addWidget(self.wf_stack)
        workflows_splitter.setSizes([300, 880])

        workflows_layout.addWidget(workflows_splitter, 1)
        self.workspace_tabs.addTab(workflows_tab, "Pipelines")

        self.workspace_area_splitter = QSplitter(Qt.Horizontal)
        self.workspace_area_splitter.setChildrenCollapsible(False)
        self.workspace_area_splitter.setHandleWidth(8)
        self.workspace_area_splitter.addWidget(self.workspace_tabs)
        self.workspace_area_splitter.addWidget(self.workspace_anchor_tabs)
        self.workspace_area_splitter.setSizes([1000, 0])
        self.workspace_area_splitter.splitterMoved.connect(lambda *_args: self.schedule_window_state_save())
        main_layout.addWidget(self.workspace_area_splitter, 1)
        QTimer.singleShot(0, self.install_editor_navigation_hotkeys)

        # Compact attachment strip. Hidden until the user attaches images/files.
        # This replaces the old "Attached images: none" text with visual chips.
        self.attachment_strip = QScrollArea()
        self.attachment_strip.setWidgetResizable(True)
        self.attachment_strip.setMaximumHeight(78)
        self.attachment_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.attachment_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.attachment_strip.setVisible(False)
        self.attachment_strip.setStyleSheet(
            "QScrollArea { background: #000711; border: 1px solid #12324a; border-radius: 8px; }"
        )
        self.attachment_strip_inner = QWidget()
        self.attachment_strip_layout = QHBoxLayout(self.attachment_strip_inner)
        self.attachment_strip_layout.setContentsMargins(6, 5, 6, 5)
        self.attachment_strip_layout.setSpacing(6)
        self.attachment_strip.setWidget(self.attachment_strip_inner)
        main_layout.addWidget(self.attachment_strip)

        # Backward compatibility for older methods that reference image_label.
        self.image_label = QLabel("")
        self.image_label.setVisible(False)

        self.prime_editor = QPlainTextEdit()
        self.prime_editor.setPlainText(PRIME_PROMPT)
        self.prime_editor.setFont(QFont("Consolas", 9))
        self.prime_editor.setMaximumHeight(80)
        self.prime_editor.setVisible(False)
        main_layout.addWidget(self.prime_editor)

        self.bottom_controls_widget = QWidget()
        bottom_layout = QVBoxLayout(self.bottom_controls_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        compact_actions = QHBoxLayout()
        compact_actions.setSpacing(6)

        def _small_action_button(icon_name, tooltip, callback, role="quiet"):
            btn = QPushButton()
            configure_button(
                btn,
                icon_name,
                tooltip=tooltip,
                role=role,
                icon_only=True,
            )
            btn.clicked.connect(callback)
            compact_actions.addWidget(btn)
            return btn

        _small_action_button(
            "cancel",
            "Cancel the active model/tool request",
            self.cancel_active_query,
            role="danger",
        )
        self.approve_editor_plan_btn = QPushButton("Approve Plan")
        self.approve_editor_plan_btn.setToolTip(
            "Approve the reviewed implementation plan and generate a code preview"
        )
        self.approve_editor_plan_btn.clicked.connect(self.approve_pending_editor_plan)
        self.approve_editor_plan_btn.setVisible(False)
        compact_actions.addWidget(self.approve_editor_plan_btn)
        self.apply_fix_compact_btn = _small_action_button(
            "check", "Apply the latest proposed editor fix/diff", self.apply_pending_editor_patch
        )
        _small_action_button("undo", "Undo the last applied project/editor change", self.undo_last_applied_changes)
        _small_action_button("clipboard", "Copy the last model prompt", self.copy_last_prompt)
        _small_action_button("document", "Copy the full conversation log", self.copy_full_log)

        # Pipeline saving is contextual now: the Pipelines tab owns pipeline management,
        # and generated answers can still populate this hidden menu when needed.
        self.workflow_action_btn = QToolButton(self.bottom_controls_widget)
        self.workflow_action_btn.setText("Pipeline")
        self.workflow_action_btn.setToolTip(
            "Pipeline actions are available from the Pipelines tab or contextual response actions."
        )
        self.workflow_action_btn.setPopupMode(QToolButton.InstantPopup)
        self.workflow_action_btn.setEnabled(False)
        self.workflow_action_btn.setVisible(False)
        self.add_editor_answer_workflow_menu = QMenu(self.workflow_action_btn)
        self.add_editor_answer_workflow_menu.aboutToShow.connect(
            self.refresh_editor_answer_workflow_menu
        )
        self.workflow_action_btn.setMenu(self.add_editor_answer_workflow_menu)
        self.add_editor_answer_workflow_btn = self.workflow_action_btn

        compact_actions.addStretch(1)
        bottom_layout.addLayout(compact_actions)

        self.clarification_controls_widget = QWidget(self.bottom_controls_widget)
        self.clarification_controls_layout = QHBoxLayout(self.clarification_controls_widget)
        self.clarification_controls_layout.setContentsMargins(6, 4, 6, 4)
        self.clarification_controls_layout.setSpacing(6)
        self.clarification_controls_widget.setStyleSheet(
            "QWidget { background-color: #000711; border: 1px solid #12324a; border-radius: 6px; }"
            "QPushButton { padding: 4px 10px; }"
            "QComboBox, QLineEdit { padding: 3px 6px; }"
        )
        self.clarification_controls_widget.setVisible(False)
        bottom_layout.addWidget(self.clarification_controls_widget)

        prompt_profile_row = QHBoxLayout()
        prompt_profile_row.setSpacing(6)
        prompt_profile_row.addWidget(QLabel("Code agent:"))

        self.code_prompt_mode_box = QComboBox()
        for label, value in (
            ("Auto", "auto"),
            ("Ask", "ask"),
            ("Plan", "plan"),
            ("Edit", "edit"),
            ("Review", "review"),
        ):
            self.code_prompt_mode_box.addItem(label, value)
        self.code_prompt_mode_box.setToolTip(
            "Choose the requested outcome explicitly. Auto keeps natural-language inference enabled."
        )
        prompt_profile_row.addWidget(self.code_prompt_mode_box)

        self.code_prompt_scope_box = QComboBox()
        for label, value in (
            ("Auto scope", "auto"),
            ("Selection", "selection"),
            ("Current file", "file"),
            ("Folder", "folder"),
            ("Project", "project"),
            ("DCC session", "dcc"),
        ):
            self.code_prompt_scope_box.addItem(label, value)
        self.code_prompt_scope_box.setToolTip(
            "Set the maximum context boundary used for discovery and generation."
        )
        prompt_profile_row.addWidget(self.code_prompt_scope_box)

        self.code_prompt_depth_box = QComboBox()
        for label, value in (
            ("Fast", "fast"),
            ("Balanced", "balanced"),
            ("Deep", "deep"),
            ("Maximum quality", "maximum"),
        ):
            self.code_prompt_depth_box.addItem(label, value)
        self.code_prompt_depth_box.setToolTip(
            "Controls the model family member, reasoning effort, response detail, latency, and cost."
        )
        prompt_profile_row.addWidget(self.code_prompt_depth_box)

        self.code_prompt_permission_box = QComboBox()
        for label, value in (
            ("Read only", "read_only"),
            ("Preview changes", "preview"),
            ("Apply after review", "apply_after_review"),
            ("Automatic safe edits", "automatic_safe"),
        ):
            self.code_prompt_permission_box.addItem(label, value)
        self.code_prompt_permission_box.setToolTip(
            "Maximum mutation authority. Destructive and external actions always require separate approval."
        )
        prompt_profile_row.addWidget(self.code_prompt_permission_box)
        prompt_profile_row.addStretch(1)
        bottom_layout.addLayout(prompt_profile_row)

        for box, key, default in (
            (self.code_prompt_mode_box, "code_prompt_mode", "auto"),
            (self.code_prompt_scope_box, "code_prompt_scope", "auto"),
            (self.code_prompt_depth_box, "code_prompt_depth", "balanced"),
            (self.code_prompt_permission_box, "code_prompt_permission", "preview"),
        ):
            index = box.findData(self.settings.get(key, default))
            box.setCurrentIndex(index if index >= 0 else box.findData(default))

        def persist_code_prompt_profile(*_args):
            from tech_connector.services.code_prompt_profile_service import (
                normalize_code_prompt_profile,
            )

            profile = normalize_code_prompt_profile(
                {
                    "mode": self.code_prompt_mode_box.currentData(),
                    "scope": self.code_prompt_scope_box.currentData(),
                    "depth": self.code_prompt_depth_box.currentData(),
                    "permission": self.code_prompt_permission_box.currentData(),
                }
            )
            self.settings.update(
                {
                    "code_prompt_mode": profile.mode,
                    "code_prompt_scope": profile.scope,
                    "code_prompt_depth": profile.depth,
                    "code_prompt_permission": profile.permission,
                }
            )
            if (
                bool(self.settings.get("auto_select_openai_model_by_depth", True))
                and hasattr(self, "model_provider_box")
                and self.model_provider_box.currentData() == "openai"
            ):
                from tech_connector.services.code_prompt_profile_service import (
                    preferred_openai_model,
                )

                current_model = str(self.model_box.currentData() or "")
                current_name = current_model.partition(":")[2].lower()
                if not current_name or current_name.startswith(
                    ("gpt-5.6", "gpt-5.3-codex")
                ):
                    preferred_model = "openai:" + preferred_openai_model(profile.depth)
                    preferred_index = self.model_box.findData(preferred_model)
                    if preferred_index >= 0:
                        self.model_box.setCurrentIndex(preferred_index)
            permission_index = self.code_prompt_permission_box.findData(profile.permission)
            if permission_index >= 0 and permission_index != self.code_prompt_permission_box.currentIndex():
                self.code_prompt_permission_box.blockSignals(True)
                self.code_prompt_permission_box.setCurrentIndex(permission_index)
                self.code_prompt_permission_box.blockSignals(False)
            try:
                self.service.settings.update(self.settings)
                self.service.save_settings()
            except Exception:
                pass
            try:
                self.update_unified_prompt_context_label()
            except Exception:
                pass

        for box in (
            self.code_prompt_mode_box,
            self.code_prompt_scope_box,
            self.code_prompt_depth_box,
            self.code_prompt_permission_box,
        ):
            box.currentIndexChanged.connect(persist_code_prompt_profile)

        input_row = QHBoxLayout()
        self.input = GrowingPromptEdit()
        set_ui_role(self.input, "composer")
        self.input.setPlaceholderText(
            "Ask anything. I’ll infer chat vs current file vs selection vs project search vs pipeline."
        )
        self.input.setToolTip(
            "One prompt line for everything: chat, editor questions, code edits, project search, DCC operations, and pipeline creation."
        )
        self.input.sendRequested.connect(self.send_message)
        self.input.textChangedString.connect(self.on_chat_input_text_changed)
        self.input.installEventFilter(self)
        input_row.addWidget(self.input, 1)
        send_btn = QPushButton("Send")
        configure_button(send_btn, "send", text="Send", tooltip="Send request", role="primary")
        send_btn.clicked.connect(self.send_message)
        input_row.addWidget(send_btn)

        self.prioritize_open_file_context_checkbox = QCheckBox("Prioritize open files")
        self.prioritize_open_file_context_checkbox.setChecked(
            bool(self.settings.get("prioritize_open_file_context", False))
        )
        self.prioritize_open_file_context_checkbox.setToolTip(
            "Prioritize currently open editor files. Off still searches the indexed project; prompts like 'this file' or 'open files' still use them."
        )
        self.prioritize_open_file_context_checkbox.stateChanged.connect(
            self.on_prioritize_open_file_context_changed
        )
        input_row.addWidget(self.prioritize_open_file_context_checkbox)

        attach_file_btn = QPushButton("File")
        attach_file_btn.setToolTip("Attach files to the next prompt. Text/code files are included as searchable context.")
        configure_button(attach_file_btn, "paperclip", text="File", role="secondary")
        attach_file_btn.clicked.connect(self.attach_files)
        input_row.addWidget(attach_file_btn)

        paste_btn = QPushButton("Paste")
        paste_btn.setToolTip("Paste an image from the clipboard and attach it to the next prompt")
        configure_button(paste_btn, "clipboard", text="Paste", role="secondary")
        paste_btn.clicked.connect(self.paste_image_from_clipboard)
        input_row.addWidget(paste_btn)

        attach_btn = QPushButton("Image")
        attach_btn.setToolTip("Attach image files to the next prompt")
        configure_button(attach_btn, "image", text="Image", role="secondary")
        attach_btn.clicked.connect(self.attach_images)
        input_row.addWidget(attach_btn)
        bottom_layout.addLayout(input_row)

        self.prompt_context_label = QLabel("Context: Chat • Project • Model")
        set_ui_role(self.prompt_context_label, "context")
        self.prompt_context_label.setToolTip(
            "Shows what context the unified prompt will use. Editor and selection context are inferred automatically."
        )
        self.prompt_context_label.setWordWrap(False)
        self.prompt_context_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.live_process_label = QLabel("Working: Ready")
        set_ui_role(self.live_process_label, "context")
        self.live_process_label.setToolTip(
            "Shows the current Tech Connector operation, such as searching the project index, building context, routing, or waiting for the model."
        )
        self.live_process_label.setWordWrap(False)
        self.live_process_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.bottom_system_status_widget = QWidget()
        self.bottom_system_status_widget.setObjectName("bottomSystemStatusWidget")
        self.bottom_system_status_widget.setStyleSheet(
            "QWidget#bottomSystemStatusWidget { background-color: #0c1016; border: 1px solid #273241; border-radius: 6px; }"
        )
        bottom_status_layout = QVBoxLayout(self.bottom_system_status_widget)
        bottom_status_layout.setContentsMargins(6, 5, 6, 5)
        bottom_status_layout.setSpacing(5)

        bottom_status_header = QHBoxLayout()
        bottom_status_header.setContentsMargins(0, 0, 0, 0)
        bottom_status_header.setSpacing(6)
        self.bottom_system_status_title = QLabel("System Status")
        self.bottom_system_status_title.setStyleSheet("font-weight: bold; color: #b9dcff;")
        self.bottom_system_status_title.setWordWrap(False)
        bottom_status_header.addWidget(self.bottom_system_status_title)
        self.bottom_system_status_detail = QLabel("routing • model • knowledge • DCC • VCS")
        self.bottom_system_status_detail.setStyleSheet("color: #8fb9c9; font-size: 11px;")
        self.bottom_system_status_detail.setWordWrap(False)
        bottom_status_header.addWidget(self.bottom_system_status_detail)
        bottom_status_header.addWidget(self.prompt_context_label, 2)
        bottom_status_header.addWidget(self.live_process_label, 2)
        self.bottom_system_status_toggle_btn = QPushButton("Hide details")
        configure_button(
            self.bottom_system_status_toggle_btn,
            "chevron_up",
            text="Hide details",
            role="quiet",
        )
        self.bottom_system_status_toggle_btn.setMaximumWidth(110)
        self.bottom_system_status_toggle_btn.setCheckable(True)
        self.bottom_system_status_toggle_btn.setChecked(True)
        bottom_status_header.addWidget(self.bottom_system_status_toggle_btn)
        bottom_status_layout.addLayout(bottom_status_header)

        self.bottom_status_details_widget = QWidget()
        bottom_status_details_layout = QVBoxLayout(self.bottom_status_details_widget)
        bottom_status_details_layout.setContentsMargins(0, 0, 0, 0)
        bottom_status_details_layout.setSpacing(4)
        bottom_status_details_layout.addWidget(self.active_model_label)
        bottom_status_details_layout.addWidget(self.model_requirement_label)
        bottom_status_details_layout.addWidget(self.status_cards_scroll)
        bottom_status_details_layout.addLayout(index_row)
        bottom_status_layout.addWidget(self.bottom_status_details_widget)

        def _toggle_bottom_status(checked):
            self.bottom_status_details_widget.setVisible(bool(checked))
            self.bottom_system_status_toggle_btn.setText("Hide details" if checked else "Show details")
            self.bottom_system_status_toggle_btn.setIcon(
                icon("chevron_up" if checked else "chevron_down")
            )
            try:
                self.settings["show_system_status"] = bool(checked)
                self.service.save_settings(self.settings)
            except Exception:
                pass
            self.schedule_window_state_save()

        self.bottom_system_status_toggle_btn.toggled.connect(_toggle_bottom_status)
        initial_status_visible = bool(self.settings.get("show_system_status", False))
        self.bottom_system_status_toggle_btn.setChecked(initial_status_visible)
        _toggle_bottom_status(initial_status_visible)
        bottom_layout.addWidget(self.bottom_system_status_widget)

        # ── Model & Safety collapsible bar ─────────────────────────────────
        self._model_safety_visible = False
        ms_toggle_row = QHBoxLayout()
        self._ms_toggle_btn = QPushButton("▶ Model & Safety")
        self._ms_toggle_btn.setFlat(True)
        self._ms_toggle_btn.setStyleSheet(
            "QPushButton { color: #6ab04c; font-size: 11px; text-align:left; padding:0 4px; }"
            "QPushButton:hover { color: #b9dcff; }"
        )
        self._ms_toggle_btn.setFixedHeight(20)
        self._ms_toggle_btn.clicked.connect(self._toggle_model_safety_bar)

        self._route_label = QLabel("")
        self._route_label.setStyleSheet(
            "color:#5a9a3a; font-size:10px; padding-left:8px;"
        )
        self._ms_toggle_btn.setVisible(False)
        self._route_label.setVisible(False)
        ms_toggle_row.addWidget(self._ms_toggle_btn)
        ms_toggle_row.addWidget(self._route_label, 1)
        # Model safety lives in AI → Model & Safety / Settings; keep controls hidden for routing state.
        # bottom_layout.addLayout(ms_toggle_row)

        self._ms_bar_widget = QWidget()
        self._ms_bar_widget.setVisible(False)
        ms_bar_layout = QHBoxLayout(self._ms_bar_widget)
        ms_bar_layout.setContentsMargins(4, 2, 4, 2)
        ms_bar_layout.setSpacing(16)

        self._chk_local_only = QCheckBox("Local model only")
        self._chk_allow_better = QCheckBox("Allow better model for complex tasks")
        self._chk_allow_better.setChecked(True)
        self._chk_allow_modifications = QCheckBox("Allow project modifications")
        self._chk_allow_modifications.setChecked(True)
        self._chk_require_confirm = QCheckBox("Require confirmation before changes")
        self._chk_require_confirm.setChecked(True)
        self._chk_tutorial_mode = QCheckBox("Tutorial / Guidance only")
        self._chk_tutorial_mode.setChecked(bool(self.settings.get("tutorial_mode", False)))
        self._chk_tutorial_mode.setToolTip(
            "Deliver step-by-step guidance, architecture, checks, and code snippets only. "
            "No project mutations."
        )
        self._chk_tutorial_mode.stateChanged.connect(self._apply_tutorial_mode_constraints)
        self._chk_github_search = QCheckBox("Allow GitHub / Community Tool Search")

        _ms_chk_style = "QCheckBox { color:#b9dcff; font-size:11px; } QCheckBox::indicator { width:13px; height:13px; }"
        for chk in (
                self._chk_local_only,
                self._chk_allow_better,
                self._chk_allow_modifications,
                self._chk_require_confirm,
                self._chk_tutorial_mode,
                self._chk_github_search,
        ):
            chk.setStyleSheet(_ms_chk_style)
            chk.stateChanged.connect(lambda *_args: self.schedule_window_state_save())
            ms_bar_layout.addWidget(chk)

        ms_bar_layout.addStretch(1)
        bottom_layout.addWidget(self._ms_bar_widget)
        # ── end Model & Safety bar ─────────────────────────────────────────

        main_layout.addWidget(self.bottom_controls_widget)
        self._apply_tutorial_mode_constraints()

        self.main_splitter.addWidget(main)
        self.main_splitter.setSizes([360, 1180])
        self.main_splitter.splitterMoved.connect(lambda *_args: self.schedule_window_state_save())
        root.addWidget(self.main_splitter, 1)
    def get_file_context(self, file_path: str):
        service = self._get_project_intelligence_service()
        return service.get_file_context(file_path) if service else None

    def search_project_files(self, query: str, limit: int = 10):
        service = self._get_project_intelligence_service()
        return service.search_project_files(query, limit) if service else []
    def _toggle_model_safety_bar(self):
        self._model_safety_visible = not self._model_safety_visible
        self._ms_bar_widget.setVisible(self._model_safety_visible)
        self._ms_toggle_btn.setText(
            ("▼" if self._model_safety_visible else "▶") + " Model & Safety"
        )

    def _ms_local_only(self) -> bool:
        return (
                getattr(self, "_chk_local_only", None) is not None
                and self._chk_local_only.isChecked()
        )

    def _ms_allow_better(self) -> bool:
        return (
                getattr(self, "_chk_allow_better", None) is None
                or self._chk_allow_better.isChecked()
        )

    def _ms_require_confirm(self) -> bool:
        return (
                getattr(self, "_chk_require_confirm", None) is None
                or self._chk_require_confirm.isChecked()
        )

    def _ms_tutorial_mode(self) -> bool:
        return (
                getattr(self, "_chk_tutorial_mode", None) is not None
                and self._chk_tutorial_mode.isChecked()
        )

    def _apply_tutorial_mode_constraints(self) -> None:
        if getattr(self, "_chk_allow_modifications", None) is None:
            return
        if self._ms_tutorial_mode():
            self._chk_allow_modifications.setChecked(False)
            self._chk_allow_modifications.setEnabled(False)
        else:
            self._chk_allow_modifications.setEnabled(True)
        self.schedule_window_state_save()

    def _ms_allow_modifications(self) -> bool:
        return (
                getattr(self, "_chk_allow_modifications", None) is None
                or self._chk_allow_modifications.isChecked()
        )

    def _ms_github_search(self) -> bool:
        return (
                getattr(self, "_chk_github_search", None) is not None
                and self._chk_github_search.isChecked()
        )

    def _update_route_label(self, route) -> None:
        """Update the small route-tier label shown next to the Model & Safety toggle."""
        if not hasattr(self, "_route_label"):
            return
        tier = getattr(route, "tier", "")
        model = getattr(route, "model", "") or "?"
        score = getattr(route, "complexity", "")
        score_str = f" | complexity {score}/10" if score != "" else ""
        self._route_label.setText(f"→ {tier} · {model}{score_str}")

    def on_github_tools_checkbox_changed(self, state):
        enabled = state == 2  # Qt.Checked is 2 in PySide6
        self.settings["search_github_tools_when_composing"] = enabled
        self.service.save_settings()
        self.append(
            f"\n[Composer Mode] Sourced GitHub tool composition is now {'ENABLED' if enabled else 'DISABLED'}.\n"
        )

    def open_file_location(self, path=None):
        path = path or getattr(self, "current_file_path", "")

        if not path:
            QMessageBox.information(self, "No file", "No file is currently open.")
            return

        p = Path(path).resolve()

        if not p.exists():
            QMessageBox.warning(self, "File Not Found", f"File does not exist:\n{p}")
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

    def workspace_tab_titles(self):
        if hasattr(self, "workspace_tabs") and hasattr(self.workspace_tabs, "workspace_tab_titles"):
            return self.workspace_tabs.workspace_tab_titles()
        if not hasattr(self, "workspace_tabs"):
            return []
        return [self.workspace_tabs.tabText(i) for i in range(self.workspace_tabs.count())]

    def _find_workspace_tab(self, tab_name: str):
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return None
        target = tab_name.strip().lower()
        for index in range(tabs.count()):
            if tabs.tabText(index).strip().lower() == target:
                return tabs.widget(index)
        return None

    def _activate_workspace_tab(self, tab_name: str) -> bool:
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return False
        target = tab_name.strip().lower()
        for index in range(tabs.count()):
            if tabs.tabText(index).strip().lower() == target:
                tabs.setCurrentIndex(index)
                self.update_unified_prompt_context_label()
                return True
        return False

    def _ensure_visible_workspace_tab(self, tab_name: str) -> bool:
        if self._activate_workspace_tab(tab_name):
            return True
        self.set_workspace_tab_visible(tab_name, True)
        return self._activate_workspace_tab(tab_name)

    def _show_workspace_tab(self, tab_name: str, cache_name: str, builder) -> None:
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return

        if self._ensure_visible_workspace_tab(tab_name):
            return

        widget = getattr(self, cache_name, None)
        if widget is None:
            widget = builder()
            setattr(self, cache_name, widget)
            if widget is None:
                return

        index = self.workspace_tabs.addTab(widget, tab_name)
        self.workspace_tabs.setCurrentIndex(index)
        self.schedule_window_state_save()

    def _build_the_kingdom_workspace_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("The Kingdom Runtime Workspace")
        header.setStyleSheet("font-weight: bold; color: #b9dcff; font-size: 14px;")
        layout.addWidget(header)

        action_row = QHBoxLayout()
        play_btn = QPushButton("Play")
        play_btn.setToolTip("Run the current .tcscene flow in the runtime launcher.")
        play_btn.clicked.connect(self.play_tc_scene)

        stop_btn = QPushButton("Stop")
        stop_btn.setToolTip("Stop an active runtime session.")
        stop_btn.clicked.connect(self.stop_tc_play_in_editor)

        build_player_btn = QPushButton("Build Player")
        build_player_btn.setToolTip("Build a standalone runtime player from this scene.")
        build_player_btn.clicked.connect(self.build_tc_windows_player)

        engine_btn = QPushButton("Open Engine Console")
        engine_btn.setToolTip("Jump to the Editor tab for full runtime console controls.")
        engine_btn.clicked.connect(lambda: self._ensure_visible_workspace_tab("Editor"))

        action_row.addWidget(play_btn)
        action_row.addWidget(stop_btn)
        action_row.addWidget(build_player_btn)
        action_row.addWidget(engine_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        command_row = QHBoxLayout()
        command_label = QLabel("Runtime Command:")
        command_row.addWidget(command_label)
        command = QLineEdit()
        command.setPlaceholderText("engine.create_game_experience('my_world', ['realistic_simulation'])")
        command_row.addWidget(command, 1)
        run_btn = QPushButton("Run")
        run_btn.setToolTip("Execute a runtime command in the shared editor engine console context.")

        def _run_command():
            text = command.text().strip()
            if not text:
                return
            editor_input = getattr(self, "engine_console_input", None)
            if editor_input is not None:
                editor_input.setPlainText(text)
            self.execute_engine_console()

        run_btn.clicked.connect(_run_command)
        command_row.addWidget(run_btn)
        layout.addLayout(command_row)

        hint = QLabel("Output is shown in the shared Engine Console panel on the Editor tab.")
        hint.setStyleSheet("color: #84b5ff; font-size: 11px;")
        layout.addWidget(hint)
        layout.addStretch(1)
        return container

    def _build_ophanim_workspace_tab(self):
        try:
            from tech_connector.ui.image_editor_widget import ImageEditorWidget
        except Exception as exc:
            QMessageBox.warning(self, "Ophanim unavailable", str(exc))
            return None
        return ImageEditorWidget(parent=self)

    def _build_garden_workspace_tab(self):
        try:
            from tech_connector.ui.three_d_mesh_painter_widget import ThreeDMeshPainterViewport
        except Exception as exc:
            QMessageBox.warning(self, "The Garden unavailable", str(exc))
            return None
        return ThreeDMeshPainterViewport(parent=self)

    def open_editor_workspace_tab(self):
        self._ensure_visible_workspace_tab("Editor")

    def open_search_symbols_workspace_tab(self):
        self._ensure_visible_workspace_tab("Search / Symbols")

    def open_pipelines_workspace_tab(self):
        self._ensure_visible_workspace_tab("Pipelines")

    def open_the_kingdom_workspace_tab(self):
        self._show_workspace_tab(
            "The Kingdom (Game Engine Runtime Suite)",
            "_the_kingdom_workspace_tab",
            self._build_the_kingdom_workspace_tab,
        )

    def open_ophanim_workspace_tab(self):
        self._show_workspace_tab(
            "Ophanim (Image & Texture Review Suite)",
            "_ophanim_workspace_tab",
            self._build_ophanim_workspace_tab,
        )

    def open_garden_workspace_tab(self):
        self._show_workspace_tab(
            "The Garden (DCC Integration Suite)",
            "_garden_workspace_tab",
            self._build_garden_workspace_tab,
        )

    def close_workspace_tab(self, _container: DetachableTabWidget, index: int) -> None:
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return
        try:
            title = _container.tabText(index)
        except Exception:
            title = ""
        if title:
            if hasattr(self, "set_workspace_tab_visible"):
                self.set_workspace_tab_visible(title, False)
            else:
                if 0 <= index < _container.count():
                    _container.removeTab(index)
            return
        if 0 <= index < _container.count():
            _container.removeTab(index)

    def set_workspace_tab_visible(self, title, visible):
        if hasattr(self, "workspace_tabs") and hasattr(self.workspace_tabs, "set_tab_visible"):
            self.workspace_tabs.set_tab_visible(title, visible)
            self.update_unified_prompt_context_label()
            self.schedule_window_state_save()

    def is_workspace_tab_visible(self, title):
        if hasattr(self, "workspace_tabs") and hasattr(self.workspace_tabs, "is_tab_visible"):
            return self.workspace_tabs.is_tab_visible(title)
        return True

    def detach_current_workspace_tab(self):
        if hasattr(self, "workspace_tabs") and hasattr(self.workspace_tabs, "detach_current_tab"):
            self.workspace_tabs.detach_current_tab()
            self.update_unified_prompt_context_label()

    def anchor_current_workspace_tab_right(self):
        if not hasattr(self, "workspace_tabs") or not hasattr(self, "workspace_anchor_tabs"):
            return
        source = self.workspace_tabs
        index = source.currentIndex()
        if index < 0 or source.count() <= 1:
            return
        self.workspace_anchor_tabs.setVisible(True)
        self.workspace_anchor_tabs.move_tab_from_container(source, index)
        self._update_workspace_anchor_visibility()
        self.schedule_window_state_save()

    def close_workspace_anchor(self):
        if not hasattr(self, "workspace_tabs") or not hasattr(self, "workspace_anchor_tabs"):
            return
        while self.workspace_anchor_tabs.count():
            self.workspace_tabs.move_tab_from_container(self.workspace_anchor_tabs, 0)
        self._update_workspace_anchor_visibility()
        self.schedule_window_state_save()

    def _update_workspace_anchor_visibility(self):
        if not hasattr(self, "workspace_anchor_tabs"):
            return
        visible = self.workspace_anchor_tabs.count() > 0
        self.workspace_anchor_tabs.setVisible(visible)
        if hasattr(self, "workspace_area_splitter"):
            if visible:
                total = sum(self.workspace_area_splitter.sizes()) or 1400
                self.workspace_area_splitter.setSizes([max(650, int(total * 0.62)), max(420, int(total * 0.38))])
            else:
                self.workspace_area_splitter.setSizes([1, 0])
        self.update_unified_prompt_context_label()

    def reattach_all_workspace_tabs(self):
        if hasattr(self, "workspace_tabs") and hasattr(self.workspace_tabs, "reattach_all_tabs"):
            self.workspace_tabs.reattach_all_tabs()
            if hasattr(self, "workspace_anchor_tabs"):
                self.close_workspace_anchor()
            self.update_unified_prompt_context_label()
            self.schedule_window_state_save()

    def show_all_workspace_tabs(self):
        if hasattr(self, "workspace_tabs") and hasattr(self.workspace_tabs, "show_all_tabs"):
            self.workspace_tabs.show_all_tabs()
            self.update_unified_prompt_context_label()
            self.schedule_window_state_save()

    def on_workspace_tab_changed(self, index):
        title = self.workspace_tabs.tabText(index)
        self._active_workspace_title = title or "Chat"
        self.schedule_unified_prompt_context_label_update()
        self.schedule_window_state_save()

    def on_workspace_tab_activated(self, title, widget, container):
        self._active_workspace_title = title or "Chat"
        self.schedule_unified_prompt_context_label_update()
        self.schedule_window_state_save()

    def active_workspace_title(self):
        active = getattr(self, "_active_workspace_title", "")
        if active:
            return active
        if not hasattr(self, "workspace_tabs"):
            return "Chat"
        try:
            return self.workspace_tabs.tabText(self.workspace_tabs.currentIndex()) or "Chat"
        except Exception:
            return "Chat"

    def schedule_unified_prompt_context_label_update(self):
        if getattr(self, "_prompt_context_label_update_pending", False):
            return
        self._prompt_context_label_update_pending = True

        def apply_update():
            self._prompt_context_label_update_pending = False
            self.update_unified_prompt_context_label()

        QTimer.singleShot(0, apply_update)

    def update_unified_prompt_context_label(self):
        if not hasattr(self, "prompt_context_label"):
            return

        parts = []
        try:
            profile = self.code_prompt_profile()
            parts.extend(
                [
                    profile.mode.title(),
                    profile.scope.replace("_", " ").title(),
                    profile.depth.title(),
                    profile.permission.replace("_", " ").title(),
                ]
            )
        except Exception:
            pass
        tab = self.active_workspace_title()
        parts.append(tab)

        path = getattr(self, "current_file_path", "")
        if path:
            try:
                parts.append(Path(path).name)
            except Exception:
                parts.append("Current file")

        try:
            if hasattr(self, "code_editor"):
                cursor = self.code_editor.textCursor()
                selected = cursor.selectedText().replace("\u2029", "\n").strip()
                if selected:
                    parts.append(f"Selection {len(selected.splitlines())} lines")
        except Exception:
            pass

        try:
            if getattr(self, "attached_images", None):
                parts.append(f"Images {len(self.attached_images)}")
        except Exception:
            pass

        try:
            if getattr(self, "_last_index_sync_status", None):
                sync = self._last_index_sync_status
                if sync.get("stale"):
                    parts.append(f"Index stale: {sync.get('total_stale', 0)} files")
                else:
                    parts.append("Index synced")
            elif project_index_db_path().exists():
                parts.append("Index ready")
            else:
                parts.append("Index missing")
        except Exception:
            pass

        try:
            parts.append(self.selected_mcphost_model().replace("ollama:", ""))
        except Exception:
            parts.append("Model")

        try:
            from tech_connector.services.app_context_service import active_app_context

            text = self.input.text() if hasattr(self, "input") else ""
            cursor_pos = self.input.cursorPosition() if hasattr(self, "input") else None
            app_context = active_app_context(text, cursor_pos)
            if app_context:
                parts.append(app_context.slash_token())
        except Exception:
            pass

        self.prompt_context_label.setText("Context: " + " • ".join(parts))

    def code_prompt_profile(self):
        """Return the current visible code-agent execution profile.

        :return: Normalized code-prompt profile.
        """

        from tech_connector.services.code_prompt_profile_service import (
            normalize_code_prompt_profile,
        )

        return normalize_code_prompt_profile(
            {
                "mode": (
                    self.code_prompt_mode_box.currentData()
                    if hasattr(self, "code_prompt_mode_box")
                    else self.settings.get("code_prompt_mode")
                ),
                "scope": (
                    self.code_prompt_scope_box.currentData()
                    if hasattr(self, "code_prompt_scope_box")
                    else self.settings.get("code_prompt_scope")
                ),
                "depth": (
                    self.code_prompt_depth_box.currentData()
                    if hasattr(self, "code_prompt_depth_box")
                    else self.settings.get("code_prompt_depth")
                ),
                "permission": (
                    self.code_prompt_permission_box.currentData()
                    if hasattr(self, "code_prompt_permission_box")
                    else self.settings.get("code_prompt_permission")
                ),
            },
            settings=self.settings,
        )

# Ctrl+S save shortcut installed by workflow mixin.
