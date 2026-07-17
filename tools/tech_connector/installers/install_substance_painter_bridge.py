"""Install the Substance Painter Tech Connector bridge plugin."""

import argparse
import os
import shutil
from pathlib import Path


PLUGIN_SOURCE = Path(__file__).with_name("substance_painter_ai_studio_bridge.py")
PLUGIN_FILENAME = "the_entire_world_ai_studio_bridge.py"


def documents_root(userprofile=None):
    override = os.environ.get("SUBSTANCE_PAINTER_PLUGINS_DIR")
    if override:
        return Path(override).parent
    base = Path(userprofile or os.environ.get("USERPROFILE", ""))
    if not base:
        raise RuntimeError("USERPROFILE is not set; cannot find Documents.")
    return base / "Documents"


def plugin_dir_candidates(userprofile=None):
    override = os.environ.get("SUBSTANCE_PAINTER_PLUGINS_DIR")
    if override:
        return [Path(override)]

    docs = documents_root(userprofile)
    return [
        docs / "Adobe" / "Adobe Substance 3D Painter" / "python" / "plugins",
        docs / "Allegorithmic" / "Substance Painter" / "plugins",
    ]


def default_plugin_dir(userprofile=None):
    candidates = plugin_dir_candidates(userprofile)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def plugin_needs_install(plugin_dir):
    target = Path(plugin_dir) / PLUGIN_FILENAME
    if not target.exists():
        return True
    try:
        return target.read_text(encoding="utf-8") != PLUGIN_SOURCE.read_text(encoding="utf-8")
    except Exception:
        return True


def install_to_plugin_dir(plugin_dir, dry_run=False):
    plugin_dir = Path(plugin_dir)
    target = plugin_dir / PLUGIN_FILENAME
    if not dry_run:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PLUGIN_SOURCE, target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-dir", help="Install to an explicit Substance Painter plugins folder.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be written without copying files.")
    args = parser.parse_args(argv)

    if not PLUGIN_SOURCE.exists():
        print("Missing %s" % PLUGIN_SOURCE)
        return 1

    plugin_dir = Path(args.plugin_dir) if args.plugin_dir else default_plugin_dir()
    target = install_to_plugin_dir(plugin_dir, dry_run=args.dry_run)
    action = "Would install" if args.dry_run else "Installed"
    print("%s Substance Painter bridge plugin:" % action)
    print("  %s" % target)
    if not args.dry_run:
        print("")
        print("Restart Substance Painter. If needed, enable the plugin from the Python/plugins menu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
