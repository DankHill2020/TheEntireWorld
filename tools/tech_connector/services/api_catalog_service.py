"""Official API catalog generation for headless/DCC function calls."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any

from tech_connector.models.constants import TOOLS_ROOT
from tech_connector.services.tool_discovery_service import extract_symbols_from_file


DCC_HOST_PACKAGES = {
    "maya": ("maya_tools",),
    "unreal": ("unreal_tools",),
    "blender": ("blender_tools",),
    "motionbuilder": ("motionbuilder_tools", "mobu_tools"),
    "substance_painter": ("substance_painter_tools",),
    "houdini": ("houdini_tools",),
    "unity": ("unity_tools",),
}

KNOWN_DCC_API_DEPENDENCIES = {
    "maya_tools.Rigging.create_rig.create_rig_from_mapping": [
        {
            "kind": "prerequisite",
            "entry_point": "maya_tools.Rigging.mocap.setup_hik.create_rig_mapping",
            "reason": "Produces body_joint_map and face_joint_map for create_rig_from_mapping.",
        }
    ],
}


def _module_from_path(path: Path, package: str) -> str:
    parts = list(path.with_suffix("").parts)
    if package in parts:
        return ".".join(parts[parts.index(package) :])
    return ".".join(path.with_suffix("").parts)


def _signature_from_symbol(symbol: dict[str, Any]) -> str:
    signature = str(symbol.get("signature") or "")
    if signature.startswith("def "):
        return signature[4:]
    if signature.startswith("async def "):
        return signature[10:]
    return signature


def _param_doc(param: dict[str, Any]) -> str:
    text = f"`{param.get('name', '')}`"
    annotation = str(param.get("annotation") or "").strip()
    default = str(param.get("default") or "").strip()
    if annotation:
        text += f" ({annotation})"
    if default:
        text += f", default `{default}`"
    else:
        text += ", required"
    return text


def _anchor_for_api_call(api_call: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(api_call or "")).strip().lower()
    text = text.replace("`", "")
    text = text.replace("...", "")
    text = re.sub(r"[()'\",]", "", text)
    text = re.sub(r"[^a-z0-9_. -]+", "", text)
    text = text.replace(".", "")
    text = re.sub(r"\s+", "-", text)
    text = text.replace(" ", "-")
    return "#" + text.strip("-")


def _anchor_for_heading(text: str) -> str:
    text = str(text or "").strip().lower()
    text = re.sub(r"[^a-z0-9 _-]+", "", text)
    text = re.sub(r"\s+", "-", text)
    return "#" + text.strip("-")


def _markdown_file_link(path_with_line: str) -> str:
    text = str(path_with_line or "")
    if ":" not in text:
        return f"`{text}`"
    path_text, line_text = text.rsplit(":", 1)
    path = Path(path_text)
    label = f"{path.name}:{line_text}" if path.name else text
    link_path = path_text.replace("\\", "/")
    if " " in path_text:
        target = f"<{link_path}:{line_text}>"
    else:
        target = f"{link_path}:{line_text}"
    return f"[{label}]({target})"


def _api_call_for_item(item: dict[str, Any]) -> str:
    api_names = item.get("api_names") or []
    if api_names:
        return f"api.dcc.{item['host']}.{api_names[0]}(...)"
    return f"api.dcc.{item['host']}.call({item['entry_point']!r}, ...)"


def _is_module_level_function(symbol: dict[str, Any]) -> bool:
    try:
        path = Path(str(symbol.get("file_path") or ""))
        lineno = int(symbol.get("lineno") or 0)
        if lineno <= 0:
            return False
        line = path.read_text(encoding="utf-8", errors="replace").splitlines()[lineno - 1]
        stripped = line.lstrip()
        return line == stripped and (stripped.startswith("def ") or stripped.startswith("async def "))
    except Exception:
        return False


def discover_dcc_api_catalog(
    *,
    tools_root: str | Path | None = None,
    aliases: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Discover public DCC functions and their official API call forms."""
    root = Path(tools_root or TOOLS_ROOT)
    aliases = aliases or {}
    hosts: dict[str, list[dict[str, Any]]] = {}

    for host, packages in DCC_HOST_PACKAGES.items():
        symbols: list[dict[str, Any]] = []
        for package in packages:
            package_dir = root / package
            if not package_dir.exists():
                continue
            for path in package_dir.rglob("*.py"):
                if "__pycache__" in path.parts or path.name == "__init__.py":
                    continue
                for symbol in extract_symbols_from_file(path):
                    if symbol.get("kind") != "function":
                        continue
                    if not _is_module_level_function(symbol):
                        continue
                    name = str(symbol.get("name") or "")
                    if not name or name.startswith("_"):
                        continue
                    module = _module_from_path(Path(symbol.get("file_path") or path), package)
                    entry_point = f"{module}.{name}"
                    symbols.append(
                        {
                            "host": host,
                            "name": name,
                            "entry_point": entry_point,
                            "signature": _signature_from_symbol(symbol),
                            "params": list(symbol.get("params") or []),
                            "outputs": list(symbol.get("outputs") or []),
                            "docstring": str(symbol.get("docstring") or "").strip(),
                            "file_path": str(symbol.get("file_path") or path),
                            "line": int(symbol.get("lineno") or 0),
                        }
                    )
        counts = Counter(item["name"] for item in symbols)
        alias_by_target: dict[str, list[str]] = {}
        for alias, target in (aliases.get(host) or {}).items():
            alias_by_target.setdefault(target, []).append(alias)
        by_entry = {item["entry_point"]: item for item in symbols}
        by_module: dict[str, list[dict[str, Any]]] = {}
        for item in symbols:
            module = item["entry_point"].rsplit(".", 1)[0]
            by_module.setdefault(module, []).append(item)
        for item in symbols:
            names = list(alias_by_target.get(item["entry_point"], []))
            if counts[item["name"]] == 1 and item["name"] not in names:
                names.append(item["name"])
            item["api_names"] = sorted(names)
            item["api_call"] = _api_call_for_item(item)
            item["ambiguous_name"] = counts[item["name"]] > 1
        for item in symbols:
            item["related_functions"] = _related_functions_for_item(
                item,
                by_entry=by_entry,
                by_module=by_module,
                alias_by_target=alias_by_target,
            )
        hosts[host] = sorted(symbols, key=lambda item: (not bool(item["api_names"]), item["name"].lower(), item["entry_point"]))

    return {
        "schema": "tech_connector.api_catalog.v1",
        "tools_root": str(root),
        "hosts": hosts,
    }


