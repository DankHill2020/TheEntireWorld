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
    _checkpoint_hash,
)


def _normalize_manifest_contract(response: str, prompt: str) -> str:
    """Normalize package paths and keep each public symbol with one owner."""

    try:
        payload = json.loads(response)
    except (TypeError, ValueError):
        return response
    contracts = payload.get("integration_contracts")
    if isinstance(contracts, dict):
        contract_blob = json.dumps(contracts).lower()
        invariants = list(contracts.get("shared_invariants") or [])
        for term in (
            "async",
            "atomic",
            "cancellation",
            "checkpoint",
            "crc",
            "dependency",
            "endianness",
            "journal",
            "observer",
            "pause",
            "resume",
            "rollback",
            "sync",
            "transaction",
        ):
            if (
                re.search(rf"\b{re.escape(term)}\b", prompt.lower())
                and not re.search(rf"\b{re.escape(term)}\b", contract_blob)
            ):
                invariants.append(
                    f"{term.capitalize()} behavior must preserve the corresponding "
                    "observable requirement from the original objective."
                )
        contracts["shared_invariants"] = list(dict.fromkeys(invariants))
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return response

    module_match = re.search(
        r"\b(?:under|in)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b",
        prompt,
    )
    module_root = (
        Path(*module_match.group(1).split("."))
        if module_match
        else None
    )
    owners: set[str] = set()
    original_paths: dict[int, str] = {}
    requested_filename_order = list(dict.fromkeys(
        Path(match.group(0)).name
        for match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\.py\b", prompt)
    ))
    requested_filenames = set(requested_filename_order)
    for item in files:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or "").replace("\\", "/")
        original_paths[id(item)] = raw_path
        raw_path_obj = Path(raw_path)
        is_test = bool(item.get("is_test")) or raw_path_obj.name.startswith("test_")
        dotted_filename = raw_path_obj.name
        if (
            module_root is not None
            and not is_test
            and raw_path_obj.name in requested_filenames
        ):
            item["path"] = str(module_root / raw_path_obj.name).replace("\\", "/")
        elif dotted_filename.endswith(".py") and dotted_filename.count(".") > 1:
            dotted_path = Path(
                *dotted_filename[:-3].split(".")
            ).with_suffix(".py")
            generic_generated_parent = (
                "generated" in {part.lower() for part in raw_path_obj.parent.parts}
            )
            normalized_path = (
                dotted_path
                if generic_generated_parent or raw_path_obj.parent == Path(".")
                else raw_path_obj.parent / dotted_path
            )
            item["path"] = str(normalized_path).replace("\\", "/")
        elif (
            module_root is not None
            and not is_test
            and raw_path_obj.suffix.lower() == ".py"
            and (
                raw_path_obj.parent == Path(".")
                or "generated" in {
                    part.lower() for part in raw_path_obj.parent.parts
                }
            )
        ):
            item["path"] = str(module_root / raw_path_obj.name).replace("\\", "/")
        symbols: list[str] = []
        for raw_symbol in item.get("public_symbols") or []:
            symbol = re.sub(
                r"^(?:(?:async\s+)?def|async|class)\s+",
                "",
                str(raw_symbol).strip(),
                flags=re.IGNORECASE,
            )
            leaf = symbol.split("(", 1)[0].rsplit(".", 1)[-1]
            if not leaf:
                continue
            if is_test:
                if leaf.startswith(("Test", "test_")):
                    symbols.append(symbol)
                continue
            if leaf in owners:
                continue
            owners.add(leaf)
            symbols.append(symbol)
        item["public_symbols"] = symbols

    prompt_file_index = {
        filename.lower(): index
        for index, filename in enumerate(requested_filename_order)
    }
    files.sort(
        key=lambda item: (
            1
            if isinstance(item, dict)
            and (
                bool(item.get("is_test"))
                or Path(str(item.get("path") or "")).name.startswith("test_")
            )
            else 0,
            prompt_file_index.get(
                Path(str(item.get("path") or "")).name.lower(),
                len(prompt_file_index),
            )
            if isinstance(item, dict)
            else len(prompt_file_index),
        )
    )
    normalized_paths = [
        str(item.get("path") or "").replace("\\", "/")
        for item in files
        if isinstance(item, dict)
    ]
    path_by_alias: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            continue
        normalized = str(item.get("path") or "").replace("\\", "/")
        original = original_paths.get(id(item), normalized)
        for alias in (normalized, original, Path(normalized).name, Path(original).name):
            if alias:
                path_by_alias[alias.lower()] = normalized
    index_by_path = {
        path.lower(): index for index, path in enumerate(normalized_paths)
    }
    for index, item in enumerate(item for item in files if isinstance(item, dict)):
        current_path = str(item.get("path") or "").replace("\\", "/")
        dependencies: list[str] = []
        for raw_dependency in item.get("depends_on") or []:
            dependency_text = str(raw_dependency).replace("\\", "/")
            dependency = path_by_alias.get(
                dependency_text.lower(),
                path_by_alias.get(Path(dependency_text).name.lower(), dependency_text),
            )
            dependency_index = index_by_path.get(dependency.lower())
            if (
                dependency
                and dependency != current_path
                and dependency_index is not None
                and dependency_index < index
                and dependency not in dependencies
            ):
                dependencies.append(dependency)
        item["depends_on"] = dependencies
    return json.dumps(payload, ensure_ascii=True)


_REPAIR_FAILURE_HISTORY: dict[str, dict[str, Any]] = {}


