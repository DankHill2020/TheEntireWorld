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

from tech_connector.services.implementation_plan_quality_part_01 import (
    _attribute_contracts,
    _callable_signatures,
    _class_base,
    _mechanics,
    _observable_actions,
    _property_names,
    _propose_cross_file_interfaces,
    _required_method_names,
    _requirement_texts,
    _signal_contracts,
    _validation_cases,
)


def _materialize_threaded_progress_declarations(
    chunk: dict[str, Any],
) -> None:
    """Add declaration surfaces required by an approved threaded progress contract."""

    progress_mechanics = [
        str(step)
        for row in chunk.get("implementation_mechanics") or []
        if isinstance(row, Mapping)
        for step in row.get("steps") or []
        if "worker progress signal" in str(step).casefold()
        or "dialog progress handler" in str(step).casefold()
    ]
    if not progress_mechanics:
        return
    progress_requirement_ids = sorted({
        str(row.get("requirement_id") or "")
        for row in chunk.get("implementation_mechanics") or []
        if isinstance(row, Mapping)
        and any(
            "worker progress signal" in str(step).casefold()
            or "dialog progress handler" in str(step).casefold()
            for step in row.get("steps") or []
        )
        and str(row.get("requirement_id") or "")
    })
    declaration_contract = chunk.setdefault("declaration_contract", {})
    progress_signature = (
        "def _handle_progress(self, current_step: int, "
        "total_steps: int, status: str) -> None"
    )
    callable_signatures = declaration_contract.setdefault(
        "callable_signatures",
        [],
    )
    existing_progress_signature = next(
        (
            str(signature)
            for signature in callable_signatures
            if re.search(
                r"def\s+(?P<name>_[A-Za-z0-9_]*progress[A-Za-z0-9_]*)\s*\(",
                str(signature),
                flags=re.IGNORECASE,
            )
        ),
        "",
    )
    if existing_progress_signature:
        progress_signature = existing_progress_signature
    else:
        callable_signatures.append(progress_signature)
    progress_name_match = re.search(
        r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        progress_signature,
    )
    progress_method_name = (
        progress_name_match.group(1)
        if progress_name_match
        else "_handle_progress"
    )
    required_methods = declaration_contract.setdefault("required_methods", [])
    if progress_method_name not in required_methods:
        required_methods.append(progress_method_name)
    method_tasks = chunk.setdefault("method_tasks", [])
    if not any(
        isinstance(task, Mapping)
        and str(task.get("name") or "") == progress_method_name
        for task in method_tasks
    ):
        method_tasks.append({
            "name": progress_method_name,
            "signature": progress_signature,
            "requirement_ids": progress_requirement_ids,
            "implementation_mechanics": progress_mechanics,
            "validation_cases": [
                "Emit one progress payload and prove the dialog updates its integer "
                "range, integer value, and visible status text."
            ],
            "behavior_ids": progress_requirement_ids,
        })
    for task in method_tasks:
        if not isinstance(task, dict):
            continue
        task_name = str(task.get("name") or "")
        role_name = task_name.casefold()
        if any(
            token in role_name
            for token in ("cleanup", "clean_up", "release", "dispose")
        ):
            task["implementation_mechanics"] = [
                "Run only from the retained worker finished signal.",
                "Schedule the finished worker for deletion when supported, then "
                "clear the retained worker reference exactly once.",
                "Restore the initiating control to its idle enabled state without "
                "starting new work or mutating result data.",
            ]
            task["validation_cases"] = [
                "Finish either a successful or failed worker and prove the retained "
                "reference is released and the initiating control is reusable."
            ]
        elif "progress" in role_name:
            task["implementation_mechanics"] = [
                step
                for step in progress_mechanics
                if "dialog progress handler" in step.casefold()
                or "progress control" in step.casefold()
                or "status text" in step.casefold()
            ]
            task["validation_cases"] = [
                "Given one `(current_step, total_steps, status)` payload, "
                "prove the existing progress control range and value are updated "
                "with integers and the existing status control displays status."
            ]
        elif any(
            token in role_name
            for token in ("error", "failure", "failed")
        ):
            task["implementation_mechanics"] = [
                "Receive the worker error signal payload and display that exact "
                "error through the existing status or error control.",
                "Leave worker disposal to the owner-side finished-signal cleanup; "
                "do not start work, dispose the active worker, or construct "
                "replacement widgets here.",
            ]
            task["validation_cases"] = [
                "Emit one worker error and prove the visible status/error surface "
                "shows the same payload without starting another worker."
            ]
        elif any(
            token in role_name
            for token in ("result", "success", "complete", "finished")
        ):
            result_filter_attributes = [
                str(attribute.get("name") or "")
                for attribute in declaration_contract.get("attributes") or []
                if isinstance(attribute, Mapping)
                and re.search(
                    r"(?:filter|include|exclude).*(?:check|toggle|combo|input)"
                    r"|(?:check|toggle|combo|input).*(?:filter|include|exclude)",
                    str(attribute.get("name") or ""),
                    flags=re.IGNORECASE,
                )
            ]
            task["implementation_mechanics"] = [
                "Receive the worker result signal payload and populate the "
                "existing result controls from that real payload.",
                *(
                    [
                        "Read and apply only these approved result-filter inputs "
                        "before presenting records: "
                        + ", ".join(result_filter_attributes)
                        + "."
                    ]
                    if result_filter_attributes
                    else []
                ),
                "Leave worker disposal to the owner-side finished-signal cleanup; "
                "do not start another worker, dispose the active worker, or "
                "reconstruct UI controls here.",
            ]
            task["validation_cases"] = [
                "Emit one worker result and prove existing result controls display "
                + (
                    "the payload after applying its approved filters without "
                    "starting another worker."
                    if result_filter_attributes
                    else "the real payload without starting another worker."
                )
            ]
        elif (
            role_name.startswith(("_on_", "_handle_"))
            and any(
                token in role_name
                for token in ("click", "refresh", "trigger")
            )
        ):
            launcher_names = [
                str(candidate.get("name") or "")
                for candidate in method_tasks
                if isinstance(candidate, Mapping)
                and str(candidate.get("name") or "") != task_name
                and not str(candidate.get("name") or "").startswith("_on_")
                and any(
                    token in str(candidate.get("name") or "").casefold()
                    for token in (
                        "background",
                        "execute",
                        "launch",
                        "run",
                        "start",
                        "worker",
                    )
                )
            ]
            if launcher_names:
                launcher_name = launcher_names[0]
                task["implementation_mechanics"] = [
                    f"Invoke `self.{launcher_name}()` exactly once and return "
                    "immediately; do not construct, start, or invoke the worker "
                    "operation directly in this action handler."
                ]
                task["validation_cases"] = [
                    f"Trigger the connected action and prove it calls "
                    f"`{launcher_name}` exactly once without blocking."
                ]
        elif any(
            token in role_name
            for token in ("execute", "launch", "refresh", "run", "start")
        ):
            task["implementation_mechanics"] = [
                "Construct the approved worker with the bound blocking operation, "
                "retain it on the UI owner, and let the worker inject its progress "
                "signal callback before invoking that operation.",
                "Connect worker result, error, and progress signals to their exact "
                "dialog handlers before calling the verified thread start method "
                "exactly once.",
                "Before assigning a new retained worker, return without starting "
                "when the existing worker is active, or keep the initiating control "
                "disabled until terminal cleanup.",
                "Connect the worker finished signal to one owner-side cleanup "
                "callable before start so the retained worker is released on every "
                "success and failure path.",
                "Return immediately after starting the worker; do not call the "
                "blocking operation, UI handlers, sleep, wait, join, poll, or "
                "processEvents directly.",
            ]
            task["validation_cases"] = [
                "Trigger the launcher and prove one retained worker is started, "
                "all three signals are connected before start, and no blocking "
                "operation executes on the caller thread."
            ]
    for helper in declaration_contract.get("helper_declarations") or []:
        if (
            not isinstance(helper, dict)
            or str(helper.get("base") or "").rsplit(".", 1)[-1] != "QThread"
        ):
            continue
        signals = [
            dict(signal)
            for signal in helper.get("signals") or []
            if isinstance(signal, Mapping)
            and str(signal.get("name") or "")
        ]
        required_signal_contracts = {
            "result": ["object"],
            "error": ["str"],
            "progress": ["int", "int", "str"],
        }
        existing_signal_names = {
            str(signal.get("name") or "") for signal in signals
        }
        for signal_name, arguments in required_signal_contracts.items():
            if signal_name in existing_signal_names:
                continue
            signals.append({
                "name": signal_name,
                "arguments": arguments,
                "declaration_required": True,
                "emit_required": True,
            })
        helper["signals"] = signals
        operation_protocol = helper.setdefault("operation_protocol", {})
        operation_protocol.update({
            "progress_callback_parameter": "progress_callback",
            "progress_callback_value": "self.progress.emit",
            "inject_progress_callback_before_invoke": True,
        })


def materialize_threaded_progress_declarations(
    chunk: dict[str, Any],
) -> None:
    """Finalize method-role ownership for one approved threaded UI chunk."""

    _materialize_threaded_progress_declarations(chunk)


