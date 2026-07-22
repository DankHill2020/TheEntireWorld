from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sqlite3
import sys
import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Allow importing sibling packages when run from the knowledge/ directory
_TOOLS_ROOT = next(
    candidate for candidate in Path(__file__).resolve().parents if candidate.name.lower() == "tools"
)
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from tech_connector.models.constants import project_index_db_path

try:
    from tech_connector.project_analysis.capability_registry import register_from_symbol

    _CAP_REGISTRY_AVAILABLE = True
except ImportError:
    _CAP_REGISTRY_AVAILABLE = False


    def register_from_symbol(_sym):  # noqa: F811
        return None

KNOWLEDGE_ROOT = Path(__file__).resolve().parent
APP_ROOT = KNOWLEDGE_ROOT.parent


def detect_tools_root() -> Path:
    configured = os.environ.get("AI_STUDIO_TOOLS_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    for candidate in [APP_ROOT] + list(APP_ROOT.parents):
        if candidate.name.lower() == "tools":
            return candidate
    return APP_ROOT


TOOLS_ROOT = detect_tools_root()
DB_PATH = project_index_db_path()

DEFAULT_ROOTS = [
    APP_ROOT,
]

TEXT_EXTS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml",
    ".ini", ".cfg", ".bat", ".ps1", ".mel", ".cpp", ".h", ".hpp", ".cs",
    ".uproject", ".uplugin"
}

ASSET_EXTS = {
    ".uasset", ".umap", ".fbx", ".ma", ".mb", ".blend", ".spp", ".exr", ".tga", ".png"
}

# Unreal Blueprint / asset metadata patterns (text-scan of serialised exports)
_BLUEPRINT_CLASS_RE = re.compile(r'"BlueprintClass"\s*:\s*"([^"]+)"')
_BLUEPRINT_NODES_RE = re.compile(r'"NodeTitle"\s*:\s*"([^"]+)"')
_UASSET_ASSET_TYPE_RE = re.compile(r'"AssetClass"\s*:\s*"([^"]+)"')
_PLUGIN_NAME_RE = re.compile(r'"Name"\s*:\s*"([^"]+)"')
LOCK_PATH = DB_PATH.with_suffix(".build.lock")

SKIP_DIRS = {
    "__pycache__", ".git", ".svn", ".idea", ".vs",
    "Intermediate", "Saved", "DerivedDataCache", "Binaries",
    "Build", ".pytest_cache", "node_modules", ".ai_studio",
    ".codex",
    ".continue",
    ".agents"
}

MAX_FILE_CHARS = 350_000
CHUNK_SIZE = 4500
CHUNK_OVERLAP = 650


@dataclass
class PythonImport:
    import_name: str
    module: str
    name: str
    alias: str
    level: int
    kind: str
    lineno: int
    col_offset: int


@dataclass
class PythonCall:
    name: str
    lineno: int
    col_offset: int


@dataclass
class PythonSymbol:
    name: str
    qualname: str
    parent_qualname: str
    parent_kind: str
    kind: str
    signature: str
    docstring: str
    start_line: int
    end_line: int
    source: str
    decorators: list[str]
    calls: list[str]
    imports: list[str]
    import_records: list[PythonImport]
    call_sites: list[PythonCall]
    maya_cmds: list[str]
    unreal_refs: list[str]
    string_literals: list[str]

def acquire_build_lock():
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_build_lock():
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def connect_index_db() -> sqlite3.Connection:
    """Open the knowledge DB with settings that allow UI readers while indexing."""
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL is safer with WAL for a desktop tool and avoids extra lock pressure.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def close_index_db(conn: sqlite3.Connection | None) -> None:
    if conn is None:
        return
    try:
        conn.commit()
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass

def root_dirs(cli_roots: list[str] | None = None) -> list[Path]:
    """Resolve indexing roots.

    Priority:
    1. explicit CLI roots,
    2. AI_KNOWLEDGE_ROOTS env var,
    3. the Tech Connector project root.

    This intentionally defaults to the whole app root, not only the
    knowledge/ package, so project-wide searches and dependency graph analysis
    see the entire tool.
    """
    if cli_roots:
        roots = [Path(p.strip()) for p in cli_roots if p and p.strip()]
    else:
        env = os.environ.get("AI_KNOWLEDGE_ROOTS")
        roots = [Path(p.strip()) for p in env.split(";") if p.strip()] if env else DEFAULT_ROOTS
    resolved = []
    for root in roots:
        try:
            r = root.expanduser().resolve()
        except Exception:
            r = root.expanduser()
        if r.exists() and r not in resolved:
            resolved.append(r)
    return resolved


