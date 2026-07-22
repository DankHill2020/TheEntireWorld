"""Connected application status and live discovery helpers."""

from __future__ import annotations

from typing import Any

from services.connected_account_service import connected_account_status_rows


def connected_application_status(settings: dict[str, Any], command_router: Any = None) -> list[dict[str, Any]]:
    def dcc_status(app_id: str, name: str) -> dict[str, Any]:
        bridge = command_router._host_bridge_for_operation(app_id) if command_router else None
        port = bridge.find_port() if bridge and hasattr(bridge, "find_port") else None
        return {
            "id": app_id,
            "name": name,
            "category": "DCC/Engine",
            "connected": bool(port),
            "mode": f"bridge:{port}" if port else "bridge not detected",
            "capabilities": ["live selection", "scene context", "execute python"] if port else ["setup required"],
        }

    rows = [
        dcc_status("maya", "Maya"),
        dcc_status("blender", "Blender"),
        dcc_status("houdini", "Houdini"),
        dcc_status("substance_painter", "Substance Painter"),
        dcc_status("motionbuilder", "MotionBuilder"),
        dcc_status("unity", "Unity"),
        dcc_status("unreal", "Unreal Engine"),
    ]
    rows.extend(connected_account_status_rows(settings))
    return rows


def format_connected_application_status(settings: dict[str, Any], command_router: Any = None) -> str:
    lines = ["Connected Application Capability Status:"]
    for row in connected_application_status(settings, command_router):
        state = "LIVE" if row["connected"] else "SETUP"
        lines.append(f"- {row['name']} [{row['category']}]: {state} ({row['mode']})")
        lines.append("  capabilities: " + ", ".join(row.get("capabilities") or []))
    return "\n".join(lines)
