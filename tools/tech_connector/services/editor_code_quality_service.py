"""Lightweight editor diagnostics and formatting helpers.

The service prefers project-standard tools when they are installed, but keeps a
stdlib fallback so the editor still gives useful guidance in packaged builds.
"""

from __future__ import annotations

import ast
import builtins
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PYTHON_BUILTINS = set(dir(builtins))


@dataclass(frozen=True)
class EditorDiagnostic:
    line: int
    column: int
    severity: str
    code: str
    message: str
    fixable: bool = False

    def display_text(self) -> str:
        location = f"{max(1, self.line)}:{max(1, self.column)}"
        fix = "  [fixable]" if self.fixable else ""
        return f"{self.severity.upper()} {location} {self.code}: {self.message}{fix}"


def project_quality_config_path() -> str:
    config = Path(__file__).resolve().parents[1] / "config" / "pyproject.toml"
    return str(config) if config.exists() else ""


def python_quality_diagnostics(source: str, path: str = "") -> list[EditorDiagnostic]:
    diagnostics: list[EditorDiagnostic] = []
    diagnostics.extend(_syntax_diagnostics(source, path))
    diagnostics.extend(_fallback_style_diagnostics(source))
    diagnostics.extend(_ruff_diagnostics(source, path))
    diagnostics.sort(key=lambda item: (item.line, item.column, item.severity, item.code))
    return _dedupe_diagnostics(diagnostics)


def reformat_python_source(source: str, path: str = "") -> tuple[str, list[str]]:
    formatted, messages = _black_format_source(source, path)
    if formatted is not None:
        return formatted, messages
    return _fallback_reformat_source(source), [
        "Black is not available; applied whitespace cleanup, tab expansion, and final newline normalization."
    ]


def fix_python_quality_issues(source: str, path: str = "") -> tuple[str, list[str]]:
    fixed, messages = _ruff_fix_source(source, path)
    if fixed is not None:
        return fixed, messages
    formatted, format_messages = reformat_python_source(source, path)
    safer = _fallback_safe_fixes(formatted)
    return safer, ["Ruff is not available; applied safe fallback fixes only."] + format_messages


def _syntax_diagnostics(source: str, path: str) -> list[EditorDiagnostic]:
    try:
        compile(source, path or "<editor>", "exec")
    except SyntaxError as exc:
        return [
            EditorDiagnostic(
                line=int(exc.lineno or 1),
                column=int(exc.offset or 1),
                severity="error",
                code="PY-SYNTAX",
                message=str(exc.msg or "Syntax error"),
                fixable=False,
            )
        ]
    except Exception as exc:
        return [
            EditorDiagnostic(
                line=1,
                column=1,
                severity="error",
                code="PY-CHECK",
                message=str(exc),
                fixable=False,
            )
        ]
    return []


def _fallback_style_diagnostics(source: str) -> list[EditorDiagnostic]:
    diagnostics: list[EditorDiagnostic] = []
    lines = source.splitlines()
    for index, line in enumerate(lines, start=1):
        if line.rstrip(" \t") != line:
            diagnostics.append(
                EditorDiagnostic(index, len(line.rstrip(" \t")) + 1, "warning", "W291", "Trailing whitespace.", True)
            )
        if "\t" in line:
            diagnostics.append(
                EditorDiagnostic(index, line.index("\t") + 1, "warning", "W191", "Tab indentation; use spaces.", True)
            )
        if len(line) > 100:
            diagnostics.append(
                EditorDiagnostic(index, 101, "weak warning", "E501", "Line exceeds 100 characters.", False)
            )
        leading = line[: len(line) - len(line.lstrip(" \t"))]
        if " " in leading and "\t" in leading:
            diagnostics.append(
                EditorDiagnostic(index, 1, "warning", "E101", "Mixed spaces and tabs in indentation.", True)
            )
    if source and not source.endswith("\n"):
        diagnostics.append(
            EditorDiagnostic(max(1, len(lines)), 1, "weak warning", "W292", "No newline at end of file.", True)
        )
    diagnostics.extend(_ast_style_diagnostics(source))
    return diagnostics


def _ast_style_diagnostics(source: str) -> list[EditorDiagnostic]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    analyzer = _FallbackPythonInspectionAnalyzer()
    analyzer.visit(tree)
    analyzer.finish()
    return analyzer.diagnostics


