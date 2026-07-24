"""Lightweight feed-forward-style route scorer for prompt understanding.

This is intentionally small and deterministic. It behaves like a frozen
single-hidden-layer classifier: extract stable prompt features, apply fixed
weights, and return calibrated route scores. The prompt router uses this as
advisory evidence only; explicit safety rules and registered-action validation
still own execution decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import re
from typing import Any


ROUTES = (
    "dcc_execute",
    "action_graph",
    "target_discovery",
    "project_search",
    "chat",
)

SUPPORTED_DCC_HOSTS = frozenset({
    "maya",
    "unreal",
    "blender",
    "houdini",
    "substance_painter",
    "motionbuilder",
    "unity",
})
FEATURE_NAMES = (
    "host_mentioned",
    "multiple_hosts",
    "dcc_operation_hint",
    "execute_verb",
    "mutation_verb",
    "query_verb",
    "source_file_ref",
    "code_block",
    "api_call",
    "multi_step",
    "pipeline_terms",
    "project_terms",
    "explain_terms",
    "placement_query",
    "no_execute_guard",
    "registered_dcc_hint",
)


@dataclass(frozen=True)
class RouteScore:
    route: str
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RouteScoringResult:
    scores: list[RouteScore]
    features: dict[str, float]
    top_route: str
    confidence: float
    ambiguity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": "request_understanding_fnn_v1",
            "scores": [item.to_dict() for item in self.scores],
            "features": dict(self.features),
            "top_route": self.top_route,
            "confidence": self.confidence,
            "ambiguity": self.ambiguity,
        }


WEIGHTS: dict[str, dict[str, float]] = {
    "dcc_execute": {
        "bias": -0.9,
        "host_mentioned": 1.4,
        "dcc_operation_hint": 0.9,
        "execute_verb": 1.1,
        "mutation_verb": 0.5,
        "api_call": 1.2,
        "multi_step": 0.3,
        "registered_dcc_hint": 0.0,
        "source_file_ref": -1.3,
        "project_terms": -0.6,
        "explain_terms": -0.8,
        "placement_query": -0.9,
        "no_execute_guard": -1.6,
    },
    "action_graph": {
        "bias": -1.0,
        "multi_step": 1.3,
        "pipeline_terms": 1.4,
        "multiple_hosts": 1.1,
        "host_mentioned": 0.2,
        "execute_verb": 0.3,
        "source_file_ref": -0.5,
        "explain_terms": -0.5,
        "placement_query": -0.2,
    },
    "target_discovery": {
        "bias": -0.7,
        "source_file_ref": 1.6,
        "mutation_verb": 1.0,
        "project_terms": 0.7,
        "host_mentioned": -0.2,
        "execute_verb": -0.7,
        "no_execute_guard": 0.2,
        "placement_query": 0.9,
    },
    "project_search": {
        "bias": -0.5,
        "query_verb": 1.0,
        "project_terms": 1.0,
        "source_file_ref": 0.5,
        "explain_terms": 0.5,
        "placement_query": 1.2,
        "no_execute_guard": 0.3,
        "mutation_verb": -0.7,
        "execute_verb": -0.8,
        "host_mentioned": -0.2,
    },
    "chat": {
        "bias": 0.2,
        "explain_terms": 0.5,
        "host_mentioned": -0.4,
        "execute_verb": -0.6,
        "mutation_verb": -0.4,
        "source_file_ref": -0.3,
        "multi_step": -0.4,
        "no_execute_guard": 1.0,
    },
}


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, value))))


def _softmax(logits: dict[str, float]) -> dict[str, float]:
    max_logit = max(logits.values()) if logits else 0.0
    exps = {key: math.exp(value - max_logit) for key, value in logits.items()}
    total = sum(exps.values()) or 1.0
    return {key: value / total for key, value in exps.items()}


def prompt_features(prompt: str, *, host: str = "", hosts: list[str] | None = None, registered_dcc_hint: bool = False) -> dict[str, float]:
    text = prompt or ""
    lower = text.lower()
    hosts = list(hosts or [])
    supported_host = host if host in SUPPORTED_DCC_HOSTS else ""
    supported_hosts = [item for item in hosts if item in SUPPORTED_DCC_HOSTS]
    registered_supported_dcc_hint = bool(registered_dcc_hint and supported_host)
    no_execute_guard = bool(re.search(r"\b(do not execute|don't execute|dont execute|no execute|dry run|plan only)\b", lower))
    placement_query = bool(re.search(r"\b(where should|where would|which file|what file|where do i|where can i)\b", lower))
    execute_verb = bool(not no_execute_guard and re.search(r"\b(run|execute|call|launch|perform|do it)\b", lower))
    mutation_verb = bool(re.search(r"\b(create|make|add|edit|modify|update|fix|patch|delete|move|connect|set|export)\b", lower))
    api_call = bool(re.search(r"\b(api call|call api|maya\.cmds|cmds\.|bpy\.|hou\.|unreal python|run python)\b", lower))
    dcc_operation_hint = bool(supported_host and not no_execute_guard and not placement_query and (execute_verb or mutation_verb or api_call))
    return {
        "host_mentioned": 1.0 if supported_host else 0.0,
        "multiple_hosts": 1.0 if len(supported_hosts) >= 2 else 0.0,
        "dcc_operation_hint": 1.0 if dcc_operation_hint else 0.0,
        "execute_verb": 1.0 if execute_verb else 0.0,
        "mutation_verb": 1.0 if mutation_verb else 0.0,
        "query_verb": 1.0 if re.search(r"\b(what|which|where|list|show|find|inspect|explain|why|how many)\b", lower) else 0.0,
        "source_file_ref": 1.0 if re.search(r"\b[A-Za-z_][A-Za-z0-9_./\\-]*\.(?:py|cpp|h|hpp|cs|qml|ui)\b", text) else 0.0,
        "code_block": 1.0 if "```" in text or re.search(r"\b(import|def|class|print|cmds\.|bpy\.|unreal\.)\b", text) else 0.0,
        "api_call": 1.0 if api_call else 0.0,
        "multi_step": 1.0 if re.search(r"\b(and then|then|after that|next|finally|step\s+\d+)\b", lower) else 0.0,
        "pipeline_terms": 1.0 if re.search(r"\b(pipeline|workflow|graph|node view|compose|sequence|multi-dcc)\b", lower) else 0.0,
        "project_terms": 1.0 if re.search(r"\b(project|codebase|file|function|class|method|module|import|dependency|repo)\b", lower) else 0.0,
        "explain_terms": 1.0 if re.search(r"\b(explain|teach|summarize|compare|review|audit|think)\b", lower) else 0.0,
        "placement_query": 1.0 if placement_query else 0.0,
        "no_execute_guard": 1.0 if no_execute_guard else 0.0,
        "registered_dcc_hint": 1.0 if registered_supported_dcc_hint else 0.0,
    }


def score_prompt_routes(
    prompt: str,
    *,
    host: str = "",
    hosts: list[str] | None = None,
    registered_dcc_hint: bool = False,
) -> RouteScoringResult:
    features = prompt_features(prompt, host=host, hosts=hosts, registered_dcc_hint=registered_dcc_hint)
    logits: dict[str, float] = {}
    for route in ROUTES:
        weights = WEIGHTS[route]
        value = float(weights.get("bias", 0.0))
        for name, feature_value in features.items():
            value += float(weights.get(name, 0.0)) * float(feature_value)
        logits[route] = value
    probabilities = _softmax(logits)
    ordered = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    top_route = ordered[0][0] if ordered else "chat"
    top_score = float(ordered[0][1]) if ordered else 0.0
    second_score = float(ordered[1][1]) if len(ordered) > 1 else 0.0
    active_features = {name for name, value in features.items() if value}
    scores = [
        RouteScore(
            route=route,
            score=round(float(score), 4),
            reasons=[
                name
                for name in FEATURE_NAMES
                if name in active_features and WEIGHTS.get(route, {}).get(name, 0.0) > 0
            ][:6],
        )
        for route, score in ordered
    ]
    return RouteScoringResult(
        scores=scores,
        features={name: float(features.get(name, 0.0)) for name in FEATURE_NAMES},
        top_route=top_route,
        confidence=round(top_score, 4),
        ambiguity=round(max(0.0, 1.0 - (top_score - second_score)), 4),
    )
