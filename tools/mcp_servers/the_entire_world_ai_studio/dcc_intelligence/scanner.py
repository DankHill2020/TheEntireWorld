"""Filesystem and Python-source indexers shared by DCC adapters."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Iterable

from .store import IntelligenceStore, ProjectRef

DEFAULT_IGNORES = {".git", "__pycache__", ".ai_studio", ".project_ai", "Intermediate", "Saved", "DerivedDataCache"}

DCC_EXTENSIONS = {
    "unreal": {".uproject", ".uasset", ".umap", ".ini", ".py", ".json", ".ush", ".usf"},
    "maya": {".ma", ".mb", ".mel", ".py", ".json"},
    "blender": {".blend", ".py", ".json"},
    "substance": {".spp", ".sbs", ".sbsar", ".py", ".json"},
    "generic": {".py", ".json", ".yaml", ".yml", ".md", ".txt"},
}


def should_skip(path: Path, ignores: set[str] | None = None) -> bool:
    ignored = ignores or DEFAULT_IGNORES
    return any(part in ignored for part in path.parts)


def hash_file(path: Path, max_bytes: int = 2_000_000) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            h.update(handle.read(max_bytes))
        return h.hexdigest()
    except OSError:
        return None


def guess_asset_type(path: Path, dcc: str) -> str:
    suffix = path.suffix.lower()
    if dcc == "unreal":
        if suffix == ".uasset":
            return "unreal_asset"
        if suffix == ".umap":
            return "unreal_level"
        if suffix == ".uproject":
            return "unreal_project"
        if suffix == ".ini":
            return "unreal_config"
    if suffix == ".py":
        return "python_source"
    if suffix in {".json", ".yaml", ".yml"}:
        return "structured_data"
    return suffix.lstrip(".") or "unknown"


class ProjectScanner:
    def __init__(self, store: IntelligenceStore):
        self.store = store

    def scan_project(self, root_path: str | Path, dcc: str = "generic", name: str | None = None,
                     include_extensions: Iterable[str] | None = None) -> ProjectRef:
        root = Path(root_path).resolve()
        project = self.store.upsert_project(dcc=dcc, name=name or root.name, root_path=root)
        extensions = {e.lower() for e in (include_extensions or DCC_EXTENSIONS.get(dcc, DCC_EXTENSIONS["generic"]))}

        for path in root.rglob("*"):
            if path.is_dir() or should_skip(path.relative_to(root)):
                continue
            if path.suffix.lower() not in extensions:
                continue
            stat = path.stat()
            rel = path.relative_to(root).as_posix()
            self.store.upsert_asset(
                project.id,
                dcc,
                asset_path=rel,
                asset_name=path.name,
                asset_type=guess_asset_type(path, dcc),
                package_path=str(path.parent.relative_to(root)).replace("\\", "/"),
                modified_at=stat.st_mtime,
                size_bytes=stat.st_size,
                content_hash=hash_file(path),
                metadata={"extension": path.suffix.lower()},
            )
            if path.suffix.lower() == ".py":
                self._scan_python_source(project, dcc, root, path)
        return project

    def _scan_python_source(self, project: ProjectRef, dcc: str, root: Path, path: Path) -> None:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            return
        rel = path.relative_to(root).as_posix()
        module = rel[:-3].replace("/", ".") if rel.endswith(".py") else rel.replace("/", ".")
        class_stack: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [getattr(b, "id", getattr(b, "attr", "")) for b in node.bases]
                self.store.conn.execute(
                    """
                    INSERT OR REPLACE INTO classes(project_id, dcc, class_name, module_name, source_path, base_class, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project.id, dcc, node.name, module, rel, bases[0] if bases else None, "{}"),
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signature = self._signature_from_node(node)
                parent = self._parent_class(tree, node)
                qualified = f"{module}.{parent + '.' if parent else ''}{node.name}"
                self.store.upsert_function(
                    project.id,
                    dcc,
                    function_name=node.name,
                    qualified_name=qualified,
                    source_path=rel,
                    class_name=parent,
                    signature=signature,
                    docstring=ast.get_docstring(node),
                    metadata={"async": isinstance(node, ast.AsyncFunctionDef)},
                )

    @staticmethod
    def _signature_from_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = [a.arg for a in node.args.args]
        if node.args.vararg:
            args.append("*" + node.args.vararg.arg)
        if node.args.kwarg:
            args.append("**" + node.args.kwarg.arg)
        return f"{node.name}({', '.join(args)})"

    @staticmethod
    def _parent_class(tree: ast.AST, func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and func in node.body:
                return node.name
        return None
