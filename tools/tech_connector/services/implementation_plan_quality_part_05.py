"""Dependency-ordered implementation-plan quality functions."""
from __future__ import annotations

import ast
import builtins
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping


_UI_ATTRIBUTE_SUFFIXES = (
    "_bar",
    "_btn",
    "_button",
    "_checkbox",
    "_combo",
    "_dial",
    "_editor",
    "_group",
    "_input",
    "_label",
    "_list",
    "_radio",
    "_slider",
    "_spinbox",
    "_stack",
    "_table",
    "_tabs",
    "_tree",
    "_view",
    "_widget",
)
_MODULE_CALLABLES = {
    name.casefold()
    for name in dir(builtins)
    if callable(getattr(builtins, name, None))
}
from tech_connector.services.implementation_plan_quality_contract import (
    APPROVED_PLAN_SCHEMA,
    APPROVED_PLAN_VALIDATOR_VERSION,
)

from tech_connector.services.implementation_plan_quality_part_02 import (
    _definition_nodes,
    _method_map,
)


def apply_deterministic_implementation_plan_repairs(
    implementation_plan: Mapping[str, Any],
    generated_files: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Apply mechanically proven AST repairs encoded by approved contracts."""

    updated = list(generated_files)
    fixes: list[str] = []
    chunks_by_path: dict[str, list[Mapping[str, Any]]] = {}
    chunks_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        chunk_path = Path(str(chunk.get("path") or ""))
        path = str(chunk_path.resolve())
        chunks_by_path.setdefault(path, []).append(chunk)
        chunks_by_name.setdefault(chunk_path.name.casefold(), []).append(chunk)

    requirement_text = " ".join(
        str(requirement.get("text") or "")
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for requirement in chunk.get("requirements") or []
        if isinstance(requirement, Mapping)
    )
    exception_message_contract_explicit = bool(
        re.search(
            r"\b(?:error|exception)\s+message\b"
            r"|\bmessage\s+(?:text|contains|includes|matches|is|must)\b",
            requirement_text,
            flags=re.IGNORECASE,
        )
    )
    slot_buttons: dict[str, set[str]] = {}
    for path_text, _original, source in updated:
        if Path(path_text).name.startswith("test_"):
            continue
        try:
            production_tree = ast.parse(source, filename=path_text)
        except SyntaxError:
            continue
        for call in [
            node for node in ast.walk(production_tree) if isinstance(node, ast.Call)
        ]:
            if not (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "connect"
                and isinstance(call.func.value, ast.Attribute)
                and isinstance(call.func.value.value, ast.Attribute)
                and isinstance(call.func.value.value.value, ast.Name)
                and call.func.value.value.value.id == "self"
                and call.args
                and isinstance(call.args[0], ast.Attribute)
                and isinstance(call.args[0].value, ast.Name)
                and call.args[0].value.id == "self"
            ):
                continue
            button_name = call.func.value.value.attr
            slot_name = call.args[0].attr
            slot_buttons.setdefault(slot_name, set()).add(button_name)
    unique_slot_buttons = {
        slot: next(iter(buttons))
        for slot, buttons in slot_buttons.items()
        if len(buttons) == 1
    }
    approved_class_surfaces: dict[str, set[str]] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if (
            not isinstance(chunk, Mapping)
            or str(chunk.get("kind") or "") != "class"
        ):
            continue
        contract = chunk.get("declaration_contract") or {}
        surface = {
            str(value)
            for value in contract.get("required_methods") or []
            if str(value)
        }
        surface.update(
            str(task.get("name") or "")
            for task in chunk.get("method_tasks") or []
            if isinstance(task, Mapping)
            and str(task.get("name") or "")
        )
        surface.update(
            str(attribute.get("name") or "")
            for attribute in contract.get("attributes") or []
            if isinstance(attribute, Mapping)
            and str(attribute.get("name") or "")
        )
        surface.add("__init__")
        approved_class_surfaces[str(chunk.get("owner") or "")] = surface

    for index, (path_text, original, source) in enumerate(updated):
        path = str(Path(path_text).resolve())
        chunks = chunks_by_path.get(path, [])
        if not chunks:
            name_matches = chunks_by_name.get(Path(path).name.casefold(), [])
            if len(name_matches) == 1:
                chunks = name_matches
        normalized_layout = re.sub(
            r"(?m)^(@[^\n]+)\n(?:[ \t]*\n)+(?=(?:class|def|async def)\s)",
            r"\1\n",
            source,
        )
        if normalized_layout != source:
            source = normalized_layout
            updated[index] = (path_text, original, source)
            fixes.append(
                f"{path}: removed blank lines between decorators and declarations."
            )
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        property_accesses_by_owner: dict[str, set[str]] = {}
        verified_dependency_imports: set[tuple[str, str]] = set()
        for chunk in chunks:
            contract = (
                chunk.get("declaration_contract")
                if isinstance(chunk.get("declaration_contract"), Mapping)
                else {}
            )
            owner_name = str(chunk.get("owner") or "")
            property_accesses_by_owner.setdefault(owner_name, set()).update(
                str(item.get("name") or "").rsplit(".", 1)[-1]
                for item in contract.get("required_accesses") or []
                if isinstance(item, Mapping)
                and str(item.get("name") or "")
            )
            for item in [
                *[
                    value
                    for value in contract.get("required_calls") or []
                    if isinstance(value, Mapping)
                ],
                *[
                    value
                    for value in contract.get("required_accesses") or []
                    if isinstance(value, Mapping)
                ],
            ]:
                qualified_name = str(item.get("name") or "")
                qualified_owner = qualified_name.rsplit(".", 1)[0]
                module_name, separator, binding_name = qualified_owner.rpartition(
                    "."
                )
                if (
                    separator
                    and module_name
                    and binding_name[:1].isupper()
                ):
                    verified_dependency_imports.add(
                        (module_name, binding_name)
                    )

        def dotted_expression(node: ast.AST) -> str:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                prefix = dotted_expression(node.value)
                return f"{prefix}.{node.attr}" if prefix else node.attr
            return ""

        dependency_bindings = {
            f"{module_name}.{binding_name}": binding_name
            for module_name, binding_name in verified_dependency_imports
        }
        verified_call_limits: dict[str, set[int]] = {}
        for chunk in chunks:
            contract = (
                chunk.get("declaration_contract")
                if isinstance(chunk.get("declaration_contract"), Mapping)
                else {}
            )
            for required_call in contract.get("required_calls") or []:
                if not isinstance(required_call, Mapping):
                    continue
                required_name = str(required_call.get("name") or "")
                signature = str(required_call.get("signature") or "")
                if not required_name or "(" not in signature or ")" not in signature:
                    continue
                try:
                    signature_tree = ast.parse(
                        "def _verified"
                        + signature[signature.find("("):]
                        + ":\n    pass\n"
                    )
                    signature_args = signature_tree.body[0].args
                except (SyntaxError, AttributeError):
                    continue
                if signature_args.vararg is not None:
                    continue
                positional_parameters = [
                    *signature_args.posonlyargs,
                    *signature_args.args,
                ]
                if (
                    positional_parameters
                    and positional_parameters[0].arg in {"self", "cls"}
                ):
                    positional_parameters = positional_parameters[1:]
                verified_call_limits.setdefault(
                    required_name.rsplit(".", 1)[-1],
                    set(),
                ).add(len(positional_parameters))
        unambiguous_verified_call_limits = {
            terminal: next(iter(limits))
            for terminal, limits in verified_call_limits.items()
            if len(limits) == 1
        }

        class ContractSyntaxRepair(ast.NodeTransformer):
            def __init__(self) -> None:
                self.owner_stack: list[str] = []
                self.changed = False
                self.arity_repairs: set[str] = set()

            def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
                self.owner_stack.append(node.name)
                node = self.generic_visit(node)
                self.owner_stack.pop()
                return node

            def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
                pushed = not self.owner_stack
                if pushed:
                    self.owner_stack.append(node.name)
                node = self.generic_visit(node)
                if pushed:
                    self.owner_stack.pop()
                return node

            def visit_AsyncFunctionDef(
                self, node: ast.AsyncFunctionDef
            ) -> ast.AST:
                return self.visit_FunctionDef(node)

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                node = self.generic_visit(node)
                qualified = dotted_expression(node)
                binding = dependency_bindings.get(qualified)
                if binding:
                    self.changed = True
                    return ast.copy_location(
                        ast.Name(id=binding, ctx=node.ctx),
                        node,
                    )
                return node

            def visit_Call(self, node: ast.Call) -> ast.AST:
                node = self.generic_visit(node)
                owner_name = self.owner_stack[-1] if self.owner_stack else ""
                property_names = property_accesses_by_owner.get(owner_name, set())
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in property_names
                    and not node.args
                    and not node.keywords
                ):
                    self.changed = True
                    return ast.copy_location(node.func, node)
                if isinstance(node.func, ast.Attribute):
                    maximum_positional = unambiguous_verified_call_limits.get(
                        node.func.attr
                    )
                    if (
                        maximum_positional is not None
                        and len(node.args) > maximum_positional
                    ):
                        node.args = node.args[:maximum_positional]
                        self.changed = True
                        self.arity_repairs.add(node.func.attr)
                return node

        removed_private_methods: list[str] = []
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            referenced_private_methods = {
                node.attr
                for node in ast.walk(class_node)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"self", "cls"}
                and node.attr.startswith("_")
            }
            approved_methods = approved_class_surfaces.get(
                class_node.name,
                set(),
            )
            retained_body: list[ast.stmt] = []
            for statement in class_node.body:
                if (
                    isinstance(
                        statement,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and statement.name.startswith("_")
                    and not statement.name.startswith("__")
                    and statement.name not in referenced_private_methods
                    and statement.name not in approved_methods
                    and not statement.decorator_list
                ):
                    removed_private_methods.append(
                        f"{class_node.name}.{statement.name}"
                    )
                    continue
                retained_body.append(statement)
            class_node.body = retained_body

        syntax_repair = ContractSyntaxRepair()
        if removed_private_methods:
            syntax_repair.changed = True
            fixes.append(
                f"{path}: removed unapproved unreachable private callable(s): "
                + ", ".join(sorted(removed_private_methods))
                + "."
            )
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            calls_by_private_method: dict[str, list[tuple[Any, ast.Call]]] = {}
            for caller in methods.values():
                for call in ast.walk(caller):
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                        and call.func.attr.startswith("_")
                        and call.func.attr in methods
                    ):
                        calls_by_private_method.setdefault(
                            call.func.attr,
                            [],
                        ).append((caller, call))
            for method_name, call_sites in calls_by_private_method.items():
                callee = methods[method_name]
                callee_bound_names = {
                    argument.arg
                    for argument in (
                        *callee.args.posonlyargs,
                        *callee.args.args,
                        *callee.args.kwonlyargs,
                    )
                }
                callee_bound_names.update(
                    node.id
                    for node in ast.walk(callee)
                    if isinstance(node, ast.Name)
                    and isinstance(node.ctx, (ast.Store, ast.Param))
                )
                callee_free_names = {
                    node.id
                    for node in ast.walk(callee)
                    if isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Load)
                    and node.id not in callee_bound_names
                    and node.id not in dir(builtins)
                }
                stored_self_attributes = {
                    node.attr
                    for node in ast.walk(callee)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and isinstance(node.ctx, ast.Store)
                }
                callee_free_names.update(
                    node.attr
                    for node in ast.walk(callee)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and isinstance(node.ctx, ast.Load)
                    and node.attr not in stored_self_attributes
                )
                for free_name in sorted(callee_free_names):
                    if not call_sites or not all(
                        free_name
                        in {
                            argument.arg
                            for argument in (
                                *caller.args.posonlyargs,
                                *caller.args.args,
                                *caller.args.kwonlyargs,
                            )
                        }
                        for caller, _call in call_sites
                    ):
                        continue
                    source_argument = next(
                        argument
                        for argument in (
                            *call_sites[0][0].args.posonlyargs,
                            *call_sites[0][0].args.args,
                            *call_sites[0][0].args.kwonlyargs,
                        )
                        if argument.arg == free_name
                    )
                    callee.args.args.append(
                        ast.arg(
                            arg=free_name,
                            annotation=source_argument.annotation,
                            type_comment=source_argument.type_comment,
                        )
                    )
                    class LocalizeThreadedParameter(ast.NodeTransformer):
                        def visit_Attribute(
                            self,
                            node: ast.Attribute,
                        ) -> ast.AST:
                            if (
                                isinstance(node.value, ast.Name)
                                and node.value.id == "self"
                                and node.attr == free_name
                            ):
                                return ast.copy_location(
                                    ast.Name(
                                        id=free_name,
                                        ctx=node.ctx,
                                    ),
                                    node,
                                )
                            return self.generic_visit(node)

                    LocalizeThreadedParameter().visit(callee)
                    for _caller, call in call_sites:
                        call.args.append(
                            ast.copy_location(
                                ast.Name(id=free_name, ctx=ast.Load()),
                                call,
                            )
                        )
                    syntax_repair.changed = True
        tree = syntax_repair.visit(tree)
        existing_imports = {
            (node.module, alias.name)
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }
        missing_imports = sorted(
            verified_dependency_imports - existing_imports
        )
        if missing_imports:
            insertion_index = int(
                bool(
                    tree.body
                    and isinstance(tree.body[0], ast.Expr)
                    and isinstance(tree.body[0].value, ast.Constant)
                    and isinstance(tree.body[0].value.value, str)
                )
            )
            for module_name, binding_name in reversed(missing_imports):
                tree.body.insert(
                    insertion_index,
                    ast.ImportFrom(
                        module=module_name,
                        names=[ast.alias(name=binding_name)],
                        level=0,
                    ),
                )
            syntax_repair.changed = True
        if syntax_repair.changed:
            ast.fix_missing_locations(tree)
            source = ast.unparse(tree).rstrip() + "\n"
            updated[index] = (path_text, original, source)
            fixes.append(
                f"{path}: normalized verified dependency imports and property "
                "access syntax."
            )
            if syntax_repair.arity_repairs:
                fixes.append(
                    f"{path}: removed excess positional arguments from verified "
                    "bound call(s): "
                    + ", ".join(sorted(syntax_repair.arity_repairs))
                    + "."
                )
        requested_guarantees = requirement_text.casefold()
        unsupported_claim_repairs: list[tuple[int, int, str]] = []
        source_lines = source.splitlines(keepends=True)
        line_offsets: list[int] = []
        offset = 0
        for line in source_lines:
            line_offsets.append(offset)
            offset += len(line)
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            if not (
                class_node.body
                and isinstance(class_node.body[0], ast.Expr)
                and isinstance(class_node.body[0].value, ast.Constant)
                and isinstance(class_node.body[0].value.value, str)
            ):
                continue
            doc_expr = class_node.body[0]
            doc_segment = ast.get_source_segment(source, doc_expr) or ""
            repaired_segment = doc_segment
            if not re.search(
                r"\bthread[- ]safe\b",
                requested_guarantees,
            ):
                repaired_segment = re.sub(
                    r"\bthread[- ]safe\s+",
                    "",
                    repaired_segment,
                    flags=re.IGNORECASE,
                )
            if repaired_segment != doc_segment:
                unsupported_claim_repairs.append((
                    line_offsets[doc_expr.lineno - 1] + doc_expr.col_offset,
                    line_offsets[doc_expr.end_lineno - 1]
                    + int(doc_expr.end_col_offset or 0),
                    repaired_segment,
                ))
        if unsupported_claim_repairs:
            for start, end, replacement in sorted(
                unsupported_claim_repairs,
                reverse=True,
            ):
                source = source[:start] + replacement + source[end:]
            tree = ast.parse(source, filename=path)
            updated[index] = (path_text, original, source)
            fixes.append(
                f"{path}: removed unsupported documentation guarantees."
            )
        type_variables = {
            target.id
            for statement in tree.body
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            for target in (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            if isinstance(target, ast.Name)
            and isinstance(getattr(statement, "value", None), ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "TypeVar"
        }
        generic_header_repairs: list[tuple[int, int, str]] = []
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            used_type_variables = sorted({
                node.id
                for node in ast.walk(class_node)
                if isinstance(node, ast.Name) and node.id in type_variables
            })
            has_generic_base = any(
                isinstance(base, ast.Subscript)
                and isinstance(base.value, ast.Name)
                and base.value.id == "Generic"
                for base in class_node.bases
            )
            if not used_type_variables or has_generic_base:
                continue
            header_line = source_lines[class_node.lineno - 1]
            header_match = re.match(
                rf"(?P<indent>\s*)class\s+{re.escape(class_node.name)}"
                r"(?P<bases>\([^:\n]*\))?\s*:",
                header_line,
            )
            if not header_match:
                continue
            existing_bases = str(header_match.group("bases") or "")
            generic_base = f"Generic[{', '.join(used_type_variables)}]"
            bases = (
                existing_bases[:-1] + f", {generic_base})"
                if existing_bases
                else f"({generic_base})"
            )
            replacement = (
                f"{header_match.group('indent')}class {class_node.name}"
                f"{bases}:"
            )
            start = line_offsets[class_node.lineno - 1]
            generic_header_repairs.append((
                start,
                start + header_match.end(),
                replacement,
            ))
        if generic_header_repairs:
            for start, end, replacement in sorted(
                generic_header_repairs,
                reverse=True,
            ):
                source = source[:start] + replacement + source[end:]
            tree = ast.parse(source, filename=path)
            updated[index] = (path_text, original, source)
            fixes.append(
                f"{path}: declared Generic ownership for used type variables."
            )
        dead_assignment_ranges: list[tuple[int, int, str]] = []
        source_lines = source.splitlines(keepends=True)
        line_offsets: list[int] = []
        offset = 0
        for line in source_lines:
            line_offsets.append(offset)
            offset += len(line)
        for function in [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            class RepairUsageVisitor(ast.NodeVisitor):
                def __init__(self, root: ast.AST) -> None:
                    self.root = root
                    self.loads: set[str] = set()
                    self.assignments: list[ast.AST] = []

                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    if node is self.root:
                        self.generic_visit(node)

                def visit_AsyncFunctionDef(
                    self,
                    node: ast.AsyncFunctionDef,
                ) -> None:
                    if node is self.root:
                        self.generic_visit(node)

                def visit_Name(self, node: ast.Name) -> None:
                    if isinstance(node.ctx, ast.Load):
                        self.loads.add(node.id)

                def visit_Assign(self, node: ast.Assign) -> None:
                    if (
                        len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                    ):
                        self.assignments.append(node)
                    self.generic_visit(node)

                def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                    if isinstance(node.target, ast.Name) and node.value is not None:
                        self.assignments.append(node)
                    self.generic_visit(node)

            usage = RepairUsageVisitor(function)
            usage.visit(function)
            for assignment in usage.assignments:
                target_name = (
                    assignment.targets[0].id
                    if isinstance(assignment, ast.Assign)
                    else assignment.target.id
                )
                value = assignment.value
                has_side_effect_boundary = any(
                    isinstance(
                        child,
                        (ast.Call, ast.Await, ast.Yield, ast.YieldFrom),
                    )
                    for child in ast.walk(value)
                )
                if (
                    target_name in usage.loads
                    or target_name.startswith("_")
                    or has_side_effect_boundary
                ):
                    continue
                end_line = int(assignment.end_lineno or assignment.lineno)
                start = line_offsets[assignment.lineno - 1]
                end = (
                    line_offsets[end_line]
                    if end_line < len(line_offsets)
                    else len(source)
                )
                dead_assignment_ranges.append((start, end, target_name))
        if dead_assignment_ranges:
            for start, end, _name in sorted(
                dead_assignment_ranges,
                reverse=True,
            ):
                source = source[:start] + source[end:]
            tree = ast.parse(source, filename=path)
            updated[index] = (path_text, original, source)
            fixes.append(
                f"{path}: removed side-effect-free unused local assignments: "
                + ", ".join(
                    name for _start, _end, name in dead_assignment_ranges
                )
                + "."
            )
        typing_exports = set(getattr(importlib.import_module("typing"), "__all__", ()))
        loaded_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        has_typevar_import = any(
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module == "typing"
            and any(alias.name == "TypeVar" for alias in node.names)
            for node in tree.body
        )
        typevar_import_repairs: list[tuple[int, int, str]] = []
        source_lines = source.splitlines(keepends=True)
        line_offsets: list[int] = []
        offset = 0
        for line in source_lines:
            line_offsets.append(offset)
            offset += len(line)
        for import_node in [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module == "typing"
        ]:
            inferred_typevars = [
                alias
                for alias in import_node.names
                if alias.name not in typing_exports
                and re.fullmatch(r"[A-Z][A-Za-z0-9_]*", alias.asname or alias.name)
                and (alias.asname or alias.name) in loaded_names
            ]
            if not inferred_typevars:
                continue
            retained_aliases = [
                alias
                for alias in import_node.names
                if alias not in inferred_typevars
            ]
            if not has_typevar_import and not any(
                alias.name == "TypeVar" for alias in retained_aliases
            ):
                retained_aliases.append(ast.alias(name="TypeVar"))
                has_typevar_import = True
            repaired_import = ast.ImportFrom(
                module="typing",
                names=retained_aliases,
                level=0,
            )
            replacement_lines = [ast.unparse(repaired_import)]
            replacement_lines.extend(
                f'{alias.asname or alias.name} = TypeVar('
                f'"{alias.asname or alias.name}")'
                for alias in inferred_typevars
            )
            typevar_import_repairs.append((
                line_offsets[import_node.lineno - 1] + import_node.col_offset,
                line_offsets[import_node.end_lineno - 1]
                + int(import_node.end_col_offset or 0),
                "\n".join(replacement_lines),
            ))
        if typevar_import_repairs:
            for start, end, replacement in sorted(
                typevar_import_repairs,
                reverse=True,
            ):
                source = source[:start] + replacement + source[end:]
            tree = ast.parse(source, filename=path)
            updated[index] = (path_text, original, source)
            fixes.append(
                f"{path}: replaced non-public typing aliases with public "
                "TypeVar declarations."
            )
        approved_mechanics = " ".join(
            str(step)
            for chunk in chunks
            for item in chunk.get("implementation_mechanics") or []
            if isinstance(item, Mapping)
            for step in item.get("steps") or []
        ).casefold()
        if "expire" in approved_mechanics or "ttl" in approved_mechanics:
            expiry_replacements: list[tuple[int, int, str]] = []
            source_lines = source.splitlines(keepends=True)
            line_offsets: list[int] = []
            offset = 0
            for line in source_lines:
                line_offsets.append(offset)
                offset += len(line)
            for class_node in [
                node for node in tree.body if isinstance(node, ast.ClassDef)
            ]:
                class_methods = _method_map(class_node)
                removal_methods = [
                    method
                    for method_name, method in class_methods.items()
                    if any(
                        marker in method_name.casefold()
                        for marker in ("remove", "delete", "discard", "evict")
                    )
                    and len(method.args.args) >= 2
                ]
                retrieval_method = class_methods.get("get")
                if retrieval_method is None or len(removal_methods) != 1:
                    continue
                key_arguments = [
                    argument.arg
                    for argument in retrieval_method.args.args
                    if argument.arg not in {"self", "cls"}
                ]
                if not key_arguments:
                    continue
                removal_name = removal_methods[0].name
                key_name = key_arguments[0]
                declared_methods = set(class_methods)
                for conditional in [
                    node
                    for node in ast.walk(retrieval_method)
                    if isinstance(node, ast.If) and node.orelse
                ]:
                    undeclared_cleanup_statements = [
                        statement
                        for statement in conditional.orelse
                        if isinstance(statement, ast.Expr)
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Attribute)
                        and isinstance(statement.value.func.value, ast.Name)
                        and statement.value.func.value.id == "self"
                        and statement.value.func.attr not in declared_methods
                        and any(
                            marker in statement.value.func.attr.casefold()
                            for marker in (
                                "cleanup",
                                "purge",
                                "expire",
                                "evict",
                                "remove",
                            )
                        )
                    ]
                    if not undeclared_cleanup_statements:
                        continue
                    for statement in undeclared_cleanup_statements:
                        expiry_replacements.append((
                            line_offsets[statement.lineno - 1]
                            + statement.col_offset,
                            line_offsets[statement.end_lineno - 1]
                            + int(statement.end_col_offset or 0),
                            f"self.{removal_name}({key_name})",
                        ))
                    for statement in conditional.orelse:
                        if isinstance(statement, ast.Return):
                            expiry_replacements.append((
                                line_offsets[statement.lineno - 1]
                                + statement.col_offset,
                                line_offsets[statement.end_lineno - 1]
                                + int(statement.end_col_offset or 0),
                                "return None",
                            ))
            if expiry_replacements:
                for start, end, replacement in sorted(
                    expiry_replacements,
                    reverse=True,
                ):
                    source = source[:start] + replacement + source[end:]
                tree = ast.parse(source, filename=path)
                updated[index] = (path_text, original, source)
                fixes.append(
                    f"{path}: replaced an undeclared expiry helper with the "
                    "approved declared removal boundary."
                )
        if "mutable fake injected clock/time source" in approved_mechanics:
            entry_names: set[str] = set()
            for statement in tree.body:
                if not (
                    isinstance(statement, ast.If)
                    and "__name__" in ast.unparse(statement.test)
                    and "__main__" in ast.unparse(statement.test)
                ):
                    continue
                entry_names.update(
                    node.func.id
                    for node in ast.walk(statement)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                )
            entry_functions = [
                statement
                for statement in tree.body
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                and statement.name in entry_names
            ]
            host_clock_calls = [
                node
                for function in entry_functions
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "time"
                and node.func.attr in {"time", "monotonic"}
                and node.end_lineno is not None
                and node.end_col_offset is not None
            ]
            if host_clock_calls:
                source_lines = source.splitlines(keepends=True)
                line_offsets: list[int] = []
                offset = 0
                for line in source_lines:
                    line_offsets.append(offset)
                    offset += len(line)
                replacements = [
                    (
                        line_offsets[node.lineno - 1] + node.col_offset,
                        line_offsets[node.end_lineno - 1] + node.end_col_offset,
                    )
                    for node in host_clock_calls
                ]
                for start, end in sorted(replacements, reverse=True):
                    source = source[:start] + "0.0" + source[end:]
                tree = ast.parse(source, filename=path)
                updated[index] = (path_text, original, source)
                fixes.append(
                    f"{path}: seeded the approved injected fake-time entry point "
                    "without reading a host clock."
                )
        if Path(path).name.startswith("test_"):
            test_changed = False

            class PublicUiTestTransformer(ast.NodeTransformer):
                def visit_Call(self, node: ast.Call) -> ast.AST:
                    nonlocal test_changed
                    self.generic_visit(node)
                    if (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr in unique_slot_buttons
                    ):
                        test_changed = True
                        button = unique_slot_buttons[node.func.attr]
                        return ast.copy_location(
                            ast.Call(
                                func=ast.Attribute(
                                    value=ast.Attribute(
                                        value=node.func.value,
                                        attr=button,
                                        ctx=ast.Load(),
                                    ),
                                    attr="click",
                                    ctx=ast.Load(),
                                ),
                                args=[],
                                keywords=[],
                            ),
                            node,
                        )
                    return node

            tree = PublicUiTestTransformer().visit(tree)  # type: ignore[assignment]
            for class_node in [
                item for item in tree.body if isinstance(item, ast.ClassDef)
            ]:
                for method_node in [
                    item
                    for item in class_node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]:
                    instance_types = {
                        target.id: statement.value.func.id
                        for statement in method_node.body
                        if isinstance(statement, ast.Assign)
                        and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Name)
                        and isinstance(statement.value, ast.Call)
                        and isinstance(statement.value.func, ast.Name)
                        and statement.value.func.id in approved_class_surfaces
                        for target in statement.targets
                    }
                    retained_statements: list[ast.stmt] = []
                    for statement in method_node.body:
                        direct_call = (
                            statement.value
                            if isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Call)
                            else None
                        )
                        is_unrequested_exception_message_assertion = bool(
                            direct_call is not None
                            and isinstance(direct_call.func, ast.Attribute)
                            and direct_call.func.attr
                            in {"assertEqual", "assertIn", "assertRegex"}
                            and any(
                                isinstance(attribute, ast.Attribute)
                                and attribute.attr == "exception"
                                for attribute in ast.walk(statement)
                            )
                            and not exception_message_contract_explicit
                        )
                        is_unused_unapproved_instance_call = bool(
                            direct_call is not None
                            and isinstance(direct_call.func, ast.Attribute)
                            and isinstance(direct_call.func.value, ast.Name)
                            and direct_call.func.value.id in instance_types
                            and direct_call.func.attr
                            not in approved_class_surfaces[
                                instance_types[direct_call.func.value.id]
                            ]
                        )
                        if is_unrequested_exception_message_assertion:
                            test_changed = True
                            continue
                        if is_unused_unapproved_instance_call:
                            test_changed = True
                            continue
                        retained_statements.append(statement)
                    method_node.body = retained_statements
                    loaded_names = {
                        child.id
                        for child in ast.walk(method_node)
                        if isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Load)
                    }
                    for with_node in [
                        child
                        for child in ast.walk(method_node)
                        if isinstance(child, ast.With)
                    ]:
                        for item in with_node.items:
                            if (
                                isinstance(item.optional_vars, ast.Name)
                                and item.optional_vars.id not in loaded_names
                            ):
                                item.optional_vars = None
                                test_changed = True
            if test_changed:
                ast.fix_missing_locations(tree)
                repaired_source = ast.unparse(tree).rstrip() + "\n"
                compile(repaired_source, path, "exec")
                updated[index] = (path_text, original, repaired_source)
                fixes.append(
                    f"{Path(path).name}: enforced approved public test contract"
                )
            continue
        if not chunks:
            continue
        definitions = _definition_nodes(tree)
        changed = False
        needs_dataclass_import = False
        needs_typing_imports: set[str] = set()
        needs_time_import = False
        needs_hashable_import = False
        needs_rlock_import = False
        entrypoint_requested = any(
            bool(
                (chunk.get("declaration_contract") or {}).get(
                    "module_entry_point_required"
                )
            )
            or any(
                re.search(
                    r"\bif\s+__name__\b|\bruns?\s+standalone\b"
                    r"|\bstandalone\b[^.!?\n]{0,60}\bentry\s+point\b"
                    r"|\brunnable\s+(?:main\s+)?example\b|\b__main__\b",
                    str(requirement.get("text") or ""),
                    flags=re.IGNORECASE,
                )
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, Mapping)
            )
            for chunk in chunks
        )
        if not entrypoint_requested:
            retained_body = [
                node
                for node in tree.body
                if not (
                    isinstance(node, ast.If)
                    and "__name__" in ast.unparse(node.test)
                    and "__main__" in ast.unparse(node.test)
                )
            ]
            if len(retained_body) != len(tree.body):
                tree.body = retained_body
                changed = True
                fixes.append(
                    f"{Path(path).name}: removed unrequested standalone entry point"
                )
        if not Path(path).name.startswith("test_"):
            retained_body = [
                node
                for node in tree.body
                if not (
                    isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                    )
                    and node.name.startswith("test_")
                )
            ]
            if len(retained_body) != len(tree.body):
                tree.body = retained_body
                changed = True
                fixes.append(
                    f"{Path(path).name}: removed misplaced test declaration"
                )
        for chunk in chunks:
            owner = str(chunk.get("owner") or "")
            class_node = definitions.get(owner)
            if not isinstance(class_node, ast.ClassDef):
                continue
            contract = chunk.get("declaration_contract") or {}
            required_base = str(contract.get("base") or "").strip()
            required_base_name = required_base.rsplit(".", 1)[-1]
            actual_base_names = {
                ast.unparse(base).rsplit(".", 1)[-1]
                for base in class_node.bases
            }
            authoritative_base_name = next(
                (
                    str(item.get("name") or "")
                    for item in chunk.get("evidence") or []
                    if isinstance(item, Mapping)
                    and str(item.get("name") or "").rsplit(".", 1)[-1]
                    == required_base_name
                    and str(item.get("strength") or "")
                    in {
                        "authoritative_signature",
                        "authoritative_source",
                        "verified_internal_symbol",
                    }
                ),
                "",
            )
            if required_base_name and required_base_name not in actual_base_names:
                conflicting_qt_bases = {
                    "QDialog",
                    "QDockWidget",
                    "QMainWindow",
                    "QWidget",
                }
                class_node.bases = [
                    ast.Name(id=required_base_name, ctx=ast.Load()),
                    *[
                        base
                        for base in class_node.bases
                        if ast.unparse(base).rsplit(".", 1)[-1]
                        not in conflicting_qt_bases
                    ],
                ]
                changed = True
                fixes.append(
                    f"{Path(path).name}:{owner}: enforced approved base "
                    f"{required_base_name}"
                )
            removed_base_names = {
                base_name
                for base_name in actual_base_names
                if required_base_name and base_name != required_base_name
            }
            if removed_base_names:
                class_node.bases = [
                    ast.Name(id=required_base_name, ctx=ast.Load())
                ]
                for import_node in [
                    node for node in tree.body if isinstance(node, ast.ImportFrom)
                ]:
                    import_node.names = [
                        alias
                        for alias in import_node.names
                        if (alias.asname or alias.name) not in removed_base_names
                    ]
                tree.body = [
                    node
                    for node in tree.body
                    if not (
                        isinstance(node, ast.ImportFrom)
                        and not node.names
                    )
                ]
                changed = True
                fixes.append(
                    f"{Path(path).name}:{owner}: removed unapproved base "
                    + ", ".join(sorted(removed_base_names))
                )
            base_module, separator, imported_base = (
                authoritative_base_name.rpartition(".")
            )
            if separator and base_module and imported_base:
                base_import = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.ImportFrom)
                        and node.module == base_module
                        and int(node.level or 0) == 0
                    ),
                    None,
                )
                imported_names = (
                    {
                        alias.asname or alias.name
                        for alias in base_import.names
                    }
                    if base_import is not None
                    else set()
                )
                if imported_base not in imported_names:
                    if base_import is None:
                        tree.body.insert(
                            0,
                            ast.ImportFrom(
                                module=base_module,
                                names=[ast.alias(name=imported_base)],
                                level=0,
                            ),
                        )
                    else:
                        base_import.names.append(ast.alias(name=imported_base))
                    changed = True
                    fixes.append(
                        f"{Path(path).name}:{owner}: imported approved base "
                        f"{authoritative_base_name}"
                    )
            decorators = {
                ast.unparse(
                    decorator.func
                    if isinstance(decorator, ast.Call)
                    else decorator
                ).rsplit(".", 1)[-1]
                for decorator in class_node.decorator_list
            }
            requires_dataclass = "dataclass" in {
                str(value).rsplit(".", 1)[-1]
                for value in contract.get("decorators") or []
            }
            requires_frozen = bool(contract.get("immutable"))
            dataclass_decorator = next(
                (
                    decorator
                    for decorator in class_node.decorator_list
                    if ast.unparse(
                        decorator.func
                        if isinstance(decorator, ast.Call)
                        else decorator
                    ).rsplit(".", 1)[-1]
                    == "dataclass"
                ),
                None,
            )
            if requires_dataclass and dataclass_decorator is None:
                class_node.decorator_list.insert(
                    0,
                    ast.Call(
                        func=ast.Name(id="dataclass", ctx=ast.Load()),
                        args=[],
                        keywords=(
                            [
                                ast.keyword(
                                    arg="frozen",
                                    value=ast.Constant(value=True),
                                )
                            ]
                            if requires_frozen
                            else []
                        ),
                    )
                    if requires_frozen
                    else ast.Name(id="dataclass", ctx=ast.Load()),
                )
                needs_dataclass_import = True
                changed = True
                fixes.append(
                    f"{Path(path).name}:{owner}: added "
                    + (
                        "@dataclass(frozen=True)"
                        if requires_frozen
                        else "@dataclass"
                    )
                )
            elif (
                requires_frozen
                and dataclass_decorator is not None
                and not (
                    isinstance(dataclass_decorator, ast.Call)
                    and any(
                        keyword.arg == "frozen"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                        for keyword in dataclass_decorator.keywords
                    )
                )
            ):
                replacement = ast.Call(
                    func=(
                        dataclass_decorator.func
                        if isinstance(dataclass_decorator, ast.Call)
                        else dataclass_decorator
                    ),
                    args=(
                        list(dataclass_decorator.args)
                        if isinstance(dataclass_decorator, ast.Call)
                        else []
                    ),
                    keywords=[
                        *(
                            [
                                keyword
                                for keyword in dataclass_decorator.keywords
                                if keyword.arg != "frozen"
                            ]
                            if isinstance(dataclass_decorator, ast.Call)
                            else []
                        ),
                        ast.keyword(
                            arg="frozen",
                            value=ast.Constant(value=True),
                        ),
                    ],
                )
                class_node.decorator_list[
                    class_node.decorator_list.index(dataclass_decorator)
                ] = replacement
                changed = True
                fixes.append(
                    f"{Path(path).name}:{owner}: enforced "
                    "@dataclass(frozen=True)"
                )

        typing_annotation_names = {
            "Annotated",
            "Any",
            "AsyncIterable",
            "AsyncIterator",
            "Awaitable",
            "Callable",
            "ClassVar",
            "Collection",
            "Final",
            "Generator",
            "Generic",
            "Hashable",
            "Iterable",
            "Iterator",
            "Literal",
            "Mapping",
            "MutableMapping",
            "MutableSequence",
            "NamedTuple",
            "Never",
            "NoReturn",
            "Optional",
            "Protocol",
            "Sequence",
            "TypeAlias",
            "TypeVar",
            "Union",
        }
        imported_or_defined_names = {
            node.name
            for node in tree.body
            if isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            )
        }
        imported_or_defined_names.update(
            alias.asname or alias.name.split(".", 1)[0]
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imported_or_defined_names.update(
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        )
        annotation_nodes: list[ast.expr] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                annotation_nodes.append(node.annotation)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.returns is not None:
                    annotation_nodes.append(node.returns)
                annotation_nodes.extend(
                    argument.annotation
                    for argument in [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                    if argument.annotation is not None
                )
                if node.args.vararg and node.args.vararg.annotation is not None:
                    annotation_nodes.append(node.args.vararg.annotation)
                if node.args.kwarg and node.args.kwarg.annotation is not None:
                    annotation_nodes.append(node.args.kwarg.annotation)
        annotation_names = {
            annotation_name.id
            for annotation in annotation_nodes
            for annotation_name in ast.walk(annotation)
            if isinstance(annotation_name, ast.Name)
        }
        needs_typing_imports = (
            annotation_names
            & typing_annotation_names
            - imported_or_defined_names
        )
        if needs_typing_imports:
            changed = True
            fixes.append(
                f"{Path(path).name}: imported standard typing annotations "
                + ", ".join(sorted(needs_typing_imports))
            )
        if not changed:
            continue
        if needs_dataclass_import:
            dataclass_import = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.module == "dataclasses"
                ),
                None,
            )
            if dataclass_import is None:
                tree.body.insert(
                    0,
                    ast.ImportFrom(
                        module="dataclasses",
                        names=[ast.alias(name="dataclass")],
                        level=0,
                    ),
                )
            elif "dataclass" not in {
                alias.name for alias in dataclass_import.names
            }:
                dataclass_import.names.append(ast.alias(name="dataclass"))
        if needs_typing_imports:
            typing_import = next(
                (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.module == "typing"
                    and node.level == 0
                ),
                None,
            )
            if typing_import is None:
                tree.body.insert(
                    0,
                    ast.ImportFrom(
                        module="typing",
                        names=[
                            ast.alias(name=name)
                            for name in sorted(needs_typing_imports)
                        ],
                        level=0,
                    ),
                )
            else:
                existing_typing_names = {
                    alias.name for alias in typing_import.names
                }
                typing_import.names.extend(
                    ast.alias(name=name)
                    for name in sorted(needs_typing_imports)
                    if name not in existing_typing_names
                )
        if needs_time_import and not any(
            isinstance(node, ast.Import)
            and any(alias.name == "time" for alias in node.names)
            for node in tree.body
        ):
            tree.body.insert(0, ast.Import(names=[ast.alias(name="time")]))
        if needs_hashable_import and not any(
            isinstance(node, ast.ImportFrom)
            and node.module in {"collections.abc", "typing"}
            and any(alias.name == "Hashable" for alias in node.names)
            for node in tree.body
        ):
            tree.body.insert(
                0,
                ast.ImportFrom(
                    module="collections.abc",
                    names=[ast.alias(name="Hashable")],
                    level=0,
                ),
            )
        if needs_rlock_import and not any(
            isinstance(node, ast.ImportFrom)
            and node.module == "threading"
            and any(alias.name == "RLock" for alias in node.names)
            for node in tree.body
        ):
            tree.body.insert(
                0,
                ast.ImportFrom(
                    module="threading",
                    names=[ast.alias(name="RLock")],
                    level=0,
                ),
            )
        ast.fix_missing_locations(tree)
        repaired_source = ast.unparse(tree).rstrip() + "\n"
        compile(repaired_source, path, "exec")
        updated[index] = (path_text, original, repaired_source)
    return updated, fixes
