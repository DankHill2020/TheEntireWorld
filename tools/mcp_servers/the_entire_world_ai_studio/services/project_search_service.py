"""Project-wide query routing and indexed retrieval for editor workflows."""

from __future__ import annotations

import re
import sqlite3
import ast
from pathlib import Path


def _connect_index_readonly(db_path: Path, timeout: int | float = 5) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, timeout=timeout, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _active_project_roots(active_path: str | None = None) -> list[str]:
    roots: list[str] = []
    try:
        from services.settings_service import load_settings
        from models.project import project_roots
        settings = load_settings()
        roots.extend(project_roots(settings))
    except Exception:
        pass

    if active_path:
        try:
            p = Path(active_path).expanduser().resolve()
            start = p.parent if p.is_file() else p
            probe = start
            while probe != probe.parent:
                if (probe / ".git").exists() or (probe / "app").exists() or (probe / "pyproject.toml").exists():
                    val = str(probe)
                    if val not in roots:
                        roots.insert(0, val)
                    break
                probe = probe.parent
        except Exception:
            pass
    return roots


def detect_search_scope(question: str) -> str:
    lower = (question or "").lower()
    if any(x in lower for x in ("everything", "all indexed", "entire indexed", "global search", "including stdlib", "including engine", "including unreal", "including maya")):
        return "all"
    if any(x in lower for x in ("unreal engine", "engine source")):
        return "engine"
    if any(x in lower for x in (" in unreal", " for unreal", "unreal project", "ue5", "ue4")):
        return "unreal_project"
    if "maya install" in lower or "maya installation" in lower:
        return "maya"
    if any(x in lower for x in (" in maya", " for maya", "maya project")):
        return "maya_project"
    return "project"


class ProjectSearchMode:
    USAGE = "usage"
    IMPORT = "import"
    CALL = "call"
    CLASS = "class"
    SYMBOL = "symbol"
    DEPENDENCIES = "dependencies"
    TEXT = "text"
    ARCHITECTURE = "architecture"
    UNUSED_FILES = "unused_files"
    UNUSED_IMPORTS = "unused_imports"
    DEPENDENTS = "dependents"
    TARGET_EDIT = "target_edit"
    UNKNOWN = "usage"


_PROJECT_SCOPE_HINTS = (
    "project", "codebase", "whole repo", "entire repo", "entire project",
    "all files", "every file", "throughout", "everywhere", "anywhere",
    "across the project", "across this project", "find every", "find all",
    "every class", "all classes", "every function", "all functions",
    "where is", "where are", "used by", "callers", "usages", "references",
    "dependencies", "dependency graph", "imports", "import graph",
    "class", "classes", "function", "functions", "method", "methods", "symbol", "symbols",
    "file", "python file", "py file",
    ".py", "arguments", "args", "required",
)


def is_project_scope_request(question: str) -> bool:
    lower = (question or "").lower()
    return any(hint in lower for hint in _PROJECT_SCOPE_HINTS)


_EXCLUDED_REL_PREFIXES = (
    ".ai_studio/",
    ".continue/",
    ".git/",
    ".github/",
    ".project_ai/",
    "external_tools/",
    ".venv/",
    "venv/",
    "__pycache__/",
)


def _is_excluded_index_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    if re.search(r"/python\d*/lib/", normalized) or re.search(r"/python\d+/lib/", normalized):
        return True
    if "/site-packages/" in normalized or "/dist-packages/" in normalized:
        return True
    if re.search(r"^[a-z]:/program files/python\d*/lib/", normalized):
        return True
    if normalized.startswith("lib/") and "depot/tools/" not in normalized:
        return True
    return any(
        normalized.startswith(prefix)
        or f"/{prefix}" in normalized
        or f"/tools/{prefix}" in normalized
        for prefix in _EXCLUDED_REL_PREFIXES
    )


def _sql_placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(max(1, int(count or 1))))


def _rel_for_sort(row: dict) -> str:
    return str(row.get("rel_path") or row.get("path") or "").replace("\\", "/").lower()


def _is_user_source_row(row: dict) -> bool:
    rel = _rel_for_sort(row)
    if not rel:
        return False
    path = str(row.get("path") or "").replace("\\", "/").lower()
    source_scope = str(row.get("source_scope") or "project").lower()
    if source_scope not in {"", "project"}:
        return False
    return not _is_excluded_index_path(rel) and not _is_excluded_index_path(path)


def _filter_index_usage_results(results: dict, *, keep_imports: bool = False) -> dict:
    """Drop dependency/runtime rows before formatting evidence for prompts."""
    if not isinstance(results, dict):
        return results
    filtered = dict(results)
    row_keys = (
        "symbols",
        "chunks",
        "imports",
        "calls",
        "exact_symbols",
        "exact_chunks",
        "exact_imports",
        "exact_calls",
        "related_symbols",
        "related_chunks",
    )
    for key in row_keys:
        rows = filtered.get(key)
        if isinstance(rows, list):
            if "import" in key and not keep_imports:
                filtered[key] = []
            else:
                filtered[key] = [row for row in rows if not isinstance(row, dict) or _is_user_source_row(row)]
    return filtered


_PROJECT_SEARCH_STOPWORDS = {
    "inspect",
    "inspection",
    "identify",
    "determine",
    "report",
    "review",
    "analyze",
    "analyse",
    "explain",
    "project",
    "current",
    "existing",
    "relevant",
    "system",
    "systems",
    "anything",
    "before",
    "making",
    "changes",
    "change",
    "edit",
    "editing",
    "edits",
    "without",
    "with",
    "and",
    "the",
    "for",
    "not",
    "do",
    "that",
    "this",
    "what",
    "where",
    "which",
    "should",
    "would",
    "could",
    "please",
    "find",
}


def _clean_index_query(question: str) -> str:
    terms = []
    for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", question or ""):
        lowered = term.lower()
        if len(lowered) < 3 or lowered in _PROJECT_SEARCH_STOPWORDS:
            continue
        terms.append(term)
    return " ".join(terms) or (question or "")


