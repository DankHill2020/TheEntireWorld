# capability_registry.py
"""Capability Registry for the Tech Connector project analysis pipeline.

Every indexed function/tool becomes a structured capability entry in SQLite.
This powers the workflow composer and model router context injection.
"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).with_name("project_analysis.db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    app TEXT,
    inputs_json TEXT,
    outputs_json TEXT,
    requires_json TEXT,
    risk TEXT DEFAULT 'low',
    source_file TEXT,
    lineno INTEGER,
    docstring TEXT,
    signature TEXT,
    tags_json TEXT,
    unreal_calls_json TEXT,
    local_calls_json TEXT,
    operation_keys_json TEXT,
    UNIQUE(name, source_file)
);

CREATE INDEX IF NOT EXISTS idx_cap_name ON capabilities(name);
CREATE INDEX IF NOT EXISTS idx_cap_app  ON capabilities(app);
"""

# Map common import prefixes → DCC application label
_APP_HINTS: Dict[str, str] = {
    "unreal":          "Unreal",
    "maya":            "Maya",
    "cmds":            "Maya",
    "pymel":           "Maya",
    "bpy":             "Blender",
    "motionbuilder":   "MotionBuilder",
    "FBSDKPython":     "MotionBuilder",
    "substance":       "Substance",
    "hou":             "Houdini",
    "unity":           "Unity",
}

# Unreal operations that count as risky mutations
_HIGH_RISK_KEYWORDS = {
    "delete", "remove", "destroy", "rename", "move", "replace",
    "import", "export", "save", "compile", "apply",
}
_MED_RISK_KEYWORDS = {
    "create", "add", "build", "generate", "set", "update", "modify",
}


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.executescript(_SCHEMA)

    # CREATE TABLE IF NOT EXISTS does not add columns to an existing registry.
    # Apply lightweight additive migrations so old project_analysis.db files are
    # upgraded without requiring the user to delete or rebuild them first.
    existing = {row[1] for row in c.execute("PRAGMA table_info(capabilities)")}
    migrations = {
        "unreal_calls_json": "TEXT",
        "local_calls_json": "TEXT",
        "operation_keys_json": "TEXT",
    }
    for column, sql_type in migrations.items():
        if column not in existing:
            c.execute(f"ALTER TABLE capabilities ADD COLUMN {column} {sql_type}")
    c.commit()
    return c


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def _infer_app(imports: List[str], calls: List[str]) -> str:
    """Guess which DCC application a symbol targets based on imports/calls."""
    for token in imports + calls:
        t = token.lower()
        for hint, app in _APP_HINTS.items():
            if hint.lower() in t:
                return app
    return "General"


def _infer_risk(name: str, docstring: str) -> str:
    text = (name + " " + docstring).lower()
    if any(k in text for k in _HIGH_RISK_KEYWORDS):
        return "high"
    if any(k in text for k in _MED_RISK_KEYWORDS):
        return "medium"
    return "low"


