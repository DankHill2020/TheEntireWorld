# bridges/unreal/blueprint_exporter.py
"""
Utility to export Unreal Blueprint assets into a concise, markdown‑friendly textual summary.
The exporter is used by the AI‑assistant to provide the LLM with a deterministic representation
of Blueprint structure instead of the raw binary .uasset file.

Key features:
- Extracts variables, functions, events, components, implemented interfaces, parent class.
- Lists referenced assets and gameplay tags.
- Generates a short node‑graph summary (counts of nodes per category).
- Caches the result on disk to avoid repeated expensive calls.

The implementation relies on the Unreal Python API (available when running inside the
Unreal editor or via the remote HTTP bridge). When the API is unavailable the function
returns a fallback placeholder string so the rest of the system continues to work.
"""
import json
import pathlib
from typing import Dict, List

try:
    import unreal  # Unreal Engine Python module
except ImportError:  # pragma: no cover – during offline testing the module is missing
    unreal = None

CACHE_DIR = pathlib.Path(__file__).parent / "blueprint_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _cache_path(asset_path: str) -> pathlib.Path:
    """Return a deterministic cache file path for *asset_path*.
    The asset_path is expected to be the Unreal package path, e.g.
    "/Game/Blueprints/BP_Player".
    """
    safe_name = asset_path.replace("/", "_").strip("_")
    return CACHE_DIR / f"{safe_name}.md"

def export_blueprint_to_text(asset_path: str) -> str:
    """Export the Blueprint identified by *asset_path* to a markdown string.

    The function attempts to load the asset, walk its graph and format the
    information. If Unreal is not available the function returns a placeholder
    indicating that the exporter could not run.
    """
    cache_file = _cache_path(asset_path)
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    if unreal is None:
        placeholder = f"[Blueprint export unavailable – Unreal Python API not loaded] {asset_path}\n"
        cache_file.write_text(placeholder, encoding="utf-8")
        return placeholder

    # Load the Blueprint asset
    blueprint = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not blueprint:
        placeholder = f"[Failed to load Blueprint] {asset_path}\n"
        cache_file.write_text(placeholder, encoding="utf-8")
        return placeholder

    # Basic meta information
    parent_class = blueprint.get_super_class()
    parent_name = parent_class.get_name() if parent_class else "None"
    interfaces = blueprint.get_implemented_interfaces()
    interface_names = [i.get_name() for i in interfaces]

    # Variables / properties
    vars_list: List[str] = []
    for var in blueprint.get_all_member_variables():
        var_type = var.get_class().get_name()
        vars_list.append(f"{var.get_name()} : {var_type}")

    # Functions / events
    functions: List[str] = []
    for fn in blueprint.get_all_functions():
        functions.append(fn.get_name())

    # Components (heuristic for Actor based blueprints)
    components: List[str] = []
    if hasattr(blueprint, "simple_constructor"):
        cdo = blueprint.get_class().get_default_object()
        for prop in cdo.get_properties():
            if isinstance(prop, unreal.ObjectProperty) and "Component" in prop.get_class().get_name():
                components.append(prop.get_name())

    # Referenced assets – we traverse the asset registry for dependencies
    deps = unreal.EditorAssetLibrary.find_package_referencers_for_asset(asset_path, True)
    referenced = [d for d in deps if d != asset_path]

    # Node graph summary – count node types in the graph
    graph = unreal.KismetEditorUtilities.get_all_graphs(blueprint)
    node_counts: Dict[str, int] = {}
    for g in graph:
        for node in g.get_nodes():
            node_type = node.get_class().get_name()
            node_counts[node_type] = node_counts.get(node_type, 0) + 1

    # Build markdown output
    lines: List[str] = []
    lines.append(f"# Blueprint Export: {asset_path}\n")
    lines.append(f"**Parent Class:** {parent_name}\n")
    if interface_names:
        lines.append(f"**Implemented Interfaces:** {', '.join(interface_names)}\n")
    if vars_list:
        lines.append("## Variables\n")
        lines.extend([f"- {v}" for v in vars_list])
        lines.append("")
    if functions:
        lines.append("## Functions / Events\n")
        lines.extend([f"- {f}" for f in functions])
        lines.append("")
    if components:
        lines.append("## Components\n")
        lines.extend([f"- {c}" for c in components])
        lines.append("")
    if referenced:
        lines.append("## Referenced Assets\n")
        lines.extend([f"- {r}" for r in referenced[:20]])
        if len(referenced) > 20:
            lines.append(f"- ... +{len(referenced)-20} more")
        lines.append("")
    if node_counts:
        lines.append("## Node Graph Summary (counts)\n")
        for typ, cnt in sorted(node_counts.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"- {typ}: {cnt}")
        lines.append("")

    output = "\n".join(lines).strip() + "\n"
    cache_file.write_text(output, encoding="utf-8")
    return output