def _merge_duplicate_owner_chunks(
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge duplicate declaration chunks for one path and owner.

    :param chunks: Materialized implementation-plan chunks.
    :return: Stable chunks with one declaration contract per owner.
    """

    merged: list[dict[str, Any]] = []
    by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}

    def merge_unique(target: list[Any], values: Iterable[Any]) -> None:
        seen = {json.dumps(value, sort_keys=True, default=str) for value in target}
        for value in values:
            fingerprint = json.dumps(value, sort_keys=True, default=str)
            if fingerprint not in seen:
                target.append(value)
                seen.add(fingerprint)

    def merge_mapping(target: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            if key not in target or target[key] in (None, "", [], {}):
                target[key] = value
            elif isinstance(target[key], list) and isinstance(value, list):
                merge_unique(target[key], value)
            elif isinstance(target[key], dict) and isinstance(value, Mapping):
                merge_mapping(target[key], value)
            elif isinstance(target[key], bool) and isinstance(value, bool):
                target[key] = target[key] or value

    for chunk in chunks:
        identity = (
            os.path.normcase(os.path.normpath(str(chunk.get("path") or ""))),
            str(chunk.get("owner") or ""),
            str(chunk.get("kind") or ""),
        )
        existing = by_identity.get(identity)
        if existing is None or not identity[1]:
            merged.append(chunk)
            if identity[1]:
                by_identity[identity] = chunk
            continue
        merge_mapping(existing, chunk)
    return merged


def enrich_implementation_plan(
    implementation_plan: Mapping[str, Any],
    *,
    original_prompt: str,
    manifest: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Add concrete contracts and tests without changing requirement ownership."""

    def _public_symbol_name(symbol: Any) -> str:
        if isinstance(symbol, Mapping):
            return str(
                symbol.get("qualified_name")
                or symbol.get("name")
                or symbol.get("owner")
                or ""
            ).split("(", 1)[0].strip()
        return str(symbol or "").split("(", 1)[0].strip()

    def _explicit_dependency_policy(source: str) -> dict[str, Any]:
        """Extract request-specific dependency rules that override defaults."""

        clauses: list[str] = []
        forbidden_imports: list[str] = []
        required_owners: list[str] = []
        for clause in re.split(r"(?<=[.!?;])\s+|\n+", str(source or "")):
            normalized = clause.strip()
            if not normalized:
                continue
            has_override = bool(re.search(
                r"\b(?:do\s+not|don't|must\s+not|never|without|only|"
                r"instead\s+of|rather\s+than)\b",
                normalized,
                flags=re.IGNORECASE,
            ))
            has_owned_transport = bool(re.search(
                r"\b(?:adapter|bridge|service|transport|wrapper|gateway|API)\b",
                normalized,
                flags=re.IGNORECASE,
            ))
            if not has_override and not has_owned_transport:
                continue
            imported_modules: list[str] = []
            for import_match in re.finditer(
                r"\bimport(?:ing)?\s+"
                r"((?:[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
                r"(?:\s*(?:,|\bor\b|\band\b)\s*"
                r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)*)",
                normalized,
                flags=re.IGNORECASE,
            ):
                imported_modules.extend(re.findall(
                    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*",
                    import_match.group(1),
                ))
            imported_modules = [
                value
                for value in imported_modules
                if value.casefold() not in {"and", "or"}
            ]
            imported_modules.extend(
                match.group(1)
                for match in re.finditer(
                    r"\bfrom\s+"
                    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
                    r"\s+import\b",
                    normalized,
                    flags=re.IGNORECASE,
                )
            )
            owner_candidates = re.findall(
                r"\b([A-Z][A-Za-z0-9_]*(?:Adapter|Bridge|Service|Transport|"
                r"Wrapper|Gateway))\b"
                r"|\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b",
                normalized,
            )
            normalized_owners = [
                value
                for pair in owner_candidates
                for value in pair
                if value and value not in imported_modules
                and any(
                    re.search(
                        r"(?:adapter|bridge|service|transport|wrapper|gateway)s?$",
                        segment,
                        flags=re.IGNORECASE,
                    )
                    for segment in value.split(".")
                )
            ]
            if not has_owned_transport:
                normalized_owners = []
            if not imported_modules and not normalized_owners:
                continue
            clauses.append(normalized)
            if has_override:
                forbidden_imports.extend(imported_modules)
            required_owners.extend(normalized_owners)
        return {
            "precedence": "explicit_request_over_general_dependency_allowance",
            "constraints": list(dict.fromkeys(clauses)),
            "forbidden_imports": list(dict.fromkeys(forbidden_imports)),
            "required_owners": list(dict.fromkeys(required_owners)),
            "exclusive_owner_required": bool(required_owners),
        }

    plan = json.loads(json.dumps(implementation_plan, default=str))
    raw_chunks = [
        chunk for chunk in plan.get("chunks") or [] if isinstance(chunk, dict)
    ]
    canonical_chunk_ids: dict[tuple[str, str, str], str] = {}
    chunk_id_remap: dict[str, str] = {}
    for chunk in raw_chunks:
        identity = (
            os.path.normcase(os.path.normpath(str(chunk.get("path") or ""))),
            str(chunk.get("owner") or ""),
            str(chunk.get("kind") or ""),
        )
        chunk_id = str(chunk.get("chunk_id") or "")
        if not chunk_id or not identity[1]:
            continue
        canonical_id = canonical_chunk_ids.setdefault(identity, chunk_id)
        chunk_id_remap[chunk_id] = canonical_id
    chunks = _merge_duplicate_owner_chunks(raw_chunks)
    plan["chunks"] = chunks
    for coverage in plan.get("requirement_coverage") or []:
        if not isinstance(coverage, dict):
            continue
        coverage["owners"] = list(dict.fromkeys(
            chunk_id_remap.get(str(owner), str(owner))
            for owner in coverage.get("owners") or []
        ))
    class_chunks = [
        chunk for chunk in chunks if str(chunk.get("kind") or "") == "class"
    ]

    def owner_terms(chunk: Mapping[str, Any]) -> list[str]:
        return [
            value.casefold()
            for value in re.findall(
                r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+",
                str(chunk.get("owner") or ""),
            )
            if len(value) >= 3
        ]

    role_counts: dict[str, int] = {}
    for class_chunk in class_chunks:
        terms = owner_terms(class_chunk)
        if terms:
            role_counts[terms[-1]] = role_counts.get(terms[-1], 0) + 1
    edge_scores: dict[tuple[str, str], int] = {}
    chunks_by_id = {
        str(chunk.get("chunk_id") or ""): chunk
        for chunk in class_chunks
        if str(chunk.get("chunk_id") or "")
    }
    for consumer in class_chunks:
        consumer_id = str(consumer.get("chunk_id") or "")
        consumer_text = " ".join(
            item["text"] for item in _requirement_texts(consumer)
        )
        for dependency_id in consumer.get("depends_on") or []:
            if str(dependency_id) in chunks_by_id:
                edge_scores[(consumer_id, str(dependency_id))] = 10
        for producer in class_chunks:
            if producer is consumer:
                continue
            producer_id = str(producer.get("chunk_id") or "")
            producer_owner = str(producer.get("owner") or "")
            terms = owner_terms(producer)
            role = terms[-1] if terms else ""
            score = 0
            if producer_owner and re.search(
                rf"(?<![.\w]){re.escape(producer_owner)}(?![.\w])",
                consumer_text,
            ):
                score = 100
            elif (
                role
                and role_counts.get(role) == 1
                and re.search(
                    rf"\b{re.escape(role)}s?\b",
                    consumer_text,
                    flags=re.IGNORECASE,
                )
            ):
                score = 50
            if score:
                edge_scores[(consumer_id, producer_id)] = max(
                    score,
                    edge_scores.get((consumer_id, producer_id), 0),
                )
    for (consumer_id, producer_id), score in list(edge_scores.items()):
        reverse_score = edge_scores.get((producer_id, consumer_id), 0)
        if reverse_score and reverse_score > score:
            edge_scores.pop((consumer_id, producer_id), None)
        elif reverse_score and reverse_score < score:
            edge_scores.pop((producer_id, consumer_id), None)
    for consumer in class_chunks:
        consumer_id = str(consumer.get("chunk_id") or "")
        consumer["depends_on"] = [
            producer_id
            for (edge_consumer, producer_id), _score in edge_scores.items()
            if edge_consumer == consumer_id
        ]
    path_by_chunk_id = {
        str(chunk.get("chunk_id") or ""): str(chunk.get("path") or "")
        for chunk in class_chunks
    }
    for file_row in plan.get("files") or []:
        if not isinstance(file_row, dict):
            continue
        file_path = str(file_row.get("path") or "")
        dependency_paths = {
            path_by_chunk_id.get(str(dependency_id), "")
            for chunk in class_chunks
            if str(chunk.get("path") or "") == file_path
            for dependency_id in chunk.get("depends_on") or []
        }
        file_row["depends_on"] = [
            (
                Path(dependency_path).parent.name
                + "/"
                + Path(dependency_path).name
            )
            for dependency_path in sorted(dependency_paths)
            if dependency_path and dependency_path != file_path
        ]
    manifest_symbols_by_owner = {
        _public_symbol_name(symbol): symbol
        for item in manifest or []
        if isinstance(item, Mapping) and not bool(item.get("is_test"))
        for symbol in item.get("public_symbols") or []
        if isinstance(symbol, Mapping) and _public_symbol_name(symbol)
    }
    expected_declarations = [
        {
            "file": str(item.get("absolute_path") or item.get("path") or ""),
            "owner": _public_symbol_name(symbol),
        }
        for item in manifest or []
        if isinstance(item, Mapping) and not bool(item.get("is_test"))
        for symbol in item.get("public_symbols") or []
        if _public_symbol_name(symbol)
    ]
    plan["expected_declarations"] = expected_declarations
    complete_text = ". ".join(
        str(item.get("text") or "")
        for chunk in chunks
        for item in chunk.get("requirements") or []
        if isinstance(item, Mapping)
    )
    dependency_policy = _explicit_dependency_policy(
        ". ".join(value for value in (original_prompt, complete_text) if value)
    )
    plan["dependency_policy"] = dependency_policy
    for chunk in chunks:
        owner = str(chunk.get("owner") or "")
        kind = str(chunk.get("kind") or "symbol")
        manifest_symbol = manifest_symbols_by_owner.get(owner, {})
        inferred_public_signatures = [
            str(value).strip()
            for value in manifest_symbol.get(
                "inferred_callable_signatures", []
            )
            if str(value).strip()
        ]
        inferred_private_signatures = [
            str(value).strip()
            for value in manifest_symbol.get(
                "inferred_private_callable_signatures", []
            )
            if str(value).strip()
        ]
        requirements = _requirement_texts(chunk)
        text = ". ".join(item["text"] for item in requirements)
        # Preserve the complete authoritative ledger for later repair and
        # re-selection. Generation still receives a compact selected view.
        chunk["evidence_ledger"] = list(chunk.get("evidence") or [])
        chunk["evidence"] = [
            item
            for item in chunk.get("evidence") or []
            if not (
                str(item.get("provider") or "") == "project_index_definition"
                and not bool(item.get("authoritative_signature"))
                and str(item.get("strength") or "") not in {
                    "authoritative_signature",
                    "official_api_research",
                    "exact_indexed_definition",
                }
                and not bool(item.get("selected_for_generation"))
                and not bool(item.get("dependency_for_selected"))
                and len(str(item.get("name") or "").split(".")) >= 3
                and str(item.get("name") or "").split(".")[-2] != owner
                and str(item.get("name") or "") not in text
                and not re.search(
                    rf"\b{re.escape(str(item.get('name') or '').rsplit('.', 1)[-1])}\b",
                    text,
                )
            )
        ]
        normalized_text = text.casefold()
        requests_open_picker = bool(
            "qfiledialog" in normalized_text
            and re.search(
                r"\b(?:browse|choose|open|pick|select)\b[^.;]{0,80}"
                r"\b(?:existing|input|source|file|image)\b",
                normalized_text,
            )
        )
        requests_save_picker = bool(
            "qfiledialog" in normalized_text
            and re.search(
                r"\b(?:save|output|destination)\b[^.;]{0,80}"
                r"\b(?:file|path|picker|dialog)\b",
                normalized_text,
            )
        )
        if requests_open_picker and not requests_save_picker:
            chunk["evidence"] = [
                item
                for item in chunk["evidence"]
                if "qfiledialog.getsave" not in str(
                    item.get("name") or ""
                ).casefold()
                and "qfiledialog.savefile" not in str(
                    item.get("name") or ""
                ).casefold()
            ]
        elif requests_save_picker and not requests_open_picker:
            chunk["evidence"] = [
                item
                for item in chunk["evidence"]
                if "qfiledialog.getopen" not in str(
                    item.get("name") or ""
                ).casefold()
            ]
        base = _class_base(owner, text) if kind == "class" else ""
        requires_off_ui_thread = bool(re.search(
            r"\b(?:outside|off)\s+(?:of\s+)?(?:the\s+)?UI\s+thread\b"
            r"|\bwithout\s+blocking\s+(?:the\s+)?UI\b"
            r"|\bnon[- ]blocking\b[^.!?\n]{0,80}"
            r"\b(?:UI|dialog|window|widget)\b",
            text,
            flags=re.IGNORECASE,
        ))
        selected_evidence_names = {
            str(item.get("name") or "").casefold()
            for item in chunk.get("evidence") or []
            if bool(item.get("selected_for_generation"))
        }
        signal_contracts = _signal_contracts(text)
        helper_declarations: list[dict[str, Any]] = []
        worker_base = ""
        if (
            requires_off_ui_thread
            and any(
                name.endswith(".qrunnable.run")
                for name in selected_evidence_names
            )
        ):
            worker_base = "QRunnable"
        elif (
            requires_off_ui_thread
            and any(
                name.endswith(".qthread.start")
                for name in selected_evidence_names
            )
        ):
            worker_base = "QThread"
        if worker_base:
            worker_owner = f"_{owner}Worker"
            worker_signals = signal_contracts
            helper_declarations.append({
                "owner": worker_owner,
                "kind": "class",
                "visibility": "private",
                "base": worker_base,
                "callable_signatures": [
                    "def __init__(self, operation, *args, **kwargs)",
                    "def run(self) -> None",
                ],
                "required_methods": ["__init__", "run"],
                "signals": worker_signals,
                "placeholders_forbidden": True,
                "operation_protocol": {
                    "store_operation": True,
                    "store_args": True,
                    "store_kwargs": True,
                    "invoke": "operation(*args, **kwargs)",
                    "completion_payload": "operation result",
                    "error_payload": "str(exception)",
                    "ui_mutation_forbidden": True,
                    "exception_swallowing_forbidden": True,
                },
                "responsibility": (
                    "Own and execute the approved blocking operation outside "
                    "the UI thread. Store the operation plus positional and keyword "
                    "arguments, invoke operation(*args, **kwargs) exactly once in "
                    "run(), emit its returned result through the approved completion "
                    "signal, and emit str(exception) through the approved error "
                    "signal. The worker operation returns data only; it must not "
                    "touch UI widgets or swallow failures."
                ),
            })
            plan["expected_declarations"].append({
                "file": str(chunk.get("path") or ""),
                "owner": worker_owner,
                "visibility": "private",
            })
        owner_signals_explicit = bool(re.search(
            rf"\b{re.escape(owner)}\b[^.!?\n]{{0,120}}"
            r"\b(?:declare|define|expose|own|provide|emit)\w*\b"
            r"[^.!?\n]{0,80}\bsignals?\b"
            r"|\b(?:dialog|widget|window|class)\b[^.!?\n]{0,80}"
            r"\b(?:declare|define|expose|own)\w*\b"
            r"[^.!?\n]{0,80}\bsignals?\b",
            text,
            flags=re.IGNORECASE,
        ))
        raw_callable_signatures = list(dict.fromkeys([
            *_callable_signatures(owner, kind, text),
            *inferred_public_signatures,
            *inferred_private_signatures,
        ]))

        def parsed_signature_name(signature: str) -> str:
            """Return a callable name only for a complete Python signature.

            :param signature: candidate function signature
            :return: parsed callable name or an empty string
            """

            normalized = re.sub(
                r"\)\s*:\s*->\s*",
                ") -> ",
                str(signature).strip(),
            ).rstrip(":").strip()
            try:
                parsed = ast.parse(normalized + ":\n    pass")
            except SyntaxError:
                return ""
            if (
                len(parsed.body) != 1
                or not isinstance(
                    parsed.body[0],
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            ):
                return ""
            return parsed.body[0].name

        valid_signature_names = {
            name
            for signature in raw_callable_signatures
            if (name := parsed_signature_name(str(signature)))
        }
        callable_signatures = [
            str(signature)
            for signature in raw_callable_signatures
            if parsed_signature_name(str(signature))
            or not any(
                re.match(
                    rf"^(?:async\s+)?def\s+{re.escape(name)}\s*\(",
                    str(signature).strip(),
                )
                for name in valid_signature_names
            )
        ]
        signature_method_names = [
            name
            for signature in callable_signatures
            if (name := parsed_signature_name(signature))
            and name != "__init__"
        ]
        required_methods = list(dict.fromkeys([
            *_required_method_names(owner, kind, text),
            *signature_method_names,
            *[
                str(item.get("method_name") or "")
                for item in (
                    manifest_symbol.get(
                        "inferred_callable_proposals", []
                    )
                    + manifest_symbol.get(
                        "inferred_private_callable_proposals", []
                    )
                )
                if str(item.get("method_name") or "")
            ],
        ]))
        chunk["declaration_contract"] = {
            "owner": owner,
            "kind": kind,
            "base": base,
            "callable_signatures": callable_signatures,
            "inferred_callable_proposals": [
                *manifest_symbol.get("inferred_callable_proposals", []),
                *manifest_symbol.get(
                    "inferred_private_callable_proposals", []
                ),
            ],
            "public_surface_locked": kind == "class",
            "private_surface_locked": bool(
                manifest_symbol.get(
                    "inferred_private_callable_proposals"
                )
            ),
            "required_methods": required_methods,
            "properties": _property_names(text) if kind == "class" else [],
            "attributes": _attribute_contracts(text),
            "signals": (
                signal_contracts
                if not worker_base or owner_signals_explicit
                else []
            ),
            "helper_declarations": helper_declarations,
            "fields": [],
            "decorators": (
                ["dataclass"]
                if re.search(
                    rf"\b{re.escape(owner)}\b\s+dataclass\b"
                    rf"|\bdataclass\s+{re.escape(owner)}\b",
                    text,
                    flags=re.IGNORECASE,
                )
                else []
            ),
            "type_hints_required": kind != "module",
            "synchronization_required": bool(
                kind == "class"
                and re.search(
                    r"\b(?:thread-safe|thread\s+safe)\b",
                    text,
                    re.IGNORECASE,
                )
            ),
            "full_owner_body_required": kind != "module",
            "private_helpers_allowed": kind == "class",
            "placeholders_forbidden": True,
            "dependency_policy": _explicit_dependency_policy(text),
            "execution_constraints": {
                "requires_off_ui_thread": requires_off_ui_thread,
                "requires_completion_path": bool(re.search(
                    r"\b(?:outside|off)\s+(?:of\s+)?(?:the\s+)?UI\s+thread\b"
                    r"|\bwithout\s+blocking\s+(?:the\s+)?UI\b",
                    text,
                    flags=re.IGNORECASE,
                )),
                "requires_error_path": bool(re.search(
                    r"\b(?:outside|off)\s+(?:of\s+)?(?:the\s+)?UI\s+thread\b"
                    r"|\bwithout\s+blocking\s+(?:the\s+)?UI\b",
                    text,
                    flags=re.IGNORECASE,
                )),
                "forbidden_ui_calls": [
                    "sleep",
                    "processEvents",
                    "wait",
                    "join",
                ],
                "forbid_handler_loops": bool(re.search(
                    r"\b(?:outside|off)\s+(?:of\s+)?(?:the\s+)?UI\s+thread\b"
                    r"|\bwithout\s+blocking\s+(?:the\s+)?UI\b",
                    text,
                    flags=re.IGNORECASE,
                )),
            },
            "module_entry_point_required": bool(
                (
                    kind == "module"
                    and re.search(
                        r"\b(?:runnable\s+(?:main\s+)?example|"
                        r"module\s+entry\s+point|run as (?:a )?script|"
                        r"runs?\s+standalone|if\s+__name__|__main__)\b",
                        text,
                        flags=re.IGNORECASE,
                    )
                )
                or (
                    kind == "class"
                    and not Path(str(chunk.get("path") or "")).is_file()
                    and (
                        str(base).rsplit(".", 1)[-1].endswith(
                            ("Dialog", "MainWindow", "Widget", "Window")
                        )
                        or str(owner).endswith(
                            ("Dialog", "MainWindow", "Widget", "Window")
                        )
                    )
                )
                or (
                    kind == "module"
                    and not Path(str(chunk.get("path") or "")).is_file()
                    and any(
                        isinstance(candidate, Mapping)
                        and str(candidate.get("path") or "")
                        == str(chunk.get("path") or "")
                        and str(candidate.get("kind") or "") == "class"
                        and (
                            str(candidate.get("owner") or "").endswith(
                                ("Dialog", "MainWindow", "Widget", "Window")
                            )
                        )
                        for candidate in chunks
                    )
                )
            ),
        }
        if kind == "class":
            chunk.setdefault("implementation_mechanics", []).append(
                "Keep the public constructor surface minimal: accept only parameters "
                "explicitly requested, bound by an approved data-flow obligation, or "
                "required by a verified base-class signature. Initialize private "
                "storage internally instead of inventing convenience inputs."
            )
            owner_method_pattern = re.compile(
                rf"^\s*(?:async\s+)?def\s+{re.escape(owner)}\s*\(",
            )
            chunk["declaration_contract"]["callable_signatures"] = [
                signature
                for signature in chunk["declaration_contract"][
                    "callable_signatures"
                ]
                if not owner_method_pattern.match(str(signature))
            ]
            chunk["declaration_contract"]["required_methods"] = [
                method
                for method in chunk["declaration_contract"]["required_methods"]
                if str(method) != owner
            ]
        if "dataclass" in chunk["declaration_contract"]["decorators"]:
            typed_field_clause = re.search(
                rf"\b(?:immutable\s+)?{re.escape(owner)}\s+dataclass\s+with\s+"
                r"(.+?)(?=;\s*|\.\s+[A-Z]|\Z)",
                text,
                flags=re.IGNORECASE,
            )
            if typed_field_clause:
                normalized_typed_fields = re.sub(
                    r",\s*(?:and|or)\s+"
                    r"(?=[a-z_][A-Za-z0-9_]*\s*:)",
                    ", ",
                    typed_field_clause.group(1),
                    flags=re.IGNORECASE,
                )
                chunk["declaration_contract"]["fields"].extend(
                    {
                        "name": field_match.group(1),
                        "type": field_match.group(2).strip().rstrip(","),
                    }
                    for field_match in re.finditer(
                        r"\b([a-z_][A-Za-z0-9_]*)\s*:\s*(.+?)"
                        r"(?=,\s*[a-z_][A-Za-z0-9_]*\s*:|\Z)",
                        normalized_typed_fields,
                    )
                )
            chunk["declaration_contract"]["immutable"] = bool(re.search(
                rf"\bimmutable\s+{re.escape(owner)}\s+dataclass\b",
                text,
                flags=re.IGNORECASE,
            ))
            mutable_field_names = [
                str(field.get("name") or "")
                for field in chunk["declaration_contract"]["fields"]
                if re.match(
                    r"^(?:dict|list|set|MutableMapping|MutableSequence|MutableSet)\b",
                    str(field.get("type") or "").strip(),
                )
            ]
            chunk["declaration_contract"]["mutable_field_names"] = (
                mutable_field_names
            )
            chunk["declaration_contract"]["immutability_depth"] = (
                "recursive"
                if (
                    chunk["declaration_contract"]["immutable"]
                    and mutable_field_names
                )
                else "structural"
            )
        if kind == "class" and owner.endswith(("Error", "Exception")):
            contained_state = re.search(
                rf"\b{re.escape(owner)}\b\s+containing\s+(?:the\s+)?"
                r"([a-z][A-Za-z0-9 _-]*?)(?=;\s*|\.\s+[A-Z]|\Z)",
                text,
                flags=re.IGNORECASE,
            )
            if contained_state:
                state_tokens = [
                    token.casefold()
                    for token in re.findall(
                        r"[A-Za-z][A-Za-z0-9]*",
                        contained_state.group(1),
                    )
                    if token.casefold() not in {
                        "detected",
                        "exact",
                        "invalid",
                        "offending",
                        "requested",
                        "the",
                    }
                ]
                state_name = "_".join(state_tokens)
                if state_name:
                    chunk["declaration_contract"]["attributes"].append({
                        "name": state_name,
                        "type": "",
                        "construction_required": True,
                        "runtime_use_required": False,
                    })
                    chunk["declaration_contract"]["callable_signatures"] = (
                        list(dict.fromkeys([
                            *chunk["declaration_contract"]["callable_signatures"],
                            f"def __init__(self, {state_name})",
                        ]))
                    )
        if "dataclass" in chunk["declaration_contract"]["decorators"]:
            fields = chunk["declaration_contract"]["fields"]
            if not fields:
                field_match = re.search(
                    rf"\b{re.escape(owner)}\b\s+dataclass\s+with\s+"
                    r"([^.!?\n;]+?)\s+fields?\b",
                    text,
                    flags=re.IGNORECASE,
                )
                if not field_match:
                    field_match = re.search(
                        rf"\b{re.escape(owner)}\b\s+dataclass\s+"
                        r"(?:containing|having|with)\s+"
                        r"(.+?)(?=;\s*(?:validate|add|include|implement|define)\b"
                        r"|[.!?\n]|$)",
                        text,
                        flags=re.IGNORECASE,
                    )
                if field_match:
                    def inferred_field_type(field_name: str) -> str:
                        lowered = field_name.casefold()
                        if (
                            lowered.startswith(("is_", "has_", "should_"))
                            or lowered in {"srgb", "enabled", "disabled", "checked"}
                            or lowered.endswith(("_flag", "_enabled"))
                        ):
                            return "bool"
                        if lowered.endswith(
                            ("_attempts", "_count", "_index", "_limit", "_size")
                        ):
                            return "int"
                        if (
                            lowered.endswith(
                                (
                                    "_at",
                                    "_delay",
                                    "_seconds",
                                    "_timestamp",
                                    "_multiplier",
                                    "_rate",
                                )
                            )
                            or lowered == "multiplier"
                        ):
                            return "float"
                        if lowered.endswith(
                            (
                                "_name",
                                "_mode",
                                "_path",
                                "_file",
                                "_filename",
                                "_text",
                                "_id",
                            )
                        ):
                            return "str"
                        numeric_surface = re.search(
                            rf"\b{re.escape(field_name)}(?:_spinbox)?\b"
                            r"[^.!?\n]{0,120}\b(?:QDoubleSpinBox|double|float|"
                            r"ranging\s+0\.0|0\.0\s+to\s+1\.0)\b",
                            complete_text,
                            flags=re.IGNORECASE,
                        )
                        return "float" if numeric_surface else "Any"

                    fields.extend(
                        {
                            "name": field_name,
                            "type": inferred_field_type(field_name),
                        }
                        for field_name in dict.fromkeys(re.findall(
                            r"\b[a-z_][A-Za-z0-9_]*\b",
                            field_match.group(1),
                        ))
                        if field_name.casefold() not in {
                            "a", "an", "and", "or", "the", "with"
                        }
                    )
            chunk["declaration_contract"]["callable_signatures"] = [
                signature
                for signature in chunk["declaration_contract"][
                    "callable_signatures"
                ]
                if not signature.startswith("def __init__(")
            ]
            if fields:
                parameters = ", ".join(
                    f"{field['name']}: {field['type']}" for field in fields
                )
                chunk["declaration_contract"]["callable_signatures"].insert(
                    0, f"def __init__(self, {parameters})"
                )
            if re.search(
                r"\bvalidate\b[^.!?\n;]{0,100}\bconstructor\b"
                r"|\bconstructor\b[^.!?\n;]{0,100}\bvalidat"
                r"|\breject\b[^.!?\n;]{0,160}"
                r"\b(?:empty|blank|negative|invalid|missing)\b",
                text,
                flags=re.IGNORECASE,
            ):
                required_methods = chunk["declaration_contract"][
                    "required_methods"
                ]
                if "__post_init__" not in required_methods:
                    required_methods.append("__post_init__")
                signatures = chunk["declaration_contract"][
                    "callable_signatures"
                ]
                if not any("__post_init__(" in value for value in signatures):
                    signatures.append("def __post_init__(self) -> None")
        is_data_contract = bool(
            "dataclass" in chunk["declaration_contract"]["decorators"]
            and not chunk["declaration_contract"]["required_methods"]
        )
        file_has_symbol_chunks = any(
            isinstance(candidate, Mapping)
            and str(candidate.get("path") or "") == str(chunk.get("path") or "")
            and str(candidate.get("kind") or "") != "module"
            for candidate in chunks
        )
        non_code_roles = {
            "structure",
            "file_contract",
            "package_contract",
            "quality",
            "documentation",
            "constraint",
        }
        module_has_runtime_contract = bool(
            chunk.get("declaration_contract", {}).get(
                "module_entry_point_required"
            )
            or any(
                re.search(
                    r"\b(?:__main__|entry\s+point|module[- ]level\s+"
                    r"(?:registration|initialization|configuration))\b",
                    requirement["text"],
                    flags=re.IGNORECASE,
                )
                for requirement in requirements
            )
        )
        chunk["generation_required"] = not (
            kind == "module"
            and file_has_symbol_chunks
            and not module_has_runtime_contract
            and requirements
            and all(
                str(requirement.get("semantic_role") or "behavior").casefold()
                in non_code_roles
                for requirement in requirements
            )
        )
        chunk["implementation_mechanics"] = []
        chunk["validation_cases"] = []
        chunk["observable_contracts"] = []
        is_error_contract = owner.rsplit(".", 1)[-1].endswith(
            ("Error", "Exception")
        )
        if is_error_contract and not chunk["declaration_contract"].get("base"):
            chunk["declaration_contract"]["base"] = "Exception"
        if is_error_contract:
            chunk["declaration_contract"]["callable_signatures"] = [
                signature
                for signature in chunk["declaration_contract"].get(
                    "callable_signatures", []
                )
                if not signature.startswith("def __init__(")
            ]
        for requirement in requirements:
            mechanics = _mechanics(
                requirement["text"],
                chunk.get("evidence") or [],
                requirement["id"],
            )
            if (
                kind == "module"
                and re.search(
                    r"\b__main__\b|\bguarded\s+(?:main|entry\s+point)\b",
                    requirement["text"],
                    flags=re.IGNORECASE,
                )
            ):
                mechanics = [
                    "Add exactly one guarded `if __name__ == \"__main__\":` "
                    "entry point.",
                    "Reuse `QApplication.instance()` when one exists; otherwise "
                    "construct one application instance.",
                    "Construct the requested top-level UI owner, call `show()`, "
                    "and enter the application event loop only for the application "
                    "instance created by this module.",
                ]
            file_has_symbol_chunks = any(
                isinstance(candidate, Mapping)
                and str(candidate.get("path") or "") == str(chunk.get("path") or "")
                and str(candidate.get("kind") or "") != "module"
                for candidate in chunks
            )
            if kind == "module" and file_has_symbol_chunks:
                mechanics = [
                    step for step in mechanics
                    if not step.startswith(
                        "Create the widget and connect its signal"
                    )
                ]
            else:
                mechanics = [
                    step for step in mechanics
                    if not step.startswith("Add a module-owned ")
                ]
            validations = _validation_cases(
                requirement["id"],
                requirement["text"],
                owner=owner,
            )
            if is_data_contract:
                mechanics = [
                    (
                        "Declare every approved typed data field directly on the "
                        "dataclass and let its generated constructor initialize them."
                    )
                ]
                validations = [
                    (
                        "Construct the dataclass through its approved typed fields "
                        "and read each value back unchanged."
                    )
                ]
            elif is_error_contract:
                mechanics = [
                    "Declare the requested exception type as an Exception subclass; "
                    "state mutation and rejection logic remain in the state owner."
                ]
                validations = [
                    "Raise and catch the requested exception type through the state "
                    "owner's invalid-operation boundary."
                ]
            chunk["implementation_mechanics"].append({
                "requirement_id": requirement["id"],
                "steps": mechanics,
            })
            chunk["validation_cases"].append({
                "requirement_id": requirement["id"],
                "checks": validations,
            })
            chunk["observable_contracts"].append({
                "requirement_id": requirement["id"],
                "actions": _observable_actions(
                    requirement["id"],
                    mechanics,
                    validations,
                ),
            })
        signatures_by_method: dict[str, str] = {}
        for signature in chunk["declaration_contract"].get(
            "callable_signatures", []
        ):
            signature_match = re.match(
                r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                str(signature),
            )
            if signature_match:
                signatures_by_method[signature_match.group(1)] = str(signature)
        proposed_requirement_ids_by_method = {
            str(proposal.get("method_name") or ""): [
                str(value)
                for value in proposal.get("requirement_ids") or []
                if str(value)
            ]
            for proposal in chunk["declaration_contract"].get(
                "inferred_callable_proposals", []
            )
            if isinstance(proposal, Mapping)
            and str(proposal.get("method_name") or "")
        }
        task_eligible_requirement_ids = {
            requirement["id"]
            for requirement in requirements
            if str(
                requirement.get("semantic_role") or "behavior"
            ).casefold() in {"behavior", "integration"}
        }
        chunk["method_tasks"] = []
        for method_name in chunk["declaration_contract"].get(
            "required_methods", []
        ):
            owned_requirement_ids = list(
                proposed_requirement_ids_by_method.get(method_name) or []
            )
            owned_requirement_ids = [
                requirement_id
                for requirement_id in owned_requirement_ids
                if requirement_id in task_eligible_requirement_ids
            ]
            if not owned_requirement_ids:
                owned_requirement_ids = [
                requirement["id"]
                for requirement in requirements
                if (
                    re.search(
                        rf"(?<![.\w]){re.escape(method_name)}\s*\(",
                        requirement["text"],
                    )
                    or (
                        method_name == "__post_init__"
                        and re.search(
                            r"\b(?:reject|invalid|empty|blank|negative)\b",
                            requirement["text"],
                            flags=re.IGNORECASE,
                        )
                    )
                    or (
                        method_name == "__init__"
                        and re.search(
                            r"\b(?:construct|constructor|initialize|field)\b",
                            requirement["text"],
                            flags=re.IGNORECASE,
                        )
                    )
                )
                ]
            if not owned_requirement_ids:
                owned_requirement_ids = [
                    requirement["id"]
                    for requirement in requirements
                    if str(
                        requirement.get("semantic_role") or "behavior"
                    ).casefold()
                    == "behavior"
                ]
            task_mechanics = [
                step
                for row in chunk["implementation_mechanics"]
                if row["requirement_id"] in owned_requirement_ids
                for step in row.get("steps") or []
            ]
            task_validations = [
                check
                for row in chunk["validation_cases"]
                if row["requirement_id"] in owned_requirement_ids
                for check in row.get("checks") or []
            ]
            chunk["method_tasks"].append({
                "name": method_name,
                "signature": signatures_by_method.get(
                    method_name,
                    f"def {method_name}(self)",
                ),
                "requirement_ids": list(dict.fromkeys(owned_requirement_ids)),
                "implementation_mechanics": list(dict.fromkeys(task_mechanics)),
                "validation_cases": list(dict.fromkeys(task_validations)),
            })
        requirement_order = {
            requirement["id"]: index
            for index, requirement in enumerate(requirements)
        }
        required_calls: list[dict[str, Any]] = []
        for evidence_item in chunk.get("evidence") or []:
            if (
                not isinstance(evidence_item, Mapping)
                or not bool(evidence_item.get("selected_for_generation"))
            ):
                continue
            if str(evidence_item.get("usage_role") or "invoke") != "invoke":
                continue
            capability_name = str(evidence_item.get("name") or "")
            signature = str(evidence_item.get("signature") or "")
            if not capability_name:
                continue
            capability_leaf = capability_name.rsplit(".", 1)[-1]
            if (
                not signature
                and capability_leaf[:1].isupper()
            ):
                continue
            raw_supports = evidence_item.get("supports") or []
            supports = (
                [str(value) for value in raw_supports if str(value)]
                if isinstance(raw_supports, (list, tuple, set))
                else [str(raw_supports)]
            )
            support_tokens = {
                token.casefold()
                for support in supports
                for token in re.findall(
                    r"[A-Za-z_][A-Za-z0-9_]{2,}", support
                )
            }
            terminal_tokens = {
                token.casefold()
                for token in re.findall(
                    r"[A-Za-z_][A-Za-z0-9_]{2,}",
                    capability_name.rsplit(".", 1)[-1],
                )
            }
            requirement_ids: list[str] = [
                str(value)
                for value in evidence_item.get("requirement_ids") or []
                if str(value) in requirement_order
            ]
            for requirement in ([] if requirement_ids else requirements):
                requirement_tokens = {
                    token.casefold()
                    for token in re.findall(
                        r"[A-Za-z_][A-Za-z0-9_]{2,}",
                        requirement["text"],
                    )
                }
                if (
                    support_tokens & requirement_tokens
                    or terminal_tokens & requirement_tokens
                ):
                    requirement_ids.append(requirement["id"])
            required_calls.append({
                "name": capability_name,
                "signature": signature,
                "requirement_ids": list(dict.fromkeys(requirement_ids)),
                "import_statement": str(
                    evidence_item.get("import_statement") or ""
                ),
                "parameter_types": {
                    match.group(1): match.group(2).strip()
                    for match in re.finditer(
                        r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^\n]+)$",
                        str(evidence_item.get("source_excerpt") or ""),
                        flags=re.MULTILINE,
                    )
                },
            })
            for requirement_id in requirement_ids:
                observable_contract = next(
                    (
                        item
                        for item in chunk["observable_contracts"]
                        if item.get("requirement_id") == requirement_id
                    ),
                    None,
                )
                if observable_contract is not None:
                    observable_contract["actions"].append({
                        "kind": "verified_call",
                        "mechanic": (
                            f"Call the verified capability `{capability_name}` "
                            + (
                                f"with signature `{signature}`."
                                if signature
                                else (
                                    "using its authoritative indexed callable "
                                    "identity; its runtime signature is unavailable."
                                )
                            )
                        ),
                        "observable": (
                            f"The owning callable invokes `{capability_name}` "
                            f"for {requirement_id}."
                        ),
                    })
        def required_call_order_key(item: Mapping[str, Any]) -> tuple[int, int]:
            requirement_ids = [
                value
                for value in item.get("requirement_ids") or []
                if value in requirement_order
            ]
            requirement_index = min(
                (requirement_order[value] for value in requirement_ids),
                default=len(requirement_order),
            )
            requirement_text = " ".join(
                requirement["text"]
                for requirement in requirements
                if requirement["id"] in requirement_ids
            ).casefold()
            terminal_terms = [
                token
                for token in re.findall(
                    r"[a-z0-9]+",
                    str(item.get("name") or "")
                    .rsplit(".", 1)[-1]
                    .casefold()
                    .replace("_", " "),
                )
                if token not in {"get", "set", "is", "do"}
            ]
            positions = [
                requirement_text.find(token)
                for token in terminal_terms
                if requirement_text.find(token) >= 0
            ]
            return (
                requirement_index,
                min(positions, default=10**6),
            )

        required_calls.sort(key=required_call_order_key)
        chunk["declaration_contract"]["required_calls"] = required_calls
        required_accesses = [
            {
                "name": str(evidence_item.get("name") or ""),
                "requirement_ids": [
                    str(value)
                    for value in evidence_item.get("requirement_ids") or []
                    if str(value) in requirement_order
                ],
            }
            for evidence_item in chunk.get("evidence") or []
            if isinstance(evidence_item, Mapping)
            and bool(evidence_item.get("selected_for_generation"))
            and str(evidence_item.get("usage_role") or "") == "access"
            and str(evidence_item.get("name") or "")
        ]
        chunk["declaration_contract"]["required_accesses"] = required_accesses
        flow_requested = bool(re.search(
            r"\b(?:in\s+(?:this|the\s+following|exact)\s+order|"
            r"call\s+order|ordered\s+(?:call|execution)\s+chain|"
            r"handoff\s+pipeline|execution\s+pipeline|call\s+sequence)\b",
            ". ".join((original_prompt, text)),
            flags=re.IGNORECASE,
        ))
        chunk["declaration_contract"]["required_call_order"] = (
            [item["name"] for item in required_calls]
            if flow_requested and len(required_calls) >= 2
            else []
        )
        if chunk["declaration_contract"]["required_call_order"]:
            chunk["validation_cases"].append({
                "requirement_id": "required_call_order",
                "checks": [
                    "Invoke the orchestration owner and assert the approved external "
                    "calls occur exactly in dependency order: "
                    + " -> ".join(
                        chunk["declaration_contract"]["required_call_order"]
                    )
                    + "."
                ],
            })
        chunk["evidence"] = sorted(
            chunk.get("evidence") or [],
            key=lambda item: (
                0
                if bool(item.get("selected_for_generation"))
                else 1
                if bool(item.get("dependency_for_selected"))
                else 2
                if str(item.get("strength") or "")
                in {"authoritative_signature", "verified_definition"}
                else 3
                if str(item.get("strength") or "") == "official_api_research"
                else 4
                if str(item.get("strength") or "") == "exact_indexed_definition"
                else 6
                if str(item.get("strength") or "") == "indexed_usage_example"
                else 5,
                str(item.get("name") or "").casefold(),
            ),
        )
    capability_contracts: list[dict[str, Any]] = []
    for chunk in chunks:
        for item in chunk.get("evidence") or []:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "")
            signature = str(item.get("signature") or "")
            strength = str(item.get("strength") or "")
            if not name or not signature or strength not in {
                "authoritative_signature",
                "verified_definition",
            }:
                continue
            capability_contracts.append({
                "owner": str(chunk.get("owner") or ""),
                "name": name,
                "signature": signature,
                "provider": str(item.get("provider") or ""),
                "provenance": str(item.get("provenance") or ""),
                "strength": strength,
                "supports": list(item.get("supports") or []),
                "query_links": list(item.get("query_links") or []),
                "selected_for_generation": bool(
                    item.get("selected_for_generation")
                ),
                "dependency_for_selected": bool(
                    item.get("dependency_for_selected")
                ),
            })
    plan["validated_capability_contracts"] = list({
        (
            item["owner"],
            item["name"],
            item["signature"],
        ): item
        for item in capability_contracts
    }.values())

    for chunk in chunks:
        declaration_contract = chunk.get("declaration_contract") or {}
        required_methods = [
            str(value)
            for value in declaration_contract.get("required_methods") or []
            if str(value)
        ]
        existing_tasks = {
            str(item.get("name") or ""): item
            for item in chunk.get("method_tasks") or []
            if isinstance(item, Mapping) and str(item.get("name") or "")
        }
        signatures_by_method = {}
        for signature in declaration_contract.get("callable_signatures") or []:
            signature_match = re.match(
                r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                str(signature),
            )
            if signature_match:
                signatures_by_method[signature_match.group(1)] = str(signature)
        mechanics_by_requirement = {
            str(item.get("requirement_id") or ""): list(item.get("steps") or [])
            for item in chunk.get("implementation_mechanics") or []
            if isinstance(item, Mapping)
        }
        validations_by_requirement = {
            str(item.get("requirement_id") or ""): list(item.get("checks") or [])
            for item in chunk.get("validation_cases") or []
            if isinstance(item, Mapping)
        }
        requirements = _requirement_texts(chunk)
        proposed_requirement_ids_by_method = {
            str(proposal.get("method_name") or ""): [
                str(value)
                for value in proposal.get("requirement_ids") or []
                if str(value)
            ]
            for proposal in declaration_contract.get(
                "inferred_callable_proposals", []
            )
            if isinstance(proposal, Mapping)
            and str(proposal.get("method_name") or "")
        }
        local_requirement_roles = {
            requirement["id"]: str(
                requirement.get("semantic_role") or "behavior"
            ).casefold()
            for requirement in requirements
        }
        task_eligible_requirement_ids = {
            requirement_id
            for requirement_id, semantic_role in local_requirement_roles.items()
            if semantic_role in {"behavior", "integration"}
        }
        len_protocol_requested = bool(
            re.search(
                r"\blen\([^()]+\)\s+(?:reports?|returns?|gives?|yields?)\b",
                original_prompt,
                flags=re.IGNORECASE,
            )
        )

        def normalize_protocol_name(name: str) -> str:
            """Return a grounded owned method name for protocol prose.

            :param name: Candidate method name.
            :return: Normalized method name or an empty string.
            """

            if name == "len" and len_protocol_requested:
                return "__len__"
            if name.casefold() not in _MODULE_CALLABLES:
                return name
            explicitly_declared = bool(
                re.search(
                    rf"\b(?:method|function|callable)\s+(?:named\s+)?"
                    rf"`?{re.escape(name)}`?\b"
                    rf"|\b(?:add|create|define|implement)\s+(?:the\s+)?"
                    rf"`?{re.escape(name)}`?\s+(?:method|function|callable)\b",
                    original_prompt,
                    flags=re.IGNORECASE,
                )
            )
            return name if explicitly_declared else ""

        normalized_existing_tasks: dict[str, dict[str, Any]] = {}
        for task_name, task in existing_tasks.items():
            normalized_name = normalize_protocol_name(task_name)
            if not normalized_name:
                continue
            normalized_task = dict(task)
            normalized_task["name"] = normalized_name
            normalized_task["signature"] = re.sub(
                rf"^((?:async\s+)?def\s+){re.escape(task_name)}(\s*\()",
                rf"\1{normalized_name}\2",
                str(normalized_task.get("signature") or ""),
                count=1,
            )
            normalized_existing_tasks[normalized_name] = normalized_task
        existing_tasks = normalized_existing_tasks
        normalized_required_methods: list[str] = []
        for method_name in required_methods:
            normalized_name = normalize_protocol_name(method_name)
            if normalized_name and normalized_name not in normalized_required_methods:
                normalized_required_methods.append(normalized_name)
        required_methods = normalized_required_methods
        declaration_contract["required_methods"] = required_methods
        declaration_contract["callable_signatures"] = [
            re.sub(
                r"^((?:async\s+)?def\s+)len(\s*\()",
                r"\1__len__\2",
                str(signature),
                count=1,
            )
            for signature in declaration_contract.get("callable_signatures") or []
            if not (
                (match := re.match(
                    r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                    str(signature).strip(),
                ))
                and not normalize_protocol_name(match.group(1))
            )
        ]
        signatures_by_method = {}
        for signature in declaration_contract.get("callable_signatures") or []:
            signature_match = re.match(
                r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                str(signature),
            )
            if signature_match:
                signatures_by_method[signature_match.group(1)] = str(signature)
        for method_name in required_methods:
            requirement_ids = list(
                proposed_requirement_ids_by_method.get(method_name) or []
            )
            requirement_ids = [
                requirement_id
                for requirement_id in requirement_ids
                if requirement_id in task_eligible_requirement_ids
            ]
            if not requirement_ids:
                requirement_ids = [
                requirement["id"]
                for requirement in requirements
                if (
                    re.search(
                        rf"(?<![.\w]){re.escape(method_name)}\s*\(",
                        requirement["text"],
                    )
                    or (
                        method_name == "__post_init__"
                        and re.search(
                            r"\b(?:reject|invalid|empty|blank|negative)\b",
                            requirement["text"],
                            flags=re.IGNORECASE,
                        )
                    )
                )
                ]
            if not requirement_ids:
                requirement_ids = [
                    requirement["id"]
                    for requirement in requirements
                    if str(
                        requirement.get("semantic_role") or "behavior"
                    ).casefold()
                    == "behavior"
                ]
            if method_name in existing_tasks:
                existing_tasks[method_name]["requirement_ids"] = list(
                    dict.fromkeys(requirement_ids)
                )
                existing_tasks[method_name][
                    "implementation_mechanics"
                ] = list(dict.fromkeys(
                    step
                    for requirement_id in requirement_ids
                    for step in mechanics_by_requirement.get(
                        requirement_id, []
                    )
                ))
                existing_tasks[method_name]["validation_cases"] = list(
                    dict.fromkeys(
                        check
                        for requirement_id in requirement_ids
                        for check in validations_by_requirement.get(
                            requirement_id, []
                        )
                    )
                )
                continue
            existing_tasks[method_name] = {
                "name": method_name,
                "signature": signatures_by_method.get(
                    method_name,
                    f"def {method_name}(self)",
                ),
                "requirement_ids": list(dict.fromkeys(requirement_ids)),
                "implementation_mechanics": list(dict.fromkeys(
                    step
                    for requirement_id in requirement_ids
                    for step in mechanics_by_requirement.get(requirement_id, [])
                )),
                "validation_cases": list(dict.fromkeys(
                    check
                    for requirement_id in requirement_ids
                    for check in validations_by_requirement.get(requirement_id, [])
                )),
            }
        if str(chunk.get("kind") or "") == "class":
            interactive_requirements = {
                requirement["id"]: requirement
                for requirement in requirements
                if re.search(
                    r"\b(?:qt|pyside[26]?|pyqt[56]?|ui|dialog|window|"
                    r"widget|panel)\b",
                    requirement["text"],
                    flags=re.IGNORECASE,
                )
                and re.search(
                    r"\b(?:button|connect|control|field|filter|input|"
                    r"progress|selection|signal|slot|status)\b",
                    requirement["text"],
                    flags=re.IGNORECASE,
                )
            }
            selected_calls_by_requirement: dict[str, list[dict[str, Any]]] = {}
            for required_call in declaration_contract.get("required_calls") or []:
                if not isinstance(required_call, Mapping):
                    continue
                for requirement_id in required_call.get("requirement_ids") or []:
                    if str(requirement_id) in interactive_requirements:
                        selected_calls_by_requirement.setdefault(
                            str(requirement_id),
                            [],
                        ).append(dict(required_call))
            for requirement_id, selected_calls in (
                selected_calls_by_requirement.items()
            ):
                if any(
                    requirement_id in {
                        str(value)
                        for value in task.get("requirement_ids") or []
                    }
                    and str(task.get("name") or "") != "__init__"
                    for task in existing_tasks.values()
                ):
                    continue
                selected_call = selected_calls[0]
                callable_leaf = str(
                    selected_call.get("name") or "requested_operation"
                ).rsplit(".", 1)[-1]
                callable_leaf = re.sub(
                    r"[^A-Za-z0-9_]+",
                    "_",
                    callable_leaf,
                ).strip("_").casefold() or "requested_operation"
                handler_name = f"_on_{callable_leaf}"
                signature = f"def {handler_name}(self) -> None"
                existing_tasks[handler_name] = {
                    "name": handler_name,
                    "signature": signature,
                    "visibility": "private",
                    "requirement_ids": [requirement_id],
                    "implementation_mechanics": [
                        "Read the requirement-owned UI controls and convert their "
                        "values to the verified callable's parameter contract.",
                        "Invoke the selected verified callable exactly once with "
                        "those values when the requirement-owned UI action fires.",
                        "Expose the returned result through the UI and surface "
                        "failures through a visible error path without swallowing "
                        "the exception.",
                    ],
                    "validation_cases": [
                        "Trigger the connected UI action and assert the verified "
                        "callable receives the control-derived arguments.",
                        "Assert the returned value and failure path are both "
                        "observable through the UI.",
                    ],
                }
                required_methods = list(
                    declaration_contract.get("required_methods") or []
                )
                if handler_name not in required_methods:
                    required_methods.append(handler_name)
                declaration_contract["required_methods"] = required_methods
                callable_signatures = list(
                    declaration_contract.get("callable_signatures") or []
                )
                if signature not in callable_signatures:
                    callable_signatures.append(signature)
                declaration_contract["callable_signatures"] = callable_signatures
        normalized_tasks: list[dict[str, Any]] = []
        len_protocol_requested = bool(
            re.search(
                r"\blen\([^()]+\)\s+(?:reports?|returns?|gives?|yields?)\b",
                original_prompt,
                flags=re.IGNORECASE,
            )
        )

        def normalized_protocol_method(name: str) -> str:
            """Map builtin protocol prose to an owned dunder, or reject it.

            :param name: Candidate class method name.
            :return: Grounded method name or an empty string.
            """

            if name == "len" and len_protocol_requested:
                return "__len__"
            if name.casefold() not in _MODULE_CALLABLES:
                return name
            explicitly_declared = bool(
                re.search(
                    rf"\b(?:method|function|callable)\s+(?:named\s+)?"
                    rf"`?{re.escape(name)}`?\b"
                    rf"|\b(?:add|create|define|implement)\s+(?:the\s+)?"
                    rf"`?{re.escape(name)}`?\s+(?:method|function|callable)\b",
                    original_prompt,
                    flags=re.IGNORECASE,
                )
            )
            return name if explicitly_declared else ""

        normalized_required_methods: list[str] = []
        for method_name in declaration_contract.get("required_methods") or []:
            normalized_name = normalized_protocol_method(str(method_name))
            if normalized_name and normalized_name not in normalized_required_methods:
                normalized_required_methods.append(normalized_name)
        declaration_contract["required_methods"] = normalized_required_methods
        normalized_signatures: list[str] = []
        for signature in declaration_contract.get("callable_signatures") or []:
            signature_text = str(signature)
            signature_match = re.match(
                r"^((?:async\s+)?def\s+)([A-Za-z_][A-Za-z0-9_]*)(\s*\()",
                signature_text.strip(),
            )
            if signature_match:
                normalized_name = normalized_protocol_method(
                    signature_match.group(2)
                )
                if not normalized_name:
                    continue
                signature_text = re.sub(
                    rf"^((?:async\s+)?def\s+){re.escape(signature_match.group(2))}(\s*\()",
                    rf"\1{normalized_name}\2",
                    signature_text,
                    count=1,
                )
            if signature_text not in normalized_signatures:
                normalized_signatures.append(signature_text)
        declaration_contract["callable_signatures"] = normalized_signatures
        for task in existing_tasks.values():
            task = dict(task)
            original_task_name = str(task.get("name") or "")
            task_name = normalized_protocol_method(original_task_name)
            if not task_name:
                continue
            if task_name != original_task_name:
                task["name"] = task_name
                task["signature"] = re.sub(
                    rf"^((?:async\s+)?def\s+){re.escape(original_task_name)}(\s*\()",
                    rf"\1{task_name}\2",
                    str(task.get("signature") or ""),
                    count=1,
                )
            explicitly_requested = bool(
                task_name
                and re.search(
                    (
                        r"\blen\([^()]+\)"
                        if task_name == "__len__"
                        else rf"(?<![A-Za-z0-9_]){re.escape(task_name)}\("
                    ),
                    original_prompt,
                )
            )
            permitted_requirement_ids = (
                set(local_requirement_roles)
                if explicitly_requested
                else task_eligible_requirement_ids
            )
            task["requirement_ids"] = [
                str(value)
                for value in task.get("requirement_ids") or []
                if str(value) in permitted_requirement_ids
            ]
            if task["requirement_ids"]:
                normalized_tasks.append(task)
        chunk["method_tasks"] = normalized_tasks
        normalized_task_names = {
            str(task.get("name") or "")
            for task in normalized_tasks
            if str(task.get("name") or "")
        }
        removed_ungrounded_methods = {
            str(method_name)
            for method_name in declaration_contract.get("required_methods") or []
            if str(method_name) not in normalized_task_names
            and not re.search(
                (
                    r"\blen\([^()]+\)"
                    if str(method_name) == "__len__"
                    else rf"(?<![A-Za-z0-9_]){re.escape(str(method_name))}\("
                ),
                original_prompt,
            )
        }
        if removed_ungrounded_methods:
            declaration_contract["required_methods"] = [
                str(method_name)
                for method_name in declaration_contract.get("required_methods") or []
                if str(method_name) not in removed_ungrounded_methods
            ]
            declaration_contract["callable_signatures"] = [
                str(signature)
                for signature in declaration_contract.get("callable_signatures") or []
                if not any(
                    re.match(
                        rf"^(?:async\s+)?def\s+{re.escape(method_name)}\s*\(",
                        str(signature).strip(),
                    )
                    for method_name in removed_ungrounded_methods
                )
            ]
            declaration_contract["inferred_callable_proposals"] = [
                proposal
                for proposal in declaration_contract.get(
                    "inferred_callable_proposals", []
                )
                if not isinstance(proposal, Mapping)
                or str(proposal.get("method_name") or "")
                not in removed_ungrounded_methods
            ]
            chunk["declaration_contract"] = declaration_contract

    proposals = _propose_cross_file_interfaces(chunks)
    prompt_lower = str(original_prompt or "").casefold()
    rejected_proposal_ids = {
        (
            str(item.get("producer_chunk") or ""),
            str(item.get("consumer_chunk") or ""),
            str(item.get("signature") or ""),
        )
        for item in proposals
        if bool(item.get("approval_required"))
        and not any(
            token.casefold() in prompt_lower
            for token in re.findall(
                r"\b(?:def\s+)?([a-z_][A-Za-z0-9_]*)\s*\(",
                str(item.get("signature") or ""),
            )
        )
    }
    if rejected_proposal_ids:
        proposals = [
            item
            for item in proposals
            if (
                str(item.get("producer_chunk") or ""),
                str(item.get("consumer_chunk") or ""),
                str(item.get("signature") or ""),
            )
            not in rejected_proposal_ids
        ]
        for chunk in chunks:
            for key in (
                "proposed_interfaces",
                "required_dependency_interfaces",
            ):
                chunk[key] = [
                    item
                    for item in chunk.get(key) or []
                    if (
                        str(item.get("producer_chunk") or ""),
                        str(item.get("consumer_chunk") or ""),
                        str(item.get("signature") or ""),
                    )
                    not in rejected_proposal_ids
                ]
    plan["proposed_interfaces"] = proposals
    plan["approval_questions"] = [
        (
            f"Approve `{item['signature']}` on producer chunk "
            f"`{item['producer_chunk']}` for consumer "
            f"`{item['consumer_chunk']}`: {item['reason']}"
        )
        for item in proposals
        if bool(item.get("approval_required"))
    ]
    plan["original_request"] = str(original_prompt or "")
    plan["baseline_quality_contract"] = {
        "syntax_valid": True,
        "imports_resolve_or_are_verified_host_local": True,
        "public_interfaces_are_completely_typed": True,
        "public_any_annotations_forbidden_when_concrete_types_are_inferable": True,
        "public_docstrings_are_substantive_and_complete": True,
        "placeholder_bodies_forbidden": True,
        "invented_dependencies_and_public_symbols_forbidden": True,
        "public_constructor_parameters_require_request_or_api_ownership": True,
        "requested_behavior_must_be_reachable": True,
        "introduced_dead_code_forbidden": True,
        "unreferenced_private_helpers_forbidden": True,
        "duplicate_behavior_implementations_forbidden": True,
        "ordered_results_require_stable_tie_breakers": True,
        "named_exclusions_use_canonical_exact_matching": True,
        "iterative_progress_uses_real_work_totals": True,
        "background_workers_prevent_overlapping_starts": True,
        "background_workers_connect_finished_cleanup": True,
        "api_calls_require_authoritative_evidence": True,
        "unrelated_existing_behavior_must_be_preserved": True,
        "completion_requires_clean_deterministic_and_behavioral_validation": True,
    }
    plan["generation_contract"] = {
        "consume_this_plan_verbatim": True,
        "one_initial_generation_per_file": True,
        "owner_capsules_are_the_only_generation_units": True,
        "package_replanning_after_approval": False,
        "valid_owner_hashes_are_immutable": True,
        "existing_file_repairs_are_symbol_scoped": True,
        "new_file_repairs_are_owner_or_callable_scoped_after_initial_assembly": True,
        "full_file_replace_existing_nonempty_file": False,
        "full_file_regeneration_after_owner_generation": False,
        "completion_requires_all_validation_cases": True,
        "final_semantic_review_covers_only_unproven_requirements": True,
        "apply_only_after_all_quality_gates_pass": True,
    }

    def normalize_speculative_private_methods(chunk: dict[str, Any]) -> None:
        """Keep private declarations mandatory only when request or protocol owned."""

        declaration_contract = chunk.get("declaration_contract") or {}
        method_tasks = [
            task
            for task in chunk.get("method_tasks") or []
            if isinstance(task, dict)
        ]
        if not method_tasks:
            return
        execution_constraints = declaration_contract.get(
            "execution_constraints"
        ) or {}
        request_text = str(original_prompt or "")
        protocol_owner = bool(
            execution_constraints.get("requires_off_ui_thread")
        )

        def method_name_from_signature(signature: str) -> str:
            match = re.match(
                r"\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                str(signature or ""),
            )
            return match.group(1) if match else ""

        def merge_concrete_types(
            public_signature: str,
            private_signature: str,
        ) -> str:
            try:
                public_node = ast.parse(
                    public_signature.rstrip().rstrip(":") + ":\n    pass\n"
                ).body[0]
                private_node = ast.parse(
                    private_signature.rstrip().rstrip(":") + ":\n    pass\n"
                ).body[0]
            except SyntaxError:
                return public_signature
            if not isinstance(public_node, ast.FunctionDef) or not isinstance(
                private_node, ast.FunctionDef
            ):
                return public_signature
            private_arguments = {
                argument.arg: argument
                for argument in [
                    *private_node.args.posonlyargs,
                    *private_node.args.args,
                    *private_node.args.kwonlyargs,
                ]
            }
            for argument in [
                *public_node.args.posonlyargs,
                *public_node.args.args,
                *public_node.args.kwonlyargs,
            ]:
                private_argument = private_arguments.get(argument.arg)
                if (
                    private_argument is not None
                    and private_argument.annotation is not None
                    and (
                        argument.annotation is None
                        or ast.unparse(argument.annotation) == "Any"
                    )
                    and ast.unparse(private_argument.annotation) != "Any"
                ):
                    argument.annotation = private_argument.annotation
            if (
                private_node.returns is not None
                and (
                    public_node.returns is None
                    or ast.unparse(public_node.returns) == "Any"
                )
                and ast.unparse(private_node.returns) != "Any"
            ):
                public_node.returns = private_node.returns
            return ast.unparse(public_node).splitlines()[0].rstrip(":")

        inferred_public_method_names = {
            str(item.get("method_name") or "")
            for item in declaration_contract.get(
                "inferred_callable_proposals"
            ) or []
            if isinstance(item, Mapping)
            and str(item.get("method_name") or "")
        }
        public_tasks = [
            task
            for task in method_tasks
            if not str(task.get("name") or "").startswith("_")
            and str(task.get("name") or "")
            not in inferred_public_method_names
        ]
        removed_names: set[str] = set()
        retained_tasks: list[dict[str, Any]] = []
        for task in method_tasks:
            task_name = str(task.get("name") or "")
            explicitly_requested = bool(re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(task_name)}\s*\(",
                request_text,
            ))
            speculative_public_helper = bool(
                task_name in inferred_public_method_names
                and not explicitly_requested
            )
            if (
                (not task_name.startswith("_") or task_name.startswith("__"))
                and not speculative_public_helper
            ):
                retained_tasks.append(task)
                continue
            task_text = " ".join(
                str(value)
                for value in task.get("implementation_mechanics") or []
            ).casefold()
            protocol_required = protocol_owner and any(
                token in task_text
                for token in (
                    "worker",
                    "signal",
                    "ui action",
                    "ui owner",
                    "progress control",
                    "status control",
                    "background",
                    "completion",
                    "error",
                )
            )
            if explicitly_requested or protocol_required:
                retained_tasks.append(task)
                continue
            task_requirement_ids = {
                str(value) for value in task.get("requirement_ids") or []
            }
            target = max(
                public_tasks,
                key=lambda public_task: len(
                    task_requirement_ids
                    & {
                        str(value)
                        for value in public_task.get("requirement_ids") or []
                    }
                ),
                default=None,
            )
            if target is None:
                retained_tasks.append(task)
                continue
            for key in (
                "requirement_ids",
                "implementation_mechanics",
                "validation_cases",
                "behavior_ids",
            ):
                target[key] = list(dict.fromkeys([
                    *[str(value) for value in target.get(key) or []],
                    *[str(value) for value in task.get(key) or []],
                ]))
            old_target_signature = str(target.get("signature") or "")
            target["signature"] = merge_concrete_types(
                old_target_signature,
                str(task.get("signature") or ""),
            )
            removed_names.add(task_name)
        if not removed_names:
            return
        signature_replacements = {
            str(task.get("name") or ""): str(task.get("signature") or "")
            for task in retained_tasks
        }
        declaration_contract["callable_signatures"] = list(dict.fromkeys(
            signature_replacements.get(
                method_name_from_signature(str(signature)),
                str(signature),
            )
            for signature in declaration_contract.get(
                "callable_signatures"
            ) or []
            if method_name_from_signature(str(signature)) not in removed_names
        ))
        declaration_contract["required_methods"] = [
            str(name)
            for name in declaration_contract.get("required_methods") or []
            if str(name) not in removed_names
        ]
        chunk["declaration_contract"] = declaration_contract
        chunk["method_tasks"] = retained_tasks
        chunk["optional_private_implementation_methods"] = sorted(
            removed_names
        )

    for chunk in chunks:
        if isinstance(chunk, dict):
            _materialize_threaded_progress_declarations(chunk)
            normalize_speculative_private_methods(chunk)
            if str(chunk.get("kind") or "") != "class":
                continue
            declaration_contract = chunk.get("declaration_contract") or {}
            if not isinstance(declaration_contract, dict):
                continue
            len_protocol_requested = bool(
                re.search(
                    r"\blen\([^()]+\)\s+(?:reports?|returns?|gives?|yields?)\b",
                    original_prompt,
                    flags=re.IGNORECASE,
                )
            )

            def explicitly_requested_method_contract(name: str) -> bool:
                """Return whether prose presents a built-in name as an API method.

                :param name: Candidate method name.
                :return: Whether the request explicitly assigns method behavior.
                """

                return bool(re.search(
                    rf"(?<![.\w]){re.escape(name)}\s*\([^)]*\)\s+"
                    r"(?:must\s+|shall\s+|should\s+)?"
                    r"(?:adds?|appends?|clears?|creates?|deletes?|gets?|"
                    r"preserves?|removes?|reports?|resets?|returns?|sets?|stores?|"
                    r"updates?|validates?|yields?)\b",
                    original_prompt,
                    flags=re.IGNORECASE,
                ))

            def final_method_name(name: str) -> str:
                """Return the final grounded method name.

                :param name: Candidate method name.
                :return: Grounded name or an empty string.
                """

                if name == "len" and len_protocol_requested:
                    return "__len__"
                if (
                    name.casefold() in _MODULE_CALLABLES
                    and not explicitly_requested_method_contract(name)
                ):
                    return ""
                return name

            final_tasks: list[dict[str, Any]] = []
            for task in chunk.get("method_tasks") or []:
                if not isinstance(task, Mapping):
                    continue
                old_name = str(task.get("name") or "")
                new_name = final_method_name(old_name)
                if not new_name:
                    continue
                normalized_task = dict(task)
                normalized_task["name"] = new_name
                normalized_task["signature"] = re.sub(
                    rf"^((?:async\s+)?def\s+){re.escape(old_name)}(\s*\()",
                    rf"\1{new_name}\2",
                    str(task.get("signature") or ""),
                    count=1,
                )
                final_tasks.append(normalized_task)
            chunk["method_tasks"] = list({
                str(task.get("name") or ""): task
                for task in final_tasks
            }.values())
            final_required: list[str] = []
            for name in declaration_contract.get("required_methods") or []:
                normalized_name = final_method_name(str(name))
                if normalized_name and normalized_name not in final_required:
                    final_required.append(normalized_name)
            declaration_contract["required_methods"] = final_required
            final_signatures: list[str] = []
            for signature in declaration_contract.get("callable_signatures") or []:
                text = str(signature)
                match = re.match(
                    r"^((?:async\s+)?def\s+)([A-Za-z_][A-Za-z0-9_]*)(\s*\()",
                    text.strip(),
                )
                if match:
                    normalized_name = final_method_name(match.group(2))
                    if not normalized_name:
                        continue
                    text = re.sub(
                        rf"^((?:async\s+)?def\s+){re.escape(match.group(2))}(\s*\()",
                        rf"\1{normalized_name}\2",
                        text,
                        count=1,
                    )
                if text not in final_signatures:
                    final_signatures.append(text)
            declaration_contract["callable_signatures"] = final_signatures
            chunk["declaration_contract"] = declaration_contract
    return plan


