"""Lightweight semantic verification that a candidate plan matches its prompt."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import re
import threading
from time import perf_counter
from typing import Any, Callable


PlanVerifierQuery = Callable[[str, str], str | None]
_ALIGNMENT_CACHE: OrderedDict[str, str] = OrderedDict()
_ALIGNMENT_CACHE_LOCK = threading.Lock()
_ALIGNMENT_CACHE_LIMIT = 256


def build_requirement_omission_cases(
    chunks: list[dict[str, Any]],
    candidate_steps: list[str],
) -> list[dict[str, Any]]:
    """Build deterministic near-miss plans by omitting one requirement's evidence."""

    steps = [str(item) for item in candidate_steps]
    cases: list[dict[str, Any]] = []
    for chunk in chunks:
        evidence = str(chunk.get("evidence") or "").strip()
        omitted_steps = list(steps)
        if evidence and evidence != "(no matching plan commitment)":
            omitted_steps = [step for step in steps if step != evidence]
        cases.append({
            "id": f"omit_{chunk.get('id') or 'requirement'}",
            "omitted_requirement_id": str(chunk.get("id") or ""),
            "omitted_requirement": str(chunk.get("requirement") or ""),
            "candidate_steps": omitted_steps,
            "removed_evidence": evidence,
            "should_match": False,
        })
    return cases


def _verdict_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["match", "missing", "wrong", "unsupported", "confidence"],
        "properties": {
            "match": {"type": "boolean"},
            "missing": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["text", "reason"], "properties": {
                "text": {"type": "string"}, "reason": {"type": "string"}, "capability": {"type": "string"},
            }}},
            "wrong": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["text", "claim", "reason"], "properties": {
                "text": {"type": "string"}, "claim": {"type": "string"}, "reason": {"type": "string"},
            }}},
            "unsupported": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["claim", "reason"], "properties": {
                "claim": {"type": "string"}, "reason": {"type": "string"},
            }}},
            "confidence": {"type": "number"},
        },
    }


def _match_only_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["match", "reason"],
        "properties": {
            "match": {"type": "boolean"},
            "reason": {"type": "string"},
        },
        "additionalProperties": False,
    }


