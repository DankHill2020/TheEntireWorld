"""
tech_connector_headless.py
--------------------------
Fully headless pipeline runner — no UI required.

Pipeline:
  1. classify_prompt_route()  ->  target_discovery route
  2. RequestEngine.process()  ->  resolve intent, scope, and target
  3. run_multi_file_project_edit_workflow()  ->  the only code-generation path
  4. extract_code_blocks()    ->  pull fenced ```python blocks from LLM output
  5. write to target file     ->  append / create the file on disk

Usage:
  python tech_connector_headless.py "add a MyClass in some.module.path ..."
  python tech_connector_headless.py --dry-run "add a MyClass in some.module.path ..."
  python tech_connector_headless.py --benchmark   (runs all test cases)
"""
from __future__ import annotations

import argparse
import itertools
import ast
import json
import os
import re
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

TOOLS_ROOT = Path(
    os.getenv("TOOLSROOT", str(Path(__file__).resolve().parents[2]))
).resolve()
if not TOOLS_ROOT.exists():
    TOOLS_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(TOOLS_ROOT))

from tech_connector.services.environment_service import (
    normalize_current_process_environment,
)

normalize_current_process_environment()

_FORBIDDEN_EDIT_ROOT_MARKERS = tuple(
    marker.strip().lower()
    for marker in re.split(r"[;,]", os.getenv("TECH_CONNECTOR_FORBIDDEN_EDIT_PATH_MARKERS", "time_fighters 5.8"))
    if marker.strip()
)

def _is_forbidden_target_path(raw_path: str) -> bool:
    normalized = str(raw_path or "").replace("\\", "/").lower()
    if not normalized:
        return False
    return any(marker in normalized for marker in _FORBIDDEN_EDIT_ROOT_MARKERS)

def _target_path_forbidden_error(raw_path: str) -> str:
    return (
        "Attempted to write inside forbidden project path: "
        f"{raw_path}. Set TECH_CONNECTOR_FORBIDDEN_EDIT_PATH_MARKERS to override."
    )


_NEW_CODE_CREATION_VERBS = {
    "add", "build", "create", "develop", "generate", "implement", "make",
    "produce", "write",
}
_NEW_CODE_ARTIFACT_NOUNS = {
    "app", "application", "class", "code", "file", "module", "package",
    "plugin", "python", "script", "service", "tool", "utility", "widget",
}
_INFERRED_FILENAME_STOP_WORDS = {
    "a", "an", "and", "as", "at", "be", "by", "class", "code", "create",
    "develop", "file", "for", "from", "generate", "i", "implement", "in",
    "into", "it", "make", "module", "of", "on", "onto", "our", "output",
    "package", "please", "produce", "python", "script", "service", "take",
    "that", "the", "this", "to", "tool", "utility", "want", "which", "with",
    "write",
}


def _is_obvious_unnamed_code_creation(
    prompt: str,
    *,
    has_explicit_target: bool,
) -> bool:
    """Recognize direct new-code requests without invoking a planning model."""

    if has_explicit_target:
        return False
    tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prompt or "")
    }
    has_creation_verb = bool(tokens & _NEW_CODE_CREATION_VERBS)
    has_artifact_noun = bool(tokens & _NEW_CODE_ARTIFACT_NOUNS)
    direct_phrase = bool(re.search(
        r"\b(?:write|build|create|make|generate|implement|develop|add)\b"
        r"[^.!?\n]{0,100}\b(?:file|script|module|class|tool|utility|"
        r"service|widget|plugin|application|app)\b",
        prompt or "",
        flags=re.IGNORECASE,
    ))
    return bool(has_creation_verb and (has_artifact_noun or direct_phrase))


def _inferred_python_filename(prompt: str) -> str:
    """Derive a stable descriptive filename from an unnamed code request."""

    raw_tokens = re.findall(
        r"[A-Za-z][A-Za-z0-9_]*",
        str(prompt or ""),
    )
    selected: list[str] = []
    for raw_token in raw_tokens:
        expanded = re.sub(
            r"(?<=[a-z0-9])(?=[A-Z])",
            "_",
            raw_token,
        )
        for token in expanded.casefold().split("_"):
            token = re.sub(r"[^a-z0-9]+", "", token)
            if (
                not token
                or token in _INFERRED_FILENAME_STOP_WORDS
                or len(token) < 2
            ):
                continue
            if token.endswith("ing") and len(token) > 6:
                token = token[:-3]
            elif token.endswith("ed") and len(token) > 5:
                token = token[:-2]
            if token and token not in selected:
                selected.append(token)
            if len(selected) >= 6:
                break
        if len(selected) >= 6:
            break
    stem = "_".join(selected) or "generated_tool"
    return f"{stem}.py"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", write_through=True)

from tech_connector.engine.request_engine import RequestEngine
from tech_connector.engine.request_context import RequestContext
from tech_connector.services.settings_service import load_settings, save_settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_model() -> str:
    """Return the best available Ollama coding model."""
    try:
        from tech_connector.services.ollama_service import (
            installed_ollama_models,
            resolve_ollama_model_name,
        )

        available = installed_ollama_models()
        # Prefer fast coding models in priority order
        preferred_models = (
            "qwen2.5-coder:7b",
            "qwen2.5-coder:3b",
            "qwen3:4b-instruct",
        )
        installed_lookup = {name.lower(): name for name in available}
        for preferred in preferred_models:
            canonical = preferred.lower()
            if canonical in installed_lookup:
                return installed_lookup[canonical]
        if available:
            return installed_lookup[next(iter(installed_lookup))]
    except Exception:
        pass
    # Final fallback from settings
    s = load_settings()
    from tech_connector.services.ollama_service import resolve_ollama_model_name

    raw = s.get("ollama_model") or s.get("model") or "qwen2.5-coder:7b"
    return resolve_ollama_model_name(raw.removeprefix("ollama:").strip())


def _estimate_llm_timeout(model: str, default: int = 120) -> int:
    try:
        from tech_connector.services.ollama_service import estimated_ollama_generation_timeout
        return max(30, int(estimated_ollama_generation_timeout(model)))
    except Exception:
        return default


def _coerce_timeout(llm_timeout: int | None, model: str) -> int:
    if not llm_timeout:
        return _estimate_llm_timeout(model)
    if llm_timeout < 30:
        return 30
    return llm_timeout


def _focused_repair_model(model: str, attempt: int) -> str:
    """Escalate failed 3B code repairs to installed 7B, never to 14B."""

    current = str(model or "")
    if attempt < 1 or not re.search(r":3b$", current, flags=re.IGNORECASE):
        return current
    candidate = re.sub(r":3b$", ":7b", current, flags=re.IGNORECASE)
    try:
        from tech_connector.services.ollama_service import installed_ollama_models

        installed = {name.lower(): name for name in installed_ollama_models()}
        return installed.get(candidate.lower(), current)
    except Exception:
        return current


_API_GAP_EVIDENCE_CACHE: dict[str, str] = {}


