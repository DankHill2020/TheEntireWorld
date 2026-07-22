"""Evidence-grounded discovery for lowering semantic actions into Blueprint nodes."""

from __future__ import annotations

import json
import fnmatch
from pathlib import Path
import re
from typing import Any, Iterable


_QUERY_STOP_WORDS = {
    "apply", "bounded", "current", "enable", "from", "observed", "owning",
    "read", "schedule", "toward", "variables", "window", "write",
}


def verified_atomic_vocabulary(operation: str) -> dict[str, Any]:
    """Load reusable live-verified action vocabulary without embedding system recipes."""

    path = Path(__file__).resolve().parents[2] / "knowledge" / "reference" / "unreal_blueprint_atomic_actions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"search_terms": [], "verified_actions": [], "evidence": {}}
    matched = [
        dict(row)
        for row in payload.get("records") or []
        if any(fnmatch.fnmatchcase(str(operation), str(pattern)) for pattern in row.get("operation_patterns") or [])
    ]
    return {
        "search_terms": list(dict.fromkeys(value for row in matched for value in row.get("search_terms") or [])),
        "verified_actions": list(dict.fromkeys(value for row in matched for value in row.get("verified_actions") or [])),
        "evidence": dict(payload.get("engine_evidence") or {}),
    }


def semantic_operation_search_terms(
    operation: str,
    *,
    context_text: str = "",
    explicit_terms: Iterable[str] | None = None,
) -> list[str]:
    """Produce broad palette queries without selecting or inventing a node."""

    if explicit_terms:
        return list(dict.fromkeys(str(value).strip() for value in explicit_terms if str(value).strip()))
    action = str(operation or "").partition(".")[2].replace("_", " ")
    words = [
        value.lower()
        for value in re.findall(r"[A-Za-z][A-Za-z0-9]+", action + " " + str(context_text or ""))
        if len(value) >= 4 and value.lower() not in _QUERY_STOP_WORDS
    ]
    operation_words = [
        value.lower()
        for value in re.findall(r"[A-Za-z][A-Za-z0-9]+", action)
        if len(value) >= 4 and value.lower() not in _QUERY_STOP_WORDS
    ]
    queries = []
    if len(operation_words) >= 2:
        queries.append(" ".join(operation_words[:2]))
    queries.extend(operation_words)
    queries.extend(value for value in words if value not in operation_words)
    return list(dict.fromkeys(queries))[:6]


def suggest_action_search_terms(
    semantic_operations: Iterable[dict[str, Any] | str],
    *,
    model: str = "qwen2.5-coder:7b",
) -> dict[str, list[str]]:
    """Ask a reasoning model for UE palette vocabulary; live reflection remains authoritative."""

    from tech_connector.knowledge.search import query_ollama_text

    items = [dict(value) if isinstance(value, dict) else {"operation": str(value)} for value in semantic_operations]
    operation_names = [str(item.get("operation") or "") for item in items if item.get("operation")]
    schema = {
        "type": "object",
        "properties": {
            "queries": {
                "type": "object",
                "properties": {
                    name: {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {"type": "string"},
                    }
                    for name in operation_names
                },
                "required": operation_names,
                "additionalProperties": False,
            },
        },
        "required": ["queries"],
    }
    raw = query_ollama_text(
        model,
        """You translate atomic gameplay operations into literal Unreal Engine Blueprint palette search phrases.
Return JSON only as {"queries": {exact_operation_key: [phrases]}}.
Preserve every operation key exactly. Give 1-4 short phrases per operation using likely UE node menu vocabulary.
Use menu text without category prefixes.
Do not claim a node exists, do not provide code, and do not design a complete mechanic.
The live context-filtered Blueprint action database will verify every phrase.""",
        json.dumps({"operations": items}, sort_keys=True),
        num_ctx=4096,
        num_predict=512,
        timeout=120,
        prefer_coder=True,
        coder_preference="fast",
        think=False,
        response_format=schema,
        temperature=0.0,
    )
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    query_rows = dict(payload.get("queries") or {})
    return {
        name: list(
            dict.fromkeys(str(value).strip() for value in query_rows.get(name) or [] if str(value).strip())
        )[:4]
        for name in operation_names
        if query_rows.get(name)
    }


