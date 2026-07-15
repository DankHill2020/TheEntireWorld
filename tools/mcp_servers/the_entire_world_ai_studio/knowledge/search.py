from __future__ import annotations

"""Local file and project search."""

from pathlib import Path
import re
import textwrap

from knowledge.python_ast import (
    extract_python_symbols_from_text,
    question_terms,
    rank_symbols_for_question,
    summarize_python_symbol,
)
from models.files import is_supported_code_file
from editor.diff import build_safe_patch_for_symbol
from models.constants import SKIP_DIRS, SUPPORTED_CODE_EXTS


def get_installed_ollama_models() -> list[str]:
    import urllib.request
    import json
    try:
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open("http://127.0.0.1:11434/api/tags", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def resolve_installed_ollama_model(model: str, installed: list[str], *, prefer_coder: bool = False) -> str:
    """Return an installed Ollama model tag for a requested model name."""

    requested = (model or "").replace("ollama:", "", 1).strip()
    if not installed:
        return requested or "qwen2.5-coder:1.5b"

    installed_names = [m.lower() for m in installed]
    req_lower = requested.lower()
    coder_models = [m for m in installed if "coder" in m.lower()]
    if prefer_coder and _is_tiny_model(req_lower) and coder_models:
        balanced = _balanced_local_coder_model(coder_models)
        if balanced:
            return balanced
    if req_lower in installed_names:
        return installed[installed_names.index(req_lower)]

    if prefer_coder and coder_models:
        return coder_models[0]

    req_clean = req_lower.split(":")[0]
    same_family = [
        model_name
        for model_name in installed
        if model_name.lower().split(":")[0] == req_clean
    ]
    if same_family:
        return same_family[0]

    if coder_models:
        return coder_models[0] if prefer_coder else installed[0]
    return installed[0]


def _is_tiny_model(model: str) -> bool:
    text = (model or "").lower()
    return bool(re.search(r"(?<!\d)(?:0\.[0-9]+|1(?:\.[0-9]+)?|2(?:\.[0-9]+)?|3(?:\.[0-9]+)?)b\b", text))


def _balanced_local_coder_model(models: list[str]) -> str:
    def score(name: str) -> float:
        text = (name or "").lower()
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b\b", text)
        size = float(match.group(1)) if match else 0.0
        if 7.0 <= size <= 16.0:
            return 100.0 - abs(size - 14.0)
        if size > 16.0:
            return 50.0 - min(size, 100.0) / 100.0
        return size

    ranked = sorted((m for m in models if m), key=score, reverse=True)
    return ranked[0] if ranked else ""


def query_ollama_text(
    model: str,
    system_prompt: str,
    user_prompt: str,
    num_ctx: int = 8192,
    num_predict: int = 2048,
    timeout: int = 120,
    prefer_coder: bool = False,
):
    import urllib.request
    import json
    try:
        from services.ollama_resource_service import build_ollama_options, ollama_keep_alive
        from services.settings_service import load_settings
        settings = load_settings()
        options = build_ollama_options(num_ctx=num_ctx, num_predict=num_predict, settings=settings)
        keep_alive = ollama_keep_alive(settings)
    except Exception:
        options = {
            "temperature": 0.2,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        }
        keep_alive = "10m"
    
    model = (model or "").replace("ollama:", "", 1).strip()
    
    installed = get_installed_ollama_models()
    model = resolve_installed_ollama_model(model, installed, prefer_coder=prefer_coder)
            
    # Normalize model name for display
    model = model.replace("ollama:", "", 1).strip()
    print(f"[Ollama Status] Active model: {model}", flush=True)
        
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "keep_alive": keep_alive,
        "options": options,
    }).encode("utf-8")
    
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        proxy_handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(req, timeout=timeout) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["message"]["content"]
    except Exception as e:
        print(f"Error querying Ollama ({model}): {e}")
        return None


def is_scrolling_restoration_query(question: str) -> bool:
    q = question.lower()
    return (
        any(w in q for w in ["how", "tell me how", "restore", "enable"]) and
        any(w in q for w in ["scrollable", "scroll", "scrolling"]) and
        any(w in q for w in ["nonscrollingspinbox", "nonscollablespinbox", "nonscrollable"])
    )


def is_editor_generation_request(question: str) -> bool:
    q = (question or "").lower()
    if is_advisory_design_question(question):
        return False
    edit_intent = re.search(
        r"\b(add|create|make|implement|generate|write|modify|change|update|fix|refactor|replace|remove|delete|insert)\b",
        q,
    )
    code_target = re.search(
        r"\b(class|function|method|file|module|tool|widget|spinbox|button|dialog|code|bug|error|issue|feature|doc|docs|documentation|docstring|readme|changelog|guide|tutorial|api reference)\b",
        q,
    )
    documentation_request = re.search(
        r"\b(document|documentation|docstring|readme|changelog|guide|tutorial|api reference)\b",
        q,
    )
    direct_edit_phrase = re.search(
        r"\b(apply|edit|patch|change this|update this|fix this|make it|make this)\b",
        q,
    )
    return bool((edit_intent and code_target) or documentation_request or direct_edit_phrase)


def is_advisory_design_question(question: str) -> bool:
    q = (question or "").lower()
    return bool(
        re.search(r"\b(what|which)\s+(class|function|method|widget)\s+could\s+i\s+(make|create|add|write)\b", q)
        or re.search(r"\bwhat\s+could\s+i\s+(make|create|add|write)\b", q)
        or re.search(r"\b(what|which)\s+.*\b(should|could)\s+i\s+(make|create|add|write)\b", q)
        or re.search(r"\b(suggest|recommend)\s+(a|an|some)?\s*(class|function|method|widget|approach)\b", q)
    )


def is_fast_local_analysis_question(question: str) -> bool:
    q = (question or "").lower()
    if is_editor_generation_request(question):
        return False
    return is_advisory_design_question(question) or bool(
        re.search(r"\b(what does|what is|explain|summarize|describe|where is|which class|which function)\b", q)
    )


def _camel_name(words: list[str], fallback: str = "CustomWidget") -> str:
    parts = []
    for word in words:
        clean = re.sub(r"[^A-Za-z0-9_]", "", word or "")
        if not clean:
            continue
        parts.append(clean[:1].upper() + clean[1:])
    return "".join(parts) or fallback


def _suggested_symbol_name(question: str, current_name: str) -> str:
    q = (question or "").lower()
    colors = [
        "blue", "red", "green", "yellow", "purple", "orange", "black", "white", "gray", "grey",
    ]
    widgets = [
        ("text field", "TextField"),
        ("textfield", "TextField"),
        ("line edit", "LineEdit"),
        ("lineedit", "LineEdit"),
        ("spin box", "SpinBox"),
        ("spinbox", "SpinBox"),
        ("button", "Button"),
        ("dialog", "Dialog"),
        ("widget", "Widget"),
    ]
    name_parts = []
    color = next((c for c in colors if re.search(rf"\b{re.escape(c)}\b", q)), "")
    if color:
        name_parts.append(color)
    for phrase, label in widgets:
        if phrase in q:
            name_parts.append(label)
            break
    if name_parts and "Widget" not in name_parts[-1]:
        name_parts.append("Widget")
    if not name_parts:
        return f"Custom{current_name}" if current_name else "CustomWidget"
    return _camel_name(name_parts)


def summarize_advisory_symbol(sym: dict, question: str) -> str:
    name = sym.get("name", "")
    kind = sym.get("kind", "symbol")
    source = sym.get("source", "")
    methods = sym.get("methods", [])
    lowered = source.lower()
    suggested_name = _suggested_symbol_name(question, name)

    responsibilities = []
    if "qwidget" in lowered:
        responsibilities.append("already follows a `QWidget` wrapper pattern")
    if "qlineedit" in lowered:
        responsibilities.append("contains a `QLineEdit`, so it is a strong reference for text-field behavior")
    if "qpushbutton" in lowered:
        responsibilities.append("adds a button beside the field")
    if "stylesheet" in lowered:
        responsibilities.append("uses Qt stylesheets for visual styling")
    if "qfiledialog" in lowered:
        responsibilities.append("includes browse/file-dialog behavior that you can keep or omit")

    out = [
        "Editor Assist",
        "",
        f"Best reference in this file: `{name}` ({kind}, lines {sym.get('start')}-{sym.get('end')}).",
        f"A good class to make would be `{suggested_name}`.",
        "",
        "Why this match:",
    ]
    if responsibilities:
        out.extend(f"- It {item}." for item in responsibilities[:4])
    else:
        out.append("- It is the closest local class match by name and contents.")

    out.extend([
        "",
        "Recommended shape:",
        f"- Base it on `{name}` only if you want the same text-field/layout pattern.",
        f"- Subclass `{name}` if the new class should preserve most of its behavior and only change styling or a small interaction.",
        f"- Make a separate fresh class if the new widget should be simpler than `{name}`.",
        "- Keep the public API small: `text()`, `setText(value)`, and maybe a `textChanged` signal passthrough.",
        "- Put the blue styling on the `QLineEdit` if only the field should be blue, or on the wrapper widget if the whole control should be blue.",
    ])
    if "qfiledialog" in lowered:
        out.append("- Drop the Browse button/dialog parts if this is just a styled text field instead of a directory picker.")
    if methods:
        out.append(f"- Existing methods to study: {', '.join(f'`{m}`' for m in methods[:5])}.")

    out.extend([
        "",
        "No edit was proposed because the question asked for a design suggestion, not an implementation.",
    ])
    return "\n".join(out)


