from __future__ import annotations

"""Transparent weighted evidence ranking for project targets."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Iterable

from services.context_momentum_service import ContextMomentum
from services.target_entity_service import TargetEntity, extract_target_entities


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
class RankedTarget:
    path: str
    score: float
    confidence: float
    signals: list[EvidenceSignal] = field(default_factory=list)
    excluded: bool = False
    exclusion_reason: str = ""
    original: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 4),
            "signals": [item.to_dict() for item in self.signals],
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
            "original": self.original,
        }


def rank_target_candidates(
    prompt: str,
    candidates: Iterable[dict[str, Any] | str],
    *,
    active_file: str = "",
    open_files: Iterable[str] = (),
    momentum: ContextMomentum | None = None,
    allowed_roots: Iterable[str] = (),
) -> list[RankedTarget]:
    entities = extract_target_entities(prompt)
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

        if active_norm and norm_lower == active_norm:
            score += 360.0
            signals.append(EvidenceSignal("active_file", 360.0, "Candidate is the active editor file."))
        if norm_lower in open_set:
            score += 240.0
            signals.append(EvidenceSignal("open_file", 240.0, "Candidate is open in the editor."))

        momentum_bonus, momentum_reasons = momentum.score_bonus(path, "file")
        if momentum_bonus:
            score += momentum_bonus
            signals.append(EvidenceSignal("context_momentum", momentum_bonus, "; ".join(momentum_reasons)))

        if p.suffix.lower() in SOURCE_SUFFIXES:
            score += 110.0
            signals.append(EvidenceSignal("source_file", 110.0, f"Candidate is editable source ({p.suffix.lower()})."))
        elif p.suffix.lower() in {".json", ".sqlite", ".db", ".log", ".txt"}:
            score -= 180.0
            signals.append(EvidenceSignal("metadata_penalty", -180.0, f"Candidate is usually metadata/data ({p.suffix.lower()})."))

        if p.name.casefold() in METADATA_FILENAMES:
            score -= 800.0
            signals.append(EvidenceSignal("index_metadata_penalty", -800.0, "Known generated/index metadata filename."))

        if roots and not any(norm_lower == root or norm_lower.startswith(root + "/") for root in roots):
            score -= 250.0
            signals.append(EvidenceSignal("outside_project_root", -250.0, "Candidate is outside the active project roots."))

        # Existing search score is supporting evidence, not the authority.
        raw_score = _float(data.get("score"), 0.0)
        if raw_score:
            contribution = min(120.0, max(-120.0, raw_score * 12.0))
            score += contribution
            signals.append(EvidenceSignal("provider_score", contribution, f"Underlying provider score={raw_score:.3f}."))

        text_blob = " ".join(str(data.get(key) or "") for key in ("name", "symbol", "summary", "text", "reason")).casefold()
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

        ranked.append(RankedTarget(path=path, score=score, confidence=0.0, signals=signals, excluded=excluded, exclusion_reason=exclusion_reason, original=data))

    ranked.sort(key=lambda item: item.score, reverse=True)
    _assign_confidence(ranked)
    return ranked


def target_resolution_summary(ranked: list[RankedTarget], *, max_items: int = 5) -> str:
    if not ranked:
        return "No target candidates were available."
    lines = ["Target evidence ranking:"]
    for index, item in enumerate(ranked[:max_items], 1):
        lines.append(f"{index}. {item.path} score={item.score:.1f} confidence={item.confidence:.3f}")
        for signal in sorted(item.signals, key=lambda s: abs(s.score), reverse=True)[:5]:
            lines.append(f"   {signal.score:+.1f} {signal.reason}")
    return "\n".join(lines)


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
