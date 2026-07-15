from __future__ import annotations

from services.unreal.contexts.common import (
    basic_asset_context,
    compact_names,
    execute_python_json,
)


class NiagaraContextBuilder:
    def __init__(self, scanner):
        self.scanner = scanner

    def build(self, asset_path: str, focus: str = "niagara"):
        result = basic_asset_context(asset_path, "niagara", focus=focus)
        script = f"""
import json
import unreal

asset_path = {asset_path!r}
out = {{
    "asset_path": asset_path,
    "asset_name": "",
    "system_class": "",
    "emitters": [],
    "user_parameters": [],
    "editable_parameters": [],
    "renderer_hints": [],
    "module_hints": [],
    "warnings": [],
}}

try:
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        out["warnings"].append("Niagara asset could not be loaded")
    else:
        try:
            out["asset_name"] = asset.get_name()
        except Exception:
            pass
        try:
            out["system_class"] = asset.get_class().get_name()
        except Exception:
            pass

        candidates = []
        for attr in (
            "emitter_handles",
            "emitters",
            "editor_data",
            "exposed_parameters",
            "user_parameters",
        ):
            try:
                candidates.append((attr, asset.get_editor_property(attr)))
            except Exception:
                pass

        for attr, value in candidates:
            if attr in ("emitter_handles", "emitters") and value:
                for item in value:
                    entry = {{
                        "name": "",
                        "source": attr,
                        "renderer_hints": [],
                        "module_hints": [],
                        "editable_parameters": [],
                        "script_parameter_cues": [],
                    }}
                    try:
                        if hasattr(item, "get_name"):
                            entry["name"] = item.get_name()
                    except Exception:
                        pass
                    try:
                        inst = item.get_editor_property("instance") if hasattr(item, "get_editor_property") else None
                        if inst:
                            try:
                                emitter = inst.get_editor_property("emitter")
                                if emitter and hasattr(emitter, "get_name"):
                                    entry["name"] = entry["name"] or emitter.get_name()
                            except Exception:
                                pass
                            for prop in ("renderer_properties", "renderers"):
                                try:
                                    renderers = inst.get_editor_property(prop)
                                    for renderer in renderers or []:
                                        try:
                                            entry["renderer_hints"].append(renderer.get_class().get_name())
                                        except Exception:
                                            entry["renderer_hints"].append(str(renderer))
                                except Exception:
                                    pass
                            for prop in (
                                "spawn_script_props",
                                "update_script_props",
                                "event_handler_script_props",
                                "simulation_stage_script_props",
                            ):
                                try:
                                    script_props = inst.get_editor_property(prop)
                                    if script_props:
                                        entry["module_hints"].append(prop)
                                except Exception:
                                    pass
                            for prop in (
                                "rapid_iteration_parameters",
                                "exposed_parameters",
                                "editor_parameters",
                            ):
                                try:
                                    params = inst.get_editor_property(prop)
                                    if params:
                                        entry["editable_parameters"].append(prop)
                                except Exception:
                                    pass
                            for prop in (
                                "spawn_script_props",
                                "update_script_props",
                                "event_handler_script_props",
                                "simulation_stage_script_props",
                            ):
                                try:
                                    script_props = inst.get_editor_property(prop)
                                    for script_prop in script_props or []:
                                        cue = prop
                                        try:
                                            script = script_prop.get_editor_property("script")
                                            if script and hasattr(script, "get_name"):
                                                cue = prop + ":" + script.get_name()
                                        except Exception:
                                            pass
                                        entry["script_parameter_cues"].append(cue)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    if not entry["name"]:
                        entry["name"] = str(item)
                    out["emitters"].append(entry)

            if attr in ("exposed_parameters", "user_parameters") and value:
                try:
                    if hasattr(value, "get_user_parameters"):
                        params = value.get_user_parameters()
                    else:
                        params = value
                    for param in params or []:
                        try:
                            name = str(param.get_name())
                        except Exception:
                            name = str(param)
                        out["user_parameters"].append(name)
                        out["editable_parameters"].append(name)
                except Exception as exc:
                    out["warnings"].append("parameter query failed: " + str(exc))

        if not out["emitters"]:
            out["warnings"].append("Emitter details were limited by available Niagara editor reflection")
except Exception as exc:
    out["warnings"].append(str(exc))

print(json.dumps(out))
"""
        response = execute_python_json(self.scanner, script, timeout=12.0)
        data = response.get("data") or {}
        warnings = list(data.get("warnings") or [])
        emitters = list(data.get("emitters") or [])
        renderer_hints = []
        module_hints = []
        script_parameter_cues = []
        editable_parameters = list(data.get("editable_parameters") or [])
        for emitter in emitters:
            renderer_hints.extend(list(emitter.get("renderer_hints") or []))
            module_hints.extend(list(emitter.get("module_hints") or []))
            script_parameter_cues.extend(
                list(emitter.get("script_parameter_cues") or [])
            )
            editable_parameters.extend(list(emitter.get("editable_parameters") or []))
        user_parameters = list(data.get("user_parameters") or [])
        likely_tweak_points = []
        if user_parameters:
            likely_tweak_points.append("user_parameters")
        if editable_parameters:
            likely_tweak_points.append("editable_parameters")
        if renderer_hints:
            likely_tweak_points.append("renderers")
        if module_hints:
            likely_tweak_points.append("modules")
        if script_parameter_cues:
            likely_tweak_points.append("script_parameters")
        if emitters:
            likely_tweak_points.append("emitters")
        result.update(
            {
                "asset_name": data.get("asset_name") or asset_path,
                "system_class": data.get("system_class"),
                "emitters": emitters,
                "user_parameters": user_parameters[:24],
                "editable_parameters": sorted(
                    {str(x) for x in editable_parameters if str(x)}
                )[:24],
                "renderer_hints": sorted({str(x) for x in renderer_hints if str(x)})[
                    :24
                ],
                "module_hints": sorted({str(x) for x in module_hints if str(x)})[:24],
                "script_parameter_cues": sorted(
                    {str(x) for x in script_parameter_cues if str(x)}
                )[:24],
                "likely_tweak_points": likely_tweak_points,
                "warnings": warnings
                + ([str(response.get("error"))] if response.get("error") else []),
                "recommended_followups": [
                    "Prefer exposed/editable parameters before stack or module rewrites.",
                    "Duplicate the Niagara system to a prototype location before structural edits.",
                    "Use stronger reasoning for multi-emitter stack rewrites or coordinated parameter changes.",
                ],
            }
        )
        result["summary"] = (
            f"Niagara {result.get('asset_name') or asset_path}"
            f" | emitters: {len(emitters)}"
            f" | user params: {len(user_parameters)}"
            f" | editable cues: {len(result['editable_parameters'])}"
            f" | renderer hints: {len(result['renderer_hints'])}"
        )
        result["highlights"] = {
            "emitters": compact_names(emitters, limit=8),
            "user_parameters": [str(x) for x in user_parameters[:8]],
            "editable_parameters": result["editable_parameters"][:8],
            "renderers": result["renderer_hints"][:8],
            "modules": result["module_hints"][:8],
            "script_parameter_cues": result["script_parameter_cues"][:8],
        }
        if not response.get("ok") and not result["warnings"]:
            result["warnings"] = ["Niagara live inspect failed"]
        return result