def summarize_compact_python_symbol(sym: dict, question: str) -> str:
    name = sym.get("name", "")
    kind = sym.get("kind", "symbol")
    source = sym.get("source", "")
    methods = sym.get("methods", [])
    lowered = source.lower()

    out = [
        "Editor Assist",
        "",
        f"Best match: `{name}` ({kind}, lines {sym.get('start')}-{sym.get('end')}).",
    ]

    if kind == "class":
        bases = []
        try:
            import ast

            tree = ast.parse(source)
            cls = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
            if cls:
                for base in cls.bases:
                    try:
                        bases.append(ast.unparse(base))
                    except Exception:
                        pass
        except Exception:
            pass
        if bases:
            out.append(f"It subclasses `{', '.join(bases)}`.")

        behavior = []
        if "qlineedit" in lowered:
            behavior.append("uses a `QLineEdit` for editable text")
        if "qpushbutton" in lowered:
            behavior.append("includes a push button")
        if "qfiledialog.getexistingdirectory" in lowered:
            behavior.append("opens a directory picker")
        if "textchanged.connect" in lowered:
            behavior.append("syncs internal state when text changes")
        if "setstylesheet" in lowered:
            behavior.append("applies Qt stylesheet styling")
        if behavior:
            out.append("")
            out.append("What it does:")
            out.extend(f"- It {item}." for item in behavior[:5])
        elif methods:
            out.append("")
            out.append("Key methods:")
            out.extend(f"- `{method}`" for method in methods[:6])
    else:
        out.append("It is the closest function match in the open file.")

    concerns = []
    if "directory.replace" in source and "directory=None" in source:
        concerns.append("`directory.replace(...)` can fail if `directory` is `None`.")
    if "new_height = 10" in source:
        concerns.append("The repeated fixed height of `10` may make the UI cramped.")
    if concerns:
        out.append("")
        out.append("Worth checking:")
        out.extend(f"- {concern}" for concern in concerns)

    out.extend([
        "",
        "No edit was proposed because this was answered as analysis, not an implementation request.",
    ])
    return "\n".join(out)


def retrieve_relevant_files_context(project_roots: list[str], question: str, exclude_path: str = None) -> str:
    terms = [t for t in question_terms(question) if len(t) > 3]
    if not terms:
        return ""
        
    matched_files = {}
    
    import sqlite3
    from models.constants import V2_DB
    
    db_success = False
    if V2_DB.exists():
        try:
            with sqlite3.connect(str(V2_DB), timeout=30) as conn:
                conn.execute("PRAGMA busy_timeout = 30000")
                conn.execute("PRAGMA journal_mode=WAL")
                cursor = conn.cursor()
                # Pre-filter files containing at least one term in their name or path
                clauses = []
                params = []
                for t in terms:
                    clauses.append("path LIKE ?")
                    params.append(f"%{t}%")
                
                query = "SELECT path FROM files"
                if clauses:
                    query += " WHERE " + " OR ".join(clauses)
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                for row in rows:
                    filepath = row[0]
                    path_obj = Path(filepath)
                    if any(skip in path_obj.parts for skip in SKIP_DIRS):
                        continue
                    if exclude_path and str(path_obj.resolve()) == str(Path(exclude_path).resolve()):
                        continue
                    score = sum(2 for t in terms if t in path_obj.name.lower())
                    if score > 0:
                        matched_files[str(path_obj.resolve())] = score
                db_success = True
        except Exception as e:
            print(f"Error querying files database: {e}")
            
    if not db_success:
        for root in project_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            for p in root_path.rglob("*"):
                if p.is_file() and p.suffix.lower() in SUPPORTED_CODE_EXTS:
                    if any(skip in p.parts for skip in SKIP_DIRS):
                        continue
                    if exclude_path and str(p.resolve()) == str(Path(exclude_path).resolve()):
                        continue
                    score = sum(2 for t in terms if t in p.name.lower())
                    if score > 0:
                        matched_files[str(p.resolve())] = score
                        
    sorted_files = sorted(matched_files.items(), key=lambda x: x[1], reverse=True)
    context_parts = []
    for filepath, score in sorted_files[:2]:
        try:
            content = Path(filepath).read_text(encoding="utf-8", errors="replace")
            if len(content) > 4000:
                content = content[:4000] + "\n... [truncated] ..."
            context_parts.append(
                f"File: {filepath}\n"
                f"Content:\n"
                f"```\n{content}\n```\n"
            )
        except Exception:
            pass
            
    if context_parts:
        return "\n--- Relevant Project Context ---\n" + "\n".join(context_parts)
    return ""


def retrieve_similar_project_symbols(symbol_name: str, exclude_file_path: str = None) -> list:
    import sqlite3
    from models.constants import V2_DB
    if not V2_DB.exists():
        return []
        
    tokens = [t.lower() for t in re.split(r"_+", symbol_name) if len(t) > 2]
    if not tokens:
        return []
        
    try:
        with sqlite3.connect(str(V2_DB), timeout=30) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            
            query = """
                SELECT s.name, s.signature, s.docstring, f.path, s.kind
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE 1=1
            """
            params = []
            
            token_filters = []
            for t in tokens:
                token_filters.append("s.name LIKE ?")
                params.append(f"%{t}%")
            
            if token_filters:
                query += " AND (" + " OR ".join(token_filters) + ")"
                
            if exclude_file_path:
                query += " AND f.path != ?"
                params.append(str(Path(exclude_file_path).resolve()))
                
            query += " LIMIT 5"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "name": row[0],
                    "signature": row[1],
                    "docstring": row[2],
                    "file_path": row[3],
                    "kind": row[4]
                })
            return results
    except Exception as e:
        print(f"Error querying similar symbols: {e}")
        return []


def search_project_symbols_by_keywords(keywords: list[str]) -> list:
    import sqlite3
    from models.constants import V2_DB
    if not V2_DB.exists():
        return []
    try:
        with sqlite3.connect(str(V2_DB), timeout=30) as conn:
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            
            query = """
                SELECT s.name, s.signature, s.docstring, f.path, s.kind, s.source
                FROM symbols s
                JOIN files f ON s.file_id = f.id
                WHERE 1=1
            """
            params = []
            for kw in keywords:
                query += " AND (s.name LIKE ? OR s.docstring LIKE ? OR s.searchable_text LIKE ?)"
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")
                params.append(f"%{kw}%")
                
            query += " LIMIT 8"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "name": row[0],
                    "signature": row[1],
                    "docstring": row[2],
                    "file_path": row[3],
                    "kind": row[4],
                    "source": row[5]
                })
            return results
    except Exception as e:
        print(f"Error searching symbols by keywords: {e}")
        return []


def request_prefers_active_file(question: str) -> bool:
    q = (question or "").lower()
    additive = re.search(r"\b(add|create|make|define|insert|include|new)\b", q)
    code_unit = re.search(r"\b(class|function|method|widget|spinbox|button|dialog|control)\b", q)
    separate_artifact = re.search(
        r"\b(new|separate)\s+(tool|file|module|folder|package|plugin|script)\b|\bscaffold\b|\btool\b",
        q,
    )
    return bool(additive and code_unit and not separate_artifact)


def _looks_like_python_definition(source: str) -> bool:
    source = textwrap.dedent(source or "").strip()
    if not source:
        return False
    try:
        import ast

        tree = ast.parse(source)
    except SyntaxError:
        return bool(re.search(r"^\s*(class|def)\s+[A-Za-z_][A-Za-z0-9_]*\b", source, re.MULTILINE))
    return any(node.__class__.__name__ in {"ClassDef", "FunctionDef", "AsyncFunctionDef"} for node in tree.body)


def _active_file_addition_content(source: str) -> str:
    return textwrap.dedent(source or "").strip()


def normalize_active_file_additions(
    changes: list[dict],
    active_file_path: str,
    active_file_text: str,
    question: str,
) -> list[dict]:
    """Prefer inserting additive class/function requests into the active file."""
    if not changes or not active_file_path or not request_prefers_active_file(question):
        return changes

    active_path = str(Path(active_file_path).resolve())
    additions = []
    normalized = []

    for change in changes:
        action = change.get("action")
        path = str(Path(change.get("path", "")).resolve()) if change.get("path") else ""
        new_content = change.get("new_content", "")

        if (
            action == "create"
            and Path(path).suffix.lower() == ".py"
            and path != active_path
            and _looks_like_python_definition(new_content)
        ):
            additions.append(_active_file_addition_content(new_content))
            continue

        normalized.append(change)

    if not additions:
        return changes

    current = active_file_text or ""
    separator = "\n\n\n" if current.strip() else ""
    proposed = current.rstrip() + separator + "\n\n\n".join(additions) + "\n"
    normalized.append(
        {
            "action": "modify",
            "path": active_path,
            "original_content": current,
            "new_content": proposed,
        }
    )
    return normalized


def parse_multi_file_changes(content: str, project_root: str) -> list[dict]:
    changes = []
    
    # Parse create_file tags
    create_matches = re.finditer(r'<create_file\s+path=["\'](.*?)["\']\s*>\n?(.*?)\n?</create_file>', content, re.DOTALL)
    for m in create_matches:
        raw_path = m.group(1).strip()
        file_content = m.group(2)
        
        resolved_path = Path(raw_path)
        if not resolved_path.is_absolute() and project_root:
            resolved_path = Path(project_root) / raw_path
            
        changes.append({
            "action": "create",
            "path": str(resolved_path.resolve()),
            "new_content": file_content
        })
        
    # Parse modify_file tags
    modify_matches = re.finditer(r'<modify_file\s+path=["\'](.*?)["\']\s*>\n?(.*?)\n?</modify_file>', content, re.DOTALL)
    for m in modify_matches:
        raw_path = m.group(1).strip()
        body = m.group(2)
        
        resolved_path = Path(raw_path)
        if not resolved_path.is_absolute() and project_root:
            resolved_path = Path(project_root) / raw_path
            
        blocks = re.findall(r"<<<< ORIGINAL\n(.*?)\n====\n(.*?)\n>>>>", body, re.DOTALL)
        for original, replacement in blocks:
            changes.append({
                "action": "modify",
                "path": str(resolved_path.resolve()),
                "original_content": original,
                "new_content": replacement
            })
            
    return changes