def _query_stage(
    stage: ProjectEditPromptStage,
    *,
    selected_model: str,
    settings: dict[str, Any],
    timeout: int,
    suffix: str = "",
) -> tuple[str, dict[str, Any]]:
    model = (
        selected_model
        or model_for_project_edit_stage(
            stage,
            settings,
            selected_model=None,
        )
    )
    explicit_cloud = str(selected_model or "").lower().startswith(
        ("anthropic:", "claude:", "openai:", "google:", "gemini:", "x:", "grok:")
    )
    provider_route = (
        LLMProviderRoute(
            provider="ollama",
            model=model,
            cloud_active=False,
            transport="local",
        )
        if selected_model and not explicit_cloud
        else None
    )
    started = time.perf_counter()
    call_error = ""
    try:
        if suffix:
            stage = replace(
                stage,
                user_prompt=str(stage.user_prompt or "") + str(suffix),
            )
            suffix = ""
        from tech_connector.services.repair_prompt_enforcement_service import (
            deterministic_repair_stage_response,
            normalize_repair_response,
            prepare_repair_stage,
            validate_repair_response,
        )

        stage, repair_prompt_report = prepare_repair_stage(stage)
        stage_metadata = dict(getattr(stage, "metadata", {}) or {})
        from tech_connector.services.project_edit_prompt_policy_service import (
            build_project_edit_task_envelope,
            compact_project_edit_system_prompt,
        )

        compact_system_prompt, system_prompt_metrics = (
            compact_project_edit_system_prompt(stage.system_prompt)
        )
        compact_user_prompt, user_prompt_metrics = build_project_edit_task_envelope(
            stage_key=stage.key,
            stage_label=stage.label,
            user_prompt=stage.user_prompt,
            metadata=stage_metadata,
        )
        repair_owner_before_call = str(
            repair_prompt_report.get("owner")
            or stage_metadata.get("symbol")
            or ", ".join(
                str(value) for value in stage_metadata.get("symbols") or []
            )
            or ""
        )
        failure_fingerprint_before_call = _checkpoint_hash({
            "stage": stage.key,
            "owner": repair_owner_before_call,
            "prompt": stage.user_prompt,
        })[:12]
        failure_history = _REPAIR_FAILURE_HISTORY.get(
            failure_fingerprint_before_call,
            {},
        )
        repeat_count = int(failure_history.get("repeat_count") or 0)
        requested_repair_temperature = float(
            stage_metadata.get("repair_temperature") or 0.0
        )
        repair_temperature = min(
            0.2,
            max(requested_repair_temperature, repeat_count * 0.1),
        )
        if repeat_count:
            print(
                "      Repair strategy transition: repeated rejected output "
                f"{repeat_count} time(s); using diversified sampling "
                f"temperature={repair_temperature:.1f} for only this owner."
            )
        if stage.key in {
            "function_repair",
            "class_repair",
            "class_set_repair",
            "missing_symbol",
            "artifact_missing_symbol",
        }:
            print(
                "      Repair context: "
                f"{repair_prompt_report['before_chars']:,} -> "
                f"{repair_prompt_report['after_chars']:,} chars; "
                f"context {repair_prompt_report.get('num_ctx_before', stage.num_ctx):,} -> "
                f"{repair_prompt_report.get('num_ctx_after', stage.num_ctx):,}; "
                f"{repair_prompt_report['reason']}"
            )

        response = deterministic_repair_stage_response(stage)
        deterministic_response = response is not None
        if response is not None:
            print(f"      Repair plan: deterministic ({stage.key}); model call skipped")
        else:
            response = generate_llm_response(
                model=model,
                system=compact_system_prompt,
                prompt=compact_user_prompt + suffix,
                response_format=stage.response_format or None,
                options={
                    "temperature": repair_temperature,
                    "num_ctx": stage.num_ctx,
                    "num_predict": stage.num_predict,
                    "think": (
                        False
                        if stage_metadata.get("disable_thinking")
                        else None
                    ),
                },
                timeout=max(int(timeout), int(stage.timeout)),
                provider_route=provider_route,
                no_progress_seconds=stage.no_progress_seconds,
                max_wall_seconds=max(int(timeout), int(stage.timeout)),
                queue_category="repair",
            )
        response, normalized_fence = normalize_repair_response(stage, response)
        if normalized_fence:
            print(f"      Normalized {stage.label}: removed one bare Python code fence")
        rejection = validate_repair_response(stage, response)
        if rejection:
            response_fingerprint = _checkpoint_hash(response or "")[:12]
            history = _REPAIR_FAILURE_HISTORY.setdefault(
                failure_fingerprint_before_call,
                {
                    "last_response_fingerprint": "",
                    "repeat_count": 0,
                },
            )
            if history.get("last_response_fingerprint") == response_fingerprint:
                history["repeat_count"] = int(history.get("repeat_count") or 0) + 1
            else:
                history["last_response_fingerprint"] = response_fingerprint
                history["repeat_count"] = 1
            print(f"      Rejected {stage.label}: {rejection}")
            call_error = rejection
    except (TimeoutError, ValueError) as exc:
        response = ""
        call_error = str(exc)
        print(
            f"      {stage.label} failed before producing code: "
            f"{call_error}"
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    inference_metrics: dict[str, Any] = {}
    if not bool(locals().get("deterministic_response", False)):
        try:
            from tech_connector.services.llm_router_service import (
                pop_last_inference_metrics,
            )

            inference_metrics = pop_last_inference_metrics()
        except Exception:
            inference_metrics = {}
    stage_metadata = dict(getattr(stage, "metadata", {}) or {})
    if "system_prompt_metrics" in locals():
        stage_metadata["prompt_compaction"] = {
            **system_prompt_metrics,
            **user_prompt_metrics,
        }
    repair_owner = str(
        (locals().get("repair_prompt_report") or {}).get("owner")
        or stage_metadata.get("symbol")
        or ", ".join(str(value) for value in stage_metadata.get("symbols") or [])
        or ""
    )
    failure_fingerprint = _checkpoint_hash({
        "stage": stage.key,
        "owner": repair_owner,
        "prompt": stage.user_prompt,
    })[:12]
    if inference_metrics:
        print(
            "      Inference telemetry: "
            f"model={model}, stage={stage.key}, "
            f"first_token={inference_metrics.get('time_to_first_token_ms')}ms, "
            f"ingest={inference_metrics.get('prompt_ingestion_ms')}ms, "
            f"generate={inference_metrics.get('generation_ms')}ms, "
            f"tokens={inference_metrics.get('input_tokens', 0)}->"
            f"{inference_metrics.get('output_tokens', 0)}, "
            f"rate={inference_metrics.get('tokens_per_second', 0.0)} tok/s, "
            f"owner={repair_owner or '(package)'}, "
            f"failure={failure_fingerprint}"
        )
    timing = {
        "stage": stage.key,
        "label": stage.label,
        "model": model,
        "elapsed_ms": elapsed_ms,
        "prompt_chars": int(
            inference_metrics.get("input_chars")
            or len(stage.system_prompt) + len(stage.user_prompt) + len(suffix)
        ),
        "response_chars": len(response or ""),
        "estimated_response_tokens": max(0, len(response or "") // 4),
        "output_chars_per_second": (
            round(len(response or "") / max(elapsed_ms / 1000.0, 0.001), 2)
        ),
        "num_ctx": stage.num_ctx,
        "model_call_skipped": bool(locals().get("deterministic_response", False)),
        "response_rejected": bool(call_error and not response),
        "call_error": call_error,
        "time_to_first_token_ms": inference_metrics.get("time_to_first_token_ms"),
        "prompt_ingestion_ms": inference_metrics.get("prompt_ingestion_ms"),
        "generation_ms": inference_metrics.get("generation_ms"),
        "input_tokens": inference_metrics.get("input_tokens", 0),
        "output_tokens": inference_metrics.get("output_tokens", 0),
        "tokens_per_second": inference_metrics.get("tokens_per_second", 0.0),
        "inference": inference_metrics,
        "repair_owner": repair_owner,
        "failure_fingerprint": failure_fingerprint,
        "strategy_transition": (
            f"diversified_sampling_{repair_temperature:.1f}"
            if bool(locals().get("repeat_count", 0))
            else ""
        ),
    }
    if call_error:
        timing["timed_out"] = True
        timing["error"] = call_error
    return response or "", timing


def _focused_repair_model(selected_model: str, attempt: int) -> str:
    """Keep the selected model resident for focused work and repairs."""

    return str(selected_model or "")


def _compact_callable_repair_model(selected_model: str) -> str:
    """Preserve selected-model affinity for a bounded callable repair."""

    return str(selected_model or "")


def _strong_task_model(selected_model: str) -> str:
    """Return the selected model, escalating a local 3B selection to 7B."""

    model = str(selected_model or "")
    if re.search(r":3b$", model, flags=re.IGNORECASE):
        return re.sub(r":3b$", ":7b", model, flags=re.IGNORECASE)
    return model


def _generation_task_model(
    stage: ProjectEditPromptStage,
    selected_model: str,
    attempt: int,
) -> str:
    """Select a model from the bounded task's structural complexity."""

    task_text = f"{stage.label}\n{stage.user_prompt}"
    callable_count = len(re.findall(r"\bdef\s+[A-Za-z_]", task_text))
    validation_count = len(re.findall(r'"checks"\s*:', task_text))
    interface_count = task_text.count('"required_dependency_interfaces"')
    structurally_complex = (
        len(stage.user_prompt) >= 14_000
        or callable_count >= 5
        or validation_count >= 4
        or interface_count >= 2
    )
    if stage.key.startswith(
        ("artifact_file_generation", "artifact_owner_generation")
    ) and structurally_complex:
        return _strong_task_model(selected_model)
    return _focused_repair_model(selected_model, attempt)


def _build_syntax_region_repair_stage(
    base_stage: ProjectEditPromptStage,
    *,
    source: str,
    path: str,
    failures: list[str],
    attempt: int,
) -> tuple[ProjectEditPromptStage, int, int]:
    """Build a bounded repair for only the source region containing a syntax error."""

    source_lines = source.splitlines()
    syntax_line = 1
    syntax_end_line = 1
    syntax_message = next(
        (str(failure) for failure in failures if str(failure).strip()),
        "Python syntax validation failed.",
    )
    try:
        ast.parse(source, filename=path)
    except SyntaxError as exc:
        syntax_line = max(1, int(exc.lineno or 1))
        syntax_end_line = max(
            syntax_line,
            int(getattr(exc, "end_lineno", None) or syntax_line),
        )
        syntax_message = f"{exc.msg} at line {syntax_line}"

    def line_indent(line: str) -> int:
        return len(line) - len(line.lstrip(" \t"))

    target_index = min(
        max(0, syntax_line - 1),
        max(0, len(source_lines) - 1),
    )
    compound_header = re.compile(
        r"^\s*(?:async\s+def|def|class|if|elif|else|for|while|try|except|"
        r"finally|with|match|case)\b"
    )
    enclosing_headers: list[int] = []
    current_indent = (
        line_indent(source_lines[target_index])
        if source_lines
        else 0
    )
    for index in range(target_index, -1, -1):
        line = source_lines[index]
        if not line.strip() or not compound_header.match(line):
            continue
        indent = line_indent(line)
        if not enclosing_headers or indent < current_indent:
            enclosing_headers.append(index)
            current_indent = indent
    if enclosing_headers:
        owner_index = enclosing_headers[
            min(max(0, attempt - 1), len(enclosing_headers) - 1)
        ]
        owner_indent = line_indent(source_lines[owner_index])
        end_index = max(owner_index, syntax_end_line - 1)
        for index in range(owner_index + 1, len(source_lines)):
            line = source_lines[index]
            if not line.strip():
                end_index = index
                continue
            if line_indent(line) <= owner_indent:
                break
            end_index = index
        start_line = owner_index + 1
        end_line = end_index + 1
    else:
        start_line = syntax_line
        end_line = syntax_end_line
    context_start = max(1, start_line - 4)
    context_end = min(max(1, len(source_lines)), end_line + 4)
    numbered_context = "\n".join(
        f"{line_number:>5}: {source_lines[line_number - 1]}"
        for line_number in range(context_start, context_end + 1)
    )
    metadata = dict(base_stage.metadata or {})
    metadata.update({
        "symbol": f"{Path(path).name}:{start_line}-{end_line}",
        "repair_temperature": min(0.2, max(0, attempt - 1) * 0.1),
        "disable_thinking": True,
        "syntax_region_start": start_line,
        "syntax_region_end": end_line,
    })
    stage = replace(
        base_stage,
        key="syntax_region_repair",
        label=(
            f"Repairing syntax region {Path(path).name}:"
            f"{start_line}-{end_line}"
        ),
        system_prompt=(
            "You repair one exact Python source region. Preserve indentation and "
            "behavior. Do not return the whole file, explanations, line numbers, "
            "or markdown fences. Return exactly two marker lines containing the "
            "replacement source between them:\n"
            "<<<REPLACEMENT>>>\n"
            "<replacement source>\n"
            "<<<END_REPLACEMENT>>>"
        ),
        user_prompt=(
            f"File: {path}\n"
            f"Syntax failure: {syntax_message}\n"
            f"Replace exactly lines {start_line}-{end_line}. Nearby source:\n"
            f"{numbered_context}\n\n"
            "Return only a syntactically valid replacement for the specified lines. "
            "Keep every unrelated line unchanged."
        ),
        response_format="",
        metadata=metadata,
        num_predict=min(int(base_stage.num_predict), 1200),
    )
    return stage, start_line, end_line


def _apply_syntax_region_repair(
    source: str,
    response: str,
    *,
    start_line: int,
    end_line: int,
) -> tuple[str, list[str]]:
    """Apply one explicitly bounded syntax replacement without replacing a file."""

    response_text = str(response or "").strip()
    outer_fence = re.fullmatch(
        r"```(?:python|py)?\s*\r?\n?(.*?)\r?\n?```",
        response_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if outer_fence:
        response_text = outer_fence.group(1).strip("\r\n")
    marker_match = re.search(
        r"<<<REPLACEMENT>>>\s*\r?\n?(.*?)\r?\n?<<<END_REPLACEMENT>>>",
        response_text,
        flags=re.DOTALL,
    )
    replacement = (
        marker_match.group(1)
        if marker_match
        else response_text
    ).strip("\r\n")
    inner_fence = re.fullmatch(
        r"```(?:python|py)?\s*\r?\n?(.*?)\r?\n?```",
        replacement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if inner_fence:
        replacement = inner_fence.group(1).strip("\r\n")
    source_lines = source.splitlines()
    if not source_lines or start_line < 1 or end_line > len(source_lines):
        return source, ["Syntax-region repair boundaries are outside the source."]
    replacement_lines = replacement.splitlines()
    replaced_line_count = end_line - start_line + 1
    if len(replacement_lines) > replaced_line_count + 12:
        return source, [
            "Syntax-region repair expanded beyond the bounded replacement region."
        ]
    candidate_lines = (
        source_lines[: start_line - 1]
        + replacement_lines
        + source_lines[end_line:]
    )
    candidate = "\n".join(candidate_lines)
    if source.endswith(("\n", "\r")):
        candidate += "\n"
    if candidate == source:
        return source, ["Syntax-region repair returned unchanged source."]
    return candidate, []


def _compact_validation_error_summary(errors: list[str]) -> str:
    """Return bounded repair evidence suitable for live workflow status."""

    summaries: list[str] = []
    for error in errors:
        text = str(error or "").strip()
        if not text:
            continue
        if "Disposable generated-patch validation failed:" in text:
            failure_blocks = re.findall(
                r"(?:ERROR|FAIL): ([^\n]+)\n-+\n(.*?)(?="
                r"\n=+\n(?:ERROR|FAIL): |\n-+\nRan |\Z)",
                text,
                flags=re.DOTALL,
            )
            for test_case, failure_body in failure_blocks:
                body_lines = failure_body.splitlines()
                exception_index = next(
                    (
                        index
                        for index in range(len(body_lines) - 1, -1, -1)
                        if re.match(
                            r"^(?:AssertionError|AttributeError|TypeError|ValueError|"
                            r"RuntimeError|FileNotFoundError|FrozenInstanceError|"
                            r"[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\s*:",
                            body_lines[index].strip(),
                        )
                    ),
                    -1,
                )
                if exception_index >= 0:
                    evidence_lines = [
                        line.strip()
                        for line in body_lines[
                            exception_index:min(len(body_lines), exception_index + 6)
                        ]
                        if line.strip()
                    ]
                    exception_evidence = " / ".join(evidence_lines)
                else:
                    exception_evidence = "runtime assertion failed"
                summary = f"{test_case.strip()}: {exception_evidence}"
                if summary not in summaries:
                    summaries.append(summary)
                if len(summaries) == 4:
                    break
        else:
            summary = text.splitlines()[0]
            if summary not in summaries:
                summaries.append(summary)
        if len(summaries) == 4:
            break
    return " | ".join(summary[:700] for summary in summaries)


def _callable_failure_evidence(
    errors: list[str],
    symbol: str,
) -> list[str]:
    """Return only validation evidence attributable to one callable owner."""

    owner = str(symbol or "")
    callable_name = owner.rsplit(".", 1)[-1]
    exact_owned = [
        str(value)
        for value in errors
        if str(value).strip()
        and (
            f"[owner:{owner}]" in str(value)
            or f"[owner:{callable_name}]" in str(value)
            or owner in str(value)
            or re.search(
                rf"\b{re.escape(callable_name)}\b",
                str(value),
            )
        )
    ]
    return exact_owned or [str(value) for value in errors if str(value).strip()]


def _contract_error_is_owned_by_other_callable(
    error: str,
    target_symbol: str,
) -> bool:
    """Return whether a contract error explicitly names a different callable."""

    owners = set(re.findall(
        r"(?:\[owner:|\.py:)([A-Za-z_][A-Za-z0-9_.]*)(?::|\])",
        str(error or ""),
    ))
    if not owners:
        return False
    target = str(target_symbol or "")
    target_name = target.rsplit(".", 1)[-1]
    return all(
        owner not in {target, target_name}
        for owner in owners
    )


def _behavioral_owner_repair_targets(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    objective: str,
) -> list[dict[str, str]]:
    """Resolve only explicit validator-owned behavioral repair targets."""

    del objective
    owner_rows: list[tuple[str, set[str]]] = []
    for error in errors:
        matching_paths = {
            path
            for path, _original, _source in generated_files
            if path in error or Path(path).name in error
        }
        owner_rows.extend(
            (marker, matching_paths)
            for marker in re.findall(
                r"\[owner:([A-Za-z_][A-Za-z0-9_.]*)\]",
                error,
            )
        )
    if not owner_rows:
        return []
    module_scoped = any("[scope:module]" in error for error in errors)
    targets: list[dict[str, str]] = []
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for marker, marker_paths in owner_rows:
            if marker_paths and path not in marker_paths:
                continue
            parts = marker.split(".", 1)
            if len(parts) == 1:
                if any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == marker
                    for node in tree.body
                ):
                    targets.append({"path": path, "symbol": marker})
                if not module_scoped:
                    for node in tree.body:
                        if not isinstance(node, ast.ClassDef):
                            continue
                        if any(
                            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and child.name == marker
                            for child in node.body
                        ):
                            targets.append({
                                "path": path,
                                "symbol": f"{node.name}.{marker}",
                            })
                continue
            class_name, callable_name = parts
            if any(
                isinstance(node, ast.ClassDef)
                and node.name == class_name
                and any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == callable_name
                    for child in node.body
                )
                for node in tree.body
            ):
                targets.append({"path": path, "symbol": marker})
    return list({
        (target["path"], target["symbol"]): target
        for target in targets
    }.values())


def _build_behavioral_owner_resolution_stage(
    generated_files: list[tuple[str, str, str]],
    candidates: list[dict[str, str]],
    errors: list[str],
    objective: str,
) -> ProjectEditPromptStage:
    rows: list[dict[str, str]] = []
    source_by_path = {
        path: source for path, _original, source in generated_files
    }
    for index, candidate in enumerate(candidates, start=1):
        path = str(candidate.get("path") or "")
        symbol = str(candidate.get("symbol") or "")
        source = source_by_path.get(path, "")
        signature = ""
        callable_source = ""
        try:
            tree = ast.parse(source, filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                owner = next(
                    (
                        parent.name
                        for parent in tree.body
                        if isinstance(parent, ast.ClassDef) and node in parent.body
                    ),
                    "",
                )
                qualified = f"{owner}.{node.name}" if owner else node.name
                if qualified == symbol:
                    callable_source = ast.unparse(node)
                    signature = (
                        ("async " if isinstance(node, ast.AsyncFunctionDef) else "")
                        + f"def {node.name}({ast.unparse(node.args)})"
                    )
                    break
        except SyntaxError:
            pass
        rows.append({
            "candidate_id": f"C{index}",
            "path": path,
            "symbol": symbol,
            "signature": signature,
            "source": callable_source,
        })
    return ProjectEditPromptStage(
        key="behavioral_owner_resolution",
        label="Resolving ambiguous repair owner",
        system_prompt=(
            "Select the single repair owner best supported by the supplied failure "
            "evidence. Return JSON only. candidate_id must be one supplied ID; never "
            "invent a path or symbol."
        ),
        user_prompt=(
            "Original objective:\n"
            + objective
            + "\n\nValidation evidence:\n- "
            + "\n- ".join(errors)
            + "\n\nAST-proven candidates:\n"
            + json.dumps(rows, indent=2)
        ),
        model_tier="local_code",
        num_ctx=3072,
        num_predict=220,
        timeout=45,
        no_progress_seconds=20,
        prefer_coder=True,
        coder_preference="fast",
        response_format={
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string"},
                "evidence": {"type": "string"},
            },
            "required": ["candidate_id", "evidence"],
            "additionalProperties": False,
        },
        metadata={"candidates": rows, "disable_thinking": True},
    )


def _parse_behavioral_owner_resolution(
    response: str,
    candidates: list[dict[str, str]],
) -> dict[str, str] | None:
    try:
        payload = json.loads(str(response or ""))
    except (TypeError, ValueError):
        return None
    candidate_id = str(payload.get("candidate_id") or "")
    if not re.fullmatch(r"C[1-9][0-9]*", candidate_id):
        return None
    index = int(candidate_id[1:]) - 1
    if index < 0 or index >= len(candidates):
        return None
    return dict(candidates[index])


def _build_runtime_snapshot_repair_stage(
    generated_files: list[tuple[str, str, str]],
    candidates: list[dict[str, str]],
    errors: list[str],
    objective: str,
    implementation_plan: dict[str, Any],
) -> tuple[
    ProjectEditPromptStage,
    dict[str, dict[str, str]],
    set[str],
]:
    """Build one causal-owner analysis for a complete runtime snapshot."""

    source_by_path = {
        str(path): source for path, _original, source in generated_files
    }
    rows: list[dict[str, str]] = []
    candidate_by_id: dict[str, dict[str, str]] = {}
    for index, candidate in enumerate(candidates, start=1):
        path = str(candidate.get("path") or "")
        symbol = str(candidate.get("symbol") or "")
        callable_source = ""
        try:
            tree = ast.parse(source_by_path.get(path, ""), filename=path)
            owner_name, separator, callable_name = symbol.partition(".")
            for node in tree.body:
                if separator and isinstance(node, ast.ClassDef):
                    if node.name != owner_name:
                        continue
                    member = next(
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
                    if member is not None:
                        callable_source = ast.unparse(member)
                        break
                elif (
                    not separator
                    and isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and node.name == owner_name
                ):
                    callable_source = ast.unparse(node)
                    break
        except SyntaxError:
            pass
        candidate_id = f"C{index}"
        rows.append({
            "candidate_id": candidate_id,
            "path": path,
            "symbol": symbol,
            "kind": (
                "test"
                if Path(path).name.startswith("test_")
                else (
                    "verification"
                    if re.search(r"(?m)^\s*assert\b", callable_source)
                    else "production"
                )
            ),
            "source": callable_source,
            "causal_evidence": str(
                candidate.get("causal_evidence") or ""
            ),
        })
        candidate_by_id[candidate_id] = {
            "path": path,
            "symbol": symbol,
            "source": callable_source,
        }
    failure_cases: list[dict[str, str]] = []
    for row in rows:
        if row["kind"] not in {"test", "verification"}:
            continue
        evidence = _callable_failure_evidence(errors, row["symbol"])
        if not evidence:
            continue
        failure_cases.append({
            "failure_id": f"F{len(failure_cases) + 1}",
            "test_candidate_id": row["candidate_id"],
            "test_symbol": row["symbol"],
            "runtime_evidence": "\n".join(evidence),
        })
    if not failure_cases and errors:
        failure_cases.append({
            "failure_id": "F1",
            "test_candidate_id": "",
            "test_symbol": "<module runtime>",
            "runtime_evidence": "\n".join(
                str(error) for error in errors
            ),
        })
    authoritative_oracles = [
        str(check)
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, dict)
        for validation_case in chunk.get("validation_cases") or []
        if isinstance(validation_case, dict)
        for check in validation_case.get("checks") or []
        if str(check).strip()
    ]
    stage = ProjectEditPromptStage(
        key="runtime_snapshot_repair_analysis",
        label="Resolving all runtime repair owners",
        system_prompt=(
            "/no_think\n"
            "You are a senior debugging lead. Analyze the complete validation "
            "snapshot before code is edited. Select only a supplied candidate ID. "
            "The original request and approved plan are authoritative. Assign every "
            "failure ID exactly once and return JSON only."
        ),
        user_prompt=(
            "Original request:\n"
            + objective
            + "\n\nAuthoritative validation oracles:\n- "
            + "\n- ".join(authoritative_oracles)
            + "\n\nFailing cases:\n"
            + json.dumps(failure_cases, ensure_ascii=True)
            + "\n\nAST-proven candidates:\n"
            + json.dumps(rows, ensure_ascii=True)
            + """

Return only this JSON shape:
{"repairs":[{"failure_ids":["F1"],"candidate_id":"C1","replacement":"def exact_name(...):\n    complete corrected body"}]}

Select the smallest proven owner for every failing behavior. Independent failures
may select different owners and must be returned in the same response. Do not
select a callable whose current source already satisfies the requirement.
Choose production only when its body contradicts the approved requirement.
Choose the test when its setup or expected value contradicts the requirement.
Trace the test's calls and compare their current bodies before choosing.
Candidate causal evidence is AST-derived observation evidence, but the approved
requirement remains authoritative when deciding whether production or its
verification expectation is stale. The replacement must directly correct the
named stale state or result relationship; formatting,
docstring, and commentary changes do not repair runtime behavior.

Threshold-N tests must perform N required operations before expecting the
transition. Sleeping never advances a constant injected clock. State-dependent
exception tests must establish that state through public setup. A success/reset
operation must satisfy its requirement from every reachable state covered by
the contract.

When runtime evidence says a mock was expected once but was called zero times,
identify the approved public operation that emits that callback and invoke that
operation after arranging its required state and before the assertion. Merely
advancing a clock does not execute the operation. Returning the unchanged
verification function is always invalid.

Calculate configured literal values and count actual setup calls. A failing
assertion is observed evidence, not contract evidence. `replacement` must contain
exactly one complete raw replacement function or method with the selected
candidate's existing signature, no class, fence, diff, explanation, ellipsis, or
placeholder. It must be materially different and directly fix this behavior.
For `assert not receiver.method(key)`, AssertionError proves the call returned a
truthy value. If the approved contract defines that boolean as whether the key or
item existed and the fixture constructed or added that exact key without removing
it, production is correct: remove the stale negation in the verification owner.
Apply the inverse reasoning to a positive boolean assertion only when setup and
the approved return contract prove the item is absent. Never change correct
production behavior to preserve a contradictory assertion polarity.
When an iterator terminates after values were accumulated for a partial result,
preserve and emit that partial result before ending iteration. In Python, bool is
a subclass of int; when booleans are explicitly invalid, reject bool before or
alongside the integer validation.
"""
        ),
        model_tier="local_semantic_verify",
        num_ctx=6144,
        num_predict=1800,
        timeout=90,
        no_progress_seconds=30,
        prefer_coder=True,
        coder_preference="standard",
        response_format="",
        metadata={
            "candidates": rows,
            "all_validation_errors": list(errors),
            "full_objective": str(objective or ""),
            "expected_failure_ids": sorted(
                failure_case["failure_id"] for failure_case in failure_cases
            ),
        },
    )
    return stage, candidate_by_id, {
        failure_case["failure_id"] for failure_case in failure_cases
    }


def _repair_stale_boolean_existence_assertion(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], str]:
    """Remove a negation contradicted by a proven existence-return contract."""

    diagnostics = "\n".join(str(error) for error in errors)
    frames = re.findall(
        r'File "([^"]+)", line (\d+), in '
        r"([A-Za-z_][A-Za-z0-9_]*)",
        diagnostics,
    )
    if not frames or "AssertionError" not in diagnostics:
        return generated_files, ""
    failure_path, failure_line_text, failure_callable = frames[-1]
    failure_line = int(failure_line_text)
    for path, _original, source in generated_files:
        if Path(path).name.casefold() != Path(failure_path).name.casefold():
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        verification = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == failure_callable
                and node.lineno <= failure_line
                <= getattr(node, "end_lineno", node.lineno)
            ),
            None,
        )
        if verification is None:
            continue
        failing_assert = next(
            (
                node
                for node in ast.walk(verification)
                if isinstance(node, ast.Assert)
                and node.lineno <= failure_line
                <= getattr(node, "end_lineno", node.lineno)
            ),
            None,
        )
        if failing_assert is None:
            continue
        negated = (
            isinstance(failing_assert.test, ast.UnaryOp)
            and isinstance(failing_assert.test.op, ast.Not)
            and isinstance(failing_assert.test.operand, ast.Call)
        )
        positive = isinstance(failing_assert.test, ast.Call)
        if not negated and not positive:
            continue
        call = (
            failing_assert.test.operand
            if negated
            else failing_assert.test
        )
        if (
            not isinstance(call.func, ast.Attribute)
            or not isinstance(call.func.value, ast.Name)
            or len(call.args) != 1
            or not isinstance(call.args[0], ast.Constant)
        ):
            continue
        receiver_name = call.func.value.id
        method_name = call.func.attr
        key_value = call.args[0].value
        if not re.search(
            rf"\b{re.escape(method_name)}\s*\([^)]*\)\s*->\s*bool\b"
            r"[^.;\n]{0,120}\breturns?\s+whether\b"
            r"[^.;\n]{0,80}\bexist(?:s|ed)?\b",
            request_prompt,
            flags=re.IGNORECASE,
        ):
            continue
        constructor = next(
            (
                statement.value
                for statement in reversed(verification.body)
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                and getattr(statement, "lineno", failure_line) < failure_line
                and any(
                    isinstance(target, ast.Name)
                    and target.id == receiver_name
                    for target in (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                )
                and isinstance(statement.value, ast.Call)
                and statement.value.args
                and isinstance(statement.value.args[0], ast.Dict)
            ),
            None,
        )
        if constructor is None:
            continue
        initial_mapping = constructor.args[0]
        key_exists = any(
            isinstance(key, ast.Constant) and key.value == key_value
            for key in initial_mapping.keys
        )
        invalidating_call = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == receiver_name
            and node.func.attr
            in {method_name, "clear", "delete", "discard", "pop", "remove"}
            and getattr(node, "lineno", failure_line) < failure_line
            for node in ast.walk(verification)
        )
        if negated:
            if not key_exists or invalidating_call:
                continue
            failing_assert.test = call
            repair_description = (
                f"removed one stale negation from the existence assertion for "
                f"`{method_name}`"
            )
        else:
            if key_exists:
                continue
            replacement_key = next(
                (
                    key.value
                    for key in initial_mapping.keys
                    if isinstance(key, ast.Constant)
                    and not any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == receiver_name
                        and node.func.attr
                        in {method_name, "delete", "discard", "pop", "remove"}
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == key.value
                        and getattr(node, "lineno", failure_line) < failure_line
                        for node in ast.walk(verification)
                    )
                ),
                None,
            )
            if replacement_key is None:
                continue
            call.args[0] = ast.copy_location(
                ast.Constant(value=replacement_key),
                call.args[0],
            )
            repair_description = (
                f"replaced one absent fixture key with an existing key in the "
                f"positive `{method_name}` assertion"
            )
        ast.fix_missing_locations(verification)
        repair_symbol = failure_callable
        parent_class = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and verification in node.body
            ),
            None,
        )
        if parent_class is not None:
            repair_symbol = f"{parent_class.name}.{failure_callable}"
        updated, splice_errors = apply_project_edit_generated_symbol_repair(
            generated_files,
            path=path,
            symbol=repair_symbol,
            replacement_response=ast.unparse(verification),
            forbidden_names=[],
        )
        if not splice_errors and updated != generated_files:
            return (
                updated,
                f"{Path(path).name}:{failure_callable} {repair_description}",
            )
    return generated_files, ""


