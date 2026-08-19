"""Dependency-ordered project edit workflow helpers."""
from __future__ import annotations

import ast
import copy
import importlib
import importlib.util
import itertools
import json
import re
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from tech_connector.models.constants import TOOLS_ROOT
from tech_connector.services.llm_router_service import (
    LLMProviderRoute,
    generate_llm_response,
    resolve_llm_provider_route,
)
from tech_connector.services.project_edit_agent_service import (
    ProjectEditApplyResult,
    ProjectEditPlan,
    ProjectEditPromptStage,
    apply_project_edit_agent_response,
    apply_project_edit_generated_symbol_repair,
    build_project_edit_agent_request,
    assemble_project_edit_generated_chunks,
    build_project_edit_artifact_chunk_stages,
    build_project_edit_artifact_file_stages,
    build_project_edit_artifact_manifest_stage,
    build_project_edit_chunk_plan_stage,
    build_deterministic_project_edit_chunk_plan,
    build_user_visible_implementation_plan,
    build_project_edit_function_repair_contract,
    build_project_edit_function_repair_plan_stage,
    build_project_edit_function_repair_stage,
    build_project_edit_class_repair_stage,
    build_project_edit_class_set_repair_stage,
    build_project_edit_integration_contract_stage,
    build_project_edit_missing_symbol_stage,
    build_project_edit_multi_file_candidate,
    parse_project_edit_chunk_plan,
    parse_project_edit_generated_chunk,
    extract_project_edit_artifact_requirements,
    complete_project_edit_integration_contract_response,
    ensure_project_edit_requested_docstrings,
    enforce_project_edit_requested_test_contracts,
    format_project_edit_generated_python,
    model_for_project_edit_stage,
    apply_project_edit_missing_symbol,
    apply_project_edit_generated_class_repair,
    apply_project_edit_generated_class_set_repair,
    parse_project_edit_artifact_manifest,
    parse_project_edit_function_repair_plan,
    parse_project_edit_generated_file,
    preview_project_edit_agent_response,
    project_edit_validation_failure_signature,
    remove_project_edit_unused_imports,
    repair_project_edit_duplicate_dependency_symbols,
    resolve_project_edit_cross_file_symbols,
    resolve_project_edit_standard_library_symbols,
)


StatusCallback = Callable[[str], None]

from tech_connector.services.project_edit_workflow_part_01 import (
    WORKFLOW_CHECKPOINT_VALIDATOR_VERSION,
    _checkpoint_hash,
    _workflow_checkpoint_path,
)

from tech_connector.services.project_edit_workflow_part_08 import (
    _compact_callable_repair_model,
    _runtime_assertion_causal_owner_targets,
    _strong_task_model,
)


def _repair_cross_collection_removal_polarity(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    verification_targets: list[dict[str, str]],
) -> tuple[list[tuple[str, str, str]], str]:
    """Repair a proven remove-then-preserve cross-collection contradiction."""

    causal_targets = _runtime_assertion_causal_owner_targets(
        generated_files,
        errors,
        verification_targets,
    )
    for target in causal_targets:
        observed_attributes = {
            value
            for value in str(
                target.get("observed_attributes") or ""
            ).split(",")
            if value
        }
        if not observed_attributes:
            continue
        path = str(target.get("path") or "")
        symbol = str(target.get("symbol") or "")
        source = next(
            (
                candidate_source
                for candidate_path, _original, candidate_source
                in generated_files
                if Path(candidate_path).resolve() == Path(path).resolve()
            ),
            "",
        )
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        owner_name, separator, method_name = symbol.partition(".")
        if not separator:
            continue
        owner = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == owner_name
            ),
            None,
        )
        method = next(
            (
                node
                for node in (owner.body if owner is not None else [])
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == method_name
            ),
            None,
        )
        if method is None:
            continue
        for observed_attribute in sorted(observed_attributes):
            already_mutates_observed = any(
                (
                    isinstance(node, (ast.Assign, ast.AnnAssign))
                    and any(
                        isinstance(assignment_target, ast.Attribute)
                        and isinstance(assignment_target.value, ast.Name)
                        and assignment_target.value.id == "self"
                        and assignment_target.attr == observed_attribute
                        for assignment_target in (
                            node.targets
                            if isinstance(node, ast.Assign)
                            else [node.target]
                        )
                    )
                )
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr
                    in {
                        "add",
                        "append",
                        "clear",
                        "discard",
                        "extend",
                        "insert",
                        "pop",
                        "remove",
                        "update",
                    }
                    and isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "self"
                    and node.func.value.attr == observed_attribute
                )
                for node in ast.walk(method)
            )
            if already_mutates_observed:
                continue
            for statement in method.body:
                if not isinstance(statement, ast.For) or not isinstance(
                    statement.target,
                    ast.Name,
                ):
                    continue
                loop_name = statement.target.id
                mutation_branch: list[ast.stmt] | None = None
                if any(
                    isinstance(node, ast.Delete)
                    or (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Attribute)
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "self"
                    )
                    for node in statement.body
                ):
                    mutation_branch = statement.body
                else:
                    successful_if = next(
                        (
                            child
                            for child in statement.body
                            if isinstance(child, ast.If)
                            and any(
                                isinstance(node, ast.Delete)
                                or (
                                    isinstance(node, ast.Call)
                                    and isinstance(node.func, ast.Attribute)
                                    and isinstance(
                                        node.func.value,
                                        ast.Attribute,
                                    )
                                    and isinstance(
                                        node.func.value.value,
                                        ast.Name,
                                    )
                                    and node.func.value.value.id == "self"
                                )
                                for node in ast.walk(child)
                            )
                        ),
                        None,
                    )
                    if successful_if is not None:
                        mutation_branch = successful_if.body
                if mutation_branch is None:
                    continue
                mutation_branch.append(
                    ast.If(
                        test=ast.Compare(
                            left=ast.Name(id=loop_name, ctx=ast.Load()),
                            ops=[ast.In()],
                            comparators=[
                                ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=observed_attribute,
                                    ctx=ast.Load(),
                                )
                            ],
                        ),
                        body=[
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Attribute(
                                            value=ast.Name(
                                                id="self",
                                                ctx=ast.Load(),
                                            ),
                                            attr=observed_attribute,
                                            ctx=ast.Load(),
                                        ),
                                        attr="remove",
                                        ctx=ast.Load(),
                                    ),
                                    args=[
                                        ast.Name(id=loop_name, ctx=ast.Load())
                                    ],
                                    keywords=[],
                                )
                            )
                        ],
                        orelse=[],
                    )
                )
                ast.fix_missing_locations(method)
                updated, splice_errors = (
                    apply_project_edit_generated_symbol_repair(
                        generated_files,
                        path=path,
                        symbol=symbol,
                        replacement_response=ast.unparse(method),
                        forbidden_names=[],
                    )
                )
                if not splice_errors and updated != generated_files:
                    return (
                        updated,
                        f"{Path(path).name}:{symbol} synchronized "
                        f"assertion-observed self.{observed_attribute} in the "
                        "proven successful mutation loop",
                    )
        for statement_index, statement in enumerate(method.body):
            if not isinstance(statement, ast.For) or not isinstance(
                statement.target,
                ast.Name,
            ):
                continue
            loop_name = statement.target.id
            source_attribute = ""
            iterator = statement.iter
            if (
                isinstance(iterator, ast.Call)
                and isinstance(iterator.func, ast.Name)
                and iterator.func.id in {"list", "tuple"}
                and iterator.args
            ):
                iterator = iterator.args[0]
            if (
                isinstance(iterator, ast.Call)
                and isinstance(iterator.func, ast.Attribute)
                and iterator.func.attr in {"keys", "items", "values"}
                and isinstance(iterator.func.value, ast.Attribute)
                and isinstance(iterator.func.value.value, ast.Name)
                and iterator.func.value.value.id == "self"
            ):
                source_attribute = iterator.func.value.attr
            if not source_attribute:
                continue
            successful_branch = next(
                (
                    node
                    for node in statement.body
                    if isinstance(node, ast.If)
                    and any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and any(
                            isinstance(argument, ast.Name)
                            and argument.id == loop_name
                            for argument in call.args
                        )
                        for call in ast.walk(node.test)
                    )
                ),
                None,
            )
            if successful_branch is None:
                continue
            deletes_source_item = any(
                isinstance(node, ast.Delete)
                and any(
                    isinstance(delete_target, ast.Subscript)
                    and isinstance(delete_target.value, ast.Attribute)
                    and isinstance(delete_target.value.value, ast.Name)
                    and delete_target.value.value.id == "self"
                    and delete_target.value.attr == source_attribute
                    for delete_target in node.targets
                )
                for node in ast.walk(successful_branch)
            )
            if not deletes_source_item:
                continue
            contradictory_index: int | None = None
            observed_attribute = ""
            for later_index in range(statement_index + 1, len(method.body)):
                later = method.body[later_index]
                if (
                    not isinstance(later, ast.Assign)
                    or len(later.targets) != 1
                    or not isinstance(later.targets[0], ast.Attribute)
                    or not isinstance(later.targets[0].value, ast.Name)
                    or later.targets[0].value.id != "self"
                    or later.targets[0].attr not in observed_attributes
                    or not isinstance(later.value, ast.ListComp)
                ):
                    continue
                has_remove_then_preserve_condition = any(
                    isinstance(condition, ast.Compare)
                    and len(condition.ops) == 1
                    and isinstance(condition.ops[0], ast.NotIn)
                    and len(condition.comparators) == 1
                    and isinstance(condition.comparators[0], ast.Attribute)
                    and isinstance(condition.comparators[0].value, ast.Name)
                    and condition.comparators[0].value.id == "self"
                    and condition.comparators[0].attr == source_attribute
                    for generator in later.value.generators
                    for condition in generator.ifs
                )
                if has_remove_then_preserve_condition:
                    contradictory_index = later_index
                    observed_attribute = later.targets[0].attr
                    break
            if contradictory_index is None:
                continue
            already_removes = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"discard", "pop", "remove"}
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"
                and node.func.value.attr == observed_attribute
                for node in ast.walk(successful_branch)
            )
            if not already_removes:
                successful_branch.body.append(
                    ast.If(
                        test=ast.Compare(
                            left=ast.Name(id=loop_name, ctx=ast.Load()),
                            ops=[ast.In()],
                            comparators=[
                                ast.Attribute(
                                    value=ast.Name(id="self", ctx=ast.Load()),
                                    attr=observed_attribute,
                                    ctx=ast.Load(),
                                )
                            ],
                        ),
                        body=[
                            ast.Expr(
                                value=ast.Call(
                                    func=ast.Attribute(
                                        value=ast.Attribute(
                                            value=ast.Name(
                                                id="self",
                                                ctx=ast.Load(),
                                            ),
                                            attr=observed_attribute,
                                            ctx=ast.Load(),
                                        ),
                                        attr="remove",
                                        ctx=ast.Load(),
                                    ),
                                    args=[
                                        ast.Name(id=loop_name, ctx=ast.Load())
                                    ],
                                    keywords=[],
                                )
                            )
                        ],
                        orelse=[],
                    )
                )
            del method.body[contradictory_index]
            ast.fix_missing_locations(method)
            replacement = ast.unparse(method)
            updated, splice_errors = apply_project_edit_generated_symbol_repair(
                generated_files,
                path=path,
                symbol=symbol,
                replacement_response=replacement,
                forbidden_names=[],
            )
            if not splice_errors and updated != generated_files:
                return (
                    updated,
                    f"{Path(path).name}:{symbol} moved removal from "
                    f"self.{observed_attribute} into the proven successful "
                    "predicate branch",
                )
    return generated_files, ""


