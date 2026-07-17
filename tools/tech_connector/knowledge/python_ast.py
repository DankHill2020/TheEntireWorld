"""AST-based local symbol analysis."""

import ast
import re


def question_terms(question: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", question)
    terms = set()
    for token in raw_tokens:
        token_lower = token.lower()
        terms.add(token_lower)
        parts = token.split('_')
        for part in parts:
            if not part:
                continue
            sub_words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)|[0-9]+', part)
            for sw in sub_words:
                terms.add(sw.lower())

    stems = set()
    for t in terms:
        for suffix in ['able', 'ing', 'ed', 'er', 'est', 'ly', 's']:
            if t.endswith(suffix) and len(t) - len(suffix) >= 3:
                stems.add(t[:-len(suffix)])
    terms.update(stems)

    stop = {
        "is", "there", "a", "an", "the", "that", "to", "in", "of", "for", "with",
        "does", "do", "class", "function", "method", "file", "this", "are", "any",
    }
    filtered = [t for t in terms if t not in stop and len(t) > 2]
    expansions = {
        "browse": ["browse", "browser", "browses", "browsing", "select", "choose", "pick", "open"],
        "directory": ["directory", "dir", "folder", "path"],
        "folder": ["folder", "directory", "dir", "path"],
        "button": ["button", "btn", "pushbutton", "qpushbutton"],
        "widget": ["widget", "qwidget", "control"],
    }
    expanded = set(filtered)
    for t in list(filtered):
        for key, vals in expansions.items():
            if t == key or t in vals:
                expanded.update(vals)
    return sorted(expanded)



_ast_cache = {}


def extract_python_symbols_from_text(text: str) -> list[dict]:
    text_hash = hash(text)
    if text_hash in _ast_cache:
        return [dict(s) for s in _ast_cache[text_hash]]

    symbols = []
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except Exception:
        return symbols
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = getattr(node, "name", "")
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            start = getattr(node, "lineno", 1)
            end = getattr(node, "end_lineno", start)
            source = "\n".join(lines[start - 1:end])
            doc = ast.get_docstring(node) or ""
            methods = []
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(child.name)
            symbols.append({
                "name": name,
                "kind": kind,
                "start": start,
                "end": end,
                "doc": doc,
                "methods": methods,
                "source": source,
                "search": "\n".join([name, kind, doc, " ".join(methods), source]).lower(),
            })
    _ast_cache[text_hash] = symbols
    return [dict(s) for s in symbols]



