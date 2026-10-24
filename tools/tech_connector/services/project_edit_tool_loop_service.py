"""Bounded, read-only context gathering before a focused project-edit preview.

This is deliberately a narrow acceleration lane.  It never writes project files,
never bypasses plan approval, and leaves the established workflow in charge when
the requested edit or its behavioral proof cannot be validated here.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from tech_connector.services.llm_router_service import generate_llm_response
from tech_connector.services.project_edit_agent_service import (
    preview_project_edit_agent_response,
)
from tech_connector.services.project_edit_agent_part_02 import (
    _format_generated_long_statements,
)
from tech_connector.services.project_edit_workflow_part_01 import ProjectEditWorkflowResult


_MAX_SOURCE_CHARS = 18_000
_MAX_CONTEXT_CHARS = 5_000
_MAX_MODEL_CALLS = 3


def _diagnose(workflow: Any, reason: str) -> None:
    """Expose bounded failure categories to opt-in benchmarks, never model text."""

    diagnostics = getattr(workflow, "focused_tool_loop_diagnostics", None)
    if isinstance(diagnostics, list):
        diagnostics.append(reason[:1000])


def _inside(root: Path, raw_path: str) -> Path | None:
    """Resolve a model-supplied path without allowing workspace escape."""

    if not raw_path or "\x00" in raw_path:
        return None
    path = Path(raw_path)
    try:
        resolved = (path if path.is_absolute() else root / path).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _context_action(root: Path, action: dict[str, Any]) -> str | None:
    """Execute only bounded, read-only repository queries requested by the model."""

    kind = str(action.get("action") or "")
    if kind == "read_file":
        target = _inside(root, str(action.get("path") or ""))
        if target is None or not target.is_file() or target.suffix != ".py":
            return "read_file rejected: path is unavailable or outside this Python project."
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return "read_file rejected: source cannot be read as UTF-8."
        try:
            requested_line = int(action.get("start_line") or 1)
        except (TypeError, ValueError):
            return "read_file rejected: start_line must be an integer."
        start = max(1, min(requested_line, len(lines) or 1))
        end = min(len(lines), start + 79)
        excerpt = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
        return f"{target.relative_to(root).as_posix()} lines {start}-{end}:\n{excerpt}"[:_MAX_CONTEXT_CHARS]
    if kind == "search_text":
        query = str(action.get("query") or "").strip()
        if not 2 <= len(query) <= 120 or any(char in query for char in "\r\n\x00"):
            return "search_text rejected: supply a short literal query."
        try:
            completed = subprocess.run(
                ["rg", "-n", "-F", "-m", "3", "--glob", "*.py", "--glob", "!**/benchmarks/**", "--", query, str(root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "search_text unavailable or timed out."
        return (completed.stdout or "No literal match found.")[:_MAX_CONTEXT_CHARS]
    return None


def _normalize_changes(
    root: Path,
    allowed: set[Path],
    raw_changes: list[Any],
    rejection_reasons: list[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Repair only unambiguous schema aliases; semantic edits still need proof."""

    normalized: list[dict[str, Any]] = []
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            if rejection_reasons is not None:
                rejection_reasons.append("non_object_change")
            return None
        change = dict(raw_change)
        raw_path = str(change.get("path") or "")
        if not raw_path and rejection_reasons is not None:
            rejection_reasons.append("missing_path")
        target = _inside(root, raw_path)
        if target is None or target not in allowed:
            if raw_path and rejection_reasons is not None:
                rejection_reasons.append("out_of_scope_path")
            return None
        if not isinstance(change.get("new_content"), str) and isinstance(
            change.get("content"), str
        ):
            change["new_content"] = change["content"]
        content = change.get("new_content")
        if not isinstance(content, str):
            if rejection_reasons is not None:
                rejection_reasons.append("missing_source_content")
            return None
        symbol = str(change.get("target_symbol") or "").strip()
        if change.get("action") == "replace_symbol" and not symbol and target.is_file():
            # A single replacement declaration matching a top-level owner is
            # unambiguous; do not guess a symbol for new or nested callables.
            try:
                replacement = ast.parse(content).body
                existing = ast.parse(target.read_text(encoding="utf-8")).body
            except (OSError, UnicodeError, SyntaxError, ValueError):
                replacement = []
                existing = []
            declaration_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            if (
                len(replacement) == 1
                and isinstance(replacement[0], declaration_types)
                and any(
                    isinstance(node, declaration_types)
                    and node.name == replacement[0].name
                    and type(node) is type(replacement[0])
                    for node in existing
                )
            ):
                symbol = replacement[0].name
                change["target_symbol"] = symbol
        prefixed_symbol = re.fullmatch(
            r"(?:function|def|class)[ _]+([A-Za-z_]\w*)", symbol,
            flags=re.IGNORECASE,
        )
        if prefixed_symbol and target.is_file():
            bare_symbol = prefixed_symbol.group(1)
            try:
                existing = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                existing = ""
            declaration_kind = (
                "class" if symbol.casefold().startswith(("class ", "class_")) else "def"
            )
            exact_declaration = re.search(
                rf"(?m)^\s*(?:def|class)\s+{re.escape(symbol)}\b",
                existing,
            )
            if not exact_declaration and re.search(
                rf"(?m)^\s*{declaration_kind}\s+{re.escape(bare_symbol)}\b",
                existing,
            ):
                symbol = bare_symbol
                change["target_symbol"] = bare_symbol
        if (
            change.get("action") in {None, "", "replace_text"}
            and symbol.isidentifier()
            and target.is_file()
            and re.match(rf"\s*(?:async\s+)?def\s+{re.escape(symbol)}\s*\(|\s*class\s+{re.escape(symbol)}\b", content)
        ):
            change["action"] = "replace_symbol"
        elif not change.get("action") and not target.exists() and target.name.startswith("test_"):
            change["action"] = "create"
        elif (
            change.get("action") == "create_symbol"
            and not target.exists()
            and target.name.startswith("test_")
        ):
            change["action"] = "create"
        normalized.append(change)
    return normalized