def _callable_behavior_fingerprint(source: str, symbol: str) -> str:
    """Hash executable callable behavior while ignoring its docstring."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    owner_name, separator, callable_name = symbol.partition(".")
    callable_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if (
            not separator
            and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == owner_name
        ):
            callable_node = node
            break
        if separator and isinstance(node, ast.ClassDef) and node.name == owner_name:
            callable_node = next(
                (
                    child
                    for child in node.body
                    if isinstance(
                        child,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and child.name == callable_name
                ),
                None,
            )
            break
    if callable_node is None:
        return ""
    executable_body = list(callable_node.body)
    if (
        executable_body
        and isinstance(executable_body[0], ast.Expr)
        and isinstance(executable_body[0].value, ast.Constant)
        and isinstance(executable_body[0].value.value, str)
    ):
        executable_body = executable_body[1:]
    return _checkpoint_hash(
        ast.dump(
            ast.Module(body=executable_body, type_ignores=[]),
            include_attributes=False,
        )
    )


def _preserve_callable_docstring(
    current_source: str,
    symbol: str,
    replacement: str,
) -> str:
    """Keep validated documentation unchanged during a behavior-only repair."""

    try:
        current_tree = ast.parse(current_source)
        replacement_tree = ast.parse(replacement)
    except SyntaxError:
        return replacement
    owner_name, separator, callable_name = symbol.partition(".")

    def find_callable(
        tree: ast.Module,
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in tree.body:
            if (
                not separator
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == owner_name
            ):
                return node
            if (
                separator
                and isinstance(node, ast.ClassDef)
                and node.name == owner_name
            ):
                return next(
                    (
                        child
                        for child in node.body
                        if isinstance(
                            child,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and child.name == callable_name
                    ),
                    None,
                )
        return None

    current_callable = find_callable(current_tree)
    replacement_callable = find_callable(replacement_tree)
    if replacement_callable is None and len(replacement_tree.body) == 1:
        only_node = replacement_tree.body[0]
        if isinstance(only_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            replacement_callable = only_node
    if current_callable is None or replacement_callable is None:
        return replacement
    current_doc = (
        current_callable.body[0]
        if current_callable.body and ast.get_docstring(current_callable, clean=False)
        else None
    )
    if current_doc is None:
        return replacement
    if replacement_callable.body and ast.get_docstring(
        replacement_callable,
        clean=False,
    ):
        replacement_callable.body[0] = current_doc
    else:
        replacement_callable.body.insert(0, current_doc)
    ast.fix_missing_locations(replacement_callable)
    return ast.unparse(replacement_callable)


def _repair_contract_proven_order_operations(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Remove exact order-destroying operations rejected by plan validation."""

    issues: list[tuple[str, str, str]] = []
    for error in errors:
        if (
            ": approved replacement-position contract deletes or pops mapping "
            "entries." in error
        ):
            location = error.split(
                ": approved replacement-position contract deletes or pops "
                "mapping entries.",
                1,
            )[0]
            path, owner = location.rsplit(":", 1)
            issues.append((path, owner, "deletion"))
        elif ": approved insertion-order property sorts its result " in error:
            location = error.split(
                ": approved insertion-order property sorts its result ",
                1,
            )[0]
            path, owner = location.rsplit(":", 1)
            issues.append((path, owner, "sorting"))

    updated = list(generated_files)
    notes: list[str] = []
    for issue_path, owner, issue_kind in issues:
        source = next(
            (
                candidate_source
                for path, _original, candidate_source in updated
                if Path(path).resolve() == Path(issue_path).resolve()
            ),
            "",
        )
        if not source:
            continue
        try:
            tree = ast.parse(source, filename=issue_path)
        except SyntaxError:
            continue
        owner_parts = owner.split(".")
        owner_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != owner_parts[-1]:
                continue
            if len(owner_parts) > 1 and not any(
                isinstance(class_node, ast.ClassDef)
                and class_node.name == owner_parts[-2]
                and node in class_node.body
                for class_node in tree.body
            ):
                continue
            owner_node = node
            break
        if owner_node is None:
            continue

        changed = False
        if issue_kind == "deletion":
            class RemoveRejectedDeletion(ast.NodeTransformer):
                def visit_Delete(self, node: ast.Delete) -> ast.AST | None:
                    nonlocal changed
                    changed = True
                    return None

                def visit_Expr(self, node: ast.Expr) -> ast.AST | None:
                    nonlocal changed
                    if (
                        isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Attribute)
                        and node.value.func.attr == "pop"
                    ):
                        changed = True
                        return None
                    return self.generic_visit(node)

            RemoveRejectedDeletion().visit(owner_node)
        else:
            for return_node in ast.walk(owner_node):
                if not isinstance(return_node, ast.Return):
                    continue
                tuple_call = return_node.value
                if (
                    not isinstance(tuple_call, ast.Call)
                    or not isinstance(tuple_call.func, ast.Name)
                    or tuple_call.func.id != "tuple"
                    or len(tuple_call.args) != 1
                ):
                    continue
                sorted_call = tuple_call.args[0]
                if (
                    isinstance(sorted_call, ast.Call)
                    and isinstance(sorted_call.func, ast.Name)
                    and sorted_call.func.id == "sorted"
                    and len(sorted_call.args) == 1
                ):
                    tuple_call.args[0] = sorted_call.args[0]
                    changed = True
                    break
        if not changed:
            continue
        ast.fix_missing_locations(owner_node)
        replacement = _preserve_callable_docstring(
            source,
            owner,
            ast.unparse(owner_node),
        )
        repaired, splice_errors = apply_project_edit_generated_symbol_repair(
            updated,
            path=issue_path,
            symbol=owner,
            replacement_response=replacement,
            forbidden_names=[],
        )
        if splice_errors or repaired == updated:
            continue
        updated = repaired
        action = (
            "removed validator-proven replacement deletion"
            if issue_kind == "deletion"
            else "removed validator-proven insertion-order sort"
        )
        notes.append(f"{Path(issue_path).name}:{owner}: {action}.")
    return updated, notes


