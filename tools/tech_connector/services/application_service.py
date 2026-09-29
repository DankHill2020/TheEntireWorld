"""Central application state and orchestration service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from tech_connector.router.prompt_router import PromptRouter
from tech_connector.services.mcphost_service import (
    MCPHostManager,
    MCPHostOutputCleaner,
    build_health_check_message,
    start_mcphost,
)
from tech_connector.services.project_service import read_file, save_file
from tech_connector.services.settings_service import (
    install_components_to_tools,
    load_settings,
    save_settings,
    update_mcp_config,
)
from tech_connector.models.constants import APP_DIR, set_active_project_root
from tech_connector.models.project import all_roots, project_roots, recent_projects, set_active_project
from tech_connector.services.source_policy import apply_source_policy, live_sources_enabled
from tech_connector.services.application_command_service import ApplicationCommandService
from tech_connector.services.project_directory_service import (
    apply_project_directory_environment,
    initialize_tc_project_directories,
    resolve_project_directories,
    update_project_directory_settings,
)


_ACTIVE_PROJECT = object()


class LazyCommandRouter:
    """Create the heavy DCC command router only when a bridge is actually used."""

    def __init__(self) -> None:
        self._router = None

    def _load(self):
        if self._router is None:
            from tech_connector.router.command_router import CommandRouter

            self._router = CommandRouter()
        return self._router

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


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
        licensing_context=None,
        licensing_activation_client=None,
        license_acceptance_store=None,
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
        if licensing_context is not None:
            self.licensing_context = licensing_context
        else:
            from tech_connector.licensing.context import LicensingContext

            self.licensing_context = LicensingContext.from_defaults(APP_DIR)
        self._licensing_activation_client = licensing_activation_client
        if license_acceptance_store is not None:
            self._license_acceptance_store = license_acceptance_store
        else:
            from tech_connector.licensing.acceptance import FileLicenseAcceptanceStore

            self._license_acceptance_store = FileLicenseAcceptanceStore(APP_DIR / "licensing")
        self.project_directories = apply_project_directory_environment(self.settings)
        set_active_project_root(self.settings.get("active_project") or None)

        if bridge is not None:
            self.bridge = bridge
        else:
            try:
                from tech_connector.bridges.mcphost_bridge import TerminalBridge

                self.bridge = TerminalBridge()
            except Exception:
                self.bridge = None

        self.mcphost_manager = MCPHostManager(self.settings)
        self.local_models_used = set()
        self.command_router = command_router if command_router is not None else LazyCommandRouter()
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

    @staticmethod
    def development_entitlement_bypass_allowed() -> bool:
        """Allow source contributors to work locally, never frozen releases."""
        from tech_connector.services.licensing_startup_policy import (
            development_entitlement_bypass_allowed,
        )

        return development_entitlement_bypass_allowed()

    def evaluate_current_entitlement(self, *, commercial_use=None, project_root=_ACTIVE_PROJECT):
        from tech_connector.models.constants import APP_VERSION

        if project_root is _ACTIVE_PROJECT:
            project_root = str(self.settings.get("active_project") or "") or None
        else:
            project_root = str(project_root or "") or None
        if commercial_use is None:
            commercial_use = bool(self.settings.get("tech_connector_commercial_use", True))
        # Opening the licensed application shell is not itself use of an
        # unregistered commercial project. Community project registration is
        # enforced as soon as a concrete project is selected.
        commercial_use = bool(commercial_use and project_root)

        return self.licensing_context.evaluate(
            project_root=project_root,
            product=self.licensing_context.configuration.product,
            app_major_version=str(APP_VERSION).lstrip("vV").split(".", 1)[0],
            commercial_use=commercial_use,
        )

    def licensing_activation_client(self):
        if self._licensing_activation_client is None:
            from tech_connector.licensing.activation_client import LicensingActivationClient

            self._licensing_activation_client = LicensingActivationClient.from_defaults(
                APP_DIR,
                self.licensing_context,
            )
        return self._licensing_activation_client

    def authorize_host_bridges(self, evaluation):
        """Issue a metadata-free local DCC capability from a valid entitlement."""
        from tech_connector.bridges.session_authorization import (
            bridge_session_path_for_context,
            ensure_bridge_session_for_evaluation,
        )

        return ensure_bridge_session_for_evaluation(
            evaluation,
            path=bridge_session_path_for_context(self.licensing_context),
        )

    def record_license_acceptance(self, evaluation):
        """Persist readable evidence from a verified, policy-allowed entitlement."""
        claims = getattr(evaluation, "claims", None)
        decision = getattr(evaluation, "decision", None)
        if claims is None or decision is None or not decision.allowed:
            raise ValueError("cannot record acceptance from a denied entitlement")
        return self._license_acceptance_store.record_verified_entitlement(claims)

    @property
    def license_acceptance_receipts_path(self) -> Path:
        return self._license_acceptance_store.path

    def reload_settings(self) -> None:
        self.settings = self._load_settings_fn()
        self.project_directories = apply_project_directory_environment(self.settings)

    def all_roots(self) -> List[str]:
        return self._roots_with_authorized_tool_bundles(all_roots(self.settings))

    def project_roots(self) -> List[str]:
        return self._roots_with_authorized_tool_bundles(project_roots(self.settings))

    def _roots_with_authorized_tool_bundles(self, roots) -> List[str]:
        from tech_connector.models.constants import APP_VERSION
        from tech_connector.services.tool_bundle_service import (
            compose_project_roots_with_bundles,
        )

        evaluation = self.evaluate_current_entitlement(
            commercial_use=False,
            project_root=None,
        )
        claims = evaluation.claims if evaluation.decision.allowed else None
        return list(
            compose_project_roots_with_bundles(
                self.settings,
                roots,
                claims,
                str(APP_VERSION),
            )
        )

    def configured_tool_bundles(self):
        """Return locally configured first-party bundles without scanning projects."""
        from tech_connector.services.tool_bundle_service import discover_tool_bundles

        return discover_tool_bundles(self.settings)

    def tool_bundle_access(self):
        """Evaluate optional bundles against the current signed entitlement."""
        from tech_connector.models.constants import APP_VERSION
        from tech_connector.services.tool_bundle_service import evaluate_tool_bundles

        evaluation = self.evaluate_current_entitlement(
            commercial_use=False,
            project_root=None,
        )
        claims = evaluation.claims if evaluation.decision.allowed else None
        return evaluate_tool_bundles(self.settings, claims, str(APP_VERSION))

    def authorized_tool_bundle_roots(self):
        """Expose official tool roots only when the bundle capability is signed."""
        from tech_connector.models.constants import APP_VERSION
        from tech_connector.services.tool_bundle_service import authorized_tool_roots

        evaluation = self.evaluate_current_entitlement(
            commercial_use=False,
            project_root=None,
        )
        claims = evaluation.claims if evaluation.decision.allowed else None
        return authorized_tool_roots(self.settings, claims, str(APP_VERSION))

    def save_settings(self, settings: Optional[Dict[str, Any]] = None) -> None:
        if settings is not None:
            self.settings = settings
        self.project_directories = apply_project_directory_environment(self.settings)
        self._save_settings_fn(self.settings)

    def set_project_directories(
        self,
        *,
        tools_project: str,
        custom_game_project: bool = False,
        game_project: str = "",
        custom_art_source: bool = False,
        art_source: str = "",
    ):
        self.project_directories = update_project_directory_settings(
            self.settings,
            tools_project=tools_project,
            custom_game_project=custom_game_project,
            game_project=game_project,
            custom_art_source=custom_art_source,
            art_source=art_source,
        )
        set_active_project(self.settings, str(self.project_directories.tools_project))
        initialize_tc_project_directories(self.project_directories)
        set_active_project_root(self.project_directories.tools_project)
        self.save_settings()
        return self.project_directories

    def resolved_project_directories(self):
        self.project_directories = resolve_project_directories(self.settings)
        return self.project_directories

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
        from tech_connector.services.remote_mobile_server import RemoteMobileServer

        if self.remote_mobile_server is not None and self.remote_mobile_server.is_running:
            return self.remote_mobile_server.base_url
        host = host or self.settings.get("remote_mobile_host", "127.0.0.1")
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
        self.settings["tools_project_dir"] = res
        self.project_directories = apply_project_directory_environment(self.settings)
        set_active_project_root(res)
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
            try:
                from tech_connector.services.model_provider_service import provider_for_model
                from tech_connector.services.ollama_service import normalize_ollama_model_name

                if provider_for_model(model) == "ollama":
                    self.local_models_used.add(normalize_ollama_model_name(model))
            except Exception:
                pass
        return ok, cmd_display, error

    def stop_mcphost(self) -> None:
        if self.bridge is not None:
            self.bridge.stop()
        self.mcphost_ready = False

    def release_local_models(self):
        try:
            from tech_connector.services.ollama_service import unload_ollama_models

            return unload_ollama_models(sorted(self.local_models_used))
        except Exception as exc:
            return {"ok": False, "error": str(exc), "models": []}

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
                from tech_connector.bridges.knowledge_bridge import IndexWorker

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
        from tech_connector.services.version_control_service import detect_version_control_for_path

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
