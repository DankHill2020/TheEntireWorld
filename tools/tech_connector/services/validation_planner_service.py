"""Validation planning for deterministic code-agent edits."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationStep:
    command: str
    reason: str
    paths: tuple[str, ...] = field(default_factory=tuple)
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "reason": self.reason,
            "paths": list(self.paths),
            "required": self.required,
        }


def plan_validation_for_paths(
    paths: list[str] | tuple[str, ...],
    *,
    project_root: str | None = None,
) -> list[dict[str, Any]]:
    """Return small, evidence-driven checks for changed or inspected files."""

    normalized = [_normalize_path(path) for path in paths if str(path or "").strip()]
    steps: list[ValidationStep] = []
    py_files = [path for path in normalized if path.lower().endswith(".py")]
    if py_files:
        for path in py_files:
            steps.append(
                ValidationStep(
                    command=f"py_compile {Path(path).name}",
                    reason="Python syntax must pass for every modified Python file.",
                    paths=(path,),
                )
            )
        test_candidates = _matching_test_files(py_files, project_root=project_root)
        for test_path in test_candidates[:6]:
            test_file = Path(test_path)
            steps.append(
                ValidationStep(
                    command=f"python -m unittest discover -s {test_file.parent} -p {test_file.name}",
                    reason="A nearby focused test exists for the changed code.",
                    paths=(test_path,),
                    required=False,
                )
            )
    non_python = [path for path in normalized if path and not path.lower().endswith(".py")]
    if non_python:
        steps.append(
            ValidationStep(
                command="manual/runtime validation",
                reason="Non-Python assets need host or application-specific validation.",
                paths=tuple(non_python[:10]),
                required=False,
            )
        )
    return [step.to_dict() for step in _dedupe_steps(steps)]


def render_validation_plan(steps: list[dict[str, Any]] | None) -> str:
    steps = list(steps or [])
    if not steps:
        return "Validation plan: no concrete changed files yet; determine targets before selecting checks."
    lines = ["Validation plan:"]
    for index, step in enumerate(steps, 1):
        required = "required" if step.get("required", True) else "recommended"
        paths = ", ".join(Path(path).name for path in step.get("paths") or [])
        suffix = f" ({paths})" if paths else ""
        lines.append(f"{index}. {step.get('command')} - {required} - {step.get('reason')}{suffix}")
    return "\n".join(lines)


def _normalize_path(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path or "")


def _matching_test_files(py_files: list[str], *, project_root: str | None = None) -> list[str]:
    roots: list[Path] = []
    if project_root:
        roots.append(Path(project_root))
    for path in py_files:
        try:
            roots.extend(Path(path).resolve().parents[:4])
        except Exception:
            continue
    out: list[str] = []
    seen_roots: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen_roots or not root.exists():
            continue
        seen_roots.add(key)
        test_dirs = [root / "tests", root / "examples" / "tech_connector" / "tests"]
        names = {Path(path).stem for path in py_files}
        for tests_dir in test_dirs:
            if not tests_dir.exists():
                continue
            for test_file in tests_dir.glob("test_*.py"):
                stem = test_file.stem.lower()
                if any(name.lower() in stem or stem in f"test_{name.lower()}" for name in names):
                    out.append(str(test_file.resolve()))
    return sorted(set(out))


def _dedupe_steps(steps: list[ValidationStep]) -> list[ValidationStep]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    out: list[ValidationStep] = []
    for step in steps:
        key = (step.command, step.paths)
        if key in seen:
            continue
        seen.add(key)
        out.append(step)
    return out
