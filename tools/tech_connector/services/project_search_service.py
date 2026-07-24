"""Project-wide query routing and indexed retrieval for editor workflows."""

from __future__ import annotations

from contextlib import contextmanager
import re
import sqlite3
import ast
from pathlib import Path


@contextmanager
def _connect_index_readonly(db_path: Path, timeout: int | float = 5):
    uri = db_path.resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, timeout=timeout, uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def _active_project_roots(active_path: str | None = None) -> list[str]:
    roots: list[str] = []
    try:
        from tech_connector.services.settings_service import load_settings
        from tech_connector.models.project import project_roots
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
    RESEARCH = "research"
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
        from tech_connector.models.constants import project_index_db_path
    except Exception:
        return []
    if not project_index_db_path().exists():
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
        with _connect_index_readonly(project_index_db_path(), timeout=5) as conn:
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
    module_path = wanted.replace(".", "/")
    module_file = f"{module_path}.py" if "." in wanted and "/" not in wanted and not wanted.endswith(".py") else ""
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
        if (
            rel.endswith(wanted)
            or path.endswith(wanted)
            or (module_file and (rel.endswith(module_file) or path.endswith(module_file)))
            or Path(rel).name.lower() == wanted_name
        ):
            return row
    try:
        from tech_connector.models.constants import project_index_db_path
        if project_index_db_path().exists():
            with _connect_index_readonly(project_index_db_path(), timeout=2) as conn:
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
                        or (module_file and (rel.endswith(module_file) or path.endswith(module_file)))
                        or rel.endswith("/" + wanted_name)
                        or path.endswith("/" + wanted_name)
                    ):
                        return data
    except Exception:
        pass
    return None


def _symbol_rows_for_file(file_path: str, *, kinds: tuple[str, ...] = ("function", "method"), limit: int = 20) -> list[dict]:
    try:
        from tech_connector.models.constants import project_index_db_path
    except Exception:
        return []
    if not project_index_db_path().exists() or not file_path:
        return []
    placeholders = ", ".join("?" for _ in kinds)
    try:
        with _connect_index_readonly(project_index_db_path(), timeout=2) as conn:
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
        from tech_connector.services.capability_service import expand_terms
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
    if re.search(r"\b(?:what|which|find|locate|show)\s+(?:the\s+)?class(?:es)?\b", lower):
        return None
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
    if re.search(r"\b(?:what|which)\s+file\s+has\s+a\s+function\s+to\b", question or "", re.IGNORECASE):
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
        from tech_connector.models.constants import project_index_db_path
        db_path = project_index_db_path()
    except Exception:
        db_path = None
    if not db_path or not db_path.exists():
        active_rows.sort(key=lambda row: (-int(row.get("match_score") or 0), int(row.get("start_line") or 0)))
        return _dedupe_function_location_rows(active_rows)[: max(1, int(limit or 8))]
    generic_query_terms = {
        "add", "any", "build", "class", "classes", "create", "existing", "file",
        "files", "function", "functions", "generate", "implementation", "make",
        "method", "methods", "project", "setup",
    }
    selective_terms = [
        term for term in query_terms
        if "_" in term or term not in generic_query_terms
    ] or query_terms
    clauses = []
    params: list[object] = []
    for term in selective_terms[:6]:
        like = f"%{term}%"
        clauses.append(
            "(lower(s.name) LIKE ? OR lower(s.qualname) LIKE ? OR lower(s.signature) LIKE ? "
            "OR lower(s.docstring) LIKE ?)"
        )
        params.extend([like, like, like, like])
    if not clauses:
        return []
    try:
        with _connect_index_readonly(project_index_db_path(), timeout=2) as conn:
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


def answer_explicit_symbol_inspection_question(
    question: str,
    *,
    project_roots: list[str] | tuple[str, ...] | None = None,
    active_path: str | None = None,
) -> str | None:
    symbol = _explicit_qualified_symbol_reference(question)
    if not symbol:
        return None
    operations = _symbol_inspection_operations(question)
    if not operations:
        return None

    resolution = _resolve_explicit_python_symbol(symbol, project_roots or (), active_path=active_path)
    if not resolution:
        return None
    path, rel, node, source, symbol_tail = resolution
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return None

    lines = [
        "What I understood",
        f"Inspect the exact project symbol `{symbol}` and answer: {', '.join(operations)}.",
        "",
        f"Target: `{symbol}`",
        f"Source: `{rel}`" + (f":{getattr(node, 'lineno', '')}" if getattr(node, "lineno", None) else ""),
        "",
    ]

    if isinstance(node, ast.ClassDef):
        lines.append(f"Definition: `class {node.name}`")
    else:
        lines.append(f"Signature: `{_callable_signature_from_ast(node)}`")
    doc = ast.get_docstring(node)
    if doc:
        lines.extend(["", "Docstring:", _compact_text(doc, 700)])

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        params = _parameter_rows_from_ast(node)
        if params:
            lines.extend(["", "Parameters:"])
            for name, defaulted in params:
                suffix = " optional/defaulted" if defaulted else " required"
                lines.append(f"- `{name}`: {suffix}")

        if "explain_behavior" in operations or "show_implementation" in operations:
            summary = _function_behavior_summary(node)
            if summary:
                lines.extend(["", "Behavior from source:"])
                lines.extend(f"- {item}" for item in summary)

        if "explain_usage" in operations:
            lines.extend(["", "Usage:"])
            lines.extend(_usage_lines(symbol, node, source, path))

        if "find_callers" in operations:
            callers = _find_symbol_callers(path, node.name, project_roots or (), limit=8)
            lines.extend(["", "Callers found:" if callers else "Callers found: none in the scanned project files."])
            for caller in callers:
                lines.append(f"- `{caller}`")

        returns = _return_summary(node)
        if returns:
            lines.extend(["", "Returns:", returns])

    if "show_implementation" in operations:
        snippet = ast.get_source_segment(source, node) or ""
        if snippet:
            lines.extend(["", "Implementation excerpt:", "```python", _trim_source(snippet, 80), "```"])

    lines.extend([
        "",
        "Resolution: exact qualified symbol. Broad fuzzy project search was not used because the explicit target resolved.",
    ])
    return "\n".join(lines)


def _explicit_qualified_symbol_reference(question: str) -> str:
    match = re.search(
        r"(?<![\w.])@([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){2,})(?![\w.])",
        question or "",
    )
    return match.group(1) if match else ""