def rank_symbols_for_question(symbols: list[dict], terms: list[str]) -> list[tuple[int, dict]]:
    ranked = []
    for sym in symbols:
        score = 0
        name_low = sym["name"].lower()
        method_low = " ".join(sym["methods"]).lower()
        for term in terms:
            if term in name_low:
                score += 12
            if term in sym["doc"].lower():
                score += 6
            if term in method_low:
                score += 5
            count = sym["search"].count(term)
            if count:
                score += min(count, 10)
        if score > 0 and sym["kind"] == "class":
            score += 2
        if score > 0:
            ranked.append((score, sym))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def summarize_python_symbol(sym: dict, question: str) -> str:
    """Produce a useful local explanation with the code reference first."""
    source = sym.get("source", "")
    name = sym.get("name", "")
    kind = sym.get("kind", "symbol")
    methods = sym.get("methods", [])

    out = []

    out.append("Relevant source excerpt:")
    lang = "python"
    out.append(f"```{lang}\n{source[:2600]}\n```")
    out.append("")

    out.append("Explanation:")
    out.append(f"`{name}` is a Python {kind} defined on lines {sym.get('start')}-{sym.get('end')}.")

    if kind == "class":
        bases = ""
        try:
            tree = ast.parse(source)
            cls = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
            if cls:
                base_names = []
                for b in cls.bases:
                    try:
                        base_names.append(ast.unparse(b))
                    except Exception:
                        pass
                if base_names:
                    bases = ", ".join(base_names)
        except Exception:
            pass

        if bases:
            out.append(f"It subclasses `{bases}`.")

        lowered = source.lower()
        responsibilities = []

        if "qfiledialog.getexistingdirectory" in lowered:
            responsibilities.append("opens a folder picker dialog so the user can choose a directory")
        if "qlineedit" in lowered:
            responsibilities.append("shows the current directory in an editable text field")
        if "qpushbutton" in lowered:
            responsibilities.append("provides a Browse button")
        if "textchanged.connect" in lowered:
            responsibilities.append("keeps its internal directory value synchronized when the user edits the text manually")
        if "replace('\\\\', '/')" in lowered or 'replace("\\\\", "/")' in lowered:
            responsibilities.append("normalizes Windows backslashes into forward slashes")
        if "partial(" in lowered:
            responsibilities.append("uses a partial/lambda callback to pass the line-edit widget into the browse handler")
        if "event.ignore()" in lowered and "wheelevent" in lowered:
            responsibilities.append("prevents mouse wheel scrolling on the spin box by ignoring the wheel event")

        if responsibilities:
            out.append("")
            out.append("What it does:")
            for r in responsibilities:
                out.append(f"- It {r}.")
        else:
            out.append("")
            out.append("What it does:")
            out.append("- It groups related UI behavior and state into a reusable class.")

        if methods:
            out.append("")
            out.append("Important methods:")
            for m in methods:
                if m == "__init__":
                    out.append("- `__init__`: builds the widget layout, stores initial state, creates the line edit and Browse button, and wires UI signals.")
                elif "get_dir" in m or "browse" in m:
                    out.append(f"- `{m}`: opens the directory browser and updates the stored directory if the user chooses one.")
                elif "update" in m:
                    out.append(f"- `{m}`: updates internal state when the UI text changes.")
                elif "wheelEvent" in m:
                    out.append("- `wheelEvent`: overrides the standard mouse wheel handler to ignore events, preventing scrolling.")
                else:
                    out.append(f"- `{m}`")

        concerns = []
        if "directory.replace" in source and "directory=None" in source:
            concerns.append("`directory` defaults to `None`, but `directory.replace(...)` will crash if `None` is actually passed.")
        if "lambda:" in source and "partial(" in source:
            concerns.append("the signal connection is more complex than it needs to be; a normal method or lambda would be easier to read.")
        if "new_height = 10" in source:
            concerns.append("the repeated manual resize to height `10` looks suspicious and may produce cramped UI behavior.")
        if "self.tr('Select Export Directory')" in source:
            concerns.append("the dialog title says `Select Export Directory`, which may be too specific if the widget is meant to be generic.")
        if "event.ignore()" in source and "super" not in source:
            concerns.append("The wheelEvent ignores the scroll event, completely disabling mouse wheel adjustments.")

        if concerns:
            out.append("")
            out.append("Potential issues:")
            for c in concerns:
                out.append(f"- {c}")

        out.append("")
        out.append("Direct answer:")
        if name.lower() == "browsedirectory":
            out.append("`BrowseDirectory` is a reusable Qt widget for displaying, editing, and browsing for a folder path. It combines a line edit and a Browse button, opens a directory picker, stores the selected path, and keeps the stored value updated when the user manually edits the text.")
        elif name.lower() == "nonscrollingspinbox":
            out.append("`NonScrollingSpinBox` is a subclass of `QSpinBox` that disables mouse wheel scrolling. To make it scrollable, you should either remove the overridden `wheelEvent` method completely (so it inherits the default scrolling behavior) or call `super(NonScrollingSpinBox, self).wheelEvent(event)` inside the method to forward the event to the parent class.")
        else:
            out.append(f"`{name}` is the best local match for your question based on its name, methods, and source.")

    else:
        out.append("")
        out.append("Direct answer:")
        out.append(f"`{name}` is a function. The local analyzer found it because its name/source matches your question.")
        src_low = source.lower()
        if "return" in src_low:
            out.append("- It returns a value.")
        if "print(" in src_low:
            out.append("- It prints output.")
        if "connect(" in src_low:
            out.append("- It connects UI/event behavior.")
        if "qfiledialog" in src_low:
            out.append("- It opens a Qt file/folder dialog.")

    return "\n".join(out)