def _project_file_rows(active_path: str | None = None, limit: int = 200, ext: str | None = None) -> list[dict]:
    """Return indexed first-party project files in deterministic path order."""
    try:
        from models.constants import V2_DB
    except Exception:
        return []
    if not V2_DB.exists():
        return []
    project_roots = _active_project_roots(active_path)
    row_limit = max(1, min(int(limit or 200), 2000))
    db_limit = 2000 if ext else row_limit

    def query_rows(conn, include_roots: bool) -> list[dict]:
        where = ["COALESCE(source_scope, 'project') IN ('project', 'external_tools')"]
        params: list[object] = []
        if include_roots and project_roots:
            root_clauses = []
            for root in project_roots:
                root_clauses.append("(root = ? OR path LIKE ?)")
                params.extend([root, str(Path(root)) + "%"])
            where.append("(" + " OR ".join(root_clauses) + ")")
        if ext:
            where.append("lower(ext) = ?")
            params.append(ext.lower() if ext.startswith(".") else f".{ext.lower()}")
        params.append(db_limit)
        rows = conn.execute(
            f"""
            SELECT path, rel_path, root, ext, size, indexed_at
            FROM files
            WHERE {' AND '.join(where)}
            ORDER BY lower(rel_path), lower(path)
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows if _is_user_source_row(dict(row))]

    try:
        with _connect_index_readonly(V2_DB, timeout=5) as conn:
            rows = query_rows(conn, include_roots=True)
            return rows or query_rows(conn, include_roots=False)
    except Exception:
        return []


def _file_hint_from_question(question: str, active_path: str | None = None) -> str:
    text = question or ""
    explicit = re.search(r"\b([A-Za-z_][A-Za-z0-9_./\\-]*\.[A-Za-z0-9_]+)\b", text)
    if explicit:
        return explicit.group(1)
    py_spaced = re.search(r"\b([A-Za-z_][A-Za-z0-9_./\\-]*)\s+(?:py|python)\s+file\b", text, re.IGNORECASE)
    if py_spaced:
        return py_spaced.group(1).rstrip("./\\") + ".py"
    if active_path and re.search(
        r"\b(this|current|active|selected|open)\s+(?:py|python)?\s*file\b",
        text,
        re.IGNORECASE,
    ):
        return str(active_path)
    return ""


def _resolve_file_hint_path(active_path: str | None, file_hint: str) -> Path | None:
    candidates: list[Path] = []
    if file_hint:
        hinted = Path(str(file_hint))
        candidates.append(hinted)
    if active_path:
        active = Path(str(active_path))
        candidates.append(active)
        if file_hint:
            wanted = str(file_hint).replace("\\", "/").lower()
            wanted_name = Path(wanted).name.lower()
            active_norm = str(active).replace("\\", "/").lower()
            if active_norm.endswith(wanted) or active.name.lower() == wanted_name:
                return active
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except Exception:
            continue
    return None


def _symbol_rows_for_requested_file(active_path: str | None, file_hint: str, *, limit: int = 80) -> tuple[str, list[dict], str]:
    resolved = _resolve_file_hint_path(active_path, file_hint)
    if resolved:
        ast_rows = _active_file_symbol_rows(str(resolved), limit=limit)
        if ast_rows:
            return str(resolved), ast_rows, "file AST fallback"

    row = _matching_file_row(active_path, file_hint)
    if row:
        rel = str(row.get("rel_path") or row.get("path") or file_hint)
        file_path = str(row.get("path") or "")
        rows = _symbol_rows_for_file(file_path, limit=limit)
        if rows:
            return rel, rows, "local project knowledge index"
        ast_rows = _active_file_symbol_rows(file_path, limit=limit)
        if ast_rows:
            return rel, ast_rows, "file AST fallback"

    return file_hint, [], ""


def _matching_file_row(active_path: str | None, file_hint: str) -> dict | None:
    if not file_hint:
        return None
    wanted = file_hint.replace("\\", "/").lower()
    wanted_name = Path(wanted).name
    active_resolved = ""
    if active_path:
        try:
            active_resolved = str(Path(active_path).expanduser().resolve()).replace("\\", "/").lower()
        except Exception:
            active_resolved = str(active_path).replace("\\", "/").lower()
    for row in _project_file_rows(active_path, limit=2000, ext=Path(wanted_name).suffix or None):
        rel = str(row.get("rel_path") or "").replace("\\", "/").lower()
        path = str(row.get("path") or "").replace("\\", "/").lower()
        if active_resolved and path == active_resolved:
            return row
        if rel.endswith(wanted) or path.endswith(wanted) or Path(rel).name.lower() == wanted_name:
            return row
    try:
        from models.constants import V2_DB
        if V2_DB.exists():
            with _connect_index_readonly(V2_DB, timeout=2) as conn:
                suffix = Path(wanted_name).suffix.lower()
                rows = conn.execute(
                    """
                    SELECT path, rel_path, root, ext, size, indexed_at
                    FROM files
                    WHERE lower(ext) = ?
                    ORDER BY lower(rel_path), lower(path)
                    LIMIT 5000
                    """,
                    [suffix],
                ).fetchall()
                for row in rows:
                    data = dict(row)
                    rel = str(data.get("rel_path") or "").replace("\\", "/").lower()
                    path = str(data.get("path") or "").replace("\\", "/").lower()
                    if _is_user_source_row(data) and (
                        (active_resolved and path == active_resolved)
                        or rel.endswith(wanted)
                        or path.endswith(wanted)
                        or rel.endswith("/" + wanted_name)
                        or path.endswith("/" + wanted_name)
                    ):
                        return data
    except Exception:
        pass
    return None


def _symbol_rows_for_file(file_path: str, *, kinds: tuple[str, ...] = ("function", "method"), limit: int = 20) -> list[dict]:
    try:
        from models.constants import V2_DB
    except Exception:
        return []
    if not V2_DB.exists() or not file_path:
        return []
    placeholders = ", ".join("?" for _ in kinds)
    try:
        with _connect_index_readonly(V2_DB, timeout=2) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    f.path,
                    f.rel_path,
                    s.name,
                    s.qualname,
                    s.kind,
                    s.signature,
                    s.start_line,
                    s.end_line,
                    s.docstring
                FROM symbols s
                JOIN files f ON f.id = s.file_id
                WHERE f.path = ?
                  AND lower(s.kind) IN ({placeholders})
                ORDER BY COALESCE(s.start_line, 999999), lower(s.qualname)
                LIMIT ?
                """,
                [file_path, *[kind.lower() for kind in kinds], int(limit)],
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def _signature_from_ast(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    names = [arg.arg for arg in [*node.args.posonlyargs, *node.args.args]]
    defaults = [None] * (len(names) - len(node.args.defaults)) + list(node.args.defaults)
    parts: list[str] = []
    for name, default in zip(names, defaults):
        if default is None:
            parts.append(name)
        else:
            parts.append(f"{name}=...")
    if node.args.vararg:
        parts.append("*" + node.args.vararg.arg)
    elif node.args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults or []):
        parts.append(arg.arg if default is None else f"{arg.arg}=...")
    if node.args.kwarg:
        parts.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(parts)})"


def _active_file_symbol_rows(active_path: str | None, *, limit: int = 80) -> list[dict]:
    if not active_path:
        return []
    path = Path(str(active_path))
    if path.suffix.lower() != ".py" or not path.exists() or not path.is_file():
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return []

    rows: list[dict] = []
    parent_stack: list[tuple[str, str]] = []

    def visit(node):
        if isinstance(node, ast.ClassDef):
            parent_stack.append(("class", node.name))
            for child in node.body:
                visit(child)
            parent_stack.pop()
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent_names = [name for _kind, name in parent_stack]
            qualname = ".".join([*parent_names, node.name]) if parent_names else node.name
            is_method = bool(parent_stack and parent_stack[-1][0] == "class")
            rows.append(
                {
                    "path": str(path),
                    "rel_path": str(path),
                    "source_scope": "project",
                    "name": node.name,
                    "qualname": qualname,
                    "kind": "method" if is_method else "function",
                    "scope_depth": len(parent_stack),
                    "signature": _signature_from_ast(node),
                    "start_line": getattr(node, "lineno", None),
                    "end_line": getattr(node, "end_lineno", None),
                    "docstring": ast.get_docstring(node) or "",
                }
            )
            parent_stack.append(("function", node.name))
            for child in node.body:
                visit(child)
            parent_stack.pop()
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return rows[: max(1, int(limit or 80))]


def _required_args_from_signature(signature: str) -> list[str]:
    match = re.search(r"\((.*)\)", signature or "")
    if not match:
        return []
    required: list[str] = []
    for raw in match.group(1).split(","):
        part = raw.strip()
        if not part or part in {"self", "cls", "*", "/"} or part.startswith("**") or part.startswith("*"):
            continue
        name = part.split(":", 1)[0].split("=", 1)[0].strip()
        if "=" not in part and name:
            required.append(name)
    return required