def _specific_api_gap_evidence(errors: list[str]) -> str:
    """Research only explicitly reported unresolved API gaps."""

    gaps: list[str] = []
    for error in errors:
        match = re.search(
            r"Capability gap:.*?evidence:\s*(.+)$",
            str(error),
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        gaps.extend(part.strip() for part in match.group(1).split(",") if part.strip())
    evidence: list[str] = []
    for gap in list(dict.fromkeys(gaps))[:3]:
        if gap not in _API_GAP_EVIDENCE_CACHE:
            try:
                from tech_connector.services.knowledge_research_service import (
                    search_public_sources,
                )

                result = search_public_sources(
                    f"{gap} Python API exact owner signature factory arguments",
                    official_only=True,
                    limit=4,
                    timeout=10.0,
                )
                _API_GAP_EVIDENCE_CACHE[gap] = json.dumps(
                    result,
                    ensure_ascii=True,
                    default=str,
                )[:6000]
            except Exception as exc:
                _API_GAP_EVIDENCE_CACHE[gap] = (
                    f"Official research unavailable for {gap}: {exc}"
                )
        evidence.append(f"{gap}:\n{_API_GAP_EVIDENCE_CACHE[gap]}")
    return "\n\n".join(evidence)


def _prompt_requires_multi_file_workflow(prompt: str) -> bool:
    """Return whether the request needs the shared bounded artifact workflow."""

    lowered = str(prompt or "").lower()
    explicit_terms = (
        "multi-file",
        "multiple files",
        "at least 2 files",
        "at least two files",
        "companion service",
        "companion module",
        "companion file",
        "backend and test",
        "backend and a test",
        "service and test",
        "service and a test",
        "with tests",
        "and tests",
        "test file",
    )
    if any(term in lowered for term in explicit_terms):
        return True
    # Dotted expressions in a single-file request are commonly API members,
    # Qt signals, or the one requested module path. Counting them as independent
    # file targets misroutes ordinary class edits into the multi-file workflow.
    return False


def _prompt_requires_companion_test(prompt: str) -> bool:
    """Return true only when the user explicitly requests a test artifact."""

    if re.search(
        r"\b(?:do\s+not|don't|without|no)\s+"
        r"(?:create|add|generate|write|include|produce|use|new|project\s+)*"
        r"(?:test\s+files?|tests?)\b",
        str(prompt or ""),
        flags=re.IGNORECASE,
    ):
        return False
    return bool(re.search(
        r"\b(?:companion\s+tests?|focused\s+tests?|pytest|unittest|"
        r"test\s+files?|unit\s+tests?|with\s+tests?)\b",
        str(prompt or ""),
        flags=re.IGNORECASE,
    ))


def _companion_test_target(target: str) -> str:
    """Choose an existing project-relative test root for a generated companion."""

    target_path = Path(target).resolve()
    test_name = f"test_{target_path.stem}.py"
    candidates = (
        target_path.parent / "tests",
        TOOLS_ROOT / "tests",
        TOOLS_ROOT / "examples" / "tech_connector" / "tests",
    )
    test_root = next((path for path in candidates if path.is_dir()), candidates[-1])
    return str((test_root / test_name).resolve())


def _target_module_path(target: str) -> str:
    """Return the importable module path for a target under TOOLS_ROOT."""

    try:
        relative = Path(target).resolve().relative_to(TOOLS_ROOT.resolve())
    except ValueError:
        return Path(target).stem
    return ".".join(relative.with_suffix("").parts)


def _is_fetch_style_request(prompt: str) -> bool:
    """Detect user prompts that explicitly request read-only symbol/file snippets."""
    lowered = str(prompt or "").lower()
    if not lowered:
        return False
    fetch_phrases = (
        r"\b(fetch|show|read|open|inspect|display|view)\b",
        r"\bwhat(?:'s| is)?\s+(?:the|a)\s+(?:implementation|code|body)\b",
        r"\bimplementation\s+of\b",
        r"\bwhere\b.*\b(?:function|class|symbol|method)\b",
    )
    has_fetch_intent = any(re.search(expr, lowered, flags=re.IGNORECASE) for expr in fetch_phrases)
    has_create_intent = re.search(
        r"\b(?:add|build|create|make|implement|develop|generate|write|modify|edit|fix|rewrite|refactor|remove)\b",
        lowered,
        flags=re.IGNORECASE,
    )
    return bool(has_fetch_intent and not has_create_intent)


def _requested_class_name(prompt: str) -> str:
    """Extract an explicitly named class without inventing a replacement name."""

    patterns = (
        r"\bclass\s+([A-Z][A-Za-z0-9_]*)\b",
        r"\b([A-Z][A-Za-z0-9_]*(?:Dialog|Widget|Window|Panel|Dock))"
        r"\s+(?:QWidget|QDialog|widget|dialog|window)\b",
        r"\b(?:add|build|create|define|implement|introduce|provide|write)"
        r"(?:\s+(?:a|an|the|new|complete|runnable|python|pyside6)){0,6}"
        r"\s+([A-Z][A-Za-z0-9_]*)\s+class\b",
    )
    for pattern in patterns:
        match = re.search(pattern, str(prompt or ""))
        if match:
            return match.group(1)
    return ""


def _repair_prompt(base_prompt: str, draft_code: str, owner_hint: str, errors: list[str]) -> str:
    """Build a focused one-shot correction prompt for unresolved generation issues."""

    error_block = ""
    if errors:
        trimmed = [str(err) for err in errors[:12]]
        error_block = "\n".join(f"- {item}" for item in trimmed)
    return (
        f"{base_prompt.rstrip()}\n\n"
        "REPAIR PASS REQUIRED:\n"
        "- The previous draft still has unresolved issues. "
        "Do not output a plan.\n"
        "- Keep the same ownership model and target file.\n"
        "- Return complete fixed code for all required files.\n"
        f"{('- Preserve and keep class/function names that already match the request.' if owner_hint else '')}\n"
        f"{('Targeted owner: ' + owner_hint) if owner_hint else ''}\n"
        "Unresolved issues:\n"
        f"{error_block}\n\n"
        "Current draft (trimmed):\n"
        "```python\n"
        f"{str(draft_code or '')[:9000]}\n"
        "```\n"
        "- Fix and re-emit final corrected code.\n"
    )


def extract_code_blocks(text: str) -> str:
    """
    Pull all fenced ```python ... ``` blocks from LLM output.
    Falls back to the raw text if no fenced blocks found.
    """
    blocks = re.findall(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    # If the whole response looks like code (no markdown prose), return as-is
    lines = text.strip().splitlines()
    code_lines = sum(1 for l in lines if l.startswith(("    ", "\t", "class ", "def ", "import ", "from ", "@", "#")))
    if code_lines / max(len(lines), 1) > 0.5:
        return text.strip()
    return text.strip()


def _candidate_json_from_preview_changes(changes: list[dict]) -> str:
    """Convert parsed preview changes to a repair-ready JSON change object."""

    items: list[dict] = []
    for item in changes:
        action = str(item.get("action") or "").strip().lower() or (
            "create" if not str(item.get("before") or "") else "modify"
        )
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
            action = "modify"
        path = str(item.get("path") or "")
        if not path:
            continue
        items.append({
            "action": action,
            "path": path,
            "target_symbol": str(item.get("target_symbol") or ""),
            "original_content": str(item.get("before") or item.get("original_content") or ""),
            "new_content": str(item.get("after") or item.get("new_content") or ""),
        })

    if not items:
        return ""

    return json.dumps({
        "changes": items,
        "report": {
            "changed": [Path(item["path"]).name for item in items],
            "reused": [],
            "verification": ["parse", "compile", "imports", "focused unittest"],
            "remaining_gaps": [],
            "requirement_coverage": [],
        },
        "blocked_reason": "",
    }, ensure_ascii=True)


def _preview_changes_to_code_output(preview_changes: list[dict], target_path: str = "") -> str:
    """Render previewed file payloads as human-readable consolidated output."""

    target_norm = str(Path(target_path).resolve()) if target_path else ""

    def _normalize_path(raw_path: str) -> str:
        if not raw_path:
            return raw_path
        if target_norm and Path(raw_path).name == Path(target_norm).name:
            return target_norm
        parts = Path(raw_path).parts
        lower_parts = [part.lower() for part in parts]
        if "unreal_tools" in lower_parts:
            idx = lower_parts.index("unreal_tools")
            return str((TOOLS_ROOT / Path(*parts[idx:])).resolve())
        return str(Path(raw_path).resolve())

    blocks: list[str] = []
    for item in preview_changes:
        after = str(item.get("after") or item.get("new_content") or "")
        path = str(item.get("path") or "")
        if not after:
            continue
        blocks.append(f"# file: {_normalize_path(path)}\n{after}")
    return "\n\n".join(blocks).strip()


def _working_file_output_from_raw(
    raw_llm_output: str,
    target_path: str,
    target_snapshot: str,
) -> str:
    """
    Build a working-file preview by applying XML patch hunks to the provided snapshot.
    """
    import re
    from tech_connector.knowledge.search import replace_content_resilient

    target_path = str(Path(target_path).resolve()) if target_path else ""
    def _normalize_path_for_output(raw_path: str) -> str:
        if not raw_path:
            return raw_path
        norm = str(Path(raw_path).resolve())
        if Path(raw_path).name == Path(target_path).name and target_path:
            return target_path
        if norm.startswith(str(TOOLS_ROOT / "unreal_tools")):
            return norm
        return norm
    working_by_path: dict[str, str] = {}
    body_outputs: list[str] = []

    create_matches = list(
        re.finditer(
            r'<create_file\s+path=["\'](.*?)["\']\s*>\n?(.*?)\n?</create_file>',
            raw_llm_output,
            re.DOTALL,
        )
    )
    modify_matches = list(
        re.finditer(
            r'<modify_file\s+path=["\'](.*?)["\']\s*>\n?(.*?)\n?</modify_file>',
            raw_llm_output,
            re.DOTALL,
        )
    )
    if not create_matches and not modify_matches:
        text = (raw_llm_output or "").strip()
        if text.startswith("{"):
            try:
                payload = json.loads(text)
                changes = payload.get("changes") if isinstance(payload, dict) else None
                if isinstance(changes, list):
                    outputs = []
                    for change in changes:
                        if not isinstance(change, dict):
                            continue
                        path = str(change.get("path") or target_path)
                        code_body = str(change.get("new_content") or "").strip()
                        if code_body:
                            outputs.append(f"# file: {_normalize_path_for_output(path)}\n{code_body}")
                    if outputs:
                        return "\n\n".join(outputs).strip()
            except Exception:
                pass
        extracted = extract_code_blocks(raw_llm_output)
        if extracted.strip():
            return extracted.strip()
        return raw_llm_output.strip()

    if target_path:
        working_by_path[target_path] = target_snapshot

    for m in create_matches:
        file_path = str(Path(m.group(1).strip()).resolve())
        body = m.group(2).strip("\n")
        if not body:
            continue
        working_by_path[file_path] = body
        body_outputs.append(f"# file: {_normalize_path_for_output(m.group(1).strip())}\n{body}")

    for m in modify_matches:
        file_path = str(Path(m.group(1).strip()).resolve())
        body = m.group(2)
        blocks = re.findall(r"<<<< ORIGINAL\n(.*?)\n====\n(.*?)\n>>>>", body, re.DOTALL)
        if not blocks:
            continue
        current = working_by_path.get(file_path, target_snapshot)
        modified = current
        for orig, repl in blocks:
            ok, modified = replace_content_resilient(modified, orig, repl)
            if not ok and repl.strip():
                modified = modified.rstrip("\n") + "\n\n" + repl.strip("\n") + "\n"
        working_by_path[file_path] = modified
        body_outputs.append(f"# file: {_normalize_path_for_output(m.group(1).strip())}\n{modified}")

    if body_outputs:
        return "\n\n".join(body_outputs).strip()
    extracted = extract_code_blocks(raw_llm_output)
    if extracted.strip():
        return extracted.strip()
    return raw_llm_output.strip()


QUALITY_PASS_ORDER = [
    "syntax",
    "imports",
    "signals",
    "api",
    "dead_code",
    "behavioral_coverage",
    "other",
]


def _quality_owner_scope_match(
    item: dict[str, object],
    owner_hint: str,
    target_path: str | None,
) -> bool:
    """Keep only validation checks that can be directly tied to the requested owner."""

    if not owner_hint and not target_path:
        return True

    lowered_hint = owner_hint.lower()
    owner_text = str(item.get("owner") or "").lower()
    text = " ".join(
        str(item.get(field) or "")
        for field in ("check", "message", "command", "owner", "path")
    ).lower()
    if lowered_hint and lowered_hint in text:
        return True
    if lowered_hint and owner_text:
        return lowered_hint in owner_text

    if lowered_hint and not owner_text:
        # Defer to textual match only when explicit owner is not emitted.
        return lowered_hint in text

    if target_path:
        target_text = str(target_path).lower()
        return target_text in text

    return False


def _filter_targeted_validation(
    validation: list[dict[str, object]] | None,
    requested_owner: str,
    target_path: str | None,
) -> list[dict[str, object]]:
    """Drop unrelated validation failures so new insertions are not blocked by old file debt."""

    if not validation:
        return []

    return [
        item
        for item in validation
        if _quality_owner_scope_match(item, requested_owner, target_path)
    ]


def _requested_base_class_name(prompt: str) -> str:
    """Extract a requested base class like `object` or `ModelessContinueDialog`."""

    lowered = str(prompt or "")
    m = re.search(
        r"(?:inherit(?:s|ing)\s+from\s+|inherits\s+from\s+)"
        r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)",
        lowered,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return "object"


def _fallback_class_scaffold(prompt: str, class_name: str, *, is_new_file: bool) -> str:
    """Build a minimal class scaffold for fallback output when plan chunks are missing."""

    base_expr = _requested_base_class_name(prompt) or "object"
    if is_new_file:
        return (
            '"""Auto-generated module scaffold."""\n\n'
            f"class {class_name}({base_expr}):\n"
            '    """Generated fallback class."""\n'
            "    def __init__(self) -> None:\n"
            f"        super({class_name}, self).__init__()\n"
        )

    return (
        f"\n\nclass {class_name}({base_expr}):\n"
        '    """Generated fallback class."""\n'
        "    def __init__(self) -> None:\n"
        f"        super({class_name}, self).__init__()\n"
    )


def _quality_check_bucket(check: str) -> str:
    """Map a project-edit validation check identifier into a quality pass."""
    check_l = str(check or "").lower()
    if check_l.startswith("syntax"):
        return "syntax"
    if check_l.startswith("import") or check_l.startswith("import_guard"):
        return "imports"
    if check_l.startswith("signal_") or check_l.startswith("ui_widget_"):
        return "signals"
    if (
        check_l.startswith("unreal_")
        or "api" in check_l
        or check_l.startswith("create_asset")
        or check_l.startswith("requested_identifier")
        or check_l.startswith("factory_")
    ):
        return "api"
    if check_l.startswith("behavior") or check_l.startswith("disposable_") or check_l in {"requested_symbols", "clear_names"}:
        return "behavioral_coverage"
    if (
        check_l.startswith("public_docstrings")
        or check_l.startswith("public_scope")
        or check_l.startswith("placeholder_")
        or check_l.startswith("undefined")
        or check_l.startswith("requested_")
    ):
        return "dead_code"
    return "other"


def _quality_check_messages_by_pass(validation: list[dict[str, object]] | None) -> dict[str, list[str]]:
    """Return failing-check messages grouped by explicit quality pass."""
    grouped: dict[str, list[str]] = {name: [] for name in QUALITY_PASS_ORDER}
    for item in validation or []:
        if item.get("ok"):
            continue
        check = str(item.get("check") or "")
        message = str(item.get("message") or item.get("command") or "No detail.")
        grouped.setdefault(_quality_check_bucket(check), []).append(message)
    return grouped


def _extract_candidate_symbols(text: str) -> list[str]:
    """Return likely class/function symbols from prompt/model output snippets."""
    found: list[str] = []
    for match in re.finditer(r"\b(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)\b", text or "", re.IGNORECASE):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def _extract_python_top_level_symbols(source: str) -> list[str]:
    """Return top-level symbols in a Python source snapshot."""
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return []
    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef)):
            symbols.append(str(node.name))
    return symbols