def verify_prompt_plan_alignment(
    prompt: str,
    candidate_plan: dict[str, Any],
    *,
    model_query: PlanVerifierQuery | None = None,
    fallback_model_query: PlanVerifierQuery | None = None,
    primary_tier: str = "semantic_1_5b",
) -> dict[str, Any]:
    """Critique coverage only; never route, rewrite, or execute the plan."""
    started = perf_counter()
    packet = {
        "request": " ".join(str(prompt or "").split()),
        "candidate_plan": _compact_candidate(candidate_plan),
    }
    system = """Compare REQUEST to CANDIDATE. Do not plan, route, rewrite, or design implementation.
Return JSON only: {"match":bool,"missing":[{"text":str,"reason":str,"capability":str}],
"wrong":[{"text":str,"claim":str,"reason":str}],"unsupported":[{"claim":str,"reason":str}],"confidence":number}.
Check every requested source, relationship, behavior, control, integration, and proof condition. Broad create/add/attach
does not cover a specific behavior unless a candidate step promises that behavior. The capability field is optional and
must be empty unless CANDIDATE itself names an unresolved capability. Treat candidate steps as promised outcomes, not
explanations already delivered. Never infer or report missing skills, expertise, tools, APIs, wrappers, code methods,
research, or implementation details; a stronger grounded planner owns those decisions.
Extra implementation detail is not a mismatch. Return at most 6 concise items per list. Empty missing/wrong/unsupported
lists are allowed only when match is true."""

    if model_query is None:
        model_query = _default_model_query
    if fallback_model_query is None:
        fallback_model_query = _default_fallback_model_query
    try:
        verifier_tier = str(primary_tier or "semantic_1_5b")
        query_system = system
        query_packet = packet
        if verifier_tier in {"semantic_code_3b", "semantic_alignment_8b"}:
            query_system = (
                "USER_REQUEST is what the user asked for. CANDIDATE_STEPS is the proposed plan. "
                "When USER_REQUEST contains ONLY REQUIREMENT TO VERIFY, compare only that focused requirement; "
                "FULL ORIGINAL REQUEST is context and must not create additional checks. "
                "Return match true only when the steps preserve all explicit requested outcomes and do not contradict them. "
                "Do not identify skills, APIs, tools, implementation methods, or additional implied requirements. "
                "Return only JSON with match and one short reason."
            )
            query_packet = {
                "USER_REQUEST": packet["request"],
                "CANDIDATE_OPERATION": packet["candidate_plan"].get("operation") or "",
                "CANDIDATE_STEPS": list(packet["candidate_plan"].get("operation_steps") or []),
            }
        primary_started = perf_counter()
        raw = model_query(query_system, json.dumps(query_packet, separators=(",", ":"), default=str))
        primary_ms = round((perf_counter() - primary_started) * 1000.0, 3)
        fallback_raw = ""
        fallback_ms = 0.0
        parsed = _parse_json_object(raw or "")
        if not parsed:
            retry_packet = {
                "request": packet["request"],
                "operation": packet["candidate_plan"].get("operation") or "",
                "steps": list(packet["candidate_plan"].get("operation_steps") or []),
            }
            fallback_started = perf_counter()
            fallback_raw = fallback_model_query(
                "Compare the request with the candidate steps. Return the required verdict JSON only.",
                json.dumps(retry_packet, separators=(",", ":"), default=str),
            ) or ""
            fallback_ms = round((perf_counter() - fallback_started) * 1000.0, 3)
            verifier_tier = "semantic_code_3b_fallback"
            parsed = _parse_json_object(fallback_raw)
        if not parsed:
            raise ValueError("Verifier returned no JSON object after one bounded retry")
        operation = str(packet["candidate_plan"].get("operation") or "")
        result = _normalize_verdict(parsed, default_namespace=operation.partition(".")[0])
        retained_missing = []
        dismissed_missing = []
        candidate_text = json.dumps(packet["candidate_plan"], default=str)
        for item in result["missing"]:
            if _candidate_covers_fragment(item.get("request_fragment") or "", candidate_text):
                dismissed_missing.append(item)
            else:
                retained_missing.append(item)
        result["missing"] = retained_missing
        result["dismissed_missing"] = dismissed_missing
        if dismissed_missing and not retained_missing and not result["distorted"] and not result["unsupported_claims"]:
            result["matches_request"] = True
        contradictory_missing = any(
            re.search(r"\b(?:closely matches|matches the request|includes the necessary)\b", item.get("reason") or "", re.I)
            for item in result["missing"]
        )
        if (result["confidence"] < 0.65 or contradictory_missing) and verifier_tier == "semantic_1_5b":
            fallback_started = perf_counter()
            fallback_raw = fallback_model_query(system, json.dumps(packet, separators=(",", ":"), default=str)) or ""
            fallback_ms = round((perf_counter() - fallback_started) * 1000.0, 3)
            fallback_parsed = _parse_json_object(fallback_raw or "")
            if fallback_parsed:
                fallback_result = _normalize_verdict(
                    fallback_parsed,
                    default_namespace=operation.partition(".")[0],
                )
                if fallback_result["confidence"] >= result["confidence"]:
                    result = fallback_result
                    verifier_tier = "semantic_code_3b_fallback"
        for raw_gap in packet["candidate_plan"].get("known_gaps") or []:
            gap = dict(raw_gap or {}) if isinstance(raw_gap, dict) else {"reason": str(raw_gap or "")}
            row = {
                "request_fragment": str(gap.get("request_fragment") or "known capability gap").strip(),
                "reason": str(gap.get("reason") or "The candidate declares this requirement unresolved.").strip(),
                "required_capability": str(gap.get("required_capability") or "").strip(),
            }
            existing_capabilities = {
                str(item.get("required_capability") or "")
                for item in result["missing"]
                if str(item.get("required_capability") or "")
            }
            if row["required_capability"] not in existing_capabilities:
                result["missing"].append(row)
        if packet["candidate_plan"].get("known_gaps"):
            result["matches_request"] = False
        result.update(
            {
                "framework": "prompt_plan_alignment_v1",
                "status": "verified" if result["matches_request"] else "mismatch",
                "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
                "model_role": "semantic_plan_critic",
                "verifier_tier": verifier_tier,
                "model_attempts": {
                    "primary_ms": primary_ms,
                    "primary_raw": str(raw or "")[:4000],
                    "fallback_ms": fallback_ms,
                    "fallback_raw": str(fallback_raw or "")[:4000],
                },
            }
        )
        return result
    except Exception as exc:
        from tech_connector.services.llm_router_service import LLMCloudProviderError

        if isinstance(exc, LLMCloudProviderError):
            raise
        return {
            "framework": "prompt_plan_alignment_v1",
            "status": "verifier_unavailable",
            "matches_request": False,
            "covered": [],
            "missing": [],
            "distorted": [],
            "unsupported_claims": [],
            "confidence": 0.0,
            "error": str(exc),
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            "model_role": "semantic_plan_critic",
            "model_attempts": {
                "primary_ms": locals().get("primary_ms", 0.0),
                "primary_raw": str(locals().get("raw") or "")[:4000],
                "fallback_ms": locals().get("fallback_ms", 0.0),
                "fallback_raw": str(locals().get("fallback_raw") or "")[:4000],
            },
        }