def _function_location_terms(question: str, active_path: str | None = None) -> list[str]:
    text = question or ""
    lower = text.lower()
    query_lower = re.split(
        r"\b(?:return|respond|format|output|do not|don't|without)\b",
        lower,
        maxsplit=1,
    )[0].strip() or lower
    stop = {
        "what", "which", "where", "file", "files", "has", "have", "contains", "contain",
        "function", "functions", "method", "methods", "for", "to", "that", "does", "do",
        "a", "an", "the", "my", "project", "codebase", "path", "located", "location",
        "with", "in", "inside", "maya", "unreal", "blender", "houdini", "motionbuilder",
        "can", "could", "would", "i", "use", "using", "name", "names", "and", "paths",
        "only", "edit", "anything", "return", "respond", "format", "output",
        "should", "from", "existing", "exist", "give", "me",
    }
    phrase = ""
    match = re.search(
        r"\b(?:function|method)\s+(?:for|to|that|which)?\s*(?:is\s+)?([A-Za-z0-9_ -]+)",
        query_lower,
    )
    if match:
        phrase = match.group(1)
    if not phrase:
        match = re.search(r"\b(?:file|path)\s+(?:for|to)\s+([A-Za-z_][A-Za-z0-9_ -]+)", query_lower)
        if match:
            phrase = match.group(1)
    if not phrase:
        phrase = query_lower

    terms: list[str] = []

    def add(term: str):
        term = (term or "").strip("_ ").lower()
        if len(term) < 3 or term in stop or term in terms:
            return
        terms.append(term)

    for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", phrase):
        word = raw.lower()
        if word.endswith("ing") and len(word) > 5:
            word = word[:-3]
            if word.endswith("at"):
                word += "e"
            elif word == "creat":
                word = "create"
            elif word == "mapp":
                word = "mapping"
        add(word)

    generic_action_terms = {"create", "make", "build", "generate", "add", "setup", "set_up"}
    explicit_names = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+\b", text)
    for name in explicit_names:
        add(name)
    try:
        from services.capability_service import expand_terms
        context = " ".join(str(part or "") for part in (question, active_path))
        return [term for term in expand_terms(terms, context=context) if len(term) >= 3 and term not in stop]
    except Exception:
        return terms


def _function_location_active_scope_requested(question: str) -> bool:
    lower = (question or "").lower()
    return bool(
        re.search(r"\b(this|current|active|open|selected)\s+(?:file|script|module)\b", lower)
        or re.search(r"\bin\s+(?:this|current|active|open|selected)\s+(?:file|script|module)\b", lower)
        or re.search(r"\bfunctions?\s+are\s+in\s+this\s+file\b", lower)
    )


def _function_location_domain_hints(question: str) -> set[str]:
    lower = (question or "").lower()
    hints: set[str] = set()
    for host in ("maya", "unreal", "blender", "houdini", "motionbuilder", "substance"):
        if host in lower:
            hints.add(host)
    if re.search(r"\brig(?:ging)?\b", lower):
        hints.add("rigging")
    if re.search(r"\bcontrol|ctrl\b", lower):
        hints.add("control")
    return hints


def _answer_function_location_question(question: str, active_path: str | None = None) -> str | None:
    lower = (question or "").lower()
    if not (
        re.search(r"\b(file|path|where|which|what)\b", lower)
        or re.search(r"\bis\s+there\s+(?:a\s+)?(?:function|method|callable)\b", lower)
    ):
        return None
    if not (
        re.search(r"\b(function|method|callable)\b", lower)
        or (
            re.search(r"\b(file|path|where|which|what)\b", lower)
            and re.search(r"\b(create|creating|make|making|build|building)\b", lower)
        )
    ):
        return None
    terms = _function_location_terms(question, active_path=active_path)
    if not terms:
        return None
    rows = _function_location_rows(terms, active_path=active_path, question=question, limit=8)
    if not rows:
        return (
            "I could not find an indexed project function matching that description.\n\n"
            "Source: local project knowledge index."
        )
    if _should_clarify_function_location(question, rows):
        lines = [
            "I found a few plausible project functions, but the request is ambiguous.",
            "",
            "Likely matches:",
        ]
        for idx, row in enumerate(rows[:5], 1):
            signature = row.get("signature") or row.get("qualname") or row.get("name") or ""
            rel = row.get("rel_path") or row.get("path") or ""
            line = row.get("start_line")
            where = f"{rel}" + (f":{line}" if line else "")
            lines.append(f"{idx}. `{signature}` - `{where}`")
        lines.extend(
            [
                "",
                "Reply with the function name or a little more context, and I will use that.",
                "",
                "Source: local project knowledge index.",
            ]
        )
        return "\n".join(lines)
    best = rows[0]
    rel = best.get("rel_path") or best.get("path") or ""
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = str(row.get("rel_path") or row.get("path") or "")
        grouped.setdefault(key, []).append(row)
    lines = [
        f"Best match: `{rel}`",
        "",
        "Matching indexed functions:",
    ]
    shown = 0
    for file_path, file_rows in grouped.items():
        shown += 1
        lines.append(f"{shown}. `{file_path}`")
        for row in file_rows[:4]:
            signature = row.get("signature") or row.get("qualname") or row.get("name") or ""
            line = row.get("start_line")
            lines.append(f"   - `{signature}`" + (f" on line `{line}`" if line else ""))
        if shown >= 3:
            break
    lines.extend(["", "Source: local project knowledge index."])
    lines.append("Next: ask `show functions in that file` or use Open in Editor on the matched path.")
    return "\n".join(lines)


def _should_clarify_function_location(question: str, rows: list[dict]) -> bool:
    if len(rows) < 2:
        return False
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+\b", question or ""):
        return False
    scores = [int(row.get("match_score") or 0) for row in rows[:3]]
    if len(scores) >= 2 and scores[0] - scores[1] <= 15:
        return True
    if len(scores) >= 3 and scores[0] < 320 and scores[0] - scores[2] <= 35:
        return True
    return False


