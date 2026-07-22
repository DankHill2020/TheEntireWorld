"""Deterministic prompt-to-action-graph planner.

This is the rule-router/deterministic-planner layer. It emits a structured
ActionGraph for operations the app can understand without asking an LLM to
invent functions, files, or execution steps.
"""

from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

from tech_connector.services.action_graph_service import ActionGraph, validate_action_graph
from tech_connector.services.workflow_service import resolve_workflow_intent


def _clean_query(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _file_hint(text: str) -> str:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+)\b", text or "")
    return match.group(1) if match else ""


def _function_mentions(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text or ""):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def _looks_like_pipeline_request(text: str) -> bool:
    lower = (text or "").lower()
    # Check for multiple DCC hosts
    hosts = []
    for host in ("maya", "unreal", "blender", "substance_painter", "unity", "motionbuilder"):
        if host in lower or host.replace("_", " ") in lower:
            hosts.append(host)
    if len(hosts) >= 2:
        return True
    return bool(
        re.search(
            r"\b("
            r"pipeline|workflow|node|graph|connected|connection|flow|bind|mapping|maping|bridge|transfer|"
            r"multi[- ]?step|step\s+\d+|chain|chained|sequence|sequential|compose|composer|wire|"
            r"node\s+view|builder|data\s+link|data\s+links|flow\s+link|flow\s+links"
            r")\b",
            lower,
        )
    )


_WORKFLOW_GRAPH_CACHE: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, Any] | None]] = {}
_WORKFLOW_GRAPH_CACHE_TTL_SECONDS = 15.0


def should_route_to_action_graph(prompt: str, project_roots: list[str] | None = None) -> bool:
    """Return True when deterministic action planning should claim a chat prompt."""
    text = _clean_query(prompt)
    if not text:
        return False
    lower = text.lower()
    if _looks_like_pipeline_request(text):
        # Keep this predicate cheap: it runs during UI-thread route classification.
        # Full symbol resolution happens later inside RequestPreparationWorker.
        return True
    file_hint = _file_hint(text)
    if re.search(r"\b(open|show|go to|jump to)\b", lower) and file_hint:
        return True
    if re.search(r"\b(find|search|locate|where is|where are)\b", lower):
        return bool(_function_mentions(text))
    if re.search(r"\b(rebuild|refresh|index)\b", lower) and re.search(r"\b(index|project|repo|repository|codebase|knowledge)\b", lower):
        return True
    if "github" in lower and re.search(r"\b(search|find|ingest|import|install)\b", lower):
        return True
    if re.search(r"\b(refresh)\b", lower) and any(host in lower for host in ("unreal", "maya", "blender")):
        return True
    return False


def _literal_actions(graph: ActionGraph, step: dict[str, Any], node_name: str, node_action_id: str) -> None:
    for param, value in (step.get("literal_values") or {}).items():
        graph.add(
            "bind_literal",
            {"node": node_name, "parameter": param, "value": value},
            depends_on=[node_action_id],
        )


def _deps(*values: str | None) -> list[str]:
    return [value for value in values if value]


def _workflow_plan_to_action_graph(prompt: str, roots: list[str]) -> dict[str, Any] | None:
    cache_key = (_clean_query(prompt).lower(), tuple(sorted(str(Path(root).resolve()) for root in roots if root)))
    cached = _WORKFLOW_GRAPH_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _WORKFLOW_GRAPH_CACHE_TTL_SECONDS:
        return cached[1]

    plan = resolve_workflow_intent(prompt, roots)
    if not plan.get("success"):
        gaps = [dict(item) for item in plan.get("capability_gaps") or []]
        if not gaps:
            _WORKFLOW_GRAPH_CACHE[cache_key] = (now, None)
            return None
        graph = ActionGraph(
            goal=prompt,
            intent="pipeline_capability_acquisition",
            confidence=float(plan.get("confidence") or 0.0),
            diagnostics=list(plan.get("diagnostics") or []),
        )
        for gap in gaps:
            graph.add(
                "search_project",
                {
                    "query": gap.get("capability") or prompt,
                    "reason": gap.get("reason") or "Resolve a missing pipeline callable.",
                },
                requires_approval=False,
            )
        data = graph.to_dict()
        data["workflow_plan"] = plan
        data["capability_gaps"] = gaps
        data["validation"] = validate_action_graph(data)
        _WORKFLOW_GRAPH_CACHE[cache_key] = (now, data)
        return data

    graph = ActionGraph(
        goal=prompt,
        intent="pipeline_graph",
        confidence=float(plan.get("confidence") or 0.0),
        diagnostics=plan.get("diagnostics") or [],
    )

    resolve_ids: dict[int, str] = {}
    node_ids: dict[int, str] = {}
    node_names: dict[int, str] = {}
    for index, step in enumerate(plan.get("steps") or [], start=1):
        symbol = step.get("symbol") or {}
        name = symbol.get("name") or f"step_{index}"
        node_names[index] = name
        resolve = graph.add(
            "resolve_function",
            {
                "query": name,
                "file_hint": Path(symbol.get("file_path", "")).name,
                "symbol": symbol,
            },
            requires_approval=False,
        )
        resolve_ids[index] = resolve.id
        node = graph.add(
            "create_node",
            {
                "node": name,
                "symbol": symbol,
                "params": step.get("params") or [],
                "outputs": step.get("outputs") or [],
            },
            depends_on=[resolve.id],
        )
        node_ids[index] = node.id
        _literal_actions(graph, step, name, node.id)

    for link in plan.get("data_links") or []:
        graph.add(
            "connect_data",
            {
                "from": {
                    "node": node_names.get(int(link.get("from_step") or 0), ""),
                    "port": link.get("from_output") or "result",
                },
                "to": {
                    "node": node_names.get(int(link.get("to_step") or 0), ""),
                    "port": link.get("to_input") or "",
                },
                "reason": link.get("reason") or "",
            },
            depends_on=_deps(node_ids.get(int(link.get("from_step") or 0)), node_ids.get(int(link.get("to_step") or 0))),
        )

    for link in plan.get("flow_links") or []:
        graph.add(
            "connect_flow",
            {
                "from": node_names.get(int(link.get("from_step") or 0), ""),
                "to": node_names.get(int(link.get("to_step") or 0), ""),
                "reason": link.get("reason") or "",
            },
            depends_on=_deps(node_ids.get(int(link.get("from_step") or 0)), node_ids.get(int(link.get("to_step") or 0))),
        )

    graph.add("validate_graph", {"target": "pipeline_node_view"})
    graph.add("generate_python", {"target": "pipeline_graph"})
    data = graph.to_dict()
    data["workflow_plan"] = plan
    data["validation"] = validate_action_graph(data)
    _WORKFLOW_GRAPH_CACHE[cache_key] = (now, data)
    return data


