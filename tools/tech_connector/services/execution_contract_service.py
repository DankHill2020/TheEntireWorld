from __future__ import annotations

"""User-intent scope contracts and post-execution scope enforcement.

The contract is deliberately deterministic. It captures what the user asked for,
what the system may change at most, and when execution must stop. This prevents a
capability such as "add docstrings" from widening a one-function request into a
whole-file rewrite.
"""

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Iterable


SCOPE_RANK = {
    "read_only": 0,
    "exact_target": 1,
    "local_region": 2,
    "file": 3,
    "module": 4,
    "project": 5,
    "cross_project": 6,
}


@dataclass
class ExecutionContract:
    goal: str
    operation: str = "unknown"
    scope: str = "exact_target"
    read_only: bool = False
    mutation_requested: bool = False
    max_files: int = 1
    max_symbols: int = 1
    max_edits: int = 1
    max_new_files: int = 0
    allowed_paths: list[str] = field(default_factory=list)
    allowed_symbols: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    forbidden_expansions: list[str] = field(default_factory=list)
    ambiguity_reasons: list[str] = field(default_factory=list)
    requires_clarification: bool = False
    confidence: float = 0.7
    reasons: list[str] = field(default_factory=list)

    def normalize(self) -> None:
        if self.scope not in SCOPE_RANK:
            self.scope = "exact_target"
        self.max_files = max(0, int(self.max_files))
        self.max_symbols = max(0, int(self.max_symbols))
        self.max_edits = max(0, int(self.max_edits))
        self.max_new_files = max(0, int(self.max_new_files))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.read_only:
            self.mutation_requested = False
            self.max_files = 0
            self.max_symbols = 0
            self.max_edits = 0
            self.max_new_files = 0

    def to_dict(self) -> dict[str, Any]:
        self.normalize()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionContract":
        obj = cls(**dict(data or {}))
        obj.normalize()
        return obj


