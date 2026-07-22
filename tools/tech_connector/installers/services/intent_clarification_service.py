"""Clarification prompts for low-confidence deterministic routing."""

from __future__ import annotations

import re
from typing import Any


CONFIDENCE_AUTO_PLAN_MIN = 0.60
CONFIDENCE_CLARIFY_MIN = 0.35


def _extract_files(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+)\b", text or ""):
        value = match.group(1)
        if value not in found:
            found.append(value)
    return found


def _extract_symbolish_names(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]{3,})\b", text or ""):
        value = match.group(1)
        lower = value.lower()
        if "_" not in value:
            continue
        if lower.endswith((".py", ".json", ".uasset")):
            continue
        if value not in found:
            found.append(value)
    return found


def build_action_graph_clarification(
    prompt: str,
    plan: dict[str, Any],
    *,
    project_roots: list[str] | None = None,
) -> dict[str, Any]:
    """Build a concise approval-style clarification for a structured prompt."""
    roots = list(project_roots or [])
    files = _extract_files(prompt)
    symbols = _extract_symbolish_names(prompt)
    diagnostics = list(plan.get("diagnostics") or [])
    confidence = float(plan.get("confidence") or 0.0)

    guesses: list[str] = []
    if "pipeline" in (prompt or "").lower() or "workflow" in (prompt or "").lower():
        guesses.append("You want Tech Connector to create or update a Pipeline node graph, not run an Unreal/DCC prototype.")
    if files:
        guesses.append("Use these source files as grounding: " + ", ".join(f"`{item}`" for item in files[:4]) + ".")
    if symbols:
        guesses.append("Resolve these function/symbol names from the project index: " + ", ".join(f"`{item}`" for item in symbols[:6]) + ".")
    if "flow" in (prompt or "").lower():
        guesses.append("Connect execution flow in the order described by the prompt.")
    if any(term in (prompt or "").lower() for term in ("arg", "args", "return", "returns", "connected")):
        guesses.append("Connect return/output values into matching downstream arguments when the index confirms compatible ports.")
    if not roots:
        guesses.append("The missing piece is an active indexed project root, so symbol resolution cannot be trusted yet.")

    if not guesses:
        guesses.append("The request looks structured, but the deterministic planner could not identify a complete action graph.")

    lines = [
        "I think I know the shape of this, but I should confirm before continuing.",
        "",
        "**Closest Interpretation**",
    ]
    lines.extend(f"- {item}" for item in guesses)
    lines.extend(
        [
            "",
            "**Confidence Benchmark**",
            f"- Planner confidence: `{confidence:.2f}`",
            f"- Auto-plan threshold: `{CONFIDENCE_AUTO_PLAN_MIN:.2f}`",
            f"- Clarify threshold: `{CONFIDENCE_CLARIFY_MIN:.2f}`",
        ]
    )
    if diagnostics:
        lines.extend(["", "**Why I Paused**"])
        lines.extend(f"- {item}" for item in diagnostics[:5])
    lines.extend(
        [
            "",
            "**Reply With**",
            "- `yes` to use this interpretation",
            "- the corrected function/file names if any guess is wrong",
            "- `index project` if the project root/index is missing",
        ]
    )
    return {
        "needs_clarification": True,
        "confidence": confidence,
        "auto_plan_threshold": CONFIDENCE_AUTO_PLAN_MIN,
        "clarify_threshold": CONFIDENCE_CLARIFY_MIN,
        "guesses": guesses,
        "files": files,
        "symbols": symbols,
        "text": "\n".join(lines),
    }