def should_skip(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return any(skip.lower() in parts for skip in SKIP_DIRS)


SOURCE_PROJECT = "project"
SOURCE_EXTERNAL_TOOLS = "external_tools"
SOURCE_THIRD_PARTY = "third_party"
SOURCE_PYTHON_STDLIB = "python_stdlib"
SOURCE_UNREAL_ENGINE = "unreal_engine"
SOURCE_MAYA = "maya"
SOURCE_DCC_APP = "dcc_app"
SOURCE_UNKNOWN = "unknown"


def make_writable(path: Path) -> bool:
    try:
        if os.name == "nt":
            os.chmod(path, 0o666)
        else:
            os.chmod(path, 0o664)
        return True
    except Exception:
        return False


def classify_source_scope(root: Path, path: Path) -> str:
    """Classify indexed files so runtime search can prefer first-party project code."""
    lowered = str(path).replace("/", "\\").lower()
    root_lower = str(root).replace("/", "\\").lower()

    if "program files\\epic games" in lowered or "\\engine\\source\\" in lowered or "\\engine\\plugins\\" in lowered:
        return SOURCE_UNREAL_ENGINE
    if "program files\\autodesk" in lowered or "maya202" in lowered or "maya20" in lowered:
        return SOURCE_MAYA
    if "site-packages" in lowered or "dist-packages" in lowered:
        return SOURCE_THIRD_PARTY
    if "python" in lowered and "\\lib\\" in lowered:
        return SOURCE_PYTHON_STDLIB
    if "program files" in lowered:
        return SOURCE_DCC_APP

    # External tools are the explicit external/third-party tool bucket.
    # Studio-owned DCC folders such as maya_tools remain project code when
    # they live under a configured project root.
    if "\\external_tools\\" in lowered:
        return SOURCE_EXTERNAL_TOOLS

    # If it came from one of the configured roots and was not recognized as installed/external, treat it as project code.
    if root_lower and lowered.startswith(root_lower.rstrip("\\") + "\\") or lowered == root_lower:
        return SOURCE_PROJECT
    return SOURCE_UNKNOWN


def iter_files(roots: list[Path] | None = None):
    for root in (roots or root_dirs()):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if should_skip(path):
                continue
            if path.suffix.lower() not in TEXT_EXTS and path.suffix.lower() not in ASSET_EXTS:
                continue
            yield root, path


def _root_for_path(path: Path, roots: list[Path]) -> Path:
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        resolved = path.expanduser()
    for root in roots:
        try:
            if resolved == root or resolved.is_relative_to(root):
                return root
        except Exception:
            try:
                if str(resolved).lower().startswith(str(root).lower().rstrip("\\/") + os.sep):
                    return root
            except Exception:
                pass
    return roots[0] if roots else resolved.parent


def stale_file_plan(conn: sqlite3.Connection, roots: list[Path]) -> tuple[list[tuple[Path, Path]], list[Path], dict[str, int]]:
    """Return changed/new files plus missing indexed files without parsing unchanged files."""
    cur = conn.cursor()
    indexed_rows = cur.execute(
        """
        SELECT root, path, rel_path, ext, size, mtime, sha1, source_scope
        FROM files
        ORDER BY path
        """
    ).fetchall()
    indexed_by_path = {str(row[1]): row for row in indexed_rows}
    indexed_norm = set()
    for row in indexed_rows:
        try:
            indexed_norm.add(str(Path(row[1]).expanduser().resolve()).lower())
        except Exception:
            indexed_norm.add(str(row[1]).lower())

    changed: list[tuple[Path, Path]] = []
    missing: list[Path] = []
    seen_changed: set[str] = set()

    for row in indexed_rows:
        path = Path(row[1])
        if not path.exists():
            missing.append(path)
            continue
        try:
            stat = path.stat()
            size_changed = int(row[4] or 0) != int(stat.st_size)
            mtime_changed = abs(float(stat.st_mtime) - float(row[5] or 0)) > 1.0
            metadata_changed = classify_source_scope(_root_for_path(path, roots), path) != (row[7] or SOURCE_PROJECT)
            bootstrap_incomplete = str(row[6] or "").startswith("bootstrap:")
            if size_changed or mtime_changed or metadata_changed or bootstrap_incomplete:
                root = Path(row[0]) if row[0] else _root_for_path(path, roots)
                key = str(path)
                if key not in seen_changed:
                    changed.append((root, path))
                    seen_changed.add(key)
        except Exception:
            root = Path(row[0]) if row[0] else _root_for_path(path, roots)
            key = str(path)
            if key not in seen_changed:
                changed.append((root, path))
                seen_changed.add(key)

    new_files: list[tuple[Path, Path]] = []
    for root, path in iter_files(roots):
        try:
            key = str(path.expanduser().resolve()).lower()
        except Exception:
            key = str(path).lower()
        if key not in indexed_norm:
            new_files.append((root, path))

    return changed + new_files, missing, {
        "indexed": len(indexed_rows),
        "changed": len(changed),
        "new": len(new_files),
        "missing": len(missing),
    }


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
    except Exception:
        return ""


def file_hash(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


def safe_unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def get_source_segment(lines: list[str], start: int, end: int) -> str:
    if start <= 0 or end <= 0:
        return ""
    return "\n".join(lines[start - 1:end])


def extract_import_records(tree: ast.AST) -> list[PythonImport]:
    imports: list[PythonImport] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(PythonImport(
                    import_name=alias.name,
                    module=alias.name,
                    name="",
                    alias=alias.asname or "",
                    level=0,
                    kind="import",
                    lineno=getattr(node, "lineno", 0),
                    col_offset=getattr(node, "col_offset", 0),
                ))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(PythonImport(
                    import_name=f"{mod}.{alias.name}" if mod else alias.name,
                    module=mod,
                    name=alias.name,
                    alias=alias.asname or "",
                    level=int(getattr(node, "level", 0) or 0),
                    kind="from",
                    lineno=getattr(node, "lineno", 0),
                    col_offset=getattr(node, "col_offset", 0),
                ))
    deduped: dict[tuple, PythonImport] = {}
    for item in imports:
        key = (
            item.import_name,
            item.module,
            item.name,
            item.alias,
            item.level,
            item.kind,
            item.lineno,
            item.col_offset,
        )
        deduped[key] = item
    return sorted(deduped.values(), key=lambda item: (item.lineno, item.col_offset, item.import_name))


def extract_imports(tree: ast.AST) -> list[str]:
    return sorted({item.import_name for item in extract_import_records(tree)})


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return call_name(node.func)
    return ""


def extract_call_sites(node: ast.AST) -> list[PythonCall]:
    calls: list[PythonCall] = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            name = call_name(n.func)
            if name:
                calls.append(PythonCall(
                    name=name,
                    lineno=getattr(n, "lineno", 0),
                    col_offset=getattr(n, "col_offset", 0),
                ))
    deduped: dict[tuple, PythonCall] = {}
    for item in calls:
        deduped[(item.name, item.lineno, item.col_offset)] = item
    return sorted(deduped.values(), key=lambda item: (item.lineno, item.col_offset, item.name))


def extract_calls(node: ast.AST) -> list[str]:
    return sorted({item.name for item in extract_call_sites(node)})


def extract_owned_call_sites(node: ast.AST, kind: str) -> list[PythonCall]:
    if kind != "class" or not isinstance(node, ast.ClassDef):
        return extract_call_sites(node)
    calls: list[PythonCall] = []
    for child in node.body:
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls.extend(extract_call_sites(child))
    deduped = {(item.name, item.lineno, item.col_offset): item for item in calls}
    return sorted(deduped.values(), key=lambda item: (item.lineno, item.col_offset, item.name))


def extract_string_literals(node: ast.AST) -> list[str]:
    strings = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            s = n.value.strip()
            if s and len(s) <= 200:
                strings.append(s)
    return sorted(set(strings))[:200]


def extract_signature(node: ast.AST) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return getattr(node, "name", "")

    parts = []
    args = node.args

    for arg in getattr(args, "posonlyargs", []):
        parts.append(arg.arg)
    for arg in args.args:
        parts.append(arg.arg)
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    for arg in args.kwonlyargs:
        parts.append(arg.arg)
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)

    return f"{node.name}({', '.join(parts)})"


def extract_python_symbols(text: str) -> list[PythonSymbol]:
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except Exception:
        return []

    file_import_records = extract_import_records(tree)
    file_imports = sorted({item.import_name for item in file_import_records})
    symbols = []

    class StackVisitor(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_ClassDef(self, node):
            self._add(node, "class")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node):
            self._add(node, "method" if self.stack else "function")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node):
            self._add(node, "method" if self.stack else "function")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def _add(self, node, kind):
            name = node.name
            qualname = ".".join(self.stack + [name]) if self.stack else name
            parent_qualname = ".".join(self.stack) if self.stack else ""
            parent_kind = "class" if parent_qualname and kind in {"method", "class"} else "module"
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", start)
            source = get_source_segment(lines, start, end)
            decorators = [safe_unparse(d) for d in getattr(node, "decorator_list", [])]
            call_sites = extract_owned_call_sites(node, kind)
            calls = sorted({item.name for item in call_sites})
            strings = extract_string_literals(node)
            maya_cmds = sorted({
                c for c in calls
                if c.startswith("cmds.") or c.startswith("maya.cmds.") or c.startswith("pm.")
            })
            unreal_refs = sorted({
                c for c in calls
                if c.startswith("unreal.") or "unreal" in c.lower()
            })
            signature = name if kind == "class" else extract_signature(node)
            symbols.append(PythonSymbol(
                name=name,
                qualname=qualname,
                parent_qualname=parent_qualname,
                parent_kind=parent_kind,
                kind=kind,
                signature=signature,
                docstring=ast.get_docstring(node) or "",
                start_line=start,
                end_line=end,
                source=source,
                decorators=[d for d in decorators if d],
                calls=calls,
                imports=file_imports,
                import_records=file_import_records,
                call_sites=call_sites,
                maya_cmds=maya_cmds,
                unreal_refs=unreal_refs,
                string_literals=strings,
            ))

    StackVisitor().visit(tree)

    module_call_sites: list[PythonCall] = []
    module_strings: list[str] = []
    module_start = 0
    module_end = 0
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        sites = extract_call_sites(node)
        if not sites:
            continue
        module_call_sites.extend(sites)
        module_strings.extend(extract_string_literals(node))
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", start)
        module_start = start if not module_start else min(module_start, start)
        module_end = max(module_end, end)

    if module_call_sites:
        module_calls = sorted({item.name for item in module_call_sites})
        module_source = get_source_segment(lines, module_start, module_end)
        symbols.append(PythonSymbol(
            name="__module__",
            qualname="__module__",
            parent_qualname="",
            parent_kind="module",
            kind="module",
            signature="__module__",
            docstring="",
            start_line=module_start or 1,
            end_line=module_end or module_start or 1,
            source=module_source,
            decorators=[],
            calls=module_calls,
            imports=file_imports,
            import_records=file_import_records,
            call_sites=module_call_sites,
            maya_cmds=sorted({
                c for c in module_calls
                if c.startswith("cmds.") or c.startswith("maya.cmds.") or c.startswith("pm.")
            }),
            unreal_refs=sorted({
                c for c in module_calls
                if c.startswith("unreal.") or "unreal" in c.lower()
            }),
            string_literals=sorted(set(module_strings))[:200],
        ))
    return symbols