def _compact_candidate(plan: dict[str, Any]) -> dict[str, Any]:
    source = dict(plan or {})
    goals = []
    graph = dict(source.get("task_graph") or {})
    for row in list(graph.get("goals") or graph.get("tasks") or [])[:64]:
        item = dict(row or {})
        goals.append(
            {
                "objective": item.get("objective") or item.get("title") or "",
                "capability": item.get("capability") or "",
                "success_condition": item.get("success_condition") or "",
            }
        )
    operation_plan = dict(source.get("operation_plan") or {})
    raw_parameters = dict(operation_plan.get("parameters") or operation_plan.get("params") or {})
    operation_parameters: dict[str, Any] = {}
    for key, value in raw_parameters.items():
        if key == "parameters" and isinstance(value, dict):
            operation_parameters[key] = {
                str(child_key): child_value
                for child_key, child_value in list(value.items())[:32]
                if isinstance(child_value, (str, int, float, bool, type(None)))
                or (
                    isinstance(child_value, (list, tuple))
                    and len(child_value) <= 4
                    and all(isinstance(item, (str, int, float, bool, type(None))) for item in child_value)
                )
            }
        elif isinstance(value, (str, int, float, bool, type(None))):
            operation_parameters[str(key)] = value
        elif key == "required_parameter_names" and isinstance(value, (list, tuple)):
            operation_parameters[str(key)] = ", ".join(str(item) for item in list(value)[:32])
        elif (
            isinstance(value, (list, tuple))
            and len(value) <= 6
            and all(isinstance(item, (str, int, float, bool, type(None))) for item in value)
        ):
            operation_parameters[str(key)] = list(value)
    return {
        "route": source.get("route") or "",
        "operation": operation_plan.get("operation") or source.get("operation") or "",
        "operation_steps": [str(value) for value in operation_plan.get("steps") or []][:64],
        "operation_parameters": operation_parameters,
        "goals": goals,
        "known_gaps": [
            *list(source.get("known_gaps") or []),
            *list(operation_plan.get("capability_gaps") or []),
        ],
    }


def _default_model_query(system: str, user: str) -> str | None:
    from tech_connector.services.llm_router_service import generate_llm_response
    from tech_connector.services.ollama_service import semantic_intent_model

    return generate_llm_response(
        model=semantic_intent_model(),
        prompt=user,
        system=system,
        response_format=_verdict_schema(),
        options={
            "temperature": 0.0,
            "num_ctx": 4096,
            "num_predict": 640,
            "top_k": 1,
            "top_p": 0.1,
            "repeat_penalty": 1.0,
        },
        timeout=10,
    )


def _default_fallback_model_query(system: str, user: str) -> str | None:
    from tech_connector.services.llm_router_service import generate_llm_response
    from tech_connector.services.ollama_service import semantic_verifier_model

    return generate_llm_response(
        model=semantic_verifier_model(),
        prompt=user,
        system=(
            "Compare the explicit user request with the candidate plan. Return only "
            '{"match": true|false, "reason": "one short sentence"}. '
            "When the request contains ONLY REQUIREMENT TO VERIFY, compare only that requirement and use the full request as context. "
            "Do not propose skills, APIs, tools, or implementation details."
        ),
        response_format=_match_only_schema(),
        options={
            "temperature": 0.0,
            "num_ctx": 3072,
            "num_predict": 360,
            "top_k": 1,
            "top_p": 0.1,
            "repeat_penalty": 1.0,
        },
        timeout=12,
    )


def _default_alignment_model_query(system: str, user: str) -> str | None:
    from tech_connector.services.llm_router_service import _query_ollama
    from tech_connector.services.ollama_service import semantic_alignment_model

    model = semantic_alignment_model()
    key = hashlib.sha256(f"{model}\0{system}\0{user}".encode("utf-8")).hexdigest()
    with _ALIGNMENT_CACHE_LOCK:
        cached = _ALIGNMENT_CACHE.get(key)
        if cached is not None:
            _ALIGNMENT_CACHE.move_to_end(key)
            return cached
    response = _query_ollama(
        model=model,
        prompt=user,
        system=(
            "Compare the explicit requirement with the candidate plan evidence. Return only "
            '{"match": true|false, "reason": "one short sentence"}. '
            "Do not infer extra requirements, skills, APIs, tools, or implementation details."
        ),
        response_format=_match_only_schema(),
        options={
            "temperature": 0.0,
            "num_ctx": 1024,
            "num_predict": 80,
            "top_k": 1,
            "top_p": 0.1,
            "repeat_penalty": 1.0,
            "think": False,
        },
        timeout=30,
    )
    if response:
        with _ALIGNMENT_CACHE_LOCK:
            _ALIGNMENT_CACHE[key] = str(response)
            _ALIGNMENT_CACHE.move_to_end(key)
            while len(_ALIGNMENT_CACHE) > _ALIGNMENT_CACHE_LIMIT:
                _ALIGNMENT_CACHE.popitem(last=False)
    return response


