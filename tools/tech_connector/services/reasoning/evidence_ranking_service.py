from __future__ import annotations

"""Transparent weighted evidence ranking for project targets."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable

from tech_connector.services.context_momentum_service import ContextMomentum
from tech_connector.services.reasoning.target_entity_service import TargetEntity, extract_target_entities


HARD_EXCLUDED_PARTS = {
    ".git", ".svn", ".hg", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".venv", "venv", "dist", "build", "logs", "log", "temp", "tmp",
}
SOFT_EXCLUDED_PARTS = {".project_ai", "cache", "generated", "tool_output"}
METADATA_FILENAMES = {"asset_index.json", "symbol_index.json", "file_index.json", "manifest.json"}
SOURCE_SUFFIXES = {".py", ".pyi", ".cpp", ".cc", ".c", ".h", ".hpp", ".cs", ".qml", ".ui"}


@dataclass
class EvidenceSignal:
    key: str
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttributionPath:
    type: str
    source: str
    evidence: str
    weight: float
    explanation: str
    query_fragment: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RankedTarget:
    path: str
    score: float
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RankedTarget:
    path: str
    score: float
    confidence: float
    signals: list[EvidenceSignal] = field(default_factory=list)
    attributions: list[AttributionPath] = field(default_factory=list)
    excluded: bool = False
    exclusion_reason: str = ""
    original: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 4),
            "signals": [item.to_dict() for item in self.signals],
            "attributions": [item.to_dict() for item in self.attributions],
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
            "original": self.original,
        }


def rank_target_candidates(
    prompt: str,
    candidates: Iterable[dict[str, Any] | str],
    *,
    active_file: str = "",
    active_line: int | None = None,
    open_files: Iterable[str] = (),
    momentum: ContextMomentum | None = None,
    allowed_roots: Iterable[str] = (),
    problem_formulation: dict[str, Any] | None = None,
) -> list[RankedTarget]:
    entities = extract_target_entities(prompt)
    formulation = dict(problem_formulation or {})
    if not formulation:
        try:
            from tech_connector.services.reasoning.problem_formulation_service import build_problem_formulation
            formulation = build_problem_formulation(prompt).to_dict()
        except Exception:
            formulation = {}
    semantic_terms = _semantic_terms_from_formulation(formulation)
    semantic_exclusions = [
        str(item).casefold()
        for item in formulation.get("exclusions") or []
        if str(item or "").strip()
    ]
    explicit_files = [item for item in entities if item.kind in {"filename", "path"}]
    explicit_symbols = [item for item in entities if item.kind == "symbol"]
    open_set = {_norm(item).casefold() for item in open_files if item}
    active_norm = _norm(active_file).casefold() if active_file else ""
    roots = [_norm(root).casefold().rstrip("/") for root in allowed_roots if root]
    momentum = momentum or ContextMomentum()
    ranked: list[RankedTarget] = []

    for raw in candidates:
        data = {"path": raw} if isinstance(raw, str) else dict(raw or {})
        path = str(data.get("path") or data.get("file") or data.get("filename") or "")
        if not path:
            continue
        norm = _norm(path)
        norm_lower = norm.casefold()
        p = Path(path)
        signals: list[EvidenceSignal] = []
        score = 0.0
        excluded, exclusion_reason = _is_excluded(path, explicit_files)

        for entity in explicit_files:
            entity_norm = _norm(entity.normalized or entity.value).casefold()
            if "/" in entity_norm and norm_lower == entity_norm:
                score += 1200.0
                signals.append(EvidenceSignal("explicit_exact_path", 1200.0, f"Exact path explicitly named: {entity.value}"))
            elif p.name.casefold() == Path(entity.value).name.casefold():
                score += 900.0
                signals.append(EvidenceSignal("explicit_filename", 900.0, f"Filename explicitly named: {entity.value}"))
            elif entity_norm and entity_norm in norm_lower:
                score += 320.0
                signals.append(EvidenceSignal("explicit_partial_path", 320.0, f"Path contains explicit target phrase: {entity.value}"))

        # Dotted module notation matching (e.g. maya_tools.Animation.anim_export -> maya_tools/Animation/anim_export)
        import re
        dotted_modules = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+)\b", prompt or "")
        for mod in dotted_modules:
            mod_as_path = mod.replace(".", "/").casefold()
            mod_stem = mod.split(".")[-1].casefold()
            pkg_root = mod.split(".")[0].casefold()
            if (
                norm_lower.endswith(mod_as_path + ".py")
                or norm_lower.endswith(mod_as_path)
                or mod_as_path in norm_lower
                or (p.stem.casefold() == mod_stem and pkg_root in norm_lower)
            ):
                score += 1500.0
                signals.append(EvidenceSignal("dotted_module_target", 1500.0, f"Dotted module explicitly named: {mod}"))

        if active_norm and norm_lower == active_norm:
            score += 360.0
            signals.append(EvidenceSignal("active_file", 360.0, "Candidate is the active editor file."))
            if active_line and active_line > 0:
                score += 45.0
                signals.append(EvidenceSignal("active_cursor_line", 45.0, f"Cursor is currently on line {active_line} in this file."))
        if norm_lower in open_set:
            score += 240.0
            signals.append(EvidenceSignal("open_file", 240.0, "Candidate is open in the editor."))
        if p.name == "__init__.py":
            score -= 600.0
            signals.append(EvidenceSignal("init_file_penalty", -600.0, "__init__.py is rarely the target module implementation."))

        if roots and not any(norm_lower == root or norm_lower.startswith(root + "/") for root in roots):
            score -= 250.0
            signals.append(EvidenceSignal("outside_project_root", -250.0, "Candidate is outside the active project roots."))

        candidate_source = str(data.get("candidate_source") or "")
        if candidate_source == "capability_gap_expected_file":
            score += 620.0
            purpose = str(data.get("purpose") or "").strip()
            reason = "Candidate is an expected generated-code target declared by the capability plan."
            if purpose:
                reason += f" Purpose: {purpose}"
            signals.append(EvidenceSignal("capability_gap_expected_file", 620.0, reason))
            if int(_float(data.get("expected_file_rank"), 99.0)) == 0:
                score += 260.0
                signals.append(EvidenceSignal("capability_gap_primary_expected_file", 260.0, "Candidate is the primary expected file for the generated artifact."))
        elif candidate_source == "generated_artifact_scope":
            score += 900.0
            signals.append(EvidenceSignal(
                "generated_artifact_scope",
                900.0,
                "Candidate is the allowed project scope for a new artifact; nearby files are evidence patterns only.",
            ))

        # Existing search score is supporting evidence, not the authority.
        raw_score = _float(data.get("score"), 0.0)
        if raw_score:
            contribution = min(120.0, max(-120.0, raw_score * 12.0))
            score += contribution
            signals.append(EvidenceSignal("provider_score", contribution, f"Index search relevance (score: {int(raw_score)})."))

        text_blob = " ".join(
            str(data.get(key) or "")
            for key in (
                "name", "symbol", "qualname", "signature", "summary",
                "docstring", "source", "text", "reason", "callers", "callees",
            )
        ).casefold()

        if semantic_terms:
            matched_terms = [term for term in semantic_terms if term in text_blob]
            if matched_terms:
                contribution = min(320.0, 55.0 * len(matched_terms))
                score += contribution
                signals.append(
                    EvidenceSignal(
                        "problem_semantics",
                        contribution,
                        "Candidate supports formulated concepts: " + ", ".join(matched_terms[:6]),
                    )
                )
            elif formulation.get("deliverables") == ["files"]:
                score -= 80.0
                signals.append(
                    EvidenceSignal(
                        "missing_behavior_evidence",
                        -80.0,
                        "Candidate lacks evidence for the formulated implementation behavior.",
                    )
                )

        narrow_helper = any(
            term in text_blob
            for term in ("helper", "utility", "space switch", "mirror", "cleanup", "delete", "remove")
        )
        asks_complete = any(
            term in " ".join(semantic_terms)
            for term in ("complete", "full", "primary", "create rig", "build rig")
        )
        if narrow_helper and asks_complete:
            score -= 140.0
            signals.append(
                EvidenceSignal(
                    "narrow_helper_penalty",
                    -140.0,
                    "Narrow/helper behavior is weaker than the formulated complete implementation goal.",
                )
            )

        for entity in explicit_symbols:
            if entity.value.casefold() in text_blob:
                score += 260.0
                signals.append(EvidenceSignal("explicit_symbol", 260.0, f"Candidate evidence contains explicit symbol {entity.value}."))

        if explicit_files and not any(Path(item.value).name.casefold() == p.name.casefold() for item in explicit_files):
            score -= 90.0
            signals.append(EvidenceSignal("explicit_target_mismatch", -90.0, "Another filename was explicitly named by the user."))

        if excluded:
            score -= 2000.0
            signals.append(EvidenceSignal("hard_exclusion", -2000.0, exclusion_reason))

        attributions = _attributions_from_signals(
            signals,
            target=path,
            prompt=prompt,
            active_line=active_line,
        )
        ranked.append(RankedTarget(path=path, score=score, confidence=0.0, signals=signals, attributions=attributions, excluded=excluded, exclusion_reason=exclusion_reason, original=data))

    ranked.sort(key=lambda item: item.score, reverse=True)
    _assign_confidence(ranked)
    return ranked


def target_resolution_summary(ranked: list[RankedTarget], *, max_items: int = 5) -> str:
    if not ranked:
        return "No target candidates were available."
    lines = ["Target evidence ranking:"]
    for index, item in enumerate(ranked[:max_items], 1):
        lines.append(f"{index}. {item.path} score={item.score:.1f} confidence={item.confidence:.3f}")
        for attribution in sorted(item.attributions, key=lambda s: abs(s.weight), reverse=True)[:5]:
            lines.append(f"   {attribution.weight:+.1f} {attribution.explanation}")
    return "\n".join(lines)


def attribution_summary(item: RankedTarget, *, max_items: int = 5) -> str:
    lines = [f"Connected `{Path(item.path).name or item.path}` to the prompt because:"]
    for index, attribution in enumerate(sorted(item.attributions, key=lambda value: abs(value.weight), reverse=True)[:max_items], 1):
        lines.append(f"  -> Match {index}: {attribution.explanation} (weight: {attribution.weight:.1f}).")
    return "\n".join(lines)



def _semantic_terms_from_formulation(formulation: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("subject", "interpreted_problem", "desired_outcome"):
        values.extend(_concept_terms(str(formulation.get(key) or "")))
    for relationship in formulation.get("relationships") or []:
        values.extend(_concept_terms(str(relationship)))
    for item in formulation.get("evidence_required") or []:
        values.extend(_concept_terms(str(item)))
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result[:24]


def _concept_terms(text: str) -> list[str]:
    stop = {
        "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "with",
        "that", "which", "what", "user", "requested", "source", "file", "files",
        "function", "functions", "method", "methods", "code", "project",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9_]+", (text or "").casefold())
        if len(token) >= 3 and token not in stop
    ]
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(0, max(0, len(tokens) - size + 1)):
            phrases.append(" ".join(tokens[index:index + size]))
    phrases.extend(tokens)
    return phrases

def _assign_confidence(ranked: list[RankedTarget]) -> None:
    if not ranked:
        return
    top = ranked[0].score
    second = ranked[1].score if len(ranked) > 1 else min(0.0, top - 400.0)
    margin = top - second
    for index, item in enumerate(ranked):
        if item.excluded:
            item.confidence = 0.0
            continue
        absolute = 1.0 / (1.0 + pow(2.718281828, -(item.score - 120.0) / 180.0))
        margin_factor = 1.0 / (1.0 + pow(2.718281828, -(margin if index == 0 else item.score - top) / 160.0))
        item.confidence = max(0.0, min(0.999, 0.68 * absolute + 0.32 * margin_factor))


def _attributions_from_signals(
    signals: list[EvidenceSignal],
    *,
    target: str,
    prompt: str,
    active_line: int | None = None,
) -> list[AttributionPath]:
    attributions: list[AttributionPath] = []
    for signal in sorted(signals, key=lambda item: abs(item.score), reverse=True):
        source = "project_index"
        kind = signal.key
        query_fragment = ""
        if signal.key.startswith("explicit"):
            source = "user_prompt"
            query_fragment = _best_prompt_fragment(prompt, signal.reason)
        elif signal.key in {"active_file", "open_file"}:
            source = "active_editor_context"
        elif signal.key == "active_cursor_line":
            source = "active_editor_context"
        elif signal.key == "context_momentum":
            source = "operation_memory"
        elif signal.key == "problem_semantics":
            source = "semantic_problem_formulation"
            query_fragment = _best_prompt_fragment(prompt, signal.reason)
        elif signal.key.endswith("penalty") or signal.score < 0:
            source = "disqualifier"
        attributions.append(
            AttributionPath(
                type=kind,
                source=source,
                evidence=target,
                weight=round(signal.score, 3),
                explanation=signal.reason,
                query_fragment=query_fragment,
                metadata={"line": active_line} if signal.key == "active_cursor_line" and active_line else {},
            )
        )
    return attributions


def _best_prompt_fragment(prompt: str, reason: str) -> str:
    prompt_text = str(prompt or "")
    reason_text = str(reason or "")
    quoted = re.findall(r"[:`] ?([^`.]+)", reason_text)
    for candidate in quoted:
        candidate = candidate.strip()
        if candidate and candidate.lower() in prompt_text.lower():
            return candidate
    words = re.findall(r"[A-Za-z0-9_]{3,}", prompt_text)
    return " ".join(words[:6])


def _is_excluded(path: str, explicit_files: list[TargetEntity]) -> tuple[bool, str]:
    norm_parts = {part.casefold() for part in re.split(r"[\\/]", path) if part}
    explicitly_named = any(Path(item.value).name.casefold() == Path(path).name.casefold() for item in explicit_files)
    if explicitly_named:
        return False, ""
    hard = norm_parts.intersection({part.casefold() for part in HARD_EXCLUDED_PARTS})
    if hard:
        return True, f"Excluded infrastructure path component: {sorted(hard)[0]}"
    soft = norm_parts.intersection({part.casefold() for part in SOFT_EXCLUDED_PARTS})
    if soft and Path(path).suffix.lower() not in SOURCE_SUFFIXES:
        return True, f"Excluded generated/metadata path component: {sorted(soft)[0]}"
    return False, ""


def _norm(value: str) -> str:
    return str(value or "").replace("\\", "/").rstrip("/")


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default