def _extract_symbol_blocks(source: str) -> dict[str, str]:
    """Return top-level and simple nested class method source text by symbol name."""
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return {}

    lines = (source or "").splitlines()
    blocks: dict[str, str] = {}

    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        start = max(int(getattr(node, "lineno", 1)) - 1, 0)
        end = int(getattr(node, "end_lineno", start + 1) or (start + 1))
        block = "\n".join(lines[start:end]).rstrip()
        if not block:
            continue
        blocks[str(node.name)] = textwrap.dedent(block).rstrip()
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                cstart = max(int(getattr(child, "lineno", 1)) - 1, 0)
                cend = int(getattr(child, "end_lineno", cstart + 1) or (cstart + 1))
                cblock = "\n".join(lines[cstart:cend]).rstrip()
                if cblock:
                    blocks[f"{node.name}.{child.name}"] = textwrap.dedent(cblock).rstrip()
    return blocks


def _find_best_fetch_target_and_symbol(
    prompt: str,
    result_meta: dict,
    target_hint: str,
    project_root: Path,
) -> tuple[str, str]:
    """
    Resolve the most likely file/symbol source for fetch-style prompts.

    Returns a tuple of (target_path, symbol_name). target_path is resolved to an
    absolute path when available, otherwise an empty string.
    """
    metadata = dict(result_meta or {})
    route_decision = dict(metadata.get("route_decision") or {})
    workspace_update = dict(metadata.get("workspace_update") or {})

    file_candidates: list[str] = []
    symbol_candidates: list[str] = []

    def _add_file(raw_path: str | None) -> None:
        if not raw_path:
            return
        try:
            path = Path(str(raw_path))
            if not path.is_absolute():
                path = (project_root / path)
            file_candidates.append(str(path.resolve()))
        except Exception:
            pass

    _add_file(str(metadata.get("selected_file") or ""))
    _add_file(str(metadata.get("selected_target") or ""))
    _add_file(str(metadata.get("target_file") or ""))
    _add_file(target_hint)
    _add_file(route_decision.get("selected_file") if isinstance(route_decision, dict) else None)
    _add_file(route_decision.get("target_file") if isinstance(route_decision, dict) else None)
    selected_entities = workspace_update.get("entities") if isinstance(workspace_update, dict) else None
    if isinstance(selected_entities, list):
        for entity in selected_entities:
            if isinstance(entity, dict):
                _add_file(str(entity.get("metadata", {}).get("file") or entity.get("file") or "" ))

    prompt_symbols = _extract_candidate_symbols(prompt)
    if prompt_symbols:
        symbol_candidates.extend(prompt_symbols)
    if metadata.get("selected_symbol"):
        symbol_candidates.append(str(metadata["selected_symbol"]))
    prompt_symbol_hint = re.search(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:class|function|method)\b",
        str(prompt or ""),
        flags=re.IGNORECASE,
    )
    if prompt_symbol_hint:
        symbol_candidates.append(prompt_symbol_hint.group(1))
    for pattern in (
        r"\bimplementation\s+of\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bcode(?:\s+snippet)?\s+for\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\bfetch\s+(?:the|an?|implementation|code)\s+of\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    ):
        match = re.search(pattern, str(prompt or ""), flags=re.IGNORECASE)
        if match:
            symbol_candidates.append(match.group(1))

    if isinstance(selected_entities, list):
        for entity in selected_entities:
            if isinstance(entity, dict):
                sym = entity.get("name") or entity.get("symbol")
                if sym:
                    symbol_candidates.append(str(sym))

    seen_files: set[str] = set()
    unique_files = [path for path in file_candidates if path and (path not in seen_files and not seen_files.add(path))]
    for candidate in unique_files:
        if candidate.lower().endswith(".py"):
            return candidate, next((sym for sym in symbol_candidates if sym), "")
    if unique_files:
        return unique_files[0], next((sym for sym in symbol_candidates if sym), "")
    return "", next((sym for sym in symbol_candidates if sym), "")


def _render_fetch_code(file_path: str, symbol_name: str) -> str:
    """Build a small code payload for fetch-style responses."""
    if not file_path:
        return ""
    file_obj = Path(file_path)
    if not file_obj.exists() or not file_obj.is_file():
        return ""
    try:
        source = file_obj.read_text(encoding="utf-8")
    except Exception:
        return ""

    blocks = _extract_symbol_blocks(source)
    if symbol_name:
        if symbol_name in blocks:
            return f"# file: {file_obj}\n{blocks[symbol_name].rstrip()}"
        last_piece = symbol_name.rsplit(".", 1)[-1]
        if last_piece in blocks:
            return f"# file: {file_obj}\n{blocks[last_piece].rstrip()}"

    lines = source.splitlines()
    preview = "\n".join(lines[:240])
    return f"# file: {file_obj}\n{preview.rstrip()}"


def _coerce_repair_code_payload(raw_llm_output: str, target_path: str) -> str:
    """Return clean python source suitable for direct symbol/file repair payloads."""
    text = (extract_code_blocks(raw_llm_output) or "").strip()
    if not text:
        return ""

    marker_blocks = re.findall(
        r"(?ms)^# file:\s*([^\n]+)\n(.*?)(?=^# file:\s*|\Z)",
        text + "\n",
    )
    if marker_blocks:
        target_name = Path(target_path).name.lower() if target_path else ""
        for marker_path, body in marker_blocks:
            marker_name = Path(str(marker_path).strip()).name.lower()
            if target_name and marker_name == target_name:
                return body.strip()
        return marker_blocks[0][1].strip()

    if text.startswith("# file:"):
        text = re.sub(r"^# file:.*\n", "", text, count=1).strip()

    lines = text.splitlines()
    candidate_starts = [
        idx
        for idx, line in enumerate(lines)
        if re.match(r"^\s*(class|def|from|import|@\w+)", line)
    ]
    candidate_starts.append(0)
    for idx in dict.fromkeys(candidate_starts):
        candidate = "\n".join(lines[idx:]).strip()
        if not candidate:
            continue
        try:
            ast.parse(candidate)
        except SyntaxError:
            continue
        return candidate

    return text


def _build_symbol_level_repair_payload(
    target: str,
    target_snapshot: str,
    request_prompt: str,
    raw_llm_output: str,
) -> str | None:
    """Build a single JSON symbol patch from generated symbol text for resilient repairs."""
    output_text = _coerce_repair_code_payload(raw_llm_output, target)
    if not output_text:
        return None

    if not target_snapshot:
        # Empty or missing target file: safest repair is a direct create action.
        return json.dumps({
            "changes": [
                {
                    "action": "create",
                    "path": target,
                    "new_content": output_text.rstrip() + "\n",
                }
            ],
            "report": {
                "changed": [Path(target).name],
                "reused": [],
                "verification": [],
                "remaining_gaps": [],
                "requirement_coverage": [],
            },
            "blocked_reason": "",
        }, ensure_ascii=True)

    existing_symbols = _extract_python_top_level_symbols(target_snapshot)
    existing_symbol_set = set(existing_symbols)
    generated_symbols = _extract_symbol_blocks(output_text)
    if not generated_symbols:
        return None

    requested = _extract_candidate_symbols(request_prompt)
    symbol: str | None = None
    strategy: str = "insert_after_symbol"

    for candidate in requested:
        if candidate in generated_symbols:
            if candidate in existing_symbol_set:
                strategy = "replace_symbol"
                symbol = candidate
            else:
                strategy = "insert_after_symbol"
                symbol = candidate
            break

    if symbol is None:
        for candidate in generated_symbols:
            if candidate in existing_symbol_set:
                strategy = "replace_symbol"
                symbol = candidate
                break

    if symbol is None:
        # New symbol insertion at stable anchor (class/function tail) for deterministic incremental repair.
        symbol = next(iter(generated_symbols), None)
        if not symbol:
            return None
        strategy = "insert_after_symbol"

    anchor = None
    if strategy == "insert_after_symbol" and existing_symbols:
        anchor = existing_symbols[-1]
    if strategy == "replace_symbol":
        anchor = symbol
    if symbol not in generated_symbols:
        return None

    new_content = generated_symbols[symbol]
    if not new_content.strip():
        return None

    payload = {
        "changes": [
            {
                "action": strategy,
                "path": target,
                "target_symbol": symbol if strategy == "replace_symbol" else (anchor or symbol),
                "new_content": new_content + "\n",
            }
        ],
        "report": {
            "changed": [Path(target).name],
            "reused": [],
            "verification": [],
            "remaining_gaps": [],
            "requirement_coverage": [],
        },
        "blocked_reason": "",
    }

    if strategy == "insert_after_symbol" and not payload["changes"][0]["target_symbol"]:
        return None
    return json.dumps(payload, ensure_ascii=True)


def _infer_repair_symbol_focus(
    request_prompt: str,
    raw_llm_output: str,
    target_snapshot: str,
) -> tuple[str, str | None] | None:
    """
    Pick a practical symbol target when a symbol-level patch failed to match.
    Returns (strategy, symbol_or_anchor).
    strategy is ``replace_symbol`` when a requested symbol exists in the file;
    otherwise ``insert_after_symbol`` with a stable anchor symbol for insertion.
    """
    existing = _extract_python_top_level_symbols(target_snapshot)
    existing_set = set(existing)

    requested = _extract_candidate_symbols(request_prompt)
    for symbol in requested:
        if symbol in existing_set:
            return "replace_symbol", symbol

    output_symbols = _extract_candidate_symbols(raw_llm_output)
    for symbol in output_symbols:
        if symbol in existing_set:
            return "replace_symbol", symbol

    anchor = existing[-1] if existing else None
    if requested:
        return ("insert_after_symbol", anchor) if anchor else None
    if output_symbols:
        return ("insert_after_symbol", anchor) if anchor else None
    return None


def _next_quality_focus(
    quality_passes: dict[str, list[str]],
) -> str:
    """Return the first passing order quality pass that currently has failures."""
    for name in QUALITY_PASS_ORDER:
        if quality_passes.get(name):
            return name
    return "other"


def _first_failing_quality_pass(
    quality_passes: dict[str, list[str]],
    start_index: int = 0,
) -> tuple[str | None, int]:
    """Return the first failing pass at or after `start_index` and its index."""
    for idx in range(start_index, len(QUALITY_PASS_ORDER)):
        name = QUALITY_PASS_ORDER[idx]
        if quality_passes.get(name):
            return name, idx
    return None, len(QUALITY_PASS_ORDER)


def _build_iterative_repair_prompt(
    user_prompt: str,
    prior_output: str,
    errors: list[str],
    attempt: int,
    dry_run: bool,
    quality_pass: str | None = None,
    target_is_new_file: bool = False,
    repair_strategy: tuple[str, str | None] | None = None,
) -> str:
    """
    Build a targeted prompt that preserves working output and asks the model to repair only failures.
    """
    phase = "dry-run preview/validation" if dry_run else "apply validation"
    error_block = "\n".join(f"- {error}" for error in errors) if errors else "- No detailed errors were reported."
    tail = prior_output
    if len(tail) > 18_000:
        tail = tail[-18_000:]
    focus_marker = f"- Focus pass: {quality_pass}\n" if quality_pass else ""
    if target_is_new_file:
        file_policy = (
            "- TARGET FILE POLICY: target file is new/empty; use a JSON change with "
            "action \"create\" for this path.\n"
        )
    else:
        file_policy = "- TARGET FILE POLICY: existing non-empty file; do not emit whole-file rewrites.\n- Use class/function chunk edits only.\n"
    if target_is_new_file:
        chunk_hint = (
            "- New-file repair: return one complete corrected target-file `create` "
            "action, including every required import, class member, connection, and "
            "`__main__` path.\n"
            "- Include separate `create` actions for any required focused companion "
            "test files. Do not reduce a new file to a class-only symbol payload.\n"
        )
    elif repair_strategy:
        strategy, symbol = repair_strategy
        if strategy == "replace_symbol" and symbol:
            chunk_hint = (
                f"- Symbol-level repair: replace an existing symbol.\n"
                f"- Use one symbol edit on target_symbol=\"{symbol}\".\n"
                "- Return a JSON payload (single change object is fine) with action \"replace_symbol\".\n"
            )
        elif strategy == "insert_after_symbol" and symbol:
            chunk_hint = (
                f"- Symbol-level repair: requested symbol is new.\n"
                f"- Use one symbol edit with action \"insert_after_symbol\" and target_symbol=\"{symbol}\".\n"
                "- Return a JSON payload (single change object is fine) with the full new symbol source in new_content.\n"
            )
        else:
            chunk_hint = "- Symbol-level repair: use the smallest possible symbol-level change.\n"
        repair_payload = (
            "Required schema example:\n"
            '{\n'
            '  "changes": [\n'
            '    {\n'
            f'      "action": "{strategy}",\n'
            '      "path": "<target path>",\n'
            f'      "target_symbol": "{symbol or ""}",\n'
            '      "new_content": "<full symbol source>\\n"\n'
            '    }\n'
            '  ],\n'
            '  "report": {\n'
            '    "changed": [],\n'
            '    "reused": [],\n'
            '    "verification": [],\n'
            '    "remaining_gaps": [],\n'
            '    "requirement_coverage": []\n'
            '  },\n'
            '  "blocked_reason": ""\n'
            '}\n'
        )
        chunk_hint = (
            f"{chunk_hint}"
            f"- {repair_payload}"
        )
    else:
        chunk_hint = (
            "- Use one symbol-level edit payload.\n"
            "- For existing files, prefer JSON with action: replace_symbol or insert_after_symbol.\n"
            "- Use one symbol chunk only.\n"
        )

    return (
        f"{user_prompt}\n\n"
        "REPAIR PASS REQUIRED:\n"
        f"- This is attempt {attempt}.\n"
        f"- Preserve any currently-correct symbols and avoid rewriting working code.\n"
        f"- The failure occurred during: {phase}.\n"
        f"{focus_marker}"
        + f"{file_policy}"
        + f"{chunk_hint}"
        + (
            "- Do not include any prose outside the requested schema.\n"
            if repair_strategy and not target_is_new_file
            else "- Do not include any prose outside the JSON payload.\n"
            "- Use one symbol-level payload for the target change.\n"
            "- Return the full JSON changes object with no markdown fences or XML.\n"
        )
        + "- Make only the smallest changes needed to satisfy the failed checks.\n"
        + f"- Fix these issues:\n{error_block}\n\n"
        + "Prior output to repair:\n"
        + "```text\n"
        + f"{tail}\n"
        + "```\n"
    )


def _needs_chunk_repair(errors: list[str]) -> bool:
    return any(
        "Original block did not match" in str(error)
        or "No <modify_file> or <create_file> changes found." in str(error)
        for error in errors
    )


def _first_or_default(iterable, default=""):
    for item in iterable:
        return item
    return default


def _quality_pass_summary(
    validation: list[dict[str, object]] | None,
    *,
    fallback_errors: list[str] | None = None,
    requested_owner: str = "",
    target_path: str = "",
) -> dict[str, list[str]]:
    """
    Group project-edit validation checks into explicit quality passes.
    """
    relevant_validation = _filter_targeted_validation(
        validation,
        requested_owner=requested_owner,
        target_path=target_path,
    )
    summary: dict[str, list[str]] = _quality_check_messages_by_pass(relevant_validation)
    if not summary or not any(summary.values()):
        if fallback_errors:
            filtered_fallback_errors = [
                error
                for error in fallback_errors
                if _quality_owner_scope_match(
                    {"command": str(error), "message": str(error)},
                    owner_hint=requested_owner,
                    target_path=target_path,
                )
            ]
            if not filtered_fallback_errors and requested_owner and not target_path:
                # If explicit class scoping is set, suppress unrelated engine-level fallback
                # noise unless it directly references the requested owner.
                filtered_fallback_errors = []
            summary["other"].extend(str(error) for error in filtered_fallback_errors)
    return summary


def write_code_to_file(target_path: str, raw_llm_output: str, code: str, dry_run: bool = False) -> str:
    """
    Apply generated code or XML patch blocks (<modify_file> / <create_file>) to target_path.
    """
    import re
    from tech_connector.knowledge.search import replace_content_resilient

    p = Path(target_path)
    
    # Check for XML modify_file or create_file blocks
    modify_matches = list(re.finditer(r'<modify_file\s+path=["\'](.*?)["\']\s*>\n?(.*?)\n?</modify_file>', raw_llm_output, re.DOTALL))
    create_matches = list(re.finditer(r'<create_file\s+path=["\'](.*?)["\']\s*>\n?(.*?)\n?</create_file>', raw_llm_output, re.DOTALL))
    
    if modify_matches or create_matches:
        results = []
        for m in modify_matches:
            filePath = Path(m.group(1).strip())
            body = m.group(2)
            if not filePath.is_absolute():
                filePath = p.parent / filePath
            blocks = re.findall(r"<<<< ORIGINAL\n(.*?)\n====\n(.*?)\n>>>>", body, re.DOTALL)
            if dry_run:
                results.append(f"[DRY RUN] Would modify {filePath} ({len(blocks)} blocks)")
            else:
                filePath.parent.mkdir(parents=True, exist_ok=True)
                existing = filePath.read_text(encoding="utf-8") if filePath.exists() else ""
                modified = existing
                for orig, repl in blocks:
                    ok, modified = replace_content_resilient(modified, orig, repl)
                    if not ok:
                        # Append replacement if original block couldn't be matched
                        modified += f"\n\n{repl}\n"
                filePath.write_text(modified, encoding="utf-8")
                results.append(f"Modified {filePath} ({len(blocks)} blocks)")

        for m in create_matches:
            filePath = Path(m.group(1).strip())
            body = m.group(2)
            if not filePath.is_absolute():
                filePath = p.parent / filePath
            if dry_run:
                results.append(f"[DRY RUN] Would create {filePath} ({len(body)} chars)")
            else:
                filePath.parent.mkdir(parents=True, exist_ok=True)
                filePath.write_text(body, encoding="utf-8")
                results.append(f"Created {filePath} ({len(body)} chars)")
        return "; ".join(results)

    # Standard fallback: write/append code to target_path
    if dry_run:
        return f"[DRY RUN] Would write {len(code)} chars to {p}"

    p.parent.mkdir(parents=True, exist_ok=True)
    separator = "\n\n# --- auto-generated ---\n\n" if p.exists() and p.stat().st_size > 0 else ""
    with p.open("a", encoding="utf-8") as f:
        f.write(separator + code + "\n")
    return f"Written {len(code)} chars â†’ {p}"


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def _explicit_dotted_module_targets(prompt: str) -> list[str]:
    """Return source-module targets explicitly identified by prompt grammar."""

    patterns = (
        r"\b(?:add|build|create|define|implement|write)\s+"
        r"([a-z_]\w*(?:\.[a-z_]\w*)+)"
        r"(?=\s+(?:as|containing|that|which|with)\b|[\s:,.]|$)",
        r"\b(?:in|into)\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b",
        r"\bmodule\s+(?:named\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b",
        r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\s+module\b",
    )
    matches = [
        match
        for pattern in patterns
        for match in re.findall(pattern, prompt or "", flags=re.IGNORECASE)
    ]
    for declaration in re.findall(
        r"\bmodules?\s*(?::|named)?\s*"
        r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+"
        r"(?:\s*(?:,|and)\s*"
        r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)*)",
        prompt or "",
        flags=re.IGNORECASE,
    ):
        matches.extend(re.findall(
            r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+",
            declaration,
        ))
    return list(dict.fromkeys(matches))


