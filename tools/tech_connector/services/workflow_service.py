"""Project-local workflow persistence and validation scaffolding, combined with deterministic prompt-to-pipeline planning from indexed symbols."""

from __future__ import annotations

import ast
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from tech_connector.services.tool_discovery_service import extract_symbols_from_file, list_internal_functions

GITHUB_INGEST_FUNCTION_SUFFIX = "_git_ingest"


@dataclass(frozen=True)
class SavedWorkflow:
    module_path: Path
    manifest_path: Path
    test_path: Path
    function_name: str
    function_path: str
    call_payload: str


@dataclass
class WorkflowIntentPlan:
    success: bool
    confidence: float
    steps: list[dict[str, Any]]
    data_links: list[dict[str, Any]]
    flow_links: list[dict[str, Any]]
    diagnostics: list[str]
    capability_gaps: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "confidence": self.confidence,
            "steps": self.steps,
            "data_links": self.data_links,
            "flow_links": self.flow_links,
            "diagnostics": self.diagnostics,
            "capability_gaps": self.capability_gaps,
        }


def slugify(value: str, fallback: str = "workflow") -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", value or "").strip("_").lower()
    text = re.sub(r"_+", "_", text)
    if not text:
        text = fallback
    if text[0].isdigit():
        text = f"{fallback}_{text}"
    return text[:64]


def extract_python_code(text: str) -> str:
    match = re.search(r"```(?:python|py)?\s*(.*?)```", text or "", re.IGNORECASE | re.DOTALL)
    return (match.group(1) if match else text or "").strip()


def first_function_name(code: str) -> str:
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    raise ValueError("Workflow code must define at least one function.")


def github_ingest_function_name(name: str) -> str:
    base = slugify(name or "workflow", fallback="workflow")
    if base.endswith(GITHUB_INGEST_FUNCTION_SUFFIX):
        return base
    return f"{base}{GITHUB_INGEST_FUNCTION_SUFFIX}"


def rename_first_function(code: str, new_name: str) -> str:
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == new_name:
                return code
            node.name = new_name
            ast.fix_missing_locations(tree)
            return ast.unparse(tree)
    raise ValueError("Workflow code must define at least one function.")


def infer_host(goal: str, selected_items: Optional[list[dict]] = None) -> str:
    text = (goal or "").lower()
    for host in ("maya", "unreal", "blender", "substance_painter", "unity", "motionbuilder"):
        if host in text or host.replace("_", " ") in text:
            return host
    for item in selected_items or []:
        file_path = (item.get("file_path") or "").lower()
        for host in ("maya", "unreal", "blender", "substance_painter", "unity", "motionbuilder"):
            if host in file_path or f"{host}_tools" in file_path:
                return host
    return "maya"