def _repair_called_approved_property(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    implementation_plan: dict[str, Any],
) -> tuple[list[tuple[str, str, str]], str]:
    """Replace a zero-argument call to an approved property in verification."""

    approved_properties = {
        str(property_name)
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, dict)
        for property_name in (
            (chunk.get("declaration_contract") or {}).get("properties") or []
        )
        if str(property_name)
    }
    diagnostics = "\n".join(str(error) for error in errors)
    frames = re.findall(
        r'File "([^"]+)", line (\d+), in '
        r"([A-Za-z_][A-Za-z0-9_]*)",
        diagnostics,
    )
    if (
        not approved_properties
        or not frames
        or "object is not callable" not in diagnostics
    ):
        return validation_files, ""
    failure_path, failure_line_text, failure_callable = frames[-1]
    failure_line = int(failure_line_text)
    for path, _original, source in validation_files:
        if Path(path).name.casefold() != Path(failure_path).name.casefold():
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        callable_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
        callable_symbol = ""
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == failure_callable
            ):
                callable_node = node
                callable_symbol = node.name
                break
            if isinstance(node, ast.ClassDef):
                member = next(
                    (
                        child
                        for child in node.body
                        if isinstance(
                            child,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and child.name == failure_callable
                    ),
                    None,
                )
                if member is not None:
                    callable_node = member
                    callable_symbol = f"{node.name}.{member.name}"
                    break
        if callable_node is None:
            continue

        class PropertyCallRepair(ast.NodeTransformer):
            changed = False

            def visit_Call(self, node: ast.Call) -> ast.AST:
                node = self.generic_visit(node)
                if (
                    node.lineno <= failure_line
                    <= getattr(node, "end_lineno", node.lineno)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in approved_properties
                    and not node.args
                    and not node.keywords
                ):
                    self.changed = True
                    return ast.copy_location(node.func, node)
                return node

        transformer = PropertyCallRepair()
        transformed = transformer.visit(callable_node)
        if not transformer.changed:
            continue
        ast.fix_missing_locations(transformed)
        updated, splice_errors = apply_project_edit_generated_symbol_repair(
            validation_files,
            path=path,
            symbol=callable_symbol,
            replacement_response=ast.unparse(transformed),
            forbidden_names=[],
        )
        if not splice_errors and updated != validation_files:
            return (
                updated,
                f"{Path(path).name}:{callable_symbol} replaced one call to "
                "an approved property with property access",
            )
    return validation_files, ""


def _repair_stale_longest_prefix_expectation(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], str]:
    """Repair a literal lookup expectation from a longest-prefix contract."""

    diagnostics = "\n".join(str(error) for error in errors)
    frames = re.findall(
        r'File "([^"]+)", line (\d+), in '
        r"([A-Za-z_][A-Za-z0-9_]*)",
        diagnostics,
    )
    if (
        "AssertionError" not in diagnostics
        or not re.search(
            r"\blongest\s+matching\s+prefix\b",
            request_prompt,
            flags=re.IGNORECASE,
        )
    ):
        return generated_files, ""
    failure_path = ""
    failure_line = 0
    failure_callable = ""
    expected_literal: Any = None
    expected_literal_is_known = False
    if frames:
        failure_path, failure_line_text, failure_callable = frames[-1]
        failure_line = int(failure_line_text)
    else:
        callable_match = re.search(
            r"\b(test_[A-Za-z_][A-Za-z0-9_]*)\s+\(",
            diagnostics,
        )
        literal_match = re.search(
            r"!=\s*(?P<literal>'[^'\n]*'|\"[^\"\n]*\"|"
            r"-?\d+(?:\.\d+)?|True|False|None)",
            diagnostics,
        )
        if callable_match is None or literal_match is None:
            return generated_files, ""
        failure_callable = callable_match.group(1)
        try:
            expected_literal = ast.literal_eval(literal_match.group("literal"))
            expected_literal_is_known = True
        except (SyntaxError, ValueError):
            return generated_files, ""
    for path, _original, source in generated_files:
        if (
            failure_path
            and Path(path).name.casefold() != Path(failure_path).name.casefold()
        ):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        verification = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == failure_callable
                and (
                    not failure_line
                    or node.lineno <= failure_line
                    <= getattr(node, "end_lineno", node.lineno)
                )
            ),
            None,
        )
        if verification is not None and not failure_line:
            matching_assertions = [
                node
                for node in ast.walk(verification)
                if isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "assertEqual"
                and len(node.value.args) >= 2
                and isinstance(node.value.args[0], ast.Call)
                and isinstance(node.value.args[1], ast.Constant)
                and expected_literal_is_known
                and node.value.args[1].value == expected_literal
            ]
            if len(matching_assertions) != 1:
                continue
            failure_line = matching_assertions[0].lineno
        failing_assert = next(
            (
                node
                for node in ast.walk(verification)
                if isinstance(node, ast.Assert)
                and node.lineno <= failure_line
                <= getattr(node, "end_lineno", node.lineno)
            ),
            None,
        ) if verification is not None else None
        lookup_call: ast.Call | None = None
        expected_node: ast.Constant | None = None
        if (
            failing_assert is not None
            and isinstance(failing_assert.test, ast.Compare)
            and len(failing_assert.test.ops) == 1
            and isinstance(failing_assert.test.ops[0], ast.Eq)
            and len(failing_assert.test.comparators) == 1
            and isinstance(failing_assert.test.comparators[0], ast.Constant)
            and isinstance(failing_assert.test.left, ast.Call)
        ):
            lookup_call = failing_assert.test.left
            expected_node = failing_assert.test.comparators[0]
        if lookup_call is None and verification is not None:
            failing_assert_equal = next(
                (
                    node.value
                    for node in ast.walk(verification)
                    if isinstance(node, ast.Expr)
                    and node.lineno <= failure_line
                    <= getattr(node, "end_lineno", node.lineno)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "assertEqual"
                    and len(node.value.args) >= 2
                    and isinstance(node.value.args[0], ast.Call)
                    and isinstance(node.value.args[1], ast.Constant)
                ),
                None,
            )
            if failing_assert_equal is not None:
                lookup_call = failing_assert_equal.args[0]
                expected_node = failing_assert_equal.args[1]
        if verification is None or lookup_call is None or expected_node is None:
            continue
        if (
            not isinstance(lookup_call.func, ast.Attribute)
            or not isinstance(lookup_call.func.value, ast.Name)
            or len(lookup_call.args) != 1
            or not isinstance(lookup_call.args[0], ast.Constant)
            or not isinstance(lookup_call.args[0].value, str)
        ):
            continue
        receiver_name = lookup_call.func.value.id
        method_name = lookup_call.func.attr
        lookup_value = lookup_call.args[0].value
        if not re.search(
            rf"\b{re.escape(method_name)}\s*\([^)]*\)"
            r"[^.;\n]{0,160}\blongest\s+matching\s+prefix\b",
            request_prompt,
            flags=re.IGNORECASE,
        ):
            continue
        constructor = next(
            (
                statement.value
                for statement in reversed(verification.body)
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                and getattr(statement, "lineno", failure_line) < failure_line
                and any(
                    isinstance(target, ast.Name)
                    and target.id == receiver_name
                    for target in (
                        statement.targets
                        if isinstance(statement, ast.Assign)
                        else [statement.target]
                    )
                )
                and isinstance(statement.value, ast.Call)
                and statement.value.args
                and isinstance(statement.value.args[0], ast.Dict)
            ),
            None,
        )
        if constructor is None:
            continue
        literal_routes = [
            (key.value, value.value)
            for key, value in zip(
                constructor.args[0].keys,
                constructor.args[0].values,
            )
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and isinstance(value, ast.Constant)
        ]
        matches = [
            (prefix, target)
            for prefix, target in literal_routes
            if lookup_value.startswith(prefix)
        ]
        if not matches:
            continue
        expected_target = max(matches, key=lambda item: len(item[0]))[1]
        current_expected = expected_node.value
        if current_expected == expected_target:
            continue
        replacement_expected = ast.copy_location(
            ast.Constant(value=expected_target),
            expected_node,
        )
        if failing_assert is not None:
            failing_assert.test.comparators[0] = replacement_expected
        else:
            failing_assert_equal.args[1] = replacement_expected
        ast.fix_missing_locations(verification)
        repair_symbol = failure_callable
        parent_class = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and verification in node.body
            ),
            None,
        )
        if parent_class is not None:
            repair_symbol = f"{parent_class.name}.{failure_callable}"
        updated, splice_errors = apply_project_edit_generated_symbol_repair(
            generated_files,
            path=path,
            symbol=repair_symbol,
            replacement_response=ast.unparse(verification),
            forbidden_names=[],
        )
        if not splice_errors and updated != generated_files:
            return (
                updated,
                f"{Path(path).name}:{repair_symbol} replaced one stale "
                "literal expectation using the approved longest-prefix rule",
            )
    return generated_files, ""


