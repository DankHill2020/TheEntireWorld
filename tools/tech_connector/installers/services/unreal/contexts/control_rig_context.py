from __future__ import annotations

from tech_connector.services.unreal.contexts.blueprint_context import BlueprintContextBuilder
from tech_connector.services.unreal.contexts.common import compact_names, execute_python_json


class ControlRigContextBuilder(BlueprintContextBuilder):
    def build(self, asset_path: str, focus: str = "control_rig"):
        result = super().build(asset_path, focus=focus)
        result["asset_category"] = "control_rig"

        script = f"""
import json
import unreal

asset_path = {asset_path!r}
out = {{
    "asset_path": asset_path,
    "asset_name": "",
    "hierarchy_items": [],
    "controls": [],
    "bones": [],
    "nulls": [],
    "rig_graph_hints": [],
    "warnings": [],
}}

try:
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        out["warnings"].append("Control Rig asset could not be loaded")
    else:
        try:
            out["asset_name"] = asset.get_name()
        except Exception:
            pass
        hierarchy = None
        for attr in ("hierarchy", "vm_hierarchy", "dynamic_hierarchy"):
            try:
                hierarchy = asset.get_editor_property(attr)
                if hierarchy:
                    break
            except Exception:
                pass
        if hierarchy:
            for getter_name in ("get_keys", "get_all_keys"):
                try:
                    keys = getattr(hierarchy, getter_name)()
                    for key in keys or []:
                        item = {{"name": "", "type": ""}}
                        try:
                            item["name"] = str(key.name)
                        except Exception:
                            item["name"] = str(key)
                        try:
                            item["type"] = str(key.type)
                        except Exception:
                            pass
                        out["hierarchy_items"].append(item)
                        lower_type = item["type"].lower()
                        if "control" in lower_type:
                            out["controls"].append(item)
                        elif "bone" in lower_type:
                            out["bones"].append(item)
                        elif "null" in lower_type or "space" in lower_type:
                            out["nulls"].append(item)
                    break
                except Exception:
                    pass
        else:
            out["warnings"].append("Control Rig hierarchy was not available through Python reflection")

        for attr in (
            "model",
            "rig_vm_model",
            "vm_model",
        ):
            try:
                model = asset.get_editor_property(attr)
                if model:
                    try:
                        if hasattr(model, "get_nodes"):
                            for node in model.get_nodes() or []:
                                try:
                                    out["rig_graph_hints"].append(str(node.get_name()))
                                except Exception:
                                    out["rig_graph_hints"].append(str(node))
                    except Exception:
                        pass
                    break
            except Exception:
                pass
except Exception as exc:
    out["warnings"].append(str(exc))

print(json.dumps(out))
"""
        response = execute_python_json(self.scanner, script, timeout=12.0)
        data = response.get("data") or {}
        warnings = list(result.get("warnings") or []) + list(data.get("warnings") or [])
        if response.get("error"):
            warnings.append(str(response.get("error")))
        controls = list(data.get("controls") or [])
        bones = list(data.get("bones") or [])
        nulls = list(data.get("nulls") or [])
        rig_graph_hints = list(data.get("rig_graph_hints") or [])
        hierarchy_items = list(data.get("hierarchy_items") or [])
        likely_tweak_points = []
        if controls:
            likely_tweak_points.append("controls")
        if rig_graph_hints:
            likely_tweak_points.append("rig_vm")
        if hierarchy_items:
            likely_tweak_points.append("hierarchy")
        result.update(
            {
                "hierarchy_items": hierarchy_items,
                "controls": controls,
                "bones": bones,
                "nulls": nulls,
                "rig_graph_hints": rig_graph_hints[:40],
                "likely_tweak_points": likely_tweak_points,
                "warnings": warnings,
            }
        )
        result["summary"] = (
            f"Control Rig {result.get('asset_name') or asset_path}"
            f" | graphs: {len(result.get('graphs') or [])}"
            f" | controls: {len(controls)}"
            f" | hierarchy items: {len(hierarchy_items)}"
        )
        result["recommended_followups"] = [
            "Inspect rig graph node connectivity before patch planning.",
            "Validate control names, hierarchy references, and execution order.",
            "Use stronger reasoning for graph rewrites or procedural rig changes.",
        ]
        result.setdefault("highlights", {})["controls"] = compact_names(
            controls, limit=10
        )
        result.setdefault("highlights", {})["bones"] = compact_names(bones, limit=10)
        result.setdefault("highlights", {})["rig_graph_hints"] = [
            str(x) for x in rig_graph_hints[:10]
        ]
        return result
