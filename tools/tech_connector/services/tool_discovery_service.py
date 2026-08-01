"""Service for indexing and discovering project internal functions and ingested third-party tools."""

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


def extract_symbols_from_file(file_path: Path) -> list[dict]:
    file_path = Path(file_path).resolve()
    file_path_str = str(file_path)
    
    try:
        mtime = file_path.stat().st_mtime
    except Exception:
        _SYMBOL_CACHE.pop(file_path_str, None)
        return []
        
    if file_path_str in _SYMBOL_CACHE:
        cached_mtime, cached_symbols = _SYMBOL_CACHE[file_path_str]
        if cached_mtime == mtime:
            _SYMBOL_CACHE.move_to_end(file_path_str)
            return cached_symbols

    symbols = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return symbols

    try:
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
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

    visitor = SymbolVisitor()
    visitor.visit(tree)
    _SYMBOL_CACHE[file_path_str] = (mtime, symbols)
    _SYMBOL_CACHE.move_to_end(file_path_str)
    while len(_SYMBOL_CACHE) > _SYMBOL_CACHE_MAX_ENTRIES:
        _SYMBOL_CACHE.popitem(last=False)
    return symbols


def list_internal_functions(
    project_roots: list[str],
    *,
    max_files: int = 1500,
    time_budget_seconds: float = 5.0,
) -> list[dict]:
    all_funcs = []
    skip_dirs = {"external_tools", "thirdparty", "venv", ".venv", ".git", "__pycache__", "build", "dist", ".agents", ".gemini", "node_modules", ".idea", ".vscode", "tests", ".ai_studio", "Intermediate", "Saved", "DerivedDataCache"}
    started = time.monotonic()
    scanned = 0
    
    for root in project_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
            
        for path in root_path.rglob("*.py"):
            if scanned >= max_files or time.monotonic() - started >= time_budget_seconds:
                return all_funcs
            # Check if any parent part is in skip_dirs
            if any(part in skip_dirs for part in path.parts):
                continue
            if not path.is_file():
                continue
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
