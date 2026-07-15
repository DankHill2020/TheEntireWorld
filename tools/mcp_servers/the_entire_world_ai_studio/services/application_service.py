"""Central application state and orchestration service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from router.command_router import CommandRouter
from router.prompt_router import PromptRouter
from services.mcphost_service import (
    MCPHostManager,
    MCPHostOutputCleaner,
    build_health_check_message,
    start_mcphost,
)
from services.project_service import read_file, save_file
from services.settings_service import (
    install_components_to_tools,
    load_settings,
    save_settings,
    update_mcp_config,
)
from models.project import all_roots, project_roots, recent_projects, set_active_project
from services.source_policy import apply_source_policy, live_sources_enabled
from services.application_command_service import ApplicationCommandService


class ApplicationService:
    """Shared application state, bridge management, and orchestration."""

    def __init__(
        self,
        settings: Optional[Dict[str, Any]] = None,
        load_settings_fn=load_settings,
        save_settings_fn=save_settings,
        install_components_fn=install_components_to_tools,
        start_mcphost_fn=start_mcphost,
        update_mcp_config_fn=update_mcp_config,
        read_file_fn=read_file,
        save_file_fn=save_file,
        index_worker_cls: Optional[Type[Any]] = None,
        bridge=None,
        command_router=None,
        prompt_router=None,
        output_cleaner=None,
    ):
        self._load_settings_fn = load_settings_fn
        self._save_settings_fn = save_settings_fn
        self._install_components_fn = install_components_fn
        self._start_mcphost_fn = start_mcphost_fn
        self._update_mcp_config_fn = update_mcp_config_fn
        self._read_file_fn = read_file_fn
        self._save_file_fn = save_file_fn
        self._index_worker_cls = index_worker_cls

        self.settings = settings if settings is not None else self._load_settings_fn()

        if bridge is not None:
            self.bridge = bridge
        else:
            try:
                from bridges.mcphost_bridge import TerminalBridge

                self.bridge = TerminalBridge()
            except Exception:
                self.bridge = None

        self.mcphost_manager = MCPHostManager(self.settings)
        self.command_router = command_router if command_router is not None else CommandRouter()
        self.prompt_router = prompt_router if prompt_router is not None else PromptRouter()
        self.output_cleaner = output_cleaner if output_cleaner is not None else MCPHostOutputCleaner()
        self.command_service = ApplicationCommandService(self)
        self.remote_mobile_server = None

        self.index_worker = None
        self.current_session: List[Dict[str, Any]] = []
        self.attached_images: List[str] = []
        self.code_snippets: List[Tuple[str, str]] = []

        self.last_user_prompt = ""
        self.last_assistant_output = ""
        self.last_tool_output = ""
        self.pending_editor_patch = None
        self.current_file_path = ""
        self.mcphost_ready = False
        self.mcphost_use_pty = False

    def reload_settings(self) -> None:
        self.settings = self._load_settings_fn()

    def all_roots(self) -> List[str]:
        return all_roots(self.settings)

    def project_roots(self) -> List[str]:
        return project_roots(self.settings)

    def save_settings(self, settings: Optional[Dict[str, Any]] = None) -> None:
        if settings is not None:
            self.settings = settings
        self._save_settings_fn(self.settings)

    def live_sources_enabled(self) -> bool:
        return live_sources_enabled(self.settings)

    def set_live_sources_enabled(self, enabled: bool) -> None:
        self.settings["enable_live_sources"] = bool(enabled)
        self.save_settings()

    def set_model_source_mode(self, mode: str) -> None:
        if mode not in {"auto_with_local_fallback", "local_only"}:
            mode = "auto_with_local_fallback"

        self.settings["model_source_mode"] = mode
        self.save_settings()

    def prepare_prompt(self, text: str) -> str:
        return apply_source_policy(text, self.settings)

    def start_remote_mobile_server(self, host: str = "", port: int | None = None) -> str:
        from services.remote_mobile_server import RemoteMobileServer

        if self.remote_mobile_server is not None and self.remote_mobile_server.is_running:
            return self.remote_mobile_server.base_url
        host = host or self.settings.get("remote_mobile_host", "0.0.0.0")
        port = int(port if port is not None else self.settings.get("remote_mobile_port", 8765))
        self.remote_mobile_server = RemoteMobileServer(
            self.command_service,
            host=host,
            port=port,
        )
        return self.remote_mobile_server.start()

    def remote_mobile_pairing_qr_url(self) -> str:
        if self.remote_mobile_server is None:
            return ""
        return getattr(self.remote_mobile_server, "pairing_qr_url", "")

    def remote_mobile_download_qr_url(self) -> str:
        if self.remote_mobile_server is None:
            return ""
        return getattr(self.remote_mobile_server, "download_qr_url", "")

    def stop_remote_mobile_server(self) -> None:
        if self.remote_mobile_server is not None:
            self.remote_mobile_server.stop()

    def recent_projects(self) -> List[str]:
        return recent_projects(self.settings)

    def set_active_project(self, path: str) -> str:
        res = set_active_project(self.settings, path)
        self.save_settings()
        return res

    def install_components(self) -> str:
        self._install_components_fn()
        return self._update_mcp_config_fn()

    def start_mcphost(self, model: str, config: str, use_pty: bool) -> Tuple[bool, str, str]:
        ok, cmd_display, error = self._start_mcphost_fn(
            self.bridge,
            self.settings,
            model,
            config,
            use_pty,
        )
        if ok:
            self.mcphost_use_pty = use_pty
            self.mcphost_ready = False
        return ok, cmd_display, error

    def stop_mcphost(self) -> None:
        if self.bridge is not None:
            self.bridge.stop()
        self.mcphost_ready = False

    def interrupt_mcphost(self) -> None:
        if self.bridge is not None:
            self.bridge.interrupt()

    def send_raw(self, text: str) -> bool:
        self.last_user_prompt = text
        self.current_session.append({"role": "user", "content": text})
        if self.bridge is None:
            return False
        return self.bridge.write(text)

    def clean_output(self, raw: str) -> str:
        cleaned = self.output_cleaner.clean(raw)
        if cleaned:
            self.last_assistant_output = cleaned
            self.current_session.append(
                {"role": "assistant_or_tool_output", "content": cleaned}
            )
        return cleaned

    def get_health_check(self) -> str:
        return build_health_check_message(self.bridge, self.mcphost_ready)

    def build_index(self, ensure_components: bool = False) -> Any:
        if ensure_components:
            self.install_components()

        if self._index_worker_cls is None:
            try:
                from bridges.knowledge_bridge import IndexWorker

                self._index_worker_cls = IndexWorker
            except Exception as e:
                raise ValueError("index_worker_cls must be provided") from e

        self.index_worker = self._index_worker_cls(self.all_roots())
        return self.index_worker

    def read_file(self, path: str) -> Tuple[bool, str]:
        return self._read_file_fn(path)

    def save_file(self, path: str, content: str) -> Tuple[bool, str]:
        return self._save_file_fn(path, content)

    def version_control_for_path(self, path: str):
        from services.version_control_service import detect_version_control_for_path

        return detect_version_control_for_path(Path(path))

    def is_read_only_file(self, path: str) -> bool:
        try:
            return Path(path).exists() and not Path(path).stat().st_mode & 0o200
        except Exception:
            return False

    def make_file_writable(self, path: str) -> Tuple[bool, str]:
        try:
            p = Path(path)
            if not p.exists():
                return False, "File does not exist."
            p.chmod(p.stat().st_mode | 0o200)
            return True, str(p)
        except Exception as e:
            return False, str(e)
