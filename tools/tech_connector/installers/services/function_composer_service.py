"""Service for composing wrapper/orchestrator functions using local LLM integration."""

from tech_connector.knowledge.search import query_ollama_text
from tech_connector.services.settings_service import load_settings


def _normalize_items(items) -> list[dict]:
    if not items:
        return []
    if isinstance(items, dict):
        return [items]
    return [item for item in items if item]


def _format_capabilities(items, empty_message: str) -> str:
    from tech_connector.services.capability_service import format_contract, infer_symbol_contract

    normalized = _normalize_items(items)
    if not normalized:
        return empty_message

    sections = []
    for index, item in enumerate(normalized, start=1):
        contract = item.get("contract") or infer_symbol_contract(item)
        item = dict(item)
        item["contract"] = contract
        sections.append(
            f"Capability {index}\n"
            f"Name: {item.get('name', '')}\n"
            f"File: {item.get('file_path')}\n"
            f"Kind: {item.get('kind')}\n"
            f"Signature: {item.get('signature', '')}\n"
            f"Inferred Contract: {format_contract(item) or 'unknown'}\n"
            f"Code:\n```python\n{item.get('source', '')}\n```"
        )
    return "\n\n".join(sections)


def compose_composite_function(
    internal_func,
    external_tool,
    user_goal: str,
    workflow_links: str = "",
) -> str:
    """Compose a composite wrapper function using the selected dependencies and instructions."""

    internal_str = _format_capabilities(
        internal_func,
        "None selected (compose using local project context).",
    )
    external_str = _format_capabilities(
        external_tool,
        "None selected (compose using local project context).",
    )

    system_prompt = (
        "You are an expert PySide/Qt, Maya, and Unreal coding assistant.\n"
        "Your task is to generate a clean, safe Python wrapper or composite function that orchestrates "
        "multiple operations together based on the user's goal. The workflow may use more than two "
        "functions or tools in sequence.\n"
        "Name the generated public wrapper function with the suffix _git_ingest, for example "
        "image_to_mesh_workflow_git_ingest. Do not use this suffix for imported dependency names.\n"
        "Output ONLY the complete Python code block containing the new function, imports, and documentation. "
        "Do not explain the changes, do not output HTML/XML, just output the raw python code block."
    )
    
    user_prompt = (
        "I already have these internal project capabilities:\n"
        f"{internal_str}\n\n"
        "I need to use them with these ingested external capabilities:\n"
        f"{external_str}\n\n"
        f"User Goal: {user_goal}\n\n"
        "Required step links / data flow:\n"
        f"{workflow_links or 'Infer obvious links, but prefer explicit intermediate variables and validate each handoff.'}\n\n"
        "Create a new project function that combines the selected capabilities safely into one workflow.\n"
        "Use the inferred input/output contracts to connect selected functions. "
        "When a function's return is unknown, assign its result to a named variable and validate it before passing it onward. "
        "Preserve the intended order from the user's goal. Pass outputs between steps explicitly, "
        "using named intermediate variables such as image_path, mesh_path, mesh_object, hierarchy_root, or selected_bones. "
        "If a selected internal function returns a local file path, pass that exact path into the external/GitHub function "
        "that consumes it rather than reopening a picker. "
        "and include cleanup/finalization steps such as baking or removing temporary rig data when requested.\n"
        "Do not rewrite dependencies unless necessary.\n"
        "Prefer a wrapper/composition function.\n"
        "Include imports, error handling, clear parameters, and validation for missing files, missing mesh results, "
        "and missing bones/slots before running later steps."
    )

    try:
        settings = load_settings()
    except Exception:
        settings = {}
        
    model = settings.get("model") or "qwen2.5-coder:14b"
    general_model = settings.get("general_model") or model
    
    response = query_ollama_text(
        general_model,
        system_prompt,
        user_prompt,
        num_ctx=8192,
        num_predict=2048,
        timeout=60,
    )
    
    return response or ""
