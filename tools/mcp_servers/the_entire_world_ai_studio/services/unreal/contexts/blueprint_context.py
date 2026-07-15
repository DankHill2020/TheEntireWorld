from __future__ import annotations

from typing import Any, Dict

from services.unreal.contexts.common import compact_names, parse_jsonish


class BlueprintContextBuilder:
    def __init__(self, scanner):
        self.scanner = scanner

    def build(self, asset_path: str, focus: str = "blueprint") -> Dict[str, Any]:
        from router.command_router import CommandRouter

        result: Dict[str, Any] = {
            "asset_path": asset_path,
            "asset_category": "blueprint",
            "focus": focus,
            "summary": "",
            "functions": [],
            "graphs": [],
            "variables": [],
            "components": [],
            "dependencies": [],
            "referencers": [],
            "warnings": [],
        }
        label, ok, payload = CommandRouter().execute_unreal_operation(
            "blueprint.dynamic_inspect",
            {"asset_name": asset_path, "timeout": 12},
        )
        result["inspect_label"] = label
        result["inspect_ok"] = ok
        if not ok:
            result["warnings"].append(str(payload))
            result["summary"] = f"Blueprint inspect failed for {asset_path}"
            return result

        parsed = parse_jsonish(payload)
        data = parsed.get("data") if isinstance(parsed, dict) else {}
        data = data if isinstance(data, dict) else {}
        result.update(
            {
                "asset_name": data.get("asset_name"),
                "parent_class": data.get("parent_class"),
                "python_class": data.get("python_class"),
                "generated_class": data.get("generated_class"),
                "functions": list(data.get("functions") or []),
                "graphs": list(data.get("graphs") or []),
                "variables": list(data.get("variables") or []),
                "components": list(data.get("components") or []),
                "dependencies": list(data.get("dependencies") or []),
                "referencers": list(data.get("referencers") or []),
                "warnings": list(data.get("warnings") or []),
                "notes": list(data.get("notes") or []),
                "capability_plan": data.get("capability_plan") or {},
            }
        )
        function_names = compact_names(result["functions"], limit=10)
        graph_names = compact_names(result["graphs"], limit=10)
        result["summary"] = (
            f"Blueprint {data.get('asset_name') or asset_path}"
            f" | functions: {len(result['functions'])}"
            f" | graphs: {len(result['graphs'])}"
            f" | variables: {len(result['variables'])}"
        )
        result["highlights"] = {
            "functions": function_names,
            "graphs": graph_names,
            "components": compact_names(result["components"], limit=8),
        }
        try:
            from services.unreal.semantic_graph_service import build_semantic_graph_analysis

            result["semantic_graph"] = build_semantic_graph_analysis(
                focus or asset_path,
                context=result,
            )
        except Exception:
            result["semantic_graph"] = {}
        return result
