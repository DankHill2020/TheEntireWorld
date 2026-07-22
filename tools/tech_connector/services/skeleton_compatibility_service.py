"""Evidence-based Unreal skeleton compatibility checks.

This compatibility facade deliberately refuses to infer compatibility from asset
names. It accepts measured metadata supplied by Unreal, or reports the exact
missing evidence needed before an animation may be assigned.
"""

from __future__ import annotations

from typing import Any


class SkeletonCompatibilityService:
    """Compare observed animation and target skeleton identities."""

    def validate_manny_skeleton_compatibility(
        self,
        anim_sequence_path: str,
        target_abp_path: str = "/Game/Variant_Combat/Anims/ABP_Manny_Combat",
        *,
        observed_animation: dict[str, Any] | None = None,
        observed_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        animation = dict(observed_animation or {})
        target = dict(observed_target or {})
        animation_skeleton = str(animation.get("skeleton_path") or "")
        target_skeleton = str(target.get("skeleton_path") or "")
        evidence_complete = bool(animation_skeleton and target_skeleton)
        compatible = evidence_complete and animation_skeleton == target_skeleton
        return {
            "anim_sequence": anim_sequence_path,
            "target_abp": target_abp_path,
            "animation_skeleton": animation_skeleton,
            "target_skeleton": target_skeleton,
            "compatible": compatible,
            "retargeting_required": evidence_complete and not compatible,
            "evidence_complete": evidence_complete,
            "evidence_source": "live_unreal_metadata" if evidence_complete else "missing",
            "missing_evidence": [
                name
                for name, value in (
                    ("animation.skeleton_path", animation_skeleton),
                    ("target.skeleton_path", target_skeleton),
                )
                if not value
            ],
            "status_message": (
                "Live skeleton identities match."
                if compatible
                else (
                    "Live skeleton identities differ; validated retargeting is required."
                    if evidence_complete
                    else "Compatibility is unknown until Unreal returns both skeleton identities."
                )
            ),
        }

    def audit_system_animation_plugs(
        self,
        anim_map: dict[str, str],
        target_abp: str,
        *,
        observed_animations: dict[str, dict[str, Any]] | None = None,
        observed_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import json
        observations = dict(observed_animations or {})
        target = dict(observed_target or {})

        # If live metadata is missing but bridge is active, retrieve it dynamically
        if not target or not observations:
            try:
                from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge
                bridge = UnrealBridge()
                if bridge.find_port() is not None:
                    query_script = f"""import unreal, json
abp_path = "{target_abp}"
anim_map = {anim_map!r}
out = {{"abp_skeleton": None, "seq_skeletons": {{}}}}
try:
    abp = unreal.load_asset(abp_path)
    if abp:
        skel1 = abp.get_editor_property('target_skeleton')
        if skel1:
            out["abp_skeleton"] = skel1.get_path_name()
    for role, path in anim_map.items():
        seq = unreal.load_asset(path)
        if seq:
            skel2 = seq.get_skeleton()
            if skel2:
                out["seq_skeletons"][path] = skel2.get_path_name()
except Exception:
    pass
print(json.dumps(out))
"""
                    res = bridge.execute_python(query_script, timeout=5.0)
                    if res and res.get("ok"):
                        data = res.get("data")
                        if isinstance(data, dict):
                            if data.get("abp_skeleton") and not target:
                                target = {"skeleton_path": data["abp_skeleton"]}
                            for p, skel in data.get("seq_skeletons", {}).items():
                                observations.setdefault(p, {"skeleton_path": skel})
            except Exception:
                pass

        audits = [
            {
                "role": role,
                **self.validate_manny_skeleton_compatibility(
                    path,
                    target_abp,
                    observed_animation=observations.get(path) or observations.get(role),
                    observed_target=target,
                ),
            }
            for role, path in anim_map.items()
        ]
        return {
            "all_plugs_valid": bool(audits) and all(row["compatible"] for row in audits),
            "target_abp": target_abp,
            "total_plugs_checked": len(audits),
            "plug_audits": audits,
            "mutation_allowed": bool(audits) and all(row["compatible"] for row in audits),
        }