def replace_content_resilient(full_content: str, original_block: str, replacement_block: str) -> tuple[bool, str]:
    if original_block in full_content:
        return True, full_content.replace(original_block, replacement_block)
        
    orig_norm = original_block.replace("\r\n", "\n").replace("\r", "\n")
    content_norm = full_content.replace("\r\n", "\n").replace("\r", "\n")
    if orig_norm in content_norm:
        content_norm = content_norm.replace(orig_norm, replacement_block.replace("\r\n", "\n").replace("\r", "\n"))
        return True, content_norm

    def clean_ws(s: str) -> str:
        return re.sub(r"\s+", "", s)
        
    orig_clean = clean_ws(original_block)
    if not orig_clean:
        return False, full_content
        
    char_map = []
    clean_content_parts = []
    for idx, char in enumerate(content_norm):
        if not char.isspace():
            clean_content_parts.append(char)
            char_map.append(idx)
            
    clean_content = "".join(clean_content_parts)
    match_idx = clean_content.find(orig_clean)
    if match_idx != -1:
        start_char_idx = char_map[match_idx]
        end_char_idx = char_map[match_idx + len(orig_clean) - 1] + 1
        
        while start_char_idx > 0 and content_norm[start_char_idx - 1] != "\n":
            start_char_idx -= 1
        while end_char_idx < len(content_norm) and content_norm[end_char_idx] != "\n":
            end_char_idx += 1
            
        new_content = content_norm[:start_char_idx] + replacement_block + content_norm[end_char_idx:]
        return True, new_content
        
    return False, full_content


def local_answer_about_file(path: str, question: str, text: str = None, query_llm: bool = True):
    """
    Answer a question about a file using local AST analysis.
    Returns (answer_text, optional_patch_dict).
    """
    from services.source_policy import check_moderation
    flagged, reason = check_moderation(question)
    if flagged:
        return f"[Moderation Warning] Request Blocked: The input {reason}. Generating malware or exploit code is restricted for safety.", None
    if text is None:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"[Editor Assist] Could not read file: {e}", None

    terms = question_terms(question)
    ext = Path(path).suffix.lower()

    output = []
    output.append("Editor Assist")
    output.append(f"File: {path}")
    output.append(f"Question: {question}")
    output.append("")

    if ext == ".py":
        symbols = extract_python_symbols_from_text(text)
        ranked = rank_symbols_for_question(symbols, terms)

        if ranked:
            best_score, best = ranked[0]
            
            edit_mode = is_editor_generation_request(question)
            if is_advisory_design_question(question):
                return summarize_advisory_symbol(best, question), None
            if is_fast_local_analysis_question(question):
                return summarize_compact_python_symbol(best, question), None

            try:
                from services.settings_service import load_settings
                settings = load_settings()
            except Exception:
                settings = {}

            # Fetch relevant project context matching query terms for automated context
            from models.project import all_roots
            roots = all_roots(settings)
            context_str = retrieve_relevant_files_context(roots, question, exclude_path=path)

            # Check for similar symbols in the project based on the active symbol name
            similar_symbols = retrieve_similar_project_symbols(best.get('name', ''), exclude_file_path=path)
            if similar_symbols:
                context_str += "\n\n--- Similar/Alternative Symbols Found in Project ---\n"
                for s in similar_symbols:
                    context_str += (
                        f"- Symbol: {s['name']}{s['signature'] or ''} ({s['kind']})\n"
                        f"  File Path: {s['file_path']}\n"
                        f"  Docstring: {s['docstring'] or 'No docstring'}\n\n"
                    )

            # Search database for symbols matching key terms of the question to locate potential duplicates
            stopwords = {
                "think", "have", "multiple", "functions", "that", "does", "do", "this", "specific",
                "thing", "can", "you", "tell", "me", "what", "they", "are", "and", "make", "it",
                "so", "only", "one", "better", "option", "project", "need", "fix", "function",
                "inside", "file", "where", "how", "find", "search", "list", "show", "what"
            }
            search_terms = [t for t in terms if t not in stopwords and len(t) > 2]
            if search_terms:
                project_matches = search_project_symbols_by_keywords(search_terms)
                if project_matches:
                    matches_str = "\n--- Matching Project Symbols (FTS/Index) ---\n"
                    for idx, m in enumerate(project_matches[:3]):
                        if m['name'] == best.get('name') and str(Path(m['file_path']).resolve()) == str(Path(path).resolve()):
                            continue
                        src = m['source'] or ""
                        src_lines = src.splitlines()
                        if len(src_lines) > 20:
                            src_truncated = "\n".join(src_lines[:15]) + "\n... [truncated] ..."
                        else:
                            src_truncated = src
                        matches_str += (
                            f"{idx+1}. Symbol: {m['name']}{m['signature'] or ''} ({m['kind']})\n"
                            f"   File Path: {m['file_path']}\n"
                            f"   Docstring: {m['docstring'] or 'No docstring'}\n"
                            f"   Source:\n"
                            f"```python\n{src_truncated}\n```\n\n"
                        )
                    context_str += matches_str

            use_llm = query_llm and not is_scrolling_restoration_query(question)
            llm_success = False
            patch = None
            
            if use_llm:
                model = settings.get("model") or "qwen2.5-coder:14b"

                if not edit_mode:
                    system_prompt = (
                        "You are a concise senior Python/PySide/Maya/Unreal code reviewer.\n"
                        "Answer using the active file context and any relevant project context provided. Explain intent, behavior, and risks. "
                        "Do not propose file edits or XML patches."
                    )
                    user_prompt = (
                        f"Active File Path: {path}\n"
                        f"Target Symbol Name: {best.get('name')}\n"
                        f"Target Symbol Kind: {best.get('kind')}\n"
                        f"Target Code:\n"
                        f"```python\n{best.get('source')}\n```\n\n"
                        f"{context_str}\n\n"
                        f"User Question: {question}\n\n"
                        "Give a useful explanation referencing the active code and any relevant project context. Keep it focused."
                    )
                    content = query_ollama_text(
                        settings.get("general_model") or model,
                        system_prompt,
                        user_prompt,
                        num_ctx=4096,
                        num_predict=700,
                        timeout=45,
                    )
                    if content:
                        output.append(content)
                        llm_success = True
                else:
                    system_prompt = (
                        "You are an expert PySide/Qt, Maya, and Unreal coding assistant.\n"
                        "You can propose creating new files and modifying existing files in the project.\n"
                        "The active file is the default edit target. If the user asks to add a class, function, method, or widget while a file is active, MODIFY the active file and insert the new code there.\n"
                        "Only CREATE a new file when the user explicitly asks for a new file/module/tool/plugin/script, or when the requested artifact clearly belongs in its own file.\n"
                        "To propose changes, you MUST output special XML tags:\n"
                        "- To MODIFY an existing file, output:\n"
                        "  <modify_file path=\"relative/or/absolute/path/to/file.py\">\n"
                        "  <<<< ORIGINAL\n"
                        "  ... exact original lines to replace ...\n"
                        "  ====\n"
                        "  ... replacement lines ...\n"
                        "  >>>>\n"
                        "  </modify_file>\n\n"
                        "- To CREATE a new file, output:\n"
                        "  <create_file path=\"relative/or/absolute/path/to/file.py\">\n"
                        "  ... file content ...\n"
                        "  </create_file>\n"
                        "If you only need to modify the current target class/function, you can output ONLY a single ```python ... ``` code block containing the raw Python code, which is backward compatible.\n"
                        "First explain your changes briefly. Then output the XML tags for the changes. Do not use standard markdown code blocks for multi-file changes; use the XML tags specified above."
                    )
                    
                    user_prompt = (
                        f"Active File Path: {path}\n"
                        f"Target Symbol Name: {best.get('name')}\n"
                        f"Target Symbol Kind: {best.get('kind')}\n"
                        f"Target Original Code:\n"
                        f"```python\n{best.get('source')}\n```\n\n"
                        f"{context_str}\n\n"
                        f"User Question: {question}\n\n"
                        "Please implement the changes to achieve the user's request. Prefer modifying the Active File Path for additive class/function/widget requests. If multiple files need to be modified or new files created, use the XML tags format."
                    )
                    
                    content = query_ollama_text(model, system_prompt, user_prompt)
                if edit_mode and content:
                    output.append(content)
                    
                    # 1. Parse XML multi-file changes first
                    changes = parse_multi_file_changes(content, roots[0] if roots else "")
                    changes = normalize_active_file_additions(changes, path, text, question)
                    if changes:
                        patch = {
                            "type": "project_changes",
                            "changes": changes,
                            "summary": f"Proposing project-wide changes across {len(changes)} files."
                        }
                    else:
                        # Fallback to single-symbol code block extraction
                        code_blocks = re.findall(r"```python\n(.*?)\n```", content, re.DOTALL)
                        if not code_blocks:
                            code_blocks = re.findall(r"```python\n(.*)", content, re.DOTALL)
                        if not code_blocks:
                            code_blocks = re.findall(r"```\n(.*?)\n```", content, re.DOTALL)
                        if not code_blocks:
                            code_blocks = re.findall(r"```\n(.*)", content, re.DOTALL)
                            
                        if code_blocks:
                            new_code = code_blocks[0].strip()
                            old_name = best.get("name")
                            new_name = None
                            m_new = re.search(r"class\s+([A-Za-z0-9_]+)", new_code)
                            if not m_new:
                                m_new = re.search(r"def\s+([A-Za-z0-9_]+)", new_code)
                            if m_new:
                                new_name = m_new.group(1)

                            action = "replace"
                            if new_name and new_name != old_name:
                                action = "insert_after"
                                summary = f"Add new {best.get('kind')} '{new_name}' below '{old_name}'."
                            else:
                                summary = f"Modify '{old_name}'."

                            patch = {
                                "type": "single_symbol",
                                "path": path,
                                "symbol": old_name,
                                "summary": summary,
                                "old": best.get("source"),
                                "new": new_code,
                                "action": action
                            }
                    llm_success = True
            
            if not llm_success:
                output.append(summarize_python_symbol(best, question))
                if context_str:
                    output.append(context_str)
                if edit_mode:
                    patch = build_safe_patch_for_symbol(path, best)
                
            if patch:
                output.append("")
                output.append("Suggested fix available:")
                output.append(f"- {patch['summary']}")
                output.append("- Review the proposed diff in the Editor tab, then accept or cancel it.")

            if len(ranked) > 1:
                output.append("")
                output.append("Other possible matches:")
                for score, sym in ranked[1:6]:
                    output.append(f"- {sym['kind']} `{sym['name']}` lines {sym['start']}-{sym['end']} score {score}")

            output.append("")
            output.append("Answered from the open file.")
            return "\n".join(output), patch

    hits = []
    for i, line in enumerate(text.splitlines(), start=1):
        score = sum(1 for t in terms if t in line.lower())
        if score:
            hits.append((score, i, line.strip()))

    hits.sort(key=lambda x: x[0], reverse=True)

    if hits:
        output.append("I found relevant lines, but this file type does not have rich local AST explanation yet:")
        for score, line_no, line in hits[:20]:
            output.append(f"- line {line_no}: {line[:220]}")
        output.append("")
        output.append("For a deeper explanation, select the relevant block and use Ask Selection.")
        return "\n".join(output), None

    output.append("No obvious local matches found in the open file.")
    output.append("Try selecting the relevant code and using Ask Selection, or use the Search / Symbols tab.")
    return "\n".join(output), None


