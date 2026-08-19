"""Deterministic grading for isolated code-agent attempts."""

from __future__ import annotations

import ast
import difflib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from .models import AgentRun, BenchmarkCase, Score


def materialize_case(case: BenchmarkCase, workspace: Path) -> dict[str, str]:
    """Create a clean seed workspace and return its text snapshot.

    :param case: Benchmark case to materialize.
    :param workspace: Empty destination directory.
    :return: Relative-path to initial-content snapshot.
    """

    workspace.mkdir(parents=True, exist_ok=False)
    for relative_path, content in case.seed_files.items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return snapshot_workspace(workspace)


def snapshot_workspace(workspace: Path) -> dict[str, str]:
    """Capture source text while excluding agent and VCS runtime state.

    :param workspace: Workspace to snapshot.
    :return: Relative-path to source-content mapping.
    """

    snapshot: dict[str, str] = {}
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace)
        if any(
            part in {".git", ".tech_connector", "__pycache__", ".pytest_cache"}
            for part in relative.parts
        ):
            continue
        try:
            snapshot[relative.as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            snapshot[relative.as_posix()] = "<binary>"
    return snapshot


def _patch_measurements(
    before: dict[str, str],
    after: dict[str, str],
) -> tuple[list[str], int, int]:
    """Measure changed files and line additions/removals.

    :param before: Seed snapshot.
    :param after: Post-agent snapshot.
    :return: Changed files, added lines, and removed lines.
    """

    changed = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    added = 0
    removed = 0
    for path in changed:
        matcher = difflib.SequenceMatcher(
            a=before.get(path, "").splitlines(),
            b=after.get(path, "").splitlines(),
        )
        for tag, first_start, first_end, second_start, second_end in matcher.get_opcodes():
            if tag in {"replace", "delete"}:
                removed += first_end - first_start
            if tag in {"replace", "insert"}:
                added += second_end - second_start
    return changed, added, removed


def _syntax_ok(workspace: Path) -> tuple[bool, str]:
    """Parse every Python source file in the solution workspace.

    :param workspace: Completed solution workspace.
    :return: Success flag and optional syntax error.
    """

    for path in workspace.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            return False, f"{path.relative_to(workspace).as_posix()}: {exc}"
    return True, ""


def _source_quality_issues(
    workspace: Path,
    changed_paths: list[str],
) -> list[str]:
    """Return deterministic maintainability defects in changed Python files.

    :param workspace: completed isolated workspace
    :param changed_paths: relative paths changed by the agent
    :return: stable quality issue descriptions
    """

    issues: list[str] = []
    generic_docstring_patterns = (
        r"\bresult\s+result\b",
        r"(?im)^\s*:return:\s*(?:the\s+)?(?:concrete\s+)?result\.?\s*$",
        r"\bprovide [a-z0-9_ ]+ behavior\b",
        r"\bcompute and return the [a-z0-9_ ]+ result\b",
        r"\bapply [a-z0-9_ ]+ and update only its documented state\b",
        r"\breturn operation for\b",
        r"\bstore validated [-a-z0-9_ ]+ state and expose\b",
    )
    for relative_path in changed_paths:
        if not relative_path.endswith(".py"):
            continue
        path = workspace / relative_path
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_path)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(source.splitlines(), start=1):
            if len(line) > 100 and not line.lstrip().startswith("#"):
                issues.append(
                    f"{relative_path}:{line_number}: line exceeds 100 characters"
                )
        for owner_name, owner in [
            ("<module>", tree),
            *(
                (node.name, node)
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)
            ),
        ]:
            for index, statement in enumerate(owner.body):
                if (
                    index > 0
                    and isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                ):
                    issues.append(
                        f"{relative_path}:{owner_name}: displaced string literal"
                    )
        parent_by_node = {
            id(child): parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }

        def is_instance_lock(node: ast.AST) -> bool:
            return (
                isinstance(node, (ast.With, ast.AsyncWith))
                and len(node.items) == 1
                and isinstance(node.items[0].context_expr, ast.Attribute)
                and isinstance(node.items[0].context_expr.value, ast.Name)
                and node.items[0].context_expr.value.id == "self"
                and node.items[0].context_expr.attr == "_lock"
            )

        for node in ast.walk(tree):
            if not is_instance_lock(node):
                continue
            parent = parent_by_node.get(id(node))
            while parent is not None:
                if is_instance_lock(parent):
                    issues.append(
                        f"{relative_path}: nested redundant self._lock context"
                    )
                    break
                if isinstance(
                    parent,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                        ast.ClassDef,
                        ast.Module,
                    ),
                ):
                    break
                parent = parent_by_node.get(id(parent))
        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            if node.name.startswith("_") and node.name != "__init__":
                continue
            docstring = str(ast.get_docstring(node) or "")
            if not docstring:
                issues.append(f"{relative_path}:{node.name}: missing docstring")
                continue
            if any(
                re.search(pattern, docstring, flags=re.IGNORECASE)
                for pattern in generic_docstring_patterns
            ):
                issues.append(f"{relative_path}:{node.name}: generic docstring")
                continue
            summary = re.split(
                r"(?m)^\s*:(?:param|return|returns|raise|raises|type)\b",
                docstring,
                maxsplit=1,
            )[0].strip()
            words = re.findall(r"[A-Za-z0-9]+", summary)
            name_words = {
                word.casefold()
                for word in re.findall(
                    r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+",
                    node.name,
                )
            }
            meaningful = {
                word.casefold()
                for word in words
                if word.casefold() not in name_words
            }
            if len(words) < 5 or len(meaningful) < 2:
                issues.append(f"{relative_path}:{node.name}: vague docstring")
    return sorted(set(issues))


