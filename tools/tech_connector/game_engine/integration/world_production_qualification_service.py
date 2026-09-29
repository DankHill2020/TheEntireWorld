from __future__ import annotations

"""Qualification for world building, streaming, and procedural geometry."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Mapping

from tech_connector.game_engine.assets.editor_python_api import TCEditorAPI
from tech_connector.game_engine.assets.world_asset_service import WORLD_ASSET_TYPES
from tech_connector.game_engine.authoring.procedural_generation_service import ProceduralGraph
from tech_connector.game_engine.integration.playable_project_qualification_service import playable_project_source_fingerprint
from tech_connector.game_engine.runtime.world_streaming_runtime_service import StreamingSource


WORLD_PRODUCTION_QUALIFICATION_SCHEMA = "tech_connector.world_production_qualification.v1"
DEFAULT_MAX_AGE_SECONDS = 7.0 * 24.0 * 60.0 * 60.0


def qualify_world_production(
    source_root: str | Path, output_root: str | Path, *, maximum_total_seconds: float = 30.0,
) -> dict[str, Any]:
    source = Path(source_root).expanduser().resolve(); output = Path(output_root).expanduser().resolve()
    run_id = f"run-{time.time_ns()}"; workspace = output / "runs" / run_id / "workspace"
    output.mkdir(parents=True, exist_ok=True); api = TCEditorAPI(workspace); started = time.perf_counter()
    level = api.create_asset("tc.prefab", "QualificationLevel", folder="Assets/Qualification")
    prop = api.create_asset("tc.data", "QualificationRock", folder="Assets/Qualification", properties={"triangle_count": 2400})
    terrain = api.create_world_asset("tc.terrain", "Terrain", properties={
        "resolution": [33, 33], "cell_size": 100.0, "height_scale": 80.0, "seed": 91,
        "erosion": {"mode": "thermal", "iterations": 2, "strength": 0.15},
        "lod": {"levels": 4}, "collision": {"enabled": True, "lod": 1},
    })
    foliage = api.create_world_asset("tc.foliage_type", "RockFoliage", properties={
        "mesh_asset_id": prop.asset_id, "minimum_spacing": 180.0, "slope_range": [0.0, 60.0], "scale_range": [0.7, 1.4],
    })
    biome = api.create_world_asset("tc.biome", "RockyBiome", properties={
        "terrain_asset_id": terrain.asset_id, "seed": 13, "density": 0.65,
        "species": [{"foliage_type_id": foliage.asset_id, "weight": 1.0}],
    })
    layer = api.create_world_asset("tc.data_layer", "Gameplay", properties={"asset_ids": [prop.asset_id]})
    navigation = api.create_world_asset("tc.navigation_mesh", "Navigation", properties={
        "terrain_asset_ids": [terrain.asset_id], "tile_size": 800.0,
        "agents": [{"name": "Human", "radius": 34.0, "height": 180.0, "maximum_slope": 60.0}],
    })
    lighting = api.create_world_asset("tc.lighting_scenario", "Day", properties={
        "terrain_asset_ids": [terrain.asset_id], "environment": {"intensity": 1.2, "rotation": 35.0},
    })
    hlod = api.create_world_asset("tc.hlod_layer", "Far", properties={
        "source_data_layer_ids": [layer.asset_id], "reduction_ratio": 0.25,
    })
    partition = api.create_world_asset("tc.world_partition", "Partition", properties={
        "source_level_id": level.asset_id, "data_layer_ids": [layer.asset_id], "hlod_layer_ids": [hlod.asset_id],
        "cell_size": 1000.0, "loading_range": 1500.0,
        "budgets": {"maximum_loaded_cells": 2, "memory_mb": 16, "io_mb_per_second": 64, "maximum_requests": 1},
    })
    assets = (terrain, foliage, biome, layer, navigation, lighting, hlod, partition); rows: list[dict[str, Any]] = []
    backend_types = {"tc.terrain", "tc.navigation_mesh", "tc.lighting_scenario", "tc.hlod_layer", "tc.world_partition"}
    for asset in assets:
        record = api.database.asset(asset.asset_id); assert record is not None
        item_started = time.perf_counter(); issues = api.validate_world_asset(asset.asset_id)
        preview = api.preview_world_asset(asset.asset_id, maximum_resolution=65)
        first = api.compile_world_asset(asset.asset_id, platform="windows", quality="high"); first_bytes = first.path.read_bytes()
        second = api.compile_world_asset(asset.asset_id, platform="windows", quality="high"); second_bytes = second.path.read_bytes()
        backend = api.build_world_backend(asset.asset_id, platform="windows", quality="high") if record.asset_type in backend_types else {}
        checks = {"validation": not any(issue.get("severity") == "error" for issue in issues),
                  "preview": bool(preview), "deterministic_cook": first_bytes == second_bytes,
                  "backend": bool(backend) if record.asset_type in backend_types else True}
        rows.append({"asset_id": asset.asset_id, "type_id": record.asset_type,
                     "status": "passed" if all(checks.values()) else "blocked", "checks": checks,
                     "cook_sha256": hashlib.sha256(first_bytes).hexdigest(), "backend": backend,
                     "elapsed_seconds": round(time.perf_counter() - item_started, 6)})
    runtime = api.open_world_streaming_runtime(partition.asset_id); cell = next(iter(runtime.cells.values()))
    loaded = runtime.tick([StreamingSource("Player", cell.center, 500.0, priority=100)])
    retained = [cell.cell_id in runtime.tick([]).resident for _ in range(runtime.unload_hysteresis_frames)]
    unloaded = runtime.tick([])
    streaming_checks = {"loads": cell.cell_id in loaded.loaded, "memory_budget": loaded.memory_mb <= loaded.budget_memory_mb,
                        "hysteresis": all(retained), "unloads": cell.cell_id in unloaded.unloaded}
    graph = ProceduralGraph(name="Qualification Boulder", graph_id="qualification_boulder", seed=17)
    graph.add_node("sphere", "mesh_uv_sphere", parameters={"segments": 12, "rings": 6, "radius": 2.0})
    graph.add_node("subdivide", "mesh_subdivide", inputs=("sphere",), parameters={"levels": 1})
    graph.add_node("normals", "mesh_compute_normals", inputs=("subdivide",)); graph.add_node("output", "output", inputs=("normals",))
    procedural = api.create_procedural_graph("QualificationBoulder", graph=graph)
    procedural_issues = api.validate_procedural_graph(procedural.asset_id)
    first_procedural = api.cook_procedural_graph(procedural.asset_id, platform="windows", quality="high").path.read_bytes()
    second_procedural = api.cook_procedural_graph(procedural.asset_id, platform="windows", quality="high").path.read_bytes()
    adapters = {}
    for target in ("unreal", "unity", "blender", "houdini", "godot"):
        document = api.procedural_native_document(procedural.asset_id, target)
        imported = api.import_procedural_native_document(document, name=f"RoundTrip_{target}")
        adapters[target] = {"schema": document["schema"], "lossless": bool(document["lossless"]),
                            "valid": not api.validate_procedural_graph(imported.asset_id)}
    procedural_checks = {"validation": not procedural_issues, "deterministic_cook": first_procedural == second_procedural,
                         "native_adapters": all(row["lossless"] and row["valid"] for row in adapters.values()),
                         "simulation": api.step_procedural_simulation(procedural.asset_id)["metadata"]["simulation"]["frame"] == 1}
    elapsed = time.perf_counter() - started
    qualified = sorted(set(WORLD_ASSET_TYPES) | {"tc.procedural_graph"})
    passed = all(row["status"] == "passed" for row in rows) and all(streaming_checks.values()) and all(procedural_checks.values()) and elapsed <= float(maximum_total_seconds)
    receipt = {"schema": WORLD_PRODUCTION_QUALIFICATION_SCHEMA, "status": "passed" if passed else "blocked",
               "verified_at": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
               "source_fingerprint": playable_project_source_fingerprint(source), "maximum_total_seconds": float(maximum_total_seconds),
               "elapsed_seconds": round(elapsed, 6), "world_assets": rows, "streaming_checks": streaming_checks,
               "procedural": {"status": "passed" if all(procedural_checks.values()) else "blocked", "checks": procedural_checks,
                              "cook_sha256": hashlib.sha256(first_procedural).hexdigest(), "adapters": adapters},
               "qualified_asset_types": qualified if passed else []}
    report = output / "world_production_qualification.json"; temporary = report.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8"); temporary.replace(report)
    return receipt | {"report": str(report)}


def validate_world_production_qualification(source_root: str | Path, receipt: Mapping[str, Any] | None, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS) -> dict[str, Any]:
    row = dict(receipt or {}); gates: list[str] = []
    if row.get("schema") != WORLD_PRODUCTION_QUALIFICATION_SCHEMA: gates.append("schema")
    if row.get("status") != "passed": gates.append("status")
    if len(row.get("world_assets") or ()) != len(WORLD_ASSET_TYPES) or any(dict(item).get("status") != "passed" for item in row.get("world_assets") or ()): gates.append("world_assets")
    if dict(row.get("procedural") or {}).get("status") != "passed": gates.append("procedural")
    verified = _timestamp(row.get("verified_at")); now = datetime.now(timezone.utc).timestamp()
    if verified <= 0.0 or now - verified > max(0.0, float(max_age_seconds)): gates.append("freshness")
    expected = playable_project_source_fingerprint(source_root)
    if str(row.get("source_fingerprint") or "") != expected: gates.append("source_fingerprint")
    return {"valid": not gates, "gates": sorted(set(gates)), "age_seconds": max(0.0, now - verified) if verified > 0 else None,
            "source_fingerprint": expected}


def load_world_production_qualification(path: str | Path) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file(): return {}
    try: value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
    return dict(value) if isinstance(value, dict) else {}


def _timestamp(value: Any) -> float:
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError): return 0.0


__all__ = ["WORLD_PRODUCTION_QUALIFICATION_SCHEMA", "load_world_production_qualification", "qualify_world_production", "validate_world_production_qualification"]