def plan_prompt_to_action_graph(prompt: str, project_roots: list[str] | None = None) -> dict[str, Any]:
    text = _clean_query(prompt)
    roots = project_roots or []
    lower = text.lower()

    if _looks_like_pipeline_request(text):
        graph = _workflow_plan_to_action_graph(text, roots)
        if graph:
            return graph

    action_graph = ActionGraph(goal=text, intent="general", confidence=0.65)

    file_hint = _file_hint(text)
    if re.search(r"\b(open|show|go to|jump to)\b", lower) and file_hint:
        resolve = action_graph.add("resolve_file", {"query": file_hint, "path": file_hint}, requires_approval=False)
        action_graph.add("open_file", {"query": file_hint, "path": file_hint}, depends_on=[resolve.id], requires_approval=False)
    elif re.search(r"\b(find|search|locate|where is|where are)\b", lower):
        function_names = _function_mentions(text)
        if function_names or re.search(r"\b(function|method|symbol)\b", lower):
            query = function_names[0] if function_names else re.sub(r"\b(find|search|locate|where is|where are|function|method|symbol)\b", "", text, flags=re.IGNORECASE).strip()
            action_graph.intent = "symbol_search"
            action_graph.add("resolve_function", {"query": query, "file_hint": file_hint}, requires_approval=False)
            action_graph.add("open_symbol", {"query": query, "file_hint": file_hint}, requires_approval=False)
        else:
            action_graph.intent = "project_search"
            action_graph.add("search_project", {"query": text}, requires_approval=False)
    elif re.search(r"\b(rebuild|refresh)\b", lower) and re.search(r"\b(index|project index|knowledge)\b", lower):
        action_graph.intent = "rebuild_index"
        action_graph.add("rebuild_index", {"scope": "project"})
    elif re.search(r"\b(index)\b", lower) and re.search(r"\b(project|repo|repository|codebase)\b", lower):
        action_graph.intent = "index_project"
        action_graph.add("index_project", {"scope": "project"})
    elif "github" in lower and re.search(r"\b(search|find)\b", lower):
        action_graph.intent = "github_search"
        action_graph.add("github_search", {"query": text}, requires_approval=False)
    elif "github" in lower and re.search(r"\b(ingest|import|install)\b", lower):
        action_graph.intent = "github_ingest"
        action_graph.add("github_search", {"query": text}, requires_approval=False)
        action_graph.add("github_ingest", {"query": text})
        action_graph.add("index_repository", {"source": "github_ingest"})
    elif re.search(r"\b(refresh)\b", lower) and "unreal" in lower:
        action_graph.intent = "refresh_unreal"
        action_graph.add("refresh_unreal", {})
    elif re.search(r"\b(refresh)\b", lower) and "maya" in lower:
        action_graph.intent = "refresh_maya"
        action_graph.add("refresh_maya", {})
    elif re.search(r"\b(refresh)\b", lower) and "blender" in lower:
        action_graph.intent = "refresh_blender"
        action_graph.add("refresh_blender", {})
    else:
        action_graph.intent = "needs_llm_planner"
        action_graph.planner = "deterministic_router"
        action_graph.confidence = 0.2
        action_graph.add("search_project", {"query": text}, requires_approval=False)
        action_graph.diagnostics.append("Deterministic router found no complete plan; LLM planner may be needed.")

    data = action_graph.to_dict()
    data["validation"] = validate_action_graph(data)
    return data


def workflow_plan_from_action_graph(graph: dict[str, Any]) -> dict[str, Any] | None:
    if graph.get("workflow_plan"):
        return graph["workflow_plan"]
    return None
