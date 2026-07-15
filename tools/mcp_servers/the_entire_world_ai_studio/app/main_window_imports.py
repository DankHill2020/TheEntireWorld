"""Main application window — thin orchestration layer."""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json
import re
import time
from datetime import datetime
from types import SimpleNamespace
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QPixmap,
    QTextCursor,
)
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
    QVBoxLayout,
    QWidget,
)
from . import main_utils
from editor.diff import apply_patch
from editor.editor_widget import CodeEditor
from editor.search import (
    comment_selection_python_style,
    duplicate_line,
    find_in_editor,
    trim_trailing_whitespace,
)
from knowledge.search import find_in_project, local_answer_about_file
from models.constants import (
    ANSI_RE,
    APP_DISPLAY_NAME,
    APP_SHORT_NAME,
    APP_VERSION,
    DCC_TOOL_PACKAGE_DIRS,
    DEFAULT_CONFIGS,
    DEFAULT_MODEL,
    HISTORY_DIR,
    IMAGE_DIR,
    LOGO_PATH,
    PRIME_PROMPT,
    TOOLS_ROOT,
    V2_DB,
)
from models.files import is_supported_code_file
from router.ai_router import AIRouter
from services.application_service import ApplicationService
from services.dcc_bridge_setup import (
    blender_script_editor_snippet,
    install_blender_startup_bridge,
    install_substance_painter_bridge,
    substance_painter_script_editor_snippet,
)
from services.model_provider_service import (
    PROVIDERS,
    credential_requirement_for_model,
    is_credit_or_quota_failure,
    provider_for_model,
    provider_setup_notes,
    provider_setup_url,
    resolve_model_for_policy,
)
from services.ollama_service import (
    AI_MODELS,
    FALLBACK_CODE_MODEL,
    FALLBACK_GENERAL_MODEL,
    ModelInstallWorker,
    as_mcphost_model,
    missing_required_models,
    warm_required_models_async,
)
from services.project_service import (
    folder_has_children,
    populate_folder_entries,
)
from services.settings_service import best_config
from services.unreal.graph_patch_service import build_patch, execute_patch
from services.update_service import GitUpdater
from ui.branding import application_stylesheet
from ui.first_run_dialog import FirstRunDialog
from ui.project_tree import (
    filter_tree_items,
    load_full_project_tree,
    load_lazy_roots,
    populate_folder_item,
)
from ui.status_bar import format_status_card
from ui.chat_worker_dialogs import ChatLogBrowser, WorkflowOutputSelectorDialog, CredentialsPromptDialog
from ui.unreal_editor_dialogs import UnrealOperationConfirmDialog, EditorDiffWidget, VCSWorker, WebImportDialog

try:
    from services.model_provider_service import should_use_local_runtime
except Exception:
    def should_use_local_runtime(model, settings):
        return True

from services.project_service import ProjectIntelligenceService
