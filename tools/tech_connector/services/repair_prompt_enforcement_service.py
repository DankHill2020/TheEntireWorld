"""Deterministic size and ownership enforcement for project-edit repair prompts."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import textwrap
from dataclasses import replace
from typing import Any


REPAIR_STAGE_KEYS = {
    "function_repair",
    "class_repair",
    "class_set_repair",
    "missing_symbol",
    "artifact_missing_symbol",
}
MAX_FUNCTION_REPAIR_CHARS = 8000
MAX_CLASS_REPAIR_CHARS = 11000


def prepare_repair_stage(stage: Any) -> tuple[Any, dict[str, Any]]:
    """Enforce ownership and right-size the model context for a repair stage."""
    stage, report = enforce_repair_prompt(stage)
    if str(getattr(stage, "key", "") or "") not in REPAIR_STAGE_KEYS:
        return stage, report
    prompt_chars = len(str(getattr(stage, "system_prompt", "") or "")) + len(
        str(getattr(stage, "user_prompt", "") or "")
    )
    output_tokens = int(getattr(stage, "num_predict", 0) or 0)
    if output_tokens < 0:
        output_tokens = 1800
    required_ctx = int(math.ceil(prompt_chars / 3.0)) + max(850, output_tokens) + 384
    current_ctx = int(getattr(stage, "num_ctx", 8192) or 8192)
    adaptive_ctx = max(2048, current_ctx, required_ctx)
    if adaptive_ctx != current_ctx:
        stage = replace(stage, num_ctx=adaptive_ctx)
    report["num_ctx_before"] = current_ctx
    report["num_ctx_after"] = adaptive_ctx
    return _with_report(stage, report), report


def deterministic_repair_stage_response(stage: Any) -> str | None:
    """Require semantic repair plans to be reasoned rather than restated."""
    del stage
    return None


def validate_repair_response(stage: Any, response: str) -> str:
    """Return a deterministic rejection reason for an invalid symbol response."""
    key = str(getattr(stage, "key", "") or "")
    if key not in {
        "function_repair",
        "class_repair",
        "class_set_repair",
        "artifact_missing_symbol",
    }:
        return ""
    text = str(response or "").strip()
    if not text:
        return "empty repair response"
    if "```" in text:
        return "repair response contains Markdown instead of raw Python"
    symbols = _repair_symbols(stage, str(getattr(stage, "user_prompt", "") or ""))
    if not symbols:
        return "repair response has no exact owner contract"
    symbol = symbols[0]
    expected_names = (
        {symbol.rsplit(".", 1)[-1]}
        if key == "function_repair"
        else {value.split(".", 1)[0] for value in symbols}
    )
    expected_types = (
        (ast.FunctionDef, ast.AsyncFunctionDef)
        if key == "function_repair"
        else (
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            if key == "artifact_missing_symbol"
            else (ast.ClassDef,)
        )
    )
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return f"repair response is not valid Python: {exc.msg}"
    extracted_nodes: list[ast.AST] | None = None
    if key == "function_repair":
        matching_callables = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == symbol.rsplit(".", 1)[-1]
        ]
        if len(matching_callables) == 1:
            extracted_nodes = matching_callables
    elif key in {"class_repair", "class_set_repair"}:
        matching_classes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and node.name in expected_names
        ]
        if (
            len(matching_classes) == len(expected_names)
            and {node.name for node in matching_classes} == expected_names
        ):
            extracted_nodes = matching_classes
    owned_nodes = (
        extracted_nodes
        if extracted_nodes is not None
        else [
            node for node in tree.body if isinstance(node, expected_types)
        ]
    )
    returned_names = {node.name for node in owned_nodes}
    if (
        extracted_nodes is None
        and len(tree.body) != len(expected_names)
    ) or returned_names != expected_names:
        return (
            "repair response must contain exactly the owned declarations: "
            + ", ".join(sorted(expected_names))
        )
    node = owned_nodes[0]
    if key == "artifact_missing_symbol" and isinstance(
        node,
        (ast.FunctionDef, ast.AsyncFunctionDef),
    ):
        metadata = dict(getattr(stage, "metadata", {}) or {})
        objective = str(metadata.get("objective") or "")
        zero_argument_call_required = bool(
            re.search(
                rf"(?<![.\w]){re.escape(node.name)}\s*\(\s*\)",
                objective,
            )
        )
        positional = [*node.args.posonlyargs, *node.args.args]
        required_positional = max(0, len(positional) - len(node.args.defaults))
        required_keyword_only = sum(
            default is None for default in node.args.kw_defaults
        )
        if zero_argument_call_required and (
            required_positional or required_keyword_only
        ):
            return (
                f"module-level {node.name} must be callable with no arguments "
                "because the objective explicitly calls it that way"
            )
    if key != "class_set_repair" and _placeholder_callable(node):
        return f"repair response for {symbol} still has a placeholder body"
    current_source = _owned_source(
        str(getattr(stage, "user_prompt", "") or ""),
        symbol,
        replacement_kind="callable" if key == "function_repair" else "class",
    )
    if current_source:
        try:
            current_tree = ast.parse(current_source)
            comparison_tree = (
                ast.Module(body=list(owned_nodes), type_ignores=[])
                if extracted_nodes is not None
                else tree
            )
            if ast.dump(current_tree, include_attributes=False) == ast.dump(
                comparison_tree,
                include_attributes=False,
            ):
                return f"repair response for {symbol} is AST-equivalent to the rejected source"
        except SyntaxError:
            pass
    return ""


def normalize_repair_response(stage: Any, response: str) -> tuple[str, bool]:
    """Normalize bounded raw-Python responses without widening their owner."""
    key = str(getattr(stage, "key", "") or "")
    if key not in REPAIR_STAGE_KEYS:
        return response, False
    text = str(response or "").strip()
    changed = False
    match = re.fullmatch(
        r"```(?:python|py)?\s*\n?(.*?)\n?```\s*",
        text,
        flags=re.I | re.S,
    )
    if match:
        text = match.group(1).strip()
        changed = True
    elif text.count("```") == 2:
        embedded_match = re.search(
            r"```(?:python|py)?\s*\n?(.*?)\n?```",
            text,
            flags=re.I | re.S,
        )
        if embedded_match:
            text = embedded_match.group(1).strip()
            changed = True
    elif "```" in text:
        symbols = _repair_symbols(
            stage,
            str(getattr(stage, "user_prompt", "") or ""),
        )
        expected_names = {
            (
                symbol.rsplit(".", 1)[-1]
                if key == "function_repair"
                else symbol.split(".", 1)[0]
            )
            for symbol in symbols
        }
        matching_blocks: list[str] = []
        for block in re.findall(
            r"```(?:python|py)?\s*\n?(.*?)\n?```",
            text,
            flags=re.I | re.S,
        ):
            try:
                block_tree = ast.parse(block.strip())
            except SyntaxError:
                continue
            declared_names = {
                node.name
                for node in ast.walk(block_tree)
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            if expected_names and expected_names.issubset(declared_names):
                matching_blocks.append(block.strip())
        if len(matching_blocks) == 1:
            text = matching_blocks[0]
            changed = True
    if key in {"function_repair", "class_repair", "class_set_repair"}:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text, changed
        retained = [
            node
            for node in tree.body
            if not isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        if len(retained) != len(tree.body):
            tree.body = retained
            ast.fix_missing_locations(tree)
            text = ast.unparse(tree).strip()
            changed = True
    return text, changed


def enforce_repair_prompt(stage: Any) -> tuple[Any, dict[str, Any]]:
    """Return a bounded repair stage and a machine-readable enforcement report."""
    key = str(getattr(stage, "key", "") or "")
    user_prompt = str(getattr(stage, "user_prompt", "") or "")
    system_prompt = str(getattr(stage, "system_prompt", "") or "")
    before_chars = len(system_prompt) + len(user_prompt)
    report = {
        "stage": key,
        "before_chars": before_chars,
        "after_chars": before_chars,
        "compacted": False,
        "reason": "not_a_repair_stage",
    }
    if key not in REPAIR_STAGE_KEYS:
        return stage, report

    limit = (
        MAX_FUNCTION_REPAIR_CHARS
        if key in {"function_repair", "missing_symbol"}
        else MAX_CLASS_REPAIR_CHARS
    )
    if before_chars <= limit:
        report["reason"] = "already_bounded"
        return _with_report(stage, report), report

    symbols = _repair_symbols(stage, user_prompt)
    if not symbols:
        report["reason"] = "missing_exact_owner"
        report["rejected"] = True
        raise ValueError(
            f"Oversized repair prompt ({before_chars:,} chars) has no exact owning symbol; "
            "refusing to send an unbounded repair request."
        )

    replacement_kind = "class" if key in {"class_repair", "class_set_repair"} else "callable"
    metadata = dict(getattr(stage, "metadata", {}) or {})
    canonical_contract = dict(metadata.get("canonical_repair_contract") or {})
    metadata_owner_source = str(metadata.get("owner_source") or "").strip()
    canonical_owner_source = str(
        canonical_contract.get("source") or metadata_owner_source
    ).strip()
    canonical_symbol = str(canonical_contract.get("symbol") or "").strip()
    owned_sources: list[str] = []
    for owned_symbol in symbols:
        target_name = (
            owned_symbol.split(".", 1)[0]
            if replacement_kind == "class"
            else owned_symbol.rsplit(".", 1)[-1]
        )
        declaration_markers = (
            (f"class {target_name}",)
            if replacement_kind == "class"
            else (f"def {target_name}(", f"async def {target_name}(")
        )
        canonical_owner_matches = (
            bool(canonical_owner_source)
            and bool(canonical_symbol)
            and (
                canonical_symbol == owned_symbol
                or canonical_symbol.rsplit(".", 1)[-1] == target_name
            )
            and any(
                marker in canonical_owner_source
                for marker in declaration_markers
            )
        )
        metadata_source = (
            canonical_owner_source
            if canonical_owner_matches
            else _extract_symbol(
                metadata_owner_source,
                target_name,
                replacement_kind=replacement_kind,
            )
            if metadata_owner_source
            else ""
        )
        owned_sources.append(
            metadata_source
            or _owned_source(
                user_prompt,
                owned_symbol,
                replacement_kind=replacement_kind,
            )
        )
    current_source = "\n\n".join(value for value in owned_sources if value)
    symbol = ", ".join(symbols)
    if not current_source:
        report["reason"] = "missing_exact_source"
        report["rejected"] = True
        raise ValueError(
            f"Oversized repair prompt for {symbol} has no extractable owner source; "
            "refusing to repair from the complete package."
        )

    requirements = _section_bullets(
        user_prompt,
        (
            "Requirements owned by this file:",
            "Deterministic validation failures:",
            "Smallest matching disposable validation failure:",
        ),
    )
    requirements = list(dict.fromkeys([
        *requirements,
        *[
            str(value)
            for value in canonical_contract.get("full_requirements") or []
            if str(value).strip()
        ],
        *[
            str(value)
            for value in canonical_contract.get("requirements") or []
            if str(value).strip()
        ],
        *[
            str(value)
            for value in (
                canonical_contract.get("all_validation_errors")
                or metadata.get("all_validation_errors")
                or []
            )
            if str(value).strip()
        ],
    ]))
    if not requirements:
        report["reason"] = "missing_failed_requirement"
        report["rejected"] = True
        raise ValueError(
            f"Oversized repair prompt for {symbol} has no failed requirement; "
            "refusing an unconstrained regeneration."
        )

    objective = str(
        canonical_contract.get("full_objective")
        or metadata.get("full_objective")
        or ""
    ).strip() or _section_text(
        user_prompt,
        ("Original objective:",),
        max_chars=len(user_prompt),
    )
    if key == "function_repair" and len(objective) > 1200:
        objective = objective[:1200].rstrip() + "\n[full objective retained by orchestration]"
    evidence = _evidence_sections(
        user_prompt,
        max_chars=1200 if key == "function_repair" else len(user_prompt),
    )
    canonical_evidence = {
        "module_imports": list(canonical_contract.get("module_imports") or []),
        "module_symbols": list(canonical_contract.get("module_symbols") or []),
        "generated_interfaces": list(
            canonical_contract.get("generated_interfaces") or []
        ),
        "sibling_signatures": list(
            canonical_contract.get("sibling_signatures") or []
        ),
        "state_context": list(canonical_contract.get("state_context") or []),
        "callsite_excerpts": list(
            canonical_contract.get("callsite_excerpts")
            or []
        ),
    }
    canonical_evidence = {
        key: value for key, value in canonical_evidence.items() if value
    }
    if canonical_evidence:
        rendered_canonical_evidence = json.dumps(
            canonical_evidence,
            indent=2,
            ensure_ascii=True,
        )
        if key == "function_repair" and len(rendered_canonical_evidence) > 2800:
            rendered_canonical_evidence = (
                rendered_canonical_evidence[:2800].rstrip()
                + "\n[remaining verified evidence retained by orchestration]"
            )
        evidence = "\n\n".join(
            value for value in (rendered_canonical_evidence, evidence) if value
        )
    critical_directives = _critical_directive_sections(
        user_prompt,
        max_chars=1000 if key == "function_repair" else len(user_prompt),
    )
    canonical_prompt_hash = hashlib.sha256(
        user_prompt.encode("utf-8")
    ).hexdigest()
    canonical_contract_hash = hashlib.sha256(
        json.dumps(
            canonical_contract,
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    consumed_sections = [
        "owner",
        "objective",
        "failed_requirements",
        "current_owner_source",
    ]
    if evidence:
        consumed_sections.append("verified_evidence")
    if critical_directives:
        consumed_sections.append("acceptance_directives")
    if (
        "VERIFIED FEDERATED SYMBOL EVIDENCE:" in user_prompt
        and not evidence
    ):
        raise ValueError(
            f"Atomic repair envelope for {symbol} could not preserve verified "
            "federated evidence; refusing an evidence-free repair."
        )
    requirement_rows = [
        {
            "id": f"REPAIR-{index:03d}",
            "owner": symbol,
            "failure": value,
        }
        for index, value in enumerate(requirements, start=1)
    ]
    compact_prompt = "\n".join(
        [
            "ATOMIC REPAIR ENVELOPE",
            f"Owner: {symbol}",
            (
                f"Replacement boundary: exactly {len(symbols)} complete "
                f"{replacement_kind} declaration"
                + ("" if len(symbols) == 1 else "s")
            ),
            "",
            "Original objective:",
            objective or f"Repair {symbol}.",
            "",
            "Failed requirements:",
            json.dumps(requirement_rows, indent=2),
            "",
            "Canonical repair context:",
            f"- full_prompt_sha256: {canonical_prompt_hash}",
            f"- owner_contract_sha256: {canonical_contract_hash}",
            "- consumed_sections: " + ", ".join(consumed_sections),
            "- This envelope contains the complete owner-specific contract; omitted "
            "prompt sections are unrelated to this replacement boundary.",
            "",
            "Verified dependencies and interfaces:",
            evidence or "(none required by the reported failure)",
            "",
            "Exact current owner source:",
            "```python",
            current_source.rstrip(),
            "```",
            "",
            "Owner-specific acceptance directives:",
            critical_directives or "(none beyond the failed requirements)",
            "",
            "Acceptance contract:",
            "- Return raw Python only.",
            f"- Return exactly the complete replacement for {symbol}.",
            "- Preserve the exact public signature and decorators.",
            "- The executable AST must differ from the rejected source.",
            "- Address every failed requirement listed above.",
            "- Do not return imports, unrelated symbols, a diff, Markdown, or explanation.",
        ]
    ).strip()

    after_chars = len(system_prompt) + len(compact_prompt)
    report.update(
        {
            "after_chars": after_chars,
            "compacted": True,
            "reason": (
                "adaptive_atomic_owner_envelope"
                if after_chars > limit
                else "atomic_owner_envelope"
            ),
            "owner": symbol,
            "requirement_count": len(requirement_rows),
            "canonical_prompt_hash": canonical_prompt_hash,
            "consumed_sections": consumed_sections,
            "target_chars": limit,
            "required_context_expansion": after_chars > limit,
        }
    )
    return _with_report(replace(stage, user_prompt=compact_prompt), report), report


def _critical_directive_sections(prompt: str, *, max_chars: int) -> str:
    """Preserve bounded repair directives that must survive prompt compaction."""

    header_matches = list(re.finditer(
        r"(?m)^([A-Z][A-Z0-9 _-]{5,}):\s*$",
        str(prompt or ""),
    ))
    sections: list[str] = []
    for index, match in enumerate(header_matches):
        header = match.group(1).strip()
        if not any(
            marker in header
            for marker in (
                "CONTRACT",
                "DIAGNOSIS",
                "REPAIR",
                "RULE",
                "SHAPE",
            )
        ):
            continue
        end = (
            header_matches[index + 1].start()
            if index + 1 < len(header_matches)
            else len(prompt)
        )
        body = str(prompt[match.end():end]).strip()
        section = f"{header}:\n{body}".strip()
        if section and section not in sections:
            sections.append(section)
    rendered = "\n\n".join(sections)
    if len(rendered) <= max_chars:
        return rendered
    directive_lines = [
        line.strip()
        for section in sections
        for line in section.splitlines()
        if line.strip()
    ]
    priority_patterns = (
        r"\bmust\b",
        r"\bnever\b",
        r"\brequired\b",
        r"\bdeclare\b",
        r"\binstall\b",
        r"\bexact(?:ly)?\b",
        r"\breturn\b",
        r"\buse\b",
        r"\bbefore\b|\bafter\b",
    )
    prioritized: list[str] = []
    for pattern in priority_patterns:
        for line in directive_lines:
            if (
                line not in prioritized
                and re.search(pattern, line, flags=re.IGNORECASE)
            ):
                prioritized.append(line)
    for line in directive_lines:
        if line not in prioritized:
            prioritized.append(line)
    selected: list[str] = []
    selected_chars = 0
    for line in prioritized:
        additional = len(line) + (1 if selected else 0)
        if selected_chars + additional > max_chars:
            continue
        selected.append(line)
        selected_chars += additional
    return "\n".join(selected).rstrip()


def _with_report(stage: Any, report: dict[str, Any]) -> Any:
    metadata = dict(getattr(stage, "metadata", {}) or {})
    metadata["repair_prompt_enforcement"] = dict(report)
    return replace(stage, metadata=metadata)


def _repair_symbols(stage: Any, prompt: str) -> list[str]:
    metadata = dict(getattr(stage, "metadata", {}) or {})
    metadata_symbols = [
        str(value).strip()
        for value in (metadata.get("symbols") or [])
        if str(value).strip()
    ]
    if metadata_symbols:
        return list(dict.fromkeys(metadata_symbols))
    symbol = str(metadata.get("symbol") or "").strip()
    if symbol:
        return [symbol]
    label = str(getattr(stage, "label", "") or "")
    patterns = (
        r"Callable owned by this worker:\s*\n([A-Za-z_][\w.]*)",
        r"Class chunk to replace:\s*\n([A-Za-z_][\w.]*)",
        r"Repairing class\s+([A-Za-z_][\w.]*)",
        r"Missing manifest-owned public symbol:\s*\n([A-Za-z_][\w.]*)",
    )
    for text in (prompt, label):
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return [match.group(1)]
    return []


def _repair_symbol(stage: Any, prompt: str) -> str:
    symbols = _repair_symbols(stage, prompt)
    return symbols[0] if symbols else ""


def _owned_source(prompt: str, symbol: str, *, replacement_kind: str) -> str:
    blocks = re.findall(r"```python\s*\n(.*?)```", prompt, flags=re.S | re.I)
    leaf = symbol.rsplit(".", 1)[-1]
    owner = symbol.split(".", 1)[0]
    for block in blocks:
        extracted = _extract_symbol(
            block,
            leaf if replacement_kind == "callable" else owner,
            replacement_kind=replacement_kind,
        )
        if extracted:
            return extracted
    if replacement_kind == "callable":
        leaf_pattern = re.compile(
            rf"(?m)^([ \t]*)(?:async\s+)?def\s+"
            rf"{re.escape(leaf)}\s*\("
        )
        for match in leaf_pattern.finditer(prompt):
            indentation = match.group(1)
            start = match.start()
            lines = prompt[start:].splitlines()
            if not lines:
                continue
            retained = [lines[0]]
            for line in lines[1:]:
                stripped = line.strip()
                if not stripped:
                    retained.append(line)
                    continue
                current_indent = line[:len(line) - len(line.lstrip())]
                if len(current_indent.expandtabs(4)) <= len(
                    indentation.expandtabs(4)
                ):
                    break
                retained.append(line)
            extracted = textwrap.dedent("\n".join(retained)).strip()
            if extracted and _extract_symbol(
                extracted,
                leaf,
                replacement_kind="callable",
            ):
                return extracted
    return ""


def _extract_symbol(source: str, target_name: str, *, replacement_kind: str) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    allowed_types = (
        (ast.ClassDef,)
        if replacement_kind == "class"
        else (ast.FunctionDef, ast.AsyncFunctionDef)
    )
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, allowed_types) and node.name == target_name
    ]
    if not candidates:
        return ""
    node = min(candidates, key=lambda item: (getattr(item, "lineno", 0), -getattr(item, "end_lineno", 0)))
    lines = source.splitlines()
    start = max(0, int(getattr(node, "lineno", 1)) - 1)
    decorators = list(getattr(node, "decorator_list", []) or [])
    if decorators:
        start = max(0, min(int(item.lineno) for item in decorators) - 1)
    end = int(getattr(node, "end_lineno", start + 1))
    return "\n".join(lines[start:end]).strip()


def _section_text(prompt: str, headers: tuple[str, ...], *, max_chars: int) -> str:
    for header in headers:
        marker = prompt.find(header)
        if marker < 0:
            continue
        value = prompt[marker + len(header) :]
        boundary = re.search(r"\n[A-Z][^\n]{2,80}:\s*\n", value)
        if boundary:
            value = value[: boundary.start()]
        return value.strip()[:max_chars].rstrip()
    return ""


def _section_bullets(prompt: str, headers: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for header in headers:
        section = _section_text(prompt, (header,), max_chars=4000)
        lines = section.splitlines()
        bullet_rows: list[str] = []
        started = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if started:
                    break
                continue
            match = re.match(r"^\s*[-*]\s+(.+?)\s*$", line)
            if match:
                bullet_rows.append(match.group(1).strip())
                started = True
                continue
            if started:
                break
        if bullet_rows:
            values.extend(bullet_rows)
            continue
        for line in lines:
            value = line.strip()
            if value and value not in {"(none)", "```", "```python", "```text"}:
                values.append(value)
                break
    return list(dict.fromkeys(values))


def _evidence_sections(prompt: str, *, max_chars: int) -> str:
    headers = (
        "Imports already available in the module:",
        "Exact generated package interfaces already available:",
        "Sibling interfaces available to call:",
        "Verified API evidence:",
        "VERIFIED FEDERATED SYMBOL EVIDENCE:",
        "Authoritative signatures:",
    )
    chunks: list[str] = []
    for header in headers:
        section_limit = (
            max_chars
            if header == "VERIFIED FEDERATED SYMBOL EVIDENCE:"
            else 1200
        )
        value = _section_text(prompt, (header,), max_chars=section_limit)
        if value and value.casefold() not in {"(none)", "```python\n(none)\n```"}:
            chunks.append(f"{header}\n{value}")
    return "\n\n".join(chunks)[:max_chars].rstrip()


def _placeholder_callable(node: ast.AST) -> bool:
    body = list(getattr(node, "body", []) or [])
    if not body:
        return True
    executable = [
        item
        for item in body
        if not (
            isinstance(item, ast.Expr)
            and isinstance(getattr(item, "value", None), ast.Constant)
            and isinstance(item.value.value, str)
        )
    ]
    if not executable:
        return True
    return all(
        isinstance(item, ast.Pass)
        or (
            isinstance(item, ast.Expr)
            and isinstance(getattr(item, "value", None), ast.Constant)
            and item.value.value is Ellipsis
        )
        for item in executable
    )
