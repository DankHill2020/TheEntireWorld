"""Compose prompt-specific gameplay behavior from data-driven atomic primitives."""

from __future__ import annotations

import json
import ast
from pathlib import Path
import re
import time
from typing import Any, Callable


PRIMITIVE_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "unreal_behavior_primitives.json"

BEHAVIOR_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "clause_coverage", "behaviors", "proposed_atomic_operations", "ambiguities", "assumptions"],
    "properties": {
        "summary": {"type": "string"},
        "clause_coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_clause", "classification", "covered_by"],
                "properties": {
                    "source_clause": {"type": "string"},
                    "classification": {"type": "string", "enum": ["behavior", "constraint", "context"]},
                    "covered_by": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "behaviors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id", "title", "source_clauses", "trigger", "observations", "guards", "states",
                    "transitions", "outcomes", "cancellation", "failure_paths", "animation_roles",
                    "proof_scenarios", "operations",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "source_clauses": {"type": "array", "items": {"type": "string"}},
                    "trigger": {"type": "string"},
                    "observations": {"type": "array", "items": {"type": "string"}},
                    "guards": {"type": "array", "items": {"type": "string"}},
                    "states": {"type": "array", "items": {"type": "string"}},
                    "transitions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["from", "event", "guards", "to"],
                            "properties": {
                                "from": {"type": "string"},
                                "event": {"type": "string"},
                                "guards": {"type": "array", "items": {"type": "string"}},
                                "to": {"type": "string"},
                            },
                        },
                    },
                    "outcomes": {"type": "array", "items": {"type": "string"}},
                    "cancellation": {"type": "array", "items": {"type": "string"}},
                    "failure_paths": {"type": "array", "items": {"type": "string"}},
                    "animation_roles": {"type": "array", "items": {"type": "string"}},
                    "proof_scenarios": {"type": "array", "items": {"type": "string"}},
                    "operations": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "proposed_atomic_operations": {"type": "array", "items": {"type": "string"}},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}

# The model authors only prompt-specific semantics. Generic lifecycle details
# are added by _enrich_behavior_lifecycle, keeping constrained generation small.
COMPACT_BEHAVIOR_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "clause_coverage", "behaviors", "proposed_atomic_operations", "ambiguities", "assumptions"],
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "clause_coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_clause", "classification", "covered_by"],
                "additionalProperties": False,
                "properties": {
                    "source_clause": {"type": "string"},
                    "classification": {"type": "string", "enum": ["behavior", "constraint", "context"]},
                    "covered_by": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "behaviors": {
            "type": "array",
            "maxItems": 7,
            "items": {
                "type": "object",
                "required": [
                    "id", "title", "source_clauses", "trigger", "observations", "guards",
                    "outcomes", "animation_roles", "proof_scenarios", "operations",
                ],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "source_clauses": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
                    "trigger": {"type": "string"},
                    "observations": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
                    "guards": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
                    "outcomes": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
                    "animation_roles": {"type": "array", "maxItems": 2, "items": {"type": "string"}},
                    "proof_scenarios": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
                    "operations": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
                },
            },
        },
        "proposed_atomic_operations": {"type": "array", "items": {"type": "string"}},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}


def _select_behavior_reasoning_model(
    settings: dict[str, Any], installed: list[str], prompt: str = ""
) -> str:
    preferred = str(settings.get("behavior_reasoning_model") or "").replace("ollama:", "", 1).strip()
    if preferred and preferred in installed:
        return preferred
    requested = str(settings.get("router_local_plan") or settings.get("router_fast_llm_model") or settings.get("general_model") or "qwen3:4b-instruct")
    # Multi-behavior gameplay contracts need the planning model. A small fast
    # model is appropriate for one compact mechanic, but it routinely drops
    # guards, sibling behaviors, and failure clauses from compound requests.
    if len(_clauses(prompt)) >= 4 or len(str(prompt or "")) >= 700:
        medium = []
        for name in installed:
            if "embed" in name.lower():
                continue
            match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", name.lower())
            size = float(match.group(1)) if match else 1000.0
            if 6.0 <= size <= 9.0:
                medium.append(
                    (
                        abs(size - 7.0),
                        "qwen2.5-coder" not in name.lower(),
                        name,
                    )
                )
        if medium:
            return min(medium)[2]
        return requested
    if str(settings.get("llm_planning_mode") or "").lower() != "fast_first":
        return requested
    candidates = []
    for name in installed:
        if "embed" in name.lower():
            continue
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", name.lower())
        size = float(match.group(1)) if match else 1000.0
        if 2.5 <= size <= 4.0:
            candidates.append((abs(size - 3.0), "coder" not in name.lower(), name))
    return min(candidates, default=(0.0, False, requested))[2]


def _narrow_repair_target_has_shell(
    target: str, accepted_fields: dict[str, Any]
) -> bool:
    """Only patch a nested field when its accepted behavior slot still exists."""

    match = re.fullmatch(r"behaviors\[(\d+)\]\.([a-z_]+)", str(target or ""))
    if not match:
        return True
    behaviors = list(dict(accepted_fields or {}).get("behaviors") or [])
    index = int(match.group(1))
    return index < len(behaviors) and isinstance(behaviors[index], dict)


def _extract_narrow_repair_value(result: Any, target: str) -> Any:
    """Accept the declared envelope, exact path, or unambiguous leaf key."""

    if not isinstance(result, dict):
        return None
    if "value" in result:
        return result["value"]
    if target in result:
        return result[target]
    leaf_key = str(target or "").rsplit(".", 1)[-1]
    return result.get(leaf_key)


def _source_precondition_phrase(text: str) -> str:
    """Extract a prompt-authored condition without knowing the gameplay system."""

    match = re.search(r"\b(?:after|if|only if|unless|when|while)\b\s+(.+)", str(text or ""), re.I)
    if not match:
        return ""
    return re.split(r"[,;.]", match.group(1), maxsplit=1)[0].strip()


def _source_behavior_phrase(text: str) -> str:
    """Extract the requested action portion that precedes a conditional phrase."""

    head = re.split(
        r"\b(?:after|if|only if|unless|when|while)\b",
        str(text or ""),
        maxsplit=1,
        flags=re.I,
    )[0]
    if ":" in head:
        head = head.rsplit(":", 1)[-1]
    head = re.sub(
        r"^\s*(?:spacebar|space|[a-z0-9])\s+input\s+(?:is\s+pressed\s*)?",
        "",
        head,
        flags=re.I,
    )
    head = head.strip(" ,.;")
    performed = re.search(r"\bperforms?\b\s+(.+)", head, re.I)
    if performed:
        return f"moves using requested {performed.group(1).strip()}"
    preserved = re.search(r"\bpreserves?\b\s+(.+)", head, re.I)
    if preserved:
        return f"jumps using the baseline {preserved.group(1).strip()}"
    return head


def _source_movement_mechanic(text: str) -> str:
    match = re.search(
        r"\b(zip|launch|dodge|roll|vault|slide|climb|jump|traverse)\w*\b",
        str(text or ""),
        re.I,
    )
    return match.group(1).lower() if match else ""


def _is_animation_state_propagation(text: str) -> bool:
    source = str(text or "")
    return bool(
        re.search(r"\bstate\w*\b", source, re.I)
        and re.search(r"\b(?:anim(?:ation)?\s*blueprint|anim\s*instance|ABP_[A-Za-z0-9_]+)\b", source, re.I)
        and re.search(r"\b(?:every\s+(?:update|frame|tick)|each\s+(?:update|frame|tick))\b", source, re.I)
    )


def _source_anim_instance_name(text: str) -> str:
    match = re.search(r"\b(ABP_[A-Za-z0-9_]+)\b", str(text or ""), re.I)
    return match.group(1) if match else "target AnimInstance"


def _source_context_guard(text: str) -> str:
    """Derive a qualitative activation fact from source-authored context only."""

    source = str(text or "")
    if _is_animation_state_propagation(source):
        return f"{_source_anim_instance_name(source)} AnimInstance is valid"
    if re.search(r"\b(?:anim|animation|montage|pose|sequence|clip)\w*\b", source, re.I):
        requested_keys = sorted(_extract_input_keys(source))
        if requested_keys:
            return f"{requested_keys[0]} input activation is received"
    obstacle = re.search(
        r"\b((?:waist[- ]high\s+)?(?:obstacle|ledge|wall|surface|ceiling))\b",
        source,
        re.I,
    )
    if obstacle:
        return f"{obstacle.group(1).lower().replace(' ', '-')} is observed"
    mechanic = _source_movement_mechanic(source)
    return f"{mechanic} activation is available" if mechanic else "activation is available"


def _source_context_sensing_operation(text: str) -> str:
    """Name a reusable query from the contextual object supplied by the prompt."""

    match = re.search(r"\b(obstacle|ledge|wall|surface|ceiling|target)\b", str(text or ""), re.I)
    noun = match.group(1).lower() if match else "context"
    return f"collision.sweep_{noun}"


def _source_animation_role(text: str) -> str:
    """Derive an asset-purpose role from the requested presentation phrase."""

    source = str(text or "").lower()
    match = re.search(
        r"\b([a-z][a-z0-9_-]*)\s+(montage|animation|pose|sequence|clip)\b",
        source,
    )
    if match:
        return f"{match.group(1).replace('-', '_')}_{match.group(2)}"
    return "behavior_animation"


def _requested_global_proof_scenarios(prompt: str) -> list[str]:
    """Materialize explicitly requested QA categories as test obligations, not evidence claims."""

    source = str(prompt or "")
    templates = {
        "positive": "positive PIE proof: valid context reaches each observable outcome",
        "negative": "negative PIE proof: invalid context rejects activation and preserves baseline state",
        "boundary": "boundary PIE proof: authored limits pass at the boundary and reject outside it",
        "interruption": "interruption PIE proof: cancellation restores every owned runtime setting",
        "regression": "regression PIE proof: reserved inputs and baseline movement remain unchanged",
    }
    return [text for category, text in templates.items() if re.search(rf"\b{category}\b", source, re.I)]


