from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.request_context import RequestContext
from engine.request_engine import RequestEngine
from knowledge.search import get_installed_ollama_models, resolve_installed_ollama_model
from router.ai_router import AIRouter, ModelTiers
from services.ollama_resource_service import build_ollama_options, choose_ollama_generation_budget, ollama_keep_alive
from services.prompt_route_service import classify_prompt_route
from services.settings_service import load_settings


DEFAULT_PROMPTS = [
    "Testing connection",
    "am i connected ?",
    "What functions create a rig in maya?",
    "what files have functions to create rig",
    "what functions are in this file?",
    "What Maya functions create a control?",
    "Inspect the project for sprint and stamina systems; do not edit anything.",
    "Where should I add a new Unreal graph rollback validator?",
    "Explain the safest implementation plan for adding missing docstrings to this file.",
]

USABILITY_SCORE = {
    "poor": 0,
    "needs_review": 1,
    "mixed": 2,
    "good": 3,
}


@dataclass
class PromptEvalCase:
    id: str
    prompt: str
    suite: str = "deterministic"
    llm_mode: str = "none"
    expected_route: str = ""
    max_deterministic_ms: int = 0
    max_prompt_build_ms: int = 0
    max_first_token_ms: int = 0
    max_ollama_ms: int = 0
    max_total_ms: int = 0
    min_usability: str = "needs_review"
    must_include: list[str] | None = None


@dataclass
class PromptSmokeResult:
    case_id: str
    run_index: int
    prompt: str
    suite: str
    llm_mode: str
    expected_route: str
    route_ok: bool
    route: str
    execution_route: str
    provider: str
    model_route_role: str
    model_route_model: str
    deterministic_action: str
    deterministic_label: str
    planned_path: list[str]
    target_paths: list[str]
    deterministic_ms: int
    prompt_build_ms: int
    ollama_model: str
    ollama_first_token_ms: int
    ollama_ms: int
    total_ms: int
    prompt_eval_count: int
    eval_count: int
    output_excerpt: str
    usability: str
    passed: bool
    notes: list[str]
    failures: list[str]


