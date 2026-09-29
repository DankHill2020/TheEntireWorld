"""Service for indexing and discovering project internal functions and ingested third-party tools."""

from __future__ import annotations

import ast
import time
from collections import OrderedDict
from pathlib import Path


def _name_from_ast(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_from_ast(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _name_from_ast(node.func)
    if isinstance(node, ast.Constant):
        return type(node.value).__name__.lower()
    if isinstance(node, (ast.Tuple, ast.List)):
        return "_".join(_name_from_ast(item) for item in node.elts if _name_from_ast(item))
    return ""


def _annotation_text(annotation) -> str:
    if annotation is None:
        return ""
    try:
        return ast.unparse(annotation)
    except Exception:
        return ""


def _function_params(node) -> list[dict]:
    params: list[dict] = []
    positional = list(getattr(node.args, "posonlyargs", [])) + list(node.args.args)
    positional_defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
    keyword = list(node.args.kwonlyargs)
    keyword_defaults = list(node.args.kw_defaults)
    for arg, default in [*zip(positional, positional_defaults), *zip(keyword, keyword_defaults)]:
        if arg.arg in {"self", "cls"}:
            continue
        item = {"name": arg.arg, "annotation": _annotation_text(arg.annotation)}
        if default is not None:
            try:
                item["default"] = ast.unparse(default)
            except Exception:
                item["default"] = "provided"
        params.append(item)
    if node.args.vararg:
        params.append({"name": "*" + node.args.vararg.arg, "annotation": _annotation_text(node.args.vararg.annotation)})
    if node.args.kwarg:
        params.append({"name": "**" + node.args.kwarg.arg, "annotation": _annotation_text(node.args.kwarg.annotation)})
    return params


def _return_names(node) -> list[str]:
    """Extract all returned variable names, unpacking tuples."""
    # Names to skip — these are noise, not real outputs
    _SKIP = {"none", "nonetype", "true", "false", ""}
    names = []
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            # Skip bare `return None` / `return True` etc.
            if isinstance(child.value, ast.Constant):
                continue
            if isinstance(child.value, ast.Tuple):
                # Tuple return: extract each element name
                for elt in child.value.elts:
                    if isinstance(elt, ast.Constant):
                        continue
                    name = _name_from_ast(elt)
                    if name and name.lower() not in _SKIP and name not in names:
                        names.append(name)
            else:
                name = _name_from_ast(child.value)
                if name and name.lower() not in _SKIP and name not in names:
                    names.append(name)
    return names


def _return_outputs(node, return_annotation: str) -> list[dict]:
    """Build a structured list of output slot dicts: {name, annotation}.
    
    If the return annotation is a Tuple, we try to match each element type.
    Falls back to labeling all returns with the overall annotation.
    """
    names = _return_names(node)
    if len(names) == 1 and ("." in names[0] or names[0].lower() in {"dict", "list", "set", "tuple"}):
        names = ["result"]
    
    # Try to parse annotation as Tuple[X, Y, Z] to get per-element types
    elem_types = []
    if return_annotation:
        try:
            anno_tree = ast.parse(return_annotation, mode='eval')
            anno_node = anno_tree.body
            # Check for Tuple[X, Y, Z] or tuple[X, Y, Z]
            if isinstance(anno_node, ast.Subscript):
                origin = _name_from_ast(anno_node.value).lower()
                if origin == "tuple":
                    slice_node = anno_node.slice
                    if isinstance(slice_node, ast.Tuple):
                        for elt in slice_node.elts:
                            elem_types.append(_annotation_text(elt))
        except Exception:
            pass
    
    outputs = []
    for i, name in enumerate(names):
        anno = elem_types[i] if i < len(elem_types) else (return_annotation if len(names) <= 1 else "")
        outputs.append({"name": name, "annotation": anno})
    
    # If no names extracted, add a single generic 'result'
    if not outputs:
        outputs.append({"name": "result", "annotation": return_annotation or ""})
        
    return outputs


_SYMBOL_CACHE_MAX_ENTRIES = 4096
_SYMBOL_CACHE = OrderedDict()
_SYMBOL_EXTRACTION_ACTIVE: set[str] = set()


def resolve_local_star_import_paths(file_path: Path, tree: ast.AST) -> list[Path]:
    """
        Resolves local modules re-exported by module-level star imports.
    :param file_path: Python facade file containing the imports.
    :param tree: parsed syntax tree for the facade.
    :return: ordered local implementation paths.
    """
    path = Path(file_path).resolve()
    resolved: list[Path] = []
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.ImportFrom) or not any(alias.name == "*" for alias in node.names):
            continue
        module_parts = [part for part in str(node.module or "").split(".") if part]
        bases: list[Path]
        if node.level:
            base = path.parent
            for _unused in range(max(0, int(node.level) - 1)):
                base = base.parent
            bases = [base]
        else:
            bases = [path.parent, *path.parents]
        for base in bases:
            module_base = base.joinpath(*module_parts) if module_parts else base
            candidates = [module_base.with_suffix(".py"), module_base / "__init__.py"]
            target = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
            if target is not None and target != path and target not in resolved:
                resolved.append(target)
                break
    return resolved


def _explicit_all_contract(file_path: Path) -> tuple[bool, set[str] | None]:
    """
        Reads a module's explicit star-export contract when statically declared.
    :param file_path: Python implementation module to inspect.
    :return: declaration flag and static names, or None names for a dynamic contract.
    """
    try:
        tree = ast.parse(Path(file_path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, UnicodeError):
        return False, None
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return True, None
            if isinstance(value, (list, tuple)) and all(isinstance(name, str) for name in value):
                return True, set(value)
            return True, None
    return False, None


def extract_symbols_from_file(file_path: Path) -> list[dict]:
    file_path = Path(file_path).resolve()
    file_path_str = str(file_path)
    
    try:
        mtime = file_path.stat().st_mtime
    except Exception:
        _SYMBOL_CACHE.pop(file_path_str, None)
        return []
        
    if file_path_str in _SYMBOL_CACHE:
        cached_entry = _SYMBOL_CACHE[file_path_str]
        if len(cached_entry) == 2:
            cached_mtime, cached_symbols = cached_entry
            dependency_mtimes = {}
        else:
            cached_mtime, dependency_mtimes, cached_symbols = cached_entry
        dependencies_current = all(
            Path(dependency).is_file() and Path(dependency).stat().st_mtime == dependency_mtime
            for dependency, dependency_mtime in dependency_mtimes.items()
        )
        if cached_mtime == mtime and dependencies_current:
            _SYMBOL_CACHE.move_to_end(file_path_str)
            return cached_symbols

    if file_path_str in _SYMBOL_EXTRACTION_ACTIVE:
        return []
    _SYMBOL_EXTRACTION_ACTIVE.add(file_path_str)

    symbols = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        _SYMBOL_EXTRACTION_ACTIVE.discard(file_path_str)
        return symbols

    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        _SYMBOL_EXTRACTION_ACTIVE.discard(file_path_str)
        return symbols

    lines = content.splitlines(keepends=True)

    class SymbolVisitor(ast.NodeVisitor):
        def __init__(self):
            super().__init__()
            self.scope_stack = []

        def visit_FunctionDef(self, node):
            self.add_node(node, "function")
            self.scope_stack.append(("function", node.name))
            try:
                self.generic_visit(node)
            finally:
                self.scope_stack.pop()

        def visit_AsyncFunctionDef(self, node):
            self.add_node(node, "function")
            self.scope_stack.append(("function", node.name))
            try:
                self.generic_visit(node)
            finally:
                self.scope_stack.pop()

        def visit_ClassDef(self, node):
            self.add_node(node, "class")
            self.scope_stack.append(("class", node.name))
            try:
                self.generic_visit(node)
            finally:
                self.scope_stack.pop()

        @staticmethod
        def decorator_name(decorator):
            if isinstance(decorator, ast.Call):
                return SymbolVisitor.decorator_name(decorator.func)
            if isinstance(decorator, ast.Name):
                return decorator.id
            if isinstance(decorator, ast.Attribute):
                prefix = SymbolVisitor.decorator_name(decorator.value)
                return f"{prefix}.{decorator.attr}" if prefix else decorator.attr
            return ""

        def add_node(self, node, kind):
            try:
                start = node.lineno - 1
                end = node.end_lineno
                source_lines = lines[start:end]
                source = "".join(source_lines).strip()
                
                # Simple signature extraction: first line of the definition
                first_line = source_lines[0].strip() if source_lines else ""
                if first_line.endswith(":"):
                    first_line = first_line[:-1].strip()
                    
                is_func = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                return_anno = _annotation_text(getattr(node, "returns", None))
                qualified_name = ".".join(
                    [scope_name for _scope_kind, scope_name in self.scope_stack]
                    + [node.name]
                )
                class_name = next(
                    (
                        scope_name
                        for scope_kind, scope_name in reversed(self.scope_stack)
                        if scope_kind == "class"
                    ),
                    "",
                )
                parent_function = next(
                    (
                        scope_name
                        for scope_kind, scope_name in reversed(self.scope_stack)
                        if scope_kind == "function"
                    ),
                    "",
                )
                decorator_names = {
                    self.decorator_name(decorator).rsplit(".", 1)[-1]
                    for decorator in getattr(node, "decorator_list", [])
                }
                if not is_func:
                    callable_scope = "class"
                elif parent_function:
                    callable_scope = "nested_function"
                elif class_name and "staticmethod" in decorator_names:
                    callable_scope = "static_method"
                elif class_name and "classmethod" in decorator_names:
                    callable_scope = "class_method"
                elif class_name:
                    callable_scope = "instance_method"
                else:
                    callable_scope = "module_function"
                symbols.append({
                    "name": node.name,
                    "qualified_name": qualified_name,
                    "class_name": class_name,
                    "callable_scope": callable_scope,
                    "file_path": str(file_path),
                    "kind": kind,
                    "lineno": getattr(node, "lineno", 0),
                    "end_lineno": getattr(node, "end_lineno", 0),
                    "signature": first_line,
                    "source": source,
                    "docstring": ast.get_docstring(node) or "",
                    "params": _function_params(node) if is_func else [],
                    "return_annotation": return_anno,
                    "returns": _return_names(node) if is_func else [],
                    "outputs": _return_outputs(node, return_anno) if is_func else [{"name": "instance", "annotation": node.name}],
                })
            except Exception:
                pass

    try:
        visitor = SymbolVisitor()
        visitor.visit(tree)

        dependency_mtimes: dict[str, float] = {}
        existing_names = {
            str(symbol.get("name") or "")
            for symbol in symbols
            if str(symbol.get("callable_scope") or "") in {"module_function", "class"}
        }
        for implementation_path in resolve_local_star_import_paths(file_path, tree):
            try:
                dependency_mtimes[str(implementation_path)] = implementation_path.stat().st_mtime
            except OSError:
                continue
            declares_explicit_all, explicit_names = _explicit_all_contract(implementation_path)
            for implementation_symbol in extract_symbols_from_file(implementation_path):
                scope = str(implementation_symbol.get("callable_scope") or "")
                name = str(implementation_symbol.get("name") or "")
                if (
                    scope not in {"module_function", "class"}
                    or not name
                    or name in existing_names
                    or (explicit_names is not None and name not in explicit_names)
                    or (name.startswith("_") and not declares_explicit_all)
                ):
                    continue
                exported = dict(implementation_symbol)
                exported["implementation_file_path"] = str(
                    implementation_symbol.get("implementation_file_path") or implementation_path
                )
                exported["file_path"] = file_path_str
                exported["reexported"] = True
                symbols.append(exported)
                existing_names.add(name)

        _SYMBOL_CACHE[file_path_str] = (mtime, dependency_mtimes, symbols)
        _SYMBOL_CACHE.move_to_end(file_path_str)
        while len(_SYMBOL_CACHE) > _SYMBOL_CACHE_MAX_ENTRIES:
            _SYMBOL_CACHE.popitem(last=False)
        return symbols
    finally:
        _SYMBOL_EXTRACTION_ACTIVE.discard(file_path_str)


def list_internal_functions(
    project_roots: list[str],
    *,
    max_files: int | None = 1500,
    time_budget_seconds: float | None = 5.0,
) -> list[dict]:
    """Discover Python symbols below the supplied project roots.

    ``None`` disables the corresponding safety limit.  Interactive callers can
    keep the bounded defaults, while background inventory jobs can request a
    complete catalog for the project selected in the UI.
    """
    all_funcs = []
    skip_dirs = {"external_tools", "thirdparty", "venv", ".venv", ".git", "__pycache__", "build", "dist", ".agents", ".gemini", "node_modules", ".idea", ".vscode", "tests", ".ai_studio", "Intermediate", "Saved", "DerivedDataCache"}
    started = time.monotonic()
    scanned = 0
    scanned_paths: set[str] = set()
    
    for root in project_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
            
        for path in root_path.rglob("*.py"):
            if max_files is not None and scanned >= max_files:
                return all_funcs
            if time_budget_seconds is not None and time.monotonic() - started >= time_budget_seconds:
                return all_funcs
            # Check if any parent part is in skip_dirs
            if any(part in skip_dirs for part in path.parts):
                continue
            if not path.is_file():
                continue
            try:
                path_key = str(path.resolve()).casefold()
            except OSError:
                path_key = str(path).casefold()
            if path_key in scanned_paths:
                continue
            scanned_paths.add(path_key)
            scanned += 1
            all_funcs.extend(extract_symbols_from_file(path))
            
    return all_funcs


def list_ingested_tools(
    external_tools_dir: Path,
    *,
    max_files: int = 800,
    time_budget_seconds: float = 3.0,
) -> list[dict]:
    all_tools = []
    if not external_tools_dir.exists() or not external_tools_dir.is_dir():
        return all_tools
    started = time.monotonic()
    scanned = 0

    for path in external_tools_dir.rglob("*.py"):
        if scanned >= max_files or time.monotonic() - started >= time_budget_seconds:
            return all_tools
        if "__pycache__" in path.parts:
            continue
        if not path.is_file():
            continue
        scanned += 1
        all_tools.extend(extract_symbols_from_file(path))
        
    return all_tools