def _related_functions_for_item(
    item: dict[str, Any],
    *,
    by_entry: dict[str, dict[str, Any]],
    by_module: dict[str, list[dict[str, Any]]],
    alias_by_target: dict[str, list[str]],
) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, entry_point: str, reason: str) -> None:
        if not entry_point or entry_point == item["entry_point"] or entry_point in seen:
            return
        seen.add(entry_point)
        target = by_entry.get(entry_point) or {}
        if target and not target.get("api_call"):
            target["api_call"] = _api_call_for_item(target)
        related.append(
            {
                "kind": kind,
                "name": target.get("name") or entry_point.rsplit(".", 1)[-1],
                "entry_point": entry_point,
                "api_call": target.get("api_call", ""),
                "api_names": sorted(alias_by_target.get(entry_point, [])),
                "source": f"{target.get('file_path', '')}:{target.get('line', 0)}" if target else "",
                "reason": reason,
            }
        )

    for dep in KNOWN_DCC_API_DEPENDENCIES.get(item["entry_point"], []):
        add(str(dep.get("kind") or "related"), str(dep.get("entry_point") or ""), str(dep.get("reason") or "Known related function."))

    for source, deps in KNOWN_DCC_API_DEPENDENCIES.items():
        if any(dep.get("entry_point") == item["entry_point"] for dep in deps):
            add("consumer", source, "Consumes this function's output in a known workflow.")

    module = item["entry_point"].rsplit(".", 1)[0]
    name_tokens = {token for token in item["name"].lower().split("_") if len(token) > 2}
    same_module = []
    for candidate in by_module.get(module, []):
        if candidate["entry_point"] == item["entry_point"]:
            continue
        candidate_tokens = {token for token in candidate["name"].lower().split("_") if len(token) > 2}
        overlap = len(name_tokens & candidate_tokens)
        if overlap:
            same_module.append((overlap, candidate))
    same_module.sort(key=lambda pair: (-pair[0], pair[1]["name"].lower()))
    for _score, candidate in same_module[:5]:
        add("same_module", candidate["entry_point"], "Shares module and name terms; may be useful in the same workflow.")

    return related


