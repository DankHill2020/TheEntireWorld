from __future__ import annotations

"""Native, reproducible qualification for the default playable-project slice."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time
from typing import Any, Mapping

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.authoring.game_template_service import available_game_templates
from tech_connector.game_engine.runtime.tc_player_build_service import (
    build_windows_player,
    compile_tcscene_for_runtime,
    validate_player_package,
)


PLAYABLE_PROJECT_QUALIFICATION_SCHEMA = "tech_connector.playable_project_qualification.v1"
DEFAULT_MAX_AGE_SECONDS = 7.0 * 24.0 * 60.0 * 60.0
DEFAULT_BUDGETS_MS = {"frame_p95": 16.667, "graph_p95": 4.0, "physics_p95": 4.0}


def qualify_playable_project(
    source_root: str | Path,
    output_root: str | Path,
    player_executable: str | Path,
    *,
    frames: int = 120,
    budgets_ms: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Generate, package, and execute every production template through the native player."""

    source = Path(source_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    player = Path(player_executable).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    budgets = dict(DEFAULT_BUDGETS_MS); budgets.update({str(key): float(value) for key, value in dict(budgets_ms or {}).items()})
    variants = [row for row in available_game_templates() if row.get("maturity") == "production"]
    run_id = f"run-{time.time_ns()}"
    run_root = output / "runs" / run_id
    rows: list[dict[str, Any]] = []
    for variant in variants:
        qualified_id = str(variant["qualified_id"])
        slug = qualified_id.replace("/", "_")
        workspace = run_root / "workspaces" / slug
        package = run_root / "packages" / slug
        started = time.perf_counter()
        api = TCEditorAPI(workspace)
        receipt = api.create_game_project_from_template(
            project_name="LaunchQualified",
            template_id=str(variant["template_id"]),
            variant_id=str(variant["variant_id"]),
        )
        level = api.database.asset(str(receipt["level_asset_id"]))
        if level is None:
            raise RuntimeError(f"Template {qualified_id} did not create its entry Level.")
        created_asset_ids = tuple(str(value) for value in receipt.get("created_asset_ids") or ())
        created_asset_types = sorted({
            record.asset_type for asset_id in created_asset_ids
            if (record := api.database.asset(asset_id)) is not None
        })
        cooked = api.cook(created_asset_ids)
        first = compile_tcscene_for_runtime(level.source_path, run_root / "determinism-a" / f"{slug}.tcruntime")
        second = compile_tcscene_for_runtime(level.source_path, run_root / "determinism-b" / f"{slug}.tcruntime")
        first_bytes = first.runtime_manifest.read_bytes(); second_bytes = second.runtime_manifest.read_bytes()
        deterministic = first_bytes == second_bytes
        packaged = build_windows_player(level.source_path, package, player_executable=player)
        runtime = validate_player_package(package, frames=max(2, int(frames)))
        profile = dict(runtime.get("profile_summary") or {})
        frame_p95 = float(dict(profile.get("frame") or {}).get("p95_ms") or 0.0)
        graph_p95 = float(dict(profile.get("graph") or {}).get("p95_ms") or 0.0)
        physics_p95 = float(dict(profile.get("physics") or {}).get("p95_ms") or 0.0)
        checks = {
            "template_valid": bool(receipt.get("ready_to_play")),
            "asset_cook": cooked.artifact.path.is_file(),
            "cook_dependency_closure": set(cooked.asset_ids) == set(created_asset_ids),
            "deterministic_compile": deterministic,
            "asset_integrity": dict(packaged.validation.get("assets") or {}).get("status") == "passed",
            "native_runtime": runtime.get("status") == "passed",
            "frame_budget": frame_p95 <= budgets["frame_p95"],
            "graph_budget": graph_p95 <= budgets["graph_p95"],
            "physics_budget": physics_p95 <= budgets["physics_p95"],
        }
        rows.append({
            "qualified_id": qualified_id,
            "status": "passed" if all(checks.values()) else "blocked",
            "checks": checks,
            "created_asset_count": len(created_asset_ids),
            "created_asset_types": created_asset_types,
            "cook_manifest_sha256": _file_hash(cooked.artifact.path),
            "packaged_asset_count": int(dict(packaged.validation.get("assets") or {}).get("verified_count") or 0),
            "entities": packaged.entities,
            "graph_operations": packaged.graph_operations,
            "manifest_sha256": hashlib.sha256(first_bytes).hexdigest(),
            "profile_summary": profile,
            "elapsed_seconds": round(time.perf_counter() - started, 6),
        })
    qualified_asset_types = sorted({
        type_id for row in rows if row["status"] == "passed"
        for type_id in row["created_asset_types"]
    })
    receipt = {
        "schema": PLAYABLE_PROJECT_QUALIFICATION_SCHEMA,
        "status": "passed" if variants and all(row["status"] == "passed" for row in rows) else "blocked",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "source_fingerprint": playable_project_source_fingerprint(source),
        "player_executable": str(player),
        "player_sha256": _file_hash(player),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "frames": max(2, int(frames)),
        "budgets_ms": budgets,
        "qualified_asset_types": qualified_asset_types,
        "variants": rows,
    }
    report = output / "playable_project_qualification.json"
    temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(report)
    return receipt | {"report": str(report)}


def validate_playable_project_qualification(
    source_root: str | Path,
    receipt: Mapping[str, Any] | None,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    row = dict(receipt or {}); gates: list[str] = []
    if row.get("schema") != PLAYABLE_PROJECT_QUALIFICATION_SCHEMA: gates.append("schema")
    if row.get("status") != "passed": gates.append("status")
    variants = list(row.get("variants") or ())
    if not variants or any(dict(item).get("status") != "passed" for item in variants): gates.append("production_variants")
    verified_at = _timestamp(row.get("verified_at"))
    now = datetime.now(timezone.utc).timestamp()
    if verified_at <= 0.0 or now - verified_at > max(0.0, float(max_age_seconds)): gates.append("freshness")
    expected_fingerprint = playable_project_source_fingerprint(source_root)
    if str(row.get("source_fingerprint") or "") != expected_fingerprint: gates.append("source_fingerprint")
    player = Path(str(row.get("player_executable") or ""))
    if not player.is_file() or str(row.get("player_sha256") or "") != _file_hash(player): gates.append("player_binary")
    return {"valid": not gates, "gates": sorted(set(gates)), "age_seconds": max(0.0, now - verified_at) if verified_at > 0 else None,
            "source_fingerprint": expected_fingerprint}


def load_playable_project_qualification(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file(): return {}
    try: value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
    return dict(value) if isinstance(value, dict) else {}


def playable_project_source_fingerprint(source_root: str | Path) -> str:
    root = Path(source_root).expanduser().resolve(); digest = hashlib.sha256()
    candidates: list[Path] = []
    for relative in ("tech_connector/game_engine", "tech_connector/ui/game_engine"):
        folder = root / relative
        if folder.is_dir():
            candidates.extend(path for path in folder.rglob("*") if path.is_file() and path.suffix.casefold() in {".py", ".cpp", ".h"} and ".tech_connector" not in path.parts)
    cmake = root / "tech_connector" / "game_engine" / "native" / "CMakeLists.txt"
    if cmake.is_file(): candidates.append(cmake)
    for path in sorted(set(candidates), key=lambda value: value.as_posix().casefold()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8")); digest.update(b"\0"); digest.update(path.read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    if not path.is_file(): return ""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value: Any) -> float:
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return 0.0


__all__ = [
    "DEFAULT_BUDGETS_MS", "DEFAULT_MAX_AGE_SECONDS", "PLAYABLE_PROJECT_QUALIFICATION_SCHEMA",
    "load_playable_project_qualification", "playable_project_source_fingerprint",
    "qualify_playable_project", "validate_playable_project_qualification",
]