def _repair_uninvoked_mock_callback(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], str]:
    """Invoke an AST-proven callback emitter before a zero-call mock assertion."""

    diagnostics = "\n".join(str(error) for error in errors)
    if not re.search(
        r"Expected ['\"]?mock['\"]? to be called once\. Called 0 times\.",
        diagnostics,
        flags=re.IGNORECASE,
    ):
        return generated_files, ""

    updated = list(generated_files)
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        callback_emitters: dict[str, dict[int, str]] = {}
        for class_name, class_node in classes.items():
            initializer = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "__init__"
                ),
                None,
            )
            if initializer is None:
                continue
            parameters = [
                argument.arg
                for argument in initializer.args.args
                if argument.arg != "self"
            ]
            callback_attributes: dict[int, str] = {}
            for assignment in ast.walk(initializer):
                if not isinstance(assignment, ast.Assign):
                    continue
                if not isinstance(assignment.value, ast.Name):
                    continue
                if assignment.value.id not in parameters:
                    continue
                parameter_index = parameters.index(assignment.value.id)
                for target in assignment.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and "callback" in target.attr.casefold()
                    ):
                        callback_attributes[parameter_index] = target.attr
            emitter_by_parameter: dict[int, str] = {}
            for parameter_index, attribute_name in callback_attributes.items():
                for method in class_node.body:
                    if (
                        not isinstance(method, ast.FunctionDef)
                        or method.name == "__init__"
                    ):
                        continue
                    if any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                        and call.func.attr == attribute_name
                        for call in ast.walk(method)
                    ):
                        emitter_by_parameter[parameter_index] = method.name
                        break
            if emitter_by_parameter:
                callback_emitters[class_name] = emitter_by_parameter

        for verification in [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(child, ast.Assert)
                or (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr.startswith("assert_called")
                )
                for child in ast.walk(node)
            )
        ]:
            callback_names = {
                target.id
                for statement in verification.body
                if isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Call)
                and (
                    isinstance(statement.value.func, ast.Name)
                    and statement.value.func.id in {"Mock", "MagicMock"}
                )
                for target in statement.targets
                if isinstance(target, ast.Name)
            }
            if not callback_names:
                continue
            instance_candidates: list[tuple[int, str, str]] = []
            for statement_index, statement in enumerate(verification.body):
                if (
                    not isinstance(statement, ast.Assign)
                    or len(statement.targets) != 1
                    or not isinstance(statement.targets[0], ast.Name)
                    or not isinstance(statement.value, ast.Call)
                    or not isinstance(statement.value.func, ast.Name)
                    or statement.value.func.id not in callback_emitters
                ):
                    continue
                class_name = statement.value.func.id
                for parameter_index, emitter_name in callback_emitters[
                    class_name
                ].items():
                    callback_argument = (
                        statement.value.args[parameter_index]
                        if parameter_index < len(statement.value.args)
                        else None
                    )
                    if (
                        isinstance(callback_argument, ast.Name)
                        and callback_argument.id in callback_names
                    ):
                        instance_candidates.append(
                            (
                                statement_index,
                                statement.targets[0].id,
                                emitter_name,
                            )
                        )
            for assertion_index, statement in enumerate(verification.body):
                if (
                    not isinstance(statement, ast.Expr)
                    or not isinstance(statement.value, ast.Call)
                    or not isinstance(statement.value.func, ast.Attribute)
                    or not statement.value.func.attr.startswith("assert_called")
                    or not isinstance(statement.value.func.value, ast.Name)
                    or statement.value.func.value.id not in callback_names
                ):
                    continue
                preceding = [
                    candidate
                    for candidate in instance_candidates
                    if candidate[0] < assertion_index
                ]
                if not preceding:
                    continue
                instance_index, instance_name, emitter_name = preceding[-1]
                already_called = any(
                    isinstance(candidate_statement, ast.Expr)
                    and isinstance(candidate_statement.value, ast.Call)
                    and isinstance(
                        candidate_statement.value.func,
                        ast.Attribute,
                    )
                    and isinstance(
                        candidate_statement.value.func.value,
                        ast.Name,
                    )
                    and candidate_statement.value.func.value.id == instance_name
                    and candidate_statement.value.func.attr == emitter_name
                    for candidate_statement in verification.body[
                        instance_index + 1:assertion_index
                    ]
                )
                if already_called:
                    continue
                source_lines = source.splitlines(keepends=True)
                insertion_line = statement.lineno - 1
                indentation = re.match(
                    r"\s*",
                    source_lines[insertion_line],
                ).group(0)
                source_lines.insert(
                    insertion_line,
                    f"{indentation}{instance_name}.{emitter_name}()\n",
                )
                repaired_source = "".join(source_lines)
                try:
                    compile(
                        ast.parse(repaired_source, filename=path),
                        path,
                        "exec",
                    )
                except (SyntaxError, ValueError):
                    return generated_files, ""
                updated[file_index] = (path, original, repaired_source)
                return (
                    updated,
                    f"{Path(path).name}:{verification.name} invoked the "
                    f"AST-proven callback emitter {instance_name}."
                    f"{emitter_name} before its mock assertion",
                )
    return generated_files, ""


