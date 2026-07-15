"""Setup helpers for direct DCC app bridges."""

from dataclasses import dataclass, field
from pathlib import Path

from bridges.blender.blender_bridge import (
    blender_user_root,
    install_to_version,
    select_versions,
    version_needs_install,
)
from bridges.substance_painter.substance_painter_bridge import (
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
    root = Path(repo_root or Path(__file__).resolve().parent.parent)
    return f'''# The Entire World Tech Connector Blender bridge setup.
# Paste this into Blender's Scripting workspace and press Run Script.
import sys
from pathlib import Path

repo_root = Path(r"{root}")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    import bpy
    from bridges.blender import blender_bridge

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
    root = Path(repo_root or Path(__file__).resolve().parent.parent)
    return f'''# The Entire World Tech Connector Substance Painter bridge setup.
# Paste this into Substance Painter's Python console/script editor and run it.
import sys
from pathlib import Path

repo_root = Path(r"{root}")
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from bridges.substance_painter import substance_painter_bridge

    plugin_dir = substance_painter_bridge.default_plugin_dir()
    substance_painter_bridge.install_to_plugin_dir(plugin_dir)
    substance_painter_bridge.start_plugin_immediately()
    print("Tech Connector Substance Painter bridge installed and running now. Restart Painter after updates.")
except Exception as exc:
    import traceback
    traceback.print_exc()
    print("Tech Connector Substance Painter bridge setup failed:", exc)
'''
