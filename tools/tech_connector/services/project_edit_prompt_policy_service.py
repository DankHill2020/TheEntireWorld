"""Compact shared model policy for the project-edit workflow."""

from __future__ import annotations

import re
from typing import Any


PROJECT_EDIT_INVARIANT_POLICY = """PROJECT EDIT INVARIANTS
- Use only evidenced project, generated-dependency, catalog, installed, or official APIs.
- Verify an external callable's exact owner, member, kind, and signature before use.
- Do not invent APIs, symbols, imports, patch targets, tests, or placeholder behavior.
- Keep repairs scoped to the failing owner and preserve already verified behavior.
- Return an explicit blocker when evidence or validation is incomplete.
- Generation creates a disposable review candidate; project writes require the request's approval policy.
"""


def _dedupe_lines(text: str) -> str:
    """Remove repeated non-structural instruction lines in stable order.

    :param text: Prompt text.
    :return: Prompt with duplicate instruction lines removed.
    """

    output: list[str] = []
    seen: set[str] = set()
    previous_blank = False
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if output and not previous_blank:
                output.append("")
            previous_blank = True
            continue
        previous_blank = False
        key = re.sub(r"\s+", " ", stripped).casefold()
        structural = stripped.endswith(":") or stripped.startswith(("{", "[", "<"))
        if key in seen and not structural:
            continue
        seen.add(key)
        output.append(raw_line.rstrip())
    while output and not output[-1].strip():
        output.pop()
    return "\n".join(output)


def compact_project_edit_system_prompt(system_prompt: str) -> tuple[str, dict[str, int]]:
    """Combine stage-specific instructions with the single invariant policy.

    :param system_prompt: Stage-specific system instructions.
    :return: Compacted prompt and size metrics.
    """

    before = str(system_prompt or "")
    compacted_stage = _dedupe_lines(before)
    combined = _dedupe_lines(PROJECT_EDIT_INVARIANT_POLICY + "\n" + compacted_stage)
    return combined, {
        "system_chars_before": len(before),
        "system_chars_after": len(combined),
    }


def build_project_edit_task_envelope(
    *,
    stage_key: str,
    stage_label: str,
    user_prompt: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, dict[str, int]]:
    """Wrap one stage request in a small explicit task envelope.

    :param stage_key: Stable workflow stage identifier.
    :param stage_label: User-facing stage label.
    :param user_prompt: Stage-specific evidence and task content.
    :param metadata: Optional stage metadata.
    :return: Task envelope and size metrics.
    """

    source = str(user_prompt or "")
    details = dict(metadata or {})
    owner = str(
        details.get("symbol")
        or ", ".join(str(item) for item in details.get("symbols") or [])
        or details.get("path")
        or "request scope"
    )
    envelope = (
        "PROJECT EDIT TASK\n"
        f"Stage: {stage_key} - {stage_label}\n"
        f"Owner: {owner}\n"
        "Output: follow the stage response contract exactly.\n"
        "Stop: return the named blocker if the evidence cannot support a valid result.\n\n"
        + _dedupe_lines(source)
    )
    return envelope, {
        "user_chars_before": len(source),
        "user_chars_after": len(envelope),
    }
