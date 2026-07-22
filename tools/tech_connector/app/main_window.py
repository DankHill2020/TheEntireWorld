"""Main application window — thin orchestration layer.

This file composes focused MainWindow mixins extracted from the original
monolithic implementation.
"""

from .main_window_imports import *
from .main_window_core import MainWindowCoreMixin
from .main_window_editor import MainWindowEditorMixin
from .main_window_dcc import MainWindowDccMixin
from .main_window_chat_runtime import MainWindowChatRuntimeMixin
from .main_window_history_assets import MainWindowHistoryAssetsMixin
from .main_window_ui import MainWindowUiMixin
from .main_window_workflows import MainWindowWorkflowsMixin


class MainWindow(
    MainWindowUiMixin,
    MainWindowEditorMixin,
    MainWindowDccMixin,
    MainWindowChatRuntimeMixin,
    MainWindowHistoryAssetsMixin,
    MainWindowWorkflowsMixin,
    MainWindowCoreMixin,
    QWidget,
):
    """Primary IDE window. Delegates business logic to services and bridges."""

    dynamic_models_loaded = Signal(list)
    thread_log_message = Signal(str)
    live_process_update = Signal(str)
    response_started = Signal(str)
    dcc_statuses_ready = Signal(dict)
    vcs_status_ready = Signal(object)
    autocomplete_suggestions_ready = Signal(int, int, int, object)


# Backward-compatible alias for any external references to App
App = MainWindow


def show_main_window(win):
    """Show the main window in a normal, foreground-ready state."""
    try:
        win.showNormal()
    except Exception:
        win.show()
    try:
        win.raise_()
        win.activateWindow()
    except Exception:
        pass

if __name__ == "__main__":
    # Immediately kick off model warming in the background while GUI is initializing
    try:
        import threading

        from tech_connector.services.model_provider_service import should_use_local_runtime
        from tech_connector.services.ollama_service import warm_ollama_model
        from tech_connector.services.settings_service import load_settings

        settings = load_settings()
        warmed = set()
        for m in settings.get("ollama_preload_models") or ["qwen3:14b"]:
            if (
                    m
                    and m not in warmed
                    and provider_for_model(m) == "ollama"
                    and should_use_local_runtime(m, settings)
            ):
                warmed.add(m)
                t = threading.Thread(
                    target=warm_ollama_model, args=(m, "24h"), daemon=True
                )
                t.start()
        selected_for_policy = settings.get("model") or "ollama:qwen3:14b"
        if (
                not warmed
                and provider_for_model(selected_for_policy) == "ollama"
                and should_use_local_runtime(selected_for_policy, settings)
        ):
            t = threading.Thread(
                target=warm_ollama_model, args=("qwen3:14b", "24h"), daemon=True
            )
            t.start()
    except Exception:
        pass

    from tech_connector.app.application import run_application
    run_application()