def _parse_json_object(text: str) -> dict[str, Any]:
    source = str(text or "").strip()
    if source.startswith("```"):
        source = re.sub(r"^```(?:json)?\s*|\s*```$", "", source, flags=re.I)
    try:
        value = json.loads(source)
        return dict(value) if isinstance(value, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", source, re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return dict(value) if isinstance(value, dict) else {}
        except Exception:
            return {}


def _candidate_covers_fragment(fragment: str, candidate_text: str) -> bool:
    """Dismiss verifier omissions contradicted by explicit candidate evidence."""

    source = str(candidate_text or "").lower()
    phrase = str(fragment or "").lower()
    if not phrase.strip():
        return False
    critical_groups = (
        (("play", "pie"), ("play", "pie")),
        (("runtime",), ("runtime", "play", "pie")),
        (("camera",), ("camera",)),
        (("blueprint",), ("blueprint",)),
    )
    for triggers, evidence in critical_groups:
        if any(token in phrase for token in triggers) and not any(token in source for token in evidence):
            return False
    stop = {
        "a", "an", "and", "or", "the", "to", "of", "in", "into", "for", "with", "that", "this",
        "how", "does", "not", "specify", "valid",
    }
    terms = {
        token for token in re.findall(r"[a-z0-9_]+", phrase)
        if len(token) >= 3 and token not in stop
    }
    if not terms:
        return False
    covered = sum(1 for token in terms if token in source)
    return covered / len(terms) >= 0.7


def _normalize_verdict(
    value: dict[str, Any],
    *,
    default_namespace: str = "capability",
) -> dict[str, Any]:
    def rows(key: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
        output = []
        for raw in list(value.get(key) or [])[:12]:
            item = dict(raw or {}) if isinstance(raw, dict) else {}
            row = {field: str(item.get(field) or "").strip() for field in fields}
            if any(row.values()):
                output.append(row)
        return output

    missing = []
    seen_missing: set[tuple[str, str]] = set()
    for raw in list(value.get("missing") or [])[:12]:
        item = dict(raw or {}) if isinstance(raw, dict) else {"text": str(raw or "")}
        row = {
            "request_fragment": str(item.get("request_fragment") or item.get("text") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
            "required_capability": str(item.get("required_capability") or item.get("capability") or "").strip(),
        }
        if row["required_capability"] and not re.fullmatch(
            r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+",
            row["required_capability"],
        ):
            row["required_capability"] = ""
        if re.search(r"\bnot (?:directly )?supported by\b", row["reason"], re.I):
            row["reason"] = "The candidate contains no concrete implementation step for this requested behavior."
        signature = (row["request_fragment"].lower(), row["required_capability"])
        if any(row.values()) and signature not in seen_missing:
            seen_missing.add(signature)
            missing.append(row)
    distorted = []
    for raw in list(value.get("distorted") or value.get("wrong") or [])[:12]:
        item = dict(raw or {}) if isinstance(raw, dict) else {"text": str(raw or "")}
        row = {
            "request_fragment": str(item.get("request_fragment") or item.get("text") or "").strip(),
            "plan_claim": str(item.get("plan_claim") or item.get("claim") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        if any(row.values()):
            distorted.append(row)
    unsupported = []
    for raw in list(value.get("unsupported_claims") or value.get("unsupported") or [])[:12]:
        item = dict(raw or {}) if isinstance(raw, dict) else {"claim": str(raw or "")}
        row = {
            "plan_claim": str(item.get("plan_claim") or item.get("claim") or "").strip(),
            "reason": str(item.get("reason") or "").strip(),
        }
        if any(row.values()):
            unsupported.append(row)
    claimed_match = bool(value.get("matches_request", value.get("match", False)))
    reason = str(value.get("reason") or "").strip()
    if (
        not claimed_match
        and re.search(r"\b(?:as requested|matches|preserves|covers all|fully represented)\b", reason, re.I)
        and not re.search(r"\b(?:not|missing|omits|contradicts|fails|except|but)\b", reason, re.I)
    ):
        claimed_match = True
    if not any(key in value for key in ("matches_request", "match")):
        raise ValueError("Verifier verdict omitted match")
    return {
        "matches_request": bool(claimed_match and not missing and not distorted and not unsupported),
        "reason": reason,
        "covered": rows("covered", ("request_fragment", "plan_evidence")),
        "missing": missing,
        "distorted": distorted,
        "unsupported_claims": unsupported,
        "confidence": max(0.0, min(1.0, float(value.get("confidence") or 0.0))),
    }