# ---------------------------------------------------------------------------
# Unreal-specific metadata helpers
# ---------------------------------------------------------------------------

def index_unreal_asset(text: str, path: Path) -> dict:
    """Extract structured metadata from an Unreal asset via best-effort text scan."""
    result = {
        "asset_type": path.suffix.lstrip("."),
        "blueprint_class": "",
        "blueprint_nodes": [],
        "plugin_deps": [],
    }
    m = _UASSET_ASSET_TYPE_RE.search(text)
    if m:
        result["asset_type"] = m.group(1)
    bp = _BLUEPRINT_CLASS_RE.search(text)
    if bp:
        result["blueprint_class"] = bp.group(1)
    result["blueprint_nodes"] = _BLUEPRINT_NODES_RE.findall(text)[:50]
    return result


def index_plugin_deps(text: str, path: Path) -> list:
    """Extract plugin names from a .uproject or .uplugin file."""
    if path.suffix.lower() not in (".uproject", ".uplugin"):
        return []
    try:
        data = json.loads(text)
        plugins = data.get("Plugins", [])
        return [p.get("Name", "") for p in plugins if p.get("Enabled", True) and p.get("Name")]
    except Exception:
        return _PLUGIN_NAME_RE.findall(text)[:50]


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        root TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        rel_path TEXT NOT NULL,
        module TEXT,
        ext TEXT,
        size INTEGER,
        mtime REAL,
        sha1 TEXT,
        indexed_at TEXT,
        source_scope TEXT DEFAULT 'project'
    );

    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        text TEXT NOT NULL,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );

    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        qualname TEXT NOT NULL,
        parent_qualname TEXT,
        parent_kind TEXT,
        kind TEXT NOT NULL,
        signature TEXT,
        docstring TEXT,
        start_line INTEGER,
        end_line INTEGER,
        source TEXT,
        decorators_json TEXT,
        calls_json TEXT,
        imports_json TEXT,
        maya_cmds_json TEXT,
        unreal_refs_json TEXT,
        string_literals_json TEXT,
        searchable_text TEXT,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );

    CREATE TABLE IF NOT EXISTS symbol_calls (
        id INTEGER PRIMARY KEY,
        symbol_id INTEGER NOT NULL,
        call_name TEXT NOT NULL,
        call_lineno INTEGER,
        call_col INTEGER,
        FOREIGN KEY(symbol_id) REFERENCES symbols(id)
    );

    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL,
        import_name TEXT NOT NULL,
        module TEXT,
        name TEXT,
        alias TEXT,
        level INTEGER DEFAULT 0,
        kind TEXT,
        lineno INTEGER,
        col_offset INTEGER,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );

    CREATE TABLE IF NOT EXISTS file_dependencies (
        id INTEGER PRIMARY KEY,
        source_file_id INTEGER NOT NULL,
        target_file_id INTEGER,
        import_name TEXT NOT NULL,
        resolved_module TEXT,
        imported_name TEXT,
        source_path TEXT NOT NULL,
        target_path TEXT,
        source_module TEXT,
        target_module TEXT,
        source_scope TEXT,
        target_scope TEXT,
        used_symbol_count INTEGER DEFAULT 0,
        is_resolved INTEGER DEFAULT 0,
        resolution_note TEXT,
        FOREIGN KEY(source_file_id) REFERENCES files(id),
        FOREIGN KEY(target_file_id) REFERENCES files(id)
    );

    CREATE TABLE IF NOT EXISTS module_resolution_errors (
        id INTEGER PRIMARY KEY,
        source_file_id INTEGER NOT NULL,
        source_path TEXT NOT NULL,
        import_name TEXT NOT NULL,
        note TEXT,
        FOREIGN KEY(source_file_id) REFERENCES files(id)
    );

    -- Unreal asset metadata (one row per .uasset/.umap/.uproject)
    CREATE TABLE IF NOT EXISTS unreal_assets (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL UNIQUE,
        asset_type TEXT,
        blueprint_class TEXT,
        blueprint_nodes_json TEXT,
        plugin_deps_json TEXT,
        FOREIGN KEY(file_id) REFERENCES files(id)
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        text,
        path UNINDEXED,
        rel_path UNINDEXED,
        tokenize='unicode61'
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
        name,
        qualname,
        kind,
        signature,
        docstring,
        searchable_text,
        path UNINDEXED,
        rel_path UNINDEXED,
        parent_qualname UNINDEXED,
        tokenize='unicode61'
    );

    CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
    CREATE INDEX IF NOT EXISTS idx_files_rel_path ON files(rel_path);
    CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
    CREATE INDEX IF NOT EXISTS idx_symbols_qualname ON symbols(qualname);
    CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_qualname);
    CREATE INDEX IF NOT EXISTS idx_symbol_calls_call_name ON symbol_calls(call_name);
    CREATE INDEX IF NOT EXISTS idx_symbol_calls_lineno ON symbol_calls(call_lineno);
    CREATE INDEX IF NOT EXISTS idx_imports_import_name ON imports(import_name);
    CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module);
    CREATE INDEX IF NOT EXISTS idx_imports_name ON imports(name);
    CREATE INDEX IF NOT EXISTS idx_file_deps_source ON file_dependencies(source_file_id);
    CREATE INDEX IF NOT EXISTS idx_file_deps_target ON file_dependencies(target_file_id);
    CREATE INDEX IF NOT EXISTS idx_file_deps_import ON file_dependencies(import_name);
    CREATE INDEX IF NOT EXISTS idx_file_deps_resolved ON file_dependencies(is_resolved);
    CREATE INDEX IF NOT EXISTS idx_file_deps_used ON file_dependencies(used_symbol_count);
    CREATE INDEX IF NOT EXISTS idx_unreal_assets_type ON unreal_assets(asset_type);
    CREATE INDEX IF NOT EXISTS idx_unreal_assets_bp   ON unreal_assets(blueprint_class);
    """)

    # Backward-compatible migration for indexes created before source_scope existed.
    cur.execute("PRAGMA table_info(files)")
    file_columns = {row[1] for row in cur.fetchall()}
    if "source_scope" not in file_columns:
        cur.execute("ALTER TABLE files ADD COLUMN source_scope TEXT DEFAULT 'project'")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_source_scope ON files(source_scope)")

    cur.execute("PRAGMA table_info(symbols)")
    symbol_columns = {row[1] for row in cur.fetchall()}
    for col_name in ("parent_qualname", "parent_kind"):
        if col_name not in symbol_columns:
            cur.execute(f"ALTER TABLE symbols ADD COLUMN {col_name} TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_qualname)")

    cur.execute("PRAGMA table_info(imports)")
    import_columns = {row[1] for row in cur.fetchall()}
    for col_name, col_type in (
        ("module", "TEXT"),
        ("name", "TEXT"),
        ("alias", "TEXT"),
        ("level", "INTEGER DEFAULT 0"),
        ("kind", "TEXT"),
        ("lineno", "INTEGER"),
        ("col_offset", "INTEGER"),
    ):
        if col_name not in import_columns:
            cur.execute(f"ALTER TABLE imports ADD COLUMN {col_name} {col_type}")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_imports_module ON imports(module)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_imports_name ON imports(name)")

    cur.execute("PRAGMA table_info(symbol_calls)")
    call_columns = {row[1] for row in cur.fetchall()}
    for col_name in ("call_lineno", "call_col"):
        if col_name not in call_columns:
            cur.execute(f"ALTER TABLE symbol_calls ADD COLUMN {col_name} INTEGER")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_symbol_calls_lineno ON symbol_calls(call_lineno)")

    # Backward-compatible graph tables for dead-code / unused-file analysis.
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS file_dependencies (
        id INTEGER PRIMARY KEY,
        source_file_id INTEGER NOT NULL,
        target_file_id INTEGER,
        import_name TEXT NOT NULL,
        resolved_module TEXT,
        imported_name TEXT,
        source_path TEXT NOT NULL,
        target_path TEXT,
        source_module TEXT,
        target_module TEXT,
        source_scope TEXT,
        target_scope TEXT,
        used_symbol_count INTEGER DEFAULT 0,
        is_resolved INTEGER DEFAULT 0,
        resolution_note TEXT,
        FOREIGN KEY(source_file_id) REFERENCES files(id),
        FOREIGN KEY(target_file_id) REFERENCES files(id)
    );

    CREATE TABLE IF NOT EXISTS module_resolution_errors (
        id INTEGER PRIMARY KEY,
        source_file_id INTEGER NOT NULL,
        source_path TEXT NOT NULL,
        import_name TEXT NOT NULL,
        note TEXT,
        FOREIGN KEY(source_file_id) REFERENCES files(id)
    );

    CREATE INDEX IF NOT EXISTS idx_file_deps_source ON file_dependencies(source_file_id);
    CREATE INDEX IF NOT EXISTS idx_file_deps_target ON file_dependencies(target_file_id);
    CREATE INDEX IF NOT EXISTS idx_file_deps_import ON file_dependencies(import_name);
    CREATE INDEX IF NOT EXISTS idx_file_deps_resolved ON file_dependencies(is_resolved);
    CREATE INDEX IF NOT EXISTS idx_file_deps_used ON file_dependencies(used_symbol_count);
    """)
    conn.commit()


