"""Deterministic long-prompt staging helpers.

Large user prompts often contain a full project contract: investigate, plan,
edit, validate, and report. Feeding the entire contract into every model/tool
stage is slow and makes the UI feel stuck. This module keeps the original
contract intact for audit/history, but produces a compact first-stage prompt
for the model.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


LONG_PROMPT_STAGE_THRESHOLD = 2600


@dataclass(frozen=True)
class PromptStage:
    key: str
    title: str
    instructions: list[str]


@dataclass(frozen=True)
class PromptChunk:
    key: str
    title: str
    items: list[str]


@dataclass(frozen=True)
class StagedPromptContract:
    original_chars: int
    source_hash: str
    user_goal: str
    chunks: list[PromptChunk]
    active_stage: PromptStage
    global_constraints: list[str]
    deferred_stages: list[PromptStage]

    def render_for_llm(self) -> str:
        lines = [
            "LONG PROMPT STAGED EXECUTION",
            f"Hash: {self.source_hash}",
            f"Original chars: {self.original_chars}",
            "Synthesis rule: connect chunks into one coherent task model; preserve ordering, safety, validation, and active-stage scope.",
            "Do not treat chunks as separate unrelated requests.",
            f"Goal: {_clip_instruction(self.user_goal or 'Understand and satisfy the user request.', limit=220)}",
            "",
            "Compact source chunks:",
        ]
        for chunk in self.chunks:
            lines.append(f"{chunk.title}:")
            lines.extend(f"- {_clip_instruction(item, limit=125)}" for item in chunk.items[:1])
            if len(chunk.items) > 1:
                lines.append(f"- ...{len(chunk.items) - 1} more requirement(s)")
        lines.extend([
            "",
            f"Active stage: {self.active_stage.title}",
        ])
        lines.extend(f"- {_clip_instruction(item, limit=145)}" for item in self.active_stage.instructions[:6])
        if self.global_constraints:
            lines.extend(["", "Global constraints:"])
            lines.extend(f"- {_clip_instruction(item, limit=130)}" for item in self.global_constraints[:4])
        if self.deferred_stages:
            lines.extend(["", "Deferred stages; do not execute yet:"])
            for stage in self.deferred_stages:
                lines.append(f"- {stage.title}: {len(stage.instructions)} instruction(s)")
        lines.extend(
            [
                "",
                "Quality bar:",
                "- Prefer project evidence over assumptions.",
                "- Do not implement or mutate assets/files yet.",
                "- If context is missing, ask only for the minimum missing information.",
                "- If later stages are required, state the next stage instead of dropping it.",
            ]
        )
        return "\n".join(lines)


def should_stage_prompt(prompt: str, threshold: int = LONG_PROMPT_STAGE_THRESHOLD) -> bool:
    text = prompt or ""
    if len(text) < int(threshold or LONG_PROMPT_STAGE_THRESHOLD):
        return False
    lower = text.lower()
    return (
        "before making any changes" in lower
        or "implementation requirements" in lower
        or "after implementation" in lower
        or len(re.findall(r"^\s*\d+[.)]\s+", text, flags=re.MULTILINE)) >= 8
    )


def build_staged_prompt_contract(prompt: str) -> StagedPromptContract:
    text = prompt or ""
    source_hash = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    user_goal = _first_nonempty_line(text)
    items = _numbered_items(text)
    if not items:
        items = [line.strip() for line in text.splitlines() if line.strip()]

    chunks = _chunk_items(items)
    investigation: list[str] = []
    implementation: list[str] = []
    validation: list[str] = []
    reporting: list[str] = []
    global_constraints: list[str] = []

    for item in items:
        lower = item.lower()
        target = global_constraints
        if any(word in lower for word in ("inspect", "identify", "determine", "found", "missing information", "propose", "plan")):
            target = investigation
        if any(word in lower for word in ("create", "extend", "integrate", "preserve", "networked", "gameplay ability", "architecture")):
            target = implementation
        if any(word in lower for word in ("compile", "syntax", "validation", "validate", "test", "rollback", "unrelated")):
            target = validation
        if any(word in lower for word in ("report", "warnings", "assumptions", "completed", "failed")):
            target = reporting
        if any(word in lower for word in ("do not fabricate", "before editing", "before making", "do not skip", "preserve existing")):
            global_constraints.append(_clip_instruction(item))
        else:
            target.append(_clip_instruction(item))

    if not investigation:
        investigation = [_clip_instruction(items[0])] if items else ["Understand the user goal and identify project evidence before changing anything."]

    active = PromptStage(
        "investigation_plan",
        "Stage 1 - Inspect existing project state and propose a staged implementation plan",
        _dedupe(investigation)[:10],
    )
    deferred = [
        PromptStage("implementation", "Stage 2 - Implement only after plan approval", _dedupe(implementation)[:12]),
        PromptStage("validation", "Stage 3 - Compile and validate behavior", _dedupe(validation)[:10]),
        PromptStage("reporting", "Stage 4 - Report verified outcome and unresolved risks", _dedupe(reporting)[:10]),
    ]
    deferred = [stage for stage in deferred if stage.instructions]
    return StagedPromptContract(
        original_chars=len(text),
        source_hash=source_hash,
        user_goal=_clip_instruction(user_goal, limit=420),
        chunks=chunks,
        active_stage=active,
        global_constraints=_dedupe(global_constraints)[:10],
        deferred_stages=deferred,
    )


def staged_prompt_for_llm(prompt: str, threshold: int = LONG_PROMPT_STAGE_THRESHOLD) -> tuple[str, StagedPromptContract | None]:
    if not should_stage_prompt(prompt, threshold):
        return prompt, None
    contract = build_staged_prompt_contract(prompt)
    return contract.render_for_llm(), contract


def _numbered_items(text: str) -> list[str]:
    matches = list(re.finditer(r"^\s*(\d+)[.)]\s+", text or "", flags=re.MULTILINE))
    if not matches:
        return []
    items: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        body = re.sub(r"\s+", " ", body)
        if body:
            items.append(f"{match.group(1)}. {body}")
    return items


def _first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _chunk_items(items: list[str], *, chunk_size: int = 6, max_chunks: int = 8) -> list[PromptChunk]:
    if not items:
        return []
    chunks: list[PromptChunk] = []
    for idx in range(0, len(items), chunk_size):
        if len(chunks) >= max_chunks:
            remaining = len(items) - idx
            if remaining > 0:
                chunks.append(
                    PromptChunk(
                        key=f"chunk_{len(chunks) + 1}",
                        title=f"Chunk {len(chunks) + 1} - Remaining requirements",
                        items=[f"{remaining} additional requirement(s) remain in the source contract; preserve the contract hash and continue staged execution."],
                    )
                )
            break
        group = items[idx: idx + chunk_size]
        title = _chunk_title(group, len(chunks) + 1)
        chunks.append(
            PromptChunk(
                key=f"chunk_{len(chunks) + 1}",
                title=title,
                items=[_clip_instruction(item, limit=220) for item in group],
            )
        )
    return chunks


def _chunk_title(items: list[str], index: int) -> str:
    joined = " ".join(items).lower()
    if any(word in joined for word in ("inspect", "identify", "determine", "found", "plan", "missing information")):
        label = "Discovery and plan"
    elif any(word in joined for word in ("create", "extend", "integrate", "preserve", "networked", "gameplay")):
        label = "Implementation requirements"
    elif any(word in joined for word in ("compile", "syntax", "validate", "test", "rollback")):
        label = "Validation and rollback"
    elif any(word in joined for word in ("report", "warnings", "assumptions", "completed", "failed")):
        label = "Reporting"
    else:
        label = "Task requirements"
    return f"Chunk {index} - {label}"


def _clip_instruction(text: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 18].rstrip() + " ...[condensed]"


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out

# --- Canonical request task graph support ---

from typing import Any


def build_request_task_graph(prompt: str, *, host: str = "", allow_model: bool = False) -> dict[str, Any]:
    """Build the canonical ordered task graph used by routing and execution.

    This delegates interpretation to prompt_intent_service so task splitting and
    route selection cannot independently reinterpret the prompt. Model use is
    opt-in because this function is also called from foreground routing.
    """
    from services.prompt_intent_service import understand_prompt_request

    understanding = understand_prompt_request(prompt, host=host, allow_model=allow_model)
    tasks = [task.to_dict() for task in understanding.tasks]
    task_ids = {str(task.get("task_id") or "") for task in tasks}
    invalid_dependencies: list[dict[str, str]] = []
    for task in tasks:
        for dependency in task.get("depends_on") or []:
            if dependency not in task_ids:
                invalid_dependencies.append({
                    "task_id": str(task.get("task_id") or ""),
                    "missing_dependency": str(dependency),
                })
    return {
        "framework": "canonical_request_task_graph_v1",
        "goal": understanding.normalized_goal,
        "primary_intent": understanding.primary_intent,
        "primary_route": understanding.primary_route,
        "tasks": tasks,
        "constraints": list(understanding.constraints),
        "expected_outputs": list(understanding.expected_outputs),
        "stop_conditions": list(understanding.stop_conditions),
        "valid": not invalid_dependencies,
        "invalid_dependencies": invalid_dependencies,
        "confidence": understanding.confidence,
        "source": understanding.source,
    }


def task_graph_route(task_graph: dict[str, Any]) -> str:
    """Derive the route from task semantics, not isolated prompt keywords."""
    tasks = list(task_graph.get("tasks") or [])
    actions = {str(task.get("action") or "") for task in tasks}
    capabilities = {str(task.get("capability") or "") for task in tasks}
    if "modify_code" in actions or "project_edit" in capabilities:
        return "target_discovery"
    if "execute" in actions or "dcc_execution" in capabilities:
        return "dcc_execute"
    if "compose" in actions or "action_graph" in capabilities:
        return "pipeline_graph"
    if actions.intersection({"search", "inspect"}):
        return "project_search"
    return str(task_graph.get("primary_route") or "chat")