def _repair_verification_defensive_copy_proof(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Insert one exact source-mapping mutation required by a copy proof."""

    marker = (
        ": requested verification callable does not independently prove "
        "clause(s): defensive copying."
    )
    issue_locations = [
        error.split(marker, 1)[0]
        for error in errors
        if marker in error
    ]
    updated = list(generated_files)
    notes: list[str] = []
    for location in issue_locations:
        path, owner = location.rsplit(":", 1)
        source = next(
            (
                candidate_source
                for candidate_path, _original, candidate_source in updated
                if Path(candidate_path).resolve() == Path(path).resolve()
            ),
            "",
        )
        if not source:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        verification = next(
            (
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == owner
            ),
            None,
        )
        if verification is None:
            continue
        mapping_assignments = {
            target.id: statement
            for statement in verification.body
            if isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Dict)
            for target in statement.targets
            if isinstance(target, ast.Name)
        }
        inserted = False
        for statement_index, statement in enumerate(verification.body):
            if not isinstance(statement, ast.Assign):
                continue
            constructor = statement.value
            if (
                not isinstance(constructor, ast.Call)
                or not constructor.args
                or not isinstance(constructor.args[0], ast.Name)
            ):
                continue
            mapping_name = constructor.args[0].id
            mapping_statement = mapping_assignments.get(mapping_name)
            if mapping_statement is None:
                continue
            mapping_value = mapping_statement.value
            first_key = next(
                (
                    key
                    for key in mapping_value.keys
                    if isinstance(key, ast.Constant)
                ),
                None,
            )
            if first_key is None:
                continue
            already_mutated = any(
                getattr(child, "lineno", 0) > statement.lineno
                and (
                    (
                        isinstance(child, ast.Subscript)
                        and isinstance(child.ctx, (ast.Store, ast.Del))
                        and isinstance(child.value, ast.Name)
                        and child.value.id == mapping_name
                    )
                    or (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == mapping_name
                        and child.func.attr
                        in {"clear", "pop", "remove", "update"}
                    )
                )
                for child in ast.walk(verification)
            )
            if already_mutated:
                continue
            mutation = ast.Delete(
                targets=[
                    ast.Subscript(
                        value=ast.Name(id=mapping_name, ctx=ast.Load()),
                        slice=ast.Constant(value=first_key.value),
                        ctx=ast.Del(),
                    )
                ]
            )
            ast.copy_location(mutation, statement)
            verification.body.insert(statement_index + 1, mutation)
            inserted = True
            break
        if not inserted:
            continue
        ast.fix_missing_locations(verification)
        replacement = _preserve_callable_docstring(
            source,
            owner,
            ast.unparse(verification),
        )
        repaired, splice_errors = apply_project_edit_generated_symbol_repair(
            updated,
            path=path,
            symbol=owner,
            replacement_response=replacement,
            forbidden_names=[],
        )
        if splice_errors or repaired == updated:
            continue
        updated = repaired
        notes.append(
            f"{Path(path).name}:{owner}: mutated the exact named constructor "
            "mapping for the approved defensive-copy proof."
        )
    return updated, notes


def _small_owner_reasoning_model(
    settings: dict[str, Any],
    selected_model: str,
) -> str:
    configured = str(
        settings.get("owner_resolution_model")
        or settings.get("local_small_code_model")
        or settings.get("fast_code_model")
        or ""
    ).strip()
    if configured:
        if configured.lower().startswith(
            (
                "anthropic:",
                "claude:",
                "openai:",
                "google:",
                "gemini:",
                "x:",
                "grok:",
            )
        ):
            return configured
        return _compact_callable_repair_model(configured)
    return _compact_callable_repair_model(selected_model)


def _causal_repair_reasoning_model(
    settings: dict[str, Any],
    selected_model: str,
) -> str:
    """Use a configurable non-thinking coder for focused causal repair."""

    configured = str(settings.get("causal_repair_model") or "").strip()
    if configured:
        return configured.removeprefix("ollama:")
    return _strong_task_model(selected_model)


def _causal_repair_escalation_model(
    settings: dict[str, Any],
    selected_model: str,
) -> str:
    """Escalate a failed causal analysis to the configured coding model."""

    configured = str(
        settings.get("router_local_code")
        or settings.get("fast_code_model")
        or settings.get("fallback_code_model")
        or "qwen2.5-coder:7b"
    ).strip()
    return configured.removeprefix("ollama:") or _strong_task_model(
        selected_model
    )


def _explicit_dotted_module_requests(prompt: str) -> list[str]:
    """Return dotted Python modules explicitly presented as artifact owners."""

    modules: list[str] = []
    for declaration in re.findall(
        r"\bmodules?\s*(?::|named)?\s*"
        r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+"
        r"(?:\s*(?:,|and)\s*"
        r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)*)",
        prompt,
        flags=re.IGNORECASE,
    ):
        modules.extend(re.findall(
            r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+",
            declaration,
        ))
    modules.extend(re.findall(
        r"(?im)^\s*(?:\d+[.)]|[-*])\s+"
        r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s*$",
        prompt,
    ))
    return list(dict.fromkeys(modules))


def _explicit_path_requested_file_manifest(
    prompt: str,
    *,
    project_root: str,
    requirement_ledger: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Build a path-preserving manifest for explicitly named Python files."""

    root = Path(project_root).resolve()
    raw_paths = list(dict.fromkeys(
        match.replace("\\", "/")
        for match in [
            *re.findall(
                r"""["']([^"']+\.py)["']""",
                prompt,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"(?<![A-Za-z0-9_])"
                r"((?:[A-Za-z]:[\\/])?[A-Za-z0-9_.-]+"
                r"(?:[\\/][A-Za-z0-9_.-]+)*\.py)\b",
                prompt,
                flags=re.IGNORECASE,
            ),
        ]
        if not match.lower().startswith(("http:", "https:"))
    ))
    dotted_modules = _explicit_dotted_module_requests(prompt)
    raw_paths.extend(
        module_name.replace(".", "/") + ".py"
        for module_name in dotted_modules
    )
    explicit_parent_candidates = list(dict.fromkeys(
        str(Path(raw_path).parent).replace("\\", "/")
        for raw_path in raw_paths
        if str(Path(raw_path).parent) not in {"", "."}
    ))
    if len(explicit_parent_candidates) == 1:
        sibling_parent = explicit_parent_candidates[0]
        raw_paths = [
            (
                str(Path(sibling_parent) / raw_path).replace("\\", "/")
                if str(Path(raw_path).parent) in {"", "."}
                else raw_path
            )
            for raw_path in raw_paths
        ]
    package_prefix_match = re.search(
        r"\b(?:(?:package|directory|folder)\s+)?"
        r"(?:under|inside|within)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*(?:[\\/][A-Za-z_][A-Za-z0-9_]*)*)"
        r"(?=\s*(?::|,|;|\.\s+)[^?\n]{0,240}"
        r"[A-Za-z_][A-Za-z0-9_.-]*\.py\b)",
        prompt,
        flags=re.IGNORECASE,
    )
    if package_prefix_match:
        package_prefix = package_prefix_match.group(1).replace("\\", "/")
        raw_paths = [
            (
                f"{package_prefix}/{raw_path}"
                if not Path(raw_path).is_absolute()
                and "/" not in raw_path.replace("\\", "/")
                else raw_path
            )
            for raw_path in raw_paths
        ]
    raw_paths = list(dict.fromkeys(raw_paths))
    raw_paths = [
        path
        for path in raw_paths
        if not any(
            other != path and other.lower().endswith("/" + path.lower())
            for other in raw_paths
        )
    ]
    if not raw_paths:
        return []

    requested_paths: list[Path] = []
    for raw_path in raw_paths:
        candidate = Path(raw_path)
        candidate = candidate if candidate.is_absolute() else root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved not in requested_paths:
            requested_paths.append(resolved)
    if not requested_paths:
        return []

    source_declarations_by_path: dict[Path, tuple[str, ...]] = {}
    for path in requested_paths:
        declarations: list[str] = []
        try:
            source_tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
        except (OSError, SyntaxError, UnicodeDecodeError):
            source_tree = ast.Module(body=[], type_ignores=[])
        for node in source_tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    declarations.append(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                declarations.extend(
                    target.id
                    for target in targets
                    if isinstance(target, ast.Name) and not target.id.startswith("_")
                )
        source_declarations_by_path[path] = tuple(dict.fromkeys(declarations))

    requirement_rows_by_path: dict[Path, list[dict[str, str]]] = {
        path: [] for path in requested_paths
    }
    path_aliases: dict[Path, tuple[str, ...]] = {}
    for path in requested_paths:
        relative = str(path.relative_to(root)).replace("\\", "/")
        without_suffix = relative[:-3] if relative.casefold().endswith(".py") else relative
        path_aliases[path] = tuple(dict.fromkeys([
            relative,
            without_suffix,
            without_suffix.replace("/", "."),
            path.name,
            path.stem,
            *source_declarations_by_path[path],
        ]))

    def mentions_path(text: str, path: Path) -> bool:
        return any(
            re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
                text,
                flags=0 if alias == path.stem else re.IGNORECASE,
            )
            for alias in path_aliases[path]
            if alias
            and not (
                len(requested_paths) > 1
                and alias == path.stem
            )
        )

    ui_paths = [
        path
        for path in requested_paths
        if re.search(
            r"(?:^|[_.-])(?:ui|dialog|widget|window|panel|dock)(?:[_.-]|$)",
            path.stem,
            flags=re.IGNORECASE,
        )
    ]
    non_ui_paths = [path for path in requested_paths if path not in ui_paths]
    active_paths: list[Path] = []
    for requirement in requirement_ledger:
        text = str(requirement.get("text") or "")
        explicitly_described = [
            path
            for path in requested_paths
            if re.search(
                rf"(?<![A-Za-z0-9_])"
                rf"(?:{'|'.join(re.escape(alias) for alias in path_aliases[path])})"
                rf"(?![A-Za-z0-9_])\s*(?::\s*)?"
                r"(?:defines?|contains?|containing|with|provides?|implements?)\b",
                text,
                flags=re.IGNORECASE,
            )
        ]
        mentioned = explicitly_described or [
            path
            for path in requested_paths
            if mentions_path(text, path)
        ]
        section_paths: list[Path] = []
        if ui_paths and re.search(
            r"\b(?:qt|ui|dialog|widget|window)\s+"
            r"(?:production\s+)?(?:file|module)\s+must\b",
            text,
            flags=re.IGNORECASE,
        ):
            section_paths = list(ui_paths)
        elif non_ui_paths and re.search(
            r"\b(?:headless\s+)?(?:backend|service|engine)\s+must\b",
            text,
            flags=re.IGNORECASE,
        ):
            section_paths = list(non_ui_paths)
        all_files = bool(
            re.search(
                r"\b(?:both|each|all|every)\s+(?:of\s+the\s+)?files?\b"
                r"|\bexactly\s+\w+\s+(?:new\s+|production\s+)?files?\b"
                r"|\b(?:create|generate)\s+only\s+"
                r"(?:these\s+|the\s+)?\w+\s+(?:production\s+)?files?\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        cross_cutting = bool(
            re.search(
                r"\b(?:use only|standard library|no external|without external"
                r"|all generated files|entire package|package-wide"
                r"|(?:detailed|complete|descriptive)\s+"
                r"(?:public\s+)?docstrings?"
                r"|placeholders?|whole-file repair|disposable validation"
                r"|report completion|production readiness)\b",
                text,
                flags=re.IGNORECASE,
            )
            or (
                not mentioned
                and re.search(
                    r"\b(?:type\s+(?:hints?|annotations?)|docstrings?)\b",
                    text,
                    flags=re.IGNORECASE,
                )
            )
        )
        if section_paths:
            owners = section_paths
            active_paths = section_paths
        elif all_files or cross_cutting:
            owners = list(requested_paths)
        elif mentioned:
            owners = mentioned
            active_paths = mentioned
        elif active_paths:
            owners = list(active_paths)
        elif len(requested_paths) == 1:
            owners = list(requested_paths)
        else:
            owners = []
        for path in owners:
            requirement_rows_by_path[path].append(requirement)

    records: list[dict[str, Any]] = []
    for path in requested_paths:
        import builtins

        owned_rows = requirement_rows_by_path[path]
        owned_text = "\n".join(
            str(item.get("text") or "") for item in owned_rows
        )
        bounded_declaration_symbols: list[str] = []
        if len(requested_paths) > 1:
            next_file_pattern = re.compile(
                r"\b[A-Za-z_][A-Za-z0-9_]*\.py\b",
                flags=re.IGNORECASE,
            )
            for path_match in re.finditer(
                rf"\b{re.escape(path.name)}\b",
                prompt,
                flags=re.IGNORECASE,
            ):
                tail_start = path_match.end()
                next_file = next_file_pattern.search(prompt, tail_start)
                tail_end = next_file.start() if next_file else len(prompt)
                tail = prompt[tail_start:tail_end]
                sentence_end = re.search(r"[.!?;\n]", tail)
                if sentence_end:
                    tail = tail[:sentence_end.start()]
                declaration_match = re.match(
                    r"\s*(?:(?:must|shall|should|will)\s+)?"
                    r"(?:with|containing|define|defines|defining|"
                    r"provides?|implements?|that\s+(?:contains|defines))\s+"
                    r"(?:(?:a|an|the|new)\s+)?([A-Z][A-Za-z0-9_]*)\b",
                    tail,
                    flags=re.IGNORECASE,
                )
                if (
                    declaration_match
                    and declaration_match.group(1)[:1].isupper()
                ):
                    bounded_declaration_symbols.append(
                        declaration_match.group(1)
                    )
            introduction_clauses = []
            path_contract_clauses = []
        else:
            introduction_clauses = re.findall(
                rf"\b(?:add|build|create|define|implement|introduce|write)\s+"
                rf"{re.escape(path.name)}\s+"
                r"(?:with|containing|defining|defines|that\s+(?:contains|defines))\s+"
                r"([^.!?\n]+)",
                owned_text,
                flags=re.IGNORECASE,
            )
            path_contract_clauses = re.findall(
                rf"\b{re.escape(path.name)}\s+"
                r"(?:with|containing|defining|defines|that\s+(?:contains|defines))\s+"
                r"([^.!?\n]+)",
                owned_text,
                flags=re.IGNORECASE,
            )
        introduction_symbols = [
            symbol
            for symbol in [
                *bounded_declaration_symbols,
                *[
                    value
                    for clause in [*introduction_clauses, *path_contract_clauses]
                    for value in re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", clause)
                ],
            ]
            if not symbol.isupper()
            and not hasattr(builtins, symbol)
        ]
        dedicated_error_symbols = [
            *re.findall(
                r"\b(?:dedicated|custom|new)\s+"
                r"([A-Z][A-Za-z0-9_]*(?:Error|Exception))\b",
                owned_text,
            ),
        ]
        type_matches = re.findall(
            r"\b(?i:add|build|create|define|implement|introduce|provide|write)"
            r"\s+(?:(?i:a|an|the|new|public)\s+)*"
            r"([A-Z][A-Za-z0-9_]*)\s+"
            r"(?i:class|dataclass|record|enum|protocol)\b"
            r"|\b([A-Z][A-Za-z0-9_]*)\s+"
            r"(?i:class|dataclass|record|enum|protocol)\b"
            r"(?=\s*(?:$|[.;,\n]|(?i:with|that|which|containing|"
            r"defining|inheriting|extending|having|for|to)\b))"
            r"|\b(?i:class|dataclass|record|enum|protocol)\s+"
            r"([A-Z][A-Za-z0-9_]*)\b",
            owned_text,
        )
        referenced_api_type_symbols = set(re.findall(
            r"\b(?:existing|official|public|valid|verified)\s+"
            r"(?:[A-Z][A-Za-z0-9_.]*\s+){0,3}"
            r"([A-Z][A-Za-z0-9_]*)\s+class\b",
            owned_text,
            flags=re.IGNORECASE,
        ))
        type_matches = [
            pair
            for pair in type_matches
            if not any(
                value and value in referenced_api_type_symbols
                for value in pair
            )
        ]
        contextual_type_symbols = [
            *re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\s*\([^)]*\)\s*"
                r"(?=(?i:must|shall|should|will|provides?|implements?|exposes?)\b)",
                owned_text,
            ),
            *re.findall(
                r"\b([A-Z][A-Za-z0-9_]*(?:Dialog|Widget|Window|Panel|Dock))"
                r"\s+(?:QWidget|QDialog|widget|dialog|window)\b",
                owned_text,
            ),
            *re.findall(
                r"\b(?:generic\s+)?([A-Z][A-Za-z0-9_]*)\s*"
                r"\[[A-Za-z_][A-Za-z0-9_]*"
                r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*\]",
                owned_text,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"\b(?:add|create|define|implement|include|introduce|provide|write)"
                r"\s+(?:(?:an?|the)\s+)?"
                r"(?:(?:modal|modeless|public|top-level)\s+)*"
                r"([A-Z][A-Za-z0-9_]*(?:Dialog|Widget|Window|Panel|Dock))\b",
                owned_text,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"\b(?i:with|add|create|implement|define|write|build|introduce|provide)"
                r"\s+(?:(?i:an?)\s+)?"
                r"(?:(?:[A-Z][A-Za-z0-9_.]*)\s+)*"
                r"([A-Z][A-Za-z0-9_]*)\s+"
                r"(?=(?i:containing|with|that|which|inheriting|subclassing|extending))\b",
                owned_text,
            ),
            *re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\s+(?:class\s+)?"
                r"(?i:inheriting\s+from|subclassing|extends)\s+"
                r"[A-Z][A-Za-z0-9_.]*\b",
                owned_text,
            ),
            *re.findall(
                r"\b(?:and\s+)?([A-Z][A-Za-z0-9_]*)\s+"
                r"(?i:with)\s+[a-z_][A-Za-z0-9_]*\s*\(",
                owned_text,
            ),
        ]
        referenced_host_type_symbols = set(re.findall(
            r"\b(?:create|find|load|modify|return|save|update)\s+"
            r"(?:an?\s+)?([A-Z][A-Za-z0-9_]*)\b"
            r"[^.!?\n]{0,160}\b(?:unreal|bpy|maya\.cmds|cmds|pyfbsdk)\.",
            owned_text,
            flags=re.IGNORECASE,
        ))
        contextual_type_symbols = [
            symbol for symbol in contextual_type_symbols
            if symbol not in referenced_host_type_symbols
        ]
        introduction_symbols = [
            symbol for symbol in introduction_symbols
            if symbol not in referenced_host_type_symbols
        ]
        qualified_method_owner_symbols = [
            owner
            for owner, _method in re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\.([a-z_][A-Za-z0-9_]*)\s*\(",
                owned_text,
            )
            if owner not in referenced_host_type_symbols
        ]
        declared_type_symbols = {
            *[
                value
                for pair in type_matches
                for value in pair
                if value
            ],
            *contextual_type_symbols,
            *introduction_symbols,
        }
        method_owner_symbols = [
            value
            for value in re.findall(
                r"\b([A-Z][A-Za-z0-9_]*)\s+"
                r"(?i:must|should|shall|will|provides?|implements?|exposes?)\b"
                r"[^.!?\n]{0,160}",
                owned_text,
            )
            if not value.isupper() and value in declared_type_symbols
        ]
        function_symbols = [
            *re.findall(
                r"\b(?:function|def)\s+(?:named\s+)?"
                r"([a-z_][A-Za-z0-9_]*)\s*\(",
                owned_text,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"\b(?:add|create|define|defining|implement|introduce|provide|write)"
                r"\s+(?:(?:an?|the)\s+)?"
                r"(?:(?:function|callable)\s+(?:named\s+)?)?"
                r"([a-z_][A-Za-z0-9_]*)\s*\(",
                owned_text,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"\b(?:add|create|define|implement|include|introduce|provide|write)"
                r"\s+(?:(?:an?|the)\s+)?"
                r"(?:(?:working|public|top-level|module-level)\s+)*"
                r"([a-z_][A-Za-z0-9_]*)\s*\(",
                owned_text,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"\b([a-z_][A-Za-z0-9_]*)\s*\(\s*\)\s+functions?\b",
                owned_text,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"\bplus\s+([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)",
                owned_text,
                flags=re.IGNORECASE,
            ),
            *re.findall(
                r"(?m)^\s*([a-z_][A-Za-z0-9_]*)\s*\([^()\n]*\)\s*$",
                owned_text,
            ),
        ]
        method_like_names = set(re.findall(
            r"\b(?:add|create|define|implement|include|introduce|provide|write)"
            r"\s+(?:(?:an?|the)\s+)?"
            r"([a-z_][A-Za-z0-9_]*)\s*\(\s*self\b",
            owned_text,
            flags=re.IGNORECASE,
        ))
        function_symbols = [
            symbol
            for symbol in function_symbols
            if symbol not in method_like_names
        ]
        public_symbols = list(dict.fromkeys([
            *contextual_type_symbols,
            *[
                value
                for pair in type_matches
                for value in pair
                if value
            ],
            *introduction_symbols,
            *dedicated_error_symbols,
            *qualified_method_owner_symbols,
            *method_owner_symbols,
            *function_symbols,
        ]))
        if len(requested_paths) > 1 and bounded_declaration_symbols:
            public_symbols = list(dict.fromkeys([
                *bounded_declaration_symbols,
                *dedicated_error_symbols,
                *function_symbols,
            ]))
        ownership_contract_symbols = re.findall(
            r"\bproduction\s+file\s+owns\s+`([A-Z][A-Za-z0-9_]*)`",
            owned_text,
            flags=re.IGNORECASE,
        )
        if ownership_contract_symbols:
            public_symbols = list(dict.fromkeys([
                *ownership_contract_symbols,
                *dedicated_error_symbols,
                *function_symbols,
            ]))
        public_symbols = [
            symbol
            for symbol in public_symbols
            if not hasattr(builtins, symbol.rsplit(".", 1)[-1])
        ]
        is_test = path.name.startswith("test_")
        if (
            not is_test
            and len(requested_paths) == 1
            and not public_symbols
        ):
            import keyword

            provisional_function = re.sub(
                r"[^A-Za-z0-9_]+",
                "_",
                path.stem,
            ).strip("_").casefold()
            if (
                not provisional_function
                or not re.fullmatch(
                    r"[a-z_][a-z0-9_]*",
                    provisional_function,
                )
                or keyword.iskeyword(provisional_function)
            ):
                provisional_function = "run_generated_tool"
            public_symbols = [provisional_function]
        records.append({
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "absolute_path": str(path),
            "purpose": (
                "Behavioral proof for the explicitly requested generated package."
                if is_test
                else f"Implement the explicitly requested {path.name} behavior."
            ),
            "requirements": [
                str(item.get("text") or "") for item in owned_rows
            ],
            "requirement_ids": [
                str(item.get("id") or "")
                for item in owned_rows
                if str(item.get("id") or "")
            ],
            "public_symbols": [] if is_test else public_symbols,
            "contracts": [
                "Preserve every explicit signature, state transition, rejection, "
                "callback, round trip, and immutability requirement owned by this file."
            ],
            "algorithm_steps": [
                "Implement every requirement assigned to this file completely.",
                "Use dependency-owned public APIs rather than duplicate definitions.",
            ],
            "validation_steps": [
                "Execute disposable behavioral tests for every owned requirement."
            ],
            "integration_contracts": [
                f"Original requirement: {item.get('text')}"
                for item in owned_rows
            ],
            "depends_on": [],
            "is_test": is_test,
        })

    if (
        records
        and not any(bool(item.get("is_test")) for item in records)
        and re.search(
            r"\b(?:companion\s+tests?|focused\s+tests?|pytest|unittest|"
            r"test\s+files?|unit\s+tests?)\b",
            prompt,
            flags=re.IGNORECASE,
        )
        and not re.search(
            r"\b(?:no|without)\s+(?:new\s+|extra\s+|additional\s+)?tests?\b"
            r"|\b(?:do\s+not|don't)\s+"
            r"(?:create|add|generate|write|include|produce)\s+"
            r"(?:any\s+|new\s+|project\s+)*"
            r"(?:test\s+files?|tests?)\b"
            r"|\b(?:exactly|only)\s+"
            r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
            r"(?:new\s+)?(?:[A-Za-z0-9_+-]+\s+){0,3}files?\b"
            r"|\bno\s+(?:other|extra|additional)\s+files?\b"
            r"|\bdo\s+not\s+(?:add|create|generate|write)\s+(?:any\s+)?"
            r"(?:other|extra|additional)\s+files?\b"
            r"|\b(?:use|run|with)\s+disposable\s+(?:tests?|validation)\b"
            r".{0,120}\b(?:rather\s+than|instead\s+of|without)\b"
            r".{0,100}\b(?:adding|creating|writing|generating)?\s*"
            r"(?:permanent\s+|project\s+|production\s+)?test\s+files?\b",
            prompt,
            flags=re.IGNORECASE,
        )
    ):
        production_records = [
            item for item in records if not bool(item.get("is_test"))
        ]
        primary_stem = Path(production_records[0]["path"]).stem
        test_path = root / f"test_{primary_stem}.py"
        records.append({
            "path": str(test_path.relative_to(root)).replace("\\", "/"),
            "absolute_path": str(test_path),
            "purpose": (
                "Focused behavioral proof for the explicitly requested generated "
                "package."
            ),
            "requirements": [
                str(item.get("text") or "") for item in requirement_ledger
                if str(item.get("text") or "")
            ],
            "requirement_ids": [
                str(item.get("id") or "") for item in requirement_ledger
                if str(item.get("id") or "")
            ],
            "public_symbols": [],
            "contracts": [
                "Exercise every approved validation case through public interfaces; "
                "do not duplicate production implementations in tests."
            ],
            "algorithm_steps": [
                "Build deterministic fixtures for every requested success and failure.",
                "Assert state preservation after every rejected operation.",
                "Mock only unavailable host boundaries.",
            ],
            "validation_steps": [
                "Run the focused test module in the disposable workspace."
            ],
            "integration_contracts": [
                f"Original requirement: {item.get('text')}"
                for item in requirement_ledger
                if str(item.get("text") or "")
            ],
            "depends_on": [
                str(item.get("path") or "") for item in production_records
            ],
            "is_test": True,
        })

    unique_symbol_owner: dict[str, str] = {}
    duplicate_symbols: set[str] = set()
    for record in records:
        for symbol in record["public_symbols"]:
            if symbol in unique_symbol_owner:
                duplicate_symbols.add(symbol)
            else:
                unique_symbol_owner[symbol] = record["path"]
    for symbol in duplicate_symbols:
        unique_symbol_owner.pop(symbol, None)
    record_order = {
        str(record.get("path") or ""): index
        for index, record in enumerate(records)
    }
    architectural_terms = {
        "adapter",
        "client",
        "controller",
        "dialog",
        "manager",
        "model",
        "module",
        "panel",
        "repository",
        "service",
        "tool",
        "view",
        "widget",
        "window",
    }

    def declaration_terms(value: object) -> set[str]:
        if isinstance(value, Mapping):
            value = (
                value.get("qualified_name")
                or value.get("name")
                or value.get("owner")
                or ""
            )
        return {
            term.casefold()
            for term in re.findall(
                r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+",
                str(value),
            )
            if len(term) >= 3 and term.casefold() not in architectural_terms
        }

    for record in records:
        owned_text = "\n".join(record["requirements"])
        current_path = str(record.get("path") or "")
        current_index = record_order.get(current_path, len(records))
        current_declaration_terms = (
            set().union(*[
                declaration_terms(symbol)
                for symbol in record.get("public_symbols") or []
            ])
            if record.get("public_symbols")
            else set()
        )
        dependencies: list[str] = []
        for symbol, owner_path in unique_symbol_owner.items():
            if owner_path == record["path"]:
                continue
            owner_index = record_order.get(owner_path)
            if owner_index is not None and owner_index >= current_index:
                continue
            semantic_terms = declaration_terms(symbol)
            explicit_reference = bool(
                re.search(rf"\b{re.escape(symbol)}\b", owned_text)
            )
            semantic_reference = (
                len(semantic_terms & current_declaration_terms) >= 2
            )
            if explicit_reference or semantic_reference:
                dependencies.append(owner_path)
        record["depends_on"] = list(dict.fromkeys(dependencies))
    return records