_TUTORIAL_GUIDANCE_SECTIONS: tuple[str, ...] = (
    "understood",
    "approach",
    "now",
    "steps",
    "links",
    "references",
    "tools",
    "risks",
)


def _default_tutorial_guidance_sections() -> set[str]:
    settings = load_settings()
    stored = settings.get("tutorial_guidance_sections")
    if isinstance(stored, dict):
        selected = {
            key
            for key in _TUTORIAL_GUIDANCE_SECTIONS
            if bool(stored.get(key, True))
        }
        return selected
    if isinstance(stored, (list, tuple, set)):
        selected = {str(key).strip().lower() for key in stored if str(key).strip()}
        explicit = {key for key in _TUTORIAL_GUIDANCE_SECTIONS if key in selected}
        if explicit:
            return explicit
    return set(_TUTORIAL_GUIDANCE_SECTIONS)


def _persist_tutorial_guidance_sections(sections: set[str]) -> None:
    try:
        settings = load_settings()
        settings["tutorial_guidance_sections"] = {
            key: bool(key in sections) for key in _TUTORIAL_GUIDANCE_SECTIONS
        }
        save_settings(settings)
    except Exception:
        pass


def _tutorial_section_preferences(prompt: str) -> tuple[set[str], bool]:
    text = str(prompt or "").lower()
    if (
        "just give me the step-by-step guidance" in text
        or "just step-by-step guidance" in text
        or "only step-by-step guidance" in text
        or "step-by-step guidance only" in text
    ):
        return {"steps"}, True

    sections = set(_default_tutorial_guidance_sections())
    explicit_preference = False
    if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(file|files|workspace|knowledge|internal|links?)\b", text):
        sections.discard("links")
        explicit_preference = True
    if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(external|official|github|reference|references|docs?)\b", text):
        sections.discard("references")
        explicit_preference = True
    if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(tool\s+steps?|terminal\s+steps?|ui\s+steps?|tool actions?)\b", text):
        sections.discard("tools")
        explicit_preference = True
    if re.search(r"\b(no|don't|do not|without|omit|skip)\b[^\n.]*\b(risk|validation|checkpoint|checks)\b", text):
        sections.discard("risks")
        explicit_preference = True

    if not sections:
        sections = {"steps"}
    return sections, explicit_preference


