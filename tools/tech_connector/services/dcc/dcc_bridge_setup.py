"""Setup helpers for direct DCC app bridges."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tech_connector.models.constants import TOOLS_ROOT

from tech_connector.bridges.blender.blender_bridge import (
    blender_user_root,
    install_to_version,
    select_versions,
    version_needs_install,
)
from tech_connector.bridges.substance_painter.substance_painter_bridge import (
    default_plugin_dir,
    install_to_plugin_dir,
    plugin_needs_install,
)


@dataclass
class DCCSetupResult:
    host: str
    ok: bool
    installed_versions: list[str] = field(default_factory=list)
    current_versions: list[str] = field(default_factory=list)
    message: str = ""
    restart_required: bool = False


def install_blender_startup_bridge(all_versions=True) -> DCCSetupResult:
    try:
        root = blender_user_root()
        versions = select_versions(root, all_versions=all_versions)
        if not versions:
            return DCCSetupResult(
                host="Blender",
                ok=False,
                message="No Blender user folder found. Open Blender once, then run bridge setup again.",
            )

        installed = []
        current = []
        for version in versions:
            version_root = root / version
            if version_needs_install(version_root):
                install_to_version(version_root)
                installed.append(version)
            else:
                current.append(version)

        if installed:
            return DCCSetupResult(
                host="Blender",
                ok=True,
                installed_versions=installed,
                current_versions=current,
                message="Installed or updated Blender bridge for: " + ", ".join(installed),
                restart_required=True,
            )

        return DCCSetupResult(
            host="Blender",
            ok=True,
            current_versions=current,
            message="Blender bridge startup hook is already installed.",
        )
    except Exception as e:
        return DCCSetupResult(host="Blender", ok=False, message=str(e))


def blender_script_editor_snippet(repo_root=None) -> str:
    root = Path(repo_root or TOOLS_ROOT)
    return f'''# The Entire World Tech Connector Blender bridge setup.
# Paste this into Blender's Scripting workspace and press Run Script.
import sys
from pathlib import Path

repo_root = Path(r"{root}")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    import bpy
    from tech_connector.bridges.blender import blender_bridge

    version = "{{}}.{{}}".format(bpy.app.version[0], bpy.app.version[1])
    version_root = blender_bridge.blender_user_root() / version
    blender_bridge.install_to_version(version_root)
    blender_bridge.start_plugin_immediately()
    print("Tech Connector Blender bridge installed for startup and running now. Restart Blender after updates.")
except Exception as exc:
    import traceback
    traceback.print_exc()
    print("Tech Connector Blender bridge setup failed:", exc)
'''


def install_substance_painter_bridge() -> DCCSetupResult:
    try:
        plugin_dir = default_plugin_dir()
        if plugin_needs_install(plugin_dir):
            target = install_to_plugin_dir(plugin_dir)
            return DCCSetupResult(
                host="Substance Painter",
                ok=True,
                installed_versions=[str(target)],
                message="Installed or updated Substance Painter bridge plugin.",
                restart_required=True,
            )

        return DCCSetupResult(
            host="Substance Painter",
            ok=True,
            current_versions=[str(plugin_dir)],
            message="Substance Painter bridge plugin is already installed.",
        )
    except Exception as e:
        return DCCSetupResult(host="Substance Painter", ok=False, message=str(e))


def substance_painter_script_editor_snippet(repo_root=None) -> str:
    root = Path(repo_root or TOOLS_ROOT)
    return f'''# The Entire World Tech Connector Substance Painter bridge setup.
# Paste this into Substance Painter's Python console/script editor and run it.
import sys
from pathlib import Path

repo_root = Path(r"{root}")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from tech_connector.bridges.substance_painter import substance_painter_bridge

    plugin_dir = substance_painter_bridge.default_plugin_dir()
    substance_painter_bridge.install_to_plugin_dir(plugin_dir)
    substance_painter_bridge.start_plugin_immediately()
    print("Tech Connector Substance Painter bridge installed and running now. Restart Painter after updates.")
except Exception as exc:
    import traceback
    traceback.print_exc()
    print("Tech Connector Substance Painter bridge setup failed:", exc)
'''



def install_gimp_bridge() -> DCCSetupResult:
    """Install Tech Connector Python-Fu plugin into local GIMP plug-ins folder."""
    try:
        app_data = Path(os.environ.get("APPDATA", r"C:/Users/Aaron/AppData/Roaming"))
        gimp_plugins = app_data / "GIMP" / "2.10" / "plug-ins"
        gimp_plugins.mkdir(parents=True, exist_ok=True)

        from tech_connector.bridges.gimp.gimp_bridge import PLUGIN_FILENAME, PLUGIN_SOURCE_CODE
        target_file = gimp_plugins / PLUGIN_FILENAME
        target_file.write_text(PLUGIN_SOURCE_CODE, encoding="utf-8")

        return DCCSetupResult(
            host="GIMP",
            ok=True,
            message=f"Successfully installed GIMP bridge plugin to {target_file}",
            restart_required=True,
        )
    except Exception as exc:
        return DCCSetupResult(host="GIMP", ok=False, message=str(exc))


def install_photoshop_uxp_bridge() -> DCCSetupResult:
    """Install Tech Connector UXP plugin into Adobe Photoshop plugin folder."""
    try:
        app_data = Path(os.environ.get("APPDATA", r"C:/Users/Aaron/AppData/Roaming"))
        ps_plugins = app_data / "Adobe" / "UXP" / "Plugins" / "TechConnectorBridge"
        ps_plugins.mkdir(parents=True, exist_ok=True)

        from tech_connector.bridges.photoshop.photoshop_bridge import PLUGIN_JS_SOURCE, PLUGIN_MANIFEST
        (ps_plugins / "manifest.json").write_text(PLUGIN_MANIFEST, encoding="utf-8")
        (ps_plugins / "index.js").write_text(PLUGIN_JS_SOURCE, encoding="utf-8")

        return DCCSetupResult(
            host="Photoshop",
            ok=True,
            message=f"Successfully installed Photoshop UXP bridge to {ps_plugins}",
            restart_required=True,
        )
    except Exception as exc:
        return DCCSetupResult(host="Photoshop", ok=False, message=str(exc))


def auto_reconnect_dcc_bridges() -> dict[str, Any]:
    """Preflight check across all 2D and 3D DCC bridges, auto-reconnecting active sockets."""
    results = {}
    from tech_connector.bridges.maya.maya_bridge import MayaBridge
    from tech_connector.bridges.substance_painter.substance_painter_bridge import SubstancePainterBridge
    from tech_connector.bridges.photoshop.photoshop_bridge import PhotoshopBridge
    from tech_connector.bridges.gimp.gimp_bridge import GimpBridge

    for name, bridge_cls in [("maya", MayaBridge), ("substance_painter", SubstancePainterBridge), ("photoshop", PhotoshopBridge), ("gimp", GimpBridge)]:
        try:
            b = bridge_cls()
            port = b.find_port()
            results[name] = {"connected": port is not None, "port": port}
        except Exception as exc:
            results[name] = {"connected": False, "error": str(exc)}

    return results