def _dedupe_function_location_rows(rows: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    for row in rows:
        path = str(row.get("rel_path") or row.get("path") or "").replace("\\", "/").lower()
        if len(path) > 2 and path[1] == ":":
            marker = "/maya_tools/"
            if marker in path:
                path = "maya_tools/" + path.split(marker, 1)[1]
        key = (
            str(row.get("name") or row.get("qualname") or "").lower(),
            path,
            int(row.get("start_line") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _function_location_rows(
    terms: list[str],
    active_path: str | None = None,
    *,
    question: str = "",
    limit: int = 8,
) -> list[dict]:
    active_resolved = ""
    if active_path:
        try:
            active_resolved = str(Path(active_path).expanduser().resolve())
        except Exception:
            active_resolved = str(active_path)
    query_terms = [term for term in terms if term]
    active_scope_requested = _function_location_active_scope_requested(question)
    domain_hints = _function_location_domain_hints(question)
    active_rows: list[dict] = []
    for row in _active_file_symbol_rows(active_path, limit=80):
        if row.get("scope_depth") not in (None, 0) and str(row.get("kind") or "").lower() != "method":
            continue
        item = dict(row)
        base_score = _function_location_score(item, query_terms, active_resolved, domain_hints=domain_hints)
        if base_score <= 0:
            continue
        item["match_score"] = base_score + (220 if active_scope_requested else 0)
        if int(item.get("match_score") or 0) > 0:
            active_rows.append(item)
    snake_terms = [term for term in query_terms if "_" in term]
    if active_resolved and snake_terms and any(term in active_resolved.lower() for term in snake_terms):
        for row in _symbol_rows_for_file(active_resolved, limit=20):
            item = dict(row)
            item.setdefault("rel_path", item.get("path"))
            item["match_score"] = _function_location_score(item, query_terms, active_resolved, domain_hints=domain_hints) + 250
            active_rows.append(item)
        if active_rows:
            active_rows.sort(key=lambda row: (-int(row.get("match_score") or 0), int(row.get("start_line") or 0)))
            return _dedupe_function_location_rows(active_rows)[: max(1, int(limit or 8))]
    try:
        from models.constants import V2_DB
    except Exception:
        V2_DB = None
    if not V2_DB or not V2_DB.exists():
        active_rows.sort(key=lambda row: (-int(row.get("match_score") or 0), int(row.get("start_line") or 0)))
        return _dedupe_function_location_rows(active_rows)[: max(1, int(limit or 8))]
    clauses = []
    params: list[object] = []
    for term in query_terms[:6]:
        like = f"%{term}%"
        clauses.append(
            "(lower(s.name) LIKE ? OR lower(s.qualname) LIKE ? OR lower(s.signature) LIKE ? "
            "OR lower(s.docstring) LIKE ?)"
        )
        params.extend([like, like, like, like])
    if not clauses:
        return []
    try:
        with _connect_index_readonly(V2_DB, timeout=2) as conn:
            rows = conn.execute(
                f"""
                SELECT
                    f.path,
                    f.rel_path,
                    f.source_scope,
                    s.name,
                    s.qualname,
                    s.kind,
                    s.signature,
                    s.start_line,
                    s.docstring
                FROM symbols s
                JOIN files f ON f.id = s.file_id
                WHERE lower(s.kind) IN ('function', 'method')
                  AND ({' OR '.join(clauses)})
                ORDER BY
                    CASE
                        WHEN lower(s.name) IN ({_sql_placeholders(len([t for t in query_terms if '_' in t]) or 1)})
                        THEN 0 ELSE 1
                    END,
                    lower(f.path),
                    COALESCE(s.start_line, 999999)
                LIMIT 5000
                """,
                [
                    *params,
                    *([t for t in query_terms if "_" in t] or [""]),
                ],
            ).fetchall()
    except Exception:
        return []

    scored = []
    scored.extend(active_rows)
    for raw in rows:
        row = dict(raw)
        if not _is_user_source_row(row):
            continue
        score = _function_location_score(row, query_terms, active_resolved, domain_hints=domain_hints)
        if score <= 0:
            continue
        row["match_score"] = score
        scored.append(row)
    scored.sort(
        key=lambda row: (
            -int(row.get("match_score") or 0),
            str(row.get("rel_path") or row.get("path") or "").lower(),
            int(row.get("start_line") or 0),
        )
    )
    return _dedupe_function_location_rows(scored)[: max(1, int(limit or 8))]


def _function_location_score(
    row: dict,
    terms: list[str],
    active_resolved: str = "",
    *,
    domain_hints: set[str] | None = None,
) -> int:
    name = str(row.get("name") or "").lower()
    qualname = str(row.get("qualname") or "").lower()
    signature = str(row.get("signature") or "").lower()
    docstring = str(row.get("docstring") or "").lower()
    kind = str(row.get("kind") or "").lower()
    path = str(row.get("path") or "")
    rel = str(row.get("rel_path") or path).replace("\\", "/").lower()
    text = " ".join([name, qualname, signature, docstring])
    is_active_file = bool(active_resolved and path and str(Path(path)).lower() == active_resolved.lower())
    word_match_text = " ".join([name, qualname, signature, docstring])
    gate_text = word_match_text
    score = 0
    snake_terms = [term for term in terms if "_" in term]
    word_terms = [term for term in terms if "_" not in term]
    generic_action_terms = {"create", "make", "build", "generate", "add", "setup", "set_up"}
    domain_terms = [term for term in word_terms if term not in generic_action_terms]
    if domain_terms and not any(term in gate_text for term in domain_terms):
        return 0
    hints = domain_hints or set()
    action_terms = [term for term in word_terms if term in generic_action_terms]
    for term in snake_terms:
        if name == term or qualname.endswith("." + term):
            score += 140
        elif term in name or (term in rel and not is_active_file):
            score += 100
        if not is_active_file and Path(rel).name.lower().startswith(term):
            score += 160
    if word_terms and all(term in word_match_text for term in word_terms):
        score += 90
    for term in word_terms:
        if term in name:
            score += 35
        elif term in qualname:
            score += 25
        elif term in signature:
            score += 16
        elif term in docstring:
            score += 14
        elif term in gate_text:
            score += 5
    arg_count = _signature_arg_count(signature)
    for action in action_terms:
        for domain in domain_terms:
            if f"{action}_{domain}" in name:
                score += 95
            elif action in name and domain in name:
                score += 35
    if any(term in {"create", "make", "build", "generate", "setup", "set_up"} for term in action_terms):
        if any(term in {"rig", "rigging"} for term in domain_terms) and "mapping" in name:
            score += 45
            if name.startswith("create_rig_from"):
                score += 140
            elif name == "create_rig_mapping" or name.endswith(".create_rig_mapping"):
                score -= 40
        if arg_count and arg_count <= 2:
            score += 30
        elif arg_count and arg_count >= 6:
            score -= 20
    if any(term in {"rig", "rigging"} for term in word_terms):
        if any(narrow in name for narrow in ("surface", "finger", "space_switch", "eye_", "brow_")) and not any(
            narrow.replace("_", "") in "".join(word_terms) for narrow in ("surface", "finger", "space_switch", "eye", "brow")
        ):
            score -= 45
    if "full" in name or "entire" in docstring or "entire character" in docstring:
        if any(term in {"rig", "rigging"} for term in word_terms):
            score += 45
    if any(term in {"create", "make", "generate", "add", "setup", "set_up"} for term in word_terms):
        if re.match(r"^(create|make|generate|add|setup|set_up)_", name):
            score += 75
        elif re.match(r"^build_", name):
            score += 40
    if "build" in word_terms:
        if re.match(r"^build_", name):
            score += 75
        elif re.match(r"^(create|make|generate|add|setup|set_up)_", name):
            score += 35
    if "maya" in hints and ("maya_tools" in rel or "/maya" in rel or "\\maya" in rel):
        score += 90
    if "unreal" in hints and ("unreal" in rel or "/content/python/" in rel):
        score += 90
    if "blender" in hints and "blender" in rel:
        score += 90
    if "rigging" in hints and ("rigging" in rel or "rig" in name or "rig" in docstring):
        score += 80
    if "control" in hints and ("ctrl" in name or "control" in name or "ctrl" in docstring or "control" in docstring):
        score += 55
    if any(term in name for term in ("space_switch", "switch", "helper")):
        if any(term in {"rig", "rigging"} for term in word_terms):
            score -= 25
    if any(term in generic_action_terms for term in word_terms):
        if kind == "function" and not signature.startswith("(self") and "self," not in signature:
            score += 55
        elif kind == "method" or signature.startswith("(self") or "self," in signature:
            score -= 45
    if name.startswith("_") and any(term in generic_action_terms for term in word_terms):
        score -= 120
    if re.search(r"\b(?:tab|ui|window|panel)\b", name) and any(term in {"rig", "rigging", "mapping"} for term in word_terms):
        score -= 90
    if any(term in generic_action_terms for term in word_terms):
        if re.search(r"\b(remove|delete|clear|cleanup|destroy|disconnect|uninstall)\b", name):
            score -= 90
    if any(term in {"remove", "delete", "clear", "cleanup"} for term in word_terms):
        if re.search(r"\b(create|build|make|generate|add|setup)\b", name):
            score -= 90
    if is_active_file and any(term in rel for term in snake_terms):
        score += 220
    if active_resolved and path and any(term in str(Path(path)).lower() for term in snake_terms):
        score += 160
    if "workflows/" in rel or rel.startswith("workflows\\"):
        score -= 80
    if "engine/source" in rel or "/content/python/" in rel or "\\content\\python\\" in rel:
        score -= 80
    if "test" in rel or "/tests/" in rel:
        score -= 25
    return score


def _signature_arg_count(signature: str) -> int:
    match = re.search(r"\((.*)\)", signature or "")
    if not match:
        return 0
    raw = match.group(1).strip()
    if not raw:
        return 0
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return len([part for part in parts if part not in {"self", "cls"}])


def _answer_file_symbol_equivalence_question(question: str, active_path: str | None = None) -> str | None:
    """Answer focused "do we already have a helper for X?" questions.

    This intentionally runs before the generic file-function inventory path.
    It ranks only symbols relevant to the requested behavior and states whether
    an obvious dedicated equivalent exists.
    """
    lower = (question or "").lower()
    file_hint = _file_hint_from_question(question, active_path)
    if not file_hint:
        return None
    if re.search(r"\b(add|create|make|write|implement|modify|edit|change|fix|patch|rename|remove|delete)\b", lower):
        return None
    existence_language = bool(re.search(r"\b(do we have|does .* have|is there|are there|any)\b", lower))
    artifact_language = bool(re.search(r"\b(helper|helpers|function|functions|method|methods|implementation|implementations)\b", lower))
    behavior_language = bool(re.search(r"\b(for|that|which|to|finding|find|filtering|filter|get|resolve|locate)\b", lower))
    if not (existence_language and artifact_language and behavior_language):
        return None

    rel, symbols, source_name = _symbol_rows_for_requested_file(active_path, file_hint, limit=240)
    if not symbols:
        return (
            f"I could not find `{file_hint}` in the indexed project files.\n\n"
            "Verification: refresh the project index or make sure the file is open, then retry the question."
        )

    focus_terms = _focused_behavior_terms(question, file_hint)
    ranked: list[tuple[float, dict, list[str]]] = []
    for row in symbols:
        if str(row.get("kind") or "").lower() not in {"function", "method"}:
            continue
        searchable = " ".join(
            str(row.get(key) or "") for key in ("name", "qualname", "signature", "docstring", "source")
        ).lower()
        name = str(row.get("name") or row.get("qualname") or "").lower()
        score = 0.0
        matched: list[str] = []
        for term in focus_terms:
            specificity = 1.5 if term in {"twist", "segment"} else 1.0
            if term in name:
                score += 8.0 * specificity
                matched.append(f"name:{term}")
            elif term in searchable:
                score += 2.0 * specificity
                matched.append(f"body:{term}")
        if re.search(r"\b(find|filter|get|resolve|collect|list|mapped|existing)\b", name):
            score += 3.0
            matched.append("resolver/filter naming")
        if re.search(r"\b(create|setup|build|show|driver)\b", name):
            score -= 1.0
        if score > 0:
            ranked.append((score, row, matched))

    ranked.sort(key=lambda item: (-item[0], int(item[1].get("start_line") or 0)))
    top = ranked[:6]
    domain_terms = {term for term in focus_terms if term in {"twist", "segment", "joint", "joints", "bone", "bones"}}
    exact = []
    for score, row, matched in top:
        name = str(row.get("name") or row.get("qualname") or "").lower()
        action_match = bool(re.search(r"\b(find|filter|get|resolve|collect|list)\b", name)) or any(token in name for token in ("_find", "_filter", "_get", "resolve_", "collect_", "list_"))
        domain_match = bool(domain_terms) and any(term.rstrip("s") in name for term in domain_terms)
        if action_match and domain_match and score >= 10:
            exact.append((score, row, matched))

    if exact:
        conclusion = "Yes. I found an obvious dedicated helper matching that behavior."
    else:
        conclusion = "No obvious dedicated equivalent was found in the indexed symbols. The closest related functions are below."

    lines = [conclusion, "", f"File: `{rel}`"]
    if focus_terms:
        lines.append("Behavior terms checked: " + ", ".join(f"`{term}`" for term in focus_terms[:8]))
    if not top:
        lines.extend([
            "",
            "No function or method in the indexed file matched the requested behavior terms.",
            "",
            f"Source: {source_name or 'local project knowledge index'}.",
        ])
        return "\n".join(lines)

    lines.extend(["", "Closest relevant functions:"])
    for score, row, matched in top:
        signature = row.get("signature") or row.get("qualname") or row.get("name") or ""
        start_line = row.get("start_line")
        lines.append(f"- `{signature}`" + (f" on line `{start_line}`" if start_line else ""))
        lines.append("  Match evidence: " + ", ".join(matched[:5]))
        summary = _indexed_symbol_summary(row)
        if summary:
            lines.append(f"  Indexed summary: {summary}")
    lines.extend([
        "",
        "This conclusion is based on indexed names, signatures, docstrings, and source excerpts; inspect the top candidates before reusing one as behaviorally equivalent.",
        f"Source: {source_name or 'local project knowledge index'}.",
    ])
    return "\n".join(lines)


def _focused_behavior_terms(question: str, file_hint: str) -> list[str]:
    lower = (question or "").lower()
    noise = {
        "do", "we", "have", "does", "is", "there", "are", "any", "in", "the", "a", "an", "for", "that", "which", "to",
        "helper", "helpers", "function", "functions", "method", "methods", "implementation", "implementations", "file", "py",
        "finding", "find", "filtering", "filter", "get", "resolve", "locate", "only", "our", "this",
    }
    file_parts = set(re.findall(r"[a-z0-9_]+", str(file_hint or "").lower()))
    raw = re.findall(r"\b[a-z_][a-z0-9_]*\b", lower)
    terms: list[str] = []
    for token in raw:
        if token in noise or token in file_parts or len(token) < 3:
            continue
        value = token[:-1] if token.endswith("s") and len(token) > 4 else token
        if value not in terms:
            terms.append(value)
    return terms[:12]


def _indexed_symbol_summary(row: dict) -> str:
    doc = str(row.get("docstring") or "").strip()
    if doc:
        return re.sub(r"\s+", " ", doc).splitlines()[0][:220]
    source = str(row.get("source") or "").strip()
    if not source:
        return ""
    for line in source.splitlines()[1:12]:
        cleaned = line.strip().strip('"\'')
        if cleaned and cleaned not in {"pass", "..."} and not cleaned.startswith(("#", "def ", "return ")):
            return cleaned[:220]
    return ""


def _answer_file_symbol_question(question: str, active_path: str | None = None) -> str | None:
    lower = (question or "").lower()
    if not re.search(r"\b(functions?|methods?|arguments?|args?|required|signature)\b", lower):
        return None
    wants_args = bool(re.search(r"\b(arguments?|args?|required|signature)\b", lower))
    explicit_function = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*)\b", question or "")
    file_hint = _file_hint_from_question(question, active_path)
    if not file_hint and active_path and wants_args and explicit_function:
        file_hint = str(active_path)
    if not file_hint:
        return None
    rel, symbols, source = _symbol_rows_for_requested_file(active_path, file_hint, limit=120)
    if not symbols:
        return (
            f"I could not find `{file_hint}` in the indexed project files.\n\n"
            "Verification: refresh the project index or make sure the file is open, then retry the question."
        )

    wants_list = bool(re.search(r"\b(functions|methods|list|show|what|which|have|contains?|in this file|in .*\.py)\b", lower))
    if wants_list and not wants_args:
        rows = [
            row for row in symbols
            if str(row.get("kind") or "").lower() in {"function", "method"}
            and (row.get("scope_depth") in (None, 0) or str(row.get("kind") or "").lower() == "method")
        ]
        if not rows:
            return f"I found `{rel}`, but it does not list any functions or methods."
        lines = [f"Functions in `{rel}`:"]
        for idx, row in enumerate(rows[:80], 1):
            signature = row.get("signature") or row.get("qualname") or row.get("name") or ""
            kind = str(row.get("kind") or "function")
            line = row.get("start_line")
            lines.append(f"{idx}. `{signature}` - {kind}" + (f", line `{line}`" if line else ""))
        if len(rows) > 80:
            lines.append(f"... {len(rows) - 80} more not shown.")
        lines.extend(["", f"Source: {source or 'local project knowledge index'}." ])
        return "\n".join(lines)

    function_name = ""
    if explicit_function:
        function_name = explicit_function.group(1).lower()
    first = next(
        (
            row for row in symbols
            if function_name
            and str(row.get("name") or "").lower() == function_name
        ),
        symbols[0],
    )
    signature = first.get("signature") or first.get("name") or ""
    required = _required_args_from_signature(signature)
    lines = [
        f"`{first.get('qualname') or first.get('name')}` in `{rel}` starts on line `{first.get('start_line')}`.",
        "",
        f"Signature: `{signature}`",
    ]
    if required:
        lines.append("Required arguments: " + ", ".join(f"`{arg}`" for arg in required))
    else:
        lines.append("Required arguments: none detected from the indexed signature.")
    lines.append("")
    lines.append(f"Source: {source or 'local project knowledge index'}.")
    return "\n".join(lines)


def answer_simple_project_index_question(question: str, active_path: str | None = None) -> str | None:
    """Answer small factual project-index questions without LLM involvement."""
    lower = (question or "").lower()
    if not is_project_scope_request(question):
        return None

    equivalence_answer = _answer_file_symbol_equivalence_question(question, active_path=active_path)
    if equivalence_answer:
        return equivalence_answer

    symbol_answer = _answer_file_symbol_question(question, active_path=active_path)
    if symbol_answer:
        return symbol_answer

    location_answer = _answer_function_location_question(question, active_path=active_path)
    if location_answer:
        return location_answer

    wants_file_fact = re.search(r"\b(first|top|start|beginning|count|how many|list|show)\b", lower) and re.search(
        r"\b(file|files|filename|file name|indexed|python|py)\b", lower
    )
    if not wants_file_fact:
        return None

    ext = ".py" if re.search(r"\b(python|py)\b|\.py\b", lower) else None
    requested_count = 10
    count_match = re.search(r"\bfirst\s+(\d+)|\btop\s+(\d+)|\blist\s+(?:the\s+)?(?:first\s+)?(\d+)", lower)
    if count_match:
        requested_count = max(1, min(int(next(g for g in count_match.groups() if g)), 50))

    rows = _project_file_rows(active_path, limit=max(50, requested_count), ext=ext)
    if not rows:
        return (
            "I could not find indexed first-party project files in the knowledge index.\n\n"
            "Verification: rebuild or refresh the project index, then retry the same question."
        )

    if re.search(r"\b(count|how many)\b", lower):
        count_rows = _project_file_rows(active_path, limit=2000, ext=ext)
        label = "Python files" if ext == ".py" else "first-party project files"
        return (
            f"The project index currently has {len(count_rows)} {label} visible to this query.\n\n"
            f"First indexed file by path: `{rows[0].get('rel_path') or rows[0].get('path')}`"
        )

    first = rows[0]
    rel = first.get("rel_path") or first.get("path") or ""
    name = Path(rel).name
    if re.search(r"\b(list|show|top)\b", lower) or requested_count > 1:
        label = "Python files" if ext == ".py" else "project files"
        lines = [f"First indexed {label} by path:"]
        for idx, row in enumerate(rows[:requested_count], 1):
            lines.append(f"{idx}. `{row.get('rel_path') or row.get('path')}`")
        return "\n".join(lines)

    label = "Python project file" if ext == ".py" else "project file"
    return (
        f"The first indexed {label} by path is `{rel}`.\n\n"
        f"File name: `{name}`\n"
        "Source: local project knowledge index."
    )


def _dependency_graph_rows(question: str, active_path: str | None = None, limit: int = 80) -> list[dict]:
    try:
        from models.constants import V2_DB
        from knowledge.search import extract_code_search_terms
    except Exception:
        return []
    if not V2_DB.exists():
        return []

    project_roots = _active_project_roots(active_path)
    terms = extract_code_search_terms(question)
    noise = {
        "dependency", "dependencies", "depend", "depends", "import", "imports",
        "project", "file", "files", "module", "modules", "graph", "show", "find",
        "list", "what", "which",
    }
    targets = [term for term in terms if term.lower() not in noise]
    params: list[object] = []
    where = ["d.is_resolved = 1"]
    if targets:
        term_clauses = []
        for term in targets[:6]:
            like = f"%{term}%"
            term_clauses.append(
                "(d.source_path LIKE ? OR d.source_module LIKE ? OR d.import_name LIKE ? OR d.target_path LIKE ? OR d.target_module LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        where.append("(" + " OR ".join(term_clauses) + ")")
    if project_roots:
        root_clauses = []
        for root in project_roots:
            root_clauses.append("(d.source_path LIKE ?)")
            params.append(str(Path(root)) + "%")
        where.append("(" + " OR ".join(root_clauses) + ")")
    params.append(max(1, min(int(limit or 80), 500)))

    try:
        with _connect_index_readonly(V2_DB, timeout=5) as conn:
            rows = conn.execute(
                f"""
                SELECT d.source_path, d.source_module, d.import_name,
                       d.target_path, d.target_module, d.imported_name,
                       d.used_symbol_count, d.resolution_note
                FROM file_dependencies d
                WHERE {' AND '.join(where)}
                ORDER BY d.source_path, d.import_name, d.target_path
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]
    except Exception:
        return []


def answer_project_dependency_question(question: str, active_path: str | None = None, limit: int = 80) -> str | None:
    lower = (question or "").lower()
    if not re.search(r"\b(dependency|dependencies|depends on|imports?|import graph)\b", lower):
        return None
    rows = _dependency_graph_rows(question, active_path=active_path, limit=limit)
    if not rows:
        return (
            "No matching dependency graph rows were found in the project index.\n\n"
            "This is a deterministic index answer. If that seems wrong, rebuild the knowledge index so `file_dependencies` is refreshed."
        )
    lines = [
        "Dependency graph matches from the local project index:",
        "",
    ]
    seen = set()
    shown = 0
    for row in rows:
        key = (row.get("source_path"), row.get("import_name"), row.get("target_path"))
        if key in seen:
            continue
        seen.add(key)
        shown += 1
        lines.append(
            f"[{shown}] {row.get('source_path')}\n"
            f"    imports: {row.get('import_name')}\n"
            f"    target: {row.get('target_path') or row.get('target_module') or '(unresolved)'}\n"
            f"    used symbol count: {row.get('used_symbol_count')}"
        )
        if shown >= 40:
            break
    return "\n".join(lines)


def detect_project_search_mode(question: str) -> str:
    """Classify a project-wide request into a retrieval mode."""
    lower = (question or "").lower()

    if re.search(r"\b(add|create|write|generate|implement|insert|modify|improve|refactor|fix|update)\b", lower) and (
        re.search(r"\b(project|repo|codebase|tool|function|class|method|module|file|existing|current|ui|pipeline|workflow|editor|service|bridge|where should|best place|which file)\b", lower)
        or re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", question or "")
    ):
        return ProjectSearchMode.TARGET_EDIT

    if re.search(r"\b(unused|not used|dead code|orphan|orphaned|not imported|never imported|safe to delete)\b", lower):
        if re.search(r"\b(import|imports|imported)\b", lower) and not re.search(r"\b(file|files|module|modules)\b", lower):
            return ProjectSearchMode.UNUSED_IMPORTS
        return ProjectSearchMode.UNUSED_FILES
    if re.search(r"\b(dependency|dependencies|import graph|outgoing imports)\b", lower):
        return ProjectSearchMode.DEPENDENCIES
    if re.search(r"\b(dependents|what uses|who uses|incoming references)\b", lower):
        return ProjectSearchMode.DEPENDENTS

    if re.search(r"\b(import|imports|imported)\b", lower):
        return ProjectSearchMode.IMPORT
    if re.search(r"\b(call|calls|callers|callee|called by)\b", lower):
        return ProjectSearchMode.CALL
    if re.search(r"\b(usage|usages|use|uses|used|references|reference|where is|where are|anywhere)\b", lower):
        return ProjectSearchMode.USAGE
    if re.search(r"\b(class|classes|subclass|inherits|derived|base class)\b", lower):
        # "classes that use QFileDialog" still needs usage search, not class-name-only search.
        if re.search(r"\b(use|uses|used|opens|open|calls|references|contains|with)\b", lower):
            return ProjectSearchMode.USAGE
        return ProjectSearchMode.CLASS
    if re.search(r"\b(which|what)\s+service\s+should\s+(own|handle|manage)\b", lower):
        return ProjectSearchMode.ARCHITECTURE
    if re.search(r"\b(function|functions|method|methods|symbol|symbols)\b", lower):
        return ProjectSearchMode.SYMBOL
    if re.search(r"\b(architecture|pattern|style|where should|best place)\b", lower):
        return ProjectSearchMode.ARCHITECTURE
    return ProjectSearchMode.USAGE


def gather_project_search_context(
    question: str,
    active_path: str | None = None,
    limit: int = 100,
    *,
    scope: str | None = None,
) -> str:
    """Gather whole-project evidence using the SQLite knowledge index.

    The important distinction: usage queries search source/chunks/imports/calls,
    not just class names. This fixes cases like QFileDialog usage inside a method.
    """
    from knowledge.search import (
        extract_code_search_terms,
        format_index_search_context,
        search_index_call_names,
        search_index_calls,
        search_index_classes,
        search_index_imports,
        search_index_symbols,
        search_index_usages,
    )

    mode = detect_project_search_mode(question)
    scope = scope or detect_search_scope(question)
    project_roots = _active_project_roots(active_path)
    terms = extract_code_search_terms(question)
    first_term = terms[0] if terms else ""

    header = [
        "Project retrieval plan:",
        f"Mode: {mode}",
        f"Scope: {scope}",
        f"Active file: {active_path or '(none)'}",
        f"Project roots: {', '.join(project_roots) or '(none)'}",
        f"Terms: {', '.join(terms) or '(none)'}",
        "",
    ]

    try:
        if mode == ProjectSearchMode.TARGET_EDIT:
            from services.project_service import discover_edit_targets, format_edit_target_context
            discovery = discover_edit_targets(question, active_path=active_path, limit=min(limit, 10), scope=scope)
            return "\n".join(header) + format_edit_target_context(discovery)

        if mode == ProjectSearchMode.UNUSED_FILES:
            from knowledge.search import analyze_unused_files, analyze_unused_imports, format_graph_analysis_context
            unused = analyze_unused_files(scope=scope, limit=limit)
            unused_imports = analyze_unused_imports(scope=scope, limit=min(limit, 80))
            return "\n".join(header) + format_graph_analysis_context(unused) + "\n\n" + format_graph_analysis_context(unused_imports)

        if mode == ProjectSearchMode.UNUSED_IMPORTS:
            from knowledge.search import analyze_unused_imports, format_graph_analysis_context
            result = analyze_unused_imports(scope=scope, limit=limit)
            return "\n".join(header) + format_graph_analysis_context(result)

        if mode == ProjectSearchMode.DEPENDENTS and first_term:
            from knowledge.search import find_file_dependents, format_graph_analysis_context
            result = find_file_dependents(first_term, scope=scope, limit=limit)
            return "\n".join(header) + format_graph_analysis_context(result)

        if mode == ProjectSearchMode.DEPENDENCIES:
            answer = answer_project_dependency_question(question, active_path=active_path, limit=limit)
            return "\n".join(header) + (answer or "No dependency graph rows found in the project index.")

        if mode == ProjectSearchMode.IMPORT and first_term:
            rows = []
            for term in terms[:8]:
                rows.extend(search_index_imports(term, limit=limit, active_path=active_path, scope=scope, project_roots=project_roots))
            if not rows:
                return "\n".join(header) + "No matching imports found in the project index."
            body = ["Import matches:"]
            seen = set()
            for i, row in enumerate(rows, 1):
                key = (row.get("path"), row.get("import_name"))
                if key in seen:
                    continue
                seen.add(key)
                body.append(f"[{i}] {row.get('import_name')}\nFile: {row.get('path')}\n")
            return "\n".join(header + body)

        if mode == ProjectSearchMode.CALL and first_term:
            rows = []
            for term in terms[:8]:
                rows.extend(search_index_calls(term, limit=limit, active_path=active_path, scope=scope, project_roots=project_roots))
            if not rows:
                return "\n".join(header) + "No matching calls found in the project index."
            body = ["Call matches:"]
            seen = set()
            for i, row in enumerate(rows, 1):
                key = (row.get("path"), row.get("qualname"), row.get("call_name"), row.get("call_lineno"), row.get("call_col"))
                if key in seen:
                    continue
                seen.add(key)
                src = (row.get("source") or "")
                lines = src.splitlines()
                if len(lines) > 35:
                    src = "\n".join(lines[:30]) + "\n... [truncated] ..."
                body.append(
                    f"[{i}] {row.get('kind')} {row.get('qualname') or row.get('name')} lines {row.get('start_line')}-{row.get('end_line')}"
                    f"{' call line ' + str(row.get('call_lineno')) if row.get('call_lineno') else ''}\n"
                    f"File: {row.get('path')}\nCall: {row.get('call_name')}\n"
                    f"{'Owner: ' + str(row.get('parent_kind')) + ' ' + str(row.get('parent_qualname')) + chr(10) if row.get('parent_qualname') else ''}"
                    f"Source:\n```python\n{src}\n```\n"
                )
            return "\n".join(header + body)

        if mode == ProjectSearchMode.CLASS:
            rows = search_index_classes(terms=terms, limit=limit, active_path=active_path, scope=scope, project_roots=project_roots)
            if not rows:
                return "\n".join(header) + "No matching classes found in the project index."
            body = ["Class matches:"]
            for i, row in enumerate(rows, 1):
                src = row.get("source") or ""
                lines = src.splitlines()
                if len(lines) > 35:
                    src = "\n".join(lines[:30]) + "\n... [truncated] ..."
                body.append(
                    f"[{i}] class {row.get('qualname') or row.get('name')} lines {row.get('start_line')}-{row.get('end_line')}\n"
                    f"File: {row.get('path')}\nSource:\n```python\n{src}\n```\n"
                )
            return "\n".join(header + body)

        if mode == ProjectSearchMode.ARCHITECTURE:
            architecture_target_context = ""
            try:
                from services.project_service import discover_edit_targets

                discovery = discover_edit_targets(question, active_path=active_path, limit=5, scope=scope)
                candidates = discovery.get("candidates") or []
                if candidates and discovery.get("confidence") in {"high", "medium"}:
                    lines = ["Likely owning service/file candidates:"]
                    for i, item in enumerate(candidates[:5], 1):
                        lines.append(f"[{i}] {item.get('path')}  score={item.get('score')}")
                    architecture_target_context = "\n".join(lines) + "\n\n"
            except Exception:
                architecture_target_context = ""
            rows = search_index_symbols(
                terms,
                limit=min(limit, 40),
                active_path=active_path,
                class_bias=True,
                scope=scope,
                project_roots=project_roots,
            )
            rows = [
                row for row in rows
                if not re.search(r"[\\/](?:\\.venv|venv|site-packages|dist-packages)[\\/]", str(row.get("path") or "").replace("\\", "/"))
            ]
            if not rows:
                return "\n".join(header) + architecture_target_context + "No matching architecture/service symbols found in the project index."
            body = ["Architecture/service symbol matches:"]
            for i, row in enumerate(rows[:40], 1):
                body.append(
                    f"[{i}] {row.get('kind')} {row.get('qualname') or row.get('name')} lines {row.get('start_line')}-{row.get('end_line')}\n"
                    f"File: {row.get('path')}\n"
                    f"Signature: {row.get('signature') or '(none)'}\n"
                )
            return "\n".join(header) + architecture_target_context + "\n".join(body)

        if mode == ProjectSearchMode.SYMBOL:
            rows = search_index_symbols(terms, limit=limit, active_path=active_path, class_bias=False, scope=scope, project_roots=project_roots)
            if not rows:
                return "\n".join(header) + "No matching symbols found in the project index."
            # Reuse usage formatter by doing a full usage search; it includes source snippets.
            results = search_index_usages(_clean_index_query(question), limit=limit, active_path=active_path, scope=scope, project_roots=project_roots)
            return "\n".join(header) + format_index_search_context(_filter_index_usage_results(results))

        # Default: usage/text/architecture searches should not be class-only.
        if "qfiledialog" in (question or "").lower() and re.search(r"\b(class|classes)\b", (question or "").lower()):
            rows = []
            for term in ("QFileDialog", "getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"):
                rows.extend(search_index_call_names(term, limit=20, active_path=active_path, scope=scope, project_roots=project_roots))
            if rows:
                seen = set()
                body = ["QFileDialog call matches:"]
                shown = 0
                for row in rows:
                    key = (row.get("path"), row.get("qualname"), row.get("call_name"), row.get("call_lineno"))
                    if key in seen:
                        continue
                    seen.add(key)
                    shown += 1
                    body.append(
                        f"[{shown}] {row.get('parent_kind') or row.get('kind')} {row.get('parent_qualname') or row.get('qualname') or row.get('name')}\n"
                        f"File: {row.get('path')}\n"
                        f"Call: {row.get('call_name')} line {row.get('call_lineno')}\n"
                    )
                    if shown >= min(limit, 40):
                        break
                return "\n".join(header + body)
        results = search_index_usages(_clean_index_query(question), limit=limit, active_path=active_path, scope=scope, project_roots=project_roots)
        return "\n".join(header) + format_index_search_context(_filter_index_usage_results(results))

    except Exception as exc:
        return "\n".join(header) + f"[Project search error] {exc}"


def should_deepen_project_search(question: str, first_answer: str | None = None) -> bool:
    """Return True when a fast indexed answer should be enriched in background.

    The first answer should stay immediate. This flag lets UI/job code append a
    slower search pass later for broad requests such as "every class" or
    "all usages" without making the user wait for full recall before seeing
    useful evidence.
    """
    lower = (question or "").lower()
    if not lower:
        return False
    if re.search(r"\b(every|all|full|complete|exhaustive|more|also|append|keep looking)\b", lower):
        return True
    if re.search(r"\b(callers|usages|references|uses|used by|classes that|files that|where is|where are)\b", lower):
        return True
    if first_answer and re.search(r"\b(top|best match|matching indexed|call matches|project index search results)\b", first_answer.lower()):
        return True
    return False


def build_deterministic_project_search_answer(
    question: str,
    active_path: str | None,
    project_context: str,
    *,
    max_chars: int = 12000,
) -> str:
    """Format indexed project evidence for chat without calling an LLM."""
    direct = answer_simple_project_index_question(question, active_path=active_path)
    if direct:
        return direct

    context = (project_context or "").strip()
    if not context:
        return "The project index did not return evidence for that request."
    if "[Project search error]" in context:
        return context[:max_chars]

    lines = [
        "I used the local project index for this, without sending the request to the LLM.",
        "",
        "**Indexed Evidence**",
        context[:max_chars],
    ]
    if len(context) > max_chars:
        lines.append("\n[truncated indexed evidence]")
    return "\n".join(lines)


def build_project_search_prompt(question: str, active_path: str | None, project_context: str, intent: str) -> str:
    return f"""You are assisting inside a Python/Qt code editor with project-wide indexed search results.

User request:
{question}

Intent:
{intent}

Active file, if relevant:
{active_path or '(none)'}

Indexed evidence:
{project_context[:18000]}

Answer rules:
- Treat this as a whole-project/codebase request, not a current-file-only request.
- By default, "project" means first-party/current-project files only; do not lead with Python stdlib, installed app, engine, or third-party results unless the evidence explicitly says the scope was broadened.
- Use the indexed evidence. Do not invent files, classes, functions, or usages.
- If exact matches exist, summarize those first.
- If exact matches are empty but related fallback matches exist, say that clearly and summarize the related results instead of claiming nothing exists.
- Group results by file.
- Include functions/methods that contain the usage even if no class is found.
- If the index may be stale or incomplete, say what verification command/search would confirm it.
- For edit/refactor requests, identify target files, imports, call sites, and risks.
- For target-discovery edits, rank candidate files before proposing changes.
- For dead-code/unused-file requests, clearly separate high-confidence candidates from heuristic/weak candidates and warn before deletion.

Response format:
1. Direct answer.
2. Relevant files and symbols found.
3. What each one does or why it matters.
4. Verification command/search if useful.
"""
