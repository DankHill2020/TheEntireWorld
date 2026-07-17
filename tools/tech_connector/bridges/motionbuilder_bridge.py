import json
from pathlib import Path
from tech_connector.models.constants import APP_ROOT


class MotionBuilderBridge:
    """MotionBuilder host bridge. Direct commandPort support is planned."""

    def __init__(self):
        # Load from plugin_registry.json directly
        registry_path = APP_ROOT / "plugins" / "plugin_registry.json"
        self._plugin = {}
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
                self._plugin = registry.get("plugins", {}).get("motionbuilder") or {}
            except Exception:
                pass

    def find_port(self, host="127.0.0.1"):
        import socket
        port = self.default_port
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.25)
                if s.connect_ex((host, port)) == 0:
                    return port
        except Exception:
            pass
        return None

    @property
    def default_port(self) -> int:
        return self._plugin.get("default_port", 7011)

    @property
    def domain(self) -> str:
        return self._plugin.get("domain", "motionbuilder")

    def mcp_selection_prompt(self) -> str:
        return "Call motionbuilder__motionbuilder_selection and show the raw response."

    def mcp_takes_prompt(self) -> str:
        return "Call motionbuilder__motionbuilder_takes and show the raw response."

    def mcp_execute_prompt(self, code: str) -> str:
        return f"Call motionbuilder__motionbuilder_execute_python with code {code!r} and show the raw response."