@dataclass
class ScopeObservation:
    files_touched: list[str] = field(default_factory=list)
    symbols_touched: list[str] = field(default_factory=list)
    edit_count: int = 0
    new_files: list[str] = field(default_factory=list)
    operation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScopeCheckResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_execution_contract(
    prompt: str,
    *,
    active_file: str = "",
    selected_symbol: str = "",
    route_decision: dict[str, Any] | None = None,
) -> ExecutionContract:
    route_decision = dict(route_decision or {})
    raw = prompt or ""
    lower = re.sub(r"\s+", " ", raw.lower()).strip()
    read_only = bool(re.search(r"\b(do not edit|don't edit|no edits|read[- ]only|inspect only|plan only|explain only|report only)\b", lower))
    mutation = not read_only and bool(re.search(r"\b(add|create|write|implement|insert|modify|change|update|fix|patch|repair|refactor|wire|connect|remove|delete)\b", lower))
    operation = _infer_operation(lower)

    scope = "exact_target"
    max_files, max_symbols, max_edits, max_new_files = 1, 1, 1, 0
    reasons: list[str] = []
    expected_outputs: list[str] = []
    stop_conditions: list[str] = []
    forbidden: list[str] = []

    exact_count = _requested_count(lower)
    if exact_count is not None:
        max_symbols = max(1, exact_count)
        max_edits = max(1, exact_count)
        reasons.append(f"Explicit requested count={exact_count}.")

    if re.search(r"\b(first|one|single|only this|this function|this method|selected function|current function)\b", lower):
        scope = "exact_target"
        max_files, max_symbols, max_edits = 1, exact_count or 1, exact_count or 1
        forbidden.append("Do not apply the same capability to additional symbols after the requested target succeeds.")
        stop_conditions.append("Stop immediately after the requested target count has been completed and validated.")
        reasons.append("Prompt contains an exact/single-target limiter.")
    elif re.search(r"\b(selection|selected lines|selected code|this block|this section|nearby)\b", lower):
        scope = "local_region"
        max_files, max_symbols, max_edits = 1, max(1, exact_count or 3), max(1, exact_count or 3)
        reasons.append("Prompt is limited to a selected/local code region.")
    elif re.search(r"\b(this file|current file|active file|in the file)\b", lower):
        scope = "file"
        max_files, max_symbols, max_edits = 1, 200, 200
        reasons.append("Prompt explicitly allows file scope.")
    elif re.search(r"\b(module|package|folder|directory)\b", lower):
        scope = "module"
        max_files, max_symbols, max_edits = 12, 500, 500
        reasons.append("Prompt explicitly allows module/folder scope.")
    elif re.search(r"\b(entire project|whole project|across the project|all files|every file|project-wide)\b", lower):
        scope = "project"
        max_files, max_symbols, max_edits = 10_000, 100_000, 100_000
        reasons.append("Prompt explicitly requests project-wide scope.")
    elif route_decision.get("mutation_scope") in {"project", "project_wide"}:
        scope = "project"
        max_files, max_symbols, max_edits = 10_000, 100_000, 100_000
        reasons.append("Route decision explicitly requests project scope.")

    if read_only:
        scope = "read_only"
        max_files = max_symbols = max_edits = max_new_files = 0
        stop_conditions.append("Stop after returning evidence-backed findings; do not mutate files or host state.")
    elif mutation:
        expected_outputs.append("A previewable, reversible change within the declared scope.")
        expected_outputs.append("Validation strategy and test execution evidence (commands + observed result) for requested behavior.")
        stop_conditions.append("Stop if the target is ambiguous or the requested scope cannot be honored safely.")
        stop_conditions.append("Stop after required validation passes for the allowed changes.")

    if operation == "docstring":
        expected_outputs.append("Docstring changes only; executable behavior must remain unchanged.")
        forbidden.extend([
            "Do not reformat unrelated code.",
            "Do not repair other docstrings unless the prompt explicitly requests it.",
        ])

    allowed_paths = [active_file] if active_file else []
    allowed_symbols = [selected_symbol] if selected_symbol else []
    ambiguity: list[str] = []
    requires_clarification = False
    if mutation and scope in {"exact_target", "local_region"} and not (active_file or selected_symbol):
        # A prompt such as "first function you find" is executable only when a deterministic
        # selector exists. It does not require asking the user, but the selector is part of the contract.
        if re.search(r"\b(first|next)\b", lower):
            expected_outputs.append("Deterministically select the first matching target in source order, then stop.")
            reasons.append("Prompt defines a deterministic first-match selector.")
        elif not re.search(r"\b(this|selected|current)\b", lower):
            ambiguity.append("No exact file or symbol target was resolved.")
            requires_clarification = True

    confidence = 0.94 if read_only or re.search(r"\b(first|one|single|only this|this file|entire project)\b", lower) else 0.78
    contract = ExecutionContract(
        goal=_normalize_goal(raw),
        operation=operation,
        scope=scope,
        read_only=read_only,
        mutation_requested=mutation,
        max_files=max_files,
        max_symbols=max_symbols,
        max_edits=max_edits,
        max_new_files=max_new_files,
        allowed_paths=allowed_paths,
        allowed_symbols=allowed_symbols,
        expected_outputs=expected_outputs,
        stop_conditions=stop_conditions,
        forbidden_expansions=forbidden,
        ambiguity_reasons=ambiguity,
        requires_clarification=requires_clarification,
        confidence=confidence,
        reasons=reasons,
    )
    contract.normalize()
    return contract


