"""Shared imports and constants for project edit agent implementation."""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import inspect
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import time
import textwrap
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


PROJECT_EDIT_CHANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "modify",
                            "replace_symbol",
                            "insert_before_symbol",
                            "insert_after_symbol",
                            "replace_text",
                            "insert_before_text",
                            "insert_after_text",
                            "ensure_import",
                        ],
                    },
                    "path": {"type": "string"},
                    "target_symbol": {"type": "string"},
                    "original_content": {"type": "string"},
                    "new_content": {"type": "string"},
                },
                "required": ["action", "path", "target_symbol", "original_content", "new_content"],
                "additionalProperties": False,
            },
        },
        "report": {
            "type": "object",
            "properties": {
                "changed": {"type": "array", "items": {"type": "string"}},
                "reused": {"type": "array", "items": {"type": "string"}},
                "verification": {"type": "array", "items": {"type": "string"}},
                "remaining_gaps": {"type": "array", "items": {"type": "string"}},
                "requirement_coverage": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "requirement": {"type": "string"},
                            "production_owners": {"type": "array", "items": {"type": "string"}},
                            "test_owners": {"type": "array", "items": {"type": "string"}},
                            "validation": {"type": "array", "items": {"type": "string"}},
                            "status": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "requirement",
                            "production_owners",
                            "test_owners",
                            "validation",
                            "status",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "changed",
                "reused",
                "verification",
                "remaining_gaps",
                "requirement_coverage",
            ],
            "additionalProperties": False,
        },
        "blocked_reason": {"type": "string"},
    },
    "required": ["changes", "report", "blocked_reason"],
    "additionalProperties": False,
}

PROJECT_EDIT_SYNTAX_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"corrected_source": {"type": "string"}},
    "required": ["corrected_source"],
    "additionalProperties": False,
}

PROJECT_EDIT_FUNCTION_REPAIR_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "algorithm_steps": {"type": "array", "items": {"type": "string"}},
        "preserve": {"type": "array", "items": {"type": "string"}},
        "postconditions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["root_cause", "algorithm_steps", "preserve", "postconditions"],
    "additionalProperties": False,
}

PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": {
            "type": "object",
            "properties": {
                "canonical_owners": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
                "signatures": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "shared_invariants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "data_layout": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "errors": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
            },
            "required": [
                "canonical_owners",
                "signatures",
                "shared_invariants",
                "data_layout",
                "errors",
            ],
            "additionalProperties": False,
            "description": (
                "Concrete package-wide API/data contracts: canonical owners, exact signatures "
                "and defaults, shared layouts/constants, bounds, and errors."
            ),
        },
        "files": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "contracts": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "algorithm_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "validation_steps": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "contracts",
                    "algorithm_steps",
                    "validation_steps",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["integration_contracts", "files"],
    "additionalProperties": False,
}

PROJECT_EDIT_INTEGRATION_CONTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "integration_contracts": PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA[
            "properties"
        ]["integration_contracts"],
    },
    "required": ["integration_contracts"],
    "additionalProperties": False,
}

PROJECT_EDIT_FILE_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "minItems": 2,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "purpose": {"type": "string"},
                    "requirement_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 60,
                        "items": {"type": "string"},
                    },
                    "public_symbols": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "is_test": {"type": "boolean"},
                },
                "required": [
                    "path",
                    "purpose",
                    "requirement_ids",
                    "public_symbols",
                    "depends_on",
                    "is_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}

from tech_connector.services.project_edit_agent_part_01 import (
    ProjectEditLeafWorkUnits,
    ProjectEditPlan,
    ProjectEditPromptStage,
    extract_project_edit_artifact_requirements,
)


def _remove_generated_top_level_calls(source: str, *, tree: ast.Module) -> str:
    """Remove generated module-level call expressions forbidden by the file contract."""

    removals = [
        statement
        for statement in tree.body
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
        )
        or (
            isinstance(statement, (ast.Assign, ast.AnnAssign))
            and isinstance(statement.value, ast.Call)
        )
    ]
    if not removals:
        return source
    lines = source.splitlines(keepends=True)
    for statement in sorted(removals, key=lambda item: item.lineno, reverse=True):
        del lines[statement.lineno - 1:int(statement.end_lineno or statement.lineno)]
    return "".join(lines)