def validate_implementation_plan_completeness(
    implementation_plan: Mapping[str, Any],
    *,
    original_prompt: str = "",
) -> list[str]:
    """Reject plans that cannot serve as bounded generation contracts."""

    errors: list[str] = []
    len_protocol_requested = bool(
        re.search(
            r"\blen\([^()]+\)\s+(?:reports?|returns?|gives?|yields?)\b",
            original_prompt,
            flags=re.IGNORECASE,
        )
    )
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, dict) or str(chunk.get("kind") or "") != "class":
            continue
        contract = chunk.get("declaration_contract") or {}
        if not isinstance(contract, dict):
            continue

        def grounded_name(name: str) -> str:
            if name == "len" and len_protocol_requested:
                return "__len__"
            return "" if name.casefold() in _MODULE_CALLABLES else name

        normalized_tasks: list[dict[str, Any]] = []
        for task in chunk.get("method_tasks") or []:
            if not isinstance(task, Mapping):
                continue
            old_name = str(task.get("name") or "")
            name = grounded_name(old_name)
            if not name:
                continue
            item = dict(task)
            item["name"] = name
            item["signature"] = re.sub(
                rf"^((?:async\s+)?def\s+){re.escape(old_name)}(\s*\()",
                rf"\1{name}\2",
                str(item.get("signature") or ""),
                count=1,
            )
            normalized_tasks.append(item)
        chunk["method_tasks"] = list({
            str(item.get("name") or ""): item for item in normalized_tasks
        }.values())
        required: list[str] = []
        for value in contract.get("required_methods") or []:
            name = grounded_name(str(value))
            if name and name not in required:
                required.append(name)
        contract["required_methods"] = required
        signatures: list[str] = []
        for value in contract.get("callable_signatures") or []:
            signature = str(value)
            match = re.match(
                r"^((?:async\s+)?def\s+)([A-Za-z_][A-Za-z0-9_]*)(\s*\()",
                signature.strip(),
            )
            if match:
                name = grounded_name(match.group(2))
                if not name:
                    continue
                signature = re.sub(
                    rf"^((?:async\s+)?def\s+){re.escape(match.group(2))}(\s*\()",
                    rf"\1{name}\2",
                    signature,
                    count=1,
                )
            if signature not in signatures:
                signatures.append(signature)
        contract["callable_signatures"] = signatures
    coverage = {
        str(item.get("requirement_id") or ""): list(item.get("owners") or [])
        for item in implementation_plan.get("requirement_coverage") or []
        if isinstance(item, Mapping)
    }
    def canonical_declaration(path: Any, owner: Any) -> tuple[str, str]:
        return (
            str(Path(str(path or "")).resolve())
            .replace("\\", "/")
            .casefold(),
            str(owner or "").strip(),
        )

    expected_declarations = {
        canonical_declaration(item.get("file"), item.get("owner"))
        for item in implementation_plan.get("expected_declarations") or []
        if isinstance(item, Mapping) and str(item.get("owner") or "")
    }
    planned_declarations = {
        canonical_declaration(
            chunk.get("path") or chunk.get("file"),
            chunk.get("owner"),
        )
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and str(chunk.get("owner") or "") != "<module>"
    }
    planned_declarations.update({
        canonical_declaration(
            chunk.get("path") or chunk.get("file"),
            helper.get("owner"),
        )
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for declaration_contract in [chunk.get("declaration_contract") or {}]
        if isinstance(declaration_contract, Mapping)
        for helper in declaration_contract.get("helper_declarations") or []
        if isinstance(helper, Mapping) and str(helper.get("owner") or "")
    })
    chunk_by_id = {
        str(chunk.get("chunk_id") or ""): chunk
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping) and str(chunk.get("chunk_id") or "")
    }
    for file_path, owner in sorted(expected_declarations):
        if (file_path, owner) not in planned_declarations:
            errors.append(
                f"Requested declaration `{owner}` in `{file_path}` has no plan chunk."
            )
    for file_path, owner in sorted(planned_declarations):
        if expected_declarations and (file_path, owner) not in expected_declarations:
            errors.append(
                f"Plan owner `{owner}` in `{file_path}` is not a requested declaration."
            )
    for requirement_id, owners in coverage.items():
        if not requirement_id or not owners:
            errors.append(
                f"Requirement `{requirement_id or '<missing>'}` has no owner."
            )
            continue
        for owner_id in owners:
            owner_chunk = chunk_by_id.get(str(owner_id))
            if owner_chunk is None:
                errors.append(
                    f"Requirement `{requirement_id}` references unknown declaration "
                    f"owner `{owner_id}`."
                )
                continue
            if str(owner_chunk.get("kind") or "") != "module":
                continue
            requirement_row = next(
                (
                    item
                    for item in owner_chunk.get("requirements") or []
                    if isinstance(item, Mapping)
                    and str(
                        item.get("id") or item.get("requirement_id") or ""
                    )
                    == requirement_id
                ),
                {},
            )
            requirement_text = str(requirement_row.get("text") or "")
            semantic_role = str(
                requirement_row.get("semantic_role") or "behavior"
            ).casefold()
            declaration_contract = (
                owner_chunk.get("declaration_contract")
                if isinstance(
                    owner_chunk.get("declaration_contract"), Mapping
                )
                else {}
            )
            deliberately_module_owned = bool(
                semantic_role in {
                    "structure",
                    "file_contract",
                    "package_contract",
                    "module",
                    "quality",
                    "documentation",
                    "constraint",
                }
                or
                declaration_contract.get("module_entry_point_required")
                or re.search(
                    r"\b(?:__main__|entry\s+point|module\s+docstring|imports?|"
                    r"constants?|exports?|package\s+wiring|module[- ]level\s+"
                    r"(?:registration|initialization|configuration))\b",
                    requirement_text,
                    flags=re.IGNORECASE,
                )
            )
            if not deliberately_module_owned:
                errors.append(
                    f"Behavioral requirement `{requirement_id}` is owned only by "
                    f"module declaration `{owner_id}` without an explicit "
                    "module-operation contract."
                )
    generic_mechanic = (
        "Implement the requirement inside its approved owner without adding "
        "undeclared public behavior."
    )
    requirement_text_by_id = {
        str(requirement.get("id") or requirement.get("requirement_id") or ""): str(
            requirement.get("text") or requirement.get("requirement") or ""
        )
        for requirement in (
            implementation_plan.get("requirements")
            or implementation_plan.get("requirement_ledger")
            or []
        )
        if isinstance(requirement, Mapping)
    }
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        mechanics_by_requirement = {
            str(item.get("requirement_id") or ""): [
                str(step).strip()
                for step in item.get("steps") or []
                if str(step).strip()
            ]
            for item in chunk.get("implementation_mechanics") or []
            if isinstance(item, Mapping)
        }
        observables_by_requirement = {
            str(item.get("requirement_id") or ""): [
                action
                for action in item.get("actions") or []
                if isinstance(action, Mapping)
                and str(action.get("kind") or "")
                and str(action.get("observable") or "").strip()
            ]
            for item in chunk.get("observable_contracts") or []
            if isinstance(item, Mapping)
        }
        requirement_evidence = {
            str(item.get("requirement_id") or ""): item
            for item in chunk.get("requirement_evidence") or []
            if isinstance(item, Mapping)
        }
        for requirement in chunk.get("requirements") or []:
            if not isinstance(requirement, Mapping):
                continue
            requirement_id = str(
                requirement.get("id")
                or requirement.get("requirement_id")
                or ""
            )
            semantic_role = str(
                requirement.get("semantic_role") or "behavior"
            ).casefold()
            if semantic_role in {
                "constant",
                "entry_point",
                "export",
                "file_contract",
                "import",
                "imports",
                "module",
                "module_wiring",
                "package_contract",
                "package_wiring",
                "quality",
                "documentation",
                "constraint",
                "structure",
            }:
                continue
            steps = mechanics_by_requirement.get(requirement_id, [])
            if not steps or steps == [generic_mechanic]:
                errors.append(
                    f"Implementation plan has no concrete mechanics for "
                    f"`{requirement_id}` in `{chunk.get('chunk_id') or '<missing>'}`."
                )
            placeholder_steps = [
                step
                for step in steps
                if re.search(
                    r"\b(?:as needed|todo|tbd|placeholder|implement later|"
                    r"fill in|your code here|not implemented)\b|\.\.\.",
                    step,
                    flags=re.IGNORECASE,
                )
            ]
            if placeholder_steps:
                errors.append(
                    "Implementation plan contains placeholder mechanics for "
                    f"`{requirement_id}` in "
                    f"`{chunk.get('chunk_id') or '<missing>'}`."
                )
            if not observables_by_requirement.get(requirement_id):
                errors.append(
                    f"Implementation plan has no machine-inspectable observable "
                    f"contract for `{requirement_id}` in "
                    f"`{chunk.get('chunk_id') or '<missing>'}`."
                )
            evidence_contract = requirement_evidence.get(requirement_id, {})
            declaration_contract = (
                chunk.get("declaration_contract")
                if isinstance(chunk.get("declaration_contract"), Mapping)
                else {}
            )
            has_existing_callable_contract = False
            if bool(chunk.get("existing_declaration")):
                for raw_signature in declaration_contract.get(
                    "callable_signatures"
                ) or []:
                    signature = re.sub(
                        r"\)\s*:\s*->\s*",
                        ") -> ",
                        str(raw_signature).strip(),
                    ).rstrip(":").strip()
                    try:
                        parsed_signature = ast.parse(
                            signature + ":\n    pass"
                        )
                    except SyntaxError:
                        continue
                    if (
                        len(parsed_signature.body) == 1
                        and isinstance(
                            parsed_signature.body[0],
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                    ):
                        has_existing_callable_contract = True
                        break
            if (
                bool(evidence_contract.get("requires_callable_evidence"))
                and not has_existing_callable_contract
                and not any(
                    bool(item.get("selected_for_generation"))
                    and str(item.get("signature") or "")
                    and str(item.get("kind") or "").casefold()
                    not in {"class", "module", "property", "attribute"}
                    and not str(item.get("signature") or "")
                    .lstrip()
                    .casefold()
                    .startswith("class ")
                    and (
                        str(item.get("kind") or "").casefold()
                        in {
                            "function",
                            "method",
                            "async_function",
                            "async_method",
                        }
                        or "(" in str(item.get("signature") or "")
                    )
                    for item in evidence_contract.get("evidence") or []
                    if isinstance(item, Mapping)
                )
            ):
                errors.append(
                    f"API-relevant requirement `{requirement_id}` has no selected "
                    "callable definition with an exact signature."
                )
    global_dependency_policy = (
        implementation_plan.get("dependency_policy")
        if isinstance(implementation_plan.get("dependency_policy"), Mapping)
        else {}
    )
    package_selected_evidence_names = {
        str(item.get("name") or "").casefold()
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for item in chunk.get("evidence") or []
        if isinstance(item, Mapping)
        and bool(item.get("selected_for_generation"))
    }
    generated_owner_names = {
        value
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for path in [str(chunk.get("path") or "").replace("\\", "/")]
        if path
        for value in {
            path.casefold(),
            Path(path).name.casefold(),
            Path(path).stem.casefold(),
            path.removesuffix(".py").replace("/", ".").casefold(),
        }
    }
    for required_owner in global_dependency_policy.get("required_owners") or []:
        required_owner_text = str(required_owner).casefold()
        required_owner_leaf = required_owner_text.rsplit(".", 1)[-1]
        if (
            required_owner_text in generated_owner_names
            or required_owner_leaf in generated_owner_names
            or required_owner_text.removesuffix(".py") in generated_owner_names
        ):
            continue
        if (
            global_dependency_policy.get("exclusive_owner_required")
            and not any(
                required_owner_text in evidence_name
                or required_owner_leaf
                in evidence_name.rsplit(".", 1)[0].split(".")
                for evidence_name in package_selected_evidence_names
            )
        ):
            errors.append(
                f"Exclusive dependency owner `{required_owner}` has no selected "
                "callable evidence anywhere in the approved package plan."
            )
    prompt = str(original_prompt or "")
    prompt_lower = prompt.casefold()
    explicit_qualified_methods = list(dict.fromkeys(re.findall(
        r"\b([A-Z][A-Za-z0-9_]*)\.([a-z_][A-Za-z0-9_]*)\s*\(",
        prompt,
    )))
    external_qualified_methods = {
        (owner, method)
        for _host, owner, method in re.findall(
            r"\b(unreal|maya(?:\.cmds)?|cmds|bpy|pyfbsdk|"
            r"PySide6|PySide2|PyQt6|PyQt5)\."
            r"([A-Z][A-Za-z0-9_]*)\.([a-z_][A-Za-z0-9_]*)\s*\(",
            prompt,
        )
    }
    explicit_signal_handlers = set(re.findall(
        r"\b[A-Za-z_][A-Za-z0-9_]*\."
        r"(?:clicked|triggered|toggled|accepted|rejected|activated)"
        r"\b[^\n.;]{0,80}?\bto\s+(?:self\.)?"
        r"([a-z_][A-Za-z0-9_]*)\b",
        prompt,
        flags=re.IGNORECASE,
    ))
    chunk_by_owner = {
        str(chunk.get("owner") or ""): chunk
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and str(chunk.get("owner") or "") != "<module>"
    }
    all_requirement_rows = {
        str(item.get("id") or item.get("requirement_id") or ""): str(
            item.get("text")
            or item.get("requirement")
            or item.get("description")
            or ""
        )
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for item in chunk.get("requirements") or []
        if isinstance(item, Mapping)
    }
    for owner, method_name in explicit_qualified_methods:
        if (owner, method_name) in external_qualified_methods:
            continue
        chunk = chunk_by_owner.get(owner)
        if chunk is None:
            errors.append(
                f"Prompt-faithfulness failure: explicit owner `{owner}` from "
                f"`{owner}.{method_name}(...)` has no declaration chunk."
            )
            continue
        contract = chunk.get("declaration_contract") or {}
        required_methods = {
            str(value) for value in contract.get("required_methods") or []
        }
        if method_name not in required_methods:
            errors.append(
                f"Prompt-faithfulness failure: `{owner}.{method_name}` is "
                "explicitly requested but absent from its declaration contract."
            )
        owning_requirement_ids = {
            str(item.get("id") or item.get("requirement_id") or "")
            for item in chunk.get("requirements") or []
            if isinstance(item, Mapping)
        }
        source_requirement_ids = {
            requirement_id
            for requirement_id, requirement_text in all_requirement_rows.items()
            if f"{owner}.{method_name}" in requirement_text
        }
        if source_requirement_ids and not (
            owning_requirement_ids & source_requirement_ids
        ):
            errors.append(
                f"Prompt-faithfulness failure: `{owner}.{method_name}` is "
                "assigned to a different declaration owner."
            )

    planned_method_owners: dict[str, set[str]] = {}
    for owner, chunk in chunk_by_owner.items():
        contract = chunk.get("declaration_contract") or {}
        required_task_methods = {
            str(value)
            for value in contract.get("required_methods") or []
            if str(value)
        }
        explicit_method_tasks = {
            str(item.get("name") or "")
            for item in chunk.get("method_tasks") or []
            if isinstance(item, Mapping) and str(item.get("name") or "")
        }
        missing_method_tasks = sorted(
            required_task_methods - explicit_method_tasks
        )
        if missing_method_tasks:
            errors.append(
                f"Plan owner `{owner}` has required callable declarations without "
                "independent method tasks: "
                + ", ".join(missing_method_tasks)
                + "."
            )
        planned_methods = {
            str(value)
            for value in contract.get("required_methods") or []
            if str(value)
        }
        planned_methods.update(
            str(item.get("name") or "")
            for item in chunk.get("method_tasks") or []
            if isinstance(item, Mapping) and str(item.get("name") or "")
        )
        planned_method_owners[owner] = planned_methods
        requested_owner_methods = {
            method_name
            for explicit_owner, method_name in explicit_qualified_methods
            if explicit_owner == owner
        }
        owned_requirement_text = "\n".join(
            str(item.get("text") or item.get("requirement") or "")
            for item in chunk.get("requirements") or []
            if isinstance(item, Mapping)
        )
        requested_owner_methods.update(
            method_name
            for method_name in planned_methods
            if re.search(
                rf"(?<![.\w]){re.escape(method_name)}\s*\(",
                owned_requirement_text,
            )
        )
        if (
            "__post_init__" in planned_methods
            and re.search(
                r"\bvalidate\b[^.!?\n;]{0,100}\bconstructor\b"
                r"|\bconstructor\b[^.!?\n;]{0,100}\bvalidat",
                owned_requirement_text,
                flags=re.IGNORECASE,
            )
        ):
            requested_owner_methods.add("__post_init__")
        if (
            "__post_init__" in planned_methods
            and any(
                isinstance(item, Mapping)
                and str(item.get("name") or "") == "__post_init__"
                and bool(item.get("requirement_ids"))
                and bool(item.get("implementation_mechanics"))
                and bool(item.get("validation_cases"))
                for item in chunk.get("method_tasks") or []
            )
        ):
            requested_owner_methods.add("__post_init__")
        decorators = {
            str(value).rsplit(".", 1)[-1]
            for value in contract.get("decorators") or []
        }
        owner_is_error = owner.endswith(("Error", "Exception"))
        owner_is_data = "dataclass" in decorators
        if owner_is_data:
            explicit_field_rows = [
                (match.group(1), match.group(2).strip().rstrip(","))
                for clause in re.findall(
                    rf"\b(?:immutable\s+)?{re.escape(owner)}\s+dataclass\s+with\s+"
                    r"(.+?)(?=;\s*|\.\s+[A-Z]|\Z)",
                    prompt,
                    flags=re.IGNORECASE,
                )
                for normalized_clause in [
                    re.sub(
                        r",\s*(?:and|or)\s+"
                        r"(?=[a-z_][A-Za-z0-9_]*\s*:)",
                        ", ",
                        clause,
                        flags=re.IGNORECASE,
                    )
                ]
                for match in re.finditer(
                    r"\b([a-z_][A-Za-z0-9_]*)\s*:\s*(.+?)"
                    r"(?=,\s*[a-z_][A-Za-z0-9_]*\s*:|\Z)",
                    normalized_clause,
                )
            ]
            planned_fields = {
                str(field.get("name") or ""): str(field.get("type") or "")
                for field in contract.get("fields") or []
                if isinstance(field, Mapping)
            }
            for field_name, field_type in explicit_field_rows:
                if planned_fields.get(field_name) != field_type:
                    errors.append(
                        f"Prompt-faithfulness failure: `{owner}.{field_name}` "
                        f"must preserve explicit type `{field_type}`."
                    )
            if (
                re.search(
                    rf"\bimmutable\s+{re.escape(owner)}\s+dataclass\b",
                    prompt,
                    flags=re.IGNORECASE,
                )
                and not bool(contract.get("immutable"))
            ):
                errors.append(
                    f"Prompt-faithfulness failure: `{owner}` lost its explicit "
                    "immutable dataclass contract."
                )
        if owner_is_error or owner_is_data:
            invented = sorted(
                method
                for method in planned_methods
                if method != "__init__" and method not in requested_owner_methods
            )
            if invented:
                errors.append(
                    f"Prompt-faithfulness failure: `{owner}` is an "
                    f"{'exception' if owner_is_error else 'data'} declaration "
                    "but owns unrequested behavior: " + ", ".join(invented)
                )
        for requirement in chunk.get("requirements") or []:
            if not isinstance(requirement, Mapping):
                continue
            requirement_text = str(requirement.get("text") or "")
            if (
                (owner_is_error or owner_is_data)
                and owner not in requirement_text
                and not (
                    owner_is_data
                    and re.search(
                        r"\bconstructor\b",
                        requirement_text,
                        flags=re.IGNORECASE,
                    )
                )
                and re.search(
                    r"\b(?:execute|run|schedule|create|build|update|connect|"
                    r"load|save|import|export|validate)\w*\b",
                    requirement_text,
                    flags=re.IGNORECASE,
                )
            ):
                errors.append(
                    f"Prompt-faithfulness failure: `{owner}` owns unrelated "
                    f"requirement `{requirement.get('id') or ''}`."
                )
        callable_signatures = list(
            contract.get("callable_signatures") or []
        )
        for signature_index, signature in enumerate(callable_signatures):
            signature_text = str(signature).strip()
            signature_text = re.sub(
                r"\)\s*:\s*->\s*",
                ") -> ",
                signature_text,
            ).rstrip(":").strip()
            callable_signatures[signature_index] = signature_text
            try:
                parsed = ast.parse(signature_text + ":\n    pass")
            except SyntaxError as exc:
                errors.append(
                    f"Plan-feasibility failure: `{owner}` has an invalid or "
                    f"truncated callable signature `{signature_text}`: {exc}."
                )
                continue
            if (
                len(parsed.body) != 1
                or not isinstance(
                    parsed.body[0],
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            ):
                errors.append(
                    f"Plan-feasibility failure: `{owner}` has a non-callable "
                    f"signature contract `{signature_text}`."
                )
                continue
            signature_name = parsed.body[0].name
            if (
                str(contract.get("kind") or "") == "class"
                and
                signature_name != "__init__"
                and signature_name not in planned_methods
            ):
                errors.append(
                    f"Prompt-faithfulness failure: `{owner}.{signature_name}` "
                    "has a callable contract without explicit method ownership."
                )
            if (
                str(contract.get("kind") or "") == "function"
                and signature_name != owner.rsplit(".", 1)[-1]
            ):
                errors.append(
                    f"Prompt-faithfulness failure: function owner `{owner}` "
                    f"declares unrelated callable `{signature_name}`."
                )
        if isinstance(contract, dict):
            contract["callable_signatures"] = callable_signatures

    for handler in sorted(explicit_signal_handlers):
        if not any(
            handler in methods for methods in planned_method_owners.values()
        ):
            errors.append(
                f"Prompt-faithfulness failure: connected handler `{handler}` "
                "is absent from every class contract."
            )

    package_prefix_match = re.search(
        r"\b(?:under|inside|within|in)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*(?:[\\/][A-Za-z_][A-Za-z0-9_]*)*)"
        r"\s*:\s*(?=[^.!?\n]*\.py\b)",
        prompt,
        flags=re.IGNORECASE,
    )
    if package_prefix_match:
        expected_prefix = (
            package_prefix_match.group(1).replace("\\", "/").casefold() + "/"
        )
        for file_item in implementation_plan.get("files") or []:
            if not isinstance(file_item, Mapping):
                continue
            path = str(file_item.get("path") or "").replace("\\", "/")
            if path and expected_prefix not in path.casefold():
                errors.append(
                    "Prompt-faithfulness failure: planned file is outside "
                    f"requested package `{expected_prefix.rstrip('/')}`: {path}"
                )

    capability_contracts = [
        item
        for item in implementation_plan.get(
            "validated_capability_contracts"
        ) or []
        if isinstance(item, Mapping)
    ]
    capability_names = {
        str(item.get("name") or "").casefold()
        for item in capability_contracts
        if str(item.get("signature") or "").strip()
        and str(item.get("strength") or "") in {
            "authoritative_signature",
            "verified_definition",
        }
    }
    explicit_external_calls = list(dict.fromkeys(re.findall(
        r"\b((?:unreal|maya(?:\.cmds)?|cmds|bpy|pyfbsdk|"
        r"PySide6|PySide2|PyQt6|PyQt5)"
        r"(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*\(",
        prompt,
    )))
    for call_path in explicit_external_calls:
        expected = call_path.casefold()
        expected_suffix = ".".join(expected.split(".")[-2:])
        if not any(
            candidate == expected
            or candidate.endswith("." + expected_suffix)
            for candidate in capability_names
        ):
            errors.append(
                "Plan-feasibility failure: explicitly requested external call "
                f"`{call_path}` has no authoritative signature contract."
            )

    for proposal in implementation_plan.get("proposed_interfaces") or []:
        if not isinstance(proposal, Mapping):
            continue
        signature = str(proposal.get("signature") or "")
        proposed_names = re.findall(
            r"\b(?:def\s+)?([a-z_][A-Za-z0-9_]*)\s*\(",
            signature,
        )
        if bool(proposal.get("approval_required")) and not any(
            name.casefold() in prompt_lower for name in proposed_names
        ):
            errors.append(
                "Prompt-faithfulness failure: unrequested cross-file interface "
                f"was proposed: `{signature}`."
            )
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            errors.append("Implementation plan contains a non-object chunk.")
            continue
        chunk_id = str(chunk.get("chunk_id") or "<missing>")
        contract = chunk.get("declaration_contract")
        if not isinstance(contract, Mapping):
            errors.append(f"Chunk `{chunk_id}` has no declaration contract.")
        mechanics = {
            str(item.get("requirement_id") or ""): item.get("steps") or []
            for item in chunk.get("implementation_mechanics") or []
            if isinstance(item, Mapping)
        }
        validations = {
            str(item.get("requirement_id") or ""): item.get("checks") or []
            for item in chunk.get("validation_cases") or []
            if isinstance(item, Mapping)
        }
        for requirement in _requirement_texts(chunk):
            requirement_id = requirement["id"]
            requirement_text = str(requirement.get("text") or "")
            requirement_mechanics = [
                str(step).strip()
                for step in mechanics.get(requirement_id) or []
                if str(step).strip()
            ]
            if not requirement_mechanics:
                errors.append(
                    f"Chunk `{chunk_id}` has no implementation mechanics for "
                    f"`{requirement_id}`."
                )
            ambiguous_mechanics: list[str] = []
            for step in requirement_mechanics:
                if re.search(
                    r"\b(?:as appropriate|if needed|as needed|and/or|"
                    r"may occur|or log|or a button|or otherwise)\b",
                    step,
                    flags=re.IGNORECASE,
                ):
                    ambiguous_mechanics.append(step)
                    continue
                for _label, mutation_pattern in (
                    ("update", r"\bupdat(?:e|ed|es|ing)\b"),
                    ("populate", r"\bpopulat(?:e|ed|es|ing)\b"),
                    ("display", r"\bdisplay(?:ed|s|ing)?\b"),
                    ("log", r"\blog(?:ged|s|ging)?\b"),
                    ("save", r"\bsav(?:e|ed|es|ing)\b"),
                    ("delete", r"\bdelet(?:e|ed|es|ing)\b"),
                    ("emit", r"\bemit(?:ted|s|ting)?\b"),
                ):
                    if re.search(
                        rf"\b(?:do\s+not|don't|never|without)\b"
                        rf"[^.;]{{0,40}}{mutation_pattern}",
                        step,
                        flags=re.IGNORECASE,
                    ):
                        continue
                    requirement_operation_pattern = mutation_pattern
                    if _label == "emit":
                        requirement_operation_pattern = (
                            r"\bemit(?:ted|s|ting)?\b"
                            r"|\bsignals?\b|\bcallbacks?\b"
                            r"|\bdeliver(?:ed|s|ing)?\b"
                            r"|\breport(?:ed|s|ing)?\b"
                        )
                    if (
                        re.search(mutation_pattern, step, flags=re.IGNORECASE)
                        and not re.search(
                            requirement_operation_pattern,
                            requirement_text,
                            flags=re.IGNORECASE,
                        )
                    ):
                        ambiguous_mechanics.append(step)
                        break
            if ambiguous_mechanics:
                errors.append(
                    f"Chunk `{chunk_id}` has ambiguous implementation mechanics "
                    f"for `{requirement_id}`. Each step must select one exact "
                    "operation and may not invent an unrequested side effect: "
                    + " | ".join(dict.fromkeys(ambiguous_mechanics))
                )
            if not validations.get(requirement_id):
                errors.append(
                    f"Chunk `{chunk_id}` has no validation cases for "
                    f"`{requirement_id}`."
                )
        unresolved = list(chunk.get("unresolved_host_api_queries") or [])
        if unresolved:
            errors.append(
                f"Chunk `{chunk_id}` still has unresolved host APIs: "
                + ", ".join(str(item) for item in unresolved)
            )
    generation_contract = implementation_plan.get("generation_contract")
    if not isinstance(generation_contract, Mapping):
        errors.append("Plan has no generation contract.")
    return errors


def _definition_nodes(tree: ast.Module) -> dict[str, ast.AST]:
    nodes: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes[node.name] = node
    return nodes


def _call_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        try:
            names.append(ast.unparse(child.func))
        except (TypeError, ValueError):
            continue
    return names


def _method_map(class_node: ast.ClassDef) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