def _infer_tags(imports: List[str], calls: List[str], unreal_refs: List[str]) -> List[str]:
    tags: List[str] = []
    combined = " ".join(imports + calls + unreal_refs).lower()
    # Unreal subsystem tags
    for keyword, tag in [
        ("blueprint",          "Blueprint"),
        ("control_rig",        "ControlRig"),
        ("motion_matching",    "MotionMatching"),
        ("animation_blueprint","AnimationBlueprint"),
        ("skeletal_mesh",      "SkeletalMesh"),
        ("gameplay",           "GameplayFramework"),
        ("asset_import",       "AssetImport"),
        ("level",              "LevelEdit"),
        ("cmds",               "MayaCmds"),
        ("pymel",              "PyMEL"),
        ("bpy",                "BlenderPython"),
    ]:
        if keyword in combined:
            tags.append(tag)
    return tags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_capability(cap: Dict[str, Any]) -> int:
    """Upsert a capability into the registry. Returns the row id.

    Minimum required keys: `name`, `source_file`.
    Optional keys include structured inputs/outputs plus exact Unreal API calls,
    local calls, and runtime operation keys.
    """
    conn = _conn()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO capabilities(
                name, app, inputs_json, outputs_json, requires_json,
                risk, source_file, lineno, docstring, signature, tags_json,
                unreal_calls_json, local_calls_json, operation_keys_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name, source_file) DO UPDATE SET
                app          = excluded.app,
                inputs_json  = excluded.inputs_json,
                outputs_json = excluded.outputs_json,
                requires_json= excluded.requires_json,
                risk         = excluded.risk,
                lineno       = excluded.lineno,
                docstring    = excluded.docstring,
                signature    = excluded.signature,
                tags_json    = excluded.tags_json,
                unreal_calls_json = excluded.unreal_calls_json,
                local_calls_json = excluded.local_calls_json,
                operation_keys_json = excluded.operation_keys_json
            """,
            (
                cap.get("name", ""),
                cap.get("app", "General"),
                json.dumps(cap.get("inputs", [])),
                json.dumps(cap.get("outputs", [])),
                json.dumps(cap.get("requires", [])),
                cap.get("risk", "low"),
                cap.get("source_file", ""),
                cap.get("lineno"),
                cap.get("docstring", ""),
                cap.get("signature", ""),
                json.dumps(cap.get("tags", [])),
                json.dumps(cap.get("unreal_calls", [])),
                json.dumps(cap.get("local_calls", [])),
                json.dumps(cap.get("operation_keys", [])),
            ),
        )
        row_id = cur.lastrowid
    conn.close()
    return row_id


def register_from_symbol(sym: Dict[str, Any]) -> Optional[int]:
    """Build a capability from an indexed Python symbol dict and register it.

    Accepts the dict produced by `build_knowledge_index_v2.extract_python_symbols()`
    or the simpler dicts from `project_analysis.ast_parser`.
    """
    name = sym.get("name", "")
    if not name or sym.get("kind", sym.get("type", "")) not in (
        "function", "method", "class"
    ):
        return None

    imports = list(sym.get("imports", []) or [])
    calls = list(sym.get("calls", []) or [])
    unreal = list(sym.get("unreal_refs", []) or [])
    unreal_calls = sorted({
        str(call) for call in [*calls, *unreal]
        if str(call).lower().startswith("unreal.")
    })
    local_calls = sorted({
        str(call) for call in calls
        if call and not str(call).lower().startswith("unreal.")
    })
    operation_keys = list(sym.get("operation_keys", []) or [])

    app  = _infer_app(imports, [*calls, *unreal_calls])
    risk = _infer_risk(name, sym.get("docstring", ""))
    tags = _infer_tags(imports, calls, unreal)

    qualified_name = str(sym.get("qualname") or name)
    if qualified_name != name:
        # Remove the pre-v2 short-name row as each source symbol is reindexed.
        # This migrates safely without guessing an owner for untouched rows.
        conn = _conn()
        with conn:
            conn.execute(
                "DELETE FROM capabilities WHERE name = ? AND source_file = ?",
                (name, str(sym.get("file") or "")),
            )
        conn.close()
    return register_capability({
        # Qualified names prevent methods with the same short name in separate
        # classes in one source file from overwriting each other.
        "name":        qualified_name,
        "app":         app,
        "inputs":      sym.get("params", []),
        "outputs":     sym.get("outputs", sym.get("returns", [])),
        "requires":    [imp for imp in imports if any(h in imp.lower() for h in _APP_HINTS)],
        "risk":        risk,
        "source_file": sym.get("file", ""),
        "lineno":      sym.get("start_line", sym.get("lineno")),
        "docstring":   sym.get("docstring", ""),
        "signature":   sym.get("signature", name),
        "tags":        tags,
        "unreal_calls": unreal_calls,
        "local_calls": local_calls,
        "operation_keys": operation_keys,
    })


def find_capabilities(
    query: str,
    app: Optional[str] = None,
    tag: Optional[str] = None,
    max_results: int = 20,
) -> List[Dict[str, Any]]:
    """Search capabilities using contextual terms and optional host filters.

    Optionally filter by app or tag.
    """
    conn = _conn()
    broad_terms = {
        "a", "an", "and", "api", "as", "at", "be", "by", "class", "code",
        "for", "from", "function", "in", "is", "it", "method", "of", "on",
        "or", "the", "this", "to", "use", "using", "via", "with",
    }
    query_terms = list(dict.fromkeys(
        token.casefold()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", query or "")
        if token.casefold() not in broad_terms
    ))[:12]
    conditions: List[str] = []
    params: List[Any] = []
    if query_terms:
        term_conditions = []
        for term in query_terms:
            term_conditions.append(
                "(name LIKE ? OR docstring LIKE ? OR signature LIKE ? "
                "OR tags_json LIKE ? OR operation_keys_json LIKE ?)"
            )
            wildcard = f"%{term}%"
            params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])
        conditions.append(f"({' OR '.join(term_conditions)})")

    if app:
        conditions.append("app = ?")
        params.append(app)
    if tag:
        conditions.append("tags_json LIKE ?")
        params.append(f"%{tag}%")

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    candidate_limit = max(max_results * 8, max_results)
    sql = (
        "SELECT name, app, inputs_json, outputs_json, requires_json, "
        "risk, source_file, lineno, docstring, signature, tags_json, "
        "unreal_calls_json, local_calls_json, operation_keys_json "
        f"FROM capabilities{where_clause} "
        f"LIMIT {candidate_limit}"
    )
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    keys = [
        "name", "app", "inputs", "outputs", "requires", "risk",
        "source_file", "lineno", "docstring", "signature", "tags",
        "unreal_calls", "local_calls", "operation_keys",
    ]
    result = []
    for row in rows:
        d = dict(zip(keys, row))
        for k in (
            "inputs", "outputs", "requires", "tags",
            "unreal_calls", "local_calls", "operation_keys",
        ):
            try:
                d[k] = json.loads(d[k] or "[]")
            except Exception:
                d[k] = []
        haystack = " ".join(
            str(d.get(field) or "")
            for field in (
                "name", "docstring", "signature", "tags",
                "operation_keys", "local_calls", "unreal_calls",
            )
        ).casefold()
        name_text = str(d.get("name") or "").casefold()
        d["_capability_score"] = (
            sum(8 for term in query_terms if term in name_text)
            + sum(2 for term in query_terms if term in haystack)
            + (20 if query and query.casefold() in haystack else 0)
        )
        result.append(d)
    result.sort(key=lambda item: (
        -int(item.pop("_capability_score", 0)),
        str(item.get("name") or "").casefold(),
    ))
    return result[:max_results]


def compose_workflow(steps: List[str]) -> Dict[str, Any]:
    """Given a list of capability names, produce an ordered execution plan.

    Returns a dict with:
    - `steps`: ordered list of resolved capability dicts
    - `missing`: names that could not be found
    - `risk`: highest risk level across all steps
    """
    resolved = []
    missing  = []
    highest_risk = "low"
    risk_order = {"low": 0, "medium": 1, "high": 2}

    for name in steps:
        matches = find_capabilities(name, max_results=1)
        if matches:
            cap = matches[0]
            resolved.append(cap)
            if risk_order.get(cap["risk"], 0) > risk_order.get(highest_risk, 0):
                highest_risk = cap["risk"]
        else:
            missing.append(name)

    return {
        "steps":   resolved,
        "missing": missing,
        "risk":    highest_risk,
    }


if __name__ == "__main__":
    # Quick smoke test
    print("Capability registry ready. DB:", DB_PATH)
    print("Total capabilities:", sqlite3.connect(str(DB_PATH)).execute("SELECT COUNT(*) FROM capabilities").fetchone()[0])