def check_scope(contract: ExecutionContract | dict[str, Any], observation: ScopeObservation | dict[str, Any]) -> ScopeCheckResult:
    c = contract if isinstance(contract, ExecutionContract) else ExecutionContract.from_dict(contract)
    o = observation if isinstance(observation, ScopeObservation) else ScopeObservation(**dict(observation or {}))
    violations: list[str] = []
    warnings: list[str] = []
    files = list(dict.fromkeys(str(path) for path in o.files_touched if path))
    symbols = list(dict.fromkeys(str(name) for name in o.symbols_touched if name))
    new_files = list(dict.fromkeys(str(path) for path in o.new_files if path))
    if c.read_only and (files or symbols or o.edit_count or new_files):
        violations.append("Read-only contract was violated by a mutation.")
    if len(files) > c.max_files:
        violations.append(f"Files touched exceeded contract: {len(files)} > {c.max_files}.")
    if len(symbols) > c.max_symbols:
        violations.append(f"Symbols touched exceeded contract: {len(symbols)} > {c.max_symbols}.")
    if int(o.edit_count) > c.max_edits:
        violations.append(f"Edit count exceeded contract: {int(o.edit_count)} > {c.max_edits}.")
    if len(new_files) > c.max_new_files:
        violations.append(f"New files exceeded contract: {len(new_files)} > {c.max_new_files}.")
    if c.allowed_paths:
        allowed = {_norm(path) for path in c.allowed_paths}
        outside = [path for path in files if _norm(path) not in allowed]
        if outside:
            violations.append("Changes touched paths outside the allowed target set: " + ", ".join(outside))
    if c.allowed_symbols:
        allowed_symbols = {name.lower() for name in c.allowed_symbols}
        outside_symbols = [name for name in symbols if name.lower() not in allowed_symbols]
        if outside_symbols:
            violations.append("Changes touched symbols outside the allowed target set: " + ", ".join(outside_symbols))
    if not symbols and c.mutation_requested and c.scope == "exact_target":
        warnings.append("Exact-target mutation did not report the affected symbol; scope proof is incomplete.")
    return ScopeCheckResult(
        ok=not violations,
        violations=violations,
        warnings=warnings,
        expected={
            "scope": c.scope,
            "max_files": c.max_files,
            "max_symbols": c.max_symbols,
            "max_edits": c.max_edits,
            "max_new_files": c.max_new_files,
        },
        actual=o.to_dict(),
    )


def render_execution_contract(contract: ExecutionContract | dict[str, Any]) -> str:
    c = contract if isinstance(contract, ExecutionContract) else ExecutionContract.from_dict(contract)
    lines = [
        "Execution contract:",
        f"- Goal: {c.goal}",
        f"- Operation: {c.operation}",
        f"- Scope: {c.scope}",
        f"- Maximum impact: files={c.max_files}, symbols={c.max_symbols}, edits={c.max_edits}, new_files={c.max_new_files}",
    ]
    if c.expected_outputs:
        lines.append("- Expected output: " + " | ".join(c.expected_outputs[:3]))
    if c.stop_conditions:
        lines.append("- Stop conditions: " + " | ".join(c.stop_conditions[:3]))
    if c.forbidden_expansions:
        lines.append("- Scope guards: " + " | ".join(c.forbidden_expansions[:3]))
    return "\n".join(lines)


def _requested_count(lower: str) -> int | None:
    match = re.search(r"\b(?:first|only|exactly)\s+(\d+)\b", lower)
    if match:
        return int(match.group(1))
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    for word, count in words.items():
        if re.search(rf"\b(?:first|only|exactly)?\s*{word}\b", lower):
            return count
    return None


def _infer_operation(lower: str) -> str:
    if "docstring" in lower or "function documentation" in lower:
        return "docstring"
    if re.search(r"\b(rename|renaming)\b", lower):
        return "rename"
    if re.search(r"\b(fix|repair|debug)\b", lower):
        return "repair"
    if re.search(r"\b(refactor)\b", lower):
        return "refactor"
    if re.search(r"\b(add|create|implement|build)\b", lower):
        return "create_or_extend"
    if re.search(r"\b(find|search|show|list|inspect|explain|what|which|where)\b", lower):
        return "inspect"
    return "unknown"


def _normalize_goal(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt or "").strip()


def _norm(path: str) -> str:
    return str(path or "").replace("\\", "/").rstrip("/").lower()
