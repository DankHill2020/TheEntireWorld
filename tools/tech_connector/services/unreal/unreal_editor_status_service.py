# coding=utf-8
"""
    Unreal Engine Process & HTTP Bridge Status Inspector Service for Tech Connector.
    Inspects whether Unreal Engine editor is open, closed, or responsive on port 12347,
    ensuring honest and accurate execution state reporting.
"""

class UnrealEditorStatusService:
    """
        Inspects live status of Unreal Engine editor process and HTTP bridge port.
    """

    def __init__(self, port: int | None = None, timeout_sec: float = 1.0):
        """
            Initializes the Unreal Editor Status Service.
        :param port: HTTP bridge port number
        :param timeout_sec: connection timeout in seconds
        """
        self.port = port
        self.timeout_sec = timeout_sec

    def check_unreal_editor_status(self) -> dict:
        """
            Queries live HTTP bridge to check if Unreal Engine editor is open and responsive.
        :return: dictionary containing live editor status, process state, and mode
        """
        try:
            from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

            bridge = UnrealBridge()
            port = self.port or bridge.find_port()
            if not port:
                raise RuntimeError("Unreal bridge is not listening on any known port.")
            health = bridge.health_check(timeout=self.timeout_sec)
            if isinstance(health, dict) and health.get("ok") is False:
                raise RuntimeError(health.get("error") or health.get("message") or "Unreal bridge health check failed.")
            return {
                "editor_open": True,
                "http_bridge_responsive": True,
                "port": port,
                "execution_mode": "LIVE_EDITOR_INJECTION",
                "status_message": f"Unreal Engine Editor is OPEN and listening on port {port}.",
                "health": health if isinstance(health, dict) else {},
            }
        except Exception as exc:
            return {
                "editor_open": False,
                "http_bridge_responsive": False,
                "port": self.port,
                "execution_mode": "OFFLINE_ASSET_GENERATION",
                "status_message": f"Unreal Engine Editor is CLOSED or unreachable ({exc}). Assets & K2 snippets generated on disk.",
            }
