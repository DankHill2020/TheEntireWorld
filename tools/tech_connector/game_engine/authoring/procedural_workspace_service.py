from __future__ import annotations

"""Portable retained state for the Tech Connector procedural workspace."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from tech_connector.game_engine.authoring.procedural_generation_service import ProceduralGraph
from tech_connector.game_engine.authoring.procedural_task_graph_service import ProceduralTaskGraph


PROCEDURAL_WORKSPACE_SCHEMA = "tech_connector.procedural_workspace.v1"


@dataclass
class ProceduralWorkspaceState:
    graphs: dict[str, ProceduralGraph] = field(default_factory=dict)
    task_graphs: dict[str, ProceduralTaskGraph] = field(default_factory=dict)
    active_graph_id: str = ""
    active_task_graph_id: str = ""
    scene_metadata: dict[str, Any] = field(default_factory=lambda: {"metadata": {}})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROCEDURAL_WORKSPACE_SCHEMA,
            "graphs": {str(key): value.to_dict() for key, value in self.graphs.items()},
            "task_graphs": {str(key): value.to_dict() for key, value in self.task_graphs.items()},
            "active_graph_id": str(self.active_graph_id),
            "active_task_graph_id": str(self.active_task_graph_id),
            "scene_metadata": deepcopy(self.scene_metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProceduralWorkspaceState":
        if str(data.get("schema") or "") != PROCEDURAL_WORKSPACE_SCHEMA:
            raise ValueError("Unsupported TC procedural workspace schema.")
        graphs = {
            str(key): ProceduralGraph.from_dict(dict(value))
            for key, value in dict(data.get("graphs") or {}).items()
            if isinstance(value, dict)
        }
        task_graphs = {
            str(key): ProceduralTaskGraph.from_dict(dict(value))
            for key, value in dict(data.get("task_graphs") or {}).items()
            if isinstance(value, dict)
        }
        active_graph_id = str(data.get("active_graph_id") or "")
        active_task_graph_id = str(data.get("active_task_graph_id") or "")
        if active_graph_id and active_graph_id not in graphs:
            active_graph_id = ""
        if active_task_graph_id and active_task_graph_id not in task_graphs:
            active_task_graph_id = ""
        scene_metadata = data.get("scene_metadata")
        return cls(
            graphs=graphs,
            task_graphs=task_graphs,
            active_graph_id=active_graph_id,
            active_task_graph_id=active_task_graph_id,
            scene_metadata=deepcopy(scene_metadata) if isinstance(scene_metadata, dict) else {"metadata": {}},
        )
