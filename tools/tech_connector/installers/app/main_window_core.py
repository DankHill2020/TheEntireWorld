"""Extracted MainWindow methods. Generated from the uploaded monolithic file."""

import os
import sys
import threading
import time
from pathlib import Path

_ROOT = next(candidate for candidate in Path(__file__).resolve().parents if candidate.name.lower() == "tools")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import re
from datetime import datetime

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

from tech_connector.editor.editor_widget import CodeEditor

from tech_connector.models.constants import (
    APP_DISPLAY_NAME,
    APP_VERSION,
    LOGO_PATH,
    project_index_db_path,
)

from tech_connector.router.ai_router import AIRouter
from tech_connector.services.application_service import ApplicationService
from tech_connector.services.dcc.dcc_bridge_setup import (
    blender_script_editor_snippet,
    install_blender_startup_bridge,
    install_substance_painter_bridge,
    substance_painter_script_editor_snippet,
)
from tech_connector.services.dcc.installer_launchers import (
    pending_first_time_dcc_installers,
    run_first_time_dcc_installers,
)
from tech_connector.services.model_provider_service import (
    PROVIDERS,
    provider_for_model,
)
from tech_connector.services.ollama_service import (
    ModelInstallWorker,
    missing_required_models,
    warm_required_models_async,
)

from tech_connector.services.update_service import GitUpdater
from tech_connector.ui.branding import application_stylesheet

from tech_connector.ui.status_bar import format_status_card

_PROCESS_STATUS_CACHE = {}


def is_process_running(process_name: str) -> bool:
    import subprocess
    cache_key = process_name.lower()
    now = time.monotonic()
    cached = _PROCESS_STATUS_CACHE.get(cache_key)
    if cached and now - cached[0] < 2.0:
        return bool(cached[1])
    try:
        if os.name == "nt":
            output = subprocess.check_output(
                f'tasklist /NH /FI "IMAGENAME eq {process_name}"',
                shell=True,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
            ).decode("utf-8", errors="ignore")
            running = process_name.lower() in output.lower()
        else:
            output = subprocess.check_output(
                f'pgrep -f "{process_name}"',
                shell=True,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
            ).decode("utf-8", errors="ignore")
            running = bool(output.strip())
        _PROCESS_STATUS_CACHE[cache_key] = (now, running)
        return running
    except Exception:
        _PROCESS_STATUS_CACHE[cache_key] = (now, False)
        return False


try:
    from tech_connector.services.model_provider_service import should_use_local_runtime
except Exception:
    def should_use_local_runtime(model, settings):
        return True