def _remove_redundant_generated_initializers(source: str, tree: ast.Module) -> str:
    """Remove no-op constructors from classes that already expose real behavior."""

    removals: list[tuple[int, int]] = []
    for class_node in (
        node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    ):
        methods = [
            node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if not any(method.name != "__init__" for method in methods):
            continue
        for method in methods:
            if method.name != "__init__":
                continue
            meaningful_body = [
                statement
                for statement in method.body
                if not (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                )
            ]
            if len(meaningful_body) == 1 and isinstance(meaningful_body[0], ast.Pass):
                removals.append((method.lineno - 1, method.end_lineno or method.lineno))
    if not removals:
        return source
    lines = source.splitlines(keepends=True)
    for start, end in sorted(removals, reverse=True):
        del lines[start:end]
    return "".join(lines)


def _generated_module_import_side_effects(tree: ast.Module) -> list[str]:
    """Return top-level executable statements that make importing generated code unsafe."""

    issues: list[str] = []
    for statement in tree.body:
        if isinstance(statement, ast.Expr):
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                continue
            if isinstance(statement.value, ast.Call):
                issues.append(f"call on line {statement.lineno}")
        elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
            issues.append(f"{statement.__class__.__name__} on line {statement.lineno}")
        elif isinstance(statement, ast.Try):
            issues.append(f"Try on line {statement.lineno}")
    return issues


def repair_project_edit_duplicate_dependency_symbols(
    source: str,
    *,
    path: str,
    project_root: str,
    generated_files: list[tuple[str, str, str]],
) -> tuple[str, list[str]]:
    """Remove echoed dependency definitions and import canonical owners when used."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return source, []
    root = Path(project_root).resolve()
    target = Path(path).resolve()
    owners: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for dependency_path, _original, dependency_source in generated_files:
        dependency = Path(dependency_path).resolve()
        if dependency == target:
            continue
        try:
            dependency_tree = ast.parse(dependency_source, filename=dependency_path)
            module = ".".join(dependency.relative_to(root).with_suffix("").parts)
        except (SyntaxError, ValueError):
            continue
        for node in dependency_tree.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            if node.name in owners:
                ambiguous.add(node.name)
            else:
                owners[node.name] = (module, str(dependency))

    duplicates = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in owners
        and node.name not in ambiguous
    ]
    if not duplicates:
        return source, []

    lines = source.splitlines(keepends=True)
    removed_names = {node.name for node in duplicates}
    for node in sorted(duplicates, key=lambda item: item.lineno, reverse=True):
        del lines[node.lineno - 1:int(node.end_lineno or node.lineno)]
    repaired = "".join(lines)
    repaired_tree = ast.parse(repaired, filename=path)
    loaded_names = {
        node.id
        for node in ast.walk(repaired_tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    required_imports = {
        name: owners[name][0]
        for name in removed_names & loaded_names
    }
    if required_imports:
        import_lines = [
            f"from {module} import {name}\n"
            for name, module in sorted(required_imports.items())
        ]
        insertion = 1 if lines and re.match(r"^#.*coding[:=]", lines[0]) else 0
        while insertion < len(lines) and (
            not lines[insertion].strip()
            or lines[insertion].startswith("import ")
            or lines[insertion].startswith("from ")
        ):
            insertion += 1
        lines[insertion:insertion] = import_lines
        repaired = "".join(lines)
    compile(ast.parse(repaired, filename=path), path, "exec")
    fixes = [
        f"{Path(path).name}: removed echoed {name} owned by "
        f"{Path(owners[name][1]).name}"
        for name in sorted(removed_names)
    ]
    fixes.extend(
        f"{Path(path).name}: imported {name} from {module}"
        for name, module in sorted(required_imports.items())
    )
    return repaired, fixes


def _render_ast_arguments(arguments: ast.arguments, *, drop_first: bool = False) -> str:
    positional = [*arguments.posonlyargs, *arguments.args]
    if drop_first and positional:
        positional = positional[1:]
    defaults_offset = len(positional) - len(arguments.defaults)
    rendered: list[str] = []
    for index, argument in enumerate(positional):
        value = argument.arg
        default_index = index - defaults_offset
        if default_index >= 0:
            value += "=" + ast.unparse(arguments.defaults[default_index])
        rendered.append(value)
    if arguments.vararg:
        rendered.append("*" + arguments.vararg.arg)
    elif arguments.kwonlyargs:
        rendered.append("*")
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        value = argument.arg
        if default is not None:
            value += "=" + ast.unparse(default)
        rendered.append(value)
    if arguments.kwarg:
        rendered.append("**" + arguments.kwarg.arg)
    return "(" + ", ".join(rendered) + ")"


def summarize_project_edit_generated_interface(path: str, source: str) -> str:
    """Render a compact AST readback for the next incremental file worker."""

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return f"{Path(path).name}: interface unavailable because source did not parse"

    entries: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            entries.append(f"{node.name}{_render_ast_arguments(node.args)}")
        elif isinstance(node, ast.ClassDef):
            constructor = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "__init__"
                ),
                None,
            )
            class_signature = (
                _render_ast_arguments(constructor.args, drop_first=True)
                if constructor is not None
                else "()"
            )
            entries.append(f"{node.name}{class_signature}")
            entries.extend(
                f"{node.name}.{child.name}{_render_ast_arguments(child.args, drop_first=True)}"
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not child.name.startswith("_")
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        rendered_value = repr(ast.literal_eval(value))
                    except (TypeError, ValueError):
                        rendered_value = "<computed>"
                    entries.append(f"{target.id}={rendered_value}")
    return f"{Path(path).name}: " + ("; ".join(entries) if entries else "(no public API)")


def build_project_edit_cross_file_failure_notes(
    generated_files: list[tuple[str, str, str]],
    validation_errors: list[str],
) -> list[str]:
    """Describe shared undefined-name ownership failures for the architecture worker."""

    undefined_uses: dict[str, int] = {}
    for error in validation_errors:
        for match in re.finditer(
            r"Generated callables reference undefined names in ([^:]+):\s*([^;\n]+)",
            str(error),
        ):
            callable_count = max(
                1,
                len([value for value in match.group(1).split(",") if value.strip()]),
            )
            for name in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", match.group(2)):
                undefined_uses[name] = undefined_uses.get(name, 0) + callable_count
    if not undefined_uses:
        return []

    owners: dict[str, list[str]] = {}
    for path_text, _original, source in generated_files:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:
            names: list[str] = []
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [node.name]
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [
                    target.id for target in targets if isinstance(target, ast.Name)
                ]
            for name in names:
                owners.setdefault(name, []).append(path_text)

    notes: list[str] = []
    for name, use_count in sorted(undefined_uses.items()):
        if use_count < 2:
            continue
        name_owners = list(dict.fromkeys(owners.get(name) or []))
        if len(name_owners) > 1:
            notes.append(
                f"Cross-file contract conflict: {name} is used unresolved by {use_count} callables "
                f"and is defined by multiple modules ({', '.join(name_owners)}). Select one "
                "canonical production owner and make every consumer depend on and import it."
            )
        elif not name_owners:
            notes.append(
                f"Cross-file contract gap: {name} is used unresolved by {use_count} callables "
                "but no generated module owns it. Add one canonical production owner and explicit "
                "dependency/import edges."
            )
    return notes


def project_edit_validation_failure_signature(
    validation_errors: list[str],
) -> tuple[str, ...]:
    """Normalize disposable failures to stable root-cause evidence."""

    facts: set[str] = set()
    for error in validation_errors:
        text = re.sub(
            r"tech_connector_patch_validation_[^\\/\s]+",
            "tech_connector_patch_validation_<temp>",
            str(error),
        )
        for line in text.splitlines():
            stripped = " ".join(line.strip().split())
            if not stripped:
                continue
            exception = re.match(
                r"^(?:[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)|AssertionError):\s*(.*)$",
                stripped,
            )
            if exception:
                normalized = re.sub(r"\bline\s+\d+\b", "line <n>", stripped)
                facts.add(normalized)
                continue
            if stripped.startswith((
                "Generated callables reference undefined names",
                "Generated production callables are placeholders",
                "New import could not be resolved",
                "Generated import is missing its manifest dependency edge",
                "Project-local import does not expose",
            )):
                facts.add(stripped)
    if facts:
        return tuple(sorted(facts))
    return tuple(sorted(
        re.sub(r"\bline\s+\d+\b", "line <n>", " ".join(str(item).split()))
        for item in validation_errors
    ))


def build_project_edit_function_repair_stage(
    contract: dict[str, Any],
    *,
    attempt: int = 1,
    repair_plan: dict[str, Any] | None = None,
) -> ProjectEditPromptStage:
    """Build a bounded callable-only repair worker from a validated contract."""

    requirements = "\n".join(
        f"- {value}" for value in contract.get("requirements") or []
    ) or "- preserve the objective behavior owned by this callable"
    imports = "\n".join(contract.get("module_imports") or []) or "(none)"
    module_symbols = ", ".join(contract.get("module_symbols") or []) or "(none)"
    generated_interfaces = "\n".join(
        contract.get("generated_interfaces") or []
    ) or "(none)"
    sibling_symbols = ", ".join(contract.get("sibling_symbols") or []) or "(none)"
    sibling_signatures = "\n".join(contract.get("sibling_signatures") or []) or "(none)"
    state_context = "\n\n".join(contract.get("state_context") or []) or "(none)"
    callsites = "\n\n".join(contract.get("callsite_excerpts") or []) or "(none)"
    forbidden_names = ", ".join(contract.get("forbidden_names") or []) or "(none)"
    symbol = str(contract.get("symbol") or "")
    owner_capsule = contract.get("atomic_owner_capsule_payload") or {}
    owner_requirement_lines = [
        str(requirement.get("text") or requirement.get("requirement") or "").strip()
        if isinstance(requirement, Mapping)
        else str(requirement).strip()
        for requirement in owner_capsule.get("requirements") or []
    ]
    owner_requirements = "\n".join(
        f"{index}. {requirement}"
        for index, requirement in enumerate(
            (line for line in owner_requirement_lines if line),
            start=1,
        )
    ) or "1. Preserve every behavior stated in the supplied owner capsule."
    callable_name = symbol.rsplit(".", 1)[-1]
    verification_callable = (
        callable_name in {"run_self_test", "self_test"}
        or callable_name.startswith("test_")
    )
    plan_text = json.dumps(repair_plan or {}, indent=2)
    forbidden_set = {
        str(value) for value in contract.get("forbidden_names") or [] if str(value)
    }
    invalid_assertion_lines = {
        str(value).strip()
        for value in contract.get("invalid_assertion_lines") or []
        if str(value).strip()
    }
    source_lines = []
    for line in str(contract.get("source") or "").splitlines():
        if line.strip() in invalid_assertion_lines:
            indent = line[: len(line) - len(line.lstrip())]
            source_lines.append(
                f"{indent}# INVALID ASSERTION REMOVED BY CONTRACT"
            )
        elif any(re.search(rf"\b{re.escape(name)}\b", line) for name in forbidden_set):
            indent = line[: len(line) - len(line.lstrip())]
            source_lines.append(
                f"{indent}# INVALID FAILURE LINE REMOVED BY CONTRACT"
            )
        else:
            source_lines.append(line)
    bounded_source = "\n".join(source_lines)
    if contract.get("atomic_owner_capsule"):
        atomic_failures = "\n".join(
            f"- {value}"
            for value in contract.get("all_validation_errors") or []
        ) or f"- {contract.get('failure') or 'Repair the supplied callable contract.'}"
        return ProjectEditPromptStage(
            key="function_repair",
            label=f"Repairing {symbol}",
            system_prompt=(
                "You are a senior Python callable repair worker. Every supplied "
                "field is authoritative and must be satisfied. Return exactly one "
                "complete replacement function or method with the exact signature. "
                "Change the executable statements responsible for every listed "
                "failure. An unchanged, AST-equivalent, formatting-only, placeholder, "
                "module, class, diff, Markdown, JSON, or explanatory response is "
                "invalid. Preserve unrelated behavior and use only supplied evidence, "
                "visible imports, owner state, arguments, locals, and builtins."
            ),
            user_prompt=f"""EXACT REPAIR OWNER
{symbol}

EVERY APPROVED OWNER REQUIREMENT (ALL ARE MANDATORY)
{owner_requirements}

FAILURES THAT MUST ALL BE ABSENT AFTER THIS REPLACEMENT
{atomic_failures}

APPROVED OWNER CAPSULE
{json.dumps(
    contract.get("atomic_owner_capsule_payload") or {},
    ensure_ascii=True,
    separators=(",", ":"),
)}

Exact required signature
{contract.get("signature") or ""}

CURRENT CALLABLE TO REPLACE
```python
{bounded_source}
```

AVAILABLE MODULE IMPORTS
```python
{imports}
```

RELEVANT OWNER STATE
```python
{state_context}
```

RELEVANT CALLERS
```python
{callsites}
```

FINAL CHECK BEFORE RESPONDING
Trace one concrete input or state transition through the replacement for every
numbered owner requirement above. Check boundary branches before the common path,
including non-matching input types, missing keys, empty values, and mutation or
aliasing constraints when named. Compare executable AST behavior against CURRENT
CALLABLE TO REPLACE. If it is equivalent or any requirement or listed failure
remains, revise it now. Return only the complete raw Python callable named
{contract.get("callable_name") or ""}.
""",
            num_predict=max(
                512,
                min(1800, (len(bounded_source) // 2) + 256),
            ),
            model_tier="local_code",
            num_ctx=8192,
            timeout=120,
            no_progress_seconds=30,
            prefer_coder=True,
            coder_preference="standard",
            response_format="",
            metadata={
                "path": str(contract.get("path") or ""),
                "symbol": symbol,
                "signature_fingerprint": str(
                    contract.get("signature_fingerprint") or ""
                ),
                "owner_source": str(contract.get("source") or ""),
                "canonical_repair_contract": dict(contract),
                "atomic_prepared": True,
            },
        )
    return ProjectEditPromptStage(
        key="function_repair",
        label=f"Repairing {symbol}",
        system_prompt=(
            "You are a bounded senior Python function repair worker. Return exactly one complete "
            "replacement function or method. Preserve its exact signature and repair only the supplied "
            "failure. The replacement must be materially different from the supplied current "
            "implementation: returning the same body, an AST-equivalent body, or formatting-only "
            "changes is forbidden. Before responding, compare your replacement with the current "
            "implementation and confirm internally that an executable statement responsible for "
            "the failure changed. "
            + (
                "A verification callable may define a private local fixture class "
                "inside its own body, but must not return a class or add a module-level "
                "declaration. "
                if verification_callable
                else
                "Do not return or introduce a class, including a nested class inside "
                "the callable. When mutable closure state is needed, use a built-in "
                "mutable container captured by a nested function. "
            )
            + "Do not return a module, diff, Markdown, "
            "JSON, or explanation."
        ),
        user_prompt=f"""Original objective:
{contract.get("objective") or ""}

Callable owned by this worker:
{symbol}

Exact required signature:
{contract.get("signature") or ""}

Current implementation:
```python
{bounded_source}
```

Requirements owned by this file:
{requirements}

Imports already available in the module:
```python
{imports}
```

Available module symbols:
{module_symbols}
Symbols listed here because validation verified an installed public API owner may
be used even when their import is not present yet; deterministic import
normalization will add the verified owner import after this symbol repair.

Exact generated package interfaces already available:
```text
{generated_interfaces}
```
Call only methods shown in this interface readback; do not invent aliases or renamed variants.

Relevant sibling callables:
{sibling_symbols}

Sibling interfaces available to call:
```python
{sibling_signatures}
```

Owning class state initialization and class-level assignments:
```python
{state_context}
```
Preserve these container types and state invariants exactly.

Bounded callers and behavioral tests that define the input/output contract:
```python
{callsites}
```
Caller-local fixture names are evidence only. They do not exist inside the repaired callable and must not be copied.

Names proven invalid by the current failure and forbidden in the replacement:
{forbidden_names}

Assertion lines proven invalid by runtime validation and forbidden in the replacement:
{chr(10).join(sorted(invalid_assertion_lines)) or "(none)"}

Smallest matching disposable validation failure:
{contract.get("failure") or ""}

Complete owner validation snapshot:
{chr(10).join(contract.get("all_validation_errors") or [])}

Approved repair micro-plan:
```json
{plan_text}
```

Return one complete replacement callable named {contract.get("callable_name") or ""}.
Keep the exact parameter list, defaults, annotations, async form, and decorators.
Use only arguments, local names, builtins, visible imports, and available module symbols.
If a new standard-library helper is needed only here, import it locally inside the callable.
Fix the root cause and preserve behavior outside this callable. Return raw Python only.
MANDATORY PRE-RETURN CHECK: compare the proposed callable against Current implementation.
Do not respond until the proposed body is materially different and the changed executable
logic directly addresses Smallest matching disposable validation failure. An identical,
AST-equivalent, comment-only, whitespace-only, or formatting-only response is invalid.
If this callable is a test, keep the original objective and accepted behavior as the
specification. Do not weaken assertions, delete coverage, or replace requested observable
behavior with assertRaises unless the objective or contract explicitly requires that error.
""",
        model_tier="local_code",
        num_ctx=6144 if attempt > 1 else 5120,
        num_predict=1100 if attempt > 1 else 850,
        timeout=90,
        no_progress_seconds=20,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "path": str(contract.get("path") or ""),
            "symbol": symbol,
            "signature_fingerprint": str(contract.get("signature_fingerprint") or ""),
            "owner_source": str(contract.get("source") or ""),
            "canonical_repair_contract": dict(contract),
        },
    )


def build_project_edit_class_repair_stage(
    generated_files: list[tuple[str, str, str]],
    *,
    path: str,
    class_name: str,
    objective: str,
    validation_errors: list[str],
) -> ProjectEditPromptStage:
    """Build a bounded class-chunk repair for a newly generated file."""

    target_context: list[str] = []
    package_interfaces: list[str] = []
    for file_path, _original, source in generated_files:
        package_interfaces.append(
            summarize_project_edit_generated_interface(file_path, source)
        )
        if Path(file_path).resolve() != Path(path).resolve():
            continue
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            target_context.append(f"File: {file_path}\n```python\n{source}\n```")
            continue
        target_node = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if target_node is not None:
            class_source = ast.get_source_segment(source, target_node) or ast.unparse(target_node)
            target_context.append(f"File: {file_path}\n```python\n{class_source}\n```")
    return ProjectEditPromptStage(
        key="class_repair",
        label=f"Repairing class {class_name}",
        system_prompt=(
            "You are a bounded senior Python integration repair worker. Return exactly one "
            "complete replacement class declaration as raw Python. Do not return imports, a "
            "module, a diff, Markdown, JSON, or explanation."
        ),
        user_prompt=f"""Original objective:
{objective}

Class chunk to replace:
{class_name}

Exact current class source:
{chr(10).join(target_context) or "(class source unavailable)"}

Generated package interfaces:
{chr(10).join(package_interfaces)}

Complete deterministic validation failures:
- {chr(10).join(validation_errors)}

Repair this class as one coherent chunk. You may correct its constructor and method signatures when runtime proof
shows that the generated contract cannot represent the requested behavior. Preserve unrelated module-level records,
exceptions, functions, and classes. Use the exact visible APIs of sibling files. If a standard-library helper is
needed, import it locally inside the method that uses it. Do not invent exceptions or external APIs.
For an immutable record class, preserve actual immutability while correcting its fields so the requested producer,
storage, traversal, and execution operations can all use the same canonical record.
For a test class, repair setup and every affected test together, keep substantive coverage, call the production API
that directly owns each named behavior, and never weaken assertions merely to make the suite pass.
Return exactly one complete class named {class_name}.
""",
        model_tier="local_code",
        num_ctx=8192,
        num_predict=-1,
        timeout=120,
        no_progress_seconds=25,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "path": str(path),
            "symbol": str(class_name),
            "owner_source": "\n\n".join(target_context),
            "all_validation_errors": list(validation_errors),
            "full_objective": str(objective or ""),
        },
    )


def build_project_edit_class_set_repair_stage(
    generated_files: list[tuple[str, str, str]],
    *,
    class_targets: list[tuple[str, str]],
    objective: str,
    approved_contract: str,
    validation_errors: list[str],
    repair_attempt: int = 1,
) -> ProjectEditPromptStage:
    """Build one coherent repair decision returned as independent class chunks."""

    target_names = [class_name for _path, class_name in class_targets]
    target_context: list[str] = []
    package_interfaces = [
        summarize_project_edit_generated_interface(file_path, source)
        for file_path, _original, source in generated_files
    ]
    for target_path, class_name in class_targets:
        target_source = next(
            (
                source
                for file_path, _original, source in generated_files
                if Path(file_path).resolve() == Path(target_path).resolve()
            ),
            "",
        )
        try:
            target_tree = ast.parse(target_source, filename=target_path)
        except SyntaxError:
            target_context.append(
                f"File: {target_path}\n```python\n{target_source}\n```"
            )
            continue
        target_node = next(
            (
                node
                for node in target_tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        if target_node is not None:
            class_source = (
                ast.get_source_segment(target_source, target_node)
                or ast.unparse(target_node)
            )
            target_context.append(
                f"File: {target_path}\n```python\n{class_source}\n```"
            )
    api_checklist: list[str] = []
    for target_path, class_name in class_targets:
        target_source = next(
            (
                source
                for file_path, _original, source in generated_files
                if file_path == target_path
            ),
            "",
        )
        try:
            target_tree = ast.parse(target_source)
        except SyntaxError:
            target_tree = ast.Module(body=[], type_ignores=[])
        target_class = next(
            (
                node
                for node in target_tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        signatures = [
            f"{child.name}({ast.unparse(child.args)})"
            for child in (target_class.body if target_class is not None else [])
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not child.name.startswith("__")
        ]
        consumer_calls: set[str] = set()
        for file_path, _original, source in generated_files:
            if not Path(file_path).name.startswith("test_"):
                continue
            try:
                consumer_tree = ast.parse(source)
            except SyntaxError:
                continue
            instance_names = {
                target.id
                for assignment in ast.walk(consumer_tree)
                if isinstance(assignment, ast.Assign)
                and isinstance(assignment.value, ast.Call)
                and isinstance(assignment.value.func, ast.Name)
                and assignment.value.func.id == class_name
                for target in assignment.targets
                if isinstance(target, ast.Name)
            }
            consumer_calls.update(
                call.func.attr
                for call in ast.walk(consumer_tree)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in instance_names
                and not call.func.attr.startswith("_")
            )
        api_checklist.append(
            f"- {class_name}: current public signatures: "
            + (", ".join(signatures) or "(none)")
            + "; consumer-called methods that must remain available: "
            + (", ".join(sorted(consumer_calls)) or "(none)")
        )
    return ProjectEditPromptStage(
        key="class_set_repair",
        label="Repairing coherent class chunks",
        system_prompt=(
            "You are a senior Python package integration repair worker. Return raw Python "
            "containing exactly the requested complete class declarations plus only the "
            "imports newly required by those declarations. Do not return unrelated "
            "declarations, module execution, diffs, Markdown, JSON, or explanation. "
            "Approved helper declarations that are not explicitly listed under Class "
            "chunks to replace together are preserved separately and must not be returned."
        ),
        user_prompt=f"""Original objective:
{objective}

Authoritative validated shared contract:
```json
{approved_contract}
```

Class chunks to replace together:
{chr(10).join(f"- {name}" for name in target_names)}

Mandatory public API preservation checklist:
{chr(10).join(api_checklist)}

Exact current target class sources:
{chr(10).join(target_context) or "(class source unavailable)"}

Generated package interfaces:
{chr(10).join(package_interfaces)}

Complete deterministic validation failures:
- {chr(10).join(validation_errors)}

Repair these declarations as one coherent package decision. All record fields, constructors, public method
signatures, stored state, consumers, and tests must agree exactly. You may correct generated signatures and immutable
record fields when runtime evidence proves the generated contract cannot represent the request. Preserve actual
immutability where requested. Use public APIs to construct every tested success, failure, cycle, missing, recovery,
and immutability state. Do not weaken tests or invent unrelated exceptions. Return each requested class exactly once.
Every loaded name must be a parameter, local binding, class/module member, builtin, or supplied import. Never read a
name from a different method's parameters. When one lock-owning method calls another, use an RLock or refactor the
private helper so it does not reacquire the lock. Every documented parameter must have an exact ``:param name:``
entry, and every value-returning callable must have ``:return:`` in its docstring.
When TTL expiry and LRU recency are both required, keep the insertion timestamp separate from the recency ordering:
``get`` updates only recency, eviction observes recency, and lazy expiry removes the entry from every related index.
``__len__`` must count live entries after lazy expiry cleanup. Never use one timestamp field for both TTL and LRU.
The validated shared contract is authoritative over every generated signature and field shown in the broken package.
{"This is a repeated failed repair. Reconstruct the class APIs and tests from the objective and authoritative contract; do not preserve a broken generated signature, record layout, fixture, or hard-coded domain sentinel merely because it appears in current code." if repair_attempt > 1 else ""}
""",
        model_tier="local_code",
        num_ctx=8192,
        num_predict=3000,
        timeout=150,
        no_progress_seconds=30,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "class_targets": list(class_targets),
            "symbols": list(target_names),
            "owner_source": "\n\n".join(target_context),
            "all_validation_errors": list(validation_errors),
            "full_objective": str(objective or ""),
        },
    )


def build_project_edit_function_repair_plan_stage(
    contract: dict[str, Any],
) -> ProjectEditPromptStage:
    """Build a small reasoning stage that diagnoses one callable before coding."""

    callsites = "\n\n".join(contract.get("callsite_excerpts") or []) or "(none)"
    generated_interfaces = "\n".join(
        contract.get("generated_interfaces") or []
    ) or "(none)"
    state_context = "\n\n".join(contract.get("state_context") or []) or "(none)"
    forbidden = ", ".join(contract.get("forbidden_names") or []) or "(none)"
    owner_capsule = contract.get("atomic_owner_capsule_payload") or {}
    owner_requirement_lines = [
        str(requirement.get("text") or requirement.get("requirement") or "").strip()
        if isinstance(requirement, Mapping)
        else str(requirement).strip()
        for requirement in owner_capsule.get("requirements") or []
    ]
    owner_requirements = "\n".join(
        f"{index}. {requirement}"
        for index, requirement in enumerate(
            (line for line in owner_requirement_lines if line),
            start=1,
        )
    ) or "1. Preserve the complete approved callable contract."
    return ProjectEditPromptStage(
        key="function_repair_plan",
        label=f"Diagnosing {contract.get('symbol') or 'failing callable'}",
        system_prompt=(
            "You are a bounded code-repair diagnostician. Determine the root cause and a concrete "
            "algorithm for one callable from its signature, current body, callers, assertions, and "
            "failure. Return JSON only. Do not write Python."
        ),
        user_prompt=f"""Objective:
{contract.get("objective") or ""}

Callable and exact signature:
{contract.get("symbol") or ""}
{contract.get("signature") or ""}

Every approved owner requirement:
{owner_requirements}

Current body:
```python
{contract.get("source") or ""}
```

Caller and assertion evidence:
```python
{callsites}
```

Exact generated package interfaces:
```text
{generated_interfaces}
```

Owning class state initialization and class-level assignments:
```python
{state_context}
```

Validation failure:
{contract.get("failure") or ""}

Proven-invalid names that the implementation may not use:
{forbidden}

Return a minimal repair algorithm using only values actually available through the signature or visible module
interfaces. Include an algorithm step and concrete boundary case for every numbered owner requirement; a plan
that addresses only the reported symptom is incomplete. State exact output postconditions from the assertions. Do not invent paths, globals, fixtures, APIs,
or new parameters. Changing the callable signature is forbidden. If the existing inputs already contain the values
needed to compute an answer, derive it from those inputs instead of reacquiring unavailable external context.
Respect the concrete container types shown in class-state initialization. For query/report/find/list/order methods,
use local traversal state and local copies of counters; do not mutate persistent fields unless the contract explicitly
requires mutation. Identify how every requested observable state is made representable by the public input methods.
Keep every JSON string concise.
""",
        model_tier="local_semantic_verify",
        num_ctx=4096,
        num_predict=900,
        timeout=45,
        no_progress_seconds=15,
        prefer_coder=False,
        coder_preference="small",
        response_format=PROJECT_EDIT_FUNCTION_REPAIR_PLAN_SCHEMA,
    )


def parse_project_edit_function_repair_plan(
    response: str,
    *,
    contract: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate a function-repair diagnosis before a coder receives it."""

    try:
        payload = json.loads(str(response or ""))
    except (TypeError, ValueError) as exc:
        return {}, [f"Function repair plan JSON did not parse: {exc}"]
    if not isinstance(payload, dict):
        return {}, ["Function repair plan must be a JSON object."]
    errors: list[str] = []
    root_cause = str(payload.get("root_cause") or "").strip()
    algorithm_steps = [
        str(value).strip()
        for value in payload.get("algorithm_steps") or []
        if str(value).strip()
    ]
    preserve = [
        str(value).strip()
        for value in payload.get("preserve") or []
        if str(value).strip()
    ]
    postconditions = [
        str(value).strip()
        for value in payload.get("postconditions") or []
        if str(value).strip()
    ]
    if not root_cause:
        errors.append("Function repair plan omitted the root cause.")
    if not algorithm_steps:
        errors.append("Function repair plan omitted concrete algorithm steps.")
    if not postconditions:
        errors.append("Function repair plan omitted output postconditions.")
    combined_algorithm = " ".join([root_cause, *algorithm_steps]).lower()
    normalized_algorithm = re.sub(r"[`'\"*]", "", combined_algorithm)
    if re.search(
        r"\b(?:add|introduce|append|change|modify|extend)\b.{0,40}\b"
        r"(?:parameter|argument|signature)\b",
        combined_algorithm,
    ):
        errors.append("Function repair plan changes the callable signature.")
    for forbidden in (contract or {}).get("forbidden_names") or []:
        name = str(forbidden).lower()
        if name not in normalized_algorithm:
            continue
        safe_mentions = (
            f"remove {name}",
            f"avoid {name}",
            f"avoid using {name}",
            f"without {name}",
            f"do not use {name}",
            f"undefined variable {name}",
            f"undefined name {name}",
            f"undefined variable '{name}'",
            f"undefined name '{name}'",
        )
        if not any(value in normalized_algorithm for value in safe_mentions):
            errors.append(
                f"Function repair plan still depends on proven-invalid name {forbidden}."
            )
    contract_evidence = " ".join([
        str((contract or {}).get("objective") or ""),
        *[str(value) for value in (contract or {}).get("requirements") or []],
        *[str(value) for value in (contract or {}).get("callsite_excerpts") or []],
    ]).lower()
    if re.search(r"\brename(?:d|s)?\b", contract_evidence):
        has_identity_basis = bool(
            re.search(r"\b(?:digest|hash|content|identity|snapshot value|mapping value)\b", normalized_algorithm)
        )
        has_candidate_sets = bool(
            re.search(r"\bremoved\b", normalized_algorithm)
            and re.search(r"\badded\b", normalized_algorithm)
        )
        if not (has_identity_basis and has_candidate_sets):
            errors.append(
                "Rename repair plan must compute removed old keys and added new keys, pair only those "
                "candidates when their snapshot digest/content values match, process them deterministically, "
                "and remove paired paths from the added and removed outputs."
            )
    return {
        "root_cause": root_cause,
        "algorithm_steps": algorithm_steps,
        "preserve": preserve,
        "postconditions": postconditions,
    }, errors


def build_project_edit_multi_file_candidate(
    generated_files: list[tuple[str, str, str]],
) -> str:
    """Compose validated full-file worker outputs into one structured candidate."""

    changes = [
        {
            "action": "modify" if original else "create",
            "path": path,
            "target_symbol": "",
            "original_content": original,
            "new_content": generated,
        }
        for path, original, generated in generated_files
    ]
    return json.dumps(
        {
            "changes": changes,
            "report": {
                "changed": [Path(path).name for path, _original, _generated in generated_files],
                "reused": [],
                "verification": ["parse", "compile", "cross-file imports", "focused unittest"],
                "remaining_gaps": [],
                "requirement_coverage": [],
            },
            "blocked_reason": "",
        },
        ensure_ascii=True,
    )


def stabilize_project_edit_import_cycles(
    generated_files: list[tuple[str, str, str]],
    *,
    project_root: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Move project-local imports into their use sites when generated modules form a cycle."""

    root = Path(project_root).resolve()
    module_by_path: dict[str, str] = {}
    source_by_module: dict[str, str] = {}
    record_by_module: dict[str, tuple[str, str, str]] = {}
    for record in generated_files:
        path_text, original, generated = record
        path = Path(path_text).resolve()
        try:
            relative = path.relative_to(root).with_suffix("")
        except ValueError:
            continue
        module = ".".join(relative.parts)
        module_by_path[path_text] = module
        source_by_module[module] = generated
        record_by_module[module] = (path_text, original, generated)

    graph: dict[str, set[str]] = {module: set() for module in source_by_module}
    imports_by_module: dict[str, list[ast.ImportFrom]] = {}
    for module, source in source_by_module.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        local_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.level == 0
            and str(node.module or "") in source_by_module
        ]
        imports_by_module[module] = local_imports
        graph[module].update(str(node.module) for node in local_imports)

    def reaches(start: str, target: str) -> bool:
        pending = [start]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(graph.get(current, set()) - seen)
        return False

    stabilized = list(generated_files)
    fixes: list[str] = []
    for module, import_nodes in imports_by_module.items():
        cyclic_nodes = [
            node for node in import_nodes
            if reaches(str(node.module), module)
        ]
        if not cyclic_nodes:
            continue
        path_text, original, source = record_by_module[module]
        tree = ast.parse(source)
        lines = source.splitlines(keepends=True)
        edits: list[tuple[int, int, str]] = []
        callable_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                callable_nodes.append(node)
            elif isinstance(node, ast.ClassDef):
                callable_nodes.extend(
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        for import_node in cyclic_nodes:
            local_names = {alias.asname or alias.name for alias in import_node.names}
            non_callable_body = [
                node
                for node in tree.body
                if node is not import_node
                and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            if any(
                isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in local_names
                for statement in non_callable_body
                for node in ast.walk(statement)
            ):
                continue
            import_text = "".join(lines[import_node.lineno - 1: import_node.end_lineno]).strip()
            users = [
                function
                for function in callable_nodes
                if any(
                    isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id in local_names
                    for node in ast.walk(function)
                )
            ]
            edits.append((import_node.lineno - 1, import_node.end_lineno, ""))
            for function in users:
                body = list(function.body)
                insertion_line = function.lineno
                if body:
                    first = body[0]
                    insertion_line = first.lineno - 1
                    if (
                        isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)
                    ):
                        insertion_line = int(first.end_lineno or first.lineno)
                indent = " " * (int(function.col_offset or 0) + 4)
                insertion = "".join(indent + part + "\n" for part in import_text.splitlines())
                edits.append((insertion_line, insertion_line, insertion))
            fixes.append(
                f"{Path(path_text).name}: moved cyclic import from {import_node.module} "
                f"into {len(users)} callable use site(s)"
            )
        for start, end, replacement in sorted(edits, key=lambda item: (item[0], item[1]), reverse=True):
            lines[start:end] = [replacement] if replacement else []
        corrected = "".join(lines)
        for index, record in enumerate(stabilized):
            if record[0] == path_text:
                stabilized[index] = (path_text, original, corrected)
                break
    return stabilized, fixes


def remove_project_edit_unused_imports(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove unused generated import aliases without discarding used siblings."""

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        if Path(path_text).name == "__init__.py":
            continue
        try:
            tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        loaded_names = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        module_import_ids = {
            id(node) for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        module_bindings = {
            alias.asname or (
                alias.name.split(".", 1)[0]
                if isinstance(node, ast.Import)
                else alias.name
            )
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
            if alias.name != "*"
        }
        replacements: list[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            kept_aliases = [
                alias
                for alias in node.names
                if alias.name == "*"
                or (
                    alias.asname or (
                        alias.name.split(".", 1)[0]
                        if isinstance(node, ast.Import)
                        else alias.name
                    )
                ) in loaded_names
            ]
            bindings = [
                alias.asname or (
                    alias.name.split(".", 1)[0]
                    if isinstance(node, ast.Import)
                    else alias.name
                )
                for alias in node.names
                if alias.name != "*"
            ]
            if id(node) not in module_import_ids and set(bindings) <= module_bindings:
                kept_aliases = []
            if len(kept_aliases) == len(node.names):
                continue
            if kept_aliases:
                node.names = kept_aliases
                replacement = ast.unparse(node)
            else:
                replacement = ""
            replacements.append((
                node.lineno - 1,
                int(node.end_lineno or node.lineno),
                replacement,
            ))
        if not replacements:
            continue
        fixes_start = len(fixes)
        lines = source.splitlines(keepends=True)
        for start, end, replacement in sorted(replacements, reverse=True):
            lines[start:end] = [replacement + "\n"] if replacement else []
            fixes.append(f"{Path(path_text).name}: removed unused import alias")
        final_source = "".join(lines)
        try:
            compile(
                ast.parse(final_source, filename=path_text),
                path_text,
                "exec",
            )
        except (SyntaxError, ValueError):
            del fixes[fixes_start:]
            continue
        updated[index] = (path_text, original, final_source)
    return updated, fixes


def _format_generated_docstring_layout(source: str) -> str:
    """Indent structured docstring content consistently with its owner.

    :param source: parseable Python source
    :return: source with readable multi-line docstrings
    """

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    lines = source.splitlines()
    expressions: dict[int, ast.Expr] = {}
    owners: list[ast.AST] = [tree]
    owners.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for owner in owners:
        body = getattr(owner, "body", None)
        if not body:
            continue
        expression = body[0]
        if (
            isinstance(expression, ast.Expr)
            and isinstance(expression.value, ast.Constant)
            and isinstance(expression.value.value, str)
        ):
            expressions[id(expression)] = expression
    for expression in sorted(
        expressions.values(),
        key=lambda item: item.lineno,
        reverse=True,
    ):
        content = str(expression.value.value)
        if "\\" in content or '"""' in content:
            continue
        cleaned = inspect.cleandoc(content)
        content_lines = [line.rstrip() for line in cleaned.splitlines()]
        if not content_lines:
            continue
        summary_lines = textwrap.wrap(
            content_lines[0],
            width=max(48, 92 - int(expression.col_offset or 0)),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [content_lines[0]]
        content_lines = [*summary_lines, *content_lines[1:]]
        wrapped_content: list[str] = []
        available_width = max(48, 92 - int(expression.col_offset or 0))
        for content_line in content_lines:
            if not content_line.lstrip().startswith(":"):
                wrapped_content.append(content_line)
                continue
            wrapped_content.extend(
                textwrap.wrap(
                    content_line.strip(),
                    width=available_width,
                    subsequent_indent="    ",
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [content_line]
            )
        content_lines = wrapped_content
        first_field = next(
            (
                index
                for index, line in enumerate(content_lines)
                if line.lstrip().startswith(":")
            ),
            -1,
        )
        if first_field > 0 and content_lines[first_field - 1].strip():
            content_lines.insert(first_field, "")
        indent = " " * int(expression.col_offset or 0)
        if len(content_lines) == 1:
            rendered = [f'{indent}"""{content_lines[0]}"""']
        else:
            rendered = [f'{indent}"""{content_lines[0]}']
            rendered.extend(
                indent + line if line else ""
                for line in content_lines[1:]
            )
            rendered.append(f'{indent}"""')
        start = expression.lineno - 1
        end = int(expression.end_lineno or expression.lineno)
        lines[start:end] = rendered
    return "\n".join(lines).rstrip() + "\n"


def _split_python_parameters(parameters: str) -> list[str]:
    """Split one generated signature without breaking nested expressions.

    :param parameters: text between the signature parentheses
    :return: ordered top-level parameter fragments
    """

    values: list[str] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    for index, character in enumerate(parameters):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in {'"', "'"}:
            quote = character
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            values.append(parameters[start:index].strip())
            start = index + 1
    tail = parameters[start:].strip()
    if tail:
        values.append(tail)
    return values


def _format_generated_function_signatures(source: str) -> str:
    """Normalize default spacing and wrap long one-line signatures.

    :param source: parseable Python source
    :return: source with stable generated signatures
    """

    formatted: list[str] = []
    pattern = re.compile(
        r"^(?P<indent>\s*)(?P<async>async\s+)?def\s+"
        r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<params>.*)\)"
        r"(?P<return>\s*->\s*.+)?\s*:\s*$"
    )
    for line in source.splitlines():
        match = pattern.match(line)
        if match is None:
            formatted.append(line)
            continue
        parameters = _split_python_parameters(match.group("params"))
        normalized: list[str] = []
        for parameter in parameters:
            assignment = re.match(r"^(.*?)(?<![=!<>])=(?!=)(.*)$", parameter)
            normalized.append(
                f"{assignment.group(1).rstrip()} = {assignment.group(2).lstrip()}"
                if assignment
                else parameter
            )
        prefix = (
            f"{match.group('indent')}{match.group('async') or ''}"
            f"def {match.group('name')}"
        )
        suffix = match.group("return") or ""
        single_line = f"{prefix}({', '.join(normalized)}){suffix}:"
        if len(single_line) <= 100:
            formatted.append(single_line)
            continue
        formatted.append(prefix + "(")
        formatted.extend(
            f"{match.group('indent')}    {parameter},"
            for parameter in normalized
        )
        formatted.append(f"{match.group('indent')}){suffix}:")
    return "\n".join(formatted).rstrip() + "\n"


def _format_generated_long_constant_mappings(source: str) -> str:
    """Wrap long top-level constant mappings without changing their AST.

    :param source: Parseable Python source.
    :return: Source with long call-valued constant entries expanded.
    """

    formatted: list[str] = []
    for line in source.splitlines():
        if len(line) <= 100 or not re.match(r"^[A-Z][A-Z0-9_]*\s*=\s*\{", line):
            formatted.append(line)
            continue
        try:
            statement = ast.parse(line).body[0]
        except SyntaxError:
            formatted.append(line)
            continue
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Dict)
            and all(key is not None for key in statement.value.keys)
        ):
            formatted.append(line)
            continue
        target = statement.targets[0].id
        replacement = [f"{target} = {{"]
        for key, value in zip(statement.value.keys, statement.value.values):
            key_text = ast.unparse(key)
            if isinstance(value, ast.Call):
                replacement.append(
                    f"    {key_text}: {ast.unparse(value.func)}("
                )
                replacement.extend(
                    f"        {ast.unparse(argument)},"
                    for argument in value.args
                )
                replacement.extend(
                    f"        {keyword.arg}={ast.unparse(keyword.value)},"
                    for keyword in value.keywords
                    if keyword.arg is not None
                )
                replacement.append("    ),")
            else:
                replacement.append(f"    {key_text}: {ast.unparse(value)},")
        replacement.append("}")
        formatted.extend(replacement)
    return "\n".join(formatted).rstrip() + "\n"


def _render_generated_dict(
    value: ast.Dict,
    *,
    prefix: str,
    indent: int,
) -> list[str]:
    """Render a generated dictionary with one reviewable entry per line.

    :param value: Dictionary expression to render.
    :param prefix: Text preceding the dictionary opening brace.
    :param indent: Indentation of the containing statement.
    :return: Rendered source lines.
    """

    lines = [prefix + "{"]
    child_indent = " " * (indent + 4)
    for key, item in zip(value.keys, value.values):
        if key is None:
            lines.append(f"{child_indent}**{ast.unparse(item)},")
            continue
        entry_prefix = f"{child_indent}{ast.unparse(key)}: "
        if isinstance(item, ast.Dict):
            nested = _render_generated_dict(
                item,
                prefix=entry_prefix,
                indent=indent + 4,
            )
            nested[-1] += ","
            lines.extend(nested)
        else:
            lines.append(f"{entry_prefix}{ast.unparse(item)},")
    lines.append(" " * indent + "}")
    return lines


def _format_generated_long_statements(source: str) -> str:
    """Wrap long generated returns and comprehension assignments.

    :param source: Parseable Python source.
    :return: Source with common long AST statements expanded.
    """

    formatted: list[str] = []
    for line in source.splitlines():
        if len(line) <= 100:
            formatted.append(line)
            continue
        indent_text = line[: len(line) - len(line.lstrip())]
        stripped = line.strip()
        try:
            statement = ast.parse(stripped).body[0]
        except SyntaxError:
            formatted.append(line)
            continue
        if isinstance(statement, ast.Return) and isinstance(statement.value, ast.Dict):
            formatted.extend(_render_generated_dict(
                statement.value,
                prefix=indent_text + "return ",
                indent=len(indent_text),
            ))
            continue
        if isinstance(statement, ast.Return) and isinstance(
            statement.value,
            (ast.ListComp, ast.SetComp, ast.GeneratorExp),
        ):
            expression = statement.value
            generator = expression.generators[0]
            opening, closing = (
                ("[", "]") if isinstance(expression, ast.ListComp)
                else ("{", "}") if isinstance(expression, ast.SetComp)
                else ("(", ")")
            )
            formatted.extend([
                indent_text + "return " + opening,
                f"{indent_text}    {ast.unparse(expression.elt)}",
                f"{indent_text}    for {ast.unparse(generator.target)} "
                f"in {ast.unparse(generator.iter)}",
                *(
                    f"{indent_text}    if {ast.unparse(condition)}"
                    for condition in generator.ifs
                ),
                indent_text + closing,
            ])
            continue
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            assignment_prefix = (
                f"{indent_text}{statement.targets[0].id} = "
            )
            if isinstance(statement.value, ast.SetComp):
                generator = statement.value.generators[0]
                formatted.extend([
                    assignment_prefix + "{",
                    f"{indent_text}    {ast.unparse(statement.value.elt)}",
                    f"{indent_text}    for {ast.unparse(generator.target)} "
                    f"in {ast.unparse(generator.iter)}",
                    *(
                        f"{indent_text}    if {ast.unparse(condition)}"
                        for condition in generator.ifs
                    ),
                    indent_text + "}",
                ])
                continue
            if (
                isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and len(statement.value.args) > 1
            ):
                formatted.extend([
                    assignment_prefix + ast.unparse(statement.value.func) + "(",
                    *(
                        f"{indent_text}    {ast.unparse(argument)},"
                        for argument in statement.value.args
                    ),
                    *(
                        f"{indent_text}    {keyword.arg}="
                        f"{ast.unparse(keyword.value)},"
                        for keyword in statement.value.keywords
                        if keyword.arg
                    ),
                    indent_text + ")",
                ])
                continue
            if (
                isinstance(statement.value, ast.Call)
                and len(statement.value.args) == 1
                and isinstance(statement.value.args[0], ast.GeneratorExp)
            ):
                generator_expression = statement.value.args[0]
                generator = generator_expression.generators[0]
                formatted.extend([
                    assignment_prefix + ast.unparse(statement.value.func) + "(",
                    f"{indent_text}    {ast.unparse(generator_expression.elt)}",
                    f"{indent_text}    for {ast.unparse(generator.target)} "
                    f"in {ast.unparse(generator.iter)}",
                    *(
                        f"{indent_text}    if {ast.unparse(condition)}"
                        for condition in generator.ifs
                    ),
                    indent_text + ")",
                ])
                continue
        formatted.append(line)
    return "\n".join(formatted).rstrip() + "\n"


def format_project_edit_generated_python(
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Normalize complete generated Python files before final validation."""

    updated = list(generated_files)
    fixes: list[str] = []
    for index, (path_text, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path_text)
            has_redundant_suite_indent = any(
                node.body
                and int(node.body[0].col_offset or 0) > int(node.col_offset or 0) + 4
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            )
            if has_redundant_suite_indent:
                encoding_line = (
                    source.splitlines()[0]
                    if re.match(r"^#.*coding[:=]", source)
                    else ""
                )
                formatted = ast.unparse(tree).rstrip() + "\n"
                if encoding_line:
                    formatted = encoding_line + "\n" + formatted
            else:
                formatted = source.rstrip() + "\n"
            formatted_tree = ast.parse(formatted, filename=path_text)
            lines = formatted.splitlines()
            top_imports = [
                node for node in formatted_tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom))
            ]
            if top_imports:
                import_lines = [ast.unparse(node) for node in top_imports]
                import_lines.sort(
                    key=lambda line: (
                        0 if line.startswith("from __future__") else
                        1 if (
                            line.split()[1].split(".", 1)[0]
                            if line.startswith(("import ", "from "))
                            else ""
                        ) in sys.stdlib_module_names else 2,
                        0 if line.startswith("import ") else 1,
                        line,
                    )
                )
                start = top_imports[0].lineno - 1
                end = int(top_imports[-1].end_lineno or top_imports[-1].lineno)
                lines[start:end] = import_lines
                formatted_tree = ast.parse("\n".join(lines) + "\n", filename=path_text)
            for node in sorted(
                (
                    node for node in formatted_tree.body
                    if not isinstance(node, (ast.Import, ast.ImportFrom))
                ),
                key=lambda item: item.lineno,
                reverse=True,
            ):
                insertion = node.lineno - 1
                while insertion > 0 and not lines[insertion - 1].strip():
                    del lines[insertion - 1]
                    insertion -= 1
                lines[insertion:insertion] = ["", ""]
            formatted = "\n".join(lines).rstrip() + "\n"
            formatted = _format_generated_docstring_layout(formatted)
            formatted = _format_generated_function_signatures(formatted)
            formatted = _format_generated_long_constant_mappings(formatted)
            formatted = _format_generated_long_statements(formatted)
            if not re.match(r"^#.*coding[:=]", source):
                formatted = formatted.lstrip("\n")
            compile(ast.parse(formatted, filename=path_text), path_text, "exec")
        except (SyntaxError, ValueError):
            continue
        if formatted != source:
            updated[index] = (path_text, original, formatted)
            fixes.append(f"{Path(path_text).name}: normalized generated Python formatting")
    return updated, fixes


def project_edit_plan_fingerprint(plan: ProjectEditPlan) -> str:
    """Fingerprint the grounded target so an approved plan cannot resume stale code."""

    discovery = dict(plan.discovery or {})
    best_target = dict(discovery.get("best_target") or {})
    path = Path(str(best_target.get("path") or plan.active_path or ""))
    digest = hashlib.sha256()
    digest.update(str(path).encode("utf-8", errors="replace"))
    index_revision = str(
        best_target.get("index_revision")
        or discovery.get("index_revision")
        or ""
    )
    if index_revision:
        digest.update(index_revision.encode("ascii", errors="replace"))
        return digest.hexdigest()
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"<missing>")
    return digest.hexdigest()


def inspect_project_edit_structured_syntax(model_response: str) -> list[dict[str, Any]]:
    """Find independently parseable Python snippets with syntax errors in a change payload."""

    text = str(model_response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
        return []

    failures: list[dict[str, Any]] = []
    parseable_actions = {
        "create",
        "modify",
        "replace_symbol",
        "insert_before_symbol",
        "insert_after_symbol",
    }
    for index, change in enumerate(payload["changes"]):
        if not isinstance(change, dict):
            continue
        action = str(change.get("action") or "")
        path = str(change.get("path") or "")
        source = str(change.get("new_content") or "")
        if action not in parseable_actions or not path.lower().endswith(".py") or not source.strip():
            continue
        candidate = source if action == "create" else textwrap.dedent(source)
        try:
            ast.parse(candidate, filename=path)
        except SyntaxError as exc:
            failures.append(
                {
                    "change_index": index,
                    "action": action,
                    "path": path,
                    "target_symbol": str(change.get("target_symbol") or ""),
                    "source": source,
                    "error": f"{exc.msg} at line {exc.lineno}",
                }
            )
    return failures


def build_project_edit_syntax_repair_stage(
    issue: dict[str, Any],
    *,
    attempt: int,
) -> ProjectEditPromptStage:
    """Build a bounded small-model task that repairs one generated Python snippet."""

    profile = "small" if attempt <= 1 else "standard"
    source = str(issue.get("source") or "")
    prompt = f"""Repair only the Python syntax in this generated change snippet.

Operation: {issue.get('action')}
Target: {issue.get('path')}::{issue.get('target_symbol') or '(file)'}
Parser error: {issue.get('error')}

Generated source:
```python
{source}
```

Preserve the intended behavior, names, signature, docstring, and indentation semantics.
Do not add imports, placeholders, ellipses, new behavior, Markdown, or explanation.
Return exactly one JSON object containing corrected_source.
"""
    return ProjectEditPromptStage(
        key=f"syntax_subagent_{attempt}",
        label=f"Repairing one generated syntax defect ({attempt}/2)",
        system_prompt=(
            "You are a bounded Python syntax repair worker. Fix only the supplied parser error and "
            "return source that ast.parse accepts without changing behavior."
        ),
        user_prompt=prompt,
        model_tier="local_code",
        num_ctx=5120 if profile == "small" else 6144,
        num_predict=1400 if profile == "small" else 1800,
        timeout=90 if profile == "small" else 120,
        no_progress_seconds=15,
        prefer_coder=True,
        coder_preference=profile,
        response_format=PROJECT_EDIT_SYNTAX_REPAIR_SCHEMA,
    )


def apply_project_edit_syntax_repair(
    model_response: str,
    *,
    change_index: int,
    repair_response: str,
) -> str:
    """Replace one structured change snippet with a syntax worker's corrected source."""

    try:
        payload = json.loads(str(model_response or "").strip())
        repair = json.loads(str(repair_response or "").strip())
        corrected = repair.get("corrected_source")
        changes = payload.get("changes")
        if not isinstance(corrected, str) or not isinstance(changes, list):
            return model_response
        if not 0 <= int(change_index) < len(changes) or not isinstance(changes[int(change_index)], dict):
            return model_response
        try:
            ast.parse(textwrap.dedent(corrected), filename=str(changes[int(change_index)].get("path") or "<generated>"))
        except SyntaxError:
            return model_response
        changes[int(change_index)]["new_content"] = corrected
        return json.dumps(payload, ensure_ascii=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return model_response


def build_project_edit_leaf_candidate(
    work_units: ProjectEditLeafWorkUnits,
    *,
    helper_source: str,
    integration_source: str,
    test_source: str,
) -> str:
    """Compose validated leaf sources into one typed, preview-only candidate."""

    changes = [
        {
            "action": "insert_before_symbol",
            "path": work_units.target_path,
            "target_symbol": work_units.integration_symbol,
            "original_content": "",
            "new_content": helper_source,
        },
        {
            "action": "replace_symbol",
            "path": work_units.target_path,
            "target_symbol": work_units.integration_symbol,
            "original_content": "",
            "new_content": integration_source,
        },
        {
            "action": "ensure_import",
            "path": work_units.test_path,
            "target_symbol": work_units.owner_module,
            "original_content": "",
            "new_content": work_units.helper_name,
        },
        {
            "action": "insert_after_symbol",
            "path": work_units.test_path,
            "target_symbol": work_units.test_anchor_symbol,
            "original_content": "",
            "new_content": test_source,
        },
    ]
    return json.dumps(
        {
            "changes": changes,
            "report": {
                "changed": [work_units.helper_name, work_units.integration_symbol],
                "reused": [work_units.test_anchor_symbol],
                "verification": ["parse", "compile", "focused unittest"],
                "remaining_gaps": [],
                "requirement_coverage": [],
            },
            "blocked_reason": "",
        },
        ensure_ascii=True,
    )


def model_for_project_edit_stage(
    stage: ProjectEditPromptStage,
    settings: dict[str, Any] | None = None,
    *,
    selected_model: str | None = None,
) -> str:
    """Return the configured model for a project-edit stage.

    Reuses the existing router model tier settings instead of defining another
    model-routing table. Context-heavy planning stages can use a smaller plan
    model while patch/code generation can reserve the coder model.
    """

    settings = dict(settings or {})
    if selected_model:
        return str(selected_model).removeprefix("ollama:").strip()
    tier = (stage.model_tier or "").strip()
    if tier == "local_plan":
        model = settings.get("router_local_plan") or settings.get("plan_model") or settings.get("general_model")
    elif tier == "local_semantic":
        model = settings.get("semantic_intent_model") or "qwen3:4b-instruct"
    elif tier == "local_semantic_verify":
        model = settings.get("semantic_verifier_model") or "qwen3:4b-instruct"
    elif tier == "local_deep":
        model = settings.get("router_local_deep") or settings.get("model") or selected_model
    elif tier == "local_fast":
        model = settings.get("router_fast_llm_model") or settings.get("router_local_plan") or settings.get("general_model")
    elif tier == "local_code":
        from tech_connector.services.ollama_service import code_model_for_profile
        import re

        profile = str(stage.coder_preference or "small").strip().lower()
        base_code_model = settings.get("router_local_code") or settings.get("code_model")
        
        model = (
            settings.get(f"router_local_code_{profile}")
            or settings.get(f"code_model_{profile}")
        )
        if not model:
            default_profile_model = code_model_for_profile(profile)
            if base_code_model:
                def model_size(name: str) -> float:
                    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", str(name or "").lower())
                    return float(match.group(1)) if match else 0.0
                
                if model_size(default_profile_model) > model_size(base_code_model):
                    model = base_code_model
                else:
                    model = default_profile_model
            else:
                model = default_profile_model
    else:
        model = None
    selected = str(model or selected_model or settings.get("model") or "qwen2.5-coder:7b")
    # Preserve the configured tier for telemetry, approval fingerprints, and
    # deterministic tests. The Ollama transport resolves installed aliases at
    # call time; doing it here silently changed the user's routing policy.
    return selected.removeprefix("ollama:").strip()


def _compact_indexed_import_context(imports: list[dict[str, Any]], *, max_chars: int = 900) -> str:
    """Render useful import evidence already captured by the project index."""

    lines: list[str] = []
    for item in imports:
        raw = str(item.get("import_name") or "").strip()
        if not raw:
            module = str(item.get("module") or "").strip()
            name = str(item.get("name") or "").strip()
            alias = str(item.get("alias") or "").strip()
            if module and name:
                raw = f"from {'.' * int(item.get('level') or 0)}{module} import {name}"
            elif module:
                raw = f"import {module}"
            if alias:
                raw += f" as {alias}"
        if raw in lines:
            continue
        if lines and len("\n".join(lines + [raw])) > max_chars:
            lines.append("# Additional existing imports omitted from this compact context.")
            break
        lines.append(raw)
    return "\n".join(lines)


def _project_edit_requires_patch(prompt: str) -> bool:
    lower = (prompt or "").lower()
    if re.search(r"\b(do not edit|do not change|do not make changes|don't edit|no edits|without editing|explain how|plan only)\b", lower):
        return False
    if re.search(r"\b(what functions|which functions|where is|where are|list|show|explain|summarize|inspect|identify|determine|report what you find)\b", lower) and not re.search(
        r"\b(then|after that|and add|and create|implement|patch|modify|change|update|fix|wire|connect|build it|make it)\b",
        lower,
    ):
        return False
    return bool(
        re.search(
            r"\b(add|create|write|generate|implement|insert|improve|refactor|fix|update|patch|wire|connect|repair|make|build)\b",
            lower,
        )
    )


def validate_project_edit_plan_output(plan: ProjectEditPlan, output: str) -> list[str]:
    """Return evidence failures that make a model-authored plan unsafe to hand off."""

    text = str(output or "").strip()
    if len(text) < 120:
        return ["Planning output was empty or too short to establish a grounded handoff."]

    errors: list[str] = []
    lowered = text.lower()
    patch_markers = ("<modify_file", "<create_file", "<<<< original", "```")
    if any(marker in lowered for marker in patch_markers) or re.search(
        r"(?m)^\s*(?:async\s+def|def|class)\s+[A-Za-z_]\w*", text
    ):
        errors.append("Planning output contained implementation code instead of a target plan.")

    discovery = dict(plan.discovery or {})
    candidates: list[dict[str, Any]] = []
    best_target = discovery.get("best_target")
    if isinstance(best_target, dict) and best_target:
        candidates.append(best_target)
    for key in ("candidates", "targets"):
        candidates.extend(item for item in discovery.get(key) or [] if isinstance(item, dict))

    known_paths: list[str] = []
    for item in candidates:
        path = str(item.get("path") or "").strip()
        if path and path.lower() not in {known.lower() for known in known_paths}:
            known_paths.append(path)
    if plan.active_path and plan.active_path.lower() not in {path.lower() for path in known_paths}:
        known_paths.append(plan.active_path)
    expanded_paths = list(known_paths)
    for path_text in known_paths:
        path = Path(path_text)
        if not path.is_file():
            continue
        split_prefixes = {path.stem, path.stem.removesuffix("_service")}
        expanded_paths.extend(
            str(candidate)
            for prefix in split_prefixes
            for candidate in sorted(path.parent.glob(f"{prefix}_part_*.py"))
        )
    known_paths = list(dict.fromkeys(expanded_paths))

    if known_paths and not any(
        path.lower() in lowered or Path(path).name.lower() in lowered
        for path in known_paths
    ):
        errors.append("Planning output did not identify any evidence-backed target file.")
    known_symbols: list[str] = []
    known_symbol_keys: set[str] = set()
    for item in candidates:
        for symbol in item.get("symbols") or []:
            name = str(symbol.get("name") if isinstance(symbol, dict) else symbol).strip()
            if name and name.lower() not in known_symbol_keys:
                known_symbols.append(name)
                known_symbol_keys.add(name.lower())
    if known_paths:
        try:
            from tech_connector.services.file_index_service import file_index_service

            for path in known_paths:
                snapshot = file_index_service.get_file_snapshot(path, symbol_limit=500)
                if snapshot is None or not list(snapshot.get("symbols") or []):
                    snapshot = file_index_service.get_bounded_python_snapshot(
                        path,
                        project_roots=list(discovery.get("project_roots") or []),
                        symbol_limit=500,
                    )
                for symbol in (snapshot or {}).get("symbols") or []:
                    name = str(symbol.get("qualname") or symbol.get("name") or "").strip()
                    bare_name = name.rsplit(".", 1)[-1]
                    for candidate_name in (name, bare_name):
                        if candidate_name and candidate_name.lower() not in known_symbol_keys:
                            known_symbols.append(candidate_name)
                            known_symbol_keys.add(candidate_name.lower())
        except Exception:
            pass
    if known_symbols and not any(
        re.search(rf"\b{re.escape(name.lower())}\b", lowered)
        for name in known_symbols
    ):
        errors.append("Planning output did not name any indexed existing symbol to inspect or reuse.")
    if _project_edit_requires_patch(plan.prompt) and any(
        phrase in lowered for phrase in ("search-only", "search only", "analysis-only", "analysis only")
    ):
        errors.append("Planning output selected a non-mutation stage for an implementation request.")
    if not any(term in lowered for term in ("reuse", "existing", "helper", "function", "class", "service")):
        errors.append("Planning output did not identify existing project behavior to reuse or inspect.")
    if not any(term in lowered for term in ("test", "verify", "validation", "compile", "import")):
        errors.append("Planning output omitted concrete implementation verification gates.")
    if "plan self-check" not in lowered:
        errors.append("Planning output omitted its evidence and scope self-check.")
    mentioned_python_files = {
        match.lower()
        for match in re.findall(r"[A-Za-z0-9_./\\-]+\.py", text, flags=re.IGNORECASE)
    }
    if "no other files" in lowered and len(mentioned_python_files) > 1:
        errors.append("Planning output contradicted its own multi-file change scope.")
    return errors


def _project_edit_requests_new_artifact_plan(prompt: str) -> bool:
    """Preserve a new generated deliverable even when live mutation is forbidden."""
    lower = " ".join(str(prompt or "").lower().split())
    implementation_verb = bool(
        re.search(
            r"\b(create|write|generate|implement|make|build|design)\b",
            lower,
        )
    )
    new_artifact_scope = bool(
        re.search(
            r"\b(multi[- ]file|new (?:tool|app|application|service|package|module|"
            r"library|system|artifact)|from scratch|complete (?:python |code |"
            r"software )?(?:artifact|implementation|package|tool|application|system)|"
            r"generated (?:code|artifact|implementation))\b",
            lower,
        )
    )
    return implementation_verb and new_artifact_scope


def build_project_edit_artifact_manifest_stage(
    plan: ProjectEditPlan,
    *,
    approved_plan: str = "",
) -> ProjectEditPromptStage | None:
    """Build a bounded manifest stage for a new disposable multi-file artifact."""

    from tech_connector.services.prompt.artifact_contract_service import restricts_live_mutation

    if not (
        _project_edit_requires_patch(plan.prompt)
        or _project_edit_requests_new_artifact_plan(plan.prompt)
    ) or not restricts_live_mutation(plan.prompt):
        return None
    requirement_ledger = extract_project_edit_artifact_requirements(plan.prompt)
    artifact_requirements = [
        item for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "artifact"
    ]
    requirement_lines = "\n".join(
        f"- {item['id']}: {item['text']}" for item in artifact_requirements
    )
    workflow_lines = "\n".join(
        f"- {item['id']}: {item['text']}"
        for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "workflow"
    )
    return ProjectEditPromptStage(
        key="artifact_manifest",
        label="Designing generated file contract",
        system_prompt=(
            "You are a senior software architect defining a bounded Python artifact. "
            "Return only the requested JSON manifest. Do not emit source code or prose."
        ),
        user_prompt=f"""Original objective:
{plan.prompt}

Approved implementation plan:
{approved_plan or "(none supplied)"}

Project root:
{(plan.discovery.get("project_roots") or [""])[0]}

Define 2-5 focused Python modules and unittest files that collectively satisfy every requested behavior. Group
closely related behavior in one owner module and keep each requirement phrase concise. Put production files before
their consumers and tests last. Use project-relative paths only. Keep files
inside existing top-level source and examples test conventions. Do not use dot-prefixed folders, SQLite files,
third-party dependencies, placeholders, or live user data. Every requirement from the objective must be owned by
at least one file. Dependencies may name only another path in this manifest. Every test file must set is_test=true,
must be under tech_connector/examples/tests/, and its filename must start with test_. Production files must set
is_test=false and must not use a test_ filename.

For each production file, public_symbols must list exact public API names or signatures, contracts must state inputs,
outputs, errors, state transitions, and invariants, algorithm_steps must describe the actual implementation algorithm,
and validation_steps must identify concrete readback or test proof. Test files must name the public behavior they call,
the fixture strategy, and success/failure/recovery assertions. Every behavior requirement must be owned by at least one
production file and at least one test file. Test files may not duplicate the same requirement set and purpose.

Populate every field of the top-level integration_contracts object with the exact package-wide source of truth that
all files must obey. canonical_owners names the one file/API that owns each shared record/type/constant. signatures
contains exact callable signatures including defaults. shared_invariants contains state, bounds, and round-trip
rules. data_layout contains exact byte/file/message field order, sizes, endianness, markers, flags, and units when
relevant. errors contains shared exception and rejection behavior. These are contract statements, not a contracts.py
file proposal, and must be concrete enough that independent file workers produce compatible code without guessing.

Authoritative requirement ledger:
{requirement_lines}

Assign every requirement ID to at least one owning file in requirement_ids. Use only IDs from this ledger. The
application validates complete ID coverage and gives each worker the original requirement text, so do not merge,
drop, invent, or repeat requirement text in the JSON.

The following workflow requirements are owned and validated by the project-edit controller. Do not create files,
tests, APIs, or requirement ownership for them:
{workflow_lines or "- none"}
""",
        model_tier="local_semantic",
        num_ctx=8192,
        num_predict=3600,
        timeout=150,
        no_progress_seconds=20,
        prefer_coder=False,
        coder_preference="small",
        response_format=PROJECT_EDIT_ARTIFACT_MANIFEST_SCHEMA,
    )


def project_edit_preview_error_score(errors: list[str]) -> int:
    """Rank candidate failures so a nearly complete patch beats malformed output."""

    score = 0
    for error in errors:
        lowered = str(error or "").lower()
        if any(marker in lowered for marker in ("json did not parse", "syntax validation failed", "did not parse")):
            score += 100
        elif any(marker in lowered for marker in ("requested public symbols", "cannot import its requested")):
            score += 70
        elif any(marker in lowered for marker in ("symbol was not found", "cannot resolve", "missing file")):
            score += 50
        elif any(marker in lowered for marker in ("docstring", "focused test file")):
            score += 5
        elif "import" in lowered:
            score += 20
        else:
            score += 30
    return score


def _edit_python_symbol_source(
    source: str,
    *,
    target_symbol: str,
    replacement: str,
    filename: str,
    operation: str,
) -> tuple[bool, str, str]:
    """Edit a top-level or ``Class.method`` symbol using AST-owned boundaries."""

    if not replacement.strip():
        return False, source, f"Replacement source is empty for symbol {target_symbol}: {filename}"
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return False, source, f"Cannot resolve {target_symbol}; existing Python did not parse: {exc}"

    parts = [part for part in target_symbol.split(".") if part]
    if not parts or len(parts) > 2:
        return False, source, f"Unsupported target symbol path: {target_symbol}"
    node: ast.AST | None = next(
        (item for item in tree.body if getattr(item, "name", None) == parts[0]),
        None,
    )
    if len(parts) == 1 and node is None:
        nested_matches = [
            child
            for parent in tree.body
            if isinstance(parent, ast.ClassDef)
            for child in parent.body
            if getattr(child, "name", None) == parts[0]
        ]
        if len(nested_matches) == 1:
            node = nested_matches[0]
        elif len(nested_matches) > 1:
            return False, source, f"Bare method target is ambiguous: {target_symbol} in {filename}"
    if len(parts) == 2 and isinstance(node, ast.ClassDef):
        class_node = node
        node = next(
            (item for item in class_node.body if getattr(item, "name", None) == parts[1]),
            None,
        )
        if node is None and operation in {"insert_before_symbol", "insert_after_symbol"}:
            if class_node.body:
                node = class_node.body[-1]
                operation = "insert_after_symbol"
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        lines = source.splitlines(keepends=True)
        matching_line_idx = -1
        target_clean = target_symbol.strip()
        for idx, line in enumerate(lines):
            if target_clean in line:
                matching_line_idx = idx
                break
        if matching_line_idx != -1 and operation in {"insert_before_symbol", "insert_after_symbol"}:
            start_offset = sum(len(line) for line in lines[:matching_line_idx])
            end_offset = sum(len(line) for line in lines[:matching_line_idx + 1])
            replacement_text = textwrap.dedent(replacement).strip("\r\n") + "\n"
            if operation == "insert_before_symbol":
                return True, source[:start_offset] + replacement_text + source[start_offset:], ""
            if operation == "insert_after_symbol":
                return True, source[:end_offset] + replacement_text + source[end_offset:], ""
        return False, source, f"Indexed Python symbol was not found: {target_symbol} in {filename}"

    decorators = list(getattr(node, "decorator_list", []) or [])
    start_line = min([int(getattr(item, "lineno", node.lineno)) for item in decorators] + [int(node.lineno)])
    end_line = int(getattr(node, "end_lineno", 0) or 0)
    if end_line < start_line:
        return False, source, f"Python symbol has invalid source bounds: {target_symbol} in {filename}"
    lines = source.splitlines(keepends=True)
    start_offset = sum(len(line) for line in lines[: start_line - 1])
    end_offset = sum(len(line) for line in lines[:end_line])
    indent = " " * int(getattr(node, "col_offset", 0) or 0)
    replacement_text = textwrap.dedent(replacement).strip("\r\n")
    if indent:
        replacement_text = textwrap.indent(replacement_text, indent)
    replacement_text += "\n"
    if operation == "replace_symbol":
        return True, source[:start_offset] + replacement_text + source[end_offset:], ""
    separator = "\n" if indent else "\n\n"
    if operation == "insert_before_symbol":
        return True, source[:start_offset] + replacement_text.rstrip() + separator + source[start_offset:], ""
    if operation == "insert_after_symbol":
        return True, source[:end_offset] + separator + replacement_text.lstrip("\r\n") + source[end_offset:], ""
    return False, source, f"Unsupported Python symbol operation: {operation}"


_HOST_RUNTIME_MODULES = {
    "bpy",
    "hou",
    "maya",
    "pyfbsdk",
    "substance_painter",
    "unreal",
}


_FORBIDDEN_EDIT_ROOT_MARKERS = tuple(
    marker.strip().lower()
    for marker in re.split(r"[;,]", os.getenv("TECH_CONNECTOR_FORBIDDEN_EDIT_PATH_MARKERS", "time_fighters 5.8"))
    if marker.strip()
)


def _is_forbidden_edit_path(path_text: str) -> bool:
    """Return true when a candidate edit path should never be written by design."""
    normalized = str(path_text or "").replace("\\", "/").lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _FORBIDDEN_EDIT_ROOT_MARKERS)


def _edit_error_for_forbidden_path(path_text: str) -> str:
    return (
        "Attempted edit target is inside a forbidden project root: "
        f"{path_text}. Set TECH_CONNECTOR_FORBIDDEN_EDIT_PATH_MARKERS to include/remove scope."
    )


def _parse_structured_project_changes(
    model_response: str,
    *,
    project_root: str | None,
    allowed_external_paths: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Parse the typed JSON change payload used by staged local coders."""

    text = str(model_response or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        return [], [], False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"Structured change JSON did not parse: {exc.msg} at line {exc.lineno}."], True
    if not isinstance(payload, dict):
        return [], ["Structured change payload must be a JSON object."], True

    raw_changes = payload.get("changes")
    if not isinstance(raw_changes, list):
        return [], ["Structured change payload is missing a changes list."], True
    errors: list[str] = []
    parsed: list[dict[str, Any]] = []
    root = Path(project_root).resolve() if project_root else None
    allowed_external = {
        str(Path(path).resolve()).casefold()
        for path in (allowed_external_paths or set())
    }
    for index, item in enumerate(raw_changes, start=1):
        if not isinstance(item, dict):
            errors.append(f"Structured change {index} must be an object.")
            continue
        action = str(item.get("action") or "").strip().lower()
        raw_path = str(item.get("path") or "").strip()
        if action not in {
            "create",
            "modify",
            "replace_symbol",
            "insert_before_symbol",
            "insert_after_symbol",
            "replace_text",
            "insert_before_text",
            "insert_after_text",
            "ensure_import",
        }:
            errors.append(f"Structured change {index} has unsupported action: {action or '(missing)' }.")
            continue
        if not raw_path:
            errors.append(f"Structured change {index} is missing a path.")
            continue
        normalized_path = raw_path
        if root is not None and _is_forbidden_edit_path(raw_path):
            candidate_path = Path(raw_path)
            if candidate_path.is_absolute():
                parts = candidate_path.parts
                for idx, part in enumerate(parts):
                    if part.lower() == "unreal_tools":
                        normalized_path = str(root.joinpath(*parts[idx:]))
                        break
                else:
                    normalized_path = str(root / candidate_path.name)
            elif root:
                normalized_path = raw_path
        raw_path = normalized_path
        if _is_forbidden_edit_path(raw_path):
            errors.append(_edit_error_for_forbidden_path(raw_path))
            continue
        path = Path(raw_path)
        if not path.is_absolute() and root is not None:
            path = root / path
        try:
            resolved_path = path.resolve()
        except OSError:
            resolved_path = path
        if action != "create" and root is not None and not resolved_path.exists():
            basename_matches = [
                candidate.resolve()
                for candidate in root.rglob(path.name)
                if candidate.is_file()
            ]
            if len(basename_matches) == 1:
                resolved_path = basename_matches[0]
            elif len(basename_matches) > 1:
                errors.append(
                    f"Structured change path is ambiguous within the project root: {raw_path}"
                )
                continue
        if root is not None:
            try:
                resolved_path.relative_to(root)
            except ValueError:
                if str(resolved_path).casefold() not in allowed_external:
                    errors.append(
                        "Structured change path is outside the project root: "
                        f"{resolved_path}"
                    )
                    continue
        new_content = item.get("new_content")
        if not isinstance(new_content, str):
            errors.append(f"Structured change {index} is missing string new_content.")
            continue
        raw_target = str(item.get("target_symbol") or "")
        change = {
            "action": action,
            "path": str(resolved_path),
            "target_symbol": raw_target if action in {"replace_text", "insert_before_text", "insert_after_text"} else raw_target.strip(),
            "new_content": new_content,
        }
        if action == "modify":
            original_content = item.get("original_content")
            if not isinstance(original_content, str) or not original_content:
                errors.append(f"Structured modify change {index} is missing exact original_content.")
                continue
            change["original_content"] = original_content
        parsed.append(change)

    blocked_reason = str(payload.get("blocked_reason") or "").strip()
    if blocked_reason and not parsed:
        errors.append(f"Coder reported a blocker: {blocked_reason}")
    return parsed, errors, True


_PLACEHOLDER_PUBLIC_NAMES = {
    "do_it",
    "foo",
    "bar",
    "new_class",
    "new_function",
    "placeholder",
    "stuff",
    "thing",
}


_UI_WIDGET_IDENTIFIER_STOPWORDS = {
    "a",
    "an",
    "and",
    "button",
    "combo",
    "in",
    "bound",
    "on",
    "the",
    "connect",
    "every",
    "value",
    "widget",
    "widgets",
}


def _infer_prompt_requirements(question: str) -> dict[str, bool]:
    """Infer generic runtime, UI, and API intent from a natural-language request."""

    lowered = (question or "").lower()
    signal_intent = bool(re.search(
        r"\b(clicked|signal|on\s+click|bind|value\s*changed|text\s*changed)\b"
        r"|\.connect\s*\(",
        lowered,
    ))
    explicit_qt_intent = bool(
        re.search(r"\b(?:qt|pyside6?|pyqt[56]?)\b", lowered)
    )
    explicit_control_intent = bool(re.search(
        r"\b(button|combo(?:\s*box)?|dropdown|spin(?:ner|\s*box)?|"
        r"text\s*(?:box|field)|line\s*edit|progress\s*bar)\b",
        lowered,
    ))
    explicit_ui_surface_intent = bool(
        re.search(r"\b(?:ui|dialog|widget|panel)\b", lowered)
        or re.search(
            r"\b(?:add|build|create|implement|launch|open|show)\b"
            r"[^\n.;]{0,60}\bwindow\b",
            lowered,
        )
    )
    ui_intent = bool(
        explicit_qt_intent
        or explicit_control_intent
        or explicit_ui_surface_intent
        or signal_intent
    )
    requirements: dict[str, bool] = {
        "needs_unreal_import": "unreal" in lowered,
        "needs_maya_import": any(
            token in lowered
            for token in ("maya", "blender", "motionbuilder", "pyfbsdk", "bpy")
        ),
        "needs_qt_import": ui_intent,
        "needs_signal_connect": ui_intent and signal_intent,
        "needs_factory_create_asset": "create_asset" in lowered and "unreal" in lowered,
        "needs_widget_entrypoint": bool(
            ui_intent
            and re.search(r"\b(dialog|window|widget)\b", lowered)
        )
        and any(
            token in lowered
            for token in (
                "add",
                "create",
                "implement",
                "build",
                "new",
                "launch",
                "show",
            )
        ),
    }
    return requirements


def _infer_ui_widget_requirements(question: str) -> list[tuple[str, str]]:
    """Infer explicit widget names and rough control kinds from prompt phrasing."""

    lowered = str(question or "").lower()
    qt_type_names = {
        name.casefold()
        for name in re.findall(r"\bQ[A-Z][A-Za-z0-9_]*\b", str(question or ""))
    }
    widget_requirements: dict[str, str] = {}

    noun_to_kind = (
        ("text box", "text"),
        ("text field", "text"),
        ("textbox", "text"),
        ("input box", "text"),
        ("input", "text"),
        ("line edit", "text"),
        ("dropdown", "combo"),
        ("combo box", "combo"),
        ("combobox", "combo"),
        ("spinner", "spin"),
        ("spin box", "spin"),
        ("spinbox", "spin"),
        ("button", "button"),
        ("progress bar", "progress"),
        ("progress", "progress"),
    )

    for noun, kind in noun_to_kind:
        noun_pattern = re.escape(noun)
        for expr in (
            rf"\b{noun_pattern}\b[^\\n]*?\b(?:for|named|called)\b[^\\n]*?`?([a-z_][a-z0-9_]*)`?",
            rf"`?([a-z_][a-z0-9_]*)`?[^\\n]*?\b(?:for|named|called)\b[^\\n]*?\b{noun_pattern}\b",
        ):
            for match in re.finditer(expr, lowered, flags=re.IGNORECASE):
                name = match.group(1).strip("`_") if match.groups() else ""
                if not name:
                    continue
                normalized_name = name.strip("`").strip("'\"")
                if (
                    re.fullmatch(r"[a-z_][a-z0-9_]*", normalized_name)
                    and normalized_name.lower() not in _UI_WIDGET_IDENTIFIER_STOPWORDS
                ):
                    widget_requirements.setdefault(normalized_name, kind)

    # Heuristic fallbacks from explicit widget-like identifiers.
    for name in re.findall(r"\b[a-z_][a-z0-9_]*\b", lowered):
        if re.search(
            r"(?:_btn$|button$|_combo$|_spin(?:ner|box)$|_input$|_label$|"
            r"_text(?:_input|_box)?$|_progress(?:_?bar)?$|_bar$)",
            name,
        ):
            kind = "button" if "_btn" in name or "button" in name else (
                "combo" if "_combo" in name else (
                    "spin" if "_spin" in name else (
                        "text" if "_text" in name or "_input" in name else (
                            "label" if "_label" in name else "progress"
                        )
                    )
                )
            )
            if (
                name not in _UI_WIDGET_IDENTIFIER_STOPWORDS
                and name not in qt_type_names
            ):
                widget_requirements.setdefault(name, kind)

    ordered = sorted(widget_requirements.items(), key=lambda item: (item[0], item[1]))
    return ordered


def _qt_widget_import_coverage(imported_modules: set[str], imported_names: set[str]) -> bool:
    """
    Determine whether generated imports provide a plausible Qt/PySide/PyQt surface.

    This intentionally checks for:
    - Known Qt/PySide/PyQt-style module names.
    - Uppercase QWidget-style constructor symbols (QLineEdit, QDialog, etc.).
    """

    qt_module_markers = (
        "qt",
        "pyside",
        "pyqt",
        "qtpy",
        "shiboken",
    )
    if any(
        any(marker in module for marker in qt_module_markers)
        for module in imported_modules
    ):
        return True
    return any(
        bool(re.match(r"^Q[A-Z][A-Za-z0-9_]*$", name))
        for name in imported_names
    )


def _expected_widget_accessor(widget_name: str, kind_hint: str | None = None) -> str | None:
    """Return the most likely value accessor for a widget kind/name."""

    lowered = widget_name.lower()
    if kind_hint == "spin" or "_spin" in lowered:
        return "value"
    if kind_hint == "combo":
        return "currentText"
    if kind_hint == "text":
        return "text"
    return None


def _widget_expected_constructors(kind_hint: str) -> set[str]:
    """Return likely Qt constructor classes for a widget-kind hint."""

    if kind_hint == "button":
        return {"QPushButton"}
    if kind_hint == "combo":
        return {"QComboBox"}
    if kind_hint == "spin":
        return {"QSpinBox", "QDoubleSpinBox"}
    if kind_hint == "text":
        return {"QLineEdit", "QTextEdit", "QPlainTextEdit"}
    if kind_hint == "progress":
        return {"QProgressBar", "ListProgressBar"}
    return set()


def _widget_ctor_base_name(ctor_name: str | None) -> str:
    if not ctor_name:
        return ""
    return str(ctor_name).rsplit(".", 1)[-1]


def _widget_ctor_is_imported(ctor_name: str, imported_names: set[str], top_level_names: set[str]) -> bool:
    base = _widget_ctor_base_name(ctor_name)
    return (
        ctor_name in imported_names
        or base in imported_names
        or ctor_name in top_level_names
        or base in top_level_names
        or (("." in ctor_name) and ctor_name.split(".", 1)[0] in imported_names)
    )


def _callable_signature_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return ast.unparse(func)
    return None


def _extract_self_chain_attr(expr: ast.AST) -> str | None:
    """Extract the attribute name immediately following ``self`` in an attribute chain."""

    attrs: list[str] = []
    current = expr
    while isinstance(current, ast.Attribute):
        attrs.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name) and current.id == "self" and attrs:
        return attrs[-1]
    return None


def _is_placeholder_callable(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in node.body:
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ):
            continue
        if isinstance(child, ast.Pass):
            continue
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and child.value.value is Ellipsis
        ):
            continue
        if isinstance(child, ast.Return) and child.value is None:
            continue
        return False
    return True


def _infer_signal_handler_requirements(question: str) -> set[str]:
    lowered = str(question or "").lower()
    if not lowered:
        return set()
    required: set[str] = set()
    patterns = (
        r"\b(?:connect|bind|wire)\b[^\n]{0,200}?\b(?:to|with)\b[^\n]{0,120}?`?(?:self\.)?([a-z_][a-z0-9_]*)`?(?:\(\))?(?:\b|$)",
        r"\b([a-z_][a-z0-9_]*)`?\s*\.\s*connect\(\s*self\.([a-z_][a-z0-9_]*)`?(?:\(\))?\s*\)",
        r"\bconnect\(\s*self\.([a-z_][a-z0-9_]*)`?(?:\(\))?\s*\)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            for group in match.groups():
                if not group:
                    continue
                name = group.strip("`'\" ")
                if re.fullmatch(r"[a-z_][a-z0-9_]*", name):
                    required.add(name)
    return required


def _is_placeholder_class(node: ast.ClassDef) -> bool:
    for child in node.body:
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ):
            continue
        if isinstance(child, ast.Pass):
            continue
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and child.value.value is Ellipsis
        ):
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _is_placeholder_callable(child):
                continue
        else:
            return False
    return True


def _imported_name_bindings(tree: ast.AST) -> set[str]:
    """Collect all symbols imported into module namespace."""

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                names.add("*")
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _method_uses_widget_access(node: ast.AST, widget_name: str, accessor: str | None = None) -> bool:
    """Check whether a method accesses a widget (optionally through a specific accessor)."""

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not isinstance(func, ast.Attribute):
            continue
        if (
            isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == widget_name
        ):
            if accessor is None:
                return True
            if func.attr == accessor:
                return True
    return False


def _method_updates_widget(node: ast.AST, widget_name: str) -> bool:
    """Return whether a handler writes observable state to a widget."""

    update_methods = {
        "addItem",
        "addItems",
        "clear",
        "display",
        "insertItem",
        "setChecked",
        "setCurrentIndex",
        "setCurrentText",
        "setEnabled",
        "setIcon",
        "setPalette",
        "setPixmap",
        "setPlainText",
        "setProperty",
        "setStyleSheet",
        "setText",
        "setValue",
        "setVisible",
    }
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in update_methods
            and isinstance(func.value, ast.Attribute)
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
            and func.value.attr == widget_name
        ):
            return True
    return False


def _unresolved_module_scope_names(tree: ast.Module) -> list[str]:
    """Return undefined names evaluated at module or class construction time."""

    available = set(dir(builtins))
    parent_by_node = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def inside_callable(node: ast.AST) -> bool:
        current = parent_by_node.get(id(node))
        while current is not None and not isinstance(current, ast.Module):
            if isinstance(
                current,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
            ):
                return True
            current = parent_by_node.get(id(current))
        return False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            available.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            available.update(
                alias.asname or alias.name.split(".", 1)[0]
                for alias in node.names
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            available.update(
                child.id
                for target in targets
                for child in ast.walk(target)
                if isinstance(child, ast.Name)
            )
    available.update(
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and not inside_callable(node)
    )
    available.update(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.name
        and not inside_callable(node)
    )
    unresolved: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if not inside_callable(node) and node.id not in available:
            unresolved.add(node.id)
    return sorted(unresolved)


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
                modules.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                modules.add(module)
                modules.add(module.split(".", 1)[0])
    return modules


def _node_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parent: dict[ast.AST, ast.AST] = {}
    for parent_node in ast.walk(tree):
        for child in ast.iter_child_nodes(parent_node):
            parent[child] = parent_node
    return parent


def _import_targets_module(node: ast.AST, module: str) -> bool:
    normalized = module.lower()
    if isinstance(node, ast.Import):
        return any(
            alias.name.lower() == normalized or alias.name.lower().startswith(f"{normalized}.")
            or alias.name.split(".", 1)[0].lower() == normalized
            for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        if not node.module:
            return False
        candidate = node.module.lower()
        return candidate == normalized or candidate.startswith(f"{normalized}.") or candidate.split(".", 1)[0] == normalized
    return False


def _has_top_level_import_for_module(tree: ast.AST, module: str) -> bool:
    """Detect module-level import statements for a given module."""

    normalized = module.lower()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if _import_targets_module(node, normalized):
                return True
    return False


def _is_importerror_handler(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id == "ImportError"
    if isinstance(handler.type, ast.Tuple):
        return any(
            isinstance(item, ast.Name) and item.id == "ImportError"
            for item in handler.type.elts
        )
    return False


def _is_sys_modules(expr: ast.AST) -> bool:
    return (
        isinstance(expr, ast.Attribute)
        and isinstance(expr.value, ast.Name)
        and expr.value.id == "sys"
        and expr.attr == "modules"
    )


def _is_module_module_guard(test: ast.AST, module: str) -> bool:
    for node in ast.walk(test):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            continue
        left = node.left
        comparators = node.comparators or ()
        for comparator in comparators:
            if isinstance(left, ast.Constant) and isinstance(left.value, str) and left.value == module and _is_sys_modules(comparator):
                return True
            if _is_sys_modules(left) and isinstance(comparator, ast.Constant) and isinstance(comparator.value, str) and comparator.value == module:
                return True
    return False


def _has_optional_import_guard(tree: ast.AST, module: str) -> bool:
    """Accept try/except ImportError imports and sys.modules gating patterns."""

    parent = _node_parent_map(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not _import_targets_module(node, module):
            continue
        parent_node = parent.get(node)
        if isinstance(parent_node, ast.Try):
            if any(_is_importerror_handler(handler) for handler in parent_node.handlers):
                return True
        if isinstance(parent_node, ast.If):
            if _is_module_module_guard(parent_node.test, module):
                return True
    return False


def _has_launch_show_call(node: ast.stmt) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "show"
            and isinstance(func.value, (ast.Name, ast.Attribute))
        ):
            return True
    return False


def _is_dunder_main_guard(test: ast.AST) -> bool:
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    left = test.left
    right = test.comparators[0]
    return (
        (
            isinstance(left, ast.Name)
            and left.id == "__name__"
            and isinstance(right, ast.Constant)
            and right.value == "__main__"
        )
        or (
            isinstance(right, ast.Name)
            and right.id == "__name__"
            and isinstance(left, ast.Constant)
            and left.value == "__main__"
        )
    )


def _has_main_window_entrypoint(tree: ast.AST) -> bool:
    local_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        if not _is_dunder_main_guard(node.test):
            continue
        for child in node.body:
            if _has_launch_show_call(child):
                return True
            for call in ast.walk(child):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id in local_functions
                    and _has_launch_show_call(local_functions[call.func.id])
                ):
                    return True
    return False


def _has_widget_class_surface(tree: ast.AST, inferred_widget_requirements: list[tuple[str, str]]) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        class_name = node.name.lower()
        if any(token in class_name for token in ("dialog", "widget", "window")):
            return True
        for base in node.bases:
            base_name: str | None = None
            if isinstance(base, ast.Name):
                base_name = base.id.lower()
            elif isinstance(base, ast.Attribute):
                base_name = base.attr.lower()
            if base_name is not None and any(
                token in base_name for token in (
                    "dialog",
                    "widget",
                    "window",
                    "qdialog",
                    "qwidget",
                    "qmainwindow",
                )
            ):
                return True
    return bool(inferred_widget_requirements)


def _iter_signal_connects(tree: ast.AST) -> tuple[
    dict[str, list[str]],
    list[str],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, dict[str, ast.FunctionDef]],
    dict[str, list[tuple[str, str | None]]],
    dict[str, dict[str, str]],
]:
    """Collect signal wiring locations and method/call details per class."""

    parent = _node_parent_map(tree)

    module_level: list[str] = []
    class_connects: dict[str, list[str]] = {}
    class_connected_self_handlers: dict[str, set[str]] = {}
    class_connecting_methods: dict[str, set[str]] = {}
    class_widget_defs: dict[str, set[str]] = {}
    class_method_nodes: dict[str, dict[str, ast.FunctionDef]] = {}
    class_signal_targets: dict[str, list[tuple[str, str | None]]] = {}
    class_widget_ctors: dict[str, dict[str, str]] = {}
    init_calls: dict[str, set[str]] = {}
    class_methods_by_class: dict[str, set[str]] = {}
    class_method_calls: dict[str, dict[str, set[str]]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            class_methods_by_class[class_name] = {
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef)
            }
            class_method_nodes[class_name] = {}
            class_method_calls[class_name] = {}
            class_widget_defs.setdefault(class_name, set())
            class_signal_targets.setdefault(class_name, [])
            class_widget_ctors.setdefault(class_name, {})
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    self_calls = {
                        call.func.attr
                        for call in ast.walk(child)
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id == "self"
                            and isinstance(call.func.attr, str)
                        )
                    }
                    class_method_calls[class_name][child.name] = self_calls
                    class_method_nodes[class_name][child.name] = child
                    if child.name == "__init__":
                        init_calls[class_name] = self_calls
                    for stmt in ast.walk(child):
                        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                            continue
                        if isinstance(stmt, ast.Assign):
                            targets = list(stmt.targets)
                        else:
                            targets = [stmt.target]
                        value = stmt.value
                        for target in targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and isinstance(target.attr, str)
                            ):
                                class_widget_defs[class_name].add(target.attr)
                                if isinstance(value, ast.Call):
                                    call_func = _callable_signature_name(value)
                                    if call_func is not None:
                                        class_widget_ctors[class_name][target.attr] = call_func

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
        ):
            continue

        containing_function: ast.AST | None = None
        containing_class: ast.AST | None = None
        cursor = node
        while cursor in parent:
            cursor = parent[cursor]
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)) and containing_function is None:
                containing_function = cursor
            if isinstance(cursor, ast.ClassDef):
                containing_class = cursor
                break

        if containing_class is None:
            module_level.append(ast.unparse(node).strip())
            continue
        if not isinstance(containing_function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        class_name = getattr(containing_class, "name", "")
        function_name = getattr(containing_function, "name", "")
        class_connects.setdefault(class_name, [])
        class_connected_self_handlers.setdefault(class_name, set())
        class_connecting_methods.setdefault(class_name, set())
        class_signal_targets.setdefault(class_name, [])
        class_connects[class_name].append(function_name or "<unknown>")

        if node.args:
            arg0 = node.args[0]
            if (
                isinstance(arg0, ast.Attribute)
                and isinstance(arg0.value, ast.Name)
                and arg0.value.id == "self"
            ):
                class_connected_self_handlers[class_name].add(arg0.attr)
                handler_name = arg0.attr
                if function_name and node.func:
                    target_widget = _extract_self_chain_attr(node.func.value)
                    class_signal_targets[class_name].append((target_widget or "", handler_name))
            elif function_name and node.func:
                target_widget = _extract_self_chain_attr(node.func.value)
                if target_widget:
                    class_signal_targets[class_name].append((target_widget, None))
        if function_name and function_name != "__init__":
            class_connecting_methods[class_name].add(function_name)

    return (
        class_connects,
        module_level,
        class_connected_self_handlers,
        class_connecting_methods,
        init_calls,
        class_methods_by_class,
        class_method_calls,
        class_widget_defs,
        class_method_nodes,
        class_signal_targets,
        class_widget_ctors,
    )


def _has_factory_argument_call(tree: ast.AST) -> bool:
    verified_factory_names = {
        target.id
        for assignment in ast.walk(tree)
        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
        for target in (
            assignment.targets
            if isinstance(assignment, ast.Assign)
            else [assignment.target]
        )
        if isinstance(target, ast.Name)
        and isinstance(assignment.value, ast.Call)
        and "factory" in ast.unparse(assignment.value.func).lower()
    }

    def is_factory_expression(expression: ast.AST) -> bool:
        if isinstance(expression, ast.Constant) and expression.value is None:
            return False
        if isinstance(expression, ast.Call):
            return "factory" in ast.unparse(expression.func).lower()
        if isinstance(expression, ast.Name):
            return expression.id in verified_factory_names
        return False

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_asset"
        ):
            if any(
                isinstance(keyword, ast.keyword)
                and keyword.arg == "factory"
                and is_factory_expression(keyword.value)
                for keyword in node.keywords
            ):
                return True
            if len(node.args) < 4:
                continue
            factory_arg = node.args[3]
            if is_factory_expression(factory_arg):
                return True
    return False


def _real_unreal_get_asset_tools_targets(tree: ast.AST) -> set[str]:
    """Collect `get_asset_tools` call sites that need API-ownership validation."""

    candidates: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "get_asset_tools":
            candidates.add("get_asset_tools")
            continue
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_asset_tools"
        ):
            candidates.add(ast.unparse(node.func.value))
    return candidates


def _validated_api_membership_call_chain(call_base: str, module_name: str = "unreal") -> bool:
    """Resolve `unreal.<owner>.get_asset_tools` against a real Unreal module, if available."""

    try:
        unreal_module = __import__(module_name)
    except Exception:
        return False

    segments = [segment.strip() for segment in call_base.split(".") if segment.strip()]
    if len(segments) < 2 or segments[0] != module_name:
        return False

    owner = unreal_module
    for segment in segments[1:]:
        if not hasattr(owner, segment):
            return False
        try:
            owner = getattr(owner, segment)
        except Exception:
            return False
    return hasattr(owner, "get_asset_tools")


def _invalid_unreal_get_asset_tools_calls(tree: ast.AST) -> tuple[list[str], list[str]]:
    """Find Unreal `get_asset_tools` calls that appear invalid or unverified."""

    candidates = _real_unreal_get_asset_tools_targets(tree)
    invalid: list[str] = []
    unverifiable: list[str] = []
    for call_expr in sorted(candidates):
        if call_expr == "get_asset_tools":
            invalid.append(call_expr)
            continue
        if not call_expr.startswith("unreal."):
            invalid.append(call_expr + ".get_asset_tools")
            continue
        if not _validated_api_membership_call_chain(call_expr):
            try:
                __import__("unreal")
            except Exception:
                unverifiable.append(f"{call_expr}.get_asset_tools")
            else:
                invalid.append(f"{call_expr}.get_asset_tools")
    return sorted(invalid), sorted(unverifiable)


def _infer_explicit_runtime_api_requests(request_prompt: str) -> set[str]:
    """Infer exact runtime API names requested in prompt text."""

    text = str(request_prompt or "")
    if not text:
        return set()

    request_paths: set[str] = set()
    for module in sorted(_HOST_RUNTIME_MODULES):
        pattern = rf"\b{re.escape(module)}\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){{1,4}}\b"
        request_paths.update(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return request_paths


def _runtime_api_calls_in_tree(tree: ast.AST) -> set[str]:
    """Collect explicitly written runtime dot-chains from call expressions."""

    call_paths: set[str] = set()
    imported_runtime_bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        runtime_root = node.module.split(".", 1)[0]
        if runtime_root not in _HOST_RUNTIME_MODULES:
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            imported_runtime_bindings[alias.asname or alias.name] = (
                f"{node.module}.{alias.name}"
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        parts: list[str] = []
        cursor = func
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if not isinstance(cursor, ast.Name):
            continue
        if cursor.id in _HOST_RUNTIME_MODULES:
            root = cursor.id
        elif cursor.id in imported_runtime_bindings:
            root = imported_runtime_bindings[cursor.id]
        else:
            continue
        if not parts:
            continue
        call_paths.add(".".join([root] + list(reversed(parts))))
    return call_paths


def _runtime_api_paths_in_tree(tree: ast.AST) -> set[str]:
    """Collect every qualified host attribute chain used by generated code."""

    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        parts: list[str] = []
        cursor: ast.AST = node
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if (
            isinstance(cursor, ast.Name)
            and cursor.id in _HOST_RUNTIME_MODULES
            and parts
        ):
            paths.add(".".join([cursor.id, *reversed(parts)]))
    return paths


def _progress_callback_contract_issues(
    tree: ast.AST,
    request_prompt: str,
) -> list[str]:
    """Validate the shared integer-step progress callback contract."""

    prompt_lower = str(request_prompt or "").lower()
    callback_requested = (
        "progress_callback" in prompt_lower
        or "progress callback" in prompt_lower
        or (
            "callback arguments" in prompt_lower
            and "integer" in prompt_lower
        )
    )
    issues: list[str] = []
    owned_functions: list[
        tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]
    ] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owned_functions.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            owned_functions.extend(
                (f"{node.name}.{method.name}", method)
                for method in node.body
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
    for owner, function in owned_functions:
        owner_prefix = f"[scope:callable][owner:{owner}] "
        parameter_names = {
            argument.arg
            for argument in (
                list(function.args.posonlyargs)
                + list(function.args.args)
                + list(function.args.kwonlyargs)
            )
        }
        callback_names = {
            name for name in parameter_names
            if name == "progress_callback" or name.endswith("_progress_callback")
        }
        progress_bar_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in {"setValue", "set_value"}
            and len(call.args) == 1
            and "progress" in ast.unparse(call.func.value).casefold()
        ]
        for call in progress_bar_calls:
            argument = call.args[0]
            safely_coerced = (
                isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Name)
                and argument.func.id in {"int", "round"}
            )
            contains_true_division = any(
                isinstance(node, ast.BinOp)
                and isinstance(node.op, ast.Div)
                for node in ast.walk(argument)
            )
            if contains_true_division and not safely_coerced:
                issues.append(
                    f"{owner_prefix}progress widgets must receive an integer "
                    "value; wrap division-based progress math in int() or round()"
                )
        if not callback_names:
            continue
        direct_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in callback_names
        ]
        assertion_calls = [
            call
            for call in ast.walk(function)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in callback_names
            and call.func.attr.startswith("assert")
        ]
        for call in direct_calls:
            first_two_are_not_float_math = all(
                not any(
                    (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, float)
                    )
                    or (
                        isinstance(node, ast.BinOp)
                        and isinstance(node.op, ast.Div)
                    )
                    for node in ast.walk(argument)
                )
                for argument in call.args[:2]
            )
            status_is_text = (
                len(call.args) >= 3
                and isinstance(call.args[2], (ast.Constant, ast.JoinedStr, ast.Name))
                and not (
                    isinstance(call.args[2], ast.Constant)
                    and not isinstance(call.args[2].value, str)
                )
            )
            if (
                len(call.args) != 3
                or call.keywords
                or not first_two_are_not_float_math
                or not status_is_text
            ):
                issues.append(
                    f"{owner_prefix}progress callbacks must use exactly "
                    "(current_int, total_int, status_str) without float math"
                )
        explicit_terminal_step_requested = bool(
            re.search(
                r"\b(?:explicit\s+)?(?:terminal|final)\s+"
                r"(?:progress\s+)?(?:callback|step|update)\b"
                r"|\bcurrent\s*==\s*total\b",
                request_prompt,
                flags=re.IGNORECASE,
            )
        )
        if explicit_terminal_step_requested and direct_calls and not any(
            len(call.args) == 3
            and ast.dump(call.args[0], include_attributes=False)
            == ast.dump(call.args[1], include_attributes=False)
            for call in direct_calls
        ):
            issues.append(
                f"{owner_prefix}progress callback sequence must emit an "
                "explicit terminal current == total step"
            )
        if callback_requested and function.name.startswith("test_"):
            if not assertion_calls or any(
                len(call.args) != 3 for call in assertion_calls
            ):
                issues.append(
                    f"{owner_prefix}requested callback proof must assert all "
                    "three callback arguments"
                )
    return sorted(set(issues))
