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
            r"(?<![.\w])([a-z_][A-Za-z0-9_]*)\([^()]*\)",
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
    if (
        "__len__" not in explicit_names
        and re.search(
            r"\blen\([^()]+\)\s+(?:reports?|returns?|gives?|yields?)\b",
            text,
            flags=re.IGNORECASE,
        )
    ):
        explicit_names.append("__len__")
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
    if re.search(
        r"\balways\b[^.!?\n]{0,180}\b(?:cleanup|close|delete|destroy|dispose|"
        r"release|remove|unlink)\w*\b|\bcleanup\b|\bfinally\b",
        text,
        re.IGNORECASE,
    ):
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
    ) and not re.search(
        r"\b(?:mutate|modify|alter)\b[^.!?\n]{0,80}"
        r"\b(?:input|argument|mapping|payload|source|value)\b",
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
        r"\b(?:type hints?|annotations?)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Declare concrete parameter and return annotations on the approved "
            "public callable while preserving its existing name and call shape."
        )
    if re.search(r"\bdocstrings?\b", text, flags=re.IGNORECASE):
        steps.append(
            "Write a project-style callable docstring with a behavioral summary, "
            "one `:param name:` entry per parameter, and a concrete `:return:` entry."
        )
    if re.search(
        r"\b(?:do\s+not|without|never)\s+(?:mutate|modify|alter)\b"
        r"[^.!?\n]{0,100}\b(?:input|argument|mapping|payload|source|value)s?\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Preserve the caller-owned input unchanged: read the required fields and "
            "return a distinct result object instead of returning or modifying the "
            "input container."
        )
    if re.search(
        r"\b(?:modify|change|edit|touch)\s+only\b"
        r"|\bonly\s+(?:modify|change|edit|touch)\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Restrict the implementation change to the approved owner path and "
            "preserve every other workspace file byte-for-byte."
        )
    if re.search(
        r"\b(?:keep|preserve|retain)\b[^.!?\n]{0,100}"
        r"\b(?:public\s+)?(?:function|callable|method)\s+name\b",
        text,
        flags=re.IGNORECASE,
    ):
        steps.append(
            "Declare and retain the approved public callable name exactly and "
            "implement the requested behavior inside that declaration."
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
        steps.extend([
            "Record each entry's insertion timestamp through the configured clock "
            "source and treat `ttl_seconds` as a relative duration; never use wall-"
            "clock datetime APIs or sleeping for expiry behavior.",
            "At each requested cache observation, compare age to `ttl_seconds`; when "
            "age is greater than or equal to the TTL, atomically remove that entry "
            "before returning the operation's missing-value result.",
        ])
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
    if re.search(
        r"\balways\b[^.!?\n]{0,180}\b(?:cleanup|close|delete|destroy|dispose|"
        r"release|remove|unlink)\w*\b|\bcleanup\b|\bfinally\b",
        text,
        re.IGNORECASE,
    ):
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
    invalid_input_requested = re.search(
        r"\breject\b[^.!?\n]{0,160}\b(?:empty|blank|negative|invalid|missing)\b"
        r"|\b(?:empty|blank|negative|invalid|missing)\b"
        r"[^.!?\n]{0,160}\b(?:reject|raise|forbid|refuse)\b",
        text,
        flags=re.IGNORECASE,
    )
    specific_validation_steps: list[str] = []
    if re.search(
        r"\b(?:capacity|size|limit)\b[^.!?\n]{0,80}"
        r"\b(?:below|less\s+than)\s+(?:one|1)\b",
        text,
        flags=re.IGNORECASE,
    ):
        specific_validation_steps.append(
            "Before allocating cache state, compare `capacity < 1` and raise "
            "ValueError without mutating the instance when that condition is true."
        )
    if re.search(r"\bblank\s+names?\b", text, flags=re.IGNORECASE):
        specific_validation_steps.append(
            "Normalize each command name with `strip().casefold()` and raise "
            "ValueError before registration when the normalized value is empty."
        )
    if re.search(
        r"\bnon[- ]?callable\b[^.!?\n]{0,80}\bhandlers?\b"
        r"|\bhandlers?\b[^.!?\n]{0,80}\bnon[- ]?callable\b",
        text,
        flags=re.IGNORECASE,
    ):
        specific_validation_steps.append(
            "Evaluate `callable(handler)` before acquiring registration state and "
            "raise ValueError when it is false."
        )
    if re.search(
        r"\bduplicate\b[^.!?\n]{0,100}\b(?:names?|aliases?)\b",
        text,
        flags=re.IGNORECASE,
    ):
        specific_validation_steps.append(
            "While holding the registry lock, compare the normalized canonical name "
            "and every normalized alias against the complete existing name/alias "
            "namespace; on any collision raise ValueError before committing any key."
        )
    if specific_validation_steps:
        steps.extend(specific_validation_steps)
    elif invalid_input_requested:
        steps.append(
            "Validate the one stated invalid input boundary before storing state, "
            "raise its requested exception type, and leave prior state unchanged."
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
        exact_requirement = " ".join(str(text or "").split())
        steps.append(
            "Implement the approved callable as one atomic operation and return, "
            "preserve, or reject exactly as required by this authoritative clause: "
            + exact_requirement
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