class AppGitUpdateWorker(QThread):
    progress = Signal(str)
    finished = Signal(str, object)

    def __init__(self, mode, ref="", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.ref = ref

    def run(self):
        try:
            updater = GitUpdater(progress_cb=self.progress.emit)
            if self.mode == "latest":
                result = updater.update_latest()
            else:
                result = updater.update_ref(self.ref)
            self.finished.emit(self.mode, result)
        except Exception as exc:
            from tech_connector.services.update_service import UpdateResult

            self.finished.emit(self.mode, UpdateResult(ok=False, message=str(exc)))


class MainWindowCoreMixin:
    @property
    def code_editor(self) -> CodeEditor:
        widget = self.editor_tabs.currentWidget()
        if widget and isinstance(widget, CodeEditor):
            return widget
        return self.fallback_editor

    def __init__(self):
        super().__init__()

        self.service = ApplicationService()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} {APP_VERSION}")
        self.resize(1540, 960)

        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))

        self.service.bridge.output.connect(self.handle_output)
        self.service.bridge.exited.connect(self.on_finished)
        self.thread_log_message.connect(self.append)
        try:
            self.live_process_update.connect(self.set_live_process)
            self.response_started.connect(self._mark_response_started)
            self.dcc_statuses_ready.connect(self._apply_dcc_statuses)
            self.autocomplete_suggestions_ready.connect(self._apply_autocomplete_suggestions)
        except Exception:
            pass

        self._stream_buffer_by_role = {}
        self._stream_header_written = set()
        self._stream_flush_pending = set()
        self._stream_preview_content_by_role = {}
        self._stream_preview_render_pending = set()
        self._stream_plain_started_roles = set()
        self._stream_preview_base_html = ""
        self._stream_finalize_pending = set()
        self._raw_terminal_buffer_by_role = {}
        self._raw_terminal_flush_pending = set()

        self.settings = self.service.settings
        try:
            from tech_connector.services.project_service import ProjectIntelligenceService

            self.intel_service = ProjectIntelligenceService()
        except Exception:
            self.intel_service = None

        try:
            from tech_connector.services.version_control_service import apply_vcs_settings

            apply_vcs_settings(self.settings)
        except Exception:
            pass
        self.last_selected_model = self.settings.get(
            "model", "ollama:qwen2.5-coder:14b"
        )
        self._cached_discovered_symbols = []
        for env_key in ["GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            val = self.settings.get(env_key.lower())
            if val:
                os.environ[env_key] = val
                if env_key == "GEMINI_API_KEY":
                    os.environ["GOOGLE_API_KEY"] = val
        self.bridge = self.service.bridge
        self.mcphost_manager = self.service.mcphost_manager
        self.ai_router = AIRouter()
        self.command_router = self.service.command_router
        self.prompt_router = self.service.prompt_router
        self.output_cleaner = self.service.output_cleaner

        self.open_editors = {}
        self.fallback_editor = CodeEditor()

        self.current_session = self.service.current_session
        self.attached_images = self.service.attached_images
        self.chat_history_raw = ""
        self.chat_copy_blocks = []
        self.code_snippets = self.service.code_snippets
        self.last_user_prompt = self.service.last_user_prompt
        self.last_assistant_output = self.service.last_assistant_output
        self.last_tool_output = self.service.last_tool_output
        self._editor_syntax_suffix = ""
        self._chat_render_pending_bottom = True
        self._response_started_at_by_role = {}
        self._pending_response_metadata_by_role = {}
        self._active_response_addendum_counts = {}
        self._active_response_addendum_keys = set()
        self._last_request_metadata = None

        self._status_once = set()
        self._last_project_panel_width = 360
        self._last_live_process = ""
        self._last_live_process_at = 0.0
        self._startup_defer_expensive_status = True

        self.editor_status_timer = QTimer(self)
        self.editor_status_timer.setSingleShot(True)
        self.editor_status_timer.timeout.connect(self.update_editor_syntax_status)

        self.chat_render_timer = QTimer(self)
        self.chat_render_timer.setSingleShot(True)
        self.chat_render_timer.timeout.connect(self.render_chat_history)

        self._ui_heartbeat_last = time.time()
        self._ui_heartbeat_last_warning = 0.0
        self._ui_heartbeat_timer = QTimer(self)
        self._ui_heartbeat_timer.setInterval(500)
        self._ui_heartbeat_timer.timeout.connect(self._record_ui_heartbeat)
        self._ui_heartbeat_timer.start()
        self._start_ui_heartbeat_watchdog()

        self.build_ui()

        # Post-build UI polish: real menu bar, collapsible status, and
        # cleaner project-side controls. Kept outside build_ui() so the
        # existing monolithic layout can remain stable while UI pieces are
        # progressively extracted.
        try:
            from tech_connector.ui.window_layout_refactor import apply_main_window_layout_refinement
            apply_main_window_layout_refinement(self)
        except Exception as exc:
            print(f"[UI] Layout refinement failed: {exc}", flush=True)

        try:
            from tech_connector.ui.main_menu import install_main_menu
            install_main_menu(self)
        except Exception as exc:
            print(f"[UI] Menu install failed: {exc}", flush=True)

        self.setStyleSheet(application_stylesheet())
        self.install_prompt_context_hooks()

        self.update_initial_status_cards()
        self.status.setText("Loading workspace...")

        QTimer.singleShot(250, self.run_after_first_paint_startup)
        QTimer.singleShot(4500, self.ensure_required_models_on_startup)
        QTimer.singleShot(7000, self.ensure_dcc_bridge_setup_on_startup)

    def start_mobile_second_screen(self):
        try:
            try:
                self.service.command_service.desktop_window = self
            except Exception:
                pass
            url = self.service.start_remote_mobile_server()
            qr_url = self.service.remote_mobile_pairing_qr_url()
            download_qr_url = self.service.remote_mobile_download_qr_url()
            self.append(f"\n[Mobile Second Screen] Running at {url}\n")
            if qr_url:
                self.append(f"[Mobile Second Screen] Pairing QR: {qr_url}\n")
                QDesktopServices.openUrl(QUrl(qr_url))
            if download_qr_url:
                self.append(f"[Mobile Second Screen] Download QR: {download_qr_url}\n")
            QMessageBox.information(
                self,
                "Mobile Second Screen",
                "Open this URL on your phone or tablet while it is on the same network:\n\n"
                f"{url}\n\n"
                "A QR code has been opened in your browser for scanning.\n\n"
                f"Download QR:\n{download_qr_url}\n\n"
                "Keep the token private. Long-press in the mobile page for context actions.",
            )
            return url
        except Exception as exc:
            QMessageBox.warning(self, "Mobile Second Screen Failed", str(exc))
            self.append(f"\n[Mobile Second Screen Error] {exc}\n")
            return ""

    def stop_mobile_second_screen(self):
        try:
            self.service.stop_remote_mobile_server()
            self.append("\n[Mobile Second Screen] Stopped.\n")
        except Exception as exc:
            QMessageBox.warning(self, "Mobile Second Screen Failed", str(exc))

    def open_mobile_download_qr(self):
        try:
            try:
                self.service.command_service.desktop_window = self
            except Exception:
                pass
            self.service.start_remote_mobile_server()
            qr_url = self.service.remote_mobile_download_qr_url()
            if qr_url:
                self.append(f"\n[Mobile Second Screen] Download QR: {qr_url}\n")
                QDesktopServices.openUrl(QUrl(qr_url))
                return qr_url
            QMessageBox.warning(self, "Mobile Download QR", "Mobile second screen server is not available.")
        except Exception as exc:
            QMessageBox.warning(self, "Mobile Download QR Failed", str(exc))
            self.append(f"\n[Mobile Second Screen Error] {exc}\n")
        return ""

    def install_prompt_context_hooks(self):
        """Keep the unified prompt context label reactive as the user changes workspace state."""
        try:
            if hasattr(self, "workspace_tabs"):
                self.workspace_tabs.currentChanged.connect(lambda _idx: self.update_unified_prompt_context_label())
        except Exception:
            pass

    def _record_ui_heartbeat(self):
        self._ui_heartbeat_last = time.time()

    def _start_ui_heartbeat_watchdog(self):
        if getattr(self, "_ui_heartbeat_watchdog_started", False):
            return
        self._ui_heartbeat_watchdog_started = True

        def watch():
            while True:
                time.sleep(1.0)
                try:
                    last = float(getattr(self, "_ui_heartbeat_last", 0.0) or 0.0)
                    lag = time.time() - last
                    if lag < 3.0:
                        continue
                    previous = float(getattr(self, "_ui_heartbeat_last_warning", 0.0) or 0.0)
                    if time.time() - previous < 10.0:
                        continue
                    self._ui_heartbeat_last_warning = time.time()
                    stage = getattr(self, "_last_live_process", "") or "unknown"
                    message = (
                        f"\n[UI Watchdog] Main Qt heartbeat delayed {lag:.1f}s while active stage was: {stage}.\n"
                    )
                    print(message.strip(), flush=True)
                    try:
                        from tech_connector.services.diagnostic_service import log_ui_event

                        log_ui_event(
                            "ui_heartbeat_delayed",
                            enabled=bool(self.settings.get("ui_diagnostic_mode", False)),
                            lag_seconds=round(lag, 2),
                            stage=stage,
                        )
                    except Exception:
                        pass
                    try:
                        self.thread_log_message.emit(message)
                    except Exception:
                        pass
                except Exception:
                    pass

        threading.Thread(target=watch, daemon=True).start()
        try:
            if hasattr(self, "editor_tabs"):
                self.editor_tabs.currentChanged.connect(lambda _idx: self.update_unified_prompt_context_label())
        except Exception:
            pass
        try:
            if hasattr(self, "fallback_editor"):
                self.fallback_editor.cursorPositionChanged.connect(self.update_unified_prompt_context_label)
        except Exception:
            pass
        try:
            if hasattr(self, "update_unified_prompt_context_label"):
                QTimer.singleShot(0, self.update_unified_prompt_context_label)
        except Exception:
            pass

    def run_after_first_paint_startup(self):
        self._startup_defer_expensive_status = False
        self._schedule_startup_step("history", 0, self.refresh_history)
        self._schedule_startup_step("snippets", 150, self.refresh_snippets_list)
        self._schedule_startup_step("project tree", 350, self.load_project_tree_lazy)
        self._schedule_startup_step("editor restore", 700, self.restore_editor_state)
        self._schedule_startup_step("integration status", 1100, self.update_integrations_status_card)
        self._schedule_startup_step("vcs status", 1500, self.update_vcs_status_card)
        self._schedule_startup_step("symbol cache", 2400, self.start_async_symbol_indexing)
        self.status.setText("Ready")
        if not self.settings.get("first_run_complete"):
            QTimer.singleShot(1800, self.show_first_run)
        elif not project_index_db_path().exists():
            self.set_card("knowledge", "warn", "Index missing")
            if hasattr(self, "index_status"):
                self.index_status.setText("Knowledge: index missing")
        QTimer.singleShot(5200, self.start_mcphost)
        QTimer.singleShot(8500, self.start_unreal_daemon_on_startup)

        self.keep_alive_timer = QTimer(self)
        self.keep_alive_timer.timeout.connect(self.keep_ollama_warm)
        self.keep_alive_timer.start(240000)

        try:
            from tech_connector.models.project import project_roots
            from tech_connector.services.project_service import start_project_index_change_watcher

            self._project_index_change_watcher = start_project_index_change_watcher(
                project_roots(self.settings)
            )
        except Exception:
            self._project_index_change_watcher = None

    def _schedule_startup_step(self, label, delay_ms, fn):
        def run_step():
            started = time.monotonic()
            try:
                fn()
            finally:
                duration_ms = int((time.monotonic() - started) * 1000)
                if duration_ms >= 250:
                    try:
                        from tech_connector.services.diagnostic_service import log_ui_event

                        log_ui_event(
                            "startup_step_slow",
                            enabled=bool(self.settings.get("ui_diagnostic_mode", False)),
                            label=label,
                            duration_ms=duration_ms,
                        )
                    except Exception:
                        pass

        QTimer.singleShot(int(delay_ms), run_step)

    def start_unreal_daemon_on_startup(self):
        try:
            daemon_cfg = self.settings.get("daemon", {})
            if not (isinstance(daemon_cfg, dict) and daemon_cfg.get("auto_start")):
                return
            if not self.intel_service:
                return
            roots = self.project_roots()
            if not roots:
                return

            import threading

            def run():
                ok, msg = self.intel_service.start_daemon(roots[0])

                def apply_result(ok=ok, msg=msg):
                    self.update_dcc_statuses()
                    if not ok:
                        self.append(f"\n[Unreal Indexer] Auto-start failed: {msg}\n")

                QTimer.singleShot(0, apply_result)

            threading.Thread(target=run, daemon=True).start()
        except Exception:
            pass

    def keep_ollama_warm(self):
        import threading

        from tech_connector.services.ollama_service import warm_ollama_model

        model = self.selected_mcphost_model()
        if (
                model
                and provider_for_model(model) == "ollama"
                and should_use_local_runtime(model, self.settings)
        ):
            t = threading.Thread(
                target=warm_ollama_model, args=(model, "24h"), daemon=True
            )
            t.start()

    def dcc_bridge_setup_ids(self):
        return {
            "blender": "Blender",
            "substance_painter": "Substance Painter",
        }

    def mark_dcc_bridge_setup_seen(self, bridge_id):
        seen = set(self.settings.get("dcc_bridge_setup_seen", []))
        if bridge_id in seen:
            return
        seen.add(bridge_id)
        self.settings["dcc_bridge_setup_seen"] = sorted(seen)
        self.service.settings["dcc_bridge_setup_seen"] = self.settings[
            "dcc_bridge_setup_seen"
        ]
        self.service.save_settings()

    def ensure_dcc_bridge_setup_on_startup(self):
        if not self.settings.get("first_run_complete"):
            self.start_dcc_status_polling()
            return

        try:
            self.confirm_and_run_first_time_dcc_installers()
        except Exception as exc:
            self.append(f"\n[DCC Setup] First-time installer launch failed: {exc}\n")

        setup_ids = self.dcc_bridge_setup_ids()
        seen = set(self.settings.get("dcc_bridge_setup_seen", []))
        pending = [bridge_id for bridge_id in setup_ids if bridge_id not in seen]
        if not pending:
            self.start_dcc_status_polling()
            return

        restart_messages = []

        if "blender" in pending:
            result = install_blender_startup_bridge(all_versions=True)
            self.mark_dcc_bridge_setup_seen("blender")
            if result.ok and result.installed_versions:
                versions = ", ".join(result.installed_versions)
                self.set_card("blender", "warn", "Restart Blender")
                self.append(
                    f"\n[Blender Setup] Installed startup bridge for Blender {versions}. Restart Blender to load it.\n"
                )
                restart_messages.append(
                    f"Blender: restart Blender. Version(s): {versions}"
                )
            elif not result.ok:
                self.set_card("blender", "off", "Setup available")
                self.append(f"\n[Blender Setup] {result.message}\n")

        if "substance_painter" in pending:
            substance_result = install_substance_painter_bridge()
            self.mark_dcc_bridge_setup_seen("substance_painter")
            if substance_result.ok and substance_result.installed_versions:
                self.set_card("substance_painter", "warn", "Restart Painter")
                self.append(
                    "\n[Substance Painter Setup] Installed startup bridge plugin. "
                    "Restart Substance Painter and enable the plugin if prompted.\n"
                )
                restart_messages.append(
                    "Substance Painter: restart Painter. If needed, enable the plugin from its Python/plugins menu."
                )
            elif not substance_result.ok:
                self.set_card("substance_painter", "off", "Setup available")
                self.append(f"\n[Substance Painter Setup] {substance_result.message}\n")

        if restart_messages:
            QMessageBox.information(
                self,
                "DCC Bridge Setup Updated",
                "Tech Connector installed or updated bridge startup files.\n\n"
                + "\n".join(restart_messages),
            )

        # Check running statuses and start dynamic polling
        self.start_dcc_status_polling()

    def start_dcc_status_polling(self):
        if getattr(self, "_dcc_status_polling_started", False):
            self.update_dcc_statuses()
            return
        self._dcc_status_polling_started = True
        self.update_dcc_statuses()
        self.status_poll_timer = QTimer(self)
        self.status_poll_timer.timeout.connect(self.update_dcc_statuses)
        self.status_poll_timer.start(10000)

    def confirm_and_run_first_time_dcc_installers(self):
        pending = pending_first_time_dcc_installers(self.settings)
        if not pending:
            return []

        reply = QMessageBox.question(
            self,
            "Install DCC Tools?",
            "Tech Connector found installed DCC applications that need one-time tool setup:\n\n"
            + "\n".join(f"- {launcher.display_name}" for launcher in pending)
            + "\n\nThis may launch installer .bat files or start the DCC application briefly to configure startup hooks."
            + "\nIf any listed application is already open, close and reopen it after setup so the new hooks load.\n\n"
            + "Install these tools now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            self.append(
                "\n[DCC Setup] User skipped first-time tool installation for: "
                + ", ".join(launcher.display_name for launcher in pending)
                + ".\n"
            )
            return []

        launched = run_first_time_dcc_installers(
            self.settings, self.service.save_settings, pending
        )
        if launched:
            names = ", ".join(launcher.display_name for launcher in launched)
            self.append(
                "\n[DCC Setup] Ran first-time installer launchers for: "
                f"{names}.\n"
                "[DCC Setup] If any of those applications were already open, "
                "close and reopen them so startup hooks are loaded.\n"
            )
            QMessageBox.information(
                self,
                "DCC Setup Started",
                "Tech Connector ran first-time setup for:\n\n"
                + "\n".join(f"- {launcher.display_name}" for launcher in launched)
                + "\n\nIf any of those applications were already open, close and reopen them.",
            )
        return launched

    def update_dcc_statuses(self):
        import threading

        if hasattr(self, "_dcc_poll_thread") and self._dcc_poll_thread.is_alive():
            return

        def bridge_port(host: str, fallback_factory=None):
            bridge = None
            try:
                router = getattr(self, "command_router", None)
                bridge = getattr(router, host, None) if router is not None else None
                if bridge is None and hasattr(router, "_host_bridge_for_operation"):
                    bridge = router._host_bridge_for_operation(host)
            except Exception:
                bridge = None
            if bridge is None and callable(fallback_factory):
                try:
                    bridge = fallback_factory()
                except Exception:
                    bridge = None
            if bridge is None or not hasattr(bridge, "find_port"):
                return None
            try:
                return bridge.find_port()
            except Exception:
                return None

        def run_polling():
            statuses = {}

            # 1. Maya
            try:
                from tech_connector.bridges.maya.maya_bridge import MayaBridge

                maya_bridge = MayaBridge()
                maya_ports = maya_bridge.find_ports()
                if len(maya_ports) > 1:
                    statuses["maya"] = ("warn", f"{len(maya_ports)} sessions: " + ", ".join(f":{port}" for port in maya_ports[:3]))
                elif maya_ports:
                    statuses["maya"] = ("ok", f"Connected :{maya_ports[0]}")
                else:
                    if is_process_running("maya.exe"):
                        statuses["maya"] = ("warn", "Open (Bridge offline)")
                    else:
                        statuses["maya"] = ("unknown", "Not running")
            except Exception:
                statuses["maya"] = ("unknown", "Not running")

            # 2. Unreal
            try:
                from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

                unreal_port = bridge_port("unreal", UnrealBridge)
                
                # Check daemon status
                daemon_info = ""
                try:
                    if hasattr(self, "intel_service") and self.intel_service:
                        stat = self.intel_service.get_status()
                        if stat:
                            indexed = stat.get("indexed_assets", 0)
                            daemon_info = f" | {indexed} assets"
                except Exception:
                    pass

                if unreal_port:
                    statuses["unreal"] = ("ok", f"Connected :{unreal_port}{daemon_info}")
                else:
                    if is_process_running("UnrealEditor.exe") or is_process_running("UE4Editor.exe"):
                        statuses["unreal"] = ("warn", f"Open (Bridge offline){daemon_info}")
                    else:
                        statuses["unreal"] = ("unknown", "Not running")
            except Exception:
                statuses["unreal"] = ("unknown", "Not running")

            # 3. Blender
            try:
                from tech_connector.bridges.blender.blender_bridge import BlenderBridge

                blender_port = bridge_port("blender", BlenderBridge)
                if blender_port:
                    statuses["blender"] = ("ok", f"Connected :{blender_port}")
                else:
                    if is_process_running("blender.exe"):
                        statuses["blender"] = ("warn", "Open (Bridge offline)")
                    else:
                        from installers.install_blender_bridge import (
                            blender_user_root,
                            select_versions,
                            version_needs_install,
                        )

                        root = blender_user_root()
                        versions = select_versions(root, all_versions=True)
                        needs_setup = False
                        for v in versions:
                            if version_needs_install(root / v):
                                needs_setup = True
                                break
                        statuses["blender"] = (
                            ("off", "Setup available")
                            if needs_setup
                            else ("unknown", "Not running")
                        )
            except Exception:
                statuses["blender"] = ("unknown", "Not running")

            # 4. MotionBuilder
            try:
                from tech_connector.bridges.motionbuilder.motionbuilder_bridge import (
                    MotionBuilderBridge,
                )

                mb_port = bridge_port("motionbuilder", MotionBuilderBridge)
                if mb_port:
                    statuses["motionbuilder"] = ("ok", f"Connected :{mb_port}")
                elif is_process_running("motionbuilder.exe"):
                    statuses["motionbuilder"] = ("warn", "Open (Bridge offline)")
                else:
                    statuses["motionbuilder"] = ("off", "Optional")
            except Exception:
                statuses["motionbuilder"] = ("off", "Optional")

            # 5. Substance Painter
            try:
                from tech_connector.bridges.substance_painter.substance_painter_bridge import (
                    SubstancePainterBridge,
                )

                substance_port = bridge_port("substance_painter", SubstancePainterBridge)
                if substance_port:
                    statuses["substance_painter"] = (
                        "ok",
                        f"Connected :{substance_port}",
                    )
                else:
                    if (is_process_running("Substance Painter.exe") or 
                        is_process_running("Adobe Substance 3D Painter.exe") or 
                        is_process_running("painter.exe")):
                        statuses["substance_painter"] = ("warn", "Open (Bridge offline)")
                    else:
                        from tech_connector.bridges.substance_painter.install_substance_painter_bridge import (
                            default_plugin_dir,
                            plugin_needs_install,
                        )

                        plugin_dir = default_plugin_dir()
                        if plugin_needs_install(plugin_dir):
                            statuses["substance_painter"] = ("off", "Setup available")
                        else:
                            statuses["substance_painter"] = ("unknown", "Not running")
            except Exception:
                statuses["substance_painter"] = ("unknown", "Not running")

            # 6. Unity
            try:
                from tech_connector.bridges.unity.unity_bridge import UnityBridge

                unity_port = bridge_port("unity", UnityBridge)
                if unity_port:
                    statuses["unity"] = ("ok", f"Connected :{unity_port}")
                elif is_process_running("Unity.exe"):
                    statuses["unity"] = ("warn", "Open (Bridge offline)")
                else:
                    statuses["unity"] = ("unknown", "Not running")
            except Exception:
                statuses["unity"] = ("unknown", "Not running")

            try:
                self.dcc_statuses_ready.emit(statuses)
            except Exception:
                pass

        self._dcc_poll_thread = threading.Thread(target=run_polling, daemon=True)
        self._dcc_poll_thread.start()

    def _apply_dcc_statuses(self, statuses):
        for key, (state, detail) in statuses.items():
            self.set_card(key, state, detail)
        unreal_state, unreal_detail = statuses.get("unreal", ("unknown", ""))
        self.maybe_auto_snapshot_unreal(unreal_state, unreal_detail)
        self.maybe_auto_reflect_unreal(unreal_state, unreal_detail)

        # Check daemon state directly to toggle button
        daemon_active = False
        try:
            if hasattr(self, "intel_service") and self.intel_service:
                daemon_active = self.intel_service.is_daemon_running()
        except Exception:
            pass

        if hasattr(self, "daemon_toggle_btn") and self.daemon_toggle_btn:
            if daemon_active:
                self.daemon_toggle_btn.setText("Stop Unreal Indexer")
                self.daemon_scan_btn.setEnabled(True)
                if hasattr(self, "unreal_docs_btn") and self.unreal_docs_btn:
                    self.unreal_docs_btn.setEnabled(True)
            else:
                self.daemon_toggle_btn.setText("Start Unreal Indexer")
                self.daemon_scan_btn.setEnabled(False)
                if hasattr(self, "unreal_docs_btn") and self.unreal_docs_btn:
                    self.unreal_docs_btn.setEnabled(False)

    def maybe_auto_snapshot_unreal(self, state, detail):
        if state != "ok":
            self._last_unreal_snapshot_port = None
            return
        match = re.search(r":(\d+)", detail or "")
        port = match.group(1) if match else "default"
        if getattr(self, "_unreal_snapshot_running", False):
            return
        if getattr(self, "_last_unreal_snapshot_port", None) == port:
            return
        self._last_unreal_snapshot_port = port
        self._unreal_snapshot_running = True
        self.set_card("unreal", "busy", "Snapshotting")
        if hasattr(self, "live_process_label"):
            self.live_process_label.setText(f"Working: Unreal snapshot cache on port {port}")

        import threading

        def run_snapshot():
            label, ok, result = self.command_router.execute_unreal_operation(
                "project.snapshot", {"directory": "/Game/"}
            )
            QTimer.singleShot(
                0, lambda: self.on_unreal_auto_snapshot_finished(label, ok, result)
            )

        threading.Thread(target=run_snapshot, daemon=True).start()

    def on_unreal_auto_snapshot_finished(self, label, ok, result):
        self._unreal_snapshot_running = False
        self.unreal_project_snapshot = result
        self.last_tool_output = result
        self.last_assistant_output = result
        if ok:
            self.set_card("unreal", "ok", "Snapshot ready")
        else:
            self.set_card("unreal", "warn", "Snapshot partial")
            self.append(
                f"[{label}] Snapshot completed with warnings/errors. Cached partial data:\n{result}\n"
            )

    def maybe_auto_reflect_unreal(self, state, detail):
        if state != "ok":
            self._last_unreal_reflection_port = None
            return
        match = re.search(r":(\d+)", detail or "")
        port = match.group(1) if match else "default"
        if getattr(self, "_unreal_reflection_running", False):
            return
        if getattr(self, "_last_unreal_reflection_port", None) == port:
            return
        self._last_unreal_reflection_port = port
        self._unreal_reflection_running = True
        self.set_card("unreal", "busy", "Reflecting API")
        if hasattr(self, "live_process_label"):
            self.live_process_label.setText(f"Working: Unreal API metadata cache on port {port}")

        import threading

        def run_reflection():
            result = {"success": False, "error": "Reflection did not run."}
            try:
                roots = self.project_roots() if hasattr(self, "project_roots") else []
                root = roots[0] if roots else None
                if not hasattr(self, "intel_service") or not self.intel_service:
                    from tech_connector.services.project_service import ProjectIntelligenceService

                    self.intel_service = ProjectIntelligenceService(project_root=root)
                ok, message = self.intel_service.ensure_running(root)
                if ok:
                    result = self.intel_service.refresh_unreal_reflection(timeout=60.0) or {
                        "success": False,
                        "error": self.intel_service.last_error or "Reflection daemon request failed.",
                    }
                else:
                    result = {"success": False, "error": message}
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            QTimer.singleShot(0, lambda: self.on_unreal_auto_reflection_finished(result))

        threading.Thread(target=run_reflection, daemon=True).start()

    def on_unreal_auto_reflection_finished(self, result):
        self._unreal_reflection_running = False
        self.update_dcc_statuses()
        if result and result.get("success"):
            counts = ((result.get("persisted") or {}).get("counts") or {})
            api_count = counts.get("python_api", 0)
            function_count = counts.get("functions", 0)
            self.set_card("unreal", "ok", f"API {api_count}/{function_count}")
        else:
            error = (result or {}).get("error") or "Unknown reflection indexing error."
            self.append(f"[Unreal Reflection] Indexing skipped or failed: {error}\n")

    def install_blender_bridge_from_menu(self):
        result = install_blender_startup_bridge(all_versions=True)
        self.mark_dcc_bridge_setup_seen("blender")
        if result.ok and result.installed_versions:
            versions = ", ".join(result.installed_versions)
            self.set_card("blender", "warn", "Restart Blender")
            self.append(
                f"\n[Blender Setup] Installed startup bridge for Blender {versions}. Restart Blender to load it.\n"
            )
            QMessageBox.information(
                self,
                "Blender Bridge Installed",
                f"Installed the Blender startup bridge for: {versions}\n\nRestart Blender to load it.",
            )
            return

        if result.ok:
            QMessageBox.information(self, "Blender Bridge", result.message)
            self.append(f"\n[Blender Setup] {result.message}\n")
            return

        QMessageBox.warning(
            self,
            "Blender Bridge Setup",
            result.message
            + "\n\nYou can also copy the Script Editor setup snippet from Tools > Blender.",
        )
        self.append(f"\n[Blender Setup] {result.message}\n")

    def copy_blender_script_editor_setup(self):
        snippet = blender_script_editor_snippet()
        QGuiApplication.clipboard().setText(snippet)
        self.append(
            "\n[Blender Setup] Copied Blender Script Editor setup snippet to clipboard.\n"
        )
        QMessageBox.information(
            self,
            "Blender Setup Snippet Copied",
            "Paste the snippet into Blender's Scripting workspace and press Run Script.\n\n"
            "It installs the startup bridge and starts the bridge for the current Blender session.",
        )

    def install_substance_painter_bridge_from_menu(self):
        result = install_substance_painter_bridge()
        self.mark_dcc_bridge_setup_seen("substance_painter")
        if result.ok and result.installed_versions:
            self.set_card("substance_painter", "warn", "Restart Painter")
            self.append(
                "\n[Substance Painter Setup] Installed bridge plugin. Restart Painter to load it.\n"
            )
            QMessageBox.information(
                self,
                "Substance Painter Bridge Installed",
                "Installed the Substance Painter bridge plugin.\n\n"
                "Restart Substance Painter. If needed, enable the plugin from its Python/plugins menu.",
            )
            return

        if result.ok:
            QMessageBox.information(self, "Substance Painter Bridge", result.message)
            self.append(f"\n[Substance Painter Setup] {result.message}\n")
            return

        QMessageBox.warning(
            self,
            "Substance Painter Bridge Setup",
            result.message
            + "\n\nYou can also copy the setup snippet from Tools > Substance Painter.",
        )
        self.append(f"\n[Substance Painter Setup] {result.message}\n")

    def copy_substance_painter_script_editor_setup(self):
        snippet = substance_painter_script_editor_snippet()
        QGuiApplication.clipboard().setText(snippet)
        self.append("\n[Substance Painter Setup] Copied setup snippet to clipboard.\n")
        QMessageBox.information(
            self,
            "Substance Painter Setup Snippet Copied",
            "Paste the snippet into Substance Painter's Python console/script editor and run it.\n\n"
            "It installs the plugin and starts the bridge for the current Painter session.",
        )

    def show_update_result(self, title, result):
        text = result.message
        if result.output:
            text += "\n\n" + result.output
        if result.restart_required:
            text += "\n\nRestart Tech Connector to finish using the updated code."

        self.append(f"\n[App Updates] {text}\n")
        if result.ok:
            QMessageBox.information(self, title, text)
        else:
            QMessageBox.warning(self, title, text)

    def check_app_update_status(self):
        result = GitUpdater().status()
        self.show_update_result("Git Status", result)

    def update_app_from_latest(self):
        reply = QMessageBox.question(
            self,
            "Update from Latest",
            "Update Tech Connector from the latest upstream Git commit?\n\n"
            "This will run git fetch and git pull --ff-only. It will stop if local files have changes.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.start_git_update_worker("latest")

    def update_app_from_git_ref(self):
        ref, ok = QInputDialog.getText(
            self,
            "Update from Git Ref",
            "Enter a branch, tag, or commit SHA:",
        )
        if not ok:
            return

        ref = ref.strip()
        if not ref:
            QMessageBox.information(self, "Update from Git Ref", "No Git ref entered.")
            return

        reply = QMessageBox.question(
            self,
            "Update from Git Ref",
            f"Update Tech Connector to this Git ref?\n\n{ref}\n\n"
            "This will run git fetch and git checkout. It will stop if local files have changes.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.start_git_update_worker("ref", ref=ref)

    def start_git_update_worker(self, mode, ref=""):
        title = "Update from Latest" if mode == "latest" else "Update from Git Ref"
        progress = QProgressDialog("Starting Git update...", "", 0, 0, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()

        worker = AppGitUpdateWorker(mode, ref=ref, parent=self)
        self._app_git_update_worker = worker
        self._app_git_update_progress = progress
        worker.progress.connect(lambda message: progress.setLabelText(message))
        worker.finished.connect(self.on_git_update_finished)
        worker.start()

    def on_git_update_finished(self, mode, result):
        progress = getattr(self, "_app_git_update_progress", None)
        if progress is not None:
            progress.close()
        self._app_git_update_progress = None
        worker = getattr(self, "_app_git_update_worker", None)
        if worker is not None:
            worker.deleteLater()
        self._app_git_update_worker = None
        title = "Update from Latest" if mode == "latest" else "Update from Git Ref"
        self.show_update_result(title, result)

    def ensure_required_models_on_startup(self):
        if not should_use_local_runtime(self.selected_mcphost_model(), self.settings):
            self.set_card("ollama", "off", "Cloud selected")
            return

        import threading

        self.set_card("ollama", "busy", "Checking models")

        def run_check():
            try:
                missing = missing_required_models()
            except Exception:
                missing = None

            QTimer.singleShot(
                0, lambda missing=missing: self.on_required_models_checked(missing)
            )

        threading.Thread(target=run_check, daemon=True).start()

    def on_required_models_checked(self, missing):
        if missing is None:
            self.set_card("ollama", "warn", "Check failed")
            return

        if not missing:
            self.set_card("ollama", "ok", "Models ready")
            QTimer.singleShot(1000, warm_required_models_async)
            return

        reply = QMessageBox.question(
            self,
            "Install Required Ollama Models",
            "Tech Connector needs these local models:\n\n"
            + "\n".join(missing)
            + "\n\nInstall them now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if reply != QMessageBox.Yes:
            self.set_card("ollama", "warn", f"Missing {len(missing)} model(s)")
            self.append("\n[Ollama] Model install skipped.\n")
            return

        self.show_model_install_dialog(missing)

    def show_model_install_dialog(self, models):
        self.model_install_dialog = QDialog(self)
        self.model_install_dialog.setWindowTitle("Installing Ollama Models")
        self.model_install_dialog.resize(700, 220)

        layout = QVBoxLayout(self.model_install_dialog)

        self.model_install_label = QLabel(
            "Installing required local AI models...\n\n" + "\n".join(models)
        )
        self.model_install_label.setWordWrap(True)
        layout.addWidget(self.model_install_label)

        self.model_install_progress = QProgressBar()
        self.model_install_progress.setRange(0, 100)
        self.model_install_progress.setValue(0)
        layout.addWidget(self.model_install_progress)

        self.model_install_log = QPlainTextEdit()
        self.model_install_log.setReadOnly(True)
        self.model_install_log.setMaximumHeight(100)
        layout.addWidget(self.model_install_log)

        self.set_card("ollama", "busy", "Installing models")

        self.model_install_worker = ModelInstallWorker(models)
        self.model_install_worker.output.connect(self.on_model_install_output)
        self.model_install_worker.progress.connect(self.on_model_install_progress)
        self.model_install_worker.finished_ok.connect(
            self.on_startup_model_install_finished
        )
        self.model_install_worker.start()

        self.model_install_dialog.show()

    def on_model_install_progress(self, value):
        if hasattr(self, "model_install_progress"):
            self.model_install_progress.setRange(0, 100)
            self.model_install_progress.setValue(value)

    def on_startup_model_install_finished(self, ok, message):
        self.append(f"\n[Ollama] {message}\n")

        if hasattr(self, "model_install_progress"):
            self.model_install_progress.setRange(0, 100)
            self.model_install_progress.setValue(100 if ok else 0)

        if hasattr(self, "model_install_label"):
            self.model_install_label.setText(message)

        self.set_card(
            "ollama",
            "ok" if ok else "bad",
            "Models ready" if ok else "Install failed",
        )

        if ok:
            QTimer.singleShot(1000, warm_required_models_async)
            QTimer.singleShot(1200, self.model_install_dialog.accept)

    def all_roots(self):
        return self.service.all_roots()

    def project_roots(self):
        return self.service.project_roots()

    def set_card(self, key, state, detail=""):
        card = getattr(self, "status_cards", {}).get(key)
        if not card:
            return
        text, stylesheet = format_status_card(key, state, detail)
        try:
            card.setTextFormat(Qt.RichText)
        except Exception:
            pass
        card.setText(text)
        try:
            from tech_connector.models.constants import STATUS_CARD_LABELS

            label = STATUS_CARD_LABELS.get(key, key)
            is_unchecked = (
                state == "unknown" 
                or not detail 
                or "not checked" in detail.lower() 
                or "not checked" in state.lower()
            )
            if is_unchecked:
                card.setToolTip(f"{label}: Not checked")
            else:
                card.setToolTip(f"{label}: {detail or state.title()}")
        except Exception:
            pass
        card.setStyleSheet(stylesheet)

    def set_ollama_card_for_model(self, state, model, cloud_detail="Cloud selected"):
        if provider_for_model(model) == "ollama":
            self.set_card("ollama", state, model)
        else:
            self.set_card("ollama", "off", cloud_detail)

    def source_mode_label(self):
        if hasattr(self, "model_source_mode_box"):
            label = self.model_source_mode_box.currentText().strip()
            if label:
                return label
        mode = self.settings.get("model_source_mode", "auto_with_local_fallback")
        return (
            "Auto cloud -> local"
            if mode == "auto_with_local_fallback"
            else "Always local"
        )

    def model_display_parts(self, model):
        raw = (model or "").strip()
        provider_id = provider_for_model(raw)
        provider = PROVIDERS.get(provider_id)
        provider_name = provider.display_name if provider else provider_id.title()
        model_name = raw
        prefix = f"{provider_id}:"
        if raw.lower().startswith(prefix):
            model_name = raw.split(":", 1)[1]
        return provider_name, model_name, raw

    def update_active_response_model_label(
            self, model=None, routing_mode=None, fallback_used=False, fallback_model=None
    ):
        if not hasattr(self, "active_model_label"):
            return
        model = model or self.selected_mcphost_model()
        provider_name, model_name, _raw = self.model_display_parts(model)
        routing_mode = routing_mode or self.source_mode_label()
        text = f"Routing mode: {routing_mode}    Active response model: {provider_name} / {model_name}"
        if fallback_used and fallback_model:
            fb_provider, fb_model, _ = self.model_display_parts(fallback_model)
            text += f"    Fallback used: {fb_provider} / {fb_model}"
        self.active_model_label.setText(text)

    def dcc_connection_label(self, task_role):
        task_role = (task_role or "").lower()
        if task_role == "unreal":
            if getattr(self, "unreal_project_snapshot", ""):
                return "unreal_snapshot_available"
            card = getattr(self, "status_cards", {}).get("unreal")
            if card and "ok" in card.styleSheet():
                return "unreal_connected"
            return "unreal_not_confirmed"
        if task_role == "maya":
            card = getattr(self, "status_cards", {}).get("maya")
            return (
                "maya_connected"
                if card and "ok" in card.styleSheet()
                else "maya_not_confirmed"
            )
        return "none"

    def build_request_metadata(
            self,
            text,
            prepared_text,
            route,
            role,
            active_model,
            fallback_used=False,
            fallback_error="",
    ):
        selected_model = self.selected_mcphost_model()
        selected_provider, selected_model_name, selected_raw = self.model_display_parts(
            selected_model
        )
        active_provider, active_model_name, active_raw = self.model_display_parts(
            active_model
        )
        task_type = getattr(route, "task_role", "") or role or "general"
        prepared_lower = (prepared_text or "").lower()
        context_markers = (
            "senior principal",
            "previous ai work",
            "locked knowledge",
            "dcc context",
            "dcc tool",
            "project snapshot",
            "unreal project",
            "maya project",
        )
        project_intelligence_used = any(
            marker in prepared_lower for marker in context_markers
        )
        dcc_connection = self.dcc_connection_label(task_type)
        dcc_context_used = task_type in {
            "unreal",
            "maya",
            "blender",
            "substance_painter",
            "motionbuilder",
        } and (
                                   project_intelligence_used
                                   or dcc_connection
                                   not in {"none", "unreal_not_confirmed", "maya_not_confirmed"}
                           )
        capabilities = []
        if project_index_db_path().exists():
            capabilities.append("knowledge_index")
        if dcc_context_used:
            capabilities.append(f"{task_type}_context")
        if getattr(route, "reason", ""):
            capabilities.append("model_router")
        metadata = {
            "routing_mode": self.source_mode_label(),
            "selected_provider": selected_provider,
            "selected_model": selected_model_name,
            "selected_raw_model": selected_raw,
            "active_provider": active_provider,
            "active_model": active_model_name,
            "active_raw_model": active_raw,
            "fallback_used": bool(fallback_used),
            "fallback_error": fallback_error,
            "knowledge_index_ready": project_index_db_path().exists(),
            "project_intelligence_used": project_intelligence_used,
            "dcc_context_used": dcc_context_used,
            "dcc_connection": dcc_connection,
            "task_type": task_type,
            "session_role": role or "main",
            "capabilities_used": capabilities,
            "router_reason": getattr(route, "reason", ""),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            prompt_route_decision = getattr(self, "_last_prompt_route_decision", None) or {}
            if isinstance(prompt_route_decision, dict):
                metadata["prompt_route_decision"] = {
                    "route": prompt_route_decision.get("route", ""),
                    "provider": prompt_route_decision.get("provider", ""),
                    "intent_category": prompt_route_decision.get("intent_category", ""),
                    "host": prompt_route_decision.get("host", ""),
                    "execution_route": prompt_route_decision.get("execution_route", ""),
                    "confidence": prompt_route_decision.get("confidence", 0),
                    "requires_confirmation": prompt_route_decision.get("requires_confirmation", False),
                    "required_context": list(prompt_route_decision.get("required_context") or [])[:8],
                    "reasons": list(prompt_route_decision.get("reasons") or [])[:4],
                }
                analysis = prompt_route_decision.get("senior_prompt_analysis") or {}
                metadata["senior_prompt_analysis"] = {
                    "primary_objective": analysis.get("primary_objective", ""),
                    "intent_category": analysis.get("intent_category", ""),
                    "affected_subsystems": list(analysis.get("affected_subsystems") or [])[:6],
                    "required_context": list(analysis.get("required_context") or [])[:8],
                    "code_modification_required": bool(analysis.get("code_modification_required", False)),
                    "runtime_execution_required": bool(analysis.get("runtime_execution_required", False)),
                    "confirmation_requirements": list(analysis.get("confirmation_requirements") or [])[:4],
                }
                progress = prompt_route_decision.get("visible_progress") or {}
                metadata["visible_progress"] = {
                    "route": progress.get("route", ""),
                    "host": progress.get("host", ""),
                    "background_worker_required": bool(progress.get("background_worker_required", False)),
                    "stage_model": progress.get("stage_model", ""),
                    "stages": [
                        {
                            "state": stage.get("state", ""),
                            "label": stage.get("label", ""),
                            "expert_id": stage.get("expert_id", ""),
                            "percent": stage.get("percent", 0),
                            "status": stage.get("status", ""),
                        }
                        for stage in list(progress.get("stages") or [])[:5]
                        if isinstance(stage, dict)
                    ],
                }
                gap_plan = prompt_route_decision.get("capability_gap_plan") or {}
                metadata["capability_gap_plan"] = {
                    "framework": gap_plan.get("framework", ""),
                    "goal": gap_plan.get("goal", ""),
                    "next_action": gap_plan.get("next_action", ""),
                    "matched_patterns": list(gap_plan.get("matched_patterns") or [])[:6],
                    "missing_links": [
                        {
                            "label": link.get("label", ""),
                            "status": link.get("status", ""),
                            "requires": list(link.get("requires") or [])[:4],
                        }
                        for link in list(gap_plan.get("missing_links") or [])[:8]
                        if isinstance(link, dict)
                    ],
                    "resolution_options": [
                        {
                            "label": option.get("label", ""),
                            "confidence": option.get("confidence", 0),
                        }
                        for option in list(gap_plan.get("resolution_options") or [])[:4]
                        if isinstance(option, dict)
                    ],
                    "planned_actions": list(gap_plan.get("planned_actions") or [])[:5],
                    "test_plan": list(gap_plan.get("test_plan") or [])[:5],
                    "report_outline": list(gap_plan.get("report_outline") or [])[:6],
                    "approval_gates": [
                        {
                            "capability": gate.get("capability", ""),
                            "strategy": gate.get("strategy", ""),
                            "requires_link": bool(gate.get("requires_link", False)),
                            "requires_fit_explanation": bool(gate.get("requires_fit_explanation", False)),
                            "requires_license_check": bool(gate.get("requires_license_check", False)),
                            "requires_user_approval": bool(gate.get("requires_user_approval", False)),
                        }
                        for gate in list(gap_plan.get("approval_gates") or [])[:5]
                        if isinstance(gate, dict)
                    ],
                    "learning_recommendations": list(gap_plan.get("learning_recommendations") or [])[:5],
                }
        except Exception:
            pass
        return metadata

    def log_model_route(self, metadata):
        if not metadata:
            return
        try:
            self._log_ui_diagnostic("model_route", **dict(metadata))
        except Exception:
            pass
        try:
            show_details = bool(self.show_activity_details_enabled())
        except Exception:
            show_details = False
        if show_details:
            self.append("\n[Model Route]\n" + self.render_model_route_summary(metadata) + "\n")

    def render_model_route_summary(self, metadata):
        if not metadata:
            return ""
        fallback = "Yes" if metadata.get("fallback_used") else "No"
        if metadata.get("fallback_used") and metadata.get("fallback_error"):
            fallback = f"Yes - {metadata['fallback_error']}"
        capabilities = ", ".join(metadata.get("capabilities_used") or ["none"])
        lines = [
            "Model route:",
            f"Provider: {metadata.get('active_provider', '')}",
            f"Model: {metadata.get('active_model', '')}",
            f"Routing: {metadata.get('routing_mode', '')}",
            f"Fallback: {fallback}",
            f"Project intelligence: {'Injected' if metadata.get('project_intelligence_used') else 'Not injected'}",
            f"DCC context: {'Used' if metadata.get('dcc_context_used') else 'Not used'}",
            f"DCC connection: {metadata.get('dcc_connection', 'none')}",
            f"Knowledge index: {'Ready' if metadata.get('knowledge_index_ready') else 'Missing'}",
            f"Timestamp: {metadata.get('timestamp', '')}",
            f"Capabilities: {capabilities}",
        ]
        if bool(self.settings.get("show_reasoning_summary", True)):
            summary = [
                "",
                "Reasoning summary:",
                f"I classified this as a {metadata.get('task_type', 'general')} request.",
                (
                    "I found the local knowledge index ready."
                    if metadata.get("knowledge_index_ready")
                    else "I did not find a ready local knowledge index."
                ),
                (
                    "I injected project or DCC context before sending the request."
                    if metadata.get("project_intelligence_used")
                    else "I sent the request without extra project intelligence context."
                ),
                (
                    f"I selected {metadata.get('active_provider')} / {metadata.get('active_model')} under {metadata.get('routing_mode')} routing."
                ),
            ]
            if metadata.get("fallback_used"):
                summary.append(
                    "A fallback model was used because the preferred cloud route was unavailable."
                )
            lines.extend(summary)
        try:
            from tech_connector.services.engineering_reasoning_service import render_senior_prompt_analysis

            prompt_summary = render_senior_prompt_analysis(
                metadata.get("senior_prompt_analysis") or {}
            )
            if prompt_summary:
                lines.extend(["", prompt_summary])
        except Exception:
            pass
        if self.settings.get("show_activity_details", False):
            try:
                from tech_connector.services.prompt_progress_service import render_prompt_progress_plan

                visible_summary = render_prompt_progress_plan(
                    metadata.get("visible_progress") or {},
                    max_stages=3,
                )
                if visible_summary:
                    lines.extend(["", visible_summary])
            except Exception:
                pass
            try:
                from tech_connector.services.goal_gap_planning_service import render_goal_gap_plan

                gap_summary = render_goal_gap_plan(
                    metadata.get("capability_gap_plan") or {},
                    max_links=4,
                )
                if gap_summary:
                    lines.extend(["", gap_summary])
            except Exception:
                pass
        return "\n".join(lines) + "\n"

    def store_request_metadata(self, role, metadata):
        role = role or "main"
        self._pending_response_metadata_by_role[role] = metadata
        self._last_request_metadata = metadata
        self.update_active_response_model_label(
            metadata.get("active_raw_model"),
            metadata.get("routing_mode"),
            metadata.get("fallback_used"),
            metadata.get("active_raw_model"),
        )
        self.log_model_route(metadata)

    def consume_request_metadata(self, role):
        return self._pending_response_metadata_by_role.pop(role or "main", None)

    def update_initial_status_cards(self):
        self.set_card(
            "knowledge",
            "ok" if project_index_db_path().exists() else "warn",
            "Index ready" if project_index_db_path().exists() else "Index missing",
        )
        self.set_card("mcphost", "off", "Stopped")
        self.set_card("ollama", "unknown", "Not checked")
        self.set_card("maya", "unknown", "Not checked")
        self.set_card("unreal", "unknown", "Not checked")
        self.set_card("blender", "unknown", "Not checked")
        self.set_card("substance_painter", "unknown", "Not checked")
        self.set_card("motionbuilder", "off", "Optional")
        self.set_card("unity", "unknown", "Not checked")
        if getattr(self, "_startup_defer_expensive_status", False):
            self.set_card("integrations", "unknown", "Checking later")
            return
        self.update_integrations_status_card()

    def update_integrations_status_card(self):
        try:
            from tech_connector.services.integration_package_service import (
                ensure_integration_bridge_manifests,
                summarize_integration_packages,
            )

            ensure_integration_bridge_manifests()
            summary = summarize_integration_packages()
            total = int(summary.get("total") or 0)
            if not total:
                self.set_card("integrations", "off", "None")
                return
            connected = int(summary.get("connected") or 0)
            validated = int(summary.get("validated") or 0)
            trusted = int(summary.get("trusted") or 0)
            if trusted:
                state = "ok"
            elif validated or connected:
                state = "warn"
            else:
                state = "unknown"
            detail = f"{total} pkg / {validated} validated / {trusted} trusted"
            if connected and not validated:
                detail = f"{total} pkg / {connected} connected"
            self.set_card("integrations", state, detail)
        except Exception:
            self.set_card("integrations", "warn", "Status unavailable")

    def closeEvent(self, event):
        if hasattr(self, "intel_service") and self.intel_service:
            try:
                self.intel_service.stop_daemon()
            except Exception:
                pass
        self.stop_mcphost()
        event.accept()

    # ------------------------------------------------------------------
    # Editor navigation/save hotkeys
    # ------------------------------------------------------------------
    def save_current_file(self):
        """Save the current editor tab to its existing file path."""
        try:
            editor = self.code_editor
        except Exception:
            editor = getattr(self, "fallback_editor", None)

        path = (
            getattr(editor, "file_path", None)
            or getattr(editor, "path", None)
            or getattr(self, "current_file_path", None)
        )
        if not path:
            return self.save_current_file_as()

        try:
            text = editor.toPlainText() if hasattr(editor, "toPlainText") else ""
            if hasattr(self, "write_text_with_vcs"):
                if not self.write_text_with_vcs(str(path), text, "save it"):
                    return False
            else:
                Path(path).write_text(text, encoding="utf-8")
            self.current_file_path = str(path)
            if hasattr(self, "file_path_label"):
                self.file_path_label.setText(str(path))
            if hasattr(self, "append"):
                self.append(f"\n[Saved file: {path}]\n")
            return True
        except Exception as exc:
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "Save Failed", str(exc))
            except Exception:
                pass
            if hasattr(self, "append"):
                self.append(f"\n[Save Failed] {exc}\n")
            return False

    def save_current_file_as(self):
        """Save the current editor tab to a user-selected path."""
        try:
            from PySide6.QtWidgets import QFileDialog
            editor = self.code_editor
            start_path = getattr(self, "current_file_path", "") or str(Path.home())
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Python File",
                start_path,
                "Python Files (*.py);;Text Files (*.txt);;All Files (*)",
            )
            if not path:
                return False
            text = editor.toPlainText() if hasattr(editor, "toPlainText") else ""
            if hasattr(self, "write_text_with_vcs"):
                if not self.write_text_with_vcs(str(path), text, "save it"):
                    return False
            else:
                Path(path).write_text(text, encoding="utf-8")
            setattr(editor, "file_path", path)
            self.current_file_path = path
            if hasattr(self, "file_path_label"):
                self.file_path_label.setText(path)
            if hasattr(self, "append"):
                self.append(f"\n[Saved file: {path}]\n")
            return True
        except Exception as exc:
            if hasattr(self, "append"):
                self.append(f"\n[Save As Failed] {exc}\n")
            return False

    def install_editor_navigation_hotkeys(self):
        """Install app-wide editor hotkeys, with an event-filter fallback.

        Ctrl+S: save current file
        Ctrl+T: trim trailing spaces
        Ctrl+F: find in current file
        Ctrl+B: find uses in current file
        Ctrl+N: find uses in project
        """
        try:
            if getattr(self, "_editor_navigation_hotkeys_installed_final", False):
                return
            self._editor_navigation_hotkeys_installed_final = True

            from PySide6.QtCore import Qt
            from PySide6.QtGui import QKeySequence, QShortcut
            from PySide6.QtWidgets import QApplication

            def _bind(name, sequence, callback_name):
                callback = getattr(self, callback_name, None)
                if not callable(callback):
                    if hasattr(self, "append"):
                        self.append(f"\n[Editor Hotkeys] missing callback for {sequence}: {callback_name}\n")
                    return None
                shortcut = QShortcut(QKeySequence(sequence), self)
                shortcut.setContext(Qt.ApplicationShortcut)
                shortcut.activated.connect(callback)
                setattr(self, name, shortcut)
                return shortcut

            _bind("shortcut_save_file_final", "Ctrl+S", "save_current_file")
            _bind("shortcut_trim_spaces_final", "Ctrl+T", "trim_trailing_spaces")
            _bind("shortcut_find_file_final", "Ctrl+F", "find_in_current_file_from_shortcut")
            _bind("shortcut_file_uses_final", "Ctrl+B", "find_uses_in_current_file_from_shortcut")
            _bind("shortcut_project_uses_final", "Ctrl+N", "find_uses_in_project_from_shortcut")

            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)

            if hasattr(self, "append"):
                self.append("\n[Editor Hotkeys] Installed: Ctrl+S Save, Ctrl+T Trim Spaces, Ctrl+F Find, Ctrl+B Uses in File, Ctrl+N Uses in Project.\n")
        except Exception as exc:
            if hasattr(self, "append"):
                self.append(f"\n[Editor Hotkeys] install failed: {exc}\n")

    def _app_has_active_focus(self):
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            active = app.activeWindow() if app is not None else None
            return active is self or (active is not None and active.window() is self)
        except Exception:
            try:
                return self.isActiveWindow()
            except Exception:
                return False

    def _handle_editor_hotkey_keypress(self, key, modifiers):
        try:
            from PySide6.QtCore import Qt
            if not (modifiers & Qt.ControlModifier):
                return False
            route = {
                Qt.Key_S: "save_current_file",
                Qt.Key_T: "trim_trailing_spaces",
                Qt.Key_F: "find_in_current_file_from_shortcut",
                Qt.Key_B: "find_uses_in_current_file_from_shortcut",
                Qt.Key_N: "find_uses_in_project_from_shortcut",
            }.get(key)
            if not route:
                return False
            callback = getattr(self, route, None)
            if callable(callback):
                callback()
                return True
        except Exception as exc:
            if hasattr(self, "append"):
                self.append(f"\n[Editor Hotkeys] key handling failed: {exc}\n")
        return False

    def eventFilter(self, obj, event):
        try:
            from PySide6.QtCore import QEvent
            if event.type() == QEvent.KeyPress and self._app_has_active_focus():
                if self._handle_editor_hotkey_keypress(event.key(), event.modifiers()):
                    return True
        except Exception:
            pass
        try:
            return super().eventFilter(obj, event)
        except Exception:
            return False

    def keyPressEvent(self, event):
        try:
            if self._handle_editor_hotkey_keypress(event.key(), event.modifiers()):
                event.accept()
                return
        except Exception:
            pass
        try:
            super().keyPressEvent(event)
        except Exception:
            event.ignore()
