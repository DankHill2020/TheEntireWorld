from __future__ import annotations

import json
import textwrap
from typing import Any, Dict


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def compact_names(items: Any, key: str = "name", limit: int = 12) -> list[str]:
    values = []
    for item in list(items or [])[:limit]:
        if isinstance(item, dict):
            values.append(str(item.get(key) or item))
        else:
            values.append(str(item))
    return values


def infer_asset_category(asset_path: str) -> str:
    text = str(asset_path or "")
    lower = text.lower()
    name = text.replace("\\", "/").rsplit("/", 1)[-1]
    short_name = name.split(".")[-1].lower()
    if any(
        token in lower
        for token in (
            "physicsasset",
            "physics_asset",
            "ragdoll",
            "phat",
            "chaoscloth",
            "clothasset",
            "/pha_",
            ".pha_",
            "/phys_",
            ".phys_",
        )
    ):
        return "physics"
    if any(token in lower for token in ("niagara", "/ns_", ".ns_", "/fx_", ".fx_")):
        return "niagara"
    if any(
        token in lower
        for token in ("ikretargeter", "retargeter", "/rtg_", ".rtg_", "retarget")
    ):
        return "retarget"
    if any(token in lower for token in ("ikrig", "ik_rig", "/ikr_", ".ikr_")):
        return "ik_rig"
    if any(
        token in lower
        for token in (
            "posesearch",
            "motionmatching",
            "motion_matching",
            "pose_search",
            "/ps_",
            ".ps_",
            "/mm_",
            ".mm_",
        )
    ):
        return "motion_matching"
    if any(token in lower for token in ("controlrig", "control_rig", "/cr_", ".cr_")):
        return "control_rig"
    if any(token in lower for token in ("blendspace", "blend_space", "/bs_", ".bs_")):
        return "blend_space"
    if any(token in lower for token in ("montage", "/am_", ".am_")):
        return "montage"
    if any(
        token in lower
        for token in ("animsequence", "animationsequence", "/a_", ".a_", "/an_", ".an_")
    ):
        return "anim_sequence"
    if any(
        token in lower for token in ("skeletalmesh", "skeletal_mesh", "/sk_", ".sk_")
    ):
        return "skeletal_mesh"
    if (
        short_name.startswith("abp_")
        or "animblueprint" in lower
        or "animation blueprint" in lower
    ):
        return "anim_blueprint"
    if short_name.startswith("bp_") or "blueprint" in lower:
        return "blueprint"
    if lower.endswith(".umap") or "/lvl_" in lower or ".lvl_" in lower:
        return "level"
    return "asset"


def basic_asset_context(
    asset_path: str, asset_category: str, focus: str = "selection"
) -> Dict[str, Any]:
    return {
        "asset_path": asset_path,
        "asset_category": asset_category,
        "focus": focus,
    }


def execute_python_json(scanner, source: str, timeout: float = 12.0) -> Dict[str, Any]:
    """Execute read-only DCC Python and return parsed JSON data.

    This goes through the shared DCC context-call registry so all hosts share the
    same bridge normalization rules. Unreal's HTTP bridge may return either a
    named function payload, a legacy eval string, or a dynamic-runner envelope;
    the registry normalizes those shapes before context builders consume them.
    """
    try:
        from services.dcc.context_call_registry import execute_python_context_json
    except Exception:
        try:
            from context_call_registry import execute_python_context_json
        except Exception:
            execute_python_context_json = None

    if execute_python_context_json is not None:
        response = execute_python_context_json(
            "unreal",
            scanner.bridge,
            textwrap.dedent(source),
            timeout=timeout,
        )
        payload = parse_jsonish(response.get("data"))
        if isinstance(payload, dict):
            return {
                "ok": bool(response.get("ok")),
                "data": payload,
                "error": response.get("error"),
            }
        return {
            "ok": bool(response.get("ok")),
            "data": {},
            "error": response.get("error") or str(payload),
        }

    # Last-resort fallback for older checkouts that do not yet have the shared
    # registry file copied into services/dcc.
    response = scanner.bridge.execute_python(
        textwrap.dedent(source), timeout=timeout, reset_globals=True
    )
    payload = parse_jsonish(response.get("data"))
    if isinstance(payload, dict) and "stdout" in payload:
        stdout_payload = None
        for line in reversed(str(payload.get("stdout") or "").splitlines()):
            parsed = parse_jsonish(line.strip())
            if isinstance(parsed, dict):
                stdout_payload = parsed
                break
        if isinstance(stdout_payload, dict):
            payload = stdout_payload
    if isinstance(payload, dict):
        return {
            "ok": bool(response.get("ok")),
            "data": payload,
            "error": response.get("error"),
        }
    return {
        "ok": bool(response.get("ok")),
        "data": {},
        "error": response.get("error") or str(payload),
    }


def resolve_unreal_object(scanner, kind: str, query: str = "selected", **kwargs) -> Dict[str, Any]:
    """Resolve a user-facing query into a typed Unreal handle through the bridge."""
    try:
        resolver = scanner.bridge.object_resolver()
        key = (kind or "").lower()
        if key in {"asset", "uasset", "object"}:
            return resolver.resolve_asset(
                query,
                expected_class=kwargs.get("expected_class", ""),
                directory=kwargs.get("directory", "/Game"),
                timeout=float(kwargs.get("timeout", 8.0)),
            )
        if key in {"actor", "level_actor"}:
            return resolver.resolve_actor(query, timeout=float(kwargs.get("timeout", 5.0)))
        if key in {"component", "actor_component"}:
            return resolver.resolve_component(
                kwargs.get("owner", "selected"),
                query,
                kwargs.get("component_class", ""),
                timeout=float(kwargs.get("timeout", 6.0)),
            )
        if key in {"control_rig", "controlrig", "control_rig_class"}:
            return resolver.resolve_control_rig(query, timeout=float(kwargs.get("timeout", 8.0)))
        return {"ok": False, "error": f"Unsupported Unreal resolver kind: {kind}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "kind": kind, "query": query}