def resolve_dcc_api_name(host: str, name: str, *, aliases: dict[str, dict[str, str]] | None = None) -> str:
    host = str(host or "").strip().lower().replace(" ", "_")
    key = str(name or "").strip()
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    aliases = aliases or {}
    if normalized in (aliases.get(host) or {}):
        return aliases[host][normalized]
    if "." in key:
        return key
    catalog = discover_dcc_api_catalog(aliases=aliases)
    matches = []
    for item in catalog.get("hosts", {}).get(host, []):
        api_names = {str(alias).lower() for alias in item.get("api_names") or []}
        if normalized in api_names or normalized == str(item.get("name") or "").lower():
            matches.append(item)
    unique = {item["entry_point"] for item in matches}
    if len(unique) == 1:
        return matches[0]["entry_point"]
    if len(unique) > 1:
        options = ", ".join(sorted(unique)[:8])
        raise ValueError(f"Ambiguous DCC API function {host}.{name}; use api.dcc.{host}.call(full_path, ...). Options: {options}")
    raise ValueError(f"Unknown DCC API function {host}.{name}; use api.dcc.{host}.call(full_path, ...) or regenerate the API catalog.")


def render_api_function_catalog_markdown(catalog: dict[str, Any], *, max_functions_per_host: int | None = None) -> str:
    lines = [
        "# Tech Connector API Function Catalog",
        "",
        "This file is generated from the current DCC tool source. Friendly calls use",
        "`api.dcc.<host>.<function>(...)` when the function name is unique or has an",
        "official alias. Ambiguous functions are still callable with",
        "`api.dcc.<host>.call(\"full.package.path\", ...)`.",
        "",
        "## DCC Index",
        "",
    ]
    for host, items in sorted((catalog.get("hosts") or {}).items()):
        lines.append(f"- [{host}](#{host}) ({len(items)} functions)")
    lines.append("")
    for host, items in sorted((catalog.get("hosts") or {}).items()):
        lines.extend([f"## {host}", ""])
        if not items:
            lines.extend(["No public functions discovered.", ""])
            continue
        selected = items[:max_functions_per_host] if max_functions_per_host else items
        for item in selected:
            lines.append(f"### `{item['api_call']}`")
            lines.append("")
            lines.append(f"- Target: `{item['entry_point']}`")
            if item.get("signature"):
                lines.append(f"- Signature: `{item['signature']}`")
            if item.get("api_names"):
                lines.append("- API names: " + ", ".join(f"`{name}`" for name in item["api_names"]))
            if item.get("ambiguous_name") and not item.get("api_names"):
                lines.append("- Name status: ambiguous; use the full target path.")
            if item.get("params"):
                lines.append("- Args:")
                for param in item["params"]:
                    lines.append(f"  - {_param_doc(param)}")
            else:
                lines.append("- Args: none")
            if item.get("related_functions"):
                lines.append("- Related functions:")
                for related in item["related_functions"]:
                    api_call = related.get("api_call") or ""
                    anchor = _anchor_for_api_call(api_call) if api_call else ""
                    api_label = f"[`{api_call}`]({anchor})" if api_call else f"`{related['entry_point']}`"
                    source = related.get("source") or ""
                    source_text = f"; source {_markdown_file_link(source)}" if source and not source.endswith(":0") else ""
                    lines.append(
                        f"  - {related['kind']}: {api_label} -> `{related['entry_point']}` - "
                        f"{related['reason']}{source_text}"
                    )
            doc = str(item.get("docstring") or "").strip()
            if doc:
                first = " ".join(doc.split())[:500]
                lines.append(f"- Description: {first}")
            source_ref = f"{item.get('file_path', '')}:{item.get('line', 0)}"
            lines.append(f"- Source: {_markdown_file_link(source_ref)}")
            lines.append("")
        if max_functions_per_host and len(items) > len(selected):
            lines.append(f"_Catalog truncated: {len(items) - len(selected)} additional functions not shown._")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