def _symbol_inspection_operations(question: str) -> list[str]:
    lower = (question or "").lower()
    operations: list[str] = []

    def add(value: str) -> None:
        if value not in operations:
            operations.append(value)

    if re.search(r"\b(what\s+does|what\s+do|how\s+does|explain|summari[sz]e|describe|run\s+through)\b", lower):
        add("explain_behavior")
    if re.search(r"\b(how\s+(?:do|can|should|would)\s+i\s+use|how\s+to\s+use|usage|example|invoke|call\s+it|call\s+this|use\s+it)\b", lower):
        add("explain_usage")
    if re.search(r"\b(who\s+calls|what\s+calls|find\s+callers?|called\s+by|callers?)\b", lower):
        add("find_callers")
    if re.search(r"\b(show|read|inspect|open)\s+(?:the\s+)?(?:implementation|source|body|code)\b", lower):
        add("show_implementation")
    return operations


def _resolve_explicit_python_symbol(
    symbol: str,
    project_roots: list[str] | tuple[str, ...],
    *,
    active_path: str | None = None,
) -> tuple[Path, str, ast.AST, str, list[str]] | None:
    parts = [part for part in str(symbol or "").split(".") if part]
    if len(parts) < 2:
        return None
    roots = [Path(root) for root in project_roots if root]
    if active_path:
        active = Path(active_path)
        if active.exists():
            roots.insert(0, active.parent if active.is_file() else active)
    roots.append(Path.cwd())

    for split_at in range(len(parts) - 1, 0, -1):
        module_parts = parts[:split_at]
        symbol_tail = parts[split_at:]
        rel_file = Path(*module_parts).with_suffix(".py")
        for root in roots:
            candidate = root / rel_file
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                source = candidate.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
            except Exception:
                continue
            node = _find_ast_symbol(tree, symbol_tail)
            if node is None and symbol_tail:
                node = _find_ast_symbol(tree, [symbol_tail[-1]])
            if node is not None:
                rel = str(rel_file).replace("\\", "/")
                return candidate, rel, node, source, symbol_tail
    return None


def _find_ast_symbol(tree: ast.AST, symbol_tail: list[str]) -> ast.AST | None:
    if not symbol_tail:
        return None
    if len(symbol_tail) == 1:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol_tail[0]:
                return node
        return None
    current: ast.AST = tree
    for part in symbol_tail:
        body = getattr(current, "body", [])
        found = None
        for child in body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name == part:
                found = child
                break
        if found is None:
            return None
        current = found
    return current


def _callable_signature_from_ast(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return _signature_from_ast(node)


def _parameter_rows_from_ast(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, bool]]:
    args = list(node.args.posonlyargs) + list(node.args.args)
    if args and args[0].arg in {"self", "cls"}:
        args = args[1:]
    default_start = len(args) - len(node.args.defaults)
    rows = [(arg.arg, index >= default_start) for index, arg in enumerate(args)]
    rows.extend((arg.arg, default is not None) for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults))
    return rows