class _FallbackPythonInspectionAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.diagnostics: list[EditorDiagnostic] = []
        self.imported_names: dict[str, ast.AST] = {}
        self.assigned_names: set[str] = set()
        self.used_names: dict[str, ast.AST] = {}
        self.global_names: set[str] = set()
        self.scope_stack: list[str] = []

    def visit_Module(self, node: ast.Module) -> Any:
        non_doc_statement_seen = False
        for index, statement in enumerate(node.body):
            is_docstring = index == 0 and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)
            if isinstance(statement, ast.ImportFrom) and statement.module == "__future__" and non_doc_statement_seen:
                self._add(statement, "warning", "PY-FUTURE", "__future__ imports must appear before regular code/imports.", False)
            if not is_docstring and not (isinstance(statement, ast.ImportFrom) and statement.module == "__future__"):
                non_doc_statement_seen = True
        self.generic_visit(node)

    def finish(self) -> None:
        for name, node in self.imported_names.items():
            if name.startswith("_") or name in self.used_names:
                continue
            self._add(node, "weak warning", "F401", f"Imported name '{name}' is unused.", True)
        defined = set(self.assigned_names) | set(self.imported_names) | self.global_names | PYTHON_BUILTINS
        for name, node in sorted(self.used_names.items()):
            if name.startswith("_") or name in defined:
                continue
            self._add(node, "warning", "F821", f"Possibly unresolved reference '{name}'.", False)

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            name = alias.asname or alias.name.split(".", 1)[0]
            self.imported_names[name] = node
            self._check_shadowing(name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        for alias in node.names:
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            if node.module != "__future__":
                self.imported_names[name] = node
            self._check_shadowing(name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._inspect_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._inspect_function_like(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self._bind_name(node.name, node)
        if node.name and not node.name[:1].isupper():
            self._add(node, "weak warning", "N801", "Class name should use CapWords.", False)
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> Any:
        for target in node.targets:
            self._bind_target(target)
        self._check_duplicate_dict_keys(node.value)
        self.generic_visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        self._bind_target(node.target)
        if node.value is not None:
            self._check_duplicate_dict_keys(node.value)
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> Any:
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> Any:
        self._bind_target(node.target)
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> Any:
        for item in node.items:
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
        if node.type is None:
            self._add(node, "warning", "E722", "Bare except catches too much; catch a specific exception.", False)
        if node.name:
            self._bind_name(str(node.name), node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        if isinstance(node.ctx, ast.Load):
            self.used_names.setdefault(node.id, node)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self._bind_name(node.id, node)

    def visit_Compare(self, node: ast.Compare) -> Any:
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and self._is_none_literal(comparator):
                self._add(node, "warning", "E711", "Use 'is None' or 'is not None' instead of equality.", True)
            if isinstance(op, (ast.Eq, ast.NotEq)) and self._is_none_literal(node.left):
                self._add(node, "warning", "E711", "Use 'is None' or 'is not None' instead of equality.", True)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> Any:
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            if isinstance(node.value, ast.Constant):
                self._add(node, "weak warning", "B018", "Statement has no effect.", False)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> Any:
        self._check_duplicate_dict_keys(node)
        self.generic_visit(node)

    def _inspect_function_like(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._bind_name(node.name, node)
        if node.name and not _is_snake_case(node.name):
            self._add(node, "weak warning", "N802", "Function name should be snake_case.", False)
        self._check_arguments(node.args)
        self._check_unreachable_body(node.body)
        if node.name == "__init__":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value is not None:
                    self._add(child, "warning", "PYI034", "__init__ should not return a value.", False)
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def _check_arguments(self, args: ast.arguments) -> None:
        for arg in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
            self._bind_name(arg.arg, arg)
            self._check_shadowing(arg.arg, arg)
        for default in list(args.defaults) + [item for item in args.kw_defaults if item is not None]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(default, "warning", "B006", "Mutable default argument can retain state between calls.", False)

    def _bind_target(self, target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self._bind_name(target.id, target)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind_target(item)
        elif isinstance(target, ast.Attribute):
            self.visit(target.value)
        elif isinstance(target, ast.Subscript):
            self.visit(target.value)

    def _bind_name(self, name: str, node: ast.AST) -> None:
        self.assigned_names.add(name)
        self._check_shadowing(name, node)

    def _check_shadowing(self, name: str, node: ast.AST) -> None:
        if name in PYTHON_BUILTINS and name not in {"_", "self", "cls"}:
            self._add(node, "weak warning", "A001", f"Name '{name}' shadows a Python built-in.", False)

    def _check_duplicate_dict_keys(self, node: ast.AST) -> None:
        if not isinstance(node, ast.Dict):
            return
        seen: set[Any] = set()
        for key in node.keys:
            if isinstance(key, ast.Constant):
                value = key.value
                if value in seen:
                    self._add(key, "warning", "PY-DUPKEY", f"Duplicate dictionary key {value!r}.", False)
                seen.add(value)

    def _check_unreachable_body(self, body: list[ast.stmt]) -> None:
        terminated = False
        for statement in body:
            if terminated:
                self._add(statement, "warning", "PY-UNREACHABLE", "Unreachable code after a terminating statement.", False)
                break
            terminated = isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue))

    def _is_none_literal(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value is None

    def _add(self, node: ast.AST, severity: str, code: str, message: str, fixable: bool) -> None:
        self.diagnostics.append(
            EditorDiagnostic(
                line=int(getattr(node, "lineno", 1) or 1),
                column=int(getattr(node, "col_offset", 0) or 0) + 1,
                severity=severity,
                code=code,
                message=message,
                fixable=fixable,
            )
        )


def _is_snake_case(value: str) -> bool:
    return bool(value) and value.lower() == value and "-" not in value and " " not in value


def _dedupe_diagnostics(items: list[EditorDiagnostic]) -> list[EditorDiagnostic]:
    seen: set[tuple[int, int, str, str]] = set()
    unique: list[EditorDiagnostic] = []
    for item in items:
        key = (item.line, item.column, item.code, item.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _fallback_reformat_source(source: str) -> str:
    lines = [line.expandtabs(4).rstrip() for line in source.splitlines()]
    text = "\n".join(lines)
    if text:
        text += "\n"
    return text


def _fallback_safe_fixes(source: str) -> str:
    text = source
    text = text.replace(" == None", " is None")
    text = text.replace(" != None", " is not None")
    text = text.replace("None ==", "None is")
    text = text.replace("None !=", "None is not")
    return text


def _black_format_source(source: str, path: str) -> tuple[str | None, list[str]]:
    try:
        import black  # type: ignore
    except ModuleNotFoundError:
        pass
    else:
        try:
            mode = black.FileMode(line_length=100)
            return black.format_file_contents(source, fast=False, mode=mode), ["Formatted with Black."]
        except Exception as exc:
            if exc.__class__.__name__ == "NothingChanged":
                return source, ["Black found no formatting changes."]
            return None, [f"Black could not format this file: {exc}"]

    return _run_tempfile_tool(source, path, ["black", "--quiet", "--config", project_quality_config_path()])


def _ruff_diagnostics(source: str, path: str) -> list[EditorDiagnostic]:
    result = _run_ruff_check(source, path, fix=False)
    if result is None:
        return []
    _fixed_source, payload = result
    diagnostics: list[EditorDiagnostic] = []
    for row in payload:
        location = row.get("location") or {}
        fix = row.get("fix")
        diagnostics.append(
            EditorDiagnostic(
                line=int(location.get("row") or 1),
                column=int(location.get("column") or 1),
                severity="warning",
                code=str(row.get("code") or "RUFF"),
                message=str(row.get("message") or "Ruff diagnostic"),
                fixable=bool(fix),
            )
        )
    return diagnostics


def _ruff_fix_source(source: str, path: str) -> tuple[str | None, list[str]]:
    result = _run_ruff_check(source, path, fix=True)
    if result is None:
        return None, []
    fixed_source, payload = result
    count = len(payload)
    return fixed_source, [f"Ruff fix ran; remaining diagnostics: {count}."]


def _run_ruff_check(source: str, path: str, *, fix: bool) -> tuple[str, list[dict[str, Any]]] | None:
    ruff_exe = shutil.which("ruff")
    if not ruff_exe:
        return None
    suffix = Path(path).suffix or ".py"
    with tempfile.TemporaryDirectory(prefix="tc_editor_quality_") as tmp:
        temp_path = Path(tmp) / f"buffer{suffix}"
        temp_path.write_text(source, encoding="utf-8")
        command = [ruff_exe, "check", "--output-format", "json", "--config", project_quality_config_path()]
        if fix:
            command.append("--fix")
        command.append(str(temp_path))
        completed = subprocess.run(command, capture_output=True, text=True, timeout=12)
        output = completed.stdout.strip() or "[]"
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = []
        fixed_source = temp_path.read_text(encoding="utf-8")
        return fixed_source, payload if isinstance(payload, list) else []


def _run_tempfile_tool(source: str, path: str, command_prefix: list[str]) -> tuple[str | None, list[str]]:
    executable = shutil.which(command_prefix[0])
    if not executable:
        return None, []
    suffix = Path(path).suffix or ".py"
    with tempfile.TemporaryDirectory(prefix="tc_editor_format_") as tmp:
        temp_path = Path(tmp) / f"buffer{suffix}"
        temp_path.write_text(source, encoding="utf-8")
        command = [executable] + [item for item in command_prefix[1:] if item] + [str(temp_path)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=12)
        if completed.returncode not in (0, 123):
            return None, [(completed.stderr or completed.stdout or "Formatter failed.").strip()]
        return temp_path.read_text(encoding="utf-8"), ["Formatted with Black."]