def _post_ollama_streamed(
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    num_ctx: int,
    num_predict: int,
    timeout: int,
) -> tuple[dict[str, Any], int]:
    settings = load_settings()
    payload = json.dumps(
        {
            "model": model.replace("ollama:", "", 1),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": True,
            "keep_alive": ollama_keep_alive(settings),
            "options": build_ollama_options(num_ctx=num_ctx, num_predict=num_predict, settings=settings),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    started = time.perf_counter()
    first_token_ms = 0
    content_parts: list[str] = []
    final_data: dict[str, Any] = {}
    read_timeout = max(5, min(10, int(timeout)))
    try:
        with opener.open(req, timeout=read_timeout) as response:
            for raw_line in response:
                elapsed = time.perf_counter() - started
                if elapsed > timeout:
                    final_data.setdefault("done", False)
                    final_data["stopped_by_timeout"] = True
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                data = json.loads(line)
                final_data = data
                chunk = ((data.get("message") or {}).get("content") or "")
                if chunk:
                    if not first_token_ms:
                        first_token_ms = int((time.perf_counter() - started) * 1000)
                    content_parts.append(chunk)
                if data.get("done"):
                    break
                if time.perf_counter() - started > timeout:
                    final_data["stopped_by_timeout"] = True
                    break
    except (TimeoutError, socket.timeout) as exc:
        final_data.setdefault("done", False)
        final_data["stopped_by_timeout"] = True
        final_data["timeout_error"] = str(exc)
    final_data["message"] = {"content": "".join(content_parts)}
    return final_data, first_token_ms


def _choose_installed_synthesis_model(
    requested_model: str,
    installed_models: list[str],
    *,
    model_tier: str,
) -> str:
    installed_lower = {item.lower(): item for item in installed_models}
    requested = str(requested_model or "").replace("ollama:", "", 1)
    if requested.lower() in installed_lower:
        return installed_lower[requested.lower()]

    if model_tier == "strong":
        preferred = ("qwen3:14b", "qwen2.5-coder:14b", "qwen3:8b", "qwen2.5-coder:7b")
    elif model_tier == "standard":
        preferred = ("qwen2.5-coder:7b", "qwen3:8b", "qwen2.5-coder:14b", "qwen3:14b")
    else:
        preferred = ("qwen2.5-coder:7b", "qwen3:8b", "qwen2.5-coder:14b", "qwen3:14b")
    for candidate in preferred:
        if candidate.lower() in installed_lower:
            return installed_lower[candidate.lower()]
    return resolve_installed_ollama_model(
        requested,
        installed_models,
        prefer_coder=model_tier != "strong",
    )


def _assess_output(text: str, prompt: str) -> tuple[str, list[str]]:
    lower = (text or "").lower()
    notes: list[str] = []
    if not text or len(text.strip()) < 40:
        return "poor", ["empty_or_too_short"]
    if "[project search error]" in lower or "unable to open database" in lower:
        return "poor", ["project_index_error"]
    if "i don't know" in lower or "cannot" in lower and "project" in lower:
        notes.append("uncertain_or_blocked")
    if "source:" in lower or "best match" in lower or "plan" in lower or "steps" in lower:
        notes.append("structured")
    if "which file should i modify" in lower or "could not find a confident edit target" in lower:
        notes.append("actionable_clarification")
    if "what functions" in prompt.lower() and ("create_" in text or "function" in lower):
        notes.append("answers_function_query")
    if "inspect" in prompt.lower() and ("found" in lower or "check" in lower or "search" in lower):
        notes.append("addresses_inspection")
    if len(notes) >= 2:
        return "good", notes
    if "actionable_clarification" in notes:
        return "mixed", notes
    if notes:
        return "mixed", notes
    return "needs_review", notes


def _case_from_prompt(prompt: str, index: int = 0) -> PromptEvalCase:
    return PromptEvalCase(id=f"prompt_{index + 1}", prompt=prompt)


def _load_cases(path: str, prompts: list[str]) -> list[PromptEvalCase]:
    if prompts:
        return [_case_from_prompt(prompt, index) for index, prompt in enumerate(prompts)]
    if path:
        raw_path = Path(path)
        if raw_path.exists():
            data = json.loads(raw_path.read_text(encoding="utf-8"))
            cases = []
            for index, item in enumerate(data):
                if isinstance(item, str):
                    cases.append(_case_from_prompt(item, index))
                elif isinstance(item, dict):
                    cases.append(
                        PromptEvalCase(
                            id=str(item.get("id") or f"case_{index + 1}"),
                            prompt=str(item.get("prompt") or ""),
                            suite=str(item.get("suite") or "deterministic"),
                            llm_mode=str(item.get("llm_mode") or item.get("expected_ollama") or "none"),
                            expected_route=str(item.get("expected_route") or ""),
                            max_deterministic_ms=int(item.get("max_deterministic_ms") or 0),
                            max_prompt_build_ms=int(item.get("max_prompt_build_ms") or 0),
                            max_first_token_ms=int(item.get("max_first_token_ms") or 0),
                            max_ollama_ms=int(item.get("max_ollama_ms") or 0),
                            max_total_ms=int(item.get("max_total_ms") or 0),
                            min_usability=str(item.get("min_usability") or "needs_review"),
                            must_include=list(item.get("must_include") or []),
                        )
                    )
            return [case for case in cases if case.prompt.strip()]
    return [_case_from_prompt(prompt, index) for index, prompt in enumerate(DEFAULT_PROMPTS)]


def _score_result(
    *,
    case: PromptEvalCase,
    route: str,
    deterministic_ms: int,
    prompt_build_ms: int,
    ollama_first_token_ms: int,
    ollama_ms: int,
    total_ms: int,
    output_text: str,
    usability: str,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if case.expected_route and route != case.expected_route:
        failures.append(f"route_expected_{case.expected_route}_got_{route}")
    if case.max_deterministic_ms and deterministic_ms > case.max_deterministic_ms:
        failures.append(f"deterministic_ms_{deterministic_ms}_over_{case.max_deterministic_ms}")
    if case.max_prompt_build_ms and prompt_build_ms > case.max_prompt_build_ms:
        failures.append(f"prompt_build_ms_{prompt_build_ms}_over_{case.max_prompt_build_ms}")
    if case.max_first_token_ms and ollama_first_token_ms > case.max_first_token_ms:
        failures.append(f"first_token_ms_{ollama_first_token_ms}_over_{case.max_first_token_ms}")
    if case.max_ollama_ms and ollama_ms > case.max_ollama_ms:
        failures.append(f"ollama_ms_{ollama_ms}_over_{case.max_ollama_ms}")
    if case.max_total_ms and total_ms > case.max_total_ms:
        failures.append(f"total_ms_{total_ms}_over_{case.max_total_ms}")
    llm_mode = (case.llm_mode or "none").lower()
    if llm_mode in {"required", "synthesis", "force", "must"} and ollama_ms <= 0:
        failures.append("ollama_required_but_not_used")
    if llm_mode in {"none", "deterministic", "forbidden"} and ollama_ms > 0:
        failures.append("ollama_used_in_deterministic_case")
    min_score = USABILITY_SCORE.get(case.min_usability, 1)
    if USABILITY_SCORE.get(usability, 0) < min_score:
        failures.append(f"usability_{usability}_below_{case.min_usability}")
    lower = (output_text or "").lower()
    for required in case.must_include or []:
        if str(required).lower() not in lower:
            failures.append(f"missing_required_text_{required}")
    return not failures, failures


def _planned_path(decision: Any, engine_result: Any) -> list[str]:
    route_dict = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
    path = [
        f"route:{route_dict.get('route') or '-'}",
        f"execution:{route_dict.get('execution_route') or '-'}",
        f"provider:{route_dict.get('provider') or '-'}",
    ]
    host = route_dict.get("host")
    if host:
        path.append(f"host:{host}")
    callable_name = route_dict.get("callable") or route_dict.get("operation") or route_dict.get("target")
    if callable_name:
        path.append(f"callable:{callable_name}")
    metadata = getattr(engine_result, "metadata", None) or {}
    if metadata.get("engine_path"):
        path.append(f"engine:{metadata.get('engine_path')}")
    if metadata.get("result_type"):
        path.append(f"result:{metadata.get('result_type')}")
    graph = metadata.get("graph") or metadata.get("action_graph") or {}
    for action in list(graph.get("actions") or [])[:8]:
        kind = action.get("kind") or action.get("type") or "action"
        label = action.get("label") or action.get("operation") or action.get("callable") or action.get("id") or ""
        path.append(f"{kind}:{label}")
    return [str(item) for item in path if str(item).strip()]


def _target_paths(engine_result: Any) -> list[str]:
    metadata = getattr(engine_result, "metadata", None) or {}
    discovery = metadata.get("discovery") or {}
    candidates = discovery.get("candidates") or []
    paths: list[str] = []
    best = discovery.get("best_target") or {}
    if best.get("path"):
        paths.append(f"best:{best.get('path')}")
    for item in candidates[:8]:
        path = str(item.get("path") or "")
        if path and f"best:{path}" not in paths and path not in paths:
            paths.append(path)
    return paths


def _should_call_ollama(case: PromptEvalCase, *, force_ollama: bool, decision: Any, engine_result: Any) -> bool:
    llm_mode = (case.llm_mode or "none").lower()
    if force_ollama or llm_mode in {"required", "synthesis", "force", "must"}:
        return True
    if llm_mode in {"none", "deterministic", "forbidden"}:
        return False
    return engine_result.action in {"passthrough", "send_raw"} or decision.provider == "llm"


def _grounding_packet(engine_result: Any, prompt: str = "") -> str:
    metadata = getattr(engine_result, "metadata", None) or {}
    discovery = metadata.get("discovery") or {}
    lines: list[str] = []
    best = discovery.get("best_target") or {}
    if best.get("path"):
        lines.append(f"Best target path: {best.get('path')}")
        lines.append(f"Best target score: {best.get('score')}")
    candidates = discovery.get("candidates") or []
    if candidates:
        lines.append("Candidate paths:")
        for index, item in enumerate(candidates[:8], start=1):
            lines.append(f"{index}. {item.get('path')} score={item.get('score')}")
    symbol_lines = _candidate_symbol_grounding([best, *list(candidates or [])], prompt=prompt)
    if symbol_lines:
        lines.extend(["", "Indexed symbols in candidate files:", *symbol_lines])
    return "\n".join(lines)


def _candidate_symbol_grounding(candidates: list[dict[str, Any]], *, prompt: str = "") -> list[str]:
    try:
        from services.project_search_service import _symbol_rows_for_file
    except Exception:
        return []
    seen: set[str] = set()
    lines: list[str] = []
    for item in candidates[:4]:
        path = str((item or {}).get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        rows = [
            row
            for row in _symbol_rows_for_file(path, kinds=("function", "method"), limit=3000)
            if str(row.get("name") or "") not in {"__init__"}
        ]
        prompt_terms = {
            term
            for term in "".join(ch if ch.isalnum() else " " for ch in prompt.lower()).split()
            if len(term) >= 3 and term not in {"the", "and", "for", "with", "that", "this", "from", "into", "what", "have", "existing", "function", "multiple", "arguments"}
        }
        if "rigging" in prompt_terms:
            prompt_terms.add("rig")
        if "creating" in prompt_terms or "creation" in prompt_terms:
            prompt_terms.add("create")
        wants_multiple_args = "multiple" in prompt.lower() and ("argument" in prompt.lower() or "param" in prompt.lower())

        def score(row: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
            name = str(row.get("name") or "").lower()
            signature = str(row.get("signature") or "")
            arg_count = 0 if not signature else max(0, signature.count(",") + 1)
            is_method = 1 if str(row.get("kind") or "").lower() == "method" else 0
            is_private = 1 if str(row.get("name") or "").startswith("_") else 0
            name_words = set(name.replace("_", " ").split())
            term_hits = len(prompt_terms.intersection(name_words))
            action_hit = 0 if {"create", "build", "setup"}.intersection(name_words) else 1
            multiple_arg_penalty = 1 if wants_multiple_args and arg_count < 2 else 0
            practical_arg_penalty = 0 if 1 <= arg_count <= 4 else abs(arg_count - 3)
            return (is_private, is_method, -term_hits, action_hit, multiple_arg_penalty, practical_arg_penalty, arg_count)
        rows = sorted(rows, key=score)
        if rows:
            lines.append(f"- {path}")
            for row in rows[:6]:
                name = row.get("name") or "symbol"
                signature = row.get("signature") or f"{name}()"
                if not str(signature).startswith(str(name)):
                    signature = f"{name}{signature}"
                line = row.get("start_line") or row.get("line") or row.get("line_start") or "?"
                kind = row.get("kind") or "function"
                lines.append(f"  - {signature} [{kind}, line {line}]")
    return lines


def _compact_model_evidence(engine_result: Any, *, max_chars: int = 1800) -> str:
    text = str(engine_result.text or engine_result.prompt or "").strip()
    if not text:
        return "[none]"
    if "Relevant symbols:" in text:
        text = text.split("Relevant symbols:", 1)[0].rstrip()
    text = "\n".join(line.rstrip() for line in text.splitlines() if not line.lstrip().startswith("```"))
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[deterministic evidence truncated]"


def run_prompt(
    case: PromptEvalCase,
    *,
    run_index: int,
    active_path: str,
    project_root: str,
    model: str,
    force_ollama: bool,
    use_router_model: bool,
    timeout: int,
) -> PromptSmokeResult:
    prompt = case.prompt
    context = RequestContext(
        text=prompt,
        current_file_path=active_path,
        project_roots=(project_root,),
        model=model,
        index_state="Index ready",
    )

    started = time.perf_counter()
    decision = classify_prompt_route(prompt, active_path=active_path, project_roots=[project_root])
    context = RequestContext(
        text=prompt,
        current_file_path=active_path,
        project_roots=(project_root,),
        model=model,
        index_state="Index ready",
        extras={"prompt_route_decision": decision.to_dict()},
    )
    engine_result = RequestEngine(progress=lambda _event: None, activity=lambda _event: None).process(context)
    deterministic_ms = int((time.perf_counter() - started) * 1000)

    model_route = AIRouter().route_prompt(
        prompt,
        editor_active=False,
        tiers=ModelTiers(active=model),
        allow_local_only=True,
    )

    output_text = engine_result.text or ""
    prompt_build_ms = 0
    ollama_first_token_ms = 0
    ollama_ms = 0
    prompt_eval_count = 0
    eval_count = 0
    ollama_model = ""

    should_call_ollama = _should_call_ollama(case, force_ollama=force_ollama, decision=decision, engine_result=engine_result)
    if should_call_ollama:
        prompt_build_started = time.perf_counter()
        settings = load_settings()
        requested_model = ((model_route.model if use_router_model else model) or model).replace("ollama:", "", 1)
        budget = choose_ollama_generation_budget(
            prompt=prompt,
            evidence_text=f"{_grounding_packet(engine_result, prompt)}\n\n{_compact_model_evidence(engine_result)}",
            route=decision.route,
            llm_mode=case.llm_mode,
            confidence=getattr(decision, "confidence", None),
            settings=settings,
        )
        if budget.model_tier == "strong":
            requested_model = str(settings.get("router_local_deep") or requested_model).replace("ollama:", "", 1)
        elif budget.model_tier == "standard":
            requested_model = str(settings.get("router_local_plan") or requested_model).replace("ollama:", "", 1)
        installed_models = get_installed_ollama_models()
        ollama_model = _choose_installed_synthesis_model(
            requested_model,
            installed_models,
            model_tier=budget.model_tier,
        )
        system_prompt = (
            "You are the Tech Connector local prompt evaluator. Answer from the provided project/route facts. "
            "Be concise, concrete, and do not invent files or APIs. "
            "If a Best target path is provided, treat it as the primary candidate unless the user explicitly asked for a different layer. "
            "If Indexed symbols are provided, treat the first symbol under the Best target as the primary callable unless it is clearly unsuitable."
        )
        grounding = _grounding_packet(engine_result, prompt)
        user_prompt = (
            f"Route: {decision.route}\n"
            f"Execution route: {decision.execution_route}\n"
            f"Active file: {active_path}\n\n"
            "Grounded route/path facts:\n"
            f"{grounding or '[none]'}\n\n"
            "Deterministic project evidence/result:\n"
            f"{_compact_model_evidence(engine_result)}\n\n"
            f"User prompt:\n{prompt}\n\n"
            "Return the useful answer the user should see with these sections when applicable:\n"
            "1. Evidence used\n"
            "2. Recommended plan\n"
            "3. Exact files/assets involved\n"
            "4. Tests or validation to run\n"
            "5. Missing facts or approval needed\n"
            "Use the deterministic evidence above as ground truth. If the evidence is insufficient, say what is missing instead of inventing files, commands, or APIs. "
            "The Active file is only UI context; do not list it as an involved file/asset unless it also appears in the grounded target paths or the user explicitly asked about the active file."
        )
        prompt_build_ms = int((time.perf_counter() - prompt_build_started) * 1000)
        model_started = time.perf_counter()
        try:
            case_timeout = int(case.max_ollama_ms / 1000) if case.max_ollama_ms else 0
            effective_timeout = max(timeout, budget.timeout_seconds)
            if case_timeout:
                effective_timeout = min(effective_timeout, case_timeout)
            data, ollama_first_token_ms = _post_ollama_streamed(
                ollama_model,
                system_prompt,
                user_prompt,
                num_ctx=budget.num_ctx,
                num_predict=budget.num_predict,
                timeout=effective_timeout,
            )
            ollama_ms = int((time.perf_counter() - model_started) * 1000)
            output_text = ((data.get("message") or {}).get("content") or "").strip()
            if data.get("stopped_by_timeout"):
                suffix = f"\n\n[OLLAMA STOPPED BY TIMEOUT after {effective_timeout}s]"
                output_text = f"{output_text}{suffix}" if output_text else suffix.strip()
            prompt_eval_count = int(data.get("prompt_eval_count") or 0)
            eval_count = int(data.get("eval_count") or 0)
        except Exception as exc:
            ollama_ms = int((time.perf_counter() - model_started) * 1000)
            output_text = f"[OLLAMA ERROR] {exc}"

    total_ms = int((time.perf_counter() - started) * 1000)
    usability, notes = _assess_output(output_text, prompt)
    passed, failures = _score_result(
        case=case,
        route=decision.route,
        deterministic_ms=deterministic_ms,
        prompt_build_ms=prompt_build_ms,
        ollama_first_token_ms=ollama_first_token_ms,
        ollama_ms=ollama_ms,
        total_ms=total_ms,
        output_text=output_text,
        usability=usability,
    )
    return PromptSmokeResult(
        case_id=case.id,
        run_index=run_index,
        prompt=prompt,
        suite=case.suite,
        llm_mode=case.llm_mode,
        expected_route=case.expected_route,
        route_ok=not case.expected_route or decision.route == case.expected_route,
        route=decision.route,
        execution_route=decision.execution_route,
        provider=decision.provider,
        model_route_role=model_route.session_role,
        model_route_model=model_route.model,
        deterministic_action=engine_result.action,
        deterministic_label=engine_result.label,
        planned_path=_planned_path(decision, engine_result),
        target_paths=_target_paths(engine_result),
        deterministic_ms=deterministic_ms,
        prompt_build_ms=prompt_build_ms,
        ollama_model=ollama_model,
        ollama_first_token_ms=ollama_first_token_ms,
        ollama_ms=ollama_ms,
        total_ms=total_ms,
        prompt_eval_count=prompt_eval_count,
        eval_count=eval_count,
        output_excerpt="\n".join(output_text.splitlines()[:12]),
        usability=usability,
        passed=passed,
        notes=notes,
        failures=failures,
    )


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(len(ordered) * percentile) - 1)))
    return ordered[index]


def summarize_results(results: list[PromptSmokeResult]) -> dict[str, Any]:
    deterministic = [result.deterministic_ms for result in results]
    prompt_build = [result.prompt_build_ms for result in results if result.prompt_build_ms]
    first_token = [result.ollama_first_token_ms for result in results if result.ollama_first_token_ms]
    ollama = [result.ollama_ms for result in results if result.ollama_ms]
    total = [result.total_ms for result in results]
    failed = [result for result in results if not result.passed]
    by_route: dict[str, int] = {}
    by_usability: dict[str, int] = {}
    by_suite: dict[str, dict[str, Any]] = {}
    for result in results:
        by_route[result.route] = by_route.get(result.route, 0) + 1
        by_usability[result.usability] = by_usability.get(result.usability, 0) + 1
        suite = result.suite or "deterministic"
        entry = by_suite.setdefault(
            suite,
            {
                "count": 0,
                "passed": 0,
                "failed": 0,
                "deterministic_ms": [],
                "prompt_build_ms": [],
                "first_token_ms": [],
                "ollama_ms": [],
                "total_ms": [],
            },
        )
        entry["count"] += 1
        entry["passed"] += 1 if result.passed else 0
        entry["failed"] += 0 if result.passed else 1
        entry["deterministic_ms"].append(result.deterministic_ms)
        if result.prompt_build_ms:
            entry["prompt_build_ms"].append(result.prompt_build_ms)
        if result.ollama_first_token_ms:
            entry["first_token_ms"].append(result.ollama_first_token_ms)
        if result.ollama_ms:
            entry["ollama_ms"].append(result.ollama_ms)
        entry["total_ms"].append(result.total_ms)

    def timing(values: list[int]) -> dict[str, int | float]:
        return {
            "avg": round(sum(values) / len(values), 2) if values else 0,
            "p50": _percentile(values, 0.5),
            "p95": _percentile(values, 0.95),
            "max": max(values) if values else 0,
        }

    by_suite_summary: dict[str, dict[str, Any]] = {}
    for suite, entry in by_suite.items():
        by_suite_summary[suite] = {
            "count": entry["count"],
            "passed": entry["passed"],
            "failed": entry["failed"],
            "deterministic_ms": timing(entry["deterministic_ms"]),
            "prompt_build_ms": timing(entry["prompt_build_ms"]),
            "first_token_ms": timing(entry["first_token_ms"]),
            "ollama_ms": timing(entry["ollama_ms"]),
            "total_ms": timing(entry["total_ms"]),
        }
    return {
        "count": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "deterministic_ms": timing(deterministic),
        "prompt_build_ms": timing(prompt_build),
        "first_token_ms": timing(first_token),
        "ollama_ms": timing(ollama),
        "total_ms": timing(total),
        "suites": by_suite_summary,
        "routes": by_route,
        "usability": by_usability,
        "failures": [
            {
                "case_id": result.case_id,
                "run_index": result.run_index,
                "prompt": result.prompt,
                "failures": result.failures,
                "route": result.route,
                "expected_route": result.expected_route,
                "deterministic_ms": result.deterministic_ms,
                "prompt_build_ms": result.prompt_build_ms,
                "first_token_ms": result.ollama_first_token_ms,
                "ollama_ms": result.ollama_ms,
                "total_ms": result.total_ms,
                "usability": result.usability,
            }
            for result in failed
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Tech Connector prompt smoke checks against local Ollama.")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--active-path", default="C:/depot/tools/custom_qt/custom_widgets.py")
    parser.add_argument("--project-root", default="C:/depot/tools")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--cases", default=str(ROOT / "scripts" / "prompt_eval_cases.json"))
    parser.add_argument("--force-ollama", action="store_true", help="Send every prompt to Ollama after deterministic routing.")
    parser.add_argument("--require-synthesis", action="store_true", help="Alias for --force-ollama; requires local model synthesis for all cases.")
    parser.add_argument("--use-router-model", action="store_true", help="Use the app router's selected model instead of the --model value for synthesis calls.")
    parser.add_argument(
        "--suite",
        choices=("all", "deterministic", "synthesis", "end_to_end"),
        default="all",
        help="Run only one prompt test lane.",
    )
    parser.add_argument("--jsonl", default="")
    parser.add_argument("--summary-json", default="")
    parser.add_argument("prompts", nargs="*")
    args = parser.parse_args()

    cases = _load_cases(args.cases, args.prompts)
    if args.suite != "all":
        cases = [case for case in cases if (case.suite or "deterministic") == args.suite]
    results: list[PromptSmokeResult] = []
    for run_index in range(1, max(1, int(args.repeat or 1)) + 1):
        for case in cases:
            results.append(
                run_prompt(
                    case,
                    run_index=run_index,
                    active_path=args.active_path,
                    project_root=args.project_root,
                    model=args.model,
                    force_ollama=bool(args.force_ollama or args.require_synthesis),
                    use_router_model=bool(args.use_router_model),
                    timeout=args.timeout,
                )
            )

    if args.jsonl:
        out_path = Path(args.jsonl)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("w", encoding="utf-8") as handle:
                for result in results:
                    handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"[prompt-smoke] Could not write JSONL report {out_path}: {exc}", file=sys.stderr)
    summary = summarize_results(results)
    if args.summary_json:
        summary_path = Path(args.summary_json)
        try:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"[prompt-smoke] Could not write summary report {summary_path}: {exc}", file=sys.stderr)

    for result in results:
        print("=" * 88)
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.case_id} run={result.run_index}: {result.prompt}")
        print(
            f"suite={result.suite} llm_mode={result.llm_mode} route={result.route} "
            f"exec={result.execution_route} provider={result.provider} "
            f"deterministic={result.deterministic_ms}ms prompt_build={result.prompt_build_ms}ms "
            f"first_token={result.ollama_first_token_ms}ms ollama={result.ollama_ms}ms "
            f"total={result.total_ms}ms model={result.ollama_model or '-'}"
        )
        print(f"action={result.deterministic_action} label={result.deterministic_label} usability={result.usability} notes={','.join(result.notes) or '-'}")
        if result.planned_path:
            print("planned_path=" + " -> ".join(result.planned_path))
        if result.target_paths:
            print("target_paths:")
            for path in result.target_paths[:8]:
                print(f"  - {path}")
        if result.failures:
            print("failures=" + ", ".join(result.failures))
        print(result.output_excerpt)
    print("=" * 88)
    print(
        f"SUMMARY count={summary['count']} passed={summary['passed']} failed={summary['failed']} "
        f"det_avg={summary['deterministic_ms']['avg']}ms det_p95={summary['deterministic_ms']['p95']}ms "
        f"first_token_avg={summary['first_token_ms']['avg']}ms first_token_p95={summary['first_token_ms']['p95']}ms "
        f"ollama_avg={summary['ollama_ms']['avg']}ms ollama_p95={summary['ollama_ms']['p95']}ms "
        f"total_avg={summary['total_ms']['avg']}ms total_p95={summary['total_ms']['p95']}ms"
    )
    for suite, suite_summary in summary.get("suites", {}).items():
        print(
            f"SUITE {suite}: count={suite_summary['count']} passed={suite_summary['passed']} "
            f"failed={suite_summary['failed']} det_avg={suite_summary['deterministic_ms']['avg']}ms "
            f"first_token_avg={suite_summary['first_token_ms']['avg']}ms "
            f"ollama_avg={suite_summary['ollama_ms']['avg']}ms total_avg={suite_summary['total_ms']['avg']}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