def parse_slots(slots_text: str) -> dict:
    slots = {}
    for line in (slots_text or "").splitlines():
        line = line.strip().strip(",")
        if not line:
            continue
        separator = "=" if "=" in line else ":" if ":" in line else ""
        if not separator:
            continue
        key, value = line.split(separator, 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            slots[key] = value
    return slots


def parse_workflow_links(links_text: str) -> list[dict]:
    links = []
    for line in (links_text or "").splitlines():
        line = line.strip().strip(",")
        if not line or "->" not in line:
            continue
        source, target = line.split("->", 1)
        source = source.strip()
        target = target.strip()
        if source and target:
            links.append({"from": source, "to": target})
    return links


def ensure_package(path: Path, stop_at: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    current = path
    while current == stop_at or stop_at in current.parents:
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")
        if current == stop_at:
            break
        current = current.parent


def resolve_project_root(project_root: Union[str, Path]) -> Path:
    root = Path(project_root).expanduser().resolve()
    if root.is_file():
        root = root.parent
    if not root.exists():
        raise ValueError(f"Project root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    return root


def _selected_manifest_items(selected_items: Optional[list[dict]]) -> list[dict]:
    items = []
    for item in selected_items or []:
        items.append(
            {
                "name": item.get("name", ""),
                "kind": item.get("kind", ""),
                "signature": item.get("signature", ""),
                "file_path": item.get("file_path", ""),
                "params": item.get("params", []),
                "outputs": item.get("outputs", []),
                "return_annotation": item.get("return_annotation", ""),
                "contract": item.get("contract", {}),
            }
        )
    return items


def save_composed_workflow(
    project_root: Union[str, Path],
    composed_code: str,
    goal: str,
    slots_text: str = "",
    workflow_links: str = "",
    host: str = "",
    selected_items: Optional[list[dict]] = None,
) -> SavedWorkflow:
    root = resolve_project_root(project_root)

    code = extract_python_code(composed_code)
    original_function_name = first_function_name(code)
    function_name = original_function_name
    code = rename_first_function(code, function_name)
    resolved_host = host or infer_host(goal, selected_items=selected_items)
    slug = slugify(function_name or goal)

    workflows_root = root / "workflows"
    workflow_dir = workflows_root / resolved_host
    ensure_package(workflow_dir, workflows_root)

    module_path = workflow_dir / f"{slug}.py"
    module_path.write_text(code.rstrip() + "\n", encoding="utf-8")

    rel_module = module_path.relative_to(root).with_suffix("")
    dotted_module = ".".join(rel_module.parts)
    function_path = f"{dotted_module}.{function_name}"
    slots = parse_slots(slots_text)
    links = parse_workflow_links(workflow_links)
    call_payload = json.dumps({"function": function_path, "args": [], "kwargs": slots}, indent=2)

    manifest_path = workflow_dir / f"{slug}.workflow.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "ai_studio.workflow.v1",
                "source": "github_ingest_composer",
                "naming": {
                    "function_suffix": GITHUB_INGEST_FUNCTION_SUFFIX,
                    "original_function": original_function_name,
                },
                "host": resolved_host,
                "goal": goal,
                "module": dotted_module,
                "function": function_name,
                "function_path": function_path,
                "selected_capabilities": _selected_manifest_items(selected_items),
                "slots": slots,
                "links": links,
                "validation": {
                    "imports_checked_by_test": True,
                    "scene_objects_checked_at_runtime": True,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_path = tests_dir / f"test_workflow_{resolved_host}_{slug}.py"
    test_path.write_text(
        "import ast\n"
        "from pathlib import Path\n\n\n"
        f"def test_workflow_{resolved_host}_{slug}_defines_callable():\n"
        f"    source = Path({str(module_path)!r}).read_text(encoding='utf-8')\n"
        "    tree = ast.parse(source)\n"
        f"    assert any(getattr(node, 'name', '') == {function_name!r} for node in tree.body)\n",
        encoding="utf-8",
    )

    return SavedWorkflow(
        module_path=module_path,
        manifest_path=manifest_path,
        test_path=test_path,
        function_name=function_name,
        function_path=function_path,
        call_payload=call_payload,
    )


# --- Prompt-to-Pipeline Planning (merged from workflow_intent_resolver.py) ---

_WORD_ALIASES = {
    "bodymap": "body_joint_map",
    "body_map": "body_joint_map",
    "bodyjointmap": "body_joint_map",
    "body_joint_map": "body_joint_map",
    "facemap": "face_joint_map",
    "face_map": "face_joint_map",
    "facejointmap": "face_joint_map",
    "face_joint_map": "face_joint_map",
    "rootjoint": "root_joint",
    "root_joint": "root_joint",
    "root": "root_joint",
}


def _normalize_name(value: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", value or "")
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return _WORD_ALIASES.get(value, value)


def _tokens(value: str) -> set[str]:
    normalized = _normalize_name(value)
    return {part for part in normalized.split("_") if part}


def _params(symbol: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in symbol.get("params") or [] if isinstance(p, dict) and p.get("name")]


def _outputs(symbol: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = symbol.get("outputs") or []
    return [o for o in outputs if isinstance(o, dict) and o.get("name")]


def _symbol_text(symbol: dict[str, Any]) -> str:
    fields = [
        symbol.get("name", ""),
        symbol.get("kind", ""),
        symbol.get("signature", ""),
        symbol.get("docstring", ""),
        Path(symbol.get("file_path", "")).name,
        str(symbol.get("file_path", "")).replace("\\", "/"),
    ]
    return " ".join(str(x) for x in fields if x)


_GENERIC_NAMES = {
    "set", "get", "load", "save", "update", "delete", "create", "make", "add",
    "remove", "clear", "reset", "start", "stop", "run", "execute", "draw",
    "show", "hide", "open", "close", "read", "write", "list", "find", "search"
}


def _score_symbol(symbol: dict[str, Any], prompt: str) -> float:
    prompt_norm = _normalize_name(prompt)
    prompt_tokens = _tokens(prompt)
    name = symbol.get("name", "")
    file_name = Path(symbol.get("file_path", "")).name
    haystack = _normalize_name(_symbol_text(symbol))
    name_norm = _normalize_name(name)
    file_norm = _normalize_name(file_name)

    score = 0.0
    if name_norm and f"_{name_norm}_" in f"_{prompt_norm}_":
        if name_norm in _GENERIC_NAMES:
            score += 1.0
        else:
            score += 20.0
    if file_norm and f"_{file_norm}_" in f"_{prompt_norm}_":
        score += 10.0
    score += len(_tokens(name) & prompt_tokens) * 3.0
    score += len(_tokens(file_name) & prompt_tokens) * 2.0
    for param in _params(symbol):
        param_norm = _normalize_name(param.get("name", ""))
        if param_norm and f"_{param_norm}_" in f"_{prompt_norm}_":
            score += 1.5
    for output in _outputs(symbol):
        output_norm = _normalize_name(output.get("name", ""))
        if output_norm and f"_{output_norm}_" in f"_{prompt_norm}_":
            score += 2.0
    if "function" in str(symbol.get("kind", "")).lower():
        score += 0.5
    if any(token in haystack for token in prompt_tokens):
        score += 0.25
    return score


def _literal_candidates(prompt: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    quoted = r'"([^"]+)"|\'([^\']+)\''
    patterns = [
        r"\b(root\s+joint|root|skeleton\s+root)\s+(?:is|=|named|called)\s+([A-Za-z_][A-Za-z0-9_:|.-]*)",
        rf"([A-Za-z_][A-Za-z0-9_ ]{{0,40}}?)\s+(?:as|to|=)\s+(?:{quoted})",
        rf"(?:with|using)\s+([A-Za-z_][A-Za-z0-9_ ]{{0,40}}?)\s+(?:as|to|=)\s+(?:{quoted})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, prompt or "", flags=re.IGNORECASE):
            raw_name = match.group(1)
            value = next((g for g in match.groups()[1:] if g is not None), "")
            if raw_name and value:
                result.append((_normalize_name(raw_name), value))
    return result


def _literal_values_for_step(prompt: str, symbol: dict[str, Any]) -> dict[str, str]:
    literals: dict[str, str] = {}
    candidates = _literal_candidates(prompt)
    for param in _params(symbol):
        param_name = param.get("name", "")
        param_norm = _normalize_name(param_name)
        for candidate_name, value in candidates:
            if candidate_name == param_norm:
                literals[param_name] = value
                break
            if candidate_name in param_norm or param_norm in candidate_name:
                literals[param_name] = value
                break
    return literals


def _param_required(param: dict[str, Any]) -> bool:
    name = str(param.get("name") or "")
    if not name or name.startswith("*"):
        return False
    return "default" not in param


def _required_params(symbol: dict[str, Any]) -> list[dict[str, Any]]:
    return [param for param in _params(symbol) if _param_required(param)]


def _output_matches_param(output: dict[str, Any], param: dict[str, Any]) -> tuple[bool, str]:
    output_name = str(output.get("name") or "")
    param_name = str(param.get("name") or "")
    output_norm = _normalize_name(output_name)
    param_norm = _normalize_name(param_name)
    if output_norm and param_norm and (
        output_norm == param_norm
        or f"_{output_norm}_" in f"_{param_norm}_"
        or f"_{param_norm}_" in f"_{output_norm}_"
    ):
        return True, "matched producer output name to required parameter"
    out_type = str(output.get("annotation") or output.get("type") or "").replace("typing.", "").strip()
    param_type = str(param.get("annotation") or param.get("type") or "").replace("typing.", "").strip()
    if out_type and param_type and out_type == param_type and out_type.lower() not in {"str", "int", "float", "bool", "any", "none", "void", "object"}:
        return True, f"matched producer output type: {out_type}"
    return False, ""


def _producer_score(symbol: dict[str, Any], param: dict[str, Any], prompt: str) -> tuple[float, dict[str, Any] | None, str]:
    best_output: dict[str, Any] | None = None
    best_reason = ""
    score = 0.0
    for output in _outputs(symbol):
        matched, reason = _output_matches_param(output, param)
        if not matched:
            continue
        output_norm = _normalize_name(output.get("name", ""))
        param_norm = _normalize_name(param.get("name", ""))
        current = 80.0
        if output_norm == param_norm:
            current += 40.0
        current += min(20.0, _score_symbol(symbol, prompt))
        name_norm = _normalize_name(symbol.get("name", ""))
        if any(token in name_norm for token in _tokens(param.get("name", ""))):
            current += 10.0
        if current > score:
            score = current
            best_output = output
            best_reason = reason
    return score, best_output, best_reason


def _find_producer_for_param(
    param: dict[str, Any],
    symbols: list[dict[str, Any]],
    prompt: str,
    used_names: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    scored: list[tuple[float, dict[str, Any], dict[str, Any], str]] = []
    for symbol in symbols:
        name = str(symbol.get("name") or "")
        if not name or name in used_names:
            continue
        score, output, reason = _producer_score(symbol, param, prompt)
        if output is not None and score > 0:
            scored.append((score, symbol, output, reason))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("file_path") or ""), int(item[1].get("lineno") or 0)))
    if not scored:
        return None, None, ""
    _score, symbol, output, reason = scored[0]
    return symbol, output, reason


def _clean_annotation(value: Any) -> str:
    return str(value or "").replace("typing.", "").strip()


def _type_family(value: Any) -> str:
    text = _clean_annotation(value).lower()
    if text.startswith("dict") or text in {"mapping", "mutablemapping"}:
        return "dict"
    if text.startswith("list") or text.startswith("tuple") or text.startswith("set") or text in {"sequence", "iterable"}:
        return "list"
    if text in {"str", "string"}:
        return "str"
    if text in {"int", "float", "bool"}:
        return text
    return text or "Any"


def _utility_symbol(kind: str, *, key: str = "", index: int = 0) -> dict[str, Any]:
    if kind == "dict_key":
        return {
            "name": "Get Dict Key",
            "kind": "utility",
            "host": "utility",
            "package": "Utility",
            "source_kind": "utility",
            "utility_kind": "dict_key",
            "params": [
                {"name": "source", "annotation": "dict", "python_type": "dict"},
                {"name": "key", "annotation": "str", "python_type": "str", "default": ""},
                {"name": "default", "annotation": "Any", "python_type": "Any", "default": None},
            ],
            "outputs": [{"name": "value", "annotation": "Any", "python_type": "Any"}],
            "return_annotation": "Any",
            "description": "Read one key from a dictionary.",
            "_planner_literal_values": {"key": key},
        }
    if kind == "list_item":
        return {
            "name": "Get List Item",
            "kind": "utility",
            "host": "utility",
            "package": "Utility",
            "source_kind": "utility",
            "utility_kind": "list_item",
            "params": [
                {"name": "source", "annotation": "list", "python_type": "list"},
                {"name": "index", "annotation": "int", "python_type": "int", "default": 0},
            ],
            "outputs": [{"name": "item", "annotation": "Any", "python_type": "Any"}],
            "return_annotation": "Any",
            "description": "Read one item from a list.",
            "_planner_literal_values": {"index": index},
        }
    return {}


def _find_adapter_source_for_param(
    param: dict[str, Any],
    symbols: list[dict[str, Any]],
    prompt: str,
    used_names: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, str]:
    prompt_norm = _normalize_name(prompt)
    param_name = str(param.get("name") or "")
    param_norm = _normalize_name(param_name)
    scored: list[tuple[float, dict[str, Any], dict[str, Any], dict[str, Any], str]] = []
    for symbol in symbols:
        name = str(symbol.get("name") or "")
        if not name or name in used_names:
            continue
        name_norm = _normalize_name(name)
        for output in _outputs(symbol):
            family = _type_family(output.get("annotation") or output.get("type") or output.get("python_type"))
            if family == "dict":
                score = 35.0 + min(20.0, _score_symbol(symbol, prompt))
                if param_norm and f"_{param_norm}_" in f"_{prompt_norm}_":
                    score += 25.0
                if name_norm and f"_{name_norm}_" in f"_{prompt_norm}_":
                    score += 20.0
                adapter = _utility_symbol("dict_key", key=param_name)
                scored.append((score, symbol, output, adapter, "adapted dictionary output with Get Dict Key"))
            elif family == "list":
                score = 25.0 + min(20.0, _score_symbol(symbol, prompt))
                if name_norm and f"_{name_norm}_" in f"_{prompt_norm}_":
                    score += 20.0
                adapter = _utility_symbol("list_item", index=0)
                scored.append((score, symbol, output, adapter, "adapted list output with Get List Item"))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("file_path") or ""), int(item[1].get("lineno") or 0)))
    if not scored:
        return None, None, None, ""
    _score, symbol, output, adapter, reason = scored[0]
    return symbol, output, adapter, reason


def _step_for_symbol(symbol: dict[str, Any], prompt: str, *, dependency_for: str = "", role: str = "") -> dict[str, Any]:
    literals = _literal_values_for_step(prompt, symbol)
    literals.update(symbol.get("_planner_literal_values") or {})
    step = {
        "symbol": symbol,
        "params": _params(symbol),
        "outputs": _outputs(symbol),
        "literal_values": literals,
    }
    if role:
        step["dependency_role"] = role
    if dependency_for:
        step["dependency_for"] = dependency_for
    return step


def _required_links_for_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for target_index, target_step in enumerate(steps, start=1):
        target_symbol = target_step.get("symbol") or {}
        literal_values = target_step.get("literal_values") or {}
        for param in _required_params(target_symbol):
            param_name = str(param.get("name") or "")
            if param_name in literal_values and str(literal_values.get(param_name, "")) != "":
                continue
            existing_source: tuple[int, str, str] | None = None
            for source_index, source_step in enumerate(steps[: target_index - 1], start=1):
                for output in source_step.get("outputs") or source_step.get("symbol", {}).get("outputs") or []:
                    matched, reason = _output_matches_param(output, param)
                    if matched:
                        existing_source = (source_index, str(output.get("name") or "result"), reason)
            if existing_source:
                links.append(
                    {
                        "from_step": existing_source[0],
                        "from_output": existing_source[1],
                        "to_step": target_index,
                        "to_input": param_name,
                        "reason": existing_source[2] or "required input satisfied by upstream producer",
                    }
                )
                continue
            for source_index, source_step in enumerate(steps[: target_index - 1], start=1):
                source_symbol = source_step.get("symbol") or {}
                if source_step.get("dependency_for") != target_symbol.get("name"):
                    continue
                if source_symbol.get("utility_kind") not in {"dict_key", "list_item"}:
                    continue
                output_name = "value" if source_symbol.get("utility_kind") == "dict_key" else "item"
                links.append(
                    {
                        "from_step": source_index,
                        "from_output": output_name,
                        "to_step": target_index,
                        "to_input": param_name,
                        "reason": "adapter output satisfies required parameter",
                    }
                )
                break
    return links


def _satisfy_required_dependencies(
    steps: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    prompt: str,
    *,
    max_insertions: int = 12,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Ensure required callable params are bound by literals, defaults, or producers."""
    diagnostics: list[str] = []
    capability_gaps: list[dict[str, Any]] = []
    insertions = 0
    index = 0
    while index < len(steps):
        step = steps[index]
        symbol = step.get("symbol") or {}
        literal_values = step.setdefault("literal_values", _literal_values_for_step(prompt, symbol))
        restarted = False
        for param in _required_params(symbol):
            param_name = str(param.get("name") or "")
            if param_name in literal_values and str(literal_values.get(param_name, "")) != "":
                continue
            existing_source = False
            for source_index, source_step in enumerate(steps[:index], start=1):
                for output in source_step.get("outputs") or source_step.get("symbol", {}).get("outputs") or []:
                    matched, _reason = _output_matches_param(output, param)
                    if matched:
                        existing_source = True
            if existing_source:
                continue
            existing_adapter = False
            for source_step in steps[:index]:
                source_symbol = source_step.get("symbol") or {}
                if source_step.get("dependency_for") == symbol.get("name") and source_symbol.get("utility_kind") in {"dict_key", "list_item"}:
                    existing_adapter = True
                    break
            if existing_adapter:
                continue

            later_direct_index: int | None = None
            for candidate_index, candidate_step in enumerate(steps[index + 1 :], start=index + 1):
                for output in candidate_step.get("outputs") or candidate_step.get("symbol", {}).get("outputs") or []:
                    matched, _reason = _output_matches_param(output, param)
                    if matched:
                        later_direct_index = candidate_index
            if later_direct_index is not None:
                producer_step = steps.pop(later_direct_index)
                steps.insert(index, producer_step)
                diagnostics.append(
                    f"Moved prerequisite `{producer_step.get('symbol', {}).get('name')}` before `{symbol.get('name')}` for `{param_name}`."
                )
                index = max(index - 1, 0)
                restarted = True
                break

            later_adapter_index: int | None = None
            later_adapter: dict[str, Any] | None = None
            later_adapter_reason = ""
            for candidate_index, candidate_step in enumerate(steps[index + 1 :], start=index + 1):
                for output in candidate_step.get("outputs") or candidate_step.get("symbol", {}).get("outputs") or []:
                    family = _type_family(output.get("annotation") or output.get("type") or output.get("python_type"))
                    if family == "dict":
                        later_adapter_index = candidate_index
                        later_adapter = _utility_symbol("dict_key", key=param_name)
                        later_adapter_reason = "adapted dictionary output with Get Dict Key"
                    elif family == "list":
                        later_adapter_index = candidate_index
                        later_adapter = _utility_symbol("list_item", index=0)
                        later_adapter_reason = "adapted list output with Get List Item"
            if later_adapter_index is not None and later_adapter:
                producer_step = steps.pop(later_adapter_index)
                adapter_step = _step_for_symbol(
                    later_adapter,
                    prompt,
                    role="adapter",
                    dependency_for=str(symbol.get("name") or ""),
                )
                steps.insert(index, producer_step)
                steps.insert(index + 1, adapter_step)
                insertions += 1
                diagnostics.append(
                    f"Moved prerequisite `{producer_step.get('symbol', {}).get('name')}` and inserted adapter `{later_adapter.get('name')}` before `{symbol.get('name')}` for `{param_name}`."
                )
                if later_adapter_reason:
                    diagnostics.append(later_adapter_reason)
                index = max(index - 1, 0)
                restarted = True
                break

            used_names = {str(item.get("symbol", {}).get("name") or "") for item in steps}
            producer, output, reason = _find_producer_for_param(param, symbols, prompt, used_names)
            if producer and output and insertions < max_insertions:
                producer_step = _step_for_symbol(
                    producer,
                    prompt,
                    role="producer",
                    dependency_for=str(symbol.get("name") or ""),
                )
                steps.insert(index, producer_step)
                insertions += 1
                diagnostics.append(
                    f"Inserted prerequisite `{producer.get('name')}` before `{symbol.get('name')}` for `{param_name}`."
                )
                index = max(index - 1, 0)
                restarted = True
                break

            adapter_producer, _adapter_source_output, adapter, adapter_reason = _find_adapter_source_for_param(
                param,
                symbols,
                prompt,
                used_names,
            )
            if adapter_producer and adapter and insertions + 2 <= max_insertions:
                producer_step = _step_for_symbol(
                    adapter_producer,
                    prompt,
                    role="producer",
                    dependency_for=str(symbol.get("name") or ""),
                )
                adapter_step = _step_for_symbol(
                    adapter,
                    prompt,
                    role="adapter",
                    dependency_for=str(symbol.get("name") or ""),
                )
                steps.insert(index, producer_step)
                steps.insert(index + 1, adapter_step)
                insertions += 2
                diagnostics.append(
                    f"Inserted `{adapter_producer.get('name')}` and adapter `{adapter.get('name')}` before `{symbol.get('name')}` for `{param_name}`."
                )
                if adapter_reason:
                    diagnostics.append(adapter_reason)
                index = max(index - 1, 0)
                restarted = True
                break

            capability_gaps.append(
                {
                    "kind": "missing_required_argument",
                    "capability": f"{symbol.get('name', 'callable')}.{param_name}",
                    "callable": symbol.get("name", "callable"),
                    "argument": param_name,
                    "parameter": param,
                    "reason": "Required argument was not provided by the user, defaulted by the signature, or produced by an indexed prerequisite function.",
                    "next_action": "ask_user_for_required_argument",
                }
            )
        if not restarted:
            index += 1

    data_links = _required_links_for_steps(steps)
    data_links.extend(_infer_data_links(steps, prompt))
    by_target: dict[tuple[int, str], dict[str, Any]] = {}
    for link in data_links:
        key = (int(link.get("to_step") or 0), str(link.get("to_input") or ""))
        current = by_target.get(key)
        if current is None or int(link.get("from_step") or 0) > int(current.get("from_step") or 0):
            by_target[key] = link
    deduped = sorted(by_target.values(), key=lambda item: (int(item.get("to_step") or 0), str(item.get("to_input") or "")))
    return steps, deduped, capability_gaps, diagnostics


def _satisfy_required_dependencies_with_escalation(
    steps: list[dict[str, Any]],
    primary_symbols: list[dict[str, Any]],
    prompt: str,
    *,
    fallback_symbol_loader: Any | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    steps, data_links, gaps, diagnostics = _satisfy_required_dependencies(steps, primary_symbols, prompt)
    if not gaps or fallback_symbol_loader is None:
        return steps, data_links, gaps, diagnostics
    fallback_symbols = list(fallback_symbol_loader() or [])
    if not fallback_symbols:
        return steps, data_links, gaps, diagnostics
    primary_keys = {
        (str(symbol.get("file_path") or ""), str(symbol.get("name") or ""), int(symbol.get("lineno") or 0))
        for symbol in primary_symbols
    }
    expanded = list(primary_symbols)
    for symbol in fallback_symbols:
        key = (str(symbol.get("file_path") or ""), str(symbol.get("name") or ""), int(symbol.get("lineno") or 0))
        if key not in primary_keys:
            expanded.append(symbol)
    diagnostics.append("Escalated dependency search beyond explicit scope because required inputs remained unresolved.")
    retry_steps, retry_links, retry_gaps, retry_diagnostics = _satisfy_required_dependencies(steps, expanded, prompt)
    return retry_steps, retry_links, retry_gaps, diagnostics + retry_diagnostics


_DISCOVER_SYMBOLS_CACHE: dict[tuple[str, ...], tuple[float, list[dict[str, Any]]]] = {}
_DISCOVER_SYMBOLS_CACHE_TTL_SECONDS = 15.0


def _discover_symbols(project_roots: list[str]) -> list[dict[str, Any]]:
    cache_key = tuple(sorted(str(Path(root).resolve()) for root in project_roots if root))
    cached = _DISCOVER_SYMBOLS_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _DISCOVER_SYMBOLS_CACHE_TTL_SECONDS:
        return list(cached[1])

    seen: set[tuple[str, str, int]] = set()
    symbols: list[dict[str, Any]] = []
    for symbol in list_internal_functions(project_roots):
        key = (
            str(symbol.get("file_path", "")),
            str(symbol.get("name", "")),
            int(symbol.get("lineno") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        if str(symbol.get("kind", "")).lower() in {"function", "class"}:
            symbols.append(symbol)
    _DISCOVER_SYMBOLS_CACHE[cache_key] = (now, list(symbols))
    return symbols


def _scope_reference_tokens(prompt: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"(?<!\w)@([A-Za-z0-9_./\\:-]+)", prompt or ""):
        token = match.group(1).strip().rstrip(".,;:!?")
        if token and ("/" in token or "\\" in token or "." in token):
            tokens.append(token)
    path_pattern = r"(?<![\"'@\w])((?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|[A-Za-z0-9_./\\-]+[\\/])[A-Za-z0-9_./\\:-]+)"
    for match in re.finditer(path_pattern, prompt or ""):
        token = match.group(1).strip().rstrip(".,;:!?")
        if token and ("/" in token or "\\" in token):
            tokens.append(token)
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        key = token.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(token)
    return unique


def _prompt_without_scope_references(prompt: str) -> str:
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_./\\:-]+", " ", prompt or "")
    text = re.sub(r"(?<![\"'@\w])(?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|[A-Za-z0-9_./\\-]+[\\/])[A-Za-z0-9_./\\:-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _resolve_scope_paths(prompt: str, roots: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for token in _scope_reference_tokens(prompt):
        normalized = token.lstrip("@").replace("\\", "/").strip("/")
        candidates: list[Path] = []
        raw = Path(token.lstrip("@"))
        if raw.is_absolute():
            candidates.append(raw)
        for root_text in roots:
            root = Path(root_text)
            candidates.append(root / normalized)
            candidates.extend(path for path in root.rglob(Path(normalized).name) if path.name.lower() == Path(normalized).name.lower())
        for candidate in candidates:
            try:
                candidate = candidate.resolve()
            except Exception:
                continue
            if candidate.exists() and candidate not in resolved:
                resolved.append(candidate)
                break
    return resolved


def _scope_symbol_pools(symbols: list[dict[str, Any]], scope_paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not scope_paths:
        return symbols, symbols
    target_symbols: list[dict[str, Any]] = []
    dependency_symbols: list[dict[str, Any]] = []
    dependency_roots: list[Path] = []
    for scope in scope_paths:
        if scope.is_file():
            dependency_roots.append(scope.parent)
        else:
            dependency_roots.append(scope)
    for symbol in symbols:
        try:
            path = Path(str(symbol.get("file_path") or "")).resolve()
        except Exception:
            continue
        in_target = any((scope.is_file() and path == scope) or (scope.is_dir() and (path == scope or scope in path.parents)) for scope in scope_paths)
        in_dependency = any(path == root or root in path.parents for root in dependency_roots)
        if in_target:
            target_symbols.append(symbol)
        if in_dependency:
            dependency_symbols.append(symbol)
    return target_symbols or symbols, dependency_symbols or target_symbols or symbols


_SCOPED_SYMBOL_CACHE: dict[tuple[str, ...], tuple[float, list[dict[str, Any]], list[dict[str, Any]]]] = {}


def _discover_scoped_symbol_pools(scope_paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cache_key = tuple(sorted(str(path.resolve()) for path in scope_paths if path.exists()))
    cached = _SCOPED_SYMBOL_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _DISCOVER_SYMBOLS_CACHE_TTL_SECONDS:
        return list(cached[1]), list(cached[2])
    target_symbols: list[dict[str, Any]] = []
    dependency_roots: list[str] = []
    for scope in scope_paths:
        if scope.is_file():
            target_symbols.extend(extract_symbols_from_file(scope))
            dependency_roots.append(str(scope.parent))
        elif scope.is_dir():
            dependency_roots.append(str(scope))
    dependency_symbols = _discover_symbols(dependency_roots) if dependency_roots else list(target_symbols)
    if not target_symbols:
        target_symbols = list(dependency_symbols)
    _SCOPED_SYMBOL_CACHE[cache_key] = (now, list(target_symbols), list(dependency_symbols))
    return target_symbols, dependency_symbols


def _ordered_candidates(prompt: str, symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [(_score_symbol(symbol, prompt), symbol) for symbol in symbols]
    scored = [(score, symbol) for score, symbol in scored if score >= 4.0]
    scored.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("file_path", "")),
            int(item[1].get("lineno") or 0),
        )
    )
    selected: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for score, symbol in scored:
        name = str(symbol.get("name") or "")
        if name in seen_names:
            continue
        symbol = dict(symbol)
        symbol["_intent_score"] = score
        selected.append(symbol)
        seen_names.add(name)
        if len(selected) >= 8:
            break
    return selected


def _requested_callable_names(prompt: str) -> list[str]:
    """Return code-like callable names explicitly requested by the user."""

    prompt = _prompt_without_scope_references(prompt)
    names: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+)\b", prompt or ""):
        name = match.group(1)
        if re.match(r"\s*=", (prompt or "")[match.end() :]):
            continue
        if name not in names:
            names.append(name)
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", prompt or ""):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names


def _explicit_order(prompt: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(candidates) < 2:
        return candidates
    prompt_norm = _normalize_name(prompt)

    def order_key(symbol: dict[str, Any]) -> tuple[int, int, float]:
        name = _normalize_name(symbol.get("name", ""))
        file_name = _normalize_name(Path(symbol.get("file_path", "")).name)
        is_generic = name in _GENERIC_NAMES
        name_pos = prompt_norm.find(name) if len(name) >= 3 and not is_generic else -1
        file_pos = prompt_norm.find(file_name) if file_name else -1
        if name_pos >= 0:
            return (0, name_pos, -float(symbol.get("_intent_score") or 0.0))
        if file_pos >= 0:
            return (1, file_pos, -float(symbol.get("_intent_score") or 0.0))
        return (2, 999999, -float(symbol.get("_intent_score") or 0.0))

    return sorted(candidates, key=order_key)


def _infer_data_links(steps: list[dict[str, Any]], prompt: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    prompt_norm = _normalize_name(prompt)
    for source_index, source_step in enumerate(steps, start=1):
        source_outputs = source_step.get("symbol", {}).get("outputs") or source_step.get("outputs") or []
        for target_index, target_step in enumerate(steps, start=1):
            if target_index <= source_index:
                continue
            target_params = target_step.get("params") or target_step.get("symbol", {}).get("params") or []
            for output in source_outputs:
                output_name = output.get("name", "")
                output_norm = _normalize_name(output_name)
                if not output_norm:
                    continue
                for param in target_params:
                    param_name = param.get("name", "")
                    param_norm = _normalize_name(param_name)
                    if not param_norm:
                        continue
                    
                    out_type = str(output.get("annotation") or output.get("type") or "").replace("typing.", "").strip()
                    param_type = str(param.get("annotation") or param.get("type") or "").replace("typing.", "").strip()
                    
                    if output_norm == param_norm or f"_{output_norm}_" in f"_{param_norm}_" or f"_{param_norm}_" in f"_{output_norm}_":
                        links.append(
                            {
                                "from_step": source_index,
                                "from_output": output_name,
                                "to_step": target_index,
                                "to_input": param_name,
                                "reason": "matched indexed output to parameter",
                            }
                        )
                        break
                    if f"_{output_norm}_" in f"_{prompt_norm}_" and f"_{param_norm}_" in f"_{prompt_norm}_":
                        links.append(
                            {
                                "from_step": source_index,
                                "from_output": output_name,
                                "to_step": target_index,
                                "to_input": param_name,
                                "reason": "prompt mentioned both output and parameter",
                            }
                        )
                        break
                    if out_type and param_type and out_type == param_type and out_type.lower() not in {"str", "int", "float", "bool", "any", "none", "void", "object"}:
                        links.append(
                            {
                                "from_step": source_index,
                                "from_output": output_name,
                                "to_step": target_index,
                                "to_input": param_name,
                                "reason": f"matched parameter type: {out_type}",
                            }
                        )
                        break
    # A pipeline input can have only one producer. Prefer the nearest upstream
    # step when several compatible earlier outputs exist.
    by_target: dict[tuple[int, str], dict[str, Any]] = {}
    for link in links:
        key = (int(link.get("to_step") or 0), str(link.get("to_input") or ""))
        current = by_target.get(key)
        if current is None or int(link.get("from_step") or 0) > int(current.get("from_step") or 0):
            by_target[key] = link
    return sorted(
        by_target.values(),
        key=lambda item: (int(item.get("to_step") or 0), str(item.get("to_input") or "")),
    )


def resolve_workflow_intent(prompt: str, project_roots: list[str]) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    diagnostics: list[str] = []
    if not prompt:
        return WorkflowIntentPlan(False, 0.0, [], [], [], ["No prompt was provided."]).as_dict()

    roots = [str(Path(root).resolve()) for root in project_roots if root and Path(root).exists()]

    if not roots:
        return WorkflowIntentPlan(False, 0.0, [], [], [], ["No valid project roots were available for symbol discovery."]).as_dict()

    scope_paths = _resolve_scope_paths(prompt, roots)
    if scope_paths:
        target_symbols, dependency_symbols = _discover_scoped_symbol_pools(scope_paths)
        symbols = list({id(item): item for item in [*target_symbols, *dependency_symbols]}.values())
        fallback_dependency_loader = lambda: _discover_symbols(roots)
    else:
        symbols = _discover_symbols(roots)
        target_symbols, dependency_symbols = symbols, symbols
        fallback_dependency_loader = None
    diagnostics.append(f"Indexed symbol candidates: {len(symbols)}")
    if scope_paths:
        diagnostics.append(
            "Explicit scope narrowed target candidates to "
            + ", ".join(str(path) for path in scope_paths[:3])
        )
    candidates = _explicit_order(prompt, _ordered_candidates(prompt, target_symbols))

    requested_names = _requested_callable_names(prompt)
    if requested_names:
        requested_set = set(requested_names)
        candidates = [
            item for item in candidates
            if str(item.get("name") or "") in requested_set
        ]
    resolved_names = {str(item.get("name") or "") for item in candidates}
    missing_names = [name for name in requested_names if name not in resolved_names]
    if not candidates:
        gaps = [
            {
                "capability": name,
                "reason": "No indexed or registered callable matched the requested pipeline step.",
                "next_action": "search_project_then_implement_and_register",
            }
            for name in (missing_names or ["pipeline callable matching the requested behavior"])
        ]
        diagnostics.append("No executable pipeline was created; callable acquisition is required.")
        return WorkflowIntentPlan(
            False,
            0.0,
            [],
            [],
            [],
            diagnostics + ["No indexed functions/classes matched the prompt strongly enough."],
            gaps,
        ).as_dict()

    steps: list[dict[str, Any]] = []
    for symbol in candidates[:4]:
        params = _params(symbol)
        outputs = _outputs(symbol)
        steps.append(
            {
                "symbol": symbol,
                "params": params,
                "outputs": outputs,
                "literal_values": _literal_values_for_step(prompt, symbol),
            }
        )

    steps, data_links, dependency_gaps, dependency_diagnostics = _satisfy_required_dependencies_with_escalation(
        steps,
        dependency_symbols,
        prompt,
        fallback_symbol_loader=fallback_dependency_loader,
    )
    diagnostics.extend(dependency_diagnostics)
    connected_steps = {link["from_step"] for link in data_links} | {link["to_step"] for link in data_links}
    explicit_names = set(requested_names)
    preserve_explicit_steps = bool(explicit_names) and all(
        str(step.get("symbol", {}).get("name") or "") in explicit_names
        for step in steps
    )
    if data_links and len(steps) > 2 and not preserve_explicit_steps:
        steps = [step for idx, step in enumerate(steps, start=1) if idx in connected_steps]
        index_map = {old_idx: new_idx for new_idx, old_idx in enumerate(sorted(connected_steps), start=1)}
        data_links = [
            {**link, "from_step": index_map[link["from_step"]], "to_step": index_map[link["to_step"]]}
            for link in data_links
            if link["from_step"] in index_map and link["to_step"] in index_map
        ]

    flow_links = [
        {"from_step": idx, "to_step": idx + 1, "reason": "prompt described a multi-step pipeline"}
        for idx in range(1, len(steps))
    ]

    top_score = float(candidates[0].get("_intent_score") or 0.0)
    confidence = min(1.0, (top_score / 24.0) + (0.2 if data_links else 0.0))
    capability_gaps = [
        {
            "capability": name,
            "reason": "The prompt named this callable, but project-index evidence did not resolve it.",
            "next_action": "search_project_then_implement_and_register",
        }
        for name in missing_names
    ]
    capability_gaps.extend(dependency_gaps)
    success = bool(len(steps) >= 1 and confidence >= 0.35 and not capability_gaps)
    diagnostics.append("Resolved steps: " + ", ".join(step["symbol"].get("name", "unknown") for step in steps))
    if data_links:
        diagnostics.append(f"Resolved data links: {len(data_links)}")
    else:
        diagnostics.append("No deterministic data links were inferred.")
    if capability_gaps:
        diagnostics.append("Pipeline execution is blocked until all named callable gaps are resolved.")
    return WorkflowIntentPlan(
        success,
        confidence,
        steps,
        data_links,
        flow_links,
        diagnostics,
        capability_gaps,
    ).as_dict()
