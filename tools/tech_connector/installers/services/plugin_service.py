"""Plugin registry access."""

import json
from pathlib import Path

from models.constants import APP_ROOT


def load_plugin_registry() -> dict:
    path = APP_ROOT / "plugins" / "plugin_registry.json"
    if not path.exists():
        return {"version": "0", "plugins": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "0", "plugins": {}}


def get_plugin(name: str):
    registry = load_plugin_registry()
    return registry.get("plugins", {}).get(name)
