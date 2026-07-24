"""
Compatibility launcher for the Blender direct bridge.

Run this file inside Blender for a one-session manual setup. The canonical
bridge implementation lives in ``blender_ai_studio_bridge_addon.py`` so the
installed add-on path and manual setup path cannot drift apart.
"""

from pathlib import Path


def _run_canonical_addon():
    try:
        source_path = Path(__file__).with_name("blender_ai_studio_bridge_addon.py")
    except NameError as exc:
        raise RuntimeError(
            "Run this script from its installer file path, or install the Blender "
            "bridge add-on with install_blender_bridge.py."
        ) from exc

    code = source_path.read_text(encoding="utf-8")
    namespace = {"__file__": str(source_path), "__name__": "__main__"}
    exec(compile(code, str(source_path), "exec"), namespace, namespace)


_run_canonical_addon()