def walk_code_files(dir_path: Path):
    ignored_dirs = {'.git', '.venv', '__pycache__', '.idea', 'build', 'dist', 'node_modules', '.continue', '.pytest_cache'}
    try:
        for p in dir_path.iterdir():
            if p.is_dir():
                if p.name not in ignored_dirs:
                    yield from walk_code_files(p)
            elif p.is_file():
                yield p
    except Exception:
        pass


def find_in_project(roots: list[str], query: str, max_results: int = 250) -> list[str]:
    """Search project roots for a query string. Returns formatted result lines."""
    if not query:
        return []

    results = []
    found = 0

    for root_path in roots:
        root_p = Path(root_path)
        if not root_p.exists():
            continue

        try:
            for p in walk_code_files(root_p):
                if found >= max_results:
                    results.append("... truncated ...")
                    return results

                if not is_supported_code_file(p):
                    continue

                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                low = text.lower()
                q = query.lower()
                if q not in low and q not in str(p).lower():
                    continue

                line_no = 1
                snippet = ""
                for i, line in enumerate(text.splitlines(), start=1):
                    if q in line.lower():
                        line_no = i
                        snippet = line.strip()
                        break

                results.append(f"{p}::{line_no} — {snippet[:140]}")
                found += 1
        except Exception:
            continue

    if found == 0:
        results.append("No results.")

    return results

# ---------------------------------------------------------------------------
# Project-wide indexed search primitives
# ---------------------------------------------------------------------------

def _index_db_path():
    from models.constants import V2_DB
    return V2_DB


def _connect_index():
    import sqlite3
    db = _index_db_path()
    if not db.exists():
        raise FileNotFoundError(f"Knowledge index not found: {db}")
    uri = db.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, timeout=30, uri=True)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    _ensure_search_schema_compat(conn)
    return conn


def _ensure_search_schema_compat(conn) -> None:
    """Add nullable graph/search columns introduced after older v2 indexes."""
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "imports" in tables:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(imports)").fetchall()}
            for col_name, col_type in (
                ("module", "TEXT"),
                ("name", "TEXT"),
                ("alias", "TEXT"),
                ("level", "INTEGER DEFAULT 0"),
                ("kind", "TEXT"),
                ("lineno", "INTEGER"),
                ("col_offset", "INTEGER"),
            ):
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE imports ADD COLUMN {col_name} {col_type}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_imports_name ON imports(name)")
        if "symbol_calls" in tables:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(symbol_calls)").fetchall()}
            for col_name in ("call_lineno", "call_col"):
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE symbol_calls ADD COLUMN {col_name} INTEGER")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol_calls_lineno ON symbol_calls(call_lineno)")
        if "symbols" in tables:
            cols = {row["name"] for row in conn.execute("PRAGMA table_info(symbols)").fetchall()}
            for col_name in ("parent_qualname", "parent_kind"):
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE symbols ADD COLUMN {col_name} TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_qualname)")
        conn.commit()
    except Exception:
        pass


def _as_dict_rows(rows):
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Scope-aware filtering/ranking
# ---------------------------------------------------------------------------

SOURCE_PROJECT = "project"
SOURCE_EXTERNAL_TOOLS = "external_tools"
SOURCE_THIRD_PARTY = "third_party"
SOURCE_PYTHON_STDLIB = "python_stdlib"
SOURCE_UNREAL_ENGINE = "unreal_engine"
SOURCE_MAYA = "maya"
SOURCE_DCC_APP = "dcc_app"
SOURCE_UNKNOWN = "unknown"
SOURCE_ALL = "all"

_EXTERNAL_PATH_MARKERS = (
    "site-packages", "dist-packages", "python311\\lib", "python312\\lib", "python310\\lib", "python39\\lib",
    "idlelib", "tkinter", "msilib",
)
_ENGINE_PATH_MARKERS = (
    "program files\\epic games", "\\engine\\source\\", "\\engine\\plugins\\",
)
_MAYA_PATH_MARKERS = (
    "program files\\autodesk", "\\maya", "maya202", "maya20",
)
_DCC_TOOL_MARKERS = (
    "maya_tools", "unreal_tools", "motionbuilder_tools", "mobu_tools", "blender_tools", "substance_painter_tools", "unity_tools",
)


def _norm_path_text(value: str | None) -> str:
    return str(value or "").replace("/", "\\").lower()


def _resolve_roots(project_roots: list[str] | None = None, active_path: str | None = None) -> list[str]:
    roots: list[str] = []

    for root in project_roots or []:
        try:
            resolved = str(Path(root).expanduser().resolve())
        except Exception:
            resolved = str(root)
        if resolved and resolved not in roots:
            roots.append(resolved)

    if not roots:
        try:
            from services.settings_service import load_settings
            from models.project import project_roots as configured_project_roots
            settings = load_settings()
            for root in configured_project_roots(settings):
                resolved = str(Path(root).expanduser().resolve())
                if resolved and resolved not in roots:
                    roots.append(resolved)
        except Exception:
            pass

    if active_path:
        try:
            active = Path(active_path).expanduser().resolve()
            if active.is_file():
                active = active.parent
            # Prefer a real repo/project marker when possible.
            probe = active
            while probe != probe.parent:
                if (probe / ".git").exists() or (probe / "pyproject.toml").exists() or (probe / "app").exists():
                    resolved = str(probe)
                    if resolved not in roots:
                        roots.insert(0, resolved)
                    break
                probe = probe.parent
        except Exception:
            pass

    return roots


def _path_is_under(path: str, roots: list[str]) -> bool:
    if not path or not roots:
        return False
    try:
        p = Path(path).expanduser().resolve()
        for root in roots:
            try:
                r = Path(root).expanduser().resolve()
                if p == r or r in p.parents:
                    return True
            except Exception:
                continue
    except Exception:
        # Fallback string-prefix check for paths that do not exist locally.
        ptxt = _norm_path_text(path)
        return any(ptxt.startswith(_norm_path_text(root).rstrip("\\") + "\\") for root in roots)
    return False


def classify_index_path(path: str, *, project_roots: list[str] | None = None, active_path: str | None = None) -> str:
    """Classify an indexed file path so project answers do not lead with stdlib/engine results."""
    roots = _resolve_roots(project_roots, active_path)
    if _path_is_under(path, roots):
        lowered = _norm_path_text(path)
        if "\\external_tools\\" in lowered:
            return SOURCE_EXTERNAL_TOOLS
        return SOURCE_PROJECT

    lowered = _norm_path_text(path)
    if any(marker in lowered for marker in _ENGINE_PATH_MARKERS):
        return SOURCE_UNREAL_ENGINE
    if any(marker in lowered for marker in _MAYA_PATH_MARKERS):
        return SOURCE_MAYA
    if any(marker in lowered for marker in _EXTERNAL_PATH_MARKERS):
        return SOURCE_PYTHON_STDLIB if ("python" in lowered and "lib" in lowered and "site-packages" not in lowered) else SOURCE_THIRD_PARTY
    if "program files" in lowered:
        return SOURCE_DCC_APP
    return SOURCE_UNKNOWN


def _scope_allowed(source_scope: str, requested_scope: str) -> bool:
    requested_scope = (requested_scope or SOURCE_PROJECT).lower()
    if requested_scope in {SOURCE_ALL, "everything", "global"}:
        return True
    if requested_scope in {SOURCE_PROJECT, "current_project", "repo", "codebase"}:
        return source_scope in {SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS}
    if requested_scope in {"unreal_project", "project_unreal", "host_unreal"}:
        return source_scope in {SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN, SOURCE_UNREAL_ENGINE}
    if requested_scope in {"maya_project", "project_maya", "host_maya"}:
        return source_scope in {SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN, SOURCE_MAYA}
    if requested_scope in {"first_party", "workspace"}:
        return source_scope in {SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN}
    if requested_scope in {"external", "third_party"}:
        return source_scope in {SOURCE_THIRD_PARTY, SOURCE_PYTHON_STDLIB, SOURCE_DCC_APP}
    if requested_scope in {"engine", "unreal"}:
        return source_scope == SOURCE_UNREAL_ENGINE
    if requested_scope == "maya":
        return source_scope == SOURCE_MAYA
    return True


def _rank_scoped_rows(
    rows: list[dict],
    *,
    active_path: str | None = None,
    project_roots: list[str] | None = None,
    scope: str = SOURCE_PROJECT,
    path_key: str = "path",
    limit: int = 80,
) -> list[dict]:
    """Attach source_scope, filter by requested scope, and rank project files above external code."""
    active_norm = ""
    try:
        active_norm = str(Path(active_path).expanduser().resolve()) if active_path else ""
    except Exception:
        active_norm = str(active_path or "")

    scored = []
    for row in rows:
        item = dict(row)
        path = str(item.get(path_key) or "")
        source_scope = item.get("source_scope") or classify_index_path(path, project_roots=project_roots, active_path=active_path)
        item["source_scope"] = source_scope
        if not _scope_allowed(source_scope, scope):
            continue
        score = 0
        if source_scope == SOURCE_PROJECT:
            score += 100
        elif source_scope == SOURCE_EXTERNAL_TOOLS:
            score += 70
        elif source_scope == SOURCE_UNKNOWN:
            score += 25
        elif source_scope in {SOURCE_UNREAL_ENGINE, SOURCE_MAYA}:
            score -= 20
        elif source_scope in {SOURCE_THIRD_PARTY, SOURCE_PYTHON_STDLIB, SOURCE_DCC_APP}:
            score -= 60
        if active_norm and path == active_norm:
            score += 45
        item["scope_score"] = score
        scored.append(item)

    scored.sort(key=lambda r: (-int(r.get("scope_score", 0)), str(r.get(path_key) or ""), int(r.get("start_line") or 0), int(r.get("chunk_index") or 0)))
    return scored[: max(1, int(limit))]