def _merge_retry_changes(
    previous: list[dict[str, Any]], current: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Carry omitted approved files through a partial validation repair.

    The caller has already scope-checked both proposals. A new edit to a path
    replaces all older edits to that path; the final combined proposal still
    goes through the normal preview and disposable behavioral validation.
    """

    updated_paths = {str(change["path"]) for change in current}
    return [
        change for change in previous
        if str(change["path"]) not in updated_paths
    ] + current


def _omit_empty_scoped_retry_changes(
    root: Path,
    allowed: set[Path],
    raw_changes: list[Any],
    previous_changes: list[dict[str, Any]],
) -> tuple[list[Any], int]:
    """Treat source-free scoped retry placeholders as omitted edits.

    A partial repair may return only changed files; prior approved-path edits
    are carried forward and the complete candidate is revalidated. Never do
    this for an initial proposal, an entirely empty retry, or an out-of-scope
    placeholder, so schema/scope errors remain visible.
    """

    if not previous_changes:
        return raw_changes, 0
    kept: list[Any] = []
    omitted = 0
    for change in raw_changes:
        if not isinstance(change, dict):
            kept.append(change)
            continue
        content = change.get("new_content")
        if not isinstance(content, str) and isinstance(change.get("content"), str):
            content = change["content"]
        target = _inside(root, str(change.get("path") or ""))
        if content is None and target in allowed:
            omitted += 1
            continue
        kept.append(change)
    if not kept:
        return raw_changes, 0
    return kept, omitted


def _focused_validation_feedback(
    changes: list[dict[str, Any]], errors: list[Any], request_prompt: str = "",
) -> str:
    """Keep actionable validation feedback ahead of bounded prior source."""

    def compact_error(message: str, limit: int) -> str:
        if len(message) <= limit:
            return message
        marker = "\n...[validation detail omitted]...\n"
        head = min(180, max(40, limit // 3))
        tail = limit - head - len(marker)
        return message[:head] + marker + message[-tail:]

    messages = [str(error) for error in errors[:4]]
    guidance = [
        "Repair the proposal. Include action/path/new_content for every returned "
        "change. Omitted previously proposed files are retained and revalidated.",
    ]
    combined = "\n".join(messages).casefold()
    if "'dict' object has no attribute" in combined:
        guidance.append(
            "A generated test fake used a dict where production expects object "
            "attributes. Keep the production attribute-based API; change the test "
            "fake to an object with those attributes (import SimpleNamespace from "
            "types, not unittest.mock)."
        )
    if "'bool' object is not callable" in combined and "select_get" in combined:
        guidance.append(
            "The test fake made select_get a boolean, but production calls "
            "select_get(). Define a select_get method on the fake that returns "
            "the selection boolean; preserve the production call."
        )
    if "unsupported operand type(s) for |" in combined:
        guidance.append(
            "The disposable Python runtime cannot evaluate that union type "
            "annotation. In the generated file, use typing.Union/Optional or "
            "postponed annotations compatible with the runtime; do not change "
            "production behavior to mask a test-annotation error."
        )
    if "fixture variables never consumed" in combined:
        guidance.append(
            "Pass each constructed fixture collection into the edited function "
            "and assert its returned value; unused fixture setup is not proof."
        )
    if "explicitly invalid boolean inputs are not proven rejected" in combined:
        guidance.append(
            "The implementation must explicitly reject bool before numeric "
            "conversion because bool is an int subclass. Test True and False "
            "with assertRaises(ValueError)."
        )
        for change in changes:
            if change.get("action") != "replace_symbol":
                continue
            try:
                parsed = ast.parse(str(change.get("new_content") or ""))
            except SyntaxError:
                continue
            if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.FunctionDef):
                continue
            function = parsed.body[0]
            arguments = [*function.args.posonlyargs, *function.args.args]
            if len(arguments) == 1:
                argument = arguments[0].arg
                guidance.append(
                    f"In {function.name}, add `if isinstance({argument}, bool): "
                    "raise ValueError(...)` before comparisons or conversion. "
                    "Return a changed owner callable; resending the previous "
                    "function cannot pass this check."
                )
                break
    if "undefined names" in combined and re.search(r"\bmath\b", combined):
        guidance.append(
            "The production callable refers to math without importing it. "
            "Add an ensure_import change on the owner path with "
            "target_symbol `math` and new_content `import math`, or put "
            "`import math` inside that callable. "
            "Importing math only in the test file does not define it for production."
        )
    if "undefined names" in combined and re.search(r"\b(?:union|optional)\b", combined):
        guidance.append(
            "The edited owner uses Union or Optional annotations without "
            "defining those names. For one typing name, use an ensure_import "
            "change on the approved owner module with target_symbol `typing` "
            "and new_content `Union` or `Optional`; that creates a from-import. "
            "Alternatively use an annotation that needs no typing "
            "name. A test-file import cannot fix an owner-module NameError."
        )
    if "split text is not stripped after splitting" in combined:
        guidance.append(
            "Calling value.strip().split(':') only trims the outside of the "
            "whole input. Normalize the split segments themselves before any "
            "validation, for example parts = [part.strip() for part in "
            "value.split(':')]. Validate and return those normalized parts. "
            "Test whitespace on both sides of the separator and reject blank "
            "segments after trimming when the task requires nonempty parts."
        )
    if "empty split segment is not rejected" in combined:
        guidance.append(
            "Checking only the number of split parts does not reject an empty "
            "part. After trimming, reject any blank part, for example "
            "if not all(parts): raise ValueError('empty segment'). Test both "
            "':operation' and 'host:' (including whitespace-only parts)."
        )
    if "no module named 'bpy" in combined or "no module named 'maya" in combined:
        guidance.append(
            "The host DCC SDK is unavailable in disposable unit tests. Do not "
            "import host SDK types into the generated test; define a small fake "
            "object with the production function's required attributes instead."
        )
    if "unicodeescape" in combined or "truncated \\uxxxxxxxx" in combined:
        guidance.append(
            "Correct Python string escaping in the generated test, especially "
            "Windows backslash paths; do not change production behavior to mask "
            "a test-source syntax error."
        )
    if "unexpected character after line continuation character" in combined:
        guidance.append(
            "The proposed Python source contains a bare backslash outside a "
            "string. Check the reported line, write a valid Python string "
            "literal, and JSON-encode new_content exactly once. Preserve the "
            "intended path-normalization behavior."
        )
    if "python syntax validation failed" in combined:
        guidance.append(
            "Fix the indicated Python syntax error in the generated file. "
            "Return complete corrected source for that approved path; do not "
            "substitute prose or omit the required test file."
        )
    if "line exceeds 100 characters" in combined:
        guidance.append(
            "Shorten the offending Python source line below 100 characters. "
            "Use short relative test paths and separate assignments; avoid "
            "long escaped Windows path literals in test fixtures."
        )
    if "eof while scanning triple-quoted string literal" in combined:
        guidance.append(
            "The proposed Python function has an unclosed triple-quoted "
            "docstring or string. Return a complete function with balanced "
            "quotes; do not replace executable code with prose."
        )
    if "ran 0 tests" in combined:
        guidance.append(
            "The generated test file did not provide discoverable behavioral "
            "proof. Include a unittest.TestCase with a test_* method that "
            "imports and calls the edited function."
        )
    if "assertionerror" in combined or "assertion failed" in combined:
        guidance.append(
            "A generated test assertion failed. Compare its expected output "
            "with the user's stated rule and the actual output before changing "
            "production code. If the expected value contradicts the request, "
            "correct the test expectation; otherwise repair the implementation. "
            "Return the corrected approved file and rerun the same behavior."
        )
    if "valueerror not raised" in combined and re.search(
        r"\b(?:trim|strip)\b", request_prompt, flags=re.I,
    ):
        guidance.append(
            "The request says to trim input. A generated test must not expect "
            "ValueError merely because an otherwise valid input has surrounding "
            "whitespace. Normalize first, then apply the requested validity "
            "checks. Correct that test expectation if whitespace is its only "
            "reason for rejection; keep tests for genuinely invalid inputs."
        )
    if "behavior-changing work requires a focused test file" in combined:
        guidance.append(
            "The proposal omitted the required test artifact. Keep the owner "
            "edit and add a separate create change for the approved test path; "
            "its complete source must contain a unittest.TestCase with a "
            "test_* method covering the requested behavior."
        )
    if "imported callable members do not exist" in combined:
        guidance.append(
            "An imported callable or class is absent from the approved project "
            "source. Preserve the exact original function/class declaration name "
            "in the owner edit. Do not invent an SDK or project symbol. Import "
            "only the existing owner callable under test, and define any small "
            "input fake locally in the approved test file."
        )
    payload = {
        "instruction": " ".join(guidance),
        "validation_errors": [compact_error(message, 850) for message in messages],
        "rejected_proposal": (
            [
                {
                    key: change[key]
                    for key in ("action", "path", "target_symbol")
                    if key in change
                }
                for change in changes
            ]
            if "explicitly invalid boolean inputs are not proven rejected" in combined
            else changes
        ),
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) <= _MAX_CONTEXT_CHARS:
        return serialized
    # Slicing serialized JSON can leave the repair model with an unterminated
    # source string. Keep the error and approved paths in valid JSON, and mark
    # long source as an excerpt instead of silently presenting it as complete.
    payload["validation_errors"] = [compact_error(message, 500) for message in messages]
    excerpts = [
        {
            **{
                key: change[key]
                for key in ("action", "path", "target_symbol")
                if key in change
            },
            "new_content_excerpt": str(change.get("new_content") or "")[:600],
            "source_truncated": len(str(change.get("new_content") or "")) > 600,
        }
        for change in changes
    ]
    payload["rejected_proposal"] = excerpts
    serialized = json.dumps(payload, ensure_ascii=False)
    while len(serialized) > _MAX_CONTEXT_CHARS and any(
        row["new_content_excerpt"] for row in excerpts
    ):
        for row in excerpts:
            row["new_content_excerpt"] = row["new_content_excerpt"][:
                len(row["new_content_excerpt"]) // 2
            ]
            row["source_truncated"] = True
        serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) > _MAX_CONTEXT_CHARS:
        payload["validation_errors"] = [
            compact_error(message, 200) for message in messages[:2]
        ]
        serialized = json.dumps(payload, ensure_ascii=False)
    while len(serialized) > _MAX_CONTEXT_CHARS and payload["instruction"]:
        payload["instruction"] = payload["instruction"][:
            max(0, len(payload["instruction"]) - (len(serialized) - _MAX_CONTEXT_CHARS) - 16)
        ]
        serialized = json.dumps(payload, ensure_ascii=False)
    while len(serialized) > _MAX_CONTEXT_CHARS and excerpts:
        excerpts.pop()
        serialized = json.dumps(payload, ensure_ascii=False)
    return serialized


def _selection_requirement_gap(prompt: str, changes: list[dict[str, Any]]) -> bool:
    """Catch an omitted selection predicate in explicit DCC selection tasks.

    Docstrings and function names do not prove that the generated implementation
    actually reads selection state. This is a narrow, source-grounded guard for
    the opt-in fast lane; other requests continue through ordinary validation.
    """

    if not re.search(
        r"\b(?:selected\s+(?:objects?|meshes?|nodes?|items?)|current\s+selection)\b",
        prompt,
        flags=re.I,
    ):
        return False
    source = "\n".join(
        str(change.get("new_content") or "")
        for change in changes
        if change.get("action") in {"replace_symbol", "replace_text"}
        and not Path(str(change.get("path") or "")).name.startswith("test_")
    )
    if not source:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False  # Existing syntax validation reports the actionable error.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and "select" in node.attr.casefold()
            and not node.attr.casefold().endswith("_set")
        ):
            return False
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and "select" in node.func.id.casefold():
                return False
            if (
                (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                ) or (
                    isinstance(node.func, ast.Name) and node.func.id == "getattr"
                )
            ) and (
                any(
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and "select" in argument.value.casefold()
                    for argument in node.args
                )
            ):
                return False
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and "select" in node.slice.value.casefold()
        ):
            return False
    return True


def _explicit_sequence_requirement_gaps(
    prompt: str, changes: list[dict[str, Any]], known_source: str = "",
) -> list[str]:
    """Reject narrow, source-grounded omissions in generated functions.

    This is deliberately narrower than a semantic judge: a split without any
    strip cannot satisfy an explicit trim request, and a bare list comprehension
    with no membership test cannot deduplicate while keeping input order.
    Ambiguous implementations continue through ordinary validation.
    """

    need_trim = bool(re.search(r"\b(?:trim|strip)\b", prompt, flags=re.I))
    need_nonempty_parts = bool(re.search(
        r"\breject\b.{0,40}\bempty\b|\bempty\b.{0,40}\breject\b",
        prompt, flags=re.I,
    ))
    need_unique = bool(re.search(
        r"\b(?:once|unique|deduplicat(?:e|ed|ion)|no duplicates)\b",
        prompt, flags=re.I,
    )) and bool(re.search(r"\b(?:order|first.seen)\b", prompt, flags=re.I))
    need_enabled = bool(re.search(r"\benabled\b", prompt, flags=re.I))
    if not (need_trim or need_nonempty_parts or need_unique or need_enabled):
        return []

    gaps: list[str] = []

    def body_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef):
        """Inspect a function's behavior without borrowing nested helpers' returns."""

        pending = list(function.body)
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            yield node
            pending.extend(ast.iter_child_nodes(node))

    for change in changes:
        if change.get("action") not in {"replace_symbol", "replace_text"}:
            continue
        if Path(str(change.get("path") or "")).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(str(change.get("new_content") or ""))
        except SyntaxError:
            continue
        nodes = list(ast.walk(tree))
        if need_enabled and known_source:
            generated_attrs = {
                node.attr for node in nodes if isinstance(node, ast.Attribute)
            }
            try:
                known_attrs = {
                    node.attr for node in ast.walk(ast.parse(known_source))
                    if isinstance(node, ast.Attribute)
                }
            except SyntaxError:
                known_attrs = set()
            if (
                "disabled" in generated_attrs
                and "enabled" not in generated_attrs
                and "disabled" not in known_attrs
            ):
                gaps.append(
                    "The request specifies enabled items, but the implementation "
                    "invents an ungrounded disabled attribute. Use the actual "
                    "enabled contract or gather repository evidence first."
                )
        split_calls = [
            node for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "split"
        ]
        strip_calls = [
            node for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "strip"
        ]
        if need_nonempty_parts and split_calls:
            empty_guard = any(
                isinstance(node, ast.If) and any(
                    isinstance(inner, ast.UnaryOp)
                    and isinstance(inner.op, ast.Not)
                    and (
                        isinstance(inner.operand, ast.Name)
                        or isinstance(inner.operand, ast.Call)
                    )
                    or isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id in {"all", "any"}
                    or isinstance(inner, ast.Compare)
                    and any(isinstance(value, ast.Constant) and value.value == ""
                            for value in (inner.left, *inner.comparators))
                    for inner in ast.walk(node.test)
                )
                for node in nodes
            )
            if not empty_guard:
                gaps.append(
                    "An empty split segment is not rejected. After trimming, "
                    "check every part for blank content and raise ValueError; "
                    "test both leading and trailing empty segments."
                )
        # Stripping only the complete reference before splitting still leaves
        # whitespace around each host/operation segment intact.
        only_whole_input_stripped = bool(split_calls and strip_calls) and all(
            any(
                isinstance(split.func.value, ast.Call)
                and strip is split.func.value
                for split in split_calls
            )
            for strip in strip_calls
        )
        if need_trim and split_calls and (not strip_calls or only_whole_input_stripped):
            gaps.append(
                "The request explicitly requires trimming each segment, but "
                "split text is not stripped after splitting. Strip each relevant "
                "segment and test surrounding whitespace."
            )
        if need_trim:
            for function in tree.body:
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                split_assignments = {
                    target.id: assignment.lineno
                    for assignment in ast.walk(function)
                    if isinstance(assignment, ast.Assign)
                    and isinstance(assignment.value, ast.Call)
                    and isinstance(assignment.value.func, ast.Attribute)
                    and assignment.value.func.attr == "split"
                    for target in assignment.targets
                    if isinstance(target, ast.Name)
                }
                for returned in (node for node in ast.walk(function) if isinstance(node, ast.Return)):
                    returned_parts = (
                        returned.value.elts
                        if isinstance(returned.value, (ast.Tuple, ast.List)) else []
                    )
                    for part in returned_parts:
                        if not (
                            isinstance(part, ast.Subscript)
                            and isinstance(part.value, ast.Name)
                            and part.value.id in split_assignments
                        ):
                            continue
                        split_name = part.value.id
                        # A subsequent assignment may have normalized the
                        # collection; do not guess its semantics here.
                        reassigned = any(
                            isinstance(assignment, ast.Assign)
                            and split_assignments[split_name] < assignment.lineno < returned.lineno
                            and any(
                                isinstance(target, ast.Name) and target.id == split_name
                                or isinstance(target, ast.Subscript)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == split_name
                                for target in assignment.targets
                            )
                            for assignment in ast.walk(function)
                        )
                        if not reassigned:
                            gaps.append(
                                "A returned split segment is not trimmed. Strip "
                                "each segment before validating and returning it; "
                                "test whitespace around both sides of the separator."
                            )
                            break
                    late_stripped = {
                        call.func.value.id
                        for call in ast.walk(returned)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "strip"
                        and isinstance(call.func.value, ast.Name)
                    }
                    for condition in (node for node in ast.walk(function) if isinstance(node, ast.If)):
                        if condition.lineno >= returned.lineno:
                            continue
                        membership_names = {
                            name.id
                            for comparison in ast.walk(condition.test)
                            if isinstance(comparison, ast.Compare)
                            and any(isinstance(op, (ast.In, ast.NotIn)) for op in comparison.ops)
                            for name in ast.walk(comparison.left)
                            if isinstance(name, ast.Name)
                        }
                        empty_names = {
                            node.id for node in ast.walk(condition.test)
                            if isinstance(node, ast.Name) and node is condition.test
                        }
                        empty_names.update(
                            node.operand.id for node in ast.walk(condition.test)
                            if isinstance(node, ast.UnaryOp)
                            and isinstance(node.op, ast.Not)
                            and isinstance(node.operand, ast.Name)
                        )
                        used_before_trim = (membership_names | empty_names) & late_stripped
                        if not used_before_trim:
                            continue
                        normalized_before_check = {
                            target.id
                            for assignment in ast.walk(function)
                            if isinstance(assignment, ast.Assign)
                            and assignment.lineno < condition.lineno
                            and isinstance(assignment.value, ast.Call)
                            and isinstance(assignment.value.func, ast.Attribute)
                            and assignment.value.func.attr == "strip"
                            for target in assignment.targets
                            if isinstance(target, ast.Name)
                        }
                        if used_before_trim - normalized_before_check:
                            gaps.append(
                                "A segment is validated before it is trimmed. "
                                "Normalize each segment before checking allowed values "
                                "or emptiness; test surrounding whitespace."
                            )
                            break
                    else:
                        continue
                    break
        direct_input_lists = []
        if need_unique and any(
            isinstance(node, ast.Return)
            and isinstance(node.value, (ast.Set, ast.SetComp))
            for function in tree.body
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
            for node in body_nodes(function)
        ):
            gaps.append(
                "The request requires first-seen order, but returning a set "
                "discards that order and changes the return contract. Return "
                "an ordered collection and test repeated eligible items."
            )
        if need_unique and known_source:
            try:
                original_tree = ast.parse(known_source)
            except SyntaxError:
                original_tree = None
            if original_tree is not None:
                original_list_functions = {
                    function.name
                    for function in ast.walk(original_tree)
                    if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(
                        isinstance(node, ast.Return)
                        and isinstance(node.value, (ast.List, ast.ListComp))
                        for node in body_nodes(function)
                    )
                }
                if any(
                    isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and function.name in original_list_functions
                    and any(isinstance(node, (ast.Yield, ast.YieldFrom))
                            for node in body_nodes(function))
                    for function in tree.body
                ):
                    gaps.append(
                        "The existing function returns a list, but the edit "
                        "uses yield and changes its return value to a generator. "
                        "Keep the list return contract and test the exact list."
                    )
        for function in tree.body:
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            argument_names = {arg.arg for arg in function.args.args}
            for node in ast.walk(function):
                if not isinstance(node, ast.Return) or not isinstance(node.value, ast.ListComp):
                    continue
                generators = node.value.generators
                if not generators or not isinstance(generators[0].iter, ast.Name):
                    continue
                if generators[0].iter.id not in argument_names:
                    continue
                if any(
                    isinstance(inner, ast.Compare)
                    and any(isinstance(op, (ast.In, ast.NotIn)) for op in inner.ops)
                    for inner in ast.walk(node.value)
                ):
                    continue
                direct_input_lists.append(node)
        if need_unique and direct_input_lists:
            gaps.append(
                "The request explicitly requires first-seen uniqueness, but a "
                "bare list comprehension preserves duplicates. Track seen values "
                "and test repeated eligible items."
            )
    return gaps


def try_focused_edit(workflow: Any) -> ProjectEditWorkflowResult | None:
    """Preview a small approved edit, or return None for the full workflow.

    Existing approval, manifest ownership and preview validation are mandatory.
    A failed or incomplete model response is not a success signal.
    """

    if not (getattr(workflow, "settings", None) or {}).get("experimental_focused_tool_loop", False):
        return None
    if not workflow.dry_run or workflow.approved_plan_id != workflow.approval_id:
        return None
    root = Path(workflow.root).resolve()
    manifest = [item for item in workflow.manifest if isinstance(item, dict)]
    owners = [item for item in manifest if not item.get("is_test")]
    if len(owners) != 1 or len(manifest) > 2:
        return None
    owner = _inside(root, str(owners[0].get("path") or ""))
    if owner is None or not owner.is_file() or owner.suffix != ".py":
        return None
    allowed: set[Path] = {owner}
    for item in manifest:
        if item is owners[0]:
            continue
        test_path = _inside(root, str(item.get("path") or ""))
        if test_path is None or not item.get("is_test") or test_path.suffix != ".py":
            return None
        allowed.add(test_path)
    try:
        source = owner.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if len(source) > _MAX_SOURCE_CHARS:
        return None
    started = time.perf_counter()
    context = [f"Approved owner {owner.relative_to(root).as_posix()}:\n{source}"]
    system = (
        "You are a repository edit agent. Return one JSON object only. "
        "Choose either {\"action\":\"search_text\",\"query\":\"literal\"}, "
        "{\"action\":\"read_file\",\"path\":\"relative.py\",\"start_line\":1}, "
        "or {\"action\":\"propose_changes\",\"changes\":[{\"action\":\"replace_symbol\","
        "\"path\":\"owner.py\",\"target_symbol\":\"function_name\","
        "\"new_content\":\"complete Python function source\"}]}. "
        "The complete approved owner source is already in context; do not "
        "request read_file for that same file. Use read/search only if other "
        "repository evidence is necessary; prefer one precise proposal. "
        "Every change MUST have its own action and path. Use replace_symbol for "
        "an existing function or class, create for a new test file, and ensure_import "
        "for an import. A from-import change is, for example, "
        "{\"action\":\"ensure_import\",\"path\":\"owner.py\"," 
        "\"target_symbol\":\"typing\",\"new_content\":\"Union\"}; this creates "
        "`from typing import Union`. A plain module import uses target_symbol "
        "`math` and new_content `import math`. "
        "Do not use replace_text to replace a named function. "
        "Edit only approved manifest paths. Do not invent API behavior. "
        "Every changed function definition MUST annotate every parameter and "
        "its return, even if the original function has no annotations. Example: "
        "def select_names(objects: list[object]) -> list[str]:. Add meaningful "
        "docstrings where required by the project validator. "
        f"The disposable proof runs on Python {sys.version_info.major}."
        f"{sys.version_info.minor}; use syntax and annotations that execute on "
        "that version. In particular, do not use X | Y type annotations on "
        "Python 3.9 without postponed evaluation; use typing.Union instead. "
        "Keep every Python "
        "source line at or below 100 characters. For new tests, import the "
        "owner through its project-root-relative dotted module path, and use "
        "unittest.TestCase with test methods that import and call the owner. "
        "Define fake objects inside the approved test file; never import fake "
        "helpers from files that are not in the approved paths. Split long "
        "assertions into input and expected assignments before asserting. "
        "Include a focused unittest test change when behavior changes and tests "
        "are allowed. Test fakes must honor the production function's input "
        "contract (object attributes are not dict keys). Prove every condition "
        "in the task, including exclusions and ordering. "
        "On validation feedback, repair the exact errors and resend a complete "
        "changes array. Return {\"action\":\"blocked\"} only if repository "
        "evidence is genuinely missing, not for a correctable schema error."
    )
    allowed_names = sorted(path.relative_to(root).as_posix() for path in allowed)
    feedback = ""
    previous_changes: list[dict[str, Any]] = []
    workflow.focused_tool_loop_model_calls = 0
    for attempt in range(_MAX_MODEL_CALLS):
        prompt = json.dumps(
            {
                "task": workflow.user_prompt,
                "approved_paths": allowed_names,
                "context": context,
                "feedback": feedback,
                "remaining_calls": _MAX_MODEL_CALLS - attempt,
            },
            ensure_ascii=False,
        )
        try:
            workflow.focused_tool_loop_model_calls = attempt + 1
            raw = generate_llm_response(
                workflow.selected_model,
                prompt,
                system=system,
                response_format="json",
                # Account-backed coding models can need more than 35 seconds
                # to return the first structured response. Respect the caller's
                # budget while retaining a bounded per-call deadline.
                timeout=max(1, min(int(workflow.timeout), 75)),
                allow_cloud_fallback=False,
                queue_category="interactive",
            )
        except Exception as exc:
            _diagnose(workflow, f"model_call_error:{type(exc).__name__}")
            return None
        reply = _json_object(raw)
        if reply is None:
            _diagnose(workflow, "invalid_json_object")
            feedback = json.dumps({
                "error": "invalid_json_object",
                "instruction": (
                    "Return exactly one valid JSON object with action and a "
                    "complete changes array. JSON-escape backslashes and "
                    "newlines inside new_content; omit Markdown fences."
                ),
            })
            continue
        action = str(reply.get("action") or ("propose_changes" if isinstance(reply.get("changes"), list) else ""))
        if action in {"replace_symbol", "replace_text", "create", "ensure_import"} and (
            not isinstance(reply.get("changes"), list)
            and isinstance(reply.get("path"), str)
            and isinstance(reply.get("new_content", reply.get("content")), str)
        ):
            reply = {"action": "propose_changes", "changes": [reply]}
            action = "propose_changes"
        if isinstance(reply.get("changes"), list) and action in {
            "replace_symbol", "replace_text", "create", "ensure_import"
        }:
            # Small local models sometimes promote a per-change action to the
            # envelope. Scope and behavioral validation still gate the patch.
            action = "propose_changes"
        if action in {"read_file", "search_text"}:
            _diagnose(workflow, f"context_action:{action}")
            if action == "read_file" and _inside(root, str(reply.get("path") or "")) == owner:
                evidence = (
                    "The complete approved owner source is already shown at the "
                    "start of context. Propose the scoped edit now; reading this "
                    "file again would not provide new evidence."
                )
            else:
                evidence = _context_action(root, reply)
            if evidence is None:
                _diagnose(workflow, f"unsupported_context_action:{action}")
                return None
            context.append(evidence)
            continue
        if action == "blocked" and feedback and attempt + 1 < _MAX_MODEL_CALLS:
            _diagnose(workflow, "correctable_model_block_retry")
            feedback = json.dumps({
                "error": "premature_block",
                "prior_feedback": feedback[:2500],
                "instruction": (
                    "The prior failure is a correctable schema, source, or test "
                    "error. Use the approved paths and current source to return "
                    "one complete propose_changes array; do not use blocked "
                    "unless required repository evidence is unavailable."
                ),
            })
            continue
        if action != "propose_changes" or not isinstance(reply.get("changes"), list):
            _diagnose(workflow, f"unsupported_model_action:{action[:40]}")
            return None
        rejection_reasons: list[str] = []
        raw_changes, omitted_retry_count = _omit_empty_scoped_retry_changes(
            root, allowed, reply["changes"], previous_changes,
        )
        if omitted_retry_count:
            _diagnose(
                workflow, f"omitted_empty_scoped_retry_changes:{omitted_retry_count}",
            )
        changes = _normalize_changes(
            root, allowed, raw_changes, rejection_reasons,
        )
        if not changes:
            reason = rejection_reasons[0] if rejection_reasons else "empty_changes"
            if reason == "missing_source_content" and getattr(
                workflow, "focused_tool_loop_debug_schema", False
            ):
                _diagnose(workflow, "missing_source_content_keys:" + ";".join(
                    ",".join(sorted(change))
                    for change in reply["changes"] if isinstance(change, dict)
                ))
            _diagnose(
                workflow,
                "invalid_or_out_of_scope_changes:" + reason,
            )
            if reason in {
                "missing_path", "missing_source_content", "empty_changes",
                "out_of_scope_path",
            }:
                feedback = json.dumps({
                    "error": reason,
                    "instruction": (
                        "Return a complete changes array. Every change must have "
                        "an approved path, an action, and new_content as a Python "
                        "source string. Do not omit or null these fields. "
                        "For ensure_import, target_symbol is a module such as "
                        "`typing` and new_content is one imported name such as "
                        "`Union`, creating `from typing import Union`; alternatively "
                        "target_symbol `math` and new_content `import math` creates "
                        "a plain module import. "
                        "Only these paths are approved: " + ", ".join(allowed_names)
                    ),
                })
                continue
            return None
        if previous_changes:
            changes = _merge_retry_changes(previous_changes, changes)
        for change in changes:
            content = str(change.get("new_content") or "")
            if not content or not any(len(line) > 100 for line in content.splitlines()):
                continue
            try:
                original_tree = ast.parse(content)
                formatted = _format_generated_long_statements(content)
                if ast.dump(original_tree, include_attributes=False) == ast.dump(
                    ast.parse(formatted), include_attributes=False,
                ):
                    change["new_content"] = formatted
            except SyntaxError:
                continue
        candidate = json.dumps({"changes": changes}, ensure_ascii=False)
        # Surface independent, source-grounded omissions with a failed
        # disposable preview. Waiting until its tests pass can spend a whole
        # local-model retry on the test fake, only to reveal a missing owner
        # predicate on the next call.
        selection_gap = _selection_requirement_gap(workflow.user_prompt, changes)
        requirement_gaps = _explicit_sequence_requirement_gaps(
            workflow.user_prompt, changes, source,
        )
        selection_error = (
            "The task explicitly requires selected objects, but the "
            "implementation does not read a selection-state API or "
            "selection helper. Add that predicate, and test an "
            "unselected object of the otherwise included kind."
        )
        try:
            preview = preview_project_edit_agent_response(
                candidate, project_root=str(root), request_prompt=workflow.user_prompt
            )
        except Exception as exc:
            _diagnose(workflow, f"preview_error:{type(exc).__name__}")
            if getattr(workflow, "focused_tool_loop_debug_traceback", False):
                _diagnose(workflow, "preview_traceback:" + "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )[-3000:])
            return None
        if preview.ok:
            if selection_gap:
                _diagnose(workflow, "selection_requirement_missing")
                previous_changes = changes
                feedback = _focused_validation_feedback(
                    changes, [selection_error],
                    workflow.user_prompt,
                )
                continue
            if requirement_gaps:
                _diagnose(workflow, "explicit_sequence_requirement_missing")
                previous_changes = changes
                feedback = _focused_validation_feedback(
                    changes, requirement_gaps, workflow.user_prompt,
                )
                continue
            if workflow.status_callback:
                workflow.status_callback("Focused tool-loop preview passed validation")
            return ProjectEditWorkflowResult(
                ok=True,
                status="preview_ok",
                candidate=candidate,
                preview=preview,
                timings=[*workflow.timings, {
                    "stage": "focused_tool_loop",
                    "seconds": round(time.perf_counter() - started, 4),
                    "model_calls": attempt + 1,
                }],
                implementation_plan=workflow.implementation_plan,
                approval_id=workflow.approval_id,
            )
        feedback = _focused_validation_feedback(
            changes,
            [*([selection_error] if selection_gap else []),
             *requirement_gaps, *preview.errors],
            workflow.user_prompt,
        )
        previous_changes = changes
        first_error = str(preview.errors[0]) if preview.errors else "unknown"
        _diagnose(workflow, f"preview_rejected:{first_error}")
    _diagnose(workflow, "model_call_budget_exhausted")
    return None