def _fallback_requested_file_manifest(
    prompt: str,
    *,
    project_root: str,
    requirement_ledger: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Build a safe minimal work manifest from explicitly requested Python files."""

    import builtins

    explicit_manifest = _explicit_path_requested_file_manifest(
        prompt,
        project_root=project_root,
        requirement_ledger=requirement_ledger,
    )
    if explicit_manifest:
        return explicit_manifest

    filenames = list(dict.fromkeys(
        Path(match.group(0)).name
        for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\.py\b", prompt)
    ))
    explicit_owner_paths: dict[str, Path] = {}
    for owner_match in re.finditer(
        r"(?im)^\s*-\s*(?:production file|focused companion test file):\s*"
        r"(.+?\.py)\s*$",
        prompt,
    ):
        owner_path = Path(owner_match.group(1).strip()).resolve()
        explicit_owner_paths[owner_path.name] = owner_path
    generated_public_symbols: list[str] = []
    requirement_text = "\n".join(
        str(item.get("text") or "")
        for item in requirement_ledger
        if str(item.get("text") or "")
    )
    explicit_class_names = list(dict.fromkeys([
        *re.findall(
            r"\bclass\s+([A-Z][A-Za-z0-9_]*)",
            requirement_text,
        ),
        *re.findall(
            r"\b(?:add|build|create|define|implement|introduce|provide|write)"
            r"(?:\s+(?:a|an|the|new|complete|runnable|python|pyside6)){0,6}"
            r"\s+([A-Z][A-Za-z0-9_]*)\s+class\b",
            requirement_text,
            flags=re.IGNORECASE,
        ),
        *re.findall(
            r"\b([A-Z][A-Za-z0-9_]*(?:Dialog|Widget|Window|Panel|Dock))"
            r"\s+(?:QWidget|QDialog|widget|dialog|window)\b",
            requirement_text,
        ),
        *re.findall(
            r"\b(?:generic\s+)?([A-Z][A-Za-z0-9_]*)\s*"
            r"\[[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*\]",
            requirement_text,
            flags=re.IGNORECASE,
        ),
    ]))
    explicit_functions = [
        *re.findall(
            r"\b(?:function|def)\s+(?:named\s+)?([a-z_][A-Za-z0-9_]*)\s*\(",
            requirement_text,
            flags=re.IGNORECASE,
        ),
        *re.findall(
            r"\b(?:add|create|define|defining|implement|introduce|provide|write)"
            r"\s+(?:(?:an?|the)\s+)?"
            r"(?:(?:function|callable)\s+(?:named\s+)?)?"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            requirement_text,
            flags=re.IGNORECASE,
        ),
        *re.findall(
            r"\b([a-z_][A-Za-z0-9_]*)\s*\(\s*\)\s+function\b",
            requirement_text,
            flags=re.IGNORECASE,
        ),
        *re.findall(
            r"__main__[^\n.;]*?\b(?:runs?|calls?|invokes?)\s+"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            requirement_text,
            flags=re.IGNORECASE,
        ),
    ]
    generated_public_symbols = list(dict.fromkeys(
        symbol
        for symbol in [*explicit_class_names, *explicit_functions]
        if not (
            symbol[:1].isupper()
            and hasattr(builtins, symbol)
        )
    ))
    explicit_single_file_scope = bool(
        re.search(
            r"\b(?:exactly|only)\s+(?:one|1)\s+"
            r"(?:new\s+)?(?:[A-Za-z0-9_+-]+\s+){0,3}files?\b"
            r"|\bno\s+(?:other|extra|additional)\s+files?\b"
            r"|\bdo\s+not\s+(?:add|create|generate|write)\s+(?:any\s+)?"
            r"(?:other|extra|additional)\s+files?\b",
            prompt,
            flags=re.IGNORECASE,
        )
    )
    if len(filenames) < 2 and not explicit_single_file_scope:
        stop_words = {
            "add",
            "build",
            "create",
            "from",
            "make",
            "implement",
            "the",
            "this",
            "that",
            "with",
            "write",
            "anywhere",
            "pyside",
            "pyside6",
            "python",
        }
        name_words = [
            word
            for word in re.findall(r"[a-z][a-z0-9]+", prompt.lower())
            if word not in stop_words
            and word not in {"a", "an", "me", "us", "to", "for", "on", "of", "qt", "ui"}
        ]
        name_words = list(dict.fromkeys(name_words))[:4] or ["generated", "tool"]
        if re.search(r"\b(?:pick|select|choose)\b", prompt, flags=re.IGNORECASE):
            name_words = [
                word for word in name_words if word not in {"pick", "select", "choose"}
            ]
            name_words.append("picker")
        stem = "_".join(name_words)
        filenames = [f"{stem}.py", f"test_{stem}.py"]
        generated_name_classes = re.findall(
            r"\b([A-Z][A-Za-z0-9_]*)\s+class\b|\bclass\s+([A-Z][A-Za-z0-9_]*)",
            prompt,
        )
        generated_public_symbols = list(dict.fromkeys([
            *generated_public_symbols,
            *[
            value
            for pair in generated_name_classes
            for value in pair
            if value
            ],
        ]))
        if not generated_public_symbols and re.search(
            r"\b(?:qt|pyside6?|pyqt[56]?)\b.*\b(?:ui|dialog|window|widget|picker)\b"
            r"|\b(?:ui|dialog|window|widget|picker)\b.*\b(?:qt|pyside6?|pyqt[56]?)\b",
            prompt,
            flags=re.IGNORECASE,
        ):
            generated_public_symbols = [
                "".join(word.title() for word in name_words) + "Dialog"
            ]
    if not generated_public_symbols:
        import keyword

        production_filename = next(
            (
                filename
                for filename in filenames
                if not filename.startswith("test_")
            ),
            "",
        )
        provisional_function = re.sub(
            r"[^a-z0-9_]+",
            "_",
            Path(production_filename).stem.casefold(),
        ).strip("_")
        if not provisional_function or not re.match(
            r"^[a-z_][a-z0-9_]*$",
            provisional_function,
        ):
            provisional_function = "run_generated_tool"
        if keyword.iskeyword(provisional_function):
            provisional_function = f"run_{provisional_function.casefold()}"
        generated_public_symbols = [provisional_function]
    module_match = re.search(
        r"\bunder\s+([A-Za-z_][A-Za-z0-9_.]*)",
        prompt,
        flags=re.IGNORECASE,
    )
    module_parts = (
        module_match.group(1).split(".")
        if module_match
        else ["tech_connector", "services", "generated"]
    )
    root = Path(project_root).resolve()
    requirements = [
        str(item.get("text") or "")
        for item in requirement_ledger
        if str(item.get("scope") or "artifact") == "artifact"
        and str(item.get("text") or "")
    ]
    production_filenames = [
        filename for filename in filenames if not filename.startswith("test_")
    ]

    def _owned_file_clause(filename: str) -> str:
        """Return only clauses that immediately describe the named file."""

        owned: list[str] = []
        file_pattern = re.compile(
            r"\b[A-Za-z_][A-Za-z0-9_]*\.py\b",
            flags=re.IGNORECASE,
        )
        for match in re.finditer(
            rf"\b{re.escape(filename)}\b",
            prompt,
            flags=re.IGNORECASE,
        ):
            tail_start = match.end()
            next_file = file_pattern.search(prompt, tail_start)
            tail_end = next_file.start() if next_file else len(prompt)
            tail = prompt[tail_start:tail_end]
            boundary = re.search(
                r"[;\n]|(?<=[.!?])\s+(?=[A-Z])",
                tail,
            )
            if boundary:
                tail = tail[:boundary.start()]
            tail = tail.lstrip(" \t,:-")
            if re.match(
                r"(?:define|defines|defining|containing|contains?|with|"
                r"provides?|implements?)\b",
                tail,
                flags=re.IGNORECASE,
            ):
                owned.append(tail)
        return " ".join(owned)

    production_paths = []
    for filename in filenames:
        if filename.startswith("test_"):
            continue
        production_path = explicit_owner_paths.get(
            filename,
            root.joinpath(*module_parts, filename),
        )
        try:
            production_paths.append(
                str(production_path.relative_to(root)).replace("\\", "/")
            )
        except ValueError:
            production_paths.append(str(production_path).replace("\\", "/"))
    records: list[dict[str, Any]] = []
    for filename in sorted(filenames, key=lambda value: value.startswith("test_")):
        is_test = filename.startswith("test_")
        path = explicit_owner_paths.get(filename)
        if path is None:
            path = (
                root / "examples" / "tech_connector" / "tests" / filename
                if is_test
                else root.joinpath(*module_parts, filename)
            )
        clause = _owned_file_clause(filename)
        constructor_symbols = set(
            re.findall(r"\b([A-Z][A-Za-z0-9_]*)\s*\(", clause)
        )
        type_symbols = [
            symbol
            for symbol in re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", clause)
            if not symbol.isupper()
            and not hasattr(builtins, symbol)
            and (
                symbol in constructor_symbols
                or sum(character.isupper() for character in symbol) >= 2
                 or re.search(
                     rf"\b{re.escape(symbol)}\s+(?:class|dataclass)\b"
                     rf"|\b(?:define|defines|defining|provides?|implements?)\s+"
                     rf"(?:an?\s+)?(?:immutable\s+)?{re.escape(symbol)}\b",
                     clause,
                     flags=re.IGNORECASE,
                )
            )
        ]
        function_symbols = re.findall(
            r"\b(?:function|def)\s+([a-z_][A-Za-z0-9_]*)\s*\(",
            clause,
            flags=re.IGNORECASE,
        )
        public_symbols = list(dict.fromkeys([
            *(
                generated_public_symbols
                if len(production_filenames) == 1
                else []
            ),
            *type_symbols,
            *function_symbols,
        ]))
        records.append({
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "absolute_path": str(path),
            "purpose": (
                "Behavioral proof for the explicitly requested generated package."
                if is_test
                else f"Implement the explicitly requested {filename} behavior."
            ),
            "requirements": requirements or [prompt],
            "requirement_ids": [
                str(item.get("id") or "")
                for item in requirement_ledger
                if str(item.get("id") or "")
            ],
            "public_symbols": [] if is_test else public_symbols,
            "contracts": [
                "Preserve every explicit signature, state transition, rejection, "
                "callback, round trip, and immutability requirement in the objective."
            ],
            "algorithm_steps": [
                "Implement every behavior owned by this file completely.",
                "Use dependency-owned public APIs rather than duplicate definitions.",
            ],
            "validation_steps": [
                "Execute disposable behavioral tests for every owned requirement."
            ],
            "integration_contracts": [
                f"Original requirement: {value}" for value in (requirements or [prompt])
            ],
            "depends_on": production_paths if is_test else [],
            "is_test": is_test,
        })
    return records


def _checkpoint_provenance(
    project_root: str,
    prompt: str,
    generated_files: list[tuple[str, str, str]],
    implementation_plan_hash: str,
) -> dict[str, str]:
    requirement_ledger = extract_project_edit_artifact_requirements(prompt)
    manifest = _fallback_requested_file_manifest(
        prompt,
        project_root=project_root,
        requirement_ledger=requirement_ledger,
    )
    return {
        "requirements_hash": _checkpoint_hash(requirement_ledger),
        "manifest_hash": _checkpoint_hash(manifest),
        "validator_version": WORKFLOW_CHECKPOINT_VALIDATOR_VERSION,
        "implementation_plan_hash": str(implementation_plan_hash or ""),
        "generated_source_hash": _checkpoint_hash(
            [list(row) for row in generated_files]
        ),
    }


def _checkpoint_payload_is_reusable(
    payload: Any,
    *,
    project_root: str,
    prompt: str,
    generated_files: list[tuple[str, str, str]],
    implementation_plan_hash: str,
) -> bool:
    if not isinstance(payload, dict):
        return False
    state = payload.get("workflow_state")
    if not isinstance(state, dict):
        return False
    validation_state = str(state.get("validation_state") or "")
    if state.get("complete") is True:
        validation_state = "validated"
    if validation_state not in {"validated", "candidate", "unvalidated"}:
        return False
    expected = _checkpoint_provenance(
        project_root,
        prompt,
        generated_files,
        implementation_plan_hash,
    )
    stored = payload.get("provenance")
    if not isinstance(stored, dict):
        return False
    # A candidate rejected by an older validator is not independently validated
    # evidence. Reuse it only when every provenance input, including the validator,
    # still matches.
    required_keys = set(expected)
    return all(
        stored.get(key) == expected[key]
        for key in required_keys
    )


def _load_workflow_checkpoint(
    project_root: str,
    prompt: str,
    selected_model: str,
    implementation_plan_hash: str,
) -> list[tuple[str, str, str]]:
    """Load a resumable candidate; validation remains authoritative."""

    checkpoint = _workflow_checkpoint_path(project_root, prompt, selected_model)
    try:
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    rows = payload.get("generated_files") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    restored: list[tuple[str, str, str]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            return []
        restored.append(tuple(str(value) for value in row))
    if not _checkpoint_payload_is_reusable(
        payload,
        project_root=project_root,
        prompt=prompt,
        generated_files=restored,
        implementation_plan_hash=implementation_plan_hash,
    ):
        return []
    return restored


def _load_workflow_checkpoint_state(
    project_root: str,
    prompt: str,
    selected_model: str,
    implementation_plan_hash: str,
) -> dict[str, Any]:
    """Load resumable repair state stored beside the generated candidate."""

    checkpoint = _workflow_checkpoint_path(project_root, prompt, selected_model)
    try:
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    rows = payload.get("generated_files") if isinstance(payload, dict) else None
    generated_files = (
        [tuple(str(value) for value in row) for row in rows]
        if isinstance(rows, list)
        and all(isinstance(row, list) and len(row) == 3 for row in rows)
        else []
    )
    if not generated_files or not _checkpoint_payload_is_reusable(
        payload,
        project_root=project_root,
        prompt=prompt,
        generated_files=generated_files,
        implementation_plan_hash=implementation_plan_hash,
    ):
        return {}
    state = payload.get("workflow_state") if isinstance(payload, dict) else None
    if not isinstance(state, dict):
        return {}
    restored = dict(state)
    provenance = payload.get("provenance")
    stored_validator = (
        str(provenance.get("validator_version") or "")
        if isinstance(provenance, dict)
        else ""
    )
    if (
        stored_validator != WORKFLOW_CHECKPOINT_VALIDATOR_VERSION
        or not bool(restored.get("complete"))
    ):
        for transient_key in (
            "attempt",
            "class_repair_attempts",
            "compact_callable_attempts",
            "file_repair_attempts",
            "final_review_errors",
            "final_review_fingerprint",
            "stalled_callable_symbols",
            "strong_callable_symbols",
        ):
            restored.pop(transient_key, None)
        restored["validation_state"] = "unvalidated"
        restored["complete"] = False
    return restored


def _save_workflow_checkpoint(
    project_root: str,
    prompt: str,
    selected_model: str,
    generated_files: list[tuple[str, str, str]],
    workflow_state: dict[str, Any] | None = None,
    implementation_plan_hash: str = "",
) -> None:
    """Atomically persist the latest candidate for interruption recovery."""

    checkpoint = _workflow_checkpoint_path(project_root, prompt, selected_model)
    try:
        state = dict(workflow_state or {})
        if checkpoint.is_file():
            try:
                persisted_payload = json.loads(
                    checkpoint.read_text(encoding="utf-8")
                )
                persisted_state = persisted_payload.get("workflow_state") or {}
                if (
                    isinstance(persisted_state, dict)
                    and "behavior_harness" not in state
                    and isinstance(
                        persisted_state.get("behavior_harness"),
                        dict,
                    )
                ):
                    state["behavior_harness"] = dict(
                        persisted_state["behavior_harness"]
                    )
            except (OSError, ValueError, TypeError):
                pass
        state["validation_state"] = (
            "validated"
            if state.get("complete") is True
            else str(state.get("validation_state") or "unvalidated")
        )
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "generated_files": [list(row) for row in generated_files],
                    "workflow_state": state,
                    "provenance": _checkpoint_provenance(
                        project_root,
                        prompt,
                        generated_files,
                        implementation_plan_hash,
                    ),
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(checkpoint)
    except OSError:
        return


def _enrich_manifest_with_explicit_declarations(
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, Any]],
) -> None:
    """Restore explicitly requested top-level owners before chunk planning."""

    production_files = [
        item for item in manifest if not bool(item.get("is_test"))
    ]
    if len(production_files) > 1:
        ledger_by_id = {
            str(
                item.get("id")
                or item.get("requirement_id")
                or ""
            ): item
            for item in requirement_ledger
        }
        for production_file in production_files:
            if production_file.get("public_symbols"):
                continue
            owned_ids = {
                str(value)
                for value in production_file.get("requirement_ids") or []
                if str(value)
            }
            owned_ledger = [
                ledger_by_id[requirement_id]
                for requirement_id in owned_ids
                if requirement_id in ledger_by_id
            ]
            _enrich_manifest_with_explicit_declarations(
                [production_file],
                owned_ledger,
            )
        return
    if len(production_files) != 1:
        return

    declaration_rows: dict[tuple[str, str], dict[str, Any]] = {}
    requirement_texts: list[str] = []
    for requirement in requirement_ledger:
        requirement_id = str(
            requirement.get("id")
            or requirement.get("requirement_id")
            or ""
        ).strip()
        text = str(
            requirement.get("text")
            or requirement.get("requirement")
            or requirement.get("description")
            or ""
        )
        requirement_texts.append(text)
        referenced_api_types = set(re.findall(
            r"\b(?:existing|official|public|valid|verified)\s+"
            r"(?:[A-Z][A-Za-z0-9_.]*\s+){0,3}"
            r"([A-Z][A-Za-z0-9_]*)\s+class\b",
            text,
            flags=re.IGNORECASE,
        ))
        class_names = list(dict.fromkeys([
            *re.findall(
                r"\bclass\s+([A-Z][A-Za-z0-9_]*)\b",
                text,
            ),
            *re.findall(
                r"\b([A-Z][A-Za-z0-9_]*(?:Dialog|Widget|Window|Panel|Dock))"
                r"\s+(?:QWidget|QDialog|widget|dialog|window)\b",
                text,
            ),
            *re.findall(
                r"\b(?i:add|create|define|defining|implement|include|introduce|provide|write)"
                r"\s+(?:(?i:an?|the)\s+)?"
                r"(?:(?i:modal|modeless|public|top-level)\s+)*"
                r"([A-Z][A-Za-z0-9_]*)\b"
                r"(?=\s+(?i:class|inheriting|extending)\b|[\s,.;:]|$)",
                text,
            ),
            *[
                value
                for pair in re.findall(
                    r"\b([A-Z][A-Za-z0-9_]*)"
                    r"(?:\s*\[[^\]\n]+\])?\s+class\b",
                    text,
                )
                for value in [pair]
                if value not in referenced_api_types
            ],
        ]))
        for name in class_names:
            if name:
                row = declaration_rows.setdefault(
                    ("class", name),
                    {
                        "name": name,
                        "qualified_name": name,
                        "kind": "class",
                        "requirement_ids": [],
                    },
                )
                if requirement_id and requirement_id not in row["requirement_ids"]:
                    row["requirement_ids"].append(requirement_id)

        for name in re.findall(
            r"\b(?:function|def)\s+(?:named\s+)?"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            text,
            flags=re.IGNORECASE,
        ):
            row = declaration_rows.setdefault(
                ("function", name),
                {
                    "name": name,
                    "qualified_name": name,
                    "kind": "function",
                    "requirement_ids": [],
                },
            )
            if requirement_id and requirement_id not in row["requirement_ids"]:
                row["requirement_ids"].append(requirement_id)
        for name in re.findall(
            r"\b(?:add|create|define|defining|expose|implement|introduce|provide|write)"
            r"\s+(?:(?:an?|the)\s+)?"
            r"(?:(?:function|callable)\s+(?:named\s+)?)?"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            text,
            flags=re.IGNORECASE,
        ):
            row = declaration_rows.setdefault(
                ("function", name),
                {
                    "name": name,
                    "qualified_name": name,
                    "kind": "function",
                    "requirement_ids": [],
                },
            )
            if requirement_id and requirement_id not in row["requirement_ids"]:
                row["requirement_ids"].append(requirement_id)
        for name in re.findall(
            r"\b(?:add|create|define|implement|introduce|provide|write)\b"
            r"[^.!?\n]{0,160}\.py\b[^.!?\n]{0,80}"
            r"\b(?:with|containing|exposing)\s+"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            text,
            flags=re.IGNORECASE,
        ):
            row = declaration_rows.setdefault(
                ("function", name),
                {
                    "name": name,
                    "qualified_name": name,
                    "kind": "function",
                    "requirement_ids": [],
                },
            )
            if requirement_id and requirement_id not in row["requirement_ids"]:
                row["requirement_ids"].append(requirement_id)
        for name in re.findall(
            r"\b(?:add|create|define|implement|include|introduce|provide|write)"
            r"\s+(?:(?:an?|the)\s+)?"
            r"(?:(?:working|public|top-level|module-level)\s+)*"
            r"([a-z_][A-Za-z0-9_]*)\s*\(",
            text,
            flags=re.IGNORECASE,
        ):
            row = declaration_rows.setdefault(
                ("function", name),
                {
                    "name": name,
                    "qualified_name": name,
                    "kind": "function",
                    "requirement_ids": [],
                },
            )
            if requirement_id and requirement_id not in row["requirement_ids"]:
                row["requirement_ids"].append(requirement_id)
        for name in re.findall(
            r"(?<![A-Za-z0-9_])"
            r"([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*"
            r"(?:->\s*[A-Za-z_][A-Za-z0-9_.]*"
            r"(?:\[[^\]]+\])?\s*)?"
            r"(?:method|function|callable)\b",
            text,
            flags=re.IGNORECASE,
        ):
            row = declaration_rows.setdefault(
                ("function", name),
                {
                    "name": name,
                    "qualified_name": name,
                    "kind": "function",
                    "requirement_ids": [],
                },
            )
            if requirement_id and requirement_id not in row["requirement_ids"]:
                row["requirement_ids"].append(requirement_id)

    combined_requirements = "\n".join(requirement_texts)
    invalid_owner_words = {
        "A",
        "An",
        "Any",
        "Each",
        "Every",
        "It",
        "Its",
        "That",
        "The",
        "These",
        "They",
        "This",
        "Those",
    }
    declaration_rows = {
        key: row
        for key, row in declaration_rows.items()
        if key[1].rsplit(".", 1)[-1] not in invalid_owner_words
    }
    explicit_class_names = {
        name
        for kind, name in declaration_rows
        if kind == "class"
    }
    explicit_top_level_functions = bool(
        re.search(
            r"\b(?:top-level|module-level|free)\s+(?:Python\s+)?functions?\b"
            r"|\bfunctions?\s+named\b",
            combined_requirements,
            flags=re.IGNORECASE,
        )
    )
    if len(explicit_class_names) == 1 and not explicit_top_level_functions:
        declaration_rows = {
            key: row
            for key, row in declaration_rows.items()
            if key[0] != "function"
        }

    public_quality_requirement_ids = list(dict.fromkeys(
        str(item.get("id") or item.get("requirement_id") or "")
        for item in requirement_ledger
        if str(item.get("id") or item.get("requirement_id") or "")
        and re.search(
            r"\b(?:type\s+(?:hints?|annotations?)|docstrings?)\b",
            str(item.get("text") or ""),
            flags=re.IGNORECASE,
        )
    ))
    if not declaration_rows:
        source_path = Path(
            str(
                production_files[0].get("absolute_path")
                or production_files[0].get("path")
                or ""
            )
        )
        try:
            source_tree = ast.parse(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path),
            )
        except (OSError, SyntaxError, UnicodeDecodeError):
            source_tree = ast.Module(body=[], type_ignores=[])
        public_declarations = [
            node
            for node in source_tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        ]
        if len(public_declarations) == 1:
            node = public_declarations[0]
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            declaration_rows[(kind, node.name)] = {
                "name": node.name,
                "qualified_name": node.name,
                "kind": kind,
                "requirement_ids": list(dict.fromkeys(
                    str(item.get("id") or item.get("requirement_id") or "")
                    for item in requirement_ledger
                    if str(item.get("id") or item.get("requirement_id") or "")
                )),
            }
        elif not public_quality_requirement_ids:
            return
    if public_quality_requirement_ids:
        source_path = Path(
            str(
                production_files[0].get("absolute_path")
                or production_files[0].get("path")
                or ""
            )
        )
        try:
            source_tree = ast.parse(
                source_path.read_text(encoding="utf-8"),
                filename=str(source_path),
            )
        except (OSError, SyntaxError, UnicodeDecodeError):
            source_tree = ast.Module(body=[], type_ignores=[])
        for node in source_tree.body:
            if not isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ) or node.name.startswith("_"):
                continue
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            row = declaration_rows.setdefault(
                (kind, node.name),
                {
                    "name": node.name,
                    "qualified_name": node.name,
                    "kind": kind,
                    "requirement_ids": [],
                },
            )
            row["requirement_ids"] = list(dict.fromkeys([
                *row.get("requirement_ids", []),
                *public_quality_requirement_ids,
            ]))
    public_symbols = []
    for raw_symbol in production_files[0].get("public_symbols") or []:
        if isinstance(raw_symbol, dict):
            symbol_name = str(
                raw_symbol.get("qualified_name")
                or raw_symbol.get("name")
                or raw_symbol.get("owner")
                or ""
            ).strip()
            symbol_kind = str(raw_symbol.get("kind") or "symbol").strip()
        else:
            symbol_name = str(raw_symbol).split("(", 1)[0].strip()
            symbol_kind = (
                "class"
                if symbol_name.rsplit(".", 1)[-1][:1].isupper()
                else "function"
            )
        if symbol_name.rsplit(".", 1)[-1] in invalid_owner_words:
            continue
        if (
            len(explicit_class_names) == 1
            and not explicit_top_level_functions
            and symbol_kind == "function"
        ):
            continue
        public_symbols.append(raw_symbol)
    existing = {
        (
            str(item.get("kind") or "symbol"),
            str(
                item.get("qualified_name")
                or item.get("name")
                or item.get("owner")
                or ""
            ),
        )
        if isinstance(item, dict)
        else (
            "class"
            if str(item).rsplit(".", 1)[-1][:1].isupper()
            else "function",
            str(item).split("(", 1)[0].strip(),
        )
        for item in public_symbols
    }
    public_symbols.extend(
        row
        for key, row in declaration_rows.items()
        if key not in existing
    )
    production_files[0]["public_symbols"] = public_symbols


def _requirement_ledger_needs_semantic_review(
    requirement_ledger: list[dict[str, str]],
) -> bool:
    """Return whether structured extraction explicitly left semantic ambiguity."""
    if not requirement_ledger:
        return True
    ids = [str(item.get("id") or "").strip() for item in requirement_ledger]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        return True
    for item in requirement_ledger:
        if not str(item.get("text") or "").strip():
            return True
        if item.get("ambiguous") is True or item.get("requires_review") is True:
            return True
        if item.get("unresolved_references"):
            return True
    return False


def _resolve_structurally_sectioned_module_requirements(
    manifest: list[dict[str, Any]],
    requirement_ledger: list[dict[str, Any]],
    unresolved_requirements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve requirements scoped by explicit backend and UI prompt sections.

    This deterministic shortcut is intentionally conservative. It activates only
    when exactly one requested production module is clearly UI-owned and exactly
    one is non-UI. Requirements outside an explicit section remain unresolved
    unless they are package-wide quality or artifact-boundary clauses.
    """

    production_rows = [
        (index, item)
        for index, item in enumerate(manifest, start=1)
        if not bool(item.get("is_test"))
    ]
    if len(production_rows) != 2:
        return [], unresolved_requirements

    def path_text(item: dict[str, Any]) -> str:
        return str(item.get("path") or item.get("absolute_path") or "").casefold()

    ui_rows = [
        row
        for row in production_rows
        if re.search(r"(?:^|[_.\\/])(?:ui|dialog|widget|window)(?:[_.\\/]|$)", path_text(row[1]))
    ]
    if len(ui_rows) != 1:
        return [], unresolved_requirements
    backend_rows = [row for row in production_rows if row != ui_rows[0]]
    if len(backend_rows) != 1:
        return [], unresolved_requirements

    def declaration_rows(
        file_index: int,
        item: dict[str, Any],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for symbol_index, raw_symbol in enumerate(
            item.get("public_symbols") or [],
            start=1,
        ):
            if isinstance(raw_symbol, Mapping):
                name = str(
                    raw_symbol.get("qualified_name")
                    or raw_symbol.get("name")
                    or raw_symbol.get("owner")
                    or ""
                ).strip()
                kind = str(raw_symbol.get("kind") or "symbol").strip()
            else:
                name = str(raw_symbol).split("(", 1)[0].strip()
                kind = "class" if name.rsplit(".", 1)[-1][:1].isupper() else "function"
            if name:
                rows.append({
                    "id": f"D{file_index}_{symbol_index}",
                    "name": name,
                    "kind": kind,
                })
        return rows

    declarations_by_file = {
        index: declaration_rows(index, item)
        for index, item in production_rows
    }

    def default_owner(file_index: int) -> str:
        class_ids = [
            row["id"]
            for row in declarations_by_file[file_index]
            if row["kind"] == "class"
        ]
        return class_ids[0] if len(class_ids) == 1 else f"D{file_index}_MODULE"

    def mentioned_declaration_ids(file_index: int, text: str) -> list[str]:
        return [
            row["id"]
            for row in declarations_by_file[file_index]
            if re.search(
                rf"(?<![A-Za-z0-9_])"
                rf"{re.escape(row['name'].rsplit('.', 1)[-1])}"
                rf"(?![A-Za-z0-9_])",
                text,
            )
        ]

    def mentioned_file_indices(text: str) -> list[int]:
        matches: list[int] = []
        for index, item in production_rows:
            path = Path(str(item.get("path") or item.get("absolute_path") or ""))
            names = {path.name.casefold(), path.stem.casefold()}
            if any(
                name
                and re.search(
                    rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])",
                    text.casefold(),
                )
                for name in names
            ):
                matches.append(index)
        if not matches and re.search(
            r"\b(?:newly\s+created\s+|new\s+)?"
            r"(?:qt\s+|gui\s+)?ui\s+(?:production\s+)?file\b",
            text,
            flags=re.IGNORECASE,
        ):
            matches.extend(index for index, _item in ui_rows)
        if not matches and re.search(
            r"\b(?:headless\s+)?(?:backend|service|engine)\s+"
            r"(?:production\s+)?file\b",
            text,
            flags=re.IGNORECASE,
        ):
            matches.extend(index for index, _item in backend_rows)
        return matches

    def capability_owner_index(text: str) -> int:
        """Return a deterministic owner only when capability evidence is decisive."""

        lowered = text.casefold()
        ui_score = sum(
            1
            for pattern in (
                r"\b(?:ui|dialog|widget|window)\b",
                r"\b(?:buttons?|inputs?|spinboxes?|comboboxes?|"
                r"progress[_ ]?bars?|labels?|controls?)\b",
                r"\b(?:signal|slot|clicked|connect(?:ed|ion)?)\b",
                r"\b(?:qthread|qrunnable|threadpool|worker)\b",
                r"\b(?:ui|gui|main)\s+thread\b",
                r"\b__main__\b|\bshow\s*\(",
            )
            if re.search(pattern, lowered)
        )
        backend_score = sum(
            1
            for pattern in (
                r"\b(?:backend|service|engine|adapter)\b",
                r"\b(?:export|import|handoff|transfer|sync)\b",
                r"\b(?:selection|selected asset|destination)\b",
                r"\b(?:progress[_ ]?callback|return(?:ing|s|ed)?)\b",
                r"\b(?:temporary|temp)\b.*\b(?:file|path|directory|folder)\b",
            )
            if re.search(pattern, lowered)
        )
        if ui_score > backend_score and ui_score:
            return ui_index
        if backend_score > ui_score and backend_score:
            return backend_index
        return 0

    ui_index = ui_rows[0][0]
    backend_index = backend_rows[0][0]
    all_owner_ids = [
        owner_id
        for index, _item in production_rows
        for owner_id in [
            f"D{index}_MODULE",
            *[row["id"] for row in declarations_by_file[index]],
        ]
    ]
    unresolved_ids = {
        str(row.get("id") or row.get("requirement_id") or "")
        for row in unresolved_requirements
    }
    assignments: list[dict[str, Any]] = []
    resolved_ids: set[str] = set()
    active_file_index = 0

    for row in requirement_ledger:
        requirement_id = str(row.get("id") or row.get("requirement_id") or "")
        text = str(row.get("text") or row.get("requirement") or "")
        lowered = text.casefold()

        if re.search(
            r"\b(?:qt|ui|dialog|widget|window)\s+(?:production\s+)?file\s+must\b",
            lowered,
        ):
            active_file_index = ui_index
        elif re.search(
            r"\b(?:headless\s+)?(?:backend|service|engine)\s+must\b",
            lowered,
        ):
            active_file_index = backend_index

        package_wide = bool(re.search(
            r"^\s*(?:give\s+every\s+public|do\s+not\s+emit|"
            r"generate\s+only|use\s+disposable\s+validation|"
            r"do\s+not\s+report\s+completion|create\s+exactly\s+"
            r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
            r"production\s+files?)\b",
            lowered,
        ))
        package_structure = bool(re.search(
            r"^\s*(?:create|add|build|generate|write)\b"
            r"[^.!?\n]{0,120}\b(?:package|production\s+files?)\b",
            lowered,
        ))
        module_operation = bool(re.search(
            r"\b__main__\b|\bmodule[- ]level\b|\bentry\s+point\b",
            text,
            flags=re.IGNORECASE,
        ))
        semantic_role = "entry_point" if module_operation else "behavior"
        if package_structure:
            declaration_ids = [
                f"D{index}_MODULE"
                for index, _item in production_rows
            ]
            semantic_role = "structure"
        elif package_wide:
            declaration_ids = list(all_owner_ids)
        else:
            directly_mentioned = [
                declaration_id
                for index, _item in production_rows
                for declaration_id in mentioned_declaration_ids(index, text)
            ]
            directly_mentioned_files = mentioned_file_indices(text)
            if module_operation and directly_mentioned_files:
                declaration_ids = [
                    f"D{index}_MODULE"
                    for index in directly_mentioned_files
                ]
            elif directly_mentioned:
                declaration_ids = directly_mentioned
            elif directly_mentioned_files:
                declaration_ids = [
                    default_owner(index)
                    for index in directly_mentioned_files
                ]
            else:
                inferred_file_index = capability_owner_index(text)
                declaration_ids = (
                    [
                        (
                            f"D{inferred_file_index}_MODULE"
                            if module_operation
                            else default_owner(inferred_file_index)
                        )
                    ]
                    if inferred_file_index
                    else []
                )
        if not declaration_ids and active_file_index:
            declaration_ids = mentioned_declaration_ids(active_file_index, text)
            if re.search(
                r"\b__main__\b|\bmodule[- ]level\b|\bentry\s+point\b",
                text,
                flags=re.IGNORECASE,
            ):
                declaration_ids.append(f"D{active_file_index}_MODULE")
            if not declaration_ids:
                declaration_ids = [default_owner(active_file_index)]
            declaration_ids = list(dict.fromkeys(declaration_ids))
        if not declaration_ids:
            for index, item in production_rows:
                stem = Path(str(item.get("path") or "")).stem.casefold()
                if stem and re.search(rf"(?<![a-z0-9_]){re.escape(stem)}(?![a-z0-9_])", lowered):
                    declaration_ids = (
                        mentioned_declaration_ids(index, text)
                        or [default_owner(index)]
                    )
                    break
        if not declaration_ids:
            continue

        assignments.append({
            "requirement_id": requirement_id,
            "semantic_role": semantic_role,
            "declaration_ids": declaration_ids,
            "depends_on": [],
        })
        resolved_ids.add(requirement_id)

    remaining = [
        row
        for row in unresolved_requirements
        if str(row.get("id") or row.get("requirement_id") or "") not in resolved_ids
    ]
    return assignments, remaining
