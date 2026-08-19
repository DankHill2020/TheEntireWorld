"""Incremental `.tcscene` save-to-game and playtest iteration contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Callable


HOT_SWAP = "hot_swap"
STATE_MIGRATION = "state_migration"
RESTART_REQUIRED = "restart_required"
_MODE_PRIORITY = {HOT_SWAP: 0, STATE_MIGRATION: 1, RESTART_REQUIRED: 2}


@dataclass
class LiveGameSession:
    session_id: str
    target: str
    transport: Callable[[dict[str, Any]], Any]
    capabilities: set[str] = field(default_factory=lambda: {HOT_SWAP, STATE_MIGRATION})
    mode: str = "local_playtest"


_SESSIONS: dict[str, LiveGameSession] = {}
_SCENE_CHUNKS: dict[str, dict[str, tuple[str, str]]] = {}
_SCENE_REVISIONS: dict[str, int] = {}


def register_live_game_session(
    session_id: str,
    transport: Callable[[dict[str, Any]], Any],
    *,
    target: str = "desktop",
    capabilities: set[str] | None = None,
    mode: str = "local_playtest",
) -> LiveGameSession:
    if not callable(transport):
        raise TypeError("A live game transport must be callable.")
    session = LiveGameSession(
        str(session_id), str(target), transport,
        set(capabilities or {HOT_SWAP, STATE_MIGRATION}), str(mode),
    )
    _SESSIONS[session.session_id] = session
    return session


def unregister_live_game_session(session_id: str) -> None:
    _SESSIONS.pop(str(session_id), None)


def live_game_sessions() -> list[dict[str, Any]]:
    return [
        {
            "session_id": item.session_id,
            "target": item.target,
            "mode": item.mode,
            "capabilities": sorted(item.capabilities),
        }
        for item in _SESSIONS.values()
    ]


def publish_tcscene_save(
    document: dict[str, Any],
    scene_path: str | Path,
    *,
    force_full: bool = False,
) -> dict[str, Any]:
    """Compile changed logical chunks and publish them to every live game session."""
    scene_id = str(document.get("scene_id") or Path(scene_path).stem)
    chunks = _scene_chunks(document)
    hashes = {chunk_id: _stable_hash(payload) for chunk_id, (_mode, payload) in chunks.items()}
    previous = _SCENE_CHUNKS.get(scene_id, {})
    previous_hashes = {
        chunk_id: payload[1] if isinstance(payload, tuple) and len(payload) == 2 else payload
        for chunk_id, payload in previous.items()
    }
    changed_ids = [
        chunk_id for chunk_id, digest in hashes.items()
        if force_full or previous_hashes.get(chunk_id) != digest
    ]
    removed_ids = sorted(set(previous_hashes) - set(hashes))
    revision = _SCENE_REVISIONS.get(scene_id, 0) + 1
    _SCENE_REVISIONS[scene_id] = revision
    _SCENE_CHUNKS[scene_id] = {chunk_id: (chunks[chunk_id][0], digest) for chunk_id, digest in hashes.items()}

    changed = [
        {
            "chunk_id": chunk_id,
            "hash": hashes[chunk_id],
            "update_mode": chunks[chunk_id][0],
            "payload": chunks[chunk_id][1],
        }
        for chunk_id in changed_ids
    ]
    required_mode = max(
        [item["update_mode"] for item in changed]
        + [_snapshot_mode_for_chunk(previous.get(chunk_id), chunk_id) for chunk_id in removed_ids]
        or [HOT_SWAP],
        key=_MODE_PRIORITY.__getitem__,
    )
    packet = {
        "schema": "tech_connector.live_scene_update.v1",
        "scene_id": scene_id,
        "scene_path": str(Path(scene_path)),
        "revision": revision,
        "required_mode": required_mode,
        "changed_chunks": changed,
        "removed_chunks": removed_ids,
    }
    deliveries = []
    if not changed and not removed_ids:
        return {
            "schema": "tech_connector.live_scene_update_receipt.v1",
            "scene_id": scene_id,
            "revision": revision,
            "changed_chunk_count": 0,
            "removed_chunk_count": 0,
            "removed_chunks": [],
            "required_mode": HOT_SWAP,
            "connected_sessions": len(_SESSIONS),
            "updated_sessions": 0,
            "deliveries": [],
            "message": "Saved. The running game is already up to date.",
        }
    for session in _SESSIONS.values():
        supported = required_mode in session.capabilities
        if not supported:
            deliveries.append({
                "session_id": session.session_id,
                "status": "restart_required",
                "reason": f"The running {session.target} session cannot apply {required_mode} updates.",
            })
            continue
        try:
            response = session.transport(packet)
            deliveries.append({
                "session_id": session.session_id,
                "status": "updated",
                "response": response,
            })
        except Exception as exc:
            deliveries.append({
                "session_id": session.session_id,
                "status": "failed",
                "reason": str(exc),
            })

    updated = sum(item["status"] == "updated" for item in deliveries)
    return {
        "schema": "tech_connector.live_scene_update_receipt.v1",
        "scene_id": scene_id,
        "revision": revision,
        "changed_chunk_count": len(changed),
        "removed_chunk_count": len(removed_ids),
        "removed_chunks": list(removed_ids),
        "required_mode": required_mode,
        "connected_sessions": len(_SESSIONS),
        "updated_sessions": updated,
        "deliveries": deliveries,
        "message": _update_message(len(changed), len(_SESSIONS), updated, required_mode),
    }


def build_playtest_iteration_plan(
    *,
    target: str = "desktop",
    session_mode: str = "play_in_editor",
    changed_modes: list[str] | tuple[str, ...] = (),
    session_connected: bool = False,
) -> dict[str, Any]:
    """Explain the fastest truthful route from an edit to a playable session."""
    modes = [mode for mode in changed_modes if mode in _MODE_PRIORITY]
    required_mode = max(modes or [HOT_SWAP], key=_MODE_PRIORITY.__getitem__)
    package_required = required_mode == RESTART_REQUIRED and str(session_mode) in {"remote_device", "external_playtest"}
    if session_connected and required_mode != RESTART_REQUIRED:
        action = "Update the running game"
        strategy = "incremental_live_sync"
    elif package_required:
        action = "Rebuild changed runtime chunks and package"
        strategy = "incremental_package"
    else:
        action = "Launch once, then keep it connected for live updates"
        strategy = "launch_reusable_session"
    return {
        "schema": "tech_connector.playtest_iteration_plan.v1",
        "target": str(target),
        "session_mode": str(session_mode),
        "required_mode": required_mode,
        "package_required": package_required,
        "strategy": strategy,
        "primary_action": action,
        "preserve": ["player position", "gameplay state", "connected players", "active level"] if required_mode == HOT_SWAP else ["compatible gameplay state", "session identity"],
        "rebuild_scope": ["changed chunks", "dependency closure"] if package_required else [],
        "explanation": (
            "No package build is needed; changed scene chunks can update the running playtest."
            if not package_required
            else "This change affects runtime/platform code, so the changed executable chunks must be rebuilt."
        ),
    }


def reset_live_sync_state() -> None:
    """Clear process-local sessions and snapshots; intended for shutdown and tests."""
    _SESSIONS.clear()
    _SCENE_CHUNKS.clear()
    _SCENE_REVISIONS.clear()


def _scene_chunks(document: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    metadata = dict(document.get("metadata") or {})
    chunks: dict[str, tuple[str, Any]] = {
        "scene.sources": (STATE_MIGRATION, document.get("sources") or []),
        "scene.rig_graph": (STATE_MIGRATION, document.get("rig_graph") or {}),
        "scene.constraints": (HOT_SWAP, document.get("cross_dcc_constraints") or []),
        "scene.timeline": (HOT_SWAP, document.get("timeline") or {}),
        "scene.runtime_simulation": (HOT_SWAP, metadata.get("runtime_simulation") or {}),
        "scene.runtime_world": (HOT_SWAP, metadata.get("runtime_world") or {}),
        "scene.gameplay": (STATE_MIGRATION, metadata.get("gameplay_graph") or {}),
    }
    native_runtime = metadata.get("native_runtime") or metadata.get("runtime_plugins")
    if native_runtime:
        chunks["runtime.native"] = (RESTART_REQUIRED, native_runtime)
    return chunks


def _snapshot_mode_for_chunk(snapshot_value: Any, chunk_id: str) -> str:
    if isinstance(snapshot_value, tuple) and len(snapshot_value) == 2:
        candidate = str(snapshot_value[0])
        if candidate in _MODE_PRIORITY:
            return candidate
    if chunk_id == "scene.sources":
        return STATE_MIGRATION
    if chunk_id == "scene.rig_graph":
        return STATE_MIGRATION
    if chunk_id == "scene.gameplay":
        return STATE_MIGRATION
    if chunk_id == "runtime.native":
        return RESTART_REQUIRED
    return HOT_SWAP


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=list).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _update_message(changes: int, sessions: int, updated: int, mode: str) -> str:
    if not sessions:
        return f"Saved {changes} changed chunk(s). No running game is connected."
    if updated == sessions:
        return f"Updated {updated} running game session(s) using {mode.replace('_', ' ')}."
    return f"Updated {updated} of {sessions} game session(s); review the remaining session status."
