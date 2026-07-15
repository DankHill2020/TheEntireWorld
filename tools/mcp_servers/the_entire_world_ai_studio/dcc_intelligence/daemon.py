"""Daemon-facing service API for local DCC intelligence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .context_builder import ContextBuilder
from .scanner import ProjectScanner
from .store import IntelligenceStore, ProjectRef
from .adapters.unreal import register_unreal_capabilities


class DCCIntelligenceService:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.ai_root = self.workspace_root / ".ai_studio" / "intelligence"
        self.store = IntelligenceStore(self.ai_root / "dcc_local_intelligence.sqlite")
        self.scanner = ProjectScanner(self.store)
        self.context_builder = ContextBuilder(self.store)

    def close(self) -> None:
        self.store.close()

    def index_project(self, root_path: str | Path | None = None, dcc: str = "generic", name: str | None = None) -> dict[str, Any]:
        root = Path(root_path).resolve() if root_path else self.workspace_root
        project = self.scanner.scan_project(root, dcc=dcc, name=name)
        if dcc == "unreal":
            register_unreal_capabilities(self.store, project.id)
        return {"ok": True, "project": project.__dict__, "db_path": str(self.store.db_path)}

    def snapshot(self, project_id: int, dcc: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = self.store.add_snapshot(project_id, dcc, **snapshot)
        return {"ok": True, "snapshot_id": snapshot_id}

    def build_context(self, project_id: int, request: str, dcc: str | None = None) -> dict[str, Any]:
        row = self.store.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return {"ok": False, "error": f"Unknown project_id: {project_id}"}
        project = ProjectRef(id=row["id"], dcc=row["dcc"], name=row["name"], root_path=row["root_path"])
        packet = self.context_builder.build(project, request, dcc=dcc)
        return {"ok": True, "context": packet.__dict__, "prompt_text": packet.to_prompt_text()}

    def record_execution(self, project_id: int, dcc: str, request_text: str, **data: Any) -> dict[str, Any]:
        execution_id = self.store.add_execution(project_id, dcc, request_text=request_text, **data)
        return {"ok": True, "execution_id": execution_id}


def handle_json(service: DCCIntelligenceService, payload: str | dict[str, Any]) -> dict[str, Any]:
    """Simple JSON-RPC-ish entrypoint for UI/HTTP bridge integration."""
    data = json.loads(payload) if isinstance(payload, str) else payload
    command = data.get("command")
    if command == "index_project":
        return service.index_project(data.get("root_path"), dcc=data.get("dcc", "generic"), name=data.get("name"))
    if command == "snapshot":
        return service.snapshot(int(data["project_id"]), data["dcc"], data.get("snapshot", {}))
    if command == "build_context":
        return service.build_context(int(data["project_id"]), data["request"], dcc=data.get("dcc"))
    if command == "record_execution":
        return service.record_execution(int(data["project_id"]), data["dcc"], data["request_text"], **data.get("data", {}))
    return {"ok": False, "error": f"Unknown command: {command}"}
