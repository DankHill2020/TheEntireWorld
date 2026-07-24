"""Local code operation adapters used by prompt planning/execution."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_type_hints


DEFAULT_EXCLUDES = ("**/.*/**", "**/__pycache__/**", "**/*.sqlite", "**/*.sqlite-*")


def _ignore_disposable_copy(_directory: str, names: list[str]) -> set[str]:
    """Exclude local metadata, caches, and SQLite state from disposable copies."""
    return {
        name
        for name in names
        if name.startswith(".")
        or name == "__pycache__"
        or name.endswith((".sqlite", ".sqlite-shm", ".sqlite-wal"))
    }


def _result(**payload: Any) -> dict[str, Any]:
    return payload


def _iter_files(root: str | Path, file_globs: list[str] | None = None, exclude_globs: list[str] | None = None):
    base = Path(root or ".").resolve()
    globs = list(file_globs or ["*.py", "*.json", "*.md"])
    excludes = list(exclude_globs or DEFAULT_EXCLUDES)
    seen: set[Path] = set()
    for pattern in globs:
        for path in base.rglob(pattern):
            if path in seen or not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if any(path.match(pattern) or Path(rel).match(pattern) for pattern in excludes):
                continue
            seen.add(path)
            yield path


def search_project(
    root: str = ".",
    search_terms: list[str] | None = None,
    file_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    prompt: str = "",
    limit: int = 80,
) -> dict[str, Any]:
    """Search project files for prompt-derived terms and return target candidates."""
    terms = [str(term).strip() for term in search_terms or [] if str(term).strip()]
    if not terms and prompt:
        terms = [token for token in str(prompt).replace("_", " ").split() if len(token) > 3][:12]
    lowered = [term.lower() for term in terms]
    matches: list[dict[str, Any]] = []
    for path in _iter_files(root, file_globs, exclude_globs):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            matches.append({"path": str(path), "error": str(exc)})
            continue
        hay = text.lower()
        found = [term for term in lowered if term in hay]
        if found:
            matches.append({"path": str(path), "matched_terms": found[:12], "size": path.stat().st_size})
        if len(matches) >= int(limit):
            break
    return _result(ok=True, root=str(Path(root or ".").resolve()), search_terms=terms, matches=matches, count=len(matches))


def inspect_symbols(source_files: list[str] | str | None = None, symbol_queries: list[str] | None = None, **_: Any) -> dict[str, Any]:
    """Inspect Python symbols in candidate files without executing project code."""
    files = [source_files] if isinstance(source_files, str) else list(source_files or [])
    symbols: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for raw in files[:80]:
        path = Path(str(raw))
        if not path.exists() or path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append({
                    "path": str(path),
                    "name": node.name,
                    "kind": type(node).__name__,
                    "line": int(getattr(node, "lineno", 0) or 0),
                })
    return _result(ok=True, symbol_queries=list(symbol_queries or []), symbols=symbols, errors=errors, count=len(symbols))


def plan_patch(requested_behavior: str = "", target_files: list[str] | str | None = None, **_: Any) -> dict[str, Any]:
    files = [target_files] if isinstance(target_files, str) else list(target_files or [])
    return _result(
        ok=True,
        requested_behavior=requested_behavior,
        target_files=files,
        edit_policy="scoped_patch_only",
        rollback_policy="record changed files and validation commands before mutation",
        validation_commands=["python -m py_compile <changed python files>", "python -m unittest <focused tests>"],
    )


def plan_expected_code(
    requested_behavior: str = "",
    expected_files: list[dict[str, Any]] | None = None,
    expected_imports: list[str] | None = None,
    expected_classes: list[dict[str, Any]] | None = None,
    method_contracts: list[dict[str, Any]] | None = None,
    representative_code: str = "",
    integration_points: list[str] | None = None,
    repo_grounding: list[dict[str, Any]] | None = None,
    pre_patch_review: list[str] | None = None,
    acceptance_tests: list[dict[str, Any]] | None = None,
    quality_gates: list[dict[str, Any]] | None = None,
    quality_bar: dict[str, Any] | None = None,
    implementation_risks: list[dict[str, Any]] | None = None,
    readback_plan: list[str] | None = None,
) -> dict[str, Any]:
    files = list(expected_files or [])
    imports = list(expected_imports or [])
    classes = list(expected_classes or [])
    contracts = list(method_contracts or [])
    grounding = list(repo_grounding or [])
    review = list(pre_patch_review or [])
    tests = list(acceptance_tests or [])
    gates = list(quality_gates or [])
    bar = dict(quality_bar or {})
    risks = list(implementation_risks or [])
    readback = list(readback_plan or [])
    quality_score = 0
    quality_score += 1 if files else 0
    quality_score += 1 if imports else 0
    quality_score += 1 if classes else 0
    quality_score += 2 if contracts else 0
    quality_score += 2 if representative_code and ": ..." not in representative_code else 0
    quality_score += 1 if grounding else 0
    quality_score += 1 if review else 0
    quality_score += 2 if tests else 0
    quality_score += 2 if gates else 0
    quality_score += 1 if readback else 0
    readiness = "implementation_ready" if quality_score >= 12 else "planning_ready" if quality_score >= 7 else "outline_only"
    return _result(
        ok=True,
        requested_behavior=requested_behavior,
        expected_files=files,
        expected_imports=imports,
        expected_classes=classes,
        method_contracts=contracts,
        representative_code=representative_code,
        integration_points=list(integration_points or []),
        repo_grounding=grounding,
        pre_patch_review=review,
        acceptance_tests=tests,
        quality_gates=gates,
        quality_bar=bar,
        implementation_risks=risks,
        readback_plan=readback,
        quality_assessment={
            "score": quality_score,
            "max_score": 14,
            "readiness": readiness,
            "blocks_patch": readiness != "implementation_ready",
            "quality_bar_level": bar.get("current_level") or readiness,
            "missing": [
                name
                for name, present in (
                    ("expected_files", bool(files)),
                    ("expected_imports", bool(imports)),
                    ("expected_classes", bool(classes)),
                    ("method_contracts", bool(contracts)),
                    ("representative_code_without_placeholder_bodies", bool(representative_code and ": ..." not in representative_code)),
                    ("repo_grounding", bool(grounding)),
                    ("pre_patch_review", bool(review)),
                    ("acceptance_tests", bool(tests)),
                    ("quality_gates", bool(gates)),
                    ("readback_plan", bool(readback)),
                )
                if not present
            ],
        },
        status="expected_code_artifact_ready",
    )


def validate_expected_code(
    representative_code: str = "",
    expected_classes: list[dict[str, Any]] | None = None,
    method_contracts: list[dict[str, Any]] | None = None,
    quality_gates: list[dict[str, Any]] | None = None,
    acceptance_tests: list[dict[str, Any]] | None = None,
    executable_fixture_code: str = "",
    smoke_test_code: str = "",
    allow_exec: bool = False,
) -> dict[str, Any]:
    """Validate generated code intent before patching it into the project."""
    errors: list[str] = []
    warnings: list[str] = []
    discovered_classes: set[str] = set()
    discovered_functions: set[str] = set()
    try:
        tree = ast.parse(representative_code or "")
    except SyntaxError as exc:
        errors.append(f"syntax_error:{exc.msg}:line_{exc.lineno}")
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                discovered_classes.add(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                discovered_functions.add(node.name)

    if ": ..." in representative_code:
        errors.append("placeholder_method_body")
    expected_class_names = {str(item.get("name")) for item in expected_classes or [] if item.get("name")}
    missing_classes = sorted(expected_class_names - discovered_classes)
    if missing_classes:
        errors.append(f"missing_expected_classes:{','.join(missing_classes)}")
    if not method_contracts:
        errors.append("missing_method_contracts")
    if not quality_gates:
        errors.append("missing_quality_gates")
    if not acceptance_tests:
        errors.append("missing_acceptance_tests")

    smoke_result: dict[str, Any] | None = None
    if executable_fixture_code or smoke_test_code:
        if not allow_exec:
            warnings.append("smoke_test_not_executed_without_allow_exec")
        elif errors:
            warnings.append("smoke_test_skipped_due_to_static_errors")
        else:
            namespace: dict[str, Any] = {
                "__builtins__": {
                    "__build_class__": __build_class__,
                    "Exception": Exception,
                    "ValueError": ValueError,
                    "bool": bool,
                    "classmethod": classmethod,
                    "dict": dict,
                    "enumerate": enumerate,
                    "getattr": getattr,
                    "hasattr": hasattr,
                    "isinstance": isinstance,
                    "list": list,
                    "len": len,
                    "object": object,
                    "set": set,
                    "str": str,
                    "super": super,
                    "tuple": tuple,
                },
                "Any": Any,
                "__name__": "__main__",
                "dataclass": dataclass,
                "get_type_hints": get_type_hints,
                "json": json,
            }
            try:
                exec(executable_fixture_code, namespace, namespace)
                exec(representative_code, namespace, namespace)
                exec(smoke_test_code, namespace, namespace)
                smoke_result = {"ok": True}
            except Exception as exc:
                errors.append(f"smoke_test_failed:{type(exc).__name__}:{exc}")
                smoke_result = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}

    return _result(
        ok=not errors,
        status="expected_code_validation_passed" if not errors else "expected_code_validation_failed",
        errors=errors,
        warnings=warnings,
        discovered_classes=sorted(discovered_classes),
        discovered_functions=sorted(discovered_functions),
        expected_class_names=sorted(expected_class_names),
        quality_gates=list(quality_gates or []),
        acceptance_tests=list(acceptance_tests or []),
        smoke_result=smoke_result,
    )


def validate_patch_in_temp_workspace(
    source_root: str | Path = ".",
    expected_files: list[dict[str, Any]] | None = None,
    patch_files: list[dict[str, str]] | None = None,
    representative_code: str = "",
    module_prelude: str = "",
    validation_commands: list[list[str] | str] | None = None,
    copy_paths: list[str] | None = None,
    timeout_seconds: int = 30,
    keep_workspace: bool = True,
) -> dict[str, Any]:
    """Materialize a generated patch in a disposable workspace and validate it there."""
    root = Path(source_root or ".").resolve()
    temp_root = Path(tempfile.mkdtemp(prefix="tech_connector_patch_validation_"))
    copied: list[str] = []
    written: list[str] = []
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for raw in copy_paths or []:
        src = (root / raw).resolve()
        if not src.exists():
            continue
        try:
            src.relative_to(root)
        except ValueError:
            errors.append(f"copy_path_outside_root:{raw}")
            continue
        dst = temp_root / raw
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore_disposable_copy)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied.append(raw)

    materialized_files = list(patch_files or [])
    if not materialized_files and representative_code:
        candidates = [item.get("path") for item in expected_files or [] if str(item.get("path", "")).endswith(".py")]
        target = str(candidates[0] if candidates else "generated_patch_artifact.py")
        materialized_files = [{"path": target, "content": f"{module_prelude}{representative_code}"}]

    for item in materialized_files:
        raw_path = str(item.get("path") or "").strip()
        if not raw_path:
            errors.append("patch_file_missing_path")
            continue
        dst = (temp_root / raw_path).resolve()
        try:
            dst.relative_to(temp_root)
        except ValueError:
            errors.append(f"patch_file_outside_temp_workspace:{raw_path}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(str(item.get("content") or ""), encoding="utf-8")
        written.append(raw_path)

    commands = list(validation_commands or [])
    if not commands:
        py_files = [path for path in written if path.endswith(".py")]
        commands = [[sys.executable, "-m", "py_compile", *py_files]] if py_files else []

    if not errors:
        for command in commands:
            args = command if isinstance(command, list) else str(command).split()
            args = [
                str(value).replace("{workspace}", str(temp_root))
                for value in args
            ]
            if args and args[0] == "python":
                args = [sys.executable, *args[1:]]
            try:
                completed = subprocess.run(
                    args,
                    cwd=temp_root,
                    capture_output=True,
                    text=True,
                    timeout=max(1, int(timeout_seconds)),
                    check=False,
                )
                results.append({
                    "command": args,
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout[-12000:],
                    "stderr": completed.stderr[-12000:],
                })
                if completed.returncode != 0:
                    errors.append(f"validation_command_failed:{' '.join(args)}")
                elif len(args) >= 3 and args[1:3] == ["-m", "unittest"]:
                    output = "\n".join((completed.stdout, completed.stderr))
                    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
                    if match is None or int(match.group(1)) < 1:
                        errors.append(f"validation_command_ran_no_tests:{' '.join(args)}")
            except Exception as exc:
                errors.append(f"validation_command_error:{type(exc).__name__}:{exc}")
                results.append({"command": args, "exit_code": None, "error": str(exc), "error_type": type(exc).__name__})

    if not keep_workspace:
        shutil.rmtree(temp_root, ignore_errors=True)

    return _result(
        ok=not errors,
        status="temp_workspace_validation_passed" if not errors else "temp_workspace_validation_failed",
        source_root=str(root),
        temp_workspace=str(temp_root),
        copied=copied,
        written=written,
        commands=results,
        errors=errors,
        keep_workspace=keep_workspace,
    )


def validate_pipeline_prompt_in_temp_workspace(
    prompt: str,
    source_files: list[dict[str, str]] | None = None,
    expected_nodes: list[str] | None = None,
    timeout_seconds: int = 30,
    keep_workspace: bool = True,
) -> dict[str, Any]:
    """Validate prompt-to-pipeline creation in a disposable project root."""
    temp_root = Path(tempfile.mkdtemp(prefix="tech_connector_pipeline_validation_"))
    written: list[str] = []
    errors: list[str] = []
    graph: dict[str, Any] = {}
    materialized: dict[str, Any] = {}
    execution_order: list[str] = []
    warnings: list[str] = []
    try:
        for item in source_files or []:
            raw_path = str(item.get("path") or "").strip()
            if not raw_path:
                errors.append("source_file_missing_path")
                continue
            dst = (temp_root / raw_path).resolve()
            try:
                dst.relative_to(temp_root)
            except ValueError:
                errors.append(f"source_file_outside_temp_workspace:{raw_path}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(str(item.get("content") or ""), encoding="utf-8")
            written.append(raw_path)
        if not errors:
            from tech_connector.services.action_planner_service import plan_prompt_to_action_graph

            graph = plan_prompt_to_action_graph(prompt, [str(temp_root)])
            validation = graph.get("validation") or {}
            if validation and not validation.get("valid", False):
                errors.append("action_graph_validation_failed")
            action_nodes = [
                str(((action.get("args") or {}).get("symbol") or {}).get("name") or (action.get("args") or {}).get("node") or "")
                for action in graph.get("actions") or []
                if action.get("type") == "create_node"
            ]
            expected = list(expected_nodes or [])
            if expected and action_nodes != expected:
                errors.append(f"action_graph_node_order_mismatch:expected={expected}:actual={action_nodes}")
            try:
                os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
                from PySide6.QtWidgets import QApplication
                from tech_connector.ui.pipeline_node_view import PipelineNodeView

                app = QApplication.instance() or QApplication([])
                view = PipelineNodeView()
                materialized = view.materialize_action_graph(graph)
                execution_order = [
                    str(view.nodes[step_id].symbol.get("name") or "")
                    for step_id in view.execution_order()
                ]
                data_flow_errors = view.validate_data_flow()
                if not materialized.get("ok"):
                    errors.extend(str(item) for item in materialized.get("errors") or ["materialization_failed"])
                if data_flow_errors:
                    errors.extend(str(item.get("message") or item) for item in data_flow_errors)
                if expected and execution_order != expected:
                    errors.append(f"execution_order_mismatch:expected={expected}:actual={execution_order}")
                app.processEvents()
            except ModuleNotFoundError as exc:
                if exc.name == "PySide6":
                    warnings.append("node_view_materialization_skipped_pyside_unavailable")
                    materialized = {
                        "ok": True,
                        "status": "action_graph_validated_node_view_skipped",
                        "node_count": len(action_nodes),
                        "link_count": len([action for action in graph.get("actions") or [] if action.get("type") in {"connect_data", "connect_flow"}]),
                    }
                    execution_order = action_nodes
                else:
                    raise
    except Exception as exc:
        errors.append(f"pipeline_validation_error:{type(exc).__name__}:{exc}")
    finally:
        if not keep_workspace:
            shutil.rmtree(temp_root, ignore_errors=True)

    return _result(
        ok=not errors,
        status="pipeline_temp_validation_passed" if not errors else "pipeline_temp_validation_failed",
        temp_workspace=str(temp_root),
        written=written,
        errors=errors,
        warnings=warnings,
        graph_intent=graph.get("intent", ""),
        graph_action_types=[action.get("type") for action in graph.get("actions") or []],
        node_count=int(materialized.get("node_count") or 0),
        link_count=int(materialized.get("link_count") or 0),
        execution_order=execution_order,
        materialized=materialized,
        keep_workspace=keep_workspace,
        timeout_seconds=timeout_seconds,
    )


def apply_patch(patch_source: str | dict[str, Any] = "", mechanism: str = "apply_patch", **_: Any) -> dict[str, Any]:
    return _result(
        ok=False,
        status="requires_agent_patch_application",
        mechanism=mechanism,
        patch_source_type=type(patch_source).__name__,
        reason="Patch application is performed by the agent/editor transaction layer so user-owned changes and approvals stay visible.",
    )


def update_tests(test_targets: list[str] | str | None = None, assertions: list[str] | None = None, **_: Any) -> dict[str, Any]:
    targets = [test_targets] if isinstance(test_targets, str) else list(test_targets or [])
    return _result(ok=True, test_targets=targets, assertions=list(assertions or []), status="test_update_plan_ready")


def run_tests(commands: list[str] | None = None, **_: Any) -> dict[str, Any]:
    return _result(
        ok=False,
        status="requires_supervised_command_execution",
        commands=list(commands or []),
        reason="Test execution must run through the terminal/execution supervisor to capture exit codes and avoid hidden side effects.",
    )


def as_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)
