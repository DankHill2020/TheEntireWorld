"""Approval-grade enrichment and persistence for implementation plans."""

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
APPROVED_PLAN_SCHEMA = "tech_connector.approved_implementation_plan.v47"
APPROVED_PLAN_VALIDATOR_VERSION = "implementation-plan-quality-v106"


def _explicit_callable_declaration(name: str, text: str) -> bool:
    """Return whether prose explicitly declares ``name`` as owned code."""

    escaped = re.escape(str(name or "").strip())
    if not escaped:
        return False
    return bool(
        re.search(
            rf"\b(?:add|create|define|implement|include|provide|expose)\s+"
            rf"(?:an?\s+|the\s+)?"
            rf"(?:(?:method|function|callable)\s+(?:named\s+)?)?"
            rf"`?{escaped}`?\s*\(",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"\b(?:method|function|callable)\s+(?:named\s+)?"
            rf"`?{escaped}`?\b",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"(?<![A-Za-z0-9_])`?{escaped}`?\s*\([^)]*\)\s*"
            rf"(?:->\s*[A-Za-z_][A-Za-z0-9_.]*"
            rf"(?:\[[^\]]+\])?\s*)?"
            rf"(?:method|function|callable)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _property_names(text: str) -> list[str]:
    """Extract explicitly requested Python property declarations."""

    names: list[str] = []
    patterns = (
        r"\b(?:add|create|define|implement|include|provide|expose)\s+"
        r"(?:an?\s+|the\s+)?`?([a-z_][A-Za-z0-9_]*)`?\s+property\b",
        r"\bproperty\s+(?:named|called)\s+"
        r"`?([a-z_][A-Za-z0-9_]*)`?\b",
    )
    for pattern in patterns:
        names.extend(
            match.group(1)
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        )
    return list(dict.fromkeys(names))


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prompt_hash(prompt: str) -> str:
    return _stable_hash(" ".join(str(prompt or "").split()))


def implementation_plan_approval_id(
    implementation_plan: Mapping[str, Any],
) -> str:
    """Hash the approved contract while excluding volatile evidence ranking."""

    def stable_contract(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): stable_contract(item)
                for key, item in value.items()
                if str(key) not in {
                    "evidence",
                    "evidence_queries",
                    "unresolved_host_api_queries",
                    "resolution",
                }
            }
        if isinstance(value, list):
            return [stable_contract(item) for item in value]
        return value

    return _stable_hash(stable_contract(implementation_plan))


def _state_root(project_root: str | Path) -> Path:
    configured = str(os.environ.get("TECH_CONNECTOR_STATE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if local_app_data:
            return Path(local_app_data) / "tech_connector"
    xdg_state = str(os.environ.get("XDG_STATE_HOME") or "").strip()
    if xdg_state:
        return Path(xdg_state).expanduser() / "tech_connector"
    home = Path.home()
    if str(home):
        return home / ".local" / "state" / "tech_connector"
    return Path(project_root).resolve() / ".tech_connector_state"


def _plan_store(project_root: str | Path) -> Path:
    configured = str(
        os.environ.get("TECH_CONNECTOR_STATE_DIR") or ""
    ).strip()
    preferred = (
        Path(configured).expanduser().resolve() / "implementation_plans"
        if configured
        else (
            Path(tempfile.gettempdir())
            / "tech_connector"
            / "implementation_plans"
        )
    )
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path(project_root).resolve() / ".tech_connector_state" / (
            "implementation_plans"
        )
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def persist_approved_plan_candidate(
    approval_id: str,
    *,
    prompt: str,
    project_root: str | Path,
    implementation_plan: Mapping[str, Any],
    manifest: Iterable[Mapping[str, Any]],
    requirement_ledger: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
) -> str:
    """Persist the exact displayed artifact and its generation ownership state."""

    store = _plan_store(project_root)
    destination = store / f"{approval_id}.json"
    manifest_rows = [dict(item) for item in manifest]
    requirement_rows = [dict(item) for item in requirement_ledger]
    assignment_rows = [dict(item) for item in assignments]
    payload = {
        "schema": APPROVED_PLAN_SCHEMA,
        "validator_version": APPROVED_PLAN_VALIDATOR_VERSION,
        "approval_id": approval_id,
        "prompt_hash": _prompt_hash(prompt),
        "project_root": str(Path(project_root).resolve()),
        "implementation_plan": dict(implementation_plan),
        "manifest": manifest_rows,
        "manifest_hash": hashlib.sha256(
            json.dumps(
                manifest_rows,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
        "requirement_ledger": requirement_rows,
        "requirement_ledger_hash": hashlib.sha256(
            json.dumps(
                requirement_rows,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
        "assignments": assignment_rows,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        indent=2,
        default=str,
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=store,
            prefix=f".{approval_id}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(serialized)
            temporary = Path(stream.name)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(destination)


def load_approved_plan_candidate(
    approval_id: str,
    *,
    prompt: str,
    project_root: str | Path,
) -> dict[str, Any] | None:
    """Load an exact approved artifact only when prompt and root still match."""

    if not re.fullmatch(r"[a-f0-9]{64}", str(approval_id or "")):
        return None
    source = _plan_store(project_root) / f"{approval_id}.json"
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if payload.get("approval_id") != approval_id:
        return None
    if payload.get("schema") != APPROVED_PLAN_SCHEMA:
        return None
    if payload.get("validator_version") != APPROVED_PLAN_VALIDATOR_VERSION:
        return None
    if payload.get("prompt_hash") != _prompt_hash(prompt):
        return None
    if str(Path(payload.get("project_root") or "").resolve()) != str(
        Path(project_root).resolve()
    ):
        return None
    plan = payload.get("implementation_plan")
    manifest = payload.get("manifest")
    requirement_ledger = payload.get("requirement_ledger")
    if not isinstance(manifest, list) or not isinstance(
        requirement_ledger,
        list,
    ):
        return None
    manifest_hash = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    requirement_ledger_hash = hashlib.sha256(
        json.dumps(
            requirement_ledger,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if payload.get("manifest_hash") != manifest_hash:
        return None
    if payload.get("requirement_ledger_hash") != requirement_ledger_hash:
        return None
    if (
        not isinstance(plan, dict)
        or implementation_plan_approval_id(plan) != approval_id
    ):
        return None
    return payload


def _requirement_texts(chunk: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "id": str(item.get("id") or ""),
            "text": str(item.get("text") or ""),
            "semantic_role": str(item.get("semantic_role") or "behavior"),
        }
        for item in chunk.get("requirements") or []
        if isinstance(item, Mapping)
    ]


def _class_base(owner: str, text: str) -> str:
    generic_match = re.search(
        rf"\b{re.escape(owner)}\s*\[\s*"
        r"([A-Z][A-Za-z0-9_]*)\s*\]",
        text,
    )
    if generic_match:
        return f"Generic[{generic_match.group(1)}]"
    patterns = (
        rf"\b{re.escape(owner)}\b\s+"
        r"(QWidget|QDialog|QMainWindow|QDockWidget)\b",
        rf"\b{re.escape(owner)}\b\s+(?:inheriting\s+from|subclassing|extends)"
        r"\s+([A-Z][A-Za-z0-9_.]*)",
        rf"\b{re.escape(owner)}\b\s+([A-Z][A-Za-z0-9_.]*)\s+"
        r"(?:containing|with|that|which)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            base = match.group(1).rstrip(".")
            if base.casefold() in {
                "class",
                "dataclass",
                "enum",
                "protocol",
                "record",
                "struct",
            }:
                continue
            return base
    if owner.endswith("Dialog") and re.search(
        r"\b(?:PySide|PyQt)\d*\b", text
    ):
        return "QDialog"
    return ""


def _callable_signatures(owner: str, kind: str, text: str) -> list[str]:
    if kind == "module":
        return []
    typed = bool(
        re.search(
            r"\btyped\b|\btype hints?\b|\bdataclass\b|\bgeneric\b"
            rf"|\b{re.escape(owner)}\s*\[[A-Z][A-Za-z0-9_]*\]"
            r"|(?<![.\w])[a-z_][A-Za-z0-9_]*\s*\([^)]*"
            r"\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*[^)]",
            text,
            re.IGNORECASE,
        )
    )
    generic_match = re.search(
        rf"\b{re.escape(owner)}\s*\[\s*"
        r"([A-Z][A-Za-z0-9_]*)\s*\]",
        text,
    )
    generic_type = generic_match.group(1) if generic_match else ""

    def split_top_level_parameters(value: str) -> list[str]:
        """Split parameters without breaking nested generic annotations."""

        parameters: list[str] = []
        current: list[str] = []
        depths = {"(": 0, "[": 0, "{": 0}
        closing = {")": "(", "]": "[", "}": "{"}
        quote = ""
        escaped = False
        for character in value:
            if quote:
                current.append(character)
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    quote = ""
                continue
            if character in {"'", '"'}:
                quote = character
                current.append(character)
                continue
            if character in depths:
                depths[character] += 1
                current.append(character)
                continue
            if character in closing:
                opener = closing[character]
                depths[opener] = max(0, depths[opener] - 1)
                current.append(character)
                continue
            if character == "," and not any(depths.values()):
                rendered = "".join(current).strip()
                if rendered:
                    parameters.append(rendered)
                current = []
                continue
            current.append(character)
        rendered = "".join(current).strip()
        if rendered:
            parameters.append(rendered)
        return parameters

    def typed_parameter(value: str) -> str:
        if value.strip() in {"self", "cls"} or not typed or ":" in value:
            return value
        name, separator, default = value.partition("=")
        clean_name = name.strip()
        lowered_name = clean_name.casefold()
        if generic_type and lowered_name in {
            "entry",
            "item",
            "value",
        }:
            annotation = generic_type
        elif generic_type and lowered_name in {
            "predicate",
            "filter",
            "matcher",
        }:
            annotation = f"Callable[[{generic_type}], bool]"
        elif lowered_name in {
                "dependency",
                "item",
                "key",
                "node",
                "parent_node",
                "child_node",
        }:
            annotation = "Hashable"
        elif lowered_name in {"items", "values", "records", "entries"}:
            annotation = "Iterable[Any]"
        elif lowered_name in {"clock", "monotonic_clock", "time_source"}:
            annotation = "Callable[[], float]"
        elif any(
            token in lowered_name
            for token in (
                "threshold",
                "count",
                "attempt",
                "index",
                "limit",
                "maximum",
                "minimum",
                "size",
            )
        ):
            annotation = "int"
        elif any(
            token in lowered_name
            for token in ("timeout", "duration", "interval", "delay", "seconds")
        ):
            annotation = "float"
        elif lowered_name.startswith(("is_", "has_", "should_", "allow_")):
            annotation = "bool"
        else:
            annotation = "Any"
        rendered = f"{clean_name}: {annotation}"
        return f"{rendered} = {default.strip()}" if separator else rendered

    def return_annotation(name: str) -> str:
        lowered = name.casefold()
        if lowered in {"main", "run_self_test", "self_test"}:
            return " -> None"
        if not typed:
            return ""
        if (
            kind == "function"
            and name == owner
            and re.search(r"\blaz(?:y|ily)\b|\byields?\b", text, re.IGNORECASE)
        ):
            if re.search(r"\blists?\b", text, re.IGNORECASE):
                return " -> Iterator[list[Any]]"
            return " -> Iterator[Any]"
        if lowered.startswith(
            (
                "add",
                "allow",
                "clear",
                "close",
                "delete",
                "insert",
                "open",
                "put",
                "record",
                "register",
                "remove",
                "reset",
                "set",
                "update",
                "append",
                "resize",
            )
        ):
            return " -> None"
        if lowered.startswith(("enqueue", "schedule")):
            return " -> None"
        if lowered.startswith(("cancel", "count")) and re.search(
            rf"\b{re.escape(name)}\s*\([^)]*\)[^.!?\n]{{0,120}}"
            r"\b(?:count|number)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return " -> int"
        if generic_type and (
            lowered.startswith(("pop", "drain", "ready"))
            or re.search(
                rf"\b{re.escape(name)}\s*\([^)]*\)[^.!?\n]{{0,120}}"
                r"\breturns?\s+(?:all\s+)?(?:ready\s+)?items\b",
                text,
                flags=re.IGNORECASE,
            )
        ):
            return f" -> list[{generic_type}]"
        if (
            lowered.endswith(("_for", "_order"))
            or lowered in {"dependencies", "keys", "nodes", "values"}
        ):
            if "delay" in lowered or "backoff" in lowered:
                return " -> float"
            return " -> tuple[Hashable, ...]"
        if "delay" in lowered or "backoff" in lowered:
            return " -> float"
        if re.search(
            rf"\b{re.escape(name)}\s*\([^)]*\)[^.!?\n]{{0,120}}"
            r"\b(?:arithmetic\s+)?mean\b",
            text,
            flags=re.IGNORECASE,
        ):
            return " -> float"
        return " -> Any"

    signatures: list[str] = []
    for match in re.finditer(
        r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)",
        text,
    ):
        name = match.group(1)
        if (
            name.casefold() in _MODULE_CALLABLES
            and not _explicit_callable_declaration(name, text)
        ):
            continue
        if (
            name.casefold().endswith("_callback")
            and not re.search(
                rf"\b{re.escape(owner)}\.{re.escape(name)}\s*\("
                rf"|\b(?:method|function|callable)\s+(?:named\s+)?"
                rf"{re.escape(name)}\b"
                rf"|\b(?:implement|define|add)\s+{re.escape(name)}\s+method\b",
                text,
                flags=re.IGNORECASE,
            )
        ):
            continue
        prefix = text[max(0, match.start() - 48):match.start()]
        suffix = text[match.end():match.end() + 32]
        if (
            re.search(r"\b(?:emit|signal)\s+$", prefix, flags=re.IGNORECASE)
            or re.match(r"\s+(?:Qt\s+)?signal\b", suffix, flags=re.IGNORECASE)
        ):
            continue
        parameters = [
            value.strip()
            for value in split_top_level_parameters(match.group(2))
            if value.strip()
            and re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*"
                r"(?:\s*:\s*[^,=]+)?"
                r"(?:\s*=\s*[^,]+)?",
                value.strip(),
            )
        ]
        rendered_parameters = [typed_parameter(value) for value in parameters]
        if (
            kind == "class"
            and (
                not rendered_parameters
                or rendered_parameters[0].split(":", 1)[0].strip() != "self"
            )
        ):
            rendered_parameters.insert(0, "self")
        rendered = ", ".join(rendered_parameters)
        explicit_return = re.match(
            r"\s*->\s*"
            r"([A-Za-z_][A-Za-z0-9_.]*"
            r"(?:\[[A-Za-z0-9_., \[\]|]+\])?"
            r"(?:\s*\|\s*[A-Za-z_][A-Za-z0-9_.]*)*)",
            text[match.end():],
        )
        rendered_return = (
            f" -> {explicit_return.group(1).strip()}"
            if explicit_return
            else return_annotation(name)
        )
        signature = f"def {name}({rendered}){rendered_return}"
        if signature not in signatures:
            signatures.append(signature)
    if kind == "class":
        receives = re.search(
            rf"\b{re.escape(owner)}\b[^.!?\n;]{{0,160}}\b"
            r"(?i:receives|accepts|takes)\s+([^.!?\n;]+)",
            text,
        )
        if not receives:
            receives = re.search(
                r"\b(?:receives?|accepts?|takes)\s+(.+?)"
                r"(?=,\s*(?:exposes?|provides?|implements?|writes?|preserves?|"
                r"rejects?|raises?|creates?|avoids?)\b|[.!?;\n]|$)",
                text,
                flags=re.IGNORECASE,
            )
        if not receives:
            receives = re.search(
                rf"\b{re.escape(owner)}\b[^.!?\n;]{{0,120}}\bwith\s+"
                r"((?:(?:a|an|the)\s+)?"
                r"(?:injected|provided|required)\s+[^,.;\n]+)",
                text,
                flags=re.IGNORECASE,
            )
        constructor_parameters = ["self"]
        if receives:
            receive_clause = receives.group(1)
            receive_parts = [
                part.strip()
                for part in re.split(r"\s*,\s*|\s+\band\b\s+", receive_clause)
                if part.strip()
            ]
            ignored_words = {
                "a",
                "an",
                "the",
                "injected",
                "provided",
                "optional",
                "required",
                "typed",
                "thread",
                "safe",
                "monotonic",
                "callable",
                "function",
                "object",
            }
            for part in receive_parts:
                optional = bool(
                    re.search(r"\boptional\b", part, flags=re.IGNORECASE)
                )
                callable_match = re.search(
                    r"\b([a-z_][A-Za-z0-9_]*)\s+callable\b",
                    part,
                    flags=re.IGNORECASE,
                )
                dependency_match = re.search(
                    r"\b([A-Z][A-Za-z0-9_.]*)\b",
                    part,
                )
                if callable_match:
                    parameter_name = callable_match.group(1).casefold()
                    rendered_parameter = (
                        f"{parameter_name}: Callable[..., Any]"
                        + (" | None = None" if optional else "")
                    )
                elif re.search(
                    r"\bmonotonic\s+(?:clock|time_source)\b",
                    part,
                    flags=re.IGNORECASE,
                ):
                    parameter_name = (
                        "time_source"
                        if "time_source" in part.casefold()
                        else "clock"
                    )
                    rendered_parameter = (
                        f"{parameter_name}: Callable[[], float]"
                        + (" | None = None" if optional else "")
                    )
                elif dependency_match:
                    dependency_type = dependency_match.group(1)
                    type_name = dependency_type.rsplit(".", 1)[-1]
                    parameter_name = re.sub(
                        r"([a-z0-9])([A-Z])",
                        r"\1_\2",
                        re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", type_name),
                    ).casefold()
                    rendered_parameter = (
                        f"{parameter_name}: {dependency_type}"
                        + (" | None = None" if optional else "")
                    )
                else:
                    words = [
                        word.casefold()
                        for word in re.findall(
                            r"\b[a-z_][A-Za-z0-9_]*\b",
                            part,
                            flags=re.IGNORECASE,
                        )
                        if word.casefold() not in ignored_words
                    ]
                    explicit_identifiers = [
                        word for word in words if "_" in word
                    ]
                    parameter_name = (
                        explicit_identifiers[-1]
                        if explicit_identifiers
                        else (words[-1] if words else "")
                    )
                    if not parameter_name:
                        continue
                    rendered_parameter = typed_parameter(parameter_name)
                if rendered_parameter not in constructor_parameters:
                    constructor_parameters.append(rendered_parameter)
        constructor_requested = bool(receives) or bool(
            owner.endswith(("Dialog", "Window", "Widget"))
            or re.search(
                r"\b(?:PySide\d*|PyQt\d*|QDialog|QMainWindow|QWidget)\b",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\bconstructor\b|\binitiali[sz](?:e|es|ed|ing)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if owner.endswith(("Dialog", "Window", "Widget")):
            constructor_parameters.append("parent=None")
        if constructor_requested:
            constructor = (
                "def __init__("
                + ", ".join(constructor_parameters)
                + (") -> None" if typed else ")")
            )
            signatures.insert(0, constructor)
        if re.search(r"\bcleanup\b", text, flags=re.IGNORECASE):
            signatures.append("def _cleanup(self)")
        if (
            re.search(r"\brefresh(?:es|ed|ing)?\b", text, flags=re.IGNORECASE)
            and not any(" refresh(" in item for item in signatures)
        ):
            signatures.append("def refresh(self)")
    exact_owner_signatures: list[str] = []
    for match in re.finditer(
        rf"\b{re.escape(owner)}\.([a-z_][A-Za-z0-9_]*)\s*"
        r"\(([^)]*)\)\s*(?:->\s*([^.;]+))?",
        text,
    ):
        method_name = match.group(1)
        parameters = match.group(2).strip()
        return_annotation = str(match.group(3) or "").strip()
        rendered_parameters = "self"
        if parameters:
            rendered_parameters += ", " + parameters
        signature = f"def {method_name}({rendered_parameters})"
        if return_annotation:
            signature += f" -> {return_annotation}"
        exact_owner_signatures.append(signature)
    constructor_acceptance = re.search(
        r"\bconstructor\b[^.!?;\n]{0,48}\baccepts?\s+([^.!?;\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if not constructor_acceptance:
        constructor_acceptance = re.search(
            r"\baccept\s+(.+?)\s+in\s+the\s+constructor\b",
            text,
            flags=re.IGNORECASE,
        )
    if constructor_acceptance:
        constructor_parameters: list[str] = []
        acceptance_clause = constructor_acceptance.group(1)
        explicit_typed_parameters = re.findall(
            r"\b(?:(optional)\s+)?"
            r"([a-z_][A-Za-z0-9_]*)\s*:\s*"
            r"([A-Z][A-Za-z0-9_.]*(?:\[[^\]\n]+\])?"
            r"(?:\s*\|\s*None)?)"
            r"(?:\s*=\s*([^,\n]+))?",
            acceptance_clause,
            flags=re.IGNORECASE,
        )
        if explicit_typed_parameters:
            for optional, parameter_name, type_name, default in explicit_typed_parameters:
                normalized_type = type_name.strip()
                if optional and "None" not in normalized_type:
                    normalized_type += " | None"
                rendered = f"{parameter_name}: {normalized_type}"
                if default.strip():
                    rendered += f" = {default.strip()}"
                elif optional:
                    rendered += " = None"
                if rendered not in constructor_parameters:
                    constructor_parameters.append(rendered)
            if re.search(
                r"\bparent\s*=\s*None\b",
                acceptance_clause,
                flags=re.IGNORECASE,
            ):
                constructor_parameters.append("parent=None")
        else:
            for type_name in re.findall(
                r"(?:\b(?:a|an)\s+)?"
                r"([A-Z][A-Za-z0-9_]*(?:\[[^\]\n]+\])?)",
                acceptance_clause,
            ):
                base_type = type_name.split("[", 1)[0]
                if type_name.startswith("Sequence["):
                    inner_type = type_name.split("[", 1)[1].rstrip("]")
                    parameter_name = (
                        re.sub(
                            r"([a-z0-9])([A-Z])",
                            r"\1_\2",
                            inner_type,
                        ).casefold()
                        .removesuffix("_spec")
                        .removesuffix("_item")
                        + "s"
                    )
                else:
                    parameter_name = re.sub(
                        r"([a-z0-9])([A-Z])",
                        r"\1_\2",
                        base_type,
                    ).casefold()
                rendered = f"{parameter_name}: {type_name}"
                if rendered not in constructor_parameters:
                    constructor_parameters.append(rendered)
            if re.search(
                r"\bmonotonic\s+(?:clock|time_source)\b",
                acceptance_clause,
                flags=re.IGNORECASE,
            ):
                parameter_name = (
                    "time_source"
                    if "time_source" in acceptance_clause.casefold()
                    else "clock"
                )
                rendered = f"{parameter_name}: Callable[[], float]"
                if rendered not in constructor_parameters:
                    constructor_parameters.append(rendered)
            for callback_match in re.finditer(
                r"\b(?P<optional>optional\s+)?"
                r"(?P<name>[a-z_][A-Za-z0-9_]*_callback)\s*"
                r"\((?P<parameters>[^)]*)\)",
                acceptance_clause,
                flags=re.IGNORECASE,
            ):
                callback_parameter_types = []
                for callback_parameter in callback_match.group(
                    "parameters"
                ).split(","):
                    parameter_name = callback_parameter.strip().casefold()
                    if not parameter_name:
                        continue
                    if parameter_name.endswith(("_int", "_count", "_index")):
                        callback_parameter_types.append("int")
                    elif parameter_name.endswith(
                        ("_str", "_text", "_status", "_message")
                    ):
                        callback_parameter_types.append("str")
                    else:
                        callback_parameter_types.append("Any")
                rendered = (
                    f"{callback_match.group('name')}: Callable[["
                    + ", ".join(callback_parameter_types)
                    + "], None]"
                )
                if callback_match.group("optional"):
                    rendered += " | None = None"
                if rendered not in constructor_parameters:
                    constructor_parameters.append(rendered)
        if owner.endswith(("Dialog", "Window", "Widget")):
            if "parent=None" not in constructor_parameters:
                constructor_parameters.append("parent=None")
        constructor = (
            "def __init__(self"
            + (
                ", " + ", ".join(constructor_parameters)
                if constructor_parameters
                else ""
            )
            + ")"
        )
        signatures = [
            signature
            for signature in signatures
            if not signature.startswith("def __init__(")
        ]
        signatures.insert(0, constructor)
    required_methods = set(_required_method_names(owner, kind, text))
    filtered_signatures: list[str] = []
    for signature in [*exact_owner_signatures, *signatures]:
        match = re.match(
            r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            signature,
        )
        if not match:
            continue
        method_name = match.group(1)
        if (
            method_name == "__init__"
            or method_name in required_methods
            or (kind == "function" and method_name == owner)
        ):
            filtered_signatures.append(signature)
    represented_methods = {
        match.group(1)
        for signature in filtered_signatures
        for match in [
            re.match(
                r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                signature,
            )
        ]
        if match
    }
    for property_name in _property_names(text):
        if property_name in represented_methods:
            continue
        property_return = " -> Any"
        property_clause = re.search(
            rf"\b{re.escape(property_name)}\s+property\b"
            r"([^.!?\n]*)",
            text,
            flags=re.IGNORECASE,
        )
        if property_clause and re.search(
            r"\b(?:immutable\s+)?tuple\b",
            property_clause.group(1),
            flags=re.IGNORECASE,
        ):
            item_type = "Any"
            if re.search(r"\bfloat\b", text, flags=re.IGNORECASE):
                item_type = "float"
            elif re.search(r"\bstr(?:ing)?\b", text, flags=re.IGNORECASE):
                item_type = "str"
            property_return = f" -> tuple[{item_type}, ...]"
        filtered_signatures.append(
            f"def {property_name}(self){property_return}"
        )
        represented_methods.add(property_name)
    filtered_signatures.extend(
        f"def {method_name}(self)"
        for method_name in required_methods - represented_methods
    )
    filtered_signatures = [
        (
            f"{signature} -> None"
            if signature.startswith("def __init__(")
            and " -> " not in signature
            else signature
        )
        for signature in filtered_signatures
    ]
    return list(dict.fromkeys(filtered_signatures))


def _required_method_names(owner: str, kind: str, text: str) -> list[str]:
    if kind != "class" or not owner:
        return []
    explicit_names = list(dict.fromkeys([
        *re.findall(
            rf"\b{re.escape(owner)}\.([a-z_][A-Za-z0-9_]*)\s*\(",
            text,
        ),
        *re.findall(
            r"\b(?:implement|define|add)\s+(?:the\s+)?"
            r"([a-z_][A-Za-z0-9_]*)"
            r"(?=\s*(?:\(|method\b|with\b|during\b|that\b))",
            text,
            flags=re.IGNORECASE,
        ),
        *re.findall(
            r"\b(?:connect|wire)\b[^\n.;]{0,160}?\bto\s+"
            r"(?:(?:the|a|an)\s+)?(?:self\.)?"
            r"([a-z_][A-Za-z0-9_]*)\s*(?=\(|method\b)",
            text,
            flags=re.IGNORECASE,
        ),
        *re.findall(
            r"\b[A-Za-z_][A-Za-z0-9_]*\."
            r"(?:clicked|triggered|toggled|accepted|rejected|activated)"
            r"\b[^\n.;]{0,80}?\bto\s+(?:self\.)?"
            r"([a-z_][A-Za-z0-9_]*)\b",
            text,
            flags=re.IGNORECASE,
        ),
        *re.findall(
            r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*\([^()]*\)",
            text,
        ),
    ]))
    prose_tokens = {
        "behavior",
        "implementation",
        "owner",
        "request",
        "requested",
        "requirement",
        "the",
    }
    explicit_names.extend(_property_names(text))
    explicit_names = [
        name for name in explicit_names
        if name.casefold() not in prose_tokens
        and (
            name.casefold() not in _MODULE_CALLABLES
            or _explicit_callable_declaration(name, text)
        )
        and (
            not name.casefold().endswith("_callback")
            or re.search(
                rf"\b{re.escape(owner)}\.{re.escape(name)}\s*\("
                rf"|\b(?:method|function|callable)\s+(?:named\s+)?"
                rf"{re.escape(name)}\b"
                rf"|\b(?:implement|define|add)\s+{re.escape(name)}\s+method\b",
                text,
                flags=re.IGNORECASE,
            )
        )
    ]
    if explicit_names:
        return explicit_names
    match = re.search(
        rf"\b{re.escape(owner)}\b\s+([^.!?\n]{{0,180}}?)\s+methods?\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"\b(?:exposes?|provides?|implements?|with)\b"
            r"([^.!?\n]{0,180}?)\s+methods?\b",
            text,
            flags=re.IGNORECASE,
        )
    if not match:
        return []
    method_clause = match.group(1)
    dependency_prefix, separator, remaining_clause = method_clause.partition(",")
    if separator and re.search(
        r"\b(?:injected|provided|required)\b",
        dependency_prefix,
        flags=re.IGNORECASE,
    ):
        method_clause = remaining_clause
    explicit_calls = re.findall(
        r"\b([a-z_][A-Za-z0-9_]*)\s*\(",
        method_clause,
    )
    if explicit_calls:
        return list(dict.fromkeys(explicit_calls))
    if re.search(r"\b[A-Z][A-Za-z0-9_]*\b", method_clause):
        return []
    return list(dict.fromkeys(
        token
        for token in re.findall(
            r"\b[a-z_][A-Za-z0-9_]*\b",
            method_clause,
        )
        if token.casefold() not in {
            "a",
            "an",
            "and",
            "or",
            "the",
            "typed",
            "with",
        }
    ))


def _attribute_contracts(text: str) -> list[dict[str, str]]:
    suffix_types = {
        "_btn": "QPushButton",
        "_button": "QPushButton",
        "_checkbox": "QCheckBox",
        "_check_box": "QCheckBox",
        "_combo": "QComboBox",
        "_combobox": "QComboBox",
        "_input": "QLineEdit",
        "_label": "QLabel",
        "_list": "QListWidget",
        "_list_widget": "QListWidget",
        "progress_bar": "QProgressBar",
        "_progress_bar": "QProgressBar",
        "_spinbox": "QSpinBox",
        "_text_edit": "QTextEdit",
    }
    descriptor_types = {
        "button": "QPushButton",
        "check box": "QCheckBox",
        "checkbox": "QCheckBox",
        "combo box": "QComboBox",
        "dropdown": "QComboBox",
        "label": "QLabel",
        "line edit": "QLineEdit",
        "progress bar": "QProgressBar",
        "spinner": "QSpinBox",
        "text box": "QLineEdit",
        "text edit": "QTextEdit",
    }
    identifiers = list(dict.fromkeys(
        token
        for token in re.findall(r"\b[a-z_][A-Za-z0-9_]*\b", text)
        if token.endswith(_UI_ATTRIBUTE_SUFFIXES)
    ))
    qt_type_suffixes = {
        "QCheckBox": "check_box",
        "QComboBox": "combo_box",
        "QLabel": "label",
        "QLineEdit": "input",
        "QListWidget": "list_widget",
        "QProgressBar": "progress_bar",
        "QPushButton": "button",
        "QRadioButton": "radio_button",
        "QSpinBox": "spinbox",
        "QDoubleSpinBox": "spinbox",
        "QTextEdit": "text_edit",
        "QToolButton": "button",
    }
    inferred_identifiers: list[tuple[str, str]] = []

    def role_identifier(role: str, widget_type: str) -> str:
        normalized_role = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(role or "").casefold(),
        ).strip("_")
        if (
            normalized_role.endswith("s")
            and not normalized_role.endswith(("ss", "us", "is"))
            and len(normalized_role) > 3
        ):
            normalized_role = normalized_role[:-1]
        suffix = qt_type_suffixes.get(widget_type, "widget")
        if not normalized_role or normalized_role == suffix:
            return suffix
        return (
            normalized_role
            if normalized_role.endswith("_" + suffix)
            else f"{normalized_role}_{suffix}"
        )

    for match in re.finditer(
        r"\b(Q[A-Z][A-Za-z0-9_]*)\s+for\s+(?:the\s+)?"
        r"([a-z_][A-Za-z0-9_-]*)\b",
        text,
    ):
        widget_type, role = match.groups()
        inferred_identifiers.append(
            (role_identifier(role, widget_type), widget_type)
        )
    for match in re.finditer(
        r"\b([A-Z][A-Za-z0-9_-]*(?:\s+and\s+"
        r"[A-Z][A-Za-z0-9_-]*)+)\s+"
        r"(Q[A-Z][A-Za-z0-9_]*s?)\b",
        text,
    ):
        labels, raw_widget_type = match.groups()
        widget_type = raw_widget_type.removesuffix("s")
        for label in re.split(r"\s+and\s+", labels):
            inferred_identifiers.append(
                (role_identifier(label, widget_type), widget_type)
            )
    for match in re.finditer(
        r"\b([a-z_][A-Za-z0-9_-]*)\s+"
        r"(Q[A-Z][A-Za-z0-9_]*)\b",
        text,
    ):
        role, widget_type = match.groups()
        canonical_type = next(
            (
                candidate
                for candidate in qt_type_suffixes
                if widget_type.casefold()
                in {candidate.casefold(), f"{candidate.casefold()}s"}
            ),
            widget_type,
        )
        if canonical_type.casefold() == "qt":
            continue
        if role.casefold() not in {
            "a", "add", "an", "and", "create", "the", "with"
        }:
            inferred_identifiers.append(
                (role_identifier(role, canonical_type), canonical_type)
            )
    role_specific_widget_types = {
        widget_type for _identifier, widget_type in inferred_identifiers
    }

    def semantic_control_type(role: str) -> str:
        """Choose a concrete Qt control from the role's interaction semantics."""

        normalized = role.casefold()
        if re.search(r"\b(?:choice|choose|mode|category|dropdown|combo)\b", normalized):
            return "QComboBox"
        if re.search(
            r"\b(?:select|selection|filter|search|name|path|text|query)\b",
            normalized,
        ):
            return "QLineEdit"
        if re.search(r"\b(?:enable|enabled|toggle|check|boolean)\b", normalized):
            return "QCheckBox"
        if re.search(r"\b(?:count|amount|number|index|quantity)\b", normalized):
            return "QSpinBox"
        if re.search(r"\b(?:run|apply|submit|generate|create|execute)\b", normalized):
            return "QPushButton"
        return "QWidget"

    for control_clause in re.findall(
        r"\bcontrols?\s+for\s+([^.!?;\n]+)",
        text,
        flags=re.IGNORECASE,
    ):
        for role in re.split(r"\s*(?:,|\band\b)\s*", control_clause):
            normalized_role = re.sub(
                r"^(?:a|an|the)\s+",
                "",
                role.strip(),
                flags=re.IGNORECASE,
            )
            normalized_role = re.sub(
                r"\b(?:control|controls|capability|operation)\b.*$",
                "",
                normalized_role,
                flags=re.IGNORECASE,
            ).strip()
            if normalized_role:
                widget_type = semantic_control_type(normalized_role)
                inferred_identifiers.append(
                    (
                        role_identifier(normalized_role, widget_type),
                        widget_type,
                    )
                )
    for widget_type, suffix in qt_type_suffixes.items():
        if (
            widget_type not in role_specific_widget_types
            and re.search(rf"\b{re.escape(widget_type)}s?\b", text)
        ):
            inferred_identifiers.append((suffix, widget_type))

    contracts: list[dict[str, str]] = []
    for identifier in identifiers:
        identifier_match = re.search(rf"\b{re.escape(identifier)}\b", text)
        start = identifier_match.start() if identifier_match else 0
        end = identifier_match.end() if identifier_match else 0
        local_prefix = text[max(0, start - 64):start]
        local_suffix = text[end:min(len(text), end + 64)]
        explicit_type = re.search(
            r"\b(Q[A-Z][A-Za-z0-9_]*)\s+(?:named\s+)?$",
            local_prefix,
        )
        if not explicit_type:
            explicit_type = re.search(
                r"^\s*(?::|as\b|\()\s*(Q[A-Z][A-Za-z0-9_]*)\b",
                local_suffix,
            )
        widget_type = explicit_type.group(1) if explicit_type else ""
        if not widget_type:
            for suffix, candidate_type in sorted(
                suffix_types.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                if identifier.casefold().endswith(suffix):
                    widget_type = candidate_type
                    break
        if not widget_type:
            normalized_prefix = re.sub(
                r"[^a-z0-9]+", " ", local_prefix.casefold()
            ).strip()
            for descriptor, candidate_type in sorted(
                descriptor_types.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                if normalized_prefix.endswith(descriptor):
                    widget_type = candidate_type
                    break
        contracts.append({
            "name": identifier,
            "type": widget_type,
            "construction_required": True,
            "runtime_use_required": True,
        })
    existing_names = {contract["name"] for contract in contracts}
    for identifier, widget_type in inferred_identifiers:
        if identifier in existing_names:
            continue
        contracts.append({
            "name": identifier,
            "type": widget_type,
            "construction_required": True,
            "runtime_use_required": True,
        })
        existing_names.add(identifier)
    return contracts


def _signal_contracts(text: str) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    seen: set[str] = set()
    patterns = (
        r"\bemit\s+([a-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)",
        r"\b([a-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)\s+(?:Qt\s+)?signal\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            name = match.group(1)
            if name in seen:
                continue
            arguments = [
                value.strip()
                for value in match.group(2).split(",")
                if value.strip()
            ]
            contracts.append({
                "name": name,
                "arguments": arguments,
                "declaration_required": True,
                "emit_required": True,
            })
            seen.add(name)
    for match in re.finditer(
        r"\b([a-z_][A-Za-z0-9_]*(?:\s*(?:,|and)\s*"
        r"[a-z_][A-Za-z0-9_]*)+)\s+(?:Qt\s+)?signals?\b",
        text,
        flags=re.IGNORECASE,
    ):
        for name in re.findall(
            r"[a-z_][A-Za-z0-9_]*",
            match.group(1),
            flags=re.IGNORECASE,
        ):
            normalized_name = name.casefold()
            if normalized_name in {"and", "or"} or normalized_name in seen:
                continue
            contracts.append({
                "name": normalized_name,
                "arguments": [],
                "declaration_required": True,
                "emit_required": True,
            })
            seen.add(normalized_name)
    inferred_payloads = (
        ("completion", ["object"]),
        ("completed", ["object"]),
        ("result", ["object"]),
        ("success", ["object"]),
        ("error", ["str"]),
        ("failed", ["str"]),
        ("failure", ["str"]),
    )
    if re.search(
        r"\b(?:completion|completed|result|success)\b[^.!?\n]{0,100}"
        r"\b(?:and|or|plus|with)\b[^.!?\n]{0,100}"
        r"\b(?:error|failed|failure)\b[^.!?\n]{0,100}\bsignals?\b"
        r"|\b(?:completion|completed|result|success)\s+and\s+"
        r"(?:error|failed|failure)\s+signals?\b",
        text,
        flags=re.IGNORECASE,
    ):
        for name, arguments in inferred_payloads:
            if name not in text.casefold():
                continue
            existing = next(
                (
                    contract
                    for contract in contracts
                    if str(contract.get("name") or "").casefold() == name
                ),
                None,
            )
            if existing is not None:
                if not existing.get("arguments"):
                    existing["arguments"] = list(arguments)
                continue
            contracts.append({
                "name": name,
                "arguments": list(arguments),
                "declaration_required": True,
                "emit_required": True,
            })
            seen.add(name)
    return contracts


def _structured_record_state_terms(text: str) -> list[str]:
    """Return state labels from a request for selectively structured records."""

    if not re.search(
        r"\bstructured\s+(?:records?|results?|rows?|entries)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return []
    match = re.search(
        r"\b(?:for|covering|representing)\s+([^,.;!?\n]{1,160})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    states: list[str] = []
    for value in re.split(r"\s+(?:or|and)\s+|/", match.group(1)):
        normalized = re.sub(
            r"\s+(?:records?|results?|rows?|entries|items?|resources?|"
            r"references?|assets?|files?|objects?)\s*$",
            "",
            value.strip(),
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"^(?:the|a|an)\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()
        if normalized and len(normalized.split()) <= 5:
            states.append(normalized.casefold())
    return list(dict.fromkeys(states))


def _validation_cases(
    requirement_id: str,
    text: str,
    *,
    owner: str,
) -> list[str]:
    cases: list[str] = []
    structured_states = _structured_record_state_terms(text)
    if structured_states:
        state_list = ", ".join(f"`{state}`" for state in structured_states)
        cases.extend([
            "Make the verified dependency return mapping records representing each "
            f"requested state ({state_list}) plus one record matching none of them; "
            "prove the owner returns normalized records for every requested state "
            "and excludes the negative control.",
            "Prove every source value is read through keys documented by the "
            "verified dependency return schema, with no invented attribute access "
            "or undocumented mapping key.",
        ])
        if any(state.startswith("un") and len(state) > 2 for state in structured_states):
            cases.append(
                "For every requested negative state prefixed with `un` and backed "
                "by a verified "
                "positive boolean field, prove true maps to exclusion and false "
                "maps to that requested negative state without consulting unrelated "
                "metadata."
            )
        if "missing" in structured_states:
            cases.append(
                "For a path-backed source record, provide one existing path and one "
                "nonexistent path; prove only the nonexistent path is marked missing."
            )
    if re.search(
        r"\b(?:outside|off)\s+(?:of\s+)?(?:the\s+)?UI\s+thread\b"
        r"|\bwithout\s+blocking\s+(?:the\s+)?UI\b"
        r"|\bnon[- ]blocking\b[^.!?\n]{0,80}\b(?:UI|dialog|window|widget)\b",
        text,
        re.IGNORECASE,
    ):
        cases.extend([
            "Trigger the UI action and prove its slot returns without executing "
            "the blocking operation, sleeping, pumping events, or entering a loop.",
            "Complete and fail the background operation deterministically; prove "
            "both outcomes are delivered back to the owner through queued signals, "
            "callbacks, or an equivalent approved event-loop-safe mechanism.",
        ])
    if re.search(
        r"\bconnect(?:ed|s|ing)?\b|\.clicked\b|\.triggered\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Construct the owner and prove the requested signal reaches the "
            "named class method exactly once."
        )
    if re.search(r"\breject\b|\bValueError\b|\bnon-positive\b", text, re.IGNORECASE):
        cases.append(
            "Exercise every stated invalid boundary and assert the requested "
            "exception type without mutating prior valid state."
        )
    if re.search(
        r"\breject\b[^.!?\n]{0,120}\bduplicate\b"
        r"|\bduplicate\b[^.!?\n]{0,120}\b(?:reject|raise|forbid)\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Setup one valid stored value, perform the same identity-bearing add "
            "operation again, and assert the approved duplicate exception while the "
            "stored order, count, and values remain unchanged."
        )
    if re.search(
        r"\b(?:raise|raises|raising)\s+IndexError\b[^.!?\n]{0,100}\bempty\b"
        r"|\bempty\b[^.!?\n]{0,100}\bIndexError\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Construct an owner with no stored values, invoke the requested removal "
            "or read operation, and assert IndexError without changing empty state."
        )
    if re.search(
        r"\b(?:previously\s+)?(?:removed|dequeued|popped)\b"
        r"[^.!?\n]{0,120}\b(?:add|enqueue|insert|store)\w*\s+again\b"
        r"|\b(?:add|enqueue|insert|store)\w*\s+again\b"
        r"[^.!?\n]{0,120}\bafter\s+(?:removal|dequeue|pop(?:ping)?)\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Add one identity-bearing value, remove that exact value, add the same "
            "identity again, and assert the second add succeeds with one stored value."
        )
    if re.search(
        r"\breturns?\s+(?:a\s+)?new\b[^.!?\n]{0,160}"
        r"\bwithout\s+mutating\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Capture the original public state, invoke the requested transformation, "
            "and assert the returned object is distinct, has exactly the stated changed "
            "value, and leaves every original field unchanged."
        )
    if re.search(r"\bpreserve\b[^.!?\n]{0,80}\border\b", text, re.IGNORECASE):
        cases.append(
            "Insert distinct values in a non-sorted order and prove every requested "
            "listing or snapshot preserves that insertion order."
        )
    if re.search(
        r"\b(?:in|first[- ]insertion)\s+order\b",
        text,
        flags=re.IGNORECASE,
    ):
        cases.append(
            "Insert distinct values in non-sorted order and assert the exact "
            "returned order without sorting; repeat the read and prove it does "
            "not mutate owner state."
        )
    if re.search(
        r"\bpreserv(?:e|es|ed|ing)\b[^.!?\n]{0,100}"
        r"\boriginal\s+insertion\s+position\b",
        text,
        flags=re.IGNORECASE,
    ):
        cases.append(
            "Insert at least three distinct entries, replace a non-leading "
            "existing entry, and prove its position and every unrelated entry "
            "remain unchanged."
        )
    if re.search(
        r"\bwithout\s+exposing\b[^.!?\n]{0,80}\bmutable\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Mutate every returned collection or nested value that is documented as "
            "mutable and prove the owner's internal state remains unchanged."
        )
    if re.search(
        r"\bimmutable\s+(?:snapshots?|views?|copies|results?)\b"
        r"|\b(?:snapshots?|views?|copies|results?)\b[^.!?\n]{0,120}"
        r"\bcannot\s+mutate\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Capture the returned snapshot, attempt every supported outer-container "
            "mutation and mutate copied nested mutable values where applicable, then "
            "assert the owner still reports the exact pre-mutation state and order."
        )
    if (
        re.search(
            r"\bimmutable\s+[A-Z][A-Za-z0-9_]*\s+"
            r"(?:data\s+class|dataclass|record|value|class|type)\b",
            text,
            re.IGNORECASE,
        )
        and re.search(
            r"\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*"
            r"(?:dict|list|set|MutableMapping|MutableSequence|MutableSet)\b",
            text,
        )
    ):
        cases.append(
            "Construct the immutable record from caller-owned mutable values, mutate "
            "the original values and every publicly exposed nested mutable value, "
            "and prove the record retains its exact recursively detached state. "
            "Repeat the proof for every copy or transition method."
        )
    if re.search(r"\balways\b.*\b(?:cleanup|remove)\b|\bcleanup\b", text, re.IGNORECASE):
        cases.append(
            "Prove cleanup after success, cancellation, and an injected failure; "
            "no event filter, callback, lock, or temporary UI state may remain."
        )
    if re.search(
        r"\bcancel\s*\([^)]*\)[^.!?\n]{0,120}"
        r"\b(?:remove|delete|discard)s?\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Invoke the cancellation callable with matching and non-matching "
            "values; prove only matching pending values are removed, retained "
            "order is unchanged, and the exact removal count is returned."
        )
    elif re.search(
        r"\bEscape\b|\bcancel(?:led|lation)?\b",
        text,
        re.IGNORECASE,
    ) and re.search(
        r"\b(?:dialog|window|widget|operation|preview|edit|ui|visibility)\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Trigger cancellation and prove original visibility/state is restored "
            "without committing the operation."
        )
    if re.search(
        r"\bevery(?:\s+(?:one|1))?\s+second\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Verify the timer interval is 1000 milliseconds and a timeout refreshes "
            "the displayed state."
        )
    if re.search(r"\bdo\s+not\s+duplicate\b|\bmust\s+not\s+duplicate\b", text, re.IGNORECASE):
        cases.append(
            "Inspect the generated AST and imports to prove the dependency is imported "
            "from its canonical owner and not redefined."
        )
    if re.search(
        r"\bif\s+__name__\b|\brunnable\b|\bruns?\s+standalone\b"
        r"|\bstandalone\b[^.!?\n]{0,60}\bentry\s+point\b",
        text,
        re.IGNORECASE,
    ):
        if re.search(
            r"\b(?:QApplication|PySide|PyQt|Qt|dialog|window|widget)\b",
            text,
            re.IGNORECASE,
        ):
            cases.append(
                "Run the module entry point with a disposable application harness and "
                "prove it constructs and shows the requested top-level object."
            )
        else:
            cases.append(
                "Run the module entry point in a disposable process and assert its "
                "requested output and successful exit status."
            )
    if re.search(
        r"\b(?:display(?:s|ed|ing)?|lists|listed|listing|show(?:s|ed|ing)?)\b"
        r"(?!\s+(?:containing|of|with)\b)"
        r"(?:\s+the)?\s+(?:current\s+)?[a-z_][A-Za-z0-9_]*",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Seed the dependency with known values, refresh the owner, and assert the "
            "displayed collection exactly matches the dependency read interface."
        )
    if re.search(
        r"\bclear\b[^.!?\n]{0,100}\b(?:immediately\s+)?refresh\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Trigger the clear action and prove dependency clear occurs before one "
            "synchronous refresh, leaving the displayed collection empty."
        )
    if re.search(r"\btyped\b|\btype hints?\b", text, re.IGNORECASE):
        cases.append(
            "Inspect the generated public declarations and assert their parameters, "
            "returns, and declared fields carry concrete type annotations."
        )
    if re.search(r"\block\b|\bthread-safe\b", text, re.IGNORECASE):
        cases.append(
            "Exercise concurrent mutation and prove all shared-state writes use the "
            "declared synchronization boundary."
        )
    method_matches = list(re.finditer(
        r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*\([^()]*\)",
        text,
    ))
    method_matches = [
        match
        for match in method_matches
        if (
            match.group(1).casefold() not in _MODULE_CALLABLES
            or _explicit_callable_declaration(match.group(1), text)
        )
    ]
    for index, method_match in enumerate(method_matches):
        clause_end = (
            method_matches[index + 1].start()
            if index + 1 < len(method_matches)
            else len(text)
        )
        method_name = method_match.group(1)
        clause = text[method_match.end():clause_end].strip(" ,;")
        if re.search(r"\bat\s+(?:the\s+)?threshold\b", clause, re.IGNORECASE):
            cases.append(
                f"Invoke `{method_name}` up to the configured threshold; prove the "
                "stated transition occurs on the threshold call, not before it."
            )
        if re.search(
            r"\bafter\s+(?:the\s+)?(?:timeout|delay|interval|duration)\b",
            clause,
            re.IGNORECASE,
        ):
            cases.append(
                f"Arrange the prerequisite state, invoke `{method_name}` before the "
                "configured time boundary, advance the injected/configured time "
                f"source, invoke `{method_name}` again, and assert the stated "
                "post-timeout transition."
            )
        if re.search(r"\braises?\b[^,;]*\bwhile\b", clause, re.IGNORECASE):
            cases.append(
                f"Invoke `{method_name}` while the stated condition holds and assert "
                "the requested exception without bypassing the public method."
            )
        if re.search(
            r"\b(?:closes?|resets?|clears?)\b",
            clause,
            re.IGNORECASE,
        ):
            cases.append(
                f"Place the owner in a non-default state, invoke `{method_name}`, "
                "and prove every stated state and counter reset."
            )
    if re.search(
        r"\bexpired\b|\bexpiry\b|\bTTL\b|\bttl_seconds\b",
        text,
        re.IGNORECASE,
    ):
        cases.append(
            "Use a controllable clock to prove live values remain available and "
            "expired values are lazily removed."
        )
    if re.search(r"\bsave\b", text, re.IGNORECASE):
        cases.append(
            "Mock only the verified external save boundary and assert the newly "
            "created object or canonical path is passed with the approved signature."
        )
    if (
        owner.rsplit(".", 1)[-1] in {"run_self_test", "self_test"}
        or owner.rsplit(".", 1)[-1].startswith("test_")
    ):
        proof_match = re.search(
            r"\bprov(?:e[sd]?|ing)\b\s+(.+)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if proof_match:
            proof_clauses = [
                clause.strip(" ,.;")
                for clause in re.split(
                    r",|\band\b",
                    proof_match.group(1),
                    flags=re.IGNORECASE,
                )
                if clause.strip(" ,.;")
            ]
            cases.extend(
                f"Invoke `{owner}` and prove this exact observable clause: {clause}."
                for clause in proof_clauses
            )
    if not cases:
        exact_requirement = " ".join(str(text or "").split())
        cases.append(
            f"Setup the minimum valid state for `{owner}`; invoke only the public "
            f"operation owned by {requirement_id}; assert this exact requested "
            f"postcondition and every stated rejection without substituting a weaker "
            f"proxy check: {exact_requirement}"
        )
    cases = list(dict.fromkeys(cases))
    generic_invalid_boundary = (
        "Exercise every stated invalid boundary and assert the requested "
        "exception type without mutating prior valid state."
    )
    if generic_invalid_boundary in cases and len(cases) > 1:
        cases.remove(generic_invalid_boundary)
    return cases


def _mechanics(
    text: str,
    evidence: Iterable[Mapping[str, Any]],
    requirement_id: str = "",
) -> list[str]:
    steps: list[str] = []
    is_entry_point_requirement = bool(re.search(
        r"\bif\s+__name__\b|\b__main__\b|\bruns?\s+standalone\b"
        r"|\bstandalone\b[^.!?\n]{0,60}\bentry\s+point\b"
        r"|\bguarded\s+(?:main|entry\s+point)\b",
        text,
        flags=re.IGNORECASE,
    ))
    if re.search(
        r"\bcreate\b[^.!?\n]{0,80}\b(?:file|package)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Create exactly the files already owned by the approved manifest under "
            "the requested package path; do not add, rename, or infer any undeclared "
            "production, test, example, or package files."
        )
    evidence_targets = [
        str(item.get("name") or "")
        for item in evidence
        if item.get("selected_for_generation")
        and str(item.get("supports") or "")
        and (
            not requirement_id
            or requirement_id in {
                str(value) for value in item.get("requirement_ids") or []
            }
        )
        and str(item.get("provider") or "")
        != "installed_package_capability_search"
    ]
    if evidence_targets:
        steps.append(
            "Use only these verified capability targets for the requested external "
            "actions: " + ", ".join(evidence_targets)
        )
        if any(
            target.startswith(
                ("unreal.", "maya.", "cmds.", "bpy.", "pyfbsdk.")
            )
            for target in evidence_targets
        ):
            steps.append(
                "Call each host API with the exact verified signature. Never use "
                "getattr, hasattr, eval, dynamically constructed member names, or "
                "string-valued stand-ins for host classes/enums. Map user-facing "
                "choices to explicit verified enum members."
            )
    declaration_match = re.search(
        r"\b([A-Za-z_][A-Za-z0-9_]*\.py)\s+"
        r"(?:must\s+)?"
        r"(?:define|defines|defining|contain|contains|containing|"
        r"implement|implements|provide|provides|with)\s+"
        r"([A-Z][A-Za-z0-9_]*)\b",
        text,
        flags=re.IGNORECASE,
    )
    if declaration_match:
        base_match = re.search(
            rf"\b{re.escape(declaration_match.group(2))}\b\s+"
            r"(?:inheriting\s+from|subclassing|extends)\s+"
            r"([A-Z][A-Za-z0-9_.]*)\b",
            text,
            flags=re.IGNORECASE,
        )
        steps.append(
            f"Declare `{declaration_match.group(2)}` in "
            f"`{declaration_match.group(1)}`"
            + (
                f" with verified base `{base_match.group(1)}`."
                if base_match
                else " as the requested top-level owner."
            )
        )
    requested_attribute_contracts = _attribute_contracts(text)
    if requested_attribute_contracts and re.search(
        r"(?:dialog|widget|window|class)",
        text,
        flags=re.IGNORECASE,
    ):
        requested_attributes = list(dict.fromkeys(
            str(contract.get("name") or "")
            for contract in requested_attribute_contracts
            if str(contract.get("name") or "")
        ))
        if requested_attributes:
            steps.extend([
                "Initialize these exact owner attributes during construction: "
                + ", ".join(f"`self.{name}`" for name in requested_attributes)
                + ".",
                "Attach every requested owner control to a constructor-reachable "
                "layout.",
            ])
            checkbox_names = [
                name
                for name in requested_attributes
                if name.endswith(("_checkbox", "_check_box", "_check"))
            ]
            value_input_names = [
                name
                for name in requested_attributes
                if name.endswith(
                    ("_input", "_combo", "_combobox", "_spinbox", "_slider")
                )
            ]
            collection_names = [
                name
                for name in requested_attributes
                if name.endswith(("_list", "_table", "_tree", "_results"))
            ]
            progress_names = [
                name
                for name in requested_attributes
                if "progress" in name
            ]
            status_names = [
                name
                for name in requested_attributes
                if name.endswith(("_status", "_status_label"))
                or "status" in name
            ]
            if checkbox_names:
                steps.extend([
                    "Read each requested checkbox through `isChecked()` when "
                    "the owned action runs: "
                    + ", ".join(f"`self.{name}`" for name in checkbox_names)
                    + ".",
                    "Apply each requested checkbox boolean to the documented "
                    "operation, filtering, or result presentation.",
                ])
            if value_input_names:
                steps.extend([
                    "Read every requested input through its real Qt accessor "
                    "when the owned action runs: "
                    + ", ".join(
                        f"`self.{name}`" for name in value_input_names
                    )
                    + ".",
                    "Pass each requested input's typed value into the approved "
                    "operation parameter with the matching semantic role.",
                ])
            if collection_names:
                steps.append(
                    "Replace the requested result collection from the completed "
                    "operation result; do not populate it with synthetic constants "
                    "or records unrelated to the returned operation data: "
                    + ", ".join(
                        f"`self.{name}`" for name in collection_names
                    )
                    + "."
                )
            if progress_names:
                steps.extend([
                    "Apply integer progress callback values to the requested "
                    "progress control range from `total_steps`: "
                    + ", ".join(
                        f"`self.{name}`" for name in progress_names
                    )
                    + ".",
                    "Apply integer `current_step` values to each requested "
                    "progress control value.",
                ])
            if status_names:
                steps.append(
                    "Set each requested status control text from the current "
                    "operation status payload: "
                    + ", ".join(
                        f"`self.{name}`" for name in status_names
                    )
                    + "."
                )
    if re.search(
        r"\b(?:completion|success)\b[^.!?\n]{0,100}\bsignals?\b"
        r"|\berror\b[^.!?\n]{0,100}\bsignals?\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.extend([
            "Declare typed completion and error signals on the worker boundary.",
            "Connect both worker signals to their exact owner handlers before dispatch.",
            "On successful execution, emit the completion signal exactly once.",
            "On failed execution, emit the error signal exactly once.",
        ])
    if re.search(
        r"\b(?:instead\s+of|rather\s+than)\s+importing\b"
        r"|\bwithout\s+importing\b"
        r"|\b(?:do\s+not|don't|never|must\s+not)\s+import\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Route the owned external behavior exclusively through the explicitly "
            "requested dependency owners and reject direct imports of every displaced "
            "module; the request-specific dependency rule overrides general host-import "
            "allowances."
        )
    if re.match(
        r"^\s*(?:do\s+not|don't|never|must\s+not|without)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Forbid every named operation in the approved owner and validate that "
            "no handler contains or reaches those blocking calls."
        )
    if re.search(
        r"^\s*(?:reject|refuse|raise|fail)\b"
        r"|\bmust\s+(?:reject|refuse|raise|fail)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Validate the stated invalid condition before dependent side effects; "
            "raise a specific exception with an actionable message and leave prior "
            "state unchanged."
        )
    if re.search(
        r"\b(?:detailed|complete|descriptive)\s+public\s+docstrings?\b"
        r"|\bdocstrings?\b[^.!?\n]{0,100}"
        r"\b(?::param|:return:|parameters?|returns?)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Write a substantive behavioral summary on every public owner and callable, "
            "with one `:param name:` field per parameter, a `:return:` field describing "
            "the concrete returned value or `None`, and one `:raises ErrorType:` field "
            "for every exception explicitly raised by that callable."
        )
    if re.search(
        r"\b(?:outside|off)\s+(?:of\s+)?(?:the\s+)?UI\s+thread\b"
        r"|\bwithout\s+blocking\s+(?:the\s+)?UI\b"
        r"|\bnon[- ]blocking\b[^.!?\n]{0,80}\b(?:UI|dialog|window|widget)\b",
        text,
        re.IGNORECASE,
    ):
        steps.extend([
            "Dispatch the blocking operation through a verified background worker, "
            "executor, task, or thread capability from approved evidence; the UI "
            "signal handler must enqueue work and return immediately.",
            "Deliver success and failure back to the UI owner through queued signals, "
            "callbacks, or an equivalent event-loop-safe completion mechanism.",
            "Retain the active worker on the UI owner until completion or failure, "
            "then release that retained reference from the completion path.",
            "Start background work only from the requested UI action; do not launch "
            "the operation during construction unless the request explicitly requires "
            "automatic startup.",
                "Declare a typed worker progress signal carrying `(int current_step, "
                "int total_steps, str status)`.",
                "Pass the background operation a progress callback that emits the "
                "typed worker progress signal.",
                "Connect the worker progress signal to a dialog progress handler.",
                "Set the declared progress control range from zero through the "
                "received integer total_steps value in the dialog progress handler.",
                "Set the declared progress control value from the received integer "
                "current_step value in the dialog progress handler.",
                "Set the declared status text control from the received status string "
                "in the dialog progress handler.",
            "Do not sleep, call processEvents(), poll, wait, join, or execute a "
            "blocking loop from a UI slot or signal handler.",
        ])
    if re.search(r"\banywhere\s+on\s+(?:the\s+)?screen\b", text, re.IGNORECASE):
        steps.extend([
            "Create one temporary pointer-capture surface spanning the virtual desktop "
            "rather than relying on events delivered to the hidden dialog.",
            "Translate the accepted global position to the owning screen before reading "
            "the pixel, so multi-monitor coordinates remain valid.",
            "Route success, Escape, and failure through one idempotent cleanup path.",
        ])
    if re.search(r"\block\b|\bthread-safe\b", text, re.IGNORECASE):
        steps.extend([
            "Own one synchronization primitive inside the state owner and keep every "
            "shared-state mutation within that boundary.",
            "When synchronized public operations compose, use one reentrant lock or "
            "private unlocked helpers; never call a lock-owning public method while "
            "holding a non-reentrant lock.",
        ])
    if re.search(r"\bcycle\b", text, re.IGNORECASE) and re.search(
        r"\bwithout mutating\b|\bprior valid state\b|\brollback\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Validate the proposed relationship against the current graph before "
            "committing it: reject self-links immediately, detect whether the new "
            "relationship closes a reachable path, and leave all collections byte-for-"
            "byte equivalent to their prior state on rejection."
        )
    if (
        re.search(r"\bdependenc(?:y|ies)\b", text, re.IGNORECASE)
        and re.search(
            r"\badd_dependency\s*\(\s*node\s*,\s*dependency\s*\)",
            text,
            re.IGNORECASE,
        )
        and not re.search(
            r"\b(?:weight|payload|metadata|edge_data)\b",
            text,
            re.IGNORECASE,
        )
    ):
        steps.append(
            "The relationship has no payload parameter: store and return the exact "
            "dependency node value only. Do not invent weighted-edge tuples, metadata "
            "wrappers, placeholder payloads, or None sentinels."
        )
    if re.search(r"\bdependenc(?:y|ies)\b", text, re.IGNORECASE) and re.search(
        r"\btopological\b|\binsertion order\b|\bnodes?\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Register both relationship endpoints as nodes. Preserve first-seen order "
            "for deterministic tie-breaking, count each node's unmet dependencies, and "
            "emit every dependency before the node that depends on it."
        )
    if re.search(
        r"\bexpired\b|\bexpiry\b|\bTTL\b|\bttl_seconds\b",
        text,
        re.IGNORECASE,
    ):
        if re.search(
            r"\binjected\b[^.;\n]{0,80}\b(?:clock|time source|time_source)\b",
            text,
            re.IGNORECASE,
        ):
            steps.append(
                "Treat `ttl_seconds` as a relative duration and compute every "
                "deadline and expiry check through the stored injected monotonic "
                "clock/time source. Never bypass that dependency with `time.time()`, "
                "`time.monotonic()`, wall-clock datetime APIs, or sleeping. Both "
                "`get` and `keys` must lazily delete expired entries."
            )
        else:
            steps.append(
                "Treat `ttl_seconds` as a relative duration: compute `expires_at` "
                "with `time.monotonic() + ttl_seconds`, never `time.time()` or "
                "wall-clock datetime APIs. Both `get` and `keys` must lazily delete "
                "expired entries."
            )
    if re.search(
        r"\bconnect(?:ed|s|ing)?\b|\.clicked\b|\.triggered\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Create the widget and connect its signal to an existing bound method during "
            "owner construction; do not emit module-level wiring."
        )
    if re.search(r"\bcall\s+the\s+backend\b", text, re.IGNORECASE):
        callable_names = [
            name
            for name in re.findall(
                r"\b([a-z_][A-Za-z0-9_]*)\s*\(",
                text,
            )
            if name not in {"if", "for", "while"}
        ]
        named_backend = re.search(
            r"\b(?:to|call)\s+([a-z_][A-Za-z0-9_]*)\b",
            text,
            flags=re.IGNORECASE,
        )
        record_names = re.findall(
            r"\b([A-Z][A-Za-z0-9_]*(?:Request|Options|Config|Input))\b",
            text,
        )
        backend_name = (
            callable_names[-1]
            if callable_names
            else (
                named_backend.group(1)
                if named_backend
                else "the approved backend callable"
            )
        )
        record_name = record_names[-1] if record_names else "the approved request object"
        steps.append(
            f"In the construction-connected handler, build `{record_name}` from "
            "every explicitly named input widget and call "
            f"`{backend_name}` exactly once with the approved progress callback. "
            "Do not replace the backend call with a signal emission or a direct "
            "host-API implementation in the UI owner."
        )
    if re.search(
        r"\bprogress_callback\b|\binteger\s+progress\s+steps?\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Invoke `progress_callback(current_step, total_steps, status)` with "
            "integer current/total values and an actionable status string at each "
            "observable stage; when processing a discovered collection, derive the "
            "total from that collection and report monotonic per-item or per-stage "
            "progress rather than a fixed illustrative range. When the callback is "
            "None, continue without emitting."
        )
    if re.search(
        r"\b(?:exclude|excluding|omit|filter(?:ing|ed)?)\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Apply exclusions against the canonical semantic unit named by the "
            "request, not an arbitrary case-sensitive substring. Prove that similar "
            "but non-equal values remain included."
        )
    if re.search(
        r"\b(?:sort|sorted|order|ordered)\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Define a total deterministic ordering key. Preserve the requested "
            "primary order and add a stable semantic tie-breaker."
        )
    if re.search(
        r"\btemporary\b[^.!?\n]{0,80}\b(?:file|path|FBX|asset)\b"
        r"|\b(?:file|path|FBX|asset)\b[^.!?\n]{0,80}\btemporary\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Create the intermediate path with the standard temporary-file APIs, "
            "use the requested extension, pass that exact path between producer and "
            "consumer, and clean it up after success or failure."
        )
    if re.search(
        r"\breturn(?:ing|s|ed)?\s+(?:the\s+)?"
        r"(?:imported|created|loaded|saved|generated)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Capture the exact result returned by the terminal dependency call and "
            "return that object unchanged; do not substitute a status string, boolean, "
            "path, or sentinel."
        )
    if re.search(r"\balways\b.*\b(?:cleanup|remove)\b|\bcleanup\b", text, re.IGNORECASE):
        steps.append(
            "Implement cleanup as an idempotent operation reached from success, cancel, "
            "exception, and owner destruction paths."
        )
    if re.search(
        r"\bevery(?:\s+(?:one|1))?\s+second\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Configure one owner-held timer with a 1000 millisecond interval and "
            "connect its timeout to the approved refresh method."
        )
    if is_entry_point_requirement:
        if re.search(
            r"\b(?:QApplication|PySide|PyQt|Qt|dialog|window|widget)\b",
            text,
            re.IGNORECASE,
        ):
            steps.append(
                "Add a module-owned QApplication entry point that constructs and shows "
                "the approved top-level owner without duplicating application instances."
            )
        else:
            steps.append(
                "Add a module-owned Python entry point that invokes the approved public "
                "callable with the requested example inputs and prints the result."
            )
    display_match = re.search(
        r"\b(?:display(?:s|ed|ing)?|lists|listed|listing|show(?:s|ed|ing)?|"
        r"inspect(?:s|ed|ing)?)\b"
        r"(?!\s+(?:containing|of|with)\b)"
        r"(?:\s+the)?\s+(?:current\s+)?"
        r"([a-z_][A-Za-z0-9_]*)",
        text,
        flags=re.IGNORECASE,
    )
    if (
        display_match
        and not is_entry_point_requirement
        and re.search(
        r"\b(?:assets?|collection|entries|files?|history|items?|list|results?|"
        r"rows?|table|tree|values?)\b",
        text,
        flags=re.IGNORECASE,
        )
    ):
        steps.append(
            f"Read `{display_match.group(1)}` through the approved dependency "
            "interface and replace the displayed collection atomically."
        )
    if re.search(
        r"\bclear\b[^.!?\n]{0,100}\b(?:immediately\s+)?refresh\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Invoke the dependency clear operation first, then synchronously invoke "
            "the owner refresh method before returning."
        )
    if re.search(r"\bpreserve\b[^.!?\n]{0,80}\border\b", text, re.IGNORECASE):
        steps.append(
            "Store ordering explicitly and return a detached ordered view; never "
            "derive insertion order from sorting or expose the mutable backing container."
        )
    if re.search(
        r"\breject\b[^.!?\n]{0,120}\bduplicate\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Track only identities currently stored by the owner, reject a duplicate "
            "before mutating state, and remove the identity from that tracking state "
            "when its value is removed."
        )
    if re.search(
        r"\b(?:raise|raises|raising)\s+IndexError\b[^.!?\n]{0,100}\bempty\b"
        r"|\bempty\b[^.!?\n]{0,100}\bIndexError\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Check the empty-state boundary before removal and raise IndexError without "
            "changing any owner state."
        )
    if re.search(
        r"\b(?:previously\s+)?(?:removed|dequeued|popped)\b"
        r"[^.!?\n]{0,120}\b(?:add|enqueue|insert|store)\w*\s+again\b"
        r"|\b(?:add|enqueue|insert|store)\w*\s+again\b"
        r"[^.!?\n]{0,120}\bafter\s+(?:removal|dequeue|pop(?:ping)?)\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Release an identity from duplicate tracking when its value leaves the "
            "owner so that the same identity can be accepted by a later add operation."
        )
    if re.search(
        r"\b(?:in|first[- ]insertion)\s+order\b"
        r"|\boriginal\s+insertion\s+position\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Use the owner's insertion sequence as authoritative: do not sort "
            "snapshots, and replace an existing mapping value in place without "
            "deleting or reinserting that key or touching unrelated entries."
        )
    if re.search(
        r"\bwithout\s+exposing\b[^.!?\n]{0,80}\bmutable\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Build the result from approved public dependency reads and detached "
            "immutable or copied values; do not read dependency storage attributes "
            "or return an owner-held mutable container."
        )
    if re.search(
        r"\b(?:dataclass|record|class)\b[^.!?\n]{0,160}"
        r"\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*"
        r"(?:str|int|float|bool|dict|list|tuple|set|[A-Z][A-Za-z0-9_]*)\b"
        r"|\b[A-Z][A-Za-z0-9_]*\s+(?:dataclass|record|class)\s+with\b"
        r"[^.!?\n]{0,200}\b[A-Za-z_][A-Za-z0-9_]*\s*:",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Declare every requested typed field on the approved owner, preserve "
            "the stated defaults, and construct immutable declarations with their "
            "approved frozen or read-only semantics."
        )
    if (
        re.search(
            r"\bimmutable\s+[A-Z][A-Za-z0-9_]*\s+"
            r"(?:data\s+class|dataclass|record|value|class|type)\b",
            text,
            re.IGNORECASE,
        )
        and re.search(
            r"\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*"
            r"(?:dict|list|set|MutableMapping|MutableSequence|MutableSet)\b",
            text,
        )
    ):
        steps.append(
            "Recursively detach mutable constructor inputs before storing them in "
            "the immutable owner and expose only immutable nested representations. "
            "Apply the same boundary normalization in copy and transition methods; "
            "frozen attribute assignment alone does not satisfy deep immutability."
        )
    if re.search(
        r"\breject\b[^.!?\n]{0,160}\b(?:empty|blank|negative|invalid|missing)\b"
        r"|\b(?:empty|blank|negative|invalid|missing)\b"
        r"[^.!?\n]{0,160}\b(?:reject|raise|forbid|refuse)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Validate the requested constructor or operation inputs before storing "
            "state and raise ValueError for every stated empty, negative, missing, "
            "or otherwise invalid value."
        )
    structured_states = _structured_record_state_terms(text)
    if structured_states:
        state_list = ", ".join(f"`{state}`" for state in structured_states)
        steps.extend([
            "Treat every dependency result as the verified return-schema type and "
            "read mapping records only through keys present in that schema; never "
            "replace documented mapping access with invented object attributes.",
            f"Derive one explicit boolean predicate for each requested state "
            f"({state_list}) from verified source values or an approved domain "
            "check, then include a record when any requested predicate is true; "
            "do not append every source record unconditionally.",
            "Build a normalized detached record for each included source item with "
            "its stable source identity, the derived state booleans, and an "
            "unambiguous status value; do not return the dependency's mutable "
            "record directly.",
        ])
        negative_states = [
            state
            for state in structured_states
            if state.startswith("un") and len(state) > 2
        ]
        if negative_states:
            steps.append(
                "For each requested negative state prefixed with `un`, derive it as "
                "the logical "
                "negation of the verified positive boolean field with the matching "
                "stem when that field exists; do not infer it from unrelated identity "
                "or namespace metadata."
            )
        if "missing" in structured_states:
            steps.append(
                "When the verified source record exposes a resource path, derive "
                "`missing` from an explicit standard-library existence check on that "
                "path, treating a blank path as missing; do not equate nonblank text "
                "with confirmed existence."
            )
    declared_methods = list(dict.fromkeys(re.findall(
        r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*"
        r"\(\s*(?:self\b[^)]*)?\)\s*(?:->\s*[^,.;]+)?",
        text,
    )))
    if declared_methods:
        steps.append(
            "Define the explicitly requested public method signatures exactly on "
            "the approved owner: "
            + ", ".join(f"`{name}`" for name in declared_methods)
            + "."
        )
    if re.search(
        r"\b(?:return|provide|expose)\b[^.!?\n]{0,160}"
        r"\bimmutable\b[^.!?\n]{0,100}\b(?:snapshots?|views?|copies|results?)\b"
        r"|\b(?:snapshots?|views?|copies|results?)\b[^.!?\n]{0,100}"
        r"\bcannot\s+mutate\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Return a detached immutable snapshot built from current public state; "
            "never return the mutable backing container or values that can mutate "
            "the owner's internal collection."
        )
    if re.search(
        r"\breturns?\s+(?:a\s+)?new\b[^.!?\n]{0,160}"
        r"\bwithout\s+mutating\b",
        text,
        re.IGNORECASE,
    ):
        steps.append(
            "Construct and return a distinct instance from the current public field "
            "values with only the stated field transition applied; do not assign to "
            "the current instance or reuse it as the result."
        )
    method_matches = list(re.finditer(
        r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*\([^()]*\)",
        text,
    ))
    method_matches = [
        match
        for match in method_matches
        if (
            match.group(1).casefold() not in _MODULE_CALLABLES
            or _explicit_callable_declaration(match.group(1), text)
        )
    ]
    transition_verbs = re.compile(
        r"\b(?:allow|block|close|open|raise|reject|reset|return|"
        r"transition|clear|remove|save|load)(?:s|d|es|ed|ing)?\b",
        flags=re.IGNORECASE,
    )
    for index, method_match in enumerate(method_matches):
        clause_end = (
            method_matches[index + 1].start()
            if index + 1 < len(method_matches)
            else len(text)
        )
        clause = text[method_match.end():clause_end].strip(" ,;")
        if not clause or not transition_verbs.search(clause):
            continue
        steps.append(
            f"Implement `{method_match.group(1)}` as its own atomic public "
            f"operation with this exact stated behavior: {clause}. Do not move "
            "that transition into an unrelated method or test fixture."
        )
    if not steps:
        steps.append(
            "Implement the requirement inside its approved owner without adding "
            "undeclared public behavior."
        )
    return list(dict.fromkeys(steps))


def _observable_actions(
    requirement_id: str,
    mechanics: Iterable[str],
    validations: Iterable[str],
) -> list[dict[str, str]]:
    """Convert concrete mechanic prose into machine-inspectable observables."""

    action_patterns = (
        (
            "declaration",
            r"\b(?:build|configure|construct|declare|define|initialize|own)\b",
        ),
        ("dispatch", r"\b(?:dispatch|enqueue|background|worker|executor|thread)\b"),
        ("wiring", r"\b(?:connect|route|signal|callback|emit|wire)\b"),
        ("rejection", r"\b(?:reject|raise|exception|invalid|forbid|refuse)\b"),
        ("return", r"\b(?:return|yield|result|output)\b"),
        (
            "state_transition",
            r"\b(?:add|clear|close|create|delete|load|mutate|open|preserve|"
            r"register|remove|replace|reset|save|set|store|transition|update)\b",
        ),
        (
            "verified_call",
            r"\b(?:call|invoke|execute|import|export|read|write|normalize|"
            r"compute|validate)\b",
        ),
        ("cleanup", r"\b(?:cleanup|restore|release|disconnect)\b"),
    )
    validation_rows = [str(value).strip() for value in validations if str(value).strip()]
    actions: list[dict[str, str]] = []
    for step in mechanics:
        mechanic = str(step).strip()
        if (
            not mechanic
            or mechanic.startswith(
                "Implement the requirement inside its approved owner"
            )
        ):
            continue
        action_kind = next(
            (
                kind
                for kind, pattern in action_patterns
                if re.search(pattern, mechanic, flags=re.IGNORECASE)
            ),
            "",
        )
        if not action_kind:
            continue
        actions.append({
            "kind": action_kind,
            "mechanic": mechanic,
            "observable": (
                validation_rows[min(len(actions), len(validation_rows) - 1)]
                if validation_rows
                else f"Prove the executable effect required by {requirement_id}."
            ),
        })
    return actions


def _propose_cross_file_interfaces(
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    class_chunks = [
        chunk for chunk in chunks if chunk.get("kind") == "class"
    ]
    proposals: list[dict[str, Any]] = []
    for consumer in class_chunks:
        consumer_text = " ".join(
            item["text"] for item in _requirement_texts(consumer)
        )
        dependency_ids = {
                str(item) for item in consumer.get("depends_on") or []
        }
        producers = [
            producer
            for producer in class_chunks
            if producer is not consumer
            and str(producer.get("chunk_id") or "") in dependency_ids
        ]
        action_dependency_match = re.search(
            r"\b(?:call|execute|invoke|run|use)\w*\s+(?:the\s+)?"
            r"([a-z_][A-Za-z0-9_]*)\b",
            consumer_text,
            flags=re.IGNORECASE,
        )
        if action_dependency_match and producers:
            dependency_role = action_dependency_match.group(1).casefold()
            semantic_producers = [
                producer
                for producer in producers
                if dependency_role
                in {
                    term.casefold()
                    for term in re.findall(
                        r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+",
                        str(producer.get("owner") or ""),
                    )
                    if len(term) >= 3
                }
            ]
            if len(semantic_producers) == 1:
                producer = semantic_producers[0]
                public_signatures = [
                    str(signature)
                    for signature in producer.get(
                        "declaration_contract", {}
                    ).get("callable_signatures", [])
                    if re.match(
                        r"def\s+[a-z][A-Za-z0-9_]*\s*\(",
                        str(signature),
                    )
                    and not re.match(
                        r"def\s+__",
                        str(signature),
                    )
                ]
                if len(public_signatures) == 1:
                    signature = public_signatures[0]
                    method_match = re.match(
                        r"def\s+([a-z][A-Za-z0-9_]*)\s*\(",
                        signature,
                    )
                    method_name = (
                        method_match.group(1) if method_match else ""
                    )
                    producer_name = str(producer.get("owner") or "")
                    proposal = {
                        "producer_chunk": producer.get("chunk_id"),
                        "consumer_chunk": consumer.get("chunk_id"),
                        "signature": signature,
                        "reason": (
                            f"`{consumer.get('owner')}` explicitly performs "
                            f"`{action_dependency_match.group(0)}` through "
                            f"`{producer_name}.{method_name}`."
                        ),
                        "approval_required": False,
                        "source": "requested_declaration_contract",
                    }
                    producer.setdefault(
                        "proposed_interfaces", []
                    ).append(proposal)
                    consumer.setdefault(
                        "required_dependency_interfaces", []
                    ).append(proposal)
                    proposals.append(proposal)
                    consumer.setdefault(
                        "implementation_mechanics", []
                    ).append({
                        "requirement_id": "approved_dependency_interfaces",
                        "steps": [
                            f"Import and retain one `{producer_name}` instance "
                            f"inside `{consumer.get('owner')}`.",
                            f"Invoke `{producer_name}.{method_name}` through the "
                            "approved background-operation boundary; bind every "
                            "required parameter from declared controls, signals, "
                            "callbacks, or verified prior results.",
                        ],
                    })
        public_value_match = re.search(
            r"\b(?:return(?:s|ed|ing)?|include(?:s|d|ing)?|"
            r"report(?:s|ed|ing)?|expose(?:s|d|ing)?|read(?:s|ing)?|"
            r"snapshot)\b[^.!?\n]{0,100}?"
            r"\b(?:each|every|the|an?)\s+"
            r"([a-z_][A-Za-z0-9_]*)(?:'s|s')\s+"
            r"([^.!?\n;]+)",
            consumer_text,
            flags=re.IGNORECASE,
        )
        if public_value_match and producers:
            producer_noun = public_value_match.group(1).casefold().rstrip("s")
            semantic_producers = [
                producer
                for producer in producers
                if producer_noun in {
                    term.casefold()
                    for term in re.findall(
                        r"[A-Z]+(?=[A-Z][a-z]|\d|\b)|[A-Z]?[a-z]+|\d+",
                        str(producer.get("owner") or ""),
                    )
                    if len(term) >= 3
                }
            ]
            if len(semantic_producers) == 1:
                producer = semantic_producers[0]
                producer_name = str(producer.get("owner") or "")
                values_text = re.split(
                    r"\b(?:without|while|but|where|so\s+that)\b",
                    public_value_match.group(2),
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
                value_names: list[str] = []
                for value_part in re.split(
                    r"\s*,\s*|\s+\band\b\s+",
                    values_text,
                    flags=re.IGNORECASE,
                ):
                    words = [
                        word.casefold()
                        for word in re.findall(
                            r"\b[a-z_][A-Za-z0-9_]*\b",
                            value_part,
                            flags=re.IGNORECASE,
                        )
                        if word.casefold() not in {
                            "a",
                            "an",
                            "its",
                            "public",
                            "the",
                        }
                    ]
                    if words:
                        value_names.append("_".join(words))
                producer_contract = producer.get("declaration_contract", {})
                producer_signatures = producer_contract.setdefault(
                    "callable_signatures",
                    [],
                )
                for value_name in list(dict.fromkeys(value_names)):
                    existing_signature = next(
                        (
                            str(signature)
                            for signature in producer_signatures
                            if re.search(
                                rf"\b(?:get_)?{re.escape(value_name)}\s*\(",
                                str(signature),
                            )
                        ),
                        "",
                    )
                    method_name = (
                        re.search(
                            r"\bdef\s+([a-z_][A-Za-z0-9_]*)\s*\(",
                            existing_signature,
                        ).group(1)
                        if existing_signature
                        else f"get_{value_name}"
                    )
                    return_type = (
                        "int"
                        if any(
                            token in value_name
                            for token in ("count", "index", "size", "total")
                        )
                        else (
                            "str"
                            if any(
                                token in value_name
                                for token in ("name", "state", "status")
                            )
                            else "Any"
                        )
                    )
                    signature = (
                        existing_signature
                        or f"def {method_name}(self) -> {return_type}"
                    )
                    proposal = {
                        "producer_chunk": producer.get("chunk_id"),
                        "consumer_chunk": consumer.get("chunk_id"),
                        "signature": signature,
                        "reason": (
                            f"`{consumer.get('owner')}` must read `{value_name}` "
                            f"from `{producer_name}` without accessing mutable internals."
                        ),
                        "approval_required": not bool(existing_signature),
                        "source": (
                            "requested_declaration_contract"
                            if existing_signature
                            else "proposed_gap_resolution"
                        ),
                    }
                    producer.setdefault("proposed_interfaces", []).append(
                        proposal
                    )
                    if existing_signature:
                        consumer.setdefault(
                            "required_dependency_interfaces",
                            [],
                        ).append(proposal)
                        proposals.append(proposal)
                    mechanics = consumer.setdefault(
                        "implementation_mechanics",
                        [],
                    )
                    dependency_mechanic = next(
                        (
                            item
                            for item in mechanics
                            if isinstance(item, dict)
                            and item.get("requirement_id")
                            == "approved_dependency_interfaces"
                        ),
                        None,
                    )
                    if dependency_mechanic is None:
                        dependency_mechanic = {
                            "requirement_id": "approved_dependency_interfaces",
                            "steps": [],
                        }
                        mechanics.append(dependency_mechanic)
                    if existing_signature:
                        dependency_mechanic["steps"].append(
                            f"Consume `{producer_name}` only through approved public "
                            f"`{method_name}()` calls for `{value_name}`; do not read "
                            "the producer's storage attributes."
                        )

                consumer_signatures = consumer.get(
                    "declaration_contract",
                    {},
                ).get("callable_signatures", [])
                producer_terms = {
                    producer_noun,
                    re.sub(
                        r"([a-z0-9])([A-Z])",
                        r"\1_\2",
                        producer_name.rsplit(".", 1)[-1],
                    ).casefold(),
                }
                dependency_received_by_method = any(
                    not str(signature).startswith("def __init__(")
                    and any(
                        re.search(
                            rf"\b{re.escape(term)}\b",
                            str(signature),
                            flags=re.IGNORECASE,
                        )
                        for term in producer_terms
                    )
                    for signature in consumer_signatures
                )
                continue
        display_match = re.search(
            r"\b(?:display(?:s|ed|ing)?|list(?:s|ed|ing)?|"
            r"show(?:s|ed|ing)?|inspect(?:s|ed|ing)?)"
            r"(?:\s+the)?\s+(?:current\s+)?"
            r"([a-z_][A-Za-z0-9_]*)",
            consumer_text,
            flags=re.IGNORECASE,
        )
        if not display_match or not producers:
            continue
        noun = display_match.group(1).casefold()
        if noun in {
            "a",
            "an",
            "from",
            "in",
            "into",
            "of",
            "on",
            "the",
            "to",
            "with",
        }:
            continue
        method_name = noun if noun.endswith("s") else f"iter_{noun}"
        semantic_method_matches: list[tuple[dict[str, Any], str]] = []
        for producer_candidate in producers:
            for callable_signature in producer_candidate.get(
                "declaration_contract", {}
            ).get("callable_signatures", []):
                callable_match = re.search(
                    r"\bdef\s+([a-z_][A-Za-z0-9_]*)\s*\(",
                    str(callable_signature),
                )
                if not callable_match:
                    continue
                callable_name = callable_match.group(1)
                if noun in callable_name.casefold().split("_"):
                    semantic_method_matches.append(
                        (producer_candidate, callable_name)
                    )
        if len(semantic_method_matches) == 1:
            _, method_name = semantic_method_matches[0]
        existing_producers = [
            producer
            for producer in producers
            if method_name in set(
                producer.get("declaration_contract", {}).get(
                    "required_methods", []
                )
            )
            or re.search(
                rf"\b{re.escape(method_name)}\s*\(",
                " ".join(
                    producer.get("declaration_contract", {}).get(
                        "callable_signatures", []
                    )
                ),
            )
        ]
        producer = (
            existing_producers[0]
            if len(existing_producers) == 1
            else None
        )
        if producer is None:
            semantic_matches = [
                candidate
                for candidate in producers
                if any(
                    re.search(
                        rf"\b{re.escape(term)}\b",
                        consumer_text,
                        flags=re.IGNORECASE,
                    )
                    for term in re.findall(
                        r"[A-Z]?[a-z]+",
                        str(candidate.get("owner") or ""),
                    )
                    if len(term) >= 3
                )
            ]
            if len(semantic_matches) != 1:
                continue
            producer = semantic_matches[0]
        producer_name = str(producer.get("owner") or "")
        existing = producer in existing_producers
        signature = next(
            (
                str(value)
                for value in producer.get(
                    "declaration_contract", {}
                ).get("callable_signatures", [])
                if re.search(
                    rf"\b{re.escape(method_name)}\s*\(",
                    str(value),
                )
            ),
            "",
        )
        if not existing or not signature:
            producer.setdefault("unresolved_dependency_interfaces", []).append({
                "consumer_chunk": consumer.get("chunk_id"),
                "capability": display_match.group(0),
                "reason": (
                    "No approved producer callable matches the requested "
                    "cross-owner data flow."
                ),
            })
            continue
        proposal = {
            "producer_chunk": producer.get("chunk_id"),
            "consumer_chunk": consumer.get("chunk_id"),
            "signature": signature,
            "reason": (
                f"`{consumer.get('owner')}` must {display_match.group(0)} "
                f"through `{producer_name}`."
            ),
            "approval_required": not existing,
            "source": (
                "requested_declaration_contract"
                if existing
                else "proposed_gap_resolution"
            ),
        }
        producer.setdefault("proposed_interfaces", []).append(proposal)
        consumer.setdefault("required_dependency_interfaces", []).append(
            proposal
        )
        proposals.append(proposal)
    return proposals


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
    chunks = [
        chunk for chunk in plan.get("chunks") or [] if isinstance(chunk, dict)
    ]
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
        chunk["declaration_contract"] = {
            "owner": owner,
            "kind": kind,
            "base": base,
            "callable_signatures": list(dict.fromkeys([
                *_callable_signatures(owner, kind, text),
                *inferred_public_signatures,
                *inferred_private_signatures,
            ])),
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
            "required_methods": list(dict.fromkeys([
                *_required_method_names(owner, kind, text),
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
            ])),
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
            r"\b(?:after|before|followed\s+by|handoff|pipeline|sequence|"
            r"sync|synchroni[sz]e|then)\b",
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
        for task in existing_tasks.values():
            task["requirement_ids"] = [
                str(value)
                for value in task.get("requirement_ids") or []
                if str(value) in task_eligible_requirement_ids
            ]
            if task["requirement_ids"]:
                normalized_tasks.append(task)
        chunk["method_tasks"] = normalized_tasks

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

        public_tasks = [
            task
            for task in method_tasks
            if not str(task.get("name") or "").startswith("_")
        ]
        removed_names: set[str] = set()
        retained_tasks: list[dict[str, Any]] = []
        for task in method_tasks:
            task_name = str(task.get("name") or "")
            if not task_name.startswith("_") or task_name.startswith("__"):
                retained_tasks.append(task)
                continue
            explicitly_requested = bool(re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(task_name)}\s*\(",
                request_text,
            ))
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
    return plan


def validate_implementation_plan_completeness(
    implementation_plan: Mapping[str, Any],
    *,
    original_prompt: str = "",
) -> list[str]:
    """Reject plans that cannot serve as bounded generation contracts."""

    errors: list[str] = []
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
                "quality",
                "documentation",
                "constraint",
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
            if (
                bool(evidence_contract.get("requires_callable_evidence"))
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


def _verification_proof_gaps(
    node: ast.AST,
    clauses: list[str],
) -> list[str]:
    source = ast.unparse(node).casefold()
    calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
    assertions = [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Assert)
        or (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr.startswith("assert")
        )
    ]
    prefix_snapshots: set[str] = set()
    for statement in ast.walk(node):
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        value = statement.value
        is_prefix_snapshot = (
            isinstance(value, ast.Attribute)
            and value.attr == "prefixes"
        ) or (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "tuple"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Attribute)
            and value.args[0].attr == "prefixes"
        )
        if not is_prefix_snapshot:
            continue
        for target in (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        ):
            if isinstance(target, ast.Name):
                prefix_snapshots.add(target.id)
    assertion_text = "\n".join(ast.unparse(item) for item in assertions)
    has_snapshot_assertion = any(
        re.search(rf"\b{re.escape(name)}\b", assertion_text)
        for name in prefix_snapshots
    )
    has_mutation_call = any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr
        in {"add", "append", "clear", "delete", "discard", "pop", "remove", "update"}
        for call in calls
    )
    mapping_assignments = [
        (target.id, statement.lineno)
        for statement in ast.walk(node)
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        and isinstance(statement.value, (ast.Dict, ast.Call))
        for target in (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        if isinstance(target, ast.Name)
    ]
    defensively_exercised = False
    for variable, assigned_line in mapping_assignments:
        passed_line = min(
            (
                call.lineno
                for call in calls
                if call.lineno > assigned_line
                if any(
                    isinstance(argument, ast.Name)
                    and argument.id == variable
                    for argument in call.args
                )
            ),
            default=0,
        )
        mutated_after_pass = any(
            getattr(child, "lineno", 0) > passed_line > assigned_line
            and (
                (
                        isinstance(child, ast.Subscript)
                        and isinstance(child.ctx, (ast.Store, ast.Del))
                    and isinstance(child.value, ast.Name)
                    and child.value.id == variable
                )
                or (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == variable
                    and child.func.attr
                    in {"append", "clear", "pop", "remove", "setdefault", "update"}
                )
            )
            for child in ast.walk(node)
        )
        if passed_line and mutated_after_pass and assertions:
            defensively_exercised = True
            break
    exception_names = {
        ast.unparse(child.type).rsplit(".", 1)[-1]
        for child in ast.walk(node)
        if isinstance(child, ast.ExceptHandler) and child.type is not None
    }
    exception_names.update(
        ast.unparse(argument).rsplit(".", 1)[-1]
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr in {"assertRaises", "assertRaisesRegex"}
        for argument in call.args[:1]
    )
    resolve_calls = [
        ast.dump(call, include_attributes=False)
        for call in calls
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "resolve"
    ]
    repeated_resolve = any(
        resolve_calls.count(call_dump) > 1
        for call_dump in set(resolve_calls)
    )
    observable_calls = [
        ast.dump(call, include_attributes=False)
        for call in calls
        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr.startswith("assert")
        )
    ]
    repeated_observable_call = any(
        observable_calls.count(call_dump) > 1
        for call_dump in set(observable_calls)
    )
    overlapping_literal_routes = any(
        any(
            left != right and (left.startswith(right) or right.startswith(left))
            for left in keys
            for right in keys
        )
        for call in calls
        for argument in call.args[:1]
        if isinstance(argument, ast.Dict)
        for keys in [[
            key.value
            for key in argument.keys
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
        ]]
    )
    remove_assertions = [
        item
        for item in assertions
        if ".remove(" in ast.unparse(item)
    ]
    has_false_remove_proof = any(
        isinstance(item, ast.Assert)
        and isinstance(item.test, ast.UnaryOp)
        and isinstance(item.test.op, ast.Not)
        or (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "assertFalse"
        )
        for item in remove_assertions
    )
    exact_checks = {
        "defensive copying": defensively_exercised,
        "validation": "ValueError" in exception_names,
        "replacement ordering": (
            bool(prefix_snapshots)
            and has_snapshot_assertion
            and ".add(" in source
        ),
        "longest-prefix selection": (
            overlapping_literal_routes and bool(resolve_calls) and bool(assertions)
        ),
        "tie stability": (
            bool(prefix_snapshots)
            and has_snapshot_assertion
            and ".add(" in source
        ),
        "missing-route rejection": "KeyError" in exception_names,
        "immutable detached prefixes": (
            bool(prefix_snapshots)
            and has_snapshot_assertion
            and has_mutation_call
        ),
        "remove results": (
            len(remove_assertions) >= 2 and has_false_remove_proof
        ),
        "clear behavior": ".clear(" in source and "()" in assertion_text,
        "repeatable resolution without state mutation": (
            repeated_resolve
            and bool(prefix_snapshots)
            and has_snapshot_assertion
        ),
    }
    gaps: list[str] = []
    for clause in clauses:
        normalized_clause = clause.casefold()
        if (
            re.search(
                r"\b(?:repeat(?:able|ed|ability)?|same\s+input|"
                r"without\s+(?:shared\s+)?state|stateless)\b",
                normalized_clause,
            )
            and not (repeated_observable_call and bool(assertions))
        ):
            gaps.append(clause)
            continue
        if (
            normalized_clause in exact_checks
            and not exact_checks[normalized_clause]
        ):
            gaps.append(clause)
    return gaps


def _final_value_guard_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Find guards that validate a value before a reducing return transform."""

    gaps: list[str] = []
    for index, statement in enumerate(node.body):
        if not isinstance(statement, ast.If):
            continue
        guarded_name = ""
        if (
            isinstance(statement.test, ast.UnaryOp)
            and isinstance(statement.test.op, ast.Not)
            and isinstance(statement.test.operand, ast.Name)
        ):
            guarded_name = statement.test.operand.id
        if not guarded_name or not any(
            isinstance(child, ast.Raise) for child in ast.walk(statement)
        ):
            continue
        for later in node.body[index + 1:]:
            if not isinstance(later, ast.Return):
                continue
            value = later.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and value.func.attr in {"strip", "lstrip", "rstrip"}
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == guarded_name
            ):
                continue
            gaps.append(
                f"`{guarded_name}` is validated before the final "
                f"`{value.func.attr}()` transformation. Assign the transformed "
                "value first, validate that exact final value, and return it."
            )
    return gaps


def _regex_requirement_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    requirement_text: str,
) -> list[str]:
    """Validate regex shape only when the approved requirement defines it."""

    normalized_requirement = requirement_text.casefold()
    if not (
        "non-alphanumeric" in normalized_requirement
        and re.search(r"\b(?:each|every)\s+run\b", normalized_requirement)
    ):
        return []
    gaps: list[str] = []
    for call in ast.walk(node):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "sub"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
        ):
            continue
        pattern = call.args[0].value
        negated_class = re.search(r"\[\^([^\]]*)\]", pattern)
        preserved = negated_class.group(1) if negated_class else ""
        if (
            r"\W" in pattern
            or r"\w" in preserved
            or r"\s" in preserved
            or "_" in preserved
        ):
            gaps.append(
                f"regex pattern {pattern!r} preserves whitespace or underscore, "
                "which are non-alphanumeric under the approved requirement"
            )
        if re.search(
            r"(?:\[\^[^\]]+\]|\\W)(?:\+|\{1(?:,\d*)?\})",
            pattern,
        ) is None:
            gaps.append(
                f"regex pattern {pattern!r} does not consume a complete run in "
                "one substitution"
            )
    return gaps


def _boundary_trim_requirement_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    requirement_text: str,
) -> list[str]:
    """Require an explicitly requested delimiter trim after normalization."""

    normalized_requirement = requirement_text.casefold()
    if not re.search(
        r"\bremov(?:e|es|ing)\s+leading\s+and\s+trailing\s+hyphens?\b",
        normalized_requirement,
    ):
        return []
    substitution_lines = [
        int(call.lineno)
        for call in ast.walk(node)
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "sub"
        )
    ]
    trim_lines = [
        int(call.lineno)
        for call in ast.walk(node)
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "strip"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "-"
        )
    ]
    if not trim_lines:
        return [
            "the callable never applies `.strip('-')` to remove the requested "
            "leading and trailing hyphens"
        ]
    if substitution_lines and max(trim_lines) < min(substitution_lines):
        return [
            "hyphen trimming occurs before normalization can introduce boundary "
            "hyphens; trim the normalized result instead"
        ]
    return []


def _discarded_pure_transform_gaps(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """Reject ignored return values from known immutable Python transforms."""

    string_names = {
        argument.arg
        for argument in (
            list(node.args.posonlyargs)
            + list(node.args.args)
            + list(node.args.kwonlyargs)
        )
        if (
            isinstance(argument.annotation, ast.Name)
            and argument.annotation.id == "str"
        )
        or (
            isinstance(argument.annotation, ast.Constant)
            and argument.annotation.value == "str"
        )
    }
    immutable_string_methods = {
        "capitalize",
        "casefold",
        "center",
        "expandtabs",
        "format",
        "format_map",
        "join",
        "lower",
        "lstrip",
        "removeprefix",
        "removesuffix",
        "replace",
        "rjust",
        "rstrip",
        "strip",
        "swapcase",
        "title",
        "translate",
        "upper",
        "zfill",
    }
    gaps: list[str] = []
    for statement in ast.walk(node):
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
        ):
            continue
        call = statement.value
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in string_names
            and call.func.attr in immutable_string_methods
        ):
            gaps.append(
                f"result of immutable string transform "
                f"`{ast.unparse(call)}` is discarded"
            )
            continue
        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "re"
            and call.func.attr in {"sub", "subn"}
        ):
            gaps.append(
                f"result of pure regular-expression transform "
                f"`{ast.unparse(call)}` is discarded"
            )
    return gaps



def validate_generated_files_against_implementation_plan(
    implementation_plan: Mapping[str, Any],
    generated_files: list[tuple[str, str, str]],
) -> list[str]:
    """Validate approved declaration and mechanic contracts against generated AST."""

    source_by_path = {
        str(Path(path).resolve()): source
        for path, _original, source in generated_files
    }
    trees: dict[str, ast.Module] = {}
    errors: list[str] = []
    for path, source in source_by_path.items():
        try:
            trees[path] = ast.parse(source, filename=path)
        except SyntaxError as exc:
            errors.append(f"{path}: approved-plan AST validation failed: {exc}")
    approved_requirement_text = " ".join(
        str(requirement.get("text") or "")
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for requirement in chunk.get("requirements") or []
        if isinstance(requirement, Mapping)
    )
    module_entry_paths = {
        str(Path(str(chunk.get("path") or "")).resolve())
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and isinstance(chunk.get("declaration_contract"), Mapping)
        and bool(
            chunk.get("declaration_contract", {}).get(
                "module_entry_point_required"
            )
        )
    }
    for path, tree in trees.items():
        module_bindings = {
            alias.asname or alias.name.split(".", 1)[0]
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        module_bindings.update(
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        )
        module_bindings.update(
            node.name
            for node in tree.body
            if isinstance(
                node,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            )
        )
        builtin_names = set(dir(builtins))

        def call_root(call: ast.Call) -> str:
            current: ast.AST = call.func
            while isinstance(current, ast.Attribute):
                current = current.value
            return current.id if isinstance(current, ast.Name) else ""

        parent_by_node = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for callable_node in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            ancestor = parent_by_node.get(callable_node)
            nested_callable = False
            while ancestor is not None:
                if isinstance(
                    ancestor,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda),
                ):
                    nested_callable = True
                    break
                ancestor = parent_by_node.get(ancestor)
            if nested_callable:
                continue
            local_names = {
                argument.arg
                for argument in (
                    *callable_node.args.posonlyargs,
                    *callable_node.args.args,
                    *callable_node.args.kwonlyargs,
                )
            }
            local_names.update(
                node.id
                for node in ast.walk(callable_node)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, (ast.Store, ast.Param))
            )
            local_names.update(
                alias.asname or alias.name.split(".", 1)[0]
                for node in ast.walk(callable_node)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            local_names.update(
                alias.asname or alias.name
                for node in ast.walk(callable_node)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            )
            local_names.update(
                argument.arg
                for node in ast.walk(callable_node)
                if isinstance(node, ast.Lambda)
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
            )
            unresolved_roots = sorted({
                root
                for call in ast.walk(callable_node)
                if isinstance(call, ast.Call)
                for root in [call_root(call)]
                if root
                and root not in local_names
                and root not in module_bindings
                and root not in builtin_names
            })
            if unresolved_roots:
                errors.append(
                    f"{path}:{callable_node.name}: callable roots are neither "
                    "imported nor defined in scope: "
                    + ", ".join(unresolved_roots)
                )

        if path in module_entry_paths:
            main_guards = [
                node
                for node in tree.body
                if isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
                and any(
                    isinstance(comparator, ast.Constant)
                    and comparator.value == "__main__"
                    for comparator in node.test.comparators
                )
            ]
            if len(main_guards) != 1:
                errors.append(
                    f"{path}: approved module entry point requires exactly one "
                    f"guarded __main__ block; found {len(main_guards)}."
                )

        class_nodes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        signal_arity_by_class: dict[str, dict[str, int]] = {}
        for class_name, class_node in class_nodes.items():
            signal_arity_by_class[class_name] = {
                target.id: len(statement.value.args)
                for statement in class_node.body
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                for target in (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                if isinstance(target, ast.Name)
                and isinstance(statement.value, ast.Call)
                and (
                    (
                        isinstance(statement.value.func, ast.Name)
                        and statement.value.func.id == "Signal"
                    )
                    or (
                        isinstance(statement.value.func, ast.Attribute)
                        and statement.value.func.attr == "Signal"
                    )
                )
            }
        for class_name, class_node in class_nodes.items():
            signal_arities = signal_arity_by_class.get(class_name, {})
            for call in (
                node
                for node in ast.walk(class_node)
                if isinstance(node, ast.Call)
            ):
                if (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "emit"
                    and isinstance(call.func.value, ast.Attribute)
                    and isinstance(call.func.value.value, ast.Name)
                    and call.func.value.value.id == "self"
                    and call.func.value.attr in signal_arities
                    and len(call.args)
                    != signal_arities[call.func.value.attr]
                ):
                    errors.append(
                        f"{path}:{class_name}: signal "
                        f"`{call.func.value.attr}` declares "
                        f"{signal_arities[call.func.value.attr]} argument(s) but "
                        f"emit supplies {len(call.args)}."
                    )
            methods = {
                node.name: node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for method in methods.values():
                worker_types = {
                    target.id: assignment.value.func.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, ast.Assign)
                    and isinstance(assignment.value, ast.Call)
                    and isinstance(assignment.value.func, ast.Name)
                    for target in assignment.targets
                    if isinstance(target, ast.Name)
                    and assignment.value.func.id in signal_arity_by_class
                }
                for call in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and isinstance(node.func.value, ast.Attribute)
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id in worker_types
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Attribute)
                    and isinstance(node.args[0].value, ast.Name)
                    and node.args[0].value.id == "self"
                ):
                    worker_name = call.func.value.value.id
                    signal_name = call.func.value.attr
                    handler_name = call.args[0].attr
                    handler = methods.get(handler_name)
                    if handler is None:
                        continue
                    signal_arity = signal_arity_by_class[
                        worker_types[worker_name]
                    ].get(signal_name)
                    if signal_arity is None:
                        continue
                    positional = [
                        *handler.args.posonlyargs,
                        *handler.args.args,
                    ]
                    if positional and positional[0].arg in {"self", "cls"}:
                        positional = positional[1:]
                    required_handler_args = max(
                        0, len(positional) - len(handler.args.defaults)
                    )
                    if signal_arity < required_handler_args:
                        errors.append(
                            f"{path}:{class_name}.{method.name}: signal "
                            f"`{worker_types[worker_name]}.{signal_name}` emits "
                            f"{signal_arity} argument(s), but connected handler "
                            f"`{handler_name}` requires "
                            f"{required_handler_args}."
                        )
    forbidden_imports_by_path: dict[str, set[str]] = {}
    dependency_constraints_by_path: dict[str, list[str]] = {}
    global_dependency_policy = (
        implementation_plan.get("dependency_policy")
        if isinstance(implementation_plan.get("dependency_policy"), Mapping)
        else {}
    )
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        declaration_contract = chunk.get("declaration_contract")
        chunk_policy = (
            declaration_contract.get("dependency_policy")
            if isinstance(declaration_contract, Mapping)
            and isinstance(
                declaration_contract.get("dependency_policy"), Mapping
            )
            else global_dependency_policy
        )
        forbidden_imports_by_path.setdefault(path, set()).update(
            str(module).casefold()
            for module in chunk_policy.get("forbidden_imports") or []
            if str(module).strip()
        )
        dependency_constraints_by_path.setdefault(path, []).extend(
            str(clause)
            for clause in chunk_policy.get("constraints") or []
            if str(clause).strip()
        )

    def approved_owner_node(
        tree: ast.Module,
        owner: str,
    ) -> ast.AST:
        if not owner or owner == "<module>":
            return tree
        owner_name = owner.rsplit(".", 1)[-1]
        return next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(
                    node,
                    (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                )
                and node.name == owner_name
            ),
            tree,
        )

    def call_path(call: ast.Call) -> str:
        try:
            return ast.unparse(call.func)
        except (AttributeError, ValueError):
            return ""

    def expression_path(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except (AttributeError, ValueError):
            return ""

    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        tree = trees.get(path)
        declaration_contract = chunk.get("declaration_contract")
        if tree is None or not isinstance(declaration_contract, Mapping):
            continue
        owner = str(chunk.get("owner") or "<module>")
        owner_node = approved_owner_node(tree, owner)
        internal_mapping_keys: dict[str, set[str]] = {}
        tools_root = Path(__file__).resolve().parents[2]
        for import_node in (
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and str(node.module or "")
        ):
            imported_module = str(import_node.module or "")
            dependency_trees = [
                candidate_tree
                for candidate_path, candidate_tree in trees.items()
                if Path(candidate_path).stem
                == imported_module.rsplit(".", 1)[-1]
            ]
            module_path = tools_root.joinpath(
                *imported_module.split(".")
            ).with_suffix(".py")
            if module_path.is_file():
                try:
                    dependency_source = module_path.read_text(encoding="utf-8")
                    dependency_trees.append(
                        ast.parse(
                            dependency_source,
                            filename=str(module_path),
                        )
                    )
                except (OSError, UnicodeError, SyntaxError):
                    pass
            for dependency_tree in dependency_trees:
                for dependency_method in (
                    node
                    for node in ast.walk(dependency_tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    keys = {
                        str(key.value)
                        for dictionary in ast.walk(dependency_method)
                        if isinstance(dictionary, ast.Dict)
                        for key in dictionary.keys
                        if isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                    }
                    if keys:
                        internal_mapping_keys.setdefault(
                            dependency_method.name,
                            set(),
                        ).update(keys)
        if internal_mapping_keys:
            def validate_mapping_loop(
                method: ast.FunctionDef | ast.AsyncFunctionDef,
                result_name: str,
                proven_keys: set[str],
            ) -> None:
                for loop in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, (ast.For, ast.AsyncFor))
                    and isinstance(node.iter, ast.Name)
                    and node.iter.id == result_name
                    and isinstance(node.target, ast.Name)
                ):
                    item_name = loop.target.id
                    invalid_attributes = sorted({
                        f"{node.value.id}.{node.attr}"
                        for node in ast.walk(loop)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == item_name
                        and node.attr not in {
                            "clear",
                            "copy",
                            "get",
                            "items",
                            "keys",
                            "pop",
                            "popitem",
                            "setdefault",
                            "update",
                            "values",
                        }
                    })
                    invalid_keys = sorted({
                        str(node.slice.value)
                        for node in ast.walk(loop)
                        if isinstance(node, ast.Subscript)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == item_name
                        and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, str)
                        and str(node.slice.value) not in proven_keys
                    })
                    if invalid_attributes:
                        errors.append(
                            f"{path}:{owner}.{method.name}: internal dependency "
                            "returns mapping records; replace invented item "
                            "attributes with proven keys: "
                            + ", ".join(invalid_attributes)
                            + ". Proven keys: "
                            + ", ".join(sorted(proven_keys))
                            + "."
                        )
                    if invalid_keys:
                        errors.append(
                            f"{path}:{owner}.{method.name}: internal dependency "
                            "mapping does not prove key(s): "
                            + ", ".join(invalid_keys)
                            + ". Proven keys: "
                            + ", ".join(sorted(proven_keys))
                            + "."
                        )

            for method in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                result_schemas: dict[str, set[str]] = {}
                for assignment in ast.walk(method):
                    if not isinstance(
                        assignment,
                        (ast.Assign, ast.AnnAssign),
                    ) or not isinstance(assignment.value, ast.Call):
                        continue
                    terminal = call_path(assignment.value).rsplit(".", 1)[-1]
                    keys = internal_mapping_keys.get(terminal)
                    if not keys:
                        continue
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    ):
                        if isinstance(target, ast.Name):
                            result_schemas[target.id] = set(keys)
                for result_name, proven_keys in result_schemas.items():
                    validate_mapping_loop(method, result_name, proven_keys)

            for class_node in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, ast.ClassDef)
            ):
                methods_by_name = {
                    method.name: method
                    for method in class_node.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                worker_result_schemas: dict[str, set[str]] = {}
                for assignment in (
                    node
                    for method in methods_by_name.values()
                    for node in ast.walk(method)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))
                    and isinstance(node.value, ast.Call)
                ):
                    operation_values = [
                        keyword.value
                        for keyword in assignment.value.keywords
                        if keyword.arg == "operation"
                    ]
                    if not operation_values:
                        continue
                    operation_name = expression_path(
                        operation_values[0]
                    ).rsplit(".", 1)[-1]
                    proven_keys = internal_mapping_keys.get(operation_name)
                    if not proven_keys:
                        continue
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    ):
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            worker_result_schemas[target.attr] = set(proven_keys)
                for call in (
                    node
                    for method in methods_by_name.values()
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                    and len(node.args) == 1
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr
                    in {"complete", "completed", "result", "succeeded"}
                    and isinstance(node.func.value.value, ast.Attribute)
                    and isinstance(node.func.value.value.value, ast.Name)
                    and node.func.value.value.value.id == "self"
                    and isinstance(node.args[0], ast.Attribute)
                    and isinstance(node.args[0].value, ast.Name)
                    and node.args[0].value.id == "self"
                ):
                    proven_keys = worker_result_schemas.get(
                        call.func.value.value.attr
                    )
                    handler = methods_by_name.get(call.args[0].attr)
                    if not proven_keys or handler is None:
                        continue
                    positional = [
                        *handler.args.posonlyargs,
                        *handler.args.args,
                    ]
                    if positional and positional[0].arg in {"self", "cls"}:
                        positional = positional[1:]
                    if positional:
                        validate_mapping_loop(
                            handler,
                            positional[0].arg,
                            proven_keys,
                        )
                        result_name = positional[0].arg
                        for delegated_call in (
                            node
                            for node in ast.walk(handler)
                            if isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "self"
                            and node.func.attr in methods_by_name
                            and node.args
                        ):
                            delegated = methods_by_name[
                                delegated_call.func.attr
                            ]
                            delegated_positional = [
                                *delegated.args.posonlyargs,
                                *delegated.args.args,
                            ]
                            if (
                                delegated_positional
                                and delegated_positional[0].arg
                                in {"self", "cls"}
                            ):
                                delegated_positional = delegated_positional[1:]
                            if not delegated_positional:
                                continue
                            delegated_name = delegated_positional[0].arg
                            consumes_collection = any(
                                isinstance(loop, (ast.For, ast.AsyncFor))
                                and isinstance(loop.iter, ast.Name)
                                and loop.iter.id == delegated_name
                                for loop in ast.walk(delegated)
                            )
                            if not consumes_collection:
                                continue
                            argument = delegated_call.args[0]
                            if (
                                isinstance(argument, ast.List)
                                and len(argument.elts) == 1
                                and isinstance(argument.elts[0], ast.Name)
                                and argument.elts[0].id == result_name
                            ):
                                errors.append(
                                    f"{path}:{owner}.{handler.name}: worker "
                                    "result is already a mapping-record "
                                    "collection; do not wrap it in another list "
                                    f"before `{delegated.name}`."
                                )
                            elif (
                                isinstance(argument, ast.Name)
                                and argument.id == result_name
                            ):
                                validate_mapping_loop(
                                    delegated,
                                    delegated_name,
                                    proven_keys,
                                )
        chunk_requirement_text = " ".join(
            (
                str(requirement.get("text") or requirement.get("requirement") or "")
                if isinstance(requirement, Mapping)
                else requirement_text_by_id.get(str(requirement), "")
            )
            for requirement in chunk.get("requirements") or []
        )
        selective_return_requested = bool(
            re.search(
                r"\breturn(?:s|ed|ing)?\b.+\b(?:for|matching|where|that are)\b"
                r".*\b(?:active|eligible|enabled|filtered|invalid|loaded|missing|"
                r"ready|selected|unloaded|valid)\b",
                chunk_requirement_text,
                flags=re.IGNORECASE,
            )
            and not re.search(
                r"\b(?:for|from)\s+(?:every|each|all)\s+selected\b",
                chunk_requirement_text,
                flags=re.IGNORECASE,
            )
        )
        if selective_return_requested:
            requested_record_states = set(
                _structured_record_state_terms(chunk_requirement_text)
            )
            for method in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                parent_by_id = {
                    id(child): parent
                    for parent in ast.walk(method)
                    for child in ast.iter_child_nodes(parent)
                }
                for loop in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, (ast.For, ast.AsyncFor))
                ):
                    loop_item_names = {
                        node.id
                        for node in ast.walk(loop.target)
                        if isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Store)
                    }
                    derived_predicate_names = {
                        target.id
                        for assignment in ast.walk(loop)
                        if isinstance(
                            assignment,
                            (ast.Assign, ast.AnnAssign),
                        )
                        and any(
                            isinstance(node, ast.Name)
                            and node.id in loop_item_names
                            for node in ast.walk(assignment.value)
                        )
                        for target in (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        if isinstance(target, ast.Name)
                    }
                    if "missing" in requested_record_states:
                        missing_assignments = [
                            assignment
                            for assignment in ast.walk(loop)
                            if isinstance(
                                assignment,
                                (ast.Assign, ast.AnnAssign),
                            )
                            and any(
                                isinstance(target, ast.Name)
                                and target.id == "missing"
                                for target in (
                                    assignment.targets
                                    if isinstance(assignment, ast.Assign)
                                    else [assignment.target]
                                )
                            )
                        ]
                        for assignment in missing_assignments:
                            value = assignment.value
                            blank_path_is_missing = not (
                                isinstance(value, ast.IfExp)
                                and isinstance(value.orelse, ast.Constant)
                                and value.orelse.value is False
                            )
                            has_existence_check = any(
                                isinstance(call, ast.Call)
                                and (
                                    (
                                        isinstance(call.func, ast.Attribute)
                                        and call.func.attr
                                        in {"exists", "is_file", "is_dir"}
                                    )
                                    or (
                                        isinstance(call.func, ast.Name)
                                        and call.func.id
                                        in {"exists", "isfile", "isdir"}
                                    )
                                )
                                for call in ast.walk(value)
                            )
                            if (
                                not blank_path_is_missing
                                or not has_existence_check
                            ):
                                errors.append(
                                    f"{path}:{owner}.{method.name}: path-backed "
                                    "`missing` state must treat a blank path as "
                                    "missing and use an explicit existence check."
                                )
                    for call in (
                        node
                        for node in ast.walk(loop)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"add", "append", "extend", "insert"}
                    ):
                        guarded_by_item_predicate = False
                        omitted_states: set[str] = set()
                        parent = parent_by_id.get(id(call))
                        while parent is not None and parent is not loop:
                            if isinstance(parent, ast.If):
                                predicate_names = {
                                    node.id
                                    for node in ast.walk(parent.test)
                                    if isinstance(node, ast.Name)
                                }
                                omitted_states = (
                                    requested_record_states - predicate_names
                                )
                                if (
                                    predicate_names & loop_item_names
                                    or (
                                        predicate_names
                                        & derived_predicate_names
                                        and not omitted_states
                                    )
                                    or (
                                        predicate_names
                                        & requested_record_states
                                        and not omitted_states
                                    )
                                ):
                                    guarded_by_item_predicate = True
                                    break
                            parent = parent_by_id.get(id(parent))
                        if not guarded_by_item_predicate:
                            if omitted_states:
                                errors.append(
                                    f"{path}:{owner}.{method.name}: selective "
                                    "return predicate omits requested state(s): "
                                    + ", ".join(sorted(omitted_states))
                                    + "."
                                )
                            else:
                                errors.append(
                                    f"{path}:{owner}.{method.name}: selective "
                                    "return requirement appends loop records "
                                    "without a per-record eligibility predicate."
                                )
                            break
        for helper in declaration_contract.get("helper_declarations") or []:
            if not isinstance(helper, Mapping):
                continue
            helper_owner = str(helper.get("owner") or "")
            helper_nodes = [
                node
                for node in tree.body
                if isinstance(node, ast.ClassDef)
                and node.name == helper_owner
            ]
            if len(helper_nodes) != 1:
                errors.append(
                    f"{path}:{owner}: approved helper declaration "
                    f"`{helper_owner}` is missing from the target file."
                )
                continue
            helper_node = helper_nodes[0]
            helper_methods = {
                node.name
                for node in helper_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for required_method in helper.get("required_methods") or []:
                if str(required_method) not in helper_methods:
                    errors.append(
                        f"{path}:{helper_owner}: approved helper method "
                        f"`{required_method}` is missing."
                    )
            declared_helper_signals = {
                target.id: len(statement.value.args)
                for statement in helper_node.body
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                for target in (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                if isinstance(target, ast.Name)
                and isinstance(statement.value, ast.Call)
                and (
                    (
                        isinstance(statement.value.func, ast.Name)
                        and statement.value.func.id == "Signal"
                    )
                    or (
                        isinstance(statement.value.func, ast.Attribute)
                        and statement.value.func.attr == "Signal"
                    )
                )
            }
            for signal_contract in helper.get("signals") or []:
                if not isinstance(signal_contract, Mapping):
                    continue
                signal_name = str(signal_contract.get("name") or "")
                expected_arity = len(signal_contract.get("arguments") or [])
                actual_arity = declared_helper_signals.get(signal_name)
                if actual_arity is None:
                    errors.append(
                        f"{path}:{helper_owner}: approved worker signal "
                        f"`{signal_name}` is not declared."
                    )
                elif actual_arity != expected_arity:
                    errors.append(
                        f"{path}:{helper_owner}: approved worker signal "
                        f"`{signal_name}` requires {expected_arity} payload "
                        f"argument(s), but its declaration has {actual_arity}."
                    )
                if signal_contract.get("emit_required"):
                    emitted = any(
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "emit"
                        and isinstance(call.func.value, ast.Attribute)
                        and isinstance(call.func.value.value, ast.Name)
                        and call.func.value.value.id == "self"
                        and call.func.value.attr == signal_name
                        for call in ast.walk(helper_node)
                    )
                    emitted = emitted or any(
                        isinstance(node, ast.Attribute)
                        and node.attr == "emit"
                        and isinstance(node.value, ast.Attribute)
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id == "self"
                        and node.value.attr == signal_name
                        for node in ast.walk(helper_node)
                    )
                    if not emitted:
                        errors.append(
                            f"{path}:{helper_owner}: approved worker signal "
                            f"`{signal_name}` is declared but never emitted."
                        )
            inferred_progress_injection = any(
                isinstance(signal_contract, Mapping)
                and str(signal_contract.get("name") or "") == "progress"
                and bool(signal_contract.get("emit_required"))
                for signal_contract in helper.get("signals") or []
            )
            if (
                helper.get("inject_progress_callback_before_invoke")
                or inferred_progress_injection
            ):
                callback_parameter = str(
                    helper.get("progress_callback_parameter")
                    or "progress_callback"
                )
                callback_value = str(
                    helper.get("progress_callback_value")
                    or "self.progress.emit"
                )
                run_method = next(
                    (
                        node
                        for node in helper_node.body
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == "run"
                    ),
                    None,
                )
                operation_calls = [
                    node
                    for node in ast.walk(run_method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr == "operation"
                ] if run_method is not None else []
                injection_lines: list[int] = []
                for node in ast.walk(run_method) if run_method is not None else []:
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        targets = (
                            node.targets
                            if isinstance(node, ast.Assign)
                            else [node.target]
                        )
                        value = node.value
                        for target in targets:
                            if (
                                isinstance(target, ast.Subscript)
                                and isinstance(target.value, ast.Attribute)
                                and isinstance(target.value.value, ast.Name)
                                and target.value.value.id == "self"
                                and target.value.attr == "kwargs"
                                and isinstance(target.slice, ast.Constant)
                                and target.slice.value == callback_parameter
                                and isinstance(value, ast.Attribute)
                                and isinstance(value.value, ast.Attribute)
                                and isinstance(value.value.value, ast.Name)
                                and value.value.value.id == "self"
                                and f"self.{value.value.attr}.{value.attr}"
                                == callback_value
                            ):
                                injection_lines.append(
                                    int(getattr(node, "lineno", 0))
                                )
                    if isinstance(node, ast.Call) and node in operation_calls:
                        for keyword in node.keywords:
                            if (
                                keyword.arg == callback_parameter
                                and isinstance(keyword.value, ast.Attribute)
                                and isinstance(
                                    keyword.value.value,
                                    ast.Attribute,
                                )
                                and isinstance(
                                    keyword.value.value.value,
                                    ast.Name,
                                )
                                and keyword.value.value.value.id == "self"
                                and (
                                    f"self.{keyword.value.value.attr}."
                                    f"{keyword.value.attr}"
                                )
                                == callback_value
                            ):
                                injection_lines.append(
                                    int(getattr(node, "lineno", 0))
                                )
                first_operation_line = min(
                    (
                        int(getattr(node, "lineno", 0))
                        for node in operation_calls
                    ),
                    default=0,
                )
                if (
                    not injection_lines
                    or not first_operation_line
                    or min(injection_lines) > first_operation_line
                ):
                    errors.append(
                        f"{path}:{helper_owner}.run: approved worker operation "
                        f"must inject `{callback_parameter}={callback_value}` "
                        "before invoking the blocking operation."
                    )
        if isinstance(owner_node, ast.ClassDef):
            helper_owner_names = {
                str(helper.get("owner") or "")
                for helper in declaration_contract.get("helper_declarations") or []
                if isinstance(helper, Mapping)
                and str(helper.get("owner") or "")
            }
            for method in owner_node.body:
                if not isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                constructs_worker = any(
                    isinstance(call, ast.Call)
                    and (
                        (
                            isinstance(call.func, ast.Name)
                            and call.func.id in helper_owner_names
                        )
                        or (
                            isinstance(call.func, ast.Attribute)
                            and call.func.attr in helper_owner_names
                        )
                    )
                    for call in ast.walk(method)
                )
                if not constructs_worker:
                    continue
                worker_lambda_callbacks = {
                    str(keyword.arg)
                    for lambda_node in ast.walk(method)
                    if isinstance(lambda_node, ast.Lambda)
                    for call in ast.walk(lambda_node.body)
                    if isinstance(call, ast.Call)
                    for keyword in call.keywords
                    if keyword.arg and keyword.arg.endswith("callback")
                }
                direct_ui_callbacks = {
                    keyword.value.attr
                    for lambda_node in ast.walk(method)
                    if isinstance(lambda_node, ast.Lambda)
                    for call in ast.walk(lambda_node.body)
                    if isinstance(call, ast.Call)
                    for keyword in call.keywords
                    if keyword.arg
                    and keyword.arg.endswith("callback")
                    and isinstance(keyword.value, ast.Attribute)
                    and isinstance(keyword.value.value, ast.Name)
                    and keyword.value.value.id == "self"
                }
                local_ui_callback_names = {
                    nested.name
                    for nested in method.body
                    if isinstance(
                        nested,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and any(
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        for node in ast.walk(nested)
                    )
                }
                direct_ui_callbacks.update(
                    keyword.value.id
                    for lambda_node in ast.walk(method)
                    if isinstance(lambda_node, ast.Lambda)
                    for call in ast.walk(lambda_node.body)
                    if isinstance(call, ast.Call)
                    for keyword in call.keywords
                    if keyword.arg
                    and keyword.arg.endswith("callback")
                    and isinstance(keyword.value, ast.Name)
                    and keyword.value.id in local_ui_callback_names
                )
                direct_ui_callbacks.update(worker_lambda_callbacks)
                if direct_ui_callbacks:
                    errors.append(
                        f"{path}:{owner}.{method.name}: worker operation passes "
                        "dialog-bound callback(s) directly across the thread "
                        "boundary: "
                        + ", ".join(
                            f"self.{name}" for name in sorted(direct_ui_callbacks)
                        )
                        + ". Route worker progress through its approved signal."
                    )
        if isinstance(owner_node, ast.ClassDef):
            for method in owner_node.body:
                if not isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                local_signals = {
                    target.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    and isinstance(assignment.value, ast.Call)
                    and ast.unparse(assignment.value.func).rsplit(".", 1)[-1]
                    == "Signal"
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Name)
                }
                if local_signals:
                    errors.append(
                        f"{path}:{owner}.{method.name}: Qt Signal declaration(s) "
                        "must be class attributes on a QObject-derived owner, not "
                        "local method values: "
                        + ", ".join(sorted(local_signals))
                        + "."
                    )
        owner_calls = [
            call
            for call in ast.walk(owner_node)
            if isinstance(call, ast.Call)
        ]
        owner_call_paths = [call_path(call) for call in owner_calls]
        owner_call_terminals = {
            value.rsplit(".", 1)[-1] for value in owner_call_paths if value
        }
        owner_callable_reference_terminals = {
            node.attr
            for node in ast.walk(owner_node)
            if isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
        }
        if owner != "<module>":
            imported_bindings = {
                alias.asname or alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            imported_bindings.update(
                alias.asname or alias.name.split(".", 1)[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            plan_chunks_by_id = {
                str(candidate_chunk.get("chunk_id") or ""): candidate_chunk
                for candidate_chunk in implementation_plan.get("chunks") or []
                if isinstance(candidate_chunk, Mapping)
                and str(candidate_chunk.get("chunk_id") or "")
            }
            for dependency_id in chunk.get("depends_on") or []:
                dependency_chunk = plan_chunks_by_id.get(
                    str(dependency_id), {}
                )
                dependency_owner = str(
                    dependency_chunk.get("owner") or ""
                )
                dependency_path = str(
                    Path(
                        str(dependency_chunk.get("path") or "")
                    ).resolve()
                )
                if (
                    not dependency_owner
                    or dependency_owner == "<module>"
                    or dependency_path == path
                ):
                    continue
                required_dependency_interfaces = [
                    item
                    for item in chunk.get(
                        "required_dependency_interfaces", []
                    )
                    if isinstance(item, Mapping)
                    and str(item.get("producer_chunk") or "")
                    == str(dependency_id)
                    and not bool(item.get("approval_required"))
                ]
                dependency_methods = {
                    match.group(1)
                    for item in required_dependency_interfaces
                    for match in [
                        re.search(
                            r"\bdef\s+([a-z_][A-Za-z0-9_]*)\s*\(",
                            str(item.get("signature") or ""),
                        )
                    ]
                    if match
                }
                dependency_referenced = any(
                    isinstance(node, ast.Name)
                    and node.id == dependency_owner
                    for node in ast.walk(owner_node)
                )
                if dependency_owner not in imported_bindings:
                    errors.append(
                        f"[owner:<module>] [repair-scope:module] "
                        f"{path}:<module>: "
                        "approved cross-file dependency "
                        f"`{dependency_owner}` required by `{owner}` is not "
                        "imported."
                    )
                elif not dependency_referenced:
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        f"approved cross-file dependency `{dependency_owner}` is "
                        "imported but never consumed as a type, value, constructor, "
                        "or explicitly approved callable."
                    )
                if dependency_methods and not (
                    dependency_methods
                    & (
                        owner_call_terminals
                        | owner_callable_reference_terminals
                    )
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        "approved cross-file dependency "
                        f"`{dependency_owner}` is not consumed through any "
                        "consumer-approved callable: "
                        + ", ".join(sorted(dependency_methods))
                        + "."
                    )
        required_calls = [
            item
            for item in declaration_contract.get("required_calls") or []
            if (
                isinstance(item, Mapping)
                and str(item.get("name") or "")
                and not (
                    not str(item.get("signature") or "")
                    and str(item.get("name") or "")
                    .rsplit(".", 1)[-1][:1]
                    .isupper()
                )
            )
        ]
        required_call_names = {
            str(item.get("name") or "") for item in required_calls
        }
        required_calls.extend(
            {
                "name": str(
                    item.get("qualified_name") or item.get("name") or ""
                ),
                "import_statement": str(item.get("import_statement") or ""),
            }
            for item in chunk.get("evidence") or []
            if isinstance(item, Mapping)
            and bool(item.get("selected_for_generation"))
            and str(item.get("signature") or "")
            and not str(
                item.get("qualified_name") or item.get("name") or ""
            ).rsplit(".", 1)[-1][:1].isupper()
            and str(item.get("qualified_name") or item.get("name") or "")
            not in required_call_names
        )
        def evidence_mapping_keys(
            required_name: str,
        ) -> set[str]:
            excerpts = [
                str(item.get("source_excerpt") or item.get("source") or "")
                for item in chunk.get("evidence") or []
                if isinstance(item, Mapping)
                and (
                    str(item.get("name") or "") == required_name
                    or str(item.get("qualified_name") or "") == required_name
                    or str(
                        item.get("qualified_name") or item.get("name") or ""
                    ).endswith("." + required_name)
                    or str(
                        item.get("qualified_name") or item.get("name") or ""
                    ).rsplit(".", 1)[-1]
                    == required_name.rsplit(".", 1)[-1]
                )
                and str(
                    item.get("source_excerpt") or item.get("source") or ""
                ).strip()
            ]
            if not excerpts:
                required_terminal = required_name.rsplit(".", 1)[-1]
                tools_root = Path(__file__).resolve().parents[2]
                for import_node in (
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and str(node.module or "")
                ):
                    module_path = tools_root.joinpath(
                        *str(import_node.module).split(".")
                    ).with_suffix(".py")
                    if not module_path.is_file():
                        continue
                    try:
                        dependency_source = module_path.read_text(
                            encoding="utf-8"
                        )
                        dependency_tree = ast.parse(
                            dependency_source,
                            filename=str(module_path),
                        )
                    except (OSError, UnicodeError, SyntaxError):
                        continue
                    for method in (
                        node
                        for node in ast.walk(dependency_tree)
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                        and node.name == required_terminal
                    ):
                        excerpt = (
                            ast.get_source_segment(dependency_source, method)
                            or ast.unparse(method)
                        )
                        if excerpt:
                            excerpts.append(excerpt)
            keys: set[str] = set()
            pending = list(excerpts)
            visited: set[str] = set()
            while pending:
                raw_excerpt = pending.pop()
                raw_lines = str(raw_excerpt).splitlines()
                first_content = next(
                    (line for line in raw_lines if line.strip()),
                    "",
                )
                leading_indent = len(first_content) - len(
                    first_content.lstrip()
                )
                excerpt = "\n".join(
                    (
                        line[leading_indent:]
                        if leading_indent
                        and line.startswith(" " * leading_indent)
                        else line
                    )
                    for line in raw_lines
                ).strip()
                if not excerpt or excerpt in visited:
                    continue
                visited.add(excerpt)
                try:
                    excerpt_tree = ast.parse(excerpt)
                except SyntaxError:
                    try:
                        excerpt_tree = ast.parse(
                            "class _IndexedEvidence:\n" + excerpt
                        )
                    except SyntaxError:
                        continue
                for node in ast.walk(excerpt_tree):
                    if isinstance(node, ast.Dict):
                        keys.update(
                            str(key.value)
                            for key in node.keys
                            if isinstance(key, ast.Constant)
                            and isinstance(key.value, str)
                        )
                    elif (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and ("{" in node.value or "dict(" in node.value)
                    ):
                        pending.append(node.value)
            return keys

        def assigned_names(node: ast.AST) -> set[str]:
            return {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Store)
            }

        for required_call in required_calls:
            required_name = str(required_call.get("name") or "")
            required_terminal = required_name.rsplit(".", 1)[-1]
            mapping_keys = evidence_mapping_keys(required_name)
            if mapping_keys:
                for method in (
                    node
                    for node in ast.walk(owner_node)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    result_names = {
                        target.id
                        for assignment in ast.walk(method)
                        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        and isinstance(assignment.value, ast.Call)
                        and call_path(assignment.value).rsplit(".", 1)[-1]
                        == required_terminal
                        for target in (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        if isinstance(target, ast.Name)
                    }
                    if not result_names:
                        continue
                    item_names = {
                        item_name
                        for loop in ast.walk(method)
                        if isinstance(loop, (ast.For, ast.AsyncFor))
                        and isinstance(loop.iter, ast.Name)
                        and loop.iter.id in result_names
                        for item_name in assigned_names(loop.target)
                    }
                    invalid_attributes = sorted({
                        f"{node.value.id}.{node.attr}"
                        for node in ast.walk(method)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in item_names
                        and node.attr not in {
                            "clear",
                            "copy",
                            "get",
                            "items",
                            "keys",
                            "pop",
                            "popitem",
                            "setdefault",
                            "update",
                            "values",
                        }
                    })
                    invalid_keys = sorted({
                        str(node.slice.value)
                        for node in ast.walk(method)
                        if isinstance(node, ast.Subscript)
                        and isinstance(node.value, ast.Name)
                        and node.value.id in item_names
                        and isinstance(node.slice, ast.Constant)
                        and isinstance(node.slice.value, str)
                        and str(node.slice.value) not in mapping_keys
                    })
                    if invalid_attributes:
                        errors.append(
                            f"{path}:{owner}.{method.name}: verified dependency "
                            f"`{required_name}` returns mapping records; consume "
                            "their proven keys with subscription instead of invented "
                            "attributes: "
                            + ", ".join(invalid_attributes)
                            + "."
                        )
                    if invalid_keys:
                        errors.append(
                            f"{path}:{owner}.{method.name}: verified dependency "
                            f"`{required_name}` records do not prove requested key(s): "
                            + ", ".join(invalid_keys)
                            + ". Proven keys: "
                            + ", ".join(sorted(mapping_keys))
                            + "."
                        )
            verified_import = str(
                required_call.get("import_statement") or ""
            ).strip()
            if verified_import:
                try:
                    verified_import_node = ast.parse(
                        verified_import,
                        filename="<verified-import>",
                    ).body[0]
                except (SyntaxError, IndexError):
                    verified_import_node = None
                import_root = ""
                if isinstance(verified_import_node, ast.ImportFrom):
                    import_root = str(verified_import_node.module or "").split(
                        ".",
                        1,
                    )[0]
                elif isinstance(verified_import_node, ast.Import):
                    import_root = verified_import_node.names[0].name.split(
                        ".",
                        1,
                    )[0]
                if (
                    verified_import_node is not None
                    and import_root not in {
                        "bpy",
                        "maya",
                        "pyfbsdk",
                        "unreal",
                    }
                    and not any(
                        ast.dump(node, include_attributes=False)
                        == ast.dump(
                            verified_import_node,
                            include_attributes=False,
                        )
                        for node in tree.body
                        if isinstance(node, (ast.Import, ast.ImportFrom))
                    )
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        "verified internal dependency import must exist at module "
                        f"scope exactly as `{verified_import}`. Localizing the "
                        "import inside a callable changes the patch/runtime "
                        "binding and is not the approved import surface."
                    )
            matching_calls = [
                call
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1]
                == required_terminal
            ]
            if not matching_calls:
                errors.append(
                    f"{path}:{owner}: approved behavior requires verified call "
                    f"`{required_name}` with signature "
                    f"`{required_call.get('signature') or ''}`, but "
                    "the owning AST contains no invocation of that callable."
                )
                continue
            approved_error_semantics = bool(
                re.search(
                    r"\b(?:error|exception|fail(?:ure)?|reject|unavailable|"
                    r"fallback)\b",
                    " ".join(
                        str(requirement.get("text") or "")
                        for requirement in chunk.get("requirements") or []
                        if isinstance(requirement, Mapping)
                    ),
                    flags=re.IGNORECASE,
                )
            )
            if not approved_error_semantics:
                matching_call_ids = {id(call) for call in matching_calls}
                for method_name, method_node in methods.items():
                    if not any(
                        id(call) in matching_call_ids
                        for call in ast.walk(method_node)
                        if isinstance(call, ast.Call)
                    ):
                        continue
                    for try_node in (
                        node
                        for node in ast.walk(method_node)
                        if isinstance(node, ast.Try)
                    ):
                        for handler in try_node.handlers:
                            broad_handler = (
                                handler.type is None
                                or (
                                    isinstance(handler.type, ast.Name)
                                    and handler.type.id
                                    in {"BaseException", "Exception"}
                                )
                            )
                            if not broad_handler:
                                continue
                            fallback_return = any(
                                isinstance(node, ast.Return)
                                and node.value is not None
                                for statement in handler.body
                                for node in ast.walk(statement)
                            )
                            fallback_output = any(
                                isinstance(node, ast.Call)
                                and call_path(node).rsplit(".", 1)[-1]
                                in {"print", "showMessage", "warning"}
                                for statement in handler.body
                                for node in ast.walk(statement)
                            )
                            if fallback_return or fallback_output:
                                errors.append(
                                    f"[owner:{owner}] [repair-scope:class] "
                                    f"{path}:{owner}.{method_name}: verified "
                                    f"call `{required_name}` is wrapped in an "
                                    "unrequested catch-all error path that "
                                    "prints, displays, or returns fallback data. "
                                    "Preserve the approved dependency result and "
                                    "let unspecified failures propagate."
                                )
            signature = str(required_call.get("signature") or "")
            if signature and "(" in signature and ")" in signature:
                try:
                    signature_tree = ast.parse(
                        "def _verified"
                        + signature[signature.find("("):]
                        + ":\n    pass\n"
                    )
                    signature_args = signature_tree.body[0].args
                except SyntaxError:
                    signature_args = None
                if signature_args is not None:
                    positional_parameters = [
                        *signature_args.posonlyargs,
                        *signature_args.args,
                    ]
                    if (
                        positional_parameters
                        and positional_parameters[0].arg
                        in {"self", "cls"}
                    ):
                        positional_parameters = positional_parameters[1:]
                    maximum_positional = (
                        None
                        if signature_args.vararg is not None
                        else len(positional_parameters)
                    )
                    if maximum_positional is not None:
                        for call in matching_calls:
                            if len(call.args) > maximum_positional:
                                errors.append(
                                    f"{path}:{owner}: verified call "
                                    f"`{required_name}` receives "
                                    f"{len(call.args)} positional argument(s), "
                                    f"but its indexed signature permits at most "
                                    f"{maximum_positional}."
                                )
            parameter_types = {
                str(name): str(type_name)
                for name, type_name in (
                    required_call.get("parameter_types") or {}
                ).items()
                if str(name) and str(type_name)
            }
            if parameter_types:
                assigned_values: dict[str, ast.AST] = {}
                for assignment in ast.walk(owner_node):
                    if (
                        isinstance(assignment, ast.Assign)
                        and len(assignment.targets) == 1
                        and isinstance(assignment.targets[0], ast.Name)
                    ):
                        assigned_values[assignment.targets[0].id] = assignment.value
                    elif (
                        isinstance(assignment, ast.AnnAssign)
                        and isinstance(assignment.target, ast.Name)
                        and assignment.value is not None
                    ):
                        assigned_values[assignment.target.id] = assignment.value

                def inferred_value_kind(
                    value: ast.AST,
                    seen: set[str] | None = None,
                ) -> str:
                    if isinstance(value, ast.Constant):
                        return type(value.value).__name__
                    if isinstance(value, (ast.List, ast.ListComp)):
                        return "list"
                    if isinstance(value, (ast.Tuple, ast.GeneratorExp)):
                        return "tuple"
                    if isinstance(value, (ast.Dict, ast.DictComp)):
                        return "dict"
                    if isinstance(value, ast.Set):
                        return "set"
                    if isinstance(value, ast.Name):
                        visited = set(seen or ())
                        if value.id in visited or value.id not in assigned_values:
                            return ""
                        visited.add(value.id)
                        return inferred_value_kind(
                            assigned_values[value.id],
                            visited,
                        )
                    if isinstance(value, ast.Call):
                        terminal = call_path(value).rsplit(".", 1)[-1]
                        if terminal in {"text", "currentText"}:
                            return "str"
                        if terminal in {"split", "splitlines", "list"}:
                            return "list"
                        if terminal == "dict":
                            return "dict"
                        if terminal in {"int", "value"}:
                            return "int"
                        if terminal == "float":
                            return "float"
                        if terminal in {"bool", "isChecked"}:
                            return "bool"
                    return ""

                def resolved_assigned_value(
                    value: ast.AST,
                    seen: set[str] | None = None,
                ) -> ast.AST:
                    if not isinstance(value, ast.Name):
                        return value
                    visited = set(seen or ())
                    if value.id in visited or value.id not in assigned_values:
                        return value
                    visited.add(value.id)
                    return resolved_assigned_value(
                        assigned_values[value.id],
                        visited,
                    )

                def is_raw_singleton_text_collection(value: ast.AST) -> bool:
                    resolved = resolved_assigned_value(value)
                    if not isinstance(resolved, (ast.List, ast.Tuple)):
                        return False
                    if len(resolved.elts) != 1:
                        return False
                    element = resolved_assigned_value(resolved.elts[0])
                    return (
                        isinstance(element, ast.Call)
                        and call_path(element).rsplit(".", 1)[-1]
                        in {"text", "currentText"}
                    )

                parameter_order = [
                    parameter.arg
                    for parameter in (
                        [*signature_args.posonlyargs, *signature_args.args]
                        if signature_args is not None
                        else []
                    )
                    if parameter.arg not in {"self", "cls"}
                ]
                for call in matching_calls:
                    supplied = {
                        parameter_order[index]: argument
                        for index, argument in enumerate(call.args)
                        if index < len(parameter_order)
                    }
                    supplied.update({
                        str(keyword.arg): keyword.value
                        for keyword in call.keywords
                        if keyword.arg
                    })
                    for parameter_name, argument in supplied.items():
                        expected_type = parameter_types.get(
                            parameter_name, ""
                        ).casefold()
                        actual_kind = inferred_value_kind(argument)
                        expected_kind = next(
                            (
                                kind
                                for kind in (
                                    "list",
                                    "dict",
                                    "tuple",
                                    "set",
                                    "str",
                                    "bool",
                                    "int",
                                    "float",
                                )
                                if re.search(rf"\b{kind}\b", expected_type)
                            ),
                            "",
                        )
                        if (
                            expected_kind
                            and actual_kind
                            and actual_kind != expected_kind
                        ):
                            errors.append(
                                f"{path}:{owner}: verified call `{required_name}` "
                                f"passes `{parameter_name}` as `{actual_kind}`, but "
                                "authoritative API evidence requires "
                                f"`{parameter_types[parameter_name]}`."
                            )
                        optional_collection = bool(
                            re.search(
                                r"\b(?:list|tuple|set)\b",
                                expected_type,
                            )
                            and re.search(
                                r"\b(?:none|optional)\b",
                                expected_type,
                            )
                        )
                        if (
                            optional_collection
                            and is_raw_singleton_text_collection(argument)
                        ):
                            errors.append(
                                f"[owner:{owner}] [repair-scope:class] "
                                f"{path}:{owner}: verified optional collection "
                                f"parameter `{parameter_name}` for "
                                f"`{required_name}` wraps raw UI text as a "
                                "single element without normalizing an empty "
                                "value. Strip and parse the text, then pass a "
                                "typed collection only when values remain; "
                                "otherwise pass None."
                            )
        called_attribute_nodes = {
            id(call.func)
            for call in owner_calls
            if isinstance(call.func, ast.Attribute)
        }
        owner_access_terminals = {
            node.attr
            for node in ast.walk(owner_node)
            if isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and id(node) not in called_attribute_nodes
        }
        for required_access in (
            declaration_contract.get("required_accesses") or []
        ):
            if not isinstance(required_access, Mapping):
                continue
            required_name = str(required_access.get("name") or "")
            required_terminal = required_name.rsplit(".", 1)[-1]
            if required_terminal not in owner_access_terminals:
                errors.append(
                    f"{path}:{owner}: approved behavior requires property access "
                    f"`{required_name}`, but the owning AST contains no non-call "
                    "attribute read for that property."
                )
        required_call_order = [
            str(value)
            for value in declaration_contract.get("required_call_order") or []
            if str(value)
        ]
        if required_call_order:
            required_terminals = [
                value.rsplit(".", 1)[-1] for value in required_call_order
            ]
            callable_nodes = [
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            ordered_chain_found = False
            for callable_node in callable_nodes:
                terminal_sequence = [
                    call_path(call).rsplit(".", 1)[-1]
                    for call in sorted(
                        (
                            node
                            for node in ast.walk(callable_node)
                            if isinstance(node, ast.Call)
                        ),
                        key=lambda node: (
                            int(getattr(node, "lineno", 0)),
                            int(getattr(node, "col_offset", 0)),
                        ),
                    )
                    if call_path(call)
                ]
                cursor = 0
                for terminal in terminal_sequence:
                    if terminal == required_terminals[cursor]:
                        cursor += 1
                        if cursor == len(required_terminals):
                            ordered_chain_found = True
                            break
                if ordered_chain_found:
                    break
            if not ordered_chain_found:
                errors.append(
                    f"{path}:{owner}: no orchestration callable executes the "
                    "approved verified capability chain in order: "
                    + " -> ".join(required_call_order)
                    + "."
                )
        chunk_requirement_text = " ".join(
            str(requirement.get("text") or "")
            for requirement in chunk.get("requirements") or []
            if isinstance(requirement, Mapping)
        )
        direct_owner_callables = (
            [
                callable_node
                for callable_node in owner_node.body
                if isinstance(
                    callable_node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            ]
            if isinstance(owner_node, ast.ClassDef)
            else [owner_node]
            if isinstance(
                owner_node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
            else []
        )
        if isinstance(owner_node, ast.ClassDef):
            referenced_private_names = {
                node.attr
                for node in ast.walk(owner_node)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"self", "cls"}
                and node.attr.startswith("_")
            }
            unreferenced_private_helpers = sorted(
                callable_node.name
                for callable_node in direct_owner_callables
                if callable_node.name.startswith("_")
                and not callable_node.name.startswith("__")
                and callable_node.name not in referenced_private_names
            )
            if unreferenced_private_helpers:
                errors.append(
                    f"{path}:{owner}: private helper callable(s) are never "
                    "referenced by production behavior and introduce dead code: "
                    + ", ".join(unreferenced_private_helpers)
                    + "."
                )
        progress_callback_owners = [
            callable_node
            for callable_node in direct_owner_callables
            if any(
                argument.arg == "progress_callback"
                for argument in (
                    *callable_node.args.posonlyargs,
                    *callable_node.args.args,
                    *callable_node.args.kwonlyargs,
                )
            )
        ]
        if progress_callback_owners and re.search(
            r"\bprogress_callback\b",
            chunk_requirement_text,
            flags=re.IGNORECASE,
        ):
            progress_error_owner = owner
            if (
                isinstance(owner_node, ast.ClassDef)
                and "." not in progress_error_owner
            ):
                progress_error_owner = (
                    f"{owner}.{progress_callback_owners[0].name}"
                )
            progress_calls = [
                call
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1] == "progress_callback"
            ]
            if len(progress_calls) < 2:
                errors.append(
                    f"{path}:{progress_error_owner}: requested progress updates "
                    "require at "
                    "least two observable callback invocations."
                )
            has_iterative_work = any(
                isinstance(
                    node,
                    (
                        ast.For,
                        ast.AsyncFor,
                        ast.ListComp,
                        ast.SetComp,
                        ast.DictComp,
                        ast.GeneratorExp,
                    ),
                )
                for callable_node in progress_callback_owners
                for node in ast.walk(callable_node)
            )
            fixed_progress_totals = [
                call.args[1]
                for call in progress_calls
                if len(call.args) >= 2
                and isinstance(call.args[1], ast.Constant)
                and isinstance(call.args[1].value, int)
            ]
            if (
                has_iterative_work
                and len(fixed_progress_totals) == len(progress_calls)
                and progress_calls
            ):
                errors.append(
                    f"{path}:{progress_error_owner}: iterative work reports only "
                    "fixed progress totals; derive total_steps from the actual work "
                    "collection and emit monotonic progress as units complete."
                )
            operation_terminals = {
                str(item.get("name") or "").rsplit(".", 1)[-1]
                for item in required_calls
            }
            operation_lines = [
                int(getattr(call, "lineno", 0))
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1]
                in operation_terminals
            ]
            progress_lines = [
                int(getattr(call, "lineno", 0))
                for call in progress_calls
            ]
            if (
                operation_lines
                and progress_lines
                and min(progress_lines) >= max(operation_lines)
            ):
                progress_owner_names = [
                    callable_node.name
                    for callable_node in ast.walk(owner_node)
                    if isinstance(
                        callable_node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                    and any(
                        isinstance(call, ast.Call)
                        and call_path(call).rsplit(".", 1)[-1]
                        in operation_terminals
                        for call in ast.walk(callable_node)
                    )
                ]
                progress_owner = (
                    f"{owner}.{progress_owner_names[0]}"
                    if len(set(progress_owner_names)) == 1
                    else owner
                )
                errors.append(
                    f"{path}:{progress_owner}: all progress updates occur after the "
                    "approved work; progress must span the operation lifecycle."
                )
        if re.search(
            r"\btemporary\b.*\b(?:file|path|directory|artifact)\b",
            chunk_requirement_text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            persistent_temp_calls = []
            temporary_provider_calls = []
            for call in owner_calls:
                terminal = call_path(call).rsplit(".", 1)[-1]
                if terminal in {
                    "NamedTemporaryFile",
                    "TemporaryDirectory",
                    "mkdtemp",
                    "mkstemp",
                }:
                    temporary_provider_calls.append(call)
                if terminal in {"mkstemp", "mkdtemp"}:
                    persistent_temp_calls.append(call)
                    continue
                if terminal != "NamedTemporaryFile":
                    continue
                delete_keyword = next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == "delete"
                    ),
                    None,
                )
                if (
                    isinstance(delete_keyword, ast.Constant)
                    and delete_keyword.value is False
                ):
                    persistent_temp_calls.append(call)
            cleanup_terminals = {
                "cleanup",
                "remove",
                "rmdir",
                "rmtree",
                "unlink",
            }
            cleanup_calls = [
                call
                for call in owner_calls
                if call_path(call).rsplit(".", 1)[-1]
                in cleanup_terminals
            ]
            finally_cleanup = any(
                call_path(call).rsplit(".", 1)[-1] in cleanup_terminals
                for try_node in ast.walk(owner_node)
                if isinstance(try_node, ast.Try) and try_node.finalbody
                for statement in try_node.finalbody
                for call in ast.walk(statement)
                if isinstance(call, ast.Call)
            )
            if not temporary_provider_calls:
                errors.append(
                    f"{path}:{owner}: requested temporary resources require "
                    "a temporary-file/directory provider rather than a fixed path."
                )
            if (
                persistent_temp_calls or cleanup_calls
            ) and not finally_cleanup:
                errors.append(
                    f"{path}:{owner}: persistent temporary resources require "
                    "cleanup in a finally path."
                )
        execution_constraints = (
            declaration_contract.get("execution_constraints")
            if isinstance(
                declaration_contract.get("execution_constraints"), Mapping
            )
            else {}
        )
        if execution_constraints.get("requires_off_ui_thread"):
            forbidden_ui_calls = {
                str(value)
                for value in execution_constraints.get(
                    "forbidden_ui_calls", []
                )
                if str(value)
            }
            forbidden_hits = sorted({
                value
                for value in owner_call_paths
                if value.rsplit(".", 1)[-1] in forbidden_ui_calls
            })
            if forbidden_hits:
                errors.append(
                    f"{path}:{owner}: off-UI-thread contract forbids blocking or "
                    "event-pumping calls in the UI owner: "
                    + ", ".join(forbidden_hits)
                    + "."
                )
            dispatch_terminals = {
                "start",
                "submit",
                "run_in_executor",
                "startThread",
            }
            has_background_dispatch = bool(
                owner_call_terminals & dispatch_terminals
            )
            if not has_background_dispatch:
                errors.append(
                    f"{path}:{owner}: off-UI-thread contract has no approved "
                    "background dispatch call such as a worker/thread start, "
                    "executor submit, or event-loop executor dispatch."
                )
            helper_names = {
                str(helper.get("owner") or "")
                for helper in declaration_contract.get(
                    "helper_declarations", []
                )
                if isinstance(helper, Mapping)
                and str(helper.get("owner") or "")
            }
            for method in (
                node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ):
                local_workers = {
                    target.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    and isinstance(assignment.value, ast.Call)
                    and isinstance(assignment.value.func, ast.Name)
                    and assignment.value.func.id in helper_names
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Name)
                }
                started_workers = {
                    call.func.value.id
                    for call in ast.walk(method)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "start"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id in local_workers
                }
                retained_workers = {
                    assignment.value.id
                    for assignment in ast.walk(method)
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    and isinstance(assignment.value, ast.Name)
                    and assignment.value.id in local_workers
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                }
                unretained_workers = sorted(
                    started_workers - retained_workers
                )
                if unretained_workers:
                    errors.append(
                        f"{path}:{owner}.{method.name}: started background worker "
                        "is held only by a local variable and may be destroyed before "
                        "completion; retain it on the owner until a completion or "
                        "failure handler releases it: "
                        + ", ".join(unretained_workers)
                        + "."
                    )
                nested_operations = {
                    node.name: node
                    for node in method.body
                    if isinstance(
                        node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                for constructor_call in (
                    node
                    for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in helper_names
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in nested_operations
                ):
                    operation_node = nested_operations[
                        constructor_call.args[0].id
                    ]
                    operation_argument_names = {
                        argument.arg
                        for argument in [
                            *operation_node.args.posonlyargs,
                            *operation_node.args.args,
                            *operation_node.args.kwonlyargs,
                        ]
                    }
                    if "progress_callback" not in operation_argument_names:
                        errors.append(
                            f"{path}:{owner}.{method.name}: nested worker "
                            "operation must accept the injected "
                            "`progress_callback` parameter."
                        )
                    direct_dialog_callbacks = sorted({
                        keyword.value.attr
                        for call in ast.walk(operation_node)
                        if isinstance(call, ast.Call)
                        for keyword in call.keywords
                        if keyword.arg
                        and keyword.arg.endswith("progress_callback")
                        and isinstance(keyword.value, ast.Attribute)
                        and isinstance(keyword.value.value, ast.Name)
                        and keyword.value.value.id == "self"
                    })
                    if direct_dialog_callbacks:
                        errors.append(
                            f"{path}:{owner}.{method.name}: nested worker "
                            "operation bypasses its injected progress callback "
                            "with dialog method(s): "
                            + ", ".join(direct_dialog_callbacks)
                            + "."
                        )
                    operation_parameters = [
                        argument.arg
                        for argument in [
                            *operation_node.args.posonlyargs,
                            *operation_node.args.args,
                            *operation_node.args.kwonlyargs,
                        ]
                        if argument.arg != "self"
                        and not argument.arg.endswith("progress_callback")
                    ]
                    supplied_operation_args = constructor_call.args[1:]
                    if len(supplied_operation_args) > len(
                        operation_parameters
                    ):
                        errors.append(
                            f"{path}:{owner}.{method.name}: worker constructor "
                            "passes positional value(s) not accepted by its "
                            "bound operation after progress callback injection."
                        )
            connection_sources = [
                expression_path(call.func.value)
                for call in owner_calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr == "connect"
                and isinstance(call.func.value, ast.Attribute)
            ]
            owner_method_names = {
                method.name
                for method in owner_node.body
                if isinstance(
                    method,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
            }
            unresolved_private_signal_targets = sorted({
                argument.attr
                for call in owner_calls
                if isinstance(call.func, ast.Attribute)
                and call.func.attr == "connect"
                for argument in call.args[:1]
                if isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "self"
                and argument.attr.startswith("_")
                and argument.attr not in owner_method_names
            })
            if unresolved_private_signal_targets:
                errors.append(
                    f"{path}:{owner}: signal connections reference undefined "
                    "private handler(s): "
                    + ", ".join(unresolved_private_signal_targets)
                    + "."
                )
            has_done_callback = "add_done_callback" in owner_call_terminals
            has_completion_path = has_done_callback or any(
                value.rsplit(".", 1)[-1].casefold()
                in {"complete", "completed", "finished", "result", "succeeded"}
                for value in connection_sources
            )
            has_error_path = has_done_callback or any(
                value.rsplit(".", 1)[-1].casefold()
                in {"error", "exception", "failed", "failure"}
                for value in connection_sources
            )
            worker_release_required = any(
                "retained worker" in str(step).casefold()
                and (
                    "finished signal" in str(step).casefold()
                    or "finished-signal" in str(step).casefold()
                    or "release" in str(step).casefold()
                    or "disposal" in str(step).casefold()
                )
                for task in chunk.get("method_tasks") or []
                if isinstance(task, Mapping)
                for step in task.get("implementation_mechanics") or []
            )
            if worker_release_required:
                retained_worker_attributes = {
                    target.attr
                    for assignment in ast.walk(owner_node)
                    if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                    and isinstance(assignment.value, ast.Call)
                    and (
                        (
                            isinstance(assignment.value.func, ast.Name)
                            and assignment.value.func.id in helper_names
                        )
                        or (
                            isinstance(assignment.value.func, ast.Attribute)
                            and assignment.value.func.attr in helper_names
                        )
                    )
                    for target in (
                        assignment.targets
                        if isinstance(assignment, ast.Assign)
                        else [assignment.target]
                    )
                    if isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                }
                worker_assignment_methods: dict[str, ast.AST] = {}
                for method in (
                    node
                    for node in owner_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ):
                    for assignment in ast.walk(method):
                        if not isinstance(
                            assignment,
                            (ast.Assign, ast.AnnAssign),
                        ) or not isinstance(assignment.value, ast.Call):
                            continue
                        targets = (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        for target in targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and target.attr in retained_worker_attributes
                            ):
                                worker_assignment_methods[target.attr] = method
                for worker_name, method in worker_assignment_methods.items():
                    assignment_lines = [
                        int(getattr(node, "lineno", 0))
                        for node in ast.walk(method)
                        if isinstance(node, (ast.Assign, ast.AnnAssign))
                        and any(
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == worker_name
                            for target in (
                                node.targets
                                if isinstance(node, ast.Assign)
                                else [node.target]
                            )
                        )
                    ]
                    first_assignment_line = min(
                        assignment_lines,
                        default=10**9,
                    )
                    has_active_worker_guard = any(
                        isinstance(node, ast.If)
                        and int(getattr(node, "lineno", 0))
                        < first_assignment_line
                        and any(
                            isinstance(comparison, ast.Compare)
                            and isinstance(
                                comparison.left,
                                ast.Attribute,
                            )
                            and isinstance(
                                comparison.left.value,
                                ast.Name,
                            )
                            and comparison.left.value.id == "self"
                            and comparison.left.attr == worker_name
                            and any(
                                isinstance(operator, ast.IsNot)
                                for operator in comparison.ops
                            )
                            and any(
                                isinstance(comparator, ast.Constant)
                                and comparator.value is None
                                for comparator in comparison.comparators
                            )
                            for comparison in ast.walk(node.test)
                        )
                        and any(
                            isinstance(statement, (ast.Return, ast.Raise))
                            for statement in ast.walk(node)
                        )
                        for node in ast.walk(method)
                    )
                    disables_trigger = any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "setEnabled"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value is False
                        and int(getattr(node, "lineno", 0))
                        < first_assignment_line
                        for node in ast.walk(method)
                    )
                    if not has_active_worker_guard and not disables_trigger:
                        errors.append(
                            f"{path}:{owner}.{method.name}: background worker "
                            f"`self.{worker_name}` can be overwritten by a repeated "
                            "start; guard an active worker or disable the initiating "
                            "control until terminal cleanup."
                        )
                    has_finished_cleanup = any(
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr == "connect"
                        and isinstance(call.func.value, ast.Attribute)
                        and call.func.value.attr == "finished"
                        and isinstance(call.func.value.value, ast.Attribute)
                        and isinstance(call.func.value.value.value, ast.Name)
                        and call.func.value.value.value.id == "self"
                        and call.func.value.value.attr == worker_name
                        for call in owner_calls
                    )
                    if not has_finished_cleanup:
                        errors.append(
                            f"{path}:{owner}.{method.name}: retained worker "
                            f"`self.{worker_name}` must connect its `finished` signal "
                            "to owner-side cleanup so every terminal path releases "
                            "the worker."
                        )
                terminal_handlers: dict[str, set[str]] = {}
                result_handler_names: set[str] = set()
                for call in owner_calls:
                    if (
                        not isinstance(call.func, ast.Attribute)
                        or call.func.attr != "connect"
                        or not call.args
                        or not isinstance(call.func.value, ast.Attribute)
                        or not isinstance(
                            call.func.value.value,
                            ast.Attribute,
                        )
                        or not isinstance(
                            call.func.value.value.value,
                            ast.Name,
                        )
                        or call.func.value.value.value.id != "self"
                        or not isinstance(call.args[0], ast.Attribute)
                        or not isinstance(call.args[0].value, ast.Name)
                        or call.args[0].value.id != "self"
                    ):
                        continue
                    signal_name = call.func.value.attr.casefold()
                    if signal_name not in {
                        "complete",
                        "completed",
                        "error",
                        "exception",
                        "failed",
                        "failure",
                        "finished",
                        "result",
                        "succeeded",
                    }:
                        continue
                    worker_name = call.func.value.value.attr
                    terminal_handlers.setdefault(
                        call.args[0].attr,
                        set(),
                    ).add(worker_name)
                    if signal_name in {
                        "complete",
                        "completed",
                        "finished",
                        "result",
                        "succeeded",
                    }:
                        result_handler_names.add(call.args[0].attr)
                methods_by_name = {
                    method.name: method
                    for method in owner_node.body
                    if isinstance(
                        method,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                result_filter_attributes = {
                    str(attribute.get("name") or "")
                    for attribute in declaration_contract.get(
                        "attributes",
                    ) or []
                    if isinstance(attribute, Mapping)
                    and re.fullmatch(
                        r"include_[A-Za-z_][A-Za-z0-9_]*_checkbox",
                        str(attribute.get("name") or ""),
                    )
                }
                for handler_name in result_handler_names:
                    handler = methods_by_name.get(handler_name)
                    if handler is None:
                        continue
                    read_attributes = {
                        node.attr
                        for node in ast.walk(handler)
                        if isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                    }
                    missing_filters = sorted(
                        result_filter_attributes - read_attributes
                    )
                    for filter_name in missing_filters:
                        errors.append(
                            f"{path}:{owner}.{handler_name}: approved result "
                            f"filter `{filter_name}` must be read and applied "
                            "inside the result consumer."
                        )
            if (
                execution_constraints.get("requires_completion_path")
                and not has_completion_path
            ):
                errors.append(
                    f"{path}:{owner}: background execution has no connected "
                    "completion/result path back to the UI owner."
                )
            if (
                execution_constraints.get("requires_error_path")
                and not has_error_path
            ):
                errors.append(
                    f"{path}:{owner}: background execution has no connected "
                    "error/failure path back to the UI owner."
                )
            if execution_constraints.get("forbid_handler_loops"):
                connected_handler_names = {
                    argument.attr
                    for call in owner_calls
                    if isinstance(call.func, ast.Attribute)
                    and call.func.attr == "connect"
                    for argument in call.args[:1]
                    if isinstance(argument, ast.Attribute)
                    and isinstance(argument.value, ast.Name)
                    and argument.value.id == "self"
                }
                blocking_loop_calls = {
                    "join", "processEvents", "sleep", "wait",
                }
                looping_handlers = sorted({
                    node.name
                    for node in ast.walk(owner_node)
                    if isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef)
                    )
                    and node.name in connected_handler_names
                    and any(
                        isinstance(loop, ast.While)
                        or (
                            isinstance(loop, (ast.For, ast.AsyncFor))
                            and any(
                                isinstance(call, ast.Call)
                                and call_path(call).rsplit(".", 1)[-1]
                                in blocking_loop_calls
                                for call in ast.walk(loop)
                            )
                        )
                        for loop in ast.walk(node)
                    )
                })
                if looping_handlers:
                    errors.append(
                        f"{path}:{owner}: off-UI-thread contract forbids loops "
                        "inside connected UI handlers: "
                        + ", ".join(looping_handlers)
                        + "."
                    )
            background_method_names = {
                argument.attr
                for call in owner_calls
                if isinstance(call.func, ast.Name)
                and call.func.id in helper_names
                and call.args
                for argument in call.args[:1]
                if isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "self"
            }
            widget_names = {
                str(attribute.get("name") or "")
                for attribute in declaration_contract.get("attributes") or []
                if isinstance(attribute, Mapping)
                and str(attribute.get("name") or "")
                and (
                    str(attribute.get("type") or "").startswith("Q")
                    or str(attribute.get("name") or "").endswith(
                        (
                            "_btn",
                            "_button",
                            "_input",
                            "_label",
                            "_bar",
                            "_widget",
                            "_combo",
                            "_spinbox",
                        )
                    )
                )
            }
            methods_by_name = {
                node.name: node
                for node in ast.walk(owner_node)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for method_name in sorted(background_method_names):
                background_method = methods_by_name.get(method_name)
                if background_method is None:
                    continue
                ui_mutations = sorted({
                    expression_path(call.func)
                    for call in ast.walk(background_method)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and expression_path(call.func).split(".")[:2]
                    in [["self", widget_name] for widget_name in widget_names]
                })
                if ui_mutations:
                    errors.append(
                        f"{path}:{owner}.{method_name}: background worker "
                        "operation mutates UI-owned widgets outside the UI "
                        "thread: "
                        + ", ".join(ui_mutations)
                        + ". Return data and update widgets only in connected "
                        "completion/error handlers."
                    )
                swallowing_handlers = [
                    handler
                    for try_node in ast.walk(background_method)
                    if isinstance(try_node, ast.Try)
                    for handler in try_node.handlers
                    if not any(
                        isinstance(child, ast.Raise)
                        for child in ast.walk(handler)
                    )
                ]
                if swallowing_handlers:
                    errors.append(
                        f"{path}:{owner}.{method_name}: background worker "
                        "operation catches an exception without re-raising it; "
                        "the worker error boundary must receive failures."
                    )
    for path, tree in trees.items():
        forbidden_imports = forbidden_imports_by_path.get(path, set())
        if forbidden_imports:
            imported_paths: set[str] = set()
            for import_node in ast.walk(tree):
                if isinstance(import_node, ast.Import):
                    imported_paths.update(
                        alias.name.casefold() for alias in import_node.names
                    )
                elif (
                    isinstance(import_node, ast.ImportFrom)
                    and import_node.level == 0
                    and import_node.module
                ):
                    module = import_node.module.casefold()
                    imported_paths.add(module)
                    imported_paths.update(
                        f"{module}.{alias.name.casefold()}"
                        for alias in import_node.names
                    )
            violations = sorted({
                imported
                for imported in imported_paths
                if any(
                    imported == forbidden
                    or imported.startswith(forbidden + ".")
                    for forbidden in forbidden_imports
                )
            })
            if violations:
                constraint_text = " ".join(dict.fromkeys(
                    dependency_constraints_by_path.get(path, [])
                ))
                errors.append(
                    f"{path}:<module>: explicit request dependency policy "
                    "forbids direct imports "
                    + ", ".join(violations)
                    + (
                        f"; governing request constraint: {constraint_text}"
                        if constraint_text else ""
                    )
                    + ". Use only the approved dependency owner or transport."
                )
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and node.module.split(".", 1)[0]
                in getattr(sys, "stdlib_module_names", set())
            ):
                continue
            try:
                imported_module = importlib.import_module(node.module)
            except (ImportError, ModuleNotFoundError) as exc:
                errors.append(
                    f"{path}:<module>: standard-library module "
                    f"{node.module!r} could not be imported: {exc}"
                )
                continue
            for alias in node.names:
                public_exports = getattr(imported_module, "__all__", None)
                is_public_attribute = (
                    hasattr(imported_module, alias.name)
                    and (
                        public_exports is None
                        or alias.name in public_exports
                    )
                )
                if alias.name == "*" or is_public_attribute:
                    continue
                try:
                    child_spec = importlib.util.find_spec(
                        f"{node.module}.{alias.name}"
                    )
                except (ImportError, ModuleNotFoundError, ValueError):
                    child_spec = None
                if child_spec is None:
                    errors.append(
                        f"{path}:<module>: standard-library module "
                        f"{node.module!r} does not expose imported symbol "
                        f"{alias.name!r}; replace the invented import with a "
                        "verified public declaration or remove its usages."
                    )
    docstring_requirement_texts = [
        str(requirement.get("text") or "")
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        for requirement in chunk.get("requirements") or []
        if isinstance(requirement, Mapping)
        if "docstring" in str(requirement.get("text") or "").casefold()
    ]
    requires_complete_docstrings = True
    requires_explicit_return_fields = any(
        re.search(
            r":returns?\b|\breturns?\s+fields?\b",
            text,
            flags=re.IGNORECASE,
        )
        for text in docstring_requirement_texts
    )
    if requires_complete_docstrings:
        generic_docstring_pattern = re.compile(
            r"\bpreserving validated inputs, state transitions, and failure "
            r"behavior\b|\bafter validating construction inputs\b|"
            r"\bcontaining the validated inputs for this operation\b|"
            r"\bsupplied to this operation\b|"
            r"\bused by (?:the )?operation\b|"
            r"\bcoordinate .+ through .+ operations\b|"
            r"\bthe calculated [a-z_ ]+ value\b|"
            r"\bproduced after the operation completes successfully\b",
            flags=re.IGNORECASE,
        )

        def docstring_issues(name: str, node: ast.AST) -> list[str]:
            docstring = str(ast.get_docstring(node) or "").strip()
            issues: list[str] = []
            if isinstance(node, ast.ClassDef):
                fields = [
                    statement.target.id
                    for statement in node.body
                    if isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                ]
                for field in fields:
                    if not re.search(
                        rf":param\s+(?:[^:\s]+\s+)?{re.escape(field)}\s*:",
                        docstring,
                    ):
                        issues.append(f"is missing :param {field}:")
                return issues
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return issues
            parameters = [
                argument.arg
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
                if argument.arg not in {"self", "cls"}
            ]
            for parameter in parameters:
                if not re.search(
                    rf":param\s+(?:[^:\s]+\s+)?{re.escape(parameter)}\s*:",
                    docstring,
                ):
                    issues.append(f"is missing :param {parameter}:")
            returns_value = any(
                isinstance(child, (ast.Yield, ast.YieldFrom))
                or (
                    isinstance(child, ast.Return)
                    and child.value is not None
                    and not (
                        isinstance(child.value, ast.Constant)
                        and child.value.value is None
                    )
                )
                for statement in node.body
                for child in ast.walk(statement)
            )
            if (
                (returns_value or requires_explicit_return_fields)
                and not re.search(r":returns?\s*:", docstring)
            ):
                issues.append("is missing :return:")
            return issues

        for path, tree in trees.items():
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                    for issue in docstring_issues(node.name, node):
                        errors.append(
                            f"{path}:{node.name}: Requested useful docstrings are "
                            f"too vague: {node.name} {issue}"
                        )
                    for method in node.body:
                        if not (
                            isinstance(
                                method,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and (
                                not (
                                    method.name.startswith("__")
                                    and method.name.endswith("__")
                                )
                                or method.name == "__init__"
                            )
                        ):
                            continue
                        qualified = f"{node.name}.{method.name}"
                        for issue in docstring_issues(qualified, method):
                            errors.append(
                                f"{path}:{qualified}: Requested useful docstrings "
                                f"are too vague: {qualified} {issue}"
                            )
                elif isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and not node.name.startswith("_"):
                    for issue in docstring_issues(node.name, node):
                        errors.append(
                            f"{path}:{node.name}: Requested useful docstrings are "
                            f"too vague: {node.name} {issue}"
                        )
    for path, tree in trees.items():
        for function in [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            class LocalUsageVisitor(ast.NodeVisitor):
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
                    if any(
                        isinstance(target, ast.Name)
                        for target in node.targets
                    ):
                        self.assignments.append(node)
                    self.generic_visit(node)

                def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
                    if isinstance(node.target, ast.Name):
                        self.assignments.append(node)
                    self.generic_visit(node)

            usage = LocalUsageVisitor(function)
            usage.visit(function)
            for assignment in usage.assignments:
                targets = (
                    [
                        target.id
                        for target in assignment.targets
                        if isinstance(target, ast.Name)
                    ]
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target.id]
                )
                unused = [
                    name
                    for name in targets
                    if name not in usage.loads and not name.startswith("_")
                ]
                if unused:
                    errors.append(
                        f"{path}:{function.name}: unused local assignment(s) "
                        f"introduce dead code: {', '.join(unused)}."
                    )
            linear_assignments: dict[str, list[tuple[int, ast.AST]]] = {}
            for statement_index, statement in enumerate(function.body):
                if (
                    isinstance(statement, ast.Assign)
                    and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                ):
                    linear_assignments.setdefault(
                        statement.targets[0].id,
                        [],
                    ).append((statement_index, statement))
                elif (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.value is not None
                ):
                    linear_assignments.setdefault(
                        statement.target.id,
                        [],
                    ).append((statement_index, statement))
            for name, assignments in linear_assignments.items():
                for assignment_index in range(len(assignments) - 1):
                    statement_index, assignment = assignments[assignment_index]
                    next_statement_index, next_assignment = assignments[
                        assignment_index + 1
                    ]
                    used_before_overwrite = any(
                        isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Load)
                        and node.id == name
                        for statement in function.body[
                            statement_index + 1:next_statement_index
                        ]
                        for node in ast.walk(statement)
                    )
                    used_by_next_assignment = any(
                        isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Load)
                        and child.id == name
                        for child in ast.walk(
                            getattr(next_assignment, "value", None)
                        )
                    )
                    if (
                        not used_before_overwrite
                        and not used_by_next_assignment
                        and isinstance(
                            getattr(assignment, "value", None),
                            ast.Call,
                        )
                    ):
                        errors.append(
                            f"{path}:{function.name}: result assigned to {name} "
                            "is overwritten before use; preserve the call side "
                            "effect but discard its unused result."
                        )
            if (
                function.name.startswith("test_")
                or "self_test" in function.name.casefold()
            ):
                for try_node in [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Try)
                ]:
                    catches_asserted_exception = any(
                        handler.type is not None
                        and any(
                            isinstance(child, ast.Assert)
                            for child in ast.walk(handler)
                        )
                        for handler in try_node.handlers
                    )
                    if (
                        catches_asserted_exception
                        and not try_node.orelse
                        and any(
                            isinstance(child, ast.Call)
                            for statement in try_node.body
                            for child in ast.walk(statement)
                        )
                    ):
                        errors.append(
                            f"{path}:{function.name}: exception proof can pass "
                            "silently when the operation does not raise; add an "
                            "explicit failure path for the no-exception branch."
                        )
    for path, tree in trees.items():
        type_variable_declarations = {
            target.id: statement.value
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
        type_variables = set(type_variable_declarations)
        unrestricted_type_variables = {
            name
            for name, declaration in type_variable_declarations.items()
            if len(declaration.args) <= 1
            and not any(
                keyword.arg in {"bound", "constraints"}
                for keyword in declaration.keywords
            )
        }
        for class_node in [
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ]:
            class_docstring = str(ast.get_docstring(class_node) or "")
            class_text = ast.unparse(class_node)
            uses_synchronization = any(
                isinstance(node, (ast.With, ast.AsyncWith))
                and any(
                    any(
                        token in ast.unparse(item.context_expr).casefold()
                        for token in ("lock", "mutex", "semaphore", "condition")
                    )
                    for item in node.items
                )
                for node in ast.walk(class_node)
            ) or any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"acquire", "release"}
                for node in ast.walk(class_node)
            )
            if (
                re.search(r"\bthread[- ]safe\b", class_docstring, re.IGNORECASE)
                and not uses_synchronization
            ):
                errors.append(
                    f"{path}:{class_node.name}: documentation claims thread-safe "
                    "behavior without a proven synchronization boundary."
                )
            if re.search(r"\batomic\b", class_docstring, re.IGNORECASE) and not (
                uses_synchronization
                or ".replace(" in class_text
                or "os.replace(" in class_text
                or any(
                    token in class_text.casefold()
                    for token in ("transaction", "compare_and_swap")
                )
            ):
                errors.append(
                    f"{path}:{class_node.name}: documentation claims atomic "
                    "behavior without a proven lock, transaction, or atomic "
                    "replacement boundary."
                )
            used_type_variables = {
                node.id
                for node in ast.walk(class_node)
                if isinstance(node, ast.Name) and node.id in type_variables
            }
            generic_type_variables = {
                node.id
                for base in class_node.bases
                if isinstance(base, ast.Subscript)
                and isinstance(base.value, ast.Name)
                and base.value.id == "Generic"
                for node in ast.walk(base.slice)
                if isinstance(node, ast.Name)
            }
            missing_generic_owners = sorted(
                used_type_variables - generic_type_variables
            )
            if missing_generic_owners:
                errors.append(
                    f"{path}:{class_node.name}: class annotations use type "
                    f"variable(s) {', '.join(missing_generic_owners)} without "
                    "declaring their Generic ownership."
                )
            unrestricted_key_usages: set[tuple[str, str]] = set()
            for function in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                generic_parameters = {
                    argument.arg: argument.annotation.id
                    for argument in (
                        *function.args.posonlyargs,
                        *function.args.args,
                        *function.args.kwonlyargs,
                    )
                    if isinstance(argument.annotation, ast.Name)
                    and argument.annotation.id in unrestricted_type_variables
                }
                for subscript in [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "self"
                    and isinstance(node.slice, ast.Name)
                    and node.slice.id in generic_parameters
                    and isinstance(node.ctx, (ast.Store, ast.Del))
                ]:
                    unrestricted_key_usages.add(
                        (
                            subscript.slice.id,
                            generic_parameters[subscript.slice.id],
                        )
                    )
            if unrestricted_key_usages:
                errors.append(
                    f"{path}:{class_node.name}: unrestricted generic value(s) "
                    + ", ".join(
                        f"{parameter}:{type_variable}"
                        for parameter, type_variable
                        in sorted(unrestricted_key_usages)
                    )
                    + " are used as mapping keys; use an order-preserving entry "
                    "sequence or explicitly constrain the TypeVar to Hashable."
                )

            parent_by_id = {
                id(child): parent
                for parent in ast.walk(class_node)
                for child in ast.iter_child_nodes(parent)
            }
            initializer = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "__init__"
                ),
                None,
            )
            accumulating_attributes = {
                target.attr
                for assignment in (
                    ast.walk(initializer) if initializer is not None else []
                )
                if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                for target in (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                if isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and isinstance(
                    assignment.value,
                    (ast.List, ast.Dict, ast.Set),
                )
                and not (
                    getattr(assignment.value, "elts", None)
                    or getattr(assignment.value, "keys", None)
                )
            }
            for attribute_name in sorted(accumulating_attributes):
                has_growth = False
                has_reset = False
                length_reads = 0
                meaningful_reads = 0
                for attribute in [
                    node
                    for node in ast.walk(class_node)
                    if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and node.attr == attribute_name
                ]:
                    parent = parent_by_id.get(id(attribute))
                    grandparent = parent_by_id.get(id(parent)) if parent else None
                    if (
                        isinstance(parent, ast.Attribute)
                        and parent.value is attribute
                        and isinstance(grandparent, ast.Call)
                        and grandparent.func is parent
                    ):
                        if parent.attr in {"append", "add", "extend", "insert"}:
                            has_growth = True
                            continue
                        if parent.attr in {"clear"}:
                            has_reset = True
                            continue
                        if parent.attr in {"discard", "pop", "remove"}:
                            continue
                    if (
                        isinstance(parent, ast.Call)
                        and isinstance(parent.func, ast.Name)
                        and parent.func.id == "len"
                    ):
                        length_reads += 1
                        continue
                    if isinstance(attribute.ctx, ast.Load):
                        meaningful_reads += 1
                if (
                    has_growth
                    and length_reads
                    and not has_reset
                    and not meaningful_reads
                ):
                    errors.append(
                        f"{path}:{class_node.name}: self.{attribute_name} is an "
                        "unbounded write-only accumulator consumed only through "
                        "len(); use an explicit counter or expose/reset the "
                        "collection according to the contract."
                    )

            for function in [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]:
                for conditional in [
                    node
                    for node in ast.walk(function)
                    if isinstance(node, ast.If) and node.orelse
                ]:
                    if conditional.body and conditional.orelse:
                        body_tail = ast.dump(
                            conditional.body[-1],
                            include_attributes=False,
                        )
                        else_tail = ast.dump(
                            conditional.orelse[-1],
                            include_attributes=False,
                        )
                        if body_tail == else_tail:
                            errors.append(
                                f"{path}:{class_node.name}.{function.name}: "
                                "conditional branches duplicate the same trailing "
                                "statement; factor it once after the branch."
                            )
                    if conditional.body and isinstance(
                        conditional.body[-1],
                        (ast.Return, ast.Raise),
                    ):
                        errors.append(
                            f"{path}:{class_node.name}.{function.name}: uses an "
                            "unnecessary else branch after a terminating return or "
                            "raise."
                        )

    entrypoint_paths = {
        str(Path(str(chunk.get("path") or "")).resolve())
        for chunk in implementation_plan.get("chunks") or []
        if isinstance(chunk, Mapping)
        and (
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
        )
    }
    class_methods_by_path: dict[str, set[str]] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or str(chunk.get("kind") or "") != "class":
            continue
        resolved_path = str(Path(str(chunk.get("path") or "")).resolve())
        class_methods_by_path.setdefault(resolved_path, set()).update(
            str(value)
            for value in (
                chunk.get("declaration_contract") or {}
            ).get("required_methods") or []
            if str(value) and not str(value).startswith("__")
        )
    for path, tree in trees.items():
        has_main_guard = any(
            isinstance(node, ast.If)
            and "__name__" in ast.unparse(node.test)
            and "__main__" in ast.unparse(node.test)
            for node in tree.body
        )
        if (
            has_main_guard
            and path not in entrypoint_paths
            and not Path(path).name.startswith("test_")
        ):
            errors.append(
                f"{path}:<module>: unrequested standalone entry point is present."
            )
        if (
            path in entrypoint_paths
            and not has_main_guard
            and not Path(path).name.startswith("test_")
        ):
            errors.append(
                f"{path}:<module>: approved runnable entry point is missing."
            )
        duplicate_method_functions = sorted(
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in class_methods_by_path.get(path, set())
        )
        if duplicate_method_functions:
            errors.append(
                f"{path}:<module>: class-owned methods were duplicated as "
                "top-level functions: " + ", ".join(duplicate_method_functions)
            )
        if not Path(path).name.startswith("test_"):
            for node in tree.body:
                if isinstance(
                    node,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                ) and node.name.startswith("test_"):
                    errors.append(
                        f"{path}:<module>: test declaration `{node.name}` is "
                        "unrequested in a production module."
                    )

    approved_surfaces: dict[str, set[str]] = {}
    approved_member_types: dict[str, dict[str, str]] = {}
    approved_constructor_types: dict[str, str] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or str(chunk.get("kind") or "") != "class":
            continue
        contract = chunk.get("declaration_contract") or {}
        allowed = {
            match.group(1)
            for signature in contract.get("callable_signatures") or []
            for match in [
                re.search(
                    r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                    str(signature),
                )
            ]
            if match
        }
        allowed.update(
            str(value) for value in contract.get("required_methods") or []
        )
        allowed.update(
            str(item.get("name") or "")
            for item in contract.get("attributes") or []
            if isinstance(item, Mapping)
        )
        allowed.update(
            str(item.get("name") or "")
            if isinstance(item, Mapping)
            else str(item)
            for item in contract.get("properties") or []
        )
        approved_surfaces[str(chunk.get("owner") or "")] = {
            value for value in allowed if value
        }
        approved_member_types[str(chunk.get("owner") or "")] = {
            str(item.get("name") or ""): str(
                item.get("return_type")
                or item.get("type")
                or item.get("annotation")
                or ""
            )
            for item in contract.get("properties") or []
            if isinstance(item, Mapping)
            and str(item.get("name") or "")
        }

    # The declaration contract can omit a property's return type even though the
    # generated declaration contains it. Overlay generated annotations so
    # verification code can be checked against the code it will actually run.
    for tree in trees.values():
        for class_node in [
            item for item in tree.body if isinstance(item, ast.ClassDef)
        ]:
            if class_node.name not in approved_surfaces:
                continue
            for member in class_node.body:
                if not isinstance(
                    member,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ):
                    continue
                if member.name == "__init__":
                    constructor_arguments = [
                        argument
                        for argument in (
                            *member.args.posonlyargs,
                            *member.args.args,
                        )
                        if argument.arg not in {"self", "cls"}
                    ]
                    if (
                        constructor_arguments
                        and constructor_arguments[0].annotation is not None
                    ):
                        approved_constructor_types[class_node.name] = (
                            ast.unparse(constructor_arguments[0].annotation)
                        )
                if not any(
                    (
                        isinstance(decorator, ast.Name)
                        and decorator.id == "property"
                    )
                    or (
                        isinstance(decorator, ast.Attribute)
                        and decorator.attr == "property"
                    )
                    for decorator in member.decorator_list
                ):
                    continue
                if member.returns is not None:
                    approved_member_types.setdefault(
                        class_node.name,
                        {},
                    )[member.name] = ast.unparse(member.returns)

    builtin_verification_types = {
        value.__name__: value
        for value in (
            bool,
            bytes,
            bytearray,
            complex,
            dict,
            float,
            frozenset,
            int,
            list,
            memoryview,
            range,
            set,
            str,
            tuple,
        )
    }

    def verification_owner_for(
        path: str,
        tree: ast.Module,
        lineno: int,
        verification_ranges: list[tuple[str, int, int]],
        is_test_module: bool,
    ) -> str:
        verification_owner = next(
            (
                owner
                for owner, start, end in verification_ranges
                if start <= lineno <= end
            ),
            "",
        )
        if not is_test_module:
            return verification_owner
        if verification_owner:
            return verification_owner
        for item in ast.walk(tree):
            if not isinstance(
                item,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            if int(item.lineno) <= lineno <= int(
                item.end_lineno or item.lineno
            ):
                return item.name
        return "<module>"

    verification_owners_by_path: dict[str, list[tuple[str, int, int]]] = {}
    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping) or not any(
            isinstance(requirement, Mapping)
            and str(requirement.get("semantic_role") or "") == "verification"
            for requirement in chunk.get("requirements") or []
        ):
            continue
        verification_path = str(
            Path(str(chunk.get("path") or "")).resolve()
        )
        verification_tree = trees.get(verification_path)
        if verification_tree is None:
            continue
        verification_node = _definition_nodes(verification_tree).get(
            str(chunk.get("owner") or "")
        )
        if isinstance(
            verification_node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            verification_owners_by_path.setdefault(
                verification_path,
                [],
            ).append((
                verification_node.name,
                int(verification_node.lineno),
                int(verification_node.end_lineno or verification_node.lineno),
            ))

    for path, tree in trees.items():
        is_test_module = Path(path).name.startswith("test_")
        verification_ranges = verification_owners_by_path.get(path, [])
        if not is_test_module and not verification_ranges:
            continue
        instance_types: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in approved_surfaces
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    instance_types[target.id] = value.func.id
                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    instance_types[f"self.{target.attr}"] = value.func.id
        for call in [
            node for node in ast.walk(tree) if isinstance(node, ast.Call)
        ]:
            if not (
                isinstance(call.func, ast.Name)
                and call.func.id in approved_constructor_types
                and call.args
                and isinstance(call.args[0], ast.Attribute)
            ):
                continue
            argument = call.args[0]
            argument_receiver = ""
            if isinstance(argument.value, ast.Name):
                argument_receiver = argument.value.id
            elif (
                isinstance(argument.value, ast.Attribute)
                and isinstance(argument.value.value, ast.Name)
                and argument.value.value.id == "self"
            ):
                argument_receiver = f"self.{argument.value.attr}"
            argument_class = instance_types.get(argument_receiver)
            argument_annotation = approved_member_types.get(
                argument_class or "",
                {},
            ).get(argument.attr, "")
            actual_root_match = re.match(
                r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
                r"([A-Za-z_][A-Za-z0-9_]*)",
                argument_annotation.strip(),
            )
            expected_annotation = approved_constructor_types[call.func.id]
            expected_root_match = re.match(
                r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
                r"([A-Za-z_][A-Za-z0-9_]*)",
                expected_annotation.strip(),
            )
            actual_root = (
                actual_root_match.group(1).casefold()
                if actual_root_match is not None
                else ""
            )
            expected_root = (
                expected_root_match.group(1).casefold()
                if expected_root_match is not None
                else ""
            )
            actual_type = builtin_verification_types.get(actual_root)
            expected_type = builtin_verification_types.get(expected_root)
            compatible = True
            if actual_type is not None and expected_type is not None:
                compatible = issubclass(actual_type, expected_type)
            elif (
                actual_type is not None
                and expected_root in {"mapping", "mutablemapping"}
            ):
                compatible = all(
                    member in dir(actual_type)
                    for member in ("items", "keys", "values")
                )
            if compatible:
                continue
            test_owner = verification_owner_for(
                path,
                tree,
                int(call.lineno),
                verification_ranges,
                is_test_module,
            )
            if not is_test_module and not test_owner:
                continue
            errors.append(
                f"{path}:{test_owner}: verification call "
                f"`{ast.unparse(call)}` passes `{argument_class}.{argument.attr}` "
                f"with generated type `{argument_annotation}` to "
                f"`{call.func.id}` constructor parameter "
                f"`{expected_annotation}`. Repair only this verification callable "
                "with a type-compatible public value; do not broaden or rewrite "
                "the valid production constructor."
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            receiver = ""
            if isinstance(node.value, ast.Name):
                receiver = node.value.id
            elif (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
            ):
                receiver = f"self.{node.value.attr}"
            class_name = instance_types.get(receiver)
            if (
                class_name
                and node.attr not in approved_surfaces[class_name]
                and not node.attr.startswith("__")
            ):
                verification_owner = next(
                    (
                        owner
                        for owner, start, end in verification_ranges
                        if start <= int(node.lineno) <= end
                    ),
                    "",
                )
                if not is_test_module and not verification_owner:
                    continue
                test_owner = "<module>"
                if verification_owner:
                    test_owner = verification_owner
                else:
                    for class_node in [
                        item for item in tree.body if isinstance(item, ast.ClassDef)
                    ]:
                        for method_node in [
                            item
                            for item in class_node.body
                            if isinstance(
                                item,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                        ]:
                            if (
                                int(method_node.lineno) <= int(node.lineno)
                                <= int(method_node.end_lineno or method_node.lineno)
                            ):
                                test_owner = (
                                    f"{class_node.name}.{method_node.name}"
                                )
                errors.append(
                    f"{path}:{test_owner}: verification code accesses unapproved `{class_name}."
                    f"{node.attr}`; use only the approved public contract. Trigger UI "
                    "behavior through approved widget attributes (for example, a "
                    "button's click() method), and assert state only through approved "
                    "dependency query methods; never call dialog slots directly or "
                    "inspect production storage. The exact approved surface for "
                    f"`{class_name}` is: "
                    + ", ".join(sorted(approved_surfaces[class_name]))
                    + "."
                )
                continue

            # Validate chained members through an approved property's concrete
            # built-in return type. For example, if `items` is annotated as a
            # tuple, verification code may use tuple members but cannot invent a
            # list-only member. This is derived from annotations and Python's
            # actual runtime surface rather than from request-specific names.
            if not isinstance(node.value, ast.Attribute):
                continue
            property_access = node.value
            property_receiver = ""
            if isinstance(property_access.value, ast.Name):
                property_receiver = property_access.value.id
            elif (
                isinstance(property_access.value, ast.Attribute)
                and isinstance(property_access.value.value, ast.Name)
                and property_access.value.value.id == "self"
            ):
                property_receiver = f"self.{property_access.value.attr}"
            property_class = instance_types.get(property_receiver)
            property_annotation = approved_member_types.get(
                property_class or "",
                {},
            ).get(property_access.attr, "")
            annotation_root_match = re.match(
                r"(?:[A-Za-z_][A-Za-z0-9_]*\.)*"
                r"([A-Za-z_][A-Za-z0-9_]*)",
                property_annotation.strip(),
            )
            annotation_root = (
                annotation_root_match.group(1)
                if annotation_root_match is not None
                else ""
            )
            runtime_type = builtin_verification_types.get(
                annotation_root.casefold()
            )
            if runtime_type is None or node.attr in dir(runtime_type):
                continue
            test_owner = verification_owner_for(
                path,
                tree,
                int(node.lineno),
                verification_ranges,
                is_test_module,
            )
            if not is_test_module and not test_owner:
                continue
            errors.append(
                f"{path}:{test_owner}: verification expression "
                f"`{ast.unparse(node)}` accesses invalid member `{node.attr}` "
                f"on `{property_class}.{property_access.attr}`, whose generated "
                f"return annotation resolves to built-in `{runtime_type.__name__}`. "
                "Repair only this verification callable and use a member supported "
                "by the resolved runtime type; do not change the valid production "
                "declaration."
            )

    for chunk in implementation_plan.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        path = str(Path(str(chunk.get("path") or "")).resolve())
        owner = str(chunk.get("owner") or "")
        kind = str(chunk.get("kind") or "")
        contract = chunk.get("declaration_contract") or {}
        tree = trees.get(path)
        if tree is None:
            continue
        definitions = _definition_nodes(tree)
        if owner == "<module>":
            owner_node: ast.AST = tree
        else:
            owner_node = definitions.get(owner)  # type: ignore[assignment]
            if owner_node is None:
                errors.append(
                    f"{path}:{owner}: approved declaration is missing."
                )
                continue
        verification_clauses = [
            match.group(1).strip().rstrip(".")
            for validation_case in chunk.get("validation_cases") or []
            if isinstance(validation_case, Mapping)
            for check in validation_case.get("checks") or []
            for match in [
                re.search(
                    r"exact observable clause:\s*(.+)$",
                    str(check),
                    flags=re.IGNORECASE,
                )
            ]
            if match is not None
        ]
        if (
            verification_clauses
            and isinstance(owner_node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            missing_proofs = _verification_proof_gaps(
                owner_node,
                verification_clauses,
            )
            if missing_proofs:
                errors.append(
                    f"{path}:{owner}: requested verification callable does not "
                    "independently prove clause(s): "
                    + ", ".join(missing_proofs)
                    + ". Repair only this callable with explicit setup, action, "
                    "assertion, and exception evidence for every listed clause."
                )
        if isinstance(owner_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for discarded_gap in _discarded_pure_transform_gaps(owner_node):
                errors.append(
                    f"{path}:{owner}: discarded pure transform introduces dead "
                    f"behavior: {discarded_gap}. Assign and consume the returned "
                    "value inside this callable."
                )
            for guard_gap in _final_value_guard_gaps(owner_node):
                errors.append(
                    f"{path}:{owner}: final-result validation order is unsafe: "
                    f"{guard_gap} Repair only this callable."
                )
            owned_requirement_text = " ".join(
                str(requirement.get("text") or "")
                for requirement in chunk.get("requirements") or []
                if isinstance(requirement, Mapping)
            )
            for regex_gap in _regex_requirement_gaps(
                owner_node,
                owned_requirement_text,
            ):
                errors.append(
                    f"{path}:{owner}: approved regex behavior is not implemented: "
                    f"{regex_gap}. Repair only this callable."
                )
            for trim_gap in _boundary_trim_requirement_gaps(
                owner_node,
                owned_requirement_text,
            ):
                errors.append(
                    f"{path}:{owner}: approved boundary normalization is not "
                    f"implemented: {trim_gap}. Repair only this callable."
                )
        if kind == "class" and isinstance(owner_node, ast.ClassDef):
            bases = {
                ast.unparse(base).rsplit(".", 1)[-1]
                for base in owner_node.bases
            }
            required_base = str(contract.get("base") or "")
            if required_base and required_base.rsplit(".", 1)[-1] not in bases:
                errors.append(
                    f"{path}:{owner}: approved base `{required_base}` is missing."
                )
            if required_base:
                required_base_name = required_base.rsplit(".", 1)[-1]
                module_bindings = {
                    node.name
                    for node in tree.body
                    if isinstance(
                        node,
                        (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
                    )
                }
                module_bindings.update(
                    alias.asname or alias.name.split(".", 1)[0]
                    for node in tree.body
                    if isinstance(node, ast.Import)
                    for alias in node.names
                )
                module_bindings.update(
                    alias.asname or alias.name
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names
                )
                if (
                    required_base_name not in {
                        "BaseException", "Exception", "object",
                    }
                    and required_base_name not in module_bindings
                ):
                    errors.append(
                        f"{path}:{owner}: approved base `{required_base_name}` "
                        "is referenced but neither imported nor defined."
                    )
            if required_base:
                unapproved_bases = sorted(
                    base
                    for base in bases
                    if base != required_base.rsplit(".", 1)[-1]
                )
                if unapproved_bases:
                    errors.append(
                        f"{path}:{owner}: unapproved base classes are present: "
                        + ", ".join(unapproved_bases)
                        + f". The approved base is `{required_base}`."
                    )
                required_base_name = required_base.rsplit(".", 1)[-1]
                base_excerpt = next(
                    (
                        str(item.get("source_excerpt") or "")
                        for item in chunk.get("evidence") or []
                        if isinstance(item, Mapping)
                        and str(item.get("name") or "").rsplit(".", 1)[-1]
                        == required_base_name
                        and str(item.get("source_excerpt") or "").strip()
                    ),
                    "",
                )
                required_constructor_parameters: list[str] = []
                if base_excerpt:
                    try:
                        base_tree = ast.parse(base_excerpt)
                    except SyntaxError:
                        base_tree = None
                    base_class = next(
                        (
                            node
                            for node in (base_tree.body if base_tree else [])
                            if isinstance(node, ast.ClassDef)
                            and node.name == required_base_name
                        ),
                        None,
                    )
                    base_init = next(
                        (
                            node
                            for node in (base_class.body if base_class else [])
                            if isinstance(
                                node,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and node.name == "__init__"
                        ),
                        None,
                    )
                    if base_init is not None:
                        positional = [
                            *base_init.args.posonlyargs,
                            *base_init.args.args,
                        ]
                        if positional and positional[0].arg in {"self", "cls"}:
                            positional = positional[1:]
                        required_count = max(
                            0,
                            len(positional) - len(base_init.args.defaults),
                        )
                        required_constructor_parameters = [
                            argument.arg
                            for argument in positional[:required_count]
                        ]
                if required_constructor_parameters:
                    class_init = _method_map(owner_node).get("__init__")
                    super_init_call = next(
                        (
                            call
                            for call in ast.walk(class_init)
                            if isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "__init__"
                            and isinstance(call.func.value, ast.Call)
                            and isinstance(call.func.value.func, ast.Name)
                            and call.func.value.func.id == "super"
                        ),
                        None,
                    ) if class_init is not None else None
                    supplied_keywords = {
                        str(keyword.arg)
                        for keyword in (super_init_call.keywords if super_init_call else [])
                        if keyword.arg
                    }
                    supplied_required = len(
                        super_init_call.args if super_init_call else []
                    ) + sum(
                        parameter in supplied_keywords
                        for parameter in required_constructor_parameters
                    )
                    if supplied_required < len(required_constructor_parameters):
                        errors.append(
                            f"{path}:{owner}.__init__: verified base "
                            f"`{required_base_name}` requires constructor values "
                            "for "
                            + ", ".join(required_constructor_parameters)
                            + "; the generated super().__init__ call does not "
                            "supply them."
                        )
            decorators = {
                ast.unparse(
                    decorator.func
                    if isinstance(decorator, ast.Call)
                    else decorator
                ).rsplit(".", 1)[-1]
                for decorator in owner_node.decorator_list
            }
            for decorator in contract.get("decorators") or []:
                if str(decorator).rsplit(".", 1)[-1] not in decorators:
                    errors.append(
                        f"{path}:{owner}: approved decorator `@{decorator}` is missing."
                    )
            methods = _method_map(owner_node)
            for method_name in contract.get("required_methods") or []:
                if str(method_name) not in methods:
                    errors.append(
                        f"{path}:{owner}: approved method `{method_name}` is missing."
                    )
            for property_name in contract.get("properties") or []:
                property_method = methods.get(str(property_name))
                property_decorators = {
                    ast.unparse(decorator).rsplit(".", 1)[-1]
                    for decorator in (
                        property_method.decorator_list
                        if property_method is not None
                        else []
                    )
                }
                if property_method is None:
                    continue
                if "property" not in property_decorators:
                    errors.append(
                        f"{path}:{owner}.{property_name}: approved property "
                        "must be implemented with `@property`."
                    )
            approved_fields = {
                str(field.get("name") or ""): str(field.get("type") or "")
                for field in contract.get("fields") or []
                if isinstance(field, Mapping) and str(field.get("name") or "")
            }
            actual_fields = {
                node.target.id: ast.unparse(node.annotation)
                for node in owner_node.body
                if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
            }
            for field_name, field_type in approved_fields.items():
                if field_name not in actual_fields:
                    errors.append(
                        f"{path}:{owner}: approved typed field `{field_name}: "
                        f"{field_type}` is missing."
                    )
            frozen_dataclass = any(
                isinstance(decorator, ast.Call)
                and ast.unparse(decorator.func).rsplit(".", 1)[-1] == "dataclass"
                and any(
                    keyword.arg == "frozen"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in decorator.keywords
                )
                for decorator in owner_node.decorator_list
            )
            if bool(contract.get("immutable")) and not frozen_dataclass:
                errors.append(
                    f"{path}:{owner}: immutable dataclass must use "
                    "`@dataclass(frozen=True)`."
                )
            if frozen_dataclass and any(
                isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                and any(
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id == "self"
                    and isinstance(child.ctx, ast.Store)
                    for child in ast.walk(node)
                )
                for method in methods.values()
                for node in ast.walk(method)
            ):
                errors.append(
                    f"{path}:{owner}: frozen dataclass mutates `self` directly."
                )
            if bool(contract.get("public_surface_locked")):
                approved_public_methods = {
                    str(method_name)
                    for method_name in contract.get("required_methods") or []
                    if str(method_name)
                    and not str(method_name).startswith("_")
                }
                approved_public_methods.update(
                    match.group(1)
                    for signature in contract.get("callable_signatures") or []
                    for match in [
                        re.match(
                            r"(?:async\s+)?def\s+"
                            r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
                            str(signature).strip(),
                        )
                    ]
                    if match and not match.group(1).startswith("_")
                )
                approved_public_methods.add("__init__")
                undeclared_public_methods = sorted(
                    method_name
                    for method_name in methods
                    if not method_name.startswith("_")
                    and method_name not in approved_public_methods
                )
                if undeclared_public_methods:
                    errors.append(
                        f"{path}:{owner}: undeclared public callable(s) are "
                        "forbidden by the locked class contract: "
                        + ", ".join(undeclared_public_methods)
                        + ". Dependency callables must be invoked through their "
                        "declaring owner, not copied onto the consumer."
                    )
            reachable_methods = {"__init__"} if "__init__" in methods else set()
            pending_reachable = list(reachable_methods)
            while pending_reachable:
                method_name = pending_reachable.pop()
                method_node = methods.get(method_name)
                if method_node is None:
                    continue
                for call in ast.walk(method_node):
                    connected_handler = (
                        call.args[0].attr
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and call.func.attr == "connect"
                            and call.args
                            and isinstance(call.args[0], ast.Attribute)
                            and isinstance(call.args[0].value, ast.Name)
                            and call.args[0].value.id == "self"
                            and call.args[0].attr in methods
                        )
                        else ""
                    )
                    if (
                        connected_handler
                        and connected_handler not in reachable_methods
                    ):
                        reachable_methods.add(connected_handler)
                        pending_reachable.append(connected_handler)
                    if (
                        isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                        and call.func.attr in methods
                        and call.func.attr not in reachable_methods
                    ):
                        reachable_methods.add(call.func.attr)
                        pending_reachable.append(call.func.attr)
            is_ui_owner = bool(
                owner.endswith(
                    ("Dialog", "Window", "Widget", "Panel", "Dock")
                )
                or any(
                    token in str(contract.get("base") or "")
                    for token in ("Dialog", "Window", "Widget", "Qt")
                )
            )
            required_behavior_handlers = {
                str(task.get("name") or "")
                for task in chunk.get("method_tasks") or []
                if isinstance(task, Mapping)
                and str(task.get("name") or "") not in {"", "__init__"}
                and bool(task.get("requirement_ids"))
            } if is_ui_owner else set()
            for handler_name in sorted(
                required_behavior_handlers - reachable_methods
            ):
                errors.append(
                    f"{path}:{owner}.{handler_name}: requirement-owning UI "
                    "handler is unreachable; connect it from construction or "
                    "call it through a constructor-reachable method."
                )
            unresolved_private_calls = {
                call.func.attr
                for method in methods.values()
                for call in ast.walk(method)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
                and call.func.attr.startswith("_")
                and call.func.attr not in methods
            }
            for method_name in sorted(unresolved_private_calls):
                errors.append(
                    f"{path}:{owner}: call to unresolved private method "
                    f"`self.{method_name}()`."
                )
            for task in chunk.get("method_tasks") or []:
                if not isinstance(task, Mapping):
                    continue
                method_name = str(task.get("name") or "")
                method_node = methods.get(method_name)
                task_contract = " ".join(
                    str(value)
                    for value in [
                        *task.get("implementation_mechanics", []),
                        *task.get("validation_cases", []),
                    ]
                )
                if (
                    method_node is not None
                    and re.search(
                        r"\b(?:visible|observable)\s+(?:error|failure)\s+path\b"
                        r"|\bsurface\s+(?:errors?|failures?)\b",
                        task_contract,
                        flags=re.IGNORECASE,
                    )
                    and not any(
                        isinstance(node, ast.Try)
                        and bool(node.handlers)
                        for node in ast.walk(method_node)
                    )
                ):
                    errors.append(
                        f"{path}:{owner}.{method_name}: approved visible error "
                        "path has no executable exception handler."
                    )
            reachable_nodes = [
                methods[name]
                for name in reachable_methods
                if name in methods
            ]
            attached_widget_attributes = {
                argument.attr
                for call in ast.walk(owner_node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in {
                    "addWidget",
                    "insertWidget",
                    "setCentralWidget",
                    "setWidget",
                }
                for argument in call.args[:1]
                if isinstance(argument, ast.Attribute)
                and isinstance(argument.value, ast.Name)
                and argument.value.id == "self"
            }
            owner_has_layout = any(
                isinstance(call, ast.Call)
                and (
                    (
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr in {
                            "setLayout",
                            "setCentralWidget",
                            "setWidget",
                        }
                    )
                    or (
                        ast.unparse(call.func).rsplit(".", 1)[-1].startswith("Q")
                        and ast.unparse(call.func).rsplit(".", 1)[-1].endswith(
                            "Layout"
                        )
                        and bool(call.args)
                    )
                )
                for call in ast.walk(owner_node)
            )
            for attribute in contract.get("attributes") or []:
                if not isinstance(attribute, Mapping):
                    continue
                attribute_name = str(attribute.get("name") or "")
                expected_type = str(attribute.get("type") or "").rsplit(".", 1)[-1]
                if not attribute_name:
                    continue
                for method_name, method_node in methods.items():
                    if method_name == "__init__":
                        continue
                    misplaced_construction = any(
                        isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        and any(
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == attribute_name
                            for target in (
                                assignment.targets
                                if isinstance(assignment, ast.Assign)
                                else [assignment.target]
                            )
                        )
                        and isinstance(assignment.value, ast.Call)
                        for assignment in ast.walk(method_node)
                    )
                    if misplaced_construction:
                        errors.append(
                            f"{path}:{owner}.{method_name}: approved UI attribute "
                            f"`{attribute_name}` is reconstructed outside "
                            "`__init__`; consume the existing widget instead."
                        )
                constructed = False
                for method_node in reachable_nodes:
                    for assignment in ast.walk(method_node):
                        value: ast.AST | None = None
                        targets: list[ast.AST] = []
                        if isinstance(assignment, ast.Assign):
                            value = assignment.value
                            targets = list(assignment.targets)
                        elif isinstance(assignment, ast.AnnAssign):
                            value = assignment.value
                            targets = [assignment.target]
                        if value is None or not any(
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == attribute_name
                            for target in targets
                        ):
                            continue
                        if not expected_type:
                            constructed = True
                            break
                        if isinstance(value, ast.Call) and (
                            (
                                expected_type == "QWidget"
                                and ast.unparse(value.func).rsplit(
                                    ".", 1
                                )[-1].startswith("Q")
                            )
                            or (
                                ast.unparse(value.func).rsplit(".", 1)[-1]
                                == expected_type
                            )
                        ):
                            constructed = True
                            break
                    if constructed:
                        break
                if bool(attribute.get("construction_required")) and not constructed:
                    errors.append(
                        f"{path}:{owner}: approved attribute `{attribute_name}` "
                        + (
                            f"must be constructed as `{expected_type}` "
                            if expected_type
                            else "must be initialized "
                        )
                        + "from `__init__` or a constructor-reachable helper."
                    )
                meaningful_widget_members = {
                    "QCheckBox": {
                        "checkState", "clicked", "isChecked", "stateChanged",
                        "toggled",
                    },
                    "QComboBox": {
                        "activated", "currentData", "currentIndex",
                        "currentIndexChanged", "currentText",
                        "currentTextChanged",
                    },
                    "QLabel": {"clear", "setPixmap", "setText", "text"},
                    "QLineEdit": {
                        "clear", "editingFinished", "setText", "text",
                        "textChanged",
                    },
                    "QListWidget": {
                        "addItem", "addItems", "clear", "currentItem",
                        "itemSelectionChanged", "selectedItems",
                    },
                    "QProgressBar": {
                        "reset", "setMaximum", "setMinimum", "setRange",
                        "setValue", "value", "valueChanged",
                    },
                    "QPushButton": {"click", "clicked", "setEnabled"},
                    "QSpinBox": {
                        "setRange", "setValue", "value", "valueChanged",
                    },
                    "QTextEdit": {
                        "append", "clear", "setPlainText", "textChanged",
                        "toPlainText",
                    },
                }
                attribute_use_members = {
                    candidate.attr
                    for candidate in ast.walk(owner_node)
                    if isinstance(candidate, ast.Attribute)
                    and expression_path(candidate).startswith(
                        f"self.{attribute_name}."
                    )
                }
                meaningful_runtime_use = bool(
                    attribute_use_members
                    & meaningful_widget_members.get(expected_type, set())
                )
                if not expected_type.startswith("Q"):
                    meaningful_runtime_use = any(
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        and node.attr == attribute_name
                        and isinstance(node.ctx, ast.Load)
                        for method in _method_map(owner_node).values()
                        if method.name != "__init__"
                        for node in ast.walk(method)
                    )
                if (
                    bool(attribute.get("runtime_use_required"))
                    and not meaningful_runtime_use
                ):
                    errors.append(
                        f"{path}:{owner}: approved attribute `{attribute_name}` "
                        "is constructed but has no meaningful runtime read, signal "
                        "wiring, or state update."
                    )
                if (
                    bool(attribute.get("construction_required"))
                    and expected_type.startswith("Q")
                    and expected_type not in {
                        "QAction",
                        "QButtonGroup",
                        "QLayout",
                        "QMenu",
                        "QShortcut",
                        "QTimer",
                    }
                    and (
                        attribute_name not in attached_widget_attributes
                        or not owner_has_layout
                    )
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        f"approved UI control `{attribute_name}` is constructed "
                        "but not attached to a constructor-reachable layout or "
                        "container, so the user cannot interact with it."
                    )
                selection_semantics = bool(
                    expected_type == "QComboBox"
                    and re.search(
                        r"\b(?:select|selection|choice|choose|mode|category)\b",
                        attribute_name.replace("_", " "),
                        flags=re.IGNORECASE,
                    )
                )
                if selection_semantics and not any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {
                        "currentData",
                        "currentIndex",
                        "currentText",
                    }
                    and isinstance(call.func.value, ast.Attribute)
                    and isinstance(call.func.value.value, ast.Name)
                    and call.func.value.value.id == "self"
                    and call.func.value.attr == attribute_name
                    for call in ast.walk(owner_node)
                ):
                    errors.append(
                        f"[owner:{owner}] [repair-scope:class] {path}:{owner}: "
                        f"selection control `{attribute_name}` never reads its "
                        "current selection through currentText(), currentData(), "
                        "or currentIndex()."
                    )
            for signature in contract.get("callable_signatures") or []:
                match = re.match(
                    r"def\s+([A-Za-z_][A-Za-z0-9_]*)\((.*)\)",
                    str(signature),
                )
                if not match:
                    continue
                method = methods.get(match.group(1))
                if method is None:
                    if (
                        match.group(1) == "__init__"
                        and "dataclass" in decorators
                    ):
                        continue
                    if (
                        match.group(1) == "__init__"
                        and re.fullmatch(
                            r"def\s+__init__\(\s*self\s*\)",
                            str(signature).strip(),
                        )
                    ):
                        continue
                    errors.append(
                        f"{path}:{owner}: approved callable `{match.group(1)}` is missing."
                    )
                    continue
                try:
                    signature_tree = ast.parse(
                        str(signature).rstrip() + ":\n    pass",
                        filename="<approved-signature>",
                    )
                    signature_node = signature_tree.body[0]
                    if not isinstance(
                        signature_node,
                        (ast.FunctionDef, ast.AsyncFunctionDef),
                    ):
                        raise SyntaxError("approved signature is not callable")
                    expected_parameters = [
                        argument.arg
                        for argument in [
                            *signature_node.args.posonlyargs,
                            *signature_node.args.args,
                            *signature_node.args.kwonlyargs,
                        ]
                    ]
                except SyntaxError:
                    expected_parameters = [
                        value.split(":", 1)[0].split("=", 1)[0].strip()
                        for value in match.group(2).split(",")
                        if value.strip()
                    ]
                actual_parameters = [
                    argument.arg
                    for argument in [
                        *method.args.posonlyargs,
                        *method.args.args,
                        *method.args.kwonlyargs,
                    ]
                ]
                requirement_text = " ".join(
                    str(requirement.get("text") or "")
                    for requirement in chunk.get("requirements") or []
                    if isinstance(requirement, Mapping)
                )
                parameter_names_are_explicit = bool(
                    re.search(
                        rf"(?<![A-Za-z0-9_.]){re.escape(method.name)}\s*"
                        r"\([^)]*\)",
                        requirement_text,
                    )
                )
                parameter_contract_failed = (
                    expected_parameters
                    != actual_parameters[:len(expected_parameters)]
                    if parameter_names_are_explicit
                    else len(actual_parameters) < len(expected_parameters)
                )
                if parameter_contract_failed:
                    errors.append(
                        f"{path}:{owner}.{method.name}: "
                        + (
                            "explicitly requested parameters "
                            f"{expected_parameters} do not match "
                            f"{actual_parameters}."
                            if parameter_names_are_explicit
                            else "inferred interface requires at least "
                            f"{len(expected_parameters)} parameters but found "
                            f"{len(actual_parameters)}."
                        )
                    )
                expected_return_match = re.search(
                    r"\)\s*->\s*(.+)$", str(signature)
                )
                if expected_return_match:
                    actual_return = (
                        ast.unparse(method.returns)
                        if method.returns is not None
                        else ""
                    )
                    expected_return = expected_return_match.group(1)
                    if (
                        "tuple" in expected_return.casefold()
                        and "..." in expected_return
                        and (
                            "tuple" not in actual_return.casefold()
                            or "..." not in actual_return
                        )
                    ):
                        errors.append(
                            f"{path}:{owner}.{method.name}: approved variable-length "
                            f"tuple return `{expected_return}` does not match "
                            f"`{actual_return or '<missing>'}`."
                        )
            owner_call_names = {
                call_name.rsplit(".", 1)[-1]
                for call_name in _call_names(owner_node)
            }
            owner_callable_names = owner_call_names | {
                node.attr
                for node in ast.walk(owner_node)
                if isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
            }
            for interface in chunk.get(
                "required_dependency_interfaces",
            ) or []:
                if not isinstance(interface, Mapping):
                    continue
                interface_match = re.search(
                    r"\bdef\s+([a-z_][A-Za-z0-9_]*)\s*\(",
                    str(interface.get("signature") or ""),
                )
                if (
                    interface_match
                    and interface_match.group(1) not in owner_callable_names
                ):
                    errors.append(
                        f"{path}:{owner}: approved dependency callable "
                        f"`{interface_match.group(1)}` is not consumed by the "
                        "consumer implementation."
                    )
            if bool(contract.get("type_hints_required")):
                annotated_fields = {
                    node.target.id
                    for node in owner_node.body
                    if isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.annotation is not None
                }
                if "dataclass" in decorators and not annotated_fields:
                    errors.append(
                        f"{path}:{owner}: typed dataclass has no annotated fields."
                    )
                for method_name in contract.get("required_methods") or []:
                    method = methods.get(str(method_name))
                    if method is None:
                        continue
                    public_args = [
                        argument
                        for argument in [
                            *method.args.posonlyargs,
                            *method.args.args,
                            *method.args.kwonlyargs,
                        ]
                        if argument.arg not in {"self", "cls"}
                    ]
                    if (
                        any(argument.annotation is None for argument in public_args)
                        or method.returns is None
                    ):
                        errors.append(
                            f"{path}:{owner}.{method_name}: typed public method "
                            "requires parameter and return annotations."
                        )

        mechanics = " ".join(
            str(step)
            for item in chunk.get("implementation_mechanics") or []
            if isinstance(item, Mapping)
            for step in item.get("steps") or []
        ).casefold()
        owner_source = ast.unparse(owner_node)
        owner_source_lower = owner_source.casefold()
        owned_requirement_text = " ".join(
            str(requirement.get("text") or "")
            for requirement in chunk.get("requirements") or []
            if isinstance(requirement, Mapping)
        )
        if isinstance(owner_node, ast.ClassDef):
            ordered_methods = _method_map(owner_node)
            for property_name in (
                chunk.get("declaration_contract", {}).get("properties") or []
            ):
                property_method = ordered_methods.get(str(property_name))
                property_requirement = next(
                    (
                        str(requirement.get("text") or "")
                        for requirement in chunk.get("requirements") or []
                        if isinstance(requirement, Mapping)
                        and re.search(
                            rf"\b{re.escape(str(property_name))}\b",
                            str(requirement.get("text") or ""),
                        )
                    ),
                    "",
                )
                if (
                    property_method is not None
                    and re.search(
                        r"\binsertion\s+order\b",
                        property_requirement,
                        flags=re.IGNORECASE,
                    )
                    and any(
                        isinstance(call.func, ast.Name)
                        and call.func.id == "sorted"
                        for call in ast.walk(property_method)
                        if isinstance(call, ast.Call)
                    )
                ):
                    errors.append(
                        f"{path}:{owner}.{property_name}: approved insertion-order "
                        "property sorts its result instead of preserving the "
                        "owner's insertion sequence."
                    )
            if re.search(
                r"\binsertion\s+order\b",
                owned_requirement_text,
                flags=re.IGNORECASE,
            ):
                for property_name in (
                    chunk.get("declaration_contract", {}).get("properties") or []
                ):
                    property_method = ordered_methods.get(str(property_name))
                    if property_method is not None and any(
                        isinstance(call.func, ast.Name)
                        and call.func.id == "sorted"
                        for call in ast.walk(property_method)
                        if isinstance(call, ast.Call)
                    ):
                        error = (
                            f"{path}:{owner}.{property_name}: approved "
                            "insertion-order property sorts its result instead "
                            "of preserving the owner's insertion sequence."
                        )
                        if error not in errors:
                            errors.append(error)
            for requirement in chunk.get("requirements") or []:
                if not isinstance(requirement, Mapping):
                    continue
                requirement_text = str(requirement.get("text") or "")
                replacement_match = re.search(
                    r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\s*\([^)]*\)"
                    r"[^.!?\n]{0,180}\bpreserv(?:e|es|ed|ing)\b"
                    r"[^.!?\n]{0,100}\boriginal\s+insertion\s+position\b",
                    requirement_text,
                    flags=re.IGNORECASE,
                )
                replacement_method = (
                    ordered_methods.get(replacement_match.group(1))
                    if replacement_match
                    else None
                )
                if replacement_method is not None and any(
                    isinstance(node, ast.Delete)
                    or (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {"pop", "popitem"}
                    )
                    for node in ast.walk(replacement_method)
                ):
                    errors.append(
                        f"{path}:{owner}.{replacement_match.group(1)}: approved "
                        "replacement-position contract deletes or pops mapping "
                        "entries. Replace an existing key in place and preserve "
                        "all unrelated entries."
                    )
                if replacement_method is not None:
                    method_parameters = [
                        argument.arg
                        for argument in (
                            *replacement_method.args.posonlyargs,
                            *replacement_method.args.args,
                        )
                        if argument.arg not in {"self", "cls"}
                    ]
                    requested_key = (
                        method_parameters[0] if method_parameters else ""
                    )
                    wrong_assignment_keys = {
                        ast.unparse(target.slice)
                        for assignment in ast.walk(replacement_method)
                        if isinstance(assignment, (ast.Assign, ast.AnnAssign))
                        for target in (
                            assignment.targets
                            if isinstance(assignment, ast.Assign)
                            else [assignment.target]
                        )
                        if isinstance(target, ast.Subscript)
                        and isinstance(target.ctx, ast.Store)
                        and ast.unparse(target.slice) != requested_key
                    }
                    if wrong_assignment_keys:
                        errors.append(
                            f"{path}:{owner}.{replacement_match.group(1)}: "
                            "approved replacement-position contract assigns "
                            "through a different key expression ("
                            + ", ".join(sorted(wrong_assignment_keys))
                            + f") instead of the requested `{requested_key}` key."
                        )
        forbids_sleeping = bool(re.search(
            r"\bwithout\s+sleep(?:ing)?\b|\bdo\s+not\s+sleep\b"
            r"|\bnever\s+sleep\b|\bmutable\s+fake\s+clock\b",
            owned_requirement_text,
            flags=re.IGNORECASE,
        ))
        if forbids_sleeping:
            sleeping_calls = [
                ast.unparse(call.func)
                for call in ast.walk(owner_node)
                if isinstance(call, ast.Call)
                and (
                    isinstance(call.func, ast.Name)
                    and call.func.id == "sleep"
                    or isinstance(call.func, ast.Attribute)
                    and call.func.attr == "sleep"
                )
            ]
            if sleeping_calls:
                errors.append(
                    f"{path}:{owner}: approved deterministic timing contract "
                    "forbids sleeping; advance the injected or fake clock instead."
                )
        if (
            "monotonic-clock deadline" in mechanics
            or "time.monotonic()" in mechanics
            or "injected monotonic" in mechanics
        ):
            file_source_lower = source_by_path.get(path, "").casefold()
            if "monotonic" not in file_source_lower:
                errors.append(
                    f"{path}:{owner}: approved monotonic TTL deadline is not implemented."
                )
            if isinstance(owner_node, ast.ClassDef):
                methods = _method_map(owner_node)
                initializer = methods.get("__init__")
                injected_clock_attrs: set[str] = set()
                if initializer is not None:
                    callable_parameters = {
                        argument.arg
                        for argument in (
                            *initializer.args.posonlyargs,
                            *initializer.args.args,
                            *initializer.args.kwonlyargs,
                        )
                        if argument.arg not in {"self", "cls"}
                    }
                    for assignment in ast.walk(initializer):
                        if not isinstance(assignment, ast.Assign):
                            continue
                        if not isinstance(assignment.value, ast.Name):
                            continue
                        if assignment.value.id not in callable_parameters:
                            continue
                        for target in assignment.targets:
                            if (
                                isinstance(target, ast.Attribute)
                                and isinstance(target.value, ast.Name)
                                and target.value.id == "self"
                                and any(
                                    token in target.attr.casefold()
                                    for token in ("clock", "time_source", "monotonic")
                                )
                            ):
                                injected_clock_attrs.add(target.attr)
                injected_clock_required = (
                    "injected monotonic" in mechanics
                    or "stored injected" in mechanics
                )
                if injected_clock_required and re.search(
                    r"\btime\.(?:monotonic|time)\s*\(",
                    owner_source,
                ):
                    errors.append(
                        f"{path}:{owner}: injected clock is bypassed by a direct "
                        "host-clock call."
                    )
                helper_methods = {
                    name: method
                    for name, method in methods.items()
                    if name.startswith("_") and name != "__init__"
                }
                for method_name in ("put", "get", "keys"):
                    method = methods.get(method_name)
                    if method is None:
                        continue
                    method_text = ast.unparse(method).casefold()
                    called_helpers = [
                        helper_methods[call_name.rsplit(".", 1)[-1]]
                        for call_name in _call_names(method)
                        if call_name.rsplit(".", 1)[-1] in helper_methods
                    ]
                    helper_text = " ".join(
                        ast.unparse(helper).casefold()
                        for helper in called_helpers
                    )
                    combined_method_text = f"{method_text} {helper_text}"
                    expiry_markers = (
                        marker in combined_method_text
                        for marker in ("monotonic", "expire", "purge", "deadline")
                    )
                    if not any(expiry_markers):
                        errors.append(
                            f"{path}:{owner}.{method_name}: approved TTL expiry "
                            "path is missing."
                        )
                    if injected_clock_required and injected_clock_attrs and not any(
                        f"self.{attribute}" in combined_method_text
                        for attribute in injected_clock_attrs
                    ):
                        errors.append(
                            f"{path}:{owner}.{method_name}: expiry logic does not use "
                            "the stored injected clock."
                        )
                    call_names = _call_names(method)
                    if (
                        method_name == "put"
                        and "insertion order" in mechanics
                        and any(
                            call_name.rsplit(".", 1)[-1] in methods
                            and any(
                                marker in call_name.casefold()
                                for marker in ("remove", "delete", "discard")
                            )
                            for call_name in call_names
                        )
                        and any(
                            call_name.endswith(".append")
                            for call_name in call_names
                        )
                    ):
                        errors.append(
                            f"{path}:{owner}.{method_name}: updating an existing "
                            "key removes and appends it, which changes insertion "
                            "order. Replace the stored value and expiration in place "
                            "for existing keys, and append to the ordering collection "
                            "only when the key is new."
                        )
                    removes_expired = (
                        ".pop(" in combined_method_text
                        or "del " in combined_method_text
                        or any(
                            any(
                                marker in call_name.casefold()
                                for marker in (
                                    "cleanup",
                                    "purge",
                                    "evict",
                                    "expire",
                                    "remove",
                                )
                            )
                            for call_name in call_names
                            if call_name.rsplit(".", 1)[-1] in methods
                        )
                    )
                    if method_name in {"get", "keys"} and not removes_expired:
                        if method_name == "get":
                            errors.append(
                                f"{path}:{owner}.{method_name}: an expired requested "
                                "key is not lazily removed. Remove that key through an "
                                "already-declared removal method, or delete it directly "
                                "from every synchronized backing collection, then return "
                                "the missing-value result; do not call an undeclared "
                                "cleanup helper."
                            )
                        else:
                            errors.append(
                                f"{path}:{owner}.{method_name}: expired keys are filtered "
                                "but not lazily removed. Iterate over a stable snapshot, "
                                "remove every expired key from all synchronized backing "
                                "collections through declared behavior, and yield only "
                                "live keys in their original order."
                            )
                    if method_name == "keys":
                        for loop in [
                            node
                            for node in ast.walk(method)
                            if isinstance(node, (ast.For, ast.AsyncFor))
                            and isinstance(node.iter, ast.Attribute)
                            and isinstance(node.iter.value, ast.Name)
                            and node.iter.value.id == "self"
                        ]:
                            iterated_attribute = loop.iter.attr
                            mutates_iterated_attribute = any(
                                isinstance(node, ast.Call)
                                and isinstance(node.func, ast.Attribute)
                                and node.func.attr in {"remove", "pop", "clear"}
                                and isinstance(node.func.value, ast.Attribute)
                                and isinstance(node.func.value.value, ast.Name)
                                and node.func.value.value.id == "self"
                                and node.func.value.attr == iterated_attribute
                                for node in ast.walk(loop)
                            )
                            if mutates_iterated_attribute:
                                errors.append(
                                    f"{path}:{owner}.{method_name}: mutates the "
                                    f"insertion-order collection self."
                                    f"{iterated_attribute} while iterating it; iterate "
                                    "over a stable snapshot before removing expired "
                                    "entries."
                                )
        if "synchronization primitive" in mechanics and isinstance(
            owner_node, ast.ClassDef
        ):
            methods = _method_map(owner_node)
            if not any(
                isinstance(node, (ast.With, ast.AsyncWith))
                for method in methods.values()
                for node in ast.walk(method)
            ):
                errors.append(
                    f"{path}:{owner}: approved synchronization boundary is missing."
                )
            locking_methods = {
                name
                for name, method in methods.items()
                if any(
                    isinstance(node, (ast.With, ast.AsyncWith))
                    for node in ast.walk(method)
                )
            }
            owner_calls = {
                method_name: {
                    call_name.split(".", 1)[1]
                    for call_name in _call_names(method)
                    if call_name.startswith("self.")
                    and "." not in call_name[len("self."):]
                }
                for method_name, method in methods.items()
            }
            uses_reentrant_lock = "rlock" in owner_source_lower
            for method_name in locking_methods:
                nested_lock_calls = (
                    owner_calls.get(method_name, set()) & locking_methods
                )
                if nested_lock_calls and not uses_reentrant_lock:
                    errors.append(
                        f"{path}:{owner}.{method_name}: calls lock-owning method(s) "
                        f"{sorted(nested_lock_calls)} while holding a non-reentrant lock."
                    )
        if "1000 millisecond interval" in mechanics:
            if "1000" not in owner_source or not any(
                name.endswith((".start", ".setInterval"))
                for name in _call_names(owner_node)
            ):
                errors.append(
                    f"{path}:{owner}: approved 1000ms timer is not configured."
                )
        if "dependency clear operation first" in mechanics and isinstance(
            owner_node, ast.ClassDef
        ):
            ordered_calls = [
                name
                for method in _method_map(owner_node).values()
                for name in _call_names(method)
            ]
            clear_index = next(
                (index for index, name in enumerate(ordered_calls) if name.endswith(".clear")),
                -1,
            )
            refresh_index = next(
                (
                    index
                    for index, name in enumerate(ordered_calls)
                    if name == "self.refresh"
                ),
                -1,
            )
            if clear_index < 0 or refresh_index <= clear_index:
                errors.append(
                    f"{path}:{owner}: approved clear-then-refresh call order is missing."
                )
        if "qapplication entry point" in mechanics:
            has_guard = any(
                isinstance(node, ast.If)
                and "__name__" in ast.unparse(node.test)
                and "__main__" in ast.unparse(node.test)
                for node in tree.body
            )
            if not has_guard or ".show" not in ast.unparse(tree):
                errors.append(
                    f"{path}:<module>: approved QApplication entry point is missing."
                )
        if (
            str(chunk.get("kind") or "") == "module"
            and "mutable fake injected clock/time source" in mechanics
        ):
            module_source = source_by_path.get(path, "")
            has_sleep = bool(
                re.search(r"\b(?:time\.)?sleep\s*\(", module_source)
            )
            has_host_clock = bool(
                re.search(r"\btime\.(?:monotonic|time)\s*\(", module_source)
            )
            if has_sleep or has_host_clock:
                entry_symbol = "<module>"
                try:
                    module_tree = ast.parse(module_source, filename=path)
                except SyntaxError:
                    module_tree = None
                if module_tree is not None:
                    for statement in module_tree.body:
                        if not isinstance(statement, ast.If):
                            continue
                        if "__main__" not in ast.unparse(statement.test):
                            continue
                        called_names = [
                            node.func.id
                            for node in ast.walk(statement)
                            if isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                        ]
                        if len(called_names) == 1:
                            entry_symbol = called_names[0]
                            break
            if has_sleep:
                errors.append(
                    f"{path}:{entry_symbol}: runnable example sleeps to demonstrate a "
                    "time-dependent state change. Repair the owned entry callable by "
                    "advancing its mutable local fake-time state synchronously; do not "
                    "sleep."
                )
            if has_host_clock:
                errors.append(
                    f"{path}:{entry_symbol}: runnable example reads a direct host clock "
                    "instead of its injected fake time source. Repair the owned entry "
                    "callable by storing time in a built-in mutable local container and "
                    "injecting a nested callable that reads only that container; advance "
                    "the container directly, do not introduce a local class, and do not "
                    "import or read a host clock."
                )
    return list(dict.fromkeys(errors))


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