def extract_code_search_terms(query: str, include_qt_related: bool = True) -> list[str]:
    """Extract high-value search terms from a project-wide code query.

    This intentionally preserves API names like QFileDialog and dotted names like
    QtWidgets.QFileDialog. For QFileDialog-style questions it also adds common
    static method names because projects often import QFileDialog directly and
    then call getOpenFileName/getExistingDirectory without repeating the class
    name nearby.
    """
    query = query or ""
    lower = query.lower()
    stop = {
        "the", "and", "for", "that", "this", "with", "from", "into", "what", "where", "which",
        "every", "class", "classes", "function", "functions", "method", "methods", "project",
        "codebase", "file", "files", "find", "show", "summarize", "explain", "does", "uses",
        "used", "opens", "open", "make", "create", "add", "change", "replace", "rename", "refactor",
        "throughout", "anywhere", "all", "each", "one", "ones", "are", "is", "in", "to", "of",
        "if", "so", "list", "tell", "me", "my", "current", "based", "on", "it", "its", "please",
        "should", "own", "owns", "owner", "service", "services",
    }

    terms: list[str] = []

    def add(term: str):
        term = (term or "").strip()
        if len(term) < 3:
            return
        if term.lower() in stop:
            return
        if term not in terms:
            terms.append(term)

    for item in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?\b", query):
        add(item)

    if include_qt_related and (
        "qfiledialog" in lower
        or "file dialog" in lower
        or "select file" in lower
        or "open file" in lower
        or "select a file" in lower
    ):
        for term in (
            "QFileDialog",
            "QtWidgets.QFileDialog",
            "getOpenFileName",
            "getOpenFileNames",
            "getSaveFileName",
            "getExistingDirectory",
        ):
            add(term)

    generic_dialog_query = (
        ("qdialog" in lower or "dialog" in lower or "popup" in lower)
        and "qfiledialog" not in lower
        and "file dialog" not in lower
    )
    if include_qt_related and generic_dialog_query:
        for term in ("QDialog", "QtWidgets.QDialog", "QMessageBox"):
            add(term)

    lowered_terms = {t.lower() for t in terms}
    for item in re.findall(r"[A-Za-z0-9_]{3,}", lower):
        if item in stop or item in lowered_terms:
            continue
        add(item)
        lowered_terms.add(item)

    return terms


def related_code_search_terms(query: str, exact_terms: list[str] | None = None) -> list[str]:
    """Fallback terms for when exact usage search returns nothing or too little."""
    exact = set(exact_terms or [])
    lower = (query or "").lower()
    related: list[str] = []

    def add(term: str):
        if term not in exact and term not in related:
            related.append(term)

    if "qfiledialog" in lower or "file dialog" in lower or "select file" in lower or "open file" in lower:
        for term in (
            "QFileDialog",
            "QtWidgets.QFileDialog",
            "getOpenFileName",
            "getOpenFileNames",
            "getSaveFileName",
            "getExistingDirectory",
            "QDialog",
            "QtWidgets.QDialog",
            "QMessageBox",
            "QLineEdit",
            "QPushButton",
        ):
            add(term)

    if "qdialog" in lower or "dialog" in lower or "popup" in lower:
        for term in ("QDialog", "QtWidgets.QDialog", "QFileDialog", "QMessageBox", "exec_", "exec"):
            add(term)

    return related


def _where_like(columns: list[str], terms: list[str]) -> tuple[str, list[str]]:
    parts = []
    params: list[str] = []
    for term in terms:
        likes = []
        for col in columns:
            likes.append(f"{col} LIKE ?")
            params.append(f"%{term}%")
        parts.append("(" + " OR ".join(likes) + ")")
    return " OR ".join(parts), params


def search_index_symbols(terms: list[str], *, limit: int = 80, active_path: str | None = None, class_bias: bool = False, scope: str = SOURCE_PROJECT, project_roots: list[str] | None = None) -> list[dict]:
    """Search symbol rows by name, signature, docstring, source, searchable text, and path."""
    if not terms:
        return []
    with _connect_index() as conn:
        cur = conn.cursor()
        where, params = _where_like(
            ["s.name", "s.qualname", "s.parent_qualname", "s.signature", "s.docstring", "s.searchable_text", "s.source", "f.path"],
            terms,
        )
        query = """
            SELECT
                s.name, s.qualname, s.parent_qualname, s.parent_kind, s.kind, s.signature, s.docstring,
                s.start_line, s.end_line, s.source, f.path
            FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE
        """ + where
        order = []
        if active_path:
            order.append("CASE WHEN f.path = ? THEN 0 ELSE 1 END")
            params.append(str(Path(active_path).resolve()))
        if class_bias:
            order.append("CASE WHEN s.kind = 'class' THEN 0 WHEN s.kind = 'method' THEN 1 ELSE 2 END")
        order.extend(["f.path", "s.start_line"])
        query += " ORDER BY " + ", ".join(order) + " LIMIT ?"
        params.append(int(limit) * 8)
        rows = _as_dict_rows(cur.execute(query, params).fetchall())
        return _rank_scoped_rows(rows, active_path=active_path, project_roots=project_roots, scope=scope, limit=limit)


def search_index_chunks(terms: list[str], *, limit: int = 80, active_path: str | None = None, scope: str = SOURCE_PROJECT, project_roots: list[str] | None = None) -> list[dict]:
    """Search chunk rows by raw text/path. This catches uses inside methods."""
    if not terms:
        return []
    with _connect_index() as conn:
        cur = conn.cursor()
        where, params = _where_like(["c.text", "f.path"], terms)
        query = """
            SELECT f.path, c.chunk_index, c.text
            FROM chunks c
            JOIN files f ON f.id = c.file_id
            WHERE
        """ + where + " ORDER BY f.path, c.chunk_index LIMIT ?"
        params.append(int(limit) * 8)
        rows = _as_dict_rows(cur.execute(query, params).fetchall())
        return _rank_scoped_rows(rows, active_path=active_path, project_roots=project_roots, scope=scope, limit=limit)


def search_index_imports(term: str, *, limit: int = 80, active_path: str | None = None, scope: str = SOURCE_PROJECT, project_roots: list[str] | None = None) -> list[dict]:
    """Search indexed import rows for an import name."""
    if not term:
        return []
    with _connect_index() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT i.import_name, i.module, i.name, i.alias, i.level, i.kind, i.lineno, i.col_offset, f.path
            FROM imports i
            JOIN files f ON f.id = i.file_id
            WHERE i.import_name LIKE ? OR i.module LIKE ? OR i.name LIKE ? OR i.alias LIKE ? OR f.path LIKE ?
            ORDER BY f.path, i.lineno, i.col_offset, i.import_name
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", int(limit) * 8),
        ).fetchall()
        return _rank_scoped_rows(_as_dict_rows(rows), active_path=active_path, project_roots=project_roots, scope=scope, limit=limit)


def search_index_calls(term: str, *, limit: int = 80, active_path: str | None = None, scope: str = SOURCE_PROJECT, project_roots: list[str] | None = None) -> list[dict]:
    """Search indexed call rows for a call name."""
    if not term:
        return []
    with _connect_index() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT sc.call_name, sc.call_lineno, sc.call_col, s.name, s.qualname, s.parent_qualname, s.parent_kind, s.kind, s.signature,
                   s.start_line, s.end_line, f.path, s.source
            FROM symbol_calls sc
            JOIN symbols s ON s.id = sc.symbol_id
            JOIN files f ON f.id = s.file_id
            WHERE sc.call_name LIKE ? OR s.source LIKE ? OR s.searchable_text LIKE ?
            ORDER BY f.path, s.start_line
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", int(limit) * 8),
        ).fetchall()
        return _rank_scoped_rows(_as_dict_rows(rows), active_path=active_path, project_roots=project_roots, scope=scope, limit=limit)