def _link_sibling_animation_dependencies(behaviors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gate presentation-only siblings on the accepted gameplay activation they visualize."""

    rows = [dict(value or {}) for value in behaviors]
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_parent.setdefault(str(row.get("_parent_clause_id") or ""), []).append(row)
    for siblings in by_parent.values():
        gameplay = [
            row for row in siblings
            if not re.search(
                r"\b(?:anim|animation|montage|pose|sequence|clip)\w*\b",
                " ".join(str(value) for value in row.get("source_clauses") or []),
                re.I,
            )
        ]
        for row in siblings:
            if row in gameplay or not row.get("animation_roles") or not gameplay:
                continue
            role_terms = _semantic_words(" ".join(str(value) for value in row.get("animation_roles") or []))
            dependency = max(
                gameplay,
                key=lambda candidate: len(
                    role_terms.intersection(
                        _semantic_words(" ".join(str(value) for value in candidate.get("source_clauses") or []))
                    )
                ),
            )
            dependency_name = re.sub(
                r"[^a-z0-9]+", "_", str(dependency.get("title") or dependency.get("id") or "gameplay").lower()
            ).strip("_")
            event = f"{dependency_name} activation succeeds"
            row["depends_on"] = [str(dependency.get("id") or "")]
            row["trigger"] = event
            row["observations"] = [f"observed {event} event"]
            row["guards"] = [event]
            enriched = _enrich_behavior_lifecycle(row)
            row.clear()
            row.update(enriched)
    return rows


def _repair_atomic_operations(
    source_text: str,
    locked_operations: list[Any],
    proposed_operations: list[Any],
    error_text: str,
) -> list[str]:
    """Retain valid atomic list members and add only critic-required capabilities."""

    errors = str(error_text or "").lower()
    rejected = set()
    if "not grounded" in errors or "feature-level placeholders" in errors or "redundant movement effects" in errors:
        rejected.update(re.findall(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", errors))
    operations = []
    for value in list(locked_operations or []) + list(proposed_operations or []):
        operation = str(value or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", operation):
            continue
        if operation in rejected or operation.split(".", 1)[0] in {"perform", "player"}:
            continue
        operations.append(operation)

    animation_only_source = bool(
        re.search(
            r"\b(?:play|plays|playing|start|starts|trigger|triggers)\w*\b.{0,60}"
            r"\b(?:anim|animation|montage|pose|sequence|clip)\w*\b",
            source_text,
            re.I,
        )
    )
    if animation_only_source and any(marker in errors for marker in (
        "animation-only request",
        "feature-level placeholders",
        "required source behavior semantics",
        "missing",
    )):
        role_key = re.sub(
            r"[^a-z0-9_]+", "_", _source_animation_role(source_text).lower()
        ).strip("_")
        operations.append(f"animation.play_{role_key}")
    elif "target-directed travel" in errors:
        operations.extend(["collision.trace_forward", "movement.launch_toward_observed_hit"])
    elif _is_animation_state_propagation(source_text) and (
        "required source behavior semantics" in errors or "missing" in errors
    ):
        operations.extend([
            "state.read_owning_character_variables",
            "state.write_anim_instance_variables",
        ])
    elif any(marker in errors for marker in (
        "required source behavior semantics",
        "authoritative gameplay effect",
        "movement, physics, character, or transform namespace",
        "feature-level placeholders",
    )):
        mechanic = _source_movement_mechanic(source_text)
        if mechanic:
            operations.append(f"movement.apply_{mechanic}_impulse")
    if "hit-gated sensing operation" in errors:
        operations.append("collision.trace_forward")
    if "contextual sensing producer" in errors:
        operations.append(_source_context_sensing_operation(source_text))
    return list(dict.fromkeys(operations))


def _narrow_repair_needs_reasoning(target: str) -> bool:
    """Separate semantic field repair from inexpensive structural cleanup."""

    return str(target or "").rsplit(".", 1)[-1] in {
        "guards", "observations", "operations", "outcomes", "proof_scenarios",
    }


def _critic_error_targets_field(error: str, field: str) -> bool:
    text = str(error or "").lower()
    known = {
        "id", "title", "source_clauses", "trigger", "observations", "guards",
        "outcomes", "animation_roles", "proof_scenarios", "operations",
    }
    primary = re.search(r"behavior_\d+\s+(?:field\s+)?([a-z_]+)", text)
    if primary and primary.group(1) in known:
        return primary.group(1) == field
    if field == "observations" and "surface-relative movement omits a measured surface direction or normal" in text:
        return True
    if field == "outcomes" and (
        "surface-relative movement outcome" in text or "wall-jump outcome" in text
    ):
        return True
    if field == "trigger" and "input key" in text:
        return True
    return bool(re.search(rf"(?<![a-z0-9_]){re.escape(field)}(?![a-z0-9_])", text))


def load_behavior_primitives(path: str | Path | None = None) -> dict[str, Any]:
    payload = json.loads(Path(path or PRIMITIVE_PATH).read_text(encoding="utf-8"))
    if payload.get("schema") != "ai_studio.unreal_behavior_primitives.v1":
        raise ValueError(f"Unsupported behavior primitive schema: {payload.get('schema')}")
    return payload


def _clauses(prompt: str) -> list[str]:
    text = " ".join(str(prompt or "").split())
    parts = re.split(r"(?<=[.!?;])\s+|\s+(?:and then|then|also)\s+", text, flags=re.I)
    return [part.strip(" ,.;") for part in parts if part.strip(" ,.;")]


def _matches(primitive: dict[str, Any], lower: str) -> list[str]:
    hits = [str(marker) for marker in primitive.get("match_any") or [] if str(marker).lower() in lower]
    groups = [list(group) for group in primitive.get("match_concept_groups") or []]
    concept_hits = [
        next((str(marker) for marker in group if str(marker).lower() in lower), "")
        for group in groups
    ]
    if groups and all(concept_hits):
        hits.extend(value for value in concept_hits if value not in hits)
    return hits


def _normalized_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _semantic_words(text: str) -> set[str]:
    stop = {
        "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "into", "is",
        "it", "of", "on", "or", "the", "to", "when", "while", "with", "player", "requested",
    }
    words = []
    for word in _normalized_words(text) - stop:
        if len(word) <= 1:
            continue
        if len(word) > 4 and word.endswith("ing"):
            word = word[:-3]
        elif len(word) > 4 and word.endswith("ated"):
            word = word[:-1]
        elif len(word) > 3 and word.endswith("ed"):
            word = word[:-2]
        elif len(word) > 4 and re.search(r"[dsvz]es$", word):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s"):
            word = word[:-1]
        if len(word) > 3 and word.endswith("e") and word[-2] in {"d", "v"}:
            word = word[:-1]
        words.append(word)
    return set(words)


def _canonical_input_key(value: str) -> str:
    token = str(value or "").upper()
    return "SPACE" if token in {"SPACE", "SPACEBAR"} else token


def _extract_input_keys(text: str) -> set[str]:
    named = re.findall(r"(?<![A-Za-z0-9_])(?:spacebar|space)(?![A-Za-z0-9_])", str(text or ""), re.I)
    single = re.findall(r"(?<![A-Za-z0-9_])[A-Z0-9](?![A-Za-z0-9_])", str(text or ""))
    return {_canonical_input_key(value) for value in named + single}


def _atomic_behavior_obligations(
    clause_lookup: dict[str, str], fixed_clauses: dict[str, str]
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Split compound outcomes so every requested effect remains auditable."""

    rows: list[dict[str, str]] = []
    lookup: dict[str, str] = {}
    for clause_id, clause in clause_lookup.items():
        if clause_id in fixed_clauses:
            continue
        parts = [
            part.strip(" ,")
            for part in re.split(r"\s*(?:[,;]|\band\b)\s*", clause, flags=re.I)
            if part.strip(" ,")
        ]
        if len(parts) == 1:
            parts = [clause]
        # A key is shared only when it belongs to the leading action. A key in a
        # later alternative (for example "..., and Space wall-jump") must not
        # leak backward into climb/hang/exit obligations.
        trigger = next(iter(sorted(_extract_input_keys(parts[0]))), "")
        topic_match = re.match(r"^([A-Z][A-Za-z0-9_-]*ing)\b", parts[0])
        shared_topic = topic_match.group(1) if topic_match else ""
        for index, part in enumerate(parts, 1):
            part = re.sub(r"^or\s+", "", part, flags=re.I)
            obligation_id = clause_id if len(parts) == 1 else f"{clause_id}.{index}"
            text = part
            leading_key = re.match(r"^(SpaceBar|Space|[A-Z0-9])\b\s*(.*)$", part)
            if leading_key and " input " not in part.lower():
                key = _canonical_input_key(leading_key.group(1))
                action_text = leading_key.group(2).strip(" :")
                text = f"{key} input is pressed: {action_text}"
            elif index > 1 and trigger and _canonical_input_key(trigger) not in _extract_input_keys(part):
                text = f"{_canonical_input_key(trigger)} input is pressed: {part}"
            elif (
                index > 1
                and shared_topic
                and not _extract_input_keys(part)
                and not part.lower().startswith(shared_topic.lower())
            ):
                text = f"{shared_topic}: {part}"
            rows.append({"id": obligation_id, "text": text, "parent_id": clause_id})
            lookup[obligation_id] = text
    return rows, lookup


def _fixed_nonbehavior_classification(clause: str) -> str:
    """Classify explicit planning/integration policy without consuming behavior slots."""

    text = str(clause or "")
    lower = text.lower()
    mechanic_terms = re.search(
        r"\b(?:climb|grapple|vault|slide|dodge|roll|jump|hang|attack|puzzle|move|zip)\w*\b",
        lower,
    )
    if "/game/" in lower and not mechanic_terms:
        return "context"
    if re.search(
        r"\b(?:plan only|do not mutate|must not|reserve\w*|enhanced input|output pose|"
        r"compile|save|read ?back|verify|verification|regression|pie|known win|"
        r"reusable atomic|canned|implementation plan|approval|proof|test|before success|"
        r"positive|negative|interruption)\b",
        lower,
    ):
        return "constraint"
    if re.search(r"\b(?:update|connect|integrat\w*|propagat\w*)\b", lower) and re.search(
        r"\b(?:abp|anim blueprint|slot|asset|skeleton|graph)\b", lower
    ):
        return "constraint"
    if re.search(r"\b(?:contextual\w*|correct|appropriate)\b", lower) and re.search(
        r"\b(?:anim|animation|montage|pose|motion|clip)\w*\b", lower
    ):
        return "constraint"
    return ""


def _apply_global_animation_presentation(prompt: str, behaviors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a prompt-requested presentation role to each gameplay behavior."""

    if not (
        re.search(r"\b(?:anim|animation|montage|pose|motion|clip)\w*\b", str(prompt or ""), re.I)
        and re.search(r"\b(?:play|present|visual|contextual|correct|appropriate)\w*\b", str(prompt or ""), re.I)
    ):
        return [dict(value or {}) for value in behaviors]
    rows = []
    for value in behaviors:
        row = dict(value or {})
        if not row.get("animation_roles"):
            identity = re.sub(
                r"[^a-z0-9]+",
                "_",
                str(row.get("title") or " ".join(row.get("source_clauses") or []) or "behavior").lower(),
            ).strip("_")
            row["animation_roles"] = [f"{identity}_montage"]
        operations = list(row.get("operations") or [])
        if not any(str(operation).startswith("animation.") for operation in operations):
            operations.append("animation.play_contextual_montage")
        row["operations"] = list(dict.fromkeys(operations))
        rows.append(row)
    return rows


def _enrich_behavior_lifecycle(behavior: dict[str, Any]) -> dict[str, Any]:
    """Expand a concise semantic behavior into a generic recoverable lifecycle."""

    row = dict(behavior or {})
    def contract_text(value: Any) -> str:
        parsed = value
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                parsed = value
        if isinstance(parsed, dict):
            return " ".join(
                str(parsed.get(key) or "").replace("_", " ").strip()
                for key in ("subject", "predicate", "criterion", "description", "name")
                if parsed.get(key) not in (None, "")
            ).strip()
        return str(parsed)

    for field_name in (
        "animation_roles", "guards", "observations", "operations", "outcomes",
        "proof_scenarios", "source_clauses",
    ):
        if isinstance(row.get(field_name), list):
            row[field_name] = [contract_text(value) for value in row[field_name]]
    token = re.sub(r"[^A-Za-z0-9]+", " ", str(row.get("id") or "Behavior")).title().replace(" ", "")
    ready, active, recovery = f"{token}Ready", f"{token}Active", f"{token}Recovery"
    guards = [str(value) for value in row.get("guards") or [] if value]
    outcomes = [str(value) for value in row.get("outcomes") or [] if value]
    canonical_operations = []
    for value in row.get("operations") or []:
        parts = []
        for part in str(value or "").split("."):
            snake = re.sub(r"(?<!^)(?=[A-Z])", "_", part)
            snake = re.sub(r"[^A-Za-z0-9]+", "_", snake).strip("_").lower()
            if snake:
                parts.append(snake)
        if parts:
            if len(parts) == 1:
                parts.insert(0, "generated")
            canonical_operations.append(".".join(parts))
    row["operations"] = list(dict.fromkeys(canonical_operations))
    if not row.get("states"):
        row["states"] = [ready, active, recovery]
    if not row.get("transitions"):
        row["transitions"] = [
            {"from": ready, "event": str(row.get("trigger") or "trigger accepted"), "guards": guards, "to": active},
            {"from": active, "event": "requested outcome completes", "guards": [], "to": ready},
            {"from": active, "event": "cancel, interruption, or guard loss", "guards": [], "to": recovery},
            {"from": recovery, "event": "owned state cleanup completes", "guards": [], "to": ready},
        ]
    else:
        transitions = [dict(value or {}) for value in row.get("transitions") or []]
        activation = next(
            (
                value for value in transitions
                if value.get("from") == ready and value.get("to") == active
            ),
            None,
        )
        if activation is not None:
            activation["event"] = str(row.get("trigger") or "trigger accepted")
            activation["guards"] = list(guards)
        row["transitions"] = transitions
    if not row.get("cancellation"):
        row["cancellation"] = ["cancel or guard loss enters recovery"]
    if not row.get("failure_paths"):
        row["failure_paths"] = [
            "failed guards leave authoritative state unchanged",
            "interruption restores every owned setting",
        ]
    if not row.get("proof_scenarios"):
        source_text = " ".join(str(value) for value in row.get("source_clauses") or [])
        boundary = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(cm|m|ms|s|seconds?|degrees?|units?|%)?\b",
            source_text,
            re.I,
        )
        if boundary:
            limit = " ".join(value for value in boundary.groups() if value)
            positive_outcome = next(
                (
                    value for value in outcomes
                    if re.search(
                        r"\b(?:character|player|pawn|actor|system|state)\b.{0,60}\b(?:applies?|becomes?|"
                        r"changes?|enters?|exits?|launches?|moves?|reaches?|sets?|travels?|updates?|"
                        r"zips|zipped|zipping|dodges?|rolls?|vaults?|slides?|climbs?|jumps?)\b",
                        value,
                        re.I,
                    )
                ),
                next(
                    (
                        value for value in outcomes
                        if not re.search(r"\b(?:performed|executed|completed)\s*$", value, re.I)
                    ),
                    outcomes[0] if outcomes else "the observable state change occurs",
                ),
            )
            guard_summary = " and ".join(guards) if guards else "all guards pass"
            row["proof_scenarios"] = [
                f"at or within {limit}, when {guard_summary}, {positive_outcome}",
                f"above {limit} or when any guard fails, activation is rejected and baseline behavior is preserved",
            ]
        else:
            row["proof_scenarios"] = outcomes[:1] + [
                "invalid context rejects activation and preserves baseline behavior"
            ]
    if not row.get("animation_roles"):
        row["animation_roles"] = []
    return row


def validate_model_behavior_synthesis(prompt: str, synthesis: dict[str, Any]) -> dict[str, Any]:
    """Critique a model-authored behavior contract before it can affect a plan."""

    synthesis = dict(synthesis or {})
    clauses = list(synthesis.get("_coverage_obligations") or _clauses(prompt))
    coverage = [dict(row) for row in synthesis.get("clause_coverage") or [] if isinstance(row, dict)]
    behaviors = [dict(row) for row in synthesis.get("behaviors") or [] if isinstance(row, dict)]
    errors: list[str] = []
    requested_global_proofs = _requested_global_proof_scenarios(prompt)
    authored_global_proofs = " ".join(
        str(value) for value in synthesis.get("global_proof_scenarios") or []
    )
    for proof in requested_global_proofs:
        category = proof.split(" ", 1)[0]
        if not re.search(rf"\b{re.escape(category)}\b", authored_global_proofs, re.I):
            errors.append(f"global proof_scenarios omit requested {category} PIE proof")
    required_behavior_fields = (
        "id", "title", "source_clauses", "trigger", "observations", "guards", "states", "transitions",
        "outcomes", "failure_paths", "proof_scenarios", "operations",
    )
    known_primitive_keys = {
        str(row.get("key") or "") for row in load_behavior_primitives().get("primitives") or []
    }
    prompt_domain_words = _normalized_words(prompt) - {
        "build", "create", "make", "implement", "system", "feature", "where", "when", "while",
        "with", "from", "toward", "matching", "current", "user", "player", "unreal", "engine",
        "the", "and", "that", "this", "into", "only", "actual", "valid", "another",
    }
    animation_requested = bool(re.search(
        r"\b(?:anim|animation|montage|pose|motion|visual)\w*\b|\bABP_[A-Za-z0-9_]+\b",
        prompt,
        re.I,
    ))
    requested_keys = _extract_input_keys(prompt)
    for index, behavior in enumerate(behaviors):
        if not isinstance(behavior.get("trigger"), str):
            errors.append(f"behavior_{index + 1} field trigger must be a string")
        for field in (
            "source_clauses", "observations", "guards", "outcomes", "animation_roles",
            "proof_scenarios", "operations",
        ):
            value = behavior.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                errors.append(f"behavior_{index + 1} field {field} must be an array of strings")
        missing = [field for field in required_behavior_fields if not behavior.get(field)]
        if missing:
            errors.append(f"behavior_{index + 1} missing: {', '.join(missing)}")
        states = {str(value) for value in behavior.get("states") or []}
        for transition_index, transition in enumerate(behavior.get("transitions") or []):
            transition = dict(transition or {})
            if transition.get("from") not in states or transition.get("to") not in states:
                errors.append(f"behavior_{index + 1} transition_{transition_index + 1} references an undeclared state")
        transition_events = " ".join(
            str(dict(value or {}).get("event") or "")
            for value in behavior.get("transitions") or []
        )
        trigger_keys_for_transition = _extract_input_keys(str(behavior.get("trigger") or ""))
        if trigger_keys_for_transition and not trigger_keys_for_transition.intersection(
            _extract_input_keys(transition_events)
        ):
            errors.append(
                f"behavior_{index + 1} transitions do not activate from the repaired trigger"
            )
        operations = [str(value) for value in behavior.get("operations") or []]
        invalid_primitive_operations = sorted(set(operations).intersection(known_primitive_keys))
        if invalid_primitive_operations:
            errors.append(
                f"behavior_{index + 1} uses behavior primitive keys as operations: "
                + ", ".join(invalid_primitive_operations)
            )
        malformed_operations = [
            value for value in operations
            if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", value)
        ]
        if malformed_operations:
            errors.append(
                f"behavior_{index + 1} operations are not namespaced atomic keys: "
                + ", ".join(malformed_operations)
            )
        generic_operation_namespaces = [
            value for value in operations
            if value.split(".", 1)[0] in {"do", "execute", "generated", "perform", "run"}
        ]
        if generic_operation_namespaces:
            errors.append(
                f"behavior_{index + 1} operations use generic namespaces: "
                + ", ".join(generic_operation_namespaces)
            )
        generic_operation_actions = [
            value for value in operations
            if value.split(".")[-1].startswith(("do_", "execute_", "perform_", "run_"))
        ]
        if generic_operation_actions:
            errors.append(
                f"behavior_{index + 1} operations use high-level placeholder actions: "
                + ", ".join(generic_operation_actions)
            )
        bare_mechanic_operations = [
            value for value in operations
            if value.split(".")[-1] in {
                "climb", "dodge", "grapple", "roll", "slide", "traverse", "vault", "zip"
            }
        ]
        if bare_mechanic_operations:
            errors.append(
                f"behavior_{index + 1} operations are feature-level placeholders rather than reusable effects: "
                + ", ".join(bare_mechanic_operations)
            )
        if behavior.get("animation_roles") and not animation_requested:
            errors.append(f"behavior_{index + 1} invented animation roles not requested by the user")
        animation_operations = [
            value for value in operations if value.split(".", 1)[0] == "animation"
        ]
        if animation_operations and not animation_requested:
            errors.append(
                f"behavior_{index + 1} operations invented unrequested animation work: "
                + ", ".join(animation_operations)
            )
        source_text = " ".join(str(value) for value in behavior.get("source_clauses") or [])
        behavior_animation_requested = bool(
            re.search(
                r"\b(?:anim|animation|montage|pose|motion|visual)\w*\b",
                " ".join(str(value) for value in behavior.get("source_clauses") or []),
                re.I,
            )
        )
        animation_only_requested = behavior_animation_requested and bool(
            re.search(
                r"\b(?:play|plays|playing|start|starts|trigger|triggers)\w*\b.{0,60}"
                r"\b(?:anim|animation|montage|pose|sequence|clip)\w*\b",
                source_text,
                re.I,
            )
        )
        if behavior_animation_requested and not behavior.get("animation_roles"):
            errors.append(f"behavior_{index + 1} omits required animation roles")
        if behavior_animation_requested:
            invalid_animation_roles = [
                str(value) for value in behavior.get("animation_roles") or []
                if not _normalized_words(str(value)).intersection(
                    {"anim", "animation", "montage", "pose", "motion", "sequence", "clip"}
                )
            ]
            if invalid_animation_roles:
                errors.append(
                    f"behavior_{index + 1} animation_roles are actors rather than animation asset roles: "
                    + ", ".join(invalid_animation_roles)
                )
            role_identity_terms = _semantic_words(source_text) - {
                "active", "anim", "animation", "clip", "montage", "motion", "play", "pose",
                "sequence", "start", "trigger",
            }
            if role_identity_terms and any(
                not role_identity_terms.intersection(_semantic_words(str(value)))
                for value in behavior.get("animation_roles") or []
            ):
                errors.append(
                    f"behavior_{index + 1} animation_roles do not identify the source behavior"
                )
        guard_terms = _semantic_words(" ".join(str(value) for value in behavior.get("guards") or []))
        observation_terms = _semantic_words(
            " ".join(str(value) for value in behavior.get("observations") or [])
        )
        source_terms = _semantic_words(" ".join(str(value) for value in behavior.get("source_clauses") or []))
        conditional_match = re.search(
            r"\b(?:after|if|only if|unless|when|while)\b\s+(.+)", source_text, re.I
        )
        conditional_terms = _semantic_words(conditional_match.group(1)) if conditional_match else set()
        if conditional_terms and not conditional_terms.intersection(observation_terms):
            errors.append(
                f"behavior_{index + 1} observations omit source-clause precondition facts"
            )
        source_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", source_text))
        source_distance = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(cm|m|units?)\b", source_text, re.I
        )
        if source_distance and not re.search(
            r"\b(?:distance|range)\b",
            " ".join(str(value) for value in behavior.get("observations") or []),
            re.I,
        ):
            errors.append(
                f"behavior_{index + 1} observations omit the requested distance measurement"
            )
        if source_distance and not any(
            source_distance.group(1) in str(value)
            and re.search(r"(?:<=|<|\bwithin\b|\bat most\b|\bno more than\b)", str(value), re.I)
            for value in behavior.get("guards") or []
        ):
            errors.append(
                f"behavior_{index + 1} guards omit the requested distance limit"
            )
        for numeric_field in ("trigger", "observations", "guards", "outcomes", "proof_scenarios", "operations"):
            field_value = behavior.get(numeric_field)
            field_text = " ".join(
                str(value)
                for value in (field_value if isinstance(field_value, list) else [field_value])
                if value is not None
            )
            invented_numbers = sorted(
                set(re.findall(r"\b\d+(?:\.\d+)?\b", field_text)) - source_numbers
            )
            if invented_numbers:
                errors.append(
                    f"behavior_{index + 1} field {numeric_field} invented numeric constants absent from the source: "
                    + ", ".join(invented_numbers)
                )
        feature_level_operations = [
            value for value in operations
            if (
                len(source_terms.intersection(_semantic_words(value.split(".")[-1]))) >= 2
                or (
                    len(_normalized_words(value.split(".")[-1])) >= 2
                    and bool(source_terms.intersection(_semantic_words(value.split(".")[-1])))
                )
            )
            and not re.search(
                r"^(?:add|apply|clear|disable|enable|launch|move|play|read|remove|resolve|restore|schedule|set|start|stop|sweep|trace|update|write)_",
                value.split(".")[-1],
            )
        ]
        if feature_level_operations:
            errors.append(
                f"behavior_{index + 1} operations are feature-level placeholders rather than reusable effects: "
                + ", ".join(feature_level_operations)
            )
        required_guard_terms = conditional_terms or source_terms
        if required_guard_terms and not required_guard_terms.intersection(guard_terms):
            errors.append(f"behavior_{index + 1} guards do not enforce a source-clause precondition")
        if not re.search(r"\bthreshold\w*\b", source_text.replace("_", " "), re.I) and any(
            re.search(r"\bthreshold\w*\b", str(value).replace("_", " "), re.I)
            for value in behavior.get("guards") or []
        ):
            errors.append(
                f"behavior_{index + 1} guards invent an unsupported symbolic tuning threshold"
            )
        if not re.search(r"\b(?:speed|velocity|momentum|moving|falling|sprinting)\w*\b", source_text, re.I) and any(
            re.search(r"\b(?:speed|velocity|momentum)\w*\b", str(value), re.I)
            for value in behavior.get("guards") or []
        ):
            errors.append(
                f"behavior_{index + 1} guards add an unsupported kinematic precondition"
            )
        generic_grounding_terms = {
            "active", "character", "current", "input", "measur", "player", "state", "valid",
        }
        meaningful_observation_terms = observation_terms - generic_grounding_terms
        ungrounded_guards = []
        for value in behavior.get("guards") or []:
            meaningful_guard_terms = _semantic_words(str(value)) - generic_grounding_terms
            if meaningful_guard_terms and not meaningful_guard_terms.intersection(
                meaningful_observation_terms
            ):
                ungrounded_guards.append(str(value))
        if ungrounded_guards:
            errors.append(
                f"behavior_{index + 1} observations do not provide the runtime facts used by guards"
            )
        for kinematic_term in ("momentum", "speed", "velocity"):
            if any(
                re.search(rf"\b{kinematic_term}\w*\b", str(value), re.I)
                for value in behavior.get("guards") or []
            ) and not any(
                re.search(rf"\b{kinematic_term}\w*\b", str(value), re.I)
                for value in behavior.get("observations") or []
            ):
                errors.append(
                    f"behavior_{index + 1} observations do not provide guarded {kinematic_term} data"
                )
        executable_guards = [
            value for value in behavior.get("guards") or []
            if len(_semantic_words(str(value))) >= 3
            and re.search(
                r"\b(?:is|has|within|less than|more than|valid|detected|blocked|present|exists?|"
                r"absent|active|available|grounded|received|sprinting|climbing|succeeds?)\b",
                str(value),
                re.I,
            )
        ]
        if not executable_guards:
            errors.append(
                f"behavior_{index + 1} guards are labels rather than executable predicates"
            )
        for guard in behavior.get("guards") or []:
            if re.search(r"\b\d+(?:\.\d+)?\b", str(guard)) and not re.search(
                r"(?:<=|>=|<|>|\bwithin\b|\bat most\b|\bat least\b|\bno (?:more|less) than\b)",
                str(guard),
                re.I,
            ):
                errors.append(
                    f"behavior_{index + 1} guards with numeric limits need an executable comparator"
                )
                break
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:cm|m|units?)\b", source_text, re.I) and not re.search(
            r"\b(?:at least|minimum|min|greater than|more than|>=|>)\b", source_text, re.I
        ) and any(
            re.search(r"\b(?:at least|minimum|greater than|more than)\b|>=|>", str(guard), re.I)
            for guard in behavior.get("guards") or []
        ):
            errors.append(
                f"behavior_{index + 1} guards invert an unspecified distance limit; use within or at most"
            )
        operation_terms = _semantic_words(" ".join(operations))
        non_effect_namespaces = {
            "animation", "audio", "camera", "collision", "debug", "perception", "query",
            "sensing", "state", "trace", "ui", "vfx",
        }
        sensing_namespaces = {"collision", "perception", "query", "sensing", "trace"}
        sensing_generic_terms = {"check", "detect", "forward", "query", "sample", "sweep", "trace"}
        ungrounded_sensing = []
        sensing_ground = source_terms.union(observation_terms)
        for value in operations:
            if value.split(".", 1)[0] not in sensing_namespaces:
                continue
            action_terms = _semantic_words(value.split(".", 1)[-1]) - sensing_generic_terms
            hit_gated_trace = "hit" in source_terms and re.search(r"(?:trace|sweep|query)", value, re.I)
            if not hit_gated_trace and not action_terms.intersection(sensing_ground):
                ungrounded_sensing.append(value)
        if ungrounded_sensing:
            errors.append(
                f"behavior_{index + 1} operations include sensing not grounded by source or observations: "
                + ", ".join(ungrounded_sensing)
            )
        generic_effect_terms = {
            "active", "apply", "character", "current", "effect", "input", "measur",
            "move", "movement", "player", "set", "start", "state", "stop", "update",
        }
        grounded_effect_terms = source_terms.union(observation_terms) - generic_effect_terms
        ungrounded_operations = []
        for value in operations:
            if value.split(".", 1)[0] in non_effect_namespaces:
                continue
            action_terms = _semantic_words(value.split(".", 1)[-1]) - generic_effect_terms
            if action_terms and not action_terms.intersection(grounded_effect_terms):
                ungrounded_operations.append(value)
        if ungrounded_operations:
            errors.append(
                f"behavior_{index + 1} operations introduce effects not grounded by source or observations: "
                + ", ".join(ungrounded_operations)
            )
        effect_terms = source_terms.union(observation_terms).union(
            _semantic_words(" ".join(str(value) for value in behavior.get("outcomes") or []))
        )
        # One retained mechanic term is enough when the operation is already a
        # concrete namespaced effect (for example movement.apply_slide_impulse).
        # Requiring two terms rejects useful atomic operations and encourages
        # feature-level names that merely restate the whole requested system.
        required_operation_overlap = 1
        if effect_terms and len(effect_terms.intersection(operation_terms)) < required_operation_overlap:
            errors.append(
                f"behavior_{index + 1} operations omit required source behavior semantics"
            )
        authoritative_state_write = _is_animation_state_propagation(source_text) and any(
            re.search(r"^state\.(?:write|set|update)_", value)
            for value in operations
        )
        if operations and not animation_only_requested and not authoritative_state_write and not any(
            value.split(".", 1)[0] not in non_effect_namespaces for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} operations omit an authoritative gameplay effect"
            )
        contextual_query_requested = bool(
            re.search(r"\b(?:obstacle|ledge|wall|surface|ceiling)\b", source_text, re.I)
            and (
                re.search(r"\b(?:observe|measure|detect|find|trace|sweep|query)\w*\b", source_text, re.I)
                or re.search(
                    r"\b(?:observed|measured|detected)\b",
                    " ".join(str(value) for value in behavior.get("observations") or []),
                    re.I,
                )
            )
        )
        if contextual_query_requested and not any(
            value.split(".", 1)[0] in {"collision", "perception", "query", "sensing", "trace"}
            for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} operations omit a contextual sensing producer"
            )
        if animation_only_requested:
            invalid_presentation_operations = [
                value for value in operations
                if value.split(".", 1)[0] not in {"animation", "state"}
            ]
            if invalid_presentation_operations:
                errors.append(
                    f"behavior_{index + 1} animation-only request invented gameplay operations: "
                    + ", ".join(invalid_presentation_operations)
                )
            if not any(value.split(".", 1)[0] == "animation" for value in operations):
                errors.append(f"behavior_{index + 1} animation-only request omits an animation operation")
            if any(
                not re.search(r"\b(?:anim|animation|montage|pose|sequence|clip)\w*\b", str(value), re.I)
                for value in behavior.get("outcomes") or []
            ):
                errors.append(
                    f"behavior_{index + 1} animation-only outcomes invent non-animation gameplay effects"
                )
            proof_text = " ".join(
                str(value) for value in behavior.get("proof_scenarios") or []
            )
            if not re.search(r"\b(?:anim|animation|montage|pose|sequence|clip)\w*\b", proof_text, re.I):
                errors.append(
                    f"behavior_{index + 1} proof_scenarios omit contextual animation playback proof"
                )
        if not animation_only_requested and re.search(
            r"\b(?:zip|launch|move|movement|dodge|roll|vault|slide|climb|jump|traverse)\w*\b",
            source_text,
            re.I,
        ) and not any(
            value.split(".", 1)[0] in {"character", "movement", "physics", "transform"}
            and not re.search(
                r"^(?:check|detect|measure|query|sample|sweep|trace)(?:_|$)",
                value.split(".")[-1],
            )
            for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} operations must include a reusable effect in the movement, physics, "
                "character, or transform namespace"
            )
        outcomes = [str(value) for value in behavior.get("outcomes") or []]
        ungrounded_outcomes = [
            value for value in outcomes
            if (_semantic_words(value) - generic_effect_terms)
            and not (_semantic_words(value) - generic_effect_terms).intersection(grounded_effect_terms)
        ]
        if ungrounded_outcomes:
            errors.append(
                f"behavior_{index + 1} outcomes introduce effects not grounded by source or observations: "
                + "; ".join(ungrounded_outcomes)
            )
        tautological_outcomes = [
            value for value in outcomes
            if re.search(r"\b(?:performed|executed|completed)\s*$", value, re.I)
            or re.search(r"\bperforms?\b.{0,50}\b(?:behavior|dodge|grapple|jump|roll|slide|vault)\b", value, re.I)
        ]
        if not animation_only_requested and outcomes and (len(tautological_outcomes) == len(outcomes) or not any(
            re.search(
                r"\b(?:accelerates?|applies?|becomes?|changes?|disables?|enables?|enters?|exits?|falls?|launches?|"
                r"moves?|points?|reaches?|restores?|rotates?|sets?|transitions?|travels?|updates?|zips|zipped|zipping|dodges?|"
                r"rolls?|vaults?|slides?|climbs?|jumps?)\b",
                value,
                re.I,
            )
            for value in outcomes
        )):
            errors.append(
                f"behavior_{index + 1} outcomes do not describe an observable state or movement change"
            )
        movement_requested = not animation_only_requested and bool(
            re.search(
                r"\b(?:zip|launch|move|movement|dodge|roll|vault|slide|climb|jump|traverse)\w*\b",
                source_text,
                re.I,
            )
        )
        directional_movement_requested = movement_requested and bool(
            re.search(r"\bdirectional\b", source_text, re.I)
        )
        if directional_movement_requested and not re.search(
            r"\b(?:direction|vector)\b",
            " ".join(str(value) for value in behavior.get("observations") or []),
            re.I,
        ):
            errors.append(
                f"behavior_{index + 1} observations omit the requested directional movement basis"
            )
        if directional_movement_requested and not any(
            re.search(r"(?:direction|vector)", value, re.I)
            and value.split(".", 1)[0] in {"character", "movement", "physics", "transform"}
            for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} operations omit the requested directional movement basis"
            )
        if directional_movement_requested and not any(
            re.search(r"\b(?:direction|vector)\b", value, re.I) for value in outcomes
        ):
            errors.append(
                f"behavior_{index + 1} outcomes omit the requested directional movement basis"
            )
        invulnerability_requested = bool(re.search(r"\binvulnerab\w*\b", source_text, re.I))
        if invulnerability_requested and any(
            re.search(r"\binvulnerab\w*\b", str(value), re.I)
            for value in behavior.get("guards") or []
        ):
            errors.append(
                f"behavior_{index + 1} guards contain a circular invulnerability precondition"
            )
        if not re.search(r"\bhit\w*\b", source_text, re.I) and any(
            re.search(r"\bhit\w*\b", str(value), re.I)
            for value in behavior.get("guards") or []
        ):
            errors.append(
                f"behavior_{index + 1} guards add an unsupported hit precondition"
            )
        if invulnerability_requested and not any(
            re.search(r"invulnerab", value, re.I) for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} operations omit the bounded invulnerability implementation"
            )
        if invulnerability_requested and not any(
            re.search(r"\binvulnerab\w*\b.{0,50}\b(?:bounded|only|window)\b|"
                      r"\b(?:bounded|only|window)\b.{0,50}\binvulnerab\w*\b", value, re.I)
            for value in outcomes
        ):
            errors.append(
                f"behavior_{index + 1} outcomes omit the bounded invulnerability implementation"
            )
        surface_relative_movement = movement_requested and bool(
            re.search(r"\b(?:wall|surface|slope|ledge|ceiling)\w*\b", source_text, re.I)
        )
        if surface_relative_movement and not re.search(
            r"\b(?:normal|direction|orientation)\w*\b",
            " ".join(str(value) for value in behavior.get("observations") or []),
            re.I,
        ):
            errors.append(
                f"behavior_{index + 1} surface-relative movement omits a measured surface direction or normal"
            )
        if surface_relative_movement and not any(
            value.split(".", 1)[0] in {"character", "movement", "physics", "transform"}
            and not re.search(r"^(?:check|detect|measure|query|sample|sweep|trace)(?:_|$)", value.split(".")[-1])
            and re.search(r"(?:direction|normal|away|toward|vector)", value, re.I)
            for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} surface-relative movement operations omit a directional basis"
            )
        if re.search(r"\bwall\w*\b", source_text, re.I) and any(
            re.search(r"\b(?:wall|surface) normal is vertical\b", str(value), re.I)
            for value in behavior.get("guards") or []
        ):
            errors.append(
                f"behavior_{index + 1} guards confuse a vertical wall with a vertical surface normal"
            )
        if surface_relative_movement and not re.search(
            r"\b(?:away|normal|direction|surface|wall)\w*\b",
            " ".join(outcomes),
            re.I,
        ):
            errors.append(
                f"behavior_{index + 1} surface-relative movement outcome omits the measured surface basis"
            )
        if re.search(r"\bwall[- ]?jump\w*\b", source_text, re.I) and not re.search(
            r"\baway\b.{0,40}\b(?:surface|wall|normal)\b|\b(?:surface|wall|normal)\b.{0,40}\baway\b",
            " ".join(outcomes),
            re.I,
        ):
            errors.append(
                f"behavior_{index + 1} wall-jump outcome does not move the character away from the measured wall"
            )
        if movement_requested and not any(
            re.search(
                r"\b(?:character|player|pawn|actor)\b.{0,60}\b(?:launches?|moves?|travels?|"
                r"zips|zipped|zipping|dodges?|rolls?|vaults?|slides?|climbs?|jumps?)\b",
                value,
                re.I,
            )
            for value in outcomes
        ):
            errors.append(
                f"behavior_{index + 1} outcomes omit the requested actor movement effect"
            )
        target_directed_hit_travel = bool(
            re.search(r"\b(?:grapple|zip)\w*\b", source_text, re.I)
            and re.search(r"\bhit\w*\b", source_text, re.I)
        )
        if target_directed_hit_travel and not any(
            re.search(r"(?:toward|target|hit|point|destination)", value, re.I)
            and value.split(".", 1)[0] in {"character", "movement", "physics", "transform"}
            for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} operations omit target-directed travel toward the measured hit"
            )
        if target_directed_hit_travel and not any(
            re.search(r"\btoward\b.{0,50}\b(?:hit|point|target|destination)\b", value, re.I)
            for value in outcomes
        ):
            errors.append(
                f"behavior_{index + 1} outcomes omit target-directed travel toward the measured hit"
            )
        redundant_movement_effects: list[str] = []
        if target_directed_hit_travel and any("toward" in value for value in operations):
            redundant_movement_effects.extend(
                value for value in operations
                if re.search(r"\.(?:apply_)?(?:grapple|zip)(?:_|$)", value, re.I)
                and "toward" not in value
            )
        if directional_movement_requested and re.search(r"\bdodge\w*\b", source_text, re.I) and any(
            re.search(r"direction", value, re.I) for value in operations
        ):
            redundant_movement_effects.extend(
                value for value in operations
                if re.search(r"movement\.apply_dodge_impulse", value, re.I)
            )
        if re.search(r"\bwall[- ]?jump\w*\b", source_text, re.I) and any(
            "wall_jump_vertical" in value for value in operations
        ):
            redundant_movement_effects.extend(
                value for value in operations if re.search(r"movement\.apply_jump_impulse", value, re.I)
            )
        if redundant_movement_effects:
            errors.append(
                f"behavior_{index + 1} operations contain redundant movement effects for one outcome: "
                + ", ".join(dict.fromkeys(redundant_movement_effects))
            )
        if re.search(r"\bhit[- ]?gated\b", source_text, re.I) and not any(
            value.split(".", 1)[0] in {"collision", "perception", "query", "sensing", "trace"}
            for value in operations
        ):
            errors.append(
                f"behavior_{index + 1} operations omit a hit-gated sensing operation"
            )
        if re.search(r"\b\d+(?:\.\d+)?\b", source_text):
            proof_text = " ".join(str(value) for value in behavior.get("proof_scenarios") or [])
            if not re.search(r"\b(?:within|below|above|at|limit|boundary|outside|inside|<=|>=|<|>)\b", proof_text, re.I):
                errors.append(
                    f"behavior_{index + 1} proof_scenarios omit numeric boundary coverage"
                )
        proof_terms = _semantic_words(
            " ".join(str(value) for value in behavior.get("proof_scenarios") or [])
        )
        outcome_terms = _semantic_words(" ".join(outcomes))
        if outcome_terms and not outcome_terms.intersection(proof_terms):
            errors.append(
                f"behavior_{index + 1} proof_scenarios do not assert the observable outcome"
            )
        if movement_requested and not re.search(
            r"\b(?:character|player|pawn|actor)\b.{0,80}\b(?:launches?|moves?|travels?|zips|zipped|"
            r"zipping|dodges?|rolls?|vaults?|slides?|climbs?|jumps?)\b",
            " ".join(str(value) for value in behavior.get("proof_scenarios") or []),
            re.I,
        ):
            errors.append(
                f"behavior_{index + 1} proof_scenarios omit the requested actor movement assertion"
            )
        negative_proofs = [
            str(value) for value in behavior.get("proof_scenarios") or []
            if re.search(
                r"\b(?:does not|fails?|invalid|no change|not |outside|preserves?|rejects?|remains unchanged|without)\b",
                str(value),
                re.I,
            )
        ]
        if conditional_terms and not any(
            conditional_terms.intersection(_semantic_words(value))
            for value in negative_proofs
        ):
            errors.append(
                f"behavior_{index + 1} proof_scenarios omit a negative proof for the requested precondition"
            )
        trigger_keys = {
            value.upper()
            for value in re.findall(
                r"(?i:press(?:es|ed)?|key)\s*['\"]?((?i:SpaceBar|Space)|[A-Z0-9])(?:['\"]|\b)",
                str(behavior.get("trigger") or ""),
            )
        }
        invented_keys = sorted(trigger_keys - requested_keys)
        if invented_keys:
            errors.append(
                f"behavior_{index + 1} invented input keys not present in the request: "
                + ", ".join(invented_keys)
            )
        source_keys = _extract_input_keys(
            " ".join(str(value) for value in behavior.get("source_clauses") or [])
        ).intersection(requested_keys)
        trigger_tokens = _extract_input_keys(str(behavior.get("trigger") or ""))
        missing_trigger_keys = sorted(
            value for value in source_keys
            if value not in trigger_tokens and not behavior.get("depends_on")
        )
        if missing_trigger_keys:
            errors.append(
                f"behavior_{index + 1} trigger omits requested input keys: "
                + ", ".join(missing_trigger_keys)
            )
        trigger_text = str(behavior.get("trigger") or "")
        trigger_has_event = bool(re.search(
            r"\b(?:press(?:ed|es)?|activat(?:ed|es)?|activation|trigger(?:ed|s)?|succeeds?)\b",
            trigger_text,
            re.I,
        ))
        trigger_is_only_context = bool(
            re.search(r"\bcontext\b", trigger_text, re.I)
            and not re.search(
                r"\b(?:press(?:ed|es)?|activat(?:ed|es)?|trigger(?:ed|s)?)\b",
                trigger_text,
                re.I,
            )
        )
        if source_keys and not behavior.get("depends_on") and (not trigger_has_event or trigger_is_only_context):
            errors.append(
                f"behavior_{index + 1} trigger does not describe an input activation event"
            )
        if source_keys and re.search(r"\b(?:after|if|unless|when|while)\b", trigger_text, re.I):
            errors.append(
                f"behavior_{index + 1} trigger embeds a source precondition instead of leaving it in guards"
            )
        key_actor_outcomes = [
            value for value in outcomes
            if re.search(r"\binput\b", value, re.I)
            and any(re.search(rf"\b{re.escape(key)}\b", value, re.I) for key in source_keys)
        ]
        if key_actor_outcomes:
            errors.append(
                f"behavior_{index + 1} outcomes treat an input key as the gameplay actor"
            )
    uncovered = []
    for index, row in enumerate(coverage):
        if str(row.get("classification") or "") not in {"behavior", "constraint", "context"}:
            errors.append(f"coverage_{index + 1} has an invalid classification")
        if not isinstance(row.get("covered_by"), list):
            errors.append(f"coverage_{index + 1} covered_by must be an array")
        elif str(row.get("classification") or "") == "behavior":
            behavior_ids = {str(value.get("id") or "") for value in behaviors}
            unknown_ids = sorted(
                str(value) for value in row.get("covered_by") or []
                if str(value) not in behavior_ids
            )
            if unknown_ids:
                errors.append(
                    f"coverage_{index + 1} covered_by references unknown behavior IDs: "
                    + ", ".join(unknown_ids)
                )
    for clause in clauses:
        clause_words = _normalized_words(clause)
        matching = []
        for row in coverage:
            source_words = _normalized_words(row.get("source_clause") or "")
            overlap = len(clause_words.intersection(source_words)) / max(1, len(clause_words))
            classification = str(row.get("classification") or "")
            covered = bool(row.get("covered_by")) or classification in {"constraint", "context"}
            if overlap >= 0.55 and classification and covered:
                matching.append(row)
        if not matching:
            uncovered.append(clause)
            continue
        covered_ids = {
            str(value)
            for row in matching
            for value in row.get("covered_by") or []
            if value
        }
        if not any(str(row.get("classification") or "") == "behavior" for row in matching):
            continue
        assigned = [row for row in behaviors if str(row.get("id") or "") in covered_ids]
        assigned_text = " ".join(
            " ".join(
                [str(row.get("title") or ""), str(row.get("trigger") or "")]
                + [str(value) for field in ("observations", "guards", "outcomes", "operations", "animation_roles") for value in row.get(field) or []]
            )
            for row in assigned
        )
        clause_terms = _semantic_words(clause)
        if clause_terms:
            overlap = len(clause_terms.intersection(_semantic_words(assigned_text))) / len(clause_terms)
            if overlap < 0.4:
                errors.append(f"Covered behavior does not semantically satisfy obligation: {clause}")
    if not behaviors:
        errors.append("No behavior contracts were produced.")
    if uncovered:
        errors.append("Prompt clause coverage is incomplete.")
    return {
        "ok": not errors,
        "errors": errors,
        "uncovered_clauses": uncovered,
        "behavior_count": len(behaviors),
        "coverage_count": len(coverage),
        "mutation_allowed": False,
    }


def synthesize_novel_behavior_contract(
    prompt: str,
    *,
    project_context: dict[str, Any] | None = None,
    model_query: Callable[[str, str], str | None] | None = None,
    stage_trace: Any | None = None,
) -> dict[str, Any]:
    """Ask the configured reasoning model to understand a novel mechanic as behavior."""

    from tech_connector.services.adaptive.behavior_convergence import (
        AdaptiveBehaviorConvergence,
    )
    from tech_connector.services.adaptive.behavior_stage_trace import BehaviorStageTrace

    trace = stage_trace or BehaviorStageTrace(prompt)

    system = """You are the behavior architect for an Unreal Engine feature generator.
Understand the user's requested experience; do not choose a canned named system and do not claim implementation success.
Return one JSON object with: summary, clause_coverage, behaviors, proposed_atomic_operations, ambiguities, assumptions.
Behavior clauses have compact IDs. clause_coverage must contain every behavior-clause ID as source_clause,
classification=behavior, and covered_by behavior IDs. Binding constraints are applied locally and must shape the result
without becoming behaviors. Use behavior-clause IDs in each behavior's source_clauses too.
Each behavior must contain id, title, source_clauses, trigger, observations, guards, outcomes,
animation_roles, proof_scenarios, and operations. Generic lifecycle states, transitions, cancellation, and recovery are added locally.
Operations are atomic semantic actions such as physics.apply_directional_gravity. Do not put behavior primitive keys in operations.
Operation keys must be lowercase namespace.action snake_case identifiers. Every behavior needs at least one concrete guard.
Reuse a provided callable operation only when its description directly performs the requested behavior; otherwise propose a precise new operation key.
Animation roles must be empty unless the prompt explicitly requests animation, pose, montage, motion, or visual presentation.
Never invent an input key. Model each context-sensitive outcome separately when it has distinct guards or gameplay effects.
Animation role names must identify the behavior, such as grapple_zip_montage, rather than generic names like Montage.
Use 1-7 behaviors. Keep each list minimal: at most 2 observations, 2 guards, 2 outcomes,
2 animation roles, 2 proof scenarios, and 3 operations. Keep every string under 100 characters.
Do not invent asset existence, API support, runtime results, or source authority. Unknowns belong in ambiguities. Output JSON only."""
    clauses = _clauses(prompt)
    clause_lookup = {f"C{index}": clause for index, clause in enumerate(clauses, 1)}
    fixed_clauses = {
        key: classification
        for key, clause in clause_lookup.items()
        if (classification := _fixed_nonbehavior_classification(clause))
    }
    behavior_obligations, obligation_lookup = _atomic_behavior_obligations(
        clause_lookup, fixed_clauses
    )

    def resolve_clause_reference(value: Any) -> str:
        """
        Resolve a model clause ID or punctuation variant to canonical source text.
        :param value: clause ID or source text returned by the model
        :return: canonical obligation text when available
        """
        raw = str(value or "")
        direct = obligation_lookup.get(raw, clause_lookup.get(raw))
        if direct:
            return str(direct)
        normalized = _normalized_words(raw)
        for candidate in [*obligation_lookup.values(), *clause_lookup.values()]:
            if normalized and normalized == _normalized_words(candidate):
                return str(candidate)
        return raw
    packet = {
        "behavior_clauses": behavior_obligations,
        "binding_context_and_constraints": [
            {"id": key, "text": clause_lookup[key], "classification": classification}
            for key, classification in fixed_clauses.items()
        ],
        "project_context": dict(project_context or {}),
        "semantic_field_requirements": {
            "binding_constraints_are_not_gameplay_guards": True,
            "animation_roles_allowed": any(
                re.search(r"\b(?:anim|animation|montage|pose|motion|visual)\w*\b", row["text"], re.I)
                for row in behavior_obligations
            ),
            "guards_must_reference_source_terms": sorted(
                set().union(*(_semantic_words(row["text"]) for row in behavior_obligations))
            ),
            "operation_key_format": "lowercase_namespace.action",
        },
    }
    convergence_attempts = 0
    if model_query is None:
        try:
            from tech_connector.knowledge.search import (
                get_installed_ollama_models,
                query_ollama_json_until_complete,
                query_ollama_text,
            )
            from tech_connector.services.settings_service import load_settings

            settings = dict(load_settings() or {})
            convergence_attempts = int(settings.get("behavior_convergence_max_attempts") or 0)
            installed_models = get_installed_ollama_models()
            model = _select_behavior_reasoning_model(
                settings, installed_models, prompt
            )
            repair_models = []
            for candidate in installed_models:
                match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", candidate.lower())
                size = float(match.group(1)) if match else 1000.0
                if 6.0 <= size <= 9.0 and "embed" not in candidate.lower():
                    repair_models.append(
                        ("qwen2.5-coder" not in candidate.lower(), abs(size - 7.0), candidate)
                    )
            repair_model = min(repair_models, default=(False, 0.0, model))[2]
            format_models = []
            for candidate in installed_models:
                if "embed" in candidate.lower():
                    continue
                match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", candidate.lower())
                size = float(match.group(1)) if match else 1000.0
                if 2.5 <= size <= 4.0:
                    format_models.append((abs(size - 3.0), "coder" not in candidate.lower(), candidate))
            format_model = min(format_models, default=(0.0, False, model))[2]
            selected_size_match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", model.lower())
            selected_size = float(selected_size_match.group(1)) if selected_size_match else 0.0
            if selected_size >= 6.0:
                # Switching models mid-contract keeps both contexts resident on
                # common GPUs and can increase first-token latency by >20x.
                format_model = model
            def model_query(system_text: str, user_text: str) -> str | None:
                obligation_count = max(1, user_text.count('"parent_id"'))
                repair_payload = {}
                try:
                    repair_payload = json.loads(user_text)
                except (TypeError, ValueError):
                    pass
                critic_errors = [
                    str(value).lower() for value in dict(repair_payload or {}).get("critic_errors") or []
                ]
                fields_to_regenerate = list(
                    dict(repair_payload or {}).get("fields_to_regenerate") or []
                )
                accepted_fields = dict(
                    dict(repair_payload or {}).get("accepted_fields") or {}
                )
                repair_candidate = dict(
                    dict(repair_payload or {}).get("repair_candidate") or {}
                )
                narrow_target = fields_to_regenerate[0] if fields_to_regenerate else ""
                narrow_structural_repair = (
                    bool(critic_errors)
                    and bool(fields_to_regenerate)
                    and _narrow_repair_target_has_shell(
                        narrow_target, repair_candidate or accepted_fields
                    )
                )
                active_model = (
                    repair_model if _narrow_repair_needs_reasoning(narrow_target) else format_model
                    if narrow_structural_repair
                    else repair_model
                    if critic_errors and repair_model != model
                    else model
                )
                if obligation_count == 1:
                    system_text = """Return one concise JSON behavior contract for behavior_clauses[0].
If accepted_fields is present, copy those values exactly without rewriting them. Generate only
fields_to_regenerate, then combine the locked and regenerated fields into the complete contract.
Return exactly: summary, clause_coverage, behaviors, proposed_atomic_operations, ambiguities, assumptions.
behaviors must contain exactly one item with id, title, source_clauses, trigger, observations, guards,
outcomes, animation_roles, proof_scenarios, operations. Use the clause ID in source_clauses and coverage.
clause_coverage items are objects with source_clause, classification, covered_by. Every other listed field is
a string or an array of short strings; proposed_atomic_operations is an array of operation-key strings.
Binding context and constraints shape the behavior but are never additional behaviors.
Obey semantic_field_requirements exactly. Never use a binding constraint as a gameplay guard.
Critic errors are mandatory field corrections. Replace rejected fields; do not copy them unchanged.
All plural fields are arrays of strings. Use 1-2 short items per list.
A guard is a complete boolean predicate with subject, predicate, and criterion, such as "measured hit is valid";
labels such as "hit-gated" are invalid. An operation namespace is a domain noun, never perform/do/run/execute/generated.
Operations are lowercase namespace.action keys, preferably two segments, such as collision.trace_forward.
An input key is only a trigger, never the actor. Trigger strings name the input activation; outcomes name the character or system.
For an animation-only clause, use animation asset roles and animation/state operations only; never invent damage, opponents, or physics.
An unqualified distance is a maximum range: guards use within or at most, never at least or greater than.
Never invent keys, assets, evidence, or success. Output JSON only."""
                if narrow_structural_repair:
                    system_text = """Repair exactly one rejected behavior-contract field.
Return exactly one JSON object with one key: value. The value must have the field's declared scalar/list shape.
Use the source clause, locked behavior, critic errors, field contract, and repair hint. Do not return the full contract.
When critic errors say numeric constants were absent from the source, value must contain no digits. Output JSON only."""
                    target_leaf = narrow_target.rsplit(".", 1)[-1]
                    target_errors = [
                        str(value)
                        for value in repair_payload.get("critic_errors") or []
                        if _critic_error_targets_field(str(value), target_leaf)
                    ]
                    all_hints = dict(repair_payload.get("repair_hints") or {})
                    target_hints = {
                        key: value
                        for key, value in all_hints.items()
                        if key == target_leaf
                        or (key == "numeric_values" and target_leaf in {
                            "guards", "observations", "operations", "outcomes", "proof_scenarios"
                        })
                    }
                    query_payload = {
                        "source_clauses": repair_payload.get("behavior_clauses") or [],
                        "field": narrow_target,
                        "critic_errors": target_errors,
                        "locked_fields": repair_payload.get("accepted_fields") or {},
                        "current_candidate": repair_payload.get("repair_candidate") or {},
                        "field_contracts": repair_payload.get("field_contracts") or {},
                        "repair_hints": target_hints,
                    }
                    query_user_text = json.dumps(query_payload, default=str)
                else:
                    query_user_text = user_text
                deterministic_error_markers = {
                    "guards": ("missing", "source-clause precondition", "guards are labels", "circular invulnerability", "unsupported hit precondition"),
                    "observations": ("missing", "must be an array", "omit source-clause precondition", "runtime facts used by guards", "guarded", "surface direction or normal", "directional movement basis"),
                    "operations": ("missing", "source behavior semantics", "authoritative gameplay effect", "movement, physics, character, or transform namespace", "hit-gated sensing", "contextual sensing producer", "animation-only request", "directional basis", "invulnerability implementation", "feature-level placeholders", "not grounded", "redundant movement effects"),
                    "outcomes": ("missing", "actor movement effect", "observable state or movement", "animation-only outcomes", "measured wall", "directional movement basis", "invulnerability implementation"),
                    "proof_scenarios": ("actor movement assertion", "observable outcome", "negative proof", "animation playback proof"),
                    "trigger": ("input key", "input activation event", "embeds a source precondition"),
                    "animation_roles": ("actors rather than animation asset roles", "identify the source behavior", "required animation roles"),
                }
                target_error_blob = " ".join(target_errors).lower() if narrow_structural_repair else ""
                can_derive_without_model = bool(narrow_structural_repair) and any(
                    marker in target_error_blob
                    for marker in deterministic_error_markers.get(target_leaf, ())
                )
                if can_derive_without_model:
                    result = json.dumps({"value": [] if target_leaf != "trigger" else ""})
                    trace.emit(
                        "deterministic_field_repair_started",
                        field=narrow_target,
                        critic_errors=target_errors,
                    )
                else:
                    trace.begin_stream()
                    trace.emit(
                        "model_request_started",
                        model=active_model,
                        initial_model=model,
                        repair_model=repair_model,
                        format_model=format_model,
                        narrow_structural_repair=narrow_structural_repair,
                        obligation_count=obligation_count,
                        system_characters=len(system_text),
                        user_characters=len(query_user_text),
                        system=system_text,
                        user=query_user_text,
                    )
                    model_started = time.monotonic()
                    result = query_ollama_json_until_complete(
                        active_model,
                        system_text,
                        query_user_text,
                        num_ctx=4096,
                        timeout=1800,
                        temperature=0.0,
                        progress_callback=trace.stream_callback,
                    )
                    trace.emit(
                        "model_request_finished",
                        model=active_model,
                        elapsed_seconds=round(time.monotonic() - model_started, 3),
                        response_characters=len(result or ""),
                        response=result or "",
                    )
                if narrow_structural_repair and result:
                    narrow_result = json.loads(result)
                    target = narrow_target
                    narrow_value = _extract_narrow_repair_value(
                        narrow_result, target
                    )
                    if narrow_value is None:
                        if can_derive_without_model:
                            narrow_value = [] if target_leaf != "trigger" else ""
                        else:
                            trace.emit(
                                "narrow_field_repair_rejected",
                                field=target,
                                response=narrow_result,
                                reason="response omitted requested field",
                            )
                            return json.dumps(
                                repair_payload.get("repair_candidate") or {}, default=str
                            )
                    if narrow_value is not None:
                        list_fields = {
                            "animation_roles", "guards", "observations", "operations",
                            "outcomes", "proof_scenarios", "source_clauses",
                        }
                        if target.rsplit(".", 1)[-1] in list_fields and not isinstance(
                            narrow_value, list
                        ):
                            narrow_value = [str(narrow_value)]
                        if isinstance(narrow_value, list):
                            narrow_value = [
                                str(
                                    value.get("description")
                                    or value.get("name")
                                    or json.dumps(value, default=str)
                                )
                                if isinstance(value, dict)
                                else str(value)
                                for value in narrow_value
                            ]
                        if target.endswith(".guards") and isinstance(narrow_value, list):
                            narrow_value = [
                                re.sub(r"\s+", " ", str(value).replace(".", " ").replace("_", " ")).strip()
                                for value in narrow_value
                            ]
                        if target.endswith(".trigger") and any(
                            "input key" in str(value).lower()
                            or "input activation event" in str(value).lower()
                            or "embeds a source precondition" in str(value).lower()
                            for value in target_errors
                        ):
                            source_packet_text = json.dumps(
                                repair_payload.get("behavior_clauses") or [], default=str
                            )
                            requested = sorted(_extract_input_keys(source_packet_text))
                            if requested:
                                narrow_value = f"{requested[0]} input is pressed"
                        assembled = json.loads(json.dumps(
                            repair_payload.get("repair_candidate")
                            or repair_payload.get("accepted_fields")
                            or {},
                            default=str,
                        ))
                        behavior_field = re.fullmatch(r"behaviors\[(\d+)\]\.([a-z_]+)", target)
                        if behavior_field:
                            behavior_index = int(behavior_field.group(1))
                            while len(assembled.setdefault("behaviors", [])) <= behavior_index:
                                assembled["behaviors"].append({})
                            locked_behavior = dict(assembled["behaviors"][behavior_index] or {})
                            source_text = " ".join(
                                str(value) for value in locked_behavior.get("source_clauses") or []
                            )
                            precondition = _source_precondition_phrase(source_text)
                            target_error_text = " ".join(target_errors).lower()
                            field_name = behavior_field.group(2)
                            if precondition and field_name == "observations" and (
                                "omit source-clause precondition facts" in target_error_text
                            ):
                                narrow_value = [f"observed {precondition} condition"]
                            elif field_name == "observations" and (
                                "missing" in target_error_text
                                or "must be an array" in target_error_text
                            ):
                                context_guard = _source_context_guard(source_text)
                                narrow_value = [
                                    "observed "
                                    + context_guard.replace("-", " ")
                                    + " fact"
                                ]
                            elif field_name == "observations" and (
                                "surface direction or normal" in target_error_text
                            ):
                                preserved = [
                                    str(value) for value in locked_behavior.get("observations") or []
                                ]
                                narrow_value = list(dict.fromkeys(
                                    preserved + ["measured wall surface normal"]
                                ))
                            elif field_name == "observations" and (
                                "directional movement basis" in target_error_text
                            ):
                                preserved = [str(value) for value in locked_behavior.get("observations") or []]
                                narrow_value = list(dict.fromkeys(
                                    preserved + ["observed input movement direction"]
                                ))
                            elif field_name == "observations" and (
                                "do not provide the runtime facts used by guards" in target_error_text
                                or "do not provide guarded" in target_error_text
                            ):
                                guard_facts = [
                                    str(value).strip()
                                    for value in locked_behavior.get("guards") or []
                                    if str(value).strip()
                                ]
                                if guard_facts:
                                    narrow_value = [
                                        f"observed {value} fact" for value in guard_facts
                                    ]
                            elif precondition and field_name == "guards" and (
                                "source-clause precondition" in target_error_text
                            ):
                                narrow_value = [f"observed {precondition} condition is active"]
                            elif field_name == "guards" and (
                                "missing" in target_error_text
                                or "source-clause precondition" in target_error_text
                                or "guards are labels" in target_error_text
                            ):
                                narrow_value = [_source_context_guard(source_text)]
                            elif field_name == "guards" and (
                                "guards are labels rather than executable predicates" in target_error_text
                            ):
                                observations = [
                                    str(value) for value in locked_behavior.get("observations") or []
                                    if str(value).strip()
                                ]
                                if observations:
                                    source_terms_for_guard = _semantic_words(source_text)
                                    selected = max(
                                        observations,
                                        key=lambda value: len(
                                            _semantic_words(value).intersection(source_terms_for_guard)
                                        ),
                                    )
                                    narrow_value = [f"observed {selected} is valid"]
                                elif re.search(r"\b(?:anim|animation|montage|pose|sequence|clip)\w*\b", source_text, re.I):
                                    requested_keys = sorted(_extract_input_keys(source_text))
                                    event_name = (
                                        f"{requested_keys[0]} input activation"
                                        if requested_keys else f"{_source_animation_role(source_text)} trigger"
                                    )
                                    narrow_value = [f"{event_name} is received"]
                            elif field_name == "guards" and (
                                "circular invulnerability precondition" in target_error_text
                                or "unsupported hit precondition" in target_error_text
                            ):
                                narrow_value = [_source_context_guard(source_text)]
                            elif precondition and field_name == "proof_scenarios" and (
                                "negative proof for the requested precondition" in target_error_text
                            ):
                                positive = next(
                                    iter(locked_behavior.get("outcomes") or []),
                                    "requested observable outcome occurs",
                                )
                                narrow_value = [
                                    str(positive),
                                    f"when observed {precondition} condition is not active, activation is rejected and authoritative state remains unchanged",
                                ]
                            elif field_name == "outcomes" and (
                                "actor movement effect" in target_error_text
                                or "observable state or movement change" in target_error_text
                                or "missing" in target_error_text
                            ):
                                if _is_animation_state_propagation(source_text):
                                    narrow_value = [
                                        f"{_source_anim_instance_name(source_text)} state variables match owning character state after every update"
                                    ]
                                elif "dodge" in source_text.lower() and (
                                    "directional movement basis" in target_error_text
                                    or "bounded invulnerability implementation" in target_error_text
                                ):
                                    narrow_value = [
                                        "character dodges along the observed input direction",
                                        "character is invulnerable only during the bounded window",
                                    ]
                                elif "wall-jump outcome" in target_error_text:
                                    narrow_value = [
                                        "character moves away from the measured wall normal and gains upward movement"
                                    ]
                                else:
                                    behavior_phrase = _source_behavior_phrase(source_text)
                                    if behavior_phrase:
                                        narrow_value = [f"character {behavior_phrase}"]
                            elif field_name == "operations" and (
                                "target-directed travel" in target_error_text
                                and "hit-gated sensing operation" in target_error_text
                            ):
                                narrow_value = [
                                    "collision.trace_forward",
                                    "movement.launch_toward_observed_hit",
                                ]
                            elif field_name == "operations" and (
                                "surface-relative movement operations omit a directional basis" in target_error_text
                            ):
                                narrow_value = [
                                    "physics.apply_directional_impulse_from_surface_normal",
                                    "movement.apply_wall_jump_vertical_velocity",
                                ]
                            elif field_name == "operations" and "dodge" in source_text.lower() and (
                                "feature-level placeholders" in target_error_text
                                or "not grounded" in target_error_text
                            ):
                                narrow_value = [
                                    "physics.apply_directional_dodge_impulse",
                                    "combat.enable_bounded_invulnerability_window",
                                    "combat.schedule_invulnerability_clear",
                                ]
                            elif field_name == "animation_roles":
                                narrow_value = [_source_animation_role(source_text)]
                            elif field_name == "operations" and (
                                "directional movement basis" in target_error_text
                                or "bounded invulnerability implementation" in target_error_text
                            ) and "dodge" in source_text.lower():
                                narrow_value = [
                                    "physics.apply_directional_dodge_impulse",
                                    "combat.enable_bounded_invulnerability_window",
                                    "combat.schedule_invulnerability_clear",
                                ]
                            elif field_name == "operations" and (
                                "hit-gated sensing operation" in target_error_text
                            ):
                                rejected_keys = set(re.findall(
                                    r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*",
                                    target_error_text,
                                ))
                                preserved_operations = [
                                    str(value)
                                    for value in locked_behavior.get("operations") or []
                                    if str(value) not in rejected_keys
                                ]
                                narrow_value = list(dict.fromkeys(
                                    preserved_operations + ["collision.trace_forward"]
                                ))
                            elif field_name == "operations" and (
                                "contextual sensing producer" in target_error_text
                            ):
                                preserved_operations = [
                                    str(value) for value in locked_behavior.get("operations") or []
                                ]
                                narrow_value = list(dict.fromkeys(
                                    preserved_operations + [_source_context_sensing_operation(source_text)]
                                ))
                            elif field_name == "operations" and (
                                "animation-only request" in target_error_text
                            ):
                                role = next(
                                    iter(locked_behavior.get("animation_roles") or []),
                                    "behavior_montage",
                                )
                                role_key = re.sub(r"[^a-z0-9_]+", "_", str(role).lower()).strip("_")
                                narrow_value = [f"animation.play_{role_key}"]
                            elif field_name == "operations" and (
                                "operations omit required source behavior semantics" in target_error_text
                            ):
                                if _is_animation_state_propagation(source_text):
                                    narrow_value = [
                                        "state.read_owning_character_variables",
                                        "state.write_anim_instance_variables",
                                    ]
                                else:
                                    mechanic = _source_movement_mechanic(source_text)
                                if not _is_animation_state_propagation(source_text) and mechanic:
                                    narrow_value = [f"movement.apply_{mechanic}_impulse"]
                            elif field_name == "outcomes" and (
                                "animation-only outcomes" in target_error_text
                            ):
                                role = next(
                                    iter(locked_behavior.get("animation_roles") or []),
                                    "behavior montage",
                                )
                                narrow_value = [f"{str(role).replace('_', ' ')} plays"]
                            elif field_name == "outcomes" and (
                                "wall-jump outcome" in target_error_text
                                or "measured surface basis" in target_error_text
                            ):
                                narrow_value = [
                                    "character moves away from the measured wall normal and gains upward movement"
                                ]
                            elif field_name == "outcomes" and (
                                "directional movement basis" in target_error_text
                                or "bounded invulnerability implementation" in target_error_text
                            ) and "dodge" in source_text.lower():
                                narrow_value = [
                                    "character dodges along the observed input direction",
                                    "character is invulnerable only during the bounded window",
                                ]
                            elif field_name == "proof_scenarios" and (
                                "contextual animation playback proof" in target_error_text
                            ):
                                outcome = next(
                                    iter(locked_behavior.get("outcomes") or []),
                                    "requested animation plays",
                                )
                                narrow_value = [str(outcome)]
                            elif field_name == "proof_scenarios" and (
                                "actor movement assertion" in target_error_text
                                or "do not assert the observable outcome" in target_error_text
                            ):
                                positive_proofs = [
                                    str(value) for value in locked_behavior.get("outcomes") or []
                                ]
                                negative_proofs = [
                                    str(value)
                                    for value in locked_behavior.get("proof_scenarios") or []
                                    if re.search(
                                        r"\b(?:does not|fails?|invalid|not |preserves?|rejects?|unchanged|without)\b",
                                        str(value),
                                        re.I,
                                    )
                                ]
                                narrow_value = list(dict.fromkeys(
                                    positive_proofs + negative_proofs
                                ))
                            if field_name == "operations":
                                narrow_value = _repair_atomic_operations(
                                    source_text,
                                    list(locked_behavior.get("operations") or []),
                                    list(narrow_value or []) if isinstance(narrow_value, list) else [narrow_value],
                                    target_error_text,
                                )
                            if behavior_field.group(2) == "proof_scenarios":
                                locked_source = " ".join(
                                    str(value) for value in locked_behavior.get("source_clauses") or []
                                )
                                if re.search(r"\b\d+(?:\.\d+)?\b", locked_source):
                                    locked_behavior["proof_scenarios"] = []
                                    narrow_value = _enrich_behavior_lifecycle(locked_behavior)["proof_scenarios"]
                            assembled["behaviors"][behavior_index][behavior_field.group(2)] = narrow_value
                        else:
                            assembled[target] = narrow_value
                        assembled.setdefault(
                            "summary",
                            "Behavior contract repaired from locked accepted fields.",
                        )
                        assembled.setdefault("clause_coverage", [])
                        assembled["proposed_atomic_operations"] = list(
                            dict.fromkeys(
                                str(operation)
                                for behavior in assembled.get("behaviors") or []
                                for operation in dict(behavior or {}).get("operations") or []
                            )
                        )
                        assembled.setdefault("ambiguities", [])
                        assembled.setdefault("assumptions", [])
                        trace.emit(
                            "narrow_field_repair_assembled",
                            field=target,
                            value=narrow_value,
                            synthesis=assembled,
                        )
                        return json.dumps(assembled, default=str)
                return result
        except Exception:
            model_query = None
    if model_query is None:
        return {"status": "unavailable", "synthesis": {}, "validation": {"ok": False, "errors": ["No reasoning model is available."]}, "stage_trace_path": str(trace.path)}
    staged_attempts: list[dict[str, Any]] = []
    staged_seed: dict[str, Any] = {}
    staged_validation: dict[str, Any] = {}
    if (
        len(behavior_obligations) > 1
        and not dict(project_context or {}).get("_disable_obligation_staging")
    ):
        merged_behaviors: list[dict[str, Any]] = []
        merged_operations: list[str] = []
        merged_ambiguities: list[str] = []
        merged_assumptions: list[str] = []
        failed_obligations: list[dict[str, Any]] = []
        for obligation_index, obligation in enumerate(behavior_obligations, 1):
            trace.emit(
                "obligation_started",
                obligation_index=obligation_index,
                obligation_count=len(behavior_obligations),
                obligation_id=obligation["id"],
                obligation=obligation["text"],
            )
            print(
                f"[Behavior Convergence] Obligation {obligation_index}/{len(behavior_obligations)}: "
                f"{obligation['text']}",
                flush=True,
            )
            constraint_text = ". ".join(
                clause_lookup[key] for key in fixed_clauses
            )
            sub_prompt = str(obligation["text"])
            if constraint_text:
                sub_prompt += ". " + constraint_text
            sub_context = dict(project_context or {})
            sub_context["_disable_obligation_staging"] = True
            sub_context["parent_behavior_context"] = clause_lookup.get(
                str(obligation.get("parent_id") or ""), obligation["text"]
            )
            sub_result = synthesize_novel_behavior_contract(
                sub_prompt,
                project_context=sub_context,
                model_query=model_query,
                stage_trace=trace,
            )
            staged_attempts.extend(
                {
                    **dict(row),
                    "obligation_id": obligation["id"],
                    "obligation": obligation["text"],
                }
                for row in sub_result.get("convergence_attempts") or []
            )
            if sub_result.get("status") != "validated":
                failed_obligation = {
                    "id": obligation["id"],
                    "text": obligation["text"],
                    "validation": sub_result.get("validation") or {},
                }
                failed_obligations.append(failed_obligation)
                trace.emit("obligation_failed", **failed_obligation)
                print(
                    f"[Behavior Convergence] Obligation {obligation_index} requires knowledge; "
                    "continuing with remaining obligations.",
                    flush=True,
                )
                continue
            trace.emit(
                "obligation_validated",
                obligation_id=obligation["id"],
                attempts=len(sub_result.get("convergence_attempts") or []),
                synthesis=sub_result.get("synthesis") or {},
            )
            print(
                f"[Behavior Convergence] Obligation {obligation_index} validated after "
                f"{len(sub_result.get('convergence_attempts') or [])} attempt(s).",
                flush=True,
            )
            sub_synthesis = dict(sub_result.get("synthesis") or {})
            for behavior in sub_synthesis.get("behaviors") or []:
                behavior = dict(behavior)
                behavior["id"] = f"O{obligation_index}_{behavior.get('id') or 'behavior'}"
                behavior["source_clauses"] = [obligation["text"]]
                behavior["_obligation_id"] = obligation["id"]
                behavior["_parent_clause_id"] = obligation["parent_id"]
                merged_behaviors.append(behavior)
            merged_operations.extend(sub_synthesis.get("proposed_atomic_operations") or [])
            merged_ambiguities.extend(sub_synthesis.get("ambiguities") or [])
            merged_assumptions.extend(sub_synthesis.get("assumptions") or [])
        if failed_obligations:
            failed_text = [str(row.get("text") or "") for row in failed_obligations]
            failed_errors = list(dict.fromkeys(
                str(error)
                for row in failed_obligations
                for error in dict(row.get("validation") or {}).get("errors") or []
            ))
            return {
                "status": "knowledge_required",
                "synthesis": {
                    "summary": "Validated obligations retained; unresolved obligations require more knowledge.",
                    "behaviors": _apply_global_animation_presentation(
                        prompt, _link_sibling_animation_dependencies(merged_behaviors)
                    ),
                    "proposed_atomic_operations": list(dict.fromkeys(merged_operations)),
                    "ambiguities": list(dict.fromkeys(merged_ambiguities + failed_text)),
                    "assumptions": list(dict.fromkeys(merged_assumptions)),
                },
                "validation": {
                    "ok": False,
                    "errors": failed_errors or ["One or more behavior obligations require knowledge."],
                    "uncovered_clauses": failed_text,
                    "behavior_count": len(merged_behaviors),
                },
                "failed_obligation": failed_obligations[0],
                "failed_obligations": failed_obligations,
                "convergence_attempts": staged_attempts,
                "stage_trace_path": str(trace.path),
            }
        merged_behaviors = _apply_global_animation_presentation(
            prompt, _link_sibling_animation_dependencies(merged_behaviors)
        )
        staged_seed = {
            "summary": "Merged independently validated behavior obligations.",
            "clause_coverage": [
                {
                    "source_clause": obligation["text"],
                    "classification": "behavior",
                    "covered_by": [
                        str(behavior.get("id") or "")
                        for behavior in merged_behaviors
                        if obligation["text"] in (behavior.get("source_clauses") or [])
                    ],
                }
                for obligation in behavior_obligations
            ] + [
                {
                    "source_clause": clause_lookup[key],
                    "classification": classification,
                    "covered_by": [],
                }
                for key, classification in fixed_clauses.items()
            ],
            "behaviors": merged_behaviors,
            "proposed_atomic_operations": list(dict.fromkeys(merged_operations)),
            "ambiguities": list(dict.fromkeys(merged_ambiguities)),
            "assumptions": list(dict.fromkeys(merged_assumptions)),
            "global_proof_scenarios": _requested_global_proof_scenarios(prompt),
            "_coverage_obligations": list(obligation_lookup.values()) + [
                clause_lookup[key] for key in fixed_clauses
            ],
        }
        staged_validation = validate_model_behavior_synthesis(prompt, staged_seed)
        if staged_validation.get("ok"):
            return {
                "status": "validated",
                "synthesis": staged_seed,
                "validation": staged_validation,
                "convergence_attempts": staged_attempts,
                "stage_trace_path": str(trace.path),
            }
    synthesis: dict[str, Any] = staged_seed
    validation: dict[str, Any] = staged_validation or {"ok": False, "errors": ["No synthesis attempt completed."]}
    convergence = AdaptiveBehaviorConvergence(max_attempts=convergence_attempts)
    user_packet = json.dumps(
        convergence.repair_packet(packet, synthesis, validation, "merge_repair")
        if synthesis else packet,
        default=str,
    )
    attempt = 0
    last_failure_signature = ""
    repeated_failure_count = 0
    critic_error_counts: dict[tuple[str, ...], int] = {}
    synthesis_counts: dict[str, int] = {}
    raw_failure_counts: dict[str, int] = {}
    exception_counts: dict[str, int] = {}
    while convergence.can_continue():
        strategy = convergence.strategy_for(attempt, validation)
        raw_text = ""
        try:
            raw = model_query(system, user_packet)
            if not raw:
                validation = {
                    "ok": False,
                    "errors": ["The behavior reasoning model did not return a response."],
                    "uncovered_clauses": _clauses(prompt),
                }
                convergence.record(validation, strategy)
                break
            raw_text = str(raw or "").strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.I | re.S)
            synthesis = json.loads(raw_text)
            if not isinstance(synthesis, dict):
                raise ValueError("Model response is not a JSON object.")
            for row in synthesis.get("clause_coverage") or []:
                if isinstance(row, dict):
                    row["source_clause"] = resolve_clause_reference(
                        row.get("source_clause")
                    )
            synthesis.setdefault("clause_coverage", []).extend(
                {
                    "source_clause": clause_lookup[key],
                    "classification": classification,
                    "covered_by": [],
                }
                for key, classification in fixed_clauses.items()
                if not any(
                    row.get("source_clause") == clause_lookup[key]
                    for row in synthesis.get("clause_coverage") or []
                    if isinstance(row, dict)
                )
            )
            for behavior in synthesis.get("behaviors") or []:
                if isinstance(behavior, dict):
                    behavior["source_clauses"] = [
                        resolve_clause_reference(value)
                        for value in behavior.get("source_clauses") or []
                    ]
                    behavior_id = str(behavior.get("id") or "")
                    for source_clause in behavior["source_clauses"]:
                        matching_coverage = next(
                            (
                                row for row in synthesis.get("clause_coverage") or []
                                if isinstance(row, dict) and row.get("source_clause") == source_clause
                            ),
                            None,
                        )
                        if matching_coverage is None:
                            synthesis.setdefault("clause_coverage", []).append(
                                {
                                    "source_clause": source_clause,
                                    "classification": "behavior",
                                    "covered_by": [behavior_id] if behavior_id else [],
                                }
                            )
                        elif behavior_id:
                            covered_by = matching_coverage.get("covered_by")
                            if not isinstance(covered_by, list):
                                covered_by = [str(covered_by)] if covered_by else []
                                matching_coverage["covered_by"] = covered_by
                            if behavior_id not in covered_by:
                                covered_by.append(behavior_id)
            synthesis["clause_coverage"] = [
                {
                    "source_clause": obligation_text,
                    "classification": "behavior",
                    "covered_by": [
                        str(behavior.get("id") or "")
                        for behavior in synthesis.get("behaviors") or []
                        if isinstance(behavior, dict)
                        and obligation_text in (behavior.get("source_clauses") or [])
                        and str(behavior.get("id") or "")
                    ],
                }
                for obligation_text in obligation_lookup.values()
            ] + [
                {
                    "source_clause": clause_lookup[key],
                    "classification": classification,
                    "covered_by": [],
                }
                for key, classification in fixed_clauses.items()
            ]
            synthesis["behaviors"] = [
                _enrich_behavior_lifecycle(behavior)
                for behavior in synthesis.get("behaviors") or []
                if isinstance(behavior, dict)
            ]
            synthesis["proposed_atomic_operations"] = list(
                dict.fromkeys(
                    str(operation)
                    for behavior in synthesis["behaviors"]
                    for operation in behavior.get("operations") or []
                )
            )
            synthesis["_coverage_obligations"] = list(obligation_lookup.values()) + [
                clause_lookup[key] for key in fixed_clauses
            ]
            synthesis["global_proof_scenarios"] = _requested_global_proof_scenarios(prompt)
            validation = validate_model_behavior_synthesis(prompt, synthesis)
            convergence.record(validation, strategy)
            trace.emit(
                "critic_result",
                attempt=attempt + 1,
                strategy=strategy,
                validation=validation,
                synthesis=synthesis,
            )
            if validation["ok"]:
                break
            synthesis_signature = json.dumps(synthesis, sort_keys=True, default=str)
            synthesis_counts[synthesis_signature] = synthesis_counts.get(synthesis_signature, 0) + 1
            if synthesis_counts[synthesis_signature] >= 3:
                validation = {
                    **validation,
                    "ok": False,
                    "errors": list(validation.get("errors") or [])
                    + [
                        "Repair convergence stalled after cycling back to the same invalid contract three times; "
                        "additional knowledge or a different technique is required."
                    ],
                }
                trace.emit(
                    "convergence_cycle_detected",
                    attempt=attempt + 1,
                    synthesis_recurrences=synthesis_counts[synthesis_signature],
                    validation=validation,
                )
                break
            critic_signature = tuple(sorted(str(value) for value in validation.get("errors") or []))
            critic_error_counts[critic_signature] = critic_error_counts.get(critic_signature, 0) + 1
            if critic_error_counts[critic_signature] >= 6:
                validation = {
                    **validation,
                    "ok": False,
                    "errors": list(validation.get("errors") or [])
                    + ["Repair convergence stalled after the same critic errors recurred without progress."],
                }
                trace.emit(
                    "convergence_stalled",
                    attempt=attempt + 1,
                    critic_error_recurrences=critic_error_counts[critic_signature],
                    validation=validation,
                )
                break
            failure_signature = json.dumps(
                {
                    "errors": validation.get("errors") or [],
                    "synthesis": synthesis,
                },
                sort_keys=True,
                default=str,
            )
            if failure_signature == last_failure_signature:
                repeated_failure_count += 1
            else:
                last_failure_signature = failure_signature
                repeated_failure_count = 0
            if repeated_failure_count >= 2:
                validation = {
                    **validation,
                    "ok": False,
                    "errors": list(validation.get("errors") or [])
                    + ["Repair convergence stalled after repeated identical invalid contracts."],
                }
                trace.emit(
                    "convergence_stalled",
                    attempt=attempt + 1,
                    repeated_failure_count=repeated_failure_count + 1,
                    validation=validation,
                )
                break
            print(
                f"[Behavior Convergence] Attempt {attempt + 1} rejected ({strategy}): "
                + "; ".join(validation.get("errors") or []),
                flush=True,
            )
            user_packet = json.dumps(
                convergence.repair_packet(packet, synthesis, validation, strategy),
                default=str,
            )
        except Exception as exc:
            validation = {"ok": False, "errors": [str(exc)], "uncovered_clauses": _clauses(prompt)}
            convergence.record(validation, strategy)
            raw_failure_signature = raw_text.strip()
            exception_signature = f"{type(exc).__name__}:{exc}"
            if raw_failure_signature:
                raw_failure_counts[raw_failure_signature] = raw_failure_counts.get(raw_failure_signature, 0) + 1
            exception_counts[exception_signature] = exception_counts.get(exception_signature, 0) + 1
            if (
                raw_failure_signature and raw_failure_counts[raw_failure_signature] >= 3
            ) or exception_counts[exception_signature] >= 4:
                validation = {
                    **validation,
                    "errors": list(validation.get("errors") or [])
                    + [
                        "Repair convergence stalled because schema repair repeated without producing "
                        "a critic-valid contract; additional knowledge or a different model is required."
                    ],
                }
                trace.emit(
                    "schema_repair_stalled",
                    attempt=attempt + 1,
                    repeated_raw_output=raw_failure_counts.get(raw_failure_signature, 0),
                    repeated_exception=exception_counts[exception_signature],
                    validation=validation,
                )
                break
            # A parse/validation failure can be repaired from returned evidence.
            # Transport failures and empty responses have nothing useful to feed
            # back and must not silently double the planning latency.
            if convergence.can_continue() and raw_text:
                user_packet = json.dumps(
                    convergence.repair_packet(
                        packet,
                        synthesis or {"partial_output": raw_text},
                        validation,
                        "schema_repair_from_scratch",
                    ),
                    default=str,
                )
            else:
                break
        attempt += 1
    synthesis["behaviors"] = _apply_global_animation_presentation(
        prompt, list(synthesis.get("behaviors") or [])
    )
    synthesis["proposed_atomic_operations"] = list(dict.fromkeys(
        str(operation)
        for behavior in synthesis.get("behaviors") or []
        for operation in dict(behavior or {}).get("operations") or []
    ))
    return {
        "status": "validated" if validation["ok"] else "knowledge_required",
        "synthesis": synthesis,
        "validation": validation,
        "convergence_attempts": staged_attempts + convergence.trace(),
        "stage_trace_path": str(trace.path),
    }


def _model_primitives(model_synthesis: dict[str, Any] | None) -> list[dict[str, Any]]:
    packet = dict(model_synthesis or {})
    fully_validated = (
        packet.get("status") == "validated"
        and bool(dict(packet.get("validation") or {}).get("ok"))
    )
    partially_validated = (
        packet.get("status") == "knowledge_required"
        and bool(dict(packet.get("synthesis") or {}).get("behaviors"))
        and bool(packet.get("failed_obligation") or packet.get("failed_obligations"))
    )
    if not fully_validated and not partially_validated:
        return []
    rows = []
    for behavior in dict(packet.get("synthesis") or {}).get("behaviors") or []:
        behavior = dict(behavior)
        rows.append(
            {
                "id": behavior.get("id"),
                "key": "generated." + re.sub(r"[^a-z0-9]+", "_", str(behavior.get("id") or behavior.get("title") or "behavior").lower()).strip("_"),
                "title": behavior.get("title"),
                "source_clauses": list(behavior.get("source_clauses") or []),
                "trigger": behavior.get("trigger"),
                "depends_on": list(behavior.get("depends_on") or []),
                "observations": list(behavior.get("observations") or []),
                "guards": list(behavior.get("guards") or []),
                "states": list(behavior.get("states") or []),
                "transitions": list(behavior.get("transitions") or []),
                "animation_roles": list(behavior.get("animation_roles") or []),
                "outcomes": list(behavior.get("outcomes") or []),
                "operations": list(behavior.get("operations") or []),
                "proof_scenarios": list(behavior.get("proof_scenarios") or behavior.get("outcomes") or []),
                "failure_paths": list(behavior.get("failure_paths") or []),
                "source": (
                    "validated_model_synthesis"
                    if fully_validated
                    else "validated_partial_model_synthesis"
                ),
                "match_evidence": [{"clause": value, "markers": ["model semantic coverage"]} for value in behavior.get("source_clauses") or []],
            }
        )
    return rows


def decompose_prompt_behaviors(
    prompt: str,
    *,
    path: str | Path | None = None,
    model_synthesis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a composable behavior graph while preserving unmatched prompt clauses."""

    payload = load_behavior_primitives(path)
    prompt_lower = str(prompt or "").lower()
    clauses = _clauses(prompt)
    selected: list[dict[str, Any]] = []
    covered_clauses: set[int] = set()
    for primitive in payload.get("primitives") or []:
        primitive = dict(primitive)
        hits = _matches(primitive, prompt_lower)
        if not primitive.get("always") and not hits:
            continue
        clause_hits = []
        for index, clause in enumerate(clauses):
            markers = _matches(primitive, clause.lower())
            if markers:
                covered_clauses.add(index)
                clause_hits.append({"clause": clause, "markers": markers})
        selected.append({**primitive, "match_evidence": clause_hits or [{"clause": "global policy", "markers": hits}]})
    generated = _model_primitives(model_synthesis)
    specific_static_matches = [row for row in selected if not row.get("always")]
    if generated:
        selected = generated + [row for row in selected if row.get("always")]

    # Instructional clauses are not behaviors and should not trigger needless research.
    instruction_only = re.compile(
        r"\b(?:unreal|build|create|implement|system|feature|please|verify|test|working|functional|prompt)\b",
        re.I,
    )
    if generated:
        unknown = list(dict(model_synthesis or {}).get("validation", {}).get("uncovered_clauses") or [])
        failures = list(dict(model_synthesis or {}).get("failed_obligations") or [])
        if not failures and dict(model_synthesis or {}).get("failed_obligation"):
            failures = [dict(model_synthesis or {}).get("failed_obligation")]
        unknown.extend(
            str(failed.get("text") or "")
            for failed in failures
            if dict(failed or {}).get("text")
        )
        unknown = list(dict.fromkeys(unknown))
    else:
        unknown = [
            clause for index, clause in enumerate(clauses)
            if index not in covered_clauses and not instruction_only.search(clause)
        ]
        if not specific_static_matches:
            unknown = clauses
    selected_keys = {str(row.get("key") or "") for row in selected}
    transitions = []
    for row in selected:
        for item in row.get("transitions") or []:
            item = dict(item)
            if item.get("unless_primitive") in selected_keys:
                continue
            if item.get("requires_primitive") and item.get("requires_primitive") not in selected_keys:
                continue
            transitions.append({**item, "primitive": row.get("key")})
    states = list(
        dict.fromkeys(
            [state for row in selected for state in row.get("states") or []]
            + [str(item.get("from") or "") for item in transitions]
            + [str(item.get("to") or "") for item in transitions]
        )
    )
    states = [state for state in states if state]
    operations = list(dict.fromkeys(op for row in selected for op in row.get("operations") or []))
    animation_roles = list(dict.fromkeys(role for row in selected for role in row.get("animation_roles") or []))
    observations = list(dict.fromkeys(value for row in selected for value in row.get("observations") or []))
    guards = list(dict.fromkeys(value for row in selected for value in row.get("guards") or []))
    proof_scenarios = list(dict.fromkeys(value for row in selected for value in row.get("proof_scenarios") or []))
    return {
        "framework": "unreal_behavior_capability_decomposition_v1",
        "source_prompt": prompt,
        "selected_primitives": selected,
        "primitive_keys": [row.get("key") for row in selected],
        "observations": observations,
        "guards": guards,
        "states": states,
        "transitions": transitions,
        "animation_roles": animation_roles,
        "operations": operations,
        "proof_scenarios": proof_scenarios,
        "unmatched_behavior_clauses": unknown,
        "knowledge_required": bool(unknown),
        "model_synthesis_status": dict(model_synthesis or {}).get("status") or "not_requested",
        "model_synthesis_validation": dict(dict(model_synthesis or {}).get("validation") or {}),
        "composition_rule": payload.get("policy"),
    }


def requires_prompt_specific_behavior_synthesis(
    prompt: str, decomposition: dict[str, Any] | None = None
) -> bool:
    """Reject shallow keyword coverage when it cannot represent every atomic obligation."""

    current = dict(decomposition or decompose_prompt_behaviors(prompt))
    if current.get("knowledge_required"):
        return True
    if any(str(value).startswith("generated.") for value in current.get("primitive_keys") or []):
        return False
    clauses = _clauses(prompt)
    lookup = {f"C{index}": clause for index, clause in enumerate(clauses, 1)}
    fixed = {
        key: classification
        for key, clause in lookup.items()
        if (classification := _fixed_nonbehavior_classification(clause))
    }
    obligations, _ = _atomic_behavior_obligations(lookup, fixed)
    specific = [
        row for row in current.get("selected_primitives") or []
        if not dict(row).get("always")
    ]
    explicit_inputs = bool(_extract_input_keys(prompt))
    selected_have_trigger_contract = all(dict(row).get("trigger") for row in specific) if specific else False
    return len(obligations) > len(specific) or (explicit_inputs and not selected_have_trigger_contract)
