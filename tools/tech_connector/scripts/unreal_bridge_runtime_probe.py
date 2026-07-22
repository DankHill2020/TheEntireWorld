"""Probe AIStudioBridge reflection and selected real Unreal assets over HTTP."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "tech_connector").is_dir())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", default="/Game/MetaHumans/LesterPhoenix/BP_LesterPhoenix")
    parser.add_argument("--anim-blueprint", default="/Game/Variant_Combat/Anims/ABP_Manny_Combat")
    args = parser.parse_args()

    unreal_code = f'''import importlib
import inspect
import json
import unreal
import tech_connector.bridges.unreal.unreal_dynamic_character_feature as feature_module

feature_module = importlib.reload(feature_module)

library = getattr(unreal, "AIStudioBridgeLibrary", None)
character = unreal.EditorAssetLibrary.load_asset({args.character!r})
anim_bp = unreal.EditorAssetLibrary.load_asset({args.anim_blueprint!r})
payload = {{
    "has_library": library is not None,
    "methods": {{
        name: bool(library and hasattr(library, name))
        for name in (
            "inspect_anim_blueprint_graph",
            "inspect_animation_sequence",
            "inspect_character_in_pie",
            "validate_character_montages_in_pie",
            "inject_key_in_pie",
        )
    }},
    "character_exists": character is not None,
    "anim_blueprint_exists": anim_bp is not None,
    "feature_module": {{
        "file": feature_module.__file__,
        "has_persisted_semantic_gate": hasattr(feature_module, "_evaluate_persisted_role_asset"),
        "validator_has_sequence_probe": "sequence_probe" in inspect.getsource(feature_module.validate_character_feature_plan),
    }},
    "anim_graph_probe": {{}},
}}
graph = json.loads(library.inspect_anim_blueprint_graph(anim_bp)) if library and anim_bp else {{}}
payload["anim_graph_probe"] = {{
    "ok": graph.get("ok"),
    "graphs": [
        {{
            "name": row.get("name"),
            "node_count": row.get("node_count"),
            "node_titles": [node.get("title") for node in row.get("nodes", [])],
        }}
        for row in graph.get("graphs", [])
    ],
}}
print("AISTUDIO_BRIDGE_PROBE=" + json.dumps(payload))
'''
    bridge = UnrealBridge()
    result = bridge.execute_python(unreal_code, timeout=60)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