def _repair_insufficient_fake_clock_advance(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], str]:
    """Raise a literal fake-clock advance proven too small for expected items."""

    diagnostics = "\n".join(str(error) for error in errors)
    if "AssertionError" not in diagnostics:
        return generated_files, ""
    updated = list(generated_files)
    for file_index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for verification in [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        ]:
            body = verification.body
            for assertion_index, statement in enumerate(body):
                if (
                    not isinstance(statement, ast.Assert)
                    or not isinstance(statement.test, ast.Compare)
                    or len(statement.test.ops) != 1
                    or not isinstance(statement.test.ops[0], ast.Eq)
                    or len(statement.test.comparators) != 1
                    or not isinstance(
                        statement.test.comparators[0],
                        (ast.List, ast.Tuple),
                    )
                ):
                    continue
                result_call = next(
                    (
                        node
                        for node in ast.walk(statement.test.left)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                    ),
                    None,
                )
                if result_call is None:
                    continue
                expected_values = {
                    ast.literal_eval(element)
                    for element in statement.test.comparators[0].elts
                    if isinstance(element, ast.Constant)
                }
                if not expected_values:
                    continue
                instance_name = result_call.func.value.id
                instance_assignments = [
                    (index, candidate)
                    for index, candidate in enumerate(body[:assertion_index])
                    if isinstance(candidate, ast.Assign)
                    and len(candidate.targets) == 1
                    and isinstance(candidate.targets[0], ast.Name)
                    and candidate.targets[0].id == instance_name
                    and isinstance(candidate.value, ast.Call)
                ]
                if not instance_assignments:
                    continue
                instance_index, instance_assignment = instance_assignments[-1]
                if (
                    not instance_assignment.value.args
                    or not isinstance(
                        instance_assignment.value.args[0],
                        ast.Name,
                    )
                ):
                    continue
                clock_name = instance_assignment.value.args[0].id
                required_delays: list[float] = []
                for candidate in body[
                    instance_index + 1:assertion_index
                ]:
                    if (
                        not isinstance(candidate, ast.Expr)
                        or not isinstance(candidate.value, ast.Call)
                        or not isinstance(
                            candidate.value.func,
                            ast.Attribute,
                        )
                        or not isinstance(
                            candidate.value.func.value,
                            ast.Name,
                        )
                        or candidate.value.func.value.id != instance_name
                        or len(candidate.value.args) < 2
                        or not isinstance(
                            candidate.value.args[0],
                            ast.Constant,
                        )
                        or candidate.value.args[0].value
                        not in expected_values
                        or not isinstance(
                            candidate.value.args[1],
                            ast.Constant,
                        )
                        or not isinstance(
                            candidate.value.args[1].value,
                            (int, float),
                        )
                    ):
                        continue
                    required_delays.append(
                        float(candidate.value.args[1].value)
                    )
                if not required_delays:
                    continue
                required_advance = max(required_delays)
                advance_calls = [
                    candidate.value
                    for candidate in body[
                        instance_index + 1:assertion_index
                    ]
                    if isinstance(candidate, ast.Expr)
                    and isinstance(candidate.value, ast.Call)
                    and isinstance(
                        candidate.value.func,
                        ast.Attribute,
                    )
                    and isinstance(
                        candidate.value.func.value,
                        ast.Name,
                    )
                    and candidate.value.func.value.id == clock_name
                    and candidate.value.func.attr in {
                        "advance",
                        "advance_by",
                    }
                    and candidate.value.args
                    and isinstance(
                        candidate.value.args[0],
                        ast.Constant,
                    )
                    and isinstance(
                        candidate.value.args[0].value,
                        (int, float),
                    )
                ]
                if not advance_calls:
                    source_lines = source.splitlines(keepends=True)
                    assertion_line_index = statement.lineno - 1
                    assertion_line = source_lines[assertion_line_index]
                    indentation = assertion_line[:statement.col_offset]
                    replacement = (
                        str(int(required_advance))
                        if required_advance.is_integer()
                        else repr(required_advance)
                    )
                    source_lines.insert(
                        assertion_line_index,
                        f"{indentation}{clock_name}.advance({replacement})\n",
                    )
                    repaired_source = "".join(source_lines)
                    try:
                        compile(
                            ast.parse(repaired_source, filename=path),
                            path,
                            "exec",
                        )
                    except (SyntaxError, ValueError):
                        return generated_files, ""
                    updated[file_index] = (path, original, repaired_source)
                    return (
                        updated,
                        f"{Path(path).name}:{verification.name} inserted the "
                        f"AST-proven fake-clock advance of {required_advance:g}",
                    )
                advance_call = advance_calls[-1]
                current_advance = float(advance_call.args[0].value)
                if current_advance >= required_advance:
                    continue
                value_node = advance_call.args[0]
                source_lines = source.splitlines(keepends=True)
                line_index = value_node.lineno - 1
                line = source_lines[line_index]
                replacement = (
                    str(int(required_advance))
                    if required_advance.is_integer()
                    else repr(required_advance)
                )
                source_lines[line_index] = (
                    line[:value_node.col_offset]
                    + replacement
                    + line[int(value_node.end_col_offset or value_node.col_offset):]
                )
                repaired_source = "".join(source_lines)
                try:
                    compile(
                        ast.parse(repaired_source, filename=path),
                        path,
                        "exec",
                    )
                except (SyntaxError, ValueError):
                    return generated_files, ""
                updated[file_index] = (path, original, repaired_source)
                return (
                    updated,
                    f"{Path(path).name}:{verification.name} raised the "
                    f"AST-proven fake-clock advance from {current_advance:g} "
                    f"to {required_advance:g}",
                )
    return generated_files, ""