def score_attempt(
    case: BenchmarkCase,
    run: AgentRun,
    workspace: Path,
    attempt_dir: Path,
    before: dict[str, str],
) -> Score:
    """Grade one attempt with hidden behavior, syntax, and scope checks.

    :param case: Benchmark case definition.
    :param run: Agent execution record.
    :param workspace: Completed isolated workspace.
    :param attempt_dir: Directory for evaluator artifacts.
    :param before: Seed source snapshot.
    :return: Deterministic score.
    """

    after = snapshot_workspace(workspace)
    changed, added, removed = _patch_measurements(before, after)
    allowed = set(case.allowed_paths)
    out_of_scope = sorted(path for path in changed if path not in allowed)
    syntax_ok, syntax_error = _syntax_ok(workspace)
    evaluator_path = attempt_dir / "hidden_evaluator.py"
    evaluator_path.write_text(case.evaluator_source, encoding="utf-8")
    evaluator_started = time.perf_counter()
    evaluator_output = ""
    passed = 0
    total = case.assertion_count
    try:
        completed = subprocess.run(
            [sys.executable, str(evaluator_path), str(workspace)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        evaluator_output = (completed.stdout + completed.stderr).strip()
        for line in reversed(completed.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            passed = int(payload.get("passed") or 0)
            total = int(payload.get("total") or total)
            break
    except subprocess.TimeoutExpired:
        evaluator_output = "Hidden evaluator timed out after 20 seconds."
    if syntax_error:
        evaluator_output = (evaluator_output + "\n" + syntax_error).strip()

    quality_issues = _source_quality_issues(workspace, changed)
    behavior_points = round(60.0 * passed / max(1, total), 3)
    quality_points = 10.0 if not quality_issues else 0.0
    syntax_points = 10.0 if syntax_ok else 0.0
    scope_points = 10.0 if not out_of_scope else 0.0
    completed_status = run.status in {"ok", "preview_ok"}
    completion_points = (
        10.0
        if changed and not run.timed_out and completed_status
        else 5.0
        if changed
        else 0.0
    )
    total_points = round(
        behavior_points
        + quality_points
        + syntax_points
        + scope_points
        + completion_points,
        3,
    )
    score = Score(
        behavior_points=behavior_points,
        quality_points=quality_points,
        syntax_points=syntax_points,
        scope_points=scope_points,
        completion_points=completion_points,
        total_points=total_points,
        assertions_passed=passed,
        assertions_total=total,
        syntax_ok=syntax_ok,
        changed_files=changed,
        out_of_scope_files=out_of_scope,
        lines_added=added,
        lines_removed=removed,
        evaluator_seconds=round(time.perf_counter() - evaluator_started, 6),
        evaluator_output=evaluator_output[-4000:],
        quality_issues=quality_issues,
    )
    (attempt_dir / "score.json").write_text(
        json.dumps(score.to_dict(), indent=2), encoding="utf-8"
    )
    return score