def search_index_call_names(term: str, *, limit: int = 80, active_path: str | None = None, scope: str = SOURCE_PROJECT, project_roots: list[str] | None = None) -> list[dict]:
    """Search indexed call rows by call name only.

    This is the fast path for prompts like "classes that open QFileDialog"; it
    avoids scanning full source text until the caller explicitly needs fallback
    usage search.
    """
    if not term:
        return []
    with _connect_index() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT sc.call_name, sc.call_lineno, sc.call_col, s.name, s.qualname, s.parent_qualname, s.parent_kind, s.kind, s.signature,
                   s.start_line, s.end_line, f.path
            FROM symbol_calls sc
            JOIN symbols s ON s.id = sc.symbol_id
            JOIN files f ON f.id = s.file_id
            WHERE sc.call_name LIKE ?
            ORDER BY f.path, s.start_line
            LIMIT ?
            """,
            (f"%{term}%", int(limit) * 8),
        ).fetchall()
        return _rank_scoped_rows(_as_dict_rows(rows), active_path=active_path, project_roots=project_roots, scope=scope, limit=limit)


def search_index_classes(base_class: str | None = None, terms: list[str] | None = None, *, limit: int = 80, active_path: str | None = None, scope: str = SOURCE_PROJECT, project_roots: list[str] | None = None) -> list[dict]:
    """Search indexed class symbols, optionally by base class or additional terms."""
    query_terms = list(terms or [])
    if base_class:
        query_terms.append(base_class)
    with _connect_index() as conn:
        cur = conn.cursor()
        params: list[str] = []
        query = """
            SELECT s.name, s.qualname, s.parent_qualname, s.parent_kind, s.kind, s.signature, s.docstring,
                   s.start_line, s.end_line, s.source, f.path
            FROM symbols s
            JOIN files f ON f.id = s.file_id
            WHERE s.kind = 'class'
        """
        if query_terms:
            where, params = _where_like(["s.name", "s.qualname", "s.parent_qualname", "s.signature", "s.docstring", "s.searchable_text", "s.source", "f.path"], query_terms)
            query += " AND (" + where + ")"
        query += " ORDER BY f.path, s.start_line LIMIT ?"
        params.append(int(limit) * 8)
        rows = _as_dict_rows(cur.execute(query, params).fetchall())
        return _rank_scoped_rows(rows, active_path=active_path, project_roots=project_roots, scope=scope, limit=limit)


def search_index_usages(query_or_symbol: str, *, limit: int = 100, active_path: str | None = None, scope: str = SOURCE_PROJECT, project_roots: list[str] | None = None) -> dict:
    """Project-wide usage search with exact, import, call, chunk, and related fallback results."""
    exact_terms = extract_code_search_terms(query_or_symbol)
    related_terms = related_code_search_terms(query_or_symbol, exact_terms)
    lower = (query_or_symbol or "").lower()
    class_bias = bool(re.search(r"\b(class|classes|widget|widgets|dialog|dialogs)\b", lower))

    exact_symbols = search_index_symbols(exact_terms, limit=limit, active_path=active_path, class_bias=class_bias, scope=scope, project_roots=project_roots)
    exact_chunks = search_index_chunks(exact_terms, limit=min(40, limit), active_path=active_path, scope=scope, project_roots=project_roots)
    exact_imports = []
    exact_calls = []
    for term in exact_terms[:8]:
        exact_imports.extend(search_index_imports(term, limit=20, active_path=active_path, scope=scope, project_roots=project_roots))
        exact_calls.extend(search_index_calls(term, limit=20, active_path=active_path, scope=scope, project_roots=project_roots))

    related_symbols = []
    related_chunks = []
    if related_terms:
        related_symbols = search_index_symbols(related_terms, limit=40, active_path=active_path, class_bias=class_bias, scope=scope, project_roots=project_roots)
        if not exact_symbols and not exact_chunks:
            related_chunks = search_index_chunks(related_terms, limit=30, active_path=active_path, scope=scope, project_roots=project_roots)

    def dedupe(items, key_fields):
        seen = set()
        out = []
        for item in items:
            key = tuple(item.get(k) for k in key_fields)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    return {
        "query": query_or_symbol,
        "exact_terms": exact_terms,
        "related_terms": related_terms,
        "scope": scope,
        "project_roots": project_roots or [],
        "exact_symbols": dedupe(exact_symbols, ("path", "qualname", "start_line")),
        "exact_chunks": dedupe(exact_chunks, ("path", "chunk_index")),
        "exact_imports": dedupe(exact_imports, ("path", "import_name")),
        "exact_calls": dedupe(exact_calls, ("path", "qualname", "call_name", "call_lineno", "call_col")),
        "related_symbols": dedupe(related_symbols, ("path", "qualname", "start_line")),
        "related_chunks": dedupe(related_chunks, ("path", "chunk_index")),
    }


def format_index_search_context(results: dict, *, max_source_lines: int = 35) -> str:
    """Format search_index_usages results for an LLM or UI answer."""
    def trim_source(src: str, limit: int = max_source_lines) -> str:
        lines = (src or "").splitlines()
        if len(lines) > limit:
            return "\n".join(lines[: limit - 5]) + "\n... [truncated] ..."
        return src or ""

    parts = [
        "Project index search results:",
        f"Query: {results.get('query')}",
        f"Exact terms: {', '.join(results.get('exact_terms') or []) or '(none)'}",
    ]
    if results.get("related_terms"):
        parts.append(f"Related fallback terms: {', '.join(results['related_terms'])}")
    parts.append("")

    imports = results.get("exact_imports") or []
    calls = results.get("exact_calls") or []
    symbols = results.get("exact_symbols") or []
    chunks = results.get("exact_chunks") or []
    related_symbols = results.get("related_symbols") or []
    related_chunks = results.get("related_chunks") or []

    if imports:
        parts.append("Exact import matches:")
        for i, row in enumerate(imports, 1):
            alias = f" as {row.get('alias')}" if row.get("alias") else ""
            line = f" line {row.get('lineno')}" if row.get("lineno") else ""
            parts.append(
                f"[{i}] {row.get('import_name')}{alias}{line}\n"
                f"File: {row.get('path')}\n"
                f"Module: {row.get('module') or '(unknown)'} | Name: {row.get('name') or '(module import)'} | Level: {row.get('level') or 0}\n"
            )

    if calls:
        parts.append("Exact call/source matches:")
        for i, row in enumerate(calls, 1):
            call_line = f" call line {row.get('call_lineno')}" if row.get("call_lineno") else ""
            owner = f"\nOwner: {row.get('parent_kind')} {row.get('parent_qualname')}" if row.get("parent_qualname") else ""
            parts.append(
                f"[{i}] {row.get('kind')} {row.get('qualname') or row.get('name')} lines {row.get('start_line')}-{row.get('end_line')}{call_line}\n"
                f"File: {row.get('path')}\n"
                f"Call: {row.get('call_name')}\n"
                f"{owner}\n"
                f"Source:\n```python\n{trim_source(row.get('source') or '')}\n```\n"
            )

    if symbols:
        parts.append("Exact symbol/source matches:")
        for i, row in enumerate(symbols, 1):
            owner = f"\nOwner: {row.get('parent_kind')} {row.get('parent_qualname')}" if row.get("parent_qualname") else ""
            parts.append(
                f"[{i}] {row.get('kind')} {row.get('qualname') or row.get('name')} lines {row.get('start_line')}-{row.get('end_line')}\n"
                f"File: {row.get('path')}\n"
                f"Signature: {row.get('signature') or row.get('name')}\n"
                f"Docstring: {row.get('docstring') or 'No docstring'}\n"
                f"{owner}\n"
                f"Source:\n```python\n{trim_source(row.get('source') or '')}\n```\n"
            )

    if chunks:
        parts.append("Exact text/chunk matches:")
        for i, row in enumerate(chunks[:30], 1):
            parts.append(
                f"[{i}] chunk {row.get('chunk_index')}\n"
                f"File: {row.get('path')}\n"
                f"Text:\n```text\n{trim_source(row.get('text') or '', 45)}\n```\n"
            )

    if related_symbols:
        parts.append("Related fallback symbol/source matches:")
        for i, row in enumerate(related_symbols[:25], 1):
            owner = f"\nOwner: {row.get('parent_kind')} {row.get('parent_qualname')}" if row.get("parent_qualname") else ""
            parts.append(
                f"[{i}] {row.get('kind')} {row.get('qualname') or row.get('name')} lines {row.get('start_line')}-{row.get('end_line')}\n"
                f"File: {row.get('path')}\n"
                f"{owner}\n"
                f"Source:\n```python\n{trim_source(row.get('source') or '')}\n```\n"
            )

    if related_chunks:
        parts.append("Related fallback text/chunk matches:")
        for i, row in enumerate(related_chunks[:20], 1):
            parts.append(
                f"[{i}] chunk {row.get('chunk_index')}\n"
                f"File: {row.get('path')}\n"
                f"Text:\n```text\n{trim_source(row.get('text') or '', 45)}\n```\n"
            )

    if not any([imports, calls, symbols, chunks, related_symbols, related_chunks]):
        parts.append("No exact or related indexed results were found. The index may be stale or the active project may not be indexed.")

    return "\n".join(parts)




# ---------------------------------------------------------------------------
# Dependency graph / unused-file analysis
# ---------------------------------------------------------------------------

def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row)


def _entrypoint_like_path(path: str) -> bool:
    p = Path(path or "")
    name = p.name.lower()
    stem = p.stem.lower()
    return (
        name in {"__init__.py", "__main__.py", "setup.py", "conftest.py"}
        or stem in {"main", "studio_main", "run", "start", "launcher"}
        or stem.startswith("test_")
        or "tests" in {part.lower() for part in p.parts}
    )


def _graph_scope_sql(scope: str) -> tuple[str, tuple]:
    if scope == SOURCE_ALL:
        return "", ()
    if scope == SOURCE_PROJECT:
        return " AND COALESCE(f.source_scope, 'project') IN (?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS)
    if scope in {"unreal_project", "project_unreal", "host_unreal"}:
        return " AND COALESCE(f.source_scope, 'project') IN (?, ?, ?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN, SOURCE_UNREAL_ENGINE)
    if scope in {"maya_project", "project_maya", "host_maya"}:
        return " AND COALESCE(f.source_scope, 'project') IN (?, ?, ?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN, SOURCE_MAYA)
    if scope == SOURCE_STRICT_PROJECT:
        return " AND COALESCE(f.source_scope, 'project') = ? ", (SOURCE_PROJECT,)
    if scope == SOURCE_EXTERNAL:
        return " AND COALESCE(f.source_scope, 'project') NOT IN (?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS)
    return "", ()


def analyze_unused_files(*, scope: str = SOURCE_PROJECT, limit: int = 200, include_entrypoints: bool = False, max_checked: int = 5000) -> dict:
    """Find Python files with no meaningful incoming project dependency edges.

    Requires the dependency graph tables produced by build_knowledge_index_v2.py.
    A file is a strong unused candidate when it has zero incoming imports from
    indexed project files. A weaker candidate has incoming imports, but all of
    those imports appear unused in the importing files according to the heuristic
    usage counter.
    """
    try:
        with _connect_index() as conn:
            if not _table_exists(conn, "file_dependencies"):
                return {
                    "kind": "unused_files",
                    "error": "Dependency graph tables are missing. Rebuild the index with the updated build_knowledge_index_v2.py.",
                    "candidates": [],
                    "weak_candidates": [],
                }

            scope_sql, scope_params = _graph_scope_sql(scope)
            files = conn.execute(
                f"""
                SELECT f.id, f.path, f.rel_path, f.module, f.source_scope
                FROM files f
                WHERE f.ext = '.py' {scope_sql}
                ORDER BY f.path
                LIMIT ?
                """,
                tuple(scope_params) + (max(1, int(max_checked or 2000)),),
            ).fetchall()

            candidates = []
            weak_candidates = []
            for f in files:
                path = f["path"]
                if not include_entrypoints and _entrypoint_like_path(path):
                    continue
                incoming = conn.execute(
                    "SELECT COUNT(*) AS c FROM file_dependencies WHERE target_file_id = ? AND is_resolved = 1",
                    (f["id"],),
                ).fetchone()["c"]
                used_incoming = conn.execute(
                    "SELECT COUNT(*) AS c FROM file_dependencies WHERE target_file_id = ? AND is_resolved = 1 AND used_symbol_count > 0",
                    (f["id"],),
                ).fetchone()["c"]
                outgoing = conn.execute(
                    "SELECT COUNT(*) AS c FROM file_dependencies WHERE source_file_id = ? AND is_resolved = 1",
                    (f["id"],),
                ).fetchone()["c"]

                row = {
                    "path": path,
                    "rel_path": f["rel_path"],
                    "module": f["module"],
                    "source_scope": f["source_scope"],
                    "incoming_imports": incoming,
                    "used_incoming_imports": used_incoming,
                    "outgoing_imports": outgoing,
                    "entrypoint_like": _entrypoint_like_path(path),
                }
                if incoming == 0:
                    row["confidence"] = "high"
                    row["reason"] = "No resolved indexed file imports this module."
                    candidates.append(row)
                elif used_incoming == 0:
                    row["confidence"] = "medium"
                    row["reason"] = "It is imported, but all incoming imports look unused by the importing files."
                    weak_candidates.append(row)

            return {
                "kind": "unused_files",
                "scope": scope,
                "candidates": candidates[:limit],
                "weak_candidates": weak_candidates[:limit],
                "total_candidates": len(candidates),
                "total_weak_candidates": len(weak_candidates),
            }
    except Exception as exc:
        return {"kind": "unused_files", "error": str(exc), "candidates": [], "weak_candidates": []}


def analyze_unused_imports(*, scope: str = SOURCE_PROJECT, limit: int = 200) -> dict:
    """Find resolved imports whose imported module/symbol appears unused."""
    try:
        with _connect_index() as conn:
            if not _table_exists(conn, "file_dependencies"):
                return {
                    "kind": "unused_imports",
                    "error": "Dependency graph tables are missing. Rebuild the index with the updated build_knowledge_index_v2.py.",
                    "imports": [],
                }
            scope_sql, scope_params = _graph_scope_sql(scope)
            rows = conn.execute(
                f"""
                SELECT d.*
                FROM file_dependencies d
                JOIN files f ON f.id = d.source_file_id
                WHERE d.is_resolved = 1
                  AND d.used_symbol_count = 0
                  {scope_sql}
                ORDER BY d.source_path, d.import_name
                LIMIT ?
                """,
                (*scope_params, limit),
            ).fetchall()
            return {"kind": "unused_imports", "scope": scope, "imports": _as_dict_rows(rows), "total": len(rows)}
    except Exception as exc:
        return {"kind": "unused_imports", "error": str(exc), "imports": []}


def find_file_dependents(path_or_module: str, *, scope: str = SOURCE_PROJECT, limit: int = 100) -> dict:
    """Return files that depend on a target file/module/path."""
    try:
        target = path_or_module or ""
        like = f"%{target}%"
        with _connect_index() as conn:
            if not _table_exists(conn, "file_dependencies"):
                return {"kind": "dependents", "error": "Dependency graph tables are missing. Rebuild the index.", "dependents": []}
            scope_sql, scope_params = _graph_scope_sql(scope)
            rows = conn.execute(
                f"""
                SELECT d.*
                FROM file_dependencies d
                JOIN files f ON f.id = d.source_file_id
                WHERE d.is_resolved = 1
                  AND (target_path LIKE ? OR target_module LIKE ? OR import_name LIKE ?)
                  {scope_sql}
                ORDER BY used_symbol_count DESC, source_path
                LIMIT ?
                """,
                (like, like, like, *scope_params, limit),
            ).fetchall()
            return {"kind": "dependents", "target": target, "dependents": _as_dict_rows(rows), "total": len(rows)}
    except Exception as exc:
        return {"kind": "dependents", "error": str(exc), "dependents": []}


def format_graph_analysis_context(result: dict) -> str:
    """Format dependency graph analysis for the editor LLM."""
    kind = result.get("kind", "graph")
    if result.get("error"):
        return f"Graph analysis error: {result['error']}"

    if kind == "unused_files":
        lines = [
            "Dependency graph analysis: unused file candidates",
            f"Scope: {result.get('scope', '(default)')}",
            f"Strong candidates: {result.get('total_candidates', 0)}",
            f"Weak candidates: {result.get('total_weak_candidates', 0)}",
            "",
        ]
        candidates = result.get("candidates", [])
        weak = result.get("weak_candidates", [])
        if candidates:
            lines.append("Files with no resolved incoming imports:")
            for i, row in enumerate(candidates, 1):
                lines.append(
                    f"[{i}] {row.get('path')}\n"
                    f"    module: {row.get('module') or '(none)'}\n"
                    f"    outgoing imports: {row.get('outgoing_imports')}\n"
                    f"    confidence: {row.get('confidence')}\n"
                    f"    reason: {row.get('reason')}"
                )
        if weak:
            lines.append("\nFiles imported only by apparently-unused imports:")
            for i, row in enumerate(weak, 1):
                lines.append(
                    f"[{i}] {row.get('path')}\n"
                    f"    module: {row.get('module') or '(none)'}\n"
                    f"    incoming imports: {row.get('incoming_imports')}\n"
                    f"    used incoming imports: {row.get('used_incoming_imports')}\n"
                    f"    confidence: {row.get('confidence')}\n"
                    f"    reason: {row.get('reason')}"
                )
        if not candidates and not weak:
            lines.append("No unused-file candidates were found in the dependency graph.")
        lines.append("\nImportant: this is static dependency analysis. Entry points, plugin-discovered modules, reflection, dynamic imports, and files loaded by path should be verified before deletion.")
        return "\n".join(lines)

    if kind == "unused_imports":
        rows = result.get("imports", [])
        lines = ["Dependency graph analysis: unused import candidates", f"Scope: {result.get('scope', '(default)')}", ""]
        if not rows:
            lines.append("No unused import candidates were found.")
        for i, row in enumerate(rows, 1):
            lines.append(
                f"[{i}] {row.get('import_name')}\n"
                f"    source: {row.get('source_path')}\n"
                f"    target: {row.get('target_path')}\n"
                f"    resolved module: {row.get('resolved_module')}\n"
                f"    used symbol count: {row.get('used_symbol_count')}"
            )
        return "\n".join(lines)

    if kind == "dependents":
        rows = result.get("dependents", [])
        lines = ["Dependency graph analysis: dependents", f"Target: {result.get('target')}", ""]
        if not rows:
            lines.append("No dependents were found.")
        for i, row in enumerate(rows, 1):
            lines.append(
                f"[{i}] {row.get('source_path')}\n"
                f"    imports: {row.get('import_name')}\n"
                f"    target: {row.get('target_path')}\n"
                f"    used symbol count: {row.get('used_symbol_count')}"
            )
        return "\n".join(lines)

    return str(result)


# ---------------------------------------------------------------------------
# Project health / sync analysis
# ---------------------------------------------------------------------------

# Backward-compatible scope constants that some graph helpers expect.
try:
    SOURCE_STRICT_PROJECT
except NameError:
    SOURCE_STRICT_PROJECT = "strict_project"
try:
    SOURCE_EXTERNAL
except NameError:
    SOURCE_EXTERNAL = "external"

_HEALTH_SYMBOL_SKIP_NAMES = {
    "__init__", "__repr__", "__str__", "__len__", "__iter__", "__next__",
    "__enter__", "__exit__", "__call__", "__getattr__", "__setattr__",
    "main", "run", "start", "stop", "setup", "teardown", "accept", "reject",
}
_HEALTH_DYNAMIC_HINTS = (
    "connect(", "triggered.connect", "clicked.connect", "timeout.connect",
    "Signal", "Slot", "QThread", "QTimer", "QAction", "setattr(", "getattr(",
    "importlib", "__name__ ==", "exec(", "eval(", "entry", "callback", "handler",
    "unreal.", "maya.", "cmds.", "bpy.", "workflow", "pipeline",
)


def _health_scope_sql(alias: str = "f", scope: str = SOURCE_PROJECT) -> tuple[str, tuple]:
    if scope in {SOURCE_ALL, "all"}:
        return "", ()
    if scope in {SOURCE_STRICT_PROJECT, "strict_project"}:
        return f" AND COALESCE({alias}.source_scope, 'project') = ? ", (SOURCE_PROJECT,)
    if scope in {"unreal_project", "project_unreal", "host_unreal"}:
        return f" AND COALESCE({alias}.source_scope, 'project') IN (?, ?, ?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN, SOURCE_UNREAL_ENGINE)
    if scope in {"maya_project", "project_maya", "host_maya"}:
        return f" AND COALESCE({alias}.source_scope, 'project') IN (?, ?, ?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN, SOURCE_MAYA)
    if scope in {SOURCE_EXTERNAL, "external"}:
        return f" AND COALESCE({alias}.source_scope, 'project') NOT IN (?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS)
    return f" AND COALESCE({alias}.source_scope, 'project') IN (?, ?, ?) ", (SOURCE_PROJECT, SOURCE_EXTERNAL_TOOLS, SOURCE_UNKNOWN)


def _symbol_health_skip(row: dict) -> tuple[bool, str]:
    name = (row.get("name") or "").strip()
    kind = (row.get("kind") or "").strip()
    path = row.get("path") or ""
    source = row.get("source") or ""
    qualname = row.get("qualname") or name

    if not name:
        return True, "empty symbol name"
    if kind == "module":
        return True, "module-level pseudo symbol"
    if name in _HEALTH_SYMBOL_SKIP_NAMES:
        return True, "common framework/entrypoint method"
    if name.startswith("__") and name.endswith("__"):
        return True, "Python dunder method"
    if name.startswith("test_") or Path(path).name.startswith("test_"):
        return True, "test symbol"
    if _entrypoint_like_path(path):
        return True, "entrypoint-like file"
    lowered = (source + "\n" + qualname).lower()
    if kind == "method" and any(h.lower() in lowered for h in _HEALTH_DYNAMIC_HINTS):
        return True, "likely callback/framework method"
    if re.search(r"\bon_[a-zA-Z0-9_]+\b", name) or name.endswith("_changed") or name.endswith("_clicked"):
        return True, "likely event/callback method"
    return False, ""


def get_index_sync_status(*, project_roots: list[str] | None = None, scope: str = SOURCE_PROJECT, limit: int = 200, scan_new_files: bool = False, max_checked: int = 2000) -> dict:
    """Compare indexed file metadata with disk state.

    This is intentionally light enough to run periodically from the UI.
    It compares the indexed file table against disk using stat-only checks
    first. It does not walk the whole project for new files unless
    scan_new_files=True, because full root walks are expensive on large repos.
    """
    try:
        with _connect_index() as conn:
            scope_sql, scope_params = _health_scope_sql("f", scope)
            rows = conn.execute(
                f"""
                SELECT f.path, f.rel_path, f.size, f.mtime, f.sha1, f.source_scope
                FROM files f
                WHERE 1=1 {scope_sql}
                ORDER BY f.path
                LIMIT ?
                """,
                tuple(scope_params) + (max(1, int(max_checked or 2000)),),
            ).fetchall()
            indexed_paths = {str(row["path"]): row for row in rows}

        changed = []
        missing = []
        checked = 0
        for row in rows:
            path = Path(row["path"])
            checked += 1
            if not path.exists():
                missing.append({"path": str(path), "reason": "missing on disk"})
                continue
            try:
                stat = path.stat()
                indexed_size = int(row["size"] or 0)
                indexed_mtime = float(row["mtime"] or 0)
                size_changed = indexed_size != int(stat.st_size)
                mtime_changed = abs(float(stat.st_mtime) - indexed_mtime) > 1.0
                if size_changed or mtime_changed:
                    changed.append({
                        "path": str(path),
                        "rel_path": row["rel_path"],
                        "reason": "size changed" if size_changed else "modified since index",
                        "indexed_mtime": indexed_mtime,
                        "disk_mtime": float(stat.st_mtime),
                        "indexed_size": indexed_size,
                        "disk_size": int(stat.st_size),
                    })
            except Exception as exc:
                changed.append({"path": str(path), "reason": f"stat failed: {exc}"})

        new_files = []
        roots = []
        for root in project_roots or []:
            try:
                p = Path(root).expanduser().resolve()
                if p.exists() and p not in roots:
                    roots.append(p)
            except Exception:
                pass
        if scan_new_files and roots:
            try:
                from models.files import is_supported_code_file as _is_supported_code_file
                from models.constants import SKIP_DIRS as _SKIP_DIRS
            except Exception:
                _is_supported_code_file = None
                _SKIP_DIRS = SKIP_DIRS
            indexed_norm = {str(Path(p).resolve()).lower() for p in indexed_paths.keys()}
            for root in roots:
                for p in root.rglob("*"):
                    if len(new_files) >= limit:
                        break
                    try:
                        if not p.is_file():
                            continue
                        if any(part in _SKIP_DIRS for part in p.parts):
                            continue
                        if _is_supported_code_file and not _is_supported_code_file(p):
                            continue
                        rp = str(p.resolve()).lower()
                        if rp not in indexed_norm:
                            new_files.append({"path": str(p), "reason": "new file not in index"})
                    except Exception:
                        continue

        total_stale = len(changed) + len(missing) + len(new_files)
        return {
            "kind": "index_sync",
            "checked": checked,
            "stale": total_stale > 0,
            "total_stale": total_stale,
            "changed": changed[:limit],
            "missing": missing[:limit],
            "new_files": new_files[:limit],
            "total_changed": len(changed),
            "total_missing": len(missing),
            "total_new": len(new_files),
            "scope": scope,
        }
    except Exception as exc:
        return {"kind": "index_sync", "error": str(exc), "stale": True, "changed": [], "missing": [], "new_files": []}


def format_index_sync_context(result: dict) -> str:
    if result.get("error"):
        return f"Index sync check failed: {result['error']}"
    lines = [
        "Index sync status:",
        f"Checked indexed files: {result.get('checked', 0)}",
        f"Changed: {result.get('total_changed', 0)}",
        f"Missing: {result.get('total_missing', 0)}",
        f"New files: {result.get('total_new', 0)}",
        "",
    ]
    if not result.get("stale"):
        lines.append("Index appears synchronized with the current project files.")
        return "\n".join(lines)
    for label, key in (("Changed files", "changed"), ("Missing indexed files", "missing"), ("New unindexed files", "new_files")):
        rows = result.get(key, [])
        if not rows:
            continue
        lines.append(label + ":")
        for i, row in enumerate(rows[:30], 1):
            lines.append(f"[{i}] {row.get('path')} — {row.get('reason')}")
        lines.append("")
    lines.append("Recommendation: run a quick index before relying on project-wide answers if these files affect the question.")
    return "\n".join(lines)


def analyze_unused_symbols(*, symbol_kind: str | None = None, scope: str = SOURCE_PROJECT, limit: int = 200) -> dict:
    """Find candidate unused functions/classes/methods using the symbol and dependency graph.

    This is a static heuristic. It favors speed and explainability over claiming
    certainty. The result is intended for Project Health UI/LLM summarization.
    """
    try:
        with _connect_index() as conn:
            scope_sql, scope_params = _health_scope_sql("f", scope)
            kind_sql = ""
            params = list(scope_params)
            if symbol_kind:
                kind_sql = " AND s.kind = ? "
                params.append(symbol_kind)
            rows = conn.execute(
                f"""
                SELECT s.id, s.name, s.qualname, s.parent_qualname, s.parent_kind, s.kind, s.start_line, s.end_line,
                       s.signature, s.source, f.path, f.rel_path, f.module, f.source_scope
                FROM symbols s
                JOIN files f ON f.id = s.file_id
                WHERE 1=1 {scope_sql} {kind_sql}
                ORDER BY f.path, s.start_line
                LIMIT 5000
                """,
                tuple(params),
            ).fetchall()

            candidates = []
            skipped = 0
            for row_obj in rows:
                row = dict(row_obj)
                skip, skip_reason = _symbol_health_skip(row)
                if skip:
                    skipped += 1
                    continue
                name = row["name"]
                qualname = row.get("qualname") or name
                path = row.get("path") or ""

                call_like = f"%{name}%"
                call_refs = conn.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM symbol_calls sc
                    JOIN symbols owner ON owner.id = sc.symbol_id
                    JOIN files f ON f.id = owner.file_id
                    WHERE (sc.call_name = ? OR sc.call_name LIKE ? OR sc.call_name LIKE ?)
                      AND f.path != ?
                    """,
                    (name, f"%.{name}", call_like, path),
                ).fetchone()["c"]

                text_refs = conn.execute(
                    """
                    SELECT COUNT(DISTINCT f.path) AS c
                    FROM chunks c
                    JOIN files f ON f.id = c.file_id
                    WHERE c.text LIKE ? AND f.path != ?
                    """,
                    (call_like, path),
                ).fetchone()["c"]

                # For class definitions, constructor calls often appear as normal text or call names.
                ref_count = int(call_refs or 0) + int(text_refs or 0)
                if ref_count > 0:
                    continue

                confidence = "medium" if row.get("kind") == "method" else "high"
                reason = "No indexed calls or text references outside the defining file."
                if row.get("kind") == "method":
                    reason += " Method usage can be dynamic through Qt signals, inheritance, or callbacks."

                candidates.append({
                    "path": path,
                    "rel_path": row.get("rel_path"),
                    "module": row.get("module"),
                    "symbol": name,
                    "qualname": qualname,
                    "parent_qualname": row.get("parent_qualname"),
                    "parent_kind": row.get("parent_kind"),
                    "kind": row.get("kind"),
                    "line": row.get("start_line"),
                    "end_line": row.get("end_line"),
                    "signature": row.get("signature"),
                    "confidence": confidence,
                    "reason": reason,
                    "call_refs": int(call_refs or 0),
                    "text_refs": int(text_refs or 0),
                })
                if len(candidates) >= limit:
                    break

            return {
                "kind": "unused_symbols",
                "symbol_kind": symbol_kind or "all",
                "scope": scope,
                "candidates": candidates,
                "total_candidates": len(candidates),
                "skipped_framework_like": skipped,
            }
    except Exception as exc:
        return {"kind": "unused_symbols", "symbol_kind": symbol_kind or "all", "error": str(exc), "candidates": []}