def clear_file(conn: sqlite3.Connection, path: Path):
    """
    Remove indexed source-of-truth rows for a changed file.

    FTS rows are intentionally NOT deleted here. The FTS tables are rebuilt
    from chunks/symbols at the end of the run. This avoids SQLite errors like:
        cannot DELETE from contentless fts5 table: chunks_fts
    """
    cur = conn.cursor()
    cur.execute("SELECT id FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()
    if not row:
        return

    file_id = row[0]
    cur.execute("DELETE FROM symbol_calls WHERE symbol_id IN (SELECT id FROM symbols WHERE file_id = ?)", (file_id,))
    cur.execute("DELETE FROM imports WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM file_dependencies WHERE source_file_id = ? OR target_file_id = ?", (file_id, file_id))
    cur.execute("DELETE FROM module_resolution_errors WHERE source_file_id = ?", (file_id,))
    cur.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()


def module_from_rel_path(rel_path: str, ext: str) -> str:
    if ext != ".py":
        return ""
    p = rel_path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".")


def index_file(conn: sqlite3.Connection, root: Path, path: Path, *, symbols_only: bool = False) -> bool:
    ext = path.suffix.lower()
    if ext in ASSET_EXTS:
        # Best-effort text scan of binary asset
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="replace")[:MAX_FILE_CHARS]
        except Exception:
            text = f"Asset file: {path.name}"
    else:
        text = read_text(path)
        if not text:
            return False

    try:
        rel = str(path.relative_to(root))
    except Exception:
        rel = str(path)

    stat = path.stat()
    sha = f"bootstrap:{stat.st_size}:{int(stat.st_mtime * 1000000)}" if symbols_only else file_hash(path)
    module = module_from_rel_path(rel, ext)
    source_scope = classify_source_scope(root, path)

    cur = conn.cursor()
    cur.execute("SELECT id, sha1, root, rel_path, module, source_scope FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()

    if row and row[1] == sha and row[2] == str(root) and row[3] == rel and (row[4] or "") == module and (row[5] or "project") == source_scope:
        if symbols_only or not _file_needs_rich_index(conn, int(row[0]), ext):
            return False

    clear_file(conn, path)

    cur.execute("""
        INSERT INTO files(root, path, rel_path, module, ext, size, mtime, sha1, indexed_at, source_scope)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(root), str(path), rel, module, ext,
        stat.st_size, stat.st_mtime, sha,
        datetime.now().isoformat(timespec="seconds"),
        source_scope
    ))

    file_id = cur.lastrowid

    if not symbols_only:
        for i, chunk in enumerate(chunk_text(text)):
            cur.execute(
                "INSERT INTO chunks(file_id, chunk_index, text) VALUES (?, ?, ?)",
                (file_id, i, chunk)
            )

    if ext == ".py":
        symbols = extract_python_symbols(text)

        file_import_records: list[PythonImport] = []
        for sym in symbols:
            file_import_records.extend(sym.import_records)
        if not file_import_records:
            try:
                file_import_records = extract_import_records(ast.parse(text))
            except Exception:
                file_import_records = []
        deduped_imports = {}
        for imp in file_import_records:
            deduped_imports[(
                imp.import_name,
                imp.module,
                imp.name,
                imp.alias,
                imp.level,
                imp.kind,
                imp.lineno,
                imp.col_offset,
            )] = imp
        file_import_records = sorted(deduped_imports.values(), key=lambda item: (item.lineno, item.col_offset, item.import_name))
        file_imports = sorted({imp.import_name for imp in file_import_records})
        for imp in file_import_records:
            cur.execute(
                """
                INSERT INTO imports(
                    file_id, import_name, module, name, alias, level, kind, lineno, col_offset
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    imp.import_name,
                    imp.module,
                    imp.name,
                    imp.alias,
                    imp.level,
                    imp.kind,
                    imp.lineno,
                    imp.col_offset,
                )
            )

        for sym in symbols:
            searchable = "\n".join([
                sym.name,
                sym.qualname,
                sym.parent_qualname,
                sym.parent_kind,
                sym.signature,
                sym.docstring,
                " ".join(sym.calls),
                " ".join(sym.imports),
                " ".join(sym.maya_cmds),
                " ".join(sym.unreal_refs),
                " ".join(sym.string_literals),
            ])

            cur.execute("""
                INSERT INTO symbols(
                    file_id, name, qualname, parent_qualname, parent_kind, kind, signature, docstring,
                    start_line, end_line, source,
                    decorators_json, calls_json, imports_json,
                    maya_cmds_json, unreal_refs_json, string_literals_json,
                    searchable_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                file_id, sym.name, sym.qualname, sym.parent_qualname, sym.parent_kind, sym.kind, sym.signature, sym.docstring,
                sym.start_line, sym.end_line, sym.source,
                json.dumps(sym.decorators),
                json.dumps(sym.calls),
                json.dumps(sym.imports),
                json.dumps(sym.maya_cmds),
                json.dumps(sym.unreal_refs),
                json.dumps(sym.string_literals),
                searchable,
            ))

            symbol_id = cur.lastrowid
            if not symbols_only:
                for call in sym.call_sites:
                    cur.execute(
                        "INSERT INTO symbol_calls(symbol_id, call_name, call_lineno, call_col) VALUES (?, ?, ?, ?)",
                        (symbol_id, call.name, call.lineno, call.col_offset)
                    )

            # Auto-populate capability registry
            if _CAP_REGISTRY_AVAILABLE and sym.kind != "module":
                try:
                    register_from_symbol({
                        "name": sym.name,
                        "kind": sym.kind,
                        "qualname": sym.qualname,
                        "parent_qualname": sym.parent_qualname,
                        "parent_kind": sym.parent_kind,
                        "file": str(path),
                        "start_line": sym.start_line,
                        "docstring": sym.docstring,
                        "signature": sym.signature,
                        "imports": sym.imports,
                        "calls": sym.calls,
                        "unreal_refs": sym.unreal_refs,
                    })
                except Exception:
                    pass  # Registry unavailable — silently skip

    # Unreal / DCC asset metadata
    if not symbols_only and ext in (".uasset", ".umap", ".uproject", ".uplugin"):
        meta = index_unreal_asset(text, path)
        meta["plugin_deps"] = index_plugin_deps(text, path)
        cur.execute(
            """
            INSERT OR REPLACE INTO unreal_assets(
                file_id, asset_type, blueprint_class,
                blueprint_nodes_json, plugin_deps_json
            ) VALUES (?,?,?,?,?)
            """,
            (
                file_id,
                meta["asset_type"],
                meta["blueprint_class"],
                json.dumps(meta["blueprint_nodes"]),
                json.dumps(meta["plugin_deps"]),
            ),
        )

    conn.commit()
    return True


def _file_needs_rich_index(conn: sqlite3.Connection, file_id: int, ext: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM chunks WHERE file_id = ? LIMIT 1", (file_id,))
    if cur.fetchone() is None:
        return True
    if ext == ".py":
        cur.execute("SELECT COUNT(*) FROM symbols WHERE file_id = ?", (file_id,))
        symbol_count = int((cur.fetchone() or [0])[0] or 0)
        if symbol_count:
            cur.execute(
                """
                SELECT 1
                FROM symbol_calls
                JOIN symbols ON symbols.id = symbol_calls.symbol_id
                WHERE symbols.file_id = ?
                LIMIT 1
                """,
                (file_id,),
            )
            # Files with symbols but no calls may be legitimately call-free; do
            # not use this alone to force endless reindexing.
    if ext in (".uasset", ".umap", ".uproject", ".uplugin"):
        cur.execute("SELECT 1 FROM unreal_assets WHERE file_id = ? LIMIT 1", (file_id,))
        if cur.fetchone() is None:
            return True
    return False


# ---------------------------------------------------------------------------
# Dependency graph / dead-code helpers
# ---------------------------------------------------------------------------

def _load_file_text_from_chunks(conn: sqlite3.Connection, file_id: int) -> str:
    cur = conn.cursor()
    cur.execute("SELECT text FROM chunks WHERE file_id = ? ORDER BY chunk_index ASC", (file_id,))
    return "".join(row[0] or "" for row in cur.fetchall())


def _body_without_import_lines(text: str) -> str:
    lines = []
    in_multiline_import = False
    paren_depth = 0
    for line in (text or "").splitlines():
        stripped = line.strip()
        if in_multiline_import:
            paren_depth += stripped.count("(") - stripped.count(")")
            if paren_depth <= 0 and not stripped.endswith("\\"):
                in_multiline_import = False
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            paren_depth = stripped.count("(") - stripped.count(")")
            if stripped.endswith("\\") or paren_depth > 0:
                in_multiline_import = True
            continue
        lines.append(line)
    return "\n".join(lines)


def _structured_import_name(
    source_module: str,
    import_name: str,
    module: str = "",
    name: str = "",
    level: int = 0,
) -> str:
    if level <= 0:
        return import_name
    package_parts = (source_module or "").split(".")[:-1]
    keep = max(0, len(package_parts) - (level - 1))
    base = package_parts[:keep]
    module_parts = [part for part in (module or "").split(".") if part]
    name_parts = [part for part in (name or "").split(".") if part]
    return ".".join(base + module_parts + name_parts)


def _resolve_import(import_name: str, module_to_file: dict[str, dict]) -> tuple[dict | None, str, str]:
    """Resolve an import string to the longest indexed module prefix.

    extract_imports() stores ImportFrom as module.name, so resolving the longest
    prefix lets `from tech_connector.services.foo import Bar` point to services.foo while
    preserving imported_name=Bar for usage checks.
    """
    parts = (import_name or "").split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in module_to_file:
            imported_name = ".".join(parts[i:])
            return module_to_file[candidate], candidate, imported_name
    return None, "", ""


def _estimate_import_usage_count(
    body_text: str,
    import_name: str,
    resolved_module: str,
    imported_name: str,
    alias: str = "",
) -> int:
    names = []
    if alias:
        names.append(alias)
    if imported_name:
        names.append(imported_name.split(".")[-1])
    if resolved_module:
        names.append(resolved_module.split(".")[-1])
    if import_name:
        names.append(import_name.split(".")[-1])
    seen = []
    for name in names:
        if name and name.isidentifier() and name not in seen:
            seen.append(name)
    if not seen:
        return 0
    total = 0
    for name in seen:
        total += len(re.findall(rf"\b{re.escape(name)}\b", body_text or ""))
    return total


def rebuild_dependency_graph(conn: sqlite3.Connection):
    """Rebuild project import/dependency graph from indexed files/imports.

    This is intentionally conservative. It resolves imports to indexed modules
    when possible and records a heuristic usage count by checking whether the
    imported module/symbol appears outside import lines.
    """
    cur = conn.cursor()
    print("")
    print("Rebuilding dependency graph...")

    cur.execute("DELETE FROM file_dependencies")
    cur.execute("DELETE FROM module_resolution_errors")

    files = cur.execute(
        "SELECT id, path, rel_path, module, ext, source_scope FROM files WHERE ext = '.py'"
    ).fetchall()
    module_to_file = {}
    for row in files:
        module = row[3] or ""
        if module and module not in module_to_file:
            module_to_file[module] = {
                "id": row[0],
                "path": row[1],
                "rel_path": row[2],
                "module": row[3],
                "ext": row[4],
                "source_scope": row[5],
            }

    rebuilt = 0
    unresolved = 0
    for file_id, path, rel_path, module, ext, source_scope in files:
        imports = cur.execute(
            """
            SELECT import_name, module, name, alias, level, kind
            FROM imports
            WHERE file_id = ?
            ORDER BY lineno, col_offset, import_name
            """,
            (file_id,),
        ).fetchall()
        if not imports:
            continue
        body = _body_without_import_lines(_load_file_text_from_chunks(conn, file_id))
        for import_row in imports:
            import_name = import_row[0] or ""
            import_module = import_row[1] or ""
            import_symbol = import_row[2] or ""
            import_alias = import_row[3] or ""
            import_level = int(import_row[4] or 0)
            resolved_import_name = _structured_import_name(
                module,
                import_name,
                module=import_module,
                name=import_symbol,
                level=import_level,
            )
            target, resolved_module, imported_name = _resolve_import(resolved_import_name or import_name, module_to_file)
            if target and target["id"] != file_id:
                usage_count = _estimate_import_usage_count(
                    body,
                    import_name,
                    resolved_module,
                    imported_name,
                    alias=import_alias,
                )
                cur.execute(
                    """
                    INSERT INTO file_dependencies(
                        source_file_id, target_file_id, import_name, resolved_module,
                        imported_name, source_path, target_path, source_module,
                        target_module, source_scope, target_scope, used_symbol_count,
                        is_resolved, resolution_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        file_id,
                        target["id"],
                        import_name,
                        resolved_module,
                        imported_name,
                        path,
                        target["path"],
                        module,
                        target["module"],
                        source_scope,
                        target["source_scope"],
                        usage_count,
                        "resolved by longest module prefix",
                    ),
                )
                rebuilt += 1
            else:
                note = "self import or unresolved"
                cur.execute(
                    """
                    INSERT INTO module_resolution_errors(source_file_id, source_path, import_name, note)
                    VALUES (?, ?, ?, ?)
                    """,
                    (file_id, path, import_name, note),
                )
                unresolved += 1

    conn.commit()
    print(f"Dependency graph complete. Resolved imports: {rebuilt}. Unresolved/self imports: {unresolved}.")


def rebuild_fts_tables(conn: sqlite3.Connection):
    """
    Rebuild FTS tables from source-of-truth tables.

    This is deterministic and avoids incremental DELETE problems with FTS5 tables.
    """
    cur = conn.cursor()

    print("")
    print("Rebuilding FTS tables...")

    cur.executescript("""
    DROP TABLE IF EXISTS chunks_fts;
    DROP TABLE IF EXISTS symbols_fts;

    CREATE VIRTUAL TABLE chunks_fts USING fts5(
        text,
        path UNINDEXED,
        rel_path UNINDEXED,
        tokenize='unicode61'
    );

    CREATE VIRTUAL TABLE symbols_fts USING fts5(
        name,
        qualname,
        kind,
        signature,
        docstring,
        searchable_text,
        path UNINDEXED,
        rel_path UNINDEXED,
        parent_qualname UNINDEXED,
        tokenize='unicode61'
    );
    """)

    cur.execute("""
        INSERT INTO chunks_fts(rowid, text, path, rel_path)
        SELECT chunks.id, chunks.text, files.path, files.rel_path
        FROM chunks
        JOIN files ON files.id = chunks.file_id
    """)

    cur.execute("""
        INSERT INTO symbols_fts(
            rowid, name, qualname, kind, signature,
            docstring, searchable_text, path, rel_path, parent_qualname
        )
        SELECT
            symbols.id,
            symbols.name,
            symbols.qualname,
            symbols.kind,
            symbols.signature,
            symbols.docstring,
            symbols.searchable_text,
            files.path,
            files.rel_path,
            symbols.parent_qualname
        FROM symbols
        JOIN files ON files.id = symbols.file_id
    """)

    conn.commit()
    print("FTS rebuild complete.")


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Build the Tech Connector knowledge index.")
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help="Root directory to index. Can be provided multiple times. Defaults to the Tech Connector app root.",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=None,
        help="Update one exact changed file without scanning project roots. Can be repeated.",
    )
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="Build files/symbols/FTS only. Skip dependency graph for a faster foreground index.",
    )
    parser.add_argument(
        "--graph-only",
        action="store_true",
        help="Only rebuild the dependency graph from the existing files/symbols/imports tables.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Nuclear option: scan every supported file. Default indexing only processes stale/new files.",
    )
    parser.add_argument(
        "--stale-only",
        action="store_true",
        help="Process only changed/new files and remove missing files. This is the default unless --full is set.",
    )
    parser.add_argument(
        "--no-fts",
        action="store_true",
        help="Skip FTS rebuild. Useful when running graph-only in the background.",
    )
    parser.add_argument(
        "--symbols-only",
        action="store_true",
        help="Bootstrap mode: index file metadata and Python symbols/imports, but skip chunks, FTS, assets, calls, and graph.",
    )
    return parser.parse_args(argv)


