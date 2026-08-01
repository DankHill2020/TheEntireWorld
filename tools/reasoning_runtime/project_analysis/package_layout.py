"""AST-based package layout audits."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


DEFAULT_IGNORED_DIRS = {
    ".ai_studio",
    ".git",
    ".index_backups",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "data",
    "installers",
    "node_modules",
}


def _top_level_import_targets(tree: ast.Module, current_module: str) -> set[str]:
    targets: set[str] = set()

    def is_main_guard(test: ast.expr) -> bool:
        return (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        )

    def visit(statements: list[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Import):
                targets.update(alias.name for alias in statement.names)
            elif isinstance(statement, ast.ImportFrom):
                if statement.level:
                    parts = current_module.split(".")
                    base = parts[: max(0, len(parts) - statement.level)]
                    module = ".".join([*base, statement.module or ""]).strip(".")
                else:
                    module = statement.module or ""
                if module:
                    targets.add(module)
                    targets.update(
                        f"{module}.{alias.name}"
                        for alias in statement.names
                        if alias.name != "*"
                    )
            elif isinstance(statement, ast.If):
                is_type_checking = (
                    isinstance(statement.test, ast.Name)
                    and statement.test.id == "TYPE_CHECKING"
                ) or (
                    isinstance(statement.test, ast.Attribute)
                    and statement.test.attr == "TYPE_CHECKING"
                )
                if not is_type_checking and not is_main_guard(statement.test):
                    visit(statement.body)
                    visit(statement.orelse)
            elif isinstance(statement, (ast.Try, ast.TryStar)):
                visit(statement.body)
                for handler in statement.handlers:
                    visit(handler.body)
                visit(statement.orelse)
                visit(statement.finalbody)

    visit(tree.body)
    return targets


def _build_import_graph(module_trees: dict[str, ast.Module]) -> dict[str, set[str]]:
    known_modules = set(module_trees)
    graph: dict[str, set[str]] = {module: set() for module in known_modules}
    for module, tree in module_trees.items():
        for imported in _top_level_import_targets(tree, module):
            candidate = imported
            while candidate and candidate not in known_modules:
                candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
            if candidate and candidate != module:
                graph[module].add(candidate)
    return graph


def _find_import_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    state: dict[str, int] = {}
    stack: list[str] = []
    positions: dict[str, int] = {}
    cycles: dict[tuple[str, ...], list[str]] = {}

    def canonical(nodes: list[str]) -> tuple[str, ...]:
        rotations = [tuple(nodes[index:] + nodes[:index]) for index in range(len(nodes))]
        return min(rotations)

    def visit(module: str) -> None:
        state[module] = 1
        positions[module] = len(stack)
        stack.append(module)
        for imported in sorted(graph.get(module, ())):
            if state.get(imported, 0) == 0:
                visit(imported)
            elif state.get(imported) == 1:
                nodes = stack[positions[imported]:]
                if nodes:
                    cycles.setdefault(canonical(nodes), nodes)
        stack.pop()
        positions.pop(module, None)
        state[module] = 2

    for module in sorted(graph):
        if state.get(module, 0) == 0:
            visit(module)
    return [cycles[key] for key in sorted(cycles)]


def audit_python_package_layout(
    project_root: str | Path,
    *,
    package_name: str,
    first_party_packages: tuple[str, ...],
    ignored_dirs: set[str] | None = None,
    legacy_marker: str = "/the_entire_world_ai_studio",
) -> dict[str, Any]:
    """Audit imports, stale paths, parse errors, and import cycles."""

    root = Path(project_root).expanduser().resolve()
    package_root = root / package_name if (root / package_name).is_dir() else root
    ignored = set(ignored_dirs or DEFAULT_IGNORED_DIRS)
    unqualified_imports: list[dict[str, Any]] = []
    stale_paths: list[dict[str, Any]] = []
    legacy_compatibility_refs: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    module_trees: dict[str, ast.Module] = {}
    module_paths: dict[str, str] = {}
    personal_references: list[dict[str, Any]] = []
    hardcoded_user_paths: list[dict[str, Any]] = []

    for path in package_root.rglob("*.py"):
        if any(part in ignored for part in path.parts):
            continue
        if "tests" in path.relative_to(package_root).parts:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as exc:
            parse_errors.append({"path": str(path), "error": str(exc)})
            continue
        relative_path = path.relative_to(package_root)
        relative = str(relative_path)
        module_parts = list(relative_path.with_suffix("").parts)
        if module_parts and module_parts[-1] == "__init__":
            module_parts.pop()
        module_name = ".".join((package_name, *module_parts))
        module_trees[module_name] = tree
        module_paths[module_name] = str(path)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                root_name = module.split(".", 1)[0]
                if root_name in first_party_packages:
                    unqualified_imports.append(
                        {"path": str(path), "relative_path": relative, "line": node.lineno, "module": module}
                    )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                normalized = node.value.replace("\\", "/").lower()
                if legacy_marker in normalized:
                    finding = {
                        "path": str(path),
                        "relative_path": relative,
                        "line": node.lineno,
                        "value": node.value,
                    }
                    if normalized == legacy_marker:
                        legacy_compatibility_refs.append(finding)
                    else:
                        stale_paths.append(finding)

    import_graph = _build_import_graph(module_trees)
    circular_imports = [
        {"modules": cycle, "paths": [module_paths[module] for module in cycle]}
        for cycle in _find_import_cycles(import_graph)
    ]

    text_extensions = {".bat", ".cfg", ".ini", ".json", ".jsonl", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
    current_user = Path.home().name.lower()
    user_home_segment = ":/" + "users/"
    for path in package_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_extensions:
            continue
        if any(part in ignored for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        relative = str(path.relative_to(package_root))
        for line_number, line in enumerate(lines, start=1):
            normalized = line.replace("\\", "/").lower()
            finding = {"path": str(path), "relative_path": relative, "line": line_number}
            if current_user and current_user in normalized:
                personal_references.append(finding)
            if user_home_segment in normalized:
                hardcoded_user_paths.append(finding)

    return {
        "ok": not unqualified_imports and not stale_paths and not parse_errors and not circular_imports and not personal_references and not hardcoded_user_paths,
        "project_root": str(root),
        "package_root": str(package_root),
        "package_name": package_name,
        "unqualified_imports": unqualified_imports,
        "stale_paths": stale_paths,
        "legacy_compatibility_refs": legacy_compatibility_refs,
        "parse_errors": parse_errors,
        "circular_imports": circular_imports,
        "module_count": len(module_trees),
        "import_edge_count": sum(len(edges) for edges in import_graph.values()),
        "personal_references": personal_references,
        "hardcoded_user_paths": hardcoded_user_paths,
    }