def analyze_unused_functions(*, scope: str = SOURCE_PROJECT, limit: int = 200) -> dict:
    return analyze_unused_symbols(symbol_kind="function", scope=scope, limit=limit)


def analyze_unused_classes(*, scope: str = SOURCE_PROJECT, limit: int = 200) -> dict:
    return analyze_unused_symbols(symbol_kind="class", scope=scope, limit=limit)


def format_unused_symbols_context(result: dict) -> str:
    if result.get("error"):
        return f"Unused symbol analysis error: {result['error']}"
    rows = result.get("candidates", [])
    label = result.get("symbol_kind") or "symbols"
    lines = [
        f"Project health analysis: unused {label} candidates",
        f"Scope: {result.get('scope', '(default)')}",
        f"Candidates returned: {len(rows)}",
        f"Framework/entrypoint-like symbols skipped: {result.get('skipped_framework_like', 0)}",
        "",
    ]
    if not rows:
        lines.append("No unused symbol candidates were found by the static analysis heuristic.")
        return "\n".join(lines)
    for i, row in enumerate(rows, 1):
        lines.append(
            f"[{i}] {row.get('kind')} {row.get('qualname') or row.get('symbol')} "
            f"line {row.get('line')}\n"
            f"    file: {row.get('path')}\n"
            f"    confidence: {row.get('confidence')}\n"
            f"    reason: {row.get('reason')}"
        )
    lines.append("\nImportant: this is static analysis. Verify callbacks, reflection, plugin entry points, dynamic imports, and DCC-discovered symbols before deleting anything.")
    return "\n".join(lines)
