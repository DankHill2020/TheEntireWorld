"""Headless level-actor editing over the same runtime-world schema used by Garden."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from tech_connector.game_engine.assets.asset_database_service import AssetDatabase
from tech_connector.game_engine.scene.federated_scene_service import load_federated_scene, save_federated_scene


LEVEL_ACTOR_EDIT_SCHEMA = "tech_connector.level_actor_edit.v1"


class LevelActorAuthoringService:
    """Apply deterministic, reference-safe actor edits to a saved Level asset."""

    def __init__(self, project_root: str | Path, database: AssetDatabase) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database

    def actors(self, level_asset_id: str) -> tuple[dict[str, Any], ...]:
        _record, _document, _blobs, world = self._load(level_asset_id)
        return tuple(copy.deepcopy(item) for item in world.get("entities") or () if isinstance(item, dict))

    def set_render_mesh(self, level_asset_id: str, actor_name: str, mesh_asset_id: str) -> dict[str, Any]:
        """Bind an imported OBJ mesh to one named actor in a saved Level."""
        mesh = self.database.asset(str(mesh_asset_id))
        if mesh is None or mesh.asset_type != "tc.static_mesh" or mesh.source_path.suffix.casefold() != ".obj":
            raise ValueError("Runtime render mesh must be an imported tc.static_mesh OBJ asset.")
        record, document, blobs, world = self._load(level_asset_id)
        matches = [row for row in world.get("entities") or () if isinstance(row, dict) and str(row.get("name") or "") == str(actor_name)]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one level actor named '{actor_name}', found {len(matches)}.")
        actor = matches[0]
        if bool(actor.get("editor_locked", False)):
            raise ValueError(f"Level actor '{actor_name}' is locked.")
        actor.setdefault("render", {})["mesh"] = str(mesh.source_path)
        document.metadata["runtime_world"] = world
        save_federated_scene(record.source_path, document, blobs=blobs)
        dependencies = [edge for edge in self.database.dependency_edges(record.asset_id) if edge[1] != f"actor_mesh:{actor_name}"]
        dependencies.append((mesh.asset_id, f"actor_mesh:{actor_name}"))
        self.database.register_asset(
            record.source_path, record.asset_type, asset_id=record.asset_id,
            metadata=record.metadata, dependencies=dependencies,
        )
        return {
            "schema": LEVEL_ACTOR_EDIT_SCHEMA, "operation": "set_render_mesh",
            "level_asset_id": record.asset_id, "actor_name": str(actor_name),
            "mesh_asset_id": mesh.asset_id, "mesh_source": str(mesh.source_path),
        }

    def transform(
        self, level_asset_id: str, actor_ids: Iterable[str], *,
        translation: Iterable[float] = (0.0, 0.0, 0.0),
        rotation: Iterable[float] = (0.0, 0.0, 0.0),
        scale_multiplier: Iterable[float] = (1.0, 1.0, 1.0),
    ) -> dict[str, Any]:
        move, rotate, scale = _vector(translation, 0.0), _vector(rotation, 0.0), _vector(scale_multiplier, 1.0)
        def mutate(world: dict[str, Any], selected: list[dict[str, Any]]) -> None:
            for entity in selected:
                transform = entity.setdefault("transform", {})
                position = _vector(transform.get("position"), 0.0); angles = _vector(transform.get("rotation"), 0.0); size = _vector(transform.get("scale"), 1.0)
                transform["position"] = [position[i] + move[i] for i in range(3)]
                transform["rotation"] = [angles[i] + rotate[i] for i in range(3)]
                transform["scale"] = [size[i] * scale[i] for i in range(3)]
        return self._edit(level_asset_id, actor_ids, "transform", mutate, skip_locked=True)

    def set_visibility(self, level_asset_id: str, actor_ids: Iterable[str], visible: bool) -> dict[str, Any]:
        return self._edit(level_asset_id, actor_ids, "visibility", lambda _world, rows: [row.__setitem__("visible", bool(visible)) for row in rows])

    def isolate(self, level_asset_id: str, actor_ids: Iterable[str]) -> dict[str, Any]:
        wanted = {str(value) for value in actor_ids}
        def mutate(world: dict[str, Any], _selected: list[dict[str, Any]]) -> None:
            world["editor_isolation_visibility"] = {str(row.get("entity_id") or ""): bool(row.get("visible", True)) for row in world.get("entities") or () if isinstance(row, dict)}
            for row in world.get("entities") or ():
                if isinstance(row, dict): row["visible"] = str(row.get("entity_id") or "") in wanted
        return self._edit(level_asset_id, wanted, "isolate", mutate)

    def show_all(self, level_asset_id: str) -> dict[str, Any]:
        def mutate(world: dict[str, Any], rows: list[dict[str, Any]]) -> None:
            for row in rows: row["visible"] = True
            world.pop("editor_isolation_visibility", None)
        return self._edit(level_asset_id, (str(row.get("entity_id") or "") for row in self.actors(level_asset_id)), "show_all", mutate)

    def set_locked(self, level_asset_id: str, actor_ids: Iterable[str], locked: bool) -> dict[str, Any]:
        return self._edit(level_asset_id, actor_ids, "lock", lambda _world, rows: [row.__setitem__("editor_locked", bool(locked)) for row in rows])

    def duplicate(self, level_asset_id: str, actor_ids: Iterable[str]) -> dict[str, Any]:
        """Duplicate unlocked actors while giving actors and components fresh identities."""

        created_ids: list[str] = []

        def mutate(world: dict[str, Any], rows: list[dict[str, Any]]) -> None:
            duplicates: list[dict[str, Any]] = []
            for row in rows:
                duplicate = copy.deepcopy(row)
                duplicate_id = f"actor-{uuid.uuid4().hex}"
                duplicate["entity_id"] = duplicate_id
                duplicate["name"] = f"{str(row.get('name') or 'Actor')} Copy"
                duplicate["editor_locked"] = False
                for component in duplicate.get("components") or ():
                    if isinstance(component, dict):
                        component["component_id"] = f"component-{uuid.uuid4().hex}"
                transform = duplicate.setdefault("transform", {})
                position = _vector(transform.get("position"), 0.0)
                transform["position"] = [position[0] + 0.5, position[1], position[2] + 0.5]
                duplicates.append(duplicate)
                created_ids.append(duplicate_id)
            world.setdefault("entities", []).extend(duplicates)

        receipt = self._edit(level_asset_id, actor_ids, "duplicate", mutate, skip_locked=True)
        receipt["source_actor_ids"] = receipt["actor_ids"]
        receipt["actor_ids"] = tuple(created_ids)
        receipt["changed_count"] = len(created_ids)
        return receipt

    def delete(self, level_asset_id: str, actor_ids: Iterable[str]) -> dict[str, Any]:
        """Delete unlocked actors and detach surviving children from deleted parents."""

        deleted_ids: list[str] = []

        def mutate(world: dict[str, Any], rows: list[dict[str, Any]]) -> None:
            deleted_ids.extend(str(row.get("entity_id") or "") for row in rows)
            deleted = set(deleted_ids)
            survivors = [
                row for row in world.get("entities") or ()
                if not isinstance(row, dict) or str(row.get("entity_id") or "") not in deleted
            ]
            for row in survivors:
                if isinstance(row, dict) and str(row.get("parent_entity_id") or "") in deleted:
                    row["parent_entity_id"] = ""
            world["entities"] = survivors

        receipt = self._edit(level_asset_id, actor_ids, "delete", mutate, skip_locked=True)
        receipt["actor_ids"] = tuple(deleted_ids)
        receipt["changed_count"] = len(deleted_ids)
        return receipt

    def move_to_folder(self, level_asset_id: str, actor_ids: Iterable[str], folder: str) -> dict[str, Any]:
        value = str(folder or "").replace("\\", "/").strip(" /")
        def mutate(world: dict[str, Any], rows: list[dict[str, Any]]) -> None:
            if value:
                folders = world.setdefault("editor_folders", [])
                if value not in folders: folders.append(value); folders.sort()
            for row in rows: row["editor_folder"] = value
        return self._edit(level_asset_id, actor_ids, "folder", mutate, skip_locked=True)

    def parent(self, level_asset_id: str, actor_ids: Iterable[str], parent_actor_id: str = "") -> dict[str, Any]:
        selected_ids = {str(value) for value in actor_ids}; parent_id = str(parent_actor_id or "")
        def mutate(world: dict[str, Any], rows: list[dict[str, Any]]) -> None:
            by_id = {str(row.get("entity_id") or ""): row for row in world.get("entities") or () if isinstance(row, dict)}
            if parent_id and parent_id not in by_id: raise KeyError(f"Unknown parent actor: {parent_id}")
            ancestor = parent_id
            while ancestor:
                if ancestor in selected_ids: raise ValueError("Parenting would create an actor hierarchy cycle.")
                ancestor = str(by_id.get(ancestor, {}).get("parent_entity_id") or "")
            for row in rows: row["parent_entity_id"] = parent_id
        return self._edit(level_asset_id, selected_ids, "parent", mutate, skip_locked=True)

    def reorder_component(self, level_asset_id: str, actor_id: str, component_id: str, new_index: int) -> dict[str, Any]:
        def mutate(_world: dict[str, Any], rows: list[dict[str, Any]]) -> None:
            if not rows: return
            components = list(rows[0].get("components") or ()); index = next((i for i, item in enumerate(components) if str(item.get("component_id") or "") == str(component_id)), -1)
            if index < 0: raise KeyError(f"Unknown component: {component_id}")
            if str(components[index].get("type") or "") == "transform": raise ValueError("The Transform component must remain first.")
            component = components.pop(index); components.insert(max(1, min(len(components), int(new_index))), component); rows[0]["components"] = components
        return self._edit(level_asset_id, (actor_id,), "reorder_component", mutate, skip_locked=True)

    def save_camera_bookmark(self, level_asset_id: str, slot: int, camera: dict[str, Any]) -> dict[str, Any]:
        index = max(1, min(9, int(slot)))
        required = {"eye", "target", "up"}
        if not required.issubset(camera): raise ValueError("Camera bookmark requires eye, target, and up vectors.")
        def mutate(world: dict[str, Any], _rows: list[dict[str, Any]]) -> None:
            world.setdefault("editor_camera_bookmarks", {})[str(index)] = copy.deepcopy(camera)
        return self._edit(level_asset_id, (), "camera_bookmark", mutate)

    def _edit(
        self, level_asset_id: str, actor_ids: Iterable[str], operation: str,
        mutation: Callable[[dict[str, Any], list[dict[str, Any]]], None], *, skip_locked: bool = False,
    ) -> dict[str, Any]:
        record, document, blobs, world = self._load(level_asset_id)
        wanted = {str(value) for value in actor_ids if str(value)}
        selected = [row for row in world.get("entities") or () if isinstance(row, dict) and str(row.get("entity_id") or "") in wanted]
        missing = sorted(wanted - {str(row.get("entity_id") or "") for row in selected})
        if missing: raise KeyError("Unknown level actor IDs: " + ", ".join(missing))
        if skip_locked: selected = [row for row in selected if not bool(row.get("editor_locked", False))]
        mutation(world, selected)
        document.metadata["runtime_world"] = world
        save_federated_scene(record.source_path, document, blobs=blobs)
        self.database.register_asset(
            record.source_path, record.asset_type, asset_id=record.asset_id,
            metadata=record.metadata, dependencies=self.database.dependency_edges(record.asset_id),
        )
        return {"schema": LEVEL_ACTOR_EDIT_SCHEMA, "operation": operation, "level_asset_id": record.asset_id, "actor_ids": tuple(str(row.get("entity_id") or "") for row in selected), "changed_count": len(selected)}

    def _load(self, level_asset_id: str):
        record = self.database.asset(str(level_asset_id))
        if record is None or record.asset_type != "tc.level": raise KeyError(f"Expected tc.level asset: {level_asset_id}")
        document, blobs = load_federated_scene(record.source_path)
        world = dict(document.metadata.get("runtime_world") or {}); world.setdefault("entities", [])
        return record, document, blobs, world


def _vector(values: Iterable[float] | None, default: float) -> list[float]:
    result = [float(value) for value in (values or ())]
    result += [float(default)] * (3 - len(result))
    return result[:3]


__all__ = ["LEVEL_ACTOR_EDIT_SCHEMA", "LevelActorAuthoringService"]
