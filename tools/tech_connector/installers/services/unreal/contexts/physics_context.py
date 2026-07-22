from __future__ import annotations

from tech_connector.services.unreal.contexts.common import (
    basic_asset_context,
    compact_names,
    execute_python_json,
)


class PhysicsContextBuilder:
    def __init__(self, scanner):
        self.scanner = scanner

    def build(self, asset_path: str, focus: str = "physics"):
        result = basic_asset_context(asset_path, "physics", focus=focus)
        script = f"""
import json
import unreal

asset_path = {asset_path!r}
out = {{
    "asset_path": asset_path,
    "asset_name": "",
    "asset_class": "",
    "bodies": [],
    "constraints": [],
    "profile_names": [],
    "linked_skeletal_mesh": "",
    "cloth_references": [],
    "chaos_references": [],
    "warnings": [],
}}

try:
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not asset:
        out["warnings"].append("Physics asset could not be loaded")
    else:
        try:
            out["asset_name"] = asset.get_name()
        except Exception:
            pass
        try:
            out["asset_class"] = asset.get_class().get_name()
        except Exception:
            pass

        for attr in ("skeletal_body_setups", "body_setups"):
            try:
                bodies = asset.get_editor_property(attr)
                for body in bodies or []:
                    entry = {{
                        "name": "",
                        "bone": "",
                        "physics_type": "",
                        "collision_trace": "",
                        "mass": None,
                        "consider_for_bounds": None,
                        "linear_damping": None,
                        "angular_damping": None,
                    }}
                    try:
                        entry["name"] = str(body.get_name())
                    except Exception:
                        pass
                    try:
                        entry["bone"] = str(body.get_editor_property("bone_name"))
                    except Exception:
                        pass
                    try:
                        entry["physics_type"] = str(body.get_editor_property("physics_type"))
                    except Exception:
                        pass
                    try:
                        entry["collision_trace"] = str(body.get_editor_property("collision_trace_flag"))
                    except Exception:
                        pass
                    try:
                        entry["consider_for_bounds"] = bool(body.get_editor_property("consider_for_bounds"))
                    except Exception:
                        pass
                    try:
                        agg = body.get_editor_property("default_instance")
                        if agg:
                            try:
                                entry["mass"] = agg.get_editor_property("mass_in_kg_override")
                            except Exception:
                                pass
                            try:
                                entry["linear_damping"] = agg.get_editor_property("linear_damping")
                            except Exception:
                                pass
                            try:
                                entry["angular_damping"] = agg.get_editor_property("angular_damping")
                            except Exception:
                                pass
                    except Exception:
                        pass
                    out["bodies"].append(entry)
                break
            except Exception:
                pass

        for attr in ("constraint_setup", "constraint_setups"):
            try:
                constraints = asset.get_editor_property(attr)
                for constraint in constraints or []:
                    entry = {{
                        "name": "",
                        "default_profile": "",
                        "disable_collision": None,
                        "angular_swing1_motion": "",
                        "angular_swing2_motion": "",
                        "angular_twist_motion": "",
                        "linear_limit": "",
                    }}
                    try:
                        entry["name"] = str(constraint.get_name())
                    except Exception:
                        pass
                    try:
                        tpl = constraint.get_editor_property("default_instance")
                        if tpl:
                            try:
                                entry["default_profile"] = str(tpl.get_editor_property("profile_instance"))
                            except Exception:
                                pass
                            for src, dst in (
                                ("disable_collision", "disable_collision"),
                                ("angular_swing1_motion", "angular_swing1_motion"),
                                ("angular_swing2_motion", "angular_swing2_motion"),
                                ("angular_twist_motion", "angular_twist_motion"),
                                ("linear_limit_type", "linear_limit"),
                            ):
                                try:
                                    entry[dst] = str(tpl.get_editor_property(src))
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    out["constraints"].append(entry)
                break
            except Exception:
                pass

        for attr in ("constraint_profiles", "physical_animation_profiles"):
            try:
                profiles = asset.get_editor_property(attr)
                for profile in profiles or []:
                    out["profile_names"].append(str(profile))
            except Exception:
                pass

        try:
            registry = unreal.AssetRegistryHelpers.get_asset_registry()
            referencers = registry.get_referencers(asset_path.split('.', 1)[0], unreal.AssetRegistryDependencyOptions())
            for ref in referencers or []:
                ref_text = str(ref)
                lower = ref_text.lower()
                if any(token in lower for token in ("sk_", "skeletalmesh", "skeletal_mesh")):
                    out["linked_skeletal_mesh"] = out["linked_skeletal_mesh"] or ref_text
                if any(token in lower for token in ("cloth", "clothing", "chaoscloth")):
                    out["cloth_references"].append(ref_text)
                if "chaos" in lower:
                    out["chaos_references"].append(ref_text)
        except Exception as exc:
            out["warnings"].append("referencer query failed: " + str(exc))
except Exception as exc:
    out["warnings"].append(str(exc))

print(json.dumps(out))
"""
        response = execute_python_json(self.scanner, script, timeout=12.0)
        data = response.get("data") or {}
        bodies = list(data.get("bodies") or [])
        constraints = list(data.get("constraints") or [])
        profile_names = list(data.get("profile_names") or [])
        cloth_references = list(data.get("cloth_references") or [])
        chaos_references = list(data.get("chaos_references") or [])
        warnings = list(data.get("warnings") or [])
        if response.get("error"):
            warnings.append(str(response.get("error")))
        likely_tweak_points = []
        if bodies:
            likely_tweak_points.append("body_values")
        if any(body.get("mass") is not None for body in bodies):
            likely_tweak_points.append("mass")
        if constraints:
            likely_tweak_points.append("constraint_limits")
        if profile_names:
            likely_tweak_points.append("profiles")
        result.update(
            {
                "asset_name": data.get("asset_name") or asset_path,
                "asset_class": data.get("asset_class"),
                "bodies": bodies,
                "constraints": constraints,
                "profile_names": profile_names[:20],
                "linked_skeletal_mesh": data.get("linked_skeletal_mesh") or "",
                "cloth_references": cloth_references[:20],
                "chaos_references": chaos_references[:20],
                "likely_tweak_points": likely_tweak_points,
                "warnings": warnings,
                "recommended_followups": [
                    "Inspect specific bodies for mass, damping, and collision before changing values.",
                    "Validate constraint motion modes and collision settings before ragdoll tuning.",
                    "Prefer explicit per-body/per-constraint plans for ragdoll tuning instead of bulk mutation.",
                ],
            }
        )
        result["summary"] = (
            f"Physics {result.get('asset_name') or asset_path}"
            f" | bodies: {len(bodies)}"
            f" | constraints: {len(constraints)}"
            f" | profiles: {len(profile_names)}"
        )
        result["highlights"] = {
            "bodies": compact_names(bodies, limit=8),
            "constraints": compact_names(constraints, limit=8),
            "profiles": [str(x) for x in profile_names[:8]],
            "cloth_refs": [str(x) for x in cloth_references[:6]],
            "chaos_refs": [str(x) for x in chaos_references[:6]],
        }
        return result
