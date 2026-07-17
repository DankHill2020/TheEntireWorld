from __future__ import annotations

"""Deterministic project-validation intents and early-exit syntax scanning."""

from dataclasses import asdict, dataclass
from pathlib import Path
import ast
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class ValidationIntent:
    kind: str
    stop_after: int | None = None
    scope: str = "project"
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_validation_intent(prompt: str) -> ValidationIntent | None:
    lower = re.sub(r"\s+", " ", prompt or "").lower()
    if re.search(r"\b(syntax error|syntax errors|parse error|compile error)\b", lower) and re.search(r"\b(find|identify|locate|check|scan|report)\b", lower):
        stop_after = 1 if re.search(r"\b(first|stop immediately|only one|one issue)\b", lower) else None
        scope = "file" if re.search(r"\b(this file|current file|active file)\b", lower) else "project"
        return ValidationIntent("python_syntax_audit", stop_after=stop_after, scope=scope, confidence=0.97, reason="Prompt requests computed syntax evidence, not textual index matches.")
    return None


def find_python_syntax_errors(
    roots_or_files: Iterable[str],
    *,
    stop_after: int | None = None,
    excluded_dirs: Iterable[str] = (".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"),
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    excluded = {item.casefold() for item in excluded_dirs}
    for path in _iter_python_files(roots_or_files, excluded):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            errors.append(
                {
                    "ok": False,
                    "kind": "python_syntax_error",
                    "path": str(path),
                    "line": int(exc.lineno or 0),
                    "offset": int(exc.offset or 0),
                    "message": str(exc.msg or exc),
                    "text": str(exc.text or "").rstrip(),
                }
            )
            if stop_after and len(errors) >= stop_after:
                break
        except OSError as exc:
            errors.append({"ok": False, "kind": "file_read_error", "path": str(path), "line": 0, "offset": 0, "message": str(exc), "text": ""})
            if stop_after and len(errors) >= stop_after:
                break
    return errors


def run_validation_intent(intent: ValidationIntent, *, project_roots: Iterable[str], active_file: str = "") -> dict[str, Any]:
    targets = [active_file] if intent.scope == "file" and active_file else list(project_roots)
    errors = find_python_syntax_errors(targets, stop_after=intent.stop_after)
    return {
        "ok": not errors,
        "status": "no_syntax_errors" if not errors else "syntax_error_found",
        "intent": intent.to_dict(),
        "issues": errors,
        "stopped_early": bool(intent.stop_after and len(errors) >= intent.stop_after),
        "files_or_roots_checked": targets,
    }


def _iter_python_files(values: Iterable[str], excluded: set[str]):
    seen: set[str] = set()
    for raw in values:
        path = Path(raw)
        if path.is_file() and path.suffix.lower() == ".py":
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                yield path
            continue
        if not path.is_dir():
            continue
        for candidate in path.rglob("*.py"):
            if any(part.casefold() in excluded for part in candidate.parts):
                continue
            key = str(candidate.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield candidate