def _function_behavior_summary(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    summary: list[str] = []
    calls: list[str] = []
    assignments: list[str] = []
    host_effects: set[str] = set()
    for child in _walk_function_body_without_nested_defs(node):
        if isinstance(child, ast.Call):
            name = _call_name(child.func)
            if name and name not in calls:
                calls.append(name)
            if name.startswith("cmds.") or name.startswith("maya.cmds."):
                host_effects.add("Uses Maya cmds and can mutate/query the current Maya scene.")
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                label = _target_name(target)
                if label and label not in assignments:
                    assignments.append(label)
    if calls:
        summary.append("Calls project/host helpers including " + ", ".join(f"`{name}`" for name in calls[:12]) + ".")
    if assignments:
        summary.append("Builds or updates local values including " + ", ".join(f"`{name}`" for name in assignments[:10]) + ".")
    summary.extend(sorted(host_effects))
    if not summary:
        summary.append("The body is small or mostly declarative; inspect the implementation excerpt for exact behavior.")
    return summary[:6]


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _target_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _call_name(node)
    if isinstance(node, (ast.Tuple, ast.List)):
        return ", ".join(filter(None, (_target_name(item) for item in node.elts)))
    return ""


def _usage_lines(symbol: str, node: ast.FunctionDef | ast.AsyncFunctionDef, source: str, path: Path) -> list[str]:
    params = [name for name, _defaulted in _parameter_rows_from_ast(node)]
    example_args = ", ".join(f"{name}={name}" for name in params)
    lines = [f"Call it as `{symbol}({example_args})`." if example_args else f"Call it as `{symbol}()`."]
    if params:
        lines.append("Provide " + ", ".join(f"`{name}`" for name in params) + " before calling it.")
    related = _nearby_mapping_builders(source, node.name)
    if related:
        lines.append("Nearby source also defines likely prerequisite/helper functions: " + ", ".join(f"`{name}`" for name in related[:6]) + ".")
    lines.append(f"Because this comes from `{path.name}`, run it in the host/context expected by that module; inspect imports and helper calls before invoking it outside that environment.")
    return lines


def _nearby_mapping_builders(source: str, target_name: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except Exception:
        return []
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == target_name:
            continue
        lowered = node.name.lower()
        if "mapping" in lowered or "map" in lowered:
            names.append(node.name)
    return names


def _return_summary(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    values: list[str] = []
    has_bare = False
    for child in _walk_function_body_without_nested_defs(node):
        if not isinstance(child, ast.Return):
            continue
        if child.value is None:
            has_bare = True
            continue
        try:
            text = ast.unparse(child.value)
        except Exception:
            text = type(child.value).__name__
        if text not in values:
            values.append(text)
    if values:
        return "Returns " + ", ".join(f"`{value}`" for value in values[:8]) + "."
    if has_bare:
        return "Contains a bare `return`; no explicit value is returned from that path."
    return "No explicit `return` value was detected, so Python returns `None` unless helper calls raise."


def _walk_function_body_without_nested_defs(node: ast.FunctionDef | ast.AsyncFunctionDef):
    stack = list(reversed(node.body))
    while stack:
        child = stack.pop()
        if child is not node and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        stack.extend(reversed(list(ast.iter_child_nodes(child))))


def _find_symbol_callers(path: Path, function_name: str, project_roots: list[str] | tuple[str, ...], *, limit: int = 8) -> list[str]:
    roots = [Path(root) for root in project_roots if root] or [path.parent]
    callers: list[str] = []
    pattern = re.compile(rf"\b{re.escape(function_name)}\s*\(")
    scanned = 0
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*.py"):
            if scanned >= 4000 or len(callers) >= limit:
                return callers
            scanned += 1
            normalized = str(candidate).replace("\\", "/").lower()
            if any(part in normalized for part in ("/.git/", "/.venv/", "/venv/", "/__pycache__/")):
                continue
            try:
                for line_no, line in enumerate(candidate.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if candidate == path and line_no == 1:
                        continue
                    if pattern.search(line):
                        callers.append(f"{candidate}:{line_no}")
                        break
            except Exception:
                continue
    return callers


def _compact_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: max(0, limit - 3)].rstrip() + "..."


def _trim_source(value: str, max_lines: int) -> str:
    lines = str(value or "").splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines] + ["..."])


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




def _parse_scoped_member_request(question: str):
    try:
        from tech_connector.services.reasoning.target_entity_service import (
            parse_scoped_member_query,
        )
        return parse_scoped_member_query(question)
    except Exception:
        return None


def _resolve_scoped_container_file(
    container_query: str,
    *,
    active_path: str | None = None,
) -> dict | None:
    query = str(container_query or "").strip()
    if not query:
        return None

    explicit_hint = _file_hint_from_question(query, active_path)
    if explicit_hint:
        row = _matching_file_row(active_path, explicit_hint)
        if row:
            return row
        resolved = _resolve_file_hint_path(active_path, explicit_hint)
        if resolved:
            return {
                "path": str(resolved),
                "rel_path": str(resolved),
                "match_score": 1000,
            }

    terms = _function_location_terms(
        f"what file has a function to {query}",
        active_path=active_path,
    )
    rows = _function_location_rows(
        terms,
        active_path=active_path,
        question=f"what file has a function to {query}",
        limit=16,
    )
    if rows:
        best = dict(rows[0])
        return {
            "path": best.get("path") or "",
            "rel_path": best.get("rel_path") or best.get("path") or "",
            "match_score": best.get("match_score") or 0,
            "evidence_symbol": best.get("signature") or best.get("name") or "",
        }

    compact = re.sub(r"[^A-Za-z0-9_]+", "_", query.lower()).strip("_")
    wanted_terms = [
        term for term in compact.split("_")
        if term and term not in {"the", "a", "an", "file", "module", "service"}
    ]
    candidates = _project_file_rows(active_path, limit=2000)
    scored = []
    for row in candidates:
        rel = str(row.get("rel_path") or row.get("path") or "").replace("\\", "/")
        name = Path(rel).stem.lower()
        score = sum(20 for term in wanted_terms if term in name)
        score += sum(4 for term in wanted_terms if term in rel.lower())
        if score:
            item = dict(row)
            item["match_score"] = score
            scored.append(item)
    scored.sort(
        key=lambda row: (
            -int(row.get("match_score") or 0),
            str(row.get("rel_path") or row.get("path") or "").lower(),
        )
    )
    return scored[0] if scored else None


def _member_behavior_terms(behavior: str) -> list[str]:
    noise = {
        "a", "an", "the", "to", "that", "which", "and", "or", "in", "from",
        "function", "functions", "method", "methods", "class", "classes",
        "helper", "helpers",
    }
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", behavior or ""):
        low = token.lower()
        if len(low) < 3 or low in noise:
            continue
        if low.endswith("ing") and len(low) > 5:
            low = low[:-3]
            if low == "creat":
                low = "create"
        elif low.endswith("s") and len(low) > 4:
            low = low[:-1]
        if low not in terms:
            terms.append(low)
    return terms[:10]


def _score_member_behavior(
    row: dict,
    *,
    behavior: str,
    member_type: str,
) -> tuple[float, list[str]]:
    name = str(row.get("name") or row.get("qualname") or "").lower()
    signature = str(row.get("signature") or "").lower()
    doc = str(row.get("docstring") or "").lower()
    source = str(row.get("source") or "").lower()
    kind = str(row.get("kind") or "").lower()
    terms = _member_behavior_terms(behavior)

    score = 0.0
    evidence: list[str] = []

    expected_kinds = {
        "function": {"function"},
        "method": {"method"},
        "class": {"class"},
        "helper": {"function", "method"},
        "symbol": {"function", "method", "class"},
    }.get(member_type, {"function", "method", "class"})
    if kind in expected_kinds:
        score += 4.0
        evidence.append(f"kind:{kind}")
    else:
        score -= 8.0

    action_terms = {
        "create": ("create", "build", "make", "generate", "setup"),
        "build": ("build", "create", "make", "setup"),
        "find": ("find", "get", "resolve", "collect", "filter", "list"),
        "detect": ("detect", "identify", "find", "classify", "filter"),
        "resolve": ("resolve", "find", "get", "map"),
        "handle": ("handle", "process", "dispatch", "route"),
        "validate": ("validate", "verify", "check", "compile", "test"),
    }
    verb = terms[0] if terms else ""
    alternatives = action_terms.get(verb, (verb,) if verb else ())

    if any(name.startswith(prefix + "_") or f"_{prefix}_" in name for prefix in alternatives):
        score += 18.0
        evidence.append("action in symbol name")
    elif any(prefix in name for prefix in alternatives):
        score += 7.0
        evidence.append("related action in symbol name")
    elif any(prefix in doc for prefix in alternatives):
        score += 3.0
        evidence.append("action in docstring")

    object_terms = [
        term for term in terms
        if term not in set(alternatives)
    ]
    matched_object_terms: list[str] = []
    for term_index, term in enumerate(object_terms):
        primary_weight = term_index == 0 and len(object_terms) > 1
        if term in name:
            score += 16.0 if primary_weight else 10.0
            evidence.append(f"name:{term}")
            matched_object_terms.append(term)
        elif term in signature:
            score += 8.0 if primary_weight else 4.0
            evidence.append(f"signature:{term}")
            matched_object_terms.append(term)
        elif term in doc:
            score += 6.0 if primary_weight else 3.0
            evidence.append(f"docstring:{term}")
            matched_object_terms.append(term)
        elif term in source:
            score += 3.0 if primary_weight else 1.0
            evidence.append(f"source:{term}")
            matched_object_terms.append(term)

    if len(object_terms) > 1:
        if object_terms[0] not in matched_object_terms:
            score -= 10.0
            evidence.append(f"missing primary behavior term:{object_terms[0]}")
        elif len(set(matched_object_terms)) == len(set(object_terms)):
            score += 6.0
            evidence.append("complete behavior phrase coverage")

    if verb in {"create", "build", "make", "generate"}:
        if any(token in name for token in ("full", "from_mapping", "entire")):
            score += 8.0
            evidence.append("full-operation naming")
        narrow_tokens = (
            "space_switch", "surface", "finger", "eye", "brow",
            "control", "ctrl", "driver",
        )
        if any(token in name for token in narrow_tokens) and not any(
            token in object_terms for token in narrow_tokens
        ):
            score -= 7.0
            evidence.append("narrow subsystem")

    return round(score, 2), list(dict.fromkeys(evidence))


def answer_scoped_member_behavior_question(
    question: str,
    active_path: str | None = None,
) -> str | None:
    request = _parse_scoped_member_request(question)
    if request is None:
        return None

    if request.reference_kind == "conversation_reference":
        if not active_path:
            return None
        container = {
            "path": str(active_path),
            "rel_path": str(active_path),
            "match_score": 1000,
        }
    else:
        container = _resolve_scoped_container_file(
            request.container_query,
            active_path=active_path,
        )
    if not container:
        return (
            f"I could not resolve the project {request.container_type} described "
            f"as `{request.container_query}`.\n\n"
            "Verification: include an exact file name or refresh the project index."
        )

    file_path = str(container.get("path") or "")
    rel_path = str(container.get("rel_path") or file_path)
    rows = _active_file_symbol_rows(file_path, limit=300)
    evidence_source = "current file AST"
    if not rows:
        rows = _symbol_rows_for_file(
            file_path,
            kinds=("function", "method", "class"),
            limit=300,
        )
        evidence_source = "local project knowledge index"

    ranked: list[dict] = []
    for raw in rows:
        row = dict(raw)
        score, evidence = _score_member_behavior(
            row,
            behavior=request.behavior_description,
            member_type=request.member_type,
        )
        if score <= 0 or any(str(item).startswith("missing primary behavior term:") for item in evidence):
            continue
        row["scoped_behavior_score"] = score
        row["scoped_behavior_evidence"] = evidence
        ranked.append(row)

    ranked.sort(
        key=lambda row: (
            -float(row.get("scoped_behavior_score") or 0.0),
            int(row.get("start_line") or 0),
        )
    )

    lines = [f"Resolved container: `{rel_path}`", ""]

    direct_ranked = [
        row for row in ranked
        if "action in symbol name" in (row.get("scoped_behavior_evidence") or [])
        and any(str(item).startswith("name:") for item in (row.get("scoped_behavior_evidence") or []))
    ]
    related_ranked = [row for row in ranked if row not in direct_ranked]

    guidance_example = _scoped_member_guidance_example(
        question,
        request=request,
        rel_path=rel_path,
        rows=rows,
    )

    if not ranked:
        lines.append(
            f"No. I did not find a {request.member_type} in that file that "
            f"directly `{request.behavior_description}`."
        )
        if guidance_example:
            lines.extend(["", guidance_example])
    else:
        if direct_ranked:
            lines.append(
                f"Yes. I found {len(direct_ranked[:8])} direct {request.member_type}"
                f"{'s' if len(direct_ranked[:8]) != 1 else ''} in that file that `{request.behavior_description}`:"
            )
        else:
            lines.append(
                f"No dedicated {request.member_type} directly `{request.behavior_description}` was found."
            )
        for index, row in enumerate(direct_ranked[:8], start=1):
            signature = (
                row.get("signature")
                or row.get("qualname")
                or row.get("name")
                or ""
            )
            line = row.get("start_line")
            evidence = ", ".join(
                row.get("scoped_behavior_evidence") or []
            )
            lines.append(
                f"{index}. `{signature}`"
                + (f" on line `{line}`" if line else "")
            )
            if evidence:
                lines.append(f"   Evidence: {evidence}")
        if related_ranked:
            lines.extend(["", "Related functions that use or set up the same concepts:"])
            for row in related_ranked[: max(0, 8 - len(direct_ranked[:8]))]:
                signature = row.get("signature") or row.get("qualname") or row.get("name") or ""
                line = row.get("start_line")
                lines.append(f"- `{signature}`" + (f" on line `{line}`" if line else ""))
        if guidance_example:
            lines.extend(["", guidance_example])

    lines.extend(
        [
            "",
            (
                "Ranking was restricted to members inside the resolved file; "
                "narrow subsystem helpers were demoted when the request described "
                "a broader operation."
            ),
            f"Source: {evidence_source}.",
        ]
    )
    return "\n".join(lines)


def _scoped_member_guidance_example(
    question: str,
    *,
    request,
    rel_path: str,
    rows: list[dict],
) -> str:
    lower = (question or "").lower()
    if not re.search(r"\b(what would|how would|needed|example|look like)\b", lower):
        return ""
    if request.member_type != "class":
        return ""
    if "qslider" not in lower and "slider" not in lower:
        return ""

    existing_classes = [
        str(row.get("name") or row.get("qualname") or "")
        for row in rows
        if str(row.get("kind") or "").lower() == "class"
    ]
    context_line = ""
    if existing_classes:
        context_line = (
            "Nearby class patterns in this file include "
            + ", ".join(f"`{name}`" for name in existing_classes[:5] if name)
            + "."
        )
    return "\n".join(
        [
            "Example functional class you could add in that module:",
            "",
            "```python",
            "class LabeledSlider(QtWidgets.QWidget):",
            "    def __init__(self, label=\"Value\", minimum=0, maximum=100, value=0, parent=None):",
            "        super(LabeledSlider, self).__init__(parent)",
            "        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)",
            "        self.slider.setRange(minimum, maximum)",
            "        self.slider.setValue(value)",
            "",
            "        self.label = QtWidgets.QLabel(label)",
            "        self.value_label = QtWidgets.QLabel(str(value))",
            "        self.slider.valueChanged.connect(self._on_value_changed)",
            "",
            "        layout = QtWidgets.QHBoxLayout(self)",
            "        layout.addWidget(self.label)",
            "        layout.addWidget(self.slider)",
            "        layout.addWidget(self.value_label)",
            "",
            "    def _on_value_changed(self, value):",
            "        self.value_label.setText(str(value))",
            "```",
            "",
            f"That matches `{rel_path}` by using the already-imported `QtWidgets` and `QtCore` aliases.",
            context_line,
        ]
    ).strip()

_CONDITIONAL_FALLBACK_RE = re.compile(
    r"\b("
    r"if (?:i|we|you) (?:have|has|find|found) none|"
    r"if (?:there is|there are) none|"
    r"if (?:it|one|that) (?:does not|doesn't|is not|isn't) exist|"
    r"if (?:we|i|you) (?:do not|don't|dont) have (?:one|any|it)|"
    r"otherwise|or else|if not"
    r")\b",
    re.IGNORECASE,
)

_RESEARCH_BEHAVIOR_RE = re.compile(
    r"\b("
    r"detect|identify|recognize|recognise|find|filter|collect|resolve|"
    r"locate|classify|determine|check whether|see if|discover"
    r")\b",
    re.IGNORECASE,
)

_RESEARCH_ARTIFACT_RE = re.compile(
    r"\b(function|functions|method|methods|helper|helpers|implementation|implementations)\b",
    re.IGNORECASE,
)


def is_project_research_request(question: str) -> bool:
    """Return True for search-analyze-decide-fallback project questions."""
    lower = (question or "").lower()
    if not _RESEARCH_ARTIFACT_RE.search(lower):
        return False
    if not _RESEARCH_BEHAVIOR_RE.search(lower):
        return False
    return bool(
        _CONDITIONAL_FALLBACK_RE.search(lower)
        or re.search(
            r"\b(do i have|do we have|what functions do i have|"
            r"which functions|is there a helper|are there helpers|"
            r"how would i make|how would we make|how should i make|"
            r"how should we make)\b",
            lower,
        )
    )


def _research_focus_terms(question: str) -> list[str]:
    """Extract behavioral/domain terms while dropping request framing."""
    noise = {
        "what", "which", "where", "when", "why", "how", "could", "would", "should",
        "please", "tell", "show", "give", "have", "has", "there", "none", "one",
        "some", "any", "function", "functions", "method", "methods", "helper",
        "helpers", "implementation", "implementations", "detect", "identify",
        "recognize", "recognise", "find", "filter", "collect", "resolve", "locate",
        "classify", "determine", "check", "whether", "make", "create", "build",
        "write", "project", "code", "file", "files", "inside", "within", "from",
        "that", "this", "with", "without", "then", "otherwise", "else", "if",
        "not", "does", "do", "dont", "doesnt", "isnt", "are", "the", "and",
        "for", "into", "our", "my", "your", "all",
    }
    terms: list[str] = []
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", question or ""):
        low = token.lower()
        if len(low) < 3 or low in noise:
            continue
        if low.endswith("s") and len(low) > 4:
            low = low[:-1]
        if low not in terms:
            terms.append(low)

    # Keep useful semantic expansions deterministic.
    expansions = {
        "twist": ["twist", "segment", "roll"],
        "joint": ["joint", "bone", "chain", "hierarchy"],
        "rig": ["rig", "rigging", "skeleton"],
        "control": ["control", "ctrl"],
    }
    expanded: list[str] = []
    for term in terms:
        for value in expansions.get(term, [term]):
            if value not in expanded:
                expanded.append(value)
    return expanded[:12]


def _research_candidate_rows(
    question: str,
    active_path: str | None = None,
    *,
    limit: int = 16,
) -> list[dict]:
    """Return ranked symbols for behavioral research, not only name matches."""
    try:
        from tech_connector.knowledge.search import search_index_symbols
    except Exception:
        return []

    terms = _research_focus_terms(question)
    if not terms:
        return []

    scope = detect_search_scope(question)
    roots = _active_project_roots(active_path)
    rows = search_index_symbols(
        terms,
        limit=max(limit * 4, 40),
        active_path=active_path,
        class_bias=False,
        scope=scope,
        project_roots=roots,
    )

    action_words = ("find", "filter", "get", "resolve", "collect", "list", "detect", "identify", "classify")
    creation_words = ("create", "setup", "build", "make", "show", "driver")
    domain_terms = [term for term in terms if term not in {"find", "filter", "get", "resolve"}]

    ranked: list[dict] = []
    for raw in rows or []:
        row = dict(raw)
        if not _is_user_source_row(row):
            continue
        name = str(row.get("name") or row.get("qualname") or "").lower()
        signature = str(row.get("signature") or "").lower()
        doc = str(row.get("docstring") or "").lower()
        source = str(row.get("source") or "").lower()
        haystack = " ".join((name, signature, doc, source))

        score = 0.0
        evidence: list[str] = []

        for term in domain_terms:
            if term in name:
                score += 8.0
                evidence.append(f"name:{term}")
            elif term in signature:
                score += 4.0
                evidence.append(f"signature:{term}")
            elif term in doc:
                score += 3.0
                evidence.append(f"docstring:{term}")
            elif term in source:
                score += 1.5
                evidence.append(f"source:{term}")

        if any(word in name for word in action_words):
            score += 6.0
            evidence.append("resolver/filter naming")
        if any(word in name for word in creation_words):
            score -= 2.0
            evidence.append("creation/setup naming")

        # Behavioral evidence: likely traversal/filtering rather than setup.
        behavior_patterns = {
            "hierarchy traversal": r"\b(listRelatives|descendants?|children|parent|hierarchy|walk|traverse)\b",
            "joint type check": r"\b(nodeType|objectType|type\s*==\s*['\"]joint|is.*joint)\b",
            "name filtering": r"\b(re\.search|re\.match|endswith|startswith|split|lower\(\)|casefold\(\))\b",
            "list filtering": r"\b(filter\(|\[.*for .* in .*\]|append\(|extend\()\b",
            "mapping lookup": r"\b(mapping|joint_map|body_joint_map|face_joint_map|get\()\b",
        }
        for label, pattern in behavior_patterns.items():
            if re.search(pattern, haystack, re.IGNORECASE):
                score += 2.5
                evidence.append(label)

        row["research_score"] = round(score, 2)
        row["research_evidence"] = list(dict.fromkeys(evidence))
        if score > 0:
            ranked.append(row)

    ranked.sort(
        key=lambda row: (
            -float(row.get("research_score") or 0.0),
            str(row.get("rel_path") or row.get("path") or "").lower(),
            int(row.get("start_line") or 0),
        )
    )
    return ranked[:max(1, int(limit or 16))]


def _dedicated_behavior_match(
    rows: list[dict],
    focus_terms: list[str],
) -> dict | None:
    """Return a high-confidence dedicated detector/helper, if one exists."""
    domain_terms = [
        term for term in focus_terms
        if term not in {"segment", "roll", "bone", "chain", "hierarchy", "rigging", "skeleton"}
    ]
    for row in rows:
        name = str(row.get("name") or row.get("qualname") or "").lower()
        score = float(row.get("research_score") or 0.0)
        action_match = bool(
            re.search(r"(?:^|_)(find|filter|get|resolve|collect|list|detect|identify|classify)(?:_|$)", name)
        )
        domain_match = any(term in name for term in domain_terms)
        if action_match and domain_match and score >= 12.0:
            return row
    return None


def _suggest_research_helper(
    question: str,
    active_path: str | None,
    rows: list[dict],
) -> str:
    """Return a grounded helper design when no dedicated equivalent exists."""
    focus = _research_focus_terms(question)
    target_file = ""
    if active_path:
        target_file = str(active_path)
    elif rows:
        target_file = str(rows[0].get("rel_path") or rows[0].get("path") or "")

    subject = " ".join(term for term in focus if term not in {"joint", "bone"}) or "target joints"
    helper_name = "find_twist_joints" if "twist" in focus else "find_matching_joints"

    lines = [
        "Suggested helper design:",
        f"- Name: `{helper_name}`",
        f"- Likely target: `{target_file or 'the existing rigging utility module'}`",
        "- Keep it read-only: return existing joint names and do not modify the Maya scene.",
        "- Accept either a root joint or an explicit joint list.",
        "- Traverse descendants only when a root is supplied.",
        "- Filter to Maya joint nodes before applying naming or metadata rules.",
        f"- Match {subject} using configurable tokens rather than one hard-coded spelling.",
        "- Preserve hierarchy order and remove duplicates.",
        "- Optionally expose strict and permissive matching modes.",
        "",
        "Implementation shape:",
        "```python",
        f"def {helper_name}(root_joint=None, joints=None, tokens=(\"twist\",), include_root=False):",
        "    \"\"\"Return existing twist joints without mutating the scene.\"\"\"",
        "    candidates = list(joints or [])",
        "    if root_joint:",
        "        descendants = cmds.listRelatives(root_joint, ad=True, type=\"joint\") or []",
        "        candidates.extend(descendants)",
        "        if include_root and cmds.nodeType(root_joint) == \"joint\":",
        "            candidates.append(root_joint)",
        "",
        "    lowered_tokens = tuple(str(token).casefold() for token in tokens if token)",
        "    result = []",
        "    seen = set()",
        "    for joint in reversed(candidates):",
        "        short_name = joint.rsplit(\"|\", 1)[-1].casefold()",
        "        if joint in seen or not any(token in short_name for token in lowered_tokens):",
        "            continue",
        "        seen.add(joint)",
        "        result.append(joint)",
        "    return result",
        "```",
        "",
        "Before adding it, inspect the closest candidates below for project-specific naming, mapping, and hierarchy conventions.",
    ]
    return "\n".join(lines)


def answer_project_research_question(
    question: str,
    active_path: str | None = None,
) -> str | None:
    """Answer semantic project research with existence analysis and fallback."""
    if not is_project_research_request(question):
        return None

    rows = _research_candidate_rows(question, active_path=active_path, limit=12)
    focus = _research_focus_terms(question)
    dedicated = _dedicated_behavior_match(rows, focus)

    if dedicated:
        signature = (
            dedicated.get("signature")
            or dedicated.get("qualname")
            or dedicated.get("name")
            or ""
        )
        location = dedicated.get("rel_path") or dedicated.get("path") or ""
        line = dedicated.get("start_line")
        lines = [
            "Yes. I found a likely dedicated helper for that behavior.",
            "",
            f"- `{signature}`",
            f"- Location: `{location}`" + (f", line `{line}`" if line else ""),
            "- Evidence: " + ", ".join(dedicated.get("research_evidence") or ["semantic symbol match"]),
            "",
            "Closest supporting candidates:",
        ]
    else:
        lines = [
            "I did not find a high-confidence dedicated helper that performs that detection behavior.",
            "",
            _suggest_research_helper(question, active_path, rows),
            "",
            "Closest supporting candidates:",
        ]

    if not rows:
        lines.append("- No relevant indexed symbols were found.")
    else:
        for row in rows[:6]:
            signature = row.get("signature") or row.get("qualname") or row.get("name") or ""
            location = row.get("rel_path") or row.get("path") or ""
            line = row.get("start_line")
            evidence = ", ".join(row.get("research_evidence") or [])
            lines.append(
                f"- `{signature}` in `{location}`"
                + (f":{line}" if line else "")
                + (f" — {evidence}" if evidence else "")
            )

    lines.extend(
        [
            "",
            "Conclusion basis: indexed names, signatures, docstrings, and source excerpts were compared for actual detector/filter behavior rather than only matching the domain word.",
            "Source: local project knowledge index.",
        ]
    )
    return "\n".join(lines)


def _semantic_contract_for_question(question: str) -> dict:
    try:
        from tech_connector.services.reasoning.semantic_execution_contract_service import (
            build_semantic_execution_contract,
        )
        return build_semantic_execution_contract(question).to_dict()
    except Exception:
        return {}


def _answer_contract_file_location_question(
    question: str,
    active_path: str | None = None,
    *,
    semantic_contract: dict | None = None,
) -> str | None:
    contract = dict(semantic_contract or {}) or _semantic_contract_for_question(question)
    if not contract:
        return None
    if str(contract.get("goal_type") or "") != "locate":
        return None
    if str(contract.get("deliverable_type") or "") != "file":
        return None
    if str(contract.get("relationship") or "") != "contains":
        return None

    behavior = str(
        contract.get("behavior")
        or contract.get("subject_text")
        or ""
    ).strip()
    if not behavior:
        return None

    terms = _function_location_terms(
        f"what file has a function to {behavior}",
        active_path=active_path,
    )
    rows = _function_location_rows(
        terms,
        active_path=active_path,
        question=question,
        limit=12,
    )
    if not rows:
        return (
            f"I understood this as: `{contract.get('goal')}`\n\n"
            "I could not find a project function with enough evidence to resolve "
            "the containing file.\n\n"
            "Verification: refresh the project index and retry."
        )

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        path = str(row.get("rel_path") or row.get("path") or "")
        grouped.setdefault(path, []).append(row)

    ranked_files = sorted(
        grouped.items(),
        key=lambda item: (
            -max(int(row.get("match_score") or 0) for row in item[1]),
            item[0].lower(),
        ),
    )

    best_path, best_rows = ranked_files[0]
    lines = [
        f"Best match: `{best_path}`",
        "",
        f"Understanding: {contract.get('goal')}",
        "",
        "Supporting functions:",
    ]
    for row in best_rows[:6]:
        signature = (
            row.get("signature")
            or row.get("qualname")
            or row.get("name")
            or ""
        )
        line = row.get("start_line")
        score = row.get("match_score")
        lines.append(
            f"- `{signature}`"
            + (f" on line `{line}`" if line else "")
            + (f" — evidence score `{score}`" if score is not None else "")
        )

    if len(ranked_files) > 1:
        lines.extend(["", "Other plausible files:"])
        for path, file_rows in ranked_files[1:4]:
            score = max(int(row.get("match_score") or 0) for row in file_rows)
            lines.append(f"- `{path}` — best evidence score `{score}`")

    lines.extend(
        [
            "",
            "Answer contract:",
            "- deliverable: file path",
            "- supporting evidence: contained function names",
            "- relationship: file contains behavior implementation",
            "",
            "Source: local project knowledge index.",
        ]
    )
    return "\n".join(lines)

def answer_simple_project_index_question(
    question: str,
    active_path: str | None = None,
    *,
    semantic_contract: dict | None = None,
) -> str | None:
    """Answer small factual project-index questions without LLM involvement."""
    lower = (question or "").lower()
    if not is_project_scope_request(question):
        return None

    scoped_answer = answer_scoped_member_behavior_question(
        question,
        active_path=active_path,
    )
    if scoped_answer:
        return scoped_answer

    location_answer = _answer_function_location_question(question, active_path=active_path)
    if location_answer:
        return location_answer

    contract_file_answer = _answer_contract_file_location_question(
        question,
        active_path=active_path,
        semantic_contract=semantic_contract,
    )
    if contract_file_answer:
        return contract_file_answer

    research_answer = answer_project_research_question(question, active_path=active_path)
    if research_answer:
        return research_answer

    equivalence_answer = _answer_file_symbol_equivalence_question(question, active_path=active_path)
    if equivalence_answer:
        return equivalence_answer

    symbol_answer = _answer_file_symbol_question(question, active_path=active_path)
    if symbol_answer:
        return symbol_answer

    maya_qt_answer = _answer_maya_qt_ui_class_question(
        question,
        active_path=active_path,
    )
    if maya_qt_answer:
        return maya_qt_answer

    if re.search(
        r"\b(what|which)\s+class\b|\bclass\s+(?:do|can|should)\s+i\b|"
        r"\bdo\s+(?:we|i)\s+have\s+(?:any\s+)?class\b|\bare\s+there\s+(?:any\s+)?classes\b",
        lower,
    ):
        from tech_connector.knowledge.search import extract_code_search_terms, search_index_classes

        terms = extract_code_search_terms(question)
        rows = search_index_classes(
            terms=terms,
            limit=5,
            active_path=active_path,
            scope=detect_search_scope(question),
            project_roots=_active_project_roots(active_path),
        )
        if rows:
            best = rows[0]
            source = str(best.get("source") or "")
            api_evidence = [
                term for term in terms
                if term.lower() in source.lower() and term.lower() not in {"directory", "folder"}
            ]
            api_evidence.sort(
                key=lambda term: (
                    0 if term.lower() in {"getexistingdirectory", "qfiledialog", "qtwidgets.qfiledialog"} else 1,
                    terms.index(term),
                )
            )
            api_evidence = api_evidence[:5]
            lines = [
                f"Yes. Best match: `{best.get('qualname') or best.get('name')}`",
                f"File: `{best.get('path')}`",
            ]
            if api_evidence:
                lines.append("Supporting API evidence: " + ", ".join(f"`{term}`" for term in api_evidence))
            alternatives = rows[1:3]
            if alternatives:
                lines.extend(["", "Other plausible classes:"])
                lines.extend(
                    f"- `{item.get('qualname') or item.get('name')}` in `{item.get('path')}`"
                    for item in alternatives
                )
            lines.extend(["", "Source: local project knowledge index."])
            return "\n".join(lines)

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


def _maya_qt_ui_evidence_rows(active_path: str | None = None) -> list[dict]:
    """Return first-party Qt classes and launchers relevant to Maya UI planning."""
    from tech_connector.knowledge.search import search_index_classes, search_index_symbols

    project_roots = _active_project_roots(active_path)
    classes: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    for base_term in ("QtWidgets.QDialog", "QtWidgets.QWidget", "QtWidgets.QMainWindow"):
        for row in search_index_classes(
            terms=[base_term],
            limit=120,
            active_path=active_path,
            scope=detect_search_scope("Maya project UI classes"),
            project_roots=project_roots,
        ):
            path = str(row.get("path") or "")
            normalized_path = path.replace("\\", "/").lower()
            if "/maya_tools/" not in normalized_path and "/custom_qt/" not in normalized_path:
                continue
            source = str(row.get("source") or "")
            declaration = source.splitlines()[0] if source else ""
            base_match = re.search(r"^class\s+[^(:]+\(([^)]*)\)", declaration.strip())
            base_class = base_match.group(1).strip() if base_match else ""
            if not re.search(r"\b(?:QtWidgets\.)?Q(?:Dialog|Widget|MainWindow)\b", base_class):
                continue
            key = (
                path.lower(),
                str(row.get("qualname") or row.get("name") or "").lower(),
                int(row.get("start_line") or 0),
            )
            if key in seen:
                continue
            seen.add(key)
            item = dict(row)
            item["base_class"] = base_class
            item["maya_hosted"] = "/maya_tools/" in normalized_path
            parent_evidence = ""
            if "wrapInstance(" in source:
                parent_evidence = "wrapInstance(..., QtWidgets.QMainWindow)"
            elif re.search(r"get_(?:maya_)?main_window", source, re.I):
                parent_evidence = "Maya main-window parent helper"
            item["parent_evidence"] = parent_evidence
            item["planning_score"] = (
                (100 if item["maya_hosted"] else 50)
                + (40 if parent_evidence else 0)
            )
            classes.append(item)

    launch_rows = search_index_symbols(
        ["launch", "show"],
        limit=300,
        active_path=active_path,
        class_bias=False,
        scope=detect_search_scope("Maya project UI classes"),
        project_roots=project_roots,
    )
    for item in classes:
        class_name = str(item.get("name") or "")
        class_path = str(item.get("path") or "").lower()
        launchers = []
        for row in launch_rows:
            if str(row.get("kind") or "") != "function":
                continue
            if str(row.get("path") or "").lower() != class_path:
                continue
            source = str(row.get("source") or "")
            if class_name in source and ".show(" in source:
                launchers.append(
                    {
                        "name": row.get("qualname") or row.get("name"),
                        "line": row.get("start_line"),
                    }
                )
        item["launchers"] = launchers

    return sorted(
        classes,
        key=lambda item: (
            -int(item.get("planning_score") or 0),
            str(item.get("path") or "").lower(),
            int(item.get("start_line") or 0),
        ),
    )


def _format_maya_qt_ui_evidence(rows: list[dict]) -> str:
    if not rows:
        return "No indexed first-party Maya Qt UI classes were found."
    lines = [
        "Existing Maya Qt UI evidence:",
        "",
        "Maya-hosted windows:",
    ]
    hosted = [row for row in rows if row.get("maya_hosted")]
    reusable = [row for row in rows if not row.get("maya_hosted")]
    for row in hosted[:10]:
        detail = f"base `{row.get('base_class')}`"
        if row.get("parent_evidence"):
            detail += f"; parent pattern `{row.get('parent_evidence')}`"
        launchers = row.get("launchers") or []
        if launchers:
            detail += "; launcher " + ", ".join(
                f"`{launcher.get('name')}` line `{launcher.get('line')}`"
                for launcher in launchers
            )
        lines.append(
            f"- `{row.get('qualname') or row.get('name')}` in `{row.get('path')}` "
            f"line `{row.get('start_line')}` - {detail}"
        )
    if reusable:
        lines.extend(["", "Reusable Qt components:"])
        for row in reusable[:10]:
            lines.append(
                f"- `{row.get('qualname') or row.get('name')}` in `{row.get('path')}` "
                f"line `{row.get('start_line')}` - base `{row.get('base_class')}`"
            )
    lines.extend(
        [
            "",
            "Planning constraint: decide whether to reuse these classes or use their "
            "Maya parenting, lifecycle, and launch conventions before proposing a new UI class.",
            "Source: local project knowledge index.",
        ]
    )
    return "\n".join(lines)


def _answer_maya_qt_ui_class_question(
    question: str,
    *,
    active_path: str | None = None,
) -> str | None:
    lower = (question or "").lower()
    if "maya" not in lower:
        return None
    if not re.search(r"\b(qt|pyside|ui|widget|dialog|window)\b", lower):
        return None
    if not re.search(r"\b(class|classes|existing|reuse|pattern|open|launch|tool|tools)\b", lower):
        return None
    return _format_maya_qt_ui_evidence(_maya_qt_ui_evidence_rows(active_path))


def _dependency_graph_rows(question: str, active_path: str | None = None, limit: int = 80) -> list[dict]:
    try:
        from tech_connector.models.constants import project_index_db_path
        from tech_connector.knowledge.search import extract_code_search_terms
    except Exception:
        return []
    if not project_index_db_path().exists():
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
        with _connect_index_readonly(project_index_db_path(), timeout=5) as conn:
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

    if _parse_scoped_member_request(question) is not None:
        return ProjectSearchMode.RESEARCH
    if is_project_research_request(question):
        return ProjectSearchMode.RESEARCH

    if re.search(
        r"^\s*(?:do\s+(?:we|i)\s+have|are\s+there|is\s+there|what|which)\b",
        lower,
    ) and re.search(r"\b(class|classes|widget|widgets)\b", lower):
        return ProjectSearchMode.CLASS

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
    from tech_connector.knowledge.search import (
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
        if mode == ProjectSearchMode.RESEARCH:
            answer = (
                answer_scoped_member_behavior_question(
                    question,
                    active_path=active_path,
                )
                or answer_project_research_question(
                    question,
                    active_path=active_path,
                )
            )
            return "\n".join(header) + (
                answer
                or "No semantic research evidence was found in the project index."
            )

        if mode == ProjectSearchMode.TARGET_EDIT:
            from tech_connector.services.project_service import discover_edit_targets, format_edit_target_context
            discovery = discover_edit_targets(question, active_path=active_path, limit=min(limit, 10), scope=scope)
            ui_evidence = _answer_maya_qt_ui_class_question(
                question,
                active_path=active_path,
            )
            evidence_section = f"{ui_evidence}\n\n" if ui_evidence else ""
            return "\n".join(header) + evidence_section + format_edit_target_context(discovery)

        if mode == ProjectSearchMode.UNUSED_FILES:
            from tech_connector.knowledge.search import analyze_unused_files, analyze_unused_imports, format_graph_analysis_context
            unused = analyze_unused_files(scope=scope, limit=limit)
            unused_imports = analyze_unused_imports(scope=scope, limit=min(limit, 80))
            return "\n".join(header) + format_graph_analysis_context(unused) + "\n\n" + format_graph_analysis_context(unused_imports)

        if mode == ProjectSearchMode.UNUSED_IMPORTS:
            from tech_connector.knowledge.search import analyze_unused_imports, format_graph_analysis_context
            result = analyze_unused_imports(scope=scope, limit=limit)
            return "\n".join(header) + format_graph_analysis_context(result)

        if mode == ProjectSearchMode.DEPENDENTS and first_term:
            from tech_connector.knowledge.search import find_file_dependents, format_graph_analysis_context
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
                from tech_connector.services.project_service import discover_edit_targets

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
    if is_project_research_request(question):
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