def print_summary(conn: sqlite3.Connection, scanned: int = 0, updated: int = 0):
    cur = conn.cursor()

    def count(table: str) -> int:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]
        except Exception:
            return 0

    print("")
    print("Done.")
    print(f"Scanned files: {scanned}")
    print(f"Updated files: {updated}")
    print(f"Indexed files: {count('files')}")
    print(f"Chunks: {count('chunks')}")
    print(f"Symbols: {count('symbols')}")
    print(f"Calls: {count('symbol_calls')}")
    print(f"Imports: {count('imports')}")
    print(f"File dependencies: {count('file_dependencies')}")


def main(argv: list[str] | None = None):
    global DB_PATH, LOCK_PATH

    args = parse_args(argv)
    roots = root_dirs(args.root)
    owner_root = roots[0] if roots else None
    DB_PATH = project_index_db_path(owner_root)
    LOCK_PATH = DB_PATH.with_suffix(".build.lock")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not acquire_build_lock():
        print(f"[ERROR] Knowledge index build already running: {LOCK_PATH}")
        sys.exit(2)

    conn = None
    total = 0
    updated = 0

    try:
        conn = connect_index_db()
        init_db(conn)

        print(f"Index DB: {DB_PATH}")
        print("Roots:")
        for r in roots:
            print(f"  - {r}")

        if args.graph_only:
            print("")
            print("Graph-only mode: using existing indexed files/symbols/imports.")
            rebuild_dependency_graph(conn)
            if not args.no_fts:
                rebuild_fts_tables(conn)
            else:
                print("")
                print("Skipping FTS rebuild (--no-fts).")
            print_summary(conn, total, updated)
            return

        removed = 0
        if args.file:
            file_plan = []
            missing_paths = []
            for value in dict.fromkeys(args.file):
                path = Path(value).expanduser().resolve()
                root = next(
                    (candidate for candidate in roots if _path_is_within(path, candidate)),
                    path.parent,
                )
                if path.is_file() and path.suffix.lower() in (TEXT_EXTS | ASSET_EXTS):
                    file_plan.append((root, path))
                else:
                    missing_paths.append(path)
            print("")
            print("Index mode: exact changed files (no project scan).")
            print(f"Changed files queued: {len(file_plan)}")
            print(f"Missing files queued: {len(missing_paths)}")
            for missing_path in missing_paths:
                try:
                    clear_file(conn, missing_path)
                    removed += 1
                except Exception as exc:
                    print(f"[ERROR] {missing_path}: could not remove stale index rows: {exc}")
        elif args.full:
            file_plan = list(iter_files(roots))
            print("")
            print("Index mode: full scan (--full).")
        else:
            file_plan, missing_paths, stale_counts = stale_file_plan(conn, roots)
            print("")
            print("Index mode: stale-only (default). Use --full for a full project scan.")
            print(f"Indexed files checked: {stale_counts.get('indexed', 0)}")
            print(f"Changed files: {stale_counts.get('changed', 0)}")
            print(f"New files: {stale_counts.get('new', 0)}")
            print(f"Missing files: {stale_counts.get('missing', 0)}")
            for missing_path in missing_paths:
                try:
                    clear_file(conn, missing_path)
                    removed += 1
                except Exception as exc:
                    print(f"[ERROR] {missing_path}: could not remove stale index rows: {exc}")

        for root, path in file_plan:
            total += 1
            try:
                if index_file(conn, root, path, symbols_only=bool(args.symbols_only)):
                    updated += 1
                    if updated % 25 == 0:
                        print(f"Indexed/updated {updated} files...")
            except sqlite3.OperationalError as e:
                # This is a database contention issue, not a source-file writability issue.
                # The connection has a busy_timeout, so if we still get here, skip the file
                # and let the user see the exact failing path without mutating source perms.
                print(f"[ERROR] {path}: {e}")
                continue
            except PermissionError as e:
                print(f"[ERROR] {path}: permission denied while reading/indexing: {e}")
                continue
            except Exception as e:
                print(f"[ERROR] {path}: {e}")
                continue

        changed_index = bool(updated or removed or args.full)
        if args.symbols_only:
            print("")
            print("Skipping dependency graph: symbols-only bootstrap mode.")
        elif not args.no_graph and changed_index:
            rebuild_dependency_graph(conn)
        elif not args.no_graph:
            print("")
            print("Skipping dependency graph: no stale indexed files changed.")
        else:
            print("")
            print("Skipping dependency graph (--no-graph).")

        if not args.no_fts and changed_index:
            rebuild_fts_tables(conn)
        elif not args.no_fts:
            print("")
            print("Skipping FTS rebuild: no stale indexed files changed.")
        else:
            print("")
            print("Skipping FTS rebuild (--no-fts).")

        print_summary(conn, total, updated)
    finally:
        close_index_db(conn)
        release_build_lock()

if __name__ == "__main__":
    main()
