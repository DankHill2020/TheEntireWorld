"""SQLite schema for the reusable DCC local intelligence layer."""
from __future__ import annotations

SCHEMA_VERSION = 4

DDL = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        description TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dcc TEXT NOT NULL,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        asset_path TEXT NOT NULL,
        asset_name TEXT NOT NULL,
        asset_type TEXT,
        package_path TEXT,
        class_name TEXT,
        modified_at REAL,
        size_bytes INTEGER,
        content_hash TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, asset_path),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        class_name TEXT NOT NULL,
        module_name TEXT,
        source_path TEXT,
        base_class TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(project_id, class_name, source_path),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS functions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        function_name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        source_path TEXT,
        class_name TEXT,
        signature TEXT,
        docstring TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(project_id, qualified_name, source_path),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS capabilities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        entrypoint TEXT,
        source_path TEXT,
        risk_level TEXT NOT NULL DEFAULT 'low',
        input_schema_json TEXT NOT NULL DEFAULT '{}',
        output_schema_json TEXT NOT NULL DEFAULT '{}',
        tags_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(project_id, dcc, name),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        source_ref TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        relation TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(project_id, source_kind, source_ref, target_kind, target_ref, relation),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS python_api (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        dcc TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        object_type TEXT NOT NULL,
        signature TEXT,
        docstring TEXT,
        source TEXT,
        tags_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(project_id, dcc, qualified_name),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS python_api_fts USING fts5(
        qualified_name,
        object_type,
        signature,
        docstring,
        content='python_api',
        content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS python_api_fts_vocab USING fts5vocab(
        python_api_fts,
        'row'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS python_api_fts_insert AFTER INSERT ON python_api BEGIN
        INSERT INTO python_api_fts(rowid, qualified_name, object_type, signature, docstring)
        VALUES (new.id, new.qualified_name, new.object_type, new.signature, new.docstring);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS python_api_fts_delete AFTER DELETE ON python_api BEGIN
        INSERT INTO python_api_fts(python_api_fts, rowid, qualified_name, object_type, signature, docstring)
        VALUES ('delete', old.id, old.qualified_name, old.object_type, old.signature, old.docstring);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS python_api_fts_update AFTER UPDATE ON python_api BEGIN
        INSERT INTO python_api_fts(python_api_fts, rowid, qualified_name, object_type, signature, docstring)
        VALUES ('delete', old.id, old.qualified_name, old.object_type, old.signature, old.docstring);
        INSERT INTO python_api_fts(rowid, qualified_name, object_type, signature, docstring)
        VALUES (new.id, new.qualified_name, new.object_type, new.signature, new.docstring);
    END
    """,
    """
    CREATE TABLE IF NOT EXISTS symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        symbol_key TEXT NOT NULL,
        symbol_key_norm TEXT NOT NULL,
        symbol_kind TEXT NOT NULL,
        display_name TEXT,
        qualified_name TEXT,
        source_ref TEXT,
        summary TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, dcc, symbol_kind, symbol_key_norm, source_ref),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS editor_state_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        snapshot_kind TEXT NOT NULL,
        selected_json TEXT NOT NULL DEFAULT '[]',
        open_document TEXT,
        active_level TEXT,
        loaded_assets_json TEXT NOT NULL DEFAULT '[]',
        state_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        request_text TEXT NOT NULL,
        action_name TEXT,
        target_ref TEXT,
        status TEXT NOT NULL,
        risk_level TEXT NOT NULL DEFAULT 'unknown',
        summary TEXT,
        result_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        source_kind TEXT NOT NULL,
        source_ref TEXT NOT NULL,
        model TEXT NOT NULL,
        text TEXT NOT NULL,
        vector_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, source_kind, source_ref, model),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        entity_key TEXT NOT NULL,
        entity_kind TEXT NOT NULL,
        display_name TEXT,
        path TEXT,
        class_name TEXT,
        parent_key TEXT,
        fingerprint TEXT,
        confidence REAL NOT NULL DEFAULT 1.0,
        source TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, dcc, entity_key),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        source_key TEXT NOT NULL,
        relation TEXT NOT NULL,
        target_key TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 1.0,
        source TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, dcc, source_key, relation, target_key),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_index_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        run_kind TEXT NOT NULL DEFAULT 'full',
        status TEXT NOT NULL,
        coverage_json TEXT NOT NULL DEFAULT '{}',
        errors_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_exclusions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        entity_path TEXT NOT NULL,
        reason TEXT NOT NULL,
        source TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        excluded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id, dcc, entity_path),
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runtime_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        dcc TEXT NOT NULL,
        scenario_key TEXT NOT NULL,
        subject_key TEXT,
        status TEXT NOT NULL,
        assertions_json TEXT NOT NULL DEFAULT '{}',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_assets_project_type ON assets(project_id, asset_type)",
    "CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(asset_name)",
    "CREATE INDEX IF NOT EXISTS idx_functions_name ON functions(function_name)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_key ON symbols(project_id, dcc, symbol_key_norm)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_kind_key ON symbols(project_id, dcc, symbol_kind, symbol_key_norm)",
    "CREATE INDEX IF NOT EXISTS idx_symbols_display ON symbols(display_name)",
    "CREATE INDEX IF NOT EXISTS idx_python_api_project_name ON python_api(project_id, dcc, qualified_name)",
    "CREATE INDEX IF NOT EXISTS idx_python_api_kind ON python_api(project_id, dcc, object_type)",
    "CREATE INDEX IF NOT EXISTS idx_capabilities_tags ON capabilities(tags_json)",
    "CREATE INDEX IF NOT EXISTS idx_dependencies_source ON dependencies(project_id, source_kind, source_ref)",
    "CREATE INDEX IF NOT EXISTS idx_dependencies_target ON dependencies(project_id, target_kind, target_ref)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_project_created ON editor_state_snapshots(project_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_execution_project_created ON execution_history(project_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_semantic_entities_lookup ON semantic_entities(project_id, dcc, entity_kind, entity_key)",
    "CREATE INDEX IF NOT EXISTS idx_semantic_entities_path ON semantic_entities(project_id, dcc, path)",
    "CREATE INDEX IF NOT EXISTS idx_semantic_relations_source ON semantic_relations(project_id, dcc, source_key)",
    "CREATE INDEX IF NOT EXISTS idx_semantic_relations_target ON semantic_relations(project_id, dcc, target_key)",
    "CREATE INDEX IF NOT EXISTS idx_semantic_runs_latest ON semantic_index_runs(project_id, dcc, id)",
    "CREATE INDEX IF NOT EXISTS idx_runtime_observations_scenario ON runtime_observations(project_id, dcc, scenario_key, id)",
]