def _expanded_search_terms(reasoned: Iterable[str], lexical: Iterable[str]) -> list[str]:
    terms = []
    for raw in list(reasoned or []) + list(lexical or []):
        value = str(raw or "").split("|", 1)[-1].strip()
        if not value:
            continue
        terms.append(value)
        words = [word for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", value) if len(word) >= 4]
        if len(words) >= 2:
            terms.append(" ".join(words[:2]))
        terms.extend(words)
    return list(dict.fromkeys(terms))[:10]


def _candidate_relevance(candidate: dict[str, Any], semantic_text: str) -> int:
    desired = set(re.findall(r"[a-z][a-z0-9]+", semantic_text.lower())) - _QUERY_STOP_WORDS
    menu = set(re.findall(r"[a-z][a-z0-9]+", str(candidate.get("menu_name") or "").lower()))
    category = set(re.findall(r"[a-z][a-z0-9]+", str(candidate.get("category") or "").lower()))
    tooltip = set(re.findall(r"[a-z][a-z0-9]+", str(candidate.get("tooltip") or "").lower()))
    score = len(desired & menu) * 25 + len(desired & category) * 8 + len(desired & tooltip) * 2
    category_text = " ".join(category)
    if ("perf" in category or "insightstrace" in category_text) and not desired.intersection({"perf", "insights"}):
        score -= 80
    if "audio" in category and "audio" not in desired:
        score -= 60
    if "addcomponent" in category_text and "component" not in desired:
        score -= 40
    return score


def _call_unreal(function: str, kwargs: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
    from tech_connector.bridges.unreal.unreal_bridge import UnrealBridge

    ok, raw = UnrealBridge().call(
        function,
        args=[],
        kwargs=kwargs,
        timeout=timeout,
        retries=0,
        retry_safe=True,
        operation="blueprint.action_discovery",
    )
    try:
        result = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except Exception:
        result = {"ok": False, "error": str(raw)}
    if not ok:
        result["ok"] = False
        result.setdefault("error", str(raw))
    return result


def discover_action_candidates(
    blueprint_path: str,
    graph_name: str,
    semantic_operations: Iterable[dict[str, Any] | str],
    max_results_per_query: int = 15,
    use_reasoning: bool = True,
    reasoning_model: str = "qwen2.5-coder:7b",
) -> dict[str, Any]:
    """Search live context-filtered actions; do not mutate the project or select a winner."""

    semantic_operations = list(semantic_operations or [])
    reasoned_terms = (
        suggest_action_search_terms(semantic_operations, model=reasoning_model)
        if use_reasoning
        else {}
    )
    rows = []
    all_ok = True
    query_cache: dict[str, dict[str, Any]] = {}
    for raw in semantic_operations:
        item = dict(raw) if isinstance(raw, dict) else {"operation": str(raw)}
        operation = str(item.get("operation") or "")
        known = verified_atomic_vocabulary(operation)
        lexical_terms = semantic_operation_search_terms(
            operation,
            context_text=str(item.get("context") or ""),
            explicit_terms=item.get("search_terms"),
        )
        known_terms = list(known.get("search_terms") or [])
        model_terms = list(reasoned_terms.get(operation, []))
        terms = (
            list(dict.fromkeys(known_terms))
            if known_terms and not model_terms
            else _expanded_search_terms(known_terms + model_terms, [] if known_terms else lexical_terms)
        )
        candidates: dict[str, dict[str, Any]] = {}
        searches = []
        for query in terms:
            result = query_cache.get(query)
            if result is None:
                result = _call_unreal(
                    "unreal_tools.blueprint.search_node_actions",
                    {
                        "blueprint_path": blueprint_path,
                        "graph_name": graph_name,
                        "query": query,
                        "max_results": int(max_results_per_query),
                    },
                )
                query_cache[query] = result
            searches.append(
                {
                    "query": query,
                    "ok": bool(result.get("ok")),
                    "returned": int(result.get("returned_match_count") or 0),
                    "error": result.get("error") or "",
                }
            )
            all_ok = all_ok and bool(result.get("ok"))
            for candidate in result.get("matches") or []:
                candidate = dict(candidate)
                key = str(candidate.get("palette_action") or "")
                if not key:
                    continue
                candidate.setdefault("matched_queries", []).append(query)
                existing = candidates.get(key)
                if existing:
                    existing["matched_queries"] = list(
                        dict.fromkeys(existing.get("matched_queries", []) + [query])
                    )
                    existing["score"] = max(int(existing.get("score") or 0), int(candidate.get("score") or 0))
                else:
                    candidates[key] = candidate
        verified_actions = set(known.get("verified_actions") or [])
        for key, candidate in candidates.items():
            candidate["verified_atomic_vocabulary"] = key in verified_actions
        ranked = sorted(
            candidates.values(),
            key=lambda value: (
                -int(bool(value.get("verified_atomic_vocabulary"))),
                -_candidate_relevance(
                    value,
                    " ".join(
                        [operation, str(item.get("context") or "")] + list(reasoned_terms.get(operation) or [])
                    ),
                ),
                -len(value.get("matched_queries") or []),
                -int(value.get("score") or 0),
                str(value.get("palette_action") or ""),
            ),
        )
        rows.append(
            {
                "operation": operation,
                "search_terms": terms,
                "searches": searches,
                "candidates": ranked[:25],
                "verified_vocabulary_evidence": known.get("evidence") or {},
                "status": "candidates_found" if ranked else "knowledge_gap",
                "selection_required": True,
            }
        )
    return {
        "ok": all_ok,
        "blueprint_path": blueprint_path,
        "graph_name": graph_name,
        "operations": rows,
        "reasoned_search_terms": reasoned_terms,
        "mutation_allowed": False,
        "next_gate": "review candidate actions, then approve disposable pin probes",
    }


def probe_selected_actions(
    blueprint_path: str,
    graph_name: str,
    selections: Iterable[dict[str, Any]],
    *,
    approved: bool = False,
    temp_folder: str = "/Game/AIStudio/Temp/NodeProbes",
) -> dict[str, Any]:
    """Probe user-approved exact actions on a retained, resettable Blueprint copy."""

    selections = [dict(value) for value in selections or []]
    if not approved:
        return {
            "ok": False,
            "status": "approval_required",
            "mutation_allowed": False,
            "selections": selections,
            "reason": "Pin probing uses a retained disposable Blueprint asset and requires plan approval.",
        }
    results = []
    for selection in selections:
        palette_action = str(selection.get("palette_action") or "")
        if not palette_action:
            results.append({"ok": False, "error": "palette_action is required"})
            continue
        results.append(
            _call_unreal(
                "unreal_tools.blueprint.probe_node_action",
                {
                    "blueprint_path": blueprint_path,
                    "graph_name": graph_name,
                    "palette_action": palette_action,
                    "temp_folder": temp_folder,
                },
                timeout=60.0,
            )
        )
    return {
        "ok": bool(results) and all(bool(value.get("ok")) for value in results),
        "status": "probed" if results and all(bool(value.get("ok")) for value in results) else "failed",
        "blueprint_path": blueprint_path,
        "graph_name": graph_name,
        "results": results,
    }
