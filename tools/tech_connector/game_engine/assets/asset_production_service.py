"""Dependency-closed cook manifests and production-readiness diagnostics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable

from .asset_database_service import AssetDatabase, DerivedArtifact
from .asset_operations_service import AssetOperationsService, AssetValidationIssue
from .asset_type_registry import AssetTypeRegistry, builtin_asset_type_registry


@dataclass(frozen=True)
class AssetCookReceipt:
    root_asset_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    platform: str
    quality: str
    source_bytes: int
    artifact: DerivedArtifact
    hot_reload_classes: tuple[str, ...]


@dataclass(frozen=True)
class AssetAuditReport:
    asset_count: int
    source_bytes: int
    family_counts: dict[str, int]
    type_counts: dict[str, int]
    issues: tuple[AssetValidationIssue, ...]
    largest_assets: tuple[tuple[str, int], ...]

    @property
    def ready(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"ready": self.ready}


class AssetProductionService:
    def __init__(
        self,
        project_root: str | Path,
        database: AssetDatabase,
        registry: AssetTypeRegistry | None = None,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.database = database
        self.registry = registry or builtin_asset_type_registry()
        self.operations = AssetOperationsService(self.project_root, database, self.registry)

    def audit(self) -> AssetAuditReport:
        records = self.database.list_assets()
        family_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        issues: list[AssetValidationIssue] = []
        for record in records:
            descriptor = self.registry.descriptor(record.asset_type)
            family = descriptor.family if descriptor else "Unregistered"
            family_counts[family] = family_counts.get(family, 0) + 1
            type_counts[record.asset_type] = type_counts.get(record.asset_type, 0) + 1
            report = self.operations.validate_asset(record.asset_id)
            issues.extend(report.issues)
            if descriptor is not None and descriptor.hot_reload_class == "restart_required":
                issues.append(AssetValidationIssue(
                    "info", "restart_boundary", f"{record.source_path.name} requires a runtime restart after edits."
                ))
        largest = sorted(
            ((record.source_path.as_posix(), int(record.size)) for record in records),
            key=lambda item: item[1], reverse=True,
        )[:20]
        return AssetAuditReport(
            len(records), sum(int(record.size) for record in records),
            dict(sorted(family_counts.items())), dict(sorted(type_counts.items())),
            tuple(issues), tuple(largest),
        )

    def cook_manifest(
        self,
        root_asset_ids: Iterable[str],
        *,
        platform: str = "desktop",
        quality: str = "high",
    ) -> AssetCookReceipt:
        roots = tuple(dict.fromkeys(str(value) for value in root_asset_ids))
        if not roots:
            raise ValueError("At least one root asset is required for a cook manifest.")
        asset_ids = self.database.dependency_closure(roots)
        records = []
        hot_reload_classes: set[str] = set()
        for asset_id in asset_ids:
            record = self.database.asset(asset_id)
            if record is None or record.status != "ready":
                raise ValueError(f"Cook dependency is unavailable: {asset_id}")
            validation = self.operations.validate_asset(asset_id)
            errors = [issue.message for issue in validation.issues if issue.severity == "error"]
            if errors:
                raise ValueError(f"{record.source_path.name}: " + "; ".join(errors))
            descriptor = self.registry.descriptor(record.asset_type)
            hot_reload = descriptor.hot_reload_class if descriptor else "restart_required"
            hot_reload_classes.add(hot_reload)
            derived_outputs: list[dict[str, Any]] = []
            if record.asset_type in {"tc.material", "tc.material_instance"}:
                from .material_asset_service import MaterialService

                materials = MaterialService(self.project_root, self.database)
                material_artifact = materials.compile(
                    record.asset_id, platform=str(platform), quality=str(quality),
                )
                derived_outputs.append({
                    "kind": "material_runtime", "path": self._project_relative(material_artifact.path),
                    "content_hash": material_artifact.content_hash,
                })
            if record.asset_type == "tc.shader_graph":
                from .asset_graph_compile_service import AssetGraphCompileService

                shader_receipt = AssetGraphCompileService(self.database, self.registry).compile_asset(
                    record.asset_id, target=str(platform),
                )
                if not shader_receipt.succeeded:
                    errors = [item.message for item in shader_receipt.diagnostics if item.severity == "error"]
                    raise ValueError(f"{record.source_path.name}: " + "; ".join(errors))
                assert shader_receipt.artifact is not None
                derived_outputs.append({
                    "kind": "shader_runtime", "path": self._project_relative(shader_receipt.artifact.path),
                    "content_hash": shader_receipt.artifact.content_hash,
                })
            if record.asset_type == "tc.prefab":
                from .prefab_service import PrefabService, compile_prefab_payload

                prefabs = PrefabService(self.project_root, self.database)
                errors = [item.message for item in prefabs.validate(record.asset_id) if item.severity == "error"]
                if errors:
                    raise ValueError(f"{record.source_path.name}: " + "; ".join(errors))
                resolution = prefabs.resolve(record.asset_id, expand_nested=True)
                prefab_artifact = self.database.store_derived(
                    record.asset_id, f"prefab_runtime:{platform}:{quality}",
                    compile_prefab_payload(resolution, platform=str(platform), quality=str(quality)),
                    metadata={"platform": platform, "quality": quality, "fingerprint": resolution.fingerprint},
                    extension=".tcprefabbin",
                )
                derived_outputs.append({
                    "kind": "prefab_runtime", "path": self._project_relative(prefab_artifact.path),
                    "content_hash": prefab_artifact.content_hash,
                })
            if record.asset_type == "tc.cloth":
                from .cloth_asset_service import compile_cloth_payload

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    cooked_payload = compile_cloth_payload(
                        dict(source_payload.get("properties") or {}),
                        platform=str(platform), quality=str(quality),
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile cloth source: {exc}") from exc
                cloth_artifact = self.database.store_derived(
                    record.asset_id, f"cloth_runtime:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality, "preserved_imported_skinning": True},
                    extension=".tcclothbin",
                )
                derived_outputs.append({
                    "kind": "cloth_runtime", "path": self._project_relative(cloth_artifact.path),
                    "content_hash": cloth_artifact.content_hash,
                })
            if record.asset_type in {"tc.physics_asset", "tc.physics_constraint"}:
                from .physics_asset_service import compile_constraint_payload, compile_physics_asset_payload

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    compiler = compile_physics_asset_payload if record.asset_type == "tc.physics_asset" else compile_constraint_payload
                    cooked_payload = compiler(
                        dict(source_payload.get("properties") or {}), platform=str(platform), quality=str(quality),
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile physics source: {exc}") from exc
                kind = "physics_asset_runtime" if record.asset_type == "tc.physics_asset" else "physics_constraint_runtime"
                physics_artifact = self.database.store_derived(
                    record.asset_id, f"{kind}:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality}, extension=".tcphysicsbin",
                )
                derived_outputs.append({
                    "kind": kind, "path": self._project_relative(physics_artifact.path),
                    "content_hash": physics_artifact.content_hash,
                })
            if record.asset_type in {"tc.skeletal_mesh", "tc.skin_binding"}:
                from .character_asset_service import compile_skeletal_mesh_plan, compile_skin_binding_payload

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    compiler = compile_skeletal_mesh_plan if record.asset_type == "tc.skeletal_mesh" else compile_skin_binding_payload
                    cooked_payload = compiler(
                        dict(source_payload.get("properties") or {}), platform=str(platform), quality=str(quality),
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile character source: {exc}") from exc
                kind = "skeletal_mesh_plan" if record.asset_type == "tc.skeletal_mesh" else "skin_binding_runtime"
                extension = ".tcskmeshbin" if record.asset_type == "tc.skeletal_mesh" else ".tcskinbin"
                character_artifact = self.database.store_derived(
                    record.asset_id, f"{kind}:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality}, extension=extension,
                )
                derived_outputs.append({
                    "kind": kind, "path": self._project_relative(character_artifact.path),
                    "content_hash": character_artifact.content_hash,
                })
            if record.asset_type in {"tc.control_rig", "tc.ik_rig", "tc.ik_retargeter"}:
                from .rig_asset_service import compile_rig_asset_payload

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    cooked_payload = compile_rig_asset_payload(
                        record.asset_type, dict(source_payload.get("properties") or {}),
                        platform=str(platform), quality=str(quality),
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile rig source: {exc}") from exc
                kind = record.asset_type.removeprefix("tc.") + "_runtime"
                rig_artifact = self.database.store_derived(
                    record.asset_id, f"{kind}:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality}, extension=".tcrigbin",
                )
                derived_outputs.append({
                    "kind": kind, "path": self._project_relative(rig_artifact.path),
                    "content_hash": rig_artifact.content_hash,
                })
            if record.asset_type == "tc.geometry_optimization_profile":
                from .geometry_optimization_service import compile_geometry_optimization_payload

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    cooked_payload = compile_geometry_optimization_payload(
                        dict(source_payload.get("properties") or {}), platform=str(platform), quality=str(quality),
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile geometry optimization source: {exc}") from exc
                optimization_artifact = self.database.store_derived(
                    record.asset_id, f"geometry_optimization_plan:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality}, extension=".tcgeooptbin",
                )
                derived_outputs.append({
                    "kind": "geometry_optimization_plan", "path": self._project_relative(optimization_artifact.path),
                    "content_hash": optimization_artifact.content_hash,
                })
            if record.asset_type in {"tc.groom", "tc.groom_binding", "tc.hair_material"}:
                from .groom_asset_service import (
                    compile_groom_binding_payload, compile_groom_payload, compile_hair_material_payload,
                )

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    compiler, kind = {
                        "tc.groom": (compile_groom_payload, "groom_runtime"),
                        "tc.groom_binding": (compile_groom_binding_payload, "groom_binding_runtime"),
                        "tc.hair_material": (compile_hair_material_payload, "hair_material_runtime"),
                    }[record.asset_type]
                    cooked_payload = compiler(dict(source_payload.get("properties") or {}), platform=str(platform), quality=str(quality))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile Groom source: {exc}") from exc
                groom_artifact = self.database.store_derived(
                    record.asset_id, f"{kind}:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality}, extension=".tcgroombin",
                )
                derived_outputs.append({"kind": kind, "path": self._project_relative(groom_artifact.path),
                                        "content_hash": groom_artifact.content_hash})
            if record.asset_type in {"tc.animation_clip", "tc.blend_space", "tc.animation_mask", "tc.animation_controller"}:
                from .animation_asset_service import compile_animation_payload

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    cooked_payload = compile_animation_payload(
                        record.asset_type, dict(source_payload.get("properties") or {}),
                        platform=str(platform), quality=str(quality),
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile animation source: {exc}") from exc
                kind = record.asset_type.removeprefix("tc.") + "_runtime"
                animation_artifact = self.database.store_derived(
                    record.asset_id, f"{kind}:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality}, extension=".tcanim",
                )
                derived_outputs.append({"kind": kind, "path": self._project_relative(animation_artifact.path),
                                        "content_hash": animation_artifact.content_hash})
            if record.asset_type == "tc.level_sequence":
                from .sequence_asset_service import SequenceAssetService

                sequence_artifact = SequenceAssetService(self.project_root, self.database).cook(
                    record.asset_id, platform=str(platform), quality=str(quality),
                )
                derived_outputs.append({"kind": "level_sequence_runtime",
                                        "path": self._project_relative(sequence_artifact.path),
                                        "content_hash": sequence_artifact.content_hash})
            if record.asset_type == "tc.effect_system":
                from .effect_asset_service import compile_effect_payload

                try:
                    source_payload = json.loads(record.source_path.read_text(encoding="utf-8"))
                    cooked_payload = compile_effect_payload(
                        dict(source_payload.get("properties") or {}),
                        platform=str(platform), quality=str(quality),
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"{record.source_path.name}: could not compile effect source: {exc}") from exc
                effect_artifact = self.database.store_derived(
                    record.asset_id, f"effect_runtime:{platform}:{quality}", cooked_payload,
                    metadata={"platform": platform, "quality": quality}, extension=".tcfxbin",
                )
                derived_outputs.append({"kind": "effect_runtime", "path": self._project_relative(effect_artifact.path),
                                        "content_hash": effect_artifact.content_hash})
            if record.asset_type in {"tc.audio_clip", "tc.sound_cue", "tc.audio_mixer", "tc.audio_attenuation", "tc.audio_reverb"}:
                from .audio_asset_service import AudioAssetService

                audio = AudioAssetService(self.project_root, self.database)
                audio_artifact = audio.cook(record.asset_id, platform=str(platform), quality=str(quality))
                derived_outputs.append({"kind": record.asset_type.removeprefix("tc.") + "_runtime",
                                        "path": self._project_relative(audio_artifact.path),
                                        "content_hash": audio_artifact.content_hash})
            if record.asset_type in {"tc.project_settings", "tc.data_schema", "tc.struct", "tc.enum", "tc.data", "tc.data_table", "tc.component_archetype", "tc.character_definition"}:
                from .gameplay_foundation_service import GameplayFoundationService

                foundation_artifact = GameplayFoundationService(self.project_root, self.database).cook(
                    record.asset_id, platform=str(platform), quality=str(quality),
                )
                derived_outputs.append({"kind": record.asset_type.removeprefix("tc.") + "_runtime",
                                        "path": self._project_relative(foundation_artifact.path),
                                        "content_hash": foundation_artifact.content_hash})
            if record.asset_type == "tc.gameplay_class":
                from .gameplay_class_service import GameplayClassService

                class_artifact = GameplayClassService(self.project_root, self.database).compile(
                    record.asset_id, platform=str(platform), quality=str(quality),
                )
                derived_outputs.append({"kind": "gameplay_class_runtime",
                                        "path": self._project_relative(class_artifact.path),
                                        "content_hash": class_artifact.content_hash})
            if record.asset_type in {
                "tc.terrain", "tc.foliage_type", "tc.biome", "tc.navigation_mesh",
                "tc.lighting_scenario", "tc.data_layer", "tc.hlod_layer", "tc.world_partition",
            }:
                from .world_asset_service import WorldAssetService

                world_artifact = WorldAssetService(self.project_root, self.database).compile(
                    record.asset_id, platform=str(platform), quality=str(quality),
                )
                derived_outputs.append({"kind": record.asset_type.removeprefix("tc.") + "_runtime",
                                        "path": self._project_relative(world_artifact.path),
                                        "content_hash": world_artifact.content_hash})
                if record.asset_type in {"tc.terrain", "tc.navigation_mesh", "tc.lighting_scenario", "tc.hlod_layer", "tc.world_partition"}:
                    from .world_build_service import WorldBuildService

                    built = WorldBuildService(self.project_root, self.database).build(
                        record.asset_id, platform=str(platform), quality=str(quality),
                    )
                    derived_outputs.append({"kind": built.build_kind,
                                            "path": self._project_relative(built.artifact.path),
                                            "content_hash": built.artifact.content_hash})
            if record.asset_type == "tc.procedural_graph":
                from .procedural_graph_asset_service import ProceduralGraphAssetService

                procedural_artifact = ProceduralGraphAssetService(self.project_root, self.database).cook(
                    record.asset_id, platform=str(platform), quality=str(quality),
                )
                derived_outputs.append({"kind": "procedural_geometry_runtime",
                                        "path": self._project_relative(procedural_artifact.path),
                                        "content_hash": procedural_artifact.content_hash})
            records.append({
                "asset_id": record.asset_id,
                "type_id": record.asset_type,
                "source": self._project_relative(record.source_path),
                "content_hash": record.content_hash,
                "revision": record.revision,
                "source_bytes": record.size,
                "dependencies": [
                    {"asset_id": dependency, "kind": kind}
                    for dependency, kind in self.database.dependency_edges(record.asset_id)
                ],
                "loader": descriptor.runtime_loader_id if descriptor else "none",
                "cooker": descriptor.cooker_id if descriptor else "none",
                "hot_reload": hot_reload,
                "derived_outputs": derived_outputs,
            })
        payload = json.dumps({
            "schema": "tech_connector.asset_cook_manifest.v1",
            "platform": str(platform), "quality": str(quality),
            "roots": list(roots), "assets": records,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        owner = roots[0]
        artifact = self.database.store_derived(
            owner, f"cook_manifest:{platform}:{quality}", payload,
            metadata={"roots": roots, "asset_count": len(records), "platform": platform, "quality": quality},
            extension=".tcmanifest",
        )
        return AssetCookReceipt(
            roots, asset_ids, str(platform), str(quality),
            sum(int(item["source_bytes"]) for item in records), artifact,
            tuple(sorted(hot_reload_classes)),
        )

    def _project_relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return str(path.resolve())