def _tutorial_mode_contract(prompt: str, sections: set[str] | None = None) -> str:
    if sections is None:
        sections, _ = _tutorial_section_preferences(prompt or "")
    lines = [
        "=== TUTORIAL / PREMIUM GUIDANCE MODE ===",
        "No code writes, no project mutations, and no host execution.",
        "Deliver a premium practical guide with the requested sections below.",
    ]
    if "understood" in sections:
        lines.append("1) What I understood")
    if "approach" in sections:
        lines.append("2) How I will approach it")
    if "now" in sections:
        lines.append("3) What I am doing now")
    if "steps" in sections:
        lines.extend(
            [
                "4) Step-by-step guidance",
                "   4.1) Discovery and evidence collection",
                "   4.2) API and extension-point selection",
                "   4.3) Implementation sketch + snippets",
                "   4.4) Validation + cleanup",
            ]
        )
    if "links" in sections:
        lines.extend(
            [
                "5) File and knowledge links",
                "   - Workspace files: absolute path links.",
                "   - Internal docs or notes: path links.",
            ]
        )
    if "references" in sections:
        lines.extend(
            [
                "6) External references",
                "   - Official docs and SDK URLs.",
                "   - GitHub links for comparable implementations.",
            ]
        )
    if "tools" in sections:
        lines.extend(
            [
                "7) Tool actions",
                "   - Concrete terminal/GUI steps to run next.",
            ]
        )
    if "risks" in sections:
        lines.extend(
            [
                "8) Risks, validation checks, and next checkpoint",
            ]
        )
    return "\n".join(lines)


