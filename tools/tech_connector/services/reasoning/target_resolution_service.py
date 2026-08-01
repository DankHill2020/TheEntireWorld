from __future__ import annotations

"""Evidence-backed target choice and clarification policy."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable

from tech_connector.services.context_momentum_service import ContextMomentum, momentum_from_operation_memory
from tech_connector.services.reasoning.evidence_ranking_service import AttributionPath, RankedTarget, rank_target_candidates, target_resolution_summary
from reasoning_runtime.reasoning.target_entity_service import extract_target_entities


@dataclass
class TargetResolution:
    status: str
    selected_path: str = ""
    confidence: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    explicit_entities: list[dict[str, Any]] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_prompt: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_target_candidates(
    prompt: str,
    candidates: Iterable[dict[str, Any] | str],
    *,
    active_file: str = "",
    open_files: Iterable[str] = (),
    operation_memory: dict[str, Any] | None = None,
    allowed_roots: Iterable[str] = (),
    auto_select_confidence: float = 0.82,
    minimum_margin: float = 0.18,
) -> TargetResolution:
    momentum = momentum_from_operation_memory(operation_memory)
    entities = extract_target_entities(prompt)
    candidate_items = list(candidates)
    ranked = rank_target_candidates(
        prompt,
        candidate_items,
        active_file=active_file,
        open_files=open_files,
        momentum=momentum,
        allowed_roots=allowed_roots,
    )
    if not ranked:
        candidate_items = _explicit_missing_file_candidates(
            prompt,
            entities,
            allowed_roots=allowed_roots,
        )
        if candidate_items:
            ranked = rank_target_candidates(
                prompt,
                candidate_items,
                active_file=active_file,
                open_files=open_files,
                momentum=momentum,
                allowed_roots=allowed_roots,
            )
    if not ranked:
        return TargetResolution(
            status="no_candidates",
            explicit_entities=[item.to_dict() for item in entities],
            needs_clarification=True,
            clarification_prompt="I could not find a project target. Name the file, symbol, widget, graph, or area to inspect.",
            reasons=["No target candidates were returned by discovery."],
        )

    top = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = top.confidence - (runner_up.confidence if runner_up else 0.0)
    explicit_filename = any(item.kind in {"filename", "path"} for item in entities)
    exact_explicit_signal = any(signal.key in {"explicit_exact_path", "explicit_filename", "dotted_module_target"} for signal in top.signals)
    single_explicit_missing_file = (
        len(ranked) == 1
        and str(top.original.get("candidate_source") or "")
        == "explicit_missing_file"
        and exact_explicit_signal
    )
    can_select = (
        not top.excluded
        and (
            single_explicit_missing_file
            or (
                top.confidence >= auto_select_confidence
                and (margin >= minimum_margin or exact_explicit_signal)
            )
        )
    )
    reasons = [signal.reason for signal in sorted(top.signals, key=lambda item: abs(item.score), reverse=True)[:6]]

    if can_select:
        return TargetResolution(
            status="selected",
            selected_path=top.path,
            confidence=top.confidence,
            candidates=[item.to_dict() for item in ranked[:8]],
            explicit_entities=[item.to_dict() for item in entities],
            reasons=reasons,
        )

    clarification = _clarification(ranked, explicit_filename=explicit_filename)
    return TargetResolution(
        status="clarification_required",
        selected_path=top.path,
        confidence=top.confidence,
        candidates=[item.to_dict() for item in ranked[:8]],
        explicit_entities=[item.to_dict() for item in entities],
        needs_clarification=True,
        clarification_prompt=clarification,
        reasons=reasons + [f"Top-to-runner-up confidence margin={margin:.3f}."],
    )


def _explicit_missing_file_candidates(
    prompt: str,
    entities: Iterable[Any],
    *,
    allowed_roots: Iterable[str],
) -> list[dict[str, Any]]:
    """Create one safe candidate for an explicitly named missing code target."""
    if not re.search(
        r"\b(?:add|build|create|generate|implement|make|modify|patch|write)\b",
        prompt or "",
        flags=re.I,
    ):
        return []

    roots: list[Path] = []
    for value in allowed_roots:
        try:
            root = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if root.exists() and root.is_dir() and root not in roots:
            roots.append(root)
    if not roots:
        return []

    resolved_targets: list[Path] = []
    for entity in entities:
        kind = str(getattr(entity, "kind", "") or "")
        value = str(getattr(entity, "normalized", "") or getattr(entity, "value", "") or "").strip()
        metadata = dict(getattr(entity, "metadata", {}) or {})
        if metadata.get("relation") != "explicit_target":
            continue

        candidate: Path | None = None
        if kind == "module":
            parts = value.split(".")
            if len(parts) >= 2 and all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
                candidate = roots[0].joinpath(*parts).with_suffix(".py")
        elif kind in {"filename", "path"}:
            raw_path = Path(value)
            candidate = raw_path if raw_path.is_absolute() else roots[0] / raw_path

        if candidate is None:
            continue
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if not any(resolved == root or root in resolved.parents for root in roots):
            continue
        if resolved not in resolved_targets:
            resolved_targets.append(resolved)

    if len(resolved_targets) != 1:
        return []
    return [{
        "path": str(resolved_targets[0]),
        "score": 0,
        "symbols": [],
        "chunks": [],
        "candidate_source": "explicit_missing_file",
        "purpose": "Explicitly named missing file requested by a write operation.",
    }]


def apply_resolution_to_state(state: Any, resolution: TargetResolution) -> Any:
    state.artifacts["target_resolution"] = resolution.to_dict()
    state.artifacts["target_ranking_report"] = target_resolution_summary([
        RankedTarget(
            path=item.get("path", ""),
            score=float(item.get("score") or 0),
            confidence=float(item.get("confidence") or 0),
            attributions=[
                AttributionPath(
                    type=str(attr.get("type") or ""),
                    source=str(attr.get("source") or ""),
                    evidence=str(attr.get("evidence") or ""),
                    weight=float(attr.get("weight") or 0),
                    explanation=str(attr.get("explanation") or ""),
                    query_fragment=str(attr.get("query_fragment") or ""),
                )
                for attr in (item.get("attributions") or [])
                if isinstance(attr, dict)
            ],
            excluded=bool(item.get("excluded", False)),
            exclusion_reason=str(item.get("exclusion_reason") or ""),
            original=dict(item.get("original") or {}),
        )
        for item in resolution.candidates
    ])
    if resolution.status == "selected":
        state.active_file = resolution.selected_path
        state.confidence.update("target", max(0.0, resolution.confidence - state.confidence.target), reason="Evidence-ranked target selected", source="target_resolution")
        momentum = momentum_from_operation_memory(getattr(state, "operation_memory", {}))
        momentum.remember(resolution.selected_path, "file", source="target_resolution", confidence=resolution.confidence)
        state.operation_memory["context_momentum"] = momentum.to_dict()
        state.operation_memory["recent_file"] = resolution.selected_path
    else:
        state.requires_confirmation = True
        if resolution.clarification_prompt not in state.missing_information:
            state.missing_information.append(resolution.clarification_prompt)
    return state


def _clarification(ranked: list[RankedTarget], *, explicit_filename: bool) -> str:
    top = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    if explicit_filename and any(signal.key == "explicit_filename" for signal in top.signals):
        return (
            f"I believe the intended file is {top.path} (confidence {top.confidence:.0%}). "
            "Confirm that target or provide a different path."
        )
    lines = ["I found plausible targets but should confirm before modifying files:"]
    for index, item in enumerate(ranked[:4], 1):
        if item.excluded:
            continue
        lines.append(f"{index}. {item.path} — confidence {item.confidence:.0%}")
    if runner:
        lines.append(f"The leading candidate does not have enough separation from the next candidate ({top.confidence:.0%} vs {runner.confidence:.0%}).")
    lines.append("Reply with a number, path, symbol, or ask me to broaden discovery.")
    return "\n".join(lines)