def _parse_runtime_snapshot_repair_analysis(
    response: str,
    candidate_by_id: dict[str, dict[str, str]],
    expected_failure_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Reject incomplete analyses and invented or duplicated repair owners."""

    raw_response = str(response or "").strip()
    raw_response = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        raw_response,
        flags=re.IGNORECASE,
    )
    raw_response = re.sub(r"\s*```\s*$", "", raw_response).strip()
    envelope_match = re.search(
        r"(?s)\A\s*CANDIDATE_ID:\s*([A-Za-z0-9_-]+)[ \t]*\r?\n"
        r"REPLACEMENT:[ \t]*\r?\n(.+?)\s*\Z",
        raw_response,
    )
    if envelope_match:
        payload: Any = {
            "repairs": [{
                "candidate_id": envelope_match.group(1),
                "replacement": envelope_match.group(2),
            }]
        }
    else:
        try:
            payload = json.loads(raw_response)
        except (TypeError, ValueError) as exc:
            return [], [
                "Runtime repair envelope did not parse: "
                f"{exc}; response={raw_response[-1200:]}"
            ]
    if not isinstance(payload, dict):
        return [], ["Runtime repair analysis must be a JSON object."]
    repairs: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    assigned_failure_ids: set[str] = set()
    for index, item in enumerate(payload.get("repairs") or [], start=1):
        if not isinstance(item, dict):
            errors.append(f"Runtime repair item {index} is not an object.")
            continue
        candidate_id = str(item.get("candidate_id") or "")
        candidate = candidate_by_id.get(candidate_id)
        root_cause = "Focused runtime behavior contradicts the approved contract."
        steps = ["Apply the supplied exact callable replacement."]
        postconditions = ["The focused runtime behavior passes its contract check."]
        raw_failure_ids = item.get("failure_ids")
        if isinstance(raw_failure_ids, list):
            failure_ids = {
                str(value) for value in raw_failure_ids if str(value).strip()
            }
        else:
            failure_ids = (
                set(expected_failure_ids)
                if len((payload.get("repairs") or [])) == 1
                else set()
            )
        replacement = str(item.get("replacement") or "").strip()
        replacement = re.sub(
            r"^\s*```(?:python)?\s*",
            "",
            replacement,
            flags=re.IGNORECASE,
        )
        replacement = re.sub(r"\s*```\s*$", "", replacement).strip()
        replacement = re.sub(
            r"^\s*python\s*\r?\n",
            "",
            replacement,
            flags=re.IGNORECASE,
        )
        if (
            "\n" not in replacement
            and "\\n" in replacement
            and re.match(r"^\s*(?:async\s+def|def)\b", replacement)
        ):
            replacement = (
                replacement
                .replace("\\r\\n", "\n")
                .replace("\\n", "\n")
                .replace("\\t", "\t")
            )
        if candidate is None:
            errors.append(
                f"Runtime repair item {index} invented `{candidate_id}`."
            )
            continue
        key = (candidate["path"], candidate["symbol"])
        if key in seen:
            errors.append(
                f"Runtime repair analysis duplicated `{candidate['symbol']}`."
            )
            continue
        invalid_failure_ids = failure_ids - expected_failure_ids
        duplicate_failure_ids = failure_ids & assigned_failure_ids
        if not failure_ids or invalid_failure_ids or duplicate_failure_ids:
            errors.append(
                f"Runtime repair owner `{candidate['symbol']}` has invalid or "
                "duplicate failure ownership."
            )
            continue
        try:
            replacement_tree = ast.parse(replacement)
        except SyntaxError as exc:
            errors.append(
                f"Runtime repair owner `{candidate['symbol']}` returned invalid "
                f"replacement syntax: {exc}."
            )
            continue
        replacement_nodes = [
            node
            for node in replacement_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        callable_name = candidate["symbol"].rsplit(".", 1)[-1]
        if (
            len(replacement_tree.body) != 1
            or len(replacement_nodes) != 1
            or replacement_nodes[0].name != callable_name
        ):
            errors.append(
                f"Runtime repair owner `{candidate['symbol']}` must return exactly "
                "one matching callable replacement."
            )
            continue
        try:
            current_tree = ast.parse(candidate.get("source") or "")
            if ast.dump(current_tree, include_attributes=False) == ast.dump(
                replacement_tree,
                include_attributes=False,
            ):
                errors.append(
                    f"Runtime repair owner `{candidate['symbol']}` returned unchanged "
                    "code."
                )
                continue
        except SyntaxError:
            pass
        seen.add(key)
        assigned_failure_ids.update(failure_ids)
        repairs.append({
            **candidate,
            "root_cause": root_cause,
            "algorithm_steps": steps,
            "postconditions": postconditions,
            "failure_ids": sorted(failure_ids),
            "replacement": replacement,
            "mechanical": False,
        })
    if not repairs:
        errors.append("Runtime repair analysis selected no executable owners.")
    missing_failure_ids = expected_failure_ids - assigned_failure_ids
    if missing_failure_ids:
        errors.append(
            "Runtime repair analysis left failures without a repair owner: "
            + ", ".join(sorted(missing_failure_ids))
        )
    if payload.get("unmapped_failures"):
        errors.append(
            "Runtime repair analysis left failures unmapped: "
            + "; ".join(
                str(value) for value in payload.get("unmapped_failures") or []
            )
        )
    return repairs, errors


def _production_callables_exercised_by_tests(
    generated_files: list[tuple[str, str, str]],
    test_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Resolve production methods reached by failing tests through AST call links."""

    source_by_path = {
        str(path): source for path, _original, source in generated_files
    }
    exercised: set[tuple[str, str]] = set()
    for target in test_targets:
        path = str(target.get("path") or "")
        symbol = str(target.get("symbol") or "")
        try:
            tree = ast.parse(source_by_path.get(path, ""), filename=path)
        except SyntaxError:
            continue
        owner_name, separator, callable_name = symbol.partition(".")
        test_node: ast.AST | None = None
        for node in tree.body:
            if (
                not separator
                and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == owner_name
            ):
                test_node = node
                break
            if separator and isinstance(node, ast.ClassDef) and node.name == owner_name:
                test_node = next(
                    (
                        child
                        for child in node.body
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == callable_name
                    ),
                    None,
                )
                break
        if test_node is None:
            continue
        instance_types: dict[str, str] = {}
        for node in ast.walk(test_node):
            if (
                isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
            ):
                assignment_targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for assignment_target in assignment_targets:
                    if isinstance(assignment_target, ast.Name):
                        instance_types[assignment_target.id] = node.value.func.id
        for node in ast.walk(test_node):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            if not isinstance(receiver, ast.Name):
                continue
            class_name = instance_types.get(receiver.id)
            if class_name:
                exercised.add((class_name, node.func.attr))

    targets: list[dict[str, str]] = []
    for path, _original, source in generated_files:
        if Path(path).name.startswith("test_"):
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if (
                    isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and (node.name, member.name) in exercised
                ):
                    targets.append({
                        "path": str(path),
                        "symbol": f"{node.name}.{member.name}",
                    })
    return targets


def _runtime_assertion_causal_owner_targets(
    generated_files: list[tuple[str, str, str]],
    errors: list[str],
    verification_targets: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Trace a failing assertion's observed value to its production mutator."""

    verification_keys = {
        (
            Path(str(target.get("path") or "")).name.lower(),
            str(target.get("symbol") or "").rsplit(".", 1)[-1],
        )
        for target in verification_targets
    }
    parsed_files: list[tuple[str, ast.Module]] = []
    production_functions: dict[str, dict[str, str]] = {}
    production_function_nodes: dict[
        str,
        ast.FunctionDef | ast.AsyncFunctionDef,
    ] = {}
    production_methods: dict[tuple[str, str], dict[str, str]] = {}
    production_method_nodes: dict[
        tuple[str, str],
        ast.FunctionDef | ast.AsyncFunctionDef,
    ] = {}
    for path, _original, source in generated_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        parsed_files.append((path, tree))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                verification_key = (Path(path).name.lower(), node.name)
                if verification_key not in verification_keys:
                    production_functions[node.name] = {
                        "path": path,
                        "symbol": node.name,
                    }
                    production_function_nodes[node.name] = node
                continue
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    production_methods[(node.name, member.name)] = {
                        "path": path,
                        "symbol": f"{node.name}.{member.name}",
                    }
                    production_method_nodes[(node.name, member.name)] = member

    resolved: list[dict[str, str]] = []
    for error in errors:
        if (
            "Disposable generated-patch validation failed:" not in str(error)
            or "AssertionError" not in str(error)
        ):
            continue
        frames = re.findall(
            r'File "([^"]+)", line (\d+), in '
            r"([A-Za-z_][A-Za-z0-9_]*)",
            str(error),
        )
        if not frames:
            continue
        failure_path, failure_line_text, failure_callable = frames[-1]
        failure_line = int(failure_line_text)
        matching_tree = next(
            (
                (path, tree)
                for path, tree in parsed_files
                if Path(path).name.lower() == Path(failure_path).name.lower()
            ),
            None,
        )
        if matching_tree is None:
            continue
        path, tree = matching_tree
        if (
            Path(path).name.lower(),
            failure_callable,
        ) not in verification_keys:
            continue
        verification = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == failure_callable
                and node.lineno <= failure_line <= getattr(
                    node,
                    "end_lineno",
                    node.lineno,
                )
            ),
            None,
        )
        if verification is None:
            continue
        failing_assert = next(
            (
                node
                for node in ast.walk(verification)
                if isinstance(node, ast.Assert)
                and node.lineno <= failure_line <= getattr(
                    node,
                    "end_lineno",
                    node.lineno,
                )
            ),
            None,
        )
        if failing_assert is None:
            continue

        instance_types: dict[str, str] = {}
        value_origins: dict[str, tuple[str, str, int]] = {}
        for node in ast.walk(verification):
            if getattr(node, "lineno", failure_line + 1) >= failure_line:
                continue
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            assignment_targets = (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            assigned_names = [
                target.id
                for target in assignment_targets
                if isinstance(target, ast.Name)
            ]
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                for assigned_name in assigned_names:
                    instance_types[assigned_name] = value.func.id
                    if value.func.id in production_functions:
                        value_origins[assigned_name] = (
                            "",
                            value.func.id,
                            node.lineno,
                        )
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name)
            ):
                for assigned_name in assigned_names:
                    value_origins[assigned_name] = (
                        value.func.value.id,
                        value.func.attr,
                        node.lineno,
                    )

        zero_result_origins: set[tuple[str, str, int]] = set()
        for node in ast.walk(verification):
            if (
                not isinstance(node, ast.Assert)
                or getattr(node, "lineno", failure_line) >= failure_line
                or not isinstance(node.test, ast.Compare)
                or len(node.test.ops) != 1
                or not isinstance(node.test.ops[0], ast.Eq)
                or len(node.test.comparators) != 1
            ):
                continue
            comparison_values = [node.test.left, node.test.comparators[0]]
            asserts_zero = any(
                isinstance(value, ast.Constant)
                and value.value == 0
                and not isinstance(value.value, bool)
                for value in comparison_values
            )
            if not asserts_zero:
                continue
            for value in comparison_values:
                if isinstance(value, ast.Name):
                    origin = value_origins.get(value.id)
                    if origin is not None:
                        zero_result_origins.add(origin)

        assertion_names = {
            node.id for node in ast.walk(failing_assert) if isinstance(node, ast.Name)
        }
        assertion_receivers = {
            node.value.id
            for node in ast.walk(failing_assert)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
        }
        observed_attributes = sorted({
            f"{node.value.id}.{node.attr}"
            for node in ast.walk(failing_assert)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
        })
        causal_calls: list[tuple[int, str, str]] = []
        for node in ast.walk(failing_assert):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in production_functions:
                    causal_calls.append(
                        (
                            failure_line + 1,
                            "",
                            node.func.id,
                        )
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
            ):
                causal_calls.append(
                    (
                        failure_line + 1,
                        node.func.value.id,
                        node.func.attr,
                    )
                )
        for name in assertion_names:
            origin = value_origins.get(name)
            if origin is not None:
                causal_calls.append((origin[2], origin[0], origin[1]))
        for node in ast.walk(verification):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or not isinstance(node.func.value, ast.Name)
                or getattr(node, "lineno", failure_line) >= failure_line
            ):
                continue
            receiver_name = node.func.value.id
            if receiver_name in assertion_receivers:
                if (
                    receiver_name,
                    node.func.attr,
                    node.lineno,
                ) in zero_result_origins:
                    continue
                causal_calls.append(
                    (node.lineno, receiver_name, node.func.attr)
                )
        for _line, receiver_name, method_name in sorted(
            causal_calls,
            reverse=True,
        ):
            if not receiver_name:
                owner = production_functions.get(method_name)
                if owner is not None:
                    resolved.append({
                        **owner,
                        "observed_attributes": "",
                        "causal_evidence": (
                            f"The failing assertion at line {failure_line} "
                            f"observes the result returned by {method_name}(). "
                            "The assertion remains authoritative unless its "
                            "expectation contradicts the approved requirement. "
                            "Repair the production callable that produced the "
                            "observed value rather than weakening verification."
                        ),
                    })
                    break
                continue
            owner_key = (instance_types.get(receiver_name, ""), method_name)
            owner = production_methods.get(owner_key)
            if owner is not None:
                owner_node = production_method_nodes.get(owner_key)
                mutated_attributes: set[str] = set()
                if owner_node is not None:
                    for node in ast.walk(owner_node):
                        mutation_target: ast.AST | None = None
                        if isinstance(node, ast.Delete):
                            for target in node.targets:
                                if (
                                    isinstance(target, ast.Subscript)
                                    and isinstance(target.value, ast.Attribute)
                                    and isinstance(target.value.value, ast.Name)
                                    and target.value.value.id == "self"
                                ):
                                    mutated_attributes.add(target.value.attr)
                        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                            assignment_targets = (
                                node.targets
                                if isinstance(node, ast.Assign)
                                else [node.target]
                            )
                            for target in assignment_targets:
                                mutation_target = target
                                if (
                                    isinstance(mutation_target, ast.Attribute)
                                    and isinstance(
                                        mutation_target.value,
                                        ast.Name,
                                    )
                                    and mutation_target.value.id == "self"
                                ):
                                    mutated_attributes.add(
                                        mutation_target.attr
                                    )
                        elif (
                            isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and isinstance(node.func.value, ast.Attribute)
                            and isinstance(node.func.value.value, ast.Name)
                            and node.func.value.value.id == "self"
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
                        ):
                            mutated_attributes.add(node.func.value.attr)
                observed_member_attributes = {
                    attribute.split(".", 1)[1]
                    for attribute in observed_attributes
                    if attribute.startswith(f"{receiver_name}.")
                }
                stale_observed_attributes = sorted(
                    observed_member_attributes - mutated_attributes
                )
                mutation_detail = ""
                if stale_observed_attributes:
                    mutation_detail = (
                        " The current method mutates "
                        + (
                            ", ".join(
                                f"self.{name}"
                                for name in sorted(mutated_attributes)
                            )
                            if mutated_attributes
                            else "no persistent instance collection"
                        )
                        + " but never mutates "
                        + ", ".join(
                            f"self.{name}"
                            for name in stale_observed_attributes
                        )
                        + ". Make the successful operation update that observed "
                        "state consistently inside the same predicate/result "
                        "branch."
                    )
                polarity_detail = ""
                if owner_node is not None:
                    for assignment in ast.walk(owner_node):
                        if (
                            not isinstance(assignment, ast.Assign)
                            or len(assignment.targets) != 1
                            or not isinstance(
                                assignment.targets[0],
                                ast.Attribute,
                            )
                            or not isinstance(
                                assignment.targets[0].value,
                                ast.Name,
                            )
                            or assignment.targets[0].value.id != "self"
                            or assignment.targets[0].attr
                            not in observed_member_attributes
                            or not isinstance(assignment.value, ast.ListComp)
                        ):
                            continue
                        for generator in assignment.value.generators:
                            for condition in generator.ifs:
                                if (
                                    isinstance(condition, ast.Compare)
                                    and len(condition.ops) == 1
                                    and isinstance(condition.ops[0], ast.NotIn)
                                    and len(condition.comparators) == 1
                                    and isinstance(
                                        condition.comparators[0],
                                        ast.Attribute,
                                    )
                                    and isinstance(
                                        condition.comparators[0].value,
                                        ast.Name,
                                    )
                                    and condition.comparators[0].value.id
                                    == "self"
                                    and condition.comparators[0].attr
                                    in mutated_attributes
                                ):
                                    polarity_detail = (
                                        " The current post-operation filter keeps "
                                        "an item when it is absent from self."
                                        f"{condition.comparators[0].attr}, but the "
                                        "successful branch first deletes that same "
                                        "item from that collection. This condition "
                                        "therefore preserves the item that should "
                                        "be removed. Remove the predicate-matching "
                                        "item from the observed collection inside "
                                        "the same successful branch instead."
                                    )
                                    break
                resolved.append({
                    **owner,
                    "observed_attributes": ",".join(
                        sorted(observed_member_attributes)
                    ),
                    "causal_evidence": (
                        f"The failing assertion at line {failure_line} observes "
                        f"{', '.join(observed_attributes) or receiver_name} after "
                        f"{receiver_name}.{method_name}() completed. Every earlier "
                        "assertion in this verification invocation passed. Update "
                        "all persistent representations of the affected pending "
                        "state. This proves the observed call relationship only; "
                        "compare the production result and verification expectation "
                        "against the approved requirement before choosing which "
                        "callable is stale."
                        + mutation_detail
                        + polarity_detail
                    ),
                })
                break
    return list({
        (target["path"], target["symbol"]): target
        for target in resolved
    }.values())