def run_pipeline(
    prompt: str,
    *,
    project_root: str | None = None,
    dry_run: bool = False,
    tutorial_mode: bool = False,
    verbose: bool = True,
    llm_timeout: int | None = None,
    model_override: str | None = None,
    num_predict: int | None = None,
    max_prompt_retries: int = 3,
    approved_plan_id: str = "",
    plan_only: bool = False,
) -> dict:
    """
    Full headless pipeline for one prompt.
    Returns a result dict with keys: action, target, code, status, timings.
    """
    preview_only_requested = bool(re.search(
        r"\b(?:without|do\s+not|don't|never)\s+"
        r"(?:actually\s+)?(?:write|writing|save|saving|apply|applying|modify|"
        r"modifying)\b[^.!?\n]{0,60}\b(?:files?|disk|project|workspace)\b"
        r"|\b(?:return|show|output|generate)\s+(?:the\s+)?code\s+only\b",
        prompt,
        flags=re.IGNORECASE,
    ))
    tutorial_sections, tutorial_preference_update = _tutorial_section_preferences(
        prompt
    ) if tutorial_mode else (_default_tutorial_guidance_sections(), False)
    if tutorial_mode and tutorial_preference_update:
        _persist_tutorial_guidance_sections(tutorial_sections)
    effective_dry_run = bool(dry_run or preview_only_requested or tutorial_mode)
    explicit_project_root = bool(str(project_root or "").strip())
    effective_project_root = Path(
        project_root or TOOLS_ROOT
    ).expanduser().resolve()
    project_root_source = (
        "explicit_override"
        if explicit_project_root
        else "environment_toolsroot"
        if os.getenv("TOOLSROOT")
        else "discovered_tools_root"
    )
    if _is_forbidden_target_path(str(effective_project_root)):
        return {
            "status": "forbidden_project_root",
            "project_root": str(effective_project_root),
            "project_root_source": project_root_source,
            "errors": [
                _target_path_forbidden_error(str(effective_project_root))
            ],
        }
    project_root_created = False
    if explicit_project_root and not effective_project_root.exists():
        try:
            effective_project_root.mkdir(parents=True, exist_ok=False)
            project_root_created = True
        except OSError as exc:
            return {
                "status": "invalid_project_root",
                "project_root": str(effective_project_root),
                "project_root_source": project_root_source,
                "errors": [
                    "Could not create explicit project root "
                    f"{effective_project_root}: {type(exc).__name__}: {exc}"
                ],
            }
    if not effective_project_root.is_dir():
        return {
            "status": "invalid_project_root",
            "project_root": str(effective_project_root),
            "project_root_source": project_root_source,
            "errors": [
                "Project root does not exist or is not a directory: "
                f"{effective_project_root}"
            ],
        }
    if verbose:
        print(
            "PROJECT ROOT: "
            f"{effective_project_root} "
            f"[{project_root_source}"
            f"{'; created' if project_root_created else ''}]",
            flush=True,
        )

    if verbose:
        print("      Startup: selecting the active coding model", flush=True)
    model = model_override or _active_model()
    if verbose:
        print(f"      Startup: selected model {model}", flush=True)
    explicit_python_targets = {
        value.replace("\\", "/").casefold()
        for value in re.findall(
            r"(?<![A-Za-z0-9_])"
            r"((?:[A-Za-z]:[\\/])?[A-Za-z0-9_.-]+"
            r"(?:[\\/][A-Za-z0-9_.-]+)*\.py)\b",
            prompt,
            flags=re.IGNORECASE,
        )
    }
    if (
        _prompt_requires_multi_file_workflow(prompt)
        or _prompt_requires_companion_test(prompt)
        or len(explicit_python_targets) >= 2
    ):
        model = _focused_repair_model(model, 1)
    if verbose:
        print("      Startup: resolving the model call timeout", flush=True)
    resolved_llm_timeout = _coerce_timeout(llm_timeout, model)
    from tech_connector.services.prompt.artifact_contract_service import (
        requests_new_code_artifact_without_target,
    )

    if verbose:
        print("      Startup: classifying explicit file and module targets", flush=True)
    explicit_python_targets = list(dict.fromkeys(
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
    explicit_python_targets = [
        path
        for path in explicit_python_targets
        if not any(
            other != path and other.lower().endswith("/" + path.lower())
            for other in explicit_python_targets
        )
    ]
    explicit_module_targets = _explicit_dotted_module_targets(prompt)
    explicit_target = ""
    if len(explicit_python_targets) == 1:
        candidate = Path(explicit_python_targets[0])
        candidate = (
            candidate
            if candidate.is_absolute()
            else effective_project_root / candidate
        )
        try:
            resolved_candidate = candidate.resolve()
            resolved_candidate.relative_to(effective_project_root)
            explicit_target = str(resolved_candidate)
        except ValueError:
            explicit_target = ""
    elif not explicit_python_targets and len(explicit_module_targets) == 1:
        candidate = (
            effective_project_root
            / Path(*explicit_module_targets[0].split("."))
        ).with_suffix(".py")
        explicit_target = str(candidate.resolve())
    obvious_unnamed_creation = _is_obvious_unnamed_code_creation(
        prompt,
        has_explicit_target=bool(
            explicit_python_targets
            or explicit_module_targets
            or explicit_target
        ),
    )
    if obvious_unnamed_creation and not explicit_target:
        explicit_target = str(
            (
                effective_project_root
                / _inferred_python_filename(prompt)
            ).resolve()
        )
        if verbose:
            print(
                "      Inferred new-file target without model routing: "
                f"{explicit_target}",
                flush=True,
            )
    direct_targetless_artifact = (
        obvious_unnamed_creation
        or requests_new_code_artifact_without_target(prompt)
    )
    if verbose:
        print(
            "      Startup: constructing request routing "
            f"(direct_artifact={direct_targetless_artifact}, "
            f"python_targets={len(explicit_python_targets)})",
            flush=True,
        )
    engine = (
        None
        if direct_targetless_artifact or explicit_target or len(explicit_python_targets) > 1
        else RequestEngine()
    )
    if verbose:
        print("      Startup: request routing ready", flush=True)

    if verbose:
        print(f"\n{'='*70}")
        print(f"PROMPT : {prompt[:120]}{'...' if len(prompt)>120 else ''}")
        print(f"MODEL  : {model}")
        print(f"TIMEOUT: {resolved_llm_timeout}s")
        print(f"ROOT   : {effective_project_root}")
        print(f"{'='*70}")

    # Phase 1: Target resolution
    ctx = RequestContext(
        text=prompt,
        project_roots=(str(effective_project_root),),
        current_file_path="",
        active_tab="Chat",
        extras={
            "headless": True,
            "run_mode": "headless",
            "prompt_mode": "headless",
        },
    )
    t0 = time.perf_counter()
    res = (
        SimpleNamespace(
            action="send_raw",
            prompt=prompt,
            text="",
            metadata=(
                {"selected_target": explicit_target}
                if explicit_target
                else {}
            ),
        )
        if direct_targetless_artifact or explicit_target or len(explicit_python_targets) > 1
        else engine.process(ctx)
    )
    resolve_ms = (time.perf_counter() - t0) * 1000.0

    meta = res.metadata or {}
    original_target = (
        meta.get("selected_target")
        or meta.get("selected_file")
        or meta.get("target_file")
        or ""
    )

    def _normalized_project_target(raw_target: str) -> str:
        if not raw_target:
            return ""
        try:
            candidate = Path(raw_target)
            if candidate.is_absolute():
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(effective_project_root)
                    return str(resolved)
                except ValueError:
                    pass
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(TOOLS_ROOT.resolve())
                    return str(resolved)
                except ValueError:
                    pass
            if _is_forbidden_target_path(str(candidate)):
                if candidate.is_absolute():
                    parts = candidate.parts
                    for idx, part in enumerate(parts):
                        if part.lower() == "unreal_tools":
                            rel_parts = parts[idx:]
                            return str(TOOLS_ROOT.joinpath(*rel_parts))
                    return str(TOOLS_ROOT / candidate.name)
            if candidate.exists():
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(effective_project_root)
                    return str(resolved)
                except Exception:
                    pass

            if candidate.is_absolute():
                parts = candidate.parts
                for idx, part in enumerate(parts):
                    if part.lower() == "unreal_tools":
                        rel_parts = parts[idx:]
                        return str(effective_project_root.joinpath(*rel_parts))
                # Avoid mirroring a foreign absolute path; use its file name.
                return str(effective_project_root / candidate.name)

            if "." in raw_target and "/" not in raw_target and "\\" not in raw_target and not raw_target.lower().endswith(".py"):
                return str(
                    (effective_project_root / Path(*raw_target.split(".")))
                    .with_suffix(".py")
                )

            rel = candidate
            return str((effective_project_root / rel).resolve())
        except Exception:
            return str(effective_project_root / raw_target)

    target = _normalized_project_target(original_target)
    if original_target and target != original_target:
        if verbose:
            print(f"      Remapped target to project root: {target}")
            print(f"      Original target  : {original_target}")

    if not target:
        for line in (res.text or "").splitlines():
            if "Selected:" in line:
                target = _normalized_project_target(
                    line.split(":", 1)[1].strip()
                )
                break
    targetless_generated_artifact = (
        direct_targetless_artifact
        and (
            not target
            or (
                Path(target).exists()
                and Path(target).is_dir()
            )
        )
    )
    is_fetch_request = _is_fetch_style_request(prompt)
    if is_fetch_request:
        fetch_target, fetch_symbol = _find_best_fetch_target_and_symbol(
            prompt,
            meta,
            target,
            effective_project_root,
        )
        fetch_code = _render_fetch_code(fetch_target, fetch_symbol)
        if fetch_code:
            if verbose:
                print("[1/3] Fetch-style snippet resolved")
                print(f"      Fetch target : {fetch_target or '(inferred)'}")
                print(f"      Fetch symbol : {fetch_symbol or '(file preview)'}")
            return {
                "action": res.action,
                "target": fetch_target,
                "code": fetch_code,
                "status": "ok",
                "quality_passes": {},
                "timings": {"resolve_ms": resolve_ms, "total_ms": resolve_ms},
            }
    requires_shared_workflow = (
        _prompt_requires_multi_file_workflow(prompt)
        or targetless_generated_artifact
    )

    if verbose:
        print(f"[1/3] Target resolved in {resolve_ms:.0f}ms")
        print(f"      Action : {res.action}")
        print(f"      Target : {target or '(none)'}")
    if target and _is_forbidden_target_path(target):
        if verbose:
            print(f"      BLOCKED: {_target_path_forbidden_error(target)}")
        return {"action": res.action, "target": target, "code": "", "status": "blocked", "reason": _target_path_forbidden_error(target), "timings": {"resolve_ms": resolve_ms}}

    if (
        (res.action != "send_raw" or not res.prompt)
        and not requires_shared_workflow
    ):
        msg = (res.text or "").strip().splitlines()[0] if res.text else res.action
        if verbose:
            print(f"      Not a code-gen target: {msg}")
        return {"action": res.action, "target": target, "code": "", "status": "skipped",
                "reason": msg, "timings": {"resolve_ms": resolve_ms}}

    target_snapshot = ""
    target_is_new_file = False
    if target:
        try:
            target_path_obj = Path(target).resolve()
            target_is_new_file = (not target_path_obj.exists()) or target_path_obj.stat().st_size == 0
            target_snapshot = target_path_obj.read_text(encoding="utf-8") if target_path_obj.exists() else ""
        except Exception:
            target_snapshot = ""
            target_is_new_file = True
    explicit_single_file_scope = bool(
        re.search(
            r"\b(?:exactly|only)\s+one\s+(?:new\s+)?file\b|\bno other files\b",
            prompt,
            flags=re.IGNORECASE,
        )
    )
    companion_test_target = (
        _companion_test_target(target)
        if (
            target
            and not explicit_single_file_scope
            and _prompt_requires_companion_test(prompt)
        )
        else ""
    )
    target_module_path = _target_module_path(target) if target else ""
    requested_class_name = _requested_class_name(prompt)
    if companion_test_target:
        requires_shared_workflow = True
    if res.action == "send_raw" and res.prompt:
        requires_shared_workflow = True

    if requires_shared_workflow:
        from tech_connector.services.project_edit_workflow_service import (
            run_multi_file_project_edit_workflow,
        )

        if verbose:
            print("[2/3] Running shared project-edit workflow...")

        workflow_prompt = prompt
        if tutorial_mode:
            workflow_prompt = _tutorial_mode_contract(
                prompt,
                sections=tutorial_sections,
            ) + "\n\n" + workflow_prompt
        if target:
            workflow_prompt += (
                "\n\nARTIFACT OWNERSHIP CONTRACT:\n"
                f"- Production file: {target}\n"
            )
        if target and requested_class_name:
            workflow_prompt += (
                f"- The production file owns `{requested_class_name}`.\n"
            )
        if companion_test_target:
            workflow_prompt += (
                f"- Focused companion test file: {companion_test_target}\n"
                "- Generate and validate both files as one request.\n"
            )
            if target_module_path and requested_class_name:
                workflow_prompt += (
                    f"- The test imports it exactly with `from {target_module_path} "
                    f"import {requested_class_name}`.\n"
                )

        def _run_workflow_step(run_prompt: str) -> tuple:
            workflow_started = time.perf_counter()
            result = run_multi_file_project_edit_workflow(
                run_prompt,
                project_root=str(effective_project_root),
                active_path=target,
                selected_model=model,
                settings=load_settings(),
                timeout=resolved_llm_timeout,
                dry_run=effective_dry_run,
                max_attempts=max(5, max_prompt_retries),
                status_callback=(lambda message: print(f"      {message}")) if verbose else None,
                approved_plan_id=approved_plan_id,
                plan_only=plan_only,
                original_prompt=prompt,
            )
            return result, (time.perf_counter() - workflow_started) * 1000.0

        workflow, workflow_ms = _run_workflow_step(workflow_prompt)
        workflow_total_ms = workflow_ms
        stage_timings: list[dict] = list(workflow.timings)
        workflow_errors = []
        code = ""
        production_readiness = workflow.readiness_snapshot()
        quality_passes: dict[str, object] = {}
        repair_statuses = {
            "symbol_repair_stalled",
            "missing_symbol_repair_stalled",
            "symbol_repair_unmapped",
            "plan_correction_required",
            "repair_strategy_exhausted",
        }
        repair_passes = 0
        max_repair_passes = max(1, max_prompt_retries)

        while True:
            preview_changes = workflow.preview.changes if workflow.preview else []
            workflow_errors = [
                err
                for err in (workflow.errors or [])
                if _quality_owner_scope_match(
                    {"message": str(err)},
                    owner_hint=requested_class_name,
                    target_path=target or "",
                )
            ]

            production_readiness = workflow.readiness_snapshot()
            if isinstance(production_readiness, dict) and requested_class_name:
                filtered_validation = [
                    item
                    for item in production_readiness.get("validation", [])
                    if _quality_owner_scope_match(
                        {
                            "message": str(item.get("message") or ""),
                            "owner": str(item.get("owner") or ""),
                            "path": str(item.get("path") or ""),
                            "check": str(item.get("category") or item.get("check") or ""),
                            "command": str(item.get("command") or ""),
                        },
                        owner_hint=requested_class_name,
                        target_path=target or "",
                    )
                ]
                production_readiness = {
                    **production_readiness,
                    "validation": filtered_validation,
                }
                if filtered_validation:
                    production_readiness["ready"] = False
                elif production_readiness.get("ready", False):
                    production_readiness["ready"] = True

            code = (
                _preview_changes_to_code_output(preview_changes, target_path=target)
                or _working_file_output_from_raw(
                    workflow.candidate,
                    target,
                    target_snapshot,
                )
            )
            quality_passes = (
                {}
                if workflow.status == "plan_approval_required"
                else _quality_pass_summary(
                    workflow.preview.validation if workflow.preview else [],
                    fallback_errors=workflow_errors,
                    requested_owner=requested_class_name,
                    target_path=target or "",
                )
            )
            if requested_class_name and code is not None:
                code_has_target = re.search(
                    rf"\b{re.escape(requested_class_name)}\b",
                    code,
                )
                if not code_has_target:
                    fallback_code = _fallback_class_scaffold(
                        prompt,
                        requested_class_name,
                        is_new_file=target_is_new_file,
                    )
                    if fallback_code:
                        code = fallback_code

            if (
                workflow.status in repair_statuses
                and workflow.status != "plan_approval_required"
                and code
                and repair_statuses is not None
                and repair_passes < max_repair_passes - 1
            ):
                repair_passes += 1
                if verbose:
                    print(
                        f"[AUTO-REPAIR] Detected {workflow.status}; "
                        f"attempt {repair_passes}/{max_repair_passes - 1}"
                    )
                workflow_prompt = _repair_prompt(
                    prompt,
                    code,
                    requested_class_name,
                    workflow_errors,
                )
                if tutorial_mode:
                    workflow_prompt = _tutorial_mode_contract(
                        prompt,
                        sections=tutorial_sections,
                    ) + "\n\n" + workflow_prompt
                workflow, step_ms = _run_workflow_step(workflow_prompt)
                workflow_ms = step_ms
                workflow_total_ms += step_ms
                stage_timings.extend(workflow.timings)
                continue
            break

        final_status = (
            "ok"
            if (
                workflow.status not in {
                    "plan_correction_required",
                    "plan_approval_required",
                    "symbol_repair_stalled",
                    "missing_symbol_repair_stalled",
                    "symbol_repair_unmapped",
                    "repair_strategy_exhausted",
                }
                and (not workflow_errors)
            )
            else workflow.status
        )
        if verbose:
            print(f"[3/3] Shared workflow status: {final_status}")
            for timing in stage_timings:
                print(
                    f"      {timing.get('label', timing.get('stage'))}: "
                    f"{float(timing.get('elapsed_ms') or 0):.0f}ms"
                )
        return {
            "action": res.action,
            "target": target,
            "code": code,
            "raw_llm": workflow.candidate,
            "status": final_status,
            "errors": workflow_errors,
            "quality_passes": quality_passes,
            "stage_timings": stage_timings,
            "implementation_plan": workflow.implementation_plan,
            "approval_id": workflow.approval_id,
            "production_readiness": production_readiness,
            "preview": {
                "status": workflow.preview.status if workflow.preview else "not_run",
                "changes": len(preview_changes),
                "errors": workflow_errors,
            },
            "timings": {
                "resolve_ms": resolve_ms,
                "llm_ms": workflow_total_ms,
                "total_ms": resolve_ms + workflow_total_ms,
            },
        }

    return {
        "action": res.action,
        "target": target,
        "code": "",
        "status": "routing_invariant_failed",
        "errors": [
            "A coding request reached no shared project-edit workflow. "
            "Legacy generation is disabled; correct the request classification or target resolution."
        ],
        "production_readiness": {
            "ready": False,
            "status": "routing_invariant_failed",
            "summary": "No code was generated because the canonical workflow was not selected.",
        },
        "timings": {"resolve_ms": resolve_ms, "total_ms": resolve_ms},
    }

# ---------------------------------------------------------------------------
# Benchmark cases
# ---------------------------------------------------------------------------

BENCHMARK_CASES = [
    {
        "id": "B1",
        "label": "Unreal Shader Generator (new nested file)",
        "prompt": (
            "add a ProceduralHLSLShaderGenerator class and MaterialPresetContainer dataclass "
            "in unreal_tools.shaders.procedural_generator. "
            "ProceduralHLSLShaderGenerator takes material_instance, hlsl_source, parameter_bindings "
            "and compiles hlsl_source into an Unreal CustomExpression node dict via a compile() method. "
            "MaterialPresetContainer stores named presets as a dict with load(path) and save(path) methods."
        ),
    },
    {
        "id": "B2",
        "label": "Maya Rigging - two joint placer functions (existing file)",
        "prompt": (
            "add auto_place_biped_finger_joints and auto_place_biped_toe_joints functions "
            "in maya_tools.Rigging.joint_placer, each taking hand_mesh and finger_count params. "
            "auto_place_biped_finger_joints uses cmds.xform to position joints along finger bones, "
            "auto_place_biped_toe_joints mirrors the logic for toes."
        ),
    },
    {
        "id": "B3",
        "label": "Custom Qt Mocap Browser Dialog (new UI class)",
        "prompt": (
            "add an AdvancedMocapSequenceBrowserDialog class in custom_qt.mocap_browser_dialog "
            "inheriting from ModelessContinueDialog. Include: QLineEdit search filter, "
            "QListWidget Top 5 candidate sidebar, QTabWidget with README QTextBrowser tab and "
            "QTreeWidget file tree tab, GitHub dark mode stylesheet, QLabel auth status banner, "
            "ListProgressBar ingestion tracker. Add start_ingestion() and _filter_candidates() methods."
        ),
    },
    {
        "id": "B4",
        "label": "Unreal Assets - find + batch_rename functions (existing file)",
        "prompt": (
            "add find_shader_material_assets and batch_rename_assets functions in unreal_tools.assets. "
            "find_shader_material_assets(asset_folder, material_preset) uses unreal.AssetRegistry "
            "to find matching UMaterial assets. "
            "batch_rename_assets(asset_list, name_prefix) renames each using unreal.EditorUtilityLibrary."
        ),
    },
    {
        "id": "B5",
        "label": "CrossDCC Asset Sync (brand-new cross-package module)",
        "prompt": (
            "add a CrossDCCAssetSyncManager class in dcc_intelligence.asset_pipeline.sync_adapter "
            "inheriting from ModelessContinueDialog with Unreal FBX export via unreal.AssetExportTask, "
            "Maya scene FBX import via cmds.file, live ListProgressBar streaming, and async socket broadcast."
        ),
    },
]


def run_benchmark(
    dry_run: bool = False,
    tutorial_mode: bool = False,
    approved_plan_id: str = "",
    plan_only: bool = False,
    llm_timeout: int | None = None,
    model_override: str | None = None,
    num_predict: int | None = None,
) -> None:
    print("=" * 80)
    print("HEADLESS CODE GENERATION BENCHMARK")
    print(f"dry_run={dry_run}")
    print(f"tutorial_mode={tutorial_mode}")
    print(f"llm_timeout={llm_timeout}")
    print("=" * 80)

    summary = []
    for case in BENCHMARK_CASES:
        print(f"\n\n{'#'*80}")
        print(f"  [{case['id']}] {case['label']}")
        print(f"{'#'*80}")
        result = run_pipeline(
            case["prompt"],
            dry_run=dry_run,
            tutorial_mode=tutorial_mode,
            approved_plan_id=approved_plan_id,
            plan_only=plan_only,
            llm_timeout=llm_timeout,
            model_override=model_override,
            num_predict=num_predict,
        )
        summary.append((case["id"], case["label"], result))

        if result["status"] == "ok":
            print(f"\n{'='*60}")
            print("GENERATED CODE:")
            print(f"{'='*60}")
            print(result["code"])

    print(f"\n\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    for cid, label, r in summary:
        t = r["timings"]
        total = t.get("total_ms", t.get("resolve_ms", 0))
        print(f"[{cid}] {label[:50]:<50} {r['status']:10} {total:.0f}ms  â†’ {r.get('target','')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Headless Tech Connector pipeline")
    parser.add_argument("prompt", nargs="?", help="Prompt to run")
    parser.add_argument("--dry-run", action="store_true", help="Resolve + generate but don't write to disk")
    parser.add_argument("--tutorial", action="store_true", help="Run in tutorial/guidance mode (no mutations, no execution)")
    parser.add_argument("--benchmark", action="store_true", help="Run all benchmark cases")
    parser.add_argument("--model", default="", help="Override model (default: auto-select)")
    parser.add_argument("--num-predict", type=int, default=None, help="Ollama max generated tokens")
    parser.add_argument(
        "--project-root",
        default="",
        help=(
            "Workspace root for target resolution, generation, validation, "
            "and writes. Explicit missing directories are created. "
            "Default: configured TOOLSROOT or the dynamically discovered "
            "tools root."
        ),
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Build and display the implementation plan without generating code",
    )
    parser.add_argument(
        "--approve-plan",
        default="",
        help="Approve an exact implementation-plan hash and continue generation",
    )
    parser.add_argument(
        "--auto-approve-plan",
        action="store_true",
        help=(
            "For unattended testing, approve the exact plan produced by this "
            "process and continue generation without a second CLI invocation"
        ),
    )
    parser.add_argument(
        "--llm-timeout",
        type=int,
        default=None,
        help="LLM call timeout in seconds (adaptive by model when omitted)",
    )
    args = parser.parse_args()
    if args.plan_only and args.auto_approve_plan:
        parser.error("--plan-only cannot be combined with --auto-approve-plan")
    if args.approve_plan and args.auto_approve_plan:
        parser.error("--approve-plan cannot be combined with --auto-approve-plan")
    if args.benchmark and args.auto_approve_plan:
        parser.error("--auto-approve-plan is only supported for one prompt")

    if args.benchmark:
        run_benchmark(
            dry_run=args.dry_run,
            tutorial_mode=args.tutorial,
            llm_timeout=args.llm_timeout,
            model_override=args.model or None,
            num_predict=args.num_predict,
            approved_plan_id=args.approve_plan,
            plan_only=args.plan_only,
        )
    elif args.prompt:
        result = run_pipeline(
            args.prompt,
            project_root=args.project_root or None,
            dry_run=args.dry_run,
            tutorial_mode=args.tutorial,
            llm_timeout=args.llm_timeout,
            model_override=args.model or None,
            num_predict=args.num_predict,
            approved_plan_id=args.approve_plan,
            plan_only=args.plan_only,
        )
        if (
            args.auto_approve_plan
            and result.get("status") == "plan_approval_required"
        ):
            approval_id = str(result.get("approval_id") or "").strip()
            if not approval_id:
                result = {
                    **result,
                    "status": "plan_auto_approval_failed",
                    "errors": [
                        "The planner requested approval without returning an "
                        "exact approval ID."
                    ],
                }
            else:
                print(
                    "\n[AUTO-APPROVAL] Continuing with exact plan "
                    f"{approval_id[:12]}..."
                )
                result = run_pipeline(
                    args.prompt,
                    project_root=args.project_root or None,
                    dry_run=args.dry_run,
                    tutorial_mode=args.tutorial,
                    llm_timeout=args.llm_timeout,
                    model_override=args.model or None,
                    num_predict=args.num_predict,
                    approved_plan_id=approval_id,
                    plan_only=False,
                )
        print(f"\n{'='*60}\nRESULT:\n{'='*60}")
        print(f"status={result.get('status')}")
        if result.get("implementation_plan"):
            print(f"\n{'='*60}\nIMPLEMENTATION PLAN:\n{'='*60}")
            print(json.dumps(result["implementation_plan"], indent=2, ensure_ascii=True))
            print(f"\nAPPROVAL ID: {result.get('approval_id')}")
        if result.get("code"):
            print(f"\n{'='*60}\nGENERATED CODE:\n{'='*60}")
            print(result["code"])
        if result.get("quality_passes"):
            print(f"\n{'='*60}\nQUALITY PASSES:\n{'='*60}")
            print(result["quality_passes"])
        if result.get("production_readiness"):
            print(f"\n{'='*60}\nPRODUCTION READINESS:\n{'='*60}")
            print(
                json.dumps(
                    result["production_readiness"],
                    indent=2,
                    ensure_ascii=True,
                )
            )
        if result.get("errors"):
            print(f"\n{'='*60}\nERRORS:\n{'='*60}")
            print(result["errors"])
        if result.get("stage_timings"):
            print(f"\n{'='*60}\nSTAGE TIMINGS:\n{'='*60}")
            for timing in result["stage_timings"]:
                print(
                    f"{timing.get('label', timing.get('stage'))}: "
                    f"{float(timing.get('elapsed_ms') or 0):.0f}ms"
                )
        if result.get("status") not in {
            "ok",
            "preview_ok",
            "plan_approval_required",
        }:
            raise SystemExit(1)
    else:
        parser.print_help()


