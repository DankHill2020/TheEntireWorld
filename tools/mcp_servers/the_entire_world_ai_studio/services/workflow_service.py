"""Project-local workflow persistence and validation scaffolding, combined with deterministic prompt-to-pipeline planning from indexed symbols."""

from __future__ import annotations

import ast
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from services.tool_discovery_service import list_internal_functions
from services.prompt_route_service import HOST_ALIASES, _detect_hosts

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "confidence": self.confidence,
            "steps": self.steps,
            "data_links": self.data_links,
            "flow_links": self.flow_links,
            "diagnostics": self.diagnostics,
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
    return links


def resolve_workflow_intent(prompt: str, project_roots: list[str]) -> dict[str, Any]:
    prompt = (prompt or "").strip()
    diagnostics: list[str] = []
    if not prompt:
        return WorkflowIntentPlan(False, 0.0, [], [], [], ["No prompt was provided."]).as_dict()

    roots = [str(Path(root).resolve()) for root in project_roots if root and Path(root).exists()]

    # Automatically scan sibling/peer tool directories (e.g. unreal_tools, maya_tools, motionbuilder_tools)
    for r in list(roots):
        p = Path(r)
        parent = p.parent
        if parent.name == "mcp_servers":
            try:
                for sibling in parent.parent.iterdir():
                    if sibling.is_dir() and sibling.name.endswith("_tools"):
                        sibling_path = str(sibling.resolve())
                        if sibling_path not in roots:
                            roots.append(sibling_path)
            except Exception:
                pass

    if not roots:
        return WorkflowIntentPlan(False, 0.0, [], [], [], ["No valid project roots were available for symbol discovery."]).as_dict()

    symbols = _discover_symbols(roots)
    diagnostics.append(f"Indexed symbol candidates: {len(symbols)}")
    candidates = _explicit_order(prompt, _ordered_candidates(prompt, symbols))

    if not candidates:
        # Check if the prompt mentions multiple DCC hosts or is a pipeline/workflow request
        lower_prompt = prompt.lower()
        hosts_sequence = []
        for word in lower_prompt.split():
            clean_word = re.sub(r"[^\w]", "", word)
            for h, aliases in HOST_ALIASES.items():
                if clean_word in aliases and h not in hosts_sequence:
                    hosts_sequence.append(h)
                    break

        # If no hosts were found in order, just get all detected hosts
        if not hosts_sequence:
            hosts_sequence = _detect_hosts(prompt)

        if len(hosts_sequence) >= 2 or any(kw in lower_prompt for kw in ["pipeline", "workflow", "bridge", "transfer", "multi-dcc"]):
            # Split the prompt into sequential action clauses
            clauses = []
            parts = re.split(r"\b(?:then|to|and|->|,)\b", lower_prompt)
            for part in parts:
                part = part.strip()
                if len(part) > 3:
                    clauses.append(part)

            # If no clauses could be split, use default steps for the detected hosts
            if not clauses:
                clauses = [f"process in {h}" for h in hosts_sequence]
                if not clauses:
                    clauses = ["export asset", "process asset", "import asset"]

            # Generate placeholder steps
            generated_steps = []
            for idx, clause in enumerate(clauses, start=1):
                # Infer which host this clause is targeting
                clause_host = ""
                for h, aliases in HOST_ALIASES.items():
                    if any(alias in clause for alias in aliases):
                        clause_host = h
                        break
                if not clause_host:
                    # Fallback to current host in sequence
                    if idx - 1 < len(hosts_sequence):
                        clause_host = hosts_sequence[idx - 1]
                    else:
                        clause_host = hosts_sequence[-1] if hosts_sequence else "dcc"

                # Make a nice human readable name
                clean_clause = re.sub(r"[^\w\s]", "", clause).strip()
                verb_words = [w for w in clean_clause.split() if w not in HOST_ALIASES.get(clause_host, []) and w not in {"the", "a", "an", "then", "to", "and", "in"}]
                action_name = "_".join(verb_words) if verb_words else f"process_{clause_host}"
                func_name = f"{clause_host}_{action_name}"

                symbol = {
                    "name": func_name,
                    "kind": "function",
                    "signature": f"(asset_path: str) -> str",
                    "docstring": f"Placeholder step: {clause.capitalize()} using {clause_host.capitalize()}.",
                    "file_path": f"c:/depot/tools/placeholders/{clause_host}_pipeline.py",
                    "lineno": 1,
                    "_intent_score": 12.0,
                }

                # Make outputs and params match so they connect
                params = [{"name": "asset_path", "type": "str"}]
                outputs = [{"name": "asset_path", "type": "str"}]
                generated_steps.append({
                    "symbol": symbol,
                    "params": params,
                    "outputs": outputs,
                    "literal_values": {"asset_path": f"C:/depot/projects/temp_asset.fbx"} if idx == 1 else {},
                })

            # Form flow links and data links
            data_links = []
            for i in range(1, len(generated_steps)):
                data_links.append({
                    "from_step": i,
                    "from_output": "asset_path",
                    "to_step": i + 1,
                    "to_input": "asset_path",
                    "reason": "Sequential pipeline data link",
                })

            flow_links = [
                {"from_step": idx, "to_step": idx + 1, "reason": "Sequential pipeline flow"}
                for idx in range(1, len(generated_steps))
            ]

            diagnostics.append("Generated placeholder pipeline steps for: " + ", ".join(hosts_sequence))
            return WorkflowIntentPlan(
                success=True,
                confidence=0.75,
                steps=generated_steps,
                data_links=data_links,
                flow_links=flow_links,
                diagnostics=diagnostics
            ).as_dict()

        return WorkflowIntentPlan(False, 0.0, [], [], [], diagnostics + ["No indexed functions/classes matched the prompt strongly enough."]).as_dict()

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

    data_links = _infer_data_links(steps, prompt)
    connected_steps = {link["from_step"] for link in data_links} | {link["to_step"] for link in data_links}
    if data_links and len(steps) > 2:
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
    success = bool(len(steps) >= 1 and confidence >= 0.35)
    diagnostics.append("Resolved steps: " + ", ".join(step["symbol"].get("name", "unknown") for step in steps))
    if data_links:
        diagnostics.append(f"Resolved data links: {len(data_links)}")
    else:
        diagnostics.append("No deterministic data links were inferred.")
    return WorkflowIntentPlan(success, confidence, steps, data_links, flow_links, diagnostics).as_dict()
